"""Matcher: candidate x job -> gates, requirement checks, score, tier, next action.

Principles
- Gates return pass / fail / unknown. Unknown is never treated as pass.
- Hard gates (profession, job open, contact, location, availability) block. Start date, pay and
  experience shortfalls are "possibly_negotiable_mismatch" -> Needs clarification, not Blocked.
- Requirements are checked against the PUBLISHED version and, when an account manager has
  proposed changes, the PROPOSED version. Meeting only the proposed version -> Conditional.
- The score is always computed against the published requirements.
- Output is a recommendation only. It never authorizes outreach or submission.

Run: python -m src.matcher [configs/default.yaml]
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import date

from src.config import load_config
from src.duplicates import BADGE as DUPLICATE_BADGE, duplicate_groups
from src.model import PROPOSED, REFERENCE_DATE, SKILL_STATUS_LABELS, Candidate, Fact, Job
from src.snapshot import World, load_snapshot
from src.suggestions import suggest_updates

PASS, FAIL, UNKNOWN = "pass", "fail", "unknown"
MEETS, NEGOTIABLE, EXCEPTION = "meets", "possibly_negotiable_mismatch", "confirmed_exception"
TIERS = ["Strong", "Conditional", "Needs clarification", "Blocked"]
HARD_GATES = {"profession", "job_open", "contact", "location", "availability"}
LOGISTICS_GATES = {"location", "start_date", "availability", "pay"}
SETTINGS = ["home_health", "outpatient", "emergency_department"]   # a job's primary setting is required
PREFERRED_SETTINGS = ["orthopedic"]
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
LABELS = {"home_health": "home-health", "oasis": "OASIS", "hchb": "Homecare Homebase",
          "outpatient": "outpatient", "orthopedic": "orthopedic",
          "emergency_department": "emergency-department"}

LICENSE_LABEL = "license self-reported, unverified – not cleared for submission"
CONDITIONAL_LABEL = f"meets proposed requirements only ({PROPOSED})"
PLACED_LABEL = "status placed – availability unknown from status alone"
NOTICE = "Recommendation only – does not authorize outreach or submission."


# --------------------------------------------------------------------------- result types

@dataclass
class Gate:
    name: str
    status: str                       # pass / fail / unknown
    reason: str
    evidence: list[Fact] = field(default_factory=list)
    mismatch: str | None = None       # meets / possibly_negotiable_mismatch / confirmed_exception
    details: list[str] = field(default_factory=list)


@dataclass
class Check:
    name: str                         # oasis, license.WA, min_experience, setting.home_health, ...
    level: str                        # required / trainable / preferred
    state: str                        # meets / unknown / fail
    detail: str
    evidence: list[Fact] = field(default_factory=list)
    mismatch: str | None = None
    labels: list[str] = field(default_factory=list)
    source: Fact | None = None        # the job fact stating this requirement
    years: float | None = None        # for min_experience
    independent_sources: int = 0
    evidence_status: str | None = None   # skill checks: demonstrated / stated / not_demonstrated / ...


@dataclass
class Match:
    candidate_id: str
    job_id: str
    tier: str
    score: float
    breakdown: dict[str, dict]
    gates: list[Gate]
    checks: dict[str, list[Check]]    # "published" and, if any, "proposed"
    meets_published: bool
    meets_proposed: bool | None
    labels: list[str]
    open_questions: list[str]
    notes: list[str]
    next_action: dict
    conflicts: dict
    suggested_updates: list[dict]
    duplicate_group: list[str]
    tie_keys: dict
    rank: int = 0
    tied_with: list[str] = field(default_factory=list)

    def gate(self, name: str) -> Gate | None:
        return next((g for g in self.gates if g.name == name), None)

    def check(self, name: str, version: str = "published") -> Check | None:
        return next((c for c in self.checks.get(version, []) if c.name == name), None)


@dataclass
class JobResult:
    job_id: str
    excluded_reason: str | None
    matches: list[Match]
    not_eligible: list[tuple[str, str]]   # (candidate id, reason) e.g. profession mismatch
    job_questions: list[str] = field(default_factory=list)   # open questions about the job itself


# --------------------------------------------------------------------------- helpers

def _placed(c: Candidate) -> bool:
    s = c.latest("status")
    return bool(s and s.value == "placed")


def _owner(c: Candidate) -> Fact | None:
    return c.latest("route_via") or c.latest("owner")


def _job_settings(j: Job) -> list[str]:
    found = {f.value for f in j.get("setting")}
    return [s for s in SETTINGS if s in found]


def _exception(cfg: dict, c: Candidate, j: Job, field_name: str) -> dict | None:
    for e in cfg.get("confirmed_exceptions") or []:
        if e.get("job") == j.id and e.get("candidate") == c.id and e.get("field") == field_name:
            return e
    return None


def _schedule_days(text: str) -> set[str]:
    first, last = text.split("–")
    return set(WEEKDAYS[WEEKDAYS.index(first):WEEKDAYS.index(last) + 1])


def _money(v: dict) -> str:
    return f"${v['amount']:,}/{v['unit']}"


# --------------------------------------------------------------------------- gates

def gate_profession(c: Candidate, j: Job) -> Gate:
    cp, jp = c.latest("profession"), j.latest("profession")
    if not cp or not jp:
        return Gate("profession", UNKNOWN, "profession missing", [f for f in (cp, jp) if f])
    ok = cp.value == jp.value
    return Gate("profession", PASS if ok else FAIL, f"candidate {cp.value}; job {jp.value}", [cp, jp])


def gate_job_open(j: Job) -> Gate:
    st = j.latest("status")
    if not st:
        return Gate("job_open", UNKNOWN, "job status missing")
    return Gate("job_open", PASS if st.value == "open" else FAIL, f"job status {st.value}", [st])


def gate_contact(c: Candidate) -> Gate:
    nc = c.latest("no_contact_until")
    allowed = c.get("contact_allowed")
    if nc and nc.value > REFERENCE_DATE:
        return Gate("contact", FAIL, f"candidate asked for no contact until {nc.value}", [nc, *allowed])
    if allowed and allowed[-1].value is False:
        return Gate("contact", FAIL, "contact_allowed is false", allowed)
    owner = _owner(c)
    if owner:
        evidence = [owner, *c.get("outreach_authorized")]
        return Gate("contact", PASS, f"only via owner {owner.value}", evidence)
    return Gate("contact", PASS, "no contact restriction recorded", allowed)


def gate_location(c: Candidate, j: Job) -> Gate:
    loc = j.latest("location").value
    places = {loc["city"], loc["state"]}
    where = f"{loc['city']}, {loc['state']}"
    relevant = [f for f in c.get("location_pref")
                if f.value["place"] in places or f.value["stance"] == "only"]
    def fits(f: Fact) -> bool:
        stance, place = f.value["stance"], f.value["place"]
        return stance in ("accept", "prefers") or (stance == "only" and place in places)

    if relevant:
        newest = relevant[-1]                       # newest dated statement wins; older ones are kept
        ok = fits(newest)
        older = [f for f in relevant[:-1] if fits(f) != ok]   # older facts that would say otherwise
        reason = f"{newest.text()} ({newest.source_label}) for {where}"
        if older:
            reason += "; overrides older: " + ", ".join(str(f) for f in older)
        return Gate("location", PASS if ok else FAIL, reason, [newest, *older])
    home = c.latest("home_location")
    if home and home.value.get("city") == loc["city"]:
        return Gate("location", PASS, f"lives in {loc['city']}", [home])
    return Gate("location", UNKNOWN, f"no stated preference covering {where}")


def gate_start(c: Candidate, j: Job, cfg: dict) -> Gate | None:
    js = j.latest("start_date")
    if not js:
        return None
    cs = c.latest("start_date")
    if not cs:
        reason = PLACED_LABEL if _placed(c) else "no start date stated"
        return Gate("start_date", UNKNOWN, reason, [js])
    if cs.value <= js.value:
        return Gate("start_date", PASS, f"can start {cs.value}; job starts {js.value}", [cs, js], MEETS)
    exc = _exception(cfg, c, j, "start_date")
    if exc:
        return Gate("start_date", PASS, f"start {cs.value} accepted by confirmed exception ({exc.get('source')})",
                    [cs, js], EXCEPTION)
    note = j.latest("start_exception")
    reason = f"can start {cs.value}, after job start {js.value}"
    if note:
        reason += f"; {note.source_id}: no confirmed exception"
    return Gate("start_date", FAIL, reason, [cs, js] + ([note] if note else []), NEGOTIABLE)


def gate_availability(c: Candidate, j: Job) -> Gate | None:
    shifts = j.get("shift_dates")
    if shifts:
        unavailable = {f.value: f for f in c.get("unavailable_date")}
        available = {f.value: f for f in c.get("available_date")}
        schedule = c.latest("current_schedule")
        busy = _schedule_days(schedule.value) if schedule else set()
        statuses, details, evidence = [], [], []
        for s in shifts:
            d = s.value["date"]
            label = f"{d} {s.value['start'][11:16]}–{s.value['end'][11:16]}"
            day = WEEKDAYS[date.fromisoformat(d).weekday()]
            if d in unavailable:
                st, why = FAIL, f"cannot work ({unavailable[d].source_id})"
                evidence.append(unavailable[d])
            elif d in available and day in busy:
                st, why = UNKNOWN, f"offered, but {day} is inside current assignment {schedule.value}"
            elif d in available:
                st, why = PASS, f"offered ({available[d].source_id})"
                evidence.append(available[d])
                if schedule:
                    why += f"; {day} is outside current assignment {schedule.value}"
            else:
                st, why = UNKNOWN, PLACED_LABEL if _placed(c) else "no availability stated"
            statuses.append(st)
            details.append(f"{label}: {st} – {why}")
        if all(s == PASS for s in statuses):
            status, reason = PASS, "available for every shift"
        elif all(s == FAIL for s in statuses):
            status, reason = FAIL, "unavailable for every shift"
        elif FAIL in statuses and PASS in statuses:
            status, reason = UNKNOWN, "covers only some shifts – one-day coverage is an OPEN QUESTION"
        else:
            status, reason = UNKNOWN, "availability not confirmed for every shift"
        return Gate("availability", status, reason, evidence + ([schedule] if schedule else []), details=details)

    js = j.latest("shift")
    if not js:
        return None
    prefs = [f for f in c.get("shift_pref") if f.value == js.value]
    if prefs:
        return Gate("availability", PASS, f"works {js.value}", [prefs[-1], js])
    reason = PLACED_LABEL if _placed(c) else f"no shift preference stated (job: {js.value})"
    return Gate("availability", UNKNOWN, reason, [js])


def gate_pay(c: Candidate, j: Job, cfg: dict) -> Gate | None:
    jp = j.latest("pay")
    if not jp:
        return None
    cp = c.latest("pay_min")
    if not cp:
        return Gate("pay", UNKNOWN, f"candidate minimum not stated (approved {_money(jp.value)})", [jp])
    if cp.value["unit"] != jp.value["unit"]:
        return Gate("pay", UNKNOWN, f"units differ: {_money(cp.value)} vs {_money(jp.value)}", [cp, jp])
    if cp.value["amount"] <= jp.value["amount"]:
        return Gate("pay", PASS, f"minimum {_money(cp.value)} ≤ approved {_money(jp.value)}", [cp, jp], MEETS)
    exc = _exception(cfg, c, j, "pay")
    if exc:
        return Gate("pay", PASS, f"pay accepted by confirmed exception ({exc.get('source')})", [cp, jp], EXCEPTION)
    return Gate("pay", FAIL, f"minimum {_money(cp.value)} > approved {_money(jp.value)}", [cp, jp], NEGOTIABLE)


# --------------------------------------------------------------------------- requirement checks

def requirement_versions(j: Job) -> dict[str, dict[str, Fact]]:
    """Published requirements, plus a proposed version when account-manager changes exist."""
    published, proposed = {}, {}
    for name in sorted(j.facts):
        if name.startswith("req.") or name == "min_experience":
            facts = j.get(name)
            pub = [f for f in facts if not f.qualifier]
            prop = [f for f in facts if f.qualifier]
            if pub:
                published[name] = pub[-1]
            if prop:
                proposed[name] = prop[-1]
    if not proposed:
        return {"published": published}
    return {"published": published, "proposed": {**published, **proposed}}


def skill_status(c: Candidate, skill: str) -> tuple[str | None, list[Fact]]:
    facts = c.get(f"skill.{skill}")
    if not facts:
        return None, []
    shown = [f for f in facts if f.evidence_status == "demonstrated"]
    absent = [f for f in facts if f.evidence_status == "confirmed_absent"]
    if absent and (not shown or absent[-1].as_of >= shown[-1].as_of):
        return "confirmed_absent", facts
    if shown:
        return "demonstrated", facts
    if any(f.evidence_status == "stated" for f in facts):
        return "stated", facts          # listed only – never meets a requirement
    return "not_demonstrated", facts


def _sources(facts: list[Fact], status: str) -> str:
    return ", ".join(dict.fromkeys(f"{f.source_label} {f.as_of[:10]}" for f in facts if f.evidence_status == status))


def check_skill(c: Candidate, skill: str, level: str, source: Fact | None, name: str | None = None) -> Check:
    status, facts = skill_status(c, skill)
    groups = len([g for g in c.evidence_groups(f"skill.{skill}") if g[0].evidence_status == status])
    label = LABELS.get(skill, skill)
    shown = SKILL_STATUS_LABELS.get(status, status)
    srcs = _sources(facts, status)
    if level == "trainable":
        state, detail = MEETS, f"{label}: trainable per job" + (f" (candidate: {shown})" if status else "")
    elif status == "demonstrated":
        state, detail = MEETS, f"{label}: {shown} ({srcs})"
    elif status == "confirmed_absent":
        state, detail = FAIL, f"{label}: {shown} ({srcs})"
    elif status == "stated":
        state, detail = UNKNOWN, f"{label}: {shown} ({srcs}) – not {SKILL_STATUS_LABELS['demonstrated']}"
    elif status == "not_demonstrated":
        state, detail = UNKNOWN, f"{label}: {shown} ({srcs})"
    else:
        state, detail = UNKNOWN, f"{label}: no evidence"
    return Check(name or skill, level, state, detail, facts, NEGOTIABLE if state == FAIL else None,
                 source=source, independent_sources=groups, evidence_status=status)


def check_license(c: Candidate, state_code: str, level: str, source: Fact) -> Check:
    facts = [f for f in c.get("license") if f.value == state_code]
    if facts:
        return Check(f"license.{state_code}", level, MEETS, f"{state_code} license reported ({facts[0].source_id})",
                     facts, labels=[LICENSE_LABEL], source=source,
                     independent_sources=len(c.evidence_groups("license")))
    return Check(f"license.{state_code}", level, UNKNOWN, f"no {state_code} license stated", source=source)


def experience_years(c: Candidate, area: str | None) -> tuple[float | None, float | None, list[Fact]]:
    """(best dated years, best claimed years, facts) for an area."""
    facts = [f for f in c.get("years_experience") if area is None or f.value["area"] == area]
    dated = [f.value["years"] for f in facts if f.value["basis"] != "claimed"]
    claimed = [f.value["years"] for f in facts if f.value["basis"] == "claimed"]
    return (max(dated) if dated else None), (max(claimed) if claimed else None), facts


def check_experience(c: Candidate, j: Job, source: Fact) -> Check:
    v = source.value
    settings = _job_settings(j)
    area = v["area"] or (settings[0] if settings else None)
    need = v["years"]
    dated, claimed, facts = experience_years(c, area)
    label = LABELS.get(area, area or "relevant")
    base = dict(name="min_experience", level=v["level"], evidence=facts, source=source, years=dated)
    if dated is not None and dated >= need:
        return Check(state=MEETS, detail=f"{dated} yrs {label} (dated) ≥ {need}", **base)
    if claimed is not None and claimed >= need:
        shown = f"; dated history shows {dated} yrs" if dated is not None else ""
        return Check(state=UNKNOWN, detail=f"claims {claimed} yrs {label}{shown} – needs {need}, unconfirmed", **base)
    if dated is not None:
        return Check(state=FAIL, detail=f"{dated} yrs {label} (dated) < {need}", mismatch=NEGOTIABLE, **base)
    return Check(state=UNKNOWN, detail=f"no {label} experience evidence (needs {need} yrs)", **base)


def check_board(c: Candidate, j: Job) -> Check | None:
    alt = j.latest("alt_board_path")
    if not alt:
        return None
    certs = {f.value for f in c.get("certification")}
    facts = c.get("certification")
    if certs & {"ABEM", "AOBEM"}:
        return Check("board_certification", "required", MEETS, "ABEM/AOBEM reported", facts,
                     labels=["self-reported, unverified"], source=alt)
    has_board = any("board" in x.lower() for x in certs)
    missing = [x for x in alt.value if x not in certs]
    if has_board and not missing:
        return Check("board_certification", "required", MEETS,
                     f"other board + {', '.join(alt.value)} (accepted path per {alt.source_id})", facts,
                     labels=["self-reported, unverified"], source=alt)
    if has_board:
        return Check("board_certification", "required", UNKNOWN, f"other board; missing {', '.join(missing)}",
                     facts, source=alt)
    return Check("board_certification", "required", UNKNOWN, "no board certification stated", facts, source=alt)


def check_version(c: Candidate, j: Job, items: dict[str, Fact]) -> list[Check]:
    checks = []
    for name, src in items.items():
        if name == "min_experience":
            checks.append(check_experience(c, j, src))
        elif name.startswith("req.license."):
            checks.append(check_license(c, name.split(".")[-1], src.value, src))
        elif name == "req.board_em":
            certs = {f.value for f in c.get("certification")}
            ok = bool(certs & {"ABEM", "AOBEM"})
            checks.append(Check("board_em", src.value, MEETS if ok else UNKNOWN,
                                "ABEM/AOBEM reported" if ok else "no ABEM/AOBEM stated", source=src))
        else:
            checks.append(check_skill(c, name[4:], src.value, src))
    setting_facts = {f.value: f for f in j.get("setting")}
    for s in _job_settings(j):
        if f"req.{s}" not in items:
            checks.append(check_skill(c, s, "required", setting_facts[s], name=f"setting.{s}"))
    for s in PREFERRED_SETTINGS:
        if s in setting_facts:
            checks.append(check_skill(c, s, "preferred", setting_facts[s], name=f"setting.{s}"))
    board = check_board(c, j)
    if board:
        checks.append(board)
    return checks


def version_met(checks: list[Check]) -> bool:
    return all(ch.state == MEETS for ch in checks if ch.level != "preferred")


# --------------------------------------------------------------------------- scoring

def score(gates: list[Gate], checks: list[Check], c: Candidate, j: Job, cfg: dict) -> tuple[float, dict]:
    required = [ch for ch in checks if ch.level != "preferred" and ch.name != "min_experience"]
    preferred = [ch for ch in checks if ch.level == "preferred"]
    logistics = [g for g in gates if g.name in LOGISTICS_GATES]

    exp_check = next((ch for ch in checks if ch.name == "min_experience"), None)
    if exp_check:
        years, need = exp_check.years or 0.0, exp_check.source.value["years"]
    else:
        settings = _job_settings(j)
        years = experience_years(c, settings[0] if settings else None)[0] or 0.0
        need = cfg["experience_cap_years"]

    values = {
        "requirements": sum(ch.state == MEETS for ch in required) / len(required) if required else 1.0,
        "experience": min(years / need, 1.0) if need else 1.0,
        "logistics": sum(g.status == PASS for g in logistics) / len(logistics) if logistics else 1.0,
        "preferred": sum(ch.state == MEETS for ch in preferred) / len(preferred) if preferred else 1.0,
    }
    weights = cfg["weights"]
    total_w = sum(weights.values())
    breakdown = {k: {"value": round(values[k], 3), "weight": weights[k],
                     "points": round(values[k] * weights[k] / total_w, 3)} for k in weights}
    return round(sum(b["points"] for b in breakdown.values()), 3), breakdown


# --------------------------------------------------------------------------- questions & actions

def open_questions(c: Candidate, j: Job, gates: list[Gate], checks: list[Check], relies_on_proposed: bool) -> list[str]:
    qs = []
    owner = _owner(c)
    for g in gates:
        if g.status == PASS or g.name in ("profession", "job_open", "contact"):
            continue
        if g.name == "location" and g.status == UNKNOWN:
            loc = j.latest("location").value
            qs.append(f"Ask candidate: would you work in {loc['city']}, {loc['state']}?")
        elif g.name == "start_date" and g.status == UNKNOWN:
            js = j.latest("start_date").value
            who = f"Ask owner {owner.value}" if owner and _placed(c) else "Ask candidate"
            qs.append(f"{who}: earliest start date? (job starts {js})")
        elif g.name == "start_date" and g.mismatch == NEGOTIABLE:
            cs, js = c.latest("start_date").value, j.latest("start_date").value
            qs.append(f"Ask account manager: would the facility accept a {cs} start instead of {js}? "
                      f"(no confirmed exception)")
        elif g.name == "pay" and g.status == UNKNOWN:
            qs.append(f"Ask candidate: minimum pay? (approved {_money(j.latest('pay').value)})")
        elif g.name == "pay" and g.mismatch == NEGOTIABLE:
            qs.append(f"Ask account manager: candidate minimum {_money(c.latest('pay_min').value)} is above "
                      f"approved {_money(j.latest('pay').value)} – any room?")
        elif g.name == "availability" and g.status == UNKNOWN:
            partial = j.latest("partial_coverage")
            if "only some shifts" in g.reason and partial:
                qs.append(f"Ask account manager: would the facility accept one-day coverage? "
                          f"({partial.source_id}: not confirmed)")
            for d in g.details:
                if ": unknown" in d:
                    qs.append(f"Ask candidate: can you work {d.split(':')[0]}?")
            if not g.details:
                qs.append(f"Ask candidate: can you work {j.latest('shift').value}?")

    # A required experience shortfall gets its own question, which also covers the setting.
    exp = next((ch for ch in checks if ch.name == "min_experience" and ch.level != "preferred"), None)
    for ch in checks:
        if ch.state == MEETS or ch.level == "preferred":
            continue
        if ch.name == "min_experience":
            if ch.state == UNKNOWN and "claims" in ch.detail:
                qs.append(f"Ask candidate: dated employer history for the claim – {ch.detail}")
            elif ch.state == UNKNOWN:
                qs.append(f"Ask candidate: how many years of {ch.detail.split('no ')[-1].split(' experience')[0]} experience?")
            else:
                qs.append(f"Ask account manager: would {ch.detail} be accepted?")
        elif ch.name.startswith("setting.") and exp and exp.state != MEETS:
            continue    # covered by the experience question
        elif ch.name.startswith("license."):
            qs.append(f"Ask candidate: do you hold an active {ch.name.split('.')[-1]} license?")
        elif ch.state == FAIL:
            skill = ch.name.split(".")[-1]
            qs.append(f"Ask account manager: is {LABELS.get(skill, skill)} trainable? "
                      f"Candidate says they have not used it.")
        else:
            skill = LABELS.get(ch.name.split(".")[-1], ch.name.split(".")[-1])
            if ch.evidence_status == "stated":
                qs.append(f"Ask candidate: describe your {skill} work – {SKILL_STATUS_LABELS['stated']} in "
                          f"{_sources(ch.evidence, 'stated')}, no {SKILL_STATUS_LABELS['demonstrated']}.")
            else:
                srcs = ", ".join(sorted({f.source_id for f in ch.evidence})) or "no source mentions it"
                qs.append(f"Ask candidate: describe your {skill} work – not demonstrated so far ({srcs}).")

    if relies_on_proposed:
        srcs = sorted({ch.source.source_id for ch in checks if ch.source and ch.source.qualifier})
        qs.append(f"Ask account manager: get facility sign-off on the proposed requirements "
                  f"({', '.join(srcs)}) – currently {PROPOSED}.")
    return list(dict.fromkeys(qs))   # de-duplicate, keep order


def next_action(c: Candidate, gates: list[Gate], tier: str, questions: list[str]) -> dict:
    if tier == "Blocked":
        contact = next(g for g in gates if g.name == "contact")
        groups = c.evidence_groups("no_contact_until")
        nc = groups[-1][0] if groups else None    # cite the original statement, not a note repeating it
        if contact.status == FAIL and nc:
            action = {"type": "blocked_until", "until": nc.value,
                      "text": f"Blocked until {nc.value} – {contact.reason} ({nc.source_id})"}
        else:
            g = next(g for g in gates if g.name in HARD_GATES and g.status == FAIL)
            action = {"type": "blocked", "text": f"Blocked – {g.name}: {g.reason}"}
    elif _owner(c):
        owner = _owner(c).value
        extra = f" with {len(questions)} open question(s)" if questions else ""
        action = {"type": "route_to_owner", "owner": owner,
                  "text": f"Route to owner {owner}{extra} – do not contact candidate directly"}
    elif questions:
        action = {"type": "ask", "text": questions[0]}
    else:
        action = {"type": "contact", "text": "Recruiter may contact the candidate (recruiter's decision)"}
    action["questions"] = questions
    action["notice"] = NOTICE
    return action


# --------------------------------------------------------------------------- evaluation & ranking

class Matcher:
    def __init__(self, world: World, config: dict, duplicates: dict[str, list[str]] | None = None):
        self.world = world
        self.config = config
        self.duplicates = (duplicates if duplicates is not None else
                           duplicate_groups(list(world.candidates.values()), config["duplicate_similarity"]))

    def open_jobs(self) -> list[str]:
        return [jid for jid, j in self.world.jobs.items() if gate_job_open(j).status == PASS]

    def evaluate(self, c: Candidate, j: Job) -> Match:
        cfg = self.config
        gates = [gate_profession(c, j), gate_job_open(j), gate_contact(c), gate_location(c, j)]
        gates += [g for g in (gate_start(c, j, cfg), gate_availability(c, j), gate_pay(c, j, cfg)) if g]

        versions = requirement_versions(j)
        checks = {v: check_version(c, j, items) for v, items in versions.items()}
        gates_ok = all(g.status == PASS for g in gates)
        meets_pub = version_met(checks["published"])
        meets_prop = version_met(checks["proposed"]) if "proposed" in checks else None
        total, breakdown = score(gates, checks["published"], c, j, cfg)

        labels, notes = [], []
        if any(g.status == FAIL for g in gates if g.name in HARD_GATES):
            tier = "Blocked"
        elif gates_ok and meets_pub:
            tier = "Strong" if total >= cfg["thresholds"]["strong_min_score"] else "Conditional"
            if tier == "Conditional":
                labels.append(f"below Strong score threshold ({cfg['thresholds']['strong_min_score']})")
        elif gates_ok and meets_prop:
            tier = "Conditional"
            labels.append(CONDITIONAL_LABEL)
        else:
            tier = "Needs clarification"

        relies_on_proposed = tier == "Conditional" and not meets_pub
        relied = checks["proposed"] if relies_on_proposed else checks["published"]
        if tier == "Needs clarification" and "proposed" in checks:
            pub_gaps = sum(ch.state != MEETS for ch in checks["published"] if ch.level != "preferred")
            prop_gaps = sum(ch.state != MEETS for ch in checks["proposed"] if ch.level != "preferred")
            relied = checks["proposed"] if prop_gaps < pub_gaps else checks["published"]
        if relies_on_proposed:
            # Unverified claims in the published version still need an answer.
            relied = relied + [ch for ch in checks["published"] if ch.state == UNKNOWN and "claims" in ch.detail]
        questions = [] if tier == "Blocked" else open_questions(c, j, gates, relied, relies_on_proposed)

        all_checks = [ch for v in checks.values() for ch in v]
        if any(LICENSE_LABEL in ch.labels for ch in all_checks):
            labels.append(LICENSE_LABEL)
        if _placed(c):
            labels.append(PLACED_LABEL)
            avail = next((g for g in gates if g.name == "availability"), None)
            if avail and avail.status == PASS:
                owner = _owner(c)
                notes.append("Availability comes from the candidate's own message, not from placement status"
                             + (f"; owner {owner.value} has not verified the placement schedule" if owner else ""))
        for ch in all_checks:
            if ch.level == "trainable" and ch.evidence_status == "confirmed_absent":
                skill = LABELS.get(ch.name.split(".")[-1], ch.name)
                notes.append(f"{skill} {SKILL_STATUS_LABELS['confirmed_absent']} "
                             f"({_sources(ch.evidence, 'confirmed_absent')}) – relies on facility training ({PROPOSED})")
        loc = next(g for g in gates if g.name == "location")
        if "overrides older" in loc.reason:
            notes.append(f"Location: {loc.reason}")
        group = self.duplicates.get(c.id, [])
        if group:
            labels.append(DUPLICATE_BADGE)

        newest = max((f.as_of for fs in c.facts.values() for f in fs), default="0000-00-00")
        start = c.latest("start_date")
        tie_keys = {
            "fewer_open_questions": len(questions),
            "earliest_start": start.value if start else "9999-12-31",
            "more_independent_evidence": -sum(ch.independent_sources for ch in checks["published"]
                                              if ch.state == MEETS),
            "freshest_evidence": -date.fromisoformat(newest[:10]).toordinal(),
        }
        return Match(c.id, j.id, tier, total, breakdown, gates, checks, meets_pub, meets_prop,
                     list(dict.fromkeys(labels)), questions, list(dict.fromkeys(notes)),
                     next_action(c, gates, tier, questions), c.conflicts(), suggest_updates(c), group, tie_keys)

    def match_job(self, job_id: str, candidate_ids: list[str] | None = None) -> JobResult:
        j = self.world.jobs[job_id]
        status = gate_job_open(j)
        if status.status != PASS:
            return JobResult(job_id, f"excluded – {status.reason}", [], [])
        matches, not_eligible = [], []
        for cid in candidate_ids or sorted(self.world.candidates):
            c = self.world.candidates[cid]
            prof = gate_profession(c, j)
            if prof.status == FAIL:
                not_eligible.append((cid, prof.reason))
                continue
            matches.append(self.evaluate(c, j))
        return JobResult(job_id, None, rank(matches, self.config), not_eligible, job_questions(j))


def job_questions(j: Job) -> list[str]:
    """Open questions about the job, asked whatever any candidate's answers are."""
    qs = []
    partial = j.latest("partial_coverage")
    if partial and partial.value == "unconfirmed" and len(j.get("shift_dates")) > 1:
        qs.append(f"OPEN QUESTION – Ask account manager: would the facility accept one-day coverage? "
                  f"(\"{partial.quote}\" {partial.source_id})")
    return qs


def rank(matches: list[Match], cfg: dict) -> list[Match]:
    """Order by tier, then score. Scores within tie_margin form a band; tie-breakers order the band;
    candidates still equal on every tie-breaker share a rank and are shown as tied."""
    margin, breakers = cfg["tie_margin"], cfg["tie_breakers"]
    by_score = sorted(matches, key=lambda m: (TIERS.index(m.tier), -m.score, m.candidate_id))
    band, band_top, prev_tier, bands = -1, None, None, {}
    for m in by_score:
        if m.tier != prev_tier or band_top - m.score > margin + 1e-9:
            band, band_top, prev_tier = band + 1, m.score, m.tier
        bands[m.candidate_id] = band

    def key(m):
        return (TIERS.index(m.tier), bands[m.candidate_id], tuple(m.tie_keys[b] for b in breakers))

    ordered = sorted(matches, key=lambda m: (key(m), m.candidate_id))
    groups: dict[tuple, list[Match]] = {}
    for m in ordered:
        groups.setdefault(key(m), []).append(m)
    position = 1
    for members in groups.values():          # dicts keep insertion order, i.e. ranked order
        ids = [m.candidate_id for m in members]
        for m in members:
            m.rank = position
            m.tied_with = [i for i in ids if i != m.candidate_id]
        position += len(members)
    return ordered


# --------------------------------------------------------------------------- CLI

def format_job(result: JobResult, world: World) -> str:
    j = world.jobs[result.job_id]
    title = j.latest("title").value
    lines = [f"=== {result.job_id} – {title}"]
    if result.excluded_reason:
        return lines[0] + f"\n  {result.excluded_reason}"
    lines += [f"  job ? {q}" for q in result.job_questions]
    for tier in TIERS:
        ms = [m for m in result.matches if m.tier == tier]
        if not ms:
            continue
        lines.append(f"  [{tier}]")
        for m in ms:
            tie = f" (tied with {', '.join(m.tied_with)})" if m.tied_with else ""
            lines.append(f"    #{m.rank} {m.candidate_id}  score {m.score:.3f}{tie}")
            lines.append(f"       next: {m.next_action['text']}")
            for g in m.gates:
                if g.status != PASS:
                    lines.append(f"       gate {g.name}: {g.status}{' / ' + g.mismatch if g.mismatch else ''} – {g.reason}")
            for v, cs in m.checks.items():
                for ch in cs:
                    if ch.state != MEETS and ch.level != "preferred":
                        lines.append(f"       {v} {ch.name}: {ch.state} – {ch.detail}")
            for q in m.open_questions:
                lines.append(f"       ? {q}")
            for lab in m.labels:
                lines.append(f"       label: {lab}")
            for n in m.notes:
                lines.append(f"       note: {n}")
            for s in m.suggested_updates:
                lines.append(f"       suggest ({s['status']}): {s['system']} {s['field']}: "
                             f"{s['current']} → {s['suggested']}")
    if result.not_eligible:
        lines.append(f"  not eligible (profession): {', '.join(cid for cid, _ in result.not_eligible)}")
    return "\n".join(lines)


def main(argv: list[str]) -> None:
    cfg = load_config(argv[0]) if argv else load_config()
    world = load_snapshot()
    matcher = Matcher(world, cfg)
    print(f"config: {cfg['name']}   snapshot: 18:00   {NOTICE}\n")
    for jid in world.jobs:
        print(format_job(matcher.match_job(jid), world) + "\n")


if __name__ == "__main__":
    main(sys.argv[1:])
