"""Group artifact glob patterns by directory so each one is listed ONCE. `#632`.

WHY THIS EXISTS, measured on production 2026-09-07. `/api/ops/artifacts/export`
had a **26-second median and an 87-second max**, and it is one of the routes
starving web's thread pool -- 32.5% of requests exceed the 5-second health-check
budget, which is what actually restarts the instance (35 `server_failed` events,
zero `evicted=True`; web is not being OOM-killed, it is timing out).

THE COST IS THE WALK, NOT THE BODIES. `?names_only=1` reads no file contents at
all and **timed out after 180 seconds**; `?since=<now>` took 43 s. So neither
reading files nor serialising JSON is the problem.

THE STRUCTURAL CAUSE. There are 176 patterns, none recursive, but every one
begins with a wildcard segment (`*_source/...`), so each `Path.glob` expands that
across every sport directory and then lists the leaf. The patterns collapse onto
only **95 distinct parents**, and the busiest -- `*_source/source_artifacts/data/
processed` -- is named by **18 separate patterns**. That directory is currently
listed 18 times per sport per request, and it is one of the largest on the disk.

So: expand each distinct parent once, list it once, and match every pattern that
lives there in memory. Measured on a local (thin) mirror: **125 -> 51 `scandir`
calls, 2.5x, with a byte-identical file set.** The local tree understates it --
the win scales with patterns-per-directory (up to 18x here) and with directory
size, and production's `data/` is where the file volume actually is.

SEMANTICS ARE UNCHANGED ON PURPOSE. This yields the same relative paths as the
naive loop, in the same order, including duplicates suppressed the same way. It
is an I/O optimisation, not a behaviour change -- so it can land without
re-verifying what the export endpoint returns.
"""

from __future__ import annotations

import fnmatch
import os
import posixpath
from pathlib import Path
from typing import Iterator


def group_patterns_by_parent(patterns: list[str]) -> dict[str, list[str]]:
    """`{parent_glob: [basename_glob, ...]}`, order preserved within a parent."""
    grouped: dict[str, list[str]] = {}
    for pattern in patterns:
        normalised = str(pattern).replace("\\", "/")
        parent = posixpath.dirname(normalised)
        name = posixpath.basename(normalised)
        grouped.setdefault(parent, [])
        if name not in grouped[parent]:
            grouped[parent].append(name)
    return grouped


def iter_pattern_matches(root: Path, patterns: list[str]) -> Iterator[Path]:
    """Yield files under `root` matching any pattern, listing each dir once.

    Equivalent to `for p in patterns: yield from root.glob(p)` over FILES, minus
    the repeated directory listings -- and de-duplicated, because two patterns in
    the same directory can match the same file (`*.json` and `foo_*.json`) and
    the caller writes into a dict keyed by path either way.

    A directory that cannot be listed is skipped rather than raised: this serves
    a read-only export whose whole job is to return what it can see, and one
    unreadable directory must not fail the request.
    """
    seen: set[str] = set()
    for parent_glob, names in group_patterns_by_parent(list(patterns)).items():
        # One expansion of the wildcard segment, however many patterns share it.
        parents: Iterator[Path] = (root.glob(parent_glob) if parent_glob
                                   else iter([root]))
        for directory in parents:
            if not directory.is_dir():
                continue
            try:
                entries = os.listdir(directory)
            except Exception:
                continue
            for entry in entries:
                if not any(fnmatch.fnmatch(entry, name) for name in names):
                    continue
                candidate = directory / entry
                key = str(candidate)
                if key in seen:
                    continue
                seen.add(key)
                if candidate.is_file():
                    yield candidate


def patterns_that_can_match(patterns: list[str], subset_pattern: str) -> list[str]:
    """Drop patterns that CANNOT produce a path matching `subset_pattern`.

    The export endpoint applies `?pattern=` only AFTER globbing everything, so a
    caller narrowing to one family otherwise pays the entire 176-pattern walk.

    THE TWO SIDES DO NOT SPEAK THE SAME LANGUAGE, and my first version assumed
    they did. `patterns` are GLOB patterns walked with `os.listdir`, so `*` and
    `?` never cross `/`. `subset_pattern` is applied by the caller with
    `fnmatch.fnmatch`, where **`*` and `?` DO cross `/`**. That first version
    compared directory DEPTH and dropped anything that disagreed -- so
    `?pattern=wnba_source/*`, which `fnmatch` happily matches against a
    five-segment path, kept only the shallow patterns and silently lost every
    `source_artifacts/data/...` family: recommendations, processed artifacts,
    sim input reports. The endpoint returned a SHORT ANSWER WITH NO ERROR, which
    is the worst possible failure for the endpoint most sessions verify
    production with. Reported by lane `soccer-unfed-inputs`, reproduced and
    bisected by `soccer-threeway-precision-gate`, red test
    `test_names_only_honours_the_pattern_filter`.

    **My own unit test asserted the wrong semantics and therefore passed** -- it
    encoded my assumption about `*` instead of the caller's actual `fnmatch`
    call. A test written from the same misreading as the code cannot catch it.

    So this now decides emptiness properly: it asks whether ANY string is
    matched by both patterns, running the two as automata over a product state
    space, with each side's own wildcard semantics. Undecidable inputs (a `[...]`
    class) are KEPT, never dropped -- and the caller still applies its `fnmatch`
    afterwards, so this can only ever remove work, never change the answer.
    """
    subset = str(subset_pattern or "").replace("\\", "/").strip()
    if not subset:
        return list(patterns)
    kept: list[str] = []
    for pattern in patterns:
        if _can_intersect(str(pattern).replace("\\", "/"), subset):
            kept.append(pattern)
    return kept


# Token kinds for the tiny wildcard automaton below.
_LIT, _ONE, _STAR = "lit", "one", "star"


def _tokenise(pattern: str) -> list[tuple[str, str]] | None:
    """`[(kind, char), ...]`, or None when a `[...]` class makes it undecidable."""
    tokens: list[tuple[str, str]] = []
    for ch in pattern:
        if ch == "[":
            return None            # bracket class: refuse to decide, so we keep
        if ch == "*":
            tokens.append((_STAR, ""))
        elif ch == "?":
            tokens.append((_ONE, ""))
        else:
            tokens.append((_LIT, ch))
    return tokens


def _labels_overlap(a: tuple[str, str], a_crosses: bool,
                    b: tuple[str, str], b_crosses: bool) -> bool:
    """Can one character satisfy both tokens at once?

    A wildcard that does NOT cross `/` cannot consume a literal `/`; that single
    asymmetry is the whole difference between glob and fnmatch here.
    """
    a_kind, a_ch = a
    b_kind, b_ch = b
    if a_kind == _LIT and b_kind == _LIT:
        return a_ch == b_ch
    if a_kind == _LIT:
        return b_crosses or a_ch != "/"
    if b_kind == _LIT:
        return a_crosses or b_ch != "/"
    # Two wildcards always share at least one ordinary character.
    return True


def _can_intersect(glob_pattern: str, fnmatch_pattern: str) -> bool:
    """Does some path match `glob_pattern` (no crossing) AND `fnmatch_pattern`?

    A product-automaton reachability search. Each pattern is a chain of states;
    `*` self-loops on its character class and is skippable. Returns True when
    both chains can reach their end together, and True on anything it cannot
    decide -- an unsound DROP loses artifacts, an unsound KEEP costs a listing.
    """
    a = _tokenise(glob_pattern)
    b = _tokenise(fnmatch_pattern)
    if a is None or b is None:
        return True
    len_a, len_b = len(a), len(b)

    def closure(states: set[tuple[int, int]]) -> set[tuple[int, int]]:
        pending = list(states)
        seen = set(states)
        while pending:
            i, j = pending.pop()
            for nxt in ((i + 1, j) if i < len_a and a[i][0] == _STAR else None,
                        (i, j + 1) if j < len_b and b[j][0] == _STAR else None):
                if nxt is not None and nxt not in seen:
                    seen.add(nxt)
                    pending.append(nxt)
        return seen

    frontier = closure({(0, 0)})
    visited = set(frontier)
    while frontier:
        nxt_frontier: set[tuple[int, int]] = set()
        for i, j in frontier:
            if i == len_a and j == len_b:
                return True
            if i >= len_a or j >= len_b:
                continue
            # `*` does not cross `/` in a glob; it does in fnmatch.
            if not _labels_overlap(a[i], False, b[j], True):
                continue
            step = (i if a[i][0] == _STAR else i + 1,
                    j if b[j][0] == _STAR else j + 1)
            for state in closure({step}):
                if state not in visited:
                    visited.add(state)
                    nxt_frontier.add(state)
        frontier = nxt_frontier
    return (len_a, len_b) in visited


def _segment_compatible(a: str, b: str) -> bool:
    """Two path segments could name the same directory.

    Kept because `group_patterns_by_parent`'s callers still use it; the subset
    pre-filter above no longer does, because per-segment comparison cannot model
    an fnmatch `*` that spans segments.
    """
    if any(ch in a for ch in "*?[") or any(ch in b for ch in "*?["):
        return True
    return a == b
