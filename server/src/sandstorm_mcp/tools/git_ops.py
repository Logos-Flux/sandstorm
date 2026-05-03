"""Git tools — match worker `src/index.ts` git_* tools 1:1."""

from __future__ import annotations

from typing import Annotated

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import Field

from .. import exec_core
from ..config import Config
from ..security import PathEscapeError, sanitize_path


def _shq(s: str) -> str:
    return "'" + s.replace("'", "'\\''") + "'"


def register(mcp: FastMCP, config: Config) -> None:
    root = config.workspace_root

    def _resolve_path(path: str | None) -> str:
        if not path:
            return str(root)
        try:
            return str(sanitize_path(path, root))
        except PathEscapeError as exc:
            raise ToolError(str(exc))

    @mcp.tool(
        name="git_clone",
        description="Clone a git repository",
    )
    async def git_clone(
        repo_url: Annotated[str, Field(description="Repository URL to clone")],
        path: Annotated[str | None, Field(description="Target directory")] = None,
        branch: Annotated[str | None, Field(description="Branch to clone")] = None,
    ) -> str:
        target = _resolve_path(path) if path else ""
        cmd = "git clone"
        if branch:
            cmd += f" -b {_shq(branch)}"
        cmd += f" {_shq(repo_url)}"
        if target:
            cmd += f" {_shq(target)}"
        result = await exec_core.run_shell(cmd, cwd=str(root), timeout=120)
        output = (result.stdout + "\n" + result.stderr).strip()
        if result.exit_code != 0:
            raise ToolError(output)
        return output

    @mcp.tool(
        name="git_status",
        description="Get repository status",
    )
    async def git_status(
        path: Annotated[str | None, Field(description="Repository path")] = None,
    ) -> str:
        cwd = _resolve_path(path)
        result = await exec_core.run_shell("git status", cwd=cwd)
        return result.stdout or result.stderr

    @mcp.tool(
        name="git_commit",
        description="Stage all changes and commit",
    )
    async def git_commit(
        message: Annotated[str, Field(description="Commit message")],
        path: Annotated[str | None, Field(description="Repository path")] = None,
    ) -> str:
        cwd = _resolve_path(path)
        cmd = f"git add -A && git commit -m {_shq(message)}"
        result = await exec_core.run_shell(cmd, cwd=cwd)
        output = (result.stdout + "\n" + result.stderr).strip()
        if result.exit_code != 0:
            raise ToolError(output)
        return output

    @mcp.tool(
        name="git_push",
        description="Push to remote",
    )
    async def git_push(
        remote: Annotated[
            str | None, Field(description="Remote name (default: origin)")
        ] = None,
        branch: Annotated[str | None, Field(description="Branch name")] = None,
        path: Annotated[str | None, Field(description="Repository path")] = None,
    ) -> str:
        cwd = _resolve_path(path)
        r = remote or "origin"
        cmd = f"git push {_shq(r)}"
        if branch:
            cmd += f" {_shq(branch)}"
        result = await exec_core.run_shell(cmd, cwd=cwd, timeout=60)
        output = (result.stdout + "\n" + result.stderr).strip()
        if result.exit_code != 0:
            raise ToolError(output)
        return output

    @mcp.tool(
        name="git_pull",
        description="Pull from remote",
    )
    async def git_pull(
        remote: Annotated[
            str | None, Field(description="Remote name (default: origin)")
        ] = None,
        branch: Annotated[str | None, Field(description="Branch name")] = None,
        path: Annotated[str | None, Field(description="Repository path")] = None,
    ) -> str:
        cwd = _resolve_path(path)
        r = remote or "origin"
        cmd = f"git pull {_shq(r)}"
        if branch:
            cmd += f" {_shq(branch)}"
        result = await exec_core.run_shell(cmd, cwd=cwd, timeout=60)
        output = (result.stdout + "\n" + result.stderr).strip()
        if result.exit_code != 0:
            raise ToolError(output)
        return output

    @mcp.tool(
        name="git_branch",
        description="List or create branches",
    )
    async def git_branch(
        name: Annotated[
            str | None, Field(description="Branch name to create (omit to list)")
        ] = None,
        path: Annotated[str | None, Field(description="Repository path")] = None,
    ) -> str:
        cwd = _resolve_path(path)
        cmd = f"git branch {_shq(name)}" if name else "git branch -a"
        result = await exec_core.run_shell(cmd, cwd=cwd)
        output = (result.stdout + "\n" + result.stderr).strip()
        if result.exit_code != 0:
            raise ToolError(output)
        return output

    @mcp.tool(
        name="git_checkout",
        description="Switch branches",
    )
    async def git_checkout(
        branch: Annotated[str, Field(description="Branch name to checkout")],
        path: Annotated[str | None, Field(description="Repository path")] = None,
    ) -> str:
        cwd = _resolve_path(path)
        cmd = f"git checkout {_shq(branch)}"
        result = await exec_core.run_shell(cmd, cwd=cwd)
        output = (result.stdout + "\n" + result.stderr).strip()
        if result.exit_code != 0:
            raise ToolError(output)
        return output

    @mcp.tool(
        name="git_diff",
        description="Show current diff",
    )
    async def git_diff(
        path: Annotated[str | None, Field(description="Repository path")] = None,
    ) -> str:
        cwd = _resolve_path(path)
        result = await exec_core.run_shell("git diff", cwd=cwd)
        return result.stdout or "(no changes)"

    @mcp.tool(
        name="git_log",
        description="Show recent commit history",
    )
    async def git_log(
        n: Annotated[
            int | None, Field(description="Number of commits (default 10)")
        ] = None,
        path: Annotated[str | None, Field(description="Repository path")] = None,
    ) -> str:
        cwd = _resolve_path(path)
        count = min(n or 10, 100)
        cmd = f"git log --oneline -{count}"
        result = await exec_core.run_shell(cmd, cwd=cwd)
        return result.stdout or result.stderr
