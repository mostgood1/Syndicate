"""Soccer half rows must not carry a full-match projection (lane `soccer-segment-projection-guard`).

Measured on the served 2026-10-10 Layer 2 board: an h1 over 0.5 goals carried
p(over) 0.945, an h1 over 1.0 0.934, and an h1 handicap was stamped
`model_edge_pct` +11.68 -- all full-match numbers, because
`attach_soccer_projections` never read `row["segment"]`. The first test fails on
the pre-change code.
"""
from __future__ import annotations

import json
from pathlib import Path

from syndicate.features.shared.soccer_projections import attach_soccer_projections, load_soccer_projections


def _index(root: Path):
    folder = root / "mls" / "api" / "recommendations"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "recommendations_2026-10-10.json").write_text(json.dumps({
        "league": "mls",
        "date": "2026-10-10",
        "generated_at": "2026-10-10T06:00:00+00:00",
        "matches": [{
            "match_id": "1", "event_id": "1", "league": "mls", "date": "2026-10-10",
            "matchup": {"home_team": "FC Dallas", "away_team": "Austin FC"},
            "win_probability": {"home": 0.5, "draw": 0.25, "away": 0.25},
        }],
    }), encoding="utf-8")
    return load_soccer_projections([root], "2026-10-10", window_dates=["2026-10-10"])


def _row(segment: str | None) -> dict:
    row = {"sport": "soccer", "kind": "game", "market": "h2h", "league": "mls",
           "home_team": "FC Dallas", "away_team": "Austin FC", "side": "home"}
    if segment is not None:
        row["segment"] = segment
    return row


def test_half_rows_get_no_projection(tmp_path: Path) -> None:
    index = _index(tmp_path)
    h1, h2 = _row("h1"), _row("h2")
    coverage = attach_soccer_projections([h1, h2], index)
    assert "projection" not in h1   # pre-change: the full-match win_probability
    assert "projection" not in h2
    assert coverage["non_full_segment_rows"] == 2


def test_full_rows_are_still_projected(tmp_path: Path) -> None:
    index = _index(tmp_path)
    full, unlabelled = _row("full"), _row(None)
    coverage = attach_soccer_projections([full, unlabelled], index)
    assert full["projection"]["basis"] == "win_probability"
    assert unlabelled["projection"]["basis"] == "win_probability"
    assert coverage["non_full_segment_rows"] == 0
