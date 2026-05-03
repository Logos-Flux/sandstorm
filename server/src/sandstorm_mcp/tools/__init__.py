"""Tool registration. Each module exposes a `register(mcp, config)` function.

Keeping registration grouped here (rather than magical auto-discovery) makes the
tool surface grep-able and the order deterministic.
"""

from __future__ import annotations

from fastmcp import FastMCP

from ..config import Config
from . import file_ops, git_ops, terminal, workspace


def register_all(mcp: FastMCP, config: Config) -> None:
    file_ops.register(mcp, config)
    terminal.register(mcp, config)
    git_ops.register(mcp, config)
    workspace.register(mcp, config)
