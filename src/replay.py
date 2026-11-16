"""Replay the post-snapshot events and show what changed.

18:00  load the snapshot and match every open job
18:05  EV-JOB-904 creates a requisition  -> match only the new job against all candidates
18:10  EV-C1-NEW updates candidate C1     -> re-match only C1 against open jobs; show before/after

Events are merged the same way as snapshot data: facts are appended, nothing is overwritten.

Run: python -m src.replay [configs/default.yaml]     (make demo)
"""
from __future__ import annotations

import sys
from datetime import date

from src.config import load_config
from src.extract import Extractor, RuleExtractor
from src.matcher import MEETS, NOTICE, PASS, TIERS, JobResult, Match, Matcher, gate_job_open, rank
from src.model import Candidate, Event, Fact, Job
from src.snapshot import World, load_snapshot

DETAIL_ROWS = 3   # show unmet requirements under the first rows of a ranking


# --------------------------------------------------------------------------- applying events

def apply_event(world: World, event: Event, extractor: Extractor) -> list[Fact]:
    """Merge an event into the world. Returns the facts the event added."""
    new = [f for fs in event.entity.facts.values() for f in fs]
    for doc in event.entity.docs:
        new += extractor.extract(doc)
    if event.subject_type == "job":
        target = world.jobs.setdefault(event.subject_id, Job(event.subject_id))
    else:
        target = world.candidates.setdefault(event.subject_id, Candidate(event.subject_id))
    target.docs.extend(event.entity.docs)
    target.aliases |= event.entity.aliases
    for f in new:
        target.add(f)
    world.pending_events.remove(event)
    return new


def take_event(world: World, event_id: str) -> Event:
    return next(e for e in world.pending_events if e.event_id == event_id)


# The demo timeline: (label, events applied in order since the snapshot).
STAGES = [("18:00 snapshot", []),
          ("18:05 + EV-JOB-904 (new requisition)", ["EV-JOB-904"]),
          ("18:10 + EV-C1-NEW (C1 message)", ["EV-JOB-904", "EV-C1-NEW"])]


def world_at(stage: int, extractor: Extractor | None = None) -> tuple[World, list[tuple[Event, list[Fact]]]]:
    """The world after the events of STAGES[stage], plus each applied event and the facts it added."""
    extractor = extractor or RuleExtractor()
    world = load_snapshot(extractor=extractor)
    applied = []
    for eid in STAGES[stage][1]:
        event = take_event(world, eid)
        applied.append((event, apply_event(world, event, extractor)))
    return world, applied


# --------------------------------------------------------------------------- comparing results

def summary(m: Match | None) -> dict | None:
    """The parts of a match a recruiter compares before and after."""
    if m is None:
        return None
    return {"tier": m.tier, "rank": m.rank, "tied": len(m.tied_with), "score": m.score,
            "action": m.next_action["text"]}


def rank_text(s: dict) -> str:
    return f"#{s['rank']}" + (f" (tied with {s['tied']})" if s["tied"] else "")


def changed_items(before: Match, after: Match) -> list[tuple[str, str, str, list[Fact]]]:
    """Gates and requirement checks whose status changed: (name, old, new, evidence)."""
    out = []
    old_gates = {g.name: g for g in before.gates}
    for g in after.gates:
        old = old_gates.get(g.name)
        if old is None or (old.status, old.mismatch) != (g.status, g.mismatch):
            old_state = old.status if old else "not checked"
            new_state = g.status + (f" / {g.mismatch}" if g.status != PASS and g.mismatch else "")
            out.append((f"gate {g.name}", old_state, f"{new_state} – {g.reason}", g.evidence))
    for version, checks in after.checks.items():
        old_checks = {ch.name: ch for ch in before.checks.get(version, [])}
        for ch in checks:
            old = old_checks.get(ch.name)
            if old is None or old.state != ch.state:
                out.append((f"{version} {ch.name}", old.state if old else "not checked",
                            f"{ch.state} – {ch.detail}", ch.evidence))
    return out


def tie_value(name: str, key) -> str:
    """Tie keys are stored sort-ready (negated); show them as a recruiter would read them."""
    if name == "freshest_evidence":
        return f"newest evidence {date.fromordinal(-key)}"
    if name == "more_independent_evidence":
        return f"{-key} independent source(s)"
    if name == "fewer_open_questions":
        return f"{key} open question(s)"
    return str(key)


def changed_tie_breakers(before: Match, after: Match, cfg: dict) -> list[tuple[str, str, str]]:
    return [(b, tie_value(b, before.tie_keys[b]), tie_value(b, after.tie_keys[b])) for b in cfg["tie_breakers"]
            if before.tie_keys[b] != after.tie_keys[b]]


def cause(evidence: list[Fact], event_id: str) -> str:
    """Quote the event fact behind a change (fall back to the first piece of evidence)."""
    facts = [f for f in evidence if f.source_id == event_id] or evidence[:1]
    return "; ".join(f'"{f.quote}" ({f.source_id} {f.as_of[:16].replace("T", " ")})' for f in facts)


# --------------------------------------------------------------------------- printing

def tier_counts(result: JobResult) -> str:
    counts = [f"{t} {sum(m.tier == t for m in result.matches)}" for t in TIERS]
    if result.not_eligible:
        counts.append(f"not eligible {len(result.not_eligible)}")
    return " · ".join(counts)


def job_heading(world: World, jid: str) -> str:
    j = world.jobs[jid]
    loc = j.latest("location").value
    start = j.latest("start_date")
    return (f"{jid} {j.latest('title').value}, {loc['city']} {loc['state']}"
            + (f", starts {start.value}" if start else ""))


def print_ranking(result: JobResult) -> None:
    for row, m in enumerate(result.matches):
        tie = "=" if m.tied_with else " "
        print(f"    #{m.rank:<2}{tie} {m.candidate_id:<4} {m.tier:<20} {m.score:.3f}  {m.next_action['text']}")
        if row < DETAIL_ROWS:
            for ch in m.checks["published"]:
                if ch.state != MEETS:
                    print(f"           - {ch.level} {ch.name}: {ch.detail}")
    if result.not_eligible:
        print(f"    not eligible (profession): {', '.join(cid for cid, _ in result.not_eligible)}")


def print_new_facts(facts: list[Fact], fields: set[str] | None = None) -> None:
    for f in facts:
        if fields is None or f.field in fields or f.field.startswith("req."):
            print(f"    + {f.field}: {f.text()}   ← \"{f.quote}\"")


# --------------------------------------------------------------------------- the demo

def run(config_path: str | None = None) -> None:
    cfg = load_config(config_path) if config_path else load_config()
    extractor = RuleExtractor()
    world = load_snapshot(extractor=extractor)
    matcher = Matcher(world, cfg)

    print(f"REPLAY  config: {cfg['name']}  reference date 2026-11-07")
    print(NOTICE)

    # 18:00 – snapshot
    print(f"\n18:00  snapshot: {len(world.candidates)} candidates, {len(world.jobs)} jobs")
    results: dict[str, JobResult] = {}
    for jid in world.jobs:
        result = matcher.match_job(jid)
        if result.excluded_reason:
            print(f"  {jid:<8} {result.excluded_reason}")
        else:
            results[jid] = result
            print(f"  {jid:<8} {tier_counts(result)}")
            for q in result.job_questions:
                print(f"           ? {q}")

    # 18:05 – new requisition: match only the new job
    event = take_event(world, "EV-JOB-904")
    new_facts = apply_event(world, event, extractor)
    jid = event.subject_id
    print(f"\n18:05  {event.event_id} {event.kind} → {job_heading(world, jid)}")
    print_new_facts(new_facts, {"setting", "shift", "min_experience", "pay"})
    if gate_job_open(world.jobs[jid]).status == PASS:
        results[jid] = matcher.match_job(jid)
        print(f"  matched {jid} against all candidates:")
        print_ranking(results[jid])
    else:
        print(f"  {jid} is not open – not matched")

    # 18:10 – candidate update: re-match only that candidate against open jobs
    event = take_event(world, "EV-C1-NEW")
    cid = event.subject_id
    before = {j: next((m for m in r.matches if m.candidate_id == cid), None) for j, r in results.items()}
    before_summary = {j: summary(m) for j, m in before.items()}
    new_facts = apply_event(world, event, extractor)
    print(f"\n18:10  {event.event_id} {event.kind} → {cid}")
    for doc in event.entity.docs:
        print(f"    message: \"{doc.text}\"")
    print_new_facts(new_facts)
    print(f"  re-matched {cid} against open jobs:")
    c = world.candidates[cid]
    for j, result in results.items():
        if before[j] is None:
            print(f"    {j:<8} not eligible – unchanged")
            continue
        others = [m for m in result.matches if m.candidate_id != cid]
        after = matcher.evaluate(c, world.jobs[j])
        result.matches = rank(others + [after], cfg)
        old, new = before_summary[j], summary(after)
        diffs = []
        if old["tier"] != new["tier"]:
            diffs.append(f"tier   {old['tier']} → {new['tier']}")
        if (old["rank"], old["tied"]) != (new["rank"], new["tied"]):
            diffs.append(f"rank   {rank_text(old)} → {rank_text(new)}")
        if old["score"] != new["score"]:
            diffs.append(f"score  {old['score']:.3f} → {new['score']:.3f}")
        if old["action"] != new["action"]:
            diffs.append(f"next   {old['action']}\n                → {new['action']}")
        if not diffs:
            print(f"    {j:<8} no change ({new['tier']}, {rank_text(new)}, {new['score']:.3f})")
            continue
        print(f"    {j:<8} " + diffs[0])
        for d in diffs[1:]:
            print(f"             {d}")
        items = changed_items(before[j], after)
        for name, old_state, new_state, evidence in items:
            print(f"             because {name}: {old_state} → {new_state}")
            print(f"               {cause(evidence, event.event_id)}")
        if not items:   # same tier and checks: the rank moved on a tie-breaker
            for name, old_key, new_key in changed_tie_breakers(before[j], after, cfg):
                print(f"             because tie-breaker {name}: {old_key} → {new_key}")
                print(f"               {cause(new_facts, event.event_id)}")


def main(argv: list[str]) -> None:
    run(argv[0] if argv else None)


if __name__ == "__main__":
    main(sys.argv[1:])
