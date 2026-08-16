"""`#364` -- WNBA game lines carried no sim at all, on a board built to show sims.

MEASURED on the live board 2026-08-11: 3 games, 1,013 rows, 36.4% projection
coverage, and **0.0% of it on game lines**. Every projection was a player prop.
601 moneyline/spread/total rows had nothing.

Not a join or naming failure -- `attach_wnba_projections` opens with
`if row["kind"] != "prop": continue`, so game rows were never considered. The
source had been there since 2026-08-02: `game_cards_<date>.csv` carries
`pred_margin`/`pred_total`, added by the very commit noting "WNBA game markets
had structurally zero edge". The columns were written and nothing read them.

These tests pin the four decisions that could each produce a plausible WRONG
number rather than a blank -- which is the failure mode that matters here, since
a bad projection propagates into EV and eventually a stake.
"""

from __future__ import annotations

from syndicate.features.shared.wnba_game_projections import (
    WnbaGameProjectionIndex,
    attach_wnba_game_projections,
)

HOME, AWAY = "Las Vegas Aces", "Washington Mystics"


def _index(margin: float | None = 7.5, total: float | None = 163.5) -> WnbaGameProjectionIndex:
    index = WnbaGameProjectionIndex()
    index.by_teams[(HOME.lower(), AWAY.lower())] = {"pred_margin": margin, "pred_total": total}
    index.games = 1
    return index


def _row(market: str, *, segment: str = "full", line=None, kind: str = "game") -> dict:
    return {
        "kind": kind,
        "market": market,
        "segment": segment,
        "line": line,
        "home_team": HOME,
        "away_team": AWAY,
    }


def test_moneyline_probability_follows_the_home_positive_margin():
    # `pred_margin` is home-positive -- confirmed at the WRITER
    # (refresh_wnba_oddsapi_props.py:2558 computes home_total - away_total), not
    # inferred. Backwards, every moneyline inverts and still looks reasonable.
    favoured = _row("h2h")
    attach_wnba_game_projections([favoured], _index(margin=7.5))
    assert favoured["projection"]["model_prob_over"] > 0.5
    assert favoured["projection"]["side"] == HOME

    underdog = _row("h2h")
    attach_wnba_game_projections([underdog], _index(margin=-7.5))
    assert underdog["projection"]["model_prob_over"] < 0.5, "a home underdog came out favoured"


def test_a_mean_never_becomes_a_fabricated_probability():
    # The `wnba_projections` module rule and `#242`: the sim ships MEANS for
    # totals/spreads, and inventing P(over) needs a distributional assumption
    # nobody has measured. A blank is recoverable; a fabricated probability
    # reaches a stake.
    rows = [_row("totals", line=161.5), _row("spreads", line=-6.5)]
    attach_wnba_game_projections(rows, _index())
    for row in rows:
        projection = row["projection"]
        assert projection["model_prob_over"] is None
        assert projection["probability_unavailable_reason"]
        assert projection["projected"] is not None


def test_edge_vs_line_is_projection_minus_line():
    row = _row("totals", line=161.5)
    attach_wnba_game_projections([row], _index(total=163.5))
    assert row["projection"]["edge_vs_line"] == 2.0


def test_a_full_game_mean_is_never_stamped_on_a_period_market():
    # `pred_margin`/`pred_total` are 40-minute means. Attaching one to a Q1 or H1
    # row puts a real number against the wrong bet.
    rows = [_row("totals", segment="q1", line=40.5), _row("spreads", segment="h1", line=-3.5)]
    coverage = attach_wnba_game_projections(rows, _index())
    assert all(r.get("projection") is None for r in rows)
    assert coverage["non_full_segment_rows"] == 2
    assert coverage["rows_with_projection"] == 0


def test_props_are_left_to_the_prop_join():
    row = _row("player_points", kind="prop")
    attach_wnba_game_projections([row], _index())
    assert row.get("projection") is None, "the game join must not touch prop rows"


def test_an_unmatched_game_is_reported_not_guessed():
    row = _row("h2h")
    row["home_team"] = "Some Other Team"
    coverage = attach_wnba_game_projections([row], _index())
    assert row.get("projection") is None
    assert coverage["unmatched_game_rows"] == 1


def test_a_missing_mean_yields_a_blank_not_a_zero():
    rows = [_row("totals", line=161.5), _row("h2h")]
    attach_wnba_game_projections(rows, _index(margin=None, total=None))
    assert all(r.get("projection") is None for r in rows), "a missing mean rendered as a real projection"


def test_moneyline_states_why_it_has_no_edge():
    """The h2h branch was the ONE that served a blank Edge with no reason.

    Found by the 2026-08-16 production falsification sweep, not by review: the
    matching fix in `prop_projections` took MLB from 284 unattributed rows to 0
    and these 3 WNBA rows did not move, because this function writes
    `row["projection"]` directly and never passes through `attach_projections`.
    A fourth producer.

    `spreads` and `totals` were already attributed AND already get an
    `edge_vs_line`; h2h is excluded from that block by `market != "h2h"`,
    because a moneyline has no line to subtract. So it alone had neither.
    """
    row = _row("h2h")
    attach_wnba_game_projections([row], _index(margin=7.5))
    projection = row["projection"]

    assert projection["model_prob_over"] > 0.5, "guard: this row HAS a model probability"
    assert projection.get("edge_vs_market_pct") is None
    assert projection.get("edge_vs_line") is None, "a moneyline has no line to subtract"
    reason = projection.get("edge_unavailable_reason")
    assert reason, "an h2h projection with no edge must say why"
    assert "producer does not compute" in reason


def test_moneyline_reason_does_not_claim_a_missing_term():
    """The reason must be honest about WHICH kind of gap this is.

    These rows are two-sided and carry a model probability, so unlike the
    means-only spreads/totals branches nothing is arithmetically missing --
    an edge is computable and is deliberately withheld. A reason borrowed from
    the mean branches would send the next reader to the sim to add a
    distribution that already effectively exists here.
    """
    row = _row("h2h")
    attach_wnba_game_projections([row], _index(margin=7.5))
    reason = row["projection"]["edge_unavailable_reason"]
    assert "mean" not in reason.lower()
    assert "one-sided" not in reason.lower()
    # And it must not reuse the mean branches' DIFFERENT key, which the board
    # does not read for the Edge column.
    assert "probability_unavailable_reason" not in row["projection"]
