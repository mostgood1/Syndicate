"""scripts/live_book_edge_readout.py -- the live book's edge at the price paid (todo #815).

Synthetic orders pin every formula. The 2026-11-16 fleet numbers are pinned by
`test_reproduces_the_2026_11_16_fleet_readout`, which runs only when
`SYNDICATE_EDGE_READOUT_PAYLOAD` points at that saved `/api/portfolio/live` payload: the repo is public,
so row-level live trades are not committed.
"""

from __future__ import annotations

import importlib.util
import json
import math
import os
import sys
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parents[1] / "scripts" / "live_book_edge_readout.py"
_spec = importlib.util.spec_from_file_location("live_book_edge_readout", _PATH)
R = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = R  # a @dataclass resolves its module through sys.modules
_spec.loader.exec_module(R)


def _order(i, *, outcome="won", p=0.5, stake=1.0, fees=0.0, event=None, date="2026-11-10", close=None,
           scope=None, path="model_edge", status="filled", **extra):
    if outcome == "won":
        pnl = stake * (1 / p - 1) - (fees or 0.0)
    elif outcome == "lost":
        pnl = -stake - (fees or 0.0)
    else:
        pnl = 0.0
    order = {
        "idempotency_key": f"k{i}",
        "event_id": event or f"e{i}",
        "status": status,
        "outcome": outcome,
        "fill_price": p,
        "fill_stake_dollars": stake,
        "fees_dollars": fees,
        "pnl_dollars": pnl,
        "selected_date": date,
        "venue": "kalshi",
        "sport": "nba",
        "market": "h2h",
        "sizing_basis": path,
    }
    if close is not None:
        order["closing_mark"] = {"reason": "resolved", "close_price": close, "clv_pct": -34.0}
        if scope:
            order["closing_mark"]["close_book_scope"] = scope
    order.update(extra)
    return order


# --- which bets count -----------------------------------------------------------


def test_only_decided_positions_with_a_usable_price_and_stake_count():
    orders = [
        _order(1),
        _order(2, status="rejected"),
        _order(3, outcome=None),
        _order(4, stake=0.0),
        _order(5, p=1.5),
        _order(6, outcome="push"),
    ]
    bets = R.bets_from_orders(orders)
    assert sorted(b.event for b in bets) == ["e1", "e6"]


def test_breakeven_carries_the_fee():
    (bet,) = R.bets_from_orders([_order(1, p=0.6, stake=6.0, fees=0.12)])
    assert bet.breakeven == pytest.approx(0.612)


def test_a_push_counts_in_roi_but_not_in_win_rate():
    s = R.summarize(R.bets_from_orders([_order(1), _order(2, outcome="lost"), _order(3, outcome="push")]))
    assert s["bets"] == 3
    assert s["win_pct"] == 50.0
    assert s["staked"] == 3.0


# --- the statistics -------------------------------------------------------------


def test_excess_wins_are_over_the_breakeven_of_the_prices_paid():
    # Four coin-flip prices, three wins: excess +1.0 over 2.0 expected; z = 1 / sqrt(4 x 0.25) = 1.
    s = R.summarize(R.bets_from_orders([_order(i, outcome="won" if i < 3 else "lost") for i in range(4)]))
    assert s["excess_wins"] == pytest.approx(1.0)
    assert s["excess_z"] == pytest.approx(1.0)
    assert s["win_pct"] == 75.0 and s["breakeven_win_pct"] == 50.0


def test_a_good_win_rate_can_still_lose_money():
    # 60% wins at 0.65 prices: the instrument the /portfolio pivot shows is the wrong one.
    orders = [_order(i, p=0.65, outcome="won" if i % 5 < 3 else "lost") for i in range(100)]
    s = R.summarize(R.bets_from_orders(orders))
    assert s["win_pct"] == 60.0
    assert s["roi_pct"] < 0 and s["excess_wins"] < 0


def test_roi_se_is_clustered_by_event():
    outcomes = ["won", "won", "lost", "lost"]
    apart = R.summarize(R.bets_from_orders([_order(i, outcome=o) for i, o in enumerate(outcomes)]))
    # Same outcomes, but each game carries two bets that won or lost together.
    together = R.summarize(
        R.bets_from_orders([_order(i, outcome=o, event=f"g{i // 2}") for i, o in enumerate(outcomes)])
    )
    assert apart["roi_pct"] == together["roi_pct"] == 0.0
    assert apart["events"] == 4 and together["events"] == 2
    assert together["roi_se_pct"] > apart["roi_se_pct"]
    assert together["roi_se_pct"] == pytest.approx(100 * math.sqrt(2 * 2.0 ** 2) / 4.0, abs=0.01)


def test_fees_are_reported_and_backed_out():
    s = R.summarize(R.bets_from_orders([_order(1, stake=10.0, fees=0.2), _order(2, stake=10.0, fees=0.2, outcome="lost")]))
    assert s["fees"] == 0.4
    assert s["fee_pct_of_stake"] == 2.0
    assert s["roi_before_fees_pct"] == pytest.approx(s["roi_pct"] + 2.0)


# --- CLV ------------------------------------------------------------------------


def test_clv_is_recomputed_from_prices_and_netted_of_the_fee():
    # A stale stamped -34 (todo #719) is ignored; 0.60 -> 0.62 is +2.0 pp gross; the fee is 1.1 pp.
    (bet,) = R.bets_from_orders([_order(1, p=0.60, stake=6.0, fees=0.11, close=0.62)])
    assert bet.scope == "same_book"  # absent scope is same-book (order_clv._scope_of)
    assert bet.clv_gross == pytest.approx(2.0)
    assert bet.fee_pp == pytest.approx(1.1)
    assert bet.clv_net == pytest.approx(0.9)


def test_an_unknown_fee_gives_gross_clv_and_no_net():
    (bet,) = R.bets_from_orders([_order(1, p=0.60, stake=6.0, fees=None, close=0.62)])
    assert bet.clv_gross == pytest.approx(2.0)
    assert bet.clv_net is None


def test_clv_is_reported_per_scope_never_blended():
    orders = [_order(1, close=0.52), _order(2, close=0.56, scope="different_book_close")]
    clv = R.clv_summary(R.bets_from_orders(orders))
    assert set(clv) == {"same_book", "different_book_close"}
    assert clv["same_book"]["clv_gross_pp"] == pytest.approx(2.0)
    assert clv["different_book_close"]["clv_gross_pp"] == pytest.approx(6.0)


def test_close_calibration_says_when_the_close_overprices_our_sides():
    # The close implies 0.80 on every side; they win half the time: wins - close = -30 pp.
    orders = [_order(i, close=0.80, outcome="won" if i % 2 else "lost") for i in range(40)]
    clv = R.clv_summary(R.bets_from_orders(orders))["same_book"]
    assert clv["wins_minus_close_pp"] == pytest.approx(-30.0)
    assert clv["wins_minus_close_z"] < -2


# --- quartiles and the gate -----------------------------------------------------


def test_stake_quartiles_partition_the_bets_and_the_dollars():
    orders = [_order(i, stake=1.0 + i, outcome="won" if i % 2 else "lost") for i in range(10)]
    quartiles = R.stake_quartiles(R.bets_from_orders(orders))
    assert [q["quartile"] for q in quartiles] == ["Q1", "Q2", "Q3", "Q4"]
    assert sum(q["bets"] for q in quartiles) == 10
    assert sum(q["dollar_share_pct"] for q in quartiles) == pytest.approx(100.0, abs=0.2)
    assert quartiles[-1]["stake_from"] >= quartiles[0]["stake_to"]


def _winning_book(n_events=850):
    # One bet per game at 0.50, 60% won, closing at 0.60 (so the close is calibrated on these sides),
    # equal stakes so the top quartile is the same bets as the book.
    return [
        _order(i, p=0.50, stake=1.0, fees=0.0, close=0.60, outcome="won" if i % 5 < 3 else "lost")
        for i in range(n_events)
    ]


def test_gate_conditions_pass_on_a_clearly_winning_calibrated_book():
    g = R.gate(R.bets_from_orders(_winning_book()))
    names = {c["name"][0]: c for c in g["conditions"]}
    assert names["1"]["pass"] and names["2"]["pass"] and names["3"]["pass"]
    assert g["status"].startswith("ADOPTED")


def test_gate_refuses_too_few_events_whatever_the_results():
    g = R.gate(R.bets_from_orders(_winning_book(n_events=200)))
    names = {c["name"][0]: c for c in g["conditions"]}
    assert not names["1"]["pass"] and not g["all_pass"]


def test_gate_refuses_an_uncalibrated_close():
    # Same winning results, but the close implies 0.85: positive CLV against an optimistic close is not evidence.
    orders = [
        _order(i, p=0.50, stake=1.0, close=0.85, outcome="won" if i % 5 < 3 else "lost") for i in range(850)
    ]
    names = {c["name"][0]: c for c in R.gate(R.bets_from_orders(orders))["conditions"]}
    assert not names["3"]["pass"]


def test_gate_refuses_when_the_biggest_stakes_lose():
    small = [_order(i, stake=1.0, outcome="won") for i in range(30)]
    big = [_order(100 + i, stake=10.0, outcome="lost") for i in range(10)]
    names = {c["name"][0]: c for c in R.gate(R.bets_from_orders(small + big))["conditions"]}
    assert not names["4"]["pass"]


# --- windows and the CLI --------------------------------------------------------


def test_default_windows_end_at_as_of():
    windows = {name: (a, b) for name, a, b in R.default_windows("2026-11-15")}
    assert windows["last 30"] == ("2026-10-17", "2026-11-15")
    assert windows["last 7"] == ("2026-11-09", "2026-11-15")
    assert windows["month to date"] == ("2026-11-01", "2026-11-15")


def test_since_makes_one_window_and_the_gate_reads_it():
    orders = [_order(1, date="2026-10-30"), _order(2, date="2026-11-05", outcome="lost")]
    report = R.build_report(orders, as_of="2026-11-15", since="2026-11-03")
    assert [w["window"] for w in report["windows"]] == ["since 2026-11-03"]
    assert report["windows"][0]["bets"] == 1
    assert report["focus"]["from"] == "2026-11-03"


def test_main_reads_a_saved_payload_and_writes_json(tmp_path, capsys):
    payload = tmp_path / "live.json"
    payload.write_text(json.dumps({"orders": [_order(i, outcome="won" if i % 2 else "lost") for i in range(8)]}))
    out = tmp_path / "report.json"
    assert R.main(["--payload-json", str(payload), "--as-of", "2026-11-15", "--no-clock", "--json", str(out)]) == 0
    text = capsys.readouterr().out
    assert "LIVE BOOK EDGE READOUT" in text and "SCALE-UP GATE" in text
    report = json.loads(out.read_text())
    assert report["orders_read"] == 8
    assert report["windows"][1]["window"] == "last 30" and report["windows"][1]["bets"] == 8


# --- the gate's clock (user 11-16: "Any betting change") ------------------------------

_CLOCK = {"start": "2026-11-17T00:04:38Z", "change_id": "BC-017", "what": "a change", "pending": False, "unclassified": 0}


def _timed(i, submitted, **kw):
    return _order(i, submitted_at=submitted, date="2026-11-17", **kw)


def test_utc_reads_the_venue_nanosecond_stamps():
    assert R._utc("2026-11-16T04:24:35.729507346Z").microsecond == 729507
    assert R._utc("2026-11-17T00:04:38Z").hour == 0 and R._utc("") is None and R._utc("nope") is None


def test_the_clock_moves_the_gate_onto_bets_submitted_after_the_load():
    orders = [
        _timed(1, "2026-11-17T00:04:37.999Z"),  # one instant before the load: old rules
        _timed(2, "2026-11-17T00:04:38Z"),
        _timed(3, "2026-11-17T03:00:00.123456789Z", outcome="lost"),
    ]
    off = R.build_report(orders, as_of="2026-11-17")
    on = R.build_report(orders, as_of="2026-11-17", clock=_CLOCK)
    assert off["clock"] is None and off["focus"]["window"] == "last 30"
    assert on["focus"]["window"] == "since BC-017"
    assert on["clock"]["events"] == 2 and on["clock"]["need"] == 800
    assert on["windows"][-1]["window"] == "since BC-017" and on["windows"][-1]["bets"] == 2
    assert on["gate"]["conditions"][0]["reading"].startswith("2 events")  # off != on
    assert off["gate"]["conditions"][0]["reading"].startswith("3 events")


def test_a_bet_with_no_submit_time_never_counts():
    report = R.build_report([_timed(1, ""), _timed(2, "2026-11-17T01:00:00Z")], as_of="2026-11-17", clock=_CLOCK)
    assert report["clock"]["events"] == 1 and report["clock"]["bets_without_submit_time"] == 1


def test_since_wins_over_the_clock():
    report = R.build_report([_timed(1, "2026-11-17T01:00:00Z")], as_of="2026-11-17", since="2026-11-01", clock=_CLOCK)
    assert report["clock"] is None and report["focus"]["window"] == "since 2026-11-01"


_REGISTER = """Classified from: `2026-11-16T18:15:00Z`

| id | kind | loaded_at (UTC) | what changed | deploys.md entry | lane |
|---|---|---|---|---|---|
| BC-001 | yes | 2026-11-17T00:04:38Z | a change | 2026-11-17T00:04:20Z | l |
"""


_DEPLOYS = "## 2026-11-17 00:04:20Z -- FLEET ff a -> b + refresh-worker TERM\n"


def _main_files(tmp_path, register_text, deploys_text=_DEPLOYS):
    payload = tmp_path / "live.json"
    payload.write_text(json.dumps({"orders": [_timed(1, "2026-11-17T01:00:00Z"), _timed(2, "2026-11-16T12:00:00Z")]}))
    reg = tmp_path / "betting_changes.md"
    reg.write_text(register_text, encoding="utf-8")
    dep = tmp_path / "deploys.md"
    dep.write_text(deploys_text, encoding="utf-8")
    return ["--payload-json", str(payload), "--as-of", "2026-11-17", "--register", str(reg), "--deploys", str(dep)]


def test_main_reads_the_register_and_prints_the_clock(tmp_path, capsys):
    out = tmp_path / "r.json"
    assert R.main([*_main_files(tmp_path, _REGISTER), "--json", str(out)]) == 0
    text = capsys.readouterr().out
    assert "CLOCK" in text and "1 of 800 events" in text and "WARNING" not in text
    assert json.loads(out.read_text())["clock"]["change_id"] == "BC-001"


def test_main_says_when_a_load_is_pending_or_a_deploy_is_unclassified(tmp_path, capsys):
    pending = _REGISTER.replace("2026-11-17T00:04:38Z", "pending:refresh-worker")
    deploys = "## 2026-11-17 02:00:00Z -- FLEET ff b -> c + live-odds-worker TERM\n"
    assert R.main(_main_files(tmp_path, pending, deploys)) == 0
    text = capsys.readouterr().out
    assert "PENDING a load, so the count is 0" in text
    assert "WARNING: 1 deploys.md load(s)" in text


def test_main_without_a_register_reads_the_last_30_days(tmp_path, capsys):
    args = _main_files(tmp_path, _REGISTER)
    args[args.index("--register") + 1] = str(tmp_path / "missing.md")
    assert R.main(args) == 0
    assert "FOCUS: last 30" in capsys.readouterr().out


# --- the pinned fleet reading ----------------------------------------------------


@pytest.mark.skipif(
    not os.environ.get("SYNDICATE_EDGE_READOUT_PAYLOAD"),
    reason="needs the saved 2026-11-16 fleet payload (not committed: public repo)",
)
def test_reproduces_the_2026_11_16_fleet_readout():
    payload = json.loads(Path(os.environ["SYNDICATE_EDGE_READOUT_PAYLOAD"]).read_text(encoding="utf-8"))
    report = R.build_report(payload["orders"], as_of="2026-11-15")
    last30 = next(w for w in report["windows"] if w["window"] == "last 30")
    assert (last30["bets"], last30["events"], last30["staked"], last30["pnl"]) == (1526, 641, 3006.48, -218.64)
    assert (last30["roi_pct"], last30["roi_se_pct"]) == (-7.27, 2.84)
    assert (last30["excess_wins"], last30["excess_z"]) == (-32.5, -1.72)
    same = report["clv"]["same_book"]
    assert (same["clv_gross_pp"], same["fee_pp"], same["clv_net_pp"]) == (1.32, 1.63, -0.3)
    assert report["stake_quartiles"][-1]["roi_pct"] == -9.19
    assert not report["gate"]["all_pass"]
