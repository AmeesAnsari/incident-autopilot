# incident-autopilot

Monitoring alerts in, **grouped incidents that resolve themselves** out.

A NOC typically gets one ticket per alarm: 40 tickets for one network outage, duplicates for every repeat alert, and engineers closing them by hand once things recover. This service sits between monitoring (PRTG or anything that can POST a webhook) and the ITSM (ServiceNow, or a built-in mock) and manages the whole incident lifecycle.

It is a clean-room version of a pattern I build at work. No client code or data is included.

## What it does

| Situation | Action |
|---|---|
| First device down for an account | Open **one** incident |
| More devices down for the same account | Add a work note to that incident, no new ticket |
| The same device alerts again | Suppress it and count it as a duplicate |
| 3+ devices down (10+ for P2) | Raise priority automatically, never lower it |
| A device recovers | Work note listing what's still down |
| The last device recovers | **Resolve** with a summary: outage length, devices, duplicates suppressed |
| Down again within 30 min of resolving | **Reopen** the same incident (flapping) instead of opening a new one |
| Recovery with no open incident | Ignore |

Incidents are grouped per **account + category**, so a power alarm and a connectivity alarm for the same customer stay separate.

## See it run

```bash
python -m incident_autopilot.simulate
```

13 alerts become **2 tickets**:

```
time   alert                                decision
08:00  AC-10293 gw-dubai-07 down            created    INC0010001 opened for gw-dubai-07
08:01  AC-10293 gw-dubai-07 down            duplicate  gw-dubai-07 already down; alert suppressed
08:02  AC-10293 gw-dubai-08 down            noted      gw-dubai-08 added (2 down)
08:02  AC-55120 meter-hub-3 down            created    INC0010002 opened for meter-hub-3
08:03  AC-10293 gw-dubai-09 down            noted      gw-dubai-09 added (3 down)
08:03  AC-10293 gw-dubai-09 down            escalated  priority -> P3 (3 devices down)
08:04  AC-10293 gw-dubai-07 down            duplicate  gw-dubai-07 already down; alert suppressed
08:09  AC-10293 gw-dubai-08 up              noted      gw-dubai-08 recovered (2 still down)
08:11  AC-10293 gw-dubai-07 up              noted      gw-dubai-07 recovered (1 still down)
08:12  AC-10293 gw-dubai-09 up              resolved   All devices recovered after 12m. Affected: gw-dubai-07, gw-dubai-08, gw-dubai-09. Duplicate alerts suppressed: 2.
08:14  AC-77001 sensor-air-12 up            ignored    sensor-air-12 recovered but no open incident tracks it
08:20  AC-10293 gw-dubai-07 down            reopened   INC0010001 reopened, gw-dubai-07 down 8m after resolve
08:26  AC-10293 gw-dubai-07 up              resolved   All devices recovered after 6m. Reopened 1 time; 26m since the first alert. ...
08:30  AC-55120 meter-hub-3 up              resolved   All devices recovered after 28m. Affected: meter-hub-3. ...
```

## Run the API

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
uvicorn incident_autopilot.app:create_app --factory --reload
```

Open http://localhost:8000/docs for the interactive API.

```bash
curl -X POST localhost:8000/alerts/prtg -H 'Content-Type: application/json' -d '{
  "device": "gw-1", "sensor": "Ping", "status": "Down", "message": "timeout",
  "datetime": "2026-11-14T08:00:00+00:00", "account": "AC-1"}'
```

| Endpoint | Purpose |
|---|---|
| `POST /alerts` | Generic, already-normalised alert |
| `POST /alerts/prtg` | PRTG "Execute HTTP Action" webhook ([template](incident_autopilot/adapters.py)) |
| `GET /incidents?status=open` | Current incidents |
| `GET /actions` | Audit trail: every decision, newest first |
| `GET /health` | Liveness, ITSM in use, open incident count |

Or with Docker: `docker build -t incident-autopilot . && docker run -p 8000:8000 incident-autopilot`.

## Connect ServiceNow

By default it uses an in-memory mock ITSM. Set these to use the ServiceNow Table API instead:

| Variable | Example |
|---|---|
| `SN_INSTANCE` | `https://yourcompany.service-now.com` |
| `SN_USER` / `SN_PASSWORD` | an integration user with the `itil` role |
| `SN_ASSIGNMENT_GROUP` | optional sys_id or name of the assignment group |
| `AUTOPILOT_DB` | SQLite path for state (default `autopilot.db`) |

The client creates incidents, adds work notes, sets impact and urgency, reopens (state 2) and resolves (state 6). Its requests are tested against a mock transport, not a live instance, so check field names and state values against your instance's configuration first.

## Design notes

- **Pure engine.** All lifecycle rules live in [`engine.py`](incident_autopilot/engine.py) with no HTTP code, so they're unit-tested directly.
- **State survives restarts.** Incidents are stored in SQLite, and a lock around each alert stops two concurrent webhooks racing on the same incident.
- **Audit trail.** Every decision is recorded with the reason (`GET /actions`), so "why didn't this open a ticket?" has an answer.
- **Vendor adapters at the edge.** Adding another monitoring tool means one function that returns an `Alert`.

## Tests

```bash
pytest -q
```

16 tests cover grouping, de-duplication, escalation, resolution, the flapping reopen and window, restart persistence, the HTTP API and the ServiceNow request shapes.

## License

MIT
