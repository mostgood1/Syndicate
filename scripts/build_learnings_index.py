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
START = "<!-- LEARNINGS-INDEX:START -->"
END = "<!-- LEARNINGS-INDEX:END -->"


def slug(text):
    s = text.lower()
    s = re.sub(r"[^\w\s-]", "", s)
    return re.sub(r"[\s]+", "-", s).strip("-")


def main():
    src = io.open(PATH, encoding="utf-8").read()
    entries = [m.group(1).strip() for m in re.finditer(r"^### (.+)$", src, re.M)]
    if not entries:
        print("no ### entries found; refusing to write an empty index")
        return 1

    kinds = {"FORBIDDEN": [], "EXONERATED": [], "other": []}
    for e in entries:
        bucket = "other"
        for k in ("FORBIDDEN", "EXONERATED"):
            if re.search(r"—\s*%s\b" % k, e):
                bucket = k
                break
        kinds[bucket].append(e)

    lines = [
        START,
        "",
        "## Index — %d rules `[generated]`" % len(entries),
        "",
        "> Regenerate with `py -3 scripts/build_learnings_index.py` after appending.",
        "> This block is the ONLY part of this file that is rewritten; rule bodies",
        "> are append-only and are never touched. **FORBIDDEN** = never do this",
        "> again. **EXONERATED** = ruled out, stop re-investigating.",
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
        for e in kinds[key]:
            lines.append("- [%s](#%s)" % (e, slug(e)))
        lines.append("")
    lines.append(END)
    block = "\n".join(lines)

    if START in src and END in src:
        out = re.sub(
            re.escape(START) + r".*?" + re.escape(END), lambda _: block, src, flags=re.S
        )
    else:
        # First run: insert after the file's own header blockquote, before the
        # first rule, so nothing existing moves relative to anything else.
        anchor = src.index("\n### ")
        cut = src.rindex("\n---\n", 0, anchor)
        out = src[:cut] + "\n\n" + block + "\n" + src[cut:]

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
