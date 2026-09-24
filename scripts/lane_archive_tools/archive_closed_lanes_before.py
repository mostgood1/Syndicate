"""Archive CLOSED lanes whose latest close date is before a cutoff: move every block of each
eligible slug from lanes.md to the end of lanes_closed.md, and add one pointer line per slug
under `## Archived lanes (full bodies in lanes_closed.md)`.

Eligible slug: holds no claims (lane_claims._claims), header status is CLOSED[-X], no header
reads OPEN / ORPHANED / VOID, and a close date (`— CLOSED[-X] YYYY-MM-DD` or `closed YYYY-MM-DD`
in the header) exists with the latest < CUTOFF. `--only slug[,slug]` restricts the set further
(used when owner liveness was checked separately); with `--owner-idle-verified` it also waives
the close-date requirement for the named slugs, since the date's only jobs are the CUTOFF
comparison that flag replaces and picking a pointer header among several.

Verifies before writing: claim set identical AS A SET; OPEN header count unchanged; every moved
non-blank line present in the new lanes_closed.md; no header of a moved slug left in lanes.md;
exactly one pointer per moved slug; both files unchanged on disk since read. CRLF preserved.
Only blank lines at removal boundaries are touched. Default dry run; --apply writes.

REFUSES FIRST, in BOTH modes, if this worktree's lanes.md or lanes_closed.md is missing any
non-blank line that `origin/main` has. Line 24 has always said "a worktree synced to
origin/main" and nothing enforced it. The gate that decides WHICH slugs are safe
(`owner_liveness.py`) reads `origin/main`; this script reads and rewrites `ARCHIVE_WORKTREE`, and
nothing compared them. Measured 2026-09-24 in the primary tree, 133 commits behind:
`lanes_closed.md` 998,153 B here against 1,092,512 B on `origin/main`, so `--apply` plus a commit
would have reverted ~94 KB of archived lane bodies -- including three slugs archived that same
morning. The existing "both files unchanged on disk since read" check cannot see this: it guards
against a concurrent LOCAL writer, not a stale BASELINE.

CONTAINMENT, not equality -- a worktree legitimately AHEAD (a lane closed locally, not yet
pushed) must still be able to archive. Only missing upstream content is a revert.
Exit 3 on refusal. `--allow-stale-worktree` waives it and prints what it waived.
"""
import re
import subprocess
import sys
import types
from pathlib import Path

import os
sys.stdout.reconfigure(encoding="utf-8")  # piped stdout is cp1252 on Windows: the em-dash printed as 0x97
W = Path(os.environ.get("ARCHIVE_WORKTREE") or sys.exit("set ARCHIVE_WORKTREE to a worktree synced to origin/main"))
LANES = W / ".syndicate" / "lanes.md"
CLOSED = W / ".syndicate" / "lanes_closed.md"
GUARD = W / ".claude" / "hooks" / "lane_claims.py"
CUTOFF = os.environ.get("ARCHIVE_CUTOFF", "2026-09-15")  # before-date rule; --only with --owner-idle-verified replaces it
APPLY = "--apply" in sys.argv
ONLY = set(sys.argv[sys.argv.index("--only") + 1].split(",")) if "--only" in sys.argv else None
OWNER_IDLE_VERIFIED = "--owner-idle-verified" in sys.argv
ALLOW_STALE = "--allow-stale-worktree" in sys.argv

BOUNDARY = re.compile(r"^#{2,3}\s")
HEADER = re.compile(r"^### (\S+) ")
OPEN_HEADER = re.compile(r"^### \S+ — OPEN\b")
CLOSED_DATE = re.compile(r"(?:—\s*CLOSED[\w-]*\s+|\bclosed\s+)(\d{4}-\d{2}-\d{2})")
POINTER_HEAD = "## Archived lanes (full bodies in `lanes_closed.md`)"


def claims(text):
    mod = types.ModuleType("lane_claims_ro")
    exec(compile(GUARD.read_text(encoding="utf-8"), str(GUARD), "exec"), mod.__dict__)
    return set(mod._claims(text))


def missing_upstream_lines(worktree_text, main_text):
    """Non-blank lines `origin/main` has that this worktree's copy does not.

    CONTAINMENT rather than equality, because the two trees differ for two very
    different reasons and only one of them is dangerous. A worktree AHEAD -- a
    lane closed locally and not yet pushed -- adds lines, and archiving from it
    reverts nothing. A worktree BEHIND is missing lines that exist upstream, and
    writing it back DELETES them. Equality would refuse both and make the tool
    unusable in the ordinary case.

    Set membership, so a line repeated upstream but present once here passes:
    the question is whether the content survives, not how many times. Blank
    lines carry no content and this script rewrites them at removal boundaries
    by design, so they are excluded -- including them would refuse every tree.
    """
    have = set(worktree_text.replace("\r\n", "\n").split("\n"))
    return [l for l in main_text.replace("\r\n", "\n").split("\n")
            if l.strip() and l not in have]


def _origin_main_blob(worktree, relative):
    """`origin/main`'s copy of one file, or None if the ref cannot be read."""
    try:
        out = subprocess.run(
            ["git", "-C", str(worktree), "cat-file", "-p", "origin/main:" + relative],
            capture_output=True, timeout=60)
    except Exception:
        return None
    return out.stdout.decode("utf-8", "replace") if out.returncode == 0 else None


raw_lanes = LANES.read_bytes()
raw_closed = CLOSED.read_bytes()
lanes_text = raw_lanes.decode("utf-8")
closed_text = raw_closed.decode("utf-8")

# THE BASELINE GATE. Runs in BOTH modes on purpose: a clean dry run followed by
# a refusing --apply would send the operator looking for the wrong problem, and
# the dry run is what gets read and believed.
_head = subprocess.run(["git", "-C", str(W), "rev-parse", "origin/main"],
                       capture_output=True, timeout=60)
_main_sha = _head.stdout.decode().strip() if _head.returncode == 0 else ""
_stale = {}
if not _main_sha:
    _stale["<ref>"] = ["origin/main cannot be resolved in this worktree"]
else:
    for _rel, _txt in ((".syndicate/lanes.md", lanes_text),
                       (".syndicate/lanes_closed.md", closed_text)):
        _main_txt = _origin_main_blob(W, _rel)
        if _main_txt is None:
            _stale[_rel] = ["origin/main:" + _rel + " could not be read"]
            continue
        _gap = missing_upstream_lines(_txt, _main_txt)
        if _gap:
            _stale[_rel] = _gap
if _stale:
    print("WORKTREE IS BEHIND origin/main (" + (_main_sha[:12] or "unresolved") + ").")
    for _rel in sorted(_stale):
        _gap = _stale[_rel]
        print("  " + _rel + ": " + str(len(_gap)) + " non-blank line(s) on origin/main are absent here")
        for _l in _gap[:3]:
            print("      " + _l[:110])
        if len(_gap) > 3:
            print("      ... and " + str(len(_gap) - 3) + " more")
    if not ALLOW_STALE:
        print("REFUSING: writing this tree back would DELETE that content. "
              "Sync the worktree, or pass --allow-stale-worktree.")
        sys.exit(3)
    print("WAIVED by --allow-stale-worktree: the lines above will be lost if this is committed.")
nl = "\r\n" if "\r\n" in lanes_text else "\n"
cnl = "\r\n" if "\r\n" in closed_text else "\n"
lines = lanes_text.split(nl)

before_claims = claims(lanes_text.replace("\r\n", "\n"))
claimed_slugs = {s for s, _ in before_claims}
open_before = sum(1 for l in lines if OPEN_HEADER.match(l))

# Every `### ` block, with its slug and end (next `##`/`###` boundary).
blocks = []
for i, l in enumerate(lines):
    m = HEADER.match(l)
    if not m:
        continue
    end = next((j for j in range(i + 1, len(lines)) if BOUNDARY.match(lines[j])), len(lines))
    blocks.append((i, end, m.group(1)))

by_slug = {}
for start, end, slug in blocks:
    by_slug.setdefault(slug, []).append((start, end))

if ONLY:
    missing = ONLY - set(by_slug)
    assert not missing, ("--only slug has no block in lanes.md", sorted(missing))

eligible, pointer_src = {}, {}
for slug, spans in by_slug.items():
    if ONLY and slug not in ONLY:
        continue
    if slug in claimed_slugs:
        continue
    headers = [lines[s] for s, _ in spans]
    status_parts = [h[len(f"### {slug} "):][:60] for h in headers]
    if any(re.match(r"—\s*(OPEN|ORPHANED|VOID)\b", p) or "**ORPHANED" in p for p in status_parts):
        continue
    if not all(re.match(r"—\s*CLOSED", p) for p in status_parts):
        continue
    dated = [(m.group(1), h) for h in headers for m in [CLOSED_DATE.search(h[:220])] if m]
    if not dated:
        # A CLOSED header carrying no close date (`### slug — CLOSED — opened ... — session ...`)
        # is still archivable when it was named explicitly in --only AND owner liveness was
        # verified separately: the date only feeds the CUTOFF, which --owner-idle-verified
        # already replaces, and picks which header sources the pointer -- and with one dateless
        # header there is nothing to pick between. Added 2026-09-20 (user decision) after three
        # scheduled runs deferred `ranking-records-build-cost` for this and nothing else.
        if not (ONLY and OWNER_IDLE_VERIFIED):
            continue
        eligible[slug] = spans
        pointer_src[slug] = headers[-1]
        continue
    latest = max(d for d, _ in dated)
    # --owner-idle-verified: the owner-liveness read (transcript idle, clean worktrees) replaces the
    # date cutoff for the named --only slugs. Every other check still applies.
    if latest >= CUTOFF and not (ONLY and OWNER_IDLE_VERIFIED):
        continue
    eligible[slug] = spans
    pointer_src[slug] = max(dated)[1]   # the header with the latest CLOSED date

if ONLY:
    assert set(eligible) == ONLY, ("--only slug not eligible", sorted(ONLY - set(eligible)))

# Existing pointers under the archived heading (a slug may already have one).
head_idx = next(i for i, l in enumerate(lines) if l.startswith(POINTER_HEAD))
existing_ptr_slugs = set()
for l in lines[head_idx + 1:]:
    if BOUNDARY.match(l):
        break
    m = re.match(r"^- `([^`]+)` — ", l)
    if m:
        existing_ptr_slugs.add(m.group(1))

# Remove the blocks; drop one blank only at a removal boundary.
starts = {s: e for spans in eligible.values() for s, e in spans}
kept, i = [], 0
while i < len(lines):
    if i in starts:
        i = starts[i]
        while i in starts:
            i = starts[i]
        if kept and kept[-1] == "" and i < len(lines) and lines[i] == "":
            i += 1
        continue
    kept.append(lines[i])
    i += 1

# Merge new pointers into the first contiguous pointer list, alphabetically.
new_pointers = {}
for slug, header in pointer_src.items():
    if slug in existing_ptr_slugs:
        continue
    new_pointers[slug] = f"- `{slug}` — " + header[len(f"### {slug} — "):]
h = next(i for i, l in enumerate(kept) if l.startswith(POINTER_HEAD))
first = next(i for i in range(h + 1, len(kept)) if kept[i].startswith("- `"))
last = first
while last < len(kept) and kept[last].startswith("- `"):
    last += 1
merged = sorted(kept[first:last] + list(new_pointers.values()), key=lambda p: p.split("`")[1])
kept = kept[:first] + merged + kept[last:]
new_lanes = nl.join(kept)

# Append moved blocks (in file order) to lanes_closed.md.
chunks = []
for slug, spans in sorted(eligible.items(), key=lambda kv: kv[1][0][0]):
    for s, e in spans:
        chunk = lines[s:e]
        while chunk and chunk[-1] == "":
            chunk.pop()
        chunks.append(cnl.join(chunk))
sep = "" if closed_text.endswith(cnl) else cnl
new_closed = closed_text + sep + cnl + (cnl + cnl).join(chunks) + cnl if chunks else closed_text

# ---------------------------------------------------------------- verification
after_claims = claims(new_lanes.replace("\r\n", "\n"))
assert after_claims == before_claims, ("claim set changed", len(before_claims ^ after_claims))
new_lines = new_lanes.split(nl)
assert sum(1 for l in new_lines if OPEN_HEADER.match(l)) == open_before, "OPEN header count changed"
closed_set = set(new_closed.split(cnl))
moved_lines = 0
for slug, spans in eligible.items():
    assert not any(l.startswith(f"### {slug} ") for l in new_lines), (slug, "header left in lanes.md")
    assert sum(1 for l in new_lines if l.startswith(f"- `{slug}` — ")) == 1, (slug, "pointer count != 1")
    for s, e in spans:
        moved_lines += e - s
        for l in lines[s:e]:
            if l.strip():
                assert l in closed_set, (slug, "line not conserved", l[:80])

print(f"eligible slugs {len(eligible)} | blocks {sum(len(v) for v in eligible.values())} | block lines {moved_lines} | new pointers {len(new_pointers)} (existing reused {len(eligible) - len(new_pointers)})")
print(f"lanes.md {len(raw_lanes)} -> {len(new_lanes.encode('utf-8'))} B | lanes_closed.md {len(raw_closed)} -> {len(new_closed.encode('utf-8'))} B")
print(f"claims unchanged {len(after_claims)} | OPEN headers {open_before} unchanged")
for slug in sorted(eligible):
    spans = eligible[slug]
    _dates = [CLOSED_DATE.search(lines[s][:220]).group(1) for s, _ in spans if CLOSED_DATE.search(lines[s][:220])]
    latest = max(_dates) if _dates else "(no close date)"
    print(f"  {slug:40s} blocks={len(spans)} lines={[f'{s + 1}-{e}' for s, e in spans]} latest_close={latest}")
    if slug in new_pointers:
        print(f"    pointer: {new_pointers[slug][:160]}")
if not APPLY:
    print("DRY RUN. Re-run with --apply to write.")
    sys.exit(0)
assert LANES.read_bytes() == raw_lanes and CLOSED.read_bytes() == raw_closed, "a file changed on disk during the run; nothing written"
CLOSED.write_bytes(new_closed.encode("utf-8"))
LANES.write_bytes(new_lanes.encode("utf-8"))
print("WROTE lanes.md and lanes_closed.md")
