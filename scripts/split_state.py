"""Split `state.md` into an INDEX plus per-domain part files. Bodies move verbatim.

WHY. state.md reached 746,526 B / 176 sections, growing ~2,290 B/hour with
several sessions appending. Every session is told to read it first, and no
session reads 746 KB -- the session-start digest already truncates. Compaction
was tried and measured first: `compact_state.py` audited every superseded
marker in the file and found 0.2% reclaimable (see its docstring). The file is
not bloated, it is BIG, and it is big because it is live current truth. So the
lever is structural, not editorial.

THE SHAPE. `state.md` keeps the cross-cutting meta sections a session needs
regardless of what it is working on, plus a one-line-per-subject INDEX of
everything. Bodies live in `state_<domain>.md`. A session reads the index
(small) and then only the part it needs.

WHY AN INDEX AND NOT JUST PARTS. `state_key_check.py`'s invariant is ONE
SUBJECT, ONE SECTION, and it is global -- two sections sharing a slug is the
stacking failure the whole key exists to catch. Split into parts with no index,
that check has to span files and "where does subject X live" stops having an
answer. The index is the thing that keeps the invariant checkable and the
subject findable, so it is not decoration.

CLASSIFICATION IS AN EXPLICIT TABLE, NOT A KEYWORD SWEEP. A keyword pass over
the 176 slugs left 19 sections (96,868 B) unclassified and its buckets were
order-dependent -- the biggest section in the file landed in a bucket only
because of where it appeared in the rule list. OVERRIDES below assigns every
one of those 19 by hand; RULES covers the rest and is ordered sport-first so
`mlb-sim-edge-is-anti-predictive` files under mlb rather than model.

VERIFICATION BEFORE ANY WRITE -- each with a test that makes it fire:
  1. every section body is byte-identical in exactly one part file
  2. every `## ` heading conserved across index + parts
  3. slugs globally UNIQUE across all files (the invariant, spanning the split)
  4. every non-blank line conserved across all output files
  5. state.md re-read immediately before the write; a concurrent change is a
     refusal, not a silent overwrite

CRLF is round-tripped through byte I/O.

    py -3 scripts/split_state.py            # dry run: plan + verification
    py -3 scripts/split_state.py --apply

Exit 0 = clean, 1 = refused, 2 = cannot read/verify.
"""
from __future__ import annotations

import argparse
import collections
import pathlib
import re
import sys

SYN = pathlib.Path(".syndicate")
STATE = SYN / "state.md"

HEAD = re.compile(r"^## ")
SLUG = re.compile(r"^## \[([^\]]+)\] ?(.*)")
INDEX_SLUG = "subject-index"

# Sections that stay in state.md itself: cross-cutting, wanted regardless of
# what a session is working on, or instructions about the file itself.
ROOT = {
    # The index itself lives in state.md. Without this it classifies as "misc"
    # -- caught by test_nothing_falls_through_on_the_real_file once the split
    # had run and the index existed to classify.
    "subject-index",
    "how-to-use",
    "substrate-rule",
    "user-decisions",
    "open-problems",
    "shipped-verified",
    "live-sha-authority",
}

# The 19 a keyword sweep could not place, assigned by reading each one.
OVERRIDES = {
    "web-preflight-dead-sample": "worker",
    "web-anon-leak": "worker",
    "web-request-path-latency": "worker",
    "web-boot-sync-healthz": "worker",
    "services-config-platform": "worker",
    "local-fleet-runner": "worker",
    "fleet": "worker",
    "probability-statistic-ownership": "model",
    "replay-diff-gate": "model",
    "settlement-resolver-coverage": "model",
    "ask-the-syndicate": "board",
    "cfbd-monthly-quota-exhausted": "football",
    "espn-egress-and-wnba-boxscores": "basketball",
}

# Ordered. Sport-specific wins over generic: a section about MLB's simulator
# belongs with MLB, not with every other model subject.
RULES = [
    ("mlb", r"^mlb|statsapi|pitch-mix|hitter|batting|roster-obj"),
    ("soccer", r"^soccer|fotmob"),
    ("football", r"^nfl|^ncaaf|football|fantasy"),
    ("basketball", r"^nba|^wnba|^ncaab|basketball"),
    # The two venue INTEGRATIONS come out first, before the generic venue
    # bucket. state_venues.md reached 151,168 B / 42 sections -- the largest
    # part of the first split -- and it partitions cleanly by venue because
    # that is how the work itself is divided: Polymarket 24 sections,
    # Kalshi 6, and 12 that are about venues in general (fees, cadence,
    # storage, join keys) and belong to neither.
    ("polymarket", r"^polymarket"),
    ("kalshi", r"^kalshi"),
    ("venues", r"venue|exchange|odds|book|arb|fee|price|quote|market|clv|shopping"),
    ("board", r"board|card|surface|lens|display|chip|layer2|^ui|games-rail|portfolio"),
    ("worker", r"worker|memory|oom|deploy|render|keyvalue|artifact|publish|cache|runtime|budget|refresh|subprocess|disk|env"),
    ("model", r"sim|model|eval|accuracy|calibrat|intelligence|shortlist|projection|prop|ladder|scorer|edge|rank"),
    ("ledger", r"session|lane|ledger|state|todo|harness|checkpoint|protocol|guard|commit|test"),
]

DOMAINS = [r[0] for r in RULES]


def load():
    data = STATE.read_bytes()
    crlf = b"\r\n" in data
    text = data.decode("utf-8-sig").replace("\r\n", "\n")
    return text.split("\n"), crlf, text


def parse(lines):
    """[(slug, title, body_text)] plus the preamble before the first heading."""
    idx = [i for i, l in enumerate(lines) if HEAD.match(l)]
    preamble = "\n".join(lines[: idx[0]]) if idx else "\n".join(lines)
    out = []
    for n, i in enumerate(idx):
        e = idx[n + 1] if n + 1 < len(idx) else len(lines)
        m = SLUG.match(lines[i])
        slug = m.group(1) if m else None
        title = m.group(2) if m else lines[i][3:]
        out.append((slug, title, "\n".join(lines[i:e]).rstrip("\n")))
    return preamble, out


def classify(slug):
    if slug in ROOT:
        return "root"
    if slug in OVERRIDES:
        return OVERRIDES[slug]
    for name, pat in RULES:
        if re.search(pat, slug, re.I):
            return name
    return "misc"


def part_path(domain):
    return SYN / f"state_{domain}.md"


def build(preamble, secs):
    """Return {path: text} for every file the split writes."""
    buckets = collections.defaultdict(list)
    for slug, title, body in secs:
        buckets[classify(slug)].append((slug, title, body))

    files = {}
    for dom, items in buckets.items():
        if dom == "root":
            continue
        header = (
            f"# state — {dom}\n\n"
            f"Split out of `state.md` by `scripts/split_state.py`. Bodies are verbatim.\n"
            f"The INDEX of every subject, across every part, is in `state.md`; the\n"
            f"one-subject-one-section rule is global and spans these files.\n"
            f"Same rules as state.md: when a fact changes, EDIT THE LINE.\n"
        )
        files[part_path(dom)] = header + "\n" + "\n\n".join(b for _s, _t, b in items) + "\n"

    # state.md: preamble, the root sections, then the index.
    # `how-to-use` leads, because it is the instructions for the file a session
    # opens first; the rest keep file order.
    root_items = sorted(buckets.get("root", []), key=lambda it: it[0] != "how-to-use")
    index_rows = []
    for slug, title, body in secs:
        dom = classify(slug)
        where = "state.md" if dom == "root" else part_path(dom).name
        first = title.strip()
        index_rows.append(f"| [{slug}] | {first[:110]} | `{where}` |")

    index = (
        "## [subject-index] SUBJECT INDEX — every subject, and which file holds it\n\n"
        "One subject, one section, ACROSS ALL FILES. `state_key_check.py` checks\n"
        "that globally; a slug appearing twice anywhere is the stacking failure.\n"
        "Regenerate with `py -3 scripts/split_state.py --reindex --apply` after\n"
        "adding a subject, or add its row here by hand. Plain `--apply` REFUSES\n"
        "once this index exists: re-splitting would orphan the parts.\n\n"
        "| subject | title | file |\n|---|---|---|\n" + "\n".join(index_rows) + "\n"
    )

    root_text = preamble.rstrip("\n") + "\n\n"
    if root_items:
        root_text += "\n\n".join(b for _s, _t, b in root_items) + "\n\n"
    root_text += index
    files[STATE] = root_text
    return files, buckets


def verify(lines, secs, files):
    bad = []
    joined = "\n".join(files[p] for p in files)

    # 1. each body appears verbatim, exactly once, across the outputs
    for slug, _title, body in secs:
        n = sum(files[p].count(body) for p in files)
        if n != 1:
            bad.append(f"body for [{slug}] appears {n}x across outputs (want exactly 1)")
            if len(bad) > 5:
                break

    # 2. headings conserved
    h_before = collections.Counter(l for l in lines if HEAD.match(l))
    h_after = collections.Counter(l for l in joined.split("\n") if HEAD.match(l))
    lost = list((h_before - h_after).elements())
    if lost:
        bad.append(f"{len(lost)} heading(s) lost: " + "; ".join(x[:60] for x in lost[:3]))

    # 3. slugs globally unique
    slugs = [m.group(1) for m in (SLUG.match(l) for l in joined.split("\n")) if m]
    dupes = [s for s, c in collections.Counter(slugs).items() if c > 1 and s != "subject-index"]
    if dupes:
        bad.append(f"slug(s) not globally unique after split: {dupes[:5]}")

    # 4. every non-blank line conserved
    c_before = collections.Counter(l for l in lines if l.strip())
    c_after = collections.Counter(l for l in joined.split("\n") if l.strip())
    gone = list((c_before - c_after).elements())
    if gone:
        bad.append(f"{len(gone)} line(s) lost: " + "; ".join(x.strip()[:60] for x in gone[:3]))
    return bad


def index_rows_for(files_texts):
    rows = []
    for path, text in files_texts:
        for line in text.split("\n"):
            m = SLUG.match(line)
            if not m or m.group(1) == INDEX_SLUG:
                continue
            rows.append(f"| [{m.group(1)}] | {m.group(2).strip()[:110]} | `{path.name}` |")
    return rows


def reindex(lines, crlf, raw, apply_):
    """Rebuild state.md's index over state.md + every part, in place.

    This is what you run after ADDING a subject to a part: the index is the
    only place that lists every subject, so a subject missing from it is
    invisible even though state_key_check.py still sees it.
    """
    parts = sorted(p for p in SYN.glob("state_*.md")
                   if not p.name.startswith("state_archive"))
    files_texts = [(STATE, "\n".join(lines))]
    files_texts += [(p, p.read_text(encoding="utf-8-sig").replace("\r\n", "\n")) for p in parts]
    rows = index_rows_for(files_texts)

    start = next((i for i, l in enumerate(lines) if l.startswith(f"## [{INDEX_SLUG}]")), None)
    if start is None:
        print("REFUSED: no index section found to rebuild.")
        return 1
    head = lines[:start]
    body = [l for l in lines[start:] if not l.startswith("| [")]
    # keep everything up to the table header, then re-emit rows
    try:
        hdr = next(i for i, l in enumerate(body) if l.startswith("|---"))
    except StopIteration:
        print("REFUSED: index section has no table header.")
        return 1
    out = head + body[: hdr + 1] + rows + [""]
    print(f"reindex: {len(rows)} subject(s) across {len(files_texts)} file(s)")
    dupes = collections.Counter(r.split("]")[0] for r in rows)
    bad = [s for s, c in dupes.items() if c > 1]
    if bad:
        print(f"REFUSED: subject(s) listed twice: {bad[:5]}")
        return 1
    if not apply_:
        print("\nDRY RUN. Re-run with --apply to write.")
        return 0
    if STATE.read_bytes().decode("utf-8-sig").replace("\r\n", "\n") != raw:
        print("REFUSED: state.md changed while this ran. Nothing written; re-run.")
        return 1
    text = "\n".join(out)
    STATE.write_bytes((text.replace("\n", "\r\n") if crlf else text).encode("utf-8"))
    print("WROTE state.md (index rebuilt).")
    return 0


def resplit(src, apply_):
    """Re-partition ONE existing part with the current RULES.

    The initial split is a one-shot on the monolith; this is what you run when
    a part outgrows itself (state_venues.md hit 151,168 B). Sections whose slug
    now classifies elsewhere move out; the rest stay. Targets are APPENDED to,
    so an existing part is never clobbered.
    """
    if not src.exists():
        print(f"REFUSED: {src} does not exist.")
        return 1
    data = src.read_bytes()
    crlf = b"\r\n" in data
    text = data.decode("utf-8-sig").replace("\r\n", "\n")
    lines = text.split("\n")
    preamble, secs = parse(lines)
    own = src.name[len("state_"):-len(".md")]

    stay, move = [], collections.defaultdict(list)
    for slug, title, body in secs:
        dom = classify(slug)
        (stay if dom in (own, "root") else move[dom]).append((slug, title, body))
    if not move:
        print(f"{src.name}: nothing re-classifies out of it; unchanged.")
        return 0

    files = {src: preamble.rstrip("\n") + "\n\n"
                  + "\n\n".join(b for _s, _t, b in stay) + "\n"}
    for dom, items in move.items():
        p = part_path(dom)
        if p.exists():
            base = p.read_bytes().decode("utf-8-sig").replace("\r\n", "\n").rstrip("\n")
        else:
            base = (f"# state — {dom}\n\n"
                    f"Split out of `state.md` by `scripts/split_state.py`. Bodies are verbatim.\n"
                    f"The INDEX of every subject, across every part, is in `state.md`; the\n"
                    f"one-subject-one-section rule is global and spans these files.\n"
                    f"Same rules as state.md: when a fact changes, EDIT THE LINE.")
        files[p] = base + "\n\n" + "\n\n".join(b for _s, _t, b in items) + "\n"

    print(f"{src.name}: {len(secs)} sections -> {len(stay)} stay, "
          f"{sum(len(v) for v in move.values())} move")
    for dom, items in sorted(move.items(), key=lambda kv: -sum(len(b) for _s, _t, b in kv[1])):
        print(f"  {sum(len(b) for _s, _t, b in items):>7} ch  {len(items):>2} sections  -> {part_path(dom).name}")
    print(f"  {sum(len(b) for _s,_t,b in stay):>7} ch  {len(stay):>2} sections  stay in {src.name}")

    bad = verify(lines, secs, files)
    # verify() only sees the files this call writes; a body that moved to an
    # EXISTING part is counted there because that part's full text is in files.
    if bad:
        print("\nREFUSED. Nothing written:")
        for b in bad:
            print(f"  * {b}")
        return 1
    print("\nverification: every body verbatim exactly once, headings conserved, "
          "slugs globally unique, every non-blank line conserved")
    if not apply_:
        print("\nDRY RUN. Re-run with --apply, then --reindex --apply.")
        return 0
    if src.read_bytes() != data:
        print(f"REFUSED: {src.name} changed while this ran. Nothing written; re-run.")
        return 1
    for p, t in files.items():
        p.write_bytes((t.replace("\n", "\r\n") if crlf else t).encode("utf-8"))
    print(f"\nWROTE {len(files)} file(s).")
    print("NEXT: py -3 scripts/split_state.py --reindex --apply")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true", help="write; default is a dry run")
    ap.add_argument("--resplit", help="re-partition ONE existing part with the "
                                      "current RULES (e.g. .syndicate/state_venues.md)")
    ap.add_argument("--reindex", action="store_true",
                    help="rebuild state.md's index over state.md + every part "
                         "(use after adding a subject to a part)")
    args = ap.parse_args(argv)

    try:
        lines, crlf, raw = load()
    except OSError as exc:
        print(f"cannot read {STATE}: {exc}")
        return 2

    if args.resplit:
        return resplit(pathlib.Path(args.resplit), args.apply)

    # ALREADY-SPLIT GUARD. Running this twice is not idempotent and is not
    # harmless: the second pass would read a state.md that holds only the index
    # and the cross-cutting subjects, re-classify THOSE, and rewrite the index
    # to list seven subjects instead of 177 -- the parts would survive on disk
    # but nothing would point at them. compact_learnings.py has the same class
    # of marker for the same reason; a tool that transforms a file in place
    # needs to recognise its own output.
    if INDEX_SLUG in "\n".join(lines):
        if not args.reindex:
            print(f"REFUSED: {STATE} already carries [{INDEX_SLUG}], so the split has run.")
            print("Re-splitting would rewrite the index to cover only the sections")
            print("left in state.md and orphan the parts. To rebuild the index over")
            print("state.md + every part instead:")
            print("  py -3 scripts/split_state.py --reindex --apply")
            return 1
        return reindex(lines, crlf, raw, args.apply)
    if args.reindex:
        print(f"REFUSED: --reindex needs an already-split {STATE}; it has no index.")
        return 1

    preamble, secs = parse(lines)
    files, buckets = build(preamble, secs)

    before_chars = len("\n".join(lines))
    print(f"state.md: {before_chars} chars, {len(secs)} sections -> {len(files)} files\n")
    for p in sorted(files, key=lambda x: -len(files[x])):
        dom = "root+index" if p == STATE else p.name
        n = len(buckets.get(p.name[6:-3] if p != STATE else "root", []))
        print(f"  {len(files[p]):>7} ch  {n:>3} sections  {p.name}   {'(index + cross-cutting)' if p == STATE else ''}")

    misc = buckets.get("misc", [])
    if misc:
        print(f"\n{len(misc)} section(s) fell through to 'misc' -- assign them in OVERRIDES:")
        for slug, _t, b in misc:
            print(f"  {len(b):>6}  [{slug}]")

    bad = verify(lines, secs, files)
    if bad:
        print("\nREFUSED. Nothing written:")
        for b in bad:
            print(f"  * {b}")
        return 1
    print("\nverification: every body verbatim exactly once, headings conserved, "
          "slugs globally unique, every non-blank line conserved")

    if not args.apply:
        print("\nDRY RUN. Re-run with --apply to write.")
        return 0

    current = STATE.read_bytes().decode("utf-8-sig").replace("\r\n", "\n")
    if current != raw:
        print("REFUSED: state.md changed while this ran. Nothing written; re-run.")
        return 1

    for p, text in files.items():
        p.write_bytes((text.replace("\n", "\r\n") if crlf else text).encode("utf-8"))
    print(f"\nWROTE {len(files)} file(s).")
    print("NEXT: py -3 scripts/state_key_check.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
