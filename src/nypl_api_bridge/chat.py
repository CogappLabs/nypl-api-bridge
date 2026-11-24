"""One chat turn: Claude + the NYPL MCP server (loaded in-process), with a selectable persona."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from anthropic import AsyncAnthropic
from fastmcp import Client
from mcp.types import TextContent

from nypl_api_bridge.api import NyplApi
from nypl_api_bridge.personas import BASE_SYSTEM_PROMPT, Persona, persona_switch_message
from nypl_api_bridge.server import create_server

MODEL = "claude-opus-5-5"
MAX_TOOL_ROUNDS = 12

ToolCallHook = Callable[[str, dict[str, Any]], None]


@dataclass(frozen=True)
class TurnResult:
    text: str
    stop_reason: str | None


def _to_claude_tool(tool: Any) -> dict[str, Any]:
    return {"name": tool.name, "description": tool.description or "", "input_schema": tool.input_schema}


def _result_text(result: Any) -> str:
    texts = [block.text for block in result.content if isinstance(block, TextContent)]
    return "\n".join(texts) if texts else "(no content)"


def _final_text(response: Any) -> str:
    return "\n\n".join(block.text for block in response.content if block.type == "text")


async def run_turn(
    *,
    anthropic_client: AsyncAnthropic,
    nypl_api: NyplApi,
    history: list[dict[str, Any]],
    question: str,
    persona_change: Persona | None,
    on_tool_call: ToolCallHook,
) -> TurnResult:
    """Append the user's question (and a persona switch, if any) to `history`, run the tool loop, and
    leave every assistant/tool message in `history` unchanged so later turns replay it exactly."""
    history.append({"role": "user", "content": question})
    if persona_change is not None:
        # Mid-conversation system message: switches voice without invalidating the cached prefix.
        history.append({"role": "system", "content": persona_switch_message(persona_change)})

    async with Client(create_server(nypl_api)) as mcp:
        tools = [_to_claude_tool(t) for t in await mcp.list_tools()]

        for _ in range(MAX_TOOL_ROUNDS):
            response = await anthropic_client.beta.messages.create(
                model=MODEL,
                max_tokens=16000,
                system=BASE_SYSTEM_PROMPT,
                tools=tools,
                messages=history,
                output_config={"effort": "medium"},
                cache_control={"type": "ephemeral"},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
            history.append({"role": "assistant", "content": response.content})

            if response.stop_reason != "tool_use":
                return TurnResult(text=_final_text(response), stop_reason=response.stop_reason)

            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    on_tool_call(block.name, block.input)
                    result = await mcp.call_tool(block.name, block.input, raise_on_error=False)
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": _result_text(result),
                            "is_error": result.is_error,
                        }
                    )
            history.append({"role": "user", "content": tool_results})

    return TurnResult(text="I ran out of tool calls before finishing. Try a narrower question.", stop_reason=None)
