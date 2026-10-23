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
    # A text price or an American 0 is no price: it neither crashes nor counts (lead probability-differential-sweep-1015).
    junk = cs.shop_gap({"fanduel": -120, "draftkings": -115, "betmgm": 105, "x": "", "y": 0, "z": True})
    assert junk == gap
    assert cs.shop_gap({"a": -110, "b": 0, "c": "n/a"}) is None


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
    assert m.season_phase("wnba", "2026-10-14") == "postseason"                             # the 2026 playoffs (was wrongly "offseason")
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


def _unset_data_root_until_teardown(monkeypatch):
    """Start the test with SYNDICATE_DATA_ROOT unset AND restore the original on teardown.

    `align_data_root` (reached through `main`) WRITES the variable. `monkeypatch.delenv(..., raising=False)` alone records
    nothing when the variable is absent, so that write outlived the test: every later test in the process read a deleted
    temp dir as its data root and 12 NCAAF tests lost their team registry in the daily ci-suite (todo #697, found by lane
    ci-suite-red-1015). `setenv` first is what makes monkeypatch remember the ORIGINAL state; `delenv` then unsets it."""
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", "set-by-test")
    monkeypatch.delenv("SYNDICATE_DATA_ROOT")


def test_the_day_ahead_is_tomorrow_in_central(monkeypatch):
    _unset_data_root_until_teardown(monkeypatch)
    m = _script()
    monkeypatch.setattr(m, "central_today", lambda: "2026-10-14")
    seen = {}
    monkeypatch.setattr(m, "fetch_rows", lambda base, sport, day=None: seen.setdefault("fetched_for", day) and [])
    monkeypatch.setattr(m, "latest_nfl_dvp", lambda root: {})
    real = m.build_sport

    def spy(sport, rows, *, selected_date, **kw):
        seen["date"] = selected_date
        return real(sport, rows, selected_date=selected_date, **kw)

    monkeypatch.setattr(m, "build_sport", spy)
    import tempfile
    with tempfile.TemporaryDirectory() as root:
        m.main(["--data-root", root, "--date", "tomorrow", "--sports", "nfl"])
    assert seen["date"] == "2026-10-15" and seen["fetched_for"] == "2026-10-15"   # the board's own day-ahead build


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
    assert rows[s["value"][1]]["line"] == 199.5                                          # the main Nix rung (the median)
    assert len(s["every_prop"]) == 7                                                     # the full table stays complete


def test_the_evidence_layer_reads_the_same_data_root_as_the_generator(monkeypatch, tmp_path):
    # A hand run without SYNDICATE_DATA_ROOT read the checkout's data/ mirror: sheets with no positions or matchups,
    # and no error (2026-10-15). Unset -> set from --data-root; a different root -> refused, never mixed.
    m = _script()
    _unset_data_root_until_teardown(monkeypatch)
    assert m.align_data_root(tmp_path) is None
    import os
    assert os.environ["SYNDICATE_DATA_ROOT"] == str(tmp_path)
    assert m.align_data_root(tmp_path) is None                                   # the same root again is fine
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path / "elsewhere"))
    assert "different root" in m.align_data_root(tmp_path)


def test_mlb_and_nhl_rows_get_faces_and_positions_from_the_days_rosters(monkeypatch, tmp_path):
    # 10-14: a face on 60 of 214 MLB rows and a position on none -- the board carries an id only on props the sim
    # projected, and a sheet rebuilt from quotes carries none. Only EMPTY fields are filled; the play cards read them.
    m = _script()
    from syndicate.features.mlb import batter_vs_pitcher as bvp
    from syndicate.features.nhl import skater_vs_goalie as svg
    monkeypatch.setattr(bvp, "player_ids", lambda api, date: {"blakesnell": {"id": 605483, "position": "P"},
                                                               "shoheiohtani": {"id": 660271, "position": "TWP"}})
    board = "https://img.mlbstatic.com/mlb-photos/image/upload/w_180,q_auto:best/v1/people/1/headshot/67/current"
    rows = [{"player": "Blake Snell"}, {"player": "Shohei Ohtani", "headshot_url": "kept", "pos": "DH"},
            {"player": "Nobody"}, {"player": "Mookie Betts", "headshot_url": board}]
    assert m.fill_identity("mlb", rows, "2026-10-14", tmp_path) == {"headshots": 1, "positions": 1}
    assert rows[0]["headshot_url"] == m.MLB_FACE.format(id=605483) and "/w_360," in rows[0]["headshot_url"] and rows[0]["pos"] == "P"
    assert rows[1] == {"player": "Shohei Ohtani", "headshot_url": "kept", "pos": "DH"} and rows[2] == {"player": "Nobody"}
    assert rows[3]["headshot_url"] == board.replace("/w_180,", "/w_360,")      # the board's 180 px is upscaled on a card
    # The board's own index gets a second look first (a kept row must see a lookup fix too); the roster fills the rest.
    from syndicate.features.shared import player_headshots as ph
    monkeypatch.setattr(ph, "headshot_url", lambda row: f"idx:{row['player_name']}" if row["player_name"] in ("Agustin Bouzat", "Cole Caufield") else None)
    monkeypatch.setattr(svg, "player_ids", lambda api, date: {   # the book's "Zack" is the roster's "Zachary"
        "zacharybolduc": {"id": 8482737, "name": "Zachary Bolduc", "position": "F"}})
    nhl = [{"player": "Zack Bolduc"}, {"player": "Cole Caufield"}]
    assert m.fill_identity("nhl", nhl, "2026-10-14", tmp_path) == {"headshots": 2, "positions": 1}
    assert nhl == [{"player": "Zack Bolduc", "headshot_url": "https://assets.nhle.com/mugs/nhl/latest/8482737.png", "pos": "F"},
                   {"player": "Cole Caufield", "headshot_url": "idx:Cole Caufield"}]
    soccer = [{"player": "Agustin Bouzat"}, {"player": "X"}]
    assert m.fill_identity("soccer", soccer, "2026-10-14", tmp_path) == {"headshots": 1, "positions": 0}
    assert soccer == [{"player": "Agustin Bouzat", "headshot_url": "idx:Agustin Bouzat"}, {"player": "X"}]


def test_a_nickname_matches_by_initial_and_last_name_only_when_unique(monkeypatch, tmp_path):
    m = _script()
    from syndicate.features.mlb import batter_vs_pitcher as bvp
    assert m._initial_last("Zack Bolduc") == m._initial_last("Zachary Bolduc") == "zbolduc"
    assert m._initial_last("Alejandro Alvarado Jr.") == "aalvarado" and m._initial_last("Pele") == ""
    monkeypatch.setattr(bvp, "player_ids", lambda api, date: {"willsmith": {"id": 1, "name": "Will Smith", "position": "C"},
                                                               "wilsonsmith": {"id": 2, "name": "Wilson Smith", "position": "P"}})
    rows = [{"player": "Willie Smith"}]                       # "wsmith" names two players: never guessed
    assert m.fill_identity("mlb", rows, "2026-10-14", tmp_path) == {"headshots": 0, "positions": 0} and rows == [{"player": "Willie Smith"}]


def test_the_old_streak_note_is_reworded_on_published_rows_and_nothing_else_moves():
    # User 2026-10-15: "update the old reason text on past sheets too". New sheets and old ones read the same.
    rows = [{"check": {"verdict": "streak_with_room", "price": -150, "ev_market": -4.0,
                       "reasons": ["4/5 on this line and the price still leaves +3.0%", "model 61% vs market 58% (above)"]}},
            {"check": {"verdict": "value", "reasons": ["best price beats the fair by +2.4%"]}},
            {"check": {"verdict": "neutral"}}]
    assert cs.reword_streak_reasons(rows) == 1
    assert rows[0]["check"]["reasons"] == [cs.streak_room_reason("4", "5", 3.0), "model 61% vs market 58% (above)"]
    assert rows[0]["check"]["reasons"][0] == "4/5 on this line; form alone says +3.0% vs the price, but streaks like this have run below the fair price"
    assert rows[0]["check"]["price"] == -150 and rows[1]["check"]["reasons"] == ["best price beats the fair by +2.4%"]
    assert cs.reword_streak_reasons(rows) == 0                                    # a second pass changes nothing


def _card(pick_id, *, sport="mlb", event="e7", market="h2h", side="away", line=None, segment="full", books=5,
          suggested=True, state="pregame", day="2026-10-15", score=1.0, player=None, lane="opportunity"):
    return {"pick_id": pick_id, "kind": "prop" if player else "game", "sport": sport, "event_id": event, "market": market,
            "side": side, "line": line, "segment": segment, "suggested": suggested, "market_state": state, "game_date": day,
            "board_score": score, "board_lane": lane, "player_name": player, "display_name": player or "Milwaukee Brewers",
            "matchup": "Milwaukee Brewers @ Los Angeles Dodgers", "home_team": "Los Angeles Dodgers", "away_team": "Milwaukee Brewers",
            "odds": 138, "quote": {"bookmaker": "betrivers", "books_quoting": books, "fair_probability": 0.437},
            "fair_price": 129, "ev_pct": 3.9, "model_probability": 0.51, "detail": "Our sim has it.", "commence_time": "2026-10-16T00:00:00Z"}


def test_picks_are_the_boards_suggested_main_line_pregame_opps_for_the_day():
    # User 2026-10-15: "there are 7 suggested opps on the main layer2 board these need to translate ... as picks to
    # promote". The board's own rules: suggested, pregame, the opportunity lane, MAIN lines only (`isAltLine`).
    cards = [
        _card("l2_main", market="totals", side="over", line=8.5, books=9, score=3.0),
        _card("l2_alt", market="totals", side="over", line=7.5, books=4, score=5.0),     # not the group's most-quoted line
        _card("l2_altmkt", market="totals_alt", side="over", line=5.5, score=4.0),        # an explicit alt market
        _card("l2_seg", market="h2h", segment="first3", score=2.0),                       # a segment pick stays
        _card("l2_live", state="live", score=9.0), _card("l2_tomorrow", day="2026-10-16", score=9.0),
        _card("l2_plain", suggested=False, score=9.0), _card("l2_other", sport="nhl", score=9.0),
        _card("l2_watch", lane="watchlist", score=9.0),
        _card("l2_unsug", market="totals", side="over", line=9.5, books=2, suggested=False),
    ]
    assert [c["pick_id"] for c in cs.select_picks(cards, sport="mlb", day="2026-10-15")] == ["l2_main", "l2_seg"]
    assert cs.is_alt_line(cards[1], cs.alt_primaries(cards)) and not cs.is_alt_line(cards[0], cs.alt_primaries(cards))


def test_a_pick_reads_like_the_board_and_keeps_its_first_price_on_the_record():
    m = _script()
    from datetime import datetime, timezone
    now = datetime(2026, 10, 15, 14, 0, tzinfo=timezone.utc)
    sheet = {"rows": [{"player": "Griffin Jax", "market": "strikeouts", "side": "over", "line": 3.5, "team": "TB", "pos": "P",
                       "team_logo": "tb.svg", "headshot_url": "row.png"}]}
    cards = [_card("l2_seg", segment="first3", score=2.0) | {"segment_label": "1st 3 innings"},
             _card("l2_jax", player="Griffin Jax", market="strikeouts", side="over", line=3.5, score=1.0)
             | {"headshot_url": "https://img.mlbstatic.com/mlb-photos/image/upload/w_180,q_auto:best/v1/people/643377/headshot/67/current"}]
    picks = m.build_picks(cards, sheet, sport="mlb", day="2026-10-15", now=now)
    assert [p["bet"] for p in picks] == ["Milwaukee Brewers moneyline · 1st 3 innings", "Over 3.5 strikeouts"]
    assert picks[0]["price"] == 138 and picks[0]["book"] == "betrivers" and picks[0]["p_market"] == 0.437
    assert picks[1]["team"] == "TB" and picks[1]["pos"] == "P" and "/w_360," in picks[1]["headshot_url"]
    later = [dict(picks[0], price=150, promoted_at="later")]                        # the board's price moved
    merged = m.merge_picks(later, {"picks": picks})
    assert [p["pick_id"] for p in merged] == ["l2_seg", "l2_jax"] and merged[0]["price"] == 138   # first price kept; Jax stays
    assert merged[0]["on_board"] is True and merged[1]["on_board"] is False                  # Jax is no longer suggested
    assert cs.pick_result_key(picks[0]).endswith("|first3") and cs.pick_result_key(picks[1]).startswith("p:")


def test_one_line_per_player_and_stat_across_every_featured_section():
    # User 2026-10-15: "reduce some of duplicate player/lines across the sheets. players with o4.5 and o5.5 lines and
    # pick one". Measured that day: Rodriguez u30.5 in Hot streaks and u32.5 in Streaks with room; Humphrey over 6.5
    # in Hot streaks and under 6.5 in Matchups. One rung per player + stat everywhere: the MAIN line (most books, the
    # board's rule), then the side whose price beats its fair by more -- never the best-EV rung across the ladder.
    def row(player, side, line, verdict, ev, market="Receiving Yards", books=5, **extra):
        f = {"games": 10, "hits": 9, "rate": 0.9}
        return {"player": player, "market": market, "side": side, "line": line, "books_quoting": books,
                "check": {"verdict": verdict, "ev_market": ev, "ev_posterior": 1.0, "price": -110, "form5": f, "form10": f}} | extra

    rows = [row("Rodriguez", "under", 30.5, "streak_with_room", 1.0, books=9),
            row("Rodriguez", "under", 32.5, "streak_with_room", 2.5, books=4),          # better EV, but an alt rung
            row("Humphrey", "over", 6.5, "streak_with_room", -1.0),
            row("Humphrey", "under", 6.5, "neutral", 0.5, matchup={"nth_most": 31, "of": 32}),
            row("Kupp", "under", 2.5, "value", 3.0, market="Receptions"),
            row("Kupp", "under", 2.5, "value", 4.0, market="Receptions_alternate")]
    s = cs.sections(rows)
    featured = [i for key, ids in s.items() if key != "every_prop" for i in ids]
    by_stat = {}
    for i in featured:
        by_stat.setdefault(cs._stat_key(rows[i]), set()).add(i)
    assert all(len(ids) == 1 for ids in by_stat.values())                       # one rung per player + stat, sheet-wide
    assert set(featured) == {0, 3, 5}                       # Rodriguez's main line; Humphrey's better side; one Kupp
    assert 0 in s["hot_streaks"] and 1 not in s["hot_streaks"] and 2 not in s["hot_streaks"]
    assert 3 in s["matchup_spots"] and len(s["every_prop"]) == 6                 # every prop stays complete


def test_a_picks_case_is_whole_statements_with_recency_vs_opponent_and_player_matchups():
    # User 2026-10-15: "bullets that end with ... instead of full explanations. We also need to feature relevant player
    # vs opponent stats" + "and recency/consistency". Nothing is cut; a record AGAINST the side is flagged, never ticked.
    detail = ("Our sim has Emmitt Finnie over 1.5 sog at 41.2%; the no-vig market says 54.2%. "
              "Recent form: over 1.5 in 5 of the last 10 (avg 1.5). "
              "Matchup: over 1.5 in 0 of 3 vs PHI; PHI allows 3.33 xG/60 (blended with this season); this season 3.94 xG a game, "
              "32 of 32 (1 = stingiest), 8 GP. "
              "Vs position: PHI allows 24.8 shots on goal a game to forwards (rank 32 of 32, 1 = fewest; 8 games this season). "
              "It projects an average of 1.4 against the 1.5 line.")
    pick = {"kind": "prop", "player_name": "Emmitt Finnie", "display_name": "Emmitt Finnie", "market": "SOG", "side": "over",
            "line": 1.5, "detail": detail, "recent_values": [4.0, 2.0, 2.0, 2.0, 2.0, 1.0, 1.0, 1.0, 0.0, 0.0],
            "recent_opponents": ["NJD", "MTL", "SEA", "OTT", "WPG", "NYR", "CBJ", "BUF", "PIT", "FLA"]}
    rows = [{"player": "Emmitt Finnie", "market": "SOG", "side": "over", "line": 2.5, "opponent": "PHI",
             "pvp": {"kind": "skater_vs_goalie", "opponent": "D. Vladar (likely starter)", "line": {"games": 2, "sog": 1, "goals": 0},
                     "summary": "0 G on 1 SOG in 2 games vs D. Vladar"}}]
    pts = cs.pick_points(pick, rows=rows)
    assert pts == [
        {"label": "Last 5", "text": "over 1.5 in 5 of 5 (newest first: 4 v NJD, 2 v MTL, 2 v SEA, 2 v OTT, 2 v WPG)", "tone": "for"},
        {"label": "Last 10", "text": "over 1.5 in 5 of 10, averaging 1.5 (low 0, high 4)", "tone": ""},
        {"label": "Vs PHI", "text": "over 1.5 in 0 of 3 meetings", "tone": "against"},
        {"label": "Vs goalie", "text": "0 G on 1 SOG in 2 games vs D. Vladar (likely starter)", "tone": ""},
        {"label": "Opponent", "text": "PHI allows 3.33 xG/60; this season 3.94 xG a game, the most generous of 32 (8 games)", "tone": "for"},
        {"label": "Vs position", "text": "PHI allows 24.8 shots on goal a game to forwards, the most of 32 (8 games this season)",
         "tone": "for"}]
    long = cs.ask_points("Recent form: " + "x " * 200)
    assert long[0]["text"].endswith("x") and len(long[0]["text"]) > 300 and "…" not in long[0]["text"]   # never cut
    # No case on the board, no kept games: the sheet row's last games are re-read at the pick's own rung.
    bare = {"kind": "prop", "player_name": "A", "market": "Receptions", "side": "over", "line": 4.5}
    row = {"player": "A", "market": "Receptions", "side": "over", "line": 3.5, "check": {"form10": {"values": [5, 6, 4, 7, 5]}},
           "vs_opponent": {"games": 3, "hits": 3, "same_line": True, "results": [{"value": 6}, {"value": 4}, {"value": 5}]},
           "opponent": "ARI"}
    assert cs.pick_points(bare, rows=[row]) == [
        {"label": "Last 5", "text": "over 4.5 in 4 of 5 (newest first: 5, 6, 4, 7, 5)", "tone": "for"},
        {"label": "Vs ARI", "text": "over 4.5 in 2 of 3 meetings (latest 6, 4, 5)", "tone": "for"}]


def test_a_game_picks_case_reads_its_teams_recent_games_and_starters():
    recent = {"away": [["2026-10-10", 24, 27], ["2026-10-03", 31, 24], ["2026-09-26", 28, 42], ["2026-09-19", 27, 31]],
              "home": [["2026-10-10", 10, 3], ["2026-10-03", 10, 42], ["2026-09-26", 20, 46], ["2026-09-19", 17, 20]]}
    total = {"kind": "game", "market": "totals", "side": "over", "line": 47.5, "segment": "full", "home_team": "ODU",
             "away_team": "GASO", "team_recent": recent, "detail": ""}
    assert cs.pick_points(total) == [
        {"label": "GASO", "text": "its games went over 47.5 in 4 of the last 4, averaging 58.5 points", "tone": "for"},
        {"label": "ODU", "text": "its games went over 47.5 in 2 of the last 4, averaging 42.0 points", "tone": ""}]
    spread = dict(total, market="spreads", side="home", line=-5.5, display_name="ODU")
    assert cs.pick_points(spread)[0] == {"label": "ODU", "text": "1-3 in its last 4, average margin -13.5; would have covered -5.5 in 1 of 4",
                                         "tone": "against"}
    assert cs.pick_points(dict(spread, segment="first3")) == []                 # full-game scores say nothing of an inning
    starter = {"player": "Tyler Glasnow", "event_id": "e7", "pvp": {"kind": "pitcher_vs_lineup", "opponent": "Milwaukee Brewers",
               "line": {"plateAppearances": 76}, "summary": "Milwaukee Brewers hitters 9-for-72, 1 HR, 41% K (76 PA, 10 hitters)"}}
    ml = {"kind": "game", "event_id": "e7", "market": "h2h", "side": "away", "segment": "first3", "detail": ""}
    assert cs.pick_points(ml, rows=[starter, dict(starter, market="outs")]) == [
        {"label": "Tyler Glasnow", "text": "Milwaukee Brewers hitters 9-for-72, 1 HR, 41% K (76 PA, 10 hitters)", "tone": ""}]
    nba = cs.ask_points("Season metrics: Net rating Toronto Raptors +1.6 (11th of 30) vs New York Knicks +4.0 (5th of 30).")
    assert nba[0]["text"] == "Net rating Toronto Raptors +1.6 (11th of 30) vs New York Knicks +4.0 (5th of 30)"


def test_a_kept_pick_rereads_its_case_and_its_recent_games_from_the_board():
    m = _script()
    from datetime import datetime, timezone
    now = datetime(2026, 10, 15, 14, 0, tzinfo=timezone.utc)
    card = _card("l2_jax", player="Griffin Jax", market="strikeouts", side="over", line=3.5) | {"recent_values": [5, 4, 6]}
    picks = m.build_picks([card], {"rows": []}, sport="mlb", day="2026-10-15", now=now)
    assert picks[0]["recent_values"] == [5, 4, 6] and picks[0]["points"][0]["label"] == "Last 5"
    stale = dict(picks[0], recent_values=None, points=[])
    still_on_board = dict(card, suggested=False, recent_values=[2, 2, 2, 2, 2])     # dropped from Suggested, still listed
    merged = m.merge_picks([], {"picks": [stale]}, rows=[], cards=[still_on_board])
    assert merged[0]["on_board"] is False and merged[0]["recent_values"] == [2, 2, 2, 2, 2]
    assert merged[0]["points"][0] == {"label": "Last 5", "text": "over 3.5 in 0 of 5 (newest first: 2, 2, 2, 2, 2)", "tone": "against"}


def test_a_segment_pick_reads_its_own_intervals_and_is_toned_against_its_market():
    # User 2026-10-15: "we should fix the gaps - for example we need the interval data". A 1st-3-innings moneyline reads
    # 1st-3-innings scores, never full-game finals; a 3-way 1st inning is a ~25% bet, so its record is judged on that.
    recent = {"away": [["2026-10-13", 1, 2], ["2026-10-12", 1, 1], ["2026-10-11", 2, 0], ["2026-10-10", 0, 0], ["2026-10-09", 3, 1],
                       ["2026-10-08", 2, 1]],
              "home": [["2026-10-13", 2, 1], ["2026-10-12", 1, 1], ["2026-10-11", 0, 0], ["2026-10-10", 0, 1], ["2026-10-09", 1, 1]]}
    pick = {"kind": "game", "sport": "mlb", "market": "h2h", "side": "away", "segment": "first3", "segment_label": "1st 3 innings",
            "home_team": "Los Angeles Dodgers", "away_team": "Milwaukee Brewers", "p_market": 0.44, "detail": "",
            "team_recent": recent, "team_recent_segment": "first3"}
    assert cs.pick_points(pick)[0] == {"label": "Milwaukee Brewers", "tone": "for",            # 3 of 4 decided vs 44%
                                       "text": "1st 3 innings: won 3, tied 2, lost 1 of its last 6, average margin +0.7"}
    assert cs.pick_points(dict(pick, team_recent_segment="full")) == []                          # never a full-game final
    three_way = dict(pick, market="h2h_3_way", segment="first1", segment_label="1st inning", team_recent_segment="first1",
                     p_market=0.24, team_recent={"away": [["d", 0, 0]] * 7 + [["d", 0, 1]] * 3, "home": []})
    assert cs.pick_points(three_way)[0]["tone"] == "against"                                    # 0 of 10 vs a 24% bet
    total = dict(pick, market="totals", side="over", line=2.5, p_market=0.5)
    assert cs.pick_points(total)[0]["text"] == "its 1st 3 innings went over 2.5 in 3 of the last 6, averaging 2.3 runs"


def test_a_picks_history_is_filled_from_the_boards_own_providers(monkeypatch):
    m = _script()
    from syndicate.features import intelligence_recent_matchup as irm
    from syndicate.features.shared import team_recent_results as trr

    asked = []
    monkeypatch.setattr(irm, "prop_recent_matchup_text", lambda row, selected_date: asked.append(dict(row)))
    monkeypatch.setattr(irm, "recent_values_for", lambda row: {"values": [5, 4, 6], "dates": ["2026-10-10", "2026-10-04", "2026-09-28"]})
    jax = {"kind": "prop", "sport": "mlb", "player_name": "Griffin Jax", "market": "strikeouts", "side": "over", "line": 3.5,
           "headshot_url": "https://img.mlbstatic.com/mlb-photos/image/upload/w_360,q_auto:best/v1/people/643377/headshot/67/current"}
    assert m.fill_pick_history(jax, day="2026-10-15", intervals=None) == "prop_recent"
    assert asked[0]["market"] == "pitcher_strikeouts" and asked[0]["player_id"] == "643377"     # the provider's names
    assert jax["recent_values"] == [5, 4, 6] and jax["recent_dates"][0] == "2026-10-10"

    monkeypatch.setattr(trr, "team_recent_results", lambda sport, team, before, n=10, *, segment="full": [["2026-10-10", 31.0, 24.0]])
    full = {"kind": "game", "sport": "ncaaf", "market": "spreads", "segment": "full", "home_team": "A", "away_team": "B"}
    assert m.fill_pick_history(full, day="2026-10-15", intervals=None) == "team_full" and full["team_recent_segment"] == "full"

    class Intervals:
        def team_results(self, sport, team, before, segment):
            return [["2026-10-13", 1.0, 2.0]] if team == "Milwaukee Brewers" else []

    seg = {"kind": "game", "sport": "mlb", "market": "h2h", "segment": "first3", "home_team": "Los Angeles Dodgers",
           "away_team": "Milwaukee Brewers"}
    assert m.fill_pick_history(seg, day="2026-10-15", intervals=Intervals()) == "team_first3"
    assert seg["team_recent"] == {"home": [], "away": [["2026-10-13", 1.0, 2.0]]} and seg["team_recent_segment"] == "first3"
    assert m.fill_pick_history(dict(seg, team_recent=None), day="2026-10-15", intervals=None) is None   # no source: a gap


def test_mlb_rows_read_their_form_from_the_boards_own_provider(monkeypatch):
    # User 2026-10-15: "look into any sports (like MLB) where consistency sections are missing". The evidence layer has
    # no MLB provider, so every MLB row had no form (0 of 140 that day) and Consistency / Hot streaks were always empty.
    m = _script()
    from syndicate.features import intelligence_recent_matchup as irm

    monkeypatch.setattr(m, "evidence_facts", lambda row, selected_date: {"error": "no evidence provider"})
    monkeypatch.setattr(irm, "prop_recent_matchup_text", lambda row, selected_date: None)
    monkeypatch.setattr(irm, "recent_values_for", lambda row: {"values": [2, 1, 3, 2, 2, 1, 2, 3, 2, 2],
                                                               "dates": [f"2026-10-{d:02d}" for d in range(14, 4, -1)]})
    base = {"kind": "prop", "game_state": "pregame", "segment": "full", "event_id": "e1", "home_team": "Los Angeles Dodgers",
            "away_team": "Milwaukee Brewers", "market": "batter_total_bases", "player_name": "Shohei Ohtani",
            "commence_time": "2026-10-15T00:15:00Z", "projection": {"player_id": "660271"}}
    rows = [dict(base, line=1.5, side="over", quote={"price": -110, "fair_probability": 0.5, "book_prices": {"fd": -110, "dk": -115}})]
    sheet = m.build_sport("mlb", rows, selected_date="2026-10-14", cap=10, dvp={})
    check = sheet["rows"][0]["check"]
    assert check["form10"]["games"] == 10 and check["form10"]["hits"] == 8 and sheet["rows"][0]["form_labels"][0] == "2026-10-14"
    assert sheet["sections"]["consistency"] == [0]                               # 8 of 10: it now has a section
    monkeypatch.setattr(irm, "recent_values_for", lambda row: None)
    assert m.board_recent_form(dict(base), "2026-10-14") == {}                    # no provider games: a blank, not a guess


def test_the_boards_narrative_never_makes_the_model_a_reason_or_repeats_recent_form():
    # 2026-10-15, the Jax outs pick: the board's narrative carried "The model baseline sits around 15.4 outs" (the model
    # as a reason) and "Across his last 5 starts, he has averaged 12.4 outs" (the Last 5 point said again).
    detail = ("Our sim has Griffin Jax over 11.5 outs at 82.6%; the no-vig market across 8 books says 54.4%. "
              "Across his last 5 starts, he has averaged 12.4 outs. "
              "The model baseline sits around 15.4 outs against a line of 11.5. "
              "If he stays on his normal starter path, the matchup against CLE gives him a fair shot to reach full workload volume.")
    pts = cs.ask_points(detail, subject="Griffin Jax", side="over")
    assert [p["label"] for p in pts] == ["Recent form", ""] and not any("model" in p["text"].lower() for p in pts)
    pick = {"kind": "prop", "player_name": "Griffin Jax", "market": "outs", "side": "over", "line": 11.5, "detail": detail,
            "recent_values": [9, 15, 15, 15, 8]}
    assert [p["label"] for p in cs.pick_points(pick)] == ["Last 5", ""]           # its own record replaces the narrative


def test_a_price_edge_the_sim_backs_is_a_syndicate_pick_and_one_it_does_not_is_a_price_play():
    # User 2026-10-15: "if i tout our sim and we show something like this it dvalues our work" -- the GASO@ODU over at
    # +109 was a Syndicate pick beside "SmartSim 12%". The board's sim_view decides; past its 15-point cap the sim has
    # no priced view, and its probability against the market decides (Jax over 3.5 K: 75% vs 50% IS backed).
    assert cs.pick_label({"sim_view": "agrees", "p_model": 0.51, "p_market": 0.44}) == "SYNDICATE PICK"
    assert cs.pick_label({"sim_view": "contradicts", "p_model": 0.12, "p_market": 0.50}) == "PRICE PLAY"
    assert cs.pick_label({"sim_view": "neutral", "p_model": 0.24, "p_market": 0.24}) == "PRICE PLAY"
    assert cs.pick_label({"sim_view": "unpriced", "p_model": 0.75, "p_market": 0.50}) == "SYNDICATE PICK"
    assert cs.pick_label({"sim_view": None, "p_model": None, "p_market": 0.50}) == "PRICE PLAY"   # no sim: never touted
    # BACKING IS A MARGIN (user 2026-10-15, "1-point floor"): NBA totals from 10-20 serve a 5%-weight sim ~0.2 pts off
    # the market, which the board reads `agrees`. That is the market's view, not the sim's.
    assert cs.pick_label({"sim_view": "agrees", "p_model": 0.5413, "p_market": 0.5392}) == "PRICE PLAY"
    assert cs.pick_label({"sim_view": "agrees", "p_model": 0.55, "p_market": 0.54}) == "SYNDICATE PICK"   # exactly 1 pt
    assert cs.pick_label({"sim_view": "agrees", "p_model": None, "p_market": 0.54}) == "PRICE PLAY"      # margin unknown
    assert cs.pick_label({"sim_view": "unpriced", "p_model": 0.505, "p_market": 0.50}) == "PRICE PLAY"
    # PRICE PLAY UNTIL GRADED (user 2026-10-15): the NHL puckline sim went live 10-15 and is ungraded -- Calgary +1.5
    # (sim 56.6 vs 51.1) stays a price play; the same margin on an NHL moneyline is a pick.
    assert cs.pick_label({"sport": "nhl", "market": "spreads", "sim_view": "agrees", "p_model": 0.566, "p_market": 0.511}) == "PRICE PLAY"
    assert cs.pick_label({"sport": "nhl", "market": "alternate_spreads", "sim_view": "agrees", "p_model": 0.6, "p_market": 0.5}) == "PRICE PLAY"
    assert cs.pick_label({"sport": "nhl", "market": "h2h", "sim_view": "agrees", "p_model": 0.566, "p_market": 0.511}) == "SYNDICATE PICK"
    assert cs.price_case({"books": 24, "p_market": 0.5, "fair_price": 100, "book": "prophetx", "price": 109}) ==         "The edge is the price: 24 books put it at 50% (fair +100); ProphetX pays +109"
    m = _script()
    pick = lambda pid, view, score: {"pick_id": pid, "kind": "game", "market": "totals", "sim_view": view, "board_score": score,
                                     "p_model": 0.12 if view == "contradicts" else 0.6, "p_market": 0.5, "book": "prophetx"}
    merged = m.merge_picks([pick("a", "contradicts", 9.0), pick("b", "agrees", 1.0)], None)
    assert [(p["pick_id"], p["label"], p["book_name"]) for p in merged] == [("b", "SYNDICATE PICK", "ProphetX"),
                                                                        ("a", "PRICE PLAY", "ProphetX")]   # picks first


def test_a_collapsed_board_read_is_re_read_not_built():
    # 2026-10-15: the NFL sheet went 157 -> 28 rows on the 12:30 PM CT build (20 of ~64 groups, read mid board build).
    m = _script()
    from datetime import datetime, timezone
    now = datetime(2026, 10, 15, 17, 30, tzinfo=timezone.utc)
    row = lambda i: {"kind": "prop", "event_id": "e1", "player_name": f"P{i}", "market": "Receptions",
                     "commence_time": "2026-10-16T00:15:00Z", "segment": "full"}
    prior = {"rows": [{"event_id": "e1", "player": f"P{i}", "market": "Receptions", "commence_time": "2026-10-16T00:15:00Z"}
                      for i in range(60)]}
    full, thin = [row(i) for i in range(64)], [row(i) for i in range(20)]
    reads, waits = iter([full]), []
    got = m.steady_rows(lambda: next(reads), thin, prior, "2026-10-15", now=now, sleep=waits.append)
    assert got is full and waits == [50.0]                                   # re-read once, kept the full read
    assert m.steady_rows(lambda: 1 / 0, full, prior, "2026-10-15", now=now, sleep=waits.append) is full and waits == [50.0]
    started = {"rows": [dict(r, commence_time="2026-10-15T17:00:00Z") for r in prior["rows"]]}   # a started game: no baseline
    assert m.steady_rows(lambda: 1 / 0, thin, started, "2026-10-15", now=now, sleep=waits.append) is thin


def test_recent_form_says_where_once():
    # NFL labels carry their own "vs" / "@" (the George Holani pick read "4 v vs SF, 5 v @WAS", 2026-10-15).
    nfl = cs.recent_points([4, 1, 5], line=1.5, side="under", opponents=["vs SF", "vs LAC", "@WAS"])
    assert nfl[0]["text"] == "under 1.5 in 1 of 3 (newest first: 4 vs SF, 1 vs LAC, 5 @WAS)"
    nhl = cs.recent_points([4, 2, 2], line=1.5, side="over", opponents=["NJD", "MTL", "SEA"])
    assert nhl[0]["text"] == "over 1.5 in 3 of 3 (newest first: 4 v NJD, 2 v MTL, 2 v SEA)"


def test_the_wnba_2026_postseason_gets_a_full_sheet():
    # 2026-10-17: the WNBA table held only 2027 windows, so a playoff day built a picks-only sheet.
    m = _script()
    assert m.season_phase("wnba", "2026-10-17") == "postseason" and m.in_season("wnba", "2026-10-31")
    assert m.season_phase("wnba", "2026-11-15") is None and m.season_phase("wnba", "2027-06-01") == "regular"



def test_a_preview_build_reads_the_boards_build_for_its_own_day(monkeypatch):
    # 2026-10-19: the 2 PM preview of the NBA opener read TODAY's board (no NBA games today) and got 0 groups.
    m = _script()
    seen = []

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"rows": []}'

    monkeypatch.setattr(m.urllib.request, "urlopen", lambda url, timeout=0: seen.append(url) or _Resp())
    monkeypatch.setattr(m.json, "load", lambda resp: {"rows": []})
    monkeypatch.setattr(m, "central_today", lambda: "2026-10-19")
    m.fetch_rows("http://x", "nba", "2026-10-20")
    m.fetch_rows("http://x", "nba", "2026-10-19")
    m.fetch_rows("http://x", "nba")
    assert seen[0].endswith("&date=2026-10-20") and "date=" not in seen[1] and "date=" not in seen[2]


def _nhl_board(ev_by_player):
    """One SOG group per player, main line 2.5 both sides, the over carrying the player's EV (the build's priority)."""
    rows = []
    for player, ev in ev_by_player.items():
        for side in ("over", "under"):
            rows.append({"kind": "prop", "game_state": "pregame", "segment": "full", "event_id": "g1",
                         "home_team": "OTT", "away_team": "BUF", "market": "SOG", "player_name": player,
                         "commence_time": "2026-10-21T23:00:00Z", "line": 2.5, "side": side,
                         "ev_pct": ev if side == "over" else -5.0,
                         "quote": {"price": -110, "fair_probability": 0.5, "book_prices": {"fd": -110, "dk": -112}}})
    return rows


def test_a_group_built_earlier_today_stays_on_the_sheet_and_a_preview_does_not_hold_one(monkeypatch):
    # User 2026-10-23: NHL consistency went 8 -> 17 -> 12 on 10-21 because each build re-picked its top 30 groups by
    # EV, and 6 of the 8 posted rows fell out of the final build. A group a build TODAY chose is kept; the cap still
    # decides what joins.
    m = _script()
    monkeypatch.setattr(m, "evidence_facts", lambda row, selected_date: {"recent_form": {"values": [3, 3, 1, 2, 4]}})
    day = "2026-10-21"
    first = m.build_sport("nhl", _nhl_board({"Batherson": 6.0, "Stutzle": 1.0}), selected_date=day, cap=1, dvp={})
    assert {r["player"] for r in first["rows"]} == {"Batherson"}
    pool = m.pool_record(first, None, today=day, at="2026-10-21T13:30:00Z")
    assert pool["g1|Batherson|SOG"]["built_on"] == day and pool["g1|Batherson|SOG"]["first_rank"] == 1

    moved = _nhl_board({"Batherson": 1.0, "Stutzle": 6.0})                 # prices moved: Stutzle ranks first now
    kept = m.build_sport("nhl", moved, selected_date=day, cap=1, dvp={}, sticky=m.sticky_groups({"pool": pool}, day))
    by_player = {r["player"]: r["pool"] for r in kept["rows"]}
    assert set(by_player) == {"Batherson", "Stutzle"} and kept["groups_sticky"] == 1
    assert by_player["Stutzle"] == {"rank": 1, "of": 2, "cap": 1, "sticky": False}
    assert by_player["Batherson"] == {"rank": 2, "of": 2, "cap": 1, "sticky": True}
    again = m.pool_record(kept, {"pool": pool}, today=day, at="2026-10-21T17:30:00Z")
    assert again["g1|Batherson|SOG"]["first_rank"] == 1 and again["g1|Batherson|SOG"]["rank"] == 2

    # Reachability: the day-ahead preview (built 10-20 for 10-21) holds nothing on 10-21 -- and no stickiness at all
    # gives the old reshuffle.
    preview = m.pool_record(first, None, today="2026-10-20", at="2026-10-20T19:00:00Z")
    assert m.sticky_groups({"pool": preview}, day) == set()
    plain = m.build_sport("nhl", moved, selected_date=day, cap=1, dvp={})
    assert {r["player"] for r in plain["rows"]} == {"Stutzle"} and plain["groups_sticky"] == 0


def test_the_line_and_side_the_days_first_build_showed_stay_put_when_prices_move():
    # NHL 10-16, Karlsson: the 12:34 PM consistency graphic showed SOG under 2.5 (7 of his last 10); by 8:27 PM the
    # over's price beat its fair by more, the sheet showed the over (3/10) and he left the section.
    m = _script()

    def row(side, ev, rate, line=2.5):
        f = {"games": 10, "hits": int(rate * 10), "rate": rate}
        return {"event_id": "g1", "player": "Erik Karlsson", "market": "SOG", "line": line, "side": side,
                "books_quoting": 5, "check": {"verdict": "neutral", "ev_market": ev, "price": -110, "form5": f, "form10": f}}

    day = "2026-10-16"
    morning = [row("under", 3.0, 0.7), row("over", 1.0, 0.3)]
    lock = m.lock_primaries(morning, None, selected=day, today=day, at="2026-10-16T13:30:00Z")
    assert lock["Erik Karlsson|sog"] == {"line": 2.5, "side": "under", "built_on": day, "at": "2026-10-16T13:30:00Z"}
    assert [r.get("primary_locked") for r in morning] == [True, None]

    evening = [row("under", 1.0, 0.7), row("over", 3.0, 0.3)]               # the prices flipped
    held = m.lock_primaries(evening, lock, selected=day, today=day, at="2026-10-17T01:27:00Z")
    assert held == lock and cs.primary_lines(evening) == {0}
    assert cs.sections(evening)["consistency"] == [0]                         # still in the section, still the under

    # Reachability: without the lock the evening build shows the over, and the under leaves the section.
    unlocked = [row("under", 1.0, 0.7), row("over", 3.0, 0.3)]
    assert cs.primary_lines(unlocked) == {1} and cs.sections(unlocked)["consistency"] == []

    # The books pulled the locked line: the usual rule picks again, and the lock waits in case it returns.
    pulled = [row("under", 1.0, 0.6, line=3.5), row("over", 3.0, 0.4, line=3.5)]
    assert m.lock_primaries(pulled, lock, selected=day, today=day, at="2026-10-17T01:27:00Z") == lock
    assert cs.primary_lines(pulled) == {1} and not any(r.get("primary_locked") for r in pulled)

    # A day-ahead preview locks nothing, and a preview's lock is not honoured on the day.
    preview = [row("under", 3.0, 0.7), row("over", 1.0, 0.3)]
    assert m.lock_primaries(preview, None, selected=day, today="2026-10-15", at="2026-10-15T19:00:00Z") == {}
    stale = {"Erik Karlsson|sog": dict(lock["Erik Karlsson|sog"], built_on="2026-10-15")}
    fresh = m.lock_primaries(evening, stale, selected=day, today=day, at="2026-10-16T13:30:00Z")
    assert fresh["Erik Karlsson|sog"]["side"] == "over"                       # re-chosen by the day's own first build
