"""Logging that traces one user question from the chat UI, through Claude's tool loop, to the NYPL HTTP calls.

Every record carries a short turn ID (one per question), so `grep 'turn 3f9a1c2e' logs/nypl.log` shows the whole
story of a single question.

- Console (stderr): level from NYPL_LOG_LEVEL (default INFO). Never stdout: the MCP server's stdio transport uses it.
- File (NYPL_LOG_DIR, default ./logs, file nypl.log): always DEBUG, which adds full tool results and Claude text.
"""

import contextvars
import json
import logging
import os
import sys
import uuid
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

ROOT_LOGGER = "nypl_api_bridge"
LOG_FILE_NAME = "nypl.log"
FORMAT = "%(asctime)s %(levelname)-7s [turn %(turn_id)s] %(name)s: %(message)s"

_turn_id: contextvars.ContextVar[str] = contextvars.ContextVar("turn_id", default="--------")


def new_turn_id() -> str:
    return uuid.uuid4().hex[:8]


def set_turn_id(turn_id: str) -> contextvars.Token[str]:
    """Tag every log record in this context (and in asyncio tasks started from it) with `turn_id`."""
    return _turn_id.set(turn_id)


def reset_turn_id(token: contextvars.Token[str]) -> None:
    _turn_id.reset(token)


class _TurnIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.turn_id = _turn_id.get()
        return True


def configure_logging(log_to_file: bool = True) -> None:
    """Attach console and file handlers to the package logger. Safe to call repeatedly (Streamlit reruns scripts)."""
    logger = logging.getLogger(ROOT_LOGGER)
    if any(getattr(h, "_nypl_handler", False) for h in logger.handlers):
        return

    logger.setLevel(logging.DEBUG)
    logger.propagate = False  # keep our lines out of Streamlit's / the root logger's output
    formatter = logging.Formatter(FORMAT)

    console = logging.StreamHandler(sys.stderr)
    console.setLevel(os.environ.get("NYPL_LOG_LEVEL", "INFO").upper())
    handlers: list[logging.Handler] = [console]

    if log_to_file:
        log_dir = Path(os.environ.get("NYPL_LOG_DIR", "logs"))
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            file_handler = RotatingFileHandler(
                log_dir / LOG_FILE_NAME, maxBytes=5_000_000, backupCount=3, encoding="utf-8"
            )
            file_handler.setLevel(logging.DEBUG)
            handlers.append(file_handler)
        except OSError as e:
            # e.g. an MCP client launching the server with an unwritable working directory: console logging still works.
            print(f"nypl_api_bridge: file logging disabled ({e})", file=sys.stderr)

    for handler in handlers:
        handler.setFormatter(formatter)
        # Filters must sit on handlers: a logger's own filters are skipped for records from child loggers.
        handler.addFilter(_TurnIdFilter())
        handler._nypl_handler = True  # type: ignore[attr-defined]
        logger.addHandler(handler)


def preview(value: Any, limit: int = 300) -> str:
    """Compact one-line rendering of `value`, truncated to `limit` characters."""
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return f"{text[:limit]}… (+{len(text) - limit} chars)"
