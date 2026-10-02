"""AS-OF backtest of every priced MLB pregame market: game lines and player props.

Lane `mlb-lines-props-backtest`. Mirrors the NHL template (lane
`nhl-player-props-projection`, deploys.md 2026-10-02 21:38Z): per market n,
MAE/bias vs the actual, dMAE vs a naive AS-OF baseline with a game-clustered
bootstrap CI, and Brier/log-loss vs the de-vigged book on the SAME rows. A
market earns a probability/edge on the board only if it beats BOTH.

WHAT "AS-OF" MEANS HERE, AND HOW EACH SIDE IS ENFORCED
------------------------------------------------------
* MODEL. `daily_summary_<date>.json` is NOT used: it is rewritten after games by
  `started_game_repairs` re-sims (findings_2026-09-14, 326 of 326 scored games),
  so it is a post-game upper bound. Instead each per-game sim file
  `daily/sims/<date>/sim_*.json` records `schedule.status` AT SIM TIME; only
  files simulated while the game was Scheduled / Pre-Game / Warmup are kept.
  In-progress / final re-sims are dropped and COUNTED.
* BOOK. Every `oddsapi_*_<date>*.json` snapshot carries `retrieved_at`
  (UTC -- `datetime.utcnow()` in vendor/mlb_bettingv2/tools/oddsapi/
  fetch_daily_oddsapi_markets.py). A quote is kept only if retrieved strictly
  before that game's first pitch; of several, the LATEST such quote wins.
* BASELINES. Built from games whose officialDate is strictly before the slate
  date: the player's own season-to-date per-game average (props) and the two
  teams' season-to-date runs scored/allowed (game lines). The baseline
  probability is the player's own empirical as-of rate of clearing the line
  (Laplace-smoothed) for props, and a normal approximation on the as-of team
  means with the league's as-of spread for game lines.
* OUTCOMES. MLB StatsAPI (public, immutable): the season schedule with
  linescores, and per-player game logs keyed by gamePk (doubleheader-safe).

Players who did not appear (0 PA / did not start) are voided and counted --
that is the `prop_player_not_in_boxscore` case of findings_2026-09-28, which
measured 96.5% of such rows as true DNPs.

Run (on the fleet host, data root = production's disk):
  python scripts/backtest_mlb_lines_props.py \
      --data-root ~/syndicate-prod/data --out /tmp/mlb_bt
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import glob
import json
import math
import os
import random
import re
import sys
import time
import unicodedata
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

STATSAPI = "https://statsapi.mlb.com/api/v1"
PREGAME_STATUSES = frozenset({"Scheduled", "Pre-Game", "Warmup"})
SEGMENTS = {"full": None, "first5": 5, "first3": 3, "first1": 1}

# book market key -> (model dist key, game-log stat key or callable, side kind)
HITTER_MARKETS = {
    "batter_hits": ("hits_dist", "h_mean", lambda s: s["hits"]),
    "batter_total_bases": ("total_bases_dist", "tb_mean", lambda s: s["totalBases"]),
    "batter_home_runs": ("home_runs_dist", "hr_mean", lambda s: s["homeRuns"]),
    "batter_rbis": ("rbi_dist", "rbi_mean", lambda s: s["rbi"]),
    "batter_runs_scored": ("runs_dist", "r_mean", lambda s: s["runs"]),
    "batter_hits_runs_rbis": ("hits_runs_rbis_dist", None, lambda s: s["hits"] + s["runs"] + s["rbi"]),
}
PITCHER_MARKETS = {
    "strikeouts": ("so_dist", "so_mean", lambda s: s["strikeOuts"]),
    "outs": ("outs_dist", "outs_mean", lambda s: s["outs"]),
    "earned_runs": ("earned_runs_dist", "er_mean", lambda s: s["earnedRuns"]),
    "hits_allowed": ("hits_dist", "hits_mean", lambda s: s["hits"]),
    "walks_allowed": ("walks_dist", "walks_mean", lambda s: s["baseOnBalls"]),
}


# --------------------------------------------------------------------------- utils
def american_to_prob(odds) -> float | None:
    try:
        o = float(str(odds).replace("+", ""))
    except (TypeError, ValueError):
        return None
    if o == 0:
        return None
    return 100.0 / (o + 100.0) if o > 0 else -o / (-o + 100.0)


def american_to_decimal(odds) -> float | None:
    try:
        o = float(str(odds).replace("+", ""))
    except (TypeError, ValueError):
        return None
    if o == 0:
        return None
    return 1.0 + (o / 100.0 if o > 0 else 100.0 / -o)


def devig_two_way(odds_a, odds_b) -> float | None:
    """Proportional de-vig; returns the fair probability of side A."""
    pa, pb = american_to_prob(odds_a), american_to_prob(odds_b)
    if pa is None or pb is None or pa + pb <= 0:
        return None
    return pa / (pa + pb)


def norm_name(name: str) -> str:
    s = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z ]", "", s.lower().replace("-", " "))
    s = re.sub(r"\b(jr|sr|ii|iii|iv)\b", "", s)
    return " ".join(s.split())


def parse_utc(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)  # vendor writes naive UTC


def dist_prob_over(dist: dict, line: float) -> float | None:
    """P(X > line | X != line) from a {value: count} sim distribution."""
    if not dist:
        return None
    over = under = 0.0
    for k, c in dist.items():
        try:
            v = float(k)
        except (TypeError, ValueError):
            continue
        if v > line:
            over += c
        elif v < line:
            under += c
    tot = over + under
    return over / tot if tot > 0 else None


def dist_mean(dist: dict) -> float | None:
    n = sum(dist.values()) if dist else 0
    return sum(float(k) * c for k, c in dist.items()) / n if n else None


def dist_degenerate(dist: dict | None) -> bool:
    return not dist or len([k for k, c in dist.items() if c]) <= 1


def phi(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def normal_prob_over(mu: float, sd: float, line: float) -> float:
    """P(X > line | X != line) for an integer-valued X ~ N(mu, sd), continuity-corrected."""
    sd = max(sd, 1e-6)
    if float(line).is_integer():
        p_over = 1.0 - phi((line + 0.5 - mu) / sd)
        p_under = phi((line - 0.5 - mu) / sd)
        return p_over / (p_over + p_under) if p_over + p_under > 0 else 0.5
    return 1.0 - phi((line - mu) / sd)


def clip(p: float) -> float:
    return min(max(p, 1e-6), 1 - 1e-6)


def brier(p: float, y: int) -> float:
    return (p - y) ** 2


def logloss(p: float, y: int) -> float:
    p = clip(p)
    return -(y * math.log(p) + (1 - y) * math.log(1 - p))


# ------------------------------------------------------------------- statistics
def cluster_boot_ci(rows, value, cluster="game_pk", draws=1000, seed=7):
    """Mean of value(row) with a percentile CI that resamples CLUSTERS (games)."""
    by = defaultdict(lambda: [0.0, 0])
    for r in rows:
        v = value(r)
        if v is None:
            continue
        b = by[r[cluster]]
        b[0] += v
        b[1] += 1
    keys = list(by)
    if not keys:
        return None, None, None
    tot = sum(by[k][0] for k in keys)
    cnt = sum(by[k][1] for k in keys)
    rng = random.Random(seed)
    stats = []
    for _ in range(draws):
        s = c = 0.0
        for _k in range(len(keys)):
            b = by[keys[rng.randrange(len(keys))]]
            s += b[0]
            c += b[1]
        stats.append(s / c)
    stats.sort()
    return tot / cnt, stats[int(0.025 * draws)], stats[int(0.975 * draws) - 1]


def verdict(n: int, lo, hi, min_n: int) -> str:
    """The NHL rule: negative difference = model better."""
    if n < min_n or lo is None:
        return "INSUFFICIENT_N"
    if hi < 0:
        return "MODEL_BETTER"
    if lo > 0:
        return "MODEL_WORSE"
    return "NO_DIFFERENCE"


# --------------------------------------------------------------------- statsapi
class StatsApi:
    def __init__(self, cache_dir: Path, offline: bool = False):
        self.cache = cache_dir
        self.cache.mkdir(parents=True, exist_ok=True)
        self.offline = offline
        self.fetched = 0

    def get(self, path: str, key: str, max_age_s: float | None = None):
        f = self.cache / (re.sub(r"[^A-Za-z0-9_.-]", "_", key) + ".json")
        if f.exists() and (max_age_s is None or time.time() - f.stat().st_mtime < max_age_s):
            return json.loads(f.read_text(encoding="utf-8"))
        if self.offline:
            return None
        req = urllib.request.Request(STATSAPI + path, headers={"User-Agent": "syndicate-backtest/1.0"})
        for attempt in range(4):
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    data = json.loads(r.read().decode("utf-8"))
                break
            except Exception:  # noqa: BLE001 -- network retry
                if attempt == 3:
                    raise
                time.sleep(2 * (attempt + 1))
        f.write_text(json.dumps(data), encoding="utf-8")
        self.fetched += 1
        return data

    def season_schedule(self, season: int, game_type: str):
        return self.get(
            f"/schedule?sportId=1&season={season}&gameType={game_type}"
            f"&startDate={season}-02-01&endDate={season}-11-30&hydrate=linescore",
            f"schedule_{season}_{game_type}", max_age_s=6 * 3600)

    def game_log(self, pid: int, group: str, season: int, game_type: str):
        return self.get(
            f"/people/{pid}/stats?stats=gameLog&group={group}&season={season}&gameType={game_type}",
            f"gamelog_{pid}_{group}_{season}_{game_type}", max_age_s=6 * 3600)


def schedule_games(sched) -> dict[int, dict]:
    """gamePk -> {date, start, home/away ids+names, status, innings} for real finals."""
    out = {}
    for d in (sched or {}).get("dates", []):
        for g in d.get("games", []):
            pk = g.get("gamePk")
            ls = g.get("linescore") or {}
            out[pk] = {
                "game_pk": pk,
                "date": g.get("officialDate") or d.get("date"),
                "start": parse_utc(g.get("gameDate")),
                "status": (g.get("status") or {}).get("detailedState"),
                "abstract": (g.get("status") or {}).get("abstractGameState"),
                "home_id": g["teams"]["home"]["team"]["id"],
                "away_id": g["teams"]["away"]["team"]["id"],
                "home_name": g["teams"]["home"]["team"].get("name"),
                "away_name": g["teams"]["away"]["team"].get("name"),
                "home_score": g["teams"]["home"].get("score"),
                "away_score": g["teams"]["away"].get("score"),
                "innings": [((i.get("home") or {}).get("runs"), (i.get("away") or {}).get("runs"))
                            for i in ls.get("innings", [])],
                "game_type": g.get("gameType"),
            }
    return out


def segment_runs(g: dict, seg: str):
    """(home, away) runs for a segment, or None if the segment did not complete."""
    if g["status"] != "Final" or g["home_score"] is None:
        return None
    k = SEGMENTS[seg]
    if k is None:
        return g["home_score"], g["away_score"]
    inn = g["innings"]
    if len(inn) < k:
        return None
    h = a = 0
    for i, (hr, ar) in enumerate(inn[:k]):
        if ar is None or (hr is None and i < k - 1):
            return None
        a += ar
        h += hr or 0  # bottom of an inning not played only when home leads after 9 -- never inside k<=5
    return h, a


# ------------------------------------------------------------------ team as-of
class TeamAsOf:
    """Season-to-date runs scored/allowed per team per segment, strictly before a date."""

    def __init__(self, games: dict[int, dict]):
        self.finals = sorted((g for g in games.values() if g["status"] == "Final" and g["game_type"] == "R"),
                             key=lambda g: g["date"])
        self._memo = {}

    def as_of(self, date: str, seg: str):
        key = (date, seg)
        if key in self._memo:
            return self._memo[key]
        team = defaultdict(lambda: [0, 0, 0])  # rs, ra, g
        totals, margins = [], []
        for g in self.finals:
            if g["date"] >= date:
                break
            r = segment_runs(g, seg)
            if r is None:
                continue
            h, a = r
            for tid, rs, ra in ((g["home_id"], h, a), (g["away_id"], a, h)):
                t = team[tid]
                t[0] += rs
                t[1] += ra
                t[2] += 1
            totals.append(h + a)
            margins.append(h - a)
        lg = None
        if len(totals) >= 30:
            mt = sum(totals) / len(totals)
            mm = sum(margins) / len(margins)
            lg = {
                "rpg": mt / 2.0, "home_margin": mm,
                "sd_total": (sum((x - mt) ** 2 for x in totals) / (len(totals) - 1)) ** 0.5,
                "sd_margin": (sum((x - mm) ** 2 for x in margins) / (len(margins) - 1)) ** 0.5,
                "n": len(totals),
            }
        self._memo[key] = (dict(team), lg)
        return self._memo[key]

    def baseline(self, date: str, seg: str, home_id: int, away_id: int, min_games: int = 10):
        team, lg = self.as_of(date, seg)
        if lg is None:
            return None

        def rate(tid):
            t = team.get(tid)
            if not t or t[2] < min_games:
                return lg["rpg"], lg["rpg"]
            return t[0] / t[2], t[1] / t[2]

        hrs, hra = rate(home_id)
        ars, ara = rate(away_id)
        home_exp = (hrs + ara) / 2.0 + lg["home_margin"] / 2.0
        away_exp = (ars + hra) / 2.0 - lg["home_margin"] / 2.0
        return {"total": home_exp + away_exp, "margin": home_exp - away_exp,
                "sd_total": lg["sd_total"], "sd_margin": lg["sd_margin"]}


# ---------------------------------------------------------------- player as-of
def player_rows(log_json) -> list[dict]:
    out = []
    for sp in (log_json or {}).get("stats", []):
        for s in sp.get("splits", []):
            st = dict(s.get("stat") or {})
            for k, v in list(st.items()):
                if isinstance(v, str) and re.fullmatch(r"-?\d+", v):
                    st[k] = int(v)
            if "outs" not in st and "inningsPitched" in st:
                ip = str(st["inningsPitched"])
                whole, _, frac = ip.partition(".")
                st["outs"] = int(whole or 0) * 3 + int(frac or 0)
            out.append({"date": s.get("date"), "game_pk": (s.get("game") or {}).get("gamePk"), "stat": st})
    return out


def asof_baseline(rows: list[dict], date: str, value, appeared, min_games: int):
    prior = [value(r["stat"]) for r in rows if r["date"] and r["date"] < date and appeared(r["stat"])]
    if len(prior) < min_games:
        return None
    return {"mean": sum(prior) / len(prior), "values": prior,
            "last10": sum(prior[-10:]) / len(prior[-10:]), "n": len(prior)}


def empirical_rate_over(values: list[float], line: float) -> float:
    over = sum(1 for v in values if v > line)
    under = sum(1 for v in values if v < line)
    return (over + 1.0) / (over + under + 2.0)


# ------------------------------------------------------------------- loaders
def load_pregame_sims(daily_dir: Path, dates_filter, counters: Counter) -> dict[int, dict]:
    sims = {}
    for f in sorted(glob.glob(str(daily_dir / "sims" / "*" / "sim_*.json"))):
        date = Path(f).parent.name
        if dates_filter and date not in dates_filter:
            continue
        try:
            s = json.loads(Path(f).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            counters["sim_unreadable"] += 1
            continue
        status = ((s.get("schedule") or {}).get("status") or {}).get("detailed")
        counters["sim_files"] += 1
        if status not in PREGAME_STATUSES:
            counters[f"sim_dropped_not_pregame:{status}"] += 1
            continue
        pk = s.get("game_pk")
        if pk in sims:
            counters["sim_duplicate_pk"] += 1
            continue
        s["_date"] = date
        sims[pk] = s
    return sims


def load_snapshots(data_dir: Path, kind: str) -> dict[str, list[dict]]:
    """date -> list of snapshot docs of `kind` (game_lines / hitter_props / pitcher_props)."""
    out = defaultdict(list)
    pats = [str(data_dir / "daily" / "snapshots" / "*" / f"oddsapi_{kind}_*.json"),
            str(data_dir / "market" / "oddsapi" / f"oddsapi_{kind}_*.json")]
    for p in pats:
        for f in glob.glob(p):
            m = re.search(r"(\d{4})_(\d{2})_(\d{2})", Path(f).name)
            if not m:
                continue
            try:
                doc = json.loads(Path(f).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            doc["_file"] = f
            doc["_retrieved"] = parse_utc(doc.get("retrieved_at"))
            out["-".join(m.groups())].append(doc)
    return out


# ----------------------------------------------------------------- game lines
def build_game_rows(sims, sched, team_asof, gl_snaps, counters):
    """One row per (game, segment, market) with model / baseline / book / actual."""
    rows, points = [], []
    for pk, s in sims.items():
        g = sched.get(pk)
        if not g or g["start"] is None:
            counters["game_no_schedule"] += 1
            continue
        date = s["_date"]
        # latest pregame quote for this game across every snapshot of the date
        best = None
        for doc in gl_snaps.get(date, []):
            if doc["_retrieved"] is None or doc["_retrieved"] >= g["start"]:
                continue
            for ev in doc.get("games", []):
                if ev.get("home_team") != g["home_name"] or ev.get("away_team") != g["away_name"]:
                    continue
                ct = parse_utc(ev.get("commence_time"))
                if ct is None or abs((ct - g["start"]).total_seconds()) > 3 * 3600:
                    continue
                if best is None or doc["_retrieved"] > best[0]:
                    best = (doc["_retrieved"], ev)
        if best is None:
            counters["game_no_pregame_quote"] += 1
        segs = (s.get("sim") or {}).get("segments") or {}
        for seg in SEGMENTS:
            ms = segs.get(seg)
            act = segment_runs(g, seg)
            if not ms or act is None:
                counters[f"game_seg_missing:{seg}"] += 1
                continue
            h, a = act
            base = team_asof.baseline(date, seg, g["home_id"], g["away_id"])
            mt = (ms.get("home_runs_mean") or 0) + (ms.get("away_runs_mean") or 0)
            mm = (ms.get("home_runs_mean") or 0) - (ms.get("away_runs_mean") or 0)
            pt = {"game_pk": pk, "date": date, "segment": seg, "gtype": g["game_type"],
                  "model_total": mt, "model_margin": mm, "act_total": h + a, "act_margin": h - a,
                  "base_total": base["total"] if base else None, "base_margin": base["margin"] if base else None}
            points.append(pt)
            book = ((best[1]["markets"].get("segments") or {}).get(seg) if best else None) or {}
            if seg == "full" and best and not book:
                book = {k: best[1]["markets"].get(k) for k in ("h2h", "spreads", "totals")}
            margin_dist = ms.get("run_margin_dist") or {}
            total_dist = ms.get("total_runs_dist") or {}
            # ---- moneyline (home side)
            hp, ap, tp = ms.get("home_win_prob"), ms.get("away_win_prob"), ms.get("tie_prob") or 0.0
            h2h = book.get("h2h") or {}
            three = bool(h2h.get("is_3_way"))
            if hp is not None and ap is not None:
                if seg == "full" or not three:
                    if h == a:
                        counters[f"ml_push:{seg}"] += 1
                    else:
                        p_model = hp / (hp + ap) if hp + ap > 0 else None
                        p_base = normal_prob_over(base["margin"], base["sd_margin"], 0.0) if base else None
                        p_book = devig_two_way(h2h.get("home_odds"), h2h.get("away_odds")) if h2h else None
                        rows.append(_row(pk, date, g, seg, "moneyline", 0.0, p_model, p_base, p_book,
                                         int(h > a), h2h.get("home_odds"), h2h.get("away_odds")))
                else:
                    ph, pa_, pd = (american_to_prob(h2h.get(k)) for k in ("home_odds", "away_odds", "draw_odds"))
                    p_book = ph / (ph + pa_ + pd) if None not in (ph, pa_, pd) else None
                    p_base = (1.0 - phi((0.5 - base["margin"]) / base["sd_margin"])) if base else None
                    rows.append(_row(pk, date, g, seg, "moneyline_3way", 0.0, hp, p_base, p_book,
                                     int(h > a), h2h.get("home_odds"), None))
            # ---- run line (home side covers if margin + home_line > 0)
            sp = book.get("spreads") or {}
            if sp.get("home_line") is not None:
                hl = float(sp["home_line"])
                cover_margin = h - a + hl
                if cover_margin == 0:
                    counters[f"rl_push:{seg}"] += 1
                else:
                    p_model = dist_prob_over(margin_dist, -hl)
                    p_base = normal_prob_over(base["margin"], base["sd_margin"], -hl) if base else None
                    p_book = devig_two_way(sp.get("home_odds"), sp.get("away_odds"))
                    rows.append(_row(pk, date, g, seg, "run_line", hl, p_model, p_base, p_book,
                                     int(cover_margin > 0), sp.get("home_odds"), sp.get("away_odds")))
            # ---- total (over side)
            tt = book.get("totals") or {}
            if tt.get("line") is not None:
                ln = float(tt["line"])
                if h + a == ln:
                    counters[f"total_push:{seg}"] += 1
                else:
                    p_model = dist_prob_over(total_dist, ln)
                    p_base = normal_prob_over(base["total"], base["sd_total"], ln) if base else None
                    p_book = devig_two_way(tt.get("over_odds"), tt.get("under_odds"))
                    rows.append(_row(pk, date, g, seg, "total", ln, p_model, p_base, p_book,
                                     int(h + a > ln), tt.get("over_odds"), tt.get("under_odds")))
    return rows, points


def _row(pk, date, g, seg, market, line, p_model, p_base, p_book, y, odds_a, odds_b):
    return {"game_pk": pk, "date": date, "gtype": g["game_type"], "market": f"{seg}:{market}",
            "line": line, "p_model": p_model, "p_base": p_base, "p_book": p_book, "y": y,
            "dec_a": american_to_decimal(odds_a), "dec_b": american_to_decimal(odds_b)}


# ------------------------------------------------------------------- props
def build_prop_rows(sims, sched, api, hp_snaps, pp_snaps, season, workers, counters, min_games):
    # who appears in which game, from the model's own lineups
    hitters, pitchers = {}, {}  # (pk, pid) -> (sim, model block)
    for pk, s in sims.items():
        sim = s.get("sim") or {}
        for pid, hb in (sim.get("hitter_props") or {}).items():
            if hb.get("is_lineup_batter", True):
                hitters[(pk, int(pid))] = hb
        for pid, pb in (sim.get("pitcher_props") or {}).items():
            pitchers[(pk, int(pid))] = pb
    starters = {(pk, int(pid)) for pk, s in sims.items() for pid in (s.get("starters") or {}).values() if pid}
    pitchers = {k: v for k, v in pitchers.items() if k in starters}
    counters["model_hitter_games"] = len(hitters)
    counters["model_starter_games"] = len(pitchers)

    pids = {("hitting", pid) for _, pid in hitters} | {("pitching", pid) for _, pid in pitchers}
    logs = {}

    def fetch(k):
        grp, pid = k
        reg = player_rows(api.game_log(pid, grp, season, "R"))
        post = player_rows(api.game_log(pid, grp, season, "P"))
        return k, reg, post

    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        for k, reg, post in ex.map(fetch, sorted(pids)):
            logs[k] = (reg, post)

    name_index = defaultdict(list)  # (date, norm name) -> [(pk, pid, role)]
    for (pk, pid), hb in hitters.items():
        name_index[(sims[pk]["_date"], norm_name(hb.get("name")), "h")].append((pk, pid))
    for pk, s in sims.items():
        for side, pid in (s.get("starters") or {}).items():
            nm = (s.get("starter_names") or {}).get(side)
            if pid and nm:
                name_index[(s["_date"], norm_name(nm), "p")].append((pk, int(pid)))

    rows, points = [], []
    for role, table, markets, snaps, grp in (
            ("h", hitters, HITTER_MARKETS, hp_snaps, "hitting"),
            ("p", pitchers, PITCHER_MARKETS, pp_snaps, "pitching")):
        appeared = (lambda st: st.get("plateAppearances", 0) > 0) if role == "h" else \
                   (lambda st: st.get("gamesStarted", 0) > 0)
        # ---- point rows: every modelled player-game where the player appeared
        for (pk, pid), blk in table.items():
            g = sched.get(pk)
            reg, post = logs.get((grp, pid), ([], []))
            mine = [r for r in reg + post if r["game_pk"] == pk]
            if not mine:
                counters[f"{role}_dnp_or_not_in_box"] += 1
                continue
            act_stat = mine[0]["stat"]
            if not appeared(act_stat):
                counters[f"{role}_dnp_or_not_in_box"] += 1
                continue
            date = sims[pk]["_date"]
            for mkt, (dkey, mkey, val) in markets.items():
                dist = blk.get(dkey)
                if role == "h" and mkt == "batter_hits_runs_rbis":
                    mean = sum(blk.get(k) or 0 for k in ("h_mean", "r_mean", "rbi_mean"))
                else:
                    mean = blk.get(mkey) if mkey else None
                    if mean is None and dist:
                        mean = dist_mean(dist)
                b = asof_baseline(reg, date, val, appeared, min_games)
                if b is None:
                    counters[f"{role}:{mkt}:no_asof_baseline"] += 1
                    continue
                points.append({"game_pk": pk, "date": date, "gtype": (g or {}).get("game_type"),
                               "market": mkt, "pid": pid, "model": mean, "base": b["mean"],
                               "base10": b["last10"], "act": val(act_stat)})
        # ---- probability rows: every two-sided priced line, quoted before first pitch
        for date, docs in snaps.items():
            key = "hitter_props" if role == "h" else "pitcher_props"
            latest = {}  # (pk, pid, mkt, line) -> (retrieved, lane)
            for doc in docs:
                for nm, mk in (doc.get(key) or {}).items():
                    cands = name_index.get((date, norm_name(nm), role), [])
                    if len(cands) != 1:
                        counters[f"{role}_name_{'unmatched' if not cands else 'ambiguous'}"] += 1
                        continue
                    pk, pid = cands[0]
                    g = sched.get(pk)
                    if not g or not g["start"] or doc["_retrieved"] is None or doc["_retrieved"] >= g["start"]:
                        counters[f"{role}_quote_not_pregame"] += 1
                        continue
                    for mkt, q in mk.items():
                        if mkt not in markets:
                            counters[f"{role}_market_unmodelled:{mkt}"] += 1
                            continue
                        for lane in (q.get("lanes") or [q]):
                            if lane.get("line") is None or lane.get("over_odds") is None or lane.get("under_odds") is None:
                                counters[f"{role}_one_sided"] += 1
                                continue
                            k = (pk, pid, mkt, float(lane["line"]))
                            if k not in latest or doc["_retrieved"] > latest[k][0]:
                                latest[k] = (doc["_retrieved"], lane)
            for (pk, pid, mkt, line), (_, lane) in latest.items():
                blk = table.get((pk, pid))
                g = sched.get(pk)
                reg, post = logs.get((grp, pid), ([], []))
                mine = [r for r in reg + post if r["game_pk"] == pk]
                if blk is None or not mine or not appeared(mine[0]["stat"]):
                    counters[f"{role}_priced_void_dnp"] += 1
                    continue
                dkey, _mkey, val = markets[mkt]
                actual = val(mine[0]["stat"])
                if actual == line:
                    counters[f"{role}_prop_push"] += 1
                    continue
                dist = blk.get(dkey)
                p_model = None if dist_degenerate(dist) else dist_prob_over(dist, line)
                if p_model is None:
                    counters[f"{role}:{mkt}:model_dist_dead"] += 1
                b = asof_baseline(reg, sims[pk]["_date"], val, appeared, min_games)
                if b is None:
                    counters[f"{role}:{mkt}:priced_no_asof_baseline"] += 1
                    continue
                rows.append({"game_pk": pk, "date": sims[pk]["_date"], "gtype": (g or {}).get("game_type"),
                             "market": mkt, "pid": pid, "line": line, "p_model": p_model,
                             "p_base": empirical_rate_over(b["values"], line),
                             "p_book": devig_two_way(lane["over_odds"], lane["under_odds"]),
                             "y": int(actual > line),
                             "dec_a": american_to_decimal(lane["over_odds"]),
                             "dec_b": american_to_decimal(lane["under_odds"])})
    return rows, points


# ---------------------------------------------------------------- summarising
def summarise_points(points, model_key, base_key, act_key, min_n, draws):
    pts = [p for p in points if p[model_key] is not None and p[base_key] is not None]
    if not pts:
        return None
    n = len(pts)
    err = lambda p, k: abs(p[k] - p[act_key])  # noqa: E731
    d, lo, hi = cluster_boot_ci(pts, lambda p: err(p, model_key) - err(p, base_key), draws=draws)
    return {"n": n, "games": len({p["game_pk"] for p in pts}), "dates": len({p["date"] for p in pts}),
            "mean_actual": sum(p[act_key] for p in pts) / n,
            "mean_model": sum(p[model_key] for p in pts) / n,
            "bias": sum(p[model_key] - p[act_key] for p in pts) / n,
            "mae_model": sum(err(p, model_key) for p in pts) / n,
            "mae_base": sum(err(p, base_key) for p in pts) / n,
            "dmae": d, "dmae_ci": [lo, hi], "verdict_vs_baseline": verdict(n, lo, hi, min_n)}


def summarise_probs(rows, min_n, draws):
    rs = [r for r in rows if r["p_model"] is not None and r["p_base"] is not None]
    out = {"n_rows": len(rs)}
    if not rs:
        return out
    out["games"] = len({r["game_pk"] for r in rs})
    out["dates"] = len({r["date"] for r in rs})
    out["base_rate"] = sum(r["y"] for r in rs) / len(rs)
    out["brier_model"] = sum(brier(r["p_model"], r["y"]) for r in rs) / len(rs)
    out["brier_base"] = sum(brier(r["p_base"], r["y"]) for r in rs) / len(rs)
    d, lo, hi = cluster_boot_ci(rs, lambda r: brier(r["p_model"], r["y"]) - brier(r["p_base"], r["y"]), draws=draws)
    out["dbrier_vs_base"], out["dbrier_vs_base_ci"] = d, [lo, hi]
    out["verdict_vs_baseline"] = verdict(len(rs), lo, hi, min_n)
    bk = [r for r in rs if r["p_book"] is not None]
    out["n_book_rows"] = len(bk)
    if bk:
        out["book_games"] = len({r["game_pk"] for r in bk})
        out["brier_model_on_book_rows"] = sum(brier(r["p_model"], r["y"]) for r in bk) / len(bk)
        out["brier_book"] = sum(brier(r["p_book"], r["y"]) for r in bk) / len(bk)
        out["logloss_model"] = sum(logloss(r["p_model"], r["y"]) for r in bk) / len(bk)
        out["logloss_book"] = sum(logloss(r["p_book"], r["y"]) for r in bk) / len(bk)
        d, lo, hi = cluster_boot_ci(bk, lambda r: brier(r["p_model"], r["y"]) - brier(r["p_book"], r["y"]), draws=draws)
        out["dbrier_vs_book"], out["dbrier_vs_book_ci"] = d, [lo, hi]
        out["verdict_vs_book"] = verdict(len(bk), lo, hi, min_n)
        # flat-stake EV>0 at the quoted price (side the model prefers)
        bets = []
        for r in bk:
            if not r["dec_a"] or not r["dec_b"]:
                continue
            ev_a = r["p_model"] * r["dec_a"] - 1
            ev_b = (1 - r["p_model"]) * r["dec_b"] - 1
            if max(ev_a, ev_b) <= 0:
                continue
            pnl = (r["dec_a"] - 1 if r["y"] else -1) if ev_a >= ev_b else (r["dec_b"] - 1 if not r["y"] else -1)
            bets.append({"game_pk": r["game_pk"], "pnl": pnl})
        if bets:
            m, lo, hi = cluster_boot_ci(bets, lambda b: b["pnl"], draws=draws)
            out["ev_bets"], out["ev_roi"], out["ev_roi_ci"] = len(bets), m, [lo, hi]
    return out


def gate(point: dict | None, prob: dict) -> str:
    """Probability/edge only if the model beats the baseline AND the book.

    Both legs are judged on the PROPER score (Brier on the priced rows). The
    point dMAE is reported but never gates: MAE is minimised by the median, so on
    a skewed 0/1-heavy stat (HR: model mean 0.055 vs ~0.12 actual) a model that
    under-predicts "beats" the baseline on MAE while losing on Brier.
    """
    if prob.get("verdict_vs_book") is None:
        return "MEAN_ONLY (no two-sided book rows)"
    base_ok = prob.get("verdict_vs_baseline") == "MODEL_BETTER"
    if prob.get("verdict_vs_book") == "MODEL_BETTER" and base_ok:
        return "EARNS_PROBABILITY"
    return "MEAN_ONLY"


def run(args) -> dict:
    data_dir = Path(os.path.expanduser(args.data_root)) / "mlb_source" / "source_artifacts" / "data"
    counters = Counter()
    sims = load_pregame_sims(data_dir / "daily", None, counters)
    gl = load_snapshots(data_dir, "game_lines")
    hp = load_snapshots(data_dir, "hitter_props")
    pp = load_snapshots(data_dir, "pitcher_props")
    api = StatsApi(Path(os.path.expanduser(args.cache)), offline=args.offline)
    sched = {}
    for gt in ("R", "F", "D", "L", "W"):
        sched.update(schedule_games(api.season_schedule(args.season, gt)))
    sims = {pk: s for pk, s in sims.items() if s["_date"].startswith(str(args.season))}

    # ---- coverage, per family and intersection (CLAUDE.md coverage-trap rule)
    def pregame_dates(snaps):
        return {d for d, docs in snaps.items() if docs}
    fam = {
        "sims_pregame": {s["_date"] for s in sims.values()},
        "game_lines": pregame_dates(gl),
        "hitter_props": pregame_dates(hp),
        "pitcher_props": pregame_dates(pp),
        "outcomes_final": {sched[pk]["date"] for pk in sims if pk in sched and sched[pk]["status"] == "Final"},
    }
    inter_lines = fam["sims_pregame"] & fam["game_lines"] & fam["outcomes_final"]
    inter_props = fam["sims_pregame"] & fam["hitter_props"] & fam["pitcher_props"] & fam["outcomes_final"]
    coverage = {k: {"dates": len(v), "first": min(v) if v else None, "last": max(v) if v else None}
                for k, v in fam.items()}
    coverage["intersection_game_lines"] = {"dates": len(inter_lines), "list": sorted(inter_lines)}
    coverage["intersection_props"] = {"dates": len(inter_props), "list": sorted(inter_props)}

    team_asof = TeamAsOf(sched)
    g_rows, g_points = build_game_rows(sims, sched, team_asof, gl, counters)
    p_rows, p_points = build_prop_rows(sims, sched, api, hp, pp, args.season, args.workers, counters,
                                       args.min_prior_games)

    report = {"generated_at": datetime.now(timezone.utc).isoformat(), "args": vars(args),
              "coverage": coverage, "counters": dict(sorted(counters.items())),
              "statsapi_fetched": api.fetched, "arms": {}}
    for arm, gtypes in (("regular", {"R"}), ("postseason", {"F", "D", "L", "W"})):
        res = {"game_lines": {}, "props": {}}
        gp = [p for p in g_points if p["gtype"] in gtypes]
        gr = [r for r in g_rows if r["gtype"] in gtypes]
        for seg in SEGMENTS:
            sp = [p for p in gp if p["segment"] == seg]
            res["game_lines"][f"{seg}:total_runs_mean"] = summarise_points(
                sp, "model_total", "base_total", "act_total", args.min_n, args.draws)
            res["game_lines"][f"{seg}:run_margin_mean"] = summarise_points(
                sp, "model_margin", "base_margin", "act_margin", args.min_n, args.draws)
        for mkt in sorted({r["market"] for r in gr}):
            prob = summarise_probs([r for r in gr if r["market"] == mkt], args.min_n, args.draws)
            seg, kind = mkt.split(":")
            pt_key = f"{seg}:total_runs_mean" if kind == "total" else f"{seg}:run_margin_mean"
            prob["gate"] = gate(res["game_lines"].get(pt_key) if kind != "moneyline" else None, prob)
            res["game_lines"][mkt] = prob
        pp_ = [p for p in p_points if p["gtype"] in gtypes]
        pr = [r for r in p_rows if r["gtype"] in gtypes]
        for mkt in list(HITTER_MARKETS) + list(PITCHER_MARKETS):
            point = summarise_points([p for p in pp_ if p["market"] == mkt], "model", "base", "act",
                                     args.min_n, args.draws)
            point10 = summarise_points([p for p in pp_ if p["market"] == mkt], "model", "base10", "act",
                                       args.min_n, args.draws)
            prob = summarise_probs([r for r in pr if r["market"] == mkt], args.min_n, args.draws)
            prob["gate"] = gate(point, prob)
            res["props"][mkt] = {"point_vs_season_avg": point, "point_vs_last10": point10, "prob": prob}
        report["arms"][arm] = res
    return report


def fmt(x, nd=4):
    return "-" if x is None else (f"{x:+.{nd}f}" if isinstance(x, float) else str(x))


def ci(c, nd=4):
    return "-" if not c or c[0] is None else f"[{c[0]:+.{nd}f}, {c[1]:+.{nd}f}]"


def render_md(rep: dict) -> str:
    L = ["# MLB lines + props AS-OF backtest", "", f"generated {rep['generated_at']}", "", "## Coverage", ""]
    for k, v in rep["coverage"].items():
        L.append(f"- {k}: {v['dates']} dates" + (f" ({v.get('first')}..{v.get('last')})" if "first" in v else ""))
    L += ["", "## Counters (drops are counted, never silent)", ""]
    L += [f"- {k}: {v}" for k, v in rep["counters"].items()]
    for arm, res in rep["arms"].items():
        L += ["", f"## {arm.upper()}", "", "### Game lines -- point (model mean vs team as-of baseline)", "",
              "| market | n | games | bias | MAE model | MAE base | dMAE [95% CI] | verdict |", "|---|---|---|---|---|---|---|---|"]
        for k, v in res["game_lines"].items():
            if v and "mae_model" in v:
                L.append(f"| {k} | {v['n']} | {v['games']} | {fmt(v['bias'],3)} | {v['mae_model']:.3f} | "
                         f"{v['mae_base']:.3f} | {fmt(v['dmae'],4)} {ci(v['dmae_ci'])} | {v['verdict_vs_baseline']} |")
        L += ["", "### Game lines -- probability", "",
              "| market | rows | dBrier vs base [CI] | book rows | Brier model / book | dBrier vs book [CI] | logloss model / book | EV>0 bets, ROI [CI] | gate |",
              "|---|---|---|---|---|---|---|---|---|"]
        for k, v in res["game_lines"].items():
            if v and "n_rows" in v:
                L.append(_prob_line(k, v))
        L += ["", "### Props -- point (model mean vs player's own as-of season average)", "",
              "| market | n | games | bias | MAE model | MAE base | dMAE [95% CI] | verdict | dMAE vs last-10 [CI] |",
              "|---|---|---|---|---|---|---|---|---|"]
        for k, v in res["props"].items():
            p, p10 = v["point_vs_season_avg"], v["point_vs_last10"]
            if p:
                L.append(f"| {k} | {p['n']} | {p['games']} | {fmt(p['bias'],3)} | {p['mae_model']:.3f} | "
                         f"{p['mae_base']:.3f} | {fmt(p['dmae'])} {ci(p['dmae_ci'])} | {p['verdict_vs_baseline']} | "
                         f"{fmt(p10['dmae']) if p10 else '-'} {ci(p10['dmae_ci']) if p10 else ''} |")
            else:
                L.append(f"| {k} | 0 | | | | | | INSUFFICIENT_N | |")
        L += ["", "### Props -- probability (baseline = player's own as-of rate of clearing the line)", "",
              "| market | rows | dBrier vs base [CI] | book rows | Brier model / book | dBrier vs book [CI] | logloss model / book | EV>0 bets, ROI [CI] | gate |",
              "|---|---|---|---|---|---|---|---|---|"]
        for k, v in res["props"].items():
            L.append(_prob_line(k, v["prob"]))
    return "\n".join(L) + "\n"


def _prob_line(k, v):
    if not v.get("n_rows"):
        return f"| {k} | 0 | | | | | | | {v.get('gate', '-')} |"
    bm = f"{v['brier_model_on_book_rows']:.4f} / {v['brier_book']:.4f}" if v.get("n_book_rows") else "-"
    ll = f"{v['logloss_model']:.4f} / {v['logloss_book']:.4f}" if v.get("n_book_rows") else "-"
    roi = f"{v['ev_bets']}, {fmt(v['ev_roi'],3)} {ci(v['ev_roi_ci'],3)}" if v.get("ev_bets") else "-"
    return (f"| {k} | {v['n_rows']} | {fmt(v['dbrier_vs_base'])} {ci(v['dbrier_vs_base_ci'])} "
            f"({v['verdict_vs_baseline']}) | {v.get('n_book_rows', 0)} | {bm} | "
            f"{fmt(v.get('dbrier_vs_book'))} {ci(v.get('dbrier_vs_book_ci'))} ({v.get('verdict_vs_book', '-')}) | "
            f"{ll} | {roi} | {v['gate']} |")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data-root", default=os.environ.get("SYNDICATE_DATA_ROOT", "data"),
                    help="root holding mlb_source/ (production's disk: the fleet data root)")
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--cache", default=os.path.join(os.environ.get("TMPDIR", "/tmp"), "mlb_lines_props_bt_cache"))
    ap.add_argument("--out", required=True)
    ap.add_argument("--min-n", type=int, default=200, help="NHL template: verdict needs n >= this")
    ap.add_argument("--min-prior-games", type=int, default=5, help="as-of games needed for a player baseline")
    ap.add_argument("--draws", type=int, default=1000)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--offline", action="store_true", help="StatsAPI from cache only")
    args = ap.parse_args(argv)
    rep = run(args)
    out = Path(os.path.expanduser(args.out))
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(rep, indent=1, default=str), encoding="utf-8")
    (out / "report.md").write_text(render_md(rep), encoding="utf-8")
    print(render_md(rep))
    return 0


if __name__ == "__main__":
    sys.exit(main())
