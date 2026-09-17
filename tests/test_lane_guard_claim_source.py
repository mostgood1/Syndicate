"""`lane-guard.py` enforces origin/main's claims plus claims added locally since the fork point.

MEASURED 2026-09-17 (lane `lane-guard-main-claims`): the guard parsed only the
PRIMARY tree's `lanes.md`, a shared copy hundreds of commits behind origin/main,
and blocked `syndicate/blueprints/ops.py` and `tests/test_artifact_publisher.py`
on claims main had already released. Its message did not say which copy it
read.

Each test runs the REAL hook as a subprocess against a throwaway git repo shaped
like that situation:

- the fork point (HEAD) has `lane-old` claiming `pkg/stale.py` and `lane-keep`
  claiming `pkg/kept.py`;
- origin/main has since CLOSED `lane-old` and added `lane-new` claiming
  `pkg/new_on_main.py`;
- the working copy adds `lane-local` claiming `pkg/local.py`, not landed.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOKS = REPO_ROOT / ".claude" / "hooks"
GUARD = HOOKS / "lane-guard.py"
DASH = "—"


def _lane(slug: str, state: str, path: str) -> str:
    return (
        f"### {slug} {DASH} {state} {DASH} opened 2026-09-10 {DASH} session s-{slug}\n"
        f"- Goal: demo.\n"
        f"- Files: `{path}`\n"
    )


FORK = "## OPEN\n\n" + _lane("lane-old", "OPEN", "pkg/stale.py") + "\n" + _lane("lane-keep", "OPEN", "pkg/kept.py")
MAIN = (
    "## OPEN\n\n" + _lane("lane-old", "CLOSED 2026-09-16", "pkg/stale.py") + "\n"
    + _lane("lane-keep", "OPEN", "pkg/kept.py") + "\n" + _lane("lane-new", "OPEN", "pkg/new_on_main.py")
)
LOCAL = FORK + "\n" + _lane("lane-local", "OPEN", "pkg/local.py")


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "-C", str(repo), *args],
        check=True, capture_output=True, text=True,
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "primary"
    (root / ".syndicate").mkdir(parents=True)
    (root / "pkg").mkdir()
    _git(root, "init", "-q")
    lanes = root / ".syndicate" / "lanes.md"
    lanes.write_text(FORK, encoding="utf-8")
    _git(root, "add", ".syndicate/lanes.md")
    _git(root, "commit", "-q", "-m", "fork point")
    fork = _git(root, "rev-parse", "HEAD")
    _git(root, "checkout", "-q", "-b", "mainline")
    lanes.write_text(MAIN, encoding="utf-8")
    _git(root, "commit", "-q", "-am", "main moves on")
    main = _git(root, "rev-parse", "HEAD")
    _git(root, "checkout", "-q", fork)
    _git(root, "update-ref", "refs/remotes/origin/main", main)
    lanes.write_text(LOCAL, encoding="utf-8")
    return root


def _run_guard(root: Path, relative: str):
    payload = {"tool_name": "Edit", "session_id": "test-session", "tool_input": {"file_path": str(root / relative)}}
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root))
    result = subprocess.run([sys.executable, str(GUARD)], input=json.dumps(payload), capture_output=True, text=True, env=env, timeout=60)
    return result.returncode, result.stderr


def test_a_claim_RELEASED_on_main_no_longer_blocks(repo):
    """THE DEFECT: the stale primary copy still says lane-old holds pkg/stale.py."""
    code, err = _run_guard(repo, "pkg/stale.py")
    assert code == 0, err


def test_a_claim_still_on_main_blocks_and_names_main_as_its_source(repo):
    code, err = _run_guard(repo, "pkg/kept.py")
    assert code == 2
    assert "lane-keep" in err
    assert "Claim source: origin/main@" in err


def test_a_claim_added_ONLY_on_main_blocks_although_the_primary_copy_lacks_it(repo):
    code, err = _run_guard(repo, "pkg/new_on_main.py")
    assert code == 2 and "lane-new" in err


def test_a_claim_added_LOCALLY_and_not_landed_still_blocks(repo):
    code, err = _run_guard(repo, "pkg/local.py")
    assert code == 2 and "lane-local" in err
    assert "added since fork point" in err


def test_an_unclaimed_file_is_never_blocked(repo):
    assert _run_guard(repo, "pkg/free.py")[0] == 0


def test_without_origin_main_it_falls_back_to_the_primary_copy_exactly_as_before(repo):
    """Never less strict when git cannot answer: the stale claim blocks again."""
    _git(repo, "update-ref", "-d", "refs/remotes/origin/main")
    code, err = _run_guard(repo, "pkg/stale.py")
    assert code == 2 and "lane-old" in err
    assert "fallback" in err


def test_the_helper_reports_what_it_dropped(repo):
    sys.path.insert(0, str(HOOKS))
    try:
        from lane_claims_source import effective_claims
    finally:
        sys.path.remove(str(HOOKS))
    entries, info = effective_claims(str(repo), LOCAL)
    paths = {path for _, path, _ in entries}
    assert paths == {"pkg/kept.py", "pkg/new_on_main.py", "pkg/local.py"}
    assert info["mode"] == "main+local"
    assert info["dropped_stale"] == 1 and info["local_added"] == 1
