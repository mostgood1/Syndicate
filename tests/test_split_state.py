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


def test_overrides_beat_rules():
    """The 19 a keyword sweep could not place are assigned by hand."""
    assert ss.classify("ask-the-syndicate") == "board"
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
