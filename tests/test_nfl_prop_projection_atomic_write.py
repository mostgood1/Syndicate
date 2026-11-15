"""The NFL prop projections artifact is replaced in one rename, never rewritten in place.

Measured 2026-11-15 19:33:51.681Z on the fleet: `prop_evidence` football read
`nfl_source/nfl_prop_projections_2026_wk10.json` 7 ms before the props build
finished rewriting it, and logged a `JSONDecodeError` at char 229,616. The writer
opened the destination with `path.open("w")` (which truncates it) and streamed
`json.dump` into it, so for the length of the dump the file on disk was a prefix.
`read_nfl_prop_projection_artifact` turns an unreadable file into None, which on
web means "no projection", so the race could not be seen as an error there.

Each test below fails on the in-place writer:
- the destination must still hold the OLD complete payload at the moment of the
  rename, and the file being renamed must already be the NEW complete payload;
- a payload that cannot be serialised must leave the old artifact untouched (the
  in-place writer truncated it first and left a partial file);
- no temp file is left behind, and the temp name never matches the readers'
  `nfl_prop_projections_<season>_wk*.json` glob.
"""

from __future__ import annotations

import fnmatch
import json
import os

import pytest

from syndicate.features.nfl import props as props_module
from syndicate.features.shared import atomic_artifact_write


def _rows(n: int, tag: str) -> list[dict]:
    return [{"player": f"{tag} {i}", "stat": "receiving_yards", "mean": 40.0 + i} for i in range(n)]


@pytest.fixture
def out_root(monkeypatch, tmp_path):
    monkeypatch.setattr(props_module, "nfl_artifact_output_root", lambda: tmp_path)
    return tmp_path


def test_the_destination_changes_in_one_rename_from_old_complete_to_new_complete(monkeypatch, out_root):
    old_path = props_module.write_nfl_prop_projection_artifact(2026, 10, _rows(3, "old"))
    old_text = old_path.read_text(encoding="utf-8")

    seen: list[tuple[str, str, str]] = []
    real_replace = os.replace

    def spying_replace(src, dst):
        # At the instant of the rename: what the destination holds, and what replaces it.
        seen.append((str(dst), open(dst, encoding="utf-8").read(), open(src, encoding="utf-8").read()))
        assert os.path.dirname(os.path.abspath(src)) == os.path.dirname(os.path.abspath(dst)), (
            "the temp file must sit in the destination's directory: os.replace is atomic only within one filesystem"
        )
        return real_replace(src, dst)

    monkeypatch.setattr(atomic_artifact_write.os, "replace", spying_replace)
    new_rows = _rows(2000, "new")
    path = props_module.write_nfl_prop_projection_artifact(2026, 10, new_rows)

    assert len(seen) == 1, "the writer must publish through exactly one os.replace onto the artifact"
    dst, before, incoming = seen[0]
    assert dst == str(path)
    assert before == old_text, "the destination was touched before the rename"
    incoming_payload = json.loads(incoming)  # complete JSON, not a prefix
    assert incoming_payload["sim_rows"] == new_rows
    assert path.read_text(encoding="utf-8") == incoming


def test_a_payload_that_cannot_serialise_leaves_the_old_artifact_untouched(out_root):
    path = props_module.write_nfl_prop_projection_artifact(2026, 10, _rows(5, "old"))
    old_text = path.read_text(encoding="utf-8")

    with pytest.raises(TypeError):
        props_module.write_nfl_prop_projection_artifact(2026, 10, _rows(5, "new") + [{"bad": object()}])

    assert path.read_text(encoding="utf-8") == old_text
    assert json.loads(old_text)["row_count"] == 5
    assert sorted(p.name for p in out_root.iterdir()) == [path.name]


def test_no_temp_file_is_left_and_the_artifact_format_is_unchanged(out_root):
    rows = _rows(4, "p")
    path = props_module.write_nfl_prop_projection_artifact(2026, 11, rows)

    assert path == out_root / "nfl_prop_projections_2026_wk11.json"
    assert sorted(p.name for p in out_root.iterdir()) == [path.name]

    text = path.read_text(encoding="utf-8")
    payload = json.loads(text)
    assert list(payload) == ["season", "week", "generated_at", "sim_rows", "row_count"]
    assert (payload["season"], payload["week"], payload["sim_rows"], payload["row_count"]) == (2026, 11, rows, 4)
    # The same bytes `json.dump(payload, handle)` wrote before: default separators, no indent.
    assert text == json.dumps(payload)


def test_the_temp_name_never_matches_the_readers_glob(monkeypatch, out_root):
    names: list[str] = []
    real_replace = os.replace

    def recording_replace(src, dst):
        names.append(os.path.basename(src))
        return real_replace(src, dst)

    monkeypatch.setattr(atomic_artifact_write.os, "replace", recording_replace)
    props_module.write_nfl_prop_projection_artifact(2026, 10, _rows(1, "p"))

    assert len(names) == 1
    # The globs `prop_evidence.football` and the artifact publisher read with.
    for pattern in ("nfl_prop_projections_2026_wk*.json", "nfl_prop_projections_*.json"):
        assert not fnmatch.fnmatch(names[0], pattern), (names[0], pattern)
