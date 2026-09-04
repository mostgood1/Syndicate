"""What does `lane-guard` ACTUALLY claim, and is each claim a real file?

WHY A TOOL. Three sessions hand-rolled this check on 2026-08-31 and it went
wrong in three different ways, so the answer belongs in one place --
`pending_deploys.py`'s principle for this repo: "a second tool answering the
same question differently is worse than no second tool."

IT REUSES `lane-guard.py`'s OWN PARSER. A lookalike is what produced the wrong
answers: one hand-written extractor counted CLOSED lanes' historical `Files:`
paths as claims (they are not -- `_claims` yields for OPEN lanes only) and
reported 16 phantom losses; another stripped the leading dot exactly as the bug
under investigation did, and so could not see it.

WHY IMPORTING THE HOOK IS AWKWARD, and how this gets around it. `lane-guard.py`
is a PreToolUse hook: run it and it reads stdin and blocks, which reads as a
silent hang or an empty result. It also has a hyphen in its name, so it is not
importable. This loads it by AST, keeping only imports, constants and function
definitions -- everything up to `def main` is already free of top-level calls,
and filtering by node type means that stays true even if it changes.

TWO CHECKS, BECAUSE ONE MISSES HALF. Measured the same day:
  - `1/p`, `15.0`, `85.13` became claims when prose was written inside a
    `- Files:` block. Caught by "does this token look like a path".
  - `.syndicate/findings_x.md` was mangled to `syndicate/findings_x.md`, which
    LOOKS perfectly well-formed and could never match the file it named.
    Caught only by "does this path exist".
`check_lane_invariants` catches neither: it verifies each claim has exactly one
holder, which is true of a claim that guards nothing.

RUN IT FROM A TREE PINNED TO `origin/main`. Existence is checked against
`git ls-files`, and the shared primary checkout drifts behind -- it reports live
files as missing, which is the same stale-tree trap in the other direction.

    py -3 scripts/lane_claim_audit.py
    py -3 scripts/lane_claim_audit.py --json

Exit 0 = every claim is a plausible, existing path. 1 = at least one is not.
2 = could not read the ledger or the hook.
"""

from __future__ import annotations

import argparse
import ast
import json
import pathlib
import subprocess
import sys
import types

REPO = pathlib.Path(__file__).resolve().parents[1]
# REPOINTED 2026-09-03 from `lane-guard.py` to `lane_claims.py`. The parser
# moved into that shared module; the hook now merely imports it. Loading the
# HOOK here broke outright -- it does `sys.path.insert(0, os.path.dirname(
# os.path.abspath(__file__)))` at import, and an exec'd namespace has no
# `__file__`. `lane_claims.py` is a pure library with no `__file__`, no
# `sys.exit(main())` and no stdin read, so the neutralising hacks below are
# now redundant rather than load-bearing. Same parser either way: the hook
# imports these exact objects.
HOOK = REPO / ".claude" / "hooks" / "lane_claims.py"
LANES = REPO / ".syndicate" / "lanes.md"

# A claim should look like a repo-relative path with a real extension. Kept
# deliberately loose: the point is to reject prose, not to police naming.
_PLAUSIBLE_SUFFIXES = (
    ".py", ".md", ".html", ".css", ".js", ".json", ".csv", ".txt",
    ".ps1", ".sh", ".yaml", ".yml", ".toml", ".ini", ".sql", ".jsonl",
)


def load_guard():
    """`lane-guard.py`'s helpers, without running the hook.

    Executes only Import / Assign / FunctionDef / ClassDef nodes. Never reaches
    `main`, so stdin is never read and nothing blocks.
    """
    src = HOOK.read_text(encoding="utf-8")
    tree = ast.parse(src)
    keep = [
        n for n in tree.body
        if isinstance(n, (ast.Import, ast.ImportFrom, ast.Assign, ast.AnnAssign,
                          ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ]
    mod = types.ModuleType("lane_guard_loaded")
    mod.__dict__["__file__"] = str(HOOK)
    exec(compile(ast.Module(body=keep, type_ignores=[]), str(HOOK), "exec"), mod.__dict__)
    for required in ("_claims", "_paths_in"):
        if not hasattr(mod, required):
            raise RuntimeError("lane-guard.py has no %s -- parser changed" % required)
    return mod


def tracked_files():
    out = subprocess.run(["git", "-C", str(REPO), "ls-files"],
                         capture_output=True, text=True, encoding="utf-8")
    if out.returncode != 0:
        return None
    return set(out.stdout.split("\n"))


def audit():
    guard = load_guard()
    claims = sorted(set(guard._claims(LANES.read_text(encoding="utf-8"))))
    tracked = tracked_files()

    not_pathlike, missing = [], []
    for slug, path in claims:
        if not path.endswith(_PLAUSIBLE_SUFFIXES):
            not_pathlike.append({"lane": slug, "claim": path})
        elif tracked is not None and path not in tracked:
            missing.append({"lane": slug, "claim": path})
    return claims, not_pathlike, missing


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    try:
        claims, not_pathlike, missing = audit()
    except Exception as exc:
        print("cannot audit: %s: %s" % (type(exc).__name__, exc), file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps({"claims": len(claims),
                          "not_pathlike": not_pathlike,
                          "missing": missing}, indent=1, sort_keys=True))
    else:
        print("%d enforced claim(s) across %d OPEN lane(s)"
              % (len(claims), len({s for s, _ in claims})))
        if not_pathlike:
            print("\n%d claim(s) that do NOT look like a path -- prose read as a claim."
                  % len(not_pathlike))
            print("Move the explanation ABOVE the `- Files:` line; anything inside or")
            print("directly after it is parsed as a continuation and becomes a claim.")
            for row in not_pathlike:
                print("   %-32s %s" % (row["lane"], row["claim"]))
        if missing:
            print("\n%d claim(s) naming a path that is NOT in git -- guarding nothing."
                  % len(missing))
            print("Either the lane is stale, or the path was mangled on the way in.")
            for row in missing:
                print("   %-32s %s" % (row["lane"], row["claim"]))
        if not (not_pathlike or missing):
            print("\nevery claim is a plausible, existing path")

    return 1 if (not_pathlike or missing) else 0


if __name__ == "__main__":
    raise SystemExit(main())
