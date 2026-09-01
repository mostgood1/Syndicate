# FINDINGS — Sim-engine edge analysis, full platform (strategy, no code changed)

**Session** syndicate-8d, 2026-09-01. **Read-only analysis** requested by the user:
"how do we improve every aspect of our sports sim engines and logic so the sim
becomes a true edge." Full report published as artifact **"Where the Edge Lives"**
(https://claude.ai/code/artifact/342e3562-d25c-43e4-a617-28e2039001ee).
Sources: the three accuracy assessments (MLB/WNBA 2026-08-31, NCAAF opener
readiness 2026-08-26), state.md engine sections, learnings.md, todo.md #610-617,
docs/reports (smartsim/soccersim/hockeysim), plus six deep code surveys
(MLB engine, basketball, football, NHL/soccer, evaluation loop, data inventory).
Nothing below is a new production measurement; it is a synthesis of existing
measured facts plus code-structural facts (marked).

## The verdict (one paragraph)

The engines are good simulators that lose to a better forecaster — on every game
main line properly measured (MLB ML/totals, WNBA ML/spread/totals via #615,
NCAAF/NFL via the domination result, soccer 8 of 9 leagues), the market wins;
the only green cell is NHL totals at n=14-15 (unpowered). That is the expected
equilibrium result, not the platform's failure. The failures are structural:
(1) money is staked on `sim − market`, which is the sim's ERROR term
(corr(edge, win) = −0.1379); (2) the sims' one un-replicable output — JOINT
distributions — is generated every sim pass and discarded at aggregation;
(3) the feedback loop has settled 0.2% of settleable rows, so nothing can
improve on evidence and Kelly is pinned at 1/16th; (4) the largest measured
latent edge (MLB prop under book, +8.48pp gross at zero hold, +0.98% at today's
~8.1% hold) is spent on vig — venue economics, not modelling, is its lever.

## The five moves (priority order)

1. **One pricing pipeline: market prior + calibrated sim deviation, fitted
   weight per market, refit on outcomes, weight allowed to hit 0.** Replaces
   three broken relationships that coexist today: independent-then-differenced
   (MLB/football/soccer/NHL), anchored-then-differenced (basketball: the sim
   blends quarter means toward market at weight 0.95 margin / 0.7 total BEFORE
   simulating — sim/quarters.py:66 — so downstream "edges" vs the same market
   are amplified noise; this mechanically explains #615), and
   anchored-validated-but-off (soccer market_anchoring, MAE −40..−51% vs
   held-out consensus, weight never chosen; NHL ports it, opt-in, unused).
2. **Point the sim where it is structurally advantaged**: props, derivatives/
   ladders/segments, correlations (SGP), live conditionals, news reactivity.
   Never main-line point estimates.
3. **Venue-hold routing + exchange prop capture** (the two newest commits on
   main — 08ecb418 Kalshi props → book_quotes, 47753528 WNBA us_ex — are step 1
   of this). Price mechanics are the platform's only consistent measured winner
   (+2.79/+2.95pp shopping, +1.57pp exchange option value on game markets).
4. **Close the loop**: prop freeze (#611) + caps.ml (#610) supply fixes; CLV
   per sport (built, ON, measured for MLB only; T-window closing sweeps exist
   for MLB+WNBA ONLY); both-side prices at selection (0/8,778 today); scheduled
   scoring/drift (13 harnesses are all CLI one-shots; drift detector has no
   caller; the ONLY closed auto-calibration loop in the repo is basketball's
   7-day mean-bias); shadow-then-promote refits on held-out gates.
5. **Abstention/uncertainty/sizing**: refuse p∈{0,1} (993 MLB rows staked off a
   0.000 null); interval-swamps-edge abstention generalized from WNBA live
   totals; tiers from realized reliability (today tier = monotone in claimed EV,
   which has corr ≈ 0 with outcome); fractional Kelly on the blended prob.

## Code-structural findings the surveys added (not previously in the ledger)

- **MLB correlations discarded**: simulate_game returns full per-sim box
  scores; aggregation keeps only marginal histograms (daily_update.py:4380-4505).
  H+R+RBI is the lone within-sim sum ("distribution of a sum is not recoverable
  from its parts" — live_mc.py). Persisting per-sim vectors/moments = an SGP,
  ladder and derivative pricing asset no price-taker can copy.
- **A true MLB live MC exists** (live_mc.py estimate_live: runners/count/pitch
  counts, 120 sims, live-odds-worker) — live is blocked on LINE CAPTURE, not
  modelling (line_live_age null 1777/1777 WNBA; WNBA capture blocked by the
  reuse guard, root cause already located by lane wnba-live-odds-capture-gap).
- **Basketball production runs n_sims=100** (render.yaml:1017, OOM economy) —
  ±5pp MC error on a coin-flip prob, larger than any hunted edge.
- **NBA still carries the WNBA integrity bugs**: arithmetic American-price
  averaging (refresh_nba_oddsapi_props.py:2148-2152) and p_win = implied + EV
  (:1159/:1251/:1315), no clamps, no totals withhold. Port before NBA season.
- **Live klass hole (the T0-3 hole)**: the JSONL tick writer re-derives klass in
  absolute points ignoring the API layer's "never BET on line_source=model"
  gate (app.py:46302-46316 vs :40612-40616) — that's how 701 self-priced rows
  became BET.
- **is_home hardcoded 0.0 at basketball props inference**
  (basketball_props_features.py:371); opponent features never fed. Candidate
  new checklist finding.
- **MLB umpire input cannot exist on Render** (mechanism live at ±8% called
  strike; producer is a Windows-only prefetch of an untracked file). MLB
  weather is captured (NWS hourly, roof-flagged) and NOT joined to the sim
  (open half of #84). Park = geometry heuristic only in prod.
- **manager_tendencies.json does not exist anywhere** — all 30 teams share one
  ManagerProfile (resolves the lane's open "absent in production?" question:
  untracked + repo-relative path ⇒ cannot exist on Render).
- **NFL regular-season smartsim2 has never been graded vs the close** (default
  deny covers it); NCAAF anytime-TD model is real and correctly
  probability-only (Brier .1817 vs mean .2192, n=18,989); continuous NCAAF
  props deliberately unmodeled (player-mean wins) until 2026 data accrues.
- **NHL/NCAAB cannot settle a bet** (no live-state poller, no resolver); NHL
  segment odds never requested (vocabulary exists).
- **OddsAPI budget correction**: 4,959,329 of 5,000,000 REMAINING (99.2%
  unused, 2026-09-01, odds_regions.py:63-66) — the 92.8%-burn crisis was fixed
  by #15/#16. Historical endpoints are 10 credits/market-region (not free;
  probe-first discipline stands).

## What NOT to do (all already paid for — see learnings/strategy docs)

Main-line mechanism shopping (MLB fully-fed still loses 4/4; pitch-mix
validated and market-silent; football payload measured null; soccer input list
exhausted); staking sim−market anywhere; the dead football levers; TTO
re-enable; HR-prop inversion (doesn't pay at any vig); pooled-root evaluation;
in-sample calibration promotion; scaling real stakes before the paper-vs-real
slippage join (paper +9.4% vs real −5.5% same week); breadth without grading
(69 pairs ship, 2 have backtests).

## Sequencing (calendar-aware; detail in the artifact §08)

Now→09-17 restore measurement (freeze/caps supply, NBA ports, WNBA live-capture
guard, both-side prices, closing sweeps beyond MLB/WNBA, schedule scorer+drift).
Parallel: MLB prop program (tail isotonic → HRR null → substitution+refit →
re-run de-biased skill → execute pre-registered #202 scan → exchange-hold
routing; gate = surviving under book at ≤5% hold). 09-17..25: WNBA sprint run
against its 8 pre-registered gates, size on CLV. Late Sep→Oct: blend layer
sport-by-sport (soccer cheapest first). Oct: joint-outcome persistence +
segment grading + first SGP/ladder fair-value surface vs Kalshi rungs (paper);
NHL powered totals re-run + settlement resolver. Nov: live as a product.

## Platform constitution proposal

Adopt football's LIFT_CONDITION as the universal staking gate: beats the naive
baseline on the same bets + 95% CI lower bound clears the venue's actual vig +
out-of-sample with pre-specified subsets + denominators in bets not rows —
plus positive CLV vs a named reference (sharp close for game lines, labeled
soft consensus for props). CLV is the flywheel: ROI needs ~2,300 bets to
confirm +2pp at 2σ; the paired line-CLV comparison resolved [+2.48,+3.13] on a
sample where ROI's CI spanned ±5.7pp (#211).

## ADDENDUM (same session, user follow-up) — centralization + the local mirror

Artifact updated with §11 and §12 (same URL). Two revisions to the assessment:

**§11 Centralization.** Nearly every integrity bug in the report is a COPY-DRIFT
bug (NBA still carries the American-averaging and implied+EV defects WNBA fixed;
≥4 tier implementations; 3 market-blend implementations; 5 calibration storage
approaches; seal MLB-only and broken; closing sweeps MLB+WNBA-only; 7 WNBA
instruments each broken its own way). Proposal: centralize CONTRACTS not
content — five shared planes (probability, market-data, evaluation, run,
artifact-contract), each with an existing seed (football's versioned profile
store is the pattern to generalize). Operationally: replace per-sport cron
habits with a FIXTURE-STATE Daily Run manifest (scheduled→capture_open→drift→
ramp→sealed→live→final→settled→graded→archived), standard verbs per transition
as per-sport plugins, ownership declared in the manifest not env vars, a
priority sim queue (drains before deploys — the n_sims=100 cut and the 97.2%
live-odds-worker cap are scheduling problems), one per-fixture ops board.
This matches CLAUDE.md's own stated direction ("state-aware execution
controller with run modes").

**§12 Local mirror — ENDORSED under three laws.** A full, provably-in-parity
local mirror UPGRADES "Render is the source of truth" (every incident behind
that rule was a PARTIAL, unverifiable mirror). Laws: (1) data one-way
prod→local, code/config one-way local→prod via git+locks, never bidirectional;
(2) parity manifest (counts+hashes per family/date) or a local reading is not
evidence — extends model_engine_standard §3b substrate rule; (3) replay-first
(book_quotes IS a full tick tape; live-lens/feed_live replayable) — no OddsAPI
spend from dev loops, deterministic diffable runs; fetch mode explicit. Build:
manifest-driven sync (unify refresh_*_mirror.ps1 + backup workflow), an
EXPORT-ONLY pattern list for worker-local families (keeps #413 web protection),
nightly env snapshots, a local 3-role fleet runner (paper-only, prod
run-modes, optional memory-capped containers), a replay-diff gate wired into
migration_gate, substrate labels in the standard. Unlocks: kills the
"deployed inert" class pre-deploy; becomes the data WAREHOUSE (fixes
retention-blocked retro-evaluation: L2 ~4d, odds_events truncation, keyvalue
10d TTL); deploys become consolidated batches with one confirmatory prod
reading each; parallel sessions stop contending for prod. Still prod-only:
venue execution, egress-shaped behavior (ESPN datacenter block), real memory
pressure, live-slate firsts (once, then tape). Practicals: mirror OUTSIDE
OneDrive and outside git (SYNDICATE_DATA_ROOT); long-arc: git stops being a
data channel (34,690/37,745 tracked files are data) AFTER orphaned-allowlist
delivery paths are fixed; Modern Standby → verify sync by manifest not
timestamp.
