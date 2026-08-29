"""The env-gated `sport_branch` profiler. `[2026-08-29]`

REACHABILITY BEFORE ANYTHING ELSE. This is a diagnostic whose whole value is
that it runs on a real build; an inert one is worse than none, because its
silence reads as "nothing to see". So the first two tests are the off/on control
on the GATE itself, and the rest pin the conditions under which it must NOT fire
(cheap metadata passes, wrong sport) -- those are what stop it flooding a log
channel that already carries ~125 lines/minute.
"""

from __future__ import annotations

import pytest

from syndicate.blueprints import home as H


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv("SYNDICATE_SPORT_OVERVIEW_PROFILE", raising=False)
    monkeypatch.delenv("SYNDICATE_SPORT_OVERVIEW_PROFILE_TOP", raising=False)
    H._SPORT_BRANCH_PROFILER["profile"] = None
    H._SPORT_BRANCH_PROFILER["slug"] = None
    yield
    prof = H._SPORT_BRANCH_PROFILER.get("profile")
    if prof is not None:
        try:
            prof.disable()
        except Exception:
            pass
    H._SPORT_BRANCH_PROFILER["profile"] = None
    H._SPORT_BRANCH_PROFILER["slug"] = None


def test_off_by_default(monkeypatch):
    """OFF. No env var, no profiler, whatever the sport."""
    assert H._sport_branch_profile_slugs() == set()
    assert H._sport_branch_profile_begin("soccer", hydrated=True) is None


def test_on_for_the_named_sport(monkeypatch):
    """ON. The control for the test above."""
    monkeypatch.setenv("SYNDICATE_SPORT_OVERVIEW_PROFILE", "soccer")
    prof = H._sport_branch_profile_begin("soccer", hydrated=True)
    assert prof is not None
    H._sport_branch_profile_end(prof, "soccer", elapsed_s=1.0)
    assert H._SPORT_BRANCH_PROFILER["profile"] is None


def test_other_sports_are_untouched(monkeypatch):
    monkeypatch.setenv("SYNDICATE_SPORT_OVERVIEW_PROFILE", "soccer")
    assert H._sport_branch_profile_begin("mlb", hydrated=True) is None


def test_all_matches_every_sport(monkeypatch):
    monkeypatch.setenv("SYNDICATE_SPORT_OVERVIEW_PROFILE", "all")
    prof = H._sport_branch_profile_begin("ncaaf", hydrated=True)
    assert prof is not None
    H._sport_branch_profile_end(prof, "ncaaf", elapsed_s=1.0)


def test_cheap_metadata_passes_are_never_profiled(monkeypatch):
    """`skip_game_hydration=True` runs all eight sports in ~2s and fires several
    times a build for `_source_state_fingerprint`. Profiling those floods the
    log AND dilutes the sample with the path that is not the problem."""
    monkeypatch.setenv("SYNDICATE_SPORT_OVERVIEW_PROFILE", "soccer")
    assert H._sport_branch_profile_begin("soccer", hydrated=False) is None


def test_a_leaked_profiler_is_cleared_rather_than_wedging_the_instrument(monkeypatch, capsys):
    """A branch that raises before its `end` leaves cProfile enabled on this
    thread, and cProfile permits only one. Without this the FIRST exception
    would silently disable the instrument for the life of the process."""
    monkeypatch.setenv("SYNDICATE_SPORT_OVERVIEW_PROFILE", "all")
    first = H._sport_branch_profile_begin("soccer", hydrated=True)
    assert first is not None
    # simulate the branch raising: `end` never runs, the profiler stays parked
    second = H._sport_branch_profile_begin("ncaaf", hydrated=True)
    assert second is not None, "the instrument wedged after one leak"
    assert second is not first
    assert "SPORT_BRANCH_PROFILE_STALE_CLEARED" in capsys.readouterr().out
    H._sport_branch_profile_end(second, "ncaaf", elapsed_s=1.0)


def test_end_emits_both_orderings_and_survives_a_bad_top(monkeypatch, capsys):
    monkeypatch.setenv("SYNDICATE_SPORT_OVERVIEW_PROFILE", "soccer")
    monkeypatch.setenv("SYNDICATE_SPORT_OVERVIEW_PROFILE_TOP", "not-a-number")
    prof = H._sport_branch_profile_begin("soccer", hydrated=True)
    sum(range(2000))
    H._sport_branch_profile_end(prof, "soccer", elapsed_s=2.5)
    out = capsys.readouterr().out
    assert "order=tottime" in out
    assert "order=cumulative" in out
    assert "elapsed_s=2.5" in out


def test_end_on_none_is_a_noop(capsys):
    H._sport_branch_profile_end(None, "soccer", elapsed_s=1.0)
    assert capsys.readouterr().out == ""


def test_begin_never_raises_even_if_the_env_is_nonsense(monkeypatch):
    monkeypatch.setenv("SYNDICATE_SPORT_OVERVIEW_PROFILE", ",,,  ,")
    assert H._sport_branch_profile_begin("soccer", hydrated=True) is None
