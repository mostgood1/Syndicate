"""A deploy claim must identify its holder by SESSION, never by a dead pid.

WHY THIS TEST EXISTS. `deploy_claim.py` used to record `"pid": os.getpid()` --
the pid of the short-lived `deploy_claim.py acquire` CLI process, which exits
about a second after writing the claim. Every claim therefore read as "held by a
dead process" within seconds of being taken, and the documented `--force`
liveness check ("verify the holder is gone") could only ever return "gone".

Measured 2026-09-01: a live claim with 15 minutes of TTL remaining was
force-broken by another session whose check was CORRECT -- `Get-Process 22884`
really did report dead. The field lied, not the checker. That turns `--force`
from an escape hatch into the default outcome, which defeats the lock.

The load-bearing assertion is `"pid" not in claim`. A test that only checked for
`holder_session` would pass while the misleading field sat right beside it.
"""

# THE SANDBOX MUST BE AIRTIGHT. Since c3a5f11b `deploy_claim.py` resolves its
# claim dir from `SYNDICATE_DEPLOY_CLAIM_DIR`, then `<SYNDICATE_LOCAL_HOME or
# ~/syndicate-prod>/local_production.env`, and only then from its own repo root.
# Copying the script into tmp_path covers only the last of those. `_run` used to
# pass the real environment through, so on the WSL fleet (nightly ci-suite) this
# file wrote a live 45-min `web` claim -- `HELD by lane-a, session: session-aaa`
# -- into the production claim dir, seen 2026-10-13 and 2026-10-14.
from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import sys

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "deploy_claim.py"


def _sandbox(tmp_path):
    """A throwaway repo root, so a test never touches real deploy claims."""
    (tmp_path / "scripts").mkdir(parents=True)
    shutil.copy(SCRIPT, tmp_path / "scripts" / "deploy_claim.py")
    # Must exist: a named dir that does not is ignored, and the resolver falls
    # through to the next source.
    (tmp_path / ".syndicate" / "deploy_claims").mkdir(parents=True)
    return tmp_path / "scripts" / "deploy_claim.py"


def _env(root, session):
    """Pin every claim-dir source inside the sandbox; inherit nothing that names one."""
    env = {k: v for k, v in os.environ.items()
           if k not in ("SYNDICATE_DEPLOY_CLAIM_DIR", "SYNDICATE_LOCAL_HOME")}
    env["SYNDICATE_DEPLOY_CLAIM_DIR"] = str(root / ".syndicate" / "deploy_claims")
    env["SYNDICATE_LOCAL_HOME"] = str(root / "no-local-home")  # no local_production.env
    env["CLAUDE_CODE_SESSION_ID"] = session
    return env


def _run(script, *args, session="session-aaa"):
    return subprocess.run(
        [sys.executable, str(script), *args],
        cwd=script.parents[1], capture_output=True, text=True,
        env=_env(script.parents[1], session),
    )


def _claim_file(tmp_path):
    claims = list((tmp_path / ".syndicate" / "deploy_claims").glob("*.json"))
    assert claims, "acquire wrote no claim under tmp_path -- it went somewhere real"
    return claims[0]


def test_claim_lands_in_the_sandbox_even_with_a_real_claim_dir_set(tmp_path, monkeypatch):
    """THE LEAK. A claim dir in the parent environment must not be inherited."""
    real = tmp_path / "pretend-production-claims"
    real.mkdir()
    monkeypatch.setenv("SYNDICATE_DEPLOY_CLAIM_DIR", str(real))
    script = _sandbox(tmp_path / "repo")
    r = _run(script, "acquire", "--service", "web", "--holder", "lane-a")
    assert r.returncode == 0, r.stdout + r.stderr
    assert (tmp_path / "repo" / ".syndicate" / "deploy_claims" / "web.json").is_file()
    assert not any(real.iterdir()), "the test wrote into the inherited claim dir"


def test_records_session_and_no_pid(tmp_path):
    script = _sandbox(tmp_path)
    r = _run(script, "acquire", "--service", "web", "--holder", "lane-a")
    assert r.returncode == 0, r.stdout + r.stderr

    claim = json.loads(_claim_file(tmp_path).read_text(encoding="utf-8"))
    assert claim["holder_session"] == "session-aaa"
    # THE REGRESSION: a pid here is always dead and is read as "holder is gone".
    assert "pid" not in claim


def test_refusal_points_at_the_session_and_the_ttl(tmp_path):
    script = _sandbox(tmp_path)
    _run(script, "acquire", "--service", "web", "--holder", "lane-a")
    r = _run(script, "acquire", "--service", "web", "--holder", "lane-b",
             session="session-bbb")
    assert r.returncode == 1
    assert "session-aaa" in r.stdout            # who to actually check
    assert "list_sessions" in r.stdout          # how to check them
    assert "TTL is the real bound" in r.stdout  # what actually holds


def test_legacy_claim_with_a_pid_is_unknown_not_gone(tmp_path):
    """Claims written before the fix still exist. They must not read as free,
    and their stale pid must not be offered as a liveness signal."""
    script = _sandbox(tmp_path)
    _run(script, "acquire", "--service", "web", "--holder", "lane-a")
    f = _claim_file(tmp_path)
    legacy = json.loads(f.read_text(encoding="utf-8"))
    legacy.pop("holder_session")
    legacy["pid"] = 22884
    f.write_text(json.dumps(legacy), encoding="utf-8")

    r = _run(script, "acquire", "--service", "web", "--holder", "lane-b")
    assert r.returncode == 1, "a legacy claim must still block"
    assert "unrecorded" in r.stdout
    assert "UNKNOWN, not gone" in r.stdout

    s = _run(script, "status", "--service", "web")
    assert "HELD" in s.stdout
    assert "22884" not in s.stdout, "never surface the stale pid as identity"
