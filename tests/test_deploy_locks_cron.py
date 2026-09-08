"""Cron services in the deploy locks. `#647`.

WHY IT EXISTS. The three cron services were created 2026-09-07, after the lock
tooling was written, and fell straight through every part of it:

  * `deploy_claim.py acquire --service ci-suite` was rejected by argparse
    `choices` -- a cron deploy could not be serialised at all;
  * `deploy_preflight.py` had no id for it;
  * `deploy-guard.py`'s `DEPLOYS_ENDPOINT` regex DID match
    `/v1/services/crn-.../deploys`, but `SRV_ID` matched only `srv-`, so
    `_target_services()` returned `()` and the guard took its "ignorance, not a
    readable no" branch: **ALLOWED UNCHECKED, while printing advice to take a
    lock that the claim tool then refused.**

THE NAIVE FIX WOULD HAVE BEEN WORSE THAN THE GAP, and that is the thing most
worth pinning here. `deploy_preflight`'s central question -- "is something
running that a deploy would kill" -- is answered from an `ALL_PROCESS_MEMORY`
log sample, and a cron emits none: it has no resident process, only a container
that exists for the length of a run. Measured 2026-09-08 across one 3h window
containing a live 40-minute `ci-suite` run: cron lines 0, refresh-worker 20.
Rule 1 of that file is "unknown is not clear", so adding the ids alone would
have made `stale` permanently True and every cron preflight UNKNOWN forever. A
gate that can never clear gets removed, and then the crons are unguarded again
with the tooling now claiming to cover them.

`cron_run_in_flight()` therefore answers the SAME question from the evidence a
cron does produce: `cron_job_run_started` / `cron_job_run_ended`, paired by
`cronJobRunId`.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK = REPO_ROOT / ".claude" / "hooks" / "deploy-guard.py"

ALLOW, BLOCK = 0, 2
SESSION = "test-session-cron-0001"
LANE = "test-lane-cron"

CRON_NAMES = ("sim-input-reports", "ci-suite", "mlb-season-artifacts")
CI_SUITE_ID = "crn-dafg4h0u01pc73aavs6g"


def _load(name: str, relpath: str):
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / relpath)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except SystemExit:
        # `deploy-guard.py` is a hook script whose module body ends in
        # `sys.exit(main())`. Every constant is defined above that line, so the
        # namespace is complete when it fires; the tests below read tables, not
        # behaviour (behaviour is exercised through the real entrypoint).
        pass
    return mod


@pytest.fixture(scope="module")
def preflight():
    return _load("deploy_preflight", "scripts/deploy_preflight.py")


@pytest.fixture(scope="module")
def claim_tool():
    return _load("deploy_claim", "scripts/deploy_claim.py")


# --------------------------------------------------------------------------
# cron_run_in_flight -- the check that replaces the process sample
# --------------------------------------------------------------------------

def _events(*rows: tuple[str, str, str]) -> list[dict]:
    """Render's shape: [{"event": {"type", "timestamp", "details": {...}}}]."""
    return [{"event": {"type": kind, "timestamp": stamp,
                       "details": {"cronJobRunId": run_id}}}
            for kind, stamp, run_id in rows]


def test_a_started_run_with_no_end_is_in_flight(preflight, monkeypatch):
    monkeypatch.setattr(preflight, "_get", lambda url, key: _events(
        ("cron_job_run_started", "2026-09-08T16:43:39Z", "run-2"),
        ("cron_job_run_ended", "2026-09-08T07:01:56Z", "run-1"),
        ("cron_job_run_started", "2026-09-08T07:00:13Z", "run-1"),
    ))
    state, detail = preflight.cron_run_in_flight(CI_SUITE_ID, "k")

    assert state is True
    assert detail["newest_run"]["id"] == "run-2"


def test_a_completed_run_is_not_in_flight(preflight, monkeypatch):
    monkeypatch.setattr(preflight, "_get", lambda url, key: _events(
        ("cron_job_run_ended", "2026-09-08T07:01:56Z", "run-1"),
        ("cron_job_run_started", "2026-09-08T07:00:13Z", "run-1"),
    ))
    state, _ = preflight.cron_run_in_flight(CI_SUITE_ID, "k")

    assert state is False


def test_the_newest_run_is_chosen_by_timestamp_not_position(preflight, monkeypatch):
    """Rule 3 of `deploy_preflight`, applied to a second endpoint.

    The logs API returns newest-N presented OLDEST-first, and reading `rows[0]`
    as the newest once produced a four-hour error in exactly the direction that
    says "safe to deploy". The events endpoint has looked newest-first every
    time -- which is precisely why it must not be depended on. Here the IN
    FLIGHT run is deliberately LAST in the list.
    """
    monkeypatch.setattr(preflight, "_get", lambda url, key: _events(
        ("cron_job_run_started", "2026-09-01T00:00:00Z", "old"),
        ("cron_job_run_ended", "2026-09-01T00:05:00Z", "old"),
        ("cron_job_run_started", "2026-09-08T16:43:39Z", "newest"),
    ))
    state, detail = preflight.cron_run_in_flight(CI_SUITE_ID, "k")

    assert state is True
    assert detail["newest_run"]["id"] == "newest"


def test_truncation_between_started_and_ended_refuses(preflight, monkeypatch):
    """If the window cuts off the `ended`, report IN FLIGHT.

    A wrong refusal costs a wait; a wrong clearance kills a run. The asymmetry
    decides the direction.
    """
    monkeypatch.setattr(preflight, "_get", lambda url, key: _events(
        ("cron_job_run_started", "2026-09-08T16:43:39Z", "run-9"),
    ))
    state, _ = preflight.cron_run_in_flight(CI_SUITE_ID, "k")

    assert state is True


@pytest.mark.parametrize("payload,label", [
    ([], "empty list"),
    (None, "not a list"),
    ([{"event": {"type": "build_ended", "timestamp": "2026-09-08T16:14:56Z", "details": {}}}],
     "build events only, no run events"),
])
def test_an_unreadable_history_is_none_not_false(preflight, monkeypatch, payload, label):
    """UNKNOWN, never CLEAR. This is rule 1 and it is the whole point.

    `False` here would mean "no run in flight" and clear the deploy on evidence
    that was never obtained.
    """
    monkeypatch.setattr(preflight, "_get", lambda url, key: payload)
    state, detail = preflight.cron_run_in_flight(CI_SUITE_ID, "k")

    assert state is None, label
    assert detail.get("error"), label


def test_an_api_failure_is_none_not_false(preflight, monkeypatch):
    def boom(url, key):
        raise RuntimeError("429 from Render")

    monkeypatch.setattr(preflight, "_get", boom)
    state, detail = preflight.cron_run_in_flight(CI_SUITE_ID, "k")

    assert state is None
    assert "RuntimeError" in detail["error"]


# --------------------------------------------------------------------------
# The lookup tables
# --------------------------------------------------------------------------

@pytest.mark.parametrize("name", CRON_NAMES)
def test_preflight_knows_every_cron(preflight, name):
    assert name in preflight.SERVICE_IDS
    assert preflight.SERVICE_IDS[name].startswith("crn-")
    assert name in preflight.CRON_SERVICES


def test_the_long_running_services_are_not_marked_as_crons(preflight):
    """The discrimination that keeps the process-sample path intact for them."""
    for name in ("web", "syndicate", "refresh-worker", "live-odds-worker"):
        assert name not in preflight.CRON_SERVICES
        assert preflight.SERVICE_IDS[name].startswith("srv-")


def test_the_fleet_report_stays_the_three_long_running_services(preflight):
    """`FLEET` answers a drift question about the always-on services.

    Crons are in `SERVICE_IDS` so they can be targeted; adding them to `FLEET`
    would put three rows nobody asked about into every preflight receipt.
    """
    assert preflight.FLEET == ("web", "refresh-worker", "live-odds-worker")


@pytest.mark.parametrize("name", CRON_NAMES)
def test_a_cron_can_be_claimed(claim_tool, name):
    """The argparse `choices` rejection that started this."""
    assert name in claim_tool.SERVICES
    assert name in claim_tool.CANONICAL_SERVICES
    assert claim_tool.canonical(name) == name


def test_crons_do_not_share_a_lock_with_each_other_or_with_web(claim_tool):
    canon = {name: claim_tool.canonical(name) for name in CRON_NAMES}
    assert len(set(canon.values())) == len(CRON_NAMES)
    assert claim_tool.canonical("web") not in canon.values()


def test_web_alias_collapse_still_holds(claim_tool):
    """`#635` must survive this change: web and syndicate are ONE lock."""
    assert claim_tool.canonical("syndicate") == claim_tool.canonical("web") == "web"


# --------------------------------------------------------------------------
# The guard, exercised as the real entrypoint
# --------------------------------------------------------------------------

def _hook_env(root: Path) -> dict:
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root))
    env.pop("SYNDICATE_DEPLOY_GUARD", None)
    return env


def _run_hook(root: Path, command: str) -> subprocess.CompletedProcess:
    payload = {"tool_name": "Bash", "session_id": SESSION,
               "tool_input": {"command": command}}
    return subprocess.run([sys.executable, str(HOOK)],
                          input=json.dumps(payload).encode("utf-8"),
                          capture_output=True, env=_hook_env(root), timeout=60)


@pytest.fixture()
def root(tmp_path: Path) -> Path:
    (tmp_path / ".syndicate").mkdir()
    (tmp_path / ".syndicate" / (".current-lane." + SESSION)).write_text(LANE, encoding="utf-8")
    return tmp_path


def _give_claim(root: Path, service: str, holder: str = LANE) -> None:
    d = root / ".syndicate" / "deploy_claims"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{service}.json").write_text(json.dumps(
        {"holder": holder, "acquired_at": time.time(), "ttl_seconds": 2700.0}), encoding="utf-8")


def _give_receipt(root: Path, service: str) -> None:
    d = root / ".syndicate" / "deploy" / "preflight"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{service}.json").write_text(json.dumps(
        {"service": service, "verdict": "CLEAR", "written_at": time.time()}), encoding="utf-8")


CRON_DEPLOY = f'curl -X POST https://api.render.com/v1/services/{CI_SUITE_ID}/deploys -d "{{}}"'


def test_an_unclaimed_cron_deploy_is_BLOCKED(root):
    """The regression itself. This returned 0 with "ALLOWED unchecked"."""
    result = _run_hook(root, CRON_DEPLOY)
    stderr = result.stderr.decode("utf-8", "replace")

    assert result.returncode == BLOCK
    assert "ci-suite" in stderr
    assert "ALLOWED unchecked" not in stderr


def test_the_guard_resolves_the_cron_by_NAME_in_its_remedy(root):
    """The old message named no service, so its advice could not be followed."""
    stderr = _run_hook(root, CRON_DEPLOY).stderr.decode("utf-8", "replace")

    assert "--service ci-suite" in stderr


def test_a_claimed_and_preflighted_cron_deploy_is_ALLOWED(root):
    _give_claim(root, "ci-suite")
    _give_receipt(root, "ci-suite")

    result = _run_hook(root, CRON_DEPLOY)

    assert result.returncode == ALLOW


def test_a_claim_on_a_DIFFERENT_cron_does_not_unlock_this_one(root):
    """Each cron is its own service; one claim must not cover the set."""
    _give_claim(root, "sim-input-reports")
    _give_receipt(root, "sim-input-reports")

    result = _run_hook(root, CRON_DEPLOY)

    assert result.returncode == BLOCK


def test_a_peers_claim_on_a_cron_blocks(root):
    _give_claim(root, "ci-suite", holder="someone-else")
    _give_receipt(root, "ci-suite")

    result = _run_hook(root, CRON_DEPLOY)
    stderr = result.stderr.decode("utf-8", "replace")

    assert result.returncode == BLOCK
    assert "someone-else" in stderr


def test_reading_a_cron_id_is_not_a_deploy(root):
    """The false-positive direction, which is what gets a guard deleted."""
    for command in (
        f"curl -s https://api.render.com/v1/services/{CI_SUITE_ID}/deploys?limit=1",
        f"grep -n {CI_SUITE_ID} scripts/deploy_preflight.py",
        f"echo {CI_SUITE_ID}",
    ):
        assert _run_hook(root, command).returncode == ALLOW, command


def test_a_render_yaml_push_does_not_demand_cron_claims():
    """Crons are not in `render.yaml`, so `blueprint_sync` cannot reach them.

    Dragging them into that blast radius would demand three claims nobody needs
    and teach people to `--force`, which is how a lock stops meaning anything.
    """
    guard = _load("deploy_guard_mod", ".claude/hooks/deploy-guard.py")

    assert guard.ALL_SERVICES == ("web", "refresh-worker", "live-odds-worker")
    for name in CRON_NAMES:
        assert name not in guard.ALL_SERVICES
        assert name in guard.ALIASES


def test_the_guard_maps_every_cron_id_to_its_name():
    guard = _load("deploy_guard_mod2", ".claude/hooks/deploy-guard.py")

    ids = [sid for sid, name in guard.SERVICE_BY_ID.items() if name in CRON_NAMES]
    assert len(ids) == len(CRON_NAMES)
    for sid in ids:
        assert guard.SRV_ID.search(f"deploy {sid} now"), sid
