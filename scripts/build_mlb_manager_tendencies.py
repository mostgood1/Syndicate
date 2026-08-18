"""Fit `data/manager/manager_tendencies.json` from `feed_live`. `#440` P2.

WHY THIS FILE MATTERS. `ManagerProfile`'s loader reads
`data/manager/manager_tendencies.json`, **that file does not exist**, and the
loader silently returns `{}` -- so all 30 teams run one hardcoded profile. The
consequences are measured:

  * the sim has NO position-player substitution at all, inflating every batter's
    opportunity by ~12-15% (`ab_mean` +14.6%, `pa_mean` +19.7%);
  * managers demonstrably differ -- 4.61 to 7.73 substitutions per game across
    30 teams, a **1.68x spread** over 618 games.

WHAT IT PRODUCES. An actuarial **hazard**, which is the shape an in-sim model can
actually consume: at each inning, given a starter is still in the game, what is
the probability the manager removes them now?

    P(removed in inning I) = league_hazard[I]
                             x slot_multiplier[slot]
                             x margin_multiplier[band]
                             x team_multiplier[team]

**THE MARGIN TERM IS THE POINT OF DOING THIS IN-SIM.** The pregame haircut could
not use score state at all -- it is unknown when a projection is made, so that
work had to fall back to the *projected* margin as a proxy, and the proxy's
direction turned out to be dominated by defensive substitutions when LEADING.
A simulation knows its own score at every inning, so it can condition on the
REAL thing. That is the capability a rescaling approach structurally cannot have,
and it is why the haircut's returns collapsed (+0.0057 -> +0.0028 -> +0.0016).

STARTERS ARE EXACT, NOT INFERRED. `boxscore.teams.<side>.battingOrder` is the
nine starting player ids in order, and each player's `battingOrder` field encodes
slot and substitution depth (`"500"` = slot 5 starter, `"501"` = first sub in
that slot). Removals come from substitution events' `replacedPlayer.id`, so a
starter's exit inning is read rather than guessed.

Usage:
  py -3 scripts/build_mlb_manager_tendencies.py --out data/manager/manager_tendencies.json
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

# `defensive_switch` moves a player between positions WITHOUT removing them from
# the lineup, so it must not count as a removal. Verified against the
# `replacedPlayer` field: a switch carries none.
REMOVAL_TYPES = {"offensive_substitution", "defensive_substitution"}
MAX_INNING = 9


def margin_band(diff: int | None) -> str:
    if diff is None:
        return "even"
    if diff >= 2:
        return "leading"
    if diff <= -2:
        return "trailing"
    return "even"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path,
                        default=REPO_ROOT / "data/manager/manager_tendencies.json")
    parser.add_argument("--min-team-games", type=int, default=15)
    args = parser.parse_args()

    files = sorted(FEED.rglob("*.json.gz"))
    if not files:
        print(f"no feed_live games under {FEED}")
        return 1

    # hazard accounting: for each inning, how many starters were AT RISK and how
    # many were removed. A starter already gone is not at risk again.
    at_risk = Counter()
    removed = Counter()
    slot_removed, slot_at_risk = Counter(), Counter()
    band_removed, band_at_risk = Counter(), Counter()
    team_removed, team_games = Counter(), Counter()
    dates = set()
    team_game_count = 0

    for path in files:
        try:
            with gzip.open(path, "rt", encoding="utf-8") as fh:
                payload = json.load(fh)
        except Exception:
            continue
        gd = payload.get("gameData") or {}
        if ((gd.get("status") or {}).get("abstractGameState") or "") != "Final":
            continue
        dates.add(str((gd.get("datetime") or {}).get("officialDate") or "")[:10])
        live = payload.get("liveData") or {}
        box = ((live.get("boxscore") or {}).get("teams") or {})
        names = {"home": ((gd.get("teams") or {}).get("home") or {}).get("name", ""),
                 "away": ((gd.get("teams") or {}).get("away") or {}).get("name", "")}

        # slot of each STARTER, per side.
        #
        # NOT from `boxscore.battingOrder` -- that list is the END-OF-GAME
        # lineup, so a starter who was replaced is ABSENT from it. Measured:
        # 0 of 4 replaced ids appeared in the list, against 4 of 4 among players
        # whose own `battingOrder` field ends in "00". Using the list would have
        # produced exactly the silent zero this first returned.
        #
        # The field encodes slot and substitution depth: "500" = slot 5 starter,
        # "501" = first substitute in that slot. So slot = value // 100.
        slot_of: dict[str, dict[int, int]] = {}
        for side in ("home", "away"):
            players = (box.get(side) or {}).get("players") or {}
            mapping: dict[int, int] = {}
            for key, entry in players.items():
                order_code = str((entry or {}).get("battingOrder") or "")
                if not order_code.endswith("00") or not order_code.isdigit():
                    continue
                pid = (entry.get("person") or {}).get("id")
                if pid is None:
                    try:
                        pid = int(str(key).replace("ID", ""))
                    except ValueError:
                        continue
                slot = int(order_code) // 100
                if 1 <= slot <= 9:
                    mapping[int(pid)] = slot
            slot_of[side] = mapping
            if slot_of[side]:
                team_game_count += 1
                if names[side]:
                    team_games[names[side]] += 1

        # removals: (side, slot) -> inning, plus the margin at that moment
        exits: dict[tuple[str, int], tuple[int, str]] = {}
        for play in (((live.get("plays") or {}).get("allPlays")) or []):
            about = play.get("about") or {}
            inning = about.get("inning")
            half = str(about.get("halfInning") or "").lower()
            if not isinstance(inning, int):
                continue
            for ev in (play.get("playEvents") or []):
                det = ev.get("details") or {}
                if det.get("eventType") not in REMOVAL_TYPES:
                    continue
                out_id = (ev.get("replacedPlayer") or {}).get("id")
                if out_id is None:
                    continue
                for side in ("home", "away"):
                    slot = slot_of.get(side, {}).get(int(out_id))
                    if slot is None:
                        continue
                    own = det.get("homeScore") if side == "home" else det.get("awayScore")
                    opp = det.get("awayScore") if side == "home" else det.get("homeScore")
                    diff = (own - opp) if isinstance(own, int) and isinstance(opp, int) else None
                    key = (side, slot)
                    # first removal only -- a slot can be substituted repeatedly
                    if key not in exits:
                        exits[key] = (min(inning, MAX_INNING), margin_band(diff))
                    if names[side]:
                        team_removed[names[side]] += 1

        # walk innings, accumulating exposure
        for side in ("home", "away"):
            if not slot_of.get(side):
                continue
            for slot in range(1, 10):
                gone_at, band = exits.get((side, slot), (None, None))
                for inning in range(1, MAX_INNING + 1):
                    if gone_at is not None and inning > gone_at:
                        break  # no longer at risk
                    at_risk[inning] += 1
                    slot_at_risk[slot] += 1
                    if gone_at == inning:
                        removed[inning] += 1
                        slot_removed[slot] += 1
                        if band:
                            band_removed[band] += 1
                if band:
                    band_at_risk[band] += 1

    if not at_risk:
        print("no exposure accumulated")
        return 1
    # A zero numerator against a large denominator is a BROKEN JOIN, not a
    # finding -- it is exactly what the end-of-game-lineup bug produced on the
    # first run (10,728 at risk, 0 removed). Refuse to write that artifact.
    if sum(removed.values()) == 0:
        print(f"REFUSED: {sum(at_risk.values())} starter-innings at risk and ZERO "
              f"removals joined. The starter->removal join is broken; not writing.")
        return 1

    inning_hazard = {str(i): (removed[i] / at_risk[i]) if at_risk[i] else 0.0
                     for i in range(1, MAX_INNING + 1)}
    overall = sum(removed.values()) / sum(at_risk.values())

    slot_mult = {}
    for slot in range(1, 10):
        rate = (slot_removed[slot] / slot_at_risk[slot]) if slot_at_risk[slot] else overall
        slot_mult[str(slot)] = round(rate / overall, 4) if overall else 1.0

    # band exposure is approximate -- a starter's band is only known at exit, so
    # this is a RATIO OF REMOVALS, normalised, not a true hazard by band. Said
    # plainly rather than presented as something it is not.
    band_total = sum(band_removed.values()) or 1
    band_share = {b: band_removed[b] / band_total for b in ("leading", "even", "trailing")}
    band_mult = {b: round(v / (1 / 3), 4) for b, v in band_share.items()}

    teams = {}
    league_rate = (sum(team_removed.values()) / sum(team_games.values())) if team_games else 0.0
    for team, games in sorted(team_games.items()):
        if games < args.min_team_games:
            continue
        rate = team_removed[team] / games
        teams[team] = {"removals_per_game": round(rate, 4),
                       "multiplier": round(rate / league_rate, 4) if league_rate else 1.0,
                       "team_games": games}

    artifact = {
        "schema_version": 1,
        "source": {"games_parsed": len(files), "team_games": team_game_count,
                   "dates": len(dates),
                   "date_range": [min(d for d in dates if d), max(d for d in dates if d)]
                   if any(dates) else None},
        "league": {
            "overall_removal_hazard_per_inning": round(overall, 5),
            "inning_hazard": {k: round(v, 5) for k, v in inning_hazard.items()},
            "slot_multiplier": slot_mult,
            "margin_multiplier": band_mult,
            "margin_multiplier_note":
                "removal SHARE by band, normalised -- exposure by band is not "
                "observable since a starter's band is known only at exit",
        },
        "teams": teams,
    }

    print("=" * 88)
    print("MLB MANAGER TENDENCIES — fitted from feed_live")
    print("=" * 88)
    print(f"\n  games {len(files)}   team-games {team_game_count}   dates {len(dates)}")
    print(f"  overall removal hazard {overall:.5f} per starter-inning\n")
    print("  INNING HAZARD  P(removed this inning | still in)")
    for i in range(1, MAX_INNING + 1):
        h = inning_hazard[str(i)]
        print(f"    inning {i}: {h:.5f}   at_risk={at_risk[i]:6d}  removed={removed[i]:4d}  "
              f"{'#' * int(h * 400)}")
    print("\n  SLOT MULTIPLIER")
    print("   ", "  ".join(f"{s}:{slot_mult[s]:.2f}" for s in map(str, range(1, 10))))
    print("\n  MARGIN MULTIPLIER (removal share, normalised)")
    print("   ", "  ".join(f"{b}:{band_mult[b]:.2f}" for b in ("leading", "even", "trailing")))
    print(f"\n  TEAMS fitted: {len(teams)}")
    if teams:
        ordered = sorted(teams.items(), key=lambda kv: -kv[1]["multiplier"])
        for t, v in ordered[:3]:
            print(f"    {t:24s} x{v['multiplier']:.2f}  ({v['removals_per_game']:.2f}/game)")
        print("    ...")
        for t, v in ordered[-3:]:
            print(f"    {t:24s} x{v['multiplier']:.2f}  ({v['removals_per_game']:.2f}/game)")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(artifact, indent=2), encoding="utf-8")
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
