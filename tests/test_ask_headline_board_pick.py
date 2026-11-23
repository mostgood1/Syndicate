"""Ask's headline is the board's own picks, for the sport asked about.

Lane `surface-consistency-oversight`, todo #861. Measured on the fleet
2026-11-23 19:29Z: "What are the best bets today?" and "Best NBA bets tonight?"
returned the SAME 5 headline rows, none of them NBA. They were ranked on 22-28
point model edges, 4 of the 5 from models whose own card said they LOSE to the
market, and 0 of the 5 were Suggested. Two causes, both covered here:

1. the ranking took `model_edge_pct` first instead of the board's pick flag and
   score (`_is_board_pick`, `_board_pick_rank_key`);
2. the sport the router inferred never reached the headline: the view passed
   only the client's context, and wrote the routed sport onto the response
   AFTER the headline was built.
"""
from __future__ import annotations

from unittest import mock

from flask import Flask

from syndicate.blueprints import ask_the_syndicate_adapter as adapter
from syndicate.blueprints.ask_the_syndicate import ask_the_syndicate_bp

READER = "pipeline.intelligence_state.read_layer2_shortlist"


def _row(sport, player, *, ev, score, suggested, edge=None, reasons=()):
    return {
        "sport": sport, "event_id": f"evt-{sport}-{player}", "kind": "prop", "market": "player_points",
        "player_name": player, "side": "over", "line": 20.5, "segment": "full",
        "home_team": "Home", "away_team": "Away",
        "ev_pct": ev, "model_edge_pct": edge, "score": {"score": score},
        "suggested": suggested, "suggested_reasons": list(reasons),
        "quote": {"price": 110, "bookmaker": "betmgm", "books_quoting": 6, "quote_seen_age_seconds": 30.0},
    }


# The 11-23 shape: the biggest model edges sit on rows the board did not pick.
BOARD = {
    "written_at": "2026-11-23T19:25:00Z",
    "rows": [
        _row("nfl", "Losing Model", ev=-8.3, score=3.6, suggested=False, edge=28.15, reasons=["ev_below_min"]),
        _row("nba", "Pick Two", ev=2.9, score=1.4, suggested=True),
        _row("nba", "Stale Line", ev=6.0, score=2.8, suggested=False, edge=9.0, reasons=["suspect_stale_quote"]),
        _row("nba", "Pick One", ev=4.1, score=2.2, suggested=True, edge=-1.5),
        _row("nhl", "Other Sport Pick", ev=5.0, score=3.0, suggested=True),
    ],
}
SNAPSHOT = {
    "query_type": "market_summary",
    "recommendations": [{"selection": "SNAPSHOT ROW", "sport": "nfl", "edge": 0.2815}],
    "summary": "Snapshot summary about other rows.",
    "readiness_gate": {"ok": True},
    "local_only": True,
}


def _ask(question, board=BOARD):
    app = Flask(__name__)
    app.register_blueprint(ask_the_syndicate_bp)
    with mock.patch(
        "syndicate.blueprints.ask_the_syndicate.read_latest_intelligence_state", return_value=dict(SNAPSHOT)
    ), mock.patch(READER, return_value=board), mock.patch(
        "syndicate.blueprints.ask_the_syndicate._read_cached_response", return_value=None
    ), mock.patch("syndicate.blueprints.ask_the_syndicate._store_cached_response"):
        response = app.test_client().post("/api/syndicate/query", json={"question": question})
    assert response.status_code == 200
    return response.get_json()


def test_an_nba_question_gets_the_boards_nba_picks_in_board_order():
    body = _ask("Best NBA bets tonight?")
    assert body["routed_sport"] == "nba"
    structured = body["structured_response"]
    top = structured["top_opportunities"]
    assert [r["selection"].split(" over")[0] for r in top] == ["Pick One", "Pick Two"]
    assert all(r["sport"] == "nba" and r["suggested"] is True for r in top)
    summary = structured["rationale_summary"]["summary"]
    assert "No board opportunity matches" not in summary, summary
    assert summary.startswith("Showing the board's top 2 suggested bets in NBA"), summary


def test_a_general_question_gets_the_boards_picks_across_sports_never_the_losing_model():
    top = _ask("What are the best bets today?")["structured_response"]["top_opportunities"]
    names = [r["selection"].split(" over")[0] for r in top]
    assert names == ["Other Sport Pick", "Pick One", "Pick Two"]
    assert "Losing Model" not in names and "Stale Line" not in names


def test_when_the_board_picks_nothing_in_the_sport_it_says_why():
    board = {"rows": [r for r in BOARD["rows"] if not (r["sport"] == "nba" and r["suggested"])]}
    structured = _ask("Best NBA bets tonight?", board)["structured_response"]
    assert structured["top_opportunities"] == []
    summary = structured["rationale_summary"]["summary"]
    assert summary == "The board suggests no NBA bets right now. Of its 1 NBA line, 1 has a stale quote.", summary


def test_a_sport_with_no_lines_is_named_not_answered_with_other_sports():
    structured = _ask("Best MLB bets today?")["structured_response"]
    assert structured["top_opportunities"] == []
    assert structured["rationale_summary"]["summary"] == "The board has no MLB lines today."


def test_routed_sport_is_what_scopes_the_headline_off_vs_on(monkeypatch):
    """Reachability: the same schema call with and without the routed sport."""
    monkeypatch.setattr("pipeline.intelligence_state.read_layer2_shortlist", lambda _d: BOARD, raising=False)
    off = adapter._market_summary_schema(SNAPSHOT, question="Best NBA bets tonight?", context={})
    on = adapter._market_summary_schema(SNAPSHOT, question="Best NBA bets tonight?", context={}, routed_sport="nba")
    assert {r["sport"] for r in off["top_opportunities"]} == {"nhl", "nba"}
    assert {r["sport"] for r in on["top_opportunities"]} == {"nba"}


def test_the_snapshot_summary_never_describes_a_board_answer(monkeypatch):
    monkeypatch.setattr("pipeline.intelligence_state.read_layer2_shortlist", lambda _d: BOARD, raising=False)
    schema = adapter._market_summary_schema(SNAPSHOT, question="What are the best bets today?", context={})
    assert "Snapshot summary" not in schema["rationale_summary"]["summary"]


def test_absence_sentence_wording():
    exclusion = adapter._BoardExclusion(
        count=1128, considered=1128, sport="nba",
        reasons=(("suspect_stale_quote", 1100), ("ev_below_min", 1039), ("single_book_fair", 230)),
    )
    assert adapter._board_summary_sentence([], exclusion) == (
        "The board suggests no NBA bets right now. Of its 1,128 NBA lines, 1,100 have a stale quote, "
        "1,039 are below the board's minimum EV and 230 have a fair price from one book only "
        "(a line can have more than one reason)."
    )
    # an unknown reason is shown by its own name, not dropped
    odd = adapter._BoardExclusion(count=2, considered=2, reasons=(("new_gate", 2),))
    assert adapter._board_summary_sentence([], odd) == "The board suggests no bets right now. Of its 2 lines, 2 new gate."


# --- the purchaser's in-play rule (todo #861, peer report 2026-11-23 19:46Z, re-measured 20:15Z) ---------------
#
# 7 of 47 Suggested rows were in play on a market price alone; one was an NCAAB under 159.5 at -102 on a 0.52
# fair, at 75-75 with 0:57 left. The purchaser refuses exactly these (`in_play_market_fair`); Ask does not
# headline them either, and says how many it left out.

def _live(row, **over):
    out = dict(row, is_live=True, market_state="live", game_state="live")
    out.update(over)
    return out


def test_an_in_play_pick_on_a_market_price_alone_is_not_headlined(monkeypatch):
    monkeypatch.delenv("SYNDICATE_PORTFOLIO_IN_PLAY_MARKET_FAIR", raising=False)
    monkeypatch.delenv("SYNDICATE_PORTFOLIO_IN_PLAY_MARKET_FAIR_CELLS", raising=False)
    stale = _live(_row("ncaab", "Stale Live", ev=3.1, score=9.0, suggested=True), market="totals", kind="game",
                  player_name=None)
    pregame = _row("ncaab", "Pregame Pick", ev=2.5, score=1.0, suggested=True)
    modelled = _live(_row("ncaab", "Live With Model", ev=2.2, score=0.5, suggested=True, edge=3.0))
    monkeypatch.setattr("pipeline.intelligence_state.read_layer2_shortlist",
                        lambda _d: {"rows": [stale, pregame, modelled]}, raising=False)
    schema = adapter._market_summary_schema(SNAPSHOT, question="best ncaab bets", context={}, routed_sport="ncaab")
    names = [r["selection"].split(" over")[0] for r in schema["top_opportunities"]]
    assert "Stale Live" not in " ".join(names)
    assert names == ["Pregame Pick", "Live With Model"]
    assert "1 in-play board pick left out" in schema["rationale_summary"]["summary"]


def test_the_purchasers_in_play_cells_and_override_are_honoured(monkeypatch):
    monkeypatch.delenv("SYNDICATE_PORTFOLIO_IN_PLAY_MARKET_FAIR", raising=False)
    monkeypatch.delenv("SYNDICATE_PORTFOLIO_IN_PLAY_MARKET_FAIR_CELLS", raising=False)
    ncaaf_total = _live(_row("ncaaf", "x", ev=3.0, score=1.0, suggested=True), market="totals", kind="game",
                        player_name=None)
    nba_total = _live(_row("nba", "x", ev=3.0, score=1.0, suggested=True), market="totals", kind="game",
                      player_name=None)
    assert adapter._is_board_pick(ncaaf_total) is True  # default cell ncaaf:totals, staked in play
    assert adapter._is_board_pick(nba_total) is False
    monkeypatch.setenv("SYNDICATE_PORTFOLIO_IN_PLAY_MARKET_FAIR", "allow")
    assert adapter._is_board_pick(nba_total) is True


def test_the_in_play_rule_does_not_depend_on_the_sizing_sport_allowlist(monkeypatch):
    """The purchaser's own function returns False everywhere when SYNDICATE_PORTFOLIO_MARKET_FAIR_SPORTS is
    absent, which it is on every role but refresh-worker. Ask's rule must refuse regardless."""
    monkeypatch.delenv("SYNDICATE_PORTFOLIO_MARKET_FAIR_SPORTS", raising=False)
    monkeypatch.delenv("SYNDICATE_PORTFOLIO_IN_PLAY_MARKET_FAIR", raising=False)
    monkeypatch.delenv("SYNDICATE_PORTFOLIO_IN_PLAY_MARKET_FAIR_CELLS", raising=False)
    from syndicate.features.shared.portfolio_commit import _refuses_in_play_market_fair

    row = _live(_row("ncaab", "x", ev=3.0, score=1.0, suggested=True), market="spreads", kind="game", player_name=None)
    assert _refuses_in_play_market_fair(row) is False  # the no-op on a role without the allowlist
    assert adapter._in_play_on_market_price_only(row) is True
    monkeypatch.setenv("SYNDICATE_PORTFOLIO_MARKET_FAIR_SPORTS", "mlb,nba,wnba,nhl,nfl,ncaaf,ncaab,soccer")
    assert _refuses_in_play_market_fair(row) is adapter._in_play_on_market_price_only(row) is True  # refresh-worker
