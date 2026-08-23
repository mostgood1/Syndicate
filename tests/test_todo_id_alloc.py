"""`#536`. Two sessions must not be handed the same TODO id.

WHY THIS EXISTS. Ids were allocated by reading `todo.md`, taking the largest and
adding one. The read and the write are not atomic, so two sessions looking at the
same moment pick the same number -- and the loser finds out at `git merge`, after
the entry, the code comments and the tests are written and have to be renamed
together, because a stale `#N` in a comment resolves to somebody else's item and
reads as deliberate.

Measured 2026-08-23: **eight collisions in one session**, across at least three
sessions -- 514/515 -> 520/521, 522 -> 523, 524 -> 525, 527/528 -> 530/531,
532 -> 536.

The mechanism is the one `deploy_claim.py` already uses and whose docstring
explains why messaging cannot substitute for it. These tests pin the property
that matters (no two callers get the same number) rather than the file layout.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import todo_id_alloc as alloc


@pytest.fixture
def _sandbox(tmp_path, monkeypatch):
    todo = tmp_path / "todo.md"
    closed = tmp_path / "todo_closed.md"
    todo.write_text("# t\n\n### `#100` — a\n\n### `#102` — b\n", encoding="utf-8")
    closed.write_text("### `#101` — c\n", encoding="utf-8")
    monkeypatch.setattr(alloc, "TODO", todo)
    monkeypatch.setattr(alloc, "CLOSED", closed)
    monkeypatch.setattr(alloc, "CLAIM_DIR", tmp_path / "ids")
    return tmp_path


def test_the_high_water_mark_spans_both_ledgers(_sandbox):
    """An id closed and archived is still ISSUED. Reading only the open file
    would re-issue it, and `todo.md`'s own rule is that ids never repeat."""
    assert alloc.high_water() == 102


def test_it_reads_the_archive_s_older_formats(_sandbox, monkeypatch):
    """The archive carries table rows and bullets, not just headers --
    `todo_id_reconcile.py` documents both eras. A scanner that saw only today's
    format would under-report the mark and collide with history."""
    (_sandbox / "todo_closed.md").write_text(
        "| **310** | old table row |\n- **#311 a bullet\n#### `#312` a sub-header\n",
        encoding="utf-8",
    )
    assert alloc.high_water() == 312


def test_two_callers_never_get_the_same_id(_sandbox):
    """THE PROPERTY. This is the whole point of the tool."""
    first = alloc.allocate("lane-a")
    second = alloc.allocate("lane-b")
    assert first == [103]
    assert second == [104]
    assert set(first).isdisjoint(second)


def test_a_claim_counts_toward_the_mark_before_the_entry_is_written(_sandbox):
    """The gap the ledger scan cannot see: an id allocated a minute ago is not in
    `todo.md` yet -- the entry is still being written. Ignoring claims would hand
    the same number to the next caller, which IS the bug."""
    alloc.allocate("lane-a")
    assert alloc.high_water() == 103


def test_an_existing_claim_is_stepped_over_not_overwritten(_sandbox):
    (_sandbox / "ids").mkdir()
    (_sandbox / "ids" / "103.claim").write_text("{}", encoding="utf-8")
    assert alloc.allocate("lane-b") == [104]
    # The squatter's file must be untouched -- overwriting it would silently
    # transfer an id somebody else is already writing an entry for.
    assert (_sandbox / "ids" / "103.claim").read_text(encoding="utf-8") == "{}"


def test_it_can_allocate_a_contiguous_batch(_sandbox):
    assert alloc.allocate("lane-a", count=3) == [103, 104, 105]


def test_the_claim_records_who_took_it(_sandbox):
    """A claim nobody can attribute is a gap with no owner to ask about."""
    (value,) = alloc.allocate("layer2-sim-view-and-live-projection")
    payload = json.loads((_sandbox / "ids" / f"{value}.claim").read_text(encoding="utf-8"))
    assert payload["id"] == value
    assert payload["holder"] == "layer2-sim-view-and-live-projection"
    assert payload["claimed_at"]


def test_empty_ledgers_start_at_one(_sandbox):
    (_sandbox / "todo.md").write_text("# nothing\n", encoding="utf-8")
    (_sandbox / "todo_closed.md").write_text("", encoding="utf-8")
    assert alloc.allocate("lane-a") == [1]


def test_a_missing_ledger_is_not_a_crash(_sandbox):
    """Absent must not read as id 0 and must not raise -- this runs at the start
    of somebody's work, and a tool that fails there gets bypassed."""
    (_sandbox / "todo_closed.md").unlink()
    assert alloc.high_water() == 102
