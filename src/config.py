"""Load and validate a matching config (configs/*.yaml)."""
from __future__ import annotations

from pathlib import Path

import yaml

CONFIG_DIR = Path(__file__).resolve().parent.parent / "configs"

WEIGHT_KEYS = {"requirements", "experience", "logistics", "preferred"}
TIE_BREAKERS = {"fewer_open_questions", "earliest_start", "more_independent_evidence", "freshest_evidence"}
PROTECTED = {"name", "first_name", "last_name", "age", "date_of_birth", "gender", "sex", "race",
             "ethnicity", "religion", "nationality", "national_origin", "disability", "marital_status",
             "pregnancy", "veteran_status", "sexual_orientation", "email"}


class ConfigError(ValueError):
    pass


def load_config(path: str | Path = CONFIG_DIR / "default.yaml") -> dict:
    cfg = yaml.safe_load(Path(path).read_text())
    validate(cfg)
    return cfg


def validate(cfg: dict) -> None:
    weights = cfg.get("weights", {})
    if set(weights) != WEIGHT_KEYS:
        raise ConfigError(f"weights must be exactly {sorted(WEIGHT_KEYS)}, got {sorted(weights)}")
    if any(w < 0 for w in weights.values()) or sum(weights.values()) <= 0:
        raise ConfigError("weights must be non-negative and not all zero")
    for tb in cfg.get("tie_breakers", []):
        if tb in PROTECTED:
            raise ConfigError(f"tie-breaker {tb!r} is a protected attribute and may never be used")
        if tb not in TIE_BREAKERS:
            raise ConfigError(f"unknown tie-breaker {tb!r}; allowed: {sorted(TIE_BREAKERS)}")
    for key in ("thresholds", "tie_margin", "experience_cap_years", "duplicate_similarity"):
        if key not in cfg:
            raise ConfigError(f"missing config key {key!r}")


def available_configs() -> list[Path]:
    return sorted(CONFIG_DIR.glob("*.yaml"))
