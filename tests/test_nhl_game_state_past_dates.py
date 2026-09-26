"""An NHL board for a past date must know its games are FINAL.

THE DEFECT, measured on production 2026-09-26. Layer 1 for 2026-09-25 reported
every game as `state: pregame` with null scores -- BOS @ WSH still said pregame
FIFTEEN HOURS after puck drop. That is not cosmetic: `#340`'s
`live_edge_unavailable_reason` keys on GAME STATE and deliberately allows an
edge when the state is unknown, so a state that is WRONG silently disables the
guard. It let a pregame projection be priced against a settled market
(+800/-750) for a published `edge_vs_market_pct +54.83`.

TWO GATES CAUSED IT, AND NEITHER WAS THE NHL API:

  1. `games()` called `_apply_nhl_live_scores` only `if is_active_today`.
  2. `_load_nhl_scoreboard_rows` called the API only when the date was today.

The API was never the problem. Measured same-instant 2026-09-26T15:58:55Z,
production's own `syndicate-nhl/1.0` User-Agent returns HTTP200 with
`states={'FINAL': 4}` for 2026-09-25. (urllib's DEFAULT UA does 403 -- that is a
real trap, but not this one.)

AND THE DISK FALLBACK CANNOT COVER IT. `odds/games/date=*/scoreboard.csv` is
deliberately absent from `HOT_ARTIFACT_PATTERNS`: a `date=*` directory pattern
makes every dated pull list every historical game-date folder, and web's export
walk already ran past its timeout (2026-09-16). So the snapshot exists only on
the service that wrote it, and the board is built on another one.

WHAT THESE TESTS PROTECT: that the window stays BOUNDED and TODAY STAYS LIVE.
An unbounded lookback would fetch once per historical date per board build, and
serving today from a cache would freeze a game in progress.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import syndicate.blueprints.home as home  # noqa: E402

TODAY = "2026-09-26"


@pytest.fixture(autouse=True)
def _clean_cache():
    """The cache is module state and wall-clock keyed, like the WNBA card
    caches `conftest` already clears between tests."""
    home._NHL_PAST_SCOREBOARD_CACHE.clear()
    yield
    home._NHL_PAST_SCOREBOARD_CACHE.clear()


# --------------------------------------------------------------------------
# the window stays bounded
# --------------------------------------------------------------------------

@pytest.mark.parametrize(
    "date_value, eligible, why",
    [
        ("2026-09-26", True, "today"),
        ("2026-09-25", True, "yesterday -- the case that was broken"),
        ("2026-09-19", True, "inside the 8-day lookback"),
        ("2026-09-01", False, "older than the lookback: an archive must not be fetched per build"),
        ("2026-09-27", False, "the FUTURE has no score to learn; the request would be pure cost"),
        ("not-a-date", False, "unparseable fails closed, to the snapshot path"),
    ],
)
def test_api_eligibility_window(date_value, eligible, why):
    assert home._nhl_scoreboard_api_eligible(date_value, today=TODAY) is eligible, why


def test_the_lookback_is_configurable(monkeypatch):
    monkeypatch.setenv("SYNDICATE_NHL_SCOREBOARD_LOOKBACK_DAYS", "2")
    assert home._nhl_scoreboard_api_eligible("2026-09-25", today=TODAY) is True
    assert home._nhl_scoreboard_api_eligible("2026-09-19", today=TODAY) is False


def test_a_junk_lookback_value_falls_back_to_the_default(monkeypatch):
    monkeypatch.setenv("SYNDICATE_NHL_SCOREBOARD_LOOKBACK_DAYS", "banana")
    assert home._nhl_scoreboard_lookback_days() == home._NHL_SCOREBOARD_LOOKBACK_DAYS


# --------------------------------------------------------------------------
# today stays LIVE
# --------------------------------------------------------------------------

def test_today_is_never_written_to_the_cache():
    home._nhl_scoreboard_cache_put(TODAY, [{"gamePk": 1}], today=TODAY)
    assert TODAY not in home._NHL_PAST_SCOREBOARD_CACHE


def test_today_is_never_served_from_the_cache():
    """Even if an entry existed, a game in progress must not be frozen."""
    home._NHL_PAST_SCOREBOARD_CACHE[TODAY] = (time.time(), [{"gamePk": 1}])
    assert home._nhl_scoreboard_cache_get(TODAY, today=TODAY) is None


def test_a_past_date_IS_cached_because_a_final_score_never_changes():
    rows = [{"gamePk": 7, "gameState": "FINAL"}]
    home._nhl_scoreboard_cache_put("2026-09-25", rows, today=TODAY)
    assert home._nhl_scoreboard_cache_get("2026-09-25", today=TODAY) == rows


def test_an_empty_result_is_not_cached():
    """Caching a miss would pin a slate at zero games for the whole TTL."""
    home._nhl_scoreboard_cache_put("2026-09-25", [], today=TODAY)
    assert "2026-09-25" not in home._NHL_PAST_SCOREBOARD_CACHE


def test_the_cache_entry_expires(monkeypatch):
    home._NHL_PAST_SCOREBOARD_CACHE["2026-09-25"] = (
        time.time() - home._NHL_PAST_SCOREBOARD_TTL_SECONDS - 1.0,
        [{"gamePk": 7}],
    )
    assert home._nhl_scoreboard_cache_get("2026-09-25", today=TODAY) is None
    assert "2026-09-25" not in home._NHL_PAST_SCOREBOARD_CACHE, "a stale entry must be evicted"


# --------------------------------------------------------------------------
# failure degrades, it does not blank the slate
# --------------------------------------------------------------------------

def test_a_failed_fetch_falls_through_to_the_snapshot(monkeypatch, tmp_path):
    """An empty scoreboard is indistinguishable from a day with no games, so a
    fetch failure must not be allowed to look like one."""
    class _Boom:
        def scoreboard_day(self, _date):
            raise RuntimeError("network is down")

    monkeypatch.setattr(home, "central_today_iso", lambda: TODAY)
    monkeypatch.setattr("syndicate.local_nhl_odds.NhlWebClient", lambda *a, **k: _Boom())
    snapshot = tmp_path / "scoreboard.csv"
    snapshot.write_text(
        "away_abbr,home_abbr,away_goals,home_goals,gameState\nBOS,WSH,2,3,FINAL\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(home, "scoreboard_snapshot_path", lambda _d: snapshot)

    rows = home._load_nhl_scoreboard_rows("2026-09-25")
    assert len(rows) == 1
    assert rows[0]["gameState"] == "FINAL"
    assert rows[0]["away_goals"] == "2"


def test_no_snapshot_and_a_failed_fetch_returns_empty_not_an_exception(monkeypatch, tmp_path):
    class _Boom:
        def scoreboard_day(self, _date):
            raise RuntimeError("network is down")

    monkeypatch.setattr(home, "central_today_iso", lambda: TODAY)
    monkeypatch.setattr("syndicate.local_nhl_odds.NhlWebClient", lambda *a, **k: _Boom())
    monkeypatch.setattr(home, "scoreboard_snapshot_path", lambda _d: tmp_path / "absent.csv")
    assert home._load_nhl_scoreboard_rows("2026-09-25") == []


# --------------------------------------------------------------------------
# the join itself
# --------------------------------------------------------------------------

def test_apply_live_scores_is_a_no_op_when_there_are_no_rows(monkeypatch):
    """This is what makes ungating the call site safe on every quiet date."""
    monkeypatch.setattr(home, "_load_nhl_scoreboard_rows", lambda _d: [])
    games = [{"away_tri": "BOS", "home_tri": "WSH"}]
    assert home._apply_nhl_live_scores(games, "2026-09-25") is games


def test_a_past_date_game_gets_its_final_score(monkeypatch):
    monkeypatch.setattr(
        home,
        "_load_nhl_scoreboard_rows",
        lambda _d: [{
            "away_abbr": "BOS", "home_abbr": "WSH",
            "away": "Boston Bruins", "home": "Washington Capitals",
            "away_goals": 2, "home_goals": 3, "gameState": "FINAL", "period": 4,
        }],
    )
    games = [{"away_tri": "BOS", "home_tri": "WSH", "away_name": "Boston Bruins",
              "home_name": "Washington Capitals"}]
    out = home._apply_nhl_live_scores(games, "2026-09-25")
    assert len(out) == 1
    blob = repr(out[0])
    assert "FINAL" in blob.upper(), f"the final state never reached the game: {blob[:200]}"


def test_the_call_site_is_no_longer_gated_on_is_active_today():
    """THE REACHABILITY TEST. The loader and cache can be perfect and still be
    unreachable if `games()` keeps its `if is_active_today` guard -- which is
    exactly how this defect survived: every piece existed, none of it ran.
    """
    import inspect

    source = inspect.getsource(home)
    assert "_apply_nhl_live_scores(games, context.context_label) if is_active_today else games" not in source, (
        "the call site is still gated on is_active_today"
    )
    assert "return _apply_nhl_live_scores(games, context.context_label)" in source
