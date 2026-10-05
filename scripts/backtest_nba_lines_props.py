"""Backtest: NBA game lines and player props, AS-OF, against actuals, naive baselines and the book.

Mirrors `scripts/backtest_nhl_props.py` (lane nhl-player-props-projection) in method and report
shape, so the NBA / NHL / NFL / NCAAF results read side by side.

WHAT IS SCORED, AND WHY THESE QUANTITIES (traced 2026-10-02, lane nba-lines-props-backtest):

  * The Layer-2 board has NO NBA projection source: `board_enrichment._attach_projections_by_sport`
    falls through to `{"supported": False, "reason": "no projection source wired for nba"}`.
    NBA model numbers reach a user only on the NBA cards page and its prop picks.
  * GAME LINES (`syndicate/features/nba/cards.py::_game_from_row`): model margin/total =
    smart-sim `score.margin_mean` / `score.total_mean` (fallback `game_cards.pred_margin/pred_total`,
    which `refresh_nba_oddsapi_props._smart_sim_projection_index` derives from the SAME smart-sim
    JSON). Probabilities are fixed-scale logistics of those means: win `_margin_win_prob(m, 6.5)`,
    cover `(m + home_spread, 7.5)`, over `(total - line, 10.5)`; quarter win at the default 3.4.
    This harness imports `_margin_win_prob` from cards.py, so the served transform is scored.
  * PLAYER PROPS (`basketball_props_edges._compute_props_edges_file_only_local`): model mean =
    `mean_<stat>` (smart-sim) when the column exists, else `pred_<stat>`; combos pr/pa/ra are sums;
    P(over) = Normal(mean, sd_<stat> or a fixed sigma); with no `props_prob_calibration*.json`
    (none exists on the fleet or the mirror) pts/pra are shrunk toward 0.5 and ast/reb/pr/pa/ra are
    BLENDED toward the book's own vig-inclusive implied price. This harness CALLS that function on
    the as-of inputs, so the probability scored is the one production computes.
  * A second, NOT-SERVED game arm scores upstream `predictions_<date>.csv` (the vendor games
    model), because it is the only game projection with full-season coverage. It is labelled.

WHERE THE INPUTS COME FROM, AND WHAT MAKES THEM AS-OF:
  * Historical artifacts are the files the producers COMMITTED: upstream `mostgood1/NBA-Betting`
    (`data/processed/`, the source app Syndicate mirrored all 2025-26 season) and Syndicate's own
    git mirror (`data/nba_source/data/processed/`, 2026 playoffs). Many files were re-committed
    after their games (props_edges: 39 of ~200 dates last written after game day), so for every
    (family, date) this harness takes the LAST version committed strictly before that date's FIRST
    tip-off (ESPN scoreboard). A commit made before tip cannot contain the result. Files with no
    pre-tip version are excluded and counted.
  * Actuals: stats.nba.com `playergamelogs` (2025-26 Regular Season + Playoffs; joined by NBA
    PLAYER_ID, never by name) and ESPN scoreboards (finals, linescores incl. OT, tip times).
  * Baselines: (a) the player's own 2025-26 per-game average over games STRICTLY before the date
    (regular season + any earlier playoff games), (b) his last-10 average; for game lines the
    captured consensus book line. The book is the latest pre-tip COMMITTED capture, not a verified
    close.

HONESTY RULES BUILT IN (same as NHL): the intersection is reported, never the union; `n` travels
with every statistic; no verdict below `--min-n`; the harness supplies no input production lacked;
"no skill" is a result; the production probability is reproduced and parity-checked row by row
(`model_prob_raw` vs this harness's Normal) before anything is scored.

Usage:
  py -3 scripts/backtest_nba_lines_props.py --out C:/tmp/nba_bt/out            # collect + score
  py -3 scripts/backtest_nba_lines_props.py --out C:/tmp/nba_bt/out --analyze-only
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import math
import os
import pickle
import subprocess
import sys
import tempfile
import time
import urllib.request
from collections import Counter, defaultdict
from datetime import date as _date, datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import numpy as np

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

UPSTREAM_URL = "https://github.com/mostgood1/NBA-Betting.git"
SEASON = "2025-26"
RS_START, RS_END = "2025-10-21", "2026-04-12"
PO_START, PO_END = "2026-04-13", "2026-06-30"
PROP_MARKETS = ("pts", "reb", "ast", "threes", "pra", "pr", "pa", "ra", "stl", "blk", "tov")
LOG_COL = {"pts": "PTS", "reb": "REB", "ast": "AST", "threes": "FG3M", "stl": "STL", "blk": "BLK", "tov": "TOV"}
COMBOS = {"pra": ("pts", "reb", "ast"), "pr": ("pts", "reb"), "pa": ("pts", "ast"), "ra": ("reb", "ast")}
# per (repo-kind, family): path template; {d} = YYYY-MM-DD
FAMILIES = {
    "props_predictions": "props_predictions_{d}.csv",
    "props_odds": "oddsapi_player_props_{d}.csv",
    "game_odds": "game_odds_{d}.csv",
    "period_lines": "period_lines_{d}.csv",
    "predictions": "predictions_{d}.csv",
}
SOURCES = {  # name -> (repo path resolver, ref, data prefix); syndicate first: it is what Syndicate served
    "syndicate": ("syndicate", "origin/main", "data/nba_source/data/processed/"),
    "upstream": ("upstream", "HEAD", "data/processed/"),
}
TEAM_TRI = {
    "Atlanta Hawks": "ATL", "Boston Celtics": "BOS", "Brooklyn Nets": "BKN", "Charlotte Hornets": "CHA",
    "Chicago Bulls": "CHI", "Cleveland Cavaliers": "CLE", "Dallas Mavericks": "DAL", "Denver Nuggets": "DEN",
    "Detroit Pistons": "DET", "Golden State Warriors": "GSW", "Houston Rockets": "HOU", "Indiana Pacers": "IND",
    "Los Angeles Clippers": "LAC", "LA Clippers": "LAC", "Los Angeles Lakers": "LAL", "Memphis Grizzlies": "MEM",
    "Miami Heat": "MIA", "Milwaukee Bucks": "MIL", "Minnesota Timberwolves": "MIN", "New Orleans Pelicans": "NOP",
    "New York Knicks": "NYK", "Oklahoma City Thunder": "OKC", "Orlando Magic": "ORL", "Philadelphia 76ers": "PHI",
    "Phoenix Suns": "PHX", "Portland Trail Blazers": "POR", "Sacramento Kings": "SAC", "San Antonio Spurs": "SAS",
    "Toronto Raptors": "TOR", "Utah Jazz": "UTA", "Washington Wizards": "WAS",
}
ESPN_TRI = {"NY": "NYK", "GS": "GSW", "SA": "SAS", "NO": "NOP", "UTAH": "UTA", "WSH": "WAS"}
NBA_HDR = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.nba.com/", "Origin": "https://www.nba.com",
           "Accept": "application/json", "x-nba-stats-origin": "stats", "x-nba-stats-token": "true"}


# ---------------------------------------------------------------------------
# small utils
# ---------------------------------------------------------------------------

def _f(v) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _dates(a: str, b: str) -> List[str]:
    d0, d1 = _date.fromisoformat(a), _date.fromisoformat(b)
    return [(d0 + timedelta(days=i)).isoformat() for i in range((d1 - d0).days + 1)]


def _git(repo: Path, *args: str, stdin: Optional[str] = None) -> str:
    env = dict(os.environ, MSYS_NO_PATHCONV="1")
    r = subprocess.run(["git", "-C", str(repo), *args], input=stdin, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=env)
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args[:3])} failed: {r.stderr[:300]}")
    return r.stdout


def _get_json(url: str, cache: Path, headers: Dict[str, str]) -> Dict:
    if cache.exists() and cache.stat().st_size > 0:
        return json.loads(cache.read_text(encoding="utf-8"))
    last = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as fh:
                data = json.load(fh)
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(data), encoding="utf-8")
            return data
        except Exception as exc:  # network: retry, then surface
            last = exc
            time.sleep(2 + 3 * attempt)
    raise RuntimeError(f"fetch failed {url}: {last}")


def _clip(p: float, lo: float = 1e-3) -> float:
    return min(1 - lo, max(lo, p))


def _logloss(p: float, y: int) -> float:
    p = _clip(p)
    return -(math.log(p) if y else math.log(1 - p))


def _american(o) -> Optional[float]:
    """A quotable American price, or None. Accepts numbers and wire strings ('+150', '-110.5');
    refuses None, '', text, non-finite and |price| < 100 (0 included) -- none of which is a price.
    Guard required by tests/test_probability_differential.py (lane nhl-props-converter-guard)."""
    if o is None or isinstance(o, bool):
        return None
    try:
        x = float(str(o).strip()) if isinstance(o, str) else float(o)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(x) or abs(x) < 100:
        return None
    return x


def _implied(o) -> Optional[float]:
    x = _american(o)
    if x is None:
        return None
    return 100.0 / (x + 100.0) if x > 0 else -x / (-x + 100.0)


def _american_to_dec(o) -> Optional[float]:
    x = _american(o)
    if x is None:
        return None
    return 1 + (x / 100.0 if x > 0 else 100.0 / -x)


def _devig(pa, pb) -> Optional[float]:
    """Proportional de-vig of a two-sided American pair -> P(side a). None if either side is not a price."""
    ia, ib = _implied(pa), _implied(pb)
    if ia is None or ib is None:
        return None
    return ia / (ia + ib)


def _std_pair(a: Optional[float], b: Optional[float]) -> Optional[Tuple[float, float]]:
    """A spread/total price pair only if it looks like a main line's juice: both sides in
    [-140, -100] U [100, 120] and total implied in [1.00, 1.10]. The upstream consensus pairs main
    points with alt-line prices (e.g. -245/+180 on a main spread) and leaves 39% of rows unpriced."""
    a, b = _american(a), _american(b)
    if a is None or b is None:
        return None
    ok = lambda x: (-140 <= x <= -100) or (100 <= x <= 120)  # noqa: E731
    if not (ok(a) and ok(b)):
        return None
    s = _implied(a) + _implied(b)
    return (a, b) if 1.0 <= s <= 1.10 else None


def _ncdf(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def _boot_ci(rows: List[Tuple[str, float]], n_boot: int = 1000, seed: int = 7) -> Tuple[float, float, float]:
    """Mean of per-row values with a GAME-clustered bootstrap 95% CI (same estimator as NHL)."""
    if not rows:
        return (float("nan"),) * 3  # type: ignore[return-value]
    keys: Dict[str, int] = {}
    idx = np.array([keys.setdefault(g, len(keys)) for g, _ in rows])
    vals = np.array([v for _, v in rows], dtype=float)
    sums = np.bincount(idx, weights=vals)
    cnts = np.bincount(idx).astype(float)
    point = float(sums.sum() / cnts.sum())
    rng = np.random.default_rng(seed)
    n = len(sums)
    draws = rng.integers(0, n, size=(n_boot, n))
    stats = np.sort(sums[draws].sum(axis=1) / cnts[draws].sum(axis=1))
    return point, float(stats[int(0.025 * n_boot)]), float(stats[int(0.975 * n_boot) - 1])


def _metrics(rows: List[Dict], pred_key: str) -> Dict:
    q = [r for r in rows if r.get(pred_key) is not None]
    n = len(q)
    if n == 0:
        return {"n": 0}
    err = [r[pred_key] - r["y"] for r in q]
    return {"n": n, "mean_pred": round(sum(r[pred_key] for r in q) / n, 4), "bias": round(sum(err) / n, 4),
            "mae": round(sum(abs(e) for e in err) / n, 4), "rmse": round(math.sqrt(sum(e * e for e in err) / n), 4)}


def _prob_block(rows: List[Dict], key: str) -> Dict:
    q = [r for r in rows if r.get(key) is not None]
    if not q:
        return {"n": 0}
    return {"n": len(q), "mean_p": round(sum(r[key] for r in q) / len(q), 4),
            "brier": round(sum((r[key] - r["yb"]) ** 2 for r in q) / len(q), 5),
            "logloss": round(sum(_logloss(r[key], r["yb"]) for r in q) / len(q), 5)}


def _delta(rows: List[Dict], a: str, b: str, kind: str) -> Dict:
    """Mean of (loss_a - loss_b) per row, game-clustered CI. kind: 'abs' (point) or 'brier'."""
    q = [r for r in rows if r.get(a) is not None and r.get(b) is not None]
    if not q:
        return {"n": 0, "point": None, "ci95": [None, None]}
    if kind == "abs":
        vals = [(r["gid"], abs(r[a] - r["y"]) - abs(r[b] - r["y"])) for r in q]
    else:
        vals = [(r["gid"], (r[a] - r["yb"]) ** 2 - (r[b] - r["yb"]) ** 2) for r in q]
    p, lo, hi = _boot_ci(vals)
    return {"n": len(q), "games": len({r["gid"] for r in q}), "point": round(p, 5), "ci95": [round(lo, 5), round(hi, 5)]}


def _verdict(d: Dict, n: int, min_n: int, better: str = "MODEL_BETTER", worse: str = "MODEL_WORSE") -> str:
    if n < min_n or d.get("point") is None:
        return "INSUFFICIENT_N"
    return better if d["ci95"][1] < 0 else (worse if d["ci95"][0] > 0 else "NO_DIFFERENCE")


# ---------------------------------------------------------------------------
# 1. AS-OF artifact selection from git history
# ---------------------------------------------------------------------------

def _repo_paths(args) -> Dict[str, Path]:
    up = args.upstream
    if not (up / ".git").exists():
        up.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "-q", "--filter=blob:none", "--no-checkout", UPSTREAM_URL, str(up)], check=True)
    else:
        try:
            _git(up, "fetch", "-q", "origin")
        except RuntimeError as exc:
            print(f"[warn] upstream fetch failed, using local history: {exc}", flush=True)
    return {"upstream": up, "syndicate": args.syndicate_repo}


def _commit_index(repo: Path, ref: str, prefix: str) -> Dict[str, List[Tuple[int, str]]]:
    """path -> [(committer unix ts, commit sha)] for every commit that added/modified it on `ref`."""
    out = _git(repo, "log", ref, "--format=@@%H %ct", "--name-only", "--diff-filter=AM", "--", prefix)
    idx: Dict[str, List[Tuple[int, str]]] = defaultdict(list)
    cur = None
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("@@"):
            sha, ts = line[2:].split()
            cur = (int(ts), sha)
        elif line and cur:
            idx[line].append(cur)
    return idx


def _pick(versions: List[Tuple[int, str]], cutoff_ts: int) -> Tuple[Optional[str], Dict]:
    pre = [v for v in versions if v[0] < cutoff_ts]
    info = {"versions": len(versions), "pre_tip": len(pre)}
    if not pre:
        return None, info
    ts, sha = max(pre)
    info["commit_ts"] = ts
    info["lead_min"] = round((cutoff_ts - ts) / 60.0, 1)
    return sha, info


def _batch_read(repo: Path, specs: List[str]) -> Dict[str, bytes]:
    """Read many `sha:path` blobs, prefetching missing ones from a partial clone in one round trip."""
    if not specs:
        return {}
    # Resolve sha:path -> blob oid with ONE `ls-tree` per commit: trees are local in a blobless clone,
    # whereas `cat-file --batch-check` on a missing blob lazily fetches it, one network round trip each.
    by_commit: Dict[str, Dict[str, str]] = defaultdict(dict)
    for s in specs:
        sha, path = s.split(":", 1)
        by_commit[sha][path] = s
    oid_of: Dict[str, str] = {}
    for sha, paths in by_commit.items():
        dirs = sorted({p.rsplit("/", 1)[0] + "/" for p in paths})
        listing = _git(repo, "ls-tree", sha, "--", *dirs)
        for line in listing.splitlines():
            meta, path = line.split("\t", 1)
            if path in paths:
                oid_of[paths[path]] = meta.split()[2]
    oids = [oid_of.get(s, "") for s in specs]
    unique = sorted({o for o in oids if o})
    missing = []
    chk = subprocess.run(["git", "-C", str(repo), "-c", "fetch.negotiationAlgorithm=noop", "cat-file",
                          "--batch-check=%(objectname) %(objecttype)", "--buffer"],
                         input=("\n".join(unique) + "\n").encode(), capture_output=True,
                         env=dict(os.environ, GIT_NO_LAZY_FETCH="1"))
    for line in chk.stdout.decode().splitlines():
        if line.endswith(" missing"):
            missing.append(line.split()[0])
    for i in range(0, len(missing), 500):
        # bytes, not text: Windows text-mode stdin writes \r\n and every oid becomes an invalid refspec
        r = subprocess.run(["git", "-C", str(repo), "-c", "fetch.negotiationAlgorithm=noop", "fetch", "-q", "origin",
                            "--no-tags", "--no-write-fetch-head", "--stdin"],
                           input=("\n".join(missing[i:i + 500]) + "\n").encode(), capture_output=True)
        if r.returncode != 0:
            print(f"[warn] blob fetch batch {i // 500} rc={r.returncode}: {r.stderr.decode(errors='replace')[-300:]}", flush=True)
    blobs: Dict[str, bytes] = {}
    p = subprocess.run(["git", "-C", str(repo), "cat-file", "--batch"], input=("\n".join(unique) + "\n").encode(),
                       capture_output=True, env=dict(os.environ, GIT_NO_LAZY_FETCH="1"))
    buf = p.stdout
    pos = 0
    for oid in unique:
        nl = buf.index(b"\n", pos)
        header = buf[pos:nl].decode()
        pos = nl + 1
        if header.endswith("missing"):
            continue
        size = int(header.split()[2])
        blobs[oid] = buf[pos:pos + size]
        pos += size + 1
    return {s: blobs[o] for s, o in zip(specs, oids) if o in blobs}


def collect(args, cutoffs: Dict[str, int]) -> Dict:
    repos = _repo_paths(args)
    out_dir: Path = args.out / "asof"
    out_dir.mkdir(parents=True, exist_ok=True)
    indexes = {name: _commit_index(repos[r], ref, prefix) for name, (r, ref, prefix) in SOURCES.items()}
    manifest: Dict = {"families": {}, "smart_sim": {}}
    wanted: Dict[str, List[Tuple[str, str, str]]] = defaultdict(list)  # repo -> [(spec, dest, key)]
    for fam, tmpl in FAMILIES.items():
        fam_m = manifest["families"].setdefault(fam, {})
        for d, cut in sorted(cutoffs.items()):
            for src, (r, _ref, prefix) in SOURCES.items():
                path = prefix + tmpl.format(d=d)
                vers = indexes[src].get(path)
                if not vers:
                    continue
                sha, info = _pick(vers, cut)
                info["source"] = src
                if sha is None:
                    fam_m.setdefault(d, info)  # remember a post-tip-only file, keep looking at other sources
                    continue
                dest = out_dir / fam / f"{d}.csv"
                fam_m[d] = info
                wanted[r].append((f"{sha}:{path}", str(dest), f"{fam}|{d}"))
                break
    # smart-sim per-game JSON (game lines' served quantity)
    for src, (r, _ref, prefix) in SOURCES.items():
        for path, vers in indexes[src].items():
            name = path.rsplit("/", 1)[-1]
            if not (name.startswith("smart_sim_") and name.endswith(".json")):
                continue
            parts = name[len("smart_sim_"):-5].split("_")
            if len(parts) != 3 or parts[0] not in cutoffs:
                continue
            d = parts[0]
            key = f"{d}_{parts[1]}_{parts[2]}"
            if key in manifest["smart_sim"] and manifest["smart_sim"][key].get("commit_ts"):
                continue
            sha, info = _pick(vers, cutoffs[d])
            info["source"] = src
            manifest["smart_sim"][key] = info
            if sha:
                wanted[r].append((f"{sha}:{path}", str(out_dir / "smart_sim" / f"{key}.json"), f"smart_sim|{key}"))
    for r, items in wanted.items():
        blobs = _batch_read(repos[r], [s for s, _, _ in items])
        for spec, dest, key in items:
            if spec in blobs:
                Path(dest).parent.mkdir(parents=True, exist_ok=True)
                Path(dest).write_bytes(blobs[spec])
            else:
                fam, k = key.split("|", 1)
                (manifest["smart_sim"] if fam == "smart_sim" else manifest["families"][fam])[k]["read_failed"] = True
    (args.out / "asof_manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return manifest


# ---------------------------------------------------------------------------
# 2. actuals: ESPN scoreboards (finals, linescores, tip times), stats.nba player logs
# ---------------------------------------------------------------------------

def fetch_scoreboards(args, dates: List[str]) -> Dict[str, List[Dict]]:
    games: Dict[str, List[Dict]] = {}
    for d in dates:
        url = f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates={d.replace('-', '')}&limit=40"
        data = _get_json(url, args.out / "cache" / "espn" / f"{d}.json", {"User-Agent": "Mozilla/5.0"})
        rows = []
        for ev in data.get("events") or []:
            comp = (ev.get("competitions") or [{}])[0]
            st = ((comp.get("status") or {}).get("type") or {})
            season_type = ((ev.get("season") or {}).get("type"))
            teams = {}
            for c in comp.get("competitors") or []:
                ab = (c.get("team") or {}).get("abbreviation", "")
                teams[c.get("homeAway")] = {"tri": ESPN_TRI.get(ab, ab), "pts": _f(c.get("score")),
                                            "ls": [_f(x.get("value")) for x in c.get("linescores") or []]}
            if "home" not in teams or "away" not in teams:
                continue
            rows.append({"date": d, "start": ev.get("date"), "completed": bool(st.get("completed")),
                         "season_type": season_type, "home": teams["home"]["tri"], "away": teams["away"]["tri"],
                         "home_pts": teams["home"]["pts"], "away_pts": teams["away"]["pts"],
                         "home_ls": teams["home"]["ls"], "away_ls": teams["away"]["ls"]})
        if rows:
            games[d] = rows
    return games


def _ts(iso: str) -> int:
    s = iso.replace("Z", "+00:00")
    if len(s) == 22 and s[16] == "+":  # 2026-02-11T00:30+00:00
        s = s[:16] + ":00" + s[16:]
    return int(datetime.fromisoformat(s).timestamp())


def fetch_player_logs(args) -> List[Dict]:
    rows: List[Dict] = []
    for stype in ("Regular Season", "Playoffs"):
        url = (f"https://stats.nba.com/stats/playergamelogs?Season={SEASON}&SeasonType={stype.replace(' ', '%20')}"
               "&LeagueID=00")
        data = _get_json(url, args.out / "cache" / "statsnba" / f"playergamelogs_{SEASON}_{stype.replace(' ', '_')}.json", NBA_HDR)
        rs = data["resultSets"][0]
        hdr = rs["headers"]
        for rr in rs["rowSet"]:
            r = dict(zip(hdr, rr))
            rows.append({"pid": int(r["PLAYER_ID"]), "name": r["PLAYER_NAME"], "team": r["TEAM_ABBREVIATION"],
                         "gid": str(r["GAME_ID"]), "date": str(r["GAME_DATE"])[:10], "stype": stype,
                         "min": _f(r.get("MIN")) or 0.0, **{k: (_f(r.get(c)) or 0.0) for k, c in LOG_COL.items()}})
    for r in rows:
        for c, parts in COMBOS.items():
            r[c] = sum(r[p] for p in parts)
    return rows


class History:
    """Per-player 2025-26 game history (played games only), for the as-of baselines."""

    def __init__(self, logs: List[Dict]) -> None:
        self.h: Dict[int, List[Dict]] = defaultdict(list)
        self.by_pd: Dict[Tuple[int, str], Dict] = {}
        for r in logs:
            self.by_pd[(r["pid"], r["date"])] = r
            if r["min"] > 0:
                self.h[r["pid"]].append(r)
        for v in self.h.values():
            v.sort(key=lambda r: r["date"])

    def resolve(self, pid: int, name: str, date: str, counter: Counter) -> Optional[int]:
        """NBA PLAYER_ID for a projection row on `date`. By id first; the 2026 playoff files carry ESPN
        ids, so fall back to a UNIQUE same-date normalized-name match among players with a log that day."""
        if (pid, date) in self.by_pd:
            counter["join_by_id"] += 1
            return pid
        if not hasattr(self, "_names"):
            from syndicate.features.shared.basketball_props_edges import _norm_name
            self._norm = _norm_name
            self._names: Dict[Tuple[str, str], set] = defaultdict(set)
            for (p, d), r in self.by_pd.items():
                self._names[(d, _norm_name(r["name"]))].add(p)
        cand = self._names.get((date, self._norm(name)), set())
        if len(cand) == 1:
            counter["join_by_name_same_date"] += 1
            return next(iter(cand))
        counter["join_name_ambiguous" if cand else "join_none"] += 1
        return None

    def asof(self, pid: int, date: str, last: int = 0) -> Tuple[Optional[Dict[str, float]], int]:
        g = [r for r in self.h.get(pid, []) if r["date"] < date]
        if last:
            g = g[-last:]
        if not g:
            return None, 0
        return {m: sum(r[m] for r in g) / len(g) for m in PROP_MARKETS}, len(g)


# ---------------------------------------------------------------------------
# 2b. OddsAPI HISTORICAL backfill (user-approved 2026-10-02, ~138k credits): one pre-tip snapshot
#     per game for props, one pre-first-tip slate snapshot per date for main game lines.
#     Writes ONLY under --out/cache (never data/ or the production quote log); dry run by default.
# ---------------------------------------------------------------------------

ODDSAPI = "https://api.the-odds-api.com/v4"
HIST_PROP_MARKETS = ("player_points", "player_rebounds", "player_assists", "player_threes",
                     "player_points_rebounds_assists", "player_points_rebounds", "player_points_assists",
                     "player_rebounds_assists", "player_steals", "player_blocks")
HIST_GAME_MARKETS = ("h2h", "spreads", "totals")


def _api_key() -> str:
    """Env first; an EMPTY env value falls through to the PRIMARY tree's .env (2026-10-05: the shell-exported key is a
    different, deactivated key and wins by precedence -- run with `ODDS_API_KEY= ...`). The value is never printed."""
    for name in ("ODDS_API_KEY", "ODDSAPI_KEY", "THE_ODDS_API_KEY"):
        if (os.environ.get(name) or "").strip():
            return os.environ[name].strip()
    env = _primary_repo() / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8-sig", errors="ignore").splitlines():
            for name in ("ODDS_API_KEY", "ODDSAPI_KEY", "THE_ODDS_API_KEY"):
                if line.strip().startswith(name + "="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise RuntimeError("no OddsAPI key in env or the primary tree's .env")


class Budget:
    MAX_CONSECUTIVE_FAILURES = 5

    def __init__(self, ceiling: int) -> None:
        self.ceiling, self.spent, self.calls = ceiling, 0, 0
        self.last_remaining: Optional[str] = None
        self.consecutive_failures = 0

    def failed(self, what: str) -> None:
        """A dead key returns 401 on every call; a loop that skips failures then spends nothing, caches nothing and looks
        like a stall. Abort instead (memory: oddsapi-key-access)."""
        self.consecutive_failures += 1
        if self.consecutive_failures >= self.MAX_CONSECUTIVE_FAILURES:
            raise RuntimeError(f"{self.consecutive_failures} consecutive OddsAPI failures (last: {what}); aborting")

    def charge(self, headers) -> None:
        self.calls += 1
        try:
            self.spent += int(headers.get("x-requests-last") or 0)
        except ValueError:
            pass
        self.last_remaining = headers.get("x-requests-remaining")
        if self.spent > self.ceiling:
            raise RuntimeError(f"credit ceiling {self.ceiling} exceeded ({self.spent}); aborting -- cached work is kept")


def _odds_get(path: str, params: Dict[str, str], cache: Path, budget: Budget, execute: bool) -> Optional[Dict]:
    if cache.exists() and cache.stat().st_size > 0:
        return json.loads(cache.read_text(encoding="utf-8"))
    if not execute:
        return None
    key = _api_key()
    from urllib.parse import urlencode
    url = f"{ODDSAPI}{path}?{urlencode({**params, 'apiKey': key})}"
    for attempt in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Syndicate-backtest/1.0"}), timeout=60) as fh:
                data = json.load(fh)
                budget.charge(fh.headers)
                budget.consecutive_failures = 0
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(data), encoding="utf-8")
            return data
        except urllib.error.HTTPError as exc:  # type: ignore[attr-defined]
            budget.charge(exc.headers or {})
            if exc.code in (401, 403):
                budget.failed(f"HTTP {exc.code} on {path}")
                raise RuntimeError(f"OddsAPI HTTP {exc.code} on {path} (key rejected; value not printed)")
            if exc.code in (404, 422):
                cache.parent.mkdir(parents=True, exist_ok=True)
                cache.write_text(json.dumps({"_http": exc.code}), encoding="utf-8")
                return {"_http": exc.code}
            time.sleep(3 + 5 * attempt)
        except Exception:  # network: retry; the URL carries the key, so never print it
            time.sleep(3 + 5 * attempt)
    budget.failed(f"network on {path}")
    raise RuntimeError(f"historical fetch failed for {path} (key redacted)")


def _iso(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch_hist_odds(args, scoreboards: Dict[str, List[Dict]], cutoffs: Dict[str, int]) -> Dict:
    import urllib.error  # noqa: F401  (HTTPError above)
    budget = Budget(args.max_credits)
    root = args.out / "cache" / "oddsapi_hist"
    n_dates = n_events = n_cached = 0
    est = 0
    for d in sorted(scoreboards):
        games = [g for g in scoreboards[d] if g["completed"]]
        if not games or d not in cutoffs:
            continue
        n_dates += 1
        first = cutoffs[d]
        snap_day = _iso(first - args.snap_min * 60)
        _odds_get("/historical/sports/basketball_nba/odds",
                  {"date": snap_day, "regions": "us", "markets": ",".join(HIST_GAME_MARKETS), "oddsFormat": "american"},
                  root / "games" / f"{d}.json", budget, args.execute)
        ev = _odds_get("/historical/sports/basketball_nba/events", {"date": snap_day},
                       root / "events" / f"{d}.json", budget, args.execute)
        est += 1 + 10 * len(HIST_GAME_MARKETS)
        if ev is None:  # dry run: size props from the ESPN game count
            est += 10 * len(HIST_PROP_MARKETS) * len(games)
            continue
        want = {(g["home"], g["away"]) for g in games}
        for e in ((ev or {}).get("data") or []):
            key = (TEAM_TRI.get(e.get("home_team", "")), TEAM_TRI.get(e.get("away_team", "")))
            if key not in want:
                continue
            n_events += 1
            est += 10 * len(HIST_PROP_MARKETS)
            cpath = root / "props" / d / f"{e['id']}.json"
            if cpath.exists():
                n_cached += 1
                continue
            snap = _iso(_ts(e["commence_time"]) - args.snap_min * 60)
            _odds_get(f"/historical/sports/basketball_nba/events/{e['id']}/odds",
                      {"date": snap, "regions": "us", "markets": ",".join(HIST_PROP_MARKETS), "oddsFormat": "american"},
                      cpath, budget, args.execute)
        if args.execute and n_dates % 10 == 0:
            print(f"[odds] {d}: credits spent {budget.spent} in {budget.calls} calls", flush=True)
    out = {"dates": n_dates, "events_matched": n_events, "events_cached": n_cached, "estimate_credits_upper": est,
           "spent": budget.spent, "calls": budget.calls, "remaining_header": budget.last_remaining, "executed": args.execute}
    print(f"[odds] {json.dumps(out)}", flush=True)
    return out


def hist_props_csv(args, d: str) -> Optional[Path]:
    """Flatten the cached historical event odds for date d into production's raw props schema."""
    src = args.out / "cache" / "oddsapi_hist" / "props" / d
    if not src.exists():
        return None
    rows = []
    for f in sorted(src.glob("*.json")):
        payload = json.loads(f.read_text(encoding="utf-8"))
        snap = payload.get("timestamp") or ""
        ev = payload.get("data") or {}
        for bk in ev.get("bookmakers") or []:
            for mk in bk.get("markets") or []:
                for oc in mk.get("outcomes") or []:
                    rows.append([snap, ev.get("id"), ev.get("commence_time"), bk.get("key"), bk.get("title"), mk.get("key"),
                                 oc.get("name"), oc.get("description"), oc.get("point"), oc.get("price"),
                                 mk.get("last_update") or bk.get("last_update"), ev.get("home_team"), ev.get("away_team")])
    if not rows:
        return None
    dest = args.out / "asof" / "props_odds_hist" / f"{d}.csv"
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["snapshot_ts", "event_id", "commence_time", "bookmaker", "bookmaker_title", "market", "outcome_name",
                    "player_name", "point", "price", "last_update", "home_team", "away_team"])
        w.writerows(rows)
    return dest


def hist_game_book(args, d: str) -> Dict[Tuple[str, str], Dict]:
    """Per game: the de-vigged MULTI-BOOK book from the pre-first-tip slate snapshot. ML = mean of
    per-book de-vigged P(home); spread/total = the modal main line, mean per-book de-vig at that line,
    median prices for ROI. Replaces the upstream consensus, whose prices are unreliable."""
    p = args.out / "cache" / "oddsapi_hist" / "games" / f"{d}.json"
    if not p.exists():
        return {}
    payload = json.loads(p.read_text(encoding="utf-8"))
    out = {}
    for ev in payload.get("data") or []:
        h, a = TEAM_TRI.get(ev.get("home_team", "")), TEAM_TRI.get(ev.get("away_team", ""))
        if not h or not a:
            continue
        ml, sp, tt = [], defaultdict(list), defaultdict(list)
        for bk in ev.get("bookmakers") or []:
            for mk in bk.get("markets") or []:
                oc = {o.get("name"): o for o in mk.get("outcomes") or []}
                if mk.get("key") == "h2h":
                    ph = _devig(_f((oc.get(ev["home_team"]) or {}).get("price")), _f((oc.get(ev["away_team"]) or {}).get("price")))
                    if ph is not None:
                        ml.append(ph)
                elif mk.get("key") == "spreads":
                    ho, ao = oc.get(ev["home_team"]) or {}, oc.get(ev["away_team"]) or {}
                    pt, hp, ap = _f(ho.get("point")), _f(ho.get("price")), _f(ao.get("price"))
                    if pt is not None and _devig(hp, ap) is not None:  # both sides quotable
                        sp[pt].append((_devig(hp, ap), hp, ap))
                elif mk.get("key") == "totals":
                    o, u = oc.get("Over") or {}, oc.get("Under") or {}
                    pt, op, up = _f(o.get("point")), _f(o.get("price")), _f(u.get("price"))
                    if pt is not None and _devig(op, up) is not None:
                        tt[pt].append((_devig(op, up), op, up))
        rec: Dict = {"books_ml": len(ml)}
        if ml:
            rec["p_home_ml"] = sum(ml) / len(ml)
        for name, dd in (("spread", sp), ("total", tt)):
            if dd:
                line = max(dd, key=lambda k: len(dd[k]))
                qs = dd[line]
                rec[name] = {"line": line, "p": sum(q[0] for q in qs) / len(qs), "books": len(qs),
                             "price_a": float(np.median([q[1] for q in qs])), "price_b": float(np.median([q[2] for q in qs]))}
        out[(h, a)] = rec
    return out


# ---------------------------------------------------------------------------
# 3. scoring: player props, point accuracy (all as-of prediction dates)
# ---------------------------------------------------------------------------

def _read_csv(path: Path) -> List[Dict]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="", errors="replace") as fh:
        return list(csv.DictReader(fh))


def _pred_mean(row: Dict, cols: Iterable[str]) -> Dict[str, Optional[float]]:
    """Production's mean selection: `mean_<stat>` if the COLUMN exists, else `pred_<stat>`; combos are sums."""
    cols = set(cols)
    m: Dict[str, Optional[float]] = {}
    for s in ("pts", "reb", "ast", "threes", "pra", "stl", "blk", "tov"):
        col = f"mean_{s}" if f"mean_{s}" in cols else f"pred_{s}"
        m[s] = _f(row.get(col))
    for c, parts in (("pr", ("pts", "reb")), ("pa", ("pts", "ast")), ("ra", ("reb", "ast"))):
        m[c] = None if any(m[p] is None for p in parts) else sum(m[p] for p in parts)  # type: ignore[misc]
    return m


def score_props_point(args, manifest: Dict, hist: History, phase_of: Dict[str, str]) -> Dict:
    rows: Dict[str, List[Dict]] = defaultdict(list)
    drops = Counter()
    engine = Counter()
    for d, info in sorted(manifest["families"]["props_predictions"].items()):
        if not info.get("commit_ts") or d < args.start:
            drops["no_pre_tip_file_dates"] += 0 if info.get("commit_ts") else 1
            continue
        preds = _read_csv(args.out / "asof" / "props_predictions" / f"{d}.csv")
        if not preds:
            drops["empty_file_dates"] += 1
            continue
        cols = preds[0].keys()
        engine["smart_sim_mean_cols" if "mean_pts" in cols else "pred_cols_only"] += 1
        # engine: smartsim = the file carries mean_* (what production serves today); onnx = pred_* only
        ph = f"{phase_of.get(d, 'unknown')}:{'smartsim' if 'mean_pts' in cols else 'onnx'}"
        seen = set()
        for p in preds:
            raw_pid = int(_f(p.get("player_id")) or 0)
            if str(p.get("playing_today", "True")).strip().lower() in ("false", "0"):
                drops["flagged_not_playing"] += 1
                continue
            pid = hist.resolve(raw_pid, str(p.get("player_name") or ""), d, drops) if raw_pid else None
            if not pid:
                drops["no_game_log_that_date(not on slate, DNP or unmatched)"] += 1
                continue
            if (pid, d) in seen:
                drops["duplicate_player_date"] += 1
                continue
            seen.add((pid, d))
            act = hist.by_pd[(pid, d)]
            if act["min"] <= 0:
                drops["did_not_play"] += 1
                continue
            base_a, na = hist.asof(pid, d)
            base_b, _ = hist.asof(pid, d, last=10)
            if base_a is None:
                drops["no_prior_game_baseline"] += 1
                continue
            mean = _pred_mean(p, cols)
            for mk in PROP_MARKETS:
                if mean.get(mk) is None:
                    drops[f"no_model_mean_{mk}"] += 1
                    continue
                rows[f"{ph}|{mk}"].append({"gid": act["gid"], "date": d, "pid": pid, "y": act[mk], "model": mean[mk],
                                          "base_a": base_a[mk], "base_b": base_b[mk] if base_b else None, "n_prior": na})
    res: Dict = {"drops": dict(drops), "engine_by_date": dict(engine), "markets": {}}
    for k, rr in sorted(rows.items()):
        n = len(rr)
        d = _delta(rr, "model", "base_a", "abs")
        res["markets"][k] = {"n": n, "games": len({r["gid"] for r in rr}), "dates": len({r["date"] for r in rr}),
                             "mean_actual": round(sum(r["y"] for r in rr) / n, 4), "model": _metrics(rr, "model"),
                             "base_a": _metrics(rr, "base_a"), "base_b": _metrics(rr, "base_b"),
                             "mae_delta_vs_a": d, "mae_delta_vs_b": _delta(rr, "model", "base_b", "abs"),
                             "verdict": _verdict(d, n, args.min_n)}
    return res


# ---------------------------------------------------------------------------
# 4. scoring: player props vs the de-vigged book, production probability
# ---------------------------------------------------------------------------

def _sigma_for(stat: str, row: Dict) -> float:
    from syndicate.features.shared.basketball_props_edges import _SigmaConfig
    sc = _SigmaConfig()

    def sd(s: str) -> float:
        v = _f(row.get(f"sd_{s}"))
        return v if (v is not None and 0.05 < v < 50.0) else float(getattr(sc, s))

    if stat in COMBOS and stat != "pra":
        return math.sqrt(sum(sd(p) ** 2 for p in COMBOS[stat]))
    return sd(stat)


def score_props_book(args, manifest: Dict, hist: History, phase_of: Dict[str, str]) -> Dict:
    import contextlib
    from syndicate.features.shared.basketball_props_edges import _compute_props_edges_file_only_local

    stats = Counter()
    parity = Counter()
    rows: List[Dict] = []
    odds_m = manifest["families"]["props_odds"]
    for d, info in sorted(manifest["families"]["props_predictions"].items()):
        oinfo = odds_m.get(d) or {}
        if not info.get("commit_ts"):
            continue
        pred_path = args.out / "asof" / "props_predictions" / f"{d}.csv"
        # prefer the OddsAPI historical backfill (one pre-tip snapshot per game, every US book); fall back to the
        # committed raw snapshot (10 dates) when a date was not backfilled
        hist_path = hist_props_csv(args, d)
        if hist_path is not None:
            odds_path = hist_path
            stats["dates_odds_oddsapi_hist"] += 1
        elif oinfo.get("commit_ts"):
            odds_path = args.out / "asof" / "props_odds" / f"{d}.csv"
            stats["dates_odds_committed"] += 1
        else:
            continue
        pred_rows = _read_csv(pred_path)
        preds = {int(_f(p.get("player_id")) or 0): p for p in pred_rows}
        eng = "smartsim" if pred_rows and "mean_pts" in pred_rows[0] else "onnx"
        with tempfile.TemporaryDirectory() as td:  # no calibration json here == the fleet's state
            (Path(td) / "data" / "processed").mkdir(parents=True)
            log = io.StringIO()
            try:
                with contextlib.redirect_stdout(log):
                    edges = _compute_props_edges_file_only_local(source_root=Path(td), date_str=d, raw_path=odds_path,
                                                                 predictions_path=pred_path, calibrate_prob=True)
            except ValueError as exc:  # production's own refusal: nothing joinable on this date
                stats["dates_production_refused"] += 1
                stats.setdefault("refused_detail", [])  # type: ignore[arg-type]
                stats["refused_detail"].append(f"{d}: {exc}; {log.getvalue().strip()[-200:]}")  # type: ignore[union-attr]
                continue
        join = [ln for ln in log.getvalue().splitlines() if "PROP_NAME_JOIN" in ln]
        if join:
            stats.setdefault("name_join", [])  # type: ignore[arg-type]
            stats["name_join"].append(f"{d}: {join[-1].split('PROP_NAME_JOIN', 1)[1].strip()}")  # type: ignore[union-attr]
        stats["dates"] += 1
        cut = (manifest.get("cutoffs") or {}).get(d)
        latest: Dict[Tuple, Dict] = {}
        records = edges.to_dict("records")
        # Production's short-key fallback is a many-to-many merge: one BOOK name can come back attached
        # to several player_ids. Such lines are excluded and counted (NHL: "ambiguous_match").
        owners: Dict[Tuple, set] = defaultdict(set)
        for e in records:
            owners[(str(e.get("player_name")), str(e.get("stat")), _f(e.get("line")), str(e.get("bookmaker")))].add(
                int(_f(e.get("player_id")) or 0))
        for e in records:
            if len(owners[(str(e.get("player_name")), str(e.get("stat")), _f(e.get("line")), str(e.get("bookmaker")))]) > 1:
                stats["ambiguous_player_match_excluded"] += 1
                continue
            stats["edge_rows"] += 1
            stat = str(e.get("stat") or "")
            side = str(e.get("side") or "")
            if stat in ("dd", "td"):
                stats["yes_no_market_excluded"] += 1
                continue
            pid = int(_f(e.get("player_id")) or 0)
            line, price = _f(e.get("line")), _f(e.get("price"))
            if not pid or line is None or price is None:
                stats["unmatched_or_unparseable"] += 1
                continue
            snap = str(e.get("snapshot_ts") or "")
            # pre-tip test against THIS row's own game (the backfill snapshots each game 45 min before its tip, so a
            # date-level first-tip cutoff would drop every later game); fall back to the date cutoff only when the
            # row carries no commence_time
            commence = str(e.get("commence_time") or "")
            limit = _ts(commence) if commence else cut
            if limit and snap and _ts(snap) >= limit:
                stats["snapshot_at_or_after_tip_excluded"] += 1
                continue
            k = (pid, stat, line, str(e.get("bookmaker")), side)
            if k not in latest or snap > latest[k]["snap"]:
                latest[k] = {"snap": snap, "price": price, "mp": _f(e.get("model_prob")), "mpr": _f(e.get("model_prob_raw")),
                             "commence": str(e.get("commence_time") or "")}
        pairs: Dict[Tuple, Dict] = defaultdict(dict)
        for (pid, stat, line, book, side), v in latest.items():
            pairs[(pid, stat, line, book)][side] = v
        for (pid, stat, line, book), sides in pairs.items():
            if "OVER" not in sides or "UNDER" not in sides:
                stats["one_sided_excluded"] += 1
                continue
            if abs(line - round(line)) < 1e-9:
                stats["integer_line_excluded"] += 1
                continue
            p = preds.get(pid) or {}
            nba_pid = hist.resolve(pid, str(p.get("player_name") or ""), d, stats)
            act = hist.by_pd.get((nba_pid, d)) if nba_pid else None
            if act is None or act["min"] <= 0:
                stats["player_did_not_play_void_or_unmatched"] += 1
                continue
            mean = _pred_mean(p, p.keys()).get(stat)
            if mean is None:
                stats["no_model_projection"] += 1
                continue
            sig = _sigma_for(stat, p)
            p_raw_h = 1.0 - _ncdf((line - mean) / sig)
            o, u = sides["OVER"], sides["UNDER"]
            if o["mpr"] is not None:
                parity["checked"] += 1
                parity["mismatch"] += abs(o["mpr"] - p_raw_h) > 2e-3
            base, _ = hist.asof(nba_pid, d)
            if base is None:
                stats["no_prior_game_baseline"] += 1
                continue
            if _american(o["price"]) is None or _american(u["price"]) is None:
                stats["unquotable_price_excluded"] += 1  # 0 / |price| < 100 / text: not a price
                continue
            y = int(act[stat] > line)
            rows.append({"gid": act["gid"], "date": d, "phase": f"{phase_of.get(d, 'unknown')}:{eng}", "mk": stat, "pid": nba_pid,
                         "line": line, "book": book, "yb": y,
                         "p_book": _devig(o["price"], u["price"]), "vig": _implied(o["price"]) + _implied(u["price"]) - 1,
                         "p_model": o["mp"], "p_model_under": u["mp"], "p_raw": o["mpr"],
                         "p_base": 1.0 - _ncdf((line - base[stat]) / sig),
                         "dec_o": _american_to_dec(o["price"]), "dec_u": _american_to_dec(u["price"])})
    out: Dict = {"filter_counts": dict(stats), "parity_model_prob_raw": dict(parity), "n_rows": len(rows),
                 "games": len({r["gid"] for r in rows}), "dates": sorted({r["date"] for r in rows}), "by_market": {}}
    groups: Dict[str, List[Dict]] = defaultdict(list)
    for r in rows:
        groups[f"{r['phase']}|{r['mk']}"].append(r)
        groups[f"{r['phase']}|ALL"].append(r)
        groups[f"all|{r['mk']}"].append(r)
        groups[f"all:{r['phase'].split(':')[1]}|{r['mk']}"].append(r)
    for k, rr in sorted(groups.items()):
        n = len(rr)
        res = {"n": n, "games": len({r["gid"] for r in rr}), "dates": len({r["date"] for r in rr}),
               "base_rate_over": round(sum(r["yb"] for r in rr) / n, 4),
               "mean_vig": round(sum(r["vig"] for r in rr) / n, 4),
               "under_plus_over_model": round(sum((r["p_model"] or 0) + (r["p_model_under"] or 0) for r in rr) / n, 4)}
        for key in ("p_book", "p_model", "p_raw", "p_base"):
            res[key] = _prob_block(rr, key)
        res["brier_delta_model_vs_book"] = _delta(rr, "p_model", "p_book", "brier")
        res["brier_delta_raw_vs_book"] = _delta(rr, "p_raw", "p_book", "brier")
        res["brier_delta_base_vs_book"] = _delta(rr, "p_base", "p_book", "brier")
        res["ev_bets"] = _ev_bets(rr)
        res["verdict"] = _verdict(res["brier_delta_model_vs_book"], n, args.min_n)
        out["by_market"][k] = res
    return out


def _ev_bets(rr: List[Dict]) -> Dict:
    """Flat stake on the side production's own probabilities price at +EV (over: p_model, under: p_model_under)."""
    bets = []
    for r in rr:
        po, pu = r["p_model"], r["p_model_under"] if r["p_model_under"] is not None else (1 - (r["p_model"] or 0))
        if po is None:
            continue
        ev_o = po * r["dec_o"] - 1
        ev_u = pu * r["dec_u"] - 1
        if max(ev_o, ev_u) <= 0:
            continue
        if ev_o >= ev_u:
            win = r["yb"] == 1
            pnl = (r["dec_o"] - 1) if win else -1.0
        else:
            win = r["yb"] == 0
            pnl = (r["dec_u"] - 1) if win else -1.0
        bets.append((r["gid"], win, pnl))
    if not bets:
        return {"n": 0}
    roi = _boot_ci([(g, p) for g, _, p in bets])
    return {"n": len(bets), "hit_rate": round(sum(w for _, w, _ in bets) / len(bets), 4),
            "roi": round(roi[0], 4), "roi_ci95": [round(roi[1], 4), round(roi[2], 4)]}


# ---------------------------------------------------------------------------
# 5. scoring: game lines (full game, halves, quarters)
# ---------------------------------------------------------------------------

def _game_odds_index(path: Path) -> Dict[Tuple[str, str], Dict]:
    out = {}
    for r in _read_csv(path):
        h, a = TEAM_TRI.get(r.get("home_team", "")), TEAM_TRI.get(r.get("visitor_team", ""))
        if h and a:
            out[(h, a)] = r
    return out


def _period_index(path: Path) -> Dict[Tuple[str, str], Dict]:
    out = {}
    for r in _read_csv(path):
        h, a = TEAM_TRI.get(r.get("home_team", "")), TEAM_TRI.get(r.get("visitor_team", ""))
        if h and a:
            out[(h, a)] = r
    return out


def _segments(g: Dict) -> Optional[Dict[str, Tuple[float, float]]]:
    """Actual (home, away) points per segment from linescores; None unless 4+ quarters are present."""
    hl, al = g["home_ls"], g["away_ls"]
    if len(hl) < 4 or len(al) < 4 or any(x is None for x in hl[:4] + al[:4]):
        return None
    seg = {f"q{i + 1}": (hl[i], al[i]) for i in range(4)}
    seg["h1"] = (hl[0] + hl[1], al[0] + al[1])
    seg["game"] = (g["home_pts"], g["away_pts"])
    return seg


def _sim_quarters(sim: Dict) -> List[Tuple[Optional[float], Optional[float]]]:
    """(home, away) mean points per quarter from either smart-sim shape (`periods.qN` or `quarters[]`)."""
    per = sim.get("periods") if isinstance(sim.get("periods"), dict) else {}
    out = []
    if per:
        for i in range(1, 5):
            q = per.get(f"q{i}") or {}
            out.append((_f(q.get("home_mean")), _f(q.get("away_mean"))))
        return out
    for q in (sim.get("quarters") or [])[:4]:
        if isinstance(q, dict):
            out.append((_f(q.get("home_pts_mu")), _f(q.get("away_pts_mu"))))
    return out


def score_games(args, manifest: Dict, scoreboards: Dict[str, List[Dict]], phase_of: Dict[str, str]) -> Dict:
    from syndicate.features.nba.cards import _margin_win_prob as mwp

    rows: Dict[str, List[Dict]] = defaultdict(list)
    drops = Counter()
    fam = manifest["families"]
    for d, games in sorted(scoreboards.items()):
        if d < args.start:
            continue
        odds = _game_odds_index(args.out / "asof" / "game_odds" / f"{d}.csv") if (fam["game_odds"].get(d) or {}).get("commit_ts") else {}
        plines = _period_index(args.out / "asof" / "period_lines" / f"{d}.csv") if (fam["period_lines"].get(d) or {}).get("commit_ts") else {}
        # multi-book pre-first-tip snapshot from the OddsAPI historical backfill (preferred over the upstream consensus,
        # whose spread/total prices are unreliable); {} when the date was not backfilled
        hist = hist_game_book(args, d)
        preds = {}
        if (fam["predictions"].get(d) or {}).get("commit_ts"):
            for r in _read_csv(args.out / "asof" / "predictions" / f"{d}.csv"):
                h, a = r.get("home_tri") or TEAM_TRI.get(r.get("home_team", "")), r.get("away_tri") or TEAM_TRI.get(r.get("visitor_team", ""))
                if h and a:
                    preds[(h, a)] = r
        ph = phase_of.get(d, "unknown")
        for g in games:
            if not g["completed"] or g["home_pts"] is None:
                drops["not_completed"] += 1
                continue
            seg = _segments(g)
            if seg is None:
                drops["no_linescore"] += 1
                continue
            key = (g["home"], g["away"])
            gid = f"{d}_{g['home']}_{g['away']}"
            o = odds.get(key)
            pl = plines.get(key) or {}
            arms: Dict[str, Dict[str, Tuple[Optional[float], Optional[float]]]] = {}
            ssp = args.out / "asof" / "smart_sim" / f"{gid}.json"
            if ssp.exists():
                sim = json.loads(ssp.read_text(encoding="utf-8"))
                sc = sim.get("score") or {}
                qs = _sim_quarters(sim)
                a: Dict[str, Tuple[Optional[float], Optional[float]]] = {}
                for i, (hm, am) in enumerate(qs, start=1):
                    a[f"q{i}"] = (hm - am, hm + am) if hm is not None and am is not None else (None, None)
                if len(qs) == 4 and all(h is not None and w is not None for h, w in qs):
                    hh, aa = sum(h for h, _ in qs), sum(w for _, w in qs)  # type: ignore[misc]
                    # SERVED: game_cards.pred_margin/pred_total = sum of q1-q4 means (regulation only),
                    # refresh_nba_oddsapi_props._smart_sim_projection_index; cards_sim_detail drops `score`.
                    a["game"] = (hh - aa, hh + aa)
                    a["h1"] = (qs[0][0] + qs[1][0] - qs[0][1] - qs[1][1], qs[0][0] + qs[1][0] + qs[0][1] + qs[1][1])  # type: ignore[operator]
                    a["_sim_p_home_win"] = (_f(sc.get("p_home_win")), None)
                    arms["smart_sim"] = a
                    if o and _f(o.get("home_spread")) is not None and _f(o.get("total")) is not None:
                        # REPLAY of the market anchor Syndicate's port applies by default
                        # (basketball_props_smart_sim._simulate_quarters_local: total 0.7 market + 0.3
                        # model, margin 0.95 market + 0.05 model). The 2025-26 upstream sims carry no
                        # `market_anchor` (raw model), so this arm is ARITHMETIC on the as-of line, not a re-sim.
                        mk_m, mk_t = -_f(o.get("home_spread")), _f(o.get("total"))  # type: ignore[operator]
                        arms["smart_sim_anchored_replay"] = {
                            "game": (0.95 * mk_m + 0.05 * (hh - aa), 0.7 * mk_t + 0.3 * (hh + aa)),  # type: ignore[operator]
                            "_sim_p_home_win": (None, None)}
                    if sc.get("margin_mean") is not None:
                        arms["smart_sim_score_full_game"] = {"game": (_f(sc.get("margin_mean")), _f(sc.get("total_mean"))),
                                                             "_sim_p_home_win": (_f(sc.get("p_home_win")), None)}
                else:
                    drops["smart_sim_without_4_quarters"] += 1
            else:
                drops["no_pre_tip_smart_sim"] += 1
            pr = preds.get(key)
            if pr:
                a = {"game": (_f(pr.get("spread_margin")), _f(pr.get("totals"))),
                     "h1": (_f(pr.get("halves_h1_margin")), _f(pr.get("halves_h1_total")))}
                for i in range(1, 5):
                    a[f"q{i}"] = (_f(pr.get(f"quarters_q{i}_margin")), _f(pr.get(f"quarters_q{i}_total")))
                a["_sim_p_home_win"] = (_f(pr.get("home_win_prob")), None)
                arms["predictions_csv"] = a
            for arm, a in arms.items():
                for sk in ("game", "h1", "q1", "q2", "q3", "q4"):
                    m, t = a.get(sk, (None, None))
                    if m is None and t is None:
                        continue
                    hp, ap = seg[sk]
                    am_, at_ = hp - ap, hp + ap
                    # book lines for the segment
                    hb = hist.get(key) if sk == "game" else None
                    p_ml_hist = None
                    if hb and (hb.get("spread") or hb.get("total") or hb.get("p_home_ml") is not None):
                        hs = hb["spread"]["line"] if hb.get("spread") else None
                        hsp, asp = (hb["spread"]["price_a"], hb["spread"]["price_b"]) if hb.get("spread") else (None, None)
                        tot = hb["total"]["line"] if hb.get("total") else None
                        top, tup = (hb["total"]["price_a"], hb["total"]["price_b"]) if hb.get("total") else (None, None)
                        hml = aml = None
                        p_ml_hist = hb.get("p_home_ml")
                        drops["book_source_oddsapi_hist"] += 1 if arm == "smart_sim" else 0
                    elif sk == "game" and o:
                        drops["book_source_upstream_consensus"] += 1 if arm == "smart_sim" else 0
                        hs, tot = _f(o.get("home_spread")), _f(o.get("total"))
                        hsp, asp = _f(o.get("home_spread_price")), _f(o.get("away_spread_price"))
                        top, tup = _f(o.get("total_over_price")), _f(o.get("total_under_price"))
                        hml, aml = _f(o.get("home_ml")), _f(o.get("away_ml"))
                    elif sk != "game" and pl:
                        hs, tot = _f(pl.get(f"{sk}_spread")), _f(pl.get(f"{sk}_total"))
                        hsp, asp = _f(pl.get(f"{sk}_home_spread_price")), _f(pl.get(f"{sk}_away_spread_price"))
                        top = tup = hml = aml = None
                    else:
                        hs = tot = hsp = asp = top = tup = hml = aml = None
                    base = {"gid": gid, "date": d}
                    if m is not None:
                        rows[f"{arm}|{ph}|{sk}|margin"].append({**base, "y": am_, "model": m, "book": (-hs if hs is not None else None)})
                    if t is not None:
                        rows[f"{arm}|{ph}|{sk}|total"].append({**base, "y": at_, "model": t, "book": tot})
                    # probabilities (served transform: cards._margin_win_prob)
                    if m is not None and am_ != 0:
                        scale = 6.5 if sk == "game" else 3.4
                        p_book = (p_ml_hist if p_ml_hist is not None else _devig(hml, aml)) if sk == "game" else None
                        # with the multi-book ML only the de-vigged probability is kept, so ROI is at the FAIR price
                        # (1/p) -- optimistic by the vig; it is not used for any verdict
                        dec_h = _american_to_dec(hml) if p_ml_hist is None else (1 / p_ml_hist if p_ml_hist else None)
                        dec_a = _american_to_dec(aml) if p_ml_hist is None else (1 / (1 - p_ml_hist) if p_ml_hist and p_ml_hist < 1 else None)
                        rows[f"{arm}|{ph}|{sk}|win_prob"].append({**base, "yb": int(am_ > 0), "p_model": mwp(m, scale=scale),
                                                                    "p_sim": a["_sim_p_home_win"][0] if sk == "game" else None,
                                                                    "p_book": p_book, "p_half": 0.5,
                                                                    "dec_h": dec_h, "dec_a": dec_a})
                    # spread/total: the book price is used only when it is a plausible main-line pair
                    # (_std_pair); otherwise the book is the line itself at 50% and -110 both sides.
                    if sk == "game" and m is not None and hs is not None and (am_ + hs) != 0:
                        sp = _std_pair(hsp, asp)
                        drops["cover_price_reset_to_-110" if sp is None else "cover_price_used"] += 1 if arm == "smart_sim" else 0
                        sp = sp or (-110.0, -110.0)
                        rows[f"{arm}|{ph}|{sk}|cover"].append({**base, "yb": int(am_ + hs > 0), "p_model": mwp(m + hs, scale=7.5),
                                                                 "p_book": _devig(*sp), "p_half": 0.5,
                                                                 "dec_h": _american_to_dec(sp[0]), "dec_a": _american_to_dec(sp[1])})
                    if sk == "game" and t is not None and tot is not None and at_ != tot:
                        tp = _std_pair(top, tup)
                        drops["over_price_reset_to_-110" if tp is None else "over_price_used"] += 1 if arm == "smart_sim" else 0
                        tp = tp or (-110.0, -110.0)
                        rows[f"{arm}|{ph}|{sk}|over"].append({**base, "yb": int(at_ > tot), "p_model": mwp(t - tot, scale=10.5),
                                                                "p_book": _devig(*tp), "p_half": 0.5,
                                                                "dec_h": _american_to_dec(tp[0]), "dec_a": _american_to_dec(tp[1])})
    res: Dict = {"drops": dict(drops), "point": {}, "prob": {}}
    for k, rr in sorted(rows.items()):
        n = len(rr)
        if k.endswith("|margin") or k.endswith("|total"):
            bk = [r for r in rr if r["book"] is not None]
            d = _delta(bk, "model", "book", "abs")
            res["point"][k] = {"n": n, "games": len({r["gid"] for r in rr}), "mean_actual": round(sum(r["y"] for r in rr) / n, 3),
                               "model": _metrics(rr, "model"), "n_with_book": len(bk), "model_on_book_rows": _metrics(bk, "model"),
                               "book": _metrics(bk, "book"), "mae_delta_vs_book": d,
                               "verdict": _verdict(d, len(bk), args.min_n_games)}
        else:
            bk = [r for r in rr if r.get("p_book") is not None]
            d = _delta(bk, "p_model", "p_book", "brier")
            entry = {"n": n, "games": len({r["gid"] for r in rr}), "base_rate": round(sum(r["yb"] for r in rr) / n, 4),
                     "p_model": _prob_block(rr, "p_model"), "p_half": _prob_block(rr, "p_half"),
                     "n_with_book": len(bk), "p_model_on_book_rows": _prob_block(bk, "p_model"), "p_book": _prob_block(bk, "p_book"),
                     "brier_delta_model_vs_book": d, "brier_delta_model_vs_half": _delta(rr, "p_model", "p_half", "brier"),
                     "verdict": _verdict(d, len(bk), args.min_n_games)}
            if any(r.get("p_sim") is not None for r in rr):
                sim_rows = [r for r in bk if r.get("p_sim") is not None]
                entry["p_sim_own"] = _prob_block(sim_rows, "p_sim")
                entry["brier_delta_sim_own_vs_book"] = _delta(sim_rows, "p_sim", "p_book", "brier")
            entry["ev_bets"] = _game_ev(bk)
            res["prob"][k] = entry
    return res


def _game_ev(rr: List[Dict]) -> Dict:
    bets = []
    for r in rr:
        if r.get("dec_h") is None or r.get("dec_a") is None:
            continue
        ev_h = r["p_model"] * r["dec_h"] - 1
        ev_a = (1 - r["p_model"]) * r["dec_a"] - 1
        if max(ev_h, ev_a) <= 0:
            continue
        win = (r["yb"] == 1) if ev_h >= ev_a else (r["yb"] == 0)
        dec = r["dec_h"] if ev_h >= ev_a else r["dec_a"]
        bets.append((r["gid"], win, (dec - 1) if win else -1.0))
    if not bets:
        return {"n": 0}
    roi = _boot_ci([(g, p) for g, _, p in bets])
    return {"n": len(bets), "hit_rate": round(sum(w for _, w, _ in bets) / len(bets), 4),
            "roi": round(roi[0], 4), "roi_ci95": [round(roi[1], 4), round(roi[2], 4)]}


# ---------------------------------------------------------------------------
# 6. coverage and per-market evidence (no market-level switch)
# ---------------------------------------------------------------------------

def coverage(manifest: Dict, scoreboards: Dict[str, List[Dict]], logs: List[Dict], phase_of: Dict[str, str]) -> Dict:
    game_dates = {d for d, g in scoreboards.items() if any(x["completed"] for x in g)}
    log_dates = {r["date"] for r in logs}
    fam_dates = {f: {d for d, i in m.items() if i.get("commit_ts")} for f, m in manifest["families"].items()}
    fam_post = {f: {d for d, i in m.items() if not i.get("commit_ts")} for f, m in manifest["families"].items()}
    ss_dates = {k[:10] for k, i in manifest["smart_sim"].items() if i.get("commit_ts")}
    out: Dict = {}
    for ph in ("regular", "playoff"):
        gd = {d for d in game_dates if phase_of.get(d) == ph}
        fam = {f: len(v & gd) for f, v in fam_dates.items()}
        fam["smart_sim(dates)"] = len(ss_dates & gd)
        fam["smart_sim(games)"] = sum(1 for k, i in manifest["smart_sim"].items() if i.get("commit_ts") and k[:10] in gd)
        fam["player_logs"] = len(log_dates & gd)
        post = {f: len(v & gd) for f, v in fam_post.items()}
        out[ph] = {"game_dates": len(gd), "games": sum(sum(1 for x in scoreboards[d] if x["completed"]) for d in gd),
                   "pre_tip_dates_per_family": fam, "post_tip_only_dates_excluded": post,
                   "intersection_props_point(preds&logs)": len(fam_dates["props_predictions"] & log_dates & gd),
                   "intersection_props_book(preds&odds&logs)": len(fam_dates["props_predictions"] & fam_dates["props_odds"] & log_dates & gd),
                   "intersection_game_served(smart_sim&game_odds&finals)": len(ss_dates & fam_dates["game_odds"] & gd),
                   "intersection_game_vendor(predictions&game_odds&finals)": len(fam_dates["predictions"] & fam_dates["game_odds"] & gd),
                   "intersection_periods(smart_sim&period_lines&finals)": len(ss_dates & fam_dates["period_lines"] & gd),
                   "props_odds_dates": sorted(fam_dates["props_odds"] & gd)}
    return out


def evidence(report: Dict) -> Dict:
    """Per-market accuracy evidence: model vs the player's own average and vs the de-vigged book.
    It is NOT a switch. User directive (2026-10-02): "every line is its own decision. we should have a
    model that is accurate that then helps inform each decision" -- no market is withheld; these readings
    feed model fixes (see --diagnose) and per-line scoring."""
    out: Dict = {"props": {}, "games": {}}
    pts = report["props_point"]["markets"]
    book = report["props_book"]["by_market"]
    for mk in PROP_MARKETS:
        rows = []
        for ph in ("regular:smartsim", "playoff:smartsim", "regular:onnx"):
            p_ = pts.get(f"{ph}|{mk}", {})
            d = p_.get("mae_delta_vs_a", {})
            rows.append(f"point vs own avg ({ph}): {p_.get('verdict')} dMAE {d.get('point')} {d.get('ci95')} n={p_.get('n')}")
        b = book.get(f"all:smartsim|{mk}", {})
        for form, key in (("picks (blended)", "brier_delta_model_vs_book"), ("market board (raw Normal)", "brier_delta_raw_vs_book")):
            d = b.get(key) or {}
            v = _verdict(d, b.get("n", 0), report["min_n"]) if b else "NO_BOOK_ROWS"
            rows.append(f"{form} Brier vs book (smart-sim): {v} {d.get('point')} {d.get('ci95')} n={b.get('n', 0)} games={b.get('games', 0)}")
        out["props"][mk] = rows
    for part in ("prob", "point"):
        for k, v in report["games"][part].items():
            arm, ph, sk, mk = k.split("|")
            if ph != "regular" or arm not in ("smart_sim", "smart_sim_anchored_replay"):
                continue
            d = v.get("brier_delta_model_vs_book") if part == "prob" else v.get("mae_delta_vs_book")
            out["games"].setdefault(f"{sk}|{mk}", []).append(f"{arm} vs book: {v['verdict']} {d}")
    return out


# ---------------------------------------------------------------------------
# 6b. DIAGNOSE: why each market loses, and which model fix helps OUT OF SAMPLE.
#     User directive (2026-10-02): "every line is its own decision. we should have a model that is
#     accurate that then helps inform each decision" -- so no market is withheld; the backtest's job
#     is to make the model accurate. Every fix is FIT on smart-sim regular-season dates < --split and
#     SCORED on dates >= --split plus the playoffs (game-clustered CI).
# ---------------------------------------------------------------------------

SIM_STATS = ("pts", "reb", "ast", "threes", "stl", "blk", "tov", "pra")
# WNBA fixes (lanes wnba-prop-dispersion / wnba-sim-rate-shrink / wnba-prop-shape, all WNBA-only and on HOLD):
# their FITTED WNBA constants, tested here for transfer to NBA as-is and against an NBA re-fit.
WNBA_RATE_SHRINK_W = {"pts": 0.15, "reb": 0.15, "ast": 0.10, "threes": 0.35}           # wnba_sim_rate_shrink.json
WNBA_DISPERSION_K = {"pts": 1.25, "reb": 1.30, "ast": 1.20, "threes": 1.15, "pra": 1.40}  # re-fit on the #2+#3 stack
WNBA_SHAPE_D = {"reb": 1.189, "ast": 1.089, "threes": 1.131}                             # NB variance = D * mean


def _murphy(ps: List[float], ys: List[int], bins: int = 10) -> Dict:
    """Brier = REL - RES + UNC (equal-count bins). REL is fixable by a transform; RES is not."""
    n = len(ps)
    if not n:
        return {"n": 0}
    order = sorted(range(n), key=lambda i: ps[i])
    ob = sum(ys) / n
    rel = res = 0.0
    for b in range(bins):
        idx = order[b * n // bins:(b + 1) * n // bins]
        if not idx:
            continue
        pk = sum(ps[i] for i in idx) / len(idx)
        ok = sum(ys[i] for i in idx) / len(idx)
        rel += len(idx) * (pk - ok) ** 2
        res += len(idx) * (ok - ob) ** 2
    brier = sum((ps[i] - ys[i]) ** 2 for i in range(n)) / n
    return {"n": n, "brier": round(brier, 5), "rel": round(rel / n, 5), "res": round(res / n, 5), "unc": round(ob * (1 - ob), 5)}


def _nb_p_over(line: float, mean: float, var: float) -> float:
    """P(X > line) for a negative binomial with this mean/variance (Poisson if var <= mean)."""
    mean = max(mean, 1e-6)
    k = math.floor(line)
    if var <= mean * 1.0001:
        p, term = 0.0, math.exp(-mean)
        for x in range(0, k + 1):
            if x > 0:
                term *= mean / x
            p += term
        return max(0.0, min(1.0, 1 - p))
    r = mean * mean / (var - mean)
    q = r / (r + mean)
    term = q ** r
    cdf = term
    for x in range(1, k + 1):
        term *= (x - 1 + r) / x * (1 - q)
        cdf += term
    return max(0.0, min(1.0, 1 - cdf))


def _collect_sim_players(args, manifest: Dict, hist: History, phase_of: Dict[str, str]) -> Tuple[List[Dict], Counter]:
    """One row per (smart-sim game, player who played): model mean/sd/minutes per stat (straight from the
    pre-tip smart-sim JSON, the numbers production merges into props_predictions mean_/sd_), actuals,
    and the as-of baselines including as-of minutes."""
    rows, c = [], Counter()
    for key, info in sorted(manifest["smart_sim"].items()):
        if not info.get("commit_ts"):
            continue
        d = key[:10]
        p = args.out / "asof" / "smart_sim" / f"{key}.json"
        if not p.exists():
            continue
        sim = json.loads(p.read_text(encoding="utf-8"))
        players = sim.get("players")
        plist = (players.get("home", []) + players.get("away", [])) if isinstance(players, dict) else (players or [])
        if not plist or "min_mean" not in (plist[0] if isinstance(plist[0], dict) else {}):
            c["sim_without_player_minutes"] += 1
            continue
        for pl in plist:
            raw = int(_f(pl.get("player_id")) or 0)
            pid = hist.resolve(raw, str(pl.get("player_name") or ""), d, c) if raw else None
            proj_min = _f(pl.get("min_mean")) or 0.0
            if not pid:
                c["projected_min>=10_no_log(DNP or unmatched)" if proj_min >= 10 else "projected_min<10_no_log"] += 1
                continue
            act = hist.by_pd[(pid, d)]
            if act["min"] <= 0:
                c["log_but_0_min"] += 1
                continue
            prior = [r for r in hist.h.get(pid, []) if r["date"] < d]
            if not prior:
                c["no_prior_game"] += 1
                continue
            asof_min = sum(r["min"] for r in prior) / len(prior)
            l5 = prior[-5:]
            asof_min5 = sum(r["min"] for r in l5) / len(l5)
            base = {m: sum(r[m] for r in prior) / len(prior) for m in SIM_STATS}
            per_min = {m: sum(r[m] for r in prior) / max(1e-6, sum(r["min"] for r in prior)) for m in SIM_STATS}
            mean = {m: _f(pl.get(f"{m}_mean")) for m in SIM_STATS}
            sd = {m: _f(pl.get(f"{m}_sd")) for m in SIM_STATS}
            if any(v is None for v in mean.values()):
                c["missing_stat_mean"] += 1
                continue
            rows.append({"gid": act["gid"], "date": d, "phase": phase_of.get(d, "unknown"), "pid": pid,
                         "name": str(pl.get("player_name") or ""),
                         "proj_min": proj_min, "act_min": act["min"], "asof_min": asof_min, "asof_min5": asof_min5,
                         "mean": mean, "sd": sd, "act": {m: act[m] for m in SIM_STATS}, "base": base, "per_min": per_min,
                         "n_prior": len(prior)})
    c["rows"] = len(rows)
    return rows, c


def diagnose(args, manifest: Dict, hist: History, scoreboards: Dict[str, List[Dict]], phase_of: Dict[str, str]) -> Dict:
    rows, counts = _collect_sim_players(args, manifest, hist, phase_of)
    split = args.split
    train = [r for r in rows if r["phase"] == "regular" and r["date"] < split]
    test = [r for r in rows if (r["phase"] == "regular" and r["date"] >= split) or r["phase"] == "playoff"]
    out: Dict = {"split": split, "counts": dict(counts),
                 "train": {"rows": len(train), "games": len({r["gid"] for r in train}), "dates": len({r["date"] for r in train})},
                 "test": {"rows": len(test), "games": len({r["gid"] for r in test}), "dates": len({r["date"] for r in test}),
                          "playoff_rows": sum(r["phase"] == "playoff" for r in test)},
                 "minutes": {}, "props": {}}

    def mae_ci(rr: List[Dict], f_a, f_b) -> Dict:
        p, lo, hi = _boot_ci([(r["gid"], abs(f_a(r) - r["y"]) - abs(f_b(r) - r["y"])) for r in rr])
        return {"point": round(p, 4), "ci95": [round(lo, 4), round(hi, 4)]}

    # minutes: the sim's projected minutes vs actual, against the as-of average
    for name, rr in (("all", rows), ("test", test)):
        if not rr:
            continue
        n = len(rr)
        out["minutes"][name] = {
            "n": n, "bias_sim": round(sum(r["proj_min"] - r["act_min"] for r in rr) / n, 3),
            "mae_sim": round(sum(abs(r["proj_min"] - r["act_min"]) for r in rr) / n, 3),
            "mae_asof_avg": round(sum(abs(r["asof_min"] - r["act_min"]) for r in rr) / n, 3),
            "mae_asof_last5": round(sum(abs(r["asof_min5"] - r["act_min"]) for r in rr) / n, 3),
            "dmae_sim_vs_last5": mae_ci([{**r, "y": r["act_min"]} for r in rr], lambda r: r["proj_min"], lambda r: r["asof_min5"])}

    for m in SIM_STATS:
        for r in rows:
            r["y"] = r["act"][m]
        tr = [r for r in train if r["sd"][m]]
        te = [r for r in test if r["sd"][m]]
        if len(tr) < 200 or len(te) < 200:
            continue
        model = lambda r: r["mean"][m]  # noqa: E731
        base = lambda r: r["base"][m]  # noqa: E731
        # --- fits on TRAIN only ---
        res_tr = sorted(r["y"] - r["mean"][m] for r in tr)
        shift = res_tr[len(res_tr) // 2]
        xs = np.array([r["mean"][m] for r in tr]); ys = np.array([r["y"] for r in tr])
        b1, b0 = (np.polyfit(xs, ys, 1) if xs.std() > 0 else (1.0, 0.0))
        grid = [i / 20 for i in range(21)]
        w_blend = min(grid, key=lambda w: sum(abs(w * r["mean"][m] + (1 - w) * r["base"][m] - r["y"]) for r in tr))
        zs = [(r["y"] - r["mean"][m]) / r["sd"][m] for r in tr if r["sd"][m] > 0.05]
        # ROBUST width: IQR(z)/1.349 (= 1 for a correct Normal). Plain std(z) is dominated by rows whose
        # stored sd is near zero (deep-bench players) and over-widens everyone else.
        sd_scale = float((np.percentile(zs, 75) - np.percentile(zs, 25)) / 1.349) if zs else 1.0
        disp = sum((r["y"] - r["mean"][m]) ** 2 for r in tr) / max(1e-6, sum(r["mean"][m] for r in tr))  # var/mean
        fixes = {
            "bias_shift": lambda r: r["mean"][m] + shift,
            "linear_recal": lambda r: b0 + b1 * r["mean"][m],
            "blend_own_avg": lambda r: w_blend * r["mean"][m] + (1 - w_blend) * r["base"][m],
            "asof_minutes": lambda r: r["mean"][m] * (r["asof_min5"] / r["proj_min"]) if r["proj_min"] > 1 else r["mean"][m],
            "asof_rate_x_sim_min": lambda r: r["per_min"][m] * r["proj_min"],
        }
        # WNBA rate shrink: new_mean = min_mean * (r_own + w * (sim_rate - r_own)), pra moves by the summed delta
        def _rs(r, wmap):
            def one(s_):
                w = wmap.get(s_)
                if w is None or r["proj_min"] <= 1 or r["n_prior"] < 3:
                    return r["mean"][s_]
                return r["proj_min"] * (r["per_min"][s_] + w * (r["mean"][s_] / r["proj_min"] - r["per_min"][s_]))
            if m == "pra":
                return r["mean"]["pra"] + sum(one(s_) - r["mean"][s_] for s_ in ("pts", "reb", "ast"))
            return one(m)
        comps = ("pts", "reb", "ast") if m == "pra" else (m,)
        if all(c_ in WNBA_RATE_SHRINK_W for c_ in comps):
            fixes["rate_shrink_wnba_w"] = lambda r: _rs(r, WNBA_RATE_SHRINK_W)
        if m != "pra":
            w_rs = min(grid, key=lambda w: sum(abs(_rs(r, {m: w}) - r["y"]) for r in tr))
            fixes["rate_shrink_nba_fit"] = lambda r, w_rs=w_rs: _rs(r, {m: w_rs})
        n = len(te)
        res = {"train_n": len(tr), "test_n": n, "test_games": len({r["gid"] for r in te}),
               "fits": {"w_rate_shrink_nba": (w_rs if m != "pra" else None), "shift": round(shift, 3), "linear": [round(float(b0), 3), round(float(b1), 3)], "w_model_in_blend": w_blend,
                        "sd_scale(iqr z)": round(sd_scale, 3), "var_over_mean": round(disp, 3)},
               "test_bias_model": round(sum(model(r) - r["y"] for r in te) / n, 3),
               "test_mae_model": round(sum(abs(model(r) - r["y"]) for r in te) / n, 4),
               "test_mae_own_avg": round(sum(abs(base(r) - r["y"]) for r in te) / n, 4),
               "test_dmae_model_vs_own_avg": mae_ci(te, model, base),
               "oracle_actual_minutes": {  # diagnostic only (uses the result): error left if minutes were known
                   "mae": round(sum(abs(r["mean"][m] * r["act_min"] / r["proj_min"] - r["y"]) for r in te if r["proj_min"] > 1) / n, 4)},
               "fixes": {}}
        for fname, f in fixes.items():
            res["fixes"][fname] = {"test_mae": round(sum(abs(f(r) - r["y"]) for r in te) / n, 4),
                                   "dmae_vs_model": mae_ci(te, f, model), "dmae_vs_own_avg": mae_ci(te, f, base)}
        # --- width / shape at a book-like line: the player's as-of average rounded to x.5 ---
        pr = []
        for r in te:
            sd = r["sd"][m]
            if not sd or sd <= 0.05:
                continue
            L = math.floor(r["base"][m]) + 0.5
            y = int(r["y"] > L)
            mu = r["mean"][m]
            pr.append({"gid": r["gid"], "yb": y,
                       "p_normal": 1 - _ncdf((L - mu) / sd),
                       "p_normal_scaled": 1 - _ncdf((L - mu) / (sd * sd_scale)),
                       "p_nb": _nb_p_over(L, mu, max(mu * disp, (sd * sd_scale) ** 2)) if m != "pra" else None,
                       "p_base_normal": 1 - _ncdf((L - r["base"][m]) / (sd * sd_scale)),
                       "p_disp_wnba_k": (1 - _ncdf((L - mu) / (sd * WNBA_DISPERSION_K[m]))) if m in WNBA_DISPERSION_K else None,
                       "p_nb_wnba_D": _nb_p_over(L, mu, WNBA_SHAPE_D[m] * mu) if m in WNBA_SHAPE_D else None,
                       "p_blend_scaled": 1 - _ncdf((L - fixes["blend_own_avg"](r)) / (sd * sd_scale)),
                       "p_rateshrink_scaled": (1 - _ncdf((L - fixes["rate_shrink_nba_fit"](r)) / (sd * sd_scale)))
                       if "rate_shrink_nba_fit" in fixes else None})
        zt = [(r["y"] - r["mean"][m]) / r["sd"][m] for r in te if r["sd"][m] and r["sd"][m] > 0.05]
        sds = [r["sd"][m] for r in te if r["sd"][m]]
        res["width_test"] = {"std_z": round(float(np.std(zt)), 3), "iqr_z/1.349": round(float((np.percentile(zt, 75) - np.percentile(zt, 25)) / 1.349), 3),
                             "share_sd_below_0.5": round(sum(x < 0.5 for x in sds) / max(1, len(sds)), 3), "cover50": round(sum(abs(z) < 0.674 for z in zt) / len(zt), 3),
                             "cover80": round(sum(abs(z) < 1.2816 for z in zt) / len(zt), 3), "n": len(zt)}
        res["prob_at_asof_line"] = {k: {**_murphy([r[k] for r in pr if r[k] is not None], [r["yb"] for r in pr if r[k] is not None]),
                                        "logloss": round(sum(_logloss(r[k], r["yb"]) for r in pr if r[k] is not None) / max(1, sum(r[k] is not None for r in pr)), 5)}
                                    for k in ("p_normal", "p_normal_scaled", "p_nb", "p_disp_wnba_k", "p_nb_wnba_D", "p_base_normal", "p_blend_scaled", "p_rateshrink_scaled")}
        for k in ("p_normal_scaled", "p_nb", "p_disp_wnba_k", "p_nb_wnba_D", "p_blend_scaled"):
            q = [r for r in pr if r[k] is not None]
            if not q:
                continue
            p_, lo, hi = _boot_ci([(r["gid"], (r[k] - r["yb"]) ** 2 - (r["p_normal"] - r["yb"]) ** 2) for r in q])
            res["prob_at_asof_line"][k]["dbrier_vs_served_normal"] = {"point": round(p_, 5), "ci95": [round(lo, 5), round(hi, 5)]}
        for k in ("p_normal", "p_normal_scaled", "p_blend_scaled", "p_rateshrink_scaled"):  # vs the player's-own-average distribution
            q = [r for r in pr if r[k] is not None]
            if q:
                p_, lo, hi = _boot_ci([(r["gid"], (r[k] - r["yb"]) ** 2 - (r["p_base_normal"] - r["yb"]) ** 2) for r in q])
                res["prob_at_asof_line"][k]["dbrier_vs_own_avg_dist"] = {"point": round(p_, 5), "ci95": [round(lo, 5), round(hi, 5)]}
        out["props"][m] = res
    out["games"] = _diagnose_games(args, manifest, scoreboards, phase_of)
    return out


def _diagnose_games(args, manifest: Dict, scoreboards: Dict[str, List[Dict]], phase_of: Dict[str, str]) -> Dict:
    """Raw smart-sim (regulation quarter sums) vs the as-of consensus line: what model weight w in
    w*model + (1-w)*line minimises error (fit on train, scored on test)? The shipped anchor is w=0.05
    (margin) / 0.30 (total). Also a bias-corrected raw total and a refit win-probability scale."""
    from syndicate.features.nba.cards import _margin_win_prob as mwp
    g = []
    fam = manifest["families"]
    for d, games in sorted(scoreboards.items()):
        if not (fam["game_odds"].get(d) or {}).get("commit_ts"):
            continue
        odds = _game_odds_index(args.out / "asof" / "game_odds" / f"{d}.csv")
        for x in games:
            if not x["completed"] or x["home_pts"] is None:
                continue
            o = odds.get((x["home"], x["away"]))
            p = args.out / "asof" / "smart_sim" / f"{d}_{x['home']}_{x['away']}.json"
            if not o or not p.exists():
                continue
            qs = _sim_quarters(json.loads(p.read_text(encoding="utf-8")))
            if len(qs) != 4 or any(h is None or a is None for h, a in qs):
                continue
            hs, tot = _f(o.get("home_spread")), _f(o.get("total"))
            if hs is None or tot is None:
                continue
            hh, aa = sum(h for h, _ in qs), sum(a for _, a in qs)  # type: ignore[misc]
            g.append({"gid": f"{d}_{x['home']}_{x['away']}", "date": d, "phase": phase_of.get(d),
                      "m": hh - aa, "t": hh + aa, "lm": -hs, "lt": tot, "am": x["home_pts"] - x["away_pts"],
                      "at": x["home_pts"] + x["away_pts"], "p_book": _devig(_f(o.get("home_ml")), _f(o.get("away_ml")))})
    tr = [r for r in g if r["phase"] == "regular" and r["date"] < args.split]
    te = [r for r in g if (r["phase"] == "regular" and r["date"] >= args.split) or r["phase"] == "playoff"]
    out: Dict = {"train_games": len(tr), "test_games": len(te)}
    grid = [i / 20 for i in range(21)]
    for k, lk, ak, shipped in (("margin", "lm", "am", 0.05), ("total", "lt", "at", 0.30)):
        mk = "m" if k == "margin" else "t"
        w = min(grid, key=lambda w: sum(abs(w * r[mk] + (1 - w) * r[lk] - r[ak]) for r in tr))
        shift = float(np.median([r[ak] - r[mk] for r in tr])) if tr else 0.0
        wb = min(grid, key=lambda w: sum(abs(w * (r[mk] + shift) + (1 - w) * r[lk] - r[ak]) for r in tr))

        def ci(fa, fb):
            p, lo, hi = _boot_ci([(r["gid"], abs(fa(r) - r[ak]) - abs(fb(r) - r[ak])) for r in te])
            return {"point": round(p, 4), "ci95": [round(lo, 4), round(hi, 4)]}
        out[k] = {"raw_bias_train": round(float(np.mean([r[mk] - r[ak] for r in tr])), 3) if tr else None,
                  "raw_bias_test": round(float(np.mean([r[mk] - r[ak] for r in te])), 3) if te else None,
                  "w_fit": w, "w_fit_after_bias_shift": wb, "shift": round(shift, 3), "w_shipped": shipped,
                  "test_dmae_raw_vs_line": ci(lambda r: r[mk], lambda r: r[lk]),
                  "test_dmae_shipped_anchor_vs_line": ci(lambda r: shipped * r[mk] + (1 - shipped) * r[lk], lambda r: r[lk]),
                  "test_dmae_fit_w_vs_line": ci(lambda r: w * r[mk] + (1 - w) * r[lk], lambda r: r[lk]),
                  "test_dmae_shift_fit_w_vs_line": ci(lambda r: wb * (r[mk] + shift) + (1 - wb) * r[lk], lambda r: r[lk])}
    # win probability: refit the logistic scale on train (served 6.5) and decompose
    ml = [r for r in te if r["am"] != 0 and r["p_book"] is not None]
    scales = [s / 2 for s in range(6, 41)]
    sc = min(scales, key=lambda s: sum((mwp(r["m"], scale=s) - int(r["am"] > 0)) ** 2 for r in tr if r["am"] != 0)) if tr else 6.5
    out["win_prob"] = {"scale_served": 6.5, "scale_fit": sc,
                       "served": _murphy([mwp(r["m"], scale=6.5) for r in ml], [int(r["am"] > 0) for r in ml]),
                       "scale_refit": _murphy([mwp(r["m"], scale=sc) for r in ml], [int(r["am"] > 0) for r in ml]),
                       "book": _murphy([r["p_book"] for r in ml], [int(r["am"] > 0) for r in ml])}
    return out


# ---------------------------------------------------------------------------
# 7. report
# ---------------------------------------------------------------------------

def _row_point(k: str, v: Dict, base: str = "a") -> str:
    m = v["model"]
    if base == "a":
        a, b, d = v["base_a"], v["base_b"], v["mae_delta_vs_a"]
        return (f"| {k} | {v['n']} | {v['games']} | {v['mean_actual']} | {m['mean_pred']} | {m['bias']} | {m['mae']} | {a['mae']} | "
                f"{b.get('mae', '')} | {d['point']} [{d['ci95'][0]}, {d['ci95'][1]}] | {m['rmse']} | {a['rmse']} | {v['verdict']} |")
    bk, d = v["book"], v["mae_delta_vs_book"]
    mb = v["model_on_book_rows"]
    return (f"| {k} | {v['n']} | {v['n_with_book']} | {v['mean_actual']} | {m.get('mean_pred')} | {m.get('bias')} | {m.get('mae')} | "
            f"{mb.get('mae', '')} | {bk.get('mae', '')} | {d['point']} [{d['ci95'][0]}, {d['ci95'][1]}] | {v['verdict']} |")


def write_md(report: Dict, path: Path) -> None:
    L = ["# NBA game-line + player-prop backtest (as-of, 2025-26)", "",
         f"generated {report['generated_at']}; min_n props = {report['min_n']}, min_n games = {report['min_n_games']}; "
         f"regular-season scoring from {report['start']}", "",
         "## coverage (per family, pre-tip versions only, and the intersections each result rests on)", "",
         "```", json.dumps(report["coverage"], indent=1), "```", "",
         "## player props: point accuracy (model = production mean; a = own as-of avg, b = last-10)", "",
         f"drops: `{json.dumps(report['props_point']['drops'])}`; engine by date: `{json.dumps(report['props_point']['engine_by_date'])}`", "",
         "| phase\\|market | n | games | mean act | mean proj | bias | MAE model | MAE a | MAE b | dMAE vs a [95% CI] | RMSE model | RMSE a | verdict |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for k, v in report["props_point"]["markets"].items():
        L.append(_row_point(k, v))
    pb = report["props_book"]
    L += ["", "## player props vs the de-vigged book (production probability, recomputed by the production function)", "",
          f"filters: `{json.dumps(pb['filter_counts'])}`; parity model_prob_raw vs harness Normal: `{json.dumps(pb['parity_model_prob_raw'])}`; "
          f"rows {pb['n_rows']}, games {pb['games']}, dates {len(pb['dates'])}", "",
          "| phase\\|market | n | games | over rate | vig | Brier book | Brier model | Brier raw | Brier base | dBrier model-book [CI] | dBrier raw-book [CI] | LL book | LL model | EV bets n | hit | ROI [CI] | verdict |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for k, v in pb["by_market"].items():
        e, d, dr = v["ev_bets"], v["brier_delta_model_vs_book"], v["brier_delta_raw_vs_book"]
        L.append(f"| {k} | {v['n']} | {v['games']} | {v['base_rate_over']} | {v['mean_vig']} | {v['p_book'].get('brier')} | {v['p_model'].get('brier')} | "
                 f"{v['p_raw'].get('brier')} | {v['p_base'].get('brier')} | {d['point']} {d['ci95']} | {dr['point']} {dr['ci95']} | "
                 f"{v['p_book'].get('logloss')} | {v['p_model'].get('logloss')} | {e['n']} | {e.get('hit_rate', '')} | {e.get('roi', '')} {e.get('roi_ci95', '')} | {v['verdict']} |")
    g = report["games"]
    L += ["", "## game lines: point accuracy vs the captured consensus line (smart_sim = SERVED; predictions_csv = vendor model, NOT served)", "",
          f"drops: `{json.dumps(g['drops'])}`", "",
          "| arm\\|phase\\|segment\\|stat | n | n w/ book | mean act | mean proj | bias | MAE model | MAE model (book rows) | MAE book | dMAE model-book [CI] | verdict |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    for k, v in g["point"].items():
        L.append(_row_point(k, v, base="book"))
    L += ["", "## game lines: probability (served transform `cards._margin_win_prob`) vs the de-vigged consensus", "",
          "| arm\\|phase\\|segment\\|market | n | n w/ book | base rate | Brier model | Brier book | dBrier model-book [CI] | Brier 0.5 | sim own p Brier | EV bets n | hit | ROI [CI] | verdict |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for k, v in g["prob"].items():
        d, e = v["brier_delta_model_vs_book"], v["ev_bets"]
        L.append(f"| {k} | {v['n']} | {v['n_with_book']} | {v['base_rate']} | {v['p_model_on_book_rows'].get('brier')} | {v['p_book'].get('brier')} | "
                 f"{d['point']} {d['ci95']} | {v['p_half'].get('brier')} | {(v.get('p_sim_own') or {}).get('brier', '')} | {e['n']} | "
                 f"{e.get('hit_rate', '')} | {e.get('roi', '')} {e.get('roi_ci95', '')} | {v['verdict']} |")
    L += ["", "## per-market evidence (diagnosis, NOT a switch: every line is its own decision)", "", "```",
          json.dumps(report["evidence"], indent=1), "```", ""]
    path.write_text("\n".join(L), encoding="utf-8")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def _primary_repo() -> Path:
    try:
        common = _git(REPO, "rev-parse", "--path-format=absolute", "--git-common-dir").strip()
        return Path(common).parent
    except Exception:
        return REPO


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=Path(r"C:\tmp\nba_bt\out"))
    ap.add_argument("--upstream", type=Path, default=Path(r"C:\tmp\nba_bt\upstream"))
    ap.add_argument("--syndicate-repo", type=Path, default=_primary_repo())
    ap.add_argument("--start", default="2025-11-01", help="first scored date (as-of averages need prior games)")
    ap.add_argument("--min-n", type=int, default=200, help="min rows for any prop verdict")
    ap.add_argument("--min-n-games", type=int, default=100, help="min games for any game-line verdict")
    ap.add_argument("--analyze-only", action="store_true")
    ap.add_argument("--fetch-odds", action="store_true", help="OddsAPI historical backfill (dry run unless --execute)")
    ap.add_argument("--execute", action="store_true", help="actually spend credits")
    ap.add_argument("--max-credits", type=int, default=150000)
    ap.add_argument("--snap-min", type=int, default=45, help="snapshot this many minutes before tip")
    ap.add_argument("--diagnose", action="store_true", help="why each market loses + OOS model fixes (needs a collected --out)")
    ap.add_argument("--split", default="2026-03-01", help="diagnose: fit on smart-sim regular dates before this, test after + playoffs")
    ap.add_argument("--odds-dates", default="", help="comma list: restrict the backfill to these dates (pilot)")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    dates = _dates(RS_START, PO_END)
    scoreboards = fetch_scoreboards(args, dates)
    cutoffs = {d: min(_ts(g["start"]) for g in gs) for d, gs in scoreboards.items() if gs}
    phase_of = {}
    for d, gs in scoreboards.items():
        st = Counter(g["season_type"] for g in gs).most_common(1)[0][0]
        phase_of[d] = "regular" if st == 2 and d <= RS_END else ("playoff" if st == 3 else f"type{st}")
    if args.fetch_odds:
        sel = {x for x in args.odds_dates.split(",") if x}
        fetch_hist_odds(args, {d: g for d, g in scoreboards.items() if not sel or d in sel}, cutoffs)
        return 0
    man_path = args.out / "asof_manifest.json"
    if args.analyze_only and man_path.exists():
        manifest = json.loads(man_path.read_text(encoding="utf-8"))
    else:
        manifest = collect(args, cutoffs)
    manifest["cutoffs"] = cutoffs
    logs = fetch_player_logs(args)
    hist = History(logs)
    if args.diagnose:
        dg = diagnose(args, manifest, hist, scoreboards, phase_of)
        (args.out / "diagnose.json").write_text(json.dumps(dg, indent=1, default=str), encoding="utf-8")
        print(f"wrote {args.out / 'diagnose.json'}", flush=True)
        return 0
    report = {"generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "min_n": args.min_n,
              "min_n_games": args.min_n_games, "start": args.start,
              "substrate": {"artifacts": "git history (upstream mostgood1/NBA-Betting HEAD + Syndicate origin/main), pre-tip versions",
                            "actuals": "stats.nba.com playergamelogs + ESPN scoreboards, fetched live, cached under --out/cache"},
              "coverage": coverage(manifest, scoreboards, logs, phase_of)}
    report["props_point"] = score_props_point(args, manifest, hist, phase_of)
    report["props_book"] = score_props_book(args, manifest, hist, phase_of)
    report["games"] = score_games(args, manifest, scoreboards, phase_of)
    report["evidence"] = evidence(report)
    report["runtime_s"] = round(time.time() - t0, 1)
    (args.out / "report.json").write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    write_md(report, args.out / "report.md")
    print(f"wrote {args.out / 'report.md'} in {report['runtime_s']} s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
