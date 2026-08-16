"""#250 -- the hydrated overview loop must stop between sports when the
container is about to be OOM-killed.

The regression these cover, in full: refresh-worker was SIGKILLed at 4GiB every
~3 minutes. `_build_candidate_pool` checks memory headroom immediately before
`build_intelligence_overview` and immediately after it, so the whole eight-sport
hydrated pass is ONE opaque stage to that circuit breaker. Measured on a cold
boot 2026-08-07 (anon 84MB at BOOTED):

    04:49:45  post_pull_hot_artifacts   2192.7MB   <- pre-stage guard cleared
    04:51:04  nhl   overview_sport_end  3532.9MB
    04:51:08  soccer board_contract     4095.8MB  100.0%  -> SIGKILL

Raising the caller's floor could not fix that: the kill happens ninety seconds
INSIDE the stage the floor guards.
"""

from __future__ import annotations

from unittest.mock import patch

from syndicate.features import intelligence as intelligence_module


BYTES_PER_MB = 1024 * 1024


def _snapshot(*, headroom_mb: float, min_required_mb: float) -> dict:
    return {
        "current_mb": 4096.0 - headroom_mb,
        "max_mb": 4096.0,
        "headroom_mb": headroom_mb,
        "min_required_mb": min_required_mb,
        "sufficient": headroom_mb >= min_required_mb,
    }


def test_per_sport_floor_covers_the_most_expensive_sport():
    # The floor must be the cost of the WORST sport, not the average, because
    # MLB runs first and is in a different class. Shipped first at 1000MB,
    # sized off soccer/nhl; it fired exactly as designed before soccer and the
    # worker kept dying, because MLB had already spent the budget:
    #     05:10:57  post_pull_hot_artifacts   993.8MB container
    #     05:12:10  mlb board_contract       3922.6MB  95.8%   -> +2.9GB
    # Pinned so the floor cannot drift back under the measured cost of the
    # sport it is supposed to stop.
    floor_mb = intelligence_module._OVERVIEW_MIN_SAFE_HEADROOM_BYTES / BYTES_PER_MB
    measured_mlb_hydrated_cost_mb = 2928.8
    assert floor_mb >= measured_mlb_hydrated_cost_mb


def test_headroom_exhausted_is_false_when_unmeasurable():
    # Local dev has no cgroups. A missing measurement must not silently
    # truncate the board everywhere that is not Render.
    with patch(
        "syndicate.features.shared.memory_observability.memory_headroom_snapshot",
        return_value=None,
    ):
        assert (
            intelligence_module._overview_headroom_exhausted(
                next_sport="soccer", sports_done=7, sports_total=8
            )
            is False
        )


def test_headroom_exhausted_is_false_when_the_check_itself_raises():
    with patch(
        "syndicate.features.shared.memory_observability.memory_headroom_snapshot",
        side_effect=RuntimeError("boom"),
    ):
        assert (
            intelligence_module._overview_headroom_exhausted(
                next_sport="soccer", sports_done=7, sports_total=8
            )
            is False
        )


def test_headroom_exhausted_is_true_when_below_floor(capfd):
    with patch(
        "syndicate.features.shared.memory_observability.memory_headroom_snapshot",
        return_value=_snapshot(headroom_mb=943.0, min_required_mb=1000.0),
    ):
        assert (
            intelligence_module._overview_headroom_exhausted(
                next_sport="soccer", sports_done=7, sports_total=8
            )
            is True
        )
    # The reason must be readable in Render's collector, hence print(flush=True)
    # rather than logger.info -- see #37.
    assert "OVERVIEW_STOPPED_FOR_MEMORY" in capfd.readouterr().out


def _floor_aware_snapshot(headroom_mb: float):
    """A snapshot that answers `sufficient` FROM THE FLOOR IT WAS HANDED.

    The point of these tests is WHICH floor the guard passes in, and a stub that
    ignores its argument cannot see that -- it would pass identically whether the
    guard asked for 1500MB or 3000MB, which is the exact bug being pinned.
    """

    def _snapshot_for(min_required_bytes: int) -> dict:
        min_required_mb = min_required_bytes / BYTES_PER_MB
        return _snapshot(headroom_mb=headroom_mb, min_required_mb=min_required_mb)

    return _snapshot_for


def test_streamed_floor_applies_to_the_cheap_sports_and_expensive_to_mlb():
    # `#387` 2026-08-14. Sizing evidence in the constant's comment: five sports
    # hydrated in 171ms for +1.7MB, against MLB's +1543MB in the same pass.
    for slug in ("nba", "wnba", "nfl", "ncaaf", "ncaab", "nhl", "soccer"):
        floor, label = intelligence_module._overview_headroom_floor_bytes(slug)
        assert label == "streamed"
        assert floor == intelligence_module._OVERVIEW_MIN_SAFE_HEADROOM_STREAMED_BYTES
    floor, label = intelligence_module._overview_headroom_floor_bytes("mlb")
    assert label == "expensive"
    assert floor == intelligence_module._OVERVIEW_MIN_SAFE_HEADROOM_BYTES


def test_an_unknown_sport_takes_the_expensive_floor():
    # An unknown cost is not a cheap cost. A new module, a renamed slug or a
    # typo must not fall through onto the relaxed branch.
    for slug in ("", "   ", "cricket", "MLB_PROPS", None):
        floor, label = intelligence_module._overview_headroom_floor_bytes(slug)  # type: ignore[arg-type]
        assert label == "expensive", slug
        assert floor == intelligence_module._OVERVIEW_MIN_SAFE_HEADROOM_BYTES


def test_slug_matching_is_case_and_whitespace_insensitive():
    assert intelligence_module._overview_headroom_floor_bytes(" Soccer ")[1] == "streamed"


def test_the_production_truncation_no_longer_happens(capfd):
    # THE REGRESSION THIS EXISTS FOR, at the measured numbers. Twice on
    # 2026-08-14 the stream stopped after MLB with headroom 2587.3MB against a
    # 3000MB floor, producing BOARD_OVERVIEW_READY sports=1 where every build in
    # the preceding three hours read sports=8.
    with patch(
        "syndicate.features.shared.memory_observability.memory_headroom_snapshot",
        side_effect=_floor_aware_snapshot(2587.3),
    ):
        assert (
            intelligence_module._overview_headroom_exhausted(
                next_sport="nba", sports_done=1, sports_total=8
            )
            is False
        )
    assert "OVERVIEW_STOPPED_FOR_MEMORY" not in capfd.readouterr().out


def test_the_gate_in_front_of_mlb_is_not_relaxed(capfd):
    # Same headroom, first sport. MLB took the process from anon 522MB to a
    # 4096MB SIGKILL in 25 seconds on 2026-08-14; that variance is unexplained,
    # so this branch keeps the full margin.
    with patch(
        "syndicate.features.shared.memory_observability.memory_headroom_snapshot",
        side_effect=_floor_aware_snapshot(2587.3),
    ):
        assert (
            intelligence_module._overview_headroom_exhausted(
                next_sport="mlb", sports_done=0, sports_total=8
            )
            is True
        )
    out = capfd.readouterr().out
    assert "OVERVIEW_STOPPED_FOR_MEMORY" in out
    # Two floors now produce this one message; without the label a relaxed
    # refusal reads identically to a strict one.
    assert "floor=expensive" in out and "floor_mb=3000" in out


def test_a_cheap_sport_still_stops_when_it_is_genuinely_tight(capfd):
    # Relaxed is not absent. Below 1500MB the cheap branch must still refuse.
    with patch(
        "syndicate.features.shared.memory_observability.memory_headroom_snapshot",
        side_effect=_floor_aware_snapshot(900.0),
    ):
        assert (
            intelligence_module._overview_headroom_exhausted(
                next_sport="soccer", sports_done=7, sports_total=8
            )
            is True
        )
    assert "floor=streamed" in capfd.readouterr().out


def test_the_streamed_floor_stays_under_the_expensive_one_and_over_the_measured_cost():
    streamed_mb = intelligence_module._OVERVIEW_MIN_SAFE_HEADROOM_STREAMED_BYTES / BYTES_PER_MB
    expensive_mb = intelligence_module._OVERVIEW_MIN_SAFE_HEADROOM_BYTES / BYTES_PER_MB
    assert streamed_mb < expensive_mb
    # Whole EIGHT-sport hydrated pass on the pre-cutover code moved anon
    # 444.6 -> 804.2MB. The streamed floor must cover that with room to spare.
    assert streamed_mb >= 2 * 359.6


def _run_overview(*, skip_game_hydration: bool, headroom_mb: float):
    sports = [{"slug": slug} for slug in ("mlb", "nba", "wnba", "nhl", "soccer")]
    with patch.object(intelligence_module, "_configured_syndicate_sports", return_value=sports), patch.object(
        intelligence_module, "_effective_date", return_value="2026-08-07"
    ), patch.object(
        intelligence_module,
        "_build_sport_overview",
        side_effect=lambda sport, *a, **k: {"slug": sport["slug"]},
    ), patch.object(
        intelligence_module, "_intel_trace", lambda *a, **k: None
    ), patch(
        "syndicate.features.shared.memory_observability.memory_headroom_snapshot",
        return_value=_snapshot(headroom_mb=headroom_mb, min_required_mb=1000.0),
    ):
        return intelligence_module.build_intelligence_overview(
            selected_date="2026-08-07",
            force_refresh=True,
            skip_game_hydration=skip_game_hydration,
        )


def test_hydrated_pass_stops_before_the_first_sport_that_would_not_fit():
    # Headroom below the floor for every check, so it stops immediately and
    # returns an empty-but-valid overview rather than being SIGKILLed.
    assert _run_overview(skip_game_hydration=False, headroom_mb=943.0) == []


def test_hydrated_pass_builds_every_sport_when_there_is_room():
    built = _run_overview(skip_game_hydration=False, headroom_mb=3000.0)
    assert [row["slug"] for row in built] == ["mlb", "nba", "wnba", "nhl", "soccer"]


def test_fingerprint_pass_is_never_truncated():
    # skip_game_hydration=True runs all eight sports in ~2s for a few MB, and
    # its output keys the caller's cache. A PARTIAL fingerprint would key that
    # cache off a short sport list and serve the wrong snapshot -- a worse
    # failure than the OOM being prevented. Same starved headroom as the
    # stops-immediately test above; this one must still build everything.
    built = _run_overview(skip_game_hydration=True, headroom_mb=943.0)
    assert [row["slug"] for row in built] == ["mlb", "nba", "wnba", "nhl", "soccer"]
