"""An Ask answer must name a bet you can place, and say what the sim thinks.

Every fixture here is a VERBATIM row captured from production on 2026-08-16
(`/api/board/layer2-shortlist` and `/api/syndicate/query`), not a hand-authored
shape. Four defects were reported against the live inline panel and all four
were reproduced against these exact objects:

1. a prop answer named neither the prop nor the side ("Ryan Johnson");
2. the briefing said "top 5" and the panel rendered 3;
3. a game side read "home -1.5 (Philadelphia Phillies @ Minnesota Twins)";
4. `bet_analysis.edge` published EV while `market_summary.edge` published the
   model edge, so the SAME pick read 14.0% in the briefing and 1.4% per-pick.

See `.syndicate/plan_2026-08-16_ask_answer_substance.md`.
"""
from __future__ import annotations

import pytest

from syndicate.blueprints import ask_the_syndicate_adapter as adapter


# --------------------------------------------------------------------------
# Production fixtures, captured 2026-08-16 ~17:2xZ.
# --------------------------------------------------------------------------

# A layer2 shortlist prop row.
PROP_ROW = {
    "away_team": "St. Louis Cardinals",
    "home_team": "Chicago Cubs",
    "kind": "prop",
    "line": 0.5,
    "market": "batter_rbis",
    "model_edge_pct": 5.52,
    "player_name": "JJ Wetherholt",
    "side": "over",
    "sport": "mlb",
    "ev_pct": 4.1826,
    "is_live": False,
    "game_state": "pregame",
    "game": {"matchup": "STL @ CHC", "state": "pregame", "away_score": None, "home_score": None},
    "projection": {
        "basis": "rbi_1plus",
        "edge_vs_market_pct": 5.52,
        "market_fair_prob_over": 0.2706,
        "model_prob_over": 0.3258,
        "model_skill": {
            "correlation": 0.1316,
            "sample_games": 2487,
            "status": "measured",
            "verdict": "biased high ~31%; real ranking signal, loses to the mean until de-biased",
        },
        "projected": 0.564,
        "side": "over",
        "source": "hitter_threshold",
    },
    "quote": {
        "book_age_seconds": 599.9,
        "bookmaker": "betrivers",
        "books_quoting": 3,
        "fair_probability": 0.28543168882992953,
        "price": 265,
    },
    "score": {"score": 3.1997, "sim_component": 0.0, "ev_component": 4.1826},
}

# A layer2 shortlist game-side row. `side` is "away" and `line` is that side's
# own handicap -- pinned by the CLOSED `spread-line-sign-convention` lane.
GAME_ROW = {
    "away_team": "Kansas City Royals",
    "home_team": "Los Angeles Angels",
    "kind": "game",
    "line": -1.5,
    "market": "spreads",
    "model_edge_pct": 3.34,
    "player_name": None,
    "side": "away",
    "sport": "mlb",
    "ev_pct": 5.1327,
    "projection": {
        "basis": "full/run_margin_dist",
        "market_fair_prob_over": 0.6047,
        "model_prob_over": 0.5713,
        "model_skill": {
            "correlation": None,
            "sample_games": 0,
            "status": "unmeasured",
            "verdict": "model never backtested -- projection is unvalidated",
        },
        "projected": -0.608,
        "side": "home",
        "source": "game_simulation",
    },
    "quote": {"book_age_seconds": 1308.9, "bookmaker": "betopenly", "books_quoting": 5,
              "fair_probability": 0.39823008849557523, "price": 164},
    "score": {"score": 4.6194, "sim_component": 0.0},
}

# `explanation.top_candidate` from a served `bet_analysis` answer. Note the
# FLATTER shape: no nested `projection`, and `edge` here is the EV fraction.
BET_CANDIDATE = {
    "away_team": "Kansas City Royals",
    "home_team": "Los Angeles Angels",
    "confidence": 0.7,              # book_confidence, NOT model confidence
    "edge": 0.013913,               # EV fraction
    "ev_pct": 1.3913,
    "fair_price": -104,
    "kind": "prop",
    "line": 2.5,
    "market": "earned_runs",
    "matchup": "Kansas City Royals @ Los Angeles Angels",
    "model_edge_pct": 14.01,
    "model_probability": 0.63,
    "odds": -101,
    "player_name": "Ryan Johnson",
    "projected": 3.951,
    "selection": "Ryan Johnson",
    "side": "over",
    "sim_projection": 3.951,
    "sport": "mlb",
    # VERBATIM, and the two fields at the end are why this comment exists. The
    # first cut of this fixture dropped `quote_seen_age_seconds` and
    # `suspect_stale` as "not needed", which is exactly how the stale-quote bug
    # survived a green suite: with only the book clock present there was no way
    # for a test to notice the code was reading the wrong one. A trimmed fixture
    # cannot fail the test its omission causes. Do not trim rows here.
    "quote": {"assumed_hold_pct": None, "book_age_seconds": 5074.9,
              "book_prices": {"betmgm": -120, "bovada": -125, "draftkings": -101},
              "bookmaker": "draftkings", "books_quoting": 2, "fair_method": "consensus",
              "fair_probability": 0.5094786729857821, "price": -101,
              "quote_seen_age_seconds": 585.4, "suspect_stale": False},
}


# --------------------------------------------------------------------------
# 1. The label names the bet.
# --------------------------------------------------------------------------

def test_prop_label_carries_side_and_line():
    """Report 1. `"JJ Wetherholt"` alone names no bet."""
    assert adapter._bet_label(PROP_ROW) == "JJ Wetherholt over 0.5"


def test_bet_analysis_selection_is_the_whole_bet():
    """The served answer was `"Ryan Johnson"` while the same dict held
    market/line/side."""
    schema = adapter._bet_analysis_schema(
        {"recommendations": [BET_CANDIDATE]}, question="Ryan Johnson over 2.5", relevance_matched=True,
    )
    assert schema["selection"] == "Ryan Johnson over 2.5"
    assert schema["market"] == "earned_runs"
    assert schema["line"] == 2.5
    assert schema["side"] == "over"


def test_game_side_names_the_team_not_the_word_home():
    """Report 2b. `"away -1.5 (...)"` requires the reader to know a convention
    before they can place it. The handicap keeps its sign: `+1.5` and `-1.5`
    are two different bets."""
    label = adapter._bet_label(GAME_ROW)
    assert label == "Kansas City Royals -1.5"
    assert "away" not in label.lower()


def test_home_side_names_the_home_team():
    row = dict(GAME_ROW, side="home", line=1.5)
    assert adapter._bet_label(row) == "Los Angeles Angels +1.5"


def test_lay_market_says_it_is_a_bet_against_the_team():
    """A bare team name on a lay market is not vague, it is INVERTED. Mirrors
    `layer2_board._pick_label`'s rule."""
    row = dict(GAME_ROW, market="h2h_lay", side="home", line=None)
    label = adapter._bet_label(row)
    assert label.startswith("LAY Los Angeles Angels")
    assert "does not" in label


def test_bet_label_matches_layer2_pick_label_on_team_naming():
    """**The anti-drift pin.** `_bet_label` deliberately does not import
    `layer2_board` (a worker-side builder that must not be called from a
    request path), so the side->team convention lives in two places. If they
    ever disagree, chat and the board name different teams for the same row.

    Only the TEAM is compared -- the adapter additionally appends the handicap,
    which the board label does not carry."""
    from syndicate.features.shared import layer2_board

    for row in (GAME_ROW, dict(GAME_ROW, side="home")):
        board_label = layer2_board._pick_label(row)
        assert adapter._bet_label(row).startswith(board_label), (
            f"adapter and board disagree: {adapter._bet_label(row)!r} vs {board_label!r}"
        )


def test_bet_label_returns_none_rather_than_a_bare_direction_word():
    """A caller must be able to keep a better `selection` it already had."""
    assert adapter._bet_label({"side": "over"}) is None


def test_bet_label_never_degrades_a_selection_it_cannot_improve():
    """Regression, caught by `test_adapter_promotes_question_relevant_recommendation`.

    A snapshot candidate carrying only `name` and `matchup` has no side and no
    line, so there is no bet here to name. The first cut returned
    `"(Milwaukee Brewers vs Pittsburgh Pirates)"` -- strictly worse than the
    `"Milwaukee Brewers ML"` it replaced. This function improves a label or
    leaves it alone."""
    assert adapter._bet_label({
        "name": "Milwaukee Brewers ML",
        "matchup": "Milwaukee Brewers vs Pittsburgh Pirates",
    }) is None
    # ... and a total with no line is not a bet either.
    assert adapter._bet_label({"side": "over", "matchup": "STL @ CHC"}) is None


# --------------------------------------------------------------------------
# 2. Edge is one quantity, in one unit, on both schemas.
# --------------------------------------------------------------------------

def test_bet_analysis_edge_is_the_model_edge_in_percent():
    """Report 3, the ten-fold contradiction. `edge` was `ev_pct / 100`."""
    schema = adapter._bet_analysis_schema(
        {"recommendations": [BET_CANDIDATE]}, question="Ryan Johnson", relevance_matched=True,
    )
    assert schema["edge"] == pytest.approx(14.01)
    assert schema["edge_pct"] == pytest.approx(14.01)
    # The value it used to publish, so a regression is unambiguous.
    assert schema["edge"] != pytest.approx(0.013913)


def test_bet_analysis_and_board_agree_on_edge_for_the_same_pick():
    """The defect stated as the user saw it: one pick, two surfaces, two
    numbers."""
    per_pick = adapter._bet_analysis_schema(
        {"recommendations": [BET_CANDIDATE]}, question="Ryan Johnson", relevance_matched=True,
    )["edge"]
    board_row = dict(PROP_ROW, model_edge_pct=14.01)
    board_edge = board_row["model_edge_pct"]
    assert per_pick == pytest.approx(board_edge)


def test_market_probability_and_ev_come_from_the_fields_that_exist():
    """Both were served as `null` while the same object carried what they
    needed. The regression harness has been reporting the first as a warning
    (`edge_without_market_probability`) into a list nobody reads."""
    schema = adapter._bet_analysis_schema(
        {"recommendations": [BET_CANDIDATE]}, question="Ryan Johnson", relevance_matched=True,
    )
    assert schema["market_probability"] == pytest.approx(48.99, abs=0.01)
    assert schema["EV"] == pytest.approx(1.3913)


def test_model_minus_market_equals_edge():
    """**The invariant that stops this whole class of bug.**

    Caught in the first replay over the live board: reading
    `quote.fair_probability` gave `Market 51.0%` per-pick while the briefing
    said `Market 49.0%` for the same pick at the same instant -- the same
    two-surfaces-two-numbers defect this lane exists to fix, re-created one
    field over. They are different quantities: the board's market probability
    is reconciled against `model_edge_pct`, the quote's is the no-vig price of
    one quote. Only the first satisfies this identity."""
    schema = adapter._bet_analysis_schema(
        {"recommendations": [BET_CANDIDATE]}, question="Ryan Johnson", relevance_matched=True,
    )
    assert schema["model_probability"] - schema["market_probability"] == pytest.approx(
        schema["edge"], abs=0.02
    )


def test_market_probability_falls_back_to_the_quote_without_a_model_edge():
    """A row with no model edge has no identity to derive from; the quote's
    no-vig fair price is then the only market number there is."""
    candidate = {k: v for k, v in BET_CANDIDATE.items()
                 if k not in ("model_edge_pct", "model_probability", "edge")}
    schema = adapter._bet_analysis_schema(
        {"recommendations": [candidate]}, question="Ryan Johnson", relevance_matched=True,
    )
    assert schema["market_probability"] == pytest.approx(50.95, abs=0.01)


def test_confidence_is_never_book_confidence():
    """`top["confidence"]` is 0.7 = book_confidence, a price-reliability term.
    Published under `confidence` it reads as model confidence: 70.0, against a
    real model probability of 63.0."""
    schema = adapter._bet_analysis_schema(
        {"recommendations": [BET_CANDIDATE]}, question="Ryan Johnson", relevance_matched=True,
    )
    assert schema["confidence"] == pytest.approx(63.0)
    assert schema["confidence"] != pytest.approx(70.0)


# --------------------------------------------------------------------------
# 3. The answer says what the sim thinks, and whether the sim was ever checked.
# --------------------------------------------------------------------------

def test_price_and_book_are_published():
    """An edge with no price behind it is not a bet -- and `ev` is computed
    against that price."""
    schema = adapter._bet_analysis_schema(
        {"recommendations": [BET_CANDIDATE]}, question="Ryan Johnson", relevance_matched=True,
    )
    assert schema["price"] == -101
    assert schema["bookmaker"] == "draftkings"
    assert schema["books_quoting"] == 2


def test_sim_terms_read_the_projection_not_sim_component():
    """`score.sim_component` is 0.0 on 108 of 108 served rows; publishing it
    would report "the sim contributed nothing" as a measurement of this bet."""
    sim = adapter._sim_terms(PROP_ROW)
    assert sim["projected"] == pytest.approx(0.564)
    assert sim["projection_source"] == "hitter_threshold"
    assert sim["model_skill_status"] == "measured"


def test_team_side_projection_is_not_published_at_all():
    """Caught in the first replay over the live board: a `Minnesota Twins -1.5`
    row rendered "Sim 1.369" directly beside "Edge 14.8%", inviting a
    comparison against the -1.5 handicap that nothing in this payload
    justifies. `_reason_sentences` already declined to write that clause;
    leaving the raw number in the numbers row smuggled it straight back in.

    The skill fields still publish -- it is the NUMBER that is unpinned, not
    whether the model behind it was ever measured."""
    sim = adapter._sim_terms(GAME_ROW)
    assert GAME_ROW["projection"]["projected"] == pytest.approx(-0.608)  # it IS on the row
    assert sim["projected"] is None                                      # and is NOT published
    assert sim["model_skill_status"] == "unmeasured"


def test_market_label_is_a_unit_only_for_a_prop():
    """"9.494 total against a line of 7.5" reads as a typo, and `totals_alt`
    gave "7.057 alt total against a line of 6.5". Both seen in the first replay
    over the live board. A prop's market IS its unit ("3.951 earned runs"); a
    game total's is not."""
    total_row = {
        "market": "totals", "side": "over", "line": 7.5, "player_name": None,
        "away_team": "Milwaukee Brewers", "home_team": "Los Angeles Dodgers",
        "projection": {"projected": 9.494},
    }
    reason = adapter._reason_sentences(
        total_row, adapter._bet_facts(total_row), adapter._sim_terms(total_row),
        model_pct=60.1, market_pct=45.9, edge_pct=14.2,
    )
    assert "projects 9.494 against a line of 7.5" in reason
    assert "9.494 total" not in reason


def test_unmeasured_model_is_stated_not_hidden():
    """88 of 108 rows say of themselves that the model was never backtested.
    Under the standing "LLM stays off" decision, the system prompt's
    surface-uncertainty rules will never execute, so this is the only place
    they can live."""
    sim = adapter._sim_terms(GAME_ROW)
    assert sim["model_skill_status"] == "unmeasured"
    reason = adapter._reason_sentences(
        GAME_ROW, adapter._bet_facts(GAME_ROW), sim,
        model_pct=57.13, market_pct=60.47, edge_pct=3.34,
    )
    assert "never been backtested" in reason


def test_reason_states_projection_against_the_line_for_over_under():
    """The MLB game lens shape: "the projection sits at X against Y". Ask had
    every analogue and generated nothing -- `recommendation` was `null` on 5 of
    5 briefing rows."""
    reason = adapter._reason_sentences(
        PROP_ROW, adapter._bet_facts(PROP_ROW), adapter._sim_terms(PROP_ROW),
        model_pct=32.58, market_pct=27.06, edge_pct=5.52,
    )
    assert "0.564" in reason
    assert "against a line of 0.5" in reason
    assert "over" in reason
    assert "+265 at betrivers" in reason


def test_reason_omits_the_projection_clause_for_a_team_side():
    """For a team side the projection is a run margin whose sign convention
    against the handicap is not pinned in this payload. A published number is
    computed or absent, never inferred -- so the clause is dropped rather than
    guessed, while model-vs-market still covers the row."""
    reason = adapter._reason_sentences(
        GAME_ROW, adapter._bet_facts(GAME_ROW), adapter._sim_terms(GAME_ROW),
        model_pct=57.13, market_pct=60.47, edge_pct=3.34,
    )
    assert "-0.608" not in reason
    assert "against a line of" not in reason
    assert "57.1%" in reason


def test_reason_degrades_to_absent_rather_than_inventing():
    """A row with no projection, no probabilities and no quote must produce
    nothing, not a sentence built out of defaults."""
    bare = {"market": "totals", "side": "over", "line": 8.5}
    assert adapter._reason_sentences(
        bare, adapter._bet_facts(bare), adapter._sim_terms(bare),
        model_pct=None, market_pct=None, edge_pct=None,
    ) is None


def test_a_quiet_market_is_not_a_stale_quote():
    """THE FALSE ALARM THIS TEST USED TO PIN.

    `BET_CANDIDATE` is the real served shape and carries BOTH clocks:
    `book_age_seconds` 5074.9 (84 min, the price has not MOVED) and
    `quote.quote_seen_age_seconds` 585.4 (9.8 min, when we last LOOKED). This
    asserted "84 minutes old" and was passing on the wrong one -- measured on
    the served board 2026-08-16, that read fired on 31 of 101 rows and **13 were
    false**, all on the freshest sport. A motionless market is not stale data.
    """
    facts = adapter._bet_facts(BET_CANDIDATE)
    assert facts["quote_age_seconds"] == pytest.approx(585.4)
    reason = adapter._reason_sentences(
        BET_CANDIDATE, facts, adapter._sim_terms(BET_CANDIDATE),
        model_pct=63.0, market_pct=50.95, edge_pct=14.01,
    )
    assert "minutes ago" not in reason
    assert "84" not in reason


def test_reason_flags_a_genuinely_stale_OBSERVATION():
    """Only the seen-clock can raise it, and it says what the number means."""
    stale = dict(BET_CANDIDATE, quote=dict(BET_CANDIDATE["quote"],
                                           quote_seen_age_seconds=7188.0))
    reason = adapter._reason_sentences(
        stale, adapter._bet_facts(stale), adapter._sim_terms(stale),
        model_pct=63.0, market_pct=50.95, edge_pct=14.01,
    )
    assert "Last checked 119 minutes ago" in reason
    assert "confirm the price before betting" in reason


def test_book_age_is_the_fallback_only_when_there_is_no_seen_clock():
    """Absence of the seen clock is not evidence of freshness -- gate as before."""
    no_seen = dict(BET_CANDIDATE)
    no_seen["quote"] = {k: v for k, v in BET_CANDIDATE["quote"].items()
                        if k != "quote_seen_age_seconds"}
    assert adapter._bet_facts(no_seen)["quote_age_seconds"] == pytest.approx(5074.9)


def test_live_game_situation_is_stated():
    live = dict(PROP_ROW, is_live=True, game_state="live",
                game={"matchup": "STL @ CHC", "state": "live", "away_score": 2, "home_score": 1})
    reason = adapter._reason_sentences(
        live, adapter._bet_facts(live), adapter._sim_terms(live),
        model_pct=32.58, market_pct=27.06, edge_pct=5.52,
    )
    assert "Live now at 2-1" in reason


# --------------------------------------------------------------------------
# 4. The market label a reader can read.
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("batter_total_bases", "batter total bases"),
        ("earned_runs", "earned runs"),
        ("spreads", "spread"),
        ("spreads_alt", "alt spread"),
        ("totals_alt", "alt total"),
        ("h2h", "moneyline"),
        (None, ""),
    ],
)
def test_market_label(key, expected):
    assert adapter._market_label(key) == expected


# --------------------------------------------------------------------------
# 5. The M1 EVIDENCE TABLE names the same bet the headline names.
#
# Reported 2026-08-16, after the headline fix shipped: the table under the
# answer still read `home -1.5 (Philadelphia Phillies @ Minnesota Twins)` one
# line below a headline reading `Minnesota Twins -1.5` -- the SAME row, in the
# SAME response, naming two different things. `_board_row_label` was the third
# copy of this logic and the last one still wrong.
#
# `ask_the_syndicate_data` imports heavy per-sport fetchers, so these tests are
# the reason this file imports it at all; keep the import local to this block.
# --------------------------------------------------------------------------

from syndicate.blueprints import ask_the_syndicate_data as data  # noqa: E402


def test_evidence_table_label_is_the_headline_label():
    """The one property that matters: the two surfaces cannot disagree."""
    for row in (PROP_ROW, GAME_ROW):
        assert data._board_row_label(row) == adapter._bet_label(row)


def test_evidence_table_never_names_a_convention():
    """`home`/`away` is a column in an artifact, not a bet a person can place."""
    label = data._board_row_label(GAME_ROW).lower()
    assert not label.startswith(("home ", "away "))
    assert label.startswith("kansas city royals")


def test_evidence_table_prop_names_prop_and_side():
    assert data._board_row_label(PROP_ROW) == "JJ Wetherholt over 0.5"


def test_evidence_table_moneyline_is_the_bare_team():
    row = dict(GAME_ROW, market="h2h", line=None, side="home")
    assert data._board_row_label(row) == "Los Angeles Angels"


def test_evidence_table_lay_market_says_it_is_against():
    """A bare team name on a lay row is not vague, it is inverted."""
    row = dict(GAME_ROW, market="h2h_lay", line=None, side="home")
    label = data._board_row_label(row)
    assert label.startswith("LAY Los Angeles Angels")
    assert "does not" in label


def test_evidence_table_game_total_keeps_the_matchup():
    """A total has no team side, so side+line+matchup IS the bet. Not a miss."""
    row = dict(GAME_ROW, market="totals", line=7.5, side="over",
               player_name=None)
    assert data._board_row_label(row) == "over 7.5 (Kansas City Royals @ Los Angeles Angels)"


def test_evidence_table_falls_back_to_the_game_never_to_the_old_shape():
    """No side and no line -> name the game, never `home -1.5 (...)`."""
    row = {"away_team": "Kansas City Royals", "home_team": "Los Angeles Angels",
           "market": "h2h", "side": "", "line": None}
    assert data._board_row_label(row) == "Kansas City Royals @ Los Angeles Angels"


def test_chart_label_keeps_LAY_and_drops_the_clause():
    """Truncation must not cut a lay label mid-phrase, and must keep `LAY`."""
    row = dict(GAME_ROW, market="h2h_lay", line=None, side="away")
    chart = data._board_row_chart_label(row)
    assert chart.startswith("LAY Kansas City Royals")
    assert "wins if" not in chart
    assert len(chart) <= 28


def test_chart_label_respects_its_budget():
    row = dict(GAME_ROW, player_name="A Player With A Very Long Name Indeed",
               side="over", line=1.5)
    assert len(data._board_row_chart_label(row)) <= 28
