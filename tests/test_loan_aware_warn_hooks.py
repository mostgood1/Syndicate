"""`scope-guard` and `lane-postwrite-check` honour a loan exactly as `lane-guard` does.

REPORTED 2026-10-07 by lane `layer2-shard-generations` (session b9bb5f37): its
loan of `pipeline/intelligence_state.py` from `web-restart-healthz` was recorded
on origin/main and lane-guard PERMITTED the Edit, yet both warning hooks reported
the write as out-of-lane -- neither consulted loans. A warning that fires on every
permitted write is one sessions learn to scroll past, including when it is real.

Each test runs the REAL hook as a subprocess against a throwaway git repo:

- the fork point (HEAD, and the working copy) holds the lender
  `mlb-doubleheader-e2e` on `pkg/lent.py` and `pkg/held.py`, plus `bystander`;
- origin/main has since added the borrower `web-restart-healthz` (own file
  `web/worker.py`, plus the loan of `pkg/lent.py`) and a SELF-GRANTER whose
  "lender" is an OPEN lane that does not hold the path.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOKS = REPO_ROOT / ".claude" / "hooks"
SCOPE = HOOKS / "scope-guard.py"
POSTWRITE = HOOKS / "lane-postwrite-check.py"
DASH = "—"


def _lane(slug: str, files: str) -> str:
    return (
        f"### {slug} {DASH} OPEN {DASH} opened 2026-10-07 {DASH} session s-{slug}\n"
        f"- Goal: demo goal for {slug}.\n"
        f"- Files: {files}\n\n"
    )


FORK = "## OPEN\n\n" + _lane("mlb-doubleheader-e2e", "`pkg/lent.py`, `pkg/held.py`") + _lane("bystander", "`side/bystander.py`")
BORROWER = _lane("web-restart-healthz", "`web/worker.py`, `pkg/lent.py` (LOAN from mlb-doubleheader-e2e, user-approved)")
SELF_GRANT = _lane("self-granter", "`mine/x.py`, `pkg/held.py` (LOAN from bystander)")
MAIN = FORK + BORROWER + SELF_GRANT


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "-C", str(repo), *args],
        check=True, capture_output=True, text=True,
    ).stdout.strip()


def _make_repo(root: Path, local: str) -> Path:
    (root / ".syndicate").mkdir(parents=True)
    for rel in ("pkg/lent.py", "pkg/held.py", "web/worker.py", "mine/x.py", "side/bystander.py"):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text("x = 1\n", encoding="utf-8")
    _git(root, "init", "-q")
    lanes = root / ".syndicate" / "lanes.md"
    lanes.write_text(FORK, encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "fork point")
    fork = _git(root, "rev-parse", "HEAD")
    _git(root, "checkout", "-q", "-b", "mainline")
    lanes.write_text(MAIN, encoding="utf-8")
    _git(root, "commit", "-q", "-am", "main moves on")
    main = _git(root, "rev-parse", "HEAD")
    _git(root, "checkout", "-q", fork)
    _git(root, "update-ref", "refs/remotes/origin/main", main)
    lanes.write_text(local, encoding="utf-8")
    return root


@pytest.fixture
def repo(tmp_path):
    """The measured shape: the primary copy LACKS the borrower's block."""
    return _make_repo(tmp_path / "primary", FORK)


@pytest.fixture
def repo_current(tmp_path):
    """The primary copy is current, so the borrower's OWN claims parse locally and
    only the loaned file is out of its declared areas."""
    return _make_repo(tmp_path / "primary", MAIN)


def _env(root: Path):
    return dict(os.environ, CLAUDE_PROJECT_DIR=str(root), SYNDICATE_SCOPE_GUARD="", SYNDICATE_LANE_POSTCHECK="")


def _session(root: Path, lane: str) -> str:
    sid = "t-" + uuid.uuid4().hex[:12]  # fresh once-per-area slot every call
    (root / ".syndicate" / f".current-lane.{sid}").write_text(lane, encoding="utf-8")
    return sid


def _scope(root: Path, rel: str, lane: str):
    sid = _session(root, lane)
    payload = {"tool_name": "Edit", "session_id": sid, "cwd": str(root),
               "tool_input": {"file_path": str(root / rel)}}
    r = subprocess.run([sys.executable, str(SCOPE)], input=json.dumps(payload),
                       capture_output=True, text=True, env=_env(root), timeout=60)
    return r.returncode, r.stderr


def _shell_write(root: Path, rel: str, lane: str):
    sid = _session(root, lane)
    payload = {"tool_name": "Bash", "session_id": sid, "cwd": str(root)}
    pre = subprocess.run([sys.executable, str(POSTWRITE), "--pre"], input=json.dumps(payload),
                         capture_output=True, text=True, env=_env(root), timeout=60)
    assert pre.returncode == 0, pre.stderr
    target = root / rel
    target.write_text(target.read_text(encoding="utf-8") + "y = 2  # shell write\n", encoding="utf-8")
    r = subprocess.run([sys.executable, str(POSTWRITE)], input=json.dumps(payload),
                       capture_output=True, text=True, env=_env(root), timeout=60)
    return r.returncode, r.stderr


# ---- scope-guard -----------------------------------------------------------

def test_scope_guard_is_quiet_on_a_loan_recorded_on_MAIN_although_the_primary_copy_lacks_the_borrower(repo):
    code, err = _scope(repo, "pkg/lent.py", "web-restart-healthz")
    assert code == 0, err


def test_scope_guard_is_quiet_on_a_lent_file_outside_the_borrowers_declared_areas(repo_current):
    code, err = _scope(repo_current, "pkg/lent.py", "web-restart-healthz")
    assert code == 0, err


def test_scope_guard_REACHABILITY_an_unlent_file_in_another_area_still_warns(repo_current):
    """Proves the hook can fire in this harness, so the quiet results above mean something."""
    code, err = _scope(repo_current, "side/bystander.py", "web-restart-healthz")
    assert code == 2 and "OUTSIDE lane 'web-restart-healthz'" in err, err


def test_scope_guard_CONTROL_a_self_granted_loan_from_a_non_holder_still_warns(repo_current):
    code, err = _scope(repo_current, "pkg/held.py", "self-granter")
    assert code == 2 and "OUTSIDE lane 'self-granter'" in err, err


# ---- lane-postwrite-check --------------------------------------------------

def test_postwrite_is_quiet_on_a_shell_write_to_a_file_lent_on_MAIN(repo):
    code, err = _shell_write(repo, "pkg/lent.py", "web-restart-healthz")
    assert code == 0, err


def test_postwrite_REACHABILITY_an_unlent_claimed_file_still_reports(repo):
    code, err = _shell_write(repo, "pkg/held.py", "web-restart-healthz")
    assert code == 2 and "OUT-OF-LANE WRITE" in err and "pkg/held.py" in err, err


def test_postwrite_CONTROL_a_self_granted_loan_from_a_non_holder_still_reports(repo_current):
    code, err = _shell_write(repo_current, "pkg/held.py", "self-granter")
    assert code == 2 and "pkg/held.py" in err and "mlb-doubleheader-e2e" in err, err
