"""Per-game concentration on LIVE venue orders (lane live-event-concentration, todo #711).

Reachability first (T0: off != on, through the real executor loop), then the
rule's edges. The findings are in `.syndicate/findings_2026-10-20_live_event_concentration.md`.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared import event_concentration as EC
from syndicate.features.shared import execution_ledger as L

_EVENT = "evt-nba-okc-sas"
_COMMENCE = "2026-10-24T23:30:00Z"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_REPORTS_ROOT", str(tmp_path))
    for key in (
        "SYNDICATE_EXECUTION_ENABLED",
        "SYNDICATE_EXECUTION_MODE",
        "SYNDICATE_EXECUTION_LIVE_ARMED",
        "SYNDICATE_EXECUTION_VENUE",
        "SYNDICATE_REFRESH_STATE_BACKEND",
        "SYNDICATE_EXECUTION_CROSS_SLATE_DEDUPE",
        "SYNDICATE_EXECUTION_BALANCE_CAPS",
        EC.MODE_ENV,
        EC.MAX_DOLLARS_ENV,
    ):
        monkeypatch.delenv(key, raising=False)
    yield


def _pos(key, *, market="spreads_alt", side="away", line=20.5, price=-1329.0, stake=10.0,
         player=None, event=_EVENT, ticker="KXNBAGAME-26OCT24OKCSAS-OKC"):
    return {
        "position_key": key,
        "event_id": event,
        "sport": "nba",
        "kind": "prop" if player else "game",
        "market": market,
        "segment": None,
        "side": side,
        "line": line,
        "player_name": player,
        "price": price,
        "stake_dollars": stake,
        "home_team": "San Antonio Spurs",
        "away_team": "Oklahoma City Thunder",
        "commence_time": _COMMENCE,
        "venue_ticker": ticker,
        "price_source": "venue_feed",
        "ev_pct": 2.0,
    }


def _arm_live(monkeypatch):
    monkeypatch.setenv("SYNDICATE_EXECUTION_ENABLED", "1")
    monkeypatch.setenv("SYNDICATE_EXECUTION_MODE", "live")
    monkeypatch.setenv("SYNDICATE_EXECUTION_LIVE_ARMED", "1")
    monkeypatch.setenv("SYNDICATE_EXECUTION_VENUE", "kalshi")
    monkeypatch.setenv("SYNDICATE_EXECUTION_MAX_ORDER_DOLLARS", "1000")
    monkeypatch.setenv("SYNDICATE_EXECUTION_MAX_DAY_DOLLARS", "10000")
    monkeypatch.setenv("SYNDICATE_EXECUTION_MAX_DAY_ORDERS", "100")
    # The Kalshi ticker-date guard is another lane's; keep it out of this test's way.
    monkeypatch.setattr("pipeline.execute_portfolio._kalshi_pregame_only_enabled", lambda: False, raising=False)


def _passes(monkeypatch, plans, *, mode=None, cap=None):
    """Run the live executor once per plan, same slate. Returns (results, sent requests)."""
    from pipeline import execute_portfolio as runner

    _arm_live(monkeypatch)
    if mode is not None:
        monkeypatch.setenv(EC.MODE_ENV, mode)
    if cap is not None:
        monkeypatch.setenv(EC.MAX_DOLLARS_ENV, str(cap))
    sent: list = []

    def submitter(request):
        sent.append(request)
        return {"status": "filled", "fill_price": 0.5, "fill_stake_dollars": request.requested_stake_dollars}

    monkeypatch.setattr(runner, "_venue_submitter", lambda venue: submitter)
    results = []
    for positions in plans:
        plan = {"positions": positions, "plan_kind": "live"}
        monkeypatch.setattr("pipeline.portfolio_commit.read_live_portfolio_plan_for_venue", lambda d, v, p=plan: p)
        monkeypatch.setattr("pipeline.portfolio_commit.read_portfolio_plan_for_venue", lambda d, v, p=plan: p)
        results.append(runner.run_execution("2026-10-24", venue_scope="kalshi"))
    return results, sent


# --------------------------------------------------------------------------
# T0 -- reachability: off != on, across two executor passes (the OKC@SAS shape)
# --------------------------------------------------------------------------

_PASS1 = [_pos("k-okc-20.5")]
_PASS2 = [_pos("k-sas-17.5", side="home", line=17.5, price=-809.0, stake=10.0,
               ticker="KXNBAGAME-26OCT24OKCSAS-SAS")]


def test_T0_off_a_second_leg_on_the_same_axis_is_sent(monkeypatch):
    results, sent = _passes(monkeypatch, [_PASS1, _PASS2])
    assert [r["placed"] for r in results] == [1, 1], results
    assert len(sent) == 2
    assert EC.REFUSAL_AXIS_HELD not in results[1]["refused"]


def test_T0_on_the_second_leg_is_refused_and_nothing_is_written(monkeypatch, capsys):
    results, sent = _passes(monkeypatch, [_PASS1, _PASS2], mode="on")
    assert results[0]["placed"] == 1
    assert results[1]["placed"] == 0
    assert results[1]["refused"] == {EC.REFUSAL_AXIS_HELD: 1}
    assert len(sent) == 1
    live = [o for o in L._load()["orders"] if o.get("mode") == "live"]
    assert len(live) == 1 and live[0]["position_key"] == "k-okc-20.5"
    assert "REFUSED_SAME_AXIS_HELD" in capsys.readouterr().out


def test_T0_shadow_logs_and_changes_nothing(monkeypatch, capsys):
    results, sent = _passes(monkeypatch, [_PASS1, _PASS2], mode="shadow")
    assert [r["placed"] for r in results] == [1, 1]
    out = capsys.readouterr().out
    assert "CONCENTRATION_SHADOW would=refuse reason=axis_held_live" in out


def test_T0_an_unknown_mode_is_off(monkeypatch):
    monkeypatch.setenv(EC.MODE_ENV, "onn")
    assert EC.mode() == "off" and EC.mode_invalid() == "onn"


def test_T0_a_rerun_of_the_same_bet_stays_a_duplicate(monkeypatch):
    results, sent = _passes(monkeypatch, [_PASS1, _PASS1], mode="on")
    assert results[1]["duplicates"] == 1
    assert results[1]["refused"] == {}
    assert len(sent) == 1


# --------------------------------------------------------------------------
# T1 -- the held predicate is the ledger's, not "any row"
# --------------------------------------------------------------------------


def _row(key, *, status="filled", mode="live", venue="kalshi", event=_EVENT, market="spreads_alt",
         side="away", stake=10.0, player=None, idem=None):
    return {"position_key": key, "status": status, "mode": mode, "venue": venue, "event_id": event,
            "market": market, "side": side, "player_name": player, "requested_stake_dollars": stake,
            "idempotency_key": idem or ("a" * 24)}


def test_T1_rejected_paper_other_venue_other_event_and_exit_rows_are_not_held():
    exit_key = "x" + "0" * 23
    rows = [
        _row("a", status="rejected"),
        _row("b", mode="paper"),
        _row("c", venue="polymarket"),
        _row("d", event="other"),
        _row("e", idem=exit_key),
        _row("f"),
        _row("g", status="submitted"),
    ]
    held = EC.held_live_orders(rows, event_id=_EVENT)
    # POOLED: the Polymarket row on the same game counts too
    assert [o["position_key"] for o in held] == ["c", "f", "g"]
    assert [o["position_key"] for o in EC.held_live_orders(rows, event_id=_EVENT, venue="kalshi")] == ["f", "g"]


# --------------------------------------------------------------------------
# T6 -- the held book is POOLED across live venues (SF@ATL under 49.5, Kalshi 21:36Z + Polymarket 02:00:59Z, 10-20)
# --------------------------------------------------------------------------


def _sf_atl(key, *, side="under", line=49.5, stake=5.42, price=113.0):
    return _pos(key, market="totals", side=side, line=line, price=price, stake=stake, event="evt-nfl-sf-atl",
                ticker="KXNFLTOTAL-26OCT24SFATL-50")


def _relabel_live_rows_as_polymarket():
    state = L._load()
    for order in state["orders"]:
        if order.get("mode") == "live":
            order["venue"] = "polymarket"
    L._persist(state)


def test_T6_a_bet_held_on_the_other_venue_blocks_the_same_game_outcome(monkeypatch, capsys):
    # pass 1 places the under on one venue; it is then held as a POLYMARKET row
    results, sent = _passes(monkeypatch, [[_sf_atl("pm-under-49.5")]], mode="on")
    assert results[0]["placed"] == 1
    _relabel_live_rows_as_polymarket()
    # pass 2 on Kalshi: same game, same outcome (a different position_key, as the venue is in the key)
    results2, sent2 = _passes(monkeypatch, [[_sf_atl("k-under-49.5", stake=0.48, price=108.0)]], mode="on")
    assert results2[0]["refused"] == {EC.REFUSAL_AXIS_HELD: 1}
    assert sent2 == []  # nothing sent on pass 2
    assert "REFUSED_SAME_AXIS_HELD" in capsys.readouterr().out


def test_T6_off_the_cross_venue_duplicate_is_sent(monkeypatch):
    _passes(monkeypatch, [[_sf_atl("pm-under-49.5")]])
    _relabel_live_rows_as_polymarket()
    results2, sent2 = _passes(monkeypatch, [[_sf_atl("k-under-49.5", stake=0.48, price=108.0)]])
    assert results2[0]["placed"] == 1


def test_T6_opposite_sides_across_venues_and_the_cap_pool_too():
    # OKC@SAS 02:00Z: Polymarket over 231.5 held, a Kalshi under 229.5 candidate -> same axis, refused
    held = [_row("pm-over", venue="polymarket", market="totals", side="over", stake=0.49)]
    under = {"position_key": "k-under", "market": "totals", "side": "under", "requested_stake_dollars": 5.0,
             "requested_price": 108.0}
    assert EC.verdict_for(under, EC.held_live_orders(held, event_id=_EVENT), cap=15.0).reason == EC.REFUSAL_AXIS_HELD
    # dollars pool: $12 held on Polymarket leaves $3 for a Kalshi prop on the same game
    held2 = [_row("pm-ml", venue="polymarket", market="h2h", stake=12.0)]
    prop = {"position_key": "k-prop", "market": "player_points", "player_name": "X", "side": "over",
            "requested_stake_dollars": 8.0, "requested_price": -150.0}
    v = EC.verdict_for(prop, EC.held_live_orders(held2, event_id=_EVENT), cap=15.0)
    assert (v.action, v.stake) == ("trim", 3.0)


def test_T1_held_on_the_axis_refuses_any_other_line_or_side():
    request = {"position_key": "new", "market": "spreads", "side": "home", "requested_stake_dollars": 5.0,
               "requested_price": 117.0}
    v = EC.verdict_for(request, [_row("held", market="spreads_alt", side="away", stake=0.5)], cap=15.0)
    assert (v.action, v.reason, v.blocking_key) == ("refuse", EC.REFUSAL_AXIS_HELD, "held")


# --------------------------------------------------------------------------
# T2 -- the per-game cap trims, then refuses below one contract
# --------------------------------------------------------------------------


def test_T2_cap_trims_to_room_across_passes(monkeypatch, capsys):
    prop = _pos("k-kj-threes", market="player_threes", side="over", line=0.5, price=-144.0, stake=8.0,
                player="Keldon Johnson", ticker="KXNBA3PT-26OCT24OKCSAS-KJ")
    results, sent = _passes(monkeypatch, [_PASS1, [prop]], mode="on", cap=15)
    assert len(sent) == 2
    assert sent[1].requested_stake_dollars == pytest.approx(5.0)
    assert results[1]["trimmed"] == 1
    assert "TRIMMED_TO_EVENT_CAP placed_at=5.00" in capsys.readouterr().out


def test_T2_in_one_pass_the_second_leg_sees_the_first(monkeypatch):
    prop = _pos("k-kj-threes", market="player_threes", side="over", line=0.5, price=-144.0, stake=8.0,
                player="Keldon Johnson", ticker="KXNBA3PT-26OCT24OKCSAS-KJ")
    results, sent = _passes(monkeypatch, [[_PASS1[0], prop]], mode="on", cap=15)
    assert [r.requested_stake_dollars for r in sent] == [10.0, 5.0]


def test_T2_room_below_one_contract_refuses():
    request = {"position_key": "new", "market": "player_points", "player_name": "X", "side": "over",
               "requested_stake_dollars": 5.0, "requested_price": -150.0}
    v = EC.verdict_for(request, [_row("held", stake=14.60)], cap=15.0)
    # room $0.40 < one contract at -150 ($0.60)
    assert (v.action, v.reason) == ("refuse", EC.REFUSAL_EVENT_CAP)
    v2 = EC.verdict_for({**request, "requested_price": 300.0}, [_row("held", stake=14.60)], cap=15.0)
    # one contract at +300 is $0.25 -- fits, so it is trimmed to the room
    assert (v2.action, v2.stake) == ("trim", 0.40)


# --------------------------------------------------------------------------
# T3 -- independence: one leg per game is never touched (every line its own decision)
# --------------------------------------------------------------------------


def test_T3_one_leg_per_event_is_identical_on_and_off(monkeypatch, tmp_path):
    markets = ["h2h", "spreads", "totals", "player_points", "team_totals"]
    plan = [
        _pos(f"k{i}", event=f"evt-{i}", market=markets[i % 5], side="over" if i % 2 else "home",
             line=1.5 + i, price=-150.0 - i, stake=9.0 + i, player=("P%d" % i) if markets[i % 5].startswith("player") else None,
             ticker=f"KXNBAGAME-26OCT24G{i:02d}-AAA")
        for i in range(20)
    ]
    runs = {}
    for label, mode in (("off", None), ("on", "on")):
        root = tmp_path / label
        root.mkdir()
        monkeypatch.setenv("SYNDICATE_REPORTS_ROOT", str(root))
        if mode is None:
            monkeypatch.delenv(EC.MODE_ENV, raising=False)
        results, sent = _passes(monkeypatch, [plan], mode=mode, cap=15)
        runs[label] = [(r.position_key, r.requested_stake_dollars) for r in sent]
        assert results[0]["refused"] == {}, results[0]["refused"]
    assert len(runs["off"]) == 20
    assert runs["on"] == runs["off"]


def test_T3_property_the_only_leg_of_an_event_is_never_refused_or_trimmed():
    for market in ("h2h", "spreads_alt", "totals_alt", "player_threes", "team_totals", "btts", "outs"):
        for stake in (0.5, 5.0, 10.0, 15.0):
            v = EC.verdict_for({"position_key": "k", "market": market, "side": "over",
                                "requested_stake_dollars": stake, "requested_price": -150.0}, [], cap=15.0)
            assert v.action == "pass", (market, stake, v)


# --------------------------------------------------------------------------
# T4 -- the axis classifier gate: every market a venue plan can carry lands on a named axis
# --------------------------------------------------------------------------


def _known_markets() -> set[str]:
    from syndicate.features.shared.kalshi_orders import _TEAM_SIDED_MARKETS
    from syndicate.features.shared.polymarket_board_join import _JOINABLE_BOARD_MARKETS

    seen_on_ledgers_2026_10 = {  # every market string on the live + paper ledgers 10-02..10-20 (probe conc_probe2)
        "h2h", "h2h_3_way", "spreads", "spreads_alt", "totals", "totals_alt", "team_totals",
        "player_points", "player_rebounds", "player_assists", "player_threes", "player_steals",
        "player_points_rebounds_assists", "player_rebounds_assists", "batter_hits", "batter_rbis",
        "batter_total_bases", "batter_hits_runs_rbis", "outs", "totals_1st_5_innings", "h2h_q1",
    }
    return set(_TEAM_SIDED_MARKETS) | set(_JOINABLE_BOARD_MARKETS) | seen_on_ledgers_2026_10


def test_T4_no_known_market_falls_through_to_other():
    other = sorted(m for m in _known_markets() if EC.axis_kind(m) == "other")
    assert other == [], other


def test_T4_axes_group_what_rides_together_and_split_what_does_not():
    a = lambda **k: EC.axis_key({"segment": None, **k})
    assert a(market="spreads_alt", side="away") == a(market="h2h", side="home") == "margin|full"
    assert a(market="totals", side="under") == a(market="totals_alt", side="over") == "total|full"
    assert a(market="totals_1st_5_innings") != a(market="totals")
    assert a(market="player_threes", player_name="A") != a(market="player_threes", player_name="B")
    assert a(market="player_threes", player_name="A") != a(market="player_points", player_name="A")
    assert a(market="team_totals", side="home") != a(market="team_totals", side="away")


# --------------------------------------------------------------------------
# T5 -- replay of the 10-20 live Kalshi book in submitted_at order (ledger read 2026-10-21 00:5xZ)
# --------------------------------------------------------------------------

_REPLAY = [  # (event, market, side, line, player, requested $, held (fill) $, price), submitted_at order
    ("mtsu", "totals", "under", 44.5, None, 5.46, 5.17, 113.0),
    ("okc", "player_points", "over", 9.5, "Keldon Johnson", 0.41, 0.39, 156.0),
    ("mtsu", "totals", "under", 45.5, None, 0.50, 0.48, 108.0),
    ("okc", "spreads_alt", "away", 20.5, None, 10.00, 10.00, -1329.0),
    ("okc", "player_threes", "under", 1.5, "Jalen Williams", 0.63, 0.63, -156.0),
    ("okc", "player_steals", "over", 0.5, "Stephon Castle", 0.66, 0.65, -178.0),
    ("okc", "player_steals", "over", 0.5, "Victor Wembanyama", 0.67, 0.67, -186.0),
    ("most", "spreads", "home", -3.5, None, 5.58, 5.50, 117.0),
    ("okc", "player_threes", "over", 0.5, "Keldon Johnson", 6.73, 6.49, -144.0),
    ("most", "spreads", "away", 2.5, None, 0.48, 0.41, 117.0),
    ("okc", "player_assists", "over", 1.5, "Devin Vassell", 0.67, 0.66, -186.0),
    ("okc", "totals", "over", 231.5, None, 0.50, 0.48, 108.0),
    ("okc", "spreads_alt", "home", 17.5, None, 10.00, 9.79, -809.0),
    ("okc", "player_threes", "over", 1.5, "Devin Vassell", 0.71, 0.66, -194.0),
    ("okc", "player_rebounds", "over", 3.5, "Cason Wallace", 0.50, 0.45, 122.0),
    ("okc", "spreads_alt", "away", 16.5, None, 0.93, 0.89, -809.0),
    ("okc", "spreads_alt", "away", -3.5, None, 0.46, 0.41, 144.0),
]


def test_T5_replay_of_the_10_20_book():
    """New orders ask their REQUESTED stake; held legs count their FILLED stake (`_stake`)."""
    held: dict[str, list] = {}
    outcome = []
    for i, (event, market, side, line, player, asked, filled, price) in enumerate(_REPLAY):
        req = {"position_key": f"r{i}", "market": market, "side": side, "player_name": player,
               "requested_stake_dollars": asked, "requested_price": price}
        v = EC.verdict_for(req, held.get(event, []), cap=15.0)
        outcome.append((v.action, v.reason, v.stake))
        if v.action in ("pass", "trim"):
            fill = filled if v.action == "pass" else v.stake
            held.setdefault(event, []).append({**_row(f"r{i}", market=market, side=side, player=player,
                                                      stake=v.stake, event=event), "fill_stake_dollars": fill})
    r1 = [i for i, o in enumerate(outcome) if o[1] == EC.REFUSAL_AXIS_HELD]
    cap = [i for i, o in enumerate(outcome) if o[1] == EC.REFUSAL_EVENT_CAP]
    trims = [(i, o[2]) for i, o in enumerate(outcome) if o[0] == "trim"]
    # R1: MTSU u45.5, MoSt +2.5, SAS +17.5, OKC +16.5, OKC -3.5 (held-first keeps OKC +20.5 @ -1329)
    assert r1 == [2, 9, 12, 15, 16]
    assert round(sum(_REPLAY[i][6] for i in r1), 2) == 11.98
    # R2 at $15: OKC@SAS holds $12.34 filled by 21:42Z; Keldon Johnson threes trimmed to the $2.66 room,
    # then the next four OKC@SAS legs are refused
    assert trims == [(8, 2.66)]
    assert cap == [10, 11, 13, 14]
    assert round(sum(o["fill_stake_dollars"] for o in held["okc"]), 2) == 15.00
    kept = sum(o["fill_stake_dollars"] for rows in held.values() for o in rows)
    total = sum(r[6] for r in _REPLAY)
    assert round(total, 2) == 43.73
    assert round(kept, 2) == 25.67
    # the 17 other 10-20 live Kalshi positions ($29.30) are single-leg games: the day goes $73.03 -> $54.97
