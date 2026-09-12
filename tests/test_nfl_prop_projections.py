"""The NFL prop projection join: reachability first, then correctness.

`model_engine_standard.md` requires a REACHABILITY test before correctness
tests for anything that can be inert -- `off != on`. Here the "off" arm is an
empty index (the state production was in until this join existed: the artifact
published, nothing reading it), and the "on" arm is the same grid against a
real index. `test_off_vs_on_reachability` is that test, and it is first on
purpose.

The fixtures use the EXACT shapes both sides really have, taken from
production on 2026-09-09 rather than invented:

  board row      market "Receiving Yards" (display label, Title Case),
                 player_name "AJ Barner", line 24.5, kind "prop",
                 plus the `sides`/`consensus` pair `_no_vig_over_probability`
                 needs to produce a fair.
  artifact row   market "receiving_yards::aj barner::24.5",
                 sim_projection 0.5565 (a COVER PROBABILITY),
                 projected_value 28.833 (the MEAN -- never interchangeable).
"""

from __future__ import annotations

import pytest

from syndicate.features.shared.nfl_prop_projections import (
    NflPropProjectionIndex,
    attach_nfl_prop_projections,
)


def _artifact_row(market: str, *, sim: float | None = 0.5565, mean: float = 28.833):
    return {
        "market": market,
        "entity": "AJ Barner",
        "game_id": "New England Patriots|Seattle Seahawks",
        "period": "full_game",
        "sim_projection": sim,
        "projected_value": mean,
        "sim_source": "nfl_prior_season_fallback",
        "rate_source": "prior_season_fallback",
        "player_team": "SEA",
    }


def _index(*rows) -> NflPropProjectionIndex:
    index = NflPropProjectionIndex(season=2026, week=1)
    for row in rows:
        index.entries[str(row["market"])] = row
    index.row_count = len(index.entries)
    return index


def _board_row(
    *,
    market: str = "Receiving Yards",
    player: str = "AJ Barner",
    line: float | None = 24.5,
    kind: str = "prop",
    over: int = -110,
    under: int = -110,
):
    """A grid row with a real two-sided consensus, so a fair can be derived."""
    row = {
        "kind": kind,
        "sport": "nfl",
        "market": market,
        "player_name": player,
        "line": line,
        "sides": ["over", "under"],
        "consensus": {"over": over, "under": under},
    }
    return row


# ---------------------------------------------------------------------------
# 1. REACHABILITY -- off != on
# ---------------------------------------------------------------------------


def test_off_vs_on_reachability():
    """An empty index leaves the row EXACTLY as it was; a real one prices it."""
    off_row = _board_row()
    off_coverage = attach_nfl_prop_projections([off_row], NflPropProjectionIndex())
    assert "projection" not in off_row
    assert off_coverage["rows_with_projection"] == 0

    on_row = _board_row()
    on_coverage = attach_nfl_prop_projections(
        [on_row], _index(_artifact_row("receiving_yards::aj barner::24.5"))
    )
    assert on_coverage["rows_with_projection"] == 1
    assert on_row["projection"]["model_prob_over"] == pytest.approx(0.5565, abs=1e-4)
    # THE POINT OF THE WHOLE LANE: a numeric edge, in probability points.
    assert isinstance(on_row["projection"]["edge_vs_market_pct"], float)


@pytest.mark.parametrize("certainty", [0.0, 1.0])
def test_an_exact_certainty_is_refused_on_this_path_not_just_wrapped(certainty):
    """`refuse_published_certainty` on the REAL join, not the AST scan's substring.

    The platform test proves the assignment line names the guard; this proves a
    0/N or N/N sim cover probability actually arrives unpriced, with the edge
    derived from it cleared and the projected MEAN kept.
    """
    row = _board_row()
    coverage = attach_nfl_prop_projections(
        [row], _index(_artifact_row("receiving_yards::aj barner::24.5", sim=certainty))
    )
    projection = row["projection"]
    assert coverage["rows_with_projection"] == 1
    assert projection["model_prob_over"] is None
    assert projection["model_prob_over_refused"] == "exact_certainty"
    assert projection["model_prob_over_refused_value"] == certainty
    assert projection.get("edge_vs_market_pct") is None
    assert projection["edge_unavailable_reason"]
    assert projection["projected"] == pytest.approx(28.833)


# ---------------------------------------------------------------------------
# 2. THE LINE IS PART OF THE JOIN
# ---------------------------------------------------------------------------


def test_line_is_part_of_the_key():
    """Two lines for one player must take their OWN probability.

    This is the defect `_nfl_prop_join_market_key` was changed on 2026-09-08 to
    fix -- 371 of 371 multi-line groups had been showing one probability. A
    line-blind join here would reintroduce it one layer up.
    """
    index = _index(
        _artifact_row("receiving_yards::aj barner::24.5", sim=0.5565),
        _artifact_row("receiving_yards::aj barner::27.5", sim=0.4978),
    )
    low = _board_row(line=24.5)
    high = _board_row(line=27.5)
    attach_nfl_prop_projections([low, high], index)
    assert low["projection"]["model_prob_over"] == pytest.approx(0.5565, abs=1e-4)
    assert high["projection"]["model_prob_over"] == pytest.approx(0.4978, abs=1e-4)
    assert low["projection"]["model_prob_over"] != high["projection"]["model_prob_over"]


def test_line_not_in_artifact_is_unmatched_not_approximated():
    """A line the model never priced is REFUSED, never snapped to a near one."""
    row = _board_row(line=26.5)
    coverage = attach_nfl_prop_projections(
        [row], _index(_artifact_row("receiving_yards::aj barner::24.5"))
    )
    assert "projection" not in row
    assert coverage["unmatched_key_rows"] == 1
    assert coverage["rows_with_projection"] == 0


# ---------------------------------------------------------------------------
# 3. NO NEUTRAL DEFAULTS -- every refusal is named
# ---------------------------------------------------------------------------


def test_missing_probability_never_falls_back_to_the_mean():
    """`projected_value` is 28.8 YARDS. It must never land in a probability."""
    row = _board_row()
    coverage = attach_nfl_prop_projections(
        [row], _index(_artifact_row("receiving_yards::aj barner::24.5", sim=None))
    )
    assert "projection" not in row
    assert coverage["no_probability_rows"] == 1


def test_unsupported_market_is_counted_and_named():
    """The raw OddsAPI key is reported, not silently aliased.

    Measured on the served board 2026-09-09: 24 rows arrived as
    `player_receptions` and 4 as `player_pass_tds` while 1,394 carried the
    display label. Reporting it is what makes the producer inconsistency
    findable; an alias map would hide it.
    """
    row = _board_row(market="player_receptions")
    coverage = attach_nfl_prop_projections([row], _index(_artifact_row("receptions::aj barner::2.5")))
    assert "projection" not in row
    assert coverage["unsupported_market_rows"] == 1
    assert coverage["unsupported_markets"]["player_receptions"] == 1


def test_lined_market_without_a_line_is_refused_but_anytime_td_is_not():
    """`anytime_td` legitimately has no line; every other market needs one."""
    lined = _board_row(market="Receiving Yards", line=None)
    td = _board_row(market="Anytime TD", line=None)
    coverage = attach_nfl_prop_projections(
        [lined, td], _index(_artifact_row("anytime_td::aj barner", sim=0.3457, mean=0.3457))
    )
    assert "projection" not in lined
    assert coverage["no_line_rows"] == 1
    assert td["projection"]["model_prob_over"] == pytest.approx(0.3457, abs=1e-4)


def test_game_rows_are_not_touched():
    """Only `kind == "prop"`. The game-line join owns everything else."""
    row = _board_row(market="h2h", kind="game", line=None)
    coverage = attach_nfl_prop_projections([row], _index(_artifact_row("receiving_yards::aj barner::24.5")))
    assert "projection" not in row
    assert coverage["rows_considered"] == 0


# ---------------------------------------------------------------------------
# 4. THE EDGE IS AGAINST A DE-VIGGED FAIR, AND SAYS SO WHEN IT CANNOT BE
# ---------------------------------------------------------------------------


def test_edge_is_priced_against_the_devigged_fair_not_the_raw_price():
    """At -110/-110 the fair is 0.5 exactly, so the edge is model - 0.5.

    Pricing against the RAW -110 implied (0.5238) instead would understate the
    edge by half the hold -- `#238`'s finding, and the reason this routes
    through `_no_vig_over_probability` rather than the quoted price.
    """
    row = _board_row(over=-110, under=-110)
    attach_nfl_prop_projections([row], _index(_artifact_row("receiving_yards::aj barner::24.5", sim=0.5565)))
    projection = row["projection"]
    assert projection["market_fair_prob_over"] == pytest.approx(0.5, abs=1e-9)
    assert projection["edge_vs_market_pct"] == pytest.approx((0.5565 - 0.5) * 100, abs=0.01)


def test_one_sided_market_gets_a_null_edge_with_a_reason_never_a_silent_gap():
    """`#426`'s invariant: the key is always SET and a null carries a reason."""
    row = _board_row()
    row["sides"] = ["over"]
    row["consensus"] = {"over": -110}
    attach_nfl_prop_projections([row], _index(_artifact_row("receiving_yards::aj barner::24.5")))
    projection = row["projection"]
    assert projection["market_fair_prob_over"] is None
    assert "edge_vs_market_pct" in projection
    assert projection["edge_vs_market_pct"] is None
    assert projection.get("edge_unavailable_reason")


# ---------------------------------------------------------------------------
# 5. PROVENANCE -- a reader can see which rate produced the number
# ---------------------------------------------------------------------------


def test_projection_carries_its_rate_provenance():
    row = _board_row()
    attach_nfl_prop_projections([row], _index(_artifact_row("receiving_yards::aj barner::24.5")))
    projection = row["projection"]
    assert projection["source"] == "nfl_prop_model"
    assert projection["sim_source"] == "nfl_prior_season_fallback"
    assert projection["rate_source"] == "prior_season_fallback"
    # The mean is carried for the display column, distinctly from the probability.
    assert projection["projected"] == pytest.approx(28.833, abs=1e-3)
    assert projection["projected"] != projection["model_prob_over"]


def test_coverage_names_which_artifact_answered():
    """An empty join must be attributable to a wrong week, not read as
    'the model has no view on these players'."""
    coverage = attach_nfl_prop_projections([_board_row()], _index(_artifact_row("x::y::1.5")))
    assert coverage["artifact_season"] == 2026
    assert coverage["artifact_week"] == 1
    assert coverage["artifact_rows"] == 1


# ---------------------------------------------------------------------------
# 6. THE WEEK-PINNING FAILURE MODE
# ---------------------------------------------------------------------------


def test_artifact_scan_recovers_when_the_resolved_week_is_empty(monkeypatch):
    """A wrong resolved week must not read as 'the model has no view'.

    `#471` shipped exactly this once (NFL week self-pinning to 1). Here
    `default_week` answers a week with no artifact, and the scan finds the one
    that exists -- reporting `resolution == "artifact_scan"` so the fallback is
    never mistaken for a clean primary resolution.
    """
    from syndicate.features.shared import nfl_prop_projections as mod

    calls: list[tuple[int, int]] = []

    def fake_reader(season: int, week: int):
        calls.append((season, week))
        if (season, week) == (2026, 1):
            return [_artifact_row("receiving_yards::aj barner::24.5")]
        return None

    monkeypatch.setattr(mod, "_resolve_season_week", lambda s, w: (2026, 9))
    import syndicate.features.nfl.props as props_mod

    monkeypatch.setattr(props_mod, "read_nfl_prop_projection_artifact", fake_reader)

    index = mod.load_nfl_prop_projections("2026-09-09")
    assert index.row_count == 1
    assert (index.season, index.week) == (2026, 1)
    assert index.resolution == "artifact_scan"
    assert (2026, 9) in calls  # the resolved week WAS tried first


def test_explicit_season_week_never_falls_back(monkeypatch):
    """An explicit ask must answer about THAT week or not at all."""
    from syndicate.features.shared import nfl_prop_projections as mod
    import syndicate.features.nfl.props as props_mod

    monkeypatch.setattr(
        props_mod,
        "read_nfl_prop_projection_artifact",
        lambda season, week: [_artifact_row("receiving_yards::aj barner::24.5")]
        if (season, week) == (2026, 1)
        else None,
    )
    index = mod.load_nfl_prop_projections("2026-09-09", season=2026, week=9)
    assert index.row_count == 0
    assert (index.season, index.week) == (2026, 9)
    assert index.resolution == "resolved"


def test_season_candidates_lead_with_the_dates_own_year():
    """The regression that the reachability run caught.

    `latest_season()` answered 2025 on 2026-09-09 while the artifact on disk was
    `nfl_prop_projections_2026_wk1.json`; a scan over `[resolved, resolved - 1]`
    could never reach 2026 and the join silently found nothing.
    """
    from syndicate.features.shared.nfl_prop_projections import _season_candidates

    assert _season_candidates(2025, "2026-09-09")[0] == 2026
    # January belongs to the PREVIOUS season's playoffs.
    assert _season_candidates(2025, "2027-01-11")[0] == 2026
    # No date still works off the resolved season, and reaches season+1.
    assert 2026 in _season_candidates(2025, None)
    # No duplicates, so the probe stays bounded.
    candidates = _season_candidates(2025, "2026-09-09")
    assert len(candidates) == len(set(candidates))
