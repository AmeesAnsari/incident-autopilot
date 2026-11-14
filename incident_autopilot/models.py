"""Data shapes shared by the engine, the store and the API."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class AlertState(str, Enum):
    DOWN = "down"
    UP = "up"


class Alert(BaseModel):
    """One normalised monitoring event. Adapters turn vendor payloads into this."""

    source: str = Field(examples=["prtg"])
    account: str = Field(min_length=1, examples=["AC-10293"])
    device: str = Field(min_length=1, examples=["gw-dubai-07"])
    category: str = Field(default="connectivity", examples=["connectivity"])
    state: AlertState
    message: str = ""
    at: datetime


class IncidentStatus(str, Enum):
    OPEN = "open"
    RESOLVED = "resolved"


class Incident(BaseModel):
    id: int
    ticket: str  # ITSM reference, e.g. INC0010001
    account: str
    category: str
    status: IncidentStatus
    priority: str
    opened_at: datetime
    resolved_at: Optional[datetime] = None
    reopened_at: Optional[datetime] = None  # start of the current outage after a reopen
    down_devices: list[str] = []
    affected_devices: list[str] = []  # every device that was ever down in this incident
    duplicate_alerts: int = 0
    reopen_count: int = 0


class Action(BaseModel):
    """What the engine decided for one alert. Returned by the API and kept as an audit trail."""

    kind: str  # created | reopened | noted | escalated | resolved | duplicate | ignored
    detail: str
    incident_id: Optional[int] = None
    ticket: Optional[str] = None
