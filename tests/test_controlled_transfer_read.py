"""The controlled-transfer reader must read the bucket the transfer landed IN.

A bandwidth bucket is labelled by its hour's START
(`.syndicate/findings_2026-09-10_spike_crossing_and_labelling.md`). Until
2026-09-10 the reader took the hour AFTER: its log window was still the
transfer's own hour, so P1/P2 were right, but P3 read the FOLLOWING hour's
meter. Arm 1 (sent 2026-09-09 00:06-00:29Z) was scored against bucket `01:00Z`
(401.1 MB) when its own bucket is `00:00Z` (437.7 MB).

The end-to-end tests drive `main()` with Render stubbed, so what is pinned is
the reading file the tool actually writes.
"""
import json
import sys

from scripts import controlled_transfer_read as ctr

ARM1 = {
    "transfer_started_at": "2026-09-09T00:06:27Z",
    "transfer_ended_at": "2026-09-09T00:29:10Z",
    "requests_200": 2596,
    "known_bytes": 158_207_000,
}
METER = {"2026-09-08T23:00:00Z": 315.3, "2026-09-09T00:00:00Z": 437.7, "2026-09-09T01:00:00Z": 401.1}


def test_the_bucket_is_the_hour_the_moment_falls_in():
    assert ctr._bucket_for("2026-09-09T00:06:27Z") == "2026-09-09T00:00:00Z"
    assert ctr._bucket_for("2026-09-09T23:59:59.900000Z") == "2026-09-09T23:00:00Z"
    assert ctr._bucket_for("2026-09-09T01:00:00Z") == "2026-09-09T01:00:00Z"


def test_a_transfer_across_the_hour_is_still_detected_as_straddling():
    assert ctr._bucket_for("2026-09-09T00:59:50Z") != ctr._bucket_for("2026-09-09T01:00:10Z")


def _read(monkeypatch, tmp_path, *, existing=None):
    transfer = tmp_path / "controlled_transfer_20260909T000627Z.json"
    transfer.write_text(json.dumps(ARM1), encoding="utf-8")
    reading_path = tmp_path / "controlled_transfer_20260909T000627Z_reading.json"
    if existing is not None:
        reading_path.write_text(json.dumps(existing), encoding="utf-8")
    calls = []

    def fake_logs(key, resource, start, end, log_type, max_pages=200):
        calls.append((log_type, start, end))
        return []

    monkeypatch.setattr(ctr, "_api_key", lambda: "k")
    monkeypatch.setattr(ctr, "_metric", lambda *a, **k: dict(METER))
    monkeypatch.setattr(ctr, "_logs", fake_logs)
    monkeypatch.setattr(sys, "argv", ["read", str(transfer)])
    assert ctr.main() == 0
    return json.loads(reading_path.read_text(encoding="utf-8")), calls


def test_arm_1_is_read_against_its_OWN_bucket(monkeypatch, tmp_path):
    reading, calls = _read(monkeypatch, tmp_path)

    assert reading["bucket"] == "2026-09-09T00:00:00Z"
    assert reading["metered_mb"] == 437.7, "the meter must be the transfer's hour, not the next one"
    assert reading["window"] == {"start": "2026-09-09T00:00:00Z", "end": "2026-09-09T01:00:00Z"}
    assert reading["settled"] is True
    # Both logs over the transfer's own hour -- the part the old code got right.
    assert calls == [("request", "2026-09-09T00:00:00Z", "2026-09-09T01:00:00Z"),
                     ("app", "2026-09-09T00:00:00Z", "2026-09-09T01:00:00Z")]


def test_a_reading_of_a_DIFFERENT_bucket_is_kept_not_overwritten(monkeypatch, tmp_path):
    old = {"bucket": "2026-09-09T01:00:00Z", "metered_mb": 401.1}
    reading, _ = _read(monkeypatch, tmp_path, existing=old)

    assert reading["bucket"] == "2026-09-09T00:00:00Z"
    assert reading["superseded"] == old


def test_a_re_read_of_the_SAME_bucket_replaces_it(monkeypatch, tmp_path):
    reading, _ = _read(monkeypatch, tmp_path, existing={"bucket": "2026-09-09T00:00:00Z", "metered_mb": 1.0})

    assert "superseded" not in reading
    assert reading["metered_mb"] == 437.7
