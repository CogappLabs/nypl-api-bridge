"""One chat turn: Claude + the NYPL MCP server (loaded in-process), with a selectable persona."""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from anthropic import AsyncAnthropic
from fastmcp import Client
from mcp.types import TextContent

from nypl_api_bridge.api import NyplApi
from nypl_api_bridge.logs import preview
from nypl_api_bridge.personas import BASE_SYSTEM_PROMPT, Persona, persona_switch_message
from nypl_api_bridge.server import create_server

MODEL = "claude-opus-5-5"
MAX_TOOL_ROUNDS = 12

ToolCallHook = Callable[[str, dict[str, Any]], None]

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class TurnResult:
    text: str
    stop_reason: str | None


@dataclass
class _TurnStats:
    claude_calls: int = 0
    tool_calls: int = 0
    tokens: dict[str, int] = field(default_factory=dict)

    def add_usage(self, usage: Any) -> None:
        for name in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"):
            self.tokens[name] = self.tokens.get(name, 0) + (getattr(usage, name, None) or 0)


def _to_claude_tool(tool: Any) -> dict[str, Any]:
    return {"name": tool.name, "description": tool.description or "", "input_schema": tool.input_schema}


def _result_text(result: Any) -> str:
    texts = [block.text for block in result.content if isinstance(block, TextContent)]
    return "\n".join(texts) if texts else "(no content)"


def _final_text(response: Any) -> str:
    return "\n\n".join(block.text for block in response.content if block.type == "text")


def _log_response(round_no: int, response: Any, elapsed_ms: float) -> None:
    """One INFO summary line per Claude response, plus fallback/refusal details and the text Claude wrote."""
    usage = getattr(response, "usage", None)
    log.info(
        "Claude round %d <- stop_reason=%s model=%s request_id=%s %.0f ms | tokens in=%s out=%s "
        "cache_read=%s cache_write=%s | blocks=%s",
        round_no,
        response.stop_reason,
        getattr(response, "model", "?"),
        getattr(response, "_request_id", "?"),
        elapsed_ms,
        getattr(usage, "input_tokens", "?"),
        getattr(usage, "output_tokens", "?"),
        getattr(usage, "cache_read_input_tokens", "?"),
        getattr(usage, "cache_creation_input_tokens", "?"),
        [block.type for block in response.content],
    )
    for block in response.content:
        if block.type == "fallback":  # server-side fallback: the requested model declined, another one continued
            log.warning("Claude fallback: %s declined, %s continued", block.from_.model, block.to.model)
        elif block.type == "text":
            log.info("Claude text: %s", preview(block.text))
            log.debug("Claude text (full):\n%s", block.text)
    if response.stop_reason == "refusal":
        details = getattr(response, "stop_details", None)
        log.warning(
            "Claude refused: category=%s explanation=%s",
            getattr(details, "category", None),
            getattr(details, "explanation", None),
        )


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
    turn_started = time.perf_counter()
    stats = _TurnStats()
    log.info("Question: %s", preview(question, 1000))
    log.info(
        "Context: %d prior messages in history; persona %s",
        len(history),
        f"switching to {persona_change.key!r}" if persona_change else "unchanged",
    )

    history.append({"role": "user", "content": question})
    if persona_change is not None:
        # Mid-conversation system message: switches voice without invalidating the cached prefix.
        history.append({"role": "system", "content": persona_switch_message(persona_change)})

    def finish(result: TurnResult) -> TurnResult:
        log.info(
            "Turn done: stop_reason=%s, %d Claude calls, %d tool calls, %.1f s | total tokens %s",
            result.stop_reason,
            stats.claude_calls,
            stats.tool_calls,
            time.perf_counter() - turn_started,
            stats.tokens,
        )
        return result

    async with Client(create_server(nypl_api)) as mcp:
        tools = [_to_claude_tool(t) for t in await mcp.list_tools()]
        log.debug("MCP tools offered to Claude: %s", [t["name"] for t in tools])

        for round_no in range(1, MAX_TOOL_ROUNDS + 1):
            log.info("Claude round %d -> %s with %d messages, %d tools", round_no, MODEL, len(history), len(tools))
            started = time.perf_counter()
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
            stats.claude_calls += 1
            stats.add_usage(getattr(response, "usage", None))
            _log_response(round_no, response, (time.perf_counter() - started) * 1000)
            history.append({"role": "assistant", "content": response.content})

            if response.stop_reason != "tool_use":
                return finish(TurnResult(text=_final_text(response), stop_reason=response.stop_reason))

            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    stats.tool_calls += 1
                    log.info("Tool call %s: %s(%s)", block.id, block.name, preview(block.input, 1000))
                    on_tool_call(block.name, block.input)
                    tool_started = time.perf_counter()
                    result = await mcp.call_tool(block.name, block.input, raise_on_error=False)
                    content = _result_text(result)
                    log.log(
                        logging.WARNING if result.is_error else logging.INFO,
                        "Tool result %s: %s in %.0f ms, %d chars: %s",
                        block.id,
                        "ERROR" if result.is_error else "ok",
                        (time.perf_counter() - tool_started) * 1000,
                        len(content),
                        preview(content, 200),
                    )
                    log.debug("Tool result %s (full, as sent to Claude):\n%s", block.id, content)
                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": content,
                            "is_error": result.is_error,
                        }
                    )
            history.append({"role": "user", "content": tool_results})

    log.warning("Hit MAX_TOOL_ROUNDS=%d without a final answer", MAX_TOOL_ROUNDS)
    return finish(
        TurnResult(text="I ran out of tool calls before finishing. Try a narrower question.", stop_reason=None)
    )
