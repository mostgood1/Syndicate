"""MLB props: WHY a row carries no projection, split by cause.

WHY THIS FILE EXISTS. `attach_projections` reported `rows_considered` and
`rows_with_projection` and nothing about the gap between them. A bare miss count
cannot distinguish the two answers that matter:

  * the sim has no view on this player/market  -- an honest blank, and
  * the NAME did not match                     -- a broken join wearing a blank's clothes.

Soccer had the identical shape and it was hiding roughly half that sport's model
coverage. What settled it there on 2026-09-03 was a PAIR of numbers:
`player_no_roster=0` next to `player_name_miss=7020`. The first proves the
rosters were present; only then does the second read as a join defect rather
than a producer gap -- and it was first reported as a producer gap, because only
the second number existed.

MLB props are Phase 1 of the edge plan and 300 of 947 settled bets at -15.35%.
That figure is unreadable while an unknown share of prop rows may have been
priced with no model view because a name did not match. This file does not claim
that share is large. It makes it measurable, which is the finding: before this,
the number could not be obtained at all.
"""

from __future__ import annotations

from syndicate.features.shared.prop_projections import (
    PropProjectionIndex,
    attach_projections,
)


def _index() -> PropProjectionIndex:
    """One pitcher and two hitters, reached by three different containers.

    `knows_player` has to answer for all three (`_pitchers`, `_hitter_means`,
    `_hitters`) or a real player reads as a name miss and the counter blames the
    join for the sim's silence -- the exact inversion it exists to prevent.
    """
    index = PropProjectionIndex()
    index.ingest_game(
        {
            "pitcher_props": {
                "111": {"outs_dist": {str(v): 1 for v in range(15, 25)}, "outs_mean": 19.5}
            },
            "hitter_props_likelihood_topn": {
                "total_bases_2plus": [
                    {"name": "Seiya Suzuki", "p_tb_2plus": 0.51, "p_tb_2plus_cal": 0.445,
                     "tb_mean": 1.646}
                ]
            },
            "hitter_hr_likelihood_all": {
                "overall": [
                    {"name": "Aaron Judge", "p_hr_1plus": 0.19, "p_hr_1plus_cal": 0.17,
                     "hr_mean": 0.21}
                ]
            },
        },
        pitcher_names={"111": "Paul Skenes"},
    )
    return index


def _row(player, market="batter_total_bases", line=1.5, **kw):
    row = {
        "market": market,
        "player_name": player,
        "line": line,
        "sides": ["over", "under"],
        "consensus": {"over": -110, "under": -110},
    }
    row.update(kw)
    return row


def test_a_name_the_index_never_heard_of_is_a_JOIN_miss():
    coverage = attach_projections([_row("Nobody At All")], _index())
    assert coverage["player_unmatched_name"] == 1
    assert coverage["player_no_projection"] == 0
    assert coverage["rows_with_projection"] == 0


def test_a_KNOWN_name_with_no_answer_is_not_blamed_on_the_join():
    """THE DISCRIMINATING CASE.

    Seiya Suzuki is in the index; `not_a_market` is not. Both this row and the
    one above return None from `project`, and before the split they were the
    same number. If `knows_player` were wrong -- or if the counter simply
    incremented on every None -- this test is the only one that fails, because
    it is the only place the two causes disagree.
    """
    coverage = attach_projections([_row("Seiya Suzuki", market="not_a_market")], _index())
    assert coverage["player_no_projection"] == 1
    assert coverage["player_unmatched_name"] == 0


def test_every_container_counts_as_known():
    """A pitcher (`_pitchers`), a means hitter (`_hitter_means`) and a bucket-only
    hitter (`_hitters`) each asked for a market they have no answer for."""
    rows = [
        _row("Paul Skenes", market="not_a_market"),
        _row("Seiya Suzuki", market="not_a_market"),
        _row("Aaron Judge", market="not_a_market"),
    ]
    coverage = attach_projections(rows, _index())
    assert coverage["player_unmatched_name"] == 0, "a real player was called a name miss"
    assert coverage["player_no_projection"] == 3


def test_an_accented_name_is_not_a_miss():
    """`knows_player` must normalise exactly as `project` does.

    `_norm_name` folds accents, so the board's "José Ramírez" and a roster's
    "Jose Ramirez" are the same key. A `knows_player` that skipped that fold
    would report a name miss on a player the very next line then projects --
    a counter that contradicts its own attach.
    """
    index = PropProjectionIndex()
    index.ingest_game(
        {
            "hitter_props_likelihood_topn": {
                "total_bases_2plus": [
                    {"name": "Jose Ramirez", "p_tb_2plus_cal": 0.40, "tb_mean": 1.4}
                ]
            }
        }
    )
    assert index.knows_player("José Ramírez") is True
    coverage = attach_projections([_row("José Ramírez")], index)
    assert coverage["player_unmatched_name"] == 0
    assert coverage["rows_with_projection"] == 1


def test_the_causes_ACCOUNT_for_every_dropped_row():
    """Projected + the three causes == considered, exactly.

    Soccer's accounting was reported as "106,450 unaccounted (75.5%)" and was
    wrong three separate ways before it closed to zero. An identity asserted in
    a test is the cheap version of that: a future drop point added without a
    counter fails here rather than silently reopening the gap.
    """
    rows = [
        _row("Seiya Suzuki"),                              # projects
        _row("Nobody At All"),                             # name miss
        _row("Aaron Judge", market="not_a_market"),        # known, no answer
        {"market": "h2h", "player_name": None, "sides": ["home"]},   # game, no sim
    ]
    coverage = attach_projections(rows, _index())
    assert coverage["rows_considered"] == 4
    assert (
        coverage["rows_with_projection"]
        + coverage["player_unmatched_name"]
        + coverage["player_no_projection"]
        + coverage["game_no_projection"]
    ) == coverage["rows_considered"]
    assert coverage["player_rows_considered"] + coverage["game_rows_considered"] == 4


def test_the_miss_RATE_uses_the_player_denominator_not_the_legacy_alias():
    """`player_rows` is a LEGACY ALIAS for every row, game markets included.

    One player row that misses, alongside three game rows, is a 100% player
    name-miss rate, not 25%. Dividing by the alias would understate it by the
    whole game-market book -- and the alias is the key whose NAME says player.
    """
    rows = [_row("Nobody At All")] + [
        {"market": "h2h", "player_name": None, "sides": ["home"]} for _ in range(3)
    ]
    coverage = attach_projections(rows, _index())
    assert coverage["player_rows_considered"] == 1
    assert coverage["player_rows"] == 4, "guard: the alias still means every row"
    assert coverage["pct_player_name_missed"] == 100.0


def test_an_empty_grid_reports_zero_rather_than_dividing_by_it():
    coverage = attach_projections([], _index())
    assert coverage["pct_player_name_missed"] == 0.0
    assert coverage["player_rows_considered"] == 0
