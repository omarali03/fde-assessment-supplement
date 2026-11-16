"""Print one candidate or job from the 18:00 snapshot: `python -m src.show C1`."""
from __future__ import annotations

import sys

from src.model import Entity
from src.snapshot import load_snapshot


def render(entity: Entity, aliases: list[str]) -> str:
    lines = [f"=== {entity.id}   aliases: {', '.join(aliases)}"]
    for name in sorted(entity.facts):
        lines.append(f"  {name}:")
        for group in entity.evidence_groups(name):
            head = group[0]
            copies = sorted({f.source_id for f in group} - {head.source_id})
            line = f"    - {head}"
            if copies:
                line += f"   (same evidence also in: {', '.join(copies)})"
            lines.append(line)
            lines.append(f'        quote: "{head.quote}"')
    conflicts = entity.conflicts()
    if conflicts:
        lines.append("  CONFLICTS (all kept):")
        for name, groups in conflicts.items():
            lines.append(f"    {name}: " + "  |  ".join(str(g[0]) for g in groups))
    return "\n".join(lines)


def main(ids: list[str]) -> None:
    world = load_snapshot()
    for eid in ids or ["C1"]:
        entity = world.candidates.get(eid) or world.jobs.get(eid)
        if entity is None:
            sys.exit(f"unknown id {eid}")
        print(render(entity, world.idmap.aliases(eid)))


if __name__ == "__main__":
    main(sys.argv[1:])
