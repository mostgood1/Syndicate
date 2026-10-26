"""One paper stake per alt ladder (user decision 2026-10-26, lane `layer2-suggested-opps`).

Rungs sharing (event, market without its alt marker, segment, player, side) are one
ladder; `cap_alt_ladder_stakes` scales them together so the ladder's total is its
largest single rung. Every rung stays staked. Reachability first: the production
runner applies it to the main plan, and a bare `commit_portfolio` (what the venue
books call) does not.
"""

from __future__ import annotations

import pytest

from pipeline.portfolio_commit import _alt_ladder_key, cap_alt_ladder_stakes
from syndicate.features.shared.portfolio_settings import PortfolioSettings


def _position(line, dollars, *, market="totals_alt", side="over", event="evt-1", player=None, segment="full"):
    fraction = dollars / 1000.0
    return {
        "sport": "nba",
        "event_id": event,
        "market": market,
        "segment": segment,
        "player_name": player,
        "side": side,
        "line": line,
        "stake_dollars": dollars,
        "stake_fraction": fraction,
        "attribution": {
            "stake_fraction_ev_only": fraction,
            "stake_fraction_sim_delta": 0.0,
            "sim_share_of_stake": 0.0,
            "stake_dollars_ev_only": dollars,
            "stake_dollars_sim_delta": 0.0,
            "side_picked_by": "market",
        },
        "sizing": {},
    }


def _plan(positions, *, min_stake=1.0):
    staked = round(sum(p["stake_dollars"] for p in positions), 2)
    return {
        "bankroll_units": 1000.0,
        "settings": {"min_stake_units": min_stake},
        "positions": positions,
        "totals": {"positions": len(positions), "staked_dollars": staked, "staked_fraction": staked / 1000.0},
    }


def test_a_ladder_totals_its_largest_rung_and_keeps_every_rung() -> None:
    plan = _plan([_position(220.5, 6.44), _position(231.5, 9.23)])
    report = cap_alt_ladder_stakes(plan)
    stakes = [p["stake_dollars"] for p in plan["positions"]]
    assert len(stakes) == 2 and all(s > 0 for s in stakes)
    assert sum(stakes) == pytest.approx(9.23, abs=0.011)
    # Ratios preserved: the bigger rung stays bigger.
    assert stakes[1] > stakes[0]
    assert report == plan["alt_ladder_cap"]
    assert (report["ladders"], report["rungs"], report["floored_at_min"]) == (1, 2, 0)
    assert report["staked_dollars_before"] == 15.67
    assert plan["totals"]["staked_dollars"] == pytest.approx(9.23, abs=0.011)
    assert plan["totals"]["positions"] == 2
    assert plan["positions"][0]["sizing"]["stake_dollars_pre_ladder_cap"] == 6.44
    assert plan["positions"][0]["sizing"]["alt_ladder_rungs"] == 2
    assert plan["positions"][0]["attribution"]["stake_dollars_ev_only"] == plan["positions"][0]["stake_dollars"]


def test_single_rungs_and_different_ladders_are_untouched() -> None:
    positions = [
        _position(220.5, 6.0),
        _position(220.5, 5.0, side="under"),
        _position(220.5, 4.0, event="evt-2"),
        _position(25.5, 3.0, market="player_points_alternate", player="A"),
        _position(25.5, 2.0, market="player_points_alternate", player="B"),
        _position(220.5, 7.0, segment="h1"),
    ]
    plan = _plan(positions)
    report = cap_alt_ladder_stakes(plan)
    assert report["ladders"] == 0
    assert [p["stake_dollars"] for p in plan["positions"]] == [6.0, 5.0, 4.0, 3.0, 2.0, 7.0]
    assert plan["totals"]["staked_dollars"] == 27.0
    assert "stake_dollars_pre_ladder_cap" not in plan["positions"][0]["sizing"]


@pytest.mark.parametrize(
    "a, b",
    [
        ("totals", "totals_alt"),
        ("spreads_alt", "spreads"),
        ("player_points", "player_points_alternate"),
        ("alternate_totals_corners", "totals_corners"),
    ],
)
def test_the_main_line_and_its_alt_rungs_are_one_ladder(a, b) -> None:
    assert _alt_ladder_key(_position(1.5, 1.0, market=a)) == _alt_ladder_key(_position(2.5, 1.0, market=b))


def test_a_rung_scaled_under_the_min_stake_is_held_at_the_min() -> None:
    plan = _plan([_position(line, 4.0) for line in (219.5, 220.5, 221.5, 222.5, 223.5)], min_stake=1.0)
    report = cap_alt_ladder_stakes(plan)
    # 5 x $4 capped at $4 is $0.80 a rung, under the $1 min: every rung held at $1, none dropped.
    assert [p["stake_dollars"] for p in plan["positions"]] == [1.0] * 5
    assert report["floored_at_min"] == 5


def _rows():
    def row(line, market="totals_alt", event="evt-nba-1", price=110):
        return {
            "sport": "nba",
            "event_id": event,
            "kind": "game",
            "market": market,
            "segment": "full",
            "line": line,
            "player_name": None,
            "home_team": "AAA",
            "away_team": "BBB",
            "commence_time": "2026-10-27T00:00:00Z",
            "side": "over",
            "quote": {"price": price, "bookmaker": "fanduel"},
            "ev_pct": 4.0,
            "model_edge_pct": 3.0,
            "score": {"score": 5.1, "price_reliability": 0.82},
            "suggested": True,
        }

    return [row(218.5, market="totals"), row(220.5), row(222.5, price=125), row(205.5, market="totals", event="evt-nba-2")]


def test_reachability_the_runner_caps_the_main_plan_and_a_bare_commit_does_not(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SYNDICATE_REPORTS_ROOT", str(tmp_path))
    monkeypatch.setenv("SYNDICATE_PORTFOLIO_COMMIT_ENABLED", "1")
    for key in ("SYNDICATE_EXECUTION_ENABLED", "SYNDICATE_REFRESH_STATE_BACKEND", "SYNDICATE_PAPER2_VENUES"):
        monkeypatch.delenv(key, raising=False)
    settings = PortfolioSettings(
        bankroll_units=1000.0, max_slate_exposure_fraction=1.0, min_ev_pct=-100.0, max_positions=50, min_stake_units=0.0
    )
    monkeypatch.setattr("syndicate.features.shared.portfolio_commit.resolve_settings", lambda: settings)
    monkeypatch.setattr("pipeline.portfolio_commit.resolve_settings", lambda: settings)
    monkeypatch.setattr("pipeline.intelligence_state.read_layer2_shortlist", lambda date: {"rows": _rows()})
    from pipeline import portfolio_commit as commit

    off = commit.commit_portfolio(_rows(), selected_date="2026-10-26", settings=settings, settled_sample_size_by_sport={})
    ladder_off = [p["stake_dollars"] for p in off["positions"] if p["event_id"] == "evt-nba-1"]
    assert len(ladder_off) == 3, off.get("refusals")
    assert "alt_ladder_cap" not in off

    result = commit.run_portfolio_commit("2026-10-26", settled_sample_size_by_sport={})
    assert result["status"] == "ok", result
    on = result["plan"]
    ladder_on = [p["stake_dollars"] for p in on["positions"] if p["event_id"] == "evt-nba-1"]
    assert len(ladder_on) == 3 and all(s > 0 for s in ladder_on)
    assert sum(ladder_on) == pytest.approx(max(ladder_off), abs=0.02)
    assert sum(ladder_on) < sum(ladder_off)
    assert on["alt_ladder_cap"]["ladders"] == 1
    single = [p["stake_dollars"] for p in on["positions"] if p["event_id"] == "evt-nba-2"]
    assert single == [p["stake_dollars"] for p in off["positions"] if p["event_id"] == "evt-nba-2"]
