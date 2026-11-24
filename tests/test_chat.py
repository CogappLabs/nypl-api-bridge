from types import SimpleNamespace
from typing import Any

import httpx

from nypl_api_bridge.api import NyplApi, build_http_client
from nypl_api_bridge.chat import run_turn
from nypl_api_bridge.personas import PERSONAS


class ScriptedMessages:
    """Stands in for `client.beta.messages`: returns canned responses and records each request."""

    def __init__(self, responses: list[Any]) -> None:
        self._responses = responses
        self.requests: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> Any:
        self.requests.append({**kwargs, "messages": list(kwargs["messages"])})
        return self._responses.pop(0)


def block(**fields: Any) -> SimpleNamespace:
    return SimpleNamespace(**fields)


def make_api() -> NyplApi:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"nyplAPI": {"response": {"result": [{"title": "Coney Island, 1905"}]}}})

    return NyplApi(build_http_client("t", transport=httpx.MockTransport(handler)))


async def test_tool_loop_runs_mcp_tool_and_applies_persona() -> None:
    messages = ScriptedMessages(
        [
            SimpleNamespace(
                stop_reason="tool_use",
                content=[block(type="tool_use", id="tu_1", name="search_items", input={"query": "coney island"})],
            ),
            SimpleNamespace(stop_reason="end_turn", content=[block(type="text", text="Ay, Coney Island, 1905!")]),
        ]
    )
    history: list[dict[str, Any]] = []
    calls: list[str] = []

    result = await run_turn(
        anthropic_client=SimpleNamespace(beta=SimpleNamespace(messages=messages)),
        nypl_api=make_api(),
        history=history,
        question="Old photos of Coney Island?",
        persona_change=PERSONAS["taxi_driver"],
        on_tool_call=lambda name, args: calls.append(name),
    )

    assert result.text == "Ay, Coney Island, 1905!"
    assert calls == ["search_items"]
    first = messages.requests[0]["messages"]
    assert first[0] == {"role": "user", "content": "Old photos of Coney Island?"}
    assert first[1]["role"] == "system" and "Taxi driver" in first[1]["content"]
    tool_result = history[3]["content"][0]
    assert tool_result["tool_use_id"] == "tu_1"
    assert "Coney Island, 1905" in tool_result["content"]
    assert tool_result["is_error"] is False
    assert [m["role"] for m in history] == ["user", "system", "assistant", "user", "assistant"]


async def test_no_persona_message_when_persona_unchanged() -> None:
    messages = ScriptedMessages([SimpleNamespace(stop_reason="end_turn", content=[block(type="text", text="Hi")])])
    history: list[dict[str, Any]] = []
    await run_turn(
        anthropic_client=SimpleNamespace(beta=SimpleNamespace(messages=messages)),
        nypl_api=make_api(),
        history=history,
        question="Hello",
        persona_change=None,
        on_tool_call=lambda name, args: None,
    )
    assert [m["role"] for m in history] == ["user", "assistant"]
