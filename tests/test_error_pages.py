"""The 404/500 handlers, added 2026-09-09.

Before them the app registered NO error handler at all: a typo'd URL and an
unhandled exception both served Werkzeug's bare white default page.

The branch worth testing is not "does an error page render" -- it is the
CONTENT NEGOTIATION. There are 213 `/api/...` routes whose callers parse JSON,
and handing one of them an HTML page on a 404 converts a clean "not found"
into a parse error at the caller, which is strictly worse than the failure
being reported. So every test below pins WHICH of the two shapes comes back,
never merely that the status code is right.
"""

from __future__ import annotations

import unittest

from syndicate.app import create_app


class ErrorPageTests(unittest.TestCase):
    def setUp(self) -> None:
        app = create_app()
        app.testing = True
        # `testing = True` sets PROPAGATE_EXCEPTIONS, which re-raises out of
        # the 500 handler instead of running it -- exactly the behaviour that
        # would make the 500 test pass while the handler never executed. Turn
        # it back off explicitly so these tests exercise the real path.
        app.config["PROPAGATE_EXCEPTIONS"] = False

        @app.route("/__test_boom")
        def _boom():
            raise RuntimeError("deliberate test explosion")

        self.app = app
        self.client = app.test_client()

    # --- 404 -------------------------------------------------------------

    def test_html_404_is_the_branded_page_and_offers_a_way_out(self) -> None:
        response = self.client.get("/definitely-not-a-real-page")
        self.assertEqual(response.status_code, 404)
        body = response.get_data(as_text=True)
        self.assertIn("text/html", response.headers["Content-Type"])
        self.assertIn("Error 404", body)
        # The whole point of extending base.html: a person can leave.
        self.assertIn('href="/market-board"', body)
        self.assertIn('href="/syndicate"', body)
        # And the crest is the page's brand moment.
        self.assertIn("shared/syndicate-crest.jpg", body)

    def test_api_404_is_json_even_with_no_accept_header(self) -> None:
        # An XHR that forgot its Accept header is the common case, and it is
        # the one the `/api/` prefix check exists for.
        response = self.client.get("/api/not-a-real-endpoint")
        self.assertEqual(response.status_code, 404)
        self.assertIn("application/json", response.headers["Content-Type"])
        payload = response.get_json()
        self.assertEqual(payload["ok"], False)
        self.assertEqual(payload["status"], 404)
        self.assertIn("error", payload)
        self.assertNotIn("<html", response.get_data(as_text=True).lower())

    def test_non_api_404_is_json_when_the_client_prefers_json(self) -> None:
        response = self.client.get(
            "/definitely-not-a-real-page",
            headers={"Accept": "application/json"},
        )
        self.assertEqual(response.status_code, 404)
        self.assertIn("application/json", response.headers["Content-Type"])
        self.assertEqual(response.get_json()["ok"], False)

    def test_browser_accept_header_still_gets_html(self) -> None:
        # A real browser sends html first but names json in the tail; that
        # must NOT tip the negotiation to JSON.
        response = self.client.get(
            "/definitely-not-a-real-page",
            headers={
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
            },
        )
        self.assertEqual(response.status_code, 404)
        self.assertIn("text/html", response.headers["Content-Type"])
        self.assertIn("Error 404", response.get_data(as_text=True))

    def test_wildcard_accept_gets_html_not_json(self) -> None:
        # `Accept: */*` is curl, most bots and plenty of HTTP clients. It
        # scores html and json equally, so a `>=` quality comparison ties and
        # falls to JSON -- which is what the first implementation did, caught
        # by `curl`ing the running app. A tie is not a preference.
        response = self.client.get(
            "/definitely-not-a-real-page", headers={"Accept": "*/*"}
        )
        self.assertEqual(response.status_code, 404)
        self.assertIn("text/html", response.headers["Content-Type"])

    def test_wildcard_accept_on_an_api_path_still_gets_json(self) -> None:
        # The `/api/` prefix must win over the Accept default, or the fix
        # above would have broken every XHR it was meant to protect.
        response = self.client.get(
            "/api/not-a-real-endpoint", headers={"Accept": "*/*"}
        )
        self.assertEqual(response.status_code, 404)
        self.assertIn("application/json", response.headers["Content-Type"])

    def test_a_route_supplied_404_message_survives_the_branded_page(self) -> None:
        """A branded 404 that is LESS informative than the one it replaced is a
        regression wearing a nicer coat.

        Soccer's unknown-league gate aborts with a description naming every
        valid league. The first version of this handler discarded it and
        printed boilerplate; `test_soccer_blueprint_routes.py` caught it. This
        pins the general rule with a local route, so the guarantee does not
        depend on soccer keeping that behaviour.
        """
        from flask import abort

        @self.app.route("/__test_specific_404")
        def _specific():
            abort(404, description="Unknown widget 'zzz'. Valid widgets: alpha, beta.")

        client = self.app.test_client()
        body = client.get("/__test_specific_404").get_data(as_text=True)
        self.assertIn("Unknown widget", body)
        self.assertIn("alpha, beta", body)
        # And the generic copy is suppressed, not merely appended after it.
        self.assertNotIn("does not match any board, sport or tool", body)

    def test_a_plain_404_does_not_show_werkzeug_boilerplate(self) -> None:
        # werkzeug always populates `description`; only a value DIFFERENT from
        # the class default means a route actually spoke. Reading it naively
        # would put "The requested URL was not found on the server..." on the
        # page, which is the voice this page exists to replace.
        body = self.client.get("/definitely-not-a-real-page").get_data(as_text=True)
        self.assertIn("does not match any board, sport or tool", body)
        self.assertNotIn("The requested URL was not found on the server", body)

    # --- 500 -------------------------------------------------------------

    def test_html_500_renders_the_branded_page(self) -> None:
        response = self.client.get("/__test_boom")
        self.assertEqual(response.status_code, 500)
        body = response.get_data(as_text=True)
        self.assertIn("text/html", response.headers["Content-Type"])
        self.assertIn("Error 500", body)
        self.assertIn('href="/"', body)

    def test_500_does_not_leak_the_exception_to_the_user(self) -> None:
        # The message is logged, not shown. A stack-trace-shaped page is both
        # a poor experience and an information leak.
        body = self.client.get("/__test_boom").get_data(as_text=True)
        self.assertNotIn("deliberate test explosion", body)
        self.assertNotIn("RuntimeError", body)
        self.assertNotIn("Traceback", body)

    def test_500_is_logged_to_stdout_where_render_can_see_it(self) -> None:
        # CLAUDE.md: `logger.info` never reaches Render's log collector, so the
        # handler uses `print(..., flush=True)`. Assert the LINE, because a
        # 500 nobody can find in the logs is most of the cost of a 500.
        import contextlib
        import io as _io

        buffer = _io.StringIO()
        with contextlib.redirect_stdout(buffer):
            self.client.get("/__test_boom")
        logged = buffer.getvalue()
        self.assertIn("UNHANDLED_500", logged)
        self.assertIn("/__test_boom", logged)
        self.assertIn("RuntimeError", logged)

    def test_api_500_is_json(self) -> None:
        @self.app.route("/api/__test_boom")
        def _api_boom():
            raise RuntimeError("deliberate test explosion")

        client = self.app.test_client()
        response = client.get("/api/__test_boom")
        self.assertEqual(response.status_code, 500)
        self.assertIn("application/json", response.headers["Content-Type"])
        self.assertEqual(response.get_json()["ok"], False)
        self.assertEqual(response.get_json()["status"], 500)


if __name__ == "__main__":
    unittest.main()
