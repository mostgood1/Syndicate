"""Tests for the deploy claim -- one deployer per service.

Every case here is a failure that actually happened on 2026-08-15, not a
hypothetical: a peer cancelled an in-flight build, a verified fix was silently
reverted 8 minutes after going live, and three sessions archived mid-
coordination while holding work.

The load-bearing assertions are the two that make the claim safe to rely on:
a foreign holder BLOCKS, and a dead holder EXPIRES. Get the first wrong and the
claim is decoration; get the second wrong and one archived session wedges a
service until someone notices.
"""

from __future__ import annotations

import importlib
import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
deploy_claim = importlib.import_module("deploy_claim")


@pytest.fixture(autouse=True)
def _isolated_claim_dir(tmp_path, monkeypatch):
    """Never touch the real .syndicate/deploy_claims during tests."""
    monkeypatch.setattr(deploy_claim, "CLAIM_DIR", tmp_path / "deploy_claims")
    yield


def _acquire(service="web", holder="lane-A", **kw):
    argv = ["acquire", "--service", service, "--holder", holder]
    for k, v in kw.items():
        argv += [f"--{k.replace('_', '-')}", str(v)]
    return deploy_claim.main(argv)


def test_acquire_then_a_second_session_is_refused():
    assert _acquire(holder="lane-A") == 0
    # The whole point: lane-B must not be able to take it by asking again.
    assert _acquire(holder="lane-B") == 1
    assert deploy_claim.active_claim("web")["holder"] == "lane-A"


def test_active_claim_is_none_when_free():
    assert deploy_claim.active_claim("web") is None


def test_expired_claim_does_not_block():
    """A session that archives while holding must not wedge the service."""
    assert _acquire(holder="dead-session", ttl=1) == 0
    time.sleep(1.2)
    assert deploy_claim.active_claim("web") is None, "an expired claim must not block"
    # ...and the next session can take it without --force.
    assert _acquire(holder="live-session") == 0
    assert deploy_claim.active_claim("web")["holder"] == "live-session"


def test_force_records_who_broke_the_claim():
    """Breaking a peer's live claim is allowed but must never be anonymous."""
    _acquire(holder="lane-A")

    # Without --force, a live claim is refused outright.
    assert _acquire(holder="lane-B") == 1
    assert deploy_claim.active_claim("web")["holder"] == "lane-A"

    # With --force it succeeds AND records whose claim was broken, so the
    # next reader can tell a handover from a land-grab.
    assert deploy_claim.main(
        ["acquire", "--service", "web", "--holder", "lane-C", "--force"]
    ) == 0
    claim = deploy_claim.active_claim("web")
    assert claim["holder"] == "lane-C"
    assert claim["replaced"]["holder"] == "lane-A"


def test_release_requires_the_token():
    deploy_claim.main(["acquire", "--service", "web", "--holder", "lane-A"])
    token = json.loads((deploy_claim.CLAIM_DIR / "web.json").read_text())["token"]

    assert deploy_claim.main(["release", "--service", "web", "--token", "wrong"]) == 1
    assert deploy_claim.active_claim("web") is not None, "a bad token must not release"

    assert deploy_claim.main(["release", "--service", "web", "--token", token]) == 0
    assert deploy_claim.active_claim("web") is None


def test_release_of_a_free_service_is_not_an_error():
    assert deploy_claim.main(["release", "--service", "web", "--force"]) == 0


def test_corrupt_claim_surfaces_rather_than_reading_as_free():
    """A truncated write must not silently mean 'go ahead and deploy'."""
    deploy_claim.CLAIM_DIR.mkdir(parents=True, exist_ok=True)
    (deploy_claim.CLAIM_DIR / "web.json").write_text("{not json", encoding="utf-8")
    claim = deploy_claim._read("web")
    assert claim is not None and claim.get("corrupt") is True
