# Engine experts: contract, pipeline trace and gate (Phase 1B M1)

Lane `engine-experts` (opened 2026-11-10), umbrella `#736`. Plan: `plan_one_engine_pregame_live.md` §2 "Experts", §3 M1.
Code: `syndicate/features/shared/engine_experts.py`. Runner: `scripts/engine_experts.py`. Tests:
`tests/test_engine_experts.py`. Standard followed: `model_engine_standard.md` (§1 checklist, §2 trace, §0 the silent
neutral default).

## The contract

One `ExpertOpinion` per line per instant (`engine_experts.ExpertOpinion`):

| field | meaning |
|---|---|
| `expert`, `expert_version`, `v` | who, which version, contract `engine_expert/1` |
| `phase`, `t` | `pregame` or `live`; the instant the opinion is about |
| `sport`, `event_id`, `line_key`, `market`, `segment`, `side`, `line`, `player` | the line (`side` is over / home for live rows: the ledger's frame) |
| `p_prior`, `prior_basis`, `prior_age_s` | the market prior and where it came from |
| `p_expert` | the expert's own probability for that side |
| `delta_logit` | `logit(p_expert) - logit(p_prior)`: the shift it proposes |
| `sigma`, `sigma_basis` | its own uncertainty on the logit scale, and what that measures |
| `clock_bucket`, `elapsed_share` | pregame: hours to the start at the record's instant, `pre>24h` / `pre6-24h` / `pre1-6h` / `pre<1h` (`pre` when unknown); live: the share of regulation elapsed, 0-25 / 25-50 / 50-75 / 75-95 / 95-100, `ot` |
| `inputs` | the scalars it read (auditable) |
| `refusal` | a NAME when it cannot opine |

**A refusal never carries a 0.** `delta_logit` is `None` whenever `refusal` is set, so the M2 learner can tell "the
expert agrees with the market" from "the expert had nothing to say". Off switch:
`SYNDICATE_ENGINE_EXPERTS_OFF=<name,...>` (absent = all on); an expert that is off refuses `expert_off`.

## The experts in slice 1

| expert | phase | p_expert | sigma | refusals worth knowing |
|---|---|---|---|---|
| `sim` | pregame | the record's `model.p_model` (calibrated sim) | `None`, basis `unrecorded:no_sims_in_record`: the record has no sim count | `model_anchored_to_prior` (below), `game_not_pregame`, `no_model_probability` |
| `under_tilt` | pregame | prior + the SUPPORTED prop under-bias (`matchup_signals.likelihood_adjustments`: NBA 1.23 pp, NCAAF 2.38 pp) | the measured residual's own uncertainty: max(binomial SE, half the two-window gap) = 0.30 pp NBA, 0.60 pp NCAAF | `signal_not_applicable` |
| `live_resim` | live | the live re-sim histogram at the instant the join priced the line: two-way (push sims out), Agresti-Coull smoothed | Monte Carlo SE of that estimate, logit scale | `ledger_refusal_row`, `no_prior`, `no_game_match`, `no_evidence_before_instant`, `evidence_stale` (> 900 s), `segment_settled`, `segment_margin_unanchored`, `no_distribution` |

**`model_anchored_to_prior`.** A pregame model probability within `ANCHOR_TOL = 1e-5` of the prior is the prior
restated. Measured on the fleet's 11-10 record (build 16:00:47Z):
- every NBA spread (744 within 1e-6 plus 12 exact, of 756, basis `sim_margin_dist/*`);
- every NCAAB spread (70 of 70);
- 332 of 862 NBA totals.

The pregame margin distribution is anchored on the market spread, so P(cover) at the market's line is the market.
Read as an opinion it would be a delta of 0 that looks like a sim agreeing with the market.

## Pipeline trace (each hop: file:line, what it writes)

**Pregame (`sim`, `under_tilt`).**

```
refresh-worker heavy board build
  pipeline/intelligence_state.py:7955   run_shadow(selected_date, layer2_shortlist)
    syndicate/features/shared/decision_record.py:1192  run_shadow -> build_records
      decision_record.write_records
        writes reports/intelligence/decision_records/<date>.json.gz   (the LATEST build only, overwritten)
      decision_record.keep_pregame_lines                               (slice 2, lane pregame-record-keep)
        writes reports/intelligence/decision_records/<date>.pregame_lines.jsonl.gz
               one row per line key: FIRST and LAST pregame record (slim), streamed merge, never drops a line;
               log line `[decision_record] PREGAME_KEEP`; switch SYNDICATE_DECISION_RECORD_PREGAME_KEEP (absent = on)
scripts/engine_experts.py pregame()  read_pregame_lines (source=kept_lines) when the date has the file,
                                     else read_records (source=latest_build); expand_record
  engine_experts.pregame_opinions_at -> sim_expert, under_tilt_expert   (each record at its own instant)
```

**Live (`live_resim`).**

```
live re-sim ticks (per sport)  ->  live/<sport> snapshot (overwritten)
  live_evidence_log.Collector (refresh-worker, every 30 s)
    writes live_evidence/<sport>/<producer date>.jsonl          (append-only, as-of stamped; M0)
board build -> live_gameline_join prices each live line off the same lane
  live_gameline_ledger.py:251  build_records  ->  :620 append_records
    writes <sport>_source/data/live_gameline_ledger/live_gameline_ledger_<date>.jsonl   (:147; rows only when a value moves)
scripts/engine_experts.py live()  ledger rows + evidence rows (date -1 .. +1)
  engine_experts.EvidenceIndex (by team names: the ledger's ids are the odds feed's, the log's are ESPN's)
  engine_experts.live_opinions -> live_resim_expert
```

Nothing writes opinions under the data root. `run --opinions OUT` writes them where pointed.

## The gate (plan §3 M1: off != on per expert; a coverage table per sport, phase and clock bucket)

- **off != on:** `tests/test_engine_experts.py` (`test_sim_expert_on_then_off`, `test_under_tilt_...`,
  `test_live_resim_refusals_are_named`).
- **Input checklist** (`engine_experts.checklist`):
  - CONSUMED is the set of paths the expert actually read in this run (`Reader`). It is never taken from a name list.
  - POPULATED is the non-null share on that source's real rows. The ledger's refusal rows are excluded, because
    they carry no values by design.
  - Output fields are walked over `dataclasses.fields(ExpertOpinion)`.
  - Documented gaps are in `EXPECTED_SPARSE`, each with its reason.
- **Join reproduction**, the expert's own correctness check: on half-point totals/spreads where the expert and the
  join read the same lane state, `p_expert` must equal the join's model probability.
- **Readings:** `.syndicate/deploys.md` and the lane block in `lanes.md`.

## Known gaps (not this slice)

- **Pregame record keeps only the day's last build** (11-09's file held no NBA line). Slice 2 keeps each line's
  first and last pregame record (`keep_pregame_lines`). It reaches production with a refresh-worker restart. The
  fleet dry run on 11-10's real record measured 0.17-0.33 s per build (write_records itself: 0.68 s), a peak of
  1-2 MB, and about 0.9 MB for 3,925 lines.
- **Stat progress** needs per-player live prop projections per tick. NBA's `liveProps` are overwritten each tick and
  kept nowhere, the evidence log included.
- **NFL live totals/spreads have no prior.** The live join refuses every one as `no_distribution`, because the NFL
  lane publishes its histograms at lane level (snake_case); leads 2026-11-10.
- **NHL live** prices only the moneyline (no distributions).
- **Rest, referee crew, weather, steam** are collected but not turned into a line shift anywhere (survey
  2026-11-10). Each needs its own measured model before it can be an expert.
- `live_evidence/` is not in `EXPORT_ONLY_ARTIFACT_PATTERNS` (`model_engine_standard.md` §3). Its size (~7 MB a
  night) needs weighing against the backup pull first.
