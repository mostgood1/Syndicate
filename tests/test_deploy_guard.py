"""Falsification suite for `.claude/hooks/deploy-guard.py`.

A guard is only worth having if it can be shown to BLOCK the thing it exists to
stop and to ALLOW the thing it must never touch. Both directions are asserted
here, because the predecessor failed each way at least once:

  * it BLOCKED reads -- `sed -n '1,22p' scripts/<entrypoint>.py` was refused as a
    deploy, and so was the edit that would have fixed it, because the pattern was
    a bare substring of the script's own name;
  * it BLOCKED everything -- once the coordinator session was archived, the
    allow-branch (`session_id in coordinator.id`) became unreachable and no
    session could deploy at all.

The hook is executed as a subprocess with a JSON payload on stdin, exactly the
way Claude Code invokes it, so these tests exercise the real entrypoint rather
than imported internals.
"""
from __future__ import annotations

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
SESSION = "test-session-0001"
LANE = "test-lane"

DEPLOY_CMD = "python scripts/render_deploy.py --service web --commit abc1234"


def hook_env(tmp_root: Path, **overrides: str) -> dict:
    """The real environment, minus anything that would pre-empt the guard.

    It must inherit PATH: the render.yaml branch shells out to `git`, and an
    empty PATH makes that raise, which the guard reads as "cannot prove the push
    carries render.yaml" and allows. That is correct behaviour for the guard and
    a silently vacuous test -- the blocking branch never ran at all.
    """
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(tmp_root))
    env.pop("SYNDICATE_DEPLOY_GUARD", None)
    env.update(overrides)
    return env


def run_hook(tmp_root: Path, command: str, session_id: str = SESSION,
             **env_overrides: str) -> subprocess.CompletedProcess:
    payload = {"tool_name": "Bash", "session_id": session_id,
               "tool_input": {"command": command}}
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload).encode("utf-8"),
        capture_output=True,
        env=hook_env(tmp_root, **env_overrides),
        timeout=60,
    )


@pytest.fixture()
def root(tmp_path: Path) -> Path:
    """A throwaway repo root: lane marker set, no claims and no receipts."""
    (tmp_path / ".syndicate").mkdir()
    (tmp_path / ".syndicate" / (".current-lane." + SESSION)).write_text(LANE, encoding="utf-8")
    return tmp_path


def give_claim(root: Path, service: str = "web", holder: str = LANE,
               age_seconds: float = 0.0, ttl: float = 2700.0) -> None:
    d = root / ".syndicate" / "deploy_claims"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{service}.json").write_text(json.dumps(
        {"holder": holder, "acquired_at": time.time() - age_seconds, "ttl_seconds": ttl}),
        encoding="utf-8")


def give_receipt(root: Path, service: str = "web", verdict: str = "CLEAR",
                 age_seconds: float = 0.0) -> None:
    d = root / ".syndicate" / "deploy" / "preflight"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{service}.json").write_text(json.dumps(
        {"service": service, "verdict": verdict, "written_at": time.time() - age_seconds}),
        encoding="utf-8")


# --------------------------------------------------------------------------
# It must ALLOW. These are the false positives that get a guard deleted.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("command", [
    "sed -n '1,22p' scripts/render_deploy.py",
    "cat scripts/render_deploy.py",
    "grep -n 'SERVICE_IDS' scripts/render_deploy.py",
    "wc -l scripts/render_deploy.py",
    "git log --oneline -- scripts/render_deploy.py",
])
def test_reading_the_entrypoint_is_not_a_deploy(root, command):
    """The exact regression that blocked this file's own rewrite."""
    assert run_hook(root, command).returncode == ALLOW


@pytest.mark.parametrize("command", [
    "python scripts/render_events.py --service web",
    "python scripts/render_logs.py --service refresh-worker --limit 50",
    "python scripts/check_deploy_safety.py",
    "curl -s -H \"Authorization: Bearer $K\" https://api.render.com/v1/services/srv-d88ahvrbc2fs73eodu30/deploys",
])
def test_render_api_reads_are_never_blocked(root, command):
    """Read paths hit the API constantly; a guard that blocks them gets disabled."""
    assert run_hook(root, command).returncode == ALLOW


def test_ordinary_push_is_not_a_deploy(root):
    assert run_hook(root, "git push origin main").returncode == ALLOW


# --------------------------------------------------------------------------
# It must BLOCK. Without these the guard is decorative.
# --------------------------------------------------------------------------

def test_deploy_without_any_locks_is_blocked(root):
    result = run_hook(root, DEPLOY_CMD)
    assert result.returncode == BLOCK
    assert b"NOT HELD by anyone" in result.stderr


def test_block_message_names_the_command_that_clears_it(root):
    """Every refusal must be self-serve -- this is the whole point of the redesign."""
    stderr = run_hook(root, DEPLOY_CMD).stderr.decode()
    assert "deploy_claim.py acquire --service web" in stderr
    assert "deploy_preflight.py --service web" in stderr
    assert LANE in stderr


def test_claim_alone_is_not_enough(root):
    give_claim(root)
    result = run_hook(root, DEPLOY_CMD)
    assert result.returncode == BLOCK
    assert b"no preflight has been run" in result.stderr


def test_preflight_alone_is_not_enough(root):
    give_receipt(root)
    assert run_hook(root, DEPLOY_CMD).returncode == BLOCK


def test_foreign_claim_blocks_and_names_the_holder(root):
    give_claim(root, holder="some-other-lane")
    give_receipt(root)
    result = run_hook(root, DEPLOY_CMD)
    assert result.returncode == BLOCK
    assert b"some-other-lane" in result.stderr
    assert b"--force" in result.stderr


def test_expired_claim_does_not_count_as_held(root):
    give_claim(root, age_seconds=3600, ttl=2700)      # 60 min old, 45 min ttl
    give_receipt(root)
    assert run_hook(root, DEPLOY_CMD).returncode == BLOCK


def test_stale_preflight_does_not_count(root):
    give_claim(root)
    give_receipt(root, age_seconds=3600)              # 60 min old, 15 min limit
    result = run_hook(root, DEPLOY_CMD)
    assert result.returncode == BLOCK
    assert b"min old" in result.stderr


def test_hold_verdict_does_not_count_as_clear(root):
    give_claim(root)
    give_receipt(root, verdict="HOLD")
    result = run_hook(root, DEPLOY_CMD)
    assert result.returncode == BLOCK
    assert b"not CLEAR" in result.stderr


def test_corrupt_claim_blocks_rather_than_reading_as_free(root):
    """An unknown must not land on the permissive branch."""
    d = root / ".syndicate" / "deploy_claims"
    d.mkdir(parents=True, exist_ok=True)
    (d / "web.json").write_text("{not json", encoding="utf-8")
    give_receipt(root)
    result = run_hook(root, DEPLOY_CMD)
    assert result.returncode == BLOCK
    assert b"does not parse" in result.stderr


def test_curl_post_to_deploys_endpoint_is_guarded(root):
    cmd = ("curl -X POST -H \"Authorization: Bearer $K\" "
           "https://api.render.com/v1/services/srv-d88ahvrbc2fs73eodu30/deploys")
    assert run_hook(root, cmd).returncode == BLOCK


# --------------------------------------------------------------------------
# Alias handling. `deploy_claim.py` and `deploy_preflight.py` both accept
# `web` and `syndicate` for one service, so a naive lookup lets two sessions
# each hold "the" web lock under a different name.
# --------------------------------------------------------------------------

def test_foreign_claim_under_the_other_alias_still_blocks(root):
    """`syndicate.json` and `web.json` are the SAME service."""
    give_claim(root, service="syndicate", holder="some-other-lane")
    give_receipt(root)
    result = run_hook(root, DEPLOY_CMD)
    assert result.returncode == BLOCK
    assert b"some-other-lane" in result.stderr


def test_receipt_filed_under_the_other_alias_is_found(root):
    give_claim(root)
    give_receipt(root, service="syndicate")
    assert run_hook(root, DEPLOY_CMD).returncode == ALLOW


def test_newest_receipt_wins_not_the_most_permissive(root):
    """A fresh HOLD must revoke an older CLEAR filed under the sibling alias."""
    give_claim(root)
    give_receipt(root, service="syndicate", verdict="CLEAR", age_seconds=300)
    give_receipt(root, service="web", verdict="HOLD", age_seconds=0)
    result = run_hook(root, DEPLOY_CMD)
    assert result.returncode == BLOCK
    assert b"not CLEAR" in result.stderr


# --------------------------------------------------------------------------
# The happy path, and the escape hatches.
# --------------------------------------------------------------------------

def test_claim_plus_fresh_preflight_allows_the_deploy(root):
    give_claim(root)
    give_receipt(root)
    result = run_hook(root, DEPLOY_CMD)
    assert result.returncode == ALLOW
    assert b"DEPLOY GUARD: clear" in result.stderr
    assert b"release --service web" in result.stderr


def test_env_off_switch_stands_the_guard_down(root):
    """Proven against a command that is otherwise BLOCKED -- see the test above."""
    result = run_hook(root, DEPLOY_CMD, SYNDICATE_DEPLOY_GUARD="off")
    assert result.returncode == ALLOW


def test_break_glass_grant_allows_and_announces_itself(root):
    d = root / ".syndicate" / "deploy" / "grants"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{SESSION}.json").write_text(json.dumps(
        {"expires_epoch": time.time() + 600, "service": "web", "note": "testing"}),
        encoding="utf-8")
    result = run_hook(root, DEPLOY_CMD)
    assert result.returncode == ALLOW
    assert b"BREAK-GLASS" in result.stderr


def test_expired_grant_is_not_a_grant(root):
    d = root / ".syndicate" / "deploy" / "grants"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{SESSION}.json").write_text(json.dumps(
        {"expires_epoch": time.time() - 1, "service": "web"}), encoding="utf-8")
    assert run_hook(root, DEPLOY_CMD).returncode == BLOCK


def test_malformed_payload_fails_open(root):
    result = subprocess.run(
        [sys.executable, str(HOOK)], input=b"not json at all",
        capture_output=True, timeout=60, env=hook_env(root),
    )
    assert result.returncode == ALLOW


def test_undeterminable_service_fails_open_loudly(root):
    """Ignorance allows -- but never silently."""
    cmd = ("curl -X POST -H \"Authorization: Bearer $K\" "
           "https://api.render.com/v1/services/srv-unknown999/deploys")
    result = run_hook(root, cmd)
    assert result.returncode == ALLOW
    assert b"could not determine the target service" in result.stderr


# --------------------------------------------------------------------------
# The render.yaml push branch, in a throwaway git repo.
#
# Ported from `.claude/hooks/test_deploy_guard_render_yaml.py`, which was
# deleted with the coordinator role it tested. Its point survives the redesign
# and is worth keeping: proving only the ALLOW direction of this branch ("a
# push with no render.yaml") is indistinguishable from the branch never running.
# `blueprint_sync` is the incident this path exists for.
# --------------------------------------------------------------------------

@pytest.fixture()
def git_root(tmp_path: Path) -> Path:
    def git(*args):
        return subprocess.run(["git", *args], cwd=tmp_path, capture_output=True, text=True)

    git("init", "-q")
    git("config", "user.email", "t@t")
    git("config", "user.name", "t")
    (tmp_path / ".syndicate").mkdir()
    (tmp_path / ".syndicate" / (".current-lane." + SESSION)).write_text(LANE, encoding="utf-8")

    (tmp_path / "app.py").write_text("x = 1\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-qm", "base")
    base = git("rev-parse", "HEAD").stdout.strip()
    git("update-ref", "refs/remotes/origin/main", base)
    return tmp_path


def _commit(root: Path, name: str, body: str) -> None:
    (root / name).write_text(body, encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True)
    subprocess.run(["git", "commit", "-qm", name], cwd=root, capture_output=True)


def test_push_of_code_only_is_allowed(git_root):
    _commit(git_root, "app.py", "x = 2\n")
    assert run_hook(git_root, "git push origin main").returncode == ALLOW


def test_push_carrying_render_yaml_is_blocked(git_root):
    _commit(git_root, "render.yaml", "services:\n  - name: web\n")
    result = run_hook(git_root, "git push origin main")
    assert result.returncode == BLOCK
    assert b"blueprint_sync" in result.stderr


def test_render_yaml_push_requires_all_three_services(git_root):
    """blueprint_sync rewrites env on EVERY service, so one lock is not enough."""
    _commit(git_root, "render.yaml", "services:\n  - name: web\n")
    give_claim(git_root, service="web")
    give_receipt(git_root, service="web")
    result = run_hook(git_root, "git push origin main")
    assert result.returncode == BLOCK
    stderr = result.stderr.decode()
    assert "refresh-worker" in stderr and "live-odds-worker" in stderr


def test_render_yaml_push_allowed_when_all_three_are_locked(git_root):
    _commit(git_root, "render.yaml", "services:\n  - name: web\n")
    for service in ("web", "refresh-worker", "live-odds-worker"):
        give_claim(git_root, service=service)
        give_receipt(git_root, service=service)
    assert run_hook(git_root, "git push origin main").returncode == ALLOW
