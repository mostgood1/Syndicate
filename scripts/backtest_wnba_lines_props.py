"""Backtest: do the WNBA pregame models beat a naive baseline AND the de-vigged book? (lane `wnba-lines-props-backtest`)

Mirrors the NHL props template (`scripts/backtest_nhl_props.py`, lane `nhl-player-props-projection`, 0f25d513):
one backtest over completed games, every input AS-OF (only what existed before tip-off), and per market

  * point accuracy -- n, mean actual, mean projected, bias, MAE, RMSE -- against a NAIVE BASELINE, with the MAE
    delta carrying a GAME-clustered bootstrap 95% CI. Props: the player's own as-of season average (b = last-10).
    Game lines: the teams' own as-of averages (margin = HCA + (home net - away net)/2, total = mean of the four
    as-of points-for/against), plus the as-of league constant as a weaker reference.
  * probability quality -- Brier and log-loss of the MODEL's probability against the DE-VIGGED BOOK's probability
    on the SAME rows (pushes excluded), paired difference with a game-clustered CI.

and a per-market COMPARISON LABEL saying which of the two references the model beats, with CIs. This is a
DIAGNOSIS, not a gate: by user decision (2026-10-02, "every line is its own decision. we should have a model that is
accurate that then helps inform each decision") a losing market is a model to fix, never a market to withhold.
"no skill" is a result and is printed as such. No label is emitted below --min-n rows.

WHERE EACH INPUT COMES FROM (the substrate is printed per family, with date coverage and the intersection):
  * finals + quarter linescores: ESPN public scoreboard (`--espn-dir`, one `sb_<date>.json` per Central date).
  * player actuals + the as-of baselines: `boxscores_<date>.csv` (ESPN-sourced, written by
    `scripts/build_wnba_boxscores.py`), read from the fleet disk (`--box-dir`). DNPs (MIN == 0) are dropped, never
    scored as zeros.
  * the book: OddsAPI HISTORICAL snapshots at tip - 60 min (`--odds-dir`, one `<espn_id>.json` per game). The
    snapshot is the one AT OR BEFORE the requested time, so it is as-of by construction. Per book, two-sided
    markets are de-vigged proportionally; the consensus is the median fair probability across books at the MODAL
    line. One-sided quotes are excluded and counted.
  * the model: `--model-dir`, one or more trees holding production-schema `predictions_<date>.csv` (game model)
    and `props_predictions_<date>.csv` (props model), each tagged with its provenance (production artifact vs
    as-of re-run). Rows from the vendor `source_artifacts` root are NEVER mixed with the Syndicate root
    (`[wnba-two-artifact-roots]`): pass them as a separate source and they are reported separately.

Usage:
  py -3 scripts/backtest_wnba_lines_props.py --espn-dir C:/tmp/wnba_bt/espn --box-dir C:/tmp/wnba_bt/box \\
      --odds-dir C:/tmp/wnba_bt/odds_hist --model asof=C:/tmp/wnba_bt/asof --out C:/tmp/wnba_bt/report
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import random
import re
import statistics
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

# ESPN tri-code -> the codes Syndicate's WNBA artifacts carry. ESPN's differ for five clubs; this mismatch is why
# `backtest_wnba_projection.py` joins 0 games even on dates that DO carry a projection.
ESPN_TO_SYND = {"GS": "GSV", "LV": "LVA", "LA": "LAS", "NY": "NYL", "CONN": "CON"}
SYND_ALIASES = {"WAS": "WSH", "CONN": "CON", "GS": "GSV", "LV": "LVA", "LA": "LAS", "NY": "NYL"}

PROP_MARKETS = {  # OddsAPI market key -> (box-score expression, props-model column)
    "player_points": (("PTS",), "pred_pts"),
    "player_rebounds": (("REB",), "pred_reb"),
    "player_assists": (("AST",), "pred_ast"),
    "player_threes": (("FG3M",), "pred_threes"),
    "player_points_rebounds_assists": (("PTS", "REB", "AST"), "pred_pra"),
    "player_points_rebounds": (("PTS", "REB"), None),
    "player_points_assists": (("PTS", "AST"), None),
    "player_rebounds_assists": (("REB", "AST"), None),
}
YESNO_MARKETS = ("player_double_double", "player_triple_double")
SEGMENTS = ("full", "h1", "h2", "q1", "q2", "q3", "q4")


# ---------------------------------------------------------------------------
# small utils
# ---------------------------------------------------------------------------

def norm_name(s: str) -> str:
    # Apostrophes are DROPPED, not spaced: NFKD+ascii drops a curly one, so spacing a straight one would make
    # "A'ja" and "A’ja" two different players.
    s = str(s or "").replace("'", "").replace("’", "").replace("`", "")
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z ]", " ", s.replace("-", " "))
    toks = [t for t in s.split() if t not in {"jr", "sr", "ii", "iii", "iv"}]
    return " ".join(toks)


def implied(o: object) -> Optional[float]:
    """American price -> implied probability, or None when there is no quotable price (0, None, "", unparseable).
    Same contract as `backtest_mlb_lines_props.american_to_prob` (5/5 in `scripts/probability_differential.py`):
    a price of 0 must never become a probability of 0.0."""
    try:
        v = float(str(o).replace("+", ""))
    except (TypeError, ValueError):
        return None
    if v == 0 or not math.isfinite(v):
        return None
    return 100.0 / (v + 100.0) if v > 0 else -v / (-v + 100.0)


def clip(p: float, lo: float = 1e-3) -> float:
    return min(1 - lo, max(lo, p))


def logloss(p: float, y: int) -> float:
    p = clip(p)
    return -(math.log(p) if y else math.log(1 - p))


def phi(z: float) -> float:
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def boot_ci(rows: List[Tuple[str, float]], n_boot: int = 2000, seed: int = 7) -> Dict:
    """Mean of per-row values with a GAME-clustered bootstrap 95% CI (same estimator as the NHL harness)."""
    by_g: Dict[str, List[float]] = defaultdict(list)
    for g, v in rows:
        by_g[g].append(v)
    keys = list(by_g)
    if not keys:
        return {"point": None, "ci95": [None, None]}
    sums = [sum(by_g[k]) for k in keys]
    cnts = [len(by_g[k]) for k in keys]
    point = sum(sums) / sum(cnts)
    rng = random.Random(seed)
    n = len(keys)
    stats = []
    for _ in range(n_boot):
        s = c = 0.0
        for _j in range(n):
            i = rng.randrange(n)
            s += sums[i]
            c += cnts[i]
        stats.append(s / c)
    stats.sort()
    return {"point": round(point, 5), "ci95": [round(stats[int(0.025 * n_boot)], 5), round(stats[int(0.975 * n_boot) - 1], 5)]}


def ci_below_zero(d: Dict) -> bool:
    return d.get("ci95") is not None and d["ci95"][1] is not None and d["ci95"][1] < 0


def ci_above_zero(d: Dict) -> bool:
    return d.get("ci95") is not None and d["ci95"][0] is not None and d["ci95"][0] > 0


def point_metrics(pred: List[float], act: List[float]) -> Dict:
    n = len(pred)
    if not n:
        return {"n": 0}
    err = [p - a for p, a in zip(pred, act)]
    return {"n": n, "mean_pred": round(sum(pred) / n, 4), "bias": round(sum(err) / n, 4),
            "mae": round(sum(abs(e) for e in err) / n, 4), "rmse": round(math.sqrt(sum(e * e for e in err) / n), 4)}


def prob_metrics(ps: List[float], ys: List[int]) -> Dict:
    n = len(ps)
    if not n:
        return {"n": 0}
    return {"n": n, "mean_p": round(sum(ps) / n, 4), "brier": round(sum((p - y) ** 2 for p, y in zip(ps, ys)) / n, 5),
            "logloss": round(sum(logloss(p, y) for p, y in zip(ps, ys)) / n, 5)}


def auc(ps: List[float], ys: List[int]) -> Optional[float]:
    """Mann-Whitney AUC (ties count half)."""
    pos = [p for p, y in zip(ps, ys) if y]
    neg = [p for p, y in zip(ps, ys) if not y]
    if not pos or not neg:
        return None
    s = sum((1.0 if a > b else 0.5 if a == b else 0.0) for a in pos for b in neg)
    return round(s / (len(pos) * len(neg)), 4)


def reliability(ps: List[float], ys: List[int], bins: int = 10) -> List[Dict]:
    order = sorted(range(len(ps)), key=lambda i: ps[i])
    n = len(order)
    out = []
    for b in range(bins):
        idx = order[b * n // bins:(b + 1) * n // bins]
        if idx:
            out.append({"mean_pred": round(sum(ps[i] for i in idx) / len(idx), 3),
                        "obs": round(sum(ys[i] for i in idx) / len(idx), 3), "n": len(idx)})
    return out


# ---------------------------------------------------------------------------
# 1. ground truth: ESPN finals + linescores
# ---------------------------------------------------------------------------

def load_games(espn_dir: Path) -> Dict[str, Dict]:
    """Every completed 2026 regular-season / post-season game, keyed by ESPN event id. Exhibition (All-Star,
    preseason) excluded. `date` is the Central date of the scoreboard the event was listed on."""
    games: Dict[str, Dict] = {}
    for p in sorted(espn_dir.glob("sb_*.json")):
        sb_date = p.stem[3:]
        for e in json.loads(p.read_text(encoding="utf-8")).get("events", []):
            slug = (e.get("season") or {}).get("slug")
            comp = (e.get("competitions") or [{}])[0]
            ctype = (comp.get("type") or {}).get("abbreviation")
            if slug not in ("regular-season", "post-season") or ctype == "ALLSTAR":
                continue
            if not ((e.get("status") or {}).get("type") or {}).get("completed"):
                continue
            side = {}
            for c in comp.get("competitors") or []:
                ls = [float(x.get("value", 0)) for x in (c.get("linescores") or [])]
                side[c["homeAway"]] = {"espn_tri": c["team"]["abbreviation"], "name": c["team"]["displayName"],
                                       "score": int(c["score"]), "ls": ls}
            if set(side) != {"home", "away"}:
                continue
            h, a = side["home"], side["away"]
            g = {"id": e["id"], "date": sb_date, "tip": e["date"], "phase": "regular" if slug == "regular-season" else "playoff",
                 "ctype": ctype, "home": ESPN_TO_SYND.get(h["espn_tri"], h["espn_tri"]),
                 "away": ESPN_TO_SYND.get(a["espn_tri"], a["espn_tri"]), "home_name": h["name"], "away_name": a["name"],
                 "home_pts": h["score"], "away_pts": a["score"], "ot": max(len(h["ls"]), len(a["ls"])) > 4}
            seg = {"full": (h["score"] - a["score"], h["score"] + a["score"])}
            if len(h["ls"]) >= 4 and len(a["ls"]) >= 4:
                for i in range(4):
                    seg[f"q{i + 1}"] = (h["ls"][i] - a["ls"][i], h["ls"][i] + a["ls"][i])
                seg["h1"] = (seg["q1"][0] + seg["q2"][0], seg["q1"][1] + seg["q2"][1])
                # OddsAPI basketball second-half markets include overtime.
                seg["h2"] = (sum(h["ls"][2:]) - sum(a["ls"][2:]), sum(h["ls"][2:]) + sum(a["ls"][2:]))
            g["seg"] = seg
            games[g["id"]] = g
    return games


# ---------------------------------------------------------------------------
# 2. player actuals + as-of player / team history
# ---------------------------------------------------------------------------

def _f(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def load_box(box_dir: Path, games: Dict[str, Dict]) -> Tuple[Dict[str, Dict[str, Dict]], Dict]:
    """{espn_id: {player_key: row}} for players who PLAYED (MIN > 0). player_key = normalised name + team."""
    out: Dict[str, Dict[str, Dict]] = defaultdict(dict)
    stats = Counter()
    for p in sorted(box_dir.glob("boxscores_2026-*.csv")):
        with p.open(encoding="utf-8", errors="replace") as fh:
            for r in csv.DictReader(fh):
                gid = str(r.get("game_id") or r.get("gameId") or "").strip()
                if gid not in games:
                    stats["rows_not_a_scored_game"] += 1
                    continue
                if _f(r.get("MIN")) <= 0:
                    stats["dnp_dropped"] += 1
                    continue
                row = {k: _f(r.get(k)) for k in ("MIN", "PTS", "REB", "AST", "FG3M", "STL", "BLK", "TOV")}
                row.update(name=r.get("PLAYER_NAME", ""), team=SYND_ALIASES.get(str(r.get("TEAM_ABBREVIATION")).upper(),
                                                                                   str(r.get("TEAM_ABBREVIATION")).upper()),
                           pid=str(r.get("PLAYER_ID") or ""))
                out[gid][norm_name(row["name"])] = row
                stats["played_rows"] += 1
    return out, dict(stats)


class History:
    """As-of history: a game's own row is never visible to it (strictly earlier tip time)."""

    def __init__(self, games: Dict[str, Dict], box: Dict[str, Dict[str, Dict]]) -> None:
        self.order = sorted(games.values(), key=lambda g: g["tip"])
        self.player: Dict[str, List[Tuple[str, Dict]]] = defaultdict(list)
        for g in self.order:
            for k, r in box.get(g["id"], {}).items():
                self.player[k].append((g["tip"], r))

    def player_avg(self, key: str, tip: str, last: Optional[int] = None) -> Tuple[Optional[Dict[str, float]], int]:
        rows = [r for t, r in self.player.get(key, []) if t < tip]
        if last:
            rows = rows[-last:]
        if not rows:
            return None, 0
        return {s: sum(r[s] for r in rows) / len(rows) for s in ("MIN", "PTS", "REB", "AST", "FG3M", "STL", "BLK", "TOV")}, len(rows)

    def player_sd(self, key: str, tip: str, expr: Tuple[str, ...]) -> Optional[float]:
        vals = [sum(r[s] for s in expr) for t, r in self.player.get(key, []) if t < tip]
        return statistics.pstdev(vals) if len(vals) >= 3 else None

    def team_naive(self, g: Dict) -> Optional[Dict[str, Dict[str, float]]]:
        """Naive game-line baseline from the teams' OWN as-of results (regular + playoff games before tip)."""
        cache = self.__dict__.setdefault("_naive_cache", {})
        if g["id"] not in cache:
            cache[g["id"]] = self._team_naive(g)
        return cache[g["id"]]

    def _team_naive(self, g: Dict) -> Optional[Dict[str, Dict[str, float]]]:
        prior = [x for x in self.order if x["tip"] < g["tip"]]
        if len(prior) < 20:
            return None
        hca = statistics.fmean(x["seg"]["full"][0] for x in prior)
        lg_total = statistics.fmean(x["seg"]["full"][1] for x in prior)

        def team(t: str):
            pf, pa = [], []
            for x in prior:
                if x["home"] == t:
                    pf.append(x["home_pts"]); pa.append(x["away_pts"])
                elif x["away"] == t:
                    pf.append(x["away_pts"]); pa.append(x["home_pts"])
            return (statistics.fmean(pf), statistics.fmean(pa), len(pf)) if len(pf) >= 3 else None

        h, a = team(g["home"]), team(g["away"])
        if not h or not a:
            return None
        seg = {}
        full_m = hca + ((h[0] - h[1]) - (a[0] - a[1])) / 2.0
        full_t = (h[0] + h[1] + a[0] + a[1]) / 2.0
        seg["full"] = {"margin": full_m, "total": full_t, "const_margin": hca, "const_total": lg_total}
        # Segment baselines scale the full-game naive line by the league's as-of segment share.
        for s in ("h1", "h2", "q1", "q2", "q3", "q4"):
            ms = [x["seg"][s][0] for x in prior if s in x["seg"]]
            ts = [x["seg"][s][1] for x in prior if s in x["seg"]]
            if not ms:
                continue
            share = statistics.fmean(ts) / lg_total
            seg[s] = {"margin": full_m * share, "total": full_t * share, "const_margin": statistics.fmean(ms),
                      "const_total": statistics.fmean(ts)}
        return seg


# ---------------------------------------------------------------------------
# 3. the book: OddsAPI historical snapshots, de-vigged
# ---------------------------------------------------------------------------

def _modal(points: Iterable[float]) -> Optional[float]:
    c = Counter(points)
    if not c:
        return None
    top = max(c.values())
    return sorted(p for p, n in c.items() if n == top)[len(sorted(p for p, n in c.items() if n == top)) // 2]


def load_book(odds_dir: Path, games: Dict[str, Dict]) -> Tuple[Dict[str, Dict], Dict]:
    """{espn_id: {"game": {(market, segment): fair}, "props": {(player_key, market): fair}}}.

    fair for spreads = {"line": home point, "p": P(home covers)}; totals/props = {"line", "p": P(over)};
    h2h = {"p": P(home wins)}; yes/no props = {"p": P(yes)}. Median across books of the per-book proportional
    de-vig, at the modal line. Every exclusion is counted."""
    out: Dict[str, Dict] = {}
    cnt = Counter()
    for gid, g in games.items():
        p = odds_dir / f"{gid}.json"
        if not p.exists():
            cnt["game_no_snapshot_file"] += 1
            continue
        rec = json.loads(p.read_text(encoding="utf-8"))
        if rec.get("error"):
            cnt[f"game_{rec['error']}"] += 1
            continue
        res = {"game": {}, "props": {}, "snapshot": (rec.get("game") or {}).get("timestamp"),
               "tip": rec.get("tip")}
        # ---- game markets
        per_mkt: Dict[Tuple[str, str], List[Tuple[str, Dict]]] = defaultdict(list)
        for bm in ((rec.get("game") or {}).get("data") or {}).get("bookmakers", []):
            for m in bm.get("markets", []):
                key = m["key"]
                base, _, seg = key.partition("_")
                seg = seg or "full"
                if base not in ("h2h", "spreads", "totals") or seg not in SEGMENTS:
                    continue
                per_mkt[(base, seg)].append((bm["key"], m))
        for (base, seg), books in per_mkt.items():
            fair = []
            for _bk, m in books:
                oc = m.get("outcomes", [])
                if base == "h2h":
                    hp = [o for o in oc if o["name"] == g["home_name"]]
                    ap = [o for o in oc if o["name"] == g["away_name"]]
                    if len(oc) != 2 or not hp or not ap:
                        cnt["h2h_not_two_way"] += 1
                        continue
                    ih, ia = implied(hp[0]["price"]), implied(ap[0]["price"])
                    if ih is None or ia is None:
                        cnt["unpriceable_quote"] += 1
                        continue
                    fair.append((None, ih / (ih + ia)))
                elif base == "spreads":
                    hp = [o for o in oc if o["name"] == g["home_name"]]
                    ap = [o for o in oc if o["name"] == g["away_name"]]
                    if not hp or not ap or abs(hp[0]["point"] + ap[0]["point"]) > 1e-9:
                        cnt["spread_unpaired"] += 1
                        continue
                    ih, ia = implied(hp[0]["price"]), implied(ap[0]["price"])
                    if ih is None or ia is None:
                        cnt["unpriceable_quote"] += 1
                        continue
                    fair.append((hp[0]["point"], ih / (ih + ia)))
                else:
                    ov = [o for o in oc if o["name"] == "Over"]
                    un = [o for o in oc if o["name"] == "Under"]
                    if not ov or not un or ov[0]["point"] != un[0]["point"]:
                        cnt["total_unpaired"] += 1
                        continue
                    io, iu = implied(ov[0]["price"]), implied(un[0]["price"])
                    if io is None or iu is None:
                        cnt["unpriceable_quote"] += 1
                        continue
                    fair.append((ov[0]["point"], io / (io + iu)))
            if not fair:
                continue
            if base == "h2h":
                res["game"][(base, seg)] = {"p": statistics.median(f[1] for f in fair), "books": len(fair)}
            else:
                line = _modal(f[0] for f in fair)
                at = [f[1] for f in fair if f[0] == line]
                res["game"][(base, seg)] = {"line": line, "p": statistics.median(at), "books": len(at)}
        # ---- props
        per_prop: Dict[Tuple[str, str], List[Tuple[Optional[float], float]]] = defaultdict(list)
        for bm in ((rec.get("props") or {}).get("data") or {}).get("bookmakers", []):
            for m in bm.get("markets", []):
                mk = m["key"]
                by_player: Dict[str, Dict[str, Dict]] = defaultdict(dict)
                for o in m.get("outcomes", []):
                    by_player[norm_name(o.get("description", ""))][o["name"]] = o
                for pk, sides in by_player.items():
                    if mk in YESNO_MARKETS:
                        if "Yes" in sides and "No" in sides:
                            iy, iN = implied(sides["Yes"]["price"]), implied(sides["No"]["price"])
                            if iy is None or iN is None:
                                cnt[f"prop_unpriceable:{mk}"] += 1
                                continue
                            per_prop[(pk, mk)].append((None, iy / (iy + iN)))
                        else:
                            cnt[f"prop_one_sided:{mk}"] += 1
                        continue
                    o, u = sides.get("Over"), sides.get("Under")
                    if not o or not u or o.get("point") != u.get("point"):
                        cnt[f"prop_one_sided:{mk}"] += 1
                        continue
                    io, iu = implied(o["price"]), implied(u["price"])
                    if io is None or iu is None:
                        cnt[f"prop_unpriceable:{mk}"] += 1
                        continue
                    per_prop[(pk, mk)].append((o["point"], io / (io + iu)))
        for (pk, mk), fair in per_prop.items():
            if mk in YESNO_MARKETS:
                res["props"][(pk, mk)] = {"p": statistics.median(f[1] for f in fair), "books": len(fair)}
            else:
                line = _modal(f[0] for f in fair)
                at = [f[1] for f in fair if f[0] == line]
                res["props"][(pk, mk)] = {"line": line, "p": statistics.median(at), "books": len(at)}
        out[gid] = res
        cnt["game_with_book"] += 1
    return out, dict(cnt)


# ---------------------------------------------------------------------------
# 4. AS-OF RE-RUN of the production prediction path (today's code, inputs truncated to before each date)
# ---------------------------------------------------------------------------
#
# Production's own stored predictions for most of 2026 were on Render's disk and were never exported, so the
# full-season arm RE-RUNS the production path. It runs on a SCRATCH copy of the data root, never the fleet disk.
# Per date D, in date order:
#   phase "game" (sequential, because the game-bias calibration reads the prior 30 days' predictions):
#     truncate every history input to games strictly before D; write D's pregame odds snapshot in the production
#     schema; seed game_odds_D with production's own `_seed_game_odds_from_props_snapshot`;
#     `wnba_betting.cli predict-date --date D --merge-odds game_odds_D.csv` (production runs it without
#     --merge-odds and lets it fetch CURRENT odds -- which at D-pregame were these odds; here the key is unset so
#     it CANNOT fetch today's); `build_wnba_totals_calibration.py --date D`.
#   phase "sim" (parallel workers, each on its own scratch tree): restore the phase-1 outputs dated <= D, then
#     `export_props_predictions_local` with production's arguments (refresh_wnba_oddsapi_props.py:4981-4999).
# NOT AS-OF, stated in the report: the model weights (`vendor/.../models/*.onnx`, single commit 2026-05-25,
# ~867 pre-2026 games, never retrained in production); the code is TODAY's, not the SHA production ran per date.
# ABSENT, as for most of production's season: pregame injuries, expected minutes, rotation/lineup history,
# league_status/rosters -- each has a production fallback, which is what runs here.
# REMOVED because each is fit on the full season: home_court_advantage.json, lineup_*.parquet,
# team_period_shares.csv, every team_advanced_stats_* file (the engine rebuilds it from the truncated history).

HISTORY_FILES = {  # file -> date column; truncated to rows with date < D
    "raw/games_nba_api.csv": "date",
    "processed/features.csv": "date",
    "processed/boxscores_history.csv": "date",
    "processed/player_logs.csv": "GAME_DATE",
}
REMOVE_ALWAYS = ("processed/features.parquet", "raw/games_nba_api.parquet", "processed/team_period_shares.csv",
                 "processed/home_court_advantage.json", "processed/lineup_player_baselines.parquet",
                 "processed/lineup_teammate_effects.parquet", "raw/injuries.csv",
                 "processed/rotation_stints_history.csv", "processed/rotation_stints_history.parquet",
                 "processed/pbp_espn_history.csv", "processed/pbp_espn_history.parquet",
                 "processed/pair_minutes_history.csv", "processed/pair_minutes_history.parquet",
                 "processed/play_context_history.csv", "processed/play_context_history.parquet",
                 "processed/player_stat_calibration.json", "processed/quarters_blend_weights.json")
DATED_RE = re.compile(r"(20\d\d-\d\d-\d\d)")
DATED_INPUT_PREFIXES = ("boxscores_", "recon_games_", "recon_props_", "recon_quarters_", "recon_players_")
DATED_OUTPUT_PREFIXES = ("predictions_", "game_odds_", "calibration_totals_", "calibration_games_",
                         "calibration_period_probs_", "oddsapi_player_props_", "odds_wnba_player_props_",
                         "props_predictions_", "smart_sim_", "game_cards_", "props_edges_", "props_recommendations_",
                         "cards_sim_detail_", "props_calibration_", "props_player_calibration_used_",
                         "team_advanced_stats_", "pregame_expected_minutes_", "league_status_", "_rotation_inputs_",
                         ".predict_date_attempt_", "injuries_excluded_")
PHASE1_OUTPUTS = ("predictions_", "calibration_totals_", "calibration_games_", "game_odds_", "oddsapi_player_props_")


def _date_of(name: str) -> Optional[str]:
    m = DATED_RE.search(name)
    return m.group(1) if m else None


def _truncate_csv(src: Path, dst: Path, col: str, cutoff: str) -> int:
    import pandas as pd
    df = pd.read_csv(src, low_memory=False)
    d = pd.to_datetime(df[col], errors="coerce").dt.strftime("%Y-%m-%d")
    out = df[d < cutoff]
    dst.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(dst, index=False)
    return len(out)


def prepare_scratch(pristine: Path, scratch: Path, date: str, archive: Optional[Path], restore_upto_incl: bool) -> Dict:
    """Make `scratch/wnba_source/data` an as-of view of `pristine` for slate `date`."""
    import shutil
    pdata, sdata = pristine / "wnba_source" / "data", scratch / "wnba_source" / "data"
    info: Dict = {"date": date}
    for sub in ("raw", "processed"):
        (sdata / sub).mkdir(parents=True, exist_ok=True)
    if not (scratch / "wnba_source" / "src").exists():
        shutil.copytree(pristine / "wnba_source" / "src", scratch / "wnba_source" / "src")
    for p in (pdata / "processed").glob("schedule_*"):
        shutil.copy2(p, sdata / "processed" / p.name)
    for rel, col in HISTORY_FILES.items():
        if (pdata / rel).exists():
            info[rel] = _truncate_csv(pdata / rel, sdata / rel, col, date)
    for rel in REMOVE_ALWAYS:
        (sdata / rel).unlink(missing_ok=True)
    for p in list((sdata / "processed").glob("*")) + list((sdata / "raw").glob("odds_wnba_player_props*")):
        if p.is_file() and _date_of(p.name) and p.name.startswith(DATED_OUTPUT_PREFIXES + DATED_INPUT_PREFIXES):
            p.unlink()
    for p in (pdata / "processed").glob("*"):
        d = _date_of(p.name)
        if d and p.name.startswith(DATED_INPUT_PREFIXES) and d < date:
            shutil.copy2(p, sdata / "processed" / p.name)
    if archive is not None:  # phase-1 outputs for earlier dates (and for D itself in phase 2)
        for p in archive.glob("*/*"):
            d = p.parent.name
            if not (d < date or (restore_upto_incl and d == date)):
                continue
            if p.name.startswith(PHASE1_OUTPUTS):
                shutil.copy2(p, sdata / "processed" / p.name)
            if d == date and p.name.startswith("odds_wnba_player_props_"):
                shutil.copy2(p, sdata / "raw" / p.name)
    return info


def write_snapshot_csv(odds_dir: Path, games: Dict[str, Dict], date: str, sdata: Path) -> int:
    """D's pregame OddsAPI historical snapshot, in the production `oddsapi_player_props_<D>.csv` schema."""
    cols = ["snapshot_ts", "event_id", "commence_time", "bookmaker", "bookmaker_title", "market", "outcome_name",
            "player_name", "point", "price", "last_update", "home_team", "away_team"]
    rows = []
    for gid, g in games.items():
        if g["date"] != date or not (odds_dir / f"{gid}.json").exists():
            continue
        rec = json.loads((odds_dir / f"{gid}.json").read_text(encoding="utf-8"))
        for part in ("game", "props"):
            blob = rec.get(part) or {}
            data = blob.get("data") or {}
            for bm in data.get("bookmakers", []):
                for m in bm.get("markets", []):
                    for o in m.get("outcomes", []):
                        rows.append([blob.get("timestamp"), data.get("id"), data.get("commence_time"), bm["key"],
                                     bm.get("title"), m["key"], o.get("name"), o.get("description", ""),
                                     o.get("point", ""), o.get("price"), m.get("last_update"),
                                     data.get("home_team"), data.get("away_team")])
    for path in (sdata / "processed" / f"oddsapi_player_props_{date}.csv",
                 sdata / "raw" / f"odds_wnba_player_props_{date}.csv"):
        with path.open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(cols)
            w.writerows(rows)
    return len(rows)


def _env_for(scratch: Path, code: Path) -> Dict[str, str]:
    import os
    env = {k: v for k, v in os.environ.items() if k not in ("ODDS_API_KEY", "ODDSAPI_KEY")}
    env.update({"WNBA_BETTING_DATA_ROOT": str(scratch / "wnba_source" / "data"),
                "SYNDICATE_DATA_ROOT": str(scratch), "SYNDICATE_WNBA_SOURCE_ROOT": str(scratch / "wnba_source"),
                "PYTHONPATH": f"{scratch / 'wnba_source' / 'src'}:{code}", "OMP_NUM_THREADS": "1",
                "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1", "PYTHONUNBUFFERED": "1"})
    return env


def _season_dates(args) -> List[str]:
    games = load_games(Path(args.espn_dir))
    dates = sorted({g["date"] for g in games.values()})
    if args.dates:
        lo, hi = args.dates.split("..")
        dates = [d for d in dates if lo <= d <= hi]
    return dates


SEED_SNIPPET = (
    "import sys; sys.path.insert(0, {scripts!r}); sys.path.insert(0, {code!r})\n"
    "from pathlib import Path\n"
    "import refresh_wnba_oddsapi_props as r\n"
    "print('SEEDED', r._seed_game_odds_from_props_snapshot(source_root=Path({src!r}), date_str={d!r}, log_file=Path({log!r})))\n"
)


def run_game_phase(args) -> int:
    """Phase 1, sequential: game model + totals calibration per date."""
    import shutil
    import subprocess
    import sys
    games = load_games(Path(args.espn_dir))
    archive, scratch, pristine, code = Path(args.archive), Path(args.scratch), Path(args.pristine), Path(args.code)
    py = sys.executable
    for d in _season_dates(args):
        out = archive / d
        if (out / f"predictions_{d}.csv").exists():
            continue
        out.mkdir(parents=True, exist_ok=True)
        t0 = datetime.now()
        info = prepare_scratch(pristine, scratch, d, archive, restore_upto_incl=False)
        sdata = scratch / "wnba_source" / "data"
        info["snapshot_rows"] = write_snapshot_csv(Path(args.odds_dir), games, d, sdata)
        # D's slate (matchups only -- known pregame). Production always had one; without it `predict-date` falls
        # through to network scoreboards that fail intermittently from this host ("No games found ... API down").
        with (sdata / "processed" / f"game_cards_{d}.csv").open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["date", "home_team", "visitor_team"])
            w.writerows([[d, g["home_name"], g["away_name"]] for g in games.values() if g["date"] == d])
        env = _env_for(scratch, code)
        with (out / "phase_game.log").open("w", encoding="utf-8") as log:
            seed = SEED_SNIPPET.format(scripts=str(code / "scripts"), code=str(code), src=str(scratch / "wnba_source"),
                                       d=d, log=str(out / "seed.log"))
            info["rc_seed"] = subprocess.run([py, "-c", seed], cwd=str(code), env=env, stdout=log, stderr=log).returncode
            go = sdata / "processed" / f"game_odds_{d}.csv"
            cmd = [py, "-m", "wnba_betting.cli", "predict-date", "--date", d]
            if go.exists():
                cmd += ["--merge-odds", str(go)]
            info["rc_predict"] = subprocess.run(cmd, cwd=str(code / "vendor" / "wnba_betting_repo"), env=env,
                                                stdout=log, stderr=log, timeout=1800).returncode
            info["rc_totals_cal"] = subprocess.run(
                [py, str(code / "scripts" / "build_wnba_totals_calibration.py"), "--date", d],
                cwd=str(code), env=env, stdout=log, stderr=log, timeout=1800).returncode
        for p in (sdata / "processed").glob("*"):
            pd_ = _date_of(p.name)
            if p.is_file() and p.name.startswith(PHASE1_OUTPUTS) and pd_ and pd_ <= d:
                (archive / pd_).mkdir(parents=True, exist_ok=True)
                if not (archive / pd_ / p.name).exists():
                    shutil.copy2(p, archive / pd_ / p.name)
        shutil.copy2(sdata / "raw" / f"odds_wnba_player_props_{d}.csv", out / f"odds_wnba_player_props_{d}.csv")
        info["seconds"] = round((datetime.now() - t0).total_seconds(), 1)
        info["predictions_written"] = (out / f"predictions_{d}.csv").exists()
        (out / "phase_game.json").write_text(json.dumps(info), encoding="utf-8")
        print("GAME", json.dumps(info), flush=True)
    return 0


def run_sim_phase(args) -> int:
    """Phase 2: SmartSim + props for the dates assigned to this worker (round-robin by --worker/--workers)."""
    import os
    import shutil
    import sys
    dates = [d for i, d in enumerate(_season_dates(args)) if i % args.workers == args.worker]
    games_all = load_games(Path(args.espn_dir))
    archive, pristine, code = Path(args.archive), Path(args.pristine), Path(args.code)
    scratch = Path(args.scratch) / f"w{args.worker}"
    prepare_scratch(pristine, scratch, dates[0] if dates else "2026-01-01", None, False)
    for k, v in _env_for(scratch, code).items():
        os.environ[k] = v
    sys.path[:0] = [str(scratch / "wnba_source" / "src"), str(code)]
    from syndicate.features.shared.basketball_props_predictions import export_props_predictions_local
    import time
    for d in dates:
        out = archive / d
        while not (out / "phase_game.json").exists():  # trail the sequential game phase
            time.sleep(20)
        if not (out / f"predictions_{d}.csv").exists() or (out / "phase_sim.json").exists():
            continue
        t0 = datetime.now()
        info = prepare_scratch(pristine, scratch, d, archive, restore_upto_incl=True)
        src_root = scratch / "wnba_source"
        if args.oracle_availability_box:
            info["oracle_excluded"] = write_oracle_exclusions(Path(args.oracle_availability_box), games_all, d,
                                                               src_root / "data" / "processed")
        pred_fp = src_root / "data" / "processed" / f"props_predictions_{d}.csv"
        try:
            rows, _ = export_props_predictions_local(
                source_root=src_root, date_str=d, out_path=pred_fp, calib_window=7, calibrate_player=True,
                player_calib_window=30, player_min_pairs=6, player_shrink_k=8, use_smart_sim=not args.no_sim,
                smart_sim_n_sims=args.n_sims, smart_sim_pbp=True, smart_sim_workers=1, smart_sim_overwrite=True,
                log_file=out / "phase_sim.log")
            info["rows"] = rows
        except Exception as exc:  # noqa: BLE001
            info["error"] = repr(exc)[:500]
        for p in (src_root / "data" / "processed").glob(f"*{d}*"):
            if p.name.startswith(("props_predictions_", "smart_sim_", "props_calibration_",
                                  "props_player_calibration_used_")):
                shutil.copy2(p, out / p.name)
        info["seconds"] = round((datetime.now() - t0).total_seconds(), 1)
        info["n_sims"] = args.n_sims
        (out / "phase_sim.json").write_text(json.dumps(info), encoding="utf-8")
        print("SIM", json.dumps(info), flush=True)
    return 0


def write_oracle_exclusions(box_dir: Path, games: Dict[str, Dict], date: str, processed: Path) -> int:
    """ORACLE, deliberately NOT as-of: mark OUT every player who did not play (absent from the box, or MIN 0) for each
    team on D, through production's own injury path (`injuries_excluded_<D>.csv`, read by
    `_smart_sim_injuries_excluded_map_for_date_local`). Candidates = every name the team's box scores list up to and
    including D. Measures the CEILING of a perfect pregame inactive report; never a forecast."""
    teams_today = {}
    for g in games.values():
        if g["date"] == date:
            teams_today[g["home"]] = g["id"]
            teams_today[g["away"]] = g["id"]
    seen: Dict[str, set] = defaultdict(set)
    played: Dict[str, set] = defaultdict(set)
    for p in sorted(box_dir.glob("boxscores_2026-*.csv")):
        d = _date_of(p.name)
        if not d or d > date:
            continue
        with p.open(encoding="utf-8", errors="replace") as fh:
            for r in csv.DictReader(fh):
                team = SYND_ALIASES.get(str(r.get("TEAM_ABBREVIATION")).upper(), str(r.get("TEAM_ABBREVIATION")).upper())
                if team not in teams_today:
                    continue
                name = str(r.get("PLAYER_NAME") or "")
                seen[team].add(name)
                if str(r.get("game_id") or r.get("gameId") or "") == teams_today[team] and _f(r.get("MIN")) > 0:
                    played[team].add(name)
    rows = [[date, team, name, "OUT"] for team in teams_today for name in sorted(seen[team] - played[team])]
    with (processed / f"injuries_excluded_{date}.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["date", "team_tri", "player", "status"])
        w.writerows(rows)
    return len(rows)


def _rebuild_main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="as-of re-run of the WNBA production prediction path")
    ap.add_argument("phase", choices=("game", "sim"))
    ap.add_argument("--espn-dir", required=True)
    ap.add_argument("--odds-dir", required=True)
    ap.add_argument("--pristine", required=True, help="root holding wnba_source/{data,src}: a COPY of the fleet tree")
    ap.add_argument("--scratch", required=True)
    ap.add_argument("--archive", required=True)
    ap.add_argument("--code", required=True, help="a checkout of the code to run (its vendor/ and scripts/)")
    ap.add_argument("--dates", default="", help="lo..hi")
    ap.add_argument("--worker", type=int, default=0)
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--n-sims", type=int, default=500)
    ap.add_argument("--no-sim", action="store_true")
    ap.add_argument("--oracle-availability-box", default="",
                    help="ORACLE (deliberately not as-of): box-score dir; every player who did not play on D is written "
                         "OUT to injuries_excluded_<D>.csv -- the ceiling of a perfect pregame injury report")
    args = ap.parse_args(argv)
    return run_game_phase(args) if args.phase == "game" else run_sim_phase(args)


# ---------------------------------------------------------------------------
# 5. model sources -> a common shape
# ---------------------------------------------------------------------------
#
# Every source is reduced to
#   games[espn_id][segment] = {"margin", "total", "p_home_win", "cover": f(home_line)->P(home covers),
#                              "over": f(line)->P(over), "how": <how the probability was produced>}
#   props[espn_id][player_key][market] = {"mean", "over": f(line)->P(over) | None, "how"}
# so every source is scored by the same code, against the same baselines and the same book rows.

def _num(v) -> Optional[float]:
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def normal_over(mu: float, sd: float):
    return lambda line: 1 - phi((line - mu) / sd) if sd and sd > 0 else None


def hist_over(values: Dict[float, float]):
    """P(X > line) from a {value: probability-mass} histogram (the board's `_dist_prob_over` shape)."""
    items = sorted(values.items())
    tot = sum(p for _, p in items) or 1.0
    return lambda line: sum(p for v, p in items if v > line) / tot


def match_game(games_by_date_pair: Dict[Tuple[str, str, str], str], date: str, home: str, away: str) -> Optional[str]:
    home, away = SYND_ALIASES.get(home, home), SYND_ALIASES.get(away, away)
    for d in (date,):
        gid = games_by_date_pair.get((d, home, away))
        if gid:
            return gid
    return None


def _pair_index(games: Dict[str, Dict]) -> Dict[Tuple[str, str, str], str]:
    idx = {}
    for gid, g in games.items():
        idx[(g["date"], g["home"], g["away"])] = gid
        # a Central-dated slate can carry a late tip on the next UTC date: index the day before as well
        prev = (datetime.strptime(g["date"], "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
        idx.setdefault((prev, g["home"], g["away"]), gid)
    return idx


LADDER_STAT = {"player_points": "pts", "player_rebounds": "reb", "player_assists": "ast", "player_threes": "threes",
               "player_points_rebounds_assists": "pra", "player_points_rebounds": "pr", "player_points_assists": "pa",
               "player_rebounds_assists": "ra"}


def ladder_over(ladder: List[Dict]):
    """The board's `wnba_projections._hit_prob_over`: P(actual >= floor(line) + 1) off the empirical ladder,
    scanning ascending (the ladder has gaps), 0.0 beyond the highest simulated total."""
    entries = sorted((float(e["total"]), float(e["hitProb"])) for e in ladder if "total" in e and "hitProb" in e)

    def f(line: float) -> float:
        thr = math.floor(float(line)) + 1
        for t, p in entries:
            if t >= thr:
                return max(0.0, min(1.0, p))
        return 0.0
    return f


def load_sim_json_games(paths: Iterable[Path], games: Dict[str, Dict], use_dist: bool = True) -> Tuple[Dict, Dict, Counter]:
    """SmartSim `smart_sim_<D>_<HOME>_<AWAY>.json` -> game + prop predictions.

    Game probability: the segment histogram `score.dist.segments[seg]` when present -- the board's method
    (`wnba_game_projections` -> `prop_projections._dist_prob_over`, P(X > line)); otherwise (the August served
    files predate the histogram) a normal fitted to the sim's own p10/p90, sd = (p90 - p10) / 2.563, and the
    report says so per row (`how`). Props: the sim mean; P(over) from the player's empirical `prop_ladders`
    (the board's `_hit_prob_over`) when present, else normal(sim mean, sim sd)."""
    idx = _pair_index(games)
    gout: Dict[str, Dict] = {}
    pout: Dict[str, Dict] = defaultdict(lambda: defaultdict(dict))
    cnt = Counter()
    for p in paths:
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            cnt["unreadable"] += 1
            continue
        date = str(d.get("date") or _date_of(p.name))
        gid = match_game(idx, date, str(d.get("home")).upper(), str(d.get("away")).upper())
        if not gid:
            cnt["no_final_match"] += 1
            continue
        s = d.get("score") or {}
        if not s and isinstance(d.get("quarters"), list) and d.get("home_team_total_pts_mean") is not None:
            # The May-June 2026 sim layout: per-quarter bivariate normals (mu per side, sigma, corr), no draws.
            # Quarter margin var = 2 s^2 (1 - r); total var = 2 s^2 (1 + r); full game = sum of quarters.
            qs = {}
            for q in d["quarters"]:
                sg, r = float(q.get("home_pts_sigma") or 0), float(q.get("corr") or 0)
                qs[f"q{int(q['q'])}"] = (q["home_pts_mu"] - q["away_pts_mu"], q["home_pts_mu"] + q["away_pts_mu"],
                                         math.sqrt(2 * sg * sg * (1 - r)), math.sqrt(2 * sg * sg * (1 + r)))
            def _blk(keys):
                m = sum(qs[k][0] for k in keys); t = sum(qs[k][1] for k in keys)
                msd = math.sqrt(sum(qs[k][2] ** 2 for k in keys)); tsd = math.sqrt(sum(qs[k][3] ** 2 for k in keys))
                return {"margin_mean": m, "total_mean": t, "p_home_win": 1 - phi(-m / msd) if msd else None,
                        "margin_q": {"p10": m - 1.2816 * msd, "p90": m + 1.2816 * msd},
                        "total_q": {"p10": t - 1.2816 * tsd, "p90": t + 1.2816 * tsd}}
            if set(qs) >= {"q1", "q2", "q3", "q4"}:
                s = _blk(["q1", "q2", "q3", "q4"])
                s["margin_mean"] = d["home_team_total_pts_mean"] - d["away_team_total_pts_mean"]
                s["total_mean"] = d["home_team_total_pts_mean"] + d["away_team_total_pts_mean"]
                d["periods"] = {k: _blk([k]) for k in ("q1", "q2", "q3", "q4")}
                d["periods"]["h1"], d["periods"]["h2"] = _blk(["q1", "q2"]), _blk(["q3", "q4"])
                d.setdefault("market", {"market_home_spread": d.get("market_home_spread"), "market_total": d.get("market_total")})
                cnt["old_layout_quarter_normals"] += 1
        dist = s.get("dist") if isinstance(s.get("dist"), dict) else {}
        segs = dist.get("segments") if isinstance(dist.get("segments"), dict) else {}
        blocks = {"full": s}
        for name, blk in (d.get("periods") or {}).items():
            if str(name).lower() in ("q1", "q2", "q3", "q4", "h1", "h2") and isinstance(blk, dict):
                blocks[str(name).lower()] = blk
        seg_out: Dict[str, Dict] = {}
        for key, blk in blocks.items():
            m, t = _num(blk.get("margin_mean")), _num(blk.get("total_mean"))
            if m is None or t is None:
                continue
            e = {"margin": m, "total": t, "p_home_win": _num(blk.get("p_home_win"))}
            h = segs.get(key) if use_dist else None
            if isinstance(h, dict) and h.get("margin") and h.get("total"):
                mh = hist_over({float(k): float(v) for k, v in h["margin"].items()})
                e["cover"] = (lambda f: (lambda line: f(-line)))(mh)
                e["over"] = hist_over({float(k): float(v) for k, v in h["total"].items()})
                e["how"] = "sim histogram (board method)"
                cnt[f"seg_hist:{key}"] += 1
            else:
                mq, tq = blk.get("margin_q") or {}, blk.get("total_q") or {}
                msd = (mq.get("p90", 0) - mq.get("p10", 0)) / 2.563 if mq else 0
                tsd = (tq.get("p90", 0) - tq.get("p10", 0)) / 2.563 if tq else 0
                if msd > 0:
                    e["cover"] = (lambda f: (lambda line: f(-line)))(normal_over(m, msd))
                if tsd > 0:
                    e["over"] = normal_over(t, tsd)
                e["how"] = "normal(sim p10/p90)"
                cnt[f"seg_normal:{key}"] += 1
            if key == "full":
                e["p_cover_at"] = (_num((d.get("market") or {}).get("market_home_spread")), _num(s.get("p_home_cover")))
                e["p_over_at"] = (_num((d.get("market") or {}).get("market_total")), _num(s.get("p_total_over")))
                anchor = d.get("market_anchor") or {}
                if anchor.get("model_margin_raw") is not None:
                    e["raw_margin"] = _num(anchor.get("model_margin_raw"))
                    e["raw_total"] = _num(anchor.get("model_total_raw"))
            seg_out[key] = e
        gout[gid] = seg_out
        stat = {"PTS": "pts", "REB": "reb", "AST": "ast", "FG3M": "threes"}
        for side in ("home", "away"):
            for pl in ((d.get("players") or {}).get(side) or []):
                pk = norm_name(pl.get("player_name"))
                lad = pl.get("prop_ladders") if isinstance(pl.get("prop_ladders"), dict) else {}
                for mk, (expr, _col) in PROP_MARKETS.items():
                    lk = LADDER_STAT[mk]
                    mus = [_num(pl.get(f"{stat[x]}_mean")) for x in expr]
                    if any(v is None for v in mus):
                        continue
                    mu = sum(mus)
                    sds = [_num(pl.get(f"{stat[x]}_sd")) for x in expr]
                    sd = math.sqrt(sum(v ** 2 for v in sds)) if all(v is not None for v in sds) else None
                    if lk == "pra" and _num(pl.get("pra_sd")) is not None:
                        sd = _num(pl.get("pra_sd"))
                    mins = _num(pl.get("min_mean")) if pl.get("min_mean") is not None else _num(pl.get("minutes"))
                    if isinstance(lad.get(lk), dict) and lad[lk].get("ladder"):
                        pout[gid][pk][mk] = {"mean": _num(lad[lk].get("mean")) or mu, "over": ladder_over(lad[lk]["ladder"]),
                                             "how": "sim ladder (board method)", "sd": sd, "min": mins}
                        continue
                    pout[gid][pk][mk] = {"mean": mu, "over": normal_over(mu, sd) if sd else None,
                                         "how": "normal(sim mean, sim sd)", "sd": sd, "min": mins}
        cnt["games"] += 1
    return gout, pout, cnt


def load_game_cards(paths: Iterable[Path], games: Dict[str, Dict]) -> Tuple[Dict, Counter]:
    """Served `game_cards_<D>.csv`: the sim's own margin/total and its probabilities AT ITS OWN market line."""
    idx = _pair_index(games)
    out, cnt = {}, Counter()
    for p in paths:
        with p.open(encoding="utf-8", errors="replace") as fh:
            for r in csv.DictReader(fh):
                gid = match_game(idx, str(r.get("date") or _date_of(p.name))[:10], str(r.get("home_tri")).upper(),
                                 str(r.get("away_tri")).upper())
                if not gid:
                    cnt["no_final_match"] += 1
                    continue
                m, t = _num(r.get("pred_margin")), _num(r.get("pred_total"))
                if m is None or t is None:
                    cnt["no_projection"] += 1
                    continue
                out[gid] = {"full": {"margin": m, "total": t, "p_home_win": _num(r.get("p_home_win")),
                                     "p_cover_at": (_num(r.get("market_home_spread")), _num(r.get("p_home_cover"))),
                                     "p_over_at": (_num(r.get("market_total")), _num(r.get("p_total_over"))),
                                     "how": "served game_cards"}}
                cnt["games"] += 1
    return out, cnt


def load_predictions_csv(paths: Iterable[Path], games: Dict[str, Dict], name_to_tri) -> Tuple[Dict, Counter]:
    """`predictions_<D>.csv` (the raw ridge game model, before SmartSim / the market anchor)."""
    idx = _pair_index(games)
    out, cnt = {}, Counter()
    for p in paths:
        d = _date_of(p.name)
        with p.open(encoding="utf-8", errors="replace") as fh:
            for r in csv.DictReader(fh):
                h, a = name_to_tri.get(r.get("home_team")), name_to_tri.get(r.get("visitor_team"))
                gid = match_game(idx, d, h or "", a or "") if h and a else None
                if not gid:
                    cnt["no_final_match"] += 1
                    continue
                seg = {"full": {"margin": _num(r.get("spread_margin")), "total": _num(r.get("totals")),
                                "p_home_win": _num(r.get("home_win_prob")), "how": "ridge"}}
                for s, pre in (("h1", "halves_h1"), ("h2", "halves_h2"), ("q1", "quarters_q1"), ("q2", "quarters_q2"),
                               ("q3", "quarters_q3"), ("q4", "quarters_q4")):
                    m, t = _num(r.get(f"{pre}_margin")), _num(r.get(f"{pre}_total"))
                    if m is not None and t is not None:
                        seg[s] = {"margin": m, "total": t, "p_home_win": _num(r.get(f"{pre}_win")), "how": "ridge"}
                if seg["full"]["margin"] is None:
                    cnt["no_projection"] += 1
                    continue
                out[gid] = seg
                cnt["games"] += 1
    return out, cnt


def load_props_predictions(paths: Iterable[Path], games: Dict[str, Dict], box: Dict) -> Tuple[Dict, Counter]:
    """`props_predictions_<D>.csv`: the props ridge `pred_*` (and, when SmartSim ran, its `mean_*`/`sd_*`)."""
    by_date_player: Dict[Tuple[str, str], str] = {}
    for gid, g in games.items():
        for pk in box.get(gid, {}):
            by_date_player[(g["date"], pk)] = gid
    ridge: Dict[str, Dict] = defaultdict(lambda: defaultdict(dict))
    cnt = Counter()
    for p in paths:
        d = _date_of(p.name)
        with p.open(encoding="utf-8", errors="replace") as fh:
            for r in csv.DictReader(fh):
                pk = norm_name(r.get("player_name"))
                gid = by_date_player.get((d, pk))
                if not gid:
                    cnt["player_not_in_a_played_box"] += 1
                    continue
                for mk, (expr, col) in PROP_MARKETS.items():
                    stat = {"PTS": "pts", "REB": "reb", "AST": "ast", "FG3M": "threes"}
                    if col and _num(r.get(col)) is not None:
                        mu = _num(r.get(col))
                    else:
                        parts = [_num(r.get(f"pred_{stat[e]}")) for e in expr]
                        if any(x is None for x in parts):
                            continue
                        mu = sum(parts)
                    ridge[gid][pk][mk] = {"mean": mu, "over": None, "how": "props ridge mean"}
                cnt["rows"] += 1
    return ridge, cnt


# ---------------------------------------------------------------------------
# 6. scoring
# ---------------------------------------------------------------------------

PHASES = ("regular", "regular_before_0819", "regular_0819_0930", "regular_since_0901", "playoff")


def in_phase(g: Dict, phase: str) -> bool:
    """`regular_since_0901` is the slice the 2026-08-31 assessment could not see (09-17..09-24 after the break).
    `regular_before_0819` / `regular_0819_0930` split on 2026-08-19, when production's props features went slim
    (`#477`: 64 of 140 zero-filled until `0417e1c9` on 2026-10-01) -- the served arm only; the re-run uses the fixed
    feature path on every date."""
    if phase == "regular_since_0901":
        return g["phase"] == "regular" and g["date"] >= "2026-09-01"
    if phase == "regular_before_0819":
        return g["phase"] == "regular" and g["date"] < "2026-08-19"
    if phase == "regular_0819_0930":
        return g["phase"] == "regular" and "2026-08-19" <= g["date"] <= "2026-09-30"
    return g["phase"] == phase


def _gate(dmae: Dict, dbrier: Optional[Dict], n: int, min_n: int) -> str:
    if n < min_n:
        return "insufficient"
    beats_base = ci_below_zero(dmae) if dmae else False
    if dbrier is None or dbrier.get("point") is None:
        return "beats baseline; book UNMEASURED" if beats_base else "no skill vs baseline"
    beats_book = ci_below_zero(dbrier)
    if beats_base and beats_book:
        return "beats baseline AND book"
    if beats_book:
        return "beats book, not baseline"
    if beats_base:
        return "beats baseline, not book" + (" (worse than book)" if ci_above_zero(dbrier) else "")
    return "no skill" + (" (worse than baseline)" if ci_above_zero(dmae) else "") + \
        ("; worse than book" if ci_above_zero(dbrier) else "")


def score_games(name: str, preds: Dict[str, Dict], games: Dict[str, Dict], hist: History, book: Dict[str, Dict],
                phase: str, min_n: int) -> Dict:
    """Point accuracy (margin, total) per segment vs the naive team baseline, and probability vs the de-vigged
    book for ML / spread / total per segment. Pushes excluded."""
    res: Dict = {"source": name, "phase": phase, "point": {}, "prob": {}}
    gids = [g for g in preds if g in games and in_phase(games[g], phase)]
    res["games"] = len(gids)
    res["dates"] = len({games[g]["date"] for g in gids})
    for seg in SEGMENTS:
        for kind in ("margin", "total"):
            rows = []
            for gid in gids:
                e = preds[gid].get(seg)
                g = games[gid]
                if not e or e.get(kind) is None or seg not in g["seg"]:
                    continue
                naive = hist.team_naive(g)
                if not naive or seg not in naive:
                    continue
                act = g["seg"][seg][0 if kind == "margin" else 1]
                rows.append((gid, e[kind], naive[seg][kind], naive[seg]["const_" + kind], act,
                             (e.get("raw_" + kind) if seg == "full" else None)))
            if not rows:
                continue
            pm = point_metrics([r[1] for r in rows], [r[4] for r in rows])
            bm = point_metrics([r[2] for r in rows], [r[4] for r in rows])
            cm = point_metrics([r[3] for r in rows], [r[4] for r in rows])
            dm = boot_ci([(r[0], abs(r[1] - r[4]) - abs(r[2] - r[4])) for r in rows])
            ent = {"n": len(rows), "mean_actual": round(statistics.fmean(r[4] for r in rows), 3), "model": pm,
                   "base_team": bm, "base_const": cm, "mae_delta_vs_team": dm}
            bk = [(r[0], book[r[0]]["game"].get(("spreads" if kind == "margin" else "totals", seg)), r[4]) for r in rows
                  if r[0] in book]
            bk = [(gid, b, a) for gid, b, a in bk if b and b.get("line") is not None]
            if bk:
                mline = [(-b["line"] if kind == "margin" else b["line"]) for _, b, _ in bk]
                ent["book_line"] = point_metrics(mline, [a for _, _, a in bk])
                ent["book_line"]["n_games"] = len(bk)
                sub = {gid for gid, _, _ in bk}
                ent["model_on_book_rows"] = point_metrics([r[1] for r in rows if r[0] in sub], [r[4] for r in rows if r[0] in sub])
                ent["mae_delta_vs_book_line"] = boot_ci([(gid, abs(next(r[1] for r in rows if r[0] == gid) - a) -
                                                          abs(ml - a)) for (gid, b, a), ml in zip(bk, mline)])
            raw = [r for r in rows if r[5] is not None]
            if raw:
                ent["raw_model_before_anchor"] = point_metrics([r[5] for r in raw], [r[4] for r in raw])
            ent["verdict_point"] = ("beats team baseline" if ci_below_zero(dm) else
                                    ("worse than team baseline" if ci_above_zero(dm) else "no difference")) \
                if len(rows) >= min_n else "insufficient"
            res["point"][f"{seg}:{kind}"] = ent
        # probabilities vs the de-vigged book
        for mkt in ("h2h", "spreads", "totals"):
            rows = []
            skipped = Counter()
            for gid in gids:
                e = preds[gid].get(seg)
                g = games[gid]
                b = (book.get(gid) or {}).get("game", {}).get((mkt, seg))
                if not e or not b or seg not in g["seg"]:
                    skipped["no_model_or_book"] += 1
                    continue
                m_act, t_act = g["seg"][seg]
                if mkt == "h2h":
                    if m_act == 0:
                        skipped["tie"] += 1
                        continue
                    p = e.get("p_home_win")
                    if p is None and e.get("margin") is not None and e.get("cover"):
                        p = e["cover"](0.0)
                    y = int(m_act > 0)
                elif mkt == "spreads":
                    line = b["line"]
                    if m_act + line == 0:
                        skipped["push"] += 1
                        continue
                    y = int(m_act + line > 0)
                    p = e["cover"](line) if e.get("cover") else None
                    if p is None and e.get("p_cover_at") and e["p_cover_at"][0] == line:
                        p = e["p_cover_at"][1]
                else:
                    line = b["line"]
                    if t_act == line:
                        skipped["push"] += 1
                        continue
                    y = int(t_act > line)
                    p = e["over"](line) if e.get("over") else None
                    if p is None and e.get("p_over_at") and e["p_over_at"][0] == line:
                        p = e["p_over_at"][1]
                if p is None:
                    skipped["model_has_no_probability_at_book_line"] += 1
                    continue
                rows.append((gid, clip(float(p)), clip(b["p"]), y))
            if not rows:
                if skipped:
                    res["prob"][f"{seg}:{mkt}"] = {"n": 0, "skipped": dict(skipped)}
                continue
            pmod = prob_metrics([r[1] for r in rows], [r[3] for r in rows])
            pbk = prob_metrics([r[2] for r in rows], [r[3] for r in rows])
            pmod["auc"] = auc([r[1] for r in rows], [r[3] for r in rows])
            pbk["auc"] = auc([r[2] for r in rows], [r[3] for r in rows])
            if mkt == "h2h":
                # the 08-31 assessment's comparator: climatology = the as-of home win rate in this segment
                clim = []
                for gid, _p, _b, y in rows:
                    prior = [x for x in hist.order if x["tip"] < games[gid]["tip"] and seg in x["seg"] and x["seg"][seg][0] != 0]
                    clim.append(statistics.fmean(1.0 if x["seg"][seg][0] > 0 else 0.0 for x in prior) if prior else 0.5)
                bc = sum((c - r[3]) ** 2 for c, r in zip(clim, rows)) / len(rows)
                pmod["brier_skill_vs_climatology"] = round(1 - pmod["brier"] / bc, 4) if bc else None
                pbk["brier_skill_vs_climatology"] = round(1 - pbk["brier"] / bc, 4) if bc else None
                pmod["favourite_accuracy"] = round(statistics.fmean(1.0 if (r[1] > 0.5) == bool(r[3]) else 0.0 for r in rows), 4)
                pbk["favourite_accuracy"] = round(statistics.fmean(1.0 if (r[2] > 0.5) == bool(r[3]) else 0.0 for r in rows), 4)
            db = boot_ci([(r[0], (r[1] - r[3]) ** 2 - (r[2] - r[3]) ** 2) for r in rows])
            dl = boot_ci([(r[0], logloss(r[1], r[3]) - logloss(r[2], r[3])) for r in rows])
            pm_key = f"{seg}:{'margin' if mkt != 'totals' else 'total'}"
            dmae = res["point"].get(pm_key, {}).get("mae_delta_vs_team")
            res["prob"][f"{seg}:{mkt}"] = {
                "n": len(rows), "base_rate": round(statistics.fmean(r[3] for r in rows), 4), "p_model": pmod, "p_book": pbk,
                "brier_delta_model_vs_book": db, "logloss_delta_model_vs_book": dl, "skipped": dict(skipped),
                "how": Counter(preds[r[0]][seg].get("how") for r in rows).most_common(1)[0][0],
                "reliability_model": reliability([r[1] for r in rows], [r[3] for r in rows], 5),
                "verdict": _gate(dmae, db, len(rows), min_n) if mkt != "h2h" else
                ("insufficient" if len(rows) < min_n else ("beats book" if ci_below_zero(db) else
                                                            ("worse than book" if ci_above_zero(db) else "no difference vs book")))}
    return res


def score_props(name: str, preds: Dict[str, Dict], games: Dict[str, Dict], box: Dict, hist: History,
                book: Dict[str, Dict], phase: str, min_n: int) -> Dict:
    res: Dict = {"source": name, "phase": phase, "point": {}, "book": {}}
    gids = [g for g in preds if g in games and in_phase(games[g], phase)]
    res["games"] = len(gids)
    drops = Counter()
    for mk, (expr, _col) in PROP_MARKETS.items():
        rows = []
        for gid in gids:
            g = games[gid]
            for pk, mkts in preds[gid].items():
                e = mkts.get(mk)
                if not e or e.get("mean") is None:
                    continue
                act_row = box.get(gid, {}).get(pk)
                if not act_row:
                    drops["projected_but_did_not_play"] += 1
                    continue
                base, n_prior = hist.player_avg(pk, g["tip"])
                if not base or n_prior < 3:
                    drops["no_asof_baseline(<3 games)"] += 1
                    continue
                l10, _ = hist.player_avg(pk, g["tip"], last=10)
                y = sum(act_row[s] for s in expr)
                rows.append((gid, pk, e, sum(base[s] for s in expr), sum(l10[s] for s in expr), y))
        if not rows:
            continue
        m = point_metrics([r[2]["mean"] for r in rows], [r[5] for r in rows])
        a = point_metrics([r[3] for r in rows], [r[5] for r in rows])
        b = point_metrics([r[4] for r in rows], [r[5] for r in rows])
        d = boot_ci([(r[0], abs(r[2]["mean"] - r[5]) - abs(r[3] - r[5])) for r in rows])
        res["point"][mk] = {"n": len(rows), "games": len({r[0] for r in rows}),
                            "mean_actual": round(statistics.fmean(r[5] for r in rows), 3), "model": m, "base_a": a,
                            "base_b": b, "mae_delta_vs_a": d,
                            "verdict": ("insufficient" if len(rows) < min_n else
                                        "beats own average" if ci_below_zero(d) else
                                        "WORSE than own average" if ci_above_zero(d) else "no difference")}
        # vs book, same rows
        brows = []
        fc = Counter()
        for gid, pk, e, base, l10, y in rows:
            b_ = (book.get(gid) or {}).get("props", {}).get((pk, mk))
            if not b_:
                fc["no_two_sided_book_line"] += 1
                continue
            line = b_["line"]
            if y == line:
                fc["push"] += 1
                continue
            if not e.get("over"):
                fc["model_has_no_distribution"] += 1
                continue
            sd = hist.player_sd(pk, games[gid]["tip"], expr)
            pbase = normal_over(base, sd)(line) if sd else None
            brows.append((gid, clip(e["over"](line)), clip(b_["p"]), int(y > line), clip(pbase) if pbase is not None else None,
                          e["mean"], line, base))
        ent = {"filter_counts": dict(fc), "n": len(brows)}
        if brows:
            ys = [r[3] for r in brows]
            ent.update({"games": len({r[0] for r in brows}), "base_rate_over": round(statistics.fmean(ys), 4),
                        "p_book": prob_metrics([r[2] for r in brows], ys), "p_model": prob_metrics([r[1] for r in brows], ys),
                        "brier_delta_model_vs_book": boot_ci([(r[0], (r[1] - r[3]) ** 2 - (r[2] - r[3]) ** 2) for r in brows]),
                        "logloss_delta_model_vs_book": boot_ci([(r[0], logloss(r[1], r[3]) - logloss(r[2], r[3])) for r in brows]),
                        "reliability_model": reliability([r[1] for r in brows], ys, 5),
                        "mean_minus_line": {"model": round(statistics.fmean(r[5] - r[6] for r in brows), 3),
                                            "own_avg": round(statistics.fmean(r[7] - r[6] for r in brows), 3)}})
            based = [r for r in brows if r[4] is not None]
            if based:
                ent["p_own_avg_normal"] = prob_metrics([r[4] for r in based], [r[3] for r in based])
            # flat-stake ROI at -110 of the model's side where model and book disagree by >= 5pp (a proxy; the
            # de-vigged median is not a purchasable price)
            bets = [(r[0], (r[1] > r[2]) == bool(r[3])) for r in brows if abs(r[1] - r[2]) >= 0.05]
            if bets:
                pnl = [(gid, (100 / 110) if win else -1.0) for gid, win in bets]
                ent["disagree_5pp_bets"] = {"n": len(bets), "hit": round(statistics.fmean(1.0 if w else 0.0 for _, w in bets), 4),
                                            "roi_at_-110": boot_ci(pnl)}
        ent["verdict"] = _gate(d, ent.get("brier_delta_model_vs_book"), ent["n"], min_n)
        res["book"][mk] = ent
    res["drops"] = dict(drops)
    return res


# ---------------------------------------------------------------------------
# 6b. diagnosis: WHY a market misses (the backtest is the diagnosis -- user decision 2026-10-02)
# ---------------------------------------------------------------------------

def _ols_slope(x: List[float], y: List[float]) -> Optional[float]:
    if len(x) < 10:
        return None
    mx, my = statistics.fmean(x), statistics.fmean(y)
    vx = sum((a - mx) ** 2 for a in x)
    return round(sum((a - mx) * (b - my) for a, b in zip(x, y)) / vx, 4) if vx else None


def diagnose_props(preds: Dict[str, Dict], games: Dict[str, Dict], box: Dict, hist: History, phase: str) -> Dict:
    """Per market: where the error comes from.

    * minutes vs rate: actual = MIN_act * rate_act; model = MIN_model * rate_model. The error is apportioned by
      substituting the ACTUAL minutes into the model's own per-minute rate (an oracle used only to apportion, never
      as a predictor), and the same for the player's own as-of per-minute rate.
    * signal in the deviation: slope of (actual - own avg) on (model - own avg). 1 = the model's departures from the
      player's average are fully real; 0 = pure noise.
    * dispersion: share of actuals inside the model's own central 80% (mean +/- 1.2816 sd), nominal 0.80;
      sd_ratio = residual sd / mean model sd (> 1 = the model is too confident).
    * bias by actual-minutes band, beside the own average's bias in the same band."""
    out: Dict = {}
    for mk, (expr, _c) in PROP_MARKETS.items():
        rows = []
        for gid, pl in preds.items():
            if gid not in games or not in_phase(games[gid], phase):
                continue
            for pk, mkts in pl.items():
                e = mkts.get(mk)
                a = box.get(gid, {}).get(pk)
                if not e or e.get("mean") is None or not a:
                    continue
                base, n = hist.player_avg(pk, games[gid]["tip"])
                if not base or n < 3:
                    continue
                y = sum(a[x] for x in expr)
                rows.append({"gid": gid, "y": y, "m": e["mean"], "b": sum(base[x] for x in expr), "bmin": base["MIN"],
                             "sd": e.get("sd"), "min": e.get("min"), "amin": a["MIN"]})
        if len(rows) < 30:
            continue
        d: Dict = {"n": len(rows)}
        d["deviation_signal_slope"] = _ols_slope([r["m"] - r["b"] for r in rows], [r["y"] - r["b"] for r in rows])
        mrows = [r for r in rows if r["min"] and r["min"] > 0]
        if len(mrows) >= 30:
            d["minutes"] = {"n": len(mrows), "model_bias": round(statistics.fmean(r["min"] - r["amin"] for r in mrows), 3),
                            "model_mae": round(statistics.fmean(abs(r["min"] - r["amin"]) for r in mrows), 3),
                            "own_avg_bias": round(statistics.fmean(r["bmin"] - r["amin"] for r in mrows), 3),
                            "own_avg_mae": round(statistics.fmean(abs(r["bmin"] - r["amin"]) for r in mrows), 3)}
            oracle = [r["m"] / r["min"] * r["amin"] for r in mrows]
            d["error_split"] = {
                "mae_model": round(statistics.fmean(abs(r["m"] - r["y"]) for r in mrows), 3),
                "mae_own_avg": round(statistics.fmean(abs(r["b"] - r["y"]) for r in mrows), 3),
                "mae_model_rate_x_actual_minutes": round(statistics.fmean(abs(o - r["y"]) for o, r in zip(oracle, mrows)), 3),
                "mae_own_rate_x_actual_minutes": round(statistics.fmean(
                    abs((r["b"] / r["bmin"] if r["bmin"] else 0) * r["amin"] - r["y"]) for r in mrows), 3),
                "bias_model_rate_x_actual_minutes": round(statistics.fmean(o - r["y"] for o, r in zip(oracle, mrows)), 3)}
        srows = [r for r in rows if r["sd"] and r["sd"] > 0]
        if len(srows) >= 30:
            inside = statistics.fmean(1.0 if abs(r["y"] - r["m"]) <= 1.2816 * r["sd"] else 0.0 for r in srows)
            resid_sd = statistics.pstdev([r["y"] - r["m"] for r in srows])
            msd = statistics.fmean(r["sd"] for r in srows)
            d["dispersion"] = {"n": len(srows), "coverage_80": round(inside, 4), "mean_model_sd": round(msd, 3),
                               "residual_sd": round(resid_sd, 3), "sd_ratio": round(resid_sd / msd, 3)}
        bands = {}
        for lo, hi in ((0, 15), (15, 25), (25, 99)):
            b = [r for r in rows if lo <= r["amin"] < hi]
            if len(b) >= 20:
                bands[f"{lo}-{hi}min"] = {"n": len(b), "bias": round(statistics.fmean(r["m"] - r["y"] for r in b), 3),
                                          "own_avg_bias": round(statistics.fmean(r["b"] - r["y"] for r in b), 3)}
        d["bias_by_actual_minutes"] = bands
        out[mk] = d
    return out


def diagnose_games(preds: Dict[str, Dict], games: Dict[str, Dict], book: Dict, phase: str) -> Dict:
    """Full game: how much of the projection is the market (anchor), the RAW model's own error and bias, whether the
    model's departure from the book line carries signal, the expansion clubs (TOR, POR: no history before 2026),
    and the total's level by month."""
    rows = []
    for gid, seg in preds.items():
        g = games.get(gid)
        e = (seg or {}).get("full")
        b = (book.get(gid) or {}).get("game", {})
        if not g or not in_phase(g, phase) or not e or e.get("margin") is None or e.get("total") is None:
            continue
        sp, to = b.get(("spreads", "full")), b.get(("totals", "full"))
        rows.append({"gid": gid, "home": g["home"], "away": g["away"], "am": g["seg"]["full"][0], "at": g["seg"]["full"][1],
                     "m": e["margin"], "t": e["total"], "rm": e.get("raw_margin"), "rt": e.get("raw_total"),
                     "bm": -sp["line"] if sp else None, "bt": to["line"] if to else None})
    if len(rows) < 20:
        return {}
    out: Dict = {"n": len(rows)}
    br = [r for r in rows if r["bm"] is not None and r["bt"] is not None]
    out["deviation_from_book_signal_slope"] = {
        "margin": _ols_slope([r["m"] - r["bm"] for r in br], [r["am"] - r["bm"] for r in br]),
        "total": _ols_slope([r["t"] - r["bt"] for r in br], [r["at"] - r["bt"] for r in br]), "n": len(br)}
    raw = [r for r in br if r["rm"] is not None and r["rt"] is not None]
    if raw:
        out["raw_model_pre_anchor"] = {
            "n": len(raw),
            "margin_mae_raw": round(statistics.fmean(abs(r["rm"] - r["am"]) for r in raw), 3),
            "margin_mae_anchored": round(statistics.fmean(abs(r["m"] - r["am"]) for r in raw), 3),
            "margin_mae_book": round(statistics.fmean(abs(r["bm"] - r["am"]) for r in raw), 3),
            "total_mae_raw": round(statistics.fmean(abs(r["rt"] - r["at"]) for r in raw), 3),
            "total_mae_anchored": round(statistics.fmean(abs(r["t"] - r["at"]) for r in raw), 3),
            "total_mae_book": round(statistics.fmean(abs(r["bt"] - r["at"]) for r in raw), 3),
            "total_bias_raw": round(statistics.fmean(r["rt"] - r["at"] for r in raw), 3),
            "raw_deviation_signal_slope_margin": _ols_slope([r["rm"] - r["bm"] for r in raw], [r["am"] - r["bm"] for r in raw]),
            "raw_deviation_signal_slope_total": _ols_slope([r["rt"] - r["bt"] for r in raw], [r["at"] - r["bt"] for r in raw])}
    exp = {}
    for label, sel in (("involves TOR/POR", lambda r: r["home"] in ("TOR", "POR") or r["away"] in ("TOR", "POR")),
                       ("other", lambda r: not (r["home"] in ("TOR", "POR") or r["away"] in ("TOR", "POR")))):
        sub = [r for r in br if sel(r)]
        if len(sub) >= 10:
            exp[label] = {"n": len(sub), "margin_mae_model": round(statistics.fmean(abs(r["m"] - r["am"]) for r in sub), 3),
                          "margin_mae_book": round(statistics.fmean(abs(r["bm"] - r["am"]) for r in sub), 3),
                          "margin_bias_model_vs_book": round(statistics.fmean(r["m"] - r["bm"] for r in sub), 3),
                          "total_mae_model": round(statistics.fmean(abs(r["t"] - r["at"]) for r in sub), 3),
                          "total_mae_book": round(statistics.fmean(abs(r["bt"] - r["at"]) for r in sub), 3)}
    out["expansion_clubs"] = exp
    months: Dict[str, List[Dict]] = defaultdict(list)
    for r in rows:
        months[games[r["gid"]]["date"][:7]].append(r)
    out["total_bias_by_month"] = {k: {"n": len(v), "model_bias": round(statistics.fmean(r["t"] - r["at"] for r in v), 3),
                                      "book_bias": round(statistics.fmean(r["bt"] - r["at"] for r in v if r["bt"] is not None), 3)
                                      if any(r["bt"] is not None for r in v) else None}
                                  for k, v in sorted(months.items())}
    return out


# ---------------------------------------------------------------------------
# 7. report
# ---------------------------------------------------------------------------

def coverage(families: Dict[str, Iterable[str]], scored_dates: Iterable[str]) -> Dict:
    """Per-family date coverage over the SCORED season dates, and the intersection a result actually rests on."""
    season = sorted(set(scored_dates))
    out = {}
    sets = {}
    for name, ds in families.items():
        s = sorted(set(ds) & set(season))
        sets[name] = set(s)
        out[name] = {"dates": len(s), "range": [s[0], s[-1]] if s else None}
    return {"season_dates": len(season), "families": out}


def _fmt_ci(d: Optional[Dict]) -> str:
    if not d or d.get("point") is None:
        return ""
    return f"{d['point']:+.4f} [{d['ci95'][0]:+.4f}, {d['ci95'][1]:+.4f}]"


def write_md(report: Dict, path: Path) -> None:
    L = ["# WNBA game-line + player-prop backtest (as-of)", "",
         f"generated {report['generated_at']}; min_n for any verdict = {report['min_n']}; bootstrap: game-clustered, "
         f"{report['n_boot']} reps", "",
         "Labels are DIAGNOSTIC (which reference the model beats, CI wholly on one side of 0). They are not a market "
         "gate: every line is its own decision (user, 2026-10-02); a losing market is a model to fix.", ""]
    L += ["## substrates and coverage", "", "```", json.dumps(report["substrates"], indent=1), "```", "",
          "per-family coverage over scored dates (the intersection per arm is in each arm's header):", "", "```",
          json.dumps(report["coverage"], indent=1), "```", ""]
    for arm in report["arms"]:
        for phase in PHASES:
            G = arm["games"].get(phase)
            P = arm["props"].get(phase)
            if not G and not P:
                continue
            L += [f"## {arm['name']} — {phase}", "", arm["describe"], ""]
            if G:
                L += [f"game-line rows rest on {G['games']} games / {G['dates']} dates.", "",
                      "### game lines: point accuracy (model vs naive team baseline; const = as-of league mean)", "",
                      "| segment:kind | n | mean act | mean proj | bias | MAE model | MAE team | MAE const | dMAE vs team [95% CI] | MAE book line (n) | dMAE vs book line [CI] | raw model MAE (pre-anchor) | verdict |",
                      "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
                for k, v in G["point"].items():
                    bl = v.get("book_line") or {}
                    raw = v.get("raw_model_before_anchor") or {}
                    raw_s = f"{raw.get('mae', '')} (n {raw.get('n', '')})" if raw else ""
                    L.append(f"| {k} | {v['n']} | {v['mean_actual']} | {v['model']['mean_pred']} | {v['model']['bias']} | "
                             f"{v['model']['mae']} | {v['base_team']['mae']} | {v['base_const']['mae']} | "
                             f"{_fmt_ci(v['mae_delta_vs_team'])} | {bl.get('mae', '')} ({bl.get('n_games', '')}) | "
                             f"{_fmt_ci(v.get('mae_delta_vs_book_line'))} | {raw_s} | {v['verdict_point']} |")
                L += ["", "### game lines: probability vs the de-vigged book (same rows; pushes excluded)", "",
                      "| segment:market | n | base rate | Brier book | Brier model | dBrier model-book [CI] | LL book | LL model | dLL [CI] | prob method | verdict |",
                      "|---|---|---|---|---|---|---|---|---|---|---|"]
                for k, v in G["prob"].items():
                    if not v.get("n"):
                        L.append(f"| {k} | 0 | | | | | | | | | unmeasured: {v.get('skipped')} |")
                        continue
                    L.append(f"| {k} | {v['n']} | {v['base_rate']} | {v['p_book']['brier']} | {v['p_model']['brier']} | "
                             f"{_fmt_ci(v['brier_delta_model_vs_book'])} | {v['p_book']['logloss']} | {v['p_model']['logloss']} | "
                             f"{_fmt_ci(v['logloss_delta_model_vs_book'])} | {v['how']} | {v['verdict']} |"
                             + (f" AUC model {v['p_model'].get('auc')} / book {v['p_book'].get('auc')}; Brier skill vs climatology "
                                f"model {v['p_model'].get('brier_skill_vs_climatology')} / book {v['p_book'].get('brier_skill_vs_climatology')}; "
                                f"fav acc {v['p_model'].get('favourite_accuracy')} / {v['p_book'].get('favourite_accuracy')}"
                                if k.endswith(':h2h') else ""))
                L.append("")
            if P:
                L += [f"### player props: point accuracy (a = own as-of season avg, b = last-10) — {P['games']} games", "",
                      f"drops: `{json.dumps(P['drops'])}`", "",
                      "| market | n | games | mean act | mean proj | bias | MAE model | MAE a | MAE b | dMAE vs a [95% CI] | RMSE model | RMSE a | verdict |",
                      "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
                for k, v in P["point"].items():
                    m, a, b = v["model"], v["base_a"], v["base_b"]
                    L.append(f"| {k} | {v['n']} | {v['games']} | {v['mean_actual']} | {m['mean_pred']} | {m['bias']} | {m['mae']} | "
                             f"{a['mae']} | {b['mae']} | {_fmt_ci(v['mae_delta_vs_a'])} | {m['rmse']} | {a['rmse']} | {v['verdict']} |")
                L += ["", "### player props vs the de-vigged book (book's modal line; pushes excluded)", "",
                      "| market | n | games | over rate | Brier book | Brier model | Brier own-avg normal | dBrier model-book [CI] | LL book | LL model | mean-line model / own avg | disagree>=5pp bets n, hit, ROI@-110 [CI] | verdict |",
                      "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
                for k, v in P["book"].items():
                    if not v.get("n"):
                        L.append(f"| {k} | 0 | | | | | | | | | | | {v['verdict']} — filters {v['filter_counts']} |")
                        continue
                    e = v.get("disagree_5pp_bets") or {}
                    ml = v.get("mean_minus_line") or {}
                    L.append(f"| {k} | {v['n']} | {v['games']} | {v['base_rate_over']} | {v['p_book']['brier']} | {v['p_model']['brier']} | "
                             f"{(v.get('p_own_avg_normal') or {}).get('brier', '')} | {_fmt_ci(v['brier_delta_model_vs_book'])} | "
                             f"{v['p_book']['logloss']} | {v['p_model']['logloss']} | {ml.get('model')} / {ml.get('own_avg')} | "
                             f"{e.get('n', '')}, {e.get('hit', '')}, {_fmt_ci(e.get('roi_at_-110'))} | {v['verdict']} |")
                L.append("")
    L += ["## diagnosis (why each market misses; per arm and phase)", ""]
    for arm in report["arms"]:
        for phase in PHASES:
            gd = (arm["games"].get(phase) or {}).get("diagnosis")
            pdg = (arm["props"].get(phase) or {}).get("diagnosis")
            if gd:
                L += [f"### {arm['name']} -- {phase} -- game lines", "", "```", json.dumps(gd, indent=1), "```", ""]
            if pdg:
                L += [f"### {arm['name']} -- {phase} -- props", "", "```", json.dumps(pdg, indent=1), "```", ""]
    L += ["## comparison summary (per market, per arm and phase; diagnostic, not a gate)", "", "| arm | phase | market | label |", "|---|---|---|---|"]
    for row in report["comparison_summary"]:
        L.append(f"| {row['arm']} | {row['phase']} | {row['market']} | {row['verdict']} |")
    path.write_text("\n".join(L) + "\n", encoding="utf-8")


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--espn-dir", required=True)
    ap.add_argument("--box-dir", required=True)
    ap.add_argument("--odds-dir", required=True)
    ap.add_argument("--asof-archive", help="phase-1/2 re-run outputs (<archive>/<date>/...)")
    ap.add_argument("--served", action="append", default=[], help="label=dir of production artifacts (repeatable)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--min-n", type=int, default=30, help="no comparison label below this many rows")
    ap.add_argument("--n-boot", type=int, default=2000)
    args = ap.parse_args(argv)
    global boot_ci
    _boot = boot_ci
    boot_ci = lambda rows, n_boot=args.n_boot, seed=7: _boot(rows, n_boot, seed)  # noqa: E731
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    games = load_games(Path(args.espn_dir))
    box, box_stats = load_box(Path(args.box_dir), games)
    hist = History(games, box)
    book, book_stats = load_book(Path(args.odds_dir), games)
    name_to_tri = {}
    for g in games.values():
        name_to_tri[g["home_name"]] = g["home"]
        name_to_tri[g["away_name"]] = g["away"]
    arms = []

    def add_arm(name, describe, gpreds, ppreds, stats):
        arm = {"name": name, "describe": describe, "stats": stats, "games": {}, "props": {}}
        for phase in PHASES:
            if gpreds:
                r = score_games(name, gpreds, games, hist, book, phase, args.min_n)
                if r["games"]:
                    arm["games"][phase] = r
            if ppreds:
                r = score_props(name, ppreds, games, box, hist, book, phase, args.min_n)
                if r["games"]:
                    r["diagnosis"] = diagnose_props(ppreds, games, box, hist, phase)
                    arm["props"][phase] = r
            if gpreds and arm["games"].get(phase):
                arm["games"][phase]["diagnosis"] = diagnose_games(gpreds, games, book, phase)
        arms.append(arm)
        print(f"arm {name}: {json.dumps({p: v['games'] for p, v in arm['games'].items()})} game rows, "
              f"{json.dumps({p: v['games'] for p, v in arm['props'].items()})} prop games; {json.dumps(stats)}", flush=True)

    fam: Dict[str, List[str]] = {"espn_finals": [g["date"] for g in games.values()],
                                 "box_scores": [games[gid]["date"] for gid in box],
                                 "book_snapshot(oddsapi historical)": [games[gid]["date"] for gid in book]}
    if args.asof_archive:
        A = Path(args.asof_archive)
        sims = sorted(A.glob("*/smart_sim_*.json"))
        g1, p1, c1 = load_sim_json_games(sims, games)
        add_arm("asof_sim", "AS-OF RE-RUN, today's code (fleet `9a7f0d2f`): SmartSim at production settings (market anchor ON: "
                "margin 0.95 market / 0.05 model, total 0.7 / 0.3), 500 sims. Probabilities by the BOARD's own methods "
                "(segment histograms; player hitProb ladders). This is what the board would serve.", g1, p1, dict(c1))
        g2, c2 = load_predictions_csv(sorted(A.glob("*/predictions_*.csv")), games, name_to_tri)
        add_arm("asof_ridge_game", "AS-OF RE-RUN: the raw ridge game model (`predictions_<D>.csv`), BEFORE SmartSim and the market "
                "anchor. Point accuracy + its own win probability; no cover/over probability is produced by this stage.",
                g2, None, dict(c2))
        p3, c3 = load_props_predictions(sorted(A.glob("*/props_predictions_*.csv")), games, box)
        add_arm("asof_ridge_props", "AS-OF RE-RUN: the props ridge `pred_*` means (before SmartSim overwrites mean/sd). Point "
                "accuracy only.", None, p3, dict(c3))
        fam["asof_predictions"] = [p.parent.name for p in A.glob("*/predictions_*.csv")]
        fam["asof_smart_sim"] = [p.parent.name for p in sims]
    for spec in args.served:
        label, d = spec.split("=", 1)
        D = Path(d)
        sims = sorted(D.glob("**/smart_sim_2026-*.json"))
        g4, p4, c4 = load_sim_json_games(sims, games)
        cards, c5 = load_game_cards(sorted(D.glob("**/game_cards_2026-*.csv")), games)
        for gid, e in cards.items():  # the served game_cards carry the sim's probability AT ITS OWN line
            if gid in g4:
                g4[gid]["full"].setdefault("p_cover_at", e["full"]["p_cover_at"])
                g4[gid]["full"].setdefault("p_over_at", e["full"]["p_over_at"])
            else:
                g4[gid] = cards[gid]
        add_arm(label, f"SERVED: production's own artifacts as stored ({d}); Syndicate root only. Where the stored sim has no "
                "histogram/ladder (August and earlier), probability = normal from the sim's own p10/p90 or mean/sd.",
                g4, p4, {"smart_sim": dict(c4), "game_cards": dict(c5)})
        fam[f"{label}_smart_sim"] = [_date_of(p.name) for p in sims]
        fam[f"{label}_game_cards"] = [_date_of(p.name) for p in D.glob("**/game_cards_2026-*.csv")]
    gate = []
    for arm in arms:
        for phase in PHASES:
            for k, v in (arm["games"].get(phase) or {}).get("prob", {}).items():
                gate.append({"arm": arm["name"], "phase": phase, "market": k, "verdict": v.get("verdict", "unmeasured")})
            for k, v in (arm["props"].get(phase) or {}).get("book", {}).items():
                gate.append({"arm": arm["name"], "phase": phase, "market": k, "verdict": v.get("verdict")})
    report = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "min_n": args.min_n,
              "n_boot": args.n_boot,
              "substrates": {"finals": "ESPN public scoreboard (fetched 2026-10-02)",
                             "box": f"fleet disk boxscores_<date>.csv ({box_stats})",
                             "book": f"OddsAPI historical, tip-60min, fetched 2026-10-02 ({book_stats})",
                             "asof": args.asof_archive, "served": args.served},
              "coverage": coverage(fam, [g["date"] for g in games.values()]),
              "games_by_phase": dict(Counter(g["phase"] for g in games.values())),
              "arms": arms, "comparison_summary": gate}

    def _clean(o):
        if isinstance(o, dict):
            return {str(k): _clean(v) for k, v in o.items() if not callable(v)}
        if isinstance(o, (list, tuple)):
            return [_clean(v) for v in o]
        return o
    (out / "report.json").write_text(json.dumps(_clean(report), indent=1), encoding="utf-8")
    write_md(report, out / "report.md")
    print(f"wrote {out / 'report.json'} and {out / 'report.md'}", flush=True)
    return 0


if __name__ == "__main__":
    import sys as _sys
    if len(_sys.argv) > 1 and _sys.argv[1] in ("game", "sim"):
        raise SystemExit(_rebuild_main())
    raise SystemExit(main())
