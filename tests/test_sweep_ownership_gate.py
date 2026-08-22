"""The odds sweep must honour the ownership flags the tick already honours.

WHY THIS EXISTS. Measured in production 2026-08-17:

    live-odds-worker  ODDS_SWEEP_OUTCOME: ZERO across 30h,
                      >=100 PREGAME_CADENCE_SKIPPED per 24h
                      ACTIVE_SPORTS=mlb,wnba,soccer  MLB_REFRESH_TICK_OWNER=true

The designated owner was skipping continuously and sweeping nothing, because
`_live_refresh_loop_effective_sports` fell back to "every season-active sport"
whenever `SYNDICATE_LIVE_ODDS_REFRESH_SPORTS` was unset and read NEITHER
`SYNDICATE_ACTIVE_SPORTS` nor the per-sport ownership flags. `#129` had already
fought this race and recorded live-odds-worker as "the sole MLB odds-refresh
owner again, not just nominally excluded" -- and the sweep path never read that.

THE GATE IS DEPLOYED AND VERIFIED (`20025cc4`). live-odds-worker now emits
`kept=mlb,wnba,soccer dropped=nfl,ncaaf` every tick, and it launched wnba at
23:55:36Z -- confirmed two ways, from a marker stamp derived off two cadence
ages and from refresh-worker's grading at 23:59:25Z (`since_launch_s=229`).

TWO CORRECTIONS TO THE ORIGINAL FRAMING, both mine, both worth stating because
the first version of this docstring asserted them and they are FALSE:

  * **"refresh-worker swept everything and starved the owner."** WRONG. Its
    `ODDS_SWEEP_OUTCOME` lines are GRADINGS of launches made elsewhere (it reads
    the shared keyvalue markers) plus its OWN purpose-built autoruns. It does
    not run `_run_live_refresh_tick` at all -- that is imported only by
    `run_live_odds_refresh_worker`. I read a grading line as an event line.

  * **"refresh-worker should not refresh mlb."** WRONG.
    `SYNDICATE_MLB_REFRESH_TICK_OWNER=false` means its TICK should not, BECAUSE
    `_launch_autorun_mlb_refresh` does -- a designed 60-second path. It is a
    which-PATH flag, not a which-SERVICE flag. Gating `launch_refresh_run`
    centrally on that misreading would have silently killed it.

So this gate is correctly scoped to the TICK, which is the only place that
resolves a sport list, and it runs on the only service that executes that tick.

The two headline tests below pin the REAL env of each service, so the
configuration can never silently return to being ignored.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared import live_refresh_loop as loop


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in (
        "SYNDICATE_ACTIVE_SPORTS",
        "SYNDICATE_MLB_REFRESH_TICK_OWNER",
        "WEEKLY_SPORTS_REFRESH_TICK_OWNER",
        "SYNDICATE_LIVE_ODDS_REFRESH_SPORTS",
        "SYNDICATE_SWEEP_ACTIVE_SPORTS_STRICT",
    ):
        monkeypatch.delenv(key, raising=False)
    yield


def _effective(monkeypatch, capsys, **env):
    # Drive through the configured override so the season calendar is not part
    # of the test -- this is about the ownership gate, not about who is in season.
    monkeypatch.setenv("SYNDICATE_LIVE_ODDS_REFRESH_SPORTS", env.pop("_sports"))
    # `#514`. The weekly carve-out consults the real schedule adapter, whose answer
    # would otherwise depend on the calendar the suite happens to run on -- the
    # exact wall-clock time-bomb `test_layer2_shortlist_wiring.py` warns about.
    # Pinned per test. `None` means "do not patch", for the tests that predate the
    # carve-out and must keep exercising the unpatched path.
    claimed = env.pop("_claimed", None)
    if claimed is not None:
        monkeypatch.setattr(
            loop, "_weekly_sport_claimed_by_fast_tick", lambda sport, date: sport in claimed
        )
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    out = loop._live_refresh_loop_effective_sports("2026-08-17")
    return out, capsys.readouterr().out


# --------------------------------------------------------------------------
# The two production configurations. These are the regression.
# --------------------------------------------------------------------------


def test_refresh_workers_real_env_keeps_only_the_weekly_sports_on_the_tick(monkeypatch, capsys):
    kept, printed = _effective(
        monkeypatch,
        capsys,
        _sports="mlb,nfl,soccer,wnba",
        SYNDICATE_ACTIVE_SPORTS="nfl",
        SYNDICATE_MLB_REFRESH_TICK_OWNER="false",
        WEEKLY_SPORTS_REFRESH_TICK_OWNER="true",
    )
    # Its TICK keeps only nfl. This says nothing about refresh-worker as a
    # SERVICE: its purpose-built autoruns (mlb on a 60s cadence, soccer) are a
    # separate path that this gate does not and must not touch.
    assert kept == ["nfl"], "the tick keeps only the weekly sports here"
    assert "SWEEP_OWNERSHIP_EXCLUDED" in printed
    for sport in ("mlb", "soccer", "wnba"):
        assert sport in printed, f"{sport} was dropped without saying so"


def test_live_odds_workers_real_env_sweeps_its_three_plus_a_weekly_sport_with_games(monkeypatch, capsys):
    """`#514` CORRECTED THIS TEST. Its old form asserted `nfl not in kept`.

    That assertion was true of the code and false of the system. On a day NFL has
    games, refresh-worker's `_active_weekly_sports_for_date` DROPS nfl -- on the
    same `_weekly_sport_claimed_by_fast_tick` predicate -- precisely because the
    fast tick is supposed to claim it. ACTIVE_SPORTS then dropped it here too, so
    the yield happened and the claim did not, and NFL had no owner at all.

    Measured 2026-08-22, with NFL games in progress: `book_grid_2026-08-22.json`
    republished `PUBLISH_SKIPPED_UNCHANGED` with the identical checksum a minute
    apart, board quote age p50 36,478s (10.1h) against MLB's 487s, and every live
    NFL row deleted by `opportunity_gate`'s 900s `LIVE_MARKET_MAX_AGE_SECONDS`.

    The old comment -- "nfl belongs to refresh-worker's weekly autorun" -- is only
    true on a day NFL has NO games. That case is the next test.
    """
    kept, printed = _effective(
        monkeypatch,
        capsys,
        _sports="mlb,nfl,soccer,wnba",
        SYNDICATE_ACTIVE_SPORTS="mlb,wnba,soccer",
        SYNDICATE_MLB_REFRESH_TICK_OWNER="true",
        WEEKLY_SPORTS_REFRESH_TICK_OWNER="false",
        _claimed={"nfl"},
    )
    assert kept == ["mlb", "nfl", "soccer", "wnba"]
    assert "SWEEP_OWNERSHIP_WEEKLY_CLAIM sport=nfl" in printed, "an override must announce itself"


def test_a_weekly_sport_with_no_games_stays_excluded_by_active_sports(monkeypatch, capsys):
    """The carve-out is scoped to the claim, not to the sport. No games, no claim,
    no override -- ACTIVE_SPORTS applies exactly as it did before `#514`, and the
    sport stays with refresh-worker's 6-hourly autorun, which does still own it."""
    kept, _ = _effective(
        monkeypatch,
        capsys,
        _sports="mlb,nfl,soccer,wnba",
        SYNDICATE_ACTIVE_SPORTS="mlb,wnba,soccer",
        SYNDICATE_MLB_REFRESH_TICK_OWNER="true",
        WEEKLY_SPORTS_REFRESH_TICK_OWNER="false",
        _claimed=set(),
    )
    assert kept == ["mlb", "soccer", "wnba"]


def test_strict_mode_restores_the_absolute_reading_of_active_sports(monkeypatch, capsys):
    """The off switch. An operator who means "never touch nfl here" can say so."""
    kept, _ = _effective(
        monkeypatch,
        capsys,
        _sports="mlb,nfl",
        SYNDICATE_ACTIVE_SPORTS="mlb",
        SYNDICATE_MLB_REFRESH_TICK_OWNER="true",
        SYNDICATE_SWEEP_ACTIVE_SPORTS_STRICT="1",
        _claimed={"nfl"},
    )
    assert kept == ["mlb"]


@pytest.mark.parametrize("nfl_has_games", [True, False])
def test_exactly_one_owner_writes_nfl_whether_or_not_it_has_games(monkeypatch, nfl_has_games):
    """`#514` REPLACED THE OLD PARTITION TEST, which measured the wrong thing.

    The old version compared `_live_refresh_loop_effective_sports` under each
    service's env and asserted the two lists were disjoint and covering. But this
    file's own docstring records that refresh-worker "does not run
    `_run_live_refresh_tick` at all" -- so for refresh-worker that function's
    output is not what it executes, and the test asserted a partition between one
    real list and one hypothetical one. `nfl` was in the hypothetical half and in
    nobody's real half, which is exactly how a sport went 10 hours without a
    price while a test said the partition held.

    So compare the two paths each service ACTUALLY runs:

      live-odds-worker  `_live_refresh_loop_effective_sports`  (the fast tick)
      refresh-worker    `_active_weekly_sports_for_date`       (the weekly autorun)

    Both consult `_weekly_sport_claimed_by_fast_tick`, so patching that one
    predicate moves ownership across the boundary and the count must stay 1.
    """
    from scripts import run_refresh_worker as rw_mod

    monkeypatch.setattr(loop, "_weekly_sport_claimed_by_fast_tick", lambda sport, date: nfl_has_games)
    monkeypatch.setenv("SYNDICATE_LIVE_ODDS_REFRESH_SPORTS", "mlb,nfl,soccer,wnba")
    monkeypatch.setenv("SYNDICATE_ACTIVE_SPORTS", "mlb,wnba,soccer")
    monkeypatch.setenv("SYNDICATE_MLB_REFRESH_TICK_OWNER", "true")
    fast_tick = loop._live_refresh_loop_effective_sports("2026-09-14")

    monkeypatch.setattr(rw_mod, "_active_sports_for_date", lambda date: "mlb,nfl,soccer,wnba")
    weekly_autorun = [
        piece for piece in rw_mod._active_weekly_sports_for_date("2026-09-14").split(",") if piece
    ]

    owners = ("nfl" in fast_tick) + ("nfl" in weekly_autorun)
    assert owners == 1, (
        f"nfl must have exactly one owner; fast_tick={fast_tick} weekly_autorun={weekly_autorun}"
    )
    if nfl_has_games:
        assert "nfl" in fast_tick, "a game day belongs to the 60s tick -- that is the whole point"
    else:
        assert "nfl" in weekly_autorun, "a quiet week belongs to the 6-hourly autorun"


# --------------------------------------------------------------------------
# Exclusion is ONLY on explicit config.
# --------------------------------------------------------------------------


def test_a_service_with_no_opinion_keeps_todays_behaviour_exactly(monkeypatch, capsys):
    """The safety property. Absent config must not silence a service.

    `_mlb_refresh_tick_owner_here` already defaults TRUE when absent, and this
    gate must not quietly invert that -- CLAUDE.md calls out that same key by
    name as the one whose absent-default is True rather than False.
    """
    kept, printed = _effective(monkeypatch, capsys, _sports="mlb,nfl,soccer,wnba")
    assert kept == ["mlb", "nfl", "soccer", "wnba"]
    assert "SWEEP_OWNERSHIP_EXCLUDED" not in printed, "nothing was dropped, so say nothing"


def test_an_absent_active_sports_does_not_mean_nothing(monkeypatch, capsys):
    kept, _ = _effective(
        monkeypatch, capsys, _sports="mlb,wnba",
        SYNDICATE_MLB_REFRESH_TICK_OWNER="true",
    )
    assert kept == ["mlb", "wnba"]


def test_an_empty_active_sports_string_is_treated_as_no_opinion(monkeypatch, capsys):
    kept, _ = _effective(monkeypatch, capsys, _sports="mlb,wnba", SYNDICATE_ACTIVE_SPORTS="   ")
    assert kept == ["mlb", "wnba"], "whitespace is not a filter"


def test_the_mlb_owner_flag_excludes_on_its_own(monkeypatch, capsys):
    kept, printed = _effective(
        monkeypatch, capsys, _sports="mlb,wnba",
        SYNDICATE_MLB_REFRESH_TICK_OWNER="false",
    )
    assert kept == ["wnba"]
    assert "SYNDICATE_MLB_REFRESH_TICK_OWNER=false" in printed, "the reason must be readable"


@pytest.mark.parametrize("sport", ["nfl", "ncaaf", "ncaab"])
def test_weekly_sports_are_deliberately_NOT_gated_here(monkeypatch, capsys, sport):
    """THE CORRECTION. My first cut also applied the weekly owner flag and broke
    `test_run_tick_claims_weekly_sports_on_game_days`.

    Weekly ownership is DYNAMIC, not the static flag: on a game day the fast
    tick CLAIMS nfl/ncaaf/ncaab even with WEEKLY_SPORTS_REFRESH_TICK_OWNER
    false, because refresh-worker's `_active_weekly_sports_for_date` drops them
    on the same predicate so exactly one owner still writes. Double-gating it
    here silently reintroduces the 24-hour NFL capture gap measured 2026-08-07.

    So the flag being false must NOT exclude the sport at this layer.
    """
    kept, _ = _effective(
        monkeypatch, capsys, _sports=f"{sport},mlb",
        WEEKLY_SPORTS_REFRESH_TICK_OWNER="false",
        SYNDICATE_MLB_REFRESH_TICK_OWNER="true",
    )
    assert sport in kept, "weekly ownership is resolved by the tick, not by this gate"


def test_active_sports_still_excludes_an_UNCLAIMED_weekly_sport(monkeypatch, capsys):
    """ACTIVE_SPORTS is a different statement from the weekly owner flag: it says
    the service does not handle that sport at all. It still applies -- to every
    sport, and to a weekly sport too whenever the fast tick has not claimed it.

    `#514` narrowed this from "always" to "unless claimed", and nothing wider.
    """
    kept, _ = _effective(
        monkeypatch, capsys, _sports="nfl,mlb",
        SYNDICATE_ACTIVE_SPORTS="mlb",
        SYNDICATE_MLB_REFRESH_TICK_OWNER="true",
        _claimed=set(),
    )
    assert kept == ["mlb"]


# --------------------------------------------------------------------------
# Never silent.
# --------------------------------------------------------------------------


def test_an_empty_result_is_allowed_but_never_silent(monkeypatch, capsys):
    """A service whose owned sports are all out of season legitimately sweeps
    nothing. That is a real answer -- but the invisible version of it is the
    bug this fixes, so it must still print what it dropped and why."""
    kept, printed = _effective(
        monkeypatch, capsys, _sports="mlb,soccer",
        SYNDICATE_ACTIVE_SPORTS="nba",
    )
    assert kept == []
    assert "SWEEP_OWNERSHIP_EXCLUDED" in printed
    assert "kept=<none>" in printed
    assert "mlb:not_in_SYNDICATE_ACTIVE_SPORTS" in printed


def test_every_dropped_sport_carries_a_reason(monkeypatch, capsys):
    _, printed = _effective(
        monkeypatch, capsys, _sports="mlb,nfl,wnba",
        SYNDICATE_ACTIVE_SPORTS="mlb,wnba",
        SYNDICATE_MLB_REFRESH_TICK_OWNER="false",
        _claimed=set(),
    )
    line = next(l for l in printed.splitlines() if "SWEEP_OWNERSHIP_EXCLUDED" in l)
    assert "nfl:not_in_SYNDICATE_ACTIVE_SPORTS" in line
    assert "mlb:SYNDICATE_MLB_REFRESH_TICK_OWNER=false" in line


def test_the_gate_itself_never_raises_on_junk(monkeypatch):
    for value in ("", "   ", None):
        assert loop._sweep_ownership_exclusion(value) is None


# --------------------------------------------------------------------------
# The launch must be VISIBLE, not reconstructed.
# --------------------------------------------------------------------------


def test_a_successful_launch_emits_its_own_line():
    """Every other launch-side print in that file is a `*_FAILED` variant, so a
    launch that SUCCEEDED was invisible.

    Measured 2026-08-18: answering "did live-odds-worker take the sweep over?"
    needed the launch time reconstructed from two `PREGAME_CADENCE_DETAIL`
    marker ages. Worse, reading the ABSENCE of `ODDS_SWEEP_OUTCOME` instead
    produced a WRONG conclusion first -- that line grades a PRIOR launch and
    lags it, so it can never answer "did one start just now".
    """
    import inspect

    src = inspect.getsource(loop)
    assert "ODDS_SWEEP_LAUNCHED" in src, "a successful sweep launch must announce itself"


def test_the_launch_line_reports_which_sports_and_how_many():
    """"A launch happened" is not enough -- the whole ownership question is
    WHICH sports this service claimed, which is what the gate decides."""
    import inspect

    src = inspect.getsource(loop)
    block = src[src.index("ODDS_SWEEP_LAUNCHED"):][:400]
    assert "sports=" in block
    assert "count=" in block


def test_the_launch_line_fires_after_the_markers_are_recorded():
    """It must mean "launched and stamped", not "about to try".

    A line that fires before the thing it reports is the same false-signal
    problem in a new place -- and the markers are what the cadence filter
    actually reads, so announcing a launch that failed to stamp would be worse
    than the silence it replaces.
    """
    import inspect

    src = inspect.getsource(loop)
    assert src.index("_record_odds_sweep_launch(") < src.index("ODDS_SWEEP_LAUNCHED"), (
        "the launch line must come after the marker records, not before"
    )
