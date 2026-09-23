"""Write a lane block into `.syndicate/lanes.md` with the separator that PARSES.

WHY THIS EXISTS RATHER THAN A TEMPLATE IN THE SKILL.

`.claude/commands/lane.md` has always shown the header with U+2014, and sessions
keep writing ASCII hyphens anyway -- `### slug - OPEN - ...`. Measured 2026-09-23:
two lanes in nineteen hours (`tripwire-applog-page-cap`, opened `2d192e9a` 09:50,
repaired `3e39e88b` 10:38; `live-gameline-game-identity`, opened `5dd126e7` 09-22
16:53, repaired `60fd67a8` 09-23 11:01). A template cannot enforce a codepoint;
this can.

THE COST OF THE HYPHEN FORM, which is not cosmetic. `lane_claims.LANE_RE`
requires U+2014. Hyphen headers were once parsed by NOTHING, which is a silently
UNGUARDED lane -- measured 2026-08-17, one live lane with three unprotected
claimed files, five by day's end. `ASCII_LANE_RE` now parses them so the claims
ARE enforced, and `lane-guard` blocks the owning session until the separator is
fixed. But the session-start digest still will not list such a lane as OPEN, so
an arriving session sees no claim on those paths -- `lane-guard.py:152-155` says
exactly this.

AND THE REPAIR HAS A SECOND COST that is easy to miss: it is made in the PRIMARY,
SHARED tree (the one `lane-guard` reads) and then committed from a worktree, so
the primary tree keeps the repair as an uncommitted modification identical to
what is already upstream. That dirt aborts every later `git merge --ff-only`.
Measured 2026-09-23: two aborted fast-forwards, both from exactly this.

PLACEMENT IS THE OTHER HALF. A block appended at EOF lands BELOW
`## Archived lanes`, and `lane-guard` reads `lanes.md` and nothing else, so the
next archive pass moves it away and its claims stop being enforced SILENTLY
(`#466`; measured 2026-08-18, seven OPEN lanes sat inside archived sections,
three owned by running sessions). This inserts at the END of the `## OPEN`
section, never at EOF.

Usage:
    py -3 scripts/lane_open.py --slug <slug> --goal "<one testable outcome>" \
        --files "<explicit paths>" [--hypothesis ...] [--falsification ...] \
        [--verification ...] [--blocked-by none] [--dry-run]

It does NOT do the collision check (`lane.md` step 3) or read `learnings.md`
(step 4). Those are judgement, not formatting, and belong to the session.
"""

from __future__ import annotations

import argparse
import datetime
import os
import pathlib
import re
import sys

# The whole point of this file, and it is built from a CODEPOINT rather than a
# literal on purpose: this source stays pure ASCII, so no editor, console
# re-encoding, copy-paste or ASCII-fying tool can quietly turn the separator back
# into a hyphen -- the exact failure this file exists to prevent. `lane-guard`
# refuses to print a literal one for the same reason (`lane-guard.py:158-160`).
#
# This is not hypothetical. Writing it here as a literal U+2014 was the FIRST
# draft of this file, and `test_source_is_pure_ascii` exists because that draft
# would have been silently as fragile as the defect. Do not "simplify" it back.
EM = chr(0x2014)

REPO = pathlib.Path(__file__).resolve().parent.parent
LANES = REPO / ".syndicate" / "lanes.md"

OPEN_HEADING = re.compile(r"^##\s+OPEN\b", re.M)
ANY_H2 = re.compile(r"^##\s", re.M)


def _read(path: pathlib.Path) -> tuple[str, bool, str]:
    """Return (text, had_bom, newline) so the file is written back as found."""
    raw = path.read_bytes()
    had_bom = raw.startswith(b"\xef\xbb\xbf")
    if had_bom:
        raw = raw[3:]
    crlf = raw.count(b"\r\n")
    lf = raw.count(b"\n") - crlf
    return raw.decode("utf-8"), had_bom, ("\r\n" if crlf > lf else "\n")


def _write(path: pathlib.Path, text: str, had_bom: bool, newline: str) -> None:
    body = text.replace("\r\n", "\n").replace("\n", newline).encode("utf-8")
    path.write_bytes((b"\xef\xbb\xbf" if had_bom else b"") + body)


def build_block(slug: str, session: str, date: str, goal: str, files: str,
                hypothesis: str, falsification: str, verification: str,
                blocked_by: str) -> str:
    header = f"### {slug} {EM} OPEN {EM} opened {date} {EM} session {session}"
    return "\n".join([
        header,
        f"- Goal: {goal}",
        f"- Files: {files}",
        f"- Hypothesis: {hypothesis}",
        f"- Falsification test: {falsification}",
        f"- Verification: {verification}",
        f"- Blocked by: {blocked_by}",
        "",
    ])


def insert_into_open_section(text: str, block: str) -> str:
    """Put `block` at the END of the `## OPEN` section, never at EOF."""
    m = OPEN_HEADING.search(text)
    if not m:
        raise SystemExit("REFUSING: no '## OPEN' heading in lanes.md -- refusing to "
                         "guess placement. A block at EOF lands under '## Archived "
                         "lanes' and stops being enforced (#466).")
    nxt = ANY_H2.search(text, m.end())
    cut = nxt.start() if nxt else len(text)
    head, tail = text[:cut], text[cut:]
    if not head.endswith("\n"):
        head += "\n"
    if not head.endswith("\n\n"):
        head += "\n"
    return head + block + "\n" + tail


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--slug", required=True)
    p.add_argument("--goal", required=True, help="ONE testable outcome")
    p.add_argument("--files", required=True, help="explicit paths, comma separated")
    p.add_argument("--hypothesis", default="n/a")
    p.add_argument("--falsification", default="n/a")
    p.add_argument("--verification", default="")
    p.add_argument("--blocked-by", default="none")
    p.add_argument("--session", default=os.environ.get("CLAUDE_CODE_SESSION_ID", ""))
    p.add_argument("--date", default=datetime.date.today().isoformat())
    p.add_argument("--lanes", default=str(LANES), help="override for tests")
    p.add_argument("--no-marker", action="store_true",
                   help="skip writing the per-session lane marker")
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args()

    if not a.session:
        return _die("REFUSING: no session id. Pass --session, or set "
                    "CLAUDE_CODE_SESSION_ID. A block with no session cannot be "
                    "traced to an owner when the lane goes quiet.")
    if re.search(r"\s", a.slug):
        return _die(f"REFUSING: slug {a.slug!r} contains whitespace; the header "
                    "parser reads the slug as one token.")

    lanes_path = pathlib.Path(a.lanes)
    text, had_bom, newline = _read(lanes_path)
    flat = text.replace("\r\n", "\n")

    if re.search(rf"^###\s+{re.escape(a.slug)}\s", flat, re.M):
        return _die(f"REFUSING: a block for {a.slug!r} already exists in "
                    f"{lanes_path}. Editing an existing lane is not this tool's job.")

    block = build_block(a.slug, a.session, a.date, a.goal, a.files,
                        a.hypothesis, a.falsification, a.verification, a.blocked_by)
    new = insert_into_open_section(flat, block)

    # Prove what we are about to write actually parses, before writing it.
    ok, why = _verify(new, a.slug)
    if not ok:
        return _die(f"REFUSING: the block this tool built does not parse: {why}")

    if a.dry_run:
        sys.stdout.write(block)
        print(f"[dry-run] would insert into the '## OPEN' section of {lanes_path}")
        return 0

    _write(lanes_path, new, had_bom, newline)
    # Deliberately NOT printing the separator itself: this stdout is re-encoded
    # by the console, and it came back as U+FFFD the first time this line ran --
    # the same reason `lane-guard.py:158-160` refuses to print a literal one.
    print(f"opened lane {a.slug!r} in {lanes_path} "
          "(inside '## OPEN', U+2014 separators)")

    if not a.no_marker:
        # Per-session marker ONLY. The bare `.syndicate/.current-lane` is a single
        # shared slot and writing it makes every other session with no marker of
        # its own read as owning YOUR lane (`lane.md` step 6).
        marker = lanes_path.parent / f".current-lane.{a.session}"
        marker.write_text(a.slug, encoding="utf-8")
        print(f"marker written: {marker.name}")
    return 0


def _verify(new_text: str, slug: str) -> tuple[bool, str]:
    """Parse the result with lane-guard's OWN parser, not a local regex."""
    sys.path.insert(0, str(REPO / ".claude" / "hooks"))
    try:
        import lane_claims  # type: ignore
    except Exception as exc:  # pragma: no cover - the hook tree may be absent
        return True, f"(lane_claims unavailable: {exc}; skipped)"
    line = next((l for l in new_text.split("\n")
                 if l.startswith(f"### {slug} ")), "")
    if not line:
        return False, "header line not found after insertion"
    if not lane_claims.LANE_RE.match(line):
        return False, ("header does not match LANE_RE, which requires U+2014. "
                       f"Got: {line[:120]!r}")
    return True, ""


def _die(msg: str) -> int:
    sys.stderr.write(msg + "\n")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
