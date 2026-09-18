"""NFL and NCAAF prop evidence over PRODUCTION-SLICED fixtures (web disk, 2026-09-17).

Every file under `tests/fixtures/prop_evidence/root/{nfl,ncaaf}_source` is cut
from the real production artifact of the same path -- rows filtered, never
typed -- and the board rows below are served `/api/board` prop rows for the same
slate. A fixture that invents both sides of a join proves nothing
(`learnings.md` 2026-09-05).

THE ONE EXCEPTION, NAMED: `nfl_source/_dev_machine_only/nfl_fantasy_usage_2025.json`.
Production web holds ZERO `nfl_fantasy_usage_*` files (allowlisted, never
published), so no production slice exists. The file is Jahmyr Gibbs's 17 lines
from the real producer's (`scripts/build_nfl_fantasy_usage.py`) output on the
dev machine, kept outside every probed path so the default fixture root matches
production, and swapped in only by the test that proves the reader's wiring.

The one hand-built subject is `GIBBS_WEEK1`: production has no week-1 board rows
left, so it carries the served row's shape with week 1's real fixture
(`2026_01_NO_DET`, schedule_2026.csv) -- the only game whose prop file IS its own
week, i.e. the only non-stale path production can exercise.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from syndicate.features.shared import prop_evidence
from syndicate.features.shared.prop_evidence import common as C
from syndicate.features.shared.prop_evidence import football
from syndicate.features.shared.prop_evidence.contract import LAYER_ORDER, Layer

ROOT = Path(__file__).parent / "fixtures" / "prop_evidence" / "root"
NFL = ROOT / "nfl_source"
NCAAF = ROOT / "ncaaf_source"
DEV_USAGE = NFL / "_dev_machine_only" / "nfl_fantasy_usage_2025.json"

_SKILL = {"correlation": None, "sample_games": 0, "status": "unmeasured",
          "verdict": "model never backtested -- projection is unvalidated"}
GIBBS_RECEPTIONS = {
    "sport": "nfl", "event_id": "56e8897681915f7ec92baeee952bb1ae", "market": "Receptions", "player_name": "Jahmyr Gibbs",
    "line": 4.5, "side": "over", "segment": "full", "home_team": "Buffalo Bills", "away_team": "Detroit Lions",
    "commence_time": "2026-09-18T00:15:00Z", "kind": "prop",
    "projection": {"basis": "nfl_prop_model_probability", "edge_vs_market_pct": 1.59, "market_fair_prob_over": 0.438,
                   "model_prob_over": 0.4539, "model_skill": _SKILL, "player_team": "DET", "projected": 4.277777777777778,
                   "rate_source": "prior_season_fallback", "side": "over", "sim_source": "nfl_prior_season_fallback",
                   "source": "nfl_prop_model"},
}
JAMESON_WILLIAMS_RECEPTIONS = {**GIBBS_RECEPTIONS, "player_name": "Jameson Williams", "projection": None}
GOFF_PASSING_TDS = {
    **GIBBS_RECEPTIONS, "market": "Passing TDs", "player_name": "Jared Goff", "line": 1.5,
    "projection": {**GIBBS_RECEPTIONS["projection"], "edge_vs_market_pct": 14.21, "market_fair_prob_over": 0.5355,
                   "model_prob_over": 0.6776, "projected": 2.0},
}
GIBBS_WEEK1 = {**GIBBS_RECEPTIONS, "event_id": "week1", "home_team": "Detroit Lions", "away_team": "New Orleans Saints",
               "commence_time": "2026-09-13T17:00:00Z", "projection": None}

JOSEPH_WILLIAMS_RECEPTIONS = {
    "sport": "ncaaf", "event_id": "03297aa8a399c223aa1cc6aa923d9bc6", "market": "Receptions", "player_name": "Joseph Williams",
    "line": 4.5, "side": "over", "segment": "full", "home_team": "Northwestern Wildcats", "away_team": "Colorado Buffaloes",
    "commence_time": "2026-09-19T23:30:00Z", "kind": "prop", "projection": None,
}
PRIBULA_PASSING_TDS_UNDER = {
    "sport": "ncaaf", "event_id": "eda972dc55ded05916deafa37efab9c3", "market": "Passing TDs", "player_name": "Beau Pribula",
    "line": 1.5, "side": "under", "segment": "full", "home_team": "West Virginia Mountaineers", "away_team": "Virginia Cavaliers",
    "commence_time": "2026-09-19T23:30:00Z", "kind": "prop", "projection": None,
}
ANGELI_PASSING_TDS = {
    "sport": "ncaaf", "event_id": "f06e90b4212fb514f3564ded9f190107", "market": "Passing TDs", "player_name": "Steve Angeli",
    "line": 1.5, "side": "over", "segment": "full", "home_team": "Pittsburgh Panthers", "away_team": "Syracuse Orange",
    "commence_time": "2026-09-17T23:30:00Z", "kind": "prop", "projection": None,
}


def _clear_ncaaf_resolver_caches() -> None:
    from syndicate.features.ncaaf import oddsapi_lines

    for name in ("_alias_map", "_mascot_tails", "fbs_canonical_names"):
        fn = getattr(oddsapi_lines, name, None)
        if hasattr(fn, "cache_clear"):
            fn.cache_clear()


@pytest.fixture(autouse=True)
def _data_root(monkeypatch):
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(ROOT))
    monkeypatch.delenv("SYNDICATE_NCAAF_SOURCE_ROOT", raising=False)
    # `resolve_team`'s alias map is lru-cached against whichever registry the
    # first caller saw; the fixture registry must be the one read here.
    _clear_ncaaf_resolver_caches()
    yield
    _clear_ncaaf_resolver_caches()


def _build(row: dict, date: str = "2026-09-17"):
    return prop_evidence.build_prop_evidence(row, selected_date=date)


def _tables(evidence, layer: Layer) -> list[dict]:
    return [t for t in evidence.to_section()["tables"] if t.get("layer") == layer.value]


def _rows(evidence, layer: Layer) -> list[list]:
    return [row for t in _tables(evidence, layer) for row in t["rows"]]


def _csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


# ---------------------------------------------------------------------------
# NFL
# ---------------------------------------------------------------------------


def test_nfl_board_row_declares_all_seven_layers_and_names_the_unpublished_one():
    evidence = _build(GIBBS_RECEPTIONS)
    coverage = evidence.coverage()
    assert list(coverage) == [layer.value for layer in LAYER_ORDER]
    assert evidence.provider == "football:nfl"
    # Production state 2026-09-17: no per-game NFL player stat artifact on web.
    assert coverage["recent_form"].startswith("artifact_missing:nfl_fantasy_usage_2026.json")
    assert {k for k, v in coverage.items() if v != "filled"} == {"recent_form"}, coverage


def test_nfl_player_sim_reads_the_line_row_and_labels_the_assumed_shape():
    evidence = _build(GIBBS_WEEK1, "2026-09-13")
    payload = json.loads((NFL / "nfl_prop_projections_2026_wk1.json").read_text(encoding="utf-8"))
    row = next(r for r in payload["sim_rows"] if r["market"] == "receptions::jahmyr gibbs::4.5")
    layer = evidence.layers[Layer.PLAYER_SIM]
    assert layer.facts["prob_over"] == pytest.approx(row["sim_projection"])
    assert layer.facts["mean"] == pytest.approx(row["projected_value"])
    assert layer.facts["stale_week"] is False and layer.facts["artifact_week"] == 1 == layer.facts["game_week"]
    rows = _rows(evidence, Layer.PLAYER_SIM)
    assert any(r[0] == "Probability basis" and str(r[1]).startswith("ASSUMED SHAPE") for r in rows)
    assert ["Spread (sd) / sample games", "not published by the prop artifact"] in rows
    # The ladder chart carries every published line for this player and stat.
    ladder = [r for r in payload["sim_rows"] if r["market"].startswith("receptions::jahmyr gibbs::")]
    chart = next(c for c in layer.charts if c["title"].startswith("Model P(over) by line"))
    assert len(chart["points"]) == len(ladder) and chart["marker"]["x"] == "4.5"


def test_nfl_stale_week_is_flagged_when_the_prop_file_is_not_the_games_week():
    evidence = _build(GIBBS_RECEPTIONS)
    facts = evidence.layers[Layer.PLAYER_SIM].facts
    assert facts["game_week"] == 2 and facts["artifact_week"] == 1 and facts["stale_week"] is True
    rows = _rows(evidence, Layer.PLAYER_SIM)
    assert any(str(r[0]).startswith("STALE WEEK: priced for week 1") for r in rows)
    assert ["Priced game (artifact)", "New Orleans Saints|Detroit Lions  — NOT this game"] in rows
    # The board row's own number is the same stale week-1 price -- both readers agree.
    assert facts["prob_over"] == pytest.approx(GIBBS_RECEPTIONS["projection"]["model_prob_over"], abs=1e-4)


def test_nfl_player_without_a_prop_row_gets_the_engine_mean_and_no_invented_probability():
    evidence = _build(JAMESON_WILLIAMS_RECEPTIONS)
    facts = evidence.layers[Layer.PLAYER_SIM].facts
    assert facts["prob_over"] is None
    fantasy = json.loads((NFL / "fantasy" / "nfl_fantasy_projections_2026.json").read_text(encoding="utf-8"))
    index = next(i for i, p in enumerate(fantasy["players"]) if p["name"] == "Jameson Williams")
    week2 = next(r for r in fantasy["week_rows"]["2"] if r[0] == index)
    assert facts["fantasy_week_mean"] == pytest.approx(week2[fantasy["row_columns"].index("receptions")])


def test_nfl_matchup_says_when_the_engine_made_no_opponent_adjustment():
    receptions = _rows(_build(GIBBS_RECEPTIONS), Layer.MATCHUP)
    assert any(r[0] == "Opponent adjustment" and str(r[1]).startswith("none") for r in receptions)
    # Passing TDs IS adjusted by the engine, so it is reported as a percentage.
    goff = _build(GOFF_PASSING_TDS)
    facts = goff.layers[Layer.MATCHUP].facts
    assert facts["opponent"] == "BUF"
    assert facts["engine_week_vs_season"]["week"] != pytest.approx(facts["engine_week_vs_season"]["season"])
    assert any(r[0] == "Opponent/environment adjustment" for r in _rows(goff, Layer.MATCHUP))


def test_nfl_game_sim_reads_the_games_week_and_flags_a_preseason_build():
    evidence = _build(GIBBS_RECEPTIONS)
    layer = evidence.layers[Layer.GAME_SIM]
    row = next(r for r in _csv(NFL / "smartsim2_projections_2026_wk2.csv") if r["game_id"] == "2026_02_DET_BUF")
    assert layer.facts["home_win_rate"] == pytest.approx(float(row["home_win_rate"]))
    assert layer.facts["generated_days_before_kickoff"] == 47
    assert any(str(r[0]).startswith("STALE: generated 2026-08-01") for r in _rows(evidence, Layer.GAME_SIM))
    assert not layer.charts  # no week-2 distribution file is published


def test_nfl_game_sim_probabilities_are_counted_off_the_published_draws():
    evidence = _build(GIBBS_WEEK1, "2026-09-13")
    layer = evidence.layers[Layer.GAME_SIM]
    full = json.loads((NFL / "smartsim2_segment_distributions_2026_wk1.json").read_text(encoding="utf-8"))["games"]["2026_01_NO_DET"]["segments"]["full"]
    assert layer.facts["p_total_over"] == pytest.approx(C.dist_prob_over(full["total_points_dist"], 49.5))
    # margin_dist is home-positive and spread_line 7 favours DET (home): cover = margin > 7.
    assert layer.facts["p_home_cover"] == pytest.approx(C.dist_prob_over(full["margin_dist"], 7.0))
    assert layer.charts and layer.charts[0]["marker"]["x"] == "49.5"


def test_nfl_environment_implied_totals_use_the_sign_checked_against_moneylines():
    evidence = _build(GIBBS_WEEK1, "2026-09-13")
    facts = evidence.layers[Layer.ENVIRONMENT].facts
    assert facts["spread_sign_consistent"] is True
    assert facts["implied_totals"] == {"home": pytest.approx(28.25), "away": pytest.approx(21.25)}
    assert facts["side"] == "home"
    assert "Out" in " ".join(facts["injuries"]["NO"])
    assert ["Roof / weather", "not published (schedule_*.csv carries no roof, surface or weather field)"] in _rows(evidence, Layer.ENVIRONMENT)


def test_nfl_recent_form_fills_from_the_usage_artifact_once_it_is_on_disk(monkeypatch):
    """Reachability in the other direction: the absence above is the reader's, not a dead layer."""
    original = C.first_existing

    def with_usage(local_dir, *relatives):
        if relatives == ("fantasy/nfl_fantasy_usage_2025.json",):
            return DEV_USAGE
        return original(local_dir, *relatives)

    monkeypatch.setattr(C, "first_existing", with_usage)
    evidence = _build(GIBBS_RECEPTIONS)
    layer = evidence.layers[Layer.RECENT_FORM]
    assert layer.filled
    lines = json.loads(DEV_USAGE.read_text(encoding="utf-8"))["player_game_lines"]
    last10 = sorted(lines, key=lambda l: l["week"], reverse=True)[:10]
    assert layer.facts["values"] == [l["receptions"] for l in last10]
    rate = layer.facts["hit_rate"]
    assert rate["line"] == 4.5 and rate["hits"] == sum(1 for l in last10 if l["receptions"] > 4.5)
    assert any(str(r[0]).startswith("LAST SEASON: no 2026 game lines") for r in _rows(evidence, Layer.RECENT_FORM))


def test_removing_the_fantasy_reader_empties_advanced(monkeypatch):
    """Reachability: advanced is filled BY the fantasy projection reader, not by anything beside it."""
    assert _build(GIBBS_RECEPTIONS).layers[Layer.ADVANCED].filled
    monkeypatch.setattr(football, "_nfl_fantasy", lambda season: None)
    assert _build(GIBBS_RECEPTIONS).coverage()["advanced"].startswith("artifact_missing:fantasy/nfl_fantasy_projections_2026.json")


def test_nfl_track_record_reports_the_scorecard_cell_as_insufficient():
    layer = _build(GIBBS_RECEPTIONS).layers[Layer.TRACK_RECORD]
    assert layer.filled
    assert layer.facts["cells"]["28d"]["verdict"] == "insufficient"


def test_names_join_through_initials_without_loosening_the_surname():
    assert football.names_match("DJ Moore", "D.J. Moore")
    assert football.names_match("Audric Estimé", "Audric Estime")
    assert football.names_match("Kenneth Walker III", "Kenneth Walker")
    assert not football.names_match("DJ Moore", "D.J. Moorer")
    assert not football.names_match("Jameson Williams", "Joseph Williams")


# ---------------------------------------------------------------------------
# NCAAF
# ---------------------------------------------------------------------------


def test_ncaaf_player_sim_reads_the_worker_artifact_and_web_never_models(monkeypatch):
    """`ncaaf_prop_projections_2026_wk3.json` in the fixture root is the REAL
    builder's output (`scripts/build_ncaaf_prop_projections.py --season 2026
    --week 3`) over the production-sliced snapshot beside it -- not typed."""
    from syndicate.features.ncaaf import prop_model
    from syndicate.features.ncaaf import prop_projections as pp

    def forbidden(*args, **kwargs):
        raise AssertionError("web must not model NCAAF props")

    for name in ("_read_rows", "_rates", "anytime_td_probability"):
        monkeypatch.setattr(prop_model, name, forbidden)
    for name in ("build_payload", "payload_from_players", "build_prop_projections"):
        monkeypatch.setattr(pp, name, forbidden)
    evidence = _build(JOSEPH_WILLIAMS_RECEPTIONS)
    coverage = evidence.coverage()
    assert list(coverage) == [layer.value for layer in LAYER_ORDER]
    assert coverage["track_record"] == "insufficient_sample:no_graded_cell_for_market"
    assert all(coverage[k] == "filled" for k in ("player_sim", "recent_form", "matchup", "advanced", "game_sim", "environment")), coverage

    artifact = json.loads((NCAAF / "data/ncaaf_prop_projections_2026_wk3.json").read_text(encoding="utf-8"))
    colorado = next(p for p in artifact["players"] if p["name"] == "Joseph Williams" and p["team"] == "Colorado")
    entry = colorado["markets"]["receptions"]
    facts = evidence.layers[Layer.PLAYER_SIM].facts
    assert facts["player_team"] == "Colorado"  # never the Holy Cross namesake the artifact also carries
    assert facts["mean"] == pytest.approx(entry["mean"])
    assert facts["prob_over"] == pytest.approx(pp.prob_over(entry, 4.5))
    assert (facts["artifact_week"], facts["game_week"], facts["stale_week"]) == (3, 3, False)
    rows = _rows(evidence, Layer.PLAYER_SIM)
    assert any(r[0] == "Model skill" and "unmeasured" in r[1] for r in rows)


def test_ncaaf_player_sim_is_a_named_absence_without_the_artifact(monkeypatch):
    """Reachability: the layer is filled BY the artifact reader and nothing else."""
    from syndicate.features.ncaaf import prop_projections as pp

    monkeypatch.setattr(pp, "newest_index_at_or_before", lambda season, week: None)
    coverage = _build(JOSEPH_WILLIAMS_RECEPTIONS).coverage()
    assert coverage["player_sim"].startswith("artifact_missing:ncaaf_prop_projections_2026_wk3.json"), coverage


def test_ncaaf_player_sim_names_a_market_the_model_does_not_price():
    row = {**JOSEPH_WILLIAMS_RECEPTIONS, "market": "Rushing Attempts", "line": 2.5}
    assert _build(row).coverage()["player_sim"].startswith("no_producer:the NCAAF prop model does not price Rushing Attempts")


def test_ncaaf_recent_form_carries_a_season_to_date_row():
    snapshot = _csv(NCAAF / "source_artifacts/data/processed/player_game_stats/ncaaf_player_game_stats_snapshot.csv")
    colorado = [r for r in snapshot if r["player_name"] == "Joseph Williams" and r["team"] == "Colorado" and r["season"] == "2026"]
    evidence = _build(JOSEPH_WILLIAMS_RECEPTIONS)
    season = evidence.layers[Layer.RECENT_FORM].facts["season_to_date"]
    total = sum(float(r["receptions"]) for r in colorado)
    assert season["season"] == 2026 and season["games"] == len(colorado)
    assert season["total"] == pytest.approx(total) and season["per_game"] == pytest.approx(total / len(colorado))
    labels = [r[0] for r in _rows(evidence, Layer.RECENT_FORM)]
    assert f"2026 season to date — total ({len(colorado)} games)" in labels
    assert "2026 season to date — per game" in labels


_BOX_COLUMNS = ("season", "week", "game_id", "player_id", "player_name", "team", "passing_attempts", "passing_yards",
                "passing_tds", "interceptions", "rushing_attempts", "rushing_yards", "receptions", "receiving_yards",
                "anytime_td", "source_snapshot_date")


def _box_for(tmp_path, monkeypatch, rows, subject_row):
    path = tmp_path / "snapshot.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=_BOX_COLUMNS, restval="0")
        writer.writeheader()
        writer.writerows(rows)
    monkeypatch.setattr(C, "first_existing", lambda *a, **k: path)
    from syndicate.features.shared.prop_evidence.contract import PropSubject

    subject = PropSubject.from_board_row(subject_row, selected_date="2026-09-19")
    return subject, football._ncaaf_box(subject, "Colorado", "Northwestern")


def _line(season, week, gid, pid, name, team, rec):
    return {"season": season, "week": week, "game_id": gid, "player_id": pid, "player_name": name, "team": team,
            "receptions": rec, "receiving_yards": rec * 10, "source_snapshot_date": "2026-09-14"}


def test_ncaaf_recent_form_keeps_a_transfers_old_school_games_by_player_id(tmp_path, monkeypatch):
    rows = [
        _line("2025", 5, "O1", "777", "Joseph Williams", "Old School", 6),
        _line("2025", 6, "O2", "777", "Joseph Williams", "Old School", 7),
        _line("2026", 1, "C1", "777", "Joseph Williams", "Colorado", 3),
        _line("2026", 1, "H1", "888", "Joseph Williams", "Holy Cross", 9),  # a namesake: never joined
        _line("2026", 1, "C1", "1", "Somebody Else", "Opponent U", 1),
        _line("2025", 5, "O1", "2", "Somebody Else", "Rival", 1),
    ]
    subject, box = _box_for(tmp_path, monkeypatch, rows, JOSEPH_WILLIAMS_RECEPTIONS)
    assert box.team == "Colorado" and [g["game_id"] for g in box.games] == ["C1"]
    assert [g["game_id"] for g in box.other_school_games] == ["O2", "O1"]
    assert box.elsewhere == ["Holy Cross"]
    layer = football._ncaaf_recent_form(subject, "receptions", "Receptions", box, "Colorado", "Northwestern")
    assert layer.facts["values"] == [3.0, 7.0, 6.0]
    assert layer.facts["other_schools"] == ["Old School"]
    assert layer.facts["season_to_date"]["games"] == 1  # 2026 only; the old-school games are 2025
    assert any("(Old School)" in r[0] for r in layer.tables[0]["rows"])


def test_ncaaf_a_transfer_facing_his_old_school_is_one_person_not_ambiguous(tmp_path, monkeypatch):
    rows = [
        _line("2025", 5, "N1", "777", "Joseph Williams", "Northwestern", 6),
        _line("2026", 1, "C1", "777", "Joseph Williams", "Colorado", 3),
    ]
    _, box = _box_for(tmp_path, monkeypatch, rows, JOSEPH_WILLIAMS_RECEPTIONS)
    assert not box.ambiguous and box.team == "Colorado"
    assert [g["game_id"] for g in box.other_school_games] == ["N1"]


def test_ncaaf_two_people_of_one_name_in_this_game_are_still_refused(tmp_path, monkeypatch):
    rows = [
        _line("2026", 1, "N1", "555", "Joseph Williams", "Northwestern", 6),
        _line("2026", 1, "C1", "777", "Joseph Williams", "Colorado", 3),
    ]
    _, box = _box_for(tmp_path, monkeypatch, rows, JOSEPH_WILLIAMS_RECEPTIONS)
    assert box.ambiguous == ["Colorado", "Northwestern"] and not box.games and not box.other_school_games


def test_ncaaf_recent_form_joins_the_board_team_not_a_same_named_player():
    snapshot = _csv(NCAAF / "source_artifacts/data/processed/player_game_stats/ncaaf_player_game_stats_snapshot.csv")
    same_name = {r["team"] for r in snapshot if r["player_name"] == "Joseph Williams"}
    assert same_name == {"Colorado", "Holy Cross"}  # the collision the join must refuse
    evidence = _build(JOSEPH_WILLIAMS_RECEPTIONS)
    facts = evidence.layers[Layer.RECENT_FORM].facts
    colorado = sorted((r for r in snapshot if r["player_name"] == "Joseph Williams" and r["team"] == "Colorado"),
                      key=lambda r: int(r["week"]), reverse=True)
    assert facts["team"] == "Colorado"
    assert facts["values"] == [float(r["receptions"]) for r in colorado]
    rate = facts["hit_rate"]
    assert (rate["line"], rate["side"]) == (4.5, "over")
    assert rate["hits"] == sum(1 for r in colorado if float(r["receptions"]) > 4.5)


def test_ncaaf_matchup_allowed_is_summed_from_the_opponents_games():
    snapshot = _csv(NCAAF / "source_artifacts/data/processed/player_game_stats/ncaaf_player_game_stats_snapshot.csv")
    games = {r["game_id"] for r in snapshot if r["team"] == "Northwestern"}
    per_game = [sum(float(r["receptions"]) for r in snapshot if r["game_id"] == g and r["team"] != "Northwestern") for g in games]
    evidence = _build(JOSEPH_WILLIAMS_RECEPTIONS)
    facts = evidence.layers[Layer.MATCHUP].facts
    assert facts["opponent"] == "Northwestern"
    assert facts["allowed_games"] == len(per_game)
    assert facts["allowed_per_game"] == pytest.approx(sum(per_game) / len(per_game))


def test_ncaaf_game_sim_joins_a_reversed_fixture_and_says_so():
    evidence = _build(PRIBULA_PASSING_TDS_UNDER)
    layer = evidence.layers[Layer.GAME_SIM]
    row = next(r for r in _csv(NCAAF / "data/smartsim2_projections_2026_wk3.csv") if r["game_id"] == "401856802")
    assert (row["home_team"], row["away_team"]) == ("Virginia", "West Virginia")  # board says the opposite
    assert layer.facts["board_reversed"] is True and layer.facts["week"] == 3
    assert layer.facts["home_win_rate"] == pytest.approx(float(row["home_win_rate"]))
    assert any(r[0] == "HOME/AWAY DISAGREE" for r in _rows(evidence, Layer.GAME_SIM))
    assert layer.charts  # total-points distribution for game 401856802
    # Recent form uses the UNDER side of the board row.
    assert evidence.layers[Layer.RECENT_FORM].facts["hit_rate"]["side"] == "under"


def test_ncaaf_week_is_placed_by_week_state_not_by_the_calendar():
    facts = _build(JOSEPH_WILLIAMS_RECEPTIONS).layers[Layer.GAME_SIM].facts
    assert facts["week"] == 3 and facts["week_resolution"] == "week_state"


def test_removing_the_snapshot_reader_empties_the_box_score_layers(monkeypatch):
    """Reachability: form, matchup and advanced are filled BY the snapshot reader."""
    monkeypatch.setattr(football, "_ncaaf_box", lambda subject, home, away: None)
    coverage = _build(JOSEPH_WILLIAMS_RECEPTIONS).coverage()
    for layer in ("recent_form", "matchup", "advanced"):
        assert coverage[layer].startswith("artifact_missing:ncaaf_player_game_stats_snapshot.csv"), coverage
    assert coverage["game_sim"] == "filled"


def test_ncaaf_player_with_no_box_lines_is_a_named_absence():
    coverage = _build(ANGELI_PASSING_TDS).coverage()
    assert coverage["recent_form"].startswith("player_not_found:Steve Angeli has no Syracuse/Pittsburgh lines")
    assert coverage["game_sim"] == "filled"
