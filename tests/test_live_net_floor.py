"""The per-venue LIVE net-of-fee floor (user 2026-10-21, lane venue-native-selection).

"Yes: build the per-venue live net floor behind SYNDICATE_LIVE_NET_FLOOR_<VENUE>
(absent = today), with reachability tests, merged to origin/main."
Evidence: .syndicate/findings_2026-10-20_venue_native_selection.md.
"""

from __future__ import annotations

import pytest

from pipeline import portfolio_commit as pc
from syndicate.features.shared.portfolio_commit import commit_portfolio
from syndicate.features.shared.portfolio_settings import PortfolioSettings

_TICKER = "KXNCAAFTOTAL-26OCT20MTUFIU-45"
_DATE = "2026-10-20"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_REPORTS_ROOT", str(tmp_path))
    monkeypatch.setenv("SYNDICATE_REFRESH_STATE_BACKEND", "file")
    (tmp_path / "intelligence").mkdir(parents=True, exist_ok=True)
    for name in ("SYNDICATE_LIVE_NET_FLOOR_KALSHI", "SYNDICATE_LIVE_NET_FLOOR_POLYMARKET", pc.LIVE_EV_FLOOR_ENV,
                 "SYNDICATE_COMPOUNDING_BANKROLL", "SYNDICATE_LIVE_STAKE_BAND", "SYNDICATE_LIVE_SMALL_EDGE_FRACTION",
                 "SYNDICATE_EXECUTION_MODE"):
        monkeypatch.delenv(name, raising=False)
    yield


def _settings():
    return PortfolioSettings(bankroll_units=1000.0, max_slate_exposure_fraction=1.0, min_ev_pct=-100.0,
                             max_positions=50, min_stake_units=0.0)


def _row(event_id, net, *, side="home", market="h2h", line=None, venue="kalshi", suggested=False):
    """An EV-only EXTRA row (tagged `live_ev_floor: 0`, as `live_ev_floor_rows` does) unless `suggested`."""
    row = {
        "sport": "ncaaf", "event_id": event_id, "kind": "game", "market": market, "segment": "full_game",
        "line": line, "player_name": None, "home_team": "Home", "away_team": "Away",
        "commence_time": "2026-10-20T23:05:00Z", "side": side,
        "quote": {"price": -110, "bookmaker": venue}, "ev_pct": 4.5, "model_edge_pct": 3.2,
        "score": {"score": 5.0, "price_reliability": 0.82}, "venue": venue,
        "price_source": "venue_feed", "venue_ticker": _TICKER,
    }
    if net is not None:
        row["ev_pct_net_of_fee"] = net
    if not suggested:
        row["live_ev_floor"] = 0
    return row


def _plan(rows, venue="kalshi"):
    return pc.commit_live_venue_plan(rows, selected_date=_DATE, settings=_settings(), venue=venue)


def _events(plan):
    return sorted(p["event_id"] for p in plan["positions"])


def _accounts(plan):
    return sum(plan["refusals"].values()) + len(plan["positions"]) == plan["rows_in"]


# ---- the key ---------------------------------------------------------------


@pytest.mark.parametrize("raw, expected", [
    (None, (None, None)), ("", (None, None)), ("  ", (None, None)),
    ("1.0", (1.0, None)), ("0.5", (0.5, None)), ("0", (0.0, None)), ("-1", (-1.0, None)),
    ("abc", (None, pc.REFUSAL_LIVE_NET_FLOOR_UNREADABLE)), ("nan", (None, pc.REFUSAL_LIVE_NET_FLOOR_UNREADABLE)),
    ("50", (None, pc.REFUSAL_LIVE_NET_FLOOR_UNREADABLE)),
])
def test_key_parsing(monkeypatch, raw, expected):
    if raw is not None:
        monkeypatch.setenv("SYNDICATE_LIVE_NET_FLOOR_KALSHI", raw)
    assert pc.live_net_floor("kalshi") == expected


def test_the_key_is_per_venue(monkeypatch):
    monkeypatch.setenv("SYNDICATE_LIVE_NET_FLOOR_KALSHI", "1.0")
    assert pc.live_net_floor("kalshi") == (1.0, None)
    assert pc.live_net_floor("polymarket") == (None, None)
    assert pc.live_net_floor(None) == (None, None)


# ---- reachability: off != on, and absent IS today ---------------------------


def test_absent_key_is_todays_plan():
    rows = [_row("lo", 0.3), _row("hi", 1.4)]
    plan = _plan(rows)
    assert _events(plan) == ["hi", "lo"]
    assert "live_net_floor" not in plan
    assert pc.REFUSAL_BELOW_LIVE_NET_FLOOR not in plan["refusals"]


def test_off_differs_from_on(monkeypatch):
    rows = [_row("lo", 0.3), _row("hi", 1.4)]
    off = _plan(rows)
    monkeypatch.setenv("SYNDICATE_LIVE_NET_FLOOR_KALSHI", "1.0")
    on = _plan(rows)
    assert _events(off) != _events(on)
    assert _events(on) == ["hi"]
    assert on["refusals"][pc.REFUSAL_BELOW_LIVE_NET_FLOOR] == 1
    assert on["refusals_by_market"][pc.REFUSAL_BELOW_LIVE_NET_FLOOR] == {"h2h": 1}
    assert on["live_net_floor"] == {"venue": "kalshi", "floor_pct": 1.0, "scope": "ev_only_extra",
                                    "rows_checked": 2, "kept": 1, "suggested_exempt": 0,
                                    pc.REFUSAL_BELOW_LIVE_NET_FLOOR: 1}
    assert _accounts(on)


def test_another_venues_key_does_not_touch_this_venue(monkeypatch):
    monkeypatch.setenv("SYNDICATE_LIVE_NET_FLOOR_POLYMARKET", "5.0")
    plan = _plan([_row("lo", 0.3, venue="kalshi")], venue="kalshi")
    assert _events(plan) == ["lo"]
    assert "live_net_floor" not in plan


def test_the_floor_is_inclusive(monkeypatch):
    monkeypatch.setenv("SYNDICATE_LIVE_NET_FLOOR_KALSHI", "1.0")
    assert _events(_plan([_row("edge", 1.0), _row("under", 0.9999)])) == ["edge"]


# ---- fail closed -------------------------------------------------------------


def test_unreadable_key_refuses_every_extra_row_by_name(monkeypatch):
    monkeypatch.setenv("SYNDICATE_LIVE_NET_FLOOR_KALSHI", "one")
    plan = _plan([_row("a", 3.0), _row("b", 0.1)])
    assert plan["positions"] == []
    assert plan["refusals"][pc.REFUSAL_LIVE_NET_FLOOR_UNREADABLE] == 2
    assert plan["live_net_floor"]["error"] == pc.REFUSAL_LIVE_NET_FLOOR_UNREADABLE
    assert _accounts(plan)


def test_a_row_without_net_ev_is_refused_when_the_floor_is_on(monkeypatch):
    rows = [_row("nonet", None), _row("ok", 2.0)]
    assert _events(_plan(rows)) == ["nonet", "ok"]  # off: today's behaviour
    monkeypatch.setenv("SYNDICATE_LIVE_NET_FLOOR_KALSHI", "1.0")
    plan = _plan(rows)
    assert _events(plan) == ["ok"]
    assert plan["refusals"][pc.REFUSAL_NO_VENUE_NET_EV] == 1


# ---- one side per line, at the venue ------------------------------------------


def test_one_side_per_line_keeps_the_higher_net(monkeypatch):
    # The better side FIRST, so "keep the last one seen" cannot pass this.
    rows = [
        _row("g", 2.1, side="under", market="totals", line=50.5),
        _row("g", 1.2, side="over", market="totals", line=50.5),
        _row("g", 1.5, side="over", market="totals", line=52.5),  # a different line: kept
    ]
    monkeypatch.setenv("SYNDICATE_LIVE_NET_FLOOR_KALSHI", "1.0")
    plan = _plan(rows)
    kept = sorted((p["side"], p["line"]) for p in plan["positions"])
    assert kept == [("over", 52.5), ("under", 50.5)]
    assert plan["refusals"][pc.REFUSAL_OTHER_SIDE_BETTER_AT_VENUE] == 1
    assert _accounts(plan)


def test_spread_sides_share_a_line():
    a, b = _row("g", 1.0, side="home", market="spreads", line=-3.5), _row("g", 1.0, side="away", market="spreads", line=3.5)
    assert pc._venue_line_key(a) == pc._venue_line_key(b)


# ---- placeability still decides first; paper books never read the key ----------


def test_unplaceable_rows_keep_their_own_refusal(monkeypatch):
    monkeypatch.setenv("SYNDICATE_LIVE_NET_FLOOR_KALSHI", "1.0")
    agg = _row("agg", 0.2)
    agg["price_source"] = "aggregator"
    plan = _plan([agg, _row("ok", 1.5)])
    assert plan["refusals"][pc.REFUSAL_AGGREGATOR_PRICED] == 1
    assert pc.REFUSAL_BELOW_LIVE_NET_FLOOR not in plan["refusals"]


def test_paper_commit_ignores_the_key(monkeypatch):
    rows = [_row("lo", 0.3), _row("hi", 1.4)]
    before = commit_portfolio(rows, selected_date=_DATE, settings=_settings(), prefer_placeable=True)
    monkeypatch.setenv("SYNDICATE_LIVE_NET_FLOOR_KALSHI", "1.0")
    after = commit_portfolio(rows, selected_date=_DATE, settings=_settings(), prefer_placeable=True)
    assert _events(before) == _events(after) == ["hi", "lo"]


# ---- reachable through the production writer -----------------------------------


def test_the_live_plan_writer_applies_and_logs_the_floor(monkeypatch, capsys):
    monkeypatch.setenv("SYNDICATE_LIVE_NET_FLOOR_KALSHI", "1.0")
    pc._write_live_venue_plan([_row("lo", 0.3), _row("hi", 1.4)], normalized=_DATE, venue="kalshi",
                              settings=_settings(), settled_sample_size_by_sport=None, paper2_plan={},
                              scope_refusals={}, job_state=None)
    from syndicate.features.shared.refresh_state_store import read_json_file

    written = read_json_file(pc.live_portfolio_plan_path_for_venue(_DATE, "kalshi"))
    assert _events(written) == ["hi"]
    assert written["live_net_floor"]["floor_pct"] == 1.0
    assert "[portfolio_commit] LIVE_NET_FLOOR date=2026-10-20 venue=kalshi" in capsys.readouterr().out


# ---- SCOPE: the 0% floor's extra rows only [user 2026-10-21] ----------------------


def test_a_suggested_row_below_the_floor_is_not_refused_but_an_extra_row_is(monkeypatch):
    monkeypatch.setenv("SYNDICATE_LIVE_NET_FLOOR_KALSHI", "1.0")
    plan = _plan([_row("sug", 0.3, suggested=True), _row("extra", 0.3)])
    assert _events(plan) == ["sug"]
    assert plan["refusals"][pc.REFUSAL_BELOW_LIVE_NET_FLOOR] == 1
    assert plan["live_net_floor"]["rows_checked"] == 1
    assert plan["live_net_floor"]["suggested_exempt"] == 1
    assert _accounts(plan)


def test_suggested_rows_get_todays_plan_with_or_without_the_key(monkeypatch):
    rows = [_row("a", 0.2, suggested=True), _row("b", 0.9, suggested=True), _row("c", None, suggested=True)]
    off = _plan(rows)
    monkeypatch.setenv("SYNDICATE_LIVE_NET_FLOOR_KALSHI", "1.0")
    on = _plan(rows)
    assert _events(on) == _events(off) == ["a", "b", "c"]
    assert pc.REFUSAL_BELOW_LIVE_NET_FLOOR not in on["refusals"]
    assert pc.REFUSAL_NO_VENUE_NET_EV not in on["refusals"]


def test_an_unreadable_key_refuses_only_the_extra_rows(monkeypatch):
    monkeypatch.setenv("SYNDICATE_LIVE_NET_FLOOR_KALSHI", "one")
    plan = _plan([_row("sug", 0.3, suggested=True), _row("extra", 3.0)])
    assert _events(plan) == ["sug"]
    assert plan["refusals"][pc.REFUSAL_LIVE_NET_FLOOR_UNREADABLE] == 1


def test_one_side_per_line_never_drops_a_suggested_row(monkeypatch):
    monkeypatch.setenv("SYNDICATE_LIVE_NET_FLOOR_KALSHI", "1.0")
    rows = [_row("g", 2.5, side="over", market="totals", line=50.5),
            _row("g", 1.1, side="under", market="totals", line=50.5, suggested=True)]
    plan = _plan(rows)
    assert sorted(p["side"] for p in plan["positions"]) == ["over", "under"]
