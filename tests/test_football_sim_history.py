"""Dated copies of each weekly football sim write (todo #807, lane ncaaf-sim-write-history).

`generate_smartsim2_ncaaf_projections.py` rewrites the week's projections CSV and
segment sidecar once a day, so only the week's last write survived and todo #805 had
to refuse every game priced off an earlier one. `archive_sim_write` keeps each write
as a dated gzip pair under `<SYNDICATE_DATA_ROOT>/sim_history/<sport>/`, skips a write
whose content equals the newest kept copy, and keeps the copies out of every sport
root, the scanned artifact manifest and the publish/export allowlists.
"""

from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

import pytest

from syndicate.features.shared import football_segment_distributions as F

REPO = Path(__file__).resolve().parents[1]
SEG = {"total_points_dist": {"3": 30, "7": 70}, "margin_dist": {"-3": 40, "3": 60},
       "home_points_mean": 5.0, "away_points_mean": 3.0}
HEADER = "game_id,season,week,home_team,away_team,total_mean,generated_at\n"


def _write(root: Path, *, week=11, generated_at="2026-11-12T16:08:20.269000+00:00", total="46.9",
           games=None) -> tuple[Path, Path]:
    root.mkdir(parents=True, exist_ok=True)
    csv_path = root / f"smartsim2_projections_2026_wk{week}.csv"
    csv_path.write_text(HEADER + f"401999001,2026,{week},Ohio State,Michigan,{total},{generated_at}\n",
                        encoding="utf-8")
    sidecar = root / f"smartsim2_segment_distributions_2026_wk{week}.json"
    payload = {"schema_version": 1, "season": 2026, "week": week, "generated_at": generated_at,
               "games": games if games is not None else {"401999001": {"sims": 100, "segments": {"q1": SEG}}}}
    sidecar.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return csv_path, sidecar


def _keep(root: Path, history: Path, **kw):
    csv_path, sidecar = _write(root, **kw)
    return F.archive_sim_write(projections_csv=csv_path, sidecar=sidecar, season=2026,
                               week=kw.get("week", 11), history_dir=history)


def test_a_write_is_kept_as_a_gzip_pair_stamped_from_the_sidecars_own_generated_at(tmp_path):
    live, history = tmp_path / "ncaaf_source" / "data", tmp_path / "sim_history" / "ncaaf"
    kept = _keep(live, history)
    assert kept == history / "smartsim2_segment_distributions_2026_wk11.20261112T160820Z.json.gz"
    csv_copy = history / "smartsim2_projections_2026_wk11.20261112T160820Z.csv.gz"
    assert gzip.decompress(kept.read_bytes()) == (live / "smartsim2_segment_distributions_2026_wk11.json").read_bytes()
    assert gzip.decompress(csv_copy.read_bytes()) == (live / "smartsim2_projections_2026_wk11.csv").read_bytes()
    assert not list(history.glob("*.tmp"))


def test_an_unchanged_rerun_adds_nothing_even_though_every_csv_row_has_a_new_generated_at(tmp_path):
    live, history = tmp_path / "live", tmp_path / "history"
    assert _keep(live, history) is not None
    assert _keep(live, history, generated_at="2026-11-13T16:26:02.205000+00:00") is None
    assert len(list(history.glob("*.json.gz"))) == 1 and len(list(history.glob("*.csv.gz"))) == 1


@pytest.mark.parametrize("change", [
    {"total": "47.3"},  # the CSV moved
    {"games": {"401999001": {"sims": 100, "segments": {"q1": {**SEG, "home_points_mean": 5.5}}}}},  # the sidecar moved
])
def test_a_changed_write_is_kept_beside_the_first(tmp_path, change):
    live, history = tmp_path / "live", tmp_path / "history"
    _keep(live, history)
    assert _keep(live, history, generated_at="2026-11-13T16:26:02+00:00", **change) is not None
    assert sorted(p.name for p in history.glob("*.json.gz")) == [
        "smartsim2_segment_distributions_2026_wk11.20261112T160820Z.json.gz",
        "smartsim2_segment_distributions_2026_wk11.20261113T162602Z.json.gz",
    ]


ROWS = [("401999001", "Ohio State", "Michigan", "46.9"), ("401999002", "Texas", "Texas A&M", "51.2"),
        ("401999003", "Oregon", "Washington", "55.0")]


def _keep_rows(root: Path, history: Path, rows, *, generated_at):
    csv_path, sidecar = _write(root, generated_at=generated_at)
    csv_path.write_text(HEADER + "".join(f"{g},2026,11,{h},{a},{t},{generated_at}\n" for g, h, a, t in rows),
                        encoding="utf-8")
    return F.archive_sim_write(projections_csv=csv_path, sidecar=sidecar, season=2026, week=11, history_dir=history)


def test_the_same_rows_in_another_order_add_nothing(tmp_path):
    # Fleet 2026-11-17 06:31:45Z: the generator rewrote wk12 with every row equal by
    # game_id but 56 of 66 in another position, and the ordered compare kept it.
    live, history = tmp_path / "live", tmp_path / "history"
    assert _keep_rows(live, history, ROWS, generated_at="2026-11-16T06:26:36+00:00") is not None
    assert _keep_rows(live, history, [ROWS[2], ROWS[0], ROWS[1]], generated_at="2026-11-17T06:31:45+00:00") is None
    assert len(list(history.glob("*.json.gz"))) == 1 and len(list(history.glob("*.csv.gz"))) == 1


@pytest.mark.parametrize("rows", [
    [ROWS[2], ROWS[0], ROWS[1][:3] + ("51.4",)],  # reordered AND one value moved
    [ROWS[1], ROWS[0]],                           # a row dropped
    [ROWS[0], ROWS[0], ROWS[1], ROWS[2]],         # a row repeated: same set, not the same rows
])
def test_reordered_rows_that_also_changed_are_still_kept(tmp_path, rows):
    live, history = tmp_path / "live", tmp_path / "history"
    _keep_rows(live, history, ROWS, generated_at="2026-11-16T06:26:36+00:00")
    assert _keep_rows(live, history, rows, generated_at="2026-11-17T06:31:45+00:00") is not None
    assert len(list(history.glob("*.json.gz"))) == 2


def test_a_malformed_row_compares_instead_of_raising(tmp_path):
    # csv.DictReader files extra fields under the key None (a list value); the compare
    # must not raise on it, or keep_sim_write would log sim_history_error and keep nothing.
    rows = [{"game_id": "1", "total_mean": "46.9"}, {"game_id": "2", "total_mean": "51.2", None: ["x"]}]
    assert F._row_multiset(rows) == F._row_multiset(list(reversed(rows)))
    assert F._row_multiset(rows) != F._row_multiset(rows[:1])


def test_the_same_write_twice_is_kept_once(tmp_path):
    live, history = tmp_path / "live", tmp_path / "history"
    first = _keep(live, history)
    assert first is not None and _keep(live, history) is None


def test_weeks_never_dedupe_each_other(tmp_path):
    # `_wk1.` must not match `_wk10.`: identical content in another week is still kept.
    live, history = tmp_path / "live", tmp_path / "history"
    assert _keep(live, history, week=10) is not None
    assert _keep(live, history, week=1) is not None
    assert len(list(history.glob("*.json.gz"))) == 2


def test_the_history_lives_under_the_data_root_outside_every_sport_root(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    assert F.sim_history_dir(sport="ncaaf") == tmp_path / "sim_history" / "ncaaf"
    monkeypatch.delenv("SYNDICATE_DATA_ROOT")
    assert F.sim_history_dir(sport="ncaaf") == REPO / "data" / "sim_history" / "ncaaf"


def test_kept_copies_are_not_in_the_scanned_manifest_nor_publishable_nor_exportable(tmp_path, monkeypatch):
    from syndicate.features.shared import artifact_manifests
    from syndicate.features.shared.artifact_publisher import (
        is_export_only_artifact_relative_path,
        is_hot_artifact_relative_path,
    )

    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("SYNDICATE_NCAAF_SOURCE_ROOT", str(tmp_path / "ncaaf_source"))
    live = tmp_path / "ncaaf_source" / "data"
    kept = _keep(live, F.sim_history_dir(sport="ncaaf"))
    assert kept is not None and kept.exists()

    # Positive control: the live sidecar IS in the scan, so an empty scan cannot pass this.
    manifest = artifact_manifests._load_scanned_manifest("ncaaf")
    paths = [str(ref.path) for group in (manifest.predictions, manifest.edges, manifest.recommendations,
                                         manifest.live_data) for ref in group]
    assert any("smartsim2_segment_distributions_2026_wk11.json" in p for p in paths)
    assert not any("sim_history" in p for p in paths)

    for name in (kept.name, kept.name.replace("segment_distributions", "projections").replace(".json.gz", ".csv.gz")):
        relative = f"sim_history/ncaaf/{name}"
        assert not is_hot_artifact_relative_path(relative)
        assert not is_export_only_artifact_relative_path(relative)
    assert is_hot_artifact_relative_path("ncaaf_source/data/smartsim2_segment_distributions_2026_wk11.json")


def _generator():
    sys.path.insert(0, str(REPO / "scripts"))
    import generate_smartsim2_ncaaf_projections as gen

    return gen


def test_the_generator_keeps_each_write_and_never_raises(tmp_path, monkeypatch):
    gen = _generator()
    live, history = tmp_path / "live", tmp_path / "history"
    csv_path, sidecar = _write(live)
    line = gen.keep_sim_write(csv_path, sidecar, season=2026, week=11, history_dir=history)
    assert line == f"sim_history_kept={history / 'smartsim2_segment_distributions_2026_wk11.20261112T160820Z.json.gz'}"
    assert gen.keep_sim_write(csv_path, sidecar, season=2026, week=11, history_dir=history) == "sim_history_kept=unchanged"

    def boom(**_kw):
        raise OSError("disk full")

    monkeypatch.setattr(F, "archive_sim_write", boom)
    assert gen.keep_sim_write(csv_path, sidecar, season=2026, week=11, history_dir=history) == (
        "sim_history_error=OSError: disk full")


def test_the_generator_imports_no_new_name_at_module_top():
    # An old refresh-worker process holding the OLD sidecar module may import this
    # generator in-process between a fleet ff and its restart: a top-level import of a
    # name only the new module has would raise there. The names are imported lazily.
    import ast

    tree = ast.parse((REPO / "scripts" / "generate_smartsim2_ncaaf_projections.py").read_text(encoding="utf-8"))
    top = {alias.name for node in tree.body if isinstance(node, ast.ImportFrom) for alias in node.names}
    assert not top & {"archive_sim_write", "sim_history_dir", "sim_history_names"}


def test_main_calls_the_keeper_right_after_the_sidecar_write():
    # `main` is one long CFBD-driven function, so this pins the call site in its source:
    # inside the segments-enabled branch, after the sidecar write, before the publish.
    import inspect

    source = inspect.getsource(_generator().main)
    write = source.index("write_segment_distributions_artifact(")
    keep = source.index("keep_sim_write(path, segment_path, season=args.season, week=args.week)")
    off = source.index('print("segment_distributions=off"')
    publish = source.index("PUBLISH TO WEB")
    assert write < keep < off < publish
