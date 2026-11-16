"""Adapter for vms_response.json (requisitions VMS-901..903, change feed EV-JOB-904)."""
from __future__ import annotations

from datetime import datetime

from src.adapters import Bundle
from src.model import Event, Fact, IdMap, Job, SourceDoc
from src.vocab import STATE_CODES, normalize_profession, normalize_specialty

SYSTEM = "vms"


def load(raw: dict, idmap: IdMap) -> Bundle:
    out = Bundle()
    for r in raw["requisitions"]:
        jid = _canonical(r["requisitionNumber"], idmap)
        out.job(jid).merge(_job_from_record(r, jid, r["requisitionNumber"], r["lastModified"]))
    return out


def load_events(raw: dict, idmap: IdMap) -> list[Event]:
    events = []
    for ev in raw.get("changeFeed", []):
        r = ev["record"]
        jid = _canonical(r["requisitionNumber"], idmap)
        job = _job_from_record(r, jid, ev["eventId"], ev["occurredAt"])
        events.append(Event(ev["eventId"], ev["occurredAt"], ev["eventType"], "job", jid, job))
    return events


def _canonical(req_number: str, idmap: IdMap) -> str:
    """VMS requisitions with an ATS job (901, 902) use the ATS id; others keep their VMS number."""
    jid = idmap.resolve(SYSTEM, req_number)
    if jid is None:
        jid = req_number
        idmap.add(SYSTEM, req_number, jid)
    return jid


def _job_from_record(r: dict, jid: str, source_id: str, as_of: str) -> Job:
    """The VMS record is the original requisition; the ATS job is a rendition of it."""
    job = Job(jid)
    job.aliases.add(f"{SYSTEM}:{r['requisitionNumber']}")

    def add(field, value, quote):
        job.add(Fact(value, field, SYSTEM, source_id, as_of, quote))

    title = r["positionName"]
    add("title", title, f"positionName={title!r}")
    if normalize_profession(title):
        add("profession", normalize_profession(title), f"positionName={title!r}")
    if normalize_specialty(title):
        add("specialty", normalize_specialty(title), f"positionName={title!r}")
    add("status", r["state"].lower(), f"state={r['state']}")
    fac = r["facility"]
    add("location", {"city": fac["city"], "state": STATE_CODES.get(fac["region"], fac["region"])},
        f"facility.city={fac['city']}, facility.region={fac['region']}")
    add("facility", fac["name"], f"facility.name={fac['name']!r}")
    if r.get("startDate"):
        iso = datetime.strptime(r["startDate"], "%m/%d/%Y").date().isoformat()
        add("start_date", iso, f"startDate={r['startDate']}")
    if r.get("contractWeeks"):
        add("duration_weeks", r["contractWeeks"], f"contractWeeks={r['contractWeeks']}")
    if r.get("weeklyHours"):
        add("hours_per_week", r["weeklyHours"], f"weeklyHours={r['weeklyHours']}")
    if r.get("shiftDescription"):
        add("shift", r["shiftDescription"].lower(), f"shiftDescription={r['shiftDescription']}")
    for s in r.get("shifts", []):
        add("shift_dates", {"date": s["start"][:10], "start": s["start"], "end": s["end"]},
            f"shifts: {s['start']} to {s['end']}")
    if r.get("candidateRate"):
        rate = r["candidateRate"]
        add("pay", {"amount": rate["value"], "unit": rate["unit"].lower()}, f"candidateRate={rate}")

    if r.get("details"):
        job.docs.append(SourceDoc(source_id, SYSTEM, "job", jid, "job_description", as_of, r["details"]))
    return job
