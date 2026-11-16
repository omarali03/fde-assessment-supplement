"""Adapter for our_system_response.json (profiles R01–R12, update EV-C1-NEW)."""
from __future__ import annotations

from src.adapters import Bundle
from src.model import Candidate, Event, Fact, IdMap, SourceDoc

SYSTEM = "our_system"

# How this file names other systems in `subject.external_source`.
EXTERNAL_SOURCES = {"fictional_ats": "ats", "fictional_vms": "vms",
                    "fictional_client_database": "client_db"}

DOC_KINDS = {"profile": "profile", "candidate_statement": "candidate_message"}


def load(raw: dict, idmap: IdMap) -> Bundle:
    out = Bundle()
    as_of = raw["exported_at"]
    for p in raw["profiles"]:
        pid = p["profile_id"]
        idmap.add(SYSTEM, pid, pid)
        cand = out.candidate(pid)
        cand.aliases.add(f"{SYSTEM}:{pid}")

        def add(field, value, quote):
            cand.add(Fact(value, field, SYSTEM, pid, as_of, quote))

        add("email", p["contact"]["email"], f"contact.email={p['contact']['email']}")
        add("profession", p["profession"], f"profession={p['profession']!r}")
        wf = p.get("workflow", {})
        if wf.get("owner"):
            add("owner", wf["owner"], f"workflow.owner={wf['owner']}")
        if wf.get("placement"):
            add("status", "placed", f"workflow.placement={wf['placement']}")
        if wf.get("contact_restriction"):
            cand.docs.append(SourceDoc(f"{pid}-WORKFLOW", SYSTEM, "candidate", pid, "operations",
                                       as_of, wf["contact_restriction"]))

        for ev in p.get("evidence", []):
            cand.docs.append(SourceDoc(ev["id"], SYSTEM, "candidate", pid, DOC_KINDS.get(ev["kind"], ev["kind"]),
                                       ev["observed_at"], ev["text"]))
    return out


def load_events(raw: dict, idmap: IdMap) -> list[Event]:
    events = []
    for u in raw.get("updates", []):
        subject = u["subject"]
        system = EXTERNAL_SOURCES.get(subject["external_source"], subject["external_source"])
        cid = idmap.resolve(system, subject["external_id"])  # EV-C1-NEW -> ATS C1
        if cid is None:
            raise ValueError(f"{u['event_id']}: unknown subject {subject}")
        cand = Candidate(cid)
        cand.docs.append(SourceDoc(u["event_id"], SYSTEM, "candidate", cid,
                                   DOC_KINDS.get(u["kind"], u["kind"]), u["occurred_at"], u["text"]))
        events.append(Event(u["event_id"], u["occurred_at"], "candidate.updated", "candidate", cid, cand))
    return events
