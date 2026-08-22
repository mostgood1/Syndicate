"""PILOT: does the BOOK already price the momentum signal?

THE QUESTION THIS ANSWERS, and why it is not the obvious one. The obvious test
is "does my signal predict goals better than the book's implied probability" --
but that needs GOALS, and today's joinable sample is ~8 matches with a ~14% base
rate at a 300s window, i.e. roughly 30 positive events. Nothing can be resolved
with 30 events; the confidence interval would span every conclusion.

This test needs no goals at all. If books price live momentum, their implied
goal expectation must MOVE WITH momentum. So: at each in-play odds snapshot,
compare the book's de-vigged Over probability against the momentum signal,
controlling for the two things that trivially drive both (match clock and
current score). A strong partial association means the price already contains
the signal and there is no edge left in it. A weak one means there may be.

RESOLUTION IS THE BINDING CONSTRAINT AND IS NOT FIXABLE HERE. Odds snapshots
arrive every ~333s (median, poll-triggered -- 69% of consecutive pairs are
identical prices, so that gap is OUR cadence, not the books moving). The signal
decays with a ~60s half-life. A momentum spike is therefore usually OVER before
the next price is observed. This pilot can detect whether books track SUSTAINED
pressure; it cannot see whether they miss brief spikes, which is exactly where
the edge would live. Read every number here with that in mind.

CLOCK ALIGNMENT is by kickoff time from FotMob, not by assuming the first live
snapshot is kickoff -- books quote in-play markets from before the whistle, so
that assumption would shift every match by an unknown offset.
"""

from __future__ import annotations

import json
import math
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_ODDS = Path("C:/tmp/audit/oh22.json")
_KICK = Path("C:/tmp/audit/kickoffs.json")
_FM = REPO_ROOT / "reports/soccer_backtest/fotmob_2y.json"


def american_to_prob(price) -> float | None:
    try:
        p = float(price)
    except (TypeError, ValueError):
        return None
    if math.isnan(p) or p == 0:
        return None
    return 100.0 / (p + 100.0) if p > 0 else (-p) / ((-p) + 100.0)


def norm(name: str) -> str:
    s = re.sub(r"[^a-z ]", "", str(name).lower())
    for junk in (" fc", " cf", " sc", " afc", " club", " city", " united", " town"):
        s = s.replace(junk, " ")
    return " ".join(s.split())


def main() -> int:
    odds = list(json.loads(_ODDS.read_text(encoding="utf-8"))["artifacts"].values())[0]
    if isinstance(odds, str):
        odds = json.loads(odds)
    markets = odds["markets"]
    kicks = json.loads(_KICK.read_text(encoding="utf-8"))
    fm = {str(m["match_id"]): m for m in json.loads(_FM.read_text(encoding="utf-8"))["matches"]
          if m.get("date") == "2026-08-22"}

    # ---- index odds by event, collecting de-vigged Over prob per snapshot ----
    events: dict[str, dict] = {}
    for key, val in markets.items():
        if not val.get("is_live") or "|market=totals|" not in key:
            continue
        m = re.search(r"event_id=([^|]+)\|home_team=([^|]+)\|away_team=([^|]+)\|market=totals\|side=([^|]+)\|book=([^|]+)", key)
        if not m:
            continue
        eid, home, away, side, book = m.groups()
        ev = events.setdefault(eid, {"home": home, "away": away, "snaps": {}})
        for h in (val.get("history") or []):
            ts = h.get("snapshot_ts")
            if not ts:
                continue
            line_obj = h.get("line") or {}
            try:
                line = float(line_obj.get("line"))
            except (TypeError, ValueError):
                continue
            if math.isnan(line):
                continue
            pr = american_to_prob(h.get("odds"))
            if pr is None:
                continue
            slot = ev["snaps"].setdefault((ts, line, book), {})
            slot[side.lower()] = pr

    # ---- join to FotMob by team name ----
    fm_by_name = {}
    for mid, meta in kicks.items():
        fm_by_name[(norm(meta["home"]), norm(meta["away"]))] = (mid, meta)

    def find(home, away):
        h, a = norm(home), norm(away)
        if (h, a) in fm_by_name:
            return fm_by_name[(h, a)]
        for (fh, fa), v in fm_by_name.items():
            if (fh in h or h in fh) and (fa in a or a in fa):
                return v
        return None

    rows = []
    joined = 0
    for eid, ev in events.items():
        hit = find(ev["home"], ev["away"])
        if not hit:
            continue
        mid, meta = hit
        match = fm.get(mid)
        if not match:
            continue
        ko_raw = meta.get("kickoff")
        try:
            ko = datetime.strptime(ko_raw, "%a, %b %d, %Y, %H:%M UTC").replace(tzinfo=timezone.utc)
        except Exception:
            continue
        joined += 1
        vm = match.get("vendor_momentum") or []
        vt = np.array([p["t"] for p in vm]) if vm else np.zeros(0)
        vv = np.array([p["value"] for p in vm]) if vm else np.zeros(0)
        gt = np.array([g["t"] for g in match["goals"]], dtype=float)

        # de-vig each (ts, line, book) that has both sides, then median per ts
        per_ts: dict[str, list[float]] = {}
        for (ts, line, book), sides in ev["snaps"].items():
            over, under = sides.get("over"), sides.get("under")
            if over is None or under is None or (over + under) <= 0:
                continue
            per_ts.setdefault(ts, []).append(over / (over + under))

        for ts, probs in per_ts.items():
            when = datetime.fromisoformat(ts)
            clock = (when - ko).total_seconds()
            if clock < 0 or clock > 5700:          # in-play only
                continue
            mom = 0.0
            if vt.size:
                idx = int(np.searchsorted(vt, clock, side="right") - 1)
                if idx >= 0:
                    mom = abs(float(vv[idx]))
            rows.append({
                "event": eid, "clock": clock,
                "p_over": float(np.median(probs)),
                "mom": mom,
                "score": float((gt <= clock).sum()) if gt.size else 0.0,
                "n_books": len(probs),
            })

    print("events with live totals: %d   joined to FotMob: %d" % (len(events), joined))
    print("in-play snapshot observations: %d" % len(rows))
    if len(rows) < 30:
        print("\nTOO FEW OBSERVATIONS TO TEST. Reporting the count and stopping"
              " rather than producing a number that cannot mean anything.")
        return 0

    clock = np.array([r["clock"] for r in rows])
    pov = np.array([r["p_over"] for r in rows])
    mom = np.array([r["mom"] for r in rows])
    score = np.array([r["score"] for r in rows])

    print("\n  momentum   mean %.1f  sd %.1f  range %.0f..%.0f" % (mom.mean(), mom.std(), mom.min(), mom.max()))
    print("  p_over     mean %.4f sd %.4f" % (pov.mean(), pov.std()))

    # raw and partial association, controlling for clock and score
    def corr(a, b):
        if a.std() == 0 or b.std() == 0:
            return float("nan")
        return float(np.corrcoef(a, b)[0, 1])

    print("\n=== DOES THE BOOK'S PRICE MOVE WITH MOMENTUM? ===")
    print("  raw corr(momentum, p_over)          %+.4f" % corr(mom, pov))
    # residualise both on clock + score (the two trivial common causes)
    D = np.column_stack([np.ones_like(clock), clock, clock ** 2, score])
    beta_p, *_ = np.linalg.lstsq(D, pov, rcond=None)
    beta_m, *_ = np.linalg.lstsq(D, mom, rcond=None)
    rp, rm = pov - D @ beta_p, mom - D @ beta_m
    pc = corr(rm, rp)
    n = len(rows)
    se = 1.0 / math.sqrt(max(1, n - 4))
    print("  PARTIAL corr, controlling clock+score  %+.4f   (~1 SE = %.4f, n=%d)" % (pc, se, n))
    print()
    if abs(pc) < 2 * se:
        print("  -> NOT distinguishable from zero at this sample size.")
        print("     This is a statement about POWER, not about books. With n=%d the" % n)
        print("     interval spans both 'fully priced' and 'not priced at all'.")
    elif pc > 0:
        print("  -> The price DOES move with momentum: books track it, and the")
        print("     edge in sustained pressure is at least partly gone.")
    else:
        print("  -> Price moves AGAINST momentum, which would be surprising and")
        print("     should be treated as a data or alignment bug before a finding.")

    Path("reports/soccer_backtest/market_momentum_pilot.json").write_text(
        json.dumps({"n_obs": n, "joined_matches": joined,
                    "raw_corr": corr(mom, pov), "partial_corr": pc,
                    "one_se": se, "rows": rows[:200]}, indent=2), encoding="utf-8")
    print("\nwrote reports/soccer_backtest/market_momentum_pilot.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
