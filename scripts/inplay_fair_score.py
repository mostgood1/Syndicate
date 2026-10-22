"""Score in-game FAIR prices against Kalshi's own in-play mid, at settlement.
Lane in-game-trading, stage 2 measurement (findings_2026-10-20 §3). Read-only.

Input: one night of scripts/inplay_recorder.py output (--dir), plus, for NBA,
the fleet's live re-sim ledger copied into <dir>/nba_live_gameline/
(`wsl -- cp .../nba_source/data/live_gameline_ledger/live_gameline_ledger_<date>.jsonl`;
the UNC path fails).

Output: <dir>/fair_rows.jsonl, one row per (game-state instant, Kalshi ticker),
read by scripts/inplay_scoreboard.py. A game-state instant is one ESPN poll
(60 s) of a game in play. Each row carries Kalshi's mid/asks at that instant,
its mid +60/+300 s later, the ticker's own settlement (Kalshi `result`), the
split tags (near/away from a score change, game phase) and every fair that
could price it:

  score_time   the cheap baseline, every sport (constants below, fixed BEFORE
               any scoring -- 2026-10-22, never fitted on recorded nights):
               * basketball/football: Brownian margin and total.
                   margin_final ~ N(d + mu*tau, SIG_M^2 * tau)
                   total_final  ~ N(S + T0*tau, SIG_T^2 * tau)
                 tau = regulation time remaining / regulation length;
                 mu = SIG_M * PhiInv(p0), p0 = Kalshi home GAME mid at the
                 pregame anchor; T0 = the strike where the pregame Kalshi TOTAL
                 ladder crosses 0.5 (linear interpolation).
                 This is the probit form of "logistic in score diff x time
                 remaining": one shape parameter per sport, no fit.
               * hockey: Poisson goals (a normal margin is wrong at 0-3 goals).
                 Regulation goals ~ Poisson(lam*tau) per team, lam_home + lam_away
                 = NHL_GOALS, home share solved so P(home wins, OT by share)
                 = p0. OT is sudden death by share; a shootout is 0.5. NHL
                 full-game totals are not scored (the fleet's Kalshi NHL store
                 carries period totals only).
               Pregame anchor: last Kalshi sample <= min(ESPN scheduled start,
               first ESPN "in" poll - 60 s) and within 45 min of it. A game
               with no anchor is NOT priced (reason counted, never defaulted).
  nba_resim    the NBA live re-sim's model_home_win_prob (h2h = P(home wins);
               totals/totals_alt = P(over line)), newest ledger row <= 120 s
               old. Spreads are not scored: the ledger's spread `line` sign
               convention is unverified (line 4.5 and 2.5 both near 0.5 on 10-20).
  books        the in-play sportsbook consensus (median no-vig over >= 3 fresh
               books, the exact line), as in scripts/inplay_edge_report.py.
               Already shown to LAG Kalshi (F1); kept as the reference row.

Only the HOME ticker of a GAME pair is scored (the away ticker is its
complement). Kalshi quote: newest active sample <= 20 s before the instant with
0 < bid <= ask < 1.
"""

from __future__ import annotations

import argparse
import bisect
import json
import math
import re
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from inplay_edge_report import book_fairs, series_multiplier, team_match  # noqa: E402

# ---- pre-registered baseline constants (2026-10-22; do not tune on scored nights) ----
# (regulation periods, minutes per period, SIG_M per full game, SIG_T per full game)
SPORT_CFG = {
    "nba": (4, 12.0, 13.0, 19.0),
    "nfl": (4, 15.0, 13.5, 13.5),
    "ncaaf": (4, 15.0, 16.0, 16.5),
    "nhl": (3, 20.0, None, None),
}
NHL_GOALS = 5.9  # regulation goals per game, both teams
PREFIX = (("KXNCAAF", "ncaaf"), ("KXNBA", "nba"), ("KXNHL", "nhl"), ("KXNFL", "nfl"))
KALSHI_MAX_AGE = 20.0
MARKOUT_MAX_AGE = 60.0
NEAR_SCORE_S = 180.0


def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def sport_of(family: str):
    return next((s for p, s in PREFIX if family.startswith(p)), None)


def kind_of(family: str):
    return next((k for k in ("GAME", "SPREAD", "TOTAL") if family.endswith(k)), None)


def phi(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def phi_inv(p):
    lo, hi = -8.0, 8.0
    for _ in range(80):
        mid = (lo + hi) / 2
        if phi(mid) < p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def clock_seconds(clock):
    s = str(clock or "0").strip()
    try:
        if ":" in s:
            m, sec = s.split(":", 1)
            return int(m) * 60 + float(sec)
        return float(s)
    except ValueError:
        return None


def time_remaining(sport, period, clock):
    """(tau = regulation fraction remaining, in_ot). None when unreadable."""
    n, mins, *_ = SPORT_CFG[sport]
    cs = clock_seconds(clock)
    if cs is None or not period:
        return None
    period = int(period)
    total = n * mins * 60
    if period > n:
        return cs / total, True
    return (cs + (n - period) * mins * 60) / total, False


# ---- Poisson (hockey) ----
def _pois(lam, kmax=20):
    out, p = [], math.exp(-lam)
    for k in range(kmax + 1):
        out.append(p)
        p *= lam / (k + 1)
    return out


def _diff_dist(lh, la):
    ph, pa = _pois(lh), _pois(la)
    dist = defaultdict(float)
    for i, x in enumerate(ph):
        for j, y in enumerate(pa):
            dist[i - j] += x * y
    return dist


def nhl_share(p0):
    """Home share h of NHL_GOALS so that P(home wins) = p0 (OT won by share)."""
    lo, hi = 0.02, 0.98
    for _ in range(50):
        h = (lo + hi) / 2
        dd = _diff_dist(h * NHL_GOALS, (1 - h) * NHL_GOALS)
        pw = sum(v for k, v in dd.items() if k > 0) + dd[0] * h
        if pw < p0:
            lo = h
        else:
            hi = h
    return (lo + hi) / 2


def nhl_prob(kind, h, diff, tau, in_ot, period, home_is_x, line):
    """P(YES) for an NHL GAME (home wins) or SPREAD (team X wins by over line)."""
    if in_ot:
        if kind == "GAME":
            return 0.5 if int(period) >= 5 else h  # 5 = shootout on ESPN
        return 0.0  # an OT/shootout win is by exactly one goal
    dd = _diff_dist(h * NHL_GOALS * tau, (1 - h) * NHL_GOALS * tau)
    if kind == "GAME":
        return sum(v for k, v in dd.items() if diff + k > 0) + sum(v for k, v in dd.items() if diff + k == 0) * h
    sign = 1 if home_is_x else -1
    return sum(v for k, v in dd.items() if sign * (diff + k) > line)


def brownian_prob(kind, sport, p0, t0, diff, total, tau, home_is_x, line):
    _, _, sig_m, sig_t = SPORT_CFG[sport]
    tau = max(tau, 1e-4)
    if kind == "TOTAL":
        if t0 is None:
            return None
        return 1 - phi((line - total - t0 * tau) / (sig_t * math.sqrt(tau)))
    mu = sig_m * phi_inv(min(0.98, max(0.02, p0)))
    m, s = diff + mu * tau, sig_m * math.sqrt(tau)
    if kind == "GAME":
        return 1 - phi(-m / s)
    return 1 - phi((line - m) / s) if home_is_x else phi((-line - m) / s)


def ladder_half(points):
    """Strike where P(over) crosses 0.5, by linear interpolation; None if not bracketed."""
    pts = sorted(points)
    for (s1, p1), (s2, p2) in zip(pts, pts[1:]):
        if p1 >= 0.5 >= p2 and p1 != p2:
            return s1 + (p1 - 0.5) * (s2 - s1) / (p1 - p2)
    return None


def load_jsonl(path):
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    ap.add_argument("--ledger", help="NBA live re-sim ledger (default: <dir>/nba_live_gameline/live_gameline_ledger_*.jsonl)")
    ap.add_argument("--out", help="default <dir>/fair_rows.jsonl")
    ap.add_argument("--max-book-age", type=float, default=90.0)
    ap.add_argument("--max-quote-age", type=float, default=120.0)
    ap.add_argument("--min-books", type=int, default=3)
    a = ap.parse_args()
    d = Path(a.dir)
    night = d.name.replace("inplay_", "")
    why = Counter()

    # ---------------- Kalshi ----------------
    quotes = defaultdict(list)  # ticker -> [(t, ya, yb, na, nb)] active, sane
    meta, result = {}, {}
    for r in load_jsonl(d / "kalshi.jsonl"):
        t = r["t"]
        if r.get("res") in ("yes", "no"):
            result[t] = 1.0 if r["res"] == "yes" else 0.0
        if r.get("st") != "active":
            continue
        ya, yb, na, nb = f(r.get("ya")), f(r.get("yb")), f(r.get("na")), f(r.get("nb"))
        if ya is None or yb is None or not (0 < yb <= ya < 1):
            continue
        quotes[t].append((ts(r["ts"]), ya, yb, na, nb))
        meta[t] = r
    for t in quotes:
        quotes[t].sort()
    qtimes = {t: [x[0] for x in v] for t, v in quotes.items()}

    def quote(t, when, max_age):
        i = bisect.bisect_right(qtimes.get(t, []), when) - 1
        if i < 0 or when - quotes[t][i][0] > max_age:
            return None
        return quotes[t][i]

    # Kalshi games: code -> {"family": {kind: fam}, "home_sub", "away_sub", "tickers": [...]}
    games = defaultdict(lambda: {"tickers": [], "subs": {}})
    for t, r in meta.items():
        fam = t.split("-")[0]
        if not sport_of(fam) or not kind_of(fam):
            continue
        code = t.split("-")[1]
        games[code]["sport"] = sport_of(fam)
        games[code]["tickers"].append(t)
        if kind_of(fam) == "GAME":
            team = t.split("-")[2]
            games[code]["subs"][team] = r.get("sub")
    for code, g in games.items():
        tail = code[7:]  # strip 26OCT20
        home = [team for team in g["subs"] if tail.endswith(team)]
        g["home_team_code"] = home[0] if len(home) == 1 else None

    def home_is_x(code, ticker):
        team = re.sub(r"\d+$", "", ticker.split("-")[2])
        return team == games[code]["home_team_code"]

    # ---------------- ESPN ----------------
    espn = defaultdict(list)  # (sport, id) -> rows
    for r in load_jsonl(d / "espn.jsonl"):
        espn[(r["sport"], str(r["id"]))].append(r)
    for k in espn:
        espn[k].sort(key=lambda r: r["ts"])

    def espn_match(code, g):
        tail = code[7:]
        subs = list(g["subs"].values())
        cands = []
        for k, rows in espn.items():
            if k[0] != g["sport"]:
                continue
            teams = rows[-1]["teams"]
            names = [x.get("name") for x in teams]
            if len(subs) == 2 and all(names) and all(any(team_match(s, n) for n in names) for s in subs):
                cands.append((2, k))
            elif all(x.get("abbr") and x["abbr"] in tail for x in teams):
                cands.append((1, k))
        if not cands:
            return None
        best = max(c[0] for c in cands)
        top = [c[1] for c in cands if c[0] == best]
        return top[0] if len(top) == 1 else None

    # ---------------- books ----------------
    books = defaultdict(list)
    if (d / "books.jsonl").exists():
        for r in load_jsonl(d / "books.jsonl"):
            books[r["sport"]].append((ts(r["ts"]), {e["id"]: e for e in r["events"]}))
    for s in books:
        books[s].sort(key=lambda x: x[0])
    btimes = {s: [x[0] for x in v] for s, v in books.items()}
    event_of = {}  # code -> oddsapi event id
    for code, g in games.items():
        subs = [s for s in g["subs"].values() if s]
        for _, evs in books.get(g["sport"], []):
            for eid, e in evs.items():
                names = (e.get("home_team"), e.get("away_team"))
                if len(subs) == 2 and all(any(team_match(s, n) for n in names) for s in subs):
                    event_of[code] = eid
            if code in event_of:
                break

    def book_p(code, ticker, when):
        s = games[code]["sport"]
        eid = event_of.get(code)
        i = bisect.bisect_right(btimes.get(s, []), when) - 1
        if eid is None or i < 0 or when - books[s][i][0] > a.max_book_age:
            return None
        bt, evs = books[s][i]
        e = evs.get(eid)
        if e is None:
            return None
        fairs = book_fairs(e, bt, a.max_quote_age)
        r = meta[ticker]
        sub, fs, kind = r.get("sub") or "", f(r.get("fs")), kind_of(ticker.split("-")[0])
        if kind == "GAME":
            key = next((k for k in fairs if k[0] == "h2h" and team_match(sub, k[1])), None)
        elif kind == "SPREAD":
            team = sub.split(" wins by")[0]
            key = next((k for k in fairs if k[0] == "spreads" and team_match(team, k[1]) and k[2] is not None and abs(k[2] + fs) < 1e-6), None)
        else:
            key = next((k for k in fairs if k[0] == "totals" and k[1] == "Over" and k[2] is not None and abs(k[2] - fs) < 1e-6), None)
        bk = fairs.get(key) if key else None
        return statistics.median(bk.values()) if bk and len(bk) >= a.min_books else None

    # ---------------- NBA re-sim ledger ----------------
    resim = defaultdict(list)  # (home_team, market_kind, line) -> [(t, p)]
    ledgers = [Path(a.ledger)] if a.ledger else sorted((d / "nba_live_gameline").glob("live_gameline_ledger_*.jsonl"))
    for lp in ledgers:
        if not lp.exists():
            continue
        txt = lp.read_text(encoding="utf-8")
        for x in txt.replace("}{", "}\n{").splitlines():
            if not x.strip():
                continue
            r = json.loads(x)
            if r.get("segment") != "full" or r.get("model_home_win_prob") is None or r.get("game_state") not in (None, "live"):
                continue
            mk = {"h2h": "GAME", "totals": "TOTAL", "totals_alt": "TOTAL"}.get(r.get("market"))
            if not mk:
                continue
            line = None if mk == "GAME" else f(r.get("line"))
            resim[(r["home_team"], mk, line)].append((ts(r["recorded_at"]), float(r["model_home_win_prob"])))
    for k in resim:
        resim[k].sort()
    resim_homes = {k[0] for k in resim}

    def resim_p(code, ticker, when):
        g = games[code]
        hsub = g["subs"].get(g["home_team_code"])
        home = next((h for h in resim_homes if hsub and team_match(hsub, h)), None)
        if home is None:
            return None
        kind = kind_of(ticker.split("-")[0])
        line = None if kind == "GAME" else f(meta[ticker].get("fs"))
        xs = resim.get((home, kind, line)) or []
        i = bisect.bisect_right([x[0] for x in xs], when) - 1
        return xs[i][1] if i >= 0 and when - xs[i][0] <= 120 else None

    fee_cache: dict = {}
    out_path = Path(a.out) if a.out else d / "fair_rows.jsonl"
    n_rows, cover = 0, Counter()
    with open(out_path, "w", encoding="utf-8") as out:
        for code, g in sorted(games.items()):
            sport = g["sport"]
            if not g.get("home_team_code"):
                why[f"{sport}:no_home_team_code"] += 1
                continue
            ek = espn_match(code, g)
            if ek is None:
                why[f"{sport}:no_espn_match"] += 1
                continue
            rows = espn[ek]
            ins = [r for r in rows if r.get("state") == "in"]
            if not ins:
                why[f"{sport}:never_in_play"] += 1
                continue
            hab = next(x["abbr"] for x in rows[-1]["teams"] if x["ha"] == "home")
            t_in = ts(ins[0]["ts"])
            anchor_t = t_in - 60
            if rows[0].get("start"):
                anchor_t = min(anchor_t, ts(rows[0]["start"]))
            home_game = next((t for t in g["tickers"] if kind_of(t.split("-")[0]) == "GAME" and t.endswith("-" + g["home_team_code"])), None)
            q0 = quote(home_game, anchor_t, 45 * 60) if home_game else None
            p0 = None if q0 is None else (q0[1] + q0[2]) / 2
            t0 = None
            if p0 is not None and sport != "nhl":
                lad = []
                for t in g["tickers"]:
                    if kind_of(t.split("-")[0]) == "TOTAL":
                        q = quote(t, anchor_t, 45 * 60)
                        if q and f(meta[t].get("fs")) is not None:
                            lad.append((f(meta[t]["fs"]), (q[1] + q[2]) / 2))
                t0 = ladder_half(lad)
            if p0 is None:
                why[f"{sport}:no_pregame_anchor"] += 1
            share = nhl_share(p0) if (p0 is not None and sport == "nhl") else None
            # score-change times (first poll showing a new score)
            changes, last = [], None
            for r in rows:
                sc = tuple(x.get("score") for x in r["teams"])
                if last is not None and sc != last:
                    changes.append(ts(r["ts"]))
                last = sc
            for r in ins:
                when = ts(r["ts"])
                tr = time_remaining(sport, r.get("period"), r.get("clock"))
                if tr is None:
                    why[f"{sport}:clock_unreadable"] += 1
                    continue
                tau, in_ot = tr
                hs = next(int(x["score"] or 0) for x in r["teams"] if x["ha"] == "home")
                as_ = next(int(x["score"] or 0) for x in r["teams"] if x["ha"] == "away")
                diff, total = hs - as_, hs + as_
                prior = [c for c in changes if c <= when]
                since = (when - prior[-1]) if prior else None
                phase = "ot" if in_ot else ("early" if tau > 2 / 3 else ("mid" if tau > 1 / 3 else "late"))
                for t in g["tickers"]:
                    fam = t.split("-")[0]
                    kind = kind_of(fam)
                    if kind == "GAME" and t != home_game:
                        continue
                    if t not in result:
                        cover["unsettled"] += 1
                        continue
                    q = quote(t, when, KALSHI_MAX_AGE)
                    if q is None:
                        cover["no_fresh_kalshi"] += 1
                        continue
                    line = f(meta[t].get("fs"))
                    hx = home_is_x(code, t)
                    fairs = {}
                    if p0 is not None:
                        if sport == "nhl":
                            if kind != "TOTAL":
                                fairs["score_time"] = nhl_prob(kind, share, diff, tau, in_ot, r.get("period"), hx, line)
                        else:
                            p = brownian_prob(kind, sport, p0, t0, diff, total, tau, hx, line)
                            if p is not None:
                                fairs["score_time"] = p
                            else:
                                cover["score_time:no_total_anchor"] += 1
                    if sport == "nba":
                        p = resim_p(code, t, when)
                        if p is not None:
                            fairs["nba_resim"] = p
                    p = book_p(code, t, when)
                    if p is not None:
                        fairs["books"] = p
                    later = {}
                    for h in (60, 300):
                        lq = quote(t, when + h, MARKOUT_MAX_AGE)
                        later[h] = None if lq is None else round((lq[1] + lq[2]) / 2, 4)
                    mult = series_multiplier(fam, fee_cache)
                    row = {"night": night, "sport": sport, "kind": kind, "game": code, "t": round(when, 1),
                           "ticker": t, "line": line, "phase": phase,
                           "since_score": None if since is None else round(since, 1),
                           "near": since is not None and since <= NEAR_SCORE_S,
                           "y": result[t], "mid": round((q[1] + q[2]) / 2, 4), "ya": q[1], "na": q[3],
                           "m60": later[60], "m300": later[300], "fee_mult": mult,
                           "fairs": {k: round(v, 5) for k, v in fairs.items()}}
                    out.write(json.dumps(row, separators=(",", ":")) + "\n")
                    n_rows += 1
                    for k in fairs:
                        cover[f"{sport}:{kind}:{k}"] += 1
                    cover[f"{sport}:{kind}:rows"] += 1
    print(f"NIGHT {night}: {n_rows} rows -> {out_path}")
    print(f"  games: {len(games)} Kalshi codes; skipped {dict(why)}")
    print("  coverage (rows per fair; rows = home GAME + every SPREAD/TOTAL rung with a fresh quote and a settlement):")
    for k, v in sorted(cover.items()):
        print(f"    {k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
