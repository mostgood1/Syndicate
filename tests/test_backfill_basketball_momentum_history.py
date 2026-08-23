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
