"""`#524`. The board's row budget is the WHOLE board's, and a payload that will
not fit sheds rows instead of freezing.

WHY THIS EXISTS. Two failures share one cause -- the persisted shortlist is a
single keyvalue write, and nothing sized it against that write.

MEASURED IN PRODUCTION 2026-08-23T00:0xZ:

    LAYER2_SHORTLIST rows=1600  (four sports, all at the 400/sport cap)
    KEYVALUE_WRITE_LARGE size_bytes=5,747,257 max_bytes=8,388,608     68.5%

3,592 bytes/row, ~735 rows of headroom -- less than two more sports at cap.
NCAAF opens ~08-29 (~7.19MB, 86%); NCAAB in November breaches. The cliff is on
the CALENDAR, so it arrives whether or not anyone edits this code.

And it arrives as the worst available failure. Above the ceiling
`write_json_file` RAISES, and both call sites of `write_layer2_shortlist` catch
it and return, so the worker keeps running while the board serves its last good
copy forever. A crash restarts; a caught refusal does not, and it presents as
"the board is stale" -- the same symptom as a dozen unrelated causes.

Two fixes, tested here: a TOTAL budget so a fifth sport redistributes instead of
adding, and a SHED so an over-ceiling payload loses its worst rows rather than
all of its freshness.
"""

from __future__ import annotations

import json

import pytest

from syndicate.features.shared import layer2_board
from pipeline import intelligence_state


# ---------------------------------------------------------------------------
# allocate_row_budget
# ---------------------------------------------------------------------------


def test_four_sports_at_cap_is_unchanged_by_the_total():
    """TODAY'S BOARD MUST NOT MOVE. The default total is exactly the measured
    four-sport board, so this change is a no-op until a fifth sport arrives --
    which is what makes it safe to ship on a live slate."""
    budget = layer2_board.allocate_row_budget(
        {"mlb": 5000, "nfl": 5000, "soccer": 20025, "wnba": 5000},
        total=1600,
        per_sport=400,
    )
    assert budget == {"mlb": 400, "nfl": 400, "soccer": 400, "wnba": 400}


def test_a_fifth_sport_redistributes_instead_of_adding():
    """THE CLIFF, removed. NCAAF opening must not grow the payload."""
    budget = layer2_board.allocate_row_budget(
        {s: 5000 for s in ("mlb", "nfl", "soccer", "wnba", "ncaaf")},
        total=1600,
        per_sport=400,
    )
    assert sum(budget.values()) == 1600, budget
    assert max(budget.values()) <= 400


def test_eight_sports_still_sum_to_the_total():
    budget = layer2_board.allocate_row_budget(
        {s: 5000 for s in ("mlb", "nba", "nfl", "nhl", "soccer", "wnba", "ncaaf", "ncaab")},
        total=1600,
        per_sport=400,
    )
    assert sum(budget.values()) == 1600
    assert set(budget.values()) == {200}


def test_a_sport_that_cannot_fill_its_share_donates_the_rest():
    """THE NAIVE SPLIT WASTES THE BUDGET. Measured tonight, NFL held 275 rows
    against a 400 allowance while soccer had 20,025 to offer and was capped. A
    flat `total // n` would shrink the sports that CAN fill their share in order
    to reserve slots for one that cannot."""
    # FIVE sports, so the fair share (320) is BELOW the per-sport ceiling (400)
    # and there is somewhere for a donation to go. My first version of this test
    # used four and asserted the budget summed to 1,600 -- impossible, because
    # three sports at a 400 ceiling plus NFL's 23 caps out at 1,223. The test was
    # wrong, not the allocator; with everyone already at the ceiling there is
    # nothing to donate to.
    budget = layer2_board.allocate_row_budget(
        {"mlb": 5000, "nfl": 23, "soccer": 5000, "wnba": 5000, "ncaaf": 5000},
        total=1600,
        per_sport=400,
    )
    assert budget["nfl"] == 23, "never allocate a sport more than it has"
    assert sum(budget.values()) == 1600, "the 297 NFL could not use must be re-used"
    # WITHIN ONE, not equal: 1,577 rows do not divide by four, and the remainder
    # has to land somewhere. `test_it_is_deterministic` pins that it always lands
    # in the same place, which is the property that actually matters.
    others = [budget[s] for s in ("mlb", "soccer", "wnba", "ncaaf")]
    assert max(others) - min(others) <= 1, budget
    assert min(others) > 1600 // 5, "a flat share would have wasted NFL's unused slots"


def test_the_ceiling_can_leave_the_total_unspent_and_that_is_correct():
    """The counterpart. Four sports, one with 23 rows: three at the 400 ceiling
    plus 23 is 1,223, and the remaining 377 have nowhere legal to go. Under-
    spending the total is the right answer -- spending it would mean breaching
    the per-sport ceiling that stops one sport owning the board."""
    budget = layer2_board.allocate_row_budget(
        {"mlb": 5000, "nfl": 23, "soccer": 5000, "wnba": 5000},
        total=1600,
        per_sport=400,
    )
    assert sum(budget.values()) == 1223
    assert budget == {"mlb": 400, "nfl": 23, "soccer": 400, "wnba": 400}


def test_the_per_sport_ceiling_still_binds_on_a_quiet_slate():
    """One sport must not take the whole board just because it is alone --
    soccer alone is 20,025 grid rows."""
    budget = layer2_board.allocate_row_budget({"soccer": 20025}, total=1600, per_sport=400)
    assert budget == {"soccer": 400}


def test_the_total_never_over_allocates_a_thin_slate():
    budget = layer2_board.allocate_row_budget({"mlb": 10, "wnba": 4}, total=1600, per_sport=400)
    assert budget == {"mlb": 10, "wnba": 4}


def test_a_minimum_keeps_a_sport_worth_its_tab():
    budget = layer2_board.allocate_row_budget(
        {s: 5000 for s in [f"s{i}" for i in range(20)]}, total=100, per_sport=400, minimum=30
    )
    assert all(v >= 30 for v in budget.values()), budget


def test_it_is_deterministic():
    """The remainder of an uneven split has to land somewhere, and it must land
    in the same place every build or two identical pools give two boards."""
    avail = {"mlb": 5000, "nfl": 5000, "soccer": 5000}
    first = layer2_board.allocate_row_budget(avail, total=1000, per_sport=400)
    for _ in range(5):
        assert layer2_board.allocate_row_budget(avail, total=1000, per_sport=400) == first


def test_no_sports_is_not_a_crash():
    assert layer2_board.allocate_row_budget({}, total=1600, per_sport=400) == {}


# ---------------------------------------------------------------------------
# select_shortlist wiring -- an allocator nothing calls is an inert feature
# ---------------------------------------------------------------------------


def _rows(sport, n, ev=5.0):
    return [
        {
            "sport": sport,
            "kind": "game" if i % 2 else "prop",
            "market": "h2h",
            "side": "home",
            "home_team": f"H{i}",
            "away_team": f"A{i}",
            "event_id": f"{sport}-e{i}",
            "ev_pct": ev,
            "score": {"score": ev - i * 0.001},
            "quote": {"price": -110, "bookmaker": "bk", "age_seconds": 30},
        }
        for i in range(n)
    ]


def test_the_shortlist_actually_applies_the_total():
    """REACHABILITY, before correctness. off != on."""
    pool = _rows("mlb", 500) + _rows("nfl", 500) + _rows("soccer", 500) + _rows("wnba", 500) + _rows("ncaaf", 500)
    wide = layer2_board.select_shortlist(pool, per_sport=400, rows_total=10_000, min_value_pct=-100.0, horizon_days=None)
    tight = layer2_board.select_shortlist(pool, per_sport=400, rows_total=1600, min_value_pct=-100.0, horizon_days=None)
    assert len(wide["rows"]) > len(tight["rows"]), "the total is inert"
    assert len(tight["rows"]) <= 1600


def test_the_allowance_is_reported_not_inferred():
    """A board that shrank because a fifth sport came into season must not look
    like a board that shrank because its pool did."""
    pool = _rows("mlb", 500) + _rows("nfl", 500)
    result = layer2_board.select_shortlist(pool, per_sport=400, rows_total=600, min_value_pct=-100.0, horizon_days=None)
    assert result["rows_total_budget"] == 600
    assert set(result["rows_allocated_by_sport"]) == {"mlb", "nfl"}


# ---------------------------------------------------------------------------
# the shed
# ---------------------------------------------------------------------------


def _payload(n_rows, row_bytes=400):
    filler = "x" * row_bytes
    return {"rows": [{"i": i, "pad": filler} for i in range(n_rows)], "per_sport": {}, "cards": []}


def test_a_payload_that_fits_is_untouched():
    payload = _payload(10)
    assert intelligence_state._shed_rows_to_fit_keyvalue(payload) is payload


def test_an_oversized_payload_is_shed_rather_than_refused(monkeypatch):
    """THE REGRESSION. Before this, the write raised, both callers swallowed it,
    and the board froze on its last good copy."""
    monkeypatch.setattr(
        "syndicate.features.shared.refresh_state_store._keyvalue_max_bytes", lambda: 200_000
    )
    payload = _payload(2000)
    assert len(json.dumps(payload, default=str)) > 200_000, "the fixture must exceed the ceiling"

    out = intelligence_state._shed_rows_to_fit_keyvalue(payload)
    assert len(out["rows"]) < 2000
    assert len(json.dumps(out, default=str)) < 200_000, "shed and STILL too big"


def test_the_shed_keeps_the_best_rows():
    """Rows arrive ranked, so shedding must come off the tail."""
    import pipeline.intelligence_state as m

    original = _payload(2000)
    original["rows"] = [{"i": i, "pad": "x" * 400} for i in range(2000)]
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("syndicate.features.shared.refresh_state_store._keyvalue_max_bytes", lambda: 200_000)
        out = m._shed_rows_to_fit_keyvalue(original)
    assert out["rows"][0]["i"] == 0, "the top row must survive"
    assert [r["i"] for r in out["rows"]] == list(range(len(out["rows"]))), "shed from the tail"


def test_the_shed_is_never_silent(monkeypatch, capsys):
    monkeypatch.setattr(
        "syndicate.features.shared.refresh_state_store._keyvalue_max_bytes", lambda: 200_000
    )
    out = intelligence_state._shed_rows_to_fit_keyvalue(_payload(2000))
    printed = capsys.readouterr().out
    assert "SHORTLIST_SHED_TO_FIT" in printed
    assert "rows_shed_for_keyvalue" in out, "a shed board must declare itself in the payload"
    assert out["rows_shed_for_keyvalue"]["dropped"] > 0


def test_an_over_ceiling_fixed_cost_says_so_instead_of_pretending(monkeypatch, capsys):
    """If `cards`/`openings` alone exceed the ceiling, no number of rows helps.
    That needs a different fix and must not read as a shed that failed."""
    monkeypatch.setattr(
        "syndicate.features.shared.refresh_state_store._keyvalue_max_bytes", lambda: 1000
    )
    payload = {"rows": [{"i": 0}], "cards": ["y" * 5000]}
    out = intelligence_state._shed_rows_to_fit_keyvalue(payload)
    printed = capsys.readouterr().out
    assert "SHORTLIST_SHED_IMPOSSIBLE" in printed
    assert out is payload, "must not half-shed a payload shedding cannot save"


def test_the_shed_never_raises(monkeypatch, capsys):
    """A rescue path that can throw is worse than the bug it rescues."""
    def _boom():
        raise RuntimeError("no ceiling for you")

    monkeypatch.setattr("syndicate.features.shared.refresh_state_store._keyvalue_max_bytes", _boom)
    payload = _payload(50)
    assert intelligence_state._shed_rows_to_fit_keyvalue(payload) is payload
    assert "SHORTLIST_SHED_FAILED" in capsys.readouterr().out
