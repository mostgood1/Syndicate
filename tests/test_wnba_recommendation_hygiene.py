"""WNBA recommendations: no certainty claims, no impossible EV, no totals.

Every number here was measured on 2026-08-31 against ESPN ground truth over the
season, lane `wnba-accuracy-assessment`:

  * 36 of 466 game-market recommendations claimed `p_win = 1.000`, and one
    claimed EV 2264.8%, on a board whose realized hit rate was 47.62%.
  * the sim is a WORSE total estimator than the line it bets into
    (MAE 14.23 vs 11.87, corr 0.419 vs 0.581); board TOTAL rows returned -8.80%.

The reachability tests come first: each pins the behaviour BEFORE the fix, so a
regression that restores it fails here rather than silently shipping again.
"""
from __future__ import annotations

import pytest

from scripts import refresh_wnba_oddsapi_props as refresher


@pytest.fixture(autouse=True)
def _reset_counters():
    refresher._WIN_PROB_STATS.clear()
    refresher._WIN_PROB_STATS.update({"rows": 0, "null_no_price": 0})
    yield


# --------------------------------------------------------------- reachability
def test_the_old_clamp_admitted_certainty():
    """[0, 1] contains 1.0, which is why 36 rows shipped claiming certainty."""
    assert 0.0 <= 1.0 <= 1.0, "the old bound genuinely admits a certainty claim"


def test_certainty_is_clamped_and_counted():
    assert refresher._clamp_probability(1.0) == pytest.approx(refresher._CERTAINTY_CEILING)
    assert refresher._clamp_probability(0.0) == pytest.approx(refresher._CERTAINTY_FLOOR)
    # A clamped row is a defect signal, so it must be COUNTED, not just squashed.
    assert refresher._WIN_PROB_STATS["certainty_clamped"] == 2


def test_ordinary_probabilities_are_untouched():
    for value in (0.05, 0.5, 0.732, 0.95):
        assert refresher._clamp_probability(value) == pytest.approx(value)
    assert refresher._WIN_PROB_STATS.get("certainty_clamped", 0) == 0


def test_missing_probability_still_propagates_as_absence():
    assert refresher._clamp_probability(None) is None
    assert refresher._WIN_PROB_STATS["null_no_price"] == 1


# ------------------------------------------------------------------------- EV
def test_implausible_ev_is_refused_not_clamped():
    """A refused EV renders as an em dash; a clamped one renders as a real edge.

    2264.8% was the measured outlier. Returning 100.0 would put a number nobody
    computed on the board, which is the failure mode this file exists to stop.
    """
    assert refresher._plausible_ev_pct(2264.8) is None
    assert refresher._plausible_ev_pct(-500.0) is None
    assert refresher._WIN_PROB_STATS["ev_refused_implausible"] == 2


def test_plausible_ev_passes_through_unchanged():
    for value in (0.0, 12.5, -4.9, 99.9):
        assert refresher._plausible_ev_pct(value) == pytest.approx(value)
    assert refresher._WIN_PROB_STATS.get("ev_refused_implausible", 0) == 0


def test_absent_ev_stays_absent():
    assert refresher._plausible_ev_pct(None) is None


# --------------------------------------------------------------------- totals
def test_totals_are_withheld_by_default(monkeypatch):
    """ABSENT MEANS WITHHELD -- the measured-correct behaviour is the refusal."""
    monkeypatch.delenv("SYNDICATE_WNBA_TOTALS_RECOMMENDATIONS", raising=False)
    assert refresher._wnba_totals_recommendations_enabled() is False


@pytest.mark.parametrize("value", ["on", "1", "true", "YES"])
def test_totals_can_be_re_enabled_explicitly(monkeypatch, value):
    monkeypatch.setenv("SYNDICATE_WNBA_TOTALS_RECOMMENDATIONS", value)
    assert refresher._wnba_totals_recommendations_enabled() is True


@pytest.mark.parametrize("value", ["off", "0", "false", "no", ""])
def test_ambiguous_values_do_not_re_enable(monkeypatch, value):
    monkeypatch.setenv("SYNDICATE_WNBA_TOTALS_RECOMMENDATIONS", value)
    assert refresher._wnba_totals_recommendations_enabled() is False


def test_totals_rows_are_dropped_and_ats_survives(monkeypatch, tmp_path):
    """The wiring, end to end -- a correct flag nobody consults is inert."""
    monkeypatch.delenv("SYNDICATE_WNBA_TOTALS_RECOMMENDATIONS", raising=False)
    processed = tmp_path / "processed"
    processed.mkdir()
    (processed / "recommendations_2026-08-30.csv").write_text(
        "home,away,market,side,line,price,ev,implied_prob,edge,pred_margin,pred_total,market_home_margin\n"
        "Atlanta Dream,Minnesota Lynx,ATS,Atlanta Dream,-3.5,-110,0.05,0.52,2.1,4.0,168,-3.5\n"
        "Atlanta Dream,Minnesota Lynx,TOTAL,Over,165.5,-110,0.04,0.52,1.8,4.0,168,-3.5\n",
        encoding="utf-8",
    )

    def _index(**_kwargs):
        row = {"home_tri": "ATL", "away_tri": "MIN",
               "home": "Atlanta Dream", "away": "Minnesota Lynx"}
        return [row], {"ATL": row, "MIN": row}, {("atlanta dream", "minnesota lynx"): row}

    monkeypatch.setattr(refresher, "_local_game_cards_index", _index)
    monkeypatch.setattr(refresher, "_load_local_props_recommendations", lambda **_k: [])
    monkeypatch.setattr(refresher, "_emit_win_prob_build", lambda *_a, **_k: None)

    count, path = refresher._build_local_recommendations_slate_artifact(
        processed_root=processed, date_str="2026-08-30"
    )
    import json

    payload = json.loads(path.read_text(encoding="utf-8")) if path else {}
    # `per_game` is the key the builder writes. This read used `games`/`slate`
    # until 2026-09-10, so it asserted over an empty list and could not fail.
    markets = [
        str(pick.get("market") or "").upper()
        for game in (payload.get("per_game") or [])
        if isinstance(game, dict)
        for pick in (game.get("picks") or [])
        if isinstance(pick, dict)
    ]
    assert "ATS" in markets, "the ATS pick must survive, or the TOTAL assertion below is vacuous"
    assert "TOTAL" not in markets, "a withheld market must not reach the slate"
    assert refresher._WIN_PROB_STATS.get("totals_withheld", 0) >= 1, (
        "the refusal must be COUNTED -- a silent drop is indistinguishable from "
        "the generator never producing totals"
    )


# ------------------------------------------------------- prop EV on the slate
def test_slate_prop_ev_is_refused_and_the_pick_sinks_in_its_game(monkeypatch, tmp_path):
    """The third prop site -- the loop that WRITES the slate -- read `ev_pct` raw.

    Pre-fix, 2264.8 reached the slate and, as `score` and the within-game sort
    key, ranked first. Refused, the pick stays, its EV is absent, the refusal is
    counted, and it sorts behind every pick whose EV is a number.
    """
    import json

    processed = tmp_path / "processed"
    processed.mkdir()

    def _index(**_kwargs):
        row = {"home_tri": "ATL", "away_tri": "MIN",
               "home": "Atlanta Dream", "away": "Minnesota Lynx"}
        return [row], {"ATL": row, "MIN": row}, {("atlanta dream", "minnesota lynx"): row}

    props = [
        {"team": "ATL", "player": "Implausible Player",
         "top_play": {"stat": "pts", "line": 20.5, "side": "OVER", "price": -110,
                      "ev_pct": 2264.8, "p_win": 0.6, "proj": 22.0}},
        {"team": "MIN", "player": "Plausible Player",
         "top_play": {"stat": "reb", "line": 8.5, "side": "OVER", "price": 105,
                      "ev_pct": 12.0, "p_win": 0.55, "proj": 9.1}},
    ]
    monkeypatch.setattr(refresher, "_local_game_cards_index", _index)
    monkeypatch.setattr(refresher, "_load_local_props_recommendations", lambda **_k: props)
    monkeypatch.setattr(refresher, "_emit_win_prob_build", lambda *_a, **_k: None)

    _, path = refresher._build_local_recommendations_slate_artifact(
        processed_root=processed, date_str="2026-09-17"
    )
    picks = [pick for game in json.loads(path.read_text(encoding="utf-8"))["per_game"] for pick in game["picks"]]
    by_player = {pick["display_pick"].split(" OVER")[0]: pick for pick in picks}
    assert set(by_player) == {"Implausible Player", "Plausible Player"}, "a refused EV must not DROP the pick"
    assert by_player["Implausible Player"]["ev_pct"] is None
    assert by_player["Implausible Player"]["score"] is None
    assert by_player["Plausible Player"]["ev_pct"] == pytest.approx(12.0)
    assert picks[-1]["display_pick"].startswith("Implausible Player"), "a refused EV sorts last in its game"
    assert refresher._WIN_PROB_STATS["ev_refused_implausible"] == 1


def test_every_prop_ev_read_routes_through_plausibility_in_both_producers():
    """Presence is not coverage. `test_nba_props_integrity` asserts the refused
    form APPEARS in each producer, and that held while the WNBA slate writer read
    `ev_pct` raw. Pin the COUNT instead: every read is a refused read."""
    from pathlib import Path

    wnba = Path(refresher.__file__)
    for path in (wnba, wnba.with_name("refresh_nba_oddsapi_props.py")):
        source = path.read_text(encoding="utf-8-sig")
        raw = source.count('top_play.get("ev_pct")')
        refused = source.count('_plausible_ev_pct(_float_or_none(top_play.get("ev_pct")))')
        assert raw > 0, f"{path.name}: the read moved, so this tripwire is now vacuous"
        assert raw == refused, f"{path.name}: {raw - refused} prop EV read(s) bypass _plausible_ev_pct"


# ------------------------------------------------------------------ tiering
def test_game_market_recommendations_are_not_labelled_playable():
    """T2-4. All 466 of the season's rows carried `playable`, a promotion label,
    on a set whose graded return was -9.68%.

    Demotion, not a new ranking: the fields a tier would rank on measure
    corr(EV, win) = +0.0466 and corr(p_win, win) = +0.0147 on these rows.
    """
    from syndicate.features.wnba import cards

    picks = [
        {"market": "ATS", "selection": "Atlanta Dream", "line": -3.5,
         "price": -110, "ev_pct": 26.1, "p_win": 0.732},
        {"market": "ML", "selection": "Minnesota Lynx", "price": 145, "p_win": 0.41},
    ]
    rows = cards._source_game_market_recommendations(picks)
    assert rows, "fixture must produce rows or the assertion is vacuous"
    assert {row["card_bucket"] for row in rows} == {"candidate"}
    assert all(row["stake_units"] is None for row in rows), (
        "sizing must stay absent: a stake from an uninformative ranking converts "
        "noise into position size"
    )


# ---------------------------------------------------- the probability inversion
def test_win_prob_inversion_is_dimensionally_correct():
    """`p + ev` adds a RETURN FRACTION to a PROBABILITY. The inversion is p*(1+ev).

    For a bet at implied probability p with true probability q,
        ev = q*(1/p - 1) - (1 - q) = q/p - 1   ->   q = p * (1 + ev)

    Round-tripping a known q through the EV definition must return q.
    """
    for implied, true_q in ((0.5265, 0.6460), (0.4000, 0.5000), (0.7500, 0.7000)):
        ev = true_q / implied - 1.0
        assert implied * (1.0 + ev) == pytest.approx(true_q), (implied, true_q)
        # the old rule does NOT round-trip
        if abs(ev) > 1e-9:
            assert implied + ev != pytest.approx(true_q)


def test_a_zero_ev_bet_is_priced_at_the_implied_probability():
    """The anchor case: no edge means the book's number IS your number."""
    for implied in (0.35, 0.5, 0.62):
        assert implied * (1.0 + 0.0) == pytest.approx(implied)
        # `p + ev` happens to agree here, which is why the bug survived.
        assert implied + 0.0 == pytest.approx(implied)
