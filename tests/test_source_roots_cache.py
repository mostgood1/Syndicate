"""Caching of the source/artifact root resolvers. `[2026-08-29]`

WHY THIS IS TESTED THIS HARD FOR A CACHE. `Path.resolve()` was 46% of soccer's
`sport_branch` (7,955 `lstat` syscalls from 1,260 resolves), so the win is real
-- but a root resolver that returns a STALE answer sends every artifact read to
the wrong disk, and this repo's whole failure vocabulary is "the reader could
not see what the writer wrote". So the correctness tests here outnumber the
performance one, and the env-sensitivity tests are the point: `monkeypatch.setenv`
must still change the answer, or a green suite ships a wrong root.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from syndicate.features.shared import source_roots as SR


@pytest.fixture(autouse=True)
def _clear():
    SR.clear_source_root_caches()
    yield
    SR.clear_source_root_caches()


HERE = __file__


def test_env_change_still_changes_the_answer(monkeypatch, tmp_path):
    """THE ONE THAT MATTERS. A cache keyed only on the arguments would pin the
    first root for the life of the process and pass every other test here."""
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    monkeypatch.setenv("SYNDICATE_TEST_ROOT", str(a))
    first = SR.preferred_source_roots(HERE, env_var="SYNDICATE_TEST_ROOT", local_dir_name="mlb_source")
    monkeypatch.setenv("SYNDICATE_TEST_ROOT", str(b))
    second = SR.preferred_source_roots(HERE, env_var="SYNDICATE_TEST_ROOT", local_dir_name="mlb_source")
    assert first != second
    assert first[0] == a.resolve()
    assert second[0] == b.resolve()


def test_data_root_change_is_seen(monkeypatch, tmp_path):
    monkeypatch.delenv("SYNDICATE_TEST_ROOT", raising=False)
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path / "one"))
    first = SR.preferred_source_roots(HERE, env_var="SYNDICATE_TEST_ROOT", local_dir_name="mlb_source")
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path / "two"))
    second = SR.preferred_source_roots(HERE, env_var="SYNDICATE_TEST_ROOT", local_dir_name="mlb_source")
    assert first != second


def test_strict_hosted_storage_change_is_seen(monkeypatch, tmp_path):
    monkeypatch.delenv("SYNDICATE_TEST_ROOT", raising=False)
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    monkeypatch.delenv("SYNDICATE_REQUIRE_HOSTED_STORAGE", raising=False)
    monkeypatch.delenv("RENDER", raising=False)
    loose = SR.preferred_source_roots(HERE, env_var="SYNDICATE_TEST_ROOT", local_dir_name="mlb_source")
    monkeypatch.setenv("SYNDICATE_REQUIRE_HOSTED_STORAGE", "1")
    strict = SR.preferred_source_roots(HERE, env_var="SYNDICATE_TEST_ROOT", local_dir_name="mlb_source")
    assert loose != strict, "strict mode must drop the local mirror"


def test_callers_get_their_own_mutable_list(monkeypatch, tmp_path):
    """The cache holds a tuple; every caller must still get a private list.
    Handing out a shared list would let one caller's mutation reach the rest."""
    monkeypatch.setenv("SYNDICATE_TEST_ROOT", str(tmp_path))
    first = SR.preferred_source_roots(HERE, env_var="SYNDICATE_TEST_ROOT", local_dir_name="mlb_source")
    assert isinstance(first, list)
    first.append(Path("/injected"))
    second = SR.preferred_source_roots(HERE, env_var="SYNDICATE_TEST_ROOT", local_dir_name="mlb_source")
    assert Path("/injected") not in second


def test_artifact_roots_are_cached_and_env_sensitive(monkeypatch, tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    monkeypatch.setenv("SYNDICATE_TEST_ART", str(a))
    first = SR.preferred_artifact_roots(HERE, env_var="SYNDICATE_TEST_ART", local_dir_name="mlb_source")
    monkeypatch.setenv("SYNDICATE_TEST_ART", str(b))
    second = SR.preferred_artifact_roots(HERE, env_var="SYNDICATE_TEST_ART", local_dir_name="mlb_source")
    assert first != second
    assert isinstance(first, list)
    first.append(Path("/injected"))
    assert Path("/injected") not in SR.preferred_artifact_roots(
        HERE, env_var="SYNDICATE_TEST_ART", local_dir_name="mlb_source"
    )


def test_repo_root_from_is_stable_and_correct():
    direct = Path(HERE).resolve().parents[3]
    assert SR.repo_root_from(HERE) == direct
    assert SR.repo_root_from(Path(HERE)) == direct, "str and Path must agree"


def test_the_cache_actually_avoids_the_resolve(monkeypatch, tmp_path):
    """REACHABILITY: off != on. Counts real `Path.resolve` calls across repeats.
    Without the cache this is linear in the number of calls."""
    monkeypatch.setenv("SYNDICATE_TEST_ROOT", str(tmp_path))
    calls = {"n": 0}
    real_resolve = Path.resolve

    def counting(self, *a, **k):
        calls["n"] += 1
        return real_resolve(self, *a, **k)

    monkeypatch.setattr(Path, "resolve", counting)
    SR.preferred_source_roots(HERE, env_var="SYNDICATE_TEST_ROOT", local_dir_name="mlb_source")
    after_first = calls["n"]
    assert after_first > 0, "the first call must really resolve"
    for _ in range(20):
        SR.preferred_source_roots(HERE, env_var="SYNDICATE_TEST_ROOT", local_dir_name="mlb_source")
    assert calls["n"] == after_first, f"cache missed: {calls['n']} vs {after_first}"


def test_strict_mode_still_raises_rather_than_caching_a_bad_answer(monkeypatch):
    """lru_cache does not memoize exceptions, so this must raise EVERY time."""
    monkeypatch.delenv("SYNDICATE_TEST_ROOT", raising=False)
    monkeypatch.delenv("SYNDICATE_DATA_ROOT", raising=False)
    monkeypatch.delenv("RENDER", raising=False)
    monkeypatch.setenv("SYNDICATE_REQUIRE_HOSTED_STORAGE", "1")
    for _ in range(3):
        with pytest.raises(RuntimeError):
            SR.preferred_source_roots(HERE, env_var="SYNDICATE_TEST_ROOT", local_dir_name="mlb_source")
