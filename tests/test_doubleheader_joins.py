"""An MLB doubleheader is TWO games at every join that keys a game by team pair.

Measured on production 2026-09-22, TB @ NYY split doubleheader:

    StatsAPI   G1 gamePk 823543  gameDate 17:05Z   G2 823494  gameDate 23:05Z
    OddsAPI    G1 event 394e1e2b commence 17:06Z   G2 574050c1 commence 23:06Z

and every team-pair join kept ONE of them for both: game 2's Layer 2 rows read
game 1's chip (`12:05P CT`), game 1's moneyline read game 2's sim (home 0.531
vs its own 0.606), game 2's props read game 1's projections and game 1's
Kalshi ticker, and game 1's MLB card carried game 2's odds.

These tests use the production shape (two games, same pair, ~6 h apart) and
call the real join functions.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from syndicate.features.shared import board_enrichment as BE
from syndicate.features.shared import doubleheader as DH

G1_START = "2026-09-22T17:05:00Z"
G2_START = "2026-09-22T23:05:00Z"
G1_COMMENCE = "2026-09-22T17:06:00Z"
G2_COMMENCE = "2026-09-22T23:06:00Z"


# --- the rule itself ---------------------------------------------------------


def test_nearest_start_separates_the_two_halves():
    games = [{"pk": 823543, "start": G1_START}, {"pk": 823494, "start": G2_START}]
    for commence, pk in ((G1_COMMENCE, 823543), (G2_COMMENCE, 823494)):
        hit, reason = DH.pick_by_start_time(games, commence, start_of=lambda g: g["start"])
        assert (hit["pk"], reason) == (pk, DH.NEAREST_START)


def test_candidate_order_does_not_decide():
    games = [{"pk": 823494, "start": G2_START}, {"pk": 823543, "start": G1_START}]
    hit, _ = DH.pick_by_start_time(games, G1_COMMENCE, start_of=lambda g: g["start"])
    assert hit["pk"] == 823543


@pytest.mark.parametrize(
    "target, starts, reason",
    [
        (None, [G1_START, G2_START], DH.AMBIGUOUS_NO_TARGET_TIME),
        (G1_COMMENCE, [G1_START, None], DH.AMBIGUOUS_NO_CANDIDATE_TIME),
        (G1_COMMENCE, [None, None], DH.AMBIGUOUS_NO_CANDIDATE_TIME),
        # Two games inside the separation window cannot be told apart on time.
        ("2026-09-22T17:30:00Z", ["2026-09-22T17:05:00Z", "2026-09-22T17:55:00Z"], DH.AMBIGUOUS_NOT_SEPARABLE),
    ],
)
def test_a_pair_it_cannot_separate_returns_nothing(target, starts, reason):
    games = [{"start": s} for s in starts]
    assert DH.pick_by_start_time(games, target, start_of=lambda g: g["start"]) == (None, reason)


def test_a_single_candidate_is_kept_without_a_gap_bound():
    only = {"start": G1_START}
    assert DH.pick_by_start_time([only], G2_COMMENCE, start_of=lambda g: g["start"]) == (only, DH.SINGLE)


def test_max_gap_refuses_a_lone_game_from_another_day():
    # Tomorrow's game of the series, with only today's game as a candidate.
    only = {"start": G1_START}
    hit, reason = DH.pick_by_start_time(
        [only], "2026-09-23T17:06:00Z", start_of=lambda g: g["start"], max_gap_seconds=DH.MAX_SAME_GAME_GAP_SECONDS
    )
    assert (hit, reason) == (None, DH.BEYOND_MAX_GAP)


def test_central_clock_reads_the_lens_start():
    assert DH.central_clock_start_epoch("2026-09-22", "12:05 PM") == DH.start_epoch(G1_START)
    assert DH.central_clock_start_epoch("2026-09-22", "6:05 PM") == DH.start_epoch(G2_START)
    assert DH.central_clock_start_epoch("2026-09-22", "Postponed") is None
    assert DH.central_clock_start_epoch("", "6:05 PM") is None


# --- the Layer 2 game block (chip join) -------------------------------------


def _chip(start, token, state="pregame"):
    return {
        "home": {"name": "New York Yankees", "abbr": "NYY"},
        "away": {"name": "Tampa Bay Rays", "abbr": "TB"},
        "state": state,
        "start_time_utc": start,
        "status_token": token,
        "matchup": "TB @ NYY",
    }


def _grid_row(commence):
    return {"home_team": "New York Yankees", "away_team": "Tampa Bay Rays", "commence_time": commence}


@pytest.fixture
def chips(monkeypatch):
    import syndicate.features.shared.game_chip_scoreboard as gcs

    def _install(by_date):
        def fake(date_str, sports):
            return list(by_date.get(date_str, []))

        monkeypatch.setattr(gcs, "build_game_chips", fake)

    return _install


def test_each_half_of_a_doubleheader_gets_its_own_chip(chips):
    # Production order: game 1's chip first, which is the one both halves took.
    chips({"2026-09-22": [_chip(G1_START, "12:05P CT", "live"), _chip(G2_START, "6:05P CT")]})
    grid = [_grid_row(G1_COMMENCE), _grid_row(G2_COMMENCE)]
    coverage = BE.attach_game_state(grid, sport="mlb", selected_date="2026-09-22")
    assert grid[0]["game"]["start_time_utc"] == G1_START
    assert grid[0]["game"]["state"] == "live"
    assert grid[1]["game"]["start_time_utc"] == G2_START
    assert grid[1]["game"]["status_token"] == "6:05P CT"
    assert grid[1]["game"]["state"] == "pregame"
    assert coverage["rows_matched"] == 2
    assert coverage["rows_resolved_by_start_time"] == 2


def test_tomorrows_series_game_does_not_take_todays_chip(chips):
    tomorrow_start = "2026-09-23T17:05:00Z"
    chips({
        "2026-09-22": [_chip(G1_START, "FINAL", "final")],
        "2026-09-23": [_chip(tomorrow_start, "12:05P CT")],
    })
    grid = [_grid_row("2026-09-23T17:06:00Z")]
    BE.attach_game_state(grid, sport="mlb", selected_date="2026-09-22")
    assert grid[0]["game"]["start_time_utc"] == tomorrow_start
    assert grid[0]["game"]["state"] == "pregame"


def test_an_mlb_row_whose_only_chip_is_another_days_game_gets_no_block(chips):
    chips({"2026-09-22": [_chip(G1_START, "FINAL", "final")]})
    grid = [_grid_row("2026-09-23T17:06:00Z")]
    coverage = BE.attach_game_state(grid, sport="mlb", selected_date="2026-09-22")
    assert "game" not in grid[0]
    assert coverage["rows_refused_other_day_game"] == 1


def test_a_row_with_no_start_time_is_refused_when_the_pair_is_ambiguous(chips):
    chips({"2026-09-22": [_chip(G1_START, "12:05P CT"), _chip(G2_START, "6:05P CT")]})
    grid = [_grid_row(None)]
    coverage = BE.attach_game_state(grid, sport="mlb", selected_date="2026-09-22")
    assert "game" not in grid[0]
    assert coverage["rows_ambiguous_game"] == 1


# --- the live-lens state overlay --------------------------------------------


def _lens_game(pk, start_clock, abstract, detailed=""):
    return {
        "gamePk": pk,
        "startTime": start_clock,
        "status": {"abstract": abstract, "detailed": detailed},
        "away": {"abbr": "TB", "name": "Tampa Bay Rays"},
        "home": {"abbr": "NYY", "name": "New York Yankees"},
        "matchup": {"score": {"away": 1, "home": 0}},
    }


@pytest.fixture
def lens(monkeypatch):
    def _install(*games):
        import syndicate.features.shared.refresh_state_store as store

        generated = (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat()
        snapshot = {"date": "2026-09-22", "generatedAt": generated, "games": list(games)}
        monkeypatch.setattr(store, "read_json_file", lambda *_a, **_k: snapshot)

    return _install


def _board_row(commence, state):
    return {**_grid_row(commence), "game": {"state": state, "status_token": ""}}


def test_game_one_going_live_leaves_game_two_pregame(lens):
    # Snapshot order as served: game 1 first.
    lens(_lens_game(823543, "12:05 PM", "Live", "In Progress"), _lens_game(823494, "6:05 PM", "Preview", "Scheduled"))
    grid = [_board_row(G1_COMMENCE, "pregame"), _board_row(G2_COMMENCE, "pregame")]
    coverage = BE.attach_live_game_state_from_lens(grid, sport="mlb", selected_date="2026-09-22")
    assert grid[0]["game"]["state"] == "live"
    assert grid[1]["game"]["state"] == "pregame"
    assert coverage["rows_corrected"] == 1


def test_game_one_final_does_not_final_game_two(lens):
    lens(_lens_game(823543, "12:05 PM", "Final"), _lens_game(823494, "6:05 PM", "Live", "In Progress"))
    grid = [_board_row(G1_COMMENCE, "live"), _board_row(G2_COMMENCE, "pregame")]
    BE.attach_live_game_state_from_lens(grid, sport="mlb", selected_date="2026-09-22")
    assert grid[0]["game"]["state"] == "final"
    assert grid[1]["game"]["state"] == "live"


def test_a_tomorrow_row_in_todays_grid_is_not_corrected_from_todays_game(lens):
    lens(_lens_game(823543, "12:05 PM", "Final"))
    grid = [_board_row("2026-09-23T17:06:00Z", "pregame")]
    coverage = BE.attach_live_game_state_from_lens(grid, sport="mlb", selected_date="2026-09-22")
    assert grid[0]["game"]["state"] == "pregame"
    assert coverage["rows_refused_other_day_game"] == 1


# --- the Kalshi prop join (the order path's ticker) -------------------------


def _kalshi_tb(ticker):
    return {
        "ticker": ticker,
        "series": "KXMLBTB",
        "title": "Jonathan Aranda: 2+ total bases?",
        "yes_american": 150,
        "no_american": -170,
        "yes_probability": 0.4,
        "no_probability": 0.62,
    }


def _aranda_row(event_id, commence):
    return {
        "sport": "mlb",
        "event_id": event_id,
        "market": "batter_total_bases",
        "player_name": "Jonathan Aranda",
        "line": 1.5,
        "side": "Over",
        "home_team": "New York Yankees",
        "away_team": "Tampa Bay Rays",
        "commence_time": commence,
        "quote": {"price": 140},
    }


G1_TB = "KXMLBTB-26SEP221305TBNYYG1-TBJARANDA8-2"
G2_TB = "KXMLBTB-26SEP221805TBNYYG2-TBJARANDA8-2"


def test_each_kalshi_prop_contract_pairs_only_with_its_own_games_row():
    from syndicate.features.shared.kalshi_board_join import join_kalshi_to_board

    rows = [_aranda_row("394e1e2b", G1_COMMENCE), _aranda_row("574050c1", G2_COMMENCE)]
    out = join_kalshi_to_board([_kalshi_tb(G1_TB), _kalshi_tb(G2_TB)], rows, selected_date="2026-09-22")
    pairs = sorted((m["ticker"], m["board_event_id"]) for m in out["matches"])
    assert pairs == [(G1_TB, "394e1e2b"), (G2_TB, "574050c1")]
    assert out["prop_game_resolved"] == 2


def test_a_game_two_contract_never_pairs_with_game_ones_lone_row():
    # Only game 1's row is on the board: game 2's contract must not take it.
    from syndicate.features.shared.kalshi_board_join import REASON_PROP_GAME_UNRESOLVED, join_kalshi_to_board

    rows = [_aranda_row("394e1e2b", G1_COMMENCE)]
    out = join_kalshi_to_board([_kalshi_tb(G2_TB)], rows, selected_date="2026-09-22")
    assert out["matches"] == []
    assert out["reasons"] == {REASON_PROP_GAME_UNRESOLVED: 1}


def test_the_ticker_resolver_gives_each_half_its_own_ticker():
    # What the order path submits: `kalshi_ticker_resolver` over the join.
    from syndicate.features.shared.kalshi_board_join import join_kalshi_to_board, kalshi_ticker_resolver

    rows = [_aranda_row("394e1e2b", G1_COMMENCE), _aranda_row("574050c1", G2_COMMENCE)]
    out = join_kalshi_to_board([_kalshi_tb(G1_TB), _kalshi_tb(G2_TB)], rows, selected_date="2026-09-22")
    resolve = kalshi_ticker_resolver(out["matches"])
    assert resolve(rows[0]) == G1_TB
    assert resolve(rows[1]) == G2_TB


# --- the sim projections (the model probability admission and sizing read) ---


def _sim_game(pk, number, home_win, tb_mean, p_tb_cal):
    # Trimmed from production's daily_summary_2026_09_22.json (both halves).
    return {
        "game_pk": pk,
        "game_number": number,
        "double_header": "S",
        "away": "TB",
        "home": "NYY",
        "full": {"home_win_prob": home_win, "away_win_prob": round(1 - home_win, 3), "tie_prob": 0.0},
        "hitter_props_likelihood_topn": {
            "total_bases_2plus": [
                {"batter_id": 666018, "name": "Jonathan Aranda", "team": "TB",
                 "p_tb_2plus": p_tb_cal + 0.05, "p_tb_2plus_cal": p_tb_cal, "tb_mean": tb_mean}
            ]
        },
    }


@pytest.fixture
def dh_index(tmp_path):
    import json

    from syndicate.features.shared.prop_projections import load_prop_projections

    summary = tmp_path / "daily_summary_2026_09_22.json"
    summary.write_text(json.dumps({"outputs": [
        _sim_game(823543, 1, 0.606, 1.513, 0.298),
        _sim_game(823494, 2, 0.531, 1.502, 0.308),
    ]}), encoding="utf-8")
    return load_prop_projections(summary)


def _proj_row(game_pk, **kw):
    row = {
        "sport": "mlb",
        "home_team": "New York Yankees",
        "away_team": "Tampa Bay Rays",
        "game": {"game_key": game_pk} if game_pk else {},
    }
    row.update(kw)
    return row


def _aranda_tb(game_pk):
    return _proj_row(game_pk, market="batter_total_bases", player_name="Jonathan Aranda", line=1.5,
                     sides=["over", "under"], consensus={"over": 140, "under": -170})


def _moneyline(game_pk):
    return _proj_row(game_pk, market="h2h", player_name=None, sides=["home"])


def test_each_half_reads_its_own_game_line_projection(dh_index):
    from syndicate.features.shared.prop_projections import attach_projections

    rows = [_moneyline("823543"), _moneyline("823494")]
    coverage = attach_projections(rows, dh_index)
    assert rows[0]["projection"]["model_prob_over"] == pytest.approx(0.606, abs=1e-3)
    assert rows[1]["projection"]["model_prob_over"] == pytest.approx(0.531, abs=1e-3)
    assert coverage["rows_resolved_by_game_pk"] == 2


def test_each_half_reads_its_own_player_projection(dh_index):
    from syndicate.features.shared.prop_projections import attach_projections

    rows = [_aranda_tb("823543"), _aranda_tb("823494")]
    attach_projections(rows, dh_index)
    assert rows[0]["projection"]["projected"] == pytest.approx(1.513)
    assert rows[1]["projection"]["projected"] == pytest.approx(1.502)


def test_a_doubleheader_row_with_no_game_id_gets_no_projection(dh_index):
    from syndicate.features.shared.prop_projections import attach_projections

    rows = [_moneyline(None), _aranda_tb(None)]
    coverage = attach_projections(rows, dh_index)
    assert "projection" not in rows[0] and "projection" not in rows[1]
    assert coverage["rows_refused_game_ambiguous"] == 2


def test_a_row_never_takes_the_other_halfs_sim_when_its_own_is_missing(tmp_path):
    import json

    from syndicate.features.shared.prop_projections import attach_projections, load_prop_projections

    summary = tmp_path / "daily_summary_2026_09_22.json"
    summary.write_text(json.dumps({"outputs": [_sim_game(823543, 1, 0.606, 1.513, 0.298)]}), encoding="utf-8")
    index = load_prop_projections(summary)
    rows = [_moneyline("823494"), _aranda_tb("823494"), _moneyline("823543")]
    coverage = attach_projections(rows, index)
    assert "projection" not in rows[0] and "projection" not in rows[1]
    assert rows[2]["projection"]["model_prob_over"] == pytest.approx(0.606, abs=1e-3)
    assert coverage["rows_refused_other_game"] == 2


def test_an_ordinary_game_is_unchanged_without_a_game_id(tmp_path):
    import json

    from syndicate.features.shared.prop_projections import attach_projections, load_prop_projections

    summary = tmp_path / "daily_summary_2026_09_22.json"
    summary.write_text(json.dumps({"outputs": [_sim_game(823543, 1, 0.606, 1.513, 0.298)]}), encoding="utf-8")
    rows = [_moneyline(None), _aranda_tb(None)]
    coverage = attach_projections(rows, load_prop_projections(summary))
    assert rows[0]["projection"]["model_prob_over"] == pytest.approx(0.606, abs=1e-3)
    assert rows[1]["projection"]["projected"] == pytest.approx(1.513)
    assert coverage["rows_resolved_by_game_pk"] == 0


def test_the_chip_join_stamps_the_game_id_projections_read(chips):
    chips({"2026-09-22": [dict(_chip(G1_START, "12:05P CT"), game_key="823543"),
                          dict(_chip(G2_START, "6:05P CT"), game_key="823494")]})
    grid = [_grid_row(G1_COMMENCE), _grid_row(G2_COMMENCE)]
    BE.attach_game_state(grid, sport="mlb", selected_date="2026-09-22")
    assert [row["game"]["game_key"] for row in grid] == ["823543", "823494"]


# --- the Polymarket board join (the order path's slug) ----------------------


def _pm_market(slug, outcomes, prices, market_type):
    import json

    return {
        "slug": slug, "sportsMarketTypeV2": market_type,
        "outcomes": json.dumps(outcomes), "outcomePrices": json.dumps(prices),
        "orderPriceMinTickSize": "0.005", "minimumTradeQty": "0.01", "orderable": True,
    }


def _pm_row(event_id, commence, market, side, line=None):
    return {"sport": "mlb", "event_id": event_id, "market": market, "side": side, "line": line,
            "home_team": "New York Yankees", "away_team": "Tampa Bay Rays", "commence_time": commence}


# Slugs as the venue listed them on 2026-09-22.
_PM_TOTAL, _PM_ML = "SPORTS_MARKET_TYPE_TOTAL", "SPORTS_MARKET_TYPE_MONEYLINE"
_PM_MARKETS = [
    _pm_market("tsc-mlb-tb-nyy-2026-09-22-dh1-8pt5", ["Over", "Under"], ["0.45", "0.56"], _PM_TOTAL),
    _pm_market("tsc-mlb-tb-nyy-2026-09-22-dh1-7pt5", ["Over", "Under"], ["0.55", "0.46"], _PM_TOTAL),
    _pm_market("tsc-mlb-tb-nyy-2026-09-22-dh2-7pt5", ["Over", "Under"], ["0.50", "0.51"], _PM_TOTAL),
    _pm_market("aec-mlb-tb-nyy-2026-09-22-dh1", ["Rays", "Yankees"], ["0.40", "0.61"], _PM_ML),
    _pm_market("aec-mlb-tb-nyy-2026-09-22-dh2", ["Rays", "Yankees"], ["0.46", "0.55"], _PM_ML),
]


def _pm_slugs(rows):
    from syndicate.features.shared.polymarket_board_join import join_polymarket_to_board, polymarket_ticker_resolver

    out = join_polymarket_to_board(_PM_MARKETS, rows, sport="mlb", selected_date="2026-09-22")
    resolve = polymarket_ticker_resolver(out.get("matches") or [])
    return [(resolve(row) or {}).get("slug") for row in rows], out


def test_each_polymarket_half_trades_only_its_own_contract():
    rows = [
        _pm_row("g1", G1_COMMENCE, "totals", "over", 7.5), _pm_row("g2", G2_COMMENCE, "totals", "over", 7.5),
        _pm_row("g1", G1_COMMENCE, "h2h", "home"), _pm_row("g2", G2_COMMENCE, "h2h", "home"),
    ]
    slugs, out = _pm_slugs(rows)
    assert slugs == [
        "tsc-mlb-tb-nyy-2026-09-22-dh1-7pt5", "tsc-mlb-tb-nyy-2026-09-22-dh2-7pt5",
        "aec-mlb-tb-nyy-2026-09-22-dh1", "aec-mlb-tb-nyy-2026-09-22-dh2",
    ]
    assert out["doubleheader_candidates_kept"] == 4


def test_a_line_only_game_one_lists_never_pairs_with_game_two():
    # dh1 lists 8.5; dh2 does not. Game 2's 8.5 row must get NOTHING.
    rows = [_pm_row("g1", G1_COMMENCE, "totals", "over", 8.5), _pm_row("g2", G2_COMMENCE, "totals", "over", 8.5)]
    slugs, _ = _pm_slugs(rows)
    assert slugs == ["tsc-mlb-tb-nyy-2026-09-22-dh1-8pt5", None]


def test_a_lone_half_on_the_board_is_refused_not_guessed():
    # Only game 2's row: its number cannot be read from the board alone.
    slugs, out = _pm_slugs([_pm_row("g2", G2_COMMENCE, "totals", "over", 8.5)])
    assert slugs == [None]
    assert out["doubleheader_candidates_skipped"]["half_unresolved"] >= 1


# --- the web's serve-time restate (`_refresh_layer2_live_state`) ------------


@pytest.fixture
def restate_chips(monkeypatch):
    import pipeline.intelligence_state as state_module
    from syndicate.features.shared import game_chip_scoreboard

    table: dict[str, list] = {}
    monkeypatch.setattr(state_module, "read_game_chips", lambda _date: None)
    monkeypatch.setattr(game_chip_scoreboard, "build_game_chips", lambda date, _sports: list(table.get(str(date), [])))
    return table


def _restate_chip(pk, start, state, away_score=None, home_score=None):
    return {
        "sport": "mlb", "game_key": pk, "start_time_utc": start, "state": state, "matchup": "TB @ NYY",
        "away": {"name": "Tampa Bay Rays", "score": away_score},
        "home": {"name": "New York Yankees", "score": home_score},
    }


def _restate_card(commence, market="totals", line=7.5):
    return {
        "sport": "mlb", "kind": "game", "market": market, "line": line, "side": "over",
        "away_team": "Tampa Bay Rays", "home_team": "New York Yankees",
        "game_date": "2026-09-22", "commence_time": commence,
        "market_state": "pregame", "lane": "pregame", "is_live": False,
    }


def test_the_restate_gives_each_half_its_own_state_and_score(restate_chips):
    import pipeline.intelligence_state as state_module

    # Game 1 live and already past the 7.5 total; game 2 not started.
    restate_chips["2026-09-22"] = [
        _restate_chip("823543", "2026-09-22T17:05:00+00:00", "live", away_score=5, home_score=4),
        _restate_chip("823494", "2026-09-22T23:05:00+00:00", "pregame"),
    ]
    g1, g2 = _restate_card(G1_COMMENCE), _restate_card(G2_COMMENCE)
    restated = state_module._refresh_layer2_live_state([g1, g2], ["2026-09-22"])
    assert restated == 1
    assert g1["market_state"] == "live" and g1["actual"] == 9.0
    assert g2["market_state"] == "pregame" and g2["is_live"] is False
    # Game 2's total is NOT graded on game 1's runs, so it is not pruned as decided.
    assert "actual" not in g2 and not g2.get("decided")


def test_the_restate_dedupes_one_game_seen_twice(restate_chips, monkeypatch):
    import pipeline.intelligence_state as state_module

    # The worker-published copy and the inline copy of ONE game are one candidate.
    chip = _restate_chip("823543", "2026-09-22T17:05:00+00:00", "live", 1, 0)
    restate_chips["2026-09-22"] = [chip]
    monkeypatch.setattr(state_module, "read_game_chips", lambda _date: {"chips": [dict(chip)], "written_at": None})
    card = _restate_card(G1_COMMENCE, market="h2h", line=None)
    assert state_module._refresh_layer2_live_state([card], ["2026-09-22"], attach_actual=False) == 1
    assert card["market_state"] == "live"


# --- the venue quote fan-in (the board's displayed venue price and venue_ref) --


_KALSHI_TB_PAYLOAD = {
    "fetched_at": "2026-09-22T16:00:00Z",
    "series": {"KXMLBTB": {"markets": [
        {"ticker": G1_TB, "series": "KXMLBTB", "title": "Jonathan Aranda: 2+ total bases?",
         "yes_ask_dollars": 0.40, "no_ask_dollars": 0.62},
        {"ticker": G2_TB, "series": "KXMLBTB", "title": "Jonathan Aranda: 2+ total bases?",
         "yes_ask_dollars": 0.44, "no_ask_dollars": 0.58},
    ]}},
}


def _fanin(rows, monkeypatch):
    import time

    from syndicate.features.shared import venue_quote_adapters as adapters
    from syndicate.features.shared.venue_quote_fanin import apply_venue_quotes, collect_quotes

    monkeypatch.setattr(adapters, "_artifact", lambda parts: (_KALSHI_TB_PAYLOAD, time.time()))
    now = time.time()
    collected = {"mlb": collect_quotes("mlb", "2026-09-22", adapters={"kalshi": adapters.kalshi_outcome}, now=now)}
    return apply_venue_quotes(rows, "2026-09-22", collected_by_sport=collected, now=now)


def _fanin_row(event_id, commence):
    return {"sport": "mlb", "event_id": event_id, "market": "batter_total_bases", "player_name": "Jonathan Aranda",
            "side": "over", "line": 1.5, "home_team": "New York Yankees", "away_team": "Tampa Bay Rays",
            "commence_time": commence}


def test_each_half_is_stamped_with_its_own_venue_contract(monkeypatch):
    result = _fanin([_fanin_row("394e1e2b", G1_COMMENCE), _fanin_row("574050c1", G2_COMMENCE)], monkeypatch)
    refs = {row["event_id"]: row.get("venue_ref") for row in result["rows"]}
    assert refs == {"394e1e2b": G1_TB, "574050c1": G2_TB}
    assert result["doubleheader_rows"] == {"qualified": 2, "unrankable": 0}


def test_an_ordinary_row_never_takes_a_doubleheader_contract(monkeypatch):
    # Only one TB @ NYY event on the board: its half cannot be named, and the
    # venue's contracts both name a half -- so neither may attach.
    result = _fanin([_fanin_row("574050c1", G2_COMMENCE)], monkeypatch)
    assert result["rows"][0].get("venue_ref") is None
    assert result["stamped"] == 0


def test_the_kalshi_and_polymarket_adapters_name_the_half():
    from syndicate.features.shared.venue_quote_adapters import doubleheader_quote_key, kalshi_doubleheader_number

    assert kalshi_doubleheader_number(G1_TB) == 1 and kalshi_doubleheader_number(G2_TB) == 2
    assert kalshi_doubleheader_number("KXMLBTB-26SEP231305TBNYY-TBJARANDA8-2") is None
    assert doubleheader_quote_key("mlb|totals|over|7.5", 2) == "mlb|totals|over|7.5|dh2"
    assert doubleheader_quote_key("mlb|totals|over|7.5", None) == "mlb|totals|over|7.5"
