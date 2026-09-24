"""GATE (b) for NCAAB: what does the new map change, and is any change WRONG?

Same contract as `gate_b_nhl_semantics_flip.py`. The population differs by
necessity: NCAAB is out of season, so there is no slate and no capture to draw
tokens from. The registry's own vocabulary IS the population a join will see --
every column a feed may render a school by -- and ground truth is the school
the registry states for each token.

TOKENS THE REGISTRY ITSELF REPORTS AS AMBIGUOUS ARE EXCLUDED FROM JUDGEMENT,
not from the comparison: `tigers` has no single true school, so a verdict about
it cannot be scored. They are counted separately, because a map that started
answering about them would be the exact 2026-08-29 failure.

Exit code is non-zero if any pair flips to a WRONG answer.

    py -3 scripts/gate_b_ncaab_semantics_flip.py [--sample N]
"""
from __future__ import annotations

import argparse
import collections
import itertools
import random
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from syndicate.features.shared import team_aliases
from syndicate.features.shared.ncaab_team_registry import iter_team_alias_offers, registry_rows
from syndicate.features.shared.team_aliases import normalize, teams_match

parser = argparse.ArgumentParser()
parser.add_argument("--sample", type=int, default=260,
                    help="tokens to compare pairwise; the full 1,341 would be 1.8M pairs")
parser.add_argument("--seed", type=int, default=20260923)
args = parser.parse_args()

rows = registry_rows()
print(f"registry rows: {len(rows)}")

owners: dict[str, set[str]] = {}
for token, school in iter_team_alias_offers():
    key = normalize(token)
    if key:
        owners.setdefault(key, set()).add(normalize(school))

unique = {k: next(iter(v)) for k, v in owners.items() if len(v) == 1}
ambiguous = {k: sorted(v) for k, v in owners.items() if len(v) > 1}
print(f"tokens offered: {len(owners)}   unambiguous: {len(unique)}   AMBIGUOUS (unscoreable): {len(ambiguous)}")
print("  worst offenders:", ", ".join(
    f"{k}({len(v)})" for k, v in sorted(ambiguous.items(), key=lambda kv: -len(kv[1]))[:8]))

mapping = team_aliases._alias_map("ncaab")
leaked = sorted(k for k in ambiguous if k in mapping)
print(f"\nambiguous tokens that LEAKED into the map: {len(leaked)}")
if leaked:
    print("   ", leaked[:20])

random.seed(args.seed)
tokens = sorted(unique)
if len(tokens) > args.sample:
    tokens = sorted(random.sample(tokens, args.sample))
print(f"\ncomparing {len(tokens)} unambiguous tokens pairwise ...")


def verdicts(map_on: bool):
    real = team_aliases._alias_map
    if not map_on:
        team_aliases._alias_map = lambda sport: ({} if normalize(sport) == "ncaab" else real(sport))
    for cache in (getattr(team_aliases, "canonical_team", None), getattr(team_aliases, "_nickname_alias_map", None)):
        try:
            cache.cache_clear()
        except Exception:
            pass
    try:
        return {(a, b): bool(teams_match("ncaab", a, b)) for a, b in itertools.permutations(tokens, 2)}
    finally:
        team_aliases._alias_map = real
        try:
            team_aliases._nickname_alias_map.cache_clear()
        except Exception:
            pass


before = verdicts(map_on=False)
after = verdicts(map_on=True)

flips = collections.Counter()
wrong, fixed = [], []
for pair, old in before.items():
    new = after[pair]
    if old == new:
        continue
    a, b = pair
    should = unique[a] == unique[b]
    flips[("FIX" if new == should else "BREAK") + ("+" if new else "-")] += 1
    (wrong if new != should else fixed).append((a, b, old, new, should))

print(f"ordered pairs compared: {len(before)}")
print(f"verdicts changed: {sum(flips.values())}   {dict(flips)}")
print(f"  FIXED : {len(fixed)}")
print(f"  BROKEN: {len(wrong)}")
print("\nsample of what the map newly resolves:")
for a, b, old, new, should in fixed[:12]:
    print(f"   {a!r} vs {b!r}: {old} -> {new}   (truth: same school = {should})")

if wrong:
    print("\n*** GATE (b) FAILS -- flipped to a WRONG answer: ***")
    for a, b, old, new, should in wrong[:40]:
        print(f"   {a!r} vs {b!r}: {old} -> {new}   (truth: same school = {should})")
    sys.exit(1)

residual = [p for p, v in after.items() if v != (unique[p[0]] == unique[p[1]])]
print(f"\nresidual wrong verdicts WITH the map: {len(residual)}")
for a, b in residual[:10]:
    print(f"   {a!r} vs {b!r}: {after[(a, b)]}   (truth: same school = {unique[a] == unique[b]})")
print("\nGATE (b) PASSES: no verdict flipped to a wrong answer.")
