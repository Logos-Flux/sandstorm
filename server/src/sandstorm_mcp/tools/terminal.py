"""Terminal tools — match worker `src/index.ts` terminal_* tools 1:1."""

from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import Field

from .. import exec_core
from ..config import Config
from ..security import PathEscapeError, sanitize_path


def register(mcp: FastMCP, config: Config) -> None:
    root = config.workspace_root

    def _resolve_cwd(cwd: str | None) -> str:
        if not cwd:
            return str(root)
        try:
            return str(sanitize_path(cwd, root))
        except PathEscapeError as exc:
            raise ToolError(str(exc))

    @mcp.tool(
        name="terminal_exec",
        description="Execute a shell command and return stdout/stderr/exit_code",
    )
    async def terminal_exec(
        command: Annotated[str, Field(description="Shell command to execute")],
        cwd: Annotated[str | None, Field(description="Working directory")] = None,
        timeout: Annotated[
            float | None,
            Field(description="Timeout in seconds (default 30, max 300)"),
        ] = None,
    ) -> str:
        resolved_cwd = _resolve_cwd(cwd)
        result = await exec_core.run_shell(command, cwd=resolved_cwd, timeout=timeout)
        parts: list[str] = []
        if result.stdout:
            parts.append(f"stdout:\n{result.stdout}")
        if result.stderr:
            parts.append(f"stderr:\n{result.stderr}")
        parts.append(f"exit_code: {result.exit_code}")
        output = "\n\n".join(parts)
        if result.exit_code != 0:
            raise ToolError(output)
        return output

    @mcp.tool(
        name="terminal_exec_background",
        description="Start a background process, return PID",
    )
    async def terminal_exec_background(
        command: Annotated[
            str, Field(description="Shell command to run in background")
        ],
        cwd: Annotated[str | None, Field(description="Working directory")] = None,
    ) -> str:
        resolved_cwd = _resolve_cwd(cwd)
        pid = await exec_core.spawn_background(command, cwd=resolved_cwd)
        return f"PID: {pid}\nStarted background process {pid}"

    @mcp.tool(
        name="terminal_kill",
        description="Kill a background process by PID",
    )
    async def terminal_kill(
        pid: Annotated[int, Field(description="Process ID to kill")],
    ) -> str:
        success, message = exec_core.kill_background(pid)
        if not success:
            raise ToolError(message)
        return message
