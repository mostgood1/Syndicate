# SPEC — the live game-line projection

**Status: PROPOSED. Nothing built. No source file edited, nothing deployed.**
Written 2026-08-14 22:2x–22:5x CDT (2026-08-15 03:2x–03:5xZ) for review before
any engine work, per the Tier 5 instruction.

Lane: `live-game-line-projection`.

Deployed commits, re-read in the step that uses them:

| service | live commit | note |
|---|---|---|
| web `srv-d88ahvrbc2fs73eodu30` | `c774fe1a` | live 03:29:56Z |
| refresh-worker `srv-d91dpertqb8s73co8ls0` | `eea7554a` | **`update_in_progress` at read time** |
| live-odds-worker `srv-d91dpertqb8s73co8lt0` | `ccd10349` | live since 08-14 19:24Z; **not an ancestor of `origin/main`** |

My checkout was **128 commits behind `origin/main`** when this work started, and
the first counter I chased (`liveLensLiveGamesEnriched`) exists in neither local
tree. Everything below that cites code cites the **deployed** tree by SHA.

---

## 0. THE HEADLINE — the premise is false, and that changes the whole scope

> "No live game-line projection exists. `predictions.full` IS THE PREGAME SIM."

**That is true of what is PUBLISHED and false of what is COMPUTED.**

A live game-line projection runs in production right now. `estimate_live()` is
called with a `LiveSituation` carrying the current inning, half, outs, base
state, score, current batter, current pitcher, ball/strike count and per-pitcher
usage, and it returns:

```python
"homeWinProb":  round(float(result.home_win_prob), 4),
"awayWinProb":  round(float(result.away_win_prob), 4),
"total":        round(float(result.avg_total_runs), 2),
"homeMargin":   round(float(result.avg_home_runs) - float(result.avg_away_runs), 2),
"source":       "live_mc",
```

`vendor/mlb_bettingv2/tools/web/flask_frontend.py:16573` (`_live_mc_projection`),
returning at :16680. It is wired into `_build_game_lens` (:16806), which stamps
`modelHomeWinProb` and a `live`/`full` lane per live game and prices them against
the live h2h / spread / totals market rows.

**This is not scaffolding and not a stub. It is the thing Tier 5 says needs
building, already built, already running, and thrown away before it reaches an
artifact.**

So the deliverable is **publication, plumbing and a precision decision** — not a
modelling build. That is a large reduction in scope and risk, and it is the one
finding that should be checked hardest before anything is committed to it.

### How I know it runs (production evidence, not code reading)

`_live_mc_projection` instruments **every** failure exit with a
`LIVE_MC_BAIL reason=...` line printed with `flush=True`, so it reaches Render's
collector. Every card in the slate calls it unconditionally, before any status
branch. On live-odds-worker:

```
100 log lines, 03:06:14Z → 03:24:14Z, all: reason=status_not_live abstract='Final'
per-tick bail counts: 9,9,9,9,9,9,9,9,9,9,9  (11 consecutive complete ticks)
```

The slate at that moment was **14 games: 9 Final, 5 Live** (the published report's
own `counts`). Nine bails per tick, every tick, all of them `status_not_live` —
so all 14 games reach the call, the 9 Final ones refuse correctly, and **the 5
live games emit no bail at all**, on every tick.

**Stated honestly:** this is proof by exhaustion of the instrumented exit set,
and there is exactly **one uninstrumented exit** — `if away_score is None or
home_score is None: return None` (:16610) returns bare `None` with no bail. A
live game with a snapshot essentially always carries both scores, so this is a
narrow hole, but it is a hole and the conclusion rests on it. **The first build
step closes it** (§6.1) so this stops being an inference.

---

## 1. Where it goes, and the three independent places it dies

### Drop 1 — the merge rejects the MC lens for exactly the live games

`syndicate/features/mlb/live_lens.py:1094`:

```python
should_use_projection_lens = projection_game_lens and (
    not card_game_lens
    or not card_is_live_or_final
    or (projection_game_lens_has_signal and not card_game_lens_has_signal)
)
```

For a live game all three disjuncts are False:

- `not card_game_lens` — False. The card path builds its own lens in
  `_live_lens_segments_from_card` (:650) from card **text**
  (`_parse_number_text(row.get("foot_right"))`, `...("home_win")`).
- `not card_is_live_or_final` — False by construction; the game is live.
- `projection_game_lens_has_signal and not card_game_lens_has_signal` — False,
  because `_lens_rows_have_projection_signal` (:744) returns True on *any* of
  `away/home/total/homeMargin` parsing as a number, and the card's
  text-derived lens carries `total` and `homeMargin`.

**So the branch written to prefer the live-state lens is False on precisely the
live games.** The card's pregame-derived interpolation wins over the live
simulation, and the comment above it — "cards stay the reliable primary source" —
is describing props, where it is correct, and silently governs the game lens too.

This is the **same shape** as the already-diagnosed prop sever at :1109, in the
same function, fifteen lines earlier. It is a second instance of one bug, not a
second bug.

### Drop 2 — the published report is the slim shape and has no `gameLens` at all

`scripts/refresh_mlb_oddsapi.py` (deployed `ccd10349`, :764) fetches the live-lens
report **over HTTP in slim mode** — its own docstring: *"always the slim shape …
`{gamePk, startTime, status}` only, no trackedProps"* — then backfills live props
for live games (`liveLensLiveGamesEnriched`). That is the payload published to
web as `mlb_source/data/live_lens/live_lens_report_*.json`.

Measured on the published copy, 03:26:47Z:

```
counts   {'games': 14, 'live': 5, 'final': 9, 'liveLensLiveGamesEnriched': 5}
perf     {'cardsFallback': True, totalMs 0.0, gameLensMs 0.0, feedFetchCount 0}
gameLens rows: 0        modelHomeWinProb: 0
```

**Fixing Drop 1 alone changes nothing that crosses to web**, because this path
carries no `gameLens` field to carry it in. Both must be fixed, or the live lens
must be published by the path that actually has it.

### Drop 3 — nothing downstream consumes a live game-line projection

- `"predictions": card.get("predictions")` — the vendored payload's `predictions`
  block **is the card's pregame block, verbatim** (:17345). So `predictions.full`
  is pregame *at source*; no merge line is discarding a live value there.
  (I initially read `live_lens.py:1127` as a third sever of the same shape. It is
  not — there is no live `predictions` to discard. Correcting it here rather than
  carrying it.)
- `shared/live_projection_join.py` is **entirely prop-shaped**: `build_live_prop_index`,
  player-name keys, a prop market alias table, and `THE EDGE PRICES
  liveModelProbOver AND NOTHING ELSE (#414)`. **There is no game-line join.** This
  is the one genuinely new module the deliverable needs, and it is small.

### What the served surface actually shows (production, 03:3xZ)

`/mlb/api/live-lens`, 14 games, 56 `gameLens` rows:

```
('Live', 'first1', None) 5      ('Final', 'first1', None) 9
('Live', 'first3', None) 10     ('Final', 'first3', None) 18
('Live', 'first5', None) 5      ('Final', 'first5', None) 9
modelHomeWinProb present on: 0 of 56
```

Three lanes, `source: None`, no probability. `_build_game_lens` produces six lanes
(`live, first1, first3, first5, first7, full`) each stamped with a `source`. **What
is served is the card-derived lens; the MC lens is absent from the published
surface entirely.** Drop 1's *effect* is confirmed in production.

**The remaining discriminator, named rather than assumed:** "the merge rejected
it" vs "the MC payload never reached the merge on this service" are both
consistent with what is served. The bail evidence favours the former (the payload
ran in-process on that worker), but it is not settled. §6.1 settles it in one
step, before any fix.

---

## 2. The stated prerequisite — re-derived, and it does NOT block this work

The brief says to establish the real cadence first, because MLB odds capture runs
on a ~121.6-minute beat and "a live edge product priced off a two-hour-old quote
is not live in any meaningful sense." **That is correct about the pregame regime
and does not bind a live product.** I re-derived both halves myself, because this
changes the sequencing recommendation and a cross-lane number that changes a
recommendation has to be my own measurement.

**(a) The deployed tree.** On `ccd10349` (live-odds-worker — the service that owns
capture), `syndicate/features/shared/live_refresh_loop.py`:

```
4429:  effective_phase = ("live" if any_live else "pregame") if adaptive_enabled else _live_refresh_loop_phase()
4587:  if not skip_launch and effective_phase == "pregame" and _pregame_relaunch_blocked(...):
```

The 1800s global cooldown is reachable **only** when no game is live.

**(b) Production, same-instant.** `/api/ops/live-refresh/state` at 03:30:58Z:
`latest_tick.adaptive = true`, `anyLive = true`, `phase = "live"`. And
`[live_lens_loop] TICK_COMPLETE … nextIntervalSeconds=60`.

**Conclusion: during a live slate the cooldown is bypassed and capture runs on the
60 s tick.** The 121.6-minute figure is the empty-slate pregame regime only.

**Therefore `0.1` (`odds/pregame-cooldown-per-sport`) is NOT a prerequisite for
this lane** and should not be sequenced in front of it. It remains the right fix
for the *pregame* board's freshness, and it still carries its OddsAPI cost against
a cap at 92.8% projected burn — but that decision is independent of this one, and
holding the live work behind it would be holding it behind an unrelated fix.

This is a correction to the brief's sequencing, not to its facts.

---

## 3. The spec

### 3.1 What it consumes

Everything already exists on the worker; no new source, no new fetch, no new
OddsAPI spend.

| input | where from | already present? |
|---|---|---|
| live game state (inning, outs, bases, score, batter, pitcher, count) | `_load_live_lens_snapshot` off the StatsAPI feed | yes |
| rosters + pregame sim context | `_load_sim_context_for_game` | yes |
| live game-line market quotes (h2h / spread / totals) | `_load_game_line_market_index` | yes |
| the simulation itself | `estimate_live(...)`, 120 sims/live game | **yes — already running** |

### 3.2 What it emits

One block per live game, on the live-lens snapshot, additive — nothing existing
changes shape:

```jsonc
"liveGameLine": {
  "source": "live_mc",
  "generatedAt": "<iso>",
  "gameState": {"inning": 7, "half": "top", "outs": 1, "awayScore": 3, "homeScore": 4},
  "simsRun": 120,
  "homeWinProb": 0.6842,
  "awayWinProb": 0.3158,
  "projTotal": 8.31,
  "projHomeMargin": 0.74,
  "probStdErr": 0.0425,        // sqrt(p(1-p)/simsRun) -- see §4
  "priceable": true            // false when probStdErr exceeds the edge floor
}
```

`priceable` is the load-bearing field. It is the refusal that keeps §4's
precision problem from silently becoming published edges.

### 3.3 Where it runs

**Nowhere new.** It runs where it already runs — inside the live-lens tick on
live-odds-worker — and the change is that its output is retained, published and
joined instead of discarded.

- **No new periodic work on refresh-worker.** `learnings.md` records that worker
  periodic work is never free and that `#241` caused a production restart loop.
  This lane adds none.
- **No request-path compute.** Web reads the artifact. `refuse_if_compute_in_request_path`
  stays exactly as it is.
- **Not the board-build loop, not `pipeline/intelligence_state.py`.** Untouched.

### 3.4 What it costs per tick

**The simulation cost is already being paid and this lane does not raise it.**
5 live games × 120 sims, once per 60 s tick, today, on both workers.

The *new* cost is bytes and one join:

| item | measured | after |
|---|---|---|
| `live/mlb_live_lens.json` (keyvalue) | **1,384,264 B** — already over the 1 MB `KEYVALUE_WRITE_LARGE` warn, under the 8 MB max | + ~5 × 400 B ≈ **+2 KB** |
| live-odds-worker container | **1,713–1,814 MB of 2,048 MB (83.7–88.6%)** | unchanged — no new allocation |
| OddsAPI credits | — | **zero** — consumes quotes already fetched |

**The memory line is the one to watch, and it is not this lane's doing:**
live-odds-worker is already running at 84–89% of a 2 GB ceiling. This lane must
not add to it, which is why the design is "retain and publish what is computed"
rather than "compute more". Any proposal to raise the sim count (§4) lands
directly on that number and must be measured there first.

**Flagged, not mine:** `[live_lens_loop] published_hot_artifacts count=1
failed=20` at 03:20:30Z — 20 of 21 publishes failing in that tick. If the publish
path is unreliable, publishing more through it inherits that. Worth a look by
whoever owns the publisher.

---

## 4. The one real modelling decision: 120 sims is too few to price an edge

This is the part that genuinely needs a product call, and it is the reason this
spec exists rather than a patch.

A win probability from **n = 120** Bernoulli trials has a standard error of
`sqrt(p(1-p)/n)`:

| p | SE at n=120 | 95% interval |
|---|---|---|
| 0.50 | **±4.56 pp** | ±8.9 pp |
| 0.75 | ±3.95 pp | ±7.7 pp |
| 0.90 | ±2.74 pp | ±5.4 pp |

To publish a **2-point** edge you need the noise well under two points. Required
n for a target SE at p = 0.5:

| target SE | n |
|---|---|
| 2.0 pp | 625 |
| 1.0 pp | **2,500** |
| 0.5 pp | 10,000 |

**120 sims is roughly 20× too few for 1 pp resolution.** It is entirely adequate
for the display number it was built for and inadequate for pricing against a
Pinnacle line.

**And the noise does not average out.** `seed=int(gamePk)` is fixed, so the
estimator is deterministic per game: consecutive ticks re-draw the *same*
pseudo-random stream from a slightly different state. The error is a
**state-correlated bias, not tick-to-tick jitter** — you cannot smooth it by
averaging consecutive ticks, and a chart of it will look reassuringly stable
while being wrong by the same 4 points all inning.

`MLB_LIVE_GAME_MC_SIMS` is env-tunable (default 120, minimum 20), so this is a
config change, not a code change — but the cost is linear and it lands on a
worker already at 84–89% of 2 GB.

**Three options, and I recommend the first:**

1. **Ship it refusing to price, at 120 sims.** Publish the projection with
   `probStdErr` and `priceable: false` wherever the interval swamps the edge. The
   number becomes visible and honest immediately, at zero added compute, and the
   live game line stops being pregame. **This is the option that makes the stated
   premise true without spending anything.**
2. **Raise the sim count**, measure the wall-time and memory cost on
   live-odds-worker first, and price only above the resulting precision floor.
   Real, but it spends headroom on the tightest container in the fleet.
3. **Keep the display number and never price it.** Honest, cheap, and concedes
   the live edge product.

Option 1 is reversible, measurable, and leaves 2 available once someone knows
what a sim actually costs there. **Nobody has measured that yet** — the published
`perf` block is zeroed on every copy reachable from web (`cardsFallback: True`),
so `gameLensMs` for a real MC pass is unmeasured. That measurement is §6.2.

---

## 5. How the counters stop being 0

**`rows_live_edged` is a PROP counter and this lane does not move it.** It lives
on the book-grid artifact and is fed by `live_projection_join`, whose input is
`liveModelProbOver` on prop rows. Its zero is caused by the prop sever at
`live_lens.py:1109` plus a 91% market-alias miss. **Saying this lane will fix
`rows_live_edged` would be wrong, and the brief's framing invites that error.**

What this lane moves is the **game-line** equivalent, which does not exist yet
and must be created alongside it:

```
rows_live_gameline_considered   live game-line markets seen on the grid
rows_live_gameline_projected    ... with a liveGameLine block joined
rows_live_gameline_priceable    ... whose probStdErr cleared the edge floor
rows_live_gameline_edged        ... carrying a model_edge_pct
rows_live_gameline_withheld     ... refused, BY REASON
```

Success is `rows_live_gameline_edged > 0` **with every withheld row naming its
reason** — the shape `live_edge_policy` already established, so a zero is
diagnosable instead of mysterious.

**The evaluation position is unusually strong here**, which is the best argument
for doing game lines before anything else: per `state.md`, 100% of MLB game-line
markets carry a sharp quote (`pinnacle`, `betfair_ex_eu`, `matchbook`, `novig`,
`prophetx`) while props carry 0%. A live game-line edge can be scored against a
genuine sharp close rather than a soft consensus. **Caveat carried from the
source, not re-derived here** (it does not change the recommendation, only
strengthens it): that was read from the git mirror on a single post-widening date
(08-09) and needs confirming against production before any CLV number is
published off it.

---

## 6. Build order — each step measurable, none of them an engine

**Nothing here is started. This is the proposal.**

1. **Settle the discriminator (read-only, no deploy).** Instrument or locally
   reproduce one live-lens tick against production inputs and record whether the
   MC payload reaches `_enhance_cards_report_with_live_projection` with a
   populated `gameLens`. Also close the one uninstrumented bail exit (§0). Until
   this lands, "the merge rejects it" is well-supported and not proven.
2. **Measure what one MC pass costs** on live-odds-worker (wall ms and peak
   anon), since §4's options all price off a number nobody has.
3. **Drop 1** — make the merge prefer a live-state lens over a text-derived one
   for live games. One condition, one test that a live game's `source` is
   `live_mc` and that a pregame game is byte-identical.
4. **Drop 2** — carry `gameLens`/`liveGameLine` through the published path.
5. **The join** — the game-line sibling of `live_projection_join`, with the
   counters in §5 and a `priceable` gate wired to `live_edge_policy`'s vocabulary.
6. **Measure on the published artifact**, never through `/mlb/api/live-lens`.

Steps 3–5 are the only ones that write source, and each is small. **No deploy
from this lane while `#435` holds refresh-worker.**

---

## 7. Explicitly out of scope

- `syndicate/features/soccer/**`, including `soccer/features/live_lens.py` — the
  unwired soccer live projector (`project_live_match`, an `initial_state` hook
  on `simulate_match`). It is a real second reference implementation and it is
  **claimed by the OPEN `soccer-model-coverage` lane**. Named here so it is not
  rediscovered later; not touched.
- `shared/nfl_game_projections.py` — the 5 wrongly-published live NFL edges.
  **Claimed by OPEN `nfl-live-edge-suppression`.** Correct, urgent, theirs.
- `pipeline/intelligence_state.py`, the board-build loop, refresh-worker memory
  (`#435`), the recommendation/CLV modules, soccer card templates.
- The prop sever at `live_lens.py:1109` and the 91% alias miss — the same
  function, but a different product surface with a different owner. This lane
  touches the game-lens branch only.

Collision-checked by executing `lane-guard.py`'s own `_claims()` over all 23
claims held by the 4 OPEN lanes that hold any. Every file this lane proposes to
touch is free; `nfl_game_projections.py` is the only candidate that was claimed,
and it is excluded above.

---

## 8. Questions for review

1. **§4 — option 1, 2 or 3?** The only question that needs a product answer.
   Recommendation: **1** (publish, refuse to price, zero added compute), leaving
   2 open once step 6.2 says what a sim costs.
2. **Is the game-line join worth building before the prop path is unsevered?**
   Game lines have a sharp reference and props do not, which argues yes.
3. **Confirm the sequencing correction in §2** — that `0.1` is not held in front
   of this work, and is re-decided on its own pregame merits.

---

## 9. Reproducing every number here

```bash
# the MC runs, and bails only on Final games (9/tick against 9 Final, 5 Live)
curl -s -H "Authorization: Bearer $RENDER_API_KEY" \
  "https://api.render.com/v1/logs?ownerId=tea-d2bb5n95pdvs73cje4fg&resource=srv-d91dpertqb8s73co8lt0&text=LIVE_MC_BAIL&limit=100"

# the published report: no gameLens, cardsFallback true
curl -s -H "X-Admin-Token: $ADMIN_TOKEN" \
  "https://syndicate-an21.onrender.com/api/ops/artifacts/stream?path=mlb_source/data/live_lens/live_lens_report_2026_08_14.json"

# the served surface: 3 card-derived lanes, source null, zero modelHomeWinProb
curl -s "https://syndicate-an21.onrender.com/mlb/api/live-lens"

# the phase is live, so the 1800s pregame cooldown is bypassed
curl -s -H "X-Admin-Token: $ADMIN_TOKEN" \
  "https://syndicate-an21.onrender.com/api/ops/live-refresh/state"
```

```bash
git show ccd10349:syndicate/features/shared/live_refresh_loop.py | sed -n '4429p;4587p'
```

**Instrument warning, measured:** web's `/mlb/api/live-lens` and web's copy of
`mlb_source/source_artifacts/data/live_lens/live_lens_report_*.json` are **web's
own cards fallback** (`cardsFallback: True`, `simContextAvailable: False` on
14/14 games, `perf` all-zero). They cannot observe the Monte Carlo and will
return a false negative for any live-sim work. Use the worker-published copy
under `mlb_source/data/live_lens/` and the `LIVE_MC_BAIL` log lines.
