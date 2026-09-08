"""The ledger could not see the segment the execution side actually bets.

MEASURED 2026-09-07 ON PRODUCTION. Seven MLB ledger days, 28,763 records:
**every single one `segment=full`**. Not one `first5`, `first3` or `first1`. The
only `withheld_reason` values present were the three that are decided BELOW the
attach site -- `prob_interval_swamps_edge`, `no_two_sided_market_price`,
`live_resim_published_no_distribution_for_this_market`.

That is not a segment blind spot, it is a wrong DENOMINATOR. The join refuses in
two places relative to `row["live_gameline"] = block`: refusals after it land in
the ledger as `priceable: false` rows, refusals before it vanished. So
`14,003 of 27,249 priceable (51.4%)` was a rate over the post-attach population
presented as a rate over the live one.

AND THE MISSING PART IS THE MAJORITY. The join's own coverage counters on the
two most recent MLB builds, same day: **25 of 29** and **34 of 41** rows
considered were refused `segment_is_not_full_game` -- 86% and 83%. It is the
largest category of live rows there is. It also costs money rather than tidiness:
the segment mis-grade confirmed this session covered 49 settled orders and every
one of them was **first5**.

WHAT IS NOT BEING FIXED HERE, deliberately. The refusal itself is CORRECT and
carries its own measurement: a full-game projection priced against a first-inning
market produced **+42.43 pp** of edge that was entirely an artifact of the
mismatch (SD @ CLE, 2026-08-16). Counting is not pricing. A refusal record
carries no probability, no market price and no edge, so nothing downstream can
promote one into the other.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared.live_gameline_join import (  # noqa: E402
    REASON_SEGMENT_NOT_FULL_GAME,
    REFUSAL_KEY,
    attach_live_gamelines,
)
from syndicate.features.shared.live_gameline_ledger import (  # noqa: E402
    _MAX_RECORDS_PER_BUILD,
    append_records,
    build_records,
    record_key,
)


def _grid_row(*, segment: str, market: str = "h2h", line=None):
    """A live game row as the board grid carries it, before any join runs."""
    return {
        "kind": "game",
        "market": market,
        "segment": segment,
        "line": line,
        "event_id": "1145a9db",
        "home_team": "Athletics",
        "away_team": "Texas Rangers",
        "books": ["pinnacle", "fanduel"],
        "age_seconds": 42.5,
        "updated_at": "2026-09-07T02:00:00Z",
        "game": {"state": "live", "home_score": 3, "away_score": 1},
        "projection": {},
    }


def _full_game_hit():
    """An index entry good enough for a full-game row to price against."""
    return {
        "game_pk": 824966,
        "home_win_prob": 0.62,
        "sims_run": 4000,
        "total_mean": 8.4,
        "home_margin": 0.6,
        "total_runs_dist": {},
        "margin_dist": {},
        "as_of": "2026-09-07T02:00:00Z",
        "carried_forward": False,
        "analytic_markets": {},
        "progress": {"fraction": 0.4, "inning": 4, "half": "top", "outs": 1},
        "pregame_home_win_prob": 0.55,
    }


def _index():
    return {("texas rangers", "athletics"): _full_game_hit()}


# ---------------------------------------------------------------------------
# REACHABILITY. This is the whole point of the change and it goes through BOTH
# halves -- the join stamping the key and the ledger emitting the record. Revert
# either one and this test fails. Asserting on the ledger record alone would
# pass against a hand-stamped row and prove nothing about the wiring, which is
# the `presence != reachability` failure this repo keeps paying for.
# ---------------------------------------------------------------------------
class TestTheSegmentRowNowReachesTheLedger:
    def test_a_first5_row_is_RECORDED_after_the_real_join_refuses_it(self):
        grid = [_grid_row(segment="first5")]
        coverage = attach_live_gamelines(grid, _index())

        # the join still REFUSES it -- nothing here relaxes the guard
        assert coverage["rows_live_gameline_priceable"] == 0
        assert coverage["withheld_by_reason"] == {REASON_SEGMENT_NOT_FULL_GAME: 1}
        assert "live_gameline" not in grid[0]

        records = build_records(grid, sport="mlb", date_str="2026-09-07")
        assert len(records) == 1, "the ledger recorded nothing -- the gap is still open"
        rec = records[0]
        assert rec["segment"] == "first5"
        assert rec["priceable"] is False
        assert rec["withheld_reason"] == REASON_SEGMENT_NOT_FULL_GAME

    def test_reverting_the_JOIN_half_would_be_caught(self):
        """Companion, stated as its own case: without the join's stamp there is
        no key for the ledger to find, so the record above cannot exist."""
        grid = [_grid_row(segment="first5")]
        attach_live_gamelines(grid, _index())
        assert REFUSAL_KEY in grid[0]
        del grid[0][REFUSAL_KEY]
        assert build_records(grid, sport="mlb", date_str="2026-09-07") == []

    def test_every_segment_the_grid_quotes_is_visible_not_just_first5(self):
        grid = [_grid_row(segment=s) for s in ("first1", "first3", "first5", "full")]
        attach_live_gamelines(grid, _index())
        records = build_records(grid, sport="mlb", date_str="2026-09-07")
        assert {r["segment"] for r in records} == {"first1", "first3", "first5", "full"}


# ---------------------------------------------------------------------------
# COUNTING IS NOT PRICING. The refusal the guard makes is measured and correct;
# a record that carried a number could be mistaken for permission to bet it.
# ---------------------------------------------------------------------------
class TestARefusalRecordCarriesNoNumber:
    def test_no_probability_no_market_price_no_edge(self):
        grid = [_grid_row(segment="first5")]
        attach_live_gamelines(grid, _index())
        rec = build_records(grid, sport="mlb", date_str="2026-09-07")[0]
        for field in ("model_home_win_prob", "market_fair_prob", "edge_pp",
                      "sigma", "prob_std_err", "sims_run", "total_mean",
                      "home_margin", "point_estimator", "model_prob_raw"):
            assert rec[field] is None, f"{field} leaked a number onto a refusal record"

    def test_the_fine_grained_game_state_fields_are_NULL_not_stale(self):
        """Dedup writes a refusal row once, at first sighting, and never
        refreshes it. An inning or a score stamped here would describe the first
        build that saw the market and then sit frozen while reading as current.
        `game_state` is the one safe field: the join only considers live rows."""
        grid = [_grid_row(segment="first5")]
        attach_live_gamelines(grid, _index())
        rec = build_records(grid, sport="mlb", date_str="2026-09-07")[0]
        for field in ("inning", "half", "outs", "progress_fraction",
                      "home_score", "away_score", "quote_age_seconds"):
            assert rec[field] is None, f"{field} would be frozen at first sighting"
        assert rec["game_state"] == "live"

    def test_the_refusal_never_lands_on_the_key_the_BOARD_reads(self):
        """`layer2_board` copies `row["live_gameline"]` onto the candidate and
        `live_gameline_score` scores it. A refusal under that name would put an
        empty live block on every first5 board row -- degraded looking
        legitimate. A separate key keeps the blast radius at zero."""
        grid = [_grid_row(segment="first5")]
        attach_live_gamelines(grid, _index())
        assert "live_gameline" not in grid[0]
        assert REFUSAL_KEY != "live_gameline"
        # and the row's own projection is untouched: not marked live_aware
        assert grid[0]["projection"] == {}


# ---------------------------------------------------------------------------
# THE EXISTING MEASUREMENT MUST SURVIVE. `append_records` keeps `records[:500]`
# and STOPS WRITING FOR THE REST OF THE DAY at 20,000 lines in the file. MLB
# already wrote 8,070 rows on 2026-08-21, and segment rows outnumber full-game
# rows about five to one -- so an unordered widening would have pushed real
# edges out of the file.
# ---------------------------------------------------------------------------
class TestItCannotDisplaceAPriceableRow:
    def test_refusals_are_emitted_AFTER_every_live_gameline_record(self):
        grid = ([_grid_row(segment="first5", market="h2h")]
                + [_grid_row(segment="full", market="h2h")]
                + [_grid_row(segment="first3", market="h2h")])
        attach_live_gamelines(grid, _index())
        records = build_records(grid, sport="mlb", date_str="2026-09-07")
        segments = [r["segment"] for r in records]
        assert segments[0] == "full", segments
        assert set(segments[1:]) == {"first5", "first3"}, segments

    def test_a_flood_of_refusals_truncates_to_refusals_only(self, tmp_path):
        """The ordering above is what makes this true. Build a grid with more
        refusals than the build cap and confirm the full-game record survives."""
        grid = [_grid_row(segment="full", market="h2h")]
        grid += [_grid_row(segment="first5", market="h2h", line=float(i))
                 for i in range(_MAX_RECORDS_PER_BUILD + 50)]
        attach_live_gamelines(grid, _index())
        records = build_records(grid, sport="mlb", date_str="2026-09-07")
        assert len(records) > _MAX_RECORDS_PER_BUILD

        path = tmp_path / "ledger.jsonl"
        cov = append_records(path, records)
        assert cov["truncated_build_cap"] > 0, "precondition: the cap must bite"
        written = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
        full = [r for r in written if r["segment"] == "full"]
        assert len(full) == 1, "the priceable full-game row was crowded out"

    def test_an_unchanged_refusal_is_written_ONCE_then_deduped(self, tmp_path):
        """What bounds the file. `_moved` compares exactly the four fields a
        refusal record holds constant, so build two writes nothing."""
        path = tmp_path / "ledger.jsonl"
        grid = [_grid_row(segment="first5")]
        attach_live_gamelines(grid, _index())
        first = append_records(path, build_records(grid, sport="mlb", date_str="2026-09-07"))
        assert first["written"] == 1

        grid2 = [_grid_row(segment="first5")]
        attach_live_gamelines(grid2, _index())
        second = append_records(path, build_records(grid2, sport="mlb", date_str="2026-09-07"))
        assert second["written"] == 0
        assert second["skipped_unchanged"] == 1

    def test_two_lines_of_one_segment_market_are_DISTINCT_records(self):
        """`record_key` includes `line`, and a first5 total at 4.5 is not the
        same market as one at 5.5. Collapsing them would undercount the
        inventory this change exists to make countable."""
        grid = [_grid_row(segment="first5", market="totals", line=4.5),
                _grid_row(segment="first5", market="totals", line=5.5)]
        attach_live_gamelines(grid, _index())
        records = build_records(grid, sport="mlb", date_str="2026-09-07")
        assert len({record_key(r) for r in records}) == 2


# ---------------------------------------------------------------------------
# NO REGRESSION ON THE PATH THAT ALREADY WORKED.
# ---------------------------------------------------------------------------
class TestTheFullGamePathIsUnchanged:
    def test_a_full_game_row_still_prices_and_still_carries_its_numbers(self):
        grid = [_grid_row(segment="full")]
        coverage = attach_live_gamelines(grid, _index())
        assert coverage["rows_live_gameline_projected"] == 1
        assert "live_gameline" in grid[0]
        assert REFUSAL_KEY not in grid[0]
        rec = build_records(grid, sport="mlb", date_str="2026-09-07")[0]
        assert rec["game_pk"] == 824966
        assert rec["model_home_win_prob"] is not None
        assert rec["progress_fraction"] == 0.4

    def test_a_row_with_NEITHER_key_is_still_not_recorded(self):
        """The pre-existing contract: the ledger records what the join decided
        about, and a row the join never looked at stays out."""
        assert build_records([_grid_row(segment="full")], sport="mlb", date_str="d") == []
