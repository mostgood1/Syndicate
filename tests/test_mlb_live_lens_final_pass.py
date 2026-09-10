"""The final pass on past MLB live-lens reports (lane `mlb-lens-final-status`).

`live_lens_loop` writes only today's report, so a game still running at the
midnight-Central roll kept a mid-game row in yesterday's report for good -- and
on web, which holds no feed payload for a past date, that row IS the date's
status. Measured 2026-09-10: 823095/823907 served `Live` for six days; 9 games
on 7 of 9 dates.

These pin that the pass finalizes exactly the stale rows, touches nothing else,
costs nothing once a date is final, survives a re-freeze by another writer, is
reachable from the tick without being able to break it -- and that a finalized
row is what makes web's merge serve Final.

The WEB half exists because the local half alone was measured inert on web
(2026-09-10, live-odds-worker `e4410f37`): the publish sweep refuses slates more
than a day old, and web serves whichever of its two copies is newer. Those tests
pin that it patches the copy web SERVES, keeps that copy's content, and never
writes this service's own files.
"""
from __future__ import annotations

import json
import os
import urllib.error

import pytest

from syndicate.features.mlb import live_lens_final_pass as fp

TODAY = "2026-09-10"


def _slim_report(date_str, rows):
    games = [dict(row) for row in rows]
    final = sum(1 for r in games if r["status"]["abstract"] == "Final")
    live = sum(1 for r in games if r["status"]["abstract"] == "Live")
    return {
        "date": date_str,
        "generatedAt": f"{date_str}T23:59:10-05:00",
        "counts": {"games": len(games), "live": live, "final": final, "pregame": len(games) - live - final},
        "performance": {},
        "games": games,
    }


FROZEN_0903 = [
    {"gamePk": 823337, "startTime": "6:05 PM", "status": {"abstract": "Final", "detailed": "Final"}},
    {"gamePk": 823095, "startTime": "8:40 PM", "status": {"abstract": "Live", "detailed": "In Progress"},
     "props": [{"id": "p1"}], "liveProps": [{"id": "lp1"}]},
    {"gamePk": 823907, "startTime": "9:10 PM", "status": {"abstract": "Live", "detailed": "In Progress"}},
]
FINAL_0909 = [{"gamePk": 823901, "startTime": "7:05 PM", "status": {"abstract": "Final", "detailed": "Final"}}]
OLD_0820 = [{"gamePk": 800001, "startTime": "7:05 PM", "status": {"abstract": "Live", "detailed": "In Progress"}}]


@pytest.fixture()
def reports(tmp_path, monkeypatch):
    fp._reset_state_for_tests()
    monkeypatch.delenv("SYNDICATE_MLB_LIVE_LENS_FINAL_PASS", raising=False)
    monkeypatch.delenv("SYNDICATE_MLB_LIVE_LENS_FINAL_PASS_LOOKBACK_DAYS", raising=False)
    monkeypatch.delenv("SYNDICATE_MLB_LIVE_LENS_FINAL_PASS_WEB", raising=False)
    # No publish URL: the web half must answer `not_configured` here and never reach a network.
    monkeypatch.delenv("SYNDICATE_WEB_PUBLISH_URL", raising=False)

    def _path(date_str):
        return tmp_path / f"live_lens_report_{date_str.replace('-', '_')}.json"

    monkeypatch.setattr(fp, "live_lens_report_path", _path)
    for date_str, rows in (("2026-09-03", FROZEN_0903), ("2026-09-09", FINAL_0909), ("2026-08-20", OLD_0820)):
        _path(date_str).write_text(json.dumps(_slim_report(date_str, rows), indent=2), encoding="utf-8")
    yield _path
    fp._reset_state_for_tests()


class _Fetch:
    """StatsAPI stand-in: records which dates were asked for."""

    def __init__(self, statuses):
        self.statuses = statuses
        self.calls = []

    def __call__(self, date_str):
        self.calls.append(date_str)
        return self.statuses.get(date_str, {})


FINAL = {"abstract": "Final", "detailed": "Final"}


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_a_frozen_row_is_finalized_and_nothing_else_changes(reports):
    fetch = _Fetch({"2026-09-03": {823095: FINAL, 823907: {"abstract": "Final", "detailed": "Game Over"}}})
    stats = fp.finalize_recent_mlb_live_lens_reports(TODAY, now_epoch=1_000, fetch=fetch)
    report = _load(reports("2026-09-03"))
    rows = {row["gamePk"]: row for row in report["games"]}
    assert rows[823095]["status"] == FINAL
    assert rows[823907]["status"] == {"abstract": "Final", "detailed": "Game Over"}
    assert rows[823095]["finalizedBy"] == "live_lens_final_pass"
    assert rows[823095]["liveProps"] == [{"id": "lp1"}], "only status is rewritten"
    assert rows[823337] == FROZEN_0903[0], "an already-final row is untouched"
    assert report["counts"] == {"games": 3, "live": 0, "final": 3, "pregame": 0}
    assert [item["gamePk"] for item in report["finalPass"][-1]["finalized"]] == [823095, 823907]
    assert stats["finalized"] == 2 and stats["still_open"] == 0
    assert "2026-09-03:823095" in stats["finalized_games"]


def test_an_all_final_report_costs_no_fetch_and_no_write(reports):
    before = os.stat(reports("2026-09-09")).st_mtime_ns
    fetch = _Fetch({"2026-09-03": {823095: FINAL, 823907: FINAL}})
    fp.finalize_recent_mlb_live_lens_reports(TODAY, now_epoch=1_000, fetch=fetch)
    assert "2026-09-09" not in fetch.calls
    assert os.stat(reports("2026-09-09")).st_mtime_ns == before


def test_a_game_statsapi_still_calls_live_is_left_alone(reports):
    fetch = _Fetch({"2026-09-03": {823095: FINAL, 823907: {"abstract": "Live", "detailed": "In Progress"}}})
    stats = fp.finalize_recent_mlb_live_lens_reports(TODAY, now_epoch=1_000, fetch=fetch)
    rows = {row["gamePk"]: row for row in _load(reports("2026-09-03"))["games"]}
    assert rows[823907]["status"]["abstract"] == "Live"
    assert stats["finalized"] == 1 and stats["still_open"] == 1
    # Not verified, so the next unthrottled pass asks again.
    fetch.statuses["2026-09-03"][823907] = FINAL
    fp.finalize_recent_mlb_live_lens_reports(TODAY, now_epoch=10_000, fetch=fetch)
    rows = {row["gamePk"]: row for row in _load(reports("2026-09-03"))["games"]}
    assert rows[823907]["status"] == FINAL


def test_an_unreadable_statsapi_writes_nothing(reports):
    before = reports("2026-09-03").read_bytes()
    stats = fp.finalize_recent_mlb_live_lens_reports(TODAY, now_epoch=1_000, fetch=lambda d: None)
    assert reports("2026-09-03").read_bytes() == before
    assert stats["fetch_failed"] >= 1 and stats["finalized"] == 0


def test_throttle_and_kill_switch(reports, monkeypatch):
    fetch = _Fetch({"2026-09-03": {823095: FINAL, 823907: FINAL}})
    fp.finalize_recent_mlb_live_lens_reports(TODAY, now_epoch=1_000, fetch=fetch)
    calls = len(fetch.calls)
    assert fp.finalize_recent_mlb_live_lens_reports(TODAY, now_epoch=1_060, fetch=fetch)["reason"] == "throttled"
    assert len(fetch.calls) == calls
    monkeypatch.setenv("SYNDICATE_MLB_LIVE_LENS_FINAL_PASS", "0")
    assert fp.finalize_recent_mlb_live_lens_reports(TODAY, now_epoch=99_000, fetch=fetch)["reason"] == "disabled"


def test_the_lookback_is_bounded(reports):
    fetch = _Fetch({"2026-08-20": {800001: FINAL}})
    fp.finalize_recent_mlb_live_lens_reports(TODAY, now_epoch=1_000, fetch=fetch)
    assert "2026-08-20" not in fetch.calls, "21 days back is outside the default 10-day look-back"
    assert _load(reports("2026-08-20"))["games"][0]["status"]["abstract"] == "Live"


def test_a_refrozen_report_is_caught_on_the_next_pass(reports):
    fetch = _Fetch({"2026-09-03": {823095: FINAL, 823907: FINAL}})
    fp.finalize_recent_mlb_live_lens_reports(TODAY, now_epoch=1_000, fetch=fetch)
    # Another writer puts the frozen copy back (a new mtime).
    path = reports("2026-09-03")
    path.write_text(json.dumps(_slim_report("2026-09-03", FROZEN_0903), indent=2), encoding="utf-8")
    os.utime(path, ns=(os.stat(path).st_atime_ns, os.stat(path).st_mtime_ns + 5_000_000_000))
    stats = fp.finalize_recent_mlb_live_lens_reports(TODAY, now_epoch=10_000, fetch=fetch)
    assert stats["finalized"] == 2
    assert all(row["status"]["abstract"] == "Final" for row in _load(path)["games"])


def test_a_finalized_row_makes_the_web_merge_serve_final(reports):
    """Web has no feed payload for a past date, so its base status is
    Pregame/Scheduled and the lens row decides. After the pass, it decides Final."""
    from syndicate.features.mlb import cards

    fp.finalize_recent_mlb_live_lens_reports(
        TODAY, now_epoch=1_000, fetch=_Fetch({"2026-09-03": {823095: FINAL, 823907: FINAL}})
    )
    row = next(r for r in _load(reports("2026-09-03"))["games"] if r["gamePk"] == 823095)
    base = {"gamePk": 823095, "status": cards._source_status(None)}
    assert base["status"]["abstract"] == "Pregame", "fixture: web's base for a past date"
    assert cards._merge_live_lens_row_into_game(base, row)["status"] == FINAL


def test_the_tick_runs_the_pass_after_the_sports_and_cannot_be_broken_by_it(tmp_path, monkeypatch):
    from syndicate.features.shared import live_lens_loop as loop

    monkeypatch.setattr(loop, "_live_lens_active_sports", lambda: ("mlb",))
    monkeypatch.setattr(loop, "_run_live_lens_tick_for_sport", lambda sport, date_str: {"ok": True, "sport": sport})
    monkeypatch.setattr(loop, "write_json_file", lambda *a, **k: None)
    monkeypatch.setattr(loop, "_meta_dir", lambda: tmp_path)
    monkeypatch.setattr(loop, "central_today_iso", lambda: TODAY)
    seen = []
    monkeypatch.setattr(fp, "finalize_recent_mlb_live_lens_reports",
                        lambda today_iso: seen.append(today_iso) or {"ran": True, "finalized": 0})
    meta = loop._run_live_lens_tick()
    assert seen == [TODAY], "the tick must call the final pass with today's date"
    assert meta["mlbFinalPass"]["ran"] is True

    def _boom(today_iso):
        raise RuntimeError("statsapi down")

    monkeypatch.setattr(fp, "finalize_recent_mlb_live_lens_reports", _boom)
    meta = loop._run_live_lens_tick()
    assert meta["ok"] is True, "a failed final pass must not fail the tick"
    assert "RuntimeError" in meta["mlbFinalPass"]["error"]


# --- the web half ------------------------------------------------------------

LIVE = {"abstract": "Live", "detailed": "In Progress"}


def _rel(form, date_str):
    return form.format(name=f"live_lens_report_{date_str.replace('-', '_')}.json")


def _full_report(date_str, rows):
    """Web's FULL target: rows carry the fields the cards merge copies onto a card."""
    report = _slim_report(date_str, rows)
    for row in report["games"]:
        row.update({"actual_box_panel": {"R": [3, 4]}, "gameLens": {"k": 1}, "market_tiles": [{"t": 1}]})
    return report


class _Web:
    """Web's disk: rel -> (text, mtime). Records every read and publish."""

    def __init__(self, copies):
        self.copies = dict(copies)
        self.reads, self.published = [], []
        self.fail_publish = False
        self.fail_probe = False

    def probe(self, rel, **_):
        if self.fail_probe:
            return fp.WebCopy("failed")
        if rel not in self.copies:
            return fp.WebCopy("absent")
        text, mtime = self.copies[rel]
        return fp.WebCopy("ok", mtime=mtime, size=len(text))

    def read(self, rel, **_):
        self.reads.append(rel)
        if rel not in self.copies:
            return fp.WebCopy("absent")
        text, mtime = self.copies[rel]
        return fp.WebCopy("ok", mtime=mtime, size=len(text), text=text)

    def publish(self, rel, text, **_):
        if self.fail_publish:
            return False
        self.published.append(rel)
        newest = max(mtime for _, mtime in self.copies.values())
        self.copies[rel] = (text, newest + 1.0)
        return True

    def rows(self, rel):
        return {row["gamePk"]: row for row in json.loads(self.copies[rel][0])["games"]}


@pytest.fixture()
def web(reports, monkeypatch):
    """Web copies for 09-04 (the full target served, 823905 frozen) and 09-09 (the
    slim form NEWER than the target, 823900 frozen in it) -- both measured shapes."""
    copies = {
        _rel(fp.WEB_TARGET_FORM, "2026-09-04"): (json.dumps(_full_report("2026-09-04", [
            {"gamePk": 823905, "startTime": "7:05 PM", "status": LIVE}])), 200.0),
        _rel(fp.WEB_SLIM_FORM, "2026-09-04"): (json.dumps(_slim_report("2026-09-04", [
            {"gamePk": 823905, "startTime": "7:05 PM", "status": {"abstract": "Final", "detailed": "Game Over"}}])),
            100.0),
        _rel(fp.WEB_TARGET_FORM, "2026-09-09"): (json.dumps(_full_report("2026-09-09", [
            {"gamePk": 823900, "startTime": "7:05 PM", "status": FINAL}])), 100.0),
        _rel(fp.WEB_SLIM_FORM, "2026-09-09"): (json.dumps(_slim_report("2026-09-09", [
            {"gamePk": 823900, "startTime": "7:05 PM", "status": LIVE}])), 100.5),
    }
    store = _Web(copies)
    local = {}
    monkeypatch.setattr(fp, "_web_configured", lambda: True)
    monkeypatch.setattr(fp, "probe_web_copy", store.probe)
    monkeypatch.setattr(fp, "read_web_copy", store.read)
    monkeypatch.setattr(fp, "publish_web_copy", store.publish)
    monkeypatch.setattr(fp, "_local_form_mtime_ns", lambda rel: local.get(rel, -1))
    store.local = local
    return store


WEB_FETCH = {
    "2026-09-03": {823095: FINAL, 823907: FINAL},
    "2026-09-04": {823905: {"abstract": "Final", "detailed": "Game Over"}},
    "2026-09-09": {823900: {"abstract": "Final", "detailed": "Game Over"}},
}


def test_web_patches_the_target_it_serves_and_keeps_that_copys_content(web):
    stats = fp.finalize_recent_mlb_live_lens_reports(TODAY, now_epoch=1_000, fetch=_Fetch(WEB_FETCH))
    target = _rel(fp.WEB_TARGET_FORM, "2026-09-04")
    row = web.rows(target)[823905]
    assert row["status"] == {"abstract": "Final", "detailed": "Game Over"}
    assert row["finalizedBy"] == "live_lens_final_pass"
    assert row["actual_box_panel"] == {"R": [3, 4]} and row["market_tiles"] == [{"t": 1}], (
        "web's own FULL copy is patched -- never replaced by a slimmer one"
    )
    assert _rel(fp.WEB_SLIM_FORM, "2026-09-04") not in web.published, "the form web does not serve is left alone"
    assert "2026-09-04:823905" in stats["web"]["finalized_games"]


def test_when_the_slim_form_is_newer_it_is_the_one_patched(web):
    """09-09 as measured: web's reconcile serves the slim form, so the target's Final is invisible."""
    stats = fp.finalize_recent_mlb_live_lens_reports(TODAY, now_epoch=1_000, fetch=_Fetch(WEB_FETCH))
    slim = _rel(fp.WEB_SLIM_FORM, "2026-09-09")
    assert slim in web.published
    assert _rel(fp.WEB_TARGET_FORM, "2026-09-09") not in web.published
    assert web.rows(slim)[823900]["status"]["abstract"] == "Final"
    assert stats["web"]["served_slim"] == 1
    assert stats["web"]["published"] == 2 and stats["web"]["still_open"] == 0


def test_a_date_web_serves_final_is_read_once_then_skipped_until_this_services_copy_changes(web):
    fp.finalize_recent_mlb_live_lens_reports(TODAY, now_epoch=1_000, fetch=_Fetch(WEB_FETCH))
    reads = len(web.reads)
    stats = fp.finalize_recent_mlb_live_lens_reports(TODAY, now_epoch=10_000, fetch=_Fetch(WEB_FETCH))
    assert len(web.reads) == reads and stats["web"]["skipped_verified"] == 10
    # This service's own copy changes -- its sweep could now publish over web's.
    web.local[_rel(fp.WEB_SLIM_FORM, "2026-09-09")] = 5
    stats = fp.finalize_recent_mlb_live_lens_reports(TODAY, now_epoch=20_000, fetch=_Fetch(WEB_FETCH))
    assert web.reads[reads:] == [_rel(fp.WEB_SLIM_FORM, "2026-09-09")]


def test_an_unreadable_web_publishes_nothing_and_is_retried(web):
    web.fail_probe = True
    stats = fp.finalize_recent_mlb_live_lens_reports(TODAY, now_epoch=1_000, fetch=_Fetch(WEB_FETCH))
    assert web.published == [] and stats["web"]["read_failed"] == 10
    web.fail_probe = False
    stats = fp.finalize_recent_mlb_live_lens_reports(TODAY, now_epoch=10_000, fetch=_Fetch(WEB_FETCH))
    assert stats["web"]["published"] == 2


def test_a_failed_publish_is_retried_on_the_next_pass(web):
    web.fail_publish = True
    stats = fp.finalize_recent_mlb_live_lens_reports(TODAY, now_epoch=1_000, fetch=_Fetch(WEB_FETCH))
    assert stats["web"]["publish_failed"] == 2 and stats["web"]["finalized"] == 0
    web.fail_publish = False
    stats = fp.finalize_recent_mlb_live_lens_reports(TODAY, now_epoch=10_000, fetch=_Fetch(WEB_FETCH))
    assert stats["web"]["published"] == 2


def test_the_web_half_never_writes_this_services_files(web, reports):
    before = {d: reports(d).read_bytes() for d in ("2026-09-09", "2026-08-20")}
    fp.finalize_recent_mlb_live_lens_reports(TODAY, now_epoch=1_000, fetch=_Fetch(WEB_FETCH))
    assert {d: reports(d).read_bytes() for d in before} == before


def test_the_web_half_is_off_when_switched_off_or_unconfigured(web, monkeypatch):
    monkeypatch.setenv("SYNDICATE_MLB_LIVE_LENS_FINAL_PASS_WEB", "0")
    stats = fp.finalize_recent_mlb_live_lens_reports(TODAY, now_epoch=1_000, fetch=_Fetch(WEB_FETCH))
    assert stats["web"] == {"ran": False, "reason": "disabled"} and web.reads == []
    monkeypatch.delenv("SYNDICATE_MLB_LIVE_LENS_FINAL_PASS_WEB")
    monkeypatch.setattr(fp, "_web_configured", lambda: False)
    stats = fp.finalize_recent_mlb_live_lens_reports(TODAY, now_epoch=10_000, fetch=_Fetch(WEB_FETCH))
    assert stats["web"] == {"ran": False, "reason": "not_configured"} and web.reads == []


def test_the_budget_defers_what_it_cannot_reach(web):
    ticks = iter([0.0] + [0.0] * 6 + [999.0] * 20)
    stats = fp.finalize_recent_mlb_live_lens_reports(
        TODAY, now_epoch=1_000, fetch=_Fetch(WEB_FETCH), web_budget_seconds=60.0, clock=lambda: next(ticks)
    )
    assert stats["web"]["deferred"] > 0
    assert stats["web"]["deferred"] + stats["web"]["dates_checked"] + stats["web"]["absent"] == 10


def test_probe_reads_web_mtime_from_a_304_without_a_body(monkeypatch):
    from email.message import Message

    from syndicate.features.shared import artifact_publisher

    headers = Message()
    headers["X-Artifact-Mtime"] = "1789079139.25"
    headers["X-Artifact-Size"] = "132548"
    seen = []

    def _urlopen(request, timeout):
        seen.append(request.full_url)
        raise urllib.error.HTTPError(request.full_url, 304, "Not Modified", headers, None)

    monkeypatch.setenv("SYNDICATE_WEB_PUBLISH_URL", "http://web.invalid")
    monkeypatch.setenv("ADMIN_TOKEN", "t")
    monkeypatch.setattr(fp.urllib.request, "urlopen", _urlopen)
    copy = fp.probe_web_copy("mlb_source/data/live_lens/live_lens_report_2026_09_09.json")
    assert copy == fp.WebCopy("ok", mtime=1789079139.25, size=132548)
    assert "/api/ops/artifacts/stream?path=" in seen[0] and "since=" in seen[0]

    def _missing(request, timeout):
        raise urllib.error.HTTPError(request.full_url, 404, "Not Found", Message(), None)

    monkeypatch.setattr(fp.urllib.request, "urlopen", _missing)
    assert fp.probe_web_copy("mlb_source/data/live_lens/x.json").state == "absent"
    assert artifact_publisher._stream_url("a/b.json").endswith("path=a%2Fb.json")


def test_publish_web_copy_streams_a_temp_file_under_the_real_path(monkeypatch):
    from syndicate.features.shared import artifact_publisher

    sent = {}

    def _streamed(file_path, *, relative_path, url, token, timeout_seconds, publisher=None):
        sent.update(path=file_path, body=file_path.read_text(encoding="utf-8"), rel=relative_path, url=url)
        return True

    monkeypatch.setenv("SYNDICATE_WEB_PUBLISH_URL", "http://web.invalid")
    monkeypatch.setenv("ADMIN_TOKEN", "t")
    monkeypatch.setattr(artifact_publisher, "_publish_streamed", _streamed)
    rel = "mlb_source/source_artifacts/data/live_lens/live_lens_report_2026_09_04.json"
    assert fp.publish_web_copy(rel, '{"games": []}') is True
    assert sent["rel"] == rel and sent["body"] == '{"games": []}'
    assert sent["url"].endswith("/api/ops/artifacts/publish")
    assert not sent["path"].exists(), "the temp file is removed"
