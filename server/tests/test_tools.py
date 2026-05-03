"""Smoke tests: in-process MCP client driving every tool in the server."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastmcp import Client, FastMCP

from sandstorm_mcp.config import Config
from sandstorm_mcp.tools import register_all


@pytest.fixture
def config(tmp_path: Path) -> Config:
    os.environ["SANDSTORM_MCP_TOKEN"] = "test"
    os.environ["SANDSTORM_WORKSPACE_ROOT"] = str(tmp_path)
    os.environ["SANDSTORM_STATE_DIR"] = str(tmp_path / ".state")
    return Config.from_env()


@pytest.fixture
def mcp(config: Config) -> FastMCP:
    server = FastMCP(name="sandstorm-test", version="0.0.0")
    register_all(server, config)
    return server


@pytest.mark.asyncio
async def test_every_worker_tool_is_registered(mcp: FastMCP) -> None:
    expected = {
        "file_read",
        "file_write",
        "file_delete",
        "file_list",
        "file_move",
        "file_mkdir",
        "terminal_exec",
        "terminal_exec_background",
        "terminal_kill",
        "git_clone",
        "git_status",
        "git_commit",
        "git_push",
        "git_pull",
        "git_branch",
        "git_checkout",
        "git_diff",
        "git_log",
        "workspace_info",
        "workspace_install",
    }
    async with Client(mcp) as client:
        tools = await client.list_tools()
    assert {t.name for t in tools} == expected


@pytest.mark.asyncio
async def test_file_write_read_roundtrip(mcp: FastMCP) -> None:
    async with Client(mcp) as client:
        write_result = await client.call_tool(
            "file_write", {"path": "hello.txt", "content": "hi there\n"}
        )
        assert "Written 9 bytes" in write_result.content[0].text

        read_result = await client.call_tool("file_read", {"path": "hello.txt"})
        assert read_result.content[0].text == "hi there\n"


@pytest.mark.asyncio
async def test_file_read_outside_workspace_is_blocked(mcp: FastMCP) -> None:
    async with Client(mcp) as client:
        result = await client.call_tool(
            "file_read", {"path": "/etc/passwd"}, raise_on_error=False
        )
        assert result.is_error
        assert "outside the allowed directory" in result.content[0].text


@pytest.mark.asyncio
async def test_terminal_exec_success_and_failure(mcp: FastMCP) -> None:
    async with Client(mcp) as client:
        ok = await client.call_tool("terminal_exec", {"command": "echo hello"})
        assert not ok.is_error
        assert "exit_code: 0" in ok.content[0].text
        assert "hello" in ok.content[0].text

        fail = await client.call_tool(
            "terminal_exec", {"command": "ls /no/such/path"}, raise_on_error=False
        )
        assert fail.is_error
        assert "exit_code: 2" in fail.content[0].text


@pytest.mark.asyncio
async def test_file_list_default_dir_is_workspace_root(
    mcp: FastMCP, config: Config
) -> None:
    async with Client(mcp) as client:
        (config.workspace_root / "marker.txt").write_text("x")
        result = await client.call_tool("file_list", {})
        assert "marker.txt" in result.content[0].text


@pytest.mark.asyncio
async def test_file_mkdir_and_move(mcp: FastMCP, config: Config) -> None:
    async with Client(mcp) as client:
        await client.call_tool("file_mkdir", {"path": "sub"})
        assert (config.workspace_root / "sub").is_dir()

        await client.call_tool("file_write", {"path": "sub/a.txt", "content": "a"})
        await client.call_tool(
            "file_move", {"source": "sub/a.txt", "dest": "sub/b.txt"}
        )
        assert not (config.workspace_root / "sub" / "a.txt").exists()
        assert (config.workspace_root / "sub" / "b.txt").read_text() == "a"


@pytest.mark.asyncio
async def test_terminal_background_lifecycle(mcp: FastMCP) -> None:
    async with Client(mcp) as client:
        spawn = await client.call_tool(
            "terminal_exec_background", {"command": "sleep 60"}
        )
        text = spawn.content[0].text
        assert "PID:" in text
        pid = int(text.split("PID: ")[1].split("\n")[0])

        killed = await client.call_tool("terminal_kill", {"pid": pid})
        assert not killed.is_error
        assert f"{pid}" in killed.content[0].text


@pytest.mark.asyncio
async def test_workspace_info_returns_sections(mcp: FastMCP) -> None:
    async with Client(mcp) as client:
        result = await client.call_tool("workspace_info", {})
        text = result.content[0].text
        assert "=== OS ===" in text
        assert "=== Git ===" in text
        assert "=== CWD ===" in text


@pytest.mark.asyncio
async def test_git_status_on_empty_dir(mcp: FastMCP) -> None:
    async with Client(mcp) as client:
        result = await client.call_tool("git_status", {})
        assert "not a git repository" in result.content[0].text.lower()
