# Recovered 2026-09-10: ledger text that existed only in the primary checkout and two stashes

`[lane census-rescue-0910, session 78cad512 / desktop local_b85a1f7c, from the 2026-09-10 open-work census]`

**This is a RECORD, not current state.** Every block below is copied verbatim
from a place that was about to be lost:

- the primary checkout's uncommitted `.syndicate/` edits, which were 812 commits
  behind `origin/main` when read;
- `stash@{4}` ("pull-primary-tree b4916e4e", 2026-09-05);
- `stash@{6}` ("sync: preserve 12 files with local content", 2026-09-04).

Much of it was written by sessions whose work was later superseded, retracted
or reworded upstream. Read it the way you would read `lanes_history.md`, and
re-derive anything load-bearing before acting on it.

**How "only here" was decided.** A line is kept if fewer than half of its 6-word
shingles occur anywhere in `origin/main`'s `.syndicate/**/*.md` plus
`docs/ai_context/*.md` at `df60b3e3`. That test treats rewrapped or moved text as
present. So what follows is text with no upstream copy in any form, plus a
little noise where upstream reworded a sentence. Lines under 8 words are not
tested, which is why some blocks start mid-thought.

**Deliberately NOT recovered:**

- **`stash@{7}` (autostash).** Its `.claude/settings.json` lines differ from
  main's only in hook-command FORM. All nine hook scripts it names —
  session-start, lane-guard, ledger-append-guard, commit-guard,
  ledger-commit-guard, deploy-guard, lane-postwrite-check, checkpoint-guard and
  ledger-postwrite-check — are wired on `origin/main`. This was checked.
- **`state_soccer.md`'s "8 home / 9 away / ship it" lines.** Main withdrew these
  on 2026-09-07 on purpose.
- **The committed `todo.md`'s one odd line.** It is a garbled duplicate heading
  of `#234`.

Lines found only here, per source:

| Source | File | Lines |
|---|---|---|
| primary checkout | leads | 4 |
| primary checkout | program_sim_confidence | 2 |
| primary checkout | log/2026-09-08 | 60 |
| primary checkout | lanes_history | 6 |
| primary checkout | lanes | 1 |
| `stash@{4}` | lanes | 49 |
| `stash@{4}` | learnings | 1 |
| `stash@{4}` | log/2026-09-04 | 119 |
| `stash@{4}` | state | 1 |
| `stash@{6}` | lanes | 41 |
| `stash@{6}` | learnings | 1 |
| `stash@{6}` | state | 1 |
| `stash@{6}` | state_layer2 | 3 |

---

## From primary tree (uncommitted): `.syndicate/leads.md` -- 4 line(s) found nowhere in origin/main's ledger


<!-- primary tree (uncommitted) .syndicate/leads.md lines 39-42; nearest heading: ## Open -->

- [ ] 2026-09-08 — from `session-scope-drift-guard` — `learnings.md` (4,081 lines on origin) has NO standing rule on scope drift, deferring leads or delegation; the mechanism now exists but the rule is unwritten — evidence: grepped FORBIDDEN/`scope drift`/`deviat`/`delegat`/`anti-drift` on `origin/main`, zero on-topic hits
- [ ] 2026-09-08 — from `session-scope-drift-guard` — lane `profitable-buckets` and its hand-written ANTI-DRIFT RULE are UNPUSHED; origin has neither, so the best statement of this failure mode exists nowhere another session can read it — evidence: `git show origin/main:.syndicate/lanes.md | grep -c profitable-buckets` → 0
- [ ] 2026-09-08 — from `lead-deferral-and-lane-census` — THREE lanes say `— OPEN` in their status field while their header prose says they are done (`layer2-cap-raise`, `accuracy-ledger-budget-raise`, `ncaaf-live-resim-wire`); `lane-guard` still enforces their claims — evidence: `py -3 scripts/lane_census.py` vs the CLOSED text in those headers
- [ ] 2026-09-08 — from `lead-deferral-and-lane-census` — the session-start digest body is **1910 B against BUDGET=1800**, so the tail is still cut; the lane census freed 389 B but other sections grew past it — evidence: `bash .claude/hooks/session-start.sh | wc -c`

## From primary tree (uncommitted): `.syndicate/program_sim_confidence.md` -- 2 line(s) found nowhere in origin/main's ledger


<!-- primary tree (uncommitted) .syndicate/program_sim_confidence.md lines 46-47; nearest heading: ## Definition of done, per sport -->

1. **Input checklist green in production.** `dataclasses.fields()` cross-check
   of CONSUMED against POPULATED, exit non-zero, published as

## From primary tree (uncommitted): `.syndicate/log/2026-09-08.md` -- 60 line(s) found nowhere in origin/main's ledger


<!-- primary tree (uncommitted) .syndicate/log/2026-09-08.md lines 280-286; nearest heading: # Session — live-gameline nightly capture, then 09-04 decomposed to the game -->

# Session — live-gameline nightly capture, then 09-04 decomposed to the game

**Lane: NONE.** This session was the scheduled task
`live-gameline-accuracy-snapshot` plus one follow-up question ("why'd the sign
flip on 9-4"). Read-only against production: no code edited, no lane claimed, no
deploy, no claim taken, `render.yaml` untouched. Recording the no-lane fact
rather than opening a 54th lane for finished read-only work.

<!-- primary tree (uncommitted) .syndicate/log/2026-09-08.md lines 291-291; nearest heading: ## What changed, by file -->

  session** (38 -> 40). The working copy is **+6 rows against HEAD**; the other 4

<!-- primary tree (uncommitted) .syndicate/log/2026-09-08.md lines 298-300; nearest heading: ## What changed, by file -->

  post-fix trend" paragraph carried 53 games / -0.00218 and told the next run to
  report the model as marginally AHEAD. Superseded and now wrong-signed; refreshed
  to point at the tool rather than a frozen figure.

<!-- primary tree (uncommitted) .syndicate/log/2026-09-08.md lines 352-364; nearest heading: ## Dead ends, and why -->

- **Staleness as the explanation for 09-04 — REJECTED BY MEASUREMENT, not dropped.**
  The story was clean (frozen ~0.55 market quotes, accidentally right on a
  comeback) and the fresh cut kills it: quote_age <= 120s scores **+0.1048**
  (n=27) against +0.0547 for >120s (n=127). The model's deficit is *larger* on
  exactly the prices someone could have taken.
- **`build_finals_index` over the served board doc** — returned 0 entries. Not a
  bug in the function; the summary payload simply has no scores. Went to StatsAPI.
- **`ls`/`find` under `data/mlb_source`** — exceeded 120s and had to be
  backgrounded. The OneDrive tree is not a viable way to answer "is this artifact
  local"; ask production.
- **A first comeback split returned n=0 for every bucket** because ledger
  `home_score`/`away_score` are **strings**. The buckets were empty and looked
  like a real null result. Coerced, and the split is where the whole finding is.

<!-- primary tree (uncommitted) .syndicate/log/2026-09-08.md lines 701-708; nearest heading: ## — the ledger LANDED, and what deliberately did not -->

## — the ledger LANDED, and what deliberately did not

**ON `origin/main` AS `2338a082`, VERIFIED BY READING THE CONTENT BACK OUT** — not by the push exit code. Eight content probes against `git show origin/main:<file>` all pass: the measurement, the deploy row, three named rules, the false-verdict log section, another session's rescued entry, and the leads.

**Landed (4 files, 795 insertions, 0 deletions on every one):**
- `deploys.md` +2 sections — the `57052784` deploy and the reading that settles it (178/178, 10/10 games, 32 distinct values, control 0), including the false FALSIFIED published and withdrawn.
- `learnings.md` +7 rules, each from something that went wrong today.
- `log/2026-09-08.md` +14 sections — nine mine and **FIVE belonging to an earlier session** whose entry lived only in an UNTRACKED local file and had never reached `origin/main`. Checked before appending: 44 headings, 0 duplicated.

<!-- primary tree (uncommitted) .syndicate/log/2026-09-08.md lines 711-715; nearest heading: ## — the ledger LANDED, and what deliberately did not -->

**HOW, and why it took a worktree.** The primary tree is **599 commits behind** and its ledger files diverge hard — `lanes.md` 155KB local vs 322KB upstream (**208** upstream commits since HEAD), `deploys.md` 1.53MB vs 1.62MB (**95**), `state.md` 117KB vs 181KB (**42**). Committing from there reverts other sessions' work, which is precisely what `ledger-commit-guard.py` refused all day. A branch cut fresh from `origin/main` with ONLY ADDITIONS replayed onto it sidesteps that entirely — and the 0-deletions figure on all four files is the proof, not a hope.

**DELIBERATELY NOT LANDED: `lanes.md`, `lanes_history.md`, `state.md`.** The whole day's lanes work — trim, block reconcile, status reconcile, ownership sweep, archive; 322KB -> 155KB, 54 OPEN -> 17, claims 118 -> 79 — is a restructure of a snapshot now 208 commits stale. Replaying it would revert upstream. **It remains LOCAL HYGIENE ONLY: this tree's digest is clean, `origin/main`'s is not.** Redoing it against current `origin/main` is a real, and separate, piece of work. `state.md` was excluded for the same reason: my edits were surgical insertions into a giant contended cell that has moved 42 commits underneath them.

**So the ledger is landed and the lane cleanup is not.** Anyone reading `origin/main` gets the measurement, the rules and the narrative; anyone reading THIS tree additionally gets a tidy `lanes.md` nobody else can see.

<!-- primary tree (uncommitted) .syndicate/log/2026-09-08.md lines 718-724; nearest heading: ## — THE LEDGER IS LANDED. Two commits on `origin/main`, and the lanes cleanup was REDONE rather than replayed -->

## — THE LEDGER IS LANDED. Two commits on `origin/main`, and the lanes cleanup was REDONE rather than replayed

### VERIFIED — both commits are on `origin/main`, content-checked not SHA-checked
`2338a082` (ledger additions) and `53b06a1e` (lanes cleanup). Their pre-rebase SHAs report `0` from `git branch -r --contains` because BOTH pushes needed a rebase mid-flight — other sessions are pushing continuously. **SHA identity is the wrong instrument after a rebase; content is the right one.** Verified by reading `origin/main` back: final coverage measurement OK, deploy record OK, three of the new rules OK, rescue-branch lead OK, log entry OK, 24 sweep notes in `lanes_history.md`, 176 pointer lines in `lanes.md`.

### WHY THE LANES WORK WAS DONE TWICE
The earlier local cleanup was correct arithmetic on a stale file: the primary tree is **604 commits behind** and its `lanes.md` diverged 208 commits from upstream. Pushing it would have reverted a great deal of other sessions' work — which is exactly what `ledger-commit-guard.py` had been refusing all day, correctly. So the second pass **re-derived the whole thing from `origin/main`'s own lane population** in a worktree cut fresh from it. Same procedure, different inputs, and the inputs are what made it landable.

<!-- primary tree (uncommitted) .syndicate/log/2026-09-08.md lines 730-730; nearest heading: ### WHY THE LANES WORK WAS DONE TWICE -->

| unowned / stale>7d | 26 / 20 | **2 / 0** | |

<!-- primary tree (uncommitted) .syndicate/log/2026-09-08.md lines 733-741; nearest heading: ### WHY THE LANES WORK WAS DONE TWICE -->

**What did NOT change is the point:** claims 64 -> 64, 15 OPEN blocks retained, 0 body lines lost.

### WHAT WAS LANDED, AND WHAT WAS DELIBERATELY NOT
Landed: the live-gameline measurement (178/178 rows, 10/10 games, against a pre-fix control of 0), 7 rules, 14 log sections — **5 of which belonged to an EARLIER session whose entry sat in an untracked local file and had never reached `origin/main`** — 2 leads, and the lanes cleanup.

NOT landed: `state.md`. My edits there were surgical insertions into a contended table cell on a file 42 upstream commits stale; replaying them safely needs the same re-derivation the lanes work got, and I did not do it. **The measurement is fully recorded in `deploys.md`, so nothing is lost — but `state.md`, the file sessions read FIRST, does not yet carry it.** That is the one real gap left.

### A PREFIX BUG, CAUGHT BY AN ASSERTION
`### <slug>` also matches a LONGER slug — a hyphen is a word boundary — so `ncaaf-live-resim` matched `ncaaf-live-resim-wire`, a different and still-OPEN lane. The pointer step asserted and refused to write 50 possibly-wrong lines. Checked directly on `origin/main` afterwards: `ncaaf-live-resim-wire` is still OPEN, `ncaaf-live-resim` is archived. Slug matching now uses `(?![a-z0-9-])`. **The assertion did the work a summary would not have.**

<!-- primary tree (uncommitted) .syndicate/log/2026-09-08.md lines 744-744; nearest heading: ### ENCODING, FIFTH TIME -->

`subprocess.run(text=True)` decodes as cp1252 on this machine and died on `0x9d` mid-verification. Five today: CRLF in a slug list (48 no-op deletions), a LF pattern matching 0 against CRLF, a heredoc collapsing a backslash, `open(...,"w")` mangling em-dashes, and this. **Every read AND every write on this machine needs an explicit `encoding="utf-8"`, subprocess included.**

<!-- primary tree (uncommitted) .syndicate/log/2026-09-08.md lines 747-747; nearest heading: ### STATE AT CLOSE -->

Both worktrees (`ledger-land`, `lanes-cleanup`) verified clean with 0 unpushed, and removed. The primary tree remains 604 behind with its own divergent ledger copies — untouched and uncommittable, which is correct.

<!-- primary tree (uncommitted) .syndicate/log/2026-09-08.md lines 750-766; nearest heading: ## — `state.md` landed. The ledger work is COMPLETE: three commits on `origin/main` -->

## — `state.md` landed. The ledger work is COMPLETE: three commits on `origin/main`

### VERIFIED — all three are on `origin/main`, checked by CONTENT
`2338a082` (measurement + 7 rules + 14 log sections + 2 leads), `53b06a1e` (lanes cleanup), `d06ee4e9` (state.md). Every push needed a rebase — other sessions push continuously — so **SHA identity is the wrong instrument here and content is the right one.** Each was verified by reading `origin/main` back: on `state.md`, all five markers present (`pregame_home_win_prob IS POPULATED`, the 178/178 figure, the withdrawn FALSIFIED, the three closed levers, the 6.5% recalibration ceiling) and `state_key_check.py` coherent.

### THE `state.md` LAND WAS THE SAME TRAP AS `learnings.md`, AND WORTH NAMING TWICE
My local copy of the `MLB live game-line model` cell was **22,966 chars against upstream's 8,038** — upstream had TRIMMED it since. **A stale local copy that is LARGER reads like it has more, when it actually has less plus other people's deleted content.** Pasting mine would have silently reverted that trim while looking like a routine update, and no deletions count would have shown it because the reverted content returns as ADDITIONS.

So the clause was written FRESH and PREPENDED: **+3,130 chars, not +15,000**, with detail delegated to `deploys.md ## 2026-09-09 01:40:53Z`. Verified surgically before commit: upstream's cell content preserved **verbatim**, exactly **1 line** differs, **line counts match** (2195 = 2195).

### THE SHAPE OF THE WHOLE LEDGER LAND
Three files needed three different treatments, and getting that wrong in either direction was the risk:
- **`learnings.md`** — stale, upstream already compliant -> RECONCILE onto upstream, carry my rules. A trim would have destroyed 61 upstream rules.
- **`lanes.md`** — stale AND upstream over budget -> REDO the whole cleanup against upstream's own lane population. Replaying my local version would have reverted 208 commits.
- **`state.md`** — stale AND upstream trimmed -> write a NEW compact clause, prepend, touch nothing else.

**"Land the ledger" was never one operation.** The uniform move — commit the local files — was wrong for all three, which is exactly what `ledger-commit-guard.py` had been refusing all day.

<!-- primary tree (uncommitted) .syndicate/log/2026-09-08.md lines 769-774; nearest heading: ### FINAL STATE -->

`origin/main`: `lanes.md` 155 KB / 15 OPEN / 2 unowned / 0 stale, claims 64; `learnings.md` carries the 7 new rules; `deploys.md` carries the deploy and the measurement; `state.md` carries the findings; `leads.md` carries 2 leads including the rescued orphan branch.

All three worktrees removed and all three `ledger/*` branches deleted, each verified clean with 0 unpushed first. **Both removals needed a second attempt** — this session's own shell held the cwd, `git worktree remove` returned 128, and the tool fell back to deleting the directory and pruning; verified rather than assumed. 41 worktrees remain, the ones deliberately held back (OPEN lanes, uncommitted work, `recover/stash-*`).

### UNCHANGED AND CORRECT: the primary tree is still divergent
`state.md`, `lanes.md`, `learnings.md`, `deploys.md` still show modified and the tree is **605 behind**. That is not debt — those local copies were the stale inputs, superseded by what is now on `origin/main`. **Nobody should commit them from here.** Anyone wanting this tree current should pull, not push.

## From primary tree (uncommitted): `.syndicate/lanes_history.md` -- 6 line(s) found nowhere in origin/main's ledger


<!-- primary tree (uncommitted) .syndicate/lanes_history.md lines 28517-28517; nearest heading: ### mlb-pregame-baseline-feed — CLOSED 2026-09-08 — opened 2026-09-08 — session d76b711b — **GOAL: MET. `pregame_home_win_prob` is populated -->

### mlb-pregame-baseline-feed — CLOSED 2026-09-08 — opened 2026-09-08 — session d76b711b — **GOAL: MET. `pregame_home_win_prob` is populated in production: 38/38 priced full-game h2h rows, 7 games, 7 distinct values `[0.469..0.6757]`, against a pre-fix control of 0.** Verification RAN; the reading is in `deploys.md` `## 2026-09-08 22:43:12Z`. Two defects fixed, and the second (the `live` lane having no prediction row) was invisible to all four unit tests and caught only end-to-end. **A false FALSIFIED was published and withdrawn mid-verification — postmortem in `learnings.md` 2026-09-08, and the instrument was hardened.** Earlier status: DEPLOYED, READING NOT YET TAKEN. `57052784` live on **live-odds-worker** 20:44:27Z (`dep-dag747p5efls73fcb3n0`); claim acquired 20:32:43Z and RELEASED. The field reaches the ledger only via the `live` lane, which exists only for a LIVE game — all 15 were `Preview` at deploy time, so a null read now would say nothing. **PRE-FIX CONTROL, same script and predicate as the pending after-reading: 2026-09-07, 4,017 live rows, 12 games, 0 non-null.** Watcher `bn3mlt0vs` runs `scratchpad/measure_pregame_baseline.py` once a game is Live; a LATE reading stays valid because the 09-08 ledger persists. Measurement recorded as PENDING in `deploys.md`. Earlier status: CODE LANDED AND VERIFIED LOCALLY. THE FIX IS TWO DEFECTS, NOT ONE, AND THE SECOND WAS INVISIBLE TO EVERY UNIT TEST.** (a) the camelCase/snake_case key mismatch below; (b) **the `live` lane had no prediction row at all.** `live_gameline_from_lens` returns the FIRST lens row stamped `live_mc` and the lane order puts `live` before `full`, so the `live` lane's baseline is the one that reaches the ledger — but `card["predictions"]` only ever holds `full`/`first1`/`first3`/`first5`, so `predictions.get("live")` was None and fixing (a) alone still produced `pregame_home_win_prob: None` in production. Fixed by mapping the `live` lane to the FULL-GAME baseline (`innings: 9` — it IS the full game, re-simulated). **Only the end-to-end test caught (b); all four unit tests were green with it broken.** ROOT CAUSE (a), verified before any edit: a camelCase/snake_case key mismatch, three read sites, no writer anywhere.** `pregame_home_win_prob` is populated on **0 of 2872 v4 rows and 0 of 531 v5 rows** of the exported MLB ledger (08-20..09-07) — never once since it shipped in `4d20ea00` — while `progress_fraction`/`inning`/`outs`, added in the SAME commit and travelling the SAME hops, are 2872/2872. `_build_game_lens` reads `baseline_probs.get("homeWin")`/`.get("awayWin")`; the only producers of that dict (`_merge_prediction_row`, `_normalized_full_game_probs`) write `home_win_prob`/`away_win_prob`. Across the whole `vendor/` tree `"homeWin"`/`"awayWin"` occur at exactly THREE sites and all three are READS — there is no writer, so the value can never be non-None. This is `learnings.md:3097` exactly: keying a predicate to a field name the record does not store.

<!-- primary tree (uncommitted) .syndicate/lanes_history.md lines 28520-28524; nearest heading: ### mlb-pregame-baseline-feed — CLOSED 2026-09-08 — opened 2026-09-08 — session d76b711b — **GOAL: MET. `pregame_home_win_prob` is populated -->

- **SHARED FILE, DECLARED `[user decision 2026-09-08]`:** `vendor/mlb_bettingv2/tools/web/flask_frontend.py` is claimed by OPEN lane `mlb-live-segment-pricing` (session 3492626c), which is editing the SAME function `_build_game_lens`. That session is unreachable — `3492626c` appears nowhere in the session roster, though its claim marker was touched 2026-09-08 11:59 — so this was NOT coordinated by message. Precedent for declaring rather than editing silently is that lane's own `board_enrichment.py` note. My change is orthogonal to theirs: it repairs the pregame BASELINE read (lines ~16933/16935/16936 local, ~17025/17027/17028 on `origin/main`) and touches nothing in the first5 lane/pricing path. Noted in that lane's block too.
- Hypothesis: n/a — this is not diagnostic any more. The root cause is measured and the mechanism is read directly from the source.
- Falsification test: if `predictions[lane_key]` turns out to carry a camelCase `homeWin` on any real card, then the current read is correct and the null has another cause. Checked: no writer of that key exists in `vendor/`, and the field is null on 3,403 of 3,403 production rows.
- Verification: **RAN, LOCAL — PASSES. PRODUCTION NOT YET READ.** New `tests/test_mlb_pregame_baseline_lane.py`, 5 tests, drives the real `_build_game_lens`. **Mutation check, each half reverted separately: (a) key rename reverted → 4 of 5 FAIL; (b) live→full mapping reverted → the end-to-end test FAILS alone.** Restored → 5 pass. Regression: **196 pass** across `test_live_gameline_{join,quote_age,ledger,score}.py` + `test_live_projection_market_key.py`, and **75 pass** across four MLB live-lens suites. The other lane's planned test files (`test_live_gameline_segment_pricing.py`, `test_live_mc_first5.py`) do not exist yet, so nothing of theirs was run or broken. **STILL OWED: a production ledger row with a non-null `pregame_home_win_prob`.** `_build_game_lens` runs on refresh-worker / live-odds-worker and is hard-refused in the web request path, so this needs a worker deploy; until then the field is still null on every production row. Original plan follows. **REACHABILITY FIRST, and the existing test cannot supply it.** `tests/test_live_gameline_quote_age.py:262-273` asserts `rec["pregame_home_win_prob"] == 0.5571` but hand-writes `"baselineHomeWinProb": 0.5571` into its fixture and never executes `_build_game_lens` — it is green today, with the field null in 100% of production rows. So: (1) a NEW test that drives the real `_build_game_lens` over a `predictions` dict in the shape `_merge_prediction_row` actually produces (`home_win_prob`), asserting the lane's `baselineHomeWinProb` is the VALUE, not merely present; (2) a mutation check — revert the key rename and that test must FAIL; (3) production: a ledger row for a live MLB game carrying a non-null `pregame_home_win_prob`, which needs a refresh-worker/live-odds-worker deploy, since `_build_game_lens` runs on the workers and is hard-refused in the web request path (`request_path_guard.py:175-199`).
- **VENDORED FILE — a re-vendor from upstream silently reverts this.** `reference_vendor_upstream_repos.md` records the upstream for `mlb_bettingv2`; the fix should go upstream too or be re-applied after any vendor sync.

## From primary tree (uncommitted): `.syndicate/lanes.md` -- 1 line(s) found nowhere in origin/main's ledger


<!-- primary tree (uncommitted) .syndicate/lanes.md lines 93-93; nearest heading: ### web-oom-census — OPEN — opened 2026-09-09 — session 2edf8b82-9f8a-4d32-bf26-ca43ecd1ea5a -->

- Files: NONE. This lane writes no code and claims no path; its only write is additive into one TODO item held by another OPEN lane, declared in that lane's block. Two OPEN holders on one path is what `check_lane_invariants` refuses, so it is a declaration and not a claim.

## From stash@{4}: `.syndicate/lanes.md` -- 49 line(s) found nowhere in origin/main's ledger


<!-- stash@{4} .syndicate/lanes.md lines 767-767; nearest heading: ### evaluation-ledger-projected-mirror — OPEN — opened 2026-09-04 — session 5959f891-a9e4-4904-a2f0-486a008278d9 — **BUILT, TESTED AND SHIPP -->

- released: `syndicate/features/shared/artifact_publisher.py` — **moved OUT of the `- Files:` line above on 2026-09-05 by lane `render-egress-transport` (session 9e40eb04).** That line already read "one allowlist entry — the file is explicitly RELEASED and NOT CLAIMED", and it still enforced as a claim: `_claimable_prefix` cuts a Files line at the FIRST disclaimer marker and reads paths only from what PRECEDES it, so a path written BEFORE its own release note is claimed anyway — `lane-guard.py` refused the edit. That is the identical trap the next bullet documents for `intelligence_evaluation.py`, one path later in the same line. Owning session `5959f891-a9e4-4904-a2f0-486a008278d9` is absent from the session roster **including archived** (60 rows, back to 2026-08-31), so the claim was being held on behalf of nobody. Nothing else in this lane is touched, and the allowlist entry it describes is a different region of the file from the publish/pull transport `render-egress-transport` edits.

<!-- stash@{4} .syndicate/lanes.md lines 945-946; nearest heading: ### ncaaf-live-resim — OPEN — opened 2026-09-05 — session 3492626c — NCAAF has a full live slate and produces NO live-aware model edge -->

  **2026-09-05 ~22:0xZ, on an explicit user override, after this session was
  asked TWICE for the claim and did not answer, these two moved to lane

<!-- stash@{4} .syndicate/lanes.md lines 1286-1286; nearest heading: ### segment-refusal-deploy — OPEN — opened 2026-09-05 — session 3492626c-1ec4-4366-9dbe-f194ae319c84 — **BLOCK RECONSTRUCTED 2026-09-05 by ` -->

### segment-refusal-deploy — OPEN — opened 2026-09-05 — session 3492626c-1ec4-4366-9dbe-f194ae319c84 — **BLOCK RECONSTRUCTED 2026-09-05 by `ledger-repair-invariants`; see the reconstruction bullet before trusting any detail**

<!-- stash@{4} .syndicate/lanes.md lines 1390-1390; nearest heading: ### render-egress-transport — OPEN — opened 2026-09-05 — session 9e40eb04-9f1c-464b-a6fb-5acac211e775 -->

- **THIS BLOCK WAS STALE IN THE PRIMARY TREE UNTIL 2026-09-05 ~23:0xZ, AND THAT IS THE POINT WORTH KEEPING.** The version above (no `/export` token, both shared files off the `- Files:` line) landed on `origin/main` in `3cb5b4ba`. The primary tree kept the superseded copy, so `check_lane_claims.py` — which resolves `lanes.md` from the tree it runs in, and is run from the PRIMARY tree by hooks and by session start — went on reporting a bad `export` claim that no longer existed upstream. A peer lane reported it to me; I re-ran the checker at the tip myself and got **exit 0, zero BAD claims**. **Both of that exchange's findings were artifacts of a stale copy** (mine: a token already removed; theirs: a `.syndicate/lanes.md` claim that no longer exists upstream). Only MY block was repaired here, deliberately: the file also held **98 uncommitted lines from another session**, and `git checkout origin/main -- .syndicate/lanes.md` — which the ledger guard suggests — would have destroyed them silently, since a deletions count cannot see an uncommitted addition.

<!-- stash@{4} .syndicate/lanes.md lines 1426-1430; nearest heading: ### ncaaf-live-resim-wire — OPEN — opened 2026-09-05 — session 520cd594-1ffa-4116-8951-4c4b53ffbfcf — the NCAAF live re-sim is BUILT AND INE -->

### ncaaf-live-resim-wire — OPEN — opened 2026-09-05 — session 520cd594-1ffa-4116-8951-4c4b53ffbfcf — the NCAAF live re-sim is BUILT AND INERT; nothing calls the producer
- **RESTORED VERBATIM 2026-09-05 ~22:4xZ by lane `edge-basis-moneyline`, not
  written from scratch.** `check_lane_invariants.py` reported this slug as a
  live marker (`.current-lane.520cd594-...`) whose block was "in NO ledger file"
  — destroyed, or never written down. It was neither: the block existed, complete,

<!-- stash@{4} .syndicate/lanes.md lines 1433-1440; nearest heading: ### ncaaf-live-resim-wire — OPEN — opened 2026-09-05 — session 520cd594-1ffa-4116-8951-4c4b53ffbfcf — the NCAAF live re-sim is BUILT AND INE -->

  in an UNCOMMITTED `.syndicate/lanes.md`. Every line from `- Goal:` down is that
  block unedited. Two things were changed and both are named here: the header's
  ASCII hyphens became U+2014 (lane-guard BLOCKS a lane whose own header uses
  hyphens, so the owner would have been locked out of its own files), and the
  `Files:` line is re-stated below against a ledger that MOVED since the original
  collision check.
- **THIS LANE HAS STAGED, UNCOMMITTED WORK AND NO COMMITS.** Its worktree is at
  `c27e9c04` with `origin/main..HEAD` EMPTY and four paths in its index:

<!-- stash@{4} .syndicate/lanes.md lines 1443-1444; nearest heading: ### ncaaf-live-resim-wire — OPEN — opened 2026-09-05 — session 520cd594-1ffa-4116-8951-4c4b53ffbfcf — the NCAAF live re-sim is BUILT AND INE -->

  `tests/test_ncaaf_live_resim_wiring.py` (A, staged). Nothing is pushed. If that
  worktree is removed the work is gone — commit it before anything else.

<!-- stash@{4} .syndicate/lanes.md lines 1452-1455; nearest heading: ### ncaaf-live-resim-wire — OPEN — opened 2026-09-05 — session 520cd594-1ffa-4116-8951-4c4b53ffbfcf — the NCAAF live re-sim is BUILT AND INE -->

  **THAT IS THE ONLY PATH THIS BLOCK CLAIMS, AND THE OTHER THREE ARE SURFACED
  RATHER THAN TAKEN.** The original block claimed all four on a collision check
  that returned FREE; re-run 2026-09-05 ~22:4xZ with the guard's own
  `claims_by_path` over THREE ledger copies, they no longer agree with each

<!-- stash@{4} .syndicate/lanes.md lines 1467-1468; nearest heading: ### ncaaf-live-resim-wire — OPEN — opened 2026-09-05 — session 520cd594-1ffa-4116-8951-4c4b53ffbfcf — the NCAAF live re-sim is BUILT AND INE -->

  A second claim would break "every claimed file has exactly one OPEN holder" and
  would guard nothing anyway. `render-egress-transport` has NO block on

<!-- stash@{4} .syndicate/lanes.md lines 1471-1475; nearest heading: ### ncaaf-live-resim-wire — OPEN — opened 2026-09-05 — session 520cd594-1ffa-4116-8951-4c4b53ffbfcf — the NCAAF live re-sim is BUILT AND INE -->

- **AND THE `artifact_publisher.py` COLLISION MAY BE A PARSER ARTEFACT, NOT A
  DISPUTE — DO NOT RESOLVE IT BY READING.** `evaluation-ledger-projected-mirror`'s
  own Files line says `artifact_publisher.py` "(one allowlist entry — the file is
  explicitly RELEASED and NOT CLAIMED)" and `run_refresh_worker.py` "(the autorun
  call site only)". The parser reads BOTH BACKWARDS: `_claimable_prefix` cuts a

<!-- stash@{4} .syndicate/lanes.md lines 1478-1483; nearest heading: ### ncaaf-live-resim-wire — OPEN — opened 2026-09-05 — session 520cd594-1ffa-4116-8951-4c4b53ffbfcf — the NCAAF live re-sim is BUILT AND INE -->

  `run_refresh_worker.py` — which the same sentence intends to KEEP. Both lanes
  want the same one-line `HOT_ARTIFACT_PATTERNS` addition, so the overlap is real
  and needs a message, not a re-read. See `learnings.md` 2026-09-05, *"in
  `lanes.md` a disclaimer AFTER a path does not disclaim it"*.
- **SCOPED CLAIM ON `artifact_publisher.py`, and the region split is the point.**
  ONE additive `HOT_ARTIFACT_PATTERNS` entry plus its comment; nothing else in

<!-- stash@{4} .syndicate/lanes.md lines 1486-1492; nearest heading: ### ncaaf-live-resim-wire — OPEN — opened 2026-09-05 — session 520cd594-1ffa-4116-8951-4c4b53ffbfcf — the NCAAF live re-sim is BUILT AND INE -->

  holds the same file for "publish + pull transport" and has already released it
  from `evaluation-ledger-projected-mirror`; I messaged that session before
  touching it and its own block uses this same region-split convention for
  `blueprints/ops.py`. My scope in `ops.py` is likewise ONE endpoint,
  `/api/ops/live-lens/snapshot-index`, which their claim does not name.
- Ops scope: `snapshot-index` gains `sources_seen` (it already builds the index
  the diagnostic comes from and threw it away) and the producer's `coverage`

<!-- stash@{4} .syndicate/lanes.md lines 1498-1505; nearest heading: ### ncaaf-live-resim-wire — OPEN — opened 2026-09-05 — session 520cd594-1ffa-4116-8951-4c4b53ffbfcf — the NCAAF live re-sim is BUILT AND INE -->

  `scripts/poll_ncaaf_live_state.py`. Every one of those is imported READ-ONLY,
  the precedent being `ncaaf/live_game_state.py` importing `poll_ncaaf_live_state`.
- **STALE SINCE THIS BLOCK WAS WRITTEN:** `live_gameline_join.py` is no longer
  held by `ncaaf-live-resim` — lane `edge-basis-moneyline` took it on a user
  override, landed `5ce75195` + `fda5c28a`, and released it; it is FREE now. The
  `edge_basis` label on live moneyline rows changed from `pregame` to `live`.
  Read-only here either way, so this lane's scope is unaffected.
- Hypothesis (diagnostic half, written before testing): the re-sim's two inputs

<!-- stash@{4} .syndicate/lanes.md lines 1512-1512; nearest heading: ### ncaaf-live-resim-wire — OPEN — opened 2026-09-05 — session 520cd594-1ffa-4116-8951-4c4b53ffbfcf — the NCAAF live re-sim is BUILT AND INE -->

  `snapshot["coverage"]["refusals_by_reason"]` recorded beside it -- a zero with

<!-- stash@{4} .syndicate/lanes.md lines 1517-1520; nearest heading: ### ncaaf-live-resim-wire — OPEN — opened 2026-09-05 — session 520cd594-1ffa-4116-8951-4c4b53ffbfcf — the NCAAF live re-sim is BUILT AND INE -->

  with 118 live NCAAF rows on the shortlist and 0 carrying a `live_gameline`
  block. The premise of this lane holds.
- Blocked by: nothing technical. **Owner action required:** commit the staged
  work, then settle the three contested paths with

## From stash@{4}: `.syndicate/learnings.md` -- 1 line(s) found nowhere in origin/main's ledger


<!-- stash@{4} .syndicate/learnings.md lines 581-581; nearest heading: ## Entries before 2026-08-20 — moved to `learnings_archive.md` `[2026-09-01]` -->

## Entries before 2026-08-20 — moved to `learnings_archive.md` `[2026-09-01]`

## From stash@{4}: `.syndicate/log/2026-09-04.md` -- 119 line(s) found nowhere in origin/main's ledger


<!-- stash@{4} .syndicate/log/2026-09-04.md lines 2518-2535; nearest heading: ## session 0aef6a99 — lane `lane-invariant-single-source` (CLOSED) + a user-directed PRIMARY TREE SYNC -->

## session 0aef6a99 — lane `lane-invariant-single-source` (CLOSED) + a user-directed PRIMARY TREE SYNC

**Two pieces of work. The lane landed as `312c93a9`; the sync moved the shared
tree `5f54bce5` -> `110d92f0` and is NOT a lane (it claimed no files).**

### 1. lane `lane-invariant-single-source` — the checker USES the guard's parser now

- **The 5 red tests were a broken DETECTOR, not a drifted regex.** The four
  pinned regexes and the 14-marker tuple were byte-identical to the hook's.
  `tests/test_check_lane_invariants.py` scraped `.claude/hooks/lane-guard.py`
  for `^HEADER_RE = re.compile(...)$`; the parser had been extracted into
  `.claude/hooks/lane_claims.py`, so the scrape found nothing and all five
  asserted "the hook changed shape" while the checker still exited 0 / green.
- **The real drift was in everything the test never pinned** — four cases
  reproduced on clean `origin/main`, VERIFIED by running both parsers:
  ASCII-hyphen lane headers (guard sees, checker blind); a blank line inside a
  Files block (ends it for the guard, not the copy); backslash paths
  (`_norm`'d by the guard only); and the severe one — a Files line naming

<!-- stash@{4} .syndicate/log/2026-09-04.md lines 2538-2605; nearest heading: ### 1. lane `lane-invariant-single-source` — the checker USES the guard's parser now -->

  copied `_claimable_prefix` did not mask backticked spans, cut inside the
  filename and dropped the rest of the line. A lane whose claim set reads empty
  cannot contest anything, so "exactly one holder" passed vacuously.
- **Fix:** `scripts/check_lane_invariants.py` imports the parser from
  `lane_claims.py` — the same import `lane-guard.py` does. `learnings.md:4712`
  already prescribed exactly this ("Prefer `lane_claims.py` regardless... a pure
  library, no module-level `main()`, no `__file__` dependency, no stdin read").
  The import guard **refuses (exit 2) rather than falling back to a copy**;
  `lane-guard` fails OPEN because a guard that blocks every edit is worse than
  none, but a CHECK whose whole output is a verdict must never print a green one
  it did not compute.
- **Also fixed in the same pass:** `open_lanes_under_archived` had a fifth
  inline copy of the header regex, em-dash only, so a stray ASCII-hyphen OPEN
  lane inside the archive was invisible while still holding claims.
- **VERIFIED:** 30/30 in that file (was 16 passed / 5 failed); 70 passed across
  the five lane-family test files; the checker and the guard return an
  IDENTICAL claim set on the live `lanes.md`. The drift tests now assert
  `is`-identity, not equality — an equal copy is exactly what the old file
  permitted, and identity cannot be re-broken by pasting a definition back.
- **BLOCKER CLEARED FIRST, `[user decision]`:** `scripts/check_lane_invariants.py`
  was phantom-claimed by OPEN lane `ncaaf-live-cadence` (prose "(caught by
  `check_lane_invariants.py`)" sitting inside its `- Files:` block, no
  disclaimer marker), and `lane-guard` really did block the edit (exit 2,
  reproduced). Fixed by splicing ONE top-level bullet before that lane's
  trailing prose — the remedy its own test documents. Its four declared paths
  are untouched and still guarded; the two other dropped entries were bare
  duplicates of paths it still holds in full form. Verified with `_claims()`.

### 2. PRIMARY TREE SYNC `5f54bce5` -> `110d92f0` (201 commits, fast-forward)

- **NOTHING LOST, measured in BOTH directions against the sync target:
  0 upstream lines, 0 local content.** Of 5 local lines that did not survive,
  all 5 are accounted for: 3 stale lane headers and 1 collision note that
  upstream deliberately rewrote, plus one `team_aliases.py` claim upstream
  deliberately released (`RELEASED [TAKEN by lane nfl-la-rams-alias]`, since
  CLOSED).
- **Method, because a naive sync here destroys live work:** 25 tracked files
  were modified. 13 held nothing absent upstream and were reset; the other 12
  were stashed, then fast-forwarded, then 3-way merged back. Snapshots first via
  `git stash create` (writes a recoverable commit WITHOUT touching the tree) at
  `refs/backup/pre-sync-2026-09-04` and `-04b`; `stash@{0}` also retained.
- **One conflict:** `log/2026-09-04.md`, resolved as a UNION with a conservation
  assertion — a daily log is append-only and each side was a different session's
  entry. `discard-guard-sees-origin`'s 89 lines survive.
- **Three duplicate lane blocks were MINE** (`mlb-rate-refit`,
  `mlb-feed-live-terminal-refresh`, `mlb-final-state-mapping`): each side had
  exactly 1, the 3-way merge kept both headers. Collapsed to upstream's block
  with a script that refuses to drop any line it cannot explain. Deliberately
  did NOT run `trim_lane_blocks.py` — it wanted to move 52 blocks, far beyond a
  sync.
- **VERIFIED after:** `lane_identity_check` coherent (92 blocks / 92 slugs);
  `state_key_check` coherent; `check_lane_invariants` 58 claims / 14 OPEN /
  none contested; 70 tests pass; index reset to HEAD so no session inherits a
  half-merged index; 545 untracked files untouched, 0 collisions.
- **BELIEVED, NOT VERIFIED:** that the two live sessions whose files moved under
  them (`#632 web OOM`, `split_state --reindex`) were unaffected. Their content
  is provably intact in the tree; whether either had an in-memory view that went
  stale is not something I can measure from here.
- **A SYNC IS AN EVENT, NOT A STATE.** The tree was 3 commits behind within
  minutes of finishing and **17 behind within the hour**. Do not treat "the
  primary tree is at origin/main" as a fact with a shelf life.

### FOUND, NOT MINE TO FIX — two live sessions are working with NO lane block

`check_lane_invariants` (the new marker check, `786331fb`) reports 2 markers
naming lanes that exist in no ledger file:

- `web-oom-heap-roots` — `.current-lane.b2b5b45b`, marker written 22:00:22Z

<!-- stash@{4} .syndicate/log/2026-09-04.md lines 2608-2615; nearest heading: ### FOUND, NOT MINE TO FIX — two live sessions are working with NO lane block -->

**Both markers are ~5.5h old, so this is NOT a marker-before-block race — the
check is right.** `b2b5b45b` is `#632 web OOM`, RUNNING as of 03:31Z. Their file
claims are therefore unenforced and invisible to every other session. Only the
owning session can write these; `SendMessage` was unavailable to this session,
so it is surfaced here and to the user instead.

Separately, `check_lane_claims` reports 1 of 70 claims naming no file in the
repo: lane `measured-correlation-pays-off` claims ``lane`'s`` — prose read as a

<!-- stash@{4} .syndicate/log/2026-09-04.md lines 2618-2618; nearest heading: ### session 0aef6a99 (cont.) - LEDGER TRIM: lanes.md 1.08x -> 0.61x of cap -->

### session 0aef6a99 (cont.) - LEDGER TRIM: lanes.md 1.08x -> 0.61x of cap

<!-- stash@{4} .syndicate/log/2026-09-04.md lines 2621-2629; nearest heading: ### session 0aef6a99 (cont.) - LEDGER TRIM: lanes.md 1.08x -> 0.61x of cap -->

reported LEDGER OVER BUDGET and LANE ARCHIVE OWED 53. **53 blocks moved verbatim
to `lanes_history.md`; 259,693 -> 146,935 B (116,020 reclaimed, 44%).**

**VERIFIED INDEPENDENTLY OF THE TOOL'S OWN REPORT**, against a snapshot at
`refs/backup/pre-trim-2026-09-04`:
- claim set **70 -> 70, byte-identical as a SET** (not merely the same count)
- OPEN lanes **16 -> 16, identical set**
- **0 of 2,266 non-blank lines lost** - every line is in `lanes.md` or
  `lanes_history.md`. `git diff --numstat`: lanes.md -1075, history +1213.

<!-- stash@{4} .syndicate/log/2026-09-04.md lines 2632-2633; nearest heading: ### session 0aef6a99 (cont.) - LEDGER TRIM: lanes.md 1.08x -> 0.61x of cap -->

Why it mattered beyond the byte count: the digest truncates OPEN LANES to 600 B
against a **22,377 B** body, so every session was arriving ~97% blind to what

<!-- stash@{4} .syndicate/log/2026-09-04.md lines 2637-2649; nearest heading: ### session 0aef6a99 (cont.) - LEDGER TRIM: lanes.md 1.08x -> 0.61x of cap -->

no claims) moved out with the rest; their full bodies are in `lanes_history.md`.

**STILL OPEN, still not mine:** the 2 orphaned lane markers and the
`measured-correlation-pays-off` phantom claim are untouched by this - a trim
moves blocks, it cannot invent one for a marker that never had a block.
**`learnings.md` remains over budget (410KB > 390KB); `compact_learnings.py`
was NOT run** - that moves rule BODIES and is a larger blast radius than this
was, so it is left for a session that takes it deliberately.

### session 0aef6a99 (final) - the trim is REAPPLIED, and a guard gap found by nearly reverting it for the wrong reason

**State handed over: the trim is IN the working tree, uncommitted, verified.**
lanes.md 145,730 B / 42 blocks / 70 claims / 16 OPEN; 0 lines lost against

<!-- stash@{4} .syndicate/log/2026-09-04.md lines 2652-2680; nearest heading: ### session 0aef6a99 (final) - the trim is REAPPLIED, and a guard gap found by nearly reverting it for the wrong reason -->

**THE FINDING, and it is a real gap in `ledger_invariants`.** The primary tree
is **36 commits behind `origin/main`**, and committing its `lanes.md` from here
would drop **210 non-blank lines and 7 whole lane blocks** that exist upstream -
including the **OPEN** lane `accuracy-ledger-budget-raise`, and the CLOSED
`web-oom-retainer-census` / `mlb-ladder-refusal-deploy` (so those two sessions
DID write the blocks whose markers were orphaned earlier today).
**`ledger_invariants.violations()` returns 0 for that file.** Called directly,
not inferred from the hook's exit code. The staleness arm at
`ledger_invariants.py:211-248` keys on a stale tree RESURRECTING archived
content; a stale tree that is merely MISSING newer blocks is subtraction it does
not model, and `ledger-commit-guard` therefore allows the commit.

**MY MISSTEP, recorded because the reasoning is the reusable part.** I read that
exposure, attributed it to my own 116 KB trim, and restored `lanes.md` +
`lanes_history.md` from the pre-trim snapshot to remove the hazard. Then I
measured the restored state: **210 lines / 7 blocks, IDENTICAL**. The exposure
is a property of the tree being 36 commits behind and has nothing to do with the
trim - which is why the revert bought nothing and cost a verified 116 KB
reclamation. Re-applied, re-verified, 0 lines lost. **The trim is orthogonal to
the staleness; I should have measured both states before acting on either.**

**DO NOT commit `lanes.md` from this tree until it is synced.** Not because of
the trim - because of the 36 commits. After a sync the trim is one command
(`scripts/trim_lane_blocks.py --apply`) and fully reproducible, so if in doubt,
sync first and re-run it rather than committing what is here.

Still uncommitted and NOT mine: `deploys.md`, `state.md`, `state_ledger.md`,
`state_layer2.md` carry another session's work, which they committed as
`2010bcc7` and then `git reset HEAD~1` back into the tree. Left alone.

## From stash@{4}: `.syndicate/state.md` -- 1 line(s) found nowhere in origin/main's ledger


<!-- stash@{4} .syndicate/state.md lines 511-511; nearest heading: ## [subject-index] SUBJECT INDEX — every subject, and which file holds it -->

| [accuracy-autorun-rearm-state] | `#626`(h) IS ONE ENV KEY AWAY — THE CODE IS ALREADY LIVE `[2026-09-03, lane accuracy-autorun-rearm, no deploy  | `state_model.md` |

## From stash@{6}: `.syndicate/lanes.md` -- 41 line(s) found nowhere in origin/main's ledger


<!-- stash@{6} .syndicate/lanes.md lines 98-114; nearest heading: ### web-oom-arena-trend — CLOSED 2026-09-04 — opened 2026-09-04 — **FIRST POSITIVE IDENTIFICATION IN `#632`.** The arena hypothesis was FALS -->

- **REOPENED AND EXTENDED 2026-09-04 `[user: "widen it to all refs anyway"]`.**
  I had closed this lane calling the four-rev set a bounded approximation,
  "rejected on cost, not correctness". The cost was then MEASURED rather than
  assumed: lanes.md is 1,322 commits / 1,301 distinct blobs / 246 MB, 11.6-13.4s
  exhaustive; pickaxe (`git log --all -S`) is 5.9s PER LINE and loses on any
  multi-line residual. `_deep_lines` now searches every committed version across
  every ref, in three git processes regardless of ref count, and ONLY after the
  cheap revs fail — so the allow-path is unchanged (0.59s -> 0.60s measured).
  The budget became ONE deadline for the invocation, not one per path, because
  per-path let `checkout -- a b c` cost three budgets. A truncated search BLOCKS
  and says TRUNCATED; it never downgrades to "nowhere else".
  Verified same-instant on the live tree: 147 flagged -> 143, the four excused
  genuinely present in the 1,302 versions but on neither HEAD nor origin/main.
  Then verified end-to-end: installing the new hook was itself BLOCKED by the
  old one over 6 lines that were all in pushed commit `e3a5154f` — and the same
  command under the new hook exits 0 in 0.58s, while `lanes.md` with 143 truly
  unreachable lines still refuses. 40/40; 8 new cases fail on `e3a5154f`.

<!-- stash@{6} .syndicate/lanes.md lines 589-590; nearest heading: ### layer2-sim-disagrees — OPEN — opened 2026-09-03 — session 3492626c-1ec4-4366-9dbe-f194ae319c84 — **ANSWERED, FIXED, LANDED, NOT DEPLOYED -->

  at the top of the board; `model_edge` reaches 14.99 as a ranking value while
  market EV maxes at 5.14, so every top row is a model disagreement.** ONLY — the OPEN lane `ncaaf-chip-compact` lists this

<!-- stash@{6} .syndicate/lanes.md lines 751-751; nearest heading: ### mlb-rate-refit — OPEN — opened 2026-09-04 — session 3492626c-1ec4-4366-9dbe-f194ae319c84 — **CREDIBILITY WIRED AND VERIFIED: every stake -->

### mlb-rate-refit — OPEN — opened 2026-09-04 — session 3492626c-1ec4-4366-9dbe-f194ae319c84 — **CREDIBILITY WIRED AND VERIFIED: every stake was 1/16 Kelly, not 1/4. $19.64 -> $121.85, positions 4 -> 8 (6.2x; I predicted 3.5-4x).** NCAAF now trades on market_fair with the 17-sigma gate intact [USER DECISION] — 10 positions, 5 model_edge / 5 market_fair, NCAAF ADDED not displaced. Per-order cap $15.01 -> $35 [USER DECISION] after 4x stakes hit it; the env var would have been INERT (stored -> env -> default). Feed-gap stamp live and verified. Ligature fold + rate/name miscount split landed. **REFIT NOT SHIPPED: 4 of 4 IN-SAMPLE, which learnings.md 2026-08-31 FORBIDS; held-out split built and already shows inplay oos +0.1% -> +16.3%.** NEXT: read the OOS run, ship only the rates that survive it.

<!-- stash@{6} .syndicate/lanes.md lines 1245-1251; nearest heading: ### sim-clv-decomposition — **CLOSED 2026-09-04 — THE GATE WAS RUN AND THE ANSWER IS NO. RECOMMENDATION: LEAVE `(0.125, 1.5)` ALONE.** A non -->

### sim-clv-decomposition — **CLOSED 2026-09-04 — THE GATE WAS RUN AND THE ANSWER IS NO. RECOMMENDATION: LEAVE `(0.125, 1.5)` ALONE.** A non-zero `sim_component` does NOT predict better CLV; in the direction the board rewards it predicts WORSE, stratified `-0.113 [-0.253,+0.027]` on props and `-0.186 [-0.340,-0.033]` on game lines over 14,111 pregame-close rows. **Falsification, not an underpowered null** — powered to 0.25pp on props with >2,400/arm, so any props effect above +0.03pp is excluded. The order-side join is STRUCTURALLY dead (`sim_view` on 13 of 667 settled, all `agrees`; `disagrees` never placed once; a 10pp ROI gap needs 3,796 settled attributed orders). **Held out, the sign does not replicate** and the two book scopes disagree about tail calibration. **AND THE SCREEN CANNOT GATE THIS:** `score_sim_weight_impact.py` returns the identical PASS at weight 0.125/0.25/0.5/**1.0** — it screens the CAP, not the weight, with 3.9x headroom. Full record: `state_layer2.md [sim-weight-clv-decomposition]`. — opened 2026-09-04 — session 3492626c-1ec4-4366-9dbe-f194ae319c84
- Verification RAN: 17,714 rows harvested from `/api/ops/clv/report?rows=1`
  across 21 dates x 5 sports (2026-08-15..09-04 — the openings ledger starts
  08-15, so the HRR-poisoned 06-04..07-08 window **cannot** contaminate it);
  rates with denominators at every cut; PRE/POST 2026-09-01 split reported;
  `score_sim_weight_impact.py` swept over (weight, cap). NO DEPLOY, NO ENV VAR,
  no order touched — the weight is the operator's call and the evidence is filed

<!-- stash@{6} .syndicate/lanes.md lines 1254-1258; nearest heading: ### sim-clv-decomposition — **CLOSED 2026-09-04 — THE GATE WAS RUN AND THE ANSWER IS NO. RECOMMENDATION: LEAVE `(0.125, 1.5)` ALONE.** A non -->

- Goal: answer `_SCORE_SIM_WEIGHT`'s OWN unblock condition — *"settled > 0 and
  CLV decomposed by component"* — as a falsifiable claim, and return a
  recommendation on `(_SCORE_SIM_WEIGHT, _SCORE_SIM_CAP_PCT)` that INCLUDES
  "leave them alone". **READ-ONLY against production. NO DEPLOY, NO ENV VAR** —
  changing `SYNDICATE_SCORE_SIM_WEIGHT` re-ranks every bet and is the operator's

<!-- stash@{6} .syndicate/lanes.md lines 1261-1261; nearest heading: ### sim-clv-decomposition — **CLOSED 2026-09-04 — THE GATE WAS RUN AND THE ANSWER IS NO. RECOMMENDATION: LEAVE `(0.125, 1.5)` ALONE.** A non -->

  against every OPEN lane: nothing claims it (new path). This lane makes NO

<!-- stash@{6} .syndicate/lanes.md lines 1264-1277; nearest heading: ### sim-clv-decomposition — **CLOSED 2026-09-04 — THE GATE WAS RUN AND THE ANSWER IS NO. RECOMMENDATION: LEAVE `(0.125, 1.5)` ALONE.** A non -->

- Hypothesis: a non-zero `sim_component` predicts better realised CLV than a
  zero one, out of sample.
- Falsification test: bucketed by `sim_component` (zero / negative / positive,
  and by magnitude), realised CLV does not separate — or separates the wrong
  way — at a sample size large enough to detect the effect. **An underpowered
  null is NOT a falsification and must not be reported as one**; if n is too
  small, report the n required and when it accrues.
- Verification: rates with denominators at every cut, a PRE/POST 2026-09-01
  split (tail calibration shipped that day), the 2026-06-04..07-08 HRR-poisoned
  window excluded or segmented, and — only if the recommendation is to RAISE —
  `scripts/score_sim_weight_impact.py` run at the proposed (weight, cap) with
  its DOMINATION / SIDE-PICKING / REORDERING numbers reported. A weight that
  fails that screen is not shippable whatever the CLV says (2026-08-08: 286 of
  300 rows negative-EV, and at 0.5 the blend promoted every one of them).

## From stash@{6}: `.syndicate/learnings.md` -- 1 line(s) found nowhere in origin/main's ledger


<!-- stash@{6} .syndicate/learnings.md lines 528-528; nearest heading: ## Entries before 2026-08-20 — moved to `learnings_archive.md` `[2026-09-01]` -->

## Entries before 2026-08-20 — moved to `learnings_archive.md` `[2026-09-01]`

## From stash@{6}: `.syndicate/state.md` -- 1 line(s) found nowhere in origin/main's ledger


<!-- stash@{6} .syndicate/state.md lines 508-508; nearest heading: ## [subject-index] SUBJECT INDEX — every subject, and which file holds it -->

| [accuracy-autorun-rearm-state] | `#626`(h) IS ONE ENV KEY AWAY — THE CODE IS ALREADY LIVE `[2026-09-03, lane accuracy-autorun-rearm, no deploy  | `state_model.md` |

## From stash@{6}: `.syndicate/state_layer2.md` -- 3 line(s) found nowhere in origin/main's ledger


<!-- stash@{6} .syndicate/state_layer2.md lines 175-177; nearest heading: ## [layer2-realized-accuracy] THE LAYER 2 BOARD'S REALIZED ACCURACY — the portfolio book is the surface, and the measurement chain is broken -->

**PARTLY ANSWERED 2026-09-04 — against CLV rather than outcome, and from the
OPENINGS ledger rather than the orders. See `[sim-weight-clv-decomposition]`
below: the order-side join is structurally dead, the board-side one is not.**
