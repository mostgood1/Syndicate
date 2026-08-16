"""Regenerate the navigation index at the top of .syndicate/learnings.md.

learnings.md is append-only by contract and that is correct -- but at 82 rules
it stopped being readable in one pass, and the session-start digest can only
afford headings. This writes a scannable index between two markers so a session
can find the relevant rule without reading 2,300 lines. It edits ONLY the block
between the markers; every rule body is untouched.

Run after appending a rule:  py -3 scripts/build_learnings_index.py
"""
import io, re, sys

PATH = ".syndicate/learnings.md"
EVIDENCE = ".syndicate/learnings_evidence.md"
EVIDENCE_LINK = "learnings_evidence.md"
# The index lives in its OWN file. learnings.md is read at every session start
# and has a size budget; a generated navigation block that grows with the rule
# count does not belong inside it. Spanning the evidence file took the index
# from 104 to 193 entries (~35KB), which would have pushed learnings.md over
# budget -- discoverability eating the thing being discovered.
INDEX_PATH = ".syndicate/learnings_index.md"
START = "<!-- LEARNINGS-INDEX:START -->"
END = "<!-- LEARNINGS-INDEX:END -->"


def slug(text):
    s = text.lower()
    s = re.sub(r"[^\w\s-]", "", s)
    return re.sub(r"[\s]+", "-", s).strip("-")


# Structural sections, not rules. Matched against the heading text.
_NOT_A_RULE = re.compile(
    r"^(Index\b|Compacted entries\b|Superseded on\b|Closed lanes\b|Evidence for\b)", re.I
)
# A rule heading is dated or carries a verdict word. Both `##` and `###` are
# accepted: the file's convention is `###`, but eight rules were appended at
# `##` on 2026-08-15 and were therefore invisible to this index -- which is the
# failure mode the index exists to prevent.
_IS_RULE = re.compile(r"^\d{4}-\d{2}-\d{2}\b|FORBIDDEN|EXONERATED|REFUTED|OVERTURNED|CORRECTION|^RULE\b")


def _headings(text):
    """Rule headings from one file, at either `##` or `###`, in document order."""
    out = []
    for m in re.finditer(r"^#{2,3} (.+)$", text, re.M):
        h = m.group(1).strip()
        if _NOT_A_RULE.match(h) or not _IS_RULE.search(h):
            continue
        out.append(h)
    return out


def main():
    src = io.open(PATH, encoding="utf-8").read()
    entries = [(h, None) for h in _headings(src)]

    # THE INDEX MUST SPAN THE EVIDENCE FILE TOO.
    #
    # Compaction moves a rule's BODY to learnings_evidence.md and leaves the
    # heading behind, so an index that scans only learnings.md under-reports by
    # exactly the number of rules that have been compacted -- 152 of them when
    # this was written, invisible to the session-start digest. A rule you cannot
    # find is a rule you will break again, so compaction must not cost
    # discoverability.
    try:
        ev = io.open(EVIDENCE, encoding="utf-8").read()
    except OSError:
        ev = ""
    seen = {h for h, _ in entries}
    for h in _headings(ev):
        if h not in seen:  # a heading kept in both places is listed once, here
            entries.append((h, EVIDENCE_LINK))

    if not entries:
        print("no rule headings found; refusing to write an empty index")
        return 1

    kinds = {"FORBIDDEN": [], "EXONERATED": [], "other": []}
    for e, where in entries:
        bucket = "other"
        for k in ("FORBIDDEN", "EXONERATED"):
            if re.search(r"\b%s\b" % k, e):
                bucket = k
                break
        kinds[bucket].append((e, where))

    lines = [
        START,
        "",
        "## Index — %d rules `[generated]`" % len(entries),
        "",
        "> Regenerate with `py -3 scripts/build_learnings_index.py` after appending.",
        "> This block is the ONLY part of this file that is rewritten; rule bodies",
        "> are append-only and are never touched. **FORBIDDEN** = never do this",
        "> again. **EXONERATED** = ruled out, stop re-investigating. Entries marked",
        "> `[evidence]` have their body in `learnings_evidence.md`.",
        "",
    ]
    for label, key in (
        ("FORBIDDEN — %d" % len(kinds["FORBIDDEN"]), "FORBIDDEN"),
        ("EXONERATED — %d" % len(kinds["EXONERATED"]), "EXONERATED"),
        ("Rules and corrections — %d" % len(kinds["other"]), "other"),
    ):
        if not kinds[key]:
            continue
        lines.append("**%s**" % label)
        lines.append("")
        for e, where in kinds[key]:
            # An entry whose body lives in the evidence file links THERE, not to
            # a local anchor that does not exist.
            target = ("%s#%s" % (where, slug(e))) if where else ("#%s" % slug(e))
            suffix = " `[evidence]`" if where else ""
            # TRUNCATED FOR DISPLAY ONLY -- the link still resolves, because the
            # anchor is slugged from the FULL heading. Index entries are
            # navigation, and some rule headings run past 150 characters; at 193
            # entries the untruncated block cost ~35KB of a file with a 117KB
            # budget, i.e. discoverability was eating the thing being discovered.
            label_text = e if len(e) <= 88 else e[:87].rstrip() + "…"
            lines.append("- [%s](%s)%s" % (label_text, target, suffix))
        lines.append("")
    lines.append(END)
    block = "\n".join(lines)

    # THE INDEX LIVES IN ITS OWN FILE.
    #
    # learnings.md is read at every session start and has a size budget. A
    # generated block that grows with the rule count does not belong inside it:
    # spanning the evidence file took the index from 104 to 193 entries (~35KB),
    # which pushed learnings.md over budget — discoverability eating the thing
    # being discovered. learnings.md keeps a short pointer instead.
    io.open(INDEX_PATH, "w", encoding="utf-8").write(block + "\n")

    pointer = "\n".join([
        START,
        "",
        "## Index — %d rules `[generated]`" % len(entries),
        "",
        "> Full index: [`learnings_index.md`](learnings_index.md) — regenerate with",
        "> `py -3 scripts/build_learnings_index.py` after appending. It spans BOTH",
        "> this file and `learnings_evidence.md`, so a rule stays findable after its",
        "> body is compacted out. **FORBIDDEN** = never do this again.",
        "> **EXONERATED** = ruled out, stop re-investigating.",
        "",
        END,
    ])
    if START in src and END in src:
        out = re.sub(
            re.escape(START) + r".*?" + re.escape(END), lambda _: pointer, src, flags=re.S
        )
    else:
        # First run: insert after the file's own header blockquote, before the
        # first rule, so nothing existing moves relative to anything else.
        anchor = src.index("\n### ")
        cut = src.rindex("\n---\n", 0, anchor)
        out = src[:cut] + "\n\n" + pointer + "\n" + src[cut:]

    io.open(PATH, "w", encoding="utf-8").write(out)
    print(
        "index written: %d rules (%d FORBIDDEN, %d EXONERATED, %d other)"
        % (
            len(entries),
            len(kinds["FORBIDDEN"]),
            len(kinds["EXONERATED"]),
            len(kinds["other"]),
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
