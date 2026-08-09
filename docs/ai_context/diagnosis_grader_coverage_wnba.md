# Why the graders produce almost no rows — the WNBA chain, measured

Written 2026-08-09. **Read-only diagnosis. No code changed, no production writes,
no deploys.** Evidence markers follow `betting_contract_lifecycle.md`: `[live]`
observed in production at a stated instant, `[structural]` proven from code,
`[asserted]` taken from another lane.

Provenance for every `[live]` figure below: **web `syndicate-an21`
(`srv-d88ahvrbc2fs73eodu30`) and refresh-worker (`srv-d91dpertqb8s73co8ls0`),
both live on commit `27a7e9df`, deployed 2026-08-09T16:41Z, `trigger=api`**.
Measured 2026-08-09 between 19:05Z and 19:35Z.

---

## 0. Headline

**The deployed WNBA fix `17d4f203` is running in production and is inert.** It is
not an undeployed fix. Its central claim — *"the root-order fix ALONE is
sufficient"* — is refuted by live measurement, and the mechanism is the one the
brief predicted: `any(candidate.iterdir())` asks *"does this directory contain
anything"*, not *"does it contain the artifact asked for."*

And behind it sits a second, independent blocker that no diagnostic in this repo
can currently see.

---

## 1. The fix is deployed. Proven, not assumed.

```
git merge-base --is-ancestor 17d4f203 27a7e9df   ->  true
web             live  2026-08-09T16:41:43Z  trigger=api  commit=27a7e9df
refresh-worker  live  2026-08-09T16:41:10Z  trigger=api  commit=27a7e9df
```

This matters because "WNBA: 0 — DEFECT, fixed by `17d4f203`, **not deployed**"
is what `betting_contract_lifecycle.md` §7 records, and acting on it would mean
scheduling a deploy that changes nothing.

## 2. And it still resolves to the wrong root

`[live]` `GET /api/ops/wnba/artifact-counts?date=2026-08-08`:

```
processed_root  -> /opt/render/project/data/wnba_source/source_artifacts/data/processed   (root1)
candidate_roots -> [ root1, /opt/render/project/data/wnba_source/data/processed (root2) ]

                                        root1    root2
game_cards_2026-08-08.csv               False    True
props_recommendations_2026-08-08.csv    False    True
recommendations_slate_2026-08-08.json   False    True
props_recommendations_top_by_game_...   False    True
props_edges_2026-08-08.csv              False    False
props_predictions_2026-08-08.csv        False    False
```

### Why the fix cannot change this

`[live]` `GET /api/ops/artifacts/export?names_only=1&pattern=*wnba_source/source_artifacts/data/processed/*`

```
root1  427 files   game_cards 43 · props_recommendations 43 · recommendations 36
                   oddsapi_player_props 45 · recommendations_slate 39 · smart_sim ...
root2  552 files
```

**root1 holds 427 files.** `any(candidate.iterdir())` short-circuits `True` on the
first candidate, the loop returns `candidates[0]`, and the behaviour is
byte-identical to the pre-fix `roots[0]`.

**This conclusion does not depend on deploy state.** With root1 non-empty the fix
is a no-op whether or not it is running — which is why §1 is stated separately:
the deploy fact kills the "just deploy it" action, the file count kills the fix
itself.

Reproduced locally against the same code path (a claim about the *code*, not
about production data):

```
any(iterdir)=True  entries=520  ...\wnba_source\source_artifacts\data\processed
any(iterdir)=True  entries=350  ...\wnba_source\data\processed
processed_root() == candidates[0]  ->  True
```

root1 is not merely non-empty, it is **stale and partial**: 43 `game_cards_*`,
none of them for 08-08. `WNBA_LIVE_LENS_DIR` points into root1, so it keeps
receiving writes and will never empty.

## 3. The actual root cause: producer and consumer read different roots from the same env

Live env-vars, **identical on web and refresh-worker** `[live]`:

```
SYNDICATE_DATA_ROOT        = /opt/render/project/data
SYNDICATE_WNBA_SOURCE_ROOT = /opt/render/project/data/wnba_source
WNBA_BETTING_DATA_ROOT     = /opt/render/project/data/wnba_source/data
WNBA_LIVE_LENS_DIR         = /opt/render/project/data/wnba_source/source_artifacts/data/live_lens
```

| | resolver | resolves to |
|---|---|---|
| **PRODUCER** | `refresh_odds_sources._local_source_artifact_root("wnba")` → `SYNDICATE_DATA_ROOT/wnba_source`, then `refresh_wnba_oddsapi_props` writes `artifact_root/data/processed` | **root2** |
| **CONSUMER** | `graded_outcomes._wnba_graded_rows_for_date` → `wnba.sources.processed_root()` → `current_odds_root_for_sport("wnba")` → `preferred_artifact_roots(...)[0]` | **root1** |

`SYNDICATE_WNBA_SOURCE_ROOT`'s basename is `wnba_source`, not `source_artifacts`,
so `preferred_artifact_roots` appends `<root>/source_artifacts` **first** and
`<root>` second — exactly the observed `candidate_roots` order.

### This is WNBA-only, and the reason is one function choice

`current_odds_root_for_sport` uses **`preferred_artifact_roots` for wnba** and
**`preferred_source_roots` for nba and nhl**. Only `preferred_artifact_roots`
injects a `source_artifacts` variant. `preferred_source_roots` returns
`<data_root>/<sport>_source` directly — which is where the producer writes.

**So NBA and NHL are correct by construction, and WNBA is the one sport whose
grader root diverges from its producer root.** `17d4f203` was right to scope
itself to WNBA; it was wrong about why.

### Confirmed on the surface that consumes the output

`[live]` `GET /wnba/api/market-accuracy?date=`:

```
2026-08-05   games.available False   props.available False
2026-08-06   games.available False   props.available False
2026-08-08   games.available False   props.available False
```

That is the `{"available": False}` early return in `_score_market_{games,props}_day`
— i.e. **0 graded rows** — and it matches the settler's own
`graded_rows_available: wnba:2026-08-05 = 0, wnba:2026-08-06 = 0`.

### A different lane found this eight days ago and worked around it

`wnba/cards.py:3878` `[code]`:

> *"Found live 2026-08-01: `processed_root()` (`current_odds_root_for_sport`)
> always prefers the `source_artifacts` candidate root whether or not that
> location actually has anything written to it ... `refresh_wnba_oddsapi_props.py`'s
> own `--artifact-root` can legitimately resolve to the OTHER candidate root."*

And `cards.py:382`, `_game_cards_keyvalue_path`, **hardcodes root2** as *"the
canonical path the refresh pipeline actually writes through ... independent of
whichever local candidate root `processed_root()` happens to resolve to."*

**Every WNBA consumer that mattered enough to be debugged has hand-rolled its own
workaround. The grader is the one that never got one, so it is the one that reads
zero.**

## 4. The second blocker — fixing the root alone still settles 0

The WNBA grader needs **four** files in **two gated pairs**
(`live_lens_local.py:347` and `:480`):

```
games:  recommendations_{d}.csv  (or recommendations_sim_{d}.csv)  AND  recon_games_{d}.csv
props:  props_recommendations_{d}.csv                              AND  recon_props_{d}.csv

either side of a pair missing  ->  {"available": False}  ->  0 rows
```

`recon_games_*` / `recon_props_*` are built by
`refresh_wnba_oddsapi_props._build_local_recon_{games,props}_artifact`, and both
return `(0, None)` unless **`boxscores_{date}.csv`** is present at the same
`processed_root`.

**Consequence for sequencing: a root fix alone is not testable as a success.** If
grading still reads zero afterwards, that is the recon dependency, not a failed
fix.

## 5. The instrument problem — this is the part worth generalizing

**`/api/ops/wnba/artifact-counts`, the endpoint built specifically to diagnose
this defect, does not measure the grader's inputs.** It checks six files:

```
game_cards · props_edges · props_predictions · props_recommendations
props_recommendations_top_by_game · recommendations_slate
```

Of those, **exactly one (`props_recommendations`) is a grader input**, and **both
recon files are absent from the list entirely**. The "0 of 6 families" figure that
`17d4f203` rests on is a true measurement of the wrong six files.

This also corrects a premise carried into this lane: `props_edges` and
`props_predictions` are indeed absent at both roots `[live]`, **but neither is a
grader input** — the grader never reads them. Their absence does not affect
grading.

Compounding it: `recon_games_*`, `recon_props_*` and dated `boxscores_*` are
**not in `HOT_ARTIFACT_PATTERNS`** (only the undated `boxscores_history.csv` is).
So they can never cross services and can never be inventoried from web.

> **An export query returning nothing for them is an allowlist artifact, not
> evidence of absence.** This document does not claim they are missing.

### Dead guard

`source_roots.py` defines `_has_files()` **twice** — line 25 inside
`preferred_source_roots`, line 88 inside `preferred_artifact_roots` — and
**calls it in neither.** Two dead helpers that look exactly like the
populated-root guard every reader assumes is already there. That is plausibly why
`17d4f203` reached for `any(iterdir())`: it reimplemented a helper that was
already present, already unused, and already the wrong test.

## 6. Reconciling the platform-wide numbers — the denominator is not stated

`[live]` `GET /api/ops/evaluation-settlement/status`, autorun epoch
**2026-08-06T11:03:17Z — three days stale**:

```
total_recommendation_records  8,276    matched 0   settled 0
  unmatched_no_graded_rows    3,716
  unmatched_no_key_match      4,560
  unmatched_unsupported_sport     0
  unmatched_bad_result            0
  already_resolved_records        0

dates: 21  (2026-07-17 .. 2026-08-06)
graded_rows_available: 8 entries, all on 2026-08-05 / 2026-08-06
  mlb:2026-08-05 {mlb: 1}   <- the only non-zero
  mlb:08-06, nfl:08-05/06, soccer:08-05/06, wnba:08-05/06  all 0
```

Three things follow that the aggregate hides:

1. **3,716 + 4,560 = 8,276 exactly.** No record was dropped as legacy-unsettleable
   or unsupported-sport. **Every record reached the grader lookup**, so the
   failure is entirely in grader coverage and key matching — nothing upstream.

2. **`graded_rows_available` is emitted only `if r.get("graded_rows_available")`**
   (`evaluation_settlement.py:686`), a truthiness filter on a dict. A call whose
   `graded_rows_by_sport` stayed `{}` is **omitted, not reported as zero**. So the
   8 shown pairs are not the denominator; 21 dates × 8 supported sports is the
   space, and **19 of 21 dates contributed no entry at all.** *An absent entry and
   a not-attempted one render identically* — the same defect this repo keeps
   paying for, now inside the one instrument built to separate the zeros.

3. **All 8,276 pending records sit in the 08-05 and 08-06 chunks.** Since only
   `mlb:2026-08-05` has a non-empty pool, the 4,560 `no_key_match` records are
   MLB-on-08-05 tested against a candidate pool of **exactly one row** — and that
   row is a `moneyline`, which `_markets_compatible` rejects for every prop
   record. **The matcher work is real and currently unvalidatable, exactly as
   briefed.**

## 7. What was NOT measured, and the experiment that closes it

- **Whether `recon_games_*` / `recon_props_*` / `boxscores_<date>.csv` exist on
  refresh-worker's root2.** Unreachable from web — allowlist-scoped, §5. My local
  checkout has 0 recon files and 41 `boxscores_*`, and **that is worthless as
  evidence**: the git mirror is fed by the same allowlist-scoped export, so
  recon absence there is expected either way.
  **Closing it:** add `*_source/data/processed/recon_{games,props}_*.csv` and
  `*_source/data/processed/boxscores_*.csv` to `HOT_ARTIFACT_PATTERNS` as a
  *diagnostic*, then re-run the `names_only=1` inventory. Allowlisting permits a
  transfer, it does not make one happen (`#208`).
- **Whether soccer's 385 graded rows `[asserted]` (07-19..08-08) can be
  reconciled with `soccer:2026-08-05 = 0` and `soccer:2026-08-06 = 0` `[live]`.**
  Both dates are inside that window. Not investigated — the soccer grader path is
  the settlement lane's.
- **Any WNBA date outside 08-05/08-06/08-08.** Three dates, one hour.
- **Whether the WNBA producer step ran at all on those dates.**
  `refresh_odds_sources._run_command` discards a successful step's stdout
  (`ops.py:1750`), so this is not observable from logs.

## 8. Proposed order — not taken, needs an owner's decision

1. **Root resolution.** Make WNBA's grader root match its producer root. The
   cheap, sibling-consistent option is to use `preferred_source_roots` as nba/nhl
   already do (§3). The thorough option is per-requested-file resolution, which
   `wnba/sources.py::_strict_artifact_path` already implements correctly.
   **Blast radius is not small:** `processed_root()` has ~20 consumers across
   `wnba/cards.py`, and the grader takes a single `root` argument
   (`build_local_market_accuracy_payload(qs, root)`), so per-file resolution is a
   signature change, not a one-liner. Several of those consumers already carry
   hand-rolled workarounds (§3) that would need re-checking, not just leaving.
2. **Then** the recon question becomes answerable: with the root correct,
   `available: false` is attributable to recon absence rather than to the wrong
   directory.
3. **Separately, and cheaply:** fix `artifact-counts` to check the grader's actual
   inputs, and delete or wire up the two dead `_has_files` helpers.

**Deploy-readiness: nothing to deploy.** The deployed fix is inert; a real fix is
not yet written.
