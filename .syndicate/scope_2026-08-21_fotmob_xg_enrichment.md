# SCOPE — FotMob xG enrichment for the soccer sim

Lane `soccer-board-mlb-parity`, drafted 2026-08-21 after the live totals lens
(`9c8ec540`) landed. **Not started. This is a scope, not a plan of record** —
§6 argues it may not be worth doing in this form, and that argument should be
settled before any code.

## 1. What ESPN gives us, and what it cannot

`ingestion/espn_live_state.py::build_live_state` produces, per team:
accumulated shots, shots on target, corners, red cards, plus per-player shot
and goal counts. **Counts without quality.**

The sim consumes those as VOLUME. `SoccerSimSimulationInput`
(`sim_engine/soccersim/contracts.py:114`) carries
`home/away_attack_rating`, `home/away_defense_rating`, `pace_seconds_per_event`
and an unused-here `feature_generation_payload` hook.

So a side with twelve speculative efforts and a side with four big chances look
similar to the engine. That is the gap: **two shots are not two chances**, and
it bites hardest on a LIVE totals projection, where the whole question is
whether the remaining ~30 minutes look like more of what just happened.

FotMob carries shot-level xG and xGOT, big-chance counts, and a momentum
series. ESPN structurally does not. That is a real capability difference, not a
preference.

## 2. What is NOT verified about FotMob, and must be before any code

I have not called FotMob's API. Everything below is a REQUIREMENT on the spike,
not a claim about how it works:

- **There is no public, documented API.** `/api/matchDetails?matchId=` is
  unofficial. It has required a request-signing header (`x-mas`) at times, which
  has broken third-party clients. Treat any field name as unverified until a
  real response is captured.
- **Terms of use are unestablished for this repo.** Confirm before shipping a
  dependency on it. This is a decision, not an implementation detail.
- **Match-id mapping ESPN <-> FotMob is unsolved.** We key on ESPN `event_id`
  everywhere. A second id space needs a join, and the last name-join gap here
  (RAAL La Louviere, 5 of 11 starters) cost a whole fixture's lineups the same
  day this was written.

**Spike first, and its output is a decision, not a module:** capture one live
and one completed match, record the exact JSON shape, confirm xG is present per
shot, and measure whether the id join resolves for all ten tracked leagues.
Reference matches supplied by the user: Marseille v Strasbourg (`2t8gik`,
live) and Preussen Munster v Karlsruher SC (`28pz1u`, completed).

## 3. Where it would actually attach

Two distinct consumers, and they should be staged separately because they carry
very different risk:

**(a) LIVE game shape — the cheap, high-value half.**
`features/live_lens.py::project_live_match` resumes a Monte Carlo from
half/clock/score and already applies red-card penalties. An in-match xG total
per side is the natural input: it says whether the current SCORE overstates or
understates the run of play. A 1-0 built on 0.4 xG against 1.6 xG conceded
should project differently from a 1-0 built on 2.1 xG.

Attach point: an `xg_so_far` pair on the live_state dict, consumed in
`project_live_match` as an adjustment to the resumed attack rates — NOT as a
new rating. See §6.

**(b) PLAYER PROPS — defer.** Shot-quality weighting for anytime-scorer
allocation is attractive and is where `build_usage_profiles` would use it, but
it multiplies with the roster-coverage ceiling below and should wait.

## 4. The standard this must meet

`docs/ai_context/model_engine_standard.md` is mandatory here. Concretely:

- **Gating input checklist.** `scripts/soccer_sim_input_checklist.py` already
  exists and cross-references CONSUMED against POPULATED over
  `dataclasses.fields()`. Any new field must appear there and the script must
  exit non-zero if it is consumed and unfed. This is the control that exists
  because 26 fields were silently unfed on the most mature engine in the repo.
- **Disk-backed and allowlisted.** The xG artifact must live under
  `SYNDICATE_DATA_ROOT` and be added to `HOT_ARTIFACT_PATTERNS`. A local cache
  cannot reach Render — and, as measured TODAY, an artifact written to one
  worker's filesystem cannot be read by the other. It must go through
  `refresh_state_store` (keyvalue) or it will be invisible to the board build.
- **Reachability before correctness.** `off != on` on a real payload, asserted
  before any accuracy claim. Four inert features in one session were caught by
  that and nothing else; today a whole gate family reported `supported: true`
  while reading an artifact that was never written.
- **Degradation is a named reason, never a silent zero.** If FotMob 403s (and
  `espn_lineups.py` documents a 403 that reproduced ONLY from Render's outbound
  IP), the sim must fall back to volume-based behaviour and SAY SO. Today's
  incident: a silent zero-lineup path logged nothing and cost hours.

## 5. Verification that would actually settle it

Not "the field is populated" — that is reachability, not value.

- Backtest on COMPLETED matches via `backtest_soccer_h2h_calibration.py`, whose
  baseline is `reports/soccer_backtest/h2h_calibration_2026-08-15_limit120_n1112.json`.
- The live tier needs its own harness: replay a completed match at N cutoffs
  (`build_live_state` already supports `as_of_seconds`, which is exactly this),
  project from each, and score the projection against the real final total.
  **Compare xG-aware against volume-only on the SAME cutoffs.** That comparison
  is the deliverable.
- **Held-out, not in-sample.** Today's soccer lane fitted `home_advantage_attack_boost`
  for championship, found a clean bracketed optimum, and it FAILED held-out
  validation at +0.0121 Brier worse. Same rule applies here.

## 6. THE ARGUMENT AGAINST, which should be answered first

**The soccer lane has already falsified "another input will help", twice.**

`soccer-model-dispersion`'s pre-registered falsification test ran on 2026-08-20:
every input-quality change that session made — xG double-count, shots-weight
shrink, clean_sheet_rate, possession_share, set_piece_goal_share,
starters_available_share, pace_seconds_per_event, ppda — landed, and the model
still came out **worse than market in 8 of 9 leagues**. The lane's own written
conclusion: *"Do not re-open this list without new evidence that a specific
field is systematically BIASED, not just present or absent."*

Note that **xG double-count is already on that list.** So xG in some form has
been touched before, and the lane concluded the binding constraint is
DISCRIMINATION — specifically bundesliga (AUC gap -0.111) and serie_a (-0.055) —
not input richness.

**And the mechanism-vs-estimator rule bites hard here.** `home_attack_rating`
is CALIBRATED against historical outcomes; it is already absorbing whatever
signal in-match xG would carry. Adding xG as a new mechanism without re-fitting
those rates is the exact shape that produced a NEGATIVE interaction in 4 of 4
markets when two mechanisms were combined.

**So the honest framing is:** this is plausible for the LIVE tier specifically —
where there is no calibrated rate absorbing in-match shot quality, because the
live tier resumes a sim rather than fitting one — and poorly supported for the
PREGAME tier, where the lane's own falsification test already applies.

**Recommended decision: scope (a) only, live tier only, and treat it as a test
of the lane's open question rather than an assumed win.** If it does not beat
volume-only on the cutoff harness, it does not ship.

**USER CONFIRMATION `[2026-08-21, user decision]`, and it is evidence rather
than approval:** the user reports using FotMob's live xG MANUALLY, for the live
tier specifically — reading whether a scoreline reflects the run of play. That
is independent support for exactly the hypothesis (a) encodes, from someone
acting on it with their own money, and it is the kind of signal that exists
nowhere in the repo. It does NOT relax the verification bar in §5: a human
reading xG in context is not the same claim as a Monte Carlo conditioned on an
xG total, and the cutoff harness is still what decides. But it does move the
live tier from "plausible" to "worth the spike", and it is the reason pregame
stays out of scope rather than both being deferred.

## 7. Sequencing

1. Spike: capture both reference matches, confirm shape, measure id join. **Output is a go/no-go.**
2. Cutoff-replay harness for the live tier, scoring volume-only. This has value
   on its own — the live totals lens shipped today has no accuracy harness at all.
3. Only then: xG ingestion + live attach, behind a flag, `off != on`.
4. Held-out comparison. Ship only on a win.

**Not in scope:** replacing ESPN. It stays the spine for fixtures, lineups and
live state. FotMob is an enrichment with a named fallback, or it is nothing.

**Unchanged ceiling:** player props are bounded by our own roster CSVs, not by
any upstream feed. We hold zero Coventry per-90 rows; their confirmed XI was
unusable today whatever the source.
