"""Entrypoint: `python -m sandstorm_mcp.main`."""

from __future__ import annotations

import uvicorn

from .app import build_app
from .config import Config
from .logging_setup import configure_logging


def main() -> None:
    config = Config.from_env()
    configure_logging(config.log_level)
    app = build_app(config)
    uvicorn.run(
        app,
        host=config.host,
        port=config.port,
        log_level=config.log_level.lower(),
        log_config=None,  # leave our JSON logger alone
        access_log=False,
    )


if __name__ == "__main__":
    main()
