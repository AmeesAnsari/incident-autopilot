"""ITSM clients: an in-memory mock for demos and tests, and a ServiceNow Table API client."""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Protocol

import httpx2 as httpx


class ITSMClient(Protocol):
    def create(self, short_description: str, description: str, priority: str) -> str: ...
    def add_note(self, ticket: str, note: str) -> None: ...
    def set_priority(self, ticket: str, priority: str) -> None: ...
    def reopen(self, ticket: str, note: str) -> None: ...
    def resolve(self, ticket: str, close_notes: str) -> None: ...


@dataclass
class MockITSM:
    """Records every call so tests and the simulator can show exactly what would be sent."""

    calls: list[tuple[str, str, str]] = field(default_factory=list)
    _numbers: itertools.count = field(default_factory=lambda: itertools.count(10001))

    def create(self, short_description: str, description: str, priority: str) -> str:
        ticket = f"INC{next(self._numbers):07d}"
        self.calls.append(("create", ticket, f"[{priority}] {short_description}"))
        return ticket

    def add_note(self, ticket: str, note: str) -> None:
        self.calls.append(("note", ticket, note))

    def set_priority(self, ticket: str, priority: str) -> None:
        self.calls.append(("priority", ticket, priority))

    def reopen(self, ticket: str, note: str) -> None:
        self.calls.append(("reopen", ticket, note))

    def resolve(self, ticket: str, close_notes: str) -> None:
        self.calls.append(("resolve", ticket, close_notes))


# ServiceNow incident.state values (out-of-the-box): 1 New, 2 In Progress, 6 Resolved.
SN_PRIORITY = {"P1": "1", "P2": "2", "P3": "3", "P4": "4"}


class ServiceNowClient:
    """Minimal ServiceNow Table API client for the incident table.

    Uses basic auth for simplicity; production setups usually prefer OAuth.
    The ``ticket`` returned is the sys_id, which every later call needs.
    """

    def __init__(self, instance_url: str, user: str, password: str, assignment_group: str = "",
                 transport: httpx.BaseTransport | None = None):
        self.http = httpx.Client(
            base_url=f"{instance_url.rstrip('/')}/api/now/table",
            auth=(user, password),
            headers={"Accept": "application/json"},
            timeout=15.0,
            transport=transport,
        )
        self.assignment_group = assignment_group

    def _patch(self, sys_id: str, body: dict) -> None:
        self.http.patch(f"/incident/{sys_id}", json=body).raise_for_status()

    def create(self, short_description: str, description: str, priority: str) -> str:
        body = {
            "short_description": short_description,
            "description": description,
            # Priority is derived from impact x urgency in ServiceNow; setting both keeps it predictable.
            "impact": SN_PRIORITY.get(priority, "3"),
            "urgency": SN_PRIORITY.get(priority, "3"),
        }
        if self.assignment_group:
            body["assignment_group"] = self.assignment_group
        response = self.http.post("/incident", json=body)
        response.raise_for_status()
        return response.json()["result"]["sys_id"]

    def add_note(self, ticket: str, note: str) -> None:
        self._patch(ticket, {"work_notes": note})

    def set_priority(self, ticket: str, priority: str) -> None:
        level = SN_PRIORITY.get(priority, "3")
        self._patch(ticket, {"impact": level, "urgency": level})

    def reopen(self, ticket: str, note: str) -> None:
        self._patch(ticket, {"state": "2", "work_notes": note})

    def resolve(self, ticket: str, close_notes: str) -> None:
        self._patch(ticket, {"state": "6", "close_code": "Solved (Permanently)", "close_notes": close_notes})
