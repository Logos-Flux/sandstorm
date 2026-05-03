"""Path sanitization and in-memory rate limiting (ports `apps/mcp/src/security.ts`)."""

from __future__ import annotations

import time
from pathlib import Path, PurePosixPath
from threading import Lock


class PathEscapeError(ValueError):
    """Raised when an input path would resolve outside the allowed workspace root."""


def sanitize_path(input_path: str, allowed_root: Path) -> Path:
    root = Path(allowed_root).resolve()
    if not input_path:
        return root

    if input_path.startswith("/"):
        candidate = PurePosixPath(input_path)
    else:
        candidate = PurePosixPath(str(root)) / input_path

    parts: list[str] = []
    for part in candidate.parts:
        if part in ("", "."):
            continue
        if part == "..":
            if parts and parts[-1] != "/":
                parts.pop()
            continue
        parts.append(part)

    normalized = Path("/" + "/".join(p for p in parts if p != "/"))

    root_str = str(root)
    if not (str(normalized) == root_str or str(normalized).startswith(root_str + "/")):
        raise PathEscapeError(
            f'Path "{input_path}" is outside the allowed directory ({root_str})'
        )
    return normalized


class RateLimiter:
    """100 requests per 60-second sliding window per bearer token, like the worker."""

    def __init__(self, limit: int = 100, window_seconds: float = 60.0) -> None:
        self.limit = limit
        self.window = window_seconds
        self._counts: dict[str, tuple[int, float]] = {}
        self._lock = Lock()

    def allow(self, token: str) -> bool:
        now = time.monotonic()
        with self._lock:
            entry = self._counts.get(token)
            if entry is None or now >= entry[1]:
                self._counts[token] = (1, now + self.window)
                return True
            count, reset_at = entry
            count += 1
            self._counts[token] = (count, reset_at)
            return count <= self.limit
