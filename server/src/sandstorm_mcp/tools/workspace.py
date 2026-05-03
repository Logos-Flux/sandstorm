"""Workspace tools — match worker `src/index.ts` workspace_* tools 1:1."""

from __future__ import annotations

from typing import Annotated, Literal

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import Field

from .. import exec_core
from ..config import Config


def register(mcp: FastMCP, config: Config) -> None:
    root = config.workspace_root

    @mcp.tool(
        name="workspace_info",
        description="Return OS info, node version, disk space, installed tools, and current working directory",
    )
    async def workspace_info() -> str:
        cmds = [
            "echo '=== OS ===' && cat /etc/os-release 2>/dev/null | head -5",
            "echo '=== Node ===' && node --version 2>/dev/null || echo 'node not installed'",
            "echo '=== Git ===' && git --version",
            f"echo '=== Disk ===' && df -h {root}",
            "echo '=== CWD ===' && pwd",
            "echo '=== Tools ===' && which bun npm yarn pip3 python3 curl wget 2>/dev/null || true",
            "echo '=== Memory ===' && free -h 2>/dev/null | head -3 || true",
        ]
        result = await exec_core.run_shell(" && ".join(cmds), cwd=str(root))
        return result.stdout

    @mcp.tool(
        name="workspace_install",
        description="Install packages via npm/bun/pip/dnf",
    )
    async def workspace_install(
        packages: Annotated[str, Field(description="Space-separated package names")],
        manager: Annotated[
            Literal["npm", "bun", "pip", "pip3", "dnf", "apt", "auto"] | None,
            Field(description="Package manager to use (default: auto-detect)"),
        ] = None,
    ) -> str:
        mgr = manager or "auto"
        if mgr == "auto":
            cmd = (
                f"if command -v bun &>/dev/null; then bun add {packages}; "
                f"elif command -v npm &>/dev/null; then npm install {packages}; "
                f'else echo "No package manager found"; exit 1; fi'
            )
        elif mgr == "npm":
            cmd = f"npm install {packages}"
        elif mgr == "bun":
            cmd = f"bun add {packages}"
        elif mgr in ("pip", "pip3"):
            cmd = f"{mgr} install {packages}"
        elif mgr == "dnf":
            cmd = f"sudo dnf install -y {packages}"
        elif mgr == "apt":
            cmd = f"sudo apt-get install -y {packages}"
        else:
            raise ToolError(f"Unknown package manager: {mgr}")

        result = await exec_core.run_shell(cmd, cwd=str(root), timeout=120)
        output = (result.stdout + "\n" + result.stderr).strip()
        if result.exit_code != 0:
            raise ToolError(output)
        return output
