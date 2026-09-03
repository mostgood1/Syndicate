"""Tests for `scripts/compact_state.py`.

REACHABILITY FIRST, then correctness. The repo's model-engine standard exists
because four features shipped inert in one session and every correctness test
passed on them. A verifier is exactly the kind of code that can be decoration:
if `verify()` cannot FAIL, the tool's whole promise ("nothing is lost") is
unfalsifiable. So each check gets a test that makes it fire, and the token
check gets one that establishes whether it is load-bearing at all.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("compact_state", ROOT / "scripts" / "compact_state.py")
cs = importlib.util.module_from_spec(spec)
sys.modules["compact_state"] = cs
spec.loader.exec_module(cs)


DOC = """# state

## [alpha] ALPHA SUBJECT

Live prose that must stay.

**THIS ENTIRE FINDING IS WRONG AND IS RETRACTED.** The body is kept below only
so the mistake is legible.

The dead body, with `sha1234abc` and 12,345 and 0.98765 in it.

More dead body.

## [beta] BETA SUBJECT

Untouched.
"""


def lines_of(text):
    return text.split("\n")


# --- structure ---------------------------------------------------------

def test_sections_finds_permissive_slugs():
    """The strict pattern in state_key_check.py misses uppercase/underscore
    slugs. This tool must see them or it cannot protect them."""
    doc = "## [layer2_board_display] X\n\n## [polymarket-price-gate-LIVE] Y\n"
    secs = cs.sections(lines_of(doc))
    assert [s[0] for s in secs] == ["layer2_board_display", "polymarket-price-gate-LIVE"]
    _stacked, _unkeyed, invisible = cs.coherence(lines_of(doc))
    assert sorted(invisible) == ["layer2_board_display", "polymarket-price-gate-LIVE"]


def test_coherence_detects_stacking():
    doc = "## [dup] ONE\n\ntext\n\n## [dup] TWO\n\ntext\n"
    stacked, _unkeyed, _inv = cs.coherence(lines_of(doc))
    assert "dup" in stacked


def test_coherence_detects_unkeyed():
    doc = "## NO SLUG HERE\n\ntext\n"
    _stacked, unkeyed, _inv = cs.coherence(lines_of(doc))
    assert len(unkeyed) == 1


# --- candidate selection ----------------------------------------------

def test_designating_marker_is_auto_and_plain_marker_is_manual():
    auto, manual = cs.candidates(lines_of(DOC))
    assert len(auto) == 1 and auto[0][1] == "alpha"
    assert manual == []


def test_correction_paragraph_is_never_auto():
    """The 10 real markers in state.md are corrections. Archiving one would
    file away the correction and leave the wrong claim -- the exact inversion
    this tool exists to avoid."""
    doc = ("## [x] X\n\n**RETRACTED: the entry that stood here said the fee was "
           "ZERO.** That was wrong.\n\nLive text after.\n")
    auto, manual = cs.candidates(lines_of(doc))
    assert auto == []
    assert len(manual) == 1


def test_pointer_makes_it_idempotent():
    """Second run must find nothing, or a re-run duplicates the archive."""
    doc = DOC.replace("More dead body.",
                      f"{cs.POINTER} `state_archive_x.md`)*")
    auto, _manual = cs.candidates(lines_of(doc))
    assert auto == []


# --- REACHABILITY of each verification check ---------------------------

def test_verify_passes_on_a_faithful_move():
    before = lines_of(DOC)
    after = [l for l in before if "dead body" not in l]
    moved = "\n".join(l for l in before if "dead body" in l)
    assert cs.verify(before, after, moved, "") == []


def test_verify_FIRES_on_a_lost_heading():
    before = lines_of(DOC)
    after = [l for l in before if not l.startswith("## [beta]")]
    assert any("heading" in b for b in cs.verify(before, after, "", ""))


def test_verify_FIRES_on_a_lost_line():
    before = lines_of(DOC)
    after = [l for l in before if "must stay" not in l]
    assert any("line(s) would be lost" in b for b in cs.verify(before, after, "", ""))


def test_verify_FIRES_on_stacking_introduced_by_the_move():
    before = lines_of(DOC)
    after = before + ["## [alpha] A SECOND ALPHA", ""]
    assert any("stacked" in b for b in cs.verify(before, after, "", ""))


def test_there_is_no_token_check_and_that_is_deliberate():
    """A token check WAS written here and removed when this very test could not
    make it fail: it searched for `moved`'s tokens in a haystack containing
    `moved`, so it could only pass. Kept as a regression guard -- if someone
    re-adds a token check, they must also make it reachable, or this fails.

    Line-conservation is exact for this tool because it moves text VERBATIM.
    The 2026-09-03 "line diff is the wrong instrument" rule governs REWORDED
    text, which this tool never produces."""
    before = lines_of(DOC)
    after = list(before)
    # tokens present in `moved` but nowhere in the surviving file or archive
    moved = "carries `sha1234abc` and 12,345"
    bad = cs.verify(before, after, moved, "")
    assert not any("token" in b for b in bad), (
        "a token check is back; give it a test that FAILS without it, "
        "then update this test"
    )
    assert not hasattr(cs, "TOKEN"), "dead TOKEN regex left behind"


# --- escort-mode guards ------------------------------------------------

def test_escort_refuses_ambiguous_marker(tmp_path, monkeypatch):
    doc = "## [x] X\n\nmarker here\n\nbody\n\nmarker here\n\nmore\n"
    p = tmp_path / "state.md"
    p.write_bytes(doc.encode())
    monkeypatch.setattr(cs, "STATE", p)
    assert cs.main(["--section", "x", "--after", "marker here"]) == 1


def test_escort_refuses_unknown_slug(tmp_path, monkeypatch):
    p = tmp_path / "state.md"
    p.write_bytes(DOC.encode())
    monkeypatch.setattr(cs, "STATE", p)
    assert cs.main(["--section", "nope", "--after", "x"]) == 1


def test_section_without_after_is_a_usage_error(tmp_path, monkeypatch):
    p = tmp_path / "state.md"
    p.write_bytes(DOC.encode())
    monkeypatch.setattr(cs, "STATE", p)
    assert cs.main(["--section", "alpha"]) == 2


# --- line endings ------------------------------------------------------

def test_crlf_is_preserved_through_apply(tmp_path, monkeypatch):
    """Editing state.md with text-mode I/O silently rewrites every line ending
    and git diff cannot show it. The tool must round-trip CRLF."""
    p = tmp_path / "state.md"
    p.write_bytes(DOC.replace("\n", "\r\n").encode())
    monkeypatch.setattr(cs, "STATE", p)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".syndicate").mkdir()
    assert cs.main(["--auto", "--apply"]) == 0
    out = p.read_bytes()
    assert b"\r\n" in out
    assert out.count(b"\n") == out.count(b"\r\n"), "mixed line endings after write"


def test_lf_file_stays_lf(tmp_path, monkeypatch):
    p = tmp_path / "state.md"
    p.write_bytes(DOC.encode())
    monkeypatch.setattr(cs, "STATE", p)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".syndicate").mkdir()
    assert cs.main(["--auto", "--apply"]) == 0
    assert b"\r" not in p.read_bytes()


def test_apply_moves_body_and_leaves_pointer(tmp_path, monkeypatch):
    p = tmp_path / "state.md"
    p.write_bytes(DOC.encode())
    monkeypatch.setattr(cs, "STATE", p)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".syndicate").mkdir()
    assert cs.main(["--auto", "--apply"]) == 0
    after = p.read_text(encoding="utf-8")
    assert cs.POINTER in after
    assert "The dead body" not in after
    assert "Live prose that must stay." in after
    # the correction itself must NOT have been archived
    assert "IS RETRACTED" in after
    arch = next(tmp_path.glob(".syndicate/state_archive_*.md"))
    assert "The dead body" in arch.read_text(encoding="utf-8")


def test_second_apply_is_a_noop(tmp_path, monkeypatch):
    p = tmp_path / "state.md"
    p.write_bytes(DOC.encode())
    monkeypatch.setattr(cs, "STATE", p)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".syndicate").mkdir()
    cs.main(["--auto", "--apply"])
    first = p.read_bytes()
    cs.main(["--auto", "--apply"])
    assert p.read_bytes() == first
