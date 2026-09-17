"""NHL prop evidence over PRODUCTION-SLICED fixtures (web disk, read 2026-09-17).

Every file under `tests/fixtures/prop_evidence/root/nhl_source` is cut from the
real production artifact of the same path -- `props_recommendations_2026-06-09`,
`_2026-06-10` (header-only), `source_artifacts/.../_2026-06-14`, `_2026-06-28`
(header-only), `predictions_2026-06-09`, `lineups_2026-06-09/-10` (CAR and VGK rows),
`player_rates_latest` (those players' ids plus both `E. Pettersson` rows),
the four `team_*_latest` files whole, and `raw/player_game_stats.csv` (every
CAR/VGK game: the tested players' rows plus one row per side). For the board rows
below, the provider gives byte-identical tables over the unsliced production files.

THE BOARD ROWS ARE CONSTRUCTED, because there is no NHL slate on 2026-09-17 and
so no served NHL board row exists. Their SHAPE is a served WNBA
`/api/board/layer2-shortlist` row; their MARKET KEYS are the ones the code path
writes, verified by reading it:

  * OddsAPI books: `syndicate/local_nhl_odds.py:545` requests
    `player_points,player_assists,player_goals,player_shots_on_goal`;
    `:546-561` maps them to the display codes `POINTS / ASSISTS / GOALS / SOG`;
    `:874-884` (`_append_nhl_book_quotes`, called with that frame at `:938`)
    writes `market` = `_nhl_segment_of(code)[1]`, which is the code unchanged
    (`_nhl_segment_of("SOG") == ("full", "SOG")`).
  * `syndicate/features/shared/odds_book_quotes.py:553,578` (`_normalize`) passes
    `market` through verbatim, and `syndicate/features/shared/layer2_board.py:130-141`
    copies it onto every board candidate as an identity field. So an NHL book
    prop reaches the board as `SOG` (lowercased by `PropSubject.market_key` to `sog`).
  * Kalshi quotes carry `canonical_market_key(sport, stat)`
    (`kalshi_catalogue.py:1434`), i.e. `player_points` / `player_saves` from
    `market_keys.py:595-620` `_HOCKEY`; `book_quote_prop_market` relabels football
    only (`odds_book_quotes.py:923-924`). A saves prop therefore arrives as
    `player_saves`.

The game is the real 2026-06-09 (ET) Stanley Cup Final game, Carolina at Vegas,
puck drop `2026-06-10T00:00:00Z` -- the `gamePk 2025030414` row of the game log
and the only row of `predictions_2026-06-09.csv`.
"""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path

import pytest

from syndicate.features.shared import prop_evidence
from syndicate.features.shared.prop_evidence import common as C
from syndicate.features.shared.prop_evidence import nhl
from syndicate.features.shared.prop_evidence.contract import LAYER_ORDER, Layer

ROOT = Path(__file__).parent / "fixtures" / "prop_evidence" / "root"
NHL = ROOT / "nhl_source"
PROPS_0609 = NHL / "data" / "processed" / "props_recommendations_2026-06-09.csv"
GAME_LOG = NHL / "source_artifacts" / "data" / "raw" / "player_game_stats.csv"
PREDICTIONS_0609 = NHL / "data" / "processed" / "predictions_2026-06-09.csv"

EICHEL_ID = "8478403"


def _board_row(**overrides):
    """A row in the served layer2-shortlist shape (keys from the WNBA board, 2026-09-17)."""
    row = {
        "away_team": "Carolina Hurricanes",
        "board_lane": "opportunity",
        "commence_time": "2026-06-10T00:00:00Z",
        "ev_basis": "market_fair",
        "ev_pct": None,
        "event_id": "nhl-2025030414",
        "game": {"away_score": None, "home_score": None, "matchup": "CAR @ VGK",
                 "start_time_utc": "2026-06-10T00:00:00+00:00", "state": "pregame", "status_token": "7:00P CT"},
        "game_state": "pregame",
        "home_team": "Vegas Golden Knights",
        "is_live": False,
        "kind": "prop",
        "line": None,
        "market": None,
        "market_state": "pregame",
        "model_edge_basis": None,
        "model_edge_pct": None,
        "model_ev_pct": None,
        "player_name": None,
        "quote": {"bookmaker": "draftkings", "price": -110, "books_quoting": 1},
        "segment": "full",
        "side": None,
        "sport": "nhl",
    }
    row.update(overrides)
    return row


EICHEL_SOG_UNDER = _board_row(player_name="Jack Eichel", market="SOG", line=2.5, side="under")
SLAVIN_POINTS = _board_row(player_name="Jaccob Slavin", market="POINTS", line=0.5, side="over")
HART_SAVES = _board_row(player_name="Carter Hart", market="player_saves", line=24.5, side="over")


@pytest.fixture(autouse=True)
def _data_root(monkeypatch):
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(ROOT))


def _build(row, date="2026-06-09"):
    return prop_evidence.build_prop_evidence(row, selected_date=date)


def _csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _tables(evidence, layer: Layer) -> list[dict]:
    return [t for t in evidence.to_section()["tables"] if t.get("layer") == layer.value]


def _row_labels(evidence, layer: Layer) -> list[str]:
    return [str(r[0]) for t in _tables(evidence, layer) for r in t["rows"]]


# --- coverage ---------------------------------------------------------------


def test_every_layer_is_declared_and_a_book_prop_fills_six_with_track_record_named():
    evidence = _build(EICHEL_SOG_UNDER)
    coverage = evidence.coverage()
    assert list(coverage) == [layer.value for layer in LAYER_ORDER]
    assert all(coverage[layer.value] == "filled" for layer in LAYER_ORDER if layer is not Layer.TRACK_RECORD), coverage
    # The scorecard grades NHL (`nhl/1`) but holds no NHL cell yet: a named sample absence.
    scorecard = json.loads((ROOT / "reports/model_scorecard/model_scorecard_latest.json").read_text(encoding="utf-8"))
    assert "nhl" in scorecard["grader"]["sport_versions"]
    assert not [c for w in scorecard["windows"].values() for c in w["cells"] if c["sport"] == "nhl"]
    assert coverage["track_record"] == "insufficient_sample:no_graded_cell_for_market"
    json.dumps(evidence.to_section())  # the Ask response must serialise


def test_board_market_keys_resolve_through_both_vocabularies():
    for key, expected in {
        "sog": "player_shots_on_goal", "points": "player_points", "goals": "player_goals", "assists": "player_assists",
        "player_saves": "player_saves", "player_total_saves": "player_saves", "player_points": "player_points",
        "player_shots_on_goal_alternate": "player_shots_on_goal", "player_blocked_shots": "player_blocked_shots",
    }.items():
        assert nhl.resolve_market(key) == (expected, None), key
    assert nhl.resolve_market("player_goal_scorer_anytime") == ("player_goals", 0.5)
    assert nhl.resolve_market("player_power_play_points") == (None, None)


# --- player_sim: Poisson labelling and the degenerate slate -----------------


def test_player_sim_reads_lambda_from_the_file_and_labels_poisson_as_the_producers_assumption():
    evidence = _build(EICHEL_SOG_UNDER)
    row = next(r for r in _csv(PROPS_0609) if r["player"] == "Jack Eichel" and r["market"] == "SOG")
    layer = evidence.layers[Layer.PLAYER_SIM]
    facts = layer.facts
    assert facts["lambda"] == float(row["proj_lambda"])
    assert facts["file_date"] == "2026-06-09"
    assert facts["prob_basis"] == "poisson_on_mean"
    assert facts["prob_over"] == pytest.approx(C.poisson_prob_over(float(row["proj_lambda"]), 2.5))
    # The file's own p_over at the same line IS Poisson on λ (build_nhl_artifacts.py:205).
    assert float(row["line"]) == 2.5
    assert facts["published_p_over"] == pytest.approx(facts["prob_over"])
    assert facts["prob_under"] == pytest.approx(1.0 - facts["prob_over"])  # half line: no push mass

    labels = _row_labels(evidence, Layer.PLAYER_SIM)
    assert "P(over 2.5) — Poisson(λ)" in labels
    assert not any("sim" in label.lower() and "p(over" in label.lower() for label in labels)
    chart = layer.charts[0]
    assert "Poisson(λ=2)" in chart["title"] and "not a sim distribution" in chart["title"]
    assert chart["y_label"] == "% probability (Poisson)"
    assert chart["marker"]["x"] == "2.5"
    assert sum(p["y"] for p in chart["points"]) == pytest.approx(100.0, abs=0.5)
    assert "props_recommendations_2026-06-09" in _tables(evidence, Layer.PLAYER_SIM)[0]["title"]


def test_a_slate_where_every_row_shares_one_lambda_is_flagged_degenerate():
    sog_lambdas = {r["proj_lambda"] for r in _csv(PROPS_0609) if r["market"] == "SOG"}
    sog_rows = sum(1 for r in _csv(PROPS_0609) if r["market"] == "SOG")
    assert sog_lambdas == {"2.0"}  # the production fact the flag exists for
    evidence = _build(EICHEL_SOG_UNDER)
    facts = evidence.layers[Layer.PLAYER_SIM].facts
    assert facts["degenerate"] is True and facts["degenerate_rows"] == sog_rows
    assert any(label.startswith(f"DEGENERATE SLATE: all {sog_rows} SOG rows") for label in _row_labels(evidence, Layer.PLAYER_SIM))


def test_the_degenerate_flag_is_off_when_lambdas_differ(tmp_path, monkeypatch):
    """Negative control: the same production file with ONE λ changed is not flagged."""
    target = tmp_path / "nhl_source" / "data" / "processed" / PROPS_0609.name
    target.parent.mkdir(parents=True)
    rows = _csv(PROPS_0609)
    fields = list(rows[0].keys())
    other = next(r for r in rows if r["market"] == "SOG" and r["player"] != "Jack Eichel")
    other["proj_lambda"] = "2.4"
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    evidence = _build(EICHEL_SOG_UNDER)
    assert evidence.layers[Layer.PLAYER_SIM].facts["degenerate"] is False
    assert not any(label.startswith("DEGENERATE") for label in _row_labels(evidence, Layer.PLAYER_SIM))


def test_saves_prop_has_no_projection_producer_and_says_so():
    evidence = _build(HART_SAVES)
    assert not any(r["market"] == "SAVES" for r in _csv(PROPS_0609))
    status = evidence.coverage()["player_sim"]
    assert status.startswith("no_producer:") and "local_nhl_odds.py:545" in status
    assert evidence.coverage()["recent_form"] == "filled"


# --- recent_form ------------------------------------------------------------


def _expected_eichel_shots(before: str) -> list[float]:
    rows = [r for r in _csv(GAME_LOG) if r["player_id"] == EICHEL_ID and r["date"] < before]
    rows.sort(key=lambda r: r["date"], reverse=True)
    return [float(r["shots"]) if r["shots"] else 0.0 for r in rows[:10]]


def test_hit_rate_uses_the_board_line_and_side_and_stops_before_this_game():
    evidence = _build(EICHEL_SOG_UNDER)
    facts = evidence.layers[Layer.RECENT_FORM].facts
    expected = _expected_eichel_shots("2026-06-10T00:00:00Z")
    assert facts["values"] == expected
    rate = facts["hit_rate"]
    assert rate["line"] == 2.5 and rate["side"] == "under"
    assert rate["hits"] == rate["under"] == sum(1 for v in expected if v < 2.5)
    # The 2026-06-10T00:00Z row is THIS game; the newest counted game is the 06-06 (ET) one.
    assert facts["newest_game"] == "2026-06-06"
    assert facts["game_types"] == ["playoff"]
    assert facts["matched_by"] == "player_id"


def test_a_blank_shots_cell_on_a_played_skater_row_is_zero_shots():
    blank = [r for r in _csv(GAME_LOG) if r["player_id"] == EICHEL_ID and r["shots"] == ""]
    assert blank and all(nhl._toi_minutes(r["timeOnIce"]) for r in blank)
    assert not any(r["shots"] == "0.0" for r in _csv(GAME_LOG))  # the zero the parser drops (collect.py:114)
    evidence = _build(EICHEL_SOG_UNDER)
    assert 0.0 in evidence.layers[Layer.RECENT_FORM].facts["values"]


def test_removing_the_game_log_reader_empties_recent_form(monkeypatch):
    """Reachability: the layer is filled BY the game-log reader, not by something beside it."""
    monkeypatch.setattr(nhl, "game_log_path", lambda: None)
    evidence = _build(EICHEL_SOG_UNDER)
    assert evidence.coverage()["recent_form"].startswith("artifact_missing:")
    assert "vs_opponent" not in evidence.layers[Layer.MATCHUP].facts


def test_removing_the_props_file_empties_player_sim_only(monkeypatch):
    real = nhl.pick_dated
    monkeypatch.setattr(nhl, "pick_dated", lambda stem, subject: None if stem == "props_recommendations" else real(stem, subject))
    evidence = _build(EICHEL_SOG_UNDER)
    assert evidence.coverage()["player_sim"].startswith("artifact_missing:")
    assert evidence.coverage()["game_sim"] == "filled"


def test_a_dressed_backup_goalie_with_no_ice_time_has_no_games():
    hill_rows = [r for r in _csv(GAME_LOG) if r["player"] == "{'default': 'A. Hill'}"]
    assert hill_rows and all(r["timeOnIce"] == "00:00" for r in hill_rows)
    evidence = _build({**HART_SAVES, "player_name": "Adin Hill"})
    assert evidence.coverage()["recent_form"].startswith("player_not_found:")


def test_goalie_recent_form_reads_saves_and_advanced_reads_actual_save_pct():
    evidence = _build(HART_SAVES)
    facts = evidence.layers[Layer.RECENT_FORM].facts
    hart = sorted((r for r in _csv(GAME_LOG) if r["player"] == "{'default': 'C. Hart'}" and r["date"] < "2026-06-10T00:00:00Z"),
                  key=lambda r: r["date"], reverse=True)[:10]
    assert facts["values"] == [float(r["saves"]) for r in hart]
    save_pct = sum(float(r["saves"]) for r in hart) / sum(float(r["shotsAgainst"]) for r in hart)
    rows = _tables(evidence, Layer.ADVANCED)[0]["rows"]
    assert ["Save % (actual), last 10", C.fmt_pct(save_pct, 1)] in rows


# --- matchup / advanced / game_sim / environment ----------------------------


def test_matchup_reads_the_opponent_profile_and_meetings():
    evidence = _build(SLAVIN_POINTS)
    facts = evidence.layers[Layer.MATCHUP].facts
    assert facts["team"] == "CAR" and facts["opponent"] == "VGK"
    xg = {r["abbr"]: r for r in _csv(NHL / "data/processed/team_xg_latest.csv")}
    assert facts["opponent_profile"]["xg"]["xga60"] == float(xg["VGK"]["xga60"])
    stingier = sum(1 for r in xg.values() if float(r["xga60"]) < float(xg["VGK"]["xga60"]))
    profile = _tables(evidence, Layer.MATCHUP)[-1]["rows"]
    assert profile[0][2].startswith(f"{stingier + 1} of {len(xg)}")
    assert facts["vs_opponent"]["games"] == 3  # Final games 1-3, all before this game


def test_advanced_joins_player_rates_by_the_lineups_player_id():
    evidence = _build(EICHEL_SOG_UNDER)
    rates = next(r for r in _csv(NHL / "data/processed/player_rates_latest.csv") if r["player_id"] == EICHEL_ID)
    lineup = next(r for r in _csv(NHL / "data/processed/lineups_2026-06-09.csv") if r["full_name"] == "Jack Eichel")
    facts = evidence.layers[Layer.ADVANCED].facts
    assert rates["full_name"] == "J. Eichel" and lineup["player_id"] == EICHEL_ID
    assert facts["player_rates"]["shot_weight"] == float(rates["shot_weight"])
    assert facts["lineup"]["proj_toi"] == lineup["proj_toi"]
    labels = _row_labels(evidence, Layer.ADVANCED)
    assert "Not published" in labels
    # `confidence` is 0.5 on every production row: stated as a default.
    value = dict(_tables(evidence, Layer.ADVANCED)[0]["rows"])["Lineup confidence"]
    assert "same value on every row" in value


def test_ambiguous_initial_without_a_lineups_id_is_a_named_absence():
    rates = [r for r in _csv(NHL / "data/processed/player_rates_latest.csv") if r["full_name"] == "E. Pettersson"]
    assert len({r["player_id"] for r in rates}) == 2
    row = _board_row(player_name="Elias Pettersson", market="SOG", line=1.5, side="over",
                     home_team="Vancouver Canucks", away_team="Seattle Kraken")
    evidence = _build(row)
    assert evidence.coverage()["advanced"].startswith("player_not_found:") and "ambiguous" in evidence.coverage()["advanced"]


def test_game_sim_reads_the_predictions_row_for_this_game():
    evidence = _build(EICHEL_SOG_UNDER)
    prediction = _csv(PREDICTIONS_0609)[0]
    facts = evidence.layers[Layer.GAME_SIM].facts
    assert (prediction["home"], prediction["away"]) == ("Vegas Golden Knights", "Carolina Hurricanes")
    assert facts["p_home_ml"] == float(prediction["p_home_ml"])
    assert facts["model_total"] == float(prediction["model_total"])
    assert facts["stale_days"] == 0
    assert "predictions_2026-06-09" in _tables(evidence, Layer.GAME_SIM)[0]["title"]


def test_environment_states_the_absent_inputs_by_name():
    evidence = _build(EICHEL_SOG_UNDER)
    rows = {r[0]: r for r in _tables(evidence, Layer.ENVIRONMENT)[0]["rows"]}
    assert rows["Starting goalies"][1].startswith("not published")
    assert rows["Rest / back-to-back"][1] == "no producer"
    assert rows["Player's side"] == ["Player's side", "", "player's team"]
    elo = {r["abbr"]: r["elo"] for r in _csv(NHL / "data/processed/team_elo_latest.csv")}
    assert rows["Team Elo (team_elo_latest)"][1:] == [C.fmt_num(elo["CAR"], 0), C.fmt_num(elo["VGK"], 0)]


def test_a_player_on_neither_team_is_a_named_matchup_absence():
    row = _board_row(player_name="Jack Eichel", market="SOG", line=2.5, side="over",
                     home_team="Montreal Canadiens", away_team="Carolina Hurricanes")
    evidence = _build(row)
    coverage = evidence.coverage()
    assert coverage["matchup"].startswith("player_not_found:") and "VGK" in coverage["matchup"]
    assert coverage["game_sim"].startswith("player_not_found:predictions_2026-06-09.csv has no CAR @ MTL row")


# --- staleness and file choice ---------------------------------------------


def test_a_preseason_game_reads_last_seasons_files_and_says_so():
    row = _board_row(player_name="Jack Eichel", market="SOG", line=2.5, side="over",
                     commence_time="2026-09-21T02:00:00Z")
    evidence = _build(row, date="2026-09-20")
    assert all(evidence.coverage()[layer] == "filled" for layer in ("player_sim", "recent_form", "game_sim"))
    sim = evidence.layers[Layer.PLAYER_SIM].facts
    # Newest NON-EMPTY file on or before the game, across both roots; the header-only 06-28 is skipped and named.
    assert sim["file_date"] == "2026-06-14" and sim["skipped_empty_files"] == ["2026-06-28"]
    assert sim["stale_days"] == 98
    assert any(label.startswith("STALE: props_recommendations_2026-06-14.csv") for label in _row_labels(evidence, Layer.PLAYER_SIM))
    assert any(label.startswith("STALE: predictions_2026-06-09.csv") for label in _row_labels(evidence, Layer.GAME_SIM))
    assert any(label.startswith("STALE: newest game is dated 2026-06-14") for label in _row_labels(evidence, Layer.RECENT_FORM))
    assert evidence.layers[Layer.RECENT_FORM].facts["values"] == _expected_eichel_shots("2026-09-21T02:00:00Z")


def test_the_games_own_header_only_file_is_authoritative():
    """06-10's props file exists and is empty: that is this slate's answer, not a cue to read 06-09."""
    row = _board_row(player_name="Jack Eichel", market="SOG", line=2.5, side="over",
                     commence_time="2026-06-11T00:00:00Z")
    evidence = _build(row, date="2026-06-10")
    status = evidence.coverage()["player_sim"]
    assert status.startswith("player_not_found:") and "props_recommendations_2026-06-10.csv (header-only)" in status


def test_slate_date_is_the_eastern_date_not_the_utc_date():
    subject = prop_evidence.PropSubject.from_board_row(EICHEL_SOG_UNDER, selected_date="")
    # The contract's own fallback is now the Eastern date of the puck drop
    # (2026-06-10T00:00Z is 8 PM ET on the 9th), not the UTC date.
    assert subject.selected_date == "2026-06-09"
    assert nhl.slate_dates(subject) == ["2026-06-09"]
    evidence = nhl.build(subject)
    assert evidence.layers[Layer.PLAYER_SIM].facts["file_date"] == "2026-06-09"


def test_poisson_under_helper_matches_the_pmf():
    assert nhl.poisson_prob_under(2.0, 2.5) == pytest.approx(math.exp(-2) * (1 + 2 + 2))
    assert nhl.poisson_prob_under(2.0, 2.0) == pytest.approx(math.exp(-2) * (1 + 2))  # integer line: X < 2
