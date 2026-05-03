# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

While the project is in `0.x`, minor version bumps may include breaking changes.

## [Unreleased]

## [0.1.0] - 2026-05-03

### Added

- Initial public release.
- FastMCP self-hosted server in `server/` exposing 20 MCP tools (file: 6, terminal: 3, git: 9, workspace: 2) over MCP streamable-HTTP at `/mcp`.
- OAuth 2.0 + bearer-token authentication (HMAC-signed, stateless).
- SQLite-backed session API (`/session/*`) with TTL reaper.
- Caddy + systemd deployment via `deploy/install.sh` (idempotent, expects `SANDSTORM_DOMAIN` + `SANDSTORM_MCP_TOKEN`).
- JSON-structured logs to stdout, captured by journald.
- Rate limiting (100 req/min per bearer token).

[0.1.0]: https://github.com/Logos-Flux/sandstorm/releases/tag/v0.1.0
