"""Smoke test: every source file the project depends on is present and readable."""
import json
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"

JSON_FILES = [
    "ats_response.json",
    "vms_response.json",
    "client_database_dump.json",
    "our_system_response.json",
    "supplemental_source_packet.json",
]
RESUMES = [f"C{i}-CV-FULL.txt" for i in range(1, 5)]


def test_json_sources_parse():
    for name in JSON_FILES:
        json.loads((DATA / name).read_text())


def test_resumes_present():
    for name in RESUMES:
        assert (DATA / name).read_text().strip()
