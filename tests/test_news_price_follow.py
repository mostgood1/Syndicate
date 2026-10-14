"""news_price_follow: material events only (baseline skipped), next-game join, per-book latency vs placebo, stale EV."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _load():
    spec = importlib.util.spec_from_file_location(
        "news_price_follow", Path(__file__).resolve().parents[1] / "scripts" / "news_price_follow.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def _inj(captured: str, event: str, athlete: str, status: str | None, previous: str | None = None) -> dict:
    return {"event": event, "captured_at": captured, "athlete": athlete, "team": "Kansas City Chiefs", "status": status,
            "previous_status": previous, "source_updated_at": captured}


def test_material_events_only_and_the_baseline_run_is_skipped(tmp_path):
    p = _load()
    _jsonl(tmp_path / "news" / "nfl" / "injuries" / "2026-10-13.jsonl", [
        _inj("2026-10-13T19:31:16Z", "new", "Baseline Out", "Out"),                       # first run: baseline
        _inj("2026-10-14T15:01:16Z", "changed", "Rashee Rice", "Out", "Questionable"),     # to_out
        _inj("2026-10-14T15:11:16Z", "changed", "CeeDee Lamb", "Questionable", "Questionable"),  # comment only
        _inj("2026-10-14T15:21:16Z", "cleared", "Back Again", None, "Injured Reserve"),    # to_in
        _inj("2026-10-14T15:31:16Z", "new", "Fresh Q", "Questionable"),                    # not material
        _inj("2026-10-14T15:41:16Z", "new", "Fresh Out", "Out"),                           # to_out
    ])
    events = p.injury_events(tmp_path, "nfl", "2026-10-13", "2026-10-15")
    assert [(e["player"], e["kind"]) for e in events] == [("Rashee Rice", "to_out"), ("Back Again", "to_in"),
                                                           ("Fresh Out", "to_out")]


def test_a_scratch_event_is_its_first_sighting(tmp_path):
    p = _load()
    rec = {"game_id": "7", "start_utc": "2026-10-15T00:30:00Z", "away": "COL", "home": "DAL", "home_scratches": []}
    _jsonl(tmp_path / "news" / "nhl" / "gameinfo" / "2026-10-15.jsonl", [
        dict(rec, captured_at="2026-10-15T00:01:16Z", away_scratches=[{"name": "Cale Makar"}]),
        dict(rec, captured_at="2026-10-15T00:11:16Z", away_scratches=[{"name": "Cale Makar"}, {"name": "Ross Colton"}]),
    ])
    events = sorted(p.scratch_events(tmp_path, "2026-10-14", "2026-10-15"), key=lambda e: e["player"])
    assert [(e["player"], e["t0"], e["team"]) for e in events] == [("Cale Makar", "2026-10-15T00:01:16Z", "COL"),
                                                                    ("Ross Colton", "2026-10-15T00:11:16Z", "COL")]


def _q(ts: str, book: str, selection: str, price: int, *, line: float = 4.5, market: str = "Receptions",
       player: str | None = "Travis Kelce", event: str = "e1", commence: str = "2026-10-18T20:00:00Z",
       kind: str = "prop") -> dict:
    return {"captured_at": ts, "bookmaker": book, "selection": selection, "price": price, "line": line, "market": market,
            "player_name": player, "event_id": event, "commence_time": commence, "kind": kind,
            "home_team": "Kansas City Chiefs", "away_team": "Las Vegas Raiders"}


def test_latency_placebo_and_stale_ev(tmp_path):
    p = _load()
    _jsonl(tmp_path / "news" / "nfl" / "injuries" / "2026-10-14.jsonl", [
        _inj("2026-10-13T19:31:16Z", "new", "Baseline", "Questionable"),
        _inj("2026-10-14T15:00:00Z", "changed", "Travis Kelce", "Out", "Questionable"),
    ])
    quotes = [
        # both books quote before the news (and once in the placebo window, 24 h earlier: only fanduel moves)
        _q("2026-10-13T12:00:00Z", "fanduel", "over", -110), _q("2026-10-13T12:00:00Z", "fanduel", "under", -110),
        _q("2026-10-13T12:00:00Z", "draftkings", "over", -110), _q("2026-10-13T12:00:00Z", "draftkings", "under", -110),
        _q("2026-10-13T15:30:00Z", "fanduel", "over", -112),
        # after the news: fanduel moves at +5 min to a lower line two-sided; draftkings never moves
        _q("2026-10-14T15:05:00Z", "fanduel", "over", 150, line=4.5), _q("2026-10-14T15:05:00Z", "fanduel", "under", -180, line=4.5),
        # an unrelated game the team does not play in -- ignored
        _q("2026-10-14T15:01:00Z", "fanduel", "over", 100, event="e2", player="Someone Else"),
    ]
    _jsonl(tmp_path / "nfl_source" / "tracking" / "book_quotes" / "2026_wk7.jsonl", quotes)
    report = p.analyze(tmp_path, "2026-10-14", "2026-10-14", ["nfl"])
    ev = [e for e in report["sports"]["nfl"]["events"] if e["player"] == "Travis Kelce"][0]
    assert ev["matched"] and ev["game"] == "e1" and ev["game_lines"] is None   # no game-line quotes in this fixture
    own = ev["own_props"]
    assert own["latency_min"] == {"fanduel": 5.0, "draftkings": None}
    assert own["moved_within"] == {15: 1, 60: 1}
    assert own["placebo_moved_within"] == {15: 0, 60: 1}     # fanduel's -112 at 15:30 the day before, 30 min into it
    # draftkings' over -110 at 4.5 is still up after fanduel moved to +150 / -180: over is now cheap -> negative EV,
    # its under -110 is now a gift -> positive EV
    by_side = {s["selection"]: s for s in own["stale"] if s["book"] == "draftkings"}
    assert by_side["under"]["ev_pct"] > 0 > by_side["over"]["ev_pct"]
    summary = report["sports"]["nfl"]["summary"]
    assert summary["matched"] == 1 and summary["median_poll_gap_min"] is None   # one capture time within the hour
    to_out = summary["own_props.to_out"]
    assert to_out["events"] == 1 and to_out["stale_quotes"] == 2 and to_out["median_latency_min_by_book"] == {"fanduel": 5.0}
    assert to_out["stale_ev_positive_share"] == 0.5 and summary["game_lines.to_out"]["events"] == 0


def test_load_quotes_takes_the_fuller_copy_and_the_date_window(tmp_path):
    import gzip

    p = _load()
    d = tmp_path / "nhl_source" / "tracking" / "book_quotes"
    _jsonl(d / "2026-10-14.jsonl", [_q("2026-10-14T10:00:00Z", "fanduel", "over", 100)])
    d.mkdir(parents=True, exist_ok=True)
    with gzip.open(d / "2026-10-14.jsonl.gz", "wt", encoding="utf-8") as fh:
        for i in range(3):
            fh.write(json.dumps(_q(f"2026-10-14T1{i}:00:00Z", "fanduel", "over", 100 + i)) + "\n")
    _jsonl(d / "2026-09-01.jsonl", [_q("2026-09-01T10:00:00Z", "fanduel", "over", 100)])  # outside the window
    assert len(p.load_quotes(tmp_path, "nhl", "2026-10-14", "2026-10-14")) == 3
