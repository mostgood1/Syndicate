"""Layer 1 grid -> Layer 2 shortlist, built worker-side into the pool artifact.

WHY THIS EXISTS. Layer 2 was building its own candidate pool while Layer 1 built
a much better one, and they disagreed badly (measured 2026-08-07, MLB):

    Layer 1   2,726 priced market instances   (1,221 prop rows)
    Layer 2     229 game candidates           (   18 prop rows)

Starved, not stale. `layer2_board.py` was written to close that and shipped with
23 tests and ZERO callers. This is the join that gives it one.

ARTIFACT-BASED. The shortlist lands in the candidate-pool payload, which is
persisted and read by web via `read_intelligence_board_state`. Web computes
nothing -- and beyond CLAUDE.md's rule, a board recomputed per request cannot be
settled, because there is no record of what was recommended at what price.
"""

from __future__ import annotations

import pytest

from pipeline.layer2_shortlist import build_layer2_shortlist


def _quote(**overrides):
    """The real book_quotes row shape.

    Field is `selection`, NOT `side` -- a hand-rolled fixture using `side`
    produces zero grid rows and looks exactly like a broken join.
    """
    row = {
        "sport": "mlb",
        "kind": "game",
        "event_id": "evt-1",
        "segment": "full_game",
        "market": "h2h",
        "player_name": "",
        "selection": "home",
        "line": None,
        "price": -110,
        "bookmaker": "draftkings",
        "home_team": "Baltimore Orioles",
        "away_team": "Los Angeles Angels",
        "commence_time": "2026-08-08T23:05:00Z",
        "snapshot_ts": "2026-08-08T19:55:00Z",
    }
    row.update(overrides)
    return row


def _two_sided(sport="mlb", event_id="evt-1"):
    rows = []
    for book, home_price, away_price in (("draftkings", -120, 105), ("fanduel", -115, 100), ("betmgm", -125, 110)):
        rows.append(_quote(sport=sport, event_id=event_id, bookmaker=book, selection="home", price=home_price))
        rows.append(_quote(sport=sport, event_id=event_id, bookmaker=book, selection="away", price=away_price))
    return rows


@pytest.fixture
def shard(monkeypatch):
    """Serve shards per sport without touching disk or the network."""
    store: dict[str, list] = {}

    def _read(sport, date_str):
        return store.get(str(sport).lower(), [])

    monkeypatch.setattr("syndicate.features.shared.odds_book_quotes.read_book_quotes", _read)
    return store


def test_a_priced_market_becomes_ranked_candidates(shard):
    shard["mlb"] = _two_sided()
    out = build_layer2_shortlist("2026-08-08", ["mlb"])

    assert out["per_sport_ingest"]["mlb"]["grid_rows"] == 1
    assert out["per_sport_ingest"]["mlb"]["sides_priced"] == 2
    assert len(out["rows"]) == 2, "a two-sided market should yield one candidate per side"


def test_each_row_carries_the_price_it_recommends(shard):
    """Settlement needs WHAT was recommended at WHAT price. A row that cannot
    state its own price makes `settled: 0` structural."""
    shard["mlb"] = _two_sided()
    row = build_layer2_shortlist("2026-08-08", ["mlb"])["rows"][0]

    assert row["quote"]["price"] is not None
    assert row["quote"]["bookmaker"]
    assert row["sport"] == "mlb"
    assert row["event_id"] == "evt-1"
    assert row["side"] in {"home", "away"}


def test_only_requested_sports_are_read(shard):
    """The read set must never widen. All eight sports are never active at once
    (4 today, 7 at the October peak), and an unrequested sport's shard costs a
    first read that is never returned to the OS."""
    seen = []

    def _read(sport, date_str):
        seen.append(sport)
        return _two_sided(sport=sport)

    import syndicate.features.shared.odds_book_quotes as obq

    original = obq.read_book_quotes
    obq.read_book_quotes = _read
    try:
        build_layer2_shortlist("2026-08-08", ["mlb", "wnba"])
    finally:
        obq.read_book_quotes = original

    assert seen == ["mlb", "wnba"], f"read a sport nobody asked for: {seen}"


def test_sport_with_no_shard_is_reported_not_hidden(shard):
    """A sport with zero rows must be attributable to its slate rather than
    silently absent -- the same reasoning as audit_slate_coverage's THIN."""
    shard["mlb"] = _two_sided()
    out = build_layer2_shortlist("2026-08-08", ["mlb", "wnba"])

    assert out["per_sport_ingest"]["wnba"]["quote_rows"] == 0
    assert out["per_sport_ingest"]["wnba"]["opportunities"] == 0


def test_ingest_stats_do_not_clobber_the_selection_report(shard):
    """`select_shortlist` already returns `per_sport` (what was SELECTED).
    These stats are what came IN. Overwriting one with the other destroys the
    accounting that makes a zero attributable."""
    shard["mlb"] = _two_sided()
    out = build_layer2_shortlist("2026-08-08", ["mlb"])

    assert "per_sport" in out and "per_sport_ingest" in out
    assert out["per_sport"]["mlb"]["selected"] == 2
    assert out["per_sport_ingest"]["mlb"]["quote_rows"] == 6


def test_one_sport_failing_does_not_lose_the_others(monkeypatch):
    """Layer 2 is additive to a board that already works. A bad shard for one
    sport must not zero the shortlist."""
    def _read(sport, date_str):
        if sport == "wnba":
            raise RuntimeError("corrupt shard")
        return _two_sided(sport=sport)

    monkeypatch.setattr("syndicate.features.shared.odds_book_quotes.read_book_quotes", _read)
    out = build_layer2_shortlist("2026-08-08", ["mlb", "wnba"])

    assert len(out["rows"]) == 2, "a failing sport took the whole shortlist down"
    assert "error" in out["per_sport_ingest"]["wnba"]


def test_never_raises_on_total_failure(monkeypatch):
    def _boom(*_a, **_k):
        raise RuntimeError("everything is broken")

    monkeypatch.setattr("syndicate.features.shared.odds_book_quotes.read_book_quotes", _boom)
    out = build_layer2_shortlist("2026-08-08", ["mlb"])
    assert out["rows"] == []


def test_empty_sport_list_is_a_no_op(shard):
    out = build_layer2_shortlist("2026-08-08", [])
    assert out["rows"] == []
    assert out["opportunities_considered"] == 0


def test_blank_sport_slugs_are_skipped(shard):
    shard["mlb"] = _two_sided()
    out = build_layer2_shortlist("2026-08-08", ["mlb", "", None])
    assert set(out["per_sport_ingest"]) == {"mlb"}


def test_multiple_sports_are_bucketed_separately(monkeypatch):
    """select_shortlist buckets per sport; a missing slug collapses every sport
    into one bucket and silently starves the smaller ones."""
    def _read(sport, date_str):
        return _two_sided(sport=sport, event_id=f"evt-{sport}")

    monkeypatch.setattr("syndicate.features.shared.odds_book_quotes.read_book_quotes", _read)
    out = build_layer2_shortlist("2026-08-08", ["mlb", "wnba"])

    assert set(out["per_sport"]) == {"mlb", "wnba"}
    assert {row["sport"] for row in out["rows"]} == {"mlb", "wnba"}


def test_shortlist_policy_is_layer2_boards_not_redefined_here(shard):
    """100 per sport, floor 30 per kind, horizon 1 -- inherited, not restated.

    Two copies of a policy that can drift is how the dead-market rule ended up
    written twice in two languages (#244, removed in #245).
    """
    from syndicate.features.shared import layer2_board

    shard["mlb"] = _two_sided()
    out = build_layer2_shortlist("2026-08-08", ["mlb"])

    assert out["per_sport_limit"] == layer2_board.SHORTLIST_ROWS_PER_SPORT == 100
    assert out["kind_floor"] == layer2_board.SHORTLIST_KIND_FLOOR == 30
    assert out["horizon_days"] == layer2_board.SHORTLIST_HORIZON_DAYS == 1


def test_forward_view_is_reachable(monkeypatch):
    """horizon_days=None is the Forward view. None is a MEANINGFUL value, so a
    plain None default would have made it unreachable while looking default."""
    far = _quote(commence_time="2026-12-25T23:05:00Z")
    rows = []
    for book, hp, ap in (("draftkings", -120, 105), ("fanduel", -115, 100)):
        rows.append({**far, "bookmaker": book, "selection": "home", "price": hp})
        rows.append({**far, "bookmaker": book, "selection": "away", "price": ap})
    monkeypatch.setattr("syndicate.features.shared.odds_book_quotes.read_book_quotes", lambda s, d: rows)

    scoped = build_layer2_shortlist("2026-08-08", ["mlb"])
    forward = build_layer2_shortlist("2026-08-08", ["mlb"], horizon_days=None)

    assert scoped["rows"] == [], "a December game should be outside a 1-day horizon"
    assert scoped["rows_beyond_horizon"] > 0, "dropped rows must be counted, not silently lost"
    assert len(forward["rows"]) == 2, "Forward view unreachable"


# ---------------------------------------------------------------------------
# The key must survive EVERY hop from pool to served response.
# ---------------------------------------------------------------------------


def test_shortlist_survives_the_pool_to_board_state_chain():
    """Each layer builds an EXPLICIT key list rather than passing keys through.

    Found before deploying, not after: the shortlist would have been built on
    the worker, persisted into the candidate pool, and been invisible on the
    board -- because _build_intelligence_board_state constructs a fixed dict and
    never copied it. Three hops, each able to drop it silently:

        _build_candidate_pool        -> pool["layer2_shortlist"]
        _compute_board_publication_response -> response["layer2_shortlist"]
        _build_intelligence_board_state     -> state["layer2_shortlist"]
        slice_intelligence_board_state_for_request -> dict(state), passes through

    This test is the guard on that chain. If a future refactor drops the key at
    any hop, the board goes quietly empty and nothing else fails.
    """
    import inspect

    from pipeline import intelligence_state as istate

    publication = inspect.getsource(istate.IntelligenceStateService._compute_board_publication_response)
    board_state = inspect.getsource(istate.IntelligenceStateService._build_intelligence_board_state)
    pool_empty = inspect.getsource(istate.IntelligenceStateService._empty_candidate_pool)

    assert "layer2_shortlist" in publication, "dropped between the pool and the publication response"
    assert "layer2_shortlist" in board_state, "dropped between the response and the persisted board state"
    assert "layer2_shortlist" in pool_empty, "an aborted build must still carry the key, present-but-empty"


def test_slice_passes_the_shortlist_through():
    """The last hop is a pass-through, so it needs no naming -- but prove it,
    because the other three are not."""
    from pipeline.intelligence_state import slice_intelligence_board_state_for_request

    state = {
        "selected_date": "2026-08-08",
        "by_sport": {},
        "ranked_all": [],
        "layer2_shortlist": {"rows": [{"sport": "mlb", "side": "home"}]},
    }
    sliced = slice_intelligence_board_state_for_request(state, sport="all", limit=None)
    assert sliced["layer2_shortlist"]["rows"], "the slice dropped the shortlist"
