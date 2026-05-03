"""Path sanitizer + rate limiter tests."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from sandstorm_mcp.security import PathEscapeError, RateLimiter, sanitize_path


def test_empty_path_returns_root(tmp_path: Path) -> None:
    assert sanitize_path("", tmp_path) == tmp_path.resolve()


def test_relative_path_resolves_under_root(tmp_path: Path) -> None:
    assert (
        sanitize_path("sub/file.txt", tmp_path)
        == (tmp_path / "sub" / "file.txt").resolve()
    )


def test_absolute_path_under_root_is_allowed(tmp_path: Path) -> None:
    assert sanitize_path(str(tmp_path / "a"), tmp_path) == (tmp_path / "a").resolve()


def test_escape_via_dotdot_is_blocked(tmp_path: Path) -> None:
    with pytest.raises(PathEscapeError):
        sanitize_path("../../etc/passwd", tmp_path)


def test_escape_via_absolute_is_blocked(tmp_path: Path) -> None:
    with pytest.raises(PathEscapeError):
        sanitize_path("/etc/passwd", tmp_path)


def test_rate_limiter_allows_up_to_limit() -> None:
    limiter = RateLimiter(limit=3, window_seconds=60)
    assert limiter.allow("tok") is True
    assert limiter.allow("tok") is True
    assert limiter.allow("tok") is True
    assert limiter.allow("tok") is False


def test_rate_limiter_is_per_token() -> None:
    limiter = RateLimiter(limit=1, window_seconds=60)
    assert limiter.allow("a") is True
    assert limiter.allow("b") is True
    assert limiter.allow("a") is False
    assert limiter.allow("b") is False


def test_rate_limiter_window_resets() -> None:
    limiter = RateLimiter(limit=1, window_seconds=0.05)
    assert limiter.allow("tok") is True
    assert limiter.allow("tok") is False
    time.sleep(0.1)
    assert limiter.allow("tok") is True
