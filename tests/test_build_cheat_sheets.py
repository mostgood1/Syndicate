"""Cheat sheets: every row carries a price check, and a streak only counts beyond what the price already implies."""
from __future__ import annotations

import importlib.util
import json
import statistics
from pathlib import Path

import pytest

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
            "away_team": "BAL", "market": "Rushing Yards", "player_name": "Derrick Henry", "commence_time": "2026-10-15T00:15:00Z"}
    rows = [dict(base, line=59.5, side="over", quote={"price": -490, "fair_probability": 0.78, "book_prices": {"fd": -490}}),
            dict(base, line=79.5, side="over", quote={"price": -150, "fair_probability": 0.58, "book_prices": {"fd": -150, "dk": -155}}),
            dict(base, game_state="live", line=59.5, side="over", quote={}),
            dict(base, player_name="Someone", segment="h1", line=9.5, side="over", quote={}),
            dict(base, event_id="e2", player_name="Sunday Guy", commence_time="2026-10-18T17:00:00Z", line=9.5,
                 side="over", quote={"price": -110, "fair_probability": 0.5})]                 # Sunday: not 10-14's sheet
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


def test_sheets_cover_regular_season_and_postseason_never_preseason():
    m = _script()
    assert m.season_phase("mlb", "2026-10-14") == "postseason"                               # the LCS gets a sheet
    assert m.season_phase("nba", "2026-10-14") is None and m.season_phase("nba", "2026-10-20") == "regular"   # preseason: none
    assert not m.in_season("ncaab", "2026-11-01") and m.in_season("ncaab", "2026-11-02")
    assert m.season_phase("wnba", "2026-10-14") is None                                     # offseason
    assert m.season_phase("nfl", "2026-10-14") == "regular" and m.season_phase("soccer", "2026-07-01") == "regular"


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


def test_a_days_sheet_is_a_record_started_games_keep_their_last_rows():
    m = _script()
    from datetime import datetime, timezone

    def row(event, player, start):
        return {"event_id": event, "player": player, "commence_time": start, "check": {"verdict": "value", "ev_market": 3.0}}

    prior = {"date": "2026-10-14", "generated_at": "2026-10-14T14:00:00Z",
             "rows": [row("early", "A", "2026-10-14T18:00:00Z"), row("late", "B", "2026-10-15T00:40:00Z"),
                      row("sunday", "C", "2026-10-18T17:00:00Z")],                         # a pre-rule row from Sunday
             "games": [{"event_id": "early"}, {"event_id": "late"}, {"event_id": "sunday"}]}
    fresh = {"date": "2026-10-14", "rows": [row("late", "B2", "2026-10-15T00:40:00Z")], "games": [{"event_id": "late"}],
             "sections": {}}
    merged = m.merge_with_record(fresh, prior, now=datetime(2026, 10, 14, 23, 0, tzinfo=timezone.utc))
    assert [r["player"] for r in merged["rows"]] == ["B2", "A"]           # fresh prices for 'late', 'early' frozen, Sunday gone
    assert {g["event_id"] for g in merged["games"]} == {"late", "early"} and merged["rows_frozen"] == 1
    assert next(g for g in merged["games"] if g["event_id"] == "early")["frozen_at"] == "2026-10-14T14:00:00Z"
    assert merged["sections"]["value"] == [0, 1]
    assert m.merge_with_record(fresh, None, now=datetime.now(timezone.utc)) is fresh


def test_central_day_is_the_games_date_in_central():
    m = _script()
    assert m.central_day("2026-10-15T00:40:00Z") == "2026-10-14"          # 7:40 PM CT on the 14th
    assert m.central_day("2026-10-15T05:30:00Z") == "2026-10-15" and m.central_day(None) is None


def test_started_games_rebuild_from_their_last_pregame_quotes(tmp_path):
    m = _script()
    from datetime import datetime, timezone

    from syndicate.features.shared.opportunity_signals import devig

    folder = tmp_path / "mlb_source" / "tracking" / "book_quotes"
    folder.mkdir(parents=True)

    def q(book, sel, price, t, **extra):
        rec = {"kind": "prop", "segment": "full", "event_id": "g1", "market": "Hits", "player_name": "Shohei Ohtani",
               "line": 0.5, "bookmaker": book, "selection": sel, "price": price, "captured_at": t,
               "commence_time": "2026-10-15T00:10:00Z", "home_team": "Los Angeles Dodgers", "away_team": "Milwaukee Brewers"}
        rec.update(extra)
        return rec

    recs = [q("dk", "over", -150, "2026-10-14T20:00:00Z"), q("dk", "under", 120, "2026-10-14T20:00:00Z"),
            q("dk", "over", -170, "2026-10-14T23:50:00Z"), q("dk", "under", 135, "2026-10-14T23:50:00Z"),   # dk's last pair
            q("fd", "over", -160, "2026-10-14T23:00:00Z"), q("fd", "under", 130, "2026-10-14T23:00:00Z"),
            q("fd", "over", -400, "2026-10-15T01:00:00Z"),                                                   # in-play: ignored
            q("dk", "yes", 900, "2026-10-14T23:00:00Z", market="Anytime HR"),                                 # one-sided: left out
            q("dk", "over", -110, "2026-10-14T23:00:00Z", event_id="later", commence_time="2026-10-15T02:00:00Z")]
    (folder / "2026-10-14.jsonl").write_text("".join(json.dumps(r) + "\n" for r in recs), encoding="utf-8")
    now = datetime(2026, 10, 15, 1, 30, tzinfo=timezone.utc)
    rows = m.quote_rows(tmp_path, "mlb", "2026-10-14", skip_events=set(), now=now)
    assert sorted((r["market"], r["side"]) for r in rows) == [("Hits", "over"), ("Hits", "under")]      # not 'later': not started
    over = next(r for r in rows if r["side"] == "over")
    fair = statistics.median([devig([-170, 135], method="shin")[0], devig([-160, 130], method="shin")[0]])
    assert over["quote"]["price"] == -160 and over["quote"]["bookmaker"] == "fd" and over["rebuilt"] is True
    assert over["quote"]["fair_probability"] == pytest.approx(fair) and over["quote"]["book_prices"] == {"dk": -170.0, "fd": -160.0}
    assert m.quote_rows(tmp_path, "mlb", "2026-10-14", skip_events={"g1"}, now=now) == []               # the record already has it


def test_one_sided_hot_form_gets_its_own_section_and_every_prop_is_listed():
    hot = {"player": "Shooter", "market": "player_shots", "line": 0.5, "side": "over",
           "check": {"verdict": "one_sided_fair", "form5": {"games": 5, "hits": 5}, "form10": {"games": 10, "hits": 9, "rate": 0.9}}}
    cold = dict(hot, player="Bench", check={"verdict": "one_sided_fair", "form5": {"games": 5, "hits": 1}, "form10": {"games": 10, "hits": 2, "rate": 0.2}})
    priced = dict(hot, player="Priced", check={"verdict": "streak_priced_in", "form5": {"games": 5, "hits": 5}, "form10": {"games": 10, "hits": 9, "rate": 0.9}})
    s = cs.sections([hot, cold, priced])
    assert s["hot_form"] == [0]                                  # only one-sided rows: a priced streak has its own section
    assert sorted(s["every_prop"]) == [0, 1, 2] and s["value"] == []


def test_a_moved_line_does_not_leave_a_stale_price_behind(tmp_path):
    m = _script()
    from datetime import datetime, timezone

    folder = tmp_path / "mlb_source" / "tracking" / "book_quotes"
    folder.mkdir(parents=True)

    def q(book, line, sel, price, t):
        return {"kind": "prop", "segment": "full", "event_id": "g1", "market": "strikeouts", "player_name": "Blake Snell",
                "line": line, "bookmaker": book, "selection": sel, "price": price, "captured_at": t,
                "commence_time": "2026-10-15T00:10:00Z", "home_team": "Los Angeles Dodgers", "away_team": "Milwaukee Brewers"}

    recs = [q("bk", 5.5, "over", -230, "2026-10-14T18:00:00Z"), q("bk", 5.5, "under", 178, "2026-10-14T18:00:00Z"),   # bk moved...
            q("bk", 6.5, "over", -120, "2026-10-14T23:30:00Z"), q("bk", 6.5, "under", 100, "2026-10-14T23:30:00Z"),   # ...to 6.5
            q("dk", 5.5, "over", -250, "2026-10-14T23:40:00Z"), q("dk", 5.5, "under", 190, "2026-10-14T23:40:00Z")]
    (folder / "2026-10-14.jsonl").write_text("".join(json.dumps(r) + "\n" for r in recs), encoding="utf-8")
    rows = m.quote_rows(tmp_path, "mlb", "2026-10-14", skip_events=set(), now=datetime(2026, 10, 15, 1, 0, tzinfo=timezone.utc))
    under55 = next(r for r in rows if r["line"] == 5.5 and r["side"] == "under")
    assert under55["quote"]["book_prices"] == {"dk": 190.0}                       # bk's abandoned 5.5 is gone
    assert {r["line"] for r in rows} == {5.5, 6.5}


def test_an_implausible_edge_is_a_price_to_check_not_value():
    row = {"side": "under", "line": 5.5, "quote": {"price": 178, "fair_probability": 0.42, "fair_method": "consensus"}, "projection": {}}
    check = cs.price_check(row, [])
    assert check.ev_market > 10 and check.verdict == "suspect_price"
