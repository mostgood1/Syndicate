"""Off-fleet OddsAPI spend reaches the fleet's quota document (lane `layer2-freshness-1h`, 2026-10-03).

Overnight 10-02/03 the account's `used` rose 126,764 credits more than the fleet's
per-sport counters; 26,220 of it was `scripts/backtest_nhl_game_lines.py`, which
DID call `record_oddsapi_quota` -- into the dev machine's filesystem backend.

Every test here uses an in-memory fake client. The first version of this feature
forwarded the quota SUITE's fake observations into PRODUCTION (15:52-15:54Z),
which is why forwarding is off under pytest unless forced.
"""
from __future__ import annotations

import json

import pytest

from syndicate.features.shared import oddsapi_quota as q

KEY = "syndicate:refresh-state:/fleet/data/reports/odds_control_plane/oddsapi_quota.json"


class _Pipe:
    def __init__(self, store):
        self.store, self.ops = store, []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def watch(self, key):
        self.watched = key

    def multi(self):
        pass

    def set(self, key, value, keepttl=False):
        self.ops.append((key, value, keepttl))

    def execute(self):
        for key, value, keepttl in self.ops:
            self.store.data[key] = value
            self.store.keepttl_seen.append(keepttl)


class _FakeRedis:
    def __init__(self, data):
        self.data, self.keepttl_seen = dict(data), []

    def scan_iter(self, match=None, count=None):
        import fnmatch

        return [k.encode() for k in self.data if fnmatch.fnmatch(k, match)]

    def get(self, key):
        v = self.data.get(key)
        return v.encode() if isinstance(v, str) else v

    def pipeline(self, transaction=True):
        return _Pipe(self)


@pytest.fixture
def fleet(monkeypatch):
    seed = {"latest": {"used": 1000}, "baseline": {"used": 900}, "by_sport": {"nfl": {"calls": 5, "credits": 50}}}
    fake = _FakeRedis({KEY: json.dumps(seed)})
    monkeypatch.setattr(q, "_FLEET_FORWARD_STATE", {"announced": False, "key": None, "client": None, "failed": None})
    import redis

    monkeypatch.setattr(redis.Redis, "from_url", classmethod(lambda cls, url, **kw: fake))
    monkeypatch.setenv("SYNDICATE_ODDSAPI_QUOTA_FORWARD", "force")
    monkeypatch.setattr(q, "_fleet_forward_enabled", q._fleet_forward_enabled)
    from syndicate.features.shared import refresh_state_store

    monkeypatch.setattr(refresh_state_store, "_keyvalue_backed", lambda path: False)
    return fake


def _obs(used=1030, last=30):
    return {"used": used, "remaining": 5_000_000 - used, "last_cost": last, "sport": "nhl",
            "endpoint": "historical/sports/icehockey_nhl/odds", "observedAt": "2026-10-03T00:50:00Z"}


def _forward(obs):
    return q._forward_to_fleet(obs, sport_key="nhl", last_cost=obs["last_cost"], families={"historical": 30.0},
                               family_error=None, hour_key="00")


def test_reachability_an_off_fleet_observation_lands_in_its_own_bucket(fleet, capsys):
    assert _forward(_obs()) == "ok:nhl:offfleet"
    doc = json.loads(fleet.data[KEY])
    assert doc["by_sport"]["nhl:offfleet"] == {"calls": 1, "credits": 30}
    assert doc["by_sport"]["nfl"] == {"calls": 5, "credits": 50}, "a production sport is never touched"
    assert doc["latest"]["used"] == 1030
    assert fleet.keepttl_seen == [True], "the fleet key's TTL is kept"
    assert "FLEET_FORWARD status=ok:nhl:offfleet" in capsys.readouterr().out


def test_off_under_pytest_unless_forced(monkeypatch):
    from syndicate.features.shared import refresh_state_store

    monkeypatch.setattr(refresh_state_store, "_keyvalue_backed", lambda path: False)
    monkeypatch.delenv("SYNDICATE_ODDSAPI_QUOTA_FORWARD", raising=False)
    assert q._fleet_forward_enabled() is False, "a test run must never write the fleet's document"
    monkeypatch.setenv("SYNDICATE_ODDSAPI_QUOTA_FORWARD", "force")
    assert q._fleet_forward_enabled() is True


def test_a_fleet_process_does_not_forward(monkeypatch):
    from syndicate.features.shared import refresh_state_store

    monkeypatch.setenv("SYNDICATE_ODDSAPI_QUOTA_FORWARD", "force")
    monkeypatch.setattr(refresh_state_store, "_keyvalue_backed", lambda path: True)
    assert q._fleet_forward_enabled() is False


def test_no_key_or_two_keys_writes_nothing(fleet):
    fleet.data = {}
    assert _forward(_obs()) == "skipped:no_quota_key"
    q._FLEET_FORWARD_STATE.update({"failed": None, "client": None, "key": None})
    fleet.data = {KEY: "{}", KEY.replace("/fleet/", "/other/"): "{}"}
    assert _forward(_obs()) == "skipped:ambiguous:2_keys"


def test_an_empty_fleet_document_is_never_rebuilt(fleet):
    fleet.data[KEY] = "{}"
    assert _forward(_obs()) == "skipped:fleet_document_unreadable"
    assert fleet.data[KEY] == "{}"


def test_off_switch(monkeypatch):
    monkeypatch.setenv("SYNDICATE_ODDSAPI_QUOTA_FORWARD", "0")
    assert q._fleet_forward_enabled() is False
