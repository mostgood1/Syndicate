"""Did any lane lose its file protection to a past archive pass?

THE SIGNATURE. `lane-guard` reads `lanes.md` and nothing else. So a lane was
silently un-guarded exactly when a block that WAS OPEN AND HELD CLAIMS stopped
being visible in `lanes.md` while it was still open -- typically by being moved
to `lanes_closed.md` / `lanes_history.md`. The claim did not get released; it
stopped being enforced, with nothing reporting it.

METHOD. Walk every commit touching `lanes.md` in chronological order, compute
the claim set at each with `lane-guard.py`'s OWN `_claims()`, and diff
consecutive versions. For every (slug, path) that disappears, classify:

  RELEASED   the slug still has a block in lanes.md, no longer reading OPEN.
             Correct: someone closed or released the lane.
  REWORDED   the slug still has an OPEN block; only the Files line changed.
             Correct: a lane narrowed its own claims.
  ARCHIVED   the slug's block is GONE from lanes.md and appears as OPEN in
             lanes_closed.md or lanes_history.md at that same commit.
             *** THIS IS THE SILENT UN-GUARD ***
  VANISHED   the block is gone from lanes.md and is not OPEN in either archive.
             Also a loss of protection, cause unknown -- report separately.

Git is driven through subprocess with list args, never a shell string: Git Bash
mangles `rev:path` into `rev\path` on Windows and returns a confident wrong
answer, which is how three checks were misread earlier in this session.
"""
from __future__ import annotations

import pathlib
import re
import subprocess
import sys
import types

REPO = pathlib.Path(r"C:\Users\tempadmin\OneDrive\Coding\Syndicate")
LANES = ".syndicate/lanes.md"
ARCHIVES = (".syndicate/lanes_closed.md", ".syndicate/lanes_history.md")

HEADER_RE = re.compile(r"^###\s+(\S+)\s", re.M)
OPEN_RE = re.compile(r"\bOPEN\b")


def git(*args):
    r = subprocess.run(["git", "-C", str(REPO), *args],
                       capture_output=True, text=True, errors="replace")
    return r.stdout if r.returncode == 0 else None


def blob(sha, path):
    return git("show", f"{sha}:{path}")


def load_guard():
    src = (REPO / ".claude/hooks/lane-guard.py").read_text(encoding="utf-8")
    mod = types.ModuleType("lg")
    exec(compile(src.replace("sys.exit(main())", "pass"), "lg", "exec"), mod.__dict__)
    return mod


def open_slugs(text):
    """Slugs whose header reads OPEN, in any file."""
    out = set()
    for line in (text or "").splitlines():
        m = re.match(r"^###\s+(\S+)\s+[—-]\s*([^—-]*)", line)
        if m and OPEN_RE.search(m.group(2)):
            out.add(m.group(1))
    return out


def all_slugs(text):
    return set(HEADER_RE.findall(text or ""))


def main():
    g = load_guard()
    shas = (git("log", "--format=%H", "--reverse", "--", LANES) or "").split()
    print(f"walking {len(shas)} commits touching {LANES}\n", flush=True)

    prev_claims, prev_sha = None, None
    findings = []
    for n, sha in enumerate(shas, 1):
        text = blob(sha, LANES)
        if text is None:
            continue
        claims = set(g._claims(text))
        if prev_claims is not None:
            lost = prev_claims - claims
            if lost:
                slugs_now, open_now = all_slugs(text), open_slugs(text)
                arch_open = set()
                for a in ARCHIVES:
                    arch_open |= open_slugs(blob(sha, a))
                for slug in sorted({s for s, _ in lost}):
                    paths = sorted(p for s, p in lost if s == slug)
                    if slug in open_now:
                        verdict = "REWORDED"
                    elif slug in slugs_now:
                        verdict = "RELEASED"
                    elif slug in arch_open:
                        verdict = "ARCHIVED"      # the silent un-guard
                    else:
                        verdict = "VANISHED"
                    findings.append((sha, slug, verdict, paths))
        prev_claims, prev_sha = claims, sha
        if n % 50 == 0:
            print(f"  ...{n}/{len(shas)}", flush=True)

    print("\n" + "=" * 70)
    bad = [f for f in findings if f[2] in ("ARCHIVED", "VANISHED")]
    for verdict in ("ARCHIVED", "VANISHED", "RELEASED", "REWORDED"):
        rows = [f for f in findings if f[2] == verdict]
        print(f"{verdict:<10} {len(rows)}")
    print("=" * 70)

    if not bad:
        print("\nNO LANE WAS SILENTLY UN-GUARDED. Every claim that stopped being\n"
              "enforced belonged to a lane that was released, closed, or had\n"
              "narrowed its own Files line while staying visible in lanes.md.")
        return 0

    print(f"\n*** {len(bad)} EVENT(S) WHERE PROTECTION WAS LOST ***\n")
    for sha, slug, verdict, paths in bad:
        subj = (git("log", "-1", "--format=%s", sha) or "").strip()[:66]
        when = (git("log", "-1", "--format=%ad", "--date=short", sha) or "").strip()
        print(f"{verdict}  {sha[:8]}  {when}  {slug}")
        print(f"    commit: {subj}")
        for p in paths:
            print(f"    unguarded: {p}")
        print()
    return 1


if __name__ == "__main__":
    sys.exit(main())
