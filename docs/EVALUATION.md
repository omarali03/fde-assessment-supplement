# Evaluation

## Approach

The packet has no historical recruiter judgments or outcome data. So before building any matching code, I worked out the **expected outcomes** from the data by hand: who should rank where for each job and event, and why. I then turned those into tests. The product is judged on whether each shortlist row shows **who deserves attention, why (quoted evidence), what's uncertain, and the next action.**

## Expected vs. actual

| Moment | Expected | Actual |
|---|---|---|
| J2, 18:00 | Casey recommended, routed to R3, availability not assumed from "placed". Drew blocked despite `contact_allowed=true`. One-day coverage is an open question | ✅ |
| J1, 18:00 | Alex and R01/R02/R03/R10 Conditional and tied (proposed requirements only). Blair needs clarification (home health not demonstrated). R11 blocked, R12 rejects Spokane | ✅ |
| VMS-903 | Excluded (filled) | ✅ |
| VMS-904, 18:05 | Blair Strong #1, routed to R2. Alex needs clarification (outpatient not demonstrated) | ✅ |
| 18:10 | Alex drops on J1 (Conditional to Needs clarification, #1 to #9) because of the Dec 8 start, quoting his message | ✅ |
| Config | Division B changes the J1 ranking | ✅ |

**47 tests pass**, and output is identical across repeated runs.

## What testing caught

1. **A stale tag was treated as evidence.** Alex's March ATS skills list said "outpatient rehabilitation", and the system counted it as demonstrated experience. Alex therefore passed the outpatient requirement and got "recruiter may contact". His résumé describes home health only. **Fix:** tags are now "stated (listed only)". They can't meet a requirement and always produce a question.
2. **An open question never appeared.** J2's one-day coverage question didn't show because no candidate happened to cover only one day. **Fix:** it's now a job-level open question that always shows.

## Scale benchmark (measured, synthetic data)

100,000 synthetic candidates (copies of the 16 sample records with randomized start dates and pay). Apple M1 Pro, single-threaded Python 3.11, 10 runs per job, duplicate detection skipped:

| Job | Candidates evaluated | p50 | p95 |
|---|---|---|---|
| J1 | 87,500 | 21.9 s | 25.5 s |
| J2 | 12,500 | 1.8 s | 3.1 s |
| VMS-904 | 87,500 | 16.6 s | 19.2 s |

About 0.2 ms per candidate. A candidate update across 3 open jobs takes **about 0.7 ms**, derived from that per-candidate cost and not separately timed.

**Estimates (not measured):** filtering by profession and state before scoring should bring a job under a second, and parallel jobs scale with CPU count. No model calls are made, so cost is compute only.

**Caveats:** p95 over 10 runs is simply the slowest run. Synthetic data is less varied than a real pool. Duplicate detection compares every pair and was skipped; at scale it would compare only within the same profession and state.

## How I'd validate with recruiters and real outcomes

1. **Offline comparison:** 3–5 recruiters build shortlists by hand for about 20 recently filled jobs. Compare them with the tool's output and review each disagreement to see whether the tool or the recruiter missed something.
2. **Shadow mode:** run alongside recruiters for a few weeks without changing their workflow.
3. **Metrics:**
   - how often recruiters accept or override a recommendation
   - time to a usable shortlist
   - submittal-to-interview rate
   - how often open questions get resolved
   - **zero outreach to blocked candidates**, as a hard safety rule
4. **Tuning:** set weights and thresholds per division from those results, not from guesses.

## Limitations

- Rule-based extraction only catches phrasing it was written for, so new wording can be missed.
- Weights and thresholds are illustrative, and the sample is far too small to tune them.
- Licenses and credentials are self-reported and unverified.
- Division B's freshness tie-breaker rewards any new evidence, including news that makes a candidate a worse fit. Freshness should count only evidence that confirms a fit.
- Possible duplicates can make the pool look larger than it is.
- The benchmark uses synthetic data and an unindexed, single-threaded run.