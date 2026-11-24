# M2b, a fresh M2 gate: DESIGN DRAFT -- decision engine #736, lane `engine-learner`

**Status: DRAFT, NOT REGISTERED.** Written 2026-11-24 3:32 PM CST on the user's "Yes, design it" (answering "Should I
design a fresh M2 on data from after #834?"). Nothing in it binds until the user registers it. No slate on or after
2026-11-24 has been read for this lane.

## Why there is an M2b

M2's one registered read (11-24 11:23 AM CST, `50319e3d3`) FAILED on HARM in `nba|totals|live|a<=60`. The
pre-registered diagnosis (`882812442`, results `62d8efd84`, in `findings_2026-11-16_m2_gate.md`) found:

- the harm is the live re-sim expert's weight (zeroed, +0.0009);
- the re-sim's over-lean went from +0.11 in train to +0.36 after `#821` F1, a data-file switch inside the test week;
- the learner carried it into p_decision (overs priced +0.089 high);
- the largest applied weight was +1.41, on a thin cell.

The learner learns how much to trust each expert **on the re-sim version it was fitted on**. M2 fitted on one version
and tested on another. M2b tests the learner the way it would have to run: fitted and tested on one version.

## What changes from M2 (each tied to a finding)

| # | Change | From |
|---|---|---|
| C1 | **One version.** Train and test both lie between the 11-24 load and the 12-08 window, with no betting-change load in between (rule: betting changes load only in windows). | the diagnosis (T2) |
| C2 | **Version exclusion.** A sport drops out (`EXCLUDED_VERSION`, never a pass, still checked for HARM) if, between the 11-24 load (08:30:37Z) and its last test game, either: `betting_changes.md` registers a `yes` load touching it, or the M3 morning capture records a change in its re-sim settings or re-sim data-settings files (Addendum 5b). Code-only loads registered `betting change: no` do not exclude, because they are declared byte-identical. The M3 nightly task's morning capture must keep running through 12-08; it does today. | correction `89ff009f2` (the version timeline sees code only) |
| C3 | **Learner `engine_learner/2`: applied weights capped at 1.0.** An expert is never trusted beyond face value. | the +1.41 weight on n 201 |
| C4 | **Learner `engine_learner/2`: a leaf with fewer than 20 train games** uses its deepest ancestor that has 20 or more; the apply rule (lower bound > 0) then reads that weight. | same |
| C5 | **Experts re-pinned** to one origin/main export taken after C3/C4 land. It carries the NHL state-instant fix `85af16b35` (11-17), which M2's pin `981ef14f6` did not. So NHL live is no longer excluded by rule; Amendment 1's look-ahead check is re-measured on M2b's train slates and excludes NHL again only if evidence is still newer than its tick. | M2's NHL `EXCLUDED_LOOKAHEAD` |
| C6 | **Reproduction (Amendment 2) is kept.** It now compares against one production version, so NCAAB/WNCAAB should reproduce (they failed in M2 on `#816` / `#824`, which loaded inside its window). | M2's NCAAB/WNCAAB `EXCLUDED_REPRODUCTION` |
| C7 | **Drift report (descriptive, not a gate).** For each sport x family x live, every expert's mean signed delta-logit in train vs test, with game-bootstrap CIs. It is the instrument that would have shown F1 if no capture had. | the diagnosis (T2) |

Unchanged from M2: the strata (LIVE outcome `sport|family|live|a<=60`; PREGAME close `sport|family|pregame`); the
>= 30 test games; the 99% bound; the floors (0.001 / 0.0002 nats); PASS and HARM as written; tau 0.5; the truths;
games held out whole; and the bootstrap (1000, seed 736).

## Dates

- **Train:** slates 2026-11-24..2026-11-30 (7 nights, from the evening after the 2:30 AM load; Thanksgiving week).
- **Test:** slates 2026-12-01..2026-12-07 (7 nights), every game held out whole.
- **Registration:** before any train opinion is built, so before 12-01. The rule and the code are fixed first. Only
  the pins (train sha256, dev game counts) are filled from the train build, as in M2.
- **12-01 morning (a scheduled task):** build the train opinions with the pinned experts, check reproduction on every
  train slate, measure C5's look-ahead, run a train-only rehearsal (not the gate), and record the pins on main.
- **The one read: Tue 2026-12-08 10:30 AM CST.** It runs in the kit, at nice 19, on recorded data, so the 12-08
  window's 2:00 AM load does not touch it. It is never run twice.

Expected size, from M2's rates: NBA live fresh about 50 test games; NCAAB and WNCAAB large; NHL depends on C5. NCAAF
has one test Saturday (12-05, conference championships) and is likely under 30, so unjudged. NFL is likely
unjudged.

## What a PASS buys, and what it does not

- A PASS stratum may reach M3 (the paper book), as before, but **only while its sport stays on the fitted version.**
- Any later C2 event for that sport (for example a 12-08 load of `#835`/`#852`/`#859` for NCAAF, `#836` or `#847`
  for every live sport) **suspends** that sport's p_decision in M3.
- Resuming needs a re-fit on the new version's first week, read forward on its second week under the same rule (a
  rolling gate). That would be its own registration later.
- If you want M3 to run past 12-08 on a sport that passed, the alternative is to hold that sport's live-input changes
  out of the 12-08 window.

## Decisions that are yours (before registration)

1. **Register M2b as drafted?**
2. **Build and push `engine_learner/2` (C3 + C4)?** It is shadow-only: nothing imports it on an order path. It is not
   a betting change, and it comes with tests, including `off != on` on the cap and the min-games rule. Without it, M2b
   runs with C1, C2 and C5-C7 only.
3. **HARM scope.** M2's rule is kept: any HARM fails the whole gate (recommended: the learner has one method, and a
   harm anywhere says it can hurt). The alternative: a HARM excludes only its own sport and phase.
4. **The live prior.** M2b keeps the books' fair, as M2 did, unless slice 5 (Kalshi's in-play mid,
   `engine-live-prior`, built and not on main) reaches main before the pin. Tonight's 6 PM Kalshi-prior re-run
   (`engine-learner-kalshi-prior-rerun-1124`) is the input to that choice.
