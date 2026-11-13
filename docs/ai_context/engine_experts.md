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
| `live_segment` (slice 4, lane `live-segment-expert`) | live | an UNSETTLED segment (college h1 / h2; NBA halves and quarters) totals or spreads line some book was quoting at a logged re-sim tick, priced from that tick's segment histogram exactly as `live_gameline_join.price_distribution_market` would (two-way, Agresti-Coull, the away-frame line); the join itself refuses college segments (`segment_pricing_disabled`, #763) | Monte Carlo SE of that estimate, logit scale (200 sims a block) | `segment_absent`, `segment_settled`, `segment_margin_unanchored` (NBA: its blocks carry no anchor), `no_distribution`, `sample_certainty` (every sim on one side: the join refuses it, #624), `prior_one_sided`, `prior_unpaired`, `prior_stale`, `prior_implausible_hold` |
| `stat_progress` (slice 3, lane `live-stat-progress-expert`) | live | one player prop's published live P(over) at one logged tick (banked actual + the re-sim's rest-of-game draws), Agresti-Coull smoothed at n = `simsRun` (100 on NBA) | Monte Carlo SE of that estimate, logit scale | producer reasons verbatim (`quote_pulled`, `certainty_refused`), `no_quote_before_instant`, `prior_one_sided`, `prior_unpaired`, `prior_stale` (> 900 s), `prior_implausible_hold` |

**The `stat_progress` prior** (`prop_prior`) is the live BOOK prior at the props row's instant `t`, rebuilt from
`book_quotes` with the board's own rules (`odds_book_quotes._fair_value_fields`):
- per (book, side), the freshest quote by observed stamp, among those CAPTURED by `t`;
- a book counts only with both sides within 600 s of each other;
- each book de-vigged within itself, then the median across books, renormalised;
- refused when the best prices imply a hold below -5% (a dead leg).

One rule is added in play: a book whose newer side is older than `PROP_QUOTE_MAX_AGE_S = 900` s is left out.
`book_quotes` appends on a change, so the age is time since the price last moved. Doubles markets are Yes/No with a
NaN line: Yes is OVER the producer's fixed line (1.5 / 2.5).

**The `live_segment` prior** is the same rule (`prop_prior`) over `book_quotes` GAME-LINE rows
(`GameLineQuoteIndex`). A spread quote carries its own side's handicap (`selection` home / away, opposite signs), and
`canonical_quote_side` puts it in the join's away frame: home at h is "home covers" at L = -h. A sign error here is
the 2026-08-08 phantom-edge defect, so the runner reads the rebuilt prior against the join's OWN de-vigged price on the
full-game lines the join priced (`SEG_FRAME`), and the sign-flipped frame beside it. The two priors use different
rules (the join de-vigs the grid's consensus price per side; the expert takes the median of per-book de-vigs), so they
differ a little; a wrong frame differs a lot.

**Why the segment expert enumerates ticks, not ledger rows.** The ledger keeps one row per segment line per day, with
no market price, on purpose (`live_gameline_join.attach_live_gamelines`: a moving price would rewrite every segment row
each build and fill the file). So the ledger cannot say when a segment line stood. `live_segment_opinions` walks the
evidence log's ticks of every game the books quoted segment lines for, and opines on each unsettled segment x market x
line some book was quoting within 900 s of the tick (`line_live_at`). A settled half, and a game no evidence game
matches by team key, are counted, not opined.

**Not a line.** The re-sim publishes each posted line with +-3 neighbour lines. A row at a line no book quoted that
day (`line_not_quoted`), or for a player and market no book quoted that day (`no_quotes_for_player_market`), is
counted and never becomes an opinion, so the coverage table's `lines` are lines a bettor could have taken.

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

**Live (`stat_progress`).**

```
NBA live re-sim tick  ->  live/nba_live_resim.json games[].liveProps (overwritten)
  syndicate/features/nba/live_resim.py build_live_props           (rows per player, stat, posted line +-3)
  live_evidence_log.Collector -> live_prop_evidence.snapshot_prop_rows
    writes live_evidence/<sport>/<date>.props.jsonl                (one row per game per changed tick; lossless)
odds fetchers (OddsAPI books, Kalshi direct)
  odds_book_quotes.append_book_quotes
    writes <sport>_source/tracking/book_quotes/<date>.jsonl[.gz]   (append-on-change, per book/market/selection)
scripts/engine_experts.py stat_progress()  props rows + the date's quote shard + evidence rows (date -1 .. +1)
  engine_experts.PropQuoteIndex (by team names + folded player + market -> line; streamed, counts population)
  engine_experts.stat_progress_opinions -> stat_progress_expert -> prop_prior
  engine_experts.prior_reproduction    (the board's _fair_value_fields on the same quotes: the gate)
```

**Live (`live_segment`).**

```
live re-sim ticks (NCAAB / WNCAAB / NBA)  ->  lane rows carrying segments.<seg> {total_dist, margin_dist, sims,
                                               settled, marginAnchored, remainingFraction}
  live_evidence_log.Collector  writes live_evidence/<sport>/<producer date>.jsonl   (M0, as above)
odds fetchers  ->  odds_book_quotes.append_book_quotes
  writes <sport>_source/tracking/book_quotes/<date>.jsonl[.gz]   (game lines carry `segment`: full / h1 / h2 / q1..)
scripts/engine_experts.py segments()  evidence rows (date -1 .. +1) + the date's quote shard + the date's ledger
  engine_experts.GameLineQuoteIndex (home key, away key, market, segment -> canonical line; streamed, counts population)
  engine_experts.live_segment_opinions -> live_segment_expert -> prop_prior
  engine_experts.segment_join_reproduction   (price_distribution_market on the same histogram: the gate)
  engine_experts.segment_prior_reproduction  (the board's _fair_value_fields on the same quotes: the gate)
  engine_experts.segment_frame_check         (the rebuilt prior vs the join's own, full-game lines: a reading)
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
  - **The join's number is the engine's, never `#780`'s tempered one** (lane `live-resim-join-unscaled`). On a ledger
    v7 record with `prob_scale` != 1 (NBA / NCAAF full-game totals), `model_home_win_prob` is the TEMPERED P(over). The
    check reads `model_home_win_prob_unscaled` there instead; a tempered record without it is not checked.
  - Fleet replay 2026-11-13: the 11-11 / 11-12 NBA ledgers (all v6, so nothing tempered yet), re-tempered with the
    join's own `scale_prob` at k 2.16. 5,552 / 4,831 tempered half-point totals were checked and 0 mismatched. Read
    the old way, 5,506 / 4,779 mismatched. The untouched rows: 0 mismatched, checklist ok, opinions identical.
- **Prior reproduction** (`stat_progress`): every opined line's prior, recomputed by the board's
  `_fair_value_fields` from the same quotes, and its `p_expert`, recomputed from the published P(over), must match
  to 1e-6. Fleet readings 2026-11-13 (the worktree's code on fleet data, read-only, nice 19):

  | night | props rows | published rows | not a line | lines | opined | prior / p mismatched | checklist |
  |---|---|---|---|---|---|---|---|
  | 11-11 (10 games) | 494 | 464,203 | 124,116 | 340,087 | 84,773 | 0 / 0 | ok |
  | 11-12 (4 games) | 237 | 229,149 | 63,676 | 165,473 | 40,057 | 0 / 0 | ok |

  - Prior age of the opined lines: median 249-255 s, p90 720-722 s.
  - Books per prior: median 2, range 1-10.
  - Opined share falls through the game, 40-44% in 0-25 to under 5% in 95-100. Late lines are mostly `quote_pulled`.
  - Median |delta| is 0.59-0.74 logit in regulation; mean delta is negative everywhere (the re-sim is below the
    books on over).
  - 11-12: corr(logit prior, logit expert) 0.35, so the join is not random.

  The biggest early disagreements have two shapes, both for the engine read rather than the expert:
  - The sim's minutes for some players: Aldama's projected 1.08 rebounds against 7 books at about 0.5 for over 3.5.
  - A single book quoting a pregame line long after it was passed: P.J. Washington PRA 21.5 at 0.46 with 12
    banked at 24% elapsed.
- **Segment checks** (`live_segment`, lane `live-segment-expert`): `SEG_JOIN`, the expert against
  `price_distribution_market` on the same segment histogram, half-point lines, must be 0 mismatched (whole-number lines
  differ by design: the expert drops push sims); `SEG_PRIOR`, its prior against `_fair_value_fields`, must be 0
  mismatched. Fleet readings 2026-11-13 (the worktree's code on fleet data, read-only, nice 19):

  | night | sport | games quoted / matched | lines | opined | SEG_JOIN checked / mismatched | SEG_PRIOR mismatched | SEG_FRAME median spreads / flipped / totals | checklist |
  |---|---|---|---|---|---|---|---|---|
  | 11-11 | NCAAB | 94 / 89 | 43,324 | 41,762 | 40,876 / 0 | 0 | 0.24 / 4.9 / 0.17 pp | ok |
  | 11-12 | NCAAB | 37 / 34 | 22,704 | 21,902 | 21,020 / 0 | 0 | 0.21 / 4.2 / 0.20 pp | ok |
  | 11-11 | NBA | 10 / 10 | 110,808 | 47,562 | 43,056 / 0 | 0 | 0.10 / 39.9 / 0.22 pp | ok |
  | 11-12 | NBA | 4 / 4 | 52,495 | 21,995 | 19,872 / 0 | 0 | 0.06 / 41.7 / 0.21 pp | ok |

  - WNCAAB: no segment quotes in `book_quotes` on either night, so no prior and no opinion.
  - Unmatched NCAAB games are team-name misses between the ESPN lanes and the odds feed (UMKC / Florida A&M, South
    Florida / Saint Joseph's on both nights).
  - NBA segment spreads all refuse `segment_margin_unanchored`: its segment blocks carry no margin anchor, which is
    the join's own rule (documented sparse for NBA). Its segment totals are opined.
  - Before `sample_certainty` existed, 442 of 21,462 NCAAB half-point lines on 11-12 were 200 of 200 (or 0): lines the
    join refuses as a certainty (#624). They are refused now.
  - Expert off: 0 opined of the same lines on every sport and night.
  - The shifts are NOT edges: nothing here is graded against an outcome or a close. That is M2's job.
- **Readings:** `.syndicate/deploys.md` and the lane block in `lanes.md`.

## Known gaps (not this slice)

- **Pregame record keeps only the day's last build** (11-09's file held no NBA line). Slice 2 keeps each line's
  first and last pregame record (`keep_pregame_lines`). It reaches production with a refresh-worker restart. The
  fleet dry run on 11-10's real record measured 0.17-0.33 s per build (write_records itself: 0.68 s), a peak of
  1-2 MB, and about 0.9 MB for 3,925 lines.
- **Stat progress** is NBA only: the props log keeps any sport whose snapshot carries `liveProps`, and only NBA's does
  today. The prior does not yet prefer Kalshi's mid, which the plan names as the in-play prior where an identity check
  holds; Kalshi is one book in the median.
- **NFL live totals/spreads have no prior.** The live join refuses every one as `no_distribution`, because the NFL
  lane publishes its histograms at lane level (snake_case); leads 2026-11-10.
- **NHL live** prices only the moneyline (no distributions).
- **Segments:** WNCAAB has segment blocks but no segment quotes, so no prior. NBA segment spreads refuse for want of a
  margin anchor. `#780`'s measured over-confidence was on FULL-GAME totals (k NBA 2.16, NCAAF 2.48); the segment
  histograms are untempered, which is right for an expert (the learner weighs it), but a segment edge must never be
  priced off them raw. If college segment pricing is ever switched on, `live_resim` will opine on the same lines from
  the ledger, and the learner must use one of the two.
- **Rest, referee crew, weather, steam** are collected but not turned into a line shift anywhere (survey
  2026-11-10). Each needs its own measured model before it can be an expert.
- `live_evidence/` is not in `EXPORT_ONLY_ARTIFACT_PATTERNS` (`model_engine_standard.md` §3). Its size (~7 MB a
  night) needs weighing against the backup pull first.
