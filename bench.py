"""Benchmark: match 100,000 synthetic candidates against each open job (`make bench`).

MEASURED, SYNTHETIC DATA. Synthetic candidates are copies of the 16 real candidates' facts with a
seeded random start date and minimum pay, so every gate, check, score and ranking step runs.
Duplicate detection is O(n²) and is skipped (duplicates={}); it runs on the real 16 records only.

One run = match every candidate against one job, including ranking. Each job is run 10 times;
p50/p95 use the nearest-rank method (with 10 runs, p95 is the slowest run).
Results are printed and saved to out/bench.txt.
"""
from __future__ import annotations

import math
import os
import platform
import random
import subprocess
import sys
import time
from datetime import date, timedelta
from pathlib import Path

from src.config import load_config
from src.matcher import Matcher
from src.model import Candidate, Fact
from src.replay import STAGES, world_at

N_CANDIDATES = 100_000
RUNS = 10
SEED = 7
OUT = Path(__file__).parent / "out" / "bench.txt"
SYNTH_AS_OF = "2026-11-07T17:59:00Z"   # newest fact on each synthetic record


def synthetic_candidates(templates: list[Candidate], n: int, seed: int) -> dict[str, Candidate]:
    rng = random.Random(seed)
    out = {}
    for i in range(n):
        t = templates[i % len(templates)]
        c = Candidate(f"S{i:06d}")
        c.facts = {k: list(v) for k, v in t.facts.items()}   # facts are immutable; lists are copied
        c.docs = t.docs
        sid = f"SYNTH-{i:06d}"
        start = (date(2026, 11, 20) + timedelta(days=rng.randrange(30))).isoformat()
        c.add(Fact(start, "start_date", "synthetic", sid, SYNTH_AS_OF, "synthetic start date"))
        pay = t.latest("pay_min")
        if pay:
            amount = round(pay.value["amount"] * rng.uniform(0.9, 1.1))
            c.add(Fact({**pay.value, "amount": amount}, "pay_min", "synthetic", sid, SYNTH_AS_OF, "synthetic pay"))
        out[c.id] = c
    return out


def percentile(samples: list[float], p: float) -> float:
    ordered = sorted(samples)
    return ordered[max(0, math.ceil(p / 100 * len(ordered)) - 1)]


def machine_info() -> str:
    cpu = platform.processor() or platform.machine()
    if sys.platform == "darwin":
        try:
            cpu = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True,
                                 text=True, check=True).stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            pass
    return (f"{cpu}, {os.cpu_count()} logical CPUs (single-threaded run), "
            f"{platform.system()} {platform.release()}, Python {platform.python_version()}")


def main() -> None:
    lines: list[str] = []

    def say(text: str = "") -> None:
        print(text, flush=True)
        lines.append(text)

    cfg = load_config()
    t0 = time.perf_counter()
    world, _ = world_at(len(STAGES) - 1)          # after both replayed events
    load_s = time.perf_counter() - t0
    templates = list(world.candidates.values())

    t0 = time.perf_counter()
    world.candidates = synthetic_candidates(templates, N_CANDIDATES, SEED)
    gen_s = time.perf_counter() - t0
    matcher = Matcher(world, cfg, duplicates={})

    say("BENCHMARK – MEASURED, SYNTHETIC DATA")
    say(f"date: {date.today()}   machine: {machine_info()}")
    say(f"config: {cfg['name']}   candidates: {N_CANDIDATES:,} synthetic (from {len(templates)} real templates, seed {SEED})")
    say(f"runs per job: {RUNS}   duplicate detection: skipped (duplicates={{}})")
    say(f"setup: load + replay {load_s:.2f}s, generate candidates {gen_s:.2f}s")
    say()
    say(f"{'job':<9}{'evaluated':>10}{'not elig.':>10}{'p50 s':>9}{'p95 s':>9}{'µs/cand (p50)':>15}")
    for jid in matcher.open_jobs():
        times = []
        for _ in range(RUNS):
            t0 = time.perf_counter()
            result = matcher.match_job(jid)
            times.append(time.perf_counter() - t0)
        p50, p95 = percentile(times, 50), percentile(times, 95)
        say(f"{jid:<9}{len(result.matches):>10,}{len(result.not_eligible):>10,}{p50:>9.2f}{p95:>9.2f}"
            f"{p50 / N_CANDIDATES * 1e6:>15.1f}")
    say()
    say("One run = gates, requirement checks, score and ranking for every candidate against one job.")
    say("Not eligible = removed at the profession gate (cheap), so jobs differ in cost.")

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text("\n".join(lines) + "\n")
    print(f"\nsaved to {OUT.relative_to(Path(__file__).parent)}")


if __name__ == "__main__":
    main()
