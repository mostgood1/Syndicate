# DecisionRecord (`#709` step 2) — shadow record + daily agreement

Lane `decision-record-shadow`. Design: `.syndicate/findings_2026-10-20_one_engine_audit.md` §4.
**SHADOW: nothing reads the record for placement, sizing or the board.**
(`tests/test_decision_record.py::test_nothing_outside_the_lane_reads_the_record` enforces it.)

## Pipeline trace (file:line at commit time)

```
IntelligenceStateLoop._build_candidate_pool          pipeline/intelligence_state.py:6748   (refresh-worker, heavy build)
  -> build_layer2_shortlist                          pipeline/intelligence_state.py:7467
  -> write_layer2_shortlist                          pipeline/intelligence_state.py:7530
  -> run_portfolio_commit (paper, paper:<venue>, live:<venue> plans)   :7682
  -> DECISION RECORD hook (own memory guard, token DECISION_RECORD_GUARD_SKIP)   :7892
     -> decision_record.run_shadow                   syndicate/features/shared/decision_record.py:1128
        -> _read_plans (portfolio_commit readers, read-only)            :1113
        -> load_context (optimizer w* table, cheat-sheet form, band/caps/floors)  :519
        -> build_records -> build_record / _blend / _gates_for / _size  :959 / :935 / :687 / :751 / :850
        -> write_records  WRITES <data root>/reports/intelligence/decision_records/<date>.json.gz   :1066
        -> _live_orders (execution_ledger._load, mode=live, read-only)  :1182
        -> decision_agreement.record_build_agreement                    syndicate/features/shared/decision_agreement.py:271
           APPENDS <date>.agreement.jsonl (one line per build)
           -> write_daily_report                                       :419
              WRITES <date>.agreement_report.json and <date>.agreement_report.md
```

The FAST layer-2 path (`_refresh_layer2_shortlist_only`) writes no plans and no record:
the record exists for heavy builds only (fleet 10-23: 50 heavy vs 5 fast in one log).

Log lines: `[decision_record] DECISION_RECORD_WRITTEN ... elapsed_s=`,
`[decision_record] DECISION_AGREEMENT date= board=a/n paper=... live_orders=a/n builds=`,
`[intelligence_state] DECISION_RECORD_FAILED`, `DECISION_RECORD_GUARD_SKIP`.

## Inputs, and where each comes from

| record part | source | absent → |
|---|---|---|
| identity | the board row | — |
| venue contract | `venue_ref` + `price_source`, dated by `venue_quote_fanin._quote_is_for_another_date` | `no_contract` (gate UNKNOWN, advisory: the Kalshi executor joins its own ticker) |
| `p_market` | `quote.fair_probability` (Shin consensus) | every verdict no-bet (`market_fair` gate) |
| `p_model` | `model_probability_cal` → `_raw` → side-adjusted `projection.model_prob_over` | w_model 0 |
| w* | `<data root>/reports/model_scorecard/model_scorecard_optimizer.json` `calibration[]`, cell = `optimizer_overlay.cell_of_row` | applied only where the fit is not `insufficient` and its ci95 LOWER bound is > 0; else 0 (`optimizer_w_ci_spans_0:<verdict>` for a fit that reaches 0, `default_unmeasured` for no fit, `skill_loses_to_market`). Was a 0.25 default for unmeasured cells until 2026-10-26 (D3, plan #736) |
| form + posterior | `<data root>/cheatsheets/<sport>/<date>.json` rows' `check.form5/form10`, re-anchored on this build's `p_market` (k = `cheat_sheets.PRIOR_STRENGTH`, provisional) | weight 0 by default anyway |
| fees | `venue_fees.taker_fee_per_contract` (Kalshi series multiplier; Polymarket 0.0695·p(1−p)) | recorded unknown, never 0 |
| price band | `execute_portfolio.live_price_band` (`SYNDICATE_LIVE_PRICE_BAND`) | evaluated at 0.40–0.75, `enforced_live=false` |
| net floor | `portfolio_commit.live_net_floor(venue)` | > 0 |
| order cap | `execution_guard.limits("live", venue)` | no cap layer |
| band / favourite cap | `live_stake_band.band_config` / `favourite_cap_config` | no band layer |
| bankroll, settled sample | the plans this tick wrote (`bankroll_units`, `compounding.capital`, `sizing.settled_sample_size`) | `bankroll_unknown`, credibility layer unapplied |

**Reuse flag:** none. Nothing is cached across builds except the cheat-sheet form index
(keyed on file mtime), so a new input reaches the record on the next heavy build.

## The rules it applies

- `p_decision = p_market + w_model·(p_model − p_market) + w_form·(p_post − p_market)`.
- ONE EV: `ev_net = p / (price_prob + fee) − 1`, at `p_decision` and at `p_market`.
- Gates (`passed` true/false/None; None blocks unless the gate is advisory):
  `price_quoted, market_fair, two_sided_fair, fresh_quote (advisory), plausible_price,
  min_ev_floor` everywhere; live adds `venue_contract_identity (advisory), pregame,
  price_band, longshot (≤0.15), concentration (advisory, R1 within the build)`.
- Size: `kelly_full → ×kelly_multiplier → ×credibility → ×skill_and_optimizer → ×bankroll
  → order_cap`. The live **stake band and favourite cap are recorded with
  `applied=false`**: the band reads FULL Kelly (audit rank 3), so the record's own stake
  stays applied Kelly and `stake_dollars_live_equivalent` says what live would do.

## Checks

- `python scripts/decision_record_checklist.py --date <D>` — fields walked with
  `dataclasses.fields()`, populated vs DEFAULT, exit 1 on an alarm. Run it where the
  file is (the fleet's data root); a checkout has no record.
- `python scripts/decision_record_agreement_report.py --date <D>` — re-render the day.
- Off switch: `SYNDICATE_DECISION_RECORD=off` (absent = shadow).
- Allowlist: `reports/intelligence/decision_records/*` in `EXPORT_ONLY_ARTIFACT_PATTERNS`
  (read-only; the record is gzip, so `/api/ops/artifacts/stream`).
