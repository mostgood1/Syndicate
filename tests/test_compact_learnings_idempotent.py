"""`compact_learnings.py` must compact once and then leave the stub alone.

WHY THIS TEST EXISTS. Measured 2026-08-31: every re-run reported "compacted
sections : 223" against `.syndicate/learnings.md` while reclaiming **0 B**, and
grew `learnings_evidence.md` by 96,555 B -- to within 2 bytes the exact size of
the pre-cutoff entries, because it was moving entries it had already moved. The
date cutoff cannot prevent this on its own: a stub keeps its original heading
date forever, so it falls before EVERY future `--keep-from`.

The second half of the test is the load-bearing half. A predicate that skips
everything would also make the re-run a no-op, so "nothing changed on run 2" is
only meaningful next to "run 1 actually compacted something".
"""
from __future__ import annotations

import pathlib
import subprocess
import sys

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "compact_learnings.py"
MARKER = "*(evidence in `learnings_evidence.md`)*"

FULL_ENTRY = """## 2026-08-01 FORBIDDEN: an entry that has never been compacted

Some evidence prose that is long enough to be worth moving out of the file, and
which must end up in the evidence file exactly once.

- **The rule going forward.** Never do the thing described above.
"""

STUB_ENTRY = f"""## 2026-08-02 FORBIDDEN: an entry that was already compacted

- Never do the other thing.
- {MARKER}
"""


def _ledger(tmp_path):
    d = tmp_path / ".syndicate"
    d.mkdir()
    (d / "learnings.md").write_text(
        "# Syndicate — Learnings\n\npreamble\n\n" + FULL_ENTRY + "\n" + STUB_ENTRY,
        encoding="utf-8",
    )
    (d / "learnings_evidence.md").write_text("# Evidence\n", encoding="utf-8")
    return d / "learnings.md", d / "learnings_evidence.md"


def _run(tmp_path):
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--keep-from", "2026-08-10", "--apply"],
        cwd=tmp_path, capture_output=True, text=True,
    )


def test_compacts_once_then_is_idempotent(tmp_path):
    learn, evid = _ledger(tmp_path)

    r1 = _run(tmp_path)
    assert r1.returncode == 0, r1.stdout + r1.stderr
    learn_1, evid_1 = learn.read_text(encoding="utf-8"), evid.read_text(encoding="utf-8")

    # Run 1 did real work: the full entry lost its prose and gained the marker,
    # and its evidence moved out. Without this the idempotence check below is
    # satisfied by a predicate that simply skips everything.
    assert "Some evidence prose" not in learn_1
    assert "Some evidence prose" in evid_1
    assert learn_1.count(MARKER) == 2          # the newly compacted one + the pre-existing stub
    assert "never been compacted" in learn_1   # heading retained
    assert "Never do the thing described above" in learn_1  # rule retained

    # The already-stubbed entry was not moved even on the first run.
    assert evid_1.count("already compacted") == 0

    r2 = _run(tmp_path)
    assert r2.returncode == 0, r2.stdout + r2.stderr

    # THE REGRESSION: a second run must change neither file.
    assert learn.read_text(encoding="utf-8") == learn_1
    assert evid.read_text(encoding="utf-8") == evid_1
    assert "already compacted  : 2" in r2.stdout


def test_reports_skips_rather_than_hiding_them(tmp_path):
    """A silent skip is how the original bug survived: the run looked productive."""
    _ledger(tmp_path)
    out = _run(tmp_path).stdout
    assert "already compacted  : 1" in out
    assert "compacted sections : 1" in out
