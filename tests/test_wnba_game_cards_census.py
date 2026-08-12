"""`#375` -- which input built game_cards, and what it contained.

Measured 2026-08-11: `game_cards_2026-08-11.csv` held 2 games for a 3-game
slate. Fever/Liberty was absent, so `#364`'s projection join had nothing to
match and 18 board rows rendered blank -- alongside a failed game-state chip
join and a matchup rendered in full names instead of tri-codes. Three symptoms,
one absence.

WHY THIS NEEDED AN INSTRUMENT RATHER THAN A FIX. `_build_local_game_cards_artifact`
has three input paths (raw player-props snapshot, processed game_odds, raw team
odds snapshot) and seven no-data exits. Which one ran, and what it held, is not
recoverable from outside: the raw snapshots live only on the worker's disk and
are not published, so `/api/ops/artifacts/export` returns MISS for every
candidate path. That left two very different bugs indistinguishable --

    the snapshot never had the game        -> fix the capture
    the snapshot had it and a filter dropped it -> fix the filter

-- with no way to tell which, and a blind fix to the wrong one would have looked
plausible either way.

`print`, not `_log`: `_log` writes to a run file on the same unreadable disk,
which is precisely the problem being solved.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def module():
    spec = importlib.util.spec_from_file_location(
        "wnba_refresh_under_test", _REPO / "scripts" / "refresh_wnba_oddsapi_props.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["wnba_refresh_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod


def _run(module, tmp_path):
    src = tmp_path / "src"
    proc = tmp_path / "proc"
    (src / "data" / "raw").mkdir(parents=True, exist_ok=True)
    (src / "data" / "processed").mkdir(parents=True, exist_ok=True)
    proc.mkdir(parents=True, exist_ok=True)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        result = module._build_local_game_cards_artifact(
            source_root=src, processed_root=proc, date_str="2026-08-11"
        )
    return result, buf.getvalue()


def test_the_no_data_path_says_which_branch_and_why(module, tmp_path):
    (count, path), out = _run(module, tmp_path)
    assert (count, path) == (0, None)
    census = [l for l in out.splitlines() if "GAME_CARDS_CENSUS" in l]
    assert census, "a build that produced nothing said nothing -- the exact gap this closes"
    line = census[0]
    assert "source=none" in line
    assert "written_rows=0" in line
    # The reason distinguishes seven different no-data exits from each other.
    assert "note=" in line and "no_raw_team_odds_snapshot" in line


def test_the_census_reports_the_expected_matchup_count(module, tmp_path):
    # `expected_matchups` is assigned AFTER the helper is defined, so a naive
    # `'expected_matchups' in dir()` guard reports 'n/a' forever -- the closure's
    # dir() lists its OWN locals, not the enclosing scope. That silently turned
    # the most useful field into a constant.
    (_, _), out = _run(module, tmp_path)
    line = next(l for l in out.splitlines() if "GAME_CARDS_CENSUS" in l)
    assert "expected_matchups=0" in line, f"expected a real count, got: {line}"
    assert "expected_matchups=n/a" not in line


def test_every_exit_path_is_instrumented(module):
    """A census that misses a branch is worse than none -- it implies coverage."""
    source = (_REPO / "scripts" / "refresh_wnba_oddsapi_props.py").read_text(encoding="utf-8")
    start = source.index("def _build_local_game_cards_artifact")
    end = source.index("def _smart_sim_projection_index")
    body = source[start:end]
    # Three write paths, each naming its input.
    for tag in ("raw_player_props_snapshot", "processed_game_odds", "raw_team_odds_snapshot"):
        assert f'_census("{tag}"' in body, f"write path {tag} is not instrumented"
    # All seven no-data exits funnel through `_no_data`, so one call covers them.
    assert '_census("none"' in body
    assert body.count("_write_game_cards_csv_rows(out_path, rows_out)") == 3, (
        "a write path was added or removed -- re-check that each one still reports"
    )


def test_the_census_cannot_break_the_build_it_observes():
    """This assertion replaces one that enshrined a real crash.

    The first cut passed `matchups=rows_by_matchup` directly, and I wrote a test
    asserting exactly that -- but `rows_by_matchup` does not exist on the
    raw-team-odds path (it groups via a DataFrame), so the census raised
    UnboundLocalError and took down the build. Five existing runner tests caught
    it; my own test had certified the bug.

    The census now derives matchups from `rows_out`, which every write path has,
    and swallows any failure. A diagnostic that can break its subject is worse
    than no diagnostic.
    """
    source = (_REPO / "scripts" / "refresh_wnba_oddsapi_props.py").read_text(encoding="utf-8")
    assert "matchups=rows_by_matchup" not in source, "per-branch variable is not defined on every path"
    assert "_matchups_of(rows_out)" in source
    assert source.count("_census(") >= 5
