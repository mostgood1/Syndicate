"""An empty live-gameline index must say WHY it is empty.

MEASURED 2026-08-25 04:21Z, and the reading was WRONG:

    LIVE_GAMELINE_JOIN sport=wnba index=0 considered=184 projected=0
      withheld=184 why={'no_live_gameline_projection': 166, ...}

184 board rows in a live game state, asking a snapshot that yielded nothing. I
read that as "WNBA has no live model wired". It does. `live_lens_loop` builds
the WNBA lens every 60 seconds -- `TICK_COMPLETE results={'wnba': True}` on
live-odds-worker at 04:24:08Z, same slate, three minutes later.

What is conditional is the STAMP (`wnba/cards.py:1381`):

    source = "live_projection" if (is_live and live_margin is not None
                                   and elapsed_min is not None) else "pregame"

`live_gameline_from_lens` accepts only `live_projection` for WNBA, so any one
of the three failing publishes a healthy snapshot that is correctly refused --
and it looked identical to an absent producer. The third is a documented hole:
the clock blanks between periods, so `elapsed_min` is None and the lane reverts
to `pregame` for the whole break (`wnba/cards.py:1345`, observed 2026-08-21
IND@DAL, ~20 minutes).

These pin the distinction the counter could not make.
"""

from __future__ import annotations

from syndicate.features.shared.live_gameline_join import build_live_gameline_index


def _snapshot(source: str, *, prob: float | None = 0.62) -> dict:
    return {
        "games": [
            {
                "away": "Chicago Sky",
                "home": "Dallas Wings",
                "gameLens": [
                    {"key": "live", "source": source, "modelHomeWinProb": prob},
                ],
            }
        ]
    }


def test_a_pregame_stamp_is_refused_and_SAYS_it_saw_a_pregame_stamp():
    """The WNBA case. The producer ran, the snapshot is real, the lane is
    `pregame`, and the join is right to refuse it -- but the old zero could not
    tell that apart from nothing being published at all."""
    diag: dict = {}
    index = build_live_gameline_index(
        _snapshot("pregame"), sources=("live_projection",), sport="wnba", diagnostics=diag
    )

    assert index == {}
    assert diag["games_in_snapshot"] == 1
    assert diag["indexed"] == 0
    assert diag["skipped_no_accepted_lane"] == 1
    # THE DISCRIMINATOR. A producer that is not wired shows `{}` here; one that
    # is wired and not currently live shows what it actually stamped.
    assert diag["sources_seen"] == {"pregame": 1}
    assert diag["accepted_sources"] == ["live_projection"]


def test_an_accepted_stamp_indexes_and_is_counted():
    diag: dict = {}
    index = build_live_gameline_index(
        _snapshot("live_projection"), sources=("live_projection",), sport="wnba", diagnostics=diag
    )

    assert len(index) == 1
    assert diag["indexed"] == 1
    assert diag["skipped_no_accepted_lane"] == 0
    assert diag["sources_seen"] == {"live_projection": 1}


def test_no_snapshot_at_all_is_a_DIFFERENT_answer_from_a_refused_stamp():
    """The two states that used to look alike, now named apart."""
    diag: dict = {}
    assert build_live_gameline_index(None, sport="wnba", diagnostics=diag) == {}
    assert diag["reason"] == "snapshot_is_not_a_mapping"
    assert diag["sources_seen"] == {}

    diag2: dict = {}
    assert build_live_gameline_index({"games": "nope"}, sport="wnba", diagnostics=diag2) == {}
    assert diag2["reason"] == "snapshot_carries_no_games_list"


def test_a_lane_with_no_probability_is_counted_where_it_actually_failed():
    """Stamp accepted, probability absent -- a producer half-working, which is
    a third state again and belongs to the producer, not the join."""
    diag: dict = {}
    index = build_live_gameline_index(
        _snapshot("live_projection", prob=None),
        sources=("live_projection",), sport="wnba", diagnostics=diag,
    )

    assert index == {}
    assert diag["skipped_no_accepted_lane"] == 1
    # The stamp WAS live. So `sources_seen` exonerates the state machine and
    # points at the probability, which is the opposite conclusion from the
    # `pregame` case above and was indistinguishable before.
    assert diag["sources_seen"] == {"live_projection": 1}


def test_mlb_is_untouched_by_the_diagnostic():
    """Passing no `diagnostics` must behave exactly as before -- MLB's index is
    the one path that was working and it is not part of this change."""
    index = build_live_gameline_index(
        {"games": [{"matchup": {"away": "Chicago Cubs", "home": "Cincinnati Reds"},
                    "gameLens": [{"key": "live", "source": "live_mc",
                                  "modelHomeWinProb": 0.55, "simsRun": 120}]}]},
        sport="mlb",
    )
    assert len(index) == 1
