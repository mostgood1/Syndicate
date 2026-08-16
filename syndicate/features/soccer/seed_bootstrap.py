"""Copy soccer's git-committed seed files onto whichever worker disk needs them.

`#145` (players), `#170` (schedule) and `#361` (history/team_history) were all
the same bug, fixed three times in `scripts/run_refresh_worker.py`: soccer's
per-league inputs are committed to git, the sim reads them from the RUNTIME
disk, and nothing copied them across.

**It has now happened a fourth time, on a service the earlier fixes never
covered.** Measured 2026-08-15:

  - `render.yaml` gives `refresh-worker` the startCommand
    `python scripts/run_refresh_worker.py`, which bootstraps all four families;
    `live-odds-worker` runs `python scripts/run_live_odds_refresh_worker.py`,
    which bootstrapped nothing. They are separate services with separate disks
    (`syndicate-data-refresh-worker` / `syndicate-data-live-odds-worker`).
  - **live-odds-worker is the service that actually builds soccer artifacts.**
    A `scripts/build_soccer_artifacts.py` process appears in its
    `ALL_PROCESS_MEMORY` payload at 02:25:48Z and 02:26:48Z, matching the
    `generated_at` stamps on all four published `recommendations_2026-08-14.json`
    files; refresh-worker shows zero `build_soccer_artifacts` in that window.
  - refresh-worker's disk is fully seeded and idle for this purpose:
    `SOCCER_SEED_CENSUS subdir=players seeded=[] already_present=[all 10
    leagues]` at 02:11:05Z.
  - Result: every published file carried `player_props: 0`, so **107 of the 123
    soccer rows on the board (every player prop) had no projection**, while the
    committed CSVs were real and correct the whole time (eredivisie 459 rows,
    championship 461, belgian_pro_league 426, primeira_liga 389).

So the logic lives here rather than in one service's entrypoint, and any
entrypoint that runs the soccer sim calls `bootstrap_soccer_seed_files`.

`scripts/run_refresh_worker.py` deliberately still carries its own copy and is
NOT changed by this: that file belongs to a live incident lane (`#435`, the
refresh-worker OOM), and its version already works. Converging the two is a
follow-up that needs coordination with that session, not a drive-by edit to a
sick service's entrypoint.

WHY ALL FOUR FAMILIES, when only `players` is known-missing: the copy is
idempotent by construction -- it only ever writes into a per-league
subdirectory that has NO matching file yet, so it can never touch or replace
anything the pipeline has already written. Seeding a family that is already
present costs one `glob` and prints `already_present`. Seeding only the family
we happened to measure is how this bug got fixed three times and came back a
fourth.
"""

from __future__ import annotations

import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

# (subdirectory under <league>/, glob, label used in the bootstrap log line).
# Mirrors `run_refresh_worker.py`'s four calls exactly; see that file for the
# per-family incident history, especially why `history` and `team_history` are
# TWO branches of `_load_team_ratings` and seeding one leaves the other broken.
SEED_FAMILIES: tuple[tuple[str, str, str], ...] = (
    ("players", "players_*.csv", "PLAYER"),
    ("api/schedule", "schedule_*.json", "SCHEDULE"),
    ("history", "*.csv", "HISTORY"),
    ("team_history", "teams_*.csv", "TEAM_HISTORY"),
)


def _data_root() -> Path:
    from syndicate.features.shared.refresh_state_store import data_root

    return data_root()


def bootstrap_soccer_seed_family(
    *, relative_subdir: str, glob_pattern: str, log_prefix: str
) -> list[str]:
    """Copy one seed family onto the runtime disk. Returns the leagues seeded.

    Deliberately narrow and provably safe: a league is skipped entirely if its
    destination directory already has ANY file matching the glob, so this can
    never overwrite pipeline output. That is why it does not reuse
    `bootstrap_data_root.py`'s broad copy-if-content-differs sync.
    """
    try:
        data_root = _data_root()
    except Exception as exc:
        print(
            f"[{log_prefix}] SOCCER_SEED_BOOTSTRAP_SKIPPED subdir={relative_subdir} "
            f"error={type(exc).__name__}: {exc}",
            flush=True,
        )
        return []

    source_root = REPO_ROOT / "data" / "soccer_source"
    if not source_root.is_dir():
        # `#362`: copying nothing because everything is present and copying
        # nothing because the source tree is not THERE are opposite facts, and
        # they used to render identically as a healthy boot.
        print(
            f"[{log_prefix}] SOCCER_SEED_CENSUS subdir={relative_subdir} "
            f"source_root_missing={source_root}",
            flush=True,
        )
        return []

    seeded_leagues: list[str] = []
    already_present: list[str] = []
    no_source: list[str] = []
    for league_dir in sorted(source_root.iterdir()):
        if not league_dir.is_dir():
            continue
        source_dir = league_dir / relative_subdir
        source_files = sorted(source_dir.glob(glob_pattern)) if source_dir.is_dir() else []
        if not source_files:
            no_source.append(league_dir.name)
            continue
        dest_dir = data_root / "soccer_source" / league_dir.name / relative_subdir
        existing = list(dest_dir.glob(glob_pattern)) if dest_dir.is_dir() else []
        if existing:
            already_present.append(league_dir.name)
            continue
        dest_dir.mkdir(parents=True, exist_ok=True)
        for src_file in source_files:
            shutil.copy2(src_file, dest_dir / src_file.name)
        seeded_leagues.append(league_dir.name)

    # UNCONDITIONAL, on every boot. A seeder that speaks only when it copies
    # cannot answer "is this league's input on the disk?", which is the only
    # question anyone ever asks it -- and on a worker, which serves no HTTP and
    # whose disk is unreadable from anywhere else, answering it otherwise costs
    # a deploy. This line is what made the live-odds-worker gap findable.
    print(
        f"[{log_prefix}] SOCCER_SEED_CENSUS subdir={relative_subdir} "
        f"seeded={sorted(seeded_leagues)} already_present={sorted(already_present)} "
        f"no_source_in_checkout={sorted(no_source)}",
        flush=True,
    )
    return seeded_leagues


def bootstrap_soccer_seed_files(*, log_prefix: str) -> dict[str, list[str]]:
    """Seed every family the soccer sim reads. Safe to call on any entrypoint."""
    seeded: dict[str, list[str]] = {}
    for relative_subdir, glob_pattern, label in SEED_FAMILIES:
        leagues = bootstrap_soccer_seed_family(
            relative_subdir=relative_subdir, glob_pattern=glob_pattern, log_prefix=log_prefix
        )
        seeded[relative_subdir] = leagues
        if leagues:
            print(
                f"[{log_prefix}] SOCCER_{label}_SEED_BOOTSTRAPPED leagues={leagues}",
                flush=True,
            )
    return seeded
