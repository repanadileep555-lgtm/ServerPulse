import asyncio
import hashlib
import json
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException

from app.db.db_pool import DatabasePool
from app.schemas.monitoring import AlertRuleUpsert, HostCreate, HostUpdate, LogBatch, MonitoringBatch, ServiceBatch, utc_text
from app.services.local_collector import find_external_collector_pid, local_collectors


LOG_RETENTION = timedelta(days=2)
SEVERITY_ORDER = ["debug", "info", "warning", "error", "critical"]
DUPLICATE_HOST_MESSAGE = "This machine is already registered"
# Metric label and unit ("%" for percentages, "" for counts).
ALERT_METRICS: dict[str, tuple[str, str]] = {
    "cpu_percent": ("CPU usage", "%"),
    "memory_percent": ("Memory usage", "%"),
    "long_running_count": ("Long-running processes", ""),
    "zombie_count": ("Zombie processes", ""),
    "process_cpu_percent": ("Process CPU usage", "%"),
    "process_memory_percent": ("Process memory usage", "%"),
    "process_count": ("Matching processes", ""),
}
# Process metrics sum or count every process whose name matches the rule's process_name in the latest sample.
_PROCESS_VALUE_SQL: dict[str, str] = {
    "process_cpu_percent": """COALESCE((SELECT SUM(p.cpu_percent) FROM process_samples p
                                     WHERE p.sample_id = s.id AND LOWER(p.name) = LOWER(?)), 0)""",
    "process_memory_percent": """COALESCE((SELECT SUM(p.memory_percent) FROM process_samples p
                                        WHERE p.sample_id = s.id AND LOWER(p.name) = LOWER(?)), 0)""",
    "process_count": """(SELECT COUNT(*) FROM process_samples p
                        WHERE p.sample_id = s.id AND LOWER(p.name) = LOWER(?))""",
}
MAX_ALERT_RULES_PER_HOST = 50
RULE_SELECT = """SELECT r.id, r.name, r.host_id, r.metric, r.process_name, r.threshold, r.sustained_minutes,
       r.enabled, r.updated_at,
       EXISTS(SELECT 1 FROM alerts a WHERE a.rule_id = r.id AND a.status <> 'resolved') AS firing
       FROM alert_rules r"""


def alert_metric_value_sql(metric: str) -> str:
    """SQL value of a metric for monitoring_samples aliased as s; process metrics take the process name as a parameter."""
    return _PROCESS_VALUE_SQL.get(metric, f"s.{metric}")


def alert_metric_params(rule: sqlite3.Row | dict[str, Any]) -> tuple[Any, ...]:
    return (rule["process_name"],) if rule["metric"] in _PROCESS_VALUE_SQL else ()


def alert_rule_summary(metric: str, process_name: str | None, threshold: float, sustained_minutes: int) -> str:
    label = ALERT_METRICS[metric][0]
    if process_name:
        label = f"{label} for {process_name}"
    return (f"{label} at or above {format_alert_value(metric, threshold)} "
            f"for {sustained_minutes} minute(s)")


def alert_rule_view(row: sqlite3.Row) -> dict[str, Any]:
    rule = dict(row)
    rule["enabled"] = bool(rule["enabled"])
    rule["firing"] = bool(rule["firing"])
    return rule


def format_alert_value(metric: str, value: float) -> str:
    return f"{value:.1f}%" if ALERT_METRICS[metric][1] == "%" else f"{value:g}"


@dataclass(frozen=True)
class HostActor:
    user_id: int
    is_admin: bool


def _owner_clause(actor: HostActor) -> tuple[str, tuple[Any, ...]]:
    # Non-admins see only hosts they registered; administrators see every host.
    if actor.is_admin:
        return "", ()
    return " AND owner_user_id = ?", (actor.user_id,)


def host_view(row: sqlite3.Row) -> dict[str, Any]:
    host = dict(row)
    host["enabled"] = bool(host["enabled"])
    if not host["enabled"]:
        connectivity = "disabled"
    elif host["last_heartbeat_at"] is None:
        connectivity = "never_seen"
    else:
        age = datetime.now(UTC) - datetime.fromisoformat(host["last_heartbeat_at"])
        connectivity = "online" if age.total_seconds() < 60 else "offline"
    host["connectivity"] = connectivity
    host.pop("collector_status_json", None)
    return host


def process_view(row: sqlite3.Row) -> dict[str, Any]:
    process = dict(row)
    process.pop("sample_id", None)
    for field in ("long_running", "zombie", "access_denied"):
        if process[field] is not None:
            process[field] = bool(process[field])
    return process


class MonitoringService:
    def __init__(self, pool: DatabasePool) -> None:
        self.pool = pool

    async def get_host(self, host_id: int, actor: HostActor) -> dict[str, Any]:
        scope, params = _owner_clause(actor)
        row = await self.pool.fetch_one(
            f"SELECT * FROM hosts WHERE id = ?{scope}", (host_id, *params)
        )
        if row is None:
            # Hosts outside the caller's scope look identical to missing hosts.
            raise HTTPException(404, "Host not found")
        return host_view(row)

    async def list_hosts(self, actor: HostActor) -> list[dict[str, Any]]:
        scope, params = _owner_clause(actor)
        rows = await self.pool.fetch_all(
            f"""SELECT h.*, m.sampled_at AS metrics_sampled_at, m.cpu_percent, m.memory_percent
                FROM hosts h
                LEFT JOIN monitoring_samples m ON m.id = (
                    SELECT id FROM monitoring_samples WHERE host_id = h.id
                    ORDER BY sampled_at DESC, id DESC LIMIT 1)
                WHERE 1 = 1{scope} ORDER BY h.name""",
            params,
        )
        return [host_view(row) for row in rows]

    async def register(self, request: HostCreate, actor: HostActor) -> dict[str, Any]:
        token = secrets.token_urlsafe(32)
        try:
            async with self.pool.transaction() as con:
                # Checked inside the write transaction so concurrent requests cannot both pass.
                conditions = ["name = ?"]
                params: list[Any] = [request.name]
                if request.deployment_type == "localhost":
                    conditions.append("deployment_type = 'localhost'")
                elif request.deployment_type == "wsl":
                    conditions.append("(deployment_type = 'wsl' AND wsl_distro = ?)")
                    params.append(request.wsl_distro)
                async with con.execute(
                    f"SELECT 1 FROM hosts WHERE owner_user_id = ? AND ({' OR '.join(conditions)}) LIMIT 1",
                    (actor.user_id, *params),
                ) as cursor:
                    if await cursor.fetchone() is not None:
                        raise HTTPException(409, DUPLICATE_HOST_MESSAGE)
                async with con.execute(
                    """INSERT INTO hosts(owner_user_id, name, platform, deployment_type, wsl_distro,
                                         long_running_seconds)
                       VALUES (?, ?, ?, ?, ?, ?) RETURNING *""",
                    (actor.user_id, request.name, request.platform, request.deployment_type,
                     request.wsl_distro, request.long_running_seconds),
                ) as cursor:
                    row = await cursor.fetchone()
                if row is None:
                    raise RuntimeError("Host insert returned no row")
                await con.execute(
                    "INSERT INTO collector_credentials(host_id, token_digest) VALUES (?, ?)",
                    (row["id"], hashlib.sha256(token.encode()).hexdigest()),
                )
        except sqlite3.IntegrityError as exc:
            if exc.sqlite_errorcode == sqlite3.SQLITE_CONSTRAINT_UNIQUE:
                raise HTTPException(409, DUPLICATE_HOST_MESSAGE) from exc
            raise
        return {"host": host_view(row), "collector_token": token}

    async def update(self, host_id: int, request: HostUpdate, actor: HostActor) -> dict[str, Any]:
        host = await self.get_host(host_id, actor)
        changes = request.model_dump(exclude_unset=True)
        columns = ", ".join(f"{key} = ?" for key in changes)
        await self.pool.execute(
            f"UPDATE hosts SET {columns} WHERE id = ?", (*changes.values(), host_id)
        )
        updated = await self.get_host(host_id, actor)
        if actor.is_admin and host["owner_user_id"] != actor.user_id:
            await self._notify_owner_of_settings_change(host, changes)
        return updated

    async def rotate_token(self, host_id: int, actor: HostActor) -> dict[str, Any]:
        host = await self.get_host(host_id, actor)
        token = secrets.token_urlsafe(32)
        async with self.pool.transaction() as con:
            await con.execute(
                "UPDATE collector_credentials SET revoked_at = ? WHERE host_id = ? AND revoked_at IS NULL",
                (utc_text(datetime.now(UTC)), host_id),
            )
            await con.execute(
                "INSERT INTO collector_credentials(host_id, token_digest) VALUES (?, ?)",
                (host_id, hashlib.sha256(token.encode()).hexdigest()),
            )
        if actor.is_admin and host["owner_user_id"] != actor.user_id:
            await self._notify(
                host,
                f"An administrator rotated the collector token for {host['name']}. The previous token "
                "no longer works and its collector stops. Open this machine and press Start collector "
                "(local machines), or rotate the token and update the collector (other machines).",
            )
        return {"host": host, "collector_token": token}

    async def _notify_owner_of_settings_change(self, host: dict[str, Any], changes: dict[str, Any]) -> None:
        changed = {key: value for key, value in changes.items() if host[key] != value}
        if not changed:
            return
        parts = []
        guidance = []
        if "enabled" in changed:
            if changed["enabled"]:
                parts.append("turned monitoring on")
                guidance.append("Start the collector if it is not running.")
            else:
                parts.append("turned monitoring off")
                guidance.append("Snapshots from this machine are rejected until monitoring is turned on again.")
        if "long_running_seconds" in changed:
            parts.append(f"set the long-running threshold to {changed['long_running_seconds']} seconds")
            guidance.append("The new threshold applies to new snapshots.")
        await self._notify(
            host,
            f"An administrator {'; '.join(parts)} for {host['name']}. {' '.join(guidance)}",
        )

    async def _notify(self, host: dict[str, Any], message: str) -> None:
        owner_id = host["owner_user_id"]
        if owner_id is None:
            return
        await self.pool.execute(
            "INSERT INTO host_notifications(recipient_user_id, host_id, message) VALUES (?, ?, ?)",
            (owner_id, host["id"], message),
        )

    async def list_notifications(self, user_id: int) -> list[dict[str, Any]]:
        rows = await self.pool.fetch_all(
            """SELECT id, host_id, message, created_at, read_at FROM host_notifications
               WHERE recipient_user_id = ? ORDER BY id DESC LIMIT 50""",
            (user_id,),
        )
        return [dict(row) for row in rows]

    async def mark_notification_read(self, notification_id: int, user_id: int) -> dict[str, Any]:
        row = await self.pool.fetch_one(
            "SELECT id FROM host_notifications WHERE id = ? AND recipient_user_id = ?",
            (notification_id, user_id),
        )
        if row is None:
            raise HTTPException(404, "Notification not found")
        await self.pool.execute(
            "UPDATE host_notifications SET read_at = COALESCE(read_at, ?) WHERE id = ?",
            (utc_text(datetime.now(UTC)), notification_id),
        )
        return {"id": notification_id, "read": True}

    async def mark_all_notifications_read(self, user_id: int) -> dict[str, Any]:
        await self.pool.execute(
            "UPDATE host_notifications SET read_at = ? WHERE recipient_user_id = ? AND read_at IS NULL",
            (utc_text(datetime.now(UTC)), user_id),
        )
        return {"read": True}

    async def list_alert_rules(self, host_id: int, actor: HostActor) -> list[dict[str, Any]]:
        await self.get_host(host_id, actor)
        rows = await self.pool.fetch_all(
            f"{RULE_SELECT} WHERE r.host_id = ? ORDER BY r.id", (host_id,)
        )
        return [alert_rule_view(row) for row in rows]

    async def create_alert_rule(self, host_id: int, request: AlertRuleUpsert, actor: HostActor) -> dict[str, Any]:
        host = await self.get_host(host_id, actor)
        self._validate_alert_rule(host, request)
        async with self.pool.transaction() as con:
            async with con.execute(
                "SELECT COUNT(*) AS total FROM alert_rules WHERE host_id = ? AND rule_type = 'machine_metric'",
                (host_id,),
            ) as cursor:
                total = (await cursor.fetchone())["total"]
            if total >= MAX_ALERT_RULES_PER_HOST:
                raise HTTPException(409, f"A machine can have at most {MAX_ALERT_RULES_PER_HOST} alert rules")
            async with con.execute(
                """INSERT INTO alert_rules(name, rule_type, host_id, metric, process_name, threshold,
                                           sustained_minutes, enabled, updated_at)
                   VALUES (?, 'machine_metric', ?, ?, ?, ?, ?, ?, ?) RETURNING id""",
                (request.name, host_id, request.metric, request.process_name, request.threshold,
                 request.sustained_minutes, int(request.enabled), utc_text(datetime.now(UTC))),
            ) as cursor:
                rule_id = (await cursor.fetchone())["id"]
        if actor.is_admin and host["owner_user_id"] != actor.user_id:
            await self._notify(
                host,
                f"An administrator created the alert '{request.name}' on {host['name']}: "
                f"{alert_rule_summary(request.metric, request.process_name, request.threshold, request.sustained_minutes)}.",
            )
        return await self._alert_rule_by_id(rule_id)

    async def update_alert_rule(
        self, host_id: int, rule_id: int, request: AlertRuleUpsert, actor: HostActor
    ) -> dict[str, Any]:
        host = await self.get_host(host_id, actor)
        self._validate_alert_rule(host, request)
        changed = await self.pool.execute(
            """UPDATE alert_rules SET name = ?, metric = ?, process_name = ?, threshold = ?,
                   sustained_minutes = ?, enabled = ?, updated_at = ?
               WHERE id = ? AND host_id = ? AND rule_type = 'machine_metric'""",
            (request.name, request.metric, request.process_name, request.threshold, request.sustained_minutes,
             int(request.enabled), utc_text(datetime.now(UTC)), rule_id, host_id),
        )
        if changed == 0:
            raise HTTPException(404, "Alert rule not found")
        if actor.is_admin and host["owner_user_id"] != actor.user_id:
            state = "turned on" if request.enabled else "turned off"
            await self._notify(
                host,
                f"An administrator updated the alert '{request.name}' on {host['name']}: "
                f"{alert_rule_summary(request.metric, request.process_name, request.threshold, request.sustained_minutes)}"
                f", and {state} the rule.",
            )
        return await self._alert_rule_by_id(rule_id)

    async def delete_alert_rule(self, host_id: int, rule_id: int, actor: HostActor) -> dict[str, Any]:
        host = await self.get_host(host_id, actor)
        row = await self.pool.fetch_one(
            "SELECT name FROM alert_rules WHERE id = ? AND host_id = ? AND rule_type = 'machine_metric'",
            (rule_id, host_id),
        )
        if row is None:
            raise HTTPException(404, "Alert rule not found")
        await self.pool.execute("DELETE FROM alert_rules WHERE id = ?", (rule_id,))
        if actor.is_admin and host["owner_user_id"] != actor.user_id:
            await self._notify(host, f"An administrator deleted the alert '{row['name']}' on {host['name']}.")
        return {"deleted": True}

    async def _alert_rule_by_id(self, rule_id: int) -> dict[str, Any]:
        row = await self.pool.fetch_one(f"{RULE_SELECT} WHERE r.id = ?", (rule_id,))
        if row is None:
            raise RuntimeError("Alert rule lookup returned no row")
        return alert_rule_view(row)

    def _validate_alert_rule(self, host: dict[str, Any], request: AlertRuleUpsert) -> None:
        metric = request.metric
        if metric == "zombie_count" and host["platform"] != "linux":
            raise HTTPException(422, "Zombie processes are only tracked on Linux machines")
        if metric == "process_cpu_percent":
            # A process's CPU share can exceed 100% on multi-core machines, so only the lower bound applies.
            if request.threshold <= 0:
                raise HTTPException(422, "Process CPU thresholds must be above 0")
        elif ALERT_METRICS[metric][1] == "%":
            if not 0 < request.threshold <= 100:
                raise HTTPException(422, "Percentage thresholds must be above 0 and at most 100")
        elif request.threshold < 1 or not request.threshold.is_integer():
            raise HTTPException(422, "Count thresholds must be whole numbers of at least 1")


    async def list_machine_alerts(self, host_id: int, limit: int, actor: HostActor) -> list[dict[str, Any]]:
        await self.get_host(host_id, actor)
        rows = await self.pool.fetch_all(
            """SELECT a.id, a.rule_id, a.host_id, r.metric, a.status, a.value, r.threshold,
                      a.triggered_at, a.resolved_at
               FROM alerts a JOIN alert_rules r ON r.id = a.rule_id
               WHERE a.host_id = ? ORDER BY a.id DESC LIMIT ?""",
            (host_id, limit),
        )
        return [dict(row) for row in rows]

    async def _evaluate_alert_rules(self, con: Any, host: dict[str, Any]) -> None:
        async with con.execute(
            "SELECT * FROM monitoring_samples WHERE host_id = ? ORDER BY sampled_at DESC, id DESC LIMIT 1",
            (host["id"],),
        ) as cursor:
            latest = await cursor.fetchone()
        if latest is None:
            return
        async with con.execute("SELECT * FROM alert_rules WHERE host_id = ? AND rule_type = 'machine_metric'",
                               (host["id"],)) as cursor:
            rules = await cursor.fetchall()
        now_text = latest["sampled_at"]
        for rule in rules:
            metric = rule["metric"]
            value = await self._rule_value(con, latest["id"], rule)
            if value is None:
                continue
            breaching = bool(rule["enabled"]) and value >= rule["threshold"]
            sustained = False
            if breaching:
                started = await self._breach_started_at(con, host["id"], rule, now_text)
                held = datetime.fromisoformat(now_text) - datetime.fromisoformat(started)
                sustained = held >= timedelta(minutes=rule["sustained_minutes"])
            async with con.execute(
                "SELECT id FROM alerts WHERE rule_id = ? AND status <> 'resolved'", (rule["id"],)
            ) as cursor:
                open_alert = await cursor.fetchone()
            if breaching and sustained and open_alert is None:
                message = (
                    f"Alert: {rule['name']} on {host['name']} is {format_alert_value(metric, value)}, "
                    f"{alert_rule_summary(metric, rule['process_name'], rule['threshold'], rule['sustained_minutes'])}."
                )
                await con.execute(
                    """INSERT INTO alerts(rule_id, host_id, status, message, value, triggered_at)
                       VALUES (?, ?, 'open', ?, ?, ?)""",
                    (rule["id"], host["id"], message, value, now_text),
                )
                await self._insert_notification(con, host, message)
            elif open_alert is not None and not breaching:
                await con.execute(
                    "UPDATE alerts SET status = 'resolved', resolved_at = ? WHERE id = ?",
                    (now_text, open_alert["id"]),
                )
                await self._insert_notification(
                    con, host,
                    f"Resolved: {rule['name']} on {host['name']} is back below "
                    f"{format_alert_value(metric, rule['threshold'])}.",
                )
            elif open_alert is not None:
                await con.execute("UPDATE alerts SET value = ? WHERE id = ?", (value, open_alert["id"]))

    async def _rule_value(self, con: Any, sample_id: int, rule: sqlite3.Row) -> float | None:
        async with con.execute(
            f"SELECT {alert_metric_value_sql(rule['metric'])} AS value FROM monitoring_samples s WHERE s.id = ?",
            (*alert_metric_params(rule), sample_id),
        ) as cursor:
            return (await cursor.fetchone())["value"]

    async def _breach_started_at(self, con: Any, host_id: int, rule: sqlite3.Row, until: str) -> str:
        # The breach began at the first breaching sample after the last sample that was not breaching.
        # NULL samples count as not breaching.
        expr = alert_metric_value_sql(rule["metric"])
        params = alert_metric_params(rule)
        threshold = rule["threshold"]
        async with con.execute(
            f"""SELECT MAX(s.sampled_at) AS last_clear FROM monitoring_samples s
                WHERE s.host_id = ? AND s.sampled_at < ? AND NOT COALESCE(({expr}) >= ?, 0)""",
            (host_id, until, *params, threshold),
        ) as cursor:
            clear = (await cursor.fetchone())["last_clear"]
        async with con.execute(
            f"""SELECT MIN(s.sampled_at) AS started FROM monitoring_samples s
                WHERE s.host_id = ? AND s.sampled_at <= ? AND s.sampled_at > ? AND ({expr}) >= ?""",
            (host_id, until, clear or "", *params, threshold),
        ) as cursor:
            started = (await cursor.fetchone())["started"]
        return started or until


    async def _insert_notification(self, con: Any, host: dict[str, Any], message: str) -> None:
        if host["owner_user_id"] is None:
            return
        await con.execute(
            "INSERT INTO host_notifications(recipient_user_id, host_id, message) VALUES (?, ?, ?)",
            (host["owner_user_id"], host["id"], message),
        )

    async def local_collector_status(self, host_id: int, actor: HostActor) -> dict[str, Any]:
        host = await self.get_host(host_id, actor)
        state = local_collectors.status(host_id)
        # A collector started outside the server is visible only through its heartbeats.
        if state["running"] or host["deployment_type"] != "localhost" or host["connectivity"] != "online":
            return state
        pid = await asyncio.to_thread(find_external_collector_pid)
        return {"running": True, "pid": pid, "source": "external"}

    async def start_local_collector(self, host_id: int, actor: HostActor) -> dict[str, Any]:
        host = await self.get_host(host_id, actor)
        if host["deployment_type"] != "localhost":
            raise HTTPException(400, "Only localhost hosts can be started from the server")
        if not host["enabled"]:
            raise HTTPException(409, "Host is disabled")

        async def issue_token() -> str:
            issued = await self.rotate_token(host_id, actor)
            return issued["collector_token"]

        return await local_collectors.start(host_id, issue_token)

    async def stop_local_collector(self, host_id: int, actor: HostActor) -> dict[str, Any]:
        state = await self.local_collector_status(host_id, actor)
        if state["source"] == "external":
            raise HTTPException(409, "This collector was started outside ServerPulse. Stop it from the terminal running it.")
        return await local_collectors.stop(host_id)

    async def collector_host(self, token: str) -> dict[str, Any]:
        row = await self.pool.fetch_one(
            """SELECT h.* FROM hosts h JOIN collector_credentials c ON c.host_id = h.id
               WHERE c.token_digest = ? AND c.revoked_at IS NULL AND h.enabled = 1""",
            (hashlib.sha256(token.encode()).hexdigest(),),
        )
        if row is None:
            raise HTTPException(401, "Invalid or disabled collector credential",
                                headers={"WWW-Authenticate": "Bearer"})
        return host_view(row)

    async def ingest(self, host: dict[str, Any], batch: MonitoringBatch) -> dict[str, Any]:
        if batch.platform != host["platform"]:
            raise HTTPException(422, "Collector platform does not match registered host")
        digest = hashlib.sha256(batch.model_dump_json().encode()).hexdigest()
        now = datetime.now(UTC)
        received = utc_text(now)
        host_id = host["id"]
        async with self.pool.transaction() as con:
            async with con.execute(
                "SELECT * FROM monitoring_receipts WHERE host_id = ? AND batch_id = ?",
                (host_id, str(batch.batch_id)),
            ) as cursor:
                receipt = await cursor.fetchone()
            if receipt is not None:
                if receipt["payload_digest"] != digest:
                    raise HTTPException(409, "Batch ID was already used with different content")
                return {"sample_id": receipt["sample_id"], "duplicate": True}
            if batch.sampled_at < now - timedelta(hours=24):
                raise HTTPException(422, "Snapshot is older than the 24-hour retention window")
            processes = []
            long_count = 0
            zombie_count = 0 if batch.platform == "linux" else None
            for process in batch.processes:
                runtime = (batch.sampled_at - process.create_time).total_seconds() if process.create_time else None
                long_running = runtime >= host["long_running_seconds"] if runtime is not None else None
                zombie = process.status == "zombie" if batch.platform == "linux" and process.status else None
                long_count += bool(long_running)
                if zombie_count is not None:
                    zombie_count += bool(zombie)
                processes.append((
                    process.pid, utc_text(process.create_time) if process.create_time else None,
                    process.name, process.status, process.cpu_percent, process.rss_bytes,
                    process.memory_percent, runtime, long_running, zombie, process.access_denied,
                ))
            used = batch.memory_total_bytes - batch.memory_available_bytes
            async with con.execute(
                """INSERT INTO monitoring_samples
                   (host_id,sampled_at,received_at,cpu_percent,memory_total_bytes,memory_available_bytes,
                    memory_used_bytes,memory_percent,process_count,denied_count,vanished_count,
                    long_running_count,zombie_count) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) RETURNING id""",
                (host_id, utc_text(batch.sampled_at), received, batch.cpu_percent,
                 batch.memory_total_bytes, batch.memory_available_bytes, used,
                 used / batch.memory_total_bytes * 100, len(processes), batch.denied_count,
                 batch.vanished_count, long_count, zombie_count),
            ) as cursor:
                sample = await cursor.fetchone()
            if sample is None:
                raise RuntimeError("Monitoring insert returned no sample")
            sample_id = sample["id"]
            await con.executemany(
                """INSERT INTO process_samples
                   (sample_id,pid,create_time,name,status,cpu_percent,rss_bytes,memory_percent,
                    runtime_seconds,long_running,zombie,access_denied) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                [(sample_id, *process) for process in processes],
            )
            await con.execute(
                """INSERT INTO monitoring_receipts(host_id,batch_id,payload_digest,sample_id,accepted_at)
                   VALUES (?,?,?,?,?)""",
                (host_id, str(batch.batch_id), digest, sample_id, received),
            )
            await con.execute("UPDATE hosts SET last_heartbeat_at = ? WHERE id = ?", (received, host_id))
            await self._evaluate_alert_rules(con, host)
            await con.execute(
                "DELETE FROM monitoring_samples WHERE host_id = ? AND sampled_at < ?",
                (host_id, utc_text(now - timedelta(hours=24))),
            )
            await con.execute(
                "DELETE FROM monitoring_receipts WHERE host_id = ? AND accepted_at < ?",
                (host_id, utc_text(now - timedelta(days=7))),
            )
        return {"sample_id": sample_id, "duplicate": False}

    async def ingest_logs(self, host: dict[str, Any], batch: LogBatch) -> dict[str, Any]:
        if batch.platform != host["platform"]:
            raise HTTPException(422, "Collector platform does not match registered host")
        digest = hashlib.sha256(batch.model_dump_json().encode()).hexdigest()
        now = datetime.now(UTC)
        received = utc_text(now)
        host_id = host["id"]
        async with self.pool.transaction() as con:
            async with con.execute(
                "SELECT * FROM ingestion_receipts WHERE host_id = ? AND batch_id = ?",
                (host_id, str(batch.batch_id)),
            ) as cursor:
                receipt = await cursor.fetchone()
            if receipt is not None:
                if receipt["payload_digest"] != digest:
                    raise HTTPException(409, "Batch ID was already used with different content")
                return {**json.loads(receipt["response_json"]), "duplicate": True}

            source_ids: dict[tuple[str, str, str], int] = {}
            for report in batch.sources:
                succeeded = received if report.status == "ok" else None
                async with con.execute(
                    """INSERT INTO log_sources(host_id, source_type, category, channel, last_status,
                                               last_error, last_attempt_at, last_success_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT (host_id, source_type, channel, category) DO UPDATE SET
                           last_status = excluded.last_status,
                           last_error = excluded.last_error,
                           last_attempt_at = excluded.last_attempt_at,
                           last_success_at = COALESCE(excluded.last_success_at, log_sources.last_success_at)
                       RETURNING id""",
                    (host_id, report.source_type, report.category, report.channel, report.status,
                     report.error, received, succeeded),
                ) as cursor:
                    source = await cursor.fetchone()
                if source is None:
                    raise RuntimeError("Log source upsert returned no row")
                source_ids[(report.source_type, report.category, report.channel)] = source["id"]
                # The checkpoint is acknowledged in the same transaction as the records it covers.
                if report.status == "ok" and report.checkpoint is not None:
                    await con.execute(
                        "UPDATE log_sources SET acknowledged_checkpoint_json = ? WHERE id = ?",
                        (json.dumps(report.checkpoint), source["id"]),
                    )

            service_ids: dict[str, int] = {}
            units = {record.unit for record in batch.records if record.unit and record.unit.endswith(".service")}
            for unit in sorted(units):
                await con.execute(
                    "INSERT OR IGNORE INTO monitored_services(host_id, service_name) VALUES (?, ?)",
                    (host_id, unit),
                )
                async with con.execute(
                    "SELECT id FROM monitored_services WHERE host_id = ? AND service_name = ?",
                    (host_id, unit),
                ) as cursor:
                    service = await cursor.fetchone()
                if service is None:
                    raise RuntimeError("Monitored service lookup returned no row")
                service_ids[unit] = service["id"]

            # Windows events carry no unit, so SCM events link to inventory by display or service name.
            references = {record.service_reference.casefold() for record in batch.records
                          if record.service_reference and not record.unit}
            reference_ids: dict[str, int] = {}
            if references:
                async with con.execute(
                    "SELECT id, service_name, display_name FROM monitored_services WHERE host_id = ?",
                    (host_id,),
                ) as cursor:
                    known = await cursor.fetchall()
                for row in known:
                    reference_ids.setdefault(row["service_name"].casefold(), row["id"])
                for row in known:
                    if row["display_name"]:
                        reference_ids.setdefault(row["display_name"].casefold(), row["id"])

            def link_service(record) -> int | None:
                if record.unit:
                    return service_ids.get(record.unit)
                if record.service_reference:
                    return reference_ids.get(record.service_reference.casefold())
                return None

            rows = [
                (host_id, source_ids[(record.source_type, record.category, record.channel)],
                 record.source_record_id, record.category, utc_text(record.occurred_at),
                 utc_text(batch.collected_at), received, record.timestamp_quality, record.severity,
                 record.native_severity, record.event_id, record.provider, record.message,
                 link_service(record))
                for record in batch.records
            ]
            accepted = 0
            if rows:
                cursor = await con.executemany(
                    """INSERT OR IGNORE INTO log_events(host_id, source_id, source_record_id, category,
                                                        occurred_at, collected_at, received_at,
                                                        timestamp_quality, severity, native_severity,
                                                        event_id, provider, message, service_id)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    rows,
                )
                accepted = cursor.rowcount
            response = {"accepted": accepted, "duplicates": len(rows) - accepted}
            await con.execute(
                """INSERT INTO ingestion_receipts(host_id, batch_id, batch_type, payload_digest,
                                                  response_json, committed_at)
                   VALUES (?, ?, 'logs', ?, ?, ?)""",
                (host_id, str(batch.batch_id), digest, json.dumps(response), received),
            )
            # A log batch proves the collector is running, so it counts as a heartbeat.
            await con.execute("UPDATE hosts SET last_heartbeat_at = ? WHERE id = ?", (received, host_id))
            await con.execute(
                "DELETE FROM log_events WHERE host_id = ? AND occurred_at < ?",
                (host_id, utc_text(now - LOG_RETENTION)),
            )
            await con.execute(
                "DELETE FROM ingestion_receipts WHERE host_id = ? AND batch_type = 'logs' AND committed_at < ?",
                (host_id, utc_text(now - timedelta(days=7))),
            )
        return {**response, "duplicate": False}

    async def list_log_sources(self, host_id: int, actor: HostActor) -> list[dict[str, Any]]:
        await self.get_host(host_id, actor)
        rows = await self.pool.fetch_all(
            """SELECT id, source_type, category, channel, enabled, last_status, last_error,
                      last_attempt_at, last_success_at
               FROM log_sources WHERE host_id = ? ORDER BY source_type, channel""",
            (host_id,),
        )
        return [{**dict(row), "enabled": bool(row["enabled"])} for row in rows]

    async def ingest_services(self, host: dict[str, Any], batch: ServiceBatch) -> dict[str, Any]:
        if batch.platform != host["platform"]:
            raise HTTPException(422, "Collector platform does not match registered host")
        digest = hashlib.sha256(batch.model_dump_json().encode()).hexdigest()
        now = datetime.now(UTC)
        received = utc_text(now)
        host_id = host["id"]
        async with self.pool.transaction() as con:
            async with con.execute(
                "SELECT * FROM ingestion_receipts WHERE host_id = ? AND batch_id = ?",
                (host_id, str(batch.batch_id)),
            ) as cursor:
                receipt = await cursor.fetchone()
            if receipt is not None:
                if receipt["payload_digest"] != digest:
                    raise HTTPException(409, "Batch ID was already used with different content")
                return {**json.loads(receipt["response_json"]), "duplicate": True}

            rows = [
                (host_id, service.service_name, service.display_name, service.current_state,
                 service.native_state, received)
                for service in batch.services
            ]
            if rows:
                await con.executemany(
                    """INSERT INTO monitored_services(host_id, service_name, display_name, current_state,
                                                      native_state, last_observation_sequence, last_status,
                                                      last_checked_at, last_error)
                       VALUES (?, ?, ?, ?, ?, 1, 'ok', ?, NULL)
                       ON CONFLICT (host_id, service_name) DO UPDATE SET
                           display_name = excluded.display_name,
                           current_state = excluded.current_state,
                           native_state = excluded.native_state,
                           last_observation_sequence = monitored_services.last_observation_sequence + 1,
                           last_status = excluded.last_status,
                           last_checked_at = excluded.last_checked_at,
                           last_error = NULL""",
                    rows,
                )
            response = {"accepted": len(rows)}
            await con.execute(
                """INSERT INTO ingestion_receipts(host_id, batch_id, batch_type, payload_digest,
                                                  response_json, committed_at)
                   VALUES (?, ?, 'services', ?, ?, ?)""",
                (host_id, str(batch.batch_id), digest, json.dumps(response), received),
            )
            # A service inventory proves the collector is running, so it counts as a heartbeat.
            await con.execute("UPDATE hosts SET last_heartbeat_at = ? WHERE id = ?", (received, host_id))
            await con.execute(
                "DELETE FROM ingestion_receipts WHERE host_id = ? AND batch_type = 'services' AND committed_at < ?",
                (host_id, utc_text(now - timedelta(days=7))),
            )
        return {**response, "duplicate": False}

    async def list_services(self, host_id: int, actor: HostActor) -> list[dict[str, Any]]:
        await self.get_host(host_id, actor)
        rows = await self.pool.fetch_all(
            """SELECT sv.id, sv.service_name, sv.display_name, sv.current_state, sv.native_state,
                      sv.last_status, sv.last_checked_at, sv.last_error,
                      COUNT(e.id) AS log_count, MAX(e.occurred_at) AS last_log_at
               FROM monitored_services sv
               LEFT JOIN log_events e ON e.service_id = sv.id
               WHERE sv.host_id = ?
               GROUP BY sv.id
               ORDER BY sv.service_name""",
            (host_id,),
        )
        return [dict(row) for row in rows]

    async def list_logs(
        self, host_id: int, source_id: int | None, min_severity: str | None,
        since: datetime | None, until: datetime | None, keyword: str,
        offset: int, limit: int, actor: HostActor,
    ) -> dict[str, Any]:
        await self.get_host(host_id, actor)
        conditions = ["e.host_id = ?"]
        params: list[Any] = [host_id]
        if source_id is not None:
            conditions.append("e.source_id = ?")
            params.append(source_id)
        if min_severity is not None:
            ranks = SEVERITY_ORDER[SEVERITY_ORDER.index(min_severity):]
            if min_severity == "debug":
                ranks = (*ranks, "unknown")
            conditions.append(f"e.severity IN ({', '.join('?' for _ in ranks)})")
            params.extend(ranks)
        if since is not None:
            conditions.append("e.occurred_at >= ?")
            params.append(utc_text(since))
        if until is not None:
            conditions.append("e.occurred_at <= ?")
            params.append(utc_text(until))
        if keyword:
            conditions.append("instr(lower(e.message), lower(?)) > 0")
            params.append(keyword)
        where = " AND ".join(conditions)
        async with self.pool.connection() as con:
            await con.execute("BEGIN")
            async with con.execute(
                f"SELECT COUNT(*) FROM log_events e WHERE {where}", params,
            ) as cursor:
                count = await cursor.fetchone()
            async with con.execute(
                f"""SELECT e.id, e.source_id, s.source_type, s.category, s.channel, e.source_record_id,
                           e.occurred_at, e.collected_at, e.timestamp_quality, e.severity,
                           e.native_severity, e.event_id, e.provider, e.message, e.service_id,
                           sv.service_name
                    FROM log_events e
                    JOIN log_sources s ON s.id = e.source_id
                    LEFT JOIN monitored_services sv ON sv.id = e.service_id
                    WHERE {where} ORDER BY e.occurred_at DESC, e.id DESC LIMIT ? OFFSET ?""",
                (*params, limit, offset),
            ) as cursor:
                rows = await cursor.fetchall()
        return {"total": count[0] if count else 0, "items": [dict(row) for row in rows]}

    async def latest(self, host_id: int, actor: HostActor) -> dict[str, Any]:
        host = await self.get_host(host_id, actor)
        row = await self.pool.fetch_one(
            "SELECT * FROM monitoring_samples WHERE host_id = ? ORDER BY sampled_at DESC, id DESC LIMIT 1",
            (host_id,),
        )
        sample = dict(row) if row else None
        if sample:
            sample.pop("host_id")
        return {"host": host, "latest": sample}

    async def metrics(self, host_id: int, limit: int, actor: HostActor) -> list[dict[str, Any]]:
        await self.get_host(host_id, actor)
        rows = await self.pool.fetch_all(
            """SELECT * FROM monitoring_samples WHERE host_id = ? AND sampled_at >= ?
               ORDER BY sampled_at DESC, id DESC LIMIT ?""",
            (host_id, utc_text(datetime.now(UTC) - timedelta(hours=24)), limit),
        )
        return [{key: value for key, value in dict(row).items() if key != "host_id"}
                for row in reversed(rows)]

    async def processes(
        self, host_id: int, offset: int, limit: int, search: str,
        long_running: bool, zombie: bool, sort: str, actor: HostActor,
    ) -> dict[str, Any]:
        await self.get_host(host_id, actor)
        async with self.pool.connection() as con:
            await con.execute("BEGIN")
            async with con.execute(
                "SELECT id, sampled_at FROM monitoring_samples WHERE host_id = ? ORDER BY sampled_at DESC, id DESC LIMIT 1",
                (host_id,),
            ) as cursor:
                latest = await cursor.fetchone()
            if latest is None:
                return {"sample_id": None, "sampled_at": None, "total": 0, "items": []}
            conditions = ["sample_id = ?", "instr(lower(COALESCE(name,'')), lower(?)) > 0"]
            params: list[Any] = [latest["id"], search]
            if long_running:
                conditions.append("long_running = 1")
            if zombie:
                conditions.append("zombie = 1")
            where = " AND ".join(conditions)
            order = {"cpu": "cpu_percent DESC", "memory": "rss_bytes DESC",
                     "runtime": "runtime_seconds DESC", "name": "name COLLATE NOCASE ASC"}[sort]
            async with con.execute(f"SELECT COUNT(*) FROM process_samples WHERE {where}", params) as cursor:
                count = await cursor.fetchone()
            async with con.execute(
                f"SELECT * FROM process_samples WHERE {where} ORDER BY {order}, pid LIMIT ? OFFSET ?",
                (*params, limit, offset),
            ) as cursor:
                rows = await cursor.fetchall()
        return {"sample_id": latest["id"], "sampled_at": latest["sampled_at"],
                "total": count[0] if count else 0, "items": [process_view(row) for row in rows]}

    async def process_history(
        self, host_id: int, pid: int, create_time: datetime, limit: int, actor: HostActor,
    ) -> dict[str, Any]:
        await self.get_host(host_id, actor)
        rows = await self.pool.fetch_all(
            """SELECT p.*, s.sampled_at FROM process_samples p
               JOIN monitoring_samples s ON s.id = p.sample_id
               WHERE s.host_id = ? AND p.pid = ? AND p.create_time = ? AND s.sampled_at >= ?
               ORDER BY s.sampled_at DESC, s.id DESC LIMIT ?""",
            (host_id, pid, utc_text(create_time), utc_text(datetime.now(UTC) - timedelta(hours=24)), limit),
        )
        return {"items": [process_view(row) for row in reversed(rows)]}
