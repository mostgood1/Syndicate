"""NBA book-blend reachability on the two serving surfaces it was wired into (2026-10-05):
the props-edges export (picks, and the board's recommendation rows) and the market board's
sim-distribution rows. off != on, NBA only, and WNBA untouched."""
from __future__ import annotations

import json
import math

import pandas as pd
import pytest

from syndicate.features.shared import basketball_market_board as board
from syndicate.features.shared import basketball_props_edges as edges
from syndicate.features.shared import nba_prop_calibration as cal

W = {"enabled": True, "space": "logit", "w": {"pts": 0.0, "reb": 0.1}}


def _processed(tmp_path, doc=W):
    processed = tmp_path / "data" / "processed"
    processed.mkdir(parents=True, exist_ok=True)
    if doc is not None:
        (processed / cal.BOOK_BLEND_FILE).write_text(json.dumps(doc), encoding="utf-8")
    return processed


def _board_rows(league):
    sim_players = {"home": [{"player_name": "Jane Doe", "pts_mean": 25.0, "pts_sd": 5.0}], "away": []}
    raw = {board._canonical_player_key("Jane Doe"): {"points": {"line": 20.5, "over_odds": -110, "under_odds": -110}}}
    _, sim_rows = board.basketball_market_board_rows_for_game(
        game_pk=1, betting={}, prop_recommendations={}, raw_player_props=raw, sim_players=sim_players, league=league)
    return [r for r in sim_rows if r.get("sim_source") == "basketball_sim_distribution"]


def test_board_nba_serves_the_book_blend_and_wnba_does_not(tmp_path, monkeypatch):
    processed = _processed(tmp_path)
    monkeypatch.setattr("syndicate.features.nba.sources.artifact_processed_root", lambda: processed)
    monkeypatch.delenv(cal.BOOK_BLEND_FLAG, raising=False)
    (nba,) = _board_rows("nba")
    (wnba,) = _board_rows("wnba")
    raw_p = board._prob_over(25.0, 5.0, 20.5)
    assert wnba["model_prob_over"] == raw_p and "book_blend" not in wnba
    assert nba["model_prob_over"] == pytest.approx(0.5)  # w(pts) = 0 -> the de-vigged book
    assert nba["book_blend"] == "applied" and nba["p_model_raw"] == round(raw_p, 4)
    monkeypatch.setenv(cal.BOOK_BLEND_FLAG, "0")
    (off,) = _board_rows("nba")
    assert off["model_prob_over"] == raw_p != nba["model_prob_over"]


def test_devig_over():
    assert board._devig_over(-110, -110) == pytest.approx(0.5)
    assert board._devig_over(-110, None) is None
    assert board._devig_over("x", -110) is None


def _merged(rows):
    df = pd.DataFrame(rows)
    df["implied_prob"] = df["price"].map(lambda v: 100 / (v + 100) if v > 0 else -v / (-v + 100))
    df["model_prob"] = df["model_prob_raw"]
    return df


def test_edges_blend_pairs_over_and_under_per_book(tmp_path):
    _processed(tmp_path)
    df = _merged([
        {"player_name": "A", "stat": "reb", "line": 6.5, "bookmaker": "dk", "side": "OVER", "price": -120, "model_prob_raw": 0.70},
        {"player_name": "A", "stat": "reb", "line": 6.5, "bookmaker": "dk", "side": "UNDER", "price": 100, "model_prob_raw": 0.30},
        {"player_name": "A", "stat": "reb", "line": 6.5, "bookmaker": "fd", "side": "OVER", "price": -115, "model_prob_raw": 0.70},
        {"player_name": "A", "stat": "tov", "line": 2.5, "bookmaker": "dk", "side": "OVER", "price": -110, "model_prob_raw": 0.60},
        {"player_name": "A", "stat": "tov", "line": 2.5, "bookmaker": "dk", "side": "UNDER", "price": -110, "model_prob_raw": 0.40},
    ])
    edges._apply_nba_book_blend(df, source_root=tmp_path)
    io, iu = 120 / 220, 100 / 200
    pb = io / (io + iu)
    lb = math.log(pb / (1 - pb))
    expect_over = 1 / (1 + math.exp(-(lb + 0.1 * (math.log(0.7 / 0.3) - lb))))
    assert df.loc[0, "model_prob"] == pytest.approx(expect_over)
    assert df.loc[1, "model_prob"] == pytest.approx(1 - expect_over)
    assert list(df["book_blend"]) == ["applied", "applied", "no two-sided book price for this line",
                                      "no weight for this stat", "no weight for this stat"]
    assert df.loc[2, "model_prob"] == 0.70 and df.loc[3, "model_prob"] == 0.60


def test_edges_blend_switch_off_and_absent_file_leave_model_prob(tmp_path, monkeypatch):
    rows = [{"player_name": "A", "stat": "pts", "line": 20.5, "bookmaker": "dk", "side": s, "price": -110, "model_prob_raw": p}
            for s, p in (("OVER", 0.8), ("UNDER", 0.2))]
    df = _merged(rows)
    edges._apply_nba_book_blend(df, source_root=tmp_path)
    assert list(df["model_prob"]) == [0.8, 0.2] and set(df["book_blend"]) == {"book-blend file absent"}
    _processed(tmp_path)
    monkeypatch.setenv(cal.BOOK_BLEND_FLAG, "off")
    df = _merged(rows)
    edges._apply_nba_book_blend(df, source_root=tmp_path)
    assert list(df["model_prob"]) == [0.8, 0.2]
    monkeypatch.delenv(cal.BOOK_BLEND_FLAG)
    df = _merged(rows)
    edges._apply_nba_book_blend(df, source_root=tmp_path)
    assert list(df["model_prob"]) == pytest.approx([0.5, 0.5])


def test_edges_compute_reaches_the_blend_only_for_nba(tmp_path):
    """The real `_compute_props_edges_file_only_local` path: league="nba" serves the de-vigged book
    (w(pts) = 0); no league leaves the model chain. off != on through the production function."""
    _processed(tmp_path)
    raw = tmp_path / "odds.csv"
    raw.write_text(
        "snapshot_ts,event_id,commence_time,bookmaker,bookmaker_title,market,outcome_name,player_name,point,price,home_team,away_team\n"
        + "".join(f"2026-09-17T18:00:00Z,evt1,2026-09-17T23:00:00Z,fanduel,FanDuel,player_points,{s},LeBron James,19.5,{p},Home Team,Away Team\n"
                  for s, p in (("Over", -120), ("Under", 100))), encoding="utf-8")
    preds = tmp_path / "preds.csv"
    preds.write_text("player_id,player_name,team,mean_pts,mean_reb,mean_ast,mean_threes,mean_pra,mean_stl,mean_blk,mean_tov\n"
                     "1,LeBron James,HOM,26.4,5.1,4.2,2.1,30.7,1.1,0.6,2.2\n", encoding="utf-8")
    kw = dict(source_root=tmp_path, date_str="2026-09-17", raw_path=raw, predictions_path=preds, calibrate_prob=False)
    on = edges._compute_props_edges_file_only_local(league="nba", **kw).set_index("side")
    off = edges._compute_props_edges_file_only_local(**kw).set_index("side")
    io, iu = 120 / 220, 100 / 200
    assert on.loc["OVER", "model_prob"] == pytest.approx(io / (io + iu))
    assert on.loc["OVER", "book_blend"] == "applied"
    assert off.loc["OVER", "model_prob"] != pytest.approx(on.loc["OVER", "model_prob"])
    assert "book_blend" not in off.columns or off["book_blend"].isna().all()


# --- Layer 2 (nba_projections.py, borrowed for this one call) -------------------------------------------------------

from tests.test_nba_layer2_projections import _prop_row, _props, nba_root  # noqa: E402,F401  (fixture reuse)


def test_layer2_prop_probability_is_the_book_blend_and_off_is_the_ladder(nba_root, monkeypatch):
    """Reachability through the real served path: `attach_nba_prop_projections`. The fixture's ladder
    says P(over 20.5) = 0.4 against a -110/-110 book; w(pts) = 0 serves 0.5, the kill switch serves 0.4."""
    from syndicate.features.nba.sources import artifact_processed_root

    (artifact_processed_root() / cal.BOOK_BLEND_FILE).write_text(json.dumps(W), encoding="utf-8")
    monkeypatch.delenv(cal.BOOK_BLEND_FLAG, raising=False)
    on = _prop_row("Lauri Markkanen", line=20.5)
    _props([on])
    monkeypatch.setenv(cal.BOOK_BLEND_FLAG, "0")
    off = _prop_row("Lauri Markkanen", line=20.5)
    _props([off])
    p_on, p_off = on["projection"], off["projection"]
    assert p_on["model_prob_over"] == pytest.approx(0.5) and p_on["book_blend"] == "applied"
    assert p_on["p_model_raw"] == pytest.approx(0.4) and p_on["edge_vs_market_pct"] == pytest.approx(0.0)
    assert p_off["model_prob_over"] == pytest.approx(0.4) and "off" in p_off["book_blend"]


def test_export_with_zero_positive_lines_writes_header_only_and_returns_zero(tmp_path, monkeypatch):
    """The blend puts the served probability on the de-vigged book, so no line clears edge >= 0 & ev >= 0.
    That is a RESULT: export returns 0 and writes a header-only file (it used to raise 'No edges computed',
    which made NBA's refresh skip its whole export phase). Missing inputs still raise."""
    _processed(tmp_path)
    monkeypatch.delenv(cal.BOOK_BLEND_FLAG, raising=False)
    raw = tmp_path / "odds.csv"
    raw.write_text(
        "snapshot_ts,event_id,commence_time,bookmaker,bookmaker_title,market,outcome_name,player_name,point,price,home_team,away_team\n"
        + "".join(f"2026-09-17T18:00:00Z,evt1,2026-09-17T23:00:00Z,fanduel,FanDuel,player_points,{s},LeBron James,19.5,{p},Home Team,Away Team\n"
                  for s, p in (("Over", -120), ("Under", 100))), encoding="utf-8")
    preds = tmp_path / "preds.csv"
    preds.write_text("player_id,player_name,team,mean_pts,mean_reb,mean_ast,mean_threes,mean_pra,mean_stl,mean_blk,mean_tov\n"
                     "1,LeBron James,HOM,26.4,5.1,4.2,2.1,30.7,1.1,0.6,2.2\n", encoding="utf-8")
    out = tmp_path / "props_edges.csv"
    n, path = edges.export_props_edges_local(source_root=tmp_path, date_str="2026-09-17", raw_path=raw,
                                             predictions_path=preds, out_path=out, league="nba")
    assert n == 0 and path == out
    text = out.read_text(encoding="utf-8").strip().splitlines()
    assert len(text) == 1 and "model_prob" in text[0]
    # the same inputs with the blend OFF do produce a +EV line, so the zero above is the blend's result
    monkeypatch.setenv(cal.BOOK_BLEND_FLAG, "0")
    n_off, _ = edges.export_props_edges_local(source_root=tmp_path, date_str="2026-09-17", raw_path=raw,
                                              predictions_path=preds, out_path=out, league="nba")
    assert n_off >= 1
    # missing inputs are still a failure
    with pytest.raises(ValueError):
        edges.export_props_edges_local(source_root=tmp_path, date_str="2026-09-17", raw_path=raw,
                                       predictions_path=_write_empty_preds(tmp_path), out_path=out, league="nba")


def _write_empty_preds(tmp_path):
    p = tmp_path / "empty_preds.csv"
    p.write_text("player_id,player_name,team,mean_pts,mean_reb,mean_ast,mean_threes,mean_pra,mean_stl,mean_blk,mean_tov\n", encoding="utf-8")
    return p


# --- NBA game lines on Layer 2 (nba_game_projections.py, borrowed for this one call) ---------------------------------

from tests.test_nba_layer2_projections import _game_row  # noqa: E402
from syndicate.features.shared.nba_game_projections import attach_nba_game_projections, load_nba_game_projections  # noqa: E402

GW = {"enabled": True, "space": "logit", "w": {"h2h:full": 0.0, "spreads:full": 0.0, "totals:full": 0.05, "default": 0.0}}


def test_layer2_game_line_is_the_book_blend_and_off_is_the_sim(nba_root, monkeypatch):
    """Real path: attach_nba_game_projections. The fixture's alt total 229.5 is P(over) 0.6 from the sim against a
    -110/-110 fair 0.5; w(totals) 0.05 (alt -> its family) serves ~0.51, the kill switch serves 0.6."""
    from syndicate.features.nba.sources import artifact_processed_root
    from tests.test_nba_layer2_projections import D

    (artifact_processed_root() / cal.GAME_BLEND_FILE).write_text(json.dumps(GW), encoding="utf-8")
    monkeypatch.delenv(cal.GAME_BLEND_FLAG, raising=False)
    on = _game_row("totals_alt", line=229.5)
    attach_nba_game_projections([on], load_nba_game_projections(D))
    monkeypatch.setenv(cal.GAME_BLEND_FLAG, "0")
    off = _game_row("totals_alt", line=229.5)
    attach_nba_game_projections([off], load_nba_game_projections(D))
    p_on, p_off = on["projection"], off["projection"]
    expect = 1 / (1 + math.exp(-0.05 * math.log(0.6 / 0.4)))
    assert p_on["model_prob_over"] == pytest.approx(round(expect, 4), abs=1e-4) and p_on["book_blend"] == "applied"
    assert p_on["book_blend_w"] == 0.05 and p_on["p_model_raw"] == pytest.approx(0.6)
    assert abs(p_on["edge_vs_market_pct"]) < 1.5
    assert p_off["model_prob_over"] == pytest.approx(0.6) and p_off["edge_vs_market_pct"] == pytest.approx(10.0)


def test_game_blend_weight_lookup_and_fallbacks(tmp_path):
    (tmp_path / cal.GAME_BLEND_FILE).write_text(json.dumps({"enabled": True, "w": {"spreads:full": 0.0}}), encoding="utf-8")
    p, m = cal.served_game_probability(0.57, 0.415, "spreads", "full", processed_root=tmp_path, env={})
    assert p == pytest.approx(0.415) and m["book_blend"] == "applied"
    p, m = cal.served_game_probability(0.57, 0.415, "spreads_alt", "full", processed_root=tmp_path, env={})
    assert p == pytest.approx(0.415)  # alt line -> its family's weight
    p, m = cal.served_game_probability(0.57, 0.415, "spreads", "h1", processed_root=tmp_path, env={})
    assert p == 0.57 and m["book_blend"] == "no weight for spreads:h1"
    p, m = cal.served_game_probability(0.57, None, "spreads", "full", processed_root=tmp_path, env={})
    assert p == 0.57 and m["book_blend"] == "no two-sided book price for this line"


def test_game_blend_phase_weights_and_unknown_is_not_permissive(tmp_path):
    doc = {"enabled": True, "w": {"totals:full": 0.05, "spreads:full": 0.0, "default": 0.0},
           "phase": {"preseason": {"default": 0.0}}}
    (tmp_path / cal.GAME_BLEND_FILE).write_text(json.dumps(doc), encoding="utf-8")
    kw = dict(processed_root=tmp_path, env={})
    p_pre, m_pre = cal.served_game_probability(0.6, 0.5, "totals", "full", phase="preseason", **kw)
    p_reg, m_reg = cal.served_game_probability(0.6, 0.5, "totals", "full", phase="regular", **kw)
    p_unk, m_unk = cal.served_game_probability(0.6, 0.5, "totals", "full", phase=None, **kw)
    assert p_pre == pytest.approx(0.5) and m_pre["book_blend_w"] == 0.0 and m_pre["season_phase"] == "preseason"
    assert m_reg["book_blend_w"] == 0.05 and p_reg > 0.5
    assert m_unk["book_blend_w"] == 0.0 and m_unk["season_phase"] == "unknown"  # smallest weight, not the base


def test_layer2_game_line_reads_the_espn_season_type(nba_root, monkeypatch):
    from syndicate.features.nba.sources import artifact_processed_root
    from tests.test_nba_layer2_projections import D

    root = artifact_processed_root()
    doc = dict(GW, phase={"preseason": {"default": 0.0}})
    (root / cal.GAME_BLEND_FILE).write_text(json.dumps(doc), encoding="utf-8")
    cache = root / "_espn_cache" / "nba"
    cache.mkdir(parents=True, exist_ok=True)
    (cache / f"scoreboard_{D.replace('-', '')}.json").write_text(
        json.dumps({"events": [{"season": {"type": 1, "slug": "preseason"}}]}), encoding="utf-8")
    monkeypatch.delenv(cal.GAME_BLEND_FLAG, raising=False)
    row = _game_row("totals_alt", line=229.5)
    attach_nba_game_projections([row], load_nba_game_projections(D))
    p = row["projection"]
    assert p["season_phase"] == "preseason" and p["book_blend_w"] == 0.0
    assert p["model_prob_over"] == pytest.approx(0.5) and p["edge_vs_market_pct"] == pytest.approx(0.0)
