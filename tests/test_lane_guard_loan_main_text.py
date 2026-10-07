"""`lane-guard.py` judges loans and declared sections on the SAME view its claims came from.

MEASURED 2026-10-07 ~16:35 CT (lane `lane-guard-loan-main-text`): lane
`web-restart-healthz` held a user-approved loan of
`syndicate/features/shared/kalshi_board_join.py` from `mlb-doubleheader-e2e`,
recorded on origin/main in 55547ac5. The guard took its claims from origin/main
(`lane_claims_source.effective_claims`) but re-parsed the PRIMARY tree's
`lanes.md` for the loan -- a copy hours behind that did not contain the
borrower's block at all -- and BLOCKED the edit.

Each test runs the REAL hook as a subprocess against a throwaway git repo:

- the fork point (HEAD, and the working copy) has only the lender
  `mlb-doubleheader-e2e` holding the file, plus a bystander lane;
- origin/main has since added the borrower `web-restart-healthz` with the loan.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
GUARD = REPO_ROOT / ".claude" / "hooks" / "lane-guard.py"
DASH = "—"
SESSION = "test-session"
LENT = "pkg/kalshi_board_join.py"


def _lane(slug: str, files: str, state: str = "OPEN") -> str:
    return (
        f"### {slug} {DASH} {state} {DASH} opened 2026-10-07 {DASH} session s-{slug}\n"
        f"- Goal: demo.\n"
        f"- Files: {files}\n\n"
    )


LENDER = _lane("mlb-doubleheader-e2e", f"`{LENT}`, `pkg/held.py`")
BYSTANDER = _lane("bystander", "`pkg/bystander.py`")
FORK = "## OPEN\n\n" + LENDER + BYSTANDER
BORROWER = _lane(
    "web-restart-healthz",
    f"`pkg/web_worker.py`, `{LENT}` (LOAN from mlb-doubleheader-e2e, user-approved)",
)
# A SELF-GRANT: the named "lender" is an OPEN lane, but it does not hold the path.
SELF_GRANT = _lane("self-granter", "`pkg/mine.py`, `pkg/held.py` (LOAN from bystander)")
MAIN = FORK + BORROWER + SELF_GRANT


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "-C", str(repo), *args],
        check=True, capture_output=True, text=True,
    ).stdout.strip()


def _make_repo(root: Path, fork: str, main: str, local: str) -> Path:
    (root / ".syndicate").mkdir(parents=True)
    (root / "pkg").mkdir()
    _git(root, "init", "-q")
    lanes = root / ".syndicate" / "lanes.md"
    lanes.write_text(fork, encoding="utf-8")
    _git(root, "add", ".syndicate/lanes.md")
    _git(root, "commit", "-q", "-m", "fork point")
    fork_sha = _git(root, "rev-parse", "HEAD")
    _git(root, "checkout", "-q", "-b", "mainline")
    lanes.write_text(main, encoding="utf-8")
    _git(root, "commit", "-q", "--allow-empty", "-am", "main moves on")
    main_sha = _git(root, "rev-parse", "HEAD")
    _git(root, "checkout", "-q", fork_sha)
    _git(root, "update-ref", "refs/remotes/origin/main", main_sha)
    lanes.write_text(local, encoding="utf-8")
    return root


@pytest.fixture
def repo(tmp_path):
    # The primary copy LACKS the borrower block entirely -- the measured shape.
    return _make_repo(tmp_path / "primary", FORK, MAIN, FORK)


def _run_guard(root: Path, relative: str, lane: str):
    (root / ".syndicate" / f".current-lane.{SESSION}").write_text(lane, encoding="utf-8")
    payload = {"tool_name": "Edit", "session_id": SESSION, "tool_input": {"file_path": str(root / relative)}}
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root))
    result = subprocess.run(
        [sys.executable, str(GUARD)], input=json.dumps(payload),
        capture_output=True, text=True, env=env, timeout=60,
    )
    return result.returncode, result.stderr


def test_a_loan_recorded_on_MAIN_is_honoured_although_the_primary_copy_lacks_the_borrower(repo):
    """THE DEFECT: the primary lanes.md has no `web-restart-healthz` block at all."""
    assert "web-restart-healthz" not in (repo / ".syndicate" / "lanes.md").read_text(encoding="utf-8")
    code, err = _run_guard(repo, LENT, "web-restart-healthz")
    assert code == 0, err
    assert "LOAN HONOURED" in err and "mlb-doubleheader-e2e" in err


def test_CONTROL_a_self_granted_loan_from_a_NON_HOLDER_still_blocks(repo):
    """`bystander` is OPEN but does not hold pkg/held.py; the real holder lent nothing."""
    code, err = _run_guard(repo, "pkg/held.py", "self-granter")
    assert code == 2, err
    assert "mlb-doubleheader-e2e" in err and "LOAN HONOURED" not in err


def test_CONTROL_a_lane_that_is_not_the_borrower_is_still_blocked_on_the_lent_file(repo):
    code, err = _run_guard(repo, LENT, "bystander")
    assert code == 2, err


def test_a_loan_only_in_the_stale_primary_copy_and_REVOKED_on_main_is_not_honoured(tmp_path):
    """The same rule as claims: an entry main has dropped no longer counts."""
    with_loan = FORK + BORROWER
    revoked = FORK + _lane("web-restart-healthz", "`pkg/web_worker.py`")
    root = _make_repo(tmp_path / "primary", with_loan, revoked, with_loan)
    code, err = _run_guard(root, LENT, "web-restart-healthz")
    assert code == 2, err


def test_a_loan_added_LOCALLY_and_not_landed_is_still_honoured(tmp_path):
    root = _make_repo(tmp_path / "primary", FORK, FORK, FORK + BORROWER)
    code, err = _run_guard(root, LENT, "web-restart-healthz")
    assert code == 0, err


def test_disjoint_sections_declared_on_MAIN_are_honoured_although_the_primary_copy_lacks_them(tmp_path):
    doc = "docs/runbook.md"
    fork = "## OPEN\n\n" + _lane("watchdog", f"`{doc}` (watchdog section only)")
    main = fork + _lane("web-reload", f"`{doc}` (web reload section only)")
    root = _make_repo(tmp_path / "primary", fork, main, fork)
    code, err = _run_guard(root, doc, "web-reload")
    assert code == 0, err
    assert "SECTION-SCOPED" in err
