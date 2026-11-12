import asyncio
import atexit
import os
import subprocess
import sys
import tempfile
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import psutil

from app.conf.config import BACKEND_DIR, settings

STATE_DIR = Path(tempfile.gettempdir()) / "serverpulse-local-collectors"


class LocalCollectorManager:
    """Runs the push collector for localhost hosts as child processes of the backend."""

    def __init__(self) -> None:
        self._processes: dict[int, subprocess.Popen[bytes]] = {}
        self._lock = asyncio.Lock()
        atexit.register(self.stop_all)

    def _running(self, host_id: int) -> bool:
        process = self._processes.get(host_id)
        if process is None:
            return False
        if process.poll() is not None:
            del self._processes[host_id]
            return False
        return True

    def status(self, host_id: int) -> dict[str, Any]:
        running = self._running(host_id)
        return {
            "running": running,
            "pid": self._processes[host_id].pid if running else None,
            "source": "server" if running else None,
        }

    async def start(self, host_id: int, issue_token: Callable[[], Awaitable[str]]) -> dict[str, Any]:
        async with self._lock:
            if self._running(host_id):
                return self.status(host_id)
            token = await issue_token()
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            env = {**os.environ, "SERVERPULSE_COLLECTOR_TOKEN": token}
            command = [
                sys.executable, "-m", "app.collector",
                "--url", f"http://127.0.0.1:{settings.port}",
                "--state-file", str(STATE_DIR / f"host-{host_id}-state.json"),
                "--logs",
            ]
            with (STATE_DIR / f"host-{host_id}.log").open("ab") as log:
                self._processes[host_id] = subprocess.Popen(
                    command, cwd=BACKEND_DIR, env=env, stdout=log, stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
            return self.status(host_id)

    async def stop(self, host_id: int) -> dict[str, Any]:
        async with self._lock:
            process = self._processes.pop(host_id, None)
            if process is not None and process.poll() is None:
                await asyncio.to_thread(_terminate, process)
            return {"running": False, "pid": None, "source": None}

    def stop_all(self) -> None:
        for process in self._processes.values():
            if process.poll() is None:
                _terminate(process)
        self._processes.clear()


def find_external_collector_pid() -> int | None:
    """Return the PID of a collector started outside the server, if one is visible in the process table."""
    candidates = []
    for process in psutil.process_iter(["pid", "ppid", "cmdline"]):
        cmdline = " ".join(process.info["cmdline"] or [])
        if "app.collector" in cmdline or "collect-host" in cmdline:
            candidates.append(process.info)
    # Launchers such as `uv run` spawn the real collector as a child; report the innermost match.
    matched = {info["pid"] for info in candidates}
    innermost = [info["pid"] for info in candidates if info["ppid"] not in matched]
    return innermost[0] if innermost else None


def _terminate(process: subprocess.Popen[bytes]) -> None:
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


local_collectors = LocalCollectorManager()
