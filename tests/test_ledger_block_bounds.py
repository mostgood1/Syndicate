"""The lane-block boundary: level 1-3, not level-3-only, not any level.

Both wrong boundaries have been used in this repo, and each test below fails
under one of them. That is the point: the rule was written in prose on
2026-10-13 and broken by its author on 2026-10-14, so it is pinned here instead.

  * `### `-only  -- the LAST block in a file runs to EOF and swallows every
    trailing `## ` section. Cost: a lane close rewrote 765 lines as 7, deleting
    114,376 chars; a day later a harness read a 12-line block as 785 lines and
    called a correctly-archived block ALTERED.
  * any heading (`#{1,6}`) -- truncates a block that legitimately contains a
    `####` sub-heading. Measured on lanes_history.md: 26 of 887 archived blocks,
    one from 259 lines to 15.

And a third, found 2026-10-14 the same day `#{1,3}` shipped: a column-0
`# comment` INSIDE a ```fenced``` code block is byte-for-byte a level-1 heading.
Measured over 1,360 blocks in the three lane files -- 386 fenced lines, 1 false
boundary, cutting `soccer-projection-collapse` from 60 lines to 9. The level
rule alone cannot settle this, because a `## ` line in a sample would fool
`#{2,3}` the same way: the fence has to be tracked.

Note what the property test at the bottom did when the fix landed -- it FAILED,
naming that exact line, because it encoded "any `#{1,3}` line in a span is a
swallowed heading". A guard that asserts the defect is indistinguishable from a
guard that asserts the invariant until something changes underneath it.
"""
import pathlib
import re
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from ledger_io import block_bounds, block_spans, block_text  # noqa: E402

LF = chr(10)
EM = chr(8212)


def _doc(*lines):
    return LF.join(lines)


# the shape that bit twice: the block is LAST, with '## ' sections after it
LAST_BLOCK_DOC = _doc(
    "# lanes",
    "",
    "## OPEN",
    "",
    "### alpha-lane %s OPEN %s opened 2026-10-14" % (EM, EM),
    "- Goal: first",
    "- Files: a.py",
    "",
    "### omega-lane %s CLOSED %s opened 2026-10-14" % (EM, EM),
    "- Goal: last block in the file",
    "- Files: b.py",
    "",
    "## Archive pointers " + EM + " 2026-10-14",
    "- `gone-lane` archived to lanes_history.md",
    "",
    "## Archived lanes",
    "- a long tail of content that is NOT part of omega-lane",
    "- more of it",
)


def _end_by_h3_only(text, slug):
    """The WRONG boundary, for contrast: next '### ' or EOF."""
    lines = text.split(LF)
    i = next(k for k, l in enumerate(lines) if l.startswith("### " + slug + " "))
    return next((j for j in range(i + 1, len(lines)) if lines[j].startswith("### ")), len(lines))


def _end_by_any_heading(text, slug):
    """The OTHER wrong boundary: next heading of any level."""
    lines = text.split(LF)
    i = next(k for k, l in enumerate(lines) if l.startswith("### " + slug + " "))
    return next((j for j in range(i + 1, len(lines)) if re.match(r"^#{1,6} ", lines[j])), len(lines))


def test_the_last_block_in_the_file_stops_at_the_next_section():
    start, end = block_bounds(LAST_BLOCK_DOC, "omega-lane")
    body = block_text(LAST_BLOCK_DOC, "omega-lane").split(LF)
    assert len(body) == 4, body                     # header + 2 fields + blank
    assert "## Archive pointers" not in block_text(LAST_BLOCK_DOC, "omega-lane")
    assert "## Archived lanes" not in block_text(LAST_BLOCK_DOC, "omega-lane")
    # and the wrong boundary really would have swallowed the rest
    assert _end_by_h3_only(LAST_BLOCK_DOC, "omega-lane") == len(LAST_BLOCK_DOC.split(LF))
    assert end < _end_by_h3_only(LAST_BLOCK_DOC, "omega-lane")


def test_a_middle_block_stops_at_the_next_block():
    body = block_text(LAST_BLOCK_DOC, "alpha-lane").split(LF)
    assert body[0].startswith("### alpha-lane")
    assert "- Goal: first" in body
    assert not any(l.startswith("### omega-lane") for l in body)


def test_a_deeper_heading_inside_a_block_is_CONTENT_not_a_boundary():
    """The lanes_history.md shape: 26 of 887 blocks carry a '####' sub-heading."""
    doc = _doc(
        "## TRIMMED FROM lanes.md",
        "",
        "### kept-lane %s CLOSED" % EM,
        "- Goal: has a sub-heading",
        "#### sub-section inside the block",
        "- still the same block",
        "",
        "### next-lane %s CLOSED" % EM,
        "- Goal: other",
    )
    body = block_text(doc, "kept-lane")
    assert "#### sub-section inside the block" in body
    assert "- still the same block" in body
    assert "next-lane" not in body
    # the any-heading boundary would have cut it at the '####'
    assert _end_by_any_heading(doc, "kept-lane") < block_bounds(doc, "kept-lane")[1]


def test_an_absent_slug_raises_rather_than_returning_something():
    with pytest.raises(KeyError):
        block_bounds(LAST_BLOCK_DOC, "no-such-lane")


def test_a_duplicated_slug_refuses_and_names_both_lines():
    doc = _doc(
        "## OPEN",
        "### twice-lane %s OPEN" % EM,
        "- Goal: first copy",
        "### twice-lane %s OPEN" % EM,
        "- Goal: second copy",
    )
    assert len(block_spans(doc)["twice-lane"]) == 2
    with pytest.raises(ValueError) as e:
        block_bounds(doc, "twice-lane")
    msg = str(e.value)
    assert "twice-lane" in msg and "2 times" in msg
    assert "[2, 4]" in msg, msg          # 1-indexed line numbers of both copies


def test_bold_and_tab_headers_are_still_found():
    doc = _doc("### **bolded-lane** %s OPEN" % EM, "- Goal: x", "## next")
    assert "bolded-lane" in block_spans(doc)


@pytest.mark.parametrize("rel", [".syndicate/lanes.md", ".syndicate/lanes_history.md"])
def test_no_span_on_the_real_ledger_contains_a_section_heading(rel):
    """Property, not a count: peers change these files constantly."""
    p = ROOT / rel
    if not p.exists():
        pytest.skip("%s not in this checkout" % rel)
    text = p.read_bytes().decode("utf-8", "replace").replace(chr(13) + LF, LF)
    lines = text.split(LF)
    spans = block_spans(text)
    assert spans, "no blocks parsed out of %s" % rel
    fenced = _fenced_lines(lines)
    for slug, got in spans.items():
        for start, end in got:
            bad = [lines[i] for i in range(start + 1, end)
                   if re.match(r"^#{1,3} ", lines[i]) and i not in fenced]
            assert not bad, "%s block %s swallowed %r" % (rel, slug, bad[:2])


def _fenced_lines(lines):
    """Independent re-implementation, on purpose.

    Calling `ledger_io._fenced` here would make this test agree with the code by
    construction -- it would pass against a `_fenced` that returned every line.
    """
    inside, tok = set(), None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            mark = stripped[:3]
            if tok is None:
                tok = mark
            elif mark == tok:
                tok = None
            continue
        if tok is not None:
            inside.add(i)
    return inside


def test_a_hash_comment_in_a_fenced_block_is_not_a_boundary():
    """The 2026-10-14 case, in miniature: a file path in a ```python sample."""
    doc = _doc(
        "### fenced-lane %s OPEN" % EM,
        "- Goal: x",
        "```python",
        "# syndicate/features/shared/board_enrichment.py:678",
        "index = load_soccer_projections(roots, selected_date)",
        "```",
        "- Files: a.py",
        "## next section",
    )
    start, end = block_bounds(doc, "fenced-lane")
    assert (start, end) == (0, 7), (start, end)
    assert "- Files: a.py" in block_text(doc, "fenced-lane")


def test_a_hash_hash_comment_in_a_fence_is_not_a_boundary_either():
    """What `^#{2,3}` alone would still get wrong, so the fix is not level-tuning."""
    doc = _doc(
        "### other-lane %s OPEN" % EM,
        "~~~",
        "## a markdown sample inside a tilde fence",
        "~~~",
        "- Files: b.py",
        "### next-lane %s OPEN" % EM,
    )
    assert block_text(doc, "other-lane").splitlines()[-1] == "- Files: b.py"


def test_a_block_heading_inside_a_fence_does_not_open_a_block():
    doc = _doc(
        "### real-lane %s OPEN" % EM,
        "```",
        "### not-a-lane %s OPEN" % EM,
        "```",
        "- Files: c.py",
    )
    spans = block_spans(doc)
    assert sorted(spans) == ["real-lane"], sorted(spans)


def test_the_real_history_case_reads_its_full_length():
    """Anchored on content, not on a line count a peer's archive pass would move."""
    p = ROOT / ".syndicate/lanes_history.md"
    if not p.exists():
        pytest.skip("lanes_history.md not in this checkout")
    text = p.read_bytes().decode("utf-8", "replace").replace(chr(13) + LF, LF)
    got = block_spans(text).get("soccer-projection-collapse")
    if not got:
        pytest.skip("that block has since been removed from the archive")
    bodies = [LF.join(text.split(LF)[s:e]) for s, e in got]
    hit = [b for b in bodies if "board_enrichment.py:678" in b]
    assert hit, "no archived copy carries the fenced sample any more"
    # the sample is mid-block: text after it must still be inside the span
    assert any("Soccer shards by KICKOFF date" in b for b in hit)


def test_an_unclosed_fence_runs_long_not_short():
    """The safe direction: visible in a diff rather than a silent truncation."""
    doc = _doc(
        "### open-fence %s OPEN" % EM,
        "```python",
        "# a comment",
        "## another",
        "- Files: d.py",
    )
    start, end = block_bounds(doc, "open-fence")
    assert (start, end) == (0, 5), (start, end)
