"""`live_state_payload` must read ACROSS SERVICES, not just off local disk.

The live poller writes this file on live-odds-worker's disk. Web has a
different one -- a hard Render constraint -- so a bare filesystem read returned
None on web for every match ever played. Measured 2026-08-21 on four finished
European fixtures: `/api/ops/artifacts/export` (keyvalue-backed) showed a full
`match_box` with score 3-0, three goals and both teams' stats, while the card
rendered "Goals" and "Match stats" as EMPTY HEADERS. The score was right
because it comes from the readable recommendations artifact; only the box
sections depended on the unreachable path.
"""
from __future__ import annotations

import json

from syndicate.features.soccer import sources


def test_reads_through_the_state_store_when_disk_has_nothing(monkeypatch, tmp_path):
    """The production case: nothing on THIS box, everything in the store."""
    payload = {"league": "epl", "date": "2026-08-21", "match_box": {"401879301": {"score_home": 3}}}
    monkeypatch.setattr(sources, "live_state_path", lambda lg, d: tmp_path / "absent.json")
    monkeypatch.setattr(
        "syndicate.features.shared.refresh_state_store.read_json_file",
        lambda path: payload,
    )
    assert sources.live_state_payload("epl", "2026-08-21") == payload


def test_falls_back_to_disk_when_the_store_is_empty(monkeypatch, tmp_path):
    """Local dev: keyvalue configured, but the file exists only on this box
    because this box ran the poller. Without the fallback, fixing production
    would break development."""
    disk = tmp_path / "live_state_2026-08-21.json"
    disk.write_text(json.dumps({"league": "epl", "match_box": {"x": {}}}), encoding="utf-8")
    monkeypatch.setattr(sources, "live_state_path", lambda lg, d: disk)
    monkeypatch.setattr(
        "syndicate.features.shared.refresh_state_store.read_json_file",
        lambda path: None,
    )
    out = sources.live_state_payload("epl", "2026-08-21")
    assert out is not None and out["match_box"] == {"x": {}}


def test_a_store_error_degrades_to_disk_rather_than_a_blank_card(monkeypatch, tmp_path):
    """A store hiccup must not empty the card -- that would be a worse failure
    than the one being fixed, and silent."""
    disk = tmp_path / "live_state_2026-08-21.json"
    disk.write_text(json.dumps({"league": "epl", "match_box": {"y": {}}}), encoding="utf-8")
    monkeypatch.setattr(sources, "live_state_path", lambda lg, d: disk)

    def _boom(path):
        raise RuntimeError("keyvalue unavailable")

    monkeypatch.setattr("syndicate.features.shared.refresh_state_store.read_json_file", _boom)
    out = sources.live_state_payload("epl", "2026-08-21")
    assert out is not None and out["match_box"] == {"y": {}}


def test_an_empty_store_payload_is_not_treated_as_an_answer(monkeypatch, tmp_path):
    """`{}` from the store means "nothing there", not "this match had no box".
    Treating it as an answer would reintroduce the empty-header bug via a
    different route."""
    disk = tmp_path / "live_state_2026-08-21.json"
    disk.write_text(json.dumps({"league": "epl", "match_box": {"z": {}}}), encoding="utf-8")
    monkeypatch.setattr(sources, "live_state_path", lambda lg, d: disk)
    monkeypatch.setattr(
        "syndicate.features.shared.refresh_state_store.read_json_file", lambda path: {}
    )
    out = sources.live_state_payload("epl", "2026-08-21")
    assert out is not None and out["match_box"] == {"z": {}}


def test_the_path_handed_to_the_store_is_the_one_the_WORKER_WROTE(monkeypatch):
    """THE ACTUAL BUG, pinned.

    `read_json_file` derives its keyvalue key FROM THE PATH. `_api_read_path`
    returns "the first root that actually HAS it" -- and on web the file exists
    on NEITHER root, because the poller wrote it to live-odds-worker's disk. So
    web resolved a different absolute path and queried a key the worker never
    wrote. Swapping only the reader (`0aaf71f0`) fixed nothing for exactly this
    reason; the path has to come from `data_root()`, which is the root the
    worker writes under.
    """
    seen = {}

    def _capture(path):
        seen["path"] = str(path).replace("\\", "/")
        return {"league": "epl", "match_box": {"401879301": {}}}

    monkeypatch.setattr(
        "syndicate.features.shared.refresh_state_store.read_json_file", _capture
    )
    monkeypatch.setattr(
        "syndicate.features.shared.refresh_state_store.data_root", lambda: __import__("pathlib").Path("/opt/render/project/data")
    )
    out = sources.live_state_payload("epl", "2026-08-21")
    assert out is not None
    assert seen["path"].endswith(
        "/soccer_source/epl/api/live_state/live_state_2026-08-21.json"
    ), seen["path"]
    # And it must be under the DATA ROOT, not the repo checkout -- the repo
    # path is what `_api_read_path` would have produced.
    assert seen["path"].startswith("/opt/render/project/data/"), seen["path"]
