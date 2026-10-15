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
    assert "Cleared this line in 9 of the last 10 games" in why and "Sim script: LAR projected ahead by 9.6" in why
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
    no_face = m.face_html({"player": "Tyler Allgeier"})
    assert ">TA<" in no_face and "img" not in no_face
