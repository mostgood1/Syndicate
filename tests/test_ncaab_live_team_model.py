from __future__ import annotations

import csv
import dataclasses
import datetime as dt
import importlib.util
from pathlib import Path

import pytest

from syndicate.features.ncaab import live_team_model as tm

_SPEC = importlib.util.spec_from_file_location(
    "build_ncaab_team_ratings", Path(__file__).resolve().parents[1] / "scripts" / "build_ncaab_team_ratings.py"
)
producer = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(producer)

FIELDS = ("team", "espn_id", "adj_off", "adj_def", "adj_em", "tempo", "raw_off", "raw_def", "games", "prior_weight", "calibration_k", "season", "as_of", "source")


def _write(directory: Path, season: int, as_of: str, rows):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"team_ratings_{season}_asof_{as_of.replace('-', '')}.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        for tid, off, deff, tempo, games in rows:
            writer.writerow({"team": f"T{tid}", "espn_id": tid, "adj_off": off, "adj_def": deff, "adj_em": off - deff, "tempo": tempo, "games": games, "prior_weight": 0.2, "season": season, "as_of": as_of})
    return path


TEAMS = [("1", 115.0, 95.0, 70.0, 10), ("2", 100.0, 110.0, 64.0, 10), ("3", 105.0, 105.0, 67.0, 10)]


def test_constants_match_the_producer():
    assert tm.HOME_POINTS == producer.HOME_POINTS
    assert tm.PRIOR_REGRESSION == producer.PRIOR_REGRESSION


def test_espn_season_convention():
    assert tm.espn_season_for(dt.date(2025, 11, 4)) == 2026
    assert tm.espn_season_for(dt.date(2026, 3, 19)) == 2026


def test_table_strictly_before_the_game_date(tmp_path):
    _write(tmp_path, 2026, "2026-01-10", TEAMS)
    _write(tmp_path, 2026, "2026-01-15", [(t, o + 5, d, tp, g) for t, o, d, tp, g in TEAMS])
    table = tm.table_for_game(dt.date(2026, 1, 15), dirs=[tmp_path])
    assert table.as_of == dt.date(2026, 1, 10), "a table dated the game day may contain the game"
    assert tm.table_for_game(dt.date(2026, 1, 16), dirs=[tmp_path]).as_of == dt.date(2026, 1, 15)


def test_unrated_team_is_refused_by_name_not_defaulted(tmp_path):
    _write(tmp_path, 2026, "2026-01-10", TEAMS)
    result = tm.prior_for_game(dt.date(2026, 1, 20), "1", "999", neutral=False, dirs=[tmp_path])
    assert isinstance(result, tm.NcaabPriorRefusal)
    assert result.reason == "team_unrated" and "999" in result.detail


def test_no_table_is_refused(tmp_path):
    result = tm.prior_for_game(dt.date(2026, 1, 20), "1", "2", neutral=False, dirs=[tmp_path])
    assert isinstance(result, tm.NcaabPriorRefusal) and result.reason == "no_ratings_table"


def test_prior_shape_and_home_edge(tmp_path):
    _write(tmp_path, 2026, "2026-01-10", TEAMS)
    home = tm.prior_for_game(dt.date(2026, 1, 20), "1", "2", neutral=False, dirs=[tmp_path])
    neutral = tm.prior_for_game(dt.date(2026, 1, 20), "1", "2", neutral=True, dirs=[tmp_path])
    assert isinstance(home, tm.NcaabGamePrior)
    assert home.total == pytest.approx(neutral.total), "home edge moves the margin, not the total"
    assert home.home_margin - neutral.home_margin == pytest.approx(tm.HOME_POINTS)
    league_tempo = (70 + 64 + 67) / 3
    assert home.possessions == pytest.approx(70 * 64 / league_tempo)
    league_off = (115 + 100 + 105) / 3
    assert neutral.home_ppp == pytest.approx(115 * 110 / league_off / 100)
    assert neutral.home_margin > 0
    # swapping sides mirrors the neutral margin
    swapped = tm.prior_for_game(dt.date(2026, 1, 20), "2", "1", neutral=True, dirs=[tmp_path])
    assert swapped.home_margin == pytest.approx(-neutral.home_margin)


def test_preseason_uses_last_season_regressed(tmp_path):
    _write(tmp_path, 2025, "2025-04-08", TEAMS)
    table = tm.table_for_game(dt.date(2025, 11, 4), dirs=[tmp_path])
    assert table.prior_season_fallback and table.season == 2025
    league_off = (115 + 100 + 105) / 3
    assert table.teams["1"].adj_off == pytest.approx(league_off + 0.7 * (115 - league_off))
    # once this season has a table, it wins
    _write(tmp_path, 2026, "2025-11-05", TEAMS)
    assert tm.table_for_game(dt.date(2025, 11, 6), dirs=[tmp_path]).prior_season_fallback is False


def test_computed_walk_forward_table_from_producer_output():
    rows = []
    for gid, (h, a, hp, ap) in enumerate([("1", "2", 80, 60), ("2", "3", 70, 72), ("3", "1", 65, 75), ("1", "3", 78, 70)]):
        for me, opp, mp, op, site in ((h, a, hp, ap, "home"), (a, h, ap, hp, "away")):
            rows.append({"game_id": str(gid), "team_id": me, "opp_id": opp, "site": site, "pts": mp, "opp_pts": op, "poss": 68.0})
    ratings = producer.compute_ratings(rows, {"1": "A", "2": "B", "3": "C"})
    table = tm.table_from_rows(({**r, "espn_id": tid} for tid, r in ratings.items()), season=2026, as_of=dt.date(2026, 1, 1), source="computed:test")
    prior = tm.game_prior(table, "1", "2", neutral=True)
    assert isinstance(prior, tm.NcaabGamePrior) and prior.home_margin > 0


def test_every_prior_field_is_populated(tmp_path):
    """Engine-standard section 1 in miniature: enumerate dataclasses.fields(), never names."""
    _write(tmp_path, 2026, "2026-01-10", TEAMS)
    prior = tm.prior_for_game(dt.date(2026, 1, 20), "1", "3", neutral=False, dirs=[tmp_path])
    for f in dataclasses.fields(prior):
        assert getattr(prior, f.name) is not None, f.name


_CSPEC = importlib.util.spec_from_file_location(
    "ncaab_live_input_checklist", Path(__file__).resolve().parents[1] / "scripts" / "ncaab_live_input_checklist.py"
)
checklist = importlib.util.module_from_spec(_CSPEC)
_CSPEC.loader.exec_module(checklist)


def _registry(tmp_path, ids):
    path = tmp_path / "registry.csv"
    path.write_text("espn_id,school\n" + "".join(f"{i},T{i}\n" for i in ids), encoding="utf-8")
    return path


def test_checklist_passes_a_full_table(tmp_path, monkeypatch):
    _write(tmp_path / "p", 2026, "2026-01-10", TEAMS)
    monkeypatch.setattr(tm, "ratings_dirs", lambda: [tmp_path / "p"])
    monkeypatch.setattr(checklist, "REGISTRY", _registry(tmp_path, ["1", "2", "3"]))
    code, report = checklist.run(dt.date(2026, 1, 20))
    assert code == 0 and report["verdict"] == "PASS"
    consumed = {r["field"] for r in report["fields"] if r["consumed"]}
    assert {"adj_off", "adj_def", "tempo"} <= consumed


def test_checklist_fails_on_thin_coverage(tmp_path, monkeypatch):
    _write(tmp_path / "p", 2026, "2026-01-10", TEAMS)
    monkeypatch.setattr(tm, "ratings_dirs", lambda: [tmp_path / "p"])
    monkeypatch.setattr(checklist, "REGISTRY", _registry(tmp_path, [str(i) for i in range(1, 11)]))
    code, report = checklist.run(dt.date(2026, 1, 20))
    assert code == 1 and report["d1_coverage"] == pytest.approx(0.3)


def test_checklist_fails_when_a_consumed_field_is_unfed(tmp_path, monkeypatch):
    """Reachability of the alarm itself: a zero tempo is unusable and tempo is consumed."""
    _write(tmp_path / "p", 2026, "2026-01-10", TEAMS)
    monkeypatch.setattr(tm, "ratings_dirs", lambda: [tmp_path / "p"])
    monkeypatch.setattr(checklist, "REGISTRY", _registry(tmp_path, ["1", "2", "3"]))
    real = tm.table_from_rows

    def zero_tempo(rows, **kw):
        table = real(rows, **kw)
        teams = {k: dataclasses.replace(v, tempo=float("nan")) for k, v in table.teams.items()}
        return dataclasses.replace(table, teams=teams)

    monkeypatch.setattr(tm, "table_from_rows", zero_tempo)
    code, report = checklist.run(dt.date(2026, 1, 20))
    assert code == 1 and report["failed_fields"] == ["tempo"]


def test_checklist_no_table_is_exit_2(tmp_path, monkeypatch):
    monkeypatch.setattr(tm, "ratings_dirs", lambda: [tmp_path / "empty"])
    code, report = checklist.run(dt.date(2026, 1, 20))
    assert code == 2 and report["verdict"] == "NO_TABLE"
