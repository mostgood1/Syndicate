"""`#514`. The live-scoped soccer captures must run BEFORE the sims, not after.

WHY THIS EXISTS. `_build_soccer_steps` already carries a long comment recording
that its own step list does not reach the end -- reproducibly dying around step
27 of ~50 -- and that the fix was to move the cheap OddsAPI captures ahead of the
expensive `build_soccer_artifacts.py` sims. That reorder was applied to the
PREGAME loops. The live-scoped captures were added afterwards and appended at the
back, so they inherited exactly the starvation the reorder had removed.

They are the steps that can least afford it. A pregame price that misses a cycle
drifts; a live price that misses one is DELETED from the board, because
`opportunity_gate.LIVE_MARKET_MAX_AGE_SECONDS` is 900 seconds and a row whose
game is live and whose quote is older than that is graded `LANE_DEAD`.

Measured in production 2026-08-22 21:06-21:14Z: soccer board quote age p50
23,941s (6.7h), max 49,626s (13.8h), `live_rows` 0-3 of 400 published, while
primeira_liga's own `live_state_2026-08-22.json` reported a match in play.

These tests pin the ORDER, not the contents -- the contents were already right.
"""

from __future__ import annotations

import argparse

import pytest

import scripts.refresh_odds_sources as ros


def _args(**kwargs):
    base = {"date": "2026-08-22", "soccer_leagues": "", "soccer_date": ""}
    base.update(kwargs)
    return argparse.Namespace(**base)


def _names(steps):
    return [step.name for step in steps]


@pytest.fixture
def _one_live_league(monkeypatch):
    monkeypatch.setattr(
        ros, "_soccer_live_scope", lambda date: {"primeira_liga": ["401882923", "401882924"]}
    )


def test_the_live_captures_come_before_every_sim(_one_live_league):
    names = _names(ros._build_soccer_steps(_args()))
    live_odds = names.index("soccer_primeira_liga_odds_live")
    first_sim = min(i for i, n in enumerate(names) if n.endswith("_artifacts"))
    assert live_odds < first_sim, (
        "a run that dies mid-list must lose sims, not live prices -- "
        f"live capture at {live_odds}, first sim at {first_sim}"
    )


def test_the_live_captures_come_before_every_pregame_step(_one_live_league):
    """Not just before the sims. `_soccer_history_step` and the schedule builds
    are also ahead of the cheap captures, and there are up to 10 of each."""
    names = _names(ros._build_soccer_steps(_args()))
    live_indices = [i for i, n in enumerate(names) if n.endswith(("_odds_live", "_props_live", "_live_state"))]
    other_indices = [i for i, n in enumerate(names) if i not in set(live_indices)]
    assert live_indices, "the premise: live steps were emitted at all"
    assert max(live_indices) < min(other_indices)


def test_live_state_polling_is_in_the_live_group(_one_live_league):
    """It WRITES the artifact `_soccer_live_scope` reads. Leaving it at the back
    of a list that does not finish lets the scope this all depends on go stale
    exactly while matches are running."""
    names = _names(ros._build_soccer_steps(_args()))
    first_sim = min(i for i, n in enumerate(names) if n.endswith("_artifacts"))
    live_states = [i for i, n in enumerate(names) if n.endswith("_live_state")]
    assert live_states, "live_state steps must still be emitted"
    assert max(live_states) < first_sim


def test_the_reorder_changed_the_order_and_nothing_else(_one_live_league):
    """Same steps, same call volume -- the whole argument for the move. A reorder
    that quietly added or dropped a step would be a different change wearing this
    one's justification."""
    names = _names(ros._build_soccer_steps(_args()))
    assert len(names) == len(set(names)), "no step may be emitted twice"
    for expected in (
        "soccer_primeira_liga_odds_live",
        "soccer_primeira_liga_props_live",
        "soccer_primeira_liga_live_state",
        "soccer_primeira_liga_odds",
        "soccer_primeira_liga_props",
        "soccer_primeira_liga_artifacts",
        "soccer_primeira_liga_picks",
    ):
        assert expected in names, f"{expected} was lost in the move"


def test_no_live_match_emits_no_live_capture_steps(monkeypatch):
    """The economy. Soccer props are billed per EVENT, so an unscoped 60s live
    refresh is ~90 event calls a tick. Nothing in play must cost nothing."""
    monkeypatch.setattr(ros, "_soccer_live_scope", lambda date: {})
    names = _names(ros._build_soccer_steps(_args()))
    assert not [n for n in names if n.endswith(("_odds_live", "_props_live"))]


def test_the_live_props_step_stays_scoped_to_the_events_in_play(_one_live_league):
    """The per-event scope is what makes the cadence affordable; the reorder must
    not have flattened it into a whole-league call."""
    steps = {step.name: step for step in ros._build_soccer_steps(_args())}
    command = list(steps["soccer_primeira_liga_props_live"].command)
    assert "--event-ids" in command
    assert command[command.index("--event-ids") + 1] == "401882923,401882924"


def test_a_live_league_outside_soccer_leagues_still_gets_its_live_capture(_one_live_league):
    """`--soccer-leagues` narrows the pregame loops; it must not be able to drop a
    league whose match is in play. The launcher's own scope is fixed separately
    (`_due_leagues_for_sport`), but this file must not depend on that having
    worked -- two independent gates, both of which used to say no."""
    names = _names(ros._build_soccer_steps(_args(soccer_leagues="mls")))
    assert "soccer_primeira_liga_odds_live" in names
    assert "soccer_mls_artifacts" in names
    assert "soccer_primeira_liga_artifacts" not in names, "the pregame narrowing still applies"


# ---------------------------------------------------------------------------
# The sim rebuild must not run every 60 seconds for a match in play
# ---------------------------------------------------------------------------


def test_an_in_play_league_drops_its_sim_from_the_live_phase(_one_live_league):
    """`build_soccer_artifacts.py` is the step this function's own comment blames
    for the run not reaching its end, and it ran on every 60s live tick.

    It rebuilds a PREGAME artifact -- schedule and ratings in, projections out --
    so re-running it mid-match produces the same numbers at the cost of the whole
    tick. The board's live view comes from `live_projection_join`, not from here.
    """
    steps = {step.name: step for step in ros._build_soccer_steps(_args())}
    assert steps["soccer_primeira_liga_artifacts"].phases == ("pregame",)


def test_a_league_not_in_play_keeps_its_sim_in_the_live_phase(_one_live_league):
    """Dropping `live` unconditionally would be wrong, and for a reason that is
    easy to miss: the refresh PHASE is global, not per-sport. Soccer sits in
    "live" for the whole of an MLB evening whether or not any soccer is playing,
    so a blanket drop would stop soccer's sims for hours at a time."""
    steps = {step.name: step for step in ros._build_soccer_steps(_args())}
    quiet = [n for n in steps if n.endswith("_artifacts") and "primeira_liga" not in n]
    assert quiet, "the premise: other leagues are in season on this date"
    for name in quiet:
        assert steps[name].phases == ("pregame", "live"), name


def test_with_nothing_in_play_every_sim_keeps_its_live_phase(monkeypatch):
    """The pre-`#514` behaviour, unchanged, whenever no match is running."""
    monkeypatch.setattr(ros, "_soccer_live_scope", lambda date: {})
    steps = [s for s in ros._build_soccer_steps(_args()) if s.name.endswith("_artifacts")]
    assert steps
    assert all(step.phases == ("pregame", "live") for step in steps)


def test_the_live_phase_still_captures_prices_for_the_league_it_stopped_simming(_one_live_league):
    """The trade has to be a trade, not a loss: the league whose sim was dropped
    is exactly the league whose live odds and props are now captured first."""
    live_names = {
        s.name for s in ros._build_soccer_steps(_args()) if "live" in s.phases
    }
    assert "soccer_primeira_liga_odds_live" in live_names
    assert "soccer_primeira_liga_props_live" in live_names
    assert "soccer_primeira_liga_artifacts" not in live_names
