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
