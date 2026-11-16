"""Step 3: rule-based extraction with quotes, evidence statuses, and the extractor interface."""
import pytest

from src.extract import MockLLMExtractor, RuleExtractor
from src.model import SourceDoc
from src.snapshot import load_snapshot


def doc(text, kind="candidate_message", as_of="2026-11-06", subject_type="candidate"):
    return SourceDoc("T-1", "test", subject_type, "X", kind, as_of, text)


def values(facts, field):
    return [f.value for f in facts if f.field == field]


def statuses(facts, field):
    return [f.evidence_status for f in facts if f.field == field]


rules = RuleExtractor()


def test_start_date_and_pay():
    facts = rules.extract(doc("I can start December 1, work weekdays for thirteen weeks, "
                              "and need at least $2,400 per week for forty hours."))
    assert values(facts, "start_date") == ["2026-12-01"]
    assert values(facts, "pay_min") == [{"amount": 2400, "unit": "week"}]
    assert values(facts, "shift_pref") == ["weekdays"]
    assert all(f.quote for f in facts)


def test_cannot_start_until():
    facts = rules.extract(doc("My start date has changed. I cannot start until December 8.", as_of="2026-11-07"))
    assert values(facts, "start_date") == ["2026-12-08"]


def test_hourly_pay():
    assert values(rules.extract(doc("My minimum is $230/hour.")), "pay_min") == [{"amount": 230, "unit": "hour"}]


def test_location_accept_and_reject():
    assert values(rules.extract(doc("I am open to Spokane now.")), "location_pref") == \
        [{"stance": "accept", "place": "Spokane"}]
    assert values(rules.extract(doc("Spokane is no longer a location I would consider.")), "location_pref") == \
        [{"stance": "reject", "place": "Spokane"}]


def test_no_contact_until_infers_year():
    facts = rules.extract(doc("Drew asks for no job contact until January 15.", kind="recruiter_note"))
    assert values(facts, "no_contact_until") == ["2027-01-15"]


def test_shift_days():
    can = rules.extract(doc("I could cover both December 5 and 6 day shifts in Dayton."))
    assert values(can, "available_date") == ["2026-12-05", "2026-12-06"]
    assert values(can, "location_pref") == [{"stance": "accept", "place": "Dayton"}]
    cannot = rules.extract(doc("I cannot work December 5 or 6."))
    assert values(cannot, "unavailable_date") == ["2026-12-05", "2026-12-06"]
    assert values(cannot, "available_date") == []


def test_skill_statuses():
    shown = rules.extract(doc("Complete OASIS start-of-care documentation.", kind="resume"))
    assert statuses(shown, "skill.oasis") == ["demonstrated"]
    missing = rules.extract(doc("No home-health, OASIS, or Homecare Homebase detail supplied.", kind="resume"))
    assert statuses(missing, "skill.home_health") == ["not_demonstrated"]
    assert statuses(missing, "skill.hchb") == ["not_demonstrated"]
    absent = rules.extract(doc("I have not used Homecare Homebase."))
    assert statuses(absent, "skill.hchb") == ["confirmed_absent"]


def test_years_of_experience_claim_and_dates():
    claim = rules.extract(doc("I have three years of home-health work, including OASIS and Homecare Homebase."))
    assert values(claim, "years_experience") == [{"years": 3, "area": "home_health", "basis": "claimed"}]
    dated = rules.extract(doc("Home-health physical therapist at Evergreen Visiting Care since May 2025.", kind="profile"))
    assert values(dated, "years_experience") == [{"years": 1.5, "area": "home_health", "basis": "dates since 2025-05"}]


def test_outpatient_orthopedic():
    facts = rules.extract(doc("My work focuses on outpatient orthopedic rehabilitation.", kind="resume"))
    assert statuses(facts, "skill.outpatient") == ["demonstrated"]
    assert statuses(facts, "skill.orthopedic") == ["demonstrated"]


def test_job_note_trainable_refers_back():
    note = SourceDoc("N", "test", "job", "J", "job_note", "2026-11-05",
                     "OASIS remains required for start-of-care visits. "
                     "Homecare Homebase is preferred; facility can train it.", qualifier="proposed")
    facts = rules.extract(note)
    assert values(facts, "req.oasis") == ["required"]
    assert values(facts, "req.hchb") == ["trainable"]
    assert all(f.qualifier == "proposed" for f in facts if f.field.startswith("req."))


def test_every_snapshot_fact_from_text_has_a_quote():
    world = load_snapshot()
    for entity in [*world.candidates.values(), *world.jobs.values()]:
        for facts in entity.facts.values():
            for f in facts:
                assert f.quote, f


def test_mock_llm_is_labelled_and_swappable():
    mock = MockLLMExtractor({"C1-MSG": [{"field": "start_date", "value": "2026-12-01", "quote": "canned"}]})
    world = load_snapshot(extractor=mock)
    facts = world.candidates["C1"].get("start_date")
    assert [f.extractor for f in facts] == ["mock-llm (MOCK)"]
    assert "MOCK" in MockLLMExtractor.__doc__
