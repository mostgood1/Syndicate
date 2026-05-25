from __future__ import annotations

import csv
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from syndicate.features.shared.basketball_props_edges import export_props_edges_local


class _FakeMask:
    def __init__(self, values: list[bool]) -> None:
        self.values = values

    def __and__(self, other: "_FakeMask") -> "_FakeMask":
        return _FakeMask([left and right for left, right in zip(self.values, other.values)])


class _FakeSeries:
    def __init__(self, values: list[object]) -> None:
        self.values = values

    def __ge__(self, other: float) -> _FakeMask:
        return _FakeMask([float(value) >= other for value in self.values])

    def astype(self, dtype: object) -> "_FakeSeries":
        if dtype is str or dtype == str or dtype == "str":
            return _FakeSeries(["" if value is None else str(value) for value in self.values])
        return self

    def map(self, func) -> "_FakeSeries":
        return _FakeSeries([func(value) for value in self.values])

    def isin(self, allowed: set[str]) -> _FakeMask:
        return _FakeMask([value in allowed for value in self.values])


class _FakeFrame:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows

    @property
    def empty(self) -> bool:
        return len(self.rows) == 0

    @property
    def columns(self) -> list[str]:
        return list(self.rows[0].keys()) if self.rows else []

    @property
    def index(self) -> range:
        return range(len(self.rows))

    def __getitem__(self, key: object) -> object:
        if isinstance(key, str):
            return _FakeSeries([row.get(key) for row in self.rows])
        if isinstance(key, _FakeMask):
            return _FakeFrame([row for row, keep in zip(self.rows, key.values) if keep])
        raise TypeError(f"Unsupported key: {key!r}")

    def __setitem__(self, key: str, value: object) -> None:
        if isinstance(value, _FakeSeries):
            for row, item in zip(self.rows, value.values):
                row[key] = item
            return
        raise TypeError(f"Unsupported value: {value!r}")

    def copy(self) -> "_FakeFrame":
        return _FakeFrame([dict(row) for row in self.rows])

    def sort_values(self, by: list[str], ascending: list[bool], inplace: bool = False) -> "_FakeFrame":
        rows = list(self.rows)
        for column, is_ascending in reversed(list(zip(by, ascending))):
            rows.sort(key=lambda row: row.get(column), reverse=not is_ascending)
        if inplace:
            self.rows = rows
            return self
        return _FakeFrame(rows)

    def to_csv(self, path: Path, index: bool = False) -> None:
        fieldnames = list(self.rows[0].keys()) if self.rows else []
        with Path(path).open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for row in self.rows:
                writer.writerow(row)


class BasketballPropsEdgesTests(unittest.TestCase):
    def test_export_props_edges_local_uses_local_engine(self) -> None:
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            source_root = root / "source"
            (source_root / "src").mkdir(parents=True, exist_ok=True)
            raw_path = root / "odds.csv"
            predictions_path = root / "predictions.csv"
            out_path = root / "props_edges_2026-05-22.csv"
            local_calls: list[dict[str, object]] = []

            def _fake_local_engine(**kwargs):
                local_calls.append(dict(kwargs))
                return _FakeFrame(
                    [
                        {"stat": "reb", "edge": 0.04, "ev": 0.05, "bookmaker": "fd"},
                        {"stat": "pts", "edge": 0.08, "ev": 0.12, "bookmaker": "dk"},
                    ]
                )

            with patch(
                "syndicate.features.shared.basketball_props_edges._compute_props_edges_file_only_local",
                side_effect=_fake_local_engine,
            ):
                rows, written_path = export_props_edges_local(
                    source_root=source_root,
                    date_str="2026-05-22",
                    raw_path=raw_path,
                    predictions_path=predictions_path,
                    out_path=out_path,
                    bookmakers="draftkings,fanduel",
                )

            self.assertEqual(len(local_calls), 1)
            self.assertEqual(local_calls[0]["date_str"], "2026-05-22")
            self.assertEqual(rows, 2)
            self.assertEqual(written_path, out_path)
            with out_path.open("r", encoding="utf-8", newline="") as handle:
                written_rows = list(csv.DictReader(handle))

        self.assertEqual(len(written_rows), 2)
        self.assertEqual(written_rows[0]["stat"], "pts")
        self.assertEqual(written_rows[1]["stat"], "reb")
        self.assertEqual(written_rows[0]["bookmaker"], "draftkings")
        self.assertEqual(written_rows[1]["bookmaker"], "fanduel")


if __name__ == "__main__":
    unittest.main()