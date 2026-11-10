"""Per sport and market (totals, spreads, h2h), per QUOTE-AGE bin: Brier model vs market and realised edge, split by
whether the GAME STATE was frozen (state older than 120 s at the build: halftime, timeouts, reviews) or moving.
READ-ONLY. Todo #780; findings .syndicate/findings_2026-11-10_live_totals_grade.md (the quote-age section).

Ledger conventions this relies on (checked on rows, 2026-11-10): `model_home_win_prob` is P(over) on totals,
P(home margin > line) on spreads (the `line` is a threshold on the HOME margin, so the home spread is -line),
P(home wins) on h2h. Run on the fleet host, like live_totals_grade.py:
    wsl -d Ubuntu-24.04 -- env MARKETS=totals,spreads,h2h nice -n 19 python3 /mnt/c/<repo>/scripts/live_gameline_age_grade.py </dev/null
"""
import glob
import json
import os
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta

sys.argv = [sys.argv[0], os.environ.get("ESPN_CACHE", "/mnt/c/tmp/livegrade/espn")]
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import live_totals_grade as g  # noqa: E402

BINS = ((0, 30), (30, 60), (60, 90), (90, 120), (120, 180), (180, 300), (300, 601))
MARKETS = os.environ.get("MARKETS", "totals").split(",")


def ts(v):
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return d
    except Exception:
        return None


def finals_detail(sport, d):
    path, groups = g.ESPN[sport]
    out = {}
    for gr in groups:
        data = g.fetch(f"https://site.api.espn.com/apis/site/v2/sports/{path}/scoreboard?dates={d.strftime('%Y%m%d')}&limit=500" + (f"&groups={gr}" if gr else ""),
                       os.path.join(g.CACHE, sport, f"{d:%Y%m%d}_{gr}.json")) or {}
        for ev in data.get("events") or []:
            comp = (ev.get("competitions") or [{}])[0]
            if not ((comp.get("status") or ev.get("status") or {}).get("type") or {}).get("completed"):
                continue
            teams = {c.get("homeAway"): c for c in comp.get("competitors") or []}
            if "home" not in teams or "away" not in teams:
                continue
            try:
                hs, as_ = float(teams["home"]["score"]), float(teams["away"]["score"])
            except Exception:
                continue
            names = []
            for side in ("home", "away"):
                t = teams[side].get("team") or {}
                names.append({g.norm(t.get(k)) for k in ("displayName", "shortDisplayName", "location", "name") if t.get(k)}
                             | {g.norm(f"{t.get('location','')}{t.get('name','')}")})
            out[ev.get("id")] = (names[0], names[1], (hs, as_))
    return out


def ledger_home_margin(r, idx_entry):
    """Final margin in the LEDGER's home orientation, or None when the orientation is ambiguous."""
    hn, an, (hs, as_) = idx_entry
    straight = g.side_hit(r.get("home_team"), hn) and g.side_hit(r.get("away_team"), an)
    flipped = g.side_hit(r.get("home_team"), an) and g.side_hit(r.get("away_team"), hn)
    if straight and not flipped:
        return hs - as_
    if flipped and not straight:
        return as_ - hs
    return None


for sport in os.environ.get("SPORTS", "ncaab,wncaab,nba,ncaaf").split(","):
    for market in MARKETS:
        states = {}
        for f in sorted(glob.glob(f"{g.DATA}/{sport}_source/data/live_gameline_ledger/live_gameline_ledger_*.jsonl")):
            for line in open(f):
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                if r.get("market") != market or r.get("segment") != "full" or not r.get("priceable"):
                    continue
                if r.get("model_home_win_prob") is None or r.get("market_fair_prob") is None:
                    continue
                if market != "h2h" and r.get("line") is None:
                    continue
                states.setdefault((r.get("event_id"), r.get("live_state_as_of"), r.get("line")), r)
        if not states:
            continue
        idx = {}
        for ds in sorted({r["date"] for r in states.values()}):
            d0 = date.fromisoformat(ds)
            i = {}
            for d in (d0, d0 + timedelta(days=1)):
                i.update(finals_detail(sport, d))
            idx[ds] = i
        fin = {}
        dirchk = [0, 0]
        cells = defaultdict(list)
        total_rows = 0
        for (eid, _, ln), r in states.items():
            if eid not in fin:
                h = g.match(idx[r["date"]], r.get("home_team"), r.get("away_team"))
                if h:
                    e = idx[r["date"]][h]
                    fin[eid] = (e[2][0] + e[2][1], ledger_home_margin(r, e))
                else:
                    fin[eid] = None
            if fin[eid] is None:
                continue
            F, M = fin[eid]
            try:
                if float(r["home_score"]) + float(r["away_score"]) > F:
                    continue
            except Exception:
                pass
            if market == "totals":
                ln = float(ln)
                if F == ln:
                    continue
                y = 1.0 if F > ln else 0.0
            elif market == "spreads":
                if M is None:
                    continue
                ln = float(ln)
                if M - ln == 0:
                    continue
                y = 1.0 if M - ln > 0 else 0.0
                mm = r.get("model_margin_mean")
                if mm is not None:
                    dirchk[0] += 1
                    dirchk[1] += (float(r["model_home_win_prob"]) > 0.5) == (float(mm) - ln > 0)
            else:
                if M is None or M == 0:
                    continue
                y = 1.0 if M > 0 else 0.0
            pm, pf = float(r["model_home_win_prob"]), float(r["market_fair_prob"])
            qa = r.get("quote_age_seconds")
            rec, st_ = ts(r.get("recorded_at")), ts(r.get("live_state_as_of"))
            if qa is None or rec is None or st_ is None:
                continue
            sa = (rec - st_).total_seconds()
            over = pm > pf
            win = y if over else 1 - y
            psf = pf if over else 1 - pf
            frozen = "frozen" if sa > 120 else "moving"
            for lo, hi in BINS:
                if lo <= float(qa) < hi:
                    cells[(frozen, lo, hi)].append((eid, (pm - y) ** 2 - (pf - y) ** 2, win - psf, (pf - y) ** 2, (pm - y) ** 2))
                    total_rows += 1
                    break
        print(f"\n## {sport} {market}: {total_rows} graded states")
        print("   state   quote age   states games  share  Brier mkt  Brier model  model-mkt (95%)     realised edge (95%)")
        for frozen in ("moving", "frozen"):
            for lo, hi in BINS:
                c = cells.get((frozen, lo, hi)) or []
                if not c:
                    continue
                bd = g.cl_mean([(e, d) for e, d, *_ in c])
                re_ = g.cl_mean([(e, w) for e, _, w, *_ in c])
                print(f"   {frozen:<7} {lo:>4}-{hi - 1 if hi > 600 else hi:<4}s {len(c):>7} {len({x[0] for x in c}):>5}  {len(c) / total_rows:>5.1%}"
                      f"  {sum(x[3] for x in c) / len(c):>9.4f}  {sum(x[4] for x in c) / len(c):>11.4f}  {g.fmt(bd[0], bd[1]):>17}  {g.fmt(re_[0], re_[1]):>20}")
