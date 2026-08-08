"""WNBA's live-lens builder was the last ungated one, and the most expensive.

MEASURED on live-odds-worker (2Gi), 2026-08-08:

    03:03:52   507.0MB   live_lens_tick_after_build_mlb
    03:03:54   581.5MB   live_lens_tick_after_build_nba
    03:04:01  1644.1MB   live_lens_tick_after_build_wnba   <- +1,062MB in ONE step

That OOM-killed the container and then crash-looped it (boots 03:07:56, 03:09:09,
03:10:31, 03:12:07).

WHY IT WAS UNGATED, and why the reasoning was wrong rather than careless: the
gate comment argued WNBA's live win-probability is "a clock parse + one logistic
call + one blend, not a sampling loop", so its cost should be negligible. That is
TRUE of `_wnba_live_margin_win_prob`. It is irrelevant, because
`build_live_lens_snapshot` calls `build_cards_page_context` -- the ENTIRE WNBA
cards page -- on every tick. The cheap computation is bolted to an expensive
build, and only the cheap part was reasoned about.

The gate is a tourniquet. The real fix is that a live-lens tick should not
rebuild a whole board page.
"""

from __future__ import annotations

import os
from unittest.mock import patch

from syndicate.features.shared import live_lens_loop


def test_wnba_is_gated_at_all():
    """It was the ONLY builder in the tick with no headroom check."""
    import inspect

    source = inspect.getsource(live_lens_loop._run_live_lens_tick_for_sport)
    assert 'sport == "wnba"' in source, "WNBA builder is unguarded again"


def test_gate_is_calibrated_from_the_measurement_not_copied():
    """This file's own history says: calibrate from measurement, never copy
    MLB's number. 1200MB = the measured 1,062MB plus margin."""
    assert live_lens_loop._wnba_live_lens_min_headroom_bytes() >= 1062 * 1024 * 1024
    assert live_lens_loop._wnba_live_lens_min_headroom_bytes() != live_lens_loop._mlb_live_lens_min_headroom_bytes()


def test_gate_is_overridable_by_env():
    with patch.dict(os.environ, {"SYNDICATE_WNBA_LIVE_LENS_MIN_HEADROOM_BYTES": "12345"}, clear=False):
        assert live_lens_loop._wnba_live_lens_min_headroom_bytes() == 12345


def test_gate_can_be_disabled():
    with patch.dict(os.environ, {"SYNDICATE_WNBA_LIVE_LENS_MEMORY_GATE_ENABLED": "false"}, clear=False):
        assert live_lens_loop._wnba_live_lens_headroom_snapshot() is None


def test_insufficient_headroom_skips_the_build_and_says_why():
    """A skipped tick must be attributable. A gate that fires silently cannot be
    told apart from a builder that never ran."""
    with patch.object(
        live_lens_loop, "_wnba_live_lens_headroom_snapshot",
        return_value={"sufficient": False, "available_bytes": 1},
    ), patch.dict(live_lens_loop._LIVE_LENS_BUILDERS, {"wnba": lambda d: (_ for _ in ()).throw(AssertionError("built anyway"))}):
        meta = live_lens_loop._run_live_lens_tick_for_sport("wnba", "2026-08-08")

    assert meta["skipped"] is True
    assert meta["reason"] == "low_headroom"


def test_sufficient_headroom_still_builds():
    """The gate must not become a permanent off-switch."""
    with patch.object(
        live_lens_loop, "_wnba_live_lens_headroom_snapshot",
        return_value={"sufficient": True, "available_bytes": 9 * 1024 ** 3},
    ), patch.dict(live_lens_loop._LIVE_LENS_BUILDERS, {"wnba": lambda d: {"games": []}}), \
         patch.dict(live_lens_loop._LIVE_LENS_VALIDATORS, {"wnba": lambda s: True}):
        meta = live_lens_loop._run_live_lens_tick_for_sport("wnba", "2026-08-08")

    assert meta.get("reason") != "low_headroom"
