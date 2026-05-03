"""Starlette app assembly: CORS, auth, OAuth endpoints, /health, /session, /mcp."""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import logging
from typing import Awaitable, Callable

from fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Mount, Route

from . import auth as auth_module
from .config import Config
from .health import node_health
from .security import RateLimiter
from .sessions import SessionService, SessionStore, reap_expired_loop
from .tools import register_all

logger = logging.getLogger(__name__)


CORS_ALLOW_HEADERS = [
    "Content-Type",
    "Authorization",
    "mcp-session-id",
    "Last-Event-ID",
    "mcp-protocol-version",
]
CORS_EXPOSE_HEADERS = ["mcp-session-id", "mcp-protocol-version"]


def _origin(request: Request) -> str:
    return f"{request.url.scheme}://{request.url.netloc}"


def _unauthorized(origin: str) -> JSONResponse:
    return JSONResponse(
        {"error": "Unauthorized"},
        status_code=401,
        headers={
            "WWW-Authenticate": (
                f'Bearer resource_metadata="{origin}/.well-known/oauth-protected-resource"'
            )
        },
    )


class AuthMiddleware(BaseHTTPMiddleware):
    """Authenticates /mcp (always) and /session/* (only if SESSION_AUTH_TOKEN is set)."""

    def __init__(
        self,
        app,
        config: Config,
        rate_limiter: RateLimiter,
    ) -> None:
        super().__init__(app)
        self.config = config
        self.rate_limiter = rate_limiter

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        path = request.url.path

        if request.method == "OPTIONS":
            return await call_next(request)

        if path == "/mcp" or path.startswith("/mcp/"):
            header = request.headers.get("authorization", "")
            token = (
                header.removeprefix("Bearer ").strip()
                if header.startswith("Bearer ")
                else ""
            )
            ctx = (
                auth_module.verify_bearer(self.config.auth_token, token)
                if token
                else None
            )
            if not ctx:
                return _unauthorized(_origin(request))
            if not self.rate_limiter.allow(token):
                return JSONResponse(
                    {"error": "Rate limit exceeded (100 req/min)"}, status_code=429
                )
            request.state.auth = ctx
            return await call_next(request)

        if path.startswith("/session/") and self.config.session_auth_token:
            header = request.headers.get("authorization", "")
            token = (
                header.removeprefix("Bearer ").strip()
                if header.startswith("Bearer ")
                else ""
            )
            if not hmac.compare_digest(token, self.config.session_auth_token):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)

        return await call_next(request)


def build_app(config: Config) -> Starlette:
    mcp = FastMCP(name="sandstorm", version="2.0.0")
    register_all(mcp, config)

    store = SessionStore(config.db_path)
    session_service = SessionService(config, store)

    mcp_app = mcp.http_app(path="/mcp", transport="http", stateless_http=True)
    mcp_lifespan = mcp_app.lifespan

    @contextlib.asynccontextmanager
    async def lifespan(app: Starlette):
        await store.init()
        reaper_task = asyncio.create_task(reap_expired_loop(session_service))
        logger.info(
            "sandstorm-mcp started",
            extra={"extra_fields": {"host": config.host, "port": config.port}},
        )
        try:
            async with mcp_lifespan(app):
                yield
        finally:
            reaper_task.cancel()
            try:
                await reaper_task
            except (asyncio.CancelledError, Exception):
                pass
            logger.info("sandstorm-mcp stopped")

    # ─── Non-MCP handlers ───────────────────────────────────

    async def health(request: Request) -> JSONResponse:
        h = await node_health(config, store)
        return JSONResponse({"server": "sandstorm", "version": "2.0.0", **h})

    async def protected_resource_meta(request: Request) -> JSONResponse:
        origin = _origin(request)
        return JSONResponse(
            {
                "resource": origin,
                "authorization_servers": [origin],
                "bearer_methods_supported": ["header"],
            }
        )

    async def authorization_server_meta(request: Request) -> JSONResponse:
        origin = _origin(request)
        return JSONResponse(
            {
                "issuer": origin,
                "authorization_endpoint": f"{origin}/oauth/authorize",
                "token_endpoint": f"{origin}/oauth/token",
                "registration_endpoint": f"{origin}/oauth/register",
                "response_types_supported": ["code"],
                "grant_types_supported": ["authorization_code"],
                "token_endpoint_auth_methods_supported": ["none"],
                "code_challenge_methods_supported": ["S256"],
            }
        )

    async def oauth_register(request: Request) -> JSONResponse:
        try:
            body = await request.json()
        except Exception:
            return JSONResponse(
                {"error": "invalid_request", "error_description": "Invalid JSON body"},
                status_code=400,
            )
        client_name = body.get("client_name") or "unknown"
        redirect_uris = body.get("redirect_uris") or []
        if not redirect_uris:
            return JSONResponse(
                {
                    "error": "invalid_request",
                    "error_description": "redirect_uris required",
                },
                status_code=400,
            )
        result = auth_module.register_client(
            config.auth_token, client_name, redirect_uris
        )
        return JSONResponse(result, status_code=201)

    async def oauth_authorize_get(request: Request) -> Response:
        qp = request.query_params
        client_id = qp.get("client_id") or ""
        redirect_uri = qp.get("redirect_uri") or ""
        state = qp.get("state") or ""
        code_challenge = qp.get("code_challenge") or ""
        code_challenge_method = qp.get("code_challenge_method") or "S256"
        response_type = qp.get("response_type") or ""

        if response_type != "code":
            return JSONResponse({"error": "unsupported_response_type"}, status_code=400)
        if not client_id or not redirect_uri or not code_challenge:
            return JSONResponse(
                {
                    "error": "invalid_request",
                    "error_description": "Missing required parameters",
                },
                status_code=400,
            )

        html = auth_module.authorize_page_html(
            client_name=qp.get("client_name") or "Claude.ai",
            form_action="/oauth/authorize",
            hidden_fields={
                "response_type": response_type,
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "state": state,
                "code_challenge": code_challenge,
                "code_challenge_method": code_challenge_method,
            },
        )
        return HTMLResponse(html)

    async def oauth_authorize_post(request: Request) -> Response:
        form = await request.form()
        password = form.get("password") or ""
        client_id = form.get("client_id") or ""
        redirect_uri = form.get("redirect_uri") or ""
        state = form.get("state") or ""
        code_challenge = form.get("code_challenge") or ""
        code_challenge_method = form.get("code_challenge_method") or "S256"

        if not hmac.compare_digest(password, config.auth_token):
            html = auth_module.authorize_page_html(
                client_name="Claude.ai",
                error="Incorrect access token. Try again.",
                form_action="/oauth/authorize",
                hidden_fields={
                    "response_type": "code",
                    "client_id": client_id,
                    "redirect_uri": redirect_uri,
                    "state": state,
                    "code_challenge": code_challenge,
                    "code_challenge_method": code_challenge_method,
                },
            )
            return HTMLResponse(html)

        code = auth_module.create_auth_code(
            config.auth_token,
            client_id,
            code_challenge,
            code_challenge_method,
            redirect_uri,
        )
        separator = "&" if "?" in redirect_uri else "?"
        location = f"{redirect_uri}{separator}code={code}"
        if state:
            location += f"&state={state}"
        return RedirectResponse(location, status_code=302)

    async def oauth_token(request: Request) -> Response:
        content_type = request.headers.get("content-type", "")
        if "application/json" in content_type:
            try:
                body = await request.json()
            except Exception:
                body = {}
        else:
            form = await request.form()
            body = dict(form)

        grant_type = body.get("grant_type") or ""
        code = body.get("code") or ""
        client_id = body.get("client_id") or ""
        code_verifier = body.get("code_verifier") or ""
        redirect_uri = body.get("redirect_uri") or ""

        if grant_type != "authorization_code":
            return JSONResponse({"error": "unsupported_grant_type"}, status_code=400)

        token = auth_module.exchange_auth_code(
            config.auth_token, code, client_id, code_verifier, redirect_uri
        )
        if not token:
            return JSONResponse(
                {
                    "error": "invalid_grant",
                    "error_description": "Invalid or expired authorization code",
                },
                status_code=400,
            )
        return JSONResponse(
            {
                "access_token": token,
                "token_type": "Bearer",
                "expires_in": auth_module.ACCESS_TOKEN_TTL_SECONDS,
            }
        )

    # ─── Session routes ──────────────────────────────────────

    async def session_create(request: Request) -> Response:
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "Invalid JSON"}, status_code=400)
        try:
            result = await session_service.create(body)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except RuntimeError as exc:
            return JSONResponse({"error": str(exc)}, status_code=500)
        return JSONResponse(result, status_code=201)

    async def session_exec(request: Request) -> Response:
        sid = request.path_params["sid"]
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "Invalid JSON"}, status_code=400)
        try:
            result = await session_service.exec(sid, body)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        if result is None:
            return JSONResponse(
                {"error": "Session not found or expired"}, status_code=404
            )
        if result.get("__expired__"):
            return JSONResponse({"error": "Session expired"}, status_code=410)
        return JSONResponse(result)

    async def session_status(request: Request) -> Response:
        sid = request.path_params["sid"]
        result = await session_service.status(sid)
        if result is None:
            return JSONResponse({"error": "Session not found"}, status_code=404)
        return JSONResponse(result)

    async def session_extend(request: Request) -> Response:
        sid = request.path_params["sid"]
        try:
            body = await request.json()
        except Exception:
            body = {}
        additional = int(body.get("additional_minutes", 15))
        result = await session_service.extend(sid, additional)
        if result is None:
            return JSONResponse(
                {"error": "Session not found or expired"}, status_code=404
            )
        return JSONResponse(result)

    async def session_delete(request: Request) -> Response:
        sid = request.path_params["sid"]
        ok = await session_service.delete(sid)
        if not ok:
            return JSONResponse({"error": "Session not found"}, status_code=404)
        return JSONResponse({"success": True})

    routes = [
        Route("/health", health, methods=["GET"]),
        Route(
            "/.well-known/oauth-protected-resource",
            protected_resource_meta,
            methods=["GET"],
        ),
        Route(
            "/.well-known/oauth-authorization-server",
            authorization_server_meta,
            methods=["GET"],
        ),
        Route("/oauth/register", oauth_register, methods=["POST"]),
        Route("/oauth/authorize", oauth_authorize_get, methods=["GET"]),
        Route("/oauth/authorize", oauth_authorize_post, methods=["POST"]),
        Route("/oauth/token", oauth_token, methods=["POST"]),
        Route("/session/create", session_create, methods=["POST"]),
        Route("/session/{sid}/exec", session_exec, methods=["POST"]),
        Route("/session/{sid}/status", session_status, methods=["GET"]),
        Route("/session/{sid}/extend", session_extend, methods=["POST"]),
        Route("/session/{sid}", session_delete, methods=["DELETE"]),
        Mount("/", app=mcp_app),
    ]

    rate_limiter = RateLimiter()

    middleware = [
        Middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
            allow_headers=CORS_ALLOW_HEADERS,
            expose_headers=CORS_EXPOSE_HEADERS,
        ),
        Middleware(AuthMiddleware, config=config, rate_limiter=rate_limiter),
    ]

    app = Starlette(routes=routes, middleware=middleware, lifespan=lifespan)
    app.state.config = config
    return app
