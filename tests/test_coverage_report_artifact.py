"""The coverage report: worker publishes, web reads, web NEVER builds.

The load-bearing test in here is `test_the_page_renders_with_the_expensive_
builder_unreachable`. Everything else could pass while the request handler
quietly called `build_intelligence_status()` -- the call
`pipeline/intelligence_state.py` records as "confirmed live to single-handedly
exceed the refresh-worker's 2GB memory limit" -- and a 200 would look exactly
the same in a test as it does in the incident. So that test makes the builder
RAISE and requires the page to render anyway. Asserting the outcome would not
have caught the defect; asserting the branch does.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from syndicate.app import create_app
from syndicate.features.shared.coverage_report_artifact import coverage_artifact_path
from syndicate.features.shared.coverage_report_artifact import project_coverage_report
from syndicate.features.shared.coverage_report_artifact import publish_coverage_report
from syndicate.features.shared.coverage_report_artifact import read_coverage_report


def _status_fixture() -> dict:
    """Shaped like build_intelligence_status()'s return, including the keys the
    projection must DROP -- `refresh_status` and `daily_update` are the two
    biggest contributors to the full blob and neither is rendered."""
    return {
        "selected_date": "2026-09-09",
        "sports": [
            {
                "slug": "mlb",
                "name": "MLB",
                "context_label": "2026-09-09",
                "data_health": "ready",
                "data_warnings": ["one warning"],
                "tracked_ready": True,
                "advanced_ready": False,
                "active_today": True,
                "advanced_gate": {
                    "ready": False,
                    "missing_inputs": [{"label": f"missing-{i}"} for i in range(10)],
                    "publish_missing_inputs": [{"label": "unpublished-a"}],
                },
                "advanced_inputs": [
                    {
                        "label": "Statcast",
                        "path": "data/mlb_source/statcast.json",
                        "metrics": ["xwoba", "barrel_rate"],
                        "exists": True,
                        "tracked": True,
                    }
                ],
                "artifacts": [
                    {"label": "Daily summary", "path": "data/x.json", "exists": True, "tracked": False}
                ],
            }
        ],
        "tracked_summary": {"tracked_ok": 7, "tracked_total": 9},
        "advanced_summary": {"tracked_ok": 2, "tracked_total": 5},
        "readiness_gate": {
            "ready": False,
            "ready_sports": [{"slug": "mlb"}],
            "blocked_sports": [{"slug": "nba"}, {"slug": "nhl"}],
        },
        "refresh_status": {"a": "x" * 5000},
        "daily_update": {"b": "y" * 5000},
    }


class ProjectionTests(unittest.TestCase):
    def test_projection_keeps_every_field_the_template_renders(self) -> None:
        report = project_coverage_report(_status_fixture(), "2026-09-09")
        self.assertEqual(report["tracked_summary"], {"tracked_ok": 7, "tracked_total": 9})
        self.assertEqual(report["advanced_summary"], {"tracked_ok": 2, "tracked_total": 5})
        self.assertEqual(report["readiness_gate"]["ready"], False)
        self.assertEqual(report["readiness_gate"]["ready_sports"], ["mlb"])
        self.assertEqual(report["readiness_gate"]["blocked_sports"], ["nba", "nhl"])
        sport = report["sports"][0]
        for field in (
            "context_label", "name", "data_health", "data_warnings",
            "tracked_ready", "advanced_ready", "active_today",
            "advanced_gate", "advanced_inputs", "artifacts",
        ):
            self.assertIn(field, sport, f"template renders sport.{field}")
        self.assertEqual(sport["advanced_inputs"][0]["metrics"], ["xwoba", "barrel_rate"])
        self.assertEqual(sport["artifacts"][0]["tracked"], False)

    def test_projection_drops_the_bulk_the_page_never_renders(self) -> None:
        # The size control IS the correctness control here: the keyvalue store
        # rejects at 8MB and drops the connection near 9MB, and the full status
        # blob is what got this call blamed for an OOM in the first place.
        report = project_coverage_report(_status_fixture(), "2026-09-09")
        self.assertNotIn("refresh_status", report)
        self.assertNotIn("daily_update", report)

    def test_missing_input_lists_are_capped_at_what_the_page_shows(self) -> None:
        # The template slices [:6]; publishing 10 would be bytes nobody reads.
        report = project_coverage_report(_status_fixture(), "2026-09-09")
        self.assertEqual(len(report["sports"][0]["advanced_gate"]["missing_inputs"]), 6)

    def test_projection_survives_a_malformed_status(self) -> None:
        # A coverage page must not be able to raise inside the loop that
        # produces the boards, so the projection tolerates junk.
        for junk in (None, {}, {"sports": "not-a-list"}, {"sports": [None, 3, "x"]}):
            report = project_coverage_report(junk, "2026-09-09")
            self.assertEqual(report["sports"], [])
            self.assertEqual(report["tracked_summary"]["tracked_total"], 0)

    def test_published_payload_is_far_under_the_keyvalue_ceiling(self) -> None:
        import json

        from syndicate.features.shared.refresh_state_store import _keyvalue_max_bytes  # type: ignore

        status = _status_fixture()
        status["sports"] = status["sports"] * 40  # far more sports than exist
        serialized = json.dumps(project_coverage_report(status, "2026-09-09"), separators=(",", ":"))
        self.assertLess(len(serialized.encode("utf-8")), _keyvalue_max_bytes() // 4)


class PublishReadRoundTripTests(unittest.TestCase):
    def test_publish_then_read_returns_the_report(self) -> None:
        self.assertTrue(publish_coverage_report(_status_fixture(), "2026-09-09"))
        report = read_coverage_report("2026-09-09")
        self.assertIsNotNone(report)
        self.assertEqual(report["tracked_summary"]["tracked_ok"], 7)

    def test_a_report_for_another_date_reads_as_absent(self) -> None:
        publish_coverage_report(_status_fixture(), "2026-09-09")
        self.assertIsNone(read_coverage_report("2026-09-08"))

    def test_a_stale_report_reads_as_absent(self) -> None:
        publish_coverage_report(_status_fixture(), "2026-09-09")
        self.assertIsNone(read_coverage_report("2026-09-09", max_age_seconds=0.0001))

    def test_publish_never_raises_when_the_store_fails(self) -> None:
        # The loop this hangs off produces the boards. A coverage page is a
        # convenience and must not be able to take it down.
        with patch(
            "syndicate.features.shared.coverage_report_artifact.write_json_file",
            side_effect=RuntimeError("store down"),
        ):
            self.assertFalse(publish_coverage_report(_status_fixture(), "2026-09-09"))

    def test_absent_artifact_reads_as_none(self) -> None:
        path = coverage_artifact_path()
        if path.exists():
            path.unlink()
        self.assertIsNone(read_coverage_report("2026-09-09"))


class StatusPageRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        app = create_app()
        app.testing = True
        self.client = app.test_client()

    def test_the_sabotage_patch_actually_bites(self) -> None:
        """CONTROL for the test below, and it is not optional.

        The route does not bind `build_intelligence_status` at all, so patching
        it proves nothing until we know the patch CAN fail something. A healthy
        reading is only evidence once you know what makes it read unhealthy.

        This pins the late-import pattern used throughout this repo
        (`from syndicate.features.intelligence import X` inside a function),
        which is how the expensive call would most plausibly come back.
        """
        with patch(
            "syndicate.features.intelligence.build_intelligence_status",
            side_effect=AssertionError("sabotage"),
        ):
            from syndicate.features.intelligence import build_intelligence_status

            with self.assertRaises(AssertionError):
                build_intelligence_status(selected_date="2026-09-09")

    def test_the_route_does_not_bind_the_expensive_builder_at_module_level(self) -> None:
        """The other half of the control.

        A module-level `from ... import build_intelligence_status` would resolve
        the name at import time, and the sabotage patch below would sail past
        it. So assert the binding does not exist -- the two tests together
        cover both import styles.
        """
        import syndicate.blueprints.intelligence as blueprint

        self.assertFalse(
            hasattr(blueprint, "build_intelligence_status"),
            "the status route must not bind build_intelligence_status; if this "
            "binding is added, the sabotage test below stops discriminating",
        )

    def test_the_page_renders_with_the_expensive_builder_unreachable(self) -> None:
        """THE test in this file.

        `build_intelligence_status()` on a request path is the failure this
        whole lane exists to avoid, and a 200 looks identical whether the route
        read an artifact or built one. So make the builder raise: if the page
        still renders, the no-compute path is the one that ran. The two control
        tests above are what let this one mean something.
        """
        publish_coverage_report(_status_fixture(), "2026-09-09")
        with patch(
            "syndicate.features.intelligence.build_intelligence_status",
            side_effect=AssertionError("the request path must never build the status"),
        ):
            response = self.client.get("/intelligence/status?date=2026-09-09")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers["Content-Type"])
        body = response.get_data(as_text=True)
        self.assertIn("The Syndicate data coverage page", body)
        self.assertIn("7/9", body)  # tracked_summary, straight from the artifact

    def test_the_page_is_html_not_a_redirect(self) -> None:
        # The regression this replaces: the board's "Data coverage" pill 302'd
        # to a JSON endpoint that serves the board state, not coverage.
        response = self.client.get("/intelligence/status?date=2026-09-09")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("application/json", response.headers["Content-Type"])

    def test_no_published_report_renders_a_degraded_page_not_an_error(self) -> None:
        path = coverage_artifact_path()
        if path.exists():
            path.unlink()
        response = self.client.get("/intelligence/status?date=2031-01-01")
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        # Says so, rather than showing 0/0 as if it were measured.
        self.assertIn("No coverage report published for this date yet", body)

    def test_the_board_pill_points_at_a_page_that_serves_html(self) -> None:
        """Pins the link and the target together.

        Either half can be right while the pair is broken -- which is exactly
        what happened for three months: the pill was fine, the route redirected.
        """
        board = self.client.get("/intelligence").get_data(as_text=True)
        self.assertIn('href="/intelligence/status"', board)
        target = self.client.get("/intelligence/status")
        self.assertEqual(target.status_code, 200)
        self.assertIn("text/html", target.headers["Content-Type"])

    def test_the_crest_is_on_the_page(self) -> None:
        response = self.client.get("/intelligence/status?date=2026-09-09")
        self.assertIn("shared/syndicate-crest.jpg", response.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
