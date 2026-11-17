"""Lane `lane-claims-parse-memo` (2026-11-17): the faster forms give the SAME answers.

`check_lane_invariants.py` was the session-start hook's critical path. It took
2.1-5.6 s on the primary tree, and the new code takes 0.8-2.4 s. Three things
changed, and each one replaced code whose every line is a past incident, so each
is pinned here against a copy of the code it replaced:

  * `lane_claims._mask_backticked` -- a split/join instead of a character loop;
  * `lane_claims.sections_are_disjoint` -- parses each text ONCE (`_section_view`),
    where it used to walk all of `lanes.md` twice per call, 43 calls a run;
  * `check_lane_invariants.upstream_lane_slugs` -- one `git cat-file --batch`
    instead of four `git show` calls, and `heading_slugs` instead of the
    `(?m)^###` regex.

The reference copies below are verbatim from `689720915`, the commit before the
change. A difference from them is a regression, not a style choice.
"""
from __future__ import annotations

import importlib.util
import pathlib
import re
import shutil
import subprocess

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, _ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


lc = _load("lane_claims_parse_memo", ".claude/hooks/lane_claims.py")
cli = _load("check_lane_invariants_parse_memo", "scripts/check_lane_invariants.py")

LEDGERS = [_ROOT / ".syndicate" / n for n in
           ("lanes.md", "lanes_closed.md", "lanes_closed_archive.md", "lanes_history.md")]
LEDGERS = [p for p in LEDGERS if p.exists()]


# --- reference copies of the replaced code (689720915) ------------------------


def _reference_mask_backticked(line):
    out = []
    inside = False
    for ch in line:
        if ch == "`":
            inside = not inside
            out.append("`")
        else:
            out.append("\x00" if inside else ch)
    return "".join(out)


def _reference_heading_slugs(text):
    return re.findall(r"(?m)^###\s+([A-Za-z0-9._-]+)", text)


def _reference_upstream_lane_slugs(root, ref="origin/main"):
    slugs = set()
    answered = False
    for name in ("lanes.md", "lanes_closed.md", "lanes_closed_archive.md",
                 "lanes_history.md"):
        try:
            out = subprocess.run(
                ["git", "show", f"{ref}:.syndicate/{name}"],
                cwd=str(root.parent), capture_output=True, timeout=60,
            )
        except (OSError, ValueError, subprocess.SubprocessError):
            return None
        if out.returncode != 0:
            continue
        answered = True
        slugs |= set(re.findall(
            r"(?m)^###\s+([A-Za-z0-9._-]+)",
            out.stdout.decode("utf-8", "replace").lstrip("﻿"),
        ))
    return slugs if answered else None


# --- _mask_backticked ----------------------------------------------------------

MASK_CASES = [
    "", "`", "``", "```", "a`b`c", "a`bc", "`x`y`z", "no ticks at all",
    "é`ü`ß", "```a```", "\x00`\x00`", "- Files: `scripts/archive_released_lanes.py`, `b.py`",
    "**NOT claimed, deliberately:** `x.py`", "trailing `open quote never closes",
]


@pytest.mark.parametrize("line", MASK_CASES)
def test_mask_matches_the_character_loop(line):
    got = lc._mask_backticked(line)
    assert got == _reference_mask_backticked(line)
    assert len(got) == len(line)


@pytest.mark.skipif(not LEDGERS, reason="no ledger files in this tree")
def test_mask_matches_the_character_loop_on_every_ledger_line():
    lines = 0
    for path in LEDGERS:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            assert lc._mask_backticked(line) == _reference_mask_backticked(line), (path.name, line[:80])
            lines += 1
    assert lines > 1000  # the population was real


# --- sections_are_disjoint: one parse per text ---------------------------------

DOC = "docs/runbook.md"


def _lanes(*blocks):
    return "## OPEN\n\n" + "\n\n".join(blocks) + "\n"


def _lane(slug, files):
    return (f"### {slug} — OPEN — opened 2026-11-17 — session s-{slug}\n"
            f"- Goal: whatever\n- Files: {files}\n- Blocked by: none")


def test_parses_each_text_once_however_many_calls(monkeypatch):
    # A text no other test uses, so the cache cannot already hold it.
    text = _lanes(_lane("a-lane", f"{DOC} (watchdog section only)"),
                  _lane("b-lane", f"{DOC} (reload section only)"),
                  _lane("c-lane", "scripts/once_only_marker_7f3e.py"))
    calls = {"claims": 0, "sections": 0}
    real_claims, real_sections = lc._claims, lc._section_entries

    def counting_claims(t):
        calls["claims"] += 1
        return real_claims(t)

    def counting_sections(t):
        calls["sections"] += 1
        return real_sections(t)

    monkeypatch.setattr(lc, "_claims", counting_claims)
    monkeypatch.setattr(lc, "_section_entries", counting_sections)
    for _ in range(10):
        assert lc.sections_are_disjoint(text, "a-lane", DOC) == "watchdog section only"
        assert lc.sections_are_disjoint(text, "b-lane", DOC) == "reload section only"
    assert calls == {"claims": 1, "sections": 1}


def test_an_edited_text_is_parsed_afresh():
    """The cache key is the text, so a changed ledger cannot get a stale verdict."""
    disjoint = _lanes(_lane("a-lane", f"{DOC} (watchdog section only)"),
                      _lane("b-lane", f"{DOC} (reload section only)"))
    same = disjoint.replace("(reload section only)", "(watchdog section only)")
    undeclared = disjoint.replace(" (reload section only)", "")
    assert lc.sections_are_disjoint(disjoint, "a-lane", DOC) == "watchdog section only"
    assert lc.sections_are_disjoint(same, "a-lane", DOC) is None
    assert lc.sections_are_disjoint(undeclared, "a-lane", DOC) is None
    assert lc.sections_are_disjoint(disjoint, "a-lane", DOC) == "watchdog section only"


def test_the_cached_value_cannot_be_mutated_by_a_caller():
    text = _lanes(_lane("a-lane", f"{DOC} (watchdog section only)"))
    entries, holders = lc._section_view(text)
    assert isinstance(entries, tuple) and isinstance(holders, tuple)
    assert all(isinstance(e, tuple) for e in entries + holders)


@pytest.mark.skipif(not LEDGERS, reason="no lanes.md in this tree")
def test_same_answer_as_the_uncached_form_on_the_live_ledger():
    """Every holder of every claimed path: the exact calls `check_lane_invariants` makes."""
    text = LEDGERS[0].read_text(encoding="utf-8", errors="replace")
    entries, holders = list(lc._section_entries(text)), list(lc._claims(text))
    assert set(lc._section_view(text)[1]) == set(holders)
    asked = 0
    for path in sorted({f for _, f in holders}):
        for slug in sorted({s for s, f in holders if lc.matches(path, f)}):
            assert (lc.sections_are_disjoint(text, slug, path)
                    == lc.sections_are_disjoint_among(entries, holders, slug, path)), (slug, path)
            asked += 1
    assert asked > 50


# --- heading_slugs ---------------------------------------------------------------

HEADING_CASES = [
    "", "###", "### a", "x\n### b", "###\n### c", "### d\r\n### e", "text### g",
    "\n\n### h-i.j_k tail", "###   \n   foo", "### é", "a\x0b### z", "a\r### y",
    "### one\n### two\n#### three\n## four\n###five", "﻿### bom",
    "### a`b`\n###\t\ttabbed",
]


@pytest.mark.parametrize("text", HEADING_CASES)
def test_heading_slugs_equals_the_multiline_regex(text):
    assert cli.heading_slugs(text) == _reference_heading_slugs(text)


@pytest.mark.skipif(not LEDGERS, reason="no ledger files in this tree")
def test_heading_slugs_equals_the_multiline_regex_on_the_ledger_files():
    texts = [p.read_text(encoding="utf-8", errors="replace") for p in LEDGERS]
    for t in texts + ["".join(texts[1:])]:
        assert cli.heading_slugs(t) == _reference_heading_slugs(t)


# --- upstream_lane_slugs: one batch, the same answer -----------------------------

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git not on PATH")


def _fast_import(repo, refs):
    """One `git fast-import` writing one commit per ref, {ref: {name: bytes}}."""
    stream = b""
    for i, (ref, files) in enumerate(refs.items()):
        stream += (b"commit %s\ncommitter t <t@example.invalid> %d +0000\n"
                   b"data 1\nx\n" % (ref.encode(), 1700000000 + i))
        for name, body in files.items():
            stream += b"M 100644 inline .syndicate/%s\ndata %d\n%s\n" % (name.encode(), len(body), body)
    subprocess.run(["git", "-C", str(repo), "fast-import", "--quiet"], input=stream, check=True,
                   capture_output=True)


@pytest.fixture(scope="module")
def upstream_repo(tmp_path_factory):
    repo = tmp_path_factory.mktemp("upstream")
    subprocess.run(["git", "init", "-q", str(repo)], check=True, capture_output=True)
    _fast_import(repo, {
        "refs/remotes/origin/main": {
            "lanes.md": "## OPEN\n\n### live-one — OPEN\n".encode(),
            "lanes_closed.md": "### closed-one — CLOSED\n### closed-two — CLOSED\n".encode(),
            "lanes_closed_archive.md": "### archived-one — CLOSED\n".encode(),
            "lanes_history.md": "### trimmed-one — CLOSED\n".encode(),
        },
        "refs/heads/some-missing": {
            "lanes.md": "### only-lanes — OPEN\n".encode(),
            "lanes_history.md": "### only-history — CLOSED\n".encode(),
        },
        "refs/heads/bom-and-no-newline": {
            "lanes.md": "﻿### bom-first — OPEN".encode(),
            "lanes_closed.md": "prose\n###   spaced-out — CLOSED".encode(),
        },
        "refs/heads/no-ledgers": {"unrelated.md": b"### not-a-ledger\n"},
    })
    (repo / ".syndicate").mkdir()
    return repo / ".syndicate"


@needs_git
@pytest.mark.parametrize("ref", ["origin/main", "some-missing", "bom-and-no-newline",
                                 "no-ledgers", "no-such-ref"])
def test_upstream_slugs_match_four_git_shows(upstream_repo, ref):
    got = cli.upstream_lane_slugs(upstream_repo, ref)
    assert got == _reference_upstream_lane_slugs(upstream_repo, ref)


@needs_git
def test_upstream_slugs_reach_every_file_and_unknown_stays_none(upstream_repo):
    """off != on: the populated ref answers with every file's slugs, and the two
    unanswerable refs give None, never an empty set."""
    assert cli.upstream_lane_slugs(upstream_repo, "origin/main") == {
        "live-one", "closed-one", "closed-two", "archived-one", "trimmed-one"}
    assert cli.upstream_lane_slugs(upstream_repo, "no-ledgers") is None
    assert cli.upstream_lane_slugs(upstream_repo, "no-such-ref") is None


@needs_git
def test_upstream_outside_a_repo_is_none(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    (tmp_path / ".syndicate").mkdir()
    assert cli.upstream_lane_slugs(tmp_path / ".syndicate") is None
    assert _reference_upstream_lane_slugs(tmp_path / ".syndicate") is None
