import json

import httpx
import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from nypl_api_bridge.api import NyplApi, build_http_client
from nypl_api_bridge.server import create_server

UUID = "510d47da-d4a5-a3d9-e040-e00a18064a99"


def make_client(handler, seen: list[httpx.Request]) -> Client:
    def recording_handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    http = build_http_client("test-token", transport=httpx.MockTransport(recording_handler))
    return Client(create_server(NyplApi(http)))


def envelope(response: dict) -> httpx.Response:
    return httpx.Response(200, json={"nyplAPI": {"request": {}, "response": response}})


async def test_search_builds_v2_request_and_unwraps_envelope() -> None:
    seen: list[httpx.Request] = []
    async with make_client(lambda r: envelope({"numResults": "1", "result": [{"uuid": UUID}]}), seen) as client:
        result = await client.call_tool(
            "search_items",
            {"query": "cats", "public_domain_only": True, "filters": ["typeOfResource:still image"]},
        )

    request = seen[0]
    assert request.url.path == "/api/v2/items/search"
    assert request.url.params["q"] == "cats"
    assert request.url.params["publicDomainOnly"] == "true"
    assert request.url.params.get_list("filter[]") == ["typeOfResource:still image"]
    assert request.headers["Authorization"] == 'Token token="test-token"'
    assert json.loads(result.content[0].text) == {"numResults": "1", "result": [{"uuid": UUID}]}


async def test_browse_collection_items_view() -> None:
    seen: list[httpx.Request] = []
    async with make_client(lambda r: envelope({}), seen) as client:
        await client.call_tool("browse_collection", {"uuid": UUID, "view": "items", "page": 2})

    assert seen[0].url.path == f"/api/v2/collections/{UUID}/items"
    assert seen[0].url.params["page"] == "2"


async def test_invalid_uuid_never_hits_network() -> None:
    seen: list[httpx.Request] = []
    async with make_client(lambda r: envelope({}), seen) as client:
        with pytest.raises(ToolError, match="Not a valid NYPL UUID"):
            await client.call_tool("get_item", {"uuid": "../../collections"})
    assert seen == []


async def test_unauthorised_maps_to_clear_error() -> None:
    seen: list[httpx.Request] = []
    async with make_client(lambda r: httpx.Response(401, text="HTTP Token: Access denied."), seen) as client:
        with pytest.raises(ToolError, match="NYPL_API_TOKEN"):
            await client.call_tool("get_total_items", {})


async def test_all_tools_registered_read_only() -> None:
    async with make_client(lambda r: envelope({}), []) as client:
        tools = await client.list_tools()
    assert len(tools) == 13
    assert all(t.annotations is not None and t.annotations.read_only_hint for t in tools)
