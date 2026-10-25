import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import importlib.util

_PATH = Path(__file__).resolve().parents[1] / "scripts" / "kalshi_market_price_map.py"
_spec = importlib.util.spec_from_file_location("kalshi_market_price_map", _PATH)
pm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pm)

END = datetime(2026, 10, 23, 3, 0, tzinfo=timezone.utc)


def test_taker_yes_win_pays_one_minus_price_minus_fee():
    (t_side, tq, tr), (m_side, mq, mr) = pm.positions(
        {"yes_price": 0.60, "taker_side": "yes"}, "yes", "quadratic_with_maker_fees", 1.0)
    assert (t_side, m_side) == ("taker", "maker")
    assert tq == pytest.approx(0.60) and mq == pytest.approx(0.40)
    assert tr == pytest.approx(0.40 - 0.07 * 0.6 * 0.4)
    assert mr == pytest.approx(-0.40 - 0.0175 * 0.4 * 0.6)


def test_taker_no_side_uses_the_no_price_and_outcome():
    (_, tq, tr), (_, mq, mr) = pm.positions({"yes_price": 0.20, "taker_side": "no"}, "yes", "quadratic", 0.5)
    assert tq == pytest.approx(0.80)
    assert tr == pytest.approx(-0.80 - 0.07 * 0.5 * 0.8 * 0.2)
    # quadratic series: the maker pays nothing
    assert mq == pytest.approx(0.20) and mr == pytest.approx(0.80)


def test_maker_fee_zero_sensitivity():
    (_, _, _), (_, _, mr) = pm.positions({"yes_price": 0.5, "taker_side": "yes"}, "no", "quadratic_with_maker_fees",
                                          1.0, maker_fee_on=False)
    assert mr == pytest.approx(0.5)


def test_phase_bands_follow_the_registration():
    d = timedelta(hours=pm.DURATION_H["nfl"])
    assert pm.phase_of(END - timedelta(minutes=5), END, "nfl") == "final"
    assert pm.phase_of(END - timedelta(hours=1), END, "nfl") == "in_play"
    assert pm.phase_of(END - d - timedelta(minutes=46), END, "nfl") == "pregame"
    # the start-time uncertainty band is excluded on both sides of the nominal start
    assert pm.phase_of(END - d - timedelta(minutes=30), END, "nfl") is None
    assert pm.phase_of(END - d + timedelta(minutes=10), END, "nfl") is None
    assert pm.phase_of(END + timedelta(seconds=1), END, "nfl") is None


def test_buckets_cover_1_to_99_and_refuse_outside():
    assert pm.bucket_of(0.01) == "1-10"
    assert pm.bucket_of(0.55) == "55-70"
    assert pm.bucket_of(0.99) == "95-100"
    assert pm.bucket_of(0.005) is None


def test_game_end_comes_from_the_moneyline_not_an_early_closing_total():
    ms = {
        ("KXNFLGAME", "game"): [{"ticker": "KXNFLGAME-26OCT22NECHI-NE", "event_ticker": "KXNFLGAME-26OCT22NECHI",
                                 "close_time": "2026-10-23T03:23:44Z", "result": "no"}],
        ("KXNFLTOTAL", "total"): [{"ticker": "KXNFLTOTAL-26OCT22NECHI-40", "event_ticker": "KXNFLTOTAL-26OCT22NECHI",
                                   "close_time": "2026-10-23T01:52:30Z", "result": "yes"}],
    }
    g = pm.build_games(ms, "nfl")
    rec = g[("nfl", "26OCT22NECHI")]
    assert rec["end"] == datetime(2026, 10, 23, 3, 23, 44, tzinfo=timezone.utc)
    assert rec["half"] == "confirm"
    assert len(rec["markets"]["total"]) == 1


def test_a_game_with_no_settled_moneyline_is_dropped():
    ms = {("KXNFLGAME", "game"): [{"ticker": "X", "event_ticker": "KXNFLGAME-A", "close_time": "2026-10-01T00:00:00Z",
                                   "result": ""}]}
    assert pm.build_games(ms, "nfl") == {}


def test_accumulate_excludes_prints_after_the_markets_own_close_and_blocks():
    rec = {"sport": "nfl", "game": "G", "end": END.isoformat(), "half": "confirm", "markets": [{
        "family": "total", "result": "yes", "close_time": (END - timedelta(hours=1)).isoformat(),
        "fee_type": "quadratic", "mult": 1.0, "prints": [
            {"t": (END - timedelta(minutes=30)).isoformat(), "yes_price": 0.9, "count": 5, "taker_side": "yes", "block": False},
            {"t": (END - timedelta(hours=1, minutes=30)).isoformat(), "yes_price": 0.5, "count": 5, "taker_side": "yes", "block": True},
            {"t": (END - timedelta(hours=1, minutes=40)).isoformat(), "yes_price": 0.5, "count": 2, "taker_side": "yes", "block": False},
        ]}]}
    cells, excl = pm.accumulate(rec)
    assert excl["after_market_close"] == 1 and excl["block"] == 1
    s = cells[("taker", "40-55", "in_play")]
    assert s[1] == 1 and s[0] == pytest.approx(0.5 - 0.07 * 0.25)


def test_verdict_needs_both_halves_and_a_positive_confirm_lower_bound():
    assert pm.verdict(299, 400, 0.01, 0.001, 0.02) == "INSUFFICIENT"
    assert pm.verdict(300, 300, 0.01, 0.001, 0.02) == "STRUCTURAL EDGE"
    assert pm.verdict(300, 300, -0.01, 0.001, 0.02) == "OPEN"
    assert pm.verdict(300, 300, 0.01, -0.03, 0.0) == "FALSIFIED"


def test_bootstrap_is_a_ratio_over_games():
    mean, lo, hi = pm.bootstrap_ci([1.0, 3.0], [1, 1], draws=500)
    assert mean == pytest.approx(2.0)
    assert 1.0 <= lo <= mean <= hi <= 3.0


def test_the_script_has_no_order_or_credential_path():
    tree = ast.parse(_PATH.read_text(encoding="utf-8"))
    mods = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)} | {
        a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    assert not any(m and m.startswith("syndicate") for m in mods)
    src = _PATH.read_text(encoding="utf-8")
    assert "method=\"POST\"" not in src and "Authorization" not in src and "KALSHI-ACCESS" not in src


def test_recheck_phase_is_elapsed_from_the_scheduled_start_not_the_end():
    start = datetime(2026, 10, 23, 0, 15, tzinfo=timezone.utc)
    d = timedelta(hours=pm.DURATION_H["nfl"])
    assert pm.elapsed_phase(start - timedelta(hours=1), start, "nfl") == "pregame"
    assert pm.elapsed_phase(start + d * 0.05, start, "nfl") is None
    assert pm.elapsed_phase(start + d * 0.3, start, "nfl") == "early"
    assert pm.elapsed_phase(start + d * 0.6, start, "nfl") == "mid"
    assert pm.elapsed_phase(start + d * 1.05, start, "nfl") == "late"


def test_recheck_cells_dedupe_prints_across_windows():
    row = {"sport": "nfl", "result": "yes", "fee_type": "quadratic", "mult": 1.0,
           "expected_expiration_time": "2026-10-23T03:15:00Z", "windows": [
               {"prints": [{"id": "a", "t": "2026-10-23T02:00:00Z", "yes_price": 0.8, "count": 1, "taker_side": "yes"}]},
               {"prints": [{"id": "a", "t": "2026-10-23T02:00:00Z", "yes_price": 0.8, "count": 1, "taker_side": "yes"}]}]}
    cells = pm.recheck_cells(row)
    assert cells[("taker", "70-85", "mid")][1] == 1
