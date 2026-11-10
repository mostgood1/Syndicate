"""Phase 1B M0: the live evidence log (lane `live-evidence-log`, 2026-11-09).

Fixtures are the shapes the fleet's live snapshots carried on 2026-11-09 (wncaab re-sim lanes with a
projection; ncaaf / nhl pregame lanes with a refusal and no projection; nfl `as_of` / `refusal` lanes)."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from syndicate.features.shared import live_evidence_log as lel


def _bball_snapshot(t: str, *, home_score: int = 30, carried: bool = False) -> dict:
    lane = {
        "key": "live", "label": "Live re-sim", "source": "live_resim", "liveStateAsOf": t,
        "modelHomeWinProb": 0.62, "rawModelHomeWinProb": 0.66, "simsRun": 200,
        "inputs": {"pace": 68.5, "players": [{"n": 1}]},
        "projection": {
            "period": 2, "clockSeconds": 431.0, "homeScore": home_score, "awayScore": 27, "scoreSource": "espn",
            "total": 141.5, "homeMargin": 4.2, "rawHomeMargin": 5.0, "marginAnchor": "market",
            "marginDist": {"-3": 10, "4": 40}, "totalRunsDist": {"140": 30, "142": 20},
            "segments": {"h2": {"total_mean": 74.1, "dist": {"70": 3}}},
        },
    }
    if carried:
        lane = {"key": "live", "source": "pregame_lens", "carriedForward": True, "carriedRefusal": "stale_state",
                "liveResimRefusal": "stale_state", "liveStateAsOf": "2026-11-09T18:00:00Z"}
    return {"date": "2026-11-09", "generatedAt": t, "games": [
        {"event_id": "E1", "home": "SMU", "away": "ETAM", "home_name": "SMU Mustangs", "away_name": "East Texas A&M",
         "status": "in_progress", "gameLens": [lane]},
    ]}


def _pregame_snapshot(t: str, refusal: str = "not_started") -> dict:
    return {"date": "2026-11-09", "generatedAt": t, "games": [
        {"home_name": "Kansas St", "away_name": "Oklahoma St", "gameLens": [
            {"key": "live", "source": "pregame_lens", "liveResimRefusal": refusal, "liveStateAsOf": ""}]},
    ]}


class _Store:
    def __init__(self):
        self.snaps: dict[str, dict] = {}

    def read(self, name):
        return self.snaps.get(name)


def _collector(tmp_path, store):
    return lel.Collector(root=tmp_path, read=store.read, sports={"wncaab": "w.json", "ncaaf": "f.json"})


def test_switch_absent_is_on_and_off_turns_it_off():
    assert lel.enabled({}) is True
    assert lel.enabled({lel.LOG_ENV: "off"}) is False
    assert lel.start_live_evidence_loop({lel.LOG_ENV: "off"}) is False
    assert lel.interval_seconds({}) == 30.0
    assert lel.interval_seconds({lel.INTERVAL_ENV: "2"}) == lel.MIN_INTERVAL_SECONDS


def test_snapshot_paths_cover_the_live_sports():
    assert set(lel.LIVE_SNAPSHOTS) >= {"nba", "ncaab", "wncaab", "ncaaf", "nfl", "nhl"}


def test_a_fresh_lane_becomes_one_full_row(tmp_path):
    store = _Store()
    store.snaps["w.json"] = _bball_snapshot("2026-11-09T18:05:00Z")
    written = _collector(tmp_path, store).collect_once(now=datetime(2026, 11, 9, 18, 5, 20, tzinfo=timezone.utc))
    assert written == {"wncaab": 1}
    rows = list(lel.iter_rows("wncaab", "2026-11-09", root=tmp_path))
    assert len(rows) == 1
    row = rows[0]
    assert row["t"] == "2026-11-09T18:05:00Z" and row["observed_at"].startswith("2026-11-09T18:05:20")
    assert row["event_id"] == "E1" and row["source"] == "live_resim" and row["refusal"] is None
    assert row["state"] == {"period": 2, "clockSeconds": 431.0, "homeScore": 30, "awayScore": 27, "scoreSource": "espn"}
    assert row["proj"]["total"] == 141.5 and row["proj"]["homeMargin"] == 4.2 and row["proj"]["marginAnchor"] == "market"
    assert row["marginDist"] == {"-3": 10, "4": 40} and row["totalRunsDist"] == {"140": 30, "142": 20}
    assert row["segments"]["h2"]["total_mean"] == 74.1
    assert row["modelHomeWinProb"] == 0.62 and row["simsRun"] == 200
    assert row["inputs"] == {"pace": 68.5}  # scalars only


def test_unchanged_snapshot_is_not_written_twice(tmp_path):
    store = _Store()
    store.snaps["w.json"] = _bball_snapshot("2026-11-09T18:05:00Z")
    c = _collector(tmp_path, store)
    assert c.collect_once() == {"wncaab": 1}
    assert c.collect_once() == {}
    store.snaps["w.json"] = _bball_snapshot("2026-11-09T18:07:00Z", home_score=33)
    assert c.collect_once() == {"wncaab": 1}
    assert [r["state"]["homeScore"] for r in lel.iter_rows("wncaab", "2026-11-09", root=tmp_path)] == [30, 33]


def test_pregame_and_refusal_lanes_only_on_change(tmp_path):
    store = _Store()
    c = _collector(tmp_path, store)
    for i in range(5):
        store.snaps["f.json"] = _pregame_snapshot(f"2026-11-09T18:0{i}:00Z")
        c.collect_once()
    assert len(list(lel.iter_rows("ncaaf", "2026-11-09", root=tmp_path))) == 1
    store.snaps["f.json"] = _pregame_snapshot("2026-11-09T18:06:00Z", refusal="no_live_state")
    c.collect_once()
    rows = list(lel.iter_rows("ncaaf", "2026-11-09", root=tmp_path))
    assert [r["refusal"] for r in rows] == ["not_started", "no_live_state"]
    assert "state" not in rows[0] and rows[0]["home"] == "Kansas St"


def test_a_pregame_lane_stamped_with_the_tick_time_is_not_rewritten(tmp_path):
    """nhl / ncaaf stamp a pregame lane's liveStateAsOf with the tick time (fleet, 2026-11-09)."""
    store = _Store()
    c = _collector(tmp_path, store)
    for i in range(4):
        snap = _pregame_snapshot(f"2026-11-09T18:0{i}:00Z", refusal="game_not_started")
        snap["games"][0]["gameLens"][0]["liveStateAsOf"] = f"2026-11-09T18:0{i}:00Z"
        store.snaps["f.json"] = snap
        c.collect_once()
    assert len(list(lel.iter_rows("ncaaf", "2026-11-09", root=tmp_path))) == 1


def test_a_dict_refusal_is_compared_by_value(tmp_path):
    """nfl's refusal is a dict ({"reason", "detail"}), fleet 2026-11-09."""
    store = _Store()
    c = _collector(tmp_path, store)
    for i in range(3):
        snap = _pregame_snapshot(f"2026-11-09T18:0{i}:00Z")
        snap["games"][0]["gameLens"][0] = {"source": "pregame", "refusal": {"reason": "game_final", "detail": "x"},
                                           "as_of": f"2026-11-09T18:0{i}:00Z", "ok": False}
        store.snaps["f.json"] = snap
        c.collect_once()
    rows = list(lel.iter_rows("ncaaf", "2026-11-09", root=tmp_path))
    assert len(rows) == 1 and rows[0]["refusal"] == {"reason": "game_final", "detail": "x"}


def test_a_carried_lane_is_recorded_once_as_carried(tmp_path):
    store = _Store()
    c = _collector(tmp_path, store)
    store.snaps["w.json"] = _bball_snapshot("2026-11-09T18:05:00Z", carried=True)
    c.collect_once()
    store.snaps["w.json"] = _bball_snapshot("2026-11-09T18:07:00Z", carried=True)
    c.collect_once()
    rows = list(lel.iter_rows("wncaab", "2026-11-09", root=tmp_path))
    assert len(rows) == 1 and rows[0]["carried"] is True and rows[0]["refusal"] == "stale_state"


def test_evidence_at_uses_the_producer_time(tmp_path):
    store = _Store()
    c = _collector(tmp_path, store)
    store.snaps["w.json"] = _bball_snapshot("2026-11-09T18:05:00Z", home_score=30)
    c.collect_once()
    store.snaps["w.json"] = _bball_snapshot("2026-11-09T18:07:00Z", home_score=33)
    c.collect_once()
    rows = list(lel.iter_rows("wncaab", "2026-11-09", root=tmp_path))
    before = lel.evidence_at(rows, "2026-11-09T18:06:59Z")
    after = lel.evidence_at(rows, "2026-11-09T18:07:00Z")
    assert before[("E1", "live")]["state"]["homeScore"] == 30
    assert after[("E1", "live")]["state"]["homeScore"] == 33
    assert lel.evidence_at(rows, "2026-11-09T18:04:00Z") == {}


def test_a_torn_last_line_is_skipped(tmp_path):
    path = lel.log_path("wncaab", "2026-11-09", root=tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"t": "2026-11-09T18:05:00Z", "event_id": "E1", "lane": "live"}) + "\n{\"t\": \"2026-",
                    encoding="utf-8")
    assert len(list(lel.iter_rows("wncaab", "2026-11-09", root=tmp_path))) == 1


def test_an_oversized_row_drops_detail_and_says_so():
    snap = _bball_snapshot("2026-11-09T18:05:00Z")
    lane = snap["games"][0]["gameLens"][0]
    lane["projection"]["segments"] = {f"q{i}": {"total_mean": 30.0, "dist": {str(j): j for j in range(2000)}} for i in range(4)}
    row = lel.lane_row("wncaab", "2026-11-09", "2026-11-09T18:05:00Z", "x", snap["games"][0], lane)
    assert "segments.detail" in row["dropped"]
    assert row["segments"]["q0"] == {"total_mean": 30.0}
    assert len(json.dumps(row)) <= lel.ROW_MAX_BYTES


def _nfl_lane(t: str) -> dict:
    """The NFL live re-sim's lane shape on the fleet, Monday night football 2026-11-09."""
    return {"source": "live_resim", "ok": True, "as_of": t, "modelHomeWinProb": 0.3427, "simsRun": 120,
            "projection": {"homeMargin": -3.93, "total": 25.5},
            "live_state": {"period": 2, "clock_seconds": 242, "home_score": 3, "away_score": 3},
            "margin_dist": {"-4": 9, "7": 6}, "total_dist": {"16": 10, "25": 6},
            "margin_mean": -3.93, "possession_marginalised": True}


def _nfl_snapshot(t: str) -> dict:
    return {"date": "2026-11-10", "generatedAt": t, "games": [
        {"event_id": "N1", "home_name": "minnesota vikings", "away_name": "buffalo bills", "gameLens": [_nfl_lane(t)]}]}


def test_a_lane_level_nfl_state_reads_under_the_shared_names(tmp_path):
    store = _Store()
    c = lel.Collector(root=tmp_path, read=store.read, sports={"nfl": "n.json"})
    store.snaps["n.json"] = _nfl_snapshot("2026-11-09T20:34:32-06:00")
    assert c.collect_once() == {"nfl": 1}
    raw = json.loads(lel.log_path("nfl", "2026-11-10", root=tmp_path).read_text(encoding="utf-8"))
    assert "state" not in raw and raw["extra"]["live_state"]["clock_seconds"] == 242  # stored verbatim
    rows = list(lel.iter_rows("nfl", "2026-11-10", root=tmp_path))
    assert rows[0]["state"] == {"period": 2, "clockSeconds": 242, "homeScore": 3, "awayScore": 3}
    assert rows[0]["marginDist"] == {"-4": 9, "7": 6} and rows[0]["totalRunsDist"] == {"16": 10, "25": 6}
    assert rows[0]["normalized"] == ["state", "marginDist", "totalRunsDist"]
    assert lel.evidence_at(rows, "2026-11-09T20:35:00-06:00")[("N1", None)]["state"]["homeScore"] == 3


def test_normalize_never_overrides_what_the_projection_supplied():
    row = {"state": {"homeScore": 30}, "marginDist": {"1": 1},
           "extra": {"live_state": {"home_score": 99}, "margin_dist": {"9": 9}, "total_dist": {"140": 2}}}
    out = lel.normalize_row(row)
    assert out["state"] == {"homeScore": 30} and out["marginDist"] == {"1": 1}
    assert out["totalRunsDist"] == {"140": 2} and out["normalized"] == ["totalRunsDist"]
    assert lel.normalize_row({"state": {"homeScore": 1}}) == {"state": {"homeScore": 1}}


def test_the_probe_sees_a_field_lane_row_does_not_extract():
    """off != on: the probe's independent read flags the un-normalized NFL row and passes the normalized one."""
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "live_evidence_check", Path(__file__).resolve().parents[1] / "scripts" / "live_evidence_check.py")
    check = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(check)
    t = "2026-11-09T20:34:32-06:00"
    game = _nfl_snapshot(t)["games"][0]
    lane = game["gameLens"][0]
    raw_row = lel.lane_row("nfl", "2026-11-10", t, t, game, lane)
    gaps = [name for name, published, read in check._published_vs_read(lane, raw_row) if published != read]
    assert gaps == ["state.homeScore", "state.awayScore", "state.period", "marginDist", "totalRunsDist"]
    assert all(p == r for _n, p, r in check._published_vs_read(lane, lel.normalize_row(raw_row)))


def _load_check():
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "live_evidence_check", Path(__file__).resolve().parents[1] / "scripts" / "live_evidence_check.py")
    check = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(check)
    return check


def test_nba_crosscheck_matches_by_instant_and_fails_on_a_missing_tick(tmp_path, capsys):
    """NBA's history writes `t` in UTC, the snapshot carries the Central offset: same instant, different text
    (fleet 2026-11-09: 0 of 422 matched as strings, 422 of 422 by instant). A missing tick must exit 1."""
    from syndicate.features.nba import live_resim as nba

    check = _load_check()
    store = _Store()
    c = lel.Collector(root=tmp_path, read=store.read, sports={"nba": "n.json"})
    store.snaps["n.json"] = _bball_snapshot("2026-11-09T19:12:34-06:00")
    c.collect_once()
    hist = nba.live_resim_history_path("2026-11-09", root=tmp_path)
    hist.parent.mkdir(parents=True, exist_ok=True)
    base = {"event_id": "E1", "source": nba.LIVE_RESIM_LENS_SOURCE, "refusal": None, "period": 2, "clock_s": 431.0,
            "home_score": 30, "away_score": 27, "total": 141.5, "margin": 4.2, "p_home": 0.62, "sims": 200}
    hist.write_text(json.dumps({**base, "t": "2026-11-10T01:12:34+00:00"}) + "\n", encoding="utf-8")
    assert check.nba_crosscheck("2026-11-09", root=tmp_path) == 0
    assert "matched=1 missing=0" in capsys.readouterr().out
    with hist.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({**base, "t": "2026-11-10T01:14:00+00:00"}) + "\n")
    assert check.nba_crosscheck("2026-11-09", root=tmp_path) == 1
    assert "missing=1" in capsys.readouterr().out


def test_an_unreadable_sport_never_stops_the_others(tmp_path):
    def read(name):
        if name == "f.json":
            raise OSError("boom")
        return _bball_snapshot("2026-11-09T18:05:00Z")

    c = lel.Collector(root=tmp_path, read=read, sports={"ncaaf": "f.json", "wncaab": "w.json"})
    assert c.collect_once() == {"wncaab": 1}
