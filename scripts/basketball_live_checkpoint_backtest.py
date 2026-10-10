"""Basketball live-lens CHECKPOINT BACKTEST on historical play-by-play (P3 of
docs/ai_context/basketball_live_native_plan.md, lane `nba-native-live-resim`).

WHAT IT DOES. For every completed game in an ESPN pbp corpus it reconstructs the game state at fixed in-game
checkpoints (end Q1 / end Q2 / end Q3 / 5:00 Q4), asks each registered PROJECTOR for its live projection
from that state, and grades it against what actually happened (the final, the rest-of-period points) and,
when a live-close file is supplied, against the live market line at that checkpoint.

WHY IT EXISTS BEFORE THE ENGINE. P3's ship gate is "beat the current vendored live projection on the same
games, state the margin and CI". The gate needs (a) a frozen, replayable baseline and (b) a population that
is the same for every candidate. Both are engine-independent, so they are built first; the native resumed
sim (P1 + P2) plugs in later as one more projector (`Projector` protocol below) without touching grading.

POPULATIONS ARE NEVER POOLED. ESPN season type 1 = preseason, 2 = regular, 3 = playoffs, 5 = play-in
(play-in is reported with playoffs). Every table is per (population, checkpoint) with its own n.

PROJECTORS SHIPPED HERE:
  pregame_rate     market prior: current score + the pregame line's share of the remaining regulation time.
                   The honest naive baseline; the native sim must beat it too.
  vendored_replay  the vendored tick's closed-form formulas (vendor/nba_betting_repo/app.py
                   `_live_lens_tick_payload` 44005, `_live_interp_cum_p50` 2164, `_scope_projection` 44167,
                   ATS blend ~44968, ML logistic ~45091) evaluated on as-of production SmartSim per-draw
                   quarter points (`--sim-draws`, the basketball-scenario-calibration recorder output).
                   FIDELITY: exact at quarter boundaries; at 5:00 Q4 the vendored 3-minute ladder is replaced
                   by linear interpolation between the Q3 and Q4 cumulative p50 (the recorder keeps quarter
                   points only); the ML pace rescale is omitted (no pregame pace in the recorder). Both are
                   stated in every report row as `fidelity`.
  espn_wp          ESPN's own published in-game home win probability at the checkpoint (ML only) -- an
                   external reference, never a candidate.

Usage:
  py -3 scripts/basketball_live_checkpoint_backtest.py fetch  --league nba --start 2025-10-02 --end 2026-06-20 \
        --cache C:/tmp/nba_live_bt/cache --read-cache C:/tmp/bball_sc/cache/nba
  py -3 scripts/basketball_live_checkpoint_backtest.py corpus --league nba --cache ... --read-cache ... \
        --out C:/tmp/nba_live_bt/games_nba.jsonl
  py -3 scripts/basketball_live_checkpoint_backtest.py grade  --games C:/tmp/nba_live_bt/games_nba.jsonl \
        --sim-draws C:/tmp/bball_sc/sim_nba --lines-cache C:/tmp/nba_bt/out/cache/oddsapi_hist/games \
        --baseline vendored_replay --out C:/tmp/nba_live_bt/report
Run research jobs at Idle priority (learnings: the fleet shares the host).
"""
from __future__ import annotations

import argparse
import dataclasses
import gzip
import json
import math
import random
import statistics
import sys
import time
import urllib.request
import zlib
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable, Mapping, Dict, Iterable, List, Optional, Protocol, Sequence, Tuple

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))  # the native_resim projector imports syndicate.features.nba.live_resim

ESPN_BASE = "https://site.web.api.espn.com/apis/site/v2/sports/basketball/{sport}/{kind}"


@dataclasses.dataclass(frozen=True)
class LeagueRules:
    """League clock parameters. ncaab hooks left for P4 (2 x 20-minute halves)."""

    key: str
    espn_sport: str
    periods: int
    period_seconds: int
    ot_seconds: int

    @property
    def regulation_seconds(self) -> int:
        return self.periods * self.period_seconds


LEAGUES: Dict[str, LeagueRules] = {
    "nba": LeagueRules("nba", "nba", 4, 720, 300),
    "wnba": LeagueRules("wnba", "wnba", 4, 600, 300),
    "ncaab": LeagueRules("ncaab", "mens-college-basketball", 2, 1200, 300),
}

POPULATION_BY_SEASON_TYPE = {1: "preseason", 2: "regular", 3: "postseason", 5: "postseason"}


# ----------------------------------------------------------------------------------------------- fetch / cache

def _http_json(url: str, tries: int = 3) -> Dict[str, Any]:
    last: Optional[Exception] = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"GET failed {url}: {last}")


def _read_gz(path: Path) -> Dict[str, Any]:
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return json.load(fh)


def _cached(name: str, url: str, cache: Path, read_caches: Sequence[Path], *, fetch: bool = True) -> Optional[Dict[str, Any]]:
    for root in (cache, *read_caches):
        p = root / name
        if p.exists():
            return _read_gz(p)
    if not fetch:
        return None
    doc = _http_json(url)
    p = cache / name
    p.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(p, "wt", encoding="utf-8") as fh:
        json.dump(doc, fh)
    return doc


def completed_events(rules: LeagueRules, day: str, cache: Path, read_caches: Sequence[Path], *, fetch: bool = True) -> List[Dict[str, Any]]:
    """Completed games on one date, ALL season types (1 preseason, 2 regular, 3 playoffs, 5 play-in).

    A scoreboard is only cached once every game on it is final, so a re-run on today's date re-fetches."""
    ymd = day.replace("-", "")
    name = f"scoreboard_{ymd}.json.gz"
    url = ESPN_BASE.format(sport=rules.espn_sport, kind="scoreboard") + f"?dates={ymd}"
    sb = None
    for root in (cache, *read_caches):
        if (root / name).exists():
            sb = _read_gz(root / name)
            break
    if sb is not None and not _scoreboard_all_final(sb) and fetch:
        sb = None
    if sb is None:
        if not fetch:
            return []
        sb = _http_json(url)
        if _scoreboard_all_final(sb):
            (cache).mkdir(parents=True, exist_ok=True)
            with gzip.open(cache / name, "wt", encoding="utf-8") as fh:
                json.dump(sb, fh)
    out = []
    for e in sb.get("events") or []:
        st = ((e.get("status") or {}).get("type")) or {}
        stype = int(((e.get("season") or {}).get("type")) or 0)
        if (st.get("completed") or str(st.get("state")) == "post") and stype in POPULATION_BY_SEASON_TYPE:
            out.append({"id": str(e.get("id")), "date": day, "season_type": stype})
    return out


def _scoreboard_all_final(sb: Dict[str, Any]) -> bool:
    evs = sb.get("events") or []
    return bool(evs) and all(
        (((e.get("status") or {}).get("type")) or {}).get("completed") for e in evs
    )


def _daterange(start: str, end: str) -> Iterable[str]:
    d, d1 = date.fromisoformat(start), date.fromisoformat(end)
    while d <= d1:
        yield d.isoformat()
        d += timedelta(days=1)


def run_fetch(args: argparse.Namespace) -> int:
    rules = LEAGUES[args.league]
    cache, reads = Path(args.cache), [Path(p) for p in args.read_cache or []]
    n_ev = n_new = fails = 0
    for day in _daterange(args.start, args.end):
        try:
            evs = completed_events(rules, day, cache, reads)
        except Exception as exc:  # noqa: BLE001
            print(f"SCOREBOARD_FAIL {day} {exc}", flush=True)
            continue
        for ev in evs:
            n_ev += 1
            name = f"summary_{ev['id']}.json.gz"
            if any((r / name).exists() for r in (cache, *reads)):
                continue
            try:
                _cached(name, ESPN_BASE.format(sport=rules.espn_sport, kind="summary") + f"?event={ev['id']}", cache, reads)
                n_new += 1
            except Exception as exc:  # noqa: BLE001
                fails += 1
                print(f"SUMMARY_FAIL {ev['id']} {exc}", flush=True)
    print(f"FETCH league={args.league} events={n_ev} new_summaries={n_new} fails={fails}", flush=True)
    return 0 if fails == 0 else 3


# ----------------------------------------------------------------------------------------------- pbp parsing

@dataclasses.dataclass
class Play:
    """One pbp row, reduced to what the harness and the situation targets read."""

    period: int
    clock_s: float
    elapsed_s: float
    home: int
    away: int
    kind: str  # shot | ft | foul | ofoul | sub | timeout | turnover | rebound_o | rebound_d | end_period | other
    team: str  # "home" | "away" | ""
    made: bool
    points: int
    p1: str  # first participant (shooter / fouler / player ENTERING on a sub)
    p2: str  # second participant (player LEAVING on a sub)
    text: str
    wallclock: str


@dataclasses.dataclass
class PbpGame:
    league: str
    event_id: str
    date: str
    season_type: int
    home: str
    away: str
    home_team_id: str
    away_team_id: str
    final_home: int
    final_away: int
    period_points: List[Tuple[int, int]]  # per period incl. OT, (home, away)
    starters: Dict[str, List[str]]  # side -> athlete ids
    athlete_side: Dict[str, str]  # athlete id -> side
    box_minutes: Dict[str, float]  # athlete id -> official minutes
    plays: List[Play]
    winprob: Dict[int, float]  # play index -> ESPN home win %, aligned to self.plays
    pickcenter: Dict[str, float]  # spread (home), total, from ESPN pregame pickcenter when present

    @property
    def population(self) -> str:
        return POPULATION_BY_SEASON_TYPE.get(self.season_type, "other")

    def to_json(self) -> Dict[str, Any]:
        d = dataclasses.asdict(self)
        d["plays"] = [dataclasses.astuple(p) for p in self.plays]
        d["winprob"] = {str(k): v for k, v in self.winprob.items()}
        return d

    @classmethod
    def from_json(cls, d: Dict[str, Any]) -> "PbpGame":
        d = dict(d)
        d["plays"] = [Play(*p) for p in d["plays"]]
        d["period_points"] = [tuple(x) for x in d["period_points"]]
        d["winprob"] = {int(k): float(v) for k, v in (d.get("winprob") or {}).items()}
        return cls(**d)


def clock_seconds(text: Any) -> Optional[float]:
    s = str(text or "").strip()
    if not s:
        return None
    try:
        if ":" in s:
            m, sec = s.split(":", 1)
            return int(m) * 60 + float(sec)
        return float(s)
    except ValueError:
        return None


def elapsed_seconds(rules: LeagueRules, period: int, clock_s: float) -> float:
    if period <= rules.periods:
        return (period - 1) * rules.period_seconds + (rules.period_seconds - clock_s)
    return rules.regulation_seconds + (period - rules.periods - 1) * rules.ot_seconds + (rules.ot_seconds - clock_s)


def classify_play(type_text: str, text: str, scoring: bool, shooting: bool) -> str:
    t = (type_text or "").lower()
    if t == "substitution":
        return "sub"
    if "timeout" in t:
        return "timeout"
    if t.startswith("end period") or t == "end game":
        return "end_period"
    if t.startswith("free throw"):
        return "ft"
    if "rebound" in t:
        return "rebound_o" if "offensive" in t else "rebound_d"
    if "turnover" in t:
        return "turnover"
    if "foul" in t:
        if "technical" in t or "flagrant foul type 2" in t:
            return "other"
        if "offensive" in t:
            return "ofoul"
        return "foul"
    if shooting:
        return "shot"
    return "other"


def parse_summary(summary: Dict[str, Any], league: str, event: Dict[str, Any]) -> Optional[PbpGame]:
    rules = LEAGUES[league]
    comp = ((summary.get("header") or {}).get("competitions") or [{}])[0]
    teams = {c.get("homeAway"): c for c in comp.get("competitors") or []}
    if "home" not in teams or "away" not in teams:
        return None
    side_by_team = {str(teams[s]["team"]["id"]): s for s in ("home", "away")}
    final = {s: int(float(teams[s].get("score") or 0)) for s in ("home", "away")}
    ls = {s: [int(float(x.get("displayValue") or 0)) for x in teams[s].get("linescores") or []] for s in ("home", "away")}
    if len(ls["home"]) < rules.periods or len(ls["home"]) != len(ls["away"]):
        return None
    period_points = list(zip(ls["home"], ls["away"]))

    starters: Dict[str, List[str]] = {"home": [], "away": []}
    athlete_side: Dict[str, str] = {}
    box_minutes: Dict[str, float] = {}
    for team_block in (summary.get("boxscore") or {}).get("players") or []:
        side = side_by_team.get(str((team_block.get("team") or {}).get("id")))
        if not side:
            continue
        for stat in team_block.get("statistics") or []:
            names = stat.get("names") or []
            mi = names.index("MIN") if "MIN" in names else None
            for a in stat.get("athletes") or []:
                aid = str((a.get("athlete") or {}).get("id") or "")
                if not aid:
                    continue
                athlete_side[aid] = side
                if a.get("starter"):
                    starters[side].append(aid)
                vals = a.get("stats") or []
                if mi is not None and mi < len(vals):
                    try:
                        box_minutes[aid] = float(vals[mi])
                    except (TypeError, ValueError):
                        pass

    plays: List[Play] = []
    id_to_index: Dict[str, int] = {}
    for raw in summary.get("plays") or []:
        period = int(((raw.get("period") or {}).get("number")) or 0)
        cs = clock_seconds((raw.get("clock") or {}).get("displayValue"))
        if period <= 0 or cs is None:
            continue
        typ = str(((raw.get("type") or {}).get("text")) or "")
        kind = classify_play(typ, str(raw.get("text") or ""), bool(raw.get("scoringPlay")), bool(raw.get("shootingPlay")))
        parts = [str((p.get("athlete") or {}).get("id") or "") for p in raw.get("participants") or []]
        team = side_by_team.get(str((raw.get("team") or {}).get("id") or ""), "")
        made = bool(raw.get("scoringPlay"))
        plays.append(Play(
            period=period, clock_s=cs, elapsed_s=elapsed_seconds(rules, period, cs),
            home=int(raw.get("homeScore") or 0), away=int(raw.get("awayScore") or 0),
            kind=kind, team=team, made=made, points=int(raw.get("scoreValue") or 0) if made else 0,
            p1=parts[0] if parts else "", p2=parts[1] if len(parts) > 1 else "",
            text=str(raw.get("text") or "")[:160], wallclock=str(raw.get("wallclock") or ""),
        ))
        id_to_index[str(raw.get("id"))] = len(plays) - 1
    if not plays:
        return None
    winprob = {}
    for w in summary.get("winprobability") or []:
        i = id_to_index.get(str(w.get("playId")))
        if i is not None and w.get("homeWinPercentage") is not None:
            winprob[i] = float(w["homeWinPercentage"])
    pick: Dict[str, float] = {}
    for pc in summary.get("pickcenter") or []:
        try:
            if pc.get("spread") is not None and "spread" not in pick:
                # ESPN `spread` is quoted for the home team ("ATL -1.5" with ATL home -> -1.5)
                pick["spread"] = float(pc["spread"])
            if pc.get("overUnder") is not None and "total" not in pick:
                pick["total"] = float(pc["overUnder"])
        except (TypeError, ValueError):
            continue
    return PbpGame(
        league=league, event_id=str(event["id"]), date=str(event["date"]), season_type=int(event["season_type"]),
        home=str(teams["home"]["team"].get("abbreviation") or ""), away=str(teams["away"]["team"].get("abbreviation") or ""),
        home_team_id=str(teams["home"]["team"]["id"]), away_team_id=str(teams["away"]["team"]["id"]),
        final_home=final["home"], final_away=final["away"], period_points=period_points,
        starters=starters, athlete_side=athlete_side, box_minutes=box_minutes,
        plays=plays, winprob=winprob, pickcenter=pick,
    )


def run_corpus(args: argparse.Namespace) -> int:
    rules = LEAGUES[args.league]
    cache, reads = Path(args.cache), [Path(p) for p in args.read_cache or []]
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    n = skipped = 0
    by_pop: Dict[str, int] = defaultdict(int)
    with out.open("w", encoding="utf-8") as fh:
        for day in _daterange(args.start, args.end):
            for ev in completed_events(rules, day, cache, reads, fetch=False):
                s = _cached(f"summary_{ev['id']}.json.gz", "", cache, reads, fetch=False)
                g = parse_summary(s, args.league, ev) if s else None
                if g is None:
                    skipped += 1
                    continue
                fh.write(json.dumps(g.to_json()) + "\n")
                n += 1
                by_pop[g.population] += 1
    print(f"CORPUS league={args.league} games={n} skipped={skipped} by_population={dict(by_pop)}", flush=True)
    return 0


def load_games(path: Path) -> List[PbpGame]:
    with path.open(encoding="utf-8") as fh:
        return [PbpGame.from_json(json.loads(ln)) for ln in fh if ln.strip()]


# ----------------------------------------------------------------------------------------------- checkpoint state

CHECKPOINTS: Dict[str, Tuple[int, float]] = {
    # name -> (period, clock seconds remaining in that period); state INCLUDES every play at that clock
    "end_q1": (1, 0.0),
    "end_q2": (2, 0.0),
    "end_q3": (3, 0.0),
    "q4_5min": (4, 300.0),
}


@dataclasses.dataclass
class CheckpointState:
    """Historical game state at a checkpoint -- the backtest's stand-in for P2's LiveGameState.

    Kept deliberately to fields P2 also promises (period, clock, score, team fouls, player PF, timeouts),
    so a native projector written against LiveGameState maps onto it one-to-one."""

    checkpoint: str
    period: int
    clock_s: float
    elapsed_s: float
    remaining_regulation_s: float
    home: int
    away: int
    period_points_so_far: List[Tuple[int, int]]  # completed periods + the current partial one
    team_fouls_period: Dict[str, int]
    player_fouls: Dict[str, int]
    timeouts_used: Dict[str, int]
    last_play_index: int
    wallclock: str

    @property
    def margin(self) -> int:
        return self.home - self.away

    @property
    def total(self) -> int:
        return self.home + self.away


def state_at(game: PbpGame, checkpoint: str, rules: Optional[LeagueRules] = None) -> Optional[CheckpointState]:
    rules = rules or LEAGUES[game.league]
    period, clock = CHECKPOINTS[checkpoint]
    last = -1
    for i, p in enumerate(game.plays):
        if p.period < period or (p.period == period and p.clock_s >= clock):
            last = i
        elif p.period > period:
            break
    if last < 0:
        return None
    incl = game.plays[: last + 1]
    if not any(p.period == period for p in incl):
        return None  # the period never started in the feed
    cur = incl[-1]
    fouls_period = {"home": 0, "away": 0}
    pf: Dict[str, int] = defaultdict(int)
    tos = {"home": 0, "away": 0}
    for p in incl:
        if p.kind in ("foul", "ofoul") and p.p1:
            pf[p.p1] += 1
            if p.kind == "foul" and p.period == period and p.team in fouls_period:
                fouls_period[p.team] += 1
        if p.kind == "timeout" and p.team in tos:
            tos[p.team] += 1
    # Per-period points so far, from the cumulative score at each period's last included play.
    pps: List[Tuple[int, int]] = []
    prev = (0, 0)
    for q in range(1, period + 1):
        rows = [p for p in incl if p.period == q]
        if not rows:
            break
        endq = (rows[-1].home, rows[-1].away)
        pps.append((endq[0] - prev[0], endq[1] - prev[1]))
        prev = endq
    elapsed = elapsed_seconds(rules, period, clock)
    return CheckpointState(
        checkpoint=checkpoint, period=period, clock_s=clock, elapsed_s=elapsed,
        remaining_regulation_s=max(0.0, rules.regulation_seconds - elapsed),
        home=cur.home, away=cur.away, period_points_so_far=pps,
        team_fouls_period=fouls_period, player_fouls=dict(pf), timeouts_used=tos,
        last_play_index=last, wallclock=cur.wallclock,
    )


def state_is_consistent(game: PbpGame, st: CheckpointState) -> bool:
    """The pbp running score must agree with ESPN's official linescore for every COMPLETED period."""
    for q, (h, a) in enumerate(st.period_points_so_far[: st.period - (0 if st.clock_s == 0 else 1)]):
        if q >= len(game.period_points) or (h, a) != tuple(game.period_points[q]):
            return False
    return True


# ----------------------------------------------------------------------------------------------- targets (truth)

@dataclasses.dataclass
class Truth:
    final_total: int
    final_margin: int
    home_win: int
    went_ot: int
    next_period_total: Optional[int]  # the period AFTER the checkpoint's period (None after Q4)
    current_period_total: Optional[int]  # the checkpoint's own period, full -- None at a period end (already known)
    second_half_total: Optional[int]  # Q3+Q4 PLUS OT (books settle 2H incl. OT) -- None once H1 is over (== total)
    first_half_total: int


def truth_for(game: PbpGame, st: CheckpointState, rules: LeagueRules) -> Truth:
    pp = game.period_points
    reg = pp[: rules.periods]
    half = rules.periods // 2
    nxt = st.period  # 0-based index of the next period
    return Truth(
        final_total=game.final_home + game.final_away,
        final_margin=game.final_home - game.final_away,
        home_win=1 if game.final_home > game.final_away else 0,
        went_ot=1 if len(pp) > rules.periods else 0,
        next_period_total=(sum(pp[nxt]) if nxt < rules.periods and st.clock_s == 0 else None),
        current_period_total=sum(pp[st.period - 1]) if st.clock_s > 0 else None,
        second_half_total=sum(sum(x) for x in pp[half:]) if st.period < half else None,
        first_half_total=sum(sum(x) for x in reg[:half]),
    )


# ----------------------------------------------------------------------------------------------- pregame inputs

@dataclasses.dataclass
class Pregame:
    spread_home: Optional[float]  # home handicap, negative = home favoured
    total: Optional[float]
    p_home_ml: Optional[float]
    source: str
    sim: Optional["SimSummary"] = None


@dataclasses.dataclass
class SimSummary:
    """What the vendored tick reads from smart_sim_<date>_<H>_<A>.json, rebuilt from per-draw quarter points."""

    total_mean: float
    margin_mean: float
    p_home_win: float
    cum_p50_by_quarter_end: List[float]  # minute 12, 24, 36, 48 (cumulative game total p50)
    quarter_p50: List[float]  # per-quarter game-total p50 (vendored quarter scope = cum(end)-cum(start))
    n_draws: int


def summarize_draws(draws: List[Dict[str, Any]]) -> Optional[SimSummary]:
    if not draws:
        return None
    totals, margins, wins = [], [], []
    cum = [[] for _ in range(4)]
    qs = [[] for _ in range(4)]
    for d in draws:
        hq, aq = d.get("hq") or [], d.get("aq") or []
        if len(hq) < 4 or len(aq) < 4:
            continue
        h = sum(hq) + int(d.get("hot") or 0)
        a = sum(aq) + int(d.get("aot") or 0)
        totals.append(h + a)
        margins.append(h - a)
        wins.append(1.0 if h > a else (0.5 if h == a else 0.0))
        run = 0
        for q in range(4):
            run += hq[q] + aq[q]
            cum[q].append(run)
            qs[q].append(hq[q] + aq[q])
    if not totals:
        return None
    return SimSummary(
        total_mean=statistics.fmean(totals), margin_mean=statistics.fmean(margins), p_home_win=statistics.fmean(wins),
        cum_p50_by_quarter_end=[statistics.median(c) for c in cum], quarter_p50=[statistics.median(q) for q in qs],
        n_draws=len(totals),
    )


def load_sim_draws(sim_dir: Optional[Path]) -> Dict[Tuple[str, str, str], SimSummary]:
    out: Dict[Tuple[str, str, str], SimSummary] = {}
    if not sim_dir or not sim_dir.exists():
        return out
    for f in sorted(sim_dir.glob("*.jsonl")):
        with f.open(encoding="utf-8") as fh:
            for ln in fh:
                if not ln.strip():
                    continue
                r = json.loads(ln)
                s = summarize_draws(r.get("draws") or [])
                if s:
                    out[(str(r["date"]), str(r["home"]).upper(), str(r["away"]).upper())] = s
    return out


# OddsAPI full team names -> ESPN abbreviations (ESPN uses GS/NY/SA/NO/UTAH/WSH).
ODDSAPI_TO_ESPN = {
    "Atlanta Hawks": "ATL", "Boston Celtics": "BOS", "Brooklyn Nets": "BKN", "Charlotte Hornets": "CHA",
    "Chicago Bulls": "CHI", "Cleveland Cavaliers": "CLE", "Dallas Mavericks": "DAL", "Denver Nuggets": "DEN",
    "Detroit Pistons": "DET", "Golden State Warriors": "GS", "Houston Rockets": "HOU", "Indiana Pacers": "IND",
    "Los Angeles Clippers": "LAC", "Los Angeles Lakers": "LAL", "Memphis Grizzlies": "MEM", "Miami Heat": "MIA",
    "Milwaukee Bucks": "MIL", "Minnesota Timberwolves": "MIN", "New Orleans Pelicans": "NO", "New York Knicks": "NY",
    "Oklahoma City Thunder": "OKC", "Orlando Magic": "ORL", "Philadelphia 76ers": "PHI", "Phoenix Suns": "PHX",
    "Portland Trail Blazers": "POR", "Sacramento Kings": "SAC", "San Antonio Spurs": "SA", "Toronto Raptors": "TOR",
    "Utah Jazz": "UTAH", "Washington Wizards": "WSH",
}
# The sim recorder used NBA tricodes; map ESPN -> tricode for the join.
ESPN_TO_TRI = {"GS": "GSW", "NY": "NYK", "SA": "SAS", "NO": "NOP", "UTAH": "UTA", "WSH": "WAS"}


def _devig(a: Optional[float], b: Optional[float]) -> Optional[float]:
    def imp(o: Optional[float]) -> Optional[float]:
        if o is None:
            return None
        return 100.0 / (o + 100.0) if o > 0 else -o / (-o + 100.0)

    pa, pb = imp(a), imp(b)
    if pa is None or pb is None or pa + pb <= 0:
        return None
    return pa / (pa + pb)


def load_pregame_lines(lines_dir: Optional[Path]) -> Dict[Tuple[str, str, str], Dict[str, float]]:
    """(date, ESPN home, ESPN away) -> modal spread/total line + mean de-vigged home ML, from OddsAPI pre-tip
    snapshots (the backtest_nba_lines_props cache: one snapshot per date before the first tip)."""
    out: Dict[Tuple[str, str, str], Dict[str, float]] = {}
    if not lines_dir or not lines_dir.exists():
        return out
    for f in sorted(lines_dir.glob("*.json")):
        d = f.stem
        try:
            payload = json.loads(f.read_text(encoding="utf-8"))
        except ValueError:
            continue
        for ev in payload.get("data") or []:
            h, a = ODDSAPI_TO_ESPN.get(ev.get("home_team", "")), ODDSAPI_TO_ESPN.get(ev.get("away_team", ""))
            if not h or not a:
                continue
            out[(d, h, a)] = _consensus(ev)
    return out


def _consensus(ev: Dict[str, Any]) -> Dict[str, float]:
    ml: List[float] = []
    sp: Dict[float, int] = defaultdict(int)
    tt: Dict[float, int] = defaultdict(int)
    for bk in ev.get("bookmakers") or []:
        for mk in bk.get("markets") or []:
            oc = {o.get("name"): o for o in mk.get("outcomes") or []}
            if mk.get("key") == "h2h":
                p = _devig((oc.get(ev["home_team"]) or {}).get("price"), (oc.get(ev["away_team"]) or {}).get("price"))
                if p is not None:
                    ml.append(p)
            elif mk.get("key") == "spreads" and (oc.get(ev["home_team"]) or {}).get("point") is not None:
                sp[float(oc[ev["home_team"]]["point"])] += 1
            elif mk.get("key") == "totals" and (oc.get("Over") or {}).get("point") is not None:
                tt[float(oc["Over"]["point"])] += 1
    rec: Dict[str, float] = {}
    if ml:
        rec["p_home_ml"] = statistics.fmean(ml)
    if sp:
        rec["spread"] = max(sp, key=lambda k: (sp[k], -abs(k)))
    if tt:
        rec["total"] = max(tt, key=lambda k: tt[k])
    return rec


def pregame_for(game: PbpGame, lines: Dict[Tuple[str, str, str], Dict[str, float]],
                sims: Dict[Tuple[str, str, str], SimSummary]) -> Pregame:
    rec = lines.get((game.date, game.home, game.away))
    if rec is None:
        # OddsAPI dates are the UTC snapshot day; ESPN dates are the US slate day. Try the next UTC day.
        nd = (date.fromisoformat(game.date) + timedelta(days=1)).isoformat()
        rec = lines.get((nd, game.home, game.away))
    source = "oddsapi_pretip"
    if not rec or "total" not in rec or "spread" not in rec:
        rec = dict(game.pickcenter) if game.pickcenter else {}
        source = "espn_pickcenter" if rec else "none"
    sim = sims.get((game.date, ESPN_TO_TRI.get(game.home, game.home), ESPN_TO_TRI.get(game.away, game.away)))
    return Pregame(spread_home=rec.get("spread"), total=rec.get("total"), p_home_ml=rec.get("p_home_ml"), source=source, sim=sim)


# ----------------------------------------------------------------------------------------------- projectors

@dataclasses.dataclass
class Projection:
    total: Optional[float] = None
    margin: Optional[float] = None  # home - away, final incl. OT
    p_home: Optional[float] = None
    next_period_total: Optional[float] = None
    current_period_total: Optional[float] = None
    second_half_total: Optional[float] = None
    first_half_total: Optional[float] = None
    fidelity: str = "exact"
    refusal: Optional[str] = None  # a NAMED reason; a refused projection is graded as missing, never imputed
    total_dist: Optional[Dict[str, int]] = None  # {value: count}, full game incl. OT (sim projectors only)
    margin_dist: Optional[Dict[str, int]] = None


class Projector(Protocol):
    name: str

    def project(self, game: PbpGame, st: CheckpointState, pre: Pregame, rules: LeagueRules) -> Projection: ...


def _phi(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


class PregameRateProjector:
    """Current score + the pregame line's pro-rata share of the remaining regulation time.

    Margin SD for ML: `margin_sd_full` * sqrt(remaining fraction) -- a stated constant, not fitted here."""

    name = "pregame_rate"

    def __init__(self, margin_sd_full: float = 13.5) -> None:
        self.margin_sd_full = margin_sd_full

    def project(self, game, st, pre, rules):
        if pre.total is None or pre.spread_home is None:
            return Projection(refusal="no_pregame_line")
        f = st.remaining_regulation_s / rules.regulation_seconds
        exp_margin = -pre.spread_home
        margin = st.margin + exp_margin * f
        sd = self.margin_sd_full * math.sqrt(max(f, 1e-6))
        per_period = pre.total / rules.periods
        half = rules.periods // 2
        cur_done = sum(st.period_points_so_far[-1]) if st.period_points_so_far else 0
        cur_left = st.clock_s / rules.period_seconds
        return Projection(
            total=st.total + pre.total * f,
            margin=margin,
            p_home=_phi(margin / sd) if f > 0 else (1.0 if st.margin > 0 else 0.0 if st.margin < 0 else 0.5),
            next_period_total=per_period if st.clock_s == 0 and st.period < rules.periods else None,
            current_period_total=cur_done + per_period * cur_left,
            second_half_total=(sum(sum(x) for x in st.period_points_so_far[half:]) + per_period * (
                (rules.regulation_seconds - max(st.elapsed_s, half * rules.period_seconds)) / rules.period_seconds)),
            first_half_total=(sum(sum(x) for x in st.period_points_so_far[:half]) + per_period * max(
                0.0, (half * rules.period_seconds - st.elapsed_s) / rules.period_seconds)),
        )


class VendoredReplayProjector:
    """The vendored tick's formulas, replayed. Line refs: vendor/nba_betting_repo/app.py."""

    name = "vendored_replay"

    def project(self, game, st, pre, rules):
        sim = pre.sim
        if sim is None:
            return Projection(refusal="no_sim_draws")
        if rules.key != "nba":
            return Projection(refusal="vendored_replay_nba_only")
        el_min = min(48.0, st.elapsed_s / 60.0)
        fidelity = "exact" if st.clock_s == 0 else "quarter_ladder_interp"

        def cum(t_min: float) -> float:
            # _live_interp_cum_p50 (2164) on a ladder known at quarter ends only.
            t = max(0.0, min(48.0, t_min))
            if t <= 0:
                return 0.0
            k = t / 12.0
            lo = int(math.floor(k))
            lo_v = 0.0 if lo == 0 else sim.cum_p50_by_quarter_end[lo - 1]
            if lo >= 4:
                return sim.cum_p50_by_quarter_end[3]
            hi_v = sim.cum_p50_by_quarter_end[lo]
            return lo_v + (k - lo) * (hi_v - lo_v)

        def scope(start: float, end: float, elapsed_scope: float, actual: float) -> float:
            # _scope_projection (44167): max(actual, actual + (sim_final - sim_at))
            s0 = cum(start)
            sim_at = cum(start + elapsed_scope) - s0
            sim_final = cum(end) - s0
            return max(actual, actual + (sim_final - sim_at))

        total = scope(0.0, 48.0, el_min, st.total)
        # ATS (~44968): w = elapsed/48; adj = (1-w)*margin_mean + w*current margin
        w = max(0.0, min(1.0, el_min / 48.0))
        margin = (1 - w) * sim.margin_mean + w * st.margin
        # ML (~45091): logistic(margin / (6 + 0.35*min_left)) blended with the pregame p_home_win.
        # The pace rescale is omitted: the recorder carries no pregame pace (stated in `fidelity`).
        min_left = max(0.0, 48.0 - el_min)
        p_score = 1.0 / (1.0 + math.exp(-st.margin / (6.0 + 0.35 * min_left)))
        p_home = (1 - w) * sim.p_home_win + w * p_score
        q = st.period
        cur_actual = sum(st.period_points_so_far[-1]) if st.period_points_so_far else 0
        el_q = max(0.0, min(12.0, 12.0 - st.clock_s / 60.0))
        cur_q = scope((q - 1) * 12.0, q * 12.0, el_q, cur_actual)
        nxt = scope(q * 12.0, (q + 1) * 12.0, 0.0, 0.0) if st.clock_s == 0 and q < 4 else None
        # Vendored has a first-half market only (p<=2); the 2H value is the same scope formula over 24..48,
        # labelled as an analog.
        h_el = max(0.0, el_min - 24.0)
        h2_actual = sum(sum(x) for x in st.period_points_so_far[2:])
        h2 = scope(24.0, 48.0, h_el, h2_actual)
        h1_actual = sum(sum(x) for x in st.period_points_so_far[:2])
        h1 = scope(0.0, 24.0, min(el_min, 24.0), h1_actual)
        return Projection(total=total, margin=margin, p_home=p_home, next_period_total=nxt,
                          current_period_total=cur_q, second_half_total=h2, first_half_total=h1,
                          fidelity=fidelity + "+no_pace_rescale+h2_analog")


class EspnWinProbProjector:
    name = "espn_wp"

    def project(self, game, st, pre, rules):
        idx = [i for i in game.winprob if i <= st.last_play_index]
        if not idx:
            return Projection(refusal="no_espn_winprob")
        return Projection(p_home=game.winprob[max(idx)], fidelity="external_reference")


def truncate_summary(summary: Dict[str, Any], checkpoint: str) -> Dict[str, Any]:
    """The ESPN summary AS IT WOULD HAVE LOOKED LIVE at `checkpoint`: plays cut at the checkpoint (inclusive
    of every play at that clock, the same rule as `state_at`), header score set to the last kept play's
    running score, linescores cut to the periods begun, status `in`. Box-score fields are kept: P2 reads
    names/starters from them and fouls from the plays, never final box stats."""
    import copy

    period, clock = CHECKPOINTS[checkpoint]
    kept: List[Dict[str, Any]] = []
    for raw in summary.get("plays") or []:
        p = int(((raw.get("period") or {}).get("number")) or 0)
        cs = clock_seconds((raw.get("clock") or {}).get("displayValue"))
        if p and cs is not None and (p > period or (p == period and cs < clock)):
            break
        kept.append(raw)
    out = copy.deepcopy({k: v for k, v in summary.items() if k not in ("plays", "winprobability")})
    out["plays"] = copy.deepcopy(kept)
    last = kept[-1] if kept else {}
    score = {"home": int(last.get("homeScore") or 0), "away": int(last.get("awayScore") or 0)}
    cum = {"home": [], "away": []}
    for q in range(1, period + 1):
        rows = [r for r in kept if int(((r.get("period") or {}).get("number")) or 0) == q]
        if rows:
            cum["home"].append(int(rows[-1].get("homeScore") or 0))
            cum["away"].append(int(rows[-1].get("awayScore") or 0))
    comp = ((out.get("header") or {}).get("competitions") or [{}])[0]
    for c in comp.get("competitors") or []:
        side = c.get("homeAway")
        if side in score:
            c["score"] = str(score[side])
            per = [b - a for a, b in zip([0] + cum[side][:-1], cum[side])]
            c["linescores"] = [{"displayValue": str(x), "value": float(x)} for x in per]
    status_type = {"id": "2", "name": "STATUS_IN_PROGRESS", "state": "in", "completed": False,
                   "description": "In Progress", "detail": "In Progress", "shortDetail": "In Progress"}
    if isinstance(comp.get("status"), dict):
        comp["status"]["type"] = dict(status_type)
    else:
        comp["status"] = {"type": dict(status_type)}
    return out


def index_engine_inputs(root: Optional[Path]) -> Dict[Tuple[str, str, str], Path]:
    """(date, HOME tricode, AWAY tricode) -> pickle, for both the production persist format
    (`engine_inputs/<date>/<H>_<A>.pkl`) and P1's recorded corpus (`<league>_<date>_<n>_<h>v<a>.pkl`)."""
    import pickle

    out: Dict[Tuple[str, str, str], Path] = {}
    if not root or not root.exists():
        return out
    for f in sorted(root.rglob("*.pkl")):
        try:
            with f.open("rb") as fh:
                doc = pickle.load(fh)
            kw = doc.get("kwargs") or {}
            h = str(kw["home_players"]["team"].iloc[0]).upper()
            a = str(kw["away_players"]["team"].iloc[0]).upper()
            out[(str(doc.get("date")), h, a)] = f
        except Exception:  # noqa: BLE001 -- an unreadable pickle is simply not indexed
            continue
    return out


class NativeResimProjector:
    """The P3 live re-sim, run through `syndicate.features.nba.live_resim` exactly as the live tick runs it
    (resume_from_summary -> map_state_names -> resim_live_game), on a summary cut at the checkpoint and the
    game's recorded pregame engine inputs. Nothing about the resume is re-implemented here."""

    name = "native_resim"

    def __init__(self, *, inputs_root: Optional[Path] = None, summary_caches: Sequence[Path] = (),
                 sims: int = 100, cache_dir: Optional[Path] = None) -> None:
        self.inputs = index_engine_inputs(inputs_root)
        self.summary_caches = list(summary_caches)
        self.sims = sims
        # Per (game, checkpoint) results, so `--shard i/n` processes can fill it in parallel and one final grade run
        # reads it without simulating. Keyed on the inputs file's size+mtime and the sim count: a re-recorded input
        # or a different N never reuses a stale projection.
        self.cache_dir = cache_dir

    def _cache_path(self, game, checkpoint: str, inputs_path: Path) -> Optional[Path]:
        if self.cache_dir is None:
            return None
        st = inputs_path.stat()
        tag = f"{game.event_id}_{checkpoint}_n{self.sims}_{st.st_size}_{int(st.st_mtime)}"
        return self.cache_dir / f"{tag}.json"

    def _summary(self, event_id: str) -> Optional[Dict[str, Any]]:
        for root in self.summary_caches:
            p = root / f"summary_{event_id}.json.gz"
            if p.exists():
                return _read_gz(p)
        return None

    def project(self, game, st, pre, rules):
        import pickle

        from syndicate.features.nba import live_resim as lr

        if rules.key != "nba":
            return Projection(refusal="native_resim_nba_only")
        key = (game.date, ESPN_TO_TRI.get(game.home, game.home), ESPN_TO_TRI.get(game.away, game.away))
        path = self.inputs.get(key)
        if path is None:
            return Projection(refusal="no_pregame_inputs")
        cpath = self._cache_path(game, st.checkpoint, path)
        if cpath is not None and cpath.exists():
            return Projection(**json.loads(cpath.read_text(encoding="utf-8")))
        proj = self._project_uncached(game, st, rules, path)
        if cpath is not None:
            cpath.parent.mkdir(parents=True, exist_ok=True)
            tmp = cpath.with_suffix(".tmp")
            tmp.write_text(json.dumps(dataclasses.asdict(proj)), encoding="utf-8")
            tmp.replace(cpath)
        return proj

    def _project_uncached(self, game, st, rules, path):
        import pickle

        from syndicate.features.nba import live_resim as lr

        summary = self._summary(game.event_id)
        if summary is None:
            return Projection(refusal="no_summary")
        resumed = lr.resume_from_summary(truncate_summary(summary, st.checkpoint), date=game.date)
        if isinstance(resumed, lr.NbaResimRefusal):
            return Projection(refusal=resumed.reason)
        _state, gs, facts = resumed
        with path.open("rb") as fh:
            inputs = dict(pickle.load(fh)["kwargs"])
        gs, _match = lr.map_state_names(gs, inputs["home_players"], inputs["away_players"])
        res = lr.resim_live_game(inputs, gs, sims=self.sims, base_seed=lr.stable_seed(facts.event_id, facts.last_seq))
        if isinstance(res, lr.NbaResimRefusal):
            return Projection(refusal=res.reason)
        seg = res.get("segments") or {}
        q = st.period
        nxt = (seg.get(f"q{q + 1}") or {}).get("total_mean") if st.clock_s == 0 and q < rules.periods else None
        cur = (seg.get(f"q{q}") or {}).get("total_mean") if st.clock_s > 0 else None
        h1 = (seg.get("h1") or {}).get("total_mean")
        return Projection(
            total=res["total_mean"], margin=res["home_margin_mean"], p_home=res["home_win_prob"],
            next_period_total=nxt, current_period_total=cur,
            second_half_total=(res["total_mean"] - h1) if (h1 is not None and st.period < rules.periods // 2) else None,
            fidelity=f"native_resim_{res['sims_run']}sims", total_dist=res["total_dist"], margin_dist=res["margin_dist"],
        )


PROJECTORS: Dict[str, Callable[[], Projector]] = {
    "pregame_rate": PregameRateProjector,
    "vendored_replay": VendoredReplayProjector,
    "espn_wp": EspnWinProbProjector,
}


# ----------------------------------------------------------------------------------------------- live close

ODDSAPI_HIST = ("https://api.the-odds-api.com/v4/historical/sports/{sport}/odds?apiKey={key}&regions=us"
                "&markets=h2h,spreads,totals&oddsFormat=american&date={ts}")
ODDSAPI_SPORT = {"nba": "basketball_nba", "wnba": "basketball_wnba", "ncaab": "basketball_ncaab"}
# Measured 2026-10-09 (one probe): x-requests-last = 30 for 3 markets x 1 region.
CREDITS_PER_SNAPSHOT = 30


def _parse_iso(s: str):
    from datetime import datetime, timezone
    s = s.replace("Z", "+00:00")
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def checkpoint_request_times(game: PbpGame, rules: LeagueRules) -> Dict[str, Tuple[str, int]]:
    """When to read the live line for each checkpoint -> (ISO request time, index of the state's last play).

    The historical endpoint resolves a request to the snapshot AT OR BEFORE it, so a line can never know more
    than the checkpoint state (a later line would hand the market information the model does not have).
    Quarter ends: just before the next period's first play (books re-post during the break). 5:00 Q4: the
    wallclock of the last play at 5:00. Whether the line was priced on the SAME score is decided after the
    fetch (`score_at_snapshot_matches`)."""
    from datetime import timedelta as _td
    out: Dict[str, Tuple[str, int]] = {}
    for cp in CHECKPOINTS:
        st = state_at(game, cp, rules)
        if st is None or not st.wallclock:
            continue
        t = _parse_iso(st.wallclock)
        if t is None:
            continue
        if st.clock_s == 0:
            nxt = next((p for p in game.plays[st.last_play_index + 1:] if p.period > st.period and p.wallclock), None)
            tn = _parse_iso(nxt.wallclock) if nxt else None
            t = (tn - _td(seconds=5)) if tn and tn > t else t
        out[cp] = (t.strftime("%Y-%m-%dT%H:%M:%SZ"), st.last_play_index)
    return out


def _score_at(game: PbpGame, ts: str) -> Optional[Tuple[int, int]]:
    t = _parse_iso(ts)
    best = None
    for p in game.plays:
        pt = _parse_iso(p.wallclock) if p.wallclock else None
        if pt is not None and pt <= t:
            best = (p.home, p.away)
    return best


class _SnapshotCache:
    """Cached historical snapshots indexed by their [timestamp, next_timestamp) validity interval."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.spans: List[Tuple[Any, Any, Path]] = []
        if root.exists():
            for f in sorted(root.glob("*.json.gz")):
                self._index(f, _read_gz(f))

    def _index(self, path: Path, doc: Dict[str, Any]) -> None:
        a = _parse_iso(str(doc.get("timestamp") or ""))
        b = _parse_iso(str(doc.get("next_timestamp") or "")) or a
        if a is not None:
            self.spans.append((a, b, path))

    def lookup(self, ts: str) -> Optional[Path]:
        t = _parse_iso(ts)
        for a, b, path in self.spans:
            if a <= t < b:
                return path
        return None

    def add(self, doc: Dict[str, Any]) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / (str(doc.get("timestamp") or "unknown").replace(":", "") + ".json.gz")
        with gzip.open(path, "wt", encoding="utf-8") as fh:
            json.dump(doc, fh)
        self._index(path, doc)
        return path


def run_live_close(args: argparse.Namespace) -> int:
    """Fetch (cached) OddsAPI historical snapshots at each game's checkpoint times; write live-close rows.

    --dry-run prints the request count, an estimate of the distinct snapshots (5-minute buckets) and the
    credit cost, and fetches nothing. A real run stops at --max-calls and after 3 consecutive failures."""
    rules = LEAGUES[args.league]
    games = load_games(Path(args.games))
    if args.population:
        games = [g for g in games if g.population in set(args.population)]
    reqs: List[Tuple[str, PbpGame, str]] = []
    for g in games:
        for cp, (ts, _) in checkpoint_request_times(g, rules).items():
            reqs.append((ts, g, cp))
    reqs.sort(key=lambda r: r[0])
    cache = _SnapshotCache(Path(args.cache))
    uncovered = [r for r in reqs if cache.lookup(r[0]) is None]
    buckets = {r[0][:15] + str(int(r[0][15]) // 5 * 5) for r in uncovered}
    print(f"LIVE_CLOSE_PLAN games={len(games)} requests={len(reqs)} uncovered={len(uncovered)} "
          f"est_snapshots={len(buckets)} est_credits={len(buckets) * CREDITS_PER_SNAPSHOT} "
          f"(per snapshot {CREDITS_PER_SNAPSHOT})", flush=True)
    if args.dry_run:
        return 0
    key = _odds_api_key(Path(args.env_file) if args.env_file else None)
    if not key:
        print("LIVE_CLOSE_NO_KEY", flush=True)
        return 2
    calls = fails = 0
    for ts, _, _ in uncovered:
        if calls >= args.max_calls:
            print(f"LIVE_CLOSE_STOP max_calls={args.max_calls}", flush=True)
            break
        if cache.lookup(ts) is not None:
            continue
        url = ODDSAPI_HIST.format(sport=ODDSAPI_SPORT[args.league], key=key, ts=ts)
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                doc = json.loads(r.read().decode("utf-8"))
                last = r.headers.get("x-requests-last")
            cache.add(doc)
            calls += 1
            fails = 0
            if calls % 50 == 0:
                print(f"LIVE_CLOSE_PROGRESS calls={calls} last_cost={last}", flush=True)
        except Exception as exc:  # noqa: BLE001
            fails += 1
            print(f"LIVE_CLOSE_FAIL {ts} {type(exc).__name__} {getattr(exc, 'code', '')}", flush=True)
            if fails >= 3:
                print("LIVE_CLOSE_ABORT consecutive_failures=3", flush=True)
                break
    out = Path(args.out)
    n = same = 0
    docs: Dict[Path, Dict[Tuple[str, str], Dict[str, Any]]] = {}
    with out.open("w", encoding="utf-8") as fh:
        for ts, g, cp in reqs:
            path = cache.lookup(ts)
            if path is None:
                continue
            if path not in docs:
                doc = _read_gz(path)
                by = {}
                for ev in doc.get("data") or []:
                    h, a = ODDSAPI_TO_ESPN.get(ev.get("home_team", "")), ODDSAPI_TO_ESPN.get(ev.get("away_team", ""))
                    if h and a:
                        by[(h, a)] = ev
                docs[path] = {"_ts": doc.get("timestamp"), **{k: v for k, v in by.items()}}
            d = docs[path]
            ev = d.get((g.home, g.away))
            if not ev:
                continue
            rec = _consensus(ev)
            if not rec:
                continue
            st = state_at(g, cp, rules)
            snap_score = _score_at(g, str(d["_ts"]))
            match = bool(st and snap_score == (st.home, st.away))
            same += match
            a, b = _parse_iso(str(d["_ts"])), _parse_iso(st.wallclock) if st and st.wallclock else None
            fh.write(json.dumps({
                "event_id": g.event_id, "checkpoint": cp, "requested": ts, "snapshot": d["_ts"],
                "snapshot_minus_state_s": (a - b).total_seconds() if a and b else None,
                "score_at_snapshot_matches": match, "total": rec.get("total"),
                "spread_home": rec.get("spread"), "p_home_ml": rec.get("p_home_ml")}) + "\n")
            n += 1
    print(f"LIVE_CLOSE_DONE calls={calls} rows={n} same_score_rows={same} out={out}", flush=True)
    return 0


def _odds_api_key(env_file: Optional[Path]) -> str:
    """Shell-exported ODDS_API_KEY can be a dead key that wins by precedence (memory 2026-10-05): the .env
    file is read FIRST when given. The value is never printed."""
    import os
    if env_file and env_file.exists():
        for ln in env_file.read_text(encoding="utf-8").splitlines():
            if ln.startswith("ODDS_API_KEY="):
                return ln.split("=", 1)[1].strip().strip('"').strip("'")
    return os.environ.get("ODDS_API_KEY", "")


def load_live_close(path: Optional[Path], *, same_score_only: bool = True) -> Dict[Tuple[str, str], Dict[str, float]]:
    """(event_id, checkpoint) -> {total, spread_home, p_home_ml} from `live-close` output (jsonl)."""
    out: Dict[Tuple[str, str], Dict[str, float]] = {}
    if not path or not path.exists():
        return out
    with path.open(encoding="utf-8") as fh:
        for ln in fh:
            if ln.strip():
                r = json.loads(ln)
                # Only a line priced on the SAME score as the checkpoint state is a like-for-like comparison.
                if same_score_only and r.get("score_at_snapshot_matches") is False:
                    continue
                out[(str(r["event_id"]), str(r["checkpoint"]))] = r
    return out


# ----------------------------------------------------------------------------------------------- grading

MARKETS = ("total", "margin", "p_home", "next_period_total", "current_period_total", "second_half_total")


def _err(market: str, proj: Projection, tr: Truth) -> Optional[float]:
    v = getattr(proj, market)
    if v is None:
        return None
    if market == "p_home":
        p = min(1 - 1e-6, max(1e-6, v))
        return (p - tr.home_win) ** 2  # Brier
    target = {
        "total": tr.final_total, "margin": tr.final_margin, "next_period_total": tr.next_period_total,
        "current_period_total": tr.current_period_total, "second_half_total": tr.second_half_total,
    }[market]
    if target is None:
        return None
    return abs(v - target)


def _signed(market: str, proj: Projection, tr: Truth) -> Optional[float]:
    v = getattr(proj, market)
    if v is None or market == "p_home":
        return None
    target = {"total": tr.final_total, "margin": tr.final_margin, "next_period_total": tr.next_period_total,
              "current_period_total": tr.current_period_total, "second_half_total": tr.second_half_total}[market]
    return None if target is None else v - target


def paired_bootstrap(diffs: Sequence[float], reps: int = 2000, seed: int = 20261009) -> Tuple[float, float, float]:
    """Mean of per-game paired differences with a percentile 95% CI (games resampled with replacement)."""
    if not diffs:
        return (float("nan"),) * 3
    rng = random.Random(seed)
    n = len(diffs)
    means = sorted(statistics.fmean(diffs[rng.randrange(n)] for _ in range(n)) for _ in range(reps))
    return statistics.fmean(diffs), means[int(0.025 * reps)], means[int(0.975 * reps) - 1]


def grade(games: Sequence[PbpGame], projectors: Sequence[Projector], *, lines, sims, live_close,
          baseline: Optional[str], checkpoints: Sequence[str] = tuple(CHECKPOINTS)) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    excluded: Dict[str, int] = defaultdict(int)
    for g in games:
        rules = LEAGUES[g.league]
        pre = pregame_for(g, lines, sims)
        for cp in checkpoints:
            st = state_at(g, cp, rules)
            if st is None:
                excluded[f"{cp}:no_state"] += 1
                continue
            if not state_is_consistent(g, st):
                excluded[f"{cp}:pbp_linescore_mismatch"] += 1
                continue
            tr = truth_for(g, st, rules)
            row: Dict[str, Any] = {"event_id": g.event_id, "date": g.date, "population": g.population,
                                   "checkpoint": cp, "pregame_source": pre.source, "proj": {}}
            for pj in projectors:
                pr = pj.project(g, st, pre, rules)
                row["proj"][pj.name] = pr
            lc = live_close.get((g.event_id, cp))
            row["live_close"] = lc
            row["truth"] = tr
            rows.append(row)

    report: Dict[str, Any] = {"excluded": dict(excluded), "cells": []}
    names = [p.name for p in projectors]
    keys = sorted({(r["population"], r["checkpoint"]) for r in rows},
                  key=lambda k: (k[0], list(CHECKPOINTS).index(k[1])))
    for pop, cp in keys:
        rs = [r for r in rows if r["population"] == pop and r["checkpoint"] == cp]
        for market in MARKETS:
            cell: Dict[str, Any] = {"population": pop, "checkpoint": cp, "market": market, "n_games": len(rs),
                                    "metric": "brier" if market == "p_home" else "mae", "projectors": {}}
            for name in names:
                errs = [e for e in (_err(market, r["proj"][name], r["truth"]) for r in rs) if e is not None]
                bias = [b for b in (_signed(market, r["proj"][name], r["truth"]) for r in rs) if b is not None]
                refusals: Dict[str, int] = defaultdict(int)
                for r in rs:
                    if r["proj"][name].refusal:
                        refusals[r["proj"][name].refusal] += 1
                if not errs:
                    continue
                fid = {r["proj"][name].fidelity for r in rs if getattr(r["proj"][name], market) is not None}
                cell["projectors"][name] = {"n": len(errs), "error": statistics.fmean(errs),
                                            "bias": statistics.fmean(bias) if bias else None,
                                            "refusals": dict(refusals), "fidelity": sorted(fid)}
            if baseline and baseline in names:
                for name in names:
                    if name == baseline:
                        continue
                    diffs = []
                    for r in rs:
                        a = _err(market, r["proj"][name], r["truth"])
                        b = _err(market, r["proj"][baseline], r["truth"])
                        if a is not None and b is not None:
                            diffs.append(a - b)
                    if diffs:
                        m, lo, hi = paired_bootstrap(diffs)
                        cell["projectors"].setdefault(name, {})[f"vs_{baseline}"] = {
                            "n_paired": len(diffs), "mean_diff": m, "ci95": [lo, hi],
                            "verdict": "better" if hi < 0 else ("worse" if lo > 0 else "not_separable")}
            if market in ("total", "margin"):
                for name in names:
                    cov = _coverage(market, [(r["proj"][name], r["truth"]) for r in rs])
                    if cov and name in cell["projectors"]:
                        cell["projectors"][name]["coverage"] = cov
            lc_rows = [r for r in rs if r.get("live_close")]
            if lc_rows and market in ("total", "margin", "p_home"):
                cell["live_close"] = _grade_vs_live_close(market, lc_rows, names)
            if cell["projectors"]:
                report["cells"].append(cell)
    report["n_rows"] = len(rows)
    return report


def central_interval(dist: Mapping[str, Any], level: float) -> Optional[Tuple[float, float]]:
    """Equal-tailed central interval of a {value: count} histogram (inclusive bounds)."""
    pts = sorted((float(k), float(v)) for k, v in (dist or {}).items() if float(v) > 0)
    n = sum(c for _, c in pts)
    if n <= 0:
        return None
    lo_q, hi_q = (1 - level) / 2 * n, (1 + level) / 2 * n
    run, lo, hi = 0.0, None, None
    for v, c in pts:
        run += c
        if lo is None and run > lo_q:
            lo = v
        if hi is None and run >= hi_q:
            hi = v
    return (lo, hi if hi is not None else pts[-1][0])


def _coverage(market: str, pairs: Sequence[Tuple["Projection", "Truth"]]) -> Optional[Dict[str, Any]]:
    """Share of games whose final falls inside the projector's central 50% / 80% interval (nominal +- 3pp is
    the design's distribution gate)."""
    attr = "total_dist" if market == "total" else "margin_dist"
    hits = {0.5: [], 0.8: []}
    for pr, tr in pairs:
        d = getattr(pr, attr, None)
        if not d:
            continue
        target = tr.final_total if market == "total" else tr.final_margin
        for lvl in hits:
            iv = central_interval(d, lvl)
            if iv:
                hits[lvl].append(1.0 if iv[0] <= target <= iv[1] else 0.0)
    if not hits[0.5]:
        return None
    return {"n": len(hits[0.5]), "cover50": statistics.fmean(hits[0.5]), "cover80": statistics.fmean(hits[0.8])}


def _grade_vs_live_close(market: str, rs: List[Dict[str, Any]], names: Sequence[str]) -> Dict[str, Any]:
    """Against the live line at the checkpoint: the line's own error, each projector's error on the SAME
    games, and the projector's side-of-line hit rate (pushes excluded)."""
    key = {"total": "total", "margin": "spread_home", "p_home": "p_home_ml"}[market]
    out: Dict[str, Any] = {}
    line_err, per = [], defaultdict(list)
    hits = defaultdict(list)
    for r in rs:
        lc, tr = r["live_close"], r["truth"]
        line = lc.get(key)
        if line is None:
            continue
        if market == "p_home":
            line_err.append((line - tr.home_win) ** 2)
        elif market == "total":
            line_err.append(abs(line - tr.final_total))
        else:
            line_err.append(abs(-line - tr.final_margin))
        for name in names:
            v = getattr(r["proj"][name], market)
            if v is None:
                continue
            if market == "p_home":
                per[name].append((v - tr.home_win) ** 2)
                continue
            target = tr.final_total if market == "total" else tr.final_margin
            ref = line if market == "total" else -line
            per[name].append(abs(v - target))
            if target != ref and v != ref:
                hits[name].append(1.0 if (v > ref) == (target > ref) else 0.0)
    out["n"] = len(line_err)
    out["line_error"] = statistics.fmean(line_err) if line_err else None
    for name in names:
        if per[name]:
            out[name] = {"error_same_games": statistics.fmean(per[name]),
                         "side_hit_rate": statistics.fmean(hits[name]) if hits[name] else None,
                         "n_sides": len(hits[name])}
    return out


def render_markdown(report: Dict[str, Any]) -> str:
    lines = ["| population | checkpoint | market | metric | n | " + " | ".join(["projector: error (n) [vs baseline]"]) + " |",
             "|---|---|---|---|---|---|"]
    for c in report["cells"]:
        parts = []
        for name, v in c["projectors"].items():
            if "error" not in v:
                continue
            s = f"{name}: {v['error']:.3f} ({v['n']})"
            for k, cmp in v.items():
                if k.startswith("vs_"):
                    s += f" [{cmp['mean_diff']:+.3f} CI {cmp['ci95'][0]:+.3f}..{cmp['ci95'][1]:+.3f} {cmp['verdict']}]"
            parts.append(s)
        lines.append(f"| {c['population']} | {c['checkpoint']} | {c['market']} | {c['metric']} | {c['n_games']} | "
                     + "<br>".join(parts) + " |")
    if report.get("excluded"):
        lines.append("")
        lines.append("Excluded: " + ", ".join(f"{k}={v}" for k, v in sorted(report["excluded"].items())))
    return "\n".join(lines) + "\n"


def _jsonable(o: Any) -> Any:
    if dataclasses.is_dataclass(o):
        return dataclasses.asdict(o)
    raise TypeError(type(o))


def run_grade(args: argparse.Namespace) -> int:
    games = load_games(Path(args.games))
    if args.population:
        games = [g for g in games if g.population in set(args.population)]
    if args.shard:
        i, n = (int(x) for x in str(args.shard).split("/", 1))
        games = [g for g in games if zlib.crc32(g.event_id.encode("utf-8")) % n == i]
    sims = load_sim_draws(Path(args.sim_draws)) if args.sim_draws else {}
    lines = load_pregame_lines(Path(args.lines_cache)) if args.lines_cache else {}
    live = load_live_close(Path(args.live_close)) if args.live_close else {}
    projectors = []
    for n in args.projectors:
        if n == "native_resim":
            caches = [Path(c) for c in (args.summary_cache or [])]
            projectors.append(NativeResimProjector(inputs_root=Path(args.engine_inputs) if args.engine_inputs else None,
                                                   summary_caches=caches, sims=args.resim_sims,
                                                   cache_dir=Path(args.native_cache) if args.native_cache else None))
        else:
            projectors.append(PROJECTORS[n]())
    rep = grade(games, projectors, lines=lines, sims=sims, live_close=live, baseline=args.baseline)
    rep["inputs"] = {"games": len(games), "sim_games": len(sims), "pregame_lines": len(lines), "live_close": len(live),
                     "projectors": args.projectors, "baseline": args.baseline}
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(rep, indent=1, default=_jsonable), encoding="utf-8")
    (out / "report.md").write_text(render_markdown(rep), encoding="utf-8")
    print(f"GRADE rows={rep['n_rows']} cells={len(rep['cells'])} excluded={rep['excluded']} out={out}", flush=True)
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("--league", default="nba", choices=sorted(LEAGUES))
    f.add_argument("--start", required=True)
    f.add_argument("--end", required=True)
    f.add_argument("--cache", required=True)
    f.add_argument("--read-cache", action="append")
    c = sub.add_parser("corpus")
    c.add_argument("--league", default="nba", choices=sorted(LEAGUES))
    c.add_argument("--start", required=True)
    c.add_argument("--end", required=True)
    c.add_argument("--cache", required=True)
    c.add_argument("--read-cache", action="append")
    c.add_argument("--out", required=True)
    g = sub.add_parser("grade")
    g.add_argument("--games", required=True)
    g.add_argument("--sim-draws")
    g.add_argument("--lines-cache")
    g.add_argument("--live-close")
    g.add_argument("--population", action="append", choices=sorted(set(POPULATION_BY_SEASON_TYPE.values())))
    g.add_argument("--projectors", nargs="+", default=["pregame_rate", "vendored_replay", "espn_wp"],
                   choices=sorted([*PROJECTORS, "native_resim"]))
    g.add_argument("--engine-inputs", help="dir of pregame engine-input pickles (native_resim)")
    g.add_argument("--summary-cache", action="append", help="ESPN summary cache dir(s) (native_resim)")
    g.add_argument("--resim-sims", type=int, default=100)
    g.add_argument("--native-cache", help="dir caching native_resim projections per (game, checkpoint)")
    g.add_argument("--shard", help="i/n: grade only games whose crc32(event_id) %% n == i (fill the cache in parallel)")
    g.add_argument("--baseline", default="vendored_replay")
    g.add_argument("--out", required=True)
    lc = sub.add_parser("live-close")
    lc.add_argument("--league", default="nba", choices=sorted(LEAGUES))
    lc.add_argument("--games", required=True)
    lc.add_argument("--population", action="append", choices=sorted(set(POPULATION_BY_SEASON_TYPE.values())))
    lc.add_argument("--cache", required=True)
    lc.add_argument("--out", required=True)
    lc.add_argument("--env-file")
    lc.add_argument("--max-calls", type=int, default=0)
    lc.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    return {"fetch": run_fetch, "corpus": run_corpus, "grade": run_grade, "live-close": run_live_close}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
