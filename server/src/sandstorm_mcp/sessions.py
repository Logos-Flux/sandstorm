"""Session API — SQLite-backed port of `apps/mcp/src/routes/sessions.ts`.

Replaces the D1 database with a local SQLite file. Schema matches the D1 migration
(`migrations/0001_sessions.sql`) so migration is a straight table copy if needed.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import aiosqlite

from .config import Config
from .exec_core import run_shell

logger = logging.getLogger(__name__)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY,
  type TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'creating',
  workspace_path TEXT NOT NULL,
  repo TEXT,
  branch TEXT,
  ttl_minutes INTEGER NOT NULL DEFAULT 30,
  expires_at TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_status_expires ON sessions(status, expires_at);
"""


def _now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


class SessionStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    async def init(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.db_path) as db:
            await db.executescript(SCHEMA_SQL)
            await db.commit()

    async def insert(self, row: dict[str, Any]) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """INSERT INTO sessions
                (id, type, status, workspace_path, repo, branch, ttl_minutes,
                 expires_at, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    row["id"],
                    row["type"],
                    row["status"],
                    row["workspace_path"],
                    row.get("repo"),
                    row.get("branch"),
                    row["ttl_minutes"],
                    row["expires_at"],
                    row["created_at"],
                    row["updated_at"],
                ),
            )
            await db.commit()

    async def get(self, session_id: str) -> dict[str, Any] | None:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT * FROM sessions WHERE id = ?", (session_id,))
            row = await cur.fetchone()
            return dict(row) if row else None

    async def get_active(self, session_id: str) -> dict[str, Any] | None:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM sessions WHERE id = ? AND status IN ('ready', 'active')",
                (session_id,),
            )
            row = await cur.fetchone()
            return dict(row) if row else None

    async def update_status(self, session_id: str, status: str) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE sessions SET status = ?, updated_at = ? WHERE id = ?",
                (status, _now_iso(), session_id),
            )
            await db.commit()

    async def set_expires(self, session_id: str, expires_at: str) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE sessions SET expires_at = ?, updated_at = ? WHERE id = ?",
                (expires_at, _now_iso(), session_id),
            )
            await db.commit()

    async def count_active(self) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            cur = await db.execute(
                "SELECT COUNT(*) FROM sessions WHERE status IN ('ready', 'active', 'creating')"
            )
            row = await cur.fetchone()
            return int(row[0]) if row else 0

    async def list_expired(self) -> list[dict[str, Any]]:
        now = _now_iso()
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                """SELECT id, workspace_path, status FROM sessions
                WHERE status IN ('ready', 'active', 'expired', 'creating')
                  AND expires_at < ?""",
                (now,),
            )
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

    async def delete_cleaned_older_than(self, hours: int = 24) -> None:
        cutoff = (
            (datetime.now(timezone.utc) - timedelta(hours=hours))
            .isoformat()
            .replace("+00:00", "Z")
        )
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "DELETE FROM sessions WHERE status = 'cleaned' AND updated_at < ?",
                (cutoff,),
            )
            await db.commit()


def _session_response(session: dict[str, Any]) -> dict[str, Any]:
    expires = datetime.fromisoformat(session["expires_at"].replace("Z", "+00:00"))
    remaining = max(
        0, round((expires - datetime.now(timezone.utc)).total_seconds() / 60)
    )
    return {
        "id": session["id"],
        "status": session["status"],
        "type": session["type"],
        "workspace_path": session["workspace_path"],
        "ttl_remaining_minutes": remaining,
        "created_at": session["created_at"],
    }


class SessionService:
    """Business logic for session routes, usable from Starlette handlers."""

    def __init__(self, config: Config, store: SessionStore) -> None:
        self.config = config
        self.store = store

    async def create(self, body: dict[str, Any]) -> dict[str, Any]:
        session_type = body.get("type")
        if not session_type or not isinstance(session_type, str):
            raise ValueError("type: field required")

        ttl_minutes = int(body.get("ttl_minutes", 30))
        if ttl_minutes < 1 or ttl_minutes > 120:
            raise ValueError("ttl_minutes: must be between 1 and 120")

        ctx = body.get("context") or {}
        requirements = body.get("requirements") or {}

        sid = str(uuid.uuid4())
        now = _now_iso()
        expires_at = (
            (datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes))
            .isoformat()
            .replace("+00:00", "Z")
        )
        workspace_path = f"{self.config.sessions_base}/{sid}"

        mkdir_result = await run_shell(
            f"mkdir -p {workspace_path!r}/context {workspace_path!r}/workspace {workspace_path!r}/outputs",
            cwd=str(self.config.workspace_root),
        )
        if mkdir_result.exit_code != 0:
            raise RuntimeError(
                f"Failed to create session directory: {mkdir_result.stderr}"
            )

        if ctx:
            ctx_json = json.dumps(ctx, indent=2)
            Path(f"{workspace_path}/context/task.json").write_text(
                ctx_json, encoding="utf-8"
            )

        env_vars = ctx.get("env") if isinstance(ctx, dict) else None
        if isinstance(env_vars, dict) and env_vars:
            env_json = json.dumps(env_vars, indent=2)
            Path(f"{workspace_path}/context/env.json").write_text(
                env_json, encoding="utf-8"
            )

        repo = requirements.get("repo")
        branch = requirements.get("branch") or "main"
        if repo:
            clone_cmd = (
                f"cd {workspace_path!r}/workspace && "
                f"git clone --depth 1 --branch {branch!r} https://github.com/{repo!r}.git ."
            )
            clone_result = await run_shell(
                clone_cmd, cwd=str(self.config.workspace_root), timeout=120
            )
            if clone_result.exit_code != 0:
                logger.warning(
                    "Session %s git clone failed: %s", sid, clone_result.stderr
                )

        await self.store.insert(
            {
                "id": sid,
                "type": session_type,
                "status": "ready",
                "workspace_path": workspace_path,
                "repo": repo,
                "branch": branch if repo else None,
                "ttl_minutes": ttl_minutes,
                "expires_at": expires_at,
                "created_at": now,
                "updated_at": now,
            }
        )
        logger.info(
            "Session %s created (type=%s ttl=%dm)", sid, session_type, ttl_minutes
        )
        return {"id": sid, "status": "ready", "workspace_path": workspace_path}

    async def exec(
        self, session_id: str, body: dict[str, Any]
    ) -> dict[str, Any] | None:
        session = await self.store.get_active(session_id)
        if not session:
            return None

        expires = datetime.fromisoformat(session["expires_at"].replace("Z", "+00:00"))
        if expires < datetime.now(timezone.utc):
            await self.store.update_status(session_id, "expired")
            return {"__expired__": True}

        command = body.get("command")
        if not command or not isinstance(command, str):
            raise ValueError("command: field required")

        timeout_ms = int(body.get("timeout_ms", 30000))
        timeout_s = max(1, timeout_ms // 1000)
        cwd = body.get("cwd") or f"{session['workspace_path']}/workspace"

        await self.store.update_status(session_id, "active")
        try:
            result = await run_shell(command, cwd=cwd, timeout=timeout_s)
        finally:
            await self.store.update_status(session_id, "ready")

        return {
            "exit_code": result.exit_code,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }

    async def status(self, session_id: str) -> dict[str, Any] | None:
        session = await self.store.get(session_id)
        if not session:
            return None
        return _session_response(session)

    async def extend(
        self, session_id: str, additional_minutes: int = 15
    ) -> dict[str, Any] | None:
        session = await self.store.get_active(session_id)
        if not session:
            return None

        created = datetime.fromisoformat(session["created_at"].replace("Z", "+00:00"))
        current_expiry = datetime.fromisoformat(
            session["expires_at"].replace("Z", "+00:00")
        )
        max_expiry = created + timedelta(minutes=120)
        new_expiry = current_expiry + timedelta(minutes=additional_minutes)
        final_expiry = min(new_expiry, max_expiry)

        expires_iso = final_expiry.isoformat().replace("+00:00", "Z")
        await self.store.set_expires(session_id, expires_iso)

        return {
            "id": session_id,
            "status": session["status"],
            "expires_at": expires_iso,
            "ttl_remaining_minutes": max(
                0,
                round((final_expiry - datetime.now(timezone.utc)).total_seconds() / 60),
            ),
        }

    async def delete(self, session_id: str) -> bool:
        session = await self.store.get(session_id)
        if not session:
            return False

        workspace = session["workspace_path"]
        if workspace.startswith(str(self.config.sessions_base)):
            try:
                shutil.rmtree(workspace, ignore_errors=True)
            except Exception as exc:
                logger.warning("Failed to clean %s: %s", workspace, exc)

        await self.store.update_status(session_id, "cleaned")
        logger.info("Session %s cleaned", session_id)
        return True


async def reap_expired_loop(
    service: SessionService, interval_seconds: int = 300
) -> None:
    """Background task replacing the CF cron trigger (`*/5 * * * *`)."""
    while True:
        try:
            await _reap_once(service)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Session reaper iteration failed")
        try:
            await asyncio.sleep(interval_seconds)
        except asyncio.CancelledError:
            raise


async def _reap_once(service: SessionService) -> None:
    expired = await service.store.list_expired()
    reaped = 0
    errors = 0
    for session in expired:
        try:
            workspace = session["workspace_path"]
            if workspace.startswith(str(service.config.sessions_base)):
                shutil.rmtree(workspace, ignore_errors=True)
            await service.store.update_status(session["id"], "cleaned")
            reaped += 1
        except Exception as exc:
            logger.warning("Failed to reap session %s: %s", session["id"], exc)
            await service.store.update_status(session["id"], "expired")
            errors += 1
    await service.store.delete_cleaned_older_than(hours=24)
    if reaped > 0:
        logger.info("Session reaper: cleaned %d sessions (%d errors)", reaped, errors)
