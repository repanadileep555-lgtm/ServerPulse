"""Inventory Windows services and systemd service units for ServerPulse service monitoring."""

import json
import subprocess
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.schemas.monitoring import SERVICE_BATCH_LIMIT, ServiceBatch, utc_text

WINDOWS_STATES = {
    "Running": "running", "Stopped": "stopped", "Paused": "paused",
    "StartPending": "transitional", "StopPending": "transitional", "ContinuePending": "transitional",
    "PausePending": "transitional",
}
SYSTEMD_STATES = {
    "active": "running", "inactive": "stopped", "failed": "failed",
    "activating": "transitional", "deactivating": "transitional", "reloading": "transitional",
}
WINDOWS_SCRIPT = "\n".join([
    "[Console]::OutputEncoding = [Text.Encoding]::UTF8",
    "$ErrorActionPreference = 'Stop'",
    "$services = @(Get-Service | ForEach-Object { [pscustomobject]@{ Name = $_.ServiceName; "
    "DisplayName = $_.DisplayName; Status = [string]$_.Status } })",
    "ConvertTo-Json -InputObject $services -Compress",
])
SYSTEMCTL_ARGUMENTS = ["systemctl", "list-units", "--type=service", "--all", "--no-pager", "--no-legend", "--plain"]


class ServiceCollectionError(RuntimeError):
    pass


def _run(arguments: list[str]) -> str:
    try:
        result = subprocess.run(
            arguments, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=60, check=False,
        )
    except FileNotFoundError:
        raise ServiceCollectionError(f"{arguments[0]} is not available") from None
    except subprocess.TimeoutExpired:
        raise ServiceCollectionError(f"{arguments[0]} timed out") from None
    if result.returncode != 0:
        first_line = (result.stderr.strip().splitlines() or ["Service query failed"])[0]
        raise ServiceCollectionError(first_line[:512])
    return result.stdout


def _windows_services() -> dict[str, dict[str, Any]]:
    entries = json.loads(_run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                               "-Command", WINDOWS_SCRIPT]).strip() or "[]")
    services = {}
    for entry in entries:
        status = entry.get("Status")
        services[entry["Name"]] = {
            "service_name": entry["Name"],
            "display_name": entry.get("DisplayName") or None,
            "current_state": WINDOWS_STATES.get(status, "unknown"),
            "native_state": status,
        }
    return services


def _systemd_services() -> dict[str, dict[str, Any]]:
    services = {}
    for line in _run(SYSTEMCTL_ARGUMENTS).splitlines():
        # Failed units may carry a bullet marker in some systemctl builds.
        parts = line.lstrip("●* ").split(None, 4)
        if len(parts) < 4:
            continue
        unit, load, active, sub = parts[:4]
        if not unit.endswith(".service") or load == "not-found":
            continue
        services[unit] = {
            "service_name": unit,
            "display_name": parts[4] if len(parts) == 5 else None,
            "current_state": SYSTEMD_STATES.get(active, "unknown"),
            "native_state": f"{active}/{sub}",
        }
    return services


def collect_services(platform: str) -> ServiceBatch:
    """Enumerate every service known to the platform's service manager. Raises ServiceCollectionError on failure."""
    services = _windows_services() if platform == "windows" else _systemd_services()
    if len(services) > SERVICE_BATCH_LIMIT:
        raise ServiceCollectionError(f"More than {SERVICE_BATCH_LIMIT} services were reported")
    return ServiceBatch.model_validate({
        "batch_id": str(uuid4()),
        "platform": platform,
        "collected_at": utc_text(datetime.now(UTC)),
        "services": list(services.values()),
    })
