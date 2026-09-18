"""MLB player props settle from the FINAL BOX SCORE, at any line and either side.

Production 2026-09-18 (`/api/ops/evaluation-settlement/status`, autorun ended
11:27:37Z): MLB settled 2,293 of 10,817 settleable (21.2%), and all 7,849
`market_not_graded` misses were `prop_not_graded`. The MLB grader's only prop
source was the season card, which grades only the props the card itself picked.

EVERY INPUT HERE IS REAL, AND EACH SIDE OF THE JOIN HAS ITS OWN SOURCE:
  * graded side: `feed/live` payloads fetched from statsapi.mlb.com for the five
    sample games (trimmed to status, linescore and box-score player stats;
    `tests/fixtures/settlement_player_box/`);
  * record side: the production `unmatched_samples` of that run, rebuilt into
    the recommendation shape the board writes and checked against the sample's
    own `record_keys` and `record_identity` before use.

Expected values were read from the fixture box scores by hand:
  Kyle Leahy (STL, 823009) 4 K / 9 outs; Tyler Phillips (MIA, 823819) 3 K /
  11 outs; José Ramírez (CLE, 823657) 0 H / 0 R; Lars Nootbaar (AZ, 825035)
  0 R; Esmerlyn Valdez is NOT in the 824630 box score at all.
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
from syndicate.features.shared.settlement_identity import prop_stat_for_record
from syndicate.features.shared.settlement_identity import record_identity

FIXTURES = Path(__file__).parent / "fixtures" / "settlement_player_box"
DATE = "2026-09-12"
GAMES = (823009, 823819, 823657, 825035, 824630)

# The market label each sample's `record_keys` carries, as the board writes it.
_SAMPLE_MARKETS = {
    "823009": "Pitcher Strikeouts",
    "823819": "Pitcher Outs",
    "823657": "Hitter Runs",
    "825035": "Hitter Runs",
    "824630": "Hitter Hits",
}
# Display names as the record carries them (the keys keep the accents).
_SAMPLE_NAMES = {
    "823009": "Kyle Leahy",
    "823819": "Tyler Phillips",
    "823657": "José Ramírez",
    "825035": "Lars Nootbaar",
    "824630": "Esmerlyn Valdez",
}


def _feed(game_pk: int) -> dict:
    return json.loads((FIXTURES / f"feed_live_{game_pk}.json").read_text(encoding="utf-8"))


def _samples() -> list[dict]:
    return json.loads((FIXTURES / "unmatched_samples_2026-09-18.json").read_text(encoding="utf-8"))["unmatched_samples"]


def _recommendation(*, game_id: str, home: str, away: str, market: str, player: str, side: str, line: str, team: str, **extra) -> dict:
    return {
        "game_id": game_id,
        "gamePk": int(game_id),
        "event_id": None,
        "sport": "MLB",
        "sport_slug": "mlb",
        "matchup": f"{away} @ {home}",
        "market": market,
        "pick": f"{side.upper()} {player}",
        "team": team,
        "entity": None,
        "player_name": player,
        "line": line,
        "odds": extra.pop("odds", "-110"),
        "market_key": extra.pop("market_key", None),
        **extra,
    }


def _record(recommendation: dict) -> dict:
    return {"sport": "mlb", "record_type": "recommendation", "result": "pending", "recommendation": recommendation}


def _sample_record(sample: dict, **overrides) -> dict:
    identity = sample["record_identity"]
    game_id = identity["game_ids"][0]
    fields = dict(
        game_id=game_id,
        home=identity["home"].upper(),
        away=identity["away"].upper(),
        market=_SAMPLE_MARKETS[game_id],
        player=_SAMPLE_NAMES[game_id],
        side=identity["side"],
        line=f"{sample['record_line']:.1f}",
        team=identity["team"].upper(),
    )
    fields.update(overrides)
    return _record(_recommendation(**fields))


def _sample(game_id: str) -> dict:
    return next(sample for sample in _samples() if sample["record_identity"]["game_ids"] == [game_id])


def _box_rows() -> list[dict]:
    rows = [go.mlb_player_box_row_from_feed(_feed(game_pk)) for game_pk in GAMES]
    return [row for row in rows if row is not None]


def _all_rows() -> list[dict]:
    rows: list[dict] = []
    for game_pk in GAMES:
        feed = _feed(game_pk)
        rows.extend(go.mlb_score_rows_from_feed(feed))
        box = go.mlb_player_box_row_from_feed(feed)
        if box is not None:
            rows.append(box)
    return rows


def _grade(record: dict, rows: list[dict] | None = None):
    return find_graded_row(record, rows if rows is not None else _all_rows(), sport="mlb", markets_compatible=_markets_compatible)


# --------------------------------------------------------------------------
# The fixtures are what they claim to be
# --------------------------------------------------------------------------


def test_sample_records_rebuild_to_the_production_keys_and_identity():
    for sample in _samples():
        record = _sample_record(sample)
        assert sorted(_evaluation_record_keys(record)) == sample["record_keys"]
        assert record_identity(record, sport="mlb").summary() == sample["record_identity"]
        assert sample["detail"] == "prop_not_graded"


def test_box_rows_from_real_feeds():
    rows = {row["game_id"]: row for row in _box_rows()}
    assert set(rows) == {str(game_pk) for game_pk in GAMES}
    leahy = next(player for player in rows["823009"]["players"] if player["name"] == "Kyle Leahy")
    assert leahy["id"] == 681517 and leahy["team"] == "STL"
    assert leahy["pitcher"]["strikeouts"] == 4.0 and leahy["pitcher"]["outs"] == 9.0
    ramirez = next(player for player in rows["823657"]["players"] if player["id"] == 608070)
    assert ramirez["name_key"] == "jose ramirez" and ramirez["hitter"]["hits"] == 0.0
    # A box row carries no verdict of its own.
    for row in rows.values():
        assert go.is_player_box_row(row) and not go.is_score_row(row)
        assert "result" not in row and "actual" not in row and "pnl" not in row


def test_a_rostered_player_who_did_not_play_is_absent_not_zero():
    feed = copy.deepcopy(_feed(823009))
    players = feed["liveData"]["boxscore"]["teams"]["home"]["players"]
    key = next(key for key, player in players.items() if player["person"]["fullName"] == "Kyle Leahy")
    players[key]["stats"] = {"batting": {}, "pitching": {}}
    row = go.mlb_player_box_row_from_feed(feed)
    assert all(player["name"] != "Kyle Leahy" for player in row["players"])


def test_unfinished_postponed_and_called_games_emit_no_box_row():
    unfinished = copy.deepcopy(_feed(823009))
    unfinished["gameData"]["status"].update({"abstractGameState": "Live", "codedGameState": "I", "detailedState": "In Progress", "statusCode": "I"})
    assert go.mlb_player_box_row_from_feed(unfinished) is None
    postponed = copy.deepcopy(_feed(823009))
    postponed["gameData"]["status"].update({"abstractGameState": "Final", "codedGameState": "D", "detailedState": "Postponed", "statusCode": "DI"})
    assert go.mlb_player_box_row_from_feed(postponed) is None
    called = copy.deepcopy(_feed(823009))
    called["gameData"]["status"]["detailedState"] = "Completed Early"
    called["liveData"]["linescore"]["innings"] = called["liveData"]["linescore"]["innings"][:6]
    assert go.mlb_player_box_row_from_feed(called) is None
    # ...while its segment score rows still emit.
    assert {row["segment"] for row in go.mlb_score_rows_from_feed(called)} == {"first1", "first3", "first5"}


# --------------------------------------------------------------------------
# The production samples
# --------------------------------------------------------------------------


def test_the_production_samples_settle_from_the_box_score():
    expected = {
        "823009": ("win", 4.0, "strikeouts"),  # over 3.5, 4 K
        "823819": ("loss", 11.0, "outs"),  # over 13.5, 11 outs
        "823657": ("win", 0.0, "batter_runs_scored"),  # under 0.5, 0 R
        "825035": ("win", 0.0, "batter_runs_scored"),  # under 0.5, 0 R
    }
    for sample in _samples():
        game_id = sample["record_identity"]["game_ids"][0]
        outcome = _grade(_sample_record(sample))
        if game_id == "824630":
            # Not in the box at all: named, pending, never "0 hits".
            assert (outcome.row, outcome.reason, outcome.detail) == (None, "market_not_graded", "player_not_in_boxscore")
            continue
        assert outcome.phase == "box_score", (game_id, outcome)
        assert (outcome.row["result"], outcome.row["actual"], outcome.row["market"]) == expected[game_id]
        assert outcome.row["line"] == sample["record_line"] and outcome.row["odds"] is None and outcome.row["pnl"] is None
        assert outcome.row["game_id"] == game_id


@pytest.mark.parametrize(
    "side, line, result",
    [
        ("over", "3.5", "win"),
        ("under", "3.5", "loss"),
        ("over", "4.0", "push"),
        ("under", "4.0", "push"),
        ("over", "4.5", "loss"),
        ("under", "5.5", "win"),
    ],
)
def test_any_line_either_side(side, line, result):
    outcome = _grade(_sample_record(_sample("823009"), side=side, line=line))
    assert (outcome.phase, outcome.row["result"]) == ("box_score", result)


@pytest.mark.parametrize(
    "market, market_key, actual",
    [
        ("Pitcher Hits Allowed", None, 2.0),
        ("Pitcher Earned Runs", None, 0.0),
        ("Pitcher Walks", None, 0.0),
        ("Pitcher Outs", None, 9.0),
        ("Pitcher Strikeouts", "strikeouts", 4.0),
        ("strikeouts", None, 4.0),
        ("outs recorded", "pitcher_outs", 9.0),
    ],
)
def test_every_pitcher_stat_and_both_spellings(market, market_key, actual):
    outcome = _grade(_sample_record(_sample("823009"), market=market, market_key=market_key, line="0.5"))
    assert outcome.phase == "box_score", outcome
    assert outcome.row["actual"] == actual


def test_hitter_stats_and_the_ladder_line_form():
    # Nootbaar 825035: over 0.5 runs at "0.5", and the ladder pick "Over 1+".
    record = _sample_record(_sample("825035"), side="over", market="Hitter Hits", market_key="batter_hits")
    outcome = _grade(record)
    assert (outcome.phase, outcome.row["result"], outcome.row["actual"]) == ("box_score", "loss", 0.0)
    ladder = copy.deepcopy(record)
    ladder["recommendation"]["pick"] = "Over 1+"
    assert _grade(ladder).row["line"] == 0.5
    disagree = copy.deepcopy(record)
    disagree["recommendation"]["pick"] = "Over 2.5"
    assert _grade(disagree).detail == "line_disagrees_with_selection"


# --------------------------------------------------------------------------
# Refusals are named, and nothing defaults
# --------------------------------------------------------------------------


def test_a_hitter_strikeout_prop_never_settles_against_the_pitcher_line():
    # `canonical_market_key` folds "Hitter Strikeouts" onto the PITCHER
    # `strikeouts` key. Without the group check this would settle Nootbaar's
    # batting strikeouts against a pitcher table.
    record = _sample_record(_sample("825035"), market="Hitter Strikeouts")
    assert prop_stat_for_record("mlb", record) == (None, "prop_market_group_disagrees")
    outcome = _grade(record)
    assert (outcome.row, outcome.detail) == (None, "prop_market_group_disagrees")
    mixed = _sample_record(_sample("823009"), market="Hitter Strikeouts", market_key="strikeouts")
    assert _grade(mixed).detail == "prop_market_group_disagrees"


@pytest.mark.parametrize(
    "overrides, detail",
    [
        ({"market": "Hitter Stolen Bases"}, "prop_market_unmapped"),
        ({"market": "Pitcher Total outs"}, "prop_market_unmapped"),
        ({"side": "yes"}, "prop_side_unmapped"),
        ({"market": "First 5 Strikeouts"}, "prop_segment_not_graded"),
        ({"player": "Kyle Lehay"}, "player_not_in_boxscore"),
        ({"market": "Hitter Hits"}, "player_group_absent"),
    ],
)
def test_refusals_are_named(overrides, detail):
    record = _sample_record(_sample("823009"), **overrides)
    if overrides.get("side") == "yes":
        record["recommendation"]["pick"] = "Yes Kyle Leahy"
    outcome = _grade(record)
    assert (outcome.row, outcome.reason, outcome.detail) == (None, "market_not_graded", detail)


def test_player_id_first_and_a_disagreeing_name_refuses():
    by_id = _sample_record(_sample("823009"), player="K. Leahy", player_id=681517)
    outcome = _grade(by_id)
    assert (outcome.phase, outcome.row["player"], outcome.row["player_id"]) == ("box_score", "Kyle Leahy", 681517)
    # The id names Leahy; the name names another pitcher in the same game.
    other = next(
        player["name"]
        for player in go.mlb_player_box_row_from_feed(_feed(823009))["players"]
        if "pitcher" in player and player["id"] != 681517
    )
    wrong = _sample_record(_sample("823009"), player=other, player_id=681517)
    assert _grade(wrong).detail == "player_id_name_disagree"


def test_a_record_on_another_game_never_reads_this_box():
    # Leahy's record pointed at a game he did not play in: the id join holds,
    # the box for THAT game has no Leahy, and it stays pending.
    record = _sample_record(_sample("823009"), game_id="823819", home="MIA", away="LAD", team="MIA")
    assert _grade(record).detail == "player_not_in_boxscore"


def test_a_card_row_still_wins_over_the_box():
    card_row = {
        "sport": "mlb", "game_id": "823009", "game_pk": 823009, "market": "strikeouts", "selection": "over",
        "player": "Kyle Leahy", "team": "STL", "home": "STL", "away": "CWS", "title": "CWS @ STL",
        "line": 3.5, "actual": 4.0, "odds": "+105", "result": "win", "pnl": 1.05,
    }
    outcome = _grade(_sample_record(_sample("823009")), [card_row, *_all_rows()])
    assert outcome.phase == "game_id" and outcome.row is card_row


def test_without_box_rows_the_old_detail_is_unchanged():
    score_only = [row for row in _all_rows() if not go.is_player_box_row(row)]
    outcome = _grade(_sample_record(_sample("823009")), score_only)
    assert (outcome.row, outcome.detail) == (None, "prop_not_graded")
    # Box rows exist for the date but not for THIS game.
    others = [row for row in _all_rows() if row.get("game_id") != "823009" or not go.is_player_box_row(row)]
    assert _grade(_sample_record(_sample("823009")), others).detail == "no_player_box_for_game"


def test_game_markets_are_unchanged_by_box_rows():
    total = _record(
        {
            "game_id": "823009", "gamePk": 823009, "sport": "MLB", "sport_slug": "mlb", "matchup": "CWS @ STL",
            "market": "Total", "market_key": "totals", "pick": "Over 1.5", "line": "1.5", "team": "-", "odds": "-110",
        }
    )
    outcome = _grade(total)
    assert outcome.phase == "game_score" and outcome.row["result"] == "win"


# --------------------------------------------------------------------------
# Reachability: the real samples, through settlement, off != on
# --------------------------------------------------------------------------


def _grader_rows(*, with_boxscore: bool) -> list[dict]:
    feeds = {game_pk: _feed(game_pk) for game_pk in GAMES}
    if not with_boxscore:
        for feed in feeds.values():
            feed["liveData"].pop("boxscore", None)
    with patch("syndicate.features.mlb.market_accuracy.build_market_accuracy_payload", return_value={"days": []}), \
         patch.object(go, "_mlb_slate_game_pks", return_value=set(GAMES)), \
         patch.object(go, "_load_cached_mlb_feed", side_effect=lambda _date, pk: feeds.get(pk)):
        return go.graded_rows_for_date("mlb", DATE)


def test_the_grader_emits_one_box_row_per_regulation_final():
    rows = _grader_rows(with_boxscore=True)
    assert sum(1 for row in rows if go.is_player_box_row(row)) == 5
    assert sum(1 for row in rows if go.is_score_row(row)) == 20
    diagnostics = go.score_row_diagnostics("mlb", DATE)
    assert diagnostics["player_box_rows"] == 5 and diagnostics["score_rows"] == 20
    assert diagnostics["players_boxed"] == sum(len(row["players"]) for row in rows if go.is_player_box_row(row))


def _write_pending(ledger_path: Path, recommendation: dict) -> dict:
    prediction = record_prediction(
        query={"question": "mlb board", "selected_date": DATE, "sport": "mlb"},
        response={"selected_date": DATE, "recommendations": []},
        persist=True,
        ledger_path=ledger_path,
    )
    return record_recommendation(prediction_record=prediction, recommendation=recommendation, persist=True, ledger_path=ledger_path)


def _settle_samples(*, with_boxscore: bool) -> tuple[dict, dict]:
    rows = _grader_rows(with_boxscore=with_boxscore)
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


def test_reachability_the_samples_settle_with_box_rows_and_not_without():
    off_summary, off_records = _settle_samples(with_boxscore=False)
    assert off_summary["settled"] == 0
    assert off_summary["unmatched_market_not_graded_detail"] == {"prop_not_graded": 5}
    assert {record["result"] for record in off_records.values()} == {"pending"}

    on_summary, on_records = _settle_samples(with_boxscore=True)
    assert on_summary["settled"] == 4 and on_summary["matched_by_phase"] == {"box_score": 4}
    assert on_summary["unmatched_market_not_graded_detail"] == {"player_not_in_boxscore": 1}
    assert {game: record["result"] for game, record in on_records.items()} == {
        "823009": "win", "823819": "loss", "823657": "win", "825035": "win", "824630": "pending",
    }
    # Priced at the RECORD's odds (-110); its own price is not stamped as the close.
    assert on_records["823009"]["pnl"] == pytest.approx(0.9091)
    assert on_records["823819"]["pnl"] == -1.0
    assert on_records["823009"]["closing_price"] is None
    assert on_summary["graded_row_market_family_counts"]["mlb"]["player_box"] == 5
