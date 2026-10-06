"""rescore_live_gameline_date.py: the SOCCER finals adapter.

Soccer is deliberately NOT shaped like NCAAF:

  * It is an ID JOIN. The ledger's soccer `game_pk` IS ESPN's event id (verified
    2026-09-30: ledger 761833 == ESPN usa.1 event 761833), so nothing compares a club
    name. That matters -- ESPN writes "St. Louis CITY SC" / "Red Bull New York" where
    the ledger writes "St. Louis City SC" / "New York Red Bulls", so a name join would
    have failed on BOTH recoverable dates.
  * DRAWS are kept and score as not-a-home-win, which `build_final_scores_index`
    documents as the unbiased treatment. **Neither live date contains a draw**
    (`draws_kept=0` on both), so that path is covered HERE and only here.
  * A postponed match is filed by ESPN under `post`; the repo's own
    `record_is_unplayed` is what excludes it.

All offline: `fetch_events` and `record_is_unplayed` are replaced with fixtures.
"""
from __future__ import annotations

import importlib.util
import pathlib

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "rescore_live_gameline_date", _ROOT / "scripts/rescore_live_gameline_date.py")
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)

from syndicate.features.soccer.ingestion import espn_lineups  # noqa: E402


def _event(event_id, home, away, hs, as_, **extra):
    rec = {"event_id": str(event_id), "home_team": home, "away_team": away,
           "home_score": hs, "away_score": as_, "status_state": "post",
           "status_completed": True, "status_name": "STATUS_FULL_TIME"}
    rec.update(extra)
    return rec


def _row(game_pk, home, away, *, scoreable=True, model=0.6):
    rec = {"event_id": f"odds-{game_pk}", "game_pk": str(game_pk),
           "home_team": home, "away_team": away, "market": "h2h", "segment": "full",
           "sport": "soccer", "quote_age_seconds": 30.0}
    rec["model_home_win_prob"] = model if scoreable else None
    rec["market_fair_prob"] = 0.5 if scoreable else None
    return rec


@pytest.fixture
def espn(monkeypatch):
    """Replace fetch_events with a fixture; returns a dict the test fills."""
    holder: dict = {"events": [], "leagues_called": []}

    def fake_fetch_events(league, *, date_windows, statuses=None, timeout=20):
        holder["leagues_called"].append(league)
        holder["statuses"] = statuses
        holder["windows"] = date_windows
        return list(holder["events"])

    monkeypatch.setattr(espn_lineups, "fetch_events", fake_fetch_events)
    # one league only, so the fixture's events are not returned ten times over
    monkeypatch.setattr(espn_lineups, "LEAGUE_ESPN_SLUGS", {"mls": "usa.1"})
    monkeypatch.setattr("syndicate.features.soccer.sources.active_leagues_for_date",
                        lambda date: ["mls"])
    return holder


def test_the_join_is_by_game_pk_and_never_by_team_name(espn):
    """The real 2026-09-30 case: the names DISAGREE and the id matches. If this ever
    starts joining on names it will silently lose both recoverable dates."""
    espn["events"] = [_event(761833, "Red Bull New York", "St. Louis CITY SC", "0", "3")]
    records = [_row(761833, "New York Red Bulls", "St. Louis City SC")]
    scores, join = mod._final_scores_soccer("2026-09-30", records)
    assert join["matched"] == 1, join
    assert scores == {"761833": (3.0, 0.0)}, "(away, home)"
    assert mod.finals_from_scores(scores) == {"761833": False}, "home lost 0-3"
    assert espn["statuses"] == {"post"}, "only finals are asked for"
    assert espn["windows"] == ["20260930-20260930"]


def test_a_DRAW_is_kept_and_scores_as_not_a_home_win(espn):
    """soccer is in DRAW_IS_A_REAL_OUTCOME. Excluding draws is what once conditioned
    the population on the outcome variable itself and 'silently deleted a third of
    soccer'. NEITHER live date has a draw, so this is the only cover for that path."""
    espn["events"] = [_event(900001, "Arsenal", "Chelsea", "2", "2")]
    records = [_row(900001, "Arsenal", "Chelsea")]
    scores, join = mod._final_scores_soccer("2026-10-01", records)
    assert join["draws_kept"] == 1 and join["matched"] == 1
    assert scores == {"900001": (2.0, 2.0)}
    assert mod.finals_from_scores(scores) == {"900001": False}, \
        "a draw is a well-defined False for 'did the home side win'"


def test_a_postponed_match_filed_under_post_is_not_a_final(espn):
    """ESPN files postponed/canceled/abandoned under `post`. The repo's own
    record_is_unplayed is the judgement, reused rather than re-derived."""
    espn["events"] = [
        _event(900002, "Everton", "Liverpool", None, None,
               status_name="STATUS_POSTPONED", status_completed=False),
        _event(900003, "Spurs", "Fulham", "1", "0"),
    ]
    records = [_row(900002, "Everton", "Liverpool"), _row(900003, "Spurs", "Fulham")]
    scores, join = mod._final_scores_soccer("2026-10-01", records)
    assert join["espn_unplayed_skipped"] == 1, join
    assert set(scores) == {"900003"}, "the postponed match must not enter the index"
    assert any("900002" in u for u in join["unmatched"])


def test_an_espn_final_the_ledger_never_priced_does_not_enter_the_index(espn):
    """The population is the LEDGER's games. An extra ESPN final is not a game this
    board priced, and folding it in would score a population the board never had."""
    espn["events"] = [_event(900004, "A", "B", "1", "0"),
                      _event(900005, "C", "D", "2", "2")]
    records = [_row(900004, "A", "B")]
    scores, join = mod._final_scores_soccer("2026-10-01", records)
    assert set(scores) == {"900004"}
    assert join["ledger_games"] == 1 and join["matched"] == 1


def test_an_unmatched_game_is_named_and_its_scoreability_reported(espn):
    espn["events"] = [_event(900006, "A", "B", "1", "0")]
    records = [_row(900006, "A", "B"),
               _row(900007, "Missing Home", "Missing Away"),
               _row(900008, "Quiet Home", "Quiet Away", scoreable=False)]
    scores, join = mod._final_scores_soccer("2026-10-01", records)
    assert join["matched"] == 1
    assert join["unmatched_scoreable"] == ["Missing Away @ Missing Home (game_pk 900007)"]
    assert any("900008" in u and "no scoreable h2h row" in u for u in join["unmatched"])


def test_a_row_without_a_game_pk_cannot_be_joined_and_is_not_counted(espn):
    """Unlike NCAAF, this adapter keys on game_pk. A soccer row that lacks one is not
    joinable by this route at all, and must not be silently counted as a ledger game."""
    espn["events"] = [_event(900009, "A", "B", "3", "1")]
    rows = [_row(900009, "A", "B")]
    orphan = _row(900009, "A", "B")
    orphan["game_pk"] = None
    rows.append(orphan)
    scores, join = mod._final_scores_soccer("2026-10-01", rows)
    assert join["ledger_games"] == 1, "the game_pk-less row adds no game"
    assert join["matched"] == 1


def test_soccer_is_wired_and_uses_its_own_ledger_tree():
    assert "soccer" in mod.WIRED_SPORTS
    assert mod.LEDGER_PATH.format(sport="soccer", date="2026-09-30") == \
        "soccer_source/data/live_gameline_ledger/live_gameline_ledger_2026-09-30.jsonl"
