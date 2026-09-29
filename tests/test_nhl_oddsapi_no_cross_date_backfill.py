"""NHL generation must not write another date's rows under this date's filename.

`scripts/refresh_nhl_oddsapi.py` used to glob the newest OTHER-dated CSV in
`data/processed/` and copy it verbatim onto today's filename, for six
REQUIRED_ARTIFACTS families, purely so `_missing_required_artifacts` would come
back empty -- and that is a warning, never a gate. It fired only when the
destination did not exist, i.e. only when generation had produced nothing real,
so it could never supply anything correct.

Measured 2026-09-28: `predictions_sim_2026-09-28.csv` and
`predictions_sim_2026-09-27.csv` both held the 2026-09-19 preseason slate, and the
Layer 2 compact rail served those seven games as today's on a date with zero real
NHL games. The near miss that settled it: `predictions_sim_2026-09-29.csv` was
absent the evening before the opener, so the next run would have copied 09-19's
rows onto the opener's sim filename -- and MTL @ TOR is on both slates.

`test_the_old_backfill_would_have_fabricated_this_file` reimplements the deleted
logic so these tests demonstrably discriminate: without it, a test asserting "no
file appeared" passes trivially on any codebase that never had the bug.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "refresh_nhl_oddsapi",
    Path(__file__).resolve().parents[1] / "scripts" / "refresh_nhl_oddsapi.py",
)


@pytest.fixture(scope="module")
def mod():
    module = importlib.util.module_from_spec(_SPEC)
    _SPEC.loader.exec_module(module)
    return module


_HEADER = "home,away,date,p_home_ml,p_away_ml,model_total\n"

# The seven that actually leaked, in production's order.
_SEPT_19_SLATE = [
    ("St. Louis Blues", "Dallas Stars"),
    ("Toronto Maple Leafs", "Montreal Canadiens"),
    ("Montreal Canadiens", "Toronto Maple Leafs"),
    ("Edmonton Oilers", "Winnipeg Jets"),
    ("Minnesota Wild", "Chicago Blackhawks"),
    ("Los Angeles Kings", "Vegas Golden Knights"),
    ("Seattle Kraken", "Vancouver Canucks"),
]


def _populate_old_date(root: Path, old_date: str) -> None:
    """An artifact root holding a POPULATED older date and nothing for the new one
    -- exactly the state in which the backfill used to fire."""
    processed = root / "data" / "processed"
    processed.mkdir(parents=True, exist_ok=True)
    body = _HEADER + "".join(f"{h},{a},{old_date},0.55,0.45,6.1\n" for h, a in _SEPT_19_SLATE)
    for name in (f"predictions_{old_date}.csv", f"predictions_sim_{old_date}.csv"):
        (processed / name).write_text(body, encoding="utf-8")


def test_the_old_backfill_would_have_fabricated_this_file(tmp_path: Path) -> None:
    """DISCRIMINATION. The deleted logic, reimplemented, to show the state below
    is one in which a backfill really would have written a file."""
    _populate_old_date(tmp_path, "2026-09-19")
    processed = tmp_path / "data" / "processed"
    destination = processed / "predictions_sim_2026-09-29.csv"
    assert not destination.exists()

    # ---- the deleted implementation, verbatim in behaviour ----
    for prefix in ("predictions_sim", "predictions"):
        for source in sorted(processed.glob(f"{prefix}_*.csv"), reverse=True):
            if source.name == destination.name or source.stem.endswith("2026-09-29"):
                continue
            destination.write_bytes(source.read_bytes())
            break
        if destination.exists():
            break

    assert destination.exists(), "fixture does not reproduce the pre-fix condition"
    assert "2026-09-19" in destination.read_text(encoding="utf-8")


def test_the_backfill_helpers_are_gone(mod) -> None:
    """Reintroduction guard. Named explicitly so a revert fails a test instead of
    quietly restoring a writer that can only fabricate."""
    assert not hasattr(mod, "_backfill_latest_dated_csv")
    assert not hasattr(mod, "_backfill_required_compatibility_artifacts")


def test_no_source_line_copies_a_differently_dated_csv_onto_a_dated_name() -> None:
    source = (Path(__file__).resolve().parents[1] / "scripts" / "refresh_nhl_oddsapi.py").read_text(encoding="utf-8")
    # The comment block explaining the removal is allowed to name them; a call is not.
    assert "_backfill_latest_dated_csv(" not in source
    assert "_backfill_required_compatibility_artifacts(" not in source
    assert "backfilled compatibility artifacts" not in source


def test_missing_artifacts_are_reported_and_nothing_is_written(mod, tmp_path: Path) -> None:
    """The behaviour that replaces the backfill: say what is missing, write nothing."""
    _populate_old_date(tmp_path, "2026-09-19")
    processed = tmp_path / "data" / "processed"
    before = sorted(p.name for p in processed.iterdir())

    missing = mod._missing_required_artifacts(artifact_root=tmp_path, date_str="2026-09-29")

    assert "data/processed/predictions_sim_2026-09-29.csv" in missing
    assert "data/processed/predictions_2026-09-29.csv" in missing
    assert sorted(p.name for p in processed.iterdir()) == before, "reporting must not create files"


def test_a_populated_date_reports_nothing_missing_for_the_files_it_has(mod, tmp_path: Path) -> None:
    """The reporter is not simply always-missing: a present file is not listed, so
    the test above is about absence rather than about a broken check."""
    _populate_old_date(tmp_path, "2026-09-19")

    missing = mod._missing_required_artifacts(artifact_root=tmp_path, date_str="2026-09-19")

    assert "data/processed/predictions_2026-09-19.csv" not in missing
    assert "data/processed/predictions_sim_2026-09-19.csv" not in missing
    # ...while the families that were never written ARE still reported.
    assert "data/processed/lineups_2026-09-19.csv" in missing


def test_the_warning_says_no_placeholder_was_written() -> None:
    """A bare 'missing required artifacts' warning reads the same whether or not
    something was substituted. This is the sentence that distinguishes them."""
    source = (Path(__file__).resolve().parents[1] / "scripts" / "refresh_nhl_oddsapi.py").read_text(encoding="utf-8")
    assert "NO placeholder written" in source
