"""`#400` -- the sweep said a class was skipped and never which artifact.

WHAT THE GAP COST. `SWEEP_SKIPPED {'too_large': 2}` was read across THREE
sessions as "book_grid is being refused at the publish ceiling", and a
compaction change was one step from shipping on that basis. It is false:

    ceiling   _PUBLISH_MAX_BYTES = 12 * 1024 * 1024 = 12,582,912
    measured  mlb book_grid stored 12,854,052  -- over
    observed  PUBLISH_OK ... book_grid ... transport=stream bytes=12855903

Both hold because two paths apply the ceiling differently: `_publish_skip_reason`
enforces it and is called by `sweep_changed_hot_artifacts` ONLY, while the direct
publish path streams anything >= `_PUBLISH_STREAM_MIN_BYTES` and never consults
it. So book_grid is skipped by the sweep AND published directly. It reaches web.

The counter was not wrong -- it was under-specified, and every reader supplied
the same plausible missing noun. The ceiling's own comment says it exists to stop
the sweep shipping "51MB odds_history shards"; a 12MB grid and a 51MB shard are
the same COUNT and completely different facts.

BOUNDED at three per reason: a sweep can skip a whole class at once, and a line
naming hundreds of files is as unreadable as one naming none. The size detail is
kept deliberately -- it is the discriminator.

The pre-existing `SWEEP_SKIPPED {dict}` line is left byte-identical because it is
greppable and other things read it; the detail rides alongside, the same shape as
`#382`'s cadence detail next to its skip line.
"""

from __future__ import annotations

import importlib

import pytest

MODULE = "syndicate.features.shared.artifact_publisher"


@pytest.fixture
def pub(monkeypatch, tmp_path):
    mod = importlib.import_module(MODULE)
    monkeypatch.setattr(mod, "_data_root", lambda: tmp_path, raising=False)
    monkeypatch.setattr(mod, "_publish_url", lambda: "http://x", raising=False)
    monkeypatch.setattr(mod, "_admin_token", lambda: "t", raising=False)
    monkeypatch.setattr(mod, "publish_hot_artifact", lambda p: True, raising=False)
    return mod


def _make(tmp_path, rel: str, size: int):
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    return path


def test_the_detail_names_the_oversized_file_and_its_size(pub, tmp_path, monkeypatch, capsys):
    rel = "mlb_source/data/book_grid/book_grid_2026-08-12.json"
    _make(tmp_path, rel, pub._PUBLISH_MAX_BYTES + 1000)
    monkeypatch.setattr(pub, "HOT_ARTIFACT_PATTERNS", (rel,), raising=False)

    pub.sweep_changed_hot_artifacts(0.0)
    out = capsys.readouterr().out
    assert "SWEEP_SKIPPED {'too_large': 1}" in out, "the original line must stay byte-identical"
    detail = next(l for l in out.splitlines() if "SWEEP_SKIPPED_DETAIL" in l)
    assert "book_grid_2026-08-12.json" in detail, "the file must be named -- this is the whole point"
    assert str(pub._PUBLISH_MAX_BYTES + 1000) in detail, "the size discriminates a 12MB grid from a 51MB shard"


def test_the_original_counter_line_is_unchanged(pub, tmp_path, monkeypatch, capsys):
    # It is greppable and other things read it. Enriching the diagnostic must not
    # alter the line that already exists.
    rel = "mlb_source/data/book_grid/g.json"
    _make(tmp_path, rel, pub._PUBLISH_MAX_BYTES + 1)
    monkeypatch.setattr(pub, "HOT_ARTIFACT_PATTERNS", (rel,), raising=False)
    pub.sweep_changed_hot_artifacts(0.0)
    lines = [l for l in capsys.readouterr().out.splitlines() if "SWEEP_SKIPPED" in l]
    plain = [l for l in lines if "SWEEP_SKIPPED_DETAIL" not in l]
    assert len(plain) == 1
    assert plain[0].endswith("{'too_large': 1}")


def test_examples_are_bounded_per_reason(pub, tmp_path, monkeypatch, capsys):
    # A sweep can skip a whole class at once; naming hundreds is as unreadable
    # as naming none.
    for n in range(9):
        _make(tmp_path, f"mlb_source/data/book_grid/g{n}.json", pub._PUBLISH_MAX_BYTES + 1)
    monkeypatch.setattr(pub, "HOT_ARTIFACT_PATTERNS", ("mlb_source/data/book_grid/*.json",), raising=False)
    pub.sweep_changed_hot_artifacts(0.0)
    out = capsys.readouterr().out
    assert "'too_large': 9" in out, "the COUNT must still report every file"
    detail = next(l for l in out.splitlines() if "SWEEP_SKIPPED_DETAIL" in l)
    # Count ENTRIES, not a letter: "book_grid" contains a 'g', so a substring
    # count reports the path shape rather than the bound. My first cut asserted
    # on `detail.count("g")` and failed against correct output.
    inner = detail.split("too_large=[", 1)[1].rsplit("]", 1)[0]
    entries = [e for e in inner.split(",") if ".json" in e]
    assert len(entries) == 3, f"expected 3 bounded examples, got {len(entries)}: {entries}"


def test_nothing_is_printed_when_nothing_is_skipped(pub, tmp_path, monkeypatch, capsys):
    _make(tmp_path, "mlb_source/data/book_grid/small.json", 128)
    monkeypatch.setattr(pub, "HOT_ARTIFACT_PATTERNS", ("mlb_source/data/book_grid/*.json",), raising=False)
    pub.sweep_changed_hot_artifacts(0.0)
    out = capsys.readouterr().out
    assert "SWEEP_SKIPPED" not in out


def test_distinct_reasons_are_reported_separately(pub, tmp_path, monkeypatch, capsys):
    # too_large and stale_slate are different problems with different fixes;
    # collapsing them would rebuild the ambiguity being removed.
    _make(tmp_path, "mlb_source/data/book_grid/book_grid_2026-08-12.json", pub._PUBLISH_MAX_BYTES + 1)
    _make(tmp_path, "mlb_source/data/book_grid/book_grid_2000-01-01.json", 64)
    monkeypatch.setattr(pub, "HOT_ARTIFACT_PATTERNS", ("mlb_source/data/book_grid/*.json",), raising=False)
    pub.sweep_changed_hot_artifacts(0.0)
    detail = next(l for l in capsys.readouterr().out.splitlines() if "SWEEP_SKIPPED_DETAIL" in l)
    assert "too_large=[" in detail and "stale_slate=[" in detail
