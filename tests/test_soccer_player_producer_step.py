"""The soccer player rosters get a PRODUCER -- and the two guards that assumed they never would.

Every `players_*.csv` on disk was a hand-run, git-committed seed. `--kind
players` existed in `fetch_soccer_history_local.py` and nothing ever called it,
so the newest European roster was `players_2025.csv` -- the COMPLETED 2025-26
season. Every summer-2026 signing and both promoted clubs were structurally
absent from the sim, and `3355d621`'s minutes-shrinkage was estimating rates for
a season that had already finished.

Half the tests here are not about the new step at all. They pin the two
DOWNSTREAM assumptions that only become false once rosters actually refresh:

  * `build_soccer_artifacts` refused to filter departed players while the newest
    file was "thin", measured as ROW COUNT against half the previous season.
    `3355d621` lowered the ingestion floor from 180 minutes to 1, which roughly
    TRIPLES the row count of a barely-started season (100 -> 364 on real EPL
    fixtures) -- so it now sails over the 220-row floor a 440-row previous
    season implies, in about matchweek 3, and `_drop_departed_players` deletes
    players who simply have not appeared yet.

    The guard is now MINUTES **and** ROWS, tripping on either, because the two
    detect different failures and only the season-progress one was disarmed.
    Row count still catches a truncated write or a half-failed scrape, about
    which minutes say nothing. Replacing rather than adding cost nine of ten
    players in an existing test -- see
    `test_a_ROW_THIN_but_MINUTES_RICH_file_also_refuses`.

  * The de-duplicator kept the NEWEST season's row per player. Correct while
    every file was a completed season; wrong the moment a current-season file
    lands, because a returning player's 2,000-minute rate is then replaced by a
    90-minute rate shrunk almost entirely to the positional prior.

Both were harmless precisely because no producer existed. Shipping the producer
alone would have armed them.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import sys
import time
from pathlib import Path

import pandas as pd
import pytest

_REPO = Path(__file__).resolve().parents[1]


def _load(name: str, relpath: str):
    spec = importlib.util.spec_from_file_location(name, _REPO / relpath)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def refresh():
    return _load("refresh_odds_sources_players_under_test", "scripts/refresh_odds_sources.py")


@pytest.fixture(scope="module")
def artifacts():
    return _load("build_soccer_artifacts_players_under_test", "scripts/build_soccer_artifacts.py")


def _roster(root: Path, league: str, season: int, *, age_days: float | None) -> Path:
    """Write a roster file and backdate it. `age_days=None` means don't create it."""
    target = root / league / "players" / f"players_{season}.csv"
    if age_days is None:
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("league,season,player_id,player_name,minutes\n", encoding="utf-8")
    stamp = time.time() - age_days * 86400.0
    os.utime(target, (stamp, stamp))
    return target


# ---------------------------------------------------------------------------
# The step itself
# ---------------------------------------------------------------------------


def test_an_absent_roster_produces_a_fetch_step(refresh, tmp_path):
    """The state production is actually in: no producer ever ran."""
    step = refresh._soccer_players_step("epl", tmp_path, sys.executable)
    assert step is not None
    assert step.name == "soccer_epl_players"


def test_a_FRESH_roster_is_a_NO_OP(refresh, tmp_path):
    """The property that keeps this off the per-tick network path.

    Without it, every refresh tick would re-fetch six leagues' rosters and
    rewrite the files every projection is built from, mid-slate.
    """
    season = int(refresh.soccer_default_season("epl"))
    _roster(tmp_path, "epl", season, age_days=0.0)
    assert refresh._soccer_players_step("epl", tmp_path, sys.executable) is None


def test_a_STALE_roster_is_refetched(refresh, tmp_path):
    """`off != on`. Together with the test above this is the whole gate: the
    same league, the same path, opposite answers from mtime alone."""
    season = int(refresh.soccer_default_season("epl"))
    _roster(tmp_path, "epl", season, age_days=30.0)
    step = refresh._soccer_players_step("epl", tmp_path, sys.executable)
    assert step is not None


def test_the_gate_is_MTIME_not_EXISTENCE(refresh, tmp_path):
    """`_soccer_history_step` returns None whenever the file is PRESENT. That is
    right for a completed-season ratings file and wrong for a current-season
    roster, which starts nearly empty and fills week by week -- "already there"
    is not "already correct". This is the difference between the two, asserted
    on a file that exists in both cases.
    """
    season = int(refresh.soccer_default_season("epl"))
    _roster(tmp_path, "epl", season, age_days=refresh._SOCCER_PLAYER_REFRESH_DAYS + 1.0)
    assert refresh._soccer_players_step("epl", tmp_path, sys.executable) is not None
    _roster(tmp_path, "epl", season, age_days=refresh._SOCCER_PLAYER_REFRESH_DAYS - 1.0)
    assert refresh._soccer_players_step("epl", tmp_path, sys.executable) is None


def test_MLS_gets_a_step_even_though_the_history_step_refuses_it(refresh, tmp_path):
    """The reason this is a SIBLING function rather than a branch inside
    `_soccer_history_step`, which hard-returns None for MLS."""
    assert refresh._soccer_history_step("mls", tmp_path, sys.executable) is None
    assert refresh._soccer_players_step("mls", tmp_path, sys.executable) is not None


@pytest.mark.parametrize(
    "league", ["eredivisie", "primeira_liga", "championship", "belgian_pro_league"]
)
def test_leagues_the_fetcher_CANNOT_serve_get_no_step(refresh, tmp_path, league):
    """`fetch_players` raises SystemExit for these without `--espn-date-windows`.
    A step for them would not be a fetch, it would be a FAILING step on every
    tick -- noisier than the gap it was meant to close, and it would mask the
    real one.
    """
    assert refresh._soccer_players_step(league, tmp_path, sys.executable) is None


def test_it_requests_the_CURRENT_season_and_only_that(refresh, tmp_path):
    """Refetching past seasons would rewrite the very files the de-duplicator
    reads to find each player's biggest sample."""
    step = refresh._soccer_players_step("epl", tmp_path, sys.executable)
    command = list(step.command)
    seasons = command[command.index("--seasons") + 1]
    assert seasons == str(int(refresh.soccer_default_season("epl")))
    assert "," not in seasons


def test_the_command_is_the_players_kind_and_writes_under_the_runtime_root(refresh, tmp_path):
    """The fetcher defaults `--out-dir` to the REPO tree, which on Render is not
    the root the sim reads. Passing it explicitly is load-bearing."""
    step = refresh._soccer_players_step("la_liga", tmp_path, sys.executable)
    command = list(step.command)
    assert command[command.index("--kind") + 1] == "players"
    assert command[command.index("--league") + 1] == "la_liga"
    out_dir = Path(command[command.index("--out-dir") + 1])
    assert out_dir == tmp_path / "la_liga" / "players"


def test_it_runs_in_BOTH_phases(refresh, tmp_path):
    """The autorun launches with `--phase live`. A pregame-only prerequisite
    would never execute on the path that needs it -- the same defect the history
    step's comment records."""
    step = refresh._soccer_players_step("epl", tmp_path, sys.executable)
    assert set(step.phases) == {"pregame", "live"}


def test_an_unreadable_path_is_not_treated_as_stale(refresh, tmp_path, monkeypatch):
    """A transient IO error must not become a weekly network call. Absent is a
    real answer (`FileNotFoundError`); unreadable is not an answer at all."""

    def _boom(self):
        raise PermissionError("nope")

    monkeypatch.setattr(Path, "stat", _boom)
    assert refresh._soccer_players_step("epl", tmp_path, sys.executable) is None


# ---------------------------------------------------------------------------
# Wiring: presence is not reachability
# ---------------------------------------------------------------------------


def test_the_step_is_REACHED_and_lands_before_the_steps_that_read_the_roster(
    refresh, tmp_path, monkeypatch
):
    """A producer that runs AFTER the sim is a producer that takes a day to
    matter. Asserts against the real plan builder, not the function alone --
    a step nothing calls is inert no matter how well it is tested.
    """
    monkeypatch.setattr(refresh, "_local_source_bundle_root", lambda sport: tmp_path)
    args = argparse.Namespace(
        date="2026-09-04", soccer_leagues="", phase="pregame", sports="soccer"
    )
    steps = refresh._build_soccer_steps(args)
    names = [step.name for step in steps]

    players = [i for i, n in enumerate(names) if n.endswith("_players")]
    assert players, f"no players step reached the plan: {names}"

    consumers = [i for i, n in enumerate(names) if n.endswith(("_schedule", "_artifacts"))]
    assert consumers, names
    assert max(players) < min(consumers), (
        "the roster producer must precede every step that reads the roster: %s" % names
    )


# ---------------------------------------------------------------------------
# The guard the producer would have armed
# ---------------------------------------------------------------------------


def _frame(rows: list[tuple[str, float]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "league": "epl",
                "season": 2026,
                "player_id": pid,
                "player_name": pid,
                "team": "A",
                "position": "M",
                "minutes": minutes,
                "shots_per90": 1.0,
            }
            for pid, minutes in rows
        ]
    )


def test_a_364_row_EARLY_SEASON_file_still_refuses_to_define_the_squad(artifacts):
    """THE REGRESSION, in the exact numbers that produced it.

    EPL `players_2025.csv` is 440 rows, so the old row-count floor was 220.
    `3355d621` lowered the ingestion floor from 180 minutes to 1, which turns
    the same early-season fixtures from 100 rows into 364 -- clearing 220 while
    barely any football has been played. The guard would have gone quiet exactly
    when the producer started giving it something to be quiet about.
    """
    latest = _frame([(f"p{i}", 30.0) for i in range(364)])
    assert len(latest) > 0.5 * 440, "the old row-count floor would have PASSED this"
    assert artifacts._busiest_player_minutes(latest) < artifacts._MIN_LATEST_SEASON_MINUTES


def test_a_real_mid_season_file_is_TRUSTED(artifacts):
    """`off != on`: the guard has to say yes to a genuine mid-season file, or it
    is not a guard, it is an off switch."""
    latest = _frame([(f"p{i}", 900.0) for i in range(300)])
    assert artifacts._busiest_player_minutes(latest) >= artifacts._MIN_LATEST_SEASON_MINUTES


def test_UNKNOWN_minutes_REFUSE_rather_than_permit(artifacts):
    """A guard whose unknown case falls through to its permissive branch is not
    a guard. A missing or unparseable column must read as "too early", which
    skips the filtering, not as "go ahead and delete players".
    """
    assert artifacts._busiest_player_minutes(pd.DataFrame([{"player_id": "a"}])) == 0.0
    assert artifacts._busiest_player_minutes(_frame([])) == 0.0
    unparseable = pd.DataFrame([{"player_id": "a", "minutes": "not a number"}])
    assert artifacts._busiest_player_minutes(unparseable) == 0.0


def test_the_guard_actually_reads_that_helper(artifacts, tmp_path, capsys):
    """End to end through `_load_player_rows`: two seasons on disk, the newest
    one barely started. Every player must survive."""
    players_dir = tmp_path / "epl" / "players"
    players_dir.mkdir(parents=True)
    _frame([(f"p{i}", 2000.0) for i in range(440)]).to_csv(
        players_dir / "players_2025.csv", index=False
    )
    _frame([(f"p{i}", 30.0) for i in range(364)]).to_csv(
        players_dir / "players_2026.csv", index=False
    )
    rows = artifacts._load_player_rows("epl", tmp_path)
    assert len({str(r["player_id"]) for r in rows}) == 440, (
        "an early-season file must not be allowed to delete 76 players"
    )
    assert "SOCCER_LATEST_SEASON_FILE_THIN" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# The de-duplicator the producer would have armed
# ---------------------------------------------------------------------------


def test_dedupe_keeps_the_BIGGER_SAMPLE_not_the_newer_season(artifacts, tmp_path):
    """A returning player's 2,000-minute rate must not be replaced by a
    90-minute one shrunk almost entirely to the positional prior."""
    players_dir = tmp_path / "epl" / "players"
    players_dir.mkdir(parents=True)
    old = _frame([(f"p{i}", 2000.0) for i in range(500)])
    old["shots_per90"] = 3.0
    old.to_csv(players_dir / "players_2025.csv", index=False)
    new = _frame([(f"p{i}", 90.0) for i in range(500)])
    new["shots_per90"] = 0.4  # shrunk toward the prior
    new.to_csv(players_dir / "players_2026.csv", index=False)

    rows = artifacts._load_player_rows("epl", tmp_path)
    kept = {str(r["player_id"]): r for r in rows}
    assert len(kept) == 500
    assert float(kept["p0"]["minutes"]) == 2000.0
    assert float(kept["p0"]["shots_per90"]) == 3.0


def test_dedupe_STILL_dedupes(artifacts, tmp_path):
    """Backward compatibility. 293 of ~600 EPL players were duplicated before
    this de-duplicator existed, and each duplicate dilutes every teammate's
    allocated share -- so 'keeps one row per player' is the load-bearing half
    and must survive the change of sort key.
    """
    players_dir = tmp_path / "epl" / "players"
    players_dir.mkdir(parents=True)
    _frame([(f"p{i}", 1800.0) for i in range(50)]).to_csv(
        players_dir / "players_2024.csv", index=False
    )
    _frame([(f"p{i}", 1900.0) for i in range(50)]).to_csv(
        players_dir / "players_2025.csv", index=False
    )
    rows = artifacts._load_player_rows("epl", tmp_path)
    assert len(rows) == 50


def test_a_row_with_UNREADABLE_minutes_loses_to_a_real_sample(artifacts, tmp_path):
    """An unreadable sample is not a better one."""
    players_dir = tmp_path / "epl" / "players"
    players_dir.mkdir(parents=True)
    good = _frame([("p0", 1500.0)])
    good.to_csv(players_dir / "players_2024.csv", index=False)
    bad = _frame([("p0", 0.0)])
    bad["minutes"] = "?"
    bad.to_csv(players_dir / "players_2025.csv", index=False)
    rows = artifacts._load_player_rows("epl", tmp_path)
    assert len(rows) == 1
    assert str(rows[0]["minutes"]) == "1500.0"


# ---------------------------------------------------------------------------
# MLS: the floor that was never local
# ---------------------------------------------------------------------------


def test_the_MLS_minutes_floor_is_no_longer_applied_SERVER_SIDE():
    """`3355d621` lowered the local threshold and MLS did not move, because ASA
    applies `minimum_minutes` as a REQUEST PARAMETER -- thin rows never arrived
    to be shrunk. Safe to lower only because `6ec3c99d` put
    `_shrink_toward_prior` in the ASA normaliser; without that this would
    publish raw 90-shots/90 rates into a share that normalises to ~1.0.
    """
    import inspect

    from syndicate.features.soccer.ingestion import player_history as ph

    assert ph._ASA_MINIMUM_MINUTES == 1
    fetch_default = inspect.signature(ph.fetch_asa_mls_players).parameters[
        "minimum_minutes"
    ].default
    assert fetch_default == 1
    norm_default = inspect.signature(ph.normalize_asa_players).parameters[
        "minimum_minutes"
    ].default
    assert norm_default == 1.0
    assert "_shrink_toward_prior" in inspect.getsource(ph.normalize_asa_players), (
        "lowering the ASA floor without shrinkage in that path is a "
        "fabricated-rate bug, not a roster fix"
    )


def test_a_ROW_THIN_but_MINUTES_RICH_file_also_refuses(artifacts, tmp_path, capsys):
    """THE MISTAKE I MADE WHILE WRITING THIS, pinned so it cannot come back.

    My first version REPLACED the row-count test with the minutes test. But the
    two detect different failures and only one of them was disarmed:

        minutes -- "barely any of the season has been played"
        rows    -- "this file is missing players it should have": a truncated
                   write, a partial fetch, a scrape that half-failed

    Minutes says nothing about the second. A single complete-looking 900-minute
    row satisfies a minutes floor while nine of ten players are missing -- which
    is exactly what `test_a_thin_new_season_file_disables_filtering_and_says_so`
    caught. The row test was INSUFFICIENT, not wrong, so it is kept alongside
    rather than replaced.
    """
    players_dir = tmp_path / "epl" / "players"
    players_dir.mkdir(parents=True)
    _frame([(f"p{i}", 900.0) for i in range(10)]).to_csv(
        players_dir / "players_2025.csv", index=False
    )
    # One row, but a FULL season of minutes: clears any minutes floor outright.
    _frame([("p0", 900.0)]).to_csv(players_dir / "players_2026.csv", index=False)

    assert artifacts._busiest_player_minutes(
        pd.read_csv(players_dir / "players_2026.csv")
    ) >= artifacts._MIN_LATEST_SEASON_MINUTES, "a minutes-only guard PASSES this file"

    rows = artifacts._load_player_rows("epl", tmp_path)
    assert len(rows) == 10, "a truncated roster must not be allowed to delete 9 players"
    out = capsys.readouterr().out
    assert "too_few=True" in out and "too_early=False" in out, out


def test_the_two_conditions_are_reported_SEPARATELY(artifacts, tmp_path, capsys):
    """They call for different responses: `too_early` resolves itself as the
    season proceeds; `too_few` means a file failed to write and will not."""
    players_dir = tmp_path / "epl" / "players"
    players_dir.mkdir(parents=True)
    _frame([(f"p{i}", 2000.0) for i in range(440)]).to_csv(
        players_dir / "players_2025.csv", index=False
    )
    _frame([(f"p{i}", 30.0) for i in range(364)]).to_csv(
        players_dir / "players_2026.csv", index=False
    )
    artifacts._load_player_rows("epl", tmp_path)
    out = capsys.readouterr().out
    # The disarmed case: plenty of rows, almost no football played.
    assert "too_early=True" in out and "too_few=False" in out, out


# ---------------------------------------------------------------------------
# A weekly writer makes an old latent hazard live
# ---------------------------------------------------------------------------


def test_an_empty_fetch_CANNOT_overwrite_a_good_roster(tmp_path):
    """`_write_csv` used to publish whatever it was handed, including nothing.

    `pd.DataFrame([]).to_csv(index=False)` is a bare newline -- 3 bytes, no
    header -- and `pd.read_csv` raises `EmptyDataError: No columns to parse from
    file` on it (both measured). So one rate-limited or shape-changed Understat
    response would replace a good roster with a file that parses as nothing, and
    take out that league's whole artifact build every cycle until someone
    noticed.

    Harmless while these CSVs were hand-run committed seeds. The producer step
    turns it into a WEEKLY opportunity against a file that already holds good
    data -- so the guard belongs in the same change as the producer.
    """
    fetch = _load("fetch_soccer_history_local_under_test", "scripts/fetch_soccer_history_local.py")
    target = tmp_path / "players_2026.csv"
    target.write_text("league,player_id,minutes\nepl,p1,900\n", encoding="utf-8")
    before = target.read_bytes()

    with pytest.raises(SystemExit) as excinfo:
        fetch._write_csv([], target)

    assert "REFUSING" in str(excinfo.value)
    assert target.read_bytes() == before, "the previous roster must survive"


def test_a_non_empty_fetch_still_writes(tmp_path):
    """`off != on`: the refusal must not be a write-disable."""
    fetch = _load("fetch_soccer_history_local_under_test2", "scripts/fetch_soccer_history_local.py")
    target = tmp_path / "nested" / "players_2026.csv"
    fetch._write_csv([{"league": "epl", "player_id": "p1", "minutes": 900}], target)
    written = pd.read_csv(target)
    assert len(written) == 1 and written.iloc[0]["player_id"] == "p1"


# ---------------------------------------------------------------------------
# The ESPN leagues call the column something else
# ---------------------------------------------------------------------------


def _espn_frame(rows: list[tuple[str, float]]) -> pd.DataFrame:
    """ESPN rows say `minutes_played`; Understat and ASA say `minutes`."""
    frame = _frame(rows)
    return frame.rename(columns={"minutes": "minutes_played"})


def test_the_guard_reads_the_ESPN_column_too(artifacts):
    """Both guards read `minutes` only, which made them BLIND on exactly the
    four leagues ESPN serves (eredivisie, primeira_liga, championship,
    belgian_pro_league).

    Measured on real eredivisie data: the guard read `latest_max_minutes=0`
    against a true 450.0 -- `too_early` stuck True forever, which is safe but
    permanently inert.
    """
    espn = _espn_frame([(f"p{i}", 450.0) for i in range(200)])
    assert artifacts._busiest_player_minutes(espn) == 450.0


def test_dedupe_keeps_the_bigger_sample_on_ESPN_rows(artifacts, tmp_path):
    """The worse half. With the column unreadable, "keep the most minutes"
    silently degraded to "keep the newest season" -- on real eredivisie data,
    161 of 161 dual-season players resolved to the thin 2026 file and mean
    minutes fell 1648.1 -> 258.4. That is exactly the regression this
    de-duplicator was changed to prevent, re-armed for four leagues.
    """
    players_dir = tmp_path / "eredivisie" / "players"
    players_dir.mkdir(parents=True)
    old = _espn_frame([(f"p{i}", 2000.0) for i in range(300)])
    old["shots_per90"] = 3.0
    old.to_csv(players_dir / "players_2025.csv", index=False)
    new = _espn_frame([(f"p{i}", 90.0) for i in range(300)])
    new["shots_per90"] = 0.4
    new.to_csv(players_dir / "players_2026.csv", index=False)

    rows = artifacts._load_player_rows("eredivisie", tmp_path)
    kept = {str(r["player_id"]): r for r in rows}
    assert len(kept) == 300
    assert float(kept["p0"]["minutes_played"]) == 2000.0
    assert float(kept["p0"]["shots_per90"]) == 3.0


def test_a_frame_with_NEITHER_column_still_refuses(artifacts):
    """Unknown must not become permissive just because a second name exists."""
    assert artifacts._busiest_player_minutes(pd.DataFrame([{"player_id": "a"}])) == 0.0
