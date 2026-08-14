"""`#433` — the read-only vendor-catalogue route.

WHY IT EXISTS. Three soccer leagues stopped reaching `tracking/book_quotes` for
3.6 days while eredivisie — same script, same key, same region, same shard —
kept capturing. Every in-pipeline explanation was falsified: the season gate
reports all ten leagues active, a single-league scoped run captured nothing
(so it is not the 50-step run truncating), and the shard append logged no
failure. The one input nobody could see was the vendor's own catalogue.

These cover the parts that would quietly mislead a diagnosis: a missing key
reported as a vendor outage, the three catalogue states collapsed into two, and
the endpoint's own cost going unattributed.
"""

from __future__ import annotations

import io
import json

import pytest

from syndicate.app import create_app


CATALOGUE = [
    {"key": "soccer_netherlands_eredivisie", "active": True, "title": "Eredivisie", "has_outrights": False},
    {"key": "soccer_efl_champ", "active": False, "title": "Championship", "has_outrights": False},
    {"key": "soccer_usa_mls", "active": True, "title": "MLS", "has_outrights": False},
    {"key": "americanfootball_nfl", "active": True, "title": "NFL", "has_outrights": False},
]


class _FakeResponse(io.BytesIO):
    def __init__(self, payload, headers=None):
        super().__init__(json.dumps(payload).encode())
        self.headers = headers or {"x-requests-used": "1000", "x-requests-remaining": "9000", "x-requests-last": "0"}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
        return False


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("ODDS_API_KEY", "test-key-do-not-use")
    monkeypatch.setenv("ADMIN_TOKEN", "test-admin")
    app = create_app()
    app.testing = True
    return app.test_client()


def _get(client, **kwargs):
    return client.get("/api/ops/oddsapi/sports", headers={"Authorization": "Bearer test-admin"}, **kwargs)


def test_each_league_reports_listed_and_active_separately(client, monkeypatch):
    """THREE STATES, NEVER TWO.

    Absent from the catalogue, present-but-inactive, and present-and-active are
    different diagnoses with different owners: the first is a mapping bug on our
    side, the second is the vendor's season, the third exonerates the vendor
    entirely. Collapsing any pair sends the next session down the wrong path —
    which is precisely what happened when `active_leagues_for_date` (a
    month-based guess) was read as though it described the vendor.
    """
    # Patched on `urllib.request` itself: the route imports it INSIDE the
    # function, so there is no module-level attribute on the blueprint to patch.
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: _FakeResponse(CATALOGUE))

    payload = json.loads(_get(client).get_data(as_text=True))
    by_league = {row["league"]: row for row in payload["soccer"]}

    assert by_league["eredivisie"]["listed"] is True
    assert by_league["eredivisie"]["active"] is True

    # Listed but out of season — the vendor knows it, it just is not running.
    assert by_league["championship"]["listed"] is True
    assert by_league["championship"]["active"] is False

    # Absent entirely. `active` is None, NOT False: we do not know its season,
    # and reporting False would assert something the catalogue never said.
    assert by_league["primeira_liga"]["listed"] is False
    assert by_league["primeira_liga"]["active"] is None


def test_a_missing_key_is_named_rather_than_reported_as_a_vendor_failure(monkeypatch):
    """503 with the reason, not a 502 that reads like OddsAPI is down."""
    monkeypatch.delenv("ODDS_API_KEY", raising=False)
    monkeypatch.setenv("ADMIN_TOKEN", "test-admin")
    app = create_app()
    app.testing = True

    response = app.test_client().get("/api/ops/oddsapi/sports", headers={"Authorization": "Bearer test-admin"})

    assert response.status_code == 503
    assert "ODDS_API_KEY" in json.loads(response.get_data(as_text=True))["error"]


def test_the_route_records_its_own_quota_headers(client, monkeypatch):
    """Do not take "this endpoint is free" on trust — measure it.

    `/v4/sports` is documented as not counting against the quota. If that is
    ever wrong, the burn must appear in the quota telemetry attributed to this
    route rather than silently inflating a sport's total.
    """
    recorded: dict[str, object] = {}

    def _fake_record(headers, *, sport=None, endpoint=None):
        recorded["sport"] = sport
        recorded["endpoint"] = endpoint
        return None

    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: _FakeResponse(CATALOGUE))
    monkeypatch.setattr("syndicate.features.shared.oddsapi_quota.record_oddsapi_quota", _fake_record)

    _get(client)

    assert recorded.get("sport") == "ops_catalogue"
    assert "apiKey" not in str(recorded.get("endpoint", ""))


def test_a_vendor_error_does_not_masquerade_as_an_empty_catalogue(client, monkeypatch):
    """An upstream failure must 502, not return `soccer: []`.

    An empty list would read as "the vendor offers none of our leagues", which
    is a catastrophic and completely wrong conclusion to hand a diagnosis.
    """
    def _boom(*args, **kwargs):
        raise TimeoutError("upstream timed out")

    monkeypatch.setattr("urllib.request.urlopen", _boom)

    response = _get(client)

    assert response.status_code == 502
    assert json.loads(response.get_data(as_text=True))["ok"] is False
