"""`#674`: NHL's per-game player log gets a scheduled writer, in the schema its readers already read.

Fixtures are recorded from the live feed on 2026-09-18: the 2025030126 box score, the
2026-05-01 score day (three finished playoff games), and web's own legacy rows for 2025030126.
Every test here fails on the pre-change code, where the module and the runner call did not exist.
"""
from __future__ import annotations

import copy
import csv
import importlib.util
import json
import sys
import types
from datetime import date
from pathlib import Path

import pytest

from syndicate.features.nhl import boxscore_log as log

REPO = Path(__file__).resolve().parents[1]
FIXTURES = REPO / "tests" / "fixtures"
BOX = json.loads((FIXTURES / "nhl_boxscore_2025030126.json").read_text(encoding="utf-8"))
SCORE = json.loads((FIXTURES / "nhl_score_2026-05-01.json").read_text(encoding="utf-8"))
LEGACY = FIXTURES / "nhl_player_game_stats_2025030126_legacy.csv"


def _legacy_rows() -> list[dict[str, str]]:
    with LEGACY.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _num(value: str) -> float | None:
    try:
        return float(value)
    except ValueError:
        return None


def _box_for(game_id: str) -> dict:
    box = copy.deepcopy(BOX)
    box["id"] = int(game_id)
    return box


def _fake_feed(days: dict[str, dict], boxes: dict[str, dict]):
    calls: list[str] = []

    def fetch(url: str):
        calls.append(url)
        if "/score/" in url:
            return days.get(url.rsplit("/", 1)[-1], {"games": []})
        game_id = url.split("/gamecenter/")[1].split("/")[0]
        return boxes.get(game_id)

    return fetch, calls


def _seed(path: Path, rows: list[dict[str, str]]) -> None:
    log.write_rows_atomic(path, [{c: r.get(c, "") for c in log.COLUMNS} for r in rows])


# --- the rows -------------------------------------------------------------------------


def test_rows_reproduce_the_legacy_file_except_the_zero_bug():
    new = {row["player_id"]: row for row in log.rows_from_boxscore(BOX)}
    old = {row["player_id"]: row for row in _legacy_rows()}
    assert set(new) == set(old) and len(new) == 40
    diffs = []
    for pid, legacy in old.items():
        for column in log.COLUMNS:
            a, b = legacy[column], new[pid][column]
            same = (_num(a) == _num(b)) if (_num(a) is not None or _num(b) is not None) else a == b
            if not same:
                diffs.append((legacy["role"], column, a, b))
    # The ONLY differences are the vendor parser's blanked zeros, now written as 0.
    assert sorted(set(diffs)) == [("goalie", "shotsAgainst", "", "0"), ("skater", "shots", "", "0")]
    assert sum(1 for d in diffs if d[1] == "shots") == 12


def test_a_zero_stays_a_zero():
    skaters = [r for r in log.rows_from_boxscore(BOX) if r["role"] == "skater"]
    assert any(r["shots"] == "0" for r in skaters)
    assert all(r["shots"] != "" for r in skaters)


def test_legacy_blanks_are_repaired_exactly():
    rows = _legacy_rows()
    blank_shots = sum(1 for r in rows if r["role"] == "skater" and r["shots"] == "")
    blank_against = sum(1 for r in rows if r["role"] == "goalie" and r["shotsAgainst"] == "")
    assert log.repair_legacy_zero_blanks(rows) == blank_shots + blank_against == 14
    assert log.repair_legacy_zero_blanks(rows) == 0          # idempotent


# --- the update ---------------------------------------------------------------------------


def test_update_adds_finished_games_keeps_history_and_reruns_as_a_no_op(tmp_path):
    path = tmp_path / "player_game_stats.csv"
    _seed(path, _legacy_rows())                               # 2025030126, dated 2026-05-01
    boxes = {gid: _box_for(gid) for gid in ("2025030116", "2025030176")}
    fetch, calls = _fake_feed({"2026-05-01": SCORE}, boxes)

    result = log.update_game_log(path, today=date(2026, 5, 2), fetch=fetch)
    assert result.games_added == ["2025030116", "2025030176"]
    assert result.games_already_present == 1                  # 2025030126 was not refetched
    assert not any("/gamecenter/2025030126/" in url for url in calls)
    assert result.rows_before == 40 and result.rows_after == 120 and result.wrote
    assert result.repaired_cells == 14
    assert result.days_scanned == ["2026-04-30", "2026-05-01", "2026-05-02"]   # newest - 1 day .. today

    again = log.update_game_log(path, today=date(2026, 5, 2), fetch=fetch)
    assert again.games_added == [] and not again.wrote and again.rows_after == 120


def test_the_offseason_gap_is_not_scanned_day_by_day(tmp_path):
    path = tmp_path / "player_game_stats.csv"
    _seed(path, _legacy_rows())                               # newest game 2026-05-01
    fetch, _ = _fake_feed({}, {})
    result = log.update_game_log(path, today=date(2026, 9, 20), fetch=fetch, lookback_days=10)
    assert result.days_scanned[0] == "2026-09-10" and result.days_scanned[-1] == "2026-09-20"


def test_unfinished_and_non_form_games_are_skipped(tmp_path):
    path = tmp_path / "player_game_stats.csv"
    day = {"games": [
        dict(SCORE["games"][1], gameState="FUT"),
        dict(SCORE["games"][2], id=2026040001, gameType=4, gameState="FINAL"),   # all-star
        dict(SCORE["games"][0], id=2026010006, gameType=1, gameState="FINAL"),   # preseason counts
    ]}
    fetch, _ = _fake_feed({"2026-09-19": day}, {"2026010006": _box_for("2026010006")})
    result = log.update_game_log(path, today=date(2026, 9, 19), fetch=fetch, lookback_days=0)
    assert result.games_added == ["2026010006"] and result.games_not_final == 1


def test_an_unreadable_box_is_named_not_written(tmp_path):
    path = tmp_path / "player_game_stats.csv"
    fetch, _ = _fake_feed({"2026-05-01": SCORE}, {})
    result = log.update_game_log(path, today=date(2026, 5, 1), fetch=fetch, lookback_days=0)
    assert result.games_added == [] and sorted(result.unreadable_boxes) == ["2025030116", "2025030126", "2025030176"]
    assert not path.exists()


# --- the scheduled entry point -----------------------------------------------------------


@pytest.fixture
def hosted(tmp_path, monkeypatch):
    from syndicate.features.shared import artifact_publisher as publisher

    data_root = tmp_path / "data"
    (data_root / "nhl_source").mkdir(parents=True)
    published: list[Path] = []
    monkeypatch.setattr(publisher, "_data_root", lambda: data_root)
    monkeypatch.setattr(publisher, "_admin_token", lambda: "token")
    monkeypatch.setattr(publisher, "_export_url", lambda pattern=None, *, since_epoch=None, exact_path=None: f"https://web/x?{exact_path}")
    monkeypatch.setattr(publisher, "publish_hot_artifact", lambda path, timeout_seconds=10: published.append(Path(path)) or True)
    monkeypatch.delenv(log.ENV_SWITCH, raising=False)
    return {"root": data_root / "nhl_source", "path": data_root / "nhl_source" / log.RELATIVE_PATH,
            "published": published, "publisher": publisher, "monkeypatch": monkeypatch}


def test_hosted_run_writes_the_readers_path_and_publishes_it(hosted):
    _seed(hosted["path"], _legacy_rows())
    fetch, _ = _fake_feed({"2026-05-01": SCORE}, {gid: _box_for(gid) for gid in ("2025030116", "2025030176")})
    status = log.refresh_hosted_game_log(hosted["root"], today=date(2026, 5, 1), fetch=fetch)
    assert status["published"] is True and hosted["published"] == [hosted["path"]]
    # The path both readers take first -- not the runner's `nhl_source/data/raw/...`.
    assert log.PUBLISHED_PATH == "nhl_source/source_artifacts/data/raw/player_game_stats.csv"
    from syndicate.features.shared.prop_evidence import common as C
    assert C.sport_roots("nhl_source")[0].parts[-2:] == ("source_artifacts", "data")


def test_a_failed_seed_pull_never_publishes_less_history(hosted):
    hosted["monkeypatch"].setattr(hosted["publisher"], "_pull_hot_artifacts_request", lambda url, token, timeout_seconds=60: (False, "HTTP 502"))
    fetch, calls = _fake_feed({"2026-05-01": SCORE}, {gid: _box_for(gid) for gid in ("2025030116",)})
    status = log.refresh_hosted_game_log(hosted["root"], today=date(2026, 5, 1), fetch=fetch)
    assert status["skipped"] == "seed_pull_failed"
    assert hosted["published"] == [] and calls == [] and not hosted["path"].exists()


def test_a_root_that_is_not_the_hosted_one_is_a_silent_skip(tmp_path, hosted):
    fetch, calls = _fake_feed({}, {})
    status = log.refresh_hosted_game_log(tmp_path / "elsewhere", fetch=fetch)
    assert status == {"published": None, "skipped": "root_mismatch"} and calls == []


def test_the_switch_turns_it_off(hosted):
    hosted["monkeypatch"].setenv(log.ENV_SWITCH, "0")
    fetch, calls = _fake_feed({}, {})
    assert log.refresh_hosted_game_log(hosted["root"], fetch=fetch)["skipped"] == f"{log.ENV_SWITCH}=0" and calls == []


# --- reachability: the scheduled runner calls it -------------------------------------------


def test_the_nhl_runner_calls_the_game_log_refresh_once_per_run(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("test_674_refresh_nhl_oddsapi", REPO / "scripts" / "refresh_nhl_oddsapi.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    fake_producer = types.ModuleType("build_nhl_artifacts")
    for name in ("build_predictions_for_date", "build_recommendations_for_date", "build_props_for_date"):
        setattr(fake_producer, name, lambda date, **kw: (tmp_path, 1))
    monkeypatch.setitem(sys.modules, "build_nhl_artifacts", fake_producer)
    import syndicate.features.nhl.sim_engine.hockeysim.ingestion as ingestion
    monkeypatch.setattr(ingestion, "collect_slate_inputs", lambda date, root=None: None)
    monkeypatch.setattr(module, "_ensure_season_inputs", lambda root: {"present": list(module._NHL_SEASON_INPUT_FILES), "missing": [], "pulled": []})
    seen: list[Path] = []
    monkeypatch.setattr(log, "refresh_hosted_game_log", lambda root, **kw: seen.append(root) or {"published": None, "skipped": "root_mismatch"})

    warnings: list[str] = []
    module._run_owned_generation(artifact_root=tmp_path, target_dates=["2026-09-19", "2026-09-20"], props_n_sims=5, warnings=warnings)
    assert seen == [tmp_path] and warnings == []

    monkeypatch.setattr(log, "refresh_hosted_game_log", lambda root, **kw: {"published": None, "error": "OSError: disk full"})
    module._run_owned_generation(artifact_root=tmp_path, target_dates=["2026-09-19"], props_n_sims=5, warnings=warnings)
    assert warnings == ["nhl game log refresh failed: OSError: disk full"]
