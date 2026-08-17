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
import os
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


def _run(module, tmp_path, *, with_schedule: bool = False):
    """Build with NO market input at all.

    `with_schedule=False` isolates the build from the repo's real
    `schedule_2026.csv`, which the 2026-08-17 fixture-identity work made this
    function consult. That is not a workaround: these tests are about which
    BRANCH ran and what it reported, and the schedule is an unrelated global
    input. The coverage behaviour it enables gets its own test below and 40
    more in `test_wnba_fixture_identity.py`.
    """
    src = tmp_path / "src"
    proc = tmp_path / "proc"
    (src / "data" / "raw").mkdir(parents=True, exist_ok=True)
    (src / "data" / "processed").mkdir(parents=True, exist_ok=True)
    proc.mkdir(parents=True, exist_ok=True)
    prior = os.environ.get("SYNDICATE_WNBA_SCHEDULE_PATH")
    if not with_schedule:
        os.environ["SYNDICATE_WNBA_SCHEDULE_PATH"] = str(tmp_path / "no_schedule.csv")
    else:
        os.environ.pop("SYNDICATE_WNBA_SCHEDULE_PATH", None)
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            result = module._build_local_game_cards_artifact(
                source_root=src, processed_root=proc, date_str="2026-08-11"
            )
    finally:
        if prior is None:
            os.environ.pop("SYNDICATE_WNBA_SCHEDULE_PATH", None)
        else:
            os.environ["SYNDICATE_WNBA_SCHEDULE_PATH"] = prior
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


def test_with_a_schedule_the_no_data_path_publishes_the_slate_instead(module, tmp_path):
    """THE EMPTY-FILE MODE, closed 2026-08-17.

    Measured across 41 dates: `game_cards_2026-06-28.csv` held 0 rows against 4
    scheduled fixtures, `2026-07-09` 0 against 3. Every market input can be
    missing while the slate is perfectly well known, and publishing nothing
    made the games vanish rather than render priceless.

    2026-08-11 is the date the `#375` census was built for -- it had a 3-game
    slate and `game_cards` wrote 2.
    """
    (count, path), out = _run(module, tmp_path, with_schedule=True)
    assert count == 3 and path is not None, "the slate is known even with no odds"
    line = next(l for l in out.splitlines() if "GAME_CARDS_CENSUS" in l)
    assert "source=schedule_only" in line
    assert "scheduled=3" in line and "backfilled=3" in line
    # The reason for having no market data is still carried, not swallowed.
    assert "note=" in line and "no_raw_team_odds_snapshot" in line
    written = path.read_text(encoding="utf-8")
    assert "fixture_id" in written.splitlines()[0], "the stable id must be in the header"
    # No invented prices on a row that has no market behind it.
    for row in written.splitlines()[1:]:
        assert ",oddsapi" not in row


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
    # Three write paths, each naming its input. Since 2026-08-17 they report by
    # routing through `_finalize_and_write`, which censuses and writes in one
    # place -- a STRONGER guarantee than three parallel `_census(...)` calls,
    # because a fourth write path cannot be added without going through it.
    for tag in ("raw_player_props_snapshot", "processed_game_odds", "raw_team_odds_snapshot"):
        assert f'_finalize_and_write("{tag}"' in body, f"write path {tag} is not instrumented"
    # All seven no-data exits funnel through `_no_data`, which reports either
    # `none` or -- when the schedule knows the slate -- `schedule_only`.
    assert '_census("none"' in body
    assert '_census(' in body and '"schedule_only"' in body
    # Exactly two write sites now: the shared funnel, and the schedule-only
    # publish inside `_no_data`. If this count moves, a path was added that may
    # not be reporting.
    assert body.count("_write_game_cards_csv_rows(") == 2, (
        "a write path was added or removed -- re-check that each one still reports"
    )
    assert body.count("_finalize_and_write(") == 4, (
        "one definition plus three write paths -- a new caller needs a census tag"
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
    # Was `>= 5` when three write paths each called `_census` directly. The
    # 2026-08-17 funnel consolidated those into `_finalize_and_write`, so the
    # count legitimately dropped to four: the definition, the funnel, and the
    # two `_no_data` outcomes. Lowered deliberately and with the reason, rather
    # than left to fail or quietly deleted.
    assert source.count("_census(") >= 4
    # SAME PROPERTY, EXTENDED TO THE NEW DEPENDENCY. The funnel imports the
    # fixture-identity module, and this build path must survive that import
    # failing -- a diagnostic that can break its subject is worse than none.
    assert "FIXTURE_IDENTITY_SKIPPED" in source, "the identity import must be guarded"
    assert source.count("FIXTURE_IDENTITY_SKIPPED") == 2, (
        "both the funnel and the schedule-only path must survive an import failure"
    )
