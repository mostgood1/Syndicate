"""A ledger tool must not alter a byte it was not asked to change.

MEASURED 2026-10-09. `lanes.md` contains exactly one mid-line BARE CR, inside a
peer's verdict line. Two separate defects turned that into damage, and conflating
them is why the first fix was a half-fix:

  READ  `pathlib.read_text()` uses UNIVERSAL NEWLINES, which maps a lone CR to LF.
        The peer's line became two lines before any processing. `74da0acd` had
        already repaired that split once.
  WRITE `write_text()` with no `newline=` uses the platform default, so on Windows
        it rewrote the whole 4MB `lanes_history.md` LF -> CRLF. Unstaged
        `git diff` reported 679/0 and hid it; the staged diff was 38,213/37,535.

`trim_lane_narrative.py` had pinned the write and left the read -- the shape of a
half-fix. These tests pin BOTH halves, and the round-trip test below FAILS against
the pre-fix code, which is what makes it worth having.
"""
from __future__ import annotations

import importlib.util
import pathlib

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
CR = chr(13)
LF = chr(10)
CRLF = CR + LF


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, _ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


io_mod = _load("ledger_io_under_test", "scripts/ledger_io.py")


def _fixture(eol):
    """A ledger-shaped fixture: a mid-line bare CR, and `eol` line endings."""
    lines = [
        "## OPEN",
        "",
        "### a-lane " + chr(8212) + " OPEN " + chr(8212) + " opened 2026-10-09",
        "- Goal: payload cut from 68 MB" + CR + '" -- GOAL: MET',
        "- Files: scripts/x.py",
        "",
    ]
    return eol.join(lines) + eol


@pytest.mark.parametrize("eol", [LF, CRLF], ids=["lf", "crlf"])
def test_round_trip_is_byte_exact(tmp_path, eol):
    """The whole point: read then write changes nothing at all."""
    p = tmp_path / "lanes.md"
    original = _fixture(eol).encode("utf-8")
    p.write_bytes(original)
    text, found = io_mod.read_ledger(p)
    io_mod.write_ledger(p, text, found)
    assert p.read_bytes() == original, "round trip altered bytes"


@pytest.mark.parametrize("eol", [LF, CRLF], ids=["lf", "crlf"])
def test_the_bare_CR_stays_mid_line(tmp_path, eol):
    """It must remain a CHARACTER, not become a line break -- the peer-line split."""
    p = tmp_path / "lanes.md"
    p.write_bytes(_fixture(eol).encode("utf-8"))
    text, _ = io_mod.read_ledger(p)
    assert io_mod.lone_cr_count(text) == 1, "the bare CR was consumed by the read"
    joined = [l for l in text.split(LF) if "68 MB" in l]
    assert len(joined) == 1, "the line was split at the bare CR"
    assert "GOAL: MET" in joined[0], "the split halves are no longer one line"


def test_the_detected_eol_is_the_file_s_own(tmp_path):
    for eol, want in ((LF, LF), (CRLF, CRLF)):
        p = tmp_path / ("x" + ("crlf" if eol == CRLF else "lf") + ".md")
        p.write_bytes(_fixture(eol).encode("utf-8"))
        _, found = io_mod.read_ledger(p)
        assert found == want


def test_an_edit_does_not_churn_the_other_lines(tmp_path):
    """A one-line change must produce a one-line diff, not a whole-file rewrite."""
    p = tmp_path / "lanes.md"
    p.write_bytes(_fixture(CRLF).encode("utf-8"))
    before = p.read_bytes()
    text, eol = io_mod.read_ledger(p)
    io_mod.write_ledger(p, text.replace("- Files: scripts/x.py", "- Files: scripts/y.py"), eol)
    after = p.read_bytes()
    crlf_b = CRLF.encode("utf-8")
    assert after.count(crlf_b) == before.count(crlf_b), "line endings churned"
    assert io_mod.lone_cr_count(after.decode("utf-8")) == 1
    changed = [(a, b) for a, b in zip(before.split(crlf_b), after.split(crlf_b)) if a != b]
    assert len(changed) == 1, "more than one line changed"


def test_universal_newlines_is_what_broke_it(tmp_path):
    """The control that names the mechanism, so the lesson cannot be mis-read.

    This asserts the BAD behaviour of the API the tools used to call -- if this
    ever starts passing, Python changed and the docstring above needs revisiting.
    """
    p = tmp_path / "lanes.md"
    p.write_bytes(_fixture(LF).encode("utf-8"))
    naive = p.read_text(encoding="utf-8")
    assert io_mod.lone_cr_count(naive) == 0, "read_text no longer eats a lone CR"
    assert len([l for l in naive.split(LF) if "68 MB" in l]) == 1
    assert "GOAL: MET" not in [l for l in naive.split(LF) if "68 MB" in l][0], (
        "read_text no longer splits the line at the bare CR")
