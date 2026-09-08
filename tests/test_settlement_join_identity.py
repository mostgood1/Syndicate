"""WP8 -- the evaluation-ledger settlement join keys both sides on ONE identity.

Production 2026-09-08: the autorun completed and settled 0 of 29,630. Every MLB
sample looked like

    record keys  {"823983", "home ml", "laa", "moneyline"}
    graded rows  15 available, moneyline family present, ZERO overlap

because the graded side spelled the same fact differently ("home", a title
string "LAA @ SEA Home Ml") and the grader dropped the gamePk both sides had.
These tests build the graded side through the REAL grader over a synthetic
payload in `market_accuracy._normalized_rows`'s shape, and the record side in
the shape `home.py:_append_game_bet_candidate` writes.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

import syndicate.features.shared.evaluation_settlement as evaluation_settlement
import syndicate.features.shared.intelligence_evaluation as intelligence_evaluation
from syndicate.features.shared import graded_outcomes as go
from syndicate.features.shared.evaluation_settlement import _evaluation_record_keys
from syndicate.features.shared.evaluation_settlement import _graded_row_keys
from syndicate.features.shared.evaluation_settlement import _markets_compatible
from syndicate.features.shared.evaluation_settlement import match_graded_row
from syndicate.features.shared.evaluation_settlement import settle_ledger_for_date
from syndicate.features.shared.evaluation_settlement import settle_ledger_for_dates
from syndicate.features.shared.intelligence_evaluation import record_prediction
from syndicate.features.shared.intelligence_evaluation import record_recommendation
from syndicate.features.shared.settlement_identity import NO_KEY_MATCH_REASONS
from syndicate.features.shared.settlement_identity import find_graded_row
from syndicate.features.shared.settlement_identity import graded_row_identity
from syndicate.features.shared.settlement_identity import record_identity
from syndicate.features.shared.settlement_identity import resolve_selection


def _mlb_day_row(game_pk: int, matchup: str, market: str, selection: str, result: str, *, line=None, player=None, team=None) -> dict:
    """One row exactly as `mlb/market_accuracy._normalized_rows` emits it."""
    away, _, home = matchup.partition(" @ ")
    if player:
        title = f"{player} {selection.title()} {line:g} {market.replace('_', ' ').title()}"
    else:
        title = f"{matchup} {selection.title()} {market.title()}"
    return {
        "game_pk": game_pk,
        "matchup": matchup,
        "market": market,
        "title": title,
        "player_name": player,
        "team": team,
        "selection": selection,
        "line": line,
        "actual": None,
        "odds": "-120",
        "stake_u": 1.0,
        "profit_u": 0.83 if result == "win" else -1.0,
        "result": result,
        "tier": "all",
    }


def _mlb_graded_rows(day_rows: list[dict], date_str: str = "2026-09-05") -> list[dict]:
    payload = {"days": [{"date": date_str, "rows": {"all": day_rows}}]}
    with patch("syndicate.features.mlb.market_accuracy.build_market_accuracy_payload", return_value=payload):
        return go.graded_rows_for_date("mlb", date_str)


def _board_record(*, sport: str, game_id, pick: str, team, market: str, matchup: str, line="-", **extra) -> dict:
    """A ledger record whose recommendation is a board candidate."""
    recommendation = {
        "game_id": str(game_id) if game_id is not None else None,
        "gamePk": game_id,
        "event_id": extra.pop("event_id", None),
        "sport": sport.upper(),
        "sport_slug": sport,
        "matchup": matchup,
        "market": market,
        "pick": pick,
        "team": team,
        "line": line,
        "odds": "-120",
        **extra,
    }
    return {"sport": sport, "record_type": "recommendation", "result": "pending", "recommendation": recommendation}


# --------------------------------------------------------------------------
# 1. The production sample, and why it could not match before
# --------------------------------------------------------------------------


def test_production_sample_keys_had_no_overlap_and_now_match_on_game_id():
    rows = _mlb_graded_rows([_mlb_day_row(823983, "SEA @ LAA", "ml", "home", "win")])
    record = _board_record(sport="mlb", game_id=823983, pick="Home ML", team="LAA", market="Moneyline", matchup="SEA @ LAA")

    # The defect, pinned: the old extractors produce disjoint key sets.
    assert sorted(_evaluation_record_keys(record)) == ["823983", "home ml", "laa", "moneyline"]
    legacy_row = {key: value for key, value in rows[0].items() if key not in {"game_id", "game_pk", "home", "away"}}
    assert sorted(_graded_row_keys(legacy_row)) == ["home", "sea @ laa home ml"]
    assert _evaluation_record_keys(record).isdisjoint(_graded_row_keys(legacy_row))

    # The fix: one identity on both sides.
    assert record_identity(record, sport="mlb").summary() == graded_row_identity(rows[0]).summary()
    outcome = find_graded_row(record, rows, sport="mlb", markets_compatible=_markets_compatible)
    assert outcome.phase == "game_id"
    assert outcome.row is rows[0]
    assert match_graded_row(record, rows)["result"] == "win"


def test_mlb_grader_now_carries_game_id_and_fixture_clubs():
    rows = _mlb_graded_rows([_mlb_day_row(823983, "SEA @ LAA", "ml", "home", "win")])
    assert rows[0]["game_id"] == "823983"
    assert rows[0]["game_pk"] == 823983
    assert (rows[0]["home"], rows[0]["away"]) == ("LAA", "SEA")


def test_selection_text_maps_to_the_graded_vocabulary():
    assert resolve_selection("mlb", "Home ML").side == "home"
    assert resolve_selection("mlb", "Away ML").side == "away"
    over = resolve_selection("mlb", "Over 8.5")
    assert (over.side, over.line) == ("over", 8.5)
    under = resolve_selection("mlb", "under")
    assert under.side == "under"
    spread = resolve_selection("mlb", "home -1.5")
    assert (spread.side, spread.line) == ("home", -1.5)
    club = resolve_selection("mlb", "LAA -1.5")
    assert (club.subject, club.line, club.side) == ("laa", -1.5, None)
    prop = resolve_selection("mlb", "over drew anderson")
    assert (prop.side, prop.subject) == ("over", "drew anderson")
    assert resolve_selection("soccer", "Draw").side == "draw"
    assert resolve_selection("mlb", "Moneyline").unmapped is True
    assert resolve_selection("mlb", "").unmapped is False
    away_spread = resolve_selection("nfl", "away +3.5")
    assert (away_spread.side, away_spread.line) == ("away", 3.5)


def test_an_unmappable_pick_still_settles_when_the_club_implies_the_side():
    rows = _mlb_graded_rows([_mlb_day_row(823983, "SEA @ LAA", "ml", "home", "win")])
    record = _board_record(sport="mlb", game_id=823983, pick="Moneyline", team="LAA", market="Moneyline", matchup="SEA @ LAA")
    assert match_graded_row(record, rows)["result"] == "win"


def test_totals_and_props_join_on_game_id_with_line_and_player():
    rows = _mlb_graded_rows(
        [
            _mlb_day_row(823983, "SEA @ LAA", "totals", "over", "win", line=8.5),
            _mlb_day_row(823983, "SEA @ LAA", "pitcher_outs", "over", "loss", line=17.5, player="Jose Soriano", team="LAA"),
        ]
    )
    total = _board_record(sport="mlb", game_id=823983, pick="Over", team=None, market="Total", matchup="SEA @ LAA", line="8.5")
    assert match_graded_row(total, rows)["market"] == "totals"
    wrong_line = _board_record(sport="mlb", game_id=823983, pick="Over", team=None, market="Total", matchup="SEA @ LAA", line="9.5")
    assert match_graded_row(wrong_line, rows) is None
    prop = _board_record(
        sport="mlb", game_id=823983, pick="Over 17.5", team="LAA", market="Pitcher Outs", matchup="SEA @ LAA",
        line="17.5", player_name="Jose Soriano",
    )
    assert match_graded_row(prop, rows)["market"] == "pitcher_outs"


# --------------------------------------------------------------------------
# 2. Never a different game
# --------------------------------------------------------------------------


def test_same_club_on_different_sides_of_two_games_does_not_cross_match():
    """LAA is HOME in 823983 and AWAY in 823990 on the same date."""
    rows = _mlb_graded_rows(
        [
            _mlb_day_row(823983, "SEA @ LAA", "ml", "home", "win"),
            _mlb_day_row(823990, "LAA @ HOU", "ml", "away", "loss"),
        ]
    )
    home_record = _board_record(sport="mlb", game_id=823983, pick="Home ML", team="LAA", market="Moneyline", matchup="SEA @ LAA")
    away_record = _board_record(sport="mlb", game_id=823990, pick="Away ML", team="LAA", market="Moneyline", matchup="LAA @ HOU")
    assert match_graded_row(home_record, rows)["game_id"] == "823983"
    assert match_graded_row(away_record, rows)["game_id"] == "823990"

    # A record for a game the grader did NOT grade must not settle against the
    # LAA look-alike, and the miss says why.
    ungraded = _board_record(sport="mlb", game_id=823999, pick="Away ML", team="LAA", market="Moneyline", matchup="LAA @ TEX")
    outcome = find_graded_row(ungraded, rows, sport="mlb", markets_compatible=_markets_compatible)
    assert outcome.row is None
    assert outcome.reason == "game_not_graded"


def test_wrong_side_of_the_right_game_does_not_match():
    rows = _mlb_graded_rows([_mlb_day_row(823983, "SEA @ LAA", "ml", "home", "win")])
    record = _board_record(sport="mlb", game_id=823983, pick="Away ML", team="SEA", market="Moneyline", matchup="SEA @ LAA")
    assert match_graded_row(record, rows) is None


# --------------------------------------------------------------------------
# 3. Every reason token
# --------------------------------------------------------------------------


def _reason(record: dict, rows: list[dict], sport: str = "mlb") -> str | None:
    return find_graded_row(record, rows, sport=sport, markets_compatible=_markets_compatible).reason


def test_reason_team_unresolved():
    rows = [{"sport": "mlb", "market": "ml", "selection": "home", "home": "LAA", "away": "SEA", "result": "win"}]
    record = _board_record(sport="mlb", game_id=None, pick="Home ML", team="ZZZ", market="Moneyline", matchup="")
    assert _reason(record, rows) == "team_unresolved"


def test_reason_selection_unmapped():
    rows = [{"sport": "mlb", "market": "ml", "selection": "home", "home": "LAA", "away": "SEA", "result": "win"}]
    record = _board_record(sport="mlb", game_id=None, pick="Moneyline", team=None, market="Moneyline", matchup="")
    assert _reason(record, rows) == "selection_unmapped"


def test_reason_game_id_absent():
    rows = [{"sport": "mlb", "market": "ml", "selection": "home", "home": "LAA", "away": "SEA", "result": "win"}]
    record = _board_record(sport="mlb", game_id=None, pick="Home ML", team="NYY", market="Moneyline", matchup="BOS @ NYY")
    assert _reason(record, rows) == "game_id_absent"


def test_reason_game_not_graded():
    rows = _mlb_graded_rows([_mlb_day_row(823983, "SEA @ LAA", "ml", "home", "win")])
    record = _board_record(sport="mlb", game_id=823999, pick="Home ML", team="NYY", market="Moneyline", matchup="BOS @ NYY")
    assert _reason(record, rows) == "game_not_graded"


def test_every_reason_token_is_reported_by_the_counters():
    assert set(NO_KEY_MATCH_REASONS) == {"team_unresolved", "selection_unmapped", "game_not_graded", "game_id_absent", "unclassified"}


# --------------------------------------------------------------------------
# 4. Soccer and WNBA on the new path
# --------------------------------------------------------------------------


def test_soccer_rows_carry_event_id_and_join_on_it():
    schedule = {
        "matches": [
            {
                "event_id": "401700123",
                "date": "2026-09-05T14:00Z",
                "status_state": "post",
                "home_team": "Arsenal",
                "away_team": "Chelsea",
                "home_score": 2,
                "away_score": 1,
            }
        ]
    }
    with patch("syndicate.features.soccer.actuals.schedule_payload", return_value=schedule), \
         patch("syndicate.features.soccer.actuals._odds_price_index", return_value={}):
        from syndicate.features.soccer.actuals import graded_rows_for_league_date

        rows = graded_rows_for_league_date("epl", "2026-09-05")
    assert rows and all(row["event_id"] == "401700123" for row in rows)

    # soccer/cards.py writes the ESPN event id into gamePk AND event_id.
    away_ml = _board_record(
        sport="soccer", game_id="401700123", pick="Away ML", team="Chelsea", market="Moneyline",
        matchup="Chelsea @ Arsenal", event_id="401700123",
    )
    matched = match_graded_row(away_ml, rows)
    assert matched["market"] == "moneyline" and matched["selection"] == "Chelsea" and matched["result"] == "loss"

    draw = _board_record(sport="soccer", game_id="401700123", pick="Draw", team=None, market="Moneyline", matchup="Chelsea @ Arsenal")
    assert match_graded_row(draw, rows)["selection"] == "Draw"

    under = _board_record(sport="soccer", game_id="401700123", pick="Under 2.5", team=None, market="Total", matchup="Chelsea @ Arsenal", line="2.5")
    assert match_graded_row(under, rows)["selection"] == "under"


def test_wnba_rows_join_through_the_canonical_club_map():
    """WNBA graded rows carry no game id; the club path must carry the join,
    and "Las Vegas Aces" / "LVA" / "LV" must be one club through
    team_aliases, not through string overlap."""
    payload = {
        "days": [
            {
                "date": "2026-09-05",
                "games": {
                    "rows": [
                        {"market": "ML", "side": "LVA", "home": "LVA", "away": "NYL", "line": None, "actual": None, "price": -150, "result": "win"},
                        {"market": "ML", "side": "PHX", "home": "PHX", "away": "SEA", "line": None, "actual": None, "price": 120, "result": "loss"},
                        {"market": "TOTAL", "side": "Over", "home": "LVA", "away": "NYL", "line": 165.5, "actual": 171, "price": -110, "result": "win"},
                    ]
                },
                "props": {"rows": []},
            }
        ]
    }
    with patch("syndicate.features.shared.live_lens_local.build_local_market_accuracy_payload", return_value=payload), \
         patch("syndicate.features.wnba.sources.processed_roots", return_value=[Path(".")]):
        rows = go.graded_rows_for_date("wnba", "2026-09-05")
    assert len(rows) == 3 and all(row.get("game_id") is None for row in rows)

    full_name = _board_record(sport="wnba", game_id="401800001", pick="Home ML", team="Las Vegas Aces", market="Moneyline", matchup="New York Liberty @ Las Vegas Aces")
    matched = match_graded_row(full_name, rows)
    assert matched is not None and matched["selection"] == "LVA" and matched["result"] == "win"

    tri_code = _board_record(sport="wnba", game_id="401800001", pick="Home ML", team="LV", market="Moneyline", matchup="NY @ LV")
    assert match_graded_row(tri_code, rows)["selection"] == "LVA"

    # The other game's home side is not this club.
    other = _board_record(sport="wnba", game_id="401800002", pick="Home ML", team="PHX", market="Moneyline", matchup="SEA @ PHX")
    assert match_graded_row(other, rows)["selection"] == "PHX"

    total = _board_record(sport="wnba", game_id="401800001", pick="Over", team=None, market="Total", matchup="NYL @ LVA", line="165.5")
    assert match_graded_row(total, rows)["market"] == "TOTAL"


# --------------------------------------------------------------------------
# 5. The counters reach the summary the autorun writes
# --------------------------------------------------------------------------


def _pending(ledger_path: Path, *, sport: str, recommendation: dict) -> dict:
    prediction = record_prediction(
        query={"question": f"{sport} test", "selected_date": "2026-09-05", "sport": sport},
        response={"selected_date": "2026-09-05", "recommendations": []},
        persist=True,
        ledger_path=ledger_path,
    )
    return record_recommendation(prediction_record=prediction, recommendation=recommendation, persist=True, ledger_path=ledger_path)


def test_settlement_reports_reason_split_and_pending_by_sport():
    rows = _mlb_graded_rows([_mlb_day_row(823983, "SEA @ LAA", "ml", "home", "win")])
    with tempfile.TemporaryDirectory() as tmp_dir:
        ledger_path = Path(tmp_dir) / "evaluation_ledger.jsonl"
        with patch.object(intelligence_evaluation, "DEFAULT_LEDGER_PATH", ledger_path):
            hit = _pending(ledger_path, sport="mlb", recommendation=_board_record(sport="mlb", game_id=823983, pick="Home ML", team="LAA", market="Moneyline", matchup="SEA @ LAA")["recommendation"])
            _pending(ledger_path, sport="mlb", recommendation=_board_record(sport="mlb", game_id=823999, pick="Home ML", team="NYY", market="Moneyline", matchup="BOS @ NYY")["recommendation"])
            # A pick that names neither a side nor a club, with no club field
            # to fall back on. (With `team`/`matchup` present the club path
            # would rightly still settle it -- the side is implied.)
            _pending(ledger_path, sport="mlb", recommendation=_board_record(sport="mlb", game_id=823983, pick="Moneyline", team=None, market="Moneyline", matchup="")["recommendation"])

            with patch.object(evaluation_settlement, "_graded_rows_for_date", return_value=rows):
                summary = settle_ledger_for_date("2026-09-05", sport="mlb", ledger_path=ledger_path)
            assert summary["matched"] == 1 and summary["settled"] == 1
            assert summary["unmatched_no_key_match"] == 2
            assert summary["unmatched_no_key_match_reasons"]["game_not_graded"] == 1
            assert summary["unmatched_no_key_match_reasons"]["selection_unmapped"] == 1
            assert summary["graded_rows_with_game_id"] == {"mlb": 1}
            reasons = {sample["reason"] for sample in summary["unmatched_samples"]}
            assert reasons == {"no_key_match:game_not_graded", "no_key_match:selection_unmapped"}
            assert all("record_identity" in sample for sample in summary["unmatched_samples"])

            with patch.object(evaluation_settlement, "_graded_rows_for_date", return_value=rows):
                totals = settle_ledger_for_dates(["2026-09-05"], sports=["mlb", "wnba"], ledger_path=ledger_path)["totals"]
            assert totals["unmatched_no_key_match_reasons"]["game_not_graded"] == 1
            assert totals["pending_by_sport"] == {"mlb:2026-09-05": 2, "wnba:2026-09-05": 0}
            assert "wnba:2026-09-05" not in totals["graded_rows_available"]
            assert hit["recommendation_id"]
