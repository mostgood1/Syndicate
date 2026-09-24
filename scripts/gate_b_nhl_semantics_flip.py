"""GATE (b): what does the new NHL map change, and is any change WRONG?

The 2026-08-29 FORBIDDEN entry's second condition: enumerate what the new map
resolves that the heuristics previously left unresolved, "because those are
exactly the lookups whose semantics flip from 'fall back' to 'authoritative'".
`teams_match` returns the map's verdict when both sides resolve and does NOT
fall through, so a mis-resolution stops being a harmless miss and becomes a
confident wrong answer.

This compares `teams_match("nhl", a, b)` with the map OFF and ON over every
ordered pair of the REAL token vocabulary the feeds emit, and classifies each
flip against ground truth -- the tri-code each token actually belongs to.

Exit code is non-zero if any pair flips to a WRONG answer.

    py -3 scripts/gate_b_nhl_semantics_flip.py
"""
from __future__ import annotations

import collections
import itertools
import json
import sys
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from syndicate.features.shared import team_aliases
from syndicate.features.shared.team_aliases import teams_match
from syndicate.local_nhl_odds import TEAM_ABBRS, TEAM_NAME_TO_ABBR, _norm_team_name

UA = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}


def get_json(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40) as r:
        return json.loads(r.read().decode())


# ---- Ground truth: token -> tri-code, built only from the source table and
# the feeds' own structured fields. A token whose club we cannot state is not
# used to judge a flip.
truth: dict[str, str] = {}


def claim(token, abbr):
    text = str(token or "").strip()
    if text and abbr:
        truth.setdefault(text, str(abbr).upper())


for name, abbr in TEAM_NAME_TO_ABBR.items():
    claim(name, abbr)
for abbr in TEAM_ABBRS:
    claim(abbr, abbr)

for anchor in ("2026-09-24", "2026-10-01"):
    for week in get_json(f"https://api-web.nhle.com/v1/schedule/{anchor}").get("gameWeek", []):
        for game in week.get("games", []):
            for side in ("awayTeam", "homeTeam"):
                team = game.get(side) or {}
                abbr = team.get("abbrev")
                place = (team.get("placeName") or {}).get("default", "")
                common = (team.get("commonName") or {}).get("default", "")
                claim(abbr, abbr)
                claim(f"{place} {common}".strip(), abbr)

ESPN_ABBR_TO_NHL = {"LA": "LAK", "NJ": "NJD", "SJ": "SJS", "TB": "TBL", "UTAH": "UTA"}
for day in ("20260923", "20260924", "20260926", "20261003"):
    payload = get_json(f"https://site.api.espn.com/apis/site/v2/sports/hockey/nhl/scoreboard?dates={day}")
    for event in payload.get("events", []):
        for comp in event["competitions"][0]["competitors"]:
            team = comp["team"]
            espn_abbr = str(team.get("abbreviation") or "").upper()
            abbr = ESPN_ABBR_TO_NHL.get(espn_abbr, espn_abbr)
            if abbr not in set(TEAM_ABBRS):
                continue
            claim(team.get("abbreviation"), abbr)
            claim(team.get("displayName"), abbr)

tokens = sorted(truth)
print(f"tokens with a known club: {len(tokens)}")
print(f"map size (new): {len(team_aliases._alias_map('nhl'))} keys")


def verdicts(map_on: bool):
    real = team_aliases._alias_map
    if not map_on:
        team_aliases._alias_map = lambda sport: ({} if team_aliases.normalize(sport) == "nhl" else real(sport))
    try:
        team_aliases.canonical_team.cache_clear()
    except Exception:
        pass
    try:
        team_aliases._nickname_alias_map.cache_clear()
    except Exception:
        pass
    try:
        return {(a, b): bool(teams_match("nhl", a, b)) for a, b in itertools.permutations(tokens, 2)}
    finally:
        team_aliases._alias_map = real
        try:
            team_aliases._nickname_alias_map.cache_clear()
        except Exception:
            pass


before = verdicts(map_on=False)
after = verdicts(map_on=True)

flips = collections.Counter()
wrong = []
fixed = []
for pair, old in before.items():
    new = after[pair]
    if old == new:
        continue
    a, b = pair
    should = truth[a] == truth[b]
    kind = ("FIX" if new == should else "BREAK") + ("+" if new else "-")
    flips[kind] += 1
    (wrong if new != should else fixed).append((a, b, old, new, should))

print(f"\nordered pairs compared: {len(before)}")
print(f"verdicts changed: {sum(flips.values())}   {dict(flips)}")
print(f"  FIXED  (now correct where it was wrong): {len(fixed)}")
print(f"  BROKEN (now wrong where it was right)  : {len(wrong)}")

print("\nsample of what the map newly resolves:")
for a, b, old, new, should in fixed[:12]:
    print(f"   {a!r} vs {b!r}: {old} -> {new}   (truth: same club = {should})")

if wrong:
    print("\n*** GATE (b) FAILS -- these flipped to a WRONG answer: ***")
    for a, b, old, new, should in wrong[:40]:
        print(f"   {a!r} vs {b!r}: {old} -> {new}   (truth: same club = {should})")
    sys.exit(1)

still_wrong = [p for p, v in after.items() if v != (truth[p[0]] == truth[p[1]])]
print(f"\nresidual wrong verdicts WITH the map (not introduced here): {len(still_wrong)}")
for a, b in still_wrong[:10]:
    print(f"   {a!r} vs {b!r}: {after[(a, b)]}   (truth: same club = {truth[a] == truth[b]})")
print("\nGATE (b) PASSES: no verdict flipped to a wrong answer.")
