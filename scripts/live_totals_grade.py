"""Grade PRICED live full-game totals rows on the fleet's live gameline ledgers against ESPN finals. READ-ONLY.

Todo #780 (2026-11-10, user "Yes, grade them"). Findings: .syndicate/findings_2026-11-10_live_totals_grade.md

Unit: one distinct re-sim state (event_id, live_state_as_of, line); repeated board builds of the same state collapse.
Model side: over if model P(over) > market fair P(over), else under. y = 1 if final total > line (pushes dropped).
Splits: |edge|, the quote's age at the build (`quote_age_seconds`), and progress (score so far / line). One bet per
game = the game's FIRST state passing a rule, the decision-level view. Engine read: model-mean and line errors against
the final, and the model's implied sd ((mean - line) / z(P over)) against its actual error sd.
SEs are game-clustered. Pushes, unmatched games and states whose score exceeds the final are dropped and counted.

Run ON THE FLEET HOST (WSL; it reads ~/syndicate-prod/data directly), at nice 19:
    wsl -d Ubuntu-24.04 -- nice -n 19 python3 /mnt/c/<repo>/scripts/live_totals_grade.py /mnt/c/tmp/livegrade/espn </dev/null
    SPORTS=ncaab,nba  (env) limits the sports; default ncaab,wncaab,nba,ncaaf (NFL had 0 priced rows on 11-10).

PRE-REGISTERED CELL (lane ncaab-live-edge20-prereg; .syndicate/findings_2026-11-13_ncaab_edge20_prereg.md):
    PREREG_780=count  prints ONLY how many games qualify so far, per ledger date. No hit, edge or Brier is printed.
    PREREG_780=grade  the ONE registered grade. Run it once, when the count reaches PREREG_N (or at the deadline).
    The cell: NCAAB priced full-game totals on ledger dates >= PREREG_FROM; each game's FIRST state with
    |model - market fair| >= 20 pp and quote age <= 30 s; bet the model's side; the first PREREG_N such games in
    time order. PREREG_DATE_FROM / PREREG_DATE_TO override the window for the code check on the ALREADY-SEEN
    11-02..11-09 dates only; the output then says it is not the registered window.
"""
import glob
import json
import math
import os
import re
import sys
import time
import urllib.request
from collections import defaultdict
from datetime import date, timedelta
from statistics import NormalDist, mean as _mean, median as _median, pstdev as _pstdev

CACHE = sys.argv[1] if len(sys.argv) > 1 else "/tmp/livegrade_espn"
DATA = os.path.expanduser("~/syndicate-prod/data")
ESPN = {
    "ncaab": ("basketball/mens-college-basketball", ("50",)),
    "wncaab": ("basketball/womens-college-basketball", ("50",)),
    "nba": ("basketball/nba", (None,)),
    "ncaaf": ("football/college-football", ("80", "81")),
    "nfl": ("football/nfl", (None,)),
}
UA = {"User-Agent": "Mozilla/5.0 (research script)"}

# The pre-registered cell (registered 2026-11-13, before any outcome on these dates was read). Do not edit these
# after the registration commit; a changed rule is a new registration with a new name.
PREREG_MODE = (os.environ.get("PREREG_780") or "").strip().lower()
PREREG_SPORT = "ncaab"
# 2026-11-13, not 11-10: a default-mode run of this script before 14:38Z 11-13 printed the cell over ledger dates
# 11-02..11-12 (151 games), so ~17 games from 11-10..11-12 were seen in aggregate before the registration.
PREREG_FROM = "2026-11-13"
PREREG_N = 200
PREREG_N_EXTENDED = 400
PREREG_EDGE_PP = 20.0
PREREG_MAX_QUOTE_AGE_S = 30.0
PREREG_BREAK_EVEN = 110.0 / 210.0  # -110
PREREG_Z = 1.645  # one-sided 95%
PREREG_DEADLINE = "2026-12-15"
PREREG_MIN_N_AT_DEADLINE = 100


def model_prob(r):
    """The model P(over) a grade reads. PREREG_780 reads the ENGINE'S OWN number (`model_home_win_prob_unscaled`,
    ledger v7) whenever the join tempered it (`#780` totals prob scale): the registered cell was found on untempered
    probabilities, and a later scale must not change which games it selects (amendment 1, 2026-11-13, made before any
    game in the window existed). NCAAB's scale is 1 at registration, so this reads `model_home_win_prob` there today.
    The default mode reads the SERVED (tempered) number."""
    if PREREG_MODE and r.get("model_home_win_prob_unscaled") is not None:
        return r.get("model_home_win_prob_unscaled")
    return r.get("model_home_win_prob")


def prereg_window():
    lo = os.environ.get("PREREG_DATE_FROM") or PREREG_FROM
    hi = os.environ.get("PREREG_DATE_TO") or "9999-12-31"
    return lo, hi, (lo, hi) != (PREREG_FROM, "9999-12-31")


def _utc_key(t):
    s = str(t or "").strip().replace("Z", "+00:00")
    try:
        from datetime import datetime, timezone
        d = datetime.fromisoformat(s)
        return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).timestamp()
    except ValueError:
        return float("inf")


def prereg_first_states(rows):
    """Each game's first qualifying state, games in time order (the registered sample order)."""
    first = {}
    for x in sorted(rows, key=lambda x: _utc_key(x["t"])):
        if x["g"] in first:
            continue
        if x["edge"] >= PREREG_EDGE_PP and x["qa"] is not None and x["qa"] <= PREREG_MAX_QUOTE_AGE_S:
            first[x["g"]] = x
    return sorted(first.values(), key=lambda x: _utc_key(x["t"]))


def prereg_verdict(fb):
    n = len(fb)
    hit = sum(x["win"] for x in fb) / n
    lb = hit - PREREG_Z * math.sqrt(hit * (1 - hit) / n)
    if lb > PREREG_BREAK_EVEN:
        v = "PASS"
    elif hit <= PREREG_BREAK_EVEN:
        v = "KILL"
    else:
        v = "INCONCLUSIVE"
    return hit, lb, v


def prereg(rows, mode):
    lo, hi, overridden = prereg_window()
    fb = prereg_first_states(rows)
    if overridden:
        print(f"  ** window {lo}..{hi} is NOT the registered window ({PREREG_FROM}..); a code check only **")
    by_date = defaultdict(int)
    for x in fb:
        by_date[x["date"]] += 1
    print(f"  PREREG_780 cell: {len(fb)} qualifying games on ledger dates {lo}..{hi if hi < '9999' else ''} "
          f"(registered sample: the first {PREREG_N}); per date {dict(sorted(by_date.items()))}")
    if mode != "grade":
        return
    if len(fb) < PREREG_N and not overridden:
        print(f"  not graded: {len(fb)} < {PREREG_N}. Grade at the deadline {PREREG_DEADLINE} only if >= "
              f"{PREREG_MIN_N_AT_DEADLINE}.")
        return
    if not fb:
        return
    for step, n_cap in enumerate((PREREG_N, PREREG_N_EXTENDED)):
        if step == 1 and len(fb) < PREREG_N_EXTENDED:
            print(f"  extension pending: {len(fb)} of {PREREG_N_EXTENDED} games; grade the extension once at "
                  f"{PREREG_N_EXTENDED}.")
            break
        s = fb[:n_cap]
        hit, lb, v = prereg_verdict(s)
        re_ = cl_mean([(x["g"], x["win"] - x["psf"]) for x in s])
        print(f"  FIRST {len(s)} GAMES ({s[0]['date']}..{s[-1]['date']}): hit {hit:.3f}, one-sided 95% lower bound "
              f"{lb:.3f} vs break-even {PREREG_BREAK_EVEN:.3f} -> {v}; market fair {sum(x['psf'] for x in s) / len(s):.3f}, "
              f"model claimed {sum(x['psm'] for x in s) / len(s):.3f}, realised edge {fmt(re_[0], re_[1])}, "
              f"ROI at -110 {hit * (1 + 100 / 110) - 1:+.3f}; over {sum(x['over'] for x in s)} / under "
              f"{sum(not x['over'] for x in s)}")
        if v != "INCONCLUSIVE":
            break
        if step == 0:
            print(f"  INCONCLUSIVE at {len(s)}: the registration extends ONCE to the first {PREREG_N_EXTENDED} games.")
        else:
            print(f"  INCONCLUSIVE at {len(s)} counts as KILL (registered).")


def norm(s):
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def final_cutoff(d):
    """Epoch after which ESPN date d's games are all over: noon UTC the next day. A scoreboard cached before it may
    hold games that were not final yet, and trusting it forever drops them as unmatched (measured 2026-11-13: the
    11-10 / 11-11 NCAAB files were cached 11-10 ~17:00 CST, so 16,631 states of the width fit had no final)."""
    from datetime import datetime, timezone
    return datetime(d.year, d.month, d.day, 12, tzinfo=timezone.utc).timestamp() + 86400


def fetch(url, path, fresh_after=None):
    """A cached file is reused only when it was written at or after `fresh_after` (epoch; None = always)."""
    if os.path.exists(path) and (fresh_after is None or os.path.getmtime(path) >= fresh_after):
        try:
            return json.load(open(path))
        except Exception:
            pass
    for _ in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
                data = json.loads(r.read().decode("utf-8"))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            json.dump(data, open(path, "w"))
            time.sleep(0.4)
            return data
        except Exception:
            time.sleep(2)
    return None


def finals(sport, d):
    """{espn_event_id: (names_home, names_away, final_total)} for completed games on ESPN date d."""
    path, groups = ESPN[sport]
    out = {}
    for g in groups:
        q = f"dates={d.strftime('%Y%m%d')}&limit=500" + (f"&groups={g}" if g else "")
        data = fetch(f"https://site.api.espn.com/apis/site/v2/sports/{path}/scoreboard?{q}",
                     os.path.join(CACHE, sport, f"{d:%Y%m%d}_{g}.json"), fresh_after=final_cutoff(d)) or {}
        for ev in data.get("events") or []:
            comp = (ev.get("competitions") or [{}])[0]
            if not ((comp.get("status") or ev.get("status") or {}).get("type") or {}).get("completed"):
                continue
            teams = {c.get("homeAway"): c for c in comp.get("competitors") or []}
            if "home" not in teams or "away" not in teams:
                continue
            try:
                total = float(teams["home"]["score"]) + float(teams["away"]["score"])
            except Exception:
                continue
            names = []
            for side in ("home", "away"):
                t = teams[side].get("team") or {}
                names.append({norm(t.get(k)) for k in ("displayName", "shortDisplayName", "location", "name") if t.get(k)}
                             | {norm(f"{t.get('location','')}{t.get('name','')}")})
            out[ev.get("id")] = (names[0], names[1], total)
    return out


def side_hit(name, names):
    n = norm(name)
    return any(x and (n == x or (len(x) >= 6 and (n.startswith(x) or x.startswith(n)))) for x in names)


def match(index, home, away):
    hits = [eid for eid, (hn, an, _) in index.items()
            if (side_hit(home, hn) and side_hit(away, an)) or (side_hit(home, an) and side_hit(away, hn))]
    return hits[0] if len(hits) == 1 else None


def cl_mean(rows):
    """(mean, game-clustered SE, n, games) of [(game, value)]."""
    if not rows:
        return float("nan"), float("nan"), 0, 0
    n = len(rows)
    mean = sum(v for _, v in rows) / n
    by = defaultdict(float)
    for g, v in rows:
        by[g] += v - mean
    G = len(by)
    se = math.sqrt(sum(s * s for s in by.values()) * G / max(G - 1, 1)) / n if G > 1 else float("nan")
    return mean, se, n, G


def fmt(m, se):
    return f"{m:+.3f} +- {1.96 * se:.3f}" if se == se else f"{m:+.3f}"


def one_bet(rows, label, pred):
    first = {}
    for x in sorted(rows, key=lambda x: str(x["t"])):
        if x["g"] not in first and pred(x):
            first[x["g"]] = x
    if not first:
        return
    fb = list(first.values())
    hit = sum(x["win"] for x in fb) / len(fb)
    se = math.sqrt(hit * (1 - hit) / len(fb))
    print(f"  ONE BET PER GAME, {label}: {len(fb)} games, hit {hit:.3f} +- {1.96 * se:.3f}, "
          f"market fair {sum(x['psf'] for x in fb) / len(fb):.3f}, model claimed {sum(x['psm'] for x in fb) / len(fb):.3f}; "
          f"ROI at -110 {hit * (1 + 100 / 110) - 1:+.3f} (break-even hit 0.524)")


def split(rows, label, keyf, cuts):
    out = []
    for lab, lo, hi in cuts:
        b = [x for x in rows if keyf(x) is not None and lo <= keyf(x) < hi]
        if not b:
            continue
        m = cl_mean([(x["g"], x["win"] - x["psf"]) for x in b])
        big = [x for x in b if x["edge"] >= 20]
        mb = cl_mean([(x["g"], x["win"] - x["psf"]) for x in big]) if big else (float("nan"), float("nan"), 0, 0)
        out.append(f"{lab:>9}: {len(b):>6} st / {len({x['g'] for x in b}):>3} g  claimed {sum(x['psm'] - x['psf'] for x in b) / len(b):+.3f}"
                   f"  realised {fmt(m[0], m[1])}   | edge 20pp+: {len(big):>5} st realised {fmt(mb[0], mb[1])}")
    nn = sum(1 for x in rows if keyf(x) is None)
    print(f"  by {label} (missing: {nn})")
    for o in out:
        print("    " + o)


def main():
    sports = [s for s in (os.environ.get("SPORTS") or "ncaab,wncaab,nba,ncaaf").split(",")]
    if PREREG_MODE:
        if PREREG_MODE not in ("count", "grade"):
            sys.exit(f"PREREG_780 must be 'count' or 'grade', not {PREREG_MODE!r}")
        sports = [PREREG_SPORT]
        win_lo, win_hi, _ = prereg_window()
    for sport in sports:
        files = sorted(glob.glob(f"{DATA}/{sport}_source/data/live_gameline_ledger/live_gameline_ledger_*.jsonl"))
        states = {}
        held_out = [0]
        for f in files:
            for line in open(f):
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                if r.get("market") != "totals" or r.get("segment") != "full" or not r.get("priceable"):
                    continue
                if PREREG_MODE and not (win_lo <= str(r.get("date") or "") <= win_hi):
                    continue
                # THE DEFAULT MODE MUST NOT READ THE REGISTERED WINDOW: its one-bet and split lines print the
                # registered cell itself. Override only after the registered grade has run.
                if (not PREREG_MODE and sport == PREREG_SPORT and str(r.get("date") or "") >= PREREG_FROM
                        and os.environ.get("PREREG_780_INCLUDE") != "1"):
                    held_out[0] += 1
                    continue
                pm, pf, ln = model_prob(r), r.get("market_fair_prob"), r.get("line")
                if pm is None or pf is None or ln is None:
                    continue
                key = (r.get("event_id"), r.get("live_state_as_of") or r.get("recorded_at"), float(ln))
                states.setdefault(key, r)
        if held_out[0]:
            print(f"\n(held out: {held_out[0]} {sport} ledger rows on dates >= {PREREG_FROM}, the PREREG_780 window; "
                  f"PREREG_780_INCLUDE=1 reads them, only after the registered grade has run)")
        if not states:
            print(f"\n## {sport}: 0 priced full-game totals states on {len(files)} ledger dates")
            continue
        dates = sorted({r["date"] for r in states.values()})
        index_by_date = {}
        for ds in dates:
            d0 = date.fromisoformat(ds)
            idx = {}
            for d in (d0, d0 + timedelta(days=1)):
                idx.update(finals(sport, d))
            index_by_date[ds] = idx
        game_final, unmatched, bad = {}, set(), set()
        rows = []
        dir_check = [0, 0]
        for (eid, as_of, ln), r in states.items():
            if eid not in game_final and eid not in unmatched:
                hit = match(index_by_date[r["date"]], r.get("home_team"), r.get("away_team"))
                if hit is None:
                    unmatched.add(eid)
                else:
                    game_final[eid] = index_by_date[r["date"]][hit][2]
            if eid not in game_final:
                continue
            final = game_final[eid]
            sc = None
            try:
                sc = float(r.get("home_score")) + float(r.get("away_score"))
                if sc > final:
                    bad.add(eid)
                    continue
            except Exception:
                pass
            if final == ln:
                continue
            y = 1.0 if final > ln else 0.0
            pm, pf = float(model_prob(r)), float(r["market_fair_prob"])
            mt = r.get("model_total_mean")
            if mt is not None and pm != pf:
                dir_check[0] += 1
                dir_check[1] += ((pm > pf) == (float(mt) > ln)) or abs(float(mt) - ln) < 0.5
            over = pm > pf
            qa = r.get("quote_age_seconds")
            rows.append(dict(g=eid, date=r["date"], pm=pm, pf=pf, y=y, edge=abs(pm - pf) * 100, over=over,
                             psm=pm if over else 1 - pm, psf=pf if over else 1 - pf, win=y if over else 1 - y,
                             t=as_of, prog=(sc / ln) if (sc is not None and ln) else None,
                             qa=float(qa) if qa is not None else None, ln=ln, final=final,
                             mt=float(mt) if mt is not None else None))
        games = {x["g"] for x in rows}
        print(f"\n## {sport}: ledger dates {dates[0]}..{dates[-1]} ({len(dates)}), priced states {len(states)}, "
              f"games {len({k[0] for k in states})}; matched to an ESPN final {len(game_final)}, unmatched {len(unmatched)}, "
              f"score>final dropped {len(bad)}; graded states {len(rows)} / {len(games)} games; "
              f"direction check {dir_check[1]}/{dir_check[0]}")
        if not rows:
            continue
        if PREREG_MODE:
            prereg(rows, PREREG_MODE)
            continue
        bm = cl_mean([(x["g"], (x["pm"] - x["y"]) ** 2 - (x["pf"] - x["y"]) ** 2) for x in rows])
        print(f"  Brier model - market (negative = model better): {fmt(bm[0], bm[1])}   "
              f"[model {sum((x['pm'] - x['y']) ** 2 for x in rows) / len(rows):.4f}, market {sum((x['pf'] - x['y']) ** 2 for x in rows) / len(rows):.4f}]")
        wr = cl_mean([(x["g"], x["win"] - x["psf"]) for x in rows])
        print(f"  model side: over {sum(x['over'] for x in rows)} / under {sum(not x['over'] for x in rows)}; "
              f"hit {sum(x['win'] for x in rows) / len(rows):.3f} vs market fair {sum(x['psf'] for x in rows) / len(rows):.3f} "
              f"vs model claim {sum(x['psm'] for x in rows) / len(rows):.3f}; realised edge {fmt(wr[0], wr[1])}")
        split(rows, "|edge| pp", lambda x: x["edge"], (("0-5", 0, 5), ("5-10", 5, 10), ("10-20", 10, 20), ("20-30", 20, 30), ("30+", 30, 101)))
        split(rows, "quote age s", lambda x: x["qa"], (("<=30", 0, 30.0001), ("30-90", 30.0001, 90), ("90-300", 90, 300), (">300", 300, 1e12)))
        split(rows, "score/line", lambda x: x["prog"], (("<0.25", -1, 0.25), ("0.25-0.5", 0.25, 0.5), ("0.5-0.75", 0.5, 0.75), ("0.75-0.9", 0.75, 0.9), (">=0.9", 0.9, 9)))
        one_bet(rows, "first state |edge|>=10pp", lambda x: x["edge"] >= 10)
        one_bet(rows, "first state |edge|>=10pp, quote<=30s, score<75% of line",
                lambda x: x["edge"] >= 10 and x["qa"] is not None and x["qa"] <= 30 and (x["prog"] or 0) < 0.75)
        one_bet(rows, "first state |edge|>=20pp, quote<=30s",
                lambda x: x["edge"] >= 20 and x["qa"] is not None and x["qa"] <= 30)
        engine_read(rows)


def engine_read(rows):
    """Is the live total's MEAN worse than the line, or its SPREAD too narrow? Per progress bucket."""
    nd = NormalDist()
    print("  ENGINE READ  bucket   states  final-mean  mean RMSE  line RMSE  implied sd  actual err sd")
    for lab, lo, hi in (("<0.25", -1, 0.25), ("0.25-0.5", 0.25, 0.5), ("0.5-0.75", 0.5, 0.75), (">=0.75", 0.75, 9)):
        b = [x for x in rows if x["mt"] is not None and x["prog"] is not None and lo <= x["prog"] < hi]
        if not b:
            continue
        em = [x["final"] - x["mt"] for x in b]
        el = [x["final"] - x["ln"] for x in b]
        sds = []
        for x in b:
            if 0.02 < x["pm"] < 0.98 and abs(x["mt"] - x["ln"]) >= 1.0:
                z = nd.inv_cdf(x["pm"])
                if abs(z) > 0.05 and (x["mt"] - x["ln"]) / z > 0:
                    sds.append((x["mt"] - x["ln"]) / z)
        print(f"  {lab:>19} {len(b):>8}  {_mean(em):>+10.2f}  {math.sqrt(sum(e * e for e in em) / len(em)):>9.2f}"
              f"  {math.sqrt(sum(e * e for e in el) / len(el)):>9.2f}  {_median(sds) if sds else float('nan'):>10.2f}  {_pstdev(em):>13.2f}")


if __name__ == "__main__":
    main()
