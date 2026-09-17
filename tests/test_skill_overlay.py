"""`skill_overlay` -- the auto-updated scoring table (USER DECISION 2026-09-17 "Auto-update measured skill").

The guardrails are the tests: validated verdicts only, the sample floors, the loss scale,
expiry, the bucket cap, and the kill switch. And reachability: a validated overlay loss
CHANGES `bucket_factor` with the switch on and does not with it off (off != on).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

import syndicate.features.shared.measured_bucket_skill as mbs
from syndicate.features.shared import skill_overlay as so

NOW = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)
VIEW = {"sport": "mlb", "market": "totals", "segment": "full", "phase": "live", "model_edge_pct": 12.0,
        "fair_probability": 0.5, "book_age_seconds": 60.0, "books_quoting": 8.0, "fair_method": "consensus"}
LOSS_ID = "mlb|totals|full|live|disagreement=10+"


def _payload(**overrides):
    payload = {
        "source": "model_scorecard/1",
        "generated_at": NOW.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "expires_at": (NOW + timedelta(hours=72)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "buckets": {LOSS_ID: {"verdict": "skill_loss", "games": 80, "dates": 6, "established_loss_rel": 0.2}},
    }
    payload.update(overrides)
    return payload


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    so.reset_cache()
    monkeypatch.delenv(so.ENV_SWITCH, raising=False)
    monkeypatch.delenv("ADMIN_TOKEN", raising=False)
    yield
    so.reset_cache()


def test_a_valid_payload_becomes_the_table():
    table, reason = so.validate(_payload(), now=NOW)
    assert reason == "ok" and set(table) == {LOSS_ID}


@pytest.mark.parametrize("mutate, reason", [
    (lambda p: p.update(expires_at=(NOW - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ")), "expired"),
    (lambda p: p.pop("expires_at"), "no_expiry"),
    (lambda p: p.update(source="hand_written"), "unknown_source"),
    (lambda p: p["buckets"][LOSS_ID].update(verdict="parity"), "unvalidated_verdict"),
    (lambda p: p["buckets"][LOSS_ID].update(games=59), "below_sample_floor"),
    (lambda p: p["buckets"][LOSS_ID].update(dates=4), "below_sample_floor"),
    (lambda p: p["buckets"][LOSS_ID].update(established_loss_rel=-0.1), "malformed_loss_scale"),
    (lambda p: p["buckets"].update({"mlb|totals|full|live": {"verdict": "skill_loss"}}), "malformed_bucket"),
    (lambda p: p.update(buckets={f"mlb|totals|full|live|x={i}": {"verdict": "skill_pocket", "games": 90, "dates": 9}
                                 for i in range(so.MAX_BUCKETS + 1)}), "too_many_buckets"),
])
def test_every_guardrail_refuses_the_whole_file(mutate, reason):
    payload = _payload()
    mutate(payload)
    assert so.validate(payload, now=NOW) == (None, reason)


def test_reachability_the_overlay_moves_bucket_factor_and_the_switch_takes_it_away(tmp_path, monkeypatch):
    path = tmp_path / "overlay.json"
    path.write_text(json.dumps(_payload()), encoding="utf-8")
    monkeypatch.setattr(so, "_overlay_file", lambda: path)
    monkeypatch.setattr(so, "datetime", _FrozenDatetime)
    on = mbs.bucket_factor(VIEW)
    assert on == pytest.approx(max(mbs.SKILL_FLOOR if hasattr(mbs, "SKILL_FLOOR") else 0.0, 1 - mbs.SKILL_GAIN * 0.2))
    assert so.status()["source"] == "overlay"
    so.reset_cache()
    monkeypatch.setenv(so.ENV_SWITCH, "off")
    assert mbs.bucket_factor(VIEW) is None, "the static table is empty, so the switch removes the factor"
    assert so.status() == {"source": "static", "reason": "switch_off", "buckets": 0}


def test_an_absent_or_expired_file_falls_back_to_the_static_table(tmp_path, monkeypatch):
    static = {"x": {"verdict": "skill_pocket"}}
    assert so.active_table(static, path=tmp_path / "missing.json", now=NOW, pull=False) is static
    assert so.status()["reason"] == "overlay_absent"
    expired = tmp_path / "expired.json"
    expired.write_text(json.dumps(_payload()), encoding="utf-8")
    assert so.active_table(static, path=expired, now=NOW + timedelta(days=4), pull=False) is static
    assert so.status()["reason"] == "expired"


def test_a_corrupt_file_never_raises(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    static = {}
    assert so.active_table(static, path=bad, now=NOW, pull=False) is static
    assert so.status()["source"] == "static" and so.status()["reason"].startswith("error:")


def test_without_a_token_a_missing_file_starts_no_pull(tmp_path, monkeypatch):
    started = []
    monkeypatch.setattr(so.threading, "Thread", lambda *a, **k: started.append(1))
    so.active_table({}, path=tmp_path / "missing.json", now=NOW)
    assert started == []


class _FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW if tz else NOW.replace(tzinfo=None)
