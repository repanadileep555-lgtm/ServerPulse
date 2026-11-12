import sqlite3
import unittest
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient

from app.auth.jwt_service import JWTService, get_jwt_service
from app.db.db_pool import DatabasePool
from app.main import app
from app.schemas.monitoring import utc_text
from db.migrate import migrate


class ServiceInventoryTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = self.enterContext(TemporaryDirectory())
        self.path = Path(directory) / "services.db"
        migrate(self.path)
        with closing(sqlite3.connect(self.path)) as con:
            con.execute("INSERT INTO users(id,username,password_hash,is_admin) VALUES (1,'owner','unused',0)")
            con.commit()
        jwt = JWTService("services-test-secret-longer-than-thirty-two", "HS256", 30)
        app.dependency_overrides[get_jwt_service] = lambda: jwt
        self.addCleanup(app.dependency_overrides.pop, get_jwt_service)
        self.owner = {"Authorization": f"Bearer {jwt.create_access_token('1')}"}
        self.enterContext(patch("app.main.DatabasePool", return_value=DatabasePool(self.path)))
        self.client = self.enterContext(TestClient(app))

    def register(self, name: str, platform: str) -> tuple[int, dict]:
        registered = self.client.post(
            "/hosts", headers=self.owner,
            json={"name": name, "platform": platform, "deployment_type": "external"},
        )
        self.assertEqual(registered.status_code, 201, registered.text)
        collector = {"Authorization": f"Bearer {registered.json()['collector_token']}"}
        return registered.json()["host"]["id"], collector

    def batch(self, platform: str, services: list[dict], batch_id: str | None = None) -> dict:
        return {
            "batch_id": batch_id or str(uuid4()), "platform": platform,
            "collected_at": utc_text(datetime.now(UTC)), "services": services,
        }

    def list_services(self, host_id: int) -> list[dict]:
        return self.client.get(f"/hosts/{host_id}/services", headers=self.owner).json()

    def test_windows_services_are_identified_with_state_and_survive_resync(self) -> None:
        host_id, collector = self.register("win-01", "windows")
        first = self.batch("windows", [
            {"service_name": "Spooler", "display_name": "Print Spooler",
             "current_state": "running", "native_state": "Running"},
            {"service_name": "WSearch", "current_state": "stopped", "native_state": "Stopped"},
        ])
        response = self.client.post("/collector/services", headers=collector, json=first)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"accepted": 2, "duplicate": False})

        replay = self.client.post("/collector/services", headers=collector, json=first)
        self.assertEqual(replay.json()["duplicate"], True)
        changed = {**first, "services": first["services"][:1]}
        self.assertEqual(self.client.post("/collector/services", headers=collector, json=changed).status_code, 409)

        second = self.batch("windows", [
            {"service_name": "Spooler", "display_name": "Print Spooler",
             "current_state": "stopped", "native_state": "Stopped"},
        ])
        self.assertEqual(self.client.post("/collector/services", headers=collector, json=second).status_code, 200)

        services = {service["service_name"]: service for service in self.list_services(host_id)}
        self.assertEqual(set(services), {"Spooler", "WSearch"})
        self.assertEqual(services["Spooler"]["current_state"], "stopped")
        self.assertEqual(services["Spooler"]["display_name"], "Print Spooler")
        self.assertEqual(services["Spooler"]["last_status"], "ok")
        self.assertIsNotNone(services["Spooler"]["last_checked_at"])
        self.assertEqual(services["WSearch"]["current_state"], "stopped")

    def test_linux_inventory_links_with_journald_units_without_losing_state(self) -> None:
        host_id, collector = self.register("web-01", "linux")
        inventory = self.batch("linux", [
            {"service_name": "nginx.service", "display_name": "A high performance web server",
             "current_state": "running", "native_state": "active/running"},
        ])
        self.assertEqual(self.client.post("/collector/services", headers=collector, json=inventory).status_code, 200)

        now = datetime.now(UTC)
        logs = self.batch("linux", [])
        logs = {
            "batch_id": str(uuid4()), "platform": "linux", "collected_at": utc_text(now),
            "sources": [{"source_type": "journald", "category": "system", "channel": "journal", "status": "ok",
                         "checkpoint": "cursor-1"}],
            "records": [{"source_type": "journald", "category": "system", "channel": "journal",
                         "source_record_id": "c-1", "occurred_at": utc_text(now - timedelta(minutes=1)),
                         "timestamp_quality": "native", "severity": "error", "message": "nginx failed",
                         "unit": "nginx.service"}],
        }
        self.assertEqual(self.client.post("/collector/logs", headers=collector, json=logs).status_code, 200)

        services = self.list_services(host_id)
        self.assertEqual([(s["service_name"], s["current_state"], s["log_count"]) for s in services],
                         [("nginx.service", "running", 1)])

    def test_inventory_platform_must_match_host(self) -> None:
        _, collector = self.register("web-02", "linux")
        payload = self.batch("windows", [{"service_name": "Spooler", "current_state": "running"}])
        self.assertEqual(self.client.post("/collector/services", headers=collector, json=payload).status_code, 422)


if __name__ == "__main__":
    unittest.main()
