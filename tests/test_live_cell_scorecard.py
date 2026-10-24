"""scripts/live_cell_scorecard.py -- classification, dedup, clustering and verdict rules."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_PATH = Path(__file__).resolve().parents[1] / "scripts" / "live_cell_scorecard.py"
_spec = importlib.util.spec_from_file_location("live_cell_scorecard", _PATH)
lcs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(lcs)


def _order(**kw):
    base = {"venue": "kalshi", "status": "filled", "outcome": "won", "fill_stake_dollars": 5.0, "pnl_dollars": 4.0,
            "fill_price": 0.5, "submitted_at": "2026-10-21T18:00:00Z", "selected_date": "2026-10-21",
            "event_id": "g1", "sport": "nba", "market": "spreads", "ev_pct": 3.0}
    base.update(kw)
    return base


def test_family_from_market_and_from_tickers():
    assert lcs.family_of({"market": "spreads_alt"}) == "spread"
    assert lcs.family_of({"market": "totals", "player_name": "X"}) == "prop"
    assert lcs.family_of({"market": "batter_hits"}) == "prop"
    assert lcs.family_of({"market": "Receptions"}) == "prop"
    # venue_rebuild rows carry no market
    assert lcs.family_of({"venue": "kalshi", "venue_ticker": "KXMLBTOTAL-26AUG251910KCTOR-8"}) == "total"
    assert lcs.family_of({"venue": "kalshi", "venue_ticker": "KXNCAAFGAME-26OCT29TROYJMU-TROY"}) == "h2h"
    assert lcs.family_of({"venue": "kalshi", "venue_ticker": "KXMLBKS-26AUG25-X"}) == "prop"
    assert lcs.family_of({"venue": "kalshi", "venue_ticker": "KXMVECROSSCATEGORY-S1-X"}) == "parlay"
    assert lcs.family_of({"venue": "polymarket", "venue_ticker": "tsc-mlb-kc-tor-2026-08-25-7pt5"}) == "total"
    assert lcs.family_of({"venue": "polymarket", "venue_ticker": "astatc-mlb-az-col-2026-09-24-k-edurod-gte5"}) == "prop"


def test_sport_and_game_fall_back_to_the_ticker():
    assert lcs.sport_of({"venue_ticker": "KXWNBASPREAD-26SEP22GSVPOR-GSV5"}) == "wnba"
    assert lcs.sport_of({"venue_ticker": "KXNBASPREAD-26OCT22X-Y"}) == "nba"
    # every series on one Kalshi game shares the date+teams token
    assert lcs.game_of({"venue_ticker": "KXMLBTOTAL-26AUG251910KCTOR-8"}) == lcs.game_of(
        {"venue_ticker": "KXMLBSPREAD-26AUG251910KCTOR-KC2"})
    assert lcs.game_of({"venue_ticker": "tsc-mlb-kc-tor-2026-08-25-7pt5"}) == lcs.game_of(
        {"venue_ticker": "aec-mlb-kc-tor-2026-08-25"})
    assert lcs.game_of({"event_id": "abc", "venue_ticker": "KX-1"}) == "abc"


def test_phase_live_is_the_path_paper_is_the_clock():
    assert lcs.phase_of(_order(ev_pct=None)) == "in_game"
    # a pregame-plan order filled after kickoff carries ev and stays pregame
    assert lcs.phase_of(_order(commence_time="2026-10-21T17:00:00Z")) == "pregame"
    assert lcs.phase_of(_order(ev_pct=None, source="venue_rebuild")) == "pregame"
    assert lcs.phase_of(_order(venue="paper:kalshi", commence_time="2026-10-21T17:00:00Z")) == "in_game"
    assert lcs.phase_of(_order(venue="paper:kalshi", commence_time="2026-10-21T19:00:00Z")) == "pregame"


def test_contract_price_reads_both_units():
    assert lcs.contract_price(0.62) == 0.62
    assert abs(lcs.contract_price(-150) - 0.6) < 1e-9
    assert abs(lcs.contract_price(150) - 0.4) < 1e-9
    assert lcs.contract_price(None) is None
    assert lcs.bucket(0.39) == "<40c" and lcs.bucket(0.40) == "40-55c" and lcs.bucket(0.75) == "75c+"


def test_paper_dedups_by_position_live_never_does():
    orders = [_order(venue="paper:kalshi", position_key="p1", fill_price=-110),
              _order(venue="paper:kalshi", position_key="p1", fill_price=-110, submitted_at="2026-10-21T19:00:00Z"),
              _order(position_key="p1"), _order(position_key="p1")]
    rows, drops = lcs.rows_from(orders)
    assert sum(r["book"] == "paper" for r in rows) == 1
    assert sum(r["book"] == "live" for r in rows) == 2
    assert drops["paper:duplicate_position"] == 1


def test_unsettled_and_unfilled_are_counted_not_scored():
    rows, drops = lcs.rows_from([_order(outcome=None), _order(status="rejected"), _order()])
    assert len(rows) == 1
    assert drops == {"live:unsettled": 1, "live:not_filled": 1}


def test_ci_is_seeded_and_clusters_by_game():
    # one game: every leg moves together, so no interval exists
    one_game = [dict(r, game="g") for r in lcs.rows_from([_order(event_id=f"e{i}") for i in range(20)])[0]]
    assert lcs.clustered_ci(one_game)["flat"] == (None, None)
    many = lcs.rows_from([_order(event_id=f"e{i}", outcome="won" if i % 2 else "lost",
                                 pnl_dollars=5.0 if i % 2 else -5.0) for i in range(40)])[0]
    assert lcs.clustered_ci(many, reps=300) == lcs.clustered_ci(many, reps=300)


def test_verdict_needs_games_not_just_bets():
    s = {"n": 50, "games": 3, "ci90_flat": [5.0, 30.0]}
    assert lcs.verdict(s, min_n=5) == "thin"
    s["games"] = 12
    assert lcs.verdict(s, min_n=5) == "EDGE"
    s["ci90_flat"] = [-30.0, -2.0]
    assert lcs.verdict(s, min_n=5) == "LOSES"


def test_report_reconciles_totals():
    orders = [_order(event_id=f"e{i}", pnl_dollars=-5.0, outcome="lost") for i in range(6)] + \
             [_order(event_id=f"f{i}", pnl_dollars=4.5) for i in range(6)]
    report = lcs.build_report(orders, None, None, reps=100, min_n=5)
    head = report["headline"][0]
    assert (head["n"], head["staked"], head["pnl"]) == (12, 60.0, -3.0)
    assert report["weekly"][0]["week"] == "2026-W43"


def _flagged_orders():
    # 12 games, every bet loses: the live cell's CI90 sits wholly below 0
    return [_order(event_id=f"e{i}", outcome="lost", pnl_dollars=-5.0) for i in range(12)]


def test_nightly_writes_dated_files_and_flags_a_losing_cell(tmp_path):
    from datetime import datetime, timezone

    now = datetime(2026, 10, 25, 13, 30, tzinfo=timezone.utc)
    summary = lcs.run_nightly(_flagged_orders(), tmp_path, now, reps=100)
    assert (tmp_path / "2026-10-25.json").is_file() and (tmp_path / "2026-10-25.md").is_file()
    assert set(summary["windows"]) == {"all", "since_2026-10-20", "last_7d"}
    losing = [f for f in summary["flags"] if f["section"] == "headline" and f["window"] == "all"]
    assert losing and losing[0]["verdict"] == "LOSES" and losing[0]["key"] == "live|kalshi|pregame"
    assert summary["previous_file"] is None and summary["flag_changes"]["new"] == summary["flags"]


def test_nightly_diffs_flags_against_the_previous_night(tmp_path):
    from datetime import datetime, timezone

    lcs.run_nightly(_flagged_orders(), tmp_path, datetime(2026, 10, 25, 13, 30, tzinfo=timezone.utc), reps=100)
    mixed = [_order(event_id=f"e{i}", outcome="won" if i % 2 else "lost", pnl_dollars=5.0 if i % 2 else -5.0)
             for i in range(12)]
    summary = lcs.run_nightly(mixed, tmp_path, datetime(2026, 10, 26, 13, 30, tzinfo=timezone.utc), reps=100)
    assert summary["previous_file"] == "2026-10-25.json"
    assert summary["flag_changes"]["new"] == []
    assert any(f["key"] == "live|kalshi|pregame" for f in summary["flag_changes"]["cleared"])


def test_nightly_refuses_when_the_live_document_does_not_read(monkeypatch, tmp_path):
    monkeypatch.setattr(lcs, "fleet_orders", lambda: None)
    assert lcs.main(["nightly", "--reports-root", str(tmp_path)]) == 2
    assert not any(tmp_path.rglob("*.json"))


def test_the_scheduled_job_runs_the_nightly_subcommand():
    from scripts import local_production as lp

    job = {j.name: j for j in lp.SCHEDULED_JOBS}["live-cell-scorecard"]
    assert job.argv == ("scripts/live_cell_scorecard.py", "nightly")
    assert (job.hour, job.minute, job.weekday, job.every_minutes) == (13, 30, None, None)
