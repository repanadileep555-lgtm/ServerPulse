import io
import json
import unittest
import urllib.error
from contextlib import nullcontext
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch

import psutil

from app.collector import ResourceSampler, deliver_logs, save_pending
from app.log_collector import collect_batch
from app.service_collector import ServiceCollectionError, collect_services


class FakeJournal:
    def __init__(self, lines: list[str]) -> None:
        self.stdout = io.StringIO("\n".join(lines))
        self.stderr = io.StringIO("")
        self.returncode = 0

    def wait(self, timeout: float | None = None) -> int:
        return self.returncode

    def poll(self) -> int:
        return self.returncode


JOURNAL_LINES = [
    json.dumps({"__CURSOR": "s=abc;i=1", "__REALTIME_TIMESTAMP": "1700000000000000",
                "PRIORITY": "3", "MESSAGE": "disk failed", "SYSLOG_IDENTIFIER": "kernel"}),
    json.dumps({"__CURSOR": "s=abc;i=2", "PRIORITY": "6", "MESSAGE": [104, 105],
                "SYSLOG_IDENTIFIER": "cron"}),
]


class CollectorTests(unittest.TestCase):
    @patch("app.collector.platform.system", return_value="Linux")
    @patch("app.collector.psutil.cpu_count", return_value=2)
    @patch("app.collector.psutil.virtual_memory", return_value=SimpleNamespace(total=1000, available=400))
    @patch("app.collector.psutil.cpu_percent", return_value=25)
    @patch("app.collector.psutil.process_iter")
    def test_identity_cpu_warmup_and_partial_visibility(self, iterator, *_mocks) -> None:
        process = Mock(pid=42)
        created = datetime.now(UTC).timestamp() - 10
        process.status.return_value = "running"
        process.name.return_value = "existing"
        process.create_time.return_value = created
        process.memory_info.return_value = SimpleNamespace(rss=100)
        process.cpu_times.side_effect = [
            SimpleNamespace(user=1, system=1), SimpleNamespace(user=2, system=1),
            SimpleNamespace(user=500, system=0), SimpleNamespace(user=501, system=0),
        ]
        denied = Mock(pid=43)
        denied.status.side_effect = psutil.AccessDenied(43)
        vanished = Mock(pid=44)
        vanished.status.side_effect = psutil.NoSuchProcess(44)
        zombie = Mock(pid=45)
        zombie.status.return_value = "zombie"
        zombie.name.side_effect = psutil.ZombieProcess(45)
        for item in (process, denied, vanished, zombie):
            item.oneshot.return_value = nullcontext()
        iterator.return_value = [process, denied, vanished, zombie]
        sampler = ResourceSampler()
        with patch("app.collector.time.monotonic", side_effect=[10, 12, 14, 16]):
            first = sampler.sample()
            second = sampler.sample()
            process.create_time.return_value = created + 1
            recycled = sampler.sample()
            with patch("app.collector.psutil.cpu_count", return_value=None):
                with self.assertLogs("app.collector", level="WARNING"):
                    unknown_cores = sampler.sample()
        self.assertIsNone(first.processes[0].cpu_percent)
        self.assertEqual(second.processes[0].cpu_percent, 25)
        self.assertIsNone(recycled.processes[0].cpu_percent)
        self.assertIsNone(unknown_cores.processes[0].cpu_percent)
        self.assertEqual(first.denied_count, 1)
        self.assertEqual(first.vanished_count, 1)
        self.assertEqual(first.processes[-1].status, "zombie")
        self.assertTrue(first.processes[1].access_denied)
        self.assertEqual(iterator.cache_clear.call_count, 4)

    def test_pending_snapshot_is_atomically_replaced(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "pending.json"
            save_pending(path, '{"batch_id":"first"}')
            save_pending(path, '{"batch_id":"second"}')
            self.assertEqual(json.loads(path.read_text())["batch_id"], "second")
            self.assertEqual(list(path.parent.iterdir()), [path])


class LogCollectorTests(unittest.TestCase):
    @patch("app.log_collector.subprocess.Popen", return_value=FakeJournal(JOURNAL_LINES))
    def test_journald_entries_map_severity_timestamp_and_checkpoint(self, _popen) -> None:
        batch = collect_batch("linux", {})
        first, second = batch.records
        self.assertEqual(first.severity, "error")
        self.assertEqual(first.timestamp_quality, "native")
        self.assertEqual(first.occurred_at, datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC))
        self.assertEqual(second.severity, "info")
        self.assertEqual(second.timestamp_quality, "fallback")
        self.assertEqual(second.message, "hi")
        self.assertEqual(batch.sources[0].checkpoint, "s=abc;i=2")

    @patch("app.log_collector.subprocess.run")
    def test_windows_level_zero_is_informational_and_unknown_levels_stay_unknown(self, run) -> None:
        events = [{"RecordId": 1, "Id": 1, "Level": 0, "Provider": "p", "Time": "2024-01-01T00:00:00Z", "Message": "a"},
                  {"RecordId": 2, "Id": 2, "Level": 4, "Provider": "p", "Time": "2024-01-01T00:00:01Z", "Message": "b"},
                  {"RecordId": 3, "Id": 3, "Level": None, "Provider": "p", "Time": "2024-01-01T00:00:02Z", "Message": "c"}]
        run.return_value = SimpleNamespace(returncode=0, stdout=json.dumps(events), stderr="")
        batch = collect_batch("windows", {})
        self.assertEqual([record.severity for record in batch.records[:3]], ["info", "info", "unknown"])
        self.assertEqual(batch.records[0].native_severity, "0")

    @patch("app.log_collector.subprocess.Popen", return_value=FakeJournal(JOURNAL_LINES))
    def test_journald_resumes_after_checkpoint(self, popen) -> None:
        collect_batch("linux", {"journald:journal": "s=abc;i=1"})
        self.assertIn("--after-cursor=s=abc;i=1", popen.call_args.args[0])

    def test_checkpoint_advances_only_after_acknowledgement(self) -> None:
        host = {"id": "host-1", "platform": "linux"}
        url = "https://pulse.example"
        with TemporaryDirectory() as directory, patch(
            "app.log_collector.subprocess.Popen", side_effect=lambda *a, **k: FakeJournal(JOURNAL_LINES),
        ):
            logs = Path(directory) / "logs.json"
            checkpoints = Path(directory) / "checkpoints.json"
            failure = urllib.error.HTTPError(url, 500, "unavailable", None, None)
            with patch("app.collector.api_request", side_effect=failure) as request:
                with self.assertRaises(urllib.error.HTTPError):
                    deliver_logs(url, "token", host, logs, checkpoints)
            self.assertTrue(logs.exists())
            self.assertFalse(checkpoints.exists())
            with patch("app.collector.api_request", return_value={"accepted": 2, "duplicates": 0}) as retry:
                deliver_logs(url, "token", host, logs, checkpoints)
            self.assertEqual(request.call_args.args[2], retry.call_args.args[2])
            self.assertFalse(logs.exists())
            self.assertEqual(json.loads(checkpoints.read_text()), {"journald:journal": "s=abc;i=2"})


class ServiceCollectorTests(unittest.TestCase):
    @patch("app.service_collector.subprocess.run")
    def test_windows_scm_states_map_to_normalized_states(self, run) -> None:
        services = [
            {"Name": "Spooler", "DisplayName": "Print Spooler", "Status": "Running"},
            {"Name": "WSearch", "DisplayName": "", "Status": "Stopped"},
            {"Name": "Dhcp", "DisplayName": "DHCP Client", "Status": "StartPending"},
        ]
        run.return_value = SimpleNamespace(returncode=0, stdout=json.dumps(services), stderr="")
        batch = collect_services("windows")
        by_name = {service.service_name: service for service in batch.services}
        self.assertEqual(by_name["Spooler"].current_state, "running")
        self.assertEqual(by_name["Spooler"].display_name, "Print Spooler")
        self.assertEqual(by_name["Spooler"].native_state, "Running")
        self.assertEqual(by_name["WSearch"].current_state, "stopped")
        self.assertIsNone(by_name["WSearch"].display_name)
        self.assertEqual(by_name["Dhcp"].current_state, "transitional")

    @patch("app.service_collector.subprocess.run")
    def test_systemd_units_are_inventoried_as_services_only(self, run) -> None:
        output = "\n".join([
            "nginx.service loaded active running A high performance web server",
            "● broken.service loaded failed failed Broken unit",
            "cron.service loaded inactive dead Regular background program processing daemon",
            "gone.service not-found inactive dead gone.service",
            "ssh.socket loaded active listening OpenSSH socket",
        ])
        run.return_value = SimpleNamespace(returncode=0, stdout=output, stderr="")
        batch = collect_services("linux")
        by_name = {service.service_name: service for service in batch.services}
        self.assertEqual(set(by_name), {"nginx.service", "broken.service", "cron.service"})
        self.assertEqual(by_name["nginx.service"].current_state, "running")
        self.assertEqual(by_name["nginx.service"].native_state, "active/running")
        self.assertEqual(by_name["broken.service"].current_state, "failed")
        self.assertEqual(by_name["cron.service"].current_state, "stopped")

    @patch("app.service_collector.subprocess.run", side_effect=FileNotFoundError)
    def test_missing_service_manager_is_reported_as_collection_error(self, _run) -> None:
        with self.assertRaises(ServiceCollectionError):
            collect_services("linux")
