"""deploy-guard on FLEET deploys `[2026-10-25, lane deploy-guard-fleet]`.

Render is suspended; production deploys are an ff of the fleet checkout,
`local_production.py reload-web`, and a TERM the supervisor respawns. Each must
need the lane's claim + a fresh CLEAR preflight, and the ledger text that QUOTES
those commands must never be blocked. The hook runs as a subprocess, exactly as
Claude Code invokes it (same harness as test_deploy_guard.py).
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
SESSION = "test-session-fleet"
LANE = "test-lane"
SHA = "b2cdb6ed6"

PS_TABLE = """1826652 /home/amyn/.venvs/syndicate/bin/python scripts/local_production.py --home /home/amyn/syndicate-prod up
1826667 /home/amyn/.venvs/syndicate/bin/python -m gunicorn wsgi:application --bind 127.0.0.1:10000
1826730 /home/amyn/.venvs/syndicate/bin/python scripts/run_refresh_worker.py
1826731 /home/amyn/.venvs/syndicate/bin/python scripts/run_live_odds_refresh_worker.py
1842841 /home/amyn/.venvs/syndicate/bin/python /home/amyn/Syndicate/scripts/run_refresh_odds_job.py --manifest-path x
"""


@pytest.fixture()
def root(tmp_path: Path) -> Path:
    (tmp_path / ".syndicate").mkdir()
    (tmp_path / ".syndicate" / (".current-lane." + SESSION)).write_text(LANE, encoding="utf-8")
    (tmp_path / "ps.txt").write_text(PS_TABLE, encoding="utf-8")
    return tmp_path


def run_hook(root: Path, command: str) -> subprocess.CompletedProcess:
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root),
               SYNDICATE_FLEET_PS_FIXTURE=str(root / "ps.txt"))
    env.pop("SYNDICATE_DEPLOY_GUARD", None)
    payload = {"tool_name": "Bash", "session_id": SESSION, "tool_input": {"command": command}}
    return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload).encode("utf-8"),
                          capture_output=True, env=env, timeout=60)


def give_claim(root: Path, service: str, holder: str = LANE) -> None:
    d = root / ".syndicate" / "deploy_claims"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{service}.json").write_text(json.dumps(
        {"holder": holder, "acquired_at": time.time(), "ttl_seconds": 2700}), encoding="utf-8")


def give_receipt(root: Path, service: str, verdict: str = "CLEAR", target_commit: str | None = SHA) -> None:
    d = root / ".syndicate" / "deploy" / "preflight"
    d.mkdir(parents=True, exist_ok=True)
    payload = {"service": service, "verdict": verdict, "written_at": time.time()}
    if target_commit:
        payload["target_commit"] = target_commit
    (d / f"{service}.json").write_text(json.dumps(payload), encoding="utf-8")


FF = f"wsl -- bash -lc 'cd ~/Syndicate && git merge --ff-only {SHA}'"
RELOAD = ("wsl -- bash -lc 'cd ~/Syndicate && ~/.venvs/syndicate/bin/python scripts/local_production.py "
          "--home ~/syndicate-prod reload-web'")
TERM_REFRESH = "wsl -- kill -TERM 1826730"


# ---- BLOCK without the locks ------------------------------------------------

@pytest.mark.parametrize("command", [
    FF,
    f"git -C /home/amyn/Syndicate merge --ff-only {SHA}",
    f"wsl -- bash -lc 'cd ~/Syndicate && git reset --hard {SHA}'",
    RELOAD,
    TERM_REFRESH,
    "wsl -- bash -lc 'pkill -TERM -f run_refresh_worker.py'",
    "wsl -- bash -lc 'kill -HUP $(pgrep -f \"gunicorn wsgi:application\" | head -1)'",
    "wsl -- bash -lc '~/.venvs/syndicate/bin/python scripts/local_production.py --home ~/syndicate-prod down'",
])
def test_fleet_deploys_without_locks_are_blocked(root, command):
    result = run_hook(root, command)
    assert result.returncode == BLOCK, result.stderr.decode()
    assert b"FLEET deploy" in result.stderr


def test_a_term_resolves_the_pid_to_its_role(root):
    err = run_hook(root, TERM_REFRESH).stderr.decode()
    assert "refresh-worker" in err and "deploy_claim.py acquire --service refresh-worker" in err


def test_an_ff_to_a_ref_is_refused_even_with_locks(root):
    give_claim(root, "web")
    give_receipt(root, "web")
    result = run_hook(root, "wsl -- bash -lc 'cd ~/Syndicate && git merge --ff-only github/main'")
    assert result.returncode == BLOCK
    assert b"EXACT SHA" in result.stderr


# ---- ALLOW with the locks ---------------------------------------------------

def test_an_ff_with_a_claim_and_a_receipt_for_that_sha_is_allowed(root):
    give_claim(root, "web")
    give_receipt(root, "web")
    assert run_hook(root, FF).returncode == ALLOW


def test_an_ff_receipt_for_another_sha_is_refused(root):
    give_claim(root, "web")
    give_receipt(root, "web", target_commit="5f32d9c4")
    result = run_hook(root, FF)
    assert result.returncode == BLOCK
    assert b"5f32d9c4" in result.stderr


def test_an_ff_on_any_held_fleet_service_counts(root):
    give_claim(root, "refresh-worker")
    give_receipt(root, "refresh-worker")
    assert run_hook(root, FF).returncode == ALLOW


def test_reload_web_needs_the_web_locks(root):
    give_claim(root, "web")
    assert run_hook(root, RELOAD).returncode == BLOCK
    give_receipt(root, "web")
    assert run_hook(root, RELOAD).returncode == ALLOW


def test_a_held_web_claim_does_not_cover_a_refresh_worker_term(root):
    give_claim(root, "web")
    give_receipt(root, "web")
    assert run_hook(root, TERM_REFRESH).returncode == BLOCK


def test_a_hold_receipt_does_not_count(root):
    give_claim(root, "web")
    give_receipt(root, "web", verdict="HOLD")
    assert run_hook(root, RELOAD).returncode == BLOCK


def test_a_peers_claim_blocks(root):
    give_claim(root, "web", holder="someone-else")
    give_receipt(root, "web")
    result = run_hook(root, RELOAD)
    assert result.returncode == BLOCK
    assert b"someone-else" in result.stderr


def test_an_ff_script_file_is_guarded(root):
    script = root / "ff.sh"
    script.write_text(f"cd ~/Syndicate\ngit merge --ff-only {SHA}\n", encoding="utf-8")
    assert run_hook(root, f"bash {script.as_posix()}").returncode == BLOCK


# ---- ALLOW always: reads, the ledger, non-role kills ------------------------

@pytest.mark.parametrize("command", [
    "wsl -- bash -lc 'cd ~/Syndicate && git rev-parse --short HEAD && git status --porcelain'",
    "wsl -- bash -lc 'cd ~/Syndicate && git fetch -q github && git merge-base --is-ancestor HEAD b2cdb6ed'",
    "wsl -- bash -lc 'cd ~/Syndicate && git log --oneline HEAD..b2cdb6ed'",
    "wsl -- bash -lc 'cd ~/Syndicate && git checkout -- engines/mlb/data/x.json'",
    "wsl -- bash -lc 'cd ~/Syndicate && git reset -q'",
    "wsl -- bash -lc '~/.venvs/syndicate/bin/python scripts/local_production.py --home ~/syndicate-prod status --lines 0'",
    "grep -n 'local_production.py reload-web' .syndicate/deploys.md",
    "grep -n \"git merge --ff-only\" ~/Syndicate/.syndicate/deploys.md",
    "wsl -- kill -TERM 1842841",
    "wsl -- kill -0 1826730",
    "kill 1826730",
    "wsl -- bash -lc 'ps -eo pid=,args= | grep run_refresh_worker'",
    "cat >> .syndicate/deploys.md <<'EOF'\n- **deploy:** `cd ~/Syndicate && git merge --ff-only 9260ea0b` at 18:56:50Z, "
    "`local_production.py reload-web` 2.6 s; refresh-worker `kill -TERM 1826730`\nEOF",
    "git commit -q -m \"deploys: fleet ff ~/Syndicate git merge --ff-only b2cdb6ed + local_production.py reload-web\"",
    "git commit -q -F - <<'EOF'\nfleet: cd ~/Syndicate && git merge --ff-only b2cdb6ed6; kill -TERM run_refresh_worker\nEOF",
])
def test_reads_ledger_text_and_non_role_kills_are_allowed(root, command):
    result = run_hook(root, command)
    assert result.returncode == ALLOW, result.stderr.decode()


# Shapes found by the transcript sweep run before enabling (2026-10-25).
@pytest.mark.parametrize("command", [
    # another worktree's ff sharing a command with a later fleet read
    "cd /c/tmp/ledger-1002 && git merge --ff-only origin/main -q && "
    "wsl -- bash -lc 'cd ~/Syndicate && git rev-parse --short HEAD'",
    # `\\|` inside a grep pattern is not a pipe into `kill`
    "grep -n 'restart.*refresh-worker\\|kill.*refresh\\|supervis.*restart' docs/ai_context/local_production_runbook.md",
    # a heredoc fed to PYTHON is python; its string literals are not commands
    "py -3 - <<'EOF'\nreps = ['cd ~/Syndicate && git merge --ff-only abc1234', 'local_production.py reload-web']\nEOF",
])
def test_sweep_false_positives_stay_allowed(root, command):
    result = run_hook(root, command)
    assert result.returncode == ALLOW, result.stderr.decode()


def test_a_python_file_holding_fleet_commands_as_strings_is_not_a_deploy(root):
    script = root / "proof.py"
    script.write_text(f"CASES = [\"cd ~/Syndicate && git merge --ff-only {SHA}\", "
                      "\"python scripts/local_production.py reload-web\"]\n", encoding="utf-8")
    assert run_hook(root, f"py -3 {script.as_posix()}").returncode == ALLOW


def test_a_redirect_after_the_sha_is_not_read_as_the_ref(root):
    give_claim(root, "web")
    give_receipt(root, "web")
    command = f"wsl -- bash -lc 'cd ~/Syndicate && git merge --ff-only {SHA} 2>&1 | tail -3'"
    assert run_hook(root, command).returncode == ALLOW


def test_wsl_cd_flag_then_cd_in_the_body_is_the_fleet(root):
    command = (f"MSYS_NO_PATHCONV=1 wsl --cd /home/amyn -- bash -c "
               f"\"cd /home/amyn/Syndicate && git merge --ff-only {SHA} 2>&1 | tail -1\"")
    assert run_hook(root, command).returncode == BLOCK


# ---- GAPS closed 2026-10-25 (lane deploy-guard-fleet-gaps), real shapes -----

def _mnt(path: Path) -> str:
    """`C:\\x\\y` -> `/mnt/c/x/y`, the WSL spelling of a Windows file."""
    posix = path.resolve().as_posix()
    return f"/mnt/{posix[0].lower()}{posix[2:]}" if posix[1:2] == ":" else posix


def test_a_git_command_built_from_a_variable_is_guarded(root):
    # 2026-10-17, session 9e18a0e7 -- ran unchecked before this lane
    command = ("MSYS_NO_PATHCONV=1 wsl -d Ubuntu-24.04 --cd ~ -- bash -lc 'G=\"git -C /home/amyn/Syndicate\"; "
               "h=$($G rev-parse --short=8 HEAD); [ \"$h\" = \"5d277bcc\" ] && $G merge --ff-only 24e00269 "
               ">/dev/null && echo done'")
    result = run_hook(root, command)
    assert result.returncode == BLOCK, result.stderr.decode()
    assert b"24e00269" in result.stderr


def test_a_variable_built_git_in_another_worktree_stays_allowed(root):
    command = "D=/c/tmp/syndicate-sessions/x; cd $D && git merge --ff-only -q origin/main"
    assert run_hook(root, command).returncode == ALLOW


def test_a_printf_built_script_run_under_another_spelling_is_guarded(root):
    # 2026-10-16: written as C:/.../web_ff16.sh, run as /mnt/c/.../web_ff16.sh
    target = root / "web_ff16.sh"
    command = (
        "printf '%s\\n' 'cd /home/amyn/Syndicate' "
        "'[ \"$(git rev-parse --short=8 HEAD)\" = \"6087b5e2\" ] || { echo \"HEAD moved\"; exit 3; }' "
        "'git merge --ff-only 652f6589 2>&1 | tail -1' "
        f"> \"{target.as_posix()}\" && cd /c && MSYS_NO_PATHCONV=1 wsl --cd /home/amyn -- bash {_mnt(target)}")
    result = run_hook(root, command)
    assert result.returncode == BLOCK, result.stderr.decode()
    assert b"652f6589" in result.stderr
    give_claim(root, "web")
    give_receipt(root, "web", target_commit="652f6589")
    assert run_hook(root, command).returncode == ALLOW


def test_a_script_copied_to_wsl_tmp_then_run_is_read_from_its_source(root):
    # 2026-10-24, this lane's own web deploy: `tr < /mnt/c/.../ff.sh > /tmp/x.sh && bash /tmp/x.sh`
    source = root / "ff_reload_web.sh"
    source.write_text(f"TARGET={SHA}\ncd ~/Syndicate || exit 10\ngit merge --ff-only \"$TARGET\" || exit 14\n"
                      "~/.venvs/syndicate/bin/python scripts/local_production.py --home ~/syndicate-prod reload-web\n",
                      encoding="utf-8")
    command = (f"wsl -- bash -lc 'tr -d \"\\r\" < {_mnt(source)} > /tmp/ff_reload_web_l2i.sh "
               "&& bash /tmp/ff_reload_web_l2i.sh'")
    result = run_hook(root, command)
    assert result.returncode == BLOCK, result.stderr.decode()
    assert SHA.encode() in result.stderr and b"reload-web" in result.stderr
    give_claim(root, "web")
    give_receipt(root, "web")
    assert run_hook(root, command).returncode == ALLOW


def test_a_scripts_positional_sha_is_bound_from_the_command(root):
    # 9e18a0e7's ff_reload.sh: `FROM=$1; TO=$2 ... git merge --ff-only "$TO"`, run 58 times
    script = root / "ff_reload.sh"
    script.write_text("set -u\nFROM=$1; TO=$2\ncd ~/Syndicate || exit 3\n"
                      "git merge --ff-only \"$TO\" >/dev/null || exit 5\n"
                      "~/.venvs/syndicate/bin/python scripts/local_production.py reload-web\n", encoding="utf-8")
    command = f"wsl -- bash {_mnt(script)} 6954cb0e 5e734fb6 2>&1 | tail -5"
    result = run_hook(root, command)
    assert result.returncode == BLOCK and b"5e734fb6" in result.stderr, result.stderr.decode()
    give_claim(root, "web")
    give_receipt(root, "web", target_commit="6954cb0e")        # the FROM, not the TO
    assert run_hook(root, command).returncode == BLOCK
    give_receipt(root, "web", target_commit="5e734fb6")
    assert run_hook(root, command).returncode == ALLOW


def test_a_redirect_after_the_script_is_not_an_argument(root):
    script = root / "deploy_gated.sh"
    script.write_text("TO=${1:?target sha}\ncd ~/Syndicate && git merge --ff-only \"$TO\"\n", encoding="utf-8")
    result = run_hook(root, f"wsl -- bash -l {_mnt(script)} 2>&1 | tail -3")
    assert result.returncode == BLOCK
    assert b"git merge 2`" not in result.stderr and b"not resolvable" in result.stderr, result.stderr.decode()


def test_a_commit_message_naming_a_deploy_script_is_not_a_run(root):
    script = root / "ff_reload.sh"
    script.write_text(f"cd ~/Syndicate && git merge --ff-only {SHA}\n", encoding="utf-8")
    command = f"git commit -q -m \"deploys: ran bash {_mnt(script)} {SHA} on the fleet\""
    assert run_hook(root, command).returncode == ALLOW


def test_an_unresolvable_ref_is_still_gated_without_sha_binding(root):
    script = root / "ff_env.sh"
    script.write_text("cd ~/Syndicate && git merge --ff-only \"$DEPLOY_SHA\"\n", encoding="utf-8")
    command = f"wsl -- bash {_mnt(script)}"
    result = run_hook(root, command)
    assert result.returncode == BLOCK and b"not resolvable" in result.stderr, result.stderr.decode()
    give_claim(root, "web")
    give_receipt(root, "web", target_commit="0123abcd")
    assert run_hook(root, command).returncode == ALLOW


def test_a_heredoc_written_script_then_run_is_guarded(root):
    command = (f"cat > /tmp/ff_x.sh <<'EOF'\ncd ~/Syndicate && git merge --ff-only {SHA}\nEOF\n"
               "wsl -- bash /tmp/ff_x.sh")
    assert run_hook(root, command).returncode == BLOCK


def test_a_produced_script_with_only_reads_stays_allowed(root):
    command = ("printf '%s\\n' 'cd /home/amyn/Syndicate' 'git log --oneline -3' > /tmp/rd.sh "
               "&& wsl -- bash /tmp/rd.sh")
    assert run_hook(root, command).returncode == ALLOW


def test_a_heredoc_fed_to_bash_is_executed_and_guarded(root):
    command = f"wsl -- bash -s <<'EOF'\ncd ~/Syndicate && git merge --ff-only {SHA}\nEOF"
    assert run_hook(root, command).returncode == BLOCK


def test_the_off_switch_still_works(root):
    env_cmd = FF
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root), SYNDICATE_DEPLOY_GUARD="off")
    payload = {"tool_name": "Bash", "session_id": SESSION, "tool_input": {"command": env_cmd}}
    result = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload).encode(),
                            capture_output=True, env=env, timeout=60)
    assert result.returncode == ALLOW
