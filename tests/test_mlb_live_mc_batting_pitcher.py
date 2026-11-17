"""MLB live MC: which pitcher does the BATTING team take the mound with next?

Lane `mlb-live-mc-batting-pitcher` (side finding of todo #814).

`_live_mc_projection` (`live_lens_port/app_slice.py`) passes `estimate_live` only
the FIELDING team's current pitcher. `_build_initial_state` (`sim_engine/live_mc.py`)
seeds the other team with `_default_pitcher_id(roster)`, its STARTER. So once a
starter has been pulled, every sim started while his team is batting puts him
back on the mound for his team's next fielding half, at his own pitch count.

These tests pin the ENGINE side of that with toy rosters (no artifact, no
network): an unset batting-side id means "the starter", and a set one is honoured.
They pass today; that is the confirmation of the defect, since the caller never
sets the batting side's id.
"""

from __future__ import annotations

from syndicate.features.mlb.sim_engine.live_mc import (
    LiveSituation,
    _build_initial_state,
    estimate_live,
)
from syndicate.features.mlb.sim_engine.models import (
    BaseState,
    BatterProfile,
    GameConfig,
    Handedness,
    Lineup,
    ManagerProfile,
    PitcherProfile,
    PitchType,
    Player,
    Team,
    TeamRoster,
)

SIMS = 120


def _player(pid: int, position: str) -> Player:
    return Player(mlbam_id=pid, full_name=f"P{pid}", primary_position=position,
                  bat_side=Handedness.R, throw_side=Handedness.R)


def _batter(pid: int) -> BatterProfile:
    return BatterProfile(player=_player(pid, "1B"), k_rate=0.22, bb_rate=0.08,
                         hbp_rate=0.008, hr_rate=0.035, inplay_hit_rate=0.275)


def _pitcher(pid: int, stamina: int) -> PitcherProfile:
    return PitcherProfile(
        player=_player(pid, "P"), k_rate=0.22, bb_rate=0.08, hbp_rate=0.008,
        hr_rate=0.035, inplay_hit_rate=0.27,
        arsenal={PitchType.FF: 0.55, PitchType.SL: 0.25, PitchType.CH: 0.20},
        stamina_pitches=stamina,
    )


def _roster(team_id: int, abbr: str, base: int) -> TeamRoster:
    return TeamRoster(
        team=Team(team_id=team_id, name=abbr, abbreviation=abbr),
        manager=ManagerProfile(),
        lineup=Lineup(
            batters=[_batter(base + i) for i in range(1, 10)],
            pitcher=_pitcher(base + 100, stamina=95),
            bench=[],
            bullpen=[_pitcher(base + 200 + i, stamina=25) for i in range(8)],
        ),
    )


AWAY = _roster(1, "AWY", 100000)
HOME = _roster(2, "HOM", 200000)
AWAY_SP = 100100
HOME_SP = 200100
HOME_RELIEVER = 200203  # in HOME's bullpen; entered in the 3rd


def _situation(home_pitcher_id=None) -> LiveSituation:
    """Bottom of the 3rd, HOME batting. HOME's starter left after 38 pitches
    (an early exit: injury or a blowup) and HOME's reliever has thrown 12. AWAY's
    starter is on the mound for AWAY, the fielding team, so the caller passes him."""
    return LiveSituation(
        inning=3, top=False, outs=0, bases=BaseState.EMPTY,
        away_score=4, home_score=1,
        away_next_batter_index=0, home_next_batter_index=3,
        away_pitcher_id=AWAY_SP,
        home_pitcher_id=home_pitcher_id,
        pitcher_pitch_count={AWAY_SP: 41, HOME_SP: 38, HOME_RELIEVER: 12},
        pitcher_batters_faced={AWAY_SP: 11, HOME_SP: 12, HOME_RELIEVER: 3},
    )


def _outs_mass(result, pid: int) -> int:
    """How many sims gave `pid` at least one more out."""
    dist = (result.pitcher_stat_dist or {}).get(pid, {}).get("OUTS", {})
    return sum(count for value, count in dist.items() if int(value) > 0)


def test_unset_batting_side_pitcher_is_seeded_as_its_starter():
    # What the caller produces today: only the fielding side's id is set.
    state = _build_initial_state(AWAY, HOME, _situation(home_pitcher_id=None), GameConfig(rng_seed=1))
    assert state.current_pitcher_by_team[2] == HOME_SP  # the pulled starter is "current"


def test_DEFECT_pulled_starter_pitches_again_in_the_sims():
    result = estimate_live(AWAY, HOME, _situation(home_pitcher_id=None), sims=SIMS, seed=7)
    # The starter left in the 3rd, yet he records outs in (nearly) every sim:
    # at 38 pitches inside the F5 leash nothing pulls him.
    assert _outs_mass(result, HOME_SP) >= int(0.9 * SIMS)
    assert _outs_mass(result, HOME_RELIEVER) < int(0.1 * SIMS)


def test_set_batting_side_pitcher_is_honoured():
    state = _build_initial_state(AWAY, HOME, _situation(home_pitcher_id=HOME_RELIEVER), GameConfig(rng_seed=1))
    assert state.current_pitcher_by_team[2] == HOME_RELIEVER
    result = estimate_live(AWAY, HOME, _situation(home_pitcher_id=HOME_RELIEVER), sims=SIMS, seed=7)
    assert _outs_mass(result, HOME_SP) == 0
    assert _outs_mass(result, HOME_RELIEVER) >= int(0.9 * SIMS)


def test_reachability_the_seed_moves_the_projection():
    """off != on at the engine: the same seed gives a different game."""
    off = estimate_live(AWAY, HOME, _situation(home_pitcher_id=None), sims=SIMS, seed=7)
    on = estimate_live(AWAY, HOME, _situation(home_pitcher_id=HOME_RELIEVER), sims=SIMS, seed=7)
    assert (off.home_win_prob, off.avg_total_runs) != (on.home_win_prob, on.avg_total_runs)


# ---------------------------------------------------------------------------
# The CALLER: `_live_mc_projection` decides which ids reach `estimate_live`.
# The fix is caller-only (the engine above already honours a set id), behind
# `MLB_LIVE_MC_BATTING_SIDE_PITCHER`, ABSENT = OFF.

import pytest  # noqa: E402

from syndicate.features.mlb.live_lens_port import app_slice  # noqa: E402


def _snapshot(pitcher_order_home):
    """Bottom of the 3rd, HOME batting; AWAY's starter on the mound."""
    return {
        "gamePk": 1,
        "status": {"abstractGameState": "Live", "detailedState": "In Progress"},
        "current": {
            "inning": 3, "halfInning": "bottom",
            "count": {"outs": 0, "balls": 0, "strikes": 0},
            "batter": {"id": 200004}, "pitcher": {"id": AWAY_SP},
        },
        "pitchingContext": {},
        "offense": {},
        "teams": {
            "away": {"totals": {"R": 4}, "pitcherOrder": [AWAY_SP], "boxscore": {"pitching": []}},
            "home": {"totals": {"R": 1}, "pitcherOrder": list(pitcher_order_home), "boxscore": {"pitching": []}},
        },
    }


@pytest.fixture
def captured(monkeypatch):
    seen = {}
    monkeypatch.setattr(app_slice, "_roster_from_snapshot_side", lambda doc: AWAY if doc.get("side") == "away" else HOME)

    def _fake_estimate_live(away, home, situation, **kwargs):
        seen["situation"] = situation
        raise RuntimeError("captured")  # the caller swallows it and returns None

    monkeypatch.setattr(app_slice, "estimate_live", _fake_estimate_live)
    return seen


def _project(snapshot):
    ctx = {"found": True, "gamePk": 1, "roster_snapshot": {"away": {"side": "away"}, "home": {"side": "home"}}}
    app_slice._live_mc_projection(snapshot, ctx, date_str="2026-06-15")


def test_caller_OFF_leaves_batting_side_unset(monkeypatch, captured):
    monkeypatch.delenv("MLB_LIVE_MC_BATTING_SIDE_PITCHER", raising=False)
    _project(_snapshot([HOME_SP, HOME_RELIEVER]))
    s = captured["situation"]
    assert s.away_pitcher_id == AWAY_SP
    assert s.home_pitcher_id is None  # -> the engine seeds HOME_SP: the defect


def test_caller_ON_passes_batting_side_last_pitcher(monkeypatch, captured):
    monkeypatch.setenv("MLB_LIVE_MC_BATTING_SIDE_PITCHER", "1")
    _project(_snapshot([HOME_SP, HOME_RELIEVER]))
    s = captured["situation"]
    assert s.away_pitcher_id == AWAY_SP  # fielding side unchanged
    assert s.home_pitcher_id == HOME_RELIEVER


def test_caller_ON_with_no_pitcher_yet_keeps_engine_default(monkeypatch, captured):
    monkeypatch.setenv("MLB_LIVE_MC_BATTING_SIDE_PITCHER", "1")
    _project(_snapshot([]))
    assert captured["situation"].home_pitcher_id is None


def test_box_pitcher_order_is_appearance_order():
    feed = {"liveData": {"boxscore": {"teams": {"home": {"pitchers": [HOME_SP, HOME_RELIEVER, 200205]}}}}}
    assert app_slice._box_pitcher_order(feed, "home") == [HOME_SP, HOME_RELIEVER, 200205]
    assert app_slice._box_pitcher_order({}, "home") == []
