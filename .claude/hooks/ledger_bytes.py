r"""Escape damage in ledger markdown -- the predicate the two ledger hooks share.

WHAT HAPPENED. A Windows path such as `C:\tmp\lpa\nfl.py` went through string
escape processing on its way into a ledger file, so its backslashes became
characters:

  `\t` -> TAB          `C:\tmp`        -> `C:<TAB>mp`
  `\b` `\f` `\v` `\a`  `\bball_sc`     -> `<BS>ball_sc`
  `\NNN` (octal)       `\2026-11-13`   -> `<U+0082>6-11-13`
  `\r` -> CR           `\realv`        -> `<CR>ealv`
  `\n` -> line break   `\nba_bt`       -> the path split across two lines

The usual carriers: a Git Bash heredoc (it collapsed `\\` to `\` here even
QUOTED, so Python then read `\t`), `echo -e` / printf, or a non-raw Python
string. Measured: commit `06fd70625` (2026-11-13) repaired 108 such paths in 36
ledger files; 4 of them had been pushed that same morning, and the next ledger
commit to land (todo #797, the same day) carried a new one. Nothing failed and
no reader noticed: the paths simply stopped pointing anywhere.

WHAT IS FLAGGED, and why each is safe to refuse:

  control   a C0 control other than TAB/LF/CR, DEL, or a C1 control
            (U+0080..U+009F). None has any use in markdown. Anywhere in a line.
  mojibake  U+00E2 U+0080 U+0080..U+00BF: UTF-8 punctuation (an em dash, a
            curly quote) encoded TWICE. Reported as one finding, not as the
            two C1 controls inside it.
  lone_cr   a CR not followed by LF. A CRLF file has none, an LF file has none.
  tab_path  a TAB INSIDE a `C:` path token, followed by a path character. The
            one false positive this admits is a tab-separated paste whose
            column starts right after a `C:` path; that is rare in this ledger
            and is a one-line fix if it happens.

WHAT IS NOT FLAGGED, on purpose:

  * U+FFFD. todo.md quotes it 11 times in prose ABOUT mojibake (`V\ufffdsquez`).
  * A TAB anywhere else -- pasted TSV and tab-indented code are legitimate.
  * A path split by `\n` with no other damage. A path at the end of a line
    followed by a lowercase line is also ordinary wrapped prose, and nothing in
    the text can tell them apart (the 11-13 repair rejoined those only after
    checking the joined path on disk). Every split it found ALSO carried a TAB
    (all were `C:\tmp\...`), so the TAB is what gets caught.

ONLY NEW DAMAGE COUNTS. `introduced(new, old)` compares (kind, line) multisets,
so damage that the committed blob already carries never blocks. That is what
keeps an unrelated commit from being held hostage by an old file, and it is
also why the comparison is per LINE with any trailing CR stripped: a CRLF
working copy and its LF blob compare equal.

Pure library, no side effects on import -- same pattern as `ledger_invariants.py`.
"""
from __future__ import annotations

import collections
import re

# The ledger this applies to: every markdown file under these two trees.
LEDGER_DIRS = (".syndicate", "docs/ai_context")

_ESCAPE = {"\x07": "a", "\x08": "b", "\x0b": "v", "\x0c": "f", "\t": "t"}
_CONTROL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
_MOJIBAKE = re.compile("\u00e2\u0080[\u0080-\u00bf]")
_LONE_CR = re.compile("\r(?!\n)")
# A path token: `C:` then path characters, where a TAB or a control character
# still counts as part of the token (it replaced a backslash + letter).
_TOKEN = re.compile("C:(?:[\t\x07\x08\x0b\x0c\x80-\x9f]|[^\\s`'\"()<>,;|*])+")
_PATH_CHAR = re.compile(r"[A-Za-z0-9_.\-]")

Finding = collections.namedtuple("Finding", "kind lineno line col")


def is_ledger_path(rel):
    rel = (rel or "").replace("\\", "/")
    return rel.endswith(".md") and any(rel.startswith(d + "/") for d in LEDGER_DIRS)


def _text(data):
    if data is None:
        return ""
    if isinstance(data, bytes):
        return data.decode("utf-8", "replace")
    return data


def _lines(text):
    """Split on LF only, so a lone CR stays INSIDE its line; drop one CRLF CR."""
    for n, line in enumerate(text.split("\n"), 1):
        yield n, (line[:-1] if line.endswith("\r") else line)


def findings(data):
    """[Finding] for every damaged character in `data` (bytes or str)."""
    out = []
    for n, line in _lines(_text(data)):
        if not line:
            continue
        taken = set()
        for m in _MOJIBAKE.finditer(line):
            out.append(Finding("mojibake", n, line, m.start()))
            taken.update(range(m.start(), m.end()))
        for m in _CONTROL.finditer(line):
            if m.start() not in taken:
                out.append(Finding("control", n, line, m.start()))
        for m in _LONE_CR.finditer(line):
            out.append(Finding("lone_cr", n, line, m.start()))
        for m in _TOKEN.finditer(line):
            tok = m.group()
            for i, ch in enumerate(tok):
                if ch == "\t" and _PATH_CHAR.match(tok[i + 1:i + 2]):
                    out.append(Finding("tab_path", n, line, m.start() + i))
    return out


def introduced(new, old):
    """Findings in `new` that `old` does not already carry, compared per line."""
    have = collections.Counter((f.kind, f.line) for f in findings(old))
    out = []
    for f in findings(new):
        key = (f.kind, f.line)
        if have[key] > 0:
            have[key] -= 1
        else:
            out.append(f)
    return out


def _visible(ch):
    if ch == "\t":
        return "<TAB>"
    if ch == "\r":
        return "<CR>"
    return "<U+%04X>" % ord(ch)


def _likely(ch):
    """What the character most likely was before escape processing."""
    if ch in _ESCAPE:
        return "\\" + _ESCAPE[ch]
    if ch == "\r":
        return "\\r (or a stray CR: delete it)"
    if 0x80 <= ord(ch) <= 0x9f:
        return "\\%o + the next digit(s)" % ord(ch)
    return "?"


_WHAT = {"control": "control character", "mojibake": "double-encoded UTF-8",
         "lone_cr": "lone CR", "tab_path": "TAB inside a C: path"}


def describe(f, width=46):
    """One line: where, what, the damage made visible, and the likely original."""
    lo = max(0, f.col - width // 2)
    snippet = "".join(_visible(c) if (c in "\t\r" or _CONTROL.match(c)) else c
                      for c in f.line[lo:f.col + width // 2])
    if f.kind == "mojibake":
        was = "the UTF-8 character it encodes (an em dash for U+00E2 U+0080 U+0094)"
    else:
        was = _likely(f.line[f.col])
    return "line %d, %s: ...%s...   (was: %s)" % (f.lineno, _WHAT[f.kind], snippet, was)


REMEDY = (
    "A backslash in a Windows path was read as an ESCAPE on its way into this\n"
    "file: \\t became a TAB, \\b \\f \\v \\a became control characters, \\NNN an octal\n"
    "character, \\r a carriage return -- and \\n a line break, which splits the\n"
    "path across two lines (this check sees the TAB beside it, not the split).\n"
    "The usual carrier is a Git Bash heredoc (it collapses \\\\ to \\ even when\n"
    "quoted), `echo -e`/printf, or a non-raw Python string.\n"
    "Fix the line in place, backslashes intact: build them with chr(92), use a\n"
    "raw string, write the script with the Write tool, or use the Edit tool on\n"
    "the ledger file. Rejoin any path the damage split across two lines.\n"
    "Repair tooling and the 11-13 precedent: commit 06fd70625.")
