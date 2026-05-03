"""Token auth + OAuth 2.0 stateless flow — ports `apps/mcp/src/oauth.ts`.

The worker accepts two bearer shapes on `/mcp`:

1. The raw shared token `SANDSTORM_MCP_TOKEN` (backward compat for CLI clients).
2. An HMAC-signed OAuth access token issued via the `/oauth/*` flow.

Both paths are supported here with identical semantics to the worker.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import html
import json
import time
from dataclasses import dataclass

AUTH_CODE_TTL_SECONDS = 600
ACCESS_TOKEN_TTL_SECONDS = 30 * 24 * 3600


def _b64url_encode_bytes(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_encode_str(s: str) -> str:
    return _b64url_encode_bytes(s.encode("utf-8"))


def _b64url_decode_str(s: str) -> str:
    padding = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + padding).decode("utf-8")


def _hmac_sign(key: str, payload: str) -> str:
    sig = hmac.new(
        key.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256
    ).digest()
    return _b64url_encode_bytes(sig)


def _sha256_b64url(s: str) -> str:
    digest = hashlib.sha256(s.encode("utf-8")).digest()
    return _b64url_encode_bytes(digest)


@dataclass(frozen=True)
class AuthCtx:
    token: str
    client_id: str | None
    is_oauth: bool


def create_auth_code(
    auth_token: str,
    client_id: str,
    code_challenge: str,
    code_challenge_method: str,
    redirect_uri: str,
) -> str:
    payload = json.dumps(
        {
            "t": int(time.time() * 1000),
            "c": client_id,
            "cc": code_challenge,
            "cm": code_challenge_method,
            "r": redirect_uri,
        },
        separators=(",", ":"),
    )
    sig = _hmac_sign(auth_token, payload)
    return f"{sig}.{_b64url_encode_str(payload)}"


def exchange_auth_code(
    auth_token: str,
    code: str,
    client_id: str,
    code_verifier: str,
    redirect_uri: str,
) -> str | None:
    dot = code.find(".")
    if dot < 0:
        return None

    sig = code[:dot]
    b64_payload = code[dot + 1 :]

    try:
        payload = _b64url_decode_str(b64_payload)
    except Exception:
        return None

    expected = _hmac_sign(auth_token, payload)
    if not hmac.compare_digest(sig, expected):
        return None

    try:
        data = json.loads(payload)
    except Exception:
        return None

    if int(time.time() * 1000) - int(data.get("t", 0)) > AUTH_CODE_TTL_SECONDS * 1000:
        return None
    if data.get("c") != client_id:
        return None
    if data.get("r") != redirect_uri:
        return None

    method = data.get("cm")
    challenge = data.get("cc")
    if method == "S256":
        if _sha256_b64url(code_verifier) != challenge:
            return None
    elif method == "plain":
        if code_verifier != challenge:
            return None
    else:
        return None

    return create_access_token(auth_token, client_id)


def create_access_token(auth_token: str, client_id: str) -> str:
    payload = json.dumps(
        {"t": int(time.time() * 1000), "c": client_id, "k": "access"},
        separators=(",", ":"),
    )
    sig = _hmac_sign(auth_token, payload)
    return f"{sig}.{_b64url_encode_str(payload)}"


def verify_bearer(auth_token: str, token: str) -> AuthCtx | None:
    if not token:
        return None

    if hmac.compare_digest(token, auth_token):
        return AuthCtx(token=token, client_id=None, is_oauth=False)

    dot = token.find(".")
    if dot < 0:
        return None

    sig = token[:dot]
    b64_payload = token[dot + 1 :]

    try:
        payload = _b64url_decode_str(b64_payload)
    except Exception:
        return None

    expected = _hmac_sign(auth_token, payload)
    if not hmac.compare_digest(sig, expected):
        return None

    try:
        data = json.loads(payload)
    except Exception:
        return None

    if data.get("k") != "access":
        return None
    if (
        int(time.time() * 1000) - int(data.get("t", 0))
        > ACCESS_TOKEN_TTL_SECONDS * 1000
    ):
        return None

    return AuthCtx(token=token, client_id=data.get("c"), is_oauth=True)


def register_client(
    auth_token: str, client_name: str, redirect_uris: list[str]
) -> dict:
    client_id = _hmac_sign(
        auth_token, f"client:{client_name}:{','.join(redirect_uris)}"
    )
    return {
        "client_id": client_id,
        "client_name": client_name,
        "redirect_uris": redirect_uris,
        "token_endpoint_auth_method": "none",
    }


def authorize_page_html(
    client_name: str,
    form_action: str,
    hidden_fields: dict[str, str],
    error: str | None = None,
) -> str:
    """Port of the worker's authorize page. HTML kept verbatim for pixel parity."""
    hidden_inputs = "\n      ".join(
        f'<input type="hidden" name="{html.escape(k)}" value="{html.escape(v)}" />'
        for k, v in hidden_fields.items()
    )
    error_block = f'<div class="error">{html.escape(error)}</div>' if error else ""
    return f"""<!DOCTYPE html>
<html><head>
  <title>Authorize - Sandstorm MCP</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body {{ font-family: system-ui, sans-serif; max-width: 400px; margin: 80px auto; padding: 20px; background: #0f172a; color: #e2e8f0; }}
    h1 {{ font-size: 1.5rem; text-align: center; margin-bottom: 8px; }}
    p {{ text-align: center; color: #94a3b8; font-size: 0.9rem; }}
    .card {{ background: #1e293b; border-radius: 12px; padding: 24px; margin-top: 24px; }}
    label {{ display: block; margin-bottom: 6px; font-size: 0.85rem; color: #94a3b8; }}
    input[type=password] {{ width: 100%; padding: 10px 12px; border: 1px solid #334155; border-radius: 8px; background: #0f172a; color: #e2e8f0; font-size: 1rem; box-sizing: border-box; }}
    button {{ width: 100%; padding: 10px; margin-top: 16px; border: none; border-radius: 8px; background: #3b82f6; color: white; font-size: 1rem; cursor: pointer; }}
    button:hover {{ background: #2563eb; }}
    .error {{ color: #f87171; text-align: center; margin-top: 12px; font-size: 0.85rem; }}
    .client {{ color: #60a5fa; font-weight: 600; }}
  </style>
</head>
<body>
  <h1>Sandstorm MCP</h1>
  <p><span class="client">{html.escape(client_name)}</span> wants to access your dev environment</p>
  <div class="card">
    <form method="POST" action="{html.escape(form_action)}">
      {hidden_inputs}
      <label for="password">Enter access token to authorize:</label>
      <input type="password" name="password" id="password" required autofocus />
      {error_block}
      <button type="submit">Authorize</button>
    </form>
  </div>
</body>
</html>"""
