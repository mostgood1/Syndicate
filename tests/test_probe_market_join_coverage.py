"""The coverage probe, and proof it refuses to overstate a join.

**A COVERAGE REPORT THAT ALWAYS SAYS "JOINABLE" IS WORSE THAN NO REPORT**, because
it converts an impossible analysis into a confident one. `CLAUDE.md` records the
MLB case this exists to prevent: four families whose windows overlapped on ONE
usable date while the analysis looked like it ran on months of data.

So every test here is about the probe saying NO when it should. Each of the three
requirements is withheld in turn, plus the subtler one -- a quote stream that
exists but never moves, which is a pre-tip snapshot rather than a live line.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import scripts.probe_market_join_coverage as probe
from syndicate.features.shared.basketball_momentum_artifacts import (
    momentum_artifact_path,
    momentum_events_path,
)

DAY = "2026-08-20"
EVENT = "401857100"


def _write_state(root: Path, day: str = DAY, event: str = EVENT) -> None:
    path = momentum_events_path(root, league_code="wnba", date_str=day)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"games": {event: {
        "pressure": [{"clock_seconds": 10.0, "possession_index": 1.0,
                      "sign": 1.0, "weight": 1.0, "type": "shot_attempt_2",
                      "team": "IND"}],
        "narrator": [{"clock_seconds": 10.0, "possession_index": 1.0,
                      "team": "IND", "sign": 1.0, "weight": 2.0}],
        "home_tri": "IND", "away_tri": "NYL"}}}))


def _write_bridge(root: Path, day: str = DAY, event: str = EVENT) -> None:
    path = momentum_artifact_path(root, league_code="wnba", date_str=day)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps({"payload": {
        "generated_at": f"{day}T23:0{i}:00Z",
        "games": {event: {"as_of_seconds": 300.0 + 60 * i}},
    }}) for i in range(3)))


def _quote(day: str, event: str, captured_at: str, line: float,
           segment: str = "q3", market: str = "totals") -> dict:
    return {"captured_at": captured_at, "sport": "wnba", "date": day,
            "event_id": event, "bookmaker": "fanduel", "market": market,
            "segment": segment, "selection": "Over", "line": line, "price": -110}


def _write_quotes(root: Path, rows: list[dict], day: str = DAY) -> None:
    path = (root / "wnba_source" / "tracking" / "book_quotes" / f"{day}.jsonl")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows))


def _moving_quotes(day: str = DAY, event: str = EVENT) -> list[dict]:
    return [_quote(day, event, f"{day}T23:0{i}:30Z", 52.5 + i * 0.5) for i in range(3)]


def _run(root: Path, capsys) -> tuple[int, str]:
    code = probe.main(["--league", "wnba", "--start", DAY, "--end", DAY,
                       "--data-root", str(root)])
    return code, capsys.readouterr().out


@pytest.fixture(autouse=True)
def _isolate_data_root(monkeypatch):
    """`--data-root` is applied by SETTING the env the real path helpers read.
    Undo it between tests so one case cannot leak into the next."""
    monkeypatch.delenv("SYNDICATE_DATA_ROOT", raising=False)


# --------------------------------------------------------------------------
# It says YES when all three are present


def test_all_three_present_reads_as_joinable(tmp_path, capsys) -> None:
    _write_state(tmp_path)
    _write_bridge(tmp_path)
    _write_quotes(tmp_path, _moving_quotes())
    code, out = _run(tmp_path, capsys)
    assert code == 0, out
    assert "VERDICT JOINABLE on 1 date(s)" in out, out
    assert f"USABLE_DATES n=1" in out, out


# --------------------------------------------------------------------------
# It says NO when any one of them is missing


def test_no_state_is_not_joinable(tmp_path, capsys) -> None:
    _write_bridge(tmp_path)
    _write_quotes(tmp_path, _moving_quotes())
    code, out = _run(tmp_path, capsys)
    assert code == 4 and "VERDICT NOT_JOINABLE" in out, out


def test_no_quotes_is_not_joinable(tmp_path, capsys) -> None:
    _write_state(tmp_path)
    _write_bridge(tmp_path)
    code, out = _run(tmp_path, capsys)
    assert code == 4 and "VERDICT NOT_JOINABLE" in out, out


def test_no_clock_bridge_is_not_joinable(tmp_path, capsys) -> None:
    """**THE REQUIREMENT MOST LIKELY TO BE ASSUMED.** State and quotes both
    present and rich -- and the join is still impossible, because game-clock
    seconds cannot be placed against wall-clock captures without the bridge."""
    _write_state(tmp_path)
    _write_quotes(tmp_path, _moving_quotes())
    code, out = _run(tmp_path, capsys)
    assert code == 4, out
    assert "bridge_pairs=0" in out, out


def test_a_bridge_without_as_of_seconds_bridges_nothing(tmp_path, capsys) -> None:
    """A capture with a wall clock and no game clock is half a bridge, and half
    a bridge reads as none."""
    _write_state(tmp_path)
    _write_quotes(tmp_path, _moving_quotes())
    path = momentum_artifact_path(tmp_path, league_code="wnba", date_str=DAY)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"payload": {
        "generated_at": f"{DAY}T23:00:00Z", "games": {EVENT: {"blocks": 1}}}}))
    code, out = _run(tmp_path, capsys)
    assert code == 4 and "bridge_pairs=0" in out, out


# --------------------------------------------------------------------------
# And NO to the subtle one: quotes that exist but never move


def test_a_single_pre_tip_snapshot_is_not_a_live_line(tmp_path, capsys) -> None:
    """**THE POINT OF `instants_per_event`.** One capture of a Q3 total is not
    something anyone could have bet into at 3:00 of Q3. Interval rows exist,
    every family is present, and it still must not read as joinable."""
    _write_state(tmp_path)
    _write_bridge(tmp_path)
    _write_quotes(tmp_path, [_quote(DAY, EVENT, f"{DAY}T22:00:00Z", 52.5)])
    code, out = _run(tmp_path, capsys)
    assert code == 4, out
    assert "quote_interval_rows=1" in out, "the rows ARE there"
    assert "instants_per_event=[1]" in out, out
    assert "VERDICT NOT_JOINABLE" in out, out


def test_many_books_at_one_instant_are_still_one_instant(tmp_path, capsys) -> None:
    """Seven books quoting the same tick is breadth, not movement. Counting rows
    instead of instants would call this a live line."""
    _write_state(tmp_path)
    _write_bridge(tmp_path)
    rows = [dict(_quote(DAY, EVENT, f"{DAY}T22:00:00Z", 52.5), bookmaker=f"book{i}")
            for i in range(7)]
    _write_quotes(tmp_path, rows)
    code, out = _run(tmp_path, capsys)
    assert "quote_interval_rows=7" in out, out
    assert "instants_per_event=[1]" in out, out
    assert code == 4, out


# --------------------------------------------------------------------------
# Selection


def test_full_game_and_moneyline_rows_are_not_interval_lines(tmp_path, capsys) -> None:
    """`segment=full` is the game line, and a moneyline carries no number to
    project against. Counting either would inflate coverage."""
    _write_state(tmp_path)
    _write_bridge(tmp_path)
    rows = [_quote(DAY, EVENT, f"{DAY}T23:0{i}:00Z", 165.5, segment="full") for i in range(3)]
    rows += [dict(_quote(DAY, EVENT, f"{DAY}T23:0{i}:00Z", 0.0, market="h2h"), line=None)
             for i in range(3)]
    _write_quotes(tmp_path, rows)
    code, out = _run(tmp_path, capsys)
    assert "quote_interval_rows=0" in out, out
    assert code == 4, out


def test_an_event_present_in_only_one_family_does_not_count(tmp_path, capsys) -> None:
    """Both families can be rich on the same date and share no game. Overlap is
    on EVENT, not on date."""
    _write_state(tmp_path)
    _write_bridge(tmp_path)
    _write_quotes(tmp_path, _moving_quotes(event="999999999"))
    code, out = _run(tmp_path, capsys)
    assert "event_overlap=0" in out, out
    assert code == 4, out


def test_usable_dates_are_listed_not_just_counted(tmp_path, capsys) -> None:
    """A count alone cannot be checked against the calendar. The dates
    themselves are what makes a thin result visible in a report."""
    _write_state(tmp_path)
    _write_bridge(tmp_path)
    _write_quotes(tmp_path, _moving_quotes())
    _, out = _run(tmp_path, capsys)
    assert f"dates=['{DAY}']" in out, out


# --------------------------------------------------------------------------
# The one-shot gate


def _poller():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "pbm_join_hook", "scripts/poll_basketball_momentum.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ENV = "SYNDICATE_WNBA_MARKET_JOIN_PROBE"


def test_the_gate_is_inert_without_the_env_var(tmp_path, monkeypatch) -> None:
    """Reachability, both directions. An unset flag must do nothing."""
    mod = _poller()
    monkeypatch.delenv(ENV, raising=False)
    assert mod.maybe_start_join_probe("wnba", tmp_path) is False


def test_the_gate_fires_once_when_the_env_names_a_range(tmp_path, monkeypatch) -> None:
    mod = _poller()
    monkeypatch.setenv(ENV, "2026-08-11..2026-08-23")
    import threading
    monkeypatch.setattr(threading, "Thread",
                        lambda **kw: type("T", (), {"start": lambda self: None})())
    assert mod.maybe_start_join_probe("wnba", tmp_path) is True
    assert mod.maybe_start_join_probe("wnba", tmp_path) is False, "at most once per process"


def test_a_malformed_spec_is_named_not_ignored(tmp_path, monkeypatch, capsys) -> None:
    """Silently treating a bad spec like an unset one is how someone sets a
    single date, expects a season, and gets nothing said."""
    mod = _poller()
    monkeypatch.setenv(ENV, "2026-08-11")
    assert mod.maybe_start_join_probe("wnba", tmp_path) is False
    assert "JOIN_PROBE_BAD_SPEC" in capsys.readouterr().out


def test_not_joinable_does_NOT_seal_the_sentinel(tmp_path, monkeypatch, capsys) -> None:
    """**THE ONE THING THIS GATE DOES DIFFERENTLY FROM ITS FIVE SIBLINGS.**
    Exit 4 is NOT_JOINABLE -- a fact about today's data, which changes as more
    slates land. Writing the sentinel would turn "not yet" into "never asked
    again", and the answer would silently stop being re-checked."""
    mod = _poller()
    monkeypatch.setenv(ENV, "2026-08-11..2026-08-23")
    spec = "2026-08-11..2026-08-23"
    sentinel = mod._backfill_sentinel(tmp_path, "wnba", f"join_probe_{spec}")

    # Run the gate's thread body inline rather than in a thread.
    captured: list = []
    import threading
    monkeypatch.setattr(threading, "Thread",
                        lambda target=None, **kw: type(
                            "T", (), {"start": lambda self: captured.append(target())})())

    monkeypatch.setattr(mod, "_join_probe_started", False, raising=False)
    mod.maybe_start_join_probe("wnba", tmp_path)
    out = capsys.readouterr().out
    assert "JOIN_PROBE_DONE" in out and "exit=4" in out, out
    assert not sentinel.exists(), (
        "a NOT_JOINABLE verdict must stay re-checkable as later slates land")


def test_joinable_DOES_seal_the_sentinel(tmp_path, monkeypatch, capsys) -> None:
    """The other direction, so the test above is about exit 4 and not about the
    sentinel never being written at all."""
    mod = _poller()
    _write_state(tmp_path)
    _write_bridge(tmp_path)
    _write_quotes(tmp_path, _moving_quotes())
    spec = f"{DAY}..{DAY}"
    monkeypatch.setenv(ENV, spec)
    sentinel = mod._backfill_sentinel(tmp_path, "wnba", f"join_probe_{spec}")

    import threading
    monkeypatch.setattr(threading, "Thread",
                        lambda target=None, **kw: type(
                            "T", (), {"start": lambda self: target()})())
    monkeypatch.setattr(mod, "_join_probe_started", False, raising=False)
    mod.maybe_start_join_probe("wnba", tmp_path)
    out = capsys.readouterr().out
    assert "exit=0" in out, out
    assert sentinel.exists(), out
