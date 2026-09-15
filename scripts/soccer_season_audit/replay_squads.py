# -*- coding: utf-8 -*-
"""H4 replay for lane `soccer-player-substrate`: does the NEW squad selection list the
players who actually shot?

For every archived fixture, rebuild each side's player list the way the builder now
would: this checkout's `build_soccer_artifacts._load_player_rows` over PRODUCTION
`players_*.csv` (plus the ESPN leagues' current-season files, fetched with
`fetch_soccer_history_local.py --kind players --seasons 2026` into
`$SOCCER_AUDIT_CACHE/espn_players/<league>/`), bound by
`loaders.build_soccer_player_features` with the new aliases. Score it against ESPN
box scores exactly as the season audit scored production's published lists.

LEAKAGE, stated up front: the player files are as of the day they were pulled, so
an early fixture is scored against a file that already knows later debutants. The
headline is each club's LATEST archived match, where file and fixture are days
apart; the all-matches figure is an upper bound.

The roster rescue reads the git-shipped roster seed, as production does
(`SYNDICATE_REPO_ROOT` must be a checkout WITH `data/`).

Inputs in the cache: `prod/players/` (production player files),
`prod/recs/` + `outcomes.json` (see `common.py`), `espn_players/`.
"""
import collections
import contextlib
import csv
import glob
import importlib.util
import io
import os
import re
import shutil
import sys
from pathlib import Path

# THIS CHECKOUT'S CODE, IMPORTED BEFORE `common`. `common` puts
# `SYNDICATE_REPO_ROOT` first on sys.path, and that root is often a DIFFERENT
# checkout chosen for its `data/` -- one whose `team_names` predates the aliases
# being measured. Importing the builder and loaders first pins every `syndicate.*`
# module to this checkout, whatever `common` inserts afterwards.
CHECKOUT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(CHECKOUT))
spec = importlib.util.spec_from_file_location("bsa_replay", CHECKOUT / "scripts" / "build_soccer_artifacts.py")
bsa = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bsa)
from syndicate.features.soccer.features.loaders import build_soccer_player_features  # noqa: E402

from common import LEAGUES, PRIMARY, S, load_outcomes, load_recs  # noqa: E402
from decompose_squads import appeared  # noqa: E402
from namejoin_diag import strict_match  # noqa: E402

ESPN = {"championship", "eredivisie", "primeira_liga", "belgian_pro_league"}


def build_root(tmp: Path) -> Path:
    root = tmp / "soccer_source"
    for f in glob.glob(os.path.join(S, "prod", "players", "soccer_source_*_players_players_*.csv")):
        m = re.search(r"soccer_source_(.+)_players_players_(\d{4})\.csv$", os.path.basename(f))
        target = root / m.group(1) / "players"
        target.mkdir(parents=True, exist_ok=True)
        shutil.copy(f, target / f"players_{m.group(2)}.csv")
    for league in ESPN:
        src = Path(S) / "espn_players" / league / "players_2026.csv"
        if src.exists():
            (root / league / "players").mkdir(parents=True, exist_ok=True)
            shutil.copy(src, root / league / "players" / "players_2026.csv")
    return root


def seed_roster_rows(league, season):
    path = Path(PRIMARY) / "data" / "soccer_source" / league / "api" / "rosters" / f"rosters_{season}.csv"
    if not path.exists():
        return ()
    with path.open(encoding="utf-8") as handle:
        return tuple(csv.DictReader(handle))


def main():
    recs, outc = load_recs(), load_outcomes()
    tmp = Path(S) / "replay_root"
    shutil.rmtree(tmp, ignore_errors=True)
    root = build_root(tmp)
    bsa.roster_rows = seed_roster_rows
    rows_by_league = {}
    for league in LEAGUES:
        with contextlib.redirect_stdout(io.StringIO()):
            rows_by_league[league] = bsa._load_player_rows(league, root)
        print(f"{league:20s} audit {dict(bsa._PLAYER_LOAD_AUDIT)}")

    latest = {}
    for (lg, mid), m in recs.items():
        if (lg, mid) in outc:
            for club in (m["home"], m["away"]):
                latest[(lg, club)] = max(latest.get((lg, club), ""), m["date"])

    stat = collections.defaultdict(collections.Counter)
    for (lg, mid), m in recs.items():
        o = outc.get((lg, mid))
        if not o:
            continue
        with contextlib.redirect_stdout(io.StringIO()):
            feats = build_soccer_player_features(rows_by_league[lg], league=lg, date=m["date"], fixture_teams=[m["home"], m["away"]])
        for side, club in (("home", m["home"]), ("away", m["away"])):
            roster = [q for q in o["players"] if q["side"] == side]
            shots = sum((q["shots"] or 0) for q in roster if appeared(q))
            new_preds = [{"player_name": f.player_name, "side": side} for f in feats if f.team == club]
            old_preds = [p for p in m["players"] if p.get("side") == side]
            scopes = ("all", "latest") if m["date"] == latest.get((lg, club)) else ("all",)
            for tag, preds in (("old", old_preds), ("new", new_preds)):
                mapping = strict_match(preds, roster)
                bound = set(mapping.values())
                covered = sum((q["shots"] or 0) for j, q in enumerate(roster) if appeared(q) and j in bound)
                for scope in scopes:
                    stat[(lg, scope)][f"{tag}_covered"] += covered
                    stat[(lg, scope)][f"{tag}_listed"] += len(preds)
                    stat[(lg, scope)][f"{tag}_phantom"] += len(preds) - len(mapping)
                    stat[(lg, scope)][f"{tag}_empty"] += 0 if preds else 1
            for scope in scopes:
                stat[(lg, scope)]["shots"] += shots
                stat[(lg, scope)]["sides"] += 1

    print("\nCOVERAGE (real shots by a listed player) and PHANTOMS (listed, not in the matchday squad), OLD published vs NEW replay")
    print(f"{'league':20s} {'scope':6s} {'sides':>5s} {'cov old':>8s} {'cov new':>8s} {'empty old':>9s} {'empty new':>9s} {'phantom/side old':>16s} {'new':>6s}")
    for lg in LEAGUES:
        for scope in ("latest", "all"):
            c = stat[(lg, scope)]
            if not c["sides"]:
                continue
            t = max(c["shots"], 1)
            print(f"{lg:20s} {scope:6s} {c['sides']:5d} {100 * c['old_covered'] / t:7.1f}% {100 * c['new_covered'] / t:7.1f}% "
                  f"{c['old_empty']:9d} {c['new_empty']:9d} {c['old_phantom'] / c['sides']:16.1f} {c['new_phantom'] / c['sides']:6.1f}")


if __name__ == "__main__":
    main()
