"""File operation tools — match worker `src/index.ts` file_* tools 1:1."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Annotated

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import Field

from ..config import Config
from ..security import PathEscapeError, sanitize_path


def register(mcp: FastMCP, config: Config) -> None:
    root = config.workspace_root

    def _safe(p: str) -> Path:
        try:
            return sanitize_path(p, root)
        except PathEscapeError as exc:
            raise ToolError(str(exc))

    @mcp.tool(
        name="file_read",
        description="Read file contents from the remote server",
    )
    async def file_read(
        path: Annotated[str, Field(description="Absolute or relative path to read")],
    ) -> str:
        target = _safe(path)
        try:
            return target.read_text(encoding="utf-8", errors="replace")
        except FileNotFoundError:
            raise ToolError(f"Error: {target}: No such file or directory")
        except IsADirectoryError:
            raise ToolError(f"Error: {target}: Is a directory")
        except PermissionError as exc:
            raise ToolError(f"Error: {exc}")

    @mcp.tool(
        name="file_write",
        description="Create or overwrite a file",
    )
    async def file_write(
        path: Annotated[str, Field(description="Absolute or relative path to write")],
        content: Annotated[str, Field(description="File content to write")],
    ) -> str:
        target = _safe(path)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            data = content.encode("utf-8")
            target.write_bytes(data)
        except PermissionError as exc:
            raise ToolError(f"Error: {exc}")
        return f"Written {len(content)} bytes to {target}"

    @mcp.tool(
        name="file_delete",
        description="Delete a file",
    )
    async def file_delete(
        path: Annotated[str, Field(description="Path to delete")],
    ) -> str:
        target = _safe(path)
        try:
            target.unlink(missing_ok=True)
        except IsADirectoryError:
            raise ToolError(f"Error: {target}: Is a directory")
        except PermissionError as exc:
            raise ToolError(f"Error: {exc}")
        return f"Deleted {target}"

    @mcp.tool(
        name="file_list",
        description="List directory contents",
    )
    async def file_list(
        path: Annotated[str, Field(description="Directory path to list")] = str(root),
        recursive: Annotated[bool, Field(description="List recursively")] = False,
    ) -> str:
        target = _safe(path)
        if not target.exists():
            raise ToolError(f"Error: {target}: No such file or directory")
        if not recursive:
            from .. import exec_core as _exec

            result = await _exec.run_shell(f"ls -la {_shq(target)}", cwd=root)
            if result.exit_code != 0:
                raise ToolError(f"Error: {result.stderr}")
            return result.stdout

        from .. import exec_core as _exec

        cmd = (
            f"find {_shq(target)} -maxdepth 5 "
            "-not -path '*/node_modules/*' -not -path '*/.git/*' | head -500"
        )
        result = await _exec.run_shell(cmd, cwd=root)
        if result.exit_code != 0:
            raise ToolError(f"Error: {result.stderr}")
        return result.stdout

    @mcp.tool(
        name="file_move",
        description="Move or rename a file",
    )
    async def file_move(
        source: Annotated[str, Field(description="Source path")],
        dest: Annotated[str, Field(description="Destination path")],
    ) -> str:
        src = _safe(source)
        dst = _safe(dest)
        if not src.exists():
            raise ToolError(f"Error: {src}: No such file or directory")
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
        except PermissionError as exc:
            raise ToolError(f"Error: {exc}")
        return f"Moved {src} → {dst}"

    @mcp.tool(
        name="file_mkdir",
        description="Create directory (recursive)",
    )
    async def file_mkdir(
        path: Annotated[str, Field(description="Directory path to create")],
    ) -> str:
        target = _safe(path)
        try:
            target.mkdir(parents=True, exist_ok=True)
        except PermissionError as exc:
            raise ToolError(f"Error: {exc}")
        return f"Created directory {target}"


def _shq(path: Path) -> str:
    """Single-quote shell-escape for paths we hand to /bin/bash."""
    s = str(path)
    return "'" + s.replace("'", "'\\''") + "'"
