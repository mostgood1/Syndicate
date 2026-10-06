"""Leak-free AS-OF rebuild of MLB sim inputs (TeamRoster artifacts) for past dates.

Lane `mlb-asof-roster-rebuild`. The combined calibration needs validation data the
fitting never touched. 05-30..06-14 have stored sims, lineups and probables but no
`roster_objs`. The production builder (`build_roster.build_team_roster`) cannot
rebuild them as-of, because nearly every stat input is season-to-date AT REQUEST
TIME. This script calls the SAME builder with a client that bounds every
current-season stat request at the day before, and turns off the layers that
cannot be bounded. Production code is untouched.

How each input is bounded (each verified against the live API on 2026-10-06, not assumed):
  * season hitting/pitching (stats=season) -> stats=byDateRange, endDate=D-1.
    Probed: Judge 2026 PA 135 through 04-30, 261 through 05-31, 285 season.
  * gameLog -> only rows dated < D are kept (recency blend, venue history).
  * statSplits (platoon, home/away) -> PRIOR season. The API IGNORES startDate/endDate
    on statSplits (81/204 either way), and byDateRange ignores sitCodes.
  * pitchArsenal -> PRIOR season. It returns nothing when given a date range.
  * any OTHER current-season stat type -> refused (LeakRefused). Fail closed:
    nothing unknown passes.
  * statcast-derived artifacts (features, quality, arsenal leaderboards, batted ball,
    conditional mix, pitch splits) are full-season files -> OFF. The data root
    points at an empty dir, and statcast_cache is None.
  * BvP: production's forward tuning already runs it OFF.
  * lineups / probables: the STORED pregame snapshot files for D.
  * bullpen availability: empty (no feed_live before 06-14 on the fleet).
  * injuries: none (injuries_raw exists only for 05-29).
  * a fresh StatsAPI cache per run, so no later response is reused.

Two known gaps from the production inputs: no statcast layers, and no bullpen
availability. The FIDELITY CHECK exists to measure them. Rebuild dates that DO
have real roster_objs (06-15..06-20), replay both, and compare.

  python scripts/mlb_asof_roster_build.py --data-root <fleet mlb data> --out-root <scratch> \\
      --dates 2026-06-15 2026-06-16 ...
writes <out-root>/daily/snapshots/<D>/roster_objs/roster_obj_*.json and copies the
stored sims for D to <out-root>/daily/sims/<D>/ (context only), so
mlb_starter_length_replay.py / mlb_strikeout_decomposition.py run on it with
--data-root <out-root>.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import sys
import tempfile
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
VENDOR = REPO / "vendor" / "mlb_bettingv2"


class LeakRefused(RuntimeError):
    pass


def _prev_day(date: str) -> str:
    return (dt.date.fromisoformat(date) - dt.timedelta(days=1)).isoformat()


def make_client(as_of: str, season: int, cache_dir: Path, counters: Counter):
    from sim_engine.data.disk_cache import DiskCache  # noqa: WPS433 (vendor import)
    from sim_engine.data.statsapi import StatsApiClient

    end = _prev_day(as_of)

    class DateBoundedClient(StatsApiClient):
        def get(self, path, params=None):  # noqa: D401
            p = dict(params or {})
            if re.fullmatch(r"/people/\d+/stats", str(path)):
                kind = str(p.get("stats") or "")
                try:
                    yr = int(p.get("season") or 0)
                except (TypeError, ValueError):
                    yr = 0
                if yr == season:
                    if kind == "season":
                        p.update({"stats": "byDateRange", "startDate": f"{season}-02-01", "endDate": end})
                        data = super().get(path, p)
                        for grp in data.get("stats") or []:
                            grp["splits"] = (grp.get("splits") or [])[:1]
                        counters["rewrite_season_to_byDateRange"] += 1
                        return data
                    if kind == "gameLog":
                        data = super().get(path, p)
                        for grp in data.get("stats") or []:
                            grp["splits"] = [s for s in (grp.get("splits") or []) if str(s.get("date") or "") < as_of]
                        counters["filter_gameLog_lt_D"] += 1
                        return data
                    if kind in ("statSplits", "pitchArsenal"):
                        p["season"] = season - 1
                        counters[f"prior_season_{kind}"] += 1
                        return super().get(path, p)
                    raise LeakRefused(f"current-season stat type {kind!r} has no as-of bound: {path} {p}")
            elif "season" in p and str(p.get("season")) == str(season) and "/stats" in str(path):
                raise LeakRefused(f"current-season stats request outside /people/<id>/stats: {path} {p}")
            return super().get(path, p)

    return DateBoundedClient(cache=DiskCache(root_dir=cache_dir, default_ttl_seconds=10 ** 9),
                             cache_ttl_seconds=10 ** 9)


def _load(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def games_for(data_dir: Path, date: str) -> list[dict]:
    snap = data_dir / "daily" / "snapshots" / date
    lu = _load(snap / "lineups.json") if (snap / "lineups.json").exists() else {"games": []}
    pr = _load(snap / "probables.json") if (snap / "probables.json").exists() else {"games": []}
    probs = {int(g["game_pk"]): g for g in pr.get("games") or [] if g.get("game_pk")}
    sims = {}
    for f in sorted((data_dir / "daily" / "sims_pregame" / date).glob("sim_*.json")) + \
            sorted((data_dir / "daily" / "sims" / date).glob("sim_*.json")):
        m = re.search(r"pk(\d+)", f.name)
        if m and int(m.group(1)) not in sims:
            sims[int(m.group(1))] = f
    out = []
    for g in lu.get("games") or []:
        pk = int(g.get("game_pk") or 0)
        if not pk or pk not in sims:
            continue
        rec = _load(sims[pk])
        pb = probs.get(pk, {})
        out.append({"game_pk": pk, "sim_path": sims[pk], "rec": rec,
                    "away_lineup": g.get("away_confirmed_ids") or [], "home_lineup": g.get("home_confirmed_ids") or [],
                    "away_projected": g.get("away_projected_ids") or [], "home_projected": g.get("home_projected_ids") or [],
                    "away_prob": pb.get("away_probable_id") or (rec.get("starters") or {}).get("away"),
                    "home_prob": pb.get("home_probable_id") or (rec.get("starters") or {}).get("home")})
    return out


def build_date(data_dir: Path, out_root: Path, date: str, season: int, counters: Counter) -> int:
    from sim_engine.data.build_roster import build_team_roster
    from sim_engine.data.roster_artifact import write_game_roster_artifact
    from sim_engine.models import Team

    cache = Path(tempfile.mkdtemp(prefix=f"asof_cache_{date}_"))
    client = make_client(date, season, cache, counters)
    written = 0
    for i, g in enumerate(games_for(data_dir, date)):
        rec = g["rec"]
        teams = {}
        for side in ("away", "home"):
            t = rec.get(side) or {}
            teams[side] = Team(team_id=int(t.get("team_id")), name=str(t.get("name") or ""),
                               abbreviation=str(t.get("abbreviation") or ""))
        try:
            rosters = {}
            for side in ("away", "home"):
                prob = g[f"{side}_prob"]
                rosters[side] = build_team_roster(
                    client, teams[side], season, as_of_date=date,
                    probable_pitcher_id=int(prob) if prob else None,
                    statcast_cache=None,
                    confirmed_lineup_ids=[int(x) for x in g[f"{side}_lineup"]] or None,
                    projected_lineup_ids=[int(x) for x in g[f"{side}_projected"]] or None,
                    pitcher_availability={}, roster_type="active", fallback_roster_types=["40Man"],
                    injured_player_ids=None, roster_entries=None, fast_mode=False,
                    profile_cache=None, use_profile_cache=False,
                )
        except LeakRefused:
            raise
        except Exception as exc:  # a failed game is counted, never silently dropped
            counters[f"build_failed:{type(exc).__name__}"] += 1
            continue
        gn = int((rec.get("schedule") or {}).get("game_number") or 1)
        name = f"roster_obj_{i}_{teams['away'].abbreviation}_at_{teams['home'].abbreviation}_pk{g['game_pk']}_g{gn}.json"
        write_game_roster_artifact(out_root / "daily" / "snapshots" / date / "roster_objs" / name,
                                   away_roster=rosters["away"], home_roster=rosters["home"],
                                   meta={"asof_rebuild": True, "as_of_end": _prev_day(date), "lane": "mlb-asof-roster-rebuild"})
        dst = out_root / "daily" / "sims" / date / g["sim_path"].name
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(g["sim_path"], dst)
        written += 1
    shutil.rmtree(cache, ignore_errors=True)
    return written


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data-root", required=True, help="fleet MLB data dir (daily/snapshots, daily/sims)")
    ap.add_argument("--out-root", required=True)
    ap.add_argument("--dates", nargs="+", required=True)
    ap.add_argument("--season", type=int, default=2026)
    args = ap.parse_args(argv)
    out_root = Path(os.path.expanduser(args.out_root)).resolve()
    # Statcast-derived artifacts are full-season: point every artifact root at an EMPTY
    # dir BEFORE the vendor modules import (their data roots are module-level).
    empty = out_root / "_empty_artifact_root"
    empty.mkdir(parents=True, exist_ok=True)
    for k in ("MLB_BETTING_DATA_ROOT", "SYNDICATE_DATA_ROOT"):
        os.environ[k] = str(empty)
    if str(VENDOR) not in sys.path:
        sys.path.insert(0, str(VENDOR))
    data_dir = Path(os.path.expanduser(args.data_root)).resolve()
    counters = Counter()
    report = {}
    for d in sorted(set(args.dates)):
        report[d] = build_date(data_dir, out_root, d, args.season, counters)
        print(f"{d}: {report[d]} games", flush=True)
    summary = {"games_by_date": report, "counters": dict(counters), "as_of_rule": "every current-season stat bounded at D-1 or prior season; statcast off"}
    (out_root / "asof_build_report.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
