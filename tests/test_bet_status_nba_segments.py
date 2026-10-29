"""NBA quarter and half game lines, graded off the daily ESPN linescore (`#745`).

  scripts/fetch_basketball_linescores.py -> nba_source/data/processed/linescores_<date>.json
  -> `bet_status_nba` (via `paper_settlement._default_resolver`) -> `_our_verdict` -> `grade_order`

Reachability first: before this, every NBA segment order refused
`actual_is_full_game_not_<seg>` before any artifact was read (15 archived paper
rows on the fleet, 2026-10-29 13:40Z).
"""

from __future__ import annotations

import json

import pytest

from syndicate.features.shared import bet_status_nba as mod
from syndicate.features.shared.paper_settlement import _default_resolver, _our_verdict

DATE = "2026-10-26"

# ESPN's shape: event id -> ESPN abbreviations, periods in order.
MIN_CLE_OT = {"away": "MIN", "home": "CLE", "away_periods": [31, 29, 26, 27, 12], "home_periods": [24, 26, 36, 27, 14]}
ATL_HOU = {"away": "ATL", "home": "HOU", "away_periods": [30, 28, 25, 22], "home_periods": [27, 33, 24, 30]}
DAL_MIA = {"away": "DAL", "home": "MIA", "away_periods": [25, 25, 25, 25], "home_periods": [25, 30, 20, 25]}


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("SYNDICATE_REFRESH_STATE_BACKEND", "file")
    yield tmp_path


def _write_linescores(tmp_path, games, date=DATE):
    path = tmp_path / mod.linescores_relative_path(date)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"date": date, "fetched_at": "2026-10-27T10:35:02Z", "games": games}), encoding="utf-8")


def _order(**kw):
    # The ledger's real shape: OddsAPI hash, full club names, canonical market, `segment`.
    order = {"sport": "nba", "mode": "paper", "venue": "paper", "status": "filled", "book": "fanduel",
             "event_id": "b57695c11301fc8264db6b94a5ea2485", "market": "totals_alt", "segment": "q1",
             "side": "under", "line": 58.5, "away_team": "Atlanta Hawks", "home_team": "Houston Rockets",
             "fill_price": 104.0, "fill_stake_dollars": 5.13, "selected_date": DATE, "idempotency_key": "k1"}
    order.update(kw)
    return order


def _verdict(order):
    verdict, resolved, refusal = _our_verdict(order, _default_resolver(DATE))
    return verdict, resolved, refusal


# ---------------------------------------------------------------------------
# Reachability: off != on, through the SAME dispatcher settlement uses
# ---------------------------------------------------------------------------


def test_reachability_no_linescore_refuses_by_name_and_a_linescore_grades(_isolated):
    off = _verdict(_order())
    assert off[0] is None and off[2] == mod.REASON_NO_LINESCORE  # not actual_is_full_game_not_q1
    _write_linescores(_isolated, {"401909866": ATL_HOU})
    on = _verdict(_order())
    assert on != off
    verdict, resolved, refusal = on
    assert refusal == ""
    # q1 alone: 30 + 27 = 57 under 58.5.
    assert resolved["current_value"] == 57.0 and resolved["settled_segment"] == "q1"
    assert verdict["outcome"] == "won"


def test_the_linescore_is_read_from_disk_under_the_keyvalue_backend(_isolated, monkeypatch):
    """The fleet's backend is keyvalue, and the producer writes plain files."""
    _write_linescores(_isolated, {"401909866": ATL_HOU})
    monkeypatch.setenv("SYNDICATE_REFRESH_STATE_BACKEND", "keyvalue")
    verdict, resolved, refusal = _verdict(_order())
    assert refusal == "" and resolved["current_value"] == 57.0


def test_a_segment_game_line_never_grades_off_the_whole_game_box(_isolated):
    """A final whole-game box present, no linescore: still refused, never graded."""
    from syndicate.features.nba import live_player_box as capture_mod

    box = _isolated / capture_mod.artifact_relative_path(DATE)
    box.parent.mkdir(parents=True, exist_ok=True)
    box.write_text(json.dumps({"date": DATE, "payload": {"games": [
        {"event_id": "401909866", "away_tri": "ATL", "home_tri": "HOU", "state": "post", "final": True,
         "away_score": 105.0, "home_score": 114.0, "players": []}]}}), encoding="utf-8")
    verdict, resolved, refusal = _verdict(_order(market="totals", line=200.5))
    assert verdict is None and refusal == mod.REASON_NO_LINESCORE
    assert resolved.get("current_value") is None


# ---------------------------------------------------------------------------
# What each segment sums
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("segment,total", [("q1", 57.0), ("q2", 61.0), ("q3", 49.0), ("q4", 52.0),
                                            ("h1", 118.0), ("h2", 101.0)])
def test_each_segment_sums_its_own_periods(_isolated, segment, total):
    _write_linescores(_isolated, {"401909866": ATL_HOU})
    _verdict_row, resolved, refusal = _verdict(_order(segment=segment, line=0.5))
    assert refusal == "" and resolved["current_value"] == total


def test_a_segment_spread_is_oriented_to_the_order_and_graded(_isolated):
    _write_linescores(_isolated, {"401909866": ATL_HOU})
    # h1: HOU 60, ATL 58. Home -1.5 covers by 0.5.
    verdict, resolved, refusal = _verdict(_order(market="spreads", segment="h1", side="home", line=-1.5))
    assert refusal == "" and verdict["outcome"] == "won"
    assert resolved["home_score"] == 60.0 and resolved["away_score"] == 58.0
    # The same game listed by ESPN the other way round: scores follow the CLUB.
    swapped = {"away": "HOU", "home": "ATL", "away_periods": ATL_HOU["home_periods"], "home_periods": ATL_HOU["away_periods"]}
    _write_linescores(_isolated, {"401909866": swapped})
    verdict, resolved, refusal = _verdict(_order(market="spreads", segment="h1", side="home", line=-1.5))
    assert refusal == "" and verdict["outcome"] == "won" and resolved["home_score"] == 60.0


def test_a_level_quarter_pushes_a_two_way_moneyline(_isolated):
    _write_linescores(_isolated, {"401909871": DAL_MIA})
    order = _order(market="h2h", segment="q1", side="home", line=float("nan"),
                   away_team="Dallas Mavericks", home_team="Miami Heat")
    verdict, _resolved, refusal = _verdict(order)
    assert refusal == "" and verdict["outcome"] == "push"
    verdict, _resolved, refusal = _verdict({**order, "segment": "q2"})
    assert verdict["outcome"] == "won"  # MIA 30, DAL 25


# ---------------------------------------------------------------------------
# Overtime: the book's rule
# ---------------------------------------------------------------------------

_MIN_CLE = dict(away_team="Minnesota Timberwolves", home_team="Cleveland Cavaliers", market="totals")


@pytest.mark.parametrize("book,q4_total,h2_total", [
    ("draftkings", 80.0, 142.0),  # q4 27+27 + OT 12+14; h2 62+54 + 26
    ("fanduel", 54.0, 142.0),
    ("betmgm", 54.0, 142.0),
    ("pinnacle", 54.0, 142.0),
])
def test_overtime_follows_each_books_rule(_isolated, book, q4_total, h2_total):
    _write_linescores(_isolated, {"401909869": MIN_CLE_OT})
    _v, q4, refusal = _verdict(_order(segment="q4", book=book, line=0.5, **_MIN_CLE))
    assert refusal == "" and q4["current_value"] == q4_total
    _v, h2, refusal = _verdict(_order(segment="h2", book=book, line=0.5, **_MIN_CLE))
    assert refusal == "" and h2["current_value"] == h2_total and h2["segment_periods"] == [3, 4, 5]


def test_an_unread_books_rule_refuses_only_when_overtime_was_played(_isolated):
    _write_linescores(_isolated, {"401909869": MIN_CLE_OT, "401909866": ATL_HOU})
    _v, _r, refusal = _verdict(_order(segment="q4", book="bovada", line=0.5, **_MIN_CLE))
    assert refusal == f"{mod.REASON_OVERTIME_RULE_UNREAD_PREFIX}bovada"
    _v, _r, refusal = _verdict(_order(segment="h2", book="bovada", line=0.5, **_MIN_CLE))
    assert refusal == f"{mod.REASON_OVERTIME_RULE_UNREAD_PREFIX}bovada"
    # Overtime cannot reach the first half, and without overtime every rule agrees.
    _v, h1, refusal = _verdict(_order(segment="h1", book="bovada", line=0.5, **_MIN_CLE))
    assert refusal == "" and h1["current_value"] == 110.0
    _v, q4, refusal = _verdict(_order(segment="q4", book="bovada", line=0.5))
    assert refusal == "" and q4["current_value"] == 52.0


# ---------------------------------------------------------------------------
# Named refusals
# ---------------------------------------------------------------------------


def test_a_segment_player_prop_still_refuses_by_name(_isolated):
    _write_linescores(_isolated, {"401909866": ATL_HOU})
    _v, _r, refusal = _verdict(_order(market="player_points", player_name="Trae Young", line=7.5))
    assert refusal == "actual_is_full_game_not_q1"


def test_a_game_not_yet_in_the_linescore_refuses_by_name(_isolated):
    _write_linescores(_isolated, {"401909871": DAL_MIA})
    _v, _r, refusal = _verdict(_order())
    assert refusal == mod.REASON_GAME_NOT_IN_LINESCORE


def test_missing_or_uneven_periods_refuse_rather_than_sum_part(_isolated):
    short = {**ATL_HOU, "home_periods": [27, 33, 24]}
    _write_linescores(_isolated, {"401909866": short})
    _v, _r, refusal = _verdict(_order(segment="h1"))
    assert refusal == "segment_actual_unavailable:h1"


def test_the_same_matchup_twice_refuses_both(_isolated):
    _write_linescores(_isolated, {"401909866": ATL_HOU, "401909899": ATL_HOU})
    _v, _r, refusal = _verdict(_order())
    assert refusal == mod.REASON_AMBIGUOUS_LINESCORE


# ---------------------------------------------------------------------------
# The producer writes where the reader reads
# ---------------------------------------------------------------------------


def test_the_scheduled_fetch_writes_the_file_this_resolver_reads(_isolated, monkeypatch):
    from scripts import fetch_basketball_linescores as producer

    competitors = [
        {"homeAway": "home", "team": {"abbreviation": "HOU"},
         "linescores": [{"value": v} for v in ATL_HOU["home_periods"]]},
        {"homeAway": "away", "team": {"abbreviation": "ATL"},
         "linescores": [{"value": v} for v in ATL_HOU["away_periods"]]},
    ]
    scoreboard = {"events": [{"id": "401909866", "status": {"type": {"completed": True}},
                              "competitions": [{"competitors": competitors}]}]}
    monkeypatch.setattr(producer, "fetch", lambda league, date: scoreboard)
    assert producer.main(["--date", DATE, "--leagues", "nba"]) == 0
    verdict, resolved, refusal = _verdict(_order())
    assert refusal == "" and resolved["current_value"] == 57.0 and verdict["outcome"] == "won"
