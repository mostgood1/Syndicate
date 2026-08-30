"""The MARKET-basis edge, its four guards, and the gate dimension it needs.

REACHABILITY BEFORE CORRECTNESS (`model_engine_standard.md`): the first test
here is `off != on` -- that a row which produced NO edge before produces one
now. Four inert fixes in one session were caught by that and by nothing else,
and a suite that only checks arithmetic would pass identically against a build
where nothing is ever attached.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from syndicate.features.football import pick_gate
from syndicate.features.shared.market_basis_edge import (
    BASIS,
    MIN_BOOKS_TO_DISPLAY,
    MIN_BOOKS_TO_SERVE,
    MIN_EDGE_PCT_TO_SERVE,
    MODEL_BASIS,
    market_basis_edge,
    summarise,
)

NOW = datetime(2026, 8, 29, 18, 0, 0, tzinfo=timezone.utc)
KICKOFF = NOW + timedelta(hours=3)
STARTED = NOW - timedelta(minutes=1)


def best_side(**overrides):
    """A healthy `best[side]` block, shaped exactly as `book_grid` emits one."""
    payload = {
        "price": 180,
        "bookmaker": "betus",
        "books_quoting": 11,
        "books_quoting_including_stale": 11,
        "edge_vs_consensus_pct": 2.16,
        "suspect_stale": False,
        "all_quotes_stale": False,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------- reachability


def test_market_basis_edge_is_attached_where_the_model_has_none():
    """OFF != ON. The whole point: a row the model gate blanks still gets a number."""
    verdict = market_basis_edge(best_side(), commence_time=KICKOFF, now=NOW)
    assert verdict.edge_pct == 2.16
    assert verdict.displayable is True
    assert verdict.servable is True
    assert verdict.basis == BASIS


def test_book_grid_attaches_market_basis_to_every_quoted_side():
    """The PRODUCER hop, not the pure function. A guard nothing calls is inert.

    Goes through `build_book_grid` itself rather than asserting on a hand-built
    row, because the defect this lane fixes was never in the arithmetic -- the
    number existed and nothing carried it to the surface.
    """
    from syndicate.features.shared.book_grid import build_book_grid

    quotes = []
    for book, away_price, home_price in (
        ("draftkings", 180, -220),
        ("fanduel", 172, -210),
        ("betmgm", 165, -205),
    ):
        for selection, price in (("away", away_price), ("home", home_price)):
            quotes.append(
                {
                    "sport": "ncaaf",
                    "kind": "game",
                    "event_id": "evt-1",
                    "segment": "full",
                    "market": "h2h",
                    "player_name": "",
                    "bookmaker": book,
                    "selection": selection,
                    "price": price,
                    "home_team": "UNLV Rebels",
                    "away_team": "Memphis Tigers",
                    "commence_time": KICKOFF.isoformat().replace("+00:00", "Z"),
                    "book_updated_at": NOW.isoformat().replace("+00:00", "Z"),
                }
            )

    rows = build_book_grid(quotes, now=NOW)
    assert rows, "no grid row built"
    row = rows[0]
    assert row["sides"], "row carries no sides"
    for side in row["sides"]:
        block = row["best"][side]
        assert "market_basis" in block, f"side {side} carries no market_basis"
        assert block["market_basis"]["basis"] == BASIS
        assert block["market_basis"]["anchor_books"] == 3


def test_pregame_guard_reads_this_rows_kickoff_not_the_previous_rows():
    """The bug the first draft of the producer hop had, pinned as a test.

    Two games in one build, one pregame and one already started. If the attach
    reads a `commence_time` that leaks across rows, the started game inherits
    the pregame kickoff and is wrongly displayable -- with no exception and no
    log line.
    """
    from syndicate.features.shared.book_grid import build_book_grid

    quotes = []
    for event, kickoff in (("evt-pre", KICKOFF), ("evt-live", STARTED)):
        for book, away_price, home_price in (
            ("draftkings", 180, -220),
            ("fanduel", 172, -210),
            ("betmgm", 165, -205),
        ):
            for selection, price in (("away", away_price), ("home", home_price)):
                quotes.append(
                    {
                        "sport": "ncaaf",
                        "kind": "game",
                        "event_id": event,
                        "segment": "full",
                        "market": "h2h",
                        "player_name": "",
                        "bookmaker": book,
                        "selection": selection,
                        "price": price,
                        "home_team": f"{event} home",
                        "away_team": f"{event} away",
                        "commence_time": kickoff.isoformat().replace("+00:00", "Z"),
                        "book_updated_at": (NOW - timedelta(minutes=5)).isoformat().replace("+00:00", "Z"),
                    }
                )

    by_event = {row["event_id"]: row for row in build_book_grid(quotes, now=NOW)}
    assert set(by_event) == {"evt-pre", "evt-live"}
    pre = by_event["evt-pre"]["best"][by_event["evt-pre"]["sides"][0]]["market_basis"]
    live = by_event["evt-live"]["best"][by_event["evt-live"]["sides"][0]]["market_basis"]
    assert pre["displayable"] is True
    assert live["displayable"] is False, "a started game inherited a pregame kickoff"
    assert "has started" in live["reason"]


# ---------------------------------------------------------------- the guards


def test_one_book_refuses_rather_than_reporting_zero():
    """414 of 552 real pregame sides looked like this. `0.0` would be a lie."""
    verdict = market_basis_edge(
        best_side(books_quoting=1, edge_vs_consensus_pct=0.0), commence_time=KICKOFF, now=NOW
    )
    assert verdict.edge_pct is None
    assert verdict.displayable is False
    assert "at least" in verdict.reason and str(MIN_BOOKS_TO_DISPLAY) in verdict.reason


def test_live_and_settled_markets_are_refused():
    """The 16.04pp NC State outlier: ten quotes, one line, 115s apart, 7x apart."""
    verdict = market_basis_edge(
        best_side(edge_vs_consensus_pct=16.04, books_quoting=5),
        commence_time=STARTED,
        now=NOW,
    )
    assert verdict.edge_pct is None
    assert verdict.displayable is False
    assert "has started" in verdict.reason


def test_absent_start_time_refuses_and_does_not_assume_pregame():
    """Unknown must not land on the permissive branch."""
    for missing in (None, "", "not-a-date"):
        verdict = market_basis_edge(best_side(), commence_time=missing, now=NOW)
        assert verdict.displayable is False, f"{missing!r} was treated as pregame"
        assert "start time" in verdict.reason


def test_stale_side_is_refused_even_though_the_producer_already_filters():
    for flag in ("suspect_stale", "all_quotes_stale"):
        verdict = market_basis_edge(best_side(**{flag: True}), commence_time=KICKOFF, now=NOW)
        assert verdict.displayable is False
        assert "stale" in verdict.reason


def test_absent_consensus_is_not_a_zero_edge():
    verdict = market_basis_edge(
        best_side(edge_vs_consensus_pct=None), commence_time=KICKOFF, now=NOW
    )
    assert verdict.edge_pct is None
    assert "no consensus" in verdict.reason


def test_display_and_serve_are_different_bars():
    """A number can be honest and still not be a pick. Both cases keep the number."""
    thin = market_basis_edge(
        best_side(books_quoting=MIN_BOOKS_TO_SERVE - 1), commence_time=KICKOFF, now=NOW
    )
    assert thin.displayable is True and thin.servable is False
    assert thin.edge_pct is not None

    small = market_basis_edge(
        best_side(edge_vs_consensus_pct=MIN_EDGE_PCT_TO_SERVE - 0.01),
        commence_time=KICKOFF,
        now=NOW,
    )
    assert small.displayable is True and small.servable is False
    assert small.edge_pct is not None


def test_label_never_says_ev():
    """The one sentence that stops this being read as expected value."""
    payload = market_basis_edge(best_side(), commence_time=KICKOFF, now=NOW).as_payload()
    assert "not EV" in payload["label"]
    assert "price shopping" in payload["label"]


def test_summarise_keys_on_reason_not_just_a_total():
    verdicts = [
        market_basis_edge(best_side(), commence_time=KICKOFF, now=NOW),
        market_basis_edge(best_side(books_quoting=1), commence_time=KICKOFF, now=NOW),
        market_basis_edge(best_side(), commence_time=STARTED, now=NOW),
    ]
    summary = summarise(verdicts)
    assert summary["sides"] == 3
    assert summary["displayed"] == 1
    assert summary["servable"] == 1
    assert len(summary["not_displayed_by_reason"]) == 2


# ---------------------------------------------------------------- the gate


def test_model_gate_is_unchanged_and_still_denies():
    """The measurement that justifies the model gate must survive this change."""
    for market in ("spread", "moneyline", "total"):
        verdict = pick_gate.market_verdict("ncaaf", market, basis=MODEL_BASIS)
        assert verdict.servable is False, market
    spread = pick_gate.market_verdict("ncaaf", "spread")
    assert spread.model_metric == 15.775
    assert spread.market_metric == 12.212
    assert spread.sample_size == 2233
    assert "t=+17.20" in spread.detail


def test_basis_defaults_to_model_so_untaught_callers_are_unchanged():
    assert pick_gate.market_verdict("ncaaf", "spread").servable is False
    assert pick_gate.is_servable("ncaaf", "spread") is False


def test_market_basis_is_servable_and_says_what_it_is_not():
    verdict = pick_gate.market_verdict("ncaaf", "spread", basis=BASIS)
    assert verdict.servable is True
    assert "NOT expected value" in verdict.detail
    assert "price shopping" in verdict.detail.lower()


def test_unknown_basis_denies_and_does_not_borrow_the_model_wording():
    verdict = pick_gate.market_verdict("ncaaf", "spread", basis="vibes")
    assert verdict.servable is False
    assert "unknown edge basis" in verdict.reason
    assert "closing line" not in verdict.reason


def test_rows_without_a_basis_are_read_as_model_not_as_any():
    rows = [
        {"market": "spread", "edge": 4.0},
        {"market": "spread", "edge": 4.0, "edge_basis": BASIS},
    ]
    kept, suppressed = pick_gate.filter_pick_rows("ncaaf", rows)
    assert len(kept) == 1
    assert kept[0]["edge_basis"] == BASIS
    assert suppressed == {"spread": 1}


@pytest.mark.parametrize(
    "spelling,expected",
    [
        ("h2h", "moneyline"),
        ("H2H", "moneyline"),
        ("moneyline_home", "moneyline"),
        ("spreads", "spread"),
        ("SPREAD", "spread"),
        ("totals", "total"),
        ("over_under", "total"),
    ],
)
def test_market_folding_reaches_the_registry_from_every_real_spelling(spelling, expected):
    assert pick_gate._normalise_market(spelling, "ncaaf") == expected
    assert pick_gate.market_verdict("ncaaf", spelling).servable is False


def test_pick_gate_market_folding_covers_market_keys():
    """`learnings.md` 2026-08-23: a private market list needs a test deriving it
    from `market_keys`, or it is a silent time bomb.

    Asserts BOTH directions: every canonical game-line key the authority can
    return is folded, and every key this module folds is one the authority
    actually produces -- a stale entry here would be dead code that reads as
    coverage.
    """
    from syndicate.features.shared.market_keys import canonical_market_key

    for canonical, registry_word in pick_gate._CANONICAL_TO_REGISTRY.items():
        resolved = canonical_market_key("ncaaf", canonical)
        assert resolved == canonical, (
            f"{canonical!r} is not a key `market_keys` returns; this mapping is stale"
        )
        assert pick_gate._normalise_market(canonical, "ncaaf") == registry_word

    registry_markets = {market for (_, market, _) in pick_gate._SERVING_REGISTRY}
    assert registry_markets <= set(pick_gate._CANONICAL_TO_REGISTRY.values()), (
        "a registry market has no route from the canonical vocabulary, so a row "
        "carrying the canonical spelling would miss the gate"
    )


def test_board_notice_names_the_basis_it_speaks_for():
    notice = pick_gate.board_notice("ncaaf", ["spread", "moneyline", "total"])
    assert notice is not None
    assert notice["basis"] == MODEL_BASIS
    assert BASIS in notice["other_bases_unaffected"]
    assert "MODEL picks" in notice["headline"]


# ------------------------------------------------- the picks page hop


def _grid_payload(commence, *, line=None, market="h2h", consensus=None, best=None):
    return {
        "rows": [
            {
                "event_id": "evt-1",
                "market": market,
                "segment": "full",
                "line": line,
                "home_team": "UNLV Rebels",
                "away_team": "Memphis Tigers",
                "commence_time": commence,
                "sides": ["away", "home"],
                "consensus": consensus or {"away": 164, "home": -205},
                "best": best
                or {
                    "away": best_side(price=180, bookmaker="betus", books_quoting=11),
                    "home": best_side(
                        price=-205, bookmaker="fanduel", books_quoting=11,
                        edge_vs_consensus_pct=0.1,
                    ),
                },
            }
        ]
    }


@pytest.fixture()
def picks_over_grid(monkeypatch):
    """Drive `_market_basis_pick_cards` over a grid payload we control."""
    from syndicate.features.ncaaf import cards as ncaaf_cards
    from syndicate.features.shared import book_grid_artifact

    def _install(payloads):
        monkeypatch.setattr(
            book_grid_artifact, "read_book_grid_artifact",
            lambda sport, date: payloads.get(date),
        )
        monkeypatch.setattr(
            ncaaf_cards, "_ncaaf_week_kickoff_dates",
            lambda season, week: tuple(sorted(payloads)),
        )

    return _install


def test_picks_page_builds_market_basis_cards(picks_over_grid):
    """The surface that rendered a blackout now renders a pick, with its basis."""
    from syndicate.features.ncaaf import picks as ncaaf_picks

    future = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat().replace("+00:00", "Z")
    picks_over_grid({"2026-09-05": _grid_payload(future)})

    counts: dict = {}
    cards = ncaaf_picks._market_basis_pick_cards(2026, 1, counts=counts)

    assert counts["dates_read"] == 1
    assert counts["dates_absent"] == 0
    assert counts["sides_considered"] == 2
    assert counts["servable"] == 1, "the +2.16 side should clear; the +0.10 side should not"
    assert len(cards) == 1

    card = cards[0]
    assert card["market"] == "moneyline"
    assert "Memphis Tigers" in card["title"], "side rendered as a token, not a team"
    assert "not expected value" in card["summary"]
    assert "price-shopping" in card["summary"].lower()
    assert any("consensus" in item for item in card["list_items"])


def test_picks_page_reports_absent_dates_separately_from_empty_ones(picks_over_grid):
    """`dates_absent` is what separates 'no grid published' from 'no edges'."""
    from syndicate.features.ncaaf import picks as ncaaf_picks

    past = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat().replace("+00:00", "Z")
    picks_over_grid({"2026-09-05": _grid_payload(past), "2026-09-06": None})

    counts: dict = {}
    cards = ncaaf_picks._market_basis_pick_cards(2026, 1, counts=counts)
    assert cards == []
    assert counts["dates_read"] == 1
    assert counts["dates_absent"] == 1
    assert counts["servable"] == 0


def test_side_label_names_the_team():
    from syndicate.features.ncaaf.picks import _side_label

    assert _side_label("home", home_team="UNLV Rebels", away_team="Memphis Tigers") == "UNLV Rebels"
    assert _side_label("away", home_team="UNLV Rebels", away_team="Memphis Tigers") == "Memphis Tigers"
    assert _side_label("over", home_team="UNLV Rebels", away_team="Memphis Tigers") == "over"


def test_spread_line_is_stated_from_the_side_that_holds_it():
    """`_canonical_line` stores the AWAY perspective; the home side is its negation."""
    from syndicate.features.ncaaf.picks import _line_for_side

    assert _line_for_side(4.5, "away", "spreads") == "+4.5"
    assert _line_for_side(4.5, "home", "spreads") == "-4.5"


def test_total_lines_are_never_signed():
    """REGRESSION. A total of 50.5 rendered '+50.5', which reads as a handicap,
    and the under side would have printed '-50.5' -- a number no total has."""
    from syndicate.features.ncaaf.picks import _line_for_side

    assert _line_for_side(50.5, "over", "totals") == "50.5"
    assert _line_for_side(50.5, "under", "totals") == "50.5"
    assert _line_for_side(None, "over", "totals") == "-"


# ------------------------------------- the region knob actually reaches NCAAF


def test_ncaaf_game_lines_reach_the_shared_region_knob(monkeypatch):
    """REACHABILITY. `SYNDICATE_LIVE_ODDS_GAME_LINE_REGIONS` had ONE reader --
    the MLB fetcher -- so setting it for NCAAF was inert: present in the
    environment, read by nothing, and the sharps never appeared.

    Asserts the REQUEST, not the config: the value has to land in the `regions`
    parameter of the call NCAAF actually makes.
    """
    import scripts.fetch_ncaaf_oddsapi_game_lines as fetcher

    monkeypatch.setenv("SYNDICATE_LIVE_ODDS_GAME_LINE_REGIONS", "us_ex,eu")
    captured: dict = {}

    class _Response:
        url = "https://example.invalid/odds"
        status_code = 200
        headers: dict = {}

        def json(self):
            return []

        def raise_for_status(self):
            return None

    def _get(url, params=None, timeout=None):
        captured["params"] = params or {}
        return _Response()

    monkeypatch.setattr(fetcher.requests, "get", _get)
    try:
        fetcher.fetch_events("KEY", region="us")
    except Exception:
        # The call may fail downstream of the request; the request is the claim.
        pass

    assert captured, "no request was made"
    regions = captured["params"].get("regions", "")
    assert regions.split(",")[0] == "us", "extras must widen, never replace `us`"
    assert "us_ex" in regions, f"us_ex never reached the request: {regions!r}"
    assert "eu" in regions, f"eu never reached the request: {regions!r}"


def test_region_extras_never_drop_the_base(monkeypatch):
    from syndicate.features.shared.odds_regions import game_line_regions

    assert game_line_regions("us", env={}) == "us"
    assert game_line_regions("us", env={"SYNDICATE_LIVE_ODDS_GAME_LINE_REGIONS": "eu"}) == "us,eu"
    # A region named twice is not billed twice, and order is preserved.
    assert (
        game_line_regions("us,eu", env={"SYNDICATE_LIVE_ODDS_GAME_LINE_REGIONS": "eu,us_ex"})
        == "us,eu,us_ex"
    )


def test_mlb_and_ncaaf_share_one_region_owner():
    """Two copies of this rule would drift, and the drift is a billing change."""
    import scripts.fetch_mlb_oddsapi_local as mlb
    from syndicate.features.shared.odds_regions import game_line_regions

    assert mlb._game_line_regions("us,us2") == game_line_regions("us,us2")


def test_market_edge_tooltip_explains_the_number_it_shows():
    """REGRESSION, found on the LIVE board 2026-08-30.

    A cell reading "+2.81 mkt" hovered as "margin model loses to the closing
    line...". The model's suppression reason had unconditional precedence, so
    `mb.label` -- the one sentence that stops a price-shopping delta being read
    as a model edge -- was suppressed exactly where the number was visible.

    Asserts on the TEMPLATE source because this branch is client-side JS; the
    payload half is covered by `test_label_never_says_ev`.
    """
    import pathlib

    html = (
        pathlib.Path(__file__).resolve().parents[1]
        / "syndicate" / "templates" / "shared" / "layer1_board.html"
    ).read_text(encoding="utf-8")

    start = html.index("var edgeWhy")
    body = html[start:html.index("var edgeTitle", start)]

    # The market branch must exist and must lead with the label.
    assert 'edgeUnit === "mkt"' in body, "no market-basis branch in the tooltip"
    label_at = body.index("mb.label")
    model_at = body.index("p.edge_unavailable_reason")
    assert label_at < model_at, (
        "the model's suppression reason still precedes the market label, so a "
        "cell showing a market edge hovers with a model message"
    )
    # And the model reason must still be CARRIED, not dropped -- both facts.
    assert "the model's own edge is withheld here" in body


# ------------------------------- the board's artifact read set (UTC vs Central)


def test_read_set_includes_the_utc_neighbour_of_every_window_date():
    """A Central-evening game lives in the NEXT day's UTC artifact.

    Measured on production 2026-08-30: `window=day&date=2026-08-29` showed 7
    games while `book_grid_2026-08-30.json` held Memphis @ UNLV at
    2026-08-30T02:19Z — 9:19pm Central on the 29th. Same game and same cause as
    the one `ncaaf/sources.py` already records dropping.
    """
    from syndicate.features.shared.layer1_board import artifact_read_dates

    got = artifact_read_dates(["2026-08-29"], today="2026-08-29")
    assert "2026-08-30" in got, "the UTC neighbour is not read, so a 9pm CT game is invisible"
    assert got[0] == "2026-08-29", "the anchor must stay first so provenance comes from it"


def test_read_set_is_deduplicated_and_order_preserving():
    from syndicate.features.shared.layer1_board import artifact_read_dates

    got = artifact_read_dates(["2026-08-29", "2026-08-30"], today="2026-08-29")
    assert got == ["2026-08-29", "2026-08-30", "2026-08-31"]
    assert len(got) == len(set(got)), "an artifact would be opened twice"


def test_read_set_survives_an_unparseable_window_date():
    """One bad date must not drop the rest of the window."""
    from syndicate.features.shared.layer1_board import artifact_read_dates

    got = artifact_read_dates(["not-a-date", "2026-09-05"], today=None)
    assert "2026-09-05" in got and "2026-09-06" in got
    assert "not-a-date" in got, "the caller's own date is still passed through to the reader"


def test_read_set_widening_cannot_change_what_the_board_SHOWS():
    """The read set is not the display scope.

    `build_layer1_board` filters on each row's own local game date against
    `window_dates`, so reading an extra artifact can only widen the candidate
    pool. This is the property that makes the fix safe; assert it rather than
    trust the comment.
    """
    from syndicate.features.shared.layer1_board import build_layer1_board

    row = {
        "sport": "ncaaf",
        "event_id": "next-day",
        "market": "h2h",
        "segment": "full",
        "commence_time": "2026-09-07T23:00:00Z",
        "home_team": "H",
        "away_team": "A",
        "sides": ["away"],
        "best": {}, "cells": {}, "books": [], "consensus": {},
    }
    board = build_layer1_board(
        [row], sport="ncaaf", selected_date="2026-08-29", window_dates=["2026-08-29"]
    )
    assert board["counts"]["games"] == 0, "an off-window fixture reached the board"
    assert board["counts"]["rows_other_dates"] == 1


# --------------------------- artifact coverage vs display window


def test_artifact_window_is_never_narrower_than_the_display_window():
    """The invariant `max_slate_window_days` exists for: the producer must not
    build a narrower window than the consumer asks for."""
    from syndicate.features.shared.layer1_board import (
        _SLATE_WINDOW_DAYS,
        artifact_window_days,
        max_artifact_window_days,
        max_slate_window_days,
        slate_window_days,
    )

    for sport in _SLATE_WINDOW_DAYS:
        assert artifact_window_days(sport) >= slate_window_days(sport), sport
    assert max_artifact_window_days() >= max_slate_window_days()


def test_ncaaf_artifact_window_covers_its_ten_day_week():
    """NCAAF week 1 spans 2026-08-29..09-07. At 7 the last three days of every
    week had no artifact, so the board answered `grid_rows_all_for_other_dates`
    on a real 300-row Friday slate."""
    from syndicate.features.shared.layer1_board import (
        artifact_window_days,
        slate_window_days,
    )

    assert slate_window_days("ncaaf") == 7, "the DISPLAY choice must not be changed by this"
    assert artifact_window_days("ncaaf") >= 10


def test_widening_artifact_coverage_does_not_widen_any_sports_display():
    """`#565`'s cost fix must survive: a wider artifact window for one sport
    must not build every sport further out."""
    from syndicate.features.shared.layer1_board import (
        artifact_window_days,
        slate_window_days,
    )

    for sport in ("ncaab", "mlb", "nba", "wnba", "nhl"):
        assert artifact_window_days(sport) == slate_window_days(sport), sport


def test_worker_gate_admits_the_ncaaf_dates_the_board_can_ask_for():
    """The producer-side gate, exercised directly."""
    import scripts.run_refresh_worker as worker

    anchor = "2026-08-29"
    assert worker._sport_covers_date("ncaaf", anchor, "2026-09-05") is True
    assert worker._sport_covers_date("ncaaf", anchor, "2026-09-07") is True
    # And it still prunes a sport that asks for one day.
    assert worker._sport_covers_date("ncaab", anchor, "2026-09-05") is False


# ------------------------------------- the venue order probe (read-only, gated)


def test_polymarket_order_probe_is_inert_without_the_env_var(monkeypatch, capsys):
    """It must not fire by accident: this rides inside a worker with real work."""
    import scripts.run_refresh_worker as worker

    monkeypatch.delenv("SYNDICATE_PROBE_POLYMARKET_ORDER", raising=False)
    called = {"n": 0}

    def _boom(*a, **k):
        called["n"] += 1
        raise AssertionError("the venue must not be contacted when the gate is unset")

    monkeypatch.setattr(
        "syndicate.features.shared.polymarket_us_orders.fetch_orders", _boom, raising=False
    )
    worker._probe_polymarket_order_once()
    assert called["n"] == 0
    assert capsys.readouterr().out == "", "an inert probe must not even log"


def test_polymarket_order_probe_reads_and_never_writes(monkeypatch, capsys):
    """Asserts the CALL, not the output: exactly one GET, no submit/cancel."""
    import scripts.run_refresh_worker as worker
    from syndicate.features.shared import polymarket_us_orders as pmo

    monkeypatch.setenv("SYNDICATE_PROBE_POLYMARKET_ORDER", "C65VD0R72KDG")
    seen = {}

    def _fetch(*, limit=100, order_ids=None):
        seen["limit"] = limit
        seen["order_ids"] = list(order_ids or [])
        return {
            "orders": [
                {
                    "orderId": "C65VD0R72KDG",
                    "status": "filled",
                    "commissionNotionalTotalCollected": 0.197,
                    "filledCount": 13.13,
                }
            ]
        }

    monkeypatch.setattr(pmo, "fetch_orders", _fetch)
    # Any write path must be untouched; make them explode if reached.
    for name in ("submit_order", "cancel_order"):
        if hasattr(pmo, name):
            monkeypatch.setattr(
                pmo, name, lambda *a, **k: (_ for _ in ()).throw(AssertionError(f"{name} called"))
            )

    worker._probe_polymarket_order_once()

    assert seen["order_ids"] == ["C65VD0R72KDG"], "probe did not scope to the one order"
    out = capsys.readouterr().out
    assert "PM_ORDER_PROBE id=C65VD0R72KDG status=ok" in out
    assert "commissionNotionalTotalCollected" in out, "the discriminating field was not printed"


def test_polymarket_order_probe_survives_a_venue_error(monkeypatch, capsys):
    """A diagnostic must never take the worker down."""
    import scripts.run_refresh_worker as worker
    from syndicate.features.shared import polymarket_us_orders as pmo

    monkeypatch.setenv("SYNDICATE_PROBE_POLYMARKET_ORDER", "C65VD0R72KDG")
    monkeypatch.setattr(
        pmo, "fetch_orders", lambda **k: (_ for _ in ()).throw(RuntimeError("http_401"))
    )
    worker._probe_polymarket_order_once()  # must not raise
    assert "PM_ORDER_PROBE_ERROR" in capsys.readouterr().out


def test_probe_distinguishes_absent_order_from_empty_read(monkeypatch, capsys):
    """'the venue has no such order' and 'the list returned nothing' differ."""
    import scripts.run_refresh_worker as worker
    from syndicate.features.shared import polymarket_us_orders as pmo

    monkeypatch.setenv("SYNDICATE_PROBE_POLYMARKET_ORDER", "C65VD0R72KDG")
    monkeypatch.setattr(pmo, "fetch_orders", lambda **k: {"orders": []})
    worker._probe_polymarket_order_once()
    out = capsys.readouterr().out
    assert "status=not_in_list" in out and "returned_rows=0" in out


# ---------------------------- polymarket fill-price side reading (live money)


def _pm_order(**over):
    """The real blocking order C65VD0R72KDG, as the venue returned it."""
    row = {
        "id": "C65VD0R72KDG",
        "state": "ORDER_STATE_FILLED",
        "cumQuantity": 13.13,
        "leavesQuantity": 0,
        "avgPx": {"currency": "USD", "value": "0.2350"},
        "price": {"currency": "USD", "value": "0.22"},
        "outcomeSide": "OUTCOME_SIDE_NO",
        "side": "ORDER_SIDE_SELL",
        "marketSlug": "tsc-mlb-phi-laa-2026-08-29-7pt5",
    }
    row.update(over)
    return row


def test_the_blocking_orders_fill_price_is_no_longer_discarded():
    """REGRESSION, real money, ~12h outage.

    `outcomeSide=NO` complemented 0.2350 -> 0.7650, which the FILL_ABOVE_LIMIT
    guard then correctly refused against a 0.22 limit, leaving fill_price None.
    The ledger fell back to a contract bound and refused 13.13 > 10.8953.
    """
    from syndicate.features.shared.polymarket_us_orders import venue_order_view

    view = venue_order_view(_pm_order())
    assert view["state"] == "filled"
    assert view["fill_price"] is not None, "the venue reported avgPx and we dropped it"
    assert abs(view["fill_price"] - 0.2350) < 1e-6, view["fill_price"]


def test_the_side_rule_still_decides_the_fills_it_got_right():
    """The four recorded fills sit near 0.5, where the limit cannot discriminate.
    They must keep falling through to the side rule, which is right on all four."""
    from syndicate.features.shared.polymarket_us_orders import venue_order_view

    cases = [
        # (limit, avgPx, outcomeSide, expected recorded price)
        (0.4545, 0.55, "OUTCOME_SIDE_NO", 0.45),
        (0.4902, 0.51, "OUTCOME_SIDE_NO", 0.49),
        (0.5192, 0.52, "OUTCOME_SIDE_YES", 0.52),
    ]
    for limit, avg, side, expected in cases:
        view = venue_order_view(
            _pm_order(
                avgPx={"value": str(avg)}, price={"value": str(limit)}, outcomeSide=side
            )
        )
        assert view["fill_price"] is not None, (limit, avg, side)
        assert abs(view["fill_price"] - expected) < 1e-6, (limit, avg, side, view["fill_price"])


def test_limit_rule_overrides_a_wrong_side_label_when_unambiguous():
    """Far from 0.5 the limit decides, and it must beat the side label."""
    from syndicate.features.shared.polymarket_us_orders import venue_order_view

    # NO label would complement 0.30 -> 0.70, absurd against a 0.28 limit.
    view = venue_order_view(
        _pm_order(avgPx={"value": "0.30"}, price={"value": "0.28"}, outcomeSide="OUTCOME_SIDE_NO")
    )
    assert abs(view["fill_price"] - 0.30) < 1e-6

    # And it complements when THAT is what the limit agrees with. Numbers chosen
    # so the complement lands ABOVE the limit -- this is a SELL, and a sell
    # filling BELOW its limit is a real violation the guard must still catch
    # (the first draft of this test asserted the opposite and was wrong).
    view = venue_order_view(
        _pm_order(avgPx={"value": "0.75"}, price={"value": "0.22"}, outcomeSide="OUTCOME_SIDE_YES")
    )
    assert abs(view["fill_price"] - 0.25) < 1e-6, view["fill_price"]


def test_a_sell_filling_below_its_limit_is_still_refused():
    """The directional rule must not become no rule: a SELL below its limit is
    as impossible as a BUY above one."""
    from syndicate.features.shared.polymarket_us_orders import venue_order_view

    view = venue_order_view(
        _pm_order(avgPx={"value": "0.10"}, price={"value": "0.22"}, side="ORDER_SIDE_SELL",
                  outcomeSide="OUTCOME_SIDE_YES")
    )
    assert view["fill_price"] is None


def test_a_buy_filling_above_its_limit_is_still_refused():
    """The original invariant, unchanged."""
    from syndicate.features.shared.polymarket_us_orders import venue_order_view

    view = venue_order_view(
        _pm_order(avgPx={"value": "0.40"}, price={"value": "0.22"}, side="ORDER_SIDE_BUY",
                  outcomeSide="OUTCOME_SIDE_YES")
    )
    assert view["fill_price"] is None


def test_an_unreadable_side_near_half_still_withholds():
    """Ambiguity is a refusal, not a coin flip -- the pre-existing contract."""
    from syndicate.features.shared.polymarket_us_orders import venue_order_view

    view = venue_order_view(
        _pm_order(avgPx={"value": "0.51"}, price={"value": "0.49"}, outcomeSide="MYSTERY")
    )
    assert view["fill_price"] is None


# ------------------------------------ avgPx = 0.0000 is absence, not a price


def test_a_zero_avgpx_is_absent_on_both_sides(capsys):
    """REGRESSION, production 2026-08-30. The SAME `avgPx='0.0000'` recorded
    0.0 on one leg and None on the other. Zero is an UNFILLED order, not a
    fill at zero, and it must read identically whatever the side."""
    from syndicate.features.shared.polymarket_us_orders import venue_order_view

    for side in ("OUTCOME_SIDE_YES", "OUTCOME_SIDE_NO"):
        view = venue_order_view(
            _pm_order(
                avgPx={"value": "0.0000"},
                price={"value": "0.51"},
                outcomeSide=side,
                cumQuantity=0,
                state="ORDER_STATE_NEW",
            )
        )
        assert view["fill_price"] is None, f"{side} booked a zero as a price"
    # And it must not masquerade as an impossible-fill alarm on a resting order.
    assert "FILL_ABOVE_LIMIT" not in capsys.readouterr().out


def test_a_zero_price_never_books_a_position_at_zero_dollars():
    """The hazard the guard is placed for: on a BUY the zero used to survive,
    and `fill_stake_dollars` is derived as contracts x fill_price."""
    from syndicate.features.shared.polymarket_us_orders import venue_order_view

    view = venue_order_view(
        _pm_order(
            avgPx={"value": "0.0000"},
            price={"value": "0.51"},
            side="ORDER_SIDE_BUY",
            outcomeSide="OUTCOME_SIDE_YES",
            cumQuantity=13.13,
        )
    )
    assert view["state"] == "filled", "the fill itself must survive"
    assert view["fill_price"] is None, "a filled row must not carry a $0 price"


def test_a_zero_WITH_a_fill_is_loud_and_a_resting_zero_is_quiet(capsys):
    """A resting zero is normal and must not spam; a zero on a FILLED order is
    the dangerous combination and must say so."""
    from syndicate.features.shared.polymarket_us_orders import venue_order_view

    venue_order_view(
        _pm_order(avgPx={"value": "0.0000"}, cumQuantity=0, state="ORDER_STATE_NEW")
    )
    assert "FILL_PRICE_ZERO_WITH_FILL" not in capsys.readouterr().out

    venue_order_view(_pm_order(avgPx={"value": "0.0000"}, cumQuantity=13.13))
    assert "FILL_PRICE_ZERO_WITH_FILL" in capsys.readouterr().out


def test_an_out_of_range_price_is_refused_and_named_as_a_units_error(capsys):
    """>= 1 is the units error this file records costing $347.36 on a $1.64 stake."""
    from syndicate.features.shared.polymarket_us_orders import venue_order_view

    view = venue_order_view(_pm_order(avgPx={"value": "104.0"}, cumQuantity=13.13))
    assert view["fill_price"] is None
    out = capsys.readouterr().out
    assert "FILL_PRICE_OUT_OF_RANGE" in out and "104.0" in out


def test_a_real_price_still_reads_through_unchanged():
    """The blocking order must keep working -- this guard must not eat it."""
    from syndicate.features.shared.polymarket_us_orders import venue_order_view

    view = venue_order_view(_pm_order())
    assert abs(view["fill_price"] - 0.2350) < 1e-6
