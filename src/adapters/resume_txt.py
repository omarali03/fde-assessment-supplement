"""Adapter for the C1–C4 *-CV-FULL.txt résumé files.

Each file is another format of the matching JSON résumé entry (same evidence), so it is
linked to it via related_source_ids and to the original extract via rendition_of.
"""
from __future__ import annotations

import re
from pathlib import Path

from src.adapters import Bundle
from src.model import IdMap, SourceDoc

SYSTEM = "resume_txt"
HEADER = re.compile(r"Candidate: (\S+) \| Received: (\S+) \| Expanded rendition of: (\S+)")


def load(data_dir: Path, idmap: IdMap) -> Bundle:
    out = Bundle()
    for path in sorted(Path(data_dir).glob("C*-CV-FULL.txt")):
        lines = path.read_text().splitlines()
        header_idx = next(i for i, line in enumerate(lines) if HEADER.search(line))
        ext_id, received, rendition_of = HEADER.search(lines[header_idx]).groups()
        cid = idmap.resolve("ats", ext_id)
        body = "\n".join(lines[header_idx + 1:]).strip()
        out.candidate(cid).docs.append(
            SourceDoc(path.name, SYSTEM, "candidate", cid, "resume", received, body,
                      rendition_of=rendition_of, related_source_ids=(path.stem,)))
    return out
