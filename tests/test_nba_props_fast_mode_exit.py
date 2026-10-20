"""`--mode fast` exit code (lane `nba-live-board`, 2026-10-20).

The NBA in-play lane runs `refresh_nba_oddsapi_props.py --mode fast --force-refresh --do-edges --do-export`. Fast mode
refreshes the snapshot only, so a fresh fast state carries edges_rows 0 by construction -- and the edges check failed it.
Measured 23:18Z: 8,435 rows written, 5,742 book quotes appended, rc=1 on every in-play run.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location("refresh_nba_props_fast_exit_under_test",
                                                  REPO_ROOT / "scripts" / "refresh_nba_oddsapi_props.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# The 23:18Z fast state as the fleet counted it: snapshot + alias written, no predictions/edges/recs (full-mode work),
# game cards / cards_sim_detail / smart_sim files left by the day's full run.
FAST_STATE = {"date": "2026-10-20", "mode": "fast", "snapshot_rows": 8435, "snapshot_alias_rows": 8435, "predictions_rows": 0,
              "edges_rows": 0, "recs_rows": 0, "game_cards_rows": 3, "cards_sim_detail_games": 3, "smart_sim_files": 3,
              "error": None}


def _code(mod, state, *, fast_mode):
    return mod._refresh_exit_code([state], state, do_edges=True, do_export=True, fast_mode=fast_mode)


def test_a_forced_fast_snapshot_pull_exits_zero(mod):
    assert _code(mod, dict(FAST_STATE), fast_mode=True) == 0


def test_full_mode_still_fails_a_snapshot_with_no_edges(mod):
    assert _code(mod, dict(FAST_STATE, mode="full"), fast_mode=False) == 1      # off != on: the same state, full mode


def test_fast_mode_keeps_the_checks_it_can_meet(mod):
    assert _code(mod, dict(FAST_STATE, snapshot_alias_rows=0), fast_mode=True) == 1      # alias never written
    assert _code(mod, dict(FAST_STATE, error="fetch failed"), fast_mode=True) == 1
