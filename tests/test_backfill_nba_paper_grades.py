"""scripts/backfill_nba_paper_grades.py -- which archived rows get a graded copy, and what it carries."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_PATH = Path(__file__).resolve().parents[1] / "scripts" / "backfill_nba_paper_grades.py"
_spec = importlib.util.spec_from_file_location("backfill_nba_paper_grades", _PATH)
bf = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bf)


def _row(i, **kw):
    base = {"idempotency_key": f"k{i}", "sport": "nba", "selected_date": "2026-10-21", "venue": "paper:kalshi:ladder",
            "mode": "paper", "status": "filled", "fill_stake_dollars": 1.0, "market": "spreads"}
    base.update(kw)
    return base


def _verdict(row, resolver):
    if row.get("market") == "unmapped":
        return None, {}, "unmapped_market"
    return ({"outcome": "won", "pnl_dollars": 0.9, "pnl_gross_dollars": 0.92, "settled_value": 4.0},
            {"home_score": 110, "away_score": 102}, "")


def _run(rows, live=frozenset(), dates=("2026-10-21",)):
    asked = []
    out, census = bf.grade_archived(rows, set(live), list(dates), resolver_for=lambda d: asked.append(d) or object(),
                                    verdict_fn=_verdict, identity_fn=lambda r: r["idempotency_key"], now="T")
    return out, census, asked


def test_only_archive_only_ungraded_filled_nba_paper_rows_on_the_dates_are_graded():
    rows = [
        _row(1),
        _row(2, outcome="lost"),                         # already graded
        _row(3, status="rejected"),                      # never filled
        _row(4, mode="live", venue="kalshi"),            # live: the venue settles it
        _row(5, sport="nfl"),                            # other sport
        _row(6, selected_date="2026-10-23"),             # outside the dates
        _row(7),                                         # still in the live document -> the worker's
        _row(8, market="unmapped"),                      # refused by the resolver, named
    ]
    out, census, asked = _run(rows, live={"k7"})
    assert [r["idempotency_key"] for r in out] == ["k1"]
    assert census["skipped_live_document"] == 1 and census["refused"] == {"unmapped_market": 1}
    assert census["considered"] == 2 and census["graded"] == 1 and census["by_date"] == {"2026-10-21": 1}
    assert asked == ["2026-10-21"]  # one resolver per date


def test_the_graded_copy_carries_the_verdict_and_never_mutates_the_input():
    rows = [_row(1)]
    out, _c, _a = _run(rows)
    g = out[0]
    assert (g["outcome"], g["pnl_dollars"], g["settled_value"], g["home_score"]) == ("won", 0.9, 4.0, 110)
    assert g["graded_by"] == bf.BACKFILL_TAG and g["graded_at"] == "T"
    assert "outcome" not in rows[0]
    # identity fields are untouched, so archived_orders' last-copy-per-identity supersedes the ungraded row
    assert {k: g[k] for k in ("idempotency_key", "selected_date", "venue")} == {k: rows[0][k] for k in ("idempotency_key", "selected_date", "venue")}
