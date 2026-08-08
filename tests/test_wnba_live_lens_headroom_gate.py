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


def test_gate_is_calibrated_to_the_stage_it_currently_guards():
    """RE-CALIBRATED 2026-08-08: 1200MB -> 300MB.

    The original 1200MB was the measured 1,062MB plus margin, and it was
    honestly derived -- from a builder that `44008605` deleted EIGHT MINUTES
    LATER. The guarded step is now a JSON read plus a rank-card pass, measured
    across 7/7 refresh-worker ticks at +69.6 to +153.5MB.

    The assertion that used to live here (`>= 1062MB`, `!= MLB's number`) was
    pinning the old cost, so it would have failed the fix rather than caught the
    drift. What is worth pinning is the RELATIONSHIP to the measurement: high
    enough to cover the worst observed build, low enough that a 4Gi service
    running a resident sim can still satisfy it.
    """
    required = live_lens_loop._wnba_live_lens_min_headroom_bytes()
    assert required >= 154 * 1024 * 1024, "below the worst measured build (+153.5MB)"
    assert required <= 600 * 1024 * 1024, "a bar this high cannot be met beside a resident MLB sim"


def test_gate_matching_mlb_is_convergence_not_a_copy():
    """MLB's gate is also 300MB, and this file's history warns loudly against
    copying it. They match because two builders were separately measured into
    the same neighbourhood (MLB 0-13MB, WNBA 69-154MB) and given the same
    worst-measured-plus-margin treatment -- so pin the SOURCE of the number, not
    its inequality to MLB's. If WNBA's builder gets expensive again, re-measure;
    do not reach for MLB's constant."""
    assert "300" in (live_lens_loop._wnba_live_lens_min_headroom_bytes.__doc__ or "")
    assert "153.5" in (live_lens_loop._wnba_live_lens_min_headroom_bytes.__doc__ or "")


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
