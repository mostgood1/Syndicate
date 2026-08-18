# Research — what is the MLB sim missing? Data, and modelling

> 2026-08-17, lane `convergence-phase7-crps`. Read from the engine source and
> from 450 batter / 449 pitcher profiles in production-written roster artifacts
> (schema v4, 06-15..06-27).
>
> **ACCESS CAVEAT, stated first.** `/api/ops/artifacts/stream` returns **403 on
> `roster_objs/` paths** (it serves `daily_summary` fine with the same token), so
> I could NOT read production roster profiles directly. Everything below rests on
> mirrored artifacts that production WROTE, plus the code path. The mirror is
> date-lossy, not field-lossy — a mirrored file is what production emitted for
> that date — but **whether TODAY's production populates these fields is
> unverified**, and that is a real gap someone with disk access should close in
> five minutes.

---

## 0. The headline

**The single largest gap is not missing modelling — it is a modelling dimension
that is fully built, actively sampled, and fed nothing.**

Pitch-type effectiveness. The sim picks a pitch from each pitcher's real arsenal
on every pitch, and then that choice **cannot affect any outcome**, because every
multiplier it would flow through is empty and defaults to 1.0.

---

## 1. Built, consumed, and UNFED — fix these first, no new modelling required

### 1a. Pitch-type effectiveness — **0% populated, 100% inert** `[measured]`

| feature | populated |
|---|---|
| `pitcher.arsenal` | **100%** (449/449) |
| `batter.platoon_mult_vs_*` | 98.7% |
| `batter.venue_mult_*` | 98.4% |
| **`batter.vs_pitch_type`** | **0.0%** (0/450) |
| **`pitcher.pitch_type_whiff_mult`** | **0.0%** (0/449) |
| **`pitcher.pitch_type_hr_mult`** | **0.0%** (0/449) |
| **`pitcher.statcast_splits_n_pitches`** | **0.0%** (0/449) |

**The sim consumes all four** — `simulate.py:1067, 1068, 1097, 1099` and
`:2779-2796` — each as `.get(pitch_type, 1.0)`. Empty map -> multiplier 1.0 ->
**a slider and a fastball are interchangeable.**

**The full causal chain, evidenced end to end:**

1. `_apply_cached_statcast_pitch_splits` (`build_roster.py:75`) applies them.
2. It calls `fetch_pitcher_pitch_splits`, which is **CACHE-ONLY** — it reads
   `cache.get("pitcher_pitch_splits", …)` and **returns None on a miss. It never
   fetches.** Its own docstring: *"Populate the cache using the x64 fetch tool:
   `tools/statcast/fetch_pitcher_pitch_splits_x64.py`"*.
3. The statcast cache holds **1,282 files in exactly one namespace: `bvp`**.
   **The `pitcher_pitch_splits` namespace has never been written.**
4. So the populator is a **manual, offline, x64-only tool that is not part of the
   daily pipeline**, and it appears never to have been run.

**Why this is the top priority:** the model, the sim's consumption, the loader,
the cache and the fetch tool ALL EXIST. This is a pipeline wiring job, not a
modelling project — and pitch-type matchup is one of the strongest known signals
in baseball (a pitcher's slider whiff rate against a batter's slider weakness is
exactly the kind of edge soft prop books do not price).

### 1b. Batter-vs-pitcher history — cached 1,282 files, **never reaches the sim**

`statcast_bvp.py` exists, `daily_update.py` fetches it, 1,282 files are cached —
and **`simulate.py` contains no reference to `bvp` at all.** The data is
collected every day and consumed by evaluation tooling only.

### 1c. `pinch_hit_aggressiveness` — loaded onto `ManagerProfile`, read by nothing

Already recorded 2026-08-17. Same shape: a knob with no consumer.

---

## 2. Genuinely ABSENT modelling, ranked by expected value

### 2a. **No defensive quality, anywhere.** `[measured — zero matches]`

No OAA, DRS, UZR, no team or per-player fielding term. `inplay_hit_rate` is a
batter x pitcher property, so **BABIP is modelled with no defence behind it.**
Two teams with identical pitching give identical hit outcomes regardless of who
is fielding.

This is the largest true modelling hole. Defence explains real, persistent
variance in BABIP, and it is a team-level input the market prices and this engine
cannot express.

### 2b. ~~**No batted-ball type model.**~~ **WRONG — CORRECTED 2026-08-17**

**RETRACTED.** The model EXISTS and the sim CONSUMES it:
`simulate.py:1120-1136` reads `bb_gb_rate` / `bb_fb_rate` / `bb_ld_rate` /
`bb_pu_rate` for BOTH batter and pitcher, with league-average fallbacks
(0.44/0.25/0.20/0.11). **All four are 0% populated on 720 batters and 717
pitchers**, so every player runs on the same defaults — a ground-ball specialist
and a fly-ball slugger are identical in the sim.

I searched `ground_ball|fly_ball|line_drive|launch_angle|exit_velo|gb_rate` and
called it absent. The fields are prefixed **`bb_`**, my pattern missed them, and
I reported an ABSENT MODEL where there is an UNFED one. **This belongs in §1
(built and unfed), not §2 (absent).** The original text follows for the record.

### 2b-original (superseded). **No batted-ball type model.** `[measured — no GB/FB/LD, no launch angle, no exit velocity]`

`inplay_hit_rate` is a single scalar. There is no ground-ball / fly-ball /
line-drive split, which has three consequences:

- **park factors cannot interact with a batter's profile** — the engine has
  `park_hr_weight`, but a fly-ball hitter and a ground-ball hitter respond to a
  hitter's park identically, which is wrong;
- **no HR/FB modelling** — HR is its own flat rate rather than a batted-ball
  outcome;
- **defence could not be applied even if it existed**, since defensive value is
  concentrated on balls in play by type.

This is the prerequisite for 2a doing real work.

### 2c. **No catcher framing.** Framing moves called strikes, which moves K and
BB — the two highest-frequency prop markets. The engine models the umpire
(`UmpireFactors`, a called-strike multiplier) but not the catcher, which is the
larger and more persistent effect.

### 2d. **No batter fatigue or availability.** `availability_mult` exists on
`PitcherProfile` only. No rest-day, no consecutive-games, no injury-return ramp
for hitters.

### 2e. **No explicit recency weighting.** Profile rates read as season
aggregates (Schwarber k_rate 0.343, bb_rate 0.145 — full-season shaped). No
visible time-decay or hot/cold term, so a hitter who changed level mid-season is
modelled at his average.

---

## 3. What IS there, and is good — do not rebuild these

Statcast-sourced arsenals (100%), platoon splits both directions (98.7%), venue
multipliers (98.4%), per-venue HR multipliers, umpire called-strike model, park
and weather weight hooks, pitcher stamina and role, bullpen leverage selection,
SB attempt/success, and now position-player substitution (`#440` P2, off).

**The engine is more sophisticated than its output suggests.** Its problem is
that several of its best features are unfed.

---

## 4. Where a market beat is most likely

Ordered by (expected signal) x (probability the market misprices it) / (cost):

1. **Pitch-type matchup (1a).** Everything exists; it needs a cache populated.
   Soft prop books price K props off season rates, not off arsenal-vs-weakness.
2. **Catcher framing (2c).** Cheap to add as a called-strike multiplier beside
   the umpire term that already exists, and it moves K/BB props directly.
3. **Batted-ball types (2b) then defence (2a).** Higher cost, and the pair
   unlocks park interaction and total-bases accuracy — the one market where P2's
   substitution work REGRESSED, plausibly because bench identity matters most
   where power does.
4. **BVP history (1b)** — already collected daily; currently evaluation-only.

**Against:** MLB game lines carry a sharp reference on 102/102 markets while
props carry 0%. Every item above should be aimed at PROPS. Chasing sharp-priced
game lines with a better engine is the losing half of this board.

---

## 5. Owed / unverified

- **Production population of §1a is UNVERIFIED** (403 on `roster_objs/`). The
  local evidence is consistent across 449 pitchers and the cache namespace is
  absent, but confirm on the worker disk before funding the work.
- Whether the x64 populator still runs against a live statcast source at all.
- §2e (recency) is inferred from profile shape, not from the builder — read
  `build_roster.py`'s rate derivation before treating it as established.
