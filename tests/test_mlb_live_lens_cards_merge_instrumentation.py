"""`_merge_cards_context_into_report` had two SILENT early returns, and they
are why a deployed fix looked identical to no fix.

`_carry_live_probability` is reachable only through this function. Measured on
live-odds-worker 2026-09-23 17:5xZ, with the carry fix `7094b69a` confirmed
present in the live commit `49b8881b`:

    [live_props] LIVE_MC_PRICED  17:47:27Z game=824785 rows=29
                                 17:49:39Z game=824223 rows=52
    [live_lens_loop] TICK_COMPLETE 17:44:49Z, 17:48:24Z results={'mlb': True, ...}
    [live_lens] LIVE_PROB_CARRIED -- NEVER EMITTED

The carry prints on its failing path, so never printing means never CALLED --
and with the tick running, the only way out is one of the two returns here.
Neither said anything, so the trace ended at a blank wall.
"""

from __future__ import annotations

import pytest

import syndicate.features.mlb.live_lens as live_lens

REPORT = {"games": [{"gamePk": 824785, "liveProps": []}]}


def test_a_raising_cards_context_names_itself(monkeypatch, capsys):
    def boom(_date):
        raise RuntimeError("cards page exploded")

    monkeypatch.setattr(live_lens, "build_cards_page_context", boom)
    out = live_lens._merge_cards_context_into_report(dict(REPORT), "2026-09-23")
    line = capsys.readouterr().out
    assert "CARDS_MERGE_SKIPPED" in line
    assert "reason=cards_context_raised" in line
    assert "RuntimeError" in line
    assert out == REPORT          # behaviour unchanged: still returns the report


def test_no_cards_is_a_DIFFERENT_reason_from_a_raise(monkeypatch, capsys):
    monkeypatch.setattr(live_lens, "build_cards_page_context", lambda _d: {"games": []})
    live_lens._merge_cards_context_into_report(dict(REPORT), "2026-09-23")
    line = capsys.readouterr().out
    assert "reason=no_cards" in line
    assert "cards_context_raised" not in line


def test_the_two_reasons_are_never_the_same_string(monkeypatch, capsys):
    """One bare `return report` covered both owners. They must stay separable."""
    monkeypatch.setattr(live_lens, "build_cards_page_context", lambda _d: {"games": []})
    live_lens._merge_cards_context_into_report(dict(REPORT), "2026-09-23")
    no_cards = capsys.readouterr().out

    def boom(_date):
        raise ValueError("nope")

    monkeypatch.setattr(live_lens, "build_cards_page_context", boom)
    live_lens._merge_cards_context_into_report(dict(REPORT), "2026-09-23")
    raised = capsys.readouterr().out
    assert no_cards != raised


def test_the_succeeding_path_counts_what_it_matched(monkeypatch, capsys):
    monkeypatch.setattr(live_lens, "build_cards_page_context",
                        lambda _d: {"games": [{"gamePk": 824785}]})
    live_lens._merge_cards_context_into_report(dict(REPORT), "2026-09-23")
    line = capsys.readouterr().out
    assert "CARDS_MERGE " in line
    assert "cards=1" in line
    assert "report_games=1" in line
    assert "matched=1" in line


def test_cards_that_match_no_report_game_report_matched_zero(monkeypatch, capsys):
    # The state that explains a zero carry without anyone reading the source:
    # cards exist, the merge runs, and NO row reaches `_carry_live_probability`.
    monkeypatch.setattr(live_lens, "build_cards_page_context",
                        lambda _d: {"games": [{"gamePk": 999999}]})
    live_lens._merge_cards_context_into_report(dict(REPORT), "2026-09-23")
    line = capsys.readouterr().out
    assert "cards=1" in line
    assert "matched=0" in line


def test_the_merge_still_returns_merged_games(monkeypatch):
    monkeypatch.setattr(live_lens, "build_cards_page_context",
                        lambda _d: {"games": [{"gamePk": 824785, "away": {"name": "TOR"}}]})
    out = live_lens._merge_cards_context_into_report(dict(REPORT), "2026-09-23")
    assert isinstance(out.get("games"), list) and len(out["games"]) == 1
