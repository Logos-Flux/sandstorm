# Sandstorm

*Self-hosted MCP server giving AI agents file, terminal, and git access on a remote Linux host.*

[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python: 3.12+](https://img.shields.io/badge/Python-3.12%2B-blue.svg)](https://www.python.org/)
[![Status: alpha](https://img.shields.io/badge/Status-alpha-orange.svg)](#status)

## Why

AI agents (Claude.ai connectors, Claude Code, custom orchestrators) increasingly
need a real shell, a real filesystem, and real git on a real machine — not a
sandboxed REPL or a vendor-managed runtime. Sandstorm exposes that surface as a
single MCP streamable-HTTP endpoint behind your own Caddy/TLS, on a host you
control. No managed plane, no vendor lock-in — just a systemd service on a Linux
box you own.

## Status

Alpha. v0.1.0 — initial public release. The 20-tool surface and wire format are
stable (carried forward from a prior Cloudflare Worker implementation that this
server replaces). The deployment shape and configuration may shift before 1.0.

## Architecture

```
claude.ai / Claude Code / any MCP client
        │  (MCP streamable-HTTP)
        ▼
  https://<your-domain>
        │  (Caddy TLS, Let's Encrypt)
        ▼
  http://127.0.0.1:8080   ← FastMCP process
        │  (asyncio.subprocess)
        ▼
  /bin/bash, git, pathlib, … on the host
```

## Quick start

Prerequisites: Debian/Ubuntu host with sudo, and a public DNS A/AAAA record
pointing at it.

```bash
# 1. Clone the repo
sudo mkdir -p /home/dev && sudo chown "$USER:$USER" /home/dev
git clone https://github.com/Logos-Flux/sandstorm.git /home/dev/sandstorm
cd /home/dev/sandstorm

# 2. Generate a bearer token
SANDSTORM_MCP_TOKEN=$(openssl rand -hex 32)

# 3. Run the installer (installs Caddy + uv, syncs deps, writes systemd unit)
SANDSTORM_DOMAIN=mcp.example.com \
SANDSTORM_MCP_TOKEN=$SANDSTORM_MCP_TOKEN \
bash deploy/install.sh
```

Caddy provisions TLS via Let's Encrypt automatically. The installer prints the
public URL and runs a local smoke test against `/health` and `/mcp`.

## Configuration

All variables live in `/etc/sandstorm-mcp.env` (`0600 root:root`), loaded by
systemd via `EnvironmentFile`.

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `SANDSTORM_MCP_TOKEN` | yes | — | Bearer token. Clients send `Authorization: Bearer <token>`. Also the HMAC key for OAuth-issued access tokens. |
| `SANDSTORM_DOMAIN` | yes (installer) | — | Public hostname Caddy serves with Let's Encrypt. |
| `SANDSTORM_MCP_HOST` | no | `127.0.0.1` | Bind address. |
| `SANDSTORM_MCP_PORT` | no | `8080` | Bind port. |
| `SANDSTORM_WORKSPACE_ROOT` | no | `/home/dev` | Sanitizer root for file/git tools. |
| `SANDSTORM_STATE_DIR` | no | `/home/dev/.sandstorm-mcp` | SQLite session DB location. |
| `MAX_INSTANCES` | no | `5` | Reported via `/health`. |
| `SESSION_AUTH_TOKEN` | no | — | If set, `/session/*` requires this bearer. |

## Tool surface

20 tools across four categories. Schemas mirror the prior Cloudflare Worker
exactly; full parameter detail in [`server/README.md`](server/README.md).

- **File (6):** `file_read`, `file_write`, `file_delete`, `file_list`, `file_move`, `file_mkdir`
- **Terminal (3):** `terminal_exec`, `terminal_exec_background`, `terminal_kill`
- **Git (9):** `git_clone`, `git_status`, `git_commit`, `git_push`, `git_pull`, `git_branch`, `git_checkout`, `git_diff`, `git_log`
- **Workspace (2):** `workspace_info`, `workspace_install`

## Auth model

Two auth shapes coexist on `/mcp`:

**Bearer token (CLI / `mcp-remote`).** Send `Authorization: Bearer
$SANDSTORM_MCP_TOKEN`. The token is root-equivalent on the workspace — anyone
holding it can run arbitrary shell commands as the `dev` user. Treat it like an
SSH private key: store in a password manager, rotate on compromise, never commit.

**OAuth 2.0 (Claude.ai custom connectors).** Stateless authorization-code flow
with PKCE (S256). Codes and access tokens are HMAC-SHA256 signed using
`SANDSTORM_MCP_TOKEN` as the key — no DB-backed session storage. Access-token
TTL is 30 days. To wire up: add `https://<your-domain>/mcp` as a custom
connector in claude.ai; it auto-discovers the OAuth endpoints via RFC 9728 /
RFC 8414 metadata. The "password" on the authorize page is your bearer token.

Rotating `SANDSTORM_MCP_TOKEN` invalidates every outstanding OAuth access token.
Raw-bearer clients just need the new value.

## Development

See [`server/README.md`](server/README.md) for tool internals, local-run
instructions, and the contributor walkthrough for adding a new tool. Quick start:

```bash
cd server
uv sync
uv run pytest
```

## Repo layout

```
server/    — FastMCP server (Python 3.12+)
deploy/    — systemd unit, Caddyfile, idempotent install.sh
```

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md).

## Security

Vulnerability disclosure and the threat model are in [`SECURITY.md`](SECURITY.md).

## License

Apache-2.0 — see [LICENSE](LICENSE).
