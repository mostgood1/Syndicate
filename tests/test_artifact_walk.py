"""The grouped artifact walk must return EXACTLY what the naive loop returns.

`#632`: `/api/ops/artifacts/export` had a 26 s median and an 87 s max, and
`?names_only=1` -- which reads no file bodies -- timed out after 180 s. The cost
is the directory walk: 176 patterns collapsing onto 95 parents, with the busiest
directory named by 18 separate patterns and therefore listed 18 times per sport.

These tests exist to make the optimisation LANDABLE BY SOMEONE ELSE: it is an
I/O change, so the thing that has to be proved is that the file set is
byte-identical to `for p in patterns: root.glob(p)`. Every case below compares
against that reference implementation rather than against a hand-written
expectation.
"""

from __future__ import annotations

import os

import pytest

from syndicate.features.shared.artifact_walk import (
    group_patterns_by_parent,
    iter_pattern_matches,
    patterns_that_can_match,
)


def _naive(root, patterns):
    """The loop being replaced, as the reference."""
    out = []
    for pattern in patterns:
        for path in root.glob(pattern):
            if path.is_file() and str(path) not in out:
                out.append(str(path))
    return sorted(out)


def _grouped(root, patterns):
    return sorted(str(p) for p in iter_pattern_matches(root, patterns))


@pytest.fixture
def tree(tmp_path):
    """A miniature of the real shape: a wildcard first segment over sports."""
    for sport in ("mlb", "nba", "wnba"):
        for sub in ("source_artifacts/data/processed", "data/live_lens"):
            d = tmp_path / f"{sport}_source" / sub
            d.mkdir(parents=True)
            for name in ("alpha_2026_09_07.json", "beta_2026_09_07.json", "notes.txt"):
                (d / name).write_text("{}", encoding="utf-8")
    (tmp_path / "mlb_source" / "source_artifacts" / "data" / "processed" / "sub").mkdir()
    return tmp_path


PATTERNS = [
    "*_source/source_artifacts/data/processed/alpha_*.json",
    "*_source/source_artifacts/data/processed/beta_*.json",
    "*_source/data/live_lens/alpha_*.json",
]


def test_it_returns_exactly_what_the_naive_loop_returns(tree):
    assert _grouped(tree, PATTERNS) == _naive(tree, PATTERNS)
    assert len(_grouped(tree, PATTERNS)) == 9      # 3 sports x (2 + 1)


def test_overlapping_patterns_in_one_directory_do_not_double_count(tree):
    # `*.json` and `alpha_*.json` both match the same file. The caller writes
    # into a dict keyed by path, so the naive loop de-duplicates implicitly --
    # this must too, or a byte budget would be charged twice for one file.
    overlapping = [
        "*_source/source_artifacts/data/processed/*.json",
        "*_source/source_artifacts/data/processed/alpha_*.json",
    ]
    grouped = _grouped(tree, overlapping)
    assert grouped == _naive(tree, overlapping)
    assert len(grouped) == len(set(grouped))


def test_directories_are_not_returned_as_files(tree):
    # `processed/sub` is a directory matching no name pattern, but a careless
    # implementation that yields entries before `is_file()` would emit it.
    got = _grouped(tree, ["*_source/source_artifacts/data/processed/*"])
    assert all(not s.endswith("sub") for s in got)
    assert got == _naive(tree, ["*_source/source_artifacts/data/processed/*"])


def test_non_matching_extensions_are_excluded(tree):
    got = _grouped(tree, PATTERNS)
    assert all(not s.endswith("notes.txt") for s in got)


def test_a_pattern_with_no_directory_is_handled(tmp_path):
    (tmp_path / "top.json").write_text("{}", encoding="utf-8")
    assert _grouped(tmp_path, ["top.json"]) == _naive(tmp_path, ["top.json"])


def test_missing_directories_yield_nothing_rather_than_raising(tmp_path):
    assert _grouped(tmp_path, ["*_source/nope/deeper/*.json"]) == []


def test_an_unreadable_directory_is_skipped_not_raised(tree, monkeypatch):
    # A read-only export must return what it CAN see; one unreadable directory
    # must not fail the whole request.
    real = os.listdir

    def boom(path, *a, **k):
        if str(path).endswith("processed"):
            raise PermissionError("nope")
        return real(path, *a, **k)

    monkeypatch.setattr(os, "listdir", boom)
    got = _grouped(tree, PATTERNS)
    assert got, "the live_lens matches must still come back"
    assert all("processed" not in s for s in got)


# --- the syscall reduction, which is the entire point ------------------------

def test_each_directory_is_listed_once_however_many_patterns_share_it(tree):
    """The busiest real parent is named by 18 patterns. Currently that directory
    is listed 18 times per sport, per request."""
    many = [f"*_source/source_artifacts/data/processed/p{i}_*.json" for i in range(18)]
    many.append("*_source/source_artifacts/data/processed/alpha_*.json")

    counts = {"n": 0}
    real = os.listdir

    def counting(path, *a, **k):
        counts["n"] += 1
        return real(path, *a, **k)

    os.listdir = counting
    try:
        list(iter_pattern_matches(tree, many))
        grouped_calls = counts["n"]
    finally:
        os.listdir = real
    # Three sport directories, one listing each -- not 19 x 3.
    assert grouped_calls == 3, f"expected one listing per directory, got {grouped_calls}"


def test_grouping_preserves_pattern_order_within_a_parent():
    grouped = group_patterns_by_parent(["a/b/x_*.json", "a/b/y_*.json", "a/b/x_*.json"])
    assert grouped == {"a/b": ["x_*.json", "y_*.json"]}


# --- the subset pre-filter ---------------------------------------------------

def test_subset_prefilter_drops_directories_that_cannot_match():
    patterns = ["*_source/data/live_lens/a_*.json",
                "*_source/source_artifacts/data/processed/a_*.json"]
    kept = patterns_that_can_match(patterns, "*_source/data/live_lens/*.json")
    assert kept == ["*_source/data/live_lens/a_*.json"]


def test_subset_prefilter_is_conservative_when_it_cannot_tell():
    # Wrong here costs FILES, not time: this feeds a backup, so dropping a
    # pattern that could have matched loses an artifact silently.
    patterns = ["*_source/data/live_lens/a_*.json"]
    assert patterns_that_can_match(patterns, "") == patterns
    assert patterns_that_can_match(patterns, "reports/x.json") == []
    # A SEPARATOR-COUNT argument, not a depth argument. The subset is applied
    # with fnmatch, whose `*` crosses `/`, so a subset may be shallower than the
    # pattern and still match. What rules a pattern out is that its paths cannot
    # carry the literal separators the subset demands.
    assert patterns_that_can_match(["*/b/c/*.json"], "*/*/*/*/*.json") == []
    assert patterns_that_can_match(["*/b/c/*.json"], "*/*/*/*.json") == ["*/b/c/*.json"]
    # A bracket class is undecidable here, so it must be KEPT, never dropped.
    assert patterns_that_can_match(["a/b/c.json"], "a/[bc]*") == ["a/b/c.json"]


def test_a_SHALLOW_subset_keeps_DEEP_patterns_because_fnmatch_star_crosses_slash():
    """THE REGRESSION. `d5e4cc51` shipped a pre-filter that compared directory
    DEPTH, so `?pattern=wnba_source/*` dropped every `source_artifacts/data/...`
    family and the endpoint returned a SHORT ANSWER WITH NO ERROR -- on the
    endpoint most sessions use to verify production.

    Reported by lane `soccer-unfed-inputs`, bisected by
    `soccer-threeway-precision-gate`. The two sides never shared semantics: the
    patterns are globbed (`*` stops at `/`), the subset is applied with fnmatch
    (`*` crosses `/`)."""
    import fnmatch as fn
    deep = "*_source/source_artifacts/data/processed/recommendations*.json"
    path = "wnba_source/source_artifacts/data/processed/recommendations_slate_2026-07-13.json"
    assert fn.fnmatch(path, "wnba_source/*"), "premise: fnmatch's * crosses '/'"
    assert patterns_that_can_match([deep], "wnba_source/*") == [deep]


def test_the_prefilter_can_only_REMOVE_WORK_never_change_the_answer(tree):
    """The property that would have caught the regression, and the only one
    really worth asserting: pre-filter then post-filter must equal post-filter
    alone, for every subset. My original test asserted my ASSUMPTION about `*`
    rather than the caller's actual fnmatch call, so it passed while the code
    was wrong -- a test written from the same misreading as the code cannot
    catch that code."""
    import fnmatch as fn
    all_patterns = PATTERNS + [
        "*_source/source_artifacts/data/processed/notes.txt",
        "mlb_source/data/live_lens/beta_*.json",
    ]
    subsets = [
        "*_source/*",                       # shallow, spans segments
        "wnba_source/*",                    # the exact production failure
        "*_source/data/live_lens/*.json",
        "*/source_artifacts/*",
        "*.json",
        "mlb_source/*/*/*/*/*.json",
        "nope/*",
    ]

    def rel(path):
        return os.path.relpath(path, tree).replace("\\", "/")

    for subset in subsets:
        truth = sorted(x for x in _naive(tree, all_patterns) if fn.fnmatch(rel(x), subset))
        got = sorted(x for x in _grouped(tree, patterns_that_can_match(all_patterns, subset))
                     if fn.fnmatch(rel(x), subset))
        assert got == truth, f"subset {subset!r} changed the RESULT, not just the work"


def test_subset_prefilter_never_changes_the_result_it_only_saves_work(tree):
    subset = "*_source/data/live_lens/*.json"
    full = _grouped(tree, PATTERNS)
    narrowed = _grouped(tree, patterns_that_can_match(PATTERNS, subset))
    import fnmatch as fn
    expected = [p for p in full if fn.fnmatch(os.path.relpath(p, tree).replace("\\", "/"), subset)]
    assert sorted(narrowed) == sorted(expected)


# --- the soundness sweep over the REAL pattern list ---------------------------
# Contributed by lane `ncaaf-live-resim-wire`, who verified my `a0d02297` fix
# independently rather than reading its docstring, and then pointed out that
# every test above runs on a TOY pattern list. They were right: the shapes that
# break a hand-written wildcard automaton are the awkward production ones.

import fnmatch as fn
import itertools

from syndicate.features.shared.artifact_publisher import (
    EXPORT_ONLY_ARTIFACT_PATTERNS,
    HOT_ARTIFACT_PATTERNS,
)

# Fillers a real path segment can be. "" matters: `foo*.json` must be allowed to
# produce `foo.json`, and a filter that assumes >=1 char is wrong in the same
# direction as the original bug.
_FILLERS = ("x", "mlb", "2026-09-07", "a_b-c", "", "wnba_source", "12")


def _witnesses(pattern, cap=4):
    """Concrete paths this GLOB pattern can produce.

    Glob semantics, NOT fnmatch: `*` and `?` never cross '/'. A `[...]` class is
    collapsed to its first literal member, so the witness stays a path the
    pattern really produces -- substituting the class verbatim would forge a
    witness and could fail this test on a CORRECT pre-filter.
    """
    out, i, literal = [], 0, []
    while i < len(pattern):
        ch = pattern[i]
        if ch == "*":
            literal.append(None)
        elif ch == "?":
            literal.append("y")
        elif ch == "[":
            close = pattern.find("]", i + 1)
            if close == -1:
                literal.append("[")
            else:
                body = pattern[i + 1:close]
                if body.startswith("!"):
                    body = body[1:]
                    literal.append("0" if "0" not in body else "9")
                else:
                    literal.append(body[0] if body else "a")
                i = close
        else:
            literal.append(ch)
        i += 1

    stars = sum(1 for c in literal if c is None)
    combos = (itertools.product(_FILLERS, repeat=stars) if stars <= cap
              else [("x",) * stars])
    for combo in combos:
        it = iter(combo)
        w = "".join(next(it) if c is None else c for c in literal)
        if "//" not in w and not w.endswith("/") and w:
            out.append(w)
    return out


def test_no_PRODUCTION_pattern_is_dropped_for_a_subset_it_can_still_match():
    """The soundness property, over the REAL 177 patterns rather than toys.

    The regression that motivated this (`d5e4cc51`) was not a coding slip -- it
    was a semantic mismatch between two wildcard languages, and it survived
    review AND a unit test because the test encoded the same misreading as the
    code. A toy pattern list cannot catch the next one: the shapes that break a
    hand-written automaton are the awkward production ones -- a `[...]` class, a
    literal `?`, an empty `*` expansion, a pattern whose star spans a '/' in the
    SUBSET but not in itself.

    So this asserts the only thing that actually matters, over every dropped
    pattern: if a pattern can still produce a path the caller's `fnmatch` would
    accept, dropping it is a WRONG ANSWER WITH NO ERROR.

    Direction matters: this is a soundness test, not a completeness one. Keeping
    a pattern that can never match only wastes work, and the caller's post-filter
    still fixes the answer. Dropping one that can is unrecoverable.
    """
    all_patterns = list(HOT_ARTIFACT_PATTERNS) + list(EXPORT_ONLY_ARTIFACT_PATTERNS)
    subsets = [
        "wnba_source/*",                                  # the production failure
        "mlb_source/*",
        "*sim_input_report*",                             # leading star
        "*.json",
        "*_source/source_artifacts/data/processed/*",
        "nfl_source/*.json",
        "soccer_source/*/history/*",
        "mlb_source/*/*/*/arsenal*",
        "*recommendations*",
        "?lb_source/*",                                   # literal ? in the subset
        "*/*/*/*/*",
        "nba_source/*.csv",
    ]

    unsound, checked = [], 0
    for subset in subsets:
        kept = set(patterns_that_can_match(all_patterns, subset))
        for pattern in all_patterns:
            if pattern in kept:
                continue
            for witness in _witnesses(pattern):
                checked += 1
                if fn.fnmatch(witness, subset):
                    unsound.append((subset, pattern, witness))
                    break

    assert checked > 10_000, f"the sweep degenerated to {checked} witnesses"
    assert not unsound, (
        "a pattern was dropped for a subset it can still match -- the export "
        "endpoint will return a SHORT ANSWER WITH NO ERROR, exactly as in "
        f"d5e4cc51. First 3 of {len(unsound)}:\n" + "\n".join(
            f"  subset={s!r} dropped={p!r} witness={w!r}" for s, p, w in unsound[:3])
    )
