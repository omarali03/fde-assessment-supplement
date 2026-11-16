"""Load the 18:00 snapshot: run every adapter, merge by canonical id, then extract from text."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from src.adapters import Bundle, ats, client_db, our_system, resume_txt, supplemental, vms
from src.extract import Extractor, RuleExtractor
from src.model import Candidate, Entity, Event, IdMap, Job

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


@dataclass
class World:
    candidates: dict[str, Candidate]
    jobs: dict[str, Job]
    idmap: IdMap
    discovery_notes: list[dict]
    pending_events: list[Event] = field(default_factory=list)   # replayed in step 5


def read(data_dir: Path, name: str) -> dict:
    return json.loads((Path(data_dir) / name).read_text())


def extract_into(entity: Entity, extractor: Extractor, docs=None) -> None:
    for doc in docs if docs is not None else entity.docs:
        for f in extractor.extract(doc):
            entity.add(f)


def load_snapshot(data_dir: Path = DATA_DIR, extractor: Extractor | None = None) -> World:
    extractor = extractor or RuleExtractor()
    raw = {name: read(data_dir, f"{name}.json") for name in
           ["ats_response", "vms_response", "client_database_dump", "our_system_response",
            "supplemental_source_packet"]}

    idmap = IdMap()
    ats.build_ids(raw["ats_response"], idmap)
    client_db.build_ids(raw["client_database_dump"], idmap)

    bundles = [
        ats.load(raw["ats_response"], idmap),
        vms.load(raw["vms_response"], idmap),
        client_db.load(raw["client_database_dump"], idmap),
        our_system.load(raw["our_system_response"], idmap),
        supplemental.load(raw["supplemental_source_packet"], idmap),
        resume_txt.load(data_dir, idmap),
    ]
    merged = Bundle()
    for b in bundles:
        for cid, c in b.candidates.items():
            merged.candidate(cid).merge(c)
        for jid, j in b.jobs.items():
            merged.job(jid).merge(j)
        merged.discovery_notes += b.discovery_notes

    for entity in [*merged.candidates.values(), *merged.jobs.values()]:
        extract_into(entity, extractor)

    events = (vms.load_events(raw["vms_response"], idmap)
              + our_system.load_events(raw["our_system_response"], idmap))
    events.sort(key=lambda e: e.occurred_at)
    return World(dict(sorted(merged.candidates.items())), dict(sorted(merged.jobs.items())),
                 idmap, merged.discovery_notes, events)
