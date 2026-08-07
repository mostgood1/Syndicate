"""#254 -- the evaluation ledger must never materialise a whole chunk.

Production chunks measured 367,229,260 and 480,112,146 bytes on refresh-worker
2026-08-07, against a `SKIP_OVERSIZED_LEDGER_CHUNK` ceiling of 256,000,000. A
ceiling only decides which files are SKIPPED; it never bounded what reading an
accepted one cost, and three of the read paths had no ceiling at all.

The worst was `_replace_ledger_line`, which held up to four full copies live at
once (read_text, splitlines, new_lines, and the joined output string) to update
a single record -- on the settlement path, on a worker with ~1.4GB of headroom.

Same defect #75 fixed in `odds_lifecycle._load_jsonl_rows`.
"""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from syndicate.features.shared import intelligence_evaluation as ev


def _write_ledger(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False, sort_keys=True, default=str) for r in rows) + "\n",
        encoding="utf-8",
    )


def _rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_count_jsonl_records_matches_non_blank_lines():
    with TemporaryDirectory() as tmp:
        path = Path(tmp) / "chunk.jsonl"
        path.write_text('{"a":1}\n\n{"a":2}\n   \n{"a":3}\n', encoding="utf-8")
        assert ev._count_jsonl_records(path) == 3


def test_count_jsonl_records_is_zero_for_a_missing_file():
    with TemporaryDirectory() as tmp:
        assert ev._count_jsonl_records(Path(tmp) / "nope.jsonl") == 0


def test_iter_jsonl_lines_is_empty_for_a_missing_file():
    with TemporaryDirectory() as tmp:
        assert list(ev._iter_jsonl_lines(Path(tmp) / "nope.jsonl")) == []


def test_replace_ledger_line_replaces_the_matching_record_only():
    with TemporaryDirectory() as tmp:
        path = Path(tmp) / "ledger.jsonl"
        rows = [
            {"recommendation_id": "a", "value": 1},
            {"recommendation_id": "b", "value": 2},
            {"recommendation_id": "c", "value": 3},
        ]
        _write_ledger(path, rows)
        identity = ev._ledger_record_identity(rows[1])
        assert ev._replace_ledger_line(path, identity, {"recommendation_id": "b", "value": 999}) is True

        after = _rows(path)
        assert len(after) == 3
        assert [r["recommendation_id"] for r in after] == ["a", "b", "c"]
        assert [r["value"] for r in after] == [1, 999, 3]


def test_replace_ledger_line_leaves_the_file_untouched_when_not_found():
    # Load-bearing: the streaming version writes to a temp file as it goes, so
    # the not-found path must DISCARD it rather than promote a rewritten copy.
    with TemporaryDirectory() as tmp:
        path = Path(tmp) / "ledger.jsonl"
        _write_ledger(path, [{"recommendation_id": "a", "value": 1}])
        before = path.read_bytes()

        assert ev._replace_ledger_line(path, "no-such-identity", {"recommendation_id": "z"}) is False
        assert path.read_bytes() == before


def test_replace_ledger_line_leaves_no_temp_file_behind():
    with TemporaryDirectory() as tmp:
        path = Path(tmp) / "ledger.jsonl"
        rows = [{"recommendation_id": "a", "value": 1}, {"recommendation_id": "b", "value": 2}]
        _write_ledger(path, rows)

        ev._replace_ledger_line(path, ev._ledger_record_identity(rows[0]), {"recommendation_id": "a", "value": 7})
        ev._replace_ledger_line(path, "missing", {"recommendation_id": "q"})

        leftovers = [p.name for p in Path(tmp).iterdir() if p.name != "ledger.jsonl"]
        assert leftovers == []


def test_replace_ledger_line_returns_false_for_a_missing_file():
    with TemporaryDirectory() as tmp:
        assert ev._replace_ledger_line(Path(tmp) / "nope.jsonl", "x", {"a": 1}) is False


def test_replace_ledger_line_drops_blank_lines_as_before():
    # Pre-existing behaviour, pinned so the rewrite did not change it.
    with TemporaryDirectory() as tmp:
        path = Path(tmp) / "ledger.jsonl"
        row = {"recommendation_id": "a", "value": 1}
        path.write_text(json.dumps(row, sort_keys=True) + "\n\n\n", encoding="utf-8")
        assert ev._replace_ledger_line(path, ev._ledger_record_identity(row), {"recommendation_id": "a", "value": 5}) is True
        assert len(_rows(path)) == 1


def test_a_null_identity_never_matches_anything(capfd):
    """#258 -- data integrity.

    `_ledger_record_identity` returns None for a record carrying none of
    portfolio_event_id / recommendation_id / prediction_id, and the matcher
    compares by equality. So `identity=None` silently replaced the FIRST
    identity-less record in the chunk and returned True, reporting success.
    Nothing in logs would show it: the return value is True either way and the
    wrong record is structurally valid.

    Latent rather than live -- the only production caller routes identity-less
    records to append -- but an unidentified record must be UNADDRESSABLE.
    """
    with TemporaryDirectory() as tmp:
        path = Path(tmp) / "ledger.jsonl"
        rows = [{"note": "no identity fields at all"}, {"recommendation_id": "b", "value": 2}]
        _write_ledger(path, rows)
        before = path.read_bytes()

        assert ev._ledger_record_identity(rows[0]) is None  # the precondition

        for null_identity in (None, "", "   "):
            assert ev._replace_ledger_line(path, null_identity, {"note": "clobbered"}) is False
            assert path.read_bytes() == before, f"file was modified for identity={null_identity!r}"

        assert "REPLACE_LEDGER_LINE_REFUSED_NULL_IDENTITY" in capfd.readouterr().out


def test_a_real_identity_still_skips_identity_less_records():
    # The guard must not make identity-less rows unwritable COLLATERAL -- a real
    # identity should still find its record with such rows present.
    with TemporaryDirectory() as tmp:
        path = Path(tmp) / "ledger.jsonl"
        target = {"recommendation_id": "real", "value": 1}
        _write_ledger(path, [{"note": "orphan"}, target, {"note": "another orphan"}])

        assert ev._replace_ledger_line(
            path, ev._ledger_record_identity(target), {"recommendation_id": "real", "value": 42}
        ) is True

        after = _rows(path)
        assert [r.get("value") for r in after] == [None, 42, None]
        assert [r.get("note") for r in after] == ["orphan", None, "another orphan"]


def test_only_the_first_match_is_replaced():
    with TemporaryDirectory() as tmp:
        path = Path(tmp) / "ledger.jsonl"
        row = {"recommendation_id": "dupe", "value": 1}
        _write_ledger(path, [row, row])
        assert ev._replace_ledger_line(path, ev._ledger_record_identity(row), {"recommendation_id": "dupe", "value": 42}) is True
        values = [r["value"] for r in _rows(path)]
        assert values == [42, 1]
