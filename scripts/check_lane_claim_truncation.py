"""Which OPEN lanes claim files the guard does not actually enforce.

    py -3 scripts/check_lane_claim_truncation.py            # report + exit code
    py -3 scripts/check_lane_claim_truncation.py --all      # closed lanes too

WHAT THIS CATCHES, and why a lane cannot see it for itself.

`lane_claims._claimable_prefix` truncates a `- Files:` line at the first
disclaimer marker, and the cut is a PREFIX -- so every path listed AFTER the
marker is dropped from the claim map. For a prohibition ("no `render.yaml`")
that is exactly right. For a line that merely MENTIONS another lane, or uses a
mid-sentence negation, before continuing to list its own files, it silently
under-claims:

    - Files: `a.py` (the loop ONLY, no rate change), `b.py`, `c.py`
                                     ^ cuts here       b.py and c.py are LOST

The author sees a Files line naming three paths. Every other session, and both
guards, see one. Nothing reports the difference -- which is how the lane that
owns `render.yaml` came to hold none of its three files.

MEASURED 2026-09-24 on the live `lanes.md`: 18 Files lines lose a path, 17 of
them OPEN. `_DISCLAIMER_MARKERS` records its own blast radius as "4 lines out
of 2,186 and every one is a genuine disclaimer", and that is no longer true.

WHY THIS ONLY REPORTS. Loosening the cut would newly contest files across
seventeen lanes at once and could block sessions mid-work, and the marker list
is the product of three measured `render.yaml` incidents. `lane_claims`' own
comment says which direction to fail -- "a false contest is loud and gets
surfaced, an unclaimed file lets two lanes edit it silently" -- so this makes
the silent half loud and leaves the cut alone.

REAL PATHS ONLY IN THE EXIT CODE. `_paths_in` also picks up prose that merely
looks path-shaped (`Yes/No`, `2b/3`, `origin/main`). Those are reported under
a separate heading and do NOT fail the check: a checker that cries wolf on
prose gets ignored, and then the real losses go with it.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / ".syndicate").is_dir():
            return parent
    return here.parents[1]


def _tracked_paths(root: Path) -> set[str]:
    """Every tracked path, for deciding whether a dropped token is REAL.

    Falls back to an on-disk walk when git cannot answer, because a checker
    that silently reports nothing is worse than a slow one.
    """
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "ls-files"],
            capture_output=True, text=True, timeout=60, check=False,
        )
        if out.returncode == 0 and out.stdout.strip():
            paths = {line.strip() for line in out.stdout.splitlines() if line.strip()}
            # UNTRACKED-BUT-PRESENT COUNTS. A lane routinely claims a file it is
            # about to create ("(NEW)"), and treating that as prose would bin a
            # real loss as noise -- the under-report this check exists to stop.
            extra = subprocess.run(
                ["git", "-C", str(root), "ls-files", "--others", "--exclude-standard"],
                capture_output=True, text=True, timeout=60, check=False,
            )
            if extra.returncode == 0:
                paths |= {l.strip() for l in extra.stdout.splitlines() if l.strip()}
            return paths
    except Exception:
        pass
    return {
        str(p.relative_to(root)).replace("\\", "/")
        for p in root.rglob("*")
        if p.is_file() and ".git" not in p.parts
    }


def _resolves(token: str, tracked: set[str]) -> bool:
    """Is this dropped token a real repository path?

    Uses the SAME suffix rule `lane_claims.matches` enforces with, so a bare
    `check_lane_invariants.py` counts as real because that is exactly how the
    guard would have treated it had it survived the cut.

    TRAILING LEDGER PUNCTUATION IS STRIPPED. The ledger writes paths inside
    backticks and then punctuates around them, and the extractor can carry the
    tail along: `tests/test_poll_soccer_live_state.py`: arrived here as
    "tests/test_poll_soccer_live_state.py`:" and was binned as prose -- an
    under-report, which is the direction this whole check exists to stop.
    """
    t = token.strip().strip("`:,.;\"'()[]").strip()
    trailing_slash = t.endswith("/")
    t = t.strip("/")
    if not t:
        return False
    if t in tracked:
        return True
    if trailing_slash:
        return any(p.startswith(t + "/") for p in tracked)
    return any(p == t or p.endswith("/" + t) for p in tracked)


# A marker that NEGATES ("no `render.yaml`") means the cut is doing its job and
# the paths after it were never claimed. A marker that REFERENCES another lane's
# status ("released", "held by") usually sits mid-sentence with this lane's own
# files still to come. The two need different verdicts and only the text can
# settle it, so they are reported apart rather than scored the same.
_NEGATION_MARKERS = (", no ", ". no ", "never", "no deploy", "no production code",
                     "no code change", "not touch", "not touched",
                     # "**NOT claimed, deliberately:** `x.py`" puts the marker FIRST,
                     # so the claimable prefix is empty and `x.py` was never a claim.
                     # That is the 2026-08-15 incident the marker list exists to
                     # preserve, and reporting it as a defect is crying wolf on the
                     # machinery working. Still LISTED, just not failing.
                     "not claimed", "not taken")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--all", action="store_true", help="include CLOSED lanes in the report")
    ap.add_argument("--lanes", default=None, help="path to lanes.md (default: the repo's)")
    args = ap.parse_args()

    root = _repo_root()
    sys.path.insert(0, str(root / ".claude" / "hooks"))
    from lane_claims import claims_lost_to_disclaimer  # noqa: E402

    lanes_path = Path(args.lanes) if args.lanes else root / ".syndicate" / "lanes.md"
    text = lanes_path.read_text(encoding="utf-8", errors="replace")
    tracked = _tracked_paths(root)

    real: list[tuple[str, str, list[str]]] = []
    noise: list[tuple[str, str, list[str]]] = []
    for slug, _open_lane, marker, lost in claims_lost_to_disclaimer(text, open_only=not args.all):
        hits = [t for t in lost if _resolves(t, tracked)]
        misses = [t for t in lost if not _resolves(t, tracked)]
        if hits:
            real.append((slug or "<unnamed>", marker, hits))
        if misses:
            noise.append((slug or "<unnamed>", marker, misses))

    scope = "every lane" if args.all else "OPEN lanes"
    print(f"lane claim truncation, {scope}, {lanes_path}")
    print()

    likely = [r for r in real if r[1] not in _NEGATION_MARKERS]
    prohibitions = [r for r in real if r[1] in _NEGATION_MARKERS]

    if likely:
        print(f"UNENFORCED -- {len(likely)} lane(s) name a REAL path the guard does NOT hold,")
        print("cut at a marker that REFERENCES another lane rather than forbidding the file.")
        print("Every one of these is genuinely unenforced; whether that was INTENDED needs a")
        print("human to read the sentence, which is exactly what this list is for.")
        print()
        for slug, marker, hits in likely:
            print(f"  {slug}")
            print(f"      cut at {marker!r}; everything after it is dropped")
            for t in hits:
                print(f"      LOST  {t}")
        print()
        print("  FIX: rewrite the Files line so every path it claims comes BEFORE the")
        print("  disclaimer, or drop the disclaimer wording. The cut is deliberate and")
        print("  is not changing; see `lane_claims.claims_lost_to_disclaimer`.")
    else:
        print("No OPEN lane loses a real path to a reference-style marker.")

    if prohibitions:
        print()
        print(f"PROBABLY CORRECT -- {len(prohibitions)} lane(s) lost a path to a NEGATION")
        print("marker, which usually means the sentence FORBADE the file rather than claiming")
        print("it. Listed for completeness and NOT failing this check.")
        for slug, marker, hits in prohibitions:
            print(f"  {slug}: {', '.join(hits)}  (cut at {marker!r})")

    if noise:
        print()
        print(f"PROSE THAT LOOKS PATH-SHAPED -- {len(noise)} lane(s), NOT failing this check:")
        for slug, marker, misses in noise:
            print(f"  {slug}: {', '.join(misses[:4])}{' ...' if len(misses) > 4 else ''}  (cut at {marker!r})")

    return 1 if likely else 0


if __name__ == "__main__":
    raise SystemExit(main())
