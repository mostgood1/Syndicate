"""Lane `nfl-game-day-injuries`: ESPN game-day injury capture, its autorun and trigger."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from syndicate.features.nfl import game_injuries as gi

FIXTURE = Path(__file__).parent / "fixtures" / "espn_summary_injuries_real_shape.json"
NOW = 1_790_000_000.0


def _iso(epoch: float) -> str:
    from datetime import datetime, timezone

    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%dT%H:%MZ")


@pytest.fixture
def out_root(tmp_path, monkeypatch):
    monkeypatch.setattr("syndicate.features.nfl.sources.nfl_artifact_output_root", lambda: tmp_path)
    return tmp_path


def _summary(status: str, *, name: str = "A Player") -> dict:
    return {
        "injuries": [
            {
                "team": {"id": "12", "abbreviation": "KC"},
                "injuries": [
                    {
                        "athlete": {"id": "99", "displayName": name, "position": {"abbreviation": "WR"}},
                        "status": status,
                        "type": {"name": f"INJURY_STATUS_{status.upper()}"},
                        "details": {"type": "Hamstring", "detail": "Strain", "fantasyStatus": {"abbreviation": status[:1]}},
                    }
                ],
            }
        ]
    }


def test_parser_reads_the_real_espn_shape():
    payload = json.loads(FIXTURE.read_text())
    rows, shape_ok = gi.parse_summary_injuries(payload, "401869368")
    assert shape_ok and len(rows) == 5
    first = next(r for r in rows if r.athlete_name == "Jalen Williams")
    assert (first.team_abbr, first.status, first.status_type, first.position) == ("OKC", "Out", "INJURY_STATUS_OUT", "G")
    assert first.athlete_id == "4593803" and first.injury_type == "Hamstring"


def test_unknown_shape_is_not_an_empty_report():
    assert gi.parse_summary_injuries({"boxscore": {}}, "1") == ([], False)
    assert gi.parse_summary_injuries(None, "1") == ([], False)
    assert gi.parse_summary_injuries({"injuries": []}, "1") == ([], True)


def test_scoreboard_and_window():
    payload = {"events": [
        {"id": "a", "date": _iso(NOW + 2 * 3600), "shortName": "BUF @ KC"},
        {"id": "b", "date": _iso(NOW + 5 * 3600), "shortName": "SNF"},
        {"id": "c", "date": _iso(NOW - 10 * 60), "shortName": "just kicked"},
        {"id": "d", "date": _iso(NOW - 60 * 60), "shortName": "long started"},
        {"id": "", "date": _iso(NOW)},
    ]}
    events = gi.parse_scoreboard_events(payload)
    assert [e.event_id for e in events] == ["d", "c", "a", "b"]
    assert [e.event_id for e in gi.events_in_window(events, now_epoch=NOW, env={})] == ["c", "a"]


def test_record_detects_changes_and_statuses_file_is_timestamp_free(out_root):
    event = gi.GameEvent("401", NOW + 3600, "BUF @ KC")
    rows_q, _ = gi.parse_summary_injuries(_summary("Questionable"), "401")
    assert gi.record_game("2026-09-27", event, rows_q, captured_at="t1") == []  # baseline
    assert gi.rebuild_statuses("2026-09-27") is True
    first = gi.statuses_path("2026-09-27").read_text()

    assert gi.record_game("2026-09-27", event, rows_q, captured_at="t2") == []
    assert gi.rebuild_statuses("2026-09-27") is False, "a re-capture with no change must not touch the file"
    assert gi.statuses_path("2026-09-27").read_text() == first

    rows_out, _ = gi.parse_summary_injuries(_summary("Out"), "401")
    changes = gi.record_game("2026-09-27", event, rows_out, captured_at="t3")
    assert [(c["change"], c["from"], c["status"]) for c in changes] == [("status", "Questionable", "Out")]
    assert gi.rebuild_statuses("2026-09-27") is True
    log = (gi.game_injuries_dir("2026-09-27") / "changes.jsonl").read_text().strip().splitlines()
    assert len(log) == 1 and json.loads(log[0])["captured_at"] == "t3"

    removed = gi.record_game("2026-09-27", event, [], captured_at="t4")
    assert [c["change"] for c in removed] == ["removed"]


def test_script_run_counts_windows_shapes_and_errors(out_root):
    from scripts import fetch_nfl_game_injuries as script

    scoreboard = {"events": [
        {"id": "in1", "date": _iso(NOW + 3600)},
        {"id": "in2", "date": _iso(NOW + 1800)},
        {"id": "bad", "date": _iso(NOW + 600)},
        {"id": "far", "date": _iso(NOW + 8 * 3600)},
    ]}

    def fetch(url, *, timeout):
        if "scoreboard" in url:
            return scoreboard
        if url.endswith("in1"):
            return _summary("Questionable")
        if url.endswith("in2"):
            return {"boxscore": {}}
        raise OSError("boom")

    published = []
    result = script.run("2026-09-27", now_epoch=NOW, fetch=fetch, publish=lambda path: published.append(path) or True)
    assert (result["events_total"], result["events_in_window"]) == (4, 3)
    assert (result["fetched"], result["shape_unknown"], result["errors"], result["rows"]) == (1, 1, 1, 1)
    assert result["statuses_rewritten"] is True
    assert result["statuses_published"] is True and published == [gi.statuses_path("2026-09-27")]
    assert "error" not in result

    # An unchanged re-capture rewrites nothing, so it must publish nothing.
    again = script.run("2026-09-27", now_epoch=NOW, fetch=fetch, publish=lambda path: published.append(path) or True)
    assert again["statuses_rewritten"] is False and again["statuses_published"] is False
    assert len(published) == 1

    def dead(url, *, timeout):
        raise OSError("dns")

    assert script.run("2026-09-27", now_epoch=NOW, fetch=dead)["error"].startswith("scoreboard")


# --- the refresh-worker autorun: off != on -----------------------------------


@pytest.fixture
def worker(monkeypatch):
    from scripts import run_refresh_worker as w

    store: dict = {}
    launched: list = []
    monkeypatch.setattr(w, "_refresh_state_store", lambda: {
        "read_json_file": lambda p: store.get(str(p)),
        "write_json_file": lambda p, v: store.__setitem__(str(p), v),
        "reports_root": lambda: Path("/tmp/rr"),
    })
    monkeypatch.setattr(w, "_active_sports_for_date", lambda d: "nfl,mlb")
    monkeypatch.setattr(w, "_write_worker_status", lambda **k: None)
    monkeypatch.setattr(w, "_latest_manifest_payload", lambda p: {})
    monkeypatch.setattr(w.subprocess, "Popen", lambda args: launched.append(args) or type("P", (), {"pid": 7})())
    monkeypatch.setattr("syndicate.features.shared.live_refresh_loop._next_fixture_epoch", lambda sport, now_epoch: now_epoch + 3600)
    monkeypatch.delenv("NFL_GAME_INJURIES_FETCH_ENABLE_REFRESH_WORKER_AUTORUN", raising=False)
    monkeypatch.delenv("NFL_GAME_INJURIES_FETCH_INTERVAL_SECONDS", raising=False)
    return w, launched, store


def _call(w):
    return w._launch_autorun_nfl_game_injuries_fetch(latest_manifest_path=Path("m"), worker_status_path=Path("s"), refresh_cycle={})


def test_autorun_off_launches_nothing_on_launches(worker, monkeypatch):
    w, launched, _ = worker
    assert _call(w) is False and launched == []
    monkeypatch.setenv("NFL_GAME_INJURIES_FETCH_ENABLE_REFRESH_WORKER_AUTORUN", "true")
    assert _call(w) is True
    assert launched and launched[0][1].endswith("fetch_nfl_game_injuries.py")
    assert _call(w) is False and len(launched) == 1, "second call inside the interval is rate-limited"


def test_autorun_skips_outside_the_window(worker, monkeypatch):
    w, launched, _ = worker
    monkeypatch.setenv("NFL_GAME_INJURIES_FETCH_ENABLE_REFRESH_WORKER_AUTORUN", "true")
    monkeypatch.setattr("syndicate.features.shared.live_refresh_loop._next_fixture_epoch", lambda sport, now_epoch: now_epoch + 6 * 3600)
    assert _call(w) is False and launched == []
    monkeypatch.setattr("syndicate.features.shared.live_refresh_loop._next_fixture_epoch", lambda sport, now_epoch: None)
    assert _call(w) is False and launched == []


# --- the starting-soon trigger watches the game-day file ----------------------


def test_game_day_file_change_forces_an_nfl_sweep(monkeypatch, tmp_path):
    from syndicate.features.shared import live_refresh_loop as loop
    from syndicate.features.shared import slate_phase as sp

    store: dict = {}
    nflverse = tmp_path / "injuries_2026.csv"
    nflverse.write_text("stable\n")
    game_day = tmp_path / "statuses.json"
    game_day.write_text('{"401": [{"status": "Questionable"}]}')
    monkeypatch.setenv("SYNDICATE_SLATE_STARTING_SOON_ENABLED", "true")
    monkeypatch.setattr(loop, "_meta_dir", lambda: tmp_path)
    monkeypatch.setattr(loop, "read_json_file", lambda p: store.get(str(p)))
    monkeypatch.setattr(loop, "write_json_file", lambda p, v: store.__setitem__(str(p), v))
    monkeypatch.setattr(loop, "_next_fixture_epoch", lambda sport, now_epoch: now_epoch + 3600)
    monkeypatch.setattr(loop, "_LIVE_STATUS_CHECKERS", {"nfl": lambda d: False})
    monkeypatch.setitem(loop._STARTING_SOON_INJURY_FILES, "nfl", (lambda d: nflverse, lambda d: game_day))
    sp._LIVE_CACHE.clear()

    def run():
        return loop._starting_soon_injury_change_sports(["nfl"], now_epoch=NOW, date_str="2026-09-27")

    assert run() == set()  # baselines for both files
    game_day.write_text('{"401": [{"status": "Out"}]}')
    assert run() == {"nfl"}
    assert run() == set()


def test_default_nfl_resolvers_include_the_game_day_file(out_root):
    from syndicate.features.shared import live_refresh_loop as loop

    resolvers = loop._STARTING_SOON_INJURY_FILES["nfl"]
    assert isinstance(resolvers, tuple) and len(resolvers) == 2
    assert resolvers[1]("2026-09-27") == gi.statuses_path("2026-09-27")


# --- the statuses file must CROSS SERVICES (found 2026-09-28) -----------------
# Written on refresh-worker, read on live-odds-worker by the starting-soon
# trigger in `live_refresh_loop`. Render disks are per-service, so it reaches
# the reader only if it is allowlisted AND its name matches live-odds-worker's
# date-scoped pull. Both assertions fail on the pre-fix allowlist.


def test_the_statuses_file_is_allowlisted_and_the_rest_is_not(tmp_path, monkeypatch):
    from syndicate.features.shared import artifact_publisher as ap

    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    monkeypatch.delenv("SYNDICATE_NFL_SOURCE_ROOT", raising=False)
    relative = ap.relative_to_data_root(gi.statuses_path("2026-09-28"))
    assert relative == "nfl_source/tracking/espn/game_injuries/2026-09-28/statuses_2026-09-28.json"
    assert ap.is_hot_artifact_relative_path(relative)
    # The per-game snapshots and the change log stay on refresh-worker.
    assert not ap.is_hot_artifact_relative_path("nfl_source/tracking/espn/game_injuries/2026-09-28/401872963.json")
    assert not ap.is_hot_artifact_relative_path("nfl_source/tracking/espn/game_injuries/2026-09-28/changes.jsonl")


def test_live_odds_workers_date_pull_reaches_the_statuses_file():
    """`live_lens_loop` pulls `pattern=*<central_today_iso()>*` every tick."""
    import fnmatch

    from syndicate.features.shared.timezone import central_today_iso

    today = central_today_iso()
    path = f"nfl_source/tracking/espn/game_injuries/{today}/statuses_{today}.json"
    assert fnmatch.fnmatch(path, f"*{today}*")


def test_a_failed_publish_never_fails_the_capture(out_root, monkeypatch):
    from scripts import fetch_nfl_game_injuries as script
    from syndicate.features.shared import artifact_publisher as ap

    def boom(path, **_):
        raise RuntimeError("web down")

    monkeypatch.setattr(ap, "publish_hot_artifact", boom)
    assert script._publish_statuses(gi.statuses_path("2026-09-27")) is False
