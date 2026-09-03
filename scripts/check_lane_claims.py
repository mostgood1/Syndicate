#!/usr/bin/env python3
"""Does every lane claim in `lanes.md` actually NAME A FILE?

A claim that names a path the repo does not have is not a weak claim, it is a
claim that guards NOTHING -- `lane-guard` matches a claim against the edited
path, so a token that can never equal any real path can never block anyone.
The lane's owner reads their `Files:` block and believes those files are held.
Nothing reports otherwise.

WHERE THIS CAME FROM. `learnings.md` 2026-08-31 prescribed exactly this check
and it was never built:

    "Audit claims two ways, not one: reject tokens that do not look like paths
    (catches `1/p`, `15.0`, prose read as a claim), AND reject claims whose path
    is absent from `git ls-files` (catches this, and stale claims on deleted
    files). `check_lane_invariants` does neither -- it verifies that each claim
    has exactly one holder, which is true of a claim that guards nothing."

The entry that produced that rule was found the same way this script works: by
listing every enforced claim and asking whether the path EXISTS. 1 of 35 claims
did not. Measured again 2026-09-03: 8 of 44.

WHY IT IS A SEPARATE SCRIPT and not a predicate added to
`check_lane_invariants.py`, which is where it would otherwise belong: that file
is claimed by the OPEN lane `ncaaf-live-cadence`. Editing it would be the exact
cross-lane write this repo's guards exist to prevent, so the check lands here
instead. Fold it in when that lane closes.

TWO SEVERITIES, ON PURPOSE.

  BROKEN (exit 1) -- the claim names no file in the repo. Always wrong, always
  the owning lane's to fix, and it goes away when they fix it. That is what
  makes it safe to fail on: a check that can never go green is one people learn
  to scroll past, and this repo has lost guards that way.

  INERT (reported, exit 0) -- the claim names a real file that `lane-guard`
  EXEMPTS anyway, i.e. anything under `.syndicate/` or `.claude/`. Listing
  `.syndicate/state.md` in a Files block reads as protection and is not; the
  ledger is deliberately never lane-guarded because every session writes it.
  Reported so nobody relies on it, NOT failed, because these claims are
  legitimate as documentation of intent and are written constantly.

Run it directly for the detail. Fails open (exit 0) if git is unavailable or
the ledger cannot be read -- a checker that blocks a session because it could
not answer is worse than one that says nothing.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), ".claude", "hooks"))
try:
    from lane_claims import _claims, is_exempt
except Exception as exc:
    sys.stderr.write("check_lane_claims: cannot import the shared lane parser "
                     "(%s); not checking.\n" % exc)
    sys.exit(0)


def _tracked(root):
    """Every path git knows, plus a basename index for suffix matching."""
    try:
        out = subprocess.run(["git", "-C", root, "ls-files"],
                             capture_output=True, text=True, timeout=60)
    except Exception:
        return None, None
    if out.returncode != 0:
        return None, None
    paths, by_base = set(), {}
    for line in out.stdout.splitlines():
        p = line.strip()
        if p:
            paths.add(p)
            by_base.setdefault(p.rsplit("/", 1)[-1], []).append(p)
    return paths, by_base


def _resolves(claim, paths, by_base, root):
    """True when this claim can match a real path the way `lane-guard` matches.

    Deliberately the SAME suffix arms `lane_claims.matches` uses, so this
    script cannot call a claim broken that the guard would in fact enforce --
    a false BROKEN would send a lane owner to rewrite a working claim.
    """
    if claim in paths:
        return True
    if os.path.exists(os.path.join(root, *claim.split("/"))):
        return True  # untracked but real: a new file the lane is about to add
    base = claim.rsplit("/", 1)[-1]
    for p in by_base.get(base, ()):
        if p == claim or p.endswith("/" + claim) or claim.endswith("/" + p):
            return True
    return False


def _why(claim):
    """The shape of the breakage, because the fix differs by shape."""
    if "{" in claim or "}" in claim:
        return ("brace expansion -- the ledger was written with shell syntax "
                "(`dir/{a,b}`) and the parser reads it literally, one broken "
                "token per brace. Write the paths out in full.")
    if "*" in claim or "?" in claim:
        return ("a glob -- claims are matched literally, never by pattern, so "
                "this holds nothing. Name the files, or name the directory's "
                "real path.")
    if "`" in claim or ("/" not in claim and "." not in claim):
        return ("prose read as a path -- something in the Files block that "
                "looked path-shaped (a backticked symbol name, a bare word). "
                "Move the sentence out of the block, or mark it with a "
                "disclaimer the parser knows (`NOT claimed:`, "
                "`read-only reference:`).")
    return ("names no file in the repo. If it is a file the lane has not "
            "CREATED yet, that is fine and it will resolve the moment it "
            "exists -- but until then the claim holds nothing. Otherwise it is "
            "deleted, renamed, or a typo: drop the claim, or update it.")


def main():
    root = os.environ.get("CLAUDE_PROJECT_DIR") or os.path.dirname(HERE)
    lanes_file = os.path.join(root, ".syndicate", "lanes.md")
    try:
        with open(lanes_file, encoding="utf-8") as fh:
            text = fh.read()
    except Exception:
        return 0

    paths, by_base = _tracked(root)
    if paths is None:
        sys.stderr.write("check_lane_claims: git unavailable; not checking.\n")
        return 0

    try:
        claims = sorted(set(_claims(text)))
    except Exception:
        return 0

    # AN EMPTY CLAIM SET IS A FINDING, NOT A CLEAN BILL OF HEALTH.
    #
    # Measured 2026-09-03, and this check exists because it caught the author of
    # this file: a regeneration of the shared parser decoded `LANE_RE`'s em-dash
    # through the Windows locale codepage instead of UTF-8, so the header
    # pattern matched nothing. The live claim set went 50 -> 0 and lane-guard was
    # INERT -- every lane in the repo unguarded -- while this script printed
    # "[ok  ] all 0 lane claim(s) name a real, guardable file" and exited 0.
    #
    # That is the permissive-default failure exactly: "I parsed nothing" mapped
    # onto "nothing is wrong", and the one reading that could have caught the
    # outage was the reading that reported success. Zero claims while the file
    # plainly holds OPEN lanes means the PARSER is broken, not the ledger, and
    # it must be louder than a broken claim, not quieter.
    open_headers = 0
    for line in text.splitlines():
        if line.startswith("### ") and " OPEN" in line:
            open_headers += 1
    if not claims and open_headers:
        print("[FATAL] the parser found ZERO claims while lanes.md holds %d "
              "header(s) reading OPEN." % open_headers)
        print("        This is a PARSER failure, not a ledger failure, and while "
              "it lasts")
        print("        lane-guard enforces NOTHING -- every lane in the repo is "
              "unguarded and")
        print("        every guard downstream reads as satisfied.")
        print("        First thing to check: the em-dash. LANE_RE requires "
              "U+2014 (e2 80 94).")
        print("        Compare bytes, not glyphs:")
        print("            grep '^LANE_RE' .claude/hooks/lane_claims.py | xxd")
        print("        A cp1252 round-trip renders it 'c3 a2 e2 82 ac', which "
              "still LOOKS")
        print("        like a dash in most terminals and matches no header at "
              "all.")
        return 1

    broken, inert = [], []
    for slug, claim in claims:
        if not _resolves(claim, paths, by_base, root):
            broken.append((slug, claim))
        elif is_exempt(claim):
            inert.append((slug, claim))

    total = len(claims)
    if not broken and not inert:
        print("[ok  ] all %d lane claim(s) name a real, guardable file" % total)
        return 0

    if inert:
        print("[note] %d of %d claim(s) name a file lane-guard EXEMPTS, so they "
              "guard nothing:" % (len(inert), total))
        for slug, claim in inert:
            print("         %-52s (%s)" % (claim, slug))
        print("       .syndicate/ and .claude/ are never lane-guarded -- every "
              "session writes them.")
        print("       Fine as a statement of intent; just do not rely on it.")

    if broken:
        print()
        print("[BAD ] %d of %d claim(s) name NO FILE IN THE REPO. These guard "
              "nothing, and" % (len(broken), total))
        print("       their lane's owner has no way to tell from reading the "
              "ledger:")
        by_lane = {}
        for slug, claim in broken:
            by_lane.setdefault(slug, []).append(claim)
        for slug in sorted(by_lane):
            print()
            print("       %s" % slug)
            for claim in by_lane[slug]:
                print("         %s" % claim)
                print("           -> %s" % _why(claim))
        print()
        print("       Fix in .syndicate/lanes.md, in the owning lane's Files "
              "block. If a lane")
        print("       is not yours, tell its owner rather than editing across "
              "lanes.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
