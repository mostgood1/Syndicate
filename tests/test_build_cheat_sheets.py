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
    rows = [{"player": "A", "check": {"verdict": "value", "ev_market": 3.0, "price": -110}},
            {"player": "B", "check": {"verdict": "value", "ev_market": 9.0, "price": 120}},
            {"player": "C", "check": {"verdict": "streak_priced_in", "ev_posterior": -5.0, "price": -150}},
            {"player": "D", "check": {"verdict": "streak_priced_in", "ev_posterior": -12.0, "price": -200}}]
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
        return {"event_id": event, "player": player, "commence_time": start, "check": {"verdict": "value", "ev_market": 3.0, "price": -110}}

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
           "check": {"verdict": "one_sided_fair", "price": 120, "form5": {"games": 5, "hits": 5}, "form10": {"games": 10, "hits": 9, "rate": 0.9}}}
    cold = dict(hot, player="Bench", check={"verdict": "one_sided_fair", "price": 120, "form5": {"games": 5, "hits": 1}, "form10": {"games": 10, "hits": 2, "rate": 0.2}})
    priced = dict(hot, player="Priced", check={"verdict": "streak_priced_in", "price": -120, "form5": {"games": 5, "hits": 5}, "form10": {"games": 10, "hits": 9, "rate": 0.9}})
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


def test_exchange_prices_are_valued_net_of_the_taker_fee(monkeypatch):
    from syndicate.features.shared import venue_fees

    monkeypatch.setattr(venue_fees, "taker_fee_per_contract", lambda book, q, **kw: (0.02, "test", False) if book == "kalshi" else (0.0, "none", False))
    row = {"side": "over", "line": 0.5, "sport": "mlb", "market": "batter_hits",
           "quote": {"price": -163, "fair_probability": 0.65, "fair_method": "consensus", "bookmaker": "kalshi"}, "projection": {}}
    gross = cs.ev_pct(0.65, -163)
    net = cs.price_check(row, []).ev_market
    q = 163 / 263
    assert net == round(100 * (0.65 - q - 0.02) / (q + 0.02), 2) and net < gross
    book = dict(row, quote=dict(row["quote"], bookmaker="draftkings"))
    assert cs.price_check(book, []).ev_market == gross                      # a sportsbook pays no fee on top


def test_game_lines_are_price_checked_and_kept_as_a_record(monkeypatch):
    m = _script()
    from datetime import datetime, timezone

    monkeypatch.setattr(m, "evidence_facts", lambda row, selected_date: {})
    base = {"kind": "game", "game_state": "pregame", "segment": "full", "event_id": "g1", "home_team": "Denver Broncos",
            "away_team": "Seattle Seahawks", "commence_time": "2026-10-16T00:15:00Z"}
    rows = [dict(base, market="spreads", side="home", line=-3.5, model_probability_cal=0.55, projection={"projected": 4.1, "side": "Denver Broncos"},
                 quote={"price": 105, "fair_probability": 0.52, "fair_method": "consensus", "bookmaker": "fanduel",
                        "book_prices": {"fanduel": 105, "draftkings": -110, "betmgm": -115}}),
            dict(base, market="totals", side="over", line=44.5, quote={"price": -110, "fair_probability": 0.5, "bookmaker": "dk"}),
            dict(base, market="h2h", segment="h1", side="home", quote={"price": -120, "fair_probability": 0.5}),     # not full game
            dict(base, game_state="live", market="h2h", side="home", quote={"price": -120, "fair_probability": 0.5})]  # in play
    sheet = m.build_sport("nfl", rows, selected_date="2026-10-15", cap=10, dvp={})
    assert [(g["market"], g["side_name"]) for g in sheet["game_lines"]] == [("spreads", "Denver Broncos"), ("totals", "over")]
    spread = sheet["game_lines"][0]
    assert spread["check"]["verdict"] == "value" and spread["check"]["ev_market"] == round(100 * (0.52 * 2.05 - 1), 2)
    assert spread["check"]["p_model"] == 0.55 and spread["projected"] == 4.1 and spread["shop"]["books"] == 3
    assert sheet["games"][0]["matchup"] == "Seattle Seahawks @ Denver Broncos"        # a game with no props still listed
    fresh = dict(sheet, rows=[], game_lines=[], games=[], sections={})                # later build: the game has started
    merged = m.merge_with_record(fresh, sheet, now=datetime(2026, 10, 16, 1, 0, tzinfo=timezone.utc))
    assert len(merged["game_lines"]) == 2 and merged["games"][0]["event_id"] == "g1"


def test_the_day_ahead_is_tomorrow_in_central(monkeypatch):
    m = _script()
    monkeypatch.setattr(m, "central_today", lambda: "2026-10-14")
    seen = {}
    monkeypatch.setattr(m, "fetch_rows", lambda base, sport: [])
    monkeypatch.setattr(m, "latest_nfl_dvp", lambda root: {})
    real = m.build_sport

    def spy(sport, rows, *, selected_date, **kw):
        seen["date"] = selected_date
        return real(sport, rows, selected_date=selected_date, **kw)

    monkeypatch.setattr(m, "build_sport", spy)
    import tempfile
    with tempfile.TemporaryDirectory() as root:
        m.main(["--data-root", root, "--date", "tomorrow", "--sports", "nfl"])
    assert seen["date"] == "2026-10-15"


def test_consistency_and_matchup_sections():
    def row(player, side="over", f5=(5, 5), f10=(10, 9), matchup=None, vs=None):
        return {"player": player, "side": side, "line": 2.5, "matchup": matchup, "vs_opponent": vs,
                "check": {"verdict": "neutral", "price": -115, "form5": {"games": f5[0], "hits": f5[1], "rate": f5[1] / f5[0]},
                          "form10": {"games": f10[0], "hits": f10[1], "rate": f10[1] / f10[0]}}}

    rows = [row("A", f10=(10, 8)), row("B", f10=(10, 10)), row("C", f10=(6, 6)), row("D", f10=(10, 6)),
            row("E", matchup={"nth_most": 2, "of": 32}), row("F", side="under", matchup={"nth_most": 2, "of": 32}),
            row("G", side="under", matchup={"nth_most": 31, "of": 32}), row("H", vs={"games": 3, "hits": 3, "same_line": True}),
            row("I", vs={"games": 3, "hits": None, "same_line": False}), row("J", vs={"games": 2, "hits": 2, "same_line": True})]
    s = cs.sections(rows)
    assert [rows[i]["player"] for i in s["consistency"]][:2] == ["B", "E"] and 2 not in s["consistency"] and 3 not in s["consistency"]
    assert {rows[i]["player"] for i in s["matchup_spots"]} == {"E", "G", "H"}       # soft D for an over, tough D for an under, 3/3 vs opp (2/2: too few)
    assert cs.matchup_summary("ncaaf", {"opponent": "Memphis", "allowed_rank": "79 of 138 (1 = fewest allowed)", "allowed_per_game": 219.7}, None) == \
        {"opponent": "Memphis", "nth_most": 60, "of": 138, "per_game": 219.7, "stat": None, "pos": None, "source": "allowed_rank"}
    vs = {"vs_opponent": {"games": 2, "hit_rate": {"games": 2, "hits": 2, "line": 3.5, "side": "over"}}}
    assert cs.vs_opponent_record(vs, 3.5, "over") == {"games": 2, "hits": 2, "same_line": True}
    assert cs.vs_opponent_record(vs, 4.5, "over") == {"games": 2, "hits": None, "same_line": False}   # another line: no rate
    with_values = {"vs_opponent": {"games": 4, "values": [5, 2, 4, 3], "hit_rate": {"line": 3.5, "side": "over"}}}
    got = cs.vs_opponent_record(with_values, 2.5, "over")                                 # any line, graded
    assert (got["games"], got["hits"], got["same_line"]) == (4, 3, True)
    got = cs.vs_opponent_record(with_values, 3.0, "under")                                # the 3.0 push drops
    assert (got["games"], got["hits"]) == (3, 1)
    one = {"vs_opponent": {"games": 1, "values": [228.0], "labels": ["24-W16"]}}           # one meeting: show what happened
    assert cs.vs_opponent_record(one, 199.5, "under")["results"] == [{"label": "24-W16", "value": 228.0, "hit": 0}]


def test_featured_sections_keep_a_sane_price_and_one_line_per_bet():
    def row(player, price, ev, line=2.5, market="Receptions"):
        return {"player": player, "market": market, "side": "under", "line": line,
                "check": {"verdict": "value", "ev_market": ev, "price": price}}

    rows = [row("Nix", -112, 3.0, 199.5, "Passing Yards"), row("Nix", -113, 4.0, 197.5, "Passing Yards"),
            row("Nix", -117, 2.5, 201.5, "Passing Yards"), row("Shaheed", 163, 6.0, 1.5), row("Kupp", -400, 5.0),
            row("Waddle", 250, 2.1), row("Mims", -251, 2.2)]
    s = cs.sections(rows)
    assert [rows[i]["player"] for i in s["value"]] == ["Shaheed", "Nix", "Waddle"]      # -400 and -251 out; one Nix
    assert rows[s["value"][1]]["line"] == 197.5                                          # the best-EV Nix rung
    assert len(s["every_prop"]) == 7                                                     # the full table stays complete


def test_the_evidence_layer_reads_the_same_data_root_as_the_generator(monkeypatch, tmp_path):
    # A hand run without SYNDICATE_DATA_ROOT read the checkout's data/ mirror: sheets with no positions or matchups,
    # and no error (2026-10-15). Unset -> set from --data-root; a different root -> refused, never mixed.
    m = _script()
    monkeypatch.delenv("SYNDICATE_DATA_ROOT", raising=False)
    assert m.align_data_root(tmp_path) is None
    import os
    assert os.environ["SYNDICATE_DATA_ROOT"] == str(tmp_path)
    assert m.align_data_root(tmp_path) is None                                   # the same root again is fine
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path / "elsewhere"))
    assert "different root" in m.align_data_root(tmp_path)


def test_mlb_rows_get_faces_and_positions_from_the_days_rosters(monkeypatch, tmp_path):
    # 10-14: a face for 1 of 21 MLB players and a position for none -- the board carries an id only on props the sim
    # projected, and a sheet rebuilt from quotes carries none. Only EMPTY fields are filled.
    m = _script()
    from syndicate.features.mlb import batter_vs_pitcher as bvp
    monkeypatch.setattr(bvp, "player_ids", lambda api, date: {"blakesnell": {"id": 605483, "position": "P"},
                                                               "shoheiohtani": {"id": 660271, "position": "TWP"}})
    rows = [{"player": "Blake Snell"}, {"player": "Shohei Ohtani", "headshot_url": "kept", "pos": "DH"}, {"player": "Nobody"}]
    assert m.fill_mlb_identity(rows, "2026-10-14", tmp_path) == {"headshots": 1, "positions": 1}
    assert rows[0]["headshot_url"].endswith("/people/605483/headshot/67/current") and rows[0]["pos"] == "P"
    assert rows[1] == {"player": "Shohei Ohtani", "headshot_url": "kept", "pos": "DH"} and rows[2] == {"player": "Nobody"}
