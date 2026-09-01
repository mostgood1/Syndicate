"""`games_{season}.json.gz` must stop being write-once, without becoming a hammer.

THE BUG THESE PIN. `ensure_games_cached` returns early on `path.exists()`, so the
file was written once and never again. Measured on production 2026-09-01:
`games_2026.json.gz` (written 2026-07-21, six weeks before kickoff) held 888
games with `completed: False` on **888 of 888**. `ncaaf_target_week` is
`min(week holding an unplayed game)`, so it returned 1 -- and would keep
returning 1 for the whole season. `_week_is_within_pregame_window` then trims the
week list to `week <= 1`, so `/ncaaf/api/cards?week=2` and `?week=3` both served
`"2026 Week 1"` while projection artifacts existed for weeks 1-13 and 15.

THE FAILURE MODES THAT WOULD BE WORSE THAN THE STALENESS, each pinned below,
because every one of them has a precedent in this repo:

  * an unlatched periodic CFBD caller -- the hourly hammer `cfbd_quota_latch`
    shipped to stop, rebuilt on a path the latch cannot see
  * a rate-limited or partial response overwriting a good schedule
  * a fetch failure taking the board to blank instead of leaving it stale
  * a refresh on the REQUEST path, which is a blocking CFBD call on the cards
    page and against CLAUDE.md's web/worker split
"""
from __future__ import annotations

import gzip
import json
import sys
import time
import urllib.error
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.football.sim_engine.smartsim2.historical_truth import (  # noqa: E402
    ncaaf_historical_loader as loader,
)

_HOUR = 3600.0
NOW = 1_756_000_000.0  # fixed; `Date.now()`-style drift makes these untestable


def _iso(epoch: float) -> str:
    """CFBD's own shape: UTC with a literal `Z`."""
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


def _write_cache(cache_dir: Path, season: int, games: list[dict]) -> Path:
    path = cache_dir / f"games_{season}.json.gz"
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        json.dump(games, handle)
    return path


def _read_cache(path: Path) -> list[dict]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return json.load(handle)


# A schedule shaped like the real one: week 1 already played, week 2 still ahead.
def _played_week1_pending_week2() -> list[dict]:
    return [
        _game(1, completed=False, kickoff=NOW - 48 * _HOUR),
        _game(2, completed=False, kickoff=NOW + 240 * _HOUR),
    ]


@pytest.fixture()
def no_latch(monkeypatch, tmp_path):
    """Point the quota latch at an empty dir so these tests never read a real one."""
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path / "state_root"))
    yield


# ---------------------------------------------------------------- staleness

def test_a_game_played_two_days_ago_and_still_uncompleted_is_stale():
    assert loader.games_payload_is_stale(_played_week1_pending_week2(), now=NOW) is True


def test_a_schedule_whose_played_games_are_marked_completed_is_fresh():
    games = _played_week1_pending_week2()
    games[0]["completed"] = True
    assert loader.games_payload_is_stale(games, now=NOW) is False


def test_a_game_that_kicked_off_an_hour_ago_is_not_yet_evidence_of_staleness():
    """The grace window. A game in progress is legitimately `completed: False`;
    calling that stale would refresh on every tick of every game day."""
    games = [_game(1, completed=False, kickoff=NOW - 1 * _HOUR)]
    assert loader.games_payload_is_stale(games, now=NOW) is False


def test_a_payload_that_is_not_a_list_is_never_stale():
    """A shape we could not interpret cannot justify spending a call."""
    assert loader.games_payload_is_stale({"error": "nope"}, now=NOW) is False
    assert loader.games_payload_is_stale(None, now=NOW) is False


def test_a_row_with_no_start_date_cannot_make_the_payload_stale():
    assert loader.games_payload_is_stale([{"week": 1, "completed": False}], now=NOW) is False


# ------------------------------------------------- reachability: off != on

def test_a_stale_cache_refreshes_and_a_fresh_one_does_not(tmp_path, monkeypatch, no_latch):
    """REACHABILITY, and the reason this test is first among the behaviour ones.

    `off != on`: the same function, same file, must fetch in one state and not
    in the other. Without this pair, a refresh that never fires and a refresh
    that always fires both look like a pass.
    """
    calls: list[str] = []

    fresh_payload = _played_week1_pending_week2()
    fresh_payload[0]["completed"] = True

    def _fake_get(path, params, **kwargs):
        calls.append(path)
        return fresh_payload

    monkeypatch.setattr(loader, "_cfbd_get_latched", _fake_get)

    # ON: stale -> one fetch, and the file on disk actually changes.
    path = _write_cache(tmp_path, 2026, _played_week1_pending_week2())
    result = loader.refresh_games_cache(2026, cache_dir=tmp_path, now=NOW)
    assert result["status"] == "refreshed", result
    assert calls == ["/games"]
    assert result["completed_before"] == 0
    assert result["completed_after"] == 1
    assert _read_cache(path)[0]["completed"] is True

    # OFF: now fresh -> no further fetch.
    result2 = loader.refresh_games_cache(2026, cache_dir=tmp_path, now=NOW + 1)
    assert result2["status"] == "fresh", result2
    assert result2["refreshed"] is False
    assert calls == ["/games"], "a fresh cache must not spend a CFBD call"


# ---------------------------------------------- never worse than stale

def test_a_failed_fetch_leaves_the_existing_cache_untouched(tmp_path, monkeypatch, no_latch):
    """A stale board is a defect. A blank one is a worse defect, and CFBD is on
    a MONTHLY quota, so an outage can last days."""
    original = _played_week1_pending_week2()
    path = _write_cache(tmp_path, 2026, original)

    def _boom(*a, **k):
        raise urllib.error.URLError("dns is down")

    monkeypatch.setattr(loader, "_cfbd_get_latched", _boom)

    result = loader.refresh_games_cache(2026, cache_dir=tmp_path, now=NOW)
    assert result["status"] == "fetch_failed", result
    assert result["refreshed"] is False
    assert _read_cache(path) == original, "the cache must survive a failed refresh"


def test_a_quota_exhausted_latch_is_a_failure_not_a_crash(tmp_path, monkeypatch, no_latch):
    """`QuotaExhausted` reaches here like any other fetch failure: the caller
    gets a status dict and the stale file, never an exception."""
    from syndicate.features.ncaaf.cfbd_quota_latch import QuotaExhausted

    original = _played_week1_pending_week2()
    path = _write_cache(tmp_path, 2026, original)

    def _latched(*a, **k):
        raise QuotaExhausted("CFBD monthly quota exhausted")

    monkeypatch.setattr(loader, "_cfbd_get_latched", _latched)

    result = loader.refresh_games_cache(2026, cache_dir=tmp_path, now=NOW)
    assert result["status"] == "fetch_failed"
    assert "QuotaExhausted" in result["error"]
    assert _read_cache(path) == original


def test_an_empty_payload_is_refused_rather_than_written(tmp_path, monkeypatch, no_latch):
    """`ensure_ratings_cached` states the rule for its own sibling: an absent
    file is honest, an empty one is not. A rate-limited answer written once
    would be served forever as though it were real."""
    original = _played_week1_pending_week2()
    path = _write_cache(tmp_path, 2026, original)
    monkeypatch.setattr(loader, "_cfbd_get_latched", lambda *a, **k: [])

    result = loader.refresh_games_cache(2026, cache_dir=tmp_path, now=NOW)
    assert result["status"] == "empty_payload_refused"
    assert _read_cache(path) == original


def test_a_payload_shorter_than_what_we_hold_is_refused(tmp_path, monkeypatch, no_latch):
    """A schedule does not shrink. Fewer rows means a partial or filtered
    response, and writing it drops games off the board with no error anywhere."""
    original = _played_week1_pending_week2()
    path = _write_cache(tmp_path, 2026, original)
    monkeypatch.setattr(loader, "_cfbd_get_latched", lambda *a, **k: [_game(1, completed=True, kickoff=NOW - 48 * _HOUR)])

    result = loader.refresh_games_cache(2026, cache_dir=tmp_path, now=NOW)
    assert result["status"] == "short_payload_refused", result
    assert result["incoming_rows"] == 1
    assert _read_cache(path) == original


# ---------------------------------------------------------------- throttle

def test_a_failed_refresh_does_not_retry_on_the_next_tick(tmp_path, monkeypatch, no_latch):
    """The generator relaunches hourly while its artifact is stale. An
    unthrottled retry here is the per-tick CFBD hammering the quota latch
    exists to stop -- and a non-quota failure never latches, so the latch
    cannot cover this."""
    calls: list[str] = []
    _write_cache(tmp_path, 2026, _played_week1_pending_week2())

    def _boom(path, params, **kwargs):
        calls.append(path)
        raise urllib.error.URLError("still down")

    monkeypatch.setattr(loader, "_cfbd_get_latched", _boom)

    assert loader.refresh_games_cache(2026, cache_dir=tmp_path, now=NOW)["status"] == "fetch_failed"
    assert len(calls) == 1

    result = loader.refresh_games_cache(2026, cache_dir=tmp_path, now=NOW + _HOUR)
    assert result["status"] == "throttled", result
    assert len(calls) == 1, "a second attempt inside the window must not call CFBD"

    # ...and it does retry once the window has passed.
    result = loader.refresh_games_cache(2026, cache_dir=tmp_path, now=NOW + 7 * _HOUR)
    assert result["status"] == "fetch_failed"
    assert len(calls) == 2


def test_the_attempt_is_stamped_before_the_call_not_after(tmp_path, monkeypatch, no_latch):
    """A process killed mid-fetch must still count as an attempt. The
    season-projection generator is launched with a timeout and has been seen to
    hit it (`SEASON_PROJECTION_TIMEOUT`); stamping after the call would make the
    throttle silently inert for exactly the failure that recurs."""
    _write_cache(tmp_path, 2026, _played_week1_pending_week2())
    marker = loader._games_refresh_marker_path(2026, tmp_path)

    def _killed(*a, **k):
        assert marker.exists(), "the attempt was not stamped before the call went out"
        raise KeyboardInterrupt("simulated timeout kill")

    monkeypatch.setattr(loader, "_cfbd_get_latched", _killed)
    with pytest.raises(KeyboardInterrupt):
        loader.refresh_games_cache(2026, cache_dir=tmp_path, now=NOW)
    assert marker.exists()


def test_force_bypasses_both_the_freshness_check_and_the_throttle(tmp_path, monkeypatch, no_latch):
    calls: list[str] = []
    fresh = _played_week1_pending_week2()
    fresh[0]["completed"] = True
    _write_cache(tmp_path, 2026, fresh)

    def _fake_get(path, params, **kwargs):
        calls.append(path)
        return fresh

    monkeypatch.setattr(loader, "_cfbd_get_latched", _fake_get)
    assert loader.refresh_games_cache(2026, cache_dir=tmp_path, now=NOW)["status"] == "fresh"
    assert calls == []
    assert loader.refresh_games_cache(2026, cache_dir=tmp_path, now=NOW, force=True)["status"] == "refreshed"
    assert calls == ["/games"]


def test_an_absent_cache_is_reported_not_fetched(tmp_path, monkeypatch, no_latch):
    """Creating the file is `ensure_games_cached`'s job. This function only ever
    replaces one that already exists, so a missing file is a status, not a
    second code path that could write a different shape."""
    monkeypatch.setattr(loader, "_cfbd_get_latched", lambda *a, **k: pytest.fail("must not fetch"))
    result = loader.refresh_games_cache(2026, cache_dir=tmp_path, now=NOW)
    assert result["status"] == "absent"
    assert not (tmp_path / "games_2026.json.gz").exists()


# ------------------------------------------------- the request-path guarantee

def test_ensure_games_cached_still_never_fetches_when_the_file_exists(tmp_path, monkeypatch):
    """`ncaaf_target_week` -> `load_games_season` -> `ensure_games_cached` runs
    inside Flask request handlers. CLAUDE.md's rule is that the web service does
    no on-request backfill; a lazy refresh there is a blocking CFBD call on the
    cards page. The producer is explicit and worker-side for exactly this
    reason."""
    _write_cache(tmp_path, 2026, _played_week1_pending_week2())

    def _boom(*a, **k):
        raise AssertionError("a reader reached CFBD")

    monkeypatch.setattr(loader, "_cfbd_get", _boom)
    monkeypatch.setattr(loader, "_cfbd_get_latched", _boom)

    path = loader.ensure_games_cached(2026, cache_dir=tmp_path)
    assert path.exists()
    assert loader.load_games_season(2026, cache_dir=tmp_path) == _played_week1_pending_week2()


# ------------------------------------------------------------- the classifier

def test_the_urllib_classifier_recognises_a_urllib_error_and_only_that():
    """NOT `cfbd.py::_classify_requests_error`, which reads `exc.response` --
    an attribute urllib errors do not have. Handing it a urllib error returns
    None for everything, so every 429 re-raises immediately and the retry ladder
    is inert while looking wired."""
    err = urllib.error.HTTPError("u", 429, "Too Many Requests", {"Retry-After": "30"}, None)
    assert loader._classify_urllib_error(err) == (429, "30")

    # A transport failure is NOT a throttle: a backoff aimed at a rate limit
    # must not also delay a real outage.
    assert loader._classify_urllib_error(urllib.error.URLError("down")) is None
    assert loader._classify_urllib_error(ValueError("nope")) is None


def test_a_429_that_is_not_the_monthly_quota_does_not_set_the_latch(tmp_path, monkeypatch):
    """A per-minute throttle and an exhausted monthly quota arrive with the same
    status code and need opposite responses. Guessing here converts a
    30-second throttle into a multi-day outage."""
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    from syndicate.features.ncaaf import cfbd_quota_latch as latch

    latch.clear_latch()

    def _throttled(path, params, **kwargs):
        raise urllib.error.HTTPError("u", 429, "slow down", {}, None)

    monkeypatch.setattr(loader, "_cfbd_get", _throttled)
    # No sleeping in a unit test; the ladder's delays are its own tests' subject.
    monkeypatch.setattr("syndicate.features.ncaaf.cfbd_backoff.time.sleep", lambda _s: None)

    with pytest.raises(urllib.error.HTTPError):
        loader._cfbd_get_latched("/games", {"year": 2026})
    assert latch.quota_latched_until() is None, "a bare 429 must not latch the month"


# --------------------------------------------------- the end-to-end symptom

def test_the_refresh_moves_ncaaf_target_week_off_one(tmp_path, monkeypatch, no_latch):
    """THE SYMPTOM THIS WHOLE CHANGE EXISTS TO FIX, end to end.

    `ncaaf_target_week` reads `DEFAULT_CACHE_DIR` with no cache_dir parameter,
    so this drives the real function against a fixture -- a test on
    `games_payload_is_stale` alone would not have caught a producer that wrote
    to a path the reader never opens.

    IT PATCHES THE BOUND DEFAULT, NOT THE MODULE CONSTANT, and that distinction
    is why this test earned its keep before it ever ran green.
    `cache_dir: Path = DEFAULT_CACHE_DIR` binds the constant's VALUE when the
    `def` executes, so `monkeypatch.setattr(loader, "DEFAULT_CACHE_DIR", ...)`
    is silently a no-op -- the reader keeps opening the real repo path. Anything
    asserting only the post-refresh state would have been testing the wrong
    file.
    """
    from syndicate.features.ncaaf.sources import ncaaf_target_week

    for fn in (loader.ensure_games_cached, loader.load_games_season):
        monkeypatch.setitem(fn.__kwdefaults__, "cache_dir", tmp_path)
    _write_cache(tmp_path, 2026, _played_week1_pending_week2())

    # BEFORE: week 1 has already been played but is still flagged unplayed, so
    # the target pins to 1 -- production's exact state on 2026-09-01.
    assert ncaaf_target_week(2026) == 1

    refreshed = _played_week1_pending_week2()
    refreshed[0]["completed"] = True
    monkeypatch.setattr(loader, "_cfbd_get_latched", lambda *a, **k: refreshed)
    assert loader.refresh_games_cache(2026, cache_dir=tmp_path, now=NOW)["status"] == "refreshed"

    # AFTER: the board can reach week 2.
    assert ncaaf_target_week(2026) == 2


@pytest.mark.skipif(
    not (REPO_ROOT / "data" / "ncaaf_source" / "historical_truth" / "games_2026.json.gz").exists(),
    reason="data/ is excluded from session worktrees; this runs in the primary tree and in CI",
)
def test_the_committed_2026_snapshot_is_the_stale_one_this_fixes():
    """Not a synthetic case. The file in git is the defect, and if a future
    refresh ever lands in the repo this test is what says so."""
    path = REPO_ROOT / "data" / "ncaaf_source" / "historical_truth" / "games_2026.json.gz"
    games = _read_cache(path)
    completed = sum(1 for g in games if g.get("completed"))
    # Measured 2026-09-01: 888 games, 0 completed, first kickoff 2026-08-29.
    assert len(games) > 800
    if completed == 0:
        assert loader.games_payload_is_stale(games, now=time.time()) is True
