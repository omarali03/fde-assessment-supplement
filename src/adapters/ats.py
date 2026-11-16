"""Adapter for ats_response.json (candidates C1–C4, jobs J1–J2)."""
from __future__ import annotations

from src.adapters import Bundle
from src.model import Fact, IdMap, SourceDoc
from src.vocab import normalize_profession, normalize_specialty, requirement_names_in, skill_names_in

SYSTEM = "ats"


def build_ids(raw: dict, idmap: IdMap) -> None:
    for c in raw["data"]["candidates"]:
        idmap.add(SYSTEM, c["id"], c["id"])
    for j in raw["data"]["jobs"]:
        idmap.add(SYSTEM, j["id"], j["id"])
        idmap.add("vms", j["external_requisition"], j["id"])


def load(raw: dict, idmap: IdMap) -> Bundle:
    out = Bundle()
    for c in raw["data"]["candidates"]:
        _candidate(c, out)
    for j in raw["data"]["jobs"]:
        _job(j, out)
    return out


def _candidate(c: dict, out: Bundle) -> None:
    cid = c["id"]
    cand = out.candidate(cid)
    cand.aliases.add(f"{SYSTEM}:{cid}")

    def add(field, value, quote, status="stated"):
        cand.add(Fact(value, field, SYSTEM, cid, c["updated_at"], quote, status))

    add("name", f"{c['first_name']} {c['last_name']}", "first_name/last_name")
    add("email", c["email"], f"email={c['email']}")
    add("profession", c["profession"], f"profession={c['profession']!r}")
    if c.get("specialty"):
        add("specialty", c["specialty"], f"specialty={c['specialty']!r}")
    add("home_location", dict(c["address"]), f"address={c['address']}")

    prefs = c.get("preferences", {})
    for state in prefs.get("states", []):
        stance = "only" if prefs.get("travel") is False else "prefers"
        add("location_pref", {"stance": stance, "place": state},
            f"preferences.states={prefs['states']}, travel={prefs.get('travel')}")
    for shift in prefs.get("shifts", []):
        add("shift_pref", shift, f"preferences.shifts={prefs['shifts']}")
    if "hours_per_week" in prefs:
        add("hours_per_week", prefs["hours_per_week"], f"preferences.hours_per_week={prefs['hours_per_week']}")
    if "duration_weeks" in prefs:
        add("duration_weeks", prefs["duration_weeks"], f"preferences.duration_weeks={prefs['duration_weeks']}")

    for skill in c.get("skills", []):
        for name in skill_names_in(skill):
            # A skills-list tag is listed, not described work (DISC-01).
            add(f"skill.{name}", name, f"skills: {skill}", "stated")

    if c.get("available_from"):
        add("start_date", c["available_from"], f"available_from={c['available_from']}")
    if c.get("expected_pay"):
        p = c["expected_pay"]
        add("pay_min", {"amount": p["amount"], "unit": p["period"]}, f"expected_pay={p}")
    add("status", c["status"], f"status={c['status']}")
    if c.get("assignment_end"):
        add("assignment_end", c["assignment_end"], f"assignment_end={c['assignment_end']}")

    # Free text -> SourceDocs. `source_text` is skipped: it restates the structured fields above.
    for d in c.get("documents", []):
        cand.docs.append(SourceDoc(d["id"], SYSTEM, "candidate", cid, "resume", d["received_at"], d["text"]))
    ops = c.get("operations")
    if ops:
        cand.docs.append(SourceDoc(ops["source_id"], SYSTEM, "candidate", cid, "operations",
                                   ops["recorded_at"], ops["text"]))


def _job(j: dict, out: Bundle) -> None:
    jid, req = j["id"], j["external_requisition"]
    job = out.job(jid)
    job.aliases |= {f"{SYSTEM}:{jid}", f"vms:{req}"}
    def add(field, value, quote):  # the ATS job mirrors the VMS requisition -> rendition_of
        job.add(Fact(value, field, SYSTEM, jid, j["updated_at"], quote, rendition_of=req))

    add("title", j["title"], f"title={j['title']!r}")
    if normalize_profession(j["title"]):
        add("profession", normalize_profession(j["title"]), f"title={j['title']!r}")
    if normalize_specialty(j["title"]):
        add("specialty", normalize_specialty(j["title"]), f"title={j['title']!r}")
    add("status", j["status"].lower(), f"status={j['status']}")
    add("location", dict(j["location"]), f"location={j['location']}")
    for key, field in [("start_date", "start_date"), ("duration_weeks", "duration_weeks"),
                       ("shift", "shift"), ("hours_per_week", "hours_per_week")]:
        if j.get(key) is not None:
            add(field, j[key], f"{key}={j[key]}")
    if j.get("minimum_experience_years") is not None:
        add("min_experience", {"years": j["minimum_experience_years"], "area": None, "level": "required"},
            f"minimum_experience_years={j['minimum_experience_years']}")
    for r in j.get("requirements", []):
        for name in requirement_names_in(r):
            add(f"req.{name}", "required", f"requirements: {r}")
    if j.get("candidate_pay"):
        p = j["candidate_pay"]
        unit = {"weekly": "week", "hourly": "hour"}.get(p["basis"], p["basis"])
        add("pay", {"amount": p["amount"], "unit": unit}, f"candidate_pay={p}")

    job.docs.append(SourceDoc(f"{jid}-DESC", SYSTEM, "job", jid, "job_description", j["updated_at"],
                              j["description"], rendition_of=req))
