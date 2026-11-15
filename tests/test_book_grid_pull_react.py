"""Reprice a live sport soon after its odds pull (todo #803, lane book-grid-pull-react).

Measured on the fleet 2026-11-14: a pull waited a median 38-103 s before its prices were in the in-play overlay,
because price-on-pull was looked for once per main-loop pass on a thread 64-75% busy. Pinned here, against the REAL
`_run_book_grid_artifact_tick` and the real helpers:
  - `pull_only` runs a price-on-pull pass or nothing -- never a regular round, even when one is due;
  - the reacting sleep looks for pulls every step while games are live, and still ends at its deadline;
    off (SYNDICATE_BOOK_GRID_PULL_REACT=off) or nothing live -> one plain sleep (off != on);
  - a regular round skips a live sport a price-on-pull pass rebuilt within 45 s, and keeps the live cadence;
    a round-built sport is never skipped; 0 seconds disables it (off != on);
  - the main loop sleeps through the reacting sleep and looks once after the live re-sims.
"""
from __future__ import annotations

import importlib.util
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

_PATH = Path(__file__).resolve().parent.parent / "scripts" / "run_refresh_worker.py"
_SPEC = importlib.util.spec_from_file_location("run_refresh_worker_pull_react", _PATH)
worker = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(worker)

TODAY = "2026-11-11"
T0 = datetime(2026, 11, 12, 0, 10, tzinfo=timezone.utc).timestamp()
LIVE = {"rows": [{"game": {"state": "live"}, "commence_time": "2026-11-12T00:00:00Z"}], "rows_total": 1}
ENV = ("SYNDICATE_BOOK_GRID_PULL_REACT", "SYNDICATE_BOOK_GRID_ROUND_SKIP_FRESH_SECONDS", "SYNDICATE_BOOK_GRID_PRICE_ON_PULL",
       "SYNDICATE_BOOK_GRID_LIVE_FIRST", "SYNDICATE_BOOK_GRID_SLOW_SPORT_SCHEDULE", "SYNDICATE_BOOK_GRID_SLOW_SPORT_SECONDS",
       "SYNDICATE_BOOK_GRID_SKIP_NONLIVE_SPORTS", "SYNDICATE_BOOK_GRID_REFRESH_INTERVAL_SECONDS")


@pytest.fixture()
def tick(tmp_path, monkeypatch):
    worker._BOOK_GRID_LAST_RUN.clear()
    worker._BOOK_GRID_SPORT_STATE.clear()
    worker._BOOK_GRID_BACKGROUND_QUEUE.clear()
    for name in ENV:
        monkeypatch.delenv(name, raising=False)
    shard = tmp_path / f"{TODAY}.jsonl"
    shard.write_text("{}\n", encoding="utf-8")
    clock = [1000.0]
    monkeypatch.setattr(worker, "_book_grid_build_clock", lambda: clock[0])

    def run(at: float, *, pull_only: bool = False):
        built = []

        def build(sport, day):
            if day != TODAY or sport not in ("ncaab", "ncaaf"):
                return None
            built.append(sport)
            clock[0] += 5.0
            return LIVE

        with patch.object(worker.time, "time", return_value=at), \
             patch.object(worker, "central_today_iso", return_value=TODAY), \
             patch.object(worker, "_book_grid_forward_days", return_value=0), \
             patch.object(worker, "_book_grid_refresh_interval_seconds", return_value=120), \
             patch.object(worker, "_book_grid_previous_rebuilt_on_disk", return_value=True), \
             patch("syndicate.features.shared.book_grid_artifact.build_book_grid_artifact", side_effect=build), \
             patch("syndicate.features.shared.book_grid_artifact.write_book_grid_artifact", return_value=shard), \
             patch("syndicate.features.shared.artifact_publisher.publish_hot_artifact", return_value=None), \
             patch("syndicate.features.shared.artifact_publisher.pull_streamed_artifact", return_value=None), \
             patch("syndicate.features.shared.odds_book_quotes.book_quotes_path", return_value=shard), \
             patch("syndicate.features.shared.refresh_state_store.data_root", return_value=tmp_path):
            meta = worker._run_book_grid_artifact_tick(pull_only=pull_only)
        return built, meta

    def new_pull(at: float):
        os.utime(shard, (at, at))

    run.new_pull = new_pull
    return run


def _first_round(tick):
    built, meta = tick(T0)
    assert set(built) == {"ncaab", "ncaaf"} and meta["on_pull"] == []
    return meta


# ------------------------------------------------------------------ pull_only
def test_pull_only_never_starts_a_round_even_when_one_is_due(tick):
    _first_round(tick)
    seq, last = worker._BOOK_GRID_LAST_RUN["tick_seq"], worker._BOOK_GRID_LAST_RUN["all"]
    built, meta = tick(T0 + 500, pull_only=True)  # a round is due (interval 120 s), no new quotes
    assert built == [] and meta is None
    assert worker._BOOK_GRID_LAST_RUN["tick_seq"] == seq and worker._BOOK_GRID_LAST_RUN["all"] == last


def test_pull_only_runs_a_price_on_pull_pass_when_a_live_shard_changed(tick):
    _first_round(tick)
    last = worker._BOOK_GRID_LAST_RUN["all"]
    tick.new_pull(T0 + 400)                              # quotes landed after the round read them
    built, meta = tick(T0 + 500, pull_only=True)         # a round is due too: still only the pull pass
    assert sorted(built) == ["ncaab", "ncaaf"] and sorted(meta["on_pull"]) == ["ncaab", "ncaaf"]
    assert worker._BOOK_GRID_LAST_RUN["all"] == last, "a price-on-pull pass leaves the round clock alone"
    assert worker._BOOK_GRID_SPORT_STATE["ncaab"]["built_tick"] is None


# ------------------------------------------------------------------ the round's skip of a sport just repriced
def test_a_round_skips_a_sport_repriced_on_pull_within_45_s_and_stays_live(tick):
    _first_round(tick)
    tick.new_pull(T0 + 200)
    pull_built, _ = tick(T0 + 230, pull_only=True)       # repriced on pull at T0+230
    assert sorted(pull_built) == ["ncaab", "ncaaf"]
    built, meta = tick(T0 + 260)                          # the next round, 30 s later
    assert built == [] and sorted(meta["skipped_fresh"]) == ["ncaab", "ncaaf"]
    assert worker._BOOK_GRID_LAST_RUN["any_live"] is True, "skipped live sports keep the live cadence"


def test_the_skip_is_for_rounds_only_a_second_pull_inside_45_s_still_prices(tick):
    _first_round(tick)
    tick.new_pull(T0 + 140)
    tick(T0 + 150, pull_only=True)                         # repriced on pull at T0+150 (inside the interval)
    tick.new_pull(T0 + 180)                                # the next pull, 30 s later
    built, meta = tick(T0 + 186, pull_only=True)           # 36 s after the last build: past the 30 s gap
    assert sorted(built) == ["ncaab", "ncaaf"] and sorted(meta["on_pull"]) == ["ncaab", "ncaaf"]


def test_a_round_rebuilds_a_sport_repriced_on_pull_more_than_45_s_ago(tick):
    _first_round(tick)
    tick.new_pull(T0 + 150)
    tick(T0 + 180, pull_only=True)
    built, meta = tick(T0 + 260)                          # 80 s later
    assert sorted(built) == ["ncaab", "ncaaf"] and meta["skipped_fresh"] == []


def test_the_skip_off_rebuilds_every_live_sport(tick, monkeypatch):
    """Reachability: off != on."""
    monkeypatch.setenv("SYNDICATE_BOOK_GRID_ROUND_SKIP_FRESH_SECONDS", "0")
    _first_round(tick)
    tick.new_pull(T0 + 200)
    tick(T0 + 230, pull_only=True)
    built, meta = tick(T0 + 260)
    assert sorted(built) == ["ncaab", "ncaaf"] and meta["skipped_fresh"] == []


def test_a_round_built_sport_is_never_skipped():
    worker._BOOK_GRID_SPORT_STATE.clear()
    worker._BOOK_GRID_SPORT_STATE["ncaab"] = {"date": TODAY, "built_at": 100.0, "built_tick": 3, "live": True}
    assert worker._book_grid_repriced_on_pull_recently("ncaab", 110.0) is False
    worker._BOOK_GRID_SPORT_STATE["ncaab"]["built_tick"] = None
    assert worker._book_grid_repriced_on_pull_recently("ncaab", 110.0) is True
    assert worker._book_grid_repriced_on_pull_recently("ncaab", 150.0) is False
    assert worker._book_grid_repriced_on_pull_recently("ncaaf", 110.0) is False


def test_the_skip_is_measured_from_when_the_pass_read_the_sport_not_from_the_pass_start():
    """Fleet 2026-11-15 03:22Z: a pass built NCAAB (56 s), NCAAF (30 s), then NHL, so NHL's quotes were read ~86 s
    after the pass started (`built_at`). Measured from `built_at`, the next round (~30 s after that read) rebuilt it."""
    worker._BOOK_GRID_SPORT_STATE.clear()
    worker._BOOK_GRID_SPORT_STATE["ncaaf"] = {"date": TODAY, "built_at": 100.0, "quotes_read_at": 160.0,
                                              "built_tick": None, "live": True}
    assert worker._book_grid_repriced_on_pull_recently("ncaaf", 190.0) is True    # 30 s after its read, 90 s after the start
    assert worker._book_grid_repriced_on_pull_recently("ncaaf", 210.0) is False   # 50 s after its read
    del worker._BOOK_GRID_SPORT_STATE["ncaaf"]["quotes_read_at"]                  # older state: falls back to built_at
    assert worker._book_grid_repriced_on_pull_recently("ncaaf", 140.0) is True
    assert worker._book_grid_repriced_on_pull_recently("ncaaf", 150.0) is False


# ------------------------------------------------------------------ the reacting sleep
@pytest.fixture()
def fake_sleep(monkeypatch):
    for name in ENV:
        monkeypatch.delenv(name, raising=False)
    now = [0.0]
    sleeps, checks = [], []
    monkeypatch.setattr(worker, "_pull_react_monotonic", lambda: now[0])

    def sleep(seconds):
        sleeps.append(round(seconds, 3))
        now[0] += seconds

    def check(stage):
        checks.append((round(now[0], 3), stage))
        if len(checks) == 3:
            now[0] += 10.0  # one check found a pull and its build took 10 s
        return None

    monkeypatch.setattr(worker, "_pull_react_sleep", sleep)
    monkeypatch.setattr(worker, "_book_grid_pull_check", check)
    worker._BOOK_GRID_LAST_RUN.clear()
    return now, sleeps, checks


def test_the_sleep_looks_for_pulls_every_step_while_live_and_ends_on_time(fake_sleep):
    now, sleeps, checks = fake_sleep
    worker._BOOK_GRID_LAST_RUN["any_live"] = True
    worker._sleep_reacting_to_live_pulls(30.0)
    assert now[0] == 30.0, "a pass inside the sleep uses up sleep time; it does not add to the loop's pace"
    assert all(at < 30.0 for at, _ in checks), "no look once the deadline is reached (a pass there would overrun it)"
    assert all(stage == "sleep" for _, stage in checks) and len(checks) >= 8
    assert max(sleeps) <= worker._BOOK_GRID_PULL_REACT_STEP_SECONDS


def test_off_is_one_plain_sleep(fake_sleep, monkeypatch):
    """Reachability: off != on."""
    now, sleeps, checks = fake_sleep
    worker._BOOK_GRID_LAST_RUN["any_live"] = True
    monkeypatch.setenv("SYNDICATE_BOOK_GRID_PULL_REACT", "off")
    worker._sleep_reacting_to_live_pulls(30.0)
    assert sleeps == [30.0] and checks == []


def test_nothing_live_is_one_plain_sleep(fake_sleep):
    now, sleeps, checks = fake_sleep
    worker._BOOK_GRID_LAST_RUN["any_live"] = False
    worker._sleep_reacting_to_live_pulls(30.0)
    assert sleeps == [30.0] and checks == []


def test_price_on_pull_off_turns_the_reacting_off_too(monkeypatch):
    monkeypatch.delenv("SYNDICATE_BOOK_GRID_PULL_REACT", raising=False)
    monkeypatch.setenv("SYNDICATE_BOOK_GRID_PRICE_ON_PULL", "off")
    assert worker._book_grid_pull_react_enabled() is False


# ------------------------------------------------------------------ the check itself
def test_the_check_prints_its_pass_and_never_raises(monkeypatch, capsys):
    for name in ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(worker, "_run_book_grid_artifact_tick", lambda **kw: {"on_pull": ["ncaab"], "pull_only": kw.get("pull_only")})
    meta = worker._book_grid_pull_check("sleep")
    out = capsys.readouterr().out
    assert meta["pull_react"] == "sleep" and meta["pull_only"] is True
    assert "BOOK_GRID_TICK" in out and '"pull_react": "sleep"' in out
    monkeypatch.setattr(worker, "_run_book_grid_artifact_tick", lambda **kw: (_ for _ in ()).throw(RuntimeError("boom")))
    assert worker._book_grid_pull_check("after_live_resims") is None
    assert "BOOK_GRID_TICK_ERROR stage=after_live_resims" in capsys.readouterr().out
    monkeypatch.setenv("SYNDICATE_BOOK_GRID_PULL_REACT", "off")
    monkeypatch.setattr(worker, "_run_book_grid_artifact_tick", lambda **kw: pytest.fail("off must not look"))
    assert worker._book_grid_pull_check("sleep") is None


# ------------------------------------------------------------------ wiring in the main loop
def test_the_main_loop_sleeps_reacting_and_looks_after_the_live_resims():
    src = _PATH.read_text(encoding="utf-8")
    main = src[src.index("def main() -> int:"):]
    assert "_sleep_reacting_to_live_pulls(poll_seconds)" in main
    assert not re.search(r"\n\s+time\.sleep\(poll_seconds\)", main), "the loop's plain sleep is replaced"
    resims = main.index("NFL_LIVE_RESIM_ERROR")
    look = main.index('_book_grid_pull_check("after_live_resims")')
    cycle = main.index('refresh_cycle = {"claimed_count": 0')
    assert resims < look < cycle
