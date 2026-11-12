import sqlite3
import tarfile
import unittest
from contextlib import closing
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.auth.jwt_service import JWTService, get_jwt_service
from app.db.db_pool import DatabasePool
from app.main import app
from app.services import ssh_collector
from app.services.secret_box import SecretBox
from db.migrate import migrate

FINGERPRINT = "SHA256:AbCdEf0123456789"
PASSWORD = "correct-horse-battery"


class FakeKey:
    algorithm = "ssh-ed25519"

    def get_fingerprint(self) -> str:
        return FINGERPRINT

    def export_public_key(self) -> bytes:
        return b"ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFake\n"


class FakeConnection:
    def __init__(self, os_name: str = "Linux", fail_on: str | None = None) -> None:
        self.os_name = os_name
        self.fail_on = fail_on
        self.commands: list[tuple[str, bytes | None]] = []
        self.closed = False

    async def run(self, command: str, check: bool = False, input: bytes | None = None, timeout=None):
        self.commands.append((command, input))
        if "uname" in command:
            return SimpleNamespace(exit_status=0, stdout=f"{self.os_name}\n", stderr="")
        if "sys.version_info" in command:
            return SimpleNamespace(exit_status=0, stdout="3 11\n", stderr="")
        if self.fail_on and self.fail_on in command:
            return SimpleNamespace(exit_status=1, stdout="", stderr="pip: network unreachable")
        return SimpleNamespace(exit_status=0, stdout="", stderr="")

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        return None


class SSHCollectorTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = self.enterContext(TemporaryDirectory())
        self.path = Path(directory) / "ssh.db"
        migrate(self.path)
        with closing(sqlite3.connect(self.path)) as con:
            con.execute("INSERT INTO users(id,username,password_hash,is_admin) VALUES (1,'admin','unused',1)")
            con.execute("INSERT INTO users(id,username,password_hash,is_admin) VALUES (2,'owner','unused',0)")
            con.execute("INSERT INTO users(id,username,password_hash,is_admin) VALUES (3,'other','unused',0)")
            con.commit()
        jwt = JWTService("ssh-test-secret-longer-than-thirty-two", "HS256", 30)
        app.dependency_overrides[get_jwt_service] = lambda: jwt
        self.addCleanup(app.dependency_overrides.pop, get_jwt_service)
        self.owner = {"Authorization": f"Bearer {jwt.create_access_token('2')}"}
        self.other = {"Authorization": f"Bearer {jwt.create_access_token('3')}"}
        self.admin = {"Authorization": f"Bearer {jwt.create_access_token('1')}"}
        self.enterContext(patch("app.main.DatabasePool", return_value=DatabasePool(self.path)))
        self.client = self.enterContext(TestClient(app))
        self.enterContext(patch.object(ssh_collector, "get_secret_box",
                                       return_value=SecretBox(Path(directory) / "credential.key")))
        self.supervisor = self.enterContext(patch.object(ssh_collector.ssh_supervisors, "ensure"))
        self.enterContext(patch.object(ssh_collector, "_fetch_host_key", AsyncMock(return_value=FakeKey())))
        self.connection = FakeConnection()
        self.enterContext(patch.object(ssh_collector, "_open", AsyncMock(return_value=self.connection)))

    def install_body(self, **overrides) -> dict:
        body = {
            "name": "remote-web", "address": "203.0.113.10", "port": 22, "username": "deploy",
            "auth_method": "password", "secret": PASSWORD, "host_key_fingerprint": FINGERPRINT,
            "long_running_seconds": 3600,
        }
        body.update(overrides)
        return body

    def host_count(self) -> int:
        with closing(sqlite3.connect(self.path)) as con:
            return con.execute("SELECT COUNT(*) FROM hosts").fetchone()[0]

    def test_admins_cannot_scan_or_install_over_ssh(self) -> None:
        self.assertEqual(self.client.post("/hosts/ssh/scan", headers=self.admin,
                                          json={"address": "203.0.113.10", "port": 22}).status_code, 403)
        self.assertEqual(self.client.post("/hosts/ssh", headers=self.admin,
                                          json=self.install_body()).status_code, 403)
        self.assertEqual(self.host_count(), 0)

    def test_install_rejects_a_changed_host_key_without_creating_a_host(self) -> None:
        response = self.client.post("/hosts/ssh", headers=self.owner,
                                    json=self.install_body(host_key_fingerprint="SHA256:Other"))
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(self.host_count(), 0)

    def test_install_rejects_non_linux_servers(self) -> None:
        self.connection.os_name = "Darwin"
        response = self.client.post("/hosts/ssh", headers=self.owner, json=self.install_body())
        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(self.host_count(), 0)

    def test_install_stores_the_secret_encrypted_and_hands_the_token_over_stdin(self) -> None:
        response = self.client.post("/hosts/ssh", headers=self.owner, json=self.install_body())
        self.assertEqual(response.status_code, 201, response.text)
        body = response.json()
        self.assertEqual(body["host"]["deployment_type"], "external")
        self.assertEqual(body["ssh"]["connected"], False)
        self.assertNotIn("collector_token", body)
        self.supervisor.assert_called_once()

        with closing(sqlite3.connect(self.path)) as con:
            stored = con.execute("SELECT encrypted_secret, host_key, remote_dir FROM ssh_collectors").fetchone()
        self.assertNotIn(PASSWORD, stored[0])
        self.assertEqual(SecretBox(Path(self.path).parent / "credential.key").decrypt(stored[0]), PASSWORD)
        self.assertEqual(stored[1], "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFake")

        token_writes = [data for command, data in self.connection.commands if "/token" in command]
        self.assertEqual(len(token_writes), 1)
        self.assertTrue(all(token_writes[0].decode() not in command for command, _ in self.connection.commands))
        self.assertTrue(self.connection.closed)

    def test_failed_remote_setup_removes_the_registered_host(self) -> None:
        self.connection.fail_on = "pip install"
        response = self.client.post("/hosts/ssh", headers=self.owner, json=self.install_body())
        self.assertEqual(response.status_code, 502, response.text)
        self.assertIn("network unreachable", response.text)
        self.assertEqual(self.host_count(), 0)
        self.supervisor.assert_not_called()

    def test_bundle_pins_the_remote_port_and_ships_the_collector(self) -> None:
        self.client.post("/hosts/ssh", headers=self.owner, json=self.install_body())
        deployed = next(data for command, data in self.connection.commands if "tar -xf" in command)
        with tarfile.open(fileobj=BytesIO(deployed)) as archive:
            names = archive.getnames()
            script = archive.extractfile("run.sh").read().decode()
        self.assertEqual(set(names), {"app/__init__.py", "app/collector.py", "app/schemas/monitoring.py", "run.sh"})
        self.assertIn("--allow-http", script)
        self.assertRegex(script, r"http://127\.0\.0\.1:\d+")

    def test_other_owners_cannot_see_or_control_an_ssh_collector(self) -> None:
        host_id = self.client.post("/hosts/ssh", headers=self.owner, json=self.install_body()).json()["host"]["id"]
        self.assertEqual(self.client.get(f"/hosts/{host_id}/ssh-collector", headers=self.other).status_code, 404)
        self.assertEqual(self.client.post(f"/hosts/{host_id}/ssh-collector/stop", headers=self.other).status_code, 404)
        self.assertEqual(self.client.get(f"/hosts/{host_id}/ssh-collector", headers=self.admin).status_code, 200)

    def test_owner_start_rotates_the_token_and_restarts_the_remote_collector(self) -> None:
        host_id = self.client.post("/hosts/ssh", headers=self.owner, json=self.install_body()).json()["host"]["id"]
        installed = next(data for command, data in self.connection.commands if command.endswith("/token"))
        self.connection.commands.clear()

        response = self.client.post(f"/hosts/{host_id}/ssh-collector/start", headers=self.owner)
        self.assertEqual(response.status_code, 200, response.text)
        commands = [command for command, _ in self.connection.commands]
        stop_index = next(i for i, c in enumerate(commands) if "collector.pid" in c and "kill" in c)
        token_index = next(i for i, c in enumerate(commands) if c.endswith("/token"))
        run_index = next(i for i, c in enumerate(commands) if c.endswith("run.sh"))
        self.assertLess(stop_index, token_index)
        self.assertLess(token_index, run_index)
        new_token = self.connection.commands[token_index][1]
        self.assertNotEqual(new_token, installed)

    def test_stop_marks_the_collector_stopped_even_when_the_server_is_unreachable(self) -> None:
        host_id = self.client.post("/hosts/ssh", headers=self.owner, json=self.install_body()).json()["host"]["id"]
        with patch.object(ssh_collector, "_open", AsyncMock(side_effect=ssh_collector.HTTPException(502, "down"))):
            response = self.client.post(f"/hosts/{host_id}/ssh-collector/stop", headers=self.owner)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["ssh"]["desired_state"], "stopped")
        self.assertFalse(response.json()["remote_stopped"])
