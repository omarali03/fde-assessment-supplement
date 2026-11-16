# Architecture

## How it works

```
Sources: ATS · VMS · client DB · our system · supplemental packet
   │
   ▼
Adapters (one per source) ──► Facts
   │                           value · field · source · source_id · date · quote · evidence status · lineage
   ▼
Rule extractor (messages, notes, résumés ──► more Facts)
   │
   ▼
Snapshot: all Facts in memory, append-only, never overwritten
   │
   ▼
Matcher (driven by config): gates → requirements → score → tier → next action
   │
   ▼
Destinations: demo CLI (make demo) · Streamlit app (make app)
```

The core idea is that **everything becomes a small "fact"** carrying its source, date and exact quote. Facts are only ever added, never replaced. So a conflict is just two facts that disagree (Alex: "Oregon only", ATS 2026-03-01, vs. "open to Spokane", C1-MSG 2026-11-06), and every explanation in the UI points straight back to its evidence.

## Matching

1. **Gates** return pass, fail or unknown: profession, job open, contact allowed, location, start date, per-day availability, pay. Unknown is never treated as pass.
2. **Requirements** are checked with an evidence status: *demonstrated* (described work), *stated* (listed only, such as an ATS tag), *not demonstrated*, or *confirmed absent*. J1 is checked against both its published and its proposed requirements.
3. **Score**: weighted components from config, with a per-component breakdown shown.
4. **Tier**: Strong / Conditional (meets only unconfirmed requirements) / Needs clarification / Blocked.
5. **Next action**: contact, route to owner (C2→R2, C3→R3, R10→R10), ask a specific question, or blocked until a date. Every action is labeled "recommendation only".

Side outputs:
- Possible-duplicate badges (word similarity within the same profession; never merged).
- Suggested field updates for recruiter review (never written back).
- Job-level open questions, such as J2's one-day coverage.

**Why rules plus weights rather than ML or an LLM score:** there are no labeled outcomes to train on, and recruiters need explanations they can check. A rule they can read and a weight they can change is auditable. An LLM is better used for extraction (below), not for the final ranking.

## Adding a source or destination

- **New source:** write one adapter that turns its records into Facts, and add its IDs to the ID map (for example, client DB person 501 = ATS C1, and VMS-901 = ATS J1). The matcher doesn't change.
- **New destination** (ATS write-back, webhook, email digest): read the match results. Matching doesn't know where output goes.

## Configuration

`configs/*.yaml` per client or division: component weights, Strong threshold, tie margin, tie-breakers, experience cap, duplicate threshold, and `confirmed_exceptions`. Config validation rejects protected attributes and unknown tie-breakers. `division_b.yaml` shows a second division's priorities, and it changes the J1 ranking.

## Events and updates

- **New job** (EV-JOB-904): build the job from its facts and score every candidate against it.
- **Candidate update** (EV-C1-NEW): add the new fact, then re-score that one candidate against open jobs only.
- `make demo` prints the before/after differences (tier, rank, score, next action) with the quote that caused each change.

In production these would arrive from each source's change feed or webhook onto a queue, and matching would run asynchronously, so recruiters see results when they open the job.

## Scale (100,000+ candidates)

- **Measured:** about 0.2 ms per candidate per job, which is about 22 s for J1 across 100k synthetic candidates. That's single-threaded with no indexing (see EVALUATION).
- **Plan (estimates, not built):**
  - Index candidates by profession and state, then score only that pool. That takes it from 100k to a few thousand, and under a second.
  - Run jobs in parallel.
  - Detect duplicates only within the same profession and state.
  - Store facts in a database such as Postgres instead of memory.
- **Updates** are cheap: one candidate times the open jobs (about 0.7 ms, derived from the measured per-candidate cost).
- **Cost:** no model calls today, so compute only. If an LLM extractor is added, run it once per new document and cache the result by content hash, so cost scales with new documents rather than with matches.

## AI extraction

Extraction is rule-based today (keywords and regex with exact quotes). `MockLLMExtractor` sits behind the same interface and is labeled **"MOCK – NO MODEL IS CALLED"**. A real extractor would have to return a quote for every fact, and each quote would be checked against the source text before the fact is accepted. A sample would also be compared with the rule extractor and with recruiter review before it's switched on.