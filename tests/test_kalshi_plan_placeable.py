"""`#661`: the LIVE venue plan holds only rows the venue can actually take.

MEASURED 2026-09-11 on production (refresh-worker `1e1285a4`):

    PAPER2_PLAN_WRITTEN date=2026-09-10 venue=kalshi rows_in=532 positions=22
      venue_priced=310 placeable_committed=4/22

and live-odds-worker's pass over that book refused 16 of 20 positions
`no_venue_ticker` -- NCAAF spreads and totals, every one
`price_source='aggregator'`. paper2's venue plan is a COMPARISON book and keeps
uncontracted rows on purpose; the defect was that live placed it.

The fix is a second plan per venue, committed over only the rows carrying the
venue's own price AND its contract id, which live reads instead. paper2's plan,
the paper books and the executor's `no_venue_ticker` refusal are unchanged, and
several tests below exist to pin exactly that.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared.portfolio_settings import PortfolioSettings

_DATE = "2026-08-22"
_TICKER = "KXNCAAFSPREAD-26AUG22AWAYHOME-HOME4"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_REPORTS_ROOT", str(tmp_path))
    for key in (
        "SYNDICATE_EXECUTION_ENABLED",
        "SYNDICATE_EXECUTION_MODE",
        "SYNDICATE_EXECUTION_LIVE_ARMED",
        "SYNDICATE_EXECUTION_VENUE",
        "SYNDICATE_PORTFOLIO_COMMIT_ENABLED",
        "SYNDICATE_REFRESH_STATE_BACKEND",
        "SYNDICATE_PAPER2_VENUES",
        "SYNDICATE_PAPER2_VENUE",
    ):
        monkeypatch.delenv(key, raising=False)
    yield


def _settings(**overrides) -> PortfolioSettings:
    values = dict(
        bankroll_units=1000.0,
        max_slate_exposure_fraction=1.0,
        min_ev_pct=-100.0,
        max_positions=50,
        min_stake_units=0.0,
    )
    values.update(overrides)
    return PortfolioSettings(**values)


def _row(event_id: str, *, price_source: str | None, venue_ticker=None, score: float = 5.0, **extra):
    """A venue-scoped row, shaped like `scope_rows_to_venue`'s output."""
    row = {
        "sport": "ncaaf",
        "event_id": event_id,
        "kind": "game",
        "market": "h2h",
        "segment": "full_game",
        "line": None,
        "player_name": None,
        "home_team": "Home",
        "away_team": "Away",
        "commence_time": "2026-08-22T23:05:00Z",
        "side": "home",
        "quote": {"price": -110, "bookmaker": "kalshi"},
        "ev_pct": 4.5,
        "model_edge_pct": 3.2,
        "score": {"score": score, "price_reliability": 0.82},
        "venue": "kalshi",
        "price_source": price_source,
        "venue_ticker": venue_ticker,
    }
    row.update(extra)
    return row


def _mixed_rows():
    # The uncontracted rows score HIGHEST, which is the production shape: the
    # aggregator's best price is what made them look good.
    return [
        _row("agg-1", price_source="aggregator", score=9.9),
        _row("agg-2", price_source="aggregator", score=9.8),
        _row("feed-no-ticker", price_source="venue_feed", venue_ticker=None, score=7.0),
        _row("feed-1", price_source="venue_feed", venue_ticker=_TICKER, score=5.0),
    ]


def _ids(plan) -> set:
    return {p.get("event_id") for p in plan.get("positions") or []}


# --------------------------------------------------------------------------
# The live plan itself
# --------------------------------------------------------------------------


def test_the_live_plan_holds_only_rows_with_a_venue_contract():
    from pipeline.portfolio_commit import commit_live_venue_plan

    live = commit_live_venue_plan(_mixed_rows(), selected_date=_DATE, settings=_settings())

    assert _ids(live) == {"feed-1"}
    assert [p.get("venue_ticker") for p in live["positions"]] == [_TICKER]
    # Two reasons, not one: they call for opposite work.
    assert live["refusals"]["aggregator_priced"] == 2
    assert live["refusals"]["no_venue_contract"] == 1
    # EVERY scoped row is still accounted for -- `commit_portfolio`'s own
    # contract, kept across the pre-filter.
    assert sum(live["refusals"].values()) + len(live["positions"]) == live["rows_in"] == 4
    assert live["placeable_rows_in"] == 1
    assert live["plan_kind"] == "live"
    assert live["refusals_by_sport"]["aggregator_priced"] == {"ncaaf": 2}
    assert live["refusals_by_market"]["no_venue_contract"] == {"h2h": 1}


def test_reachability_the_live_book_is_not_the_paper2_book_on_the_same_rows():
    """off != on, before any correctness claim.

    OFF is the book live used to read: paper2's, committed with
    `prefer_placeable=True`. ON is the live plan. Same rows, same settings --
    if these came out equal, the change would be inert.
    """
    from pipeline.portfolio_commit import commit_live_venue_plan
    from syndicate.features.shared.portfolio_commit import commit_portfolio

    rows = _mixed_rows()
    paper2 = commit_portfolio(rows, selected_date=_DATE, settings=_settings(), prefer_placeable=True)
    live = commit_live_venue_plan(rows, selected_date=_DATE, settings=_settings())

    assert _ids(paper2) != _ids(live)
    # PAPER IS UNCHANGED: the comparison book still holds the uncontracted rows.
    assert {"agg-1", "agg-2", "feed-no-ticker"} <= _ids(paper2)
    assert _ids(live) == {"feed-1"}


def test_an_uncontracted_row_can_no_longer_shrink_a_contracted_stake():
    """The slate ceiling is shared by every committed row. In paper2's book the
    uncontracted rows take part of it, and the one bet live can actually make is
    scaled down to fit. In the live book they are absent, so it is not.

    (It did not bind on the measured production build -- `slate_scale_factor=1.0`
    -- which is why this is pinned here rather than read off the logs.)
    """
    from pipeline.portfolio_commit import commit_live_venue_plan
    from syndicate.features.shared.portfolio_commit import commit_portfolio

    rows = _mixed_rows()
    tight = _settings(max_slate_exposure_fraction=0.005)
    paper2 = commit_portfolio(rows, selected_date=_DATE, settings=tight, prefer_placeable=True)
    live = commit_live_venue_plan(rows, selected_date=_DATE, settings=tight)

    def stake_of(plan, event_id):
        return next(p["stake_dollars"] for p in plan["positions"] if p["event_id"] == event_id)

    assert paper2["totals"]["slate_scale_factor"] < live["totals"]["slate_scale_factor"]
    assert stake_of(live, "feed-1") > stake_of(paper2, "feed-1")


def test_every_placeable_position_paper2_committed_is_in_the_live_plan():
    """The self-check `LIVE_PLAN_WRITTEN` prints as `paper2_placeable_missing`.

    Same rows and gates, with fewer rows competing for the cap and the budget,
    so the live book can only keep MORE of the contracted bets -- never fewer.
    The cap binds here, and the uncontracted rows outscore every contracted one.
    """
    from pipeline.portfolio_commit import commit_live_venue_plan, placeable_refusal
    from syndicate.features.shared.portfolio_commit import commit_portfolio

    rows = [
        _row("agg-1", price_source="aggregator", score=9.9),
        _row("agg-2", price_source="aggregator", score=9.8),
        _row("agg-3", price_source="aggregator", score=9.7),
        _row("feed-1", price_source="venue_feed", venue_ticker=_TICKER + "-1", score=2.0),
        _row("feed-2", price_source="venue_feed", venue_ticker=_TICKER + "-2", score=1.0),
    ]
    capped = _settings(max_positions=3)
    paper2 = commit_portfolio(rows, selected_date=_DATE, settings=capped, prefer_placeable=True)
    live = commit_live_venue_plan(rows, selected_date=_DATE, settings=capped)

    paper2_placeable = {p["position_key"] for p in paper2["positions"] if placeable_refusal(p) is None}
    assert paper2_placeable, "the fixture must put a contracted row in paper2's book"
    assert paper2_placeable <= {p["position_key"] for p in live["positions"]}
    assert _ids(live) == {"feed-1", "feed-2"}


@pytest.mark.parametrize(
    "row, reason",
    [
        ({"price_source": "aggregator", "venue_ticker": _TICKER}, "aggregator_priced"),
        ({"price_source": None, "venue_ticker": None}, "aggregator_priced"),
        ({"price_source": "venue_feed", "venue_ticker": None}, "no_venue_contract"),
        ({"price_source": "venue_feed", "venue_ticker": "  "}, "no_venue_contract"),
        ({"price_source": "venue_feed", "venue_ticker": {}}, "no_venue_contract"),
        ({"price_source": "venue_feed", "venue_ticker": _TICKER}, None),
        ({"price_source": "venue_feed", "venue_ticker": {"slug": "tsc-x"}}, None),
    ],
)
def test_placeability_needs_the_venues_price_AND_its_contract(row, reason):
    """An aggregator-priced row that somehow carries a ticker is still refused:
    the order would be sent at a price the venue never quoted for it."""
    from pipeline.portfolio_commit import placeable_refusal

    assert placeable_refusal(row) == reason


# --------------------------------------------------------------------------
# The writer, end to end through `run_portfolio_commit`
# --------------------------------------------------------------------------


def _board_row(event_id: str, score: float):
    """A shortlist row as the board publishes it: no `price_source` yet, and
    the aggregator's view of Kalshi in `book_prices`."""
    return {
        "sport": "ncaaf",
        "event_id": event_id,
        "kind": "game",
        "market": "h2h",
        "segment": "full_game",
        "line": None,
        "player_name": None,
        "home_team": f"Home {event_id}",
        "away_team": f"Away {event_id}",
        "commence_time": "2026-08-22T23:05:00Z",
        "side": "home",
        "quote": {
            "price": -110,
            "bookmaker": "draftkings",
            "book_prices": {"draftkings": -110, "kalshi": -105},
        },
        "ev_pct": 6.0,
        "model_edge_pct": 4.0,
        "score": {"score": score, "price_reliability": 0.82},
    }


def _run_commit(monkeypatch, *, venues: str):
    monkeypatch.setenv("SYNDICATE_PORTFOLIO_COMMIT_ENABLED", "1")
    monkeypatch.setenv("SYNDICATE_PAPER2_VENUES", venues)
    board = [_board_row("agg-1", 9.9), _board_row("agg-2", 9.8), _board_row("feed-1", 5.0)]
    monkeypatch.setattr(
        "pipeline.intelligence_state.read_layer2_shortlist", lambda date: {"rows": board}
    )
    from pipeline import portfolio_commit as mod

    monkeypatch.setattr(mod, "resolve_settings", lambda: _settings())
    monkeypatch.setattr(
        "syndicate.features.shared.portfolio_commit.resolve_settings", lambda: _settings()
    )

    # Kalshi's OWN feed prices and contracts exactly one row; the other two fall
    # back to the aggregator's `book_prices["kalshi"]`, as NCAAF did on 09-11.
    def price_resolver(row):
        return -102 if row.get("event_id") == "feed-1" else None

    def ticker_resolver(row):
        return _TICKER if row.get("event_id") == "feed-1" else None

    monkeypatch.setattr(
        mod,
        "_venue_price_resolver",
        lambda venue, date=None: (price_resolver, ticker_resolver) if venue == "kalshi" else (None, None),
    )
    result = mod.run_portfolio_commit(_DATE, settled_sample_size_by_sport={})
    assert result["status"] == "ok", result
    return mod, board, (price_resolver, ticker_resolver)


def test_reachability_the_live_plan_is_written_only_when_paper2_runs(monkeypatch):
    """off != on at the ARTIFACT: with paper2 disabled there is no live plan,
    and with it on there is one for the same date."""
    mod, _, _ = _run_commit(monkeypatch, venues="")
    assert mod.read_live_portfolio_plan_for_venue(_DATE, "kalshi") is None

    mod, _, _ = _run_commit(monkeypatch, venues="kalshi")
    assert isinstance(mod.read_live_portfolio_plan_for_venue(_DATE, "kalshi"), dict)


def test_the_writer_puts_the_live_plan_beside_an_UNCHANGED_paper2_plan(monkeypatch, capsys):
    from syndicate.features.shared.portfolio_commit import commit_portfolio
    from syndicate.features.shared.venue_scope import scope_rows_to_venue

    mod, board, (price_resolver, ticker_resolver) = _run_commit(monkeypatch, venues="kalshi")
    out = capsys.readouterr().out

    paper2 = mod.read_portfolio_plan_for_venue(_DATE, "kalshi")
    live = mod.read_live_portfolio_plan_for_venue(_DATE, "kalshi")

    # PAPER2 IS WHAT IT WAS: the same commit over the same scoped rows, with its
    # uncontracted positions still in it.
    scoped, _ = scope_rows_to_venue(
        board, "kalshi", price_resolver=price_resolver, ticker_resolver=ticker_resolver
    )
    expected = commit_portfolio(scoped, selected_date=_DATE, settings=_settings(), prefer_placeable=True)
    assert [(p["position_key"], p["stake_dollars"]) for p in paper2["positions"]] == [
        (p["position_key"], p["stake_dollars"]) for p in expected["positions"]
    ]
    assert {p["price_source"] for p in paper2["positions"]} == {"aggregator", "venue_feed"}

    # THE LIVE PLAN: only the contracted row, carrying the contract.
    assert _ids(live) == {"feed-1"}
    assert live["positions"][0]["venue_ticker"] == _TICKER
    assert live["positions"][0]["price_source"] == "venue_feed"
    assert live["refusals"]["aggregator_priced"] == 2
    assert live["venue"] == "kalshi"

    # THE VERIFICATION LINE, as production will print it.
    line = next(l for l in out.splitlines() if "LIVE_PLAN_WRITTEN" in l)
    assert f"date={_DATE} venue=kalshi" in line
    assert "placeable_committed=1/1" in line
    assert "paper2_placeable=1 paper2_placeable_missing=0" in line
    assert "PAPER2_PLAN_WRITTEN" in out


def test_a_failed_live_commit_FAILS_CLOSED_and_leaves_paper2_alone(monkeypatch, capsys):
    """An older build's live plan must never be placed as if it were current.
    If the live commit fails, the live plan is emptied and the line says why;
    the comparison book is already on disk and is not touched."""
    from pipeline import portfolio_commit as mod

    # A stale live plan from an earlier build, holding a bet.
    mod.write_json_file(
        mod.live_portfolio_plan_path_for_venue(_DATE, "kalshi"),
        {"positions": [{"position_key": "stale", "venue_ticker": _TICKER}]},
    )

    def boom(*args, **kwargs):
        raise RuntimeError("synthetic")

    monkeypatch.setattr(mod, "commit_live_venue_plan", boom)
    _run_commit(monkeypatch, venues="kalshi")
    out = capsys.readouterr().out

    live = mod.read_live_portfolio_plan_for_venue(_DATE, "kalshi")
    assert live["positions"] == []
    assert "synthetic" in live["error"]
    assert "LIVE_PLAN_FAILED" in out
    assert mod.read_portfolio_plan_for_venue(_DATE, "kalshi")["positions"], "paper2 must survive"


# --------------------------------------------------------------------------
# The reader: live mode places the live plan; paper is untouched
# --------------------------------------------------------------------------


def _plans():
    from syndicate.features.shared.portfolio_commit import commit_portfolio

    contracted = _row("feed-1", price_source="venue_feed", venue_ticker=_TICKER, score=5.0)
    uncontracted = _row("agg-1", price_source="aggregator", score=9.9)
    paper2 = commit_portfolio(
        [uncontracted, contracted], selected_date=_DATE, settings=_settings(), prefer_placeable=True
    )
    from pipeline.portfolio_commit import commit_live_venue_plan

    live = commit_live_venue_plan([uncontracted, contracted], selected_date=_DATE, settings=_settings())
    assert len(paper2["positions"]) == 2 and len(live["positions"]) == 1
    return paper2, live


def _serve(monkeypatch, *, paper2, live):
    monkeypatch.setattr(
        "pipeline.portfolio_commit.read_portfolio_plan_for_venue", lambda date, venue: paper2
    )
    monkeypatch.setattr(
        "pipeline.portfolio_commit.read_live_portfolio_plan_for_venue", lambda date, venue: live
    )


def _arm_live(monkeypatch):
    monkeypatch.setenv("SYNDICATE_EXECUTION_ENABLED", "1")
    monkeypatch.setenv("SYNDICATE_EXECUTION_MODE", "live")
    monkeypatch.setenv("SYNDICATE_EXECUTION_LIVE_ARMED", "1")
    monkeypatch.setenv("SYNDICATE_EXECUTION_VENUE", "kalshi")


def _recording_submitter(monkeypatch):
    from pipeline import execute_portfolio as runner

    sent = []

    def submitter(request):
        sent.append(request)
        return {"status": "filled", "fill_price": 0.46, "fill_stake_dollars": 0.92}

    monkeypatch.setattr(runner, "_venue_submitter", lambda venue: submitter)
    return sent


def test_live_places_the_live_plan_and_never_meets_an_uncontracted_row(monkeypatch, capsys):
    from pipeline import execute_portfolio as runner

    paper2, live = _plans()
    _serve(monkeypatch, paper2=paper2, live=live)
    _arm_live(monkeypatch)
    sent = _recording_submitter(monkeypatch)

    result = runner.run_execution(_DATE, venue_scope="kalshi")
    out = capsys.readouterr().out

    assert result["plan_source"] == "live"
    assert result["positions"] == 1
    assert result["placed"] == 1
    assert "no_venue_ticker" not in result["refused"]
    assert [r.venue_ticker for r in sent] == [_TICKER]
    assert "REFUSED_NO_VENUE_TICKER" not in out
    assert "plan_source=live" in out


def test_live_without_a_live_plan_falls_back_to_paper2_and_SAYS_SO(monkeypatch, capsys):
    """The two workers deploy separately. Until the writer ships, the reader
    places paper2's book exactly as before -- and the refusal it always had
    still stops the uncontracted row before anything is written."""
    from pipeline import execute_portfolio as runner
    from syndicate.features.shared.execution_ledger import ledger_summary

    paper2, _ = _plans()
    _serve(monkeypatch, paper2=paper2, live=None)
    _arm_live(monkeypatch)
    sent = _recording_submitter(monkeypatch)

    result = runner.run_execution(_DATE, venue_scope="kalshi")
    out = capsys.readouterr().out

    assert result["plan_source"] == "paper2_fallback"
    assert result["positions"] == 2
    assert result["refused"] == {"no_venue_ticker": 1}
    assert [r.venue_ticker for r in sent] == [_TICKER]
    assert ledger_summary(_DATE)["orders"] == 1
    assert "LIVE_PLAN_ABSENT" in out
    assert "REFUSED_NO_VENUE_TICKER venue=kalshi" in out


def test_a_paper_scoped_run_still_books_the_whole_paper2_plan(monkeypatch):
    """PAPER IS UNCHANGED. The comparison book records what the strategy would
    have done at this venue, uncontracted rows included, and never reads the
    live plan."""
    from pipeline import execute_portfolio as runner

    paper2, _ = _plans()

    def never(date, venue):
        raise AssertionError("a paper run read the live plan")

    monkeypatch.setattr(
        "pipeline.portfolio_commit.read_portfolio_plan_for_venue", lambda date, venue: paper2
    )
    monkeypatch.setattr("pipeline.portfolio_commit.read_live_portfolio_plan_for_venue", never)
    monkeypatch.setenv("SYNDICATE_EXECUTION_ENABLED", "1")

    result = runner.run_execution(_DATE, venue_scope="kalshi")

    assert result["mode"] == "paper"
    assert result["plan_source"] == "paper2"
    assert result["venue"] == "paper:kalshi"
    assert result["placed"] == 2


def test_the_order_path_check_reads_the_plan_live_would_place(monkeypatch):
    """`ORDER_PATH` answers "what would live build", so it must read what live
    reads -- otherwise it keeps reporting `no_venue_ticker` for rows the placer
    never sees."""
    from pipeline import execute_portfolio as runner

    paper2, live = _plans()
    _serve(monkeypatch, paper2=paper2, live=live)

    report = runner.verify_order_paths(_DATE, venues=("kalshi",))

    assert report["plan_source"] == {"kalshi": "live"}
    verdicts = report["venues"]["kalshi"]["markets"]
    assert all("no_venue_ticker" not in counts for counts in verdicts.values()), verdicts
