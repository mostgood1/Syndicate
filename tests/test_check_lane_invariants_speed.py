"""Lane `lane-invariants-speed-2` (2026-11-17): the faster forms give the SAME answers.

Three rewrites in `check_lane_invariants.py` / `lane_claims.py`, each pinned here
against a verbatim copy of the code it replaced (`2bc967e2f`):

  * `heading_slugs_in_bytes` + `_ledger_bytes` -- the archive headings found in
    the raw bytes, where `_ledger_text` decoded and newline-translated ~9 MB;
  * `upstream_lane_slugs(..., wanted=...)` -- origin/main's `lanes.md` first,
    the other three ledger files only when a wanted slug is still missing;
  * `lane_claims.claim_groups` -- compares only spellings that can be the same
    file, not all ~61,000 pairs.
"""
from __future__ import annotations

import collections
import importlib.util
import io
import pathlib
import random
import re
import shutil
import subprocess
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / ".claude" / "hooks"))
import lane_claims  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "check_lane_invariants_speed", _ROOT / "scripts" / "check_lane_invariants.py")
cli = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cli)

BOM = "﻿"


# --- reference copies of the replaced code (2bc967e2f) ------------------------


def _ref_heading_slugs(text):
    return re.findall(r"(?m)^###\s+([A-Za-z0-9._-]+)", text)


def _ref_ledger_text(root, name):
    try:
        return (root / name).read_text(encoding="utf-8", errors="replace").lstrip(BOM)
    except OSError:
        return ""


def _ref_orphaned_lane_markers(text, path):
    root = pathlib.Path(path).resolve().parent
    live = set(re.findall(r"(?m)^###\s+([A-Za-z0-9._-]+)", text))
    archived = set(_ref_heading_slugs(
        _ref_ledger_text(root, "lanes_closed.md")
        + _ref_ledger_text(root, "lanes_closed_archive.md")
        + _ref_ledger_text(root, "lanes_history.md")))
    missing, stale = [], []
    for marker in sorted(root.glob(".current-lane.*")):
        try:
            slug = marker.read_text(encoding="utf-8", errors="replace").lstrip(BOM).strip()
        except OSError:
            continue
        if not slug or slug in live:
            continue
        (stale if slug in archived else missing).append((slug, marker.name))
    return missing, stale


def _ref_claim_groups(by_spelling):
    spellings = sorted(by_spelling)
    parent = {s: s for s in spellings}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i, a in enumerate(spellings):
        for b in spellings[i + 1:]:
            if lane_claims.same_file(a, b):
                ra, rb = find(a), find(b)
                if ra != rb:
                    parent[rb] = ra
    grouped = {}
    for s in spellings:
        root = find(s)
        names, slugs = grouped.setdefault(root, (set(), set()))
        names.add(s)
        slugs.update(by_spelling[s])
    return [(sorted(n), sorted(s)) for n, s in grouped.values()]


# --- the whitespace list is exactly what `re` calls \s --------------------------


def test_whitespace_list_is_every_char_a_str_pattern_calls_whitespace():
    """Exhaustive over Unicode (~1.5 s): a Python whose `\\s` gains a character fails here."""
    every = "".join(chr(c) for c in range(0x110000) if re.match(r"\s", chr(c)))
    assert cli._STR_WHITESPACE == every


# --- heading_slugs_in_bytes == the text-mode read --------------------------------

FRAGMENTS = [b"###", b"####", b"#", b"\n", b"\r", b"\r\n", b" ", b"\t", b"slug-a", b"x.y_z",
             b"9", b"\xef\xbb\xbf", b"\xff", b"\xc2", b"\xe2\x80", b"\x85", b"\xc2\x85",
             b"\xc2\xa0", b"\xe2\x80\xa8", b"\xe3\x80\x80", b"\xe1\x9a\x80", b"\x1c", b"\x0b",
             "é".encode(), b"(", b"`", b"--"]


def _text_mode(tmp_path, raws):
    """What the old reader saw: each file read in text mode, BOM-stripped, joined."""
    out = []
    for i, raw in enumerate(raws):
        p = tmp_path / f"f{i}.md"
        p.write_bytes(raw)
        out.append(_ref_ledger_text(tmp_path, p.name))
    return "".join(out)


def _strip_bom(raw):
    while raw.startswith(BOM.encode()):
        raw = raw[3:]
    return raw


EDGE_DOCS = [
    b"", b"###", b"### a", b"\n### b", b"x\r\n### c\r\n### d", b"x\r### e", b"\r\r### f",
    b"###\r\n   g", b"###\r h", b"### \xc2\xa0i", b"###\xe2\x80\xa8j", b"###\x85k", b"###\xc2\x85l",
    b"\xef\xbb\xbf### m", b"\xef\xbb\xbf\xef\xbb\xbf### n", b"####o", b"x### p", b"\xff\n### q",
    b"\xe2\x80\n### r", b"### s\xe2\x80\xa8t", b"### u\r", b"text\n\n###\n", b"### " + "é".encode(),
    b"\n###\x1c\x1dv", b"###\x0bw\n###\x0cx", b"\xe2\n###\xe3\x80\x80y",
]


@pytest.mark.parametrize("raw", EDGE_DOCS)
def test_bytes_scan_equals_text_mode_on_edge_cases(tmp_path, raw):
    want = _ref_heading_slugs(_text_mode(tmp_path, [raw]))
    assert cli.heading_slugs_in_bytes(_strip_bom(raw), b"\n\r") == want


def _text_mode_in_memory(raws):
    """`_text_mode` without the disk: `open()` in text mode is this same TextIOWrapper
    (UTF-8, errors="replace", universal newlines) over a byte stream."""
    return "".join(io.TextIOWrapper(io.BytesIO(raw), encoding="utf-8", errors="replace").read().lstrip(BOM)
                   for raw in raws)


def test_the_in_memory_reader_is_the_file_reader(tmp_path):
    for raw in EDGE_DOCS:
        assert _text_mode_in_memory([raw]) == _text_mode(tmp_path, [raw])


def test_bytes_scan_equals_text_mode_on_random_documents():
    rng = random.Random(20261117)
    for i in range(3000):
        raws = [b"".join(rng.choice(FRAGMENTS) for _ in range(rng.randint(0, 40)))
                for _ in range(rng.randint(1, 3))]
        want = _ref_heading_slugs(_text_mode_in_memory(raws))
        got = cli.heading_slugs_in_bytes(b"".join(_strip_bom(r) for r in raws), b"\n\r")
        assert got == want, raws


def test_lf_only_mode_equals_the_old_upstream_decode():
    """`git cat-file` output was decoded, never newline-translated: a CR is not a line start."""
    rng = random.Random(7)
    for raw in EDGE_DOCS + [b"".join(rng.choice(FRAGMENTS) for _ in range(30)) for _ in range(800)]:
        want = _ref_heading_slugs(raw.decode("utf-8", "replace").lstrip(BOM))
        assert cli.heading_slugs_in_bytes(_strip_bom(raw), b"\n") == want, raw


@pytest.mark.skipif(not (_ROOT / ".syndicate" / "lanes_history.md").exists(), reason="no ledger")
def test_bytes_scan_equals_text_mode_on_this_trees_archives():
    root = _ROOT / ".syndicate"
    names = ("lanes_closed.md", "lanes_closed_archive.md", "lanes_history.md")
    want = _ref_heading_slugs("".join(_ref_ledger_text(root, n) for n in names))
    got = cli.heading_slugs_in_bytes(b"".join(cli._ledger_bytes(root, n) for n in names), b"\n\r")
    assert got == want and len(want) > 100


# --- orphaned_lane_markers: same verdicts --------------------------------------


def _ledger_dir(tmp_path, lanes, archives, markers):
    d = tmp_path / ".syndicate"
    d.mkdir()
    (d / "lanes.md").write_text(lanes, encoding="utf-8")
    for name, raw in archives.items():
        (d / name).write_bytes(raw)
    for sid, body in markers.items():
        (d / f".current-lane.{sid}").write_bytes(body)
    return d / "lanes.md"


def test_marker_verdicts_match_on_crlf_cr_bom_archives(tmp_path):
    path = _ledger_dir(
        tmp_path,
        lanes="## OPEN\n\n### live-one — OPEN\n",
        archives={
            "lanes_closed.md": b"\xef\xbb\xbf### closed-crlf \xe2\x80\x94 CLOSED\r\nbody\r\n",
            "lanes_closed_archive.md": b"x\r### closed-lone-cr \xe2\x80\x94 CLOSED",
            "lanes_history.md": b"### history-nbsp\xc2\xa0x\n###\xc2\xa0nbsp-slug\n",
        },
        markers={"a": b"live-one\n", "b": b"closed-crlf", "c": b"\xef\xbb\xbfclosed-lone-cr\r\n",
                 "d": b"", "e": b"  \n", "f": b"nbsp-slug", "g": b"never-written",
                 "h": b"history-nbsp"},
    )
    text = path.read_text(encoding="utf-8")
    want = _ref_orphaned_lane_markers(text, str(path))
    assert cli.orphaned_lane_markers(text, str(path)) == want
    assert want[1] and want[0]  # both outcomes are populated: stale AND missing


def test_no_marker_needing_the_archives_reads_none(tmp_path, monkeypatch):
    """Lazy: the archives are read only when some marker names a non-live lane."""
    path = _ledger_dir(tmp_path, "### live-one — OPEN\n", {"lanes_history.md": b"### x\n"},
                       {"a": b"live-one", "b": b""})
    reads = []
    monkeypatch.setattr(cli, "_ledger_bytes", lambda root, name: reads.append(name) or b"")
    assert cli.orphaned_lane_markers(path.read_text(encoding="utf-8"), str(path)) == ([], [])
    assert reads == []


@pytest.mark.skipif(not (_ROOT / ".syndicate" / "lanes.md").exists(), reason="no ledger")
def test_marker_verdicts_match_on_this_tree():
    path = _ROOT / ".syndicate" / "lanes.md"
    text = path.read_text(encoding="utf-8", errors="replace")
    assert cli.orphaned_lane_markers(text, str(path)) == _ref_orphaned_lane_markers(text, str(path))


# --- claim_groups: same groups, same order --------------------------------------


def _random_spellings(rng):
    dirs = ["scripts", "tests", "syndicate/features/nba", "syndicate/features/mlb", "docs/ai_context",
            ".syndicate", "pipeline", "tests/fixtures/box"]
    files = ["cards.py", "live_lens.py", "todo.md", "check.py", "a.json", "state.md", "x.py"]
    out = collections.defaultdict(set)
    for _ in range(rng.randint(1, 60)):
        kind = rng.random()
        if kind < 0.1:
            s = rng.choice(dirs) + "/"
        elif kind < 0.3:
            s = rng.choice(files)
        else:
            s = "/".join(rng.sample(dirs, rng.randint(1, 2))) + "/" + rng.choice(files)
        out[s].add(rng.choice(["lane-a", "lane-b", "lane-c", "lane-d"]))
    return dict(out)


def test_claim_groups_match_all_pairs_on_random_spellings():
    rng = random.Random(61000)
    for _ in range(400):
        by = _random_spellings(rng)
        assert lane_claims.claim_groups(by) == _ref_claim_groups(by), by


@pytest.mark.skipif(not (_ROOT / ".syndicate" / "lanes.md").exists(), reason="no ledger")
def test_claim_groups_match_all_pairs_on_the_live_ledger():
    text = (_ROOT / ".syndicate" / "lanes.md").read_text(encoding="utf-8", errors="replace")
    by = lane_claims.claims_by_path(text)
    assert len(by) > 50
    assert lane_claims.claim_groups(by) == _ref_claim_groups(by)


# --- sections_are_disjoint: narrowed holders, same answer --------------------------


def _lane(slug, files):
    return (f"### {slug} — OPEN — opened 2026-11-17 — session s-{slug}\n"
            f"- Goal: g\n- Files: {files}\n- Blocked by: none")


def test_narrowed_holders_give_the_unnarrowed_answer_with_directory_claims():
    text = "## OPEN\n\n" + "\n\n".join([
        _lane("dir-a", "`tests/fixtures/box/` (the box fixtures only)"),
        _lane("dir-b", "`tests/fixtures/` (the fixture root only)"),
        _lane("file-a", "`tests/fixtures/box/x.py` (the x section only), `y.md`"),
        _lane("bare-b", "`x.py` (the bare x section only)"),
        _lane("plain-c", "`tests/fixtures/box/x.py`, `docs/y.md` (the y doc only)"),
    ]) + "\n"
    entries = list(lane_claims._section_entries(text))
    holders = list(lane_claims._claims(text))
    rels = ["tests/fixtures/box/", "tests/fixtures/box/x.py", "x.py", "tests/fixtures/", "docs/y.md",
            "y.md", "other/x.py", "tests/fixtures/box/z.json"]
    slugs = sorted({s for s, _ in holders})
    asked = answered = 0
    for rel in rels:
        for slug in slugs:
            want = lane_claims.sections_are_disjoint_among(entries, holders, slug, rel)
            assert lane_claims.sections_are_disjoint(text, slug, rel) == want, (slug, rel)
            asked += 1
            answered += want is not None
    assert asked == len(rels) * len(slugs) and answered > 0  # both outcomes occur


# --- upstream_lane_slugs(wanted=...) -----------------------------------------------

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git not on PATH")


@pytest.fixture(scope="module")
def upstream_repo(tmp_path_factory):
    repo = tmp_path_factory.mktemp("upstream2")
    subprocess.run(["git", "init", "-q", str(repo)], check=True, capture_output=True)
    files = {"lanes.md": "### live-one — OPEN\n### live-two — OPEN\n",
             "lanes_closed.md": "### closed-one — CLOSED\r\n",
             "lanes_history.md": "﻿### trimmed-one — CLOSED\n"}
    stream = b"commit refs/remotes/origin/main\ncommitter t <t@example.invalid> 1700000000 +0000\ndata 1\nx\n"
    for name, body in files.items():
        raw = body.encode("utf-8")
        stream += b"M 100644 inline .syndicate/%s\ndata %d\n%s\n" % (name.encode(), len(raw), raw)
    subprocess.run(["git", "-C", str(repo), "fast-import", "--quiet"], input=stream, check=True,
                   capture_output=True)
    (repo / ".syndicate").mkdir()
    return repo / ".syndicate"


@needs_git
@pytest.mark.parametrize("wanted,batches", [
    ({"live-one"}, 1),                       # lanes.md answers it: one fetch
    ({"live-one", "live-two"}, 1),
    ({"live-one", "trimmed-one"}, 2),        # history needed: the second fetch
    ({"never-written"}, 2),
    ({"closed-one"}, 2),
])
def test_wanted_answers_membership_exactly(upstream_repo, monkeypatch, wanted, batches):
    full = cli.upstream_lane_slugs(upstream_repo)
    assert full == {"live-one", "live-two", "closed-one", "trimmed-one"}
    calls = []
    real = cli._upstream_batch
    monkeypatch.setattr(cli, "_upstream_batch", lambda *a: calls.append(a[2]) or real(*a))
    got = cli.upstream_lane_slugs(upstream_repo, wanted=wanted)
    assert {s: s in got for s in wanted} == {s: s in full for s in wanted}
    assert len(calls) == batches


@needs_git
def test_wanted_keeps_none_for_an_unknown_upstream(upstream_repo, tmp_path, monkeypatch):
    assert cli.upstream_lane_slugs(upstream_repo, "no-such-ref", wanted={"x"}) is None
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    (tmp_path / ".syndicate").mkdir()
    assert cli.upstream_lane_slugs(tmp_path / ".syndicate", wanted={"x"}) is None
