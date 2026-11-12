"""#792: the college in-play odds lane keeps pulling a game still live at midnight Central.

Measured 11-12 (USC @ CAL, tip 04:00Z): the #774 re-sim kept the game past the roll, but the lane asked only "is a
game live on TODAY's slate?", so its last pull was 05:58:49Z, the game's sportsbook quotes froze at 05:58Z, and the
carryover board's join priced 0 of its rows (every one refused for quote age). These tests drive
`launch_autorun_ncaab_live_refresh` through the real `prior_slate_in_play` and the re-sim's real window switch.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
UTC = dt.timezone.utc
# 00:05 CST Thu 11-12: five minutes after the roll, inside the re-sim's default 4 h window.
NOW = dt.datetime(2026, 11, 12, 6, 5, tzinfo=UTC)
TODAY, PRIOR = "2026-11-12", "2026-11-11"
WINDOW_ENV = "SYNDICATE_COLLEGE_LIVE_RESIM_PRIOR_DATE_HOURS"


@pytest.fixture(autouse=True)
def _quiet_side_threads(monkeypatch):
    monkeypatch.setenv("SYNDICATE_COLLEGE_MOMENTUM_CAPTURE", "0")
    monkeypatch.setenv("SYNDICATE_COLLEGE_PREGAME_SIM", "0")
    monkeypatch.delenv(WINDOW_ENV, raising=False)
    monkeypatch.delenv("SYNDICATE_ENABLE_NCAAB_LIVE_REFRESH_AUTORUN", raising=False)
    monkeypatch.delenv("SYNDICATE_ENABLE_WNCAAB_LIVE_REFRESH_AUTORUN", raising=False)


def _resim(*, date=TODAY, generated=NOW - dt.timedelta(seconds=60), games=None):
    return {"sport": "ncaab", "date": date, "generatedAt": generated.isoformat(timespec="seconds"),
            "games": list(games or [])}


def _row(event_id, state="In Progress", slate_date=None):
    row = {"event_id": event_id, "home": "California Golden Bears", "away": "USC Trojans",
           "status": {"detailedState": state}, "gameLens": []}
    if slate_date:
        row["slateDate"] = slate_date
    return row


@pytest.fixture
def lane(tmp_path, monkeypatch):
    """The lane with its store, slate count and launcher faked; the re-sim window and file read are real code."""
    from syndicate.features.ncaab import inplay_lane

    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    store: dict[str, dict] = {}
    launches: list[dict] = []
    live_today = {"n": 0}
    monkeypatch.setattr(inplay_lane, "read_json_file", lambda path: store.get(str(path)))
    monkeypatch.setattr(inplay_lane, "write_json_file", lambda path, payload: store.__setitem__(str(path), payload))
    monkeypatch.setattr(inplay_lane, "central_today_iso", lambda: TODAY)
    monkeypatch.setattr(inplay_lane, "ncaab_live_game_count",
                        lambda d, league="ncaab": live_today["n"] if d == TODAY else 99)  # 99: never asked
    monkeypatch.setattr(inplay_lane, "launch_refresh_run", lambda **kw: launches.append(kw) or {"runStamp": "r1"})

    class Lane:
        module = inplay_lane

        def publish(self, snapshot, league="ncaab"):
            from syndicate.features.ncaab.live_resim import live_lens_snapshot_path

            store[str(live_lens_snapshot_path(league))] = snapshot

        def tick(self, league="ncaab", now=NOW):
            return inplay_lane.launch_autorun_ncaab_live_refresh(league, now=now)

    Lane.store, Lane.launches, Lane.live_today = store, launches, live_today
    return Lane()


# ------------------------------------------------------------------------------------------- prior_slate_in_play

def test_prior_slate_in_play_names_only_the_previous_dates_in_progress_rows(lane):
    lane.publish(_resim(games=[_row("401", slate_date=PRIOR), _row("402", "Unknown", slate_date=PRIOR),
                               _row("500")]))  # 500 is today's row
    assert lane.module.prior_slate_in_play("ncaab", NOW) == (PRIOR, ["401"])


def test_a_central_offset_generated_at_is_read_as_the_same_instant(lane):
    # The fleet's file reads e.g. "2026-11-12T08:56:01-06:00" (read 14:56Z 11-12): an offset, not "Z".
    central = dt.timezone(dt.timedelta(hours=-6))
    snap = _resim(games=[_row("401", slate_date=PRIOR)])
    snap["generatedAt"] = (NOW - dt.timedelta(seconds=60)).astimezone(central).isoformat(timespec="seconds")
    lane.publish(snap)
    assert lane.module.prior_slate_in_play("ncaab", NOW) == (PRIOR, ["401"])
    snap["generatedAt"] = (NOW - dt.timedelta(seconds=700)).astimezone(central).isoformat(timespec="seconds")
    lane.publish(snap)
    assert lane.module.prior_slate_in_play("ncaab", NOW) == (PRIOR, [])


def test_the_first_tick_after_the_roll_reads_the_pre_midnight_snapshot_as_the_previous_date(lane):
    # The re-sim has not ticked since 23:59: its file is still the 11-11 snapshot, rows without slateDate.
    lane.publish(_resim(date=PRIOR, generated=dt.datetime(2026, 11, 12, 5, 59, tzinfo=UTC), games=[_row("401")]))
    assert lane.module.prior_slate_in_play("ncaab", NOW) == (PRIOR, ["401"])


@pytest.mark.parametrize("snapshot", [
    None,
    _resim(generated=NOW - dt.timedelta(seconds=601), games=[_row("401", slate_date=PRIOR)]),   # stopped re-sim
    {**_resim(games=[_row("401", slate_date=PRIOR)]), "generatedAt": "2026-11-12T06:04:00"},     # no timezone
    {**_resim(games=[_row("401", slate_date=PRIOR)]), "generatedAt": "not a time"},
    _resim(games=[_row("500")]),                                                                 # today's only
])
def test_a_missing_stale_or_unparseable_resim_file_names_no_game(lane, snapshot):
    if snapshot is not None:
        lane.publish(snapshot)
    assert lane.module.prior_slate_in_play("ncaab", NOW) == (PRIOR, [])


def test_outside_the_resim_window_there_is_no_previous_date(lane):
    late =dt.datetime(2026, 11, 12, 10, 5, tzinfo=UTC)  # 04:05 CST, past the default 4 h
    lane.publish(_resim(generated=late - dt.timedelta(seconds=30), games=[_row("401", slate_date=PRIOR)]))
    assert lane.module.prior_slate_in_play("ncaab", late) == (None, [])


# ------------------------------------------------------------------------------------------------- the launcher

def test_after_the_roll_the_lane_pulls_the_previous_date_while_its_game_is_in_progress(lane, capsys):
    lane.publish(_resim(games=[_row("401", slate_date=PRIOR)]))
    out = lane.tick()
    assert out == {"date": PRIOR, "live_games": 1, "runStamp": "r1", "prior_slate_games": ["401"]}
    (kw,) = lane.launches
    # The same forced in-play run it had at 23:59, for THAT date (the shard the carryover board reads).
    assert kw["date"] == PRIOR and kw["sports"] == "ncaab" and kw["phase"] == "live"
    assert kw["force_refresh"] is True and kw["force_refresh_sports"] == "ncaab"
    assert kw["lane"] == "live-odds-worker-ncaab-live"
    log = capsys.readouterr().out
    assert f"NCAAB_LIVE_AUTORUN_LAUNCHED date={PRIOR} " in log and "prior_slate_games=1" in log


def test_off_is_not_on_through_the_resim_window_switch(lane, monkeypatch):
    lane.publish(_resim(games=[_row("401", slate_date=PRIOR)]))
    monkeypatch.setenv(WINDOW_ENV, "0")
    assert lane.tick() is None and lane.launches == []
    monkeypatch.setenv(WINDOW_ENV, "4")
    assert lane.tick()["date"] == PRIOR and len(lane.launches) == 1


def test_the_window_length_is_the_resims_own(lane, monkeypatch):
    at_0230 = dt.datetime(2026, 11, 12, 8, 30, tzinfo=UTC)
    lane.publish(_resim(generated=at_0230 - dt.timedelta(seconds=30), games=[_row("401", slate_date=PRIOR)]))
    monkeypatch.setenv(WINDOW_ENV, "2")
    assert lane.tick(now=at_0230) is None and lane.launches == []
    monkeypatch.delenv(WINDOW_ENV)
    assert lane.tick(now=at_0230)["date"] == PRIOR


@pytest.mark.parametrize("games", [[], [_row("402", "Unknown", slate_date=PRIOR)], [_row("500")]])
def test_no_previous_date_game_in_progress_means_no_pull(lane, games):
    lane.publish(_resim(games=games))
    assert lane.tick() is None and lane.launches == []


def test_a_stopped_resim_stops_the_paid_pulls(lane):
    lane.publish(_resim(generated=NOW - dt.timedelta(minutes=11), games=[_row("401", slate_date=PRIOR)]))
    assert lane.tick() is None and lane.launches == []


def test_todays_live_game_still_wins(lane):
    lane.publish(_resim(games=[_row("401", slate_date=PRIOR)]))
    lane.live_today["n"] = 2
    out = lane.tick()
    assert out == {"date": TODAY, "live_games": 2, "runStamp": "r1"}
    assert lane.launches[0]["date"] == TODAY


def test_the_cadence_carries_across_the_roll(lane):
    import time

    from syndicate.features.ncaab.inplay_lane import _status_path

    lane.publish(_resim(games=[_row("401", slate_date=PRIOR)]))
    lane.store[str(_status_path("ncaab"))] = {"epoch": time.time() - 30, "date": PRIOR, "reported": True}
    assert lane.tick() is None and lane.launches == []   # 23:59's pull was 30 s ago: wait out the 240 s


def test_the_lane_switch_still_turns_it_off(lane, monkeypatch):
    lane.publish(_resim(games=[_row("401", slate_date=PRIOR)]))
    monkeypatch.setenv("SYNDICATE_ENABLE_NCAAB_LIVE_REFRESH_AUTORUN", "0")
    assert lane.tick() is None and lane.launches == []


def test_womens_college_basketball_reads_its_own_resim_file(lane, capsys):
    lane.publish(_resim(games=[_row("401", slate_date=PRIOR)]), league="ncaab")
    assert lane.tick("wncaab") is None and lane.launches == []        # the men's file says nothing about women's
    lane.publish({**_resim(games=[_row("w9", slate_date=PRIOR)]), "sport": "wncaab"}, league="wncaab")
    out = lane.tick("wncaab")
    assert out["date"] == PRIOR and out["prior_slate_games"] == ["w9"]
    kw = lane.launches[0]
    assert kw["sports"] == "wncaab" and kw["force_refresh_sports"] == "wncaab"
    assert kw["lane"] == "live-odds-worker-wncaab-live"
    assert f"WNCAAB_LIVE_AUTORUN_LAUNCHED date={PRIOR} " in capsys.readouterr().out


def test_a_broken_prior_check_costs_nothing_but_its_own_pull(lane, monkeypatch, capsys):
    def boom(league="ncaab", now=None):
        raise RuntimeError("keyvalue down")

    monkeypatch.setattr(lane.module, "prior_slate_in_play", boom)
    assert lane.tick() is None and lane.launches == []
    assert "NCAAB_LIVE_AUTORUN_PRIOR_SLATE_ERROR RuntimeError: keyvalue down" in capsys.readouterr().out
    lane.live_today["n"] = 1                                                  # today's pulls are untouched
    assert lane.tick()["date"] == TODAY


# --------------------------------------------------------------------- where the pull files its quotes

def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_the_in_play_pull_for_the_previous_date_files_under_that_dates_shard(tmp_path, monkeypatch):
    """The carryover board reads the previous date's shard; the pull launched with date=<prior> must land there."""
    from syndicate.features.shared.odds_book_quotes import book_quotes_path

    module = _load("ncaab_odds_inplay_midnight", "scripts/refresh_ncaab_odds_history.py")
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path / "data_root"))
    tipped = dt.datetime.now(UTC) - dt.timedelta(minutes=125)   # a 04:00Z tip read at ~06:05Z

    class _Client:
        def __init__(self, region="us", api_key=None):
            self.sport_key = "basketball_ncaab"

        def iter_current_odds_expanded(self, *, markets, date_iso, bookmakers=None):
            return [{"event_id": "uscal", "commence_time": tipped, "period": "full_game", "market": "h2h",
                     "book": "draftkings", "home_team_name": "California Golden Bears",
                     "away_team_name": "USC Trojans",
                     "moneyline_home": -150, "moneyline_away": 130, "last_update": dt.datetime.now(UTC).isoformat()}]

        def iter_event_odds(self, event_id, *, markets, bookmakers=None, fallback_full_game=True):
            return []

    monkeypatch.setattr(module, "_load_source_adapter", lambda root: _Client)
    monkeypatch.setattr("sys.argv", ["x", "--date", PRIOR, "--out-dir", str(tmp_path / "out"), "--in-play-only"])
    assert module.main() == 0
    prior_shard = book_quotes_path("ncaab", PRIOR)
    assert prior_shard.exists(), "the previous date's pull must file under the previous date's shard"
    rows = [json.loads(line) for line in prior_shard.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert {r.get("event_id") for r in rows} == {"uscal"}
    assert not book_quotes_path("ncaab", TODAY).exists()
