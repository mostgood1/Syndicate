"""Live first, background under a budget, in refresh-worker's book-grid round (todo #803, lane book-grid-live-first).

Measured on the fleet 2026-11-14 19:00-20:13Z: live work alone took 20-40 s a round, and every long gap between
live repricings was a round that also built background work -- today's pre-game grids (54-110 s), the next days'
(~170 s), yesterday's after each restart (5-minute holes). These tests drive the REAL `_run_book_grid_artifact_tick`
with a build clock that advances by each grid's build time, and pin: live sports are built every round and before
any background work; background drains under the budget, always at least one job, and nothing is dropped; a queued
pair the foreground builds leaves the queue; price-on-pull never drains it; the queue clears when the date rolls;
the off switch restores the single sequential pass (off != on); and a restart skips yesterday when its grids were
already written after the date rolled.
"""
from __future__ import annotations

import importlib.util
import os
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "run_refresh_worker_live_first", Path(__file__).resolve().parent.parent / "scripts" / "run_refresh_worker.py"
)
worker = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(worker)

TODAY, YESTERDAY, TOMORROW = "2026-11-11", "2026-11-10", "2026-11-12"
T0 = datetime(2026, 11, 12, 0, 10, tzinfo=timezone.utc).timestamp()
LIVE = {"rows": [{"game": {"state": "live"}, "commence_time": "2026-11-12T00:00:00Z"}], "rows_total": 1}
PRE = {"rows": [{"game": {"state": "pre"}, "commence_time": "2026-11-12T05:00:00Z"}], "rows_total": 1}
OTHER = {"rows": [], "rows_total": 0}
ENV = ("SYNDICATE_BOOK_GRID_LIVE_FIRST", "SYNDICATE_BOOK_GRID_BACKGROUND_BUDGET_SECONDS",
       "SYNDICATE_BOOK_GRID_SLOW_SPORT_SCHEDULE", "SYNDICATE_BOOK_GRID_SLOW_SPORT_SECONDS",
       "SYNDICATE_BOOK_GRID_PRICE_ON_PULL", "SYNDICATE_BOOK_GRID_SKIP_NONLIVE_SPORTS",
       "SYNDICATE_BOOK_GRID_REFRESH_INTERVAL_SECONDS")
# Seconds per build, shaped like 2026-11-14: college live grids 3-10 s, pre-game grids 30-60 s, the next days and
# yesterday 5-50 s. The slow-sport schedule (45 s) is set high below so it does not interleave with this.
DURATIONS = {
    ("ncaab", TODAY): 3.0, ("ncaaf", TODAY): 10.0,
    ("nba", TODAY): 40.0, ("soccer", TODAY): 60.0, ("nfl", TODAY): 30.0,
    ("nba", YESTERDAY): 50.0, ("ncaab", YESTERDAY): 8.0,
    ("nfl", TOMORROW): 25.0, ("soccer", TOMORROW): 5.0,
}
TODAY_PAYLOADS = {"ncaab": LIVE, "ncaaf": LIVE, "nba": PRE, "soccer": PRE, "nfl": PRE}
LIVE_SPORTS = {"ncaab", "ncaaf"}


@pytest.fixture()
def tick(tmp_path, monkeypatch):
    worker._BOOK_GRID_LAST_RUN.clear()
    worker._BOOK_GRID_SPORT_STATE.clear()
    worker._BOOK_GRID_BACKGROUND_QUEUE.clear()
    for name in ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SYNDICATE_BOOK_GRID_SLOW_SPORT_SECONDS", "1000")
    shard = tmp_path / f"{TODAY}.jsonl"
    shard.write_text("{}\n", encoding="utf-8")
    clock = [1000.0]
    monkeypatch.setattr(worker, "_book_grid_build_clock", lambda: clock[0])
    state = {"today": TODAY, "on_disk": False}

    def run(k: int, *, at: float | None = None):
        built: list[tuple[str, str]] = []

        def build(sport, day):
            if day == state["today"]:
                payload = TODAY_PAYLOADS.get(sport)
            else:
                payload = OTHER if (sport, day) in DURATIONS else None
            if payload is None:
                return None
            built.append((sport, day))
            clock[0] += DURATIONS.get((sport, day), 1.0)
            return payload

        when = T0 + 130 * k if at is None else at
        with patch.object(worker.time, "time", return_value=when), \
             patch.object(worker, "central_today_iso", return_value=state["today"]), \
             patch.object(worker, "_book_grid_forward_days", return_value=1), \
             patch.object(worker, "_book_grid_refresh_interval_seconds", return_value=120), \
             patch.object(worker, "_sport_covers_date", return_value=True), \
             patch.object(worker, "_book_grid_previous_rebuilt_on_disk", return_value=state["on_disk"]), \
             patch("syndicate.features.shared.book_grid_artifact.build_book_grid_artifact", side_effect=build), \
             patch("syndicate.features.shared.book_grid_artifact.write_book_grid_artifact", return_value=shard), \
             patch("syndicate.features.shared.artifact_publisher.publish_hot_artifact", return_value=None), \
             patch("syndicate.features.shared.artifact_publisher.pull_streamed_artifact", return_value=None), \
             patch("syndicate.features.shared.odds_book_quotes.book_quotes_path", return_value=shard), \
             patch("syndicate.features.shared.refresh_state_store.data_root", return_value=tmp_path):
            meta = worker._run_book_grid_artifact_tick()
        return built, meta

    run.state = state
    run.shard = shard
    return run


def _background(built):
    return [(s, d) for s, d in built if not (d == TODAY and s in LIVE_SPORTS)]


def test_live_sports_every_round_and_before_any_background(tick):
    for k in range(1, 12):
        built, meta = tick(k)
        live_idx = [i for i, (s, d) in enumerate(built) if d == TODAY and s in LIVE_SPORTS]
        assert {built[i][0] for i in live_idx} == LIVE_SPORTS, (k, built)
        if k > 1:  # the first round after a start builds every today sport: liveness is not known yet
            other_idx = [i for i, pair in enumerate(built) if pair not in {(s, TODAY) for s in LIVE_SPORTS}]
            assert not other_idx or max(live_idx) < min(other_idx), (k, built)
        assert meta["live_first"] is True


def test_background_is_bounded_by_the_budget_and_always_moves(tick):
    budget = worker._BOOK_GRID_BACKGROUND_BUDGET_SECONDS_DEFAULT
    longest = max(DURATIONS.values())
    for k in range(1, 12):
        built, meta = tick(k)
        # Every job but the last started inside the budget: the round's background is under the budget plus one job.
        assert meta["background_seconds"] < budget + longest, (k, meta["background_seconds"])
        built_background = [f"{s}@{d}" if d != TODAY else s for s, d in built if f"{s}@{d}" in meta["background_built"]
                            or (d == TODAY and s in meta["background_built"])]
        assert built_background == meta["background_built"], (k, built, meta["background_built"])
        if meta["background_pending"] or meta["background_queued"]:
            assert meta["background_built"] or meta["background_seconds"] == 0, k


def test_nothing_queued_is_dropped(tick):
    queued, drained = [], []
    for k in range(1, 30):
        _, meta = tick(k)
        queued += meta["background_queued"]
        drained += meta["background_built"]
    def has_grid(item):  # queued pairs with no shard are popped and skipped, never built
        sport, _, day = item.partition("@")
        return (sport, day or TODAY) in DURATIONS
    assert queued and sorted(q for q in queued if has_grid(q)) == sorted(drained)
    assert not worker._BOOK_GRID_BACKGROUND_QUEUE
    assert {"nba@2026-11-10", "ncaab@2026-11-10", "nfl@2026-11-12", "soccer@2026-11-12"} <= set(drained)
    assert {"nba", "soccer", "nfl"} <= set(drained), "today's pre-game sports, due by their 600 s, came from the queue"


def test_the_round_with_pre_game_work_due_stays_short(tick):
    """The 20:08:42Z shape: today's pre-game grids due again. Live first, then at most the budget plus one job."""
    for k in range(1, 6):
        tick(k)
    built, meta = tick(6)  # 650 s after round 1: nba / soccer / nfl due by their non-live interval
    assert set(meta["background_queued"]) >= {"nba", "soccer", "nfl"}
    assert {s for s, d in built if d == TODAY} & LIVE_SPORTS == LIVE_SPORTS
    spent = sum(DURATIONS.get(pair, 1.0) for pair in built)
    assert spent <= 13.0 + worker._BOOK_GRID_BACKGROUND_BUDGET_SECONDS_DEFAULT + 60.0, built


def test_off_restores_the_single_sequential_pass(tick, monkeypatch):
    """Reachability: off != on. Off, round 1 builds yesterday and tomorrow in the same pass, in order, and the
    pre-game grids due again are built in the round that finds them due."""
    monkeypatch.setenv("SYNDICATE_BOOK_GRID_LIVE_FIRST", "off")
    built, meta = tick(1)
    assert ("nba", YESTERDAY) in built and ("nfl", TOMORROW) in built and ("soccer", TOMORROW) in built
    assert meta["live_first"] is False and meta["background_built"] == [] and meta["background_queued"] == []
    for k in range(2, 6):
        tick(k)
    built6, _ = tick(6)
    assert {("nba", TODAY), ("soccer", TODAY), ("nfl", TODAY)} <= set(built6)

    monkeypatch.delenv("SYNDICATE_BOOK_GRID_LIVE_FIRST")
    worker._BOOK_GRID_LAST_RUN.clear()
    worker._BOOK_GRID_SPORT_STATE.clear()
    built_on, meta_on = tick(1)
    assert meta_on["live_first"] is True
    assert len(_background(built_on)) < len(_background(built)), "on: the first round drains only part of the queue"


def test_a_queued_pair_the_foreground_builds_leaves_the_queue(tick):
    tick(1)
    worker._BOOK_GRID_BACKGROUND_QUEUE.insert(0, (TODAY, "ncaab"))  # e.g. queued before it went live
    built, _ = tick(2)
    assert built.count(("ncaab", TODAY)) == 1
    assert (TODAY, "ncaab") not in worker._BOOK_GRID_BACKGROUND_QUEUE


def test_the_budget_is_tunable(tick, monkeypatch):
    monkeypatch.setenv("SYNDICATE_BOOK_GRID_BACKGROUND_BUDGET_SECONDS", "0")
    _, meta = tick(1)
    assert len(meta["background_built"]) == 1 and meta["background_pending"] >= 2
    monkeypatch.setenv("SYNDICATE_BOOK_GRID_BACKGROUND_BUDGET_SECONDS", "100000")
    _, meta2 = tick(2)
    assert meta2["background_pending"] == 0


def test_price_on_pull_never_drains_the_queue(tick):
    tick(1)
    pending = list(worker._BOOK_GRID_BACKGROUND_QUEUE)
    assert pending
    # 60 s after round 1 (inside the 120 s interval) a live sport's shard changed: a price-on-pull pass.
    stamp = T0 + 130 + 30
    os.utime(tick.shard, (stamp, stamp))
    built, meta = tick(0, at=stamp + 30)
    assert meta is not None and meta["on_pull"], meta
    assert all(d == TODAY and s in LIVE_SPORTS for s, d in built)
    assert worker._BOOK_GRID_BACKGROUND_QUEUE == pending and meta["background_built"] == []


def test_the_queue_clears_when_the_date_rolls(tick):
    tick(1)
    assert worker._BOOK_GRID_BACKGROUND_QUEUE
    tick.state["today"] = TOMORROW
    _, meta = tick(2)
    assert all(d != YESTERDAY for d, _ in worker._BOOK_GRID_BACKGROUND_QUEUE) or meta["background_pending"] == 0
    assert all(not item.endswith(f"@{YESTERDAY}") for item in meta["background_built"])


def test_a_restart_skips_yesterday_already_rebuilt_on_disk(tick, monkeypatch):
    tick.state["on_disk"] = True
    monkeypatch.setenv("SYNDICATE_BOOK_GRID_BACKGROUND_BUDGET_SECONDS", "100000")
    built, meta = tick(1)
    assert all(d != YESTERDAY for _, d in built)
    assert worker._BOOK_GRID_LAST_RUN["previous_date"] == YESTERDAY and meta["rebuilt_previous"] is None


def test_off_never_consults_the_disk_for_yesterday(tick, monkeypatch):
    tick.state["on_disk"] = True
    monkeypatch.setenv("SYNDICATE_BOOK_GRID_LIVE_FIRST", "off")
    built, _ = tick(1)
    assert ("nba", YESTERDAY) in built


# ---------------------------------------------------------------------------- the on-disk check itself
@pytest.fixture()
def disk(tmp_path):
    shards, grids = tmp_path / "shards", tmp_path / "grids"
    shards.mkdir()
    grids.mkdir()
    rollover = datetime(2026, 11, 11, 6, 0, tzinfo=timezone.utc).timestamp()  # Central midnight starting 11-11

    def setup(present: dict[str, float | None]):
        for sport, offset in present.items():
            (shards / f"{sport}_{YESTERDAY}.jsonl").write_text("{}\n", encoding="utf-8")
            if offset is not None:
                grid = grids / f"{sport}_{YESTERDAY}.json"
                grid.write_text("{}", encoding="utf-8")
                os.utime(grid, (rollover + offset, rollover + offset))

    def check():
        with patch("syndicate.features.shared.odds_book_quotes.book_quotes_path",
                   side_effect=lambda sport, day: shards / f"{sport}_{day}.jsonl"), \
             patch("syndicate.features.shared.book_grid_artifact.book_grid_artifact_path",
                   side_effect=lambda sport, day: grids / f"{sport}_{day}.json"):
            return worker._book_grid_previous_rebuilt_on_disk(YESTERDAY, TODAY)

    return setup, check


def test_on_disk_every_grid_after_the_rollover_is_rebuilt(disk):
    setup, check = disk
    setup({"nba": 60.0, "ncaab": 3600.0})
    assert check() is True


def test_on_disk_one_grid_before_the_rollover_is_not(disk):
    setup, check = disk
    setup({"nba": 60.0, "ncaab": -60.0})
    assert check() is False


def test_on_disk_a_missing_grid_is_not(disk):
    setup, check = disk
    setup({"nba": 60.0, "ncaab": None})
    assert check() is False


def test_on_disk_no_shards_is_unsure_so_not(disk):
    _, check = disk
    assert check() is False
