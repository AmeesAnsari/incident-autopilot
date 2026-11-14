"""Replay a realistic alarm storm and print what the engine does at each step.

    python -m incident_autopilot.simulate
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .engine import Engine
from .itsm import MockITSM
from .models import Alert, AlertState
from .store import Store

T0 = datetime(2026, 11, 14, 8, 0, tzinfo=timezone.utc)

# (minute offset, account, device, state, message)
SCENARIO = [
    (0, "AC-10293", "gw-dubai-07", "down", "Ping timeout"),
    (1, "AC-10293", "gw-dubai-07", "down", "Ping timeout"),  # repeat: suppressed
    (2, "AC-10293", "gw-dubai-08", "down", "Ping timeout"),
    (2, "AC-55120", "meter-hub-3", "down", "No data for 10 min"),  # different account: separate incident
    (3, "AC-10293", "gw-dubai-09", "down", "Ping timeout"),  # third device: escalate to P3
    (4, "AC-10293", "gw-dubai-07", "down", "Ping timeout"),  # repeat: suppressed
    (9, "AC-10293", "gw-dubai-08", "up", "Ping OK"),
    (11, "AC-10293", "gw-dubai-07", "up", "Ping OK"),
    (12, "AC-10293", "gw-dubai-09", "up", "Ping OK"),  # last one: resolve
    (14, "AC-77001", "sensor-air-12", "up", "OK"),  # recovery without an incident: ignored
    (20, "AC-10293", "gw-dubai-07", "down", "Ping timeout"),  # 8 min after resolve: reopen
    (26, "AC-10293", "gw-dubai-07", "up", "Ping OK"),
    (30, "AC-55120", "meter-hub-3", "up", "Data flowing"),
]


def run() -> MockITSM:
    itsm = MockITSM()
    engine = Engine(Store(), itsm)
    print(f"{'time':<6} {'alert':<36} decision")
    print("-" * 100)
    for minute, account, device, state, message in SCENARIO:
        at = T0 + timedelta(minutes=minute)
        alert = Alert(source="sim", account=account, device=device, state=AlertState(state), message=message, at=at)
        for action in engine.handle(alert):
            label = f"{account} {device} {state}"
            print(f"{at:%H:%M}  {label:<36} {action.kind:<10} {action.detail}")

    print(f"\n{len(SCENARIO)} alerts -> {sum(1 for c in itsm.calls if c[0] == 'create')} tickets, "
          f"{len(itsm.calls)} ITSM calls:")
    for verb, ticket, text in itsm.calls:
        print(f"  {verb:<9} {ticket}  {text}")
    return itsm


if __name__ == "__main__":
    run()
