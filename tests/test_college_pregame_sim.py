"""College basketball pregame sims, straight to the boards (lane wncaab-module, Phase 3).

The producer (`college_basketball/pregame_sim.py`) is the live tier's engine from the opening tip; the join
(`shared/college_game_projections.py`) prices board rows off its histograms; the launcher
(`ncaab/inplay_lane.maybe_launch_pregame_sims`) runs it from the live-odds-worker. The engine itself is
replaced by a deterministic `simulate` here: these tests pin the plumbing, not the model.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from syndicate.features.college_basketball import pregame_sim as ps
from syndicate.features.ncaab import live_resim as lr
from syndicate.features.ncaab import slate

NOW = datetime(2026, 11, 3, 15, 0, tzinfo=timezone.utc)


def _game(event_id, home, away, *, start="2026-11-04T00:00:00Z", state=None, neutral=False):
    return {"event_id": event_id, "start_time_utc": start, "neutral_site": neutral,
            "home": {"espn_id": home[0], "abbr": home[1], "name": home[2]},
            "away": {"espn_id": away[0], "abbr": away[1], "name": away[2]},
            "live_state": {"in_progress": state == "live", "final": state == "final"}}


TENN = ("2633", "TENN", "Tennessee Volunteers")
WOF = ("2747", "WOF", "Wofford Terriers")
UK = ("96", "UK", "Kentucky Wildcats")
MAN = ("2363", "MAN", "Manhattan Jaspers")


@pytest.fixture
def slate_day(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    games = [_game("1", TENN, WOF), _game("2", UK, MAN), _game("3", UK, WOF, state="live")]
    path = slate.slate_artifact_path("2026-11-03", "ncaab")
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"games": games}), encoding="utf-8")
    calls = []
    provenance = {"ratingsAsOf": "2026-11-02", "playerPriorsAsOf": "2026-11-02", "priorSeasonFallback": True,
                  "halfSplit": True, "mechanisms": ["endgame_foul_window_s"], "pregameTotal": 150.0, "pregameHomeMargin": 10.0}
    monkeypatch.setattr(lr, "load_player_priors", lambda day, dirs=None: object())

    def build(date, home_id, away_id, *, neutral, home_code="", away_code="", priors=None, **_):
        calls.append((home_id, away_id))
        if away_id == MAN[0]:
            return lr.NcaabResimRefusal("team_unrated", f"away:{away_id}")
        return {"_provenance": dict(provenance)}

    monkeypatch.setattr(lr, "build_engine_inputs", build)
    return {"tmp": tmp_path, "calls": calls, "provenance": provenance}


def _simulate(rng, state):
    # home 40+38, away 35+33: a fixed 78-68 game, half by half.
    return None, None, [40, 38], [35, 33]


def test_producer_sims_pregame_games_and_names_every_refusal(slate_day):
    summary = ps.run_pregame_sims("2026-11-03", sims=100, now=NOW, simulate=_simulate)
    assert summary["pregame"] == 2 and summary["simmed"] == 1 and summary["refused"] == 1  # the live game is not a candidate
    doc = ps.read_pregame_sims("2026-11-03")
    sim = doc["games"]["1"]
    assert sim["sims_run"] == 100 and sim["total_mean"] == 146.0 and sim["home_margin_mean"] == 10.0
    assert sim["dist"]["segments"]["full"]["total"] == {"146": 100}
    assert sim["dist"]["segments"]["h1"]["margin"] == {"5": 100} and sim["dist"]["segments"]["h2"]["total"] == {"71": 100}
    assert sim["home"]["key"] and sim["provenance"]["halfSplit"] is True and "exactTarget" in sim["provenance"]
    assert doc["games"]["2"]["refused"] == "team_unrated" and "dist" not in doc["games"]["2"]
    assert "3" not in doc["games"]


def test_producer_resims_only_when_inputs_change(slate_day):
    ps.run_pregame_sims("2026-11-03", sims=100, now=NOW, simulate=_simulate)
    again = ps.run_pregame_sims("2026-11-03", sims=100, now=NOW, simulate=_simulate)
    assert again["unchanged"] == 1 and again["simmed"] == 0
    slate_day["provenance"]["ratingsAsOf"] = "2026-11-03"  # tomorrow's ratings job ran
    assert ps.run_pregame_sims("2026-11-03", sims=100, now=NOW, simulate=_simulate)["simmed"] == 1


def test_producer_stops_at_its_deadline(slate_day):
    ticks = iter([0.0, 100.0, 100.0, 100.0, 100.0])
    summary = ps.run_pregame_sims("2026-11-03", sims=100, now=NOW, deadline=50.0, clock=lambda: next(ticks, 100.0), simulate=_simulate)
    assert summary["simmed"] == 0 and summary["not_reached"] == 2
    assert ps.read_pregame_sims("2026-11-03") is None  # nothing half-built is published


def test_womens_games_refuse_by_name_until_their_tables_exist(tmp_path, monkeypatch):
    # The women's path is real (user 2026-11-02 "Approve the loans"); with no women's priors table on disk a game
    # refuses with the re-sim's own reason, never a default and never the men's tables.
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("SYNDICATE_WNCAAB_SOURCE_ROOT", str(tmp_path / "wncaab_source"))
    path = slate.slate_artifact_path("2026-11-03", "wncaab")
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"games": [_game("9", TENN, WOF)]}), encoding="utf-8")
    summary = ps.run_pregame_sims("2026-11-03", "wncaab", sims=100, now=NOW)
    entry = ps.read_pregame_sims("2026-11-03", "wncaab")["games"]["9"]
    assert summary["refused"] == 1 and entry["refused"] in {"no_player_priors", "no_ratings_table"} and "dist" not in entry


def _row(market, *, home="Tennessee Volunteers", away="Wofford Terriers", line=None, segment="full_game", sides=("home", "away"), prices=(-110, -110)):
    return {"kind": "game", "sport": "ncaab", "market": market, "segment": segment, "line": line, "home_team": home, "away_team": away,
            "commence_time": "2026-11-04 00:00:00+00:00", "sides": list(sides), "consensus": dict(zip(sides, prices))}


def test_join_prices_board_rows_off_the_histograms(slate_day):
    from syndicate.features.shared.board_enrichment import _attach_projections_by_sport

    ps.run_pregame_sims("2026-11-03", sims=100, now=NOW, simulate=_simulate)
    grid = [
        _row("totals", line=140.5, sides=("over", "under")),  # every draw 146 -> refused as certain, not published as 1.0
        _row("spreads", line=-7.5),
        _row("h2h"),
        _row("totals", line=70.5, segment="h1", sides=("over", "under")),
        _row("totals", line=150.5, home="Wofford Terriers", away="Tennessee Volunteers", sides=("over", "under")),  # reversed
        _row("totals", line=150.5, home="Kentucky Wildcats", away="Manhattan Jaspers", sides=("over", "under")),  # refused game
    ]
    coverage = _attach_projections_by_sport(grid, sport="ncaab", selected_date="2026-11-03")
    assert coverage["supported"] and coverage["source"] == "college_pregame_sim"
    assert coverage["rows_with_projection"] == 4 and coverage["period_rows_priced"] == 1
    assert grid[1]["projection"]["projected"] == 10.0 and grid[1]["projection"]["basis"] == "sim_margin_dist/full"
    assert grid[3]["projection"]["projected"] == 75.0 and grid[3]["projection"]["basis"] == "sim_total_dist/h1"
    reasons = coverage["unprojected_by_reason"]
    assert reasons["teams match the sim reversed: orientation differs from the slate"] == 1
    assert reasons["pregame sim refused this game: team_unrated"] == 1
    assert grid[0]["projection"].get("model_prob_over") is None  # one-sided sample: no certainty published


def test_join_reports_an_empty_window_by_name(tmp_path, monkeypatch):
    from syndicate.features.shared.board_enrichment import _attach_projections_by_sport

    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    coverage = _attach_projections_by_sport([_row("h2h")], sport="wncaab", selected_date="2026-11-03")
    assert coverage == {"supported": True, "rows_with_projection": 0, "reason": "no wncaab pregame sim for this date window"}


class _Child:
    def __init__(self):
        self.pid, self.code = 4242, None

    def poll(self):
        return self.code


def test_launcher_switch_is_reachable_and_runs_one_child_at_a_time(slate_day, monkeypatch):
    from syndicate.features.ncaab import inplay_lane

    monkeypatch.setattr(inplay_lane, "central_today_iso", lambda: "2026-11-03")

    class _FrozenNow(datetime):
        # `_pregame_game_count` judges is_pregame against datetime.now; unpinned, the fixture's
        # 11-04 00:00Z tips went past and the test turned red from 11-04 (ci-suite #697).
        @classmethod
        def now(cls, tz=None):
            return NOW if tz is not None else NOW.replace(tzinfo=None)

    monkeypatch.setattr(inplay_lane, "datetime", _FrozenNow)
    monkeypatch.setattr(inplay_lane, "_pregame_child", None)
    monkeypatch.setattr(inplay_lane, "_pregame_last_launch", 0.0)
    launched, child = [], _Child()

    def popen(command, cwd=None):
        launched.append(command)
        return child

    clock = iter([1000.0, 1000.0, 1100.0, 3000.0, 3000.0])
    monkeypatch.setenv("SYNDICATE_COLLEGE_PREGAME_SIM", "0")
    assert inplay_lane.maybe_launch_pregame_sims(popen=popen, clock=lambda: next(clock), now=NOW) is None and not launched
    monkeypatch.setenv("SYNDICATE_COLLEGE_PREGAME_SIM", "1")
    got = inplay_lane.maybe_launch_pregame_sims(popen=popen, clock=lambda: next(clock), now=NOW)
    assert got["pregame_games"] == 2 and got["dates"] == ["2026-11-03", "2026-11-04"]
    assert any(str(part).endswith("build_college_pregame_sims.py") for part in launched[0]) and "--budget-seconds" in launched[0]
    assert inplay_lane.maybe_launch_pregame_sims(popen=popen, clock=lambda: next(clock), now=NOW) is None  # child still running
    child.code = 0
    assert inplay_lane.maybe_launch_pregame_sims(popen=popen, clock=lambda: 1100.0, now=NOW) is None  # exited, interval not passed
    assert inplay_lane.maybe_launch_pregame_sims(popen=popen, clock=lambda: 3000.0, now=NOW) is not None and len(launched) == 2


def test_launcher_judges_pregame_on_the_clock_it_is_given(slate_day, monkeypatch):
    # The 2026-11-04 nightly failure, pinned: the same slate is "two pregame games" before the tip and nothing after it.
    from syndicate.features.ncaab import inplay_lane

    monkeypatch.setattr(inplay_lane, "central_today_iso", lambda: "2026-11-03")
    monkeypatch.setattr(inplay_lane, "_pregame_child", None)
    monkeypatch.setattr(inplay_lane, "_pregame_last_launch", 0.0)
    monkeypatch.setenv("SYNDICATE_COLLEGE_PREGAME_SIM", "1")
    launched = []

    def popen(command, cwd=None):
        launched.append(command)
        return _Child()

    after_tip = datetime(2026, 11, 4, 6, 0, tzinfo=timezone.utc)
    assert inplay_lane.maybe_launch_pregame_sims(popen=popen, clock=lambda: 1000.0, now=after_tip) is None and not launched
    assert inplay_lane.maybe_launch_pregame_sims(popen=popen, clock=lambda: 1000.0, now=NOW)["pregame_games"] == 2


def _priced_row(market, line, *, sides, prices, home="Tennessee Volunteers", away="Wofford Terriers"):
    return {"kind": "game", "sport": "ncaab", "market": market, "segment": "full_game", "line": line, "home_team": home,
            "away_team": away, "commence_time": "2026-11-04 00:00:00+00:00", "sides": list(sides), "consensus": dict(zip(sides, prices))}


def _spread_sim(rng, state):
    # A spread of outcomes so no line is a certainty: home margin cycles 2..18.
    _spread_sim.i = (getattr(_spread_sim, "i", 0) + 1) % 9
    margin = 2 + 2 * _spread_sim.i
    return None, None, [40 + margin, 38], [40, 38]


def test_margin_lines_are_market_anchored_and_totals_are_not(slate_day, monkeypatch):
    # User 2026-11-02 "Fix + anchor": sim margins ran at ~half the market's (slope 0.51, 109 games).
    from syndicate.features.shared import college_game_projections as cgp

    ps.run_pregame_sims("2026-11-03", sims=180, now=NOW, simulate=_spread_sim)
    index = cgp.load_college_game_projections("2026-11-03", "ncaab")
    spread = _priced_row("spreads", 10.5, sides=("home", "away"), prices=(-110, -110))
    total = _priced_row("totals", 160.5, sides=("over", "under"), prices=(-110, -110))
    cgp.attach_college_game_projections([spread, total], index)
    sp, tt = spread["projection"], total["projection"]
    assert sp["book_blend"] == "applied" and sp["book_blend_w"] == 0.0 and sp["p_model_raw"] is not None
    assert abs(sp["model_prob_over"] - sp["market_fair_prob_over"]) < 1e-3 and abs(sp["edge_vs_market_pct"]) < 0.1
    assert sp["projected"] == 10.0  # the sim's own margin stays on the row
    assert tt["book_blend"].startswith("not applied") and tt["model_prob_over"] == tt["p_model_raw"]
    monkeypatch.setenv("SYNDICATE_COLLEGE_MARGIN_MODEL_WEIGHT", "1")  # the switch is reachable: w=1 serves the sim
    spread2 = _priced_row("spreads", 10.5, sides=("home", "away"), prices=(-110, -110))
    cgp.attach_college_game_projections([spread2], index)
    assert abs(spread2["projection"]["model_prob_over"] - spread2["projection"]["p_model_raw"]) < 1e-3


def test_a_calibrated_prior_table_is_not_shrunk_twice():
    import datetime as dt

    from syndicate.features.ncaab import live_team_model as tm

    calibrated = [{"espn_id": "1", "adj_off": "120", "adj_def": "95", "tempo": "70", "games": "30", "calibration_k": "0.78"},
                  {"espn_id": "2", "adj_off": "100", "adj_def": "105", "tempo": "66", "games": "30", "calibration_k": "0.78"}]
    legacy = [{k: v for k, v in row.items() if k != "calibration_k"} for row in calibrated]
    assert tm.prior_regression_for(calibrated) == 0.0 and tm.prior_regression_for(legacy) == tm.PRIOR_REGRESSION
    table = tm.table_from_rows(calibrated, season=2026, as_of=dt.date(2026, 4, 6), source="t",
                               regress_toward_mean=tm.prior_regression_for(calibrated), prior_season=True)
    assert table.prior_season_fallback is True and table.teams["1"].adj_off == 120.0 and table.teams["1"].games == 0


def test_a_changed_prior_target_resims_the_game(slate_day):
    ps.run_pregame_sims("2026-11-03", sims=100, now=NOW, simulate=_simulate)
    slate_day["provenance"]["pregameHomeMargin"] = 18.0  # same table dates, a differently-built prior
    assert ps.run_pregame_sims("2026-11-03", sims=100, now=NOW, simulate=_simulate)["simmed"] == 1
