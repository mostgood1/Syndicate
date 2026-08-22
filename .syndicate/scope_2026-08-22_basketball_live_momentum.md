# SCOPE — live-lens attack momentum for basketball (NBA / WNBA / NCAAB)

Drafted 2026-08-22 in response to "replicate soccer's live-lens momentum for
every sport, starting with basketball; it has to be artifact driven."
**Not started. No lane claimed, no code written.** This is a scope: §3 and §7
contain decisions that should be settled before any module exists.

Soccer's implementation landed on `origin/main` at `83589e54` ("momentum as a
DRAWN CHART"). Everything below is measured against that tree.

---

## 1. What soccer's momentum actually is — six pieces, two of them soccer-specific

| Piece | Where | Portable? |
|---|---|---|
| Weights + causal decay math | `soccer/features/momentum.py` | math YES, weights NO |
| Producer (writes the artifact) | `scripts/poll_soccer_live_state.py:187` `_momentum_block` | pattern YES |
| Worker→web transfer | `artifact_publisher.py:547` `soccer_source/*/api/live_state/live_state_*.json` | pattern YES |
| Reader (artifact → chart data) | `soccer/cards.py:1466` `_momentum_chart`, `:1528` `_momentum_section` | **verbatim** |
| Render | `templates/shared/_game_card_generic.html:190-245` | **already shared by every sport** |
| Validation harness | `scripts/soccer_momentum_leadlag.py` | pattern YES |

Three design decisions in that module are the actual intellectual content, and
all three carry over unchanged:

1. **The scoring event is EXCLUDED from the series** (`include_goals=False`).
   A series that counts goals spikes AT the goal, so it correlates with goals
   by construction and predicts nothing. Any vendor panel with a peak exactly
   on a goal marker has this property.
2. **`momentum_at` is strictly causal** — events after `t` are skipped, not
   clipped. Without this the lead/lag test passes trivially and means nothing.
3. **`supported` / `reason` rather than a bare zero.** A flat series and an
   absent one are different states. This is `model_engine_standard.md`'s
   neutral-default trap applied to a display field: `.get(k, 0.0)` makes an
   unfed series indistinguishable from a balanced match.

The measurement that licenses the panel existing at all
(`poll_soccer_live_state.py:356`, measured 2026-08-21): two minutes before a
goal, momentum favours the side that scores by **+1.141 against a control mean
of 0.000, Cohen's d = +0.397, n=76 pre-goal / 638 control.**

**Basketball gets no panel until it has its own version of that number.**

---

## 2. What basketball already has — measured, not assumed

**The UI is free.** `_game_card_generic.html` is rendered by every sport via
`shared/game_cards_board.html` (nba, wnba, ncaab, nhl, nfl, ncaaf, mlb
blueprints all call it). The SVG chart renders the moment a cards builder sets
`game["shared_momentum"]`. `mom_uid` keys off `game.event_id`, which every
basketball game carries.

**The clock model is already solved and already tested.**
`shared/game_shape.py:483` `basketball_elapsed_minutes(period, clock, *,
quarter_minutes, ot_minutes, regulation_periods)` — handles OT, strict `M:SS`
parsing, and is pinned by
`test_basketball_elapsed_minutes_agrees_with_the_wnba_implementation` so it
cannot drift from `wnba/cards.py:_wnba_elapsed_minutes`. `_BASKETBALL_RULES`
(`:478`) covers `nba` (12') and `wnba` (10'). **NCAAB is absent** and needs
adding — men's 2x20, women's 4x10.

**A worker-side live tick already runs.** `live_lens_loop.py:150`
`_LIVE_LENS_SPORTS = ("mlb", "nba", "wnba", "soccer", "nfl")`, each with a
`build_live_lens_snapshot()` wrapper (`nba/live_lens.py:563`). NCAAB is not in
it; `ncaab/live_lens.py` has no snapshot builder at all.

**The ESPN plays parser exists and WORKS** —
`vendor/nba_betting_repo/app.py:2349` `_live_espn_actions_from_summary`, emitting
`teamTricode / actionType / shotResult / isFieldGoal / shotValue / period /
clock / scoreHome / scoreAway / description`.

**Possessions exist** — the `live_pbp_stats_<date>.jsonl` family carries
`poss_est = FGA + TOV + 0.44*FTA - OREB`
(`vendor/wnba_betting_repo/app.py:3572`), per team and per period.

### 2a. THE GAP, stated precisely

**Nothing persists a per-event, timestamped pressure stream.**
`live_pbp_stats` persists only AGGREGATES (`pbp_attempts`, `pbp_possessions`,
`pbp_recent`). The per-play list is built in-process on the vendor app and
discarded. That stream is the artifact this scope exists to create.

### 2b. Three things measured off the tracked mirror 2026-08-22

Run over all 61 `data/*_source/**/live_snapshots/live_pbp_stats_*.jsonl`
(126 game records total):

* **`pointsAttempted` IS present in ESPN's basketball plays.** This was the
  scope's biggest open risk and it is retired. `fga > 0` requires
  `isFieldGoal`, which in `_live_espn_actions_from_summary` requires
  `p["pointsAttempted"] in (2,3)`. Measured: **2,778 attempts across 19
  populated records.** The WNBA pbp endpoint
  (`vendor/wnba_betting_repo/app.py:38643`) sources actions ONLY from that ESPN
  parser, so this is direct evidence about the ESPN feed, not the NBA CDN.
* **Team attribution is clean: 0 of 2,778 attempts land in `UNKNOWN`.** Volume
  splits across real tricodes (TOR 539, SEA 524, NYL 375, PHX 278, LVA 263...).
  This matters more than anything else here — momentum is a SIGNED quantity, so
  an unattributed event is a discarded event.
* **But the buckets are keyed by TRICODE, and `home`/`away` are ZERO.**
  `pbp_attempts["home"]`/`["away"]` exist as dicts and carry 0 on every
  populated record. `game_shape.py:459` already flags this for
  `pbp_possessions` and calls it "a trap for NEW code rather than an active
  bug": a reader that goes straight to `home`/`away` gets a plausible-looking
  zero, not an obvious miss. It is true of `pbp_attempts` too.

**Coverage of that mirror is one date.** 19 of 126 records are populated, all
on **2026-06-27**, 13 distinct games, 17 WNBA / 2 NBA. Per `CLAUDE.md`, the git
mirror is a lossy cold-start net and not evidence about production — any
backtest quoting it must print this denominator.

---

## 3. Where basketball is NOT soccer — three real divergences

### 3a. Scoring is dense, not rare — so publish TWO series

~200 scoring events per basketball game against ~2.7 goals. Soccer's "exclude
the goal" is cheap because goals are a rounding error in the feed; in
basketball, excluding points throws away most of the signal, and including them
reproduces the vendor problem at 100x the rate.

Proposal — one pass, two series:

* **`pressure`** — shot attempts, offensive rebounds, drawn shooting fouls,
  forced turnovers, steals, blocks. **Points EXCLUDED.** This is the series
  that gets lead/lag-validated and the one the chart draws.
* **`scoring`** — actual point differential under the same decay. A narrator by
  construction. Useful for the LABEL ("PHX on a 9-0 run"); **never** to be
  claimed as predictive, and never fed to a model.

Keeping them separate is what stops the second from silently contaminating the
first, which is the exact failure `include_goals=False` exists to prevent.

### 3b. The validation target must be reframed

"Does momentum precede the next basket" is close to meaningless at basketball's
event density. The honest question:

> Does `pressure` at instant `t` predict the point differential over
> `(t, t+180s]`, signed toward the team momentum favours, against control
> instants sampled the same way?

Same Cohen's d reporting as soccer, same strict causality, same requirement
that points be absent from the series being tested.

### 3c. Half-life must be SWEPT, and probably measured in possessions

`DEFAULT_HALF_LIFE_SECONDS = 300.0` is soccer's, and its own docstring calls it
"a CHOSEN constant, not a fitted one -- it should be swept before any number
from it is trusted." Five minutes is roughly two or three attacking sequences
in soccer. In a game with a 24-second shot clock it is ~12 possessions per
side, which is far too long to read as "right now".

Two options, and this is a decision owed (§7):

* Sweep seconds over {60, 90, 120, 180} per league. Simple; needs three
  tunings, and NCAAB pace differs again.
* **Express decay in POSSESSIONS**, using the `poss_est` already computed. One
  constant that ports across NBA/WNBA/NCAAB pace regimes without re-fitting.
  Preferred, but it couples momentum to the pbp aggregate family whose coverage
  §2b just measured as thin — so it needs the capture from Phase B first.

---

## 4. The artifact chain

    ESPN summary plays[]
      -> shared/basketball_momentum.py            (signed weighted events, elapsed-second keyed)
      -> nba|wnba/live_lens.py build_live_lens_snapshot   (PRODUCER, on the worker tick)
      -> (a) data/live/<sport>_live_lens.json     live_momentum_payload   [cross-service]
         (b) <sport>_source/.../live_lens/live_momentum_<date>.jsonl      [backtest record]
      -> HOT_ARTIFACT_PATTERNS                    (transfer)
      -> nba|wnba/cards.py                        (READER -> game["shared_momentum"])
      -> _game_card_generic.html                  (renders, no change needed)

**Fetch discipline:** compute from the summary the pbp payload ALREADY fetches.
Soccer's rule — "computed from the SAME summary already in hand, no extra
request" — is what keeps the tick affordable.

**Two writes, deliberately:**

* **(a) the live-lens aggregate** is the path that actually crosses services.
  `learnings.md` records why: soccer's per-league `live_state` files are written
  with a raw `out_path.write_text()` on one worker while the board builds on
  another, so neither the filesystem nor the keyvalue key resolves. Only the
  aggregate, written through `refresh_state_store`, crosses.
* **(b) the per-tick jsonl append** is what makes the backtest possible at all.
  ESPN's summary is retrospectively complete, so a nightly capture would nearly
  do — but only the per-tick record proves the value we DISPLAYED at instant `t`
  was the causal one we later claim it was.

Allowlist entries needed (the patterns come in twins):

    *_source/source_artifacts/data/live_lens/live_momentum_*.jsonl
    *_source/data/live_lens/live_momentum_*.jsonl

`#208` applies: allowlisting PERMITS a transfer, it does not make one happen.

---

## 5. Phases

**A — pure functions. No wiring, no deploy risk.**
Extract soccer's `momentum_at` / `momentum_series` into
`shared/momentum_core.py` so the platform has ONE causal-decay implementation
rather than seven; soccer imports it back. Add
`shared/basketball_momentum.py` — shared rather than per-sport, matching the
`basketball_props_*.py` / `basketball_live_artifacts.py` precedent, since
NBA/WNBA/NCAAB differ only in period geometry and tricode maps. Key every event
on `basketball_elapsed_minutes`, never on raw display clock. Unit tests against
a captured summary fixture.

**B — capture only. Producer writes; nothing reads.**
Extend `build_live_lens_snapshot()` in `nba/live_lens.py` and
`wnba/live_lens.py`. Land the allowlist entries. Proves the data exists before
any surface claims it does.

**C — validate. This is the gate.**
`scripts/basketball_momentum_leadlag.py` against §3b's target. Sweep half-life
and weights HERE, and take the defaults from the sweep rather than from soccer.
**WNBA is the only basketball league that can be validated live this week** —
NBA is out of season on 2026-08-22, NCAAB not until November.

**D — reader + card.** Only after C returns a number. Lift soccer's
`_momentum_chart` into `shared/momentum_card.py` (it already emits normalised
`x in [0,100]`, `y in [-1,1]` points with per-match peak scaling) and have both
sports call it. One template change: `"Attack momentum"` becomes a passed-in
title so basketball can say "Run pressure".

**E — the rest of the platform.** NCAAB (add to `_LIVE_LENS_SPORTS` AND
`_BASKETBALL_RULES`), then NHL (shots / hits / zone time — the closest
analogue to soccer), then NFL (a different animal: the play is the unit and the
clock stops, so seconds-decay is the wrong axis entirely).

---

## 6. Risks, and what is NOT verified

* **Which service EXECUTES decides whether this is live.** Soccer's
  `live_state` — and therefore its momentum — is written by **refresh-worker**
  (`SYNDICATE_ENABLE_SOCCER_WEEKLY_REFRESH_AUTORUN`), NOT by the worker whose
  name says live. Worse, per `learnings.md` 08-22: the live-lens loop runs on
  BOTH workers writing the same aggregate, so a partial deploy makes the
  feature **FLICKER** — whichever service ticks last wins. A clean zero is
  easier to diagnose than intermittent truth. Resolve the executing service
  from env and routing, then check THAT SHA.
* **Lane conflict, unresolved.** `soccer-board-mlb-parity` is OPEN and owns
  `soccer/cards.py` and `_game_card_generic.html`, with "momentum on a live
  card" still on its OWED list. Extracting soccer's chart into shared touches
  its files. **Mitigation: build basketball's own copy in Phase D and extract
  to shared once that lane closes.** Do not edit across lanes.
* **`wnba-halftime-elapsed` is OPEN** and is precisely the clock-derivation
  class of bug this depends on. Reuse whatever it landed; do not re-derive.
* **`nba/cards.py:1109` fetches ESPN summaries on the WEB REQUEST PATH**
  (`_public_live_player_boxscore_payload`). Pre-existing worker-split
  violation, out of scope to fix here — but the momentum path must not route
  through it.
* **ESPN is unreachable from a Claude Code session** — the agent proxy returns
  403 for `site.api.espn.com` and `site.web.api.espn.com`. Fixtures must be
  captured on a worker or pulled from production
  (`/api/ops/artifacts/export`), never fetched locally.
* **Unverified: the weights in §3a.** They are a proposal ordered by how
  strongly each event says "this team is threatening right now", exactly as
  soccer's are. No basketball number justifies any of them yet. Phase C, not
  before.
* **Unverified: NCAAB's feed.** Everything in §2b was measured on WNBA (17 of
  19 records) and NBA (2). NCAAB's ESPN surface, tricode coverage, and men's-vs-
  women's period geometry are all untested.

---

## 7. Decisions — ANSWERED 2026-08-22 by the user

**1. Decay axis: PUBLISH BOTH, DECIDE IN PHASE C.** Phase B writes the
seconds-decayed series AND `poss_est` alongside in the same artifact; the
Phase C sweep settles which axis wins with data rather than a Phase A guess.
This is why the item stopped blocking Phase B: the question does not need an
answer to make progress, only to make a *choice*, and the choice is deferred to
where the evidence will be.

**2. The narrator series IS published, under a name that cannot be mistaken.**
Phase C needs it as the outcome variable and re-deriving it later is worse.
Published as **`scoring_narrator`**, never `scoring_momentum` — `learnings.md`
2026-08-21 FORBIDS publishing a field under a name that describes a different
quantity, and "momentum" on a series that counts points is exactly that.

**3. Sim input: NOT DECIDED, and deliberately not needed yet.** Momentum is
display-and-validation only until Phase C returns a number. If pressure does
not lead scoring the question is moot; if it does,
`model_engine_standard.md` binds in full (input checklist over
`dataclasses.fields()`, reachability test, and a re-fit of whatever rates were
absorbing the mechanism).

**4. Deploy posture: BUILD PHASE B, STOP BEFORE DEPLOY.** The producer and the
allowlist land on the branch; nothing reaches production without a separate
decision. Consequence, stated because it is a real cost: Phase C slips past
this week's WNBA slate, and WNBA is the only basketball league in season.

### 7a. LANE COLLISION, found at Phase B planning — this SHAPES the build

`syndicate/features/wnba/live_lens.py` is claimed by
`layer2-sim-view-and-live-projection` (OPEN). `live_lens_loop.py` is claimed by
`soccer-board-mlb-parity`. Neither may be edited from this lane.

**Resolution: Phase B is built as a SCRIPT plus a shared module, which is
soccer's own shape** — `scripts/poll_soccer_live_state.py` is a script the loop
imports, not code inside `features/soccer/`. So the producer lands entirely in
unclaimed files:

    syndicate/features/shared/basketball_momentum_artifacts.py   NEW
    scripts/poll_basketball_momentum.py                          NEW
    syndicate/features/shared/artifact_publisher.py              allowlist only

**WHAT THIS LEAVES UNDONE, AND IT MUST NOT BE MISREAD AS WIRED.** Nothing calls
the script. Adding it to `live_lens_loop._LIVE_LENS_BUILDERS` (or to the two
sports' snapshot builders) is a one-line change in a claimed file and is part
of the deploy step the user has deferred. This is `#208`'s lesson in a second
guise: a producer that exists and a producer that RUNS are different states,
and so are an allowlisted pattern and a transferred artifact. Phase B ships
capture CAPABILITY, not capture.

## 8. Original framing of the decisions (kept — this is what was owed before §7 answered them)

1. **Seconds or possessions for the decay axis** (§3c). Possessions is the
   better answer if `poss_est` coverage in PRODUCTION (not the mirror) is
   adequate — which Phase B measures.
2. **Whether `scoring` is published at all**, or whether the label should be
   derived from the pbp `current_scoring_run` that already exists. Publishing a
   narrator series alongside a predictor invites someone downstream to feed the
   wrong one to a model.
3. **Whether momentum is ever allowed to become a SIM INPUT.** If yes,
   `model_engine_standard.md` binds in full: a gating input checklist over
   `dataclasses.fields()` (never a name grep), a documented pipeline trace, a
   reachability test (`off != on`) before any correctness test, and — because
   this is adding a MECHANISM to a calibrated engine — a re-fit of whatever
   rates were previously absorbing it. Measured precedent: two mechanisms added
   together produced a NEGATIVE interaction in 4 of 4 markets.
4. **Deploy shape.** Phases A-D are `.py` only, so pushing is free
   (`autoDeploy = no`). **If any phase adds an env knob, that is a
   `render.yaml` change, which fires `blueprint_sync` and applies to
   production regardless** — needing all three service claims and a live-vs-
   blueprint env diff first. Prefer a hardcoded default over a knob until C
   returns a number worth making configurable.
