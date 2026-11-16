"""Suggested field updates for recruiter review.

When a newer candidate statement contradicts (or fills) an older structured field, we suggest an
update. Suggestions are shown to a recruiter and NEVER written back to any source system.
"""
from __future__ import annotations

from src.model import REFERENCE_DATE, SYSTEM_LABELS, Candidate

REVIEW_LABEL = "suggested – for recruiter review, not written back"


def _structured(c: Candidate, field: str):
    return [f for f in c.get(field) if f.extractor == "structured"]


def _from_text(c: Candidate, field: str):
    return [f for f in c.get(field) if f.extractor != "structured"]


def suggest_updates(c: Candidate) -> list[dict]:
    out = []

    def suggest(system, field, current, suggested, evidence, reason):
        out.append({"candidate": c.id, "system": SYSTEM_LABELS.get(system, system), "field": field,
                    "current": current, "suggested": suggested, "evidence": evidence,
                    "reason": reason, "status": REVIEW_LABEL})

    # Contact: a newer "do not contact until" vs. an older contact_allowed=true / no restriction.
    nc = c.latest("no_contact_until")
    if nc and nc.value > REFERENCE_DATE:
        allowed = [f for f in c.get("contact_allowed") if f.value is True and f.as_of < nc.as_of]
        if allowed:
            old = allowed[-1]
            suggest(old.source_system, "contact_allowed", "true", f"false (until {nc.value})", str(nc),
                    f"{old.source_id} ({old.as_of[:10]}) still says contact_allowed=true")
        elif not c.get("contact_allowed"):
            system = "our_system" if any(a.startswith("our_system:") for a in c.aliases) else "ats"
            suggest(system, "contact_restriction", "none recorded", f"no contact until {nc.value}", str(nc),
                    "candidate asked not to be contacted; no restriction is recorded")

    # Location: a newer text statement that contradicts an older structured field
    # (old field says "X only", or the candidate now rejects a place the field lists).
    text_prefs = _from_text(c, "location_pref")
    if text_prefs:
        new = text_prefs[-1]
        for old in _structured(c, "location_pref"):
            contradicts = ((old.value["stance"] == "only" and old.value["place"] != new.value["place"])
                           or (new.value["stance"] == "reject" and old.value["place"] == new.value["place"]))
            if old.as_of < new.as_of and contradicts:
                suggest(old.source_system, "location preference", old.text(), f"review: {new.text()}", str(new),
                        f"structured field dated {old.as_of[:10]} predates the candidate's statement")

    # Start date and pay: newest text statement vs. older or empty structured field (ATS records only).
    is_ats = any(a.startswith("ats:") for a in c.aliases)
    for field, label in [("start_date", "available_from"), ("pay_min", "expected_pay")]:
        texts = _from_text(c, field)
        if not texts:
            continue
        new = texts[-1]
        structured = _structured(c, field)
        if structured and structured[-1].value != new.value and structured[-1].as_of < new.as_of:
            suggest(structured[-1].source_system, label, structured[-1].text(), new.text(), str(new),
                    "newer candidate statement differs")
        elif not structured and is_ats:
            suggest("ats", label, "empty", new.text(), str(new), "structured field is empty")
    return out
