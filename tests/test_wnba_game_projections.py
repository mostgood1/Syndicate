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
    load_wnba_game_projections,
)

HOME, AWAY = "Las Vegas Aces", "Washington Mystics"


def _index(
    margin: float | None = 7.5,
    total: float | None = 163.5,
    *,
    p_home_win: float | None = None,
    p_home_cover: float | None = None,
    p_total_over: float | None = None,
    sim_market_home_spread: float | None = None,
    sim_market_total: float | None = None,
) -> WnbaGameProjectionIndex:
    index = WnbaGameProjectionIndex()
    index.by_teams[(HOME.lower(), AWAY.lower())] = {
        "pred_margin": margin,
        "pred_total": total,
        "p_home_win": p_home_win,
        "p_home_cover": p_home_cover,
        "p_total_over": p_total_over,
        "sim_market_home_spread": sim_market_home_spread,
        "sim_market_total": sim_market_total,
    }
    index.games = 1
    return index


def _row(
    market: str,
    *,
    segment: str = "full",
    line=None,
    kind: str = "game",
    consensus: dict | None = None,
    sides: list | None = None,
    game_state: str | None = None,
) -> dict:
    row: dict = {
        "kind": kind,
        "market": market,
        "segment": segment,
        "line": line,
        "home_team": HOME,
        "away_team": AWAY,
    }
    if consensus is not None:
        row["consensus"] = consensus
    if sides is not None:
        row["sides"] = sides
    if game_state is not None:
        # `live_edge_policy.game_state_of` reads `row["game"]["state"]`, NOT a
        # top-level `game_state` key -- a different shape from
        # `opportunity_gate.game_state_of`'s. Matched here deliberately so
        # this fixture exercises the SAME function the code under test calls.
        row["game"] = {"state": game_state}
    return row


# `#263` -- two-sided consensus book pricing, so `_no_vig_over_probability`
# (imported straight from `prop_projections.py`, not reimplemented) has
# something real to de-vig. American odds, both sides quoted at -110 -- a
# standard ~4.55% hold, not a degenerate case. Spreads quote home/away;
# totals quote over/under -- `_no_vig_over_probability` handles both
# vocabularies, per its own docstring.
_SPREADS_CONSENSUS = {"home": -110, "away": -110}
_SPREADS_SIDES = ["home", "away"]
_TOTALS_CONSENSUS = {"over": -110, "under": -110}
_TOTALS_SIDES = ["over", "under"]


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


# `#263` -- the sim's own real, model-free Monte Carlo probability
# (`p_home_cover`/`p_total_over`), threaded through when a row's line matches
# the sim's own market line.


def test_spreads_at_market_line_gets_a_real_probability_and_edge():
    row = _row("spreads", line=2.0, consensus=_SPREADS_CONSENSUS, sides=_SPREADS_SIDES)
    index = _index(margin=9.32, p_home_cover=0.30, sim_market_home_spread=2.0)
    attach_wnba_game_projections([row], index)
    projection = row["projection"]

    assert projection["model_prob_over"] == 0.3
    # -110/-110 de-vigs to an exact 0.5 fair -- (0.30 - 0.50) * 100.
    assert projection["edge_vs_market_pct"] == -20.0
    assert projection.get("probability_unavailable_reason") is None, (
        "a stale reason must not sit beside a real probability"
    )
    # The mean-based fields are UNCHANGED by this -- same convention as before.
    assert projection["projected"] == 9.32
    assert projection["edge_vs_line"] == 7.32


def test_totals_at_market_line_gets_a_real_probability_and_edge():
    row = _row("totals", line=164.5, consensus=_TOTALS_CONSENSUS, sides=_TOTALS_SIDES)
    index = _index(total=163.08, p_total_over=0.49, sim_market_total=164.5)
    attach_wnba_game_projections([row], index)
    projection = row["projection"]

    assert projection["model_prob_over"] == 0.49
    assert projection["edge_vs_market_pct"] == -1.0
    assert projection.get("probability_unavailable_reason") is None


def test_alt_line_stays_null_with_an_honest_alternate_line_reason():
    # `#263`'s whole point: the sim priced ONE line (2.0), this row asks about
    # a DIFFERENT one (1.5, a spreads_alt row) -- the 3-point quantile summary
    # cannot answer that, so this must stay a blank, never a fabricated number.
    row = _row("spreads", line=1.5, consensus=_SPREADS_CONSENSUS, sides=_SPREADS_SIDES)
    index = _index(margin=9.32, p_home_cover=0.30, sim_market_home_spread=2.0)
    attach_wnba_game_projections([row], index)
    projection = row["projection"]

    assert projection["model_prob_over"] is None
    assert projection["edge_vs_market_pct"] is None
    reason = projection["probability_unavailable_reason"]
    assert "alternate line" in reason
    assert "2" in reason, "the reason should name the line the sim DID price"
    # The old, now-false-for-main-lines reason must not appear here either --
    # this IS still an honest "no distribution" statement, just a more precise
    # one; the assertion below is really about it not silently reverting.
    assert "not a distribution" not in reason
    # Mean-based fields still populate for an alt line -- only the
    # probability/edge terms are gated.
    assert projection["projected"] == 9.32
    assert projection["edge_vs_line"] == 7.82


def test_sim_line_absent_keeps_the_original_mean_only_reason():
    # An OLDER `game_cards` row, written before `#263` -- no sim_market_* at
    # all. Must degrade to decision 3's exact original behaviour, not the new
    # alternate-line wording (there is no "own line" to contrast against).
    row = _row("totals", line=161.5, consensus=_TOTALS_CONSENSUS, sides=_TOTALS_SIDES)
    index = _index(total=163.5)  # no p_total_over / sim_market_total supplied
    attach_wnba_game_projections([row], index)
    projection = row["projection"]

    assert projection["model_prob_over"] is None
    assert projection["probability_unavailable_reason"] == "sim ships a total mean, not a distribution"


def test_market_line_priced_but_one_sided_book_reports_why():
    # At the sim's own line, but the BOOK only quotes one side -- a different
    # rejection than the mean-only one, and it must say so via the SAME
    # `_edge_unavailable_reason` every other sport's game market uses, not a
    # bespoke sixth phrasing.
    row = _row("spreads", line=2.0, consensus={"home": -110}, sides=["home"])
    index = _index(margin=9.32, p_home_cover=0.30, sim_market_home_spread=2.0)
    attach_wnba_game_projections([row], index)
    projection = row["projection"]

    assert projection["model_prob_over"] == 0.3, "the sim probability still attaches -- only the EDGE is refused"
    assert projection["edge_vs_market_pct"] is None
    assert "one-sided market" in projection["edge_unavailable_reason"]


def test_live_market_suppresses_the_edge_even_at_market_line():
    # `live_edge_unavailable_reason` (imported, not reimplemented) must fire
    # here exactly as it does for every other sport's game market: a pregame
    # sim priced against a re-priced live market is not an edge.
    row = _row(
        "totals",
        line=164.5,
        consensus=_TOTALS_CONSENSUS,
        sides=_TOTALS_SIDES,
        game_state="live",
    )
    index = _index(total=163.08, p_total_over=0.49, sim_market_total=164.5)
    attach_wnba_game_projections([row], index)
    projection = row["projection"]

    assert projection["model_prob_over"] == 0.49, "the sim probability itself is not suppressed, only the edge"
    assert projection["edge_vs_market_pct"] is None
    assert "pregame projection" in projection["edge_unavailable_reason"]


def test_h2h_falls_back_to_the_margin_transform_when_no_sim_probability_exists():
    # `basketball-model-owner`'s question (sim p_home_win vs _margin_win_prob)
    # is now ANSWERED (`6933d263`): p_home_win is primary when present. This
    # is the fallback half -- a game with the OTHER #263 fields populated
    # (p_home_cover, sim_market_home_spread -- both spreads/totals concerns,
    # irrelevant to h2h) but no p_home_win at all must still degrade to the
    # margin transform exactly as before, not silently produce no projection.
    row = _row("h2h")
    index = _index(margin=7.5, p_home_cover=0.9, sim_market_home_spread=2.0)
    attach_wnba_game_projections([row], index)
    projection = row["projection"]

    assert projection["basis"] == "margin_win_prob"
    assert projection.get("edge_vs_market_pct") is None
    assert "producer does not compute" in projection["edge_unavailable_reason"]


def test_h2h_prefers_the_sims_real_win_probability_when_present():
    # The answered half. `p_home_win` is a per-game empirical Monte Carlo
    # estimate -- when a completed sim reached this game, it is PRIMARY over
    # the fixed-scale margin transform, per `basketball-model-owner`'s call.
    row = _row("h2h")
    index = _index(margin=7.5, p_home_win=0.82)
    attach_wnba_game_projections([row], index)
    projection = row["projection"]

    assert projection["model_prob_over"] == 0.82, "must read the sim's own probability, not re-derive it from the mean"
    assert projection["basis"] == "sim_win_probability"
    assert projection["side"] == HOME
    # The edge-withholding policy is UNCHANGED by the source improving --
    # source quality and validation status are different questions (see the
    # module's own comment on this).
    assert projection.get("edge_vs_market_pct") is None
    assert "producer does not compute" in projection["edge_unavailable_reason"]


def test_h2h_sim_probability_of_zero_is_not_mistaken_for_absent():
    # `entry.get("p_home_win")` returning `0.0` is a REAL, legitimate
    # probability (a completely one-sided sim result), not "missing" --
    # `is not None`, not truthiness, is what the join must test on. A naive
    # `if sim_prob_home:` would silently fall back to the margin transform
    # here and this test would catch it.
    row = _row("h2h")
    index = _index(margin=-25.0, p_home_win=0.0)
    attach_wnba_game_projections([row], index)
    projection = row["projection"]

    assert projection["model_prob_over"] == 0.0
    assert projection["basis"] == "sim_win_probability"


# --- load_wnba_game_projections: reads the REAL game_cards column names ----
#
# The exact gap that shipped a real bug: this module's `entry` dict key is
# `sim_market_home_spread`, but every existing test above builds a
# WnbaGameProjectionIndex BY HAND and never exercises the loader's actual
# `row.get(...)` calls -- so a mismatch between that internal key and the
# real CSV column name (`basketball-model-owner` shipped `market_home_spread`,
# no `sim_` prefix) would pass every test above while being silently dead in
# production. This is the loader's parse path, not the join's.


def _patch_game_cards_rows(monkeypatch, rows):
    monkeypatch.setattr(
        "syndicate.features.wnba.cards._load_game_cards_csv_rows_from_keyvalue",
        lambda selected_date: rows,
    )


def test_loader_reads_the_real_column_names_not_the_internal_key_names(monkeypatch):
    # Shaped exactly like the real game_cards_<date>.csv header
    # (_GAME_CARDS_HEADER_ORDER in refresh_wnba_oddsapi_props.py, confirmed
    # against the landed producer commit `6933d263`): market_home_spread /
    # market_total, NOT sim_market_home_spread / sim_market_total.
    row = {
        "home_team": HOME,
        "visitor_team": AWAY,
        "home_tri": "LVA",
        "away_tri": "WAS",
        "pred_margin": "7.5",
        "pred_total": "163.5",
        "p_home_win": "0.82",
        "p_home_cover": "0.59",
        "p_total_over": "0.6",
        "market_home_spread": "-10.5",
        "market_total": "169.5",
    }
    _patch_game_cards_rows(monkeypatch, [row])
    index = load_wnba_game_projections("2026-08-19")

    assert index.games == 1
    entry = index.lookup(HOME, AWAY)
    assert entry is not None
    assert entry["p_home_win"] == 0.82
    assert entry["p_home_cover"] == 0.59
    assert entry["p_total_over"] == 0.6
    # The internal key stays `sim_market_*` -- only the SOURCE column changed.
    assert entry["sim_market_home_spread"] == -10.5
    assert entry["sim_market_total"] == 169.5


def test_loader_degrades_gracefully_on_a_row_written_before_263(monkeypatch):
    # An older game_cards row predating this column set. DictReader + .get()
    # on a real CSV returns "" for a missing column, not KeyError -- and
    # _as_float("") is None, which is decision 3's original, correct blank.
    row = {
        "home_team": HOME,
        "visitor_team": AWAY,
        "pred_margin": "7.5",
        "pred_total": "163.5",
    }
    _patch_game_cards_rows(monkeypatch, [row])
    index = load_wnba_game_projections("2026-08-19")

    entry = index.lookup(HOME, AWAY)
    assert entry is not None
    assert entry["p_home_win"] is None
    assert entry["sim_market_home_spread"] is None

    # And the full join still degrades correctly through to the margin
    # transform -- the end-to-end path, not just the loader in isolation.
    row_h2h = _row("h2h")
    attach_wnba_game_projections([row_h2h], index)
    assert row_h2h["projection"]["basis"] == "margin_win_prob"
