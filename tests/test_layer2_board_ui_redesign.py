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


class ProjectionIsNotAContradiction(unittest.TestCase):
    """Item 9: Michael Van Buren Jr. Under 0.5 passing TDs, served 2026-10-08 --
    sim P(under) 0.523, projected (a MEAN) 0.745. Both true; the old sentence
    read as the sim contradicting itself, and the direction tag judged on the
    mean alone."""

    ROW = {"player_name": "Michael Van Buren Jr.", "market": "player_pass_tds", "side": "under", "line": 0.5,
           "projection": {"projected": 0.745, "prob_over": 0.477}}

    def test_sentence_explains_mean_versus_likely_result(self) -> None:
        from syndicate.features.shared.layer2_row_context import _projection_sentence

        text = _projection_sentence(self.ROW, 0.523, 0.745, 0.5)
        self.assertIn("Its average is 0.7", text)
        self.assertIn("52.3% of its simulations finish under", text)
        self.assertNotIn("It projects 0.7 against", text)

    def test_agreeing_mean_keeps_the_plain_sentence(self) -> None:
        from syndicate.features.shared.layer2_row_context import _projection_sentence

        row = dict(self.ROW, side="over")
        self.assertEqual(_projection_sentence(row, 0.62, 14.8, 11.5),
                         "It projects an average of 14.8 against the 11.5 line.")

    def test_side_probability_vetoes_a_mean_only_contradiction(self) -> None:
        from unittest.mock import patch

        from syndicate.features.shared import layer2_board

        projection = {"projected": 0.745}
        with patch.object(layer2_board, "_model_prob_for_side", return_value=0.523):
            self.assertIsNone(layer2_board._sim_direction_contradiction(self.ROW, projection))
        with patch.object(layer2_board, "_model_prob_for_side", return_value=0.41):
            self.assertEqual(layer2_board._sim_direction_contradiction(self.ROW, projection), 0.245)
        with patch.object(layer2_board, "_model_prob_for_side", return_value=None):
            self.assertEqual(layer2_board._sim_direction_contradiction(self.ROW, projection), 0.245)


class PropSideFramingEndToEnd(unittest.TestCase):
    """Item 9's root cause: NHL/NBA/WNBA producers wrote the model's LEAN into
    `projection["side"]`, and every reader treats that field as the framing of
    `model_prob_over` -- so an under-leaning prop shipped P(under) on its OVER
    row. Producer -> board, through the real NHL attach and the real
    `_model_prob_for_side`. (Gage Goncalves o0.5 assists, 2026-10-08: lam 0.269,
    served 76.4%, true P(over) 23.6%.)"""

    def _nhl_rows(self, lam: float, line: float):
        from syndicate.features.nhl import prop_projections as npp

        idx = npp.NhlPropProjectionIndex(date="2026-10-02")
        idx.by_key[(npp._norm("Gage Goncalves"), "ASSISTS")] = (npp._norm("Detroit Red Wings"), npp._norm("New York Rangers"), lam)
        idx.context[(npp._norm("Gage Goncalves"), "ASSISTS")] = {"line_slot": "L1", "proj_toi": "18.0", "sim_starter": "", "game_type": "regular"}
        base = {"kind": "prop", "sport": "nhl", "market": "player_assists", "player_name": "Gage Goncalves", "line": line,
                "home_team": "Detroit Red Wings", "away_team": "New York Rangers", "commence_time": "2026-10-02T23:00:00Z"}
        rows = [dict(base, side="over"), dict(base, side="under")]
        npp.attach_nhl_prop_projections(rows, idx, selected_date="2026-10-02")
        return rows

    def test_under_leaning_prop_keeps_its_over_probability_on_the_over_row(self) -> None:
        import math

        from syndicate.features.shared.layer2_board import _model_prob_for_side

        over, under = self._nhl_rows(0.269, 0.5)
        p_over = 1 - math.exp(-0.269)
        self.assertEqual(over["projection"]["side"], "over")
        self.assertEqual(over["projection"]["lean"], "under")
        self.assertAlmostEqual(_model_prob_for_side(over), p_over, places=3)
        self.assertAlmostEqual(_model_prob_for_side(under), 1 - p_over, places=3)

    def test_over_leaning_prop_is_unchanged(self) -> None:
        import math

        from syndicate.features.shared.layer2_board import _model_prob_for_side

        over, _ = self._nhl_rows(2.0, 1.5)
        self.assertEqual(over["projection"]["lean"], "over")
        self.assertAlmostEqual(_model_prob_for_side(over), 1 - math.exp(-2) * 3, places=3)

    def test_no_producer_writes_the_lean_into_side(self) -> None:
        for rel in ("syndicate/features/nhl/prop_projections.py", "syndicate/features/shared/nba_projections.py",
                    "syndicate/features/shared/wnba_projections.py"):
            text = (ROOT / rel).read_text(encoding="utf-8")
            self.assertNotRegex(text, r'projection\["side"\] = "over" if', rel)


class EmbedRowReferences(unittest.TestCase):
    """Page size: top_opportunities rides as pick_id references into ranked_all,
    recommendations as an alias of it -- only when every row is exactly its
    ranked_all row. Measured 2026-10-08: 48.7M -> 17.9M chars, gzip 5.0 -> 1.85 MB."""

    def _payload(self):
        rows = [{"pick_id": f"p{i}", "sport": "nhl", "x": i} for i in range(5)]
        top = [dict(rows[3]), dict(rows[1])]
        return {"ranked_all": rows, "top_opportunities": top, "recommendations": [dict(r) for r in top]}

    def test_subset_becomes_references_and_recommendations_an_alias(self) -> None:
        from syndicate.blueprints.intelligence import _slim_embedded_board_payload

        slim = _slim_embedded_board_payload(self._payload())
        self.assertNotIn("top_opportunities", slim)
        self.assertNotIn("recommendations", slim)
        self.assertEqual(slim["_embed_row_refs"]["top_opportunities"]["ids"], ["p3", "p1"])
        self.assertEqual(slim["_embed_aliases"]["recommendations"], "top_opportunities")

    def test_a_row_that_differs_keeps_the_full_list(self) -> None:
        from syndicate.blueprints.intelligence import _slim_embedded_board_payload

        payload = self._payload()
        payload["top_opportunities"][0]["x"] = 99
        slim = _slim_embedded_board_payload(payload)
        self.assertIn("top_opportunities", slim)
        self.assertNotIn("_embed_row_refs", slim)

    @unittest.skipUnless(shutil.which("node"), "node not on PATH")
    def test_the_page_rebuilds_the_references(self) -> None:
        text = TEMPLATE.read_text(encoding="utf-8")
        start = text.index("  function rehydrateAliases(payload) {")
        depth, seen, end = 0, False, start
        for i in range(start, len(text)):
            if text[i] == "{":
                depth, seen = depth + 1, True
            elif text[i] == "}":
                depth -= 1
                if seen and depth == 0:
                    end = i + 1
                    break
        from syndicate.blueprints.intelligence import _slim_embedded_board_payload

        slim = _slim_embedded_board_payload(self._payload())
        script = text[start:end] + "\nconst p = " + json.dumps(slim) + ";\nrehydrateAliases(p);\n" \
            "console.log(JSON.stringify([p.top_opportunities.map(r => r.pick_id), p.recommendations === p.top_opportunities]));"
        out = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(json.loads(out.stdout.strip()), [["p3", "p1"], True])


class EmbedIsBrowserJson(unittest.TestCase):
    def test_nan_and_infinity_become_null(self) -> None:
        # Python's json.loads ACCEPTS NaN; a browser's JSON.parse does not. Parse
        # strictly, the way the browser does.
        text = _embed_json_text({"ranked_all": [{"line": float("nan"), "x": float("inf"), "y": 1.5}]})
        parsed = json.loads(text, parse_constant=lambda name: (_ for _ in ()).throw(ValueError(name)))
        self.assertEqual(parsed["ranked_all"][0], {"line": None, "x": None, "y": 1.5})


class TeamLogosAndChipSituation(unittest.TestCase):
    def test_logo_resolves_by_name_key_or_alias_from_a_branding_file(self) -> None:
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        from syndicate.features.shared import team_logos

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nhl_team_branding.csv"
            path.write_text("team_id,abbreviation,location,display_name,primary_color,secondary_color,logo_url,source_snapshot_date\n"
                            "1,TOR,Toronto,Toronto Maple Leafs,,,https://x/tor.png,2026-10-01\n", encoding="utf-8")
            team_logos._index.cache_clear()
            with patch.object(team_logos, "_branding_files", return_value=[path]):
                self.assertEqual(team_logos.logo_url("nhl", "Toronto Maple Leafs"), "https://x/tor.png")
                self.assertEqual(team_logos.logo_url("nhl", "toronto maple leafs"), "https://x/tor.png")
                self.assertIsNone(team_logos.logo_url("nhl", "Atlantis Squids"))
                rows = [{"sport": "nhl", "home_team": "Toronto Maple Leafs", "away_team": "Nowhere"}]
                self.assertEqual(team_logos.stamp_row_logos(rows), 1)
                self.assertEqual(rows[0]["home_logo"], "https://x/tor.png")
                self.assertNotIn("away_logo", rows[0])
            team_logos._index.cache_clear()

    def test_live_situation_drops_what_the_token_already_says(self) -> None:
        from syndicate.features.shared.game_chip_scoreboard import _live_situation

        self.assertEqual(_live_situation({"live_state": {"status": "In Progress | Top 7 | 1 out"}}, "TOP 7"), "1 out")
        self.assertEqual(_live_situation({"status": {"detailed": "3rd & 4 at TB 38"}}, "Q2 3:21"), "3rd & 4 at TB 38")
        self.assertIsNone(_live_situation({"live_state": {"status": "In Progress"}}, "Q2 3:21"))


class ChartsAndHeadshots(unittest.TestCase):
    """Approved mockup board 10 + headshots (user 2026-10-08)."""

    def test_price_ladder_reproduces_the_producer_price_at_the_line(self) -> None:
        from syndicate.features.nhl.prop_projections import price_p_over
        from syndicate.features.shared.price_ladder import price_ladder

        ladder = price_ladder(lambda t: price_p_over("ASSISTS", t, 0.269), 0.5)
        at_line = [p for t, p in ladder if t == 0.5][0]
        self.assertAlmostEqual(at_line, round(price_p_over("ASSISTS", 0.5, 0.269), 4), places=4)
        self.assertEqual([t for t, _ in ladder][:3], [-0.5, 0.5, 1.5])
        self.assertTrue(all(ladder[i][1] >= ladder[i + 1][1] for i in range(len(ladder) - 1)))

    def test_continuous_ladder_steps_in_half_sd(self) -> None:
        from syndicate.features.shared.price_ladder import price_ladder

        ladder = price_ladder(lambda t: max(0.0, min(1.0, 1 - t / 200)), 60.5, sd=20)
        self.assertEqual([t for t, _ in ladder], [30.5, 40.5, 50.5, 60.5, 70.5, 80.5, 90.5])

    def test_chart_columns_carry_ladder_and_recent_values(self) -> None:
        from unittest.mock import patch

        from syndicate.features.shared import layer2_board

        row = {"kind": "prop", "projection": {"ladder": [[-0.5, 1.0], [0.5, 0.48], [1.5, 0.16]]}}
        with patch("syndicate.features.intelligence_recent_matchup.recent_values_for",
                   return_value={"values": [0, 1, 0], "line": 0.5, "side": "under"}):
            cols = layer2_board._chart_columns(row)
        self.assertEqual(cols["sim_ladder"][1], [0.5, 0.48])
        self.assertEqual(cols["recent_values"], [0, 1, 0])

    def test_headshot_name_maps_drop_ambiguous_names(self) -> None:
        from syndicate.features.shared.player_headshots import _unique

        out = _unique([("jsmith", "1"), ("jsmith", "2"), ("adoe", "3"), ("adoe", "3")])
        self.assertEqual(out, {"adoe": "3"})

    def test_nhl_headshot_uses_the_team_free_latest_path(self) -> None:
        from unittest.mock import patch

        from syndicate.features.shared import player_headshots

        with patch.object(player_headshots, "_nhl_ids", return_value={"austonmatthews": "8479318"}):
            url = player_headshots.headshot_url({"sport": "nhl", "player_name": "Auston Matthews"})
        self.assertEqual(url, "https://assets.nhle.com/mugs/nhl/latest/8479318.png")

    @unittest.skipUnless(shutil.which("node"), "node not on PATH")
    def test_chart_node_harness(self) -> None:
        result = subprocess.run(["node", str(ROOT / "tests" / "js" / "board_prop_charts.test.mjs")],
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class PropShowsOnlyThePlayersTeam(unittest.TestCase):
    """User 2026-10-08: a prop showed BOTH team logos; it must show the player's team only."""

    def test_player_side_matches_by_logo(self) -> None:
        from unittest.mock import patch

        from syndicate.features.shared import player_headshots

        logos = {"TOR": "u/tor.png", "Toronto Maple Leafs": "u/tor.png", "Vegas Golden Knights": "u/vgk.png"}
        row = {"sport": "nhl", "player_name": "Auston Matthews", "home_team": "Vegas Golden Knights", "away_team": "Toronto Maple Leafs"}
        with patch.object(player_headshots, "_nhl_teams", return_value={"austonmatthews": "TOR"}), \
                patch("syndicate.features.shared.team_logos.logo_url", side_effect=lambda sport, *names: next((logos[n] for n in names if n in logos), None)):
            self.assertEqual(player_headshots.player_side(row), "away")
        with patch.object(player_headshots, "_nhl_teams", return_value={}):
            self.assertIsNone(player_headshots.player_side(row))

    def test_page_never_draws_two_crests_on_a_prop(self) -> None:
        text = TEMPLATE.read_text(encoding="utf-8")
        self.assertIn('return isProp ? "" : `<span class="board-crest-pair">', text)
        self.assertIn("item.player_side", text)


class GameAndRemainingPropLadders(unittest.TestCase):
    """User 2026-10-08: "build it all" -- game-line charts + NBA / MLB / soccer props."""

    def test_ncaaf_normal_ladder_reproduces_the_published_probability(self) -> None:
        from syndicate.features.ncaaf.game_projections import _chart_normal_ladder, _normal_prob_above

        ladder = _chart_normal_ladder(52.0, 14.0, 55.5)
        at = [p for t, p in ladder if t == 55.5][0]
        self.assertAlmostEqual(at, round(_normal_prob_above(55.5, 52.0, 14.0), 4), places=4)

    def test_soccer_margin_ladder_is_unconditional_home_win(self) -> None:
        from syndicate.features.shared.soccer_projections import _scoreline_ladder

        scorelines = {"1-0": 0.3, "0-0": 0.25, "0-1": 0.2, "2-1": 0.15, "1-1": 0.1}
        ladder = _scoreline_ladder(scorelines, 0.0, margin=True)
        at0 = [p for t, p in ladder if t == 0.0][0]
        self.assertAlmostEqual(at0, 0.45, places=4)  # P(home wins) incl. draws in the denominator
        totals = _scoreline_ladder(scorelines, 1.5, margin=False)
        self.assertAlmostEqual([p for t, p in totals if t == 1.5][0], 0.25, places=4)  # 2-1 + 1-1

    def test_mlb_display_prob_does_not_refuse_tails(self) -> None:
        from syndicate.features.shared.prop_projections import _display_prob_over

        dist = {"0": 10, "1": 30, "2": 60}
        self.assertEqual(_display_prob_over(dist, 2.5), 0.0)
        self.assertEqual(_display_prob_over(dist, -0.5), 1.0)
        self.assertAlmostEqual(_display_prob_over(dist, 0.5), 0.9)

    def test_price_ladder_skips_missing_rungs_but_needs_the_line(self) -> None:
        from syndicate.features.shared.price_ladder import price_ladder

        table = {0.5: 0.4, 1.5: 0.12}
        self.assertEqual(price_ladder(lambda t: 1.0 if t < 0 else table.get(t), 0.5),
                         [[-0.5, 1.0], [0.5, 0.4], [1.5, 0.12]])
        self.assertIsNone(price_ladder(lambda t: 1.0 if t < 0 else table.get(t), 2.5))

    def test_board_passes_kind_and_raw_probability(self) -> None:
        from syndicate.features.shared import layer2_board

        row = {"kind": "game", "projection": {"ladder": [[-0.5, 0.6], [0.0, 0.55], [0.5, 0.5]], "ladder_kind": "margin",
                                              "p_model_raw": 0.55, "book_blend": "applied"}}
        cols = layer2_board._chart_columns(row)
        self.assertEqual(cols["sim_ladder_kind"], "margin")
        self.assertEqual(cols["sim_ladder_raw_over"], 0.55)


class TeamRecentResults(unittest.TestCase):
    """Game-row last-10 (mockup board 11): scores from local files, no network."""

    def test_nfl_scores_newest_first_inside_the_window(self) -> None:
        import tempfile
        from pathlib import Path
        from unittest import mock

        from syndicate.features.shared import team_recent_results as trr

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nfl_source" / "tracking" / "nflverse"
            path.mkdir(parents=True)
            (path / "schedules_games.csv").write_text(
                "gameday,home_team,away_team,home_score,away_score\n"
                "2026-01-04,DAL,NYG,20,10\n"      # last season: outside the window
                "2026-09-20,DAL,NYG,37,20\n"
                "2026-09-27,PHI,DAL,34,31\n"
                "2026-10-11,DAL,TB,,\n",          # unplayed
                encoding="utf-8",
            )
            with mock.patch.dict("os.environ", {"SYNDICATE_DATA_ROOT": tmp}):
                got = trr.team_recent_results("nfl", "DAL", "2026-10-08T23:00:00Z")
        self.assertEqual(got, [["2026-09-27", 31.0, 34.0], ["2026-09-20", 37.0, 20.0]])

    def test_unknown_sport_is_empty_not_a_guess(self) -> None:
        from syndicate.features.shared.team_recent_results import team_recent_results

        # Was "nba" until lane board-history-charts gave basketball a source (2026-10-09).
        self.assertEqual(team_recent_results("cricket", "Boston Celtics", "2026-10-08"), [])

    def test_basketball_reads_only_the_current_season(self) -> None:
        """NBA/WNBA team history comes from the NEWEST season's player log only: an October NBA board
        must not reach last June's Finals through the 120-day window (lane board-history-charts)."""
        import tempfile
        from pathlib import Path
        from unittest import mock

        from syndicate.features.shared import team_recent_results as trr

        header = "game_id,date,season,season_type,TEAM_ABBREVIATION,opponent,home_away,PLAYER_ID,PLAYER_NAME,PTS\n"
        with tempfile.TemporaryDirectory() as tmp:
            for sport, last_season, current in (
                ("nba", "g1,2026-06-12,2025,playoffs,BOS,DAL,home,1,A,60\ng1,2026-06-12,2025,playoffs,DAL,BOS,away,2,B,55\n", ""),
                ("wnba", "", "w1,2026-10-04,2026,playoffs,NYL,ATL,home,3,C,50\nw1,2026-10-04,2026,playoffs,NYL,ATL,home,4,D,32\n"
                              "w1,2026-10-04,2026,playoffs,ATL,NYL,away,5,E,92\nw0,2026-09-01,2026,preseason,ATL,NYL,away,5,E,70\n"),
            ):
                base = Path(tmp) / f"{sport}_source" / "data" / "processed"
                base.mkdir(parents=True)
                (base / "player_game_log_2025.csv").write_text(header + last_season, encoding="utf-8")
                (base / "player_game_log_2026.csv").write_text(header + current, encoding="utf-8")
            trr._CACHE.clear()
            with mock.patch.dict("os.environ", {"SYNDICATE_DATA_ROOT": tmp}):
                nba = trr.team_recent_results("nba", "BOS", "2026-10-08")
                wnba = trr.team_recent_results("wnba", "NYL", "2026-10-08")
        self.assertEqual(nba, [], "last season's Finals must not appear on an October NBA board")
        self.assertEqual(wnba, [["2026-10-04", 82.0, 92.0]], "points summed per team; preseason excluded")


class SoccerBttsAndHandicapPricing(unittest.TestCase):
    """User 2026-10-08 "make sure everything is getting sim data": BTTS and
    Asian handicaps priced from the sim's own scoreline distribution."""

    SCORES = {"0-0": 0.10, "1-0": 0.20, "0-1": 0.10, "1-1": 0.15, "2-0": 0.15, "2-1": 0.15, "0-2": 0.05, "3-1": 0.10}

    def test_btts_sums_the_both_scored_cells(self) -> None:
        from syndicate.features.shared.soccer_projections import _btts_prob_from_scorelines

        self.assertAlmostEqual(_btts_prob_from_scorelines(self.SCORES), 0.40)  # 1-1, 2-1, 3-1

    def test_half_line_is_plain_cover_probability(self) -> None:
        from syndicate.features.shared.soccer_projections import _handicap_prob_from_scorelines

        p, push = _handicap_prob_from_scorelines(self.SCORES, 0.5)  # away +0.5 / home -0.5: home must win
        self.assertAlmostEqual(p, 0.60)
        self.assertEqual(push, 0.0)

    def test_whole_line_conditions_out_the_push(self) -> None:
        from syndicate.features.shared.soccer_projections import _handicap_prob_from_scorelines

        # home -1 (away line +1): win by 2+ = 0.25 (2-0, 3-1... 2-0 is +2, 3-1 is +2), push on +1 = 0.35
        p, push = _handicap_prob_from_scorelines(self.SCORES, 1.0)
        self.assertAlmostEqual(push, 0.35)
        self.assertAlmostEqual(p, 0.25 / 0.65)

    def test_quarter_line_home_and_away_sum_to_one(self) -> None:
        from syndicate.features.shared.soccer_projections import _handicap_prob_from_scorelines

        home, _ = _handicap_prob_from_scorelines(self.SCORES, 0.25)
        # The away leg of the same market is the home leg of the mirrored line.
        mirrored = {f"{k.split('-')[1]}-{k.split('-')[0]}": v for k, v in self.SCORES.items()}
        away, _ = _handicap_prob_from_scorelines(mirrored, -0.25)
        self.assertAlmostEqual(home + away, 1.0)

    def test_beyond_the_simulated_support_is_refused(self) -> None:
        from syndicate.features.shared.soccer_projections import _handicap_prob_from_scorelines

        self.assertIsNone(_handicap_prob_from_scorelines(self.SCORES, 3.5))


class SimUnpricedReason(unittest.TestCase):
    def test_reason_words(self) -> None:
        from syndicate.features.shared.layer2_board import _sim_unpriced_reason as why

        self.assertEqual(why({"model_prob_over": 0.3, "edge_unavailable_reason": "the model probability is inside its own simulation noise: x"}, {}), "noise")
        self.assertEqual(why({"projected": 10.5, "model_prob_over": None, "probability_unavailable_reason": "source carries a mean"}, {}), "average")
        self.assertEqual(why({"model_prob_over": 0.6, "edge_unavailable_reason": "one-sided market: no two-sided fair"}, {}), "one_sided")


class NflSegmentPricing(unittest.TestCase):
    """User 2026-10-08: NFL quarter/half lines priced from the sim's segment histograms."""

    def _blocks(self):
        import json
        import tempfile
        from pathlib import Path

        from syndicate.features.shared.nfl_segment_projections import load_nfl_segment_blocks

        seg = {"total_points_dist": {"7": 40, "10": 30, "14": 30}, "margin_dist": {"-3": 30, "0": 20, "3": 30, "7": 20},
               "home_points_mean": 6.0, "away_points_mean": 5.0}
        payload = {"games": {"2026_05_TB_DAL": {"sims": 100, "segments": {"q1": seg, "full": seg}}}}
        tmp = tempfile.mkdtemp()
        (Path(tmp) / "smartsim2_segment_distributions_2026_wk5.json").write_text(json.dumps(payload), encoding="utf-8")
        return load_nfl_segment_blocks([Path(tmp)])

    def test_quarter_total_and_full_spread_are_priced(self) -> None:
        from syndicate.features.shared.nfl_segment_projections import attach_nfl_segment_projections

        blocks = self._blocks()
        base = {"kind": "game", "home_team": "Dallas Cowboys", "away_team": "Tampa Bay Buccaneers",
                "commence_time": "2026-10-09T00:15:00Z"}
        total = dict(base, market="totals", segment="q1", line=10.5)
        spread = dict(base, market="spreads", segment="full", line=1.5, projection={"projected": 1.0, "model_prob_over": None})
        priced_full = dict(base, market="spreads", segment="full", line=1.5, projection={"model_prob_over": 0.4})
        got = attach_nfl_segment_projections([total, spread, priced_full], blocks)
        self.assertAlmostEqual(total["projection"]["model_prob_over"], 0.3)       # only the 14s clear 10.5
        self.assertAlmostEqual(spread["projection"]["model_prob_over"], 0.5)      # home margin > 1.5: 3 and 7
        self.assertEqual(priced_full["projection"]["model_prob_over"], 0.4)      # an existing probability is left alone
        self.assertEqual(got["segment_rows_priced"], 2)


class TeamRecentIntervals(unittest.TestCase):
    """User 2026-10-08: interval rows must not show full-game history."""

    def test_ncaaf_halves_and_quarters_come_from_line_scores(self) -> None:
        import gzip
        import json
        import tempfile
        from pathlib import Path
        from unittest import mock

        from syndicate.features.shared import team_recent_results as trr

        game = {"startDate": "2026-10-03T16:00:00.000Z", "completed": True, "homeTeam": "TCU", "awayTeam": "Baylor",
                "homePoints": 10, "awayPoints": 17, "homeLineScores": [0, 7, 3, 0], "awayLineScores": [0, 7, 10, 0]}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ncaaf_source" / "historical_truth"
            path.mkdir(parents=True)
            with gzip.open(path / "games_2026.json.gz", "wt", encoding="utf-8") as fh:
                json.dump([game], fh)
            with mock.patch.dict("os.environ", {"SYNDICATE_DATA_ROOT": tmp}):
                full = trr.team_recent_results("ncaaf", "TCU", "2026-10-10")
                h1 = trr.team_recent_results("ncaaf", "TCU", "2026-10-10", segment="h1")
                h2 = trr.team_recent_results("ncaaf", "TCU", "2026-10-10", segment="h2")
                mlb_f5 = trr.team_recent_results("mlb", "NYY", "2026-10-10", segment="first5")
        self.assertEqual(full, [["2026-10-03", 10.0, 17.0]])
        self.assertEqual(h1, [["2026-10-03", 7.0, 7.0]])
        self.assertEqual(h2, [["2026-10-03", 3.0, 10.0]])
        self.assertEqual(mlb_f5, [])  # no interval source: nothing, never full-game finals
