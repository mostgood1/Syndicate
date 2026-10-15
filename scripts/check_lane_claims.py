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

  TWO CONDITIONS NARROW THAT ESCALATION, both added 2026-10-12 after it
  misfired on two live claims at once. A close name is evidence of a typo only
  when the lane has not said otherwise and the neighbour is actually adoptable:

    * THE NEIGHBOUR MUST NOT BE ANOTHER OPEN LANE'S. The suggestion told
      `nba-lineup-pools` its reserved `tests/test_nba_lineup_pools.py` was
      "almost certainly a TYPO for `tests/test_nba_pregame_lineup_pools.py`" --
      a file the OPEN lane `nba-pregame-lineup-pools` claims. Following the
      remedy would have put two OPEN lanes on one path and had `lane-guard`
      block one of them. A check whose advice manufactures the contest the
      guards exist to prevent is worse than silence, so a held neighbour is
      never offered as a fix and the holder is named instead.

    * A PATH THE LANE MARKED `(NEW)` IS A RESERVATION, NOT A GUESS. Measured on
      the live ledger the same day: 44 of 74 `Files:` lines carry a `(NEW)`
      marker, so it is the ledger's established way of writing down a file the
      lane is about to create -- which is precisely the NOT WRITTEN YET shape
      below. It is honoured rather than overridden because the worked example
      did NOT use it: `ncaaf-live-cadence`'s typo'd path carries no marker, so
      reading the marker costs that catch nothing. The neighbour is still
      printed, as information, without the typo assertion.

  NOT WRITTEN YET (reported, exit 0) -- a well-formed path, absent, with
  nothing close to it, OR with a close name that the lane has excused by
  marking the claim `(NEW)` or that another OPEN lane holds (see the two
  conditions above). A lane legitimately claims a file it is about to create,
  and such a claim starts guarding the moment the file lands. Reported so it is
  visible, never failed, because failing on it is the wolf-crying case.

  Either way the claim guards NOTHING until the file exists -- a reservation is
  unenforceable, and saying so is the point of listing it here. What changed is
  only which remedy is printed, never whether the gap is reported.

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
import re
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


#: A standalone CLOSED token in the status field. The near-miss check excludes it,
#: because a closed lane's Files line is a historical record and not an unenforced
#: claim -- which this file's own docstring says and its predicate did not.
CLOSED_RE = re.compile(r"\bCLOSED\b")


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
                # NOT `status.upper()`, and NOT without the CLOSED test. Measured
                # 2026-10-14: the case-insensitive containment fired on lane
                # `nba-pregame-lineup-pools`, whose CLOSED status reads
                # `CLOSED 2026-10-14 (GOAL MET via the pre-opener as-of replay; ...)`
                # -- the substring `open` inside the PROSE word "pre-opener" matched,
                # while `OPEN_RE` (case-sensitive \bOPEN\b) correctly did not. That one
                # false positive made `check_lane_claims.py` exit 1 on origin/main, so
                # EVERY session's start digest read `LEDGER INCOHERENT` for a lane with
                # nothing wrong with it. Only the first em-dash segment is the status,
                # which is why one lane trips it and the other CLOSED blocks do not:
                # they carry a bare `CLOSED` there.
                #
                # Uppercase containment is the right test because the near-miss class
                # this exists for is written uppercase in this ledger (`REOPENED`,
                # `OPENED`) -- the worked example was `**REOPENED 2026-09-03 for the
                # READ side**`. A mixed-case `Reopened` would be missed here, and that
                # is deliberate rather than overlooked: `OPEN_RE` does not enforce it
                # either, so the REPORT now matches the ENFORCEMENT instead of being
                # wider than it.
                #
                # The CLOSED test implements what the docstring above already promises
                # -- "A CLOSED lane with a Files block is a normal historical record and
                # is not reported" -- which the predicate never actually checked.
                near = (
                    "OPEN" in status
                    and not OPEN_RE.search(status)
                    and not CLOSED_RE.search(status)
                )
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


def _is_test_of(test_name, module_name):
    """True when `test_name` is the conventional test file for `module_name`.

    Both spellings this repo uses: a `test_` prefix (`tests/test_foo.py`, which
    is every test here) and a `_test` suffix, included so the guard does not
    depend on a convention nobody has broken yet.
    """
    # The empty checks are load-bearing (a bare "" would make `"test_" + ""`
    # equal `"test_"` and match a claim literally named that). An
    # `test_name == module_name` clause was here too and is GONE: it could
    # not change any outcome, because `"test_" + X` and `X + "_test"` never
    # equal `X`. Mutation testing caught it as a survivor -- a branch that
    # reads like protection and guards nothing is worse than no branch,
    # because it makes the next reader think the case is handled here.
    if not test_name or not module_name:
        return False
    stem, dot, ext = module_name.rpartition(".")
    if not dot:
        stem, ext = module_name, ""
    suffix = ("." + ext) if dot else ""
    return test_name in ("test_" + module_name, stem + "_test" + suffix)


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
    # A MODULE IS NEVER THE TYPO-CORRECTION FOR ITS OWN TEST.
    #
    # `test_team_recent_results.py` against `team_recent_results.py` scores
    # **0.898** on a 0.85 cutoff, so difflib matched them and this function
    # reported lane `board-interval-charts`'s deliberate reservation of a test
    # file as "almost certainly a TYPO for" the module under test. Measured
    # 2026-10-15 on origin/main: that ONE claim of 381 was the whole reason
    # `check_lane_claims.py` exited 1, so every session's start digest read
    # `LEDGER INCOHERENT` -- the same cost the `pre-opener` false positive had
    # the day before, from the same instrument.
    #
    # AND THE PRINTED REMEDY WAS ACTIVELY HARMFUL: that lane already claimed
    # the module on the same `Files:` line with its own section scope, so
    # applying the suggestion would have duplicated the module claim and
    # deleted the test-path reservation.
    #
    # DELIBERATELY NARROW. Only the pair that differs by exactly a `test_`
    # prefix or a `_test` suffix is suppressed, so the typo class this function
    # exists for is untouched: `test_ncaaf_live_autorun.py` against
    # `test_ncaaf_lines_autorun.py` (0.943, live -> lines) is still a near miss,
    # because neither is the test-form of the other.
    if _is_test_of(base, close[0]) or _is_test_of(close[0], base):
        return None
    for p in by_base[close[0]]:
        # Prefer a neighbour sitting in the same directory as the claim.
        if p.rsplit("/", 1)[0] == claim.rsplit("/", 1)[0]:
            return p
    return by_base[close[0]][0]


def _marked_new_at(line, at):
    """True when a `(NEW...)` parenthetical follows the claim at `at`.

    Written WITHOUT a regex on purpose. The first cut used one and a
    backslash escape did not survive being written through a shell heredoc
    and a non-raw string literal: the word-boundary became a literal
    backspace byte (0x08), the pattern matched nothing, and the detector was
    INERT while every test that mattered still passed -- the marker simply
    never registered, so every reservation kept reading as a typo. Plain
    string work cannot be mangled that way.
    """
    rest = line[at:].lstrip("` ")
    if not rest.startswith("("):
        return False
    inner = rest[1:].lstrip()
    if inner[:3].lower() != "new":
        return False
    return len(inner) == 3 or not (inner[3].isalnum() or inner[3] == '_')


def _new_marked(text):
    """(slug, claim) pairs whose `Files:` entry the lane marked `(NEW)`.

    The marker is a statement of intent the ledger already uses heavily -- 44
    of 74 `Files:` lines on 2026-10-12 -- and it is the difference between "I
    mistyped a path" and "I have reserved a path I am about to create". The
    parser that builds claim sets strips the parenthetical, so by the time a
    claim reaches the classification loop the marker is gone; this reads it back
    off the raw block.

    Deliberately matched only when the parenthetical FOLLOWS the path and its
    first word is `new`, so `(NEW, the as-of replay)` counts and a section
    qualifier like `(the ncaab entries only)` does not. Case-insensitive
    because the ledger writes both `(NEW)` and `(new)`.
    """
    out = set()
    slug = None
    in_files = False
    for line in text.splitlines():
        if HEADER_RE.match(line):
            m = LANE_RE.match(line) or ASCII_LANE_RE.match(line)
            slug = m.group(1) if m else None
            in_files = False
            continue
        if slug is None:
            continue
        if FILES_RE.match(line):
            in_files = True
        elif FIELD_RE.match(line):
            in_files = False
        if not in_files:
            continue
        for claim in _paths_in(line):
            at = line.find(claim)
            while at != -1:
                if _marked_new_at(line, at + len(claim)):
                    out.add((slug, claim))
                    break
                at = line.find(claim, at + 1)
    return out


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

    # Who holds what, so a suggestion can never name another lane's file, and
    # which claims the lane itself marked `(NEW)`. Both are read from the SAME
    # text the claim set came from, so they cannot describe a different ledger.
    new_marked = _new_marked(text)
    holders = {}
    for slug, claim in claims:
        holders.setdefault(claim, set()).add(slug)

    broken, unwritten, inert = [], [], []
    for slug, claim in claims:
        if not _resolves(claim, paths, by_base, root):
            neighbour = _near_miss(claim, by_base)
            held_by = sorted(holders.get(neighbour, set()) - {slug}) if neighbour else []
            # An impossible token stays BROKEN however it is marked: a glob or a
            # brace list cannot resolve when the file lands, so `(NEW)` does not
            # excuse it. For a well-formed path, the typo hypothesis survives
            # only if the lane did not reserve the path AND the neighbour is
            # free to adopt.
            if _impossible(claim):
                broken.append((slug, claim, neighbour, held_by))
            elif neighbour and not held_by and (slug, claim) not in new_marked:
                broken.append((slug, claim, neighbour, held_by))
            else:
                unwritten.append((slug, claim, neighbour, held_by,
                                  (slug, claim) in new_marked))
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
        for slug, claim, neighbour, held_by in broken:
            by_lane.setdefault(slug, []).append((claim, neighbour, held_by))
        for slug in sorted(by_lane):
            print()
            print("       %s" % slug)
            for claim, neighbour, held_by in by_lane[slug]:
                print("         %s" % claim)
                if neighbour and held_by:
                    print("           -> `%s` is the closest name, but DO NOT ADOPT IT:"
                          % neighbour)
                    print("              the OPEN lane(s) %s claim it."
                          % ", ".join(held_by))
                elif neighbour:
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
        for slug, claim, neighbour, held_by, is_new in unwritten:
            print("         %-52s (%s)%s"
                  % (claim, slug, "  [marked NEW]" if is_new else ""))
            if neighbour and held_by:
                print("           close name `%s` exists but the OPEN lane(s) %s claim it,"
                      % (neighbour, ", ".join(held_by)))
                print("           so it is NOT a typo to adopt -- taking it would contest "
                      "that lane.")
            elif neighbour:
                print("           close name `%s` exists and no lane claims it. Read as a"
                      % neighbour)
                print("           reservation because this claim is marked (NEW); if the "
                      "new file")
                print("           was in fact never written, that neighbour is the likely "
                      "intent.")
        print("       REPORTED, NOT FAILED. A lane legitimately claims a file "
              "it is about to")
        print("       create, and such a claim starts guarding the moment the "
              "file lands, so")
        print("       failing on it would be a check that cries wolf at every "
              "session start.")
        print("       Every one of these guards NOTHING until its file exists. "
              "A close-named")
        print("       file is a TYPO only when the lane did not mark the path "
              "(NEW) and no")
        print("       other OPEN lane holds the neighbour -- those are listed "
              "as BAD above.")

    # A near-miss HEADER is the same failure as a broken claim -- files
    # declared, nothing enforced -- so it fails the check on its own.
    # `unwritten` deliberately does NOT.
    return 1 if near_headers else 0


if __name__ == "__main__":
    sys.exit(main())
