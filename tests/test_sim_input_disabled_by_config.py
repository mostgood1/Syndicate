"""DISABLED != BROKEN in the input checklist. `#440`.

WHY. On 2026-08-20 the checklist reported 15 failures. FIVE were the
`vs_pitcher_*` BVP fields, zero because `FORWARD_BVP_MATCHUP_MODE = "off"` -- a
deliberate modelling decision with a stated re-entry condition ("until the
matchup path proves net value on a cleaner holdout"), not a breakage. They were
reported identically to the four GENUINE defects found that same day, and that
cost a session half an hour tracing a non-bug.

The critical property, pinned by `test_flipping_the_switch_restores_failure`:
the exemption is READ FROM THE REAL CONFIG. A hardcoded list would keep excusing
these fields long after BVP was switched back on -- which is the same
neutral-default failure mode this checklist exists to catch.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
VENDOR = REPO / "vendor" / "mlb_bettingv2"
for _p in (str(REPO), str(VENDOR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

BVP_FIELDS = {"vs_pitcher_hr_mult", "vs_pitcher_k_mult", "vs_pitcher_bb_mult",
              "vs_pitcher_inplay_mult", "vs_pitcher_history"}


def _mod():
    spec = importlib.util.spec_from_file_location(
        "_cl_mod", REPO / "scripts" / "sim_input_checklist.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules["_cl_mod"] = m
    spec.loader.exec_module(m)
    return m


def test_bvp_fields_are_reported_disabled_while_the_switch_is_off():
    out = _mod()._disabled_by_config("2026-08-20")
    assert BVP_FIELDS <= set(out), f"missing: {BVP_FIELDS - set(out)}"
    for f in BVP_FIELDS:
        assert "FORWARD_BVP_MATCHUP_MODE" in out[f], "the reason must name the actual switch"


def test_flipping_the_switch_restores_failure(monkeypatch):
    """THE test. Turn BVP on and these fields must go back to ordinary
    accounting -- otherwise the exemption outlives the reason for it."""
    import sim_engine.forward_tuning as ft
    monkeypatch.setattr(ft, "FORWARD_BVP_MATCHUP_MODE", "on", raising=False)
    out = _mod()._disabled_by_config("2026-08-20")
    assert not (BVP_FIELDS & set(out)), (
        "BVP is ON but the fields are still exempted -- a stale exemption hides "
        "a real breakage, which is worse than the noise it was meant to remove")


def test_a_date_before_forward_tuning_is_not_exempted():
    """Forward tuning only applies from its start date; before it, the switch
    does not govern and an empty field is NOT explained by this config."""
    m = _mod()
    import sim_engine.forward_tuning as ft
    before = ft.FORWARD_TUNING_START_DATE.replace(year=ft.FORWARD_TUNING_START_DATE.year - 1)
    assert not (BVP_FIELDS & set(m._disabled_by_config(before.isoformat())))


def test_unknown_date_does_not_crash_the_checklist():
    """Never fatal: the audit must survive a bad date rather than take the
    sim job down with it."""
    assert isinstance(_mod()._disabled_by_config("not-a-date"), dict)


def test_the_corrected_comment_no_longer_claims_a_production_number():
    """The old comment cited "13.9%" beside fields that read 0% in production;
    that number came from --simulate-rebuild, which bypasses the `bvp_hr_on`
    gate. True-but-misleading is the shape that sends the next reader hunting a
    regression that never happened."""
    src = (REPO / "scripts" / "sim_input_checklist.py").read_text(encoding="utf-8")
    i = src.index("BVP is SPARSE BY NATURE")
    window = src[i:i + 1400]
    assert "13.9%" not in window or "NOT A PRODUCTION NUMBER" in window
