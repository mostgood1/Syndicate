"""The incremental quote read's periodic check runs AFTER the build when the caller asks (todo #790, lane
nba-grid-check-after-build).

Measured on the fleet's 11-16 NBA slate: the check (a one-pass reference read of the whole shard plus a row-for-row
compare) cost 3.2-17.5 s inside 10 of 214 NBA grid builds, 3 of the 18 that crossed the 45 s slow-sport line. These
tests pin: inside `checks_after_build()` a due check is listed, not run, and the build line says so; outside a scope,
or with the switch off, it runs inline exactly as before (off != on); a check run later covers the bytes the build
read, whatever was appended since; a mismatch found later still turns the read off; a replaced file skips the check
and starts over; a check never run stays due; only the thread that opened the scope defers. And through the REAL
`_run_book_grid_artifact_tick`: the check's time is outside `build_seconds`, runs after the publish, and a mismatch
rebuilds the sport at once.
"""

from __future__ import annotations

import importlib.util
import json
import random
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from syndicate.features.shared import book_grid_quote_read as qr
from syndicate.features.shared.book_grid import freshest_rows_for_grid
from syndicate.features.shared.odds_book_quotes import book_quotes_path, iter_book_quotes

SPORT, DATE = "nba", "2099-11-16"


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    for name in (qr.ENABLED_ENV, qr.VERIFY_SECONDS_ENV, qr.CHECK_AFTER_BUILD_ENV):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(qr.VERIFY_SECONDS_ENV, "0")  # every build is due, so each test decides only WHERE it runs
    qr.reset_state()
    yield
    qr.reset_state()


def _shard() -> Path:
    path = book_quotes_path(SPORT, DATE)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _rows(rng: random.Random, n: int, clock: list[int]) -> str:
    """Re-quotes, ties, line moves (new anchors) and one bad line in fifty: what the reduce decides on."""
    out = []
    for _ in range(n):
        clock[0] += rng.choice([0, 1, 2, 5])
        stamp = f"2099-11-16T{(clock[0] // 3600) % 24:02d}:{(clock[0] // 60) % 60:02d}:{clock[0] % 60:02d}Z"
        market, base = rng.choice([("h2h", None), ("spreads", 5.5), ("totals", 221.5)])
        line = None if base is None else base + rng.choice([-1.0, -0.5, 0.0, 0.5, 1.0])
        out.append(json.dumps({
            "sport": SPORT, "kind": "game", "event_id": rng.choice(["e1", "e2"]), "segment": "", "market": market,
            "player_name": "", "selection": rng.choice(["home", "away"] if market != "totals" else ["over", "under"]),
            "line": line, "price": rng.choice([-110, -105, 100, 120]), "bookmaker": rng.choice(["fanduel", "pinnacle"]),
            "book_updated_at": stamp, "snapshot_ts": stamp, "captured_at": stamp,
            "home_team": "Home", "away_team": "Away", "commence_time": "2099-11-17T00:00:00Z",
        }))
        if rng.random() < 0.02:
            out.append('{"price": -110, "bookmak')
    return "\n".join(out) + "\n"


def _append(text: str) -> None:
    with open(_shard(), "ab") as handle:
        handle.write(text.encode("utf-8"))


def _one_pass() -> list[dict]:
    return freshest_rows_for_grid(iter_book_quotes(SPORT, DATE), report=False)


def _verify_field(out: str) -> list[str]:
    return re.findall(r"BOOK_GRID_QUOTE_READ sport=\S+ date=\S+ .*?verify=(\S+)", out)


def _state() -> qr._ShardState:
    (state,) = qr._STATES.values()
    return state


def test_inside_the_scope_a_due_check_is_listed_not_run(capsys):
    _append(_rows(random.Random(1), 200, [0]))
    with qr.checks_after_build() as pending:
        rows, _ = qr.read_grid_quote_rows(SPORT, DATE)
    out = capsys.readouterr().out
    assert rows == _one_pass()
    assert pending == [(SPORT, DATE)]
    assert _verify_field(out) == ["deferred"], out
    assert "BOOK_GRID_QUOTE_READ_CHECK" not in out
    before = _state().verified_at

    results = qr.run_checks_after_build(pending)
    out = capsys.readouterr().out
    assert results == {(SPORT, DATE): "match"}
    assert pending == []
    assert re.search(rf"BOOK_GRID_QUOTE_READ_CHECK sport={SPORT} date={DATE} result=match kept=\d+ rows=\d+ "
                     r"check_s=\S+ when=after_build", out), out
    assert _state().verified_at > before


def test_outside_any_scope_the_check_runs_inline_as_before(capsys):
    _append(_rows(random.Random(2), 150, [0]))
    rows, _ = qr.read_grid_quote_rows(SPORT, DATE)
    assert rows == _one_pass()
    assert _verify_field(capsys.readouterr().out) == ["match"]


@pytest.mark.parametrize("switch, expected, listed", [(None, "deferred", True), ("1", "deferred", True),
                                                       ("0", "match", False), ("off", "match", False)])
def test_off_is_not_on(monkeypatch, capsys, switch, expected, listed):
    """REACHABILITY: the same build inside the same scope defers with the switch on (absent = on) and checks inline
    with it off."""
    if switch is not None:
        monkeypatch.setenv(qr.CHECK_AFTER_BUILD_ENV, switch)
    _append(_rows(random.Random(3), 150, [0]))
    with qr.checks_after_build() as pending:
        rows, _ = qr.read_grid_quote_rows(SPORT, DATE)
    assert rows == _one_pass()
    assert _verify_field(capsys.readouterr().out) == [expected]
    assert (pending == [(SPORT, DATE)]) is listed


def test_a_later_check_covers_the_bytes_the_build_read_whatever_was_appended(capsys):
    rng, clock = random.Random(4), [0]
    _append(_rows(rng, 200, clock))
    with qr.checks_after_build() as pending:
        built, _ = qr.read_grid_quote_rows(SPORT, DATE)
    _append(_rows(rng, 60, clock))  # a capture lands between the build and its check
    capsys.readouterr()
    assert qr.run_checks_after_build(pending) == {(SPORT, DATE): "match"}
    kept = int(re.search(r"BOOK_GRID_QUOTE_READ_CHECK .* kept=(\d+)", capsys.readouterr().out).group(1))
    assert kept == len(built)
    # The next build still reads the appended lines, from where the last build stopped.
    rows, _ = qr.read_grid_quote_rows(SPORT, DATE)
    out = capsys.readouterr().out
    assert rows == _one_pass()
    assert re.search(r"mode=incremental new_rows=[1-9]", out), out


def test_a_mismatch_found_after_the_build_turns_the_read_off(capsys):
    rng, clock = random.Random(5), [0]
    _append(_rows(rng, 200, clock))
    with qr.checks_after_build() as pending:
        qr.read_grid_quote_rows(SPORT, DATE)
    # Corrupt the kept state the way a reducer bug would: forget the anchors.
    _state().reducer.anchors.clear()
    _state().reducer.anchor_indices.clear()
    capsys.readouterr()
    assert qr.run_checks_after_build(pending) == {(SPORT, DATE): "MISMATCH"}
    out = capsys.readouterr().out
    assert "BOOK_GRID_QUOTE_READ_VERIFY" in out and "result=MISMATCH" in out
    assert "result=MISMATCH" in re.search(r"BOOK_GRID_QUOTE_READ_CHECK .*", out).group(0)
    assert qr._DISABLED is not None
    _append(_rows(rng, 10, clock))
    rows, _ = qr.read_grid_quote_rows(SPORT, DATE)
    assert rows == _one_pass()
    assert "mode=full:disabled_after_mismatch" in capsys.readouterr().out


def test_a_replaced_file_skips_the_check_and_starts_over(capsys):
    rng, clock = random.Random(6), [0]
    _append(_rows(rng, 120, clock))
    with qr.checks_after_build() as pending:
        qr.read_grid_quote_rows(SPORT, DATE)
    other = _shard().with_name("replacement.jsonl")
    other.write_text(_rows(rng, 90, clock), encoding="utf-8")
    other.replace(_shard())
    assert qr.run_checks_after_build(pending) == {(SPORT, DATE): "skipped:replaced"}
    assert qr._STATES == {}
    assert qr._DISABLED is None
    capsys.readouterr()
    rows, _ = qr.read_grid_quote_rows(SPORT, DATE)
    assert rows == _one_pass()
    assert "mode=fresh:new" in capsys.readouterr().out


def test_a_check_never_run_stays_due(capsys):
    rng, clock = random.Random(7), [0]
    _append(_rows(rng, 100, clock))
    with qr.checks_after_build():
        qr.read_grid_quote_rows(SPORT, DATE)  # the caller never runs it (its build raised, say)
    _append(_rows(rng, 10, clock))
    with qr.checks_after_build() as pending:
        qr.read_grid_quote_rows(SPORT, DATE)
    assert pending == [(SPORT, DATE)]
    assert _verify_field(capsys.readouterr().out) == ["deferred", "deferred"]


def test_only_the_thread_that_opened_the_scope_defers(capsys):
    _append(_rows(random.Random(8), 100, [0]))
    seen: list[list] = []
    with qr.checks_after_build() as pending:
        worker = threading.Thread(target=lambda: seen.append(list(qr.read_grid_quote_rows(SPORT, DATE)[0])))
        worker.start()
        worker.join()
    assert pending == []
    assert seen and seen[0] == _one_pass()
    assert _verify_field(capsys.readouterr().out) == ["match"]


def test_a_check_with_no_state_or_after_the_read_is_off_is_skipped(capsys):
    assert qr.run_checks_after_build([(SPORT, DATE)]) == {(SPORT, DATE): "skipped:no_shard"}
    _append(_rows(random.Random(9), 50, [0]))
    assert qr.run_checks_after_build([(SPORT, DATE)]) == {(SPORT, DATE): "skipped:no_state"}
    qr._DISABLED = "x/y"
    assert qr.run_checks_after_build([(SPORT, DATE)]) == {(SPORT, DATE): "skipped:disabled"}


# --------------------------------------------------------------------------- through the real refresh-worker tick

_SPEC = importlib.util.spec_from_file_location(
    "run_refresh_worker_check_after_build", Path(__file__).resolve().parent.parent / "scripts" / "run_refresh_worker.py"
)
worker = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(worker)

TODAY = "2026-11-16"
T0 = datetime(2026, 11, 17, 1, 30, tzinfo=timezone.utc).timestamp()
LIVE = {"rows": [{"game": {"state": "live"}, "commence_time": "2026-11-17T00:30:00Z"}], "rows_total": 1}
BUILD_S, CHECK_S = 40.0, 15.0


@pytest.fixture()
def tick(tmp_path, monkeypatch):
    for name in ("SYNDICATE_BOOK_GRID_LIVE_FIRST", "SYNDICATE_BOOK_GRID_SLOW_SPORT_SCHEDULE",
                 "SYNDICATE_BOOK_GRID_PRICE_ON_PULL", "SYNDICATE_BOOK_GRID_SKIP_NONLIVE_SPORTS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SYNDICATE_BOOK_GRID_SLOW_SPORT_SECONDS", "1000")
    shard = tmp_path / f"{TODAY}.jsonl"
    shard.write_text(_rows(random.Random(11), 150, [0]), encoding="utf-8")
    clock = [1000.0]
    events: list[str] = []
    monkeypatch.setattr(worker, "_book_grid_build_clock", lambda: clock[0])
    real_verify = qr._verify

    def costly_verify(*args, **kwargs):
        clock[0] += CHECK_S  # the reference read's time, on the same clock the build is measured with
        events.append("check")
        return real_verify(*args, **kwargs)

    monkeypatch.setattr(qr, "_verify", costly_verify)

    def build(sport, day):
        if sport != "nba" or day != TODAY:
            return None
        rows, _ = qr.read_grid_quote_rows(sport, day)  # the REAL read, on a real shard
        assert rows
        clock[0] += BUILD_S
        events.append("build")
        return LIVE

    def run(k: int = 1):
        worker._BOOK_GRID_LAST_RUN.clear()
        worker._BOOK_GRID_SPORT_STATE.clear()
        worker._BOOK_GRID_BACKGROUND_QUEUE.clear()
        events.clear()
        with patch.object(worker.time, "time", return_value=T0 + 130 * k), \
             patch.object(worker, "central_today_iso", return_value=TODAY), \
             patch.object(worker, "_book_grid_forward_days", return_value=0), \
             patch.object(worker, "_book_grid_refresh_interval_seconds", return_value=120), \
             patch.object(worker, "_sport_covers_date", return_value=True), \
             patch.object(worker, "_book_grid_previous_rebuilt_on_disk", return_value=True), \
             patch("syndicate.features.shared.book_grid_artifact.build_book_grid_artifact", side_effect=build), \
             patch("syndicate.features.shared.book_grid_artifact.write_book_grid_artifact", return_value=shard), \
             patch("syndicate.features.shared.artifact_publisher.publish_hot_artifact",
                   side_effect=lambda *a, **k: events.append("publish") or True), \
             patch("syndicate.features.shared.artifact_publisher.pull_streamed_artifact", return_value=None), \
             patch("syndicate.features.shared.odds_book_quotes.book_quotes_path", return_value=shard), \
             patch("syndicate.features.shared.refresh_state_store.data_root", return_value=tmp_path):
            return worker._run_book_grid_artifact_tick()

    run.events = events
    return run


def test_the_tick_measures_the_build_without_its_check_and_checks_after_the_publish(tick, capsys):
    meta = tick()
    out = capsys.readouterr().out
    assert meta["build_seconds"]["nba"] == BUILD_S
    assert tick.events == ["build", "publish", "check"]
    assert _verify_field(out) == ["deferred"]
    assert "BOOK_GRID_QUOTE_READ_CHECK sport=nba date=2026-11-16 result=match" in out


def test_off_the_tick_checks_inside_the_build_as_before(tick, capsys, monkeypatch):
    """REACHABILITY through the tick: off, the check's time is back inside `build_seconds`."""
    monkeypatch.setenv(qr.CHECK_AFTER_BUILD_ENV, "off")
    meta = tick()
    out = capsys.readouterr().out
    assert meta["build_seconds"]["nba"] == BUILD_S + CHECK_S
    assert tick.events == ["check", "build", "publish"]
    assert _verify_field(out) == ["match"]
    assert "BOOK_GRID_QUOTE_READ_CHECK" not in out


def test_a_mismatch_after_the_build_rebuilds_the_sport_at_once_from_the_one_pass_read(tick, capsys):
    def corrupt_then_check(pending):
        qr._STATES[next(iter(qr._STATES))].reducer.anchors.clear()
        qr._STATES[next(iter(qr._STATES))].reducer.anchor_indices.clear()
        return real_run(pending)

    real_run = qr.run_checks_after_build
    with patch.object(qr, "run_checks_after_build", side_effect=corrupt_then_check):
        meta = tick()
    out = capsys.readouterr().out
    assert tick.events == ["build", "publish", "check", "build", "publish"]
    assert "result=MISMATCH" in out
    assert re.findall(r"BOOK_GRID_QUOTE_READ sport=nba date=\S+ mode=(\S+)", out) == [
        "fresh:new", "full:disabled_after_mismatch"]
    assert meta["written"].count("nba:1") == 2
