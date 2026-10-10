# Syndicate — Learnings

> **Append only.** Rules must be obeyable by a session with zero context.
> `FORBIDDEN` = never do this again. `EXONERATED` = ruled out, stop
> re-investigating.

> **USE THE TEMPLATE — it is what lets this file be compacted without judgement.**
> Five bullets: `What we believed` / `What was actually true` / `How we found
> out` / `The rule going forward` / `Cost`. The compaction pass keeps the RULE
> bullet in this file and moves the other four to `learnings_evidence.md`, so a
> templated entry shrinks to ~500B automatically and every rule stays readable
> at session start.
>
> **Prose entries cannot be compacted mechanically.** As of 2026-08-16, 28
> entries (68 KB, all written 08-15) state their rule somewhere mid-paragraph
> rather than in a `The rule going forward` bullet. Extracting it needs a human
> reading each one, and a regex that guessed would keep the evidence and drop
> the rule — so they were left INTACT rather than mangled. They are the reason
> this file is 162 KB against a 117 KB budget.
>
> If you write a rule tonight, write it in the template and it costs the next
> session nothing.


<!-- LEARNINGS-INDEX:START -->

## Index — 1345 rules `[generated]`

> Full index: [`learnings_index.md`](learnings_index.md) — regenerate with
> `py -3 scripts/build_learnings_index.py` after appending. It spans BOTH
> this file and `learnings_evidence.md`, so a rule stays findable after its
> body is compacted out. **FORBIDDEN** = never do this again.
> **EXONERATED** = ruled out, stop re-investigating.

<!-- LEARNINGS-INDEX:END -->

---
## Entries before 2026-09-08 — moved to `learnings_archive.md` `[2026-08-20 cutoff on 2026-09-01; extended to 2026-09-01 on 2026-09-06; to 2026-09-08 on 2026-09-20]`

> **390 entries moved out of this file, VERBATIM and in full: 149 in the two
> passes of 2026-09-01 and 2026-09-06, and 241 more on 2026-09-20 when the
> cutoff went to 2026-09-08.**
> Nothing was deleted, summarised, or reworded.
>
> **They are still indexed.** `build_learnings_index.py` now spans
> `learnings.md`, `learnings_evidence.md` AND `learnings_archive.md`, so every
> archived rule remains findable in [`learnings_index.md`](learnings_index.md).
> A rule you cannot find is a rule you will break again.
>
> **THE COST, STATED: the session-start digest greps THIS FILE only, so its
> standing-rule count dropped 160 -> 125 on 2026-09-06 and 267 -> 116 on
> 2026-09-20.** Those rules are one file away, not gone — `learnings_archive.md`
> holds 301 FORBIDDEN/EXONERATED headings and every one of them is in
> `learnings_index.md` — but a session that greps only
> `learnings.md` will not see them. **Age is not expiry: a FORBIDDEN rule does
> not stop being true.** If one of these is bitten again, move it back.
## Compacted entries — moved to `learnings_evidence.md` `[2026-08-31]`

> **68 entries that were stubbed here now live ONLY in `learnings_evidence.md`,
> in FULL — heading, rule, and the whole working.** Nothing was deleted and
> nothing was summarised: every one of the 68 headings was verified present
> there before this section was replaced.
>
> **Find them in [`learnings_index.md`](learnings_index.md)**, which
> `build_learnings_index.py` generates across BOTH files — a rule stays indexed
> after its body moves, which is the property that makes this safe.
>
> **Why they left.** `learnings.md` is read at every session start against a
> 120,000 B cap. These were already rule-only stubs whose evidence had moved on
> 2026-08-15; keeping a second copy of the rule here cost 35,071 B and bought
> nothing the index does not already give. Four of them carry `FORBIDDEN` or
> `EXONERATED` in the heading, so the session-start digest's rule COUNT drops by
> 4; the six it displays are unchanged (they are the file-order tail, and this
> section sits 9% into the file).
## Superseded on 2026-08-15 — the two `same_book_n` entries

Both were merged into **"never read a joiner zero as a fact about the world"**
above; full original text is in `learnings_evidence.md`. They reappeared here
once after being removed — a stale-read write on this shared file resurrected
them alongside their own replacement. If they show up a third time, delete
them again rather than assuming the merge was reverted: the merged rule and
the evidence file are the source of truth.
## 2026-09-21 FORBIDDEN: diagnosing a failure from its most vivid example `[lane layer2-line-move-magnitude]`

I diagnosed 174 sign conflicts from ONE row -- `mlb spreads_alt away -1.5 ->
+0.5`, "+37.22 pp" -- quoted it in four commits, the findings file, the lane,
state.md and learnings.md, and wrote the retry prerequisite around it ("a side's
fair must be monotone in its line"). Then the check ran: that example was one
of **7 spreads in 174**; only **14%** of conflicts had a non-monotone curve at
all; **86%** had a correctly monotone curve. The prerequisite I had recorded as
"the first step, not an optional one" explained a minority of the failure.

**THE RULE.** Before a diagnosis enters the ledger, DECOMPOSE the whole
failure population into its candidate causes and report the share of each.
An example is evidence that a mechanism EXISTS, never that it DOMINATES. The
most extreme row is selected for being extreme, which makes it the least
representative row available.
## 2026-09-21 FORBIDDEN: verifying that a signal was COMPUTED as verifying that it is REAL `[lane layer2-line-move-magnitude]`

The 2026-09-20 deploy was recorded as VERIFIED on "1,063 rows now score a line
move that scored 0.0". That number counts rows that RECEIVED a line score. It
never asked whether the line had moved. Measured the next day on the live
board: **538 of 912 line-moved rows (59%) still had their opening line
published in the same build**, because the openings index collapses a bet's
simultaneously-published lines onto whichever was recorded first. Those rows
carried median `|component|` 0.975 against 0.352 -- **233 at the cap** -- so
the verified headline was mostly the gap between two different lines.

**THE RULE.** A verification must include one check that the population the
feature acts on IS the population it claims to act on -- here, "is the
opening line actually gone?" -- not only that the feature produced output.
Coverage going up is equally what a feature firing on the WRONG rows looks
like. Same family as `[feedback_presence_is_not_reachability]`, one level up:
the code was reached, the output was produced, and neither proved it was about
the right thing.
## 2026-09-21 FORBIDDEN: shipping a "by construction" guarantee without checking the property of the DATA it rests on `[lane layer2-line-move-magnitude]`

An argument can be valid and still false in production, because its PREMISES
are claims about data. Mine was valid: *a line move toward the pick must raise
the ORIGINAL bet's probability, so sign and magnitude cannot disagree.* I built
on it, deployed it, and the first board under it returned **174 conflicts in
342 scored rows (51%)**.

The premise nobody checked: that the board's ALTERNATE-LINE FAIRS ARE MUTUALLY
CONSISTENT. They are not. `mlb spreads_alt away -1.5 -> +0.5` (away getting
WEAKER) showed `away -1.5` gaining **37.22 probability points** — two
independently devigged alternate lines disagreeing. The logic was fine; its
input violated a property the logic silently required.

**It was checkable offline in one query** — within one build, is a side's fair
monotone in its line? — and I skipped it because the construction "proved" it
could not matter.

**THE RULE.** When a guarantee is derived rather than measured, list the
properties of the INPUT the derivation assumes, and measure each one on real
data BEFORE building. "By construction" is a statement about the code; it says
nothing about whether the data honours the code's assumptions.

**What contained the damage, and is the reusable half:** the instrument
(`movement_line_sign_conflict`) was built BEFORE deploying, to test the
argument rather than trust it. It cost one deploy to learn this. Without it the
magnitude ships as a quiet wrong signal in the ranking — indistinguishable from
a working feature at every level except the data, which is
`model_engine_standard.md`'s own thesis. Reverted in `f1fe4ee1`.


**CORRECTED THE SAME DAY — the rule stands, its worked example's CAUSE was wrong.** This
entry names "alternate-line fairs are not mutually consistent" as the unchecked premise.
Decomposing all 173 conflicts showed only **14%** had a non-monotone curve; **86%** were
correctly monotone. The real cause was the OPENINGS INDEX pairing different lines of one
bet, so the opening read at L0 was often not that bet's opening -- fixed and verified
(`line_moved` 913 -> 0, `deploys.md` 2026-09-21 14:41Z). The lesson is therefore doubly
true: the premise that failed was not even the one I named, and I named it from one vivid
row. See the entry below on diagnosing from the most vivid example.
## 2026-09-21 FORBIDDEN: rolling back by redeploying an ANCESTOR SHA `[lane layer2-line-move-magnitude]`

Render deploys a COMMIT, not a diff. Redeploying an ancestor of the live SHA is
a no-op that reports success — the live commit already contains it.

I tried to revert `d419cc24` by deploying its parent `96e17478`. Preflight
refused: *"96e17478 is already contained in live d419cc24 -- the deploy is
redundant."* Without that refusal the deploy would have gone green, changed
nothing, and left 174 sign conflicts live **behind a successful receipt** —
the most dangerous shape a failed rollback can take, because the receipt is
what the next reader trusts.

**THE RULE.** A rollback is a NEW commit (`git revert <sha>`), pushed, then
deployed like any other change and verified by the same measurement that
caught the defect. Then CHECK WHAT SURVIVED: `git revert` of one commit leaves
its neighbours, which is right, but confirm it — here `088f39fe` (the moneyline
waiver) had to be read back off the served board to be sure the revert had not
taken it too. Correct rollback: `f1fe4ee1`, conflicts **174 -> 0**.
## 2026-09-20 FORBIDDEN: reading a comment REPEATED across files as corroboration `[lane layer2-line-movement-scoring]`

A sentence copied into six places is **one claim with six copies**, not six
independent confirmations. Copies do not age independently either: when the
code moves, every copy is stale at once, and the count makes the stale claim
look better established the more it has spread.

I asserted *"`sweep_changed_hot_artifacts` does not run on refresh-worker"* on
the strength of *"its only production caller is `live_lens_loop`, on another
service"* appearing at `artifact_publisher.py:496` and `:561`,
`run_refresh_worker.py:1631` and `:3049`, `build_ncaaf_roster_snapshot.py:81`
and `refresh_ncaaf_player_game_stats.py:200`. Six sites. **The claim is stale:**
`artifact_publisher.py:1490` says the sweep has **FOUR** paths into it, names
them, and records an incident caused by believing otherwise -- *"a guard on one
of them is bypassed by the other three -- which is exactly what happened"*.
`run_refresh_worker.py:4380` spawns one of them.

**THE AGGRAVATING DETAIL: the contradicting line was in my own grep output.** I
ran `grep -rn sweep_changed_hot_artifacts`, `:1490` printed, and I read past it
because six agreeing lines had already settled the question. Repetition did not
just fail to help -- it actively suppressed the one line that mattered.

**AND I COMPOUNDED IT** by taking a peer's 75-minute window of
`publishedArtifacts 0` as "never", which is this file's own
absence-in-a-window rule, cited by me at two other people the same day.

**THE RULE.** A comment is a claim by one author at one time. Corroboration
comes from a DIFFERENT KIND of evidence -- the call graph, a runtime counter, a
log line -- never from the same sentence found again. Before resting a
structural claim on a comment: grep for the SYMBOL and read every hit,
especially the ones that disagree; prefer the site that ENUMERATES ("four paths
into it") over the site that ASSERTS ("the only caller"), because the enumerator
had to look.

Retracted within the hour, before anyone built on it: `c99bc013` corrected in
the lane.
## 2026-09-20 FORBIDDEN: quoting a RATIO next to an extreme value it was not computed from `[lane layer2-line-movement-scoring]`

Caught by a PEER session re-measuring rather than banking my reading, which is
the only reason it was caught at all.

I wrote: *"Every openings file since 2026-09-01 is over the cap, up to **31.1 MB**
on 09-19, against the allowlist comment's stated '~90 KB a day' -- **174x stale**."*

Both numbers are TRUE and they do not belong to each other. 174x is
15,691,334 / 90,000, which is **09-20's** file. The 31.1 MB sitting beside it is
**09-19's**, and its ratio is **345x**. A reader takes a multiplier as the
multiplier OF THE NUMBER NEXT TO IT -- that is what adjacency means in prose --
so the sentence asserts something false while containing no false number.

**THE RULE.** When a ratio and an absolute sit in one sentence they must be the
SAME OBSERVATION. If you want the peak's magnitude AND a typical ratio, that is
two sentences or two labelled pairs, never one clause. State the denominator AND
the date/row each figure came from.

**WHY 'a rate, not a count' DOES NOT COVER THIS.** That rule is about a MISSING
denominator. Here the denominator is present and correct; the defect is that the
NUMERATOR silently changed between the two halves of the sentence, so a check for
"did I divide by something" passes. The check that catches it: **point at the
exact row each number came from, and if two figures in one clause point at
different rows, split the clause.**

Corrected in place in `findings_2026-09-20_layer2_movement_scoring.md` rather
than silently patched, with the peer's independent reproduction beside it
(09-19 31,120,228; 09-20 15,736,057 -- 44,723 bytes above mine 40 min earlier,
which is the file still appending, not a disagreement). `c21312f7`.
## 2026-09-16 — a detector that matches a FORMULA at published precision has a FALSE-POSITIVE RATE, and mine fired at about 1 row per 1,200 `[session abacd435, lane soccer-anytime-scorer]`

- **The instrument.** `unconditional_ladder_share` decided whether a soccer shot row was priced on the OLD unconditional ladder by testing `ladder["0.5"] == round(1 - exp(-expected_shots), 4)`. It verified fix #2 on both workers.
- **What happened.** A 3-hour sentinel over 28 artifacts flagged one row with `expected_shots` > 0: Serge Gnabry, bundesliga, ladder 0.8653 against 1 - exp(-2.0046) = 0.8653. Read naively that is a deployed fix not applying to a row.
- **What was true.** He was on the new mixture path. His conditional mean was 2.5541, not the fallback's 2.9601, and no row in that artifact matched the fallback. A mixture's P(>= 1) is below the Poisson value at its own mean, so it can coincide with the Poisson value at a DIFFERENT (lower) mean. At 4 published decimals such a collision is expected roughly once per thousand rows.
- **How to apply.**
  - A formula-equality detector tests a VALUE, and values collide. Before reading a small nonzero share as a failure, check the mechanism's own signature instead — here, whether the conditional mean equals the fallback's `x / max(minutes, 0.25)`.
  - State a detector's false-positive rate when you record a reading that uses it, so the next person does not have to rediscover it from one alarming row.
  - Keep the denominator honest too: this one counted rows that CANNOT discriminate (zero-mean rows price 0.0 either way), which inflated the raw share to 15% in one league while the discriminating share was 0.
- *(evidence: `deploys.md` 2026-09-16 01:23Z sentinel sweep; bundesliga `recommendations_2026-09-18.json` gen 00:21:57Z)*
## 2026-09-16 — OVERTURNED: "the pre-registered criterion is the safe part, the risk is in the mechanism" — two hypotheses in one night died on the CRITERION `[session abacd435, fixes #4 and #5a; no lane]`

- **H20 condition (c)** compared the model's favourite price to **the market's**. On TEST, favourites the market priced at 70.7% actually won **78.5%** (n=158), so the arm that best matched OUTCOMES (k=2.0, at 0.801) is the one the criterion penalised hardest. It silently assumed the benchmark was calibrated on that sample.
- **H25 condition (b)** used the **pooled signed** bias. Per league, |bias| shrank in 8 of 10 and worsened in none, yet the pooled figure moved +0.106 -> +0.111: MLS (n=134, the largest league, over-predicting) improved from -0.41 to -0.19 and pushed the signed mean UP. H22 had already written that cancellation down -- the pooled bias barely moves because MLS runs the other way -- and I still wrote the criterion on the pooled number.
- Both verdicts stand as recorded (H20 INVALID and falsified; H25 FALSIFIED). Neither was re-interpreted after it failed, which is the point of writing them first.
- **How to apply.**
  - After drafting a criterion, ask what ELSE could move it. A pooled signed mean over heterogeneous groups is almost never the quantity a decision needs; a per-group magnitude plus a sign test usually is.
  - When the comparator is a market, say whether it is assumed calibrated on that sample. If it is not, closer-to-the-market is not better.
  - A criterion defect is free to fix before the run and total afterwards: each of these cost a compute run of about 2.5 h that no amount of re-reading can rescue.
- *(evidence: `log/2026-09-15.md` H20 entry `7171760b` and the H25 analysis; the analyzer's own degenerate `improved 0/9, p=0.004` line, which compares k*=1.0 against itself)*
## 2026-09-16 — FORBIDDEN: gating a backtest on a `matches_scored` baseline produced by a DIFFERENT code state. Pin a fresh reference at the commit the run uses `[session abacd435, fix #4]`

- H20's sanity gate compared per-league match counts to `reports/soccer_backtest/h2h_calibration_2026-08-15_limit120_n1112.json` and failed on four leagues: bundesliga 126 -> **71**, la_liga 123 -> 120, ligue_1 126 -> 120, serie_a 120 -> 121.
- **The run was right and the baseline was stale.** `skipped_thin_ratings` rose 3-5x in exactly the five Understat leagues (epl 202 -> 699, la_liga 202 -> 873, bundesliga 180 -> 847, serie_a 200 -> 613, ligue_1 180 -> 528) and is byte-identical in the four goals-based ones. The harness was corrected after that baseline to read ratings the way production does, branch for branch: the big five use Understat xG+ppda with `window=45` where the baseline used goals-as-xG with `window=90`, and a 45-day window admits far fewer teams to the 20-prior-matches test.
- **How to apply.** A stored baseline measures a CODE STATE, not a league. Record the commit beside any baseline a gate reads; when the harness has changed, generate a fresh reference arm at the running commit and say so BEFORE the run. Do not swap the gate after seeing it fail.
- *(evidence: `log/2026-09-15.md` H20 entry; `summary_k1.0.json` coverage against the baseline, compared per league at 00:48:51Z)*

### 2026-09-16 (session a1e40980, lane `soccer-live-scoreboard-range-stale`) — `write_json_file` writes keyvalue **OR** disk, NEVER both — so "also store it in the shared cache" is a MOVE, not an addition

Nearly shipped as an addition. The plan was to make the soccer poller ALSO write its per-league `live_state_<date>.json` through `refresh_state_store.write_json_file`, so the `read_json_file` already at the top of `_live_state_payload_uncached` would hit and the chips would stop waiting on a hot-artifact pull.

- `write_json_file` (`refresh_state_store.py:697`) takes the keyvalue branch and **returns** -- the `_atomic_write_text` below it is the `else`. On Render every soccer path is keyvalue-backed, so that call would have taken the file OFF live-odds-worker's disk, where `_finished_matches` reads it back, where the `HOT_ARTIFACT_PATTERNS` publish finds it, and where every other per-league reader looks.
- Worse in the failure mode: keyvalue writes are REFUSED above 8 MB and can fail transiently. A failed write leaves the PREVIOUS value in the store, and the reader prefers the store -- so a stale copy would silently SHADOW a correct disk file, with a 10-day TTL. That is strictly worse than the hop it was meant to fix. `delete_text_file`'s own docstring records the same shape from 2026-07-23.
- **How to apply:** before adding a `write_json_file` for an artifact anything reads from disk -- a publish sweep, a directory walk, a `Path.exists()` -- check `_keyvalue_backed(path)` for that path and read the BRANCH, not the function name. If it must live in both places that is two writes and a rule for which wins, not one call. Prefer an artifact ALREADY crossing services (here `live/soccer_live_lens.json`) over converting one that is not.
- *(evidence: `refresh_state_store.py:697` and `:868-898`; the abandoned design and its replacement, `.syndicate/log/2026-09-15.md` and commit `08f4c4a2`)*
## 2026-09-16 -- `lanes.md` ACCRUES IMPERATIVES THAT NOBODY RETIRES, and re-offering one costs the USER, not just me

In one session I surfaced an "open work" list built from `lanes.md` prose and got **three items wrong in the same way** -- each was an
imperative that had been satisfied elsewhere and never struck:

1. `book-quotes-prefer-fuller-copy`: "LANDED on main, NOT DEPLOYED" -- already live on all three services; the correcting verdict was in the
   SAME block. The user APPROVED a redundant deploy before an ancestry check caught it.
2. `heavy-build-child-process`: "DECISION OWED TO USER: flag off refresh-worker (a) vs off live-odds-worker (b)" -- **the user had already
   decided exactly that on 2026-09-14 ("Off on refresh-worker (Recommended)"), it shipped, and the same lane block already held the reading
   that GRADED it.** I asked them to decide it again, and they answered again.
3. Same lane: I reported (a) as available work while the block's newest status named a DIFFERENT owed decision.

The common shape: a lane block is APPEND-ONLY in practice. "OWED", "NOT DEPLOYED", "DECISION OWED" are written once and outlive their truth,
while the thing that retires them lands in `deploys.md`, in an env var, or in a later paragraph of the same block.

- **STANDING RULE: never offer an owed item without verifying it against the source that RETIRES it** -- deploy state from the service's live
  commit, env state from a single-key GET, a user decision from `deploys.md`. `lanes.md` proposes; it never confirms.
- **A settled item must be struck IN PLACE, not answered further down.** Appending the answer below the question leaves both true-looking, and
  the imperative is the half that reads like work.
- **Re-asking a decided question is not a cheap error.** It spends the user's attention on a choice they already made, and it invites them to
  contradict their own earlier reasoning without knowing they are doing so.
- Same family as the `state.md` rule "overwrite the stale line; do not stack contradictory lines" -- this is that failure in `lanes.md`.
- *(evidence: `SYNDICATE_ENABLE_LIVE_LENS_LOOP` single-key GET 2026-09-16 03:28Z -- refresh-worker OFF, live-odds-worker ON, web absent;
  `deploys.md` "User decision ~01:30Z"; `57b67127` an ancestor of all three live SHAs)*

### 2026-09-16 (session a1e40980, lane `web-export-timeout`) — FORBIDDEN: reporting a lane UNPROTECTED from a checking loop that re-queries a GENERATOR

I told the user, and wrote into commit `259691fc`'s message, that lane `book-quotes-splice-repair` was unprotected on three files because the claim parser read them as UNCLAIMED. **All three were claimed, before and after. The defect was in my check.**

- `lane_claims._claims(text)` returns a **generator**. My loop did `for f in files: holders = {lane for lane, path in claims if path == f}` against one `claims` object. The FIRST iteration drained it; every file after the first saw an empty iterable and reported `UNCLAIMED`.
- It was self-consistently wrong, which is why it passed review: ops.py (queried first) came back with a real holder, so the output looked like a working instrument that had found three genuinely unprotected files. The one true row made the three false ones credible.
- It survived a BEFORE/AFTER comparison too — I ran it against `origin/main` and against my edit and got the same three UNCLAIMED, and read that stability as confirmation. Both runs shared the bug, so the comparison could only ever agree with itself. A diff between two readings of the same broken instrument is not a control.
- **How to apply:** materialise before querying — `claims = list(_claims(text))` — and whenever a check reports something ABSENT, re-read one known-present case LAST rather than first. The ordering matters: a drained iterator always makes the earliest query look healthy. Before publishing "lane X is unprotected", "artifact Y is missing" or "nobody reads Z", re-run the check with the order reversed; if the answer moves, the instrument is the finding.
- Same family as *a rate, not a count* and *instrument blindness*: the reading was about my probe, not the population. The cost here was a false public statement about another session's lane, which is the kind of thing that gets someone's files taken out from under them.
- *(evidence: `list(_claims(...))` at `3169bdeb` returns `book-quotes-splice-repair` for all three files; the retraction is in `lanes.md` under lane `web-export-timeout`)*
## 2026-09-16 — FORBIDDEN: counting a log-search result without excluding the search tool's own echo of the pattern

`scripts/render_logs.py` prints a header naming what it searched for — the service name followed by `text=` and the pattern — so the obvious filter `[l for l in out.splitlines() if text in l]` **counts the query as a match**. Measured 2026-09-16 05:14Z, twice in one session: a verify script reported `1 wider-window refusal` on a service that had emitted none, and a spot check reported `1` ESPN refusal on refresh-worker over 60 minutes when the true count was `0`. I had already cited the first number in a session message as evidence that the fix was not over-greedy. **It is a floor of exactly 1 on every count, which is the worst possible magnitude: too small to look wrong, and it converts every zero into a one.**

The tell is cheap and should be habit: print the matched line's timestamp next to the count. The phantom's timestamp rendered as `#`.

**How to apply.** Filter to lines that ARE log lines — a `^\d{4}-\d{2}-\d{2}T` match — not merely lines containing the pattern. This generalises past this one tool: any wrapper that echoes its own query (grep with a banner, a paging tool that prints the window it covered) puts its parameters into the output stream it is filtering. Related: [[feedback_instrument_blindness]] — a healthy reading is evidence only once you know what makes it read unhealthy; here the unhealthy reading was unreachable, because the count could not go below 1.

### 2026-09-16 (session a1e40980, lane `web-export-timeout`) — FORBIDDEN: predicting a fix's effect from an inventory bucketed at a DIFFERENT boundary than the fix uses

I predicted `truncated: false` after deploying an 8 MB per-file cap, reasoning that the files which were not giant accumulators came to 11.1 MB against a 24 MB budget. Web answered `truncated: true` at 22.35 MB, and refresh-worker truncated at 77 files with **zero** files over the cap.

- The 11.1 MB was **files under 1 MB** — the bucket my inventory script happened to print. The fix's boundary was **8 MB**. Everything between 1 and 8 MB was in neither number, and it was enough to fill the budget on its own.
- The prediction was registered at preflight and graded wrong, which is the protocol working. What it cost was one confident sentence to the user ("truncation becomes rare") that the measurement then contradicted.
- **How to apply:** before predicting a threshold change, compute the population at the threshold the change actually uses — `sum(size for size in sizes if size <= CAP)` — not at whatever boundary an earlier report printed. If the only number to hand is bucketed elsewhere, say the prediction is unbounded rather than borrowing it.
- *(evidence: `deploys.md` 2026-09-16 04:01:38Z and 05:01:10Z)*
## 2026-09-16 -- A "NATURAL EXPERIMENT" IN WORKER MEMORY MUST BE CHECKED AGAINST THE DEPLOY TIMELINE FIRST

I reported a ~3x candidate-pool JSON->RSS multiplier, headlined by a "full cache flush" of 183.2 -> 0 MB that returned 525.5 MB of RSS, and
the user approved a production deploy sized on it. **The flush was a restart.** refresh-worker redeployed at 00:36:13Z, inside that
interval; the two other intervals showing RSS falling with the cache also each contained a deploy. The one restart-free drop gave 0.63.

- **STANDING RULE: before reading any interval of a worker's memory as cause and effect, list that service's deploys AND events for the
  window** (`/v1/services/<id>/deploys`, `/events`) and discard every interval that contains one. A restart moves the cache and RSS together,
  which is precisely the signature of the effect being hunted.
- **I applied `worker memory is boot-confounded` correctly to the AFTER reading and missed it in the BEFORE measurement the same night.** The
  rule is not "distrust post-deploy numbers"; it is "no interval containing a boot is evidence", wherever the interval sits.
- **Several busy lanes deploy one worker in an evening** (five refresh-worker deploys in 7 h here). On such a night the restart-free
  population is small; say so and report n, rather than widening the window until a pattern appears.
- Same family as *retraction is not innocence* and *gate on the output*: a clean-looking ratio from a confounded interval is worse than none,
  because it gets acted on.
- *(evidence: refresh-worker deploys finishedAt 22:12:03Z / 23:33:30Z / 00:36:13Z / 04:17:12Z / 05:06:56Z; `deploys.md` 2026-09-16 03:50Z and
  its retraction 14:10Z)*
## 2026-09-16 — FORBIDDEN: treating a clean `land` or a silent lane-guard as proof that a SCRIPT write respected another lane's file claim

Measured 2026-09-16 ~05:30Z, session abacd435. `docs/ai_context/todo.md` is claimed by OPEN, owned lane `kalshi-shard-balance-gate`. On 2026-09-15 lane-guard correctly REFUSED my `#664` entry for exactly that reason. On 2026-09-16 I wrote `#665` into the same file through a Python script: **lane-guard did not see it, and `session_worktree.py land` printed `ledger/lanes clean` and `ledger/todo ids clean` and pushed it.** Neither check compares the committed diff against other lanes' `Files:` claims. I found the claim only afterwards, by running the `#71` check.

This is the lane-claim twin of the deploy guard missing Python deploys: **a guard that hooks a TOOL is blind to the same effect produced by a script**, and a later check that reports "clean" was never looking at claims. The breach was small (8 added lines, 0 deletions), which is why it matters as a rule: small, additive, conflict-free writes are exactly the ones nobody re-examines.

**How to apply.** Before any script write to a path outside `.syndicate/` — and `todo.md` counts, it is claimed often — run `py -3 scripts/check_lane_claims.py` or grep `lanes.md` on `origin/main` for the path and read the holder's status. If an OPEN lane claims it, stop and surface, as the protocol says; the absence of a refusal is not permission.
## 2026-09-16 — FORBIDDEN: a duplicate detector whose grouping key is a field the defect writes. It reads 0 in both states. `[lane layer2-chip-rail-duplicate]`

The Games rail seated SEV @ DEP twice because `deriveGameCards` took each game's join keys from its FIRST row, and that row had none. The production replay already carried two duplicate detectors. Both read **0 on the broken template**: detector 1 groups cards by the chip they resolve (the duplicate's chip-less card resolves none), and detector 2 groups by the card's matchup text (first-row text, `SEV @ DEP` vs the chip card's `SEV @ Deportiv`). The second is the same instrument failure the script's own comment warned about for the first, one field over. Only a detector anchored on the ROWS (a chip-seeded card whose game has keyed board rows) read 1 -> 0.

**How to apply.** Before trusting a "0 duplicates" reading, name the field each detector groups on and check it is not produced by the code under test; then run it on the pre-change code and require it to read non-zero. The same session's two watchers failed the same way: one grepped `server_failed` and matched the tool's `# CLEAN no server_failed` footer, and one gated on a TOTAL row count and printed `RECOVERED` while soccer kept falling.
## 2026-09-16 — FORBIDDEN (user decision): blocking a whole SPORT or MARKET FAMILY from staking

**Every play is its own entity.** The user, 2026-09-16 ~10:25 CT, verbatim: "we shouldnt block anything globally - that includes MLB player props.  every prop and game line is its own entity in the scheme of things - we optimize overall but there's ALWAYS a chance an individual play is viable based on EV, sim edge, etc".

It came up when a session proposed adding `soccer:game_line,soccer:game_total` to `SYNDICATE_PORTFOLIO_EXCLUDED_FAMILIES` after measuring live soccer 1X2 at 0-7 (-$29.03) and an audit showing soccer 1X2 and O/U 2.5 losing to the close. The user rejected the category block AND the existing `mlb:player_prop` default it would have extended (lane `portfolio-no-family-exclusion` removes that mechanism).

**How to apply.** A measured loss in a market family is evidence for a PER-PLAY criterion (a stricter EV or sim-edge bar, a precision gate, a calibration fix), not for switching the family off. Do not propose, add, or re-enable a `sport:family` or sport-wide staking exclusion. Where an existing gate is category-shaped (for example a sport allowlist), surface it to the user as a decision; do not remove or extend it on inference.

### 2026-09-16 (session a1e40980, lane `web-export-timeout`) — FORBIDDEN: passing an epoch-float boundary through fixed-precision formatting into a STRICT comparison

A float timestamp formatted to six decimals looks precise enough for a `>=` boundary. It is not: rounding moves the value up as often as down, and a strict `mtime < since` then excludes exactly the file the boundary names.

- Measured on production 2026-09-16 14:36Z. A verification chain followed the export's `next_since` cursor with `f"{since:.6f}"` and LOST 2 OF 6 FILES. The two cursors that rounded UP past their file's true mtime (`1789565893.2385237 -> .238524`, `1789568946.8659189 -> .865919`) were exactly the two skipped; the two that rounded down were not. Re-run with `str(float)`: 6 of 6.
- **It read as the fix failing.** The skip was produced by my PROBE, while the production client — which writes the exact repr — was fine. A verification instrument that rounds can manufacture the very defect it is checking for.
- **How to apply:** carry epoch floats as `repr()` / `str()`, never `:.Nf`, whenever they cross a boundary comparison. On the receiving side, compare with a tolerance sized to the coarsest rounding a caller might apply (`12cbe434` uses 1 ms), so a rounded cursor RE-SENDS rather than SKIPS. When a boundary read comes back short, check each boundary value's rounding direction before concluding the code is wrong.
- *(evidence: `deploys.md` 2026-09-16 14:32:33Z and 14:56:00Z; `tests/test_artifact_export_oversize.py::ArtifactExportRoundedCursorTests`)*

### 2026-09-16 (session 30234b9d, lane `wnba-future-date-cache-carry`) — FORBIDDEN: running reproduction variants in one process through a builder with a process-local cache

A reproduction script ran three data-root variants back to back through `build_live_state_payload`. All three read 0 games, which would have FALSIFIED a true hypothesis.

- The builder wraps `_build_cards_page_context_uncached` in `_BUILD_CARDS_PAGE_CONTEXT_CACHE` (12 s TTL, keyed on date and flags, not on the data). The first variant's empty context answered the next two. The tell was in hand: the uncached builder was never entered for variants 2 and 3.
- With the cache cleared per run, the only-real-slates variant returned the four phantom games. The same call made directly on `_build_cards_page_context_uncached` had shown 4 all along.
- **How to apply:** before comparing variants in one interpreter, list every module-level cache on the path (`*_CACHE`, `lru_cache`, `.cache_clear`) and clear each per run. Confirm the branch ran for EVERY variant (a stage marker or a call log), not only the first. A null from a cached path is instrument silence, and `learnings.md` already requires a live population behind a null.

### 2026-09-16 (session 30234b9d, lane `wnba-future-date-cache-carry`) — OVERTURNED: "the Goal's named readings cover the seed"

The 09-16 reading passed all three criteria the Goal named (0 WNBA chips, Layer 2 `no_slate`, no `dashboard_games=4` line), while the Goal's own core clause, "seeds NO prior-slate games under that day's `live_state` key", FAILED: the key held 4 phantom FINALs.

- The named readings were CONSUMERS that filter (the chips reader drops the rows) and ONE emitter of ONE seed path. The key itself, the only reading that discriminates between seeds, was not in the list; the scheduled task read it only as an extra step.
- **How to apply:** when a Goal says "X is not written", its verification must read X (the stored artifact or key) directly, alongside any downstream surface. A clean consumer or a silent log line from a known writer does not exclude an unknown writer.
- *(evidence: `deploys.md` 2026-09-16 14:14Z; the seed was a future-date build at 04:31:02Z, fixed in `02684624`)*
## 2026-09-16 — FORBIDDEN: gating anything on a substring of `render_logs.py` output without `--width`

`scripts/render_logs.py` truncates every message to 200 characters by default (`--width 200`). A worker's `ALL_PROCESS_MEMORY` line is ~3,900 characters and its process list sits past character 200. Measured 2026-09-16 16:47Z, session abacd435: a watcher waiting for refresh-worker's MLB daily sim to finish (so a deploy would not kill it) read the 16:44:35Z sample, found neither `run_mlb_daily_sim_job` nor `daily_update.py`, and exited "done" — on the SAME sample `deploy_preflight.py` had just used to return `HOLD: 5 job(s) in flight`. Re-read with `--width 200000`: 3,895 chars, both tokens present. Nothing was deployed on the false signal, only because the watcher's output was checked before acting.

This is the second instrument defect in this one tool today (see the header-echo rule above): **one inflates every count by 1, the other hides every token past column 200.** Both make a watcher report the state you are waiting for.

**How to apply.** Pass `--width 200000` whenever a decision depends on WHAT a line contains, and prove the watcher reads the unhealthy state on a sample known to be unhealthy before trusting its all-clear. `deploy_preflight.py` itself reads the Render logs API untruncated, so it remains the authority on in-flight jobs.
## 2026-09-16 — FORBIDDEN: opening a source file for write before its new content is fully built. A raise between `open(p, 'wb')` and `write` leaves the file EMPTY, with no error pointing at the file. `[lane soccer-board-tomorrow-shortlist-collapse]`

A splice script did `open(p,'wb').write(nl.join(lines))`. `nl` was bytes and `lines` str, so `join` raised, but only AFTER `open` had truncated `pipeline/layer2_shortlist.py`: 2,363 lines to 0. The traceback named the type error, not the file. It was caught only because the next command printed `git diff --numstat` (`0 2363`). Had the next step been a test run, it would have failed on an import and looked like a code bug.

**How to apply.** Build the bytes first, then open: `data = ...; with open(p, 'wb') as f: f.write(data)`. For code, prefer the Edit tool, which never truncates on failure. After any scripted write to a tracked file, read `git diff --numstat` before doing anything else, and treat a deletion count near the file's length as an emptied file.
## 2026-09-16 — FORBIDDEN: attributing a portfolio plan's output change to a deploy without reading the plan's own `settings` block. Settings are written through an API with no deploy, and they bind before code does. `[lane soccer-board-tomorrow-shortlist-collapse]`

I recorded the plan's `sized` 25 -> 99 as "the portfolio change plus the recovered rows" because a deploy carrying both had just gone live. The cause was a `POST /portfolio/settings` 16 minutes earlier (`max_positions` 25 -> 150, exposure 0.251 -> 0.35). The evidence was in the payload I had already fetched: `settings.max_positions` with `sources: stored`, and the earlier post-deploy plan still sizing exactly 25 with `beyond_max_positions` 79 -- a cap binding, not rows missing. Corrected by the owning lane, re-derived, `deploys.md` 17:06Z.

**How to apply.** Before attributing any plan change, read `settings` (values AND sources) and the binding refusal (`beyond_max_positions`, the exposure scale) on the plans either side. If a cap was the binding refusal before, a settings change is the first suspect, not the deploy.
## 2026-09-16 — FORBIDDEN: changing a staking-policy env value without running the gating input checklist WITH that value

Measured 2026-09-16, session abacd435, lane `portfolio-no-family-exclusion`. Setting `SYNDICATE_PORTFOLIO_MARKET_FAIR_SPORTS` to every sport (a user-approved policy change: EV-only staking in all sports) made `scripts/portfolio_commit_input_checklist.py` FAIL on every commit — its canonical MLB row stripped of `model_edge_pct` must be refused `no_model_edge_pct`, and with `mlb` allowlisted it was sized instead — and `intelligence_state` SKIPS the whole commit on a checklist failure. Result: **no portfolio plan for any sport from ~17:45Z until an env revert**, and nothing in the deploy's own verify legs could fire, because they all waited on a plan.

The change had tests, all green: the code tests pinned the allowlist's behaviour, and the checklist test covered the feature OFF only. **An env value is a code path.** The deploy's pre-registered legs were about the effect of the change; none was about whether the commit still RAN.

**How to apply.** (1) Before any env change that alters what the commit accepts, run the gating checklist in-process with that env set (`SYNDICATE_PORTFOLIO_MARKET_FAIR_SPORTS=<value> py -3 scripts/portfolio_commit_input_checklist.py`, or the pytest that drives it) and require exit 0. (2) Every portfolio deploy's verify must include a liveness leg: a commit after go-live that is NOT `PORTFOLIO_COMMIT_SKIPPED`. (3) A verifier waiting for a post-deploy artifact must also watch for the SKIP/FAIL line that means the artifact will never come; "no population yet" for 2x the usual cadence is itself a reading.

### 2026-09-16 (session a1e40980, lane `web-export-timeout`) — FORBIDDEN: grading a watermark-ADVANCED prediction on the next request's `since` when a window clamp can produce the same advance

**What I believed.** Twice today the lane recorded that the 2 h pull-window clamp "should never bite" at a 48 MB budget. And I pre-registered a deploy prediction, "tomorrow's floor advances past 17:48:19Z", to be read from the `since=` of the next tomorrow request.

**What was true.**
- The clamp BIT on the very first tomorrow pull after the deploy: `20:35:20Z PULL_WINDOW_CLAMPED scope=2026-09-17 skipped_seconds=2821.9`. Timeouts had frozen the floor, and tomorrow pulls are rare (none 18:33Z -> 20:35Z). "Truncation is rare" never bounded it: the gap between pulls does, and a failing pull freezes the floor meanwhile.
- That request's `since=18:35:20Z` was PAST 17:48:19Z, so the prediction read MET. The clamp did it, and a 30 s client would have produced the identical advance. The discriminating reading came 43 min later: the NEXT tomorrow request carried `since` = the prior successful pull's own start (`1789590920.878161`), with no clamp line.

**How to apply.**
- A watermark "advanced" prediction must name the value only the fix can write (a successful pull's own start, a returned cursor), not a direction. Check for `PULL_WINDOW_CLAMPED` in the same window before crediting any advance.
- A time-window clamp's exposure is the longest GAP between successful pulls of a scope, not the truncation rate. Read that gap before calling it harmless.
- *(evidence: `deploys.md` 2026-09-16 20:47Z, 20:58Z, 21:28Z)*
## 2026-09-16 — FORBIDDEN: pinning a PUBLISHED claim with a test that reads the configuration it depends on implicitly

Measured 2026-09-16, session abacd435, lane `sim-view-reachability-caveat`. `/api/ops/execution/ledger-summary` told readers that four sim-verdict buckets are "structurally empty and stay empty". Production's paper ledger held 324 orders in them. The sentence had been false since 2026-09-04, when `SYNDICATE_PORTFOLIO_MARKET_FAIR_SPORTS` first named a sport. Two tests existed specifically to keep it true ("so the payload cannot keep asserting a structural fact after the structure changes"). Both called the commit gate with the env read implicitly. CI leaves it absent, so they stayed green for 12 days. With production's value, both failed.

Same root as the rule above (an env value is a code path), in a different place: there it broke a gate, here it let an instrument lie.

**How to apply.** A test whose assertion depends on a setting must set that setting explicitly with `monkeypatch`, in every state production can hold, and assert the outcome in each. If a claim is true only under one configuration, it is not structural. Publish what holds in any configuration (here: "no model edge, so sized on market fair") instead of what holds in CI.
## 2026-09-17 - FORBIDDEN: predicting which DEPLOY will fix a served value before tracing which DATA COPY the serving service builds it from `[lane soccer-postponed-served-final]`

**What happened.** The postponed ATH @ LEV chip read `0-0 FINAL`. I recommended deploying refresh-worker "to fix the chip", then said the fix was waiting on a live-odds-worker rebuild. Both predictions were about code. Data decided it: a 21:37Z artifact built by old code and copied to refresh-worker. The chip cleared when the corrected artifact reached refresh-worker (23:00Z, still on OLD code), and it came BACK after refresh-worker restarted onto the FIXED code (00:05Z), while web on the same fixed code served it correctly. The rebuild-cadence prediction (4 h, so ~01:37Z) was also wrong: it ran at 22:43Z.

**Rule.** Before naming a deploy as the fix for a served value, read the value's input on the service that builds it and compare it with the same input on another service. Identical code with divergent output (here web vs refresh-worker) puts the defect in the data copy. Do not predict a periodic job's next run from its configured interval; read its last run.
## 2026-09-17 — FORBIDDEN: diagnosing from an AGGREGATE timestamp without naming which input set it — and correcting a claim on weaker evidence than the claim had `[lane heavy-build-memory-refusal]`

**What happened.** Asked why the combined Layer 2 board showed "last refresh an hour ago", I read `state_last_updated` (22:03:10Z, 61 min old) and traced it to memory-guard refusals -- without knowing that field is the OLDEST of several dated inputs. Later, finding that out, I pushed a correction saying today's staleness was UNKNOWN. A third read showed the oldest input was in fact TODAY's shortlist, and the 22:03Z stamp matched `LAYER2_SHORTLIST date=2026-09-16` exactly. The first diagnosis was right; the correction was wrong, and both were pushed to the ledger.

**Rule.** Before diagnosing from a timestamp served by an aggregate (combined board, window, multi-date or multi-sport payload), read its definition AND the per-input stamps in the same read, and name which input sets it. A correction is a claim: it needs its own measurement at the same bar, not just a reason the first claim might be wrong.

**Evidence.** `pipeline/intelligence_state.py` combined-window freshness block (`computed_at` = oldest dated input); reads of `/api/intelligence/query` `state_meta` and `/api/board/layer2-shortlist?date=` at 00:45Z and 00:58Z 2026-09-17; ledger commits 7dda4e0a (over-correction), 1b58575e (refined); `deploys.md` 2026-09-17 00:00:56Z entry.

### 2026-09-17 (session a1e40980, lane `soccer-postponed-served-final`) — FORBIDDEN: blaming a stale DATA COPY for a value that flips exactly at a RESTART without first looking for a process-lifetime cache on its reader

**What was believed.** refresh-worker's chip for postponed ATH @ LEV went `pregame` -> `final 0-0` on the first publish after a restart. The lane recorded "the defect is refresh-worker's DATA COPY", named the recommendations file as the likely stale input, and predicted which file it was.

**What was true.**
- The recommendations copy was clean before AND after the restart: refresh-worker re-published its own at the clean 171,140 B (the old-code build was 234,306 B) at 00:29:40Z, and the chip stayed `final` even after refresh-worker rebuilt it at 01:06Z.
- The match had left recommendations, so it was carded from the SCHEDULE artifact through a second path (`_unsimulated_game`) with no unplayed guard. refresh-worker's schedule was an old-code build (21:51Z) that is never re-pulled (no date in its name). `schedule_payload` was `@lru_cache` for the process's life, so the OLD process kept serving a pre-postponement read, and the restart is what surfaced the stale disk copy.
- **A restart is not a neutral event for a reader with a process-lifetime cache.** It changes the answer without any file changing, so "it flipped at the deploy" pointed at the cache, not at the deploy's code or at a data copy being written.

**How to apply.**
- When a served value changes exactly at a restart, grep the read path for `@lru_cache` / module-level memos BEFORE naming a stale file, and list every card path that can build the value (here two: recommendations and schedule).
- Discriminate unreadable worker disks with what crosses the boundary: web's `[ops.publish] ACCEPTED ... publisher= bytes= delta=` log gave each service's copy size and build time.
- An artifact with no date in its name is outside the dated pull. A service that built it on old code keeps that copy until it rebuilds it.
- *(evidence: `deploys.md` 2026-09-17 00:39Z and 01:25Z; commit `bea2a355`)*
## 2026-09-17 — FORBIDDEN: pre-registering a forward test without measuring that its qualifying population can exist, or a threshold without measuring its ceiling

Measured 2026-09-17, session abacd435. Two registrations were written as binding and would have graded nothing:
- **H24 (`#665`)** required "a production recommendations artifact built BEFORE kickoff". 43 of 43 matches sat in artifacts generated AFTER kickoff, because the builder rewrites one file per league-date through the match. The population was zero forever. Nobody could have found out before grading day (2026-10-15).
- **H26 (corners)** set r(total) >= 0.20. The corners market's own implied mean reaches r 0.155 on the same matches, so the bar sat above what any pregame number can know, and a market-parity estimator (r 0.182) "failed".

**How to apply.** Before a forward registration is binding:
1. Read production for the qualifying artifact AS THE RULE WORDS IT (here: `generated_at` vs `kickoff` per match) and count how many recent units would have qualified. Zero means the rule is broken, not the model.
2. Put the best available reference (the market's own accuracy on the same units) beside any absolute threshold, and set the bar relative to it.
A registration is a promise about a measurement that will exist; check that it can.
## 2026-09-17 — FORBIDDEN: running `git worktree prune` from a session

Measured 2026-09-17 ~11:4xZ, session abacd435. While removing its own temporary worktree, it ran `git worktree prune`. prune is REPO-GLOBAL: it tried to delete 8 other sessions' worktree records (`.git/worktrees/*`). Every attempt failed with "Permission denied", so nothing was lost. It still acted on work this session did not own.

**How to apply.** Remove only your own worktree (`git worktree remove <path>`). If a directory is left behind, delete that directory and check `git worktree list` for your path alone. Never prune.

### 2026-09-17 (session a1e40980) — FORBIDDEN: running a ledger-wide cleanup tool without first reading the rules of the lane that owns that cleanup

**What happened.** The user approved "Apply all 15" after a dry run of `scripts/archive_released_lanes.py` showed 15 claim-free CLOSED lane blocks, "claims unchanged". Applied (`bac96455`). But a scheduled lane that owns archiving (`closed-lane-archive-0917b`, earlier the same day) had documented three rules the tool does not enforce: move a closed lane only when its owner session has been idle >= 240 min; never move five named lanes (including `heavy-build-child-process`, which was moved); and put bodies in `lanes_closed.md` with a one-line pointer (the tool wrote `lanes_history.md`, no pointer). 11 of the 15 belonged to sessions active at that moment.

**The dry run was not the check.** It verified what the TOOL verifies -- claims and OPEN headers -- and was silent on policy that lived only in another lane's verdict and today's log. The user's approval was given on that incomplete picture, because I presented it that way.

**How to apply.**
- Before any bulk ledger move, grep today's and yesterday's log and `lanes_history.md` for a lane that owns that kind of cleanup (`archive`, `trim`, `never-archive`) and read its rules; put them in the approval question.
- Owner-idle is not optional: an owner editing its own block during a move either fails to find it or re-creates it.
- Undoing a landed archive trips `ledger-commit-guard` (restored blocks read as un-archiving); the override needs the user's explicit approval for that commit.
- *(evidence: `bac96455`, revert `1a309584`, `4ef3bff8`; `log/2026-09-17.md` ~11:02 CDT and this session's entry)*

### 2026-09-17 (session 4a583d41, lane prop-evidence-parity) — FORBIDDEN: a cap, filter or truncation that drops output without saying what it dropped

**What happened.** `MAX_TABLES = 8` in Ask's evidence merge. A production MLB
prop answer (Nolan McLean, earned runs, read 18:0xZ) BUILT nine tables and
SERVED eight — the park/weather table fell off the end, and nothing in the
payload, the panel or the logs said a table had been dropped. The ledger's own
record of that surface ("MLB prop unchanged at 8 + 3") had been reading the CAP
as if it were the answer's natural size for a month.

**Why it survived.** A truncation looks exactly like an absence from outside:
both render as "that table is not here". The cap was set when the answer had
fewer sections, and every later section quietly competed for the same eight
slots. Nothing failed, so nothing was investigated.

**How to apply.**
- A cap must report its own bite: carry the built and served counts on the
  payload (`prop_evidence.tables_built` / `tables_served` is the instance), or
  log when they differ. "Fits in the budget" is not the same claim as "is all
  there was".
- When you raise a cap, re-read what appears — the newly visible item is
  evidence about what the cap was hiding, and it may be the most useful one.
- The same shape applies to any `[:N]`, `head`, `LIMIT` or sample in a path
  whose output someone reads as a complete set.
- *(evidence: production Ask captures 2026-09-17 18:0x-18:2xZ, `log/2026-09-17.md`; fix in `fdea0a2e`)*

### 2026-09-17 (session 4a583d41, lane prop-evidence-parity) — FORBIDDEN: reading a field name out of a TEST FIXTURE and calling it the producer's contract

**What happened.** Ask read `player["minutes"]` from the basketball sim's
`cards_sim_detail`. The production engine writes **`min_mean`**; `minutes`
exists only on a fallback stub. So the player Minutes row never rendered on real
data and the team table printed `0` minutes for every player — for months, with
a green test, because `tests/test_ask_the_syndicate.py`'s fixture was written
with the reader's key rather than the writer's.

**The tell nobody looked at.** `or 0` in the formatter turned a missing key into
a plausible number. A neutral default makes an unfed field indistinguishable
from a working one — `model_engine_standard.md` says exactly this about sim
inputs, and it applies to READERS as well as engines.

**How to apply.**
- Verify a key against the WRITER (the producer's `player_dict[...] = ...`), or
  against a real artifact, never against a fixture you or a peer wrote.
- Slice test fixtures out of production files. The fixtures for this work are
  cut from the real `cards_sim_detail`, `smart_sim_*`, `props_recommendations`
  and box-score files, and the WNBA test asserts `"minutes" not in player` so
  the stub key cannot come back.
- Never let a formatter substitute `0` for absent. `—` is the honest cell.
- *(evidence: `state_basketball.md` measured `min_mean 38.37` for Bueckers; fix + test in `fdea0a2e`)*
## 2026-09-17 — A CACHE TTL READ FROM THE CODE IS NOT THE LIVE TTL, and the live one decides how long a served timestamp may lag. `[lane board-today-freshness]`
- **The belief overturned:** `read_combined_intelligence_response`'s own comments discuss the combined-board cache as the 15 s default (`SYNDICATE_INTELLIGENCE_COMBINED_BOARD_CACHE_SECONDS`, `max(1.0, ...15)`), and `#632`'s comment reasons from "the TTL defaults to 15 s while the rebuild costs 5-18 s". I designed against that number.
- **What was actually true:** web sets the key to **180 s** (single-key env read, 2026-09-17 ~17:59Z), and `_COMBINED_BOARD_STALE_TTL_MULTIPLE` serves a stale entry for up to 10x that during a rebuild. So a stamp in the served payload can be up to 180 s behind the artifact route, and up to 1,800 s in the worst case.
- **How we found out:** a post-deploy reading. At 17:57:42Z `/api/board/layer2-shortlist?date=2026-09-17` said `written_at` 17:56:42Z while the combined board served 17:25:57Z for the same date — which formally triggered that lane's falsification test. The payload named its own cause: `age_seconds` and `newest_age_seconds` both back-computed to a build at 17:56:37Z, 5 s BEFORE the newer shortlist existed. A read after expiry agreed exactly.
- **The rule going forward:**
  - Before designing or verifying anything whose correctness depends on a cache window, READ THE KEY ON THE SERVICE. A code default is the value for a service that does not set it, which is not evidence about the one you are measuring. Same discipline as `feedback_which_service_runs_the_code`: config moves with no diff.
  - **A caching layer is a second clock.** Any "the payload disagrees with the artifact" verdict must first ask how old the payload's own build is, from a field the payload already carries. This one was answerable with no extra request.
  - The cache is PER WORKER (module-level dict, `WEB_CONCURRENCY=2`), so same-instant reads can land on entries of different ages, and a recycle forces a cold rebuild. State the worker, or the comparison is unattributable.
- **Cost:** none to the fix (the design had already refused to serve any cached clock-relative verdict, which is why the mismatch was a stamp lag and not a wrong freshness verdict). Cost was one confusing reading and the work to attribute it.
## 2026-09-17 (session 1628e558, lane `web-memory-guard`) — OVERTURNED, my own hypothesis: "cap glibc arenas on web and per-worker anon comes down". THE LEVER MOVED ITS OWN INSTRUMENT AND NOT THE OUTCOME

Web workers had never had `#285`'s arena cap (`configure_malloc_arenas` is called only by the two worker entrypoints), and the 2026-09-06 lanes had measured a ~390 MB arena ceiling per worker with ~87% free-but-retained. Capping arenas at 2 in gunicorn's `post_fork` did exactly what it says: `arena_count` **13 -> 2** on every worker, `secondary_arena_mb` **371.2 -> 0.8-189.4**, both read straight off `/api/ops/memory`. The pre-registered OUTCOME criterion still failed: anon at 876 requests was **723.3 MB, 12.6% below** the 827.9 MB baseline against a 15% bar, and another worker reached **748.7 MB at 273 requests**. Growth is uneven (0.24-3.28 MB/request across workers) and anon sometimes FALLS without a restart, which the pre-cap process never did.

- **A fix that moves the instrument it targets has not thereby moved the thing you care about.** Name the outcome number before the deploy, or the instrument's improvement becomes the verdict by default.
- **A mitigation shipped in the same deploy can destroy the comparison you pre-registered.** The recycle guard truncates worker lifetimes, so no post-deploy worker reaches the 1,010-request point the baseline was taken at: the criterion became partly unmeasurable BY CONSTRUCTION. If a guard and a hypothesis ship together, write the hypothesis's criterion in units the guard cannot cut off (per-request, per-100-requests), not "at request N".
- **Report it as FAILED-AS-WRITTEN, not as "no effect" and not as a null.** The retained bytes did fall; the growth did not stop. Both halves are the finding.
## 2026-09-17 (session 1628e558, lane `web-memory-guard`) — FORBIDDEN: bounding a process's memory with a check that runs BETWEEN units of work, then sizing the limit at the target

`post_request` recycles a gunicorn worker when `RssAnon` crosses its limit, so it can only ever see memory BETWEEN requests. Measured on the first three production recycles: pid 41 crossed at 666.7 MB against a 666.0 limit (7 MB of overshoot, which the 5-request check interval explains at ~1.3 MB/request), but pid 40 crossed at **723.2 against 678.4 -- 44.8 MB over**, and a later worker read **748.7 MB, ~72 MB over**. One request allocates tens of MB (the combined-board rebuild reads two ~5.2 MB artifacts and materialises ~9,334 dicts in a single request, no streaming), and no check frequency catches an allocation that happens inside the request it is waiting for.

- **Size the limit for the largest single unit of work, not for the ceiling you want.** 2 x (650 + ~100) fits 2,048 MB with the master and two merge children; 2 x 700 plus a 72 MB overshoot does not leave that room.
- **Checking more often is the tempting fix and it is the wrong one** — it would have bought ~7 MB of the 45.
- Corollary for the instrument: `growth_episodes` in `/api/ops/memory` RE-BASELINES ON EVERY READ (`baseline_age_s` ~6 s), so `episodes_captured=0` and `max_anon_rise_seen_mb=0.0` are what it prints while a worker grows 500 MB between two reads. A zero from an instrument that resets itself is not a measurement of zero.

### 2026-09-17 (session 4a583d41, lane prop-evidence-parity) â FORBIDDEN: treating your own commit on `main` as inert because YOU have not deployed it

**What happened.** Two web commits sat on `origin/main` while this lane waited for deploy
approval, and I described them to the user as "landed, not deployed" as though that were a
stable state. A peer lane (`a1e40980`) pointed out what it actually is: **the next web deploy
by ANY lane ships them.** That queue was three lanes deep at the time â my two plus
web-memory-guard's per-worker memory limit change â and no lane's expectation covered another
lane's change.

**Why `autoDeploy = no` does not save you.** It stops a PUSH from deploying. It does nothing
about the next deploy someone else triggers, which carries every commit merged since the live
SHA. "Nothing is deployed" is true of the service, never of your code's future.

**How to apply.**
- The moment code lands unshipped, write a RIDE-ALONG VERDICT in the lane block: is it safe
  for someone else's deploy to carry this unmeasured, and what is the blast radius if it does.
  Back it with a measurement, not a feeling (here: 0.14-0.27 s per answer, <16 MB transient,
  ~6 KB payload, one visible behaviour change).
- The verification is still OWED BY YOUR LANE when a ride-along ships it. A ride-along moves
  code; it does not take the reading, and a deploy receipt written by another lane will not
  mention your predicate.
- Before deploying, re-read what has accumulated: `origin/main` moved 18 commits under this
  lane in about two hours.
- *(evidence: `log/2026-09-17.md` ~20:55Z; verdict landed in `46e86b03`)*
## 2026-09-17 (session 1628e558, lanes model-scorecard-cron / web-memory-guard) — `session_worktree.py close` REFUSES A CHERRY-PICKED BRANCH FOREVER, AND ITS "N commit(s) not on origin/main" IS AN ANCESTRY CLAIM, NOT A CONTENT ONE

Seven worktrees, all clean, every commit's content on `origin/main`. `close` accepted two (the lane branches, which had been rebased by `land`) and refused five with *"1 commit(s) not on origin/main -- Land them, or pass --force to discard. Nothing here is recoverable from another session"*. Those five were BUILDER branches whose commits I cherry-picked onto the lane branch: cherry-picking rewrites the SHA, so the original commit is not an ancestor of main and never will be, however many times it lands.

- **`git cherry -v origin/main <branch>` is the check that settles it.** A `-` prefix means git found a patch-identical commit upstream; a `+` means it did not. All five printed `-`, so `--force` discarded nothing. The same relation is invisible to `merge-base --is-ancestor`, which is what the tool (and my instinct) reached for.
- **The refusal text is right to be loud and wrong about the world**: read it as "I cannot see these upstream", not "these are unlanded" — the same shape as `learnings.md` 2026-09-12's *remote-absent is not content-absent*, and the reason that rule exists.
- **Belt and braces for a `--force` you are about to run on someone's only copy:** `git cat-file -e origin/main:<path>` for every file the branch introduced, and count the fixtures too. Cheap, and it converts "the patch-ids match" into "the files are there".
- Two operational notes from the same pass: the tool clears OneDrive's READONLY bit on the worktree admin dir before deleting it (git alone cannot), and it reports stale admin dirs it could not remove — `session_worktree.py prune` owns those, `close` does not.
## 2026-09-17 — OVERTURNED: "refresh-worker publishes NO soccer recommendations, so its pre-kickoff freeze is not observable from web" `[lane soccer-live-corners-stage2]`

- **What was believed** (`deploys.md` 2026-09-17 05:42:11Z, my own verify): 0 `.refresh-worker.json` freeze files on web by 11:48:31Z and 0 publisher lines for `soccer_source/*/api/recommendations/*` in 169 log lines, therefore refresh-worker's freeze and its estimator corners are local-only and the forward grades merge over ONE visible service.
- **What is true** (read 16:45Z): web holds **18** `recommendations_prekickoff_<date>.refresh-worker-4tx2.json` files, **50 entries, 50/50** carrying `corners_basis=team_rates_pressure_v1`, with web mtimes from **07:58:26Z** — before the reading that found none.
- **The rule:** the service TAG in a filename is not the service NAME. `RENDER_SERVICE_NAME` is `refresh-worker-4tx2` here, so a check for `.refresh-worker.json` matches nothing while the files sit there. When a name-shaped check returns zero, PRINT THE NAMES THAT DO EXIST before concluding absence. This is 2026-09-15's "a reader's zero is not the writer's absence" one layer down: the reader was looking for the wrong string.
## 2026-09-17 — FORBIDDEN: reading "which service runs the LOOP" as "which service runs the CODE" `[lane soccer-live-corners-stage2]`

- **Measured:** `SYNDICATE_ENABLE_LIVE_LENS_LOOP` true on live-odds-worker, false on refresh-worker. I wrote from that: this change "needs live-odds-worker only".
- **Why that was too strong** (peer a1e40980): `live_lens_loop.py:58` imports `poll_active_leagues_for_tick` FROM `scripts/poll_soccer_live_state`, and refresh-worker reaches the same `poll_league` through `SYNDICATE_ENABLE_SOCCER_WEEKLY_REFRESH_AUTORUN`, which is true there. Their log count: 62 `[soccer_live_state]` lines on live-odds-worker against 1 on refresh-worker in 6 h — a RARE SECOND WRITER, not a non-writer.
- **The rule:** an env flag says which ENTRY POINT is enabled, not which code runs. Trace the importers before scoping a deploy to one service. (Their counts are quoted and owed a re-measurement by this lane before being cited as fact.)
- **SEEN AGAIN 2026-09-21 (lane clv-close-from-book-quotes, session 9e340058):** I deployed an NCAAF book_quotes WRITER fix (`de6da1b7`) to live-odds-worker because its dedicated `ncaaf-lines` lane launches there. The capture that actually files NCAAF game lines ran seven minutes later in REFRESH-WORKER's pregame sweep (`refresh_status_latest__refresh-worker`, sports incl. ncaaf) on the old commit, and re-misfiled 244 rows. Caught only because the verification read the ARTIFACT (which shard the new rows landed in) instead of the deploy state. Before scoping a writer fix to one service, read every lane's latest run in `/api/ops/odds-refresh/status` for which launcher ran that sport.
## 2026-09-17 — FORBIDDEN: verifying a new ARTIFACT field on a served UI route `[lane soccer-live-corners-stage2]`

- **What happened:** after the live-corners deploy, `/soccer/<lg>/api/game/<event>` carries none of `corners_basis`, `live_corners`, `sim_projected_total_corners`, nor even `projected_total_corners` (checked directly 21:19Z). A verification taken there scores the change a NO-OP.
- **What is true:** the fields are in the artifact the worker writes — `soccer_source/<lg>/api/live_state/live_state_<date>.json`, `games[].projection` — where the 21:15:11.797Z snapshot carried all three.
- **The rule:** a served page is a fixed contract exposing a chosen subset. Verify a new field on the surface that WRITES it; if a UI route is meant to carry it, that contract change is a second piece of work.
- **Corollary, found in the same minute and worth as much as the deploy:** run the CONSUMER CENSUS. The only reader of `projected_total_corners` is `syndicate/features/soccer/live_lens.py:109`, so a better live corners number currently feeds one displayed metric and no money path (`leads.md` 2026-09-17).

### 2026-09-17 (session 4a583d41, lane prop-evidence-parity) — FORBIDDEN: polling for a job-free deploy window without holding the claim first

**What happened.** refresh-worker's preflight was HOLD (jobs in flight), so I polled it every
50 s waiting for a gap — with the claim FREE, because I did not want to sit on a lock I could
not yet use. Six polls in, lane `soccer-shot-woodwork-undercount` acquired refresh-worker, and
this lane waited ~25 minutes for a claim it had been first in line for. The lock is not a
courtesy to take at the last second; it is the queue.

**Why the instinct is wrong.** "Do not hold a lock you cannot use yet" is right for locks that
block work. A deploy claim blocks only OTHER DEPLOYS, has a 45-minute TTL, expires on its own
(`EXPIRED (does not block)`), and is released with one command. Holding it during a poll costs
nothing and is the only thing that makes the poll meaningful.

**How to apply.**
- `deploy_claim.py acquire` FIRST, then poll `deploy_preflight.py` for the window.
- Fire the deploy in the SAME loop cycle as the CLEAR. Job-free windows on refresh-worker
  measured ~70 s tonight (7 HOLDs then CLEAR on try 8, deploy fired 0 s later and landed).
  A CLEAR you carry into a human-paced next command is a CLEAR you have already lost.
- `release` refuses with "token does not match" when the acquiring shell was a different
  process. Pass `--token <token printed by acquire>`; `--force` is for a holder that is GONE,
  and reaching for it here would have been a false claim about another session.
- *(evidence: `log/2026-09-17.md` ~21:50Z; deploy `dep-dam5tcvqj5pc73bv6i1g`)*
## 2026-09-17 — FORBIDDEN: verifying a change on a UI CONTRACT route. A served page selects fields; absence there is a fact about the contract, never about the writer. `[lanes soccer-shot-woodwork-undercount, soccer-live-corners-stage2]`
- **The belief overturned:** that `/soccer/<league>/api/game/<event_id>` shows what the live-state writer wrote. It does not. Measured 2026-09-17 21:16Z: that route carries NONE of `corners_basis`, `live_corners`, `sim_projected_total_corners` — nor even `projected_total_corners` — while the same fields were live in the `live_state` ARTIFACT written 83 s earlier. A parallel lane had planned to grade its own deploy on that route and would have scored a shipped, working change as INERT.
- **A second face of the same defect, same evening:** at FULL TIME that route stops rendering the live box entirely (`rows: []`, read 21:28:49Z), so a plan to "take the clean reading after the whistle" measures nothing at all. The in-play window was the only one that existed, and it was nearly missed by waiting for a cleaner one.
- **How we found out:** one lane read the artifact, the other read the route, and the two disagreed about whether the same deploy had done anything.
- **The rule going forward:**
  - **Verify on the surface the WRITER wrote** — the artifact, the keyvalue payload, the log line — not on a display contract that chooses a subset for the UI. If the reading must come from a served route, first prove that route carries the field when the field is known to exist.
  - Absence on a display surface is evidence about the display surface. Say which surface every production reading came from, in the entry.
  - A live instrument has a WINDOW, and it can close in a way that looks like nothing happened. Ask "when does this surface stop reporting?" before deferring a reading to a more convenient moment.
- **Related, measured the same hour:** an IN-PLAY gap between our snapshot and a vendor's live box mixes the defect with poll lag (our artifact refreshes every ~2 min while ESPN's boxscore moves continuously; observed 1 -> 2 -> 1 in seven minutes). Lag can only make our count LOWER, so only a gap of 0 — or a gap equal to the known event count on a caught-up read — carries information.

### 2026-09-17 (session 4a583d41, lane nfl-usage-publish) — FORBIDDEN: writing UTF-8 punctuation as a `\xNN` escape inside a Python `str` and then `.encode()`-ing it

**What happened.** I built ledger blocks in a heredoc'd Python script from a `str` containing
the three escapes for an em-dash and encoded it UTF-8. Those escapes are three CHARACTERS, so
the encode emitted SIX bytes and the em-dash landed as mojibake. In `lanes.md` it hit the lane
HEADER, and `lane_claims` parses on the em-dash — so the new lane's `Files:` claims parsed as
EMPTY and nothing was enforcing them. Six occurrences in `lanes.md`, then one more in
`todo.md` an hour later, after I had already been bitten once.

**Why it is dangerous rather than cosmetic.** The file still opens, still renders, and still
passes `check_lane_invariants`, which reads headers rather than claims. The only symptom was a
`scope-guard` warning that is easy to read as noise. A third instance appeared while writing
THIS entry: the escape examples inside the text were themselves parsed by Python.

**How to apply.**
- Write ledger bytes with BYTE literals, or the real character in UTF-8 source. Never `\xNN`
  escapes in a `str` you later encode. When the TEXT must show such escapes, write the file
  with an editor tool rather than a heredoc'd string.
- After any scripted ledger write: the file must `.decode('utf-8')` without raising, and a
  scan for the double-encoded em-dash byte sequence must return 0.
- Then re-run the PARSER, not the linter: `lane_claims._claims(text)` must list your files.
- *(evidence: `log/2026-09-17.md`; 6 + 4 + 1 occurrences repaired in-session)*
- **The same mechanism, second shape, measured 2026-09-21 (session 35e1fa38):** a heredoc does not only mangle `\xNN`. It turns `\t` `\b` `\a` `\f` into CONTROL BYTES: `C:\tmp` -> `C:<TAB>mp`, and the regex `\bOPEN\b` -> `<BS>OPEN<BS>`, which sat inside THIS file's archives as a corrupted rule. A ledger-wide scan found **54 bytes in 18 files**, all restored (`cd3037b8`, `76e36bad`, `e8815bd1`, `352a5445`). The check above misses them all. **Add:** after any scripted ledger write, a scan for bytes < 0x20 other than CR/LF must return 0. `_env_xref.txt` is a real TSV and the only exception.

### 2026-09-17 (session 4a583d41, lane nfl-usage-publish) — FORBIDDEN: backgrounding an instrument you adapted but never watched complete ONE cycle

**What happened.** I `sed`-adapted a deploy-when-clear loop for a second service and renamed
the `--expect` field without renaming its paired `--baseline` flag. `deploy_preflight` answered
`NO_EXPECTATION` every cycle — correctly, it refuses a prediction with no baseline — and
because the loop was backgrounded it burned 24 cycles over ~14 minutes unable to act, through a
CLEAR window that did open (job counts fell to 3; the fixed rerun found CLEAR on its first
cycle and deployed instantly).

**Why the first run did not reveal it.** Preflight reports the JOB check before it validates
expectations, so while jobs were in flight every cycle printed `HOLD` — the same line a healthy
run prints. The defect was only observable in the state I had not yet reached.

**How to apply.**
- Run an adapted instrument for exactly ONE cycle in the foreground and read it before
  backgrounding. One cycle costs seconds; a blind loop costs the window.
- Renaming one half of a paired flag set (`--expect` / `--baseline`) is a silent break: grep
  for both halves.
- A verdict identical in the healthy and broken cases is not evidence the instrument works.
- *(evidence: `deploys.md` 2026-09-17 22:28:46Z entry)*
## 2026-09-17 — RECONCILE AT THE FINEST UNIT THE DATA OFFERS. A per-match residual hid a one-sided structure that per-team showed immediately. `[lane soccer-shot-on-target-definition]`
- **The belief overturned:** that "our on-target count disagrees with ESPN's in BOTH directions" — measured per MATCH the day before (exact in 15/24 with woodwork off target, 10/24 with it on) and used to conclude only that the stat was not derivable. Per TEAM, over the same fixtures, the residual is **strictly one-sided**: 39/48 exact, 9 short by 1-3, **never over**. Match totals let the two teams' errors cancel and destroyed the sign.
- **What was actually true:** ESPN's `shotsOnTarget` is not a function of the commentary type keys at all. Every subset of them peaks at 39/48, and all 9 short teams have EXACT total shots (48/48 per team) — so the events are present and the vendor's BOXSCORE classifies some of them differently from the vendor's own COMMENTARY. Adding `shot-hit-woodwork` makes the fit worse (10 exact teams each had 1-3 of them), which settles a second question the same measurement was not designed to answer.
- **How we found out:** the same census re-run per team instead of per match. Nothing else changed.
- **The rule going forward:**
  - **Reconcile at the smallest unit that carries the field** — per team before per match, per player before per team. An aggregate residual can be zero while both components are wrong; its SIGN is the first casualty.
  - **Two surfaces from one vendor are two sources.** "Derive X from feed Y" is a hypothesis to falsify, not a contract, even when both come from the same API response.
  - When a rule cannot be made exact, record what the field IS (here: a lower bound, 0.25/team/match low) next to the code, and name any priced consumer — otherwise the next reader "fixes" it by widening and overshoots the 39 cases that were already right to rescue the 9 that were not.
## 2026-09-17 — FORBIDDEN: counting a search tool's own ECHO of your query as a hit. It turns a zero into a one, and a one is a rate. `[lane soccer-shot-woodwork-undercount]`
- **The belief overturned:** "refresh-worker is a RARE SECOND WRITER of soccer live state — 1 `[soccer_live_state]` line in 6 h against live-odds-worker's 62." I published that ratio in `state_soccer.md`, in a lane verdict and in a `deploys.md` entry, and other sessions used it to size a risk.
- **What was actually true:** the 1 was `# refresh-worker  text='[soccer_live_state]'` — `render_logs.py`'s own header line, echoing the string I searched for. My count piped the tool's output through `grep -c` without dropping `#` headers. The real count is ZERO. Re-measured by `soccer-live-corners-stage2` over 47 h: live-odds-worker 1,381, refresh-worker 0, with the zero validated against the same reader and service (1,260 `SOCCER_UNIT_OUTCOME`, 166 `BOARD_BUILD_TIMING` in the same window), so it is a real absence rather than a broken query.
- **Why it mattered:** "1 in 6 h" and "0 in 47 h" are different KINDS of statement. The first is a rate and justifies urgency; the second says the code path exists and has never fired, which makes the same fix insurance. A peer was about to ask their user to authorise a deploy on my number.
- **The rule going forward:**
  - **Strip a tool's own headers before counting its output** (`grep -v '^#'`, or use the tool's `--json`/structured mode). A count that includes the query text is measuring the question, not the answer.
  - **A count of 1 deserves the same scepticism as a count of 0** — print the matching line before believing it. One line is cheap to eyeball and is exactly where an echo, a substring hit or a header hides. (The sibling trap the same evening: a plain `SOCCER_LIVE_STATE` search also matches `match_not_in_soccer_live_state` inside settlement lines.)
  - **When a published number is corrected, correct it everywhere it was published** — ledger subject, lane verdict and deploy entry — and name who re-measured it. A stale number in one file outlives the retraction in another.

### 2026-09-17 (session 4a583d41, lane nfl-prop-week-substrate) — FORBIDDEN: recording "this service CANNOT do X" when the evidence is only that a READER did not find X

**What happened.** A builder docstring and `state_football.md` both said "NEITHER SERVICE HAS THE
PLAYER-LEVEL pbp" and "refresh-worker can never build this artifact", and the NFL prop autorun
was left refusing `zero_sim_rows` hourly for over a week on that basis. The evidence was a row
count of zero. The pbp was on the worker's mounted disk the whole time (97,951,481 B, recorded
as `exists: true` in an artifact that worker itself built); the reader looked for it in the
ephemeral checkout. The same wrong root made the week resolver read git's unplayed schedule,
so every launch was week 1. This is the standing 2026-09-15 rule ("reading a READER's zero as
the WRITER's absence") meeting its most expensive form: the zero was written down as a
capability limit, so nobody re-checked the path.

**How to apply.**
- Before recording that a service lacks an input, find the input BY A PATH THAT DOES NOT RUN
  THROUGH THE READER UNDER SUSPICION — here, any artifact whose basis names the file and its size.
- A "cannot succeed here" note is a claim about the world; check it like one. If the reader
  resolves its root by probing for a DIFFERENT file, the note is about the probe.
- In this codebase specifically: any NFL read built on `default_nfl_source_root()` is suspect on
  a Render service. `#389`, `#441`, `#671` and `#672` are the same defect four times.

**Addendum to the double-encoding rule above (same session).** It recurred a THIRD time, in
`state_football.md`, minutes after the rule was written. The rule did not stop it; the byte check
inside the write path did. Put the check in the script that writes, not only in the ledger.
- *(evidence: `log/2026-09-17.md` ~23:45Z; `4d221768`)*
## 2026-09-17 — FORBIDDEN: reading an artifact FAMILY's retention as its CONTENTS' lifetime `[lane soccer-live-corners-stage2]`

- **What I believed and registered:** H32's evidence lives in `soccer_source/<lg>/api/live_state/live_state_<date>.json`, whose retention rule is 8 days, so "a DAILY harvest into a cache" preserves it (written into H32's registration, `log/2026-09-17.md` ~15:05 CT).
- **What was true** (22:01:52Z): the FILE lives 8 days, but its `games` block holds only the matches in play at the tick that wrote it. A date with two completed matches read `games: []`, so the projections were gone ~45 minutes after full time. A daily harvest would have captured nothing, every day, and the November grade would have had no evidence. It was caught only because the harvest was about to be built and I read one finished date first.
- **The rule:** retention says how long a PATH survives. It says nothing about how long a VALUE inside a rewritten file survives. For any artifact rewritten per tick, measure the lifetime of the specific field on a date whose events have ENDED before designing anything that depends on it.
- **Corollary, same evening:** a block added inside a whole-file-replaced artifact is only as durable as the least-updated service that writes that file. refresh-worker runs the corners swap but not the history code, so any tick of its would drop the block (`poll_soccer_live_state.py:443` write vs `:416` merge-forward). Measured rate: 0 in 47 h. `HISTORY_TRUNCATED` names it if that changes.
- *(evidence: `deploys.md` 2026-09-17 22:44:03Z; `log/2026-09-17.md` ~17:10 and ~18:10 CT)*
## 2026-09-18 — A LAUNCH'S REASON LABEL IS NOT ITS CAUSE, AND A REASON TOKEN IS NOT A LAUNCH COUNT. Both misread the MLB sim debounce the same night. `[lane mlb-sim-retrigger-churn]`
- **The belief overturned:** that counting `reason=fingerprint_change` in refresh-worker's logs counts fingerprint-triggered launches. It miscounts twice over. (1) The token appears on each sim's `MLB_DAILY_SIM_TRIGGERED` line AND its `MLB_DAILY_SIM_END` line, so every run counted twice: my pre-registered baseline "7 per 3 h" was really 4, and the prediction "<= 4" was set against a number the fix never had to beat. (2) `_mlb_daily_sim_decision` sets `reason = "fingerprint_change"` whenever ANY game's fingerprint changed, even when the launch was actually caused by `props_regen`, `join_mismatch` or `board_missing` riding along — so after the debounce went live, 3 of 4 "fingerprint" launches were props-regen launches in disguise.
- **How we found out:** the counts read "no change" after a fix that visibly held back 7 changes. The new `MLB_SIM_FINGERPRINT_LAUNCH` lines and the existing `MLB_PROPS_REGEN_DUE` lines lined up to the second, which the label never could have shown.
- **The rule going forward:**
  - **Count the event line, not a token.** One line type per event (`MLB_DAILY_SIM_TRIGGERED`), and check how many line types carry the token before using it as a counter.
  - **A reason label records the first matching branch, not the cause.** Where several triggers can merge, log each trigger's contribution separately, and grade a fix on the trigger it changed.
  - **Re-derive a baseline with the SAME counter you will grade with, before pre-registering the prediction** — a prediction set against a miscounted baseline can pass while proving nothing.

### 2026-09-18 (session 4a583d41, lane nfl-prop-week-substrate) — FORBIDDEN: predicting when a gated job runs next from a timer you saw in a log line, without reading which branch the job is on

**What happened.** After deploying the `#672` fix I told the user the NFL prop autorun would
relaunch "within the hour", because its logs had shown `cooldown_seconds=3600`. That number
belonged to `artifact_stale_relaunched_recently`. The first post-deploy launch left no artifact,
which puts the job on a DIFFERENT branch, `artifact_missing_after_launch`, gated on the full
`interval_seconds=86400`. The next build was ~24 h away, and a watcher sat out its 95-minute
window waiting for a launch the code would never make that night.

**The sibling error, same lane.** I recorded "the board was playing week 3" from game DATES,
without reading the schedule the code reads. Production's own schedule said week 2. The fix
chose week 2, and for a while I read that as a partial failure.

**How to apply.**
- Before predicting a re-run, name the guard's BRANCH from its latest log line and read that
  branch's timer in code. The same job can wait 1 h or 24 h depending on how its last run ended.
- A fact the code derives from a file (the current week, the active slate) is read FROM THAT
  FILE, not inferred from calendar arithmetic. The whole bug was a reader looking at the wrong
  copy of the schedule; the diagnosis should not repeat it by looking at no copy.
- *(evidence: `log/2026-09-18.md`; `deploys.md` 2026-09-18 00:33:04Z entry)*
## 2026-09-18 — FORBIDDEN: treating a named data file's PRESENCE as proof that it COVERS what a rule needs `[lane soccer-h24-grader]`

- **What the plan said** (`todo.md #665`, written by this session on 2026-09-15): "The pre-registration names `reports/soccer_backtest/fotmob_2y.json.gz` for the base seasons; confirm it is present before relying on it."
- **What was true** (2026-09-17 ~20:10 CT, from the file itself and its harvester's docstring): the file was present, committed and loadable. It held ONE season for Eredivisie, Championship and Belgian Pro League, and **only the current 2026 season for MLS**, while the registration defines the base as 2024-25 + 2025-26 (MLS 2024 + 2025). A presence check passes; the grade would then have computed MLS's "base" from the very season under test.
- **The rule:** a check on a data dependency must ask the question the rule asks, not whether the file exists. Print its per-group date coverage against the exact ranges the rule names, which is what `CLAUDE.md`'s "print the per-family coverage and the intersection" already demands of backtests. "Present" is a weaker claim than "covers", and a plan that asks only for the weaker one hands the next session a false all-clear.
- *(evidence: `log/2026-09-17.md` ~20:10 CT and ~20:40 CT; base matches after the fix MLS 1,062, Championship 1,114, Belgian 626, Eredivisie 618)*
## 2026-09-18 — FORBIDDEN: storing a production env value BEFORE holding the service's deploy claim `[lane worker-disk-auto-retention]`

**What happened.** On 2026-09-17 I PUT `SYNDICATE_DISK_RETENTION_DRY_RUN=1` on refresh-worker at ~22:05Z so that my own same-commit re-inject could follow after the 22:12:49Z spacing. Another lane took refresh-worker's claim at ~22:12Z and deployed `7ef0431b` at 22:34:51Z; that deploy -- and two more -- injected my env. The change went live under another lane's deploy, with no receipt, no pre-registered baseline read at deploy time, and no one watching its first boot. I had warned other sessions about exactly this ride-along the same day (the next-day floor env) and then repeated it myself.

**Rule.** A production env value is part of the next deploy of that service, whoever runs it. Write it only while holding the service's claim, immediately before your own deploy; never set it early to 'save time'. If another lane takes the claim first, either revert the PUT or tell that lane its deploy will carry your change and agree who reads it.

**Evidence.** `deploys.md` 2026-09-18 13:45Z; refresh-worker deploys `7ef0431b` (22:34:51Z), `c05918c8` (00:39:36Z), `c6a91b90` (01:20:00Z); `DISK_RETENTION_SUMMARY` 2026-09-18 00:48:54Z.

### 2026-09-18 (session 4a583d41, lane soccer-prop-conditioning) — FORBIDDEN: measuring a soccer name join, or anything that resolves team names, in a session worktree without `data/`

**What happened.** While closing `prop-evidence-parity` I measured the soccer fixture join with
`SoccerProjectionIndex.match_for` over production recommendation files, found 4 of 12 fixtures
"never join" ("Inter Milan"/"Internazionale", "FC Zwolle"/"PEC Zwolle", "SC Telstar"/"Telstar",
"FC Twente Enschede"/"FC Twente"), and filed it into `#673` as a defect. It was false. The soccer
alias map (`team_aliases._soccer_alias_to_name`) is DERIVED from the git-tracked team-branding
CSVs under `data/soccer_source/<league>/source_artifacts/`, and a session worktree excludes `data/`
by design. In that checkout the map was empty, `canonical_team` returned None for every club, and
`teams_match` fell back to heuristics. On production all four fixtures join (123/124, 267/275,
13/14, 13/14 rows projected on the served board). The code read fine and the numbers were real,
but they came from an environment production never runs.

**How to apply.**
- A join, alias, branding or roster measurement comes from the SERVED payload (`/api/board/layer1`
  rows with a projection), or from code run beside the data it reads. A session worktree has
  neither; the tool says so when it opens ("92 tests fail in this tree for that absence alone").
- Before filing "X never joins" from a local replay, run the same pair through the served board.
  A null there needs a live population (the fixture's rows must be on the board).
- The same absence explains most red soccer tests in a worktree: 21 of 26 failures in this
  session's sweep passed once git's own ten branding CSVs were present.
- To add those CSVs temporarily, note that writing a file under a sparse-excluded path CLEARS its
  skip-worktree bit, so deleting it afterwards shows as a tracked DELETION. `git sparse-checkout
  reapply` restores the bit; check `git status` for ` D` before any commit.
- *(evidence: `log/2026-09-18.md` ~14:40Z; lane `soccer-prop-conditioning`)*

**SEEN AGAIN 2026-09-21, in a form this rule's title does not name: a TEST RESULT, not a
measurement** `[lane layer2-line-move-magnitude, session 9e340058]`. I A/B'd 61 test files in a
session worktree, found 15 failing in both arms, and wrote into five places -- two `deploys.md`
entries, a lane block, the log and a peer message -- that they were "red on main". **14 of them
were `test_ncaaf_game_projections.py`, which resolves team names through the NCAAF team
registry under `data/`** -- the exact dependency this rule describes -- and its fixture copies
that registry (`:305`). All absent in the worktree; never run on a full checkout. Caught only
when asked to record them as a lead. Withdrawn in `fb176d26`.

**The rule generalises past joins: in a worktree, NO conclusion about code that reads `data/`
-- a measurement, a test verdict, a null -- is evidence about main.** A same-tree A/B is still
valid for COMPARING two arms (both lacked the data equally); it says nothing about whether
either arm is broken. `session_worktree.py` prints this on every `open` (~92 tests fail for
`data/` absence alone); I read it and did not apply it to my own failure list.
## 2026-09-18 — FORBIDDEN: certifying a cross-source NAME join as exact from one fixture `[lane soccer-live-corners-book-test]`

- **What the code said** (`syndicate/features/shared/soccer_live_gameline_source.py`, `soccer_live_gameline_index` docstring): the live pricer keys matches on full team names with no alias table because "Gate 1 measured that this join is exact for soccer: the ESPN names in the live-state artifact matched the OddsAPI grid on 286 rows for the 2026-08-20 la_liga fixture."
- **What was measured** (2026-09-18, the 38 in-play `alternate_totals_corners` events of 09-12..09-17, OddsAPI names vs ESPN summary names, same league, kickoff within 30 min): that key joined **21**. The platform's own `team_names.canonical_team_name` joined **34, with 0 wrong fixtures**. The misses are systematic, not noise: FC Augsburg / Augsburg, Osasuna / CA Osasuna, Atalanta / Atalanta BC, Le Havre AC / Le Havre, Paris Saint-Germain / Paris Saint Germain, the accent in CF Montreal, Houston Dynamo FC / Houston Dynamo. 286 rows were one fixture of one league: a row count is not coverage.
- **The rule:** a name join between two sources is certified per league, over the population it will serve, with the unmatched count printed as a funnel stage. One fixture proves only that fixture. A join that drops a row must count it, because a silent miss looks like "no price", which reads as a normal state.
- *(evidence: `log/2026-09-18.md` ~11:22 CT, and ~14:47 CT (19:47Z): READ on the pricer's own production run, the served soccer book grid joined 3 of 8 in-play matches, the other 5 for names alone; lead in `leads.md`)*
### 2026-09-18 (session 4a583d41, lane soccer-prop-conditioning) — a background watcher piped through `grep` writes NOTHING until it exits

**What happened.** I backgrounded a deploy watcher as `py -3 watch.py 2>&1 | grep -v http_compression`. Its
output file stayed empty through two reads. Nothing was wrong with the watcher: `grep` writing to a file
(not a terminal) block-buffers, so lines arrive only when the buffer fills or the process ends. An empty
output file looks exactly like a hung or dead watcher. The session rule "read the first cycle before
trusting a watcher" caught it, and the empty read was then misleading in the other direction.

**How to apply.** For any backgrounded watcher: `py -3 -u` (or `PYTHONUNBUFFERED=1`), and
`grep --line-buffered` on every filter in the pipe. Read the output file once before trusting it; if it is
empty, suspect buffering before suspecting the watcher.
- *(evidence: `log/2026-09-18.md` ~16:40Z checkpoint)*
## 2026-09-18 — FORBIDDEN: attributing a web health-check failure to your change without the day's post-deploy baseline `[lane ncaaf-player-data, session 259d6003]`

**What happened.** Minutes after web went live on `1c5caea6`, my typed Ask question took 25.6 s and then 59.8 s (both 502), and web failed health checks at 18:14:20Z (with a restart) and 18:20:05Z -- each inside one of my calls. I pulled the new fetcher (`e67c8b8a`) and redeployed. On that build -- fetcher unregistered, and **no requests from this session** -- web failed again at 18:29:21Z, 18:31:43Z and 18:33:48Z. The events API showed the same shape after EVERY web deploy that day and the day before (1-4 `server_failed reason.unhealthy` within ~10 min, then quiet). The fetcher measured 0.152 s cold on production's own snapshot. It was restored 30 minutes after it was pulled, at the cost of two extra web deploys, each with its own cold window.

**The rule.** Before attributing a post-deploy symptom to your change, read the service's events for the last several deploys and state the baseline rate (failures per deploy, minutes after go-live). A symptom inside a window that has one on every deploy is not evidence about your change. The control that settles it is cheap: leave the service alone for the window and watch -- that is what turned this. And a timing taken inside the cold window measures the window, not the code: re-time warm (>= 10 min after go-live) before calling anything slow.
- *(evidence: `deploys.md` 2026-09-18 18:09:25Z entry; `leads.md` 2026-09-18 post-deploy health-check lead)*
## 2026-09-18 — OVERTURNED: "a CLOSED block whose HEADER sessions are all idle is safe to archive" — a session the header never names had closed it 3 minutes earlier `[lane lane-archive-tool-checks, session 4991d2ec]`

- **What was believed:** the 09-15 rule above made the archive tools read owner liveness, taking "owner" to be the session ids in the block's first 3 lines. `owner_liveness.py` printed SAFE for `fotmob-team-name-aliases` because da346015 had been idle 3,910m.
- **What happened:** scheduled task session 96d06e18 had CLOSED the block at 19:08Z (commit 1e064aa3) and was active 3m before the read. Scheduled tasks, archivers and handoff sessions edit blocks they do not own, and none of them is added to the header.
- **How to apply:** judge a block's liveness by WHO LAST TOUCHED IT as well as by who owns it. `git blame` over the block's own lines on origin/main gives the newest touching commit; if that is younger than the idle threshold, WAIT. Both lane-archive tools now do this (`C:\tmp\lane-archive-tools\`, 2026-09-18). An identity you cannot see is a reason to wait, never a reason to proceed.
## 2026-09-18 — FORBIDDEN: sizing a time window from a DOCUMENTED cadence without measuring the cadence under load `[lane soccer-live-corners-book-test]`

- **What the rule assumed:** H36 took the live projection in force within 180 s of each book update, sized on the "~60 s cadence" written in `live_projection_history.py`'s docstring.
- **What was measured** (2026-09-18, the served history rows, then live-odds-worker's own write lines): the soccer live loop's per-league gap grows with matches in play, 116-155 s with 1-2, ~220 s with 3-5, 267-397 s with 6-9, 432 s with 15+ (2026-09-12). The docstring's figure was an idle-load number. At 180 s the window would have dropped a large, match-independent share of every busy slate's captures, most of all on Saturdays. It was amended to 600 s before any outcome existed, with the 180 s subset reported beside it.
- **The rule:** a window, timeout or tolerance that assumes how often something happens must be sized from that cadence MEASURED AT THE LOAD THE RULE WILL MEET. A cadence in a docstring or a config default is a belief about one load level. Measure it by load bucket before a registration or a guard depends on it.
- *(evidence: `log/2026-09-18.md` ~14:25 CT and ~14:50 CT; lead in `leads.md`)*
## 2026-09-18 A revert justified by ONE quantity does not cover another, and its call-count premise can go stale. `[lane market-history-index-memo]`

**What I believed.** The `#75` note in `odds_lifecycle.py` said caching `build_recent_market_history_index` "was tried and reverted": it "bought nothing (identical peak)" and the index "runs once per game", ~15 rebuilds of ~14k events, "noise". I read that as settled, and the profile target went elsewhere at first.

**What was true.** #75 measured PEAK MEMORY, which a rebuild never moves. The cost is CPU, and the premise had drifted: cProfile on refresh-worker 2026-09-18 showed **1,311 rebuilds per build, once per candidate**, for 517.5 of 641.0 s in candidate collection. Memoised per file version (`42594360`), candidate collection went 322.8 s → 47.7 s median.

**How to apply.**
- A recorded revert names the quantity it measured. Before trusting it for a DIFFERENT cost, re-measure that cost. "Identical peak" says nothing about CPU.
- A "runs N times" premise is a call count, and call counts move when callers change. Re-derive it from a profile (`ncalls`) rather than from the note.
- Profile before theorising: logs and wall spans pointed at book-quote cache thrash (real, ~8 s per cycle), while the profiler named two leaves worth ~90% of two stages.
- *(evidence in `.syndicate/deploys.md` 2026-09-18 19:55:27Z and 23:50Z, and `log/2026-09-18.md` evening checkpoint)*

### 2026-09-19 (session 4a583d41, lane nfl-prop-week-substrate) — FORBIDDEN: naming the cause of a fallback from its summary tag when the row carries the fields that split it

**What happened.** The NFL week-2 prop artifact had `sim_source=nfl_prior_season_fallback` on all 1,614 rows. I wrote
into `deploys.md`, `state_football.md`, a lane verdict and `leads.md` that "no player resolved in the 2026 index" and
"probably no 2026 pbp on refresh-worker". Both were wrong. The same rows carry `player_id_source` (1,509/1,614
`current_season`), `player_team_source` (1,545 `current_season`) and `rate_source` (the one field that fell back), and
`player_stats.player_rate` has a documented >= 2-game floor that makes every week-2 rate fall back. I had the file on disk
and read one field of five.

**How to apply.**
- `sim_source` is a SUMMARY of several joins. Before naming which join failed, count each per-join source field the row
  carries (`player_id_source`, `player_team_source`, `rate_source`, ...). The failing one is the cause; the others clear it.
- Before calling a fallback a defect, read the fallback's own condition in code. "Falls back only when the current season
  cannot answer" plus an n >= 2 floor is expected behaviour in week 2, not a missing input.
- *(evidence: `deploys.md` 2026-09-19 14:4xZ correction; `nfl_prop_projections_2026_wk2.json` rows)*
## 2026-09-18 — RECURRENCE of 2026-09-17 "a cache TTL read from the code is not the live TTL": I told the user an autorun flag was OFF because the code's default is off; the service sets it `true` `[lane ncaaf-player-data, session 259d6003]`
- **What happened.** A survey read `_..._autorun_enabled`'s absent-means-off default and I reported "the flag is off, a deploy alone won't run it". The refresh-worker env had the key set `true`; the autorun was already live. Corrected to the user in the same session.
- **Rule.** A value the code DEFAULTS to answers "what happens on a service that does not set the key" -- nothing else. Before stating a flag's state on production, read that ONE key on that service (single-key env endpoint; never the list API, which dumps secret values), and say which you read: `code default` or `live key`.

### 2026-09-19 (session 4a583d41, lane wnba-postgame-to-disk) — FORBIDDEN: keying a backfill on an artifact's PRESENCE when another writer produces the same path without the step the backfill exists to perform
- **What happened.** `#675`'s first backfill rebuilt a WNBA date whose box score was "not on disk". The point of the backfill was to PUBLISH the lost dates to web. But `intelligence_state._refresh_wnba_boxscores` (the settlement pass, same service, every ~3 min) writes the same file and never publishes. Once the fix moved that write to disk, "on disk" stopped meaning "on web", and 2026-09-18 would have been skipped for good. The tests passed, because none of them had a second writer. Caught by grepping every reader and writer of the path before committing. On the new code, the settlement pass wrote 09-18 and 09-17 ten minutes after go-live, before any producer tick.
- **Rule.** A backfill's predicate must name the OUTCOME it exists to produce (published, graded, sent), recorded by the step that produces it. It must not name an intermediate artifact another writer can create. Before trusting a presence check, list every writer of that path (`grep` the relative-path helper, not just the filename literal).

### 2026-09-19 (session a1e40980, lanes sim-sizing-skill-gate / board-build-stage-slowdown) — FORBIDDEN: letting a skill verdict gate the RANKING while the same number still sizes the MONEY; and widening a model's coverage before measuring it against the market
- **What happened.** `measured_market_skill` held 31 measured markets, 0 of them beating the market, and a `loses_to_market` verdict demoted the Layer 2 score. `portfolio_commit` never read the verdict: the sim still owned 0.25-0.39 of every day's staked dollars (57.6% on a representative row), and it sized a live WNBA over at 89% on 09-18.
- The same night I shipped WNBA score/combos distributions for coverage. The watcher read "405 edges, up from 15" as success. The market-relative backtest I ran next says those probabilities are noise (props: log-loss 0.858 vs the market's 0.682; totals: the sim +3.6 over the market total).
- **Rule.** A skill verdict is only real where EVERY consumer of the number reads it. Grep the number's consumers: rank, stake, side choice, the position cut. Before widening a model's reach (new markets, alternate lines, combos), score it against the de-vigged close. More edges on an unmeasured model is more risk, not progress.

### 2026-09-19 (session a1e40980, lane board-build-stage-slowdown) — A cadence that tracks "live windows" can be RESTART churn: count the boots before attributing it to load
- **What happened.** The soccer book grid rebuilt every 31-54 min "only when matches were live", and two sessions read it as live load. The cause was 5 refresh-worker SIGTERMs in that window (12 in 10 h, mostly deploys). Each boot empties the in-memory tick state (forcing the 18-grid tick). Each boot also re-ran the daily reconciliation INLINE from scratch, because it only stamps on completion; it ran ~23 min, and a deploy killed it every time. With no restart, live ticks came every 3-15 min.
- **Rule.** Before attributing a slow cadence to load or live state, count `WORKER_SHUTDOWN`/`BOOTED` in the same window. Any daily job that runs inline and stamps only at completion turns deploy churn into a retry storm.
### 2026-09-19 (session f26bba3b, lanes intelligence-idle-poll + polling-idle-pause-all) — OVERTURNED: "`skipWhenHidden` stops an unattended tab from polling." `document.hidden` answers whether the tab is ON SCREEN, not whether anyone is there; a verification tab left open in a Claude browser pane polled `/intelligence` (~6 MB) every minute for 11 h
- **What happened.** `/intelligence` passed `skipWhenHidden: true`. A session opened it in the Claude desktop browser pane to read one chip (09-17 17:56Z) and never closed it; the pane stayed visible and the page polled at 60/h until 04:53:47Z, ~4 GB of web egress, the 18Z..01Z tripwire spikes. Found only by grouping the edge log by FULL user agent (`Claude/2.110.0 ... MSIX`) — the tripwire's 60-char truncation read it as a plain Windows browser.
- **Rule.** Gate background polling on INTERACTION, not visibility (`polling.js` now pauses every poller after 15 idle min). And close any browser tab you opened for a verification when the reading is taken; a tab left open keeps polling after its session has moved on.
- **Test trap.** An OFF-SCREEN Claude pane reports `document.hidden === true`, so the old visibility gate stops polling there on its own; a test of the idle gate in such a pane passes vacuously unless `document.hidden` is overridden (as in `deploys.md` 2026-09-18 16:03:31Z).

### 2026-09-19 (session 4a583d41, lane mls-board-evening-gaps) — FORBIDDEN: filtering a board's GAMES by a game-level label when the label is derived from its rows; count the rows' own labels
- **What happened.** I filtered Layer 1's `games` on `game.league == "mls"`, then reported "5 of 13 MLS fixtures ABSENT from the board". I wrote that into a lane as hypothesis H1, a truncation theory. All 13 were present. The five carried game-level `league: None` because EACH had one league-less row beside 150-155 `mls` rows. The payload said so: `leagues` summed to 52 against `games` 57. That was the field I already had, and I read it only after writing the claim.
- **Rule.** Before claiming a fixture is absent from a board, select it by the ROWS (any row whose own `league`, or whose teams, match) and reconcile the payload's own totals: per-league counts against `games`, rows against `rows_total`. An absence claim needs a selector that could have found the thing (see "Compound absence claim" and "Null needs a live population").
## 2026-09-19 — FORBIDDEN: changing a shared helper's DEFAULT to fix one caller without a census of every caller that takes the default `[lane soccer-live-shared-paths]`

- **What happened:** `live_lens.build_resume_state` gained `include_stoppage=True` as its DEFAULT, to fix `project_live_match`'s missing end-of-half minutes (its docstring measures the resulting bias). `goal_in_window_probability` also calls it, with a clock it has already TRUNCATED to the window, and takes the default. So every goal window has since simulated window + the half's stoppage base: measured 2026-09-19 on the live commit's own code, a second-half "next 5 min" simulated 600 s, "next 10 min" 900 s, and at 60' (neutral, 1-0) the published next-5-minute probability was 0.195 where the model implies 0.100. No test failed, because no test read the clock a window simulates.
- **The same helper hid a second fact:** `project_live_player_props` also took the defaults, which made its simulations IDENTICAL to the projection's, so every live tick ran the same 80 matches twice (25% of a tick).
- **The rule:** when a shared function's default changes, list every caller that relies on the default and state, per caller, what the new value means for its inputs. A default is an argument every caller passes without writing it down. A test that pins the INPUT the callee receives (here, the clock a window simulates) catches the change; a test of the output alone usually does not.
- *(evidence: `log/2026-09-19.md` ~10:55 CT and ~11:15 CT; `3bced149`, `ee05f778`)*
### 2026-09-19 (session a1e40980, lane preflight-board-build-hold) — FORBIDDEN: reading a preflight CLEAR as "nothing in flight" on refresh-worker
- **What happened.** My env re-inject got `CLEAR: only infrastructure processes running` at 16:04:53Z and restarted refresh-worker while today's board build was between its Layer 2 write (16:05:23Z) and its publish. The board the user was watching froze from 10:49 to 11:20 CDT during live NCAAF.
- Preflight counts CHILD JOBS. The board build is a THREAD inside the worker. The detector that sees it (`check_deploy_safety.board_build_state()`, plus a drain the worker honours) already existed and was never wired into the gate.
- **Rule.** Before trusting a guard's CLEAR, name what it inspects and list what it cannot see. For refresh-worker, fire only right after a `BOARD_BUILD_TIMING` for TODAY's date, or drain first. A restart is not free even when every lock is green.
### 2026-09-19 (session 70e3a497, lane nhl-season-readiness) — FORBIDDEN: pinning a verification on a log marker without first tracing that marker's path to the log collector
- **What happened.** The lane pinned, correctly and BEFORE any change, "(a) live-odds-worker logs `=== NHL RUNNER HIT ===` for date 2026-09-19". It never could. `scripts/refresh_odds_sources.py:2281` runs every per-sport step under `subprocess.run(..., capture_output=True)`, which captures the child's stdout into a string the parent never prints. Two scheduled readings (10:10Z and 21:31 CDT) each spent queries on a zero that was guaranteed by the call site, and the same boundary silently voided the `[nhl_runner] NHL_SEASON_INPUTS present=5 missing=[]` check behind (c).
- A `capture_output=True` / `stdout=PIPE` boundary is invisible in the emitting file: `print(..., flush=True)` at `refresh_nhl_oddsapi.py:684` looks exactly like a line that reaches Render. The defect lives at the CALLER, one file away, and a passing unit test (`tests/test_nhl_refresh_runner.py:72` asserts the string is in `stdout.getvalue()`) confirms the print, not the delivery.
- **The rule.** When you pin a verification on a log line, name the process that prints it and every hop to the collector, and say which hop you checked. If the emitter is a child process, check the parent's `subprocess` call before pinning. Where the hop is broken, pin on what the PARENT emits (`ODDS_SWEEP_LAUNCHED`, `STEP_END`) or on the ARTIFACT the child wrote -- both are on the same service and both are real measurements, where the zero is not.
- **Second, smaller.** The early reading logged "one unattributed earlyExit at 11:23:59Z". It was a planned uptime recycle, matched to its `LIVE ODDS REFRESH WORKER RECYCLING` line 4 s earlier -- as were all 8 in the window. Leaving an event unattributed when the attributing line is one query away hands the next session a phantom to re-investigate.
- *(evidence: `log/2026-09-19.md` ~03:05Z addendum; `deploys.md` 2026-09-20 03:05Z; `f230361a`)*
## 2026-09-20 — FORBIDDEN: holding a shared deploy claim while polling for a gate that cannot open in that window `[lane soccer-live-shared-paths]`

- **What I did:** a deployer loop took the `live-odds-worker` claim and retried the preflight every ~4 minutes, first for 1h35m (21:35-23:10Z) and then again overnight, waiting for a 0-job CLEAR. Every sample read HOLD with 3-7 jobs.
- **What was true:** lane `live-inplay-board-cadence` measured it (19:12-19:52Z) -- TWO combined live sweeps (`refresh_odds_sources --sports mlb,wnba,ncaaf,soccer --phase live --mode full`) run CONCURRENTLY, each about an hour, so while any slate is live a 0-job sample essentially never occurs. The loop was not waiting for a gate that was about to open; it was holding a service-wide lock against every other lane for a condition that could not arise. That lane had to ask for the claim before I released it.
- **The rule:** before a retry loop takes a shared lock, state what has to become true for the gate to open and how often that happens. If the answer is unknown, poll the GATE without the lock and take the lock only when the gate is open. A lock held while waiting is a denial of service to every other holder, and the TTL hides it: re-acquiring on expiry looks like activity, not like blocking.
- *(evidence: `log/2026-09-19.md` ~18:15 CT and ~21:25 CT; `84e537c9`, `e99c69b1`)*
### 2026-09-20 (session 4a583d41, lanes mls-board-evening-gaps / wnba-postgame-to-disk) — FORBIDDEN: a deploy runner that never asks whether its change is ALREADY LIVE, when other sessions deploy the same service
- **What happened.** My gated runner for `6419eea5` waited for a safe window on refresh-worker for two hours. In that time session a1e40980 deployed `aebc040d` for its own lane, which carried my commit as a rider, and told me so. The runner had checked spacing, the claim, the board build and in-flight jobs -- and had no predicate for "the target already contains my fix". It was armed at 18:27Z under a user override to fire over a jobs-only HOLD (killing the MLB daily sim). Had I not stopped it by hand at 18:28Z, it would have restarted a service mid-slate and killed that sim to ship a change that was already running. Preflight would not have stopped it either: its redundancy check compares the target SHA to the live SHA, and main's tip had moved past `aebc040d`.
- **Rule.** On a repo where several sessions deploy the same service, a deploy runner's LAST check before firing is `git merge-base --is-ancestor <my fix> <live SHA>`: if the live commit already contains the change, stand down and take the reading instead. "My deploy has not fired" is not the same as "my change is not live", and the ledger's own convention -- riders named in someone else's `deploys.md` entry -- exists precisely because that is common. The same check belongs in the watcher: read liveness by CONTENT (ancestry of the fix), never by whether your own deploy id went live.

### 2026-09-20 (session 8eb963f9, scheduled task `archive-closed-lanes-0917`) — OVERTURNED: "an owner-idleness gate will drain the CLOSED backlog out of `lanes.md`"

- **What was believed.** The scheduled archiver, gated on owner transcript idleness >= 240m, would work through the CLOSED backlog a few blocks per run. Three runs now say otherwise.
- **Measured.** `owner_liveness.py --idle-min 240` at 2026-09-20T03:17Z and again at 15:47Z — **12 hours apart** — read owners `abacd435`, `a1e40980` and `4a583d41` at **0-1 minutes idle BOTH times**. Those three own 23 of the ~30 CLOSED blocks. A long-running session is not a session that goes idle: for it the 240m gate is unreachable BY CONSTRUCTION, not by timing, so the gate selects stragglers only.
- **The job grew the file it exists to shrink.** The 22:17 CDT run moved 0 blocks and still wrote its own lane block: `lanes.md` 638,121 → 641,536 B, **+3,415 B for a zero-move run**. An archiving job's own bookkeeping must never land in the file it archives — a zero-move run belongs in `log/`, which is not read at session start.
- **And the backlog was not stalled — the owners drain it themselves.** At 15:47Z session `abacd435` held an uncommitted `-193 / +0` `lanes.md` edit in worktree `soccer-espn-window-validation`, moving its own 15 CLOSED blocks into `lanes_history.md`. The gate was correctly refusing to race a live writer; "0 archived" was the gate working, not failing.
- **Rule.** Before reading "0 archived" as a stalled backlog, check whether the owners are draining it themselves. An idleness gate over permanently-live sessions is a straggler collector, and pricing it as a backlog drainer buys runs that cost more bytes than they reclaim.
- **TWO archive destinations, and the pointer difference is BY DESIGN — checked the same day, do not re-open it.** `lanes_closed.md` (the scheduled task's tools) leaves a pointer under `## Archived lanes`; `lanes_history.md` (`scripts/archive_released_lanes.py`) leaves none — measured `-193 / +0`, and the word "pointer" appears nowhere in that script's code, only in its docstring's prose. That is NOT a defect: `check_lane_invariants.py:324-325` and `:374-376` pool `^###\s+(slug)` headers over all FOUR ledger files (`lanes.md`, `lanes_closed.md`, `lanes_closed_archive.md`, `lanes_history.md`), so a block moved verbatim keeps its header and every checker still finds it, and the script writes a banner naming the moved slugs and the date. Adding pointers would put bytes back into a file the script exists to shrink.
- **What misled me, and the rule.** Commit `c42aef5b` says "archive this session's two CLOSED blocks … **with a pointer each** -- archive_released_lanes.py": `+2 / -77` in `lanes.md`, so the pointers are real, but that session wrote them BY HAND and the message attributes them to the tool. A commit message naming a tool is a claim about the SESSION's whole edit, not about what the tool does — read the tool before inferring its behaviour from a message that credits it.
- *(evidence: `log/2026-09-19.md` 22:17 CDT addendum, `log/2026-09-20.md` 10:47 CDT; commits `f92ce93d`, `e59d91d4`)*

### 2026-09-20 (session a1e40980, lane live-inplay-board-cadence) — FORBIDDEN: reading an interval knob as the cadence when the code consults it once per loop pass. The PASS is the cadence; the knob is a ceiling on nothing.

- **The belief:** `SYNDICATE_NCAAF_LINES_REFRESH_INTERVAL_SECONDS` sets how often NCAAF lines are captured. It is read by `_ncaaf_lines_refresh_interval_seconds()`, it gates the launch, and lowering it 300 -> 150 should double the capture rate. The env was written, read back, and the value was correct.
- **What was actually true:** the launcher is called once per `run_live_odds_refresh_worker` main-loop pass, and a pass ran **2.1-10.4 min** (measured 2026-09-19 18:02-18:31Z: 4.4, 2.1, 8.4, 10.4). So the interval could only ever round UP to the pass. MEASURED launch gaps: **median 535 s at interval=300** and **532 s at interval=150** — a 2x change in the knob moved the cadence by 3 seconds.
- **How it was caught:** not by reading the code, which looks correct in isolation, but by timing the LAUNCH LINES either side of the change (`NCAAF_LINES_AUTORUN_LAUNCHED`, 17:24-18:31Z). The env read-back said 150 and the system said 532.
- **The fix and its measurement:** a 30 s timer thread that calls the same launchers (`bad3b94e`), keeping their own interval gates and per-lane mutexes. After it: NCAAF **152 s** median (n=18), NFL **154 s** (n=15). Same knob, same value, 3.5x the cadence.
- **The rule:** before trusting a periodic knob, measure the EMITTED events it is supposed to pace, not the value in the environment. A knob whose consumer is inside a slower loop is a lever connected to nothing — and it reads as a working fix, because the value really did change. Related: `[2026-09-15] carrying a deploy's predicted effect on a time-based reading`, and the standing rule that presence is not reachability.

### 2026-09-20 (session a1e40980, lane live-inplay-board-cadence) — FORBIDDEN: reporting `book_age_seconds` as the board's latency. It is time since the PRICE MOVED; our lag is `quote_seen_age_seconds`, and the two differ by minutes.

- **What I reported all day:** "served in-play quote age" = (now - `price_grid_generated_at`) + `book_age_seconds`, as the measure of the lane's goal ("within ~3 min of the price MOVING"). Numbers: 310 s and 316 s on 09-19, 262 s across the 09-20 NFL kickoff window, against a 733 s baseline. The arithmetic was right and the comparison to its own baseline was fair, because the baseline used the same formula.
- **What it actually measures:** `layer2_board.py:2820-2825` says it outright — `book_age_seconds` is "time since the price last MOVED", `quote_seen_age_seconds` is "time since we last LOOKED". The same file already records the gap between them: nfl book_age median **331.6m** against seen_age **270.4m**; wnba **376.2m** against **68.5m**. So a number built on `book_age` charges MARKET QUIESCENCE to the pipeline. A line that has not ticked in four minutes is not a board that is four minutes late.
- **The corrected decomposition, 2026-09-20 17:22-17:23Z, 369-377 in-play overlay cards:** time since we LOOKED ~**202 s** + grid->serve **79-160 s** = **~362 s look-to-serve**, against `book_age`-based numbers of 322-369 s that happened to land nearby for the wrong reason.
- **Why it matters beyond bookkeeping:** the two framings point at different fixes. `book_age` says "tighten the freshness ceiling" (`SYNDICATE_INPLAY_OVERLAY_MAX_PRICE_AGE_SECONDS` 300 -> 180 was modelled at 109 of 377 cards kept, median 162 s) — which would mostly discard rows whose price simply had not moved. The seen-age framing says the work is split between capture (~202 s: not every event is refreshed by every 154 s run) and the board (79-160 s).
- **The rule:** when a goal names an EVENT ("within N minutes of the price moving"), the metric must start at that event. A field whose name contains `age` is not automatically the age you mean — read what the producer documents it as before building a verdict on it. Related: `[a projection is not a model edge]`, and the standing rule to count the field the CONSUMER reads.

### 2026-09-20 (session a1e40980, lanes live-inplay-board-cadence + pull-window-dated-scope) — FORBIDDEN: reading a ZERO COUNTER as evidence about the thing being counted. It cannot separate "the mechanism did not run" from "it ran and had nothing to report". Read a POSITIVE marker instead.

- **TWICE IN ONE SESSION, six hours apart, in unrelated subsystems.** That is why this is its own rule and not a footnote on the two incidents.
  - **(1) The inert interval knob.** `SYNDICATE_NCAAF_LINES_REFRESH_INTERVAL_SECONDS` 300 -> 150 was written and read back correctly, and the launch cadence did not move (median 535 s -> 532 s) because the launcher is called once per main-loop pass. The env read-back was a zero-information confirmation: it told me the VALUE was set, never that anything consumed it.
  - **(2) The empty skip list.** `SWEEP_SKIPPED` on refresh-worker read **0**, and I concluded `clv_price_trail` was absent because "its producer is not deployed". Both halves were wrong: the producer IS deployed and writing (`[clv_price_trail] TRAIL rows_in=4956 written=1182`), and the counter was 0 because **no sweep ran on that service in the window** -- its main loop never sweeps, and a sweep arrives only from rare spawned jobs (`run_queued_refresh_job.py`, `run_mlb_daily_sim_job.py`; the queued path measured **0 samples >0 in 1.5 h** at `run_refresh_worker.py:4183`). NOTE: my first write-up of this said "does not run at all", which is the absence-in-a-window error one rule along -- corrected within the hour, by the same peer whose over-strong claim I had just amended.
- **What settled (2), and it is the template:** a POSITIVE/NEGATIVE CONTRAST across services, same window. refresh-worker `PUBLISH_OK` **339** (its own direct publishes, so the service and the logger are both alive) against `publishedArtifacts` **0** and `PUBLISH_SKIPPED_UNCHANGED` **0**; live-odds-worker emits both constantly. The live `PUBLISH_OK` is what makes the two zeroes mean something — without it they are indistinguishable from a dead logger.
- **Why the code could not settle it either:** `live_lens_loop.py:1041` and `live_refresh_loop.py:5993` both call the sweep, the latter calling itself "one of FOUR paths into that sweep", and both runners call `start_live_lens_loop()` behind `SYNDICATE_ENABLE_LIVE_LENS_LOOP`. Which service sweeps is a FLAG that moves with no diff. A comment naming "the only production caller" was stale in the tree while I was reading it.
- **The rule:** before a zero is evidence, name the line that would be present if the mechanism HAD run, and confirm that line is being emitted somewhere for something. Pair it with `[absent signal is about the emitter]` and `[absence in a window isn't absence]` — this is the same family, and the session count says it keeps recurring in new disguises.
## 2026-09-20 — RELEASING A LANE CLAIM ON `origin/main` ALONE CAN *MANUFACTURE* THE SAME BLOCK, and the second block reads identically to the first `[lane daily-accuracy-suite]`

Nine paths were released from an orphaned lane's `- Files:` line, landed on
`origin/main`, and the very next edit was blocked again by the SAME lane on the
SAME file. It looked like the push had not taken effect. It had.

`lane_claims_source.effective_claims` computes
`local_added = primary - base_claims - main_claims`. While the claim sat on
`main`, the stale primary tree's identical `(lane, path)` pair was cancelled by
`main_claims`. **Removing it from `main` is exactly what stops that
cancellation**, so the primary tree's surviving copy is promoted to a
local-added claim and re-blocks. The release removed the claim from one source
and created it in the other.

**The only tell is the `Claim source:` line**, which flipped from
`origin/main@44e96867` to `primary tree lanes.md, added since fork point
1a280739`. Everything else in the BLOCKED message — file, lane, remedy text —
is byte-identical, so a quick re-read looks like a no-op push.

**RULE: a claim take or release is TWO edits, in the same pass** — the worktree
copy that lands on `main`, and the primary tree's copy that the hooks read. Also:
the guard blocks on ANY lane other than `current`, so adding your own lane
alongside the incumbent does nothing; the incumbent's entry has to actually go.

This is the mirror image of the 2026-09-17 fix (`3d3587f7`) that taught the guard
to read `origin/main`. That fix removed the need to mirror a take into the primary
tree; it did not remove the need to mirror a RELEASE, because the two operations
sit on opposite sides of the same set subtraction. The earlier note read as
"mirroring is no longer the fix", which is true for one direction and false for
the other — the most expensive kind of half-true.
## 2026-09-21 — FORBIDDEN: windowing a simulation by TRUNCATING the clock it is told is left, when the simulator's dynamics read that clock `[session abacd435, measured offline]`

- **What is wrong:** `live_lens.goal_in_window_probability` answers "goal in the next W seconds" by resuming the match with `clock_remaining = W`. `soccersim.situation_model.classify_urgency` reads exactly that field: 2nd half and <= 480 s left while trailing by 1-2 is DESPERATION, <= 1500 s trailing is TRAILING_PUSH, <= 900 s leading is PROTECT_LEAD, 1st half <= 120 s is CLOSING_HALF. So the window is not "the next five minutes of this match"; it is "the last five minutes of a half", played by both sides accordingly.
- **Measured 2026-09-21, N=3000 per estimate, neutral ratings:** at the 60th minute the published number is LOW by 0.0183 (next 5) and 0.0277 (next 10) when a side leads by one, and by 0.0150 / 0.0190 when a side trails by one or two — 8-12% relative, six of six affected pairs negative. Four control pairs where no urgency rule can fire agree to 0.0000 exactly, because identical seeds give identical path prefixes.
- **The rule:** before windowing a simulation by shortening its clock, list every input the simulator derives FROM that clock. If any behaviour switches on it, the truncation is a DIFFERENT MODEL, not a shorter run of the same one. Simulate the real remaining time and take the window out of the resulting path by TIMESTAMP — which is also cheaper, because one path answers every window.
- **The near neighbour, same function, one day earlier:** `build_resume_state`'s `include_stoppage` default made this same window simulate W PLUS the half's stoppage (2026-09-19 entry). Both bugs have one shape: the window's clock is not the match's clock, and no test read the clock the window was handed.
- *(evidence: `scratchpad/goal_window_urgency_bias.py`, `log/2026-09-21.md`, and the cost lead in `leads.md`)*

### 2026-09-21 (session a1e40980, lane live-inplay-board-cadence) — FORBIDDEN: lowering a THRESHOLD to speed something up without first measuring how often its TRIGGER fires. Below the trigger rate, the threshold is decoration.

- **The change:** `SYNDICATE_INPLAY_OVERLAY_CACHE_MIN_AGE_SECONDS` 45 -> 22, to make the served board pick up in-play overlays sooner. Modelled gain 306 -> 253 s. Measured gain: **none** — expiry-age median 85 s (n=10) against an 86 s baseline.
- **Why:** the combined-board rebuild is LAZY. It fires when a REQUEST finds the entry stale, so the floor only matters if requests arrive faster than the floor. Measured: board queries every **28 s** across **2** gunicorn workers = about **56 s per worker**, always older than 45 s. The knob sat below the trigger and could never bind.
- **The tell I ignored:** I had already measured the two facts that predict this — `COMBINED_BOARD_OVERLAY_EXPIRED age_s` values of 67-72 s (well above the old 45 s floor, so the floor was not what released them) and a page that polls every 60 s. A threshold below the observed trigger interval is inert BY ARITHMETIC, before any deploy.
- **Ask first, in this order:** what fires this check, how often does that happen, and is my threshold above or below that rate? If below, the knob is decoration and the real lever is the trigger (here: make the rebuild proactive instead of request-driven, a code change with its own cost on a health-check-sensitive service).
- **Third inert change in ONE session**, each found only by measuring emitted behaviour rather than reading the setting back: an interval knob consulted once per slow loop pass; an allowlist entry for a file whose service never sweeps; and this floor. The family rule is `[a zero counter cannot separate did-not-run from ran-with-nothing-to-report]` — this is its twin: a setting read back correctly says nothing about whether anything consumes it.
## 2026-09-21 — A FILTER ON A MODEL METRIC GRADES THE MODEL, NOT THE FILTER'S OWN EDGE; and a seeded bootstrap is deterministic in ORDER, not in DATA `[lane inplay-skill-scoreboard, session a1e40980]`
- **The belief:** "the scorecard's `fair_method=consensus` bucket tells us whether the price-shopping edge is real." I recommended building a slice on it, and the user said proceed.
- **What was true:** both scorecard metrics need `model_edge_pct`: Brier of `fair + me/100`, and ROI only where `me > 0`. A `fair_method` band chooses WHICH rows get graded. It still grades the MODEL on them. The consensus edge (best price vs fair) was graded nowhere. On live rows there is no model edge either (graded live model rows over 28d: mlb 0, wnba 0, nfl 0, ncaaf 16, soccer 118). So the slice would have read `insufficient` forever, and it looked like "wait for more data".
- **Caught before any code edit,** by re-running the scorecard's own `evaluate_ids` over production's saved state and asking why the games count was 0, not what the verdict was.
- **How to apply:** before proposing an instrument for a question, write down the formula the instrument evaluates and check that the quantity in the question appears in it. A band, a filter or a segment changes the population. It never changes the estimand.
- **Second rule, same session:** a fixed seed makes a bootstrap reproducible only for the same ORDER of values. `bootstrap_mean` resamples by index, a run sees games in insertion order, and the saved state comes back key-sorted. 4 of 12 shuffles of the same games changed the validated set. Sort the values canonically before resampling, and test with shuffles, not with a second run over the same list.
## 2026-09-21 — A VERDICT OVER EVERYTHING THE BOARD PRICED IS NOT A VERDICT ON WHAT IT SHOWS; report both, and never replace one with the other `[lane inplay-skill-scoreboard, session a1e40980]`
- **What I said:** "the price-shopping edge FAILS on soccer in-play player props, -39% to -76% per game". That was true of the recorded population. Read as exposure, it was wrong: 99.9% of those rows sit in the `dead` lane and are never served. Meanwhile NCAAF in-play moneyline, 154 of 182 rows unserved, puts its 28 SERVED rows at the very top of the live board.
- **Caught by** splitting the same graded rows by the recorder's board lane (`ln`) before calling anything an exposure. The unsplit number would have sent a fix to the soccer props, which the gate already handles, and missed the moneyline rows at the top of the board.
- **How to apply:** before reading a population verdict as risk, split it by what the consumer actually sees (lane, shortlist, served) and report both columns. The 2026-09-12 FORBIDDEN rule still stands: filtering the MEASURED population to the published subset freezes the metric. So the served column goes BESIDE the pooled one, never INSTEAD of it.
## 2026-09-21 — FORBIDDEN: a guard that reads its credential through a DIFFERENT loader than the action it guards `[lane preflight-board-build-hold, session a1e40980]`
- **The belief (mine, 09-20):** "no `RENDER_API_KEY` means this shell cannot deploy either, so the board-build HOLD may treat it as not applicable." It shipped with a test pinning exactly that.
- **What was true:** `render_deploy.py` and `deploy_preflight._api_key()` fall back to the MAIN worktree's `.env`. `check_deploy_safety._load_render_key()` did not. From a session worktree, where the protocol runs every deploy, the guard could not ask while the deploy could act. So the HOLD was silently inert for every protocol deploy for ~23 h. Every Render call through that loader got HTTP 400 with an empty body, which I also misread as an API failure.
- **Found by accident:** chasing the 400 on an unrelated reading, and comparing the helper's key with the `.env` key (equality and length only, never the value).
- **How to apply:** a guard must obtain its inputs the way the guarded action does, preferably through the same function. "The guard cannot run, so the action cannot run" is a claim to TEST from the directory the action runs in, not to reason about. Tests that pass because a credential is MISSING are a red flag: `test_deploy_preflight`'s harnesses passed for exactly that reason and started calling production the moment the key was found.
## 2026-09-21 — FORBIDDEN: fixing a MISSING source before testing whether the consumer could use it when PRESENT; and grading a close for a game that has not kicked off `[lane clv-close-from-book-quotes, session 9e340058]`

- **Measured:** CLV resolved 0 for NFL/NCAAF/WNBA because odds_history was never written for them (fast-mode lanes return before the step). The proposed fix was "make the fast lanes write it". WNBA HAD odds_history on 08-20/08-27/08-29 and resolved **0 of 1,165 / 2,449 / 2,723** anyway: 33- vs 32-char event ids, a prop key shape the join never builds, no alternates. The source the consumer needed (`book_quotes`, per book, keyed by the opening's own fields) already existed on web; 98.9% / 92.0% / 88.5-98.1% exact same-book coverage.
- **The rule:** before restoring a missing input, find a date where it WAS present and run the consumer over it. A zero that persists with the input present is a key or shape defect, and restoring the input fixes nothing.
- **Second rule, same session:** a "last observation before kickoff" for a game that has not kicked off is the CURRENT price, not a close. An mlb report read at ~15:40Z counted 1,039 such rows and they fed a forward-CLV verdict; at 17:07:51Z 971 of 1,102 resolved rows were unstarted games. Any CLV-over-a-date reading must be on finished games only, or on code that refuses them (`a720941d`, `not_started`).
- **Third, a tooling one:** the export route's `oversize` list is not a wall -- `/api/ops/artifacts/stream?path=` serves those files uncapped. Reading the cap as a limit produced a 12-17% NCAAF coverage figure whose real value was 88.5-98.1%.
## 2026-09-21 — A MECHANISM THAT EXPLAINS AN ODD RANKING IS NOT EVIDENCE THE RANKING IS HARMFUL; grade the class before fixing it `[lane ncaaf-live-h2h-top-scores, session a1e40980]`
- **What I was about to do:** served NCAAF in-play moneyline rows scored up to 86 (a typical #1 is ~6) and that slice lost -0.38/game. I traced the score to longshot EV passing a 1-probability-point guard, and was heading to recommend a longshot gate or a bigger in-play error floor.
- **What the class showed:** served in-play rows across all sports, graded by implied probability. The 5-15% bucket made **+1.20/game [+0.38, +2.08]** over 91 games. NCAAF longshots across markets made +2.41 to +4.67. The losing slice was one market, 15 games, with a CI that includes 0. The fix I had in mind would have removed the rows that made money.
- **How to apply:** before proposing a fix for "X ranks too high and loses", grade X's whole CLASS (the slice the fix would actually touch) on realised outcomes, not the example that surfaced it. A mechanism tells you WHY something ranks; only realised outcomes tell you whether that is wrong. The two questions need separate evidence.
## 2026-09-21 — FORBIDDEN: comparing two RANKINGS on raw closing-line value in probability points, gross of the venue fee; and adopting a correction fitted on the whole population without re-checking it on the subset you will act on `[lane layer2-score-outcome-calibration, session 236bd219]`
- **What I believed, twice, and it was wrong both times:** (1) a candidate ranking that picked favourites "beat" today's score because its CLV was higher in probability points (+1.34 vs +0.96) -- in ROI-equivalent units (delta-p x decimal) it was LOWER (+2.66% vs +3.19%), because one point at +240 is worth ~1.8x one point at -127; (2) then today's score looked marginally better than the fee-aware candidate (-0.15 pts paired) -- until the fee actually paid was netted: 25% of today's top-10 are Kalshi/Polymarket, and net of fees the fee-aware ranking won by +0.79 [+0.27, +1.29] over 82 slates.
- **And a third, on the model side:** a logit slope of 1.18 [1.08, 1.30] fitted on ALL graded rows said the consensus fair overstates longshots. Inside the positive-EV subset -- the only rows the board bets -- longshots were calibrated (hit = fair within 0.3 pp) and the shortfall sat at even money, where a slope changes nothing. Applied, it would have demoted the +EV longshots that deliver.
- **How to apply:** compare rankings on (a) the same slates, paired, (b) ROI-equivalent CLV = clv_pp/100 x decimal, (c) NET of the fee each pick would pay. Before adopting any calibration or correction fitted on a whole population, re-measure it on the subset your ranking actually selects; a population-level bias can be absent, or reversed, in the tail you act on.
## 2026-09-21 — CODE ON MAIN SHIPS WITH ANYONE'S DEPLOY: a "deploy it after X" gate cannot hold once the commit has landed `[lane live-inplay-board-cadence, session a1e40980]`
- **The belief:** the user approved lever 2b ("deploy b tomorrow after tonight's reading"), so I landed `3072ab01` on main and scheduled a GATED refresh-worker deploy for the next morning. I believed that controlled WHEN it shipped.
- **What happened:** at 21:49:21Z another lane deployed refresh-worker from main (`dd43fd49`). The protocol requires deploying an `origin/main` commit, so that deploy carried `3072ab01`: a day early, with no gate, and co-live with tonight's lever-1 reading, which it now confounds. Nobody did anything wrong. The commit was simply eligible.
- **How to apply:** once a commit is on main, its ship time belongs to whoever deploys that service next. If WHEN matters (a gate, a clean A/B, one change per deploy), ship it DEFAULT-OFF behind a flag and let the deploy be the flag flip, or keep it off main until the gate passes. After landing, check each service's live commit for your SHA (`git merge-base --is-ancestor`) before assuming it is not live.
## 2026-09-21 — FORBIDDEN: deploying a fix whose test fixture SUPPLIES a field the production pipeline only attaches in a LATER stage; run the new code over the production payload with that field WITHHELD first `[lane layer2-score-outcome-calibration, session 236bd219]`
- **What happened:** `569ebca1` read the Kalshi ticker from `side_best` so MLB rows would pay the x0.5 series fee. Its test put a ticker on `side_best`, passed, and failed with the fix reverted -- a textbook reachability test. Deployed (refresh-worker `b99143e2`), it moved **0 of 82** rows: at scoring time no Kalshi price has a ticker anywhere; `apply_venue_quotes` stamps `venue_ref` onto the rows AFTER `build_layer2_rows` scored them (`layer2_shortlist.py:1752` vs `:1611`). 45 of the 82 served rows carried a ticker -- visible on the served payload, so it looked available.
- **The fix that worked (`03d3f801`)** was checked the other way first: the new function run over the SERVED rows with the ticker deliberately withheld resolved 81 of 82, and production then read 21 of 21.
- **How to apply:** before deploying a fix that reads field F, find the STAGE that writes F relative to the stage that reads it (grep the writer, not the served payload), and run the fix over a production payload with F removed. A field present on the served row proves only that SOME stage wrote it, not that it existed when your code ran. Also: predict a RATE, not a count, when the population can shrink between baseline and reading (MLB supply 407 -> 255 at first pitch made ">= 39 rows" miss while 21/21 held).
## 2026-09-22 — RULE: a catch-all refusal token says WHERE an order died, not WHY; read the module's own line just before it, and expect the next gate once the first one clears `[lane layer2-score-outcome-calibration, session 236bd219]`
- **What happened:** with `commence_time` fixed, the Soroka strikeout prop refused `market_unresolved_for_position`. I read the token and filed a lead saying `resolve_market` "finds no market for the slug", with the fix pointing at slate truncation or storage. Wrong: the `POLYMARKET_SIDE_REFUSED ... reason=yes_no_market_subject_is_not_our_side outcomes=['Yes','No']` line 24 s earlier showed the market WAS in the slate. The resolver had no player-prop branch. `_polymarket_resolve_market` returns `None` for about ten distinct reasons, and the builder turns every one into the same token.
- **And it was masked:** `commence_unknown` fires before market resolution, so no prop had ever reached the side resolver. Fixing one gate exposed the next one on the first pass.
- **How to apply:** before diagnosing `market_unresolved_for_position` (or any `OrderBuildError` token raised on a `None` return), pull the `POLYMARKET_*` / `KALSHI_*` lines for the same slug in the seconds before it. After removing a refusal, read the NEXT pass for a new refusal on the same rows before calling the path open.
- **Cost:** the lead I filed named the wrong subsystem ("absent from the stored slate -- truncation / date ordering") and would have sent the next session into `polymarket_us_markets`. Caught within the hour only because the fix was mine to write. The REAL cost is older: Polymarket player props have never once been placeable, silently, for as long as the prop join has been producing matches -- every one refused at build, counted under a token that reads like a venue data gap.
- **A rule would not have caught this; a CHECK would.** Nothing watches for a market family that is present in a venue plan and NEVER builds. `ORDER_PATH venue=<v> markets={...}` already carries `would_build` / refusal counts per family per pass, so the check is a daily census over those lines: any family with positions > 0 and `would_build` == 0 across a whole day is named. Filed as a lead 2026-09-22.
## 2026-09-22 — RULE: a preflight POLLER writes receipts; stopping the loop does not stop the child it already launched, and the newest receipt is the one the guard reads `[lane mlb-doubleheader-e2e, session 3692ff18]`
- **What happened:** I polled `deploy_preflight.py` in a loop while refresh-worker was busy, retargeted mid-wait (the deploy target moved from `0731d3ae` to `f15ffb80` as more of the lane landed), and stopped the old loop with TaskStop. The new loop returned `CLEAR: only infrastructure processes running` at 16:28:52Z for `f15ffb80`; the deploy was then REFUSED — `the CLEAR preflight is for 0731d3ae but this deploys f15ffb80`. The stopped loop's in-flight preflight child had finished AFTER mine and overwritten the receipt with the old target's verdict. The guard was right and the loop was the liar.
- **Why it matters:** the window a poller exists to catch is minutes wide (here: between back-to-back board builds). Spending it on a refused deploy can cost the window, and the receipt's target is the only field that distinguishes "my CLEAR" from "a CLEAR".
- **How to apply:** run one preflight IMMEDIATELY before the deploy call, in the same step, with the exact SHA you are about to deploy — treat a poller's CLEAR as "the service is quiet now", never as the authorisation. When a poll loop is retargeted or stopped, assume a child of the old target is still in flight. Related: `project_preflight_newest_verdict_and_early_release` (another session's CLAIMED preflight wipes your CLEAR) — the same hazard from inside one session.
## 2026-09-22 — RULE: fixing a PRODUCER does not fix a surface until you know WHICH service builds it and WHERE that file lives; a board surface for a FUTURE date can be built inline on web from the git checkout `[lane ncaaf-kickoff-cache-staleness, session 3692ff18]`
- **The belief:** NCAAF compact cards showed "TBD" because the CFBD games cache went stale with no signal to refresh it. I fixed the staleness rule, deployed refresh-worker, and then -- when the user said not to wait for the daily run -- forced a regeneration with a temporary `SEASON_PROJECTION_REFRESH_INTERVAL_SECONDS=3600` plus a deploy. The generator relaunched (`interval_seconds=3600` in-process 19:52:18Z, NCAAF at ~19:54Z) and the board did not move: still 43 placeholder starts, 42 "TBD".
- **Two facts I had not checked, either of which alone defeats the fix:** (1) `DEFAULT_CACHE_DIR` resolves to `Path(__file__).parents[6] / "data"` -- the repo CHECKOUT (`/opt/render/project/src/data/...`), not the mounted disk -- so a worker-side refresh is thrown away by the next deploy and is invisible to every other service (the path is not in `HOT_ARTIFACT_PATTERNS`). (2) `/api/board/game-chips` returns `source: worker_artifact` for TODAY but `source: inline_artifact_missing` for a date four days out: the upcoming-date surface is built INLINE ON WEB, from WEB's committed copy -- which was still the July snapshot (888 rows, `completed: False` on 888 of 888). The fix that moved the board was re-fetching the COMMITTED file.
- **How to apply:** before deploying a producer fix, answer three questions in this order and write the answers down -- WHICH service builds the surface the user is looking at (read the payload's own `source`/`published_at`, do not assume the worker), WHERE the file it reads lives (checkout vs mounted disk vs keyvalue -- resolve the constant, do not assume `data/` is the disk), and WHETHER anything carries it between services (`HOT_ARTIFACT_PATTERNS`). A forced run is a test of the RULE, never of the surface: it proved the staleness predicate fires and proved nothing about the board. Related: `feedback_presence_is_not_reachability`, `project_keyvalue_artifact_split_blinds_guards`.
## 2026-09-22 — RULE: a check built on an instrument INHERITS that instrument's divergence; before acting on "planned but never done", confirm the counter is produced by the path you are judging `[lane kalshi-spread-line-missing, session 236bd219]`
- **What I believed:** my own census's first alert, written up the same hour -- "kalshi `spreads` has positions every cycle and has NEVER built an order" -- pointed at the venue or the plan data, and I filed it that way (`#683`, first wording: the rows "carry no usable line").
- **What was actually true:** the rows carried signed lines (`2.5`, `-14.5`). `ORDER_PATH` is produced by `verify_order_paths`, a DRY RUN, and that dry run built through a builder the live submitter does not use (v1 `order_body`, which drops the line). The live path builds the same row. The census counted the verifier's verdicts and I read them as the venue's.
- **How I found out:** reading the two call sites of `_side_to_kalshi` (`kalshi_orders.py:239` vs `:471`), then an A/B of one real request through both builders -- v1 REFUSED `spread_line_missing: None`, v2 built `side='bid'`.
- **The rule going forward:** when a derived check says "X is planned and never happens", name the EMITTER of the counter before naming a cause, and ask whether that emitter runs the same code as the thing it describes. For dry-run counters the first suspect is the dry run. State the limitation wherever the check's output is written up.
- **Cost:** one wrong lead and one wrong todo wording, corrected the same day; and a real defect (the verifier lying about a money path) was nearly filed as a venue data gap, which would have sent the next session into `polymarket_us_markets`-style slate archaeology.
- **The check that now enforces it:** `tests/test_kalshi_builder_parity.py` reads the AST of `verify_order_paths` and fails if it imports a builder `kalshi_submitter` does not call. A behavioural test cannot see this -- after the fix both builders accept a well-formed spread.
## 2026-09-22 - RULE: an identity field that is USUALLY ABSENT is not an identity; count how often a key's id slot is actually populated on production data before trusting the key `[lane dh-grading-ledger-joins, session 3692ff18]`
- **What happened:** `live_gameline_ledger.record_key` began `(game_pk, ...)`, which reads as "the game is in the key". It is not: `game_pk` comes from the live-gameline projection and is never set on the segment-refusal path, so production 2026-09-22 had it on **25 of 132 records**. With the slot empty the key is `(None, segment, market, line, books_key)`, and `_moved` deduped ACROSS GAMES on it - 2026-09-20 had 13 keys spanning more than one game, ONE of them covering **14 games**. The doubleheader I was chasing was the small half of this: on 09-04 and 08-29 both halves even shared a real gamePk, because the index that produced it was keyed on the team pair.
- **Why a code reading missed it:** the field is present in the tuple and present in the record shape, and the docstring argued carefully about `line` and `books_key`. Nothing in the file says how OFTEN `game_pk` is None, and that is the whole defect. A test with a populated `game_pk` passes forever.
- **How to apply:** for any dedupe/join key, run a census over real files before trusting it - per slot, what fraction of rows populate it, and how many distinct real entities share one key. Two numbers, one query. If a slot can be absent, either add a field that never is (`event_id` here, present on 132 of 132) or make the absence refuse. Sibling rules: `feedback_read_the_field_you_already_have`, `feedback_unknown_must_not_default_permissive`.
## 2026-09-22 - RULE: "the published numbers did not move" is not evidence a data defect was harmless - a downstream dedupe can absorb it entirely, so go find the window where it was NOT absorbed `[lane dh-grading-ledger-joins, session 3692ff18]`
- **What happened:** the live-gameline ledger wrote a doubleheader's second odds event under the FIRST game's gamePk, with the first game's live state. Replaying `bucket_realised_performance.py` on the production rows for the published window (09-01..09-07, 28,627 rows) with and without those rows produced **byte-identical JSON**: the analysis's own `(bucket, game_pk)` dedupe had discarded all 69. Had I stopped there I would have reported "no impact". The window one week earlier (08-26..09-01, two doubleheaders instead of one) told the opposite story: 359 contaminated rows - 0.77% of the window - moved h2h calibration from 0.501 to 0.492, past the script's 3pp gate, and the analysis **refused the entire window** with `UNMEASURED: no market passed its gate`.
- **Why one window absorbed it and the other did not:** the dedupe protects the BUCKETS but the market-calibration gate runs over raw ROWS, before any dedupe. So the same defect is invisible in one statistic and fatal to another, in the same script. Whether it shows also depends on the slate: one doubleheader's halves happened to have the same winner AND the same margin, two others had opposite winners.
- **How to apply:** when sizing a data defect, replay at least two windows and pick one where the defect is DENSE, not the one that happens to be published. Diff the full output, not the headline. And state which statistic you measured - "the buckets are unchanged" and "the window is reportable" are different claims. Sibling rules: `feedback_null_result_needs_a_live_population`, `feedback_rate_not_count`, `feedback_a_projection_is_not_a_model_edge`.
- **The good news, recorded because it is reusable:** the 3pp calibration gate is what caught this. A gate whose refusal message says "that points at MY join, not the book" turned a silent cross-game join bug into a visible refusal, a week before anyone went looking.
## 2026-09-22 - RULE: a `**[RELEASED ...]**` note does not release a lane claim, and a hand-rolled probe over a guard's parser is not the guard `[lane live-gameline-game-identity, session 3692ff18]`
- **What happened, twice in ten minutes.** (1) I told the user `live_gameline_join.py` belonged to lane `live-edge-basis`. It does not: that lane is CLOSED-VERIFIED since 2026-08-17 (`lanes.md:1367`), and the line I read (`lanes.md:52`) is a guarded-claims note ABOUT the closed lane. (2) I then "checked" with `lane_claims._claims(text)` and printed NONE. `_claims` returns a GENERATOR of `(lane, path)` pairs; I called `.items()` on it inside a comprehension, which yields nothing and raises nothing, so an empty result read as "unclaimed". The real holder was `accuracy-assessment-0914`, and only the lane-guard hook - the same parser, used correctly - said so. (3) After the user approved the take, I annotated the holder's `Files:` line `**[RELEASED ... ]**` and the guard blocked me AGAIN: the parser reads the literal PATH, so an annotation beside it changes nothing. The release needs the path REPLACED by prose, which is exactly what `lanes.md:711` had already done for the artifact publisher.
- **How to apply:** to ask "who holds this file", run the GUARD, or `scripts/check_lane_claims.py` - do not re-implement its parser inline. If you must call `_claims()`, print `type()` and the raw list before drawing a conclusion; a generator consumed wrongly is silent, which is the failure mode that looks most like a clean answer. To release a claim, remove the PATH and keep the prose plus an annotation naming the taker, the decision and the scope.
- **Sibling rules:** `feedback_read_the_field_you_already_have`, `feedback_null_result_needs_a_live_population`, `feedback_compound_absence_claim`, `project_lane_guard_reads_primary_tree` (the guard reads the PRIMARY tree's `.current-lane.<session>` marker - a worktree copy is not enough).
## 2026-09-22 - RULE: "Run now" on a scheduled task EXECUTES its side effects - a task whose prompt writes the ledger cannot be smoke-tested by running it, and the tool-approval it is usually run for may not exist `[no lane, session dc70079c]`

- **What happened:** asked to run a newly created scheduled reading "now, to pre-approve its tools". Its stored prompt ends by writing a findings file, appending a verdict to `deploys.md`, rewriting a `state_layer2.md` subject and pushing to `main`. Run on 09-22 it would have done all of that against ONE slate - **discharging an owed verification with a non-result** - and worse, the existence of `findings_2026-09-29_layer2_fee_net_out_of_sample.md` is the exact signal a LATER scheduled task (`layer2-score-v2-promotion-decision-1006`) keys on to decide whether the 09-29 reading ran. A "harmless test run" would have poisoned the chain it was meant to protect.
- **What was done instead, and it worked:** back up the task's `SKILL.md`; `update_scheduled_task` with a DRY-RUN prompt that exercises every command shape and is explicitly forbidden from writing to the repo or pushing; dispatch; **restore the real prompt while the run is still live** (the session receives its prompt at dispatch, so restoring immediately is safe - confirmed, both runs executed the dry-run text after the file on disk already held the real one); then `diff` the restored prompt against the backup. One run restored byte-for-byte; the other differed by one synonym, which was reported rather than papered over.
- **Exercise the push WITHOUT creating anything:** `git push origin origin/main:main` is a no-op that prints `Everything up-to-date`. A write-nothing dry run otherwise leaves the single riskiest approval unexercised.
- **The measured punchline, and it inverts the premise:** **both dry runs surfaced ZERO permission prompts.** Every command shape was already covered, so the stated goal - pre-approving tools - was a **no-op**. The runs paid for themselves only as diagnostics: `origin/main` moves under a run (1 commit mid-run, 89 that day) so a run must PIN the SHA it snapshotted; `rows=1` is not a size control on `/api/ops/clv/report` (1,074,201 B returned); and the NCAAF registry copy is load-bearing, not precautionary (2,334 of 16,505 records).
- **How to apply:** before "Run now" on any scheduled task, **read its prompt's write section first**. If it writes the ledger, pushes, deploys, or produces a file another task keys on, swap in a dry-run prompt rather than running it. And do not spend a run on tool approval without first asking whether anything actually prompts - verify the approval was recorded, because "I ran it to pre-approve" is a belief until a prompt appears and is answered.
- **Verify the restore and the arm afterwards, both:** `diff` the prompt against a pre-run backup, and re-read `enabled` / `nextRunAt` **after** dispatch - a one-time task could plausibly have had its single fire consumed by the manual run. It did not, but that is a measurement, not an assumption.
- **Sibling rules:** `feedback_verify_the_mitigation_was_applied`, `feedback_confirm_the_code_ran`, `feedback_presence_is_not_reachability`.
## 2026-09-22 - RULE: a pass that rewrites a CONTENDED ledger file must be REBUILT against the tip at push time, never rebased onto it - and `archive_released_lanes.py` writes CRLF on Windows `[no lane, session dc70079c]`

- **What happened, two traps in one pass** (archiving 21 CLOSED lane blocks out of `lanes.md`). **(1) Base drift.** The dry run and its verification ran against `origin/main` `875a9dbc`; by push time the tip was `eddcfb60` and the guard's claim count had moved **163 -> 165** because another session had appended. The commit was refused by an explicit base check, the whole pass was re-run against the new tip, and it landed first try. Pushing the pre-computed `lanes.md` would have silently reverted those two claims - the exact failure `archive_released_lanes.py`'s own docstring records happening before ("another session rewrote `lanes.md` between this session's two appends").
- **(2) CRLF.** The tool writes with `pathlib.write_text`, so on Windows Python translates `\n` -> `\r\n` while the git blob is LF. Hashing the file as written produces a **whole-file rewrite** diff: it hides what actually moved, defeats the 0-deletions gate, and maximises the damage if the push does land on top of a concurrent edit. Measured: 1,408 of 1,408 newlines came back as CRLF.
- **How to apply:** make the WHOLE pass a function of the current tip - fetch, snapshot at a PINNED sha, re-run the tool, re-verify, commit, push, and **on rejection start over rather than rebasing a stale result**. Wrap it in a retry loop so drift costs a rebuild, not a round trip. And `.replace(b"\r\n", b"\n")` before `git hash-object` on anything a Windows Python wrote.
- **The verification that makes it safe is not the tool's own.** Recompute the claim set with `lane_claims._claims` over before and after and compare as a **SET, not a count**; check every line that left `lanes.md` is present in `lanes_history.md`; check the OPEN slug set is unchanged; check the destination file's prior bytes are an exact **PREFIX**. The tool does two of those internally - and its docstring is the source of the rule that "the script said so" is not a measurement.
- **Also recorded, because it sends readers to the wrong file:** `lanes.md`'s `## Archived lanes` heading says "full bodies in `lanes_closed.md`", while `archive_released_lanes.py` writes to **`lanes_history.md`**. Any pointer line must name its destination explicitly rather than inheriting the heading's.
- **Sibling rules:** `feedback_untracked_is_not_new`, `feedback_shell_layer_transcodes_bytes`, `project_shared_tree_commit_recipes`, `project_ledger_commit_guard_race`.
## 2026-09-23 - RULE: a poller that pins `--baseline-read-at` stops meaning anything 15 minutes later, and a poller that only exits on CLEAR will then wait forever `[lane mlb-doubleheader-e2e, session 3692ff18]`
- **What happened:** waiting for a deploy window, I backgrounded a loop running the real `deploy_preflight` every 75s with `--baseline-read-at 2026-09-23T00:26:37Z` pinned. Preflight refuses a baseline older than 15 minutes, so from 00:41:37Z every cycle would have returned **NO_EXPECTATION instead of HOLD or CLEAR** -- and the loop exited only on `CLEAR`. It would have polled all night, printing a verdict that no longer described the thing I was waiting for. Caught it before that point only because I re-read my own command while thinking about something else.
- **Why it is the dangerous shape:** the loop keeps running, keeps printing, and keeps looking like a watcher. Nothing errors. The failure is that the instrument silently switches to answering a DIFFERENT question -- "is your paperwork current" instead of "is the worker busy" -- and the exit condition can no longer fire. Sibling: `feedback_instrument_blindness`, and the 503 the same night where preflight returned UNKNOWN and said so ("an unreadable log is not evidence of a quiet worker").
- **How to apply:** any poll that carries a time-boxed argument must RE-READ it each cycle, not pin it. Print the verdict AND the underlying counters every cycle so a change in what is being answered is visible. And give the loop a terminal branch for every verdict it can receive, not just the one you are hoping for -- an exit condition that can only be reached by success is not a watcher, it is a wish.
## 2026-09-23 - RULE: `check_deploy_safety.py --drain` CANNOT be run from a developer machine, and `deploy_preflight` recommends it anyway `[lane mlb-doubleheader-e2e, session 3692ff18]`
- **What happened:** blocked by an in-flight job tree, I reached for the drain -- the mechanism `deploy_preflight`'s own HOLD text names as "the other way", and the right one, because it stops the worker starting NEW work and waits for the running job to finish instead of killing it. It cannot connect: `SYNDICATE_REFRESH_STATE_URL` is a Render-INTERNAL hostname (`redis.exceptions.ConnectionError: Error 11001 connecting to red-...:6379. getaddrinfo failed`), resolvable only inside Render's private network, and `ops.py` exposes no drain route, so there is no HTTP path either.
- **The tool is not broken -- it refused correctly.** Run without the keyvalue backend it prints `[UNKNOWN] Drain requires the keyvalue backend ... Without it the flag is written to a LOCAL FILE and the production worker never sees it. Refusing rather than pretending.` A weaker tool would have written the local file, printed DRAIN_REQUESTED, and left a session waiting on a flag production never saw. **The defect is that the RECOMMENDATION names a path with no reachable transport from where the recommendation is read.**
- **How to apply:** from a dev machine the only levers on an in-flight job are WAIT or kill; there is no third. To drain, run it from a Render Shell on refresh-worker (`--drain --drain-owner <lane> --drain-wait-seconds N`), deploy into the gap, then `--undrain`. Do not spend the time I did discovering the transport gap. Reading the two state-backend values from Render to configure it locally does NOT help and means handling a credential for nothing -- read them as `<N chars>` if you must confirm, never print them (`feedback_env_api_dumps_secrets`).
## 2026-09-23 - RULE: an artifact NAMED for a model's inputs is not evidence of its inputs until it reproduces that model's OWN output `[lane nfl-total-sum-direction-scale, session dae18452]`
- **What happened:** diagnosing why NFL totals over-disperse, I reconstructed the sim's per-team ratings from `smartsim2_ratings_2025_wk10.json` -- the artifact the generator writes beside the projections, named for exactly those ratings -- and regressed the SAME run's `margin_mean` on them. Slope +0.141, r = 0.215. Recomputing the identical quantity with `_centred_per_game` instead gave +0.521, r = 0.989. Same process, same output CSV, same 14 games; only the reconstruction of the INPUTS differed. The engine is deterministic in its ratings, so r = 0.989 is what a faithful reconstruction looks like and 0.215 is proof the file is not one (`#685`).
- **Why it is the dangerous shape:** the artifact is not corrupt, absent or stale -- it parses, has all 32 teams, carries a plausible `generated_at` and a `rating_source` per club. Every check that asks "is this file healthy" passes. It cost two confidently-wrong intermediate readings before anything looked odd: a production total-slope of +0.77 that is really +0.19, and a claimed rating-sum SD of 27.5 against a true 9.06 -- and the 27.5 sent me looking for an anomaly in the 2026 ratings that does not exist. The tell was not in the file; it was that the reconstruction could not reproduce the output the same run had already written.
- **How to apply:** before drawing any conclusion from an artifact that RECORDS a computation's inputs, close the loop -- predict that run's own published output from them and require a near-deterministic fit (r > 0.95 where the code is deterministic). If it does not close, the file is a description of the inputs, not the inputs. Recompute from source instead. This is `assert the branch, not the outcome` applied to a data file rather than a code path, and it generalises past the NFL sim to any `*_ratings_*.json`, feature dump or `_inputs.json` written alongside the thing it supposedly explains.
## 2026-09-23 — OVERTURNED: "a past-date snapshot that returns data re-ran the scorer" — the board served a 22-day-old RETAINED build, so a missing cut stayed missing `[scheduled task live-gameline-accuracy-snapshot]`

- **What was believed:** that 2026-08-30/08-31 carry no `fresh_quotes_only` brier because the OBSERVER script predated the cut, and that re-requesting 08-30 would return exit 6 (`no data for date`) because the board no longer reaches back that far.
- **What falsified it:**
  - The cut was introduced on BOTH sides in ONE commit, `4d20ea00` (2026-09-01T16:07:41Z): the board scorer (`live_gameline_score.py:681`) and the observer (`snapshot_live_gameline_score.py:239`). It was never observer-only. The invariant holds across all 75 rows then in `history.jsonl` — the 25 captured before that commit lack the key, the 50 after carry it, zero violations either way.
  - The 08-30 backfill returned **exit 0 with 14 games**, not exit 6. But `board_generated_at` was **2026-09-01T04:43:24Z** — a build 11h24m OLDER than the commit that created the cut. `priceable_only` and `all_records` compared byte-equal to the row captured on 2026-08-31. The endpoint served a RETAINED snapshot; it did not recompute.
  - So the cut stayed empty, `fresh_quote_seconds` came back `None`, the pool was unchanged (265 games, +0.00732) and the tool's `COVERAGE GAP` block still named both dates.
- **How to apply:**
  - A past-date snapshot call returns the board's RETAINED score for that date, not a recomputation under today's scorer. Read `board_generated_at` — not the exit code, not the presence of numbers — before treating a backfilled row as current-scorer output. Same family as `feedback_one_endpoint_two_code_paths`: one endpoint, two provenances, and the discriminating field was already in the payload.
  - A field ABSENT from a row dates the CODE THAT WROTE the row; a field present-and-`None` dates the PAYLOAD. Distinguish the two before diagnosing a data gap — here `fresh_quote_seconds: None` was the tell that the board, not the script, lacked the cut.
  - When attributing a missing field to "the observer", `git log -S` the field on the PRODUCER too. `-S` against a single expression can be misled by a later refactor: a 2026-09-08 contract-3 commit also matched and would have dated the introduction a week late.
  - A gap that can only affect dates BEFORE the introducing commit is STATIC — bounded, never growing, and correctly excluded rather than silently averaged in. Recovering it means re-running the scorer offline over the per-record ledgers, which is not what a snapshot call does.
  - *(evidence: scheduled task `live-gameline-accuracy-snapshot`, run 2026-09-23 09:18 CT — itself ~9h45m standby-displaced; `reports/live_gameline_accuracy/history.jsonl` rows for 2026-08-30)*
## 2026-09-23 — FORBIDDEN: writing a dated ledger file (`log/<date>.md`) with a whole-file write. READ IT FIRST AND APPEND -- another session's entry for today is already in it `[session 236bd219]`
- **What happened:** I wrote `.syndicate/log/2026-09-23.md` with `Path.write_bytes(entry)` because I had created 09-22's file the same way. 09-23 already existed: session 3692ff18 had written the MLB board-outage entry that morning. My commit landed as `8 insertions, 44 deletions` -- their entry gone from `origin/main` for two minutes.
- **How I found out:** `git diff --cached --numstat` before the commit message, the same check `shell-layer-transcodes-bytes` prescribes for shared-ledger appends. It printed `8 44` and I read it. Nothing else would have caught it: no hook covers `log/*.md`, and the file is not claimed by any lane.
- **The rule going forward:** every dated ledger file is SHARED and append-only by convention -- `log/<date>.md`, `deploys.md`, `leads.md`, `learnings.md`. Read the existing bytes, append, and gate the commit on **0 deletions** for that path. A whole-file write is only ever correct for a file you just created in the same command, and even then the existence check has to be in the write itself, not in your memory of it.
- **Cost:** none this time -- restored verbatim from `HEAD~1` (`b4cd14d7`, 13 added / 0 deleted against the pre-clobber version). The near-miss is the point: the same code path had a `.exists()` branch on 09-22 and did not on 09-23.
## 2026-09-23 — A SHARED TEST FIXTURE THAT OMITS A FIELD PRODUCTION ALWAYS SUPPLIES CAN HIDE AN ENTIRE DISPATCH

- **What I believed:** that `tests/test_execute_portfolio.py` covering
  `_polymarket_resolve_market` across 9 moneyline tests meant the resolver's
  market dispatch was exercised.
- **What is true:** the shared fixture `_PolyReq` carried **no `market`
  attribute at all**, so `market` read `""` in every one of those tests. They
  ran the fall-through arm -- the team matcher -- and could never have noticed
  that a market with no branch lands there. Production cannot produce that
  input: `_order_from_position` returns None unless `market` is non-empty
  (`pipeline/execute_portfolio.py`, `if not (position_key and event_id and
  market and side and sport)`). The same omission sat in
  `tests/test_polymarket_slate_freshness.py::_Request`.
- **How I found out:** adding a branch keyed on `market` turned 9 passing
  tests red at once, all with `market='' ... reason=no_order_branch_for_market`.
  The fixture had been asserting on a path for a year that no live request
  could take.
- **The rule going forward:** when a stub request/row fixture omits a field
  the production constructor REQUIRES, that is not a harmless default -- it is
  a different input class, and every test built on it is evidence about the
  wrong one. When adding a branch keyed on such a field, a sudden mass failure
  of old tests is the fixture confessing, not the change breaking. Check what
  the real constructor refuses before "fixing" the assertions.
- **Sibling, not duplicate, of `confirm-the-code-ran`:** that rule is about a
  fixture picking a CHEAPER path than production. This is a fixture picking an
  IMPOSSIBLE one, where the tell is not a suspicious speed but silence.
- **Cost:** none -- caught by the change itself, in the same session. Nine
  tests and two files corrected (`abc6d4b8`).
## 2026-09-23 — RULE: a fix whose job is to EMIT a special character must not CONTAIN one — the first draft of the em-dash fix stored a literal U+2014 `[lane lane-open-emits-em-dash]`

- **What happened.** `scripts/lane_open.py` was written to stop lanes being opened with ASCII hyphens instead of U+2014 (two lanes in nineteen hours; `lane_claims.LANE_RE` requires the em-dash, and the session-start digest will not list a hyphen-headed lane as OPEN, so an arriving session sees no claim on its paths). The source was authored as `EM = "—"`. The authoring tool takes JSON arguments and **decoded the escape**, so the file on disk held the raw bytes `E2 80 94`. Measured with `od -An -c`: `E M   =   " 342 200 224 "`.
- **Why that is the defect and not a detail.** The file existed to be immune to transcoding and was storing the exact byte sequence it warns about, under a comment claiming it was written as an escape *"so that no editor, console re-encoding or copy-paste can turn it back into a hyphen"*. One ASCII-fying pass and it silently emits hyphens again — the fix reintroducing its own bug, with its documentation asserting the opposite.
- **The same file had a SECOND instance.** Its success message printed the separator, and the console returned `U+FFFD` on the very first run. `lane-guard.py:158-160` already refuses to print a literal one for exactly this reason — *"an instruction to use U+2014 that arrives as a mangled byte is worse than no instruction at all"*. The precedent was in the adjacent file and went unapplied until it bit.
- **What did NOT catch it.** Ten passing tests. Nor the mutation test — flipping `EM` to a hyphen turned 5 of 10 red and proved the suite load-bearing, but a LITERAL em-dash passes every one of those tests, because it works perfectly until something downstream mangles it. It surfaced only when a restore-from-backup printed `EM = "—"` where an escape had been written, and the bytes were then read directly.
- **How to apply:**
  - Build the character from its CODEPOINT (`chr(0x2014)`), keep the source pure ASCII, and PIN that with a test asserting zero bytes `> 127` in the file (`test_source_is_pure_ascii`). A comment promising ASCII is not a constraint; a test is.
  - Never print the character in the tool's own output. Print its NAME (`"U+2014"`).
  - **Check the BYTES, not the rendering.** A terminal, an editor and a diff all display `—` whether the source holds the literal or produces it. `od -An -c` / a `b > 127` scan is the only discriminator, and rendering is what makes this invisible to review.
  - Authoring tools that take JSON arguments decode `\uXXXX` into the character. To write the escape through one, escape the backslash — or better, do not want the escape.
  - Generalises past em-dashes: any tool whose job is to emit a byte sequence the surrounding stack is known to mangle — BOMs, CRLF, tabs, NBSP, RTL marks — should construct it, not contain it. Related: `feedback_shell_layer_transcodes_bytes`.
  - *(evidence: `49b8881b` the fix, `fdfe579f` the close; lane `lane-open-emits-em-dash` in `lanes.md` carries the full verdict)*
## 2026-09-23 — RULE: when a number cannot be explained, look at what the upstream response ALREADY contains before adding a call, a model, or a hypothesis `[lane polymarket-balance-detail, session 236bd219]`
- **What I believed:** polymarket's $6.12 gap between cash and buying power needed either a new positions endpoint or an inference from our own order ledger. I had written the leading candidate into the lead: collateral on NO positions via `pendingWithdrawals` / the $1-per-contract hold.
- **What was actually true:** the `/account/balances` response we fetch EVERY CYCLE carries 19 fields, one of which is `marginRequirement` = **6.12**, matching the gap to the cent. `pendingWithdrawals` was 0. We were storing 4 of the 19 and discarding the rest, so the answer had been arriving all day and being thrown away.
- **How I found out:** persisting the other 15 fields -- no new venue call, no new credential, ~90 lines including tests -- and reading the first stamp after the deploy.
- **The rule going forward:** before proposing a new call or a derived estimate for an unexplained number, print the FULL key set of the payload you already receive. Keep key names even when you do not keep values: a complete key list is what makes an ABSENCE provable, and it is the difference between "the venue does not tell us" and "we never looked".
- **Cost:** none realised -- but the lead I had already filed named the wrong mechanism, and a session picking it up would have started on a positions endpoint that was never needed.
## 2026-09-23 — RULE: where a JOIN chose the row, the ORDER path must use the JOIN's own decoder. Four separate money-path defects this week were all "two implementations of one question, and the money side held the weaker one" `[lanes layer2-score-outcome-calibration / kalshi-spread-line-missing / polymarket-h2h-nickname-sides, session 236bd219]`
- **What we believed each time:** a venue data gap. The refusal tokens say so -- `market_unresolved_for_position`, `spread_line_missing`, `team_side_not_in_outcomes` all read like "the venue did not give us what we need".
- **What was actually true, four times:** (1) `#682` Polymarket player props -- the resolver had no branch, while `polymarket_board_join._parse_player_prop` decodes the slug. (2) `#683` Kalshi spreads -- `verify_order_paths` built through v1 `order_body`, which drops the line, while the live submitter passes it. (3) corners (`abc6d4b8`, another lane, from the same census alert) -- no Yes/No total branch, while the join's `gt` token pins the polarity. (4) h2h nicknames -- `_side_for_team` resolves none of `['Buffaloes','Bears']`, while `team_aliases.teams_match` -- the matcher that CHOSE the slug -- resolves both uniquely.
- **How we found out:** the census (`scripts/venue_order_family_census.py`) turns "planned every cycle, never ordered" into a named line; then, in each case, running the two implementations over the SAME production row and comparing.
- **The rule going forward:** when the board join has already matched a row to a venue contract, the order path may not re-derive that match with its own logic. Import the join's decoder, and where the join applies a UNIQUENESS rule, carry the uniqueness too -- it is the safety property, not a detail. If the join's helper is private (`_parse_player_prop`, `_greater_than_line`), import it anyway and say why; a second implementation that can disagree with the one that chose the row is the defect.
- **Cost:** Polymarket player props were unplaceable for as long as the prop join had produced matches; Kalshi spreads were reported unplaceable on 117 position-passes in one day; h2h ran at 12 builds of 58. All silent, all with passing tests, all reading as venue problems.
## 2026-09-23 - FORBIDDEN: shipping a change because every point estimate favours it, when not one of them clears its own standard error `[lane smartsim2-total-nonlinearity, session dae18452]`
- **What happened:** `#686` removes a response the engine has and reality does not -- mechanism-correct, measured causally, defensible on first principles. The user's instruction was "ship it if both improve". Both DID improve on point estimate. Paired on 272 held-out games: the correction alone -0.076 +- 0.172 (t=-0.44), the re-fitted level -0.071 +- 0.072 (t=-0.99), both together -0.147 +- 0.185 (t=-0.79), better on **139 of 272 -- a coin flip**. And the bucket live in September, weeks 2-4, went the WRONG WAY at +0.531 +- 0.475. A literal reading of "both improve" said ship; the evidence said nothing had been shown.
- **Why it is the dangerous shape:** a mechanism-correct change is the easiest kind to ship on a null, because the causal story does the persuading and the statistics are treated as confirmation. It also had a SECOND cost that only appeared when looked for: the correction drove wk10's model total SD to 1.58 against a market ~4.2, i.e. a model too timid to disagree -- the same `2.6x too little differentiation` pathology this repo already has a subject for, reached from the other side. Correct-and-useless is a real outcome and it does not announce itself.
- **How to apply:** an instruction to ship on improvement is an instruction to ship on a MEASURED improvement. Before shipping, state the standard error next to the delta and the win RATE next to the mean; if the interval spans zero and the win rate is ~50%, report that and ship nothing, whatever the mechanism says. Landing it DISABLED with the measurement attached is the move -- it keeps the work and refuses the claim. `feedback_rate_not_count` is the sibling rule; this is its decision-time half.
## 2026-09-23 - RULE: build a ledger append from `git show HEAD:<file>`, not from the working copy, and gate it on `--numstat` `[lane smartsim2-total-nonlinearity, session dae18452]`
- **What happened:** appending two lines to `lanes.md` produced a **1,524 / 1,522** diff -- the whole file rewritten. `.syndicate/*.md` is STORED as LF and CHECKED OUT as CRLF, and an earlier session had rewritten the file, so the separator I had used successfully hours before was now wrong. Two spliced separators landed as bare LF inside a CRLF body, and git saw every line as changed.
- **Why it matters here specifically:** these files are shared, append-only, and read at every session start. A whole-file rewrite in a lanes/deploys commit is indistinguishable from a destructive edit at review time, and the ledger-commit guard gates on exactly that.
- **How to apply:** read the bytes you are editing from `git show HEAD:<path>`, detect the separator from THAT blob (not from the working file, not from memory), splice, write. Then run `git diff --numstat` and refuse to commit unless the numbers are the ones you intended -- 2 added / 0 deleted for a two-line append. The numstat check is what caught this; nothing else would have.
## 2026-09-23 OVERTURNED: “lanes.md is over cap, so archive its CLOSED lane blocks” `[scheduled task archive-closed-lanes-0917, session 8a815e5b, no lane]`

The job was scheduled every 2 h on that premise and moved 3, 0, 0, 0 blocks. The premise was arithmetically
impossible and nothing in the loop checked it. Measured on origin/main 2026-09-23: OPEN blocks are **423,218 B of
524,327 B (80.7%)** across 41 lanes; CLOSED is **25,886 B (4.9%)** across 3. Archiving EVERY CLOSED block leaves
~498 KB against a 234 KB cap — still 2.1x. The reclaimable mass is 7 OPEN lanes dormant on both clocks: 95,379 B,
3.7x the entire CLOSED population.

**RULE: size a cleanup job against the segment it can actually touch BEFORE scheduling it, and record that
denominator in the job itself.** Four runs of 0 read as “the system is working” — and that reading was even true —
while the file grew 4,366 B in 40 minutes from a segment the job was forbidden to touch. A repeatedly null job is
evidence about its TARGET, not only about its subject.
## 2026-09-23 FORBIDDEN: calling a lane ABANDONED from its owner session's idleness alone `[same session]`

`bandwidth-controlled-transfer` is the single largest block in lanes.md (68,525 B, 13% of the file). Every session
id in its header was idle **7.0 days**. The block had been modified **0.2 days** earlier, by a session the header
does not name. An owner-idle test alone would have flagged the most actively-written lane in the file as dormant.

**RULE: dormancy needs BOTH clocks — owner transcript idle AND `git blame` committer-time on the block's own lines.**
This is the same failure `owner_liveness.py`'s last-modifier check was added for on 2026-09-18
(`fotmob-team-name-aliases`, closed by a session it never named); it was fixed there for CLOSED blocks and
re-appeared the moment a new reader looked at OPEN ones. A header names who OPENED a lane, never who is writing it.
## 2026-09-23 - RULE: a monitor must compute its metric the SAME WAY as the baseline it is judged against, and the estimator must be written down next to the number `[lane nfl-total-sum-direction-scale, session dae18452]`
- **What happened:** a scheduled board check re-read a board whose artifact had NOT rebuilt -- byte-identical input, so the model column could not have moved -- and reported total SD **4.61** against a **4.47** baseline, margin 5.46 vs 5.29, and annotated the market as `2.59 (was 2.51)` as though the lines had moved. Nothing had. It used the SAMPLE standard deviation (ddof=1); the baseline used the POPULATION one. On n=16 that is exactly `sqrt(16/15)` = **3.28%**, and all four figures matched that factor to within 0.012.
- **Why it is the dangerous shape:** it is SELF-CONSISTENT. Every run would report the same +3.28%, so it never looks like a bug -- it looks like a small steady drift away from a fix, which is the most plausible-sounding kind of wrong. The first REAL regression then arrives as "a bit more of the usual drift" and is the one nobody chases. A wrong number gets caught; a wrong ESTIMATOR gets normalised.
- **How to apply:** when a baseline is recorded for something to be monitored against, record the estimator beside it (`pstdev`, ddof=0) and pin it in the monitor's own instructions. And give the monitor the invariant, not just the method: *if the input did not change, the output CANNOT have changed, so a difference is yours*. The re-run that confirmed the fix said exactly that in its own entry, which is how the instrument confirmed itself rather than being taken on trust. Sibling: `feedback_measure_same_instant` -- same class, different axis.
- **Also, from the same runs:** `list_task_runs` reports `status: "running"` for a scheduled run that finished its work and committed ten minutes earlier -- the field tracks the SESSION being open, not the task being done. Do not read "running" as "still working"; the commit and the notification are the completion signals.
- **ADDENDUM `[lane nfl-total-sum-direction-scale, session f09f27bf, the run this entry is about]`: the reason it produced a false CAUSE and not merely a false number.** The factor is applied to every SD in the report, so the MODEL and MARKET columns inflate by the same 3.28% and appear to move together -- and co-movement is precisely the signature of "market lines shifted while the model held". The run therefore had a ready, plausible mechanism to attribute the difference to, wrote `2.59 (was 2.51)` as market drift, and stopped looking. A scale error on a shared estimator does not present as noise; it presents as a CORRELATION, and a correlation invites an explanation. **So: the invariant above is not a sanity check to run when something looks wrong -- it must be run BEFORE the difference is explained, because a difference that has already been explained is never re-examined.** Concretely, on identical input bytes the recompute matched the baseline on 4 of 4 to the reported precision (4.47 / 2.51 / 5.29 / 4.86); the one number that could not have moved, the model SD, was sitting in the report having moved, and that alone settles it without any statistics at all. Sibling: `feedback_read_the_field_you_already_have`.
## 2026-09-23 — A NOTATION THE LEDGER USES IS NOT A NOTATION THE PARSER HONOURS, AND ONLY THE PARSER DECIDES

- **What I believed:** that a claim written in `lanes.md` guards the thing it
  names. Everyone writing one believes this; it is why they write it.
- **What is true:** three different spellings guarded NOTHING, for months, and
  no instrument said so. `.../event_simulator.py` (an elision a human reads
  instantly and `matches` cannot resolve). `tests/fixtures/settlement_player_box/`
  (the conventional trailing slash, which `_norm` stripped, turning a directory
  into a file that cannot exist -- 0 of 6 files guarded). And a whole class in
  the other direction: prose CITING a file under a `- Files:` line became a
  claim, so a lane "held" files it had only mentioned, and one such phantom
  blocked a real edit today.
- **How I found out:** a claim I had to TAKE under a user decision turned out
  to be a citation; auditing for siblings turned up the elisions; auditing
  those turned up the directory. Each was found by fixing the one before it --
  none by the checks that run every session.
- **The rule going forward:** when a guard reads human-written notation, the
  notation and the predicate are two halves that must be TESTED AGAINST EACH
  OTHER, the way this repo already insists for two guards that must agree. The
  cheap version is a census: for every claim, does it match at least one real
  file? That question takes one pass over `git ls-tree` and would have found
  all three the day they were written.
- **And the audit itself needs the same scepticism.** My first census reported
  a `(NEW)` file reservation as a dead claim -- "no tracked file matches" is
  not "guards nothing", and a prospective claim starts working the moment the
  file exists. An audit that conflates the two reports a working reservation
  as a defect.
- **Failure direction, stated because it decided the method:** tightening a
  claim parser DROPS claims, which unguards files and stops nobody -- silent.
  So every change was measured against the live ledger BEFORE shipping, and
  that is the only reason an early cut that dropped three real test-file
  claims was caught rather than deployed.
### 2026-09-24 - FORBIDDEN: writing a watcher or guard whose predicate matches on how a state PRINTS rather than on what it MEANS

- **What we believed:** that polling a CLI for a known phrase is a fine way to
  detect a state. Four separate times in one session it was not.
- **What was actually true, four times in one session (lane `nhl-ncaab-club-maps`):**
  1. A claim watcher polled for the literal token `free`. An expired claim prints
     `EXPIRED (does not block)` -- acquirable, different words. The claim freed at
     01:02:48Z and the loop sat through it to its own deadline, ~3 min wasted.
  2. An auto-deploy script found its window, then ABORTED on its own guard: it
     tested for `"held by YOU"` (which is `deploy_preflight`'s phrasing) while
     `deploy_claim.py acquire` prints `HELD by <lane>`. The claim was already mine.
  3. `Path.read_text` does universal-newline translation, so a CRLF ledger file was
     read as LF and written back as LF -- an EOL rewrite nobody asked for. (Harmless
     only because `.gitattributes` normalises; the alarm was mine too.)
  4. A `render_logs.py --text` filter was written as a regex alternation
     (`A\|B\|C`) against a tool that does LITERAL substring matching. "nothing
     matched" was read as "no sim running" -- a null result from a query that could
     never have matched anything.
- **How we found out:** each one surfaced only because a second, independent reading
  disagreed with the watcher -- a manual `status`, a hand-run preflight, a byte-level
  diff, a re-run with a single substring.
- **The rule going forward:** gate on the EXIT CODE, the parsed field, or the byte,
  never on a phrase. When only text is available, assert the match is non-empty
  before trusting a negative -- `absent signal` is a fact about the matcher until
  proven a fact about the world. And a tool's `--text` is literal unless its own
  help says otherwise.
- **Cost:** ~4 minutes and one aborted deploy trigger; no wrong number reached the
  ledger, because every one was caught by a disagreeing second reading rather than
  by the watcher itself. That is the part that does not generalise -- a watcher
  nobody double-checks fails silently.

---
## 2026-09-24 FORBIDDEN: stating a deploy expectation as a COUNT when the population it counts can change size between the baseline and the verify `[lane mlb-live-gameline-venue-freshness, session 4ab694ed]`

`deploy_preflight.py --expect` records a prediction on the receipt, and it is
what a later reader uses to decide whether the deploy worked. I wrote
`live_gameline_join_mlb_stale_refusals=lt_110` against a baseline of 110.

Post-deploy it read 57 / 43 / 48. The expectation PASSES, literally, and the
deploy did nothing. The count fell because the MLB slate was ending -- the same
builds show `considered` 603 -> 332 and the live-lens index 10 -> 6. Against
the denominator that matters, full-game rows the join actually considered, the
refusal rate is 100% / 100% / 87.7% after and 100% / 94.7% before. Nothing
moved.

**The receipt would have recorded a success that is not one**, and it would
have been believed, because a receipt is exactly the artefact a later session
reads instead of re-deriving. `learnings.md` already carries "A rate, not a
count" for findings; this extends it to the PREDICTION, which is worse, because
a finding gets re-examined and a discharged expectation does not.

HOW TO APPLY: if the population can change size -- a slate ending, games going
final, a window narrowing -- the `--expect` field must be the rate, or a pair
(numerator AND denominator) so the reader can compute it. "Fewer refusals" is
not a prediction when the thing being refused is also disappearing.

---
## 2026-09-24 FORBIDDEN: overriding your own local probe with a production number you have not tied to your change by TIME `[lane mlb-live-gameline-venue-freshness, session 4ab694ed]`

I probed `_key_claimants` locally and it returned an EMPTY set for a club key,
which means `_unconfirmed_on_a_contested_key` returns False for one and that
guard cannot reject it. I then saw `AMBIGUOUS_UNNAMED_REJECTED sport=mlb` go
0 -> 166 in production shortly after my commit went live, called it "my new
keys are matching and the guard is rejecting them", reported it, and BUILT A
SECOND FIX on that reading.

Both halves were checkable and I checked neither before reporting:

- **The clock.** The jump is at 01:51:37Z. The deploy went live at 02:06:45Z --
  FIFTEEN MINUTES LATER. "Shortly after" was never verified against the
  deploy's own `finishedAt`.
- **The control.** The Render deploys API shows NO deploy on refresh-worker or
  live-odds-worker between 19:37:21Z and 02:06:32Z. No code changed at all in
  the window where the counter moved, so nothing of mine could be responsible.

The local probe was RIGHT and I discarded it because the production number felt
more authoritative. A production reading is more authoritative about PRODUCTION;
it says nothing about CAUSE until it is tied to the change by time and by a
control.

HOW TO APPLY: before attributing any counter movement to your deploy, print the
deploy's `finishedAt` next to the first moved sample, and enumerate every deploy
on every service in the window. If a local probe contradicts the attribution,
the probe is a falsification test -- run it down rather than outvote it. And
when a reading is withdrawn, withdraw everything built on it in the same breath:
retraction is not innocence, and the follow-on fix I had already written had to
be re-justified from scratch on different grounds.

---
## 2026-09-24 -- A WORKTREE DIFF IS EVIDENCE ABOUT ITS BASELINE, NOT ABOUT ITS AUTHOR: a FRESH diff from a LIVE session attributed 310 of upstream's own lines to it `[scheduled task archive-closed-lanes-0917, session ac238d51, no lane]`

- **What I believed.** That after the two 2026-09-23 fixes -- `changed_lines_only()` for context
  lines, and `--diff-stale-min` for abandoned WIP -- "worktree holds an uncommitted `lanes.md` diff
  naming this slug" was a trustworthy live-owner signal. Both fixes were measured, both were right,
  and I read them as having closed the family.
- **What is true.** They closed two mechanisms of three. Today `owner_liveness.py --idle-min 240`
  returned `SAFE_SLUGS=` empty on **6 of 6** CLOSED blocks, and one worktree
  (`tripwire-applog-page-cap`) was the reason on all six -- including three whose owners were idle
  722-866 m and whose blocks were last modified 738-881 m ago, i.e. past both 240 m clocks by 8-14
  hours with nothing else against them.
- **Why neither guard fired, correctly.** That worktree's `lanes.md` was written 8.4 h ago, so the
  3-day staleness bound treats it as fresh -- and it IS fresh. Its session was idle 17 m, so it is
  live -- and it IS live. The slugs appear on real `+`/`-` lines, not context, so the narrowing does
  not apply either. Every guard gave the right answer to the question it was asked.
- **The question none of them asked.** Its HEAD is **134 commits behind `origin/main`**. A diff
  against a stale baseline renders upstream's edits as the worktree's own. Classified against
  `origin/main`'s copy: of 310 changed lines, only **13 `+` lines are novel**, and all 13 are OLDER
  versions of two lanes that upstream has since CLOSED. Each of the three blocked slugs was named by
  **exactly one** line, a `+` whose text is **byte-identical to `origin/main`**.
- **How to apply.** When a diff is used as evidence that someone is WORKING on something, the
  baseline is part of the claim. `git diff HEAD` answers "how does this tree differ from the commit
  it was cut from", which on a stale checkout is mostly a question about upstream. Compare the
  changed text against the CURRENT shared tip before attributing it to the worktree's owner: a line
  already on `origin/main` cannot be that session's pending work, and a session that edits a block
  to exactly what upstream already says has made a no-op edit, so the narrowing cannot hide real work.
- **Do not fix it by widening the staleness bound.** That bound separates abandoned WIP from live
  work and was measured for exactly that. This case is a live session with a fresh file; moving the
  bound would discard true signals to suppress a false one. Same shape as
  `gate-on-the-output-not-the-input`: the guard encoded an assumption about HOW a diff goes wrong.
- **Sibling of `untracked-is-not-new`.** There, `??` meant "not in MY index" and was read as "new".
  Here, a `+` line means "not in MY HEAD" and was read as "authored here". Both are statements about
  the reader's baseline that look like statements about the file.
- **Cost:** none yet -- 3,297 B of eligible lane blocks deferred one cycle, and the deferral is the
  gate being conservative, which is the correct failure direction. The cost would be unbounded if the
  worktree is never committed: while it sits there, NO CLOSED block in `lanes.md` can be archived by
  that job, whatever its age. Reported, not patched (the task file reserves tool changes).

---
### 2026-09-24 - REPEAT of `a null result needs a live population`: I sampled only the side of a window where the frame COULD NOT be non-null, and nearly skipped a real deploy

- **What we believed:** that web's inline chip path was UNMEASURABLE, so a `web`
  deploy of the club maps had no stated expectation and should not be made. I
  wrote that into `deploys.md` at 14:00:48Z as a finding.
- **What was actually true:** the inline path was measurable and the fix was
  VISIBLY MISSING on it. `/api/board/game-chips` serves the worker's artifact for
  a current date and builds chips inline on web otherwise. I tested only FORWARD
  dates (2026-09-26, 09-29), which return `inline_artifact_missing` with **zero
  chips of any sport** because no slate exists yet -- a frame that could not have
  been non-null. PAST dates run the same code over a real slate: 2026-09-22 served
  **nhl 0/10** keyed and 09-20 **0/7**, while mlb/nfl/soccer/wnba were complete in
  the same responses. Every archived NHL date was still showing the original defect
  after refresh-worker was fixed.
- **How we found out:** the user asked for the deploy anyway. Looking for an
  expectation a second time, with past dates in the window, produced one in a
  single request.
- **Why this is a REPEAT and not a new rule:** `learnings.md` already carries *a
  null result needs a live population -- prove the frame could have been non-null*.
  The forward dates had no games at all. The rule was right, known, and written
  down, and I still did not apply it, because "I checked the inline path" FELT like
  a population check while being a check of two empty days.
- **The rule going forward, sharpened:** when a probe returns nothing, name the
  population it ran over BEFORE concluding anything -- and if that population is
  zero, the probe has measured nothing at all. A window has two sides; sampling one
  is not sampling the window.
- **Cost:** nearly a skipped deploy that mattered. Zero once corrected: the
  correction is recorded in `deploys.md` beside the original claim rather than
  replacing it, so both readings stay visible.

---
## 2026-09-24 — A VENUE'S BALANCE STATE IS A SAMPLE, NOT A PROPERTY, AND I REPORTED ONE AS THE OTHER

- **What I said, to the user, on 2026-09-23:** "both venues refuse every live
  order on `insufficient_venue_balance`" -- offered as the standing state of
  the world, and used to argue that a deploy enabling a new market family was
  a smaller change than it sounded.
- **What is true:** that was a reading of two passes, 15 minutes apart, on one
  evening. Polymarket has placed 5 orders today. Only KALSHI is
  standing-dormant, and only because the user decided not to fund it. The
  balance moves on its own: measured 09-24, polymarket went 0.13 -> 1.39 ->
  0.31 (an NCAAF total took 1.05) -> 6.59, all inside three hours.
- **How I found out:** the census's PLACEMENT line the next day read
  `polymarket ... placing ... placed=3`, flatly contradicting what I had told
  the user the evening before.
- **The rule going forward:** a venue's cash, buying power, rate-limit state
  or dormancy is a SAMPLE with a timestamp, never a property to reason from.
  Say "at 16:01Z polymarket refused 4 of 4 on balance", never "polymarket
  refuses on balance". The difference decides whether a reader treats a
  deploy as inert.
- **The one exception is a stated DECISION,** which is a property until it is
  revoked: kalshi is unfunded because the user said so, and that survives any
  single reading.
- **Cost:** a wrong characterisation of a live-money deploy's blast radius,
  given to the user before they authorised it. Corrected in `deploys.md` the
  next day. Sibling of `re-baseline before judging`: there the stale number
  was someone else's, here it was my own, 18 hours old.

### 2026-09-24 (session 25e0f859, lane live-gameline-rescore-0830-0831) — FORBIDDEN: reading a past date's RE-CAPTURE as a recompute. The board serves a RETAINED summary, so every field the scorer gained later is permanently absent for that date — and the missing cut FREEZES the pool rather than shrinking it
- **What happened.** 2026-08-30 and 2026-08-31 had outcomes but contributed nothing to the `fresh_quotes_only` pool. One of them had been re-captured as recently as 09-23 and still came back empty, which reads like "that night had no fresh quotes". It is not: **`/api/board/book-grid?date=<past>` re-serves a STORED score object**, so a date summarised before a cut shipped can never acquire it, no matter how many times it is captured. These two are the only dates summarised inside the ~47h window between `75cf9aec` (2026-08-30 11:59 CDT, added `scored_markets`) and `4d20ea00` (2026-09-01 11:07 CDT, added `fresh_quotes_only`).
- **The field that settles it, and it was already in the row.** The 09-23 re-capture carries `scored_markets: ['h2h']` — a post-`75cf9aec` field — while `fresh_quote_seconds` is **None**. `live_gameline_score.py` sets that to a CONSTANT unconditionally, precisely so a null can never be ambiguous (its own docstring says so). A null there proves the scoring function never ran. Do not infer vintage from dates when the payload carries a constant that dates itself.
- **Absent vs null is the tell, and they have DIFFERENT causes.** The ORIGINAL 08-30/08-31 rows have `fresh_quotes_only` **absent** (the observer script predated the passthrough); the 09-23 re-capture has it **null** (the scorer that produced the summary predated the cut). Absent dates the OBSERVER, null dates the SCORER. Collapsing them is the same mistake that once misclassified these exact two dates and silently halved the poolable sample.
- **The data was never missing.** `quote_age_seconds` is present on **100%** of records (5,904/5,904 and 8,161/8,161); `live_gameline_ledger.py` has stamped it since `7e1d0cac` (2026-08-15). Re-scoring the raw per-record ledger with the CURRENT scorer recovered both dates.
- **Rule.** Before concluding a date "has no data" for a metric, check whether the metric POSTDATES the stored summary — compare the metric's introducing commit against the date, and look for a constant-valued provenance field reading null. Then go to the per-record source, which is usually older and richer than the summary built from it. And when a cut is empty for some dates, remember `best_per_date` SKIPS them: the pool does not shrink, it freezes at whatever it last contained.
- **Corollary, and it is the part that nearly shipped wrong: to reproduce a past measurement you need the board's POPULATION, not the fullest one.** StatsAPI lists 12 finals for 08-31; the board scored 11. Scoring all 12 yields a perfectly plausible +0.03591 (n=458/412) that is NOT comparable with any neighbouring date. A leave-one-out search over the 12 found exactly ONE game reproducing the retained figures — `824314` BAL @ COL, first pitch 00:1xZ, which finished after the board's last build. Same shape as 2026-09-08, where a 09-04 reconstruction resolved 15 games against the board's 13 and reported +0.06352 for the board's +0.07827.
- **How to apply.** A backfill that reconstructs a published number must GATE on reproducing that number exactly — briers to full precision AND row counts — and REFUSE otherwise, rather than print a warning next to a plausible figure. `scripts/rescore_live_gameline_date.py` exits 4 on mismatch and 3 if no expectation is supplied; both refusal paths were exercised before the passing one was trusted. Stamp reconstructed rows (`rescored_from_ledger`, source sha, scorer commit, excluded ids) so a reconstruction is never read as an observation.

### 2026-09-24 (session 25e0f859, lane live-gameline-rescore-prefix-window) — FORBIDDEN: quietly substituting a weaker check when a backfill's strong gate cannot be met. Weaken it EXPLICITLY, record on the row what was actually verified, and make the consumer SPLIT on that — a pool must never average two populations of its own independent unit
- **What happened.** Recovering `fresh_quotes_only` for 08-20..08-29 needed the gate that had worked two dates earlier: reproduce the retained `all_records` exactly, which proves the re-score is the board's own measurement. It cannot be met for these dates and never will be. Their retained figures came from the PRE-FIX scorer, which the current one will not reproduce BY DESIGN. Replaying the actual pre-fix code (`ad4bc5c6`) does not rescue it either: that scorer keys finals on `game_pk` OR `event_id` off the BOARD GRID, and `findings_2026-09-08` had already measured that the served grid no longer rebuilds that index (0 entries against the server's own `finals_seen: 2598`). On 08-29 the replay matches `records_considered` **5554/5554 exactly** and still yields 15 games / n=5380 against the retained 16 / 4917.
- **The tempting move is to score them on StatsAPI finals and append the rows.** They look exactly like their neighbours. They are not: `score_live_gameline_offline.py` measured the board's index at **143 games over 08-20..08-31 where StatsAPI gives 157**, and the shortfall lands on whichever games upstream score-nulling touched — a BIASED selection, not a random sample of the same thing. Two selections of the independent unit averaged into one headline is the same error as pooling across scorer eras, one level down, and `pool()` already refuses that.
- **Rule.** When the gate that makes a reconstruction trustworthy cannot be met, do not lower it silently. (1) Make the weaker anchor a SEPARATE, named option that refuses unless the caller also declares what is now unproven — here `--expect-records-considered` proves only that the same LEDGER was scored and exits 3 without `--finals-population statsapi`. (2) Stamp the row with what it actually used. (3) Teach the CONSUMER to split on that stamp and print both sub-pools, so the weaker rows can never be read as the stronger ones. Absent may map to the strong value only when that is true BY CONSTRUCTION (every ordinary capture reads a board build, so absent IS `board`) — never as a convenience.
- **Corollary on lane goals.** A goal can carry a verification clause that turns out to be impossible. That is `GOAL: NOT MET` plus a finding — not licence to swap in a weaker check and call it MET. Here the impossibility WAS the main result, and it is now the reason nobody re-attempts this the same way.
- **A refusal is a measurement.** The three dates the anchor rejected are worth more than the seven it passed: `08-24` anchors fine and has ZERO rows at the 120s cut (genuinely empty at the fresh cut, not frozen — now an honest coverage gap); `08-28` fails ordinarily (capture taken mid-slate, 6,466 vs 6,534); and `08-20`'s capture read **4,817 records where the ledger serves 4,809 TODAY** — an APPEND-ONLY ledger that shrank by 8. Nothing else was looking at that, and only a gate that refuses could have surfaced it. See `leads.md`.
## 2026-09-24 — A NARROWING FILTER THAT RETURNS THE WRONG SHAPE DOES NOT NARROW ITS PREDICATE, IT VOIDS IT — and a voided guard looks like the fix working spectacularly well `[lane archive-diff-baseline-echo, session ac238d51, caught pre-merge]`

- **What I was doing.** Inserting `drop_upstream_echoes()` into the lane-archive gate between
  `changed_lines_only()` and its consumer, to stop a stale-baseline worktree diff blocking CLOSED
  lanes. A pure narrowing change: drop some lines, keep the rest.
- **What I wrote.** A list comprehension taking and returning a **list** of lines, because that is
  the shape the logic reads most naturally in.
- **What the pipeline actually passes.** `changed_lines_only()` returns the lines **joined into one
  string**, and both call sites then ask `slug in text`. Handed a string, my comprehension iterated
  it CHARACTER BY CHARACTER and returned a list of single characters. `slug in <list of one-char
  strings>` is False for **every** slug, always.
- **So the guard did not get narrower. It stopped existing.** Every CLOSED block would have read
  SAFE, and the archiver would have moved lane blocks whose owners were mid-edit — the exact
  incident the whole worktree check was built for on 2026-09-15. I set out to reduce false positives
  and my first draft removed all true positives instead.
- **The failure mode presents as SUCCESS, which is why nothing else would have caught it.** A
  too-permissive gate prints MORE `SAFE` and archives MORE blocks. Running it and eyeballing the
  output would have shown the three stuck slugs cleared — the exact result I was hoping for, with
  five more beside them — and I would have read that as the fix working better than expected. No
  exception, no log line, no diff in the shape of the output.
- **What caught it:** one unit test asserting the CONSUMER'S predicate rather than the function's
  logic — `assert "beta-lane" in out` on a line that must survive, plus `isinstance(out, str)`. The
  logic tests all passed against the list version.
- **How to apply.**
  - When inserting a function into an existing pipeline, the contract is **the shape the next
    consumer requires**, not the shape the logic reads well in. Read the consumer, not the producer.
  - Test the consumer's actual predicate. Here that is `slug in out`, not "the right lines came back".
  - **For anything whose job is to say NO, ask what a bug makes it say.** A guard fails toward YES,
    and YES is silent. State the permissive failure explicitly and write the test that fails on it.
    Same family as `unknown-must-not-default-permissive`, but the cause is a TYPE, not a branch.
  - Sibling of `confirm-the-code-ran`: there a fixture picked a cheaper path and the failure looked
    like a *good* result (80x too fast). Here a shape error makes a guard look maximally effective.
    Both are cases where the wrong answer is the one you were hoping to see.
- **Cost:** none. Caught pre-merge, pinned by `test_returns_a_string_not_a_list`, and the reason is
  in the function's own docstring so the next editor cannot re-introduce it blind.

---
## 2026-09-24 - RULE: a hypothesis can be RIGHT about the defect and WRONG about it being the BOTTLENECK, and fixing a real-but-non-binding defect measures IDENTICALLY to shipping something broken `[lane mlb-live-gameline-venue-freshness, session 4ab694ed]`

I diagnosed that the grid venue re-price -- the only pass whose re-stamped age
`attach_live_gamelines` can see -- spoke ROLE keys while Kalshi keys a moneyline
by CLUB. That diagnosis was CORRECT. `404d2194` fixed it and production moved by
nothing, and I spent the next several hours treating "no effect" as evidence the
fix had not REACHED, hunting for a guard eating it, and mis-attributing a
counter to it.

The instrument settled it the other way. The club shape is **healthy**: pregame
24 offered / 24 present / 24 taken / 24 repriced -- every h2h side on a 12-game
slate. It was never the bottleneck. Of 427 live sides only 23 find a venue quote
at all and **17 of those 23 are refused for SEGMENT MISMATCH**, because the
venues quote FULL-GAME contracts while the live board is mostly first3/first5.

**The two situations are indistinguishable from the outcome metric alone.** "The
fix did not reach" and "the fix reached and something else is the constraint"
both read as a flat line, and only the first one tempts you to keep fixing the
thing you already fixed.

HOW TO APPLY: before shipping a fix for a constraint you have NAMED but not
SIZED, add the counter that sizes it -- what fraction of the refused population
does this defect actually explain? If the answer is unknown, the fix is a guess
about the bottleneck no matter how certain the mechanism is. And when a
correctly-diagnosed fix measures flat, the FIRST hypothesis should be "it was
not the binding constraint", not "it did not run" -- checking reachability is
cheap and checking the ranking of constraints is what actually moves the number.

---
### 2026-09-24 - FORBIDDEN: gating a change that MOVES A PATCHED SEAM on a hand-picked test subset. The blast radius is every test that patches the OLD symbol, and it is enumerable.

- **What we believed:** that a careful, hand-picked regression sweep across the
  files "in the area" was an adequate gate for `7931b18a`, which moved two NFL
  week ENUMERATORS off `default_nfl_source_root()` onto `_source_roots()`. Eight
  files, 120 passing tests, shipped.
- **What was actually true:** the subset had a hole exactly where the change had
  reach. `tests/test_nfl_hide_backfill_weeks.py` patches
  `default_nfl_source_root` and calls `available_weeks()`, so moving that
  enumerator took it off the seam the fixture steers. It went GREEN -> RED and
  **the deploy went to production with it red** (control: 6 passed against
  `7931b18a^`, 1 failed after). Nothing else caught it: the earlier full sweep
  had run before this change existed, and the hand-picked one did not include
  the file.
- **Production was NOT harmed, and that is the trap.** Searching every root is
  precisely the fix, and its reading (`CHIP_JOIN_COVERAGE` 0 of 1,227 -> 1,230 of
  1,230) stands. What broke was VERIFICATION: the guard proving pre-season
  backfill weeks stay hidden stopped reaching its own fixture, so it asserted
  nothing. A regression that leaves behaviour correct and a guard hollow is the
  hardest kind to notice, because every signal you look at is green.
- **How we found out:** the follow-up audit this same session opened to hunt
  stale seams in OTHER files. Its first finding was the auditor's own regression,
  one commit old.
- **The rule going forward:** when a change moves a symbol that tests PATCH, the
  gate is not "tests in the area". It is mechanical and cheap --
  `grep -rl "<the old symbol>" tests/` gives the exact blast radius, and every
  hit either patches a live seam, patches nothing, or must be run. On this
  change that was 26 files; the honest subset was knowable in one command and I
  did not run it.
- **A grep is the START of the split, never the answer.** Those 26 resolved to
  16 already-safe / 5 mention-only / 5 candidates, and running the candidates
  under instrumentation found **1** genuinely affected test. Reporting "26 files
  affected" would have been as wrong as reporting none.
- **Instrument the RESOLUTION, not the call.** The audit
  (`scripts/audit_nfl_root_seams.py`) first reported 2 extra affected tests;
  both were `data_path` returning a NAMED FALLBACK for a file that does not
  exist -- a path into `data/nfl_source` that reads nothing. Requiring
  `.exists()` is the whole difference between "resolved a path" and "read a
  file". An instrument that cannot tell those apart manufactures the defect it
  exists to find, and it flagged its own author's new test correctly only after
  that fix.
- **Cost:** one deploy shipped with a red test, ~20 minutes to find and repair,
  nothing wrong in production. Cheap only because the audit was opened; had it
  not been, a hollow guard would have sat green indefinitely.

---

### 2026-09-24 (session 25e0f859, lane live-gameline-ledger-0820-shrink) — OVERTURNED: "the ledger for a past date shrank." A file served by an ops route is the SERVING SERVICE's disk, never the writer's — so two counts of "the same file" can be two different files
- **What I published first.** 2026-08-20's board artifact counted `records_considered: 4817`; `/api/ops/artifacts/stream` serves **4,809** records for that date. I wrote it into `leads.md` as *"an append-only live-gameline ledger appears to have SHRUNK"*, which is a claim about MUTATION and was wrong.
- **What is true.** The ledger is WRITTEN on refresh-worker's disk, and the board that computes `records_considered` is BUILT there — `ops.py:2976`'s own comment says so, citing `render.yaml`. `api_ops_artifacts_stream` resolves `target = data_root() / relative_path` and `send_file`s it: **the disk of whichever service serves the request**, i.e. web. Web holds the ledger only because something PULLED it — `artifact_publisher.py:1277` allowlists it as STREAMED, explicitly NOT swept, and says outright *"allowlisting only PERMITS a push; something has to make it."* So 4,817 and 4,809 are two files, not one file at two times.
- **The writer was innocent and that was checkable in one read:** `append_records` opens `"a"` and carries a `_MAX_RECORDS_PER_FILE` CAP that stops writing — there is no delete path. I should have read the writer before writing the word "shrank".
- **What made it diagnosable was a per-date control, not the architecture.** The architecture alone would have supported the two-copy story as a plausible narrative for anything. The evidence is that the 2026-08-27 bulk capture wrote SEVEN dates in one run and **six match today's stream exactly** (8070, 4223, 1718, 6534, 10406, 7644); only 08-20 differs. A retention trim, a compaction or a re-seed cannot single out one date.
- **Rule.** Before describing a served artifact as changed, deleted, truncated or shrunk, establish WHICH SERVICE'S DISK answered you. On Render the disks are not shared; an ops route reads its own. Then read the writer for a delete path. A difference between "what a build recorded" and "what a route serves" is a TRANSPORT fact until proven otherwise, and the default should be staleness, not mutation.
- **The operative consequence, which outlives the anecdote:** a past ledger fetched from `stream` is NOT necessarily the file the board scored, so any backfill or re-score reading one must anchor on something the original build recorded (`records_considered`, or exact reproduction of a retained figure) and REFUSE on mismatch. `rescore_live_gameline_date.py` does, and that gate is the only reason this was visible at all — it refused exactly the two dates where the copies diverge, and all ten it passed matched their anchor.
## 2026-09-24 — A FIX DEFINED RELATIVE TO A MOVING REFERENCE DECAYS AGAINST A FROZEN TARGET — `drop_upstream_echoes` narrows less against the same worktree every day, and nothing announces it `[session ac238d51, lanes archive-diff-baseline-echo / closed-lane-archive-20260924-1219]`

- **What I shipped and what I believed.** `173e42bc` added `drop_upstream_echoes()` to the
  lane-archive gate: discard a changed line whose text is already on `origin/main`, because a
  worktree that is BEHIND renders upstream's own lines as its own. Verified off != on, both
  directions, and it freed three blocks that had been stuck 19 h. I wrote it up as *the* answer to
  the stale-baseline mechanism.
- **What is actually true.** The filter is defined against `origin/main`, which MOVES. The target —
  an abandoned worktree — does NOT. Every commit that rewrites a line the worktree still holds takes
  that line out of `origin/main`'s set, and the line stops being discountable. So the same frozen
  diff gets *less* filterable over time, monotonically, with no one touching it.
- **Measured the same afternoon, like for like** — identical diff, identical filter, only the
  reference moved: worktree `tripwire-applog-page-cap` showed **13** lines "not on `origin/main`"
  against tip `c4e2a022`, and **30** against the tip **two hours later**. Nothing in the worktree
  changed. Its false-positive weight against the gate grows on its own.
- **Why this is not just a caveat.** It inverts the maintenance story. I recorded the blockage as
  *bounded* — the 3-day `--diff-stale-min` clock frees it at 2026-09-27 06:04Z — and that is still
  true, but the cost of waiting is NOT flat, and a worktree that gets touched (resetting the mtime
  clock) without being rebased becomes progressively harder to filter with no upper bound at all.
- **How to apply.**
  - When a predicate is written as `X is already in <live reference>`, ask what happens as the
    reference moves and the subject does not. If the answer is "the predicate weakens", the fix has
    a half-life and the write-up must say so.
  - **State the decay next to the verification.** An off != on reading is a measurement at ONE
    instant against ONE reference; it does not license "this is fixed" for a filter whose reference
    is a moving branch. Re-read it later against the same subject — that is what caught this.
  - Prefer, where it is available, a comparison against something that does not move: the merge-base
    of the worktree's HEAD with `origin/main` answers "did THIS session change it" without decaying.
    Not done here; recorded as the shape of a durable fix.
  - Generalises past this gate: any staleness/dedup/allowlist check phrased against `origin/main`,
    `latest`, `HEAD` or "current config" has this property. Related:
    `re-baseline-before-judging` (a handed-down baseline expires) — same physics, opposite direction:
    there the BASELINE went stale, here the REFERENCE moves and the subject goes stale against it.
- **Cost:** none yet — the reclaim landed and the three blocks are archived. The exposure is a future
  session reading the 2026-09-24 entry above, or the tool's README, and concluding the mechanism is
  closed. It is narrowed, not closed, and it re-opens a little each day.

---

### 2026-09-24 (session f5615aa2, no lane) — OVERTURNED: "the dry-run prompt replaced the stored prompt, restore it." A scheduled task's RUN-TIME OVERRIDE is not an edit to its stored prompt — and "restoring" a prompt that was never changed replaces a correct one with a paraphrase

- **The belief, and who held it.** The one-time task `layer2-score-v2-promotion-decision-1006`
  (fires 2026-10-06 10:00 CDT, closes todo `#679` step 5) was run early on 2026-09-22 under a
  temporary DRY RUN brief, whose own text said *"the real one is restored immediately after this
  run."* The follow-up instruction was "restore the real task prompt now" — premised on the stored
  prompt having been overwritten.
- **What was actually true, measured.** `SKILL.md` already held the real brief: 6,703 bytes, mtime
  2026-09-22 16:19:37 Central, **zero** matches for
  `dry.?run|pre-approval|l2dry6|temporary prompt|graded_dry|no-op push`, and every real-brief marker
  present (`NEVER deploys`, the PROMOTE/DO NOT PROMOTE/REJECT rule, the multiple-comparisons guard,
  the NCAAF-registry trap, the `findings_2026-10-06_*.md` output path). The dry-run text reached the
  session as a **dispatch-time override**, never as a write to the stored prompt.
- **The second false fear, also measured.** The early run did **not** consume the one-time fire:
  `fireAt` = `nextRunAt` = `2026-10-06T15:00:00.000Z`, `enabled: true`, `totalRuns: 1`. An early
  manual run and a scheduled fire are separate things.
- **What the damage would have been.** The only recoverable source for a "restore" was the repo
  brief `.syndicate/scheduled_task_score_v2_promotion_decision.md` (161 lines on `origin/main`).
  Rebuilding `SKILL.md` from it would have swapped a correct, condensed 6.7 KB prompt — one that
  deliberately *defers* to the versioned repo brief — for a fresh paraphrase, silently dropping
  whatever the paraphrase missed. The task then fires unattended at 10:00 on 10-06 with nobody
  reading it.
- **How to apply.**
  - **Read the artifact before restoring it.** "Restore X" is a claim about X's current state, not an
    instruction that is safe to execute blind. Diff or grep the target for the contaminant FIRST;
    a no-op restore and a destructive one are indistinguishable from the request alone.
  - For scheduled tasks specifically: `list_scheduled_tasks` → the entry's `path` is the stored
    prompt, and `fireAt`/`nextRunAt`/`enabled` say whether the schedule is still armed. Check both;
    they answer different questions and both were assumed wrong here.
  - **A reconstruction is not a restoration.** If no byte-identical source of the original exists,
    say so and stop, rather than producing a lookalike. Related: `retraction-is-not-innocence`
    (withdrawing a claim does not establish the opposite) — here, an instruction premised on a
    false state does not make the state false.
  - Note `list_scheduled_tasks` returns **79,771 characters / 1,347 lines** and exceeds the
    tool-result token cap outright — grep the saved tool-result file, do not try to read it directly.
- **Cost:** none. Nothing was overwritten; the check cost two tool calls. The exposure was a correct
  prompt for an unattended 10-06 decision run, replaced two days before it fires.

---
## 2026-09-24 — `git checkout -- <path>` ON A STAGED CHANGE IS A SILENT NO-OP, AND A DESTRUCTIVE COMMAND THAT DOES NOTHING REPORTS EXACTLY LIKE ONE THAT WORKED `[session ac238d51]`

- **What happened.** Authorised to discard a redundant `.syndicate/deploys.md` diff in another
  session's worktree, I ran `git -C <wt> checkout -- .syndicate/deploys.md`. No output, exit 0. The
  file was still `438 0` against HEAD.
- **Why.** `git status` read `M ` — **staged**, with the working tree already matching the index.
  `checkout -- <path>` restores the working tree FROM THE INDEX, and the index held the change, so
  it faithfully restored the thing I was trying to remove. `checkout HEAD -- <path>` (or
  `restore --source=HEAD --staged --worktree`) is what resets both.
- **Why this is dangerous rather than merely annoying.** Destructive git commands are silent on
  success. So "no output, exit 0" is the SAME observation for *did exactly what I asked* and *did
  nothing at all*, and the direction of the error is the one that does not announce itself — I was
  one step from reporting a discard that had not happened. The inverse error (discarding more than
  intended) at least leaves evidence.
- **How to apply.**
  - **Read the two-column status code before any restore.** `M ` is staged, ` M` is worktree-only,
    `MM` is both. `checkout --` only addresses the second column.
  - **Verify a destructive operation by its POSTCONDITION, never by its exit code** —
    `git diff HEAD -- <path>` empty AND the status entry gone. Same family as
    `confirm-the-code-ran`: assert the state, not the invocation.
  - Related in the opposite direction: `git checkout -- <file>` on an UNCOMMITTED file destroys it
    outright (it did exactly that to my own patch earlier the same day, and `discard-guard.py`
    refused the same command on a sibling file). The command is under-powered on staged content and
    over-powered on unstaged content, which is a bad combination to carry a vague mental model into.
- **Second failure the same minute, logged because it has its own rule already.** I had described
  that worktree as "two ledger files, 0 untracked". It held **53 entries** including a staged
  `scripts/` file — because I had run `git status --porcelain -- .syndicate` and separately counted
  only `??` lines, then characterised the WHOLE worktree from those two filtered queries. That is
  `compound-absence-claim` exactly: a claim over a population from a check that could only ever see
  part of it. **When the next action is destructive, re-run the query UNFILTERED first.**
- **Cost:** none. The no-op was caught by verification, the discard was then done correctly, all 323
  discarded lines were confirmed present on `origin/main`, and the untouched files stayed untouched.

---
### 2026-09-24 - FORBIDDEN: counting files under `data/**` with `ls` and calling the result "tracked". I did, twice, and published the number.

- **What we believed:** that `oddsapi_player_props_*.csv` is tracked in git with real
  data in most weeks -- "**45 of 58 tracked props files carry real data rows**" -- and
  that this REFUTED `nfl_props_path`'s docstring claim that the family ships as
  header-only stubs. Recorded in `28bd4023` and in the closing block of lane
  `nfl-props-backtest-seam` (`55fe7f8e`), and used as the justification for a repair.
- **What was actually true:** git tracks **14** of those files and **13 are 6-byte
  stubs**. The 58 were the PRIMARY TREE's WORKING DIRECTORY -- 44 of them UNTRACKED
  local captures a developer's pipeline had generated. Measured both ways afterwards:

      worktree @ origin/main   git-tracked 14   on disk 14
      primary tree             git-tracked 14   on disk 58   (44 `??`)

- **How we found out:** the follow-up lane re-ran the same count in a WORKTREE and got
  a different answer. Nothing else would have caught it -- the number was plausible,
  specific, and load-bearing.
- **Why it is worth its own entry when `CLAUDE.md` already says this.** `CLAUDE.md`
  states it outright: "`git ls-files` vs. what is on disk is a real distinction here...
  **Say which you used.**" I did not say which I used, because I did not notice there
  was a choice -- `ls` in a repo directory FEELS like reading the repo. The rule needs
  the trigger attached: **any count of files under `data/**` is `git ls-files` or it is
  not about the repo**, and the two differ by 3x in this one directory.
- **The retraction is in-place, not a deletion.** Both recorded claims keep their
  original text marked `[RETRACTED ...]`, because a wrong number that was ACTED ON is a
  record worth keeping (`feedback_retraction_is_not_innocence`: withdrawing a bad claim
  gives "not proven", never "proven innocent").
- **What survived the retraction, and it matters:** ONE tracked file
  (`oddsapi_player_props_2025_wk22.csv`, 10,274 B) does carry real rows, so
  `_csv_has_data_rows` already has a checkout file it will ACCEPT and the leak the repair
  closed was real on a clean checkout -- just smaller than claimed. **The fix was right
  and the justification was wrong**, which is the combination that survives review and
  should not.
- **Cost:** a false number published in two commits and a lane block; caught within the
  hour because the next lane's falsification clause pointed at exactly that assumption.

---
## 2026-09-24 FORBIDDEN: recording that a path MOVED LANES by spelling the path, inside a Files or Tests block. Prose ABOUT a path is indistinguishable from a claim OF it `[lane lane-claim-truncation-visible, session 4ab694ed]`

`lane_claims._paths_in` extracts every backticked path-shaped token in a Files
or Tests block. It has no notion of a sentence. So a note explaining that a file
was taken AWAY re-claims it.

Both halves of this happened in one session, minutes apart, while I was fixing
the first:

- "(`test_artifact_publisher.py` TAKEN 2026-09-24 by lane nhl-live-resim)" --
  re-claimed the very file it was recording the release of, leaving it held by
  two lanes.
- "...while the take used the `tests/` prefix" -- a bare DIRECTORY token,
  which `matches()` extends over the whole subtree. One lane silently claimed
  EVERY TEST FILE IN THE REPOSITORY, and `check_lane_invariants` reported a
  single contested "file" held by **29 lanes**.

The second is the dangerous shape: a directory claim is invisible in the diff
(one word changed), blocks every other session from every test, and reads as a
sentence about punctuation.

HOW TO APPLY: inside a Files or Tests block, write a take/release note WITHOUT
spelling the thing as a path -- "the artifact-publisher pull tests were TAKEN by
lane X", "the tests-directory prefix". Never put a trailing-slash token in
backticks anywhere in those blocks unless you mean to claim the subtree. After
any ledger edit that mentions a file, run `py -3 scripts/check_lane_invariants.py`
and read the claim count, not just the exit line.

---
## 2026-09-24 - RULE: a guard's own recorded blast radius EXPIRES, and "fix the N it flags" is a hypothesis, not an instruction `[lane lane-claim-truncation-visible, session 4ab694ed]`

`_DISCLAIMER_MARKERS` carries a careful measurement: adding `", no "` and four
siblings "change 4 lines out of 2,186 and every one is a genuine disclaimer",
with the instruction "Re-measure the same way before adding a sixth". Nobody
re-measured the EXISTING five. Re-measured 2026-09-24 on the live `lanes.md`:
**18 Files lines lose a path and 17 of them are OPEN lanes** -- one keeping 0 of
3, one keeping 6 of 23.

The measurement was true when written and silently stopped being true as the
ledger's prose style drifted. A number in a comment is a reading with a date,
not a property.

THE SECOND HALF, and it is the one that nearly caused harm. Asked to "fix the 16
lanes", the obvious action is to restore every dropped path. READING them showed
only **ONE** was a genuine under-claim. The dominant shape is
"RELEASED ... to lane X: `<path>`", where the path after the marker is the file
being GIVEN AWAY -- restoring those would have re-claimed released files and
manufactured exactly the false contests the whole exercise was avoiding. One of
my own alarming summaries ("the lane that owns `render.yaml` holds none of its
three paths") was flatly wrong: that token sits inside "neither `render.yaml`
nor the start command changes", a negation.

HOW TO APPLY: when a new checker flags N items, the deliverable is N READINGS,
not N fixes. Classify before editing, and say out loud how many survived --
17 -> 1 here. And when you quote a comment's measurement as current, re-run it
first; this repo's own `A rate, not a count` rule is the same failure one level
up.

---

### 2026-09-24 (session 25e0f859, lane verify-mirror-live-copy) — FORBIDDEN: installing a comparison tool AT the location it is supposed to check, without asking what it resolves its two SIDES from. It may compare that location with itself and pass forever
- **What happened.** `verify_mirror.py` compares the git-tracked mirror of the lane-archive tools against the live out-of-git copies. It was missing from the live directory, so "nothing there verifies itself" — and the obvious fix is to copy it there. But `here = Path(__file__).resolve().parent` is the side it treats as the MIRROR, and `--live` DEFAULTS to the live tools directory. Copied there and run with defaults, both sides resolve to the same path. Measured, not predicted: it printed `3 mirrored file(s), 0 discrepancy(ies)` and exit 0 while comparing the directory with itself — **output byte-identical to a genuine pass**, with nothing in it to tell the two apart.
- **A check that cannot fail is worse than no check**, because the absent one is visibly absent and this one reports success. Same shape as the instrument-blindness entries already here: a healthy reading is evidence only once you know what makes it read unhealthy.
- **Rule.** Before moving, copying or re-pointing any tool that compares A with B, write down where it gets A and where it gets B. If either is derived from the tool's own location, moving it changes what it compares. Then run it at the new location BEFORE trusting it, and check the output can still be negative — here, against a temp copy with one file altered, it must still report DIFFERS and exit non-zero.
- **How it was fixed:** the same-directory invocation exits 2 rather than passing. The comparison itself is symmetric, so from the live directory `--live <repo>/scripts/lane_archive_tools` gives correct MATCH/DIFFERS, with only the MISSING-LIVE / MISSING-MIRROR labels reading from the other side.

### 2026-09-24 (session 25e0f859) — `lane_open.py` writes into the SHARED primary tree, and a peer's write to `lanes.md` can delete your block before it is ever committed. Twice in one session
- **What happened.** Two lanes were opened with `lane_open.py`, which writes the block into the primary tree's `lanes.md`. Both blocks were GONE from that file by the time the closing commit tried to read them back — the file moved 491,116 -> 494,543 -> 493,938 B while the work was in progress, so a peer session had rewritten it. Neither block had been committed, so neither existed anywhere: not locally, not on `origin/main`.
- **What made it visible at all** was `.syndicate/.current-lane.<session-id>` still holding the slug, and the closing script's regex failing loudly rather than silently writing an empty block. A bare shared `.current-lane` would have given no signal.
- **Rule.** If a lane's block matters, commit it soon after opening it, or reconstruct it from the fields at close and SAY SO in the block. Never assume the block you wrote is still in a shared `lanes.md` minutes later — read it back before relying on it, and treat "the slug is not in the file" as a peer overwrite rather than as your own error.
### 2026-09-24 — FORBIDDEN: asking the user to authorise an interruption by quoting how LONG it lasts. A duration is not a cost until the interrupted thing's own cadence sits beside it.

- **What we believed:** that restarting `live-odds-worker` mid-slate costs "**~5-6 minutes
  with no in-play odds capture**" on 4 live MLB games. I put that to the user as the price
  of a fleet-alignment deploy and they authorised it on that number. It came from this
  service's own boot time, measured earlier the same day (live 14:23:51Z -> `venue_poll
  STARTED` 14:28:58Z).
- **What was actually true, measured across the restart:** the gap was **11m36s**
  (`MLB_LIVE_PROBE` 20:01:50Z -> 20:13:26Z) — **longer** than I said, because the last
  pre-restart probe fired 5m56s BEFORE the instance was replaced, so the gap is
  time-to-replacement PLUS boot, not boot alone. And **far cheaper** than the framing
  implied, because the loop's own cadence in the pre-deploy hour was:

      8m41s  5m23s  7m01s  10m25s  5m52s  6m06s  6m29s  7m20s     median ~6m45s, max 10m25s

  **The restart cost about ONE EXTRA CYCLE — 1.1x the largest gap this loop takes with
  nothing wrong.** I had described it as a blackout of a continuously-capturing service.
- **Why the two errors matter together.** Wrong in BOTH directions is what made it
  undetectable: had I only overstated it, the measurement would have looked like good
  news and been banked; had I only understated the duration, the cadence would have
  rescued me. A number that is too big on one axis and too small on the other survives a
  sanity check.
- **The rule, with the trigger attached.** `feedback_rate_not_count` already says a count
  without a denominator is not a finding. The new surface is that **an ESTIMATE offered to
  a human as the basis for a decision is held to the same standard as a finding, and
  earlier** — the denominator has to be read BEFORE the question is asked, not after
  the action is taken. Here it was one log query against the hour before the deploy, and I
  had already run that query's cousin for the baseline.
- **How we found out:** only because the lane's Verification required measuring the gap
  rather than asserting the deploy succeeded. Had the lane said "confirm the poll resumes",
  the estimate would never have been checked and the wrong figure would have been reused
  for the next mid-slate restart.
- **Cost:** none to production — the interruption was real but ordinary. The cost was to
  the decision: the user weighed a trade-off against a number I had not measured.

---
## 2026-09-24 RULE: an instrument that reads ONE channel cannot testify about a system with TWO. A 403 from the disk-gated route is not evidence about the Redis crossing `[lane nhl-live-resim, session 4ab694ed]`

`live/*_live_lens.json` crosses services through **keyvalue (Redis)**, not
through `HOT_ARTIFACT_PATTERNS`. Verified on production 2026-09-24, all three
services: `SYNDICATE_REFRESH_STATE_BACKEND` is `keyvalue` on web,
refresh-worker and live-odds-worker; `live/` matches none of
`_KEYVALUE_EXCLUDED_PATH_MARKERS`; so `write_json_file` returns after the Redis
SET and `read_json_file` after the GET, and **neither ever touches disk**. The
board reader is `read_json_file(data_root()/"live"/f"{sport}_live_lens.json")`.

Three comments in `artifact_publisher.py` said or implied otherwise, and I wrote
one of them THAT MORNING ("without an entry here the snapshot is a file that
exists and cannot cross"). The measured fact underneath them was real --
`/api/ops/artifacts/stream?path=live/nfl_live_lens.json` answers 403 -- but that
route reads DISK and gates on `target.is_file()`. For a keyvalue-backed path
there is no file, so **403 there means "not on disk", never "cannot cross"**.
The same file warns about this exact conflation twenty lines further down.

THE COST, inside one hour: I recommended "allowlist `live/nfl_live_lens.json`,
cheap 24h work" as the top Wave-1 item. It would have bought nothing, and if
NFL's lens had been wired on the strength of it, it would have shipped `#340` --
a pregame probability under a live label.

THE CROSSING'S ACTUAL PRECONDITION is key identity, and nothing asserts it:
`_state_key_for_path` is `{namespace}:refresh-state:{ABSOLUTE RESOLVED PATH}`.
Measured: `SYNDICATE_DATA_ROOT` is `/opt/render/project/data` on all three, and
the namespace is `syndicate` on all three -- set explicitly on web, ABSENT on
both workers where the code defaults to that same string. A service given a
different data root would break every such join SILENTLY, with no reason
emitted, and the allowlist would look like the culprit.

HOW TO APPLY: before citing an instrument as evidence about a path, ask which
CHANNEL it reads. Disk-gated routes (`artifacts/stream`, `pull_hot_artifacts`,
the export sweep) are blind to every keyvalue-backed path -- which is most
operational state. And when a comment asserts a MECHANISM ("X cannot cross
without Y"), that is a claim with a date: re-derive it from
`_keyvalue_backed` + the reader's own call before building a plan on it.

---
### 2026-09-24 — FORBIDDEN: trusting a structural guard to protect CONTENT. A keep-set guard cannot see damage to MEANING, and mine passed while gutting a contract.

- **What we believed:** that a trim of someone else's lane block was safe once the
  checks passed -- claim set identical as a set, zero orphaned indented lines, OPEN
  count unchanged, every moved line present verbatim in `lanes_history.md`, every
  kept line still present. Five blocks were trimmed on that basis.
- **What was actually true:** on `polymarket-rejected-resubmit-loop` the keep rule
  kept `- Hypothesis (to test, not believed), ranked:` and `- Falsification test:`
  while moving their indented children, which ARE the content. The result is a
  contract that promises a list and delivers nothing. **Every check passed:** no
  claim moved, nothing was orphaned by indentation, the claim set matched exactly.
  The guards measure STRUCTURE and PRESENCE; the damage was to MEANING, and nothing
  automated in that set can see it.
- **How we found out:** the dry run printed the keep set with a reason per line and
  a human read it. Nothing else would have. The fix is mechanical once seen -- a
  kept contract key, or any kept line ending in a colon, keeps its whole subtree.
- **The rule:** a tool that REMOVES prose gets an opt-in `--apply` and a dry run
  that prints what it will keep and why. The reviewer is the instrument. Structural
  checks are necessary and are not sufficient, and the gap between them is exactly
  the class of damage that survives review because the report is green.
- **Two more from the same hour, same shape:**
  - **A vacuous test, found only by mutation.** `test_a_claim_bearing_line_is_kept`
    used a plain `- Files:` line, which a DIFFERENT rule keeps anyway, so deleting
    the claim rule left the suite green. A keep-policy test is vacuous unless its
    fixture isolates the one rule under test -- "keep more" passes every
    nothing-was-lost assertion.
  - **A write that reported success and did nothing.** A `str.replace` adding a
    constant silently no-opped because the file held a literal em-dash rather than
    `\u2014`; `ast.parse` then passed, because the resulting NameError is a RUNTIME
    error. I printed "added; parses clean" having asserted nothing about the
    replacement landing. **Assert the anchor count before writing, and assert the
    symbol exists after.**
- **Cost:** none shipped -- all three were caught before a write. The cost was that
  three of five automated guards reported green on a transformation that would have
  destroyed a lane's contract.

---
### 2026-09-24 — FORBIDDEN: pushing a whole-file write without rebuilding it on the base it is committed against. I clobbered another session's work, and my own explanation of the warning number is what let it through.

- **What happened:** `e9287fab` staged a `lanes.md` built on an older `origin/main`
  against a newer one. In between, sessions `e9c5ca1c` and `2c2dcade` -- the
  scheduled closed-lane archive task -- had added two CLOSED lane blocks and three
  archive pointer lines. My write deleted all of them, and I pushed it.
- **The warning was in front of me and I talked myself out of it.** The numstat
  read `25 insertions, 12 deletions`, and I explained the deletions as "my OPEN
  block being replaced by the CLOSED block". **That block had never been pushed**,
  so a close could only ever have been an INSERT. The number disagreed with my
  story and I trusted the story.
- **I had the correct procedure and skipped it.** For every earlier whole-file
  rewrite that day I re-asserted the base blob immediately before committing and
  rebuilt the transformation when it had moved -- twice it had. Here the edit felt
  small, so I did not.
- **Then I did it again on the fix.** The restore commit chained `git push` after
  the numstat print instead of gating on it, so it pushed `14 insertions, 17
  deletions` before I had read either number. The restore happened to be correct --
  the 17 were three blocks the archive task had MOVED to `lanes_closed.md`, which
  my clobber had accidentally UN-archived by reinstating their bodies -- but I did
  not know that when I pushed.
- **Why "0 deletions" is the wrong gate here.** A move legitimately deletes; an
  archive legitimately deletes. The gate that works is: **a whole-file write is
  rebuilt on the base it will be committed against, every time, and every deletion
  is NAMED before the push, not explained after it.** Naming them takes one
  `git diff --numstat` read and one `grep '^-'`.
- **How it was caught and repaired:** the numstat on the fix looked wrong too, which
  finally made me read the deleted lines. Repair was to rebuild my change on THEIR
  base -- where it was a pure insert -- and assert that every line of their base
  survived. Verified after: 0 lines from `2ee87e4c` missing from `origin/main`,
  three archived blocks each with a pointer in `lanes.md` and a body in
  `lanes_closed.md`, both new archive blocks present, `INVARIANTS HOLD`.
- **Cost:** another session's committed work was absent from `origin/main` for
  about four minutes, and for part of that time three lanes were silently
  un-archived. Nothing was lost permanently, and only because the clobbered content
  was still reachable from `2ee87e4c`.

---
## 2026-09-25 FORBIDDEN: a one-shot `replace(old, new, 1)` on a line that is not UNIQUE in the file. The edit lands on the first match, and the damage is the site you did NOT mean to touch `[lane nfl-live-resim-activation, session 4ab694ed]`

`snapshot = read_json_file(data_root() / "live" / f"{sport}_live_lens.json")`
appears twice in `board_enrichment.py`. I meant
`attach_live_gamelines_for_sport` (line 2215) and hit
`attach_live_game_state_from_lens` (line 821), then deployed it.

TWO HARMS, AND THE ONE I DID NOT INTEND WAS WORSE. The fix never landed -- the
join kept reading the pregame lens. AND NFL's live SCORE/CLOCK reader was
silently repointed at a file with a different shape. A failed fix is a null
result; a working function quietly pointed at the wrong data is a regression,
and nothing in the change said so.

IT WAS ONLY CAUGHT BY A FIELD I HAD NOT PREDICTED ON. `index_why.sources_seen`
came back `{}` -- not `{pregame: 16}`, not `{live_resim: 16}`, but NO lanes at
all, which a re-sim snapshot cannot produce because a refusal still emits a
lane. The predicted field (`nfl_gameline_join_present`) read TRUE and the deploy
was still broken.

HOW TO APPLY: before a one-shot replace, COUNT the matches. If more than one,
anchor on something unique (the enclosing `def`, a neighbouring line) or edit by
line number after locating the right function. Afterwards, grep the changed
token and check WHICH function each hit lives in -- `head -N file | grep -n
'^def '` answers that in one command. And when a receipt's predicted field
passes, read one field that would look different if the change had landed
somewhere else.

---
## 2026-09-25 - RULE: an instrument that ALREADY FIRES before your change cannot verify it. Read its baseline, not its name `[lane nfl-live-resim-activation, session 4ab694ed]`

Wiring NFL's live tier, the obvious success signal was
`LIVE_GAMELINE_BUILD sport=nfl`. It sounds exactly like the thing being turned
on. Measured before deploying: it had ALREADY fired **52 times** in the same
window, because it is `book_grid`'s build and is not gated on
`_LIVE_GAMELINE_SPORTS`. Predicting on it would have scored a PASS on a deploy
that changed nothing about it.

The discriminator was the neighbouring `LIVE_GAMELINE_JOIN sport=nfl`: **0**
lines, against a live MLB control of **23** in the same window. The control is
the half people skip -- a zero only means something once you have shown the
instrument can read non-zero right now.

THE SAME MISTAKE IN ITS OTHER FORM, same session: I watched
`/nhl/api/live-lens` for an hour as evidence about the BOARD. It is the PAGE
api and never reads the re-sim snapshot, so `live_resim_mentions=0` there was
uninformative rather than reassuring -- while the board instrument I had
already used correctly for MLB sat one command away.

HOW TO APPLY: before naming a field in `--expect`, read its CURRENT value and a
control. Two questions, both cheap: *is it already non-zero?* and *what would
make it read differently?* If a healthy-looking reading would be produced by
doing nothing, it is not a verification.

---
## 2026-09-25 - RULE: a FETCH that failed must not be spelled like a RESULT that is empty, and a missing request header is a real cause `[lane nhl-live-resim, session 4ab694ed]`

NHL's producer published an empty slate through six live games. Root cause,
measured same-instant on the live endpoint:

    default urllib UA -> HTTP 403 Forbidden
    "Mozilla/5.0"     -> 200, 11 games

`api-web.nhle.com` refuses `Python-urllib/3.x`. **And I had already hit this
myself, in my own probe, hours earlier** -- I added a User-Agent to the probe to
make it work and never connected it to the producer I had written.

What made it undiagnosable was the second line:
`except Exception: return []`. A 403 became "no games scheduled", so the tick
reported `ok: true` in under a second and the board read
`games_in_snapshot: 0` with no refusal to inspect. The sub-second duration was
itself the tell -- a tick that re-simmed six live games cannot finish that fast.

HOW TO APPLY: a network read that fails gets its OWN type or its own recorded
reason, never the same empty collection an honest zero produces. When a
producer publishes nothing, check the FETCH before the logic. And when you fix
something in a throwaway probe to make it work, ask whether production does the
same thing -- the workaround IS the finding.

---
## 2026-09-25 - RULE: COUNT THE MATCHES BEFORE YOU WRITE. Four defects in one session, one shape `[lane nhl-live-resim, session 4ab694ed]`

Every one of these was a write whose TARGET was not unique, and in three of the
four the damage was at a site I never looked at:

- `s.replace(old, new, 1)` on a snapshot-read line that appears twice in
  `board_enrichment.py` -- landed in `attach_live_game_state_from_lens`, not the
  game-line join. The fix never shipped AND a working reader was repointed at a
  file it cannot parse. **Deployed.**
- An appended test helper `_score_row()` SHADOWED an existing one of the same
  name in the same file. 14 passing tests went red instantly.
- A blanket `replace("_score_row(", "_named_row(")` to repair that also renamed
  `team_names_from_score_row` -> `team_names_from_named_row`.
- And then `live_state_from_score_row` the same way.

The first one is the expensive one and the pattern is worth naming: a one-shot
replace is SILENT about ambiguity. It does not fail when there are two matches;
it picks one. So the failure mode is not an error, it is a correct-looking edit
in the wrong place, and it survives review because the diff reads exactly as
intended.

HOW TO APPLY: before any `replace(..., 1)` or appended helper, COUNT --
`grep -c` the string, `grep -n "^def name"` the symbol. If the count is not 1,
anchor on something unique (the enclosing `def`, a neighbouring line) or edit by
line number. Afterwards, grep the changed token and print WHICH function each
hit is in: `head -N file | grep -n '^def '` answers that in one command. The
cost of not doing it here was a production deploy that changed the wrong
behaviour and verified as a pass on its own predicted field.

---
## 2026-09-25 - RULE: "deploy live" and "artifact rebuilt" are DIFFERENT EVENTS when producer and consumer are different services `[lane nhl-live-resim, session 4ab694ed]`

Measured, one fix, 90 seconds apart:

    14:26:46Z  deploy live on live-odds-worker
    14:27:54Z  board join on refresh-worker -> the OLD number
    14:28:18Z  producer tick, first run on the new code, rewrites the snapshot
    14:33:26Z  board join -> the new number, prediction MET

Reading the 14:27:54Z line would have recorded a FAILED fix. The consumer runs
on a different service with its own cadence and reads an ARTIFACT, so it keeps
serving the pre-boot file until the producer rewrites it.

This is the third distinct instance in one session of a correct-looking reading
supporting a wrong conclusion -- the others being a fix deployed to a service
that does not run the code, and an instrument (`LIVE_GAMELINE_BUILD sport=nfl`)
that already fired 52 times before the change.

HOW TO APPLY: when the thing you changed WRITES and the thing you read CONSUMES,
gate the verification on the WRITER's timestamp, never the deploy's. Find the
producer's own clock (a tick status, an artifact mtime, a generatedAt) and
require it to postdate the boot before any consumer reading counts.

---
## 2026-09-25 FORBIDDEN: gating a deploy's verification on a `print()` inside a step the orchestrator runs as a SUBPROCESS. Production cannot hear it `[lane nhl-board-rows-missing, session 4ab694ed]`

I shipped a fix to NHL's odds collector and added `NHL_QUOTE_SHARDS` in the same
commit, specifically so the deploy could be verified by "did the new code run".
Measured since boot:

    odds-refresh job lines (control): 298
    NHL_QUOTE_SHARDS lines:             0

The control proves the cadence was running, so the null discriminates. The cause
is `refresh_odds_sources._run_command`, which runs every producer under
`subprocess.run(capture_output=True)` and DISCARDS a successful step's stdout.

THE PART THAT MAKES THIS A RULE RATHER THAN A MISTAKE: **I had diagnosed exactly
this trap TWO HOURS EARLIER in the same session.** I used the absence of
`local_nhl_odds` log lines to conclude "NHL odds never run", was refuted by a
25.9 KB NHL odds artifact, and wrote the discard behaviour down as the reason.
Then I put my own new instrument in the same swallowed stream.

Knowing a trap is not the same as applying it. The application step is
mechanical and skippable, and I skipped it because the instrument felt like part
of the fix rather than part of the verification.

HOW TO APPLY: before naming a log line in `--expect`, ask WHERE IT IS EMITTED
FROM. If the emitter is a step the orchestrator launches as a subprocess, the
line is for a human reading a local run, not for production verification. Put
the number somewhere production can hear: a published artifact, a counter in the
step's RETURN VALUE that the orchestrator logs, or an ops route. And verify the
instrument can fire BEFORE relying on it -- one grep with a control, which is
the same thing that caught it here, just hours too late.

---
### 2026-09-25 — FORBIDDEN: checking a claim set as a `{path: lane}` mapping. A dict cannot represent a contest, so the check passes at the exact moment it should fail.

- **What we believed:** that my borrow of `doubleheader.py` from an idle lane had moved the
  claim, because the script asserted on the claim set before pushing and the assertion passed.
- **What was actually true:** the borrow APPENDED a note to the holder's `Files:` line and left
  both backticked paths on it, so `_claims` attributed each path to that lane AND to mine.
  `check_lane_invariants.py` went `VIOLATED: 2 contested file(s)` -- breaking the coherence I
  had restored an hour earlier in the same session.
- **Why the check could not have caught it.** It built `{str(path): lane}` from the claim
  pairs. Two lanes holding one path collapse into one entry, last writer wins, and the contest
  -- the only failure that matters for a claim edit -- becomes invisible by construction.
  **Claims are a SET of (lane, path) pairs; any check that flattens them to a mapping is blind
  to the thing it is checking for.**
- **How we found out:** `lane-guard` refused the very next edit, naming the holder. The guard
  was the instrument; my own verification was not.
- **How to apply:** verify claim edits as `{(lane, path)}` and assert on
  `{p for _,p in after if len({l for l,q in after if q == p}) > 1} == set()`. And when
  borrowing, REMOVE the path from the holder's line -- the repo's own form
  (`book-quotes-splice-repair`: "Files: RETURNED ... are HANDED to lane ...") -- rather than
  annotating it, because the parser reads paths, not prose.
- **Cost:** two contested claims live on `origin/main` for ~4 minutes, repaired in `3b2ce9a4`.

---
### 2026-09-25 — FORBIDDEN: shipping a second fix for a symptom you have not measured. The first fix was right and insufficient, and I only learned why by reading one field.

- **What we believed:** that the traditional-doubleheader join failed because the 45-minute
  separation rule could not resolve halves published five minutes apart. True, and it took the
  rail from 4 tiles to 3.
- **What was actually true for the REMAINING tile:** the unjoined group carried
  `commence_time 23:06:00Z` while both chips started 20:05Z and 20:10Z -- **~3 hours from
  both**. A traditional doubleheader has no real second start until game 1 ends, so StatsAPI
  publishes a NOMINAL placeholder minutes after game 1 while the book publishes the REALISTIC
  one. No time window could ever bridge it, and widening the near-exact window -- the obvious
  next move -- would have broken the controls that keep it honest while still not working.
- **What I did instead of measuring, twice.** I wrote a surplus-chip display rule that (a)
  shipped INERT, because it keyed groups on display text and chips on abbreviations, and (b)
  was the wrong trade anyway, removing a duplicate TILE by HIDING a game's clock -- which an
  existing test asserted against on purpose. Both were guesses at a symptom I had not read.
- **The one field that settled it** took a single query of the payload the page already had.
  It turned the next fix from "widen the tolerance" into "pair on ORDER", which is exact,
  needs no time agreement, and had a mechanism already in the repo
  (`doubleheader_event_ranks`).
- **How to apply:** when a fix moves a symptom without clearing it, the next action is a
  READING of the surviving case, not a second fix. "It got better" is the most expensive place
  to stop measuring, because the remaining failure now looks like a tuning problem.
- **A corollary worth its own line: inert code passes its tests.** The surplus rule was green
  because it never fired. A new branch needs a test that proves it EXECUTES -- `off != on` --
  before any test of what it does.
- **Cost:** two deploys and one revert that a single payload read would have made unnecessary.

---
## 2026-09-25 - RULE: a CADENCE MARKER records that a sport was LISTED, not that its producer ran. Never read one as evidence of work `[lane nhl-board-rows-missing, session 4ab694ed]`

NHL's pregame sweep marker reset on schedule all evening -- `marker_age_s` went
6955 -> 93 across the 19:23Z boundary, exactly as a 2-hour cadence should. It
looked like proof the collector had run. It is not:

    live_refresh_loop.py:5868  launched_sports = launch_sports.split(",") if ... else
                               _live_refresh_loop_effective_sports(selected_date)
    live_refresh_loop.py:5876  _record_pregame_sport_sweep_epochs(tick_started_epoch,
                               list(launched_sports))

The marker is written for every sport in the INTENDED list, before any statement
about whether that sport's step executed, produced output, or failed.

THE MEASUREMENT THAT BROKE THE TIE, and it is the only one that could. A shard
report is written UNCONDITIONALLY by `collect_and_write_team_odds`, even for an
empty frame. Sweep at 19:24:26Z, marker reset, shard report still 404 four
minutes later -> the collector did not run. The NHL odds artifact had likewise
been frozen at 15:44:17Z through two prior sweeps that both moved the marker.

HOW TO APPLY: before citing a timestamp, interval or marker as evidence that
work HAPPENED, find the line that writes it and check what it is a function of.
A marker written from the launch LIST is a fact about scheduling; only an
artifact written by the producing function itself is a fact about production.
This is the fourth signal in one session that looked like it answered the
question and belonged to a different emitter -- the others being absent log
lines from a discarded subprocess stream, a 403 read as absence, and a board
join read 24 s before the producer's tick.

---
## 2026-09-25 - RULE: a SAMPLE or a DERIVED LIST is not the population, and "never" is a claim about the population `[lane nhl-board-rows-missing, session 4ab694ed]`

Two categorical claims in one thread, both wrong, both from the same move:

  * "NHL is never in a refresh run." Built from every-9th-stamp sampling of 182
    runs PLUS a log tail beginning at 20:02 -- after NHL's 2-hourly slot had
    closed. The direct launch line then read
    `ODDS_SWEEP_LAUNCHED sports=mlb,nhl` at 19:24:30Z.
  * "No run stamp for mlb,nhl exists." The stamp list was harvested from PUBLISH
    log lines, so any run that publishes nothing is INVISIBLE to it. Absence in
    that list is not absence in the world.

Neither was a reasoning error about the system. Both were forgetting what the
evidence was made of: a stride-sampled subset, and a list filtered by an
unrelated predicate.

HOW TO APPLY: before writing "never", "none" or "zero", say out loud what the
denominator is and how it was built. If it was sampled, sample-based statements
are bounded ("not in 21 of 182") and the categorical one is unavailable. If it
was derived from a log grep, name the predicate that filtered it -- a list of
things that PUBLISHED cannot answer a question about things that RAN. And when a
cheap direct instrument exists (here: the one launch line that prints the sport
set), read THAT instead of reconstructing the population from side effects.

THE SESSION TALLY, because the pattern outweighs any single case: five signals
looked like they answered the question and belonged to a different emitter --
absent log lines from a discarded subprocess stream, a 403 read as absence, a
board join read 24 s before the producer's tick, a cadence marker written from
an intended list, and a publish-derived stamp list.

---
### 2026-09-25 — FORBIDDEN: reading a board tile's LIVE styling, or a chip's `state=live`, as evidence that play has started. `abstractGameState` flips at WARMUP.

- **What we believed:** that a re-check showing game 1 "LIVE (Top 1, 0-0)" had
  observed the pregame-to-live transition -- the one state the doubleheader join
  had never been tested in. A scheduled run reported exactly that, and it was the
  headline of its own log entry.
- **What was actually true:** StatsAPI 19:59Z gave 823491 `detailedState: Warmup`
  with `abstractGameState: Live`, `currentInning 1 Top`, **start 20:05Z**. The
  reading was taken at 19:51Z -- **14 minutes before first pitch**. The abstract
  state flips at warmup and the board's live styling follows it, so "Top 1, 0-0"
  is what a game that has not started looks like.
- **Why this is the expensive direction of error.** It manufactures a PASS for
  the exact case that was missing. A false negative gets re-checked; a false
  positive closes the question and the untested path ships. The run also wrote
  it into the daily log as verified.
- **How to apply:** when a state transition is the thing under test, read
  `detailedState` (or compare `now` against the posted start) -- never
  `abstractGameState`, never the chip's `state`, never the rendered styling. If
  the check runs before first pitch, its result is a PREGAME result whatever the
  tile says.
- **Two mechanism facts found alongside it, both cheap to re-learn wrongly:**
  a manual "Run now" does NOT consume a one-time `fireAt` (verified: `enabled`
  and `nextRunAt` unchanged after dispatch), but it DOES delay it -- the
  dispatcher refuses a second concurrent run, so a 59-minute pre-approval run
  pushed a 19:30Z fire to 19:50:24Z. Pre-approving a scheduled check is not free.
- **And a state.md line survived the code it described:** the surplus-chip pass
  was removed in `4d785045` while `state_mlb.md` still claimed the fix "seats
  only the SURPLUS chips". A removal has to delete the CLAIM, not just the code.

---
## 2026-09-25 RULE: a pairing that demands EQUAL COUNTS from two feeds breaks when either feed retires members on its own schedule. Test it across the lifecycle, not at one instant `[no lane, scheduled dh-rail-recheck-0925-live]`

- **What was believed:** `42b9be30`'s ordinal pairing was verified at 18:07Z with both
  games pregame. At 19:51Z a PASS with game 1 "LIVE" was read as surviving the
  transition. That run was already withdrawn: warmup, not in-play.
- **What happened in play (20:33Z, 21:12Z):** the guard `gs.length === cs.length`
  refused, because the ODDS side retired game 1's event once it started while
  StatsAPI kept both chips. The feeds disagree about membership on a SCHEDULE, not
  by accident. A guard written against a snapshot where both had 2 members could
  not see that.
- **How to apply:** for any join that counts, orders or pairs members across two
  feeds, write down when each feed ADDS and DROPS a member (pregame open, first
  pitch, final, postponement) and verify at each boundary. The pre-registered
  risks for this run (start revision, chip reshape) were both wrong. The real
  one was membership, which nobody listed.

---
### 2026-09-25 — FORBIDDEN: reading the DOM within a few seconds of a reload and reporting what is missing. The board loads in two waves and the second one is slower.

- **What I claimed:** that every MLB opportunity card had disappeared from the rail --
  17 tiles, all chip-keyed, zero group tiles, zero "opportunities". I was about to
  report a board-wide outage.
- **What was actually true:** I had read 5 seconds after `location.reload()`. Chips come
  from a GET (`/api/board/game-chips`) and cards from a POST
  (`/api/intelligence/query`) that takes longer. The next read, seconds later, showed
  **16 MLB group tiles**. Nothing was missing; the page was mid-load.
- **Why it nearly cost a revert:** I had deployed minutes earlier, so the obvious
  explanation was my own change, and the obvious action was to roll back a fix that was
  working correctly.
- **How to apply:** after a reload, wait for the SLOW wave or assert on it before
  reporting absence -- e.g. require a non-zero card count, or poll until it stabilises.
  An absence measured during a load is a statement about your timing, not the page.
- **The same session's other version of this:** `-p no:randomly` emitted nothing for ten
  minutes and I called it hung; the output was buffered behind `| tail -5`. Both are the
  same error -- treating "I cannot see it yet" as "it is not there".

---
## 2026-09-25 - a CONFIGURABLE default read out of the source is not a production value

FORBIDDEN: quoting a code default as the production setting for anything an env
var can override, without reading the environment.

`_wnba_pregame_refresh_interval_seconds()` returns `int(raw or 14400)`. I read
the 14400 and told the user TWICE that WNBA pregame would next launch "~01:24Z".
It launched at ~23:24Z. Production sets
`SYNDICATE_WNBA_PREGAME_REFRESH_INTERVAL_SECONDS=7200`, so the fallback I quoted
had never applied. Off by two hours, stated as fact in a deploy receipt.

Same shape as the existing "absent is not off" rule: the `or DEFAULT` idiom makes
the source look authoritative when it is only the fallback branch. Read the env,
or say "code default, production unread".
## 2026-09-25 - a rate from ONE observation, in a window containing a restart

FORBIDDEN: reporting a rate computed from a single event -- doubly so when the
window contains a deploy or restart that changes the behaviour being counted.

I reported the refresh self-collision rate as "~1 per 16 min" from ONE refusal in
a window spanning a deploy restart. Measured on a clean window (22:56:21Z ->
23:25:33Z, single deployed commit): 7 refusals in 29.2 min = 1 per 4.2 min,
across 5 distinct holder runs. Four times higher, and it had been used to
characterise how significant the remaining defect was.

One event gives an interval, not a rate. It cannot tell "rare" apart from
"I happened to look between two of them".
### 2026-09-26 — FORBIDDEN: keying a mechanism on a field without reading what that field actually holds IN THE CASE THE MECHANISM HANDLES -- and writing the fixture from the same assumption, which makes the test agree with you.

- **What I believed:** that a board group's state (`hasLive`/`allFinal`, from its rows'
  `market_state`) tracks its game, so a timeless doubleheader group could be matched to
  the chip in the same state.
- **What production held:** `market_state: "pregame"` on a group whose game was in the
  TOP OF THE 9th and whose own tile rendered LIVE. Measured 2026-09-25 22:39Z on served
  `c081d2e3`. The pass computed `want = "pregame"`, never matched the live chip, and the
  rail seated that game twice -- the exact symptom the fix was written for.
- **The field is unreliable PRECISELY where the mechanism needs it.** A group goes
  timeless because its markets were pulled when the game started; the same staleness that
  removes its clock is what leaves its state behind. So the one case the pass exists for
  is the one case the field lies in. That is not bad luck -- it is a reason to expect it.
- **THE TESTS AGREED WITH ME BECAUSE I WROTE THEM TO.** The scenario fed the timeless
  group `market_state: 'live'`, a value production does not produce there. Reachability
  was proved -- the test did fail without the change -- and it was still vacuous about
  the real world. **`off != on` proves the branch executes, not that its input exists.**
  A fixture built from the assumption cannot test the assumption; the shape has to come
  from a reading.
- **What replaced it needs no field at all:** elimination. When the ordered passes have
  claimed every chip but one and one timeless group is left, the pair is forced by the
  bucket's own definition. Prefer a rule that derives from structure over one that
  believes a value.
- **A second defect rode along, unnoticed until the rewrite:** the old per-group loop
  handed the first of two same-state timeless groups a chip by ITERATION ORDER -- a wrong
  merge, which on this rail HIDES A GAME. It had passing tests too.
- **Cost:** two deploys, and a production failure that a single payload read before
  writing the pass would have prevented.

---
### 2026-09-26 — FORBIDDEN: guarding one ARM of an if/else when you mean to EXCLUDE. The item does not drop out -- it falls into the other branch, silently reclassified.

- **What I wrote:** `if (at === null && !resolvesChipById(group)) untimed.push(group); else
  groups.push({ at, key })`, intending "skip this group".
- **What it did:** sent the skipped group into the `else` -- the TIMED list -- carrying
  `at: null`. It then sorted against real timestamps, where `null - number` is `NaN`, and
  the ordered pass handed out every chip. The group I meant to exclude took the pairing and
  the group that needed one got nothing.
- **Why it was hard to see:** the suite stayed green (22 passed), because no existing test
  had two startless groups in one bucket. The symptom only appeared when I drove the
  function directly with the measured production shape.
- **How to apply:** to exclude, test the DISCRIMINATOR first and make the exclusion its own
  terminal branch -- `if (at !== null) {...} else if (!excluded) {...}`. A condition
  tightened on one arm of a binary is not a filter; it is a re-router.
- **AND THE SECOND ERROR WAS THE INSTRUMENT.** I concluded "the change does the opposite of
  its design" from a probe that iterated CARDS while the card list was empty, so the column
  that would have shown the exclusion working printed nothing at all. An empty collection
  prints as silence and reads as evidence. **Check that your probe returned a non-empty
  population before drawing anything from what it did not show** -- the same rule as
  `feedback_null_result_needs_a_live_population`, applied to a debug print rather than a
  query.
- **Cost:** one wrong public statement ("behaviour is UNKNOWN"), one backed-out change that
  was correct in design, and a ledger entry that had to be withdrawn.

---

### 2026-09-27 — FORBIDDEN: fitting a correction without reading the PROVENANCE of the inputs the grade ran on. A stale input produces a bias that looks exactly like a model defect, and the correction you derive from it is a new defect you deployed yourself.

- **What happened.** I graded NCAAF's live totals estimator, measured a signed bias of
  **-2.165 points**, fitted `shift +2.165`, validated it (worst predicted-probability bucket
  0.1463 -> 0.0492, plus an out-of-sample check), shipped it, and deployed it. The grade had
  run against `sp_ratings_2026.json` stamped `fetched_at 2026-09-05`, `verified=False` --
  **22 days stale**. Re-run over the SAME dates with the ratings production actually uses:
  uncorrected bias **+0.171**, CI over games [-1.176, +1.538], and my correction took the
  worst bucket from **0.0556 UP to 0.1558**. The margin correction (+1.06) was the same
  story: 0.0411 -> 0.0869.
- **Why:** the `-2.165` was a property of the INPUT, not of the simulator. A model fed
  three-week-old team ratings really is biased -- and correcting the model for it bakes the
  staleness into the estimator, so the correction is wrong by exactly that much the moment
  the ratings refresh. Production refreshes them.
- **The harness printed it every single time:**
  `[sp_ratings] season=2026 source=cache teams=138 fetched_at=2026-09-05T21:43:09 verified=False`.
  I read `teams=138` (the field that says the ratings EXIST) and never read `fetched_at` or
  `verified` (the fields that say whether they are the ones production uses). Same shape as
  `feedback_read_the_field_you_already_have`, applied to an input rather than a payload.
- **How to apply:** a grade that produces a CONSTANT must print, and its ledger row must
  quote, the provenance of every input it fitted on -- for a cache: the fetch time, the
  freshness verdict, and how that compares with what production reads. Absent provenance is
  STALE, not fresh. And before deploying a correction, re-run the grade once against
  deliberately-refreshed inputs: if the constant moves materially, you measured the input.
- **Second rule, from the failed verification.** I then tried to verify the fix in production
  by pairing `live_model_prob_over` per `(game, market, line)` across two board snapshots.
  Pairing controlled for ROW IDENTITY but not for GAME STATE, and the snapshots were 8.5
  minutes apart: rows swung ±0.14 to ±0.27 because teams scored, against a predicted effect
  of ~0.10. **5 fell, 5 rose.** A paired design whose confounder is larger than its effect
  measures nothing -- match on the state the quantity depends on (period, clock, score), or
  say the reading is unobtainable. The mean moved the predicted direction and that was NOT
  evidence.
- **Cost:** two corrections deployed to production that made live totals and spreads
  calibration worse for about an hour, a retracted "the bias drifts across the season" claim
  that was an artifact of low-n midweek dates landing in one half of a split, and three
  ledger rows that had to be corrected by a fourth.

---
## 2026-09-28 — AN ALLOWLIST IS AN ELIGIBILITY CHECK, NOT A TRANSPORT. And a check that answers about the wrong object is worse than one that fails.

Lane `nfl-ncaaf-live-props`. Three beliefs overturned, all the same shape: **a
check answered, and it was answering about something other than what I asked.**

- **FORBIDDEN: reporting a path "retrievable" because it is in
  `HOT_ARTIFACT_PATTERNS`.** The allowlist is read on THREE sides — the worker
  before it sends, web on ingest, web on stream/export — and **none of them moves
  a file.** An artifact written on refresh-worker (which serves no HTTP) is not
  reachable from web (which serves the stream route off WEB's disk) until
  something explicitly PUBLISHES it. Allowlisting alone turns the retrieval from
  **403 into 404**, which is the worse failure: 403 says "not permitted", 404
  says "the capture never happened". Measured: a capture family was allowlisted,
  deployed, and one verification away from being reported as done. **Before
  calling an artifact retrievable, name the line of code that SENDS it.**

- **FORBIDDEN: treating a preflight `CLEAR` as validating its own baseline.**
  `deploy_preflight.py` checks a baseline's **AGE**, never its **truth**. A
  watcher whose API call 400'd left `LIVE` empty, so `git show ":<path>"` read
  the **WORKTREE INDEX** — which contained the change — and fed back a baseline
  identical to the expected post-state. It returned CLEAR. **An empty git rev is
  not an error, it is the index**, and any `"$REV:path"` built from a variable
  must hard-stop on an empty `$REV`. Every baseline must be read from a NAMED live
  SHA, with an assertion that it reads as expected before the deploy proceeds.

- **FORBIDDEN: `echo "$X" | grep -qv PATTERN` as a "not that state" test.**
  `echo ""` emits one EMPTY line, which does not contain the pattern, so grep -v
  matches and exits 0. A monitor built this way reported **"SPACING OPEN"** off a
  preflight that had printed nothing at all — an absent verdict read as a green
  light. Parse the verdict token explicitly (`grep -oE '^(CLEAR|HOLD|...)'` into a
  `case`) and give **unparseable its own branch that is NOT permissive**. This is
  the standing "unknown must not default permissive" rule reappearing in shell.

**Cost:** none shipped — all three were caught before they authorised anything,
the second because the numbers looked too convenient and the baseline was re-read
by hand. **What caught them was the same habit each time: asking what would make
this instrument read healthy while the thing it measures is broken.**

---
## 2026-09-28 (session 249f998b, lane mlb-prop-grading-player-match) - a VOID count's size is not evidence of a join failure

- **What was believed:** 9,728 MLB `prop_player_not_in_boxscore` rows against ~156k graded were "too large to be DNPs alone", so they had to be player-name match misses.
- **What was measured:** 94.8% are true DNPs (2,882 rows over 4 dates, checked against StatsAPI box scores under any spelling); the name misses are exactly two players. Books post props before lineups and the recorder keeps every priced side, so bench players' props are a large, legitimate void class (~9% of prop rows).
- **Rule:** before calling a skip reason a join bug, classify a sample of it against the source of truth. Volume alone says nothing about which class dominates.

---
## 2026-09-28 (session f9c8d1b9, lane live-props-model-probability) - A producer test that asserts its OWN field proves nothing about the reader

**What happened.** `#539` (2026-08-23) priced soccer's one-sided live props and its eleven tests asserted `edge_vs_modelled_fair_pct` on the projection. The board reads that number through `layer2_board._modelled_fair_edge_for`, which ALSO requires `modelled_fair_side` -- a companion field only the pregame sweep wrote. Every test was green for five weeks while the path delivered 0 of 3,547 edges to the board and the scorecard.

**Rule:** when a producer writes a field another module consumes, at least one test must drive the real producer into the real consumer and assert the CONSUMER's output. And a lane hypothesis naming one end of a pipeline ("recording drops it" / "grading drops it") must be tested at every hop between the two, not only the two named ends -- here the defect sat in neither.

---
## 2026-09-28 — an "unreproducible CI flake" was a production bug: never `print` inside a signal handler (session 2aff0397)

BELIEF OVERTURNED: `test_worker_shutdown` end-to-end failing once on CI with empty output was treated as unexplained noise. It was the shutdown handler losing its record: a signal that lands while `sys.stdout`'s BufferedWriter lock is held runs the handler inside that flush, every `print` there raises "reentrant call", and the `finally: os._exit(0)` exits silently -- the RECORD_FAILED fallback line too, because it also used `print`. Fixed with `os.write` (#113). RULE: in a signal handler write with `os.write` to a raw fd, never `print`/logging. And when a test fails with no diagnosis, the first push is DIAGNOSTICS in the assertion message (here: the child's returncode), not a re-run -- the next CI failure then named the mechanism.
## 2026-09-28 (session 273dc243, lane nfl-live-gameline-full-rows) - "VERIFIED" on a slate where nothing priced verified only the refusal path

**What happened.** `nfl-live-resim-activation` closed its goal on `sources_seen {pregame: 16}` -- every lane a refusal. That reading proves refusals are rejected; it cannot see the PRICED lane, which carried snake-case fields the join never reads, and named games by tri-code where the grid uses full names. On 09-27 the re-sim priced 1-4 games per tick for ten hours and the join indexed zero. The unit fixtures named games "Dallas Cowboys" -- the cheaper path production never takes. Same class as the entry above, second instance the same day.

**Rule:** a join verification must include at least one ACCEPTED record (`indexed >= 1`) on production-shaped input; an all-refusal reading verifies the refusal branch only and must say so. Fixtures feeding a join must use the identifiers the production producer actually emits (here: the projection CSV's tri-codes).

---
## 2026-09-28 (session acb76ba7) - Two readers of one fact must read the SAME copy; fixing one reader's location can blind the other

The lane marker `.current-lane.<session>` had two copies once sessions moved into worktrees (primary tree, worktree), and three guards read them: `lane-guard` and `deploy-guard` read the primary, `lane-postwrite-check` read the worktree. `lane_open.py` wrote only the worktree copy, so deploy-guard refused a lane that held its claim. Moving the write to the primary tree (`02338706`) fixed that and, within minutes, made `lane-postwrite-check` report `Your lane: 'none'` on the session's own file. Worse, the pre-existing split had let a STALE worktree copy silently GRANT another lane's file (4 of 6 new tests fail on the old hook). The same week, `snapshot-index` read `nfl_live_lens.json` while the join it diagnoses read `nfl_live_resim.json`: the same shape, a diagnostic and its subject resolving one name to two files.

**Rule:** before moving where a fact is WRITTEN, enumerate every READER and the root each one resolves (grep the marker name in `.claude/hooks/`). Make readers resolve through ONE shared lookup, or import the writer's map (`_LIVE_GAMELINE_SNAPSHOT_PATHS`), never a parallel copy. A test must cover the case where the copies DISAGREE, not only where one is missing.

---
## 2026-09-28 (session acb76ba7) - A half-removed session worktree is held open by the Bash tool's own cwd, not by a leftover process

`session_worktree.py close` half-removed a worktree three times in one session: the admin dir and every file were gone, the empty directory and branch remained, and the retry refused with "state is unknown". Each time, the `close` ran from PowerShell with the primary tree as its cwd, and the harness's working directory had already moved out. The holder was the Bash tool: its cwd persists between calls, and the last Bash call had been `cd <worktree> && ... land`. Moving Bash out (`cd /c/tmp`) before the close removed the cause. The three-condition check (0 files, unregistered, 0 commits on `origin/main..session/<lane>`) then made `close --force` safe every time.

**Rule:** before `close`, move EVERY shell that ever `cd`'d into the worktree back out: Bash, PowerShell, and the harness directory. Only a checked `--force` may clean up a half-removed tree: the folder is empty, `git worktree list` no longer shows it, and the branch has 0 commits beyond `origin/main`.

---
## 2026-09-28 (session f9c8d1b9, lane live-props-model-probability) - Interval coverage is not calibration; and sample on the clock the product prices on

**What happened.** I shipped per-market WNBA residual tables and widened rebounds/assists to a line grid on the strength of 90%-band coverage of 91.5-91.8% OUT OF SAMPLE. An hour later, line-level calibration -- predicted vs observed P(final >= line) over the exact ladder the lens publishes -- showed rebounds overstating overs by 18.5 pp and threes by 18.7 pp even in-season. Coverage was true and irrelevant: a band can hold 90% of finals while every over near the centre is mispriced, because the distribution is skewed and one sigma per bucket ignores player scale. Separately, the grader sampled each player right AFTER their own event, which inflates the pace the projection extrapolates; production prices on a clock tick.

**Rule:** before pricing a new market or widening a grid, gate on LINE-LEVEL calibration (reliability by predicted-probability bucket over the lines actually published), not on interval coverage. Measure with the sampling design production uses (a clock), not one triggered by the outcome being predicted.

---
## 2026-09-28 — A POPULATION IS PART OF A CONSTANT. Four findings reversed when the population changed, and three retractions came from measuring the wrong pair.

Lane `layer2-triad-alignment`. Every item below was measured, believed, and then
overturned by a SECOND measurement in the same session.

- **FORBIDDEN: selecting a constant on one population and shipping it to
  another.** A spread-shrinkage `k=3` was selected on 132,136 rows with a genuine
  convex minimum and a -0.003479 held-out Brier gain. On the 16,967 rows the BOARD
  ACTUALLY QUOTES it was monotonically HARMFUL, and it made starters NARROWER --
  the opposite of the defect. The league prior it shrank toward had a median
  `rushing_yards` sd of 10.2 computed across 564 "rushers" who are mostly
  marginal, against a workhorse's ~25. **State the population next to every
  fitted constant, and re-run the selection on the population that will consume
  it.**

- **FORBIDDEN: comparing arms scored on different row sets.** The first pilot
  showed shrinkage winning by -0.0516. It was entirely composition: shrinkage
  gives a positive sd to players whose games were all identical, rows production
  drops outright, so one arm scored 11,038 cells and the other 15,659. Pinned to
  a common population the effect VANISHED and the real one was 15x smaller. A
  `cells` count that differs between arms is the tell.

- **FORBIDDEN: reading a DERIVED anomaly as evidence about its INPUT.** I reported
  a "placeholder 0.500 market fair" on 24% of NFL rows and the user approved
  fixing it. Recomputing the de-vig from prices in the same payload gave
  0.4964-0.5002: NFL props are quoted near-symmetrically, so 0.500 is CORRECT.
  The spread of the EDGE was evidence about the MODEL and I attributed it to the
  MARKET. `edge = model_prob - fair`, so a 0.500 fair is simply where a
  confident-but-wrong model shows its widest arithmetic gap.

- **FORBIDDEN: calling an estimator biased by comparing a MEAN to a SINGLE
  OUTCOME.** I reported the NFL prop mean as "often far from the line". Comparing
  two EXPECTATIONS -- the rolling mean against the player's OWN future realised
  mean -- gives 0.983 / 1.019 / 1.000 / 0.978 and is flat in n. The estimator is
  unbiased. What looked like bias was selection on a noisy estimate plus a ~20%
  mean-vs-median gap that is arithmetic on right-skewed markets (`passing_yards`
  at 0.987 is the control: QBs always play, the skew vanishes).

- **FORBIDDEN: accepting a constant at the edge of its grid.** An interceptions
  sweep picked `k=24`, the largest candidate. Extending the grid showed the fit
  Brier still falling at k=128 -- `#471`'s "more shrinkage is free" artifact --
  and k=24's HELD-OUT gap was 0.1474, the WORST of every k tried. Where there is
  no interior minimum, say what the monotone decline MEANS (here: a QB's own
  interception rate carries no measurable signal) rather than picking a number
  off the slope.

**AND THE ONE THAT WAS NOT A CONSTANT.** `calibrate_nfl_cover_probability_blend`
reads the model through `backtest_nfl_props._rate_from_log`, a LOCAL COPY of
`player_rate` whose docstring said "identical math" and still called `pstdev`.
Two blend re-fits run specifically to re-calibrate ON the new spread never saw it,
and returned numbers identical to SIX DECIMAL PLACES across eight markets. **Two
independent runs agreeing that exactly is impossible** -- that, not the code, is
what exposed it. A second copy of an estimator does not announce its drift; the
docstring asserting it is identical is the thing that makes the drift invisible.

---
## 2026-09-28 (session 2aff0397, lane nfl-game-day-injuries) - A flag is set on the service whose LOOP reads it; a file is read on the service whose DISK holds it

- What we believed: `SYNDICATE_SLATE_PHASE_OBSERVE` belonged on refresh-worker, next to the capture flag; and the ESPN game-day `statuses_<date>.json`, written under `SYNDICATE_DATA_ROOT`, was "disk-backed" and so reachable by the starting-soon trigger.
- What was actually true: observe mode runs only in `live_refresh_loop._run_live_refresh_tick`, which runs on live-odds-worker; refresh-worker ignores the flag. The trigger also runs on live-odds-worker, and the statuses file was written on refresh-worker's disk, never published (not in `HOT_ARTIFACT_PATTERNS`), so the trigger's input did not exist where it ran.
- How we found out: the user set the flag, redeployed, and saw no `SLATE_PHASE` line. Tracing the reader showed the service.
- The rule going forward: before telling anyone where to set a flag, grep for the function that reads it and name the SERVICE whose entrypoint reaches that function. Before calling an input "disk-backed", name the service that WRITES it and the service that READS it; if they differ, the file must be allowlisted in `HOT_ARTIFACT_PATTERNS` AND published by its producer, with a test that fnmatches the reader's pull pattern.
- Cost: one wasted deploy cycle for the flag, and a trigger that was inert since it merged (#111).
## 2026-09-28 — A LANE BLOCK AND THE DEPLOY LEDGER DISAGREED FOR A DAY, AND THE LEDGER WAS RIGHT. Plus: a verdict is a claim and ages like one.

Lane hygiene pass, session 4ab694ed. Both items below were found by AUDITING my
own prior verdicts, not by anything failing.

- **FORBIDDEN: trusting a lane block's status over `deploys.md` when they
  disagree.** `worker-memory-heartbeat` read "GOAL: NOT MET -- the code is LANDED
  and DELIBERATELY NOT DEPLOYED" for a full day while `deploys.md` recorded
  `87ce81d7` deployed and VERIFIED, with both halves of that lane's own
  Verification satisfied (181 samples, 0 of 180 over the preflight limit,
  CLEAR x3). **A lane saying "not deployed" about something deployed and
  verified is worse than a stale OPEN lane: it is a FALSE NEGATIVE sitting
  exactly where the next session looks first.** The deploy ledger is written at
  the moment of measurement; a lane block is written from memory afterwards. When
  they conflict, the ledger wins and the block gets corrected.

- **FORBIDDEN: an all-refusal reading reported as a join verification.** Restated
  here from session `273dc243`'s entry because it landed on MY lane and I am the
  one who has to not repeat it: `nfl-live-resim-activation` closed `GOAL: MET` on
  `sources_seen {pregame: 16}` -- sixteen REFUSALS and no accept. The accept path
  was broken the entire window (snake_case fields the join never reads,
  tri-codes against a full-name grid); the re-sim priced 1-4 games per tick for
  TEN HOURS and the join indexed ZERO. **A verification that only ever exercises
  the reject branch verifies the reject branch.** It must say so, and it must not
  close a goal about the accept branch.

  This is the same shape as three entries already in this file -- "absence in a
  window isn't absence", "null needs a live population", "presence is not
  reachability" -- and it still got through, because it arrived wearing the word
  VERIFIED and a production timestamp.

- **A VERDICT AGES, SO AUDIT OLD ONES, NOT JUST NEW WORK.** Both findings came
  from re-reading verdicts I had already written and banked. Nothing failed to
  prompt the audit; a survey of open lanes did. **When correcting a verdict, keep
  the superseded text beneath the correction** rather than overwriting it -- a
  silently rewritten verdict teaches the next reader nothing about why the first
  one was believed.

- **AND THE MECHANICAL ONE:** a whole-file replace in `lanes.md` matched TWICE --
  a peer had written the same verdict phrase -- and would have rewritten their
  verdict. An assertion on match count caught it. **Edits to one lane's block
  must be bounded to that block's line range**, because nothing in this file's
  prose is unique.

---
## 2026-09-28 (session f9c8d1b9, lane live-props-model-probability) - A variant chosen in-season can fail the playoff holdout for a reason outside the variant

**What happened.** Threes rate shrinkage toward pregame, selected on August, cut the worst line-level gap to 3.4 pp there and went to 13.3 pp on held-out September (playoffs) -- worse than the live model -- while Brier skill improved. The shrinkage was fine; the thing it shrank TOWARD, the pregame threes expectation, overshoots by 18% in the playoffs against 8% in-season. Every earlier count-model change today passed the same holdout; this one leaned harder on the pregame anchor and was the only one to fail.

**Rule:** when a change increases a model's reliance on the pregame anchor, check the anchor's own bias in the evaluation regime (actual vs expected by period) before shipping, and keep the held-out period out of selection even when it would "rescue" a variant. Better Brier with worse line calibration is not a pass.

---
## 2026-09-28 FORBIDDEN: telling the user a market is "not scored" off a PRINTED LABEL without reading the served payload's keys `[lane gameline-spread-total-scoring, session 3b474634]`
- **What happened.** The nightly snapshot printed `spreads=399(refused) totals=372(refused)`, and I reported to the user that totals and spreads were not scored. They had been scored on every build since scorer contract 3 (2026-09-08), under `live_gameline_score.point_forecast`, and retained in history since 09-24. The label predated contract 3: it meant "not in the Brier", and nothing updated it when a second scoring rule shipped.
- **The field that settled it was already served.** `point_forecast`, `point_forecast_markets` and `scorer_contract: 3` sat in the same payload the label summarised.
- **Rule.** Before stating that something is not measured, read the payload's own keys for it. A printout is an observer with its own vintage, and a label that describes one scoring rule goes silently wrong when a second one ships. Fixed in `a8b61e7e`: markets are now labelled by HOW they are scored (`brier` / `point-forecast` / `unscored`).
## 2026-09-28 FORBIDDEN: flagging a delegated lane's work as DRIFT without reading the consent and user-request lines first `[lane gameline-spread-total-scoring, session 3b474634]`
- **What happened.** Polling lane `live-props-model-probability`, I reported to the user that it had drifted into four hours of WNBA model tuning. Every step was USER-REQUESTED in that session ("widen WNBA rebounds and assists too", "build the player-scaled spread model", ... "Ship it now"), and each cross-lane write was recorded with consent in `layer2-triad-alignment`'s block. I judged from the commit subjects against the lane's written Goal.
- **Why it matters.** A monitor that cries drift at the user's own direction trains the user to ignore it -- the same failure as a guard that cries wolf. The lane Goal is what the opener wrote; the user can redirect a session in its own chat, and the ledger records it where the WRITE lands, not where the goal is.
- **Rule.** Before calling work outside a lane's goal "drift", grep the lane's block AND the blocks of every lane whose files it touched for `USER-REQUESTED` / `user decision` / consent lines. Drift is work nobody asked for; redirected work is not drift, it is a goal the ledger has not caught up with.
## 2026-09-28 FORBIDDEN: writing a test from the same mental model as the code, on a fixture you invented rather than one read from production `[lane nhl-board-row-date-mismatch, session 4ab694ed]`
- **What happened.** `fae9aab8` compared a predictions row's `date` to the requested date with `str(...)[:10]`. I wrote `test_a_timestamp_shaped_date_compares_on_its_date_part` to cover timestamps — and it **asserted the bug**, pinning the truncation as correct behaviour. It passed while production dropped real games, and I shipped it to two services.
- **Why the test could not fail.** Its fixture was `2026-09-29T21:00:00Z` under a `2026-09-29` filename — a time of day where UTC and Central agree. Every other fixture in the file used bare dates, because bare dates were all I had looked at. The real rows are `2026-01-26T00:00:00Z` and `2026-01-26T01:00:00Z` under `predictions_2026-01-25.csv`: 6 PM and 7 PM Central **on the 25th**, dropped. Six affected dates served 13 of 16 games, and one of them (05-24) went further and served **05-25's slate** — the guard against serving another date's games caused exactly that.
- **The tell was available before the failure.** The code and the test were written in the same sitting from the same assumption, and the fixture was invented to match it. A test whose inputs come from the author's model can only confirm the model.
- **Rule.** When a guard compares a field, take the fixture from a PRODUCTION row, not from your head — and pick the row where the two candidate interpretations DISAGREE (here, a late game crossing midnight UTC). If no fixture in the file can distinguish the right answer from the wrong one, the file tests nothing about that decision. Pair it with an `off != on` test that patches the old behaviour back in and reproduces the defect.
## 2026-09-28 FORBIDDEN: admitting a sport to a capability set without checking that its producer stamps the field the consumer gates on `[lane nfl-live-resim-activation, session 4ab694ed]`
- **What happened.** `LIVE_GAME_STATE_JOIN sport=nfl supported=False reason="no live status source wired for nfl"` while PHI @ CHI was in Q2. The pieces looked present: `scripts/poll_nfl_live_state.py`, `syndicate/features/nfl/live_game_state.py`, and the ESPN fetcher already listing `nfl`. Adding `"nfl"` to `_LIVE_GAME_STATE_SPORTS` with a capture reader would have looked complete and done **nothing**.
- **Two independent gaps, both invisible from the set.** (1) `poll_nfl_live_state` never stamped `fetched_at`; `poll_ncaaf_live_state` always has. The football arm skips any capture whose age it cannot establish, so an **unstamped record fails identically to an ancient one** — every capture discarded as stale, silently. (2) Nothing kept the capture fresh: its only caller was settlement's lazy capture, which fetches when the record is ABSENT or EMPTY, never when merely STALE, so a capture written pregame sat unrefreshed all game. A reader that must not fetch plus a writer that cannot refresh is no source at all.
- **The code said so and I nearly did it anyway.** The comment above that set already read: *"Adding a sport here without a source that actually carries finished matches turns a stated 'unsupported' into a silent 'supported, corrected 0'."*
- **Rule.** Before admitting a sport/venue/market to a capability set, trace the full round trip on the WORKING sibling and diff it field by field: who writes the record, on what cadence, and does it stamp every field the consumer's gates read. A stated `supported=False` is more valuable than a silent `supported=True, corrected=0`, so the arm must degrade to a NAMED reason.
## 2026-09-28 FORBIDDEN: using `deploy_preflight.py` as a status probe, and trusting its HOLD text's window figure `[lane nhl-board-row-date-mismatch, session 4ab694ed]`
- **Two separate defects in the same tool, both measured.**
- **(1) A probe destroys the verdict that authorised the deploy.** Preflight WRITES `.syndicate/deploy/preflight/<service>.json` on every run. I ran it with `--no-expectation "status probe"` to check a deploy's progress, and it overwrote my `CLEAR` (00:14:48Z) with `OFF_MAIN` (00:17:30Z) — from a stale local git view that had not fetched. The deploy had already fired at 00:15:00Z so nothing was blocked, but had it needed re-verification there would have been no record that it was ever cleared. Use the deploys API or `pending_deploys.py` to read status; preflight is for authorising, not observing.
- **(2) The HOLD text's window is 3x too large.** It says *"the ~4 min after a `BOARD_BUILD_TIMING` line"*. Measured over 13 consecutive refresh-worker builds during a live game: finishes every **180.6s**, each build **101–134s wall**, leaving an idle of **65.9s mean / 70.8s max**. And the guard forces preflight and the deploy into SEPARATE tool calls — a chained `preflight && render_deploy` is refused whole because `deploy-guard.py` evaluates the STORED verdict at PreToolUse, so neither runs. Two ~30–50s calls do not fit in 66s, so under a live-game cadence the documented window does not exist and an operator following that sentence reaches for `--allow-mid-build` believing they were unlucky.
- **Rule.** Measure the idle window from `BOARD_BUILD_TIMING` gaps minus each `wall_s` before planning a refresh-worker deploy; do not take the HOLD text's number. Never chain preflight with the deploy. And never run preflight to "check on" a deploy — it is a writer.
## 2026-09-29 FORBIDDEN: attributing a CAUSE to a coverage pattern before reading the artifact's `generated_at` against the state of the world it describes `[lane layer2-triad-alignment, session 4ab694ed]`
- **What happened.** `nfl_prop_projections_2026_wk3.json` held 276 rows where a known-healthy week-1 artifact had 966. The shape looked diagnostic: 7 of 32 teams absent, 6 games with exactly ONE side present, 1 game with NEITHER, seven more teams at a single player, and 41% of all rows on two teams. I reasoned that a truncated run leaves CONTIGUOUS games unfinished and this does not, therefore it must be a per-team data dependency failing — and named `rating_source=nflverse_pbp_epa_rolling` as the likely culprit. I wrote that into the ledger and proposed a row-count ratchet guard.
- **All four shapes had one innocent cause.** `generated_at 2026-09-28T16:24:03Z`, and at that moment **15 of the 16 week-3 games had already been played**. `nfl_props_rows_for_week` joins ODDS to sim rows, so it can only emit a player whose props are still QUOTED; a finished game has no prop market. Absent teams = teams whose games were over. One-sided games = nothing. The 41% = the only unplayed game. The producer was correct end to end.
- **The refutation was in fields I had already fetched.** `player_id_source: current_season 262`, `rate_source: current_season_rolling 229` — player resolution worked on every row, which a failing pbp dependency cannot produce. I read those fields only after the conclusion was already in the ledger.
- **The comparison was also not like-for-like, and that made the wrong answer look quantified.** 966 was built BEFORE any week-1 game had played. Putting 276 next to it and reporting "29%" dressed a category error in a percentage.
- **Cost of being wrong here.** The proposed fix — refuse a build that is a small fraction of the previous row count — would have fired on a CORRECT build run late in the week, and would have said nothing about the real defect, which is that nobody had built the next week's artifact at all.
- **Rule.** An artifact's shape is evidence about the moment it was built, not about the code that built it, until you have read its `generated_at` and asked what was true then. Before attributing a coverage gap to a dependency: (1) read the build timestamp, (2) ask what the world looked like at that instant — which games were live, which markets were quoted, (3) read the per-row provenance fields (`*_source`), which usually say outright whether a stage succeeded. Only a pattern that survives all three is about the producer. And never compare two artifacts' row counts without checking they were built at the same point in their slate's life.
## 2026-09-29 FORBIDDEN: trusting a metric's NAME for what it compares against — "real market hit rate" never read a price, and its headline was the majority-class null `[lane nfl-live-resim-activation, session 4ab694ed]`
- **What happened.** `scripts/backtest_nfl_props.py` has a section titled `SECTION 3 -- REAL MARKET HIT RATE (wherever a real quoted line exists)`, persisted as `section_3_real_market_hit_rate`. It reported `anytime_td: n=6583, hit_rate 0.774, brier 0.1674`. I read that as evidence the model performs against the market. It is neither of those things.
- **It never reads a price.** The loop pulls `over_price`/`under_price` from nowhere; it takes the LINE and the OUTCOME only, and scores `predicted_side_hit = (1 if prob > 0.5 else 0) == outcome`. There is no market probability anywhere in the computation, de-vigged or otherwise. The word "market" in the name means "a real quoted line existed for this row", not "compared against the market".
- **And the headline number is the majority-class null.** anytime_td's base rate of scoring is **0.2209**, so always calling "no TD" is right **0.7791** of the time. The reported hit rate was **0.774**. The model's probability is almost always below 0.5, so its "side call" is *no* on nearly every row and it scores the null — an impressive-looking 77% that a constant function achieves.
- **What the real comparison showed, once built.** De-vigging the paired prices (~100% two-sided on eight of nine markets) and scoring Brier model vs market on 2024: **all eight lose**, every CI clear of zero, the 2025/26 holdout worse, and a 63-segment sweep found **zero** segments where the model wins against ~3 expected by chance. The structure is the tell — the model is at parity with the book exactly where it claims NO edge (`receiving_yards edge [-0.03,0.03)`: +0.00002) and worst where it claims the BIGGEST edge (`edge [-1,-0.15)`: +0.09441). The "edge" is model error, and the board seats rows BY edge.
- **Why the name was load-bearing.** Eight markets carried `status: unmeasured` while a section named for the market sat in the same report saying nothing about the market. The 2026-09-11 "Withhold, all sports" decision was waiting on exactly this measurement, and the metric that looked like it had been taken had not been.
- **Rule.** Before citing a metric as evidence for a claim, read the code that computes it and name the two things it compares — not the title, not the key, and not the docstring. For any accuracy number ask specifically: (1) what is the COMPARATOR (a constant baseline, the market, nothing), and (2) what does a TRIVIAL predictor score on this same metric and population? A metric whose null is unstated is unreadable: `0.774` and `beats the baseline` were both true and neither meant what the name implied. When the comparator is the market, the price must appear in the computation — if you cannot point to the line of code that reads it, it is not a market comparison.
## 2026-09-29 FORBIDDEN: reading "production has this artifact" as "a publisher put it there" — feed_live is on production because it is GIT-TRACKED, and `is_hot()` is False for the very files that are already there `[lane mlb-live-prop-grader, session 4ab694ed]`
- **What happened.** `/api/ops/artifacts/export?pattern=*feed_live*` returns `count=146` on production, so I planned to publish 472 more the same way. `/api/ops/artifacts/publish` returned **403 `relative_path is not an allowed hot artifact`**. feed_live matches none of the 200 `HOT_ARTIFACT_PATTERNS`.
- **The discriminating check, which is the whole lesson.** I ran `is_hot_artifact_relative_path()` against a path production ALREADY SERVES: `mlb_source/source_artifacts/data/raw/statsapi/feed_live/2026/2026-06-14/822722.json.gz` → **False**. Those 146 files were never published. They are git-tracked and arrive in the DEPLOY CHECKOUT. Two different mechanisms put bytes on that disk, and `export` cannot tell them apart because it scans the disk, not the allowlist.
- **Why the wrong reading is expensive.** It makes "just publish the rest" look like a chore rather than a decision. The only two real routes both cost something permanent: adding feed_live to `HOT_ARTIFACT_PATTERNS` also widens what every worker PULLS (78 MB, recurring, on services whose scarce resource is memory) to serve a ONE-OFF backtest; committing the delta is 61.6 MB into a tree where `data/` is deliberately a lossy cold-start subset. Neither is visible if you assume the publisher already handles this family.
- **Rule.** Before planning to publish an artifact family, check `is_hot_artifact_relative_path()` on a path that family ALREADY has on production — not on the new path you want to add. If the existing one is False, the family arrives by some other mechanism (git checkout, bootstrap, mirror refresh) and the publish route was never its path. And when the allowlist is the blocker, remember it is not a permission list: it governs PULLS as well as publishes, so widening it to push once buys a recurring cost on every worker.
- **The cheaper answer existed.** feed_live is re-fetchable from `statsapi.mlb.com/api/v1.1/game/<pk>/feed/live` — public, unauthenticated, immutable once final — via `vendor/mlb_bettingv2/tools/datasets/backfill_statsapi_feed_live.py`. Verified rather than assumed: a rebuild of 2026-05-28 gave **6/6 MEASUREMENT-identical** games and **0/6 byte-identical** ones. **Byte-identity is the wrong test** for anything gzipped — gzip stores a timestamp, so two honest captures of the same immutable game differ in bytes while agreeing on every number you would compute from them. Pin the corpus DEFINITION and a rebuild command; do not ship the bytes.
## 2026-09-29 STANDING: claimed edge running ANTI-correlated with realised return is now measured in TWO sports — treat "ROI falls as the EV threshold rises" as the primary read, not any single threshold's CI `[lane mlb-live-prop-grader, session 4ab694ed]`
- **What was measured.** MLB LIVE prop probabilities graded against the price they were served at (584 rows, 7 dates): ROI by nested EV threshold ran **EV>0.00 +0.0060, >0.05 -0.0044, >0.10 -0.0200, >0.20 -0.1224**. Not one of those CIs clears zero on its own — n is small and the odds average 1.94 — so read individually the honest verdict on each is "indistinguishable from zero", and the study would report NOTHING.
- **The order is the evidence the individual intervals cannot carry.** Four nested subsets, each a strictly more confident slice of the same population, declining monotonically. Earlier the same session, the NFL prop sweep found the identical structure from the other direction: the model sat at parity with the book exactly where it claimed NO edge (`receiving_yards edge [-0.03,0.03)`: **+0.00002** over 3,085 rows) and at its WORST where it claimed the BIGGEST (`edge [-1,-0.15)`: **+0.09441**). Two sports, two harnesses, same shape.
- **Why this needs saying.** A per-threshold report with wide CIs invites "nothing is established, move on", and that is how a real defect survives a measurement. The thresholds are NOT independent tests, so the multiplicity argument that would rightly deflate four scattered findings does not apply to a monotone trend across nested subsets. Conversely the trend is NOT a licence to quote any single number as established — it is evidence about the RELATIONSHIP between claimed edge and realised return, and that is the thing worth acting on.
- **Rule.** When grading a model against a price by EV threshold, always report the nested series and read its ORDER first. A monotone decline is a finding even when every CI includes zero; a flat or noisy series with one significant cell is not. Always print the bet-everything NULL beside it — the NFL anytime-TD study returned +16.4% on that null and was a join defect, while this one returned +0.0192 with a CI spanning zero, which is what a sound join looks like. And say which of the two you have before quoting anything else.
- **The companion finding, same session, opposite direction.** MLB's live probability is OVERCONFIDENT where it is confident (`[0.55,0.7)`: claims 0.6347, realises 0.5789, n=380, claim above the interval) while NBA's live sigma is TOO WIDE (pooled stdev(z) 0.7744, i.e. UNDER-confident). Opposite signs, one class of defect: **an uncertainty that was published without ever being measured**. Neither is a reason to withhold a market; both are a reason to re-fit against a measured residual.
## 2026-09-29 FORBIDDEN: checking production for ONE property and then diagnosing a DIFFERENT property from the local checkout — I verified the file COUNT against production and still reported a 3.5-month silent regression that was a mirror gap `[lane mlb-live-prop-grader, session 4ab694ed]`
- **What happened.** `live_lens_report_*.json` files on disk showed `liveProps` populated on 7 dates (2026-06-01..06-11) and **zero** on ~70 later dates, including dates carrying 10-14 live games. I reported that as a producer regression silent since 2026-06-11, and said so to the user before pulling anything.
- **It was a mirror gap.** Production holds **238** of those files over **132 dates (04-10..09-30)**; the checkout had **110 / 87**. Fetching the 45 missing dates found **28 carry liveProps** — 09-19 **1119**, 09-20 **999**, 09-23 **988**, 09-26 **935**, 09-12 **959**, and 148 on the day I was looking. The producer was healthy and emitting far MORE than in June.
- **Why this is not just another instance of "check production first".** I DID check production — `export?pattern=*live_lens_report_*&names_only=1` returned 238 vs my 110 — and I read that number, in the same minute, as evidence about file COUNT while diagnosing CONTENT from local files. Verifying one property of a production family buys NO confidence about another property of it. The count told me my mirror was incomplete; I then reasoned as though it were complete.
- **A second thing that made the wrong reading look solid.** Many of the populated dates show `live: 0` at snapshot time, because liveProps PERSIST in the report after games finish. So on a local-only read, "no game was live when this snapshot was taken" and "no live props were captured" are indistinguishable — and the dates I happened to have were disproportionately the ones where they coincided.
- **Rule.** Before reporting that a family STOPPED being produced, or changed behaviour at a date, fetch the actual bodies for the dates you are claiming are empty — from production, not the mirror. A names-only listing answers "which files exist", never "what is in them". And when a count check tells you the local mirror is incomplete, that is a reason to STOP reasoning from local content, not a box ticked. Say which corpus every coverage claim rests on, and if it is the mirror, say that it is a lower bound.
- **Cost:** one wrong claim stated to the user, retracted the same turn. The upside is the real one: the window widened from **584 graded rows over 7 dates** to **~8,100 rows over ~35 dates** once the missing dates were pulled — a ~10x sample that was there the whole time.
## 2026-09-30: a task QUEUED with spawn_task can be landed by ANOTHER session while you are still building it, so re-fetch `main` before opening the PR
- **What happened.** Session 157058fe queued "Fix Windows process-liveness checks" as a suggested-task card. The user started that card, which launched a separate session, and then asked session 157058fe to start the same task. Both sessions built the same fix in parallel. The other session's `67b5f471` reached `main` first and covered more ground: six sites, the two lane-held files (with cross-lane notes), and a zombie-parse fix. PR #119 then hit add/add conflicts on every file and was closed as superseded. This cost about 40 minutes of duplicated work and an extra lane block.
- **Rule.** When asked to start work you earlier queued as a suggested task, `git fetch origin main` and grep for the task's todo id, here `#692 item 3`, BEFORE writing code. Fetch and grep again right before opening the PR. Ask the user whether the card was already started. When a fix touching the same files lands first, close your PR as superseded. Do not merge-resolve it back onto `main`.
## 2026-09-30: an in-process test of a CLI function does not test the CLI, so run the entrypoint once
- PR #122 added three passing tests of `local_production.cmd_down`, and the real `python3 scripts/local_production.py down` then crashed on its first import. pytest had the repo root on `sys.path`; a script run does not. Presence is not reachability, this time at the entrypoint.
- **Rule.** When a change adds an import to a `scripts/*.py` entrypoint, include one test that runs the file as a subprocess from outside the repo with `PYTHONPATH` stripped.

### 2026-10-01 — FORBIDDEN: `x or 0` (or `or {}` / `or ""`) BEFORE the check in a guard that exists to tell UNKNOWN from ZERO. The normalisation IS the unknown-as-zero bug, applied one line early. Test present-None, "", [], absent and unparseable as five separate cases. `[lane soccer-live-gameline-index-diag]`
- What we believed: my guard in `bc8a8340`, `int(diag["games_in_snapshot"] or 0)` inside `try/except (KeyError, TypeError, ValueError)`, sent every unknown game count to "index diagnostics unavailable". I told the owning lane exactly that in a hand-off message: "absent or unparseable ... now returns 'index diagnostics unavailable'".
- What was actually true: `or 0` turns a PRESENT-but-null `None` / `""` / `[]` into a counted `0` before `int()` can raise, so all three still fell through to "no <sport> game in play", the permissive answer the guard was written to stop. Absent (KeyError) and `"many"` (ValueError) were caught; the null family was not.
- How we found out: the owning lane (`live-gameline-zero-attribution`, session d26c7fa7) read my hand-off, ran the six sentinels against `bc8a8340` from a `git archive` snapshot, and sent the table back: MISSING / "many" -> unavailable, None / "" / [] -> nothing in play. Fixed in `9ab88382`: no `or 0`, an explicit `None`/blank-string branch, and 3 new test params that fail on `bc8a8340`. Recorded in this lane's block (`lanes.md`, "MY GUARD WAS ITSELF PERMISSIVE ONE LAYER DOWN") and the 2026-10-01 02:28Z `deploys.md` entry.
- TECHNICAL failure: `x or 0` cannot tell "no value" from "zero". In a reader that is the 2026-09-17 bug (`or 0` in Ask's formatter rendered a missing key as 0 minutes). In a GUARD it is worse, because the guard is the one line meant to catch it.
- EPISTEMIC failure, the one to fix: I claimed coverage from a test matrix I copied rather than derived. The parametrised cases (`None, {}, [], {"games_in_snapshot": "many"}`) came from the existing test's list, and three of the four vary the WHOLE `diag`, not the key. So the matrix exercised "diag is not a dict" and "key absent", and I read a green run as "absent or unparseable is covered". I also copied the `_count()` idiom three lines above (`int(diag.get(key) or 0)`) into the guard written to protect against `_count()`. The hand-off then turned an untested belief into a stated fact for another session.
- SECOND instance in the same lane: `tests/test_soccer_live_gates_wiring.py::test_gate3_soccer_off_vs_on` built "OFF" as NO artifact at all and asserted the reason "no soccer match in play". The permissive reading was ENSHRINED as the expected value, so fixing it read as a test regression. Rule: a test asserting "nothing in play" (or any "honest zero" reason) must construct a READABLE empty artifact; asserting it from a missing artifact encodes unknown-as-zero as correct.
- The rule going forward: in any branch that decides unknown vs zero, (1) do not coalesce before the check; (2) enumerate the sentinel matrix against the KEY, not the container: absent, `None`, `""`, `[]`, non-numeric, and a real `0`, which must still read as zero; (3) do not state coverage in a hand-off until that matrix has run.
- Would a rule have caught it? No. Two rules (09-17 and unknown-must-not-default-permissive) already said this in prose, and I wrote the bug while citing one of them in the comment above it. **Proposed CHECK, not built:** one shared parser, `parse_count(raw) -> int | None` (None for absent / None / blank / container / unparseable), used by every unknown-vs-zero guard (`_attribute_live_gameline_zero`, the coverage contract's readers), plus ONE parametrised test of the full sentinel matrix against the parser. A guard then cannot re-derive the coercion by hand. A cheaper partial check: an AST test that fails on `int(<anything> or 0)` inside any function whose body assigns a `"reason"` key.
- Cost: one wrong statement sent to another session and corrected by it; one extra commit (`9ab88382`); no production effect (soccer's own producer always sets an int, so the null family was unreachable for soccer, and reachable only for a future producer that leaves the key present and unset).
## 2026-10-01: "minutes 0" is not "did not play" in ESPN box scores, so read ESPN's `didNotPlay` flag
- Belief overturned: a box-score row with MIN 0 is a DNP. My first cut of `did_not_play()` (lane `basketball-recon-dnp-exclusion`) dropped every MIN-0 row from recon_props. ESPN reports WHOLE minutes, so a few seconds on the floor reads MIN 0: Rayah Marshall (WNBA 2026-09-24, MIN 0, plus-minus -2) and Jeremy Sochan (NBA 2026-06-13, MIN 0.0, +1) both played. My own Finals backfill had already dropped Sochan by that rule, and was corrected.
- Rule: use the source's explicit flag (`didNotPlay`, now saved as `DID_NOT_PLAY` by `_event_rows_from_summary`). Where it is absent, require MIN 0 AND plus-minus 0 AND every counting stat 0. Blank minutes are unknown, never DNP. Check a rule like this against real rows of the edge case before shipping it; the live producer (`build_wnba_recon`) already used the flag and was the reference I should have read first.
- Cost: one data file rewritten (20 -> 21 rows); caught before any NBA in-season run.
## 2026-10-01: a GRACEFUL gunicorn gthread exit still drops requests, so "graceful" is about the process, not the connections
- Belief overturned: `post_request` setting `worker.alive = False` (web's memory guard, and gunicorn's own `--max-requests`) recycles a worker without dropping requests, which `state_worker.md` recorded as "5 recycles, all graceful". gunicorn 21.2.0's `gthread.run()` leaves its loop and `poller.close()`s connections it accepted but has not read yet; process exit resets them. Measured: isolated repro 101-106 of 4,000 failed per round; live web 2 resets across 2 recycles; the audit sweep's `/wnba/market-board` ConnectionResetError at 0.0 s.
- Rule: when a component claims to exit gracefully, measure the CLIENT side across the exit (fresh connections, concurrent, spanning a forced recycle), not the server's log line. The fix (`DrainingThreadWorker`, `cd507a9b`) stops listening, drains accepted connections, then exits: 0 failures in the same tests, and `WEB_WORKER_DRAINED` is the proof line.
## 2026-10-01: repointing a script's base URL does not repoint its LOG reads, so a fleet run can stay blind to Render
- Belief overturned: after `scripts/_base_url.py` (`06f5fa7f`), my own checkpoint said "run check_deploy_safety.py to confirm it reaches the fleet" as if a reachable base URL meant a working script. It reached the fleet and authenticated, then reported `Board build state UNKNOWN (no BUILD_SPAN_ENTER in the lookback window)` on every run: the board-build check and the `--drain` TTL read Render's logs API (`api.render.com/v1/logs`, service id hard-coded), which sees nothing from the WSL fleet. The script could never return CLEAR there.
- Rule: when moving a tool to another host, list EVERY data source it reads (HTTP base, logs API, Render API, keyvalue store, files), not just the base URL, and run it once to see each verdict leave UNKNOWN. A guard whose source silently became empty reads UNKNOWN/None, which looks like caution, not breakage. Fixed for check_deploy_safety in `d5a235ee` + `38f1f620` (fleet log by line order -- it has no timestamps). Still Render-bound: `deploy_preflight.py` (deliberately) and anything else calling `api.render.com` logs.
## 2026-10-01: a drain that says CLEAR has not drained anything until the ACK is newer than the request
- Belief overturned: `check_deploy_safety.py --drain` CLEAR meant "the worker is drained and idle". Measured on the local fleet: CLEAR came 1 s after DRAIN_REQUESTED, from a worker heartbeat published 43 s BEFORE the request (`acked_drain_at=None`); the worker actually acked ~60 s later. And `in_flight` only ever carries `mlb_sim`, so "idle" was also true in the middle of a board build. Fixed in `c829b2df` (`_drain_clear`: ack >= requested_at AND idle AND board build idle).
- Rule: a state read used to confirm a REQUEST must carry proof it was written AFTER the request (an ack timestamp >= the request's), and "idle" only covers the work the publisher actually marks -- check which work that is before trusting it as a whole-worker idle.
- Process: a watcher that `rm -f`s its target file before tailing it races the writer and can unlink the live output (the fixed drain's own CLEAR line and rc were lost that way; ordering had to come from a separate observer). Never delete a file a background job may already be writing; tail with `tail -F` or use a fresh path per run.
## 2026-10-02: a process listing is not a list of work -- zombies, and names that contain other names
- Belief overturned: when I shipped the refresh-worker child scan (`995c177f`) I treated "every descendant in `ps`" as live work a restart would kill, and matched the worker by substring. Sampling live-odds-worker next (03:27-03:30Z) showed finished children lingering as `[python] <defunct>` in 3 of 8 samples (state `Z`: nothing left to kill, but they block a "no children" gate), and `run_live_odds_refresh_worker.py` CONTAINS `refresh_worker.py`, so a substring match could pick the wrong worker. Both fixed in `9fc24936` (drop `Z`, exact argv basename under the supervisor).
- Rule: before gating on a process scan, sample the real tree more than once and read the STATE column, not just the args; identify processes by exact basename plus parent, never by substring. A gate that counts zombies never clears and reads as caution, which is the same silence as a gate that never blocks.
## 2026-10-02: a red suite with a recorded baseline is not "known red" until each entry fails on the runner you trust for the same reason
- Belief overturned: `state_worker.md` [ci-suite-pytest-step] (2026-09-08) called the daily red "correct" and said not to regenerate the baseline. The local fleet's first full run (`869c4999`) failed 48; every one of the 36 recorded failures PASSED on Windows. They were Linux-only HOST LEAKS (`os.environ["TEMP"]`, the cgroup's `memory.stat`, real refresh-job processes, Windows `powershell`, 0600 dirs), stale fixtures (hard-coded "future" dates, EV from before a rule), and two real code defects -- one of which (`soccer_season_audit/outcomes.py` TEMP) silently dropped every soccer outcome on Linux. Fixed at cause; the suite is green on `d559535b` with an empty baseline.
- Rule: before accepting a failure into a baseline, run it on a second OS or host. A test that passes on one and fails on the other is reading the HOST, and a baseline built from it records the leak as a fact about the code. A test that reads a real resource (env var, cgroup, process table, clock, shell binary) must stub it -- or it measures whichever machine runs it.
- Process: the same run also proved a GREEN run is host-dependent: 13 refresh-worker tests passed in run 1 and failed in run 2 because the live fleet happened to be running jobs on the same host. One green run is a sample, not a verdict -- re-run before closing.
## 2026-10-02: a determinism test inside ONE process cannot see per-process randomness
- Belief overturned: `test_it_is_DETERMINISTIC_so_two_variants_compare_on_the_same_draws` passing meant the NFL live re-sim's rating perturbation was reproducible. It called the function twice in one interpreter; the seed was `random.Random(tuple.__hash__())`, and a tuple hashes its str member through the per-process PYTHONHASHSEED. Every new process drew different ratings (p 0.657..0.760 at rating_sd 0.75 over hash seeds 0..9), the daily ci-suite failed on it at random, and the rating_sd calibration numbers quoted in `live_resim.py` were drawn under random seeds. Fixed `92565cd5`.
- Rule: a reproducibility claim needs two FRESH interpreters with different `PYTHONHASHSEED`s, not two calls. Never seed an RNG from `hash()` of anything containing a str; `random.Random(<str>)` seeds from a SHA-512 and is stable.
- Also: a "held by OPEN lane X" pointer written in ANOTHER lane's block is a snapshot -- `nfl-live-resim-activation` had been CLOSED for three days. Check `lanes_closed.md` (or the census) before treating a cross-lane claim as live.
## 2026-10-02: a clean reproduction of PART of a caught scope exonerates nothing -- reproduce exactly what the `except` wraps
- Belief overturned: chasing WNBA odds run `20261002_135535`'s `IndexError`, I reproduced `sync_basketball_props_tracking_for_source_root` on a scratch copy, it ran clean (`ok: True`), and I read that as "the current inputs no longer trigger it". Wrong: the `except` that flattened the error to its message wrapped ALL of `sync_sport_post_refresh_tracking`, and the raise was in a LATER call (`refresh_impacted_recommendations_for_tracking` -> `build_recommendation_output` -> `[0]` on `[]`). Reproducing the full wrapped call on the same data raised at once.
- Rule: when an error survives only as a message, first find the `try` that caught it and reproduce exactly that scope; a sub-call that runs clean says nothing about the steps after it. Also: when a message-only error hides the line, a scratch copy of the real inputs plus the real call beats reading code for candidate indexing ops (the static scan found nothing; the error was one module away).
- Also corrected in the same session: I told the user both fixes "need a fleet restart". They did not -- the code runs in a per-run `refresh_odds_sources.py` subprocess that imports from disk. Check WHICH process imports a module before quoting a deploy cost.
## 2026-10-02: a restart count and a `code=` stamp cannot tell a deliberate deploy from an accident
- Belief overturned: reading the fleet at 15:40Z I told another lane's owner that refresh-worker had exited "on its own" (`exited code=0 after 1773s`, `restarts=1`), that web had NOT loaded its template (`code=927d1787`, `restarts=0`), and that a 15:10Z restart was unrecorded. All three wrong: the user had `kill -TERM`'d refresh-worker and HUP'd web in the same second to deploy `5c1b1bf2` (web workers started 15:40:24Z; the served page carried the new strings), and the 15:10Z restart was in deploys.md under a CT-only header my `HH:MMZ` grep could not match.
- Rule: before calling a role change spontaneous or a deploy partial, read the WORKER start times and the SERVED artifact (not `status`'s stamp, which a HUP never updates), and search deploys.md by commit and text, not by one timestamp format. A hand-off to another session that states facts is a claim it will act on -- check them as hard as a deploy verify.
## 2026-10-02: a test that passes against a swallowing parser can be vacuous -- prove the fixture reaches the code
- Belief overturned: my first `test_nba_event_served_on_the_wnba_url_is_dropped` PASSED ("the NBA event yields no WNBA game") while proving nothing: the fake response lacked `r.ok`, `fetch_bovada_odds_current` keeps a payload only `if r.ok`, the `AttributeError` was swallowed into `continue`, and the fetcher returned `[]` with or without my filter. The sibling test (real WNBA slate parses) failing was the only signal.
- Rule: for any "X is filtered out" test, assert the PRECONDITION in the same test -- the same input WITH the filter bypassed must produce X (here: MIA@TOR appears when `is_wnba_team` is patched to always-true). Code that catches `Exception` around I/O turns a broken mock into a green negative test.
## 2026-10-02 -- A log COUNT can match its own watcher; a status LABEL can lag the code
- Unanchored grep counted `EXECUTION=3` before any EXECUTION line existed: `ALL_PROCESS_MEMORY` lines embed every process's cmdline, including the watcher's own grep pattern. **Anchor log counts on `^<stamp>Z [tag] NAME`.**
- `local_production.py status` `code=` is `RENDER_GIT_COMMIT` from the env built at `up`. live-odds-worker read `927d1787` while running `c1067485` (its split line exists only there). **Judge a role's code by its `==== start` time against the checkout's ff.**
- A role-only SIGTERM "took 108 s" once and was believed to be the cost. The next took 895 s: it was the remainder of an uninterruptible `time.sleep`. A single timing was luck of phase, not a property; fixed in `5c205087`.
## 2026-10-02: a scan of what a nested record MENTIONS is not what it is ABOUT -- read its subject fields before acting on it
- Belief overturned twice in one task: 22 evaluation-ledger rows naming MIA@TOR were first called "WNBA predictions on the NBA game" (from a substring match), then "multi-sport records whose removal would hit every sport" (a scan for sport-ish keys found mlb..wnba in every row). Both were readings of what the row MENTIONED. Its subject fields (`record_type=recommendation`, `recommendation.game_id/event_id=MIA@TOR`, `recommendation.sport=WNBA`) said each row was ONE WNBA Moneyline pick on that game, with the other sports only in its board-state context.
- Rule: before deleting/quarantining rows of a nested record type, identify the record's own subject fields and select on those; a substring or key-name scan only bounds where to look. The count also moved (22 -> 24) between reading and acting -- re-count at the moment of the write.
## 2026-10-02 -- A role restart on the shared fleet is an event in someone else's data
- Three role-only restarts of live-odds-worker, each to load a new build for MY lane, read in another lane as unexplained clean exits mid-sleep. It spent a trace on them while the supervisor's backoff climbed to 80 s (about 6 min of odds capture per cycle). Nothing in the log named the sender (now fixed: STOP_SIGNAL, aee8827b).
- **Before a role restart, append a one-line deploys.md entry (time, role, reason) BEFORE sending the signal, not only in the after-the-fact write-up.** Prefer one restart that loads a finished build over one per iteration: here 3 dry-run reloads could have been 1 had the dry run's diagnostics (cost sample, repair-would-rewrite count) been in the first build.
## 2026-10-02: a per-sport failure inside a big odds run is NOT in the run file -- read the sport's own log
- Measured: the hourly all-sport odds runs store stdout/stderr cut to the first + last 32 KB (17 MB / 42 MB in the middle dropped), and the per-sport summary in the tail carries only `ok`, never the step error. NBA had failed in ~32 consecutive runs with no readable cause in any run artifact or in the keyvalue refresh manifest; the cause sat in `data/<sport>_source/logs/syndicate_refresh_oddsapi_props_<date>.log` (timestamped per run), plus `smart_sim_failures_<date>.csv`.
- Also: a watcher that reads a field the file does not have prints nothing, which reads exactly like "no runs yet" -- v1 of the WNBA watcher was silent for 3.5 h over 8 runs. Prove a watcher sees one known-past run before trusting its silence.
## 2026-10-02: a snapshot's row count is not its player-prop count, and a lane note naming a file IS a claim
- Measured: the NBA props runner gated edges on `snapshot_rows > 0`, but the OddsAPI snapshot carries game lines (h2h/spreads/totals, empty player_name) too. Preseason MIA@TOR had 28 rows and 0 player props, so "no edges" failed every hourly NBA run once SmartSim worked. Count the field the consumer needs (`player_name` set), and make only a KNOWN zero skip -- an unreadable snapshot must still fail.
- Measured: `check_lane_invariants.py` reported a contested file because a `Files:` note said "(ncaaf_historical_loader.py was BORROWED ... RETURNED)" -- a bare filename with an extension anywhere on a Files line parses as a claim. Describe returned/borrowed files in words, not by filename.
## 2026-10-02: a date read off `commence_time[:10]` is a UTC date -- an evening slate is "tomorrow" in it, and so was my diagnosis
- Measured (lane `layer2-freshness-1h`): I bucketed NHL board rows by `commence_time[:10]`, saw "10-03", concluded tomorrow's games were unprojected, and shipped a date-set fix (5c1b1bf2) that moved nothing. All 17 rows were TONIGHT: 7:10-9:10pm CT is 00:10-02:10Z the next day. The real defect was the same mistake in code -- `attach_nhl_game_projections` scoped rows by the UTC prefix and dropped every evening game (fixed 693de7a7, 17/17 projected). Bucket by `central_date_from_iso` before reasoning about slates, and check the weekday too: I also ran half a day calling Friday 2026-10-02 a Thursday, which inverted an NCAAF savings estimate.
- Related, same day: a sim input checklist (`scripts/nhl_sim_input_checklist.py`) audits the CHECKOUT's `data/` mirror unless pointed at production (`SYNDICATE_ARTIFACT_ROOT_<SPORT>` / `SYNDICATE_DATA_ROOT`). Its "21 unfed fields on the fleet" was a reading of the mirror; it prints the substrate path on one line -- read that line before quoting the result.
## 2026-10-02 OVERTURNED: "pull from production (/api/ops/artifacts/export)" as the route to MLB history -- since 2026-09-30 production is the local WSL fleet, and its pre-09-30 history IS the git mirror `[lane mlb-lines-props-backtest, session b98d59a1]`

- What we believed: the CLAUDE.md rule "Render is the source of truth; pull from `/api/ops/artifacts/export`" still names a reachable substrate richer than git.
- What was true: Render suspended all three services 2026-09-30 (`docs/ai_context/local_production_runbook.md`). Production is now `/home/amyn/syndicate-prod` in WSL (web on 127.0.0.1:10000). Its MLB data root was SEEDED from the git mirror at bootstrap, so every artifact dated before 09-30 there is byte-for-byte the checkout's: all 44 MLB sim dates (05-28..07-12) are git-tracked. MLB sims for 07-13..09-29 existed only on Render's disk and are unreachable until someone pays to unsuspend web.
- Rule: before scoping any backtest, locate production FIRST (`wsl -l -v`, `ps` for `local_production.py up`) and print per-family coverage from THAT data root; label any pre-09-30 artifact on the fleet as `checkout`-provenance, not `render`. A "full season" request is a billing decision when its middle months were Render-only.
## 2026-10-02 - RULE: a captured odds file with no capture timestamp is not a CLOSE; grade a model vs the book only on quotes that prove they were pregame `[lane nhl-lines-backtest, session 9ed26377]`

- Every NHL `data/odds/team/date=*/oddsapi.csv`, on the fleet and in the local mirror, carries an empty `book_last_update` (0 of 5,343 rows), and the files are rewritten through the game. The fleet's 2026-10-02 file held in-play totals (VAN-EDM: 15 points, 6.0..16.5). Treated as a "close", an in-play price knows the score, so the book would look better than it was and the model worse.
- **How to apply:** for any vs-book grade, take the close from `<sport>_source/tracking/book_quotes` (every row has `captured_at`). Use the last quote per (book, market, selection, line) with `captured_at` <= commence, or an OddsAPI historical snapshot taken before the start. Count and report the rows dropped as post-start.
- The same median-of-everything shape is a live production defect: `market_lines.load_market_lines` sets the NHL totals line to the median of every captured point, so hockeysim prices lines no book quotes.
- *(evidence: `.syndicate/findings_nhl_game_lines_backtest.md`; `scripts/backtest_nhl_game_lines.py::quote_log_close`)*
## 2026-10-02: a cadence setting is only as fine as the loop that CHECKS it -- and a "10-minute run" can be a run that failed
- Measured (lane `layer2-freshness-1h`, local fleet): I moved NFL/NCAAF from 1800s to 1500s and predicted ~45-min peaks. Nothing changed (58-59 min) because the idle loop slept 900s between checks, so every interval in 16-32 min fired at ~32 -- it launched 38 min apart at 1500s. Read the loop's tick spacing (`PREGAME_CADENCE_DETAIL` timestamps) before tuning any interval it gates; fixed in 963c2374.
- Same night: I sized soccer's 45-min cadence on "runs take ~10 min". Those were FAILED runs (rc 1 at a schedule step until 5566d4ba); the real run is 24 min, 94% full-season schedule rebuilds. Check a run's `ok`/returnCode before using its duration as a baseline.
- Same night, ops: env in `local_production.env` is read at SUPERVISOR start only (a child TERM re-uses the old env), and `down` immediately followed by `Start-ScheduledTask` can race -- the new supervisor sees the old one and exits 0, leaving production down (23:01-23:08Z). Confirm the old supervisor is gone (`pgrep -f "local_production.py.*up"`) before starting, and confirm a new one after.
## 2026-10-02 -- Belief overturned: IDLE priority is the safe way to run a backtest beside the local fleet `[lane ncaaf-lines-props-backtest, session 7e94d2ff]`
- Measured: 7 MC workers at IDLE_PRIORITY_CLASS got ~9 s CPU each in 25 min while the host was only 34% busy -- Windows 11 runs Idle-class processes in efficiency mode, so they starve even beside free cores. BELOW_NORMAL ran (10 games / 184 s) and still yields to the fleet's Normal-priority vmmemWSL.
- The second limit was MEMORY, not CPU: with two peer backtests the host hit 96% RAM and the workers' working sets were trimmed to ~35 MB; they then thrashed (0.2 s CPU per 20 s) with 4.5 cores idle. A CPU-priority knob cannot protect the fleet from that -- check `psutil.virtual_memory().percent` before launching a pool, and pause (per-unit caches make it resumable) rather than add pressure to production.
## 2026-10-02 -- Belief overturned: a benchmark is what its COLUMN says, and a registry verdict is a reading with a window `[lane soccer-lines-props-backtest, session 43e4d5fe]`
- Measured: the 2025-26 soccer 1X2 result "loses to the de-vigged CLOSE" (08-15, n 1,112) was graded against football-data `Avg*` -- the market average at collection, i.e. PRE-close (`match_history.py:109-113`); the closing columns are `AvgC*`. Name a benchmark from the source column you joined, not from the docstring that describes it.
- Same lane: `measured_market_skill.py` registers soccer pregame totals as PARITY (n 194, 08-31..09-13, CI [-0.004, +0.024]) and Layer 2 still ranks those edges at x1.0; on n 492 (to 09-20) the same market LOSES +0.0095 [+0.0032, +0.0157]. A verdict_class is a frozen reading: carry its window next to it and re-grade before a consumer relies on "parity".
## 2026-10-02 FORBIDDEN: proposing a MARKET-WIDE withhold of a model's probability as the answer to "the model loses to the book" `[lanes mlb-lines-props-backtest / mlb-board-mean-only, session b98d59a1]`

- What I did: copied the NHL template's gate (empty `MEASURED_MARKETS`), recommended "MLB mean-only on the board", and built it on the user's "make it" -- while a standing rule already said otherwise (user: "every line is its own decision"; no market-wide pauses/exclusions).
- What was true: the user's directive is "MLB should still show everything - the prime directive of the app is that every line is its own decision. we should have a model that is accurate that then helps inform each decision". A backtest that the model loses to the book is a MODEL-ACCURACY finding, not a publication switch. The reversal came before shipping. The cost was a lane, two loans on main, and a cross-session interrupt.
- Rule: a backtest verdict feeds (a) WHY -- decompose reliability vs resolution, bias, dispersion -- and (b) a ranked fix plan. Never a sport- or market-wide withhold. Before recommending ANY change to what the board shows, grep the standing rules for the board's directive and quote it in the recommendation. A template from another sport's lane carries that lane's decision, not this one's.
## 2026-10-02 -- A task prompt's rule can contradict a standing user decision; check before building to it `[lane ncaaf-lines-props-backtest, session 7e94d2ff]`
- The prompt said "a market earns a probability/edge only if it beats the baseline AND the book" and I delivered a gate list recommending withheld probabilities. The standing decision (memory `feedback_every_line_its_own_decision`; reaffirmed 2026-10-02 ~7:05 PM CT; `1ece602a`) forbids market-wide exclusions. A peer session caught it.
- How to apply: before turning a prompt's decision RULE into a deliverable, grep memory/state/learnings for a decision on the same subject; when they conflict, say so up front and build the diagnosis (why it loses, what fixes it) rather than the exclusion.
## 2026-10-03 — FORBIDDEN: reading a production-EQUIVALENCE check as proof the harness ran production's ENVIRONMENT. Both sides can share the same wrong input and agree perfectly `[lane nfl-lines-props-backtest, session 05b01a84]`

- **What we believed:** the props harness was production. Its selfcheck fed one week's quotes through
  `nfl_props_rows_for_week(use_artifact=False)` and matched every probability: **0 mismatches over
  8,976 rows.**
- **What was actually true:** the game-context multiplier was **exactly 1.0 on 100% of rows**, in both
  the harness and the "production" call. The scratch data root had no `upcoming_recs_*.csv`, so
  `default_nfl_source_root()` (the `#441` probe for an unrelated file) fell through to a non-existent
  `source_artifacts/`, and `game_context()` read no schedule. On the fleet the multiplier is live
  (non-1.0 on ~87% of rows). **An equivalence check proves the CODE matches; it is silent about any
  input both sides read from the same place.**
- **How we found out:** the report printed `ctx mean / share!=1` per market and every cell read
  `1.0 / 0.0`, against non-zero coefficients in `_NFL_GAME_CONTEXT_PARAMS`. The summary column caught
  it, not the check.
- **The rule going forward:** next to any equivalence check, assert that every FED input is non-neutral
  on the population (here: `game_context(season)` non-empty for each scored season; the harness now
  refuses otherwise). A neutral default that both sides share cannot be found by comparing the sides.
  Same family as `model_engine_standard.md` §4.2 (a neutral default makes an unfed field invisible).
- **Cost:** one full props run discarded (~15 min).
## 2026-10-03 — RULE: after `land`, read your lane's block for DETACHED lines, not only for duplicates. A rebase merge can re-home your additions under ANOTHER lane's header, and no header-level check sees it `[lane nfl-lines-props-backtest, session 05b01a84]`

- **What happened:** I appended reading lines to my OPEN block across three lands. Meanwhile 5+ other
  lanes were inserted at the end of `## OPEN`. After the merges, my header + Goal..Verification stayed
  at line 1146, and my 19 reading lines (plus my `Blocked by`) sat at line 1217, under the CLOSED
  `mlb-board-mean-only` block. My readings read as another lane's, and my block had no `Blocked by`.
- **Why the existing checks missed it:** `check_lane_invariants` and `lane_identity_check` (the
  2026-09-02 rule) count HEADERS. No header moved or duplicated; only body lines did.
- **How to apply:** after every `land`, `grep -n` a distinctive string from your newest lane line and
  confirm its nearest preceding `### ` header is YOURS. Keep lane-block additions few and short (the
  narrative belongs in `log/<date>.md`), which also keeps the blast radius small.
- **Cost:** fixed at checkpoint; no claim was mis-enforced (the lines carried no `Files:`).
## 2026-10-03 OVERTURNED: "the WNBA moneyline sim is the best pregame asset (AUC 0.7631, Brier skill +16.5%)" -- the comparator was climatology; against the BOOK on the same rows the discrimination was the market's `[lane wnba-lines-props-backtest, session 39b666bb]`

- **What we believed:** 08-31 graded the sim ML against climatology and called it the platform's best asset; the board was faulted for not betting it.
- **What was true:** on the same games the de-vigged book's own AUC was higher (0.825 vs 0.790, n=119); today's code ties the book only because it anchors 95% to the spread; the raw model alone is worse than the book (dBrier +0.029, CI excludes 0).
- **How found:** an OddsAPI historical backfill (tip-60min) gave a book probability for every game, so every model probability could be scored against the market on identical rows.
- **Rule:** an accuracy number is evidence of an edge only against the price it would trade into. Report the BOOK's AUC/Brier on the same rows beside the model's, every time; a skill score against climatology or a constant answers a different question. Also: a pre-sim market anchor makes "model ~= market" true by construction -- score the raw pre-anchor output separately before calling the model accurate.
## 2026-10-03 — "League X has had no recommendations since the cutover" is a claim about the PRODUCER only if League X had a fixture inside the sim horizon. Read the fixture calendar from two independent sources before calling it a gap `[lane soccer-projections-gap, session 6214bc11]`

- **Overturned:** the brief and lead `fleet-soccer-recs-gap` read "EPL newest 08-21, Serie A 08-28, none since cutover" as a producer failure. Two independent sources say otherwise. The ESPN schedule and OddsAPI `game_odds_current.csv` both list **no EPL/Serie A fixture from 09-21 until 10-10** (international window). With `SYNDICATE_SOCCER_SIM_HORIZON_DAYS=7`, zero units is the correct output. The fleet disk holds no 09-xx files because Render's disk was lost, not because a producer stopped.
- **The real zero was one league over:** MLS recommendation files EXISTED and held 0 matches. Units were keyed on the UTC `date[:10]`, while ESPN buckets by local day (`e26ba342`; same mistake as NHL `693de7a7` and learnings line "Bucket by `central_date_from_iso`"). "No recommendations for this date" means `index.matches == 0`. It does NOT mean "no file": open the file and count.
- **How to apply:** per league, print schedule fixtures by CENTRAL date beside odds events and recs-file match counts before naming a stage as the first zero. A file count is not a match count.
- **Instrument:** `deploy_preflight.py` reads the suspended Render services and returns UNKNOWN on the local fleet. It is not a fleet gate. The fleet gate is `deploy_claim` + `check_deploy_safety --base-url http://127.0.0.1:10000`.
## 2026-10-03: a process that writes PRODUCTION by default must not run under the test runner -- my quota forwarder wrote 556 fake observations into the fleet
- Measured (lane `layer2-freshness-1h`): the off-fleet quota forwarder enables itself whenever the state backend is not keyvalue -- which is TRUE of a pytest run on a dev machine, whose headers are fake. Running the quota suite once forwarded 556 fake observations into the live fleet document (fake buckets, inflated hour/family counters, and a used=0 observation that reset the burn baseline). Repaired by exact subtraction from a replay against a throwaway Redis; the old baseline was unrecoverable. Any default-on path to a production store needs a test-runner exclusion in the CODE (not only a conftest), and its first test run should point at a throwaway target -- check the production key after the first run, not after the commit.
- Same day: a script that "already records" can still record nowhere -- `record_oddsapi_quota` off the fleet wrote to the dev machine's filesystem backend. Confirm WHERE an instrument writes from the process that calls it.
## 2026-10-03 — OVERTURNED (mine): "the NFL prop loss is RELIABILITY, not resolution, so widening the spread fixes it". At a MAIN LINE a Murphy split compares two near-zero resolutions; the calibration SLOPE is the instrument that discriminates `[lanes nfl-lines-props-backtest -> nfl-prop-predictive-spread, session 05b01a84]`

- **What I believed:**
  - Murphy reliability was 10-300x the book's, and the model's resolution was "at or above" the book's.
  - So I concluded the loss was calibration and fixable by reshaping (the 2026-09-08 rule: decompose
    before prescribing).
  - A widened spread then closed 56-74% of the Brier gap out of sample, and I ranked it fix #1.
- **What was actually true:** the PRODUCTION model's calibration slope, logistic(y ~ a + b·logit(p)) at
  the line, is ≈ 0 in all six continuous markets on 2025 (receptions 0.11, receiving yards −0.07,
  rushing yards −0.01, passing yards −0.06). The book's slope is ≈ 1 (0.78-1.56), with its sd of
  logit 10x smaller.
  - **The model's probability at the line is noise.**
  - The book's resolution is near zero BY CONSTRUCTION at a main line, which is priced near 50%. So
    "model resolution ≥ book's" compared two near-zero numbers and discriminated nothing.
  - Widening "worked" by flattening the noise toward 50%. The fitted parameters ran to the flattening
    edge (shrinkage off, c = 3.0, log-normal weight 0).
- **How it was caught:** I had PRE-REGISTERED a slope bar in the lane ("< 0.6 = shrinking toward the base
  rate, NOT a repair"), on a peer's MLB caution. The Brier bar alone reported MET. The pre-registration
  is the only reason "MET" was not shipped as a repair.
- **The rule going forward:**
  - Before calling a forecast's loss "reliability" (fixable by a transform), report the calibration
    slope of the model AND of the comparator, plus each one's spread (sd of logit p).
  - A slope near 0 with a large spread is noise, whatever the Murphy terms say. The fix then is
    information, not shape.
  - A Murphy split against a comparator that sits at 50% by construction (a main line) is not evidence
    about resolution.
  - Corollary of 2026-09-21 ("a filter on a model metric grades the model"): a Brier gain from
    flattening grades the noise, not the mechanism.
- **Cost:** one recommendation (#1 of `findings_2026-10-02_nfl_lines_props_backtest.md` §7) withdrawn, and one
  lane's premise falsified; nothing deployed.
## 2026-10-03 — A log watcher on the fleet can be triggered by ITS OWN grep: `ALL_PROCESS_MEMORY` lines print every process's command line, including the watcher's regex `[lane soccer-recs-empty-overwrite, session 6214bc11]`

- **What happened:** my post-ff watcher grepped `refresh-worker.log`/`live-odds-worker.log` for soccer build lines, and its "refusals" grep searched for `SOCCER_RECS_EMPTY_OVERWRITE_REFUSED`. Both outputs came back full of `ALL_PROCESS_MEMORY` lines. Those lines list the command line of every live process, my own `grep` included, so the token appeared in the log because I was searching for it. I nearly read "watcher fired + census unchanged" as verification. A clean re-read showed no soccer build had run at all.
- **How to apply:** anchor a fleet log match to the EMITTER, `^<ts>Z \[<role>\] TOKEN`, and exclude `ALL_PROCESS_MEMORY`. Before trusting a watcher's trigger, confirm the artifact changed (`find -newermt <deploy time>`). Same family as "Log watchers: match timestamped lines" and "Gate verify on artifact mtime".
## 2026-10-03 -- Belief overturned: "the L25 workers thrashed on memory" -- they were FROZEN for outliving their tool call `[lane ncaaf-lines-props-backtest, session 7e94d2ff]`
- Measured: a sim process got 0.0 CPU-s per 10 s at BELOW_NORMAL and then at NORMAL priority, with idle cores, light paging (190 pages/s, disk 2%) and a 73 MB working set; the identical game took 36 s in the foreground of a blocking tool call. Workers whose call passed its timeout and was moved to the background dropped to ~0.1 CPU-s per 10 s at once.
- How to apply: run long local compute in the FOREGROUND of a blocking call sized under its timeout (batch the work), and prove progress by CPU-seconds per interval, not by a "running" status. Before calling a stall memory thrash, read the page-fault rate and disk time -- a frozen process and a paging one look the same in a game counter. My 10-02 entry's memory explanation is withdrawn as the primary cause.
## 2026-10-03 — "Already up to date" answers a question about the FF, not about what HEAD is. Pin the deploy to the HEAD you enumerated, or a concurrent ff becomes your ride-along `[lane refresh-worker-soccer-loop-silent, session 6214bc11]`

- **What happened:** I enumerated ride-alongs against fleet HEAD `eedfde5e` at ~19:19Z. Another session ff'd the checkout to `ca3c85cd` at 19:20:11Z. My gated script waited for CLEAR, ran `git merge --ff-only <my target>` (satisfied, "Already up to date") and restarted at 19:27. The restart loaded three other lanes' changes, one of them a peer's registry fix that peer meant to deploy and measure itself.
- **How to apply:** a gated deploy script records the HEAD its ride-along read was taken against, and ABORTS if HEAD differs at fire time (`[ "$(git rev-parse HEAD)" = "$EXPECTED" ] || exit`). Re-enumerate, then re-arm. Afterwards derive loaded code from the role's start epoch against the reflog, never the env stamp (the supervisor reuses `item.env` on a respawn).
- **Related, same session:** on the one-host fleet, any process scan over `/proc` sees ALL roles (`5602290f`). A guard that counted "its" jobs host-wide starved refresh-worker for hours. Scope by the job's inherited `RENDER_SERVICE_NAME`.
## 2026-10-03 — RECURRENCE (mine, same day as the rule): an UNANCHORED one-shot replace in `lanes.md` edited ANOTHER lane, and my block's body lines were merged under a third lane's header `[lane nfl-prop-mean-inputs, session 05b01a84]`

- **Two existing rules, both broken in one commit (`76cb25f7`):**
  - 2026-09-25 FORBIDDEN, "a one-shot `replace(old, new, 1)` on a line that is not UNIQUE": I replaced
    `- Blocked by: none` with `str.replace(..., 1)`. The first match in the FILE was lane
    `accuracy-ledger-budget-raise`'s, not mine.
  - This morning's RULE, "after `land`, read your block for DETACHED lines": my FIT RESULT / Blocked-by /
    PREDICTION lines sat under `nhl-live-sweep-fast`.
- **The mechanism of the detachment, now known.** Another session's `lane_open.py` and my edit both
  INSERTED at the same anchor: the line after my block's last line, which was the end of `## OPEN`.
  Git's rebase merged the two insertions in sequence with no conflict, the new lane's header first.
  Everything I appended after that point now belongs, structurally, to the newer lane. No header-level
  invariant check can see it.
- **How to apply:**
  - Every `lanes.md` edit is RANGE-ANCHORED: find my header, find the next `### `, and edit only inside
    `[h, nxt)`, asserting exactly one match there.
  - After every `land`, `git show origin/main:.syndicate/lanes.md` and check that the nearest `### `
    above each line I added is mine.
  - Prefer EDITING an existing line of my block over APPENDING after its last line. The last line is
    exactly where `lane_open.py` inserts.
- **Cost:** two repairs (`ac1717ee`), one other lane's line mis-edited for ~1 h; no claim was
  mis-enforced.
## 2026-10-03 - RULE: landing a behaviour change on main DEPLOYS it the moment any session fast-forwards the fleet. Baseline BEFORE you land, and land only when ready to measure `[lane nhl-game-lines-model, session 9ed26377]`

- I landed the NHL game-market sim fixes (7865b26e) ~20:05Z and was holding a 10-minute coordination window before my own ff. Another session fast-forwarded the fleet to github/main at 20:11:45Z (ad85d3e2) and again at 20:18:14Z (f351eac5). Both carried 7865b26e live while I held no claim. My `merge-base --is-ancestor HEAD <target>` guard caught it, so no redundant ff fired.
- It worked out only because the baseline had been taken at 20:10:30Z, 75 s before go-live, and the change had a crisp artifact signature (legacy model_total == sum of periods; calibrated = +0.25..0.30).
- **How to apply:**
  - Take the baseline before landing.
  - Read the go-live time from the fleet reflog (`git reflog --date=iso`), not from your own ff.
  - Hold a change that must not ship unmeasured off main; moving the files aside and landing only the ledger works.
  - When a ride-along owner needs notice, the notice must say "live as of <reflog time>", not "I will ff at X".
- *(evidence: `.syndicate/deploys.md` 2026-10-03 20:11:45Z and 20:54:04Z entries)*
## 2026-10-03 -- Belief overturned: files written into a sparse worktree's excluded `data/` survive git operations `[session 43e4d5fe, lane soccer-1x2-ratings-xg-source]`
- Measured twice: `data/soccer_source/*/history/*.csv` materialised byte-exact into a `session_worktree.py` worktree (data/ excluded by sparse checkout) were DELETED by a later `git rebase origin/main` -- and a backtest reading them per league died with "no committed history" for every league after the first. Two runs (the 2025-26 totals run and the H37 arm A) were lost before the cause was seen.
- How to apply: never run a long job off files you placed in a sparse worktree; run it from a static snapshot outside git (`git archive HEAD syndicate scripts` + the data files written byte-exact) so no checkout, rebase or land can touch its inputs. And a long job's output must be written incrementally (`--append-dump`), or a guard stop discards hours.
## 2026-10-03 — Clean up ONLY your own worktree. `git worktree prune` is repo-global and reaches other sessions' worktree records `[session 6214bc11, closing soccer-projections-gap]`

- **What happened:** after a half-closed `session_worktree.py close` (dir empty, unregistered), I ran `git worktree prune` to tidy up. It tried to delete `.git/worktrees/lrl_ab`, which belongs to ANOTHER session, and failed only because Windows refused it (Permission denied). On a different permission state it would have removed a live peer's worktree record.
- **How to apply:** finish a half-close by hand, scoped to your own path: `rmdir <your empty dir>`, `git branch -d session/<your slug>` (after confirming 0 unique commits). Never run `git worktree prune` / `git worktree remove` on paths you didn't create. Same family as "Never git stash in a worktree" (repo-global state reached from a local-looking command).
## 2026-10-03 -- Belief overturned: "my new regression test catches the bug" -- it passed on the OLD code `[session 8de04a09, lane consensus-movement-implied-guard]`

- **What I believed:** a test feeding a book that quotes 0 into `consensus_movement_by_sport.observations` and asserting the consensus is unchanged would fail on the old converter (which priced 0 as 0.0).
- **What was actually true:** with three identical clean books the per-capture median of `[x, x, x, 1.0]` is still `x` -- the median absorbed the outlier, so the test passed on the buggy code. Found only by patching the old converter back in and re-running. Fixed by using ONE clean book (median of two = mean, which the bad pair moves).
- **How to apply:** before landing a regression test, run it against the code it guards (patch the old function back in, or import the `origin/main` module from a temp copy) and see it FAIL. A robust statistic (median, trimmed mean, clip) in the path under test is the usual way a test goes inert.
## 2026-10-03 — FORBIDDEN: `git checkout origin/main -- .syndicate/lanes.md` to "sync" the ledger while your own lane block is UNCOMMITTED. It erases the block silently `[lane nfl-kalshi-forward-clv, session 05b01a84]`

- **What happened:** I opened `nfl-kalshi-forward-clv` with `lane_open.py`. That writes the block into the
  worktree's `lanes.md` and does not commit it. I then built and dry-ran the script, and later ran the
  sync recipe I had been using all day before each commit, `git checkout origin/main -- lanes.md
  deploys.md`. The block was gone. Nothing reported it.
- **How it was caught:** the next anchored edit asserted exactly one `### nfl-kalshi-forward-clv` header
  and found none. The anchored-edit discipline from earlier the same day was what made the loss loud.
- **The rule:**
  - Land a `lane_open.py` block in the SAME step that writes it, before any other work.
  - Sync ONLY `deploys.md` from upstream (the file the commit guard compares). Never `lanes.md` while it
    holds anything of yours that is not on main.
  - If a sync of lanes.md is needed, rebase the committed branch instead.
- **Cost:** none in the end. The block was re-created verbatim (its prediction was still pre-data) and
  landed in `f11e7b7e`. It would have silently dropped the lane's pre-registration if the assertion had
  not existed.
## 2026-10-04 — RULE: a callee's DEFAULT is dead code if every caller passes the argument; read the COMMAND LINE the producer actually ran, not the callee's default `[lane nba-layer2-projections, session ed75e56a]`

- Belief: `fetch_basketball_oddsapi_props_local.py`'s `DEFAULT_MARKETS` lists the player props, so NBA props were "requested and simply not offered".
- What was true: the orchestrator ALWAYS passed `--markets` for NBA (`_effective_markets` -> game + half lines). The default never applied, and no NBA prop was requested at all. The producer log's own `$ ... --markets h2h,spreads,...` line said so on every hourly run. Its "no player-prop lines offered" message read as a statement about the BOOKS when it was a statement about our REQUEST.
- How to apply: when a producer reports "none offered", grep its logged command for the argument before believing it. Since the fix (06:02:17Z), the same message really is about the books (0 NBA preseason props), and only the logged `--markets` tells the two states apart.


### 2026-10-04 — An automated restart is not done until the NEW process answers; on a failed start, retry and keep the lock -- never log and exit
**FORBIDDEN:** an unattended script that stops production (`local_production.py down`, or any role kill) and then releases its claims / exits without a CONFIRMED healthy restart. Evidence: deploys.md 2026-10-04 08:39:03Z entry; `C:\tmp\soccer-lpb\flip_overnight.log`; `~/syndicate-prod/logs/supervisor.log`.
- What we believed: that "confirm the old supervisor is gone, then `Start-ScheduledTask`" (the mitigation in this file's 2026-10-02 entry, "down immediately followed by Start-ScheduledTask can race") made the overnight restart safe, and that my script's comment "starting the task anyway so production is not left down" meant production could not be left down.
- What was actually true: at 08:39:03Z the supervisor was confirmed GONE; `Start-ScheduledTask SyndicateLocalProduction` at 08:39:04Z returned, the task recorded LastTaskResult 0, and `up` NEVER RAN -- supervisor.log has no line between `stopped.` and the 13:53Z restore. Exit 0 meant the Task Scheduler's "restart every minute on failure" never fired. My script read `healthz after restart: False`, then RELEASED all three claims and exited. Production stayed down 5 h 14 min (08:39:03Z-13:53:23Z) until a human-driven check found it; one plain `Start-ScheduledTask` at 13:53:13Z brought it up in 10 s. Root cause of the silent start: UNPROVEN (leading suspect: the WSL service, which had returned WSAETIMEDOUT twice the previous afternoon).
- How we found out: the next morning's routine "check on the H37 run" read the flip log; `/healthz` refused connections; task state Ready.
- The rule going forward: a restart is (a) start, (b) poll `/healthz` for minutes, (c) on failure RETRY the start (fresh `wsl` invocation) N times with backoff, (d) if still down, keep the claims, raise the loudest alert available, and exit NON-ZERO so whatever scheduled it can see a failure. The postcondition (new process healthy) is the deliverable; the precondition (old process gone) is not. My design handled "the stop step failed" and never considered "the start step failed".
- Also EPISTEMIC: the restart path was never exercised before running unattended on production at night -- only the read-only verify script was dry-run. A path you cannot test should not be the one running alone at 3 AM.
- Cost: 5 h 14 min with no board builds, odds sweeps, live tracking or scheduled jobs on the fleet (paper money only); a ci-suite run killed mid-flight at `down`.
- **EXONERATED (with evidence): the change being shipped.** The 13:53Z start carried the SAME commit (`6d2e46c3`) and the SAME env (`SYNDICATE_SOCCER_PROP_OWN_RATE_BLEND=1`) and was healthy in 10 s, so neither the flag nor the fast-forwarded code caused the outage. The safety gate also worked as designed (19 NOT CLEAR aborts 08:00-08:36Z, claims released each time, then one clear window).
## 2026-10-04 — RULE: fixing a BIAS is not fixing the PROJECTION; gate an estimator change on paired per-player Brier, never on the totals it was fit to `[lane nhl-player-props-projection]`

- Belief overturned (twice in one lane): "the refit matches the real total, so the prop gets better." NHL blocks: a shared scale took team bias -0.738 -> -0.001, then a positional term took D/F bias to +0.005/+0.002 -- and paired player blocks MAE got WORSE both times (+0.0083, +0.0069). Assists: real assist rates, a primary/secondary split and two line-quality mechanisms each moved the target aggregate and none improved ASSISTS@0.5 Brier.
- Why: an unbiased mean spread over the wrong individuals adds variance; the error lived in WHO gets the event, which a level/position fit cannot touch. MAE also rises when a skewed count's mean is lifted toward truth.
- How to apply: before shipping any calibration/attribution change, run the paired per-player comparison at the betting lines (Brier) against the current production engine on the same player-games; a matched total is a precondition, not evidence.
## 2026-10-03 — RECURRENCE (mine): I reported a production flag as "default OFF" from the CODE default, without reading the env `[lane nfl-off-market-edge, session 05b01a84]`

- The "absent != off" rule (CLAUDE.md, 2026-09-09 FORBIDDEN on reporting a stage OFF from an absent flag) cuts BOTH ways.
  - I wrote "`SYNDICATE_SCORE_FEE_NET` default OFF" into a findings gap table from `opportunity_signals.py:1067`.
  - The fleet refresh-worker had it `=1`, and the served board applied it on 212/212 venue rows.
  - The user then asked me to "turn it on".
- **How to apply:** a code default is a statement about the CODE. Before a findings line says a feature is on or off in production, read the running process env (only that key), and if possible the served payload's own evidence that the branch ran.

## 2026-10-04 — RULE: an evaluation that calls the same helper as the engine cannot see that helper's defect; when an estimator writes integer ladders, test a SUB-HALF-UNIT change end to end `[lanes wnba-sim-rate-shrink / wnba-minutes-redistribution, session 39b666bb]`

- The WNBA rate shrink shifted integer prop ladders by v' = round_half_up(v + delta). That is a NO-OP for |delta| < 0.5 -- most threes and assists deltas -- so the means moved and the board's probabilities did not.
- Its fit script scored Brier with the SAME rounding, so the measured gains already contained the loss, and the engine-equivalence check compared MEANS (316/316 equal), which the defect never touches. Every check passed.
- Caught only when a second module used the convention and a dry run printed a Brier delta of exactly [0.0, 0.0] for threes. Fixed with a mean-preserving shift (bfa92d5f); held out, assists Brier -0.0041 and threes -0.0014 on the same rows.
- Same session, recurrence of the 2026-10-04 "fixing a BIAS is not fixing the PROJECTION" rule: a minutes re-share took the top-five minutes bias from -1.61 to -0.21 and made PRA Brier WORSE (+0.0073 / +0.0088). Removed minutes are low-usage minutes; holding the per-minute rate overstates the loss.
- **How to apply:** an exactly-zero delta on any market is a finding, not a null. Before trusting an estimator that edits discrete distributions, feed it a change smaller than one unit and assert the published probability moves; and never let the fit's scorer reuse the engine helper under test without a test of that helper of its own.

## 2026-10-05 — RULE: "the module applied" is not "production serves it"; read the artifact the CONSUMER reads, at the field it reads `[lane nba-prop-calibration, session e0a3e383]`

- I enabled the NBA prop calibration and recorded reading 1 MET: the module, applied to an in-memory copy of a sim,
  moved Embiid's mean 21.1 -> 25.0. Production served none of it, twice over:
  - (1) The smart-sim run REUSES any existing sim, so the props file rebuilt 3 minutes after the enable carried the
    raw values (21.08 / 6.91) until a stale-sim rule existed (468b8620).
  - (2) Layer 2's NBA prop join reads the sim LADDER, not `<stat>_mean` / `<stat>_sd`. The calibration's integer
    ladder shift is a no-op below half a unit, so the ladder lags the calibrated mean on 125/169 threes rows and
    122/169 tov rows.
- The out-of-sample evidence scored Normal(mean, sd). That is a different quantity from what Layer 2 serves, so
  "beats the served sim" was measured on a path the board does not read.
- **How to apply:** before calling an estimator live, find the CONSUMER (grep the field it reads, not the field you
  wrote) and read THAT field from a production artifact written AFTER the change. An enable on a producer that
  reuses artifacts needs a stale/version rule or a rebuild. Evaluate the served transform, ladder and all, not a
  convenient proxy. Recurrence of the 2026-10-04 integer-ladder rule (WNBA bfa92d5f) and of the engine standard's
  "publishing is not sufficient -- a new input requires a REBUILD".

## 2026-10-04 — FORBIDDEN: a fleet restart gate whose DOWN and UP halves live in different processes. When the session ended, the half that runs `down` survived and the half that starts the fleet did not `[lane nba-day-of-sweep-ownership, session ed75e56a]`

- What happened: a CLEAR-gated restart ran as a PowerShell wrapper (start task + verify) around a WSL bash loop (wait CLEAR, then `local_production.py down`). The Claude session ended mid-wait. The wrapper died; the WSL loop (pid 1090598) kept polling. Had it read CLEAR, it would have stopped all three roles with nothing left to start them. Found by `pgrep` on the next turn and killed before it acted.
- Rule: before resuming after any session break, `pgrep -fa` for your own gate/watch scripts on the fleet and kill orphans first. Better, put both halves in ONE process, or make the WSL side refuse `down` unless a live parent is present.
- Related, same session: `tail -f` in WSL on a `/mnt/c` file never saw appends written from Windows (a 30-min monitor delivered 0 events while the file grew). Poll by line count instead.

## 2026-10-05 — RULE: before fixing a measured bias, check whether it is COMPENSATING another; measure both terms of the product first `[lane nhl-ev-rotation]`

- Belief overturned: "the NHL SOG edges come from wrong line order, so fix the line order / ice time." Measured: line order was mostly right, and the engine's excess top-line ice time (+2.2 min) was offsetting a too-flat per-minute shot rate (0.110 vs 0.133). Correcting the ice time alone made SOG@1.5 and POINTS@0.5 Brier WORSE.
- How to apply: when a projection is a product (minutes x rate, opportunities x conversion), decompose sim vs actual for EACH factor on the same population before changing one; a fix to one factor needs the other in the same backtest arm.
## 2026-10-05 — RULE: a verification is only as good as the population it ran on; if no member of the reading carries the failing trait, MET is untested `[lane basketball-injury-exclusion-reinclusion, session 39b666bb]`

- 2026-10-04 reading 2 for the injury-exclusion fix: "0 of 44 OUT-listed players in the pools" -- MET, recorded, and true.
- None of that day's OUT players had an apostrophe or period in her name. Every such excluded player had ALWAYS been simulated: the exclusion keys keep punctuation (`_norm_name_key`), while the vendored pool filter compares `_norm_player_key`, which strips it.
- Found the next day, only because a NEW exclusion source (availability) put two apostrophe names (Ny'Ceara Pryor, 22.9 min) into the set. Fixed 1111942f.
- Also caught: my first watcher matched names without teams and reported 4 leaks, 2 of them traded players excluded only under their OLD team. A team-keyed rule needs a team-keyed check.
- **How to apply:** when a check passes, ask what input would have made it fail and whether the population contained one. For anything that matches NAMES across two code bases, test with punctuated, accented and suffixed names explicitly, against the OTHER side's real normalizer -- never a copy of your own.

## 2026-10-05 — RULE: a pre-registered "no cell worse" bar over many cells must state its false-fail rate under the null BEFORE the run `[lane nhl-season-inputs-in-season, session 9ed26377]`

- What happened: I pre-registered "no line's 95% CI entirely > 0 in any of all / Oct / Nov+" over 33 cells (11 prop lines x 3 periods) for the NHL in-season props inputs. Two variants (H16, H17) each failed on ONE cell, at the boundary (+0.00012 [+0.00001, +0.00028]), in the same 6-game window (10-27..10-31) where the arms first differ. Under a TRUE null, P(at least one of 33 one-sided 2.5% exceedances) is ~0.57, so the bar fails a no-effect change about half the time. I wrote that down only after the second failure, and did not use it to pass anything.
- Rule: for a multi-cell guard, compute 1 - (1 - alpha)^cells (or simulate it on a null arm) and print it next to the bar when you pre-register it. Then either budget the cells (e.g. pre-register a few primary cells; treat the rest as reported, not gating) or accept the stated false-fail rate.
- Also confirmed the props lane's rule (2026-10-04): MAE improved in October while Brier at POINTS@0.5 got worse (+0.00144 [+0.00014, +0.00275]); gate props on Brier at the lines.

## 2026-10-05 — RULE: an overnight ONE-TIME scheduled task is DEFERRED, not skipped. It fires hours late when the laptop wakes, or not at all, and it stays armed `[lane ncaaf-total-level-shrink, session 64f14d78]`

- What happened (10-04/05): 3 overnight one-time tasks missed their slot. `ncaaf-total-level-shrink-fit` (fireAt 3:30 AM CT 10-04) started at 11:29 AM CT, **~8 h late**. `fleet-restart-fee-net-env-1004` (11:30 PM CT) and `ncaaf-live-shrink-03-post-restart-reading` (1:15 AM CT) both had **totalRuns 0** at 9:20 AM CT 10-05 and were still `enabled`, with nextRunAt in the past. The deploys.md entry said the shrink "loads at the 04:30Z guarded restart". It loaded through the supervisor's natural role restarts instead (06:19 / 09:06 / 09:18 CT).
- Cause (BELIEVED, consistent with MEASURED precedent): Windows Modern Standby. state.md "Live-gameline collector (laptop cron)" measured one standby span covering a 23:34 CT fire, 6 of 10 nights. Wake timers do not help (AC=important-only, DC=disabled).
- How to apply:
  - Do not write "loads at the <overnight time> restart" as if it were a schedule. Name the READING that proves the load, and judge it by process start time vs checkout time.
  - Judge a scheduled task by `list_task_runs` totalRuns plus its artifact, never by fireAt or lastRunAt.
  - **A missed one-time task with side effects is a LIVE HAZARD.** Its late fire runs in daylight, outside the window the user approved. After a miss, disable it or re-scope it with the user. Never assume it expired. This is especially true of a restart task, which can kill an in-flight sim.
  - Prefer a daytime or attended slot for anything with a production side effect. An overnight task should be read-only and idempotent.

## 2026-10-05 — RULE: a paid fetch loop must probe one call first and stop on consecutive failures; env precedence can silently pick a dead key `[lane nhl-lines-backtest, session 9ed26377]`

- What happened: the NHL 3-way backfill's key resolver reads `os.environ` before `.env`. The session shell exports an `ODDS_API_KEY` that is DEACTIVATED (401 `DEACTIVATED_KEY`); the `.env` key works. The first run only worked because a failed key extraction left the override empty and it fell through to `.env`. The restart used the exported key: every call 401'd, the loop (which skipped failures) cached nothing and printed nothing, and it read as a stall for minutes.
- Rule: before spending, probe ONE call and print status + `x-requests-last` only; make the loop raise after N consecutive failures (be62ddad does 5); name which key source won (env vs `.env`) without printing it.

## 2026-10-05 — RULE: an OFFLINE backtest replay silently runs the OLD engine once the engine reads a new endpoint; prove the new field is populated before scoring `[lane nhl-season-inputs-in-season, session 9ed26377]`

- What happened: re-running the NHL props A/B "on the current engine" after c29e1271 / de074a80. Both read per-game PP/SH minutes from a NEW host (NHL stats API) through the harness's HTTP cache. Offline (`allow_net=False`), the cache misses, `special_teams_toi` swallows the miss as an "enrichment" and returns {}. Lineups then fall back to positional PP units with `proj_ev_toi = None`: the old engine path, with no error and plausible numbers.
- Rule: before scoring a replay of a changed engine, count the new field in the replay's own artifacts (here proj_ev_toi on 833/833 skaters). Diff the projections against the previous run (here 97% of lambdas changed). Only then score. An engine change that adds an endpoint needs the harness online (or a pre-fetch) once.

## 2026-10-05 — RULE: a scheduled task's newest run stuck at `running` blocks every later firing, and the only symptom is the backlog it was supposed to clear `[lane: none, user-requested lanes.md archive]`

- What happened: the digest reported `LANE ARCHIVE OWED: 20 closed/orphaned lanes still in lanes.md`, which reads as a backlog for a human to clear. The job that clears it, `archive-closed-lanes-0917` (every 2 h, `enabled: true`), had not run since **2026-10-01T00:11:30Z** — 4.6 days. `list_task_runs` shows why: that run is still `status: running` with `last_activity_at` **15 seconds** after `started_at`, hung inside a Bash call. No run has started since.
- **`enabled: true` and a future `nextRunAt` are not evidence the task is running**, and neither is `lastRunAt` — it is the DISPATCH of the wedged run ([[project-lastrunat-is-dispatch-not-execution]] says the same of a stalled call; this is the stronger case where the stall is permanent and silent).
- Rule: when a digest counter that an automation owns is high, read `list_task_runs` for that task BEFORE treating the count as work to do by hand. A newest run in `running` with `last_activity_at` far behind `started_at` is wedged, and hand-clearing the backlog leaves the cause in place, so the count returns.
- **Cleared 2026-10-05 18:13Z** by `stop_session` on the wedged run (user instruction; the auto-mode classifier had refused it unprompted). The run's status flipped `running` -> `succeeded` and nothing is in flight, so the 2-hourly cron can dispatch again. **What that measures is the BLOCKER clearing, not the task working** — the next natural tick was 19:37:40Z, and only a run appearing after it proves dispatch. The fix for a wedged run is therefore a one-line check, not a rebuild: stop the stuck turn.
- **RETRACTED THE SAME DAY, 20:40Z — the wedge was REAL but is NOT the cause, and the stop did NOT restore dispatch.** Measured after clearing it: the 19:37:40Z slot produced nothing (watched to 20:36Z, 59 min past due and past the ≤760 s jitter; `totalRuns` still **58**). Wider reading: **0 of 8 enabled cron tasks have run in 3 h**, the newest cron dispatch of ANY task is `soccer-inplay-693-verify` at **72.3 h** ago — an HOURLY task — and the last dispatches of any kind were two one-time tasks ~25 h ago.
- The frozen-run signature is real and widespread: 3 of 4 enabled cron tasks checked have a newest run stuck at `running` **11-15 seconds** after `started_at` (`archive-closed-lanes-0917` 15 s, `soccer-inplay-693-verify` 13 s, `live-gameline-accuracy-snapshot` 11 s) — all unattended runs, all frozen on an early tool call. **But `venue-order-family-census-daily` refutes it as the explanation:** its newest run `succeeded` (09-30, 41 min) and that daily cron has still not fired in 5 days. A per-task "skip while a run is in flight" cannot produce that.
- **ROOT CAUSE OF THE FREEZE, reproduced on demand 20:43Z.** `run_scheduled_task` ("Run now") DID create a run (`totalRuns` 58 -> **59**), so run creation is not broken. That run froze at the identical mark: `started_at` 20:43:09Z, `last_activity_at` 20:43:24.9Z = **15.9 s**, and its transcript's last entry is a `tool_use` of **Bash** — `ls -la /c/tmp/lane-archive-tools/; date -u; TZ=America/Chicago date; wc -c ...` — with **no tool_result for ~90 s** until a `stop_session` produced the rejection row. An unattended run has nobody to answer a permission decision, so it waits forever. That is the 11-16 s signature on every task.
- **Therefore a restart cannot fix the freeze**, whatever it does for the timer: cron firing again would produce frozen runs, not archived lanes. The fix belongs in the task's tool approvals (its first Bash call is a compound command over `C:	mp` and the primary tree), not in the process.
- Blocked here, for the user: `update_scheduled_task {enabled:false}` (a toggle to re-arm the timer without restarting anything) is refused by the auto-mode classifier, as is `stop_session` unprompted. An app restart is the user's call and is NOT cheap — measured at 20:41Z: **5 peer sessions had written transcripts within the last minute**, 10 within 30 min, and **14 worktrees held uncommitted paths** (one with 42). A restart also ends the session that would verify the result.
- So the standing conclusion is **cron dispatch is broken HOST-side, not per task**, since ~2026-10-02T20:17Z. What survives of the rule above: read `list_task_runs` before trusting a digest counter, and never read `enabled: true` + a future `nextRunAt` as evidence — **`nextRunAt` advanced from 19:37:40Z to 21:37:40Z with no run created and `lastRunAt` unmoved**, so it is recomputed arithmetic, not a record that anything fired.
- Also measured the same day: `owner_liveness.py` returning `SAFE_SLUGS=` (empty) for all 20 is the gate WORKING, not a failure. It decides whether a block is safe to archive *from outside its owning session*; every one of the 20 was closed within the day by a session still live. The one thing it cannot establish for itself is that YOU own the block — so an operator may archive their own CLOSED blocks and must leave the rest.
- And: `git blame` over a CLOSED block's line range before archiving it is worth the call. One line inside this session's block was a peer's NHL full-season measurement, which archiving would have moved out of the lane that earned it. Three other peer attributions in the same pass were only boundary lines (`- Blocked by: none` plus a blank, rewritten when a peer inserted a block below), so blame needs reading PER LINE, not per commit.


## 2026-10-05 PRIME DIRECTIVE: no market is withheld; accuracy ranks, it never hides `[user directive, lane stop-market-withholding]`
- **Verbatim:** "WE HAVE TO STOP WITHHOLDING MARKETS! THIS IS A PRIME DIRECTIVE OF THE APP. All lines are judged individually - models are tested for accuracy but each bet is at the line level".
- **Overrides (logged as an explicit user override):** the 2026-09-11 "Withhold, all sports" admission rule (incl. its 2026-09-14 `loses_to_market` clause) and the `#400` excluded-markets knob. Both REMOVED from `layer2_board.select_shortlist`, not defaulted off.
- **FORBIDDEN:** any rule that removes a row, pick, edge or stake because of its MARKET, market family, or a (sport, market) model verdict. A gate must be a property of the LINE (its price/EV, quote age, an impossible book, game state, the per-game cap). A model's measured accuracy may only scale rank/stake (`skill_reliability`).
- **Why it mattered, measured:** fleet build 2026-10-05 withheld 3,166 rows by the removed rule; 3,111 were soccer player props, while ~770 credits/h were still being spent fetching them.
- **Same lane, same day, also removed (user: "go ahead with all three"):** `football/pick_gate.py` is now a LABEL (NCAAF model picks served with their measured record, never dropped); `live_gameline_join.publishing_disabled_for_sport` deleted (fleet refresh-worker still carried `SYNDICATE_LIVE_GAMELINE_PUBLISH_DISABLED_SPORTS=nfl` -- now inert); `portfolio_commit` sizes EVERY model edge x `skill_reliability` (floor 0.5) -- the 09-19 `measured_only` gate and the 09-18 NCAAF price-basis rule are deleted, their env keys inert.

## 2026-10-05 -- A tier-mean bias fix is not a line-accuracy fix (lane nhl-elite-assists)

- **Belief overturned:** raising the elite tier from 0.66x to 0.91x of real assists would improve the ASSISTS@0.5 line. It made it WORSE (+0.00095, CI excludes 0) while every tier mean got closer. Amplifying a noisy per-player signal fixes the bucket averages and spreads noise across the bulk of players; the line Brier is what pays for it. The milder weighting (0.78x) was flat on assists and better on points, and shipped.
- **Rule:** gate an attribution change on paired per-player Brier at the lines, never on tier calibration alone; report both.
- **Also measured:** sequential primary/secondary sampling from four teammates compresses weight ratios -- real-share weights at power 1 barely moved the elite (0.63x -> 0.65x). Decompose a count into rate x share against real data (shift charts) before changing the attribution.

## 2026-10-05 — RULE: `nhl_sim_input_checklist.py` audits the git mirror unless `SYNDICATE_ARTIFACT_ROOT_NHL` points at the prod disk; read its `dates` line before trusting PASS or FAIL `[lane nhl-confirmed-goalies, session 9ed26377]`

- What happened: run on the fleet with `SYNDICATE_DATA_ROOT` set (which it does not read), it fell back to `nhl_source_root()` = the repo's June mirror. It printed `dates 8 (2026-06-02..2026-06-14)` and a wall of FAILs, and I wrote it off as "not usable as this gate".
- With `SYNDICATE_ARTIFACT_ROOT_NHL=/home/amyn/syndicate-prod/data/nhl_source` it audits the live dates (09-30..10-08) and PASSes, incl. is_starting_goalie exactly one per team per game. Corrected by the props lane's session.
- Rule: the `dates` line is the substrate. If it is not the slate you mean, the verdict is about a different system.

## 2026-10-05 — RULE: the scheduled-task freeze is an APPROVAL-list gap, and fixing it is the USER's action — `[Self-Modification]` blocks the agent `[lane: none, user-requested]`

- Measured: `permissions.allow` holds **312 rules at user level (304 Bash) and 71 project-local (58 Bash), and they are nearly all hyper-specific literals** — a whole pytest invocation, a whole grep with its path — because each was created by clicking "allow this exact command". There are **ZERO** rules for `date`, `wc`, `stat`, `printf`, and exactly **one** for `ls` (a 150-character literal). The routine's first command is composed fresh at runtime (`ls -la /c/tmp/lane-archive-tools/; date -u; TZ=America/Chicago date; wc -c …`), a COMPOUND of four segments, and matches nothing — so it prompts, and an unattended run has nobody to answer.
- **A literal allowlist cannot fix this class of failure.** Every run composes new commands; the next one hangs on a different line. The structural options are a few read-only PREFIX rules, or a permission mode for the routine that does not prompt — and `update_scheduled_task` exposes no permission-mode field, so the prompt mode cannot be changed through the MCP tool.
- **The agent cannot apply either fix.** Writing `permissions.allow` is refused as `[Self-Modification]`, and `update_scheduled_task {enabled:false}` (the no-restart way to re-arm the timer) is refused too. Both refusals are correct and must not be routed around; record the exact rules and hand them to the user.
- Rules handed over 2026-10-05, in BOTH syntaxes because this installation's 22 Bash glob rules use the space form (`Bash(git add *)`) while the documented form is the colon one: `ls`, `date`, `wc`, `stat`, `TZ=America/Chicago date`, each as `Bash(<cmd> *)` and `Bash(<cmd>:*)`. **Caveat stated to the user, not hidden:** a prefix rule also matches the same command with a shell redirection (`ls > file`), so it is not read-only in the strict sense.
- Placement: `.claude/settings.local.json` in the PRIMARY tree, which is git-ignored (`~/.config/git/ignore` line 1) so it is local and not shared through git — and the primary tree is exactly where a scheduled run's cwd is, while worktree sessions have no copy of that file.
## 2026-10-05 -- A paired comparison on common keys cannot see a coverage change (lane nhl-scratch-dilution)

- **Measured:** the last-game dressing rule read as "Brier flat on every line" on 35,613 common player-games, but the two runs projected DIFFERENT players: 2,674 played player-games only under the new rule, 920 only under the old (36,533 -> 38,287 projected). The gain was coverage (lines that become priceable instead of refused), invisible to a key intersection.
- **Rule:** when a change alters WHO is projected, report the covered population of each arm and the symmetric difference beside the paired metric; never let the intersection's silence stand for "no effect".
- **Also (lane nhl-elite-assists):** normalising per-goal assist inclusion to the engine's assist count (1.615) PENALISES elites on strong lines (sum of linemate shares ~1.9) -- elite 0.73 -> 0.68. Single-player shares cannot express "linemates assist less beside him".

## 2026-10-05 -- RULE: an unattended scheduled task must need ZERO permission decisions, and a re-armed fresh task proves the timer, not a stopped run `[lane daily-optimizer, session 5942cf5f]`
- The freeze (every unattended run stuck ~11-16 s after start) is a permission prompt nobody can answer. It is fixable PER TASK: make the run's only shell call one fixed command (put any reader script in the task's own folder so the run needs no git / repo-lag workaround) and pre-approve exactly that command in `.claude/settings.local.json`. Measured: `daily-optimizer-review` run-now 21:30:45Z `succeeded` in 30 s with no prompt.
- `list_task_runs.last_activity_at` LAGS the transcript: it read 16.4 s (the frozen signature) while the run had already received its tool result. Read the transcript (the session's .jsonl) before calling a run frozen.
- The TIMER is separate and host-wide: a task re-armed as a one-time `fireAt` 2 min out did not fire (21:37Z, checked 21:39Z). A fresh, re-saved task is the discriminating test; "stop the wedged run" is not. Remedy is an app restart, which is the user's call.

## 2026-10-05 — RULE: a gated fleet restart must re-check the checkout's HEAD at TERM time, not only at launch. The disk moves while the gate waits `[lane layer2-unmeasured-per-line, session f028352c]`
- **What I believed:** my gated restart was safe because it refused unless `~/Syndicate` HEAD was an ancestor of the approved target and then fast-forwarded to it. That check ran ONCE, at launch.
- **What was true:** `check_deploy_safety` stayed NOT CLEAR for 45-60 minutes per attempt (odds runs, an MLB sim), and in that window other sessions fast-forwarded the fleet FOUR times with no restart (`82e26761`, `340b04cd`, `bce1cb2a`, `cb1bb280`). Each is legitimate on its own -- a ff loads nothing into a running role. But the TERM loads whatever is on disk AT THE TERM. One of those moves carried part B UNSCALED (`fcd348cd`), which the user had rejected. The script would have loaded it on the next CLEAR. A peer's message caught it, not the script.
- **The rule:** in any wait-then-restart script, re-read `git rev-parse HEAD` immediately before the TERM and refuse unless it equals the approved SHA (not merely descends from it). Name the SHA the role will load in the approval, and re-ask the user when it changes. Also: claims have a 45-min TTL and no renew, and a long gate outlives them, so re-acquire before expiry. The release needs `--token`.
- **Cost:** one manual abort, three extra user decisions, ~2 h of restart latency.

## 2026-10-05 — RESOLVED: the approvals were applied on user instruction and the routine now RUNS; the `git -C` shape was the real gap `[lane: none, user-requested]`

- **The discriminating fact, measured:** the allowlist held **21 git rules and ZERO matching the `git -C <path> <sub>` shape** — they are all plain `Bash(git fetch *)`, `Bash(git diff *)`. The scheduled routine always writes `git -C <abs path>` (CLAUDE.md requires it, because parallel Bash calls share a cwd), so **every git call it makes misses every git rule**. That is why this routine froze where interactive sessions never do. A prefix rule cannot reach the subcommand when `-C <path>` sits in front of it, so the rules need a mid-pattern glob (`Bash(git -C * fetch *)`) plus literal primary-tree forms as a fallback.
- Applied with the user's explicit go-ahead after a `[Self-Modification]` refusal: **71 -> 141 allow rules** in the git-ignored `.claude/settings.local.json` of the primary tree. 10 read-only utilities (`ls`/`date`/`wc`/`stat`/`TZ=… date`), 44 `git -C` rules over 11 READ-ONLY subcommands, 14 rules for the three script entrypoints. **User decision: read-only only** — nothing for add/commit/merge/rebase/reset/restore/checkout/stash or `session_worktree.py`, asserted in the writer so a destructive rule aborts the write.
- **Verified end to end, not assumed.** Runs 59 and 60 froze at 15.9 s and 25.5 s with `tool_use=1, tool_result=0`. Run 61 after the change: the first compound RETURNED (`total 1084 drwxr-xr-x …`), the three tool files were read, and it reached `py -3 …/owner_liveness.py --worktree … --idle-min 240` — `tool_use=6, tool_result=5`, still advancing at 34 s+. **The measurement that distinguishes the states is `tool_result` count, not elapsed time.**
- Carry-over: a run that DOES find SAFE slugs will stall at its commit/land step, by design. That is the safe failure — an unattended run stops rather than writing unsupervised in the shared primary tree.

## 2026-10-05 — RULE: before logging "reading owed on the first slate with X", prove X can occur; check that the fetch even requests it `[lane nhl-confirmed-goalies, session 9ed26377]`

- What happened: I logged "served-board SAVES coverage: owed on the first slate with SAVES book lines", and checkpointed it twice. `local_nhl_odds.collect_oddsapi_props` requested only points / assists / goals / SOG, so no SAVES line could ever arrive. The owed reading had no possible due date.
- Rule: for any reading gated on a future event, check the event's precondition in the code or data path NOW (here: the market list, then a grep of `player_props_lines` and the quote log). A reading whose trigger cannot fire is not owed; it is a defect. Related: 2026-10-05 learning on a "no cell worse" bar's null rate; memory "Caveat = scheduled defect".

## 2026-10-05 -- Windows open() without encoding silently halves a JSON dataset (lane nhl-elite-assists)

- **Measured:** 1,340 of 2,792 NHL play-by-play files failed `json.load(open(f))` -- cp1252 default vs UTF-8 player names -- inside a `try/except: continue`, so the parse "succeeded" on 1,452 games and the first cross-validation ran on half the data with no error. Caught only because the game count (1,452) did not match the fetch count (2,792).
- **Rule:** pass `encoding="utf-8"` on every `open()` of fetched data, and print the parsed count beside the expected count before using any result -- a swallowed exception in a loader is a denominator change, not a skip.

## 2026-10-05 — RULE: the read-only grant was allowed and the WRITE grant is refused as `[Self-Modification]`; and the next blocker is unmatchable by ANY rule `[lane: none, user-requested]`

- Same mechanism, same user authorisation, **opposite verdicts**: writing 58 READ-ONLY rules went through, and writing the 38 destructive ones (`git -C * add|commit|merge|rebase|reset|restore|checkout|stash|apply`, plus `session_worktree.py`) is refused as `[Self-Modification]`. Do not retry past that and do not reach it another way; hand the list to the user. It is saved at `C:\tmp\settings-backup-2026-10-05\write_rules_for_user.txt`.
- **AND THE WRITE GRANT WOULD BUY NOTHING ON ITS OWN, which is the part worth knowing before anyone pastes it.** Run 61 does not fail at a git write — it fails EARLIER, at Phase A1, on `SP='…\<run-uuid>\scratchpad'; cat > "$SP/mk_wait.py" <<'EOF'`. The first segment is a VARIABLE ASSIGNMENT whose path carries that run's own uuid, so no prefix rule can reach it and no literal can be written in advance. The allowlist is the wrong instrument for this one.
- The two fixes that would actually work: a **non-prompting permission mode** for the routine (not exposed by `update_scheduled_task`, whose fields are title/prompt/description/cron/fireAt/enabled/notify), or **editing the task PROMPT** so Phase A1 builds its private watcher copy with the `Write` tool instead of a shell heredoc. `prompt` IS settable, so the second is the cheap one — but it is a rewrite of a 12,508-byte task file and needs its own decision.

## 2026-10-05 — RULE: a scheduled task stores the tool approvals granted DURING a run; the allowlist was never the right lever `[lane: none, user-requested]`

- `update_scheduled_task` said it outright in its own result: *"Tool approvals granted during a run are stored on the task and auto-applied to future runs… recommend the user click 'Run now' first to pre-approve the tools it needs — this prevents future runs from pausing on permission prompts."* So the fix for a frozen routine is **one ATTENDED run in the app's UI where the user approves the prompts**, after which unattended runs inherit them. Nothing in `permissions.allow` was needed.
- That also explains the FAILURE MODE this chased all day: the task ran fine for months on its stored approvals, then composed a command shape it had never been approved for (`SP='…'; cat > "$SP/mk_wait.py" <<'EOF'`), and an unattended run had nobody to approve it — so it froze, and a frozen run blocks every later firing. **A routine's approval set is a function of what it has ALREADY been asked to do, so a prompt that leaves the MECHANISM open is a latent freeze.** That is why A1 now names the Write tool instead of saying "write a copy ... by a short Python script".
- Applied 2026-10-05 and verified byte-exact: the A1/A2 rewrite plus a standing `EVERY BASH CALL IS ONE COMMAND` constraint. 2 lines removed, 6 added, 2 hunks; the applied body matches the candidate at **0 differing lines and the same sha256**, frontmatter intact, and 9 structural checks pass (Phase B, Phase C, the NEVER list and the zero-move rule all unchanged).
- Keep in proportion: the 58 read-only allow rules added earlier are not wrong, they are just not the mechanism. The `git -C` finding stands on its own — 21 git rules existed and **0** matched the `git -C <path> <sub>` shape the routine uses.

## 2026-10-05 — RULE: fixing a mean-level bias is not evidence for the market; and a backtest must resolve names exactly as production does `[lane: soccer-xg-totals-bias]`

- **The belief overturned:** that soccer's totals loss to the book was the model's goals-level bias (2025-26 xG leagues: 2.95 projected vs 2.77 actual). A season-tracking level correction took the 2025-26 mean bias from +0.071 to +0.005 and O/U 2.5 Brier did not move (+0.0004 [-0.0015, +0.0022], n 2,724). A threshold market's skill is not the mean's: grade the MARKET the correction is for, not the bias it removes.
- **Cheap screen that held:** independent Poisson from the dumped as-of goal means reproduced the sim's own O/U 2.5 Brier within 0.0004-0.0013. A goal-mean intervention can be screened on existing dumps in seconds, with both arms through the same approximation, before paying ~37 CPU-s/match of re-simulation.
- **Backtest name resolution:** the h2h harness's thin-ratings filter used a raw `ratings.get(name)` while the sim used `match_team_name`, so the five Understat leagues silently scored only identically-named teams (EPL 170 of 380). The same audit found production's fuzzy matcher pricing promoted Le Mans as Lens. A backtest that resolves names differently from production is testing a different sample, and a fuzzy matcher's failures are wrong-CLUB joins, not misses -- check `match_team_name(x) != x` across the served names before trusting either.

## 2026-10-05 — all three frozen scheduled tasks hardened the same way: pin the MECHANISM in the prompt, then one attended run stores the approvals `[lane: none, user-requested]`

- **Same disease in all three, each frozen on its FIRST composed tool call with `tool_use` one ahead of `tool_result`:** `archive-closed-lanes-0917` 15.9 s on `SP='…'; cat > "$SP/mk_wait.py" <<'EOF'`; `soccer-inplay-693-verify` 13 s on a multi-statement PowerShell one-liner (`$r = Invoke-RestMethod …; $lg = …; [pscustomobject]@{…} | ConvertTo-Json`); `live-gameline-accuracy-snapshot` 11 s on a three-segment Bash compound (`powershell -NoProfile -Command "…"; git -C "…" fetch -q origin; ls … && echo EXISTS || echo MISSING`). **None of the three prompts named the mechanism**, so each run improvised a shape its stored approval set had never seen.
- Fix applied to all three: a standing **ONE STATEMENT PER TOOL CALL** rule (no `;`, no `&&`, no shell or PowerShell variable assignment, no heredoc; files via Write, reads via Read, multi-step work via a scratchpad Python script run as one command), plus the measured freeze cited in each so nobody relaxes it later. `archive-closed-lanes-0917` also got A1 pinned to the Write tool and A2 to one command.
- **Verified byte-exact, not assumed:** archive body matched its candidate at 0 differing lines / same sha256; `live-gameline` likewise (body 24,116 -> 25,152 B, sha `b4465f9094fd3ab5`, 13/13 structural checks); soccer 5,475 -> 6,491 B with 18/18 checks, including that the self-grep warning, the unknown-is-not-zero rule and the Step 5 self-disable all survived.
- **A direct write to a scheduled-task `SKILL.md` is refused as `[Auto-Mode Bypass]`** (confirming the earlier tripwire finding) while `update_scheduled_task` is the sanctioned path and works. It replaces the WHOLE prompt, so every edit is a full-file send — build the candidate on disk first and diff the applied result against it, which is the only thing that catches a transcription error in a 25 KB production routine.
- All three frozen runs cleared (`running` -> `succeeded`), so nothing is in flight blocking dispatch. **What remains is the user's: ONE attended "Run now" per task**, approving the prompts, after which unattended runs inherit the stored approvals.

## 2026-10-05 — RULE: a measured-skill registry change reaches the board only after a REFRESH-WORKER restart; and a ride-along's state must be re-read at TERM time, not at ff time `[lane nhl-saves-skill-registry, session 9ed26377]`

- What happened, part 1: after registering NHL SAVES I did ff + web HUP and read the board. Still `unmeasured`. `/api/board/book-grid` serves a refresh-worker ARTIFACT (`enrichment_state: from_artifact`), and the post-ff rebuild (23:07:53Z) also read `unmeasured`: the long-lived refresh-worker process held the old module. Only the gated refresh-worker restart (23:46:37Z) moved it (10/10 measured at 23:47:15Z).
- What happened, part 2: I wrote that a ride-along (NBA game-line blend) was "still gated by its switch file". I had read the file's absence at ~23:05Z; the user placed it at 23:31:48Z, 15 minutes before my TERM. The restart loaded it ACTIVE. Corrected in deploys.md 61355e97, after the watcher session asked.
- Rule: verify a registry or skill change on the served artifact after a refresh-worker restart, not after a web HUP. Read every ride-along's switch/env state at the moment of the restart, because the gate can wait 40 minutes.

## 2026-10-06 — RULE: a per-task stored approval cannot carry a command whose TEXT changes every run — and these runs' pinned command does `[lane: none, user-requested]`

- **The command is unique per run, twice over:** the scratchpad path carries the RUN'S OWN UUID (`…\claude\<run-uuid>\scratchpad\…`) and the helper script's FILENAME is the model's choice, different each time — observed `mk_wait_patched.py`, `mk_patch.py`, `nightly.py`, `probe.py` across four runs of three tasks. So an approval of the exact string can never match the next run.
- **Measured, after the user approved all three:** the parked runs' pending calls received **no result for ~26 minutes** (the only row that ever arrived was the rejection my own `stop_session` produced), and a **FRESH** archive run started at 23:59:09Z — after the approval — did `Glob, Read, Read, Write ✓` and then **waited again** on `py -3 "…\607aefda-…\scratchpad\mk_patch.py"` (5 use / 4 result). Two readings fit and I cannot separate them from here: either the stored approval is exact-string, or it never registered on the task.
- **So the allowlist IS the right instrument for THIS call, and my earlier "the allowlist was never the lever" was too broad.** Only a PREFIX rule can cover a per-run path. The nine needed rules (Bash and PowerShell × quoted/unquoted × backslash/forward, plus the `ARCHIVE_WORKTREE=` form) are saved at `C:\tmp\settings-backup-2026-10-05\scratchpad_rules_for_user.txt`; writing them is refused to the agent as `[Self-Modification]`.
- **The better fix needs no permission at all: make the command TEXT STABLE.** Have each prompt write its helper to a FIXED path (`C:\tmp\sched-task-scratch\<task-id>\run.py`) and invoke exactly that string every run. Then ONE per-task approval matches forever, and nothing has to be added to `permissions.allow`. A task runs at most one session at a time, so a fixed path cannot collide with itself.
- What already works and should not be re-litigated: the **Write tool is auto-approved**, and all three rewritten prompts now produce exactly one pinned command instead of an improvised compound.

## 2026-10-05 -- A sim-vs-real ratio on a definition-dependent count can flip sign (lane nhl-elite-pp-onice)

- **Measured:** "elite PP on-ice goals-for" read 0.82x real on one definition of a power-play goal and 1.69x on another -- official PPG (landing pp_goals) 393 vs skater-count PPG from pbp situationCode 259 on the same 345 games. A lane was opened on the 0.82x. The quantity measured identically on both sides (PP ice time: sim shift seconds vs NHL stats ppTimeOnIce) showed the real defects (PP1 0.903 vs 0.632 of PP time; team PP time 1.47x).
- **Rule:** before acting on a sim-vs-real ratio, confirm the numerator is counted the same way on both sides; when the definition is ambiguous, decompose on a quantity that is not (time, shots).

## 2026-10-06 — FIX APPLIED: each scheduled task now writes its helper to a FIXED path, so one approval matches every future run `[lane: none, user decision]`

- The approval could never carry forward because the command text was unique per run (run-uuid in the scratchpad path, plus a model-chosen filename). All three prompts now pin BOTH halves to a constant: Write to `C:\tmp\sched-task-scratch\<task-id>\run.py` and run exactly `py -3 "C:\tmp\sched-task-scratch\<task-id>\run.py"` (the archive task keeps its `ARCHIVE_WORKTREE=` prefix, also constant). **Nothing needed to go into `permissions.allow`.**
- Verified byte-exact on all three: 0 differing lines against the on-disk candidate and matching sha256 — soccer 6,874 B (1 fixed-path ref), archive 13,511 B (2 refs: the A1 Write target and the A2 command), live-gameline 25,661 B (2 refs). No `<your scratchpad>` reference remains in any of them. Directories pre-created so no run has to.
- **Why a fixed path is safe here and is not the `C:\tmp\lane-archive-tools\` hazard:** a task runs at most one session at a time, so it cannot collide with itself; the file is rewritten every run and holds no state, so a stale copy cannot be mistaken for a fix; and nothing reads it but the run that wrote it. The lane-archive-tools warning is about SHARED, HAND-MAINTAINED scripts that a rewrite can silently revert — the opposite case.
- The remaining step is one approval per task, and it now sticks. If a run still stalls, read the `tool_result` count (not the clock) and check whether the stalled call is the constant one or something new.

## 2026-10-06 — two residual facts about the fixed-path fix, measured on the first run under it

- **The fixed path took effect**, and the run reached it: fresh archive run (`b37f92ee`) did `Glob, Read, Read` then a `Write` to `C:\tmp\sched-task-scratch\archive-closed-lanes-0917\…` — 4 use / 3 result.
- **A Write OUTSIDE the per-session scratchpad PROMPTS; inside it is auto-approved.** Measured both ways within an hour: three runs' Writes to their own scratchpad returned immediately, and the first Write to the fixed `C:\tmp` directory is pending. So the fixed-path design does not remove an approval, it makes the approval CONSTANT — which is the whole point, but say it accurately.
- **The model did NOT honour the pinned filename:** the prompt says `run.py` and the run wrote `build_run.py`. A prompt can pin a DIRECTORY reliably and a FILENAME only by persuasion, so the durable form of the approval has to be directory-scoped, not command-string-scoped. If the stored approval turns out to be exact-string, the filename drift defeats it the same way the uuid did.


## 2026-10-06 -- A free-memory guard must read AVAILABLE memory, and `--workers 1` is not one process `[lane nhl-pp-time, session dd07cae9]`

- **Belief overturned:** "free memory 1.2 GB" (Win32_OperatingSystem.FreePhysicalMemory) was read as the host's headroom. It excludes the standby cache; `\Memory\Available MBytes` read 2.85 GB at the same moment. A guard on FreePhysicalMemory waits forever or kills for nothing. Use the Available counter.
- **And:** `scripts/backtest_nhl_props.py --workers 1` still forks a ProcessPool worker, so records.pkl is held twice (~0.9 GB together); one in-process driver over `run_date` holds it once (~0.45 GB). Measured: 2 workers tripped a 1.8 GB floor in 34 s; the in-process driver runs under 1.2 GB with resumable per-date output.
- **How to apply:** guard on Available, run memory-tight backtests in-process from a DETACHED process (a run tied to a tool call died silently at 19:47 CT with empty stderr), and make every run resumable per date so a guard kill costs one date.

## 2026-10-06 — RULE: a run dispatched by `run_scheduled_task` cannot have its pending permission request answered afterwards; the approval must exist BEFORE the run starts `[lane: none, user-requested]`

- **Three for three.** The user reported approving, twice, and the parked run's pending call still received NO result: archive run `83374649` sat at `use=4 result=3` with `last_activity_at` **00:38:00Z, unchanged for 2h56m**; before it `09a8d6ed` sat ~26 min and a fresh run after the first approval behaved identically. This is evidence about the MECHANISM, not about whether anyone clicked: a request raised inside an MCP-dispatched run appears to be unanswerable after the fact.
- **So the mechanism I built two fixes around was the wrong one.** `update_scheduled_task`'s hint says *"recommend the USER click 'Run now' first to pre-approve the tools it needs"* — I substituted `run_scheduled_task` for that click and the two are NOT equivalent: an MCP dispatch is unattended from birth, so there is no live party for the prompt to reach. The per-task stored-approval path only applies to a run that is ATTENDED FROM THE START.
- **Two things can actually work, and only these:** (1) the user clicks **Run now in the routine's own UI** and approves as prompts appear, which then stores the approvals on the task; or (2) the matching rules are in `permissions.allow` BEFORE any run starts — and writing those is refused to the agent as `[Self-Modification]`, so that path is the user's too.
- Corrections I owe the record, both mine: "the allowlist was never the lever" was wrong (a per-run path needs a PREFIX rule, which only the allowlist provides), and "a fixed helper path makes one approval stick" was premature (it makes the approval constant, but a constant request that nobody can answer is still unanswered). The prompt hardening itself stands on its own merits — one statement per call, Write instead of heredocs — and is verified in all three tasks.
- **Operational cost of getting this wrong: a parked run blocks its task's schedule.** Clearing one is directly measured to restore dispatch (live-gameline fired 52 s after a clear). All parked runs were cleared 2026-10-06 03:35Z.

## 2026-10-06 — FORBIDDEN: rewriting a shared ledger file through a TEXT-mode read (Python read_text/open('r'), universal newlines). A lone carriage return in someone else's line becomes a line break `[lane basketball-injury-exclusion-reinclusion, session 39b666bb]`

- `lanes.md` carries a lone carriage return (CR, byte 0x0D) inside a peer's nhl checkpoint line. My one-line insertion read the file with `read_text()` (universal newlines turn a lone CR into a line feed) and wrote it back: the peer's line was split in two. The numstat (3+/1-, for a 1-line insert) was the only sign.
- The repair has a second trap. On this CRLF worktree, a file holding a lone CR is NOT converted by git (the conversion would not be reversible), so the whole-file diff showed 2,116+/2,115-; the fix was writing the exact BLOB bytes (all LF, lone CR kept).
- Third instance, same session: writing THIS entry through a shell heredoc turned the backslash-r escapes I typed into real CR bytes, and learnings.md showed a whole-file diff (3,155+/3,148-). Caught by the numstat gate, rebuilt from the HEAD blob.
- **How to apply:** edit ledger files as BYTES (read_bytes / split on the LF byte / write_bytes), and write entry text from a FILE made with the Write tool, never through a heredoc. Gate every ledger commit on numstat equal to the lines you meant to change, never just "deletions == 0". Verify on origin with `MSYS_NO_PATHCONV=1 git show origin/main:<path>` (Git Bash mangles rev:path).

## 2026-10-06 — RULE: when a default moves from a DEAD endpoint to a LIVE one, every test that leaned on the default starts doing live I/O `[lane scripts-fleet-default, session 5da10f7c]`
- **Belief overturned:** "token helpers are safe to call in tests". They were only safe because the default target
  was Render, which the helper never contacted and whose token sat in a file the test redirected. Flipping the default
  to the fleet made a no-argument call read the LIVE fleet token through `wsl.exe`, and a failing assertion printed it.
- **How to apply:** before flipping a default, grep the tests for calls that pass no explicit target, and put the
  "never read the real secret under test" rail in the RESOLVER (`'pytest' in sys.modules`), not in a conftest you may
  not hold. Tests of the real path must name their fixture file explicitly.

## 2026-10-06 -- Compute a deploy prediction with the shipped code's own arithmetic (lane nhl-early-season-shot-volume)

- **Measured:** the deploys.md prediction for the roster shot-volume fix said STL -2.8% and league +0.6-1%; the fleet showed STL +1.6% and league +2.0%. The code was right -- recomputed its way, every team matched within ~1 point. The prediction had been derived from a diagnostic script that counted unrated skaters as 0, while the code (and its tuning) count them at a replacement level; STL dresses 3 unrated skaters.
- **Rule:** derive the expected post-deploy reading by calling the shipped function (or the same formula with every fallback it applies) on the live inputs, not from the diagnostic that motivated the change. A prediction from a different computation turns a correct deploy into an apparent miss.

## 2026-10-06 — RULE: on Windows, `subprocess.run(["git", ...], timeout=)` does not stop git; and never `git fetch` the OneDrive primary repo from a scheduled job `[session 5da10f7c]`
- **Measured:** the harvest launcher's `git fetch` of the primary checkout (on OneDrive, hundreds of refs and
  worktrees) sat minutes in `rev-list --objects --not --all --alternate-refs`. Its 120 s timeout killed only
  `git.exe`'s shim; the real fetch, `git-remote-https` and a `git archive` lived on as orphans for ~27 min, the disk sat
  at 101% busy, and later runs stalled even importing a .py file (faulthandler trace in `importlib get_data`), each
  killed by the task's 10-minute limit. Killing the orphans: disk busy 101% -> 14%.
- **How to apply:** a scheduled job that needs repo code keeps its OWN small clone (`--depth 1 --filter=blob:none
  --sparse`, measured ~2 s to update) outside OneDrive. Run git with stdin/stdout/stderr = DEVNULL (a captured pipe
  held by a git grandchild blocks `subprocess.run` past its timeout), `-c gc.auto=0 -c maintenance.auto=false`,
  `GIT_TERMINAL_PROMPT=0`. After any timeout, look for surviving `git.exe`/`git-remote-https.exe` and kill them.
  Arm `faulthandler.dump_traceback_later` below the task's time limit so a stall leaves its own stack.
## 2026-10-06 -- A window-aggregated coverage dict sums its IDENTITY fields (lane layer2-triad-alignment)

- **Measured:** `/api/board/layer2-shortlist` -> `per_sport_ingest.nfl.enrichment.projections.prop_coverage` read `artifact_week=35`, `artifact_season=14182`, `pct_projected=482.3` on a 7-date window. The per-date `/api/board/book-grid` read week 5, season 2026, 63.7-73.6%. On 2026-09-29 the same field verified a deploy (`3f28cdb7`) as "3 -> 4", when the window effectively held one date.
- **Rule:** before trusting a week, season, id or pct read off an aggregate payload, check the aggregation: an identity field that is exactly N x a plausible value is a sum. Read the per-unit endpoint for identity, and use the aggregate only for counts.

## 2026-10-06 -- A peer worktree's modified lanes.md is NOT evidence its lane is unlanded; read origin/main `[session af3cc595]`

- **Measured:** `check_lane_invariants.py` in the primary tree flagged `layer2-coverage-identity-merge` and `wnba-slate-and-out-props` as "marker with no block anywhere". I found each block in its owner's worktree with `lanes.md` showing `M`, reported "written but not pushed", and messaged both owners. Both blocks were already on origin/main (`a1d3b030`; `dfb193bb`/`96228fcf`). The PRIMARY tree had been fast-forwarded minutes BEFORE they landed, and the check reads the primary tree.
- **Rule:** before calling a lane block unlanded, `git show origin/main:.syndicate/lanes.md | grep '^### <slug> '` after a fresh fetch. A dirty `lanes.md` in a worktree only means that worktree differs from its own HEAD. An orphan-marker flag written minutes ago is most often a lane in flight or a lagging primary tree, never grounds to write or delete a block.
- **Also 2026-10-06:** zero freeze/recommendation files for European soccer 09-21..10-08 was the FIXTURE CALENDAR (ESPN: no match in any of the nine leagues), not a writer defect. Before diagnosing a missing per-date artifact, count the real events for those dates.
## 2026-10-06 — RULE: an injury feed of DAILY SNAPSHOTS marks a return by ABSENCE; read the latest snapshot, never the player's latest row `[lane wnba-props-out-player-leak, session 4d5b3bd3]`

- What I believed: "OUT on the feed" = the player's most recent row in `raw/injuries.csv` says OUT (SmartSim's rule: latest row per player within 30 days).
- What was true: the file stacks one full injury report per date, and a player who returns simply does not appear on the next one. Jewell Loyd and Stephanie Talbot were OUT on the 10-05 snapshot and absent from 10-06; the latest-row rule kept them OUT, and my first baseline (64 lines, 3 players) was wrong -- the true count was 39 lines, Allisha Gray only. A peer fix built on SmartSim's map shipped the same over-refusal.
- Caught by: diffing the player sets of two consecutive snapshot dates before trusting a count.
- How to apply: for any feed that RE-STATES current state on each fetch, status = membership in the latest snapshot on/before the date. Check the rows-per-date pattern first; flat counts per date mean snapshots, not events.

## 2026-10-06 — OVERTURNED: "listed soccer players' shares are overstated because absent players' mass is handed to them" `[lane soccer-roster-only-players]`
- **Believed** (pre-registration 5c36cf37): ~25% of shots/goals by players absent from the sim list means listed players' shares are inflated, so adding roster-only players with team totals FIXED would improve the listed players' props.
- **Measured** (119 matches 09-17..09-30, paired engine replay): listed appeared players were already UNDER-predicted (SOT realised 0.256 vs 0.233; starters' first scorer 1.70x); moving mass off them made SOT significantly worse (+0.00162 [+0.00043, +0.00286]) and calibration worse on both markets.
- **How to apply:** before a share-REDISTRIBUTING mechanism, check the sign of the listed players' realised/expected. "Someone else took the shots" says the list is incomplete, not that the listed shares are too big — when the team volume itself is short for the players who play, redistribution is the wrong direction.

## 2026-10-06 — RULE: production shares a CPU with research, and nothing on this host gives production priority; WSL `nice` is invisible to Windows `[lane web-restart-healthz, session 46e09dbb]`
- **Believed:** the web outages of 10-06 (watchdog down 13:52, 14:23, 15:08 CT; Layer 2 board "not loading") were web bugs -- a recycle policy, a slow cold boot, a heavy healthz.
- **Measured:** the 13:52 exit was a session's manual `TERM` of the gunicorn master (deploys.md 18:48:23Z). Everything after was CPU: the Windows host at 100% (research pythons at Normal priority + 8 WSL backtest workers), the WSL VM getting ~3.6 of 12 cores, gunicorn's own log lines stamped 47 s after it formatted them, 7 cold game-chips builds at 234-404 s each, `WORKER TIMEOUT` kills, and the SAME 6 MB board query going from 5-20 s (10-05) to 96-243 s (10-06) with no code or payload change. In-WSL research was already `nice 19` and did not help: Windows schedules `vmmemwsl` as one Normal process against every Windows python.
- **How to apply:** before diagnosing fleet latency, read host CPU (`Get-Counter '\Processor(_Total)\% Processor Time'`) and the per-process split; launch Windows-side research with `start /low` (or set Idle priority) and WSL-side with `nice 19`; a request duration that moved with no payload change is a CPU reading, not a code regression. Raising `vmmemwsl` priority needs an elevated shell (the user's action).
- **Also (mine):** a fleet ff chained `git diff --stat ... && git merge --ff-only` in ONE command -- the merge ran before anyone read the diff (2 inert ride-alongs this time). Diff, READ, then ff in a separate call. And on the fleet the remote is `github`; `origin/main` there is a stale ref that showed 233 bogus changed files.

## 2026-10-06 -- RULE: a deploy drain on refresh-worker HOLDS THE MLB SIM TICK, so retrying a drain is not free; cap the TOTAL drain time, not each attempt `[lane published-negative-ev, session 5942cf5f]`
- The belief: a drain only defers board builds, so re-running `check_deploy_safety.py --drain` until CLEAR costs at most a stale board.
- What was true: while drained, refresh-worker logged `DRAIN_HOLD stage=mlb_sim_tick reason=deploy_drain_requested` every ~30-60 s. Three back-to-back 15-min drains (20:10-21:17Z 2026-10-06, playoff evening) held MLB sims for most of an hour, for a paper-only fee change. Lifting the drain let the tick run within 10 s.
- Why the drain never cleared: refresh-worker starts odds-refresh children back to back on a live slate (one child ran 7,632 s), so 'no child in flight' rarely holds in the evening.
- How to apply: budget the drain (e.g. <= 15 min total per evening slate), grep the worker log for `DRAIN_HOLD` while it is up, and prefer an overnight window or a natural restart for anything that is not urgent.

## 2026-10-06 — RULE: `lane-guard` sees only Edit/Write/MultiEdit/NotebookEdit, so a file written by a Bash-run script is UNGUARDED — and "BLOCKED" is a claim about one editing route, not about the file `[lane: lane-loans-are-enforceable]`

- **Measured in the hook itself:** `TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")` and `if payload.get("tool_name", "") not in TOOLS: return`. A PreToolUse hook on Bash could not do better in general — it cannot know what a script will write before it runs — so this is a boundary of the design, not a bug to patch.
- **Confirmed from the other side by a peer** (session 936c0a27, 2026-10-06): their edit to a file claimed by three lanes *was never refused*. They applied it with a Python script through Bash, lane-guard never saw it, and only `lane-postwrite-check` warned — which their recorded loan then answered. Verified independently: the commit touches `basketball_props_smart_sim.py` (35 lines) plus a 115-line new test, and `test_stale_snapshot_keeps_only_season_ending` exists.
- **I got this wrong in the direction that flatters the instrument.** Having measured that all three lanes were BLOCKED by the guard's predicate, I told the user they would "be BLOCKED the moment they edit". That holds only for the four tool names above. The deadlock was real for Edit/Write and invisible to the route this repo actually edits with — including every patch I applied today, each of which was a Write-to-scratchpad plus a Bash-run Python script, i.e. **never evaluated by lane-guard at all**.
- **How to apply.** `lane-postwrite-check` is the instrument that covers script edits, after the fact; `lane-guard` is the pre-write one and covers four tools. So: silence from lane-guard says nothing about a Bash edit, a claim is enforced only on the Edit/Write path, and compliance for script edits is DISCIPLINE plus a post-write warning. Same family as [[feedback-deploy-guard-misses-python-deploys]] — a guard hooked to tool names is blind to the interpreter.
- The loan fix (`76f4b879`) is still correct and still needed — it removes the invariant violation and unblocks the Edit/Write path — but it is **less load-bearing than I presented it**, because the dominant editing route never reaches the guard it repairs.

## 2026-10-07 — RULE: never stage an upstream copy of a ledger file on a branch that is BEHIND main `[lane: soccer-team-history-current-season]`

- **What happened:** `1b88656f` was meant to add ONE line to `lanes.md`. The recipe "`git checkout origin/main -- .syndicate/lanes.md`, edit, commit, `land`" was run on a worktree branch whose HEAD was behind `origin/main`. The commit's diff against its OWN parent therefore contained every upstream edit made since that parent; when upstream had meanwhile MOVED 26 lane blocks, the land's rebase re-applied the old positions and `main` got 26 duplicate blocks (+228 lines). Removed in `4ab0f4a8` (exactly parent + 1 line, 0 duplicates). The same mechanism produced two near-misses earlier the same session (a vs-origin numstat showing 6 and 11 deletions).
- **Why the usual check missed it:** `git diff --cached --numstat origin/main` read `1 0` — correct against origin at that instant. What lands is the diff against the commit's PARENT, rebased; a check against origin cannot see a stale parent.
- **Rule:** before staging an upstream copy, make HEAD == `origin/main` (`git rev-parse HEAD origin/main` equal; if not, land or `git merge --ff-only origin/main` first). After landing, read `git show --numstat <landed sha>` — it must equal the intended change. Gate on the LANDED commit, not on the pre-commit diff.

## 2026-10-07 -- A stopped, frozen scheduled run reads "succeeded" `[session af3cc595]`

- **Measured 2026-10-06:** four "Run now" dispatches froze on their first tool call (permission prompt, no child process). After `stop_session`, `list_task_runs` reported each as `status: succeeded`. None had executed a single command.
- **Rule:** a run's `status` says the session ended, not that the task did its job. Before believing a run, read its last events (`list_events`) or the artifact or ledger entry it was supposed to write. A run whose last event is a tool call with no result, and no matching process on the machine, is FROZEN, not slow.
- **Same session:** an LLM run's prose summary can contradict its own table ("beat pooled in all four sports" over a table where NFL lost). Relay the numbers, not the summary sentence.

## 2026-10-07 — FORBIDDEN: judging a 2026-27 squad list by what you "know" about who plays where `[lane soccer-roster-refresh]`
- **What happened:** the refreshed EPL roster newly dropped Romero, Watkins, Rodri, Martinelli and Vicario from the sim, and I called it a regression ("real, current regulars") before checking.
- **What was true:** none of them had a 2026-27 row in the league's stats file (5+ rounds in), and none was on any club in ESPN's current roster. Spurs' current list holds Robertson, Tonali and Marmoush. They had left, and it was the July roster that had been wrong.
- **How to apply:** a model's or a session's football knowledge predates the season being served. Before calling a squad change wrong, check the two sources the system itself trusts (the current-season stats file and the current roster) for that player, and say which one disagrees.
## 2026-10-07 -- OVERTURNED: "NFL's projection join takes `selected_date`, so the layer2 window must loop it per date" `[lane layer2-coverage-identity-merge]`
- **The belief** was a code comment in `_attach_projections_over_window`: "ncaaf and nfl also span days and their joins take `selected_date` alone, so they genuinely need this loop."
- **What was true:** `load_nfl_prop_projections` ignores the date (it resolves the current season/week), and `load_nfl_game_projections` builds a season-wide index. All 7 passes were identical, so every NFL count in the shortlist was 7x: games_in_index 2247 = 321 x 7. Identity fields were summed into week 35 and season 14182, and that summed field was the one the 2026-09-29 `3f28cdb7` deploy was verified on.
- **Rule:** before a sport goes in or out of `_SELF_WINDOWING_PROJECTION_SPORTS`, read what its loaders do with the date; don't infer it from the call signature. A field named `artifact_*`, or anything that identifies WHICH artifact answered, must never pass through a numeric sum.

## 2026-10-07 -- AGREEING WITH AN EXISTING COMPONENT IS NOT VERIFICATION; IT INHERITS THAT COMPONENT'S DEFECTS (lane wnba-slate-and-out-props)

- **Belief overturned:** I shipped a props OUT filter (ea5a8877) and called it verified because, over production's real 10-07 inputs, it dropped *exactly* the players the SmartSim dropped (Gray, Loyd, Talbot). It reused the sim's own exclusion helper, so of course it agreed -- including on the sim's bug: the injury feed is DAILY SNAPSHOTS and the helper kept each player's latest row, so Loyd and Talbot, off the 10-06 report, stayed 'OUT'. My own grep had shown their last rows were 10-04/10-05; I read past it. A peer lane caught it; ea5a8877 was reverted (39412c42) and the sim fixed (e3f2c3c0).
- **Rule:** when a new check is validated by agreement with an existing one, the agreement measures shared inputs, not correctness. Check the disagreements' complement too: for each excluded item, read the raw source row that justifies it *as of the date in question*.

## 2026-10-07 -- RULE: `deploy_claim.py --force` acts on whoever holds the claim AT THAT INSTANT; re-read `status` immediately before forcing `[lane web-restart-healthz, session 46e09dbb]`
- Believed: the refresh-worker claim I forced at ~00:42Z belonged to layer2-coverage-identity-merge, because status said so when I read it ~26 min earlier and I had messaged that session.
- Actually: that claim was released at 00:38-00:39Z and lane wnba-slate-and-out-props' poller re-acquired it at 00:39:00Z. My force displaced a different, live holder, and my deploys entry and message named the wrong one. No harm only because that lane was still waiting on web.
- How to apply: `status` in the SAME command as `acquire --force`, and name the holder from that reading in deploys.md. Pollers re-acquire within seconds of a release, so a claim reading older than a minute says nothing about who you are about to displace.

## 2026-10-07 — RULE (user decision): restart the refresh-worker ONLY right after a board save — never mid-build `[lane web-restart-healthz, session 46e09dbb; user: "yes add the restart rule"]`
- **Why:** every refresh-worker restart discards the board build in flight, and the board serves nothing newer until the NEXT build saves. Measured on the fleet: 10-06 19:42 CT a full `down` killed a build at `layer2_shortlist_build`; 10-07 09:44 CT (mine) discarded one; 10-07 ~10:10 CT a refresh-worker exit (code 0, `exited code=0 after 1588s`) landed 3 min after a 22-min build returned (`BOARD_BUILD_TIMING wall_s=1306.2`, 15:07:35Z) and BEFORE `STATE_PERSIST_BEGIN` -- no board save from 09:26 to ~10:40 CT. The first build after a restart is also the slowest (cold caches; 1,306 s vs ~5 min warm that morning).
- **How to apply:**
  - Wait for a FRESH `^\S+ \[intelligence_state\] STATE_PERSIST_BEGIN` line (anchor the prefix -- ALL_PROCESS_MEMORY JSON lines contain the token), then restart within ~60 s, before the next `BUILD_SPAN_ENTER stage=build_intelligence_overview`.
  - `check_deploy_safety.py`'s "Board build IN FLIGHT" is BLOCKING for a refresh-worker restart, not advisory. Web reloads (`local_production.py reload-web`, HUP) do not touch the build and are exempt.
  - A fleet fast-forward is not a restart, but it makes the next restart load everything up to HEAD: diff HEAD..target for runtime paths and ff only as far as the commit you are loading (10-07 09:45 CT: a peer ff 86 s after mine pulled in NHL/soccer commits that lane had not announced).
  - Record every restart in deploys.md -- the 10:10 one was not, and had to be traced from transcripts.

## 2026-10-07 — RULE: a PHANTOM claim outlives its session and can block a fix nobody ever claimed the right to block `[lane: lane-section-scoped-claims]`

- Asked to request a loan on `scripts/check_lane_invariants.py` from OPEN lane `live-gameline-game-identity`. **Both halves of the premise are false, and measuring beat asking.**
- **There is nobody to ask:** that session's transcript (`3692ff18…`) was last written **2026-09-27 00:11Z — 10.6 days before**. An OPEN lane header says nothing about whether its owner still exists.
- **Nobody ever claimed the checker.** The ONLY path `_paths_in` extracts from that lane's whole Files declaration is `check_lane_invariants.py`, and it comes out of this sentence: *"the shared board-enrichment module **[claim DROPPED 2026-09-23: it was contested between this lane and `mlb-doubleheader-e2e`, BOTH MINE, which `check_lane_invariants.py` flagged as one of two contested files…"*. The lane was DROPPING a claim and named the tool that flagged it. The intended claim — "the shared board-enrichment module" — is not path-shaped and extracts nothing, so the lane ended up holding ONLY a file it merely mentioned.
- **Backticks do NOT protect against this, and I nearly assumed they would.** `_mask_backticked` exists for the OPPOSITE job: stopping `_claimable_prefix` cutting at a marker word that is part of a FILENAME (`archive_released_lanes.py` → `scripts/archive`). It is used by `_is_disclaimer` and `_claimable_prefix`, never by `_paths_in`. The ledger's backtick convention is why a prose mention is path-shaped in the first place.
- **How to apply.** Before asking any lane for anything: check its owner's transcript mtime, and check WHICH TEXT produces the claim (`_files_segments` + `_paths_in` on that lane alone). A claim that comes out of a sentence about a path is a phantom, and the documented release is the checker's own line — "delete the path, or say it naming NO path". Adding `claim dropped` to the disclaimer markers would fix this class, but inherits the PREFIX-cut hazard ([[feedback-files-line-disclaimer-prefix-cut]]): every real path listed after the phrase on that line would be dropped too, so it is a decision rather than a tidy-up.
- **Third instance today of one root cause:** the lane model's text parsing has no representation for a loan (deadlocked 3 lanes), none for a section (deadlocked 2), and cannot tell a claim from a mention (this). The first two were fixable in the parser; this one cannot be fixed there without trading a phantom claim for silently dropped real ones.

## 2026-10-07 -- A ledger line saying an action happened can be written BEFORE the action, and the action can then fail `[session af3cc595]`

- **Measured:** a scheduled reading appended "Re-armed for 2026-10-10T15:00Z" to `deploys.md`, pushed it (`32d80245`), then froze on the `update_scheduled_task` approval prompt. The task was left DISABLED with no next run. The ledger said the opposite of the system.
- **Rule:** when a prompt (or you) records a follow-up action in the ledger, do the action first, read it back (`list_scheduled_tasks` `nextRunAt`, a commit on origin/main, a file on disk), and only then write that it happened. When reading someone else's "re-armed / scheduled / deployed" line, check the system, not the line.

## 2026-10-07 -- Parallel harness processes that each (re)generate a SHARED input file race, and the failure looks like speed `[session e0a3e383]`

- **Measured:** 7 parallel sweep processes each called `hist_props_csv(d)`, which rewrites
  `asof/props_odds_hist/<d>.csv`. Two points finished 6 dates in under an hour, while the others took ~10 min per date.
  They had simulated **0 games on every date**: truncated snapshots, so SmartSim had no players. One crashed in
  `copy2`. Nothing errored loudly: the harness wrote 0-game files that would have read as results.
- **Rule:** generate shared inputs ONCE, before fanning out, and have workers only read them. A run that produced
  nothing must write no output, not an empty file. A point that runs faster than its peers is a suspect, not a win:
  compare output counts with the baseline before reading any statistic.

## 2026-10-07 — FORBIDDEN merge=union WAS LIVE FOR 5 WEEKS THROUGH UNTRACKED CONFIG: `.git/config` `core.attributesFile` pointed at a session scratchpad file applying `.syndicate/*.md merge=union` to every session `[lane wnba-props-out-player-leak, session 4d5b3bd3]`

- **What was true:** since 2026-08-31 14:40 CT, the primary repo's LOCAL config had `core.attributesFile = <session 5611932c scratchpad>/push-wt/.git-union-attrs`. That 28-byte file holds `.syndicate/*.md merge=union`.
  - Local config is shared by every worktree, so every session's rebase union-merged lanes.md, deploys.md, learnings.md and the rest.
  - session_isolation_protocol.md forbids exactly this, twice: a union merge cannot carry a deliberate deletion, so a removed block comes back on the next rebase.
- **How it hid:**
  - The tracked `.gitattributes` has no merge line, so `git grep` and the repo history show nothing.
  - Only `git check-attr merge -- .syndicate/lanes.md` (`merge: union`) and `git config --show-origin --get core.attributesFile` reveal it.
  - The pointer lived in another session's scratchpad, outside every tree any guard reads.
- **Cost, measured on origin/main:** 81 commits on lanes.md since 08-31 mention "duplicate" (a message match, not proof of cause for each). This morning two lanes were duplicated by concurrent rebases and needed three cleanup commits in about 10 minutes (0fd47526, 4352357f, 946a2231). Meanwhile the ledger guard refused every ledger commit repo-wide.
- **My own error, corrected by the peer:** I attributed the 10:37 duplicate to 7fc5dd79 (lane layer2-out-gate-reach) from the commit that first showed it. Its owner's trace was right: 7fc5dd79 carried one copy, and a later rebase (e406452c) doubled it through the union merge. A commit that SHOWS a duplicate is not the commit that MADE it, while union merging is on.
- **Fixed 2026-10-07 ~11:10 CT (user: "yes, unset it and record the learning"):** `git config --local --unset core.attributesFile`. Afterwards `git config --get core.attributesFile` returns nothing (rc 1), and `git check-attr merge` reports `unspecified` for lanes.md/deploys.md in the primary tree and in a session worktree.
- **How to apply:**
  - When ledger blocks duplicate, or deletions "come back", run `git check-attr merge -- .syndicate/lanes.md` before blaming a session. Anything but `unspecified` is the cause.
  - Never point repo-level config (`core.attributesFile`, `core.hooksPath`, merge drivers) at a session scratchpad: it outlives the session, applies to all sessions, and is invisible to every tracked-file check.
  - A conflict in a ledger file is meant to surface at `land` and be rebuilt on upstream (the ledger-append recipe), not be made quiet.

## 2026-10-07 -- A GATE TESTED BY FEEDING ROWS STRAIGHT IN IS NOT TESTED; TEST THROUGH THE REBUILD PRODUCTION USES (lane layer2-out-gate-reach)

- **Belief overturned:** f9adcdd8's Layer 2 OUT-player gate shipped with 4 passing tests and a served counter, and I recorded it as 'mechanism verified'. All four tests handed rows directly to select_shortlist. Production does not: build_layer2_rows rebuilds every candidate from _IDENTITY_FIELDS plus an explicit field list, and the upstream flag (`player_availability`) was not on it -- the same shape #270 recorded for `projection`. The served counter reading 0 was read as 'no OUT player quoted' when the frame could not have been non-null for a second reason. Caught when Layer 1 fired on a real row (Gray, rows=9) and Layer 2 still read 0 on a post-flag build.
- **Rule:** a gate on a field stamped upstream needs one test that starts from the upstream row and runs the real transformation chain to the gate (here grid row -> build_layer2_rows -> select_shortlist), and that test must fail with the carry removed. A counter that reads 0 is evidence only after a replay of real input shows it can read non-zero.

## 2026-10-07 -- A lever applied with `hasattr`/`setattr` onto a substituted config is a silent no-op `[session e0a3e383]`

- **Measured:** the sweep added fields to the vendor `EventSimConfig`, but Syndicate passes its own frozen
  `EventSimConfigLocal`, which lacks them. `hasattr` skipped 5 of 7 sweep points silently (they ran the baseline, with
  clean logs), and the vendor engine's `getattr(cfg, name, default)` hid it a second time.
  - Only the 2 points whose field already existed failed loudly, and only because the dataclass is frozen.
- **Rule:**
  - Prove a lever at the ENGINE boundary (count the calls whose cfg carries the value), not at the place you set it.
  - Reject unknown lever names against the engine's own fields.
  - Engine-level byte-identity and reachability tests do not prove that the production wrapper passes the lever
    through. Run one through the real call path.

## 2026-10-07 — RULE (user decision): research and backtest jobs launch at LOW priority; production shares this machine `[lane web-restart-healthz, session 46e09dbb; user: "yes ask the research sessions to launch low priority"]`
- **Why:** WSL `nice` is invisible to Windows, and Windows sees the whole fleet as one Normal process (`vmmemwsl`). Measured 10-06/10-07: host CPU 100%, the VM got 2-3.6 of 12 cores, and the board's shortlist step took 1,924 s (vs ~120-230 s with cores free) -- 1.5 h with no board save. Inside the VM, research at nice 0 (7 x `basketball_scenario_rates.py sim`, ~5 cores) competed equally with refresh-worker.
- **How to apply:** WSL: `nice -n 19 <cmd>` (multiprocessing children inherit). Windows: `start /low /b python ...`, or set `.PriorityClass = 'Idle'` right after launch (children inherit). An operator who finds a running job at normal priority may lower it (`renice -n 19 -p <pid>` / `PriorityClass = 'Idle'`); it keeps running. Unattended scheduled tasks cannot be messaged -- put the prefix in the task prompt itself.

## 2026-10-07 -- OVERTURNED: "check_deploy_safety's `Board build idle` means a refresh-worker restart loses nothing" `[lane layer2-coverage-games-in-sum, session 5d9a4d65]`
- **The belief:** my scoped gate restarted refresh-worker on "Board build idle (last completed 241 log lines ago)" + no live children.
- **What was true:** that line is true of a build's RETURN. A 22-min build had returned at 15:07:35Z and not yet persisted; the TERM at 15:10:25Z discarded it, and no board save landed 9:26 to ~10:40 AM CT (traced by lane web-restart-healthz). A fresh child also spawned in the ~4 s between gate read and TERM.
- **Rule:** gate a refresh-worker restart on the persist line, per the 2026-10-07 restart-after-save rule above (STATE_PERSIST_BEGIN). Treat `Board build idle` as necessary, not sufficient, until check_deploy_safety itself requires the save.

## 2026-10-07 — `MSYS_NO_PATHCONV=1` ALSO BLOCKS `git -C /c/...`: the "fix" for rev:path mangling made a live worktree read as deleted `[session 4d5b3bd3]`

- **What happened:** `MSYS_NO_PATHCONV=1 git -C /c/tmp/syndicate-sessions/<wt> show origin/main:...` failed with `fatal: cannot change to '/c/tmp/...': No such file or directory`. I took it as the worktree being deleted, and spent three checks on a non-event. The directory was intact and the branch fully landed.
- **Why:** Windows git does not understand `/c/...`. Git Bash normally converts it, and `MSYS_NO_PATHCONV=1` (the standing fix for `rev:path` arguments, see memory "Git Bash mangles path args") turns that conversion off for EVERY argument, `-C` included.
- **How to apply:**
  - With `MSYS_NO_PATHCONV=1`, give `-C` a Windows-form path (`C:/tmp/...`), or `cd` first.
  - Before concluding a path is gone, check it without git (`ls -d`). A git error about a path is evidence about git's view of the path, not the filesystem.

## 2026-10-07 — FORBIDDEN: using an artifact's `generated_at` to prove a build read a new input `[lane soccer-roster-refresh]`
- **Believed:** the la_liga build stamped 00:20:20Z ran on the refreshed roster written 00:16:51Z, because it was "generated after" the write. Recorded as evidence in deploys.md 2026-10-06 22:38:35Z.
- **True:** it read the JULY roster. Its departed count, 179, is the July number; every later build reads 188. `generated_at` is stamped at the END of a build, and the inputs were read before 00:16:51Z.
- **How to apply:** prove provenance with a field only the new input can produce (here the dropped count, predicted beforehand), or compare the input's mtime with the build's START. Never use the end stamp.

## 2026-10-07 — FORBIDDEN: a readiness/presence check that decides what counts by "is the path inside the git checkout" `[session 13ac7622, lane intelligence-evidence-coverage]`
- **What happened:** `_advanced_readiness_summary` counted only `inside_repo` rows as required. Production data lives under `SYNDICATE_DATA_ROOT` (Render disk, now the fleet's `~/syndicate-prod/data`), so every real input was excluded and `ready = bool(rows) and not missing` was TRUE with nothing present: NCAAF read `ready` 9/9 with 0/27 inputs (fleet 2026-10-07). The same layer printed the metric NAMES of each input file as "Advanced drivers in play" without reading one value (77/77 recs had empty `advanced_signals`).
- **Rule:** decide REQUIRED by what the consumer needs, and measure EXISTS where production reads it (the data root), never by repo membership. A gate whose required set can be empty must read not-ready, not ready. An explanation may name a metric only next to a value it read.
- **Evidence:** `ced2618f`; `[intelligence-season-evidence]` in `state_board.md`.

## 2026-10-07 -- Unattended scheduled runs cannot show a permission prompt: pre-allow the exact command, or the run freezes silently `[session af3cc595]`

- **Measured:** over 10-06..10-07 every routine whose next command was not already approved froze on its first such call, nine runs in all. The event view showed "(called Bash/PowerShell/Write)" with no result, no process existed on the machine, and the user saw NO prompt to approve. A stopped one then reads `succeeded`. Adding EXACT allow rules to the project's `.claude/settings.local.json` fixed it, confirmed on 4 routines (census, gameline, H24, optimizer).
- **Rule:** write a routine's commands as fixed shapes (one command per call, no `&&`/`;`/pipes, a fixed script path rather than inline logic), add each shape as an allow rule (both `Bash(...)` and `PowerShell(...)` when either tool may run it), and tell the prompt to use the Grep/Read TOOLS for searching and reading. Then test with a real "Run now" and check the run's process list, not its status.
- **Also measured:** a Bash-tool command with Windows backslash paths runs with the backslashes STRIPPED (`C:\tmp\x` -> `C:tmpx`, a relative path) and no error. In routine prompts write every path as `C:/...`. Git Bash also rewrites `/mnt/c/...` arguments (`wsl ... bash /mnt/c/...` exits 127), so give WSL commands to the PowerShell tool.

## 2026-10-07 — FORBIDDEN: `xargs -0 -a /proc/<pid>/environ env -i <cmd>` to borrow a role's env -- xargs APPENDS the items as argv `[session 13ac7622, lane intelligence-evidence-coverage]`
- **What happened:** to run `check_deploy_safety.py` "with the worker's env" I wrote `xargs -0 -a /proc/$w/environ env -i python scripts/check_deploy_safety.py --base-url ...`. xargs puts its input AFTER the given command, so every `KEY=VALUE` became an ARGUMENT to the script; argparse rejected them and printed them -- live Kalshi/Polymarket private keys landed in the session transcript (user rotating them). The same wrapper had looked fine twice earlier only because those scripts ignored argv.
- **Rule:** load a role's env in Python (`dict` from `/proc/<pid>/environ`) and pass it as `env=` to `subprocess.run`, never via argv; print the child's output only through an ALLOWLIST of expected lines plus a secret-shaped-line filter (`C:\tmp\iec_safety.py` is the working shape). A tool run "with production env" is a secret-handling operation even when the tool is read-only.

## 2026-10-07 — A diagnostic watcher is production load: mine pulled 90 MB from web every 3.5 min for 1.6 h while the user's Ask timed out `[session 13ac7622, lane intelligence-evidence-coverage]`
- **What happened:** to wait for a new build I polled `/api/intelligence/status` every 180 s. That endpoint returns ~90 MB and took 25-44 s per call on a 2-worker web; the access log shows the calls exactly while I was diagnosing "web-worker contention" behind the Ask rail's timeouts.
- **Rule:** before scheduling a poll against web, measure the endpoint's bytes and seconds ONCE; prefer a log line or a tiny route (here the worker log's timestamped `STATE_PERSIST_BEGIN`, read locally, costs nothing). When diagnosing contention, list your OWN background jobs first.

## 2026-10-07 -- RULE: a line-ending sniff of a shared ledger file must not be `"\r\n" in text` `[lane: soccer-team-history-current-season]`

- lanes.md carried exactly ONE CRLF line among 2,351 LF lines. A helper that set `crlf = "\r\n" in text` and re-joined with CRLF rewrote every line (a 2351/2351 numstat for a one-line edit); caught before it reached main. Edit ledger files byte-exactly on the `git show origin/main:<path>` blob (replace bytes, never split/re-join with a guessed ending), and read `git diff --numstat` -- it must equal the intended change.

## 2026-10-07 -- RULE: `check_deploy_safety --drain` cannot produce a restart window on the local fleet `[lane: soccer-team-history-current-season]`

- Measured 15:25-15:56Z: the drain stops new BOARD builds, so the board save that the user's rule ("restart the refresh-worker only right after a save") waits for can never come while it is in force; and it does not hold the live-odds-worker, whose odds jobs run continuously, so its CLEAR never arrives either. Use `check_deploy_safety` (idle = a LOOP_ITERATION after STATE_PERSIST_BEGIN, since e28aeafb) WITHOUT a drain as the restart gate, with the three claims held.

## 2026-10-07 -- EXONERATED: possession alternation, quarter environment SD and possession-count jitter are not why the NBA sim's margins are too wide `[session e0a3e383, lane basketball-scenario-calibration]`

- **Pre-registered sweep** (12 FIT dates, 87 games, levers verified at the engine boundary):
  - within-game margin SD 18.10 at baseline;
  - best 17.51 with alternation = 1.0;
  - env_sd_scale and possessions_jitter null down to 0.
  - Real-game total dispersion is ~14.
- **Do not re-tune these three expecting to close the gap.** The excess is elsewhere (shot-level or lineup
  randomness). Details: findings_2026-10-06_basketball_scenario_calibration.md, Phase 2 #1 RESULT.

### 2026-10-07 — Bisect a ledger regression commit-by-commit before naming ANY culprit, yourself included `[lane football-sim-player-attribution, session 20aa7f5b]`
- What we believed: "my lane-open commit ec9961dc wrote a DUPLICATE football-sim-player-attribution block" -- I put that in the dedupe commit message (0fd47526) and in this postmortem's own incident line, because I had just rebuilt lanes.md byte-wise to dodge a line-ending change and assumed my insert had doubled.
- What was actually true: ec9961dc carried exactly ONE block. The duplicate first appears in 7fc5dd79 (10:37), reappears in 7d46e1f3 right after my dedupe, and is the union-merge defect already recorded above (2026-10-07 FORBIDDEN merge=union via core.attributesFile) -- a rebase with `merge=union` resurrects deleted or concurrent blocks. Neither my rebuild nor 7fc5dd79's author wrote it.
- How we found out: the postmortem's step 1 ("reconstruct from evidence, not memory") -- a 5-second loop `for c in $(git log --format=%h ec9961dc~1..origin/main -- .syndicate/lanes.md); do git show $c:.syndicate/lanes.md | grep -c '^### <slug>'; done` printed blocks=1 at ec9961dc and blocks=2 first at 7fc5dd79.
- The rule going forward: before attributing a ledger regression (duplicate block, dropped section, lost claim) to any commit, print the invariant's value at EVERY commit that touched the file since it was last good, and name the FIRST commit where it flips -- then say whether that commit's own diff wrote it or a merge/rebase did. Self-blame is a hypothesis like any other; a confident wrong attribution in a commit message is permanent and misleads the next reader exactly like blaming a peer (cf. the peer's 7fc5dd79 correction above).
- Cost: one false self-attribution written into git history (0fd47526's message), one wrong incident framing passed to /postmortem, ~10 min of a peer's time verifying it.
- **Check, not just prose (proposed):** when `ledger_invariants.py` refuses a commit for a broken invariant, have it print the FIRST origin/main commit at which that invariant broke (the loop above, bounded to the last ~20 commits touching the file) and whether that commit's diff or its merge parent introduced it. The guard already computes the invariant; adding the bisect turns "who did this?" from a guess into a printed fact at the moment someone is most likely to guess.

## 2026-10-07 -- To diagnose a frozen scheduled run, read its transcript .jsonl, not the event view `[session af3cc595]`

- **Measured:** the app's event view for a scheduled run shows "(called Bash)" with no arguments, so for two days every freeze diagnosis here was a guess (and the first two guesses were wrong). The run's own transcript, `~/.claude/projects/<project>/<uuid>.jsonl`, records every `tool_use` input and every `tool_result`. Find it as the newest `.jsonl` whose mtime matches the run's `last_activity_at` and that contains a phrase unique to the task prompt (NOT one this session also typed: the marker matched my own transcript once). A `tool_use` with no matching `tool_result` is the frozen call, exactly.
- **What it found, 4 runs, 4 different freezes:** an improvised `Test-Path ...; Get-Date ...` compound; Git Bash expanding `~` in a `wsl ... ~/...` command (exit 127); a Read of a backgrounded command's temp output file (a Bash call > 120 s goes to the background); `...; echo rc=$?`. None of these was a prescribed command: every prescribed one matched its rule. Models improvise status checks, clocks and exit-code echoes. Prescribe those too, and keep long work in the foreground with an explicit `timeout`.

- **2026-10-07 (web-restart-healthz): an exit guard keyed on SIGNAL deaths misses a worker that traps SIGTERM.** The refresh-worker exits 0 on TERM (`exited code=0 after 17334s`, a claimed restart), so 88c532cd's signal-only check would have recorded none of the restarts it was written for. Record ANY exit of a supervised role the supervisor did not cause (07c0c683). Test the guard against the real exit path, not the assumed one.

### 2026-10-08 — A dry run passes only when its NUMBERS are plausible, not when it completes `[lane football-scenario-calibration, session 20aa7f5b]`
- What we believed: the NCAAF live-replay harness was validated -- its 2024 dry run ran end to end, so the one-time 2025 live read went ahead (and printed "LIVE GATES PASS").
- What was actually true: the harness fed RAW SP+/PPA components to `ncaaf/live_resim.resim_live_game`, which expects `sp_offense_defense_rating`'s centred, scaled, defense-NEGATED engine ratings. Production's own live errors in that dry run were margin 23.0 / total 33.6 pts (NFL's: 7.2 / 7.5); projections included Q1 totals of 114 and a home margin of -99.7. Both arms were equally wrong, so the deltas looked orderly and the gates "passed".
- How we found out: reporting the 2025 result, the ABSOLUTE production error (35.6 pts on totals) was implausible next to NFL's; printing three replayed games showed the absurd projections.
- The rule going forward: a dry run is accepted only after its baseline arm's absolute numbers are checked against a known-sane reference (another sport, the pregame error, the book). Paired deltas between two arms fed the same broken input look perfectly normal -- they cannot reveal an input defect. Spending a held-out read on a dry run that was only checked for completion is FORBIDDEN.
- Cost: the one-time NCAAF 2025 live read was spent on an invalid harness (pregame 2025 was valid and is reported); a corrected re-run is now informational only.
- **Check, not just prose:** `football_scenario_replay.grade` now voids every gate when production's own live total abs error exceeds 20 pts (sane NFL/NCAAF values are ~7-8). The same pattern -- a plausibility band on the BASELINE arm, not the delta -- belongs in any paired harness before a held-out read.


## 2026-10-08 -- RECURRENCE of 10-03 "pin the deploy to the HEAD you enumerated" `[lane nhl-pk-units, session dd07cae9]`

- I read the ride-alongs 27424623..50910fb3, then ran `git merge --ff-only github/main` on the fleet; main had moved to fdf487f6 in the 20 minutes between, so one commit (prop_evidence read cache, off by default, inert without a restart) rode along unread and was only read after the fact.
- **How to apply:** fast-forward the fleet to the exact SHA you enumerated (`git merge --ff-only <sha>`), never to a remote branch name; re-list ride-alongs if you change the target.

## 2026-10-08 -- A guard that reads its BLOCK from one ledger view must read its EXEMPTIONS from the same view `[lanes lane-guard-loan-main-text, loan-aware-warn-hooks, session 74f50e68]`

- What we believed: lane `lane-guard-main-claims` (2026-09-17) had made lane-guard read origin/main + local additions instead of the stale primary `lanes.md`.
- What was actually true: only the CLAIMS moved. The loan and disjoint-section exemptions added later re-parsed the primary copy, so a loan recorded on main (55547ac5) was blocked because the stale copy lacked the borrower's block. The two warning hooks (`scope-guard`, `lane-postwrite-check`) did not consult loans at all.
- How we found out: a user-approved loan was blocked on 2026-10-07 ~16:35 CT and the session wrote around the guard; a peer then reported the warning hooks still firing on the permitted write.
- The rule going forward: every reader of `lanes.md` that feeds ONE decision (claims, loans, sections, holders) goes through `lane_claims_source` (`effective_claims` / `effective_entries` / `honoured_loan`). A new exemption that takes the raw `text` is the same bug again.
- Also: `scripts/lane_open.py` rewrites ALL line endings in `lanes.md`; check `git diff --numstat` shows 0 deletions after it, or insert the block byte-exactly.

## 2026-10-08 -- MCP tools are NOT honoured by the allow list in unattended scheduled runs; a run cannot re-arm itself `[session af3cc595]`

- **Measured:** `mcp__scheduled-tasks__update_scheduled_task` IS in `.claude/settings.local.json`'s allow list, yet an unattended run's call to it hung > 4 min with no effect (the task's SKILL.md was unchanged afterwards). In the same run every Bash/PowerShell call matching a rule ran with no prompt. A 2026-10-07 run had done the same thing: wrote "Re-armed for 2026-10-10" to `deploys.md`, then froze on this call, leaving the task disabled.
- **Rule:** routine prompts must not call scheduled-tasks tools (update/list/run). A run REPORTS the next fire time and its new carried-forward numbers in its final message; an attended session applies them, then reads the schedule back (`nextRunAt`). After every scheduled reading, check that its re-arm actually happened.

## 2026-10-08 -- A RECYCLE'S STATED CAUSE IS A BELIEF, NOT A MEASUREMENT: live-odds-worker's 6 h restart "resets page cache"; the growth it resets is anonymous heap (lane live-odds-worker-rss-drift)

- **What was believed:** `run_live_odds_refresh_worker.py:1085-1094` (2026-07-15) says the worker's climb (~416 -> ~989 MB) is page cache from routine file I/O, and recycles every 6 h to reset it. State's subject key still reads `live-odds-worker-memory-is-page-cache`.
- **What was measured (fleet, 10-04..10-08):** the PROCESS's post-GC/post-`malloc_trim` floor rises +10..+95 MB/h within each boot. RssAnon is 89% of RSS, RssFile 11%, shmem 0. Page cache is not in a process's RSS at all; a cgroup reading (Render) counts both, which is how the two got conflated.
- **Rule:** when a mitigation's comment names a cause, check that the cause is in the quantity being mitigated (RSS vs cgroup `memory.current` vs `anon`) before trusting it, and before "the recycle handles it" closes the question. Here the recycle WORKS (median 27 s tick cost, no cross-day leak); it just works on something other than what it says.

## 2026-10-08 -- RULE: a fleet log count must be anchored on the emitter's line prefix; ALL_PROCESS_MEMORY lines carry other lines' strings `[lane nba-live-lens-oversize-write, session d48f3a34]`
- A verification watcher counted `/KEYVALUE_WRITE_REJECTED/ && /nba_live_lens/` after a fix and read **7**, which looked like a failed deploy. All 7 were `ALL_PROCESS_MEMORY` JSON lines (live-odds-worker) that contain both strings; anchored on `^<ts> [refresh_state_store] KEYVALUE_WRITE_REJECTED key=.../live/nba_live_lens.json` the count was **0** (vs 19 before). Anchor every count on the emitting module's prefix and bound the window at BOTH ends.

## 2026-10-08 - RULE: removing one bias from a calibrated model can EXPOSE another it was cancelling -- score a convention fix on real quotes before shipping it `[lane nfl-passing-yards-prop-coin, session f628c245]`
- **What I believed:** passing_attempts counting sacks (+2.42/QB-game) was a pure defect, so fixing it and re-fitting CV, k and blend by the standard would improve the market.
- **What was true:** every in-pipeline check passed (official 561/561, CV method reproduced exactly, k and blend improved out of sample on the synthetic line ladder), yet on the identical 3,774 real quotes graded officially LL moved +0.0018 [-0.018, +0.021] while mean P(over) fell 0.517 -> 0.419 against 0.498: the inflation had been cancelling the log-normal blend's under-lean, and a ladder of lines centred on the MEAN cannot see a lean that only shows at lines set at the MEDIAN.
- **Rule:** a convention or input fix to a fitted model is graded on REAL quoted lines, same rows before and after, mean P(over) beside the over-rate, before it ships -- the calibrators' own OOS improvement is necessary, not sufficient. Also: a diagnostic resolver call without game teams (`resolve_player_id_with_prior`) is not the board's path; I nearly filed a production collision from it.

## 2026-10-08 -- A record cap that keeps a size BOUNDED can still be silent data loss; read what the trim drops, not just the size it holds `[lane execution-ledger-keyvalue-growth, session a9190ad7]`
- **What I was handed:** the execution ledger grows ~0.85 MB/day toward the 8 MB keyvalue cap, so it would be refused around 10-10 (a linear extrapolation of the total).
- **What was true:** the 5,000-row cap held it at ~6.7 MB (`SIZE_WARNING ... BOUNDED` said so on every write). The real event was the cap FIRING, ~10-09 03:00Z: it would have dropped ~600 paper rows a day permanently while six readers treated the document as the whole history. The guard line read healthy because it measured size, which was never the failure.
- **Rule:** before projecting a capped store, find the cap and read what crossing it DOES to the rows. A bounded accumulator that drops on overflow needs an archive, and its full-history readers must be switched to it (`execution_ledger.full_history_orders()`).

## 2026-10-08 -- RULE: prove a browser-bound JSON blob parses IN A BROWSER (or with a strict parser) -- Python's `json.loads` accepted it twice while every browser rejected it `[lane layer2-board-ui-redesign, session d4409ac4]`
- **What happened:** the home embed (`<script id="initial-intelligence-response">`) was checked server-side with `json.loads` and "parsed". In the browser it failed twice over: HTML-escaped a second time (`&#34;`, since ebd17ee2) and, once that was fixed, 21 bare `NaN` tokens, which Python accepts and `JSON.parse` does not. The page's try/catch turned the embed into `{}` and silently waited for the API, so the board looked fine and the 68 MB embed did nothing for 16 days.
- **Rule:** test what the CONSUMER parses, with the consumer's parser: `json.loads(text, parse_constant=<raise>)` at minimum, or a headless browser with the follow-up API blocked. A fallback path that hides a failed primary path must be tested with the fallback disabled.

## 2026-10-08 -- RULE: a field's NAME is a contract; check every READER before writing a value into it -- `projection["side"]` held the lean in three producers and the frame in every consumer `[lane layer2-board-ui-redesign, session d4409ac4]`
- **What happened:** NHL/NBA/WNBA prop producers wrote `"over" if mean > line else "under"` into `projection["side"]`; every reader (`_model_prob_for_side`, `_model_edge_for`, `board_enrichment`, the Ask adapter) treats it as the side `model_prob_over` describes and complemented the probability. 367 of 597 NHL rows showed P(under) on their OVER row, 328 tagged "sim agrees", the board's #1 row among them. The edge was inverted in the same direction, so probability and edge agreed and no consistency check fired.
- **Rule:** grep every reader of a shared field before writing to it. For count props, the Markov check `P(X >= k) <= mean / k` is a cheap invariant that catches a flipped side the edge cannot.

## 2026-10-08 -- The production prop-evidence readers do NOT cut history at the slate date; any backtest through them leaks the outcome `[lane intelligence-evidence-coverage]`
- **Belief overturned:** "the providers read only games before the slate" -- I wrote it for basketball from the `as_of` argument's name. `_box_games(sport, name, as_of)` never filters by date: it reads every box row on disk. NFL `_nfl_usage` reads every week of the season; NCAAF `_ncaaf_box` every week in the snapshot; NHL `_game_log` cuts at the GAME's kickoff, so a sighting days earlier sees the games in between; soccer cuts at the match date, not the sighting.
- **Why it hid:** live, the game has not been played, so every one of these is correct in production. Only a replay over past dates sees the future rows -- and the result looks like signal.
- **How it was caught:** a per-row assertion "newest game used < sighting date" refused 2,269 / 2,269 WNBA rows and ~4,400 NHL rows on the first H3 pass. Without it the test would have scored on leaked outcomes.
- **Rule:** a backtest that calls a production evidence/feature reader must (a) cut every history list at the decision time itself and (b) assert per row that the newest input predates it. Never infer point-in-time from a parameter name.

## 2026-10-08 -- A FLEET READING TAKEN THROUGH `wsl` FROM A WORKTREE CWD CAN BE ABOUT THE WORKTREE: `git` in `bash -c 'cd ~/Syndicate && git ...'` answered for my Windows worktree (lane down-reaps-odds-jobs)

- **What happened:** from Git Bash with cwd = `C:\tmp\syndicate-sessions\<lane>`, `wsl -d Ubuntu-24.04 -- bash -c 'cd /home/amyn/Syndicate && git merge-base --is-ancestor <sha> HEAD'` printed `fatal: not a git repository: /mnt/c/tmp/syndicate-sessions/<lane>/C:/.../.git/worktrees/<lane>` and my `|| echo no` turned it into "**fleet lacks the fix**". The truth, read via PowerShell `wsl --cd /home/amyn/Syndicate` from `C:\`, was `1884c0e5`, containing it. `env -u GIT_DIR ...` did not help, and `env | grep ^GIT_` was 0 on the good path.
- **Rule:** read the fleet checkout with `wsl -d Ubuntu-24.04 --cd /home/amyn/Syndicate -- ...` from a neutral cwd (PowerShell, `Set-Location C:\`), or `git -C /home/amyn/Syndicate`, and NEVER fold a git error into a yes/no with `||`: print the sha, then decide.

## 2026-10-08 -- A "within-group" slope needs per-group demeaning; pooling across groups measures the groups `[session e0a3e383]`

- **Measured:** an NBA sim "within-draw" H1→H2 margin slope of +0.21 pooled 158k draws across 791 games, removing
  only the grand mean. Per-game demeaned it was −0.001. The +0.21 was the spread of the sim's game means (SD 13.1).
- The wrong number was written up as a "persistent per-draw shock" and handed to a code survey, which found no such
  term and spotted the missing demeaning.
- **Rule:** when a claim says "within X", subtract each X's mean (or use a fixed-effects regression) before pooling,
  and state the demeaning in the result line.
  - A fast check: compute the slope on the X means alone. If it is large, the pooled slope is measuring it.

## 2026-10-08 -- A numstat you print AFTER the commit is not a gate `[lane prop-recency-budget]`
- `git diff --numstat` read `1036 1036` for a one-line move in `.syndicate/leads.md` (the autocrlf working copy's CRLF went into the blob), but the commit was chained in the same command, so the number was read after it had landed (e5592355; restored da62cb56).
- **Rule:** for ledger edits, run the numstat as its OWN step and only commit when insertions/deletions match the edit's size (an append: N/0; a one-line move: 1/1 or 2/1). A count near the file's line count is a line-ending rewrite, not an edit.

## 2026-10-08 -- "Board build idle" on a FRESH refresh-worker means its first build has not STARTED, not that a save happened `[lane layer2-board-ui-redesign]`
A restart-after-save watcher read `Board build idle` 7.5 min after a supervisor `up` and TERMed the worker at 20:30:03Z -- killing the cold build (served `layer2_shortlist` was still 20:07:24Z, from before the up). The safety read describes the log since boot, and a process that has not begun building reads exactly like one that just finished. **Rule:** a "right after a save" gate must compare the served `layer2_shortlist` stamp to the worker's start time (`ps -o etimes`) and fire only when the save is NEWER than the boot. Cost here was ~8 min of cold build; on a full slate it is ~20. Corollary measured the same hour: each board DATE saves separately (`state_meta.dates`), so a restart is not live for tomorrow's rows until that date's shortlist re-saves -- reading only today's date made soccer look unchanged.

## 2026-10-09 — FORBIDDEN: rewriting a ledger file in TEXT mode; read and write bytes `[lane soccer-roster-refresh-accuracy]`
- **What happened:** a checkpoint edit read `lanes.md` with Python's default universal newlines and wrote it back. A peer lane's verdict line held an embedded `\r`, which became a line break: the peer's line was split in two (d55a3c17, numstat `3 1` where `1 0` was intended). Repaired byte-exactly in 74da0acd.
- **How to apply:** to splice a line into a shared ledger file, `open(p, 'rb')`, insert bytes, `open(p, 'wb')`. Then check `git diff --cached --numstat` shows deletions == 0 before committing. A nonzero deletion on an append-only edit means your write changed someone else's bytes.

## 2026-10-09 -- A calibration fitted AND validated inside one month inherits that month's environment `[lanes mlb-combined-calibration, mlb-statsapi-asof-rebuild]`
The combined calibration was fitted on 06-15..07-12 and validated on 05-30..06-14, and its hr_rate_mult 1.856 passed. Out of sample (07-16..09-27, 985 games) it over-predicted HR ~25% and runs +0.70/game. Reason: June 2026 was a league-wide HR spike (StatsAPI HR/PA: Jun .0343 vs season .0303; not temperature, June was cooler than Jul/Aug), and both sets sat inside it. A fit + validation pair from adjacent weeks shares one environment, so validation cannot catch an environment-specific fit. **Rule:** before trusting a level parameter, compare the fit window's league rate for that stat against the season's (StatsAPI teams/stats byDateRange, one call per month); if the window is an outlier month, the validation set must come from a different month.

## 2026-10-09 -- A fix that closes one bias can EXPOSE a second one that was cancelling it -- check the metric before AND after the change before attributing it `[lane mlb-statsapi-asof-rebuild]`
I attributed the shipped config's ~10-pitch-per-start deficit to its early_count_foul_boost change (2.05 -> 1.5) and pre-registered a pitch fix on it. Restoring 2.05 added only +0.7 pitches. Pitches per PA had been ~11% low BOTH before and after the ship (P/BF z -2.5 / -2.3, a field I already had); pre-ship pitches per START looked right only because starters faced +1.9 BF too many. The same shape occurred with starter walks the same week (right only by cancellation). **Rule:** when a shipped change seems to "cause" a regression, read the per-unit metric (P/BF, BB/BF) pre and post first. If the per-unit metric did not move, the change exposed an old error; it did not create one, and the fix target is the old error.

## 2026-10-09 — A SINGLE FULL-SUITE PASS CANNOT ESTABLISH A FAILURE COUNT ON THIS SUITE `[lane suite-baseline-flakiness, session 4ab694ed]`

**Rule.** Never offer a full-suite failure count as a result without re-running
the failing files in isolation first. On this suite, per FILE, the failure set is
sometimes not even stable between runs.

**Why, measured 2026-10-07/09.** Per-file isolated re-runs of the 23 files that
failed in one long run: **92 reproduced, 56 did not reproduce, and 41 failed ONLY
in isolation.** The decisive cases are not marginal:
`test_inplay_board_cadence.py` failed **7 tests in the long run and 9 alone, with
ZERO tests in common**; `test_execution_multi_venue.py` failed exactly **one test
in each run — a different one**. Zero overlap kills the obvious story ("earlier
state masked it"): the mechanism is nondeterminism, in thread/lock/launcher/socket
tests, on a host pinned at 100% CPU.

**How to apply.** Classify per file, three ways: reproduced / did not reproduce /
only-in-isolation. Normalise parametrize ids before comparing — they are
GENERATED per run (`[823494-574050c1]` vs `[823543-394e1e2b]`), and comparing raw
node ids reported one test as BOTH an artefact AND a newly-masked failure. Quote
the stable group as signal and name the unstable group explicitly, so the next
session cannot read a single-pass count as a regression.

**Two corrections this produced.**
1. `state.md`'s `[full-suite-run-method]` said **"`py -3 -m pytest tests/` IN ONE
   PROCESS CANNOT FINISH"**. It can: 22,003 tests, 10h29m15s, one process.
   Overwritten in place.
2. I diagnosed an `xdist -n 3` run as an execnet DEADLOCK on the strength of
   0.00s CPU across controller and 3 workers for 8.5 minutes, and designed a whole
   args-file sharding replacement around that. It was **CPU starvation at Idle**
   while the fleet held ~11 of 12 cores. **0% CPU and a hang are
   indistinguishable without a control** — the control that settled it was an A/B
   with two simultaneous Idle processes (Normal 94% of a core, Idle 30% and 1%).
   Related and already in this file: an Idle run yields to the fleet entirely
   because Windows sees the whole WSL fleet as ONE Normal process.

## 2026-10-09 -- A test that passes in a data-less worktree is not a passing test -- run it with SYNDICATE_DATA_ROOT=prod before trusting it `[lane nfl-name-test-hermetic]`
My 10-07 reachability test asserted `(None, "unresolved")` and passed in my worktree. A peer's 10-08 change added a collision branch that, with REAL data, returns `ambiguous_current_season` for `k.williams`, and the fleet CI (on a checkout with data) flagged it. The same blindness cut the other way the same day: 19 odds-test failures I saw in worktrees were pure data absence (the fleet CI passes both files). **Rule:** a worktree's test result is a statement about a tree with no data/. Before calling a test green or red, run it on the fleet with `SYNDICATE_DATA_ROOT=$HOME/syndicate-prod/data` (read-only, nice 19), or read the latest `logs/job-ci-suite.log`, which runs the full suite against data.

## 2026-10-09 -- A classifier built from the code's write path still needs a read of the real file before it is trusted `[lane soccer-lineup-reach]`
I wrote the confirmed-XI classifier from `build_usage_profiles` (10-11 players at >=0.75) and it reported 0 confirmed on every side. Two blind spots: it keyed sides off `match.home_team`, which the freeze does not carry (0 rows everywhere), and EPL season shares alone reach 12-16 at >=0.75. Printing one side's raw shares showed the real signature (0 players in the middle band) in a minute. **Rule:** before running a classifier over a population, print the raw field for one known-positive and one known-negative case; a classifier whose every output is the same answer has measured nothing.

## 2026-10-08 -- A MULTI-FILE LEDGER EDIT AND ITS COMMIT MUST NOT RUN IN PARALLEL: the commit recorded 1 of 3 files under a message claiming all 3 (lane status-effective-memory-cap)

- **What happened:** one script edited state_worker.md, then lanes.md, then the log. It raised `ValueError` at lanes.md (the lane was the LAST block under `## OPEN`, so "next `
### `" did not exist). The commit was a SEPARATE tool call in the SAME batch, so it ran anyway and pushed `state_worker.md` alone under "close lane". The script's numstat line, printed before the commit, already showed only 1 file.
- **Rule:** run the commit in a LATER turn than the edit, after reading the edit's output; or gate it in one command (`script && git add ... && [ "$(git diff --cached --name-only | wc -l)" = 3 ] && git commit`). Bound a lane block by the next heading of EITHER level (`
##` or `
###`), never `
###` alone.

## 2026-10-09 — A "TAKE MY SIDE FROM THE MARKER TO EOF" CONFLICT RESOLVER IS SAFE ONLY IF YOUR SECTION IS AT EOF `[lane suite-baseline-flakiness, session 4ab694ed]`

**Rule.** When auto-resolving a ledger rebase conflict, extract YOUR addition by
its own bounds — marker to the next heading — never marker-to-end-of-file. And
assert an invariant that would catch the failure (no duplicated entries, one
`## Archived lanes` heading) before writing.

**Why, measured.** My land script resolved every conflicted ledger file with
"upstream + my side from my marker to EOF". For `log/<date>.md` and
`learnings.md` that is correct, because an append IS at EOF. For `lanes.md` it is
not: a lane block goes at the end of `## OPEN`, which is byte 4,478 of a
736,805-byte file, so marker-to-EOF captured my block PLUS the entire archived
section and appended a second copy. Result on `origin/main`: lanes.md
728,228 -> 834,895 B (+106,667), the one-line archived index 516 -> 1,032 entries
with 516 duplicated, and 638 added lines.

**Why it was not caught sooner.** The obvious check did not see it. `### ` block
slugs stayed DISTINCT (144 -> 145) because what duplicated was the one-line INDEX,
not the blocks — so "no duplicate slugs" read as clean while 104,199 bytes were
duplicated. The signal that did show it was the SIZE delta: +103,007 B for a
2,465 B block. **Check the magnitude against what you intended to add.**

**Repair, for the pattern.** The duplicated span was byte-identical to the
original across all 104,199 bytes (only a trailing newline differed), which is
what made deleting it safe rather than merging it. Verify that equality explicitly
before removing a six-figure byte count; do not infer it from headings that look
repeated.

**Also.** A peer (`0d4fd33b`) had already hoisted my block out of the archived
section where the bad append left it — `lane-guard` reads `lanes.md` and nothing
else, so a block below `## Archived lanes` has its claims silently un-enforced.
The post-write guard named it immediately; it was right and I should have fixed it
before pushing anything further.

## 2026-10-09 — THE SPARSE-WORKTREE PENALTY, NOW MEASURED AT SUITE SCALE: ~10x THE FAILURE COUNT `[lane suite-baseline-flakiness, session 4ab694ed]`

The rule that a worktree supports no conclusion about code reading `data/` is
already in this file. What was missing was the SIZE of the effect on the full
suite, which is what makes a sparse count look like a credible regression report.

**Same suite, same week, one process, serial, both runs to completion:**

| tree | tests | result |
|---|---|---|
| sparse worktree `b1d9ce0f` | 22,003 | **331 failed, 191 errors** (10h29m) |
| primary tree `4d9f4ade` | 22,784 | **49 failed, 6 errors** (1d 3h59m) |

**The discriminating evidence, not the inference.** Earlier I split the sparse
failures per file into 13 whose failure set was STABLE across two independent runs
and 8 whose set CHANGED. I guessed from test NAMES that the stable 13 were data
dependence. All 13 are GREEN in the complete checkout — `test_archives.py` (32
failures), `test_bet_status_ncaaf.py` (10), `test_ask_sport_coverage.py` (4) and
the rest. They were confirmed by DISAPPEARANCE, which is a measurement; the names
were only a hypothesis.

**How to apply.** Never quote a sparse-worktree failure count as the suite's
state — it is wrong by about an order of magnitude here. If a sparse run is all
you have, say so and give the figure as an upper bound. And note the corollary:
the 55 real failures live in 26 files with ZERO overlap against the 23 files the
sparse run pointed at, so a sparse run does not even identify the right FILES to
investigate.

## 2026-10-09 -- FORBIDDEN: listing a role's env KEYS with `tr '\0' '\n' < /proc/<pid>/environ | cut -d= -f1` -- a multi-line value (a PEM key) prints its body lines as "names" `[lane games-rail-full-detail, session d4409ac4]`
- **What happened:** to find which env keys only the web process has, I split `/proc/<pid>/environ` on NUL -> newline and cut at `=`. `KALSHI_PRIVATE_KEY` is a PEM with embedded newlines, so every line of its body after the first had no `=` and was printed whole as a "key name" -- private-key material landed in the session transcript. User told to rotate the key.
- **Rule:** read a role's env in PYTHON (`dict(x.split("=", 1) for x in raw.split("\0") if "=" in x)`) and print only KEY NAMES that match `^[A-Z][A-Z0-9_]*$` (or booleans / lengths for chosen keys). Never line-split environ in a shell pipeline. Same family as the 2026-10-07 xargs rule: any tool run against a production env is a secret-handling operation.
- **Also measured:** the local fleet loads ONE env file into every role, so `SYNDICATE_WEB_DYNO` is set on the refresh-worker too -- it does not identify the web there. Web-only keys are `GUNICORN_CMD_ARGS` / `PORT`.

## 2026-10-09 — RULE: ESPN basketball `plays[].sequenceNumber` is not chronological; use the list order, and gate any pbp replay on the reconstructed final == the header score `[lane wnba-native-live-cutover, session 99686b8c]`

Sorting 2026 WNBA plays by `sequenceNumber` put the last play mid-game on 27 of 218 games and cut stint-minutes agreement with the box to 0.82; the feed's list order gave 344/347 score-reconciled games and 6,901/6,901 players within 1 minute. The failure was silent until the replay's final score was compared with the header, so that comparison is the gate, not an optional check. Also: a clean `vendor\.` grep is not proof of no vendored code. `importlib.import_module(f"{pkg}.sim.events")` after a `sys.path.insert(vendor/...)` matches no `vendor.` pattern.

## 2026-10-09 -- a refusal with a fallback is not a stale copy: read what the FALLBACK wrote `[lane query-state-cache-oversize]`
The 10-08 lead framed query_state_cache refusals as "readers get a stale copy". Every refusal was followed by a SUCCESSFUL trimmed write, `STATE_PERSIST_TRIMMED kept_full=0`, so readers got a fresh cache with no responses at all: 546 of 546 fallbacks. The trim's budget was in RAW bytes (6 MB), written before #322's compression, so a 42 MB-raw snapshot could never be kept. A compressed cap paired with a raw-byte fallback budget is a unit mismatch that makes the fallback structurally empty. Also: "0 since <time>" in a lead expires. Refusals resumed 18 h later because the count is driven by how many board-window dates are held (2-3), and a restart resets that to 1. **How to apply:** after any KEYVALUE_WRITE_REJECTED, count the fallback outcome lines (TRIMMED kept_full=/FAILED) in the same window before describing the cost. Re-read a lead's "none since" with a window that ends now.

## 2026-10-09 - RULE: copy fleet files to the Windows side through the //wsl.localhost share, not with cp/dd from inside WSL to `/mnt/c` `[lane nfl-kalshi-clv-pooled, session f628c245]`
- **What happened:** `cp` and then `dd bs=1M` from `~/syndicate-prod/data` to `/mnt/c/...` failed with `Cannot allocate memory` on 40-160 MB files (drvfs write path) while WSL reported 9.8 GB available; one file was left truncated (40.9 of 41.5 MB). Separately, `$VAR`s in an inline `wsl bash -lc '...'` arrived EMPTY from Git Bash, so `cd $D` went to `~` and a file was written into the WSL home.
- **Rule:** read fleet data from Windows (PowerShell `Copy-Item` from the //wsl.localhost/Ubuntu-24.04/home/amyn/... share), hash every copied file, and compare sizes against the source. Put multi-variable WSL commands in a script file (`wsl bash /mnt/c/.../x.sh`) rather than inline.


## 2026-10-09 -- RULE: ESPN NCAAB summary payloads drop lines and headlines; read the core odds API and header.gameNote `[lane ncaab-native-live-tier, session e48a0f9b]`
- Measured: `summary?event=` has an EMPTY `pickcenter` for early-season games (0 of 169 on 2025-11-03, 0 of 82 on 11-15, present by 12-10), while `sports.core.api.espn.com/.../events/<id>/competitions/<id>/odds` still holds ESPN BET open/close. The summary's `competitions[0].notes` is None; the tournament headline is `header.gameNote`.
- ESPN keeps NO in-play line history: provider 59 ("ESPN Bet - Live Odds") holds one untimestamped last quote, and `/odds/<p>/history/0/movement` returns 0 items. Do not grade a "live close" against it.
- How to apply: a corpus that reads only the summary silently loses ~10% of its lines (the early season) and labels every NCAA tournament game as other postseason.

## 2026-10-09 - RULE: a "beat the incumbent" ship gate must also carry a NAIVE baseline `[lane nba-native-live-resim, session 6c348b8f]`
- **What happened:** P3's gate was written as "beat the current vendored live projection".
  - Replayed on 780 games, the vendored NBA live tick LOST to the simplest estimator available: current
    score + the pregame line's pro-rata share of the remaining time.
  - It lost on margin at end Q1 (+0.86 MAE, CI +0.40..+1.30) and on ML at end Q2 and 5:00 Q4.
  - A native sim that beat the incumbent could still be worse than doing nothing clever.
- **Rule:** every model gate names a naive baseline beside the incumbent, and reports both. A candidate
  ships only if it beats the better of the two.
- **Related:** a mechanism measured in one season phase is not a target in another. Regular-season
  score-effect reversion (−0.17) was not detectable in the playoffs (n=91).

## 2026-10-09 — `git diff` CAN SHOW A LINE-ENDING REWRITE AS CLEAN WHILE THE COMMIT RECORDS EVERY LINE `[lane lanes-archive-over-budget, session 4ab694ed]`

**Rule.** After any tool writes a shared ledger file, read `git diff --cached
--numstat` BEFORE committing, and check the committed blob's line endings after.
Unstaged `git diff` is not a safe preview of what the commit will record.

**Why, measured.** `scripts/archive_released_lanes.py` writes in text mode, so on
Windows it rewrote the whole 4MB `lanes_history.md` from LF to CRLF. I checked for
exactly that and got a false all-clear: unstaged `git diff --numstat` reported
**679 insertions / 0 deletions**, so I concluded git would normalise it. The
staged diff was **38,213 / 37,535**, and that is what 5ac74a83 pushed.

**The asymmetry that produced it.** `core.autocrlf=true`, no `.gitattributes` rule
for these paths. git normalised `lanes.md` (committed CRLF 0, bare LF 1,870) and
did **NOT** normalise `lanes_history.md` (committed CRLF 38,213, bare LF 0). The
difference: `lanes_history.md` contained a **bare CR**, which makes git decline to
treat the file as normalisable text. Two files written the same way by the same
tool in one commit, landing with opposite line endings.

**The second, worse half.** That same text-mode write converted `lanes.md`'s single
mid-line bare CR into a line break, SPLITTING a peer's line inside the archived
`layer2-board-ui-redesign` block — byte for byte the failure `74da0acd` repaired
after an earlier text-mode rewrite of `lanes.md`, and what the 10-06 standing rule
forbids. A lone CR mid-line is a CHARACTER, not a line ending, and must survive.

**How to apply.**
- A regex `^...$` with MULTILINE is unsafe on a CRLF file: `.` matches CR, so `$`
  sits after it and the match swallows the CR. Reassembling then emits a bare CR.
  Match the line body with [^\r\n]* instead. This bit me twice in one
  session; only a lone-CR assertion caught the second.
- Assert lone-CR conservation across every file a write touches, AND across the
  PAIR when a tool moves content between two files: the CR left `lanes.md` and did
  not arrive in `lanes_history.md`, which a per-file check calls fine.
- Prove content separately from formatting. The honest figure for this archive is
  the diff against the commit BEFORE it — 678 insertions / 0 deletions, 0 prior
  lines missing — not the line-ending churn.
- Writing \r\n inside a shell heredoc collapses to a real CR: the heredoc
  eats one backslash level. Build such fragments with chr(92), or assert the text
  contains no CR before writing it. That is how a real CR got into this very entry
  on the first attempt.

## 2026-10-09 — OVERTURNED (mine): "the WNBA linear live lens's ML is worse than ESPN from end Q1". The baseline was anchored on a file the lens never reads `[lane wnba-native-live-cutover, session 99686b8c]`

v1 of the 2026 checkpoint corpus fed the shipped lens functions `predictions_<date>.csv`'s `home_win_prob` / `totals`. Production's lens reads `game["betting"]`, whose `p_home_win` / `pred_total` / `p_home_cover` / `p_total_over` come from the per-game `smart_sim_*.json` via `refresh_wnba_oddsapi_props._smart_sim_projection_index` -- a different estimate (DAL v TOR 2026-08-12: 0.657 vs 0.74; 165.8 vs 180.0). Re-anchored, the end-Q1 deficit (+0.020, CI excluding 0) became level (-0.000). **RULE:** importing the shipped FUNCTION is not enough to reproduce a production baseline; feed it the INPUT production feeds it, traced from the call site (`cards.py:1365 betting = game["betting"]`) back to the producer, and call the producer too. Second half, same session: a parser cross-check that "agreed on every cell" was empty for the score, because both sides read ESPN's per-play running `homeScore`, which lags the scoring-play sum on 36 of 347 games. Agreement between two readers of one field says nothing about that field.

## 2026-10-09 -- OVERTURNED: "#473 has zero current production impact because NBA is offseason" `[lane basketball-native-engine, session d10f7421]`
- **Belief (state_basketball [basketball-smart-sim-engine], 2026-08-19):** NBA's team-advanced-stats rebuild returns nothing, but this has "zero current production impact since NBA is offseason".
- **Measured 2026-10-09** (engine input checklist over 15 real NBA production sims, 10-05..08): `home/away_team_adj` was absent on **0 of 30 NBA team-sides**, against **24 of 24 WNBA**. The NBA preseason sims are live and run with neutral team quality.
- **Rule.** A defect parked with "no impact because the season is off" carries a due date: the season opener. Re-measure it then, with the checklist, not the note. Same family as "a documented caveat is a scheduled defect".

## 2026-10-10 - RULE: a fleet job launched from a short-lived shell must be detached, and must resolve a worker pid AT USE `[lane nba-native-live-resim, session 6c348b8f]`
- **What happened:** two of three fleet verification jobs failed for reasons unrelated to the code under test.
  - A parity replay started with `nohup ... &` inside `wsl -- bash script.sh` died with an empty log when the WSL session exited.
  - An A/B arm read `--env-from-pid` resolved 28 minutes earlier; the refresh-worker restarted in between, so `/proc/<pid>/environ` was gone.
  - The first compare then ran arm A against STALE files in arm B's untouched data copy and printed FAIL.
- **Rule:**
  - Launch with `setsid nohup ... < /dev/null & disown` and confirm the pid is alive in a later call.
  - Resolve a role pid in the same shell line that uses it.
  - An A/B compare is only valid when the arm's run line says `exit=0` and wrote N.
