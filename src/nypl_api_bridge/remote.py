"""The MCP server over HTTP, for hosting online (e.g. on Vercel). No login: anyone with the URL can call the tools.

MCP endpoint: /mcp. Health check: /health. The ASGI app itself is built in the repo-root index.py, which is
Vercel's entrypoint. Run it locally with:
    NYPL_API_TOKEN=... uv run uvicorn index:app --port 8000
"""

import os

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse

from nypl_api_bridge.api import NyplApi, build_http_client
from nypl_api_bridge.logs import configure_logging
from nypl_api_bridge.server import create_server


def create_app(api: NyplApi) -> Starlette:
    mcp = create_server(api)

    @mcp.custom_route("/health", methods=["GET"])
    async def health(request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    # Stateless: each request stands alone, as serverless instances don't share sessions.
    return mcp.http_app(stateless_http=True)


def create_app_from_env() -> Starlette:
    token = os.environ.get("NYPL_API_TOKEN", "")
    if not token:
        raise RuntimeError("NYPL_API_TOKEN is not set. Add it to the host's environment variables.")
    # Vercel's filesystem is read-only, so log to stderr only there (it shows up in Vercel's logs).
    configure_logging(log_to_file=not os.environ.get("VERCEL"))
    return create_app(NyplApi(build_http_client(token, transport=None)))
