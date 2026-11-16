"""Adapter for client_database_dump.json (people 501–504, journal entries, job notes)."""
from __future__ import annotations

from src.adapters import Bundle
from src.model import PROPOSED, Fact, IdMap, SourceDoc
from src.vocab import STATE_CODES

SYSTEM = "client_db"


def build_ids(raw: dict, idmap: IdMap) -> None:
    for p in raw["tables"]["people"]:
        idmap.add(SYSTEM, p["person_pk"], p["ats_candidate_id"])  # person 501 = ATS C1


def load(raw: dict, idmap: IdMap) -> Bundle:
    out = Bundle()
    tables = raw["tables"]

    for p in tables["people"]:
        cid = idmap.resolve(SYSTEM, p["person_pk"])
        cand = out.candidate(cid)
        cand.aliases.add(f"{SYSTEM}:{p['person_pk']}")
        src = f"person-{p['person_pk']}"

        def add(field, value, quote):
            cand.add(Fact(value, field, SYSTEM, src, p["last_updated"], quote))

        add("email", p["email_address"], f"email_address={p['email_address']}")
        if p.get("owner"):
            add("owner", p["owner"], f"owner={p['owner']}")
        if p.get("preferred_region_text"):
            text = p["preferred_region_text"]
            add("location_pref", {"stance": "prefers", "place": STATE_CODES.get(text, text)},
                f"preferred_region_text={text!r}")

    for e in tables["journal_entries"]:
        cid = idmap.resolve(SYSTEM, e["person_fk"])
        out.candidate(cid).docs.append(
            SourceDoc(e["entry_pk"], SYSTEM, "candidate", cid, e["entry_type"], e["created_on"], e["body"]))

    for n in tables["job_notes"]:
        jid = idmap.resolve("ats", n["ats_job_id"])
        qualifier = PROPOSED if n.get("author_role") == "account_manager" else None
        out.job(jid).docs.append(
            SourceDoc(n["note_pk"], SYSTEM, "job", jid, "job_note", n["created_on"], n["body"],
                      author_role=n.get("author_role"), qualifier=qualifier))
    return out
