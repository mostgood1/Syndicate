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

TWO DEFECTS FIXED 2026-08-20, both of which made this script print VERIFIED
while verifying NOTHING. Found on the first real live game it ever saw:

1. **It read fields the payload does not have.** It looked for
   `lane["live_margin"]` and `lane["elapsed_min"]`. The lane built by
   `_wnba_game_lens` publishes neither: the margin is
   `lane["projection"]["homeMargin"]`, and elapsed is not published at all --
   it is DERIVED from `status.period` / `status.clock` via
   `_wnba_elapsed_minutes`. So every live row hit the `continue`.
2. **A row it could not check counted as a row that passed.** `continue` left
   `bad` at 0, so the script printed "VERIFIED on 1 live row(s)" and exited 0
   having compared nothing. Unknown defaulted to the permissive branch --
   the exact failure mode this repo has a standing rule about. Rows that
   cannot be recomputed are now counted separately and exit 3; only a row
   whose served value was actually reproduced can produce a 0.

Also: the expected value is now computed by IMPORTING the shipped functions
rather than re-implementing the blend here. The old copy could drift from
production and would then "verify" the wrong formula -- the same
two-copies-of-one-convention hazard `#475` called out.

Exit codes:  0 verified   1 no live game (not a failure)   2 MISMATCH
             3 live game found but NOT checkable (fields missing)
"""
from __future__ import annotations

import argparse
import json
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


def _fetch(date_str: str) -> dict:
    url = f"{_BASE}/wnba/api/cards?" + urllib.parse.urlencode({"date": date_str})
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--date", default=None, help="YYYY-MM-DD (default: yesterday, today and tomorrow UTC)")
    ap.add_argument("--tolerance", type=float, default=1e-9)
    args = ap.parse_args()

    import datetime as dt

    # The shipped code IS the reference. Importing it (rather than restating
    # the formula) means this script cannot verify a formula production does
    # not run.
    from syndicate.features.wnba.cards import (
        _WNBA_LIVE_MARGIN_SCALE as SHIPPED,
        _margin_win_prob,
        _wnba_elapsed_minutes,
        _wnba_live_cover_prob,
        _wnba_live_margin_win_prob,
    )

    def expected_old(pregame: float, margin: float, elapsed: float) -> float:
        """What the pre-`#481` constant would have served for the same inputs."""
        scale = _OLD_A + _OLD_B * max(0.0, _REG - elapsed)
        live = _margin_win_prob(margin, scale=scale)
        weight = max(0.0, min(1.0, elapsed / _REG))
        return ((1.0 - weight) * pregame) + (weight * live)

    def expected_old_cover(
        pregame: float, margin: float, home_spread: float, elapsed: float
    ) -> float:
        """Pre-`#481` cover probability. `#481` refit win AND cover, deliberately
        sharing one constant, so verifying only the moneyline would leave half
        the change unchecked."""
        scale = _OLD_A + _OLD_B * max(0.0, _REG - elapsed)
        live = _margin_win_prob(margin + home_spread, scale=scale)
        weight = max(0.0, min(1.0, elapsed / _REG))
        return ((1.0 - weight) * pregame) + (weight * live)

    now = dt.datetime.now(dt.timezone.utc)
    # YESTERDAY-UTC is the load-bearing one and the easy thing to get wrong.
    # The board keys games by the ET business date, so a game tipping
    # 2026-08-21T00:00Z -- an ordinary 7pm ET tip -- is filed under
    # `2026-08-20`. Searching only today/tomorrow UTC therefore reports "no
    # live game" during precisely the evening window when WNBA games are
    # actually being played. Measured 2026-08-21T00:16Z: IND@DAL was live,
    # in Q1, with a `live_projection` lane, and a today/tomorrow search
    # returned nothing. All three dates are cheap; the miss is not.
    dates = [args.date] if args.date else [
        (now - dt.timedelta(days=1)).strftime("%Y-%m-%d"),
        now.strftime("%Y-%m-%d"),
        (now + dt.timedelta(days=1)).strftime("%Y-%m-%d"),
    ]

    live_rows: list[dict] = []
    for date_str in dates:
        try:
            payload = _fetch(date_str)
        except Exception as exc:
            print(f"  fetch {date_str}: {type(exc).__name__}: {exc}")
            continue
        for game in payload.get("games") or []:
            status = game.get("status") if isinstance(game.get("status"), dict) else {}
            lens = game.get("gameLens")
            lanes = lens if isinstance(lens, list) else (
                (lens or {}).get("lanes") if isinstance(lens, dict) else None
            )
            for lane in (lanes or []):
                if not isinstance(lane, dict):
                    continue
                if str(lane.get("source") or "") != "live_projection":
                    continue
                projection = lane.get("projection") if isinstance(lane.get("projection"), dict) else {}
                markets = lane.get("markets") or {}
                moneyline = markets.get("moneyline") or {}
                spread = markets.get("spread") or {}
                betting = game.get("betting") if isinstance(game.get("betting"), dict) else {}
                live_rows.append({
                    "date": date_str,
                    "matchup": f"{game.get('away_tri')}@{game.get('home_tri')}",
                    "period": status.get("period"),
                    "clock": status.get("clock"),
                    "margin": projection.get("homeMargin"),
                    # Published output of the function under test.
                    "served_home_p": lane.get("modelHomeWinProb"),
                    "pregame": lane.get("baselineHomeWinProb"),
                    "ml_p_win": moneyline.get("p_win"),
                    "ml_selection": moneyline.get("selection"),
                    # Cover path -- same refitted constant, verified alongside.
                    "served_cover_p": spread.get("p_win"),
                    "home_spread": spread.get("homeLine"),
                    "pregame_cover": betting.get("p_home_cover"),
                })

    if not live_rows:
        print("NO LIVE WNBA GAME with a live_projection lane right now.")
        print("  (not a failure -- #481 can only be confirmed on a served payload mid-game)")
        return 1

    print(f"shipped _WNBA_LIVE_MARGIN_SCALE = {SHIPPED}")
    bad = 0
    unchecked = 0
    checked = 0
    for row in live_rows:
        print(f"\n  {row['matchup']} ({row['date']})  P{row['period']} clock {row['clock']}")
        margin = row["margin"]
        pregame = row["pregame"]
        served = row["served_home_p"]
        elapsed = _wnba_elapsed_minutes(row["period"], row["clock"])
        missing = [
            name for name, value in (
                ("projection.homeMargin", margin),
                ("baselineHomeWinProb", pregame),
                ("modelHomeWinProb", served),
                ("elapsed (from status.period/clock)", elapsed),
            ) if value is None
        ]
        if missing:
            # NOT a pass. A row we cannot reproduce is a row we did not verify.
            unchecked += 1
            print(f"    NOT CHECKABLE -- payload missing: {', '.join(missing)}")
            continue

        margin = float(margin)
        pregame = float(pregame)
        served = float(served)
        elapsed = float(elapsed)
        exp_new = _wnba_live_margin_win_prob(pregame, margin, elapsed)
        exp_old = expected_old(pregame, margin, elapsed)
        gap = abs(served - exp_new)
        ok = gap <= args.tolerance
        checked += 1
        if not ok:
            bad += 1
        blend_w = max(0.0, min(1.0, elapsed / _REG))
        print(f"    margin={margin:+.0f}  elapsed={elapsed:.3f}min  blend_w={blend_w:.3f}  pregame={pregame:.4f}")
        print(f"    SERVED     modelHomeWinProb = {served:.10f}")
        print(f"    RECOMPUTED (scale {SHIPPED})    = {exp_new:.10f}   gap={gap:.2e}  {'OK' if ok else 'MISMATCH'}")
        print(f"    would-be OLD {_OLD_A}+{_OLD_B}*min_left = {exp_old:.10f}   (delta {served - exp_old:+.4f})")
        # Cross-check: the published moneyline must agree with the lane's own
        # home-side probability, or the board is showing a different number
        # than the one just verified.
        if row["ml_p_win"] is not None and row["ml_selection"] is not None:
            ml_home = (
                float(row["ml_p_win"]) if str(row["ml_selection"]) == "home"
                else 1.0 - float(row["ml_p_win"])
            )
            flag = "OK" if abs(ml_home - served) <= 1e-6 else "DISAGREES WITH LANE"
            print(f"    markets.moneyline -> home_p = {ml_home:.10f}  {flag}")

        # The cover half of `#481`, which shares the same constant by design.
        served_cover = row["served_cover_p"]
        home_spread = row["home_spread"]
        pregame_cover = row["pregame_cover"]
        if served_cover is None or home_spread is None or pregame_cover is None:
            print("    spread: NOT CHECKABLE (no served cover prob / line / pregame anchor)")
        else:
            served_cover = float(served_cover)
            exp_cover = _wnba_live_cover_prob(
                float(pregame_cover), margin, float(home_spread), elapsed
            )
            exp_cover_old = expected_old_cover(
                float(pregame_cover), margin, float(home_spread), elapsed
            )
            cover_gap = abs(served_cover - exp_cover)
            cover_ok = cover_gap <= args.tolerance
            checked += 1
            if not cover_ok:
                bad += 1
            print(f"    SPREAD (line {home_spread:+.1f}) served p_cover = {served_cover:.10f}")
            print(f"    RECOMPUTED (scale {SHIPPED})    = {exp_cover:.10f}   gap={cover_gap:.2e}  {'OK' if cover_ok else 'MISMATCH'}")
            print(f"    would-be OLD {_OLD_A}+{_OLD_B}*min_left = {exp_cover_old:.10f}   (delta {served_cover - exp_cover_old:+.4f})")

    print()
    if bad:
        print(f"MISMATCH on {bad} of {checked} checks -- served value does not match the deployed formula")
        return 2
    if not checked:
        print(f"NOT VERIFIED: {unchecked} live row(s) found, none checkable. Nothing was compared.")
        return 3
    message = (
        f"VERIFIED: {checked} check(s) across {len(live_rows) - unchecked} live row(s) "
        f"reproduce the refitted scale exactly"
    )
    if unchecked:
        message += f"  ({unchecked} further row(s) NOT checkable and NOT counted as passing)"
    print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
