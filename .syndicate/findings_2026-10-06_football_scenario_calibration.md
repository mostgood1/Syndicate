# Football scenario calibration (smartsim2, NFL + NCAAF) — lane `football-scenario-calibration`

Opened 2026-10-06, session 20aa7f5b. User decisions (2026-10-06, in chat): run the MLB
`mlb-combined-calibration` scenario loop on the shared smartsim2 engine; **game + live lines
first, player attribution (props) in a follow-on lane**; **NFL and NCAAF together**.

## Method (ported from `mlb-combined-calibration`)

1. Pre-register the scenario here BEFORE measuring: population, formula, CI, decision rule.
2. Measure the REAL rate from play-by-play on FIT seasons only.
3. Measure the SIM rate from production's own `build_projection` (300 seeds, shipped profile,
   production env) on the SAME FIT games, via the `segment_accumulator` seam — every seed's
   full `SmartSim2SimulationOutput` (drive_log + possession_log). No engine code is modified
   to measure.
4. Reachability before correctness: any lever is shown `off != on` on one game before use.
5. Mechanism default-off, byte-identical (seeded sha256 of the outputs) + tests.
6. Measured rates FIXED in every arm; jointly re-fit the rates that were absorbing them
   (`model_engine_standard.md` §4.4).
7. VALIDATION read ONCE. Ship only if every gate clears its own SE (learnings 2026-09-23).

## Splits (fixed now, before any reading)

| | FIT | VALIDATION (read once) | prior-only |
|---|---|---|---|
| NFL | 2023, 2024 REG | 2025 REG | 2022 (as-of prior season) |
| NCAAF | 2023, 2024 FBS-vs-FBS REG | 2025 | — |

Amends the lane's Verification line (which said NFL FIT 2022-24): 2022 has no prior season in
the local pbp, so its as-of ratings differ from production's construction.

## Phase 1 — PRE-REGISTERED 2026-10-06 (before any measurement): real-vs-sim scenario table

No engine change in Phase 1. Output: one row per (sport, scenario, bucket) with real rate,
sim rate, n (real drives/plays/games), 95% CI by GAME-clustered bootstrap (1000 reps) on the
real side, sim SE from seed-clustered bootstrap, and gap.

Drive = a possession in the pbp drive table (NFL: nflverse `fixed_drive`; NCAAF: CFBD drives),
excluding drives that start with < 0:00 remaining and kneel-only end-of-half drives are KEPT
(the sim has them). Points per drive counts the offense's TD as 7 in the SIM (engine fixed)
and as 6 + actual PAT/2pt in REAL; the 7-vs-actual difference is reported as its own row (S7).

| id | scenario | metric (both sides) | buckets |
|---|---|---|---|
| S1 | drive scoring vs team quality | P(drive ends TD), P(FG), P(punt), P(turnover), P(TOD), points/drive | overall; by rating-gap tercile of the offense vs the defense (gap computed from the SAME as-of ratings the sim received) |
| S1b | dispersion | SD across team-games of the per-team-game points/drive | overall |
| S2 | garbage time | points/drive and sec/play for drives starting in Q4 with |score diff| >= 17 (NFL) / >= 21 (NCAAF) | leading vs trailing offense |
| S3 | pace | seconds of game clock per offensive play | score state (lead 9+, within 8, trail 9+) × half |
| S4 | red zone | P(TD | drive reaches opp 20), P(FG att | reaches opp 20) | — |
| S4b | FG make | make rate by kick distance | <30, 30-39, 40-49, 50+ |
| S5 | 4th down | P(go), P(punt), P(FG att) on 4th down | field position (own half / opp 40-30 / opp 29-) × to-go (1-2, 3-5, 6+) |
| S6 | drives per game | possessions per team per game; plays per drive | — |
| S7 | TD value | points per TD incl. PAT/2pt | — |
| S8 | overtime | P(game reaches OT); P(tie after OT) (NFL) | — |
| S9 | half split | share of game points in H1 | — |
| S10 | game-level spread | SD of total, SD of margin conditional on the projected line (residual vs close) | — |

**Decision rule (fixed):** a scenario-bucket is FLAGGED when the sim rate lies outside the real
95% CI AND the implied points-per-team-game effect of the gap exceeds 0.25 (NFL) / 0.40 (NCAAF).
Flagged rows are ranked by that effect and become Phase 2 candidates, each pre-registered
separately. A row inside the CI is recorded EXONERATED for this engine version — it is not
re-opened without a new reason.

**Falsification of the lane hypothesis at Phase 1:** if no row is flagged in either sport, the
loss to the close is not a scenario-rate problem and the lane closes with that result.

**Coverage rule (CLAUDE.md):** the script prints per-family season/week coverage (pbp, drives,
ratings, closing lines) and the intersection, and the result states the game count it rests on.
Source: LOCAL files only (Render suspended since 2026-09-30); `data/` untracked mirror, vintage
printed per file (mtime + row count).

## Results

(none yet)
