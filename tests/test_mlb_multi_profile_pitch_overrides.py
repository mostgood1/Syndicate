"""Every profile's pitch-model override default must be `off` or a file that exists.

A missing path is silently worse than `off`: `_load_jsonish` returns None (overrides = {})
AND the explicit `--pitch-model-overrides` flag suppresses daily_update's forward-tuning
default, so the profile runs PitchModelConfig class defaults. That is how the game-ROI
profile ran uncalibrated through 2026-10-09 (lane mlb-game-profile-pitch-config).
"""
import re
from pathlib import Path

VENDOR = Path(__file__).resolve().parents[1] / "vendor" / "mlb_bettingv2"
SRC = (VENDOR / "tools" / "daily_update_multi_profile.py").read_text(encoding="utf-8")


def _defaults():
    pat = re.compile(r'"--(game|pitcher|hitter)-pitch-model-overrides",\s*(?:#[^\n]*\n\s*)*default="([^"]*)"')
    return dict(pat.findall(SRC))


def test_all_three_profile_defaults_are_found():
    assert set(_defaults()) == {"game", "pitcher", "hitter"}


def test_each_default_is_off_or_an_existing_file():
    for profile, value in _defaults().items():
        if value.strip().lower() in ("off", "false", "0", "none", "null", ""):
            continue
        assert (VENDOR / value).is_file(), f"{profile} profile default points at a missing file: {value}"


def test_game_profile_uses_forward_tuning():
    assert _defaults()["game"] == "off"
