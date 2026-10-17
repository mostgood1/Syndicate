"""The every-15-minute picks refresh (user 2026-10-16: "for Syndicate picks (from the layer 2 board) we need the cheat
sheets to be checking for new opps and adding them on a regular basis")."""
from __future__ import annotations

import importlib.util
import json
import os
import time
from pathlib import Path

import pytest


def _script():
    spec = importlib.util.spec_from_file_location(
        "build_cheat_sheets", Path(__file__).resolve().parents[1] / "scripts" / "build_cheat_sheets.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _card(pick_id, *, sport="mlb", score=1.0, day="2026-10-15", suggested=True):
    return {"pick_id": pick_id, "kind": "game", "sport": sport, "event_id": "e7", "market": "h2h", "side": "away",
            "line": None, "segment": "full", "suggested": suggested, "market_state": "pregame", "game_date": day,
            "board_score": score, "board_lane": "opportunity", "player_name": None, "display_name": "Milwaukee Brewers",
            "matchup": "Milwaukee Brewers @ Los Angeles Dodgers", "home_team": "Los Angeles Dodgers",
            "away_team": "Milwaukee Brewers", "odds": 138,
            "quote": {"bookmaker": "betrivers", "books_quoting": 5, "fair_probability": 0.437},
            "fair_price": 129, "ev_pct": 3.9, "model_probability": 0.51, "detail": "Our sim has it.",
            "commence_time": "2026-10-16T00:00:00Z"}


@pytest.fixture
def m(monkeypatch):
    mod = _script()
    monkeypatch.setattr(mod, "attach_images", lambda sheet, cache: {"urls": 0, "cached": 0})   # no network in tests
    monkeypatch.setattr(mod, "fill_pick_history", lambda pick, *, day, intervals: None)
    return mod


def _write(root: Path, sport: str, day: str, doc: dict) -> Path:
    path = root / "cheatsheets" / sport / f"{day}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def _ago(minutes: int) -> str:
    from datetime import datetime, timedelta, timezone

    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat(timespec="seconds")


def test_a_new_board_pick_joins_the_sheet_and_the_rows_are_left_alone(m, tmp_path):
    rows = [{"player": "A", "market": "Hits", "side": "over", "line": 0.5, "event_id": "e7"}]
    first = m.build_picks([_card("l2_old")], {"rows": rows}, sport="mlb", day="2026-10-15",
                          now=m.datetime(2026, 10, 15, 13, 0, tzinfo=m.timezone.utc))
    # l2_new was first seen a refresh ago (the hold, user 2026-10-17): still suggested now, so it joins
    path = _write(tmp_path, "mlb", "2026-10-15", {"sport": "mlb", "date": "2026-10-15", "rows": rows,
                                                    "picks": m.merge_picks(first, None), "pick_pending": {"l2_new": _ago(16)}})
    cards = [_card("l2_old", score=1.0) | {"odds": 160}, _card("l2_new", score=2.0)]   # the old pick's price moved
    totals = m.refresh_picks(tmp_path, ["mlb"], ["2026-10-15"], cards, intervals=None)
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert totals == {"sheets": 1, "new": 1, "picks": 2}
    assert {p["pick_id"] for p in doc["picks"]} == {"l2_old", "l2_new"}
    assert next(p for p in doc["picks"] if p["pick_id"] == "l2_old")["price"] == 138      # first price kept
    assert doc["rows"] == rows and doc["picks_refreshed_at"] and doc["pick_pending"] == {}


def test_nothing_new_and_nothing_left_the_board_leaves_the_file_untouched(m, tmp_path):
    picks = m.merge_picks(m.build_picks([_card("l2_a")], {"rows": []}, sport="mlb", day="2026-10-15",
                                        now=m.datetime(2026, 10, 15, 13, 0, tzinfo=m.timezone.utc)), None)
    path = _write(tmp_path, "mlb", "2026-10-15", {"sport": "mlb", "date": "2026-10-15", "rows": [], "picks": picks})
    before = path.read_bytes()
    totals = m.refresh_picks(tmp_path, ["mlb"], ["2026-10-15"], [_card("l2_a")], intervals=None)
    assert totals["sheets"] == 0 and path.read_bytes() == before


def test_a_pick_the_board_dropped_stays_and_says_so(m, tmp_path):
    picks = m.merge_picks(m.build_picks([_card("l2_a")], {"rows": []}, sport="mlb", day="2026-10-15",
                                        now=m.datetime(2026, 10, 15, 13, 0, tzinfo=m.timezone.utc)), None)
    path = _write(tmp_path, "mlb", "2026-10-15", {"sport": "mlb", "date": "2026-10-15", "rows": [], "picks": picks})
    m.refresh_picks(tmp_path, ["mlb"], ["2026-10-15"], [_card("l2_a", suggested=False)], intervals=None)
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert [p["pick_id"] for p in doc["picks"]] == ["l2_a"] and doc["picks"][0]["on_board"] is False


def test_a_day_with_no_sheet_yet_gets_a_picks_only_sheet(m, tmp_path):
    totals = m.refresh_picks(tmp_path, ["mlb", "nhl"], ["2026-10-15"], [_card("l2_a")], intervals=None)
    path = tmp_path / "cheatsheets" / "mlb" / "2026-10-15.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert totals["new"] == 0 and doc["picks_only"] is True and doc["picks"] == [] and "l2_a" in doc["pick_pending"]
    assert not (tmp_path / "cheatsheets" / "nhl" / "2026-10-15.json").exists()      # no pick, no sheet
    doc["pick_pending"]["l2_a"] = _ago(16)                                             # a refresh later, still suggested
    path.write_text(json.dumps(doc), encoding="utf-8")
    totals = m.refresh_picks(tmp_path, ["mlb"], ["2026-10-15"], [_card("l2_a")], intervals=None)
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert totals["new"] == 1 and [p["pick_id"] for p in doc["picks"]] == ["l2_a"]


# ------------------------------------------------------------------ hold, cap, fold (user 2026-10-17)
def test_a_first_sighting_waits_and_a_flicker_is_forgotten(m):
    now = m.datetime(2026, 10, 17, 17, 0, tzinfo=m.timezone.utc)
    hold: dict = {}
    assert m.hold_picks([{"pick_id": "a"}, {"pick_id": "b"}], {}, hold, now=now) == set()
    assert set(hold) == {"a", "b"}
    later = now + m.timedelta(minutes=15)
    assert m.hold_picks([{"pick_id": "a"}], {}, hold, now=later) == {"a"}    # b left the board: forgotten
    assert hold == {}
    hold = {"c": now.isoformat()}
    assert m.hold_picks([{"pick_id": "c"}], {}, hold, now=now + m.timedelta(minutes=4)) == set()   # too soon


def test_the_day_is_capped_best_board_score_first(m):
    now = m.datetime(2026, 10, 17, 17, 0, tzinfo=m.timezone.utc)
    kept = {f"k{i}": {} for i in range(m.PICK_DAILY_CAP - 1)}
    hold = {pid: (now - m.timedelta(minutes=20)).isoformat() for pid in ("x", "y", "z")}
    assert m.hold_picks([{"pick_id": "y"}, {"pick_id": "x"}, {"pick_id": "z"}], kept, hold, now=now) == {"y"}
    assert set(hold) == {"x", "z"}                                            # still waiting for room


def test_a_dropped_pick_is_stamped_and_the_stamp_clears_when_the_board_backs_it_again(m):
    picks = m.merge_picks(m.build_picks([_card("l2_a")], {"rows": []}, sport="mlb", day="2026-10-15",
                                        now=m.datetime(2026, 10, 15, 13, 0, tzinfo=m.timezone.utc)), None)
    off = m.merge_picks([], {"picks": picks}, now=m.datetime(2026, 10, 15, 14, 0, tzinfo=m.timezone.utc))
    assert off[0]["on_board"] is False and off[0]["dropped_at"].startswith("2026-10-15T14:00")
    back = m.merge_picks(m.build_picks([_card("l2_a")], {"rows": []}, sport="mlb", day="2026-10-15",
                                       now=m.datetime(2026, 10, 15, 15, 0, tzinfo=m.timezone.utc)), {"picks": off})
    assert back[0]["on_board"] is True and "dropped_at" not in back[0]


def test_the_page_folds_picks_dropped_before_their_game():
    page = (Path(__file__).resolve().parents[1] / "syndicate" / "templates" / "cheat_sheets.html").read_text(encoding="utf-8")
    assert "const droppedEarly = p =>" in page and '<details class="dropped no-export">' in page
    assert "still graded" in page


def test_the_refresh_skips_while_a_full_build_holds_the_lock(m, tmp_path, monkeypatch):
    held = m.acquire_build_lock(tmp_path, holder="full-build today")
    assert held is not None
    called = []
    monkeypatch.setattr(m, "fetch_board_cards", lambda base: called.append(base) or [])
    args = m.argparse.Namespace(base_url="http://x", date=None, sports="mlb")
    assert m.main_picks_only(args, tmp_path) == 0 and called == []         # skipped before touching the board
    m.release_build_lock(held)
    assert m.main_picks_only(args, tmp_path) == 0 and called == ["http://x"]
    assert not (tmp_path / "cheatsheets" / ".build.lock").exists()          # released after its run


def test_a_stale_lock_from_a_crashed_run_is_taken_over(m, tmp_path):
    lock = tmp_path / "cheatsheets" / ".build.lock"
    lock.parent.mkdir(parents=True)
    lock.write_text("{}", encoding="utf-8")
    old = time.time() - m.BUILD_LOCK_STALE_SECONDS - 60
    os.utime(lock, (old, old))
    assert m.acquire_build_lock(tmp_path, holder="picks-refresh") == lock
    assert json.loads(lock.read_text(encoding="utf-8"))["holder"] == "picks-refresh"


def test_the_refresh_puts_alt_prices_on_the_ladder_when_they_land_after_the_full_build(m, tmp_path):
    # Alt ladders are fetched 20-90 min before a game -- after the day's last full build for evening games -- so the
    # 15-minute refresh recomputes the ladder and rewrites the sheet when a new capture adds prices.
    row = {"player": "Nazem Kadri", "market": "SOG", "side": "over", "line": 2.5, "event_id": "e7",
           "check": {"form10": {"values": [2, 3, 3, 2, 4, 4, 2, 2, 2, 0]}, "p_market": 0.52},
           "shop": {"median_implied": 0.546}}
    path = _write(tmp_path, "nhl", "2026-10-15", {"sport": "nhl", "date": "2026-10-15", "rows": [row], "picks": []})
    m.refresh_picks(tmp_path, ["nhl"], ["2026-10-15"], [], intervals=None)
    first = json.loads(path.read_text(encoding="utf-8"))
    assert first["ladders"][0]["alt_captured"] is False
    alt = tmp_path / "nhl_source" / "tracking" / "alt_ladders" / "2026-10-15.jsonl"
    alt.parent.mkdir(parents=True)
    alt.write_text(json.dumps({"player": "Nazem Kadri", "base_market": "player_shots_on_goal", "side": "over",
                               "line": 3.5, "bookmaker": "draftkings", "price": 200}) + "\n", encoding="utf-8")
    totals = m.refresh_picks(tmp_path, ["nhl"], ["2026-10-15"], [], intervals=None)
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert totals["sheets"] == 1 and doc["ladders"][0]["alt_captured"] is True
    assert any(c.get("best_price") == 200 for c in doc["ladders"][0]["rungs"])
