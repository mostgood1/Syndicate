# The learner against Kalshi's own price (dev study, 2026-11-17)

Lane `engine-learner`, umbrella #736. The user asked for it ("Yes, run it") after M3's dev rehearsal: there, the NCAAF
live gain the learner showed against the books' price lost 3.3c per contract at Kalshi. The hypothesis and falsifier
were written to the lane before the run (main `526f9f4b3`, 7:54 PM CST). **Dev slates only**: nothing of M2's
11-15..11-22 or M3's windows was read. Kit `C:\tmp\elp\kprior` (`make_opinions.py`, `run.sh`, outputs).

## Method

- **Opinions:** the M2 kit's frozen ones (experts `981ef14f6`). Live, full-game h2h, spreads and totals; NBA, NHL,
  NFL and NCAAF; slates 11-09, 11-10, 11-11, 11-13 and 11-14 (the in-play recorder has no 11-12).
- **Kalshi's price:** the recorder's 10 s Kalshi quotes, placed on each line by M3's index (the order path's
  resolver, the live join's frame), at the decision instant t_d: the tick, or the evidence state's `as_of` if later.
  - P1 is the last quote at or before t_d, at most 60 s old.
  - P2 is the first quote in [t_d + 10, t_d + 70] s: M3's entry quote.
- **The same line-instants in every arm:** only those with both P1 and P2. NBA 42,329; NCAAF 10,327; NHL 1,517; NFL 0
  (no NFL Kalshi market could be placed).
- **Arms:**
  - `book`: the original opinions, the control.
  - `kbefore` / `kentry`: prior = P1 / P2. Each expert's delta becomes logit(p_expert) - logit(p_Kalshi), and the
    books' fair is added as one more expert, `books`.
- **Learner:** the frozen one (tau 0.5), test from 11-13 (44 train games, 87 test games, each game held out whole),
  outcome truth.

## Result

**The hypothesis holds.** Against either Kalshi prior, 0 of 82 cells are applied and 0 of 20,657 held-out examples
move. Against the books' prior on the same lines, 16 NBA cells are applied, mostly where the books' prior was 60 to
900 s old. None of them reaches a held-out d_ll CI below 0 on these 14 NBA test games.

| test, prior log loss | books | Kalshi P1 | Kalshi P2 |
|---|---|---|---|
| NBA h2h | 0.4470 | 0.4160 | 0.4137 |
| NBA spreads | 0.4605 | 0.4433 | 0.4378 |
| NBA totals | 0.4370 | 0.4133 | 0.4106 |
| NCAAF h2h | 0.4616 | 0.4481 | 0.4463 |
| NCAAF spreads | 0.6809 | 0.6035 | 0.5953 |
| NCAAF totals | 0.6854 | 0.6265 | 0.6146 |
| NHL h2h | 0.5481 | 0.5373 | 0.5324 |
| NHL spreads | 0.5472 | 0.4683 | 0.4696 |

Fitted NBA weights against P2 (train cells with n >= 300; n-weighted mean, typical SE):

| expert | NBA spreads | NBA totals |
|---|---|---|
| `books` | -0.68 (se ~0.44) | -0.27 (se ~0.49) |
| `live_resim` | +0.17 (se ~0.48) | -0.32 (se ~0.40) |

Against the books' prior, `live_resim` was +0.46 / +0.25.

## Reading

- **Kalshi's in-play mid is a much better forecast than the books' fair** in every sport and family here. Log loss is
  lower by 0.02 to 0.09 nats, and by most in NCAAF spreads and totals.
- **Moving toward the books from Kalshi makes the forecast worse.** The `books` weights are negative.
- **The live re-sim shows no weight against Kalshi.** NBA's train set is 44 games, so this rules out a strong signal
  (w near 1), not a modest one (w up to about 0.5-0.8).
- **NCAAF trained on only 214 line-instants** (weeknights 11-10 and 11-11), so its null says little.
- **Consequence:** a live learner built on the books' prior (M2 as registered) can pass M2 and still have nothing to
  sell at Kalshi. This is the dev-data reason M3's rehearsal lost. Live edge, if any, has to come from information
  Kalshi lacks, judged against Kalshi's own price.

## What would change it

The same study on more data. After M2's 11-24 read, slates 11-15..11-22 may be read, adding two NCAAF Saturdays and
about 8 NBA nights. Whether slice 5 (Kalshi as the prior) is worth rebuilding turns on that: a weight surviving against
P2 there. Nothing here changes M2's or M3's registered rules.


## Context for the 11-24 re-run: what changed inside its windows (filed 2026-11-18 11:21 AM CST, before its data; the rule is unchanged)

The re-run trains on 11-09..11-17 and tests on 11-18..11-22. Two things the opinions and quotes rest on changed inside
those windows. Nothing in the registered rule changes; this is filed before the run so its result is read with it.

**1. The live re-sims** (the live expert reads what they publish; full timeline and method: `.syndicate/findings_2026-11-17_m3_paper_book.md`, Addendum 5;
times are role loads, not commits):
- **NBA:** training nights 11-09..11-13 ran without the closing-line margin anchor, 11-14..11-17 with it (loaded about
  11-14 9:37 AM). The starter-exit refusals loaded 11-15 12:25 PM and 11-16 12:15 PM. As of 11-18 10:34 AM, every
  test night runs the version loaded 11-17 3:53 PM.
- **NCAAF:** the one training Saturday (11-14) ran before the QB-exit refusals (loaded 11-15). The `#808` end-of-half
  switches (11-16, all default OFF) and an MLB edit to the shared exit-gate file (11-17) also came in training. The
  test Saturday (11-21) runs after all of them.
- **NFL:** the QB-exit refusals (11-15), real timeouts left (11-16), and the drive in progress (11-17) loaded during
  training; per-game seeding loaded 11-18 2:03 AM, before any test game.
- **NHL** is not in M3's timeline (never eligible for M3). Its re-sim also changed during training, per `deploys.md`:
  the end-game (11-11 4:34 PM), the published total (11-13 11:57 AM), overtime as sudden death (11-13 3:28 PM) and the
  rest of the period as regulation (11-14 1:42 PM); the goalie-pull refusal was committed 11-16.
- Later changes: the M3 nightly records them every morning in `C:\tmp\elp\m3_kit\epochs\timeline.json`; read the
  11-24 copy with the result. The `#834` and `#836` fixes are not to load before 11-22 ends.

**2. The recorder's Kalshi quotes.** The new poll loop (`e9eb52568`, `a2af81258`) records from the 11-18 night on;
training nights used the old loop. In a dry test the old loop never quoted 40-42% of a Saturday's markets, most NCAAF
totals among them, and quoted no NFL or NHL market (`739fa951b`). So the test nights hold line-instants, NCAAF totals
above all, whose cells were thin or empty in training, and those fall back to their parent cells exactly as the
learner is built to. The Normal-priority fix (`c0d9cf9b8`) records from 11-19 on.


## Correction to the re-run's context note (2026-11-18 11:51 AM CST, before its data; the rule is unchanged)

The note missed one change. **F1 of todo `#821`** (`feed_game_model` with the outs penalties off, in the NBA processed root's `nba_sim_total_inputs.json`) was switched on 2026-11-17 at 11:35 AM CST (`deploys.md` 17:34:59Z). It is a data-file switch, not code, so the version timeline cannot see it. It moves the NBA pregame sim's totals, which the NBA live re-sim starts from. Lane `nba-live-total-anchor` measured 11-18's 12 NBA pregame totals at +6.78 (se 1.04) above the closing line (`.syndicate/findings_2026-11-18_nba_live_total_anchor.md`). So of the NBA training nights only 11-17 starts from that level, and every test
night does.

## Re-run on 11-09..11-22 (train to 11-17, test 11-18..11-22)

Run 2026-11-24 6:01-6:22 PM CST by the one-time task `engine-learner-kalshi-prior-rerun-1124`, after M2's read was
finished (`m2gate_kit\out\progress.txt` DONE, `m2_verdict.txt` 11:22 AM). Pins checked before launch:
`make_opinions.py` 4a31034b6e0fd2a7..., `run.sh` 6e9eea0ca1987529... Kit `C:\tmp\elp\kprior2`, nice 19, every
`rc=0`. Frozen learner `981ef14f6`, tau 0.5, outcome truth, the same line-instants in all three arms.

- **Data:** 188,193 examples on 12,320 lines; train 83,956 (180 games, before 11-18), test 104,237 (139 games, each
  held out whole). Test games: NBA 38, NCAAF 59-60, NHL 31, NFL 10. 11-12 has no recorder file. 11-15's 587 NCAAF
  opinions found no Kalshi market (the old poll loop); NCAAF's train now rests mostly on 11-14 (9,875 kept).
- **Line-instants kept per date** (`make.txt`, opinions with both Kalshi quotes):
  - NBA train 11-09 14,673, 11-10 12,867, 11-11 5,018, 11-13 6,547, 11-14 3,224, 11-15 9,294, 11-16 11,484, 11-17
    6,369; test 11-18 20,593, 11-19 8,893, 11-20 19,619, 11-21 12,865, 11-22 16,183.
  - NCAAF train 11-10 169, 11-11 45, 11-13 238, 11-14 9,875, 11-15 0, 11-17 223; test 11-18 664, 11-19 542, 11-20
    2,375, 11-21 18,206.
  - NHL train 123 / 208 / 413 / 170 / 603 / 709 / 322 / 613; test 484 / 1,702 / - / 1,549 / 717.
  - NFL train 11-15 1,099, 11-16 104; test 11-19 106, 11-22 1,464 (none before 11-15: no Kalshi market placed).

| test, prior log loss | books | Kalshi P1 (`kbefore`) | Kalshi P2 (`kentry`) |
|---|---|---|---|
| NBA h2h | 0.4896 | 0.4780 | 0.4758 |
| NBA spreads | 0.4588 | 0.4350 | 0.4313 |
| NBA totals | 0.4897 | 0.4720 | 0.4681 |
| NCAAF h2h | 0.5128 | 0.5122 | 0.5127 |
| NCAAF spreads | 0.6842 | 0.6109 | 0.6039 |
| NCAAF totals | 0.6924 | 0.6230 | 0.6198 |
| NFL h2h | 0.1696 | 0.1450 | 0.1450 |
| NFL spreads | 0.6575 | 0.6260 | 0.6216 |
| NFL totals | 0.7066 | 0.7183 | 0.7139 |
| NHL h2h | 0.6122 | 0.5901 | 0.5836 |
| NHL spreads | 0.5388 | 0.4719 | 0.4658 |

**Applied cells per arm** (`REACH`):
- `book`: 92 of 184 cells, 38,750 of 104,237 test examples move. Every applied cell is `live_resim`, w +0.47 to +1.19,
  in NBA, NCAAF and NHL. Held-out ON: NHL spreads d_ll -0.0387 [-0.0653, -0.0131] (31 games; the a180-900 bucket
  -0.0822); NCAAF spreads -0.0147 [-0.0397, +0.0128]; NBA h2h / spreads / totals +0.0046 / +0.0049 / +0.0035, all CIs
  across 0; NFL totals +0.0164 [+0.0017, +0.0355].
- `kbefore`: 3 of 142 cells, 13,842 examples move: `live_resim` NBA h2h 50-75 a<=60 (w +0.55), NBA spreads_alt 50-75
  a<=60 (+0.68), NCAAF spreads 25-50 a<=60 (+0.84).
- `kentry`: 3 of 182 cells, 10,989 examples move, all `live_resim`, all NBA, clock 50-75, a<=60: h2h w +0.558 (se
  0.276, n 654), spreads +0.608 (se 0.349, n 1,332), spreads_alt +0.690 (se 0.271, n 9,173). No `books` cell is
  applied; its weights against `kentry` are negative in every cell (-0.03 to -1.42).

**The held-out lines that decide THE RULE** (`kentry`, live, HELD_OUT ON; ON_BY_AGE a<=60 is the same):

| sport, family | games | d_ll | 95% CI |
|---|---|---|---|
| NBA h2h | 38 | +0.0021 | [-0.0038, +0.0080] |
| NBA spreads | 38 | +0.0032 | [-0.0007, +0.0069] |
| every other sport, family | - | 0 (no cell applied) | [0, 0] |

**Verdict: slice 5 (Kalshi as the live prior) is NOT worth rebuilding for any sport|family.** Only NBA h2h and NBA
spreads have a cell applied against `kentry`, and neither held-out CI is below 0; both point estimates are worse than
Kalshi's own price.

Reading (not part of the rule):
- Kalshi's price again out-forecasts the books' fair, by 0.01 to 0.08 nats, in every sport and family but NFL totals
  and NCAAF h2h.
- Against the books' prior the live re-sim does carry weight, and on NHL spreads it holds out. That is the books' fair
  being stale, not information Kalshi lacks: against Kalshi the same expert keeps 3 NBA cells, and they do not hold out.
- `HELD_OUT RAW` (unshrunk, applied or not) against `kentry` has NBA totals at -0.0112 [-0.0161, -0.0058] and NFL h2h
  at -0.0082 [-0.0111, -0.0040] (10 games). No NBA totals cell passes the applied test, so this is not a result under
  the rule. The `books` weights there are about -1 at 0-50% of the clock, so the raw gain would come from moving away
  from the books, not from the re-sim.
- Read with the context notes above: every NBA test night starts from the `#821` F1 level, and M2's 11-24 FAIL was
  HARM on NBA totals live against the books' prior.


## POST-#834 RE-CHECK: registered 2026-11-25 10:59 AM CST, before its data

**User:** "Yes, schedule it", answering "Schedule a 12-01 re-check of the re-sim against Kalshi's price on post-#834
NBA nights?". Lane `engine-learner`, todo `#736`. Read-only on the fleet. It gates nothing by itself.

**Why.** The 11-24 re-run above tested NBA only on nights 11-18..11-22. Those were all on `#821` F1's level, before
`#834` (the NBA total anchor: loaded 11-24 2:30 AM CST, live check MET 9:34 PM, `4df200017`). M2b was held on 11-25
(`214617a25`) on the re-run's answer. This asks the same question on the post-`#834` version.

### Data and split

- Central slates 2026-11-24..2026-11-30, **NBA only** (see "Why NBA only").
- Train 11-24..11-27; test 11-28..11-30 (`--test-from 2026-11-28`). Each game is held out whole.
- No slate from 11-24 on has been read for this lane. The smoke run below used 11-21/11-22, which the 11-24 re-run
  had already read.
- If M2b is ever resumed, it cannot treat 11-24..11-30 as unseen.

### Method (as the 11-24 re-run, except dates, paths and NBA only)

1. A settings/data snapshot (`vsnap.py`). It uses M3 Addendum 5b's own readers and stores hashes only.
2. The pinned experts write `ops/opinions_<date>.jsonl` for NBA: the M2 kit's code, an export of `981ef14f6`
   (`launch.py experts --sports nba`).
3. `make_opinions.py` re-prices each line-instant to the in-play recorder's Kalshi quotes. It is the re-run's script
   with only its dates, paths, sports and reader changed. The diff against `kprior2/make_opinions.py` is:
   - the docstring, `OUT`, `OPS` (replacing `TRAIN` / `TEST`), `DATES` and `SPORTS` (from `KP3_SPORTS`, here `nba`);
   - the one read of `OPS`, now `read_live_gameline_ops`, which applies `main()`'s own tests while reading (smoke 4:
     output byte-identical).
4. The pinned learner runs on book / kbefore / kentry: outcome truth, tau 0.5, `--min-print-n 100`.

### Why NBA only

- **Memory.** On the fleet, the four-sport build of an already-read Saturday (11-21) peaked at 4,838 MB of this job's
  own memory. Host MemAvailable fell to 1,823 MB, and to 1,212 MB in the first smoke. The fleet trades live money on
  this host. Most of the peak is the four-sport opinion file: 420,688 opinions, about 2 GB once read. 11-27 and 11-28
  are heavy college nights.
- **Scope.** The rule judges NBA only. `#834` changed only NBA, and the other sports were descriptive in this design.
- **What it changes.** The learner has a root weight per expert shared across sports (`node_path`: `*` -> sport ->
  ...). So an NBA-only fit is not the 11-24 four-sport fit restricted to NBA: NBA's cells shrink toward an NBA-only root.
  That is the cleaner fit for an NBA-only question, but its numbers are not directly comparable cell by cell with
  11-24's.

Everything runs on the fleet at nice 19, attached, under a memory guard:
- it kills the run's process group if host MemAvailable falls under 1,200 MB;
- before each heavy step it waits up to 10 minutes for 3,000 MB available;
- it logs this job's own memory per step (`mem.log`, summary in `guard.log`).

### THE RULE

This is the 11-17 Kalshi-prior rule, applied to NBA on the post-`#834` version. It is computed by `verdict.py` from
`learner_kentry.json`, never from the text output, which hides cells below `--min-print-n`; see the correction below.

For each NBA family f in h2h, spreads, totals, against Kalshi's entry quote (`kentry`):

- **ADDS:** a `live_resim` weight in a cell `nba/f/...` is applied, AND HELD_OUT ON `nba|f|live` has a ci95 upper
  bound below 0, on at least 15 test games.
- **NOTHING:** at least 15 test games, and not ADDS.
- **UNDERPOWERED:** fewer than 15 test games.

Summary: ADDS if any family ADDS; NOTHING if all three are NOTHING; otherwise UNDERPOWERED.

### Validity

Any failure below makes it `KCHECK_VERDICT INVALID`, with no family verdict.

- **V1.** Every step returns rc=0, and the run ends with `KPRIOR3_ALL_DONE`.
- **V2. One NBA re-sim version over 2026-11-24T08:31:00Z..2026-12-01T08:00:00Z.** Any of these breaks it:
  - a `betting_changes.md` `yes` load in the span whose text names NBA, basketball or live (other `yes` loads are
    listed as notes);
  - an Engine Watch re-sim version row for NBA of kind `switch` starting in the span (code rows are notes);
  - any change between the snapshot taken at registration (`vsnap_base.json`) and the one taken at run start, in:
    the NBA re-sim setting hashes per role, the NBA keys in `local_production.env`, or the `nba_source` settings
    files' content;
  - an `nba_source` settings file written in the span;
  - a role missing from either snapshot.
- **V4.** At most 5% of NBA line-instants are not final.

**Gap check at registration (11-24 08:31Z to the baseline, 11-25 16:59Z):** nothing changed.
- No `local_production.env` backup is stamped after 08:23:56Z, which is the window batch's own edit before the load.
- The three `nba_source` settings files were last written 11-17 17:35:08Z (F1's `nba_sim_total_inputs.json`) or
  earlier.
- Engine Watch has no NBA version row after `nba-E14` (the 11-24 load).

### Descriptive (no rule)

- Prior log loss per sport and family: books, Kalshi before, Kalshi entry.
- HELD_OUT RAW for the NBA families.
- Reach.
- **The re-sim's over-lean on NBA full-game totals.** This is `live_resim`'s mean delta toward over, per game, with a
  game bootstrap. It is computed against both priors, for this run and for the re-run's 11-18..11-22. It shows whether
  `#834` removed F1's lean.

### Expected size, stated before the data

- At the re-run's rate (38 NBA test games over 5 nights), the 3 test nights give about 20-23 NBA games. NBA's
  Thanksgiving slate, if any, is light.
- Train is 4 slates against the re-run's 9, so fewer cells can pass the applied test. A NOTHING here is weaker evidence
  than 11-24's.

### What each result means (the user's call either way)

- **ADDS:** the anchored re-sim carries information beyond Kalshi's price on that family. That reopens an M2b judged
  against Kalshi's price.
- **NOTHING:** no evidence the re-sim adds anything beyond Kalshi's price. M2b stays held.
- **UNDERPOWERED / INVALID:** reported with the reason. A re-run would be a new decision.

### Schedule

- One-time task `engine-learner-kalshi-recheck-1201`, Tue 2026-12-01 10:00 AM CST.
- It runs once, into `C:\tmp\elp\kprior3\run`, and stops if that folder already exists. It writes the verdict and
  pushes the result with `push_result.py`, mechanically, additions only. It updates Engine Watch and reports to the user.
- No fleet change, no betting change.
- If the task never runs, Engine Watch's `kalshi_recheck` gate goes overdue on 12-03 and the fleet-watcher flags it.

### Smoke (11-21/11-22, nights already read; plumbing only, not a result)

All four smokes ran on 11-21/11-22 (nights the 11-24 re-run had already read). Every step returned rc 0.

1. **Four sports.** Plumbing clean; the verdict is UNDERPOWERED (7 test games), as it should be. Host MemAvailable
   fell to 1,212 MB.
2. **Four sports, with this job's memory logged.** The re-pricing step peaked at 4,838 MB (host down to 1,823 MB). The
   other steps stayed at or under 1,136 MB.
3. **NBA only.**
   - The re-pricing step still peaked at 3,382 MB, because it read an NBA night's 250-300 MB opinion file (mostly
     props) whole. Host minimum 2,898 MB.
   - The NBA rows are identical to the 11-24 re-run's, for both nights and both priors (12,865 / 16,183 book rows).
   - The over-lean line reproduces 11-24's to 4 decimals.
4. **The re-pricing step filters while reading** (`read_live_gameline_ops`, the same tests `main()` applies). Peak
   739 MB, and the output is byte-identical to smoke 3's for all three priors and both nights.

Peaks of this job in the final configuration: experts at or under 783 MB, re-pricing 739 MB, learner at or under
648 MB.

### Pins (sha256)

```
d81a58ab2f57d4ef7e9fb2ea19d911ac657607bea8f1f2d72f85480901d7e3ba */c/tmp/elp/kprior3/run.sh
3c16c694e5cc974de126fcbd905d2960cddc6f9d84783c2c2eadbcde96a4c4bf */c/tmp/elp/kprior3/run_fg.sh
20823e15a0e382044dfbacb9d51ed17e684b7a0a3a7bdc93ad11e82ef72a87bd */c/tmp/elp/kprior3/vsnap.py
406488593d4e9ae713aa8cb978a5b7a8e64b55026bf712c0aa0f0651f82b2061 */c/tmp/elp/kprior3/make_opinions.py
0e52e318358a832611745836d4ae8eed31e7fc56e0bdf98cd4b8cb35adf095d9 */c/tmp/elp/kprior3/verdict.py
e630a76928c8acb20ecfb7e2164cf428723bf9f3f724fab79d7beb09ce4a71f0 */c/tmp/elp/kprior3/push_result.py
03d40874fdf29f6b6bb3434b46aedfe62c9967f665e43124ee86722798852ac4 */c/tmp/elp/kprior3/task_prompt.md
5d136ff45cd2237d7b43cde494773096b9fdad99fb8336d98ee2e0309ba3fa94 */c/tmp/elp/kprior3/vsnap_base.json
3a1a38c208192eaa147e23be07b2e43bd638ad74640411f764f14a7c24105116 */c/tmp/elp/m2gate_kit/launch.py
8170a5112905ec406d4060f6232a7df867181d0a2a9425b610a20597542f4058 */c/tmp/elp/m2gate_kit/code/PINNED_SHA
e59d7d6f94c537ed1e0b8c79b6d129649f835ca6bdcb11f5a82f626e280bf9b7 */c/tmp/elp/m2gate_kit/code/scripts/engine_learner.py
b9d5db099b9131df95544ddf78e7082b9bdfb9497cba443c2cc3806eea088fd9 */c/tmp/elp/m2gate_kit/code/syndicate/features/shared/engine_learner.py
ede517b2bf0059b5c020a38d882cc577ee1502adb8430a6f35b23ded6d1e274b */c/tmp/elp/m2gate_kit/code/scripts/engine_experts.py
812e4e8a8c504efbb7c73296491d16f9e6cbce5c8b52ef25744a2fabce08e461 */c/tmp/elp/m2gate_kit/code/syndicate/features/shared/engine_experts.py
d445c67b2fde08663fb322365edf68205c7cf33cdb16e22fc34fc45469063d70 */c/tmp/elp/m3_kit/code/scripts/engine_paper_m3.py
ffba9bb4f424f556750f3558a2e9d28f4b45e4023c1bae1ba27810886e7ef325 */c/tmp/elp/m3_kit/code/syndicate/features/shared/engine_paper_m3.py
50d42599553b16c6377601b6d42ea21af7881fb342bcfa76ab4c4ed7d3b1dbf3 */c/tmp/elp/m3_kit/epochs/m3_epochs.py
```

### CORRECTION to the 11-24 re-run's applied cells (2026-11-25)

- **The `kentry` arm's 3 applied cells are:**
  - NBA h2h 50-75 a<=60 (w +0.558, se 0.276, n 654);
  - NBA spreads_alt 50-75 a<=60 (+0.690, se 0.271, n 9,173);
  - **NCAAF spreads 0-25 a60-180** (+0.668, se 0.335, n 30).
- **Not NBA spreads 50-75 a<=60.** That cell (w +0.608, se 0.349, n 1,332) is `applied=False`, with a lower bound of
  -0.076.
- **Why it was missed.** The text output prints only cells with n >= 100, which hid the NCAAF cell, and the write-up
  was read from the text. `learner_kentry.json` is authoritative.
- **The verdict is unchanged.** NCAAF spreads' HELD_OUT ON is d_ll 0, CI [0, 0], so it is still "not worth rebuilding
  for any sport|family".
- **What was wrong:** "all NBA" and "no other sport|family has a cell applied". The 11-25 M2b hold note's "only 3 NBA
  `live_resim` cells" carries the same slip; its conclusion (no weight holds out against Kalshi) stands.
