"""`scripts/collect_news_snapshots.py` -- free, timestamped, append-only news change-logs (lane news-collectors-backfill)."""
from __future__ import annotations

import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "collect_news_snapshots", Path(__file__).resolve().parents[1] / "scripts" / "collect_news_snapshots.py"
)
cns = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(cns)

T0 = datetime(2026, 10, 13, 18, 0, tzinfo=timezone.utc)
T1 = datetime(2026, 10, 13, 18, 10, tzinfo=timezone.utc)


def _espn(*items):
    return {"injuries": [{"displayName": "Atlanta Hawks", "injuries": [
        {"id": i[0], "status": i[1], "date": "2026-10-13T17:00Z", "shortComment": i[2],
         "type": {"abbreviation": i[1][:1]}, "athlete": {"id": i[0], "displayName": f"P{i[0]}"}, "details": {}}
        for i in items]}]}


def _fetcher(pages):
    calls = []

    def fetch(url):
        calls.append(url)
        for key, body in pages.items():
            if key in url:
                return json.dumps(body).encode() if not isinstance(body, (str, bytes)) else (body.encode() if isinstance(body, str) else body)
        raise ValueError(f"unexpected url {url}")
    fetch.calls = calls
    return fetch


def _lines(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def test_first_run_is_a_baseline_then_only_changes_are_written(tmp_path: Path) -> None:
    f0 = _fetcher({"nba/injuries": _espn(("1", "Out", "knee"), ("2", "Day-To-Day", "ankle"))})
    cns.run(tmp_path, ["nba"], ["injuries"], fetch=f0, now=T0)
    f1 = _fetcher({"nba/injuries": _espn(("1", "Out", "knee"), ("2", "Questionable", "ankle, game-time call"), ("3", "Out", "rest"))})
    status = cns.run(tmp_path, ["nba"], ["injuries"], fetch=f1, now=T1)
    rows = _lines(tmp_path / "news" / "nba" / "injuries" / "2026-10-13.jsonl")
    assert [r["event"] for r in rows[:2]] == ["new", "new"]           # baseline
    later = rows[2:]
    assert {(r["athlete_id"], r["event"]) for r in later} == {("2", "changed"), ("3", "new")}
    changed = next(r for r in later if r["athlete_id"] == "2")
    assert changed["previous_status"] == "Day-To-Day" and changed["captured_at"] == "2026-10-13T18:10:00Z"
    assert changed["source_updated_at"] == "2026-10-13T17:00Z"
    assert status["results"]["nba_injuries"]["by_event"] == {"new": 1, "changed": 1, "cleared": 0}


def test_a_player_dropping_off_the_report_is_logged_as_cleared(tmp_path: Path) -> None:
    cns.run(tmp_path, ["nhl"], ["injuries"], fetch=_fetcher({"nhl/injuries": _espn(("9", "Out", "upper body"))}), now=T0)
    cns.run(tmp_path, ["nhl"], ["injuries"], fetch=_fetcher({"nhl/injuries": _espn()}), now=T1)
    rows = _lines(tmp_path / "news" / "nhl" / "injuries" / "2026-10-13.jsonl")
    assert rows[-1]["event"] == "cleared" and rows[-1]["previous_status"] == "Out"


NBA_PAGE = """<table class="table"><thead><tr><th>Game</th><th>Crew Chief</th><th>Referee</th><th>Umpire</th>
<th>Alternate</th></tr></thead><tbody><tr> <td>Cleveland @ Orlando</td> <td> <a href="x"> JB DeRosa (#14) </a> </td>
<td> <a href="y"> Robert Hussey (#85) </a> </td> <td> <a href="z"> Intae Hwang (#73) </a> </td> <td></td> </tr></tbody></table>"""


def test_nba_referee_crews_are_parsed_and_logged_once(tmp_path: Path) -> None:
    assert cns.parse_nba_referees(NBA_PAGE) == [{"game": "Cleveland @ Orlando", "crew_chief": "JB DeRosa (#14)",
                                                 "referee": "Robert Hussey (#85)", "umpire": "Intae Hwang (#73)",
                                                 "alternate": None}]
    for now in (T0, T1):
        cns.run(tmp_path, ["nba"], ["referees"], fetch=_fetcher({"referee-assignments": NBA_PAGE}), now=now)
    assert len(_lines(tmp_path / "news" / "nba" / "referees" / "2026-10-13.jsonl")) == 1


def test_nhl_officials_and_scratches_are_logged_when_posted_and_when_they_change(tmp_path: Path) -> None:
    schedule = {"gameWeek": [{"games": [{"id": 2026020090, "startTimeUTC": "2026-10-13T20:00:00Z",
                                         "awayTeam": {"abbrev": "NJD"}, "homeTeam": {"abbrev": "DET"}}]}]}
    empty = {"gameInfo": {"referees": [], "linesmen": [], "awayTeam": {"scratches": []}, "homeTeam": {"scratches": []}}}
    posted = {"gameInfo": {"referees": [{"fullName": {"default": "Jon McIsaac"}, "sweaterNumber": 2}],
                           "linesmen": [{"fullName": {"default": "Matt MacPherson"}}],
                           "awayTeam": {"scratches": [{"id": 1, "firstName": {"default": "Nick"}, "lastName": {"default": "Foligno"}}]},
                           "homeTeam": {"scratches": []}}}
    cns.run(tmp_path, ["nhl"], ["referees"], fetch=_fetcher({"schedule/now": schedule, "right-rail": empty}), now=T0)
    assert not (tmp_path / "news" / "nhl" / "gameinfo").exists()  # nothing posted -> nothing written
    cns.run(tmp_path, ["nhl"], ["referees"], fetch=_fetcher({"schedule/now": schedule, "right-rail": posted}), now=T1)
    cns.run(tmp_path, ["nhl"], ["referees"], fetch=_fetcher({"schedule/now": schedule, "right-rail": posted}), now=T1)
    rows = _lines(tmp_path / "news" / "nhl" / "gameinfo" / "2026-10-13.jsonl")
    assert len(rows) == 1
    assert rows[0]["referees"] == ["Jon McIsaac"] and rows[0]["away_scratches"] == [{"id": 1, "name": "Nick Foligno"}]


def test_one_failing_source_does_not_stop_the_others_and_no_oddsapi_is_called(tmp_path: Path) -> None:
    fetch = _fetcher({"nba/injuries": _espn(("1", "Out", "knee"))})  # nfl url unknown -> raises
    status = cns.run(tmp_path, ["nba", "nfl"], ["injuries"], fetch=fetch, now=T0)
    assert "nba_injuries" in status["results"] and "nfl_injuries" in status["errors"]
    assert status["oddsapi_requests"] == 0
    assert not any("the-odds-api" in url for url in fetch.calls)
    assert json.loads((tmp_path / "news" / "_status" / "last_run.json").read_text())["requests"] == 1


def test_mlb_injuries_are_collected_by_default(tmp_path: Path) -> None:
    # User 2026-10-14: "collect MLB injuries now, flag in 2027". The scheduled task passes no --sports, so the
    # default is what runs on the fleet.
    import unittest.mock as mock

    seen = {}

    def fake_run(root, sports, kinds, **kw):
        seen["sports"] = sports
        return {"results": {}, "errors": {}, "requests": 0, "oddsapi_requests": 0}

    with mock.patch.object(cns, "run", fake_run):
        cns.main(["--data-root", str(tmp_path)])
    assert seen["sports"] == ["nba", "nhl", "nfl", "wnba", "mlb"]
    fetch = _fetcher({"baseball/mlb/injuries": _espn(("7", "10-Day-IL", "hamstring"))})
    status = cns.run(tmp_path, ["mlb"], ["injuries"], fetch=fetch, now=T0)
    assert status["results"]["mlb_injuries"]["listed"] == 1
    rows = _lines(tmp_path / "news" / "mlb" / "injuries" / "2026-10-13.jsonl")
    assert rows[0]["status"] == "10-Day-IL" and rows[0]["event"] == "new"


# ----------------------------------------------------------------------------- backfill copy

_BSPEC = importlib.util.spec_from_file_location(
    "copy_backfill_to_fleet", Path(__file__).resolve().parents[1] / "scripts" / "copy_backfill_to_fleet.py"
)
cbf = importlib.util.module_from_spec(_BSPEC)
_BSPEC.loader.exec_module(cbf)


def test_backfill_copy_verifies_hashes_filters_and_is_idempotent(tmp_path: Path) -> None:
    src = tmp_path / "src"
    (src / "sub").mkdir(parents=True)
    (src / "2024_wk1.jsonl").write_text("a\n")
    (src / "sub" / "2025_wk2.jsonl").write_text("b\n")
    (src / "notes.txt").write_text("skip me")
    dest = tmp_path / "dest"
    first = cbf.copy_set("s", src, r"^20(23|24|25)_wk\d+\.", dest, dry_run=False)
    assert (first["files"], first["copied"], first["mismatches"]) == (2, 2, [])
    assert (dest / "s" / "sub" / "2025_wk2.jsonl").read_text() == "b\n"
    manifest = json.loads((dest / "s" / "MANIFEST.json").read_text())
    assert {e["path"] for e in manifest["entries"]} == {"2024_wk1.jsonl", "sub/2025_wk2.jsonl"}
    again = cbf.copy_set("s", src, r"^20(23|24|25)_wk\d+\.", dest, dry_run=False)
    assert (again["copied"], again["skipped_identical"]) == (0, 2)
    assert (src / "notes.txt").exists()  # the source is never touched
