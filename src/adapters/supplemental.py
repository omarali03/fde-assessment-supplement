"""Adapter for supplemental_source_packet.json (expanded résumés, notes, discovery notes).

Expanded résumés are renditions of the ATS résumé extracts (`rendition_of`), and notes
that repeat a message carry `related_source_ids`, so they are not counted as new evidence.
"""
from __future__ import annotations

from src.adapters import Bundle
from src.model import PROPOSED, IdMap, SourceDoc

SYSTEM = "supplemental"


def load(raw: dict, idmap: IdMap) -> Bundle:
    out = Bundle()

    for r in raw["resume_documents"]:
        cid = idmap.resolve("ats", r["candidate_id"])
        out.candidate(cid).docs.append(
            SourceDoc(r["document_id"], SYSTEM, "candidate", cid, "resume", r["received_at"], r["text"],
                      rendition_of=r.get("rendition_of")))

    for n in raw["notes"]:
        related = tuple(n.get("related_source_ids", []))
        if "ats_job_id" in n:
            jid = idmap.resolve("ats", n["ats_job_id"])
            qualifier = PROPOSED if n.get("author_role") == "account_manager" else None
            out.job(jid).docs.append(
                SourceDoc(n["source_id"], SYSTEM, "job", jid, n["kind"], n["recorded_at"], n["body"],
                          related_source_ids=related, author_role=n.get("author_role"), qualifier=qualifier))
        else:
            cid = (idmap.resolve("ats", n["candidate_id"]) if "candidate_id" in n
                   else idmap.resolve("our_system", n["profile_id"]))
            out.candidate(cid).docs.append(
                SourceDoc(n["source_id"], SYSTEM, "candidate", cid, n["kind"], n["recorded_at"], n["body"],
                          related_source_ids=related, author_role=n.get("author_role")))

    out.discovery_notes = list(raw.get("discovery_notes", []))
    return out
