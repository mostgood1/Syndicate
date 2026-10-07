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
  * statcast player FEATURES -> rebuilt per date from the raw pitch files with
    game_date <= D-1 (`build_statcast_player_feature_set.build_feature_set`, called
    in-process: its CLI always overwrites the checkout's player_features_2026.json),
    and injected into build_roster's per-season cache. The vendor tree's own
    player_features_2026.json is FULL-SEASON; the first rebuild read it (a leak).
    The prior-season lookup (2025) has no file in production and falls back to
    player_features_latest.json, i.e. the CURRENT as-of file; mirrored here.
  * statcast quality map: no file exists in production either -> empty.
  * the other statcast artifacts (arsenal leaderboards, batted ball, conditional
    mix, pitch splits) are full-season files -> OFF. The data root points at an
    empty dir, and statcast_cache is None.
  * stamina: production builds pitchers through the PROFILE-CACHE HIT path, which
    re-applies `_apply_statcast_pitch_count_stamina_adjustment` (-4..+6 pitches).
    The cache-miss path this script takes never does, so it is applied after the
    feature application (measured: without it the rebuilt starters went 15.51
    outs against 16.16 stored, the fidelity gate's failure).
  * BvP: production's forward tuning already runs it OFF.
  * lineups / probables: the STORED pregame snapshot files for D.
  * bullpen availability: empty (no feed_live before 06-14 on the fleet).
  * injuries: none (injuries_raw exists only for 05-29).
  * a fresh StatsAPI cache per run, so no later response is reused.

SOURCE MODE `--source statsapi` (lane mlb-statsapi-asof-rebuild) rebuilds dates whose stored
inputs are gone (2026-07-13..09-29 lived on Render). Instead of lineups.json / probables.json /
the stored sim record it uses: the StatsAPI schedule (games, teams, probable starters), an as-of
lineup PROJECTION from earlier games (scripts/mlb_asof_lineup_projection.py, option B -- passed
as projected ids with confirmed empty, as production mostly ran), and production's own
`fetch_game_context` + umpire shrink 0.75 for park / weather / umpire. It writes a synthetic
sim record per game in production's field layout so the replay tools run unchanged.

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


def install_asof_statcast(raw_root: Path, date: str, season: int, counters: Counter) -> None:
    """Point build_roster's statcast loaders at features built from pitches < D."""
    from sim_engine.data import build_roster as br
    from tools.datasets.build_statcast_player_feature_set import build_feature_set

    feats = build_feature_set(raw_root=raw_root, season=season, start_date=dt.date(season, 2, 1),
                              end_date=dt.date.fromisoformat(_prev_day(date)),
                              min_pitches_pitcher=450, min_pitches_batter=450,
                              min_pitches_pitch_type=60, min_bip_ev=25)
    counters["statcast_pitchers"] = len(feats.get("pitchers") or {})
    br._STATCAST_FEATURES_CACHE_BY_SEASON.clear()
    br._STATCAST_FEATURES_CACHE_BY_SEASON.update({season: feats, season - 1: feats})
    br._STATCAST_QUALITY_CACHE_BY_SEASON.clear()
    br._STATCAST_QUALITY_CACHE_BY_SEASON.update({season: {}, season - 1: {}})
    if not getattr(br, "_asof_stamina_wrapped", False):
        orig = br._apply_statcast_features_to_pitcher

        def wrapped(prof, season_):
            applied = orig(prof, season_)
            if applied and br._apply_statcast_pitch_count_stamina_adjustment(prof):
                counters["stamina_adjusted"] += 1
            return applied

        br._apply_statcast_features_to_pitcher = wrapped
        br._asof_stamina_wrapped = True


UMPIRE_SHRINK = 0.75  # production's --umpire-shrink default (tools/daily_update.py)


def _context_obj(weather, park, umpire) -> dict:
    """Production's sim-record layout for the context (tools/daily_update.py, roster_snap)."""
    out = {}
    if weather is not None:
        wm = weather.multipliers()
        out["weather"] = {"source": weather.source, "condition": weather.condition, "temperature_f": weather.temperature_f,
                          "wind_speed_mph": weather.wind_speed_mph, "wind_direction": weather.wind_direction,
                          "wind_raw": weather.wind_raw, "is_dome": weather.is_dome,
                          "multipliers": {"hr_mult": wm.hr_mult, "inplay_hit_mult": wm.inplay_hit_mult, "xb_share_mult": wm.xb_share_mult}}
    if park is not None:
        pm = park.multipliers()
        out["park"] = {"source": park.source, "venue_id": park.venue_id, "venue_name": park.venue_name,
                       "roof_type": park.roof_type, "roof_status": park.roof_status, "left_line": park.left_line,
                       "center": park.center, "right_line": park.right_line,
                       "multipliers": {"hr_mult": pm.hr_mult, "inplay_hit_mult": pm.inplay_hit_mult, "xb_share_mult": pm.xb_share_mult}}
    if umpire is not None:
        old = float(getattr(umpire, "called_strike_mult", 1.0) or 1.0)
        umpire.called_strike_mult = float(1.0 + UMPIRE_SHRINK * (old - 1.0))
        out["umpire"] = {"source": umpire.source, "home_plate_umpire_id": umpire.home_plate_umpire_id,
                         "home_plate_umpire_name": getattr(umpire, "home_plate_umpire_name", None),
                         "called_strike_mult": umpire.called_strike_mult,
                         "multipliers": {"called_strike_mult": umpire.multipliers().called_strike_mult}}
    return out


class StatsApiSource:
    """Games / probables / projected lineups / context for a date from StatsAPI only."""

    PLAYED = ("Final", "Completed Early", "Game Over")

    def __init__(self, cache: Path, season: int, last_date: str):
        import mlb_asof_lineup_projection as lp

        self.lp = lp
        self.http = lp.Http(cache)
        self.games = lp.season_games(self.http, f"{season}-03-01", last_date)
        self.hands = lp.pitch_hands(self.http, [g[f"{s}_probable"] for g in self.games for s in ("away", "home")])
        self.history = lp.team_history(self.games, self.hands)

    def games_for(self, out_root: Path, date: str, client, counters: Counter) -> list[dict]:
        from sim_engine.data.statsapi import fetch_game_context

        out = []
        sim_dir = out_root / "daily" / "sims" / date
        sim_dir.mkdir(parents=True, exist_ok=True)
        todays = sorted((g for g in self.games if g["date"] == date), key=lambda g: (g["game_pk"], g["game_number"]))
        for i, g in enumerate(todays):
            if g["status"] not in self.PLAYED:
                counters[f"skipped_status:{g['status']}"] += 1
                continue
            if not (g["away_probable"] and g["home_probable"]):
                counters["skipped_no_probable"] += 1
                continue
            proj = {}
            for side, opp in (("away", "home"), ("home", "away")):
                roster = self.lp.active_roster(self.http, g[f"{side}_team_id"], date)
                proj[side] = self.lp.project(self.history[g[f"{side}_team_id"]], date,
                                             self.hands.get(g[f"{opp}_probable"]), roster)
                counters["projected_short"] += int(len(proj[side]) < 9)
            weather, park, umpire = fetch_game_context(client, g["game_pk"])
            rec = {"date": date, "game_pk": g["game_pk"], "source": "statsapi_asof_rebuild",
                   "schedule": {"game_number": g["game_number"]},
                   "away": {"team_id": g["away_team_id"], "name": g["away_name"], "abbreviation": g["away_abbr"]},
                   "home": {"team_id": g["home_team_id"], "name": g["home_name"], "abbreviation": g["home_abbr"]},
                   "starters": {"away": g["away_probable"], "home": g["home_probable"]},
                   "lineups_projected": proj, **_context_obj(weather, park, umpire)}
            path = sim_dir / f"sim_{i}_{g['away_abbr']}_at_{g['home_abbr']}_pk{g['game_pk']}_g{g['game_number']}.json"
            path.write_text(json.dumps(rec, indent=1), encoding="utf-8")
            out.append({"game_pk": g["game_pk"], "sim_path": path, "rec": rec,
                        "away_lineup": [], "home_lineup": [],
                        "away_projected": proj["away"], "home_projected": proj["home"],
                        "away_prob": g["away_probable"], "home_prob": g["home_probable"]})
        counters["statsapi_games"] += len(out)
        return out


def build_date(data_dir: Path, out_root: Path, date: str, season: int, counters: Counter,
               raw_root: Path | None = None, games: list[dict] | None = None,
               shared_cache: Path | None = None) -> int:
    from sim_engine.data.build_roster import build_team_roster
    from sim_engine.data.roster_artifact import write_game_roster_artifact
    from sim_engine.models import Team

    if raw_root is not None:
        install_asof_statcast(raw_root, date, season, counters)
    # A SHARED cache is safe across dates: the date-bounded client rewrites every
    # current-season request BEFORE it reaches the cache (byDateRange endDate=D-1 is part of
    # the key), and gameLog responses are cached whole and filtered < D after the read.
    cache = shared_cache if shared_cache is not None else Path(tempfile.mkdtemp(prefix=f"asof_cache_{date}_"))
    client = make_client(date, season, cache, counters)
    written = 0
    for i, g in enumerate(games if games is not None else games_for(data_dir, date)):
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
        if Path(g["sim_path"]).resolve() != dst.resolve():
            shutil.copyfile(g["sim_path"], dst)
        written += 1
    if shared_cache is None:
        shutil.rmtree(cache, ignore_errors=True)
    return written


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data-root", required=True, help="fleet MLB data dir (daily/snapshots, daily/sims)")
    ap.add_argument("--out-root", required=True)
    ap.add_argument("--dates", nargs="+", required=True)
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--source", choices=["stored", "statsapi"], default="stored",
                    help="stored = the fleet's lineups/probables/sim records; statsapi = schedule + as-of lineup projection + live-feed context")
    ap.add_argument("--statsapi-cache", default="~/mlb_statsapi_asof_cache")
    ap.add_argument("--shared-cache", default="",
                    help="persistent StatsAPI cache shared across dates (default: a fresh cache per date)")
    ap.add_argument("--statcast-raw-root", default="",
                    help="statcast/raw_pitches dir; builds as-of features per date (required for fidelity)")
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
    shared = Path(os.path.expanduser(args.shared_cache)) if args.shared_cache else None
    if shared is not None:
        shared.mkdir(parents=True, exist_ok=True)
    source = None
    if args.source == "statsapi":
        sys.path.insert(0, str(REPO / "scripts"))
        source = StatsApiSource(Path(os.path.expanduser(args.statsapi_cache)), args.season, max(args.dates))
    for d in sorted(set(args.dates)):
        games = None
        if source is not None:
            ctx_client = make_client(d, args.season, shared or Path(tempfile.mkdtemp(prefix=f"asof_ctx_{d}_")), counters)
            games = source.games_for(out_root, d, ctx_client, counters)
        report[d] = build_date(data_dir, out_root, d, args.season, counters, games=games, shared_cache=shared,
                               raw_root=Path(os.path.expanduser(args.statcast_raw_root)) if args.statcast_raw_root else None)
        print(f"{d}: {report[d]} games", flush=True)
    summary = {"games_by_date": report, "counters": dict(counters), "as_of_rule": "every current-season stat bounded at D-1 or prior season; statcast features as of D-1" if args.statcast_raw_root else "every current-season stat bounded at D-1 or prior season; statcast off"}
    (out_root / "asof_build_report.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
