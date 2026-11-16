"""Recruiter view of the matcher: `make app` (streamlit run app.py).

Everything shown is a recommendation. The app never contacts, submits or writes back to any system.
"""
from __future__ import annotations

from pathlib import Path

import streamlit as st

from src.config import available_configs, load_config
from src.matcher import NOTICE, PASS, TIERS, JobResult, Match, Matcher, requirement_versions
from src.model import PROPOSED, Entity
from src.replay import STAGES, world_at

ASSUMPTIONS = Path(__file__).parent / "docs" / "ASSUMPTIONS.md"
STATUS_ICON = {"pass": "✅", "fail": "⛔", "unknown": "❓", "meets": "✅"}
TIER_ICON = {"Strong": "🟢", "Conditional": "🟡", "Needs clarification": "🟠", "Blocked": "⛔"}


# --------------------------------------------------------------------------- data (cached per config + stage)

@st.cache_resource(show_spinner="Loading sources and matching…")
def load(config_path: str, stage: int):
    cfg = load_config(config_path)
    world, applied = world_at(stage)
    matcher = Matcher(world, cfg)
    results = {jid: matcher.match_job(jid) for jid in world.jobs}
    return cfg, world, applied, results


def summary(result: JobResult) -> dict[str, tuple]:
    return {m.candidate_id: (m.tier, m.rank, m.score, m.next_action["text"]) for m in result.matches}


# --------------------------------------------------------------------------- small renderers

def fact_rows(entity: Entity, fields: list[str] | None = None) -> list[dict]:
    rows = []
    for name in fields or sorted(entity.facts):
        for group in entity.evidence_groups(name):
            head = group[0]
            copies = sorted({f.source_id for f in group} - {head.source_id})
            rows.append({"field": name, "value": head.text(), "source": head.source_label,
                         "date": head.as_of[:10], "status": head.evidence_status,
                         "qualifier": head.qualifier or "", "quote": head.quote,
                         "same evidence also in": ", ".join(copies)})
    return rows


def show_conflicts(entity: Entity) -> None:
    conflicts = entity.conflicts()
    if not conflicts:
        return
    st.markdown("**Conflicting sources (all kept, none overwritten)**")
    for name, groups in conflicts.items():
        st.warning(f"**{name}**: " + "  ·  ".join(f"{g[0]} – “{g[0].quote}”" for g in groups))


def show_match(m: Match) -> None:
    action = m.next_action
    box = st.error if action["type"].startswith("blocked") else st.info
    box(f"**Next action:** {action['text']}\n\n_{action['notice']}_")

    if m.labels:
        st.markdown(" ".join(f"`{lab}`" for lab in m.labels))
    if m.duplicate_group:
        st.caption("Possible duplicate group (records are never merged): " + ", ".join(m.duplicate_group))

    left, right = st.columns(2)
    with left:
        st.markdown("**Gates**")
        st.dataframe([{"": STATUS_ICON.get(g.status, ""), "gate": g.name, "status": g.status,
                       "mismatch": g.mismatch or "", "reason": g.reason} for g in m.gates],
                     hide_index=True, use_container_width=True)
        for g in m.gates:
            if g.details:
                st.caption(f"{g.name}: " + " · ".join(g.details))
    with right:
        st.markdown(f"**Score {m.score:.3f}** (always against published requirements)")
        st.dataframe([{"component": k, "value": v["value"], "weight": v["weight"], "points": v["points"]}
                      for k, v in m.breakdown.items()], hide_index=True, use_container_width=True)

    for version, checks in m.checks.items():
        title = "Published requirements" if version == "published" else f"Proposed requirements ({PROPOSED})"
        met = m.meets_published if version == "published" else m.meets_proposed
        st.markdown(f"**{title}** – {'met' if met else 'not met'}")
        st.dataframe([{"": STATUS_ICON.get(ch.state, "❓"), "requirement": ch.name, "level": ch.level,
                       "state": ch.state, "detail": ch.detail,
                       "evidence": ", ".join(sorted({f.source_id for f in ch.evidence}))} for ch in checks],
                     hide_index=True, use_container_width=True)

    if m.open_questions:
        st.markdown("**Open questions**")
        for q in m.open_questions:
            st.markdown(f"- {q}")
    for n in m.notes:
        st.caption(f"Note: {n}")
    if m.suggested_updates:
        st.markdown("**Suggested field updates** – for recruiter review, never written back")
        st.dataframe([{k: s[k] for k in ("system", "field", "current", "suggested", "reason", "evidence")}
                      for s in m.suggested_updates], hide_index=True, use_container_width=True)


# --------------------------------------------------------------------------- tabs

def matches_tab(world, results, previous) -> None:
    labels = {f"{jid} – {world.jobs[jid].latest('title').value}": jid for jid in results}
    jid = labels[st.selectbox("Job", list(labels))]
    job, result = world.jobs[jid], results[jid]

    loc, start, pay = (job.latest(k) for k in ("location", "start_date", "pay"))
    facts = [f"📍 {loc.value['city']}, {loc.value['state']}" if loc else "",
             f"start {start.value}" if start else "",
             f"pay ${pay.value['amount']:,}/{pay.value['unit']}" if pay else "",
             f"status {job.latest('status').value}"]
    st.caption("  ·  ".join(x for x in facts if x))

    if result.excluded_reason:
        st.warning(f"Not matched: {result.excluded_reason}")
        return
    for q in result.job_questions:
        st.warning(q)

    with st.expander("Job requirements – published vs proposed"):
        versions = requirement_versions(job)
        names = sorted(set().union(*versions.values()))
        st.dataframe([{"requirement": n,
                       **{v: (versions[v][n].text() if n in versions[v] else "") for v in versions},
                       "source": ", ".join(sorted({versions[v][n].source_id for v in versions if n in versions[v]}))}
                      for n in names], hide_index=True, use_container_width=True)
        if "proposed" in versions:
            st.caption(f"Proposed = {PROPOSED}. Candidates meeting only the proposed version are Conditional.")

    if previous is not None:
        before = summary(previous[jid]) if jid in previous and not previous[jid].excluded_reason else {}
        changes = []
        for cid, (tier, rnk, score, action) in summary(result).items():
            old = before.get(cid)
            if old != (tier, rnk, score, action):
                changes.append({"candidate": cid,
                                "tier": f"{old[0]} → {tier}" if old and old[0] != tier else tier,
                                "rank": f"#{old[1]} → #{rnk}" if old else f"new #{rnk}",
                                "score": f"{old[2]:.3f} → {score:.3f}" if old else f"{score:.3f}",
                                "next action changed": "yes" if not old or old[3] != action else ""})
        if changes:
            st.markdown("**Changed since the previous stage**")
            st.dataframe(changes, hide_index=True, use_container_width=True)

    st.markdown("**Ranking**")
    st.dataframe([{"rank": f"#{m.rank}" + (" =" if m.tied_with else ""), "candidate": m.candidate_id,
                   "tier": f"{TIER_ICON[m.tier]} {m.tier}", "score": m.score,
                   "tied with": ", ".join(m.tied_with), "open questions": len(m.open_questions),
                   "next action": m.next_action["text"]} for m in result.matches],
                 hide_index=True, use_container_width=True)
    if result.not_eligible:
        st.caption("Not eligible (profession): " + ", ".join(f"{c} – {r}" for c, r in result.not_eligible))

    for tier in TIERS:
        for m in (m for m in result.matches if m.tier == tier):
            tie = f" (tied with {', '.join(m.tied_with)})" if m.tied_with else ""
            with st.expander(f"{TIER_ICON[tier]} #{m.rank} {m.candidate_id} – {tier} – {m.score:.3f}{tie}"):
                show_match(m)


def evidence_tab(world) -> None:
    kind = st.radio("Show", ["Candidate", "Job"], horizontal=True)
    pool = world.candidates if kind == "Candidate" else world.jobs
    eid = st.selectbox(kind, list(pool))
    entity = pool[eid]
    st.caption("Aliases: " + (", ".join(world.idmap.aliases(eid)) or "none"))
    show_conflicts(entity)
    st.markdown("**Evidence** – one row per independent source; renditions and repeating notes are grouped")
    st.dataframe(fact_rows(entity), hide_index=True, use_container_width=True)
    with st.expander(f"Source documents ({len(entity.docs)})"):
        for d in sorted(entity.docs, key=lambda d: (d.as_of, d.source_id)):
            extra = f" · rendition of {d.rendition_of}" if d.rendition_of else ""
            st.markdown(f"**{d.source_id}** · {d.kind} · {d.as_of[:16].replace('T', ' ')}{extra}")
            st.text(d.text)


def decisions_tab(world) -> None:
    text = ASSUMPTIONS.read_text().strip() if ASSUMPTIONS.exists() else ""
    if not text:
        st.info("docs/ASSUMPTIONS.md is empty. Open decisions will appear here once it is written.")
    else:
        sections = ["## " + s for s in text.split("\n## ")[1:]]
        open_ones = [s for s in sections if "status:** open" in s.lower() or "status: open" in s.lower()]
        if open_ones:
            st.markdown(f"**{len(open_ones)} open decision(s)**")
            for s in open_ones:
                st.markdown(s)
                st.divider()
        with st.expander("Full ASSUMPTIONS.md", expanded=not open_ones):
            st.markdown(text)
    st.markdown("**Discovery notes (source packet)**")
    for n in world.discovery_notes:
        st.caption(f"{n['source_id']} · {n['speaker_role']}: “{n['text']}”")


# --------------------------------------------------------------------------- page

def main() -> None:
    st.set_page_config(page_title="Candidate matching", page_icon="🩺", layout="wide")
    st.title("Candidate–job matching")
    st.warning(NOTICE + " Nothing here is written back to any source system.")

    with st.sidebar:
        configs = {p.stem: str(p) for p in available_configs()}
        config_path = configs[st.selectbox("Config", list(configs))]
        stage_labels = [label for label, _ in STAGES]
        stage = stage_labels.index(st.radio("Timeline (2026-11-07)", stage_labels))
        cfg, world, applied, results = load(str(config_path), stage)
        st.caption(f"Weights: " + ", ".join(f"{k} {v}" for k, v in cfg["weights"].items()))
        st.caption(f"Strong ≥ {cfg['thresholds']['strong_min_score']} · tie margin {cfg['tie_margin']} · "
                   f"tie-breakers: {', '.join(cfg['tie_breakers'])}")
        if applied:
            st.markdown("**Events replayed**")
        for event, facts in applied:
            st.markdown(f"`{event.occurred_at[11:16]}` **{event.event_id}** → {event.subject_id}")
            for f in facts:
                if f.field in ("start_date", "location_pref", "pay_min", "no_contact_until") or f.field.startswith("req."):
                    st.caption(f"+ {f.field}: {f.text()} – “{f.quote}”")

    previous = load(str(config_path), stage - 1)[3] if stage > 0 else None
    tabs = st.tabs(["Matches", "Evidence", "Open decisions"])
    with tabs[0]:
        matches_tab(world, results, previous)
    with tabs[1]:
        evidence_tab(world)
    with tabs[2]:
        decisions_tab(world)


main()
