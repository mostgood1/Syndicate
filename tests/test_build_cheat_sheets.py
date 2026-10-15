"""Cheat sheets: every row carries a price check, and a streak only counts beyond what the price already implies."""
from __future__ import annotations

import importlib.util
from pathlib import Path

from syndicate.features.shared import cheat_sheets as cs


def _row(side="over", line=60.5, price=-110, fair=0.5, model_over=None, skill=None, suggested=False, ev=None):
    return {"kind": "prop", "side": side, "line": line, "suggested": suggested, "ev_pct": ev,
            "quote": {"price": price, "bookmaker": "fanduel", "fair_probability": fair, "book_prices": {"fanduel": price}},
            "projection": {"model_prob_over": model_over, "model_skill": skill}}


def test_form_record_counts_hits_newest_first_and_skips_pushes():
    values = [70, 61, 60.5, 40, 90, 10, 100]          # newest first
    rec = cs.form_record(values, 60.5, "over", 5)
    assert rec == {"games": 4, "hits": 3, "rate": 0.75, "values": [70.0, 61.0, 60.5, 40.0, 90.0]}
    assert cs.form_record(values, 60.5, "under", 5)["hits"] == 1
    assert cs.form_record(None, 60.5, "over", 5)["rate"] is None


def test_the_posterior_is_anchored_on_the_market():
    # 5-for-5 against a 75% price moves it only to 80% at k = 20 -- a streak the line was set knowing.
    assert cs.consistency_posterior(0.75, 5, 5, k=20) == 0.8
    assert cs.consistency_posterior(0.75, 5, 5) == 0.7778          # default k = 40 (provisional)
    assert cs.consistency_posterior(0.5, 0, 0) == 0.5
    assert cs.consistency_posterior(None, 5, 5) is None


def test_ev_and_odds_math():
    assert cs.decimal_odds(150) == 2.5 and round(cs.decimal_odds(-200), 4) == 1.5
    assert cs.ev_pct(0.5, 100) == 0.0 and cs.ev_pct(0.6, 100) == 20.0
    assert round(cs.implied_from_price(-300), 4) == 0.75


def test_a_streak_already_in_the_price_is_labelled_priced_in():
    # Tout ticket: cleared 60+ in 5 of 5, priced -490 (implied 83%); fair 0.78 -> posterior (31.2 + 5) / 45 = 0.8044
    # at k = 40, below the 83% the price implies, so EV at -490 is about -3.1%.
    row = _row(price=-490, fair=0.78, line=59.5)
    check = cs.price_check(row, [144, 68, 89, 73, 102])
    assert check.form5 == {"games": 5, "hits": 5, "rate": 1.0, "values": [144.0, 68.0, 89.0, 73.0, 102.0]}
    assert check.p_posterior == 0.8044
    assert check.ev_posterior < 0 and check.verdict == "streak_priced_in"
    assert "already implies 83%" in check.reasons[0]


def test_a_streak_with_room_and_value_rows():
    # 5/5 recent, 5/7 overall; fair 0.48 at +100 (market EV -4%) -> posterior (19.2 + 5) / 47 = 0.5149 -> EV +2.98%.
    with_room = cs.price_check(_row(price=100, fair=0.48, line=59.5), [70, 80, 90, 75, 65, 30, 20])
    assert with_room.verdict == "streak_with_room" and with_room.ev_posterior == 2.98 and with_room.ev_market == -4.0
    value = cs.price_check(_row(price=120, fair=0.5, line=59.5), [10, 20, 30])
    assert value.verdict == "value" and value.ev_market == 10.0


def test_model_lean_and_skill_note_are_shown_not_trusted():
    check = cs.price_check(_row(fair=0.5, model_over=0.62, skill={"established_loss_rel": 0.10114}), [])
    assert check.verdict == "neutral" and check.p_model == 0.62
    assert any("model 62% vs market 50%" in r for r in check.reasons)
    assert any("model loses to the book" in r for r in check.reasons)
    assert cs.price_check(_row(side="under", model_over=0.62), []).p_model == 0.38


def test_game_script_reads_the_sim_margin():
    lean = cs.game_script({"margin_mean": -6.2, "total_mean": 44.1, "home_win_rate": 0.31}, "MIA", "KC")
    assert lean["leader"] == "KC" and lean["trailer"] == "MIA" and "KC rushing volume" in lean["helped"]
    assert cs.game_script({"margin_mean": 1.0}, "A", "B")["script"] == "close"
    assert cs.game_script(None, "A", "B") is None


def test_sections_sort_by_the_number_that_matters():
    rows = [{"check": {"verdict": "value", "ev_market": 3.0}}, {"check": {"verdict": "value", "ev_market": 9.0}},
            {"check": {"verdict": "streak_priced_in", "ev_posterior": -5.0}},
            {"check": {"verdict": "streak_priced_in", "ev_posterior": -12.0}}]
    s = cs.sections(rows)
    assert s["value"] == [1, 0] and s["streaks_priced_in"] == [3, 2] and s["streaks_with_room"] == []


def _script():
    spec = importlib.util.spec_from_file_location(
        "build_cheat_sheets", Path(__file__).resolve().parents[1] / "scripts" / "build_cheat_sheets.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_generator_groups_pregame_full_game_props_and_builds_evidence_once_per_group(monkeypatch):
    m = _script()
    calls = []
    monkeypatch.setattr(m, "evidence_facts", lambda row, selected_date: calls.append(row["player_name"]) or {
        "recent_form": {"values": [80, 70, 65, 90, 61], "game_labels": ["W5", "W4", "W3", "W2", "W1"]},
        "advanced": {"pos": "RB", "team": "BAL"}, "matchup": {"opponent": "CLE"},
        "game_sim": {"home_score_mean": 17.0, "away_score_mean": 26.0}})
    base = {"kind": "prop", "game_state": "pregame", "segment": "full", "event_id": "e1", "home_team": "CLE",
            "away_team": "BAL", "market": "Rushing Yards", "player_name": "Derrick Henry"}
    rows = [dict(base, line=59.5, side="over", quote={"price": -490, "fair_probability": 0.78, "book_prices": {"fd": -490}}),
            dict(base, line=79.5, side="over", quote={"price": -150, "fair_probability": 0.58, "book_prices": {"fd": -150, "dk": -155}}),
            dict(base, game_state="live", line=59.5, side="over", quote={}),
            dict(base, player_name="Someone", segment="h1", line=9.5, side="over", quote={})]
    dvp = {"teams": {"CLE": {"RB": {"rush_yds": {"rank": 30, "of": 32, "per_game": 128.0, "games": 5}}}}, "through_week": 5}
    sheet = m.build_sport("nfl", rows, selected_date="2026-10-14", cap=10, dvp=dvp)
    assert calls == ["Derrick Henry"] and len(sheet["rows"]) == 2           # live and h1 rows dropped; one evidence call
    assert sheet["rows"][0]["dvp"]["nth_most"] == 3                          # rank 30 of 32 fewest = 3rd most allowed
    assert sheet["games"][0]["script"]["leader"] == "BAL"
    verdicts = {r["line"]: r["check"]["verdict"] for r in sheet["rows"]}
    assert verdicts[59.5] == "streak_priced_in"


def test_shop_gap_is_best_vs_median_book_and_needs_three_books():
    gap = cs.shop_gap({"fanduel": -120, "draftkings": -115, "betmgm": 105})
    assert gap["best_book"] == "betmgm" and gap["books"] == 3
    assert gap["gap_pp"] == round(100 * (115 / 215 - 100 / 205), 2)      # median -115 vs best +105
    assert cs.shop_gap({"a": -110, "b": -105}) is None


def test_dvp_extremes_turn_fewest_ranks_into_most_allowed():
    teams = {"MIA": {"RB": {"rush_yds": {"rank": 32, "of": 32, "per_game": 150.0, "games": 5}},
                     "WR": {"rec_yds": {"rank": 2, "of": 32, "per_game": 120.0, "games": 5}}}}
    out = cs.dvp_extremes(teams, "MIA")
    assert [(c["pos"], c["stat"], c["nth_most"]) for c in out] == [("RB", "rush_yds", 1), ("WR", "rec_yds", 31)]
    assert cs.dvp_extremes(teams, "XXX") == []


def test_kickoff_is_the_games_date_and_time_in_central():
    m = _script()
    assert m.kickoff_ct("2026-10-18T20:05:00Z") == "Sun Oct 18 · 3:05 PM CT"
    assert m.kickoff_ct("2026-10-15T00:40:00Z") == "Wed Oct 14 · 7:40 PM CT"
    assert m.kickoff_ct(None) is None


def test_identity_fills_team_logo_position_and_headshot_without_overriding_the_evidence(monkeypatch):
    m = _script()
    from syndicate.features.shared import layer2_row_context, team_logos

    monkeypatch.setattr(layer2_row_context, "row_identity",
                        lambda row, ctx: {"headshot_url": "https://img/" + row["player_name"], "player_side": "home"})
    monkeypatch.setattr(team_logos, "logo_url", lambda sport, *names: f"logo:{sport}:{names[0]}")
    row = {"player_name": "Martin Necas", "home_team": "Colorado Avalanche", "away_team": "Dallas Stars"}
    positions = {"nhl": {"martinnecas": "F"}}
    got = m.player_identity(row, sport="nhl", team=None, pos=None, context={}, positions=positions)
    assert got["team"] == "Colorado Avalanche" and got["pos"] == "F" and got["headshot_url"] == "https://img/Martin Necas"
    assert got["team_logo"] == "logo:nhl:Colorado Avalanche" and got["opponent_logo"] == "logo:nhl:Dallas Stars"
    kept = m.player_identity(row, sport="nhl", team="COL", pos="C", context={}, positions=positions)
    assert kept["team"] == "COL" and kept["pos"] == "C"                       # the evidence layer wins

    def boom(row, ctx):
        raise RuntimeError("no roster")

    monkeypatch.setattr(layer2_row_context, "row_identity", boom)
    bare = m.player_identity(row, sport="nhl", team=None, pos=None, context={}, positions=positions)
    assert bare["headshot_url"] is None and bare["team_logo"] is None and bare["pos"] == "F"   # unknown side: no crest


def test_sports_get_sheets_only_inside_their_regular_season():
    m = _script()
    assert m.in_season("nba", "2026-10-20") and not m.in_season("nba", "2026-10-14")       # preseason: no sheet
    assert not m.in_season("ncaab", "2026-11-01") and m.in_season("ncaab", "2026-11-02")
    assert not m.in_season("mlb", "2026-10-14") and not m.in_season("wnba", "2026-10-14")   # postseason / offseason
    assert m.in_season("nfl", "2026-10-14") and m.in_season("soccer", "2026-07-01")         # soccer is never gated


def test_a_short_team_name_from_the_evidence_finds_its_side(monkeypatch):
    m = _script()
    from syndicate.features.shared import layer2_row_context, team_logos

    monkeypatch.setattr(layer2_row_context, "row_identity", lambda row, ctx: {"headshot_url": None})   # no side known
    logos = {"Sam Houston State Bearkats": "shsu.png", "Western Kentucky Hilltoppers": "wku.png"}
    monkeypatch.setattr(team_logos, "logo_url", lambda sport, *names: logos.get(names[0]))
    row = {"player_name": "Hunter Watson", "home_team": "Sam Houston State Bearkats", "away_team": "Western Kentucky Hilltoppers"}
    got = m.player_identity(row, sport="ncaaf", team="Sam Houston", pos="QB", context={}, positions={})
    assert got["team_logo"] == "shsu.png" and got["opponent_logo"] == "wku.png" and got["team"] == "Sam Houston"
    nope = m.player_identity(row, sport="ncaaf", team="Houston", pos="QB", context={}, positions={})
    assert nope["team_logo"] is None                                       # "Houston" is neither side: no crest
