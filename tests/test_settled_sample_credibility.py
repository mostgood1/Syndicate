"""Sample credibility is WIRED, and wiring it changes the stake.

`bankroll_manager.py:210` sizes every board candidate as

    staked_fraction = full_kelly_fraction * multiplier * credibility

where `credibility = _sample_credibility(settled_sample_size)` ramps from a 0.25
floor to 1.0 at 50 settled bets. **No caller ever passed
`settled_sample_size_by_sport`**, so it defaulted to `None`, every sport looked
up 0, and every market sized at the floor -- 1/16 Kelly rather than the intended
1/4.

The hook's own comment said this was "correct while `settled_count` is 0
platform-wide" and that stakes should rise "on evidence rather than on a constant
being edited". Measured 2026-09-04, settlement carried **1,594 settled orders**
(616 in the dominant sport at +5.76% ROI). The caveat had come due.

`test_deriving_the_map_changes_the_stake` is the reachability test and it comes
first on purpose: a wired hook that does not move the number is inert, and
inertness is what this whole file exists to catch.

CORRECTION 2026-09-04, SAME DAY: wiring it was right, the UNIT was not. The map
counted settled ORDER ROWS, and the same bet placed at Kalshi and at Polymarket
is two rows and one Bernoulli trial. NFL's 18 settled rows are 12 distinct
decisions, which is BELOW the 0.25 credibility floor (12/50 = 0.24) rather than
at 0.36. See the RECONCILIATION block below -- it recomputes both of this
system's "settled by sport" numbers from one ledger and pins the identity
between them.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pipeline.portfolio_commit as runner  # noqa: E402
from syndicate.features.bankroll_manager import (  # noqa: E402
    _MIN_SAMPLE_CREDIBILITY,
    _SAMPLE_SIZE_FOR_FULL_CREDIBILITY,
    _sample_credibility,
    compute_board_stake,
)

CANDIDATE = {
    "model_probability": 0.58,
    "fair_probability": 0.50,
    "decimal_price": 2.05,
    "price_reliability": 1.0,
}


# --- reachability: off != on -------------------------------------------------


def test_deriving_the_map_changes_the_stake():
    """THE test. An unfed sample floors credibility at 0.25; a real sample of 50+
    earns 1.0 -- a 4x stake on identical inputs."""
    floored = compute_board_stake(CANDIDATE, settled_sample_size=0)
    earned = compute_board_stake(CANDIDATE, settled_sample_size=616)
    f = float(floored["stake_fraction"])
    e = float(earned["stake_fraction"])
    assert f > 0.0, "the floor is deliberately non-zero, not a silent 0"
    assert e > f, "wiring the sample must RAISE the stake, or the hook is inert"
    # 0.25 -> 1.00 is 4x IN THE CREDIBILITY TERM, but `compute_bet_size` also
    # caps at `cap_fraction` (3.5% of bankroll per bet), so on a candidate with
    # a real edge the delivered ratio is 3.5x, not 4x. Asserting a bare 4x here
    # would be asserting a number the sizer does not produce.
    assert 3.0 < e / f <= 4.0 + 1e-9, "got %.4f -> %.4f (%.3fx)" % (f, e, e / f)
    assert e <= float(earned["cap_fraction"]) + 1e-9, "the per-bet cap still binds"


def test_the_full_4x_lands_where_the_cap_does_not_bind():
    """On a thin edge the cap is not reached, so credibility delivers its whole
    4x. This is what separates "the cap swallowed it" from "the hook is inert"."""
    thin = dict(CANDIDATE, model_probability=0.515)
    f = float(compute_board_stake(thin, settled_sample_size=0)["stake_fraction"])
    e = float(compute_board_stake(thin, settled_sample_size=616)["stake_fraction"])
    assert f > 0.0 and e < float(compute_board_stake(thin, settled_sample_size=616)["cap_fraction"])
    # `stake_fraction` is stored ROUNDED (0.001875 -> 0.00187), so the ratio of
    # two rounded numbers is 4.0107 rather than 4.0. Compare against the
    # rounding granularity instead of asserting a bare equality the stored
    # values cannot satisfy.
    # `stake_fraction` is stored rounded to 5dp, so `f` carries up to 5e-6 of
    # rounding error and the 4x multiplies it to 2e-5. The true values here are
    # exactly 4x (0.001875 -> 0.0075); the tolerance is the rounding, not slack.
    assert abs(e - 4.0 * f) <= 4 * 5e-6 + 1e-9, (
        "uncapped, credibility delivers 4x within rounding; got %.5f -> %.5f" % (f, e))
    assert 3.9 < e / f < 4.1


def test_the_floor_is_what_an_unfed_hook_produces():
    assert _sample_credibility(0) == _MIN_SAMPLE_CREDIBILITY == 0.25
    assert _sample_credibility(None) == 0.25


def test_credibility_ramps_and_caps():
    assert _sample_credibility(_SAMPLE_SIZE_FOR_FULL_CREDIBILITY) == 1.0
    assert _sample_credibility(616) == 1.0, "past full credibility it must not exceed 1.0"
    half = _sample_credibility(25)
    assert 0.49 < half < 0.51, "the ramp is linear in the sample size"


# ---------------------------------------------------------------------------
# THE RECONCILIATION. Two settlement numbers disagreed about NFL in production
# on 2026-09-04 and the disagreement sized real money:
#
#   /portfolio/paper  settlement_all_time.by_sport   nfl: orders=1, settled=0
#   refresh-worker    [portfolio_commit] SETTLED_SAMPLE          nfl: 18
#
# BOTH PRODUCERS WERE RIGHT AND THEY COUNT DIFFERENT POPULATIONS:
#
#   paper page   settled ORDER ROWS, portfolio book, MODE != LIVE. That filter
#                is load-bearing -- the page's banner says "no money moves" and
#                a live position rendered under it is a real wager wearing a
#                disclaimer that it is not one.
#   credibility  distinct settled DECISIONS, portfolio book, EVERY MODE. The
#                live book is 315 of the ledger's 979 settled rows and ALL 18
#                of the NFL, so paper-only is not a sample of our NFL edge.
#
# AND THE CONSUMER'S UNIT WAS WRONG. It counted rows. The same bet placed at
# Kalshi and at Polymarket is two rows and ONE Bernoulli trial -- the game
# resolves once, so the pair cannot disagree, and on production all six NFL
# pairs settled identically. 18 rows -> 12 decisions -> credibility 0.36 ->
# 0.25, the floor.
#
# These tests recompute BOTH numbers from ONE fixture ledger and pin the
# identity between them, so a future change to either side that breaks the
# reconciliation fails here rather than in a stake.
# ---------------------------------------------------------------------------

from syndicate.features.shared.paper_settlement import (  # noqa: E402
    settled_decisions_by_sport,
    settlement_summary,
)


def _order(
    *,
    sport,
    event_id,
    venue,
    mode="live",
    outcome="won",
    market="totals",
    side="over",
    line=37.5,
    player="",
    segment="full",
    stake=5.0,
    pnl=1.0,
    idem=None,
    opening_key=None,
    date="2026-08-28",
):
    """One ledger row, shaped the way `execution_ledger` writes it.

    `opening_key` carries the bookmaker, exactly as production does -- that is
    what makes the two-venue duplicate two ROWS with two distinct
    `position_key`s and one decision. Measured on a real pair 2026-09-04:

        ...|side=over|line=34.5|bookmaker=polymarket
        ...|side=over|line=34.5|bookmaker=kalshi
    """
    key = opening_key
    if key is None:
        key = (
            f"event_id={event_id}|market={market}|player={player}"
            f"|segment={segment}|side={side}|line={line}|bookmaker={venue}"
        )
    return {
        "sport": sport,
        "event_id": event_id,
        "market": market,
        "side": side,
        "line": line,
        "player_name": player or None,
        "segment": segment,
        "venue": venue,
        "book": venue,
        "mode": mode,
        "status": "filled",
        "outcome": outcome,
        "opening_key": key,
        "idempotency_key": idem or f"{venue}-{event_id}-{side}-{line}-{mode}",
        "selected_date": date,
        "fill_stake_dollars": stake,
        "pnl_dollars": pnl,
    }


# The fixture is the production SHAPE, scaled down so every number in the
# assertions can be counted by eye.
#
#   nfl     one preseason total, taken at BOTH venues, both won -> 2 rows, 1
#           decision. Plus one unsettled paper row, which is what made the paper
#           page read `orders=1, settled=0`.
#   mlb     two distinct live decisions and one paper decision, no overlap.
#   soccer  one decision taken in BOTH BOOKS -- paper and live -- which is the
#           other duplication class and the one `book_of` does not catch.
LEDGER = [
    # --- nfl: the reported symptom, in miniature ---------------------------
    _order(sport="nfl", event_id="nfl-1", venue="kalshi", line=34.5),
    _order(sport="nfl", event_id="nfl-1", venue="polymarket", line=34.5),
    _order(sport="nfl", event_id="nfl-2", venue="paper", mode="paper", outcome=""),
    # --- mlb: no duplication at all ----------------------------------------
    _order(sport="mlb", event_id="mlb-1", venue="kalshi", market="h2h", side="home", line=None),
    _order(sport="mlb", event_id="mlb-2", venue="polymarket", market="h2h", side="home", line=None),
    _order(sport="mlb", event_id="mlb-3", venue="paper", mode="paper", market="h2h", side="home", line=None),
    # --- soccer: the SAME decision in the paper book and the live book -----
    _order(sport="soccer", event_id="soc-1", venue="paper", mode="paper", market="h2h", side="home", line=None),
    _order(sport="soccer", event_id="soc-1", venue="kalshi", market="h2h", side="home", line=None),
    # --- the venue-scoped SHADOW book, which belongs to neither number -----
    _order(sport="nfl", event_id="nfl-1", venue="paper:kalshi", mode="paper", line=34.5),
    _order(sport="mlb", event_id="mlb-9", venue="paper:novig", mode="paper", market="h2h", side="home", line=None),
]


def _paper_page_by_sport(ledger):
    """What `/portfolio/paper` computes: the payload's own `mode != LIVE` filter
    (`intelligence.py`, `_paper_portfolio_payload`) and then `by_sport`."""
    paper_rows = [o for o in ledger if str(o.get("mode") or "paper") != "live"]
    summary = settlement_summary(None, orders=paper_rows)
    return {b["key"]: b["settled"] for b in summary["by_sport"]}


def test_the_two_numbers_disagree_about_nfl_exactly_as_production_did():
    """The symptom, reproduced from one ledger. If this ever stops reproducing,
    the fixture has drifted away from the bug it was written for."""
    page = _paper_page_by_sport(LEDGER)
    credibility = settled_decisions_by_sport(LEDGER)

    assert page.get("nfl", 0) == 0, "the paper page sees no settled NFL"
    assert credibility["nfl"] == 1, "the credibility sample does, and it is not zero"


def test_the_gap_is_fully_explained_and_nothing_is_left_over():
    """THE PIN. Every sport's credibility count must equal

        distinct decisions in the paper book
      + distinct decisions in the live book
      - decisions present in BOTH

    computed independently of the function under test. A drift on either side
    breaks this with the sport named, rather than moving a stake in silence.
    """
    from syndicate.features.shared.clv_position_join import market_key
    from syndicate.features.shared.paper_settlement import BOOK_PORTFOLIO, book_of

    expected = {}
    for row in LEDGER:
        if book_of(row) != BOOK_PORTFOLIO or not row.get("outcome"):
            continue
        sport = row["sport"]
        book = "live" if row.get("mode") == "live" else "paper"
        expected.setdefault(sport, {"paper": set(), "live": set()})
        expected[sport][book].add(market_key(row["opening_key"]))

    reconciled = {
        sport: len(b["paper"]) + len(b["live"]) - len(b["paper"] & b["live"])
        for sport, b in expected.items()
    }
    assert reconciled == {"nfl": 1, "mlb": 3, "soccer": 1}
    assert settled_decisions_by_sport(LEDGER) == reconciled


def test_one_bet_at_two_venues_is_one_piece_of_evidence():
    """The correction that moved NFL to the floor. Two rows, two position keys,
    one game -- and the pair CANNOT disagree, which is the whole reason it is
    one trial. Measured on production: 6 such NFL pairs, 6 identical outcomes."""
    two_venues = [r for r in LEDGER if r["event_id"] == "nfl-1" and r["venue"] in ("kalshi", "polymarket")]
    assert len(two_venues) == 2
    assert len({r["opening_key"] for r in two_venues}) == 2, "two distinct rows"
    assert len({r["outcome"] for r in two_venues}) == 1, "one outcome, necessarily"
    assert settled_decisions_by_sport(two_venues) == {"nfl": 1}


def test_the_same_decision_in_both_books_is_also_counted_once():
    """The paper book and the live book overlap -- measured 2026-09-04, 27
    settled decisions appear in both. `book_of` does not catch this: both rows
    are in the PORTFOLIO book, one just has `venue="paper"`."""
    both_books = [r for r in LEDGER if r["event_id"] == "soc-1"]
    assert {r["mode"] for r in both_books} == {"paper", "live"}
    assert settled_decisions_by_sport(both_books) == {"soccer": 1}


def test_the_row_count_and_the_decision_count_are_different_numbers():
    """The mutation this file exists to catch. If someone reinstates the row
    count, `nfl` reads 2 rather than 1 and this goes red."""
    summary = settlement_summary(None, orders=LEDGER)
    rows_by_sport = {b["key"]: b["settled"] for b in summary["by_sport"]}
    decisions = settled_decisions_by_sport(LEDGER)

    assert rows_by_sport["nfl"] == 2, "the ledger really does hold two NFL rows"
    assert decisions["nfl"] == 1, "and they are one decision"
    assert rows_by_sport != decisions, (
        "a settled-ROW count is not a sample size; if these are equal the dedupe "
        "is inert and NFL is being sized on duplicates"
    )


def test_the_shadow_books_are_in_neither_number():
    """`paper:kalshi` and friends are the venue-scoped comparison book. Counting
    them would restore the double-count `book_of` was written to remove."""
    shadow_only = [r for r in LEDGER if str(r["venue"]).startswith("paper:")]
    assert shadow_only, "fixture must actually contain shadow rows"
    assert settled_decisions_by_sport(shadow_only) == {}


# --- the derivation ----------------------------------------------------------


def test_it_lowercases_the_sport_and_SUMS_a_case_collision():
    """The consumption site looks the sport up as
    `str(row.get("sport") or "").strip().lower()`. A key that does not match is
    silently 0 -- which is the floor again, i.e. the exact bug, re-created.

    AND A COLLISION MERGES RATHER THAN OVERWRITING. Every ledger row measured
    2026-09-04 was already lowercase (596 live + 1,847 paper), so this is
    latent; the previous implementation ASSIGNED into the map, so a future
    `"NFL"` beside an `"nfl"` would have discarded one of them silently.
    """
    mixed = [
        _order(sport="NFL", event_id="a", venue="kalshi", line=1.5),
        _order(sport="nfl", event_id="b", venue="kalshi", line=2.5),
        _order(sport=" Soccer ", event_id="c", venue="kalshi", market="h2h", side="home", line=None),
    ]
    assert settled_decisions_by_sport(mixed) == {"nfl": 2, "soccer": 1}


def test_it_drops_unknown_and_unsettled_rows():
    """`unknown` is not a sport, it is a failed sport join. An ungraded row is
    not evidence yet."""
    rows = [
        _order(sport="unknown", event_id="u", venue="kalshi"),
        _order(sport="", event_id="v", venue="kalshi", line=1.5),
        _order(sport="nhl", event_id="w", venue="kalshi", outcome="", line=2.5),
        _order(sport="mlb", event_id="x", venue="kalshi", line=3.5),
    ]
    assert settled_decisions_by_sport(rows) == {"mlb": 1}


def test_an_unkeyable_row_counts_as_its_own_decision():
    """Dropping it would UNDERSTATE the sample, and understating is the
    direction that silently re-floors a sport. It cannot be deduped, so it is
    its own decision -- never merged with another unkeyable row."""
    rows = [
        _order(sport="mlb", event_id="", venue="kalshi", opening_key="", idem="one"),
        _order(sport="mlb", event_id="", venue="kalshi", opening_key="", idem="two"),
    ]
    assert settled_decisions_by_sport(rows) == {"mlb": 2}


def test_it_reads_the_whole_ledger_when_no_orders_are_passed(monkeypatch):
    """`settled_sample_size_by_sport=None` means "work it out" -- from the
    ledger, both modes, not from whatever a page happened to filter."""
    monkeypatch.setattr(
        "syndicate.features.shared.execution_ledger._load",
        lambda *a, **k: {"orders": LEDGER},
    )
    assert runner._settled_sample_size_by_sport() == {"nfl": 1, "mlb": 3, "soccer": 1}


def test_a_settlement_failure_reverts_rather_than_breaking_the_commit(monkeypatch):
    """Returning {} restores the OLD behaviour. Raising would take the whole
    plan down, which is a worse outcome than sizing conservatively."""
    def boom(*a, **k):
        raise RuntimeError("ledger unreadable")

    monkeypatch.setattr("syndicate.features.shared.execution_ledger._load", boom)
    assert runner._settled_sample_size_by_sport() == {}


def test_malformed_rows_do_not_break_the_derivation(monkeypatch):
    monkeypatch.setattr(
        "syndicate.features.shared.execution_ledger._load",
        lambda *a, **k: {"orders": [
            "not-a-mapping",
            None,
            _order(sport="nfl", event_id="ok", venue="kalshi"),
        ]},
    )
    assert runner._settled_sample_size_by_sport() == {"nfl": 1}


def test_an_empty_ledger_yields_an_empty_map(monkeypatch):
    monkeypatch.setattr(
        "syndicate.features.shared.execution_ledger._load",
        lambda *a, **k: {"orders": []},
    )
    assert runner._settled_sample_size_by_sport() == {}


# ---------------------------------------------------------------------------
# THE WIRING ITSELF. Everything above tests the derivation and the sizer in
# ISOLATION -- and a mutation check proved that is not enough: deleting the two
# lines in `run_portfolio_commit` that call the derivation left every test above
# GREEN. A hook can be perfect and still never be called, which is the exact
# failure this whole file was written about.
# ---------------------------------------------------------------------------


def _row():
    return {
        "sport": "mlb",
        "event_id": "evt-1",
        "market": "h2h",
        "side": "home",
        "price": -110,
        "ev_pct": 9.0,
        "model_edge_pct": 8.0,
        "model_probability": 0.58,
        "fair_probability": 0.50,
        "score": {"price_reliability": 1.0},
    }


def test_run_portfolio_commit_ACTUALLY_PASSES_the_derived_map(tmp_path, monkeypatch):
    """Deleting the derivation call must turn THIS red.

    Asserts the value reaching `commit_portfolio`, not the value the helper can
    produce -- those are different claims and only the first one is the fix.
    """
    monkeypatch.setenv("SYNDICATE_REPORTS_ROOT", str(tmp_path))
    monkeypatch.setenv("SYNDICATE_PORTFOLIO_COMMIT_ENABLED", "1")
    monkeypatch.setattr(
        "pipeline.intelligence_state.read_layer2_shortlist",
        lambda date: {"rows": [_row()]},
    )
    monkeypatch.setattr(
        "syndicate.features.shared.execution_ledger._load",
        lambda *a, **k: {"orders": [
            _order(sport="mlb", event_id=f"e{i}", venue="kalshi",
                   market="h2h", side="home", line=None)
            for i in range(616)
        ]},
    )

    seen = {}
    real = runner.commit_portfolio

    def spy(rows, **kwargs):
        seen["samples"] = kwargs.get("settled_sample_size_by_sport")
        return real(rows, **kwargs)

    monkeypatch.setattr(runner, "commit_portfolio", spy)
    runner.run_portfolio_commit("2026-08-22")

    assert "samples" in seen, "commit_portfolio was never called"
    assert seen["samples"] == {"mlb": 616}, (
        "the derived per-sport sample must REACH the sizer; got %r" % (seen["samples"],))


def test_an_explicit_map_is_not_overwritten_by_the_derivation(tmp_path, monkeypatch):
    """`None` means "work it out"; a supplied map means the caller has decided.
    Conflating them would make the argument untestable and unoverridable."""
    monkeypatch.setenv("SYNDICATE_REPORTS_ROOT", str(tmp_path))
    monkeypatch.setenv("SYNDICATE_PORTFOLIO_COMMIT_ENABLED", "1")
    monkeypatch.setattr(
        "pipeline.intelligence_state.read_layer2_shortlist",
        lambda date: {"rows": [_row()]},
    )
    monkeypatch.setattr(
        "syndicate.features.shared.execution_ledger._load",
        lambda *a, **k: {"orders": [
            _order(sport="mlb", event_id=f"e{i}", venue="kalshi",
                   market="h2h", side="home", line=None)
            for i in range(616)
        ]},
    )

    seen = {}
    real = runner.commit_portfolio

    def spy(rows, **kwargs):
        seen["samples"] = kwargs.get("settled_sample_size_by_sport")
        return real(rows, **kwargs)

    monkeypatch.setattr(runner, "commit_portfolio", spy)
    runner.run_portfolio_commit("2026-08-22", settled_sample_size_by_sport={"mlb": 3})
    assert seen["samples"] == {"mlb": 3}, "an explicit map must win over the derivation"
