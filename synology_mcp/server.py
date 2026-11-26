"""Entry point for the Synology MCP server.

Supports both ``stdio`` (default) and ``streamable-http`` / ``sse`` transports.
When ``MCP_HTTP=true`` or ``MCP_TRANSPORT=streamable-http`` (or ``--http`` CLI flag),
starts a Streamable HTTP server on ``MCP_HOST:MCP_PORT`` (default ``0.0.0.0:8765/mcp``)
with optional Bearer token authentication (``MCP_API_TOKEN``) and a ``/health`` endpoint.
"""

from __future__ import annotations

import argparse
import hmac
import sys

from . import config, tools  # noqa: F401  (import registers all tools)
from .app import mcp


def _build_http_asgi_app(transport: str):
    """Build a Starlette/ASGI app for Streamable HTTP or SSE with optional Bearer auth."""
    from starlette.responses import JSONResponse

    inner_app = (
        mcp.sse_app() if transport == "sse" else mcp.streamable_http_app()
    )
    expected_token = config.MCP_API_TOKEN

    async def asgi_wrapper(scope, receive, send):
        if scope["type"] == "http":
            path = scope.get("path", "")
            if path in ("/", "/health"):
                res = JSONResponse({"ok": True, "service": "synology-mcp", "transport": transport})
                await res(scope, receive, send)
                return

            if expected_token:
                headers = {k.decode("latin1").lower(): v.decode("latin1") for k, v in scope.get("headers", [])}
                auth = headers.get("authorization", "")
                token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
                if not token or not hmac.compare_digest(token, expected_token):
                    res = JSONResponse({"error": "Unauthorized"}, status_code=401)
                    await res(scope, receive, send)
                    return

        await inner_app(scope, receive, send)

    return asgi_wrapper


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Synology DSM 7 MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http", "sse"],
        default=None,
        help="Transport protocol (default: stdio, or streamable-http if MCP_HTTP=true)",
    )
    parser.add_argument(
        "--http",
        action="store_true",
        help="Shortcut for --transport streamable-http",
    )
    parser.add_argument("--host", default=None, help="HTTP bind host (default: MCP_HOST or 0.0.0.0)")
    parser.add_argument("--port", type=int, default=None, help="HTTP bind port (default: MCP_PORT or 8765)")
    args = parser.parse_args(argv)

    transport = args.transport
    if args.http:
        transport = "streamable-http"
    elif not transport:
        transport = "streamable-http" if config.MCP_HTTP else config.MCP_TRANSPORT

    if args.host:
        config.MCP_HOST = args.host
        mcp.settings.host = args.host
    if args.port:
        config.MCP_PORT = args.port
        mcp.settings.port = args.port

    if transport in ("streamable-http", "sse"):
        import uvicorn

        app = _build_http_asgi_app(transport)
        print(
            f"Starting Synology MCP ({transport}) on http://{config.MCP_HOST}:{config.MCP_PORT}{config.MCP_PATH}",
            file=sys.stderr,
        )
        uvicorn.run(app, host=config.MCP_HOST, port=config.MCP_PORT, log_level="info")
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
