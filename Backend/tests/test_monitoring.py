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
from db.migrate import migrate, rollback


class MonitoringTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = self.enterContext(TemporaryDirectory())
        self.path = Path(directory) / "monitor.db"
        migrate(self.path)
        with closing(sqlite3.connect(self.path)) as con:
            con.execute(
                "INSERT INTO users(id,username,password_hash,is_admin) VALUES (1,'admin','unused',1)"
            )
            con.execute(
                "INSERT INTO users(id,username,password_hash,is_admin) VALUES (2,'viewer','unused',0)"
            )
            con.commit()
        jwt = JWTService("monitoring-test-secret-longer-than-thirty-two", "HS256", 30)
        app.dependency_overrides[get_jwt_service] = lambda: jwt
        self.addCleanup(app.dependency_overrides.pop, get_jwt_service)
        self.admin = {"Authorization": f"Bearer {jwt.create_access_token('1')}"}
        self.viewer = {"Authorization": f"Bearer {jwt.create_access_token('2')}"}
        self.enterContext(patch("app.main.DatabasePool", return_value=DatabasePool(self.path)))
        self.client = self.enterContext(TestClient(app))
        registered = self.client.post(
            "/hosts", headers=self.viewer,
            json={"name": "WSL", "platform": "linux", "deployment_type": "wsl", "wsl_distro": "Ubuntu"},
        )
        self.assertEqual(registered.status_code, 201, registered.text)
        self.host_id = registered.json()["host"]["id"]
        self.collector = {"Authorization": f"Bearer {registered.json()['collector_token']}"}

    def batch(self, sampled_at: datetime | None = None) -> dict:
        now = sampled_at or datetime.now(UTC)
        return {
            "batch_id": str(uuid4()), "platform": "linux", "sampled_at": utc_text(now),
            "cpu_percent": 23, "memory_total_bytes": 1000, "memory_available_bytes": 400,
            "denied_count": 1, "vanished_count": 2,
            "processes": [
                {"pid": 42, "create_time": utc_text(now - timedelta(hours=2)), "name": "worker",
                 "status": "sleeping", "cpu_percent": 12, "rss_bytes": 200, "memory_percent": 20},
                {"pid": 43, "create_time": utc_text(now - timedelta(minutes=5)), "name": "orphan",
                 "status": "zombie"},
                {"pid": 44, "access_denied": True},
            ],
        }

    def send(self, batch: dict):
        return self.client.post("/collector/snapshots", headers=self.collector, json=batch)

    def test_hosts_are_scoped_to_their_owner_and_names_are_unique_per_owner(self) -> None:
        with closing(sqlite3.connect(self.path)) as con:
            con.execute("INSERT INTO users(id,username,password_hash,is_admin) VALUES (3,'other','unused',0)")
            con.commit()
        jwt = app.dependency_overrides[get_jwt_service]()
        other = {"Authorization": f"Bearer {jwt.create_access_token('3')}"}

        self.assertEqual(self.client.get("/hosts", headers=other).json(), [])
        self.assertEqual(self.client.get(f"/hosts/{self.host_id}/monitoring", headers=other).status_code, 404)
        self.assertEqual(self.client.get(f"/hosts/{self.host_id}/processes", headers=other).status_code, 404)

        self.assertEqual(len(self.client.get("/hosts", headers=self.admin).json()), 1)
        self.assertEqual(self.client.get(f"/hosts/{self.host_id}/monitoring", headers=self.admin).status_code, 200)

        same_name = self.client.post("/hosts", headers=other, json={
            "name": "WSL", "platform": "linux", "deployment_type": "wsl", "wsl_distro": "Ubuntu",
        })
        self.assertEqual(same_name.status_code, 201, same_name.text)
        duplicate = self.client.post("/hosts", headers=other, json={
            "name": "WSL", "platform": "linux", "deployment_type": "wsl", "wsl_distro": "Ubuntu",
        })
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(len(self.client.get("/hosts", headers=other).json()), 1)
        self.assertEqual(len(self.client.get("/hosts", headers=self.admin).json()), 2)

    def test_duplicate_local_wsl_and_external_machines_are_rejected_per_user(self) -> None:
        local = {"name": "Local", "platform": "windows", "deployment_type": "localhost"}
        self.assertEqual(self.client.post("/hosts", headers=self.viewer, json=local).status_code, 201)
        second_local = self.client.post("/hosts", headers=self.viewer, json={**local, "name": "Local-2"})
        self.assertEqual(second_local.status_code, 409)
        self.assertEqual(second_local.json()["detail"], "This machine is already registered")

        wsl = {"name": "Ubuntu", "platform": "linux", "deployment_type": "wsl", "wsl_distro": "Ubuntu-22"}
        self.assertEqual(self.client.post("/hosts", headers=self.viewer, json=wsl).status_code, 201)
        renamed_wsl = self.client.post("/hosts", headers=self.viewer, json={**wsl, "name": "Ubuntu-copy"})
        self.assertEqual(renamed_wsl.status_code, 409)
        self.assertEqual(renamed_wsl.json()["detail"], "This machine is already registered")

        external = {"name": "Server1", "platform": "linux", "deployment_type": "external"}
        self.assertEqual(self.client.post("/hosts", headers=self.viewer, json=external).status_code, 201)
        self.assertEqual(self.client.post("/hosts", headers=self.viewer, json=external).status_code, 409)

        with closing(sqlite3.connect(self.path)) as con:
            con.execute("INSERT INTO users(id,username,password_hash,is_admin) VALUES (3,'other','unused',0)")
            con.commit()
        jwt = app.dependency_overrides[get_jwt_service]()
        other = {"Authorization": f"Bearer {jwt.create_access_token('3')}"}
        self.assertEqual(self.client.post("/hosts", headers=other, json=local).status_code, 201)
        self.assertEqual(self.client.post("/hosts", headers=other, json=wsl).status_code, 201)

    def test_local_collector_runs_only_for_owned_localhost_hosts(self) -> None:
        local = self.client.post("/hosts", headers=self.viewer, json={
            "name": "Local", "platform": "linux", "deployment_type": "localhost",
        })
        self.assertEqual(local.status_code, 201, local.text)
        local_id = local.json()["host"]["id"]
        with closing(sqlite3.connect(self.path)) as con:
            con.execute("INSERT INTO users(id,username,password_hash,is_admin) VALUES (3,'other','unused',0)")
            con.commit()
        jwt = app.dependency_overrides[get_jwt_service]()
        other = {"Authorization": f"Bearer {jwt.create_access_token('3')}"}

        self.assertEqual(
            self.client.post(f"/hosts/{self.host_id}/local-collector/start", headers=self.viewer).status_code, 400
        )
        self.assertEqual(
            self.client.post(f"/hosts/{local_id}/local-collector/start", headers=other).status_code, 404
        )

        with patch("app.services.local_collector.subprocess.Popen") as popen:
            popen.return_value.pid = 4321
            popen.return_value.poll.return_value = None
            started = self.client.post(f"/hosts/{local_id}/local-collector/start", headers=self.viewer)
            self.assertEqual(started.status_code, 200, started.text)
            self.assertEqual(started.json(), {"running": True, "pid": 4321, "source": "server"})
            self.assertEqual(popen.call_count, 1)
            new_token = popen.call_args.kwargs["env"]["SERVERPULSE_COLLECTOR_TOKEN"]
            self.assertIn("app.collector", popen.call_args.args[0])
            self.assertIn("--logs", popen.call_args.args[0])

            again = self.client.post(f"/hosts/{local_id}/local-collector/start", headers=self.viewer)
            self.assertEqual(again.json(), {"running": True, "pid": 4321, "source": "server"})
            self.assertEqual(popen.call_count, 1)
            self.assertEqual(
                self.client.get(f"/hosts/{local_id}/local-collector", headers=self.viewer).json(),
                {"running": True, "pid": 4321, "source": "server"},
            )

            stopped = self.client.post(f"/hosts/{local_id}/local-collector/stop", headers=self.viewer)
            self.assertEqual(stopped.json(), {"running": False, "pid": None, "source": None})
            popen.return_value.terminate.assert_called_once()

        with closing(sqlite3.connect(self.path)) as con:
            con.execute("UPDATE hosts SET last_heartbeat_at = ? WHERE id = ?", (utc_text(datetime.now(UTC)), local_id))
            con.commit()
        with patch("app.services.monitoring_service.find_external_collector_pid", return_value=777):
            external = self.client.get(f"/hosts/{local_id}/local-collector", headers=self.viewer)
            self.assertEqual(external.json(), {"running": True, "pid": 777, "source": "external"})
            stop_external = self.client.post(f"/hosts/{local_id}/local-collector/stop", headers=self.viewer)
            self.assertEqual(stop_external.status_code, 409)

        new_credential = {"Authorization": f"Bearer {new_token}"}
        self.assertEqual(self.client.post("/collector/snapshots", headers=new_credential,
                                          json=self.batch()).status_code, 200)
        old_credential = {"Authorization": f"Bearer {local.json()['collector_token']}"}
        self.assertEqual(self.client.post("/collector/snapshots", headers=old_credential,
                                          json=self.batch()).status_code, 401)


        payload = self.batch()
        response = self.send(payload)
        self.assertEqual(response.status_code, 200, response.text)
        duplicate = self.send(payload)
        self.assertTrue(duplicate.json()["duplicate"])
        self.assertEqual(duplicate.json()["sample_id"], response.json()["sample_id"])
        summary = self.client.get(f"/hosts/{self.host_id}/monitoring", headers=self.viewer).json()
        self.assertEqual(summary["host"]["connectivity"], "online")
        self.assertEqual(summary["latest"]["memory_used_bytes"], 600)
        self.assertEqual(summary["latest"]["memory_percent"], 60)
        self.assertEqual(summary["latest"]["long_running_count"], 1)
        self.assertEqual(summary["latest"]["zombie_count"], 1)
        self.assertEqual(summary["latest"]["denied_count"], 1)
        page = self.client.get(
            f"/hosts/{self.host_id}/processes?long_running=true&limit=1", headers=self.viewer
        ).json()
        self.assertEqual(page["total"], 1)
        self.assertEqual(page["items"][0]["pid"], 42)
        self.assertTrue(page["items"][0]["long_running"])
        self.assertEqual(self.client.get(
            f"/hosts/{self.host_id}/processes?zombie=true", headers=self.viewer
        ).json()["items"][0]["pid"], 43)
        history = self.client.get(
            f"/hosts/{self.host_id}/process-history", headers=self.viewer,
            params={"pid": 42, "create_time": payload["processes"][0]["create_time"]},
        ).json()
        self.assertEqual(len(history["items"]), 1)
        # A recycled PID must not merge with a different process creation time.
        self.assertEqual(self.client.get(
            f"/hosts/{self.host_id}/process-history", headers=self.viewer,
            params={"pid": 42, "create_time": utc_text(datetime.now(UTC))},
        ).json()["items"], [])
        payload["cpu_percent"] = 99
        self.assertEqual(self.send(payload).status_code, 409)

    def test_roles_credentials_rotation_and_disabled_hosts(self) -> None:
        self.assertEqual(self.client.get("/hosts").status_code, 401)
        self.assertEqual(self.client.get("/hosts", headers=self.collector).status_code, 401)
        self.assertEqual(self.client.post("/hosts", json={
            "name": "anonymous", "platform": "windows", "deployment_type": "external",
        }).status_code, 401)
        self.assertEqual(self.client.post("/collector/snapshots", headers=self.admin, json=self.batch()).status_code, 401)
        rotated = self.client.post(
            f"/hosts/{self.host_id}/credentials/rotate", headers=self.admin
        ).json()
        self.assertEqual(self.send(self.batch()).status_code, 401)
        self.collector = {"Authorization": f"Bearer {rotated['collector_token']}"}
        self.assertEqual(self.send(self.batch()).status_code, 200)
        self.client.patch(f"/hosts/{self.host_id}", headers=self.admin, json={"enabled": False})
        self.assertEqual(self.send(self.batch()).status_code, 401)
        self.assertEqual(self.client.get(
            f"/hosts/{self.host_id}/monitoring", headers=self.viewer
        ).json()["host"]["connectivity"], "disabled")
        with closing(sqlite3.connect(self.path)) as con:
            digests = [row[0] for row in con.execute("SELECT token_digest FROM collector_credentials")]
        self.assertNotIn(rotated["collector_token"], digests)

    def test_owners_manage_their_hosts_and_administrators_notify_them(self) -> None:
        with closing(sqlite3.connect(self.path)) as con:
            con.execute("INSERT INTO users(id,username,password_hash,is_admin) VALUES (3,'other','unused',0)")
            con.commit()
        jwt = app.dependency_overrides[get_jwt_service]()
        other = {"Authorization": f"Bearer {jwt.create_access_token('3')}"}

        rotated = self.client.post(f"/hosts/{self.host_id}/credentials/rotate", headers=self.viewer)
        self.assertEqual(rotated.status_code, 200, rotated.text)
        self.assertEqual(self.send(self.batch()).status_code, 401)
        self.collector = {"Authorization": f"Bearer {rotated.json()['collector_token']}"}
        self.assertEqual(self.send(self.batch()).status_code, 200)
        self.assertEqual(self.client.patch(
            f"/hosts/{self.host_id}", headers=self.viewer, json={"long_running_seconds": 600}
        ).status_code, 200)
        self.assertEqual(self.client.get("/notifications", headers=self.viewer).json(), [])

        self.assertEqual(self.client.patch(
            f"/hosts/{self.host_id}", headers=other, json={"enabled": False}
        ).status_code, 404)
        self.assertEqual(self.client.post(
            f"/hosts/{self.host_id}/credentials/rotate", headers=other
        ).status_code, 404)

        self.assertEqual(self.client.patch(
            f"/hosts/{self.host_id}", headers=self.admin, json={"long_running_seconds": 7200}
        ).status_code, 200)
        self.assertEqual(self.client.patch(
            f"/hosts/{self.host_id}", headers=self.admin, json={"enabled": False}
        ).status_code, 200)
        self.assertEqual(self.client.post(
            f"/hosts/{self.host_id}/credentials/rotate", headers=self.admin
        ).status_code, 200)

        notifications = self.client.get("/notifications", headers=self.viewer).json()
        messages = [item["message"] for item in notifications]
        self.assertEqual(len(messages), 3, messages)
        self.assertTrue(any("7200 seconds" in message for message in messages))
        self.assertTrue(any("turned monitoring off" in message for message in messages))
        self.assertTrue(any("rotated the collector token" in message for message in messages))
        self.assertEqual(self.client.get("/notifications", headers=self.admin).json(), [])

        notification_id = notifications[0]["id"]
        self.assertEqual(self.client.post(
            f"/notifications/{notification_id}/read", headers=self.admin
        ).status_code, 404)
        self.assertEqual(self.client.post(
            f"/notifications/{notification_id}/read", headers=self.viewer
        ).status_code, 200)
        self.assertIsNotNone(self.client.get("/notifications", headers=self.viewer).json()[0]["read_at"])

    def test_unknown_values_windows_zombies_and_threshold_update(self) -> None:
        registered = self.client.post("/hosts", headers=self.viewer, json={
            "name": "Windows", "platform": "windows", "deployment_type": "localhost",
        }).json()
        headers = {"Authorization": f"Bearer {registered['collector_token']}"}
        payload = self.batch()
        payload["platform"] = "windows"
        payload["processes"][1]["status"] = "sleeping"
        self.assertEqual(self.client.post("/collector/snapshots", headers=headers, json=payload).status_code, 200)
        host_id = registered["host"]["id"]
        summary = self.client.get(f"/hosts/{host_id}/monitoring", headers=self.viewer).json()
        self.assertIsNone(summary["latest"]["zombie_count"])
        rows = self.client.get(f"/hosts/{host_id}/processes", headers=self.viewer).json()["items"]
        unknown = next(row for row in rows if row["pid"] == 44)
        self.assertIsNone(unknown["cpu_percent"])
        self.assertIsNone(unknown["long_running"])
        self.assertTrue(all(row["zombie"] is None for row in rows))
        self.client.patch(
            f"/hosts/{self.host_id}", headers=self.admin, json={"long_running_seconds": 10800}
        )
        self.assertEqual(self.send(self.batch()).status_code, 200)
        self.assertEqual(self.client.get(
            f"/hosts/{self.host_id}/monitoring", headers=self.viewer
        ).json()["latest"]["long_running_count"], 0)

    def test_validation_is_atomic(self) -> None:
        for field, value in [("cpu_percent", 101), ("memory_available_bytes", 1001),
                             ("sampled_at", "2026-01-01T00:00:00"),
                             ("platform", "windows"), ("denied_count", 0),
                             ("memory_total_bytes", 10 ** 30), ("host_id", 999)]:
            payload = self.batch()
            payload[field] = value
            with self.subTest(field=field):
                self.assertEqual(self.send(payload).status_code, 422)
        duplicate_pid = self.batch()
        duplicate_pid["processes"].append(duplicate_pid["processes"][0])
        self.assertEqual(self.send(duplicate_pid).status_code, 422)
        self.assertEqual(self.send(self.batch(datetime.now(UTC) - timedelta(days=2))).status_code, 422)
        self.assertIsNone(self.client.get(
            f"/hosts/{self.host_id}/monitoring", headers=self.viewer
        ).json()["latest"])

    def test_oversized_snapshot_is_rejected_before_json_parsing(self) -> None:
        response = self.client.post(
            "/collector/snapshots", headers={**self.collector, "Content-Type": "application/json"},
            content=b" " * (16 * 1024 * 1024 + 1),
        )
        self.assertEqual(response.status_code, 413)
        self.assertIsNone(self.client.get(
            f"/hosts/{self.host_id}/monitoring", headers=self.viewer
        ).json()["latest"])

    def test_long_running_boundary_and_missing_identity(self) -> None:
        now = datetime.now(UTC)
        payload = self.batch(now)
        payload["processes"][0]["create_time"] = utc_text(now - timedelta(seconds=3600))
        payload["processes"][1]["create_time"] = utc_text(now - timedelta(seconds=3599.999999))
        self.assertEqual(self.send(payload).status_code, 200)
        rows = self.client.get(
            f"/hosts/{self.host_id}/processes?sort=runtime", headers=self.viewer
        ).json()["items"]
        by_pid = {row["pid"]: row for row in rows}
        self.assertTrue(by_pid[42]["long_running"])
        self.assertFalse(by_pid[43]["long_running"])
        self.assertIsNone(by_pid[44]["long_running"])

    def test_late_arrival_never_replaces_latest_and_disabled_user_cannot_read(self) -> None:
        self.send(self.batch())
        old = self.batch(datetime.now(UTC) - timedelta(hours=1))
        self.send(old)
        metrics = self.client.get(f"/hosts/{self.host_id}/metrics", headers=self.viewer).json()
        self.assertEqual(len(metrics), 2)
        self.assertLess(metrics[0]["sampled_at"], metrics[1]["sampled_at"])
        with closing(sqlite3.connect(self.path)) as con:
            con.execute("UPDATE hosts SET last_heartbeat_at = ? WHERE id = ?",
                        (utc_text(datetime.now(UTC) - timedelta(minutes=2)), self.host_id))
            con.commit()
        summary = self.client.get(f"/hosts/{self.host_id}/monitoring", headers=self.viewer).json()
        self.assertEqual(summary["host"]["connectivity"], "offline")
        self.assertEqual(summary["latest"]["sampled_at"], metrics[-1]["sampled_at"])
        with closing(sqlite3.connect(self.path)) as con:
            con.execute("UPDATE users SET enabled = 0 WHERE id = 2")
            con.commit()
        self.assertEqual(self.client.get("/hosts", headers=self.viewer).status_code, 401)

    def test_retention_and_receipt_replay_after_history_expires(self) -> None:
        payload = self.batch()
        receipt = self.send(payload).json()
        with closing(sqlite3.connect(self.path)) as con:
            con.execute("UPDATE monitoring_samples SET sampled_at = ?",
                        (utc_text(datetime.now(UTC) - timedelta(days=2)),))
            con.commit()
        self.send(self.batch())
        duplicate = self.send(payload).json()
        self.assertTrue(duplicate["duplicate"])
        self.assertIsNone(duplicate["sample_id"])
        with closing(sqlite3.connect(self.path)) as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM monitoring_samples").fetchone()[0], 1)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM process_samples WHERE sample_id = ?",
                                         (receipt["sample_id"],)).fetchone()[0], 0)
            self.assertEqual(con.execute("PRAGMA foreign_key_check").fetchall(), [])


    def test_machine_alert_fires_after_sustained_breach_and_notifies_owner(self) -> None:
        created = self.client.post(f"/hosts/{self.host_id}/alert-rules", headers=self.viewer,
                                   json={"name": "High CPU", "metric": "cpu_percent", "threshold": 50,
                                         "sustained_minutes": 2, "enabled": True})
        self.assertEqual(created.status_code, 201, created.text)
        self.assertEqual(created.json()["firing"], False)
        rule_url = f"/hosts/{self.host_id}/alert-rules/{created.json()['id']}"
        self.assertEqual(self.client.put(rule_url, headers=self.viewer,
                                         json={"name": "High CPU", "metric": "cpu_percent", "threshold": 150,
                                               "sustained_minutes": 2}).status_code, 422)
        start = datetime.now(UTC) - timedelta(minutes=5)

        def sample(minute: int, cpu: int):
            return self.send({**self.batch(start + timedelta(minutes=minute)), "cpu_percent": cpu})

        self.assertEqual(sample(0, 80).status_code, 200)
        self.assertEqual(sample(1, 80).status_code, 200)
        self.assertEqual(self.client.get(f"/hosts/{self.host_id}/alerts", headers=self.viewer).json(), [])

        self.assertEqual(sample(2, 80).status_code, 200)
        alerts = self.client.get(f"/hosts/{self.host_id}/alerts", headers=self.viewer).json()
        self.assertEqual([(a["metric"], a["status"]) for a in alerts], [("cpu_percent", "open")])
        self.assertEqual(self.client.get(f"/hosts/{self.host_id}/alert-rules", headers=self.viewer).json()[0]["firing"], True)

        self.assertEqual(sample(3, 10).status_code, 200)
        alerts = self.client.get(f"/hosts/{self.host_id}/alerts", headers=self.viewer).json()
        self.assertEqual(alerts[0]["status"], "resolved")
        self.assertIsNotNone(alerts[0]["resolved_at"])

        messages = [n["message"] for n in self.client.get("/notifications", headers=self.viewer).json()]
        self.assertTrue(messages[0].startswith("Resolved: High CPU"), messages)
        self.assertTrue(messages[1].startswith("Alert: High CPU"), messages)

        self.assertEqual(self.client.post("/notifications/read-all", headers=self.viewer).status_code, 200)
        unread = [n for n in self.client.get("/notifications", headers=self.viewer).json() if n["read_at"] is None]
        self.assertEqual(unread, [])

    def test_admin_alert_rule_change_notifies_owner(self) -> None:
        response = self.client.post(f"/hosts/{self.host_id}/alert-rules", headers=self.admin,
                                    json={"name": "Memory", "metric": "memory_percent", "threshold": 90,
                                          "sustained_minutes": 5, "enabled": False})
        self.assertEqual(response.status_code, 201, response.text)
        messages = [n["message"] for n in self.client.get("/notifications", headers=self.viewer).json()]
        self.assertEqual(len(messages), 1)
        self.assertIn("administrator created the alert 'Memory'", messages[0])

    def test_custom_alert_rules_allow_several_per_metric_and_deleting_removes_their_alerts(self) -> None:
        rules_url = f"/hosts/{self.host_id}/alert-rules"
        warn = self.client.post(rules_url, headers=self.viewer, json={
            "name": "Warn", "metric": "cpu_percent", "threshold": 50, "sustained_minutes": 1})
        critical = self.client.post(rules_url, headers=self.viewer, json={
            "name": "Critical", "metric": "cpu_percent", "threshold": 90, "sustained_minutes": 1})
        self.assertEqual((warn.status_code, critical.status_code), (201, 201))
        start = datetime.now(UTC) - timedelta(minutes=5)
        for minute in (0, 1):
            self.send({**self.batch(start + timedelta(minutes=minute)), "cpu_percent": 80})
        alerts = self.client.get(f"/hosts/{self.host_id}/alerts", headers=self.viewer).json()
        self.assertEqual([(a["rule_id"], a["status"]) for a in alerts], [(warn.json()["id"], "open")])

        warn_url = f"{rules_url}/{warn.json()['id']}"
        self.assertEqual(self.client.delete(warn_url, headers=self.viewer).json(), {"deleted": True})
        self.assertEqual(self.client.delete(warn_url, headers=self.viewer).status_code, 404)
        self.assertEqual([r["name"] for r in self.client.get(rules_url, headers=self.viewer).json()], ["Critical"])
        self.assertEqual(self.client.get(f"/hosts/{self.host_id}/alerts", headers=self.viewer).json(), [])

    def test_process_alerts_match_the_named_process_and_resolve_when_it_exits(self) -> None:
        created = self.client.post(f"/hosts/{self.host_id}/alert-rules", headers=self.viewer, json={
            "name": "Worker CPU", "metric": "process_cpu_percent", "process_name": "WORKER",
            "threshold": 10, "sustained_minutes": 2})
        self.assertEqual(created.status_code, 201, created.text)
        start = datetime.now(UTC) - timedelta(minutes=5)
        without_worker = [p for p in self.batch()["processes"] if p.get("name") != "worker"]
        for minute in (0, 1, 2):
            self.assertEqual(self.send(self.batch(start + timedelta(minutes=minute))).status_code, 200)
        alerts = self.client.get(f"/hosts/{self.host_id}/alerts", headers=self.viewer).json()
        self.assertEqual([(a["metric"], a["status"], a["value"]) for a in alerts], [("process_cpu_percent", "open", 12)])

        self.assertEqual(self.send({**self.batch(start + timedelta(minutes=3)), "processes": without_worker}).status_code, 200)
        alerts = self.client.get(f"/hosts/{self.host_id}/alerts", headers=self.viewer).json()
        self.assertEqual(alerts[0]["status"], "resolved")
        messages = [n["message"] for n in self.client.get("/notifications", headers=self.viewer).json()]
        self.assertTrue(messages[0].startswith("Resolved: Worker CPU"), messages)

    def test_alert_rule_validation_requires_process_name_only_for_process_metrics(self) -> None:
        rules_url = f"/hosts/{self.host_id}/alert-rules"
        base = {"threshold": 1, "sustained_minutes": 1}
        cases = [
            {"name": "Named machine", "metric": "cpu_percent", "process_name": "chrome", "threshold": 50,
             "sustained_minutes": 1},
            {"name": "Unnamed process", "metric": "process_count", **base},
            {"name": "   ", "metric": "zombie_count", **base},
        ]
        for case in cases:
            self.assertEqual(self.client.post(rules_url, headers=self.viewer, json=case).status_code, 422, case)
        self.assertEqual(self.client.get(rules_url, headers=self.viewer).json(), [])

    def test_consolidated_schema_matches_migrations(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "migration.db"
            migrate(path)
            schema = Path(__file__).parents[1] / "db" / "schema" / "schema.sql"
            with closing(sqlite3.connect(path)) as migrated, closing(sqlite3.connect(":memory:")) as fresh:
                fresh.executescript(schema.read_text(encoding="utf-8"))
                for table in ("hosts", "monitoring_samples", "process_samples", "monitoring_receipts",
                              "host_notifications", "ssh_collectors", "alert_rules", "alerts"):
                    with self.subTest(table=table):
                        # ALTER TABLE appends the host column; physical order is not significant.
                        migrated_columns = {row[1]: row[2:] for row in migrated.execute(f"PRAGMA table_info({table})")}
                        fresh_columns = {row[1]: row[2:] for row in fresh.execute(f"PRAGMA table_info({table})")}
                        self.assertEqual(migrated_columns, fresh_columns)
                        self.assertEqual(
                            migrated.execute(f"PRAGMA foreign_key_list({table})").fetchall(),
                            fresh.execute(f"PRAGMA foreign_key_list({table})").fetchall(),
                        )

    def test_down_and_up_preserve_existing_hosts(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "migration.db"
            migrate(path)
            with closing(sqlite3.connect(path)) as con:
                con.execute("INSERT INTO hosts(name,platform,deployment_type) VALUES ('old','windows','localhost')")
                con.commit()
            self.assertEqual(rollback(path), "0008_machine_alerts")
            self.assertEqual(rollback(path), "0007_user_profiles")
            self.assertEqual(rollback(path), "0006_ssh_collectors")
            self.assertEqual(rollback(path), "0005_host_notifications")
            self.assertEqual(rollback(path), "0004_host_ownership")
            with closing(sqlite3.connect(path)) as con:
                con.execute(
                    """INSERT INTO monitoring_samples(host_id,sampled_at,received_at,cpu_percent,memory_total_bytes,
                       memory_available_bytes,memory_used_bytes,memory_percent,process_count,denied_count,
                       vanished_count,long_running_count) VALUES (1,'2026-01-01T00:00:00.000000Z',
                       '2026-01-01T00:00:00.000000Z',1,1000,400,600,60,0,0,0,0)"""
                )
                con.commit()
            self.assertEqual(
                migrate(path),
                ["0004_host_ownership", "0005_host_notifications", "0006_ssh_collectors", "0007_user_profiles",
                 "0008_machine_alerts"],
            )
            with closing(sqlite3.connect(path)) as con:
                self.assertEqual(con.execute("SELECT name,long_running_seconds,owner_user_id FROM hosts").fetchone(),
                                 ("old", 3600, None))
                self.assertEqual(con.execute("SELECT COUNT(*) FROM monitoring_samples").fetchone()[0], 1)
