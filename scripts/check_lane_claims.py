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

FOUR SEVERITIES, AND THE SPLIT BETWEEN THE FIRST TWO IS THE WHOLE DESIGN.

The first version failed on every claim that named no file -- all nine it found
on the live ledger. Session c38d3e5c pointed out that three of those needed no
action from anyone, and this runs at EVERY SESSION START.
`check_lane_invariants.py` set the precedent in its own docstring: its phantom
scan is a HINT that never fails, because a check that cries wolf gets ignored.

So the question is not "does this path exist" but **"can this token EVER
resolve"**:

  BROKEN (exit 1) -- structurally impossible, or a typo. A brace list, a glob,
  or prose can never match however the repo changes, because claims are
  compared literally. A well-formed path that is absent ALSO fails when a
  close-named tracked file exists, because that is a typo -- and the message
  names the neighbour. The worked example is `ncaaf-live-cadence` claiming
  `tests/test_ncaaf_live_autorun.py` while the file it created was
  `tests/test_ncaaf_lines_autorun.py`.

  NOT WRITTEN YET (reported, exit 0) -- a well-formed path, absent, with
  nothing close to it. A lane legitimately claims a file it is about to create,
  and such a claim starts guarding the moment the file lands. Reported so it is
  visible, never failed, because failing on it is the wolf-crying case.

  NEAR-MISS HEADER (exit 1) -- the block declares files, but its header status
  is REOPENED/OPENED rather than a standalone OPEN, so `\\bOPEN\\b` rejects it
  and NONE of its claims reaches any claim set. Same outcome as BROKEN (files
  declared, nothing enforced) reached a different way, and invisible to every
  set-comparison in the repo -- `trim_lane_blocks.py` verifies a trim by
  recomputing the claim set, so it reads these blocks as claim-free.

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
import difflib
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), ".claude", "hooks"))
try:
    from lane_claims import (
        ASCII_LANE_RE,
        FIELD_RE,
        FILES_RE,
        HEADER_RE,
        LANE_RE,
        OPEN_RE,
        _claimable_prefix,
        _claims,
        _paths_in,
        is_exempt,
    )
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


def _near_miss_open(text):
    """Blocks that DECLARE files under a header that is not quite OPEN.

    Returns [(slug, status, [paths])].

    THE FAILURE THIS CATCHES, found 2026-09-03 by session c38d3e5c: a lane
    relabelled its header to `**REOPENED 2026-09-03 for the READ side**`.
    `OPEN_RE` is `\\bOPEN\\b`, which correctly rejects REOPENED -- that
    strictness is deliberate and documented (the session-start hook once counted
    "NO LANE WAS EVER OPENED" as an open lane). But the lane still declared SIX
    files plus a function-scoped claim, and NONE of them entered any claim set.
    `lane-guard` had not enforced them since the relabel, and nothing said so.

    IT DEFEATS EVERY SET-COMPARISON WE HAVE. `trim_lane_blocks.py` verifies a
    trim by recomputing the claim set and asserting it is unchanged -- so it
    happily moved that block out of `lanes.md` and reported "claims unchanged",
    because those claims were never counted. A set comparison cannot protect a
    claim it never saw.

    Deliberately NARROW: only headers whose status CONTAINS "OPEN" but does not
    match it as a standalone word. That is the near-miss class -- REOPENED,
    OPENED -- where the author plainly meant the lane to be live. A CLOSED lane
    with a Files block is a normal historical record and is not reported.
    """
    out = []
    slug = status = None
    near = False
    in_files = False
    paths = []

    def flush():
        if near and slug and paths:
            out.append((slug, status.strip(), sorted(set(paths))))

    for line in text.splitlines():
        if HEADER_RE.match(line):
            flush()
            m = LANE_RE.match(line) or ASCII_LANE_RE.match(line)
            if m:
                slug, status = m.group(1), m.group(2)
                near = ("OPEN" in status.upper()) and not OPEN_RE.search(status)
            else:
                slug = status = None
                near = False
            in_files, paths = False, []
            continue
        if not near:
            continue
        m = FILES_RE.match(line)
        if m:
            in_files = True
            paths += _paths_in(_claimable_prefix(m.group(1)))
            continue
        if in_files:
            stripped = line.strip()
            if not stripped or (FIELD_RE.match(line) and not line[:1].isspace()):
                in_files = False
                continue
            paths += _paths_in(_claimable_prefix(stripped).lstrip("- "))
    flush()
    return out


def _impossible(claim):
    """True when this token can NEVER resolve to a path, however the repo changes.

    THE DISCRIMINATOR IS NOT "DOES THE PATH EXIST", IT IS "CAN IT EVER". Raised
    2026-09-03 by session c38d3e5c against the first version, which failed on all
    nine broken shapes: three of them needed no action from anyone, and this
    check runs at every session start. `check_lane_invariants.py` set the
    precedent in its own docstring -- its phantom scan is a HINT that never
    fails, because a check that cries wolf gets ignored, and this repo has lost
    guards that way.

    Brace lists, globs and prose are structurally impossible: no file will ever
    be created that makes `scripts/{build_wnba_recon` or
    `live_player_box_*.json` match, because claims are compared literally. Those
    are defects today and tomorrow. A well-formed path that is merely ABSENT is
    ambiguous -- a lane legitimately claims a file it is about to create -- and
    is handled by `_near_miss` instead.
    """
    return ("{" in claim or "}" in claim or "*" in claim or "?" in claim
            or "`" in claim or ("/" not in claim and "." not in claim))


def _near_miss(claim, by_base):
    """A tracked file this claim was probably MEANT to name, or None.

    This is what keeps the severity split from being too blunt. Demoting every
    absent-but-well-formed path to a warning would have let through the worked
    example this repo already paid for: `ncaaf-live-cadence` claimed
    `tests/test_ncaaf_live_autorun.py` while the file it created was
    `tests/test_ncaaf_lines_autorun.py` (live -> lines). That is a typo, it can
    never self-resolve, and the lane could not tell from reading the ledger.

    So an absent path FAILS when a near neighbour exists (and the message names
    it), and only REPORTS when nothing close is there -- which is the shape of a
    file genuinely not written yet. Matching is on the BASENAME, since that is
    where these typos land and a directory rename is a different animal.
    """
    base = claim.rsplit("/", 1)[-1]
    if not base:
        return None
    close = difflib.get_close_matches(base, list(by_base), n=1, cutoff=0.85)
    if not close or close[0] == base:
        return None
    for p in by_base[close[0]]:
        # Prefer a neighbour sitting in the same directory as the claim.
        if p.rsplit("/", 1)[0] == claim.rsplit("/", 1)[0]:
            return p
    return by_base[close[0]][0]


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

    near_headers = _near_miss_open(text)

    broken, unwritten, inert = [], [], []
    for slug, claim in claims:
        if not _resolves(claim, paths, by_base, root):
            neighbour = _near_miss(claim, by_base)
            if _impossible(claim) or neighbour:
                broken.append((slug, claim, neighbour))
            else:
                unwritten.append((slug, claim))
        elif is_exempt(claim):
            inert.append((slug, claim))

    total = len(claims)
    if not broken and not unwritten and not inert and not near_headers:
        print("[ok  ] all %d lane claim(s) name a real, guardable file" % total)
        return 0

    if near_headers:
        print("[BAD ] %d block(s) DECLARE files under a header that is not OPEN, so "
              "none of" % len(near_headers))
        print("       those claims is in any claim set and lane-guard does not "
              "enforce them:")
        for slug, status, declared in near_headers:
            print()
            print("       %s   header status: %s" % (slug, status[:70]))
            for p in declared:
                print("         %s" % p)
        print()
        print("       `OPEN_RE` is \\bOPEN\\b, which rejects REOPENED and OPENED on "
              "purpose --")
        print("       the loose version once counted \"NO LANE WAS EVER OPENED\" as "
              "open. So the")
        print("       fix belongs in the HEADER, not the regex: give the status a "
              "standalone")
        print("       OPEN token (e.g. `OPEN - REOPENED 2026-09-03 for ...`). If "
              "the lane is")
        print("       not yours, tell its owner -- this is silent for them too.")
        print("       NOTE: a set-comparison cannot catch this. trim_lane_blocks "
              "verifies by")
        print("       recomputing the claim set, so it reads these blocks as "
              "claim-free and")
        print("       will move them out of lanes.md reporting \"claims "
              "unchanged\".")

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
        for slug, claim, neighbour in broken:
            by_lane.setdefault(slug, []).append((claim, neighbour))
        for slug in sorted(by_lane):
            print()
            print("       %s" % slug)
            for claim, neighbour in by_lane[slug]:
                print("         %s" % claim)
                if neighbour:
                    print("           -> almost certainly a TYPO for `%s`, which exists."
                          % neighbour)
                else:
                    print("           -> %s" % _why(claim))
        print()
        print("       Fix in .syndicate/lanes.md, in the owning lane's Files "
              "block. If a lane")
        print("       is not yours, tell its owner rather than editing across "
              "lanes.")
        return 1
    if unwritten:
        print()
        print("[note] %d claim(s) name a well-formed path that does not exist "
              "YET." % len(unwritten))
        for slug, claim in unwritten:
            print("         %-52s (%s)" % (claim, slug))
        print("       REPORTED, NOT FAILED. A lane legitimately claims a file "
              "it is about to")
        print("       create, and such a claim starts guarding the moment the "
              "file lands, so")
        print("       failing on it would be a check that cries wolf at every "
              "session start.")
        print("       Nothing close to these names exists -- if one did, it "
              "would be a typo and")
        print("       would be listed as BAD above with the neighbour named.")

    # A near-miss HEADER is the same failure as a broken claim -- files
    # declared, nothing enforced -- so it fails the check on its own.
    # `unwritten` deliberately does NOT.
    return 1 if near_headers else 0


if __name__ == "__main__":
    sys.exit(main())
