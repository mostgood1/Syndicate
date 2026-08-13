"""Two-actor tests for the checkpoint-guard Stop hook.

WHY THIS FILE IS TWO-ACTOR AND WHY THAT IS THE POINT
----------------------------------------------------
The guard has two failure directions and they are not symmetric:

  FALSE WARN  - a session that did checkpoint is told it did not. Loud,
                annoying, gets noticed and fixed.
  FALSE PASS  - a session that did NOT checkpoint is waved through. Silent.
                The work is lost, which is the only thing this hook exists to
                prevent.

An earlier fix (2026-08-13) scoped the guard's DENOMINATOR to the session but
left its WITNESS as the repo-global `.syndicate/.last-checkpoint`. Eight
single-actor cases passed. All eight asked "does this session get the right
verdict for its own actions"; none asked "can ANOTHER session's action change
my verdict". It could: session A touching the shared marker silenced session
B's warning entirely.

A single-actor suite cannot express that failure however many cases it has.
So every case here has a bystander, session A, doing the right thing - and the
assertion is about session B. `test_two_actor_*` is the load-bearing one; if
you only keep one test from this file, keep that.
"""
import datetime
import json
import os
import shutil
import subprocess
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GUARD = os.path.join(REPO_ROOT, ".claude", "hooks", "checkpoint-guard.py")

# Fixed epoch so ordering never depends on the wall clock or on test duration.
T = 1786600000.0

pytestmark = pytest.mark.skipif(
    not os.path.exists(GUARD) or shutil.which("git") is None,
    reason="checkpoint-guard hook or git not available",
)


def _iso(ts):
    return (
        datetime.datetime.fromtimestamp(ts, datetime.timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )


@pytest.fixture
def repo(tmp_path):
    """A git repo with a ledger, one committed file, and a helper API."""
    root = tmp_path / "wt"
    (root / ".syndicate" / "log").mkdir(parents=True)
    run = lambda *a: subprocess.run(a, cwd=str(root), capture_output=True, text=True)
    run("git", "init", "-q", ".")
    run("git", "config", "user.email", "t@t")
    run("git", "config", "user.name", "t")
    (root / "code.txt").write_text("base\n", encoding="utf-8")
    run("git", "add", "-A")
    run("git", "commit", "-qm", "base")

    class R:
        path = root

        def write(self, rel, text, at):
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
            os.utime(str(p), (T + at, T + at))

        def transcript(self, entries, name="B.jsonl"):
            lines = []
            for kind, off, arg in entries:
                ts = _iso(T + off)
                if kind == "edit":
                    blk = {"type": "tool_use", "name": "Edit",
                           "input": {"file_path": str(root / arg)}}
                    lines.append({"type": "assistant", "timestamp": ts,
                                  "message": {"content": [blk]}})
                elif kind == "bash":
                    blk = {"type": "tool_use", "name": "Bash",
                           "input": {"command": arg}}
                    lines.append({"type": "assistant", "timestamp": ts,
                                  "message": {"content": [blk]}})
                elif kind == "checkpoint":
                    lines.append({"type": "user", "timestamp": ts, "message": {
                        "content": "<command-name>/checkpoint</command-name>"}})
            p = root / name
            p.write_text("".join(json.dumps(l) + "\n" for l in lines), encoding="utf-8")
            return str(p)

        def verdict(self, tpath):
            payload = json.dumps({"transcript_path": tpath, "cwd": str(root),
                                  "hook_event_name": "Stop"})
            r = subprocess.run([sys.executable, GUARD], input=payload,
                               capture_output=True, text=True)
            return r.returncode, (r.stderr or "")

    return R()


def _session_a_checkpoints(repo, at=200):
    """Bystander session A does everything right, on the SHARED ledger."""
    repo.write(".syndicate/.last-checkpoint", "", at)
    repo.write(".syndicate/log/2026-08-13.md", "A's checkpoint\n", at)


def test_two_actor_another_sessions_checkpoint_does_not_clear_mine(repo):
    """THE load-bearing case. B never checkpointed; A did, later. B must warn.

    Under the marker-based witness this returned 0 and B's work was lost
    silently. Regression guard for that exact hole.
    """
    repo.write("code.txt", "B changed this\n", 0)
    _session_a_checkpoints(repo, at=200)  # newer than B's work
    rc, err = repo.verdict(repo.transcript([("edit", 0, "code.txt")]))
    assert rc == 1, "B was cleared by A's checkpoint -- the false pass is back"
    assert "never checkpointed" in err


def test_two_actor_my_own_checkpoint_does_clear_mine(repo):
    """Same bystander, but B checkpointed too. B must pass.

    Pairs with the test above: together they prove the guard distinguishes
    WHOSE checkpoint it is, rather than just always warning.
    """
    repo.write("code.txt", "B changed this\n", 0)
    _session_a_checkpoints(repo, at=200)
    rc, _ = repo.verdict(repo.transcript(
        [("edit", 0, "code.txt"), ("checkpoint", 100, None)]))
    assert rc == 0


def test_work_after_my_checkpoint_warns(repo):
    repo.write("code.txt", "B changed this\n", 150)
    _session_a_checkpoints(repo, at=200)
    rc, err = repo.verdict(repo.transcript(
        [("edit", 0, "code.txt"), ("checkpoint", 100, None)]))
    assert rc == 1
    assert "postdates the last checkpoint" in err


def test_heredoc_ledger_append_counts_as_a_checkpoint(repo):
    """`/checkpoint` step 2 is a `cat >>` heredoc and leaves no file-tool
    record. Without this the guard warns at every real checkpoint."""
    repo.write("code.txt", "B changed this\n", 0)
    rc, _ = repo.verdict(repo.transcript([
        ("edit", 0, "code.txt"),
        ("bash", 100, "cat >> .syndicate/log/2026-08-13.md <<'EOF'"),
    ]))
    assert rc == 0


def test_ledger_only_work_is_not_at_risk(repo):
    """`.syndicate/**` is the persistence, not the thing at risk."""
    repo.write(".syndicate/state.md", "B wrote ledger only\n", 0)
    rc, _ = repo.verdict(repo.transcript([("edit", 0, ".syndicate/state.md")]))
    assert rc == 0


def test_guard_can_warn_with_no_bystander(repo):
    """Positive control. If this ever passes, the suite proves nothing:
    a guard that cannot warn makes every other assertion here vacuous."""
    repo.write("code.txt", "B changed this\n", 0)
    rc, _ = repo.verdict(repo.transcript([("edit", 0, "code.txt")]))
    assert rc == 1


def test_fails_open_on_a_broken_payload(repo):
    """Every error path exits 0. A guard that blocks on its own bug costs
    more than the mistakes it prevents."""
    r = subprocess.run([sys.executable, GUARD], input="not json",
                       capture_output=True, text=True)
    assert r.returncode == 0
