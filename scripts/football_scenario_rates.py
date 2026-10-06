"""Real-vs-sim GAME SCENARIO rates for the shared smartsim2 engine (NFL + NCAAF).

Lane `football-scenario-calibration` (2026-10-06), Phase 1. Pre-registration:
`.syndicate/findings_2026-10-06_football_scenario_calibration.md` -- the scenario
ids (S1..S12), buckets and the flag rule are fixed THERE, before any reading.

ONE COUNTER FUNCTION FOR BOTH SIDES. Real play-by-play and simulated games are
first turned into the same normalised drive record (`Drive`), and every metric
is computed from those records by `add_drive` / `add_game`. A rate can only
differ between the two sides because the drives differ, never because the two
sides were counted by different code.

  real NFL   nflverse pbp (`tracking/nflverse/pbp/pbp_<season>.csv`), drives =
             `fixed_drive`, REG season only.
  real NCAAF CFBD drives (`historical_truth/drives_<season>.json.gz`) + plays
             (`plays_<season>_wkNN.json.gz`) for the in-drive 4th-down / FG / red
             zone rows; FBS-vs-FBS, weeks 3-15 (the as-of blend's weeks).
  sim        PRODUCTION'S OWN `build_projection` (300 seeds, production env,
             shipped profile) through its `segment_accumulator` seam -- every
             seed's full `SmartSim2SimulationOutput` is read, nothing in the
             engine is modified to measure it.

THE INTERSECTION IS SCORED. Real metrics are computed only over games the sim
side also simulated (joined on game id), and the report prints per-family
coverage and the count the result rests on (CLAUDE.md coverage rule).

Usage:
  py -3 scripts/football_scenario_rates.py sim   --sport nfl   --seasons 2023,2024 --workers 6
  py -3 scripts/football_scenario_rates.py real  --sport nfl   --seasons 2023,2024
  py -3 scripts/football_scenario_rates.py fetch --sport ncaaf --seasons 2024
  py -3 scripts/football_scenario_rates.py sim   --sport ncaaf --seasons 2024 --workers 6
  py -3 scripts/football_scenario_rates.py real  --sport ncaaf --seasons 2024
  py -3 scripts/football_scenario_rates.py report --sport nfl --seasons 2023,2024
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
import os
import random
import shutil
import sys
import time
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

PRIMARY = Path(r"C:\Users\tempadmin\OneDrive\Coding\Syndicate")
OUT_ROOT = Path(r"C:\tmp\football_scenarios")
QUARTER_SECONDS = 900
GARBAGE_MARGIN = {"nfl": 17, "ncaaf": 21}          # pre-registered (S2)
FLAG_POINTS = {"nfl": 0.25, "ncaaf": 0.40}         # pre-registered flag rule
NCAAF_WEEKS = range(3, 16)                          # the as-of blend's weeks
NCAAF_PROFILE_VERSION = "ncaaf-goal-line-refit-1"   # production's promoted artifact


# ---------------------------------------------------------------------------
# the normalised record both sides are reduced to
# ---------------------------------------------------------------------------

@dataclass
class Drive:
    side: str                 # 'home' | 'away' -- the OFFENSE
    q: int                    # start quarter, 5+ = overtime
    gsr: int                  # regulation game-seconds remaining at drive start
    diff: int                 # offense score minus defense score at start
    fp: int                   # yards from the offense's OWN goal line (1..99)
    result: str               # TD FG MFG PUNT TO TOD EOH SAF OPP_TD RET_TD OTHER
    pts: int                  # points the OFFENSE scored on the drive
    plays: int
    secs: int
    rz: bool                  # any scrimmage snap from the opponent 20 or closer
    prev: str                 # how the possession began: half | score | punt | turnover | other
    fourths: List[Tuple[int, int, str]] = field(default_factory=list)   # (fp, to_go, go|punt|fg)
    fgs: List[Tuple[int, bool]] = field(default_factory=list)          # (kick distance, made)
    td_pts: Optional[int] = None   # REAL only: 6 + PAT/2pt actually scored


def _prev_category(result: Optional[str]) -> str:
    if result is None:
        return "half"
    if result in ("TD", "FG", "RET_TD", "OPP_TD", "SAF"):
        return "score"
    if result == "PUNT":
        return "punt"
    if result in ("TO", "TOD", "MFG"):
        return "turnover"
    return "other"


def _fp_bucket(fp: int) -> str:
    if fp < 50:
        return "own"
    if fp < 71:
        return "opp50-30"
    return "opp29in"


def _togo_bucket(togo: int) -> str:
    return "1-2" if togo <= 2 else ("3-5" if togo <= 5 else "6+")


def _fg_bucket(dist: int) -> str:
    return "<30" if dist < 30 else ("30-39" if dist < 40 else ("40-49" if dist < 50 else "50+"))


def _state(diff: int) -> str:
    return "lead9" if diff >= 9 else ("trail9" if diff <= -9 else "close")


def add_drive(c: Dict[str, float], d: Drive, sport: str) -> None:
    """Every per-drive scenario counter. Keys are 'metric' or 'metric:bucket:part'."""
    def inc(k: str, v: float = 1.0) -> None:
        c[k] = c.get(k, 0.0) + v

    if d.q >= 5:
        inc("ot:drives")
        inc("ot:pts", d.pts)
        return
    inc("drives")
    inc(f"res:{d.result}")
    inc("pts", d.pts)
    inc("plays", d.plays)
    inc("secs", d.secs)
    if d.result == "TD" and d.td_pts is not None:      # S7, real side only
        inc("td:n")
        inc("td:pts", d.td_pts)
    # S2 garbage time
    if d.q == 4 and abs(d.diff) >= GARBAGE_MARGIN[sport]:
        s = "lead" if d.diff > 0 else "trail"
        for k, v in (("drives", 1), ("pts", d.pts), ("secs", d.secs), ("plays", d.plays)):
            inc(f"gt:{s}:{k}", v)
    # S3 pace
    h = 1 if d.q <= 2 else 2
    inc(f"pace:{_state(d.diff)}:h{h}:secs", d.secs)
    inc(f"pace:{_state(d.diff)}:h{h}:plays", d.plays)
    # S4 red zone
    if d.rz:
        inc("rz:n")
        if d.result == "TD":
            inc("rz:td")
        if d.result in ("FG", "MFG"):
            inc("rz:fga")
    # S4b field goals
    for dist, made in d.fgs:
        b = _fg_bucket(dist)
        inc(f"fg:{b}:att")
        if made:
            inc(f"fg:{b}:made")
    # S5 fourth downs
    for fp, togo, dec in d.fourths:
        b = f"{_fp_bucket(fp)}|{_togo_bucket(togo)}"
        inc(f"4th:{b}:n")
        inc(f"4th:{b}:{dec}")
    # S12 drive start field position by how the possession began
    inc(f"fp:{d.prev}:n")
    inc(f"fp:{d.prev}:sum", d.fp)


def add_team_game(c: Dict[str, float], drives: List[Drive]) -> None:
    """S1b: one per-team-game points/drive value (regulation drives)."""
    reg = [d for d in drives if d.q <= 4]
    if not reg:
        return
    x = sum(d.pts for d in reg) / len(reg)
    c["ppd_tg:n"] = c.get("ppd_tg:n", 0.0) + 1
    c["ppd_tg:sum"] = c.get("ppd_tg:sum", 0.0) + x
    c["ppd_tg:sumsq"] = c.get("ppd_tg:sumsq", 0.0) + x * x
    c["team_games"] = c.get("team_games", 0.0) + 1


def add_game(c: Dict[str, float], *, total: float, margin: float, ot: bool, h1: float,
             offense_pts: float) -> None:
    def inc(k: str, v: float) -> None:
        c[k] = c.get(k, 0.0) + v

    inc("g:n", 1)
    inc("g:total", total)
    inc("g:total_sq", total * total)
    inc("g:margin", margin)
    inc("g:margin_sq", margin * margin)
    inc("g:ot", 1.0 if ot else 0.0)
    inc("g:h1", h1)
    inc("g:nonoff", total - offense_pts)      # S11 points not scored by an offensive drive


# ---------------------------------------------------------------------------
# SIM side: SmartSim2SimulationOutput -> Drive records
# ---------------------------------------------------------------------------

_SIM_RESULT = {"touchdown": "TD", "field_goal": "FG", "missed_field_goal": "MFG", "punt": "PUNT",
               "turnover": "TO", "turnover_on_downs": "TOD", "end_of_half_stop": "EOH",
               "end_of_quarter_stop": "EOH", "safety": "SAF"}


def _v(x: Any) -> str:
    return str(getattr(x, "value", x))


def sim_drives(output: Any) -> List[Drive]:
    out: List[Drive] = []
    prev: Optional[str] = None
    prev_q = 0
    for d in output.drive_log:
        st = d["start_state"]
        q = int(st["quarter"])
        owner = st["possession_owner"]
        sh, sa = int(st["score_home"]), int(st["score_away"])
        diff = (sh - sa) if owner == "home" else (sa - sh)
        steps = d.get("steps") or []
        fourths, fgs, rz = [], [], False
        for s in steps:
            ss = s["start_state"]
            o = _v(s["outcome"])
            fp = int(ss["field_position"])
            if fp >= 80 and int(ss.get("possession_owner") == owner):
                rz = True
            if int(ss["down"]) == 4:
                dec = "punt" if o == "punt" else ("fg" if o in ("field_goal", "missed_field_goal", "field_goal_attempt") else "go")
                fourths.append((fp, int(ss["distance"]), dec))
            if o in ("field_goal", "missed_field_goal"):
                fgs.append((100 - fp + 17, o == "field_goal"))
        result = _SIM_RESULT.get(_v(d["outcome"]), "OTHER")
        # a new half resets the "how did it begin" chain, as in the real data
        p = "half" if (prev is None or (q == 3 and prev_q <= 2) or (q >= 5 and prev_q <= 4)) else _prev_category(prev)
        out.append(Drive(side=owner, q=q, gsr=_gsr(q, int(st["clock_remaining"])), diff=diff,
                         fp=int(st["field_position"]), result=result, pts=int(d.get("points_scored") or 0),
                         plays=len(steps), secs=sum(int(s.get("clock_consumed") or 0) for s in steps),
                         rz=rz, prev=p, fourths=fourths, fgs=fgs))
        prev, prev_q = result, q
    return out


def _gsr(q: int, clock: int) -> int:
    return (4 - q) * QUARTER_SECONDS + clock if q <= 4 else 0


class ScenarioAccumulator:
    """Duck-types `FootballSegmentAccumulator.add(output)`; reads, never mutates."""

    def __init__(self, sport: str) -> None:
        self.sport = sport
        self.side: Dict[str, Dict[str, float]] = {"home": {}, "away": {}}
        self.game: Dict[str, float] = {}
        self.ratings: Optional[Dict[str, float]] = None

    def add(self, output: Any) -> None:
        if self.ratings is None:
            inp = output.input_state
            self.ratings = {k: float(inp[k]) for k in ("home_offense_rating", "home_defense_rating",
                                                       "away_offense_rating", "away_defense_rating")}
        drives = sim_drives(output)
        for side in ("home", "away"):
            mine = [d for d in drives if d.side == side]
            for d in mine:
                add_drive(self.side[side], d, self.sport)
            add_team_game(self.side[side], mine)
        h, a = output.final_score["home"], output.final_score["away"]
        ql = list(output.quarter_log)
        h1 = sum(x["home_points"] + x["away_points"] for x in ql[:2])
        add_game(self.game, total=h + a, margin=h - a, ot=any(d.q >= 5 for d in drives), h1=h1,
                 offense_pts=sum(d.pts for d in drives))


# ---------------------------------------------------------------------------
# SIM workers
# ---------------------------------------------------------------------------

_W: Dict[str, Any] = {}


def _lower_priority() -> None:
    try:
        import psutil
        psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS if os.name == "nt" else 10)
    except Exception:  # noqa: BLE001
        pass


def _parse_profile_set(items: List[str]) -> Dict[str, Any]:
    """`key=value` pairs -> CalibrationProfile overrides (bools, ints, floats)."""
    out: Dict[str, Any] = {}
    for item in items or []:
        k, v = item.split("=", 1)
        lv = v.strip().lower()
        out[k.strip()] = True if lv in ("1", "true", "on") else False if lv in ("0", "false", "off") else float(v)
    return out


def _apply_profile_set(gen: Any, sport: str, overrides: Dict[str, Any]) -> None:
    """ONE field changed against production's own resolved profile, nothing else.
    NFL resolves its profile per game through `nfl_calibration_profile()`; NCAAF's
    generator reads the module constant -- both are wrapped here, in the worker."""
    if not overrides:
        return
    from dataclasses import fields as _fields, replace as _replace
    current = gen.nfl_calibration_profile() if sport == "nfl" else gen.NCAAF_CALIBRATION_PROFILE
    bad = set(overrides) - {f.name for f in _fields(current)}
    if bad:
        raise SystemExit(f"unknown profile fields {bad}")
    if sport == "nfl":
        base = gen.nfl_calibration_profile
        gen.nfl_calibration_profile = lambda: _replace(base(), **overrides)
    else:
        gen.NCAAF_CALIBRATION_PROFILE = _replace(gen.NCAAF_CALIBRATION_PROFILE, **overrides)


def _nfl_init(root: str, overrides: Dict[str, Any]) -> None:
    from scripts import backtest_nfl_lines_props as H
    H.configure_env(Path(root))          # production's measured NFL env, refuses stray knobs
    _lower_priority()
    from scripts import generate_smartsim2_nfl_projections as gen
    _apply_profile_set(gen, "nfl", overrides)
    _W.update(gen=gen, plays={}, sport="nfl")


def _nfl_plays(season: int):
    if season not in _W["plays"]:
        _W["plays"][season] = _W["gen"].load_pbp_plays(season)
    return _W["plays"][season]


def _ncaaf_init(work: str, overrides: Dict[str, Any]) -> None:
    _ncaaf_env(Path(work))
    _lower_priority()
    from syndicate.features.football.sim_engine.smartsim2 import ncaaf_calibration_profile as P
    version = (P.NCAAF_CALIBRATION_PROFILE_METADATA or {}).get("version")
    if version != NCAAF_PROFILE_VERSION:
        raise SystemExit(f"NCAAF profile resolved to {version!r}, production runs {NCAAF_PROFILE_VERSION!r}")
    from scripts import generate_smartsim2_ncaaf_projections as gen
    _apply_profile_set(gen, "ncaaf", overrides)
    _W.update(gen=gen, sport="ncaaf")


def sim_task(task: Dict[str, Any]) -> Dict[str, Any]:
    gen, sport = _W["gen"], _W["sport"]
    acc = ScenarioAccumulator(sport)
    t0 = time.time()
    if sport == "nfl":
        s = task["season"]
        proj, _ = gen.build_projection(season=s, week=task["week"], home_team=task["home"], away_team=task["away"],
                                       game_id=task["game_id"], current_plays=_nfl_plays(s),
                                       prior_plays=_nfl_plays(s - 1), seeds=task["seeds"], segment_accumulator=acc)
    else:
        proj = gen.build_projection(season=task["season"], week=task["week"], home_team=task["home"],
                                    away_team=task["away"], game_id=str(task["game_id"]), ppa_index={},
                                    rating_source=task["rating_source"], seeds=task["seeds"],
                                    sp_index=task["index"], sp_means=tuple(task["means"]), segment_accumulator=acc)
    return {"game_id": str(task["game_id"]), "season": task["season"], "week": task["week"],
            "home": task["home"], "away": task["away"], "seeds": task["seeds"],
            "margin_mean": proj.margin_mean, "total_mean": proj.total_mean,
            "margin_stdev": proj.margin_stdev, "total_stdev": proj.total_stdev,
            "home_win_rate": proj.home_win_rate, "ratings": acc.ratings,
            "c_home": acc.side["home"], "c_away": acc.side["away"], "c_game": acc.game,
            "secs": round(time.time() - t0, 1)}


# ---------------------------------------------------------------------------
# task lists (the SAME games the backtest harnesses score)
# ---------------------------------------------------------------------------

def nfl_root() -> Path:
    return PRIMARY / "data" / "nfl_source"


def nfl_tasks(seasons: List[int], seeds: int) -> List[Dict[str, Any]]:
    from scripts import backtest_nfl_lines_props as H
    sched = H.load_schedule(nfl_root())
    return [{"season": g["season_i"], "week": g["week_i"], "home": g["home_team"], "away": g["away_team"],
             "game_id": gid, "seeds": seeds}
            for gid, g in sorted(sched.items()) if g["season_i"] in seasons and g["completed"]]


def ncaaf_work() -> Path:
    return OUT_ROOT / "ncaaf_work"


def _ncaaf_env(work: Path) -> None:
    os.environ["SYNDICATE_CALIBRATION_PROFILE_DIR"] = str(work / "calib")
    os.environ["SYNDICATE_DATA_ROOT"] = str(work / "dataroot")
    os.environ["SYNDICATE_NCAAF_SOURCE_ROOT"] = str(work / "dataroot" / "ncaaf_source")
    os.environ.pop("SYNDICATE_NCAAF_DRIVE_PRIORS", None)
    os.environ.pop("SYNDICATE_NCAAF_DRIVE_PROFILE", None)
    for var in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ.setdefault(var, "1")


def ncaaf_prepare_work() -> Path:
    """A private dataroot: production's promoted profile + the local truth files (copied, read-only use)."""
    work = ncaaf_work()
    (work / "calib").mkdir(parents=True, exist_ok=True)
    src_profile = Path(r"C:\tmp\ncaaf_lpb\calib\ncaaf_profile.json")
    if not (work / "calib" / "ncaaf_profile.json").exists():
        shutil.copy2(src_profile, work / "calib" / "ncaaf_profile.json")
    ht = work / "dataroot" / "ncaaf_source" / "historical_truth"
    ht.mkdir(parents=True, exist_ok=True)
    src = PRIMARY / "data" / "ncaaf_source" / "historical_truth"
    for name in ("sp_ratings_2023.json", "sp_ratings_2024.json", "games_2024.json.gz", "games_2025.json.gz"):
        if not (ht / name).exists() and (src / name).exists():
            shutil.copy2(src / name, ht / name)
    (work / "cache").mkdir(exist_ok=True)
    return work


def _ncaaf_games(season: int) -> List[dict]:
    path = PRIMARY / "data" / "ncaaf_source" / "historical_truth" / f"games_{season}.json.gz"
    return json.load(gzip.open(path, "rt", encoding="utf-8"))


def _final(g: dict) -> bool:
    return bool(g.get("completed")) and g.get("homePoints") is not None and g.get("awayPoints") is not None


def cmd_fetch(args) -> None:
    """CFBD per-game PPA for the FIT season's weeks (cached; never re-fetched)."""
    work = ncaaf_prepare_work()
    _ncaaf_env(work)
    from scripts import backtest_ncaaf_lines_props as H
    H._load_dotenv()
    from scripts import generate_smartsim2_ncaaf_projections as gen
    calls = 0
    for season in args.season_list:
        for week in range(1, max(NCAAF_WEEKS)):
            path = work / "cache" / f"ppa_games_{season}_wk{week:02d}.json"
            if path.exists():
                continue
            rows = gen._load_ppa_games_week_uncached(season, week)
            path.write_text(json.dumps(rows), encoding="utf-8")
            calls += 1
            print(f"ppa {season} wk{week}: {len(rows)} rows", flush=True)
    print(f"CFBD calls this run: {calls}")


def ncaaf_tasks(seasons: List[int], seeds: int) -> List[Dict[str, Any]]:
    from scripts import backtest_ncaaf_lines_props as H
    work = ncaaf_prepare_work()
    _ncaaf_env(work)
    from scripts import generate_smartsim2_ncaaf_projections as gen
    tasks = []
    for season in seasons:
        games = _ncaaf_games(season)
        prior = dict(gen._read_sp_cache(work / "dataroot" / "ncaaf_source" / "historical_truth" / f"sp_ratings_{season - 1}.json"))
        for week in NCAAF_WEEKS:
            by_id = {int(g["id"]): g for g in games if int(g.get("week") or 0) < week and _final(g)}
            rows = []
            for wk in range(1, week):
                p = work / "cache" / f"ppa_games_{season}_wk{wk:02d}.json"
                if not p.exists():
                    raise SystemExit(f"missing {p}; run `fetch` first")
                rows.extend(json.loads(p.read_text(encoding="utf-8")))
            index, _ = gen.inseason_blend_index(prior, rows, by_id, beta=H.BLEND_BETA_ASOF_2025)
            means = gen.sp_league_means(index)
            for g in games:
                if int(g.get("week") or 0) != week or not _final(g) or g.get("seasonType") != "regular":
                    continue
                if g.get("homeClassification") != "fbs" or g.get("awayClassification") != "fbs":
                    continue
                h, a = gen.norm(g["homeTeam"]), gen.norm(g["awayTeam"])
                if h not in prior or a not in prior or h not in index or a not in index:
                    continue
                tasks.append({"season": season, "week": week, "game_id": int(g["id"]), "home": g["homeTeam"],
                              "away": g["awayTeam"], "means": list(means), "index": {h: index[h], a: index[a]},
                              "rating_source": f"asof_blend_ppa_{season}_wk{week}", "seeds": seeds})
    return tasks


def cmd_sim(args) -> None:
    out = OUT_ROOT / args.sport
    out.mkdir(parents=True, exist_ok=True)
    overrides = _parse_profile_set(args.profile_set)
    cache = out / f"sim_{'-'.join(map(str, args.season_list))}_s{args.seeds}{_variant(args)}.jsonl"
    tasks = (nfl_tasks if args.sport == "nfl" else ncaaf_tasks)(args.season_list, args.seeds)
    if args.every:
        tasks = tasks[:: args.every]      # an even spread over the season, not its first weeks
    if args.limit:
        tasks = tasks[: args.limit]
    done = set()
    if cache.exists():
        done = {json.loads(l)["game_id"] for l in cache.read_text(encoding="utf-8").splitlines() if l.strip()}
    todo = [t for t in tasks if str(t["game_id"]) not in done]
    print(f"[sim {args.sport}] {len(tasks)} games, {len(done)} cached, {len(todo)} to run, "
          f"{args.seeds} seeds, {args.workers} workers -> {cache}", flush=True)
    if not todo:
        return
    init, initarg = (_nfl_init, str(nfl_root())) if args.sport == "nfl" else (_ncaaf_init, str(ncaaf_work()))
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=args.workers, initializer=init, initargs=(initarg, overrides)) as ex, \
            cache.open("a", encoding="utf-8") as fh:
        futs = [ex.submit(sim_task, t) for t in todo]
        for i, fut in enumerate(as_completed(futs), 1):
            fh.write(json.dumps(fut.result()) + "\n")
            fh.flush()
            if i % 25 == 0 or i == len(todo):
                el = time.time() - t0
                print(f"[sim {args.sport}] {i}/{len(todo)}  {el/60:.1f} min  eta {el/i*(len(todo)-i)/60:.1f} min", flush=True)


# ---------------------------------------------------------------------------
# REAL side
# ---------------------------------------------------------------------------

_NFL_SCRIM = {"pass", "run", "punt", "field_goal", "qb_kneel", "qb_spike"}
_NFL_RESULT = {"Touchdown": "TD", "Field goal": "FG", "Missed field goal": "MFG", "Punt": "PUNT",
               "Turnover": "TO", "Turnover on downs": "TOD", "End of half": "EOH", "Safety": "SAF",
               "Opp touchdown": "OPP_TD"}


def _i(x: Any, default: int = 0) -> int:
    try:
        return int(float(x))
    except (TypeError, ValueError):
        return default


def _mmss(x: str) -> int:
    try:
        m, s = str(x).split(":")
        return int(m) * 60 + int(s)
    except ValueError:
        return 0


def real_nfl(seasons: List[int]) -> Dict[str, Dict[str, Any]]:
    games: Dict[str, Dict[str, Any]] = {}
    for season in seasons:
        path = nfl_root() / "tracking" / "nflverse" / "pbp" / f"pbp_{season}.csv"
        rows_by_game: Dict[str, List[dict]] = defaultdict(list)
        with path.open(encoding="utf-8", newline="") as fh:
            for r in csv.DictReader(fh):
                if r.get("season_type") == "REG":
                    rows_by_game[r["game_id"]].append(r)
        for gid, rows in rows_by_game.items():
            games[gid] = _nfl_game(gid, rows)
    return games


def _nfl_game(gid: str, rows: List[dict]) -> Dict[str, Any]:
    home = rows[0]["home_team"]
    by_drive: Dict[str, List[dict]] = defaultdict(list)
    order: List[str] = []
    for r in rows:
        k = r.get("fixed_drive") or ""
        if not k:
            continue
        if k not in by_drive:
            order.append(k)
        by_drive[k].append(r)
    drives: List[Drive] = []
    prev: Optional[str] = None
    prev_q = 0
    for k in sorted(order, key=lambda x: _i(x)):
        dr = by_drive[k]
        scrim = [r for r in dr if r.get("play_type") in _NFL_SCRIM and r.get("posteam")]
        first = scrim[0] if scrim else next((r for r in dr if r.get("posteam")), None)
        if first is None:
            continue
        off = first["posteam"]
        q = _i(first["qtr"])
        res = _NFL_RESULT.get(dr[0].get("fixed_drive_result", ""), "OTHER")
        if res == "TD" and not scrim:
            res = "RET_TD"       # a return touchdown carried on the receiving team's drive
        td_pts = None
        pts = 0
        if res == "TD":
            xp = any(r.get("extra_point_result") == "good" and r.get("posteam") == off for r in dr)
            two = any(r.get("two_point_conv_result") == "success" and r.get("posteam") == off for r in dr)
            td_pts = 6 + (1 if xp else 0) + (2 if two else 0)
            pts = td_pts
        elif res == "FG":
            pts = 3
        fourths, fgs = [], []
        for r in scrim:
            fp = 100 - _i(r.get("yardline_100"), 50)
            if r.get("down") == "4" and r.get("play_type") in ("pass", "run", "punt", "field_goal"):
                pt = r["play_type"]
                fourths.append((fp, _i(r.get("ydstogo"), 10), "punt" if pt == "punt" else ("fg" if pt == "field_goal" else "go")))
            if r.get("play_type") == "field_goal" and r.get("kick_distance"):
                fgs.append((_i(r["kick_distance"]), r.get("field_goal_result") == "made"))
        p = "half" if (prev is None or (q == 3 and prev_q <= 2) or (q >= 5 and prev_q <= 4)) else _prev_category(prev)
        drives.append(Drive(side="home" if off == home else "away", q=q,
                            gsr=_i(first.get("game_seconds_remaining")), diff=_i(first.get("score_differential")),
                            fp=100 - _i(first.get("yardline_100"), 75), result=res, pts=pts, plays=len(scrim),
                            secs=_mmss(first.get("drive_time_of_possession") or ""),
                            rz=any(_i(r.get("yardline_100"), 99) <= 20 for r in scrim), prev=p,
                            fourths=fourths, fgs=fgs, td_pts=td_pts))
        prev, prev_q = res, q
    last = rows[-1]
    hs, as_ = _i(last.get("home_score")), _i(last.get("away_score"))
    h1 = max((_i(r.get("total_home_score")) + _i(r.get("total_away_score")) for r in rows if _i(r.get("qtr")) <= 2), default=0)
    return {"drives": drives, "total": hs + as_, "margin": hs - as_, "ot": any(_i(r.get("qtr")) >= 5 for r in rows),
            "h1": h1, "close_spread": _flt(last.get("spread_line")), "close_total": _flt(last.get("total_line"))}


def _flt(x: Any) -> Optional[float]:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


_CFBD_RESULT = {"TD": "TD", "FG": "FG", "MISSED FG": "MFG", "PUNT": "PUNT", "INT": "TO", "FUMBLE": "TO",
                "DOWNS": "TOD", "END OF HALF": "EOH", "END OF GAME": "EOH", "END OF 4TH QUARTER": "EOH",
                "SF": "SAF"}
_CFBD_SCRIM = {"Rush", "Pass Reception", "Pass Incompletion", "Sack", "Passing Touchdown", "Rushing Touchdown",
               "Interception", "Pass Interception Return", "Interception Return Touchdown",
               "Fumble Recovery (Own)", "Fumble Recovery (Opponent)", "Fumble Return Touchdown", "Punt",
               "Field Goal Good", "Field Goal Missed", "Blocked Field Goal", "Blocked Punt", "Safety",
               "Punt Return Touchdown", "Blocked Punt Touchdown", "Blocked Field Goal Touchdown", "Pass"}


def real_ncaaf(seasons: List[int]) -> Dict[str, Dict[str, Any]]:
    root = PRIMARY / "data" / "ncaaf_source" / "historical_truth"
    games: Dict[str, Dict[str, Any]] = {}
    for season in seasons:
        meta = {int(g["id"]): g for g in _ncaaf_games(season)}
        plays_by_drive: Dict[str, List[dict]] = defaultdict(list)
        for wk in range(1, 17):
            p = root / f"plays_{season}_wk{wk:02d}.json.gz"
            if p.exists():
                for r in json.load(gzip.open(p, "rt", encoding="utf-8")):
                    plays_by_drive[str(r.get("driveId"))].append(r)
        drives_by_game: Dict[int, List[dict]] = defaultdict(list)
        for d in json.load(gzip.open(root / f"drives_{season}.json.gz", "rt", encoding="utf-8")):
            drives_by_game[int(d["gameId"])].append(d)
        for gid, dl in drives_by_game.items():
            g = meta.get(gid)
            if g is None or not _final(g):
                continue
            games[str(gid)] = _ncaaf_game(g, sorted(dl, key=lambda d: int(d.get("driveNumber") or 0)), plays_by_drive)
    return games


def _ncaaf_game(g: dict, dl: List[dict], plays_by_drive: Dict[str, List[dict]]) -> Dict[str, Any]:
    drives: List[Drive] = []
    prev: Optional[str] = None
    prev_q = 0
    for d in dl:
        q = _i(d.get("startPeriod"), 1)
        raw = str(d.get("driveResult") or "")
        res = _CFBD_RESULT.get(raw)
        if res is None:
            res = "OPP_TD" if raw.endswith("TD") else "OTHER"
        st = d.get("startTime") or {}
        el = d.get("elapsed") or {}
        plays = sorted(plays_by_drive.get(str(d.get("id")), []), key=lambda r: _i(r.get("playNumber")))
        scrim = [r for r in plays if r.get("playType") in _CFBD_SCRIM and r.get("offense") == d.get("offense")]
        if res == "TD" and not scrim:
            res = "RET_TD"
        # CFBD's per-drive start/end scores LAG (a TD drive can read 14 -> 14), so
        # points come from the result, TD = 7. PAT/2pt (S7) is not measurable here.
        pts = 7 if res == "TD" else (3 if res == "FG" else 0)
        fourths, fgs = [], []
        for r in scrim:
            ytg = _i(r.get("yardsToGoal"), 50)
            pt = r.get("playType", "")
            if _i(r.get("down")) == 4:
                fourths.append((100 - ytg, _i(r.get("distance"), 10),
                                "punt" if "Punt" in pt else ("fg" if "Field Goal" in pt else "go")))
            if "Field Goal" in pt:
                fgs.append((ytg + 17, pt == "Field Goal Good"))
        p = "half" if (prev is None or (q == 3 and prev_q <= 2) or (q >= 5 and prev_q <= 4)) else _prev_category(prev)
        drives.append(Drive(side="home" if d.get("isHomeOffense") else "away", q=q,
                            gsr=_gsr(q, _i(st.get("minutes")) * 60 + _i(st.get("seconds"))),
                            diff=_i(d.get("startOffenseScore")) - _i(d.get("startDefenseScore")),
                            fp=100 - _i(d.get("startYardsToGoal"), 75), result=res, pts=pts, plays=_i(d.get("plays")),
                            secs=_i(el.get("minutes")) * 60 + _i(el.get("seconds")),
                            rz=any(_i(r.get("yardsToGoal"), 99) <= 20 for r in scrim), prev=p,
                            fourths=fourths, fgs=fgs, td_pts=None))
        prev, prev_q = res, q
    nonoff = sum(7 for d in drives if d.result in ("OPP_TD", "RET_TD")) + sum(2 for d in drives if d.result == "SAF")
    hl, al = g.get("homeLineScores") or [], g.get("awayLineScores") or []
    hs, as_ = _i(g["homePoints"]), _i(g["awayPoints"])
    return {"drives": drives, "total": hs + as_, "margin": hs - as_, "ot": len(hl) > 4,
            "h1": sum(_i(x) for x in hl[:2]) + sum(_i(x) for x in al[:2]),
            "close_spread": None, "close_total": None, "nonoff": nonoff}


def cmd_real(args) -> None:
    out = OUT_ROOT / args.sport
    out.mkdir(parents=True, exist_ok=True)
    games = (real_nfl if args.sport == "nfl" else real_ncaaf)(args.season_list)
    path = out / f"real_{'-'.join(map(str, args.season_list))}.jsonl"
    with path.open("w", encoding="utf-8") as fh:
        for gid, g in games.items():
            c_side = {"home": {}, "away": {}}
            for side in ("home", "away"):
                mine = [d for d in g["drives"] if d.side == side]
                for d in mine:
                    add_drive(c_side[side], d, args.sport)
                add_team_game(c_side[side], mine)
            c_game: Dict[str, float] = {}
            # NFL: non-offensive points = the residual (PATs are measured per drive).
            # NCAAF: counted directly, since its drive points assume TD = 7.
            off_pts = (g["total"] - g["nonoff"]) if "nonoff" in g else sum(d.pts for d in g["drives"])
            add_game(c_game, total=g["total"], margin=g["margin"], ot=g["ot"], h1=g["h1"], offense_pts=off_pts)
            fh.write(json.dumps({"game_id": gid, "c_home": c_side["home"], "c_away": c_side["away"], "c_game": c_game,
                                 "total": g["total"], "margin": g["margin"], "close_spread": g["close_spread"],
                                 "close_total": g["close_total"], "n_drives": len(g["drives"])}) + "\n")
    print(f"[real {args.sport}] {len(games)} games -> {path}")


# ---------------------------------------------------------------------------
# REPORT
# ---------------------------------------------------------------------------

def _load(path: Path) -> Dict[str, dict]:
    return {json.loads(l)["game_id"]: json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()}


def _sum(cs: Iterable[Dict[str, float]]) -> Dict[str, float]:
    t: Dict[str, float] = defaultdict(float)
    for c in cs:
        for k, v in c.items():
            t[k] += v
    return t


# (row id, label, numerator key(s), denominator key, scale) -- rates computed as sum(num)/sum(den)
def _metric_rows(keys: Iterable[str]) -> List[Tuple[str, str, str, str]]:
    rows = [("S1", f"P({r})/drive", f"res:{r}", "drives") for r in ("TD", "FG", "MFG", "PUNT", "TO", "TOD", "EOH", "SAF", "OPP_TD", "RET_TD")]
    rows += [("S1", "pts/drive", "pts", "drives"), ("S6", "plays/drive", "plays", "drives"),
             ("S6", "drives/team-game", "drives", "team_games"), ("S3", "secs/play (all)", "secs", "plays"),
             ("S4", "P(TD|RZ)", "rz:td", "rz:n"), ("S4", "P(FGA|RZ)", "rz:fga", "rz:n"),
             ("S4", "P(reach RZ)/drive", "rz:n", "drives"), ("S7", "pts/TD", "td:pts", "td:n"),
             ("S8", "OT pts/drive", "ot:pts", "ot:drives")]
    for s in ("lead", "trail"):
        rows += [("S2", f"garbage {s}: pts/drive", f"gt:{s}:pts", f"gt:{s}:drives"),
                 ("S2", f"garbage {s}: secs/play", f"gt:{s}:secs", f"gt:{s}:plays"),
                 ("S2", f"garbage {s}: drive share", f"gt:{s}:drives", "drives")]
    for st in ("lead9", "close", "trail9"):
        for h in ("h1", "h2"):
            rows.append(("S3", f"secs/play {st} {h}", f"pace:{st}:{h}:secs", f"pace:{st}:{h}:plays"))
    for b in ("<30", "30-39", "40-49", "50+"):
        rows.append(("S4b", f"FG make {b}", f"fg:{b}:made", f"fg:{b}:att"))
    for fpb in ("own", "opp50-30", "opp29in"):
        for tg in ("1-2", "3-5", "6+"):
            for dec in ("go", "punt", "fg"):
                rows.append(("S5", f"4th {fpb} {tg}: P({dec})", f"4th:{fpb}|{tg}:{dec}", f"4th:{fpb}|{tg}:n"))
    for p in ("half", "score", "punt", "turnover"):
        rows.append(("S12", f"start fp after {p}", f"fp:{p}:sum", f"fp:{p}:n"))
    return rows


def _rate(c: Dict[str, float], num: str, den: str) -> Optional[float]:
    d = c.get(den, 0.0)
    return c.get(num, 0.0) / d if d else None


def _boot(units: List[Dict[str, float]], num: str, den: str, reps: int, seed: int) -> Tuple[Optional[float], Optional[float]]:
    rng = random.Random(seed)
    vals = []
    n = len(units)
    for _ in range(reps):
        nn = dd = 0.0
        for _ in range(n):
            u = units[rng.randrange(n)]
            nn += u.get(num, 0.0)
            dd += u.get(den, 0.0)
        if dd:
            vals.append(nn / dd)
    if len(vals) < reps * 0.9:
        return None, None
    vals.sort()
    return vals[int(0.025 * len(vals))], vals[int(0.975 * len(vals)) - 1]


def _points_effect(row_id: str, label: str, gap: float, base: Dict[str, float]) -> Optional[float]:
    """Implied points per TEAM-GAME of the gap (sim - real), first order. None where no clean mapping."""
    tg = base.get("team_games") or 0
    if not tg:
        return None
    drives_pg = base.get("drives", 0) / tg
    if label == "pts/drive":
        return gap * drives_pg
    if label.startswith("P(TD)/drive"):
        return gap * drives_pg * 7
    if label.startswith("P(FG)/drive"):
        return gap * drives_pg * 3
    if label == "drives/team-game":
        return gap * (base.get("pts", 0) / max(1.0, base.get("drives", 0)))
    if label == "P(TD|RZ)":
        return gap * base.get("rz:n", 0) / tg * 4.0           # TD instead of FG: +4
    if label == "pts/TD":
        return gap * base.get("td:n", 0) / tg
    if label.startswith("garbage") and "pts/drive" in label:
        s = label.split()[1].rstrip(":")
        return gap * base.get(f"gt:{s}:drives", 0) / tg
    if label.startswith("FG make"):
        b = label.split()[-1]
        return gap * base.get(f"fg:{b}:att", 0) / tg * 3
    return None


def _variant(args) -> str:
    return "".join(f"_{x.replace('=', '-')}" for x in sorted(args.profile_set or []))


def cmd_report(args) -> None:
    sport = args.sport
    out = OUT_ROOT / sport
    tag = "-".join(map(str, args.season_list))
    sim = _load(out / f"sim_{tag}_s{args.seeds}{_variant(args)}.jsonl")
    real = _load(out / f"real_{tag}.jsonl")
    common = sorted(set(sim) & set(real))
    print(f"COVERAGE {sport} {tag}: sim {len(sim)} games, real {len(real)} games, INTERSECTION {len(common)} "
          f"(sim-only {len(set(sim) - set(real))}, real-only {len(set(real) - set(sim))})")
    if not common:
        return
    # S1 rating-gap terciles: gap = offense rating minus the opponent's defense rating, as the sim RECEIVED them
    gaps = []
    for gid in common:
        r = sim[gid]["ratings"]
        gaps.append((gid, "home", r["home_offense_rating"] - r["away_defense_rating"]))
        gaps.append((gid, "away", r["away_offense_rating"] - r["home_defense_rating"]))
    gv = sorted(x[2] for x in gaps)
    cuts = (gv[len(gv) // 3], gv[2 * len(gv) // 3])
    terc = {(g, s): ("weak" if v < cuts[0] else ("mid" if v < cuts[1] else "strong")) for g, s, v in gaps}

    def units(src: Dict[str, dict], tercile: Optional[str] = None) -> List[Dict[str, float]]:
        us = []
        for gid in common:
            u: Dict[str, float] = defaultdict(float)
            for side in ("home", "away"):
                if tercile and terc[(gid, side)] != tercile:
                    continue
                for k, v in src[gid][f"c_{side}"].items():
                    u[k] += v
            us.append(u)
        return us

    results = []
    for scope in (None, "weak", "mid", "strong"):
        ru, su = units(real, scope), units(sim, scope)
        rt, stt = _sum(ru), _sum(su)
        rows = _metric_rows(rt.keys())
        if scope:
            rows = [r for r in rows if r[0] == "S1" or r[1] in ("P(TD|RZ)", "plays/drive")]
        for rid, label, num, den in rows:
            rr, sr = _rate(rt, num, den), _rate(stt, num, den)
            if rr is None or sr is None:
                continue
            lo, hi = _boot(ru, num, den, args.reps, 7)
            slo, shi = _boot(su, num, den, max(200, args.reps // 5), 11)
            eff = _points_effect(rid, label, sr - rr, rt)
            outside = lo is not None and not (lo <= sr <= hi)
            flag = bool(outside and eff is not None and abs(eff) >= FLAG_POINTS[sport])
            results.append({"id": rid, "scope": scope or "all", "metric": label, "real": rr, "real_lo": lo,
                            "real_hi": hi, "sim": sr, "sim_lo": slo, "sim_hi": shi, "gap": sr - rr,
                            "n_real_den": rt.get(den, 0), "pts_per_team_game": eff, "outside_ci": outside,
                            "FLAG": flag})
    # S1b dispersion, S8-S11 game level
    def sd_tg(t):
        n = t.get("ppd_tg:n", 0)
        if not n:
            return None
        m = t["ppd_tg:sum"] / n
        return math.sqrt(max(0.0, t["ppd_tg:sumsq"] / n - m * m))
    rt_all, st_all = _sum(units(real)), _sum(units(sim))
    game_rows = [("S1b", "SD of team-game pts/drive", sd_tg(rt_all), sd_tg(st_all))]
    rg = _sum(real[g]["c_game"] for g in common)
    sg = _sum(sim[g]["c_game"] for g in common)
    for rid, label, key in (("S8", "P(OT)", "g:ot"), ("S9", "H1 points/game", "g:h1"), ("S11", "non-offensive pts/game", "g:nonoff"),
                            ("S10", "total/game", "g:total"), ("S10", "margin/game", "g:margin")):
        game_rows.append((rid, label, rg[key] / rg["g:n"], sg[key] / sg["g:n"]))
    # S10 spread of outcomes: real residual SDs vs the sim's own predictive SD
    res_t = [real[g]["total"] - sim[g]["total_mean"] for g in common]
    res_m = [real[g]["margin"] - sim[g]["margin_mean"] for g in common]
    sd = lambda xs: statistics_pstdev(xs)
    game_rows += [("S10", "SD(actual total - sim mean)", sd(res_t), sum(sim[g]["total_stdev"] for g in common) / len(common)),
                  ("S10", "SD(actual margin - sim mean)", sd(res_m), sum(sim[g]["margin_stdev"] for g in common) / len(common))]
    ct = [(real[g]["total"] - real[g]["close_total"]) for g in common if real[g].get("close_total") is not None]
    cm = [(real[g]["margin"] - real[g]["close_spread"]) for g in common if real[g].get("close_spread") is not None]
    if ct:
        game_rows.append(("S10", f"SD(actual total - close) n={len(ct)}", sd(ct), None))
        game_rows.append(("S10", f"SD(actual margin - close) n={len(cm)}", sd(cm), None))
    report = {"sport": sport, "seasons": args.season_list, "seeds": args.seeds, "games": len(common),
              "tercile_cuts": cuts, "rows": results,
              "game_rows": [{"id": a, "metric": b, "real": c, "sim": d} for a, b, c, d in game_rows]}
    (out / f"report_{tag}{_variant(args)}.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    _print(report)


def statistics_pstdev(xs: List[float]) -> Optional[float]:
    if len(xs) < 2:
        return None
    m = sum(xs) / len(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / len(xs))


def _fmt(x: Optional[float], nd: int = 3) -> str:
    return "-" if x is None else f"{x:.{nd}f}"


def _print(rep: Dict[str, Any]) -> None:
    print(f"\n{rep['sport'].upper()} {rep['seasons']}  games={rep['games']}  seeds={rep['seeds']}  tercile cuts={rep['tercile_cuts']}")
    print(f"{'id':5} {'scope':6} {'metric':34} {'real':>8} {'95% CI':>17} {'sim':>8} {'gap':>8} {'pts/tg':>7}  flag")
    for r in rep["rows"]:
        if r["n_real_den"] < 30:
            continue
        ci = f"[{_fmt(r['real_lo'])},{_fmt(r['real_hi'])}]"
        print(f"{r['id']:5} {r['scope']:6} {r['metric']:34} {_fmt(r['real']):>8} {ci:>17} {_fmt(r['sim']):>8} "
              f"{_fmt(r['gap']):>8} {_fmt(r['pts_per_team_game'], 2):>7}  {'FLAG' if r['FLAG'] else ('out' if r['outside_ci'] else '')}")
    print()
    for g in rep["game_rows"]:
        print(f"{g['id']:5} {g['metric']:40} real {_fmt(g['real'])}   sim {_fmt(g['sim'])}")


# ---------------------------------------------------------------------------
# H2: the measured 4th-down decision + conversion tables (pre-registered)
# ---------------------------------------------------------------------------

FD_FP_EDGES = (40, 50, 60, 70, 80, 90)            # yards from own goal -> 7 buckets
FD_TOGO_EDGES = (2, 3, 5, 8, 11)                  # to-go 1 | 2 | 3-4 | 5-7 | 8-10 | 11+
FD_SMOOTH = 10.0


def fd_fp_bucket(fp: int) -> int:
    return sum(1 for e in FD_FP_EDGES if fp >= e)


def fd_togo_bucket(togo: int) -> int:
    return sum(1 for e in FD_TOGO_EDGES if togo >= e)


def _fd_excluded(q: int, clock: int, fp: int, diff: int) -> bool:
    """States the engine already decides by its own rules (late-trailing go, urgency FG)."""
    if q >= 4 and clock <= 300 and diff < 0:
        return True
    if q in (2, 4) and clock <= 90 and fp >= 65 and -9 <= diff <= 2:
        return True
    return False


def fourth_down_rows(sport: str, seasons: List[int]) -> List[Tuple[int, int, str, Optional[bool]]]:
    """(fp, to_go, decision, converted-or-None) for every in-population real 4th down."""
    rows: List[Tuple[int, int, str, Optional[bool]]] = []
    if sport == "nfl":
        for season in seasons:
            path = nfl_root() / "tracking" / "nflverse" / "pbp" / f"pbp_{season}.csv"
            with path.open(encoding="utf-8", newline="") as fh:
                for r in csv.DictReader(fh):
                    if r.get("season_type") != "REG" or r.get("down") != "4" or r.get("aborted_play") == "1":
                        continue
                    pt = r.get("play_type")
                    if pt not in ("pass", "run", "punt", "field_goal"):
                        continue
                    q = _i(r.get("qtr"))
                    fp = 100 - _i(r.get("yardline_100"), 50)
                    if _fd_excluded(q, _i(r.get("quarter_seconds_remaining")), fp, _i(r.get("score_differential"))):
                        continue
                    dec = "punt" if pt == "punt" else ("fg" if pt == "field_goal" else "go")
                    conv = (r.get("fourth_down_converted") == "1") if dec == "go" else None
                    rows.append((fp, _i(r.get("ydstogo"), 10), dec, conv))
    else:
        root = PRIMARY / "data" / "ncaaf_source" / "historical_truth"
        for season in seasons:
            meta = {int(g["id"]): g for g in _ncaaf_games(season)}
            for wk in range(1, 17):
                p = root / f"plays_{season}_wk{wk:02d}.json.gz"
                if not p.exists():
                    continue
                for r in json.load(gzip.open(p, "rt", encoding="utf-8")):
                    g = meta.get(int(r.get("gameId") or 0))
                    if not g or g.get("seasonType") != "regular" or g.get("homeClassification") != "fbs" \
                            or g.get("awayClassification") != "fbs":
                        continue
                    pt = r.get("playType", "")
                    if _i(r.get("down")) != 4 or pt not in _CFBD_SCRIM:
                        continue
                    q = _i(r.get("period"))
                    clock = _i((r.get("clock") or {}).get("minutes")) * 60 + _i((r.get("clock") or {}).get("seconds"))
                    fp = 100 - _i(r.get("yardsToGoal"), 50)
                    diff = _i(r.get("offenseScore")) - _i(r.get("defenseScore"))
                    if q > 4 or _fd_excluded(q, clock, fp, diff):
                        continue
                    dec = "punt" if "Punt" in pt else ("fg" if "Field Goal" in pt else "go")
                    conv = None
                    if dec == "go":
                        off_td = pt in ("Passing Touchdown", "Rushing Touchdown")
                        conv = off_td or _i(r.get("yardsGained")) >= _i(r.get("distance"), 99)
                    rows.append((fp, _i(r.get("distance"), 10), dec, conv))
    return rows


def fourth_down_tables(rows: List[Tuple[int, int, str, Optional[bool]]]) -> Dict[str, Any]:
    cell: Dict[Tuple[int, int], Dict[str, int]] = defaultdict(lambda: {"go": 0, "fg": 0, "punt": 0})
    marg: Dict[int, Dict[str, int]] = defaultdict(lambda: {"go": 0, "fg": 0, "punt": 0})
    conv: Dict[int, List[int]] = defaultdict(lambda: [0, 0])
    for fp, togo, dec, c in rows:
        fb, tb = fd_fp_bucket(fp), fd_togo_bucket(togo)
        cell[(fb, tb)][dec] += 1
        marg[fb][dec] += 1
        if dec == "go":
            conv[tb][0] += int(bool(c))
            conv[tb][1] += 1
    decision: Dict[str, Any] = {}
    for fb in range(len(FD_FP_EDGES) + 1):
        m = marg[fb]
        mt = sum(m.values()) or 1
        for tb in range(len(FD_TOGO_EDGES) + 1):
            c = cell[(fb, tb)]
            n = sum(c.values())
            sm = {k: c[k] + FD_SMOOTH * m[k] / mt for k in ("go", "fg", "punt")}
            tot = sum(sm.values()) or 1.0
            decision[f"{fb},{tb}"] = {"go": round(sm["go"] / tot, 4), "fg": round(sm["fg"] / tot, 4),
                                      "punt": round(sm["punt"] / tot, 4), "n": n}
    conversion = {str(tb): {"p": round(conv[tb][0] / conv[tb][1], 4) if conv[tb][1] else None, "n": conv[tb][1]}
                  for tb in range(len(FD_TOGO_EDGES) + 1)}
    return {"decision": decision, "conversion": conversion, "n_rows": len(rows)}


def cmd_fourth(args) -> None:
    rows = fourth_down_rows(args.sport, args.season_list)
    t = fourth_down_tables(rows)
    out = OUT_ROOT / args.sport / f"fourth_down_tables_{'-'.join(map(str, args.season_list))}.json"
    out.write_text(json.dumps(t, indent=1), encoding="utf-8")
    print(f"{args.sport} {args.season_list}: {t['n_rows']} in-population 4th downs -> {out}")
    togo_lbl = ["1", "2", "3-4", "5-7", "8-10", "11+"]
    fp_lbl = ["<40", "40-49", "50-59", "60-69", "70-79", "80-89", "90+"]
    print("P(go) [n]      " + "".join(f"{x:>14}" for x in togo_lbl))
    for fb, fl in enumerate(fp_lbl):
        print(f"fp {fl:>6}     " + "".join(f"{t['decision'][f'{fb},{tb}']['go']:>8.3f} [{t['decision'][f'{fb},{tb}']['n']:>3}]"
                                          for tb in range(6)))
    print("P(fg)          " + "".join(f"{x:>14}" for x in togo_lbl))
    for fb, fl in enumerate(fp_lbl):
        print(f"fp {fl:>6}     " + "".join(f"{t['decision'][f'{fb},{tb}']['fg']:>14.3f}" for tb in range(6)))
    print("conversion     " + "".join(f"{(t['conversion'][str(tb)]['p'] or 0):>8.3f} [{t['conversion'][str(tb)]['n']:>3}]" for tb in range(6)))


# ---------------------------------------------------------------------------
# H3: non-offensive scoring rates (pre-registered)
# ---------------------------------------------------------------------------

def _wilson(k: int, n: int) -> Tuple[Optional[float], Optional[float]]:
    if not n:
        return None, None
    z = 1.96
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return c - h, c + h


def nonoff_counts(sport: str, seasons: List[int]) -> Dict[str, List[int]]:
    """[successes, trials] per rate; plus the free-kick start spots after safeties."""
    c: Dict[str, List[int]] = defaultdict(lambda: [0, 0])
    fk: List[int] = []
    if sport == "nfl":
        for season in seasons:
            path = nfl_root() / "tracking" / "nflverse" / "pbp" / f"pbp_{season}.csv"
            prev_safety_game = None
            with path.open(encoding="utf-8", newline="") as fh:
                for r in csv.DictReader(fh):
                    if r.get("season_type") != "REG":
                        continue
                    pt = r.get("play_type")
                    ret_td = r.get("return_touchdown") == "1"
                    td_team = r.get("td_team")
                    if prev_safety_game == r["game_id"] and pt in ("pass", "run"):
                        fk.append(100 - _i(r.get("yardline_100"), 65))   # first snap after the free kick
                        prev_safety_game = None
                    if pt in ("pass", "run") and (r.get("interception") == "1" or r.get("fumble_lost") == "1"):
                        c["def_td"][1] += 1
                        c["def_td"][0] += int(ret_td and td_team == r.get("defteam"))
                    if pt == "punt":
                        c["punt_ret_td"][1] += 1
                        c["punt_ret_td"][0] += int(ret_td and td_team == r.get("defteam"))
                    if pt == "kickoff":
                        c["ko_ret_td"][1] += 1
                        c["ko_ret_td"][0] += int(ret_td and td_team == r.get("posteam"))
                    if pt in ("pass", "run", "qb_kneel", "qb_spike"):
                        y = _i(r.get("yardline_100"), 50)
                        if y >= 90:
                            b = "safety_1_5" if y >= 95 else "safety_6_10"
                            c[b][1] += 1
                            c[b][0] += int(r.get("safety") == "1")
                    if r.get("safety") == "1":
                        prev_safety_game = r["game_id"]
    else:
        root = PRIMARY / "data" / "ncaaf_source" / "historical_truth"
        to_types = {"Interception", "Pass Interception Return", "Fumble Recovery (Opponent)"}
        def_td_types = {"Interception Return Touchdown", "Fumble Return Touchdown"}
        for season in seasons:
            meta = {int(g["id"]): g for g in _ncaaf_games(season)}
            for wk in range(1, 17):
                p = root / f"plays_{season}_wk{wk:02d}.json.gz"
                if not p.exists():
                    continue
                plays = json.load(gzip.open(p, "rt", encoding="utf-8"))
                plays.sort(key=lambda r: (int(r.get("gameId") or 0), _i(r.get("driveNumber")), _i(r.get("playNumber"))))
                after_safety = None
                for r in plays:
                    g = meta.get(int(r.get("gameId") or 0))
                    if not g or g.get("seasonType") != "regular" or g.get("homeClassification") != "fbs" \
                            or g.get("awayClassification") != "fbs":
                        continue
                    pt = r.get("playType", "")
                    if after_safety == r.get("gameId") and pt in ("Rush", "Pass Reception", "Pass Incompletion", "Sack"):
                        fk.append(100 - _i(r.get("yardsToGoal"), 65))
                        after_safety = None
                    if pt in to_types or pt in def_td_types:
                        c["def_td"][1] += 1
                        c["def_td"][0] += int(pt in def_td_types)
                    if pt in ("Punt", "Blocked Punt", "Punt Return Touchdown", "Blocked Punt Touchdown"):
                        c["punt_ret_td"][1] += 1
                        c["punt_ret_td"][0] += int(pt.endswith("Touchdown"))
                    if pt in ("Kickoff", "Kickoff Return (Offense)", "Kickoff Return Touchdown"):
                        c["ko_ret_td"][1] += 1
                        c["ko_ret_td"][0] += int(pt == "Kickoff Return Touchdown")
                    if pt in _CFBD_SCRIM and pt not in ("Punt", "Blocked Punt", "Field Goal Good", "Field Goal Missed",
                                                         "Blocked Field Goal", "Punt Return Touchdown",
                                                         "Blocked Punt Touchdown", "Blocked Field Goal Touchdown"):
                        ytg = _i(r.get("yardsToGoal"), 50)
                        if ytg >= 90:
                            b = "safety_1_5" if ytg >= 95 else "safety_6_10"
                            c[b][1] += 1
                            c[b][0] += int(pt == "Safety")
                    if pt == "Safety":
                        after_safety = r.get("gameId")
    out = {k: list(v) for k, v in c.items()}
    out["free_kick_start"] = [sum(fk), len(fk)]
    return out


def cmd_nonoff(args) -> None:
    c = nonoff_counts(args.sport, args.season_list)
    path = OUT_ROOT / args.sport / f"nonoff_rates_{'-'.join(map(str, args.season_list))}.json"
    rates = {}
    for k, (s, n) in sorted(c.items()):
        if k == "free_kick_start":
            rates[k] = {"mean": round(s / n, 2) if n else None, "n": n}
            print(f"{args.sport} {k:14} mean {rates[k]['mean']}  n={n}")
            continue
        lo, hi = _wilson(s, n)
        rates[k] = {"p": round(s / n, 5) if n else None, "k": s, "n": n, "lo": lo, "hi": hi}
        print(f"{args.sport} {k:14} {s:5d}/{n:6d} = {s / n if n else 0:.5f}  95% [{lo:.5f}, {hi:.5f}]")
    path.write_text(json.dumps(rates, indent=1), encoding="utf-8")


# ---------------------------------------------------------------------------
# COMPARE: a switch ON vs production (OFF), paired on the same games and seeds
# ---------------------------------------------------------------------------

def _paired_ci(deltas: List[float], reps: int = 2000, seed: int = 3) -> Tuple[float, float, float]:
    rng = random.Random(seed)
    n = len(deltas)
    mean = sum(deltas) / n
    bs = sorted(sum(deltas[rng.randrange(n)] for _ in range(n)) / n for _ in range(reps))
    return mean, bs[int(0.025 * reps)], bs[int(0.975 * reps) - 1]


def cmd_compare(args) -> None:
    sport = args.sport
    out = OUT_ROOT / sport
    tag = "-".join(map(str, args.season_list))
    off = _load(out / f"sim_{tag}_s{args.seeds}.jsonl")
    on = _load(out / f"sim_{tag}_s{args.seeds}{_variant(args)}.jsonl")
    real = _load(out / f"real_{tag}.jsonl")
    common = sorted(set(off) & set(on) & set(real))
    print(f"COMPARE {sport} {tag} {_variant(args) or '(no variant!)'}: OFF {len(off)}, ON {len(on)}, real {len(real)}, "
          f"PAIRED {len(common)} games, {args.seeds} seeds each")
    if len(common) < 20:
        print("too few paired games for a reading")
        return

    def rows(fn) -> List[float]:
        return [fn(g) for g in common]

    lines = []
    for label, fn in (
        ("mean total (pts)", lambda g, s: s[g]["total_mean"]),
        ("mean margin (home, pts)", lambda g, s: s[g]["margin_mean"]),
        ("total SD (sim)", lambda g, s: s[g]["total_stdev"]),
        ("margin SD (sim)", lambda g, s: s[g]["margin_stdev"]),
        ("P(home win)", lambda g, s: s[g]["home_win_rate"]),
    ):
        d = rows(lambda g: fn(g, on) - fn(g, off))
        m, lo, hi = _paired_ci(d)
        lines.append((label, sum(rows(lambda g: fn(g, off))) / len(common), sum(rows(lambda g: fn(g, on))) / len(common), m, lo, hi))
    # accuracy vs the actual result -- a NEGATIVE delta is an improvement
    acc = []
    for label, fn in (
        ("MAE total vs actual", lambda g, s: abs(real[g]["total"] - s[g]["total_mean"])),
        ("MAE margin vs actual", lambda g, s: abs(real[g]["margin"] - s[g]["margin_mean"])),
        ("Brier home win", lambda g, s: (s[g]["home_win_rate"] - (1.0 if real[g]["margin"] > 0 else 0.0)) ** 2),
    ):
        keep = [g for g in common if not (label.startswith("Brier") and real[g]["margin"] == 0)]
        d = [fn(g, on) - fn(g, off) for g in keep]
        m, lo, hi = _paired_ci(d)
        acc.append((label, sum(fn(g, off) for g in keep) / len(keep), sum(fn(g, on) for g in keep) / len(keep), m, lo, hi))
    close = [g for g in common if real[g].get("close_total") is not None and real[g].get("close_spread") is not None]
    if close:
        for label, fn in (
            ("|sim - close| total", lambda g, s: abs(s[g]["total_mean"] - real[g]["close_total"])),
            ("|sim - close| margin", lambda g, s: abs(s[g]["margin_mean"] - real[g]["close_spread"])),
        ):
            d = [fn(g, on) - fn(g, off) for g in close]
            m, lo, hi = _paired_ci(d)
            acc.append((label, sum(fn(g, off) for g in close) / len(close), sum(fn(g, on) for g in close) / len(close), m, lo, hi))
        ref_t = sum(abs(real[g]["total"] - real[g]["close_total"]) for g in close) / len(close)
        ref_m = sum(abs(real[g]["margin"] - real[g]["close_spread"]) for g in close) / len(close)
    print(f"\n{'quantity':30} {'OFF':>9} {'ON':>9} {'ON-OFF':>9} {'95% CI (paired, games)':>24}")
    for label, a, b, m, lo, hi in lines + acc:
        sig = "" if lo <= 0 <= hi else "  *"
        print(f"{label:30} {a:9.3f} {b:9.3f} {m:+9.3f}   [{lo:+.3f}, {hi:+.3f}]{sig}")
    if close:
        print(f"{'(close) MAE total / margin':30} {ref_t:9.3f} {ref_m:9.3f}   on the same {len(close)} games")

    # scenario rows: OFF vs ON vs real on the paired games
    def tot(src: Dict[str, dict]) -> Dict[str, float]:
        return _sum([src[g]["c_home"] for g in common] + [src[g]["c_away"] for g in common])
    to, tn, tr = tot(off), tot(on), tot(real)
    print(f"\n{'scenario row':34} {'real':>8} {'OFF':>8} {'ON':>8}")
    keys = [r for r in _metric_rows(tr.keys()) if r[0] in ("S1", "S4", "S5", "S6", "S12")]
    for rid, label, num, den in keys:
        rr, ro, rn = _rate(tr, num, den), _rate(to, num, den), _rate(tn, num, den)
        if rr is None or tr.get(den, 0) < 30:
            continue
        print(f"{rid:4} {label:29} {rr:8.3f} {_fmt(ro):>8} {_fmt(rn):>8}")


def main(argv: Optional[List[str]] = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("fetch", "sim", "real", "report", "fourth", "compare", "nonoff"))
    ap.add_argument("--sport", choices=("nfl", "ncaaf"), required=True)
    ap.add_argument("--seasons", required=True)
    ap.add_argument("--seeds", type=int, default=300)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--reps", type=int, default=1000)
    ap.add_argument("--every", type=int, default=0, help="take every Nth game (an even spread)")
    ap.add_argument("--profile-set", action="append", default=[],
                    help="CalibrationProfile field=value against production's profile (repeatable)")
    args = ap.parse_args(argv)
    args.season_list = [int(s) for s in args.seasons.split(",")]
    if 2025 in args.season_list and not os.environ.get("FOOTBALL_SCENARIO_READ_VALIDATION"):
        raise SystemExit("2025 is VALIDATION (read once, pre-registered); set FOOTBALL_SCENARIO_READ_VALIDATION=1 to read it")
    {"fetch": cmd_fetch, "sim": cmd_sim, "real": cmd_real, "report": cmd_report, "fourth": cmd_fourth, "compare": cmd_compare, "nonoff": cmd_nonoff}[args.cmd](args)


if __name__ == "__main__":
    main()
