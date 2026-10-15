"""Play cards: only rows whose price check passes become cards; the model and form are context or risk, never the reason."""
from __future__ import annotations

import importlib.util
from pathlib import Path

from syndicate.features.shared import cheat_sheets as cs
from syndicate.features.shared import play_cards as pc


def _row(player="A", ev=3.0, verdict="value", books=4, suggested=False, fair_method="consensus_no_vig", **extra):
    row = {"player": player, "event_id": "e1", "market": "Receptions", "line": 2.5, "side": "under",
           "books_quoting": books, "suggested": suggested, "fair_method": fair_method, "team": "ATL", "pos": "RB",
           "check": {"verdict": verdict, "ev_market": ev, "price": -139, "book": "betonlineag", "p_market": 0.6018,
                     "p_model": 0.5456, "form10": {"games": 10, "hits": 9, "rate": 0.9, "values": [2, 2, 2, 4, 2, 2, 1, 0, 1, 0]},
                     "reasons": ["model loses to the book in this market (measured, +10.1% worse)"]}}
    row.update(extra)
    return row


def test_odds_helpers():
    assert pc.american_from_prob(0.6018) == -151 and pc.american_from_prob(0.25) == 300
    assert pc.american_from_prob(0.5) == -100 and pc.american_from_prob(None) is None
    assert pc.fmt_american(114) == "+114" and pc.fmt_american(-139) == "-139" and pc.fmt_american(None) == "-"


def test_only_price_checked_rows_become_cards():
    assert pc.eligible(_row())
    assert not pc.eligible(_row(ev=12.0))                                  # implausible: stale or mis-paired quote
    assert not pc.eligible(_row(books=2))                                  # fair rests on too few books
    assert pc.eligible(_row(books=2, suggested=True))                       # the board's full Suggested rule passed
    assert not pc.eligible(_row(fair_method="book_margin_model", suggested=True))   # one-sided: assumed-hold fair
    assert not pc.eligible(_row(verdict="one_sided_fair"))
    assert not pc.eligible(_row(verdict="streak_with_room", ev=-1.0))       # a streak alone is never a card


def test_select_is_best_ev_first_one_card_per_player_capped():
    sheet = {"sport": "nfl", "date": "2026-10-14", "rows": [_row("A", ev=2.5), _row("B", ev=4.0), _row("A", ev=3.5),
                                                               _row("C", ev=3.0), _row("D", ev=2.2)]}
    assert [r["player"] for r in pc.select(sheet, per_sport=3)] == ["B", "A", "C"]


def test_why_and_risk_put_the_model_in_the_risk_box_and_thin_books_first():
    why, risk = pc.why_and_risk(_row(books=2, suggested=True), {"script": {"read": "LAR projected ahead by 9.6"}})
    assert why[0].startswith("Best price -139 beats the no-vig fair (-151) by +3.0%")
    assert not any("last 10" in w for w in why) and "Sim script: LAR projected ahead by 9.6" in why   # form is context only
    assert risk[0].startswith("Only 2 books quote this side")
    assert any("Model says 55% vs market 60%" in r for r in risk)


def test_card_fields_and_ledger_record():
    row = _row()
    fields = pc.card_fields(row, sport="nfl", date="2026-10-14", number=1,
                            game={"matchup": "Arizona Cardinals @ Los Angeles Rams", "commence_time": "2026-10-18T20:05:00Z"})
    assert fields["bet"] == "UNDER 2.5 RECEPTIONS" and fields["fair"] == "-151" and fields["edge"] == "+3.0%"
    assert fields["form_values"][0] == 0 and fields["form_values"][-1] == 2          # oldest first for the chart
    rec = pc.ledger_record(fields, row, sport="nfl", generated_at="2026-10-14T23:40:00Z")
    assert rec["card_id"] == fields["id"] == pc.card_id("nfl", "2026-10-14", row)
    assert rec["result"] is None and rec["close"] is None and rec["price"] == -139


def test_the_sheet_never_calls_a_one_sided_fair_value():
    row = {"side": "yes", "line": None, "quote": {"price": 1000, "fair_probability": 0.095, "fair_method": "book_margin_model",
                                                  "assumed_hold_pct": 8.0, "bookmaker": "fanduel"}, "projection": {}}
    check = cs.price_check(row, [])
    assert check.ev_market > 2 and check.verdict == "one_sided_fair"


def test_render_card_fills_every_placeholder(tmp_path):
    spec = importlib.util.spec_from_file_location("build_play_cards", Path(__file__).resolve().parents[1] / "scripts" / "build_play_cards.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    fields = pc.card_fields(_row(), sport="nfl", date="2026-10-14", number=2,
                            game={"matchup": "Arizona Cardinals @ Los Angeles Rams", "commence_time": "2026-10-18T20:05:00Z"})
    html_text = m.render_card(fields, "data:image/webp;base64,AAAA")
    assert "$" not in html_text.replace("$$", "")                                   # no unfilled template field
    assert "FREE PLAY #2" in html_text and "UNDER 2.5 RECEPTIONS" in html_text and "-151" in html_text
    assert "<svg" in m.chart_svg([1, 3], ["25-W1", "26-W2"], 2.5, "under") and ">W2<" in m.chart_svg([1, 3], ["25-W1", "26-W2"], 2.5, "under")


def test_card_shows_headshot_team_crest_position_and_both_logos():
    spec = importlib.util.spec_from_file_location("build_play_cards", Path(__file__).resolve().parents[1] / "scripts" / "build_play_cards.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    row = _row(headshot_url="data:image/webp;base64,HEAD", team_logo="data:image/webp;base64,ATL", kickoff_ct="Sun Oct 18 · 3:05 PM CT")
    game = {"matchup": "Arizona Cardinals @ Los Angeles Rams", "commence_time": "2026-10-18T20:05:00Z",
            "home_logo": "data:image/webp;base64,LAR", "away_logo": "data:image/webp;base64,ARI", "kickoff_ct": "Sun Oct 18 · 3:05 PM CT"}
    fields = pc.card_fields(row, sport="nfl", date="2026-10-14", number=1, game=game)
    html_text = m.render_card(fields, "data:image/webp;base64,AAAA")
    assert 'class="head" src="data:image/webp;base64,HEAD"' in html_text and "base64,ATL" in html_text
    assert html_text.index("base64,ARI") < html_text.index("base64,LAR") and "ATL · RB" in html_text
    assert "Sun Oct 18 · 3:05 PM CT" in html_text and "$" not in html_text.replace("$$", "")
    no_face = m.hero_html({"player": "Tyler Allgeier"})
    assert ">TA<" in no_face and "img" not in no_face


def _pick(**extra):
    pick = {"pick_id": "l2_129acb8c9c927fb9", "kind": "game", "sport": "mlb", "event_id": "e7",
            "matchup": "Milwaukee Brewers @ Los Angeles Dodgers", "home_team": "Los Angeles Dodgers", "away_team": "Milwaukee Brewers",
            "player_name": None, "display_name": "Milwaukee Brewers", "market": "h2h", "side": "away", "line": None,
            "segment": "first3", "segment_label": "1st 3 innings", "price": 138, "book": "betrivers", "books": 5,
            "fair_price": 129, "p_market": 0.437, "p_model": 0.509, "ev_pct": 3.92, "sim_view": "agrees",
            "detail": "Our sim has Milwaukee Brewers to win (1st 3 innings) at 50.9%; the no-vig market across 5 books says 43.7%. "
                      "Recent form: Brewers led after 3 in 6 of their last 10.",
            "bet": "Milwaukee Brewers moneyline · 1st 3 innings", "commence_time": "2026-10-16T00:00:00Z", "board_score": 4.39}
    pick.update(extra)
    return pick


def test_a_syndicate_pick_card_shows_its_case_without_making_the_model_the_reason():
    # User 2026-10-15: "add the suggested opps as a picks section with pick graphics". The model is context or risk on
    # a card, never the reason -- the sim-vs-market sentence becomes the chart, not a bullet.
    from syndicate.features.shared import play_cards as pc

    f = pc.pick_card_fields(_pick(), sport="mlb", date="2026-10-15", number=1)
    assert f["bet"] == "MILWAUKEE BREWERS MONEYLINE · 1ST 3 INNINGS" and f["price"] == "+138" and f["fair"] == "+129"
    assert f["team"] == "1st 3 innings" and f["headshot"] is None and f["edge"] == "+3.9%"
    assert f["why"][0].startswith("Best price +138 beats the no-vig fair (+129)")
    assert not any(w.startswith("Our sim has") for w in f["why"]) and "Recent form: Brewers led after 3 in 6 of their last 10" in f["why"]
    assert f["chart_title"] == "Sim vs market" and "Our sim" in f["chart_svg"] and "51%" in f["chart_svg"]
    html = pc.render_card(f, "data:,", template="$chart_title|$bet|$chart_caption|$tag")
    assert html.startswith("Sim vs market|MILWAUKEE BREWERS MONEYLINE") and html.endswith("|SYNDICATE PICK")   # no number
    rec = pc.ledger_record(f, _pick(), sport="mlb", generated_at="2026-10-15T14:00:00Z")
    assert rec["segment"] == "first3" and rec["pick_id"] == "l2_129acb8c9c927fb9" and rec["price"] == 138 and rec["kind"] == "game"


def test_the_daily_cards_promote_the_syndicate_picks_first():
    from syndicate.features.shared import play_cards as pc

    value_row = {"event_id": "e1", "player": "Somebody", "market": "Receptions", "line": 2.5, "side": "under", "books_quoting": 5,
                 "check": {"verdict": "value", "ev_market": 3.0, "price": -110, "p_market": 0.55}}
    with_picks = {"sport": "mlb", "date": "2026-10-15", "rows": [value_row], "picks": [_pick()]}
    without = {"sport": "nfl", "date": "2026-10-15", "rows": [value_row], "picks": []}
    cards = pc.pick_cards([with_picks, without], per_sport=3)
    assert [(f["label"], f["player"]) for f, _item, _s in cards] == [("SYNDICATE PICK", "Milwaukee Brewers"), ("FREE PLAY", "Somebody")]



def test_ask_the_syndicates_case_becomes_short_labelled_points():
    # User 2026-10-15: "the 'Ask The Syndicate' data to be cleaner in how its represented on these picks ... refer to
    # the X.COM sheets". The sim's sentences are tiles, not points; season metrics keep their two best ranks.
    from syndicate.features.shared import cheat_sheets as cs

    detail = ("Our sim has Junior Caminero over 0.5 hits at 63.7%; the no-vig market across 6 books says 62.1%. "
              "Recent form: over 0.5 in 7 of the last 10 logged games (avg 1; log since 2026-09-23). "
              "Splits (2023-26): vs RHP .265 AVG, 72 HR in 1140 PA; vs CLE .227 AVG, 3 HR in 76 PA (2024-26). "
              "History vs this team: over 0.5 in 12 of 19 games since 2024-09-12. "
              "Matchup: vs Gavin Williams (career) 2 hits in 10 PA, 1 HR, 3 K, 0 BB. It projects an average of 1.1 against the 0.5 line. "
              "Season metrics, 2,880 pitches: xwOBA Junior Caminero 0.410 (73rd of 461); Barrel rate Junior Caminero 13.3% (41st of 461); "
              "Hard-hit rate Junior Caminero 50.4% (27th of 461).")
    pts = cs.ask_points(detail, subject="Junior Caminero", limit=8)
    assert pts == [{"label": "Recent form", "text": "over 0.5 in 7 of the last 10 games (avg 1)", "tone": "for"},
                   {"label": "Splits", "text": "vs RHP .265 AVG, 72 HR in 1140 PA", "tone": ""},
                   {"label": "Vs this team", "text": "over 0.5 in 12 of 19 games since 2024-09-12", "tone": "for"},
                   {"label": "Matchup", "text": "vs Gavin Williams (career) 2 hits in 10 PA, 1 HR, 3 K, 0 BB", "tone": ""},
                   {"label": "Season", "text": "Hard-hit rate 50.4% (27th of 461)", "tone": ""},
                   {"label": "Season", "text": "Barrel rate 13.3% (41st of 461)", "tone": ""}]
    nfl = cs.ask_points("Matchup: over 1.5 in 4 of 6 vs ARI; ARI has allowed 32.4 points a game (5 games).")
    assert nfl == [{"label": "Vs ARI", "text": "over 1.5 in 4 of 6 meetings", "tone": "for"},
                   {"label": "Opponent", "text": "ARI has allowed 32.4 points a game (5 games)", "tone": ""}]
    # User 2026-10-15: "we still have bullets that end with ... instead of full explanations" -- nothing is cut.
    assert not any(p["text"].endswith(("…", "...")) for p in cs.ask_points("Recent form: " + "x " * 200))


def test_a_pick_card_ticks_what_backs_it_and_flags_what_argues_against_it():
    # A 0-in-3 record vs this team is a RISK on the card, never a tick; what backs the side is listed first, and every
    # bullet is a whole statement -- the card shrinks its type to fit rather than cutting one short.
    from syndicate.features.shared import play_cards as pc

    points = [{"label": "Last 10", "text": "over 1.5 in 5 of 10, averaging 1.5 (low 0, high 4)", "tone": ""},
              {"label": "Last 5", "text": "over 1.5 in 5 of 5 (newest first: 4 v NJD, 2 v MTL, 2 v SEA, 2 v OTT, 2 v WPG)", "tone": "for"},
              {"label": "Vs PHI", "text": "over 1.5 in 0 of 3 meetings", "tone": "against"},
              {"label": "Vs position", "text": "PHI allows 24.8 shots on goal a game to forwards, the most of 32 (8 games this season)",
               "tone": "for"}]
    pick = _pick(kind="prop", player_name="Emmitt Finnie", display_name="Emmitt Finnie", market="SOG", side="over", line=1.5,
                 segment="full", points=points, recent_values=[4, 2, 2, 2, 2, 1], recent_opponents=["NJD", "MTL", "SEA", "OTT", "WPG", "NYR"])
    f = pc.pick_card_fields(pick, sport="nhl", date="2026-10-15", number=1)
    assert f["why"][1:] == ["Last 5: over 1.5 in 5 of 5 (newest first: 4 v NJD, 2 v MTL, 2 v SEA, 2 v OTT, 2 v WPG)",
                            "Vs position: PHI allows 24.8 shots on goal a game to forwards, the most of 32 (8 games this season)",
                            "Last 10: over 1.5 in 5 of 10, averaging 1.5 (low 0, high 4)"]
    assert f["risk"][0] == "Vs PHI: over 1.5 in 0 of 3 meetings"
    values, labels = pc.pick_form({"rows": []}, pick)                     # its kept games draw the chart, oldest left
    assert values == [1, 2, 2, 2, 2, 4] and labels == ["NYR", "WPG", "OTT", "SEA", "MTL", "NJD"]
    assert "--li" in pc.render_card(f, "data:,")                           # the fit-to-frame script ships with the card


def test_the_badge_holds_the_sports_ball():
    # User 2026-10-15: "the syndicate logo changed the ball being held based on sport". Every mapped badge ships; hockey
    # has no puck version, so it keeps the plain badge.
    from syndicate.features.shared import play_cards as pc

    assert pc.badge_name("MLB") == "syndicate_roi_badge_baseball.webp" and pc.badge_name("ncaaf") == "syndicate_roi_badge_football.webp"
    assert pc.badge_name("wnba") == "syndicate_roi_badge_basketball.webp" and pc.badge_name("nhl") == "syndicate_roi_badge_puck.webp"
    assert pc.badge_name("cricket") == "syndicate_roi_badge.webp"                    # a sport with no ball keeps the plain one
    assert all((pc.BRAND_DIR / pc.badge_name(s)).is_file() for s in pc.SPORT_BALL)


def test_a_price_play_graphic_never_shows_the_sims_number():
    # User 2026-10-15: touting the sim beside "SmartSim 12%" devalues the work. A price edge the sim does not back posts
    # as a PRICE PLAY: Books in place of SmartSim, the market against the price in the chart, the price as the reason.
    from syndicate.features.shared import play_cards as pc

    pick = _pick(market="totals", side="over", line=47.5, display_name="GASO @ ODU", bet="Over 47.5", sim_view="contradicts",
                 p_model=0.12, p_market=0.5, price=109, fair_price=100, book="prophetx", books=24, ev_pct=4.5, points=[])
    f = pc.pick_card_fields(pick, sport="ncaaf", date="2026-10-15", number=1)
    assert f["label"] == "PRICE PLAY" and f["tile3_k"] == "Books" and f["tile3_v"] == "24" and f["model_prob"] is None
    assert f["why"][0].startswith("The edge is the price: 24 books put it at 50% (fair +100); ProphetX pays +109")
    html = pc.render_card(f, "data:,").split("</style>", 1)[1]                # what renders, not the CSS comments
    assert "Market outlook" in html and "SmartSim" not in html and ">12%<" not in html and "Sim 12" not in html \
        and "Our sim" not in html                                                # 12% as TEXT (the background has cx="12%")
    backed = pc.pick_card_fields(_pick(), sport="mlb", date="2026-10-15", number=1)          # sim agrees: a pick
    assert backed["label"] == "SYNDICATE PICK" and "SmartSim outlook" in pc.render_card(backed, "data:,")
