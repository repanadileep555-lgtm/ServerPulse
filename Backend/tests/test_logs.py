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


class LogIngestionTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = self.enterContext(TemporaryDirectory())
        self.path = Path(directory) / "logs.db"
        migrate(self.path)
        with closing(sqlite3.connect(self.path)) as con:
            con.execute("INSERT INTO users(id,username,password_hash,is_admin) VALUES (1,'owner','unused',0)")
            con.execute("INSERT INTO users(id,username,password_hash,is_admin) VALUES (2,'other','unused',0)")
            con.commit()
        jwt = JWTService("logs-test-secret-longer-than-thirty-two", "HS256", 30)
        app.dependency_overrides[get_jwt_service] = lambda: jwt
        self.addCleanup(app.dependency_overrides.pop, get_jwt_service)
        self.owner = {"Authorization": f"Bearer {jwt.create_access_token('1')}"}
        self.other = {"Authorization": f"Bearer {jwt.create_access_token('2')}"}
        self.enterContext(patch("app.main.DatabasePool", return_value=DatabasePool(self.path)))
        self.client = self.enterContext(TestClient(app))
        registered = self.client.post(
            "/hosts", headers=self.owner,
            json={"name": "web-01", "platform": "linux", "deployment_type": "external"},
        )
        self.assertEqual(registered.status_code, 201, registered.text)
        self.host_id = registered.json()["host"]["id"]
        self.collector = {"Authorization": f"Bearer {registered.json()['collector_token']}"}

    def record(self, record_id: str, severity: str, message: str, occurred: datetime) -> dict:
        return {
            "source_type": "journald", "category": "system", "channel": "journal",
            "source_record_id": record_id, "occurred_at": utc_text(occurred),
            "timestamp_quality": "native", "severity": severity, "message": message,
        }

    def batch(self, records: list[dict], batch_id: str | None = None) -> dict:
        return {
            "batch_id": batch_id or str(uuid4()), "platform": "linux",
            "collected_at": utc_text(datetime.now(UTC)),
            "sources": [{"source_type": "journald", "category": "system", "channel": "journal",
                         "status": "ok", "checkpoint": "cursor-2"}],
            "records": records,
        }

    def send(self, payload: dict):
        return self.client.post("/collector/logs", headers=self.collector, json=payload)

    def test_duplicate_batches_are_idempotent_and_records_dedupe_by_source_record(self) -> None:
        now = datetime.now(UTC)
        first = self.batch([
            self.record("c-1", "info", "started", now - timedelta(minutes=2)),
            self.record("c-2", "error", "disk full", now - timedelta(minutes=1)),
        ])
        response = self.send(first)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"accepted": 2, "duplicates": 0, "duplicate": False})

        replay = self.send(first)
        self.assertEqual(replay.json()["duplicate"], True)

        changed = {**first, "records": first["records"][:1]}
        self.assertEqual(self.send(changed).status_code, 409)

        overlap = self.batch([self.record("c-2", "error", "disk full", now - timedelta(minutes=1))])
        self.assertEqual(self.send(overlap).json(), {"accepted": 0, "duplicates": 1, "duplicate": False})

    def test_windows_batches_are_rejected_for_linux_hosts(self) -> None:
        payload = self.batch([])
        payload["platform"] = "windows"
        payload["sources"][0]["source_type"] = "windows_eventlog"
        response = self.send(payload)
        self.assertEqual(response.status_code, 422, response.text)

    def test_log_queries_filter_by_severity_keyword_and_stay_within_owner_scope(self) -> None:
        now = datetime.now(UTC)
        self.send(self.batch([
            self.record("c-1", "debug", "verbose noise", now - timedelta(minutes=3)),
            self.record("c-2", "warning", "Disk nearly full", now - timedelta(minutes=2)),
            self.record("c-3", "critical", "kernel panic", now - timedelta(minutes=1)),
        ]))

        errors = self.client.get(
            f"/hosts/{self.host_id}/logs", headers=self.owner, params={"min_severity": "warning"},
        ).json()
        self.assertEqual(errors["total"], 2)
        self.assertEqual([item["message"] for item in errors["items"]], ["kernel panic", "Disk nearly full"])

        keyword = self.client.get(
            f"/hosts/{self.host_id}/logs", headers=self.owner, params={"keyword": "DISK"},
        ).json()
        self.assertEqual(keyword["total"], 1)

        sources = self.client.get(f"/hosts/{self.host_id}/log-sources", headers=self.owner).json()
        self.assertEqual(sources[0]["last_status"], "ok")
        source_filtered = self.client.get(
            f"/hosts/{self.host_id}/logs", headers=self.owner, params={"source_id": sources[0]["id"]},
        ).json()
        self.assertEqual(source_filtered["total"], 3)

        self.assertEqual(
            self.client.get(f"/hosts/{self.host_id}/logs", headers=self.other).status_code, 404,
        )
        self.assertEqual(
            self.client.get(f"/hosts/{self.host_id}/logs", headers=self.owner,
                            params={"since": "2020-01-01T00:00:00"}).status_code, 422,
        )
    def test_journald_service_units_link_to_services_and_log_batches_count_as_heartbeat(self) -> None:
        now = datetime.now(UTC)
        service_record = {**self.record("c-1", "error", "nginx failed", now - timedelta(minutes=1)),
                          "unit": "nginx.service"}
        scope_record = {**self.record("c-2", "info", "session opened", now), "unit": "user@1000.scope"}
        self.assertEqual(self.send(self.batch([service_record, scope_record])).status_code, 200)

        items = self.client.get(f"/hosts/{self.host_id}/logs", headers=self.owner).json()["items"]
        by_message = {item["message"]: item for item in items}
        self.assertEqual(by_message["nginx failed"]["service_name"], "nginx.service")
        self.assertIsNone(by_message["session opened"]["service_id"])

        with closing(sqlite3.connect(self.path)) as con:
            heartbeat = con.execute("SELECT last_heartbeat_at FROM hosts WHERE id = ?", (self.host_id,)).fetchone()
        self.assertIsNotNone(heartbeat[0])

        services = self.client.get(f"/hosts/{self.host_id}/services", headers=self.owner).json()
        self.assertEqual([(s["service_name"], s["log_count"]) for s in services], [("nginx.service", 1)])
        self.assertEqual(services[0]["current_state"], "unknown")

    def test_scm_events_link_to_windows_services_by_display_name(self) -> None:
        registered = self.client.post(
            "/hosts", headers=self.owner,
            json={"name": "win-01", "platform": "windows", "deployment_type": "external"},
        )
        self.assertEqual(registered.status_code, 201, registered.text)
        host_id = registered.json()["host"]["id"]
        collector = {"Authorization": f"Bearer {registered.json()['collector_token']}"}
        with closing(sqlite3.connect(self.path)) as con:
            con.execute("INSERT INTO monitored_services(host_id, service_name, display_name) VALUES (?,?,?)",
                        (host_id, "Spooler", "Print Spooler"))
            con.commit()

        now = datetime.now(UTC)

        def scm_event(record_id: str, reference: str, message: str) -> dict:
            return {"source_type": "windows_eventlog", "category": "system", "channel": "System",
                    "source_record_id": record_id, "occurred_at": utc_text(now),
                    "timestamp_quality": "native", "severity": "info", "event_id": 7036,
                    "provider": "Service Control Manager", "service_reference": reference, "message": message}

        payload = {
            "batch_id": str(uuid4()), "platform": "windows", "collected_at": utc_text(now),
            "sources": [{"source_type": "windows_eventlog", "category": "system", "channel": "System",
                         "status": "ok", "checkpoint": "2"}],
            "records": [scm_event("1", "print spooler", "Print Spooler entered the running state."),
                        scm_event("2", "Unknown Service", "Unknown Service entered the stopped state.")],
        }
        self.assertEqual(self.client.post("/collector/logs", headers=collector, json=payload).status_code, 200)

        items = self.client.get(f"/hosts/{host_id}/logs", headers=self.owner).json()["items"]
        by_message = {item["message"]: item for item in items}
        self.assertEqual(by_message["Print Spooler entered the running state."]["service_name"], "Spooler")
        self.assertIsNone(by_message["Unknown Service entered the stopped state."]["service_id"])

        services = self.client.get(f"/hosts/{host_id}/services", headers=self.owner).json()
        self.assertEqual([(s["service_name"], s["log_count"]) for s in services], [("Spooler", 1)])


if __name__ == "__main__":
    unittest.main()
