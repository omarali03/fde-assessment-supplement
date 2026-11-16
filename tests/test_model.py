"""Step 2: shared format, id mapping, conflicts kept, lineage de-duplication."""
import pytest

from src.model import PROPOSED
from src.snapshot import load_snapshot


@pytest.fixture(scope="module")
def world():
    return load_snapshot()


def texts(entity, field):
    return [str(f) for f in entity.get(field)]


def test_c1_keeps_both_location_facts(world):
    prefs = texts(world.candidates["C1"], "location_pref")
    assert "Oregon only (ATS 2026-03-01)" in prefs
    assert "open to Spokane (C1-MSG 2026-11-06)" in prefs
    assert "location_pref" in world.candidates["C1"].conflicts()


def test_id_mapping(world):
    assert world.idmap.resolve("client_db", "501") == "C1"
    assert world.idmap.resolve("vms", "VMS-901") == "J1"
    assert world.idmap.resolve("vms", "VMS-903") == "VMS-903"
    ev = next(e for e in world.pending_events if e.event_id == "EV-C1-NEW")
    assert ev.subject_id == "C1"
    ev = next(e for e in world.pending_events if e.event_id == "EV-JOB-904")
    assert ev.subject_id == "VMS-904"


def test_profiles_with_identical_text_stay_separate(world):
    assert {"R01", "R02", "R03"} <= set(world.candidates)
    assert world.candidates["R01"].get("email")[0].value != world.candidates["R02"].get("email")[0].value


def test_resume_renditions_count_once(world):
    c1 = world.candidates["C1"]
    groups = c1.evidence_groups("skill.oasis")
    assert len(groups) == 1
    assert {f.source_id for f in groups[0]} == {"C1-CV", "C1-CV-FULL", "C1-CV-FULL.txt"}


def test_note_repeating_message_counts_once(world):
    c1 = world.candidates["C1"]
    groups = c1.evidence_groups("pay_min")
    assert len(groups) == 1
    assert {f.source_id for f in groups[0]} == {"C1-MSG", "C1-NOTE-02"}

    c4 = world.candidates["C4"]
    assert len(c4.evidence_groups("no_contact_until")) == 1


def test_note_citing_two_sources_does_not_merge_them(world):
    # R04-NOTE-01 cites both R04-BASE and R04-UPDATE; those remain two pieces of evidence.
    groups = world.candidates["R04"].evidence_groups("skill.home_health")
    assert len(groups) == 2


def test_ats_job_and_vms_requisition_are_one_source(world):
    groups = world.jobs["J1"].evidence_groups("req.oasis")
    published = [g for g in groups if not g[0].qualifier]
    assert len(published) == 1


def test_proposed_requirements_are_kept_and_labelled(world):
    hchb = world.jobs["J1"].get("req.hchb")
    assert {(f.value, f.qualifier) for f in hchb} == {("required", None), ("trainable", PROPOSED)}
    exp = world.jobs["J1"].get("min_experience")
    assert {(f.value["years"], f.qualifier) for f in exp} == {(2, None), (1, PROPOSED)}


def test_facts_are_never_overwritten(world):
    starts = [f.value for f in world.candidates["R07"].get("start_date")]
    assert starts == ["2026-12-01", "2026-12-08"]
