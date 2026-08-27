"""Exchange prices need a clock the live-refresh loop does not own.

WHY THIS LOOP EXISTS. Both venue refreshes rode the live worker's main loop,
and that loop is ADAPTIVE: `_live_refresh_loop_interval_for_meta` returns the
IDLE interval (~900s) whenever no game is live. So a venue tick placed there
could only run every ~900s while idle, no matter what its own interval said --
and every interval env var read as a lever that did nothing. Measured
2026-08-27: polymarket slate ages of 428s and 828s against a 180s self-pace,
and kalshi at 1,250s.

That idle interval is CORRECT for what it guards -- expensive per-sport work
nobody needs when nothing is live. Exchange prices are the opposite kind of
thing: free to fetch, and moving continuously whether or not a game is live.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def worker():
    """Import the worker entrypoint by path -- it is a script, not a package."""
    path = REPO_ROOT / "scripts" / "run_live_odds_refresh_worker.py"
    spec = importlib.util.spec_from_file_location("run_live_odds_refresh_worker", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["run_live_odds_refresh_worker"] = module
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# cadence
# ---------------------------------------------------------------------------


def test_the_default_is_sixty_seconds(worker, monkeypatch):
    monkeypatch.delenv("SYNDICATE_VENUE_POLL_INTERVAL_SECONDS", raising=False)

    assert worker.venue_poll_interval_seconds() == 60


def test_a_faster_cadence_is_floored_not_honoured(worker, monkeypatch):
    """Kalshi has already answered this platform with http_429s. An unpaced loop
    against a venue that rate-limits is the failure the request spacing exists
    to prevent, so the floor is a real bound and not a suggestion."""
    monkeypatch.setenv("SYNDICATE_VENUE_POLL_INTERVAL_SECONDS", "1")

    assert worker.venue_poll_interval_seconds() == worker.MIN_VENUE_POLL_INTERVAL_SECONDS
    assert worker.MIN_VENUE_POLL_INTERVAL_SECONDS == 30


@pytest.mark.parametrize("bad", ["", "   ", "abc", "0", "-5"])
def test_a_bad_value_falls_back_to_the_default_never_to_zero(worker, monkeypatch, bad):
    """`int("")` raising into a bare except that returns 0 would turn a typo
    into an unpaced loop -- the gate both venue refreshers already document."""
    monkeypatch.setenv("SYNDICATE_VENUE_POLL_INTERVAL_SECONDS", bad)

    assert worker.venue_poll_interval_seconds() == 60


def test_a_slower_cadence_is_honoured(worker, monkeypatch):
    monkeypatch.setenv("SYNDICATE_VENUE_POLL_INTERVAL_SECONDS", "300")

    assert worker.venue_poll_interval_seconds() == 300


# ---------------------------------------------------------------------------
# the tick
# ---------------------------------------------------------------------------


def test_a_tick_refreshes_BOTH_venues(worker, monkeypatch):
    called = []
    monkeypatch.setattr(worker, "_polymarket_us_slate_refresh_tick", lambda: called.append("polymarket"))
    import pipeline.kalshi_odds_refresh as kor
    monkeypatch.setattr(kor, "run_kalshi_odds_refresh",
                        lambda **kw: called.append("kalshi") or {"status": "ok", "markets": []})

    worker._venue_poll_tick()

    assert called == ["kalshi", "polymarket"]


def test_one_venue_failing_does_not_cost_the_other(worker, monkeypatch):
    """A shared `except` would let a Kalshi outage silently stop Polymarket
    updating, which is indistinguishable from Polymarket having nothing to say."""
    called = []
    monkeypatch.setattr(worker, "_polymarket_us_slate_refresh_tick", lambda: called.append("polymarket"))
    import pipeline.kalshi_odds_refresh as kor

    def _boom(**kw):
        raise RuntimeError("kalshi down")

    monkeypatch.setattr(kor, "run_kalshi_odds_refresh", _boom)

    worker._venue_poll_tick()  # must not raise

    assert called == ["polymarket"], "polymarket was skipped by kalshi's failure"


def test_the_tick_does_NOT_force_either_refresh(worker, monkeypatch):
    """Forcing would bypass the per-series clock that keeps us inside the
    venue's rate limits -- the very thing that makes a 60s poll safe against
    refreshers whose own intervals are longer."""
    seen = {}
    monkeypatch.setattr(worker, "_polymarket_us_slate_refresh_tick", lambda: None)
    import pipeline.kalshi_odds_refresh as kor
    monkeypatch.setattr(kor, "run_kalshi_odds_refresh",
                        lambda **kw: seen.update(kw) or {"status": "ok", "markets": []})

    worker._venue_poll_tick()

    assert seen.get("force") is not True, "the poll forced a refresh past its own clock"


# ---------------------------------------------------------------------------
# starting it
# ---------------------------------------------------------------------------


def test_it_is_ON_by_default(worker, monkeypatch):
    """A poll that ships switched off is a poll that silently never runs. It
    lives in ONE process, so default-on cannot fan out across services."""
    monkeypatch.delenv("SYNDICATE_VENUE_POLL_ENABLED", raising=False)
    monkeypatch.setattr(worker, "_VENUE_POLL_THREAD", None)
    monkeypatch.setattr(worker.threading, "Thread", lambda **kw: _FakeThread())

    assert worker.start_venue_poll_loop() is True


@pytest.mark.parametrize("off", ["0", "false", "no", "off", "OFF"])
def test_it_can_be_switched_off_without_a_code_change(worker, monkeypatch, off):
    monkeypatch.setenv("SYNDICATE_VENUE_POLL_ENABLED", off)
    monkeypatch.setattr(worker, "_VENUE_POLL_THREAD", None)

    assert worker.start_venue_poll_loop() is False


def test_it_does_not_start_twice(worker, monkeypatch):
    """A second thread would double every venue call and halve the effective
    spacing the floor is protecting."""
    monkeypatch.delenv("SYNDICATE_VENUE_POLL_ENABLED", raising=False)
    monkeypatch.setattr(worker, "_VENUE_POLL_THREAD", _FakeThread(alive=True))

    assert worker.start_venue_poll_loop() is False


class _FakeThread:
    def __init__(self, alive=False):
        self._alive = alive

    def start(self):
        self._alive = True

    def is_alive(self):
        return self._alive


# ---------------------------------------------------------------------------
# the bug this file shipped, and the guard that makes it impossible again
# ---------------------------------------------------------------------------


def test_no_function_is_defined_AFTER_the_main_guard():
    """I SHIPPED THIS BUG TO PRODUCTION AND IT CRASH-LOOPED THE WORKER.

    The venue poll functions were appended to the END of the file -- after
    `if __name__ == "__main__": raise SystemExit(main())`. Module bodies execute
    top to bottom, so `main()` ran BEFORE those defs existed:

        2026-08-27T16:41:04Z  NameError: name 'start_venue_poll_loop' is not defined
        2026-08-27T16:42:29Z  NameError: name 'start_venue_poll_loop' is not defined

    Once every ~85s, because the NameError escaped `main()`, killed the process
    and Render restarted it. Every unit test passed the whole time: they import
    the module and call the functions directly, which never executes the guard.
    Nothing about "does this file still boot" was being asked.

    So the check is structural, not behavioural -- a def below the guard is
    unreachable to `main()` no matter what it contains.
    """
    import ast

    src = (REPO_ROOT / "scripts" / "run_live_odds_refresh_worker.py").read_text(encoding="utf-8")
    tree = ast.parse(src)

    guard_lines = [n.lineno for n in ast.walk(tree)
                   if isinstance(n, ast.If) and "__main__" in ast.dump(n.test)]
    assert guard_lines, "the __main__ guard vanished"
    guard = max(guard_lines)

    stranded = sorted(n.name for n in tree.body
                      if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.lineno > guard)

    assert not stranded, (
        f"defined after the __main__ guard and therefore unreachable to main(): {stranded}"
    )


def test_the_venue_poll_names_exist_before_the_guard():
    """The positive half: the names `main()` actually calls are there to call."""
    import ast

    src = (REPO_ROOT / "scripts" / "run_live_odds_refresh_worker.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    guard = max(n.lineno for n in ast.walk(tree)
                if isinstance(n, ast.If) and "__main__" in ast.dump(n.test))
    before = {n.name for n in tree.body
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.lineno < guard}

    for name in ("start_venue_poll_loop", "venue_poll_interval_seconds",
                 "_venue_poll_tick", "_venue_poll_background_loop"):
        assert name in before, f"{name} is not defined before the guard"


def test_the_tick_reports_BOTH_venues_on_success_not_just_kalshi(worker, monkeypatch, capsys):
    """The `[venue_poll]` family must be able to answer "did both refresh?".

    It used to print KALSHI on success and Polymarket only on FAILURE, so a
    Polymarket half that had silently stopped produced output identical to one
    working perfectly -- and the question could only be answered by leaving this
    log family entirely.
    """
    monkeypatch.setattr(worker, "_polymarket_us_slate_refresh_tick", lambda: None)
    import pipeline.kalshi_odds_refresh as kor
    monkeypatch.setattr(kor, "run_kalshi_odds_refresh",
                        lambda **kw: {"status": "ok", "markets": []})

    worker._venue_poll_tick()
    out = capsys.readouterr().out

    assert "[venue_poll] KALSHI" in out
    assert "[venue_poll] POLYMARKET" in out, "a successful polymarket refresh left no trace"
