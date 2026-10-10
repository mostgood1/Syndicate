"""No script may rewrite a `.syndicate` ledger DOCUMENT with newline-translating IO.

WHY A GUARD AND NOT A NOTE. The correct pattern already existed in the repo THREE
times before this was enforced -- `lane_open.py` reads/writes bytes and preserves a
BOM, `compact_state.py` reads bytes and restores CRLF explicitly,
`build_soccer_player_match_log.py` pins `newline=""` -- while four tools got it
wrong and two more got it HALF right (pinning the write, leaving the read). Five
independent implementations of one concern, so it recurs by omission. Only an
executable rule stops the seventh tool.

WHAT THE TWO DEFECTS ARE, measured 2026-10-09 on `lanes.md`/`lanes_history.md`:
  READ   `read_text()` / bare `open()` use UNIVERSAL NEWLINES, which maps a lone CR
         to LF. `lanes.md` carried one mid-line bare CR inside a peer's verdict
         line, so every such read turned that line into TWO lines before any work.
  WRITE  `write_text()` / `open(...,"w")` with no `newline=` uses the platform
         default, which rewrote 4MB of `lanes_history.md` LF -> CRLF. Unstaged
         `git diff` showed that as 679/0 and HID it; the staged diff was
         38,213/37,535.

THE ALLOWLIST IS THE WEAK POINT, so it names a MECHANISM per file, not a waiver:
each entry must read/write bytes itself. If you are tempted to add a file here
because the test is inconvenient, use `scripts/ledger_io.py` instead.
"""
from __future__ import annotations

import pathlib
import re

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]

# Files that handle the bytes themselves. Each is the MECHANISM, not a waiver.
_BYTES_OK = {
    "scripts/lane_open.py": "read_bytes/write_bytes, and preserves a UTF-8 BOM",
    "scripts/compact_state.py": "read_bytes + explicit CRLF restore + utf-8-sig",
}

# A ledger DOCUMENT: markdown under .syndicate that sessions read as prose.
_LEDGER_DOC = re.compile(r"['\"]\.?[\w/]*\.syndicate/[\w/]*\.md")
_UNSAFE_READ = re.compile(r"(?:(\w+)\.read_text\(|io\.open\(\s*(\w+)\s*,\s*encoding=)")
_UNSAFE_WRITE = re.compile(r"(?:(\w+)\.write_text\(([^)]*)\)|open\(\s*(\w+)\s*,\s*['\"]w['\"]([^)]*)\))")


def _ledger_identifiers(src: str) -> set[str]:
    """Names assigned a .syndicate/*.md path anywhere in the module."""
    names = set()
    for m in re.finditer(r"(?m)^\s*([A-Za-z_]\w*)\s*=\s*(.+)$", src):
        name, rhs = m.group(1), m.group(2)
        if ".syndicate" in rhs and (".md" in rhs or "lanes" in rhs or "learnings" in rhs
                                    or "state" in rhs or "deploys" in rhs):
            names.add(name)
    return names


def _candidates():
    for f in sorted((_ROOT / "scripts").rglob("*.py")):
        rel = str(f.relative_to(_ROOT)).replace(chr(92), "/")
        try:
            src = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if not _LEDGER_DOC.search(src):
            continue
        yield rel, src


def _writes_a_ledger(src: str) -> bool:
    """Does this module write a ledger doc by ANY mechanism?

    `write_ledger(` must be in this list. A first cut of it was not, so the helper's
    own callers classified as "pure readers" and their reads went unchecked -- the
    detector was blind to exactly the files it had just fixed.
    """
    return bool(re.search(r"write_ledger\(|write_text\(|write_bytes\(|"
                          r"open\([^)]*['\"]w['\"]", src))


def _offences(rel: str, src: str) -> list[str]:
    """Unsafe IO applied to one of this module's ledger-path names.

    SCOPE: an unsafe WRITE is always an offence. An unsafe READ is an offence only
    in a module that also WRITES, because that is where a split line gets persisted.
    A pure reader with a universal-newline read can still mis-parse a line holding a
    bare CR -- that is a real but separate exposure, recorded as a lead rather than
    enforced here, so this guard's name and its behaviour agree.
    """
    if rel in _BYTES_OK:
        return []
    names = _ledger_identifiers(src)
    if not names:
        return []
    bad = []
    if _writes_a_ledger(src):
        for m in _UNSAFE_READ.finditer(src):
            ident = m.group(1) or m.group(2)
            if ident in names:
                bad.append(f"universal-newline READ of {ident}: {m.group(0)[:46]}")
    for m in _UNSAFE_WRITE.finditer(src):
        ident, tail = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
        if ident in names and "newline" not in (tail or ""):
            bad.append(f"platform-newline WRITE of {ident}: {m.group(0)[:46]}")
    return bad


def test_the_guard_can_actually_see_something():
    """A control. Without it, an empty candidate set would pass silently."""
    cands = list(_candidates())
    assert len(cands) >= 8, f"only {len(cands)} candidates -- the detector is blind"
    assert any(rel in _BYTES_OK for rel, _ in cands), "the bytes-OK files are not even scanned"


@pytest.mark.parametrize("rel", [r for r, _ in _candidates()])
def test_no_ledger_document_is_rewritten_with_translating_io(rel):
    src = (_ROOT / rel).read_text(encoding="utf-8", errors="replace")
    bad = _offences(rel, src)
    assert not bad, (
        "use scripts/ledger_io.py (read_ledger/write_ledger) for " + rel + ":"
        + chr(10) + chr(10).join("  - " + b for b in bad))


def test_every_allowlisted_file_really_does_handle_bytes():
    """The allowlist must stay a statement of mechanism, not a silencer."""
    for rel, reason in sorted(_BYTES_OK.items()):
        p = _ROOT / rel
        assert p.exists(), rel + " is allowlisted but missing"
        src = p.read_text(encoding="utf-8", errors="replace")
        assert "read_bytes" in src and "write_bytes" in src, (
            rel + " is allowlisted as '" + reason + "' but no longer reads/writes bytes")


def test_the_write_detector_knows_about_the_helper():
    """Control for the blindness that bit the first cut of this guard.

    `write_ledger(` is how every converted tool writes, so a detector that does not
    recognise it classifies those tools as pure readers and skips their reads.
    """
    assert _writes_a_ledger("    write_ledger(LANES, text, eol)")
    assert _writes_a_ledger('    LANES.write_text(t, encoding="utf-8")')
    assert _writes_a_ledger('    with open(LANES, "w", encoding="utf-8") as fh:')
    assert not _writes_a_ledger("    text, eol = read_ledger(LANES)")


def test_a_converted_tool_is_classified_as_a_writer():
    """Named example, so the rule above is anchored to a real file."""
    src = (_ROOT / "scripts/archive_released_lanes.py").read_text(encoding="utf-8")
    assert _writes_a_ledger(src), "the archive tool must count as a writer"
    assert not _offences("scripts/archive_released_lanes.py", src)
