"""Step 6: the expected outcomes from the spec, at 18:00 and after replaying both events."""
import copy

import pytest

from src import replay
from src.config import ConfigError, load_config, validate
from src.duplicates import BADGE
from src.extract import RuleExtractor
from src.matcher import LICENSE_LABEL, MEETS, PLACED_LABEL, Matcher
from src.model import SKILL_STATUS_LABELS
from src.snapshot import load_snapshot

DEFAULT = load_config()
DIVISION_B = load_config("configs/division_b.yaml")


def results_for(world, cfg):
    m = Matcher(world, cfg)
    return {jid: m.match_job(jid) for jid in world.jobs}


def match(results, job, cid):
    return next(m for m in results[job].matches if m.candidate_id == cid)


def replayed_world(*event_ids):
    world = load_snapshot()
    for eid in event_ids:
        replay.apply_event(world, replay.take_event(world, eid), RuleExtractor())
    return world


@pytest.fixture(scope="module")
def snapshot():
    world = load_snapshot()
    return world, results_for(world, DEFAULT)


@pytest.fixture(scope="module")
def after_job_event():
    world = replayed_world("EV-JOB-904")
    return world, results_for(world, DEFAULT)


@pytest.fixture(scope="module")
def after_both_events():
    world = replayed_world("EV-JOB-904", "EV-C1-NEW")
    return world, results_for(world, DEFAULT)


# --------------------------------------------------------------------------- 18:00 snapshot

def test_vms_903_is_excluded(snapshot):
    _, results = snapshot
    assert results["VMS-903"].matches == []
    assert "filled" in results["VMS-903"].excluded_reason


def test_c1_keeps_both_location_facts(snapshot):
    world, _ = snapshot
    prefs = [str(f) for f in world.candidates["C1"].get("location_pref")]
    assert "Oregon only (ATS 2026-03-01)" in prefs
    assert "open to Spokane (C1-MSG 2026-11-06)" in prefs


def test_j2_one_day_coverage_is_an_open_question(snapshot):
    _, results = snapshot
    qs = results["J2"].job_questions
    assert any("OPEN QUESTION" in q and "one-day coverage" in q and "J2-NOTE-01" in q for q in qs)


def test_c1_conditional_on_j1_meets_proposed_only(snapshot):
    _, results = snapshot
    m = match(results, "J1", "C1")
    assert m.tier == "Conditional"
    assert m.meets_published is False and m.meets_proposed is True
    assert any("proposed – pending facility confirmation" in lab for lab in m.labels)


def test_c3_placed_availability_not_assumed_and_routed_to_r3(snapshot):
    _, results = snapshot
    m = match(results, "J2", "C3")
    assert PLACED_LABEL in m.labels
    avail = m.gate("availability")
    assert all(f.source_id != "C3-OPS" and f.field != "status" for f in avail.evidence)
    assert all("C3-MSG" in d for d in avail.details)            # each shift checked against the candidate's message
    assert any("not from placement status" in n for n in m.notes)
    assert m.next_action["type"] == "route_to_owner" and m.next_action["owner"] == "R3"


@pytest.mark.parametrize("cfg", [DEFAULT, DIVISION_B], ids=["default", "division_b"])
def test_c4_never_gets_a_contact_action(cfg):
    world = replayed_world("EV-JOB-904", "EV-C1-NEW")
    for result in results_for(world, cfg).values():
        for m in result.matches:
            if m.candidate_id == "C4":
                assert m.tier == "Blocked"
                assert m.next_action["type"] == "blocked_until"
                assert m.next_action["until"] == "2027-01-15"


def test_c4_contact_allowed_suggestion(snapshot):
    _, results = snapshot
    s = next(s for s in match(results, "J2", "C4").suggested_updates if s["field"] == "contact_allowed")
    assert s["current"] == "true" and s["suggested"].startswith("false")
    assert "not written back" in s["status"]


def test_routing_to_owners(snapshot, after_job_event):
    _, results = snapshot
    assert match(results, "J1", "C2").next_action["owner"] == "R2"
    assert match(results, "J1", "R10").next_action["owner"] == "R10"
    _, results = after_job_event
    assert match(results, "VMS-904", "C2").next_action["owner"] == "R2"
    for result in results.values():
        for m in result.matches:
            assert m.next_action["notice"].startswith("Recommendation only")


def test_r01_r03_tied(snapshot):
    _, results = snapshot
    r01, r02, r03 = (match(results, "J1", c) for c in ("R01", "R02", "R03"))
    assert r01.rank == r02.rank == r03.rank
    assert {"R02", "R03"} <= set(r01.tied_with)


def test_duplicates_badged_never_merged(snapshot):
    world, results = snapshot
    assert len(world.candidates) == 16
    profiles = ["C1"] + [f"R{i:02d}" for i in range(1, 13)]
    for cid in profiles:
        assert cid in world.candidates                        # still its own record
        m = match(results, "J1", cid)
        assert BADGE in m.labels and "C1" in m.duplicate_group
    for cid in ("C2",):
        assert BADGE not in match(results, "J1", cid).labels
    assert BADGE not in match(results, "J2", "C3").labels
    emails = {world.candidates[c].latest("email").value for c in profiles if world.candidates[c].latest("email")}
    assert len(emails) > 1                                    # different people on record


def test_license_label(snapshot):
    _, results = snapshot
    assert "self-reported, unverified" in LICENSE_LABEL
    for result in results.values():
        for m in result.matches:
            for ch in m.checks["published"]:
                if ch.name.startswith("license.") and ch.state == MEETS:
                    assert LICENSE_LABEL in ch.labels and LICENSE_LABEL in m.labels


def test_stated_only_skill_never_meets_and_always_asks(after_both_events):
    _, results = after_both_events
    seen = 0
    for result in results.values():
        for m in result.matches:
            for checks in m.checks.values():
                for ch in checks:
                    if ch.evidence_status != "stated" or ch.level == "trainable":
                        continue
                    seen += 1
                    assert ch.state != MEETS
                    assert SKILL_STATUS_LABELS["stated"] in ch.detail
                    if ch.level == "required" and m.tier != "Blocked":
                        assert any(SKILL_STATUS_LABELS["stated"] in q for q in m.open_questions)
    assert seen > 0                                           # the rule was actually exercised (C1 outpatient)


# --------------------------------------------------------------------------- replay

def test_replay_vms_904(after_job_event):
    _, results = after_job_event
    top = results["VMS-904"].matches[0]
    assert (top.candidate_id, top.tier, top.rank, top.tied_with) == ("C2", "Strong", 1, [])
    c1 = match(results, "VMS-904", "C1")
    assert c1.tier == "Needs clarification"
    assert c1.check("setting.outpatient").evidence_status == "stated"


def test_replay_c1_drops_on_j1(snapshot, after_both_events):
    _, before = snapshot
    _, after = after_both_events
    old, new = match(before, "J1", "C1"), match(after, "J1", "C1")
    assert (old.tier, new.tier) == ("Conditional", "Needs clarification")
    assert new.rank > old.rank and new.score < old.score
    gate = new.gate("start_date")
    assert gate.status == "fail" and any(f.source_id == "EV-C1-NEW" for f in gate.evidence)
    assert [f.value for f in after_both_events[0].candidates["C1"].get("start_date")][-1] == "2026-12-08"
    assert len(after_both_events[0].candidates["C1"].get("start_date")) > 1   # old date kept, not overwritten


# --------------------------------------------------------------------------- configuration

def test_division_b_changes_j1_ranking(snapshot):
    world, default = snapshot
    div_b = results_for(world, DIVISION_B)
    order = lambda r: [(m.candidate_id, m.rank) for m in r["J1"].matches]
    assert order(default) != order(div_b)


@pytest.mark.parametrize("attr", ["name", "age", "gender", "race", "email", "date_of_birth"])
def test_protected_attributes_rejected_as_tie_breakers(attr):
    cfg = copy.deepcopy(DEFAULT)
    cfg["tie_breakers"] = [attr]
    with pytest.raises(ConfigError, match="protected"):
        validate(cfg)


def test_deterministic_output(capsys):
    outputs = []
    for _ in range(2):
        replay.run()
        outputs.append(capsys.readouterr().out)
    assert outputs[0] == outputs[1] and "18:10" in outputs[0]
