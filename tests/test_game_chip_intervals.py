"""Interval projections on basketball rail chips (`game_chip_intervals`, lane basketball-interval-projections).

User 2026-11-07: "need the game rail cards to indicate the interval projections", "we need college qtr/half
projections back". These pin: halves for men's college, quarters elsewhere; settled / in-progress / ahead from
the live lane; the anchored live margin; no college pregame win probability; no block (never a neutral one)
when the sim is absent; and that both attach paths actually reach the module (off != on).
"""
from __future__ import annotations

import pytest

import syndicate.features.shared.game_chip_intervals as gci
from syndicate.features.shared import game_chip_scoreboard as gcs


@pytest.fixture(autouse=True)
def _fresh_cache():
    gci.clear_cache()
    yield
    gci.clear_cache()


def _point(value):
    return {str(value): 10}


def _pregame_entry(segments, total, margin, win=0.64):
    return {"event_id": "401909532", "computed_at": "2026-11-07T12:00:00Z", "sims_run": 2000, "total_mean": total,
            "home_margin_mean": margin, "home_win_prob": win, "dist": {"segments": segments}}


def _chip(sport="ncaab", state="pregame", key="401909532", away=("Providence Friars", "providence", "PROV"),
          home=("Nebraska Cornhuskers", "nebraska", "NEB")):
    return {"sport": sport, "state": state, "game_key": key, "start_time_utc": "2026-11-08T00:00:00Z",
            "away": {"name": away[0], "key": away[1], "abbr": away[2]},
            "home": {"name": home[0], "key": home[1], "abbr": home[2]}}


def _patch_sources(monkeypatch, *, college=None, live=None, nba=None, wnba=None):
    monkeypatch.setattr(gci, "_college_pregame_games", lambda sport, d: (college or {}).get(sport, {}))
    monkeypatch.setattr(gci, "_live_snapshot", lambda sport: (live or {}).get(sport))
    monkeypatch.setattr(gci, "_nba_pregame", lambda d: nba)
    monkeypatch.setattr(gci, "_wnba_pregame", lambda d: wnba)


def test_hist_mean_reads_string_keys_and_refuses_garbage():
    assert gci.hist_mean({"70": 1, "72": 3}) == pytest.approx(71.5)
    assert gci.hist_mean({}) is None
    assert gci.hist_mean({"x": 1}) is None
    assert gci.hist_mean(None) is None


def test_mens_college_pregame_shows_halves_and_no_win_probability(monkeypatch):
    segs = {"full": {"total": _point(150), "margin": _point(4)},
            "h1": {"total": _point(70), "margin": _point(2)},
            "h2": {"total": _point(80), "margin": _point(2)}}
    _patch_sources(monkeypatch, college={"ncaab": {"401909532": _pregame_entry(segs, 150.0, 4.0)}})
    chip = _chip()
    gci.attach_interval_projections([chip], "2026-11-07")
    block = chip["intervals"]
    assert block["source"] == "pregame_sim"
    assert [p["label"] for p in block["periods"]] == ["1H", "2H"]
    assert block["periods"][0] == {"key": "h1", "label": "1H", "away": 34.0, "home": 36.0, "total": 70.0,
                                   "home_margin": 2.0, "state": "ahead"}
    assert block["final"] == {"away": 73.0, "home": 77.0, "total": 150.0, "home_margin": 4.0, "home_win_prob": None}
    assert block["sims"] == 2000


def test_womens_college_pregame_shows_quarters(monkeypatch):
    segs = {"full": {"total": _point(132), "margin": _point(-8)}}
    for q, (t, m) in zip(("q1", "q2", "q3", "q4"), ((33, -2), (33, -2), (33, -2), (33, -2))):
        segs[q] = {"total": _point(t), "margin": _point(m)}
    _patch_sources(monkeypatch, college={"wncaab": {"401909532": _pregame_entry(segs, 132.0, -8.0)}})
    chip = _chip(sport="wncaab")
    gci.attach_interval_projections([chip], "2026-11-07")
    periods = chip["intervals"]["periods"]
    assert [p["label"] for p in periods] == ["Q1", "Q2", "Q3", "Q4"]
    assert (periods[0]["away"], periods[0]["home"]) == (17.5, 15.5)


def _live_snapshot(event_id="401909532", period=2, segments=None, margin=10.555, total=148.62, refused=False):
    lane = {"key": "live", "source": "live_resim", "liveStateAsOf": "2026-11-07T20:03:45+00:00", "simsRun": 200,
            "modelHomeWinProb": 0.97}
    if refused:
        lane = {"key": "live", "liveResimRefusal": "no_margin_anchor"}
    else:
        lane["projection"] = {"homeMargin": margin, "total": total, "rawHomeMargin": 10.45, "period": period,
                              "segments": segments if segments is not None else {
                                  "h1": {"total_mean": 69.0, "total_dist": _point(69), "margin_dist": _point(5),
                                         "settled": True},
                                  "h2": {"total_mean": 79.62, "total_dist": _point(80), "margin_dist": _point(6),
                                         "settled": False}}}
    return {"games": [{"event_id": event_id, "away": "Providence Friars", "home": "Nebraska Cornhuskers",
                       "gameLens": [lane]}]}


def test_live_college_uses_the_lane_settled_flags_and_its_anchored_margin(monkeypatch):
    _patch_sources(monkeypatch, live={"ncaab": _live_snapshot()})
    chip = _chip(state="live")
    gci.attach_interval_projections([chip], "2026-11-07")
    block = chip["intervals"]
    assert block["source"] == "live_resim"
    assert [p["state"] for p in block["periods"]] == ["settled", "in_progress"]
    assert (block["periods"][0]["away"], block["periods"][0]["home"]) == (32.0, 37.0)   # 69 total, +5 home
    # The FINAL is the lane's anchored homeMargin (10.555), never rawHomeMargin (10.45).
    assert block["final"]["home_margin"] == 10.6
    assert block["final"]["home_win_prob"] == 0.97
    assert block["as_of"] == "2026-11-07T20:03:45+00:00"


def test_live_overtime_keeps_the_second_half_in_progress(monkeypatch):
    segs = {"h1": {"total_mean": 70, "margin_dist": _point(0), "settled": True},
            "h2": {"total_mean": 82, "margin_dist": _point(0), "settled": False}}
    _patch_sources(monkeypatch, live={"ncaab": _live_snapshot(period=3, segments=segs)})
    chip = _chip(state="live")
    gci.attach_interval_projections([chip], "2026-11-07")
    assert [p["state"] for p in chip["intervals"]["periods"]] == ["settled", "in_progress"]


def test_a_refused_live_lane_gives_no_block_and_drops_a_stale_one(monkeypatch):
    _patch_sources(monkeypatch, live={"ncaab": _live_snapshot(refused=True)})
    chip = _chip(state="live")
    chip["intervals"] = {"source": "pregame_sim", "periods": [], "final": {}}
    counts = gci.attach_interval_projections([chip], "2026-11-07")
    assert "intervals" not in chip
    assert counts.get("removed") == 1


def test_no_sim_means_no_block_never_a_neutral_one(monkeypatch):
    _patch_sources(monkeypatch)
    chips = [_chip(), _chip(state="live"), _chip(sport="nba", key="0022500001"), _chip(state="final")]
    gci.attach_interval_projections(chips, "2026-11-07")
    assert all("intervals" not in c for c in chips)


def test_other_sports_are_untouched(monkeypatch):
    _patch_sources(monkeypatch)
    chip = {"sport": "nhl", "state": "pregame", "game_key": "1"}
    gci.attach_interval_projections([chip], "2026-11-07")
    assert chip == {"sport": "nhl", "state": "pregame", "game_key": "1"}


def test_live_lane_joins_on_the_team_pair_when_the_ids_differ(monkeypatch):
    """NBA chips may carry another id than the ESPN event id the live snapshot is keyed on."""
    segs = {q: {"total_mean": 56, "margin_dist": _point(1), "settled": q == "q1"} for q in ("q1", "q2", "q3", "q4")}
    snap = {"games": [{"event_id": "401700001", "away": "Boston Celtics", "home": "New York Knicks",
                       "gameLens": [{"key": "live", "liveStateAsOf": "x", "simsRun": 400, "modelHomeWinProb": 0.55,
                                     "projection": {"homeMargin": 3.0, "total": 224.0, "period": 2, "segments": segs}}]}]}
    _patch_sources(monkeypatch, live={"nba": snap})
    chip = _chip(sport="nba", state="live", key="0022500999", away=("Boston Celtics", "boston celtics", "BOS"),
                 home=("New York Knicks", "new york knicks", "NYK"))
    gci.attach_interval_projections([chip], "2026-11-07")
    block = chip["intervals"]
    assert [p["state"] for p in block["periods"]] == ["settled", "in_progress", "ahead", "ahead"]
    assert block["final"] == {"away": 110.5, "home": 113.5, "total": 224.0, "home_margin": 3.0, "home_win_prob": 0.55}


def test_nba_pregame_reads_the_smart_sim_segments(monkeypatch):
    class Entry:
        dist = {"segments": {"full": {"total": _point(226), "margin": _point(-4)},
                             **{q: {"total": _point(56), "margin": _point(-1)} for q in ("q1", "q2", "q3", "q4")}}}
        p_home_win = 0.38
        sim_draws = 5000

    class Index:
        def lookup(self, home, away, commence=None):
            return Entry() if (home, away) == ("New York Knicks", "Boston Celtics") else None

    _patch_sources(monkeypatch, nba=Index())
    chip = _chip(sport="nba", key="0022500999", away=("Boston Celtics", "boston celtics", "BOS"),
                 home=("New York Knicks", "new york knicks", "NYK"))
    gci.attach_interval_projections([chip], "2026-11-07")
    block = chip["intervals"]
    assert block["final"] == {"away": 115.0, "home": 111.0, "total": 226.0, "home_margin": -4.0, "home_win_prob": 0.38}
    assert block["periods"][0]["away"] == 28.5 and block["sims"] == 5000


def test_live_only_leaves_pregame_chips_alone(monkeypatch):
    _patch_sources(monkeypatch, live={"ncaab": _live_snapshot()})
    pre = _chip()
    pre["intervals"] = {"source": "pregame_sim", "kept": True}
    live = _chip(state="live")
    gci.attach_interval_projections([pre, live], "2026-11-07", live_only=True)
    assert pre["intervals"] == {"source": "pregame_sim", "kept": True}
    assert live["intervals"]["source"] == "live_resim"


# ------------------------------------------------------------------------------------------- reachability

def test_the_worker_build_reaches_the_attach(monkeypatch):
    """off != on through the chip builder itself: the same empty build gains the call, with live_only False."""
    calls = []
    monkeypatch.setattr(gci, "attach_interval_projections",
                        lambda chips, d, live_only=False: calls.append((d, live_only)) or {})
    monkeypatch.setattr(gcs, "_attach_board_plays", lambda *a, **k: None)
    try:
        gcs._build_game_chips_uncached("2026-11-07", (), ("k-intervals",), 0.0)
    finally:
        with gcs._cache_lock:
            gcs._cache.pop(("k-intervals",), None)
    assert calls == [("2026-11-07", False)]


def test_the_serve_path_reaches_the_attach_for_live_chips(monkeypatch):
    calls = []
    monkeypatch.setattr(gci, "attach_interval_projections",
                        lambda chips, d, live_only=False: calls.append((d, live_only)) or {})
    gcs.attach_served_linescores([], "2026-11-07")
    assert calls == [("2026-11-07", True)]


def test_an_attach_failure_never_costs_the_scoreboard(monkeypatch, capsys):
    def boom(*a, **k):
        raise RuntimeError("no store")

    monkeypatch.setattr(gci, "attach_interval_projections", boom)
    chips = [_chip()]
    gcs._attach_intervals(chips, "2026-11-07", live_only=False)
    assert chips == [_chip()]
    assert "ATTACH_FAILED" in capsys.readouterr().out
