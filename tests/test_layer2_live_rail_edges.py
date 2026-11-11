"""Live lines + fresh-quote live-edge flag on the Layer 2 Games rail (lane layer2-live-rail-edges, todo #781).

The behaviour is in the page's own JavaScript (`intelligence.html`, the LIVE RAIL LINES block), so the
assertions live in the node harness `tests/js/games_rail_live_lines.test.mjs`, which extracts that block from
the template and runs it. This wrapper puts the harness in the pytest suite, and pins the two numbers the
flag rests on, so a change to either is a visible test edit rather than a silent one:

  - LIVE_EDGE_FRESH_QUOTE_SECONDS = 120, in every game-line market: todo #780's all-market addendum graded priced
    live totals, spreads and moneylines (NCAAB / NBA / NCAAF) at ~0 realised edge under 120 s, with the apparent
    edge only on older quotes (clearly from 180-300 s); 120 s is also the join's MLB ceiling. Even inside 120 s the
    realised edge is ~0, so the flag is worded as a model-vs-line disagreement, never as an edge.
  - the live join's own pricing ceiling stays 600 s (MLB 120 s): tightening it is #780's candidate fix 1, a
    separate user decision this lane does not make.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "syndicate" / "templates" / "intelligence.html"
HARNESS = ROOT / "tests" / "js" / "games_rail_live_lines.test.mjs"


def _template() -> str:
    return TEMPLATE.read_text(encoding="utf-8").replace("\r\n", "\n")


@pytest.mark.skipif(shutil.which("node") is None, reason="node not on PATH")
def test_live_rail_lines_node_harness() -> None:
    result = subprocess.run(["node", str(HARNESS)], capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-2000:]
    assert "FAIL" not in result.stdout
    assert "all passed" in result.stdout


def test_fresh_quote_threshold_and_minimum_are_the_stated_ones() -> None:
    html = _template()
    assert re.search(r"const LIVE_EDGE_FRESH_QUOTE_SECONDS = 120;", html)
    assert re.search(r"const LIVE_EDGE_MIN_PP = 3;", html)


def test_the_join_pricing_ceiling_is_unchanged() -> None:
    from syndicate.features.shared import live_gameline_join as join

    assert join._DEFAULT_MAX_QUOTE_AGE_SECONDS == 600.0
    assert join._MAX_QUOTE_AGE_BY_SPORT == {"mlb": 120.0}


def test_the_rail_flag_reads_the_clock_the_grade_used() -> None:
    """`book_age_seconds` on a served row is the grid cell's `age_seconds`, which the live join reads as the
    quote's age and the live gameline ledger records as `quote_age_seconds` -- the field #780 bucketed."""
    html = _template()
    block = re.search(r"// ===== LIVE RAIL LINES -- BEGIN[\s\S]*?// ===== LIVE RAIL LINES -- END =====", html)
    assert block, "LIVE RAIL LINES block missing"
    assert "item && item.book_age_seconds" in block.group(0)
    assert "quote_seen_age_seconds" not in block.group(0).split("const LIVE_EDGE_FRESH_QUOTE_SECONDS")[1]
    ledger = (ROOT / "syndicate" / "features" / "shared" / "live_gameline_ledger.py").read_text(encoding="utf-8")
    assert '"quote_age_seconds": row.get("age_seconds")' in ledger
    board = (ROOT / "syndicate" / "features" / "shared" / "layer2_board.py").read_text(encoding="utf-8")
    assert '"book_age_seconds": quote_age_cell.get("age_seconds")' in board
