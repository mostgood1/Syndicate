"""MLB game markets settle from FINAL SCORES, at any line and for either side.

Production 2026-09-17 (`/api/ops/evaluation-settlement/status`): the autorun
settled 1,388 of 9,807 records, and 6,815 misses were reported `game_not_graded`.
The MLB grader read only the season card, which grades props plus ONE moneyline
side per game -- no totals, no run lines, no segments -- and all 5 unmatched
samples were full-game totals overs on games the card DID grade.

EVERY INPUT HERE IS REAL, AND EACH SIDE OF THE JOIN HAS ITS OWN SOURCE:
  * graded side: `feed/live` payloads fetched from statsapi.mlb.com for the five
    sample games (trimmed; `tests/fixtures/settlement_final_scores/`), and the
    production card payload for 2026-09-11 (`card_payload_2026-09-11.json`);
  * record side: the production `unmatched_samples` (game id, matchup clubs,
    market, pick, line), rebuilt into the recommendation shape
    `home.py:_append_game_bet_candidate` writes and checked against the
    sample's own `record_keys` and `record_identity` before use. Run-line and
    moneyline records reuse those same games and clubs, with the pick wording
    of that function's own call sites ("Away ML", "Home -1.5").
"""

from __future__ import annotations

import copy
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

import syndicate.features.shared.evaluation_settlement as evaluation_settlement
import syndicate.features.shared.intelligence_evaluation as intelligence_evaluation
from syndicate.features.shared import graded_outcomes as go
from syndicate.features.shared.evaluation_settlement import _evaluation_record_keys
from syndicate.features.shared.evaluation_settlement import _markets_compatible
from syndicate.features.shared.evaluation_settlement import settle_ledger_for_date
from syndicate.features.shared.intelligence_evaluation import _iter_record_payloads
from syndicate.features.shared.intelligence_evaluation import record_prediction
from syndicate.features.shared.intelligence_evaluation import record_recommendation
from syndicate.features.shared.settlement_identity import find_graded_row
from syndicate.features.shared.settlement_identity import record_identity

FIXTURES = Path(__file__).parent / "fixtures" / "settlement_final_scores"
DATE = "2026-09-11"
FINAL_GAMES = (822684, 824227, 823012, 824711, 824954)
NOT_STARTED_GAME = 823334  # 2026-09-17, fetched while in Pre-Game


def _feed(game_pk: int) -> dict:
    return json.loads((FIXTURES / f"feed_live_{game_pk}.json").read_text(encoding="utf-8"))


def _samples() -> list[dict]:
    return json.loads((FIXTURES / "unmatched_samples_2026-09-17.json").read_text(encoding="utf-8"))["unmatched_samples"]


def _card_payload() -> dict:
    return json.loads((FIXTURES / f"card_payload_{DATE}.json").read_text(encoding="utf-8"))


def _board_recommendation(*, game_id: str, matchup: str, market: str, pick: str, line: str = "-", team: str = "-", **extra) -> dict:
    """The keys `home.py:_append_game_bet_candidate` writes that settlement reads."""
    return {
        "game_id": game_id,
        "gamePk": int(game_id),
        "event_id": None,
        "sport": "MLB",
        "sport_slug": "mlb",
        "matchup": matchup,
        "market": market,
        "pick": pick,
        "team": team,
        "entity": None,
        "player_name": None,
        "line": line,
        "odds": extra.pop("odds", "-110"),
        "market_key": extra.pop("market_key", None),
        **extra,
    }


def _record(recommendation: dict) -> dict:
    return {"sport": "mlb", "record_type": "recommendation", "result": "pending", "recommendation": recommendation}


def _sample_record(sample: dict) -> dict:
    identity = sample["record_identity"]
    matchup = f"{identity['away'].upper()} @ {identity['home'].upper()}"
    line = f"{sample['record_line']:.1f}"
    return _record(
        _board_recommendation(
            game_id=identity["game_ids"][0], matchup=matchup, market="Total", pick=f"Over {line}", line=line,
            market_key="totals",
        )
    )


def _matchup(game_pk: int) -> str:
    for sample in _samples():
        if sample["record_identity"]["game_ids"] == [str(game_pk)]:
            return f"{sample['record_identity']['away'].upper()} @ {sample['record_identity']['home'].upper()}"
    raise AssertionError(f"{game_pk} is not a production sample game")


def _score_rows() -> list[dict]:
    rows: list[dict] = []
    for game_pk in FINAL_GAMES:
        rows.extend(go.mlb_score_rows_from_feed(_feed(game_pk)))
    return rows


def _grade(recommendation: dict, rows: list[dict] | None = None):
    return find_graded_row(_record(recommendation), rows if rows is not None else _score_rows(), sport="mlb", markets_compatible=_markets_compatible)


# --------------------------------------------------------------------------
# The fixtures are what they claim to be
# --------------------------------------------------------------------------


def test_sample_records_rebuild_to_the_production_keys_and_identity():
    for sample in _samples():
        record = _sample_record(sample)
        assert sorted(_evaluation_record_keys(record)) == sample["record_keys"]
        assert record_identity(record, sport="mlb").summary() == sample["record_identity"]


def test_score_rows_from_real_feeds():
    rows = {(row["game_id"], row["segment"]): row for row in _score_rows()}
    # LAA 3 @ WSH 4, first five level 1-1; home led after the top of the 9th.
    assert (rows[("822684", "full")]["away_score"], rows[("822684", "full")]["home_score"]) == (3.0, 4.0)
    assert (rows[("822684", "first5")]["away_score"], rows[("822684", "first5")]["home_score"]) == (1.0, 1.0)
    assert rows[("822684", "full")]["home"] == "WSH" and rows[("822684", "full")]["away"] == "LAA"
    # SEA 5 @ ATH 6 in ten innings: a full row, from the team totals.
    assert (rows[("824954", "full")]["away_score"], rows[("824954", "full")]["home_score"]) == (5.0, 6.0)
    assert {segment for game_id, segment in rows if game_id == "824711"} == {"full", "first1", "first3", "first5"}


def test_a_game_that_has_not_finished_emits_nothing():
    feed = _feed(NOT_STARTED_GAME)
    assert feed["gameData"]["status"]["abstractGameState"] == "Preview"
    # Its linescore carries 0-0 team totals: a score, to anything that did not
    # check the game state first.
    assert feed["liveData"]["linescore"]["teams"]["home"]["runs"] == 0
    assert go.mlb_score_rows_from_feed(feed) == []


def test_a_postponed_game_marked_final_emits_nothing():
    # StatsAPI marks a postponed game abstractGameState=Final. Real payload,
    # status edited to that shape.
    feed = copy.deepcopy(_feed(822684))
    feed["gameData"]["status"].update({"abstractGameState": "Final", "codedGameState": "D", "detailedState": "Postponed", "statusCode": "DI"})
    assert go.mlb_score_rows_from_feed(feed) == []


def test_a_game_called_before_nine_innings_keeps_its_segments_and_loses_the_full_game_row():
    feed = copy.deepcopy(_feed(823012))
    feed["gameData"]["status"]["detailedState"] = "Completed Early"
    feed["liveData"]["linescore"]["innings"] = feed["liveData"]["linescore"]["innings"][:6]
    segments = {row["segment"] for row in go.mlb_score_rows_from_feed(feed)}
    assert segments == {"first1", "first3", "first5"}


# --------------------------------------------------------------------------
# Totals, run lines, moneylines, segments
# --------------------------------------------------------------------------


def test_the_five_production_samples_settle_from_the_final_score():
    expected = {"822684": ("loss", 7.0), "823012": ("win", 10.0), "824954": ("win", 11.0), "824227": ("push", 8.0), "824711": ("loss", 5.0)}
    for sample in _samples():
        outcome = find_graded_row(_sample_record(sample), _score_rows(), sport="mlb", markets_compatible=_markets_compatible)
        game_id = sample["record_identity"]["game_ids"][0]
        assert outcome.phase == "game_score", (game_id, outcome)
        assert (outcome.row["result"], outcome.row["actual"]) == expected[game_id]
        assert outcome.row["line"] == sample["record_line"] and outcome.row["odds"] is None


@pytest.mark.parametrize(
    "game_pk, pick, line, result",
    [
        (824227, "Over 8.0", "8.0", "push"),
        (824227, "Under 8.0", "8.0", "push"),
        (824227, "Over 7.5", "7.5", "win"),
        (824227, "Under 7.5", "7.5", "loss"),
        (822684, "Under 8.0", "8.0", "win"),
        (822684, "Over 6.5", "6.5", "win"),
    ],
)
def test_totals_at_any_line(game_pk, pick, line, result):
    outcome = _grade(_board_recommendation(game_id=str(game_pk), matchup=_matchup(game_pk), market="Total", pick=pick, line=line))
    assert outcome.row is not None and outcome.row["result"] == result


@pytest.mark.parametrize(
    "game_pk, market, pick, line, team, result",
    [
        # WSH beat LAA 4-3.
        (822684, "Spread", "Home -1.5", "-1.5", "WSH", "loss"),
        (822684, "Spread", "Away +1.5", "1.5", "LAA", "win"),
        (822684, "Alternate Spreads", "Away +2.5", "2.5", "LAA", "win"),
        (822684, "Spread", "Home -1", "-1", "WSH", "push"),
        (822684, "Run Line", "LAA +1.5", "1.5", "LAA", "win"),
        # DET beat COL 6-2.
        (824227, "Alternate Spreads", "Home -3.5", "-3.5", "DET", "win"),
        (824227, "Alternate Spreads", "Away +3.5", "3.5", "COL", "loss"),
        (824227, "Spread", "Away +4", "4", "COL", "push"),
    ],
)
def test_run_lines_both_sides_including_alternates(game_pk, market, pick, line, team, result):
    outcome = _grade(_board_recommendation(game_id=str(game_pk), matchup=_matchup(game_pk), market=market, pick=pick, line=line, team=team))
    assert outcome.phase == "game_score", outcome
    assert outcome.row["result"] == result


def test_an_alternate_market_key_grades_the_same_as_the_main_line():
    outcome = _grade(_board_recommendation(game_id="824227", matchup=_matchup(824227), market="Spread", pick="Home -2.5", line="-2.5", team="DET", market_key="spreads_alt"))
    assert outcome.row["result"] == "win"


@pytest.mark.parametrize(
    "game_pk, pick, team, result",
    [(822684, "Home ML", "WSH", "win"), (822684, "Away ML", "LAA", "loss"), (824711, "Away ML", "KC", "win"), (824711, "Home ML", "BOS", "loss")],
)
def test_moneyline_both_sides(game_pk, pick, team, result):
    outcome = _grade(_board_recommendation(game_id=str(game_pk), matchup=_matchup(game_pk), market="Moneyline", pick=pick, team=team))
    assert outcome.row is not None and outcome.row["result"] == result


def test_the_final_score_agrees_with_every_card_moneyline_verdict():
    """Two independent sources for the same five games: the production card's
    own `ml` verdicts, and the statsapi final scores."""
    card_ml = [row for row in _card_payload()["days"][0]["rows"]["all"] if row["market"] == "ml"]
    assert len(card_ml) == 5
    for row in card_ml:
        pick = "Home ML" if row["selection"] == "home" else "Away ML"
        outcome = _grade(_board_recommendation(game_id=str(row["game_pk"]), matchup=row["matchup"], market="Moneyline", pick=pick))
        assert outcome.row["result"] == row["result"], row


def test_first_five_total():
    # COL 1 @ DET 1 through five.
    matchup = _matchup(824227)
    over = _grade(_board_recommendation(game_id="824227", matchup=matchup, market="First 5 Total", pick="Over 1.5", line="1.5"))
    assert (over.row["result"], over.row["segment"], over.row["actual"]) == ("win", "first5", 2.0)
    push = _grade(_board_recommendation(game_id="824227", matchup=matchup, market="totals", pick="Under 2", line="2", segment="first5"))
    assert push.row["result"] == "push"
    # The same record on the full game would be graded against 8 runs: it must
    # not be, and the segment is why.
    assert over.row["actual"] != 8.0


def test_first_five_moneyline_tie():
    matchup = _matchup(822684)  # 1-1 through five
    two_way = _grade(_board_recommendation(game_id="822684", matchup=matchup, market="Moneyline", pick="Home ML", team="WSH", market_key="h2h", segment="first5"))
    assert two_way.row["result"] == "push"
    three_way = _grade(_board_recommendation(game_id="822684", matchup=matchup, market="Moneyline", pick="Home ML", team="WSH", market_key="h2h_3_way", segment="first5"))
    assert three_way.row["result"] == "loss"
    draw = _grade(_board_recommendation(game_id="822684", matchup=matchup, market="3-Way Moneyline", pick="Draw", segment="first5"))
    assert draw.row["result"] == "win"
    # A display label cannot say whether a tie refunds: refused, not guessed.
    unknown = _grade(_board_recommendation(game_id="822684", matchup=matchup, market="First 5 Moneyline", pick="Home ML", team="WSH"))
    assert unknown.row is None
    assert (unknown.reason, unknown.detail) == ("market_not_graded", "segment_moneyline_tie_way_unknown")


def test_a_first_five_moneyline_never_settles_against_the_full_game_card_row():
    """The segment hazard: `_markets_compatible` maps "First 5 Moneyline" and
    the card's `ml` to the same keyword family."""
    card_rows = [dict(row, sport="mlb", game_id=str(row["game_pk"])) for row in go_card_rows()]
    record = _board_recommendation(game_id="822684", matchup=_matchup(822684), market="First 5 Moneyline", pick="Home ML", team="WSH")
    assert _markets_compatible("First 5 Moneyline", "ml", "mlb") is True
    assert _grade(record, rows=card_rows).row is None


def test_refusals_are_named():
    matchup = _matchup(822684)
    projection_in_line = _grade(_board_recommendation(game_id="822684", matchup=matchup, market="First 5 Total", pick="Over 4.5", line="4.1"))
    assert projection_in_line.detail == "line_disagrees_with_selection"
    unknown_segment = _grade(_board_recommendation(game_id="822684", matchup=matchup, market="2nd Inning Total", pick="Over 0.5", line="0.5"))
    assert unknown_segment.detail == "segment_unrecognized"
    team_total = _grade(_board_recommendation(game_id="822684", matchup=matchup, market="Team Total", pick="Over 3.5", line="3.5", team="WSH"))
    assert team_total.detail == "not_a_score_market"
    wrong_way_round = _grade(_board_recommendation(game_id="822684", matchup="WSH @ LAA", market="Moneyline", pick="Home ML"))
    assert wrong_way_round.detail == "fixture_orientation_disagrees"
    other_game = _grade(_board_recommendation(game_id="824227", matchup="COL @ DET", market="Moneyline", pick="Home ML", team="LAA"))
    assert other_game.detail == "team_side_disagrees"


# --------------------------------------------------------------------------
# The grader: card rows for props, score rows for game markets
# --------------------------------------------------------------------------


def go_card_rows() -> list[dict]:
    with patch("syndicate.features.mlb.market_accuracy.build_market_accuracy_payload", return_value=_card_payload()):
        return go._mlb_card_graded_rows_for_date(DATE)


def _grader_rows(*, with_feeds: bool) -> list[dict]:
    feeds = {game_pk: _feed(game_pk) for game_pk in FINAL_GAMES} if with_feeds else {}
    with patch("syndicate.features.mlb.market_accuracy.build_market_accuracy_payload", return_value=_card_payload()), \
         patch.object(go, "_mlb_slate_game_pks", return_value=set(FINAL_GAMES)), \
         patch.object(go, "_load_cached_mlb_feed", side_effect=lambda _date, pk: feeds.get(pk)):
        return go.graded_rows_for_date("mlb", DATE)


def test_the_grader_emits_card_rows_first_then_score_rows():
    rows = _grader_rows(with_feeds=True)
    card = [row for row in rows if not go.is_score_row(row)]
    scores = [row for row in rows if go.is_score_row(row)]
    assert len(card) == 15 and len(scores) == 20
    assert rows[: len(card)] == card
    diagnostics = go.score_row_diagnostics("mlb", DATE)
    assert diagnostics["games_graded"] == 5 and diagnostics["feeds_not_cached"] == 0
    assert diagnostics["score_rows_by_segment"] == {"full": 5, "first1": 5, "first3": 5, "first5": 5}


def test_a_missing_feed_is_counted_not_hidden():
    rows = _grader_rows(with_feeds=False)
    assert not any(go.is_score_row(row) for row in rows)
    diagnostics = go.score_row_diagnostics("mlb", DATE)
    assert diagnostics["feeds_not_cached"] == 5 and diagnostics["games_graded"] == 0


def test_props_still_come_from_the_card():
    rows = _grader_rows(with_feeds=True)
    prop = _record(
        _board_recommendation(
            game_id="822684", matchup=_matchup(822684), market="Hitter Hits", pick="OVER Brady House", line="0.5", team="WSH",
            player_name="Brady House", entity="Brady House", market_key="batter_hits",
        )
    )
    outcome = find_graded_row(prop, rows, sport="mlb", markets_compatible=_markets_compatible)
    assert outcome.phase == "game_id"
    assert (outcome.row["market"], outcome.row["player"], outcome.row["result"]) == ("hitter_hits", "Brady House", "win")
    # A prop the card did not grade is not rescued by the score.
    other = _record(
        _board_recommendation(
            game_id="822684", matchup=_matchup(822684), market="Hitter Total Bases", pick="OVER Brady House", line="1.5", team="WSH",
            player_name="Brady House", entity="Brady House", market_key="batter_total_bases",
        )
    )
    missed = find_graded_row(other, rows, sport="mlb", markets_compatible=_markets_compatible)
    assert (missed.row, missed.reason, missed.detail) == (None, "market_not_graded", "prop_not_graded")


# --------------------------------------------------------------------------
# Reachability: the real samples, through settlement, off != on
# --------------------------------------------------------------------------


def _write_pending(ledger_path: Path, recommendation: dict) -> dict:
    prediction = record_prediction(
        query={"question": "mlb board", "selected_date": DATE, "sport": "mlb"},
        response={"selected_date": DATE, "recommendations": []},
        persist=True,
        ledger_path=ledger_path,
    )
    return record_recommendation(prediction_record=prediction, recommendation=recommendation, persist=True, ledger_path=ledger_path)


def _settle_samples(*, with_feeds: bool) -> tuple[dict, dict]:
    rows = _grader_rows(with_feeds=with_feeds)
    with tempfile.TemporaryDirectory() as tmp_dir:
        ledger_path = Path(tmp_dir) / "evaluation_ledger.jsonl"
        with patch.object(intelligence_evaluation, "DEFAULT_LEDGER_PATH", ledger_path):
            written = [_write_pending(ledger_path, _sample_record(sample)["recommendation"]) for sample in _samples()]
            with patch.object(evaluation_settlement, "_graded_rows_for_date", return_value=rows):
                summary = settle_ledger_for_date(DATE, sport="mlb", ledger_path=ledger_path)
            stored = {
                record["recommendation_id"]: record
                for record in _iter_record_payloads(ledger_path=ledger_path)
                if record.get("record_type") == "recommendation"
            }
            by_game = {record["recommendation"]["game_id"]: stored[record["recommendation_id"]] for record in written}
    return summary, by_game


def test_reachability_the_samples_settle_with_score_rows_and_not_without():
    off_summary, off_records = _settle_samples(with_feeds=False)
    assert off_summary["settled"] == 0
    assert off_summary["unmatched_no_key_match_reasons"]["market_not_graded"] == 5
    assert off_summary["unmatched_market_not_graded_detail"] == {"no_score_rows_for_game": 5}
    assert {record["result"] for record in off_records.values()} == {"pending"}

    on_summary, on_records = _settle_samples(with_feeds=True)
    assert on_summary["settled"] == 5 and on_summary["matched_by_phase"] == {"game_score": 5}
    assert {game: record["result"] for game, record in on_records.items()} == {
        "822684": "loss", "823012": "win", "824954": "win", "824227": "push", "824711": "loss",
    }
    # Priced at the RECORD's odds (-110), and the record's own price is not
    # stamped as its close.
    assert on_records["823012"]["pnl"] == pytest.approx(0.9091)
    assert on_records["822684"]["pnl"] == -1.0 and on_records["824227"]["pnl"] == 0.0
    assert on_records["823012"]["closing_price"] is None
    assert on_summary["graded_games_indexed"] == {"mlb": 5}
    assert on_summary["graded_rows_carrying_game_id"] == {"mlb": 35}
    assert on_summary["graded_row_market_family_counts"]["mlb"]["game_score:full"] == 5
