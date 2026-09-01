"""The NCAAF week state is an ARTIFACT the platform owns, not a vendor cache.

WHAT THIS REPLACES. `ncaaf_target_week` -- "lowest week with an unplayed game"
-- read `historical_truth/games_<season>.json.gz` directly, on the request path.
`ensure_games_cached` writes that file ONCE, so the 2026 copy (written
2026-07-21) still said `completed: False` on 888 of 888 games six weeks later.
The answer was 1 for the whole season, and `_week_is_within_pregame_window`
trimmed the board to `week <= 1` while projection artifacts existed for weeks
1-13 and 15.

WHY AN ARTIFACT AND NOT JUST A FRESHER CACHE. Refreshing the cache fixes the
worker's disk only -- web has its own, and this publisher cannot carry a gzip
below the streaming threshold (`read_text(encoding="utf-8")` ->
`UnicodeDecodeError` -> SKIP_READ_FAILED). A small JSON crosses fine, so web
reads counts the worker derived instead of calling CFBD from a request handler.

THE TWO WAYS THIS CHANGE COULD BE INERT, both pinned below, because the
sibling entry in `artifact_publisher` was exactly this kind of no-op for 13
days:
  * the artifact is written but `ncaaf_target_week` still prefers the stale
    cache -- so the ORDER is asserted, not just the parsing
  * the artifact is written to a path the allowlist does not match, so it is
    never published and never reaches web at all
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

NOW = 1_756_000_000.0
_HOUR = 3600.0


def _iso(epoch: float) -> str:
    import datetime as _dt

    return _dt.datetime.fromtimestamp(epoch, _dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _game(week: int, *, completed: bool, kickoff: float) -> dict:
    return {
        "week": week,
        "seasonType": "regular",
        "completed": completed,
        "startDate": _iso(kickoff),
        "homeTeam": f"H{week}",
        "awayTeam": f"A{week}",
    }


@pytest.fixture()
def ncaaf_root(tmp_path, monkeypatch):
    """Point the NCAAF source root at a fixture, and clear the root caches --
    `source_roots` memoises on an env fingerprint, so a test that only sets the
    var can read a previous test's answer."""
    from syndicate.features.shared.source_roots import clear_source_root_caches

    root = tmp_path / "ncaaf_source"
    monkeypatch.setenv("SYNDICATE_NCAAF_SOURCE_ROOT", str(root))
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    clear_source_root_caches()
    yield root
    clear_source_root_caches()


# --------------------------------------------------------------- derivation

def test_counts_are_per_week_and_split_played_from_unplayed(ncaaf_root):
    from syndicate.features.ncaaf.week_state import build_week_state

    state = build_week_state(
        2026,
        games=[
            _game(1, completed=True, kickoff=NOW - 72 * _HOUR),
            _game(1, completed=False, kickoff=NOW + 48 * _HOUR),
            _game(2, completed=False, kickoff=NOW + 240 * _HOUR),
        ],
        now=NOW,
    )
    assert state["season"] == 2026
    assert state["games"] == 3
    assert state["weeks"]["1"] == {"games": 2, "completed": 1, "unplayed": 1}
    assert state["weeks"]["2"] == {"games": 1, "completed": 0, "unplayed": 1}


def test_a_game_long_past_kickoff_and_still_unplayed_is_counted_and_flagged(ncaaf_root):
    """`stale_completion_flags` is the number that would have made the original
    defect visible in one read. It was 8 on the frozen 2026 snapshot -- the same
    8 the cards board was independently reporting as `Final`."""
    from syndicate.features.ncaaf.week_state import build_week_state

    state = build_week_state(2026, games=[_game(1, completed=False, kickoff=NOW - 72 * _HOUR)], now=NOW)
    assert state["stale_completion_flags"] == 1
    # Still counted as unplayed: this records what the source SAYS, and
    # silently completing it here would invent a result we do not have.
    assert state["weeks"]["1"]["unplayed"] == 1


def test_a_game_in_progress_is_not_flagged_as_stale(ncaaf_root):
    from syndicate.features.ncaaf.week_state import build_week_state

    state = build_week_state(2026, games=[_game(1, completed=False, kickoff=NOW - 1 * _HOUR)], now=NOW)
    assert state["stale_completion_flags"] == 0


def test_postseason_rows_are_excluded(ncaaf_root):
    """The regular-season week numbering is what `ncaaf_target_week` indexes;
    a bowl game entering it would add a week that is not on that scale."""
    from syndicate.features.ncaaf.week_state import build_week_state

    bowl = _game(1, completed=False, kickoff=NOW + 100 * _HOUR)
    bowl["seasonType"] = "postseason"
    state = build_week_state(2026, games=[bowl], now=NOW)
    assert state["games"] == 0
    assert state["weeks"] == {}


# ------------------------------------------------------------- round trip

def test_write_then_read_round_trips_through_the_real_path(ncaaf_root):
    from syndicate.features.ncaaf.week_state import (
        build_week_state,
        read_week_state,
        week_state_path,
        write_week_state,
    )

    state = build_week_state(2026, games=[_game(1, completed=False, kickoff=NOW + 48 * _HOUR)], now=NOW)
    path = write_week_state(state)
    assert path == week_state_path(2026)
    assert read_week_state(2026) == state


def test_an_absent_or_malformed_artifact_reads_as_none_never_raises(ncaaf_root):
    """This replaces a read that always worked, so any failure here has to be
    at least as survivable as what it replaced."""
    from syndicate.features.ncaaf.week_state import read_week_state, week_state_path

    assert read_week_state(2026) is None

    path = week_state_path(2026)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    assert read_week_state(2026) is None

    path.write_text(json.dumps({"season": 2026, "weeks": "wrong type"}), encoding="utf-8")
    assert read_week_state(2026) is None


def test_a_season_mismatch_is_refused_rather_than_served(ncaaf_root):
    """A week number carries no season, so a cross-season hit would be silently
    plausible -- the same trap the WNBA live-lens path hit with dates."""
    from syndicate.features.ncaaf.week_state import read_week_state, week_state_path

    path = week_state_path(2026)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"season": 2025, "weeks": {"1": {"unplayed": 1}}}), encoding="utf-8")
    assert read_week_state(2026) is None


# ------------------------------------------------------------ the decision

def test_target_week_is_the_lowest_week_with_an_unplayed_game(ncaaf_root):
    from syndicate.features.ncaaf.week_state import target_week_from_state

    state = {
        "weeks": {
            "1": {"games": 2, "completed": 2, "unplayed": 0},
            "2": {"games": 3, "completed": 0, "unplayed": 3},
            "3": {"games": 3, "completed": 0, "unplayed": 3},
        }
    }
    assert target_week_from_state(state) == 2


def test_target_week_is_none_when_the_state_cannot_answer(ncaaf_root):
    """None is the same "cannot determine" the schedule path returns, and
    `_week_is_within_pregame_window` fails OPEN on it -- so an unusable artifact
    widens the board rather than blanking it."""
    from syndicate.features.ncaaf.week_state import target_week_from_state

    assert target_week_from_state(None) is None
    assert target_week_from_state({"weeks": {}}) is None
    assert target_week_from_state({"weeks": {"1": {"unplayed": 0}}}) is None


# ------------------------------- the artifact must actually WIN, and PUBLISH

def test_ncaaf_target_week_prefers_the_artifact_over_the_stale_cache(ncaaf_root, monkeypatch):
    """THE ORDER, NOT JUST THE PARSING.

    The games cache is the STALE source by construction. If `ncaaf_target_week`
    consulted it first, the artifact would never have an effect and this whole
    change would be inert while looking wired -- which is precisely how the
    season-projection publish call sat as a no-op for 13 days.
    """
    from syndicate.features.ncaaf import sources
    from syndicate.features.ncaaf.week_state import build_week_state, write_week_state

    # The stale cache says week 1 is still pending -- production's exact state.
    monkeypatch.setattr(
        "syndicate.features.football.sim_engine.smartsim2.historical_truth."
        "ncaaf_historical_loader.load_games_season",
        lambda season, **kw: [
            _game(1, completed=False, kickoff=NOW - 72 * _HOUR),
            _game(2, completed=False, kickoff=NOW + 240 * _HOUR),
        ],
    )
    assert sources.ncaaf_target_week(2026) == 1, "precondition: the cache alone pins to 1"

    # The published artifact knows week 1 is done.
    write_week_state(
        build_week_state(
            2026,
            games=[
                _game(1, completed=True, kickoff=NOW - 72 * _HOUR),
                _game(2, completed=False, kickoff=NOW + 240 * _HOUR),
            ],
            now=NOW,
        )
    )
    assert sources.ncaaf_target_week(2026) == 2


def test_the_cache_still_answers_when_no_artifact_has_been_published(ncaaf_root, monkeypatch):
    """The fallback is what makes this safe to deploy in any order: web on the
    new code with no artifact yet behaves exactly as it does today."""
    from syndicate.features.ncaaf import sources

    monkeypatch.setattr(
        "syndicate.features.football.sim_engine.smartsim2.historical_truth."
        "ncaaf_historical_loader.load_games_season",
        lambda season, **kw: [_game(4, completed=False, kickoff=NOW + 240 * _HOUR)],
    )
    assert sources.ncaaf_target_week(2026) == 4


def test_ncaaf_target_week_never_reaches_cfbd(ncaaf_root, monkeypatch):
    """The reason the artifact exists rather than a web-side refresh. This runs
    inside Flask request handlers; CLAUDE.md's rule is that the web service does
    no on-request backfill."""
    from syndicate.features.football.sim_engine.smartsim2.historical_truth import ncaaf_historical_loader
    from syndicate.features.ncaaf import sources
    from syndicate.features.ncaaf.week_state import build_week_state, write_week_state

    def _boom(*a, **k):
        raise AssertionError("a request-path read reached CFBD")

    monkeypatch.setattr(ncaaf_historical_loader, "_cfbd_get", _boom)
    monkeypatch.setattr(ncaaf_historical_loader, "_cfbd_get_latched", _boom)

    write_week_state(build_week_state(2026, games=[_game(2, completed=False, kickoff=NOW + 48 * _HOUR)], now=NOW))
    assert sources.ncaaf_target_week(2026) == 2


def test_the_written_path_is_one_the_allowlist_actually_matches(ncaaf_root):
    """THE HALF THAT PERMITS THE TRANSFER.

    `artifact_publisher`'s own note records the sibling defect: both football
    generators called `publish_hot_artifact` for 13 days and both were no-ops,
    because the pattern they relied on was never added. The publish call is
    worthless without this, and the two are written in different files, so this
    asserts them against each other rather than by eye.
    """
    from syndicate.features.shared.artifact_publisher import (
        is_hot_artifact_relative_path,
        relative_to_data_root,
    )
    from syndicate.features.ncaaf.week_state import build_week_state, write_week_state

    path = write_week_state(build_week_state(2026, games=[_game(1, completed=False, kickoff=NOW)], now=NOW))

    relative = relative_to_data_root(path)
    assert relative == "ncaaf_source/data/week_state/ncaaf_week_state_2026.json", relative
    assert is_hot_artifact_relative_path(relative), (
        f"{relative} is written by the generator but no HOT_ARTIFACT_PATTERNS entry matches it, "
        "so publish_hot_artifact returns SKIP_NOT_ALLOWLISTED and web never sees it"
    )
