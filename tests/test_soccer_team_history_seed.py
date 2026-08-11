"""`#361` -- the ratings seeder covered one of `_load_team_ratings`' two disk branches.

MEASURED, and the split is the whole point. `_load_team_ratings` reads team
ratings from three different places:

    mls                                     live ASA fetch, nothing on disk
    eredivisie/primeira_liga/championship/  <league>/history/matches_*.csv
      belgian_pro_league
    epl/la_liga/bundesliga/serie_a/ligue_1  <league>/team_history/teams_*.csv

refresh-worker is a plain script with no Flask app, so it never runs
`bootstrap_data_root`'s broad sync -- `SYNDICATE_BOOTSTRAP_ON_START=1` is set on
that service and is inert there. It relies on narrow per-kind seeders instead:
`#145` added `players`, `#170` added `api/schedule`, and a third added `history`.

Nothing seeded `team_history`. So on 2026-08-11 the four goals-based leagues
started writing and la_liga did not -- 44 launches, 0 writes, exit 1 in ~10s from
`SystemExit("no team history under ...")`, with no error in any log because a
clean exit is not a crash. It read as a per-LEAGUE data problem for most of a
session when it was a per-BRANCH one.

THIS IS NOT ONLY A LA_LIGA FIX. epl, bundesliga, serie_a and ligue_1 take the
same Understat branch and open 08-21/08-22/08-28 -- outside the 7-day sim horizon
on the day this was found, so all four would have failed identically on entering
it. la_liga was simply the first to arrive.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]

# Which league takes which branch -- mirrors build_soccer_artifacts._load_team_ratings.
_UNDERSTAT = ("epl", "la_liga", "bundesliga", "serie_a", "ligue_1")
_GOALS_BASED = ("eredivisie", "primeira_liga", "championship", "belgian_pro_league")


def _load_worker_module():
    spec = importlib.util.spec_from_file_location(
        "rw_seed_under_test", _REPO / "scripts" / "run_refresh_worker.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["rw_seed_under_test"] = module
    spec.loader.exec_module(module)
    return module


def _seed_repo(tmp_path: Path) -> Path:
    """A git-checkout-shaped tree carrying both ratings inputs."""
    repo_soccer = tmp_path / "repo" / "data" / "soccer_source"
    for league in _UNDERSTAT:
        d = repo_soccer / league / "team_history"
        d.mkdir(parents=True, exist_ok=True)
        (d / "teams_2025.csv").write_text("team,rating\nGetafe,1.2\n", encoding="utf-8")
    for league in _GOALS_BASED:
        d = repo_soccer / league / "history"
        d.mkdir(parents=True, exist_ok=True)
        (d / "matches_2025.csv").write_text("home,away,hg,ag\nA,B,1,0\n", encoding="utf-8")
    # MLS is legitimately absent from BOTH and must stay that way.
    (repo_soccer / "mls" / "api").mkdir(parents=True, exist_ok=True)
    return repo_soccer


def _run_seeders(monkeypatch, tmp_path):
    module = _load_worker_module()
    _seed_repo(tmp_path)
    data_root = tmp_path / "runtime"
    data_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path / "repo", raising=False)
    monkeypatch.setattr(module, "_refresh_state_store", lambda: {"data_root": lambda: data_root}, raising=False)
    module._bootstrap_soccer_history_seed_files()
    return data_root


def test_the_understat_branch_is_seeded(monkeypatch, tmp_path):
    data_root = _run_seeders(monkeypatch, tmp_path)
    for league in _UNDERSTAT:
        landed = sorted((data_root / "soccer_source" / league / "team_history").glob("teams_*.csv"))
        assert landed, (
            f"{league} takes the team_history branch and got no seed -- "
            "this is the exact gap that gave la_liga 44 launches and 0 writes"
        )


def test_the_goals_based_branch_is_still_seeded(monkeypatch, tmp_path):
    # The half that already worked. Breaking it would trade one outage for another.
    data_root = _run_seeders(monkeypatch, tmp_path)
    for league in _GOALS_BASED:
        landed = sorted((data_root / "soccer_source" / league / "history").glob("*.csv"))
        assert landed, f"{league} lost its match-history seed"


def test_mls_is_left_alone(monkeypatch, tmp_path):
    # MLS sources ratings live from ASA and has neither directory in git. Creating
    # one for it would be inventing an empty input on the branch that works.
    data_root = _run_seeders(monkeypatch, tmp_path)
    assert not (data_root / "soccer_source" / "mls" / "team_history").exists()
    assert not (data_root / "soccer_source" / "mls" / "history").exists()


def test_an_existing_runtime_file_is_never_overwritten(monkeypatch, tmp_path):
    # The seeder's safety property: it only fills a directory with NO matching
    # files, so it can never replace what the live pipeline has fetched. The
    # runtime copy is the fresher one by definition.
    module = _load_worker_module()
    _seed_repo(tmp_path)
    data_root = tmp_path / "runtime"
    live = data_root / "soccer_source" / "la_liga" / "team_history"
    live.mkdir(parents=True, exist_ok=True)
    (live / "teams_2025.csv").write_text("LIVE DATA", encoding="utf-8")
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path / "repo", raising=False)
    monkeypatch.setattr(module, "_refresh_state_store", lambda: {"data_root": lambda: data_root}, raising=False)
    module._bootstrap_soccer_history_seed_files()
    assert (live / "teams_2025.csv").read_text(encoding="utf-8") == "LIVE DATA"


def test_the_seeder_is_actually_called_at_boot():
    # `#361` is the third instance of this family and the second time a fix
    # existed but did not run for some input. Assert the wiring, not just the
    # function -- a seeder nothing invokes is indistinguishable from no seeder.
    source = (_REPO / "scripts" / "run_refresh_worker.py").read_text(encoding="utf-8")
    assert "_bootstrap_soccer_history_seed_files()" in source
    assert 'relative_subdir="team_history"' in source
