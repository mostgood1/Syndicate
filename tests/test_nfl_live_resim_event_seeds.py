"""Each NFL game's live re-sim draws its own seeds (todo #813 part 2, lane `nfl-live-resim-event-seeds`).

Before: every game at every tick ran seeds 1..N, so one set of random numbers carried the whole slate
(+0.29 [+0.11, +0.46] points at the end of Q3 over the 11-09..11-16 replay). After: the seeds are keyed
by ESPN's event id, the same across a game's ticks, and a row with no id keeps 1..N bit-identically.

Reachability BEFORE correctness, per `docs/ai_context/model_engine_standard.md`:
  * the row's `event_id` reaches the state, and the state's id reaches the engine's `seed` (call-site capture);
  * no id is the old seeds exactly; two ids give different games (off != on);
  * the offset is the same in every interpreter, whatever PYTHONHASHSEED says.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import syndicate.features.nfl.live_resim as live_resim  # noqa: E402
from syndicate.features.nfl.live_resim import (  # noqa: E402
    NflLiveGameState,
    NflResimRefusal,
    _event_seed_base,
    live_state_from_row,
    resim_live_game,
)

ON = {"SYNDICATE_NFL_LIVE_RESIM": "1"}
SEPARATED = dict(home_offense=27.0, home_defense=19.0, away_offense=20.0, away_defense=24.0)

# The home side leads by a touchdown early in Q4 and has the ball, so the probability sits well outside
# the uninformative band and the re-sim publishes rather than refusing.
Q4 = dict(away_team="A", home_team="B", period=4, clock_seconds=600, home_score=24, away_score=17,
          down=1, distance=10, field_position=30, possession_owner="home")

ROW = {"state": "in", "period": 4, "clock_seconds": 600, "home_score": 24, "away_score": 17,
       "possession_owner": "home"}

EVENT_A = "401772936"
EVENT_B = "401772937"


def _without_timing(out):
    return {k: v for k, v in out.items() if k != "elapsed_seconds"}


def _capture(monkeypatch):
    seen = []

    def fake(simulation_input, *, profile):
        seen.append(simulation_input)
        return SimpleNamespace(final_score={"home": 30, "away": 0})

    monkeypatch.setattr(live_resim, "simulate_game", fake)
    return seen


# ---- the offset ---------------------------------------------------------------------------------------

def test_no_id_is_offset_zero():
    for missing in (None, "", "   "):
        assert _event_seed_base(missing) == 0, missing


def test_an_id_gives_a_positive_31_bit_offset_and_ids_differ():
    a, b = _event_seed_base(EVENT_A), _event_seed_base(EVENT_B)
    for base in (a, b):
        assert 0 < base <= 0x7FFFFFFF
    assert a != b
    # Whitespace around an id is the same game.
    assert _event_seed_base(f" {EVENT_A} ") == a


def test_the_offset_is_the_same_in_every_interpreter():
    """`hash()` of a str moves with PYTHONHASHSEED; the offset must not, or a restart re-draws every game."""
    code = ("import sys; sys.path.insert(0, sys.argv[1]); "
            "from syndicate.features.nfl.live_resim import _event_seed_base; "
            f"print(_event_seed_base({EVENT_A!r}))")
    seen = set()
    for hash_seed in ("0", "1", "4242"):
        env = dict(os.environ, PYTHONHASHSEED=hash_seed)
        proc = subprocess.run([sys.executable, "-c", code, str(REPO_ROOT)], capture_output=True,
                              text=True, env=env, cwd=str(REPO_ROOT), timeout=120)
        assert proc.returncode == 0, proc.stderr[-2000:]
        seen.add(int(proc.stdout.strip().splitlines()[-1]))
    assert seen == {_event_seed_base(EVENT_A)}


# ---- the row reaches the state ------------------------------------------------------------------------

def test_the_row_carries_the_event_id_into_the_state():
    st = live_state_from_row(dict(ROW, event_id=EVENT_A), away_team="A", home_team="B")
    assert isinstance(st, NflLiveGameState)
    assert st.event_id == EVENT_A
    # An int id (ESPN's ids are digit strings, but a reader may have parsed one) is the same game.
    st = live_state_from_row(dict(ROW, event_id=int(EVENT_A)), away_team="A", home_team="B")
    assert st.event_id == EVENT_A


def test_an_absent_or_blank_id_is_None():
    for row in (dict(ROW), dict(ROW, event_id=None), dict(ROW, event_id=""), dict(ROW, event_id="  ")):
        st = live_state_from_row(row, away_team="A", home_team="B")
        assert st.event_id is None, row


# ---- the state reaches the engine ---------------------------------------------------------------------

def test_no_id_runs_the_old_seeds_exactly(monkeypatch):
    seen = _capture(monkeypatch)
    out = resim_live_game(NflLiveGameState(**Q4), **SEPARATED, sims=6, env=ON)
    assert not isinstance(out, NflResimRefusal), getattr(out, "detail", "")
    assert [i.seed for i in seen] == [1, 2, 3, 4, 5, 6]
    assert out["seed_basis"] == "shared"


def test_an_id_runs_that_games_own_seeds(monkeypatch):
    seen = _capture(monkeypatch)
    st = live_state_from_row(dict(ROW, event_id=EVENT_A), away_team="A", home_team="B")
    out = resim_live_game(st, **SEPARATED, sims=6, env=ON)
    base = _event_seed_base(EVENT_A)
    assert [i.seed for i in seen] == [base + k for k in range(1, 7)]
    assert out["seed_basis"] == "event"


def test_two_games_draw_disjoint_seeds(monkeypatch):
    seen = _capture(monkeypatch)
    resim_live_game(NflLiveGameState(**Q4, event_id=EVENT_A), **SEPARATED, sims=60, env=ON)
    first = {i.seed for i in seen}
    seen.clear()
    resim_live_game(NflLiveGameState(**Q4, event_id=EVENT_B), **SEPARATED, sims=60, env=ON)
    assert first.isdisjoint({i.seed for i in seen})


def test_a_game_keeps_its_seeds_from_tick_to_tick(monkeypatch):
    """Keyed by the game, not the tick: a line should move with the clock, not with a fresh draw."""
    seen = _capture(monkeypatch)
    resim_live_game(NflLiveGameState(**Q4, event_id=EVENT_A), **SEPARATED, sims=8, env=ON)
    early = [i.seed for i in seen]
    seen.clear()
    later = dict(Q4, clock_seconds=420, home_score=27)
    resim_live_game(NflLiveGameState(**later, event_id=EVENT_A), **SEPARATED, sims=8, env=ON)
    assert [i.seed for i in seen] == early


def test_both_possession_plans_reuse_the_games_seeds(monkeypatch):
    seen = _capture(monkeypatch)
    unknown = dict(Q4, possession_owner=None)
    resim_live_game(NflLiveGameState(**unknown, event_id=EVENT_A), **SEPARATED, sims=8, env=ON)
    base = _event_seed_base(EVENT_A)
    by_owner = {}
    for i in seen:
        by_owner.setdefault(i.initial_possession_owner, []).append(i.seed)
    assert by_owner == {"home": [base + k for k in range(1, 5)], "away": [base + k for k in range(1, 5)]}


def test_resampled_ratings_follow_the_games_seeds(monkeypatch):
    """With rating_sd > 0 the ratings are drawn from the seed too, so two games stop sharing those draws."""
    seen = _capture(monkeypatch)
    resim_live_game(NflLiveGameState(**Q4, event_id=EVENT_A), **SEPARATED, sims=4, env=ON, rating_sd=0.75)
    a = [i.home_offense_rating for i in seen]
    seen.clear()
    resim_live_game(NflLiveGameState(**Q4, event_id=EVENT_B), **SEPARATED, sims=4, env=ON, rating_sd=0.75)
    assert a != [i.home_offense_rating for i in seen]


# ---- on real sims -------------------------------------------------------------------------------------

def test_no_id_is_bit_identical_to_an_explicit_None():
    plain = resim_live_game(NflLiveGameState(**Q4), **SEPARATED, sims=60, env=ON)
    explicit = resim_live_game(NflLiveGameState(**Q4, event_id=None), **SEPARATED, sims=60, env=ON)
    assert not isinstance(plain, NflResimRefusal), getattr(plain, "detail", "")
    assert _without_timing(plain) == _without_timing(explicit)


def test_off_is_not_on_two_games_play_different_games():
    shared = resim_live_game(NflLiveGameState(**Q4), **SEPARATED, sims=60, env=ON)
    game_a = resim_live_game(NflLiveGameState(**Q4, event_id=EVENT_A), **SEPARATED, sims=60, env=ON)
    game_b = resim_live_game(NflLiveGameState(**Q4, event_id=EVENT_B), **SEPARATED, sims=60, env=ON)
    for out in (shared, game_a, game_b):
        assert not isinstance(out, NflResimRefusal), getattr(out, "detail", "")
    assert shared["margin_dist"] != game_a["margin_dist"]
    assert game_a["margin_dist"] != game_b["margin_dist"]


def test_the_same_game_replays_exactly():
    first = resim_live_game(NflLiveGameState(**Q4, event_id=EVENT_A), **SEPARATED, sims=60, env=ON)
    again = resim_live_game(NflLiveGameState(**Q4, event_id=EVENT_A), **SEPARATED, sims=60, env=ON)
    assert _without_timing(first) == _without_timing(again)
    assert first["seed_basis"] == "event"
