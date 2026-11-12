"""Read Windows event logs and Linux journald entries for ServerPulse log ingestion."""

import json
import logging
import re
import subprocess
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from app.schemas.monitoring import LogBatch, utc_text

logger = logging.getLogger(__name__)

MESSAGE_LIMIT = 4096
BATCH_RECORD_LIMIT = 200
WINDOWS_CHANNEL_LIMIT = 100
FIRST_RUN_EVENTS = 50
WINDOWS_SOURCES = (("System", "system"), ("Application", "application"))
JOURNAL_CHANNEL = "journal"
# Level 0 is LogAlways: many Application events carry no severity, so they are treated as informational.
WINDOWS_LEVELS = {0: "info", 1: "critical", 2: "error", 3: "warning", 4: "info", 5: "debug"}
JOURNAL_PRIORITIES = {
    0: "critical", 1: "critical", 2: "critical", 3: "error",
    4: "warning", 5: "info", 6: "info", 7: "debug",
}
EXTRA_FRACTION_DIGITS = re.compile(r"(\.\d{6})\d+")
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
PERMISSION_HINTS = ("access is denied", "permission", "insufficient")


def _clip(value: Any, limit: int) -> str | None:
    return None if value is None else str(value)[:limit]


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(EXTRA_FRACTION_DIGITS.sub(r"\1", value.replace("Z", "+00:00")))


def _failure(base: dict[str, Any], stderr: str) -> dict[str, Any]:
    first_line = (stderr.strip().splitlines() or ["Log read failed"])[0][:512]
    status = "unavailable" if any(hint in stderr.lower() for hint in PERMISSION_HINTS) else "error"
    return {**base, "status": status, "error": first_line}


def _windows_script(channel: str, checkpoint: str | None) -> str:
    if checkpoint is None:
        fetch = f"$events = Get-WinEvent -LogName '{channel}' -MaxEvents {FIRST_RUN_EVENTS}"
    else:
        fetch = (
            f"$events = Get-WinEvent -LogName '{channel}' -Oldest "
            f"-FilterXPath '*[System[EventRecordID>{checkpoint}]]' -MaxEvents {WINDOWS_CHANNEL_LIMIT}"
        )
    return "\n".join([
        "[Console]::OutputEncoding = [Text.Encoding]::UTF8",
        "$ErrorActionPreference = 'Stop'",
        "try {",
        f"  {fetch}",
        "} catch {",
        "  if ($_.FullyQualifiedErrorId -like 'NoMatchingEventsFound*') { $events = @() } else { throw }",
        "}",
        "ConvertTo-Json -InputObject @($events | ForEach-Object { [pscustomobject]@{ RecordId = $_.RecordId; "
        "Id = $_.Id; Level = $_.Level; Provider = $_.ProviderName; "
        "Time = $_.TimeCreated.ToUniversalTime().ToString('o'); Message = $_.Message; "
        "ScmService = $(if ($_.ProviderName -eq 'Service Control Manager' -and $_.Properties.Count -gt 0) "
        "{ [string]$_.Properties[0].Value } else { $null }) } }) -Compress",
    ])


def _windows_source(channel: str, category: str, checkpoint: str | None,
                    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    base = {"source_type": "windows_eventlog", "category": category, "channel": channel}
    if checkpoint is not None and not checkpoint.isdigit():
        checkpoint = None
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-Command", _windows_script(channel, checkpoint)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60, check=False,
        )
    except FileNotFoundError:
        return {**base, "status": "unavailable", "error": "PowerShell is not available"}, []
    except subprocess.TimeoutExpired:
        return {**base, "status": "error", "error": "Event log query timed out"}, []
    if result.returncode != 0:
        return _failure(base, result.stderr), []

    events = sorted(json.loads(result.stdout.strip() or "[]"), key=lambda event: int(event["RecordId"]))
    records = []
    for event in events:
        level = event.get("Level")
        records.append({
            **base,
            "source_record_id": str(event["RecordId"]),
            "occurred_at": utc_text(_parse_time(event["Time"])),
            "timestamp_quality": "native",
            "severity": WINDOWS_LEVELS.get(level, "unknown"),
            "native_severity": _clip(level, 64),
            "event_id": event.get("Id"),
            "provider": _clip(event.get("Provider"), 256),
            "service_reference": _clip(event.get("ScmService"), 256),
            "message": _clip(event.get("Message") or "", MESSAGE_LIMIT),
        })
    report: dict[str, Any] = {**base, "status": "ok"}
    if records:
        report["checkpoint"] = records[-1]["source_record_id"]
    return report, records


def _journal_source(checkpoint: str | None, collected_at: datetime,
                    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    base = {"source_type": "journald", "category": "system", "channel": JOURNAL_CHANNEL}
    arguments = ["journalctl", "--no-pager", "--output=json", "--quiet"]
    arguments.append(f"--after-cursor={checkpoint}" if checkpoint else f"--lines={FIRST_RUN_EVENTS}")
    try:
        process = subprocess.Popen(
            arguments, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace",
        )
    except FileNotFoundError:
        return {**base, "status": "unavailable", "error": "journalctl is not available"}, []

    lines: list[str] = []
    try:
        for line in process.stdout or []:
            if line.strip():
                lines.append(line)
            if len(lines) == BATCH_RECORD_LIMIT:
                break
        truncated = len(lines) == BATCH_RECORD_LIMIT
        if truncated:
            process.terminate()
        stderr = process.stderr.read() if process.stderr else ""
        returncode = process.wait(timeout=30)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()

    if returncode != 0 and not truncated:
        return _failure(base, stderr), []

    records = []
    for line in lines:
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            logger.warning("Skipped a journal entry that is not valid JSON")
            continue
        cursor = entry.get("__CURSOR")
        if not isinstance(cursor, str) or not cursor or len(cursor) > 256:
            continue
        timestamp = entry.get("__REALTIME_TIMESTAMP")
        native_time = timestamp is not None and str(timestamp).isdigit()
        occurred = EPOCH + timedelta(microseconds=int(timestamp)) if native_time else collected_at
        message = entry.get("MESSAGE", "")
        if isinstance(message, list):
            message = bytes(message).decode("utf-8", errors="replace")
        priority = entry.get("PRIORITY")
        priority_value = int(priority) if str(priority).isdigit() else None
        records.append({
            **base,
            "source_record_id": cursor,
            "occurred_at": utc_text(occurred),
            "timestamp_quality": "native" if native_time else "fallback",
            "severity": JOURNAL_PRIORITIES.get(priority_value, "unknown"),
            "native_severity": _clip(priority, 64),
            "event_id": None,
            "provider": _clip(entry.get("SYSLOG_IDENTIFIER"), 256),
            "unit": _clip(entry.get("_SYSTEMD_UNIT"), 256),
            "message": _clip(message if message is not None else "", MESSAGE_LIMIT),
        })
    report: dict[str, Any] = {**base, "status": "ok"}
    if records:
        report["checkpoint"] = records[-1]["source_record_id"]
    return report, records


def collect_batch(platform: str, checkpoints: dict[str, str]) -> LogBatch:
    """Read new entries from each log source. Checkpoints are only advanced after the backend acknowledges."""
    collected_at = datetime.now(UTC)
    reports: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    if platform == "windows":
        for channel, category in WINDOWS_SOURCES:
            key = f"windows_eventlog:{channel}"
            report, found = _windows_source(channel, category, checkpoints.get(key))
            reports.append(report)
            records.extend(found)
    else:
        key = f"journald:{JOURNAL_CHANNEL}"
        report, found = _journal_source(checkpoints.get(key), collected_at)
        reports.append(report)
        records.extend(found)
    return LogBatch.model_validate({
        "batch_id": str(uuid4()),
        "platform": platform,
        "collected_at": utc_text(collected_at),
        "sources": reports,
        "records": records,
    })
