#!/usr/bin/env bash
# Idempotent installer for sandstorm-mcp on a Debian/Ubuntu Linux host.
#
# Usage (as a sudo-capable user that owns $REPO_DIR):
#   SANDSTORM_MCP_TOKEN=<your-token> SANDSTORM_DOMAIN=mcp.example.com bash deploy/install.sh
#
# Re-run anytime: skips already-installed components, updates unit / Caddyfile
# from the repo, syncs Python deps, restarts services.

set -euo pipefail

REPO_DIR="${REPO_DIR:-/home/dev/sandstorm}"
ENV_FILE="/etc/sandstorm-mcp.env"
DOMAIN="${SANDSTORM_DOMAIN:?SANDSTORM_DOMAIN must be set (e.g. mcp.example.com)}"

echo "==> Installing system deps"
sudo apt-get update -qq
sudo apt-get install -y -qq curl ca-certificates debian-keyring debian-archive-keyring apt-transport-https git

echo "==> Installing Caddy (official repo)"
if ! command -v caddy &>/dev/null; then
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list >/dev/null
    sudo apt-get update -qq
    sudo apt-get install -y -qq caddy
else
    echo "    Caddy already installed ($(caddy version | head -1))"
fi

echo "==> Installing uv"
if ! command -v uv &>/dev/null; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
fi
export PATH="$HOME/.local/bin:$PATH"

echo "==> Creating workspace directories"
mkdir -p /home/dev/workspace /home/dev/sessions /home/dev/.sandstorm-mcp

echo "==> Syncing Python deps"
cd "$REPO_DIR/server"
uv sync

echo "==> Writing env file"
if [[ ! -f "$ENV_FILE" ]]; then
    if [[ -z "${SANDSTORM_MCP_TOKEN:-}" ]]; then
        echo "ERROR: SANDSTORM_MCP_TOKEN not set in environment." >&2
        echo "       Export it and re-run, or create $ENV_FILE manually." >&2
        exit 1
    fi
    sudo tee "$ENV_FILE" >/dev/null <<EOF
SANDSTORM_MCP_TOKEN=${SANDSTORM_MCP_TOKEN}
SANDSTORM_MCP_HOST=127.0.0.1
SANDSTORM_MCP_PORT=8080
SANDSTORM_WORKSPACE_ROOT=/home/dev
SANDSTORM_STATE_DIR=/home/dev/.sandstorm-mcp
MAX_INSTANCES=5
EOF
    sudo chmod 600 "$ENV_FILE"
    sudo chown root:root "$ENV_FILE"
    echo "    Wrote $ENV_FILE"
else
    echo "    $ENV_FILE already exists — leaving it alone"
fi

echo "==> Installing systemd unit"
sudo cp "$REPO_DIR/deploy/sandstorm-mcp.service" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable sandstorm-mcp >/dev/null
sudo systemctl restart sandstorm-mcp

echo "==> Installing Caddy config"
sudo mkdir -p /var/log/caddy
sudo sed "s|SANDSTORM_DOMAIN|${DOMAIN}|g" "$REPO_DIR/deploy/Caddyfile" | sudo tee /etc/caddy/Caddyfile >/dev/null
if sudo systemctl is-active --quiet caddy; then
    sudo systemctl reload caddy || sudo systemctl restart caddy
else
    sudo systemctl enable --now caddy >/dev/null
fi

echo "==> Waiting for services..."
sleep 3

if systemctl is-active --quiet sandstorm-mcp; then
    echo "    sandstorm-mcp: active"
else
    echo "    sandstorm-mcp: FAILED" >&2
    sudo journalctl -u sandstorm-mcp -n 40 --no-pager
    exit 1
fi

if systemctl is-active --quiet caddy; then
    echo "    caddy: active"
else
    echo "    caddy: FAILED" >&2
    sudo journalctl -u caddy -n 40 --no-pager
    exit 1
fi

echo ""
echo "==> Local smoke test (no Caddy)"
TOKEN=$(sudo awk -F= '$1=="SANDSTORM_MCP_TOKEN"{print $2}' "$ENV_FILE")
if curl -fsS http://localhost:8080/health >/dev/null; then
    echo "    /health: OK"
else
    echo "    /health: FAILED" >&2
    exit 1
fi
status=$(curl -s -o /dev/null -w '%{http_code}' http://localhost:8080/mcp -X POST)
echo "    /mcp (no auth): HTTP $status  (expect 401)"
status=$(curl -s -o /dev/null -w '%{http_code}' http://localhost:8080/mcp \
    -X POST \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -H "Accept: application/json, text/event-stream" \
    -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"install-smoke","version":"1"}}}')
echo "    /mcp (with auth): HTTP $status  (expect 200)"

echo ""
echo "==> Done."
echo "    Public URL: https://$DOMAIN"
echo "    Tail logs:  sudo journalctl -u sandstorm-mcp -f"
echo "    Caddy logs: sudo tail -f /var/log/caddy/sandstorm-mcp.log"
