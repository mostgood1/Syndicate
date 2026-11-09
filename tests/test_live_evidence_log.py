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


def test_an_unreadable_sport_never_stops_the_others(tmp_path):
    def read(name):
        if name == "f.json":
            raise OSError("boom")
        return _bball_snapshot("2026-11-09T18:05:00Z")

    c = lel.Collector(root=tmp_path, read=read, sports={"ncaaf": "f.json", "wncaab": "w.json"})
    assert c.collect_once() == {"wncaab": 1}
