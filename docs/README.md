# Candidate–Job Matching (FDE assessment)

A recruiter-facing matching tool. When a job arrives, it shows which candidates deserve attention, why (with quoted evidence and its source), what's still uncertain, and the appropriate next action. It reads four sources without overwriting anything, and re-checks only what changes when a new job or candidate update arrives.

All data is fictional or synthetic. No paid services, API keys or network access are needed. Recommendations are not authorization to contact or submit anyone.

## Setup

Requires Python 3.11.

```bash
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Run

| Command | What it shows |
|---|---|
| `make demo` | Loads the 18:00 snapshot, replays the new job (EV-JOB-904, 18:05) and C1's update (EV-C1-NEW, 18:10), and prints before/after changes with the quote that caused each one |
| `make app` | Recruiter screen at http://localhost:8501 |
| `make test` | 47 tests covering the expected outcomes |
| `make bench` | 100,000-candidate synthetic benchmark (takes about 7 min); writes `out/bench.txt` |

## Where to start

1. **In the app, open J2 (Dayton ED).** Drew looks strongest on paper but is blocked by his own message. Casey is recommended and routed to her recruiter, R3.
2. **Click "Apply 18:05", then "Apply 18:10".** Blair goes to the top of the new outpatient job, routed to R2. Alex drops on J1 because his start moved to Dec 8.
3. **Switch to the Division B config** to see how a different configuration changes the J1 ranking.

## Repository layout

```
data/       source files (synthetic)
configs/    default.yaml, division_b.yaml
src/        adapters/, extract.py, snapshot.py, matcher.py, replay.py, duplicates.py, suggestions.py
tests/      47 tests
app.py      Streamlit recruiter screen
bench.py    scale benchmark
out/        benchmark results
docs/       ARCHITECTURE, ASSUMPTIONS, EVALUATION, HANDOFF
```

Read next: `docs/ASSUMPTIONS.md` for the decisions and open questions, then `docs/ARCHITECTURE.md`.