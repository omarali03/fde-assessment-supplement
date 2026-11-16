"""One adapter per source file. Each maps that file's field names into the shared format.

Adapters turn structured fields into Facts directly and wrap free text as SourceDocs;
free text is read later by an Extractor (src/extract.py), never by an adapter.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from src.model import Candidate, Job


@dataclass
class Bundle:
    candidates: dict[str, Candidate] = field(default_factory=dict)
    jobs: dict[str, Job] = field(default_factory=dict)
    discovery_notes: list[dict] = field(default_factory=list)

    def candidate(self, cid: str) -> Candidate:
        return self.candidates.setdefault(cid, Candidate(cid))

    def job(self, jid: str) -> Job:
        return self.jobs.setdefault(jid, Job(jid))
