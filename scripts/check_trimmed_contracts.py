#!/usr/bin/env python3
"""Catch the one trim failure `trim_lane_narrative.py` says no check measures.

That tool's own docstring names it: a contract key whose content lives in INDENTED
CHILDREN can keep its parent line and lose every child, leaving "a contract that
promises a list and delivers nothing -- and every automated check passes: no claim
moves, nothing is orphaned by indentation, the claim set matches. **The damage is
to MEANING, which no check here measures.**"

It is measurable, just not from the after-state alone: you need the BEFORE. For
every `### <slug>` block in both files, for every kept contract key, compare how
many indented children it had before with how many it has now. A key that had
children and now has none is an EMPTY PROMISE and is reported. A key that never
had children is untouched and fine.

Also reports a key that lost SOME children, as a weaker signal to eye -- partial
loss is legitimate when the children were dated narrative, but worth seeing.

    py -3 scripts/check_trimmed_contracts.py <before.md> [<after.md>]

Default after-file is `.syndicate/lanes.md`. Exit 1 if any contract key became an
empty promise, 0 otherwise.
"""
from __future__ import annotations

import pathlib
import re
import sys

CONTRACT = re.compile(r"^\s*-\s*(Goal|Why|Files|Hypothesis|Falsification test|"
                      r"Verification|Blocked by|GOAL VERDICT)\b", re.I)
BLOCK_END = re.compile(r"^#{2,3}\s")


def indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def blocks(text: str) -> dict[str, list[str]]:
    lines = text.split("\n")
    out: dict[str, list[str]] = {}
    for i, line in enumerate(lines):
        if not line.startswith("### "):
            continue
        slug = line[4:].split(" ")[0].strip().rstrip("*")
        j = i + 1
        while j < len(lines) and not BLOCK_END.match(lines[j]):
            j += 1
        # a slug can legitimately appear more than once; concatenate its blocks
        out.setdefault(slug, []).extend(lines[i:j])
    return out


def contract_children(body: list[str]) -> dict[str, int]:
    """key-line -> number of lines indented deeper than it, before the next
    line at or above its own indent."""
    counts: dict[str, int] = {}
    for n, line in enumerate(body):
        if not CONTRACT.match(line):
            continue
        base = indent(line)
        kids = 0
        for later in body[n + 1:]:
            if not later.strip():
                continue
            if indent(later) <= base:
                break
            kids += 1
        # key by the line's own text so the same key appearing twice is distinct
        counts[f"{n}:{line.strip()[:90]}"] = kids
    return counts


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print(__doc__.strip().split("\n\n")[-2])
        return 2
    before = pathlib.Path(argv[0]).read_text(encoding="utf-8", errors="replace")
    after_path = pathlib.Path(argv[1]) if len(argv) > 1 else pathlib.Path(".syndicate/lanes.md")
    after = after_path.read_text(encoding="utf-8", errors="replace")

    b, a = blocks(before), blocks(after)
    empty_promises: list[tuple[str, str, int]] = []
    partial: list[tuple[str, str, int, int]] = []
    gone: list[str] = []

    for slug, body_b in b.items():
        body_a = a.get(slug)
        if body_a is None:
            gone.append(slug)          # archived wholesale; not this tool's concern
            continue
        cb, ca = contract_children(body_b), contract_children(body_a)
        # match keys by their TEXT, since line numbers move
        by_text_b: dict[str, int] = {}
        for k, v in cb.items():
            by_text_b[k.split(":", 1)[1]] = max(by_text_b.get(k.split(":", 1)[1], 0), v)
        by_text_a: dict[str, int] = {}
        for k, v in ca.items():
            by_text_a[k.split(":", 1)[1]] = max(by_text_a.get(k.split(":", 1)[1], 0), v)
        for text, kids_b in by_text_b.items():
            if kids_b == 0:
                continue
            kids_a = by_text_a.get(text)
            if kids_a is None:
                continue               # the key itself left; not an empty promise
            if kids_a == 0:
                empty_promises.append((slug, text, kids_b))
            elif kids_a < kids_b:
                partial.append((slug, text, kids_b, kids_a))

    print(f"  slugs compared: {len(set(b) & set(a))}   "
          f"slugs absent from the after-file: {len(gone)}")
    print(f"  contract keys that lost SOME children (eye these): {len(partial)}")
    for slug, text, kb, ka in partial[:12]:
        print(f"      {slug}: {text[:72]}  ({kb} -> {ka})")
    print()
    if empty_promises:
        print(f"  EMPTY PROMISES -- a contract key kept with ALL children gone: {len(empty_promises)}")
        for slug, text, kb in empty_promises:
            print(f"      {slug}: {text[:80]}  (had {kb} children, now 0)")
        return 1
    print("  EMPTY PROMISES: none. Every kept contract key that had children still has some.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
