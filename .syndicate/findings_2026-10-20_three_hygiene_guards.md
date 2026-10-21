# Three standing hygiene guards, taken: 17 converters classified, two guard false positives removed, and a gate test that had drifted TWICE

`[2026-10-21 02:55Z / 2026-10-20 21:55 CDT]` session `4ab694ed`
lane `hygiene-guards-1020` — shipped `a5a38a95`
`[no outcomes used; this is repo hygiene plus one production finding]`

The three guards named as a hypothesis in
`findings_2026-10-21_full_suite_seven_real_failures.md` ("guards of that shape
typically fail when someone adds a thing without registering it — **Unverified**").
The hypothesis was **right for two of the three and wrong for the third**.

## 1. `test_every_converter_is_registered_or_excused` — 17 unclassified

Exactly as predicted: a backlog, no drift. Classified from each BODY.

**Six are real scalar converters → REGISTERED.** Three of them pass all five
requirements (`eval_sim_day_vs_actual:_implied_prob_from_american`,
`kalshi_maker_shadow:american_to_prob`, `kalshi_maker_shadow:prob_to_american`).

**Eleven are not → excused with a reason**, grouped by the shape of the excuse,
since that is the reusable part: five two-sided de-vigs (two prices or two
probabilities in, a normalized probability out), three parsers/formatters, two
where neither side is a probability, and `cross_game_parlays.american` — a real
scalar converter of a direction **the harness carries no grid for**
(decimal to american), now the third known implementation of it.

### Registering made three PRE-EXISTING defects visible — it added none

This is the part worth keeping. All three have always failed these
requirements; they were invisible because they were never registered, which is
precisely what the tripwire exists to surface.

| impl | score | fails |
|---|---|---|
| `mlb.sim_engine.live_prop_ranking:american_odds_implied_prob` | 4/5 | `accepts_float_price` |
| `mlb.sim_engine.market_pitcher_props:american_implied_prob` | 4/5 | `accepts_float_price` |
| `scripts.ev_overstatement_decomp:decimal_odds` | 2/5 | `refuses_zero` / `_none` / `_empty_string` |

Both MLB impls coerce through an int (`_safe_int`, `_parse_american_odds`), so
`-110.5` truncates to `-110`: **0.5238095238 against the reference
0.5249406175**, a wrong number rather than a refusal, 0.11 of a percentage
point of probability. Integer prices — what books quote — are unaffected; the
exposure is averaged or consensus prices, which arrive as floats. Same cluster
as `hr_targets` and the `live_lens_port` twin already recorded.

**RECORDED in `KNOWN_FAILING`, NOT fixed, deliberately.** The MLB pair are
sim-engine converters and prop pricing is calibrated around what they return,
so changing them is a mechanism change owed a measurement (CLAUDE.md's
model-engine standard), not a hygiene edit. The decomp script is a fifth copy
of the unguarded one-liner whose existing cluster note already states the
reasoning: turning the raise into a `None` would only move the `TypeError` into
the caller's arithmetic — its own `_devig_pair` divides by the result. It is
also the instrument of lane `sim-stake-unfitted-market-only`'s pre-registered
forward reading, so editing it mid-registration would move the measurement too.

**Reachability, not just green:** on a scratch root holding one planted
`_american_to_probability`, the sweep still reports it, and ignores a
non-converter-shaped helper beside it. `off != on`.

## 2. `test_no_new_timezone_ambiguous_date_calls` — 5 files, and 2 were the GUARD'S FAULT

Partly drift, which the hypothesis did not anticipate. The pattern was an open
prefix ending at `%Y-%m-%d` with no closing quote, so it also matched
`%Y-%m-%dT%H:%M:%SZ` — a full ISO **instant**, explicitly labelled UTC, which
is the correct thing to stamp a telemetry field with and not a slate date at
all. It flagged exactly that in `nba/live_tick/tick.py` and
`wnba/live_tick/tick.py` (both a `"utc":` field).

Narrowed to require the format to be **exactly** `%Y-%m-%d`. Measured before
changing it, against this lane's own falsification test: it removes two hits
and takes **no ALLOWLIST file to zero** (which would have meant the pattern was
the only thing catching that file). Trade stated in the code: a format that
merely starts with the date and continues is no longer flagged — every such
form is an instant, and the date-shaped uses of `utcnow()` are still covered by
the `utcnow().date()` and `Timestamp.utcnow().date()` patterns.

**The remaining 3 files / 4 sites are real debt owned by other OPEN lanes**, so
they are allowlisted with the owner named rather than edited across a lane
boundary. Each already takes an injectable `today`, so each fix is one line in
the owning lane:

- `nhl-season-inputs-in-season` — `inseason_season_inputs.py` (2),
  `inseason_team_xg.py` (1). All three are `today = today or date.today()`
  feeding `season_code(today)`. The stakes are a **season boundary**, not a
  slate, so the skew can only matter within a day of the enable date.
- `board-interval-charts` — `interval_history.py` (1).

### I got the severity of that last one wrong first, and checked

I wrote "a slate-date default, the high-stakes kind" into the allowlist reason
— inferred from the variable being called `today`. It is read at **exactly one
site**: `_keep`'s `day < self.today and all(g.get("decided") for g in games)`,
the decision to persist a day to the disk cache. Behind `all(decided)` a
one-day skew can only persist an already-final day early or defer it. It moves
no slate and mis-dates no game.

**The finding worth passing on is a different one on the same line:**
`cached_team_results` — the board's reader — builds `IntervalHistory(root,
offline=True)` with no `today=` and caches it in the module-level `_READERS`
dict, so `self.today` is **frozen at the value the process booted with**. For a
long-lived gunicorn worker that is days stale, and `central_today()` would not
fix it; the fix is to resolve "today" per call rather than per reader.

## 3. `test_gate3_unwired_sport_still_fails_closed` — NOT the hypothesis

Not a backlog. The test names a sport it expects to be unwired, and **that
sport keeps getting wired**. It has now drifted twice: `nhl` joined
`_LIVE_GAMELINE_SPORTS` on 2026-09-24 (lane `nhl-live-resim`) and the test went
red that day; it was changed to `nba`.

### The production finding: NBA live pricing is ON by default

`nba` is in the wired set **by default, not by configuration**.
`_nba_live_priced()` reads the env var, coerces a missing value to the empty
string, and asks whether that is in `("0", "false", "off", "no")`. An absent
variable becomes `""`, `""` is in none of those, so **absent reads as ON**.

Measured 2026-10-20 21:45 CDT: `SYNDICATE_NBA_LIVE_PRICED` is **absent on every
live fleet process** — refresh-worker (pid 3158881), live-odds-worker, and both
gunicorn web workers. So NBA live pricing is on in production, and `nba` is
wired there as well as in the test.

The neighbouring `_LIVE_GAMELINE_SNAPSHOT_PATHS` comment says NBA is *"Read
only when `SYNDICATE_NBA_LIVE_PRICED` admits the sport"* — **written as opt-in,
implemented as opt-out.** Another instance of
`feedback_unknown_must_not_default_permissive`.

**I did not flip the default.** Doing so would turn off NBA live pricing in
production, which is a product decision and not this lane's to take. It is
raised to the owner and recorded below.

### The fix: derive the sport, do not name it

Both gate 2 and gate 3 now take the wired set from the implementation and pick
a sport outside it, preferring a real one. All eight sports Syndicate runs are
currently wired for gamelines, so gate 3 falls back to a token; **gate 2 still
derives a real sport (`nhl`) and will move itself** the day NHL props are
wired. The assertion is unchanged and is not vacuous: a sport the code does not
know must fail CLOSED rather than return `supported: True` and render a blank
live column.

**Proved it tracks the env, not a name:** with `SYNDICATE_NBA_LIVE_PRICED=0`,
`nba` leaves the wired set and the derivation picks `nba` — a real sport — and
the file is green both ways.

## Verification

- `27 passed` — `test_probability_differential.py` (10),
  `test_slate_date_timezone_discipline.py` (8),
  `test_soccer_live_gates_wiring.py` (9) — on the REBASED tree, re-run after
  taking 9 peer commits (one of which added a new script) rather than trusting
  the pre-rebase result.
- `discover_unregistered()` → `17` before, `0` after, re-checked post-rebase.
- Shipped `a5a38a95` (`45ea1885..a5a38a95`), 184 insertions / 6 deletions, and
  every one of the 6 deletions verified as my own replaced lines.

**These three guards read only `syndicate/`, `pipeline/` and `scripts/`** — the
converter sweep walks exactly those three, the timezone sweep two of them —
none of which differ between the sparse worktree and the fleet checkout, and
gate 3 needs no artifact. So unlike the rest of that seven-failure list, the
sparse worktree is a faithful instrument here and no fleet run is owed.

## Left for someone else, with an owner

1. **`_nba_live_priced()` default** — absent reads ON. Either make it opt-in as
   its own comment describes (a production change: NBA live pricing stops) or
   set the variable explicitly on the fleet so the behaviour is stated rather
   than inherited. Owner: whoever owns NBA live re-sim
   (`tests/test_nba_live_resim.py` is also in the seven).
2. **The two MLB sim-engine float truncations** — a mechanism change owed a
   measurement, not a hygiene edit.
3. **`interval_history`'s module-cached reader** freezing `today` at process
   boot. Owner: `board-interval-charts`.
4. **The 4 allowlisted timezone sites.** Owners: `nhl-season-inputs-in-season`,
   `board-interval-charts`. One line each.

## Against the seven

Three of the seven are closed. The other four
(`test_archives`, `test_intelligence`, `test_nba_live_resim`,
`test_ncaaf_team_aliases`) remain **unattributed by design** — that run used
`--tb=no`, so it produced names without causes, and I am not guessing at one.
