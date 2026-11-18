"""The NHL stats-REST report cache (`nhl_web.STATS_CACHE_ENV`) `[2026-11-18, lane nhl-stats-rest-cache]`.

The fixtures under `tests/fixtures/nhl_stats_report_cache/` are REAL payloads fetched 2026-11-18 ~15:49Z
(TOR 2026-27: the club schedule, the timeonice + goalsForAgainst gameType-2 reports, the eight window
boxscores), trimmed to the fields the readers read. Nothing here is an invented report shape.

What is proven:
* REACHABILITY (off != on): the same two collections make 4 stats-REST calls each with the switch off
  and 2 then 0 with it on.
* PARITY: the usage rows (PP/SH minutes, lines, units, projected TOI) and the assist shares built from the
  cache are identical, byte for byte as JSON, to the rows built with the switch off.
* Each reuse rule's refusal: a newly finished game, an in-progress game, an unsettled stale copy, a
  schedule that cannot be trusted, a failed fetch.
"""
from __future__ import annotations

import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from syndicate.features.nhl.sim_engine.hockeysim.ingestion import lineups as lu
from syndicate.features.nhl.sim_engine.hockeysim.ingestion import nhl_web
from syndicate.features.nhl.sim_engine.hockeysim.ingestion.nhl_web import NhlWebIngestClient

FIX = Path(__file__).parent / "fixtures" / "nhl_stats_report_cache"
DATE = "2026-11-18"
SEASON = "20262027"
PREV = "20252026"
NOW = datetime(2026, 11, 18, 16, 0, tzinfo=timezone.utc)


def _load(name: str):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


SCHEDULE = _load("schedule_TOR_20262027.json")
TOI = _load("timeonice_TOR_20262027_gt2.json")
GFA = _load("goalsForAgainst_TOR_20262027_gt2.json")
BOXES = _load("boxscores_TOR_window.json")
EMPTY = {"data": [], "total": 0}  # what the API returned for TOR's 2026-27 playoffs: 21 bytes


class FakeNhl:
    """Routes the client's GETs to the real payloads; records every URL."""

    def __init__(self, overrides=None):
        self.calls = []
        self.overrides = overrides or {}

    def stats_calls(self):
        return [u for u in self.calls if "/stats/rest/" in u]

    def __call__(self, url: str):
        self.calls.append(url)
        for needle, value in self.overrides.items():
            if needle in url:
                if isinstance(value, Exception):
                    raise value
                return copy.deepcopy(value)
        if f"club-schedule-season/TOR/{SEASON}" in url:
            return copy.deepcopy(SCHEDULE)
        if f"seasonId%3D{PREV}" in url or f"club-schedule-season/TOR/{PREV}" in url:
            raise OSError("HTTP Error 520")  # last season unreachable: both paths must degrade the same way
        if "gameTypeId%3D3" in url:
            return copy.deepcopy(EMPTY)
        if "skater/timeonice" in url:
            return copy.deepcopy(TOI)
        if "skater/goalsForAgainst" in url:
            return copy.deepcopy(GFA)
        raise AssertionError(f"unexpected GET {url}")


def _client(tmp_path: Path, fake: FakeNhl, *, stats_cache: bool, now=NOW) -> NhlWebIngestClient:
    cache = tmp_path / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    for gid, box in BOXES.items():  # the window's boxscores are already cached, as in production
        (cache / f"boxscore_{gid}.json").write_text(json.dumps(box), encoding="utf-8")
    client = NhlWebIngestClient(cache_dir=cache, rate_limit_per_sec=0, stats_cache=stats_cache,
                                now=(now if callable(now) else (lambda: now)))
    client._get = fake  # type: ignore[assignment]
    return client


def _collect_rows(client: NhlWebIngestClient):
    """The production sequence for one team (`collect.collect_slate_inputs`), minus the roster/news."""
    usage = lu.build_team_usage(client, "TOR", date=DATE, n_games=8)
    lu.infer_lines(usage)
    lu.project_lineup(usage, date=DATE)
    lu.attach_assist_share(usage, [(client.onice_goals("TOR", SEASON, before_date=DATE), 1.0),
                                   (client.onice_goals("TOR", PREV, before_date=DATE), lu.ASSIST_SHARE_PRIOR_SEASON_WEIGHT)],
                           DATE)
    return json.dumps(usage, sort_keys=True, default=str)


def test_fixture_is_the_real_slate_shape():
    finished = [g for g in SCHEDULE["games"] if g["gameType"] == 2 and g["gameState"] in ("OFF", "FINAL") and g["gameDate"] < DATE]
    assert len(finished) == 23
    assert {str(r["gameId"]) for r in TOI["data"]} == {str(g["id"]) for g in finished}  # 414 rows, 18 a game
    assert len(TOI["data"]) == len(GFA["data"]) == 414
    assert not any(g["gameType"] == 3 for g in SCHEDULE["games"])


def test_reachability_off_is_not_on(tmp_path):
    off_fake, on_fake = FakeNhl(), FakeNhl()
    off = _client(tmp_path / "off", off_fake, stats_cache=False)
    on = _client(tmp_path / "on", on_fake, stats_cache=True)
    for _ in range(2):
        _collect_rows(off)
        _collect_rows(on)
    # off: timeonice + goalsForAgainst, gameType 2 and 3, every run (last season's 2 raise and are not counted twice)
    assert len([u for u in off_fake.stats_calls() if f"seasonId%3D{SEASON}" in u]) == 8
    # on: gameType 3 never (the schedule lists none); gameType 2 once each, then served from disk
    assert len([u for u in on_fake.stats_calls() if f"seasonId%3D{SEASON}" in u]) == 2
    # TOR played 11-17 (start 11-18 00:00Z): at 16:00Z that copy is inside the 18 h settle window, so the
    # reuse is the 6 h unsettled tier
    assert on.stats_report_counts["skip_empty"] == 4 and on.stats_report_counts["hit_unsettled"] == 2
    assert not list((tmp_path / "off" / "cache").glob("statsrest_*"))  # off writes nothing
    assert set(off.stats_report_counts) == {"fetch:off"}             # ...and its log line counts the calls
    assert off.stats_report_counts["fetch:off"] == len(off_fake.stats_calls())


def test_parity_cached_rows_equal_uncached_rows_on_the_real_slate(tmp_path):
    uncached = _collect_rows(_client(tmp_path / "off", FakeNhl(), stats_cache=False))
    on_fake = FakeNhl()
    on = _client(tmp_path / "on", on_fake, stats_cache=True)
    this_season = lambda: [u for u in on_fake.stats_calls() if f"seasonId%3D{SEASON}" in u]  # noqa: E731
    cold = _collect_rows(on)
    n_cold = len(this_season())
    warm = _collect_rows(on)
    assert n_cold == 2 and len(this_season()) == n_cold  # the warm run made no 2026-27 stats-REST call
    # last season is unreachable in this fake (520): fetched and failed every run, exactly as with the switch off
    assert on.stats_report_counts["fetch:no_schedule"] == 4
    assert uncached == cold == warm
    rows = json.loads(warm)
    # the cache served what the readers use: real PP minutes and assist shares, not the fallbacks
    assert sum(1 for r in rows if r.get("pp_toi_total")) >= 8
    assert sum(1 for r in rows if r.get("assist_share") is not None) >= 18
    assert sum(1 for r in rows if r.get("proj_ev_toi") is not None) >= 18


def test_absent_switch_is_on_and_off_values_turn_it_off(monkeypatch):
    monkeypatch.delenv(nhl_web.STATS_CACHE_ENV, raising=False)
    assert NhlWebIngestClient(rate_limit_per_sec=0).stats_cache is True
    for value in ("off", "0", "false", "no", " OFF "):
        monkeypatch.setenv(nhl_web.STATS_CACHE_ENV, value)
        assert NhlWebIngestClient(rate_limit_per_sec=0).stats_cache is False
    monkeypatch.setenv(nhl_web.STATS_CACHE_ENV, "on")
    assert NhlWebIngestClient(rate_limit_per_sec=0).stats_cache is True


def test_without_before_date_every_report_is_fetched(tmp_path):
    fake = FakeNhl()
    client = _client(tmp_path, fake, stats_cache=True)
    for _ in range(2):
        client.special_teams_toi("TOR", SEASON)
    assert len(fake.stats_calls()) == 4  # other callers keep the old transport


def test_a_newly_finished_game_forces_a_refetch(tmp_path):
    fake = FakeNhl()
    client = _client(tmp_path, fake, stats_cache=True)
    client.recent_finished_game_ids("TOR", SEASON, before_date=DATE)
    newest = max((g for g in SCHEDULE["games"] if g["gameType"] == 2 and g["gameState"] == "OFF"), key=lambda g: g["gameDate"])
    stale = {"data": [r for r in TOI["data"] if r["gameId"] != newest["id"]], "total": 0}
    path = client.stats_cache_dir / f"statsrest_timeonice_TOR_{SEASON}_gt2.json"
    path.write_text(json.dumps({"fetched_at_utc": NOW.isoformat(), "payload": stale}), encoding="utf-8")
    st = client.special_teams_toi("TOR", SEASON, before_date=DATE)
    assert client.stats_report_counts["fetch:new_game"] == 1
    assert str(newest["id"]) in st                                  # the fresh report, not the stale copy
    held = {str(r["gameId"]) for r in json.loads(path.read_text())["payload"]["data"]}
    assert str(newest["id"]) in held                                 # and it replaced the copy on disk
    # a game the slate date does not read (dated on/after it) is not required
    assert client.special_teams_toi("TOR", SEASON, before_date=newest["gameDate"]) == st
    assert client.stats_report_counts["hit"] == 1


def test_a_game_in_progress_is_never_served_from_cache(tmp_path):
    live = copy.deepcopy(SCHEDULE)
    newest = max((g for g in live["games"] if g["gameType"] == 2 and g["gameState"] == "OFF"), key=lambda g: g["gameDate"])
    fake = FakeNhl()
    client = _client(tmp_path, fake, stats_cache=True)
    client.recent_finished_game_ids("TOR", SEASON, before_date=DATE)
    client.onice_goals("TOR", SEASON, before_date=DATE)               # warm
    newest["gameState"] = "LIVE"
    client._record_schedule("TOR", SEASON, live)
    n = len(fake.stats_calls())
    client.onice_goals("TOR", SEASON, before_date=DATE)
    assert len(fake.stats_calls()) == n + 1
    assert client.stats_report_counts["fetch:in_progress"] == 1


def test_settle_window(tmp_path):
    """An unsettled copy (fetched < 18 h after the newest game started) is reused for 6 h, then re-read;
    a settled copy is reused until the team finishes another game."""
    finished = [g for g in SCHEDULE["games"] if g["gameType"] == 2 and g["gameState"] == "OFF" and g["gameDate"] < DATE]
    newest_start = max(datetime.fromisoformat(g["startTimeUTC"].replace("Z", "+00:00")) for g in finished)
    clock = {"now": newest_start + timedelta(hours=3)}
    fake = FakeNhl()
    client = _client(tmp_path, fake, stats_cache=True, now=lambda: clock["now"])
    client.recent_finished_game_ids("TOR", SEASON, before_date=DATE)
    client.onice_goals("TOR", SEASON, before_date=DATE)               # fetched 3 h after the start
    clock["now"] = newest_start + timedelta(hours=8)                 # 5 h old: unsettled but fresh
    client.onice_goals("TOR", SEASON, before_date=DATE)
    assert client.stats_report_counts["hit_unsettled"] == 1
    clock["now"] = newest_start + timedelta(hours=10)                # 7 h old: re-read
    client.onice_goals("TOR", SEASON, before_date=DATE)
    assert client.stats_report_counts["fetch:unsettled_stale"] == 1
    clock["now"] = newest_start + timedelta(hours=25)                # fetched now: settled
    client.onice_goals("TOR", SEASON, before_date=DATE)              # 10 h old copy, still unsettled -> re-read
    clock["now"] = newest_start + timedelta(days=4)
    client.onice_goals("TOR", SEASON, before_date=DATE)
    assert client.stats_report_counts["hit"] == 1                    # settled: reused days later
    assert client.stats_report_counts["fetch:unsettled_stale"] == 2


def test_playoff_report_is_skipped_only_when_the_schedule_lists_no_playoff_game(tmp_path):
    with_playoffs = copy.deepcopy(SCHEDULE)
    with_playoffs["games"].append({"id": 2026030111, "gameType": 3, "gameState": "FUT", "gameDate": "2027-04-20",
                                   "startTimeUTC": "2027-04-20T23:00:00Z"})
    fake = FakeNhl()
    client = _client(tmp_path, fake, stats_cache=True)
    client._record_schedule("TOR", SEASON, with_playoffs)
    client.special_teams_toi("TOR", SEASON, before_date=DATE)
    assert any("gameTypeId%3D3" in u for u in fake.stats_calls())   # a listed playoff game -> fetched
    assert client.stats_report_counts["skip_empty"] == 0


@pytest.mark.parametrize("schedule", [{}, {"games": []}, {"games": [{"id": 1, "gameType": 1, "gameState": "OFF"}]}, None])
def test_an_untrustworthy_schedule_means_fetch_never_skip(tmp_path, schedule):
    """An empty or malformed schedule must read as UNKNOWN. Read as "no games of that type" it would turn
    an outage into an empty report -- the silent fallback learnings 2026-10-05 is about."""
    fake = FakeNhl({f"club-schedule-season/TOR/{SEASON}": schedule})
    client = _client(tmp_path, fake, stats_cache=True)
    client._finished_competitive_ids("TOR", SEASON, DATE)
    st = client.special_teams_toi("TOR", SEASON, before_date=DATE)
    assert len(fake.stats_calls()) == 2 and client.stats_report_counts["skip_empty"] == 0
    assert client.stats_report_counts["fetch:no_schedule"] == 2
    assert st  # the real report's rows


def test_a_failed_fetch_raises_as_before_and_writes_nothing(tmp_path):
    fake = FakeNhl({"skater/timeonice": OSError("HTTP Error 520")})
    client = _client(tmp_path, fake, stats_cache=True)
    client.recent_finished_game_ids("TOR", SEASON, before_date=DATE)
    assert client.special_teams_toi("TOR", SEASON, before_date=DATE) == {}
    assert not list(client.stats_cache_dir.glob("statsrest_timeonice_*"))


def test_a_complete_season_schedule_is_read_from_disk_once_final(tmp_path):
    prev = {"games": [{"id": 2025020001 + i, "gameType": 2, "gameState": "OFF", "gameDate": f"2026-03-{i + 1:02d}",
                       "startTimeUTC": f"2026-03-{i + 1:02d}T23:00:00Z"} for i in range(3)]}
    rows = {"data": [{"gameId": g["id"], "gameDate": g["gameDate"], "playerId": 7, "goals": 0, "assists": 1,
                      "evenStrengthGoalsFor": 2, "powerPlayGoalFor": 0, "shortHandedGoalsFor": 0} for g in prev["games"]]}
    fake = FakeNhl({f"club-schedule-season/TOR/{PREV}": prev, f"seasonId%3D{PREV}%20and%20gameTypeId%3D2": rows})
    client = _client(tmp_path, fake, stats_cache=True)
    first = client.onice_goals("TOR", PREV, before_date=DATE)
    assert (client.stats_cache_dir / f"club_schedule_TOR_{PREV}.json").exists()
    again = _client(tmp_path, fake, stats_cache=True)                # a new process: nothing in memory
    n = len(fake.calls)
    assert again.onice_goals("TOR", PREV, before_date=DATE) == first
    assert len(fake.calls) == n                                       # schedule from disk, report from disk
    assert again.stats_report_counts == {"hit": 1, "skip_empty": 1}


def test_an_incomplete_season_schedule_is_never_written(tmp_path):
    fake = FakeNhl()
    client = _client(tmp_path, fake, stats_cache=True)
    client.onice_goals("TOR", SEASON, before_date=DATE)               # 2026-27 is in progress
    assert not (client.stats_cache_dir / f"club_schedule_TOR_{SEASON}.json").exists()
    early = _client(tmp_path / "early", FakeNhl({f"club-schedule-season/TOR/{PREV}": {"games": [
        {"id": 1, "gameType": 2, "gameState": "OFF", "gameDate": "2026-04-01"}]},
        f"seasonId%3D{PREV}": EMPTY}), stats_cache=True, now=datetime(2026, 9, 20, tzinfo=timezone.utc))
    early.onice_goals("TOR", PREV, before_date="2026-09-20")          # before Oct 1: not provably over
    assert not (early.stats_cache_dir / f"club_schedule_TOR_{PREV}.json").exists()


def test_collect_prints_the_per_date_line(tmp_path, capsys):
    from syndicate.features.nhl.sim_engine.hockeysim.ingestion.collect import collect_slate_inputs

    for flag, word in ((True, "on"), (False, "off")):
        client = NhlWebIngestClient(cache_dir=tmp_path, offline=True, stats_cache=flag)
        summary = collect_slate_inputs(DATE, root=tmp_path, client=client, out_dir=tmp_path)
        assert summary["stats_reports"] == {}
        assert f"NHL_STATS_REPORT_CACHE date={DATE} enabled={word} teams=0 fetched=0 served=0" in capsys.readouterr().out


def test_the_default_stats_cache_lives_under_the_data_root(monkeypatch, tmp_path):
    """The fleet's live-odds-worker sets SYNDICATE_DATA_ROOT and no SYNDICATE_ARTIFACT_ROOT_NHL (read 11-18): the
    stats cache must land in the data root, not in the checkout where the boxscore cache resolves."""
    monkeypatch.delenv("SYNDICATE_ARTIFACT_ROOT_NHL", raising=False)
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    client = NhlWebIngestClient(rate_limit_per_sec=0)
    assert client.stats_cache_dir == tmp_path / "nhl_source" / "data" / "ingestion_cache"
    assert client.cache_dir == nhl_web._default_cache_dir()          # the boxscore cache is not moved here
    monkeypatch.setenv("SYNDICATE_ARTIFACT_ROOT_NHL", str(tmp_path / "bundle"))
    assert NhlWebIngestClient(rate_limit_per_sec=0).stats_cache_dir == tmp_path / "bundle" / "data" / "ingestion_cache"
