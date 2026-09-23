"""`scripts/lane_open.py` emits a header the STRICT parser accepts.

The load-bearing assertion is not "there is an em-dash in the string" -- it is
that `lane_claims.LANE_RE` matches, because that is the regex `lane-guard` and
the session-start digest actually use. `ASCII_LANE_RE` would accept a hyphen
header too, so asserting "it parses" without saying WHICH parser would pass on
exactly the defect this tool exists to prevent.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
TOOL = REPO / "scripts" / "lane_open.py"
sys.path.insert(0, str(REPO / ".claude" / "hooks"))
import lane_claims  # noqa: E402

EM = "—"

LANES_FIXTURE = (
    "# Lanes\n"
    "\n"
    "## OPEN\n"
    "\n"
    f"### existing-lane {EM} OPEN {EM} opened 2026-09-01 {EM} session abc\n"
    "- Goal: something\n"
    "- Files: a/b.py\n"
    "- Blocked by: none\n"
    "\n"
    "## Archived lanes\n"
    "\n"
    f"### old-lane {EM} CLOSED 2026-08-01 {EM} opened 2026-07-01 {EM} session xyz\n"
    "- Goal: done\n"
)


def _lanes(tmp_path: pathlib.Path, text: str = LANES_FIXTURE) -> pathlib.Path:
    p = tmp_path / "lanes.md"
    p.write_text(text, encoding="utf-8")
    return p


def _run(lanes: pathlib.Path, *extra: str) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(TOOL), "--lanes", str(lanes), "--slug", "new-lane",
           "--goal", "a testable outcome", "--files", "scripts/x.py",
           "--session", "sess-1", "--date", "2026-09-23", "--no-marker", *extra]
    return subprocess.run(cmd, capture_output=True, text=True)


def _header(lanes: pathlib.Path, slug: str) -> str:
    for line in lanes.read_text(encoding="utf-8").split("\n"):
        if line.startswith(f"### {slug} "):
            return line
    raise AssertionError(f"no header for {slug}")


def test_header_matches_the_strict_parser(tmp_path):
    lanes = _lanes(tmp_path)
    assert _run(lanes).returncode == 0
    header = _header(lanes, "new-lane")
    assert lane_claims.LANE_RE.match(header), header
    assert EM in header


def test_header_is_not_the_ascii_hyphen_form(tmp_path):
    """The control. A hyphen header parses only via the fallback; ours must not."""
    lanes = _lanes(tmp_path)
    _run(lanes)
    header = _header(lanes, "new-lane")
    assert " - OPEN - " not in header
    # And prove the control is real: the hyphen form does match the fallback,
    # so this test would have caught the defect rather than passing vacuously.
    hyphen = "### slug - OPEN - opened 2026-09-23 - session s"
    assert lane_claims.ASCII_LANE_RE.match(hyphen)
    assert not lane_claims.LANE_RE.match(hyphen)


def test_claims_are_enforced_for_the_new_lane(tmp_path):
    lanes = _lanes(tmp_path)
    _run(lanes)
    claims = list(lane_claims._claims(lanes.read_text(encoding="utf-8")))
    assert ("new-lane", "scripts/x.py") in claims


def test_block_lands_inside_the_open_section_not_at_eof(tmp_path):
    """#466: a block below '## Archived lanes' stops being enforced silently."""
    lanes = _lanes(tmp_path)
    _run(lanes)
    text = lanes.read_text(encoding="utf-8")
    assert text.index("### new-lane ") < text.index("## Archived lanes")


def test_refuses_duplicate_slug(tmp_path):
    lanes = _lanes(tmp_path)
    r = subprocess.run(
        [sys.executable, str(TOOL), "--lanes", str(lanes), "--slug", "existing-lane",
         "--goal", "g", "--files", "f.py", "--session", "s", "--no-marker"],
        capture_output=True, text=True)
    assert r.returncode == 2
    assert "already exists" in r.stderr


def test_refuses_without_a_session(tmp_path):
    lanes = _lanes(tmp_path)
    r = subprocess.run(
        [sys.executable, str(TOOL), "--lanes", str(lanes), "--slug", "s2",
         "--goal", "g", "--files", "f.py", "--session", "", "--no-marker"],
        capture_output=True, text=True)
    assert r.returncode == 2


def test_refuses_when_there_is_no_open_section(tmp_path):
    lanes = _lanes(tmp_path, "# Lanes\n\n## Archived lanes\n\n### x " + EM + " CLOSED\n")
    r = _run(lanes)
    assert r.returncode != 0
    assert "## OPEN" in r.stderr


def test_line_endings_are_preserved(tmp_path):
    lanes = _lanes(tmp_path)
    lanes.write_bytes(LANES_FIXTURE.replace("\n", "\r\n").encode("utf-8"))
    _run(lanes)
    raw = lanes.read_bytes()
    assert b"\r\n" in raw
    assert raw.count(b"\n") == raw.count(b"\r\n"), "a bare LF was introduced"


def test_source_is_pure_ascii(tmp_path):
    """The tool must emit U+2014 without CONTAINING one.

    A literal em-dash in this source is one ASCII-fying editor, console
    re-encode or copy-paste away from becoming a hyphen -- which would make the
    fix silently reintroduce the defect it exists to prevent. `chr(0x2014)`
    cannot be damaged that way.
    """
    raw = TOOL.read_bytes()
    offenders = [(i, b) for i, b in enumerate(raw) if b > 127]
    assert not offenders, f"non-ASCII byte(s) in {TOOL.name}: {offenders[:5]}"


def test_dry_run_writes_nothing(tmp_path):
    lanes = _lanes(tmp_path)
    before = lanes.read_bytes()
    r = _run(lanes, "--dry-run")
    assert r.returncode == 0
    assert lanes.read_bytes() == before
    assert EM in r.stdout
