"""Streamlit chat UI. Run with: uv run nypl-chat"""

import asyncio
import logging
import os
from typing import Any

import anthropic
import httpx
import streamlit as st

from nypl_api_bridge.api import NyplApi, build_http_client
from nypl_api_bridge.chat import ToolCallHook, TurnResult, run_turn
from nypl_api_bridge.logs import configure_logging, new_turn_id, reset_turn_id, set_turn_id
from nypl_api_bridge.personas import PERSONAS, Persona

configure_logging()
log = logging.getLogger("nypl_api_bridge.app")

STOP_REASON_NOTES = {
    "refusal": "Claude declined to answer that one.",
    "max_tokens": "The answer was cut off because it hit the length limit.",
}


async def answer(
    *,
    token: str,
    history: list[dict[str, Any]],
    question: str,
    persona_change: Persona | None,
    on_tool_call: ToolCallHook,
) -> TurnResult:
    # Clients are created inside the event loop that uses them (asyncio.run makes a new loop per turn).
    async with build_http_client(token, transport=None) as http, anthropic.AsyncAnthropic() as claude:
        return await run_turn(
            anthropic_client=claude,
            nypl_api=NyplApi(http),
            history=history,
            question=question,
            persona_change=persona_change,
            on_tool_call=on_tool_call,
        )


st.set_page_config(page_title="NYPL Collections Chat", page_icon="📚")
st.title("📚 Ask the NYPL Digital Collections")

nypl_token = os.environ.get("NYPL_API_TOKEN", "")
if not nypl_token:
    st.error("Set NYPL_API_TOKEN before starting the app.")
    st.stop()

if "history" not in st.session_state:
    st.session_state.history = []  # full API history, replayed unchanged every turn
    st.session_state.transcript = []  # (role, persona label, text) for display
    st.session_state.active_persona = None

with st.sidebar:
    persona_key = st.radio(
        "Reply persona", options=list(PERSONAS), format_func=lambda k: PERSONAS[k].label, key="persona_key"
    )
    st.caption("You can switch persona mid-conversation; the next reply uses the new voice.")
    if st.button("New conversation"):
        for key in ("history", "transcript", "active_persona"):
            del st.session_state[key]
        st.rerun()

for role, label, text in st.session_state.transcript:
    with st.chat_message(role):
        if label:
            st.caption(label)
        st.markdown(text)

if question := st.chat_input("Ask about maps, photographs, menus, manuscripts…"):
    persona = PERSONAS[persona_key]
    persona_change = persona if st.session_state.active_persona != persona.key else None

    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant"):
        st.caption(persona.label)
        history = st.session_state.history
        checkpoint = len(history)
        # asyncio.run copies this context, so every log line from Claude, MCP and NYPL calls gets the turn ID.
        turn_token = set_turn_id(new_turn_id())
        log.info("New question from the UI (persona %s)", persona.key)
        try:
            with st.status("Searching the collections…") as status:
                try:
                    result = asyncio.run(
                        answer(
                            token=nypl_token,
                            history=history,
                            question=question,
                            persona_change=persona_change,
                            on_tool_call=lambda name, args: status.write(f"`{name}` {args}"),
                        )
                    )
                except (anthropic.APIError, httpx.HTTPError) as e:
                    # Error boundary: drop this turn's partial messages so the next request starts from a valid history.
                    log.exception("Turn failed; discarding %d partial messages", len(history) - checkpoint)
                    del history[checkpoint:]
                    status.update(label="Something went wrong", state="error")
                    st.error(f"{type(e).__name__}: {e}")
                    st.stop()
                status.update(label="Done", state="complete", expanded=False)
        finally:
            reset_turn_id(turn_token)
        text = result.text or STOP_REASON_NOTES.get(result.stop_reason or "", "(no reply)")
        st.markdown(text)

    st.session_state.active_persona = persona.key
    st.session_state.transcript.append(("user", None, question))
    st.session_state.transcript.append(("assistant", persona.label, text))
