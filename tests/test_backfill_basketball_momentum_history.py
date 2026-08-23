"""Season backfill: it must produce the SAME artifact shape as live capture,
and must not fabricate the one artifact it cannot know."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import scripts.backfill_basketball_momentum_history as bf
from syndicate.features.shared.basketball_momentum_artifacts import momentum_events_path

HOME, AWAY = "16", "20"


def _summary(home_tri: str, away_tri: str, n: int = 80) -> dict[str, Any]:
    plays = []
    for i in range(n):
        plays.append({
            "period": {"number": 1 + i // 40},
            "clock": {"displayValue": f"{9 - (i % 40) // 5}:{(i * 7) % 60:02d}"},
            "team": {"id": HOME if i % 2 == 0 else AWAY},
            "type": {"text": ""}, "text": "",
            "shootingPlay": True, "pointsAttempted": 2,
            "scoreValue": 2 if i % 3 == 0 else 0,
        })
    return {"header": {"competitions": [{"competitors": [
        {"homeAway": "home", "team": {"id": HOME, "abbreviation": home_tri}},
        {"homeAway": "away", "team": {"id": AWAY, "abbreviation": away_tri}}]}]},
        "plays": plays}


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(bf.time, "sleep", lambda *_: None)


def _wire(monkeypatch, by_date: dict[str, list[str]], summaries: dict[str, Any]):
    monkeypatch.setattr(bf, "all_event_ids", lambda lg, d: by_date.get(d, []))
    monkeypatch.setattr(bf, "fetch_summary", lambda lg, e: summaries.get(e, {}))


def test_writes_the_same_shape_the_live_poller_writes(tmp_path, monkeypatch) -> None:
    """A backfilled date and a captured one must be indistinguishable, or
    `basketball_projection_rows` has to learn which is which."""
    _wire(monkeypatch, {"2026-06-01": ["401", "402"]},
          {"401": _summary("IND", "NYL"), "402": _summary("LAS", "CON")})
    games, rows = bf.backfill_date("wnba", "2026-06-01", out_root=tmp_path)
    assert games == 2 and rows > 0

    doc = json.loads(momentum_events_path(
        tmp_path, league_code="wnba", date_str="2026-06-01").read_text())
    assert doc["schema"] == "basketball_momentum_events_v1"
    for block in doc["games"].values():
        assert block["pressure"] and block["home_tri"] and block["away_tri"]


def test_does_not_fabricate_the_per_tick_causal_record(tmp_path, monkeypatch) -> None:
    """**The jsonl is evidence of what a card SHOWED at instant t.** A backfill
    has no such history, and inventing one would turn a reconstruction into a
    false claim about the past."""
    _wire(monkeypatch, {"2026-06-01": ["401"]}, {"401": _summary("IND", "NYL")})
    bf.backfill_date("wnba", "2026-06-01", out_root=tmp_path)
    assert not list(tmp_path.rglob("live_momentum_*.jsonl"))


def test_is_resumable_and_skips_finished_dates(tmp_path, monkeypatch) -> None:
    """A season backfill that restarts from the top after any interruption is
    one that never finishes."""
    _wire(monkeypatch, {"2026-06-01": ["401"]}, {"401": _summary("IND", "NYL")})
    assert bf.backfill_date("wnba", "2026-06-01", out_root=tmp_path)[0] == 1

    calls: list[str] = []
    monkeypatch.setattr(bf, "fetch_summary",
                        lambda lg, e: calls.append(e) or _summary("IND", "NYL"))
    assert bf.backfill_date("wnba", "2026-06-01", out_root=tmp_path) == (0, 0)
    assert calls == [], "a completed date must not be re-fetched"


def test_overwrite_forces_a_refetch(tmp_path, monkeypatch) -> None:
    _wire(monkeypatch, {"2026-06-01": ["401"]}, {"401": _summary("IND", "NYL")})
    bf.backfill_date("wnba", "2026-06-01", out_root=tmp_path)
    assert bf.backfill_date("wnba", "2026-06-01", out_root=tmp_path,
                            overwrite=True)[0] == 1


def test_an_off_season_date_writes_nothing(tmp_path, monkeypatch) -> None:
    _wire(monkeypatch, {}, {})
    assert bf.backfill_date("wnba", "2026-01-15", out_root=tmp_path) == (0, 0)
    assert not list(tmp_path.rglob("momentum_events_*.json"))


def test_a_run_that_wrote_nothing_exits_nonzero(tmp_path, monkeypatch) -> None:
    """A silent empty run is how a broken fetch gets mistaken for an off-season."""
    _wire(monkeypatch, {}, {})
    code = bf.main(["--league", "wnba", "--start", "2026-01-01",
                    "--end", "2026-01-03", "--data-root", str(tmp_path)])
    assert code == 3


def test_a_multi_date_range_accumulates(tmp_path, monkeypatch) -> None:
    _wire(monkeypatch,
          {"2026-06-01": ["401"], "2026-06-02": ["402", "403"]},
          {"401": _summary("IND", "NYL"), "402": _summary("LAS", "CON"),
           "403": _summary("LVA", "SEA")})
    code = bf.main(["--league", "wnba", "--start", "2026-06-01",
                    "--end", "2026-06-02", "--data-root", str(tmp_path)])
    assert code == 0
    assert len(list(tmp_path.rglob("momentum_events_*.json"))) == 2


def test_a_game_with_no_usable_plays_is_named_not_dropped(tmp_path, monkeypatch) -> None:
    _wire(monkeypatch, {"2026-06-01": ["401", "402"]},
          {"401": _summary("IND", "NYL"), "402": {"header": {}, "plays": []}})
    games, _ = bf.backfill_date("wnba", "2026-06-01", out_root=tmp_path)
    assert games == 1


# ---------------------------------------------------------------------------
# The one-shot hook -- gated in the momentum poller, not the worker entrypoint
# ---------------------------------------------------------------------------

def _poller():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "pbm_hook", "scripts/poll_basketball_momentum.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_the_hook_is_inert_without_the_env_var(tmp_path, monkeypatch) -> None:
    """**Reachability, both directions.** An unset flag must do nothing, or the
    gate is decoration."""
    mod = _poller()
    monkeypatch.delenv("SYNDICATE_WNBA_MOMENTUM_BACKFILL", raising=False)
    assert mod.maybe_start_backfill("wnba", tmp_path) is False


def test_the_hook_fires_when_the_env_var_names_a_range(tmp_path, monkeypatch) -> None:
    mod = _poller()
    monkeypatch.setenv("SYNDICATE_WNBA_MOMENTUM_BACKFILL", "2026-05-01..2026-05-02")
    started: list[str] = []
    monkeypatch.setattr(mod, "_backfill_started", False, raising=False)
    import threading
    monkeypatch.setattr(threading, "Thread",
                        lambda **kw: type("T", (), {"start": lambda self: started.append("x")})())
    assert mod.maybe_start_backfill("wnba", tmp_path) is True
    assert started == ["x"]


def test_it_fires_at_most_once_per_process(tmp_path, monkeypatch) -> None:
    """The poller runs every tick; the backfill must not restart every time."""
    mod = _poller()
    monkeypatch.setenv("SYNDICATE_WNBA_MOMENTUM_BACKFILL", "2026-05-01..2026-05-02")
    import threading
    monkeypatch.setattr(threading, "Thread",
                        lambda **kw: type("T", (), {"start": lambda self: None})())
    assert mod.maybe_start_backfill("wnba", tmp_path) is True
    assert mod.maybe_start_backfill("wnba", tmp_path) is False


def test_a_completed_backfill_is_not_repeated_after_a_restart(tmp_path, monkeypatch) -> None:
    """The sentinel survives the process; a worker that restarts hourly must not
    re-pull a season each time."""
    mod = _poller()
    spec = "2026-05-01..2026-05-02"
    monkeypatch.setenv("SYNDICATE_WNBA_MOMENTUM_BACKFILL", spec)
    sentinel = mod._backfill_sentinel(tmp_path, "wnba", spec)
    sentinel.parent.mkdir(parents=True, exist_ok=True)
    sentinel.write_text(spec, encoding="utf-8")
    assert mod.maybe_start_backfill("wnba", tmp_path) is False


def test_a_malformed_spec_is_refused_and_named(tmp_path, monkeypatch, capsys) -> None:
    mod = _poller()
    monkeypatch.setenv("SYNDICATE_WNBA_MOMENTUM_BACKFILL", "2026-05-01")   # no range
    assert mod.maybe_start_backfill("wnba", tmp_path) is False
    assert "BACKFILL_BAD_SPEC" in capsys.readouterr().out


def test_the_scoreboard_url_has_exactly_one_sports_segment() -> None:
    """**THE 400 THAT KILLED THE FIRST SEASON PULL.**

    `_SPORT_PATH` already contains `sports/`. The backfill originally retyped
    the URL and prefixed it again, producing
    `.../v2/sports/sports/basketball/wnba/scoreboard` -- HTTP 400 on every date,
    measured 2026-08-23 16:04Z across the whole range.

    Both callers now share one builder, and this pins the shape so a future
    retype cannot reintroduce it.
    """
    from scripts.poll_basketball_momentum import scoreboard_url

    for league in ("wnba", "nba", "ncaab"):
        url = scoreboard_url(league, "2026-06-19")
        assert url.count("/sports/") == 1, url
        assert url.endswith("/scoreboard?dates=20260619"), url


def test_the_backfill_and_the_poller_build_the_same_url() -> None:
    """Two callers, one construction -- the property that makes the bug above
    impossible rather than merely fixed."""
    import scripts.backfill_basketball_momentum_history as backfill
    from scripts.poll_basketball_momentum import scoreboard_url

    assert backfill.scoreboard_url is scoreboard_url
