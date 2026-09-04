<!-- HANDOFF: todo.md entry for `#646`, written by lane mlb-hitter-so-dead-field 2026-09-04.
     NOT applied: docs/ai_context/todo.md is claimed by OPEN lane accuracy-ledger-budget-raise
     (session 82fe0160), so I stopped rather than edit across lanes -- the same courtesy that
     lane's own block extends. Nothing of theirs was touched.
     TO APPLY: paste the block below into docs/ai_context/todo.md immediately above `#645`.
     The id 646 is ALLOCATED and claimed (.syndicate/todo_ids/646.claim); it will not be reused. -->

### `#646` — **MLB hitter `strikeouts` was a DEAD FIELD on the served board. Fixed and landed, NOT DEPLOYED — the deploy is the whole remaining item** — lane `mlb-hitter-so-dead-field`, 2026-09-04 — **LANDED `0b9a03e7`; DEPLOY + READING OWED**

`_HITTER_PROP_DIST_SPECS` names row_key `"SO"`; the per-sim `hitter_stat_values`
dict — duplicated at `vendor/mlb_bettingv2/tools/daily_update.py:709`
(`_simw_chunk`) and `:4429` (`_sim_many`) — never set it. The read is
`.get(row_key, 0)`, so `strikeouts_dist` was `{0: n_sims}` and `so_mean` `0.0`
for EVERY hitter of EVERY game, permanently, with passing tests and no log line.
Fixed at both sites; `so` was already in scope and already going to `_inc_sum`.

**Confirmed on the SERVED production payload 2026-09-04** (artifact
16:27:56-05:00): `/mlb/api/hitter-ladders?prop=hitter_strikeouts` reads
`mean 0.0 / mode 0 / modeProb 1.0 / maxTotal 0`, ONE rung
`{total: 0, exactProb: 1.0}`. Control, same player, `prop=hits`: `mean 1.252`,
6 rungs, `marketLine 0.5`.

**Severity — no money was ever at risk, and that is an ACCIDENT, not a guard.**
`batter_strikeouts` is requested and paid for (7 keys in `meta.markets` of
`oddsapi_hitter_props_2026_09_04.json`) but the feed returns SIX: **0 of 289
players** carry it, against 270-283 for the other six. So the ladder join found
no line and nothing was priceable. If those quotes ever arrive, P(0 K)=1.000
prices a 100%-confidence UNDER against a real 0.5 line.
`syndicate/features/shared/probability_refusal.py` would refuse `p=0.0` —
**NOT VERIFIED to be applied on the MLB ladder path; that check is part of this
item.**

**WHAT IS OWED:**
- **(a) Deploy refresh-worker.** Both locks (`deploy_claim.py` +
  `deploy_preflight.py`, CLEAR <15 min, commit on `origin/main`). Not taken this
  session: another lane was mid-deploy on this fleet on 2026-09-04.
- **(b) A ROSTER/SIM REBUILD, not just a deploy.** The sim writes these dists;
  publishing the code does not rewrite yesterday's artifact. Until a rebuild
  runs, the served ladder keeps reading `mean 0.0`.
- **(c) The reading that proves it.** Re-run the exact control/treatment pair
  above on the served payload: `prop=hitter_strikeouts` must show `mean > 0`,
  `modeProb < 1.0` and more than one rung, with `prop=hits` unchanged.
- **(d) Verify `probability_refusal` covers the MLB ladder path**, so the
  protection stops being accidental.

**Nothing downstream needs re-fitting** (checked, production): there is no
fitted hitter-props calibration artifact at all, and the 1,373-row
`props_actuals_2026-09-04.csv` carries no hitter-strikeouts market. Standard
§4.4 populate-a-dead-field, not a new mechanism.

**Regression is now gated:** `set(spec row_keys) <= set(hitter_stat_values)`
plus a two-site drift check run inside `scripts/sim_input_checklist.py`, which
`scripts/run_mlb_daily_sim_job.py` executes — so it fails the daily job, before
the roster glob, not gated on `--warn-only`. Note the reachability tests do NOT
catch the two-site drift: `workers=1` never enters `_simw_chunk`.

