import asyncio
import contextlib
import io
import logging
import secrets
import sqlite3
import tarfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import asyncssh
from fastapi import HTTPException

from app.conf.config import BACKEND_DIR, settings
from app.db.db_pool import DatabasePool
from app.schemas.monitoring import HostCreate, utc_text
from app.schemas.ssh_collector import SSHInstallRequest, SSHScanRequest
from app.services.monitoring_service import HostActor, MonitoringService
from app.services.secret_box import get_secret_box

logger = logging.getLogger(__name__)

CONNECT_TIMEOUT = 20
COMMAND_TIMEOUT = 600
MAX_RETRY_DELAY = 300
BUNDLE_FILES = ("app/__init__.py", "app/collector.py", "app/schemas/monitoring.py")
# The collector is pushed through the SSH reverse tunnel, so its traffic is encrypted end to end.
RUN_SCRIPT = """#!/bin/sh
cd "$(dirname "$0")" || exit 1
if [ -f collector.pid ] && kill -0 "$(cat collector.pid)" 2>/dev/null; then
  exit 0
fi
SERVERPULSE_COLLECTOR_TOKEN="$(cat token)" nohup venv/bin/python -m app.collector \\
  --url "http://127.0.0.1:{remote_port}" --allow-http --state-file state.json \\
  >> collector.log 2>&1 < /dev/null &
echo $! > collector.pid
"""
STOP_COMMAND = "cd {remote_dir} && if [ -f collector.pid ]; then kill \"$(cat collector.pid)\" 2>/dev/null; rm -f collector.pid; fi"


class RemoteStepError(RuntimeError):
    pass


@dataclass(frozen=True)
class SSHTarget:
    address: str
    port: int
    username: str
    auth_method: str
    secret: str = field(repr=False)
    host_key: str


def _target(row: sqlite3.Row) -> SSHTarget:
    return SSHTarget(
        address=row["address"],
        port=row["port"],
        username=row["username"],
        auth_method=row["auth_method"],
        secret=get_secret_box().decrypt(row["encrypted_secret"]),
        host_key=row["host_key"],
    )


async def _fetch_host_key(address: str, port: int) -> asyncssh.SSHKey:
    try:
        key = await asyncio.wait_for(asyncssh.get_server_host_key(host=address, port=port), CONNECT_TIMEOUT)
    except (asyncssh.Error, OSError, TimeoutError) as exc:
        raise HTTPException(502, f"Could not reach {address}:{port} over SSH") from exc
    if key is None:
        raise HTTPException(502, f"Could not read the host key from {address}:{port}")
    return key


async def _open(target: SSHTarget) -> asyncssh.SSHClientConnection:
    # Only the host key captured at install time is trusted; any other key fails the connection.
    pattern = target.address if target.port == 22 else f"[{target.address}]:{target.port}"
    known_hosts = asyncssh.import_known_hosts(f"{pattern} {target.host_key}\n")
    client_keys: list[asyncssh.SSHKey] = []
    password = None
    if target.auth_method == "private_key":
        try:
            client_keys = [asyncssh.import_private_key(target.secret)]
        except asyncssh.KeyImportError as exc:
            raise HTTPException(422, "Private key could not be read. Use an unencrypted OpenSSH or PEM key.") from exc
    else:
        password = target.secret
    try:
        return await asyncio.wait_for(
            asyncssh.connect(
                host=target.address, port=target.port, username=target.username,
                known_hosts=known_hosts, client_keys=client_keys, password=password, agent_path=None,
            ),
            CONNECT_TIMEOUT,
        )
    except (asyncssh.Error, OSError, TimeoutError) as exc:
        raise HTTPException(502, f"Could not connect to {target.address}:{target.port} over SSH") from exc


async def _run(conn: asyncssh.SSHClientConnection, command: str, input_data: bytes | None = None) -> str:
    try:
        result = await conn.run(command, check=False, input=input_data, timeout=COMMAND_TIMEOUT)
    except (asyncssh.Error, OSError, TimeoutError) as exc:
        raise RemoteStepError(str(exc)) from exc
    if result.exit_status != 0:
        detail = (result.stderr or result.stdout or "").strip()[-300:]
        raise RemoteStepError(detail or f"exit status {result.exit_status}")
    return result.stdout or ""


async def _probe(conn: asyncssh.SSHClientConnection) -> None:
    try:
        os_name = (await conn.run("uname -s", check=False, timeout=COMMAND_TIMEOUT)).stdout or ""
    except (asyncssh.Error, OSError, TimeoutError) as exc:
        raise HTTPException(502, "Could not run commands on the server") from exc
    if os_name.strip() != "Linux":
        raise HTTPException(422, "Only Linux servers can be installed over SSH")
    try:
        version = await _run(conn, "python3 -c 'import sys; print(sys.version_info[0], sys.version_info[1])'")
    except RemoteStepError as exc:
        raise HTTPException(422, "python3 is required on the server") from exc
    if tuple(int(part) for part in version.split()[:2]) < (3, 11):
        raise HTTPException(422, "Python 3.11 or newer is required on the server")


def _bundle(remote_port: int) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        for relative in BUNDLE_FILES:
            data = (BACKEND_DIR / relative).read_bytes()
            info = tarfile.TarInfo(relative)
            info.size = len(data)
            info.mode = 0o644
            archive.addfile(info, io.BytesIO(data))
        script = RUN_SCRIPT.format(remote_port=remote_port).encode()
        info = tarfile.TarInfo("run.sh")
        info.size = len(script)
        info.mode = 0o755
        archive.addfile(info, io.BytesIO(script))
    return buffer.getvalue()


async def _deploy(conn: asyncssh.SSHClientConnection, remote_dir: str, remote_port: int, token: str) -> None:
    await _run(conn, f"mkdir -p {remote_dir} && tar -xf - -C {remote_dir}", _bundle(remote_port))
    await _run(conn, f"cd {remote_dir} && python3 -m venv venv && venv/bin/pip install --quiet psutil pydantic")
    await _run(conn, f"umask 077 && cat > {remote_dir}/token", token.encode())
    await _run(conn, f"sh {remote_dir}/run.sh")


async def _supervise(pool: DatabasePool, host_id: int, connected: set[int]) -> None:
    """Keeps a reverse tunnel to the remote collector open and restarts the collector after reconnects."""
    delay = 1.0
    while True:
        row = await pool.fetch_one("SELECT * FROM ssh_collectors WHERE host_id = ?", (host_id,))
        if row is None or row["desired_state"] != "running":
            return
        try:
            conn = await _open(_target(row))
            try:
                await _run(conn, f"sh {row['remote_dir']}/run.sh")
                await conn.forward_remote_port("127.0.0.1", row["remote_port"], "127.0.0.1", settings.port)
                connected.add(host_id)
                delay = 1.0
                await conn.wait_closed()
            finally:
                conn.close()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("SSH collector for host %s is unavailable: %s", host_id, exc)
        finally:
            connected.discard(host_id)
        await asyncio.sleep(delay)
        delay = min(delay * 2, MAX_RETRY_DELAY)


class SSHSupervisorManager:
    """Runs one reconnecting supervisor task per SSH-managed host while the backend is up."""

    def __init__(self) -> None:
        self._tasks: dict[int, asyncio.Task[None]] = {}
        self._connected: set[int] = set()
        self.lock = asyncio.Lock()

    def is_connected(self, host_id: int) -> bool:
        return host_id in self._connected

    def ensure(self, pool: DatabasePool, host_id: int) -> None:
        task = self._tasks.get(host_id)
        if task is None or task.done():
            self._tasks[host_id] = asyncio.create_task(_supervise(pool, host_id, self._connected))

    async def cancel(self, host_id: int) -> None:
        task = self._tasks.pop(host_id, None)
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._connected.discard(host_id)

    async def restore(self, pool: DatabasePool) -> None:
        rows = await pool.fetch_all("SELECT host_id FROM ssh_collectors WHERE desired_state = 'running'")
        for row in rows:
            self.ensure(pool, row["host_id"])

    async def shutdown(self) -> None:
        for host_id in list(self._tasks):
            await self.cancel(host_id)


ssh_supervisors = SSHSupervisorManager()


class SSHCollectorService:
    def __init__(self, pool: DatabasePool) -> None:
        self.pool = pool
        self.monitoring = MonitoringService(pool)

    async def scan(self, request: SSHScanRequest) -> dict[str, Any]:
        key = await _fetch_host_key(request.address, request.port)
        return {
            "address": request.address,
            "port": request.port,
            "host_key_algorithm": key.algorithm,
            "host_key_fingerprint": key.get_fingerprint(),
        }

    async def install(self, request: SSHInstallRequest, actor: HostActor) -> dict[str, Any]:
        key = await _fetch_host_key(request.address, request.port)
        if key.get_fingerprint() != request.host_key_fingerprint:
            raise HTTPException(409, "The server's host key changed since you confirmed it. Scan the server again.")
        target = SSHTarget(
            address=request.address,
            port=request.port,
            username=request.username,
            auth_method=request.auth_method,
            secret=request.secret,
            host_key=key.export_public_key().decode().strip(),
        )
        conn = await _open(target)
        try:
            await _probe(conn)
            created = await self.monitoring.register(
                HostCreate(name=request.name, platform="linux", deployment_type="external",
                           long_running_seconds=request.long_running_seconds),
                actor,
            )
            host_id = created["host"]["id"]
            remote_dir = f"serverpulse/host-{host_id}"
            remote_port = secrets.randbelow(40000) + 20000
            try:
                await _deploy(conn, remote_dir, remote_port, created["collector_token"])
                await self.pool.execute(
                    """INSERT INTO ssh_collectors(host_id, address, port, username, auth_method,
                                                  encrypted_secret, host_key, remote_dir, remote_port,
                                                  desired_state)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'running')""",
                    (host_id, target.address, target.port, target.username, target.auth_method,
                     get_secret_box().encrypt(target.secret), target.host_key, remote_dir, remote_port),
                )
            except Exception as exc:
                # Remove the host so a failed install does not leave an unreachable machine registered.
                await self.pool.execute("DELETE FROM hosts WHERE id = ?", (host_id,))
                if isinstance(exc, RemoteStepError):
                    raise HTTPException(502, f"Remote setup failed: {exc}") from exc
                raise
        finally:
            conn.close()
            await conn.wait_closed()
        ssh_supervisors.ensure(self.pool, host_id)
        return await self.status(host_id, actor)

    async def status(self, host_id: int, actor: HostActor) -> dict[str, Any]:
        host = await self.monitoring.get_host(host_id, actor)
        row = await self._row(host_id)
        return {
            "host": host,
            "ssh": {
                "address": row["address"],
                "port": row["port"],
                "username": row["username"],
                "auth_method": row["auth_method"],
                "remote_port": row["remote_port"],
                "desired_state": row["desired_state"],
                "connected": ssh_supervisors.is_connected(host_id),
            },
        }

    async def start(self, host_id: int, actor: HostActor) -> dict[str, Any]:
        await self.monitoring.get_host(host_id, actor)
        row = await self._row(host_id)
        target = _target(row)
        async with ssh_supervisors.lock:
            conn = await _open(target)
            try:
                # The old collector keeps the previous token until it is stopped, so stop it before issuing a new one.
                issued = await self.monitoring.rotate_token(host_id, actor)
                await self._stop_remote(conn, row["remote_dir"])
                await _run(conn, f"umask 077 && cat > {row['remote_dir']}/token",
                           issued["collector_token"].encode())
                await _run(conn, f"sh {row['remote_dir']}/run.sh")
            except RemoteStepError as exc:
                raise HTTPException(502, f"Remote start failed: {exc}") from exc
            finally:
                conn.close()
                await conn.wait_closed()
            await self.pool.execute(
                "UPDATE ssh_collectors SET desired_state = 'running', updated_at = ? WHERE host_id = ?",
                (utc_text(datetime.now(UTC)), host_id),
            )
            ssh_supervisors.ensure(self.pool, host_id)
        return await self.status(host_id, actor)

    async def stop(self, host_id: int, actor: HostActor) -> dict[str, Any]:
        await self.monitoring.get_host(host_id, actor)
        row = await self._row(host_id)
        async with ssh_supervisors.lock:
            await ssh_supervisors.cancel(host_id)
            await self.pool.execute(
                "UPDATE ssh_collectors SET desired_state = 'stopped', updated_at = ? WHERE host_id = ?",
                (utc_text(datetime.now(UTC)), host_id),
            )
            remote_stopped = True
            try:
                conn = await _open(_target(row))
                try:
                    await self._stop_remote(conn, row["remote_dir"])
                finally:
                    conn.close()
                    await conn.wait_closed()
            except (HTTPException, RemoteStepError) as exc:
                # The collector keeps running until the machine is reachable again; stopping it later is safe.
                logger.warning("Could not stop the remote collector for host %s: %s", host_id, exc)
                remote_stopped = False
        result = await self.status(host_id, actor)
        result["remote_stopped"] = remote_stopped
        return result

    async def _stop_remote(self, conn: asyncssh.SSHClientConnection, remote_dir: str) -> None:
        await _run(conn, STOP_COMMAND.format(remote_dir=remote_dir))

    async def _row(self, host_id: int) -> sqlite3.Row:
        row = await self.pool.fetch_one("SELECT * FROM ssh_collectors WHERE host_id = ?", (host_id,))
        if row is None:
            raise HTTPException(400, "Host is not connected over SSH")
        return row
