"""hockeysim's predictions reach the NHL board WITHOUT inventing a number.

NHL Layer 1 reported `no_projection_source_for_sport` while
`predictions_<date>.csv` was published the whole time -- 14 games on production
for 2026-09-26. `_attach_projections_by_sport` had no `nhl` branch. This is the
join, and these tests exist mostly to pin what it REFUSES.

THE THREE REFUSALS, each from a measured property of the real artifact:

  1. `p_over = 0.0` when hockeysim ran with no market (`anchor_state=no_market`,
     `totals_line_used` empty). Measured 2026-09-26: 14 of 14 games. Publishing
     it says the under is a CERTAINTY. It is mixed within one file
     (2026-09-23: 2 of 4 anchored), so the refusal must be per-GAME.
  2. A probability against a line the model did not price. `p_over` belongs to
     `totals_line_used`; at any other number it answers a different question.
  3. A puckline anywhere but home -1.5. `p_home_pl_-1.5` and `p_away_pl_+1.5`
     are exact complements -- the same bet stated twice -- so P(home covers
     +1.5) is simply not in this artifact.

And the fourth, which is a belt over a defect elsewhere: NHL's board reported
`state: pregame` fifteen hours after puck drop, so `#340`'s live-edge guard
could not fire and this join published `edge_vs_market_pct +54.83` against a
SETTLED market quoting +800/-750. `_started_game_reason` reads `commence_time`
off the row instead.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.nhl import game_projections as gp  # noqa: E402

FUTURE = "2099-01-01T00:00:00Z"
PAST = "2020-01-01T00:00:00Z"


def _entry(**over: object) -> gp.NhlGameProjectionEntry:
    base = dict(
        home="Nashville Predators",
        away="Carolina Hurricanes",
        p_home_ml=0.38405,
        model_total=6.7993,
        model_spread=-0.7918,
        p_home_pl_minus_1_5=0.18635,
        p_over=0.55,
        totals_line_used=6.5,
        anchor_state="anchored",
    )
    base.update(over)
    return gp.NhlGameProjectionEntry(**base)  # type: ignore[arg-type]


def _row(market: str, line: object = None, *, commence: str = FUTURE) -> dict:
    return {
        "market": market,
        "line": line,
        "kind": "game",
        "segment": "full",
        "home_team": "Nashville Predators",
        "away_team": "Carolina Hurricanes",
        "commence_time": commence,
    }


# --------------------------------------------------------------------------
# 1. the zero that must never be published
# --------------------------------------------------------------------------

def test_no_market_zero_is_refused_not_published():
    """`p_over=0.0` with `anchor_state=no_market` must never become a probability."""
    index = gp.NhlGameProjectionIndex(date="2026-09-26")
    index.by_pair[("nashvillepredators", "carolinahurricanes")] = _entry()
    # Simulate the loader's own refusal by going through it:
    row = _row("totals", 6.5)
    entry = _entry(p_over=None, totals_line_used=None, anchor_state="no_market")
    projection = gp._game_projection(row, "totals", entry)
    assert projection is not None
    assert projection["model_prob_over"] is None
    assert "unset 0.0" in projection["probability_unavailable_reason"]
    # The PROJECTION still goes out -- shown, not priced.
    assert projection["projected"] == pytest.approx(6.799, abs=1e-3)


def test_the_loader_applies_the_refusal_per_game(tmp_path, monkeypatch):
    """2026-09-23 had 2 anchored and 2 no_market IN ONE FILE."""
    csv_path = tmp_path / "predictions_2026-09-23.csv"
    csv_path.write_text(
        "home,away,p_home_ml,model_total,model_spread,p_home_pl_-1.5,p_over,totals_line_used,anchor_state\n"
        "Team A,Team B,0.6,6.5,0.4,0.3,0.55,6.5,anchored\n"
        "Team C,Team D,0.4,5.9,-0.2,0.2,0.0,,no_market\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "syndicate.features.nhl.sources.processed_path", lambda *p: csv_path
    )
    index = gp.load_nhl_game_projections("2026-09-23")
    assert index.games == 2
    anchored = index.lookup("Team A", "Team B")
    unanchored = index.lookup("Team C", "Team D")
    assert anchored is not None and unanchored is not None
    assert anchored.p_over == pytest.approx(0.55)
    assert unanchored.p_over is None, "the 0.0 survived the loader"
    assert unanchored.totals_line_used is None


# --------------------------------------------------------------------------
# 2. a probability belongs to ONE line
# --------------------------------------------------------------------------

def test_over_probability_only_at_the_line_the_model_priced():
    entry = _entry(p_over=0.55, totals_line_used=6.5)
    priced = gp._game_projection(_row("totals", 6.5), "totals", entry)
    other = gp._game_projection(_row("totals", 5.5), "totals", entry)
    assert priced["model_prob_over"] == pytest.approx(0.55)
    assert other["model_prob_over"] is None
    assert "different question" in other["probability_unavailable_reason"]
    # But BOTH carry the projection, because a projected total is line-independent.
    assert priced["projected"] == other["projected"]


def test_the_projected_total_is_published_at_every_line():
    entry = _entry()
    for line in (3.5, 5.5, 6.5, 7.5, 8.5):
        projection = gp._game_projection(_row("totals", line), "totals", entry)
        assert projection["projected"] == pytest.approx(6.799, abs=1e-3)
        assert projection["edge_vs_line"] == pytest.approx(6.799 - line, abs=1e-3)


# --------------------------------------------------------------------------
# 3. only one puckline exists in this artifact
# --------------------------------------------------------------------------

def test_puckline_probability_only_at_home_minus_1_5():
    entry = _entry()
    home_lay = gp._game_projection(_row("spreads", -1.5), "spreads", entry)
    home_take = gp._game_projection(_row("spreads", 1.5), "spreads", entry)
    assert home_lay["model_prob_over"] == pytest.approx(0.18635, abs=1e-4)
    assert home_take["model_prob_over"] is None
    assert "same bet restated" in home_take["probability_unavailable_reason"]
    # The projected margin still goes out on both.
    assert home_lay["projected"] == pytest.approx(-0.792, abs=1e-3)
    assert home_take["projected"] == pytest.approx(-0.792, abs=1e-3)


def test_alternate_pucklines_get_no_probability():
    entry = _entry()
    for line in (-2.5, 2.5, -5.5, -6.5):
        projection = gp._game_projection(_row("spreads", line), "spreads", entry)
        assert projection["model_prob_over"] is None, f"line {line} was priced"


# --------------------------------------------------------------------------
# orientation: the failure that publishes a confident number for the OTHER team
# --------------------------------------------------------------------------

def test_a_flipped_game_restates_every_number():
    index = gp.NhlGameProjectionIndex(date="2026-09-26")
    index.by_pair[("nashvillepredators", "carolinahurricanes")] = _entry()
    # Board has the teams the other way round.
    flipped = index.lookup("Carolina Hurricanes", "Nashville Predators")
    assert flipped is not None
    assert flipped.orientation_flipped is True
    assert flipped.p_home_ml == pytest.approx(1.0 - 0.38405)
    assert flipped.model_spread == pytest.approx(0.7918)
    assert flipped.model_total == pytest.approx(6.7993), "a total has no side"
    # THE ONE THAT MATTERS: the away side of a home -1.5 is not its complement.
    assert flipped.p_home_pl_minus_1_5 is None


def test_an_unflipped_game_is_untouched():
    """Negative control: without this, `oriented` could flip everything always."""
    index = gp.NhlGameProjectionIndex(date="2026-09-26")
    index.by_pair[("nashvillepredators", "carolinahurricanes")] = _entry()
    straight = index.lookup("Nashville Predators", "Carolina Hurricanes")
    assert straight.orientation_flipped is False
    assert straight.p_home_ml == pytest.approx(0.38405, abs=1e-4)
    assert straight.p_home_pl_minus_1_5 == pytest.approx(0.18635, abs=1e-4)


# --------------------------------------------------------------------------
# h2h
# --------------------------------------------------------------------------

def test_h2h_publishes_a_probability_and_no_projected_stat():
    projection = gp._game_projection(_row("h2h"), "h2h", _entry())
    assert projection["model_prob_over"] == pytest.approx(0.38405, abs=1e-4)
    assert projection["projected"] is None, "a win probability is not a projected stat"
    assert projection["side"] == "Nashville Predators"


# --------------------------------------------------------------------------
# 4. the started-game belt over the broken game-state join
# --------------------------------------------------------------------------

def _fair_half(_row_arg):
    return 0.5


def test_a_started_game_gets_no_edge():
    """`#340`: a pregame model priced against a market that watched the game."""
    row = _row("h2h", commence=PAST)
    projection = gp._game_projection(row, "h2h", _entry())
    gp._price_against_market(row, projection, _fair_half)
    assert projection["edge_vs_market_pct"] is None
    assert "already started" in projection["edge_unavailable_reason"]


def test_a_pregame_row_still_gets_its_edge():
    """The negative control. Without it the guard could suppress everything."""
    row = _row("h2h", commence=FUTURE)
    projection = gp._game_projection(row, "h2h", _entry())
    gp._price_against_market(row, projection, _fair_half)
    assert projection["edge_vs_market_pct"] == pytest.approx((0.38405 - 0.5) * 100, abs=0.01)


def test_an_unparseable_commence_time_fails_OPEN():
    """Blanking edges on a parsing gap is the harm `live_edge_policy` warns of."""
    assert gp._started_game_reason({"commence_time": "not-a-time"}) is None
    assert gp._started_game_reason({}) is None


# --------------------------------------------------------------------------
# coverage counters
# --------------------------------------------------------------------------

def test_counters_separate_projected_from_priced():
    index = gp.NhlGameProjectionIndex(date="2026-09-26")
    index.by_pair[("nashvillepredators", "carolinahurricanes")] = _entry(
        p_over=None, totals_line_used=None, anchor_state="no_market"
    )
    grid = [_row("h2h"), _row("totals", 6.5), _row("spreads", -1.5)]
    coverage = gp.attach_nhl_game_projections(grid, index, selected_date="2099-01-01")
    assert coverage["supported"] is True
    assert coverage["rows_with_projection"] == 3
    # h2h + puckline are priced; the total is refused for no_market.
    assert coverage["rows_with_probability"] == 2
    assert coverage["rows_unmatched"] == 0
    assert coverage["probability_refusals"], "a refusal must be counted by name"


def test_rows_from_another_date_are_not_counted_as_misses():
    """The NCAAF counting artefact: 9.3% reported vs a re-derived 47%."""
    index = gp.NhlGameProjectionIndex(date="2026-09-26")
    index.by_pair[("nashvillepredators", "carolinahurricanes")] = _entry()
    grid = [_row("h2h", commence="2026-09-27T00:00:00Z")]
    coverage = gp.attach_nhl_game_projections(grid, index, selected_date="2026-09-26")
    assert coverage["rows_considered"] == 0
    assert coverage["rows_unmatched"] == 0


def test_an_unmatched_game_is_counted_not_silently_dropped():
    index = gp.NhlGameProjectionIndex(date="2026-09-26")
    index.by_pair[("someteam", "otherteam")] = _entry()
    coverage = gp.attach_nhl_game_projections([_row("h2h")], index, selected_date="2099-01-01")
    assert coverage["rows_with_projection"] == 0
    assert coverage["rows_unmatched"] == 1


def test_prop_rows_are_left_alone():
    index = gp.NhlGameProjectionIndex(date="2026-09-26")
    index.by_pair[("nashvillepredators", "carolinahurricanes")] = _entry()
    prop = _row("totals", 2.5)
    prop["kind"] = "prop"
    coverage = gp.attach_nhl_game_projections([prop], index, selected_date="2099-01-01")
    assert coverage["rows_considered"] == 0
    assert "projection" not in prop


def test_a_period_market_is_not_given_a_full_game_number():
    index = gp.NhlGameProjectionIndex(date="2026-09-26")
    index.by_pair[("nashvillepredators", "carolinahurricanes")] = _entry()
    period = _row("totals", 1.5)
    period["segment"] = "p1"
    coverage = gp.attach_nhl_game_projections([period], index, selected_date="2099-01-01")
    assert coverage["rows_non_full_segment"] == 1
    assert coverage["rows_with_projection"] == 0
    assert "projection" not in period


def test_a_missing_artifact_is_an_empty_index_not_an_exception(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "syndicate.features.nhl.sources.processed_path", lambda *p: tmp_path / "nope.csv"
    )
    index = gp.load_nhl_game_projections("2026-09-26")
    assert index.games == 0


def test_the_source_is_nhls_own_provenance():
    """Publishing NHL rows under another sport's source name is FORBIDDEN."""
    projection = gp._game_projection(_row("h2h"), "h2h", _entry())
    assert projection["source"] == "nhl_hockeysim"
    assert "smartsim" not in projection["source"]


def test_skill_is_reported_as_unmeasured_not_as_good_or_bad():
    projection = gp._game_projection(_row("h2h"), "h2h", _entry())
    assert projection["model_skill"]["state"] == "unmeasured"
