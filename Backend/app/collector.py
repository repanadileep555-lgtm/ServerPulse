"""Poll local resources and push snapshots to a registered ServerPulse host."""

import argparse
import json
import logging
import os
import platform
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import psutil

from app.log_collector import collect_batch
from app.schemas.monitoring import LogBatch, MonitoringBatch, ServiceBatch, utc_text
from app.service_collector import ServiceCollectionError, collect_services

logger = logging.getLogger(__name__)

LOG_INTERVAL = 60
SERVICE_INTERVAL = 300


class ResourceSampler:
    def __init__(self) -> None:
        system = platform.system().lower()
        if system not in ("windows", "linux"):
            raise RuntimeError("Only Windows and Linux collectors are supported")
        self.platform = system
        self._previous: dict[tuple[int, float], tuple[float, float]] = {}

    def sample(self) -> MonitoringBatch:
        # A blocking one-second measurement runs only in the standalone collector.
        cpu = psutil.cpu_percent(interval=1)
        memory = psutil.virtual_memory()
        processes: list[dict[str, Any]] = []
        current: dict[tuple[int, float], tuple[float, float]] = {}
        denied_count = 0
        vanished_count = 0
        cores = psutil.cpu_count()
        if not cores:
            logger.warning("Logical CPU count unavailable; process CPU percentages are unknown")
        # psutil caches Process objects; refresh creation times for recycled PIDs.
        psutil.process_iter.cache_clear()
        for process in psutil.process_iter():
            record: dict[str, Any] = {
                "pid": process.pid, "create_time": None, "name": None, "status": None,
                "cpu_percent": None, "rss_bytes": None, "memory_percent": None,
                "access_denied": False,
            }
            try:
                with process.oneshot():
                    # Read status first: zombies often deny other details.
                    record["status"] = process.status()
                    record["name"] = process.name()
                    created = process.create_time()
                    record["create_time"] = utc_text(datetime.fromtimestamp(created, UTC))
                    rss = process.memory_info().rss
                    record["rss_bytes"] = rss
                    record["memory_percent"] = min(100, rss / memory.total * 100)
                    times = process.cpu_times()
                    ticks = times.user + times.system
                    observed = time.monotonic()
                    identity = (process.pid, created)
                    previous = self._previous.get(identity)
                    if previous is not None and observed > previous[0] and cores:
                        record["cpu_percent"] = min(
                            100, max(0, (ticks - previous[1]) / (observed - previous[0]) / cores * 100)
                        )
                    current[identity] = (observed, ticks)
            except psutil.ZombieProcess:
                record["status"] = "zombie"
            except psutil.NoSuchProcess:
                vanished_count += 1
                continue
            except psutil.AccessDenied:
                record["access_denied"] = True
                denied_count += 1
            processes.append(record)
        self._previous = current
        return MonitoringBatch.model_validate({
            "batch_id": str(uuid4()), "platform": self.platform,
            "sampled_at": utc_text(datetime.now(UTC)), "cpu_percent": cpu,
            "memory_total_bytes": memory.total, "memory_available_bytes": memory.available,
            "denied_count": denied_count, "vanished_count": vanished_count,
            "processes": processes,
        })


def save_pending(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            file.write(payload)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str,
    ) -> None:
        # Never forward a collector credential to a redirect destination.
        return None


def api_request(url: str, token: str, payload: bytes | None = None) -> dict[str, Any]:
    request = urllib.request.Request(
        url, data=payload,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    with urllib.request.build_opener(NoRedirect()).open(request, timeout=30) as response:
        return json.load(response)


def load_checkpoints(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def deliver_logs(url: str, token: str, host: dict[str, Any], logs_path: Path, checkpoint_path: Path) -> None:
    """Send one log batch. Checkpoints advance only after the backend acknowledges the batch."""
    if logs_path.exists():
        pending = json.loads(logs_path.read_text(encoding="utf-8"))
        if pending["host_id"] != host["id"] or pending["backend_url"] != url:
            raise RuntimeError("Pending logs belong to another backend/host; use a different state file")
        batch = LogBatch.model_validate(pending["logs"])
    else:
        batch = collect_batch(host["platform"], load_checkpoints(checkpoint_path))
        if not batch.records and all(source.status == "ok" for source in batch.sources):
            return
        save_pending(logs_path, json.dumps({
            "host_id": host["id"], "backend_url": url, "logs": batch.model_dump(mode="json"),
        }))
    try:
        acknowledgement = api_request(url + "/collector/logs", token, batch.model_dump_json().encode())
    except urllib.error.HTTPError as exc:
        if exc.code >= 500 or exc.code == 429:
            raise
        logs_path.unlink(missing_ok=True)
        logger.error("Backend rejected log batch (HTTP %s); it was discarded and will be rebuilt", exc.code)
        return
    if "accepted" not in acknowledgement:
        raise RuntimeError("Backend did not acknowledge a committed log batch")
    checkpoints = load_checkpoints(checkpoint_path)
    for source in batch.sources:
        if source.checkpoint:
            checkpoints[f"{source.source_type}:{source.channel}"] = source.checkpoint
    save_pending(checkpoint_path, json.dumps(checkpoints))
    logs_path.unlink()
    logger.info("Delivered %d log records from %d sources", len(batch.records), len(batch.sources))


def deliver_services(url: str, token: str, host: dict[str, Any], services_path: Path) -> None:
    """Sync the platform's service inventory. A pending inventory is retried with the same batch ID."""
    if services_path.exists():
        pending = json.loads(services_path.read_text(encoding="utf-8"))
        if pending["host_id"] != host["id"] or pending["backend_url"] != url:
            raise RuntimeError("Pending service inventory belongs to another backend/host; use a different state file")
        batch = ServiceBatch.model_validate(pending["services"])
    else:
        try:
            batch = collect_services(host["platform"])
        except ServiceCollectionError as exc:
            logger.warning("Service inventory unavailable: %s", exc)
            return
        save_pending(services_path, json.dumps({
            "host_id": host["id"], "backend_url": url, "services": batch.model_dump(mode="json"),
        }))
    try:
        acknowledgement = api_request(url + "/collector/services", token, batch.model_dump_json().encode())
    except urllib.error.HTTPError as exc:
        if exc.code >= 500 or exc.code == 429:
            raise
        services_path.unlink(missing_ok=True)
        logger.error("Backend rejected service inventory (HTTP %s); it was discarded and will be rebuilt", exc.code)
        return
    if "accepted" not in acknowledgement:
        raise RuntimeError("Backend did not acknowledge a committed service inventory")
    services_path.unlink()
    logger.info("Synced %d services", len(batch.services))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="Backend origin (HTTPS for remote hosts)")
    parser.add_argument("--state-file", type=Path, default=Path("collector-state.json"))
    parser.add_argument("--interval", type=float, default=10, help="Seconds between samples (at least 2)")
    parser.add_argument("--logs", action="store_true", help="Also collect Windows event logs or journald entries")
    parser.add_argument("--once", action="store_true", help="Deliver one snapshot and exit")
    parser.add_argument("--allow-http", action="store_true", help="Allow HTTP only on a trusted isolated lab network")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parsed = urllib.parse.urlsplit(args.url)
    if parsed.scheme not in ("https", "http") or not parsed.hostname or parsed.username or parsed.password:
        parser.error("--url must be an HTTP(S) origin without embedded credentials")
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        parser.error("--url must be an origin without a path, query, or fragment")
    if parsed.scheme != "https" and parsed.hostname not in ("localhost", "127.0.0.1", "::1") and not args.allow_http:
        parser.error("Remote collectors require HTTPS (or --allow-http for isolated labs)")
    if not 2 <= args.interval <= 3600:
        parser.error("--interval must be between 2 and 3600 seconds")
    token = os.environ.get("SERVERPULSE_COLLECTOR_TOKEN")
    if not token:
        parser.error("Set SERVERPULSE_COLLECTOR_TOKEN to the registered host credential")
    url = args.url.rstrip("/")
    sampler = ResourceSampler()
    logs_path = args.state_file.with_name(args.state_file.stem + "-logs.json")
    checkpoint_path = args.state_file.with_name(args.state_file.stem + "-log-checkpoints.json")
    services_path = args.state_file.with_name(args.state_file.stem + "-services.json")
    last_logs = float("-inf")
    last_services = float("-inf")
    delay = 1.0
    try:
        while True:
            started = time.monotonic()
            try:
                host = api_request(url + "/collector/configuration", token)
                if host["platform"] != sampler.platform:
                    raise RuntimeError("This machine's platform does not match the registered host")
                if args.state_file.exists():
                    pending = json.loads(args.state_file.read_text(encoding="utf-8"))
                    if pending["host_id"] != host["id"] or pending["backend_url"] != url:
                        raise RuntimeError("Pending snapshot belongs to another backend/host; use a different state file")
                    batch = MonitoringBatch.model_validate(pending["snapshot"])
                else:
                    batch = sampler.sample()
                    save_pending(args.state_file, json.dumps({
                        "host_id": host["id"], "backend_url": url,
                        "snapshot": batch.model_dump(mode="json"),
                    }))
                acknowledgement = api_request(
                    url + "/collector/snapshots", token, batch.model_dump_json().encode()
                )
                if "sample_id" not in acknowledgement:
                    raise RuntimeError("Backend did not acknowledge a committed snapshot")
                args.state_file.unlink()
                logger.info("Delivered snapshot %s (%d processes)", batch.batch_id, len(batch.processes))
                delay = 1
                if time.monotonic() - last_services >= SERVICE_INTERVAL:
                    deliver_services(url, token, host, services_path)
                    last_services = time.monotonic()
                if args.logs and time.monotonic() - last_logs >= LOG_INTERVAL:
                    deliver_logs(url, token, host, logs_path, checkpoint_path)
                    last_logs = time.monotonic()
                if args.once:
                    return
                time.sleep(max(0, args.interval - (time.monotonic() - started)))
            except urllib.error.HTTPError as exc:
                if exc.code < 500 and exc.code != 429:
                    raise RuntimeError(
                        f"Backend rejected collection (HTTP {exc.code}); pending data retained. "
                        "Check credential, platform, batch validity, and snapshot age."
                    ) from None
                logger.warning("Backend returned HTTP %s; retrying in %.0fs", exc.code, delay)
                time.sleep(delay)
                delay = min(delay * 2, 60)
            except (urllib.error.URLError, TimeoutError, ConnectionError):
                logger.warning("Backend unreachable; pending data retained; retrying in %.0fs", delay)
                time.sleep(delay)
                delay = min(delay * 2, 60)
    except KeyboardInterrupt:
        logger.info("Collector stopped; any pending snapshot remains on disk")


if __name__ == "__main__":
    main()
