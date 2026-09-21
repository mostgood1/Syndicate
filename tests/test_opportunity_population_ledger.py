"""The whole priced population is recorded -- published or not -- once per side per day.

`[2026-09-14, user decision: "Build it for all sports"]`, lane `accuracy-assessment-0914`.

The load-bearing tests:
- the sink receives ALL candidates `build_layer2_rows` priced, including rows that never
  become opportunities (grading only published rows is the 2026-09-12 FORBIDDEN
  publication-filter shape);
- first sighting only, across calls (the bound that keeps a day's file small);
- a failing sink or recorder can never take the board down;
- it ships OFF.
"""

from __future__ import annotations

import fnmatch
import json
from datetime import datetime, timezone

import pytest

import syndicate.features.shared.opportunity_population_ledger as pop

NOW = datetime(2026, 9, 14, 17, 0, tzinfo=timezone.utc)


def _row(event_id="evt-1", market="totals", side="over", line=8.5, player=None, segment="full", **extra):
    row = {
        "sport": "mlb",
        "kind": "game" if player is None else "prop",
        "event_id": event_id,
        "market": market,
        "side": side,
        "line": line,
        "segment": segment,
        "commence_time": "2026-09-14T23:05:00Z",
        "home_team": "Home Team",
        "away_team": "Away Team",
        "board_lane": "opportunity",
        "game_state": "pregame",
        "ev_pct": 2.4,
        "model_edge_pct": 1.1,
        "ev_basis": "market_fair",
        "quote": {"price": 105, "fair_probability": 0.4981, "fair_method": "consensus",
                  "books_quoting": 9, "book_age_seconds": 42.0},
        "score": {"score": 1.9, "value_pct": 2.5, "skill_reliability": 0.97},
        "projection": {"model_skill": {"status": "measured", "verdict_class": "parity",
                                       "established_loss_rel": 0.0}},
    }
    if player is not None:
        row["player_name"] = player
    row.update(extra)
    return row


@pytest.fixture(autouse=True)
def _no_publish(monkeypatch):
    calls = []
    import syndicate.features.shared.artifact_publisher as ap

    monkeypatch.setattr(ap, "publish_hot_artifact", lambda path, **_: calls.append(path) or True)
    return calls


# --------------------------------------------------------------------------
# the switch
# --------------------------------------------------------------------------


def test_it_ships_off(monkeypatch):
    monkeypatch.delenv(pop.ENV_FLAG, raising=False)
    assert pop.population_ledger_enabled() is False


@pytest.mark.parametrize("value,expected", [("on", True), ("1", True), ("TRUE", True),
                                            ("off", False), ("", False), ("maybe", False)])
def test_only_an_explicit_on_enables_it(monkeypatch, value, expected):
    monkeypatch.setenv(pop.ENV_FLAG, value)
    assert pop.population_ledger_enabled() is expected


# --------------------------------------------------------------------------
# identity and records
# --------------------------------------------------------------------------


def test_the_key_separates_everything_that_changes_the_bet():
    keys = {
        pop.population_key(_row()),
        pop.population_key(_row(side="under")),
        pop.population_key(_row(line=9.5)),
        pop.population_key(_row(segment="first5")),
        pop.population_key(_row(market="batter_hits", player="A. Hitter", line=0.5)),
        pop.population_key(_row(market="batter_hits", player="B. Hitter", line=0.5)),
    }
    assert len(keys) == 6


def test_the_key_round_trips():
    key = pop.population_key(_row(market="batter_hits", player="A. Hitter", line=0.5, segment="full"))
    parsed = pop.parse_population_key(key)
    assert parsed == {"event_id": "evt-1", "market": "batter_hits", "player_name": "a. hitter",
                      "segment": "full", "side": "over", "line": 0.5}


@pytest.mark.parametrize("bad", [{"market": "totals"}, {"event_id": "e"}, {"event_id": "a|b", "market": "m"}])
def test_an_unkeyable_row_gets_no_key(bad):
    assert pop.population_key(bad) is None


def test_a_record_is_compact_and_copies_rather_than_derives():
    row = _row()
    record = pop.population_record(row, pop.population_key(row), "2026-09-14T17:00:00Z", sport="mlb")
    line = json.dumps(record, sort_keys=True, separators=(",", ":"))
    assert len(line.encode("utf-8")) < 450, "this repeats tens of thousands of times a day"
    assert record["ev"] == 2.4 and record["me"] == 1.1 and record["sc"] == 1.9
    assert record["vc"] == "parity" and record["ln"] == "opportunity" and record["fm"] == "consensus"
    assert record["la"] is None
    # team names are what a final score joins on
    assert record["ht"] == "Home Team" and record["at"] == "Away Team"


# --------------------------------------------------------------------------
# recording
# --------------------------------------------------------------------------


def test_first_sighting_only_across_calls(tmp_path, _no_publish):
    rows = [_row(), _row(side="under")]
    first = pop.record_population(rows, sport="mlb", date="2026-09-14", now=NOW, root=tmp_path)
    second = pop.record_population(rows + [_row(line=9.5)], sport="mlb", date="2026-09-14", now=NOW, root=tmp_path)
    assert first["written"] == 2
    assert second["written"] == 1 and second["already_recorded"] == 2 and second["duplicate"] == 2
    lines = pop.part_path("2026-09-14", "mlb", 0, root=tmp_path).read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3


def test_a_different_date_or_sport_is_a_different_population(tmp_path):
    pop.record_population([_row()], sport="mlb", date="2026-09-14", now=NOW, root=tmp_path)
    assert pop.record_population([_row()], sport="mlb", date="2026-09-15", now=NOW, root=tmp_path)["written"] == 1
    assert pop.record_population([_row()], sport="soccer", date="2026-09-14", now=NOW, root=tmp_path)["written"] == 1


def test_parts_roll_before_part_bytes(tmp_path):
    rows = [_row(event_id=f"evt-{i}") for i in range(40)]
    report = pop.record_population(rows, sport="mlb", date="2026-09-14", now=NOW, root=tmp_path, part_bytes=2000)
    parts = sorted(tmp_path.glob("intelligence/opportunity_population/2026-09-14__mlb__part*.jsonl"))
    assert report["written"] == 40
    assert len(parts) > 1
    assert all(p.stat().st_size <= 2000 for p in parts)
    assert sum(len(p.read_text(encoding="utf-8").splitlines()) for p in parts) == 40


def test_the_day_ceiling_truncates_and_says_so(tmp_path):
    rows = [_row(event_id=f"evt-{i}") for i in range(40)]
    report = pop.record_population(rows, sport="mlb", date="2026-09-14", now=NOW, root=tmp_path, max_day_bytes=3000)
    assert report["truncated_at_day_ceiling"] is True
    assert 0 < report["written"] < 40
    # a truncated side was never keyed, so it is not silently marked as recorded
    keys = pop.keys_path("2026-09-14", "mlb", root=tmp_path).read_text(encoding="utf-8").splitlines()
    assert len(keys) == report["written"]


def test_unkeyable_and_non_mapping_rows_are_counted_not_written(tmp_path):
    report = pop.record_population([_row(), {"market": "x"}, "junk", None], sport="mlb", date="2026-09-14",
                                   now=NOW, root=tmp_path)
    assert report["written"] == 1 and report["unkeyable"] == 3


def test_it_publishes_only_parts_written_this_call(tmp_path, _no_publish):
    pop.record_population([_row()], sport="mlb", date="2026-09-14", now=NOW, root=tmp_path)
    assert len(_no_publish) == 1
    pop.record_population([_row()], sport="mlb", date="2026-09-14", now=NOW, root=tmp_path)
    assert len(_no_publish) == 1, "nothing new, nothing sent"


def test_the_sidecar_is_not_publishable_and_the_parts_are_allowlisted(tmp_path):
    from syndicate.features.shared.artifact_publisher import HOT_ARTIFACT_PATTERNS

    part = "reports/intelligence/opportunity_population/2026-09-14__mlb__part000.jsonl"
    sidecar = "reports/intelligence/opportunity_population/2026-09-14__mlb.keys"
    assert any(fnmatch.fnmatch(part, pattern) for pattern in HOT_ARTIFACT_PATTERNS)
    assert not any(fnmatch.fnmatch(sidecar, pattern) for pattern in HOT_ARTIFACT_PATTERNS)


# --------------------------------------------------------------------------
# the wiring: ALL candidates reach the sink, and the sink cannot hurt the board
# --------------------------------------------------------------------------


def _grid_row(**overrides):
    row = {
        "sport": "wnba", "event_id": "evt-1", "kind": "prop", "market": "player_points",
        "segment": "full", "line": 18.5, "player_name": "A. Player", "home_team": "Home",
        "away_team": "Away", "commence_time": "2099-01-01T00:00:00Z", "sides": ["over", "under"],
        "books_quoting": 2, "cells": {},
        "best": {
            "over": {"price": -110, "bookmaker": "draftkings", "books_quoting": 2, "age_seconds": 30.0},
            "under": {"price": -110, "bookmaker": "fanduel", "books_quoting": 2, "age_seconds": 30.0},
        },
    }
    row.update(overrides)
    return row


def test_the_sink_receives_every_candidate_not_only_opportunities():
    from syndicate.features.shared.layer2_board import build_layer2_rows

    received = []
    # No projection: both sides are BUILT, neither scores, so neither is an opportunity.
    result = build_layer2_rows([_grid_row()], population_sink=received.extend)
    assert result["candidates"] == 2
    assert list(result.get("opportunities") or []) == []
    assert len(received) == 2, "the unpublished population is exactly what must be recorded"
    assert {c.get("side") for c in received} == {"over", "under"}


def test_without_a_sink_the_builder_is_unchanged():
    from syndicate.features.shared.layer2_board import build_layer2_rows

    assert build_layer2_rows([_grid_row()])["candidates"] == 2


def test_a_sink_that_raises_cannot_take_the_board_down():
    from syndicate.features.shared.layer2_board import build_layer2_rows

    def boom(_candidates):
        raise RuntimeError("recorder exploded")

    rows = build_layer2_rows([_grid_row(projection={"edge_vs_market_pct": 6.0})], population_sink=boom)
    assert rows["candidates"] == 2


# --------------------------------------------------------------------------
# one sighting per PHASE  [2026-09-17, lane model-scorecard-cron, "Recorder live coverage"]
# --------------------------------------------------------------------------

LIVE_NOW = datetime(2026, 9, 15, 0, 30, tzinfo=timezone.utc)  # after the 23:05Z first pitch


def test_a_side_first_priced_pregame_is_recorded_again_when_live_at_the_same_line(tmp_path):
    """Off != on: before the change the second call wrote 0 (same identity, same line)."""
    pregame = pop.record_population([_row(side="home", market="h2h", line=None)], sport="mlb",
                                    date="2026-09-14", now=NOW, root=tmp_path)
    live = pop.record_population([_row(side="home", market="h2h", line=None, game_state="live")], sport="mlb",
                                 date="2026-09-14", now=LIVE_NOW, root=tmp_path)
    again = pop.record_population([_row(side="home", market="h2h", line=None, game_state="live")], sport="mlb",
                                  date="2026-09-14", now=LIVE_NOW, root=tmp_path)
    assert pregame["written"] == 1 and pregame["live_pending"] == 0
    assert live["written"] == 1 and live["live_pending"] == 1
    assert again["written"] == 0 and again["duplicate"] == 1
    records = [json.loads(line) for line in
               pop.part_path("2026-09-14", "mlb", 0, root=tmp_path).read_text(encoding="utf-8").splitlines()]
    assert [r["gs"] for r in records] == ["pregame", "live"]
    assert records[0]["k"] == records[1]["k"], "the identity key on the record is unchanged"


def test_an_absent_game_state_falls_back_to_the_sighting_clock(tmp_path):
    before = pop.record_population([_row(game_state=None)], sport="mlb", date="2026-09-14", now=NOW, root=tmp_path)
    after = pop.record_population([_row(game_state=None)], sport="mlb", date="2026-09-14", now=LIVE_NOW,
                                  root=tmp_path)
    assert before["written"] == 1 and after["written"] == 1 and after["live_pending"] == 1


def test_the_sidecar_distinguishes_the_live_sighting(tmp_path):
    pop.record_population([_row(game_state="live")], sport="mlb", date="2026-09-14", now=LIVE_NOW, root=tmp_path)
    keys = pop.keys_path("2026-09-14", "mlb", root=tmp_path).read_text(encoding="utf-8").split()
    assert keys == [pop.population_key(_row()) + pop.LIVE_KEY_SUFFIX]


# --------------------------------------------------------------------------
# score_v2 on the record (lane layer2-score-outcome-calibration, 2026-09-21)
# --------------------------------------------------------------------------


def _scoring_grid_row():
    """A grid row the builder actually SCORES (one book on both sides -> a same-book fair)."""
    return {
        "sport": "mlb", "event_id": "evt-9", "kind": "game", "market": "totals", "segment": "full",
        "line": 8.5, "player_name": None, "home_team": "St. Louis Cardinals",
        "away_team": "Colorado Rockies", "commence_time": "2026-09-14T23:15:00Z",
        "sides": ["over", "under"], "books_quoting": 11,
        "game": {"state": "pregame", "status_token": "6:15P CT"},
        "best": {
            "over": {"price": -110, "bookmaker": "draftkings", "age_seconds": 52.0, "books_quoting": 9},
            "under": {"price": -105, "bookmaker": "draftkings", "age_seconds": 60.0, "books_quoting": 9},
        },
    }


def test_a_record_copies_score_v2_and_the_priced_bookmaker():
    row = _row()
    row["quote"] = {**(row.get("quote") or {}), "bookmaker": "kalshi"}
    row["score_v2"] = {"score_v2": 1.234567, "ev_net_pct": 2.5, "fee_basis": "kalshi_series_from_market"}
    record = pop.population_record(row, pop.population_key(row), "2026-09-14T17:00:00Z", sport="mlb")
    assert (record["s2"], record["n2"], record["fb"], record["bk"]) == (1.2346, 2.5, "kalshi_series_from_market", "kalshi")
    line = json.dumps(record, sort_keys=True, separators=(",", ":"))
    assert len(line.encode("utf-8")) < 520, "this repeats tens of thousands of times a day"


def test_a_row_without_score_v2_records_nulls_not_a_guess():
    record = pop.population_record(_row(), pop.population_key(_row()), "2026-09-14T17:00:00Z", sport="mlb")
    assert record["s2"] is None and record["n2"] is None and record["fb"] is None


def test_reachability_the_builders_sink_carries_score_v2_onto_the_record():
    """Through the REAL builder and sink -- the path production records from -- not a
    hand-built row: every scored candidate the sink receives yields a non-null `s2`."""
    from syndicate.features.shared.layer2_board import build_layer2_rows

    received = []
    result = build_layer2_rows([_scoring_grid_row()], population_sink=received.extend)
    scored = [c for c in received if c.get("score") is not None]
    assert scored, "fixture produced no scored candidate -- the test would prove nothing"
    for candidate in scored:
        record = pop.population_record(candidate, pop.population_key(candidate), "2026-09-14T17:00:00Z", sport="mlb")
        assert record["s2"] is not None and record["n2"] is not None
        assert record["fb"] == "none" and record["bk"] == "draftkings"
    assert result["candidates"] == 2
