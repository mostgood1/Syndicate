"""Can the NCAAF `clubs_unresolved` refusals be recovered WITHOUT an alias map?

MEASUREMENT ONLY. Changes nothing, wired into no path. Lane
`exchange-join-refusals`; the fix sites it informs (`venue_quote_adapters.py`,
`venue_quote_fanin.py`) are held by `live-venue-order-placement` and are not
touched.

--------------------------------------------------------------------------
ANSWER FIRST, MEASURED 2026-08-30 (n=25, the ops.py:609 cap, over a ~164-market population)
--------------------------------------------------------------------------

    canonical_team resolves both outcomes  (today's path) :  0/25    0.0%  STRUCTURAL
    H1  slug token pair -> registry teams                 :  2/25    8.0%  FALSIFIED
    H2  schedule-constrained mascot pair                  :  3-4/25  12-16%  SOUND, SMALL
    of the H2 misses: game not on our board at all        :  ~100%

**THE HEADLINE NUMBER 314 IS NOT A JOIN BACKLOG.** ~21 of 25 sampled Polymarket
NCAAF markets are games Syndicate does not card -- FCS/D-II/D-III matchups
(Campbell v East Tennessee St, VMI v Idaho St, Citadel v Wofford, Savannah St v
South Carolina St...). The registry is 247 D-III / 171 D-II / 128 FCS / 138 FBS
and the board cards FBS-vs-FBS. Polymarket simply lists far more college
football than this platform boards. **Those refusals are CORRECT and there is
nothing to recover in them.**

**STATE THE INTERVAL, NOT A POINT.** Pooled 7/50 = 14.0%, 95% Wilson
[7.0%, 26.2%] -> **~11-43 joinable markets** on a 164-market slate, point ~23.
The rate moved 16% -> 12% within an hour as the slate shrank 166 -> 163 with
games going final; four consecutive runs at one slate state were identical, so
that is drift, not run-to-run noise.

    ROBUST:     tens of markets, not hundreds. 314 is not a backlog.
    NOT ROBUST: any single point estimate. n=25 is a HARD CAP in ops.py:609.

--------------------------------------------------------------------------
H1 -- WHY THE SLUG TOKEN PAIR FAILS (it was the obvious fix; it does not work)
--------------------------------------------------------------------------

Polymarket's slug carries school tokens where the outcomes carry mascots:

    slug     aec-cfb-nmxst-flst-2026-08-29     outcomes ["Seminoles","Aggies"]

That LOOKS like the shape commit `a3386d6c` used for the other half of this
defect. It is not, because Polymarket's abbreviation vocabulary is not the
registry's:

    nmxst -> None     (registry has NMSU)      flst   -> None  (registry has FSU)
    sacst -> None                              emich  -> None  (registry has EMU)
    cita  -> None     woff -> None             morgst -> None
    ncat  -> '2448'   <- the one that happened to coincide

23 of 25 rows fail on the slug alone. **Same verdict as the reverted alias map:
the gap is upstream VOCABULARY, not a keying choice.** Recording the negative so
the next reader does not spend the afternoon rediscovering it.

--------------------------------------------------------------------------
H2 -- THE MECHANISM THAT DOES WORK, AND ITS SAFETY PROPERTY
--------------------------------------------------------------------------

Never resolve the NAME. Constrain by the SLATE:

  1. Take our own carded schedule for the slug's date.
  2. Resolve each scheduled team to a registry id (51/51 on 2026-08-29) and read
     its `mascot_name`.
  3. A Polymarket row joins iff its outcome mascot PAIR matches exactly one
     scheduled game's mascot pair.

Measured on 2026-08-29: **51 distinct mascot pairs from 51 games, 0 colliding**,
and 0 of 25 sampled rows resolved ambiguously. A mascot 25-way ambiguous across
684 teams ("Tigers") is unique inside a two-team pair on a given day. That is
what makes this safe where a global alias map is FORBIDDEN
(`learnings.md` 2026-08-29): ambiguity is refused per-row against a real slate
rather than pre-resolved into an authoritative map that flips `teams_match` from
"fall back" to "confident wrong answer".

**POSITIONAL ASSIGNMENT STAYS REFUSED.** Outcome array order does not follow
slug order -- reversed on 2 of the first 3 samples, and the adapter's own comment
records 1 of 5 on spread rows. H2 does not need order: it matches an unordered
PAIR, then takes each side's role from the SCHEDULE, which knows home from away.

--------------------------------------------------------------------------
FULL INPUT SET (enumerate before trusting a diff-based control)
--------------------------------------------------------------------------

    team_aliases.canonical_team("ncaaf", .)  CODE. `_alias_map` has NO ncaaf
                                             branch -- returns {} at line 505.
                                             No disk read, no data/ dependency.
                                             So the 0% is STRUCTURAL, not a
                                             sampling result.
    ncaaf_team_registry -> the CSV           data/, git-TRACKED, and
                                             `git diff origin/main` = 0 lines.
    polymarket_board_join.parse_slug         CODE, pure string parsing, no I/O.
    /api/ops/polymarket/slate                PRODUCTION.
    /ncaaf/api/cards                         PRODUCTION.

This list is why a diff against `origin/main` is a valid control here instead of
a clean worktree: every LOCAL input is enumerated and cleared. The enumeration is
the hard part -- miss one (a transitive import, an untracked `data/` file) and
you have proved something about the files you happened to think of. Where inputs
cannot be enumerated, use a clean worktree.

Reads `/api/ops/polymarket/slate`, which serves OUR OWN persisted artifact from
the keyvalue store (`/api/ops/artifacts/export` scans DISK and returns count 0
for it -- see `learnings.md` 2026-08-29 on that trap). It does NOT call the
Polymarket API; a second independent caller for one venue is a documented
incident class here.

    py -3 scripts/probe_polymarket_ncaaf_slug_role_join.py
    py -3 scripts/probe_polymarket_ncaaf_slug_role_join.py --date 2026-09-04
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import os
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from syndicate.features.shared.ncaaf_team_registry import (  # noqa: E402
    registry_path,
    resolve_ncaaf_team_id,
)
from syndicate.features.shared.polymarket_board_join import parse_slug  # noqa: E402
from syndicate.features.shared.team_aliases import canonical_team  # noqa: E402

DEFAULT_BASE = "https://syndicate-an21.onrender.com"


def _admin_token() -> str:
    token = os.environ.get("ADMIN_TOKEN")
    if token:
        return token.strip()
    env = Path(__file__).resolve().parents[1] / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("ADMIN_TOKEN"):
                return line.split("=", 1)[1].strip().strip("\"'")
    return ""


def _get(base: str, path: str) -> dict:
    req = urllib.request.Request(base + path, headers={"X-Admin-Token": _admin_token()})
    with urllib.request.urlopen(req, timeout=120) as handle:  # noqa: S310
        return json.loads(handle.read().decode("utf-8"))


def _registry_rows() -> list[dict]:
    path = registry_path()
    if path is None:
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _outcomes(raw: object) -> list[str]:
    if isinstance(raw, list):
        return [str(v) for v in raw]
    if isinstance(raw, str) and raw.strip():
        try:
            decoded = json.loads(raw)
        except (ValueError, TypeError):
            return []
        return [str(v) for v in decoded] if isinstance(decoded, list) else []
    return []


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default=DEFAULT_BASE)
    ap.add_argument("--date", default="2026-08-29")
    ap.add_argument("--league", default="ncaaf")
    ap.add_argument("--sport", default="ncaaf")
    args = ap.parse_args()

    rows = _registry_rows()
    mascot_by_id = {str(r["team_id"]): str(r.get("mascot_name") or "").strip().lower() for r in rows}
    # FBS ONLY, keyed by mascot -> the schools that could actually appear on a
    # board this platform cards. See the scope test at the bottom for why the
    # subdivision SET per mascot is the wrong index for that question.
    fbs_schools_by_mascot: dict[str, set[str]] = {}
    for r in rows:
        if str(r.get("subdivision") or "").strip().upper() != "FBS":
            continue
        fbs_schools_by_mascot.setdefault(
            str(r.get("mascot_name") or "").strip().lower(), set()
        ).add(str(r.get("school_name") or r.get("canonical_team_name") or ""))

    slate = _get(args.base_url, f"/api/ops/polymarket/slate?league={args.league}&market=h2h")
    samples = slate.get("samples") or []
    population = (slate.get("by_league_and_board_market") or {}).get(f"{args.league}|h2h")

    cards = _get(args.base_url, f"/{args.league}/api/cards?date={args.date}").get("games") or []

    # --- our own carded slate -> mascot pairs -------------------------------
    pair_index: dict[frozenset, list[tuple[str, str]]] = collections.defaultdict(list)
    unresolved_schedule = 0
    for game in cards:
        away = (game.get("away") or {}).get("name")
        home = (game.get("home") or {}).get("name")
        away_id, home_id = resolve_ncaaf_team_id(away), resolve_ncaaf_team_id(home)
        if not (away_id and home_id):
            unresolved_schedule += 1
            continue
        pair_index[frozenset({mascot_by_id.get(away_id, ""), mascot_by_id.get(home_id, "")})].append(
            (str(away), str(home))
        )
    colliding = sum(1 for v in pair_index.values() if len(v) > 1)

    print(
        f"[probe] slate age_s={slate.get('age_seconds')} population({args.league}|h2h)={population} "
        f"sampled={len(samples)}  (ops.py:609 caps samples at 25 -- a SAMPLE, not a census)"
    )
    print(
        f"[probe] carded schedule {args.date}: games={len(cards)} "
        f"resolved={len(cards) - unresolved_schedule} unresolved={unresolved_schedule} | "
        f"distinct mascot pairs={len(pair_index)} colliding={colliding}"
    )

    n = name_ok_n = h1_n = h2_n = 0
    out_of_scope = 0
    ambiguous = 0
    misses: list[str] = []

    for row in samples:
        parsed = parse_slug(str(row.get("slug") or "")) or {}
        if str(parsed.get("date") or "") != args.date:
            continue
        names = _outcomes(row.get("outcomes"))
        if not names:
            continue
        n += 1

        if all(canonical_team(args.sport, name) for name in names):
            name_ok_n += 1

        away_id = resolve_ncaaf_team_id(str(parsed.get("away") or ""))
        home_id = resolve_ncaaf_team_id(str(parsed.get("home") or ""))
        if away_id and home_id and away_id != home_id:
            h1_n += 1

        key = frozenset(name.strip().lower() for name in names)
        matched = pair_index.get(key, [])
        if len(matched) == 1:
            h2_n += 1
        elif len(matched) > 1:
            ambiguous += 1
            misses.append(f"AMBIG   {row.get('slug')} {names} -> {matched}")
        else:
            # NOT A JOIN FAILURE UNTIL PROVEN ONE.
            #
            # THE TEST IS PER-PAIR, NOT PER-MASCOT, and the difference is not
            # cosmetic. A first cut asked "is ANY school sharing either mascot
            # FBS?" and called Citadel v Wofford (both FCS) IN_SCOPE, because
            # "Bulldogs" is also Georgia's. That over-reported in-scope misses
            # 15x -- 28.6% against a true 0%. Mascot sharing is exactly the
            # ambiguity this whole probe exists to respect; a scope test that
            # leaks across it is the same category error as the alias map.
            #
            # Correct test: could this mascot pair be an FBS-vs-FBS fixture at
            # all? Only if mascot A names some FBS school AND mascot B names a
            # DIFFERENT FBS school. If not, we would never card it and the
            # refusal is right.
            first, second = names[0].strip().lower(), names[-1].strip().lower()
            fbs_first = fbs_schools_by_mascot.get(first, set())
            fbs_second = fbs_schools_by_mascot.get(second, set())
            could_be_fbs = bool(fbs_first and fbs_second and (fbs_first | fbs_second) - (fbs_first & fbs_second))
            scope = "IN_SCOPE_MISS" if could_be_fbs else "OUT_OF_SCOPE"
            if not could_be_fbs:
                out_of_scope += 1
            misses.append(
                f"{scope:13s} {row.get('slug')} {names} "
                f"fbs_candidates={sorted(fbs_first)[:2]}/{sorted(fbs_second)[:2]}"
            )

    if not n:
        print(f"[probe] NO ROWS for date={args.date}. Nothing measured -- not a negative result.")
        return 2

    def rate(x: int) -> str:
        return f"{x}/{n} = {100.0 * x / n:5.1f}%"

    unmatched = n - h2_n - ambiguous
    print()
    print(f"[probe] RESULT  n={n} polymarket {args.league} h2h rows dated {args.date}")
    print(f"  today's path: canonical_team resolves both  : {rate(name_ok_n)}")
    print(f"  H1  slug token pair -> registry teams       : {rate(h1_n)}")
    print(f"  H2  schedule-constrained mascot pair        : {rate(h2_n)}")
    print(f"      ambiguous (>1 carded game)              : {rate(ambiguous)}")
    print(f"      unmatched                               : {rate(unmatched)}")
    if unmatched:
        print(
            f"        PROVABLY out of scope (no FBS pair) : "
            f"{out_of_scope}/{unmatched} = {100.0 * out_of_scope / unmatched:5.1f}%  "
            f"<- correct refusals, nothing to recover"
        )
        print(
            f"        scope UNDETERMINED                  : "
            f"{unmatched - out_of_scope}/{unmatched}  "
            f"<- UPPER BOUND on recoverable, not an estimate"
        )
        print(
            "        (a mascot pair that COULD be FBS is not an FBS game. "
            "Savannah St v South Carolina St reads as Auburn v Georgia to this\n"
            "         test because the slug tokens do not resolve -- see H1. "
            "Every undetermined row inspected 2026-08-30 was in fact FCS.)"
        )
    if misses:
        print(f"\n[probe] rows H2 does not join ({len(misses)}):")
        for line in misses[:20]:
            print("   ", line)
    print(
        f"\n[probe] DENOMINATOR: population is {population} markets; this is a "
        f"{len(samples)}-row sample. Scale the RATE, never the count. "
        f"At {100.0 * h2_n / n:.0f}% that is ~{round(population * h2_n / n)} joinable markets, "
        f"NOT the 314 the clubs_unresolved counter reports."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
