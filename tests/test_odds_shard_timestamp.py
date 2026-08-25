"""The odds-history shards stamp `updated_at`, and nothing looked for it.

MEASURED across every VENUE_REPRICE on 2026-08-24/25:

  mlb    oddsapi {'status': 'error', 'reason': 'shard_has_no_timestamp'}
  wnba   oddsapi {'status': 'error', 'reason': 'shard_has_no_timestamp'}
  soccer oddsapi {'status': 'error', 'reason': 'shard_has_no_timestamp'}

That reason is only reachable AFTER the payload loads and AFTER `markets` is
confirmed non-empty, so the shards were present and full the whole time. The
real shape:

  data/mlb_source/artifacts/mlb/odds_history.json
    'date', 'markets' (35 entries), 'updated_at' = '2026-07-12T02:47:30+00:00'

`_fetched_at` looked for fetched_at / generated_at / last_updated / as_of and
never `updated_at`, so one missing key name took an entire odds source offline
for three sports at once -- reported as an ERROR, which reads like a feed to
chase rather than a name to fix.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared.venue_quote_adapters import _fetched_at


def test_updated_at_resolves_to_a_timestamp():
    """The exact shape of the real shards."""
    payload = {"date": "2026-08-24", "markets": {"a": 1}, "updated_at": "2026-07-12T02:47:30+00:00"}

    assert _fetched_at(payload, None) is not None


def test_a_shard_with_ONLY_updated_at_is_no_longer_timestampless():
    """The regression, stated as the production symptom."""
    payload = {"markets": {"a": 1}, "updated_at": "2026-08-24T23:00:00Z"}

    resolved = _fetched_at(payload, None)

    assert resolved is not None and resolved > 0


@pytest.mark.parametrize(
    "key", ["fetched_at", "generated_at", "last_updated", "as_of", "updated_at"]
)
def test_every_accepted_timestamp_key_resolves(key):
    assert _fetched_at({key: "2026-08-24T12:00:00Z"}, None) is not None


def test_an_explicit_fetch_stamp_STILL_WINS_over_updated_at():
    """Appended, not inserted. A shard carrying both must prefer the fetch
    stamp -- `updated_at` can only ADD a resolvable timestamp, never displace
    a more precise one."""
    payload = {
        "fetched_at": "2026-08-24T23:00:00Z",
        "updated_at": "2026-07-12T02:47:30+00:00",
    }

    resolved = _fetched_at(payload, None)
    fetched_only = _fetched_at({"fetched_at": "2026-08-24T23:00:00Z"}, None)

    assert resolved == fetched_only


def test_a_shard_with_no_stamp_at_all_still_returns_the_mtime_fallback():
    assert _fetched_at({"markets": {"a": 1}}, 1787622814.0) == 1787622814.0


def test_a_shard_with_no_stamp_and_no_mtime_still_refuses():
    """The refusal must survive -- a quote with no defensible age must not
    silently acquire one."""
    assert _fetched_at({"markets": {"a": 1}}, None) is None


def test_the_oddsapi_adapter_stops_erroring_on_a_real_shard_shape(monkeypatch):
    """End to end through the adapter, not just the helper."""
    from syndicate.features.shared import venue_quote_adapters as adapters

    payload = {
        "date": "2026-08-24",
        "updated_at": "2026-08-24T23:00:00Z",
        "markets": {
            "event_id=abc|home_team=Chicago Cubs|away_team=Arizona Diamondbacks"
            "|market=h2h|side=home|book=draftkings": {"price": -120},
        },
    }
    monkeypatch.setattr(
        "syndicate.features.shared.odds_control_plane.load_odds_history_payload_for_sport",
        lambda sport, date: payload,
    )

    outcome = adapters.oddsapi_outcome("mlb", "2026-08-24")

    assert outcome.reason != "shard_has_no_timestamp"
    assert outcome.status != "error", outcome.reason
