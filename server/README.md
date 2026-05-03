# sandstorm-mcp (self-hosted)

FastMCP server that exposes 20 file/terminal/git/workspace tools to AI agents
over MCP streamable-HTTP. Runs on any Debian/Ubuntu host, fronted by Caddy.

## Architecture

```
claude.ai / Claude Code / any MCP client
        │  (MCP, streamable HTTP)
        ▼
  https://<your-domain>
        │  (Caddy TLS termination, Let's Encrypt)
        ▼
  http://127.0.0.1:8080   ← FastMCP process (this package)
        │  (asyncio.subprocess)
        ▼
  /bin/bash, git, pathlib, … on the host
```

No CF Workers, no KV, no D1, no sidecar agent. The FastMCP process is the executor.

## Tool surface (20 tools)

File ops (6): `file_read`, `file_write`, `file_delete`, `file_list`, `file_move`, `file_mkdir`.
Terminal (3): `terminal_exec`, `terminal_exec_background`, `terminal_kill`.
Git (9): `git_clone`, `git_status`, `git_commit`, `git_push`, `git_pull`, `git_branch`, `git_checkout`, `git_diff`, `git_log`.
Workspace (2): `workspace_info`, `workspace_install`.

Names and schemas mirror the prior Cloudflare Worker implementation exactly.

## Non-MCP endpoints

| Path                                      | Auth | Purpose |
|-------------------------------------------|------|---------|
| `GET /health`                             | none | Node health + active session count |
| `GET /.well-known/oauth-protected-resource` | none | RFC 9728 metadata |
| `GET /.well-known/oauth-authorization-server` | none | RFC 8414 metadata |
| `POST /oauth/register`                    | none | RFC 7591 DCR |
| `GET/POST /oauth/authorize`               | password form | OAuth 2.0 authorize |
| `POST /oauth/token`                       | PKCE | OAuth 2.0 token |
| `POST /session/create` + related          | optional bearer `SESSION_AUTH_TOKEN` | Session API (orchestrator) |

## Running locally

```bash
# Requires Python 3.12+
uv sync

# Set the bearer token (same one claude.ai clients will send)
export SANDSTORM_MCP_TOKEN=dev-token-change-me
export SANDSTORM_MCP_HOST=127.0.0.1
export SANDSTORM_MCP_PORT=8080
# Optional:
export SANDSTORM_WORKSPACE_ROOT=$HOME/sandstorm-sandbox   # defaults to /home/dev
export SANDSTORM_STATE_DIR=$HOME/sandstorm-sandbox/.sandstorm-mcp

# Start the server
uv run python -m sandstorm_mcp.main
```

Smoke test:

```bash
# No auth → 401
curl -i http://localhost:8080/mcp

# With auth → MCP discovery (JSON-RPC initialize)
curl -s http://localhost:8080/mcp \
  -X POST \
  -H "Authorization: Bearer $SANDSTORM_MCP_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"curl","version":"1"}}}'

# List tools
curl -s http://localhost:8080/mcp \
  -X POST \
  -H "Authorization: Bearer $SANDSTORM_MCP_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list"}'
```

## Adding a new tool

1. Pick the right module under `src/sandstorm_mcp/tools/`
   (`file_ops.py`, `git_ops.py`, `terminal.py`, `workspace.py`) or create a new one
   and wire it into `tools/__init__.py:register_all`.
2. Decorate the function with `@mcp.tool(name=..., description=...)`. Use `Annotated[T, Field(description="...")]` for parameters.
3. Return a string on success. Raise `fastmcp.exceptions.ToolError(msg)` to produce `isError: true`.
4. Add a test in `tests/test_tools.py`.

## Rotating the auth token

```bash
# 1. Pick a new strong token, e.g.:
NEW=$(python -c 'import secrets; print(secrets.token_urlsafe(32))')

# 2. Update the env file and restart
sudo sed -i "s|^SANDSTORM_MCP_TOKEN=.*|SANDSTORM_MCP_TOKEN=$NEW|" /etc/sandstorm-mcp.env
sudo systemctl restart sandstorm-mcp

# 3. Update the claude.ai custom connector with the new token
# 4. Save the new token to Proton Pass (vault: Claude)
```

Rotation invalidates every existing OAuth access token (they are HMAC-signed with
the server token). Clients using the raw bearer just need the new value.

## Logs

All logs are JSON on stdout → systemd-journald. Tail live:

```bash
sudo journalctl -u sandstorm-mcp -f
sudo journalctl -u sandstorm-mcp -n 200 --no-pager
```

Caddy access logs live at `/var/log/caddy/sandstorm-mcp.log` (JSON).
