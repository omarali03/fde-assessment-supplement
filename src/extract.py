"""Extraction: free text (résumés, messages, notes) -> Facts with quotes.

`Extractor` is the interface. `RuleExtractor` is the real implementation (regex rules,
deterministic). `MockLLMExtractor` shows how an LLM-backed extractor would plug in; it is
a MOCK and never calls a model.

Skill evidence statuses:
  demonstrated      the text describes doing it ("Complete OASIS start-of-care documentation")
  not_demonstrated  the text raises it without showing it ("No home-health ... detail supplied",
                    "Has not yet answered questions about home-health work")
  confirmed_absent  the candidate says they lack it ("I have not used Homecare Homebase")
  stated            listed only, e.g. an ATS skills tag (set by the ATS adapter); never meets a requirement
"""
from __future__ import annotations

import re
from typing import Protocol

from src.model import REFERENCE_DATE, Fact, SourceDoc
from src.vocab import (CERTIFICATIONS, LICENSE_RE, MONTH_RE, NUMBER_RE, STATE_CODES, month_number,
                       normalize_place, requirement_names_in, resolve_date, skill_names_in, to_number,
                       years_between)


class Extractor(Protocol):
    name: str

    def extract(self, doc: SourceDoc) -> list[Fact]: ...


# --------------------------------------------------------------------------- helpers

def sentences(text: str) -> list[str]:
    """Split into lines, then sentences. Bullets and blank lines are dropped."""
    out = []
    for line in text.splitlines():
        line = line.strip(" •\t")
        if line:
            out += [s.strip() for s in re.split(r"(?<=[.!?])\s+(?=[A-Z$])", line) if s.strip()]
    return out


CONFIRMED_ABSENT = re.compile(r"\b(have not used|haven't used|never used|no experience (?:with|in))\b", re.I)
NEGATION = re.compile(r"\b(no|not|never|without|asked)\b", re.I)


def skill_status(sentence: str) -> str:
    if CONFIRMED_ABSENT.search(sentence):
        return "confirmed_absent"
    if NEGATION.search(sentence):
        return "not_demonstrated"
    return "demonstrated"


# Candidate rules
START = re.compile(rf"\b(?:start|available)(?: on| from)?(?: until)? {MONTH_RE} (\d{{1,2}})(?:, (\d{{4}}))?", re.I)
PAY = re.compile(r"\$\s?([\d,]+)\s*(?:(?:/|per )\s*(week|hour)|for (?:forty|40) hours)", re.I)
LOC_ACCEPT = re.compile(r"\b(?:open to|interested in|could cover [^.]*? in) ([A-Z][a-z]+)")
LOC_REJECT = re.compile(r"\b([A-Z][a-z]+) is no longer a location|\bnot (?:consider|work in) ([A-Z][a-z]+)")
NO_CONTACT = re.compile(rf"(?:not contact|no (?:job )?contact)[^.]*?until {MONTH_RE} (\d{{1,2}})(?:, (\d{{4}}))?", re.I)
DAY_LIST = re.compile(rf"{MONTH_RE} (\d{{1,2}})(?: (?:and|or) (\d{{1,2}}))?")
CANNOT_WORK = re.compile(r"\b(cannot|can't|unable to) (work|cover)\b", re.I)
CAN_WORK = re.compile(r"\b(could|can|able to) (work|cover)\b", re.I)
WEEKDAYS = re.compile(r"\bweekdays\b", re.I)
SCHEDULE = re.compile(r"current assignment (?:is|runs) (\w+day) through (\w+day)", re.I)
YEARS_CLAIM = re.compile(rf"\b{NUMBER_RE} years? (?:of|in) ", re.I)
DATE_RANGE = re.compile(
    rf"(?:since {MONTH_RE} (\d{{4}}))"                     # since May 2025
    rf"|(?:{MONTH_RE} (\d{{4}})\s*(?:–|-|to)\s*present)"   # May 2025–present
    r"|(?:(\d{4})-(\d{2})\s*(?:–|-|to)\s*present)"          # 2025-05 to present
    r"|(?:(\d{4})\s*(?:–|-|to)\s*present)", re.I)           # 2016–present
EXPERIENCE_AREAS = ["home_health", "outpatient", "emergency_department"]
OWNER = re.compile(r"\b(?:Assigned recruiter|Recruiter) (R\d+)\b")
ROUTE_VIA = re.compile(r"\bgo through (?:recruiter )?(R\d+)\b")
CONTACT_ALLOWED = re.compile(r"contact_allowed=(true|false)")
NO_OUTREACH = re.compile(r"no authorization for automated candidate outreach", re.I)

# Job rules
MIN_EXP = re.compile(rf"\b{NUMBER_RE} years? of (relevant |home-health )?experience (?:is )?(preferred|acceptable|required)", re.I)
MIN_EXP_STRUCT = re.compile(r"minimum experience: (\d+) years?", re.I)
ALT_BOARDS = re.compile(r"[Oo]ther boards (?:considered )?with ([A-Z, and]+)|consideration of other boards with ([A-Z, and]+)")
SETTINGS = {"home_health": r"home[- ]health|home visits", "outpatient": r"\boutpatient\b",
            "orthopedic": r"\borthopedic\b", "emergency_department": r"emergency[- ](?:medicine|department)"}


# --------------------------------------------------------------------------- extractor

class RuleExtractor:
    name = "rules"

    def extract(self, doc: SourceDoc) -> list[Fact]:
        if doc.subject_type == "job":
            return self._job(doc)
        if doc.kind == "operations":
            return self._operations(doc)
        return self._candidate(doc)

    def _fact(self, doc: SourceDoc, field: str, value, quote: str, status: str = "stated") -> Fact:
        is_requirement = field.startswith("req.") or field == "min_experience"
        return Fact(value, field, doc.source_system, doc.source_id, doc.as_of, quote, status,
                    extractor=self.name, rendition_of=doc.rendition_of,
                    related_source_ids=doc.related_source_ids,
                    qualifier=doc.qualifier if is_requirement else None)

    # ---- candidates

    def _candidate(self, doc: SourceDoc) -> list[Fact]:
        facts: list[Fact] = []
        segs = sentences(doc.text)
        for i, s in enumerate(segs):
            add = lambda field, value, status="stated": facts.append(self._fact(doc, field, value, s, status))

            starts = START.findall(s)
            if starts:
                add("start_date", resolve_date(*starts[0], doc.as_of))
            for amount, unit in PAY.findall(s):
                add("pay_min", {"amount": int(amount.replace(",", "")), "unit": (unit or "week").lower()})
            for place in LOC_ACCEPT.findall(s):
                add("location_pref", {"stance": "accept", "place": normalize_place(place)})
            for a, b in LOC_REJECT.findall(s):
                add("location_pref", {"stance": "reject", "place": normalize_place(a or b)})
            for m in NO_CONTACT.findall(s):
                add("no_contact_until", resolve_date(*m, doc.as_of))
            if not starts:
                days = [(mo, d) for mo, d1, d2 in DAY_LIST.findall(s) for d in (d1, d2) if d]
                field = ("unavailable_date" if CANNOT_WORK.search(s)
                         else "available_date" if CAN_WORK.search(s) else None)
                for mo, d in days if field else []:
                    add(field, resolve_date(mo, d, None, doc.as_of))
            if WEEKDAYS.search(s) and not NEGATION.search(s):
                add("shift_pref", "weekdays")
            m = SCHEDULE.search(s)
            if m:
                add("current_schedule", f"{m.group(1).capitalize()}–{m.group(2).capitalize()}")

            for name in skill_names_in(s):
                add(f"skill.{name}", name, skill_status(s))

            m = YEARS_CLAIM.search(s)
            if m and not NEGATION.search(s):
                area = next((a for a in skill_names_in(s[m.end():]) if a in EXPERIENCE_AREAS), None)
                add("years_experience", {"years": to_number(m.group(1)), "area": area, "basis": "claimed"})

            m = DATE_RANGE.search(s)
            if m:
                context = s + " " + (segs[i - 1] if i else "")
                area = next((a for a in skill_names_in(context) if a in EXPERIENCE_AREAS), None)
                start = _range_start(m)
                add("years_experience", {"years": years_between(start, REFERENCE_DATE), "area": area,
                                         "basis": f"dates since {start[:7]}"})

            for m in LICENSE_RE.finditer(s):
                if re.search(r"\bactive\b", s, re.I):
                    add("license", STATE_CODES[m.group(1).capitalize()])
            for cert in CERTIFICATIONS:
                if re.search(rf"\b{cert}\b", s):
                    add("certification", cert)
            if re.search(r"family[- ]medicine board certification", s, re.I):
                add("certification", "Family Medicine board")
        return facts

    def _operations(self, doc: SourceDoc) -> list[Fact]:
        facts = []
        for s in sentences(doc.text):
            for part in re.split(r";\s*", s):
                add = lambda field, value: facts.append(self._fact(doc, field, value, part))
                for owner in OWNER.findall(part):
                    add("owner", owner)
                for r in ROUTE_VIA.findall(part):
                    add("route_via", r)
                for v in CONTACT_ALLOWED.findall(part):
                    add("contact_allowed", v == "true")
                if NO_OUTREACH.search(part):
                    add("outreach_authorized", False)
        return facts

    # ---- jobs

    def _job(self, doc: SourceDoc) -> list[Fact]:
        facts: list[Fact] = []
        levels: dict[str, tuple[str, str]] = {}   # requirement -> (level, quote); later clauses win
        for s in sentences(doc.text):
            last_names: list[str] = []
            for clause in re.split(r";\s*", s):
                add = lambda field, value: facts.append(self._fact(doc, field, value, clause))
                names = requirement_names_in(clause)
                level = _requirement_level(clause)
                if level == "trainable" and not names:
                    names = last_names          # "Homecare Homebase is preferred; facility can train it"
                if level:
                    for name in names:
                        levels[name] = (level, s if names is last_names else clause)
                last_names = names or last_names

                m = MIN_EXP.search(clause)
                if m:
                    area = "home_health" if (m.group(2) or "").strip() == "home-health" else None
                    lvl = "required" if m.group(3).lower() in ("acceptable", "required") else "preferred"
                    add("min_experience", {"years": to_number(m.group(1)), "area": area, "level": lvl})
                m = MIN_EXP_STRUCT.search(clause)
                if m:
                    add("min_experience", {"years": int(m.group(1)), "area": None, "level": "required"})
                m = ALT_BOARDS.search(clause)
                if m:
                    certs = re.findall(r"[A-Z]{3,}", m.group(1) or m.group(2))
                    add("alt_board_path", certs)
                if re.search(r"no confirmed exception to the .* start", clause, re.I):
                    add("start_exception", "none confirmed")
                if re.search(r"only one day", clause, re.I) and re.search(r"not confirmed", clause, re.I):
                    add("partial_coverage", "unconfirmed")
                if doc.kind == "job_description":
                    for setting, pat in SETTINGS.items():
                        if re.search(pat, clause, re.I):
                            add("setting", setting)
                    if WEEKDAYS.search(clause):
                        add("shift", "weekdays")

        for name, (level, quote) in levels.items():
            facts.append(self._fact(doc, f"req.{name}", level, quote))
        return facts


def _requirement_level(clause: str) -> str | None:
    if re.search(r"\btrain", clause, re.I):
        return "trainable"
    if re.search(r"\bpreferred\b", clause, re.I):
        return "preferred"
    if re.search(r"requir|\bneeded\b|\bmust\b", clause, re.I):
        return "required"
    return None


def _range_start(m: re.Match) -> str:
    g = m.groups()
    if g[0]:
        return f"{g[1]}-{month_number(g[0]):02d}-01"
    if g[2]:
        return f"{g[3]}-{month_number(g[2]):02d}-01"
    if g[4]:
        return f"{g[4]}-{g[5]}-01"
    return f"{g[6]}-01-01"   # year only: assume January


# --------------------------------------------------------------------------- mock LLM

class MockLLMExtractor:
    """MOCK — NO MODEL IS CALLED.

    Shows how an LLM extractor would replace RuleExtractor behind the same interface.
    It returns canned facts keyed by source_id (empty unless given), each labelled with
    extractor="mock-llm (MOCK)" so they can never be mistaken for real extraction.
    """
    name = "mock-llm (MOCK)"

    def __init__(self, canned: dict[str, list[dict]] | None = None):
        self.canned = canned or {}

    def extract(self, doc: SourceDoc) -> list[Fact]:
        return [Fact(item["value"], item["field"], doc.source_system, doc.source_id, doc.as_of,
                     item.get("quote", ""), item.get("evidence_status", "stated"), extractor=self.name,
                     rendition_of=doc.rendition_of, related_source_ids=doc.related_source_ids)
                for item in self.canned.get(doc.source_id, [])]
