"""Possible-duplicate detection.

Two candidates of the same profession whose original profile/résumé text is very similar are
grouped under a "possible duplicate – unconfirmed" badge. They are NEVER merged: text similarity
alone does not prove two records are the same person (R01–R12 have different emails).
"""
from __future__ import annotations

import re

from src.model import Candidate

BADGE = "possible duplicate – unconfirmed"
STOPWORDS = {"a", "an", "and", "at", "for", "in", "of", "on", "the", "to", "with", "since", "fictional"}


def tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9][a-z0-9'-]*", text.lower())) - STOPWORDS


def base_text(c: Candidate) -> str:
    """The candidate's original profile/résumé text (renditions are skipped)."""
    docs = sorted((d for d in c.docs if d.kind in ("resume", "profile") and not d.rendition_of),
                  key=lambda d: (d.as_of, d.source_id))
    return docs[0].text if docs else ""


def jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a | b else 0.0


def duplicate_groups(candidates: list[Candidate], threshold: float) -> dict[str, list[str]]:
    """Map candidate id -> sorted ids in its possible-duplicate group (only groups of 2+)."""
    info = []
    for c in sorted(candidates, key=lambda c: c.id):
        prof = c.latest("profession")
        info.append((c.id, prof.value if prof else None, tokens(base_text(c))))

    parent = {cid: cid for cid, _, _ in info}

    def find(x):
        while parent[x] != x:
            x = parent[x]
        return x

    for i, (a, prof_a, tok_a) in enumerate(info):
        for b, prof_b, tok_b in info[i + 1:]:
            if prof_a and prof_a == prof_b and tok_a and jaccard(tok_a, tok_b) >= threshold:
                parent[find(b)] = find(a)

    groups: dict[str, list[str]] = {}
    for cid, _, _ in info:
        groups.setdefault(find(cid), []).append(cid)
    return {cid: members for members in groups.values() if len(members) > 1 for cid in members}
