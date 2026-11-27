# FINDINGS: cheat-sheet optimization program, reading 1 — where the sheets lose, and the one defect behind the best section's collapse

Lane `cheat-sheet-optimization` (session eda3ffd5), todo `#862`, 2026-11-27. User: "i need a session dedicated to
optimizing the cheat sheets across all sports and continuing to refine the data/cheat sheets for success. Most of them
are currently losing." Read-only on the fleet: every read ran `nice -n 19` on `~/syndicate-prod/data/cheatsheets`
(fleet checkout `8455f25c0`), and there was no odds fetch and no write. Scripts:
`C:\Users\tempadmin\AppData\Local\Temp\claude\759cfbca308a6e00\eda3ffd5-0d27-44c4-9c85-2b653a3fccfe\scratchpad\`
(`cs_study.py`, `cs_diag.py`, `cs_diag2.py`, `replay_nba_matchup.py`; outputs `*_out.txt`).

## What the numbers rest on

- **Featured bets:** `<sport>/<date>.postmortem.jsonl`, official days 2026-10-15..11-26, decided bets only: **7,639
  bet-lines**. Sections by the version each sheet was stamped with: v1 29 dates (10-15..11-12), v3 12 dates
  (11-13..11-24; 11-13 is mixed v1/v2/v3 by build), v4 2 dates (11-25..11-26).
- **Population:** every graded row of each day's final sheet (`rows`, graded via `<date>.reconciled.json`), **28,861
  rows**: fit window 10-15..11-12 20,564, holdout 11-13..11-26 8,297. The holdout is the window AFTER the 11-13 rule
  change, so the 11-13 assessment never saw it.
- ROI = 1 u at the sheet's best price. Excess = y − `check.p_market` (the fair the sheet shows). 95% intervals: bootstrap
  over GAMES (`review_cheat_sheets._boot_ci`).
- Per-sport coverage: NBA, NHL, NFL, NCAAF, NCAAB, soccer run through 11-26; WNBA (7 games) and MLB (10 games) ended in
  October and are readings only.

## 1. The record (official, featured)

Overall featured: 3,868-3,726, **−196.1 u, −2.6%** (`record.json` 11-27 06:55 CT). By section and rules version:

| section | v1 (10-15..11-12) | v3 (11-13..11-24) | v4 (11-25..26) |
|---|---|---|---|
| Consistency | +2.0% [−2.3, +6.5] (1,586) | −4.5% [−12.3, +2.9] (643) | −19.9% (76) |
| Hot streaks | +2.8% [−2.0, +8.2] (1,346) | −1.5% [−8.5, +6.6] (546) | −23.0% (63) |
| Matchups | +2.4% [−3.9, +8.1] (1,031) | −5.1% [−17.2, +8.2] (246) | −11.4% (33) |
| Value | −5.2% [−12.5, +2.3] (871) | +2.6% [−13.1, +17.9] (202) | +12.9% (27) |
| Sim vs the line | — | −3.5% [−10.0, +2.9] (822) | −13.8% (108) |
| Syndicate picks | −3.5% [−9.3, +2.1] (1,441) | −2.8% [−12.5, +6.4] (483) | −11.8% (75) |
| Skater vs goalie | −7.0% [−14.7, +1.1] (564) | −1.7% (65) | 0-4 |
| Defenders on his targets | −9.9% [−28.7, +4.8] (128) | −12.4% [−29.5, +5.3] (63) | −17.1% (22) |

(Picks and price plays are combined here; the review splits them.) Every section is within noise of ROI 0 in every era
except where noted below. The loss is broad and shallow, roughly the vig: the sections pick bets priced near their fair,
and outside a few signals their selection adds nothing beyond the price.

By sport since 11-13 the deepest holes are NFL (Consistency −16.5% on 97, Hot streaks −17.4% on 89, Sim vs the line
−30.0% on 45 in v4, Defenders on his targets −12.4% on 63) and NBA Syndicate picks −18.8% [−35.8, −1.7] (139), the one
cell beyond noise.

## 2. A DEFECT: NBA Matchups and NBA defender matchups lost their evidence

NBA Matchups was the one section that beat the price before 11-13: **+20.6% [+4.0, +37.7], 142 bets / 43 games**
(excess +10.2 pts); WNBA +18.6% [+8.3, +30.1]. Since 11-13 it has featured about 7 NBA bets in 12 days.

**Measured:** NBA primary sheet rows with 3+ meetings vs the opponent: **348 in the fit window, 14 in the holdout**. By
date: 30-62 a sheet on 10-23..11-10, then 2-10 a sheet from 11-13 (11-24: 0 of 228 rows carry `vs_opponent`). NBA
defender matchups (`pvp`): 172 rows on 11-10, 0 on 11-24.

**Cause** (code + data, both read 2026-11-27):

1. `prop_evidence/basketball._matchup` takes the opponent from the sim's player row when the player is found in
   `cards_sim_detail` (`opponent = _code(sport, player.get("opponent"))`), and from the box-score team codes otherwise.
2. **The NBA engine's `cards_sim_detail` player rows carry no `team` and no `opponent`**: every NBA file read, 10-03 /
   10-31 / 11-01..11-27 (32 keys a row, neither present). The WNBA engine's rows carry both (09-30, 10-09, 10-31), and
   so does the production-sliced WNBA fixture every basketball evidence test reads, so the tests stayed green.
3. So for every sim-found NBA player the opponent was `''`, the meetings filter ran on nothing, and with no opposing
   advanced-stats row either the WHOLE MATCHUP layer went absent. The sheet row's `opponent` then fell back to the
   card's full team name ("Philadelphia 76ers"), which `nba/defender_matchups.team_code` cannot match to a roster, so
   no defender line was built either.
4. Before ~11-11 most NBA players were NOT found in the sim (11-10: 67 of 300 sheet rows had a projection) and took the
   box-score path, which works. Lane `nba-prop-engine-name-join` (11-10..11-14, a correct fix) raised that to 218 of 224
   (11-11), and the evidence vanished with it. The pattern on the sheets is exact: on 11-10, rows with a projection have
   a full-name opponent and no `vs_opponent`; rows without one have a tricode and do.

**Fix** (`_matchup`, built 2026-11-27): when the sim row names no opponent, take the GAME's other tricode
(`away_tri` if the player's side is home, else `home_tri`), and his own team the same way; a row that names its opponent
keeps it (the WNBA engine). Tests `tests/test_prop_evidence_basketball_sim_opponent.py`: the real fixture's sim rows
with `team`/`opponent` stripped (the NBA shape) — 5 of 6 fail on the old code, all 6 pass on the fix; the 13 existing
basketball evidence tests pass. Display only: the MATCHUP layer feeds the sheet, the board's "Matchup:" sentence and
Ask's text; no pricing, staking or placement path reads it (`git grep` 11-27).

**Fleet replay, old vs fixed `_matchup` on served NBA sheets** (primary rows of each sheet, evidence rebuilt today
from the fleet's data root under each version; read-only, nice 19; finished ~1:20 PM CST 11-27):

| NBA sheet | old: MATCHUP layer filled | fixed: filled | fixed: 3+ meetings | fixed: strong (3+, >= 2/3 on this line) |
|---|---|---|---|---|
| 11-25 | 2 of 158 | 158 | 106 | 36 |
| 11-24 | 0 of 149 | 149 | 107 | 36 |
| 11-20 | 0 of 163 | 162 | 126 | 39 |
| 11-10 | 0 of 172 | 172 | 122 | 39 |

The falsification bar (fixed 3+ meetings at least ~10x the old code's 2 on 11-25) is MET: 106 vs 2. "Strong" is the
Matchups admission rule, so the section has ~36-39 candidates a sheet again (it shows the top 25). The 11-10 sheet as
BUILT had 174 rows with a record because its day's sim found few players then; rebuilt today, the sim finds them all,
so the old code now gives that sheet nothing either. The resolved opponent was one of the game's two teams on 641 of
642 rows; the one exception (11-10) is traced below.

**The exception, traced:** 11-10 Josh Hart points, MIL @ NYK (7:40 PM ET), resolved opponent CLE. `_find_player` tries
the board date, the tip's Eastern date, then the tip's UTC date (11-11). His game was not in the 11-10 sim file, so he
was found in the 11-11 file, in the Knicks' NEXT game vs CLE. The old code ignored that row's (absent) opponent, so the
wrong game never showed; the first fix would have printed "vs CLE" on a Bucks game. **Guard (second commit):** the sim
game lends its tricodes only when its two teams are this prop's two teams by canonical name (`_sim_game_is_this_game`;
an unplaceable game counts as NOT this game); otherwise the box-score path decides, as for a player with no sim row.
Test `test_a_sim_row_from_another_game_does_not_lend_its_opponent`. The same fallback also hands such a prop the next
game's projection, minutes and game sim in the other layers: recorded as a lead (`leads.md` 2026-11-27), not this lane's.

**Guarded replay** (same script, ~2:10 PM CST 11-27): 11-10 old 0 / fixed 172 of 172 filled, 3+ meetings 122, strong 39, wrong opponent **0** (Josh Hart now resolved by the box path); 11-25 old 2 / fixed 158 of 158, 106, 36, wrong opponent 0. The guard costs no coverage on either sheet.

## 3. What did and did not persist after the 11-13 rule change (population, primary featurable rows)

| reading | fit 10-15..11-12 | holdout 11-13..11-26 | persisted? |
|---|---|---|---|
| NBA fair lean, overs (excess) | −4.0 [−6.8, −1.5] (2,077) | −0.7 [−4.3, +2.7] (1,057) | **no** — the NBA over-lean is gone (matches lane `prop-fair-side-lean`'s forward read 11-27: −0.29 [−2.15, +1.59]) |
| NBA sim edge ≥ 5%, both sides (ROI) | +6.7% [−0.4, +13.6] (1,021) | +2.3% [−5.4, +9.7] (762) | shrank; its fit edge sat in the UNDERS (+12.0%), i.e. the over-lean |
| NBA sim edge, by size | 5-10% +7.6 / 10-20% +7.7 / 20%+ +5.0 | +6.6 / +1.5 / −2.2 | the section takes the BIGGEST edges first; those did worst in the holdout (a reading, all within noise) |
| NFL sim edge ≥ 5% (ROI) | −4.8% [−11.3, +1.8] (623) | **−12.7% [−22.5, −3.7]** (509) | negative in both; beyond noise in the holdout |
| NFL whole featurable pool (ROI) | −4.0% [−9.0, +1.2] (1,363) | **−11.8% [−19.7, −4.7]** (797 / 30 games) | the NFL fair over-states the shown side by 4.8 pts [−8.7, −1.4] since 11-13: a FAIR problem, not a section problem |
| NCAAF overs / unders (ROI) | +2.3% / −3.1% | **−18.1% [−30.9, −4.8] / +11.7% [+0.6, +23.7]** | a new football over-lean in the holdout |
| L10 hit rate as a predictor (excess, 0-0.3 → 0.8-1.0) | −6.8 → +2.6, monotone | −3.4 → +0.7, flat | **no** — the form signal behind Consistency / Hot streaks faded |
| EV at the best price as a predictor | none (<−5 +3.1 … 2-5 −2.8) | none | never: an off-consensus best price is mostly a stale or informed book |
| one-sided fair rows (ROI) | **−26.3% [−37.1, −14.6]** (424 / 182) | **−32.6% [−52.8, −12.6]** (113 / 39) | **yes, both windows** |
| sim side vs EV side where they disagree | NBA sim side +15.8% vs −19.8% (79) | 19 rows | rare (19 NBA / 14 NFL in the holdout); NOT the cause of NFL's fall |

## 4. Proposals (a person decides; display only — no cheat-sheet rule prices, stakes or places a bet)

1. **Load the NBA evidence fix** (section 2). Expected: NBA rows with 3+ meetings back toward the fit window's ~30-60 a
   sheet, NBA Matchups and NBA defender matchups featuring again; the board's NBA "Matchup:" sentence back on most rows.
   Its own record restarts from the load and is judged at 30+ bets (its prior: +20.6% on 142).
2. **One-sided fair rows never feature** (Consistency, Matchups, player-vs-player), as Sim vs the line already does.
   A line property (how its fair was made), losing −26% / −33% in both windows; today it touches mainly soccer
   (Consistency −19.8% on 18, Matchups −49.5% on 18) and is why soccer's featured record is −17.3% (335). The rows stay
   on "Every prop on the board".
3. **Sim vs the line prints its record since launch beside the pre-launch one.** The header says NBA "+8.0% before
   launch"; since launch it is −4.3% (315). Label, never hide.
4. **Probation verdict for two player-vs-player sections** that trail their fair in both windows: Skater vs goalie
   (−7.0% on 564, then −7.4% on 69) and Defenders on his targets (−9.9% on 128, then −13.6% on 85). Option: keep each
   history as the row's evidence line (it already is), stop featuring them as bet sections.
5. **For the fair owners, not this lane:** since 11-13 the NFL fair over-states the shown side (pool −11.8%), and NCAAF
   overs trail by 7.7 pts. Every NFL / NCAAF section inherits it; route to `fair-price-v2`.

## 5. Changes built in this reading — HELD on local branch `cso-nba-matchup-fix-held` (2 commits: the fix + the same-game guard), not on main

Not on main because an ff of the fleet ships all of main: the push is the user's decision. Both are display only
(`--betting-change no`): the cheat-sheet builder and the review are scripts and load at their next scheduled run after
an ff; the board's NBA "Matchup:" sentence loads at refresh-worker's next restart.

- `prop_evidence/basketball._matchup`: the opponent and team from the sim game when the sim row has none (section 2).
- `scripts/review_cheat_sheets.py`: every featured bet carries its sheet's rules version, and each section prints its
  record per rules version ("by section rules: v1 (from 10-15) …; v3 (from 11-13) …"). The season line mixed days built
  under retired rules: Consistency read season −0.5% while its v3 days were −4.5% and its v4 days −19.9%. Test
  `test_each_section_reports_its_record_under_each_rules_version`.

## 6. Section rules v5 — BUILT (proposals 2-4 of section 4; user 2026-11-27 "Build proposals 1-3 as v5 rules")

The user's 1-3 are this file's proposals 2-4 (the chat numbered them without the NBA fix, which loaded at 20:37:49Z).
Display only, `--betting-change no`. Nothing outside the sheet tools reads a sheet's sections: `cheat_sheet_record`
and the section study re-derive them; play cards select on each row's own verdict; the SGP pools, cross-game parlays
and board picks import only `prop_result_key` / `consistency_posterior` / `board_refusal_text`.

- **One-sided fairs never feature** in a bet section (`cs.sections`, rules >= 5: the bet sections draw from the primary
  lines minus `verdict == "one_sided_fair"`). "Every prop on the board" keeps every row. "Price shopping" keeps them:
  it is a price comparison, not graded as a pick. Hot form (v1 only) is unchanged on v1 days.
- **Sim vs the line prints its since-launch record.** The build reads `cheatsheets/record.json` once per run and stamps
  `sim_edge_record` (official `by_sport.<sport>.sim_edge`, first and last graded day) on each v5 sheet. The page appends
  "Since launch, official sheets Nov 13 - Nov 26: 315 bets (162-153), ROI -4.3% at the best price -- it has not beaten
  the price since launch." A v4 sheet never prints it.
- **Skater vs goalie and Defenders on his targets stop featuring** (`RETIRED_IN_V5`; `RETIRED_SECTIONS` dates them
  2026-11-28). The record keeps their rows as "(retired 11/28)" and drops their "no bets yet" placeholder, as with Hot
  form. The page says where they used to be, with both windows' numbers. The rows keep their `pvp` history, and a
  pick's evidence still cites it (`pvp_point`).
- **A day keeps its rules once a game on it has started** (`build_cheat_sheets.build_rules`). The builder used to stamp
  the current version on every rebuild, so a version loaded mid-day re-judged games already in play or graded. A
  start time it cannot read counts as started. The build prints `keeps section rules v4` when it pins.

**Replay** (fleet, ~3:05 PM CST 11-27). Every official sheet 11-13..11-26 (stamp >= 3; 64 graded sheets) was judged
under v4 and v5 with the worktree code, graded by its own reconciled file, with posted rows pinned as the record pins
them. "Featured" counts a bet once a day:

| scope | v4 | v5 | removed |
|---|---|---|---|
| all featured | 1141-1116, −86.1 u, −3.8% (2,257) | 1101-1068, −75.9 u, −3.5% (2,169) | 40-48, −10.2 u, −11.6% (88) |
| NFL featured | −9.0% (400) | −8.8% (345) | −10.5% (55) |
| NFL Defenders on his targets | 39-46, −13.6% (85) | — | the whole section |
| NHL featured | +2.4% (551) | +1.5% (533) | **+30.4% (18)** |
| NHL Skater vs goalie | 35-34, −7.4% (69) | — | the whole section |
| soccer featured | −44.3% (65) | −37.7% (50) | −66.1% (15) |
| soccer Consistency / Matchups | −84.7% (10) / −64.6% (10) | −100% (2) / −100% (3) | the one-sided rows |

NBA, NCAAF and NCAAB featured no one-sided row in the window, so they do not change. **Caveat: in sample.** This window
is the holdout that motivated the rules, so the replay shows what v5 removes, not a forward test. NHL is the exception:
the 18 bets only Skater vs goalie featured went 11-7 (+30.4%). The section lost overall because most of its rows were
featured elsewhere too. 18 bets is noise, and the retirement rests on both windows (−7.0% on 564, then −7.4% on 69).

**Tests:** `tests/test_cheat_sheet_section_rules_v5.py`, 9:
- v4 vs v5 on the same rows for each rule;
- the record labels;
- the since-launch text, both signs;
- the page prints it only under v5;
- `build_rules`;
- `main` stamps v5 and the record on a fresh day, and keeps v4 with no record on a started one.

Three older tests pinned the version or the retired sections' scorecard rows and were updated. One of them,
`tests/test_cheat_sheet_board_judgement.py::test_rules_version_is_four`, belongs to the OPEN lane
`surface-consistency-oversight`. It changes only by loan: the user picked "Borrow it" when asked, and the loan is noted in both lane blocks. That one assertion moves `== 4` -> `>= 4`. 333 tests pass across the cheat-sheet, evidence, review, reconcile and play-card suites.
The page script passes `node --check`. It was not rendered in a browser.
