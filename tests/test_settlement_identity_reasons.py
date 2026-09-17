"""`game_not_graded` is split into `game_absent` and `market_not_graded`.

Production 2026-09-17 reported 6,815 `game_not_graded` misses while every sample
named a game the graded index DID hold: a full-game total on a game the season
card graded only for props and one moneyline. One token for "we never graded
this game" and "we graded this game, not this market" sent the diagnosis at the
join instead of the grader.

Graded side: the production card payload for 2026-09-11 (real rows, no score
rows). Record side: the production unmatched samples for the same games.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from syndicate.features.shared import graded_outcomes as go
from syndicate.features.shared.evaluation_settlement import _markets_compatible
from syndicate.features.shared.settlement_identity import NO_KEY_MATCH_REASONS
from syndicate.features.shared.settlement_identity import find_graded_row
from syndicate.features.shared.settlement_identity import record_segment

FIXTURES = Path(__file__).parent / "fixtures" / "settlement_final_scores"
DATE = "2026-09-11"


def _card_rows() -> list[dict]:
    payload = json.loads((FIXTURES / f"card_payload_{DATE}.json").read_text(encoding="utf-8"))
    with patch("syndicate.features.mlb.market_accuracy.build_market_accuracy_payload", return_value=payload):
        return go._mlb_card_graded_rows_for_date(DATE)


def _sample_totals_record(game_id: str) -> dict:
    samples = json.loads((FIXTURES / "unmatched_samples_2026-09-17.json").read_text(encoding="utf-8"))["unmatched_samples"]
    sample = next(s for s in samples if s["record_identity"]["game_ids"] == [game_id])
    identity = sample["record_identity"]
    line = f"{sample['record_line']:.1f}"
    return {
        "sport": "mlb",
        "record_type": "recommendation",
        "result": "pending",
        "recommendation": {
            "game_id": game_id,
            "gamePk": int(game_id),
            "sport": "MLB",
            "sport_slug": "mlb",
            "matchup": f"{identity['away'].upper()} @ {identity['home'].upper()}",
            "market": "Total",
            "market_key": "totals",
            "pick": f"Over {line}",
            "team": "-",
            "line": line,
            "odds": "-110",
        },
    }


def test_indexed_game_wrong_market_is_market_not_graded():
    rows = _card_rows()
    assert any(row["game_id"] == "822684" for row in rows), "the card grades this game"
    outcome = find_graded_row(_sample_totals_record("822684"), rows, sport="mlb", markets_compatible=_markets_compatible)
    assert outcome.row is None
    assert outcome.reason == "market_not_graded"
    assert outcome.detail == "no_score_rows_for_game"


def test_unindexed_game_is_game_absent():
    rows = [row for row in _card_rows() if row["game_id"] != "822684"]
    assert rows and not any(row["game_id"] == "822684" for row in rows)
    outcome = find_graded_row(_sample_totals_record("822684"), rows, sport="mlb", markets_compatible=_markets_compatible)
    assert (outcome.row, outcome.reason, outcome.detail) == (None, "game_absent", None)


def test_vocabulary_problems_still_outrank_the_game_reasons():
    record = _sample_totals_record("822684")
    record["recommendation"].update({"market": "Moneyline", "market_key": "h2h", "pick": "Moneyline", "matchup": "", "line": "-"})
    outcome = find_graded_row(record, _card_rows(), sport="mlb", markets_compatible=_markets_compatible)
    assert outcome.reason == "selection_unmapped"


def test_reason_tokens_are_the_counter_keys_and_unclassified_stays_last():
    assert NO_KEY_MATCH_REASONS == (
        "team_unresolved", "selection_unmapped", "game_absent", "market_not_graded", "game_id_absent", "unclassified",
    )


def test_record_segment_reads_every_place_a_segment_is_written():
    def seg(**recommendation):
        return record_segment({"recommendation": recommendation})

    assert seg(market="Total", market_key="totals") == "full"
    assert seg(market="First 5 Total") == "first5"
    assert seg(market="F5 Moneyline") == "first5"
    assert seg(market="totals", market_key="totals_1st_3_innings") == "first3"
    assert seg(market="Total", segment="first1") == "first1"
    assert seg(market="Live Total") == "full"
    assert seg(market="Hitter Total Bases") == "full"
    # Unmapped segment words and contradictions refuse.
    assert seg(market="2nd Inning Total") == "unrecognized"
    assert seg(market="First 5 Total", segment="full") == "unrecognized"
