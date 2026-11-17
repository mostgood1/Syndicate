"""Lane `lane-claims-checker-speed` (2026-11-17): the near-miss prefilter returns
exactly what `difflib.get_close_matches` over every name returns.

`check_lane_claims._near_miss` used to score every tracked basename for every
claim that names no file: 18 x 21,556 candidates, 1.2-1.8 s, the session-start
hook's critical path. `_close_basename` now drops two kinds of candidate before
difflib sees them:
  * those outside difflib's own length test;
  * those whose characters that are absent from the claim already cap
    `quick_ratio` below the cutoff.
Both are exact upper bounds, so the answer cannot change. This file holds that
claim to account against the unfiltered call, on synthetic typos and on this
checkout's real tracked basenames. `tests/test_check_lane_claims.py` covers the
checker's verdicts end to end, the worked typo example included.
"""
from __future__ import annotations

import difflib
import importlib.util
import pathlib
import random
import shutil
import string
import subprocess

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "check_lane_claims_speed", _ROOT / "scripts" / "check_lane_claims.py")
clc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(clc)


def _reference(base, names, cutoff):
    return difflib.get_close_matches(base, list(names), n=1, cutoff=cutoff)


def _mutate(rng, word):
    """One to three edits: the typo shapes `_near_miss` exists to catch."""
    chars = list(word)
    for _ in range(rng.randint(1, 3)):
        op = rng.choice("sidt")
        i = rng.randrange(len(chars) or 1)
        if op == "s" and chars:
            chars[i] = rng.choice(string.ascii_lowercase + "_.")
        elif op == "i":
            chars.insert(i, rng.choice(string.ascii_lowercase + "_"))
        elif op == "d" and len(chars) > 1:
            del chars[i]
        elif op == "t" and i + 1 < len(chars):
            chars[i], chars[i + 1] = chars[i + 1], chars[i]
    return "".join(chars)


def _synthetic_names(rng, count):
    words = ["live", "lines", "autorun", "ncaaf", "nba", "board", "grid", "lane", "claims",
             "check", "refresh", "worker", "props", "sim", "model", "edge", "quote", "rail"]
    names = set()
    while len(names) < count:
        stem = "_".join(rng.sample(words, rng.randint(1, 4)))
        prefix = rng.choice(["", "", "test_"])
        names.add(prefix + stem + rng.choice([".py", ".md", ".json", ".csv", ""]))
    return sorted(names)


EDGE_BASES = ["a", "x.py", "test_.py", "é_ü.py", "ß" * 30, "a" * 120,
              "test_ncaaf_live_autorun.py", "test_team_recent_results.py", "README"]


# Cutoffs near the real 0.85 only. A low cutoff makes the REFERENCE run difflib's
# full `ratio()` on nearly every candidate: 0.0 and 0.6 took 81 s and 30 s here,
# and both passed (2026-11-17), so they were dropped for time, not for failing.
@pytest.mark.parametrize("cutoff", [0.85, 0.75, 0.95, 1.0])
def test_synthetic_typos_get_the_same_match(cutoff):
    rng = random.Random(20261117)
    names = _synthetic_names(rng, 800) + ["é_ü.py", "a" * 119, "ncaaf_lines_autorun.py",
                                          "test_ncaaf_lines_autorun.py", "team_recent_results.py"]
    bases = [_mutate(rng, rng.choice(names)) for _ in range(150)] + EDGE_BASES
    bases += [rng.choice(names) for _ in range(15)]  # exact names: a match of 1.0
    found = 0
    for base in bases:
        if not base:
            continue
        want = _reference(base, names, cutoff)
        assert clc._close_basename(base, names, cutoff) == want, (base, cutoff)
        found += bool(want)
    # The population produced real matches, not only misses: the 15 exact names
    # always match, and below 1.0 some typos must match too.
    assert found >= 15 if cutoff == 1.0 else found > 25


def test_a_dict_of_names_is_read_like_its_list():
    """`_near_miss` passes `by_base` itself, a dict keyed by basename."""
    by_base = {"ncaaf_lines_autorun.py": ["a/ncaaf_lines_autorun.py"], "other.md": ["other.md"]}
    assert clc._close_basename("ncaaf_live_autorun.py", by_base, 0.85) == ["ncaaf_lines_autorun.py"]


@pytest.mark.skipif(shutil.which("git") is None, reason="git not on PATH")
def test_real_tracked_basenames_get_the_same_match():
    out = subprocess.run(["git", "-C", str(_ROOT), "ls-files"], capture_output=True, text=True)
    if out.returncode != 0:
        pytest.skip("not a git checkout")
    names = sorted({p.rsplit("/", 1)[-1] for p in out.stdout.splitlines() if p.strip()})
    assert len(names) > 1000
    rng = random.Random(822)
    bases = [_mutate(rng, rng.choice(names)) for _ in range(10)] + EDGE_BASES[-3:]
    for base in bases:
        assert clc._close_basename(base, names, 0.85) == _reference(base, names, 0.85), base


def test_near_miss_goes_through_the_prefilter(monkeypatch):
    """Reachability: the check runs the new path, not a leftover direct call."""
    calls = []
    real = clc._close_basename

    def spy(base, names, cutoff, by_len=None):
        calls.append((base, cutoff, by_len is not None))
        return real(base, names, cutoff, by_len)

    monkeypatch.setattr(clc, "_close_basename", spy)
    by_base = {"test_ncaaf_lines_autorun.py": ["tests/test_ncaaf_lines_autorun.py"]}
    claim = "tests/test_ncaaf_live_autorun.py"
    assert clc._near_miss(claim, by_base) == "tests/test_ncaaf_lines_autorun.py"
    by_len = clc._names_by_length(by_base)
    assert clc._near_miss(claim, by_base, by_len) == "tests/test_ncaaf_lines_autorun.py"
    assert calls == [("test_ncaaf_live_autorun.py", 0.85, False), ("test_ncaaf_live_autorun.py", 0.85, True)]


def test_a_prebuilt_length_index_gives_the_same_answers():
    """`main` builds `_names_by_length` once and passes it to every call."""
    rng = random.Random(5)
    names = _synthetic_names(rng, 600)
    by_len = clc._names_by_length(names)
    assert sorted(n for group in by_len.values() for n in group) == sorted(names)
    for base in [_mutate(rng, rng.choice(names)) for _ in range(60)] + EDGE_BASES:
        if base:
            assert (clc._close_basename(base, names, 0.85, by_len)
                    == clc._close_basename(base, names, 0.85) == _reference(base, names, 0.85)), base
