"""One slug, one OPEN lane, one home. The rule `lanes.md` relies on and nothing checks.

WHY THIS EXISTS. `lane-guard.py` answers "is this FILE claimed by an open lane"
and answers it well. Nobody answers "is the LANE LEDGER ITSELF coherent", and on
2026-08-18 it was not: 50 blocks across 24 slugs, 13 slugs declared more than
once, and five slugs simultaneously present in `lanes.md` and `lanes_closed.md`
-- a lane both open and closed, which has no answer to "who holds this file",
the one question lanes exist to answer.

The same day, a collapse moved 22 blocks to `lanes_history.md` and left two in
NEITHER file. With three possible homes (`lanes.md`, `lanes_closed.md`,
`lanes_history.md`) a block can fall between any two of them, and an append-only
ledger makes that deletion look exactly like a tidy in review.

IT REUSES `lane-guard.py`'s PARSER RATHER THAN WRITING A SECOND ONE. That hook
is what actually enforces claims, so a checker that parsed headers even slightly
differently would grade a file nobody is guarding. `pending_deploys.py` states
the principle for this repo: "a second tool answering the same question
differently is worse than no second tool." Its `OPEN_RE`/`LANE_RE` have already
been through three revisions against real headers -- `OPENED`/`REOPENED` must
not count, `DEPLOYED, MEASUREMENT OPEN` must -- and that history is not worth
re-earning here.

WHAT IT CHECKS
  1. DUPLICATE OPEN   one slug with two OPEN blocks. Two sessions can each read
                      themselves as the holder.
  2. OPEN AND CLOSED  the same slug OPEN and CLOSED inside `lanes.md`. Which is
                      current is unanswerable from the file.
  3. OPEN BUT FILED   OPEN in `lanes.md` while also present in `lanes_closed.md`.
  4. UNPARSEABLE      a `### ` header whose status `lane-guard.py` cannot read.
                      These are NOT guarded -- the file claims are invisible to
                      the hook -- which is worse than a lane being wrong.

EXIT CODES
  0  coherent            1  at least one of (1)-(3)            2  cannot read

    python scripts/lane_identity_check.py
    python scripts/lane_identity_check.py --json
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LANES = REPO_ROOT / ".syndicate" / "lanes.md"
CLOSED = REPO_ROOT / ".syndicate" / "lanes_closed.md"
HISTORY = REPO_ROOT / ".syndicate" / "lanes_history.md"
GUARD = REPO_ROOT / ".claude" / "hooks" / "lane-guard.py"


REQUIRED_ATTRS = ("HEADER_RE", "LANE_RE", "ASCII_LANE_RE", "OPEN_RE")


def _load_guard():
    """Import `lane-guard.py` for its header regexes. The hyphen blocks a plain import.

    IT ENDS IN A BARE `sys.exit(main())`, being a hook rather than a library, so
    importing it RUNS it: it reads an empty stdin, decides there is nothing to
    guard, and exits 0. The first version of this file swallowed that and printed
    NOTHING while exiting 0 -- a silent pass that looked exactly like a clean
    ledger. Catching SystemExit is safe because the regexes are module-level and
    defined long before that line.

    The assert is the part that matters: a success code is not evidence the code
    ran. If the exit happens EARLIER in future -- an import error, a guard added
    at the top -- the attributes are missing and this fails loudly instead of
    grading the ledger with a half-built parser.
    """
    spec = importlib.util.spec_from_file_location("lane_guard", GUARD)
    if spec is None or spec.loader is None:
        raise SystemExit(f"FATAL: cannot load {GUARD}")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except SystemExit:
        pass
    missing = [a for a in REQUIRED_ATTRS if not hasattr(module, a)]
    if missing:
        print(f"FATAL: {GUARD.name} loaded without {', '.join(missing)} -- "
              "its parser moved and this tool would grade nothing.", file=sys.stderr)
        raise SystemExit(2)
    return module


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        print(f"FATAL: cannot read {path}: {exc}", file=sys.stderr)
        raise SystemExit(2)


def blocks(guard, text):
    """Yield (slug, status_text, is_open) per '### ' header, guard's parser exactly."""
    for line in text.splitlines():
        if not guard.HEADER_RE.match(line):
            continue
        m = guard.LANE_RE.match(line) or guard.ASCII_LANE_RE.match(line)
        if m:
            yield m.group(1), m.group(2), bool(guard.OPEN_RE.search(m.group(2)))
        else:
            # Same branch lane-guard takes: a header it cannot parse claims
            # nothing, so its Files block is invisible to the guard.
            yield None, line, False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    guard = _load_guard()
    lanes_text = _read(LANES)

    open_blocks: dict[str, int] = {}
    closed_in_lanes: set[str] = set()
    all_slugs: set[str] = set()
    unparseable: list[str] = []

    for slug, status, is_open in blocks(guard, lanes_text):
        if slug is None:
            unparseable.append(status.strip()[:100])
            continue
        all_slugs.add(slug)
        if is_open:
            open_blocks[slug] = open_blocks.get(slug, 0) + 1
        elif "CLOSED" in status.upper():
            closed_in_lanes.add(slug)

    closed_blocks = list(blocks(guard, _read(CLOSED)))
    archived = {s for s, _, _ in closed_blocks if s}
    # PRESENCE in the archive is not a contradiction. A lane can legitimately be
    # closed, archived, and later RE-OPENED -- `live-game-line-projection` was --
    # and flagging that would mark a correct ledger dirty forever, which is how a
    # checker earns the reputation that gets it ignored. What is wrong is an
    # ARCHIVED block still asserting OPEN: then the archive claims a live lane.
    archived_open = {s for s, _, is_open in closed_blocks if s and is_open}
    in_history = {s for s, _, _ in blocks(guard, _read(HISTORY)) if s} if HISTORY.exists() else set()

    duplicate_open = sorted((s, n) for s, n in open_blocks.items() if n > 1)
    open_and_closed = sorted(set(open_blocks) & closed_in_lanes)
    open_but_filed = sorted(set(open_blocks) & archived_open)

    report = {
        "blocks": sum(1 for _ in blocks(guard, lanes_text)),
        "distinct_slugs": len(all_slugs),
        "open_lanes": len(open_blocks),
        "archived_slugs": len(archived),
        "history_slugs": len(in_history),
        "duplicate_open": duplicate_open,
        "open_and_closed_in_lanes_md": open_and_closed,
        "open_but_also_in_lanes_closed": open_but_filed,
        "unparseable_headers": unparseable,
    }
    failed = bool(duplicate_open or open_and_closed or open_but_filed)

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
        return 1 if failed else 0

    print(f"{report['blocks']} blocks / {report['distinct_slugs']} distinct slugs / "
          f"{report['open_lanes']} open lanes "
          f"({report['archived_slugs']} archived, {report['history_slugs']} in history)")

    if duplicate_open:
        print(f"\nDUPLICATE OPEN -- {len(duplicate_open)} slug(s) with more than one OPEN block.")
        print("Two sessions can each read themselves as the holder:")
        for slug, n in duplicate_open:
            print(f"  {slug}: {n} OPEN blocks")

    if open_and_closed:
        print(f"\nOPEN AND CLOSED -- {len(open_and_closed)} slug(s) both states in lanes.md.")
        print("Which one is current cannot be answered from the file:")
        for slug in open_and_closed:
            print(f"  {slug}")

    if open_but_filed:
        print(f"\nOPEN IN TWO FILES -- {len(open_but_filed)} slug(s) OPEN in lanes.md")
        print("while lanes_closed.md ALSO carries an OPEN block for them:")
        for slug in open_but_filed:
            print(f"  {slug}")

    if unparseable:
        print(f"\nNOT GUARDED -- {len(unparseable)} header(s) whose status lane-guard.py")
        print("cannot parse. Their Files blocks claim nothing and no hook sees them:")
        for header in unparseable[:10]:
            print(f"  {header}")
        if len(unparseable) > 10:
            print(f"  ... and {len(unparseable) - 10} more")

    if not failed and not unparseable:
        print("\ncoherent -- one slug, one OPEN lane, one home")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
