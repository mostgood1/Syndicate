"""WHO does a manager go to, and when? Mining substitutions from `feed_live`.

`#440` Phase 7 / plan P1+P2. The MLB sim has **no position-player substitution
model at all** (`simulate.py`'s only `bench` reference builds a lookup cache),
which inflates every batter's opportunity by ~12-15% and every counting prop
with it. A flat haircut recovers part of that
`[measured: closes the market gap in 3 of 3 families out-of-sample]`, but a flat
scalar cannot know that THIS batter was pulled in the 7th.

This builds the empirical basis for the real thing. `feed_live` records every
substitution with everything needed:

    eventType   pitching_substitution | offensive_substitution |
                defensive_substitution | defensive_switch
    player          who came IN
    replacedPlayer  who went OUT
    position        what position they play
    battingOrder    which lineup slot
    about.inning / halfInning
    details.awayScore / homeScore     -> score state at the moment

So "who does the manager go to, by inning, position and situation" is a
measurement, not a guess.

**THE LOAD-BEARING OUTPUT IS THE PER-TEAM SPREAD.** `data/manager/manager_tendencies.json`
does not exist and its loader silently returns `{}`, so all 30 teams currently
share one hardcoded profile. If managers differ materially here, that file is
worth building and P2 is justified. If they do not, a league-average
substitution model is enough and P2 should be dropped. This script is designed
to answer that, not to assume it.

Usage:
  py -3 scripts/mlb_substitution_profile.py --json reports/phase7/sub_profile.json
"""

from __future__ import annotations

import argparse
import gzip
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FEED = REPO_ROOT / "data/mlb_source/source_artifacts/data/raw/statsapi/feed_live"

SUB_TYPES = {"pitching_substitution", "offensive_substitution",
             "defensive_substitution", "defensive_switch"}


def score_band(diff: int | None) -> str:
    """Score differential from the SUBSTITUTING team's perspective."""
    if diff is None:
        return "unknown"
    if diff <= -5:
        return "trailing_big"
    if diff <= -1:
        return "trailing"
    if diff == 0:
        return "tied"
    if diff <= 4:
        return "leading"
    return "leading_big"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path, default=None)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    files = sorted(FEED.rglob("*.json.gz"))
    if args.limit:
        files = files[:args.limit]
    if not files:
        print(f"no feed_live games under {FEED}")
        return 1

    by_type = Counter()
    by_inning = defaultdict(Counter)          # type -> inning -> n
    by_slot = Counter()                        # batting slot of the REPLACED batter
    by_position = Counter()
    by_band = defaultdict(Counter)             # type -> score band -> n
    per_team_subs = defaultdict(Counter)       # team -> type -> n
    per_team_games = Counter()
    pitcher_sub_innings = []
    games_parsed = 0

    for path in files:
        try:
            with gzip.open(path, "rt", encoding="utf-8") as fh:
                payload = json.load(fh)
        except Exception:
            continue
        games_parsed += 1
        gd = payload.get("gameData") or {}
        teams = gd.get("teams") or {}
        home_name = ((teams.get("home") or {}).get("name") or "").strip()
        away_name = ((teams.get("away") or {}).get("name") or "").strip()
        for name in (home_name, away_name):
            if name:
                per_team_games[name] += 1

        plays = (((payload.get("liveData") or {}).get("plays") or {}).get("allPlays") or [])
        for play in plays:
            about = play.get("about") or {}
            inning = about.get("inning")
            half = str(about.get("halfInning") or "").lower()
            for ev in (play.get("playEvents") or []):
                det = ev.get("details") or {}
                etype = det.get("eventType")
                if etype not in SUB_TYPES:
                    continue
                by_type[etype] += 1
                if isinstance(inning, int):
                    by_inning[etype][inning] += 1
                    if etype == "pitching_substitution":
                        pitcher_sub_innings.append(inning)

                # The FIELDING team substitutes on defense/pitching; the BATTING
                # team substitutes on offense. Getting this backwards would
                # attribute every bullpen move to the wrong manager.
                if etype == "offensive_substitution":
                    team = home_name if half == "bottom" else away_name
                    own, opp = (det.get("homeScore"), det.get("awayScore")) if half == "bottom" \
                        else (det.get("awayScore"), det.get("homeScore"))
                else:
                    team = away_name if half == "bottom" else home_name
                    own, opp = (det.get("awayScore"), det.get("homeScore")) if half == "bottom" \
                        else (det.get("homeScore"), det.get("awayScore"))
                if team:
                    per_team_subs[team][etype] += 1
                diff = (own - opp) if isinstance(own, int) and isinstance(opp, int) else None
                by_band[etype][score_band(diff)] += 1

                order = str(ev.get("battingOrder") or "")
                if len(order) >= 1 and order[0].isdigit():
                    slot = int(order[0])
                    if 1 <= slot <= 9:
                        by_slot[slot] += 1
                pos = ((ev.get("position") or {}).get("abbreviation") or "").strip()
                if pos:
                    by_position[pos] += 1

    print("=" * 92)
    print("MLB SUBSTITUTION PROFILE — mined from feed_live")
    print("=" * 92)
    print(f"\n  games parsed {games_parsed}   substitution events {sum(by_type.values())}\n")
    for etype, n in by_type.most_common():
        print(f"  {etype:26s} {n:6d}   {n / max(1, games_parsed):5.2f} per game")

    print("\nBY INNING (when does the manager act?)\n")
    print(f"  {'inning':>7s} " + "".join(f"{t.split('_')[0][:7]:>9s}" for t in sorted(by_type)))
    for inning in range(1, 13):
        row = "".join(f"{by_inning[t].get(inning, 0):9d}" for t in sorted(by_type))
        if any(by_inning[t].get(inning) for t in by_type):
            print(f"  {inning:7d} {row}")

    print("\nPOSITION-PLAYER REMOVAL BY LINEUP SLOT (the opportunity haircut, by slot)\n")
    total_slot = sum(by_slot.values()) or 1
    for slot in range(1, 10):
        n = by_slot.get(slot, 0)
        bar = "#" * int(40 * n / max(by_slot.values() or [1]))
        print(f"    slot {slot}: {n:5d}  {n/total_slot:5.1%}  {bar}")

    print("\nBY SCORE STATE (does the manager sub differently when winning?)\n")
    bands = ["trailing_big", "trailing", "tied", "leading", "leading_big", "unknown"]
    print(f"  {'type':26s}" + "".join(f"{b[:12]:>13s}" for b in bands))
    for etype in sorted(by_type):
        print(f"  {etype:26s}" + "".join(f"{by_band[etype].get(b, 0):13d}" for b in bands))

    print("\nTOP POSITIONS SUBSTITUTED\n   ",
          ", ".join(f"{p}={n}" for p, n in by_position.most_common(10)))

    # ---- THE QUESTION THAT DECIDES P2 ----
    print("\n" + "=" * 92)
    print("DOES THE MANAGER MATTER? per-team substitutions per game")
    print("=" * 92 + "\n")
    rates = {}
    for team, games in per_team_games.items():
        if games < 5:
            continue
        rates[team] = sum(per_team_subs[team].values()) / games
    if rates:
        ordered = sorted(rates.items(), key=lambda kv: -kv[1])
        for team, rate in ordered[:6]:
            print(f"    {team:26s} {rate:5.2f} subs/game  (n={per_team_games[team]})")
        print("    ...")
        for team, rate in ordered[-4:]:
            print(f"    {team:26s} {rate:5.2f} subs/game  (n={per_team_games[team]})")
        vals = list(rates.values())
        spread = max(vals) - min(vals)
        print(f"\n    teams {len(rates)}   mean {statistics.fmean(vals):.2f}   "
              f"sd {statistics.pstdev(vals):.2f}   SPREAD {spread:.2f} subs/game")
        print(f"    max/min ratio = {max(vals)/max(1e-9, min(vals)):.2f}x")
        if spread >= 1.0:
            print("\n    => MANAGERS DIFFER MATERIALLY. A per-team profile is justified;")
            print("       one hardcoded ManagerProfile for all 30 teams is not.")
        else:
            print("\n    => managers look SIMILAR on this metric. A league-average")
            print("       substitution model may be sufficient; do not build per-team")
            print("       tendencies on this evidence alone.")

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps({
            "games": games_parsed,
            "by_type": dict(by_type),
            "by_inning": {t: dict(v) for t, v in by_inning.items()},
            "by_slot": dict(by_slot),
            "by_score_band": {t: dict(v) for t, v in by_band.items()},
            "by_position": dict(by_position),
            "per_team_rate": rates,
        }, indent=2), encoding="utf-8")
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
