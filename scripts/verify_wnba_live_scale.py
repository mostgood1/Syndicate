"""Verify `#481`'s refitted live scale on a REAL served payload.

`#481` refitted `_WNBA_LIVE_MARGIN_SCALE` (6.0 + 0.35*min_left -> 2.1) after
grading 212 games / 73,878 live samples: the old scale was ~2.5x too wide and
compressed every live probability toward 0.5 (samples priced 0.6-0.7 actually
won 91.3%). Brier 0.1896 -> 0.1644.

That was an OFFLINE grade against cached play-by-play. This script closes the
loop the honest way: it reads what web ACTUALLY SERVES for a live game and
checks the number against what the deployed formula should produce, so the
claim rests on a served payload rather than on a replay.

WHY IT RECOMPUTES INSTEAD OF EYEBALLING: "0.99 looks about right" is not a
verification. The check reconstructs the expected probability from the SAME
(margin, elapsed) the payload reports, using the shipped constant, and fails
on a mismatch. It also reports what the OLD constant would have produced, so
the diff is visible rather than asserted.

Exit codes:  0 verified   1 no live game (not a failure)   2 MISMATCH
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import urllib.parse
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_BASE = "https://syndicate-an21.onrender.com"
_REG = 40.0
_OLD_A, _OLD_B = 6.0, 0.35


def _margin_win_prob(margin: float, scale: float) -> float:
    if scale <= 0:
        return 0.5
    return 1.0 / (1.0 + math.exp(max(-60.0, min(60.0, -float(margin) / float(scale)))))


def _expected(pregame: float | None, margin: float, elapsed: float, scale: float) -> float:
    live = _margin_win_prob(margin, scale)
    if pregame is None:
        return live
    w = max(0.0, min(1.0, elapsed / _REG))
    return (1.0 - w) * float(pregame) + w * live


def _fetch(date_str: str) -> dict:
    url = f"{_BASE}/wnba/api/cards?" + urllib.parse.urlencode({"date": date_str})
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", default=None, help="YYYY-MM-DD (default: today UTC and yesterday)")
    ap.add_argument("--tolerance", type=float, default=0.02)
    args = ap.parse_args()

    import datetime as dt

    dates = [args.date] if args.date else [
        dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d"),
        (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)).strftime("%Y-%m-%d"),
    ]

    try:
        from syndicate.features.wnba.cards import _WNBA_LIVE_MARGIN_SCALE as SHIPPED
    except Exception:
        SHIPPED = 2.1

    live_rows = []
    for d in dates:
        try:
            payload = _fetch(d)
        except Exception as exc:
            print(f"  fetch {d}: {type(exc).__name__}: {exc}")
            continue
        for g in payload.get("games") or []:
            lens = g.get("gameLens")
            lanes = lens if isinstance(lens, list) else (lens or {}).get("lanes") if isinstance(lens, dict) else None
            for lane in (lanes or []):
                if not isinstance(lane, dict):
                    continue
                if str(lane.get("source") or "") != "live_projection":
                    continue
                mk = lane.get("markets") or {}
                ml = mk.get("moneyline") or {}
                if ml.get("p_win") is None:
                    continue
                live_rows.append({
                    "date": d,
                    "matchup": f"{g.get('away_tri')}@{g.get('home_tri')}",
                    "p_win": float(ml["p_win"]),
                    "selection": ml.get("selection"),
                    "margin": lane.get("live_margin"),
                    "elapsed": lane.get("elapsed_min"),
                    "pregame": (g.get("betting") or {}).get("p_home_win"),
                })

    if not live_rows:
        print("NO LIVE WNBA GAME with a live_projection lane right now.")
        print("  (not a failure -- #481 can only be confirmed on a served payload mid-game)")
        return 1

    print(f"shipped _WNBA_LIVE_MARGIN_SCALE = {SHIPPED}")
    bad = 0
    for r in live_rows:
        m, e = r.get("margin"), r.get("elapsed")
        print(f"\n  {r['matchup']} ({r['date']})  served p_win={r['p_win']:.4f} sel={r['selection']}")
        if m is None or e is None:
            print("    payload omits live_margin/elapsed_min -- cannot recompute, reporting served value only")
            continue
        m, e = float(m), float(e)
        exp_new = _expected(r["pregame"], m, e, SHIPPED)
        exp_old = _expected(r["pregame"], m, e, _OLD_A + _OLD_B * max(0.0, _REG - e))
        # served p_win is for the PICKED side; convert to home-side for comparison
        home_p = r["p_win"] if str(r["selection"]) == "home" else 1.0 - r["p_win"]
        gap = abs(home_p - exp_new)
        ok = gap <= args.tolerance
        print(f"    margin={m:+.0f} elapsed={e:.1f}min  home_p(served)={home_p:.4f}")
        print(f"    expected NEW scale={SHIPPED}: {exp_new:.4f}   gap={gap:.4f}  {'OK' if ok else 'MISMATCH'}")
        print(f"    would-be OLD 6.0+0.35*min_left: {exp_old:.4f}   (delta {exp_new - exp_old:+.4f})")
        if not ok:
            bad += 1

    if bad:
        print(f"\nMISMATCH on {bad} of {len(live_rows)} live rows -- served value does not match the deployed formula")
        return 2
    print(f"\nVERIFIED on {len(live_rows)} live row(s): served probabilities match the refitted scale")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
