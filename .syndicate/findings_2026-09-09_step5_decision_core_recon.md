# FINDINGS — step 5: the pipeline already exists, runs in the right order, and FIVE OF ITS SIX STAGES ARE SWITCHED OFF

`[2026-09-09, lane segments-joint-v1, code recon + a live env read that closed its one UNVERIFIED]`

## Verdict

Audit rec 5 asks to *"REPLACE the decision core with one seven-stage opportunity
pipeline"*. **It does not need replacing. On the primary path the stages exist
and already run in the correct order.** Step 5 is (a) **consolidation** — naming
what is inlined, collapsing five duplicate decision paths — plus one real
ordering defect on a secondary path.

**This is the second time in two days that an audit recommendation was written
without knowing what production already did.** Step 3's recon corrected four of
five clauses the same way.

## The decision core, traced

    layer2_board.build_layer2_rows          (shared/layer2_board.py:2510)
      -> select_shortlist                    (:4158)
      -> pipeline/layer2_shortlist.build_layer2_shortlist:627
      -> artifact
      -> shared/portfolio_commit.commit_portfolio:746
      -> pipeline/portfolio_commit.run_portfolio_commit:1020
      -> pipeline/execute_portfolio.py -> execution_ledger

The `pipeline/*.py` twins are RUNNERS, not duplicate logic.

## The real order, per row, inside `build_layer2_rows` — and it is CORRECT

| # | stage | site | status in production |
|---|---|---|---|
| 1 | quote plane | `_resolve_fair:1451` / `_anchored_fair:1356`, called `:2540` — **first** | **ON** — `SYNDICATE_FAIR_ANCHOR=sharp_only` |
| 2 | abstain (eligibility) | `opportunity_gate.annotate:272` at `:2825` — before scoring, deliberately | on |
| 3 | model plane | `_model_edge_for:2151` at `:2832`, given the de-vigged fair | on |
| 4 | calibrate | `_calibrate_model_edge:2318` at `:2834` — after model, before blend/size | **OFF** |
| 5 | blend | `blended_score` at `:2895`; staked blend `blend_beta 0.0`, `UNFITTED_VERSION` | **INERT** |
| 6 | size | `sizing_inputs_with_provenance:400` -> `_interval_verdict:329` -> `sizing_candidate:513` | **partly OFF** |
| 7 | settle/grade | `paper_settlement`, `clv_join`, `order_clv` | on |

**ROUTE IS NOT A STAGE AND MUST NOT BE BUILT AS ONE.** `scope_rows_to_venue`
runs at `pipeline/portfolio_commit.py:1326` *after* the plan, producing a second
venue-scoped comparison book (`venue_scope.py:1-40`). That is consistent with
today's scoring, which **refuted** venue routing outright (realised diff ~±1 pt,
**−1.67 against a sharp book**). The seven-stage diagram is really **six stages
and a comparison artefact**.

## THE HEADLINE: the pipeline was built and never switched on

Read from LIVE env-vars 2026-09-09 (00:30Z 09-10) (the recon had this as UNVERIFIED, taken from
the ledger; this is the direct read):

    refresh-worker      SYNDICATE_FAIR_ANCHOR            = 'sharp_only'   <- the ONLY one on
                        SYNDICATE_PRICING_CALIBRATION    = ABSENT
                        SYNDICATE_KELLY_ON_FAIR          = ABSENT
                        SYNDICATE_PREGAME_INTERVAL_GATE  = ABSENT
                        SYNDICATE_PARLAY_MEASURED_JOINT  = ABSENT
    live-odds-worker    all five ABSENT

**One of six stages is live.** Calibration resolves to identity
(`probability_calibration.py:199,203`), the staked blend is β=0 against an
unfitted profile (`portfolio_commit.py:391`), Kelly-on-fair is off
(`bankroll_manager.py:152`), the pregame interval gate is off. **Step 5's real
content is not architecture. It is that five measured mechanisms are shipped
dark.** Each was deliberately flag-absent-by-default so it could be measured
before it moved a number — that discipline was right — and then nothing flipped
them.

## SIX independent decision paths — this is the actual rewrite surface

1. **board/shortlist -> `commit_portfolio`** — already the pipeline.
2. `intelligence_state._attach_board_stakes:5615` — served candidate board. **No
   fair plane, no calibration, no interval gate.**
3. `syndicate/features/intelligence.py:9383` — its own `_compute_bet_size`, its
   own `risk_level`/confidence arithmetic off `adjusted_edge or edge`.
4. `intelligence_audit.py:772` and `:956`.
5. `intelligence_parlay_runtime.py:563`.
6. `live_gameline_join.py` — its own priceability gate (`:196`) for the live lane.

**Paths 2–5 emit NO refusals at all — they degrade silently.** That is the
strongest argument for consolidation: the refusal vocabulary the audit says to
KEEP is real and shared on path 1 (`opportunity_gate.py:58-61` 4 lanes + 8
reasons; `portfolio_commit.py` 7 `refuse()` names + 3 sizing reasons, with
`prob_interval_swamps_edge` genuinely IMPORTED from `live_gameline_join` at
`:129`), and simply absent everywhere else.

## The one real ordering defect

`pipeline/intelligence_state.py:6359` **sizes** (`_attach_board_stakes:5581`)
**before** `:6365` ranks (`_attach_adjusted_scores`). The stake is computed
against the raw edge, and the score it should have used is attached afterwards.
One swap.

## What constrains any change

`portfolio_commit` **back-derives market fair from `ev_pct`**
(`sizing_inputs_from_row`: `fair = (ev_pct/100 + 1)/(profit + 1)`), so **`ev_pct`
must stay MARKET-priced**; the model substitution deliberately touches only the
score term (`layer2_board.py:2860-2890`). Board-contract fields the plan is
derived from: `ev_pct`, `model_ev_pct`, `ev_basis`, `model_edge_pct`,
`model_edge_basis`, `score`, `quote`, `board_lane`, `gate`, `movement`
(`:2905-2960`). Consumers: `layer2_rows_to_board_cards:3217`,
`_layer2_board_columns:3821`, `venue_scope`, `order_clv`, `clv_position_join`,
`position_marks`, `execution_ledger`, `paper_settlement`.

## Production funnel, for scale

08-24..08-31: `no_model_edge_pct` **2,506**, `below_min_ev_pct` 1,567,
`below_min_stake` 46, `zero_kelly` 37 — **~4,150 refusals against ~458 orders**,
and `model_edge_pct` is numeric on only **902 of 2,623 rows (34.4%)**
(`state_layer2.md`).

## Recommended shape

1. Extract the stages already inlined at `build_layer2_rows:2540-2960` into named,
   individually-testable functions in one `opportunity_pipeline.py` returning a
   **stamped stage trace**. Behaviour-preserving; a byte-identity harness already
   exists (`lanes.md:661`). ~1 day.
2. Swap `intelligence_state.py:6359`/`:6365`.
3. Repoint paths 2–5 at it and delete their private sizing. ~2–3 days.
4. **Do NOT build stage 6.**

**And separately from the refactor, the higher-value question: which of the five
dark stages should be switched on, and in what order, each with a reading.**
That is a smaller change than the extraction and is where the measured work of
steps 2 and 3 actually reaches a served number.
