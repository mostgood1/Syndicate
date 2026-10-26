"""Hermetic tests for `scripts/e5_venue_news_lag.py` (lane `e5-venue-news-lag`). No network, no data root."""
from __future__ import annotations

import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("e5_venue_news_lag", ROOT / "scripts" / "e5_venue_news_lag.py")
e5 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(e5)

UTC = timezone.utc
T = datetime(2026, 10, 20, 15, 0, tzinfo=UTC)


def _ts(minutes: float) -> datetime:
    return T + timedelta(minutes=minutes)


def _iso(minutes: float) -> str:
    return _ts(minutes).strftime("%Y-%m-%dT%H:%M:%SZ")


def _rec(minutes, athlete, aid, event, status=None, previous=None, team="Houston Rockets"):
    rec = {"athlete": athlete, "athlete_id": aid, "captured_at": _iso(minutes), "event": event, "team": team}
    if status is not None:
        rec["status"] = status
    if previous is not None:
        rec["previous_status"] = previous
    return rec


def _runs(*mins):
    return [_ts(m) for m in mins]


# ----------------------------------------------------------------------------- events


def test_baseline_run_is_never_an_event():
    recs = [_rec(0, "Steven Adams", "1", "new", "Out")]
    events, counts = e5.injury_events(recs, "nba", _runs(0, 10, 20))
    assert events == [] and counts["candidates"] == 0


def test_same_run_id_churn_pair_nets_to_no_event():
    recs = [_rec(0, "Luke Kennard", "1", "new", "Day-To-Day"),
            # run 2: ESPN re-keys the athlete -- a new id and a cleared id for one name, same status
            _rec(10, "Luke Kennard", "2", "new", "Day-To-Day"),
            _rec(10, "Luke Kennard", "1", "cleared", previous="Day-To-Day")]
    events, counts = e5.injury_events(recs, "nba", _runs(0, 10, 20))
    assert events == [] and counts["candidates"] == 0


def test_churn_pair_carrying_a_real_change_is_one_event():
    recs = [_rec(0, "Other Guy", "9", "new", "Out"),
            _rec(10, "Steven Adams", "1", "new", "Day-To-Day"),
            _rec(20, "Steven Adams", "2", "new", "Out"),
            _rec(20, "Steven Adams", "1", "cleared", previous="Day-To-Day")]
    events, counts = e5.injury_events(recs, "nba", _runs(0, 10, 20, 30))
    assert [(e["kind"], e["t0"]) for e in events] == [("to_out", _ts(20))]
    assert events[0]["player_key"] == "STEVEN ADAMS"


def test_flap_is_dropped_and_its_reversal_is_not_an_event():
    recs = [_rec(0, "Other Guy", "9", "new", "Out"),
            _rec(10, "Steven Adams", "1", "new", "Out"),
            _rec(20, "Steven Adams", "1", "cleared", previous="Out")]
    events, counts = e5.injury_events(recs, "nba", _runs(0, 10, 20, 30, 40))
    assert events == [] and counts["flap"] == 1


def test_state_holds_when_the_next_run_wrote_nothing_for_the_sport():
    recs = [_rec(0, "Other Guy", "9", "new", "Out"),
            _rec(10, "Steven Adams", "1", "new", "Out")]
    # runs 20 and 30 happened (other sports wrote records) but nba changed nothing
    events, _ = e5.injury_events(recs, "nba", _runs(0, 10, 20, 30))
    assert [(e["kind"], e["t0"]) for e in events] == [("to_out", _ts(10))]


def test_back_in_after_a_confirmed_out_is_to_in():
    recs = [_rec(0, "Other Guy", "9", "new", "Out"),
            _rec(10, "Steven Adams", "1", "new", "Out"),
            _rec(60, "Steven Adams", "1", "cleared", previous="Out")]
    events, _ = e5.injury_events(recs, "nba", _runs(0, 10, 20, 50, 60, 70))
    assert [e["kind"] for e in events] == ["to_out", "to_in"]


def test_questionable_is_playable_so_no_event():
    recs = [_rec(0, "Other Guy", "9", "new", "Out"),
            _rec(10, "Steven Adams", "1", "new", "Questionable")]
    events, counts = e5.injury_events(recs, "nba", _runs(0, 10, 20))
    assert events == [] and counts["candidates"] == 0


def test_t0_after_a_host_sleep_is_uncertain():
    recs = [_rec(0, "Other Guy", "9", "new", "Out"),
            _rec(90, "Steven Adams", "1", "new", "Out")]
    events, counts = e5.injury_events(recs, "nba", _runs(0, 90, 100))  # 90 min gap before t0
    assert events == [] and counts["t0_uncertain"] == 1


def test_scratch_first_sighting_and_flap():
    base = {"game_id": "g1", "away": "SJS", "home": "OTT", "start_utc": _iso(60)}
    recs = [dict(base, captured_at=_iso(30), away_scratches=[], home_scratches=[{"name": "Thomas Chabot"}, {"name": "A Flap"}]),
            dict(base, captured_at=_iso(40), away_scratches=[], home_scratches=[{"name": "Thomas Chabot"}])]
    events, counts = e5.scratch_events(recs, _runs(20, 30, 40, 50))
    assert [(e["player"], e["t0"], e["team"]) for e in events] == [("Thomas Chabot", _ts(30), "OTT")]
    assert counts["flap"] == 1


# ----------------------------------------------------------------------------- identity


@pytest.mark.parametrize("label,name,ok", [
    ("Utah", "Utah Jazz", True),
    ("Los Angeles L", "Los Angeles Lakers", True),
    ("Los Angeles L", "Los Angeles Clippers", False),
    ("Chicago WS", "Chicago White Sox", True),
    ("Chicago WS", "Chicago Cubs", False),
    ("New York", "New Orleans Pelicans", False),
    ("", "Utah Jazz", False),
])
def test_label_matches(label, name, ok):
    assert e5.label_matches(label, name) is ok


def test_kalshi_event_needs_exactly_two_markets_one_per_team():
    events = {"KXNBAGAME-26OCT25LALUTA": [{"ticker": "A-LAL", "label": "Los Angeles L"}, {"ticker": "A-UTA", "label": "Utah"}],
              "KXNBAGAME-26OCT25LACPHX": [{"ticker": "B-LAC", "label": "Los Angeles C"}, {"ticker": "B-PHX", "label": "Phoenix"}]}
    hit = e5.match_kalshi_event(events, home="Utah Jazz", away="Los Angeles Lakers")
    assert hit == ("KXNBAGAME-26OCT25LALUTA", {"home": "A-UTA", "away": "A-LAL"})
    assert e5.match_kalshi_event({"X": events["KXNBAGAME-26OCT25LALUTA"][:1]}, "Utah Jazz", "Los Angeles Lakers") is None


# ----------------------------------------------------------------------------- books


def _h2h(rows):
    return sorted((_ts(m), book, sel, price) for m, book, sel, price in rows)


def test_book_first_move_is_directional_and_bracketed():
    rows = _h2h([(-30, "dk", "home", -150), (-30, "dk", "away", 130),
                 (-30, "fd", "home", -150), (-30, "fd", "away", 130),
                 (4, "dk", "home", -145), (4, "dk", "away", 125),      # home UP a little: wrong way for to_out
                 (8, "fd", "home", -120), (8, "fd", "away", 100)])     # home DOWN ~4pp: the move
    tl = e5.book_timelines(rows, "home")
    snaps = sorted({r[0] for r in rows} | {_ts(6)})
    prev = lambda t: max([s for s in snaps if s < t], default=None)  # noqa: E731
    bm = e5.book_first_move(tl, ["dk", "fd"], _ts(0), _ts(60), -1, prev)
    assert bm["book"] == "fd" and bm["late"] == _ts(8) and bm["early"] == _ts(6) and bm["mid"] == _ts(7)
    assert e5.book_first_move(tl, ["dk", "fd"], _ts(0), _ts(60), +1, prev) is None or \
        e5.book_first_move(tl, ["dk", "fd"], _ts(0), _ts(60), +1, prev)["book"] == "dk"


def test_consensus_is_the_median_of_books_at_t():
    rows = _h2h([(-10, "a", "home", -200), (-10, "a", "away", 170), (-10, "b", "home", 100), (-10, "b", "away", -120)])
    tl = e5.book_timelines(rows, "home")
    q = e5.consensus_at(tl, ["a", "b"], _ts(0))
    assert 0.45 < q < 0.68


# ----------------------------------------------------------------------------- venue measures


def _unit(s=-1, t0=0, W=120, t_end=60):
    return {"t0": _ts(t0), "s": s, "W": timedelta(minutes=W), "t_end": _ts(t_end)}


def test_measure_venue_lag_drift_and_fee_net_ev():
    series = [(_ts(-90), 0.60), (_ts(-1), 0.60), (_ts(5), 0.59), (_ts(12), 0.55), (_ts(60), 0.50)]
    book = {"early": _ts(2), "mid": _ts(3), "late": _ts(4), "book": "fd"}
    out = e5.measure_venue(series, lambda t: 1 - (e5.value_at(series, t) or 0) + 0.01, lambda t: 0.50,
                           _unit(), book, None, "kalshi", "KXNBAGAME-26OCT25LALUTA-UTA")
    assert out["tau_v_min"] == 12.0
    assert out["lag_mid"] == 9.0 and out["lag_early"] == 10.0 and out["lag_late"] == 8.0
    assert out["lag_censored"] is False
    assert out["drift"] == pytest.approx(0.10)                 # 0.60 at t0+1 -> 0.50 at t_end, signed by s=-1
    price = 1 - 0.60 + 0.01
    fee = 0.07 * price * (1 - price)                           # full-rate bound if the series is unknown
    assert out["ev_1"] == pytest.approx(0.50 / (price + fee) - 1, rel=0.2)
    assert out["moved_15"] is True


def test_measure_venue_censors_a_venue_that_never_moves():
    series = [(_ts(-90), 0.60), (_ts(30), 0.605)]
    book = {"early": _ts(2), "mid": _ts(3), "late": _ts(4), "book": "fd"}
    out = e5.measure_venue(series, lambda t: 0.41, lambda t: 0.5, _unit(W=120), book, None, "kalshi", None)
    assert out["tau_v_min"] is None and out["lag_censored"] is True and out["lag_mid"] == pytest.approx(117.0)


def test_kalshi_mid_refuses_one_sided_books():
    assert e5.kalshi_mid((T, 0.30, 0.31)) == pytest.approx(0.305)
    assert e5.kalshi_mid((T, None, 0.31)) is None
    assert e5.kalshi_mid((T, 0.0, 0.05)) is None
    assert e5.kalshi_mid((T, 0.40, 0.30)) is None


# ----------------------------------------------------------------------------- statistics and verdict


def _rows(n_games, per_game, **fields):
    rows = []
    for g in range(n_games):
        for i in range(per_game):
            rows.append(dict({"unit_id": f"u{g}-{i}", "game": f"g{g}"}, **fields))
    return rows


def test_cluster_boot_is_deterministic_and_brackets_the_point():
    rows = [{"game": f"g{i % 7}", "x": float(i % 5)} for i in range(40)]
    a, b = e5.cluster_boot(rows, "x"), e5.cluster_boot(rows, "x")
    assert a == b and a["n"] == 40 and a["games"] == 7
    assert a["ci95"][0] <= a["mean"] <= a["ci95"][1]


def test_verdict_underpowered_below_the_minimum():
    assert e5.verdict(_rows(5, 2, lag_early=5.0, lag_mid=5.0, lag_late=5.0, drift=0.02))["verdict"] == "UNDERPOWERED"


def test_verdict_kills_a_fast_venue():
    rows = _rows(20, 2, lag_early=1.0, lag_mid=0.5, lag_late=0.0, drift=0.02)
    assert e5.verdict(rows)["verdict"] == "KILL"


def test_verdict_kills_a_symmetric_move():
    rows = _rows(20, 2, lag_early=9.0, lag_mid=8.0, lag_late=7.0)
    for i, r in enumerate(rows):
        r["drift"] = 0.02 if i % 2 else -0.02
    assert e5.verdict(rows)["verdict"] == "KILL"


def test_verdict_unresolved_when_the_bracket_straddles_two_minutes():
    rows = _rows(20, 2, lag_early=3.0, lag_mid=1.5, lag_late=0.0, drift=0.03)
    assert e5.verdict(rows)["verdict"] == "UNRESOLVED"


def test_verdict_timing_strategy_needs_positive_ev_and_increment():
    base = dict(lag_early=9.0, lag_mid=8.0, lag_late=7.0, drift=0.03)
    cancel_only = _rows(20, 2, ev_1=-0.02, ev_inc_1=0.01, **base)
    assert e5.verdict(cancel_only)["verdict"] == "PASS_CANCEL_PROTECTION_ONLY"
    timing = _rows(20, 2, ev_1=0.05, ev_inc_1=0.04, **base)
    assert e5.verdict(timing)["verdict"] == "PASS_TIMING_STRATEGY"


# ----------------------------------------------------------------------------- units


class _FakeBooks:
    sport = "nba"

    def __init__(self):
        self.games = {"g1": {"home": "Utah Jazz", "away": "Houston Rockets", "commence": _ts(300)}}

    def next_game(self, tkey, t0):
        return "g1"

    def game_for_scratch(self, ev):
        return "g1"


def _ev(minutes, kind, player="P"):
    return {"sport": "nba", "kind": kind, "source": "espn_injuries", "player": player, "player_key": player.upper(),
            "team": "Houston Rockets", "team_key": "HOUSTON ROCKETS", "t0": _ts(minutes)}


def test_burst_merges_same_kind_and_drops_mixed():
    units, counts = e5.build_units([_ev(0, "to_out", "A"), _ev(20, "to_out", "B"), _ev(100, "to_out", "C"),
                                    _ev(105, "to_in", "D")], _FakeBooks(), _ts(1000))
    assert len(units) == 1 and units[0]["players"] == ["A", "B"] and units[0]["t0"] == _ts(0)
    assert counts["merged"] == 2 and counts["mixed_burst"] == 1
    assert units[0]["W"] == timedelta(minutes=120) and units[0]["t_end"] == _ts(60)


def test_units_wait_for_the_game_to_commence():
    units, counts = e5.build_units([_ev(0, "to_out")], _FakeBooks(), _ts(200))
    assert units == [] and counts["not_commenced"] == 1


def test_collector_runs_come_from_the_log_and_skip_errored_feeds(tmp_path):
    log = tmp_path / "news_collector.log"
    log.write_text("\n".join([
        'NEWS_COLLECT {"captured_at": "2026-10-20T15:00:00Z", "errors": {}, "results": {"nba_injuries": {}, "nhl_gameinfo": {}}}',
        "some other line",
        'NEWS_COLLECT {"captured_at": "2026-10-20T15:10:00Z", "errors": {"nba_injuries": "HTTP 503"}, "results": {"nba_injuries": {}}}',
        'NEWS_COLLECT {"captured_at": "2026-10-20T15:20:00Z", "errors": {}, "results": {"nba_injuries": {}}}',
    ]), encoding="utf-8")
    runs, source = e5.collector_runs(tmp_path, log)
    assert source == "collector_log"
    assert runs["nba_injuries"] == [_ts(0), _ts(20)]
    assert runs["nhl_gameinfo"] == [_ts(0)]
