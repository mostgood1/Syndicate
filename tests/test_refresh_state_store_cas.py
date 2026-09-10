"""`#656` -- `compare_and_swap_json_file`, the store half of an atomic ledger write.

`write_json_file` is a blind SET, so a read -> merge -> SET caller loses any
write that lands between its read and its SET. These pin the primitive on both
backends with the rival write FORCED into that window, never hoped for -- a
concurrency test that passes because nothing overlapped reports green for the
one condition it exists to create.
"""

from __future__ import annotations

import json

import pytest
import redis

from syndicate.features.shared import refresh_state_store as store


class _FakeRedis:
    """Enough of redis-py for WATCH / MULTI / EXEC.

    Every SET bumps a per-key version and a pipeline's EXEC compares against the
    versions it WATCHed -- the server's own rule. `on_get` runs AFTER a GET has
    taken its value, which is how a test puts a rival write between a read and
    the SET that follows it.
    """

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.ttls: dict[str, int] = {}
        self.versions: dict[str, int] = {}
        self.log: list[tuple] = []
        self.on_get = None

    def get(self, key):
        value = self.store.get(key)
        self.log.append(("get", key))
        if self.on_get is not None:
            self.on_get(key)
        return value

    def set(self, key, value, ex=None):
        self.store[key] = str(value)
        self.versions[key] = self.versions.get(key, 0) + 1
        if ex is None:
            self.ttls.pop(key, None)
        else:
            self.ttls[key] = ex
        self.log.append(("set", key))
        return True

    def pipeline(self, transaction=True):
        return _FakePipeline(self)


class _FakePipeline:
    def __init__(self, client: _FakeRedis) -> None:
        self.client = client
        self.watched: dict[str, int] = {}
        self.queued: list | None = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.reset()
        return False

    def watch(self, *keys):
        for key in keys:
            self.watched[key] = self.client.versions.get(key, 0)
        self.client.log.append(("watch", *keys))

    def multi(self):
        self.queued = []

    def set(self, key, value, ex=None):
        self.queued.append((key, value, ex))

    def execute(self):
        changed = [k for k, v in self.watched.items() if self.client.versions.get(k, 0) != v]
        self.client.log.append(("exec", "aborted" if changed else "ok"))
        if changed:
            self.reset()
            raise redis.exceptions.WatchError("Watched variable changed.")
        for key, value, ex in self.queued or []:
            self.client.set(key, value, ex=ex)
        self.reset()
        return [True]

    def reset(self):
        self.watched = {}
        self.queued = None


@pytest.fixture
def kv(monkeypatch):
    fake = _FakeRedis()

    def _client():
        return fake

    _client.cache_clear = lambda: None
    monkeypatch.setenv("SYNDICATE_REFRESH_STATE_BACKEND", "keyvalue")
    monkeypatch.setattr(store, "_get_keyvalue_client", _client)
    return fake


@pytest.fixture
def disk(monkeypatch):
    monkeypatch.setenv("SYNDICATE_REFRESH_STATE_BACKEND", "filesystem")


def _path(tmp_path):
    return tmp_path / "intelligence" / "doc.json"


def _rival_once(kv, key, write):
    """An `on_get` hook: after the first GET of `key`, run `write` once."""
    fired = []

    def hook(k):
        if k == key and not fired:
            fired.append(1)
            kv.on_get = None
            write()

    kv.on_get = hook
    return fired


# ---------------------------------------------------------------------------
# keyvalue
# ---------------------------------------------------------------------------


def test_keyvalue_build_reads_AFTER_the_watch_is_armed(kv, tmp_path):
    """The whole guarantee rests on this order. A read taken before the WATCH
    could miss a write that the EXEC would then happily overwrite."""
    path = _path(tmp_path)
    store.write_json_file(path, {"n": 0})
    kv.log.clear()

    result = store.compare_and_swap_json_file(
        path, lambda attempt: {"n": store.read_json_file(path)["n"] + 1}
    )

    assert result == store.CasResult(attempts=1, backend="keyvalue")
    assert [op[0] for op in kv.log] == ["watch", "get", "exec", "set"]
    assert store.read_json_file(path) == {"n": 1}


def test_keyvalue_a_rival_SET_between_the_read_and_the_SET_forces_a_rebuild(kv, tmp_path, capsys):
    path = _path(tmp_path)
    store.write_json_file(path, {"rows": ["a"]})
    fired = _rival_once(
        kv, store._state_key_for_path(path),
        lambda: store.write_json_file(path, {"rows": ["a", "rival"]}),
    )
    seen = []

    def build(attempt):
        rows = store.read_json_file(path)["rows"]
        seen.append(list(rows))
        return {"rows": rows + ["ours"]}

    result = store.compare_and_swap_json_file(path, build, backoff_seconds=0)

    assert fired == [1], "the rival never landed inside the window"
    assert result.attempts == 2 and result.conflicts == 1
    assert seen == [["a"], ["a", "rival"]]
    assert store.read_json_file(path) == {"rows": ["a", "rival", "ours"]}
    assert "CAS_CONFLICT" in capsys.readouterr().out


def test_keyvalue_exhaustion_raises_and_writes_nothing(kv, tmp_path):
    path = _path(tmp_path)
    key = store._state_key_for_path(path)
    store.write_json_file(path, {"v": 0})
    rivals = []

    def always(k):
        if k == key:
            rivals.append(1)
            kv.set(k, json.dumps({"v": -len(rivals)}))

    kv.on_get = always
    with pytest.raises(store.WriteConflict) as info:
        store.compare_and_swap_json_file(
            path, lambda attempt: {"ours": attempt, "v": store.read_json_file(path)["v"]},
            max_attempts=3, backoff_seconds=0,
        )
    kv.on_get = None

    assert info.value.attempts == 3
    assert "ours" not in store.read_json_file(path)


def test_keyvalue_announces_a_large_write_only_once_it_LANDS(kv, tmp_path, monkeypatch, capsys):
    """`KEYVALUE_WRITE_LARGE` lines were read as document VERSIONS to prove the
    2026-09-04 lost update. An aborted attempt printing one would put a version
    in that record that never existed."""
    monkeypatch.setenv("SYNDICATE_KEYVALUE_WARN_BYTES", "1024")
    path = _path(tmp_path)
    store.write_json_file(path, {"pad": "x"})
    _rival_once(kv, store._state_key_for_path(path), lambda: kv.set(store._state_key_for_path(path), '{"pad":"y"}'))
    capsys.readouterr()

    store.compare_and_swap_json_file(
        path, lambda attempt: {"base": store.read_json_file(path)["pad"], "pad": "z" * 4096},
        backoff_seconds=0,
    )

    out = capsys.readouterr().out
    assert out.count("CAS_CONFLICT") == 1
    assert out.count("KEYVALUE_WRITE_LARGE") == 1


def test_keyvalue_an_oversized_document_is_refused_and_nothing_is_written(kv, tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_KEYVALUE_WARN_BYTES", "1024")
    monkeypatch.setenv("SYNDICATE_KEYVALUE_MAX_BYTES", "2048")
    path = _path(tmp_path)
    store.write_json_file(path, {"v": 1})

    with pytest.raises(store.KeyValuePayloadTooLarge):
        store.compare_and_swap_json_file(path, lambda attempt: {"pad": "x" * 4096})

    assert store.read_json_file(path) == {"v": 1}


def test_keyvalue_keeps_write_json_files_ttl_rule(kv, tmp_path):
    """A dated path takes the store's TTL and an undated one never expires --
    the money ledger depends on the second half."""
    dated = tmp_path / "intelligence" / "doc_2026-09-10.json"
    undated = _path(tmp_path)
    assert store._default_keyvalue_ttl_seconds(dated) is not None

    store.compare_and_swap_json_file(dated, lambda attempt: {"v": 1})
    store.compare_and_swap_json_file(undated, lambda attempt: {"v": 1})

    assert kv.ttls.get(store._state_key_for_path(dated)) == store._default_keyvalue_ttl_seconds(dated)
    assert store._state_key_for_path(undated) not in kv.ttls


# ---------------------------------------------------------------------------
# filesystem -- local runs and tests
# ---------------------------------------------------------------------------


def test_disk_a_rival_write_inside_the_window_forces_a_rebuild(disk, tmp_path):
    path = _path(tmp_path)
    store.write_json_file(path, {"rows": ["a"]})
    fired = []

    def build(attempt):
        rows = store.read_json_file(path)["rows"]
        if not fired:
            fired.append(1)
            # Another writer, landing after our read and before our replace.
            store.write_json_file(path, {"rows": rows + ["rival"]})
        return {"rows": rows + ["ours"]}

    result = store.compare_and_swap_json_file(path, build, backoff_seconds=0)

    assert result == store.CasResult(attempts=2, backend="filesystem")
    assert store.read_json_file(path) == {"rows": ["a", "rival", "ours"]}


def test_disk_exhaustion_raises(disk, tmp_path):
    path = _path(tmp_path)
    store.write_json_file(path, {"n": 0})

    def build(attempt):
        n = store.read_json_file(path)["n"]
        store.write_json_file(path, {"n": n + 100})
        return {"n": n + 1}

    with pytest.raises(store.WriteConflict):
        store.compare_and_swap_json_file(path, build, max_attempts=2, backoff_seconds=0)


def test_disk_creates_an_absent_file_byte_identical_to_write_json_file(disk, tmp_path):
    doc = {"z": 1, "updated_at": "2026-09-10T00:00:00Z", "nested": {"k": [1, 2]}}
    store.compare_and_swap_json_file(tmp_path / "a.json", lambda attempt: dict(doc))
    store.write_json_file(tmp_path / "b.json", dict(doc))

    assert (tmp_path / "a.json").read_bytes() == (tmp_path / "b.json").read_bytes()
