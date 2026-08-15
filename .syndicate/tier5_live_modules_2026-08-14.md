# TIER 5 / Deliverable 1 — the `live`-named modules, read one by one

Read 2026-08-14 21:3x–22:0x CDT (2026-08-15 02:3xZ). Read-only; no lane opened,
no file edited, nothing deployed.

**Deployed commits at the moment of the read** (re-read in the same step, per
`state.md`'s own rule — they moved three times in 35 minutes on 08-14):

| service | live commit | deployed |
|---|---|---|
| web `srv-d88ahvrbc2fs73eodu30` | `a86eb4ed` | 2026-08-15T01:41:43Z |
| refresh-worker `srv-d91dpertqb8s73co8ls0` | `548ded38` | 2026-08-15T02:29:39Z |
| live-odds-worker `srv-d91dpertqb8s73co8lt0` | `ccd10349` | 2026-08-14T19:24:01Z |

---

## Scope correction: the count is 30, not 16

The plan says "16 are named `live`". Under the app tree
(`syndicate/**`, excluding `tests/`, `vendor/`, `scripts/`, `data/`), the count
of modules whose **basename** contains `live` is **30**. Including `scripts/`
adds 6 more; `tests/` adds 41; `vendor/` adds 47. No definition I could
construct yields 16, so I read all 30 rather than guess which subset was meant.
The read is still bounded and the conclusion does not turn on the count.

Importers below are **AST-resolved**, not grepped — a basename grep for
`live_lens` collides across eight sports and gives the wrong answer.

---

## The three verdicts, and what they mean

- **SEVERED** — wired end to end, runs in production, output is read, and the
  product outcome is nonetheless zero because one identified link drops it.
  Not scaffolding (nothing is awaiting a projection that doesn't exist) and not
  abandoned (it runs on every board build).
- **REQUEST-ONLY** — reachable solely from a Flask route. Costs nothing in the
  background; costs one page render when someone opens it. Not a compute
  liability under any reading.
- **UNWIRED** / **DEAD** — nothing on a production path reaches it.

---

## The table

| # | module | app importers (AST) | on a production compute path? | does anything read its output? | verdict |
|---|---|---|---|---|---|
| 1 | `shared/live_refresh_loop.py` | 7 — `s.app`, `pipeline.intelligence_state`, `blueprints.ops`, `features.intelligence`, `shared.recommendation_engine`, both worker entrypoints | **YES** — `SYNDICATE_ENABLE_LIVE_ODDS_REFRESH_LOOP=true` on live-odds-worker; it fired the 02:35:20Z tick | yes — every quote on the board | **LIVE, load-bearing.** This is the odds engine. |
| 2 | `shared/live_lens_loop.py` | 2 — `run_refresh_worker`, `run_live_odds_refresh_worker` | **YES** — `SYNDICATE_ENABLE_LIVE_LENS_LOOP=true` on *both* workers | yes — writes `live/<sport>_live_lens.json`, which the board reads | **LIVE.** Produces the snapshot. |
| 3 | `shared/live_projection_join.py` | 1 — `shared/board_enrichment` → `shared/book_grid_artifact:238` | **YES** — runs on every book-grid build | yes — publishes `live_projections` into the artifact | **SEVERED.** See §A. |
| 4 | `mlb/live_lens.py` | 6 — `live_lens_loop`, `blueprints.mlb`, `blueprints.home`, `mlb.cards`, `scripts.refresh_mlb_oddsapi`, `utils.mlb_debug` | **YES** — the loop's MLB tick | yes — the snapshot the join reads (148 rows at read time) | **SEVERED.** See §A. |
| 5 | `shared/live_edge_policy.py` | 3 — `shared.prop_projections`, `shared.soccer_projections`, `shared.wnba_projections` | **YES** — on every projection attach for those three | yes — measured: 58 MLB live rows carrying its exact reason string | **LIVE — with a measured hole.** See §B. |
| 6 | `shared/live_lens_contract.py` | 8 — every per-sport `live_lens` | YES (transitively) | yes | **LIVE.** The one piece of genuine cross-sport convergence here. |
| 7 | `nfl/live_game_state.py` | 1 — `nfl.preseason_cards` | **YES** — NFL preseason cards are on the board; live NFL rows carried `Q4 4:53` at read time | yes — the board's NFL game-state labels | **LIVE — and its label is not consumed by any edge guard.** See §B. |
| 8 | `shared/basketball_live_artifacts.py` | 3 — `nba.cards`, `wnba.cards`, `scripts.refresh_wnba_oddsapi_props` | **YES** for WNBA (in season; 6 WNBA rows on the shortlist) | yes | **LIVE.** |
| 9 | `nfl/live_lens.py` | 3 — `live_lens_loop`, `blueprints.nfl`, `blueprints.home` | **YES** — in the loop's sport list | its own page reads the snapshot back; **no board consumer**, and see §D — the snapshot never reaches web | **SCAFFOLDING + a publish gap.** |
| 10 | `nba/live_lens.py` | 3 — `live_lens_loop`, `blueprints.nba`, `nba.cards` | in the loop, but NBA is out of season → no live games → no work | own page only | **SCAFFOLDING** (dormant, near-zero cost now). |
| 11 | `wnba/live_lens.py` | 2 — `live_lens_loop`, `blueprints.wnba` | **YES** — in the loop, WNBA in season | own page only; published to web | **SCAFFOLDING.** |
| 12 | `soccer/live_lens.py` | 2 — `live_lens_loop`, `blueprints.soccer` | **YES** — in the loop, soccer in season | own page only; see §D | **SCAFFOLDING + a publish gap.** This is the *page* module (reads `live_state_payload`), not the projector — see #13. |
| 13 | `soccer/features/live_lens.py` | 3 — `soccer.features.__init__`, `scripts.backtest_soccer_live_lens`, `scripts.poll_soccer_live_state` | **NO** — neither script is scheduled anywhere (no cron, no `render.yaml`, no worker import). `docs/reports/soccersim_phase1_build_report.md:1028` says the poller "has never been run" | nothing | **UNWIRED — and it is the most important line in this table.** See §C. |
| 14 | `soccer/ingestion/espn_live_state.py` | 3 — same two scripts + package `__init__` | **NO** — same | nothing | **UNWIRED.** #13's input half. |
| 15 | `shared/live_lens_local.py` | 13 — the accuracy modules, `shared.graded_outcomes`, three `market_accuracy` | request paths only; `graded_outcomes` reaches `evaluation_settlement`, whose autorun is `false` on refresh-worker and absent elsewhere | yes, on request | **REQUEST-ONLY.** |
| 16 | `ncaab/live_lens.py` | 2 — `blueprints.ncaab`, `blueprints.home` | **NO** — not in `live_lens_loop`'s sport list | on request | **REQUEST-ONLY** (out of season). |
| 17 | `ncaaf/live_lens.py` | 2 — `blueprints.ncaaf`, `blueprints.home` | **NO** — not in the loop | on request | **REQUEST-ONLY.** |
| 18 | `nhl/live_lens.py` | 1 — `blueprints.nhl` | **NO** — not in the loop | on request | **REQUEST-ONLY** (out of season). |
| 19 | `mlb/live_lens_daily_accuracy.py` | 1 — `blueprints.mlb` (`mlb/live_lens_daily_accuracy.html` + API) | no | on request | **REQUEST-ONLY.** |
| 20 | `nba/live_lens_daily_accuracy.py` | 1 — `blueprints.nba` | no | on request | **REQUEST-ONLY.** |
| 21 | `nba/live_game_accuracy.py` | 1 — `blueprints.nba` | no | on request | **REQUEST-ONLY.** |
| 22 | `nba/live_prop_accuracy.py` | 1 — `blueprints.nba` | no | on request | **REQUEST-ONLY.** |
| 23 | `nba/live_prop_audit.py` | 1 — `blueprints.nba` | no | on request | **REQUEST-ONLY.** |
| 24 | `nhl/live_game_accuracy.py` | 1 — `blueprints.nhl` | no | on request | **REQUEST-ONLY.** |
| 25 | `nhl/live_lens_daily_accuracy.py` | 1 — `blueprints.nhl` | no | on request | **REQUEST-ONLY.** |
| 26 | `wnba/live_game_accuracy.py` | 1 — `blueprints.wnba` | no | on request | **REQUEST-ONLY.** |
| 27 | `wnba/live_lens_daily_accuracy.py` | 1 — `blueprints.wnba` | no | on request | **REQUEST-ONLY.** |
| 28 | `wnba/live_prop_accuracy.py` | 1 — `blueprints.wnba` | no | on request | **REQUEST-ONLY.** |
| 29 | `wnba/live_prop_audit.py` | 1 — `blueprints.wnba` | no | on request | **REQUEST-ONLY.** |
| 30 | `features/live_ui_audit.py` | **0** — no importer in `syndicate/`, `pipeline/`, `scripts/`, `app.py`, or `tests/` | no | nothing | **DEAD.** An `argparse` CLI parked in `features/`. Only unambiguous deletion candidate in the set. |

**Tally: 1 dead, 2 unwired, 11 request-only, 5 live, 4 scaffolding, 2 severed,
5 live-with-a-hole/label-only.** Nothing here is an "abandoned approach still
costing compute" in the sense the plan feared. The compute is in items 1–4 and
9–12, and all of it runs on purpose.

---

## §A — the severed link, and the exact line

The premise "`rows_live_edged` has been 0 on every build" is **true and I
reproduced it**, from the board artifact's own counters
(`mlb_source/data/book_grid/book_grid_2026-08-14.json`, `generated_at`
02:41:58Z, pulled via `/api/ops/artifacts/stream`):

```
rows_live_considered      989
rows_live_projected        86
rows_live_edged             0
rows_live_edge_withheld    86
live_games_in_snapshot      5
snapshot_rows_seen        148
snapshot_live_prob_seen     0     <-- the whole story
snapshot_by_game_state.live = {rows: 135, with_live_projection: 93, with_live_prob: 0}
miss_no_market_alias      903
```

Two independent blockers, both measured:

**1. The snapshot carries no live probability at all.** 93 live rows have a
`liveProjection` (a mean); **0** have `liveModelProbOver`. `live_projection_join`
prices `liveModelProbOver` *and nothing else*, deliberately (`#414`: falling back
to `modelProbOver` is what put a pregame number on a live label and produced
+36.5% edges on props that had already won). So the join withholds all 86 and
says so. **The join is behaving correctly. Its input is empty.**

**Why the input is empty — `syndicate/features/mlb/live_lens.py:1105-1118`:**

```python
# Props: cards stay the reliable primary source (#124 follow-up (a)) --
# never overwritten here -- but if the card artifact genuinely has none
# for this game while the projection report does, fill the gap ...
if not (enhanced.get("liveProps") or enhanced.get("props") or enhanced.get("trackedProps")):
    ...  # only here do the MC rows get used
```

The 120-sim Monte Carlo payload is merged in by
`_enhance_card_row_with_live_projection`, and its props are used **only when the
cards artifact produced none**. In the normal case the cards artifact has props,
so the MC props — the only rows that can carry `liveModelProbOver` — are
discarded. What survives is the cards path's own
`_bounded_live_pitcher_projection` (`mlb/cards.py:3441`), a deterministic
interpolation of the pregame mean by game progress. It yields a mean and no
probability, which is exactly what the counters show.

**So `#414` is deployed and inert.** Its output lands in the payload that
line 1109 throws away. This is the `presence ≠ reachability` /
`test the fix's predicate` pattern again, and I did not confirm the MC even
runs on the worker — I did not need to, because **the finding holds either
way**: if it runs, its props are dropped here; if it doesn't, there is no
second source of `liveModelProbOver`. Both roads end at 0.

**2. The market alias table misses 903 of 989 live rows (91%).** Unmatched
samples the join itself recorded: `outs` (tried `outs`, `pitcher_outs`),
`batter_total_bases` (tried `batter_total_bases`, `total_bases`, `tb`). Even
with a live probability, coverage would cap near 9% until this is fixed.

Fixing (1) alone gets live edges onto ~86 rows. Fixing (1) and (2) gets to ~989.
Neither is a new model.

---

## §B — the asymmetry is not pregame-vs-live, it is MLB-vs-NFL

**The premise "zero live edges published" is FALSE as of this read, and what is
published is wrong.** From the served Layer 2 shortlist
(`/api/board/layer2-shortlist`, `server_time` 02:37:04Z), 105 rows:

- 51 rows `market_state: live` — the live tier is **not** dark
- **5 of them carry a `model_edge_pct`**, all NFL, all `basis:
  smartsim2_total_normal`, on games at `Q4 4:53` and `Q4 2:52`
- edges of `+2.70`, `+2.47`, `−2.47`, `−4.53`, `−7.03`, against full-game
  totals of 34.5–39.5 — i.e. a **pregame full-game projection priced against a
  market that has already seen 55 minutes of football**
- the other 46 live rows are correctly blank, 31 of them carrying
  `live_edge_policy`'s exact string: *"game is live: a pregame projection cannot
  be priced against a live market"*

**Cause:** `shared/live_edge_policy.py` is imported by `prop_projections`,
`soccer_projections` and `wnba_projections`. It is **not** imported by
`shared/nfl_game_projections.py`, which has no `market_state` guard of any kind
(it suppresses on skill and on `margin_mean`, never on liveness). Its own
docstring predicted this exact failure for a different sport:

> "This existed in `prop_projections.py` and was copied into
> `soccer_projections.py`, and WNBA never got it — so on 2026-08-10 a live WNBA
> game served 128 of 128 projected rows with an `edge_vs_line` … Two sports,
> opposite answers to the same question, on the same board."

The rule was then centralised so "every sport's projection attach can depend on
it". NFL's still doesn't. And these rows **rank** — `ev_pct` up to 2.65 seats
them on a 105-row shortlist, which is the specific harm the policy exists to
prevent.

This is a one-import fix in a file no OPEN lane claims. I did not make it —
this session is read-only by instruction — but it is the highest
value-per-line item Tier 5 surfaced.

---

## §C — a live game-line projector already exists, in soccer, unwired

`soccer/features/live_lens.py` exports `project_live_match`,
`goal_in_window_probability` and `project_live_player_props`, built on
`match_simulator.simulate_match`'s `initial_state` hook — *"project a match
forward from any current state … resumed from any half/clock/score instead of
always starting at kickoff"* — fed by `soccer/ingestion/espn_live_state.py`.

That is a working reference implementation of the thing Tier 5 says does not
exist. It is reachable only from `scripts/backtest_soccer_live_lens.py` and
`scripts/poll_soccer_live_state.py`, **neither of which is scheduled** — no
cron, no `render.yaml` entry, no worker import; and the soccersim phase-1 report
records the poller as never having been run.

It is therefore costing **zero** compute, and it materially changes the price of
option 1 in the product decision: "build the live game-line projection" is not a
green-field build in at least one sport.

---

## §D — two of the five live-lens sports never cross to web

`live_lens_loop.py:150` builds five sports:

```python
_LIVE_LENS_SPORTS: tuple[str, ...] = ("mlb", "nba", "wnba", "soccer", "nfl")
```

`artifact_publisher.py:433-435` allowlists three:

```python
"live/mlb_live_lens.json",
"live/nba_live_lens.json",
"live/wnba_live_lens.json",
```

**`live/nfl_live_lens.json` and `live/soccer_live_lens.json` are built on
live-odds-worker every tick and never published.** The same publisher block
already carries a written post-mortem of exactly this bug for the three that
*are* listed — *"None of these three paths were ever in this allowlist, so that
periodic push always skipped them (SKIP_NOT_ALLOWLISTED) — not a keyvalue-size
failure like `#43`/`#112`, just a plain missing entry"* — and records what the
fallback costs: web's own recompute had real prop rows while refresh-worker's
had `prop_row_counts=[0]*9` across nine live games.

The two omitted sports are **NFL and soccer**, both in season. NBA, which is
allowlisted, is out of season. So the fix landed on the three sports that were
being looked at and the same defect is still live on the two that were not.

Two lines in the allowlist. It does not need the product decision.

---

## What this changes in the plan

1. **"16 modules"** → 30 under the app tree; correct the figure.
2. **"zero live edges ever published"** → false. 5 are published right now, all
   NFL, all structurally wrong. Re-verify before quoting (this is the plan's own
   rule from the *Corrections* section, applied to the plan).
3. **"scaffolding vs abandoned"** → neither is the right frame for the core
   path. It is a complete pipeline severed at `mlb/live_lens.py:1109`, plus a
   91% alias miss.
4. **`live_ui_audit.py`** is the only clean deletion.
5. `soccer/features/live_lens.py` should be named in the product decision as an
   existing asset, not discovered after it is taken.
