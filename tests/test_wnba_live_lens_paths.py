"""Live-lens artifacts are read from the directory the writer actually writes to.

The defect, measured 2026-08-31 (lane `wnba-accuracy-assessment`): every WNBA
live-accuracy endpoint reported `signals.exists: false` on every date sampled
while 34 consecutive days of signals (106KB-1.23MB each) sat on the Render disk.
Production sets `WNBA_LIVE_LENS_DIR=.../data/live_lens`; every Syndicate-side
reader built `.../data/processed/live_lens_signals_<date>.jsonl`.

`test_signals_are_unreadable_under_the_old_rule` is the REACHABILITY test and
has to come first: it pins the pre-fix behaviour so a regression that quietly
restores it fails here rather than showing up as another silent five-week gap.
Without it, every assertion below would also pass against a reader that only
ever looked in `data/processed`, on a fixture that happened to put the file
there.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from syndicate.features.shared import live_lens_paths


DATE = "2026-08-30"
SIGNALS = f"live_lens_signals_{DATE}.jsonl"
PROJECTIONS = f"live_lens_projections_{DATE}.jsonl"


@pytest.fixture()
def wnba_tree(tmp_path: Path) -> dict[str, Path]:
    """The production layout: CSVs in `data/processed`, JSONL in `data/live_lens`."""
    source = tmp_path / "wnba_source" / "source_artifacts" / "data"
    processed = source / "processed"
    live_lens = source / "live_lens"
    processed.mkdir(parents=True)
    live_lens.mkdir(parents=True)
    (processed / f"recommendations_{DATE}.csv").write_text("date,pick\n", encoding="utf-8")
    (live_lens / SIGNALS).write_text(
        json.dumps({"date": DATE, "klass": "BET", "market": "player_prop"}) + "\n",
        encoding="utf-8",
    )
    return {"processed": processed, "live_lens": live_lens}


# --------------------------------------------------------------- reachability
def test_signals_are_unreadable_under_the_old_rule(wnba_tree):
    """OFF != ON. The old rule was `root / filename`; on this tree it misses."""
    old_rule = wnba_tree["processed"] / SIGNALS
    assert not old_rule.exists(), (
        "fixture does not reproduce the defect -- it must NOT place signals in "
        "data/processed, or every assertion below is vacuous"
    )
    assert (wnba_tree["live_lens"] / SIGNALS).is_file()


def test_resolver_finds_the_signals_the_old_rule_missed(wnba_tree):
    resolved = live_lens_paths.resolve(wnba_tree["processed"], SIGNALS)
    assert resolved == wnba_tree["live_lens"] / SIGNALS
    assert resolved.is_file()


# ------------------------------------------------------------------ behaviour
def test_csv_resolution_is_untouched(wnba_tree):
    """The fix is additive: non-live-lens filenames resolve exactly as before."""
    name = f"recommendations_{DATE}.csv"
    resolved = live_lens_paths.resolve(wnba_tree["processed"], name)
    assert resolved == wnba_tree["processed"] / name
    assert live_lens_paths.candidate_paths(wnba_tree["processed"], name) == [
        wnba_tree["processed"] / name
    ]


def test_missing_file_reports_the_live_lens_directory_not_processed(wnba_tree):
    """A miss must name where the file WOULD be.

    Reporting `data/processed/...` on a miss is what made this read as "the
    producer never ran" for five weeks.
    """
    missing = live_lens_paths.resolve(wnba_tree["processed"], "live_lens_signals_1999-01-01.jsonl")
    assert missing.parent == wnba_tree["live_lens"]


def test_env_var_directory_wins_when_set(tmp_path, monkeypatch):
    processed = tmp_path / "wnba_source" / "data" / "processed"
    elsewhere = tmp_path / "mounted" / "wnba_live_lens"
    processed.mkdir(parents=True)
    elsewhere.mkdir(parents=True)
    (elsewhere / SIGNALS).write_text("{}\n", encoding="utf-8")
    monkeypatch.setenv("WNBA_LIVE_LENS_DIR", str(elsewhere))
    assert live_lens_paths.resolve(processed, SIGNALS) == elsewhere / SIGNALS


def test_env_var_of_another_sport_is_never_used(tmp_path, monkeypatch):
    """A filename carries a date but not a sport; a cross-sport hit would be silent."""
    wnba_processed = tmp_path / "wnba_source" / "data" / "processed"
    mlb_live_lens = tmp_path / "mlb_source" / "data" / "live_lens"
    wnba_processed.mkdir(parents=True)
    mlb_live_lens.mkdir(parents=True)
    (mlb_live_lens / SIGNALS).write_text("{}\n", encoding="utf-8")
    monkeypatch.setenv("MLB_LIVE_LENS_DIR", str(mlb_live_lens))
    monkeypatch.delenv("WNBA_LIVE_LENS_DIR", raising=False)
    resolved = live_lens_paths.resolve(wnba_processed, SIGNALS)
    assert mlb_live_lens not in resolved.parents
    assert resolved.parent != mlb_live_lens


def test_multiple_roots_resolve_per_requested_file(tmp_path):
    """`#309`: the file decides the root, not a guess made up front."""
    root_a = tmp_path / "wnba_source" / "source_artifacts" / "data"
    root_b = tmp_path / "wnba_source" / "data"
    (root_a / "processed").mkdir(parents=True)
    (root_a / "live_lens").mkdir(parents=True)
    (root_b / "processed").mkdir(parents=True)
    (root_b / "live_lens").mkdir(parents=True)
    # Signals only on root B, projections only on root A.
    (root_b / "live_lens" / SIGNALS).write_text("{}\n", encoding="utf-8")
    (root_a / "live_lens" / PROJECTIONS).write_text("{}\n", encoding="utf-8")
    roots = [root_a / "processed", root_b / "processed"]
    assert live_lens_paths.resolve(roots, SIGNALS) == root_b / "live_lens" / SIGNALS
    assert live_lens_paths.resolve(roots, PROJECTIONS) == root_a / "live_lens" / PROJECTIONS


def test_shared_reader_uses_the_resolver(wnba_tree):
    """The wiring, not just the helper -- a correct helper nobody calls is inert."""
    from syndicate.features.shared import live_lens_local

    resolved = live_lens_local._artifact_path(wnba_tree["processed"], SIGNALS)
    assert resolved == wnba_tree["live_lens"] / SIGNALS

    resolved_list = live_lens_local._artifact_path([wnba_tree["processed"]], SIGNALS)
    assert resolved_list == wnba_tree["live_lens"] / SIGNALS


def test_wnba_accuracy_modules_pass_every_candidate_root():
    """They passed a single `processed_root()`, which `#309` says picks wrong."""
    from syndicate.features.wnba import (
        live_game_accuracy,
        live_lens_daily_accuracy,
        live_prop_accuracy,
        live_prop_audit,
    )

    for module in (live_lens_daily_accuracy, live_game_accuracy, live_prop_accuracy, live_prop_audit):
        root = module._artifact_root()
        assert isinstance(root, list), f"{module.__name__} must pass every candidate root"
        assert root, f"{module.__name__} resolved no roots at all"


# ------------------------------------------------- leakage-visibility contract
def _scored(period: int, result: str, n: int) -> list[dict]:
    return [
        {
            "market": "player_prop", "period": period, "line_source": "oddsapi",
            "result": result, "profit_units": 0.909 if result == "win" else -1.0,
            "lens": "pts", "side": "OVER", "driver_tags": [],
        }
        for _ in range(n)
    ]


def test_period_breakdown_is_exposed():
    from syndicate.features.shared import live_lens_local

    rows = _scored(1, "win", 20) + _scored(4, "win", 20)
    payload = live_lens_local._attach_breakdowns({"n_settled": 40}, rows)
    periods = {row["period"] for row in payload["by_period"]}
    assert {"Q1", "Q4"} <= periods
    assert any(row.get("line_source") == "oddsapi" for row in payload["by_line_source"])


def test_leakage_note_fires_on_the_real_shape():
    """The measured WNBA shape: Q1 55.1% -> Q2 78.8% -> Q3 78.1% -> Q4 98.0%.

    Q3 dips below Q2. A strict-monotonicity guard stayed silent on exactly this
    data, which is the failure this test exists to prevent.
    """
    from syndicate.features.shared import live_lens_local

    rows = (
        _scored(1, "win", 55) + _scored(1, "loss", 45)
        + _scored(2, "win", 79) + _scored(2, "loss", 21)
        + _scored(3, "win", 78) + _scored(3, "loss", 22)
        + _scored(4, "win", 98) + _scored(4, "loss", 2)
    )
    payload = live_lens_local._attach_breakdowns({"n_settled": len(rows)}, rows)
    note = payload["leakage_note"]
    assert note, "guard must fire on the shape it was written for, dip and all"
    assert "PREGAME" in note


def test_leakage_note_silent_when_flat():
    from syndicate.features.shared import live_lens_local

    rows = (
        _scored(1, "win", 55) + _scored(1, "loss", 45)
        + _scored(4, "win", 56) + _scored(4, "loss", 44)
    )
    payload = live_lens_local._attach_breakdowns({"n_settled": len(rows)}, rows)
    assert payload["leakage_note"] is None


def test_self_priced_rows_are_counted_not_silently_dropped(tmp_path):
    """`by_line_source` with no `model` row must not read as "never happened"."""
    from syndicate.features.shared import live_lens_local

    processed = tmp_path / "wnba_source" / "data" / "processed"
    live_lens = tmp_path / "wnba_source" / "data" / "live_lens"
    processed.mkdir(parents=True)
    live_lens.mkdir(parents=True)
    lines = []
    for source in ("model", "model", "oddsapi"):
        lines.append(json.dumps({
            "market": "player_prop", "klass": "BET", "line_source": source,
            "game_id_canon": "0401857186", "player": "A B", "name_key": "A B",
            "stat": "pts", "side": "OVER", "line": 10.0, "period": 1,
        }))
    (live_lens / SIGNALS).write_text("\n".join(lines) + "\n", encoding="utf-8")

    _rows, meta = live_lens_local._score_day(
        processed, DATE, allowed_markets={"player_prop"}, assume_price=-110.0
    )
    assert meta["signals"]["self_priced_excluded"] == 2
    assert meta["signals"]["filtered"] == 1
