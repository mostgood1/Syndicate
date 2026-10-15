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
     +1.5) is simply not in this artifact. A spreads row's `line` is the AWAY
     point (`book_grid._canonical_line`, `#262`), so home -1.5 is the row at
     `line = +1.5`. Reading it as the home point put P(away +1.5) on the away
     -1.5 leg: 0.764 against the sim's own away moneyline 0.543, higher in 21
     of 21 away-favoured games (lane sim-gap-ev-study, 09-30..10-14).

The live rule is NOT a fourth refusal here: `#340` is owned by the shared
`live_edge_unavailable_reason`. A per-sport belt lived in this module on
2026-09-26 because NHL game state was wrong (the board said `pregame`
fifteen hours after puck drop, and this join published
`edge_vs_market_pct +54.83` against a settled market). The state defect was
fixed and the belt removed once the shared guard was measured doing the job
alone -- 23 of 23 rows on a finished slate.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.nhl import game_projections as gp  # noqa: E402

# Midday UTC so the CENTRAL date equals the UTC date: the join scopes rows by
# Central slate date (2026-10-02), and midnight UTC is the previous Central evening.
FUTURE = "2099-01-01T18:00:00Z"
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
    # The row's line is the AWAY point: +1.5 is away +1.5 / home -1.5.
    home_lay = gp._game_projection(_row("spreads", 1.5), "spreads", entry)
    away_lay = gp._game_projection(_row("spreads", -1.5), "spreads", entry)
    assert home_lay["model_prob_over"] == pytest.approx(0.18635, abs=1e-4)
    assert home_lay["side"] == "Nashville Predators", "framed on the home team"
    assert away_lay["model_prob_over"] is None
    assert "away -1.5 / home +1.5" in away_lay["probability_unavailable_reason"]
    # The projected margin still goes out on both.
    assert home_lay["projected"] == pytest.approx(-0.792, abs=1e-3)
    assert away_lay["projected"] == pytest.approx(-0.792, abs=1e-3)


def test_alternate_pucklines_get_no_probability():
    entry = _entry()
    for line in (-2.5, 2.5, -5.5, -6.5):
        projection = gp._game_projection(_row("spreads", line), "spreads", entry)
        assert projection["model_prob_over"] is None, f"line {line} was priced"
        assert "alternate lines" in projection["probability_unavailable_reason"]


def test_a_flipped_game_prices_no_puckline_and_says_why():
    """hockeysim's home -1.5 is the board's AWAY -1.5 here, and spreads are
    framed on the board's home -- so it is refused, never re-framed."""
    index = gp.NhlGameProjectionIndex(date="2026-09-26")
    index.by_pair[("nashvillepredators", "carolinahurricanes")] = _entry()
    flipped = index.lookup("Carolina Hurricanes", "Nashville Predators")
    row = dict(_row("spreads", 1.5), home_team="Carolina Hurricanes", away_team="Nashville Predators")
    projection = gp._game_projection(row, "spreads", flipped)
    assert projection["model_prob_over"] is None
    assert "hockeysim's away" in projection["probability_unavailable_reason"]


def test_an_away_favourite_puckline_is_never_priced_above_its_moneyline():
    """THE DEFECT, end to end through the REAL grid, join and board resolver.

    CAR (away) is the -1.5 favourite at CHI. Books quote the main market
    (away -1.5 / home +1.5) and the alternate (home -1.5 / away +1.5); the grid
    files them under away-frame lines -1.5 and +1.5. Before the fix the board
    served away -1.5 at 0.852 -- P(away +1.5) -- above the sim's own away
    moneyline of 0.656, and the market hockeysim prices got nothing.
    """
    from datetime import datetime, timezone

    from syndicate.features.shared import layer2_board as lb
    from syndicate.features.shared.book_grid import build_book_grid

    def quote(selection: str, line: float, price: int) -> dict:
        return {
            "sport": "nhl", "kind": "game", "event_id": "car-chi", "segment": "full",
            "market": "spreads", "player_name": "", "selection": selection, "line": line,
            "price": price, "bookmaker": "draftkings",
            "home_team": "Chicago Blackhawks", "away_team": "Carolina Hurricanes",
            "commence_time": FUTURE, "snapshot_ts": "2099-01-01T11:55:00Z",
        }

    grid = build_book_grid(
        [
            quote("away", -1.5, +150), quote("home", 1.5, -180),   # main
            quote("home", -1.5, +330), quote("away", 1.5, -450),   # alternate
        ],
        now=datetime(2099, 1, 1, 12, tzinfo=timezone.utc),
    )
    index = gp.NhlGameProjectionIndex(date="2099-01-01")
    index.by_pair[("chicagoblackhawks", "carolinahurricanes")] = _entry(
        home="Chicago Blackhawks", away="Carolina Hurricanes",
        p_home_ml=0.344, model_spread=-0.55, p_home_pl_minus_1_5=0.148,
    )
    coverage = gp.attach_nhl_game_projections(grid, index, selected_date="2099-01-01")
    by_line = {float(row["line"]): row for row in grid}
    assert set(by_line) == {-1.5, 1.5}
    # The frame this test rests on: at away-frame -1.5 the AWAY team lays 1.5.
    assert by_line[-1.5]["cells"]["draftkings"]["away"]["line"] == -1.5

    main, alternate = by_line[-1.5], by_line[1.5]
    # away -1.5 / home +1.5: hockeysim cannot price it, so neither leg gets a number.
    assert lb._model_prob_for_side(main, "away") is None
    assert lb._model_prob_for_side(main, "home") is None
    assert main["projection"]["edge_vs_market_pct"] is None
    # home -1.5 / away +1.5: exactly the artifact's two columns.
    assert lb._model_prob_for_side(alternate, "home") == pytest.approx(0.148)
    assert lb._model_prob_for_side(alternate, "away") == pytest.approx(0.852)
    # Winning by two implies winning.
    assert lb._model_prob_for_side(alternate, "home") <= 0.344
    assert coverage["rows_with_probability"] == 1
    assert coverage["probability_refusals"] == {"no cover probability at away -1.5 / home +1.5": 1}


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


def test_the_live_rule_is_DELEGATED_to_the_shared_guard(monkeypatch):
    """`#340` is owned by `live_edge_unavailable_reason`, not re-implemented here.

    A per-sport belt lived in this module on 2026-09-26, reading `commence_time`
    off the row, because NHL game state was WRONG -- the board said `pregame`
    fifteen hours after puck drop, so the shared guard could not fire and this
    join published `edge_vs_market_pct +54.83` against a settled market. The
    state defect was fixed (`0c9b6329`) and the belt was removed once the shared
    guard was MEASURED doing the job alone: 23 of 23 rows on a finished slate.
    """
    monkeypatch.setattr(
        "syndicate.features.shared.live_edge_policy.live_edge_unavailable_reason",
        lambda _row: "game is final: the market is settled",
    )
    row = _row("h2h", commence=PAST)
    projection = gp._game_projection(row, "h2h", _entry())
    gp._price_against_market(row, projection, _fair_half)
    assert projection["edge_vs_market_pct"] is None
    assert projection["edge_unavailable_reason"] == "game is final: the market is settled"


def test_a_pregame_row_still_gets_its_edge(monkeypatch):
    """THE NEGATIVE CONTROL. Without it, a guard that suppressed everything
    would pass the test above and blank the edge column."""
    monkeypatch.setattr(
        "syndicate.features.shared.live_edge_policy.live_edge_unavailable_reason",
        lambda _row: None,
    )
    row = _row("h2h", commence=FUTURE)
    projection = gp._game_projection(row, "h2h", _entry())
    gp._price_against_market(row, projection, _fair_half)
    assert projection["edge_vs_market_pct"] == pytest.approx((0.38405 - 0.5) * 100, abs=0.01)


def test_this_module_carries_NO_live_rule_of_its_own():
    """A belt reintroduced quietly would diverge from `#340` without anyone
    choosing that. If NHL state regresses, fix the STATE JOIN, not this file."""
    import inspect

    assert "_started_game_reason" not in inspect.getsource(gp)
    # Scoped to the EDGE path only. `attach_nhl_game_projections` reads
    # `commence_time` for DATE SCOPING, which is correct and unrelated -- an
    # assertion over the whole module would flag that and teach the next reader
    # to delete the wrong thing.
    pricing = inspect.getsource(gp._price_against_market)
    assert "commence_time" not in pricing, (
        "the edge path is reading a clock again instead of the shared guard"
    )
    assert "live_edge_unavailable_reason" in pricing


# --------------------------------------------------------------------------
# coverage counters
# --------------------------------------------------------------------------

def test_counters_separate_projected_from_priced():
    index = gp.NhlGameProjectionIndex(date="2026-09-26")
    index.by_pair[("nashvillepredators", "carolinahurricanes")] = _entry(
        p_over=None, totals_line_used=None, anchor_state="no_market"
    )
    grid = [_row("h2h"), _row("totals", 6.5), _row("spreads", 1.5)]
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
    # Noon CT on 09-27: genuinely the next slate. (00:00Z on 09-27 would be 7pm CT
    # on 09-26 -- THIS slate -- which is the case the next test pins.)
    grid = [_row("h2h", commence="2026-09-27T17:00:00Z")]
    coverage = gp.attach_nhl_game_projections(grid, index, selected_date="2026-09-26")
    assert coverage["rows_considered"] == 0
    assert coverage["rows_unmatched"] == 0


def test_an_evening_game_belongs_to_its_central_slate_not_the_utc_date():
    """Fleet board 2026-10-02 15:43Z: WPG 7:10p, DAL 8:10p, VGK 9:10p CT carried
    no projection while DET 5:40p and CAR 6:10p did -- all five were in
    `predictions_2026-10-02.csv`. The join read the UTC prefix of commence_time,
    and a 7pm CT puck drop is already the next UTC day."""
    index = gp.NhlGameProjectionIndex(date="2026-10-02")
    index.by_pair[("nashvillepredators", "carolinahurricanes")] = _entry()
    evening = _row("totals", 6.5, commence="2026-10-03T00:10:00Z")   # 7:10pm CT 10-02
    early = _row("totals", 6.5, commence="2026-10-02T22:40:00Z")     # 5:40pm CT 10-02
    coverage = gp.attach_nhl_game_projections([evening, early], index, selected_date="2026-10-02")
    assert coverage["rows_considered"] == 2
    assert coverage["rows_with_projection"] == 2
    assert evening.get("projection") is not None


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
