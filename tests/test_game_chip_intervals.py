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


def _patch_sources(monkeypatch, *, college=None, live=None, nba=None, wnba=None, soccer=None, other_live=None,
                   nhl=None, nfl=None, ncaaf=None, mlb=None):
    """Every source the module reads, stubbed: absent unless a test hands one in. No test reads a disk."""
    monkeypatch.setattr(gci, "_college_pregame_games", lambda sport, d: (college or {}).get(sport, {}))
    monkeypatch.setattr(gci, "_live_snapshot", lambda sport: (live or {}).get(sport))
    monkeypatch.setattr(gci, "_nba_pregame", lambda d: nba)
    monkeypatch.setattr(gci, "_wnba_pregame", lambda d: wnba)
    monkeypatch.setattr(gci, "_soccer_pregame_matches", lambda league, day: (soccer or {}).get((league, day)))
    monkeypatch.setattr(gci, "_other_live_snapshot", lambda sport: (other_live or {}).get(sport))
    monkeypatch.setattr(gci, "_nhl_pregame", lambda day: (nhl or {}).get(day))
    monkeypatch.setattr(gci, "_nfl_segment_blocks", lambda: nfl or {})
    monkeypatch.setattr(gci, "_ncaaf_pregame", lambda day: (ncaaf or {}).get(day))
    monkeypatch.setattr(gci, "_mlb_daily_summary", lambda day: (mlb or {}).get(day))


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


def test_a_sport_without_an_interval_source_is_untouched(monkeypatch):
    _patch_sources(monkeypatch)
    chip = {"sport": "tennis", "state": "pregame", "game_key": "1"}
    gci.attach_interval_projections([chip], "2026-11-07")
    assert chip == {"sport": "tennis", "state": "pregame", "game_key": "1"}


def test_basketball_blocks_keep_their_shape(monkeypatch):
    """Phase 3 added optional keys (`precision`, three-way probabilities); a basketball block carries none of them."""
    segs = {"full": {"total": _point(150), "margin": _point(4)},
            "h1": {"total": _point(70), "margin": _point(2)}, "h2": {"total": _point(80), "margin": _point(2)}}
    _patch_sources(monkeypatch, college={"ncaab": {"401909532": _pregame_entry(segs, 150.0, 4.0)}})
    chip = _chip()
    gci.attach_interval_projections([chip], "2026-11-07")
    assert set(chip["intervals"]) == {"source", "as_of", "sims", "periods", "final"}
    assert set(chip["intervals"]["final"]) == {"away", "home", "total", "home_margin", "home_win_prob"}


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


# ------------------------------------------------------------------------------------------- other sports (Phase 3)
#
# Lane all-sport-interval-projections. User 2026-11-07: "this worked well for basketball - once reimplemented we
# need this for all sports". Each sport shows what its engine simulates and publishes, nothing more: soccer halves,
# NFL / NCAAF quarters, MLB first-1/3/5 innings pregame; the projected final alone where the engine publishes no
# period (NHL; live soccer / NFL / NCAAF); and no block at all where it publishes nothing.

def _other_chip(sport, state="pregame", key="1", away=("Away Team", "away team", "AWY"),
                home=("Home Team", "home team", "HOM"), start="2026-11-08T00:00:00+00:00", league=None):
    chip = {"sport": sport, "state": state, "game_key": key, "start_time_utc": start,
            "away": {"name": away[0], "key": away[1], "abbr": away[2]},
            "home": {"name": home[0], "key": home[1], "abbr": home[2]}}
    if league:
        chip["league"] = league
    return chip


def _soccer_match(event_id="761942"):
    return {"event_id": event_id, "matchup": {"home_team": "Austin FC", "away_team": "Portland Timbers"},
            "win_probability": {"home": 0.4975, "draw": 0.2175, "away": 0.285},
            "team_projection": {"home_mean": 1.795, "away_mean": 1.4175, "total_mean": 3.2125, "margin_mean": 0.3775},
            "periods": {"h1": {"home_mean": 0.875, "away_mean": 0.6325}, "h2": {"home_mean": 0.92, "away_mean": 0.785}},
            "simulations": 400}


def _soccer_chip(state="pregame", key="761942"):
    return _other_chip("soccer", state=state, key=key, league="mls", away=("Portland Timbers", "portland timbers", "POR"),
                       home=("Austin FC", "austin fc", "ATX"))


def test_soccer_pregame_shows_the_simulated_halves_and_three_way_odds(monkeypatch):
    # A 6 PM Central kickoff is 00:00Z tomorrow: the artifact is filed under the Central day.
    _patch_sources(monkeypatch, soccer={("mls", "2026-11-07"): {"_generated_at": "g", "761942": _soccer_match()}})
    chip = _soccer_chip()
    gci.attach_interval_projections([chip], "2026-11-07")
    block = chip["intervals"]
    assert block["source"] == "pregame_sim" and block["sims"] == 400 and block["precision"] == 1
    assert [(p["label"], p["away"], p["home"]) for p in block["periods"]] == [("1H", 0.6, 0.9), ("2H", 0.8, 0.9)]
    assert block["final"] == {"away": 1.4, "home": 1.8, "total": 3.2, "home_margin": 0.4, "home_win_prob": 0.497,
                              "draw_prob": 0.217, "away_win_prob": 0.285}


def test_soccer_without_a_sim_artifact_gets_no_block(monkeypatch):
    """UEFA cups have no sim, and far-off matchdays none yet: no block, never an empty or filled one. A match of
    another pair on the same league-day is not this one."""
    other = dict(_soccer_match("999"), matchup={"home_team": "FC Dallas", "away_team": "Colorado Rapids"})
    _patch_sources(monkeypatch, soccer={("mls", "2026-11-07"): {"_generated_at": "g", "999": other}})
    chips = [_soccer_chip(), dict(_soccer_chip(), league="ucl")]
    gci.attach_interval_projections(chips, "2026-11-07")
    assert all("intervals" not in c for c in chips)


def test_soccer_live_shows_the_projected_final_only(monkeypatch):
    snap = {"date": "2026-11-07", "generated_at": "t", "games": [{"league": "mls", "event_id": "761942", "projection": {
        "simulations": 80, "projected_final_home_goals": 2.1, "projected_final_away_goals": 0.6,
        "home_win_probability": 0.81, "draw_probability": 0.14, "away_win_probability": 0.05}}]}
    _patch_sources(monkeypatch, other_live={"soccer": snap})
    chip = _soccer_chip(state="live")
    gci.attach_interval_projections([chip], "2026-11-07")
    block = chip["intervals"]
    assert block["source"] == "live_resim" and block["periods"] == [] and block["sims"] == 80
    assert block["final"]["away"] == 0.6 and block["final"]["home"] == 2.1 and block["final"]["draw_prob"] == 0.14


def test_a_live_snapshot_from_another_slate_is_refused_but_a_day_either_way_is_not(monkeypatch):
    """NCAAF's lens stamps `date` in UTC (2026-11-08 over the Central 11-07 slate, measured): a day off is the same
    slate; three days off is a stale snapshot."""
    lane = {"key": "live", "source": "live_resim", "simsRun": 120, "modelHomeWinProb": 0.9, "liveStateAsOf": "t",
            "projection": {"total": 58.9, "homeMargin": 18.8}}
    game = {"away_name": "Sam Houston", "home_name": "Jacksonville State", "gameLens": [lane]}
    chip = _other_chip("ncaaf", state="live", away=("Sam Houston", "sam houston", "SH"),
                       home=("Jacksonville State", "jacksonville state", "JS"), start="2026-11-07T20:00:00+00:00")
    _patch_sources(monkeypatch, other_live={"ncaaf": {"date": "2026-11-08", "games": [game]}})
    gci.attach_interval_projections([chip], "2026-11-07")
    assert chip["intervals"]["final"]["home_margin"] == 18.8
    gci.clear_cache()
    _patch_sources(monkeypatch, other_live={"ncaaf": {"date": "2026-11-04", "games": [game]}})
    gci.attach_interval_projections([chip], "2026-11-07")
    assert "intervals" not in chip


def test_ncaaf_and_nfl_live_withhold_the_win_probability_the_board_blanks(monkeypatch):
    ncaaf_lane = {"key": "live", "source": "live_resim", "simsRun": 120, "modelHomeWinProb": 0.9,
                  "projection": {"total": 58.9, "homeMargin": 18.8}}
    nfl_lane = {"source": "live_resim", "ok": True, "simsRun": 300, "modelHomeWinProb": 0.7, "as_of": "t",
                "projection": {"total": 44.0, "homeMargin": 3.5}}
    _patch_sources(monkeypatch, other_live={
        "ncaaf": {"games": [{"away_name": "Sam Houston", "home_name": "Jacksonville State", "gameLens": [ncaaf_lane]}]},
        "nfl": {"games": [{"away_name": "jacksonville jaguars", "home_name": "baltimore ravens", "away_code": "JAX",
                           "home_code": "BAL", "gameLens": [nfl_lane]}]}})
    ncaaf = _other_chip("ncaaf", state="live", away=("Sam Houston", "sam houston", "SH"),
                        home=("Jacksonville State", "jacksonville state", "JS"))
    nfl = _other_chip("nfl", state="live", key="2026_09_JAX_BAL",
                      away=("Jacksonville Jaguars", "jacksonville jaguars", "JAX"),
                      home=("Baltimore Ravens", "baltimore ravens", "BAL"))
    gci.attach_interval_projections([ncaaf, nfl], "2026-11-07")
    assert ncaaf["intervals"]["final"]["home_win_prob"] is None
    assert nfl["intervals"]["final"] == {"away": 20.2, "home": 23.8, "total": 44.0, "home_margin": 3.5,
                                         "home_win_prob": None}
    assert nfl["intervals"]["sims"] == 300 and nfl["intervals"]["as_of"] == "t"


def test_a_refused_or_failed_live_lane_gives_no_block(monkeypatch):
    refused = {"key": "live", "source": "pregame_only", "liveResimRefusal": "no_slate_features"}
    not_ok = {"source": "live_resim", "ok": False, "projection": {"total": 44.0, "homeMargin": 3.5}}
    _patch_sources(monkeypatch, other_live={
        "nhl": {"games": [{"away_name": "Rangers", "home_name": "Kraken", "gameLens": [refused]}]},
        "nfl": {"games": [{"away_name": "jacksonville jaguars", "home_name": "baltimore ravens", "gameLens": [not_ok]}]}})
    nhl = _other_chip("nhl", state="live", away=("New York Rangers", "new york rangers", "NYR"),
                      home=("Seattle Kraken", "seattle kraken", "SEA"))
    nfl = _other_chip("nfl", state="live", away=("Jacksonville Jaguars", "jacksonville jaguars", "JAX"),
                      home=("Baltimore Ravens", "baltimore ravens", "BAL"))
    gci.attach_interval_projections([nhl, nfl], "2026-11-07")
    assert "intervals" not in nhl and "intervals" not in nfl


def test_nhl_live_joins_the_nickname_feed_and_keeps_its_win_probability(monkeypatch):
    lane = {"key": "live", "source": "live_resim", "simsRun": 200, "modelHomeWinProb": 0.12, "liveStateAsOf": "t",
            "projection": {"total": 5.8, "homeMargin": -2.4, "period": 2}}
    _patch_sources(monkeypatch, other_live={"nhl": {"date": "2026-11-07", "games": [
        {"away_name": "Rangers", "home_name": "Kraken", "gameLens": [lane]}]}})
    chip = _other_chip("nhl", state="live", away=("New York Rangers", "new york rangers", "NYR"),
                       home=("Seattle Kraken", "seattle kraken", "SEA"))
    gci.attach_interval_projections([chip], "2026-11-07")
    assert chip["intervals"]["final"] == {"away": 4.1, "home": 1.7, "total": 5.8, "home_margin": -2.4,
                                          "home_win_prob": 0.12}
    assert chip["intervals"]["periods"] == [] and chip["intervals"]["precision"] == 1


def test_a_reversed_team_pair_is_not_a_live_match(monkeypatch):
    lane = {"key": "live", "source": "live_resim", "projection": {"total": 5.8, "homeMargin": -2.4}}
    _patch_sources(monkeypatch, other_live={"nhl": {"games": [
        {"away_name": "Kraken", "home_name": "Rangers", "gameLens": [lane]}]}})
    chip = _other_chip("nhl", state="live", away=("New York Rangers", "new york rangers", "NYR"),
                       home=("Seattle Kraken", "seattle kraken", "SEA"))
    gci.attach_interval_projections([chip], "2026-11-07")
    assert "intervals" not in chip


class _NhlIndex:
    def __init__(self, entry):
        self.by_pair = {("x", "y"): entry}
        self._entry = entry

    def lookup(self, home, away):
        return self._entry if (home, away) == ("Toronto Maple Leafs", "Montreal Canadiens") else None


def test_nhl_pregame_shows_the_projected_final_and_no_fixed_share_periods(monkeypatch):
    """hockeysim's `periodN_*_proj` are fixed league shares of its input rate: the block carries no period."""
    from syndicate.features.nhl.game_projections import NhlGameProjectionEntry

    entry = NhlGameProjectionEntry(home="Toronto Maple Leafs", away="Montreal Canadiens", p_home_ml=0.465789,
                                   model_total=6.6414, model_spread=-0.2149, p_home_pl_minus_1_5=0.25, p_over=0.51,
                                   totals_line_used=6.5, anchor_state="anchored")
    _patch_sources(monkeypatch, nhl={"2026-11-07": _NhlIndex(entry)})
    chip = _other_chip("nhl", key="4", away=("Montreal Canadiens", "montreal canadiens", "MTL"),
                       home=("Toronto Maple Leafs", "toronto maple leafs", "TOR"))
    gci.attach_interval_projections([chip], "2026-11-07")
    block = chip["intervals"]
    assert block["periods"] == [] and block["precision"] == 1
    assert block["final"] == {"away": 3.4, "home": 3.2, "total": 6.6, "home_margin": -0.2, "home_win_prob": 0.466}


def _football_segments():
    q = {"home_points_mean": 7.0, "away_points_mean": 3.0, "total_points_dist": _point(10), "margin_dist": _point(4)}
    full = {"home_points_mean": 27.0, "away_points_mean": 17.0, "total_points_dist": _point(44),
            "margin_dist": _point(10)}
    return {"full": full, "q1": q, "q2": q, "q3": q, "q4": dict(q, home_points_mean=6.0, away_points_mean=4.0),
            "h1": q, "h2": q}


def test_nfl_pregame_shows_the_simulated_quarters_by_game_id(monkeypatch):
    block = {"game_id": "2026_09_DEN_CAR", "sims": 300, "segments": _football_segments()}
    _patch_sources(monkeypatch, nfl={"by_id": {"2026_09_DEN_CAR": block}, "by_pair": {}})
    chip = _other_chip("nfl", key="2026_09_DEN_CAR", away=("Denver Broncos", "denver broncos", "DEN"),
                       home=("Carolina Panthers", "carolina panthers", "CAR"))
    gci.attach_interval_projections([chip], "2026-11-08")
    iv = chip["intervals"]
    assert [p["label"] for p in iv["periods"]] == ["Q1", "Q2", "Q3", "Q4"]
    assert (iv["periods"][3]["away"], iv["periods"][3]["home"]) == (4.0, 6.0)
    # No win probability: the board's football moneyline probability comes from the projections CSV.
    assert iv["final"] == {"away": 17.0, "home": 27.0, "total": 44.0, "home_margin": 10.0, "home_win_prob": None}
    assert "precision" not in iv and iv["sims"] == 300


def test_ncaaf_pregame_restates_a_reversed_pair_in_the_chips_frame(monkeypatch):
    """A neutral-site game can be listed the other way round in the projections CSV: the sides swap, never mislabel."""
    from syndicate.features.ncaaf.game_projections import _norm

    inputs = {"blocks": {"401858511": {"sims": 300, "segments": _football_segments()}},
              "game_ids": {(_norm("Michigan State"), _norm("Michigan")): "401858511"}}  # CSV: home MSU, away UM
    _patch_sources(monkeypatch, ncaaf={"2026-11-07": inputs})
    chip = _other_chip("ncaaf", key="11_Michigan_State_Michigan", away=("Michigan State", "michigan state", "MS"),
                       home=("Michigan", "michigan", "MIC"))
    gci.attach_interval_projections([chip], "2026-11-07")
    iv = chip["intervals"]
    assert (iv["periods"][0]["away"], iv["periods"][0]["home"]) == (7.0, 3.0)
    assert iv["final"]["home_margin"] == -10.0 and iv["final"]["away"] == 27.0


def test_mlb_pregame_shows_first_one_three_five_innings_and_the_final(monkeypatch):
    def seg(a, h, w):
        return {"away_runs_mean": a, "home_runs_mean": h, "home_win_prob": w, "total_runs_dist": _point(1)}

    row = {"game_pk": 849804, "away": "MIL", "home": "TB", "first1": seg(0.393, 0.437, 0.2),
           "first3": seg(1.002, 1.139, 0.35), "first5": seg(1.652, 1.816, 0.41), "full": seg(3.378, 3.075, 0.501)}
    _patch_sources(monkeypatch, mlb={"2026-10-26": {"_generated_at": "g", "849804": row}})
    chip = _other_chip("mlb", key="849804", start="2026-10-26T23:08:00+00:00",
                       away=("Milwaukee Brewers", "milwaukee brewers", "MIL"), home=("Tampa Bay Rays", "tampa bay rays", "TB"))
    gci.attach_interval_projections([chip], "2026-10-26")
    iv = chip["intervals"]
    assert [(p["label"], p["away"], p["home"]) for p in iv["periods"]] == [("F1", 0.4, 0.4), ("F3", 1.0, 1.1),
                                                                           ("F5", 1.7, 1.8)]
    assert iv["final"] == {"away": 3.4, "home": 3.1, "total": 6.5, "home_margin": -0.3, "home_win_prob": 0.501}
    assert iv["precision"] == 1 and iv["as_of"] == "g"


def test_mlb_live_has_no_block_yet(monkeypatch):
    """No verified live reader (season over 2026-11-07): a live MLB chip loses any pregame block, gains none."""
    _patch_sources(monkeypatch)
    chip = _other_chip("mlb", state="live", key="849804")
    chip["intervals"] = {"source": "pregame_sim"}
    gci.attach_interval_projections([chip], "2026-10-26")
    assert "intervals" not in chip


def test_other_sport_sources_are_reached_off_and_on(monkeypatch):
    """off != on for the new sources through the public attach: absent -> no block, present -> a block."""
    def chips():
        return [_soccer_chip(), _other_chip("nfl", key="2026_09_DEN_CAR")]

    _patch_sources(monkeypatch)
    off = chips()
    gci.attach_interval_projections(off, "2026-11-07")
    assert all("intervals" not in c for c in off)
    gci.clear_cache()
    _patch_sources(monkeypatch, soccer={("mls", "2026-11-07"): {"_generated_at": "g", "761942": _soccer_match()}},
                   nfl={"by_id": {"2026_09_DEN_CAR": {"sims": 300, "segments": _football_segments()}}, "by_pair": {}})
    on = chips()
    gci.attach_interval_projections(on, "2026-11-07")
    assert all("intervals" in c for c in on)


def test_one_sports_failing_source_never_costs_another(monkeypatch):
    _patch_sources(monkeypatch, soccer={("mls", "2026-11-07"): {"_generated_at": "g", "761942": _soccer_match()}})

    def boom(*a, **k):
        raise RuntimeError("unreadable")

    monkeypatch.setattr(gci, "_nfl_pregame_block", boom)
    chips = [_other_chip("nfl", key="x"), _soccer_chip()]
    counts = gci.attach_interval_projections(chips, "2026-11-07")
    assert counts.get("nfl:error") == 1 and "intervals" not in chips[0] and "intervals" in chips[1]


def test_json_reads_are_reused_until_the_file_changes(tmp_path):
    import os

    path = tmp_path / "x.json"
    path.write_text('{"a": 1}', encoding="utf-8")
    assert gci._read_json_unchanged(path) == {"a": 1}
    st = path.stat()
    path.write_text('{"a": 2}', encoding="utf-8")
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns))  # same mtime AND same size: the cached parse is kept
    assert gci._read_json_unchanged(path) == {"a": 1}
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 10_000_000))
    assert gci._read_json_unchanged(path) == {"a": 2}
    assert gci._read_json_unchanged(tmp_path / "absent.json") is None
