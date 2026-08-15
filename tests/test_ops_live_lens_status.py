"""`/api/ops/live-lens/status` exposes the per-tick live_mc tally.

Lane `live-game-line-projection`. Evidence: `.syndicate/deploys.md`,
2026-08-15 follow-up.

`_tally_mlb_live_mc_sources` counts live_mc / live_projection /
segment_projection per gameLens lane, every tick, into `meta["liveMcSources"]`.
Nothing read it: `live_lens_loop_status_payload()` had zero callers. These pin
the route that fixes that, and — more importantly — the two ways the fix could
have been silently useless.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from syndicate.app import app


_TOKEN = "test-admin-token"


@pytest.fixture()
def client():
    # Without a configured token the ops `before_request` short-circuits every
    # route with 503 "ADMIN_TOKEN not configured", so a test that omits this is
    # asserting against the gate rather than against the route under test.
    previous = app.config.get("ADMIN_TOKEN")
    app.config.update(TESTING=True, ADMIN_TOKEN=_TOKEN)
    try:
        with app.test_client() as c:
            yield c
    finally:
        app.config["ADMIN_TOKEN"] = previous


_TICK = {
    "sport": "mlb",
    "date": "2026-08-15",
    "liveMcSources": {"live_mc": 6, "segment_projection": 54},
}


def test_route_returns_the_live_mc_tally(client):
    with patch(
        "syndicate.features.shared.live_lens_loop.live_lens_loop_status_payload",
        return_value={"enabled": False, "intervalSeconds": 60, "threadAlive": False,
                      "latestStatus": {}, "latestTick": _TICK},
    ):
        r = client.get("/api/ops/live-lens/status", headers={"X-Admin-Token": _TOKEN})
    assert r.status_code == 200
    assert r.get_json()["latestTick"]["liveMcSources"] == {"live_mc": 6, "segment_projection": 54}


def test_local_only_fields_are_flagged(client):
    """`enabled`/`threadAlive` are the LOCAL process's and are False on web by
    design. Unflagged, a reader sees `enabled: false` and concludes the loop is
    off — a false negative on the exact question this route exists to answer."""
    with patch(
        "syndicate.features.shared.live_lens_loop.live_lens_loop_status_payload",
        return_value={"enabled": False, "intervalSeconds": 60, "threadAlive": False,
                      "latestStatus": {}, "latestTick": _TICK},
    ):
        r = client.get("/api/ops/live-lens/status", headers={"X-Admin-Token": _TOKEN})
    body = r.get_json()
    assert body["_localFieldsAreThisServiceOnly"] == ["enabled", "intervalSeconds", "threadAlive"]
    # The shared half must NOT be flagged — that is the half that is trustworthy.
    assert "latestTick" not in body["_localFieldsAreThisServiceOnly"]


def test_route_is_admin_gated(client):
    """Every /api/ops/* route is gated by before_request; a new one must not
    be the exception that leaks worker state."""
    r = client.get("/api/ops/live-lens/status")
    assert r.status_code == 401


def test_empty_tick_does_not_error(client):
    """A worker that has not ticked yet returns {}, not a 500."""
    with patch(
        "syndicate.features.shared.live_lens_loop.live_lens_loop_status_payload",
        return_value={"enabled": False, "intervalSeconds": 60, "threadAlive": False,
                      "latestStatus": {}, "latestTick": {}},
    ):
        r = client.get("/api/ops/live-lens/status", headers={"X-Admin-Token": _TOKEN})
    assert r.status_code == 200
    assert r.get_json()["latestTick"] == {}


class TestTheAllowlistFixWouldHaveBeenInert:
    """Pins WHY this is a route and not a hot-artifact allowlist entry.

    The tick file is keyvalue-backed, so it is never written to disk, and
    `/api/ops/artifacts/stream` gates on `target.is_file()`. Allowlisting it
    would 404 forever. If someone later makes that path disk-backed, these fail
    and the cheaper fix becomes available — that is the point of pinning it.
    """

    def test_tick_path_is_keyvalue_backed_so_it_never_reaches_disk(self):
        from syndicate.features.shared import refresh_state_store as store
        from syndicate.features.shared.live_lens_loop import _meta_dir

        path = _meta_dir() / "latest_live_lens_tick.json"
        with patch.object(store, "_state_backend_kind", return_value="keyvalue"):
            assert store._keyvalue_backed(path) is True

    def test_only_migration_runs_is_excluded_from_keyvalue(self):
        from syndicate.features.shared.refresh_state_store import _KEYVALUE_EXCLUDED_PATH_MARKERS

        assert _KEYVALUE_EXCLUDED_PATH_MARKERS == ("migration_runs/",)

    def test_stream_endpoint_still_refuses_the_tick_path(self, client):
        """Belt and braces: the artifact route must not start serving it by
        accident, which would give two sources of truth for one number."""
        r = client.get(
            "/api/ops/artifacts/stream?path=reports/live_lens_loop/latest_live_lens_tick.json",
            headers={"X-Admin-Token": _TOKEN},
        )
        assert r.status_code in (403, 404)
