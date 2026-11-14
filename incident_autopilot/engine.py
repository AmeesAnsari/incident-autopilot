"""The incident lifecycle rules. Pure logic: no HTTP, easy to test.

Rules, per (account, category):

* First device down            -> create one incident.
* Another device down          -> add a work note to the same incident (no new ticket).
* Same device down again       -> duplicate: counted, nothing sent to the ITSM.
* Enough devices down          -> raise the priority (P4 -> P3 -> P2).
* A device recovers            -> work note.
* Last device recovers         -> resolve the incident with a summary.
* Down again soon after resolve-> reopen the same incident instead of opening a new one (flapping).
* Recovery with no incident    -> ignored.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from .itsm import ITSMClient
from .models import Action, Alert, AlertState, Incident, IncidentStatus
from .store import Store


@dataclass(frozen=True)
class Policy:
    reopen_window: timedelta = timedelta(minutes=30)
    # (devices down, priority), checked from the top
    priority_steps: tuple[tuple[int, str], ...] = ((10, "P2"), (3, "P3"), (1, "P4"))

    def priority_for(self, devices_down: int) -> str:
        for threshold, priority in self.priority_steps:
            if devices_down >= threshold:
                return priority
        return self.priority_steps[-1][1]


PRIORITY_RANK = {"P1": 1, "P2": 2, "P3": 3, "P4": 4}


def _fmt_duration(delta: timedelta) -> str:
    minutes = int(delta.total_seconds() // 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m" if hours else f"{minutes}m"


class Engine:
    def __init__(self, store: Store, itsm: ITSMClient, policy: Policy = Policy()):
        self.store, self.itsm, self.policy = store, itsm, policy

    def handle(self, alert: Alert) -> list[Action]:
        with self.store.lock:
            actions = self._down(alert) if alert.state == AlertState.DOWN else self._up(alert)
            self.store.log(actions)
            return actions

    # ------------------------------------------------------------------ down

    def _down(self, alert: Alert) -> list[Action]:
        incident = self.store.open_for(alert.account, alert.category)

        if incident and alert.device in incident.down_devices:
            incident.duplicate_alerts += 1
            self.store.save(incident)
            return [self._act("duplicate", f"{alert.device} already down; alert suppressed", incident)]

        if incident:
            incident.down_devices.append(alert.device)
            self._remember(incident, alert.device)
            self.itsm.add_note(incident.ticket, f"{alert.at:%H:%M} {alert.device} down: {alert.message}".strip())
            actions = [self._act("noted", f"{alert.device} added ({len(incident.down_devices)} down)", incident)]
            actions += self._maybe_escalate(incident)
            self.store.save(incident)
            return actions

        last = self.store.last_resolved_for(alert.account, alert.category)
        if last and last.resolved_at and alert.at - last.resolved_at <= self.policy.reopen_window:
            return self._reopen(last, alert)
        return self._create(alert)

    def _create(self, alert: Alert) -> list[Action]:
        priority = self.policy.priority_for(1)
        ticket = self.itsm.create(
            short_description=f"{alert.category.title()} alarm for {alert.account}",
            description=f"{alert.at:%Y-%m-%d %H:%M} {alert.device} down via {alert.source}: {alert.message}".strip(),
            priority=priority,
        )
        incident = Incident(
            id=self.store.next_id(), ticket=ticket, account=alert.account, category=alert.category,
            status=IncidentStatus.OPEN, priority=priority, opened_at=alert.at,
            down_devices=[alert.device], affected_devices=[alert.device],
        )
        self.store.save(incident)
        return [self._act("created", f"{ticket} opened for {alert.device}", incident)]

    def _reopen(self, incident: Incident, alert: Alert) -> list[Action]:
        gap = _fmt_duration(alert.at - incident.resolved_at)
        incident.status = IncidentStatus.OPEN
        incident.resolved_at = None
        incident.reopened_at = alert.at
        incident.reopen_count += 1
        incident.down_devices = [alert.device]
        self._remember(incident, alert.device)
        self.itsm.reopen(incident.ticket, f"Reopened: {alert.device} down again {gap} after resolution (flapping?)")
        self.store.save(incident)
        return [self._act("reopened", f"{incident.ticket} reopened, {alert.device} down {gap} after resolve", incident)]

    def _maybe_escalate(self, incident: Incident) -> list[Action]:
        wanted = self.policy.priority_for(len(incident.down_devices))
        if PRIORITY_RANK[wanted] >= PRIORITY_RANK[incident.priority]:
            return []  # never lower priority automatically
        incident.priority = wanted
        self.itsm.set_priority(incident.ticket, wanted)
        return [self._act("escalated", f"priority -> {wanted} ({len(incident.down_devices)} devices down)", incident)]

    # ------------------------------------------------------------------ up

    def _up(self, alert: Alert) -> list[Action]:
        incident = self.store.open_for(alert.account, alert.category)
        if not incident or alert.device not in incident.down_devices:
            return [Action(kind="ignored", detail=f"{alert.device} recovered but no open incident tracks it")]

        incident.down_devices.remove(alert.device)
        if incident.down_devices:
            self.itsm.add_note(incident.ticket, f"{alert.at:%H:%M} {alert.device} recovered; still down: "
                                                f"{', '.join(incident.down_devices)}")
            self.store.save(incident)
            return [self._act("noted", f"{alert.device} recovered ({len(incident.down_devices)} still down)", incident)]

        incident.status = IncidentStatus.RESOLVED
        incident.resolved_at = alert.at
        outage_start = incident.reopened_at or incident.opened_at
        summary = f"All devices recovered after {_fmt_duration(alert.at - outage_start)}."
        if incident.reopen_count:
            times = "time" if incident.reopen_count == 1 else "times"
            summary += (f" Reopened {incident.reopen_count} {times}; "
                        f"{_fmt_duration(alert.at - incident.opened_at)} since the first alert.")
        summary += (f" Affected: {', '.join(incident.affected_devices)}."
                    f" Duplicate alerts suppressed: {incident.duplicate_alerts}.")
        self.itsm.resolve(incident.ticket, summary)
        self.store.save(incident)
        return [self._act("resolved", summary, incident)]

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _remember(incident: Incident, device: str) -> None:
        if device not in incident.affected_devices:
            incident.affected_devices.append(device)

    @staticmethod
    def _act(kind: str, detail: str, incident: Incident) -> Action:
        return Action(kind=kind, detail=detail, incident_id=incident.id, ticket=incident.ticket)
