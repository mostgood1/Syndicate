"""The form sections print their own official record (todo #862, user 2026-11-28 "Yes, add it").

Consistency and Hot streaks returned about the price minus the vig since 11-13 (findings_2026-11-27 section 8). Their
headers now say so in numbers: the record since launch and the last 14 days, stamped by the build from `record.json`
(`section_records`) and printed by the page. Display only: no section's members change. The build is driven through
`main`, so a stamp that never reaches a sheet fails here.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from syndicate.features.shared import cheat_sheets as cs

REPO = Path(__file__).resolve().parents[1]


def _day(date, sport="nba", beta=False, **sections):
    return {"date": date, "sport": sport, "beta": beta, "sections": sections}


def _t(w, l, units):
    return {"w": w, "l": l, "n": w + l, "units": units}


def _record():
    return {"generated_at": "2026-11-28T05:01:04+00:00",
            "official": {"by_sport": {
                "nba": {"consistency": {"w": 448, "l": 429, "n": 877, "units": -25.87, "roi_pct": -2.9},
                        "hot_streaks": {"w": 392, "l": 357, "n": 749, "units": -8.25, "roi_pct": -1.1},
                        "sim_edge": {"w": 169, "l": 171, "n": 340, "units": -24.91, "roi_pct": -7.3}},
                "nhl": {"consistency": {"w": 0, "l": 0, "n": 0, "units": 0.0}}}},
            "days": [_day("2026-10-15", consistency=_t(10, 5, 4.0), hot_streaks=_t(4, 4, -0.4)),
                     _day("2026-11-13", consistency=_t(1, 1, -0.1)),                  # one day before the window
                     _day("2026-11-14", consistency=_t(3, 7, -4.5)),                  # the window's first day
                     _day("2026-11-20", beta=True, consistency=_t(9, 0, 8.0)),       # beta: not official
                     _day("2026-11-26", sport="nhl", consistency=_t(9, 0, 8.0)),     # another sport
                     _day("2026-11-27", consistency=_t(6, 4, 1.5))]}


def test_the_record_since_launch_and_the_last_14_days():
    got = cs.section_since_launch(_record(), "NBA", "consistency")
    assert {k: got[k] for k in ("n", "w", "l", "units", "roi_pct", "from", "through")} == {
        "n": 877, "w": 448, "l": 429, "units": -25.87, "roi_pct": -2.9, "from": "2026-10-15", "through": "2026-11-27"}
    # 11-14..11-27 inclusive: 3-7 and 6-4; 11-13, the beta day and the NHL day are out
    assert got["recent"] == {"n": 20, "w": 9, "l": 11, "units": -3.0, "roi_pct": -15.0, "days": 14,
                             "from": "2026-11-14", "through": "2026-11-27"}
    hot = cs.section_since_launch(_record(), "nba", "hot_streaks")
    assert hot["through"] == "2026-10-15" and hot["recent"]["n"] == 8          # its last day ends its own window
    assert cs.section_since_launch(_record(), "nhl", "consistency") is None     # no graded bet
    assert cs.section_since_launch(_record(), "nfl", "consistency") is None
    assert cs.section_since_launch(None, "nba", "consistency") is None
    assert cs.section_since_launch(_record(), "nba", "consistency", recent_days=None).get("recent") is None


def test_sim_vs_the_line_keeps_its_shape():
    got = cs.sim_edge_since_launch(_record(), "nba")
    assert "recent" not in got and got["n"] == 340 and got["from"] == cs.SIM_EDGE_LAUNCH   # no sim_edge day in the record


def test_the_text_says_both_numbers_and_never_hides_a_loss():
    got = cs.section_since_launch(_record(), "nba", "consistency")
    assert cs.section_record_text(got) == (
        "Its official record, Oct 15 - Nov 27: 877 bets (448-429), ROI -2.9% at the best price -- it has not beaten "
        "the price. The last 14 days (Nov 14 - Nov 27): 20 bets (9-11), ROI -15.0%. Under 30 bets a record is a "
        "reading, not a trend.")                                                    # the 14 days hold 20 bets
    win = cs.section_record_text(dict(got, roi_pct=2.0, recent=None))
    assert win == "Its official record, Oct 15 - Nov 27: 877 bets (448-429), ROI +2.0% at the best price."
    one = cs.section_record_text({"n": 1, "w": 0, "l": 1, "roi_pct": -100.0, "from": "2026-11-21", "through": "2026-11-21"})
    assert one == ("Its official record, Nov 21: 1 bet (0-1), ROI -100.0% at the best price -- it has not beaten the "
                   "price. Under 30 bets a record is a reading, not a trend.")
    assert cs.section_record_text(None) == cs.section_record_text({"n": 0, "roi_pct": 0.0}) == ""


def _row(player, side="over", form10=(10, 9), **extra):
    return {"player": player, "market": "player_points", "side": side, "line": 20.5, "books_quoting": 5, "event_id": "e",
            "check": {"verdict": "streak_with_room", "ev_market": 0.0, "price": -110,
                      "form5": {"games": 5, "hits": 5, "rate": 1.0},
                      "form10": {"games": form10[0], "hits": form10[1], "rate": form10[1] / form10[0]}}} | extra


def test_the_page_prints_the_records_only_when_the_build_stamped_them():
    rec = _record()
    records = {k: cs.section_since_launch(rec, "nba", k) for k in cs.FORM_RECORD_SECTIONS}
    rows = [_row("Hot")]
    base = {"sport": "nba", "date": "2026-11-28", "rows": rows, "games": [], "section_rules": 5}
    on = cs.page_payload([dict(base, section_records=dict(records, value={"n": 5, "roi_pct": 1.0}))])["nba"]
    off = cs.page_payload([base])["nba"]
    assert set(on["section_records_text"]) == {"consistency", "hot_streaks"}        # an unknown key is ignored
    assert on["section_records_text"]["consistency"].startswith("Its official record, Oct 15 - Nov 27: 877 bets")
    assert off["section_records_text"] == {}
    # display only: the same members either way
    assert on["sections"] == off["sections"] and on["sections"]["consistency"] == [0] == on["sections"]["hot_streaks"]
    page = (REPO / "syndicate" / "templates" / "cheat_sheets.html").read_text(encoding="utf-8")
    assert 'RECORD("consistency")' in page and 'blurb += RECORD("hot_streaks")' in page
    assert "d.section_records_text" in page


def _script():
    spec = importlib.util.spec_from_file_location("build_cheat_sheets", REPO / "scripts" / "build_cheat_sheets.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _unset_data_root_until_teardown(monkeypatch):
    # `align_data_root` (reached through `main`) WRITES the variable; see test_build_cheat_sheets (todo #697).
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", "set-by-test")
    monkeypatch.delenv("SYNDICATE_DATA_ROOT")


@pytest.mark.parametrize("prior_start,stamped", [(None, True), ("2026-11-27T20:00:00Z", False)])
def test_the_build_stamps_the_form_records_on_a_v5_day(monkeypatch, tmp_path, prior_start, stamped):
    # Reachability (off != on through `main`): a fresh day gets the stamp; a started v4 day does not.
    _unset_data_root_until_teardown(monkeypatch)
    m = _script()
    from datetime import datetime as real_dt, timezone
    import syndicate.features.shared.interval_history as ih
    import syndicate.features.shared.layer2_row_context as rc

    class Fixed(real_dt):
        @classmethod
        def now(cls, tz=None):
            return real_dt(2026, 11, 27, 21, 0, tzinfo=timezone.utc)

    monkeypatch.setattr(m, "datetime", Fixed)
    monkeypatch.setattr(m, "central_today", lambda: "2026-11-27")
    monkeypatch.setattr(m, "latest_nfl_dvp", lambda root: {})
    monkeypatch.setattr(m, "_position_indexes", lambda: {})
    monkeypatch.setattr(m, "fetch_board_cards", lambda base: [])
    monkeypatch.setattr(ih.IntervalHistory, "warm", lambda self, sport, day: 0)
    monkeypatch.setattr(rc, "load_layer2_row_context", lambda day: {})
    real_steady = m.steady_rows
    monkeypatch.setattr(m, "steady_rows", lambda *a, **k: real_steady(*a, **dict(k, sleep=lambda s: None)))
    rows = [{"kind": "prop", "game_state": "pregame", "segment": "full", "event_id": "e1", "player_name": f"P{i}",
             "market": "Receptions", "commence_time": "2026-11-28T00:15:00Z"} for i in range(2)]
    monkeypatch.setattr(m, "fetch_rows", lambda base, sport, day=None: list(rows))
    sheets = tmp_path / "cheatsheets"
    (sheets / "nfl").mkdir(parents=True)
    rec = {"generated_at": "2026-11-27T12:55:37+00:00",
           "official": {"by_sport": {"nfl": {"consistency": {"w": 60, "l": 70, "n": 130, "units": -18.2, "roi_pct": -14.0},
                                             "hot_streaks": {"w": 50, "l": 52, "n": 102, "units": -7.0, "roi_pct": -6.9}}}},
           "days": [_day("2026-11-23", sport="nfl", consistency=_t(8, 12, -5.1), hot_streaks=_t(7, 9, -2.8))]}
    (sheets / "record.json").write_text(json.dumps(rec), encoding="utf-8")
    target = sheets / "nfl" / "2026-11-27.json"
    if prior_start:
        target.write_text(json.dumps({"date": "2026-11-27", "generated_at": "2026-11-27T17:30:00Z", "section_rules": 4,
                                      "games": [], "sections": {}, "section_records": {"consistency": {"n": 1}},
                                      "rows": [{"event_id": "e0", "player": "Q", "market": "Receptions", "line": 4.5,
                                                "side": "over", "commence_time": prior_start}]}), encoding="utf-8")
    m.main(["--data-root", str(tmp_path), "--date", "2026-11-27", "--sports", "nfl", "--base-url", "http://127.0.0.1:9"])
    sheet = json.loads(target.read_text(encoding="utf-8"))
    if stamped:
        got = sheet["section_records"]
        assert set(got) == {"consistency", "hot_streaks"}
        assert got["consistency"]["n"] == 130 and got["consistency"]["recent"]["n"] == 20
        assert got["hot_streaks"]["roi_pct"] == -6.9
    else:
        assert sheet["section_rules"] == 4 and "section_records" not in sheet
