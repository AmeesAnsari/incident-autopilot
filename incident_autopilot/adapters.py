"""Turn vendor webhook payloads into :class:`Alert`.

The PRTG adapter expects a notification template that posts JSON with the
placeholders below. PRTG lets you choose the payload of an "Execute HTTP
Action" notification, so configure it to send, for example::

    {"device": "%device", "sensor": "%name", "status": "%status",
     "message": "%message", "datetime": "%datetime", "account": "%group"}

Adjust the field names here if your template differs.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from .models import Alert, AlertState

PRTG_DOWN = {"down", "down (partial)", "down (acknowledged)"}
PRTG_UP = {"up"}


class UnsupportedStatus(ValueError):
    pass


def from_prtg(payload: Mapping[str, Any], category: str = "connectivity") -> Alert:
    status = str(payload.get("status", "")).strip().lower()
    if status in PRTG_DOWN:
        state = AlertState.DOWN
    elif status in PRTG_UP:
        state = AlertState.UP
    else:
        # Warning / Unusual / Paused don't open or close incidents.
        raise UnsupportedStatus(f"PRTG status '{payload.get('status')}' is not actionable")

    # PRTG's %datetime follows the server's locale, so it often isn't ISO 8601.
    # If it can't be parsed, fall back to the time the webhook arrived.
    raw_time = payload.get("datetime")
    try:
        at = datetime.fromisoformat(str(raw_time)) if raw_time else datetime.now(timezone.utc)
    except ValueError:
        at = datetime.now(timezone.utc)
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)

    sensor = payload.get("sensor")
    message = str(payload.get("message", "")).strip()
    return Alert(
        source="prtg",
        account=str(payload["account"]),
        device=str(payload["device"]),
        category=category,
        state=state,
        message=f"{sensor}: {message}" if sensor else message,
        at=at,
    )
