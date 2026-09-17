"""Ask the Syndicate x `prop_evidence_v1`: routing, MLB's reference answer, the BvP index.

What is pinned here, and why each one:

* A board-row prop in a provider sport is answered by the provider ALONE, with
  every table layer-tagged and a coverage block -- and the old fetchers still run
  when the provider finds nothing, so a join miss never answers with less.
* MLB's reference tables are served UNCHANGED (content and order), measured
  against a real production answer captured 2026-09-17 (Brett Baty total bases,
  `fixtures/prop_evidence/mlb_ask_capture_baty_2026-09-17.json`), with the
  track-record layer and coverage table after them.
* The batter-vs-pitcher index built on the worker gives the SAME counts as the
  web-side aggregation it replaces, is read in preference to it, and the table
  title states the data's own last date instead of the answer's date.
"""

from __future__ import annotations

import csv
import gzip
import json
import os
from pathlib import Path

import pytest

from scripts import build_mlb_bvp_index as bvp_index
from syndicate.blueprints import ask_the_syndicate_data as ask_data

FIXTURES = Path(__file__).parent / "fixtures" / "prop_evidence"
ROOT = FIXTURES / "root"
BATY_CAPTURE = json.loads((FIXTURES / "mlb_ask_capture_baty_2026-09-17.json").read_text(encoding="utf-8"))

RIVERS_POINTS = {
    "sport": "wnba", "event_id": "0fd1d4ee6d6e720e030e8cefb6a5a591", "market": "player_points",
    "player_name": "Saniya Rivers", "line": 9.5, "side": "over", "segment": "full",
    "home_team": "Atlanta Dream", "away_team": "Connecticut Sun", "commence_time": "2026-09-17T23:30:00Z",
    "kind": "prop", "projection": None,
}
BATY_TOTAL_BASES = {
    "sport": "mlb", "event_id": "86a852d517d266c4d6c74e570caffa06", "market": "batter_total_bases",
    "player_name": "Brett Baty", "line": 1.5, "side": "over", "segment": "full",
    "home_team": "New York Mets", "away_team": "Philadelphia Phillies", "commence_time": "2026-09-17T23:16:00Z",
    "kind": "prop", "projection": None,
}


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(ROOT))
    ask_data._BVP_CACHE.clear()
    ask_data._BVP_THROUGH.clear()
    yield
    ask_data._BVP_CACHE.clear()
    ask_data._BVP_THROUGH.clear()


def _baty_sections():
    """The production answer's sections, split as the four MLB fetchers built them."""
    tables = [dict(t, layer=None) for t in BATY_CAPTURE["tables"]]
    for t in tables:
        t.pop("layer")
    charts = [{"type": "bar", "title": c["title"], "x_label": "", "y_label": "", "points": [{"x": "1", "y": 1.0}]}
              for c in BATY_CAPTURE["charts"]]
    return [
        {"tables": tables[0:1], "charts": charts[0:1], "as_of": "2026-09-17", "sport": "mlb", "evidence": {}},
        {"tables": tables[1:3], "charts": charts[1:2], "as_of": "2026-09-16", "sport": "mlb", "evidence": {}},
        {"tables": tables[3:8], "charts": [], "as_of": "2026-09-17", "sport": "mlb", "evidence": {}},
    ]


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------


def test_provider_sport_prop_is_answered_by_the_provider_alone(monkeypatch):
    called = []
    monkeypatch.setattr(ask_data, "_fetchers_for_sport", lambda sport, q: called.append(sport) or [])
    out = ask_data.collect_focused_evidence("case for Saniya Rivers 9.5", {"selected_date": "2026-09-17"}, board_row=RIVERS_POINTS)
    assert called == []
    block = out["prop_evidence"]
    assert block["provider"] == "basketball:wnba"
    coverage = block["coverage"]
    assert {k for k, v in coverage.items() if v == "filled"} == {
        "player_sim", "recent_form", "matchup", "advanced", "game_sim", "environment"}
    # WNBA has no graded scorecard cell yet and this row carries no skill note:
    # the missing layer is stated, in the coverage block AND the last table.
    assert coverage["track_record"] == "insufficient_sample:no_graded_cell_for_market"
    assert all(t.get("layer") for t in out["tables"])
    assert not any(t["title"].startswith("SmartSim projection") for t in out["tables"])  # the old WNBA table
    last = out["tables"][-1]
    assert last["title"] == "What this answer could not show"
    assert last["rows"] == [["Track record", "Not enough graded games yet (no_graded_cell_for_market)"]]


def test_provider_that_finds_nothing_falls_back_to_the_old_fetchers(monkeypatch):
    legacy = {"tables": [{"title": "Last 10 games — Nobody Atall (through 2026-06-01)", "columns": [], "rows": []}],
              "charts": [], "as_of": "2026-06-01", "sport": "wnba"}
    monkeypatch.setattr(ask_data, "_fetchers_for_sport", lambda sport, q: [lambda question, context: legacy])
    row = {**RIVERS_POINTS, "player_name": "Nobody Atall"}
    out = ask_data.collect_focused_evidence("case", {"selected_date": "2026-09-17"}, board_row=row)
    titles = [t["title"] for t in out["tables"]]
    assert "Last 10 games — Nobody Atall (through 2026-06-01)" in titles
    assert titles[-1] == "What this answer could not show"
    assert out["prop_evidence"]["coverage"]["player_sim"].startswith("player_not_found:")


def test_game_rows_are_untouched_by_the_prop_path(monkeypatch):
    section = {"tables": [{"title": "Match sim outlook — A @ B (2026-09-19)", "columns": [], "rows": []}],
               "charts": [], "as_of": "2026-09-19", "sport": "soccer"}
    monkeypatch.setattr(ask_data, "_fetchers_for_sport", lambda sport, q: [lambda question, context: section])
    game_row = {"sport": "soccer", "event_id": "e", "market": "totals", "side": "over", "line": 2.5,
                "home_team": "B", "away_team": "A", "kind": "game"}
    out = ask_data.collect_focused_evidence("case", {"selected_date": "2026-09-19"}, board_row=game_row)
    assert "prop_evidence" not in out
    assert [t["title"] for t in out["tables"]] == ["Match sim outlook — A @ B (2026-09-19)"]


# ---------------------------------------------------------------------------
# MLB reference answer
# ---------------------------------------------------------------------------


def test_mlb_reference_tables_are_served_unchanged_then_track_record(monkeypatch):
    sections = _baty_sections()
    monkeypatch.setattr(ask_data, "_fetchers_for_sport", lambda sport, q: [lambda question, context, s=s: s for s in sections])
    out = ask_data.collect_focused_evidence("case for Brett Baty 1.5", {"selected_date": "2026-09-17"}, board_row=BATY_TOTAL_BASES)
    served = out["tables"]
    reference = BATY_CAPTURE["tables"]
    for got, want in zip(served, reference):
        assert (got["title"], got["columns"], got["rows"]) == (want["title"], want["columns"], want["rows"])
    assert served[len(reference)]["title"].startswith("Track record — MLB batter_total_bases")
    assert served[len(reference)]["layer"] == "track_record"
    assert out["prop_evidence"]["provider"] == "mlb:reference_fetchers"


def test_mlb_reference_tables_are_tagged_by_layer(monkeypatch):
    sections = _baty_sections()
    monkeypatch.setattr(ask_data, "_fetchers_for_sport", lambda sport, q: [lambda question, context, s=s: s for s in sections])
    out = ask_data.collect_focused_evidence("case", {"selected_date": "2026-09-17"}, board_row=BATY_TOTAL_BASES)
    layers = [t["layer"] for t in out["tables"]]
    assert layers[:8] == ["game_sim", "recent_form", "advanced", "matchup", "matchup", "player_sim", "advanced", "matchup"]
    coverage = out["prop_evidence"]["coverage"]
    assert {k for k, v in coverage.items() if v == "filled"} == {
        "game_sim", "recent_form", "advanced", "matchup", "player_sim", "track_record"}
    # Baty's matchup profile carries no park/weather rows on this slate, so the
    # environment layer is honestly unshown -- and says so in the last table.
    assert coverage["environment"].startswith("not_shown:")
    assert out["tables"][-1]["title"] == "What this answer could not show"


def test_park_weather_rows_count_as_the_environment_layer():
    table = {"title": "Matchup profile — X (2026-09-17)", "columns": ["Factor", "Value"],
             "rows": [["K rate", "20.0%"], ["Park HR mult", "1.05"]]}
    ask_data._tag_legacy_layers([table])
    assert table["layer"] == "matchup" and table["also_layers"] == ["environment"]


def test_the_table_cap_keeps_the_coverage_table(monkeypatch):
    many = {"tables": [{"title": f"Last {i} games — P (through 2026-09-01)", "columns": [], "rows": []} for i in range(20)],
            "charts": [], "as_of": "2026-09-01", "sport": "mlb"}
    monkeypatch.setattr(ask_data, "_fetchers_for_sport", lambda sport, q: [lambda question, context: many])
    out = ask_data.collect_focused_evidence("case", {"selected_date": "2026-09-17"}, board_row=BATY_TOTAL_BASES)
    assert len(out["tables"]) == ask_data.MAX_TABLES
    assert out["tables"][-1]["title"] == "What this answer could not show"
    assert out["prop_evidence"]["tables_built"] == 21 and out["prop_evidence"]["tables_served"] == ask_data.MAX_TABLES


def test_wnba_typed_path_reads_min_mean_the_key_the_engine_writes(tmp_path, monkeypatch):
    processed = tmp_path / "processed"
    processed.mkdir()
    source = json.loads((ROOT / "wnba_source/data/processed/cards_sim_detail_2026-09-17.json").read_text(encoding="utf-8"))
    (processed / "cards_sim_detail_2026-09-17.json").write_text(json.dumps(source), encoding="utf-8")
    monkeypatch.setenv("WNBA_BETTING_DATA_ROOT", str(tmp_path))
    result = ask_data._wnba_focused_evidence("Saniya Rivers points tonight", {"selected_date": "2026-09-17"})
    player = next(p for g in source["games"] for side in ("home", "away") for p in g["sim"]["players"][side]
                  if p["player_name"] == "Saniya Rivers")
    assert "minutes" not in player
    rows = result["tables"][0]["rows"]
    assert ["Minutes", f"{player['min_mean']:.1f}", "—"] in rows


# ---------------------------------------------------------------------------
# BvP index
# ---------------------------------------------------------------------------


def _legacy(tmp_path: Path) -> Path:
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    index = {"by_date": {
        "2024-05-01": {"694973": {"694192": {"pa": 3, "hr": 1, "hits": 2, "so": 0, "bb": 0, "hbp": 0, "inplay_pa": 3, "inplay_hits": 2}}},
        "2025-08-10": {"694973": {"694192": {"pa": 4, "hr": 0, "hits": 1, "so": 2, "bb": 1, "hbp": 0, "inplay_pa": 3, "inplay_hits": 1}}},
    }}
    (legacy / "aaa.json").write_text(json.dumps(index), encoding="utf-8")
    # An overlapping second file repeats a date: counted once.
    (legacy / "bbb.json").write_text(json.dumps({"by_date": {"2024-05-01": index["by_date"]["2024-05-01"]}}), encoding="utf-8")
    return legacy


def _raw_chunk(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["game_date", "pitcher", "batter", "events"])
        writer.writeheader()
        writer.writerows(rows)


def test_index_matches_the_web_aggregation_it_replaces(tmp_path, monkeypatch):
    legacy = _legacy(tmp_path)
    mlb_root = tmp_path / "mlb"
    legacy_dest = mlb_root / "cache" / "statcast" / "bvp" / "statcast_bvp_file_daily"
    legacy_dest.parent.mkdir(parents=True)
    legacy.rename(legacy_dest)
    monkeypatch.setenv("MLB_BETTING_DATA_ROOT", str(mlb_root))
    from_web = ask_data._bvp_counts_for_pitcher(694973)

    data_root = tmp_path / "data"
    result = bvp_index.build(data_root, raw_root=tmp_path / "no_raw", legacy_dirs=[legacy_dest])
    shard = json.loads(bvp_index.shard_path(data_root, 694973).read_text(encoding="utf-8"))
    from_index = {int(b): dict(zip(shard["fields"], v)) for b, v in shard["pitchers"]["694973"].items()}
    assert from_index == from_web == {694192: {"pa": 7, "hits": 3, "hr": 1, "so": 2, "bb": 1, "hbp": 0, "inplay_pa": 6, "inplay_hits": 3}}
    assert result["through"] == "2025-08-10" and result["pairs"] == 1


def test_web_reads_the_shard_first_and_titles_the_datas_own_horizon(tmp_path, monkeypatch):
    legacy = _legacy(tmp_path)
    data_root = tmp_path / "data"
    bvp_index.build(data_root, raw_root=tmp_path / "no_raw", legacy_dirs=[legacy])
    mlb_root = data_root / "mlb_source" / "source_artifacts" / "data"
    monkeypatch.setenv("MLB_BETTING_DATA_ROOT", str(mlb_root))
    # No legacy files under this root at all: only the shard can answer.
    assert not (mlb_root / "cache").exists()
    counts = ask_data._bvp_counts_for_pitcher(694973)
    assert counts[694192]["pa"] == 7
    assert ask_data._bvp_through_label(694973, "2026-09-17") == "2025-08-10"


def test_legacy_fallback_also_titles_its_own_horizon(tmp_path, monkeypatch):
    legacy = _legacy(tmp_path)
    mlb_root = tmp_path / "mlb"
    dest = mlb_root / "cache" / "statcast" / "bvp" / "statcast_bvp_file_daily"
    dest.parent.mkdir(parents=True)
    legacy.rename(dest)
    monkeypatch.setenv("MLB_BETTING_DATA_ROOT", str(mlb_root))
    ask_data._bvp_counts_for_pitcher(694973)
    assert ask_data._bvp_through_label(694973, "2026-09-17") == "2025-08-10"


def test_raw_chunks_win_their_dates_and_count_like_the_vendor_scanner(tmp_path):
    legacy = _legacy(tmp_path)
    raw = tmp_path / "raw"
    # 2025-08-10 is ALSO in legacy (4 PA there); raw must replace it, not add to it.
    _raw_chunk(raw / "2025" / "statcast_2025-08-10_2025-08-16.csv.gz", [
        {"game_date": "2025-08-10", "pitcher": "694973", "batter": "694192", "events": "home_run"},
        {"game_date": "2025-08-10", "pitcher": "694973", "batter": "694192", "events": "strikeout_double_play"},
        {"game_date": "2025-08-10", "pitcher": "694973", "batter": "694192", "events": "intent_walk"},
        {"game_date": "2025-08-10", "pitcher": "694973", "batter": "694192", "events": "single"},
        {"game_date": "2025-08-10", "pitcher": "694973", "batter": "694192", "events": "field_out"},
        {"game_date": "2025-08-10", "pitcher": "694973", "batter": "694192", "events": ""},  # not a PA
        {"game_date": "2026-09-16", "pitcher": "694973", "batter": "694192", "events": "hit_by_pitch"},
    ])
    data_root = tmp_path / "data"
    result = bvp_index.build(data_root, raw_root=raw, legacy_dirs=[legacy])
    shard = json.loads(bvp_index.shard_path(data_root, 694973).read_text(encoding="utf-8"))
    counts = dict(zip(shard["fields"], shard["pitchers"]["694973"]["694192"]))
    # legacy 2024-05-01 (3 PA, 2 H, 1 HR, 3 in play, 2 in-play hits) + raw 2025-08-10 (5 PA) + raw 2026-09-16 (1 HBP)
    assert counts == {"pa": 9, "hits": 4, "hr": 2, "so": 1, "bb": 1, "hbp": 1, "inplay_pa": 5, "inplay_hits": 3}
    assert result["sources"]["raw_dates"] == ["2025-08-10", "2026-09-16"]
    assert result["through"] == "2026-09-16"


def test_an_empty_build_writes_nothing(tmp_path):
    data_root = tmp_path / "data"
    result = bvp_index.build(data_root, raw_root=tmp_path / "no_raw", legacy_dirs=[])
    assert result["pairs"] == 0 and result["paths"] == []
    assert bvp_index.index_is_missing(data_root)
    assert not (data_root / bvp_index.INDEX_RELATIVE).exists()
