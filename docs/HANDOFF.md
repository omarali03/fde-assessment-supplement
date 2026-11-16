# Handoff

## Implemented, simulated, deferred

| Implemented | Simulated or mocked | Deferred |
|---|---|---|
| Source adapters, append-only facts with provenance and lineage, ID mapping, rule-based extraction, matcher (gates, requirements, scores, tiers, ties, next actions), duplicate badges, suggested field updates, job-level open questions, event replay, Streamlit app, 47 tests, 100k benchmark | `MockLLMExtractor` (no model called); 100k synthetic candidates; events replayed from files rather than live feeds | Approval workflow for requirement changes, writing back to sources, live license verification, indexing and a database, a real LLM extractor, notifications to owning recruiters |

## Open questions for the client

Full list in ASSUMPTIONS.md. The ones that matter most:
1. Who approves requirement changes such as J1's, and how does approval reach the product?
2. Source precedence and freshness windows per division.
3. Does "no restriction recorded" mean OK to contact?
4. Will the Dayton facility accept one-day coverage?

## Onboarding a similar client

1. **Map their sources.** Write one adapter per system that outputs Facts, plus ID mappings between them.
2. **Run discovery** on the decisions in ASSUMPTIONS.md: precedence, freshness, ownership, contact rules, what counts as evidence.
3. **Create configs** per division: weights, thresholds and tie-breakers.
4. **Calibrate** on about 20 filled jobs with their recruiters, using the comparison in EVALUATION.md.
5. **Shadow mode**, then go live, with blocked-candidate outreach monitored as a hard rule.

No matcher changes are needed for a new client unless they have a genuinely new kind of requirement.

## How I used AI

- **Claude (chat)** helped me read and analyze the data packet, find the conflicts and traps, draft the discovery email, plan the build, and structure these docs.
- **Claude Code** wrote the code in eight steps. I reviewed each step's output before approving the next.
- **How I checked it:**
  - I wrote the expected outcomes before any matching code and tested every step against them.
  - I spot-checked evidence quotes against the source files.
  - I made the judgment calls myself: keeping the stated vs. demonstrated rule, documenting the freshness issue rather than hiding it, and making one-day coverage a permanent open question.
- The two bugs described in EVALUATION.md were caught by comparing output with my expected outcomes.