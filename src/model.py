"""Shared format.

Every value is a Fact that remembers where it came from. Candidates and Jobs keep
every Fact they are given (nothing is overwritten), so conflicting facts sit side
by side and the matcher decides what to do with them.

Evidence lineage: `rendition_of` links a document to the original it re-renders
(expanded résumé -> résumé extract; ATS job -> VMS requisition), and
`related_source_ids` links a note to the sources it repeats. Facts with the same
value from one lineage are the same evidence and count once (see evidence_groups).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from src.vocab import STATE_NAMES

REFERENCE_DATE = "2026-11-07"
SNAPSHOT_AT = "2026-11-07T18:00:00Z"

# Skill evidence: "demonstrated" = described work (résumé duties, messages, notes);
# "stated" = listed only (e.g. an ATS skills tag) – never enough to meet a requirement;
# "not_demonstrated" = raised but not shown; "confirmed_absent" = candidate says they lack it.
# "stated" is also used for everything that isn't a skill (preferences, dates, pay, licenses).
EVIDENCE_STATUSES = ("demonstrated", "not_demonstrated", "confirmed_absent", "stated")
SKILL_STATUS_LABELS = {"demonstrated": "demonstrated (described work)", "stated": "stated (listed only)",
                       "not_demonstrated": "not demonstrated", "confirmed_absent": "confirmed absent"}

PROPOSED = "proposed – pending facility confirmation"

# Fields that naturally hold several values at once (a list, not competing claims).
MULTI_VALUED = {"certification", "license", "available_date", "unavailable_date", "shift_dates",
                "setting", "title", "email"}

SYSTEM_LABELS = {
    "ats": "ATS",
    "vms": "VMS",
    "client_db": "Client DB",
    "our_system": "Our system",
    "supplemental": "Supplemental",
    "resume_txt": "Résumé file",
}


@dataclass(frozen=True)
class Fact:
    value: Any
    field: str
    source_system: str
    source_id: str
    as_of: str                      # ISO date or datetime, as given by the source
    quote: str                      # the source text or field this fact came from
    evidence_status: str = "stated"
    extractor: str = "structured"   # "structured" (adapter field mapping) or an extractor name
    rendition_of: str | None = None
    related_source_ids: tuple[str, ...] = ()
    qualifier: str | None = None    # e.g. PROPOSED for account-manager requirement changes

    @property
    def lineage(self) -> frozenset[str]:
        ids = {self.source_id, *self.related_source_ids}
        if self.rendition_of:
            ids.add(self.rendition_of)
        return frozenset(ids)

    @property
    def value_key(self) -> str:
        """Facts with equal value_key say the same thing."""
        return json.dumps(self.value, sort_keys=True, default=str) + "|" + self.evidence_status

    @property
    def source_label(self) -> str:
        if self.extractor == "structured":
            return SYSTEM_LABELS.get(self.source_system, self.source_system)
        return self.source_id

    def text(self) -> str:
        v = self.value
        if self.field == "location_pref":
            place = STATE_NAMES.get(v["place"], v["place"])
            return {"only": f"{place} only", "prefers": f"prefers {place}",
                    "accept": f"open to {place}", "reject": f"rejects {place}"}[v["stance"]]
        if self.field.startswith("skill."):
            return f"{self.field[6:]}: {SKILL_STATUS_LABELS.get(self.evidence_status, self.evidence_status)}"
        if self.field == "pay_min" or self.field == "pay":
            return f"{self.field} ${v['amount']:,}/{v['unit']}"
        if self.field == "years_experience":
            return f"{v['years']} yrs {v['area'] or 'unspecified'} ({v['basis']})"
        if self.field == "min_experience":
            return f"{v['years']} yrs {v['area'] or 'relevant'} experience {v['level']}"
        if self.field.startswith("req."):
            return f"{self.field[4:]} {v}"
        return f"{self.field} = {v}"

    def __str__(self) -> str:
        s = f"{self.text()} ({self.source_label} {self.as_of[:10]})"
        return s + (f" [{self.qualifier}]" if self.qualifier else "")


@dataclass(frozen=True)
class SourceDoc:
    """A piece of free text (résumé, message, note) waiting for extraction."""
    source_id: str
    source_system: str
    subject_type: str               # "candidate" or "job"
    subject_id: str                 # canonical id
    kind: str                       # resume, profile, candidate_message, recruiter_note, operations, job_description, job_note
    as_of: str
    text: str
    rendition_of: str | None = None
    related_source_ids: tuple[str, ...] = ()
    author_role: str | None = None
    qualifier: str | None = None


@dataclass
class Entity:
    id: str
    facts: dict[str, list[Fact]] = field(default_factory=dict)
    docs: list[SourceDoc] = field(default_factory=list)
    aliases: set[str] = field(default_factory=set)

    def add(self, fact: Fact) -> None:
        self.facts.setdefault(fact.field, []).append(fact)

    def merge(self, other: "Entity") -> None:
        for facts in other.facts.values():
            for f in facts:
                self.add(f)
        self.docs.extend(other.docs)
        self.aliases |= other.aliases

    def get(self, name: str) -> list[Fact]:
        """All facts for a field, oldest first."""
        return sorted(self.facts.get(name, []), key=lambda f: (f.as_of, f.source_id))

    def latest(self, name: str) -> Fact | None:
        facts = self.get(name)
        return facts[-1] if facts else None

    def evidence_groups(self, name: str) -> list[list[Fact]]:
        """Group facts that are the same evidence. Each group counts as ONE piece of evidence.

        - A rendition belongs to its original: root = rendition_of or source_id.
        - A fact from a source that repeats others (related_source_ids, e.g. a recruiter note)
          joins the first group with the same value whose source it cites. It never bridges two
          independent groups, so a note citing both a profile and an update keeps them separate.
        """
        groups: dict[tuple[str, str], list[Fact]] = {}
        repeats = []
        for f in self.get(name):
            if f.related_source_ids and not f.rendition_of:
                repeats.append(f)
            else:
                groups.setdefault((f.value_key, f.rendition_of or f.source_id), []).append(f)
        for f in repeats:
            target = next((key for key, g in groups.items() if key[0] == f.value_key and
                           any(x.source_id in f.related_source_ids or key[1] in f.related_source_ids
                               for x in g)), None)
            groups.setdefault(target or (f.value_key, f.source_id), []).append(f)
        return sorted(groups.values(), key=lambda g: (g[0].as_of, g[0].source_id))

    def independent_count(self, name: str, value_key: str) -> int:
        return sum(1 for g in self.evidence_groups(name) if g[0].value_key == value_key)

    def conflicts(self) -> dict[str, list[list[Fact]]]:
        """Fields whose evidence disagrees (more than one distinct value)."""
        out = {}
        for name in sorted(set(self.facts) - MULTI_VALUED):
            groups = self.evidence_groups(name)
            if len({g[0].value_key for g in groups}) > 1:
                out[name] = groups
        return out


class Candidate(Entity):
    kind = "candidate"


class Job(Entity):
    kind = "job"


@dataclass(frozen=True)
class Event:
    """A change that arrives after the snapshot. `entity` holds the new facts/docs to merge."""
    event_id: str
    occurred_at: str
    kind: str
    subject_type: str
    subject_id: str
    entity: Entity


class IdMap:
    """Maps (source system, source id) to one canonical id.

    ATS C1 = client DB person 501 = EV-C1-NEW subject; VMS-901 = ATS J1.
    """

    def __init__(self) -> None:
        self._map: dict[tuple[str, str], str] = {}

    def add(self, system: str, external_id: str, canonical: str) -> None:
        self._map[(system, str(external_id))] = canonical

    def resolve(self, system: str, external_id: str) -> str | None:
        return self._map.get((system, str(external_id)))

    def aliases(self, canonical: str) -> list[str]:
        return sorted(f"{s}:{e}" for (s, e), c in self._map.items() if c == canonical)
