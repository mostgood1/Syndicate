"""Tests for the hockeysim historical-truth layer (parse + aggregate + loader cache).

All offline: parsing runs on synthetic ``landing`` dicts and aggregation on synthetic records, so
no test touches the network. A cache round-trip test exercises the loader against a temp cache dir.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from syndicate.features.nhl.sim_engine.hockeysim.historical_truth import (
    HistoricalGameRecord,
    NhlStatsWebTruthLoader,
    build_truth_snapshot,
    parse_landing,
)


def _landing(*, state="OFF", final_type="REG", home_score=3, away_score=1):
    """A synthetic finished-game landing: home 3 (1 EN) vs away 1 (1 PP), final period `final_type`."""
    return {
        "id": 2025020740,
        "gameDate": "2026-01-15",
        "season": "20252026",
        "gameType": 2,
        "gameState": state,
        "homeTeam": {"abbrev": "BUF", "score": home_score, "sog": 30},
        "awayTeam": {"abbrev": {"default": "MTL"}, "score": away_score, "sog": 25},
        "periodDescriptor": {"number": 3, "periodType": final_type},
        "summary": {
            "scoring": [
                {"periodDescriptor": {"number": 1, "periodType": "REG"}, "goals": [
                    {"isHome": True, "strength": "ev", "goalModifier": "none"},
                    {"isHome": False, "strength": "pp", "goalModifier": "none"},
                ]},
                {"periodDescriptor": {"number": 2, "periodType": "REG"}, "goals": [
                    {"isHome": True, "strength": "ev", "goalModifier": "none"},
                ]},
                {"periodDescriptor": {"number": 3, "periodType": "REG"}, "goals": [
                    {"isHome": True, "strength": "ev", "goalModifier": "empty-net"},
                ]},
            ]
        },
    }


# --- parse ------------------------------------------------------------------


def test_parse_landing_basic():
    rec = parse_landing(_landing())
    assert rec is not None
    assert rec.home_abbr == "BUF" and rec.away_abbr == "MTL"  # dict-form abbrev handled
    assert rec.home_goals == 3 and rec.away_goals == 1
    assert rec.home_sog == 30 and rec.away_sog == 25
    assert rec.period_goals == ((1, 1), (1, 0), (1, 0))
    assert rec.pp_goals_away == 1 and rec.pp_goals_home == 0
    assert rec.en_goals_home == 1
    assert rec.home_win is True
    assert rec.total_goals == 4
    assert rec.went_ot is False and rec.went_shootout is False


def test_parse_landing_captures_shorthanded_goals():
    """`sh_goals_*` -- the counterpart PP goals need to calibrate `pk_goal_cal_mult`
    (`docs/ai_context/hockeysim_engine_reference.md` §2d). Isolated fixture, not `_landing()`,
    since adding a goal there would also shift the fixture's period-goal/score-total assertions."""
    payload = {
        "id": 1, "gameDate": "2026-01-15", "season": "20252026", "gameType": 2, "gameState": "OFF",
        "homeTeam": {"abbrev": "BUF", "score": 2, "sog": 20},
        "awayTeam": {"abbrev": "MTL", "score": 1, "sog": 15},
        "periodDescriptor": {"number": 3, "periodType": "REG"},
        "summary": {"scoring": [
            {"periodDescriptor": {"number": 1, "periodType": "REG"}, "goals": [
                {"isHome": True, "strength": "ev"},
                {"isHome": True, "strength": "sh"},
                {"isHome": False, "strength": "sh"},
            ]},
        ]},
    }
    rec = parse_landing(payload)
    assert rec.sh_goals_home == 1
    assert rec.sh_goals_away == 1


def test_parse_landing_ignores_unfinished():
    assert parse_landing(_landing(state="LIVE")) is None
    assert parse_landing({}) is None
    assert parse_landing({"gameState": "FUT"}) is None


def test_parse_landing_flags_overtime_and_shootout():
    ot = parse_landing(_landing(final_type="OT"))
    assert ot.went_ot is True and ot.went_shootout is False
    so = parse_landing(_landing(final_type="SO"))
    assert so.went_ot is True and so.went_shootout is True


def test_parse_landing_shootout_period_not_counted_as_goals():
    payload = _landing(final_type="SO")
    payload["summary"]["scoring"].append(
        {"periodDescriptor": {"number": 5, "periodType": "SO"}, "goals": [
            {"isHome": True, "strength": "ev"}]}
    )
    rec = parse_landing(payload)
    # SO frame must not add a period-goal tuple; only the 3 REG periods.
    assert len(rec.period_goals) == 3
    assert rec.went_shootout is True


# --- aggregate --------------------------------------------------------------


def _rec(**kw) -> HistoricalGameRecord:
    base = dict(
        game_id="g", date="2026-01-10", season="20252026", game_type=2,
        home_abbr="AAA", away_abbr="BBB", home_goals=3, away_goals=2,
        home_sog=30, away_sog=28, period_goals=((1, 1), (1, 0), (1, 1)),
    )
    base.update(kw)
    return HistoricalGameRecord(**base)


def test_build_truth_snapshot_math():
    recs = [
        _rec(home_goals=3, away_goals=2, home_sog=30, away_sog=20, pp_goals_home=1, went_ot=False),
        _rec(home_goals=1, away_goals=4, home_sog=25, away_sog=25, en_goals_away=1, sh_goals_home=1, went_ot=True),
    ]
    snap = build_truth_snapshot(recs)
    m = snap.metrics
    assert snap.n_games == 2
    assert m.goals_per_game == pytest.approx((5 + 5) / 2)          # (3+2)+(1+4) = 10 / 2
    assert m.home_goals_per_game == pytest.approx((3 + 1) / 2)
    assert m.away_goals_per_game == pytest.approx((2 + 4) / 2)
    assert m.shots_per_game == pytest.approx((50 + 50) / 2)
    assert m.home_win_pct == pytest.approx(0.5)                    # game1 home win, game2 away win
    assert m.ot_rate == pytest.approx(0.5)
    assert m.pp_goal_share == pytest.approx(1 / 10)
    assert m.sh_goal_share == pytest.approx(1 / 10)
    assert m.empty_net_share == pytest.approx(1 / 10)
    # period shares sum to ~1
    assert sum(m.period_goal_share) == pytest.approx(1.0, abs=1e-3)


def test_build_truth_snapshot_excludes_playoffs():
    recs = [_rec(game_type=2), _rec(game_type=3), _rec(game_type=3)]
    snap = build_truth_snapshot(recs, regular_only=True)
    assert snap.n_games == 1
    assert snap.excluded_games == 2


def test_build_truth_snapshot_empty_raises():
    with pytest.raises(ValueError):
        build_truth_snapshot([])
    with pytest.raises(ValueError):
        build_truth_snapshot([_rec(game_type=3)], regular_only=True)


def test_calibration_snapshot_keys():
    snap = build_truth_snapshot([_rec()])
    cal = snap.to_calibration_snapshot()
    assert set(cal) == {
        "goals_per_game", "home_goals_per_game", "away_goals_per_game", "shots_per_game",
        "shooting_pct", "period1_share", "period2_share", "period3_share",
        "pp_goal_share", "sh_goal_share", "empty_net_share", "home_win_pct", "ot_rate", "shootout_rate",
    }
    assert all(isinstance(v, float) for v in cal.values())


# --- loader cache -----------------------------------------------------------


def test_loader_offline_returns_empty_without_cache(tmp_path):
    loader = NhlStatsWebTruthLoader(cache_dir=tmp_path, offline=True)
    assert loader.finished_game_ids_for_date("2026-01-15") == []
    assert loader.fetch_landing("2025020740") is None
    assert loader.load_from_cache() == []


def test_loader_load_from_cache_roundtrip(tmp_path):
    (tmp_path / "landing_2025020740.json").write_text(json.dumps(_landing()), encoding="utf-8")
    loader = NhlStatsWebTruthLoader(cache_dir=tmp_path, offline=True)
    # cache hit works even offline
    assert loader.fetch_landing("2025020740") is not None
    recs = loader.load_from_cache()
    assert len(recs) == 1 and recs[0].home_abbr == "BUF"
    snap = build_truth_snapshot(recs)
    assert snap.n_games == 1
