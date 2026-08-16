# Moon Begin
"""Persistent, privacy-conscious diagnostic logging for local operations."""

from __future__ import annotations

import json
import logging
import re
from logging.handlers import RotatingFileHandler
from typing import Any

from .config import APP_DIR


LOG_DIR = APP_DIR / "logs"
LOG_PATH = LOG_DIR / "operations.log"
_LOGGER_NAME = "ytba.operations"
_SENSITIVE_KEY = re.compile(r"(?:api[_-]?key|authorization|cookie|sessdata|token|password|secret)", re.I)


def _safe_value(value: Any) -> Any:
    """Keep diagnostic context useful without retaining credentials or transcripts."""
    if isinstance(value, dict):
        return {str(key): "[redacted]" if _SENSITIVE_KEY.search(str(key)) else _safe_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_safe_value(item) for item in list(value)[:20]]
    text = str(value)
    return text[:2000] + "…" if len(text) > 2000 else text


def logger() -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    result = logging.getLogger(_LOGGER_NAME)
    if result.handlers:
        return result
    result.setLevel(logging.INFO)
    handler = RotatingFileHandler(LOG_PATH, maxBytes=2 * 1024 * 1024, backupCount=4, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    result.addHandler(handler)
    result.propagate = False
    return result


def log_event(event: str, **context: Any) -> None:
    """Append one structured event; logging must never break the user workflow."""
    try:
        payload = {"event": event, **{key: _safe_value(value) for key, value in context.items()}}
        logger().info(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    except Exception:
        pass


def log_exception(event: str, error: BaseException, **context: Any) -> None:
    try:
        payload = {"event": event, "error": _safe_value(error), **{key: _safe_value(value) for key, value in context.items()}}
        # Do not emit the raw traceback: third-party exception text can include request headers.
        logger().error(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    except Exception:
        pass
# Moon End
