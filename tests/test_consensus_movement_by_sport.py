"""Nightly consensus-movement check (lane `layer2-freshness-1h`, 2026-10-02).

Reachability first: synthetic quote logs with a KNOWN answer must come out as that
answer -- momentum, reversion, or insufficient -- through the real functions.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from scripts import consensus_movement_by_sport as cm

NOW = datetime(2026, 10, 3, 10, 30, tzinfo=timezone.utc)
KICK = datetime(2026, 10, 3, 0, 0, tzinfo=timezone.utc)


def _american(p: float) -> int:
    return int(round(-100 * p / (1 - p))) if p >= 0.5 else int(round(100 * (1 - p) / p))


def _game(event: str, path: list[float], books=("dk", "fd", "mgm")) -> list[dict]:
    """A two-way market whose over-probability follows `path` at every book (with vig)."""
    rows = []
    for i, p in enumerate(path):
        t = (KICK - timedelta(hours=len(path) - i)).isoformat()
        for b in books:
            for side, q in (("over", p), ("under", 1 - p)):
                rows.append({
                    "event_id": event, "market": "totals", "segment": "full", "player_name": None,
                    "line": 45.5, "selection": side, "bookmaker": b, "price": _american(min(0.97, q * 1.04)),
                    "captured_at": t, "commence_time": KICK.isoformat(),
                })
    return rows


def _report(paths: list[list[float]]) -> dict:
    rows = [r for i, path in enumerate(paths) for r in _game(f"e{i}", path)]
    return cm.contrast(cm.observations(rows, now=NOW))


def test_reachability_a_move_that_continues_reads_as_momentum():
    # The market moves toward "over" mid-way and keeps going to the close.
    out = _report([[0.50, 0.52, 0.54, 0.56, 0.60] for _ in range(25)])
    assert out["events"] == 25
    assert out["verdict"] == "momentum", out
    assert out["toward_minus_against_pp"] > 0


def test_a_move_that_comes_back_reads_as_reversion():
    out = _report([[0.50, 0.53, 0.55, 0.53, 0.50] for _ in range(25)])
    assert out["verdict"] == "reversion", out
    assert out["toward_minus_against_pp"] < 0


def test_too_few_games_is_insufficient_not_a_verdict():
    out = _report([[0.50, 0.52, 0.54, 0.56, 0.60] for _ in range(5)])
    assert out["verdict"] == "insufficient"
    assert out["ci95"] is None


def test_unstarted_games_are_excluded():
    rows = _game("future", [0.5, 0.52, 0.55, 0.6])
    for r in rows:
        r["commence_time"] = (NOW + timedelta(days=1)).isoformat()
    assert cm.observations(rows, now=NOW) == []


def test_a_zero_price_does_not_move_the_consensus():
    # A second book quotes "under" at 0 -- not a real American price. The old local
    # converter priced it 0.0, so that book's pair de-vigged to over=1.0 and dragged
    # the median; the owner refuses it and the one-sided book drops out of consensus.
    # ONE clean book: with three identical ones the median of [x, x, x, 1.0] is
    # still x, and this test passed against the old converter.
    clean = _game("e0", [0.50, 0.52, 0.54, 0.56, 0.60], books=("dk",))
    bad = _game("e0", [0.50, 0.52, 0.54, 0.56, 0.60], books=("bad",))
    for r in bad:
        if r["selection"] == "under":
            r["price"] = 0
    consensus = lambda rows: sorted(round(o[1], 9) for o in cm.observations(rows, now=NOW) if o[0] == "e0")
    assert set(consensus(clean + bad)) == set(consensus(clean))
