"""Layer 2 board page redesign `[user 2026-10-08, lane layer2-board-ui-redesign]`.

Pins, per phase:
  * the embedded board JSON is PARSEABLE as served. From 2026-09-22 (ebd17ee2)
    the page escaped it twice (`"` -> `&#34;`), so every visit downloaded the
    whole embed, failed `JSON.parse` on byte 1 and waited for the API instead.
    The existing tests checked the JSON text, never the rendered page.
  * every filter is visible: no "More filters" fold, no odds-range slider, and a
    Full game / Game intervals filter that reads both places a row names its
    period (node harness `tests/js/board_period_filter.test.mjs`).
"""

from __future__ import annotations

import html as html_lib
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

from flask import render_template

from syndicate.app import app
from syndicate.blueprints.intelligence import _embed_json_text

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "syndicate" / "templates" / "intelligence.html"


def _render_board(embed_text: str) -> str:
    with app.test_request_context("/"):
        return render_template(
            "intelligence.html",
            initial_intelligence_response_json=embed_text,
            initial_intelligence_selected_date=None,
            initial_intelligence_today_iso="2026-10-08",
        )


class EmbedParsesAsServed(unittest.TestCase):
    def test_the_served_script_block_is_valid_json(self) -> None:
        payload = {"ranked_all": [{"player": 'O\'Neil "Jr."', "note": "</script><b>&"}], "ok": True}
        page = _render_board(_embed_json_text(payload))
        block = re.search(
            r'<script id="initial-intelligence-response" type="application/json">(.*?)</script>', page, re.S
        )
        self.assertIsNotNone(block)
        text = block.group(1)
        self.assertNotIn("&#34;", text)
        # What the browser does: textContent of a <script> is NOT entity-decoded.
        parsed = json.loads(text)
        self.assertEqual(parsed["ranked_all"][0]["note"], "</script><b>&")
        self.assertEqual(parsed["ranked_all"][0]["player"], 'O\'Neil "Jr."')

    def test_a_script_close_tag_in_the_data_cannot_end_the_block(self) -> None:
        page = _render_board(_embed_json_text({"ranked_all": [{"x": "</script><script>alert(1)</script>"}]}))
        self.assertEqual(page.count('<script id="initial-intelligence-response"'), 1)
        self.assertNotIn("<script>alert(1)", page)
        self.assertEqual(html_lib.unescape("&#34;"), '"')  # sanity: the old failure shape


class FiltersAllVisible(unittest.TestCase):
    def setUp(self) -> None:
        self.text = TEMPLATE.read_text(encoding="utf-8")

    def test_no_more_filters_fold_and_no_odds_range(self) -> None:
        for gone in ('id="board-more-filters"', "board-odds-filter", "ODDS_LADDER", "matchesOddsRange"):
            self.assertNotIn(gone, self.text, gone)

    def test_period_filter_is_present_and_wired(self) -> None:
        self.assertIn('id="board-period-tabs"', self.text)
        self.assertIn('renderTabs("board-period-tabs"', self.text)
        self.assertIn("isIntervalRow(item)", self.text)

    def test_every_filter_group_carries_counts(self) -> None:
        for tab_id in ("board-day-tabs", "board-sport-tabs", "board-state-tabs", "board-market-tabs",
                       "board-period-tabs", "board-edge-tabs", "board-lane-tabs", "board-alt-tabs",
                       "board-steam-tabs"):
            self.assertRegex(self.text, rf'renderTabs\("{tab_id}", withCounts\(', tab_id)

    def test_hidden_rows_are_attributed_to_named_filters(self) -> None:
        # The default Opportunities and Main-lines filters hide rows; the results
        # bar must list them, which is what made "hidden by 0 filters" possible.
        self.assertIn('out.push({ key: "lane"', self.text)
        self.assertIn('out.push({ key: "alt"', self.text)
        self.assertNotIn("hidden by ${active.length} filter", self.text)

    @unittest.skipUnless(shutil.which("node"), "node not on PATH")
    def test_period_classifier_node_harness(self) -> None:
        result = subprocess.run(
            ["node", str(ROOT / "tests" / "js" / "board_period_filter.test.mjs")],
            capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
