"""The in-play overlay (lane `live-inplay-board-cadence`).

USER 2026-09-19: "we need live interval odds for all sports to reach the board
faster"; "Build it, deploy ASAP". The board's in-play rows came from a Layer 2
shortlist rewritten about every ~12 min, while the book grid rebuilt every ~2-3
min. The worker now writes the grid's fresh in-play rows as board cards
(`book_grid_inplay_<date>.json`), and web swaps them in at serve time.

Every behaviour asserted here is also shown OFF under `SYNDICATE_INPLAY_OVERLAY=off`
(reachability, off != on).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from syndicate.features.shared import book_grid_artifact as bga


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(bga, "data_root", lambda: tmp_path)
    monkeypatch.delenv("SYNDICATE_INPLAY_OVERLAY", raising=False)
    monkeypatch.delenv("SYNDICATE_INPLAY_OVERLAY_MAX_PRICE_AGE_SECONDS", raising=False)
    monkeypatch.delenv("SYNDICATE_INPLAY_OVERLAY_MAX_FILE_AGE_SECONDS", raising=False)
    monkeypatch.setattr(bga, "_publish_inplay_overlay", lambda path: True)
    bga._INPLAY_ROWS.clear()
    bga._INPLAY_PUBLISHED_NONEMPTY.clear()
    bga._INPLAY_READ_CACHE.clear()


def _row(state="live", age=120.0, market="spreads", segment="h1", event="ev1"):
    return {"sport": "ncaaf", "event_id": event, "kind": "game", "market": market, "segment": segment,
            "game": {"state": state}, "seen_age_seconds": age}


@pytest.fixture()
def fake_chain(monkeypatch):
    """Stand-in for the shortlist chain: one opportunity and one card per row."""
    from syndicate.features.shared import layer2_board

    calls = {}

    def build(rows):
        calls["rows"] = list(rows)
        return {"opportunities": [{"event_id": r["event_id"], "market": r["market"], "segment": r["segment"]} for r in rows]}

    def select(opps):
        calls["opps"] = list(opps)
        return {"rows": list(opps)}

    def cards(rows):
        return [{"sport": "ncaaf", "event_id": r["event_id"], "market": r["market"], "segment": r["segment"],
                 "line": 3.5, "odds": -110, "source": "layer2_shortlist"} for r in rows]

    monkeypatch.setattr(layer2_board, "build_layer2_rows", build)
    monkeypatch.setattr(layer2_board, "select_shortlist", select)
    monkeypatch.setattr(layer2_board, "layer2_rows_to_board_cards", cards)
    return calls


# --- worker side ---------------------------------------------------------------


def test_only_live_rows_seen_within_the_ceiling_are_in_play():
    grid = [_row(), _row(age=300.0), _row(age=301.0), _row(state="pre"), _row(age=None), "junk"]
    assert bga.select_inplay_rows(grid) == [grid[0], grid[1]]


def test_the_overlay_is_built_by_the_shortlist_chain_and_tagged(fake_chain):
    overlay = bga.build_inplay_overlay("ncaaf", "2026-09-19", [_row(), _row(market="totals", segment="q1")], grid_generated_at="G")
    assert overlay["rows_inplay"] == 2 and overlay["opportunities"] == 2
    assert [c["source"] for c in overlay["cards"]] == ["layer2_inplay_overlay"] * 2
    assert all(c["inplay_overlay"] is True and c["price_grid_generated_at"] == "G" for c in overlay["cards"])
    assert all(o["sport"] == "ncaaf" for o in fake_chain["opps"])


def test_write_uses_the_pre_cap_rows_and_leaves_the_grid_file_unchanged(fake_chain, tmp_path):
    grid = [_row(event="kept"), _row(event="cut_by_cap")]
    bga._remember_inplay_rows("ncaaf", "2026-09-19", "G1", grid)
    payload = {"generated_at": "G1", "rows": grid[:1]}
    path = bga.write_book_grid_artifact("ncaaf", "2026-09-19", payload)
    assert json.loads(path.read_text(encoding="utf-8")) == payload
    overlay = json.loads(bga.book_grid_inplay_artifact_path("ncaaf", "2026-09-19").read_text(encoding="utf-8"))
    assert sorted(c["event_id"] for c in overlay["cards"]) == ["cut_by_cap", "kept"]


def test_an_empty_overlay_is_written_only_to_clear_a_previous_one(fake_chain):
    target = bga.book_grid_inplay_artifact_path("ncaaf", "2026-09-19")
    bga.write_book_grid_artifact("ncaaf", "2026-09-19", {"generated_at": "G1", "rows": [_row(state="pre")]})
    assert not target.exists()
    bga.write_book_grid_artifact("ncaaf", "2026-09-19", {"generated_at": "G2", "rows": [_row()]})
    assert len(json.loads(target.read_text(encoding="utf-8"))["cards"]) == 1
    bga.write_book_grid_artifact("ncaaf", "2026-09-19", {"generated_at": "G3", "rows": [_row(state="final")]})
    assert json.loads(target.read_text(encoding="utf-8"))["cards"] == []


def test_an_overlay_failure_never_costs_the_grid(monkeypatch):
    from syndicate.features.shared import layer2_board

    monkeypatch.setattr(layer2_board, "build_layer2_rows", lambda rows: (_ for _ in ()).throw(RuntimeError("boom")))
    path = bga.write_book_grid_artifact("ncaaf", "2026-09-19", {"generated_at": "G", "rows": [_row()]})
    assert path.exists()
    assert not bga.book_grid_inplay_artifact_path("ncaaf", "2026-09-19").exists()


def test_kill_switch_stops_the_worker_writing(fake_chain, monkeypatch):
    monkeypatch.setenv("SYNDICATE_INPLAY_OVERLAY", "off")
    bga.write_book_grid_artifact("ncaaf", "2026-09-19", {"generated_at": "G", "rows": [_row()]})
    assert not bga.book_grid_inplay_artifact_path("ncaaf", "2026-09-19").exists()


# --- web read -------------------------------------------------------------------


def _write_overlay(sport, date, cards, *, written_at):
    bga.write_book_grid_inplay_overlay(sport, date, {"written_at": written_at, "cards": cards})


def test_web_reads_fresh_overlays_and_skips_stale_ones():
    now = datetime(2026, 9, 19, 17, 0, tzinfo=timezone.utc)
    _write_overlay("ncaaf", "2026-09-19", [{"event_id": "a"}], written_at=(now - timedelta(seconds=100)).strftime("%Y-%m-%dT%H:%M:%SZ"))
    _write_overlay("soccer", "2026-09-19", [{"event_id": "b"}], written_at=(now - timedelta(seconds=900)).strftime("%Y-%m-%dT%H:%M:%SZ"))
    cards, report = bga.inplay_overlay_cards("2026-09-19", now=now)
    assert [c["event_id"] for c in cards] == ["a"]
    assert report["sports"]["ncaaf"] == 1 and report["sports"]["soccer"].startswith("stale_")


def test_identity_ignores_line_and_side_so_a_moved_line_replaces_the_old_one():
    a = {"sport": "ncaaf", "event_id": "e", "market": "spreads", "segment": "h1", "line": 3.5, "side": "home"}
    b = dict(a, line=6.5, side="away")
    assert bga.inplay_overlay_identity(a) == bga.inplay_overlay_identity(b)
    assert bga.inplay_overlay_identity(a) != bga.inplay_overlay_identity(dict(a, segment="q1"))


# --- web merge --------------------------------------------------------------------


def _card(event, market="spreads", segment="h1", line=3.5, source="layer2_shortlist"):
    return {"sport": "ncaaf", "sport_slug": "ncaaf", "event_id": event, "market": market, "segment": segment,
            "line": line, "odds": -110, "source": source, "commence_time": "2026-09-19T16:00:00Z"}


def test_merge_replaces_same_identity_adds_new_and_leaves_earlier_dates(monkeypatch):
    from pipeline import intelligence_state as st

    overlay = [_card("live1", line=6.5, source="layer2_inplay_overlay"), _card("live2", segment="q1", source="layer2_inplay_overlay")]
    monkeypatch.setattr(bga, "inplay_overlay_cards", lambda date, **_: (list(overlay), {"sports": {"ncaaf": 2}, "newest_written_at": "W"}))
    earlier_date = _card("live1")  # a PREVIOUS date's card with the same identity: must not be touched
    cards = [earlier_date, _card("live1", line=3.5), _card("pregame1", market="totals", segment="full")]
    result = st._merge_inplay_overlay(cards, "2026-09-19", start=1)
    assert result == {"replaced": 1, "added": 1}
    assert cards[0] is earlier_date
    today = cards[1:]
    assert [(c["event_id"], c["source"]) for c in today] == [
        ("pregame1", "layer2_shortlist"), ("live1", "layer2_inplay_overlay"), ("live2", "layer2_inplay_overlay"),
    ]
    assert [c["line"] for c in today if c["event_id"] == "live1"] == [6.5]
    assert all(c["source_board_date"] == "2026-09-19" for c in today[1:])


def test_merge_is_inert_with_the_kill_switch(monkeypatch):
    from pipeline import intelligence_state as st

    _write_overlay("ncaaf", "2026-09-19", [_card("live1", line=6.5, source="layer2_inplay_overlay")],
                   written_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    on = [_card("live1")]
    assert st._merge_inplay_overlay(on, "2026-09-19") == {"replaced": 1, "added": 0}
    monkeypatch.setenv("SYNDICATE_INPLAY_OVERLAY", "off")
    off = [_card("live1")]
    assert st._merge_inplay_overlay(off, "2026-09-19") == {"replaced": 0, "added": 0}
    assert off[0]["source"] == "layer2_shortlist"


# --- web cache expiry on a newer overlay ------------------------------------------


def test_newest_overlay_mtime_is_the_max_over_sports_and_zero_when_none():
    import os

    assert bga.newest_inplay_overlay_mtime(["2026-09-19"]) == 0.0
    _write_overlay("ncaaf", "2026-09-19", [], written_at="2026-09-19T17:00:00Z")
    _write_overlay("wnba", "2026-09-19", [], written_at="2026-09-19T17:00:00Z")
    os.utime(bga.book_grid_inplay_artifact_path("ncaaf", "2026-09-19"), (1000.0, 1000.0))
    os.utime(bga.book_grid_inplay_artifact_path("wnba", "2026-09-19"), (2000.0, 2000.0))
    assert bga.newest_inplay_overlay_mtime(["2026-09-19", "2026-09-20"]) == 2000.0


@pytest.fixture()
def combined(monkeypatch):
    """read_combined_intelligence_response over one empty date; `builds` counts rebuilds."""
    from pipeline import intelligence_state as st

    monkeypatch.setenv("SYNDICATE_INTELLIGENCE_COMBINED_BOARD_CACHE_SECONDS", "180")
    monkeypatch.delenv("SYNDICATE_INPLAY_OVERLAY_CACHE_EXPIRY", raising=False)
    monkeypatch.delenv("SYNDICATE_INPLAY_OVERLAY_CACHE_MIN_AGE_SECONDS", raising=False)
    st._COMBINED_INTELLIGENCE_RESPONSE_CACHE.clear()
    st._COMBINED_OVERLAY_MTIME_BY_KEY.clear()
    builds: list[str] = []
    monkeypatch.setattr(st, "read_layer2_shortlist", lambda d: None)
    monkeypatch.setattr(st, "_read_single_date_response_for_combining", lambda d: builds.append(d))
    monkeypatch.setattr(st, "board_l2a_fallback_enabled", lambda: True)
    key = (("2026-09-19",), "all", None)

    def read():
        st.read_combined_intelligence_response(dates=["2026-09-19"])
        return len(builds)

    def age_entry(seconds):
        built_at, payload = st._COMBINED_INTELLIGENCE_RESPONSE_CACHE[key]
        st._COMBINED_INTELLIGENCE_RESPONSE_CACHE[key] = (built_at - seconds, payload)

    def land_overlay(mtime):
        import os

        _write_overlay("ncaaf", "2026-09-19", [], written_at="2026-09-19T17:00:00Z")
        os.utime(bga.book_grid_inplay_artifact_path("ncaaf", "2026-09-19"), (mtime, mtime))

    return read, age_entry, land_overlay


def test_a_newer_overlay_expires_the_cached_board_only_past_the_floor(combined):
    import time

    read, age_entry, land_overlay = combined
    land_overlay(time.time() - 100)
    assert read() == 1
    assert read() == 1  # same overlay: the TTL holds
    land_overlay(time.time())
    assert read() == 1  # newer overlay, but the entry is younger than the 45 s floor
    age_entry(60)
    assert read() == 2  # newer overlay and past the floor: rebuilt inside the 180 s TTL
    age_entry(60)
    assert read() == 2  # built against the newest overlay: the TTL holds again


def test_no_newer_overlay_keeps_the_ttl(combined):
    import time

    read, age_entry, land_overlay = combined
    land_overlay(time.time() - 100)
    assert read() == 1
    age_entry(120)
    assert read() == 1


def test_kill_switch_keeps_the_plain_ttl(combined, monkeypatch):
    import time

    read, age_entry, land_overlay = combined
    monkeypatch.setenv("SYNDICATE_INPLAY_OVERLAY_CACHE_EXPIRY", "off")
    land_overlay(time.time() - 100)
    assert read() == 1
    land_overlay(time.time())
    age_entry(60)
    assert read() == 1
    monkeypatch.delenv("SYNDICATE_INPLAY_OVERLAY_CACHE_EXPIRY")
    assert read() == 2  # off != on: the same state rebuilds with the switch removed


# --- the credit cap: the pregame segment tier on its own cadence --------------------


class _SegResponse:
    def __init__(self, event_id, status_code=200):
        self.status_code = status_code
        self.headers = {}
        self.url = "https://api.the-odds-api.com/v4/x"
        self.text = ""
        self._event_id = event_id

    def json(self):
        return {"id": self._event_id, "bookmakers": []}


class _SegSession:
    """Records every per-event call: the credit-spending thing is what is asserted."""

    def __init__(self, status_code=200):
        self.event_ids: list[str] = []
        self.status_code = status_code

    def get(self, url, params=None, timeout=None):
        event_id = url.rstrip("/").split("/")[-2]
        self.event_ids.append(event_id)
        return _SegResponse(event_id, self.status_code)


def _segments(session, now, env, state):
    from syndicate.features.shared import segment_odds_fetch as sof

    events = [
        {"id": "pre", "commence_time": (now + timedelta(minutes=90)).isoformat().replace("+00:00", "Z")},
        {"id": "live", "commence_time": (now - timedelta(minutes=30)).isoformat().replace("+00:00", "Z")},
    ]
    return sof.fetch_event_segments(api_key="k", sport="ncaaf", sport_key="americanfootball_ncaaf",
                                    base_url="https://api.the-odds-api.com/v4", events=events, session=session,
                                    now=now, env=env, pregame_state=state)


NOW_SEG = datetime(2026, 9, 19, 18, 0, tzinfo=timezone.utc)


def test_default_fetches_both_tiers_every_run(tmp_path):
    session = _SegSession()
    env = {"SYNDICATE_NCAAF_SEGMENT_MARKETS": "all"}
    for minutes in (0, 3):
        _, stats = _segments(session, NOW_SEG + timedelta(minutes=minutes), env, tmp_path / "s.json")
        assert stats["pregame_included"] is True and stats["pregame_deferred"] == 0
    assert sorted(session.event_ids) == ["live", "live", "pre", "pre"]
    assert not (tmp_path / "s.json").exists()


def test_pregame_tier_waits_for_its_interval_and_live_never_does(tmp_path):
    session = _SegSession()
    env = {"SYNDICATE_NCAAF_SEGMENT_MARKETS": "all", "SYNDICATE_NCAAF_SEGMENT_PREGAME_INTERVAL_SECONDS": "1800"}
    state = tmp_path / "s.json"
    _, first = _segments(session, NOW_SEG, env, state)
    assert sorted(session.event_ids) == ["live", "pre"] and first["pregame_included"] is True
    session.event_ids.clear()
    _, second = _segments(session, NOW_SEG + timedelta(minutes=3), env, state)
    assert session.event_ids == ["live"]
    assert second["pregame_included"] is False and second["pregame_deferred"] == 1
    session.event_ids.clear()
    _segments(session, NOW_SEG + timedelta(minutes=31), env, state)
    assert sorted(session.event_ids) == ["live", "pre"]


def test_a_run_where_every_call_failed_does_not_stamp_the_pregame_tier(tmp_path):
    env = {"SYNDICATE_NCAAF_SEGMENT_MARKETS": "all", "SYNDICATE_NCAAF_SEGMENT_PREGAME_INTERVAL_SECONDS": "1800"}
    state = tmp_path / "s.json"
    _segments(_SegSession(status_code=500), NOW_SEG, env, state)
    assert not state.exists()
    retry = _SegSession()
    _segments(retry, NOW_SEG + timedelta(minutes=3), env, state)
    assert sorted(retry.event_ids) == ["live", "pre"]


# --- live-odds-worker: in-play capture on its own clock -------------------------------


@pytest.fixture(scope="module")
def worker():
    import importlib.util
    import pathlib

    path = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "run_live_odds_refresh_worker.py"
    spec = importlib.util.spec_from_file_location("test_inplay_capture_worker", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_both_inplay_launchers_run_and_one_failure_never_costs_the_other(worker, monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(worker, "_launch_autorun_wnba_live_refresh", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(worker, "_launch_autorun_ncaaf_lines_refresh", lambda: calls.append("ncaaf"))
    worker._launch_inplay_capture_autoruns("thread")
    assert calls == ["ncaaf"]
    assert "WNBA_LIVE_AUTORUN_ERROR source=thread RuntimeError: boom" in capsys.readouterr().out


def test_the_main_loop_launches_through_the_same_locked_helper(worker, monkeypatch):
    sources = []
    monkeypatch.setattr(worker, "_launch_inplay_capture_autoruns", lambda source: sources.append(source))
    monkeypatch.setattr(worker, "_launch_autorun_soccer_pregame_refresh", lambda: None)
    monkeypatch.setattr(worker, "_launch_autorun_wnba_pregame_refresh", lambda: None)
    monkeypatch.setattr(worker, "_run_live_refresh_tick", lambda: {"ok": True})
    monkeypatch.setattr(worker, "_log_worker_memory", lambda *a, **k: None)
    worker._run_tick()
    assert sources == ["loop"]


def test_the_helper_holds_the_shared_lock_while_launching(worker, monkeypatch):
    held = []
    monkeypatch.setattr(worker, "_launch_autorun_wnba_live_refresh", lambda: held.append(worker._INPLAY_LAUNCH_LOCK.locked()))
    monkeypatch.setattr(worker, "_launch_autorun_ncaaf_lines_refresh", lambda: held.append(worker._INPLAY_LAUNCH_LOCK.locked()))
    worker._launch_inplay_capture_autoruns("loop")
    assert held == [True, True] and not worker._INPLAY_LAUNCH_LOCK.locked()


def test_the_thread_ticks_the_launchers_and_stops_on_its_event(worker, monkeypatch):
    ticks = []

    def once(source):
        ticks.append(source)
        worker._INPLAY_CAPTURE_STOP.set()

    monkeypatch.setattr(worker, "_launch_inplay_capture_autoruns", once)
    worker._INPLAY_CAPTURE_STOP.clear()
    worker._inplay_capture_background_loop()
    assert ticks == ["thread"]


def test_kill_switch_and_tick_floor(worker, monkeypatch):
    monkeypatch.setenv("SYNDICATE_INPLAY_CAPTURE_THREAD", "off")
    assert worker.inplay_capture_thread_enabled() is False
    assert worker.start_inplay_capture_loop() is False
    monkeypatch.delenv("SYNDICATE_INPLAY_CAPTURE_THREAD")
    assert worker.inplay_capture_thread_enabled() is True  # absent = ON, stated
    monkeypatch.setenv("SYNDICATE_INPLAY_CAPTURE_TICK_SECONDS", "2")
    assert worker.inplay_capture_tick_seconds() == 10
    monkeypatch.setenv("SYNDICATE_INPLAY_CAPTURE_TICK_SECONDS", "junk")
    assert worker.inplay_capture_tick_seconds() == 30


# --- NFL gets its own in-play capture lane -----------------------------------------


def test_nfl_lines_autorun_is_off_when_the_flag_is_absent_and_launches_nothing(worker, monkeypatch):
    launched = []
    monkeypatch.delenv("SYNDICATE_ENABLE_NFL_LINES_REFRESH_AUTORUN", raising=False)
    monkeypatch.setattr(worker, "launch_refresh_run", lambda **kw: launched.append(kw))
    worker._launch_autorun_nfl_lines_refresh()
    assert launched == [], "absent means OFF, and this one spends credits"
    assert worker._nfl_lines_refresh_enabled() is False


def test_nfl_lines_autorun_launches_fast_on_its_own_lane_when_enabled(worker, monkeypatch, tmp_path):
    launched = []
    monkeypatch.setenv("SYNDICATE_ENABLE_NFL_LINES_REFRESH_AUTORUN", "on")
    monkeypatch.setenv("SYNDICATE_NFL_LINES_REFRESH_INTERVAL_SECONDS", "150")
    monkeypatch.setattr(worker, "_nfl_lines_autorun_status_path", lambda: tmp_path / "nfl_status.json")
    monkeypatch.setattr(worker, "_nfl_active_for_date", lambda d: True)
    monkeypatch.setattr(worker, "_nfl_has_games_within_horizon", lambda d: True)
    monkeypatch.setattr(worker, "launch_refresh_run", lambda **kw: launched.append(kw) or {"runStamp": "r1"})
    worker._launch_autorun_nfl_lines_refresh()
    assert len(launched) == 1
    call = launched[0]
    # mode=fast is what leaves player props -- the largest credit family -- to the full sweep.
    assert call["sports"] == "nfl" and call["phase"] == "live" and call["mode"] == "fast"
    assert call["lane"] == "live-odds-worker-nfl-lines", "must not contend with the combined sweep's lane"
    assert call["skip_mirror"] is True and call["regions"] == "us"
    # The interval gate holds the second call inside 150 s.
    worker._launch_autorun_nfl_lines_refresh()
    assert len(launched) == 1


def test_the_capture_thread_launches_nfl_too(worker, monkeypatch):
    calls = []
    monkeypatch.setattr(worker, "_launch_autorun_wnba_live_refresh", lambda: calls.append("wnba"))
    monkeypatch.setattr(worker, "_launch_autorun_ncaaf_lines_refresh", lambda: calls.append("ncaaf"))
    monkeypatch.setattr(worker, "_launch_autorun_nfl_lines_refresh", lambda: calls.append("nfl"))
    worker._launch_inplay_capture_autoruns("thread")
    assert calls == ["wnba", "ncaaf", "nfl"]


def test_an_nfl_failure_never_costs_the_ncaaf_launch(worker, monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(worker, "_launch_autorun_wnba_live_refresh", lambda: None)
    monkeypatch.setattr(worker, "_launch_autorun_ncaaf_lines_refresh", lambda: calls.append("ncaaf"))
    monkeypatch.setattr(worker, "_launch_autorun_nfl_lines_refresh", lambda: (_ for _ in ()).throw(RuntimeError("nfl boom")))
    worker._launch_inplay_capture_autoruns("loop")
    assert calls == ["ncaaf"]
    assert "NFL_LINES_AUTORUN_ERROR source=loop RuntimeError: nfl boom" in capsys.readouterr().out


def test_the_nfl_odds_step_passes_the_refresh_mode_through(monkeypatch):
    """`--mode fast` must reach refresh_nfl_oddsapi.py, or a fast run still fetches props."""
    import argparse
    import importlib.util
    import pathlib

    path = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "refresh_odds_sources.py"
    import sys

    spec = importlib.util.spec_from_file_location("test_refresh_odds_sources_nfl", path)
    module = importlib.util.module_from_spec(spec)
    # Registered BEFORE exec: the module defines dataclasses, and @dataclass
    # resolves its own module out of sys.modules while the class body runs.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    seen = {}
    for mode in ("fast", "full"):
        args = argparse.Namespace(date="2026-09-20", season=2026, week=3, mode=mode, phase="live")
        steps = module._build_nfl_steps(args)
        odds = next(s for s in steps if s.name == "nfl_oddsapi_refresh")
        command = list(odds.command)
        assert "--mode" in command, "the step drops --mode, so fast runs props anyway"
        seen[mode] = command[command.index("--mode") + 1]
    assert seen == {"fast": "fast", "full": "full"}



# --- lever 1: warm a watched board as soon as a newer overlay lands (2026-09-21) ------------------
#
# Before: the expiry above only fired when a REQUEST arrived, so a new overlay waited for the next
# visitor (~56 s per gunicorn worker on 2026-09-20), who then paid the 5-18 s rebuild.


KEY = (("2026-09-19",), "all", None)


@pytest.fixture()
def warm(combined, monkeypatch):
    from pipeline import intelligence_state as st

    st._COMBINED_BOARD_ACTIVE_KEYS.clear()
    monkeypatch.setattr(st, "_ensure_combined_board_overlay_warmer", lambda: None)  # no real thread in tests
    return (st,) + tuple(combined)


def test_a_watched_board_is_rebuilt_when_a_newer_overlay_lands_with_no_request(warm, capsys):
    import time

    st, read, age_entry, land_overlay = warm
    land_overlay(time.time() - 100)
    assert read() == 1
    assert KEY in st._COMBINED_BOARD_ACTIVE_KEYS, "a request must mark the board as watched"
    seen_at = st._COMBINED_BOARD_ACTIVE_KEYS[KEY]

    land_overlay(time.time())
    age_entry(60)
    warmed = st._warm_combined_board_overlays_once()
    assert len(warmed) == 1 and warmed[0]["rebuilt"] is True
    # The warmer's own call must not keep a board warm that nobody asked for.
    assert st._COMBINED_BOARD_ACTIVE_KEYS[KEY] == seen_at
    assert read() == 2, "the warmer rebuilt it; the next request is served that board, not a second rebuild"
    assert "COMBINED_BOARD_OVERLAY_WARMED" in capsys.readouterr().out


def test_the_warmer_leaves_a_board_alone_when_no_newer_overlay_landed(warm):
    import time

    st, read, age_entry, land_overlay = warm
    land_overlay(time.time() - 100)
    assert read() == 1
    age_entry(120)
    assert st._warm_combined_board_overlays_once() == []
    assert read() == 1


def test_the_warmer_keeps_the_rebuild_floor(warm):
    """Same decision as a request: a board younger than the floor is not rebuilt, so the
    warmer cannot rebuild more often than requests already could."""
    import time

    st, read, age_entry, land_overlay = warm
    land_overlay(time.time() - 100)
    assert read() == 1
    land_overlay(time.time())
    assert st._warm_combined_board_overlays_once() == []


def test_a_board_nobody_watched_recently_is_dropped_not_warmed(warm):
    import time

    st, read, age_entry, land_overlay = warm
    land_overlay(time.time() - 100)
    assert read() == 1
    st._COMBINED_BOARD_ACTIVE_KEYS[KEY] = time.time() - st._COMBINED_BOARD_ACTIVE_WINDOW_SECONDS - 1
    land_overlay(time.time())
    age_entry(60)
    assert st._warm_combined_board_overlays_once() == []
    assert KEY not in st._COMBINED_BOARD_ACTIVE_KEYS


def test_the_warmer_is_on_by_default_only_when_hosted(monkeypatch):
    from pipeline import intelligence_state as st
    from syndicate.features.shared import request_path_guard as guard

    monkeypatch.delenv("SYNDICATE_COMBINED_BOARD_OVERLAY_WARMER", raising=False)
    monkeypatch.setattr(guard, "hosted_signal", lambda: None)
    assert st.combined_board_overlay_warmer_state() == (False, "not_hosted")
    monkeypatch.setattr(guard, "hosted_signal", lambda: "RENDER")
    assert st.combined_board_overlay_warmer_state() == (True, "hosted:RENDER")
    monkeypatch.setenv("SYNDICATE_COMBINED_BOARD_OVERLAY_WARMER", "off")
    assert st.combined_board_overlay_warmer_state() == (False, "env_off"), "the kill switch beats hosted"
    monkeypatch.setattr(guard, "hosted_signal", lambda: None)
    monkeypatch.setenv("SYNDICATE_COMBINED_BOARD_OVERLAY_WARMER", "on")
    assert st.combined_board_overlay_warmer_state() == (True, "env_on")


def test_the_warmer_thread_starts_once_and_only_when_enabled(monkeypatch):
    from pipeline import intelligence_state as st

    started: list[str] = []

    class FakeThread:
        def __init__(self, target=None, name=None, daemon=None):
            self.name = name

        def start(self):
            started.append(self.name)

    monkeypatch.setattr(st.threading, "Thread", FakeThread)
    monkeypatch.setattr(st, "_COMBINED_BOARD_WARMER_STARTED", False)
    monkeypatch.setenv("SYNDICATE_COMBINED_BOARD_OVERLAY_WARMER", "off")
    st._ensure_combined_board_overlay_warmer()
    assert started == []

    monkeypatch.setattr(st, "_COMBINED_BOARD_WARMER_STARTED", False)
    monkeypatch.setenv("SYNDICATE_COMBINED_BOARD_OVERLAY_WARMER", "on")
    st._ensure_combined_board_overlay_warmer()
    st._ensure_combined_board_overlay_warmer()
    assert started == ["combined-board-overlay-warmer"], "one thread per process"
