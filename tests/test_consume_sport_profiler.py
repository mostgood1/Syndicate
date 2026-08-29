"""`_consume_sport` instrumentation: the shared branch profiler + segments.

WHY THIS REGION. The first profiler was pointed at `_build_sport_overview` and
measured 3.22s of a 362.76s soccer bracket -- 0.9%. `OVERVIEW_SPORT_BEGIN..END`
contains only that call, this consumer, and a memory log, so ~99% is here. These
tests pin the gate and the segment arithmetic; the production reading does the
rest.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared import branch_profiler as BP


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv("SYNDICATE_CONSUME_SPORT_PROFILE", raising=False)
    monkeypatch.delenv("SYNDICATE_CONSUME_SPORT_PROFILE_TOP", raising=False)
    BP._PARKED.clear()
    yield
    for prof in list(BP._PARKED.values()):
        if prof is not None:
            try:
                prof.disable()
            except Exception:
                pass
    BP._PARKED.clear()


ENV = "SYNDICATE_CONSUME_SPORT_PROFILE"


def test_off_by_default():
    assert BP.profile_keys(ENV) == set()
    assert not BP.profile_enabled_for(ENV, "soccer")


def test_on_for_a_named_key(monkeypatch):
    """The control for the test above."""
    monkeypatch.setenv(ENV, "soccer")
    assert BP.profile_enabled_for(ENV, "soccer")
    assert not BP.profile_enabled_for(ENV, "mlb")


@pytest.mark.parametrize("value", ["off", "0", "false", "no", "none", "disabled", "OFF", " Off "])
def test_explicit_off_values(monkeypatch, value):
    """Render's env API rejects an empty value (HTTP 400), so turning this off
    has to be a WORD -- and it must not depend on no sport being named `off`."""
    monkeypatch.setenv(ENV, value)
    assert BP.profile_keys(ENV) == set()


@pytest.mark.parametrize("value", ["all", "1", "true", "on"])
def test_all_values(monkeypatch, value):
    monkeypatch.setenv(ENV, value)
    assert BP.profile_enabled_for(ENV, "anything")


def test_body_runs_and_output_appears_when_enabled(monkeypatch, capsys):
    monkeypatch.setenv(ENV, "soccer")
    ran = []
    with BP.profile_branch(ENV, "soccer", label="consume_sport"):
        ran.append(True)
        sum(range(1000))
    out = capsys.readouterr().out
    assert ran == [True]
    assert "order=tottime" in out and "order=cumulative" in out


def test_body_runs_and_is_silent_when_disabled(capsys):
    """OFF != ON, on the CONTEXT MANAGER rather than only the gate helper."""
    ran = []
    with BP.profile_branch(ENV, "soccer", label="consume_sport"):
        ran.append(True)
    assert ran == [True]
    assert capsys.readouterr().out == ""


def test_an_exception_in_the_body_propagates_and_releases(monkeypatch, capsys):
    """The profiler must never change control flow, and must not stay parked."""
    monkeypatch.setenv(ENV, "soccer")
    with pytest.raises(ValueError):
        with BP.profile_branch(ENV, "soccer", label="consume_sport"):
            raise ValueError("boom")
    assert BP._PARKED.get(ENV) is None
    capsys.readouterr()
    with BP.profile_branch(ENV, "soccer", label="consume_sport"):
        pass
    assert "order=tottime" in capsys.readouterr().out, "instrument wedged after a raise"


def test_a_parked_profiler_is_cleared_rather_than_wedging(monkeypatch, capsys):
    """cProfile permits one profiler per thread. Without the stale-clear the
    first leak would silently disable the diagnostic for the process lifetime."""
    monkeypatch.setenv(ENV, "all")
    import cProfile

    leaked = cProfile.Profile()
    leaked.enable()
    BP._PARKED[ENV] = leaked
    with BP.profile_branch(ENV, "soccer", label="consume_sport"):
        pass
    out = capsys.readouterr().out
    assert "STALE_CLEARED" in out
    assert "order=tottime" in out


def test_segment_threshold_default_and_override(monkeypatch):
    from pipeline.intelligence_state import _consume_sport_segment_log_threshold_sec as thr

    monkeypatch.delenv("SYNDICATE_CONSUME_SPORT_SEGMENT_LOG_SEC", raising=False)
    assert thr() == 10.0
    monkeypatch.setenv("SYNDICATE_CONSUME_SPORT_SEGMENT_LOG_SEC", "0.5")
    assert thr() == 0.5
    monkeypatch.setenv("SYNDICATE_CONSUME_SPORT_SEGMENT_LOG_SEC", "nonsense")
    assert thr() == 10.0


# ---------------------------------------------------------------------------
# The candidate_collection hook uses the SAME shared profiler with its own env
# var. These pin that the two are independent -- arming one must not arm the
# other, or "turn the profiler off" stops meaning anything specific.

CC_ENV = "SYNDICATE_CANDIDATE_COLLECTION_PROFILE"


def test_candidate_collection_env_is_independent_of_consume_sport(monkeypatch):
    monkeypatch.delenv(CC_ENV, raising=False)
    monkeypatch.setenv(ENV, "all")
    assert BP.profile_enabled_for(ENV, "soccer")
    assert not BP.profile_enabled_for(CC_ENV, "2026-08-29"), "arming one armed the other"


def test_candidate_collection_keys_on_the_date(monkeypatch):
    monkeypatch.setenv(CC_ENV, "2026-08-29")
    assert BP.profile_enabled_for(CC_ENV, "2026-08-29")
    assert not BP.profile_enabled_for(CC_ENV, "2026-08-30")


def test_candidate_collection_all_and_off(monkeypatch):
    monkeypatch.setenv(CC_ENV, "all")
    assert BP.profile_enabled_for(CC_ENV, "any-date")
    monkeypatch.setenv(CC_ENV, "off")
    assert not BP.profile_enabled_for(CC_ENV, "any-date")


def test_the_two_hooks_park_separately(monkeypatch, capsys):
    """_PARKED is keyed by env var. If it were global, the candidate_collection
    hook entering would clear the consume_sport hook's live profiler."""
    monkeypatch.setenv(ENV, "all")
    monkeypatch.setenv(CC_ENV, "all")
    with BP.profile_branch(ENV, "soccer", label="consume_sport"):
        with BP.profile_branch(CC_ENV, "2026-08-29", label="candidate_collection"):
            pass
    out = capsys.readouterr().out
    # ASSERT SUCCESS, NOT MERELY THE LABEL. `BEGIN_FAILED` also contains the
    # label, so `"candidate_collection" in out` passes on the failure path --
    # which is exactly what happens if cProfile refuses a second concurrent
    # profiler on this thread. Assert the REPORT line instead.
    assert "candidate_collection key=2026-08-29 order=tottime" in out, out[:400]
    assert "BEGIN_FAILED" not in out, out[:400]
    assert "STALE_CLEARED" not in out, "one hook cleared the other's profiler"
