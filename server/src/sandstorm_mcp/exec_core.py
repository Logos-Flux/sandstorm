"""Subprocess execution primitives + background PID tracking.

Replaces the HTTP bounce from the Cloudflare Worker → sandstorm-agent → `child_process.exec`.
Now the FastMCP process IS the executor: everything runs via `asyncio.subprocess`.
"""

from __future__ import annotations

import asyncio
import os
import signal
from dataclasses import dataclass
from pathlib import Path

MAX_BUFFER = 10 * 1024 * 1024  # 10MB — matches sandstorm-agent MAX_BUFFER
DEFAULT_TIMEOUT_SECONDS = 30
MAX_TIMEOUT_SECONDS = 300


@dataclass(frozen=True)
class ExecResult:
    stdout: str
    stderr: str
    exit_code: int


async def run_shell(
    command: str,
    cwd: str | os.PathLike[str],
    timeout: float | None = None,
    env: dict[str, str] | None = None,
) -> ExecResult:
    """Run `command` via /bin/bash -c with cwd, capture stdout+stderr, enforce timeout."""
    timeout_s = min(timeout or DEFAULT_TIMEOUT_SECONDS, MAX_TIMEOUT_SECONDS)
    Path(cwd).mkdir(parents=True, exist_ok=True)

    proc = await asyncio.create_subprocess_exec(
        "/bin/bash",
        "-c",
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(cwd),
        env={**os.environ, **(env or {})},
        start_new_session=True,
    )

    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
    except asyncio.TimeoutError:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        stdout_b = b""
        stderr_b = f"timeout after {timeout_s}s".encode()
        return ExecResult(
            stdout=stdout_b.decode("utf-8", errors="replace"),
            stderr=stderr_b.decode("utf-8", errors="replace"),
            exit_code=124,
        )

    stdout_s = stdout[:MAX_BUFFER].decode("utf-8", errors="replace")
    stderr_s = stderr[:MAX_BUFFER].decode("utf-8", errors="replace")
    return ExecResult(stdout=stdout_s, stderr=stderr_s, exit_code=proc.returncode or 0)


_background_procs: dict[int, asyncio.subprocess.Process] = {}
_background_meta: dict[int, dict] = {}


async def spawn_background(command: str, cwd: str | os.PathLike[str]) -> int:
    Path(cwd).mkdir(parents=True, exist_ok=True)
    proc = await asyncio.create_subprocess_exec(
        "/bin/bash",
        "-c",
        command,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
        stdin=asyncio.subprocess.DEVNULL,
        cwd=str(cwd),
        start_new_session=True,
    )
    pid = proc.pid
    _background_procs[pid] = proc
    _background_meta[pid] = {"command": command, "cwd": str(cwd)}

    async def _reap() -> None:
        await proc.wait()
        _background_procs.pop(pid, None)
        _background_meta.pop(pid, None)

    asyncio.create_task(_reap())
    return pid


def kill_background(pid: int) -> tuple[bool, str]:
    try:
        os.kill(pid, signal.SIGTERM)
        return True, f"Sent SIGTERM to {pid}"
    except ProcessLookupError:
        return False, f"No such process {pid}"
    except PermissionError as exc:
        return False, f"Permission denied killing {pid}: {exc}"
