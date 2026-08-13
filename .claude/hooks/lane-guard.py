#!/usr/bin/env python3
"""PreToolUse hook - blocks edits to files claimed by another OPEN lane.

Lower value while running a single session; keep it wired for when a second
session comes back. Fails open on any parse error: a broken guard that blocks
all edits is worse than no guard.

Parsing notes (measured against the real .syndicate/lanes.md, 2026-08-13):
the claim block is NOT a single "- Files: a, b, c" line. 7 of 8 lanes write
"- Files (exclusive to this lane):" and then one nested bullet per path, with
the path in backticks. Deeper bullets under those hold symbol names and line
numbers, not paths, so a token only counts as a claim if it looks like a path
(has a separator, or a short file extension). Paths are normalised to forward
slashes because os.path.relpath returns backslashes on Windows and the ledger
is written with forward slashes.
"""
import json, os, re, sys

TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")
LANE_RE = re.compile(r"^###\s+(\S+)\s+—\s+(\w+)")
FILES_RE = re.compile(r"^\s*-\s*Files\b[^:]*:(.*)$")
FIELD_RE = re.compile(r"^-\s*\w")
PATHISH_RE = re.compile(r"^[\w.\-]+\.\w{1,5}$")


def _norm(p):
    return p.replace("\\", "/").strip("/")


def _paths_in(text):
    """Pull path-looking tokens out of a claim line."""
    out = []
    for tok in re.split(r"[,\s]+", text or ""):
        tok = tok.strip().strip("`<>*_()[].,;")
        if not tok or tok.lower() in ("n/a", "none", "fill", "in", "tbd"):
            continue
        if "/" in tok or "\\" in tok or PATHISH_RE.match(tok):
            norm = _norm(tok)
            if norm:
                out.append(norm)
    return out


def _claims(text):
    """Yield (slug, claimed_path) for every OPEN lane."""
    slug = None
    open_lane = False
    in_files = False
    for line in text.splitlines():
        m = LANE_RE.match(line)
        if m:
            slug, status = m.group(1), m.group(2)
            open_lane = status == "OPEN"
            in_files = False
            continue

        m = FILES_RE.match(line)
        if m:
            in_files = True
            if open_lane:
                for f in _paths_in(m.group(1)):
                    yield slug, f
            continue

        if in_files:
            stripped = line.strip()
            # A new top-level field ("- Goal:", "- Hypothesis:") or a blank
            # run ends the claim block; nested bullets continue it.
            if not stripped or (FIELD_RE.match(line) and not line[:1].isspace()):
                in_files = False
                continue
            if open_lane and stripped.startswith("-"):
                for f in _paths_in(stripped.lstrip("- ")):
                    yield slug, f


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0

    if payload.get("tool_name", "") not in TOOLS:
        return 0

    path = (payload.get("tool_input") or {}).get("file_path")
    if not path:
        return 0

    root = os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())
    lanes_file = os.path.join(root, ".syndicate", "lanes.md")
    if not os.path.exists(lanes_file):
        return 0

    try:
        rel = _norm(os.path.relpath(path, root))
    except Exception:
        return 0

    # Never guard the ledger or the harness config itself.
    if rel.startswith(".syndicate") or rel.startswith(".claude"):
        return 0

    current = ""
    marker = os.path.join(root, ".syndicate", ".current-lane")
    if os.path.exists(marker):
        try:
            with open(marker, encoding="utf-8") as fh:
                current = fh.read().strip()
        except Exception:
            current = ""

    try:
        with open(lanes_file, encoding="utf-8") as fh:
            text = fh.read()
    except Exception:
        return 0

    conflict = None
    try:
        for slug, f in _claims(text):
            if slug == current:
                continue
            if rel == f or rel.endswith("/" + f) or f.endswith("/" + rel):
                conflict = slug
    except Exception:
        return 0

    if conflict:
        sys.stderr.write(
            f"BLOCKED: {rel} is claimed by OPEN lane '{conflict}'.\n"
            f"Current lane: '{current or 'none'}'.\n"
            "Close or reassign that lane, or work a different file. "
            "Do not edit across lanes.\n"
        )
        return 2
    return 0


sys.exit(main())
