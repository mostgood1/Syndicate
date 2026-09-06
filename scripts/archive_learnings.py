"""Move dated `learnings.md` entries older than a cutoff to `learnings_archive.md`.

WHY A TOOL AND NOT A ONE-OFF. `learnings.md` is read at every session start and
written by every session, and this is a STRUCTURAL rewrite rather than an
append. The three verification checks below are the only thing between a
classification bug and a silently mangled ledger, so they gate the write the
same way `compact_learnings.py` and `split_state.py` gate theirs.

THE HAZARD THIS EXISTS TO SURVIVE: THE HEADING DATE FORMAT IS HETEROGENEOUS.
Measured 2026-09-06 across 482 sections, five shapes are in use:

    ## 2026-08-20 — RULE                         iso-lead      427
    ## 08-21 RULE                                mmdd-lead      29
    ## Ancestry is the wrong test `[2026-08-20]`  trailing       16
    ## [2026-09-05] RULE                         bracket-lead    5
    ## RULE  (date only in the body)             body-date       1

A naive `^## 2026-\\d\\d-\\d\\d` misses 41 real rules. A loose one sweeps up the
four STRUCTURAL sections -- `## Index`, `## Compacted entries`, `## Entries
before <date> — moved to ...`, `## Superseded on ...` -- and the third of those
is the POINTER that makes the archive findable at all.

AN UNCLASSIFIABLE SECTION IS A REFUSAL, NOT A DEFAULT. `learnings.md` itself
carries the rule: an unknown must not fall onto the permissive branch. If a
sixth date shape appears, this stops rather than guessing.

COMPACTION IS A DIFFERENT LEVER AND IS NEARLY SPENT: it moves a body to
`learnings_evidence.md` and keeps the rule here, and 411 of 426 entries are
already stubs. Archival moves the WHOLE entry, heading included, and relies on
`build_learnings_index.py` -- which already reads `learnings_archive.md` -- to
keep it findable. REGENERATE THE INDEX AFTER RUNNING THIS.

    py -3 scripts/archive_learnings.py --before 2026-09-01
    py -3 scripts/archive_learnings.py --before 2026-09-01 --apply
    py -3 scripts/build_learnings_index.py --apply

Exit 0 = clean (or nothing to do), 1 = refused, 2 = cannot read/verify.
"""
from __future__ import annotations

import argparse
import collections
import pathlib
import re
import sys

LEARN = pathlib.Path(".syndicate/learnings.md")
ARCHIVE = pathlib.Path(".syndicate/learnings_archive.md")

# Structure, never archived. Anchored on the heading so prose cannot match.
STRUCT = re.compile(r"^## (Index\b|Compacted entries\b|Entries before \d|Superseded on \d)")

# Date shapes, most specific first. `mmdd-lead` has no year: every entry in this
# file is 2026, and a two-digit year would be a different problem than this one.
SHAPES = (
    ("bracket-lead", re.compile(r"^##\s+\[(2026)-(\d\d)-(\d\d)\]")),
    ("iso-lead", re.compile(r"^##\s+(2026)-(\d\d)-(\d\d)")),
    ("mmdd-lead", re.compile(r"^##\s+\[?(?P<mm>\d\d)-(?P<dd>\d\d)\b")),
    ("trailing", re.compile(r"`\[(2026)-(\d\d)-(\d\d)")),
)


def section_date(sec):
    """(iso_date, shape) or (None, None). Heading first, then the first lines."""
    head = sec.split("\n")[0]
    for name, rx in SHAPES:
        m = rx.search(head)
        if not m:
            continue
        if name == "mmdd-lead":
            return "2026-%s-%s" % (m.group("mm"), m.group("dd")), name
        return "%s-%s-%s" % (m.group(1), m.group(2), m.group(3)), name
    m = re.search(r"\[(2026)-(\d\d)-(\d\d)", "\n".join(sec.split("\n")[:3]))
    if m:
        return "%s-%s-%s" % (m.group(1), m.group(2), m.group(3)), "body-date"
    return None, None


def load(path):
    data = path.read_bytes()
    bom = data[:3] if data[:3] == b"\xef\xbb\xbf" else b""
    crlf = b"\r\n" in data
    return data[len(bom):].decode("utf-8").replace("\r\n", "\n"), bom, crlf


def write(path, text, bom, crlf):
    path.write_bytes(bom + (text.replace("\n", "\r\n") if crlf else text).encode("utf-8"))


def headings(text):
    return collections.Counter(re.findall(r"^## .*$", text, re.M))


def nonblank(text):
    return collections.Counter(l for l in text.split("\n") if l.strip())


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--before", required=True,
                    help="archive dated entries strictly before this ISO date")
    ap.add_argument("--apply", action="store_true", help="write; default is a dry run")
    args = ap.parse_args(argv)

    try:
        learn, l_bom, l_crlf = load(LEARN)
        arch, a_bom, a_crlf = load(ARCHIVE)
    except OSError as exc:
        print("cannot read: %s" % exc)
        return 2

    parts = re.split(r"^(?=## )", learn, flags=re.M)
    preamble = parts[0] if parts and not parts[0].startswith("## ") else ""
    body = [s for s in parts if s.startswith("## ")]

    keep, move, unknown = [], [], []
    shapes = collections.Counter()
    for s in body:
        if STRUCT.match(s.split("\n")[0]):
            keep.append(s)
            continue
        d, shape = section_date(s)
        if not d:
            unknown.append(s)
            continue
        shapes[shape] += 1
        (move if d < args.before else keep).append(s)

    if unknown:
        print("REFUSED: %d section(s) carry no recognisable date." % len(unknown))
        for s in unknown[:5]:
            print("   " + s.split("\n")[0][:90])
        print("A sixth date shape means this tool's classifier is incomplete.")
        print("Teach it the shape rather than letting the section default.")
        return 1

    if not move:
        print("nothing before %s; unchanged." % args.before)
        return 0

    new_learn = preamble.rstrip("\n") + "\n\n" + "\n".join(s.strip("\n") for s in keep) + "\n"
    new_arch = arch.rstrip("\n") + "\n\n" + "\n".join(s.strip("\n") for s in move) + "\n"

    # --- verification, before any write -------------------------------------
    bad = []
    h_before = headings(learn) + headings(arch)
    h_after = headings(new_learn) + headings(new_arch)
    lost = list((h_before - h_after).elements())
    if lost:
        bad.append("%d heading(s) lost: %s" % (len(lost), "; ".join(x[:50] for x in lost[:3])))
    dupe = [h for h, c in (h_after - h_before).items() if c > 0]
    if dupe:
        bad.append("%d heading(s) DUPLICATED: %s" % (len(dupe), "; ".join(x[:50] for x in dupe[:3])))
    n_before = nonblank(learn) + nonblank(arch)
    n_after = nonblank(new_learn) + nonblank(new_arch)
    gone = list((n_before - n_after).elements())
    if gone:
        bad.append("%d non-blank line(s) lost: %s"
                   % (len(gone), "; ".join(x.strip()[:50] for x in gone[:3])))

    print("date shapes : " + "  ".join("%s=%d" % kv for kv in shapes.most_common()))
    print("archiving   : %d entries before %s" % (len(move), args.before))
    print("staying     : %d (incl. %d structural)"
          % (len(keep), sum(1 for s in keep if STRUCT.match(s.split("\n")[0]))))
    print("learnings.md: %d -> %d B" % (len(learn.encode()), len(new_learn.encode())))
    print("archive     : %d -> %d B" % (len(arch.encode()), len(new_arch.encode())))

    if bad:
        print("\nREFUSED. Nothing written:")
        for b in bad:
            print("  * " + b)
        return 1
    print("\nverification: every heading conserved in exactly one file, "
          "no duplicates, every non-blank line conserved")

    if not args.apply:
        print("\nDRY RUN. Re-run with --apply, then build_learnings_index.py --apply.")
        return 0

    current, _b, _c = load(LEARN)
    if current != learn:
        print("REFUSED: learnings.md changed while this ran. Nothing written; re-run.")
        return 1
    write(ARCHIVE, new_arch, a_bom, a_crlf)
    write(LEARN, new_learn, l_bom, l_crlf)
    print("\nWROTE both files.")
    print("NEXT: py -3 scripts/build_learnings_index.py --apply")
    return 0


if __name__ == "__main__":
    sys.exit(main())
