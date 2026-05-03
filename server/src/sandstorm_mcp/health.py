"""Health endpoint — ports `apps/mcp/src/lib/health.ts`."""

from __future__ import annotations

import logging

from .config import Config
from .exec_core import run_shell
from .sessions import SessionStore

logger = logging.getLogger(__name__)


async def node_health(config: Config, store: SessionStore) -> dict:
    try:
        cmds = [
            'echo "CORES:$(nproc)"',
            "echo \"MEM:$(free -m | awk '/Mem:/{print $7}')\"",
            f"echo \"DISK:$(df -m {config.workspace_root} | awk 'NR==2{{print $4}}')\"",
            "echo \"UPTIME:$(awk '{print int($1)}' /proc/uptime)\"",
            "echo \"TOOLS:$(which node bun python3 git gh curl 2>/dev/null | xargs -I{} basename {} | tr '\\n' ',')\"",
        ]
        result = await run_shell(" && ".join(cmds), cwd=str(config.workspace_root))
        fields = {}
        for line in result.stdout.splitlines():
            if ":" in line:
                key, _, value = line.partition(":")
                fields[key] = value

        active = await store.count_active()
        cores_total = int(fields.get("CORES", "4") or 4)

        return {
            "ok": True,
            "cores_available": max(0, cores_total - active),
            "memory_mb_available": int(fields.get("MEM") or 0),
            "disk_mb_available": int(fields.get("DISK") or 0),
            "active_instances": active,
            "max_instances": config.max_instances,
            "tools": [t for t in (fields.get("TOOLS") or "").split(",") if t],
            "uptime_seconds": int(fields.get("UPTIME") or 0),
        }
    except Exception:
        logger.exception("Health check failed")
        return {
            "ok": False,
            "cores_available": 0,
            "memory_mb_available": 0,
            "disk_mb_available": 0,
            "active_instances": 0,
            "max_instances": config.max_instances,
            "tools": [],
            "uptime_seconds": 0,
        }
