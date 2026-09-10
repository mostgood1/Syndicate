"""The LOCAL capture's retained row must carry what the sample was made of.

`live_gameline_accuracy.build_row` is the worker-side twin of the row built by
`scripts/snapshot_live_gameline_score.py`, and `test_live_gameline_accuracy.py`
already pins its allowlist. This is the same assertion on the other copy: the
two histories are meant to stay comparable, and until 2026-08-30 this one
retained `unscored` and none of the other four.

WHY IT MATTERS HERE SPECIFICALLY. `75cf9aec` found the scorer comparing
P(over) and P(home covers) against "did the home team win" -- the ledger
carries three markets and `build_records` stores every one of their
probabilities under the field name `model_home_win_prob`, which is only true
for h2h. It survived ten nights of nightly capture because the retained history
recorded the Brier and nothing about which markets were in it. A row that keeps
the number without the population reproduces exactly that blindness, in the
file a later reader trusts most.
"""

from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "snapshot_live_gameline_score.py"


def _load():
    spec = importlib.util.spec_from_file_location("snapshot_lgs", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# Shaped like the real 2026-08-30 payload, whose counters are internally
# consistent in the way the assertions below rely on: the scored market's count
# equals `all_records.model.n`, and the refused counts sum to the `unscored`
# reason. Numbers are scaled down; the relationships are production's.
_SERVED = {
    "generated_at": "2026-08-30T23:00:00+00:00",
    "date": "2026-08-30",
    "live_gameline_score": {
        "enabled": True,
        "records_considered": 30,
        "games_with_outcome": 2,
        "records_by_market": {"h2h": 6, "spreads": 11, "totals": 12},
        "scored_markets": ["h2h"],
        "unscored": {"market_probability_is_not_a_home_win_probability": 23,
                     "record_carries_no_model_probability": 1},
        "finals_index": {"sport": "mlb", "finals_seen": 40, "finals_level": 0,
                         "finals_skipped_no_numeric_score": 0,
                         "finals_skipped_no_numeric_score_games": 0},
        "all_records": {"model": {"brier": 0.31, "n": 6},
                        "market": {"brier": 0.24, "n": 6}},
        "priceable_only": {"model": {"brier": 0.134, "n": 6},
                           "market": {"brier": 0.196, "n": 6},
                           "model_minus_market_brier": -0.062},
        "last_per_game": {"model": {"brier": 0.3, "n": 2}},
    },
}


def _run(mod, tmp_path, served, argv_extra=()):
    """Drive `main()` with the network stubbed, and return the appended row."""
    out = tmp_path / "history.jsonl"
    mod.fetch = lambda *a, **k: served  # noqa: ARG005 — the whole point
    import sys
    argv = sys.argv
    sys.argv = ["snapshot", "--sport", "mlb", "--date", "2026-08-30",
                "--out", str(out), *argv_extra]
    try:
        rc = mod.main()
    finally:
        sys.argv = argv
    if not out.exists():
        return rc, None
    return rc, json.loads(list(io.open(out, encoding="utf-8"))[-1])


def test_retained_row_carries_the_market_mix(tmp_path):
    """The two keys that name the population behind the Brier."""
    mod = _load()
    rc, row = _run(mod, tmp_path, _SERVED)
    assert rc == 0
    assert row["records_by_market"] == {"h2h": 6, "spreads": 11, "totals": 12}
    assert row["scored_markets"] == ["h2h"]


def test_retained_row_matches_the_worker_side_allowlist(tmp_path):
    """All five `extra` keys the twin names, not just the two in the headline.

    `live_gameline_accuracy.build_row` allowlists
    `("finals_index", "unscored", "reason", "records_by_market",
    "scored_markets")`. Drift between the two is the same defect class this
    fixes -- one history able to explain a number the other cannot.
    """
    mod = _load()
    _rc, row = _run(mod, tmp_path, _SERVED)
    for key in ("finals_index", "unscored", "records_by_market", "scored_markets"):
        assert key in row, f"{key} dropped by the local capture's allowlist"
    assert row["finals_index"]["finals_seen"] == 40
    assert row["unscored"]["market_probability_is_not_a_home_win_probability"] == 23
    # `reason` is present-but-null on a build that scored something. The key
    # must exist so a zero-outcome row can say WHY rather than being
    # indistinguishable from a failure.
    assert "reason" in row


def test_the_mix_reconciles_against_the_numbers_beside_it(tmp_path):
    """A retained mix that cannot be checked against its own row is decoration.

    Two identities hold in production and are asserted here so a future change
    that retains the keys but mis-sources them fails loudly:
      * the SCORED market's count == `all_records.model.n`
      * the REFUSED counts sum to the `unscored` market reason
    """
    mod = _load()
    _rc, row = _run(mod, tmp_path, _SERVED)
    by_market = row["records_by_market"]
    scored = set(row["scored_markets"])
    assert sum(v for k, v in by_market.items() if k in scored) == \
        row["all_records"]["model"]["n"]
    assert sum(v for k, v in by_market.items() if k not in scored) == \
        row["unscored"]["market_probability_is_not_a_home_win_probability"]


def test_a_pre_fix_board_is_reported_as_unknown_not_as_empty(tmp_path):
    """A board older than `75cf9aec` emits no market counters at all.

    That is NOT the same as a slate whose mix was empty, and the row must not
    make the two look alike -- `None` (absent) rather than `{}` (measured and
    empty).
    """
    mod = _load()
    served = json.loads(json.dumps(_SERVED))
    del served["live_gameline_score"]["records_by_market"]
    del served["live_gameline_score"]["scored_markets"]
    rc, row = _run(mod, tmp_path, served)
    assert rc == 0
    assert row["records_by_market"] is None
    assert row["scored_markets"] is None


def test_reachability_the_keys_come_from_the_payload_not_a_default(tmp_path):
    """REACHABILITY BEFORE CORRECTNESS: `off != on`.

    A retained key that is really a constant would pass every assertion above.
    Feeding a different mix must move the retained value, or the row is not
    reading the payload at all -- the failure mode `learnings.md` records
    against this file's neighbours, where a test named for the right invariant
    passed for weeks against broken code.
    """
    mod = _load()
    served = json.loads(json.dumps(_SERVED))
    served["live_gameline_score"]["records_by_market"] = {"h2h": 99}
    served["live_gameline_score"]["scored_markets"] = ["h2h", "spreads"]
    _rc, row = _run(mod, tmp_path, served)
    assert row["records_by_market"] == {"h2h": 99}
    assert row["scored_markets"] == ["h2h", "spreads"]
