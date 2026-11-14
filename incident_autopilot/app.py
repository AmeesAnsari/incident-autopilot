"""HTTP API. Run with ``uvicorn incident_autopilot.app:create_app --factory``."""

from __future__ import annotations

import os
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Query

from .adapters import UnsupportedStatus, from_prtg
from .engine import Engine
from .itsm import ITSMClient, MockITSM, ServiceNowClient
from .models import Action, Alert, Incident
from .store import Store


def build_itsm() -> ITSMClient:
    """ServiceNow when SN_INSTANCE is set, otherwise the in-memory mock."""
    instance = os.getenv("SN_INSTANCE")
    if not instance:
        return MockITSM()
    return ServiceNowClient(
        instance, os.environ["SN_USER"], os.environ["SN_PASSWORD"], os.getenv("SN_ASSIGNMENT_GROUP", "")
    )


def create_app(store: Optional[Store] = None, itsm: Optional[ITSMClient] = None) -> FastAPI:
    store = store or Store(os.getenv("AUTOPILOT_DB", "autopilot.db"))
    itsm = itsm or build_itsm()
    engine = Engine(store, itsm)

    app = FastAPI(title="incident-autopilot", version="0.1.0",
                  description="Monitoring alerts in, grouped self-resolving incidents out.")
    app.state.engine, app.state.itsm = engine, itsm

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {"ok": True, "itsm": type(itsm).__name__, "open_incidents": len(store.all("open"))}

    @app.post("/alerts", response_model=list[Action])
    def receive_alert(alert: Alert) -> list[Action]:
        """Generic, already-normalised alert."""
        return engine.handle(alert)

    @app.post("/alerts/prtg", response_model=list[Action])
    def receive_prtg(payload: dict[str, Any], category: str = "connectivity") -> list[Action]:
        try:
            alert = from_prtg(payload, category)
        except UnsupportedStatus as exc:
            return [Action(kind="ignored", detail=str(exc))]
        except KeyError as exc:
            raise HTTPException(422, f"PRTG payload is missing {exc}") from exc
        return engine.handle(alert)

    @app.get("/incidents", response_model=list[Incident])
    def list_incidents(status: Optional[str] = Query(None, pattern="^(open|resolved)$")) -> list[Incident]:
        return store.all(status)

    @app.get("/incidents/{incident_id}", response_model=Incident)
    def get_incident(incident_id: int) -> Incident:
        incident = store.get(incident_id)
        if not incident:
            raise HTTPException(404, "incident not found")
        return incident

    @app.get("/actions", response_model=list[Action])
    def recent_actions(limit: int = Query(50, ge=1, le=500)) -> list[Action]:
        """Audit trail: what the engine decided, newest first."""
        return store.recent_actions(limit)

    return app
