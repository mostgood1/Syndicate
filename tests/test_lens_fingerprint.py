"""The live-lens fingerprint: making an unreplayable block ATTRIBUTABLE.

`#625`(5) had to declare five whole blocks of the board artifact UNREPLAYABLE
because they depend on `data_root()/<sport>_live_lens.json` -- one undated,
mutable key with no historical value. 167 of 167 rows whose projection differed
traced back to it.

**Dating that snapshot was measured and rejected** (2026-09-03): it is
keyvalue-backed, a single 4,194,400-byte key, so one write per 60s tick is
~5.76 GB/day for MLB alone against a 256 MB store already 86.8% full with 12,203
keys evicted -- and a dated path takes a TTL, which under `volatile-lru` makes
the archive the first thing evicted.

So the board records the input's FINGERPRINT instead. It does not make the
correction reproducible; it makes a divergence attributable.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from syndicate.features.shared.board_enrichment import _lens_fingerprint  # noqa: E402

GAMES = [
    {"state": "final", "home": {"name": "Reds"}, "away": {"name": "Padres"}, "home_score": 4, "away_score": 2},
    {"state": "live", "home": {"name": "Cubs"}, "away": {"name": "Pirates"}, "home_score": 1, "away_score": 0},
]


def test_same_effective_input_gives_the_same_digest() -> None:
    assert _lens_fingerprint(GAMES, 160.6)["sha256_12"] == _lens_fingerprint(list(GAMES), 160.6)["sha256_12"]


def test_a_changed_score_changes_the_digest() -> None:
    """If this ever stops holding, the fingerprint has stopped identifying the
    input and two different boards would claim the same lens."""
    moved = [dict(GAMES[0], home_score=5), GAMES[1]]
    assert _lens_fingerprint(GAMES, 160.6)["sha256_12"] != _lens_fingerprint(moved, 160.6)["sha256_12"]


def test_a_changed_state_changes_the_digest() -> None:
    moved = [dict(GAMES[0], state="live"), GAMES[1]]
    assert _lens_fingerprint(GAMES, 160.6)["sha256_12"] != _lens_fingerprint(moved, 160.6)["sha256_12"]


def test_age_alone_does_not_change_the_digest() -> None:
    """Two boards can share a digest and differ in age -- that means the lens
    stopped moving, not that the board changed. Folding age into the hash would
    destroy exactly that distinction."""
    a = _lens_fingerprint(GAMES, 10.0)
    b = _lens_fingerprint(GAMES, 900.0)
    assert a["sha256_12"] == b["sha256_12"]
    assert a["age_seconds"] != b["age_seconds"]


def test_it_stays_cheap() -> None:
    """The whole point is that it is ~100 bytes rather than the 4 MB snapshot.
    A fingerprint that grew with the slate would reintroduce the cost it avoids."""
    big = [dict(GAMES[0], home={"name": f"Team{i}"}) for i in range(30)]
    encoded = json.dumps(_lens_fingerprint(big, 12.0))
    assert len(encoded) < 400, f"fingerprint grew to {len(encoded)} bytes"


def test_empty_lens_still_produces_a_usable_identity() -> None:
    """An empty lens is a real state, and it must be distinguishable from a
    populated one rather than collapsing to something falsy."""
    fp = _lens_fingerprint([], None)
    assert fp["games"] == 0 and fp["states"] == {} and fp["age_seconds"] is None
    assert fp["sha256_12"] and fp["sha256_12"] != _lens_fingerprint(GAMES, None)["sha256_12"]
