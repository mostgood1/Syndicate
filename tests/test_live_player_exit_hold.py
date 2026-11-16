"""In-play ENTRY holds on a key player's exit (lane live-player-exit-gate, user loan from in-game-trading 2026-11-15).

The producer side is the REAL NFL re-sim snapshot built from the NE @ DET halftime payload of 2026-11-15
(Drake Maye hurt 14:41:43Z); the entry side uses the OddsAPI team names an entry actually carries.
"""

from __future__ import annotations

import copy
import gzip
import json
from pathlib import Path

import pytest

from syndicate.features.nfl import live_player_box
from syndicate.features.nfl import live_resim as R
from syndicate.features.shared import inplay_entries_live as live
from syndicate.features.shared import inplay_entries_paper as ip
from syndicate.features.shared import live_player_exit_hold as H
from syndicate.features.shared import live_player_status as lps

FIX = Path(__file__).parent / "fixtures" / "live_player_status" / "nfl_401873053_halftime_2026-11-15.json.gz"
LIVE_ROW = {"state": "in", "event_id": "401873053", "period": 3, "clock_seconds": 600, "home_score": 21,
            "away_score": 3, "possession_owner": "home", "down": 2, "distance": 7, "field_position": 41}
NE, DET = "New England Patriots", "Detroit Lions"  # OddsAPI names, as an in-play entry carries them


@pytest.fixture
def summary():
    with gzip.open(FIX, "rt", encoding="utf-8") as fh:
        return json.load(fh)


def _clean(summary):
    s = copy.deepcopy(summary)
    s["injuries"] = []
    for drive in s["drives"]["previous"]:
        for play in drive["plays"]:
            play["text"] = play["text"].split(" was injured during the play")[0]
    return s


def _producer_snapshot(monkeypatch, payload):
    monkeypatch.setattr(R, "_attach_live_player_stats", lambda targets, **kw: {"stubbed": True})
    monkeypatch.setattr(live_player_box, "_fetch_summary", lambda event_id: payload)
    return R.build_live_lens_snapshot("2026-11-15", games=[{"away_team": "NE", "home_team": "DET", "live_key": "g1"}],
                                      live_index={"g1": LIVE_ROW}, ratings={"DET": (27.0, 19.0), "NE": (20.0, 24.0)},
                                      sims=20, env={})


def _hold(snap, env=None):
    reads: list = []
    return H.ExitHold(read_fn=lambda sport: reads.append(sport) or snap, env=env or {}), reads


def test_the_map_is_the_one_the_moneyline_join_reads():
    from syndicate.features.shared.board_enrichment import _LIVE_GAMELINE_SNAPSHOT_PATHS

    for sport, name in H.PUBLISHING_SPORTS.items():
        assert _LIVE_GAMELINE_SNAPSHOT_PATHS.get(sport, f"{sport}_live_lens.json") == name


def test_real_producer_snapshot_holds_the_maye_game_by_oddsapi_names(monkeypatch, summary):
    hold, _ = _hold(_producer_snapshot(monkeypatch, summary))
    out = hold.check("nfl", DET, NE)
    assert out["verdict"] == "fail" and out["reason"] == "key_player_out"
    assert out["players"] == ["NE:Drake Maye:injured_in_play"]  # the non-key exits are props-only
    assert hold.check("nfl", NE, DET)["verdict"] == "fail"  # home/away order does not matter


def test_off_ne_on_and_the_clean_game_passes(monkeypatch, summary):
    snap = _producer_snapshot(monkeypatch, summary)
    on, _ = _hold(snap)
    off, off_reads = _hold(snap, env={lps.ENV_SWITCH: "off"})
    assert on.check("nfl", DET, NE)["verdict"] == "fail"
    assert off.check("nfl", DET, NE) == {"verdict": "off"} and off_reads == []  # off costs no read
    monkeypatch.setattr(lps, "REPLACED_AFTER_SNAPS", 10**6)  # the backup's snaps would give Maye away too
    clean, _ = _hold(_producer_snapshot(monkeypatch, _clean(summary)))
    assert clean.check("nfl", DET, NE)["verdict"] == "pass"


def test_unknowns_are_counted_never_refused(monkeypatch, summary):
    snap = _producer_snapshot(monkeypatch, summary)
    assert _hold(None)[0].check("nfl", DET, NE) == {"verdict": "unknown", "why": "snapshot_unreadable"}
    assert _hold(snap)[0].check("nfl", "Buffalo Bills", "New York Jets")["why"] == "game_not_in_snapshot"
    assert _hold(snap)[0].check("nfl", None, NE)["why"] == "entry_has_no_teams"
    unread = copy.deepcopy(snap)
    unread["games"][0].pop("playersOut")
    assert _hold(unread)[0].check("nfl", DET, NE)["why"] == "game_exits_not_read"

    def boom(sport):
        raise OSError("redis down")

    assert H.ExitHold(read_fn=boom, env={}).check("nfl", DET, NE)["verdict"] == "unknown"


def test_a_sport_that_publishes_no_exits_is_off_and_reads_nothing():
    hold, reads = _hold({"games": []})
    for sport in ("nhl", "mlb", "soccer", "ncaab"):
        assert hold.check(sport, "A", "B") == {"verdict": "off"}
    assert reads == []


def test_one_read_per_cache_window():
    t = {"now": 0.0}
    reads: list = []
    hold = H.ExitHold(read_fn=lambda s: reads.append(s) or {"games": []}, clock=lambda: t["now"], env={})
    hold.check("nfl", DET, NE)
    hold.check("nfl", DET, NE)
    t["now"] = H.CACHE_S + 1
    hold.check("nfl", DET, NE)
    assert reads == ["nfl", "nfl"]


class _FixedHold:
    def __init__(self, verdict):
        self.verdict, self.calls = verdict, []

    def check(self, sport, home, away):
        self.calls.append((sport, home, away))
        return self.verdict


FAIL = {"verdict": "fail", "reason": "key_player_out", "players": ["NE:Drake Maye:injured_in_play"]}
ENTRY = {"key": "2026-11-15:KXNFLGAME-26NOV15NEDET-DET:yes", "ticker": "KXNFLGAME-26NOV15NEDET-DET", "leg": "yes",
         "ask": 0.60, "edge": 0.05, "line": None, "sport": "nfl", "kind": "h2h",
         "home_team": DET, "away_team": NE, "event_id": "oddsapi-ev"}


@pytest.fixture
def _live_env(monkeypatch, tmp_path):
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("SYNDICATE_REPORTS_ROOT", str(tmp_path))
    for k in ("SYNDICATE_LIVE_PRICE_BAND", "SYNDICATE_LIVE_CELL_GATE", "SYNDICATE_INPLAY_ENTRY_ORDER_DOLLARS"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("SYNDICATE_INPLAY_MIN_ASK", "off")


@pytest.mark.parametrize("verdict, placed", [(FAIL, False), ({"verdict": "pass"}, True), ({"verdict": "off"}, True),
                                             ({"verdict": "unknown", "why": "snapshot_unreadable"}, True)])
def test_live_placer_refuses_first_and_records_the_guard(_live_env, verdict, placed):
    calls, records = [], []
    hold = _FixedHold(verdict)
    p = live.LiveEntryPlacer(today_fn=lambda: "2026-11-15", orders_fn=lambda: [],
                             place_fn=lambda **kw: calls.append(kw) or {"placed": True},
                             enabled_fn=lambda: True, record_fn=lambda day, rec: records.append(rec), exit_hold=hold)
    out = p(ENTRY)
    assert out["placed"] is placed and bool(calls) is placed
    assert hold.calls == [("nfl", DET, NE)]
    (rec,) = records
    assert rec["guards"]["player_exit"] == verdict
    if not placed:
        assert out == {"placed": False, "reason": "key_player_out", "players": ["NE:Drake Maye:injured_in_play"]}
        assert rec["guards"]["check_order"] == {"verdict": "not_reached"}


def test_paper_loop_refuses_the_booking_so_no_live_order_is_tried():
    """Reachability through the real paper loop (the NBA moneyline harness of test_inplay_entries_paper):
    the same pass books with the hold passing and books nothing -- and never calls on_book -- with it failing."""
    T0 = 1_761_000_000.0
    tick = "KXNBAGAME-26OCT22CHIMIL-MIL"
    upd = ip._iso(T0 - 10)
    book = {"id": "nba1", "home_team": "Milwaukee Bucks", "away_team": "Chicago Bulls",
            "commence_time": ip._iso(T0 - 3600),
            "bookmakers": [{"key": f"b{i}", "markets": [{"key": "h2h", "last_update": upd, "outcomes": [
                {"name": "Milwaukee Bucks", "price": 1 / 0.62}, {"name": "Chicago Bulls", "price": 1 / 0.38}]}]}
                for i in range(4)]}

    def get(url):
        if url.startswith(ip.espn_url("nba")):
            return {"events": [{"competitions": [{"status": {"type": {"state": "in"}}, "competitors": [
                {"team": {"abbreviation": "MIL"}, "score": "50"}, {"team": {"abbreviation": "CHI"}, "score": "48"}]}]}]}
        if url.startswith(ip.oddsapi_url("nba")):
            return [book]
        return {"markets": [{"ticker": tick, "event_ticker": "KXNBAGAME-26OCT22CHIMIL", "status": "active",
                             "yes_sub_title": "Milwaukee", "yes_ask_dollars": "0.5500", "yes_bid_dollars": "0.5400",
                             "no_ask_dollars": "0.4600", "result": ""}]}

    def run(verdict):
        clock = {"t": T0}
        hooked: list = []
        hold = _FixedHold(verdict)
        loop = ip.PaperEntryLoop(today_fn=lambda: "2026-10-22", clock=lambda: clock["t"], get=get,
                                 tickers_fn=lambda d, s: [tick], load=lambda: {"entries": {}}, persist=lambda d: None,
                                 sports=("nba",), on_book=lambda e: hooked.append(e) or {"placed": False},
                                 exit_hold=hold)
        loop.step()
        clock["t"] = T0 + 20
        loop.books_t, loop.espn_t, loop.last_pass_t = {}, {}, None
        return loop.step(), loop, hooked, hold

    out, loop, hooked, hold = run({"verdict": "pass"})
    assert out["booked"] == 1 and len(hooked) == 1
    out, loop, hooked, hold = run({**FAIL})
    assert out["signals"] == 1 and out["booked"] == 0 and loop.doc["entries"] == {} and hooked == []
    assert ("nba", "Milwaukee Bucks", "Chicago Bulls") in hold.calls
