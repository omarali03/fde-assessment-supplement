"""Shared vocabulary: states, months, number words, skill and requirement names."""
from __future__ import annotations

import re
from datetime import date

STATE_NAMES = {"OR": "Oregon", "WA": "Washington", "OH": "Ohio"}
STATE_CODES = {name: code for code, name in STATE_NAMES.items()}

MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]
MONTH_RE = "(" + "|".join(MONTHS) + ")"

NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
                "seven": 7, "eight": 8, "nine": 9, "ten": 10, "thirteen": 13, "forty": 40}
NUMBER_RE = r"(\d+|" + "|".join(NUMBER_WORDS) + ")"

# Skills a candidate can demonstrate. Order is fixed so output is deterministic.
SKILL_PATTERNS = {
    "home_health": r"home[- ]health|home visits|patients' homes",
    "oasis": r"\boasis\b",
    "hchb": r"homecare homebase",
    "outpatient": r"\boutpatient\b",
    "orthopedic": r"\borthopedic\b",
    "emergency_department": r"emergency[- ]department",
}

# Requirements a job can state (licenses are handled separately).
REQUIREMENT_PATTERNS = {
    "oasis": r"\boasis\b",
    "hchb": r"homecare homebase",
    "emergency_department": r"emergency[- ]department experience",
    "board_em": r"\bABEM\b|\bAOBEM\b",
}
LICENSE_RE = re.compile(r"\b(Washington|Ohio|Oregon)(?: PT| physical-therapy| physician)? license", re.I)

CERTIFICATIONS = ["ABEM", "AOBEM", "ATLS", "ACLS", "PALS", "BLS"]


def to_number(token: str) -> int:
    return int(token) if token.isdigit() else NUMBER_WORDS[token.lower()]


def month_number(name: str) -> int:
    return MONTHS.index(name.capitalize()) + 1


def resolve_date(month: str, day: str, year: str | None, as_of: str) -> str:
    """'December 1' said on 2026-11-06 means the next December 1 on or after that day."""
    m, d = month_number(month), int(day)
    if year:
        return date(int(year), m, d).isoformat()
    said_on = date.fromisoformat(as_of[:10])
    candidate = date(said_on.year, m, d)
    if candidate < said_on:
        candidate = date(said_on.year + 1, m, d)
    return candidate.isoformat()


def years_between(start_iso: str, end_iso: str) -> float:
    days = (date.fromisoformat(end_iso[:10]) - date.fromisoformat(start_iso[:10])).days
    return round(days / 365.25, 1)


def skill_names_in(text: str) -> list[str]:
    return [name for name, pat in SKILL_PATTERNS.items() if re.search(pat, text, re.I)]


def requirement_names_in(text: str) -> list[str]:
    names = [name for name, pat in REQUIREMENT_PATTERNS.items() if re.search(pat, text, re.I)]
    for m in LICENSE_RE.finditer(text):
        names.append("license." + STATE_CODES[m.group(1).capitalize()])
    return names


def normalize_place(text: str) -> str:
    """State names become codes ('Oregon' -> 'OR'); city names stay as written."""
    return STATE_CODES.get(text, text)


def normalize_profession(title: str) -> str | None:
    if re.search(r"physician", title, re.I):
        return "Physician"
    if re.search(r"physical therapist|\bPT\b", title, re.I):
        return "Physical Therapist"
    return None


def normalize_specialty(title: str) -> str | None:
    if re.search(r"emergency|\bED\b", title, re.I):
        return "Emergency Medicine"
    return None
