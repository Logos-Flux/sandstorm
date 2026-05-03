"""Environment-based configuration for the Sandstorm MCP server."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    auth_token: str
    session_auth_token: str | None
    host: str
    port: int
    workspace_root: Path
    sessions_base: Path
    max_instances: int
    db_path: Path
    log_level: str

    @classmethod
    def from_env(cls) -> "Config":
        token = os.environ.get("SANDSTORM_MCP_TOKEN") or os.environ.get(
            "MCP_AUTH_TOKEN"
        )
        if not token:
            raise RuntimeError(
                "SANDSTORM_MCP_TOKEN (or MCP_AUTH_TOKEN) must be set in the environment."
            )

        workspace_root = Path(
            os.environ.get("SANDSTORM_WORKSPACE_ROOT", "/home/dev")
        ).resolve()
        sessions_base = workspace_root / "sessions"
        db_dir = Path(
            os.environ.get(
                "SANDSTORM_STATE_DIR", str(workspace_root / ".sandstorm-mcp")
            )
        )
        db_path = db_dir / "sessions.db"

        return cls(
            auth_token=token,
            session_auth_token=os.environ.get("SESSION_AUTH_TOKEN") or None,
            host=os.environ.get("SANDSTORM_MCP_HOST", "127.0.0.1"),
            port=int(os.environ.get("SANDSTORM_MCP_PORT", "8080")),
            workspace_root=workspace_root,
            sessions_base=sessions_base,
            max_instances=int(os.environ.get("MAX_INSTANCES", "5")),
            db_path=db_path,
            log_level=os.environ.get("SANDSTORM_LOG_LEVEL", "INFO"),
        )
