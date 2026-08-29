"""Release `lanes.md` file claims held by lanes whose owning session is GONE.

WHY THIS EXISTS. `lane-guard.py` enforces a lane's `- Files:` block against
every OTHER session, and it has no notion of whether the claiming session still
exists. Claims therefore outlive their owners: measured 2026-08-29, **26 OPEN
lanes held 107 claims while exactly 3 sessions were alive**, so ~24 lanes were
blocking live work on behalf of nobody. This is not theoretical -- lane
`live-venue-order-placement` records needing a USER OVERRIDE that same day to
take `venue_quote_adapters.py` off `kalshi-line-aware-rungs`, a lane whose
session was gone and whose header already SAID the files were free.

WHAT IT DOES NOT DO. It does not close lanes and it does not delete anything.
An UNOWNED lane is still a record of owed work -- several here carry a single
undischarged reading -- so the block stays, the paths stay, and only their
*enforceability* is dropped. The lane's next owner reclaims by striking the
release note, exactly as the ledger already does by hand.

HOW A CLAIM IS RELEASED. `lane-guard._claimable_prefix()` cuts a Files line at
the first disclaimer marker and reads paths only from what precedes it. So a
`released:` token inserted ahead of the path text on every line of the block
makes the whole block unclaimable while leaving it readable. That is the
ledger's own existing convention, not a new one -- "released" is in the hook's
`_DISCLAIMER_MARKERS` precisely because a lane wrote a release note by hand on
2026-08-19 and the hook mis-read it as a claim.

LIVENESS IS MEASURED, NOT ASSUMED. A session is live iff its Claude Code
transcript was written within `--stale-minutes`. On 2026-08-29 that break was
unambiguous: 4 transcripts inside 60s, the next 87 minutes back. Pass `--live`
explicitly to override. Sessions named in a header by a HUMAN NAME rather than
a uuid (`syndicate-27`, `soccer-sport-owner`) can never match a live id and are
always treated as gone -- which is correct: those naming schemes predate
per-session ids and every one of them is weeks stale.

    py -3 scripts/release_phantom_lane_claims.py                    # dry run
    py -3 scripts/release_phantom_lane_claims.py --apply

Exit 0 = clean (or nothing to do), 1 = verification refused the write, 2 = could
not read.

VERIFICATION RUNS AGAINST `lane-guard.py`'s OWN `_claims()`, never a
reimplementation. `check_lane_invariants.py` carries a simplified copy that
disagreed with the guard by 32 claims over the same file on 2026-08-18, and
`live-venue-order-placement` hit the same split again on 2026-08-29: "the
checker reported no violation while the guard refused the edit". Three
properties must hold before anything is written: released lanes yield ZERO
claims, every OTHER lane's claim set is unchanged, and every released path is
still findable in the new text.
"""
from __future__ import annotations

import argparse
import collections
import datetime
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
LANES = ROOT / ".syndicate" / "lanes.md"
TRANSCRIPTS = (
    pathlib.Path.home()
    / ".claude" / "projects" / "C--Users-tempadmin-OneDrive-Coding-Syndicate"
)
RELEASE_TOKEN = "released:"


def load_guard():
    """Exec `lane-guard.py` with its `sys.exit(main())` neutralised.

    The hook ends in a bare `sys.exit(main())`, so importing it kills the
    importing process with exit code 0 and no output -- documented in
    `check_lane_invariants.py` as having bitten two earlier attempts.
    """
    src = (ROOT / ".claude" / "hooks" / "lane-guard.py").read_text(encoding="utf-8")
    src = src.replace("sys.exit(main())", "pass")
    ns = {"__name__": "_lane_guard_loaded_not_run"}
    exec(compile(src, str(ROOT / ".claude/hooks/lane-guard.py"), "exec"), ns)
    return ns


def live_sessions(stale_minutes):
    """Session ids whose transcript was written within `stale_minutes`."""
    cutoff = time.time() - stale_minutes * 60
    out = []
    for p in TRANSCRIPTS.glob("*.jsonl"):
        try:
            if p.stat().st_mtime >= cutoff:
                out.append(p.stem)
        except OSError:
            continue
    return sorted(out)


def claim_map(guard, text):
    by = collections.defaultdict(set)
    for slug, path in guard["_claims"](text):
        by[slug].add(path)
    return by


def open_lane_headers(guard, text):
    """[(line_index, slug, header_line)] for every OPEN lane."""
    out = []
    for i, line in enumerate(text.splitlines()):
        if not guard["HEADER_RE"].match(line):
            continue
        m = guard["LANE_RE"].match(line) or guard["ASCII_LANE_RE"].match(line)
        if m and guard["OPEN_RE"].search(m.group(2)):
            out.append((i, m.group(1), line))
    return out


def release_block(guard, lines, start, note):
    """Insert the release token ahead of the path text on one Files block.

    Returns the number of lines changed. `start` is the index of the `- Files:`
    line; the block ends where `_claims()` ends it (blank line, or a new
    top-level field), so the bounds here are the guard's own, not a guess.
    Lines that already yield no paths are left alone, which makes this
    idempotent.
    """
    m = guard["FILES_RE"].match(lines[start])
    if not m:
        return 0

    # Walk the block FIRST and decide whether it claims anything at all. A
    # `- Files:` header whose paths all sit on continuation lines is the
    # commonest shape here, and inserting the note only when the header line
    # itself carried a path left those blocks marked but UNEXPLAINED -- a bare
    # `released:` with nothing saying who released it or why.
    targets = []
    if guard["_paths_in"](guard["_claimable_prefix"](m.group(1))):
        targets.append(start)
    i = start + 1
    while i < len(lines):
        line = lines[i]
        if guard["HEADER_RE"].match(line):
            break
        stripped = line.strip()
        if not stripped or (guard["FIELD_RE"].match(line) and not line[:1].isspace()):
            break
        if guard["_paths_in"](guard["_claimable_prefix"](stripped).lstrip("- ")):
            targets.append(i)
        i += 1
    if not targets:
        return 0

    # Rewrite back-to-front so earlier indices stay valid.
    for idx in reversed(targets):
        if idx == start:
            head_len = len(lines[idx]) - len(m.group(1))
            lines[idx] = (lines[idx][:head_len] + " " + RELEASE_TOKEN
                          + lines[idx][head_len:])
        else:
            indent = len(lines[idx]) - len(lines[idx].lstrip())
            lines[idx] = lines[idx][:indent] + RELEASE_TOKEN + " " + lines[idx][indent:]
    # The note is its own line so it reads as a note, never as an interjection
    # in the middle of a wrapped `Files (collision-checked ...)` header. It is
    # indented, non-empty and not a top-level field, so it does not end the
    # block; it contains "RELEASED", so it claims nothing itself.
    lines.insert(start + 1, "  " + note)
    return len(targets)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--stale-minutes", type=float, default=60.0)
    ap.add_argument("--live", action="append", default=[],
                    help="session id to treat as live (repeatable); overrides mtime")
    ap.add_argument("--path", default=str(LANES))
    args = ap.parse_args()

    lanes_path = pathlib.Path(args.path)
    try:
        text = lanes_path.read_text(encoding="utf-8")
    except OSError as exc:
        print("could not read {}: {}".format(lanes_path, exc))
        return 2
    guard = load_guard()

    live = args.live or live_sessions(args.stale_minutes)
    source = "explicit" if args.live else "<{:g}min".format(args.stale_minutes)
    print("live sessions ({}):".format(source))
    for s in live:
        print("  " + s)

    before = claim_map(guard, text)
    headers = open_lane_headers(guard, text)
    phantom = [(i, slug, h) for i, slug, h in headers
               if not any(s in h for s in live) and before.get(slug)]
    keep = [slug for _, slug, h in headers if any(s in h for s in live)]

    print("\n{} OPEN lanes, {} claims".format(
        len(headers), sum(len(v) for v in before.values())))
    print("LIVE-OWNED (untouched): " + (", ".join(keep) or "none"))
    print("PHANTOM (claims to release): {}\n".format(len(phantom)))

    today = datetime.date.today().isoformat()
    note = ("**CLAIMS RELEASED {} — phantom sweep, the owning session is gone. "
            "The paths in this block are a RECORD, not a claim. A lane that "
            "resumes this work reclaims them by striking this note and the "
            "`released:` tokens.**".format(today))

    lines = text.splitlines()
    total = 0
    for _, slug, _ in phantom:
        print("  {:44} {:>3} claims".format(slug, len(before[slug])))
    # REVERSE ORDER, because `release_block` inserts the note line and every
    # later header index recorded above would otherwise slide by one per lane
    # touched -- 21 lanes here, so the last block would be read ~21 lines off
    # its own header and the rewrite would land in the wrong lane.
    for i, slug, _ in sorted(phantom, key=lambda r: -r[0]):
        j = i + 1
        while j < len(lines) and not guard["HEADER_RE"].match(lines[j]):
            if guard["FILES_RE"].match(lines[j]):
                marked = release_block(guard, lines, j, note)
                total += marked
                if marked:
                    j += 1  # step over the note line just inserted
            j += 1

    new = "\n".join(lines) + ("\n" if text.endswith("\n") else "")
    after = claim_map(guard, new)

    # --- verification, all three properties, before any write ---
    ok = True
    still = {s: sorted(after.get(s, ())) for _, s, _ in phantom if after.get(s)}
    if still:
        ok = False
        print("\nREFUSED: these lanes still hold claims after the rewrite:")
        for s, v in still.items():
            print("  {}: {}".format(s, v))
    for slug in keep:
        if before.get(slug, set()) != after.get(slug, set()):
            ok = False
            print("\nREFUSED: live lane '{}' claim set CHANGED {} -> {}".format(
                slug, sorted(before.get(slug, ())), sorted(after.get(slug, ()))))
    for _, slug, _ in phantom:
        for p in before[slug]:
            if p.rsplit("/", 1)[-1] not in new:
                ok = False
                print("\nREFUSED: released path vanished from the file: " + p)
    # NOT a line-count check: the note lines make the count grow by design. The
    # property that matters is that nothing was LOST, so every original line
    # must still be present -- modulo the release token this tool inserts.
    new_lines = set(lines)
    for original in text.splitlines():
        if original in new_lines:
            continue
        stripped = original.strip()
        if any(stripped in ln.replace(RELEASE_TOKEN + " ", "").replace(
                " " + RELEASE_TOKEN, "") for ln in lines):
            continue
        ok = False
        print("\nREFUSED: line lost from the ledger: " + original[:120])

    released = sum(len(before[s]) for _, s, _ in phantom)
    print("\n{} line(s) marked, {} claim(s) released, {} claim(s) remain".format(
        total, released, sum(len(v) for v in after.values())))
    if not ok:
        return 1
    if not args.apply:
        print("DRY RUN — pass --apply to write")
        return 0
    lanes_path.write_text(new, encoding="utf-8")
    print("WROTE " + str(lanes_path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
