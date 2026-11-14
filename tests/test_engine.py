from datetime import datetime, timedelta, timezone

import pytest

from incident_autopilot.engine import Engine, Policy
from incident_autopilot.itsm import MockITSM
from incident_autopilot.models import Alert, AlertState
from incident_autopilot.store import Store

T0 = datetime(2026, 11, 14, 8, 0, tzinfo=timezone.utc)


@pytest.fixture
def setup():
    itsm = MockITSM()
    return Engine(Store(), itsm), itsm


def alert(device, state, minute=0, account="AC-1", category="connectivity"):
    return Alert(source="test", account=account, device=device, category=category,
                 state=AlertState(state), at=T0 + timedelta(minutes=minute))


def kinds(actions):
    return [a.kind for a in actions]


def test_first_down_creates_one_incident(setup):
    engine, itsm = setup
    assert kinds(engine.handle(alert("d1", "down"))) == ["created"]
    assert [c[0] for c in itsm.calls] == ["create"]
    assert itsm.calls[0][2].startswith("[P4]")


def test_second_device_groups_into_same_incident(setup):
    engine, itsm = setup
    engine.handle(alert("d1", "down"))
    assert kinds(engine.handle(alert("d2", "down", 1))) == ["noted"]
    assert [c[0] for c in itsm.calls] == ["create", "note"]
    assert len(engine.store.all()) == 1


def test_repeat_alert_is_suppressed_and_counted(setup):
    engine, itsm = setup
    engine.handle(alert("d1", "down"))
    assert kinds(engine.handle(alert("d1", "down", 1))) == ["duplicate"]
    assert len(itsm.calls) == 1
    assert engine.store.all()[0].duplicate_alerts == 1


def test_escalates_at_threshold_and_never_lowers(setup):
    engine, itsm = setup
    for n, dev in enumerate(["d1", "d2"]):
        engine.handle(alert(dev, "down", n))
    assert kinds(engine.handle(alert("d3", "down", 3))) == ["noted", "escalated"]
    assert ("priority", "INC0010001", "P3") in itsm.calls
    engine.handle(alert("d3", "up", 4))  # back to 2 down: priority stays P3
    assert engine.store.all()[0].priority == "P3"


def test_resolves_only_when_last_device_recovers(setup):
    engine, itsm = setup
    engine.handle(alert("d1", "down"))
    engine.handle(alert("d2", "down", 1))
    assert kinds(engine.handle(alert("d1", "up", 5))) == ["noted"]
    actions = engine.handle(alert("d2", "up", 7))
    assert kinds(actions) == ["resolved"]
    assert "7m" in actions[0].detail and "d1, d2" in actions[0].detail
    assert itsm.calls[-1][0] == "resolve"


def test_flapping_reopens_within_window(setup):
    engine, itsm = setup
    engine.handle(alert("d1", "down"))
    engine.handle(alert("d1", "up", 5))
    assert kinds(engine.handle(alert("d1", "down", 15))) == ["reopened"]
    assert len(engine.store.all()) == 1
    assert engine.store.all()[0].reopen_count == 1
    # The resolve note times the second outage, not the whole incident.
    detail = engine.handle(alert("d1", "up", 18))[0].detail
    assert detail.startswith("All devices recovered after 3m. Reopened 1 time; 18m since the first alert.")


def test_new_incident_after_window():
    itsm = MockITSM()
    engine = Engine(Store(), itsm, Policy(reopen_window=timedelta(minutes=10)))
    engine.handle(alert("d1", "down"))
    engine.handle(alert("d1", "up", 5))
    assert kinds(engine.handle(alert("d1", "down", 30))) == ["created"]
    assert len(engine.store.all()) == 2


def test_accounts_and_categories_are_separate(setup):
    engine, _ = setup
    engine.handle(alert("d1", "down", account="AC-1"))
    engine.handle(alert("d1", "down", account="AC-2"))
    engine.handle(alert("d1", "down", account="AC-1", category="power"))
    assert len(engine.store.all("open")) == 3


def test_recovery_without_incident_is_ignored(setup):
    engine, itsm = setup
    assert kinds(engine.handle(alert("d9", "up"))) == ["ignored"]
    assert itsm.calls == []


def test_state_survives_restart(tmp_path):
    db = str(tmp_path / "a.db")
    Engine(Store(db), MockITSM()).handle(alert("d1", "down"))
    engine = Engine(Store(db), MockITSM())
    assert kinds(engine.handle(alert("d1", "down", 1))) == ["duplicate"]
