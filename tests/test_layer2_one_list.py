"""One list: the Layer 2 board's picks reach the evaluation ledger (lane intelligence-evidence-coverage)."""

from __future__ import annotations

import json

import pytest

from syndicate.features.shared import layer2_ledger as l2

_CARD = {
    "sport": "wnba",
    "sport_slug": "wnba",
    "event_id": "6608125b38823d94d6eef41f1717d86c",
    "kind": "prop",
    "market": "player_threes",
    "market_key": "player_threes",
    "segment": "full",
    "side": "over",
    "line": 1.5,
    "player_name": "Naz Hillmon",
    "selection": "Naz Hillmon",
    "home_team": "Atlanta Dream",
    "away_team": "New York Liberty",
    "odds": 163,
    "commence_time": "2026-10-07T23:30:00Z",
    "model_probability": 0.45,
    "score": {"value_pct": 4.2},
    "detail": "Our sim has ...",
}


def test_pick_id_ignores_book_price_and_board_fields():
    moved = dict(_CARD, odds=150, score={"value_pct": 9.9}, detail="changed", bookmaker="dk")
    assert l2.pick_id(moved) == l2.pick_id(_CARD)


def test_pick_id_separates_line_side_and_player():
    base = l2.pick_id(_CARD)
    assert l2.pick_id(dict(_CARD, line=2.5)) != base
    assert l2.pick_id(dict(_CARD, side="under")) != base
    assert l2.pick_id(dict(_CARD, player_name="Jonquel Jones")) != base


def test_first_sightings_keeps_only_the_date_and_new_picks(tmp_path):
    tomorrow = dict(_CARD, commence_time="2026-10-08T23:30:00Z", player_name="Other")
    records, counts = l2.first_sightings([_CARD, _CARD, tomorrow], "2026-10-07", reports_root=tmp_path)
    assert counts["new"] == 1 and counts["other_date"] == 1 and counts["already"] == 1
    record = records[0]
    assert record["source"] == "layer2_shortlist" and record["pick_id"] == l2.pick_id(_CARD)
    # Volatile board fields are not in the ledger payload (they would re-mint the id).
    assert "score" not in record and "detail" not in record
    assert record["implied_probability"] == 0.45 and record["odds"] == 163
    # Nothing marked until the write succeeded; then the pick is not re-recorded.
    l2.mark_recorded(records, "2026-10-07", reports_root=tmp_path)
    again, counts2 = l2.first_sightings([_CARD], "2026-10-07", reports_root=tmp_path)
    assert again == [] and counts2["already"] == 1


def test_late_evening_eastern_game_belongs_to_its_eastern_date(tmp_path):
    # 01:30Z on 10-08 is 21:30 ET on 10-07.
    late = dict(_CARD, commence_time="2026-10-08T01:30:00Z")
    records, _ = l2.first_sightings([late], "2026-10-07", reports_root=tmp_path)
    assert len(records) == 1


def test_mlb_record_carries_the_statsapi_game_pk(tmp_path):
    from syndicate.features.shared.team_aliases import canonical_team

    card = dict(
        _CARD,
        sport="mlb",
        sport_slug="mlb",
        event_id="oddsapi-hash",
        market="batter_rbis",
        player_name="Mauricio Dubon",
        home_team="Atlanta Braves",
        away_team="Los Angeles Dodgers",
        commence_time="2026-10-07T23:00:00Z",
    )
    index = {(canonical_team("mlb", "Atlanta Braves"), canonical_team("mlb", "Los Angeles Dodgers")): [{"game_pk": 849833, "game_date": "2026-10-07T23:05:00Z"}]}
    records, counts = l2.first_sightings([card], "2026-10-07", reports_root=tmp_path, mlb_index=index)
    assert records[0]["game_pk"] == 849833
    assert records[0]["oddsapi_event_id"] == "oddsapi-hash" and "event_id" not in records[0]
    assert counts["mlb_pk_stamped"] == 1


def test_board_cards_carry_pick_id():
    from syndicate.features.shared.layer2_board import layer2_rows_to_board_cards

    row = {
        "sport": "wnba",
        "event_id": "e1",
        "kind": "prop",
        "market": "player_threes",
        "segment": "full",
        "side": "over",
        "line": 1.5,
        "player_name": "Naz Hillmon",
        "home_team": "Atlanta Dream",
        "away_team": "New York Liberty",
        "commence_time": "2026-10-07T23:30:00Z",
        "quote": {"price": 163, "bookmaker": "betrivers", "fair_probability": 0.39, "books_quoting": 7},
        "score": {"value_pct": 4.2, "score": 3.1},
        "ev_pct": 4.2,
    }
    (card,) = layer2_rows_to_board_cards([row])
    assert card["pick_id"] == l2.pick_id(row)


# ---------------------------------------------------------------- the recorder

@pytest.fixture()
def recorder(tmp_path, monkeypatch):
    import pipeline.intelligence_state as state

    calls = []
    monkeypatch.setattr(state, "read_layer2_shortlist", lambda date: {"cards": [_CARD]})
    monkeypatch.setattr(state, "reports_root", lambda: tmp_path)
    import syndicate.features.shared.intelligence_evaluation as ie

    monkeypatch.setattr(ie, "build_intelligence_evaluation_bundle", lambda **kw: calls.append(kw) or {})
    return state, calls


def test_recorder_is_off_by_default(recorder, monkeypatch):
    state, calls = recorder
    monkeypatch.delenv("SYNDICATE_LEDGER_RECORD_LAYER2", raising=False)
    assert state.maybe_record_layer2_board_to_evaluation_ledger("2026-10-07") is None
    assert calls == []


def test_recorder_on_records_once_per_pick_per_date(recorder, monkeypatch):
    state, calls = recorder
    monkeypatch.setenv("SYNDICATE_LEDGER_RECORD_LAYER2", "1")
    first = state.maybe_record_layer2_board_to_evaluation_ledger("2026-10-07")
    assert first["new"] == 1 and len(calls) == 1
    sent = calls[0]["response"]["recommendations"]
    assert sent[0]["source"] == "layer2_shortlist"
    assert calls[0]["query"]["query_type"] == "layer2_board_state" and calls[0]["persist"] is True
    second = state.maybe_record_layer2_board_to_evaluation_ledger("2026-10-07")
    assert second["new"] == 0 and len(calls) == 1


def test_recorder_failure_never_raises(recorder, monkeypatch):
    state, _ = recorder
    monkeypatch.setenv("SYNDICATE_LEDGER_RECORD_LAYER2", "1")
    monkeypatch.setattr(state, "read_layer2_shortlist", lambda date: (_ for _ in ()).throw(RuntimeError("boom")))
    assert state.maybe_record_layer2_board_to_evaluation_ledger("2026-10-07") is None
