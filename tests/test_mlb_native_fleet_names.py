"""The MLB native tools' Render names became fleet names on 2026-11-17 (lane
mlb-native-fleet-names, todo #766 follow-up). Names only: the URLs were repointed at the
fleet by lane render-retirement (`193df776e`).

This pins the compatibility the rename promised:
- every old CLI flag (and the old `--source render-sync` value) still parses, to the same
  destination as its new spelling;
- the two renamed scripts still run, and still import, by their old names (shims);
- `daily_update.py` launches and passes only the new names, and its next-day relaunch strips
  BOTH spellings;
- the on-disk `live_lens/render_sync/` directory is unchanged (no migration was made);
- the two ops-report readers count both the new and the old validation-error prefix.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "syndicate" / "features" / "mlb" / "native" / "tools"


class _Parsed(Exception):
    def __init__(self, namespace: argparse.Namespace) -> None:
        super().__init__("parsed")
        self.namespace = namespace


def _parse_main(monkeypatch: pytest.MonkeyPatch, main, argv: list[str]) -> argparse.Namespace:
    """Run `main()` up to its parse_args and return the namespace (nothing after it runs)."""
    real_parse = argparse.ArgumentParser.parse_args

    def _stop_after_parse(self, args=None, namespace=None):
        raise _Parsed(real_parse(self, args, namespace))

    monkeypatch.setattr(argparse.ArgumentParser, "parse_args", _stop_after_parse)
    monkeypatch.setattr(sys, "argv", ["prog", *argv])
    with pytest.raises(_Parsed) as caught:
        main()
    return caught.value.namespace


# --- daily_update.py ---------------------------------------------------------------------


def test_daily_update_old_validation_flags_parse_to_the_new_destinations(monkeypatch) -> None:
    import syndicate.features.mlb.native.tools.daily_update as DU

    new = _parse_main(monkeypatch, DU.main, [
        "--validate-fleet-frontend", "off",
        "--fleet-validation-base-url", "http://a",
        "--fleet-validation-cron-token", "t1",
        "--fleet-validation-timeout-seconds", "7",
    ])
    old = _parse_main(monkeypatch, DU.main, [
        "--validate-render-frontend", "off",
        "--render-validation-base-url", "http://a",
        "--render-validation-cron-token", "t1",
        "--render-validation-timeout-seconds", "7",
    ])
    keys = ("validate_fleet_frontend", "fleet_validation_base_url",
            "fleet_validation_cron_token", "fleet_validation_timeout_seconds")
    assert [getattr(new, k) for k in keys] == ["off", "http://a", "t1", 7]
    assert [getattr(old, k) for k in keys] == [getattr(new, k) for k in keys]
    assert not any("render" in k for k in vars(new)), sorted(k for k in vars(new) if "render" in k)


def test_next_day_relaunch_strips_both_spellings_and_passes_the_new_one() -> None:
    import syndicate.features.mlb.native.tools.daily_update as DU

    args = argparse.Namespace(season=2026, date="2026-06-01", seed=1337, seed_source="default_fixed")
    raw_argv = [
        "--sims", "10",
        "--validate-render-frontend", "on",
        "--render-validation-base-url", "http://old",
        "--fleet-validation-cron-token", "tok",
        "--fleet-validation-timeout-seconds=9",
    ]
    cmd = DU._build_next_day_ui_daily_command(args, raw_argv, "2026-06-02")
    flat = " ".join(cmd)
    assert "render" not in flat.replace(str(TOOLS), ""), flat
    assert cmd.count("--validate-fleet-frontend") == 1
    assert cmd[cmd.index("--validate-fleet-frontend") + 1] == "off"
    for gone in ("http://old", "tok", "--fleet-validation-cron-token", "--fleet-validation-timeout-seconds=9"):
        assert gone not in cmd, gone
    assert cmd[cmd.index("--sims") + 1] == "10"


def test_frontend_validation_stage_launches_the_fleet_smoke(monkeypatch) -> None:
    import syndicate.features.mlb.native.tools.daily_update as DU

    seen: dict = {}

    def _fake_run(cmd, **kwargs):
        seen["cmd"] = list(cmd)
        return types.SimpleNamespace(returncode=0, stdout=json.dumps({"failures": []}), stderr="")

    monkeypatch.setattr(DU.subprocess, "run", _fake_run)
    args = argparse.Namespace(
        validate_fleet_frontend="on",
        fleet_validation_base_url="http://127.0.0.1:10000",
        fleet_validation_cron_token="",
        fleet_validation_timeout_seconds=5,
        live_lens_base_url="",
        live_lens_cron_token="",
    )
    stage = DU._run_fleet_frontend_validation_stage(args, date_str="2026-06-01", season=2026, expected_commit="abc")
    assert stage["status"] == "ok", stage
    smoke = Path(seen["cmd"][1])
    assert smoke.name == "smoke_fleet_frontend.py" and smoke.is_file()
    assert seen["cmd"][seen["cmd"].index("--base-url") + 1] == "http://127.0.0.1:10000"

    off = DU._run_fleet_frontend_validation_stage(
        argparse.Namespace(validate_fleet_frontend="off"), date_str="2026-06-01", season=2026, expected_commit="abc"
    )
    assert off == {"status": "skipped", "date": "2026-06-01", "season": 2026, "reason": "validate_fleet_frontend=off"}


@pytest.mark.parametrize("prop", ["outs", "strikeouts"])
def test_corrections_stage_commands_parse_in_the_fit_scripts(monkeypatch, prop) -> None:
    """Every flag `daily_update.py` passes to a fitter is one that fitter's parser accepts,
    and lands where the new names say."""
    import syndicate.features.mlb.native.tools.daily_update as DU

    launched: list[list[str]] = []

    def _fake_logged(cmd, **kwargs):
        launched.append([str(part) for part in cmd])
        return types.SimpleNamespace(returncode=0, stdout="{}", stderr="")

    monkeypatch.setattr(DU, "_run_logged_subprocess", _fake_logged)
    args = argparse.Namespace(
        refresh_live_pitcher_corrections="on",
        live_lens_base_url="http://127.0.0.1:10000",
        live_lens_cron_token="tok",
        live_lens_timeout_seconds=11,
    )
    stage = DU._refresh_live_pitcher_corrections_stage(args, max_date_str="2026-06-01")
    assert stage["base_url"] == "http://127.0.0.1:10000" and "render_base_url" not in stage
    cmd = next(c for c in launched if c[1].endswith(f"fit_live_pitcher_{prop}_correction.py"))
    assert not any("render" in part for part in cmd[2:]), cmd

    module = __import__(f"syndicate.features.mlb.native.tools.tune.fit_live_pitcher_{prop}_correction", fromlist=["main"])
    ns = _parse_main(monkeypatch, module.main, cmd[2:])
    assert (ns.source, ns.sync_fleet, ns.fleet_base_url, ns.fleet_cron_token, ns.fleet_timeout_seconds) == (
        "fleet-sync", "on", "http://127.0.0.1:10000", "tok", 11)


def test_prior_day_live_lens_stage_keeps_the_render_sync_directory(monkeypatch, tmp_path) -> None:
    import syndicate.features.mlb.native.tools.daily_update as DU

    monkeypatch.setattr(DU, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(DU, "_fetch_live_lens_reports_payload", lambda **kw: {"latestReport": {}, "registrySummary": {}})
    args = argparse.Namespace(sync_live_lens="on", live_lens_base_url="127.0.0.1:10000", live_lens_cron_token="tok",
                              live_lens_timeout_seconds=5, live_lens_sync_out="")
    stage = DU._prior_day_live_lens_stage(args, "2026-06-01")
    assert stage["source"] == "fleet_api" and stage["base_url"] == "https://127.0.0.1:10000", stage
    assert "render_base_url" not in stage
    assert (tmp_path / "live_lens" / "render_sync" / "live_lens_reports_2026_06_01.json").is_file()
    assert DU._LIVE_LENS_SYNC_DIRNAME == "render_sync"


# --- the tune scripts ----------------------------------------------------------------------


@pytest.mark.parametrize("module_name", [
    "syndicate.features.mlb.native.tools.tune.export_live_pitcher_projection_dataset",
    "syndicate.features.mlb.native.tools.tune.fit_live_pitcher_outs_correction",
    "syndicate.features.mlb.native.tools.tune.fit_live_pitcher_strikeouts_correction",
])
def test_tune_scripts_accept_old_flags_and_old_source_value(monkeypatch, module_name) -> None:
    module = __import__(module_name, fromlist=["main"])
    old = _parse_main(monkeypatch, module.main, [
        "--source", "render-sync", "--sync-render", "off",
        "--render-base-url", "http://a", "--render-cron-token", "t", "--render-timeout-seconds", "3",
    ])
    new = _parse_main(monkeypatch, module.main, [
        "--source", "fleet-sync", "--sync-fleet", "off",
        "--fleet-base-url", "http://a", "--fleet-cron-token", "t", "--fleet-timeout-seconds", "3",
    ])
    keys = ("sync_fleet", "fleet_base_url", "fleet_cron_token", "fleet_timeout_seconds")
    assert [getattr(old, k) for k in keys] == [getattr(new, k) for k in keys] == ["off", "http://a", "t", 3]
    from syndicate.features.mlb.native.tools.tune import export_live_pitcher_projection_dataset as EX
    assert EX._normalize_source(old.source) == EX._normalize_source(new.source) == "fleet-sync"


def test_fleet_sync_reads_the_render_sync_directory_under_both_source_names(tmp_path) -> None:
    from syndicate.features.mlb.native.tools.tune import export_live_pitcher_projection_dataset as EX

    sync_dir = tmp_path / "render_sync"
    sync_dir.mkdir()
    archive_row = {
        "market": "pitcher_props", "prop": "outs", "selection": "over", "key": "k1", "owner": "P",
        "marketLine": 16.5, "teamSide": "home", "finalActual": 18,
        "firstSeenSnapshot": {"actual": 6, "liveProjection": 17.0},
        "gameState": {"progressFraction": 0.3, "inning": 3, "status": "Live"},
    }
    (sync_dir / "live_lens_reports_2026_06_01.json").write_text(
        json.dumps({"date": "2026-06-01", "firstObservationArchive": [archive_row]}), encoding="utf-8")
    direct = list(EX._iter_fleet_sync_projection_rows(tmp_path, {"outs"}, include_pregame=True))
    by_new = EX._collect_projection_rows(tmp_path, {"outs"}, source="fleet-sync", include_pregame=True)
    by_old = EX._collect_projection_rows(tmp_path, {"outs"}, source="render-sync", include_pregame=True)
    assert len(direct) == 1 and by_new == by_old == direct
    assert direct[0]["source"] == "fleet_sync_archive" and direct[0]["result"] == "win"


def test_maybe_sync_writes_into_render_sync_for_both_source_names(monkeypatch, tmp_path) -> None:
    from syndicate.features.mlb.native.tools.tune import export_live_pitcher_projection_dataset as EX

    calls: list[dict] = []
    monkeypatch.setattr(EX, "sync_fleet_live_lens_history", lambda **kw: calls.append(kw) or {"ok": True})
    for source in ("fleet-sync", "render-sync", "both"):
        EX._maybe_sync_fleet_history(tmp_path, source=source, sync_fleet=True, max_date="2026-06-01",
                                     fleet_base_url="http://a", fleet_cron_token="t")
    assert EX._maybe_sync_fleet_history(tmp_path, source="local", sync_fleet=True) is None
    assert [c["out_dir"] for c in calls] == [tmp_path / "render_sync"] * 3


def test_sync_failure_text_still_matches_the_daily_update_skip_rule(monkeypatch, tmp_path) -> None:
    """daily_update.py treats a fitter's stderr containing `no archived observation rows were
    found` as a skip, not an error; the reworded message must still contain it."""
    import syndicate.features.mlb.native.tools.daily_update as DU  # noqa: F401  (the rule's home)
    from syndicate.features.mlb.native.tools.eval import sync_fleet_live_lens_history as SY
    import datetime as dt

    monkeypatch.setattr(SY, "_fetch_payload", lambda **kw: {"firstObservationArchive": []})
    with pytest.raises(RuntimeError) as caught:
        SY.sync_fleet_live_lens_history(base_url="http://a", cron_token="t", start_date=dt.date(2026, 6, 1),
                                        end_date=dt.date(2026, 6, 1), out_dir=tmp_path, require_archive=True)
    assert "no archived observation rows were found" in str(caught.value)
    assert "render" not in str(caught.value).lower()


# --- the shims -------------------------------------------------------------------------------


def test_sync_shim_imports_the_old_names() -> None:
    from syndicate.features.mlb.native.tools.eval import sync_fleet_live_lens_history as NEW
    from syndicate.features.mlb.native.tools.eval.sync_render_live_lens_history import (
        LIVE_LENS_SYNC_DIRNAME,
        _env_first,
        _infer_render_base_url,
        sync_render_live_lens_history,
    )

    assert sync_render_live_lens_history is NEW.sync_fleet_live_lens_history
    assert _infer_render_base_url is NEW._infer_fleet_base_url
    assert _env_first is NEW._env_first and LIVE_LENS_SYNC_DIRNAME == "render_sync"


def test_smoke_shim_imports_the_old_helper_name() -> None:
    from syndicate.features.mlb.native.tools.smoke import smoke_fleet_frontend as NEW
    from syndicate.features.mlb.native.tools.smoke.smoke_render_frontend import _infer_render_base_url, main

    assert _infer_render_base_url is NEW._infer_fleet_base_url and main is NEW.main


@pytest.mark.parametrize("old, new", [
    ("eval/sync_render_live_lens_history.py", "eval/sync_fleet_live_lens_history.py"),
    ("smoke/smoke_render_frontend.py", "smoke/smoke_fleet_frontend.py"),
])
def test_old_script_paths_still_run_the_same_cli(old, new) -> None:
    def _help(rel: str) -> list[str]:
        done = subprocess.run([sys.executable, str(TOOLS / rel), "--help"], capture_output=True, text=True,
                              cwd=str(ROOT), timeout=120)
        assert done.returncode == 0, done.stderr[-2000:]
        # argparse wraps the usage block to the prog name's length: compare words, names masked.
        return done.stdout.replace(Path(old).name, "X").replace(Path(new).name, "X").split()

    assert _help(old) == _help(new)


# --- the ops-report readers ----------------------------------------------------------------


@pytest.mark.parametrize("module_name", [
    "syndicate.features.mlb.cards",
    "syndicate.features.mlb.live_lens_port.app_slice",
])
def test_workflow_summary_counts_both_validation_prefixes(module_name) -> None:
    module = __import__(module_name, fromlist=["_workflow_summary"])
    doc = {"errors": [
        "fleet frontend validation failed: cards: missing X-App-Commit header",
        "Render frontend validation failed: an ops report from before 2026-11-17",
        "current-day season frontend artifact build failed: boom",
    ]}
    summary = module._workflow_summary(None, doc)
    assert summary["validationErrorCount"] == 2
    assert summary["errorCount"] == 1 and summary["errors"] == ["current-day season frontend artifact build failed: boom"]
