"""Lane `reconciliation-disk-walks`: one disk walk per date, results unchanged.

The daily reconciliation autorun runs INLINE in refresh-worker's main loop. On
2026-09-18 it took ~23 min (21:03:51Z -> ~21:27:13Z), and while it ran no
book-grid tick happened. Per date it made six `rglob` walks of the whole
persistent disk (48,816 directories) and derived the same file list twice.

Every test here compares against FROZEN copies of the pre-change code
(`_reference_*`), so "unchanged" is measured rather than asserted: the file
list and its ORDER (the first matching row wins, so order decides which of
two conflicting files settles a prediction), the matcher's choice, and the
ledger outcome.
"""

from __future__ import annotations

import csv
import logging
import os
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import pytest

from syndicate.features import prediction_reconciliation as recon
from syndicate.features.prediction_ledger import record_prediction


DATE = "2026-09-18"
OTHER_DATE = "2026-09-17"


# --- frozen pre-change code ---------------------------------------------------


def _reference_candidate_result_paths(date_value: str, roots: Sequence[Path]) -> list[Path]:
    paths: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        for pattern in recon.RECONCILIATION_PATTERNS:
            for candidate in root.rglob(pattern.format(date=date_value)):
                if candidate.is_file():
                    paths.append(candidate)
    unique: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path.resolve()).lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def _reference_match_result_row(prediction: Mapping[str, Any], rows: Iterable[Any]) -> Mapping[str, Any] | None:
    prediction_keys = recon._prediction_keys(prediction)
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        row_keys = recon._row_keys(row)
        if prediction_keys and row_keys and prediction_keys.isdisjoint(row_keys):
            continue
        if recon._normalize_text(row.get("market")) and recon._normalize_text(prediction.get("market")) and recon._normalize_text(row.get("market")) != recon._normalize_text(prediction.get("market")):
            continue
        return row
    return None


# --- fixtures -----------------------------------------------------------------


def _write_rows(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _build_tree(root: Path) -> None:
    """Result files for two dates, scattered across nested directories.

    The same NAME sits in several directories (rglob returns each), one
    pattern-named entry is a DIRECTORY (rglob returns it, `is_file` drops it),
    and there are decoys for another date and unrelated names.
    """
    row = [{"player": "Jane Doe", "market": "points", "result": "win"}]
    for relative in (
        f"closing_lines_{DATE}.csv",
        f"mlb_source/reconciliation/props_actuals_{DATE}.csv",
        f"mlb_source/reconciliation/deep/er/closing_lines_{DATE}.csv",
        f"nba_source/data/processed/recon_props_{DATE}.csv",
        f"nba_source/data/processed/recon_games_{DATE}.csv",
        f"wnba_source/data/processed/recon_props_{DATE}.csv",
        f"settlement_inputs/closing_lines_{DATE}.csv",
        f"settlement_inputs/game_results_{DATE}.csv",
        f"a/b/c/d/game_results_{DATE}.csv",
        f"settlement_inputs/closing_lines_{OTHER_DATE}.csv",
        f"nba_source/data/processed/recon_props_{OTHER_DATE}.csv",
        f"nba_source/data/processed/unrelated_{DATE}.csv",
        f"nba_source/data/processed/closing_lines_{DATE}.csv.gz",
    ):
        _write_rows(root / relative, row)
    (root / f"z_dir/game_results_{DATE}.json").mkdir(parents=True)
    (root / f"a/b/game_results_{DATE}.json").write_text('{"rows": [{"player": "Jane Doe", "result": "loss"}]}', encoding="utf-8")
    for index in range(12):
        (root / f"empty/{index:02d}/leaf").mkdir(parents=True)


@pytest.fixture()
def tree(tmp_path: Path) -> Path:
    root = tmp_path / "data"
    _build_tree(root)
    return root


# --- the walk -----------------------------------------------------------------


@pytest.mark.parametrize("date_value", [DATE, OTHER_DATE, "2026-01-01"])
def test_paths_equal_the_rglob_reference_order_included(tree: Path, tmp_path: Path, date_value: str) -> None:
    second_root = tmp_path / "second"
    _build_tree(second_root)
    roots = [tree, tmp_path / "absent", second_root]

    assert recon._candidate_result_paths(date_value, roots) == _reference_candidate_result_paths(date_value, roots)


def test_the_fixture_exercises_duplicates_and_directories(tree: Path) -> None:
    # Guards the test above from passing vacuously on a tree with one match.
    paths = _reference_candidate_result_paths(DATE, [tree])
    names = [path.name for path in paths]
    assert names.count(f"closing_lines_{DATE}.csv") == 3
    assert f"game_results_{DATE}.json" in names
    assert all(path.is_file() for path in paths)
    assert len(paths) == 10


def test_a_symlinked_directory_is_not_followed_as_before(tree: Path, tmp_path: Path) -> None:
    target = tmp_path / "outside"
    _write_rows(target / f"closing_lines_{DATE}.csv", [{"player": "x", "market": "y", "result": "win"}])
    try:
        os.symlink(target, tree / "linked", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable on this platform")

    assert recon._candidate_result_paths(DATE, [tree]) == _reference_candidate_result_paths(DATE, [tree])


def _count_scandir(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    counts: dict[str, int] = {}
    real = os.scandir

    def counting(path: Any = ".") -> Any:
        key = os.path.normcase(os.fspath(path))
        counts[key] = counts.get(key, 0) + 1
        return real(path)

    monkeypatch.setattr(os, "scandir", counting)
    return counts


def test_each_directory_is_listed_once_per_call(tree: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    counts = _count_scandir(monkeypatch)
    recon._candidate_result_paths(DATE, [tree])
    after = dict(counts)
    assert after and set(after.values()) == {1}

    # Reachability contrast: the rglob version lists every directory once per
    # PATTERN. If this ever reads 1, the counter is not seeing the walk.
    counts.clear()
    _reference_candidate_result_paths(DATE, [tree])
    assert set(counts.values()) == {len(recon.RECONCILIATION_PATTERNS)}
    assert set(counts) == set(after)


# --- the per-date reconcile ---------------------------------------------------


def _record(ledger_path: Path, prediction_id: str, *, player: str, market: str = "points", date_value: str = DATE) -> None:
    record_prediction(
        sport="nba",
        market=market,
        selection=f"{player} over 20.5",
        odds=-110,
        features_snapshot={"selected_date": date_value, "player_name": player, "line": 20.5, "pick": "Over"},
        timestamp=f"{date_value}T12:00:00Z",
        prediction_id=prediction_id,
        ledger_path=ledger_path,
    )


def test_reconcile_walks_once_per_date(tree: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ledger_path = tmp_path / "prediction_ledger.json"
    _record(ledger_path, "p1", player="Jane Doe")
    calls: list[str] = []
    real = recon._candidate_result_paths

    def spy(date_value: str, roots: Sequence[Path]) -> list[Path]:
        calls.append(date_value)
        return real(date_value, roots)

    monkeypatch.setattr(recon, "_candidate_result_paths", spy)
    payload = recon.reconcile_prediction_results_for_date(DATE, ledger_path=ledger_path, result_roots=[tree])

    assert calls == [DATE]
    assert payload["summary"]["result_files"] == [str(path) for path in _reference_candidate_result_paths(DATE, [tree])]


def test_the_first_file_in_walk_order_still_settles_a_conflict(tmp_path: Path) -> None:
    """Two files disagree about one player; the one rglob lists FIRST wins, as before."""
    root = tmp_path / "data"
    _write_rows(root / f"a_first/closing_lines_{DATE}.csv", [{"player": "Ann Lee", "market": "points", "result": "loss"}])
    _write_rows(root / f"b_second/closing_lines_{DATE}.csv", [{"player": "Ann Lee", "market": "points", "result": "win"}])
    ledger_path = tmp_path / "prediction_ledger.json"
    _record(ledger_path, "p-ann", player="Ann Lee")

    reference_paths = _reference_candidate_result_paths(DATE, [root])
    reference_rows = recon._result_rows_from_paths(reference_paths)
    prediction = next(p for p in recon.load_all_predictions(ledger_path=ledger_path) if p.get("id") == "p-ann")
    expected = _reference_match_result_row(prediction, reference_rows)
    assert expected is not None

    payload = recon.reconcile_prediction_results_for_date(DATE, ledger_path=ledger_path, result_roots=[root])

    assert payload["summary"]["resolved"] == 1
    assert payload["predictions"][0]["result"]["outcome"] == expected["result"]
    assert payload["summary"]["result_files"] == [str(path) for path in reference_paths]


def test_the_matcher_picks_the_same_row_as_before() -> None:
    rows: list[Any] = [
        "not a row",
        {"player": "Other Guy", "market": "points", "result": "win"},
        {"player": "Jane Doe", "market": "rebounds", "result": "loss"},
        {"market": "", "result": "push"},
        {"player": "Jane Doe", "market": "Points", "result": "win"},
        {"player": "jane_doe", "market": "points", "result": "loss"},
        {"team": "NYL", "market": "moneyline", "result": "win"},
        {},
    ]
    predictions = [
        {"sport": "nba", "market": "points", "selection": "Jane Doe", "features_snapshot": {"player_name": "Jane Doe"}},
        {"sport": "nba", "market": "rebounds", "selection": "Jane Doe"},
        {"sport": "wnba", "market": "moneyline", "selection": "NYL"},
        {"market": "assists", "selection": "Nobody"},
        {},
        {"market": "points"},
    ]
    keyed = recon._keyed_result_rows(rows)
    for prediction in predictions:
        assert recon._match_result_row(prediction, keyed) is _reference_match_result_row(prediction, rows)


def test_unmatched_debug_payload_is_built_only_when_info_is_enabled(
    tree: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    ledger_path = tmp_path / "prediction_ledger.json"
    _record(ledger_path, "p-nobody", player="Nobody Here", market="assists")
    built: list[int] = []
    real = recon._candidate_result_debug_rows

    def spy(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        built.append(len(rows))
        return real(rows)

    monkeypatch.setattr(recon, "_candidate_result_debug_rows", spy)

    caplog.set_level(logging.WARNING, logger=recon.logger.name)
    payload = recon.reconcile_prediction_results_for_date(DATE, ledger_path=ledger_path, result_roots=[tree])
    assert payload["summary"]["skipped"] == 1
    assert built == []

    caplog.set_level(logging.INFO, logger=recon.logger.name)
    recon.reconcile_prediction_results_for_date(DATE, ledger_path=ledger_path, result_roots=[tree])
    assert built and built[0] > 0
    assert any("no match found" in record.getMessage() for record in caplog.records)


def test_each_date_prints_its_timing_split(tree: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ledger_path = tmp_path / "prediction_ledger.json"
    _record(ledger_path, "p1", player="Jane Doe")

    recon.reconcile_prediction_results_for_date(DATE, ledger_path=ledger_path, result_roots=[tree])

    lines = [line for line in capsys.readouterr().out.splitlines() if "RECONCILE_DATE_TIMING" in line]
    assert len(lines) == 1
    line = lines[0]
    assert f"date={DATE}" in line and "predictions=1" in line and "resolved=1" in line
    assert "result_files=10" in line
    for field in ("ledger_s=", "walk_s=", "rows_s=", "match_s=", "write_s=", "total_s="):
        assert field in line
