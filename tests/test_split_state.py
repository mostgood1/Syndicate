"""Tests for `scripts/split_state.py`.

REACHABILITY FIRST. This tool rewrites the repo's source of truth into ten
files; its four verification checks are the only thing standing between a
classification bug and a silently mangled ledger. So each check gets a test
that makes it FIRE, not just one that watches it pass.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("split_state", ROOT / "scripts" / "split_state.py")
ss = importlib.util.module_from_spec(spec)
sys.modules["split_state"] = ss
spec.loader.exec_module(ss)

DOC = """## [mlb-thing] MLB SUBJECT

MLB body with `abc1234` in it.

## [polymarket-thing] VENUE SUBJECT

Venue body.

## [how-to-use] HOW TO USE THIS FILE

Instructions.

## [refresh-worker-memory] WORKER SUBJECT

Worker body.
"""


def setup(tmp_path, monkeypatch, text=DOC, crlf=False):
    syn = tmp_path / ".syndicate"
    syn.mkdir()
    p = syn / "state.md"
    p.write_bytes(text.replace("\n", "\r\n").encode() if crlf else text.encode())
    monkeypatch.setattr(ss, "SYN", syn)
    monkeypatch.setattr(ss, "STATE", p)
    monkeypatch.chdir(tmp_path)
    return p


# --- classification -----------------------------------------------------

def test_root_sections_stay_in_state_md():
    assert ss.classify("how-to-use") == "root"
    assert ss.classify("user-decisions") == "root"


def test_sport_wins_over_generic():
    """Ordering matters: an MLB section about the simulator belongs with MLB,
    not in the generic model bucket."""
    assert ss.classify("mlb-sim-edge-is-anti-predictive") == "mlb"
    assert ss.classify("soccer-shots-prop-skill") == "soccer"


def test_specific_wins_over_the_bucket_it_came_from():
    """The board re-split's rule order, asserted because two of these are
    genuinely ambiguous and a reorder would silently misfile them.

    `portfolio-live-surface` contains 'surface' and must NOT go to ui;
    `ui-board-cards` contains 'board' and must NOT stay in board."""
    assert ss.classify("portfolio-live-surface") == "portfolio"
    assert ss.classify("ui-board-cards") == "ui"
    assert ss.classify("board-chip-coverage") == "layer2"
    assert ss.classify("live-surface-tier5") == "ui"
    # what deliberately STAYS on the build side
    assert ss.classify("week-scoped-board-window") == "board"
    assert ss.classify("board-freshness") == "board"
    assert ss.classify("locked-cards-retuned-no-autorun") == "board"


def test_overrides_beat_rules():
    """The 19 a keyword sweep could not place are assigned by hand."""
    # retargeted board -> ui in the 2026-09-03 board re-split: it is a product
    # SURFACE, and what stayed in `board` is the build side.
    assert ss.classify("ask-the-syndicate") == "ui"
    assert ss.classify("fleet") == "worker"
    assert ss.classify("replay-diff-gate") == "model"


def test_nothing_falls_through_on_the_real_file():
    """'misc' is the bucket that means 'nobody decided'. If the live file ever
    produces one, the split should not be run until it is assigned."""
    real = ROOT / ".syndicate" / "state.md"
    if not real.exists():
        return
    text = real.read_bytes().decode("utf-8-sig").replace("\r\n", "\n")
    _pre, secs = ss.parse(text.split("\n"))
    misc = [s for s, _t, _b in secs if ss.classify(s) == "misc"]
    assert misc == [], f"unassigned subjects: {misc}"


# --- REACHABILITY of each verification check ----------------------------

def test_verify_passes_on_a_faithful_split(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch)
    lines = DOC.split("\n")
    pre, secs = ss.parse(lines)
    files, _b = ss.build(pre, secs)
    assert ss.verify(lines, secs, files) == []


def test_verify_FIRES_when_a_body_is_dropped(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch)
    lines = DOC.split("\n")
    pre, secs = ss.parse(lines)
    files, _b = ss.build(pre, secs)
    victim = next(p for p in files if p.name == "state_mlb.md")
    files[victim] = "# emptied\n"
    bad = ss.verify(lines, secs, files)
    assert any("body for [mlb-thing]" in b for b in bad), bad


def test_verify_FIRES_when_a_body_is_duplicated(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch)
    lines = DOC.split("\n")
    pre, secs = ss.parse(lines)
    files, _b = ss.build(pre, secs)
    a = next(p for p in files if p.name == "state_mlb.md")
    b = next(p for p in files if p.name == "state_polymarket.md")
    files[b] = files[b] + files[a]
    bad = ss.verify(lines, secs, files)
    assert any("appears 2x" in x or "not globally unique" in x for x in bad), bad


def test_verify_FIRES_on_a_lost_line(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch)
    lines = DOC.split("\n")
    pre, secs = ss.parse(lines)
    files, _b = ss.build(pre, secs)
    victim = next(p for p in files if p.name == "state_worker.md")
    files[victim] = files[victim].replace("Worker body.", "")
    bad = ss.verify(lines, secs, files)
    assert bad, "dropping a line must be refused"


# --- apply / idempotence ------------------------------------------------

def test_apply_writes_parts_and_index(tmp_path, monkeypatch):
    p = setup(tmp_path, monkeypatch)
    assert ss.main(["--apply"]) == 0
    out = p.read_text(encoding="utf-8")
    assert "[subject-index]" in out
    assert "[how-to-use]" in out          # root section stayed
    assert "MLB body" not in out          # body moved out
    assert "MLB body" in (tmp_path / ".syndicate" / "state_mlb.md").read_text(encoding="utf-8")


def test_how_to_use_leads_state_md(tmp_path, monkeypatch):
    p = setup(tmp_path, monkeypatch)
    ss.main(["--apply"])
    out = p.read_text(encoding="utf-8")
    assert out.index("[how-to-use]") < out.index("[subject-index]")


def test_second_apply_REFUSES(tmp_path, monkeypatch):
    """Re-splitting an already-split file would rewrite the index to cover only
    what is left in state.md and orphan every part."""
    setup(tmp_path, monkeypatch)
    assert ss.main(["--apply"]) == 0
    assert ss.main(["--apply"]) == 1


def test_reindex_needs_an_existing_index(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch)
    assert ss.main(["--reindex"]) == 1


def test_reindex_recovers_a_subject_added_to_a_part(tmp_path, monkeypatch):
    p = setup(tmp_path, monkeypatch)
    ss.main(["--apply"])
    part = tmp_path / ".syndicate" / "state_mlb.md"
    part.write_text(part.read_text(encoding="utf-8") + "\n## [mlb-new] A NEW SUBJECT\n\nbody\n",
                    encoding="utf-8")
    assert "[mlb-new]" not in p.read_text(encoding="utf-8")
    assert ss.main(["--reindex", "--apply"]) == 0
    assert "[mlb-new]" in p.read_text(encoding="utf-8")


# --- resplit ------------------------------------------------------------

RESPLIT_DOC = """# state — venues

header prose.

## [polymarket-thing] PM SUBJECT

PM body.

## [kalshi-thing] K SUBJECT

K body.

## [venue-fee-economics] GENERIC VENUE SUBJECT

Generic body.
"""


def test_resplit_moves_by_the_current_rules(tmp_path, monkeypatch):
    syn = tmp_path / ".syndicate"
    syn.mkdir()
    monkeypatch.setattr(ss, "SYN", syn)
    monkeypatch.setattr(ss, "STATE", syn / "state.md")
    monkeypatch.chdir(tmp_path)
    src = syn / "state_venues.md"
    src.write_text(RESPLIT_DOC, encoding="utf-8")

    assert ss.resplit(src, True) == 0
    left = src.read_text(encoding="utf-8")
    assert "Generic body." in left          # still belongs to venues
    assert "PM body." not in left           # moved out
    assert "PM body." in (syn / "state_polymarket.md").read_text(encoding="utf-8")
    assert "K body." in (syn / "state_kalshi.md").read_text(encoding="utf-8")
    assert "header prose." in left          # preamble preserved


def test_resplit_appends_to_an_existing_target(tmp_path, monkeypatch):
    """A target that already exists must be APPENDED to, never clobbered."""
    syn = tmp_path / ".syndicate"
    syn.mkdir()
    monkeypatch.setattr(ss, "SYN", syn)
    monkeypatch.setattr(ss, "STATE", syn / "state.md")
    monkeypatch.chdir(tmp_path)
    src = syn / "state_venues.md"
    src.write_text(RESPLIT_DOC, encoding="utf-8")
    (syn / "state_polymarket.md").write_text(
        "# state — polymarket\n\n## [polymarket-existing] ALREADY HERE\n\nkeep me.\n",
        encoding="utf-8")

    assert ss.resplit(src, True) == 0
    pm = (syn / "state_polymarket.md").read_text(encoding="utf-8")
    assert "keep me." in pm, "existing target content was clobbered"
    assert "PM body." in pm


def test_resplit_is_a_noop_when_nothing_reclassifies(tmp_path, monkeypatch):
    syn = tmp_path / ".syndicate"
    syn.mkdir()
    monkeypatch.setattr(ss, "SYN", syn)
    monkeypatch.setattr(ss, "STATE", syn / "state.md")
    monkeypatch.chdir(tmp_path)
    src = syn / "state_mlb.md"
    src.write_text("# state — mlb\n\n## [mlb-thing] X\n\nbody.\n", encoding="utf-8")
    before = src.read_bytes()
    assert ss.resplit(src, True) == 0
    assert src.read_bytes() == before


def test_resplit_refuses_a_missing_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert ss.resplit(tmp_path / "nope.md", True) == 1


# --- line endings -------------------------------------------------------

def test_crlf_round_trips(tmp_path, monkeypatch):
    p = setup(tmp_path, monkeypatch, crlf=True)
    assert ss.main(["--apply"]) == 0
    for f in (tmp_path / ".syndicate").glob("state*.md"):
        d = f.read_bytes()
        assert d.count(b"\n") == d.count(b"\r\n"), f"{f.name} has mixed endings"


def test_lf_file_stays_lf(tmp_path, monkeypatch):
    p = setup(tmp_path, monkeypatch)
    assert ss.main(["--apply"]) == 0
    for f in (tmp_path / ".syndicate").glob("state*.md"):
        assert b"\r" not in f.read_bytes()


# --- reindex must not truncate below the table --------------------------
#
# THE INCIDENT THESE PIN. 2026-09-04, lane `sim-clv-decomposition`: running
# `--reindex --apply` to register ONE new subject deleted 55 lines of another
# session's uncommitted `### [web-oom-leak]` UPDATE block, appended below the
# index table. The block was in no commit on any branch. `reindex()` rebuilt
# the file as `head + body[:hdr+1] + rows + [""]` and simply never re-emitted
# `body[hdr+1:]`. It printed "WROTE state.md (index rebuilt)" and exited 0.
#
# Three properties are pinned here, and each test FAILS on the pre-fix code:
#   1. content below the table survives byte-identically
#   2. the real `.syndicate/state.md` corpus survives (it carries such a tail)
#   3. a post-table region that cannot be classified REFUSES rather than writes

SPLIT_STATE = """# state

## [how-to-use] HOW TO USE THIS FILE

Instructions.

## [subject-index] SUBJECT INDEX — every subject, and which file holds it

prose about the index.

| subject | title | file |
|---|---|---|
| [how-to-use] | HOW TO USE THIS FILE | `state.md` |
| [mlb-thing] | MLB SUBJECT | `state_mlb.md` |
"""

TAIL = """
### `[web-oom-leak]` UPDATE — appended below the table by another session

**Supersedes the line above.** Body text with `backticks`, an em-dash — and a
| pipe that does not start the line.

* bullet one
* bullet two
"""


def split_setup(tmp_path, monkeypatch, tail="", crlf=False, state=SPLIT_STATE):
    """An ALREADY-SPLIT tree: state.md with an index, plus one part file."""
    syn = tmp_path / ".syndicate"
    syn.mkdir()
    text = state + tail
    (syn / "state.md").write_bytes(
        text.replace("\n", "\r\n").encode() if crlf else text.encode())
    part = "# state — mlb\n\n## [mlb-thing] MLB SUBJECT\n\nbody.\n"
    (syn / "state_mlb.md").write_bytes(
        part.replace("\n", "\r\n").encode() if crlf else part.encode())
    monkeypatch.setattr(ss, "SYN", syn)
    monkeypatch.setattr(ss, "STATE", syn / "state.md")
    monkeypatch.chdir(tmp_path)
    return syn


def test_table_span_stops_at_the_first_non_row():
    """The table is the CONTIGUOUS run of rows after `|---`, not every `| [`
    line in the file. The old code had no notion of where the table ended."""
    lines = (SPLIT_STATE + TAIL).split("\n")
    start = next(i for i, l in enumerate(lines) if l.startswith("## [subject-index]"))
    sep, end = ss.table_span(lines, start)
    assert lines[sep].startswith("|---")
    assert end - sep - 1 == 2, "expected exactly the 2 contiguous rows"
    assert not lines[end].startswith("| [")


def test_table_span_reports_a_missing_separator():
    assert ss.table_span(["## [subject-index] X", "no table here"], 0) == (None, None)


def test_reindex_PRESERVES_content_below_the_table(tmp_path, monkeypatch):
    """THE REGRESSION PIN. Everything below the table must come through
    byte-identical, while the table itself is rebuilt."""
    syn = split_setup(tmp_path, monkeypatch, tail=TAIL)
    # the reason anyone runs --reindex: a subject was added to a part
    part = syn / "state_mlb.md"
    part.write_text(part.read_text(encoding="utf-8")
                    + "\n## [mlb-new] A NEWLY ADDED SUBJECT\n\nnew body.\n",
                    encoding="utf-8")

    assert ss.main(["--reindex", "--apply"]) == 0
    out = (syn / "state.md").read_text(encoding="utf-8")

    assert "[mlb-new]" in out, "the index was not actually rebuilt"
    assert out.endswith(TAIL), "content below the index table was not preserved verbatim"


def test_reindex_preserves_a_tail_it_would_have_dropped(tmp_path, monkeypatch):
    """Byte-level: the region below the last row is unchanged, line for line."""
    syn = split_setup(tmp_path, monkeypatch, tail=TAIL)
    before = (syn / "state.md").read_text(encoding="utf-8").split("\n")
    assert ss.main(["--reindex", "--apply"]) == 0
    after = (syn / "state.md").read_text(encoding="utf-8").split("\n")

    def tail_of(lines):
        start = next(i for i, l in enumerate(lines) if l.startswith("## [subject-index]"))
        _sep, end = ss.table_span(lines, start)
        return lines[end:]

    assert tail_of(after) == tail_of(before)


def test_reindex_preserves_the_tail_of_the_REAL_state_md(tmp_path, monkeypatch):
    """Run it on the real corpus, in a copy. The live `.syndicate/state.md`
    carries exactly this shape -- UPDATE blocks appended below the table -- so
    a synthetic fixture alone would not prove the tool is safe to run today."""
    real = ROOT / ".syndicate" / "state.md"
    if not real.exists():
        return
    lines = real.read_bytes().decode("utf-8-sig").replace("\r\n", "\n").split("\n")
    start = next((i for i, l in enumerate(lines) if l.startswith("## [subject-index]")), None)
    if start is None:
        return
    _sep, end = ss.table_span(lines, start)
    tail = [l for l in lines[end:] if l.strip()]
    if not tail:
        return  # nothing appended below the table right now; nothing to pin

    syn = tmp_path / ".syndicate"
    syn.mkdir()
    for src in (ROOT / ".syndicate").glob("state*.md"):
        (syn / src.name).write_bytes(src.read_bytes())
    monkeypatch.setattr(ss, "SYN", syn)
    monkeypatch.setattr(ss, "STATE", syn / "state.md")
    monkeypatch.chdir(tmp_path)

    assert ss.main(["--reindex", "--apply"]) == 0
    out = (syn / "state.md").read_bytes().decode("utf-8-sig").replace("\r\n", "\n")
    missing = [l for l in tail if l not in out]
    assert not missing, (
        f"{len(missing)} of {len(tail)} non-blank line(s) below the real index "
        f"table were lost, e.g. {missing[0][:70]!r}")


def test_reindex_tail_survives_crlf(tmp_path, monkeypatch):
    syn = split_setup(tmp_path, monkeypatch, tail=TAIL, crlf=True)
    assert ss.main(["--reindex", "--apply"]) == 0
    data = (syn / "state.md").read_bytes()
    assert b"bullet two" in data
    assert data.count(b"\n") == data.count(b"\r\n"), "mixed line endings"


def test_reindex_still_normalises_a_blank_only_tail(tmp_path, monkeypatch):
    """No trailing content: behave exactly as before -- one trailing newline."""
    syn = split_setup(tmp_path, monkeypatch, tail="\n\n\n")
    assert ss.main(["--reindex", "--apply"]) == 0
    out = (syn / "state.md").read_bytes()
    assert out.endswith(b"| `state_mlb.md` |\n")


# --- the unknown post-table region must REFUSE, not write ---------------

def test_reindex_REFUSES_stray_rows_below_the_table(tmp_path, monkeypatch):
    """`learnings.md`: an unknown must not default onto the permissive branch.

    Index-shaped rows separated from the table by other content cannot be
    classified -- stale rows to replace, or content to keep? Refuse, and leave
    the file alone."""
    syn = split_setup(
        tmp_path, monkeypatch,
        tail="\n### a block\n\nprose.\n\n| [orphan-subject] | STRANDED ROW | `state_mlb.md` |\n")
    before = (syn / "state.md").read_bytes()
    assert ss.main(["--reindex", "--apply"]) == 1
    assert (syn / "state.md").read_bytes() == before, "REFUSED but wrote anyway"


def test_reindex_line_guard_FIRES_on_a_reintroduced_truncation(tmp_path, monkeypatch):
    """REACHABILITY of the runtime guard, not just of the splice.

    Simulate the exact regression by making `table_span` claim the table runs
    to EOF -- which is what the old `[l for l in ... if not l.startswith('| [')]`
    filter effectively did. The guard must catch it and write nothing."""
    syn = split_setup(tmp_path, monkeypatch, tail=TAIL)
    before = (syn / "state.md").read_bytes()

    real_span = ss.table_span
    monkeypatch.setattr(ss, "table_span",
                        lambda lines, start: (real_span(lines, start)[0], len(lines)))

    assert ss.main(["--reindex", "--apply"]) == 1
    assert (syn / "state.md").read_bytes() == before, "guard fired but wrote anyway"


def test_reindex_dry_run_writes_nothing_with_a_tail(tmp_path, monkeypatch):
    syn = split_setup(tmp_path, monkeypatch, tail=TAIL)
    before = (syn / "state.md").read_bytes()
    assert ss.main(["--reindex"]) == 0
    assert (syn / "state.md").read_bytes() == before


def test_reindex_normalises_a_MIXED_ending_tail(tmp_path, monkeypatch):
    """The live file's real shape, pinned. Measured 2026-09-04: `state.md` was
    CRLF for 580 lines and bare LF for the 55 appended tail lines, because the
    appending session's tool wrote LF. Preservation is of CONTENT -- every line
    survives -- and endings come out uniform. This exists so the whole-tail
    diff that produces is never mistaken for a content loss."""
    syn = tmp_path / ".syndicate"
    syn.mkdir()
    head = SPLIT_STATE.replace("\n", "\r\n").encode()   # CRLF body
    tail = TAIL.encode()                                 # bare-LF tail
    (syn / "state.md").write_bytes(head + tail)
    (syn / "state_mlb.md").write_bytes(
        b"# state - mlb\r\n\r\n## [mlb-thing] MLB SUBJECT\r\n\r\nbody.\r\n")
    monkeypatch.setattr(ss, "SYN", syn)
    monkeypatch.setattr(ss, "STATE", syn / "state.md")
    monkeypatch.chdir(tmp_path)

    before = (syn / "state.md").read_bytes()
    assert before.count(b"\n") > before.count(b"\r\n"), "fixture is not mixed"

    assert ss.main(["--reindex", "--apply"]) == 0
    after = (syn / "state.md").read_bytes()

    # every line survives ...
    assert before.replace(b"\r\n", b"\n") == after.replace(b"\r\n", b"\n")
    # ... and the endings are now uniform, not mixed
    assert after.count(b"\n") == after.count(b"\r\n")
