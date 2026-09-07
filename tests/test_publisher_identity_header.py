"""Every publish path must name its sender.

`#488` added `X-Artifact-Publisher` so the receiver can tell "one service pruned
its own file" from "a second service overwrote the first's newer copy with an
older one" -- opposite situations needing opposite responses.

MEASURED 2026-09-07: every `[ops.publish] ACCEPTED` line on web read
`publisher=unknown`, including `arsenal_2026.json bytes=546739`. Only
`_publish_streamed` ever sent the header; `publish_hot_artifact` -- the JSON
path, which is what smaller artifacts take -- never did. So the field was
populated for large files and empty for small ones, which is worse than
uniformly absent: it reads as a working field with gaps rather than a missing
one, and it was empty for precisely the incident it exists to detect.

`SYNDICATE_REFRESH_LANE` was set the whole time ('refresh-worker' on the live
service), so the identity existed and only the header dropped it.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from syndicate.features.shared import artifact_publisher as ap


class _FakeResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return b"{}"

    @property
    def headers(self):
        return {}


@pytest.fixture(autouse=True)
def _forget_published_checksums():
    """`_LAST_PUBLISHED_CHECKSUM` is module state with PROCESS lifetime.

    Without this, the second test publishing identical content hits
    `PUBLISH_SKIPPED_UNCHANGED` and never issues a request -- so it asserts
    about headers that were never sent, and whether it passes depends on which
    test ran first. Same order-dependence class as the season-pull flag, found
    the same way: by a test that failed for a reason unrelated to its subject.
    """
    ap._LAST_PUBLISHED_CHECKSUM.clear()
    yield
    ap._LAST_PUBLISHED_CHECKSUM.clear()


@pytest.fixture
def captured(monkeypatch):
    """Capture the outbound request without a network."""
    seen = {}

    def _urlopen(request_obj, *a, **kw):
        seen["headers"] = dict(getattr(request_obj, "headers", {}) or {})
        seen["full"] = {k.lower(): v for k, v in seen["headers"].items()}
        return _FakeResponse()

    monkeypatch.setattr(ap.urllib_request, "urlopen", _urlopen)
    monkeypatch.setattr(ap, "_publish_url", lambda: "https://example.invalid/api/ops/artifacts/publish")
    monkeypatch.setattr(ap, "_admin_token", lambda: "token")
    return seen


def _artifact(tmp_path: Path) -> Path:
    """An ALLOWLISTED relative path, or `publish_hot_artifact` refuses it.

    The first version of this test used a bare filename and got
    `SKIP_NOT_ALLOWLISTED` -- the guard doing its job, and a reminder that a
    publish test which never reaches the request proves nothing about headers.
    """
    p = (tmp_path / "mlb_source" / "source_artifacts" / "data"
         / "sim_input_report" / "sim_input_report_2026-09-07.json")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"hello": "world"}), encoding="utf-8")
    return p


def test_the_JSON_path_sends_the_publisher(captured, tmp_path, monkeypatch):
    """The path that was missing it. This is the regression."""
    monkeypatch.setenv("SYNDICATE_REFRESH_LANE", "refresh-worker")
    monkeypatch.setattr(ap, "_data_root", lambda: tmp_path)
    monkeypatch.setattr(ap, "_publish_budget_blocks", lambda *a, **kw: False)

    ap.publish_hot_artifact(_artifact(tmp_path))

    assert "x-artifact-publisher" in captured["full"], (
        "publish_hot_artifact sent no X-Artifact-Publisher -- the receiver logs "
        "'unknown' and #488's whole purpose is defeated for every small artifact"
    )
    assert captured["full"]["x-artifact-publisher"] == "refresh-worker"


def test_an_UNSET_lane_sends_empty_rather_than_a_guess(captured, tmp_path, monkeypatch):
    """Empty is the honest value and the receiver already handles it.

    `_publisher_identity` returns "" when SYNDICATE_REFRESH_LANE is unset, and
    ops.py maps that to UNKNOWN deliberately -- because assuming
    'same publisher' is the permissive branch and would silence exactly the
    case #488 detects. A fabricated identity here would be worse than none.
    """
    monkeypatch.delenv("SYNDICATE_REFRESH_LANE", raising=False)
    monkeypatch.setattr(ap, "_data_root", lambda: tmp_path)
    monkeypatch.setattr(ap, "_publish_budget_blocks", lambda *a, **kw: False)

    ap.publish_hot_artifact(_artifact(tmp_path))

    assert captured["full"].get("x-artifact-publisher") == "", (
        "an unset lane must send an EMPTY identity, not a hostname or a default "
        "-- the receiver's UNKNOWN branch is the safe one and must stay reachable"
    )


def test_publisher_identity_reads_the_service_env(monkeypatch):
    monkeypatch.setenv("SYNDICATE_REFRESH_LANE", "live-odds-worker")
    assert ap._publisher_identity() == "live-odds-worker"
    monkeypatch.delenv("SYNDICATE_REFRESH_LANE", raising=False)
    assert ap._publisher_identity() == ""
