"""The HTTP app (nypl_api_bridge.remote) as a hosting platform would serve it, with NYPL mocked."""

import json
from collections.abc import Iterator

import httpx
import pytest
from starlette.testclient import TestClient

from nypl_api_bridge.api import NyplApi, build_http_client
from nypl_api_bridge.remote import create_app

# A public hostname, as on Vercel: requests must not be rejected for not being localhost.
BASE_URL = "https://nypl-api-bridge.vercel.app"
MCP_HEADERS = {"Accept": "application/json, text/event-stream"}


def fake_nypl(request: httpx.Request) -> httpx.Response:
    assert request.url.path == "/api/v2/items/total"
    return httpx.Response(200, json={"nyplAPI": {"request": {}, "response": {"count": {"$": "123"}}}})


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app(NyplApi(build_http_client("test-token", transport=httpx.MockTransport(fake_nypl))))
    with TestClient(app, base_url=BASE_URL) as c:  # `with` runs the lifespan, which starts the MCP session manager
        yield c


def rpc(client: TestClient, method: str, params: dict | None = None) -> dict:
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
    response = client.post("/mcp", headers=MCP_HEADERS, json=body)
    assert response.status_code == 200, response.text
    if response.headers["content-type"].startswith("text/event-stream"):
        data = [line.removeprefix("data: ") for line in response.text.splitlines() if line.startswith("data: ")]
        return json.loads(data[-1])
    return response.json()


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_lists_tools_without_login_or_session(client: TestClient) -> None:
    tools = {tool["name"] for tool in rpc(client, "tools/list")["result"]["tools"]}
    assert {"search_items", "get_item", "get_total_items"} <= tools


def test_calls_a_tool(client: TestClient) -> None:
    result = rpc(client, "tools/call", {"name": "get_total_items", "arguments": {}})["result"]
    assert not result.get("isError"), result
    assert "123" in json.dumps(result)
