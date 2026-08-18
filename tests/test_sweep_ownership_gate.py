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
    ):
        monkeypatch.delenv(key, raising=False)
    yield


def _effective(monkeypatch, capsys, **env):
    # Drive through the configured override so the season calendar is not part
    # of the test -- this is about the ownership gate, not about who is in season.
    monkeypatch.setenv("SYNDICATE_LIVE_ODDS_REFRESH_SPORTS", env.pop("_sports"))
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


def test_live_odds_workers_real_env_lets_it_sweep_the_three_it_owns(monkeypatch, capsys):
    kept, _ = _effective(
        monkeypatch,
        capsys,
        _sports="mlb,nfl,soccer,wnba",
        SYNDICATE_ACTIVE_SPORTS="mlb,wnba,soccer",
        SYNDICATE_MLB_REFRESH_TICK_OWNER="true",
        WEEKLY_SPORTS_REFRESH_TICK_OWNER="false",
    )
    assert kept == ["mlb", "soccer", "wnba"]
    assert "nfl" not in kept, "nfl belongs to refresh-worker's weekly autorun"


def test_the_two_services_partition_the_sports_with_no_overlap_and_no_gap(monkeypatch, capsys):
    """The property that actually matters: every sport swept exactly once."""
    slate = "mlb,nfl,soccer,wnba"
    rw, _ = _effective(
        monkeypatch, capsys, _sports=slate,
        SYNDICATE_ACTIVE_SPORTS="nfl",
        SYNDICATE_MLB_REFRESH_TICK_OWNER="false",
        WEEKLY_SPORTS_REFRESH_TICK_OWNER="true",
    )
    lo, _ = _effective(
        monkeypatch, capsys, _sports=slate,
        SYNDICATE_ACTIVE_SPORTS="mlb,wnba,soccer",
        SYNDICATE_MLB_REFRESH_TICK_OWNER="true",
        WEEKLY_SPORTS_REFRESH_TICK_OWNER="false",
    )
    assert set(rw) & set(lo) == set(), "no sport may be swept twice"
    assert set(rw) | set(lo) == set(slate.split(",")), "no sport may be dropped by both"


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


def test_active_sports_still_excludes_a_weekly_sport(monkeypatch, capsys):
    """ACTIVE_SPORTS is a different statement from the weekly owner flag: it
    says the service does not handle that sport at all. It still applies."""
    kept, _ = _effective(
        monkeypatch, capsys, _sports="nfl,mlb",
        SYNDICATE_ACTIVE_SPORTS="mlb",
        SYNDICATE_MLB_REFRESH_TICK_OWNER="true",
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
