"""NBA live bet status: the worker's live box capture, the resolver, and the page.

The order of the sections is the order of the pipeline:

  live tick ESPN fetch -> `nba/live_player_box.capture` -> live_player_box_<date>.json
  -> `bet_status_nba` (via `paper_settlement._default_resolver`) -> plan["bet_status"]
  -> `_attach_open_bet_status` -> `/portfolio` open-row cell.

Reachability first: before this, `_default_resolver` had no `nba` entry and every
open NBA order read `no_resolver_for_nba` (fleet, 2026-10-24).
"""

from __future__ import annotations

import json

import pytest

from syndicate.features.nba import live_player_box as capture_mod
from syndicate.features.shared import bet_status_nba as mod
from syndicate.features.shared.bet_status import statuses_for_orders

DATE = "2026-10-23"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("SYNDICATE_REFRESH_STATE_BACKEND", "file")
    yield tmp_path


def _player(name="Daniel Gafford", team="DAL", **stats):
    row = {"team_tri": team, "player": name, "mp": 12.0, "pts": 4, "reb": 3, "ast": 4,
           "stl": 0, "blk": 0, "tov": 0, "threes_made": 0, "pf": 2}
    row.update(stats)
    return row


def _game(event_id="401909844", away="DAL", home="IND", state="in", final=False, players=None,
          away_score=77.0, home_score=47.0, captured_at="2026-10-24T00:31:00Z"):
    return {"event_id": event_id, "away_tri": away, "home_tri": home, "state": state, "final": final,
            "status_detail": "10:36 - 3rd", "away_score": away_score, "home_score": home_score,
            "captured_at": captured_at, "players": players if players is not None else [_player()]}


def _write_box(tmp_path, games):
    path = tmp_path / capture_mod.artifact_relative_path(DATE)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"date": DATE, "payload": {"games": games}}), encoding="utf-8")


def _order(**kw):
    # The order carries the board's OddsAPI hash, never the ESPN id -- the real shape.
    order = {"sport": "nba", "event_id": "e0c3a7b1f00dhash", "market": "player_blocks",
             "player_name": "Daniel Gafford", "side": "over", "line": 0.5,
             "away_team": "Dallas Mavericks", "home_team": "Indiana Pacers",
             "segment": "full", "idempotency_key": "k1"}
    order.update(kw)
    return order


def _status(order):
    from syndicate.features.shared.paper_settlement import _default_resolver

    report = statuses_for_orders([order], resolver=_default_resolver(DATE))
    return report["rows"][0]


# ---------------------------------------------------------------------------
# Reachability: off != on, through the SAME dispatcher portfolio_commit uses
# ---------------------------------------------------------------------------


def test_reachability_no_box_is_named_and_a_box_resolves(_isolated):
    off = _status(_order())
    assert off["unavailable_reason"] == mod.REASON_NO_BOX  # not no_resolver_for_nba
    _write_box(_isolated, [_game(players=[_player(blk=1)])])
    on = _status(_order())
    assert on != off
    assert on["status"] == "won" and on["current_value"] == 1.0 and on["line"] == 0.5


# ---------------------------------------------------------------------------
# The user's case and the monotone rules
# ---------------------------------------------------------------------------


def test_over_half_a_block_is_won_at_one_block_mid_game(_isolated):
    _write_box(_isolated, [_game(players=[_player(blk=1)])])
    row = _status(_order())
    assert row["status"] == "won" and row["decided"] is True
    assert row["as_of"] == "2026-10-24T00:31:00Z"


def test_over_not_yet_crossed_is_behind_not_lost(_isolated):
    _write_box(_isolated, [_game(players=[_player(blk=0)])])
    assert _status(_order())["status"] == "live_behind"


def test_under_is_only_alive_until_final_then_won(_isolated):
    _write_box(_isolated, [_game(players=[_player(blk=0)])])
    assert _status(_order(side="under"))["status"] == "live_ahead"
    _write_box(_isolated, [_game(state="post", final=True, players=[_player(blk=0)])])
    assert _status(_order(side="under"))["status"] == "won"


def test_combo_market_sums_and_refuses_a_partial_sum(_isolated):
    _write_box(_isolated, [_game(players=[_player(pts=20, reb=8, ast=5)])])
    row = _status(_order(market="player_points_rebounds_assists", line=30.5))
    assert row["current_value"] == 33.0 and row["status"] == "won"
    _write_box(_isolated, [_game(players=[_player(pts=20, reb=None, ast=5)])])
    assert _status(_order(market="player_points_rebounds_assists"))["unavailable_reason"] == mod.REASON_NO_STAT


def test_pregame_reads_not_started(_isolated):
    _write_box(_isolated, [_game(state="pre", players=[], away_score=None, home_score=None)])
    assert _status(_order())["status"] == "not_started"


def test_absent_player_is_named_never_zero(_isolated):
    _write_box(_isolated, [_game(players=[_player(name="Someone Else")])])
    assert _status(_order(side="under"))["unavailable_reason"] == mod.REASON_PLAYER_NOT_FOUND


def test_matchup_recovery_handles_names_the_tri_table_misses(_isolated):
    """`_canonical_nba_tri("Utah Jazz")` returns "UTAH JAZZ"; the join must not."""
    _write_box(_isolated, [_game(away="NOP", home="UTA", players=[_player(name="Lauri Markkanen", team="UTA", pts=11)])])
    row = _status(_order(away_team="New Orleans Pelicans", home_team="Utah Jazz",
                         player_name="Lauri Markkanen", market="player_points", line=20.5))
    assert row["status"] == "live_behind" and row["current_value"] == 11.0


def test_segment_bet_refuses_a_whole_game_box(_isolated):
    _write_box(_isolated, [_game(players=[_player(blk=1)])])
    assert _status(_order(segment="h1"))["unavailable_reason"].startswith("actual_is_full_game_not_")


def test_game_lines_read_team_scores_oriented_to_the_order(_isolated):
    _write_box(_isolated, [_game(away_score=77.0, home_score=47.0)])
    total = _status(_order(market="totals", side="over", line=230.5, player_name=None))
    assert total["current_value"] == 124.0 and total["status"] == "live_behind"
    spread = _status(_order(market="spreads", side="Dallas Mavericks", line=-5.5, player_name=None))
    assert spread["status"] == "live_ahead" and spread["current_value"] == 30.0 and spread["line"] == 5.5
    assert spread["value_kind"] == "margin"


# ---------------------------------------------------------------------------
# The live column honours the resolver's restated side/line, as settlement does
# ---------------------------------------------------------------------------

# A REAL fleet ledger row (`/api/portfolio/live`, 2026-10-24 01:37Z), read as
# `unknown_side` on the live column while settlement could grade it.
_REAL_SPREAD_ROW = {
    "sport": "nba", "market": "spreads_alt", "side": "home", "line": 3.5, "player_name": None,
    "event_id": "0d34c898f6cbb990077ae9f0a2773513", "away_team": "New York Knicks",
    "home_team": "Boston Celtics", "selected_date": "2026-10-23", "segment": "full",
    "status": "filled", "venue": "kalshi", "mode": "live", "idempotency_key": "13a19205299eec095b02b271",
}


def _nyk_at_bos(away_score, home_score, state="in", final=False):
    # Scores as the 00:31Z capture read them (NYK 54 @ BOS 60, 3rd quarter).
    return _game(event_id="401909095", away="NYK", home="BOS", state=state, final=final,
                 away_score=away_score, home_score=home_score, players=[])


def test_real_spread_row_before_and_after(_isolated):
    from syndicate.features.shared.bet_status import resolve_bet_status

    _write_box(_isolated, [_nyk_at_bos(54.0, 60.0)])
    # BEFORE: the order's own side reaches the grader, which has no direction for "home".
    before = resolve_bet_status(market="spreads_alt", side="home", line=3.5, current_value=6.0)
    assert before["unavailable_reason"] == "unknown_side"
    # AFTER: Boston +3.5, up 6 -> margin +6 against -3.5 -> ahead, not yet decided.
    after = _status(dict(_REAL_SPREAD_ROW))
    assert after["unavailable_reason"] is None
    assert (after["status"], after["current_value"], after["line"]) == ("live_ahead", 6.0, -3.5)
    assert after["decided"] is False and after["value_kind"] == "margin"
    assert after["side"] == "home"  # the row still records what was bet


def test_real_spread_row_decides_only_at_final(_isolated):
    _write_box(_isolated, [_nyk_at_bos(110.0, 104.0, state="post", final=True)])
    row = _status(dict(_REAL_SPREAD_ROW))
    assert row["status"] == "lost" and row["current_value"] == -6.0 and row["decided"] is True


def test_moneyline_on_a_team_name(_isolated):
    _write_box(_isolated, [_nyk_at_bos(54.0, 60.0)])
    row = _status(dict(_REAL_SPREAD_ROW, market="h2h", side="New York Knicks", line=None))
    assert row["status"] == "live_behind" and row["current_value"] == -6.0 and row["line"] == 0.0


def test_a_prop_is_not_restated(_isolated):
    _write_box(_isolated, [_game(players=[_player(blk=1)])])
    row = _status(_order())
    assert row["value_kind"] is None and row["side"] == "over" and row["line"] == 0.5


def test_unmapped_market_is_permanent_and_checked_before_the_box(_isolated):
    assert _status(_order(market="player_first_basket"))["unavailable_reason"] == mod.REASON_UNMAPPED_MARKET


# ---------------------------------------------------------------------------
# Double-double / triple-double: a count of categories at ten, line restated
# ---------------------------------------------------------------------------


def _jokic(**kw):
    # The fleet's only archived one (2026-10-24): side "Yes", line NaN.
    fields = {"market": "player_double_double", "side": "Yes", "line": float("nan"), "player_name": "Nikola Jokic"}
    return _order(**{**fields, **kw})


def _final_jokic_box(tmp_path, **stats):
    base = {"pts": 30, "reb": 12, "ast": 9, "stl": 1, "blk": 0}
    base.update(stats)
    _write_box(tmp_path, [_game(state="post", final=True, players=[_player(name="Nikola Jokic", **base)])])


def test_double_double_reachability_was_unmapped_now_resolves(_isolated):
    _final_jokic_box(_isolated)
    row = _status(_jokic())
    assert row["unavailable_reason"] is None and row["status"] == "won"
    assert row["current_value"] == 2.0 and row["line"] == 1.5


@pytest.mark.parametrize(
    "stats, side, expected",
    [
        ({}, "Yes", "won"),  # 30 / 12: two categories
        ({"ast": 11}, "Yes", "won"),  # a triple-double is a double-double too
        ({"reb": 9}, "Yes", "lost"),  # 30 / 9: one category
        ({"reb": 9}, "No", "won"),
        ({}, "No", "lost"),
        ({"pts": 8, "reb": 10, "ast": 4, "stl": 10, "blk": 0}, "Yes", "won"),  # steals count
        ({"reb": 10, "ast": 9.0}, "Yes", "won"),  # exactly ten counts
    ],
)
def test_double_double_counts_five_categories_at_ten(_isolated, stats, side, expected):
    _final_jokic_box(_isolated, **stats)
    assert _status(_jokic(side=side))["status"] == expected


def test_triple_double_needs_three(_isolated):
    _final_jokic_box(_isolated)
    row = _status(_jokic(market="player_triple_double"))
    assert row["line"] == 2.5 and row["status"] == "lost"
    _final_jokic_box(_isolated, ast=10)
    assert _status(_jokic(market="player_triple_double"))["status"] == "won"


def test_double_double_is_not_decided_mid_game(_isolated):
    _write_box(_isolated, [_game(players=[_player(name="Nikola Jokic", pts=30, reb=12)])])
    row = _status(_jokic())
    assert row["status"] == "live_ahead" and row["decided"] is False


def test_double_double_refuses_a_missing_category(_isolated):
    _final_jokic_box(_isolated, blk=None)
    assert _status(_jokic())["unavailable_reason"] == mod.REASON_NO_STAT


def test_double_double_grades_through_paper_settlement(_isolated):
    from syndicate.features.shared.paper_settlement import _default_resolver, _our_verdict

    _final_jokic_box(_isolated)
    order = _jokic(status="filled", fill_price=-680.0, fill_stake_dollars=28.32, fees_dollars=0.0)
    verdict, _resolved, refusal = _our_verdict(order, _default_resolver(DATE))
    assert refusal == ""
    assert verdict["outcome"] == "won" and verdict["settled_value"] == 2.0 and verdict["line"] == 1.5
    assert verdict["pnl_dollars"] == round(28.32 * 100 / 680, 4)


# ---------------------------------------------------------------------------
# The capture's merge rules (no ESPN)
# ---------------------------------------------------------------------------


def _scoreboard(*events):
    return {"events": list(events)}


def _event(event_id, state, completed=False, away="DAL", home="IND", away_score="77", home_score="47"):
    return {"id": event_id, "competitions": [{
        "status": {"type": {"state": state, "completed": completed, "shortDetail": state}},
        "competitors": [
            {"homeAway": "home", "score": home_score, "team": {"abbreviation": home}},
            {"homeAway": "away", "score": away_score, "team": {"abbreviation": away}},
        ]}]}


def _run(scoreboard, summaries, existing=None, stamp="2026-10-24T01:00:00Z"):
    written = {}
    fetched = []

    def fetch_summary(event_id):
        fetched.append(event_id)
        return {"event": event_id}

    result = capture_mod.capture(
        DATE,
        fetch_scoreboard=lambda d: scoreboard,
        fetch_summary=fetch_summary,
        extract_players=lambda summary: summaries.get(summary["event"], []),
        to_tri=lambda abbr: abbr,
        read_existing=lambda: existing,
        write=written.update,
        now=lambda: stamp,
    )
    return result, written, fetched


def test_capture_writes_state_scores_and_players():
    result, written, _ = _run(_scoreboard(_event("1", "in"), _event("2", "pre", away="NOP", home="UTA")),
                              {"1": [_player(blk=2)]})
    games = {g["event_id"]: g for g in written["payload"]["games"]}
    assert result["written"] and result["live"] == 1
    assert games["1"]["players"][0]["blk"] == 2 and games["1"]["captured_at"] == "2026-10-24T01:00:00Z"
    assert games["2"]["state"] == "pre" and games["2"]["players"] == [] and games["2"]["home_score"] is None


def test_capture_keeps_last_box_when_a_live_fetch_comes_back_empty():
    prior = {"payload": {"games": [{**_game(event_id="1"), "captured_at": "2026-10-24T00:50:00Z"}]}}
    _, written, _ = _run(_scoreboard(_event("1", "in")), {}, existing=prior)
    game = written["payload"]["games"][0]
    assert game["players"] and game["captured_at"] == "2026-10-24T00:50:00Z"


def test_capture_never_marks_final_without_a_post_final_read():
    prior = {"payload": {"games": [_game(event_id="1")]}}
    _, written, _ = _run(_scoreboard(_event("1", "post", completed=True)), {}, existing=prior)
    assert written["payload"]["games"][0]["final"] is False


def test_capture_does_not_refetch_a_held_final():
    prior = {"payload": {"games": [_game(event_id="1", state="post", final=True)]}}
    result, written, fetched = _run(_scoreboard(_event("1", "post", completed=True)), {}, existing=prior)
    assert fetched == [] and result["carried"] == 1 and written["payload"]["games"][0]["final"] is True


def test_capture_writes_nothing_without_a_slate():
    result, written, _ = _run(_scoreboard(), {})
    assert not result["written"] and written == {}


# ---------------------------------------------------------------------------
# The page join carries the as-of
# ---------------------------------------------------------------------------


def test_open_row_join_carries_as_of(monkeypatch):
    import pipeline.portfolio_commit as commit
    from syndicate.blueprints import intelligence as bp

    monkeypatch.setattr(commit, "read_portfolio_plan", lambda date: {"bet_status": {"rows": [
        {"idempotency_key": "k1", "status": "won", "current_value": 1.0, "line": 0.5,
         "as_of": "2026-10-24T00:31:00Z"}]}})
    out = bp._attach_open_bet_status([{"idempotency_key": "k1", "selected_date": DATE, "status": "filled"}])
    assert out[0]["live_status"]["as_of"] == "2026-10-24T00:31:00Z"
