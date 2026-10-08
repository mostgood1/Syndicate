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


class ResearchRailAndSlipTray(unittest.TestCase):
    """Phase 3: Ask docks on the right, the slip is a pill + tray, and the
    blotter fits beside the rail (9 columns, Live/Actual only when live)."""

    def setUp(self) -> None:
        self.text = TEMPLATE.read_text(encoding="utf-8")
        self.css = (ROOT / "syndicate" / "static" / "shared" / "board_cards.css").read_text(encoding="utf-8")

    def test_ask_and_slip_live_in_separate_containers(self) -> None:
        research = self.text[self.text.index('id="board-research"'):self.text.index('class="board-research-tab"')]
        self.assertIn('id="ask-bar-panel"', research)
        self.assertNotIn('id="bet-slip-panel"', research)
        tray = self.text[self.text.index('id="board-slip-tray"'):self.text.index('class="board-slip-pill"')]
        self.assertIn('id="bet-slip-panel"', tray)

    def test_page_does_not_use_the_layer1_rail_toggle_class(self) -> None:
        # board_rail_toggle.js acts on `.board-rail`; this page must not have one.
        self.assertNotIn('class="board-rail"', self.text)

    def test_asking_opens_the_rail_and_the_slip_reports_its_count(self) -> None:
        self.assertIn('addEventListener("syndicate:ask"', self.text)
        self.assertIn('addEventListener("syndicate:slip-count"', self.text)
        ask = (ROOT / "syndicate" / "static" / "shared" / "ask_bar.js").read_text(encoding="utf-8")
        slip = (ROOT / "syndicate" / "static" / "shared" / "bet_slip.js").read_text(encoding="utf-8")
        self.assertIn('new CustomEvent("syndicate:ask"', ask)
        self.assertIn('new CustomEvent("syndicate:slip-count"', slip)

    def test_blotter_has_nine_columns_and_live_columns_are_conditional(self) -> None:
        block = self.text[self.text.index("  const BLOTTER_COLUMNS = ["):]
        block = block[:block.index("\n  ];")]
        keys = re.findall(r'\{ key: "(\w+)"', block)
        self.assertEqual(keys, ["score", "pick", "book", "fair", "ev", "winpct", "move", "age", "live", "actual"])
        self.assertEqual(len(re.findall(r"liveOnly: true", block)), 2)

    def test_breakpoints_from_the_approved_mockups(self) -> None:
        for media in ("(min-width: 1024px) and (max-width: 1279px)", "(max-width: 1023px)", "(max-width: 767px)"):
            self.assertIn(media, self.css, media)
        self.assertIn(".board-toolbar { grid-template-columns: minmax(0, 1fr); }", self.css)


class TopPlaysAndHowRanks(unittest.TestCase):
    """Phase 4: the Best opportunities strip became a 3-tab Top plays rail, and
    How this board ranks was rewritten -- the 1.5-point sim cap still stated."""

    def setUp(self) -> None:
        self.text = TEMPLATE.read_text(encoding="utf-8")

    def test_top_plays_rail_has_three_tabs(self) -> None:
        self.assertNotIn("🔥 Best opportunities</h2>", self.text)
        for value in ('value: "sport"', 'value: "moving"', 'value: "agree"'):
            self.assertIn(value, self.text)
        self.assertIn('data-pick-id="${escapeHtml(pickKey(item))}"', self.text)

    def test_how_ranks_still_states_the_sim_cap(self) -> None:
        block = self.text[self.text.index('<details class="board-ranks"'):self.text.index("</details>", self.text.index('<details class="board-ranks"'))]
        self.assertIn("at most 1.5 points", block)
        self.assertIn("sim off-scale", block)
        self.assertNotIn("Under 53.5", self.text)

    def test_off_scale_matches_the_backend_cap(self) -> None:
        board = (ROOT / "syndicate" / "features" / "shared" / "layer2_board.py").read_text(encoding="utf-8")
        cap = re.search(r"_MODEL_EDGE_MAX_POINTS\s*=\s*([0-9.]+)", board)
        self.assertIsNotNone(cap)
        self.assertIn(f"const SIM_OFF_SCALE_POINTS = {int(float(cap.group(1)))};", self.text)
