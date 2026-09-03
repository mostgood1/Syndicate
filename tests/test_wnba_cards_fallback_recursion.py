"""`_artifact_bundle` must not be able to re-enter itself through the live-state
fallback.

MEASURED 2026-09-02 (lane `wnba-cards-fallback-recursion`), by calling
`_artifact_bundle(today)` with a depth spy:

    no game_cards CSV   bundle 247  depth 247  fallback 247  RecursionError 2  0.79s
    WITH one CSV row    bundle   1  depth   1  fallback   0  RecursionError 0  0.00s
    CSV removed again   bundle 247  depth 247  fallback 247  RecursionError 2  0.61s

`_artifact_bundle:1686` called `_games_from_live_state_fallback`, which called
`_artifact_bundle` straight back at `:3078`, and nothing memoises either. The
trigger is an EMPTY artifact, not a date: one row in `game_cards_<date>.csv` is
enough to prevent it. It is also disabled on Render by `_render_web_dyno()`,
which is why it survived as a cold/dev path.

The cost was never the point -- 0.6-0.8s. The defect was the SILENCE: the
`except Exception` swallowed the `RecursionError`, so "WNBA has no cards today"
and "the fallback blew the stack 247 frames deep" were the same observable. Three
separate mis-attributions in one session came out of that.

These tests are written so the PRE-FIX code fails them: a depth assertion that
247 cannot satisfy, and a log assertion against a marker that did not exist.
"""
from __future__ import annotations

import pytest

from syndicate.features.wnba import cards


@pytest.fixture()
def today():
    return cards.central_today_iso()


@pytest.fixture()
def depth_spy(monkeypatch):
    """Counts entries into `_artifact_bundle` and the deepest nesting reached.

    Asserting on DEPTH rather than wall clock on purpose: a timing assertion
    passes on a fast machine even while the recursion is still there, which is
    exactly how this survived."""
    state = {"calls": 0, "cur": 0, "max": 0, "fallback": 0, "recursion": 0}
    real_bundle = cards._artifact_bundle
    real_fallback = cards._games_from_live_state_fallback

    def bundle(selected_date, **kwargs):
        state["calls"] += 1
        state["cur"] += 1
        state["max"] = max(state["max"], state["cur"])
        try:
            return real_bundle(selected_date, **kwargs)
        except RecursionError:
            state["recursion"] += 1
            raise
        finally:
            state["cur"] -= 1

    def fallback(selected_date, ttl=12):
        state["fallback"] += 1
        return real_fallback(selected_date, ttl)

    monkeypatch.setattr(cards, "_artifact_bundle", bundle)
    monkeypatch.setattr(cards, "_games_from_live_state_fallback", fallback)
    return state


def _no_cards_artifact(monkeypatch, tmp_path):
    """Force the empty-artifact condition that triggers the fallback."""
    monkeypatch.setattr(cards, "_wnba_source_roots", lambda: (tmp_path,))
    monkeypatch.setattr(cards, "_load_game_cards_csv_rows_from_keyvalue", lambda *a, **kw: [])
    monkeypatch.setattr(cards, "_render_web_dyno", lambda: False)


def test_fallback_cannot_reenter_artifact_bundle(monkeypatch, tmp_path, depth_spy, today):
    """The load-bearing assertion. Pre-fix this reached depth 247."""
    _no_cards_artifact(monkeypatch, tmp_path)
    cards._artifact_bundle(today)
    assert depth_spy["max"] <= 2, (
        "the fallback re-entered _artifact_bundle: depth %d" % depth_spy["max"]
    )
    assert depth_spy["recursion"] == 0, "a RecursionError was raised"


def test_off_does_not_equal_on(monkeypatch, tmp_path, depth_spy, today):
    """`allow_fallback=False` must actually skip the fallback -- a flag that
    changed nothing would pass every other test here."""
    _no_cards_artifact(monkeypatch, tmp_path)
    cards._artifact_bundle(today, allow_fallback=False)
    skipped = depth_spy["fallback"]
    depth_spy["fallback"] = 0
    cards._artifact_bundle(today)
    allowed = depth_spy["fallback"]
    assert skipped == 0, "allow_fallback=False still called the fallback"
    assert allowed >= 1, "the fallback is no longer reachable at all -- this fix would be a silent feature removal"


def test_failure_is_named_not_swallowed(monkeypatch, tmp_path, capsys, today):
    """The actual defect. Pre-fix the except branch printed nothing, so a blown
    stack and an empty slate were indistinguishable."""
    _no_cards_artifact(monkeypatch, tmp_path)

    def boom(selected_date, ttl=12):
        raise RecursionError("maximum recursion depth exceeded")

    monkeypatch.setattr(cards, "_games_from_live_state_fallback", boom)
    cards._artifact_bundle(today)
    out = capsys.readouterr().out
    assert "LIVE_STATE_FALLBACK_FAILED" in out, "the failure was swallowed silently"
    assert "RecursionError" in out, "the error TYPE must be named, not just that it failed"


def test_failure_still_degrades_to_empty_rows(monkeypatch, tmp_path, today):
    """Logging must not change the behaviour: a failed fallback still yields an
    empty slate rather than propagating into the request."""
    _no_cards_artifact(monkeypatch, tmp_path)

    def boom(selected_date, ttl=12):
        raise RuntimeError("nope")

    monkeypatch.setattr(cards, "_games_from_live_state_fallback", boom)
    bundle = cards._artifact_bundle(today)
    assert isinstance(bundle, dict)


def test_rows_present_means_the_fallback_is_never_reached(monkeypatch, tmp_path, depth_spy, today):
    """The measured trigger condition, pinned: one row is enough."""
    processed = tmp_path / "data" / "processed"
    processed.mkdir(parents=True)
    (processed / ("game_cards_%s.csv" % today)).write_text(
        "date,game_id,home_team,visitor_team,commence_time,home_ml,away_ml,"
        "home_spread,away_spread,total,bookmaker,home_tri,away_tri\n"
        "%s,401800001,Las Vegas Aces,Seattle Storm,%sT23:00:00Z,-150,+130,"
        "-3.5,+3.5,165.5,draftkings,LVA,SEA\n" % (today, today),
        encoding="utf-8",
    )
    monkeypatch.setattr(cards, "_wnba_source_roots", lambda: (tmp_path,))
    monkeypatch.setattr(cards, "_load_game_cards_csv_rows_from_keyvalue", lambda *a, **kw: [])
    monkeypatch.setattr(cards, "_render_web_dyno", lambda: False)
    cards._artifact_bundle(today)
    assert depth_spy["fallback"] == 0, "the fallback ran despite the artifact having rows"
    assert depth_spy["max"] == 1


def test_ordinary_callers_are_unchanged(monkeypatch, tmp_path, today):
    """`allow_fallback` is keyword-only with a True default, so the five
    existing call sites keep their behaviour."""
    import inspect

    sig = inspect.signature(cards._artifact_bundle)
    param = sig.parameters["allow_fallback"]
    assert param.kind is inspect.Parameter.KEYWORD_ONLY
    assert param.default is True
