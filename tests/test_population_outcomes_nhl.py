"""`population_outcomes_nhl` -- every NHL row in the priced population, settled from the NHL API.

Fixtures and their provenance are described in `tests/test_bet_status_nhl.py`: real
api-web.nhle.com payloads trimmed under `tests/fixtures/nhl_settlement/`, and OddsAPI rows the
NHL collector wrote for CAR @ VGK on 2026-06-06 (Stanley Cup Final G3, 4-5 in double overtime).

The records here are built the way production builds them, end to end: the OddsAPI rows go
through `local_nhl_odds._append_nhl_book_quotes` (the real quote-row code), each row is keyed by
`opportunity_population_ledger.population_key` and recorded as `population_record` would
(k / t / sport / ct / ht / at / px / fp / me), and `bucket_search.scorecard_record` shapes it --
so the settler sees exactly the lowercased key fields a recorder row carries.

HAND-VERIFIED against the raw box: Mitch Marner 3 G, 1 A, 4 P, 10 SOG; Jack Eichel 0 G, 1 SOG,
4 blocked; Jordan Staal 5 SOG; regulation 4-4; final 5-4 VGK.
"""

from __future__ import annotations

import copy
import csv
import importlib.util
import json
import math
import pathlib
from datetime import datetime, timezone
from urllib.parse import urlsplit

import pytest

from syndicate.features.shared import population_outcomes_nhl as pon
from syndicate.features.shared.population_outcomes_nhl import GRADER_VERSION, SPORTS, NhlPopulationSettler

_SRC = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "bucket_search.py"
_spec = importlib.util.spec_from_file_location("bucket_search", _SRC)
bs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bs)

FIX = pathlib.Path(__file__).resolve().parent / "fixtures" / "nhl_settlement"
SIGHTED_AT = "2026-06-06T22:00:00Z"
TODAY = "2026-06-07"


class FakeNhle:
    """api-web.nhle.com from the fixtures. Records every URL; an unknown path is a failed read."""

    def __init__(self, overrides: dict | None = None) -> None:
        self.urls: list[str] = []
        self.overrides = overrides or {}

    def __call__(self, url: str):
        self.urls.append(url)
        path = urlsplit(url).path
        name = path[len("/v1/"):].replace("/", "_") + ".json"
        if name in self.overrides:
            return copy.deepcopy(self.overrides[name])
        target = FIX / name
        return json.loads(target.read_text(encoding="utf-8")) if target.is_file() else None


def _nan_to_none(value):
    return None if isinstance(value, float) and math.isnan(value) else value


@pytest.fixture
def records(monkeypatch) -> dict[str, dict]:
    """key-without-event -> a recorder record, built through the real row and key code."""
    pd = pytest.importorskip("pandas")
    from syndicate import local_nhl_odds
    from syndicate.features.shared import odds_book_quotes
    from syndicate.features.shared.opportunity_population_ledger import population_key

    captured: list[dict] = []
    monkeypatch.setattr(odds_book_quotes, "append_book_quotes", lambda **kwargs: captured.extend(kwargs["rows"]))
    with (FIX / "oddsapi_team_odds_2026-06-06.csv").open(encoding="utf-8") as handle:
        team = list(csv.DictReader(handle))
    game = team[0]
    local_nhl_odds._append_nhl_book_quotes(pd.DataFrame([
        {"event_id": row["event_id"], "commence_time": row["commence_time"], "home_team": row["home"],
         "away_team": row["away"], "bookmaker_key": row["bookmaker_key"], "market": row["market"],
         "outcome_name": row["outcome_name"], "outcome_price": float(row["outcome_price"]),
         "outcome_point": float(row["outcome_point"]) if row["outcome_point"] else None}
        for row in team
    ]), date="2026-06-06", kind="game")
    with (FIX / "oddsapi_props_lines_2026-06-06.csv").open(encoding="utf-8") as handle:
        lines = list(csv.DictReader(handle))
    local_nhl_odds._append_nhl_book_quotes(pd.DataFrame([
        {"market": row["market"], "player": row["player_name"], "line": float(row["line"]),
         "odds": float(row[f"{side.lower()}_price"]), "side": side, "book": row["book"],
         "event_id": game["event_id"], "commence_time": game["commence_time"],
         "home_team": game["home"], "away_team": game["away"]}
        for row in lines for side in ("OVER", "UNDER")
    ]), date="2026-06-06", kind="prop")

    out: dict[str, dict] = {}
    for row in captured:
        board = {**row, "side": row["selection"], "line": _nan_to_none(row["line"])}
        key = population_key(board)
        assert key, board
        out.setdefault(key.split("|", 1)[1], {
            "k": key, "t": SIGHTED_AT, "sport": "nhl", "ct": row["commence_time"],
            "ht": row["home_team"], "at": row["away_team"], "px": row["price"], "fp": 0.5, "me": 1.0,
        })
    return out


def shaped(record: dict, **changes) -> dict:
    out, why = bs.scorecard_record(record)
    assert out is not None, why
    return {**out, **changes}


def test_grader_version_and_sports():
    assert GRADER_VERSION == "nhl/1"
    assert SPORTS == frozenset({"nhl"})


def test_the_keys_are_the_recorder_spelling(records):
    assert "h2h||full|home|" in records
    assert "totals||full|over|5.5" in records
    assert "sog|mitch marner|full|over|1.5" in records


def test_game_lines_from_the_final(records):
    settler = NhlPopulationSettler(fetch_json=FakeNhle())
    assert settler(shaped(records["h2h||full|home|"])) == ("win", "nhl_final")
    assert settler(shaped(records["h2h||full|away|"])) == ("loss", "nhl_final")
    assert settler(shaped(records["spreads||full|home|1.5"])) == ("win", "nhl_final")
    assert settler(shaped(records["spreads||full|away|-1.5"])) == ("loss", "nhl_final")
    assert settler(shaped(records["spreads||full|away|1.5"])) == ("win", "nhl_final")
    assert settler(shaped(records["spreads||full|home|-1.5"])) == ("loss", "nhl_final")
    assert settler(shaped(records["totals||full|over|5.5"])) == ("win", "nhl_final")
    assert settler(shaped(records["totals||full|under|6.0"])) == ("loss", "nhl_final")


def test_regulation_three_way_and_periods(records):
    """DERIVED from the real h2h / totals records: market and segment changed, names untouched."""
    settler = NhlPopulationSettler(fetch_json=FakeNhle())
    ml = records["h2h||full|home|"]
    assert settler(shaped(ml, market="h2h_3_way", side="draw")) == ("win", "nhl_linescore")
    assert settler(shaped(ml, market="h2h_3_way", side="home")) == ("loss", "nhl_linescore")
    total = records["totals||full|over|5.5"]
    # P2 VGK 4-0, P3 CAR 4-0, P1 0-0.
    assert settler(shaped(total, segment="p2", line=3.5)) == ("win", "nhl_linescore")
    assert settler(shaped(total, segment="p1", side="under", line=0.5)) == ("win", "nhl_linescore")
    # A level first period on a two-way h2h pushes.
    assert settler(shaped(ml, segment="p1")) == ("push", "nhl_linescore")
    assert settler(shaped(ml, segment="p3")) == ("loss", "nhl_linescore")


def test_props_win_loss_push_and_void(records):
    settler = NhlPopulationSettler(fetch_json=FakeNhle())
    assert settler(shaped(records["sog|mitch marner|full|over|1.5"])) == ("win", "nhl_box")
    assert settler(shaped(records["goals|mitch marner|full|over|0.5"])) == ("win", "nhl_box")
    assert settler(shaped(records["points|mitch marner|full|under|1.5"])) == ("loss", "nhl_box")
    assert settler(shaped(records["sog|jack eichel|full|over|2.5"])) == ("loss", "nhl_box")
    assert settler(shaped(records["assists|shea theodore|full|over|0.5"])) == ("win", "nhl_box")
    # DERIVED line: Staal took exactly 5 shots.
    assert settler(shaped(records["sog|jordan staal|full|over|1.5"], line=5.0)) == ("push", "nhl_box")
    # DERIVED name: Alexander Holtz, on Vegas's roster, did not dress for G3.
    assert settler(shaped(records["sog|jack eichel|full|over|2.5"], player_name="alexander holtz")) == (None, "dnp_void")
    # DERIVED market: the goalie who dressed and never played.
    assert settler(shaped(records["sog|jack eichel|full|over|2.5"], market="player_saves",
                          player_name="adin hill", line=0.5)) == (None, "dnp_void")


def test_permanent_refusals_read_nothing(records):
    fake = FakeNhle()
    settler = NhlPopulationSettler(fetch_json=fake)
    prop = records["sog|mitch marner|full|over|1.5"]
    assert settler(shaped(prop, market="player_hits")) == (None, "nhl_prop_market_not_mapped")
    assert settler(shaped(prop, segment="p1")) == (None, "nhl_prop_needs_full_game")
    assert settler(shaped(records["h2h||full|home|"], market="first_goal")) == (None, "unmapped_market")
    assert settler(shaped(records["h2h||full|home|"], segment="first5")) == (None, "unsupported_segment:first5")
    assert fake.urls == []


def test_non_nhl_records_are_not_handled(records):
    fake = FakeNhle()
    settler = NhlPopulationSettler(fetch_json=fake)
    other = shaped(records["h2h||full|home|"], sport="nba")
    assert not settler.handles(other)
    assert settler(other) is None
    assert fake.urls == []


def test_not_started_and_not_final(monkeypatch):
    """The real 2026-09-19 preseason slate, every game FUT on the NHL API."""
    record = {"k": "evt-mtl-tor|totals||full|over|5.5", "t": "2026-09-19T20:00:00Z", "sport": "nhl",
              "ct": "2026-09-19T23:00:00Z", "ht": "Toronto Maple Leafs", "at": "Montreal Canadiens", "px": -110}
    monkeypatch.setattr(pon, "_utcnow", lambda: datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc))
    fake = FakeNhle()
    assert NhlPopulationSettler(fetch_json=fake)(shaped(record)) == (None, "not_started")
    assert fake.urls == []  # before kickoff nothing is read

    monkeypatch.setattr(pon, "_utcnow", lambda: datetime(2026, 9, 20, 3, 0, tzinfo=timezone.utc))
    fake = FakeNhle()
    assert NhlPopulationSettler(fetch_json=fake)(shaped(record)) == (None, "not_started")
    assert any(urlsplit(url).path == "/v1/score/2026-09-19" for url in fake.urls)

    # DERIVED state: the same game LIVE in the 3rd period.
    score = json.loads((FIX / "score_2026-09-19.json").read_text(encoding="utf-8"))
    game = next(g for g in score["games"] if g["id"] == 2026010006)
    game.update({"gameState": "LIVE", "periodDescriptor": {"number": 3, "periodType": "REG"},
                 "awayTeam": {**game["awayTeam"], "score": 2}, "homeTeam": {**game["homeTeam"], "score": 3}})
    live = NhlPopulationSettler(fetch_json=FakeNhle({"score_2026-09-19.json": score}))
    assert live(shaped(record)) == (None, "game_not_final")


def test_reachability_real_records_grade_only_through_the_settler(records):
    """off != on. Without the settler a prop is `player_prop` and a line has no chip to join."""
    prop = records["sog|mitch marner|full|over|1.5"]
    line = records["h2h||full|home|"]
    graded, ungraded = bs.grade_population([prop, line], {}, today=TODAY)
    assert not graded
    assert ungraded.get("player_prop") == 1
    assert sum(ungraded.values()) == 2

    settler = NhlPopulationSettler(fetch_json=FakeNhle())
    graded, ungraded = bs.grade_population([prop, line], {}, today=TODAY, extra_settler=settler)
    assert ungraded == {}
    assert len(graded) == 2 and {row["y"] for row in graded} == {1.0}
    assert {row["sport"] for row in graded} == {"nhl"}
    assert settler.counters["graded_from:nhl_box"] == 1 and settler.counters["graded_from:nhl_final"] == 1


def test_disk_cache_keeps_final_payloads_only(tmp_path, records, monkeypatch):
    settler = NhlPopulationSettler(fetch_json=FakeNhle(), cache_dir=tmp_path)
    assert settler(shaped(records["sog|mitch marner|full|over|1.5"])) == ("win", "nhl_box")
    assert len(list((tmp_path / "nhle").glob("*.json"))) == 3  # final score date + box + roster

    offline = NhlPopulationSettler(fetch_json=lambda url: None, cache_dir=tmp_path)
    assert offline(shaped(records["goals|mitch marner|full|over|0.5"])) == ("win", "nhl_box")
    assert offline.feed.counters["nhle_requests"] == 0

    monkeypatch.setattr(pon, "_utcnow", lambda: datetime(2026, 9, 20, 3, 0, tzinfo=timezone.utc))
    pregame = {"k": "evt|h2h||full|home|", "t": "2026-09-19T20:00:00Z", "sport": "nhl", "ct": "2026-09-19T23:00:00Z",
               "ht": "Toronto Maple Leafs", "at": "Montreal Canadiens", "px": -110}
    NhlPopulationSettler(fetch_json=FakeNhle(), cache_dir=tmp_path)(shaped(pregame))
    assert len(list((tmp_path / "nhle").glob("*.json"))) == 3  # a FUT slate is not kept
