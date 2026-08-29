# HANDOFF → lane `ncaaf-settlement-resolver`: the NCAAF team registry has no `UMass` alias

**From** session `6dc988f8`, lane `ncaaf-chip-grid-join`, 2026-08-29.
**Impact today:** 4 shortlist rows on a future date. **No game in play is affected.**
**Why it is yours:** the registry module and its vocabulary are your lane's;
this is a data gap in the artifact it reads, not a defect in your code.

---

## The finding, in one line

`ncaaf_team_registry.csv` knows UMass only as **`Massachusetts`**. OddsAPI sends
**`UMass Minutemen`**. Nothing bridges them, so a legitimate FBS-vs-FBS game
fails its chip↔grid join.

## Evidence

Measured on the served `/api/board/layer2-shortlist?date=2026-08-29&limit=2000`
after the join fix (`95c4fb12`) was live on web and refresh-worker:

```
2026-09-03    20 rows,  2 with game_state
   OK   Akron Zips @ Wake Forest Demon Deacons
   MISS Massachusetts/UMass Minutemen @ Rutgers Scarlet Knights   <- THIS ONE
   MISS Albany @ Buffalo            (FCS visitor - correct, no card, no chip)
   MISS Bethune-Cookman @ UCF       (FCS visitor - correct)
   MISS Merrimack @ Delaware        (FCS visitor - correct)
   MISS West Georgia @ Kennesaw St  (FCS visitor - correct)
```

**9 of the 10 unmatched matchups across 09-03/09-04 are correct** — they are
FBS-vs-FCS, the board cards FBS-vs-FBS only, so no chip exists and no join is
possible. **This is the only real miss.**

The schedule confirms it should match:

```
schedule row: Massachusetts @ Rutgers | classifications: fbs fbs
chip built  : MAS @ RUT               | away {name: "Massachusetts", abbr: "MAS"}
                                        home {name: "Rutgers",       abbr: "RUT"}

teams_match("ncaaf", "Rutgers",       "Rutgers Scarlet Knights") -> True
teams_match("ncaaf", "RUT",           "Rutgers Scarlet Knights") -> True
teams_match("ncaaf", "Massachusetts", "UMass Minutemen")         -> False
teams_match("ncaaf", "MAS",           "UMass Minutemen")         -> False
```

Home side resolves on both fields; away side on neither. No heuristic can bridge
`Massachusetts` ↔ `UMass` — it is a vocabulary fact.

## The registry rows

```
team_id 113  canonical "Massachusetts"    abbr "MASS"  school "Massachusetts"
             mascot "Minutemen"           aliases  mass|massachusetts|minutemen

team_id 379  canonical "UMass Dartmouth"  abbr "MAS"   school "UMass Dartmouth"
             mascot "Corsairs"            aliases  corsairs|mas|umass dartmouth
```

Team 113 carries no `umass` in any column, so
`unambiguous_team_index()`'s combined key is `massachusetts minutemen`, never
`umass minutemen`.

## Where it comes from

`scripts/build_ncaaf_team_registry_snapshot.py`
→ `syndicate/features/ncaaf/cfbd.py::write_team_registry_snapshot_csv`
→ `_registry_aliases()` (cfbd.py:475), which is CFBD's own `aliases` list plus
`school`, `name`, `mascot`, `nickname`, `abbreviation`.

**CFBD simply does not ship `UMass` for team 113.** So the CSV is faithful to its
source; the gap is that the source's vocabulary is narrower than OddsAPI's.

**Do NOT hand-edit the CSV** — it is a generated artifact and the next builder run
overwrites it.

---

## ⚠ THE TRAP I ALREADY FELL INTO — do not repeat it

**I tried fixing this in `team_aliases._alias_map("ncaaf")`, built the whole map
from `unambiguous_team_index()`, measured it, and REVERTED it.** Two reasons,
both measured:

1. **It does not fix this case.** With the map populated,
   `canonical_team("ncaaf", "UMass Minutemen")` still returned `None`, because
   the registry has no such key to derive one from. The map cannot invent
   vocabulary the registry lacks.
2. **It actively introduces a mis-resolution.** `canonical_team("ncaaf", "MAS")`
   → **`UMass Dartmouth`**, because `MAS` is team 379's real abbreviation and
   collides with the chip's synthetic abbr for Massachusetts
   (`_abbr("Massachusetts")` takes the first three letters). Populating the map
   makes `teams_match` **map-authoritative** — `team_aliases.py:640-644` returns
   the equality verdict and deliberately does NOT fall through to heuristics —
   so a mis-resolution stops being a harmless miss and becomes a confident wrong
   answer. `_basketball_alias_to_name`'s docstring records the same failure from
   the other direction ("worse than no answer").

Control taken after reverting: ncaaf alias map back to 0 keys, and the 8 pairs
from the 08-29 slate still match 8/8.

## Two routes that would work

- **A supplement, sport-scoped.** `team_aliases._WNBA_EXTRA_ALIASES` is the exact
  precedent and its comment explains the reasoning: two WNBA franchises were
  nickname-only, Polymarket named them by city, and the overlay lives in
  `team_aliases` specifically so it cannot reach a merged map and reassign
  another league's codes. An `_NCAAF_EXTRA_ALIASES` with `umass` /
  `umass minutemen` → `Massachusetts` is the same shape. **But note it only
  helps if the ncaaf map is populated at all**, which re-opens the `MAS` hazard
  above — so it likely needs the map restricted to FBS teams, or `MAS` excluded.
- **Widen the builder.** Add a local supplement inside `_registry_aliases()` so
  the generated CSV carries `umass` on team 113. Survives regeneration, keeps one
  source of truth, and benefits settlement's own joins — not just the board's.

I have no view on which you prefer; the second looks closer to your lane's
"authoritative vocabulary" principle, but it is your call and your file.

## How to verify a fix

```python
from syndicate.features.shared.team_aliases import teams_match
teams_match("ncaaf", "Massachusetts", "UMass Minutemen")   # must become True
teams_match("ncaaf", "MAS", "Idaho Vandals")               # must stay False
```

Then on production: `/api/board/layer2-shortlist?date=2026-08-29&limit=2000`,
NCAAF rows for kickoff date `2026-09-03` should go **2/20 → 6/20** (the UMass
game carries 4 rows). The other 14 are FCS visitors and must stay unmatched.

**Judge it only on a pool whose `written_at` is later than your deploy** — that
endpoint is a pure read of a worker-built artifact, and I nearly reported a
working fix as broken by checking a pool written 12 minutes before it.

## Context you may want

- `deploys.md` 2026-08-29 — the `teams_match` argument-order fix (`95c4fb12`),
  its per-sport blast-radius table, and why NCAAF was the only sport that showed
  it (`_alias_map` is empty for ncaaf, nhl and ncaab).
- `state.md [ncaaf-chip-grid-join]` — the residual breakdown this came from.
