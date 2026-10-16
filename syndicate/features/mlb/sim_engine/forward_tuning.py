from __future__ import annotations
_ENGINE_FILE = str(__import__("pathlib").Path(__file__).resolve().parents[4].joinpath('engines', 'mlb', 'sim_engine', 'forward_tuning.py'))  # EDIT: this module's path under the engines/mlb DATA root (same depth as vendor/mlb_bettingv2)

from datetime import date, datetime
from pathlib import Path


_ROOT = Path(_ENGINE_FILE).resolve().parents[1]
FORWARD_TUNING_START_DATE = date(2026, 4, 14)
FORWARD_PITCH_MODEL_OVERRIDES_PATH = (
    _ROOT / "data" / "tuning" / "pitch_model_overrides" / "forward_start_2026_04_14_v1.json"
).resolve()
FORWARD_MANAGER_PITCHING_OVERRIDES_PATH = (
    _ROOT / "data" / "tuning" / "manager_pitching_overrides" / "forward_start_2026_04_14_v1.json"
).resolve()
# Keep explicit CLI opt-in available, but default forward runs away from BvP HR
# until the matchup path proves net value on a cleaner holdout.
FORWARD_BVP_MATCHUP_MODE = "off"
FORWARD_BVP_MIN_PA = 6


def parse_target_date(value: str) -> date:
    text = str(value or "").strip()
    if not text:
        raise ValueError("date value is required")
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        return datetime.strptime(text, "%Y-%m-%d").date()


def should_use_forward_tuning(date_str: str) -> bool:
    return parse_target_date(str(date_str)) >= FORWARD_TUNING_START_DATE
