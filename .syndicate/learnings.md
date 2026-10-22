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

## Index — 1395 rules `[generated]`

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

- **THE RULE.** Before a diagnosis enters the ledger, DECOMPOSE the whole failure population into its candidate causes and report the share of each. An example is evidence that a mechanism EXISTS, never that it DOMINATES. The most extreme row is selected for being extreme, which makes it the least representative row available.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-21 FORBIDDEN: verifying that a signal was COMPUTED as verifying that it is REAL `[lane layer2-line-move-magnitude]`

- **THE RULE.** A verification must include one check that the population the feature acts on IS the population it claims to act on -- here, "is the opening line actually gone?" -- not only that the feature produced output. Coverage going up is equally what a feature firing on the WRONG rows looks like. Same family as `[feedback_presence_is_not_reachability]`, one level up: the code was reached, the output was produced, and neither proved it was about the right thing.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-21 FORBIDDEN: shipping a "by construction" guarantee without checking the property of the DATA it rests on `[lane layer2-line-move-magnitude]`

- **It was checkable offline in one query** — within one build, is a side's fair monotone in its line? — and I skipped it because the construction "proved" it could not matter.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-21 FORBIDDEN: rolling back by redeploying an ANCESTOR SHA `[lane layer2-line-move-magnitude]`

- **THE RULE.** A rollback is a NEW commit (`git revert <sha>`), pushed, then deployed like any other change and verified by the same measurement that caught the defect. Then CHECK WHAT SURVIVED: `git revert` of one commit leaves its neighbours, which is right, but confirm it — here `088f39fe` (the moneyline waiver) had to be read back off the served board to be sure the revert had not taken it too. Correct rollback: `f1fe4ee1`, conflicts **174 -> 0**.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-20 FORBIDDEN: reading a comment REPEATED across files as corroboration `[lane layer2-line-movement-scoring]`

- **THE AGGRAVATING DETAIL: the contradicting line was in my own grep output.** I ran `grep -rn sweep_changed_hot_artifacts`, `:1490` printed, and I read past it because six agreeing lines had already settled the question. Repetition did not just fail to help -- it actively suppressed the one line that mattered.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-20 FORBIDDEN: quoting a RATIO next to an extreme value it was not computed from `[lane layer2-line-movement-scoring]`

- **09-19's**, and its ratio is **345x**. A reader takes a multiplier as the multiplier OF THE NUMBER NEXT TO IT -- that is what adjacency means in prose -- so the sentence asserts something false while containing no false number.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-16 — a detector that matches a FORMULA at published precision has a FALSE-POSITIVE RATE, and mine fired at about 1 row per 1,200 `[session abacd435, lane soccer-anytime-scorer]`

- **The instrument.** `unconditional_ladder_share` decided whether a soccer shot row was priced on the OLD unconditional ladder by testing `ladder["0.5"] == round(1 - exp(-expected_shots), 4)`. It verified fix #2 on both workers.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-16 — OVERTURNED: "the pre-registered criterion is the safe part, the risk is in the mechanism" — two hypotheses in one night died on the CRITERION `[session abacd435, fixes #4 and #5a; no lane]`

- **H20 condition (c)** compared the model's favourite price to **the market's**. On TEST, favourites the market priced at 70.7% actually won **78.5%** (n=158), so the arm that best matched OUTCOMES (k=2.0, at 0.801) is the one the criterion penalised hardest. It silently assumed the benchmark was calibrated on that sample.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-16 — FORBIDDEN: gating a backtest on a `matches_scored` baseline produced by a DIFFERENT code state. Pin a fresh reference at the commit the run uses `[session abacd435, fix #4]`

- **The run was right and the baseline was stale.** `skipped_thin_ratings` rose 3-5x in exactly the five Understat leagues (epl 202 -> 699, la_liga 202 -> 873, bundesliga 180 -> 847, serie_a 200 -> 613, ligue_1 180 -> 528) and is byte-identical in the four goals-based ones. The harness was corrected after that baseline to read ratings the way production does, branch for branch: the big five use Understat xG+ppda with `window=45` where the baseline used goals-as-xG with `window=90`, and a 45-day window admits far fewer teams to the 20-prior-matches test.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-16 -- `lanes.md` ACCRUES IMPERATIVES THAT NOBODY RETIRES, and re-offering one costs the USER, not just me

- **STANDING RULE: never offer an owed item without verifying it against the source that RETIRES it** -- deploy state from the service's live commit, env state from a single-key GET, a user decision from `deploys.md`. `lanes.md` proposes; it never confirms.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-16 — FORBIDDEN: counting a log-search result without excluding the search tool's own echo of the pattern

- **How to apply.** Filter to lines that ARE log lines — a `^\d{4}-\d{2}-\d{2}T` match — not merely lines containing the pattern. This generalises past this one tool: any wrapper that echoes its own query (grep with a banner, a paging tool that prints the window it covered) puts its parameters into the output stream it is filtering. Related: [[feedback_instrument_blindness]] — a healthy reading is evidence only once you know what makes it read unhealthy; here the unhealthy reading was unreachable, because the count could not go below 1.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-16 -- A "NATURAL EXPERIMENT" IN WORKER MEMORY MUST BE CHECKED AGAINST THE DEPLOY TIMELINE FIRST

- **STANDING RULE: before reading any interval of a worker's memory as cause and effect, list that service's deploys AND events for the window** (`/v1/services/<id>/deploys`, `/events`) and discard every interval that contains one. A restart moves the cache and RSS together, which is precisely the signature of the effect being hunted.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-16 — FORBIDDEN: treating a clean `land` or a silent lane-guard as proof that a SCRIPT write respected another lane's file claim

- **How to apply.** Before any script write to a path outside `.syndicate/` — and `todo.md` counts, it is claimed often — run `py -3 scripts/check_lane_claims.py` or grep `lanes.md` on `origin/main` for the path and read the holder's status. If an OPEN lane claims it, stop and surface, as the protocol says; the absence of a refusal is not permission.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-16 — FORBIDDEN: a duplicate detector whose grouping key is a field the defect writes. It reads 0 in both states. `[lane layer2-chip-rail-duplicate]`

- **How to apply.** Before trusting a "0 duplicates" reading, name the field each detector groups on and check it is not produced by the code under test; then run it on the pre-change code and require it to read non-zero. The same session's two watchers failed the same way: one grepped `server_failed` and matched the tool's `# CLEAN no server_failed` footer, and one gated on a TOTAL row count and printed `RECOVERED` while soccer kept falling.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-16 — FORBIDDEN (user decision): blocking a whole SPORT or MARKET FAMILY from staking

- **Every play is its own entity.** The user, 2026-09-16 ~10:25 CT, verbatim: "we shouldnt block anything globally - that includes MLB player props.  every prop and game line is its own entity in the scheme of things - we optimize overall but there's ALWAYS a chance an individual play is viable based on EV, sim edge, etc".
- *(evidence in `learnings_evidence.md`)*

## 2026-09-16 — FORBIDDEN: gating anything on a substring of `render_logs.py` output without `--width`

- **How to apply.** Pass `--width 200000` whenever a decision depends on WHAT a line contains, and prove the watcher reads the unhealthy state on a sample known to be unhealthy before trusting its all-clear. `deploy_preflight.py` itself reads the Render logs API untruncated, so it remains the authority on in-flight jobs.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-16 — FORBIDDEN: opening a source file for write before its new content is fully built. A raise between `open(p, 'wb')` and `write` leaves the file EMPTY, with no error pointing at the file. `[lane soccer-board-tomorrow-shortlist-collapse]`

- **How to apply.** Build the bytes first, then open: `data = ...; with open(p, 'wb') as f: f.write(data)`. For code, prefer the Edit tool, which never truncates on failure. After any scripted write to a tracked file, read `git diff --numstat` before doing anything else, and treat a deletion count near the file's length as an emptied file.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-16 — FORBIDDEN: attributing a portfolio plan's output change to a deploy without reading the plan's own `settings` block. Settings are written through an API with no deploy, and they bind before code does. `[lane soccer-board-tomorrow-shortlist-collapse]`

- **How to apply.** Before attributing any plan change, read `settings` (values AND sources) and the binding refusal (`beyond_max_positions`, the exposure scale) on the plans either side. If a cap was the binding refusal before, a settings change is the first suspect, not the deploy.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-16 — FORBIDDEN: changing a staking-policy env value without running the gating input checklist WITH that value

- **How to apply.** (1) Before any env change that alters what the commit accepts, run the gating checklist in-process with that env set (`SYNDICATE_PORTFOLIO_MARKET_FAIR_SPORTS=<value> py -3 scripts/portfolio_commit_input_checklist.py`, or the pytest that drives it) and require exit 0. (2) Every portfolio deploy's verify must include a liveness leg: a commit after go-live that is NOT `PORTFOLIO_COMMIT_SKIPPED`. (3) A verifier waiting for a post-deploy artifact must also watch for the SKIP/FAIL line that means the artifact will never come; "no population yet" for 2x the usual cadence is itself a reading.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-16 — FORBIDDEN: pinning a PUBLISHED claim with a test that reads the configuration it depends on implicitly

- **How to apply.** A test whose assertion depends on a setting must set that setting explicitly with `monkeypatch`, in every state production can hold, and assert the outcome in each. If a claim is true only under one configuration, it is not structural. Publish what holds in any configuration (here: "no model edge, so sized on market fair") instead of what holds in CI.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-17 - FORBIDDEN: predicting which DEPLOY will fix a served value before tracing which DATA COPY the serving service builds it from `[lane soccer-postponed-served-final]`

- **What happened.** The postponed ATH @ LEV chip read `0-0 FINAL`. I recommended deploying refresh-worker "to fix the chip", then said the fix was waiting on a live-odds-worker rebuild. Both predictions were about code. Data decided it: a 21:37Z artifact built by old code and copied to refresh-worker. The chip cleared when the corrected artifact reached refresh-worker (23:00Z, still on OLD code), and it came BACK after refresh-worker restarted onto the FIXED code (00:05Z), while web on the same fixed code served it correctly. The rebuild-cadence prediction (4 h, so ~01:37Z) was also wrong: it ran at 22:43Z.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-17 — FORBIDDEN: diagnosing from an AGGREGATE timestamp without naming which input set it — and correcting a claim on weaker evidence than the claim had `[lane heavy-build-memory-refusal]`

- **What happened.** Asked why the combined Layer 2 board showed "last refresh an hour ago", I read `state_last_updated` (22:03:10Z, 61 min old) and traced it to memory-guard refusals -- without knowing that field is the OLDEST of several dated inputs. Later, finding that out, I pushed a correction saying today's staleness was UNKNOWN. A third read showed the oldest input was in fact TODAY's shortlist, and the 22:03Z stamp matched `LAYER2_SHORTLIST date=2026-09-16` exactly. The first diagnosis was right; the correction was wrong, and both were pushed to the ledger.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-17 — FORBIDDEN: pre-registering a forward test without measuring that its qualifying population can exist, or a threshold without measuring its ceiling

- **H24 (`#665`)** required "a production recommendations artifact built BEFORE kickoff". 43 of 43 matches sat in artifacts generated AFTER kickoff, because the builder rewrites one file per league-date through the match. The population was zero forever. Nobody could have found out before grading day (2026-10-15).
- *(evidence in `learnings_evidence.md`)*

## 2026-09-17 — FORBIDDEN: running `git worktree prune` from a session

- **How to apply.** Remove only your own worktree (`git worktree remove <path>`). If a directory is left behind, delete that directory and check `git worktree list` for your path alone. Never prune.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-17 — A CACHE TTL READ FROM THE CODE IS NOT THE LIVE TTL, and the live one decides how long a served timestamp may lag. `[lane board-today-freshness]`

- **The rule going forward:**
- *(evidence in `learnings_evidence.md`)*

## 2026-09-17 (session 1628e558, lane `web-memory-guard`) — OVERTURNED, my own hypothesis: "cap glibc arenas on web and per-worker anon comes down". THE LEVER MOVED ITS OWN INSTRUMENT AND NOT THE OUTCOME

- **A fix that moves the instrument it targets has not thereby moved the thing you care about.** Name the outcome number before the deploy, or the instrument's improvement becomes the verdict by default.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-17 (session 1628e558, lane `web-memory-guard`) — FORBIDDEN: bounding a process's memory with a check that runs BETWEEN units of work, then sizing the limit at the target

- **Size the limit for the largest single unit of work, not for the ceiling you want.** 2 x (650 + ~100) fits 2,048 MB with the master and two merge children; 2 x 700 plus a 72 MB overshoot does not leave that room.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-17 (session 1628e558, lanes model-scorecard-cron / web-memory-guard) — `session_worktree.py close` REFUSES A CHERRY-PICKED BRANCH FOREVER, AND ITS "N commit(s) not on origin/main" IS AN ANCESTRY CLAIM, NOT A CONTENT ONE

- **`git cherry -v origin/main <branch>` is the check that settles it.** A `-` prefix means git found a patch-identical commit upstream; a `+` means it did not. All five printed `-`, so `--force` discarded nothing. The same relation is invisible to `merge-base --is-ancestor`, which is what the tool (and my instinct) reached for.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-17 — OVERTURNED: "refresh-worker publishes NO soccer recommendations, so its pre-kickoff freeze is not observable from web" `[lane soccer-live-corners-stage2]`

- **What was believed** (`deploys.md` 2026-09-17 05:42:11Z, my own verify): 0 `.refresh-worker.json` freeze files on web by 11:48:31Z and 0 publisher lines for `soccer_source/*/api/recommendations/*` in 169 log lines, therefore refresh-worker's freeze and its estimator corners are local-only and the forward grades merge over ONE visible service.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-17 — FORBIDDEN: reading "which service runs the LOOP" as "which service runs the CODE" `[lane soccer-live-corners-stage2]`

- **Measured:** `SYNDICATE_ENABLE_LIVE_LENS_LOOP` true on live-odds-worker, false on refresh-worker. I wrote from that: this change "needs live-odds-worker only".
- *(evidence in `learnings_evidence.md`)*

## 2026-09-17 — FORBIDDEN: verifying a new ARTIFACT field on a served UI route `[lane soccer-live-corners-stage2]`

- **What happened:** after the live-corners deploy, `/soccer/<lg>/api/game/<event>` carries none of `corners_basis`, `live_corners`, `sim_projected_total_corners`, nor even `projected_total_corners` (checked directly 21:19Z). A verification taken there scores the change a NO-OP.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-17 — FORBIDDEN: verifying a change on a UI CONTRACT route. A served page selects fields; absence there is a fact about the contract, never about the writer. `[lanes soccer-shot-woodwork-undercount, soccer-live-corners-stage2]`

- **The rule going forward:**
- *(evidence in `learnings_evidence.md`)*

## 2026-09-17 — RECONCILE AT THE FINEST UNIT THE DATA OFFERS. A per-match residual hid a one-sided structure that per-team showed immediately. `[lane soccer-shot-on-target-definition]`

- **The rule going forward:**
- *(evidence in `learnings_evidence.md`)*

## 2026-09-17 — FORBIDDEN: counting a search tool's own ECHO of your query as a hit. It turns a zero into a one, and a one is a rate. `[lane soccer-shot-woodwork-undercount]`

- **The rule going forward:**
- *(evidence in `learnings_evidence.md`)*

## 2026-09-17 — FORBIDDEN: reading an artifact FAMILY's retention as its CONTENTS' lifetime `[lane soccer-live-corners-stage2]`

- **What I believed and registered:** H32's evidence lives in `soccer_source/<lg>/api/live_state/live_state_<date>.json`, whose retention rule is 8 days, so "a DAILY harvest into a cache" preserves it (written into H32's registration, `log/2026-09-17.md` ~15:05 CT).
- *(evidence in `learnings_evidence.md`)*

## 2026-09-18 — A LAUNCH'S REASON LABEL IS NOT ITS CAUSE, AND A REASON TOKEN IS NOT A LAUNCH COUNT. Both misread the MLB sim debounce the same night. `[lane mlb-sim-retrigger-churn]`

- **The rule going forward:**
- *(evidence in `learnings_evidence.md`)*

## 2026-09-18 — FORBIDDEN: treating a named data file's PRESENCE as proof that it COVERS what a rule needs `[lane soccer-h24-grader]`

- **What the plan said** (`todo.md #665`, written by this session on 2026-09-15): "The pre-registration names `reports/soccer_backtest/fotmob_2y.json.gz` for the base seasons; confirm it is present before relying on it."
- *(evidence in `learnings_evidence.md`)*

## 2026-09-18 — FORBIDDEN: storing a production env value BEFORE holding the service's deploy claim `[lane worker-disk-auto-retention]`

- **What happened.** On 2026-09-17 I PUT `SYNDICATE_DISK_RETENTION_DRY_RUN=1` on refresh-worker at ~22:05Z so that my own same-commit re-inject could follow after the 22:12:49Z spacing. Another lane took refresh-worker's claim at ~22:12Z and deployed `7ef0431b` at 22:34:51Z; that deploy -- and two more -- injected my env. The change went live under another lane's deploy, with no receipt, no pre-registered baseline read at deploy time, and no one watching its first boot. I had warned other sessions about exactly this ride-along the same day (the next-day floor env) and then repeated it myself.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-18 — FORBIDDEN: certifying a cross-source NAME join as exact from one fixture `[lane soccer-live-corners-book-test]`

- **What the code said** (`syndicate/features/shared/soccer_live_gameline_source.py`, `soccer_live_gameline_index` docstring): the live pricer keys matches on full team names with no alias table because "Gate 1 measured that this join is exact for soccer: the ESPN names in the live-state artifact matched the OddsAPI grid on 286 rows for the 2026-08-20 la_liga fixture."
- *(evidence in `learnings_evidence.md`)*

## 2026-09-18 — FORBIDDEN: attributing a web health-check failure to your change without the day's post-deploy baseline `[lane ncaaf-player-data, session 259d6003]`

- **What happened.** Minutes after web went live on `1c5caea6`, my typed Ask question took 25.6 s and then 59.8 s (both 502), and web failed health checks at 18:14:20Z (with a restart) and 18:20:05Z -- each inside one of my calls. I pulled the new fetcher (`e67c8b8a`) and redeployed. On that build -- fetcher unregistered, and **no requests from this session** -- web failed again at 18:29:21Z, 18:31:43Z and 18:33:48Z. The events API showed the same shape after EVERY web deploy that day and the day before (1-4 `server_failed reason.unhealthy` within ~10 min, then quiet). The fetcher measured 0.152 s cold on production's own snapshot. It was restored 30 minutes after it was pulled, at the cost of two extra web deploys, each with its own cold window.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-18 — OVERTURNED: "a CLOSED block whose HEADER sessions are all idle is safe to archive" — a session the header never names had closed it 3 minutes earlier `[lane lane-archive-tool-checks, session 4991d2ec]`

- **What was believed:** the 09-15 rule above made the archive tools read owner liveness, taking "owner" to be the session ids in the block's first 3 lines. `owner_liveness.py` printed SAFE for `fotmob-team-name-aliases` because da346015 had been idle 3,910m.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-18 — FORBIDDEN: sizing a time window from a DOCUMENTED cadence without measuring the cadence under load `[lane soccer-live-corners-book-test]`

- **What the rule assumed:** H36 took the live projection in force within 180 s of each book update, sized on the "~60 s cadence" written in `live_projection_history.py`'s docstring.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-18 A revert justified by ONE quantity does not cover another, and its call-count premise can go stale. `[lane market-history-index-memo]`

- **What I believed.** The `#75` note in `odds_lifecycle.py` said caching `build_recent_market_history_index` "was tried and reverted": it "bought nothing (identical peak)" and the index "runs once per game", ~15 rebuilds of ~14k events, "noise". I read that as settled, and the profile target went elsewhere at first.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-18 — RECURRENCE of 2026-09-17 "a cache TTL read from the code is not the live TTL": I told the user an autorun flag was OFF because the code's default is off; the service sets it `true` `[lane ncaaf-player-data, session 259d6003]`

- **What happened.** A survey read `_..._autorun_enabled`'s absent-means-off default and I reported "the flag is off, a deploy alone won't run it". The refresh-worker env had the key set `true`; the autorun was already live. Corrected to the user in the same session.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-19 — FORBIDDEN: changing a shared helper's DEFAULT to fix one caller without a census of every caller that takes the default `[lane soccer-live-shared-paths]`

- **What happened:** `live_lens.build_resume_state` gained `include_stoppage=True` as its DEFAULT, to fix `project_live_match`'s missing end-of-half minutes (its docstring measures the resulting bias). `goal_in_window_probability` also calls it, with a clock it has already TRUNCATED to the window, and takes the default. So every goal window has since simulated window + the half's stoppage base: measured 2026-09-19 on the live commit's own code, a second-half "next 5 min" simulated 600 s, "next 10 min" 900 s, and at 60' (neutral, 1-0) the published next-5-minute probability was 0.195 where the model implies 0.100. No test failed, because no test read the clock a window simulates.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-20 — FORBIDDEN: holding a shared deploy claim while polling for a gate that cannot open in that window `[lane soccer-live-shared-paths]`

- **What I did:** a deployer loop took the `live-odds-worker` claim and retried the preflight every ~4 minutes, first for 1h35m (21:35-23:10Z) and then again overnight, waiting for a 0-job CLEAR. Every sample read HOLD with 3-7 jobs.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-20 — RELEASING A LANE CLAIM ON `origin/main` ALONE CAN *MANUFACTURE* THE SAME BLOCK, and the second block reads identically to the first `[lane daily-accuracy-suite]`

- **The only tell is the `Claim source:` line**, which flipped from `origin/main@44e96867` to `primary tree lanes.md, added since fork point 1a280739`. Everything else in the BLOCKED message — file, lane, remedy text — is byte-identical, so a quick re-read looks like a no-op push.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-21 — FORBIDDEN: windowing a simulation by TRUNCATING the clock it is told is left, when the simulator's dynamics read that clock `[session abacd435, measured offline]`

- **What is wrong:** `live_lens.goal_in_window_probability` answers "goal in the next W seconds" by resuming the match with `clock_remaining = W`. `soccersim.situation_model.classify_urgency` reads exactly that field: 2nd half and <= 480 s left while trailing by 1-2 is DESPERATION, <= 1500 s trailing is TRAILING_PUSH, <= 900 s leading is PROTECT_LEAD, 1st half <= 120 s is CLOSING_HALF. So the window is not "the next five minutes of this match"; it is "the last five minutes of a half", played by both sides accordingly.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-21 — A FILTER ON A MODEL METRIC GRADES THE MODEL, NOT THE FILTER'S OWN EDGE; and a seeded bootstrap is deterministic in ORDER, not in DATA `[lane inplay-skill-scoreboard, session a1e40980]`

- **The belief:** "the scorecard's `fair_method=consensus` bucket tells us whether the price-shopping edge is real." I recommended building a slice on it, and the user said proceed.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-21 — A VERDICT OVER EVERYTHING THE BOARD PRICED IS NOT A VERDICT ON WHAT IT SHOWS; report both, and never replace one with the other `[lane inplay-skill-scoreboard, session a1e40980]`

- **What I said:** "the price-shopping edge FAILS on soccer in-play player props, -39% to -76% per game". That was true of the recorded population. Read as exposure, it was wrong: 99.9% of those rows sit in the `dead` lane and are never served. Meanwhile NCAAF in-play moneyline, 154 of 182 rows unserved, puts its 28 SERVED rows at the very top of the live board.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-21 — FORBIDDEN: a guard that reads its credential through a DIFFERENT loader than the action it guards `[lane preflight-board-build-hold, session a1e40980]`

- **The belief (mine, 09-20):** "no `RENDER_API_KEY` means this shell cannot deploy either, so the board-build HOLD may treat it as not applicable." It shipped with a test pinning exactly that.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-21 — FORBIDDEN: fixing a MISSING source before testing whether the consumer could use it when PRESENT; and grading a close for a game that has not kicked off `[lane clv-close-from-book-quotes, session 9e340058]`

- **Measured:** CLV resolved 0 for NFL/NCAAF/WNBA because odds_history was never written for them (fast-mode lanes return before the step). The proposed fix was "make the fast lanes write it". WNBA HAD odds_history on 08-20/08-27/08-29 and resolved **0 of 1,165 / 2,449 / 2,723** anyway: 33- vs 32-char event ids, a prop key shape the join never builds, no alternates. The source the consumer needed (`book_quotes`, per book, keyed by the opening's own fields) already existed on web; 98.9% / 92.0% / 88.5-98.1% exact same-book coverage.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-21 — A MECHANISM THAT EXPLAINS AN ODD RANKING IS NOT EVIDENCE THE RANKING IS HARMFUL; grade the class before fixing it `[lane ncaaf-live-h2h-top-scores, session a1e40980]`

- **What I was about to do:** served NCAAF in-play moneyline rows scored up to 86 (a typical #1 is ~6) and that slice lost -0.38/game. I traced the score to longshot EV passing a 1-probability-point guard, and was heading to recommend a longshot gate or a bigger in-play error floor.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-21 — FORBIDDEN: comparing two RANKINGS on raw closing-line value in probability points, gross of the venue fee; and adopting a correction fitted on the whole population without re-checking it on the subset you will act on `[lane layer2-score-outcome-calibration, session 236bd219]`

- **What I believed, twice, and it was wrong both times:** (1) a candidate ranking that picked favourites "beat" today's score because its CLV was higher in probability points (+1.34 vs +0.96) -- in ROI-equivalent units (delta-p x decimal) it was LOWER (+2.66% vs +3.19%), because one point at +240 is worth ~1.8x one point at -127; (2) then today's score looked marginally better than the fee-aware candidate (-0.15 pts paired) -- until the fee actually paid was netted: 25% of today's top-10 are Kalshi/Polymarket, and net of fees the fee-aware ranking won by +0.79 [+0.27, +1.29] over 82 slates.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-21 — CODE ON MAIN SHIPS WITH ANYONE'S DEPLOY: a "deploy it after X" gate cannot hold once the commit has landed `[lane live-inplay-board-cadence, session a1e40980]`

- **The belief:** the user approved lever 2b ("deploy b tomorrow after tonight's reading"), so I landed `3072ab01` on main and scheduled a GATED refresh-worker deploy for the next morning. I believed that controlled WHEN it shipped.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-21 — FORBIDDEN: deploying a fix whose test fixture SUPPLIES a field the production pipeline only attaches in a LATER stage; run the new code over the production payload with that field WITHHELD first `[lane layer2-score-outcome-calibration, session 236bd219]`

- **What happened:** `569ebca1` read the Kalshi ticker from `side_best` so MLB rows would pay the x0.5 series fee. Its test put a ticker on `side_best`, passed, and failed with the fix reverted -- a textbook reachability test. Deployed (refresh-worker `b99143e2`), it moved **0 of 82** rows: at scoring time no Kalshi price has a ticker anywhere; `apply_venue_quotes` stamps `venue_ref` onto the rows AFTER `build_layer2_rows` scored them (`layer2_shortlist.py:1752` vs `:1611`). 45 of the 82 served rows carried a ticker -- visible on the served payload, so it looked available.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-22 — RULE: a catch-all refusal token says WHERE an order died, not WHY; read the module's own line just before it, and expect the next gate once the first one clears `[lane layer2-score-outcome-calibration, session 236bd219]`

- **What happened:** with `commence_time` fixed, the Soroka strikeout prop refused `market_unresolved_for_position`. I read the token and filed a lead saying `resolve_market` "finds no market for the slug", with the fix pointing at slate truncation or storage. Wrong: the `POLYMARKET_SIDE_REFUSED ... reason=yes_no_market_subject_is_not_our_side outcomes=['Yes','No']` line 24 s earlier showed the market WAS in the slate. The resolver had no player-prop branch. `_polymarket_resolve_market` returns `None` for about ten distinct reasons, and the builder turns every one into the same token.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-22 — RULE: a preflight POLLER writes receipts; stopping the loop does not stop the child it already launched, and the newest receipt is the one the guard reads `[lane mlb-doubleheader-e2e, session 3692ff18]`

- **What happened:** I polled `deploy_preflight.py` in a loop while refresh-worker was busy, retargeted mid-wait (the deploy target moved from `0731d3ae` to `f15ffb80` as more of the lane landed), and stopped the old loop with TaskStop. The new loop returned `CLEAR: only infrastructure processes running` at 16:28:52Z for `f15ffb80`; the deploy was then REFUSED — `the CLEAR preflight is for 0731d3ae but this deploys f15ffb80`. The stopped loop's in-flight preflight child had finished AFTER mine and overwritten the receipt with the old target's verdict. The guard was right and the loop was the liar.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-22 — RULE: fixing a PRODUCER does not fix a surface until you know WHICH service builds it and WHERE that file lives; a board surface for a FUTURE date can be built inline on web from the git checkout `[lane ncaaf-kickoff-cache-staleness, session 3692ff18]`

- **The belief:** NCAAF compact cards showed "TBD" because the CFBD games cache went stale with no signal to refresh it. I fixed the staleness rule, deployed refresh-worker, and then -- when the user said not to wait for the daily run -- forced a regeneration with a temporary `SEASON_PROJECTION_REFRESH_INTERVAL_SECONDS=3600` plus a deploy. The generator relaunched (`interval_seconds=3600` in-process 19:52:18Z, NCAAF at ~19:54Z) and the board did not move: still 43 placeholder starts, 42 "TBD".
- *(evidence in `learnings_evidence.md`)*

## 2026-09-22 — RULE: a check built on an instrument INHERITS that instrument's divergence; before acting on "planned but never done", confirm the counter is produced by the path you are judging `[lane kalshi-spread-line-missing, session 236bd219]`

- **The rule going forward:** when a derived check says "X is planned and never happens", name the EMITTER of the counter before naming a cause, and ask whether that emitter runs the same code as the thing it describes. For dry-run counters the first suspect is the dry run. State the limitation wherever the check's output is written up.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-22 - RULE: an identity field that is USUALLY ABSENT is not an identity; count how often a key's id slot is actually populated on production data before trusting the key `[lane dh-grading-ledger-joins, session 3692ff18]`

- **What happened:** `live_gameline_ledger.record_key` began `(game_pk, ...)`, which reads as "the game is in the key". It is not: `game_pk` comes from the live-gameline projection and is never set on the segment-refusal path, so production 2026-09-22 had it on **25 of 132 records**. With the slot empty the key is `(None, segment, market, line, books_key)`, and `_moved` deduped ACROSS GAMES on it - 2026-09-20 had 13 keys spanning more than one game, ONE of them covering **14 games**. The doubleheader I was chasing was the small half of this: on 09-04 and 08-29 both halves even shared a real gamePk, because the index that produced it was keyed on the team pair.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-22 - RULE: "the published numbers did not move" is not evidence a data defect was harmless - a downstream dedupe can absorb it entirely, so go find the window where it was NOT absorbed `[lane dh-grading-ledger-joins, session 3692ff18]`

- **What happened:** the live-gameline ledger wrote a doubleheader's second odds event under the FIRST game's gamePk, with the first game's live state. Replaying `bucket_realised_performance.py` on the production rows for the published window (09-01..09-07, 28,627 rows) with and without those rows produced **byte-identical JSON**: the analysis's own `(bucket, game_pk)` dedupe had discarded all 69. Had I stopped there I would have reported "no impact". The window one week earlier (08-26..09-01, two doubleheaders instead of one) told the opposite story: 359 contaminated rows - 0.77% of the window - moved h2h calibration from 0.501 to 0.492, past the script's 3pp gate, and the analysis **refused the entire window** with `UNMEASURED: no market passed its gate`.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-22 - RULE: a `**[RELEASED ...]**` note does not release a lane claim, and a hand-rolled probe over a guard's parser is not the guard `[lane live-gameline-game-identity, session 3692ff18]`

- **What happened, twice in ten minutes.** (1) I told the user `live_gameline_join.py` belonged to lane `live-edge-basis`. It does not: that lane is CLOSED-VERIFIED since 2026-08-17 (`lanes.md:1367`), and the line I read (`lanes.md:52`) is a guarded-claims note ABOUT the closed lane. (2) I then "checked" with `lane_claims._claims(text)` and printed NONE. `_claims` returns a GENERATOR of `(lane, path)` pairs; I called `.items()` on it inside a comprehension, which yields nothing and raises nothing, so an empty result read as "unclaimed". The real holder was `accuracy-assessment-0914`, and only the lane-guard hook - the same parser, used correctly - said so. (3) After the user approved the take, I annotated the holder's `Files:` line `**[RELEASED ... ]**` and the guard blocked me AGAIN: the parser reads the literal PATH, so an annotation beside it changes nothing. The release needs the path REPLACED by prose, which is exactly what `lanes.md:711` had already done for the artifact publisher.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-22 - RULE: "Run now" on a scheduled task EXECUTES its side effects - a task whose prompt writes the ledger cannot be smoke-tested by running it, and the tool-approval it is usually run for may not exist `[no lane, session dc70079c]`

- **What happened:** asked to run a newly created scheduled reading "now, to pre-approve its tools". Its stored prompt ends by writing a findings file, appending a verdict to `deploys.md`, rewriting a `state_layer2.md` subject and pushing to `main`. Run on 09-22 it would have done all of that against ONE slate - **discharging an owed verification with a non-result** - and worse, the existence of `findings_2026-09-29_layer2_fee_net_out_of_sample.md` is the exact signal a LATER scheduled task (`layer2-score-v2-promotion-decision-1006`) keys on to decide whether the 09-29 reading ran. A "harmless test run" would have poisoned the chain it was meant to protect.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-22 - RULE: a pass that rewrites a CONTENDED ledger file must be REBUILT against the tip at push time, never rebased onto it - and `archive_released_lanes.py` writes CRLF on Windows `[no lane, session dc70079c]`

- **What happened, two traps in one pass** (archiving 21 CLOSED lane blocks out of `lanes.md`). **(1) Base drift.** The dry run and its verification ran against `origin/main` `875a9dbc`; by push time the tip was `eddcfb60` and the guard's claim count had moved **163 -> 165** because another session had appended. The commit was refused by an explicit base check, the whole pass was re-run against the new tip, and it landed first try. Pushing the pre-computed `lanes.md` would have silently reverted those two claims - the exact failure `archive_released_lanes.py`'s own docstring records happening before ("another session rewrote `lanes.md` between this session's two appends").
- *(evidence in `learnings_evidence.md`)*

## 2026-09-23 - RULE: a poller that pins `--baseline-read-at` stops meaning anything 15 minutes later, and a poller that only exits on CLEAR will then wait forever `[lane mlb-doubleheader-e2e, session 3692ff18]`

- **What happened:** waiting for a deploy window, I backgrounded a loop running the real `deploy_preflight` every 75s with `--baseline-read-at 2026-09-23T00:26:37Z` pinned. Preflight refuses a baseline older than 15 minutes, so from 00:41:37Z every cycle would have returned **NO_EXPECTATION instead of HOLD or CLEAR** -- and the loop exited only on `CLEAR`. It would have polled all night, printing a verdict that no longer described the thing I was waiting for. Caught it before that point only because I re-read my own command while thinking about something else.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-23 - RULE: `check_deploy_safety.py --drain` CANNOT be run from a developer machine, and `deploy_preflight` recommends it anyway `[lane mlb-doubleheader-e2e, session 3692ff18]`

- **What happened:** blocked by an in-flight job tree, I reached for the drain -- the mechanism `deploy_preflight`'s own HOLD text names as "the other way", and the right one, because it stops the worker starting NEW work and waits for the running job to finish instead of killing it. It cannot connect: `SYNDICATE_REFRESH_STATE_URL` is a Render-INTERNAL hostname (`redis.exceptions.ConnectionError: Error 11001 connecting to red-...:6379. getaddrinfo failed`), resolvable only inside Render's private network, and `ops.py` exposes no drain route, so there is no HTTP path either.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-23 - RULE: an artifact NAMED for a model's inputs is not evidence of its inputs until it reproduces that model's OWN output `[lane nfl-total-sum-direction-scale, session dae18452]`

- **What happened:** diagnosing why NFL totals over-disperse, I reconstructed the sim's per-team ratings from `smartsim2_ratings_2025_wk10.json` -- the artifact the generator writes beside the projections, named for exactly those ratings -- and regressed the SAME run's `margin_mean` on them. Slope +0.141, r = 0.215. Recomputing the identical quantity with `_centred_per_game` instead gave +0.521, r = 0.989. Same process, same output CSV, same 14 games; only the reconstruction of the INPUTS differed. The engine is deterministic in its ratings, so r = 0.989 is what a faithful reconstruction looks like and 0.215 is proof the file is not one (`#685`).
- *(evidence in `learnings_evidence.md`)*

## 2026-09-23 — OVERTURNED: "a past-date snapshot that returns data re-ran the scorer" — the board served a 22-day-old RETAINED build, so a missing cut stayed missing `[scheduled task live-gameline-accuracy-snapshot]`

- **What was believed:** that 2026-08-30/08-31 carry no `fresh_quotes_only` brier because the OBSERVER script predated the cut, and that re-requesting 08-30 would return exit 6 (`no data for date`) because the board no longer reaches back that far.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-23 — FORBIDDEN: writing a dated ledger file (`log/<date>.md`) with a whole-file write. READ IT FIRST AND APPEND -- another session's entry for today is already in it `[session 236bd219]`

- **The rule going forward:** every dated ledger file is SHARED and append-only by convention -- `log/<date>.md`, `deploys.md`, `leads.md`, `learnings.md`. Read the existing bytes, append, and gate the commit on **0 deletions** for that path. A whole-file write is only ever correct for a file you just created in the same command, and even then the existence check has to be in the write itself, not in your memory of it.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-23 — A SHARED TEST FIXTURE THAT OMITS A FIELD PRODUCTION ALWAYS SUPPLIES CAN HIDE AN ENTIRE DISPATCH

- **The rule going forward:** when a stub request/row fixture omits a field the production constructor REQUIRES, that is not a harmless default -- it is a different input class, and every test built on it is evidence about the wrong one. When adding a branch keyed on such a field, a sudden mass failure of old tests is the fixture confessing, not the change breaking. Check what the real constructor refuses before "fixing" the assertions.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-23 — RULE: a fix whose job is to EMIT a special character must not CONTAIN one — the first draft of the em-dash fix stored a literal U+2014 `[lane lane-open-emits-em-dash]`

- **What happened.** `scripts/lane_open.py` was written to stop lanes being opened with ASCII hyphens instead of U+2014 (two lanes in nineteen hours; `lane_claims.LANE_RE` requires the em-dash, and the session-start digest will not list a hyphen-headed lane as OPEN, so an arriving session sees no claim on its paths). The source was authored as `EM = "—"`. The authoring tool takes JSON arguments and **decoded the escape**, so the file on disk held the raw bytes `E2 80 94`. Measured with `od -An -c`: `E M   =   " 342 200 224 "`.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-23 — RULE: when a number cannot be explained, look at what the upstream response ALREADY contains before adding a call, a model, or a hypothesis `[lane polymarket-balance-detail, session 236bd219]`

- **The rule going forward:** before proposing a new call or a derived estimate for an unexplained number, print the FULL key set of the payload you already receive. Keep key names even when you do not keep values: a complete key list is what makes an ABSENCE provable, and it is the difference between "the venue does not tell us" and "we never looked".
- *(evidence in `learnings_evidence.md`)*

## 2026-09-23 — RULE: where a JOIN chose the row, the ORDER path must use the JOIN's own decoder. Four separate money-path defects this week were all "two implementations of one question, and the money side held the weaker one" `[lanes layer2-score-outcome-calibration / kalshi-spread-line-missing / polymarket-h2h-nickname-sides, session 236bd219]`

- **The rule going forward:** when the board join has already matched a row to a venue contract, the order path may not re-derive that match with its own logic. Import the join's decoder, and where the join applies a UNIQUENESS rule, carry the uniqueness too -- it is the safety property, not a detail. If the join's helper is private (`_parse_player_prop`, `_greater_than_line`), import it anyway and say why; a second implementation that can disagree with the one that chose the row is the defect.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-23 - FORBIDDEN: shipping a change because every point estimate favours it, when not one of them clears its own standard error `[lane smartsim2-total-nonlinearity, session dae18452]`

- **What happened:** `#686` removes a response the engine has and reality does not -- mechanism-correct, measured causally, defensible on first principles. The user's instruction was "ship it if both improve". Both DID improve on point estimate. Paired on 272 held-out games: the correction alone -0.076 +- 0.172 (t=-0.44), the re-fitted level -0.071 +- 0.072 (t=-0.99), both together -0.147 +- 0.185 (t=-0.79), better on **139 of 272 -- a coin flip**. And the bucket live in September, weeks 2-4, went the WRONG WAY at +0.531 +- 0.475. A literal reading of "both improve" said ship; the evidence said nothing had been shown.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-23 - RULE: build a ledger append from `git show HEAD:<file>`, not from the working copy, and gate it on `--numstat` `[lane smartsim2-total-nonlinearity, session dae18452]`

- **What happened:** appending two lines to `lanes.md` produced a **1,524 / 1,522** diff -- the whole file rewritten. `.syndicate/*.md` is STORED as LF and CHECKED OUT as CRLF, and an earlier session had rewritten the file, so the separator I had used successfully hours before was now wrong. Two spliced separators landed as bare LF inside a CRLF body, and git saw every line as changed.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-23 OVERTURNED: “lanes.md is over cap, so archive its CLOSED lane blocks” `[scheduled task archive-closed-lanes-0917, session 8a815e5b, no lane]`

- **RULE: size a cleanup job against the segment it can actually touch BEFORE scheduling it, and record that denominator in the job itself.** Four runs of 0 read as “the system is working” — and that reading was even true — while the file grew 4,366 B in 40 minutes from a segment the job was forbidden to touch. A repeatedly null job is evidence about its TARGET, not only about its subject.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-23 FORBIDDEN: calling a lane ABANDONED from its owner session's idleness alone `[same session]`

- **RULE: dormancy needs BOTH clocks — owner transcript idle AND `git blame` committer-time on the block's own lines.** This is the same failure `owner_liveness.py`'s last-modifier check was added for on 2026-09-18 (`fotmob-team-name-aliases`, closed by a session it never named); it was fixed there for CLOSED blocks and re-appeared the moment a new reader looked at OPEN ones. A header names who OPENED a lane, never who is writing it.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-23 - RULE: a monitor must compute its metric the SAME WAY as the baseline it is judged against, and the estimator must be written down next to the number `[lane nfl-total-sum-direction-scale, session dae18452]`

- **What happened:** a scheduled board check re-read a board whose artifact had NOT rebuilt -- byte-identical input, so the model column could not have moved -- and reported total SD **4.61** against a **4.47** baseline, margin 5.46 vs 5.29, and annotated the market as `2.59 (was 2.51)` as though the lines had moved. Nothing had. It used the SAMPLE standard deviation (ddof=1); the baseline used the POPULATION one. On n=16 that is exactly `sqrt(16/15)` = **3.28%**, and all four figures matched that factor to within 0.012.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-23 — A NOTATION THE LEDGER USES IS NOT A NOTATION THE PARSER HONOURS, AND ONLY THE PARSER DECIDES

- **The rule going forward:** when a guard reads human-written notation, the notation and the predicate are two halves that must be TESTED AGAINST EACH OTHER, the way this repo already insists for two guards that must agree. The cheap version is a census: for every claim, does it match at least one real file? That question takes one pass over `git ls-tree` and would have found all three the day they were written.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-24 FORBIDDEN: stating a deploy expectation as a COUNT when the population it counts can change size between the baseline and the verify `[lane mlb-live-gameline-venue-freshness, session 4ab694ed]`

- **The receipt would have recorded a success that is not one**, and it would have been believed, because a receipt is exactly the artefact a later session reads instead of re-deriving. `learnings.md` already carries "A rate, not a count" for findings; this extends it to the PREDICTION, which is worse, because a finding gets re-examined and a discharged expectation does not.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-24 FORBIDDEN: overriding your own local probe with a production number you have not tied to your change by TIME `[lane mlb-live-gameline-venue-freshness, session 4ab694ed]`

- **The clock.** The jump is at 01:51:37Z. The deploy went live at 02:06:45Z -- FIFTEEN MINUTES LATER. "Shortly after" was never verified against the deploy's own `finishedAt`.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-24 -- A WORKTREE DIFF IS EVIDENCE ABOUT ITS BASELINE, NOT ABOUT ITS AUTHOR: a FRESH diff from a LIVE session attributed 310 of upstream's own lines to it `[scheduled task archive-closed-lanes-0917, session ac238d51, no lane]`

- **The rule going forward, sharpened:** when a probe returns nothing, name the population it ran over BEFORE concluding anything -- and if that population is zero, the probe has measured nothing at all. A window has two sides; sampling one is not sampling the window.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-24 — A VENUE'S BALANCE STATE IS A SAMPLE, NOT A PROPERTY, AND I REPORTED ONE AS THE OTHER

- **The rule going forward:** a venue's cash, buying power, rate-limit state or dormancy is a SAMPLE with a timestamp, never a property to reason from. Say "at 16:01Z polymarket refused 4 of 4 on balance", never "polymarket refuses on balance". The difference decides whether a reader treats a deploy as inert.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-24 — A NARROWING FILTER THAT RETURNS THE WRONG SHAPE DOES NOT NARROW ITS PREDICATE, IT VOIDS IT — and a voided guard looks like the fix working spectacularly well `[lane archive-diff-baseline-echo, session ac238d51, caught pre-merge]`

- **What I was doing.** Inserting `drop_upstream_echoes()` into the lane-archive gate between `changed_lines_only()` and its consumer, to stop a stale-baseline worktree diff blocking CLOSED lanes. A pure narrowing change: drop some lines, keep the rest.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-24 - RULE: a hypothesis can be RIGHT about the defect and WRONG about it being the BOTTLENECK, and fixing a real-but-non-binding defect measures IDENTICALLY to shipping something broken `[lane mlb-live-gameline-venue-freshness, session 4ab694ed]`

- **The rule going forward:** when a change moves a symbol that tests PATCH, the gate is not "tests in the area". It is mechanical and cheap -- `grep -rl "<the old symbol>" tests/` gives the exact blast radius, and every hit either patches a live seam, patches nothing, or must be run. On this change that was 26 files; the honest subset was knowable in one command and I did not run it.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-24 — A FIX DEFINED RELATIVE TO A MOVING REFERENCE DECAYS AGAINST A FROZEN TARGET — `drop_upstream_echoes` narrows less against the same worktree every day, and nothing announces it `[session ac238d51, lanes archive-diff-baseline-echo / closed-lane-archive-20260924-1219]`

- **What I shipped and what I believed.** `173e42bc` added `drop_upstream_echoes()` to the lane-archive gate: discard a changed line whose text is already on `origin/main`, because a worktree that is BEHIND renders upstream's own lines as its own. Verified off != on, both directions, and it freed three blocks that had been stuck 19 h. I wrote it up as *the* answer to the stale-baseline mechanism.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-24 — `git checkout -- <path>` ON A STAGED CHANGE IS A SILENT NO-OP, AND A DESTRUCTIVE COMMAND THAT DOES NOTHING REPORTS EXACTLY LIKE ONE THAT WORKED `[session ac238d51]`

- **What happened.** Authorised to discard a redundant `.syndicate/deploys.md` diff in another session's worktree, I ran `git -C <wt> checkout -- .syndicate/deploys.md`. No output, exit 0. The file was still `438 0` against HEAD.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-24 FORBIDDEN: recording that a path MOVED LANES by spelling the path, inside a Files or Tests block. Prose ABOUT a path is indistinguishable from a claim OF it `[lane lane-claim-truncation-visible, session 4ab694ed]`

- "(`test_artifact_publisher.py` TAKEN 2026-09-24 by lane nhl-live-resim)" -- re-claimed the very file it was recording the release of, leaving it held by two lanes.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-24 - RULE: a guard's own recorded blast radius EXPIRES, and "fix the N it flags" is a hypothesis, not an instruction `[lane lane-claim-truncation-visible, session 4ab694ed]`

- **18 Files lines lose a path and 17 of them are OPEN lanes** -- one keeping 0 of 3, one keeping 6 of 23.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-24 RULE: an instrument that reads ONE channel cannot testify about a system with TWO. A 403 from the disk-gated route is not evidence about the Redis crossing `[lane nhl-live-resim, session 4ab694ed]`

- **What we believed:** that a trim of someone else's lane block was safe once the checks passed -- claim set identical as a set, zero orphaned indented lines, OPEN count unchanged, every moved line present verbatim in `lanes_history.md`, every kept line still present. Five blocks were trimmed on that basis.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-25 FORBIDDEN: a one-shot `replace(old, new, 1)` on a line that is not UNIQUE in the file. The edit lands on the first match, and the damage is the site you did NOT mean to touch `[lane nfl-live-resim-activation, session 4ab694ed]`

- *(evidence in `learnings_evidence.md`)*

## 2026-09-25 - RULE: an instrument that ALREADY FIRES before your change cannot verify it. Read its baseline, not its name `[lane nfl-live-resim-activation, session 4ab694ed]`

- *(evidence in `learnings_evidence.md`)*

## 2026-09-25 - RULE: a FETCH that failed must not be spelled like a RESULT that is empty, and a missing request header is a real cause `[lane nhl-live-resim, session 4ab694ed]`

- *(evidence in `learnings_evidence.md`)*

## 2026-09-25 - RULE: COUNT THE MATCHES BEFORE YOU WRITE. Four defects in one session, one shape `[lane nhl-live-resim, session 4ab694ed]`

- `s.replace(old, new, 1)` on a snapshot-read line that appears twice in `board_enrichment.py` -- landed in `attach_live_game_state_from_lens`, not the game-line join. The fix never shipped AND a working reader was repointed at a file it cannot parse. **Deployed.**
- *(evidence in `learnings_evidence.md`)*

## 2026-09-25 - RULE: "deploy live" and "artifact rebuilt" are DIFFERENT EVENTS when producer and consumer are different services `[lane nhl-live-resim, session 4ab694ed]`

- *(evidence in `learnings_evidence.md`)*

## 2026-09-25 FORBIDDEN: gating a deploy's verification on a `print()` inside a step the orchestrator runs as a SUBPROCESS. Production cannot hear it `[lane nhl-board-rows-missing, session 4ab694ed]`

- **What we believed:** that my borrow of `doubleheader.py` from an idle lane had moved the claim, because the script asserted on the claim set before pushing and the assertion passed.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-25 - RULE: a CADENCE MARKER records that a sport was LISTED, not that its producer ran. Never read one as evidence of work `[lane nhl-board-rows-missing, session 4ab694ed]`

- *(evidence in `learnings_evidence.md`)*

## 2026-09-25 - RULE: a SAMPLE or a DERIVED LIST is not the population, and "never" is a claim about the population `[lane nhl-board-rows-missing, session 4ab694ed]`

- **What we believed:** that a re-check showing game 1 "LIVE (Top 1, 0-0)" had observed the pregame-to-live transition -- the one state the doubleheader join had never been tested in. A scheduled run reported exactly that, and it was the headline of its own log entry.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-25 RULE: a pairing that demands EQUAL COUNTS from two feeds breaks when either feed retires members on its own schedule. Test it across the lifecycle, not at one instant `[no lane, scheduled dh-rail-recheck-0925-live]`

- **What was believed:** `42b9be30`'s ordinal pairing was verified at 18:07Z with both games pregame. At 19:51Z a PASS with game 1 "LIVE" was read as surviving the transition. That run was already withdrawn: warmup, not in-play.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-25 - a CONFIGURABLE default read out of the source is not a production value

- FORBIDDEN: quoting a code default as the production setting for anything an env var can override, without reading the environment.

- *(evidence in `learnings_evidence.md`)*

## 2026-09-25 - a rate from ONE observation, in a window containing a restart

- **What I believed:** that a board group's state (`hasLive`/`allFinal`, from its rows' `market_state`) tracks its game, so a timeless doubleheader group could be matched to the chip in the same state.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-28 — AN ALLOWLIST IS AN ELIGIBILITY CHECK, NOT A TRANSPORT. And a check that answers about the wrong object is worse than one that fails.

- **FORBIDDEN: reporting a path "retrievable" because it is in `HOT_ARTIFACT_PATTERNS`.** The allowlist is read on THREE sides — the worker before it sends, web on ingest, web on stream/export — and **none of them moves a file.** An artifact written on refresh-worker (which serves no HTTP) is not reachable from web (which serves the stream route off WEB's disk) until something explicitly PUBLISHES it. Allowlisting alone turns the retrieval from **403 into 404**, which is the worse failure: 403 says "not permitted", 404 says "the capture never happened". Measured: a capture family was allowlisted, deployed, and one verification away from being reported as done. **Before calling an artifact retrievable, name the line of code that SENDS it.**
- *(evidence in `learnings_evidence.md`)*

## 2026-09-28 (session 249f998b, lane mlb-prop-grading-player-match) - a VOID count's size is not evidence of a join failure

- **What was believed:** 9,728 MLB `prop_player_not_in_boxscore` rows against ~156k graded were "too large to be DNPs alone", so they had to be player-name match misses.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-28 (session f9c8d1b9, lane live-props-model-probability) - A producer test that asserts its OWN field proves nothing about the reader

- **What happened.** `#539` (2026-08-23) priced soccer's one-sided live props and its eleven tests asserted `edge_vs_modelled_fair_pct` on the projection. The board reads that number through `layer2_board._modelled_fair_edge_for`, which ALSO requires `modelled_fair_side` -- a companion field only the pregame sweep wrote. Every test was green for five weeks while the path delivered 0 of 3,547 edges to the board and the scorecard.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-28 — an "unreproducible CI flake" was a production bug: never `print` inside a signal handler (session 2aff0397)

- *(evidence in `learnings_evidence.md`)*

## 2026-09-28 (session 273dc243, lane nfl-live-gameline-full-rows) - "VERIFIED" on a slate where nothing priced verified only the refusal path

- **What happened.** `nfl-live-resim-activation` closed its goal on `sources_seen {pregame: 16}` -- every lane a refusal. That reading proves refusals are rejected; it cannot see the PRICED lane, which carried snake-case fields the join never reads, and named games by tri-code where the grid uses full names. On 09-27 the re-sim priced 1-4 games per tick for ten hours and the join indexed zero. The unit fixtures named games "Dallas Cowboys" -- the cheaper path production never takes. Same class as the entry above, second instance the same day.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-28 (session acb76ba7) - Two readers of one fact must read the SAME copy; fixing one reader's location can blind the other

- **Rule:** before moving where a fact is WRITTEN, enumerate every READER and the root each one resolves (grep the marker name in `.claude/hooks/`). Make readers resolve through ONE shared lookup, or import the writer's map (`_LIVE_GAMELINE_SNAPSHOT_PATHS`), never a parallel copy. A test must cover the case where the copies DISAGREE, not only where one is missing.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-28 (session acb76ba7) - A half-removed session worktree is held open by the Bash tool's own cwd, not by a leftover process

- **Rule:** before `close`, move EVERY shell that ever `cd`'d into the worktree back out: Bash, PowerShell, and the harness directory. Only a checked `--force` may clean up a half-removed tree: the folder is empty, `git worktree list` no longer shows it, and the branch has 0 commits beyond `origin/main`.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-28 (session f9c8d1b9, lane live-props-model-probability) - Interval coverage is not calibration; and sample on the clock the product prices on

- **What happened.** I shipped per-market WNBA residual tables and widened rebounds/assists to a line grid on the strength of 90%-band coverage of 91.5-91.8% OUT OF SAMPLE. An hour later, line-level calibration -- predicted vs observed P(final >= line) over the exact ladder the lens publishes -- showed rebounds overstating overs by 18.5 pp and threes by 18.7 pp even in-season. Coverage was true and irrelevant: a band can hold 90% of finals while every over near the centre is mispriced, because the distribution is skewed and one sigma per bucket ignores player scale. Separately, the grader sampled each player right AFTER their own event, which inflates the pace the projection extrapolates; production prices on a clock tick.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-28 — A POPULATION IS PART OF A CONSTANT. Four findings reversed when the population changed, and three retractions came from measuring the wrong pair.

- **FORBIDDEN: selecting a constant on one population and shipping it to another.** A spread-shrinkage `k=3` was selected on 132,136 rows with a genuine convex minimum and a -0.003479 held-out Brier gain. On the 16,967 rows the BOARD ACTUALLY QUOTES it was monotonically HARMFUL, and it made starters NARROWER -- the opposite of the defect. The league prior it shrank toward had a median `rushing_yards` sd of 10.2 computed across 564 "rushers" who are mostly marginal, against a workhorse's ~25. **State the population next to every fitted constant, and re-run the selection on the population that will consume it.**
- *(evidence in `learnings_evidence.md`)*

## 2026-09-28 (session 2aff0397, lane nfl-game-day-injuries) - A flag is set on the service whose LOOP reads it; a file is read on the service whose DISK holds it

- The rule going forward: before telling anyone where to set a flag, grep for the function that reads it and name the SERVICE whose entrypoint reaches that function. Before calling an input "disk-backed", name the service that WRITES it and the service that READS it; if they differ, the file must be allowlisted in `HOT_ARTIFACT_PATTERNS` AND published by its producer, with a test that fnmatches the reader's pull pattern.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-28 — A LANE BLOCK AND THE DEPLOY LEDGER DISAGREED FOR A DAY, AND THE LEDGER WAS RIGHT. Plus: a verdict is a claim and ages like one.

- **FORBIDDEN: trusting a lane block's status over `deploys.md` when they disagree.** `worker-memory-heartbeat` read "GOAL: NOT MET -- the code is LANDED and DELIBERATELY NOT DEPLOYED" for a full day while `deploys.md` recorded `87ce81d7` deployed and VERIFIED, with both halves of that lane's own Verification satisfied (181 samples, 0 of 180 over the preflight limit, CLEAR x3). **A lane saying "not deployed" about something deployed and verified is worse than a stale OPEN lane: it is a FALSE NEGATIVE sitting exactly where the next session looks first.** The deploy ledger is written at the moment of measurement; a lane block is written from memory afterwards. When they conflict, the ledger wins and the block gets corrected.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-28 (session f9c8d1b9, lane live-props-model-probability) - A variant chosen in-season can fail the playoff holdout for a reason outside the variant

- **What happened.** Threes rate shrinkage toward pregame, selected on August, cut the worst line-level gap to 3.4 pp there and went to 13.3 pp on held-out September (playoffs) -- worse than the live model -- while Brier skill improved. The shrinkage was fine; the thing it shrank TOWARD, the pregame threes expectation, overshoots by 18% in the playoffs against 8% in-season. Every earlier count-model change today passed the same holdout; this one leaned harder on the pregame anchor and was the only one to fail.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-28 FORBIDDEN: telling the user a market is "not scored" off a PRINTED LABEL without reading the served payload's keys `[lane gameline-spread-total-scoring, session 3b474634]`

- **What happened.** The nightly snapshot printed `spreads=399(refused) totals=372(refused)`, and I reported to the user that totals and spreads were not scored. They had been scored on every build since scorer contract 3 (2026-09-08), under `live_gameline_score.point_forecast`, and retained in history since 09-24. The label predated contract 3: it meant "not in the Brier", and nothing updated it when a second scoring rule shipped.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-28 FORBIDDEN: flagging a delegated lane's work as DRIFT without reading the consent and user-request lines first `[lane gameline-spread-total-scoring, session 3b474634]`

- **What happened.** Polling lane `live-props-model-probability`, I reported to the user that it had drifted into four hours of WNBA model tuning. Every step was USER-REQUESTED in that session ("widen WNBA rebounds and assists too", "build the player-scaled spread model", ... "Ship it now"), and each cross-lane write was recorded with consent in `layer2-triad-alignment`'s block. I judged from the commit subjects against the lane's written Goal.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-28 FORBIDDEN: writing a test from the same mental model as the code, on a fixture you invented rather than one read from production `[lane nhl-board-row-date-mismatch, session 4ab694ed]`

- **What happened.** `fae9aab8` compared a predictions row's `date` to the requested date with `str(...)[:10]`. I wrote `test_a_timestamp_shaped_date_compares_on_its_date_part` to cover timestamps — and it **asserted the bug**, pinning the truncation as correct behaviour. It passed while production dropped real games, and I shipped it to two services.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-28 FORBIDDEN: admitting a sport to a capability set without checking that its producer stamps the field the consumer gates on `[lane nfl-live-resim-activation, session 4ab694ed]`

- **What happened.** `LIVE_GAME_STATE_JOIN sport=nfl supported=False reason="no live status source wired for nfl"` while PHI @ CHI was in Q2. The pieces looked present: `scripts/poll_nfl_live_state.py`, `syndicate/features/nfl/live_game_state.py`, and the ESPN fetcher already listing `nfl`. Adding `"nfl"` to `_LIVE_GAME_STATE_SPORTS` with a capture reader would have looked complete and done **nothing**.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-28 FORBIDDEN: using `deploy_preflight.py` as a status probe, and trusting its HOLD text's window figure `[lane nhl-board-row-date-mismatch, session 4ab694ed]`

- **Two separate defects in the same tool, both measured.**
- *(evidence in `learnings_evidence.md`)*

## 2026-09-29 FORBIDDEN: attributing a CAUSE to a coverage pattern before reading the artifact's `generated_at` against the state of the world it describes `[lane layer2-triad-alignment, session 4ab694ed]`

- **What happened.** `nfl_prop_projections_2026_wk3.json` held 276 rows where a known-healthy week-1 artifact had 966. The shape looked diagnostic: 7 of 32 teams absent, 6 games with exactly ONE side present, 1 game with NEITHER, seven more teams at a single player, and 41% of all rows on two teams. I reasoned that a truncated run leaves CONTIGUOUS games unfinished and this does not, therefore it must be a per-team data dependency failing — and named `rating_source=nflverse_pbp_epa_rolling` as the likely culprit. I wrote that into the ledger and proposed a row-count ratchet guard.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-29 FORBIDDEN: trusting a metric's NAME for what it compares against — "real market hit rate" never read a price, and its headline was the majority-class null `[lane nfl-live-resim-activation, session 4ab694ed]`

- **What happened.** `scripts/backtest_nfl_props.py` has a section titled `SECTION 3 -- REAL MARKET HIT RATE (wherever a real quoted line exists)`, persisted as `section_3_real_market_hit_rate`. It reported `anytime_td: n=6583, hit_rate 0.774, brier 0.1674`. I read that as evidence the model performs against the market. It is neither of those things.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-29 FORBIDDEN: reading "production has this artifact" as "a publisher put it there" — feed_live is on production because it is GIT-TRACKED, and `is_hot()` is False for the very files that are already there `[lane mlb-live-prop-grader, session 4ab694ed]`

- **What happened.** `/api/ops/artifacts/export?pattern=*feed_live*` returns `count=146` on production, so I planned to publish 472 more the same way. `/api/ops/artifacts/publish` returned **403 `relative_path is not an allowed hot artifact`**. feed_live matches none of the 200 `HOT_ARTIFACT_PATTERNS`.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-29 STANDING: claimed edge running ANTI-correlated with realised return is now measured in TWO sports — treat "ROI falls as the EV threshold rises" as the primary read, not any single threshold's CI `[lane mlb-live-prop-grader, session 4ab694ed]`

- **What was measured.** MLB LIVE prop probabilities graded against the price they were served at (584 rows, 7 dates): ROI by nested EV threshold ran **EV>0.00 +0.0060, >0.05 -0.0044, >0.10 -0.0200, >0.20 -0.1224**. Not one of those CIs clears zero on its own — n is small and the odds average 1.94 — so read individually the honest verdict on each is "indistinguishable from zero", and the study would report NOTHING.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-29 FORBIDDEN: checking production for ONE property and then diagnosing a DIFFERENT property from the local checkout — I verified the file COUNT against production and still reported a 3.5-month silent regression that was a mirror gap `[lane mlb-live-prop-grader, session 4ab694ed]`

- **What happened.** `live_lens_report_*.json` files on disk showed `liveProps` populated on 7 dates (2026-06-01..06-11) and **zero** on ~70 later dates, including dates carrying 10-14 live games. I reported that as a producer regression silent since 2026-06-11, and said so to the user before pulling anything.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-30: a task QUEUED with spawn_task can be landed by ANOTHER session while you are still building it, so re-fetch `main` before opening the PR

- **What happened.** Session 157058fe queued "Fix Windows process-liveness checks" as a suggested-task card. The user started that card, which launched a separate session, and then asked session 157058fe to start the same task. Both sessions built the same fix in parallel. The other session's `67b5f471` reached `main` first and covered more ground: six sites, the two lane-held files (with cross-lane notes), and a zombie-parse fix. PR #119 then hit add/add conflicts on every file and was closed as superseded. This cost about 40 minutes of duplicated work and an extra lane block.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-30: an in-process test of a CLI function does not test the CLI, so run the entrypoint once

- The rule going forward: in any branch that decides unknown vs zero, (1) do not coalesce before the check; (2) enumerate the sentinel matrix against the KEY, not the container: absent, `None`, `""`, `[]`, non-numeric, and a real `0`, which must still read as zero; (3) do not state coverage in a hand-off until that matrix has run.
- *(evidence in `learnings_evidence.md`)*

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

**The second, worse half — AND I NAMED ITS CAUSE WRONG `[corrected 2026-10-09,
lane ledger-tools-byte-safe-io]`.** A peer's line inside the archived
`layer2-board-ui-redesign` block was SPLIT at `lanes.md`'s single mid-line bare CR
— byte for byte the failure `74da0acd` repaired after an earlier rewrite, and what
the 10-06 standing rule forbids. I blamed the text-mode WRITE. It was the **READ**:
`pathlib.read_text()` and a bare `open()` use UNIVERSAL NEWLINES, which maps a lone
CR to LF before any processing runs, so the line was already two lines in memory.
Measured: on-disk `a CR b LF c LF` reads back as `a LF b LF c LF`, and with
`newline=""` as `a CR b LF c LF`. The text-mode write is a SEPARATE defect — it
churned the line endings. Both are now fixed behind `scripts/ledger_io.py`.
A lone CR mid-line is a CHARACTER, not a line ending, and must survive.

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

## 2026-10-10 -- A rising walk-forward correction is not a drifting model: read the residual's own trend first `[session e0a3e383]`

- **Measured:** an NBA totals calibration term rose 7.3 → 15 (clipped) across the season. It read as "the model
  drifts", and a fix was pre-registered on that premise.
- The raw residual's own trend was −0.60 per 30 days [−2.00, +1.00]: none. The rise was a short early-season window
  plus the ±15 clip binding.
- The real cause was a constant LEVEL: −5.1 from a double-counted defense and −8.5 from injury penalties.
- **Rule:** before attributing a moving correction to drift, regress the uncorrected residual on date with a
  date-clustered CI. A fitted term's path also carries its window and its clip.

## 2026-10-10 — RULE: measure a sim input's reachability on a PREGAME call, never on a completed game; a finished game hands the sim lookups (ESPN box -> name/id map) that a pregame call does not have `[lane basketball-native-live-state, session 82bc583a]`
- **What we believed:** the native `rotation_stints_history` reaches the NBA smart sim. deploys.md 2026-10-09 18:56:24Z recorded "Reachability (off != on) ... MET" on PHI v MEM 2026-03-10: ON applied, 49-lineup pool; OFF `no_rotation_stints_history`.
- **What was actually true:**
  - That game was COMPLETED. `_espn_name_to_id_map_for_game_local` read its ESPN box and mapped 26 players.
  - For a PREGAME game there is no box. The only other fallback read the vendored `pbp_espn_history.csv`, and the map came back EMPTY (2026-10-10 TOR v LAC 0, ATL v IND 0).
  - Every production pregame call would have refused with `no_espn_name_map`, and the "MET" described a path production never takes.
  - (NBA preseason slates also admit no history by design, lane nba-season-phase. That is a second, intended gate the probe never met either.)
- **How we found out:** lane nba-sim-team-adj-473 ran fresh NBA sims and messaged that `lineup_pools` was 0/4. I verified the empty map on the fleet myself, fixed it with a native fallback from `rotation_stints/player_checks_*.csv` (45e03ae2), and re-measured with the box lookup FORCED EMPTY: WNBA NYL 13 mapped, applied, 152 lineups (deploys.md 2026-10-10 14:25:14Z).
- **Technical failure:** an input's id-join depended on an artifact (the game's own box) that exists only after the game.
- **Epistemic failure:** I chose a COMPLETED game for the probe because the probe needed a roster, and the completed game supplied one. The probe built its inputs from the very artifact production lacks. Memory `[[feedback_confirm_the_code_ran]]` and learnings 2026-10-05 ("a verification is only as good as the population it ran on") both already said this, and I still did it. A rule I had read was not enough.
- **The rule going forward:** a reachability reading for a pregame model input is taken with the post-game lookups forced off (here `_espn_event_id_for_matchup_local -> ""`), or on a live-dated pregame slate. Its record names which lookups the probe could see.
- **Proposed check, not prose:** P1's `scripts/basketball_sim_input_checklist.py` should read PRODUCTION `smart_sim_<date>_*.json` on the fleet and report the `rotation_minutes.{home,away}.reason` distribution. It should exit non-zero when the history file exists and 0% of regular-season sims applied it. That reads what production did, which no probe can fake.
- **Also this lane, smaller (each recorded where it happened):**
  - **A process kill matched other sessions' work.** I killed my leftover pytest by a command-line fragment (`pytest` + `no:cacheprovider`), and it also killed P1's and another session's test runs. Match your OWN pid, or a unique token in your own argv, never a shared flag.
  - **I described `up` as light.** On a running fleet `up` refuses until `down`, so it is a full restart. Read `cmd_up` before offering it.
- **Cost:** about 20 hours with a false "MET" on the ledger (2026-10-09 18:56Z -> 2026-10-10 14:25Z fix). No production harm: preseason NBA slates admit no history anyway, and WNBA sims ran before the backfill. Two other sessions' test runs were interrupted.

## 2026-10-10 -- A config "resolves" check proves the resolver, not the run: read the run's own recorded config, PER PROFILE `[lane mlb-game-profile-pitch-config]`
**The miss.** Two MLB ships (combined calibration 10-07, HR 1.5 10-08) were V1-verified by calling `_apply_forward_tuning_defaults` and confirming it points at the forward pitch file.
- Production never relied on that default for game lines. The multi-profile runner passes the game-ROI profile an EXPLICIT `--pitch-model-overrides` pointing at a file that never existed.
- A missing path loads as `{}`, and the explicit flag suppresses the default.
- So game lines, and every board prop number read from `daily/sims`, ran class defaults all season. The props profiles did get the file.
- The evidence was in the run's own `daily/snapshots/<d>/meta.json` (`cfg_kwargs.pitch_model_overrides: {}`) the whole time.
**Rule.**
- Verify a config ship against the `cfg_kwargs` the production RUN recorded, for EACH profile/output dir that serves a surface.
- A V2 replay must include an arm for "the config the run actually used", not only new-vs-old of the intended path.
- A loader that maps a missing file to `{}` must be paired with a test that every configured path exists.

## 2026-10-10 — A HALF-FIX LOOKS EXACTLY LIKE A FIX: PIN BOTH ENDS OF AN IO PAIR `[lane ledger-tools-byte-safe-io, session 4ab694ed, 5dfddf6e]`

**Rule.** When a defect involves reading AND writing a file, fix and test both
ends. A tool that pins only the write still corrupts on the read, and the symptom
is identical, so the half-fix reads as done.

**Why, measured.** `trim_lane_narrative.py` already wrote with `newline=LF` — the
write half of the bare-CR problem, correctly pinned — and still read with a bare
`open()`, i.e. universal newlines, which maps a lone CR to LF. It would have split
a peer's line exactly like the three tools that had neither end pinned. I would
have shipped the same half-fix: my first instinct was "the tools write in text
mode", and the write is the half that is easy to see because it churns a visible
4MB diff. The read is the half that silently loses a character.

**How to apply.** Audit the PAIR across every tool in a family before fixing one.
Here: 4 tools, all 4 unsafe on read, 3 also unsafe on write — one shared helper at
the choke point, not four local patches. The audit table is the deliverable; a
per-tool fix would have left `trim_lane_narrative.py` looking already-correct.

**A SECOND, UNRELATED TRAP THIS EXPOSED — naming a sibling script in a docstring
can change deploy classification.** `scripts/pending_deploys.py` builds a
TRANSITIVE closure of script basenames NAMED anywhere in runtime-reachable text,
and demotes a `scripts/` path to "owns no service" only when nothing names it.
My new helper's docstring named two sibling tools; that pulled them into the
closure and, through one of their texts, a third — re-promoting pure ledger tooling
to runtime code. `tests/test_pending_deploys_runtime.py::test_pure_tooling_is_demoted`
caught it. Fix was prose, not code: name siblings by ROLE. Verified by comparing
closure membership against HEAD, which also showed `archive_released_lanes` was
already in the closure before my change — pre-existing, not mine.
**Prose in a docstring is an input to a deploy heuristic here.**

## 2026-10-10 OVERTURNED: "only the vendored orchestrator LOOP runs; the data computation is Syndicate's" (basketball_sim_engine_reference.md Sec0) -- lane basketball-native-orchestrator

**The belief:** Sec0 said the ~20 monkeypatched helpers meant only `simulate_smart_game`'s own loop was vendored code running in production.

**What the P6 closure showed:** the loop called OTHER vendored modules that nobody had patched.
- `connected_game._apply_lineup_teammate_effects_to_priors` APPLIED in production WNBA. Measured 10-09 LVA@GSV: 20 nudges.
- `boxscores` made ESPN scoreboard and summary HTTP calls with an on-disk cache.
- `prob_calibration` read calibration files.
- The bridge also imported the vendored team-advanced-stats BUILDERS.

These read the VENDORED `config.paths`, which the bridge never pinned. It matched the bridge's root only because the fleet env sets `NBA/WNBA_BETTING_DATA_ROOT`. On a machine without that env, the same code reads `vendor/<pkg>_repo/data`.

**Rule:** "we replaced its helpers" is not "its data path is ours". Compute the executed closure by AST from the entrypoint, cutting only at the names actually replaced. List every module it reaches, and every global the reached code reads (`paths`, `LEAGUE`, module caches). An unpinned global in a module you never patched is an input you do not own.

## 2026-10-10 -- Feeding a previously-NEUTRAL input switches on every consumer's handling of it, including the wrong ones `[lane nba-sim-team-adj-473, session eb2ba139]`
- **What happened.** #473 fed real NBA team ratings where every consumer had only ever seen neutral values. Two consumers were wrong in ways a neutral input hid: the engine stacked team quality on a 95%-market-anchored target (counted twice), and the quarter model subtracted the opponent's def rating with the wrong sign on points-derived ratings. As built, the published margin moved 4.2 pts/game and |pub - market| went 1.83 -> 4.57 (22 same-seed games); the checklist said the input was "populated" and passed.
- **Rule.** Before shipping an unfed-input fix, A/B the PUBLISHED output (not just the input checklist) on the same games and seed, and enumerate every consumer of the field (grep the reader, not the writer: here `_load_adv_map` fed pace/def to a second model). A consumer that was "calibrated" while the input was constant was calibrated to nothing. Same family as mechanism vs estimator (`model_engine_standard.md`).

## 2026-10-10 RULE: a board-card fix is live only when EVERY date's stored shortlist has been rewritten -- not at the first post-deploy save
**Evidence (lane board-history-charts):** the corners guard in `layer2_board._chart_columns` was loaded at 15:39:49Z. The served board read 285 -> 115 -> 103 -> 0 corners rows with team history, over 35 minutes.
- Today's shortlist, written 15:56:54Z by the new worker, was 0/182 from its first write.
- The page also merges the next days' stored shortlists. The 10-11 one had been written at 14:18:03Z by the OLD code (183/183) and was only rewritten at 16:06:41Z.
- The first post-deploy STATE_PERSIST therefore served a mix of new-code and old-code cards.
**How to apply:**
- After a card-level change, read `written_at` of EVERY date in the board horizon (`read_layer2_shortlist(<date>)`, with the web's state env keys) before measuring.
- Gate the measurement on the newest one being after the deploy AND a STATE_PERSIST finishing after that.
- A partial reading in between is a mixed board, not a partial fix. Two more traps in the same hour:
  - An Ask probe built from a shortlist fetched before the last rebuild matches no row, because resolve_board_row is exact-or-nothing, and reads as "broken".
  - A probe that does not reproduce the button's payload (nested `context`, "What's the case for and against ..." wording) is routed out_of_scope.

## 2026-10-12 -- A calibration that improves Brier can make the BETS worse: on a pricing seam, shrink toward the market, not toward 0.5 `[lane mlb-probability-calibration]`
**The miss.** A symmetric affine-logit fitted out of sample on MLB passed the pre-registered Brier rule in 8 of 13 markets.
- The same curves made the ROI of EV>0 bets at the book's prices WORSE in 6 of those 8: full total -7.6% -> -12.7%, K -10.3% -> -14.3%.
- Mechanism: slopes near 0 flatten p toward 0.5, and the seam re-differences against the fair, so the residual edge becomes (0.5 - fair). That favours plus-money sides wherever the market is not 50/50.
**Rule.**
- A calibration that feeds an edge must be judged on the EDGE it produces (ROI of the bets it selects, at real prices) as well as on Brier.
- Prefer a market-ward form (`p' = fair + w*(p - fair)`): it scales the edge and never flips its side.
- A fitted w near 0 is a finding about the model's information content, not a calibration to celebrate.

## 2026-10-12 — A GUARD'S OWN DETECTOR MUST RECOGNISE THE FIX IT ENFORCES `[lane ledger-writer-byte-safety-guard, session 4ab694ed, 84dec600]`

**Rule.** When you write a test that enforces "use helper X", its detector has to
know what a call to X looks like. Otherwise the files that already comply are
classified as out-of-scope and stop being checked — the guard goes quiet exactly
where it was supposed to be loudest.

**Why, measured.** The first cut of `tests/test_ledger_writers_byte_safe.py`
decided "does this module write a ledger doc?" by searching for `write_text(`,
`write_bytes(` and `open(...,"w")`. It did not search for `write_ledger(`, the
helper every converted tool now uses. So all eight converted tools scored as PURE
READERS, and the guard skipped their reads — the exact files it had just been
written to protect. A second control now pins this:
`_writes_a_ledger("write_ledger(LANES, text, eol)")` must be true.

**Second instance in the same guard.** Its first cut also flagged
`check_trimmed_contracts.py`, a pure reader that writes nothing and therefore
cannot corrupt anything. A guard whose name says "rewrite" must not fail on reads
in non-writers, or it accumulates allowlist entries for harmless files and the
allowlist becomes the thing people edit instead of the code.

**How to apply.** For any new guard, write two controls before trusting it: one
asserting it SEES a compliant file (so scope cannot silently collapse) and one
asserting it FIRES on the pre-fix tree. This guard has both, plus a third
asserting every allowlisted file still uses the mechanism its allowlist entry
claims — an allowlist entry that names a mechanism can be checked; a waiver
cannot.

**And a null result worth stating as one.** Run against 35 later peer commits the
guard reported 26 passed, but its candidate set is 15 scripts and NONE of the 4
new peer scripts touch a ledger doc. So that green says the 15 pre-existing
candidates are still clean; it does not say the guard caught anything new. The
frame could not have been non-null.

## 2026-10-12 REPEAT of the 2026-10-06 FORBIDDEN (text-mode ledger rewrite), and a committed merge marker found by the same check `[lane basketball-props-models-native, session 2d413211]`

- **The repeat.** In my 2026-10-09 rebase-conflict fix (commit 984312a8), and in later one-line lane edits, I read `lanes.md` with Python TEXT mode (`open(p, encoding=...)`). Two lone CR bytes in other lanes' lines became line breaks:
  - games-rail-full-detail: its 10-10 00:10Z verdict;
  - basketball-native-live-state: an NCAAB PROGRESS line, which gained a blank line.
  The whole file also went CRLF -> LF. That diff was 1,952+/1,949-, and it was the only sign. I gated on "my block replaced" and never on numstat.
- **Found today** because a byte-exact edit showed 1/1 while my text-mode version of the same edit showed 8 changed lines. Repair: the NCAAB line was rejoined byte-exactly. The games-rail lane had already replaced its verdict head, so the detached tail is now an orphan in its block; I told its owner (session d4409ac4) rather than edit their block.
- **Second finding, same check:** `d93bfc7e` committed UNRESOLVED merge markers into lanes.md. Both sides were pure additions, with the shared `- Blocked by: none` factored out. `check_lane_invariants` then reported "not a ledger", and the markers hid a new lane's claims on the orchestrator package. Resolved in 05a0be1c by keeping both sides and restoring the factored line to each block.
- **How to apply:**
  1. Every ledger edit is `read_bytes()` / `split(b"\n")` / `write_bytes()`, including conflict resolution.
  2. Before every ledger commit, `git diff --cached --numstat <file>` must equal the lines you meant to touch.
  3. After a rebase that touched a ledger, grep `origin/main`'s copy for `^<<<<<<< |^>>>>>>> `.

## 2026-10-12 -- A replay builder that deletes files to prevent leakage also deletes production inputs: probe the engine boundary for every consumed input `[session e0a3e383]`

- **Measured:** the NBA as-of replay scratch builder removed dated files and a REMOVE_ALWAYS list, to stop
  all-history artifacts leaking future games. It thereby silently removed two inputs that production feeds:
  - ESPN box starters (player_checks, a dated sub-directory): starters 0/18;
  - rotation_stints_history (lineup pools): no_rotation_stints_history on every side.
- A pre-registered fit (score_effect_k) had been chosen on those replays.
- Fixed by as-of truncation (date < slate) instead of deletion.
- **Rule:**
  - Before any fit on replays, probe at the engine boundary that each consumed input is POPULATED in the replay as in
    production (team_adj, starters, lineup pools...). Do not trust the builder's file list.
  - Prefer as-of truncation to deletion. For a fitted all-history artifact that cannot be truncated
    (lineup_teammate_effects), record it as a stated replay-vs-production difference.

## 2026-10-12 — BACKTICKS IN A DOUBLE-QUOTED SHELL ARGUMENT EXECUTE, AND SILENTLY DELETE THE WORD FROM A LEDGER WRITE `[lane layer2-out-gate-fixture-game-field, session 4ab694ed]`

**Rule.** Never put a backtick inside a double-quoted shell argument that writes to
the ledger. `lane_open.py --goal "... the `game` field ..."` runs `game` as a
command and substitutes its (empty) output, so the lane block is written with the
word MISSING. Use single quotes for the whole argument, or build the backtick with
`chr(96)` from Python.

**Why, measured.** Opening a lane this way printed four `bash: game: command not
found` lines and still exited 0 — `lane_open.py` wrote the block, and the Goal and
Falsification lines read *"giving the grid fixture the  field real rows carry"* and
*"the missing field is not  and the premise is wrong"*. The ledger recorded a goal
with its subject deleted. Repaired by hand the same session.

**Why this is not the existing backtick rule.** The other backtick entries in this
file are about `lane_claims._paths_in` treating a backticked token as a CLAIM, and
about `_mask_backticked` doing the opposite job. Those concern how the ledger is
PARSED. This one is about the ledger being WRITTEN wrong before any parser sees it,
and the symptom is a missing word rather than an extra claim.

**How to apply.** The failure is loud on stderr and invisible in the file, so the
check is to read back what was written, not to watch the command. Any `lane_open.py`
/ `lead` / commit-message invocation that carries markdown backticks is exposed;
prefer single-quoted arguments there.

## 2026-10-12 -- A failure reason belongs to the diag it came from: name the diag KEY before attributing a reason to a feature `[session ee14e4ec / 7693274b, lane nba-pregame-lineup-pools]`

- **Overturned belief:** "NBA lineup pools 0/4: `no_espn_id_map` 3/4, DAL_HOU `no_team_rows`" (#473 post-deploy checklist,
  repeated in state_basketball and in this lane's brief). Those strings exist only in `lineup_effects` (teammate
  effects, orchestrator/connected_game.py:234/:279). The POOL's diag is `rotation_minutes`, and on those games it read
  `team_not_in_history` / `no_recent_history` (preseason guard). The pool never reached a name map.
- The misattribution sent a fix (45e03ae2, native name-map fallback) to a stage that was not failing, and hid a real
  gap: teammate effects have their own name-map copy with no native fallback (leads.md 2026-10-12).
- **Rule:** when quoting a refusal reason for feature X, cite the diag key it was read from, and grep that the
  emitter of the reason string is X's code path. Two features with a name map each emit look-alike reasons.

## 2026-10-12 VARIANT of the lone-CR trap: a regex that captures a `- Goal:` line keeps its `\r` `[lane wnba-live-period-lines-native, session 2d413211]`

- **What happened:** in a CRLF working copy, `re.search(rb"\n- Goal: (.*?)\n", ...)` captures the goal text WITH its trailing `\r`. Pasting that capture into a verdict line plants a lone CR mid-line. Git then marks the file `w/-text` (`git ls-files --eol`) and stops normalising line endings, so the commit would have rewritten the whole file to CRLF: 1,839+/1,838- for a 2-line edit. The games-rail lane hit the same trap the same day.
- **How to apply:**
  1. Build ledger edits from the BLOB (`git show HEAD:<path>`, which is LF here), not from the CRLF working copy.
  2. `.rstrip(b"\r")` every captured line.
  3. Assert `b"\r" not in out` before writing.
  4. The numstat gate (lines changed == lines meant) is what caught it, again.

## 2026-10-12 OVERTURNED: "the WNBA playoff transition fires once a season when the playoffs open" (artifact_publisher.py allowlist comment and tests/test_nhl_quote_shard_dates.py, 2026-09-25) `[lane wnba-playoff-transition-off-vendor, session 2d413211]`

- **Measured:** the vendored `wnba_betting.playoff_transition` is NBA-shaped. It accepts only NBA regular-season game ids (`002...`) and `YYYY-YY` seasons, while the WNBA schedule carries ESPN ids (`040...`) and `YYYY`. The production copy raised before doing anything for every 2026 date, playoff opening included, and returned `skipped`. It never wrote a receipt or a model. The step was removed (1cbaf4ab).
- **Rule:** a step that is "waiting for its one chance" must be dry-run against real data BEFORE that chance. Call its gate function (here `resolve_regular_season_window`) for the dates when it should fire, read-only. An allowlisted receipt pattern proves the receipt would be visible, not that it would ever be written. The allowlist entry in artifact_publisher.py is now dead; it is harmless and is left in place.

## 2026-10-12 -- Before building features for a market, test whether ANY available input adds to the de-vigged price `[lanes mlb-pitcher-outs-k-dist, mlb-starter-workload-signal]`
**What happened.** The plan after a failed distribution fix was a starter-length feature project.
- A one-hour pre-registered test first: logistic BOOK vs BOOK+inputs, fit on one window, game-clustered dlogloss on the next.
- Every candidate input (the sim, recent pitch counts, rest, averages) added nothing to the starter outs/K price; for outs the extra inputs were significantly WORSE (overfit).
- That one test retired a multi-day build.
**Rule.** For a market where the model already loses to the book, run "does input X add to logit(p_book)?" out of sample BEFORE engineering X into the engine.
- If the market-shrink w is ~0 and nothing adds to the book, the market is efficiently priced for the inputs you have: stop, or source a faster / non-public input.


## 2026-10-12 -- RULE: a calibrated engine's known bias may be ABSORBING a missing mechanism; fix one and the other shows. Test the pair, never one alone `[lane ncaab-native-live-tier, session e48a0f9b]`
- Measured (NCAAB, 608 paired games, same seeds): turning on the engine's exact target calibration cut the tip total bias from +6.4 to +1.1, and made EVERY in-game total checkpoint worse (CI excludes 0). The early overshoot had been compensating for the missing second-half free-throw lift (+6.9 FT points).
- Second instance, same day: a bonus free-throw mechanism matched real FTA and fouls but left the half split at ~0. A bonus trip REPLACES a possession; real halves have equal possessions (34.2 / 34.9), so the split lives in scoring per possession, not in foul rules.
- How to apply: before switching on a "fix" for a calibrated engine, run it paired against the current default at EVERY checkpoint the product serves, not only the one it was built for. Decompose the target (here FT vs FG points, possessions per half) before choosing the mechanism.

## 2026-10-12 FORBIDDEN: reading a tool's EMPTY output as a negative result -- a tool that REFUSED and a tool that found nothing print the same thing `[lane lane-claims-new-marker, session 4ab694ed]`

- **Measured twice in one hour, opposite failure modes, identical reading.**
  (1) `pending_deploys.py` piped through `grep -i check_lane_claims` printed
  nothing, and I reported that the dev checker was not pulled into the deploy
  closure. Re-run with the UNFILTERED output captured: **exit 2, one line,
  `could not read live commits from deploy_preflight -- refusing to guess`.** It
  is fail-CLOSED and had answered nothing at all. (2) An off/on comparison ran
  the `HEAD` copy of a script from the scratchpad and reported no typo
  assertion for ALL THREE fixtures -- including the one that MUST fail. That
  script bootstraps `sys.path` from `dirname(HERE)/.claude/hooks`, so outside
  the repo the shared parser import fails and it takes its documented
  fail-OPEN branch: exit 0, silent. The filtered print showed only lines
  starting `->`, which hid the import-failure message.
- **Rule: before reporting an empty result, prove the instrument produced a
  population.** Read the exit code AND the line count of the unfiltered output.
  A grep over a crashed, refused, or fail-open tool is indistinguishable from a
  clean negative, and a filter that drops the error line is what makes it look
  clean. Fail-open and fail-closed differ in every way EXCEPT how their silence
  reads.
- **Corollary for a script copied out of its repo:** a tool whose `sys.path`
  bootstrap is relative to its own location cannot work from a scratchpad. Put
  the support tree beside it inside the fixture, and create those support files
  AFTER `git add` so they never enter `ls-files` and perturb what is measured.
- Same family as [[feedback_instrument_blindness]] and
  [[feedback_null_result_needs_a_live_population]]: a healthy reading is
  evidence only once you know what makes it read unhealthy.

## 2026-10-12 FORBIDDEN: bounding a block in a structured ledger file by the next SAME-LEVEL heading `[lane lanes-archive-20261012, session 4ab694ed]`

- **Measured.** Closing a lane in place, I bounded my block by scanning for the
  next `### ` heading. That block was the LAST `### ` in `lanes.md`, so the
  boundary ran to EOF and the rewrite replaced **765 lines with 7**, deleting
  **114,376 chars**: the `## MERGED FROM`, `## Archive pointers` and
  `## Archived lanes` sections, 763 lines that all live BELOW the last lane
  block. Caught before the commit by the line-count print, not by any guard.
- **Rule: bound a block by the next heading of ANY level** (`^#{1,6} `), and
  assert the block is a plausible size before writing -- a lane block is ~6-14
  lines, 765 is not a lane block. Re-count the file's `## ` sections and `### `
  blocks after the write.
- Third instance of one shape: **from my marker to EOF is only safe when your
  section IS at EOF.** The other two were a land script that duplicated 104,199
  B of `lanes.md`, and a prefix rewrite that clobbered 1,125 lines.

## 2026-10-13 OVERTURNED: "the NHL game-line model needs better inputs to beat the as-of GF/GA baseline on moneyline" -- eight were tried and none did `[lane nhl-game-lines-model, CLOSED GOAL: NOT MET, session 9ed26377 / closed by 4ab694ed]`

- **Measured over the 2025-26 regular season, walk-forward with as-of fits only** (`docs/reports/nhl_game_lines_model_experiments_2026-10-02.md`, 609 lines, 971 CIs, 265 `n=` values; OOS n=681, full regular n=1,132, playoffs holdout n=82). **Eight candidate inputs, NOT ONE with a CI excluding zero on ML**: sim machinery, save%, GSAx, prior-season GSAx, recency weighting, dispersion, score-adjusted xG, confirmed starters. Against the BOOK the model is at parity on ML, puck line, totals and the regulation 3-way.
- **The calibration half of the same lane SUCCEEDED, which is the contrast that matters:** settled total bias went **+0.111 -> +0.008** by fixing mis-settlement (full-game OT/SO, regulation tie mass, empty net, regulation pace) and reading the modal pregame totals line. **Calibration defects are findable and fixable from the inside; DISCRIMINATION was not improvable by any input in hand.**
- **Rule: before building features for a market, test whether any available input adds to the de-vigged price -- and if the answer is no across the inputs you have, the deficit is INFORMATION, not engineering.** A projection that ties a GF/GA average is not short of features. Shipping two more layers that each reach production and move nothing (score-adjusted xG ML dBrier -0.00017 [-0.00036, +0.00002]; GSAx ML +0.00056 [-0.00118, +0.00238]) costs real deploys and buys no edge.
- **Corollary on how to read a "ships" verdict:** both of those layers passed their stop conditions and SHIPPED, because the stop condition was "do not deploy if the CI is entirely worse", not "deploy only if it is better". A pre-registered gate phrased as a floor admits anything that is merely harmless -- which is correct for a calibration fix and misleading for an edge claim. Say which you are testing.
- Same shape as the MLB finding that nothing added to the starter outs/K de-vigged price, and as [[feedback_a_projection_is_not_a_model_edge]]. Also [[feedback_check_the_stat_is_priced]]: parity with the book IS the ceiling once the book prices the same information.

## 2026-10-13 FORBIDDEN: a goal clause that requires an undisturbed production window, on a fleet where any session can deploy `[lane live-inplay-board-cadence, CLOSED GOAL: NOT MET; session a1e40980 / closed by 4ab694ed]`

- **Measured.** The goal required live rows to refresh *"without a full board build and **without a restart during a live slate**"*. Across its three readings, clause G2 FAILED in 2 of 3 because a DIFFERENT session deployed refresh-worker mid-window (`ce9be1ea` 23:56Z, `d5449df7` 02:32-02:35Z), and the third window carried 5 HTTP 502s plus 5 web `oomKilled`. **Not one of those was the lane's own change.** G2 therefore measured the FLEET's deploy rate, not the work under test, and no amount of effort inside the lane could turn it green.
- **Rule: never write a goal clause the lane cannot control.** With ~15 sessions able to deploy at will, "no restart in the window" is a property of the schedule, not of the change. Write it as an exclusion instead -- *measure only windows with no deploy, and report how many windows that left* -- so a disturbed window is DISCARDED rather than scored as a failure. State the discard count; if it is most of them, that IS the finding.
- **Corollary:** the same reading is why the lane's primary number survived and its secondary clauses did not. Look-to-serve (362 s -> 241 s, a 33% cut) is measured per card and is robust to a mid-window restart; a boolean "restart-free" clause is destroyed by one. **Prefer a continuous measure over a boolean gate when the environment is shared.**
- Same family as [[feedback_absence_in_a_window_is_not_absence]] and [[feedback_measure_same_instant]]: say what the window was, and what the window admitted.

## 2026-10-13 OVERTURNED: "`--check` passed, so the generated port is what the generator produces" -- it passed on the Windows checkout only `[lanes nba-live-tick-native / nba-source-cli-native, session 2d413211]`

- **Measured.** All three port generators (P6's orchestrator, the live ticks and the NBA CLI) stamp each generated file with a hash of the vendored source's RAW bytes. A Windows checkout (CRLF) and the fleet's Linux checkout (LF) stamp different hashes. `--check` and the tests that run it passed on Windows and failed on the fleet for every generated file after the 18587150 ff. P6's had been failing there unseen since 2026-10-10. Fixed in a82f821a (the hash is over LF-normalised bytes; code unchanged).
- **Rule.** A byte-exact self-check belongs on the DEPLOYED checkout, not only on the machine that generated the files. Anything that hashes or compares file bytes must normalise line endings, or say why not.

## 2026-10-13 A 0-diff parity run proves only what the run exercised: count the leaves, and read what the arm WROTE `[lane nba-live-tick-native, session 2d413211]`

- **Measured.** Two live NBA preseason recordings of the vendored tick (10-12 23:45Z, 01:45Z) came back 0 diffs over 18 and 17 leaves, with no file written. The tick gates every in-game write on a live total line or a prop line, and preseason has neither; production wrote no NBA signal that day either. The real evidence came from a doctored replay of 2026-10-05, a slate production had written 17+17 on: 3,717 leaves, signals, projections and the props registry.
- **Rule.** Report the leaf count and files_written next to every "0 diffs". When the arm writes nothing, pick inputs that exercise the write paths (a slate production wrote on), and say that the inputs are doctored.

## 2026-10-13 -- A seed fixes the RNG, not the process: cross-process sim comparisons need PYTHONHASHSEED `[session ee14e4ec / 7693274b, lane basketball-pregame-teammate-effects]`

- **Measured:** the basketball smart sim with a fixed seed is identical WITHIN a process (OFF vs OFF-repeat, 194/194 players). ACROSS processes it was not: identical code, same seed and inputs, differed on 102,817 of 137,481 output leaves. With PYTHONHASHSEED=0 on both, the only differences were 6 scratch-path strings. String-hash randomisation changes set/dict iteration order, and so the order draws are consumed.
- **Cost if missed:** a refactor's "is it neutral?" check reads as a large regression (or hides one inside noise).
- **Rule:** for any sim A/B or neutrality check split across processes (two code versions, two worktrees, before/after a deploy), set PYTHONHASHSEED to the same value in both, and run a same-code control under the same setting first. Arms in ONE process need only the seed.


## 2026-10-14 -- RULE: a fail-open guard must PROVE it ran; and a hook fix on main is NOT live until the PRIMARY tree is fast-forwarded `[lane precommit-python-probe, session e48a0f9b]`
- **Measured:** `.githooks/pre-commit` ran the first `python3` on PATH. On Windows that was the WindowsApps App Execution Alias, which from a backgrounded Git Bash could not start ("Permission denied", exit 126). The hook treats every non-1 exit as fail-open, so commit 857ec54b went in with NO ledger check and no warning. The same hook had blocked commits all day from a foreground shell, so "it has been catching things" was no evidence it ran.
- **Second half:** `core.hooksPath` points at the primary tree's `.githooks`. The fix (ca7a0aa4) was on main and inert until the primary tree (891 behind) was fast-forwarded.
- **How to apply:**
  - A fail-open check must distinguish "checked, clean" from "could not run", and SAY the latter (probe the interpreter; warn when nothing starts).
  - Verify a hook or guard fix by running it from where it actually executes (the primary tree), not from the worktree where it was written.

## 2026-10-14 RULE: a fleet status read right after YOUR OWN `wsl` call boots WSL is not an outage reading -- wait for the boot path, then re-read
**Evidence (session 43e4d5fe, 2026-10-13):**
- WSL had stopped at ~04:37:10Z. My next `wsl -e` call booted it (`uptime -s` 04:37:32Z), and `status` 4 s later read all three roles DOWN, with SyndicateLocalProduction "not running".
- I escalated a restore decision to the user. The boot path had already brought every role back at 04:38:47Z (pids 476/540), 75 s after my read.
- The user's answer arrived 8.5 h later. Only a re-read before acting kept it from becoming a second, unneeded fleet restart under a peer's live claim (nba-live-tick-native had just taken refresh-worker).
**How to apply:**
- If `uptime -s` is within ~2 min of now, the read is a boot, not a steady state. Wait ~2 min, re-read `status` + healthz, and only then call it an outage.
- Any approval that arrives long after the question is asked is an approval of the state AS DESCRIBED. Re-read the state and every claim before acting on it, and act on nothing that has changed.

## 2026-10-14 -- nflverse spells the Rams `LA`, not `LAR`: grep a game by DATE, never by a guessed game_id `[lane nfl-mnf-settlement-lag, session d4409ac4]`
- I checked "is MNF in the fleet pbp" with `grep -c 2026_05_BUF_LAR` four times over ~4 h and reported 0 each time; the game is `2026_05_BUF_LA` (199 rows, present since 18:57Z). A zero from a guessed key is the empty-output trap the 10-12 FORBIDDEN names.
- **Rule:** select by `game_date` (or the schedule's own game_id) and print what is there before concluding a game is absent.

## 2026-10-14 -- RULE: before "re-fit the calibration", check WHERE in the pipeline the calibration reads its residual `[lane basketball-scenario-calibration, session e0a3e383]`
- **Measured:** a pre-registered step said "re-fit the NBA totals calibration" to absorb +1.2 points added by new engine
  foul mechanisms. `build_nba_totals_calibration.py` fits actual − `market_anchor.model_total_raw`, the raw
  ratings × pace total UPSTREAM of the engine. The engine mechanisms never touch that number, so the re-fit would
  have reproduced the same terms and "passed" while fixing nothing.
- **The real cause:** FT volume (+1.2 FTA/game). The bonus rate had been fitted before a second foul mechanism was
  switched on (mechanism vs estimator again).
- **Same session, same shape (the target is not what it is labelled):**
  - ESPN team stat `fouls` (20.52) is NOT personal fouls (19.67 from the player box).
  - ESPN pbp writes an offensive foul twice ("Offensive Foul" + "Offensive Foul Turnover"), which inflated sixth-foul
    counts 390 vs 141.
  - `float(x or 1.0)` turned a lever value of 0.0 into OFF.
- **How to apply:**
  - Name the exact field a calibration or target is computed from, and confirm the change you are compensating can
    move it.
  - Reconcile any new real target against a second source (box vs pbp) before gating on it.

## 2026-10-14 — RULE: ESPN soccer commentary shot events carry NO athlete id; key a per-player join on the name within the team `[lane soccer-live-anytime-scorer, session b9bb5f37]`
- **Belief overturned:** `espn_live_state.build_live_state` credited shots, goals and assists to `player_stats` by `shot["player_id"]`, and the live props looked fine because every row still had a projection.
- **What was true:** 134 of 134 shot events on four 10-12 summaries had `player_id == ""`, so every live player read 0 shots, 0 goals and 0 assists in production. A scorer was priced as if they had not scored. Separately, serie_a/epl/la_liga/bundesliga/mls player rows are keyed `understat_<n>`/`asa_<id>`, so even an id-bearing stat could never meet its row.
- **Rule:** before trusting a per-player join across ESPN and another source, COUNT the populated key on real payloads (non-empty ids, ids shared with the other side). A probe at a mid-match cutoff that compares banked goals with the scoreline (minus own goals) is the cheapest positive control. Fixed in 8fd8d83b (name within team, unique only).

## 2026-10-14 -- RULE: register a lead ALONE unless the family is the claim; a pairing chosen for tidiness cost a pass `[lane signal-engine-nhl, session 9e18a0e7]`
- **Measured:** the two NHL saves leads were registered as one Holm family for the out-of-sample test (v3). `saves_opp_volume_high` repeated (+9.1% [+0.8, +17.5], p 0.0185 on 138 unseen games; +10.6% before) but needed p <= 0.0125 as the stronger of two; its partner (`saves_team_leaky`) reversed. Alone at 0.025 it would have passed. The bar stood, and the lead went to a third, single-hypothesis forward test (S1F), costing a season.
- **Rule:** pair hypotheses under a family correction only when the CLAIM is the family. Two leads with separate evidence get separate registrations (and, if both run, a split alpha decided up front). Holm across a strong and a weak lead charges the strong one for the weak one.

## 2026-10-14 -- a Windows Update restart takes the fleet down until someone LOGS ON: the task's only trigger is at-logon `[session d4409ac4]`
- 1:29 AM CT MoUsoCoreWorker restarted the PC; `SyndicateLocalProduction` (MSFT_TaskLogonTrigger, Interactive) did not run until the 7:47 AM logon -> 6 h 19 m outage, settlement 51 min late. Read like a slow settlement; it was a host event.
- **Rule:** when a scheduled fleet job is late, check `uptime -s` in WSL and Windows event 1074 BEFORE reading the job's own code.

## 2026-10-14 -- OVERTURNED: "TaskStop stops a Git Bash watcher loop" (lane nba-native-live-resim)
- **Belief:** `TaskStop` on a background Git Bash `until/for` loop ends it.
- **Reality:** the loop's bash process survived. It and its replacement both fired a fleet `down` (14:07:45Z and 14:08:17Z on 2026-10-13); the second killed a supervisor the first had just started. That cost ~25 s of extra outage and one extra cold start. Both events are visible in `role_restarts.jsonl`.
- **Rule:** before arming a replacement for any loop that can take an outward action (down/up, deploy, push), kill the old loop by pid and confirm with `ps -ef | grep [a]uto_cycle` that it is gone. Never let two armed actors share a trigger.


## 2026-10-14 -- RULE: `local_production.py status`'s supervisor `since` is NOT the supervisor's start; judge a fleet `up` by `supervisor.log` and role `restarts=` `[lane ncaab-native-live-tier, session e48a0f9b]`
- **Measured:** `status` printed `supervisor pid=202264 since 2026-10-14T02:30:28Z`. 02:30:28Z was live-odds-worker's own uptime recycle (`RECYCLING after 19641s`, exit 0, respawned `restarts=1`). The real `up` was 2026-10-13 21:02Z (lane fair-price-v2, recorded). I read `since` as a new `up`, called it "unattributed", and wrote that into deploys.md; the correction was appended.
- **How to apply:**
  - A full `up` is `supervisor.log`'s `stopping roles ... stopped.` + `LOCAL PRODUCTION UP ... commit=<sha>`, plus every role's `==== start <ts> restarts=0`.
  - A `restarts>=1` start is a single-role respawn that REUSES the env from `up`.
  - Before calling any fleet change "unrecorded", grep `deploys.md` for the exact seconds and the SHA, not only today's headers.

## 2026-10-14 CORRECTION to 2026-10-13's own block-boundary rule: it prescribed the WRONG regex, and the rule was broken the day after it was written `[lane ledger-io-block-bounds, session 4ab694ed, commit 48328ada]`

- **The 2026-10-13 entry says "bound a block by the next heading of ANY level (`^#{1,6} `)". That overshoots.** Measured on `lanes_history.md`: `^#{1,6}` truncates **26 of 887** archived blocks, one from **259 lines to 15**, because archived blocks legitimately carry `####` sub-headings. A heading DEEPER than the block's own level is CONTENT. **The correct boundary is `^#{1,3}`** -- stop at the next `#`, `##` or `###`. `lanes.md` has 2 such lines and 0 of its 75 blocks contains one, so the two boundaries agree there and ONLY the archive exposes the difference; a rule verified on `lanes.md` alone reads correct and is not.
- **The rule was also broken one day after it was written, by me.** A fresh verification harness bounded by `###` only, read a 12-line block as **785 lines / 120,001 chars**, and reported a correctly-archived block as ALTERED. Its gate refused the commit, so the cost was minutes -- but prose plainly did not transfer.
- **Rule: when a boundary rule recurs, move it out of prose and into a shared helper.** `scripts/ledger_io.py` now owns it: `block_spans` / `block_bounds` / `block_text`, with `block_bounds` RAISING on an absent slug and on a duplicated one (naming both line numbers) rather than picking a copy. Call it; do not re-derive the regex in the next ad-hoc script.
- **Corollary on where to look for the defect:** the production tools were already right (`archive_state_subject.py` scans inside `subject_span`, which bounds at the next `## `; `check_trimmed_contracts.py` independently chose `^#{2,3}`). Both failures were in throwaway harnesses, which get no tests and no review -- so a rule that only tools obey is a rule that fails exactly where nothing is watching.

## 2026-10-14 -- a .ps1 handed to the user for an admin change must ship with a .cmd launcher: this host's execution policy blocks scripts and the failure is SILENT `[session d4409ac4]`
- Two "run this script" rounds changed nothing; the user saw a window and reported DONE once. PowerShell/Operational event 4100: "running scripts is disabled on this system". Only the read-back from my side caught it.
- **Rule:** give a `.cmd` wrapper (`powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0x.ps1"`), make the script log to a file, and verify by reading the changed object back -- never by what the window said.

## 2026-10-14 — OVERTURNED (mine, twice in one hour): a frame size sitting NEAR a cap is not evidence the cap binds; classify each dropped item by mechanism before naming one `[lane wnba-native-live-cutover, session 99686b8c]`

WNBA pregame engine frames had a median of 10 players all season and real rotation players were missing. I first said "no recent team games" (true only in May), then "capped at ~10" from the flat median -- and sent the second to a peer as a lead. The code does cap WNBA at 11, but classifying each of the 261 missing players against its team's previous game showed 217 sat that game out (the K=1 recency rule's trigger) and only 12 met a full frame; 197 of the 261 were missing from frames of 8-10, which a cap of 11 cannot have cut. **RULE:** before attributing a shortfall to a limit, count how many dropped items met the limit's condition at the time (here: frame == cap). A distribution summary (median 10) cannot tell a binding cap from an upstream filter that leaves pools small.

## 2026-10-14 -- "free" stale worktree admin dir is not "holds no unlanded commit": check ORIG_HEAD and the reflog before pruning `[session ee14e4ec / 7693274b]`

- **Measured:** `session_worktree.py prune` labelled two `.git/worktrees/*` dirs "free, 0 HELD (the last pointer to a commit)". They had no HEAD file, but their ORIG_HEAD + `logs/HEAD` named 9 commits reachable from neither origin/main nor any branch. Deleting the dir drops that last reference, and gc can then collect them.
- **Here it cost nothing:** all 9 had landed under rebased SHAs (6 patch-id identical; 3 differing only by a correctly dropped stale `deploys.md` hunk).
- **Rule:** before `prune --apply`, list every SHA in each stale dir's ORIG_HEAD and `logs/HEAD`. Any SHA unreachable from origin/main or a branch must be matched on main by patch-id or `git range-diff` (git cherry semantics), or rescued with `git branch rescue/<id> <sha>`. The tool's "free" does not do this.

### A "Saved schedule" line is not a fetch -- read the content's date range `[2026-10-14, session 2d413211, lanes nba-schedule-current-season + basketball-schedule-adapter-native]`

The NBA `fetch-schedule` printed "Saved schedule to ..." and exited 0 on every run, so it read as working. It had not fetched in this
season: cdn.nba.com answers 403 here, and the command's local fallback re-reads `schedule_2025_26.csv` and writes it back. A
fresh mtime on a file holding 2024-10-22..2026-04-12 with empty statuses. The give-away was in the payload (empty `game_status`,
the date range), not the log or the exit code. A second writer (the schedule_adapter fallback in a long-lived worker) kept
re-asserting the stale content after the fix shipped, so even the fixed path's output can be overwritten by an unfixed sibling.
**How to apply:** for any fetched artifact, check its newest date and a status/provenance field before calling the fetch healthy;
and before calling a writer fixed, enumerate EVERY writer of that file (`grep` the filename across syndicate/ and scripts/).

## 2026-10-14 -- OVERTURNED: "copying a script into tmp_path sandboxes it" -- not once the script resolves paths from the ENVIRONMENT `[lane deploy-claim-test-sandbox, session 9ed1222d, commit ff304ae1]`
- **Belief:** `test_deploy_claim_holder_identity` was safe because it copied `deploy_claim.py` into tmp_path, so REPO_ROOT pointed at the sandbox.
- **Overturned by:** c3a5f11b made `deploy_claim.py` read `SYNDICATE_DEPLOY_CLAIM_DIR`, then `local_production.env`, BEFORE its repo root. The test passed `os.environ` through, so wherever that var is set (the WSL fleet, nightly ci-suite) it wrote a live 45-min `web` claim held by `lane-a`/`session-aaa` into the production claim dir -- seen in `status` 10-13 and 10-14. Reproduced against a scratch dir.
- **Rule:** a test that shells out to a repo script must build its env by subtraction then pinning: drop every var the script resolves a path from, set each one into tmp_path, and assert the artifact landed under tmp_path. When a script gains a new path source, grep tests/ for subprocess callers of it in the same change.

### A scripted claim acquire must gate on its exit code, never on grepped output `[2026-10-14, session 2d413211, lane basketball-schedule-adapter-native]`

`deploy_claim.py acquire ... | grep -E "ACQUIRED|token|REFUSED|held"` printed NOTHING when the claim was refused (the refusal's
wording matched none of the patterns), and the script carried on: ff + a live-odds-worker restart landed inside another lane's
claims, taken for a planned reboot test. Silence was read as success. **How to apply:** in any deploy script, run
`acquire` unfiltered, `|| exit` on its status, and re-read `status --service <svc>` naming YOUR holder before the first mutating
command. A filter on a guard's output is a way to not see the guard.

## 2026-10-14 — RULE: an offline soccer squad/lineup measurement must run with SYNDICATE_DATA_ROOT set, or the departed filter's roster rescue is EMPTY `[lane soccer-starter-name-match, session b9bb5f37]`
- **Belief overturned:** I reported confirmed-starter resolution as 2,058 -> 2,130 of 2,222, and 14 starters "dropped by the departed filter", from `_load_player_rows(league, root)` with an explicit root.
- **What was true:** `_current_roster_names` reads through the data root, not the `source_root` argument. Without `SYNDICATE_DATA_ROOT` it returned 0 names (roster_size=0 in every league), so the filter rescued nobody and dropped 10 starters that production keeps. With it set, the figures are 2,069 -> 2,142, and only 4 "dropped" remained. Those were not drops either: the deduped row kept an older season's name ("Jonathan Buatu" vs ESPN "Buatu").
- **Rule:** when calling a loader with an explicit root, PRINT a size for every side input it reads (the roster set here) before trusting the output. An empty rescue list looks exactly like a working filter.

## 2026-10-14 -- RULE: the code the fleet supervisor RUNS is the last `LOCAL PRODUCTION UP ... commit=` line in supervisor.log -- not the checkout HEAD, not `supervisor.json` started_at, not `status` `[lane forward-input-preservation, session 9e18a0e7]`
- **What happened:** a peer fast-forwarded `~/Syndicate` to `a78aab9c` at 18:04:42Z, and `supervisor.json` said started_at 18:05:02Z -- 20 s later, so it read as "the supervisor loaded the ff". It had not: `cmd_up` imports SCHEDULED_JOBS and prints `commit=` at process start (17:58:54Z, `commit=63631afb6494`), and stamps started_at only after the roles come up (~6 min here). An ff inside that window is on disk, before the stamp, and NOT loaded. `local_production.py status` is blind the same way: it lists SCHEDULED_JOBS from the checkout's FILE, so an unloaded job prints `last_run=never` exactly like a loaded one that is not yet due.
- **Rule:** to say "commit Y / job X is live on the fleet", read the last `LOCAL PRODUCTION UP` line's `commit=` and run `git merge-base --is-ancestor Y <that commit>`; once the job has been due, also read its key in `run/scheduled_jobs.json`. Checkout HEAD, started_at and `status` each answer a different question.

## 2026-10-14 RULE: with uncommitted CODE in a worktree, land ledger edits with plumbing on origin/main -- and never recover a bad local commit with `reset --mixed`
**Evidence (session 43e4d5fe, lane past-line-overlays):**
- The worktree held uncommitted code; HEAD was b5100a80 and origin/main had moved 6 commits.
- A lanes.md append was written from the NEWER origin blob and committed onto the OLD HEAD, so the commit (5846f693) carried 6 / 3 lines of other sessions' lane edits as if they were mine. The push was rejected (non-fast-forward), so nothing landed. A forced or rebased push would have re-applied stale context.
- Recovering with `git reset --mixed origin/main` kept the old working tree. Nine files other sessions had changed upstream (learnings, state, log, two scripts, live_refresh_loop.py, a deleted test) then showed as MY modifications, each one a silent revert if committed. lane-postwrite-check flagged three as out-of-lane writes when I restored them.
**How to apply:**
- Build the ledger commit without the working tree: `GIT_INDEX_FILE=tmp git read-tree origin/main`, `update-index --cacheinfo` the edited blob, `write-tree`, `commit-tree -p origin/main`, `push <c>:refs/heads/main`, and retry from a fresh fetch on rejection (C:\tmp\soccer-lpb\ledger_commit.sh does this).
- If a stale local commit already exists: `git reset --mixed origin/main` and then `git checkout origin/main -- <every path you did not author>` BEFORE anything else. Read `git status`; your own files are the only ones allowed to differ.

## 2026-10-14 SECOND CORRECTION, same day, same rule: `^#{1,3}` is still not the boundary — a `#` line inside a FENCED CODE BLOCK is not a heading `[lane ledger-block-bounds-fenced, session 4ab694ed]`

- **The entry above says "the correct boundary is `^#{1,3}`". It is still wrong, in a third way.** A column-0 `# comment` inside a ```` ```python ```` sample is byte-for-byte a level-1 Markdown heading. Measured over **1,360 blocks** in lanes.md + lanes_history.md + lanes_closed.md: **386 fenced lines, 1 false boundary**, truncating `soccer-projection-collapse` from **60 lines to 9** at `# syndicate/features/shared/board_enrichment.py:678` — a file path in a code sample.
- **No level rule can settle this, which is why the third attempt is not a fourth regex.** `^#{2,3}` is immune to that one case and would be fooled identically by a `## ` line in a Markdown sample; `^#{1,3}` is fooled by `# `. **The fence has to be tracked.** `ledger_io.fenced_lines()` does it, and it is applied to the START predicate as well as the END one, so a `### foo` in a sample no longer opens a phantom block either.
- **CORRECTION to that entry's own corollary.** It said "the production tools were already right" and cited `archive_released_lanes.py`'s independent choice of `^#{2,3}` as confirmation. Measured: that regex **disagrees with `^#{1,3}` on `lanes_history.md`**, the file that tool APPENDS TO — 1 block of 658, read 51 lines too long. It agrees on `lanes.md` (0 of 70), the file the tool reads, so the tool was never wrong in practice — but "independently chose the same rule" was offered as evidence the rule was right, and it was agreement on the only file where the rules cannot differ. **Two implementations agreeing on the easy population is not corroboration.**
- **Rule: an UNCLOSED fence must make the block run LONG, not short.** A long block shows up in any diff; a short one deletes content silently, which is the failure this rule has now produced three times. `fenced_lines` treats everything after an unclosed opener as fenced deliberately, and a test pins it.
- **And the guard that encoded the defect:** `tests/test_ledger_block_bounds.py`'s property test asserted that no span's interior holds a `^#{1,3} ` line. When the fix landed it FAILED, naming the exact code-sample line. It was not a false alarm and it was not protecting anything — it had pinned the old behaviour as the invariant. **When a test fails on a fix, ask which of the two encodes the rule before changing either.**

## 2026-10-14 -- CORRECTION to "OVERTURNED: copying a script into tmp_path sandboxes it" (lane deploy-claim-test-sandbox) `[lane ci-env-home-sandbox, session feaf967d, commits 921fa58e 148947d6]`
- **What that block says:** the test wrote live claims because it passed `os.environ` through and `SYNDICATE_DEPLOY_CLAIM_DIR` was set "(the WSL fleet, nightly ci-suite)".
- **Correction:** in the nightly ci-suite that var was scrubbed by `ci_env()`. The leak came through HOME: ci_env passed it, and the script's fallback read `~/syndicate-prod/local_production.env`, which names the production claim dir. Both stray claims fall inside nightly ci-suite windows (10-13 ~08:00-08:50Z with the claim at ~08:31Z; 10-14 12:47:59-14:08:32Z with the claim at 13:57:31Z). That block's rule stands; this adds to it.
- **Rule:** an env scrub is an ALLOWLIST of variables, but HOME is one variable that stands for a whole directory of configuration. A sandboxed run must replace HOME (and USERPROFILE), not pass it through. It must also point every "defaults to localhost" service URL at a dead port, because on the fleet host `127.0.0.1:6379` IS production. Measured the same day: with the env scrubbed and HOME sandboxed, a test still wrote the fleet's OddsAPI quota document through a `redis://127.0.0.1:6379` default. It patched the enable switch rather than setting the env var the scrub controlled.
- **How to apply:** gate a sandbox on what the child process RESOLVES or TOUCHES (resolve the path in a subprocess; put an audit hook on socket.connect/open), not on the env dict's keys. The key list looked clean both times.

## 2026-10-15 OVERTURNED (mine, within an hour of landing it): **an ABSENCE-OF-RESPONSE claim needs its own check, exactly like an absence-of-data claim** `[lane model-edge-gap-attribution, session 4ab694ed, commit d8360836 then corrected]`

- **What I shipped:** a measured finding that 72.7% of the Layer 2 ranking's model edges come from a model whose own verdict says it loses or was never backtested — and the sentence *"using such a model's edge as a ranking term requires naming that subset, and nothing in the board does."* The numbers were right. **The last clause was false.**
- **What exists:** `layer2_board._apply_skill_reliability` (line 937), `measured_market_skill.skill_reliability`, and `daily_optimizer`'s overlay multiplying it into rank AND stake. **All three were already written down in `state_model.md`**, one of them in the very subject my finding belonged to. Measured after: **all 1,011 established-loss rows are penalised, 0 unpenalised**, factor down to the 0.5 floor.
- **The asymmetry that made it easy.** I was careful with every DENOMINATOR (cap defeated, `rows == total_rows`, no share over zero rows, two reads ten minutes apart) and then spent none of that care on the claim that nothing responds. **Measuring a population tells you nothing about whether the system reacts to it.** The repo already has the data-side version of this rule (`null result needs a live population`); this is the control-side twin.
- **Rule: before reporting a population as unresponded-to, FIND THE RESPONDER.** Grep for the field, the factor, the gate; read the state subject the finding belongs to. If no responder exists, say which search would have found one. Absence of a mechanism is a claim, not a default.
- **Corollary, and it is the useful half:** the mislabel I found (308 rows whose verdict text says "loses to" under `verdict_class: measured`/`parity`) does **not** reach the score, because the factor keys on `status` + `established_loss_rel` and never on `verdict_class`. Had I not looked for the responder I would have filed a cosmetic vocabulary bug as a live scoring fault — a much worse error than the one I made, and the SAME search prevents both.
- **Why this cost one reading instead of a lane:** `state.md` contradicted my own findings file at checkpoint time and I checked instead of writing. That is the protocol's start-of-session read paying off at the END of a session.

### 2026-10-15 -- A recent hit-record ("cleared N of the last N") does not beat the price; never show it as edge
- **Believed:** X.com "consistency" tickets (alt rungs -260..-490, every leg cleared every game) imply a mispriced edge; the cheat sheet's "streaks the price leaves room for" used a market-anchored posterior with a provisional k = 40.
- **Measured (session 9e18a0e7 subagent, as-of backtest, game-clustered):** NFL 2023-24 + 2026, NBA 2025-26, MLB 2026 -- 2,197 tout-style 5/5 rungs in 1,234 games hit 68.7% vs a Shin fair of 71.6%: **-2.6 pts [-4.9, -0.3], ROI -8.5% [-11.3, -5.5]**; 5/5 minus other rungs in the same price band -0.7 [-3.1, +1.7]; price-adjusted logit lift NBA -0.5 [-2.2, +1.3]; the fitted beta-binomial concentration was 1,000-100,000 in 14 of 17 cells (the price carries all the weight) and the shrunk estimate adds nothing out of sample. Tables: `C:\tmp\edge-analyses\consistency\`.
- **Rule:** a streak or consistency feature never enters ranking, tickets or a published "edge" without an out-of-sample, price-adjusted, game-clustered hit-minus-fair test. Public surfaces label streaks "already in the price".
- **Also from that run:** NFL 2026 quote files are labelled by CAPTURE week, not game week (26 of 71 events in `2026_wk4`/`wk5` belong to the next week) -- assign game week from the schedule; `grade_football_fade_leads.py::nfl_records` appears to join by file week (unverified, for `signal-engine-football`).

### 2026-10-15 -- Per-slate snapshot files: the newest file is not the whole league
- **What happened:** `player_headshots._nhl_rows` read only the newest `roster_snapshot_<date>.csv`. Those files are PER SLATE (only that date's teams); the newest (10-17) held no Colorado row, so MacKinnon / Makar / Necas / Kadri had no headshot and no side on the board or the cheat sheets (NHL sheet identity 18 of 49).
- **Fix (d79a1ad5):** union the newest 60 snapshots, newest file wins per player (a trade shows the new team), a name on two players inside one file is still dropped. NHL identity 47/47 after.
- **Rule:** before taking "the newest file" of a dated family, check whether each file is a full snapshot or one slate/partition of it.

## 2026-10-15 RULE: `ps -o lstart` in the fleet's WSL prints CENTRAL time -- never feed it to `date -u -d`; use role_restarts.jsonl or `ps -o etimes`
**Evidence (session 43e4d5fe, lane past-line-overlays):** refresh-worker pid 295247 read as "started 2026-10-14T17:52:37Z" via `date -u -d "$(ps -o lstart= -p $pid)"`. That put the start BEFORE the 20:18:56Z ff carrying the change, contradicting `status`'s code=abed0ccc. The true start was ~22:52Z: role_restarts.jsonl shows a claimed exit at 22:53:13Z. A 5-hour clock error would have called a correctly loaded fix "not loaded" (or the reverse).
**How to apply:** For a role's start, read `role_restarts.jsonl` (UTC, carries holder) or compute `now - ps -o etimes=` (seconds, zone-free). Treat any lstart-derived timestamp as Central.

## 2026-10-15 OVERTURNED (mine, 90 minutes after landing it): **a SERVED snapshot is a score-ranked subset, not the board — never answer a "what can be priced" question with one** `[lane ncaaf-live-segment-history, session 4ab694ed, corrects 81a4d85d]`

- **What I landed:** "the venue segment constraint is MLB-specific", from the served shortlist at 00:55Z — 189 non-MLB live rows, 95.8% `segment=full`. I checked the frame WAS live (21 games in play, via game-chips), defeated the row cap, and took two readings. All of that was care spent on the wrong axis.
- **What the priced population says** (`opportunity_population` ledger, 212,665 live sides, 16 dates): ncaaf **54.1%** full, nba **65.4%**, mlb **74.6%**, nfl 86.2%, soccer 97.1%, nhl 100%. **MLB is third of the five segment-carrying sports.** The verdict was wrong.
- **NBA is the proof, and it is the whole lesson in one row: 19 of 19 = 100% full SERVED, 65.4% of 17,682 PRICED.** The served live board is score-ranked and tiny — 709 NCAAF live sides priced on 10-14 against **12** served. A snapshot answers "what is the board showing"; it cannot answer "what could be priced", and those two questions look identical when you only have one instrument.
- **Rule: match the denominator to the verb.** SHOWN -> the served board. PRICED / COULD BE PRICED / COULD BE BET -> the priced population. GRADED -> the settled population. The originating MLB finding's own 427 was priced-scale, so the comparison was never like-for-like and the mismatch was invisible because both numbers were called "live rows".
- **My own caveat was pointing at it and I stopped one step short.** I wrote that two readings nine minutes apart disagreed by 88 rows and 6.7 points, and concluded "a single live reading carries more variance than its denominator suggests". The right conclusion was that the denominator itself was wrong. **A variance caveat on a snapshot is often a sampling-frame error wearing a noise costume.**
- **Corollary that cost two findings files:** the premise *"the live MLB board is mostly first3/first5"* was inherited, never measured, and false (74.6% full). I repeated it twice. **An inherited premise carries no measurement — when a chain of leads rests on one sentence, measure that sentence first.** Doing so also re-sized the real problem: segment mismatch is 4.0% of the MLB venue failure, and the 94.6% that matched no quote at all is the actual lead.

## 2026-10-15 OVERTURNED (mine): **`--data-root` is not the data root the evidence layer reads -- a hand run of the cheat-sheet generator degraded sheets with no error** `[lane cheat-sheets, session 9e18a0e7]`
- `scripts/build_cheat_sheets.py --data-root X` wrote to X, but `build_prop_evidence` found its data through `SYNDICATE_DATA_ROOT`. The scheduled tasks set both; my hand runs set one. Result: the 10-15 NFL sheet with positions 0/131 and no matchups, and the 10-14 NCAAF sheet (built by hand 2 h earlier) with matchups 0/118 -- served for hours, unnoticed.
- **Nothing errored because every evidence layer returned a clean `absent_reason`** ("no gsis id", "not on this disk"). An absence the code explains to itself is still an absence: the run summary printed `pos: 0` and I read past it twice.
- **Rule: a script that takes a root as an argument must make every layer it calls agree on that root -- or refuse.** Fixed (88fce6f7): unset -> set from `--data-root`; a different one -> REFUSED. Verified by re-running the exact failing command with the variable unset.
- **Corollary: a repair rebuild can be worse than the damage.** Rebuilding the NHL 10-14 record from quotes dropped it from 102 to 66 rows; the prior was restored. Back up, compare counts, keep the better.

## 2026-10-15 **truncating a log line SILENTLY ALTERS VALUES, it does not only hide fields** `[lane venue-prop-series-request-side, session 4ab694ed]`

- **Measured, on myself, twice in one lane.** I read `TRIM_SELECT` through `cut -c1-220` and the cut landed inside a number: **`kept_in_window=5149` came back as `kept_in_window=53`**, and for several minutes I believed 53 of 6,000 retained Kalshi markets were in the board's date window (0.88%) rather than 5,149 (85.8%). The cut also hid `cut_in_window` entirely — the field the emitter's own comment calls **the point of the line**.
- **Why it is worse than a missing field.** A missing field reads as absent and prompts a second look. A truncated number reads as a VALUE, plausibly, and the conclusion built on it looks measured. I only caught it by reading the emitter and noticing field names I had not seen in the output.
- **Rule: never cut a structured log line.** Print it whole, or parse it by field name. If it is too wide to read, split on whitespace or pull the fields you want by regex — never `cut -c`, `head -c`, or a fixed-width column. Same family as the book-grid row cap and the `awk $1>=iso` window: a DISPLAY limit masquerading as data.
- **And the sibling, fourth instance tonight:** a shell variable does not survive into `wsl -- bash -lc '...'`. Each failure printed empty names and a column of zeros, which reads exactly like a real negative result — `for n in A B C; do grep $n ...` returned seven zeros for seven series that are each named thousands of times. **A loop whose variable is empty does not error, it reports absence.** Put the loop in Python, or echo the interpolated command once before trusting its output.

## 2026-10-15 -- A sweep's `UNPARSEABLE` is a claim about its READER first: `ast.parse(str)` rejects a BOM the importer accepts `[lane probability-differential-sweep-1015, session ffbcd001]`
- **What was believed:** the converter tripwire listed `wnba/recon_tools/build_live_player_lens_tuning.py:<UNPARSEABLE SyntaxError>`, read as "check that file parses".
- **What was true:** the file imports. It starts with a UTF-8 BOM carried from its vendored source. The sweep opened it as `utf-8`, so U+FEFF reached `ast.parse` as a character. Fixed by reading `utf-8-sig` (`b2f40e6f`).
- **How to apply:** before calling a file broken on a tool's say-so, parse it the way Python imports it (`ast.parse(open(p, 'rb').read())`). Any AST walker in this repo should read `utf-8-sig` or pass bytes.

## 2026-10-15 **a lead I file is not evidence, and "the obvious cheapest fix" is where a deliberate protection gets deleted** `[lane segment-series-vocabulary, session 4ab694ed]`

- **What happened:** I filed three ordered asks and labelled one of them cheapest — *"make the board's demand plumbing ask for segment rungs it already prices"*. Taking it an hour later, the filter it names is deliberate, its docstring says why, a 13-name refuse-list test pins it, and the module records the real-money incident that installed it: **$7.08 across five orders that priced "under 2.5 runs in three innings" against the venue's price for nine innings.** The ask would have re-opened it.
- **Why the ask looked cheap:** `demand_rungs = 0` reads as an obvious omission. A deliberate zero and an accidental zero are the same number. The repo already has the data-side rule (`attributed_zero` — a zero WITH a stated reason is the guard working); this is the **code**-side twin, and the stated reason lives in the docstring of the thing that produces the zero.
- **Rule: before acting on a lead, read the docstring of the line you intend to change, and grep the tests for its name.** Both were one command away here, and either alone would have stopped it. A lead written by me carries exactly as much authority as a lead written by anyone else, which is none until re-grounded — and that is now the THIRD time this session a lead of mine has been wrong when taken (stale triad numbers, a guessed `edge_unavailable_reason`, this).
- **What saved the write-up from the same error twice over:** the one real gap I found (`_KALSHI_SERIES_BY_MARKET` missing `("mlb","h2h","first5")`) survived two checks and failed both — its callers are fee-only, so it cannot mis-pair, and `KXMLBF5` has no measured fee rate, so adding it would be inert. **Check reachability, THEN check effect.** Either check alone would have let a no-op ship as a fix.

## 2026-10-15 **a predicate whose FIELDS no longer exist returns a clean zero, and a clean zero that agrees with your prior is the hardest kind to catch** `[lane ncaaf-segment-refusal-cost, session 4ab694ed]`

- **What happened:** I re-ran the 2026-09-06 measurement that holds `_SEGMENT_REFUSAL_ENABLED = True`, using its own documented predicate (`venue_basis.venue` set AND that venue in `book_prices`). It returned **0 refusable / 0 displayable / 0 servable for every sport** — exactly the 09-06 result. Then I checked the payload: **neither key exists on any of 4,535 served rows.** Absent from the schema, not null.
- **Why it nearly landed:** the zero AGREED WITH THE PRIOR. A disagreeing zero gets investigated; a confirming one gets written down. The only thing that caught it was the script printing `NO row wears a venue price -- EMPTY FRAME, not a confirmation` — a note I wrote because the lane's own falsification clause demanded it, not because I suspected the fields.
- **Rule: before reporting a predicate's result, assert its FIELDS are present on the population.** Count the rows that carry each key, not just the rows that satisfy the predicate. `sum(1 for r in rows if KEY in r)` is one line and distinguishes "the condition is false" from "the condition is unaskable".
- **And the second-order consequence, which is worse than the first:** a LIVE FLAG is held on by a measurement whose method now returns zeros to anyone who re-checks it. **When a decision cites a measurement, the measurement's own reproducibility decays** — so a decision record should name the FIELDS it read, which this one did (that is the only reason the drift was findable at all).
- **Attribute every zero to a side.** Reported correctly, the equivalent predicate's zero is the THIRD kind: 1,265 rows carried a `venue_ref` and 93 were segment, and the INTERSECTION was empty. "Neither side empty, intersection empty" is a finding; "0" is not.

## 2026-10-15 -- A SHEET BUILT RIGHT AFTER A REFRESH-WORKER RESTART READS A HALF-BUILT BOARD; A TEST KEYED ON THE PROVIDER'S OWN NAMES HID A 0-OF-11 GAP `[session 9e18a0e7, lanes cheat-sheets / mlb-pitcher-recent-form]`
- **Measured:** the NFL cheat sheet built at 15:57:36Z, 1.5 min after the claimed refresh-worker restart, came out at 21 groups / 32 rows; the same build at ~16:03Z gave 66 / 158 (147 before the restart). The board API answers during the first post-restart build with whatever it has.
- **Rule:** after a refresh-worker restart, build or measure anything that reads the board only after the first post-restart `BOARD_BUILD_TIMING` is followed by a `LOOP_ITERATION` (persisted) -- the same gate check_deploy_safety uses.
- **Measured:** `test_mlb_pitcher_gets_recent_form_from_starts` passed for weeks with market "pitcher_strikeouts" while the board names it "strikeouts" -- 0 of 11 board pitcher props got recent form (2026-10-15).
- **Rule:** a provider test feeds the CONSUMER's real field values (copy them from a served payload), not the provider's own vocabulary; and it must fail with the fix removed (checked here by disabling the alias).

## 2026-10-15 **a test file is never a typo for its module — and a fuzzy-match heuristic that cannot say so will call every pre-written test path a defect** `[lane claim-checker-test-prefix-near-miss, session 4ab694ed]`

- **Measured:** `test_team_recent_results.py` vs `team_recent_results.py` scores **0.898** on `check_lane_claims._near_miss`'s 0.85 difflib cutoff. That one claim of 381 made the checker exit 1 on origin/main, so **every session's start digest read `LEDGER INCOHERENT`** — the second time in two days a single false positive from this instrument did that (the first was the `pre-opener` substring).
- **The remedy it printed was worse than the alarm.** The lane already claimed the module on the same `Files:` line with a section scope; following *"almost certainly a TYPO for <module>"* would have duplicated that claim and deleted the test-path reservation. **A heuristic that prints a FIX has to be held to a higher bar than one that prints a WARNING**, because the fix gets applied by someone who trusts it.
- **Rule: when a checker proposes a correction, verify the proposal resolves to something the lane does not already hold.** Two minutes of `_claims()` lookup distinguishes "you typo'd this" from "you reserved a file you intend to create". Third time this session that following this checker's printed remedy would have manufactured a contest.
- **And on mutation testing, which earned its keep twice here:** it reported a survivor for a clause I had just written (`test_name == module_name`) that **could not change any outcome** — dead code wearing a guard's clothes, now deleted. Then the empty-string clause beside it ALSO survived, until I pinned the one case it changes. **A surviving mutant is either dead code or a missing test, and the two look identical until you work out which.** Its comment had named the case correctly all along, so reading the comment was not enough; only the mutant proved nothing tested it.

## 2026-10-15 **asserting STALENESS about a record you have only grepped — the third display-limit error of one session** `[lane none (checkpoint), session 4ab694ed]`

- **What I did:** grepped `todo.md` for my session id, got #688's one-line header, and wrote into a checkpoint that *"the todo's framing is stale"* and that #688 was *"the only substantive work owed to this session"*. **#688 is 46 lines.** Its body already recorded `fail=0, info=0` as its own finding and already scoped what was LEFT (NFL/NBA live re-sim, ncaab no live tier) — more precisely than I then did by running the checker myself.
- **The user acted on my report** and asked me to strike the stale framing. There was nothing to strike but my own sentence. A wrong summary does not stay inside the summary: it becomes someone else's instruction.
- **Rule: before calling a record stale, READ THE RECORD.** `grep` gives you a line; staleness is a property of the document. For a `todo.md` item that means from its `### ` to the next one — and `ledger_io.block_spans` already exists to do exactly that for `###` blocks.
- **THE PATTERN, three times in one session, and it is one pattern:** (1) a log line cut at 220 chars turned `kept_in_window=5149` into `53`; (2) a grep spanning two sections of one report returned 2 and answered neither question; (3) a grep returning 1 line of 46 produced an assertion about the other 45. **Each time the instrument was a DISPLAY LIMIT and I treated its output as the object.** The fix is the same in all three: bound the read to the object (whole line, one section, whole block), never to what fits.
- **Corollary worth keeping:** my "discovery" that the checker is green was a RE-measurement of something recorded. That is not waste — re-measuring is cheap and the reading was real — but it must be reported as agreement with the record, not as a finding about it.

## 2026-10-15 — RULE: replay the PRODUCTION call path's own grouping, not a helper that answers the same question differently `[lane soccer-starter-club-move, session b9bb5f37]`
- **Belief overturned:** I reported confirmed-starter resolution "in production" as 2,142, then 2,156, using `poll_soccer_live_state._team_player_rows` to pick each club's rows.
- **What was true:** that helper FUZZY-matches the team, so it included comma-joined rows ("Everton,Manchester City", ligue_1's 31 "Paris Saint Germain,Rennes"). Production's `build_soccer_artifacts._attach_confirmed_starters` keys rows by the EXACT team string and never sees them. Production resolved 2,132, so my figures were 24 too high, and the gap itself was a bug (fixed bffcaebf).
- **Rule:** an offline replay that claims a production number must call the same grouping or keying function production calls (or reproduce it line for line), and say which one it used. Same family as the 2026-10-14 SYNDICATE_DATA_ROOT rule: a helper that gives the plausible answer is not the code that ran.

## 2026-10-15 **a surviving mutant is dead code, a missing test, OR a mutant that does not do what it claims** `[lane soccer-prop-skill-registry-gap, session 4ab694ed]`

- **Three survivors in one session, one of each kind.** (1) A `test_name == module_name` clause in `check_lane_claims` that could not change any outcome — **dead code**, deleted. (2) The empty-string clause beside it, whose one reachable case (`_is_test_of("test_", "")`) nothing covered — **missing test**, pinned. (3) A registry mutant labelled "cites a different source" that actually added an unrelated `_drift` field and never touched `source` — **a bad mutant**, rebuilt. All three LOOK identical in the output: `78 passed *** SURVIVED ***`.
- **Rule: read the mutation before believing the survival.** A survivor is a claim about three different things and only the diff distinguishes them. Checking the anchor count is not enough — mine matched, applied cleanly, and mutated nothing that mattered.
- **Corollary that saved this lane from a worse error:** the existing suite caught MY test asserting `skill_note(...)["status"] == "measured"` when `test_note_is_compact_and_carries_no_status` documents that the note deliberately carries no status (it is added by `normalize_existing_note` at the row). **When a new test fails against old code, suspect the new test first** — the old one has survived more days.
- **And the substrate lesson, which is the reason the lane existed:** the omission this fix closed was CORRECT when written and carried its own reason ("no board row carries `player_shots`"). A reason that is a fact about today is an **expiry date**, and nothing watches it. 383 rows ranked ~9.3% too high for ten days because a true sentence stopped being true. Same family as `documented caveat is a scheduled defect`, now with a measured cost.

## 2026-10-15 — A ledger entry written BEFORE `session_worktree.py land` cites SHAs the land's rebase replaces `[lane soccer-uefa-competitions]`

- **What happened:** twice in one session, a checkpoint cited the branch's SHAs (`61415354` -> `a0954c2e` -> `f9d06686`). Each rebase (one manual, then `land`'s own) rewrote them, so the ledger named commits that never reached main.
- **Rule:** cite a commit by SHA only after it is on origin/main. Read the SHA off `git log origin/main` after the land, never from the branch. If the ledger must ship in the same land, cite the commit SUBJECT, then correct it to the SHA in a follow-up ledger commit. Repeats the memory rule "never write an unseen SHA"; this is its rebase form.

## 2026-10-15 **asserting a mechanism is ABSENT from one function's behaviour, when a different consumer implements it — and three self-consistent wrong measurements on the way to noticing** `[lane skill-pocket-reward-reachability, session 4ab694ed]`

- **The claim:** "a pocket carries no reward field, so `skill_reliability` returns 1.0 and a bucket measured to beat the market ranks identically to one never backtested." Every clause true; the conclusion false. `skill_reliability` is the CATEGORY factor. Pockets are consumed by `measured_bucket_skill.bucket_factor`, which `layer2_board` consults FIRST, where a pocket **cancels the category demotion** — live on **794 of 4,549** served rows, and cancelling **244 of the demotions I had shipped an hour earlier**.
- **Rule: a field's absence from struct A proves nothing about mechanism M until you have found M's consumer.** I measured `established_loss_rel is None` on 14 buckets and concluded about ranking. The ceiling, the rationale and the consumer were all in ONE file I had not opened. This is the same shape as `absence of a response needs its own check`, one level lower: not "does anything respond" but "does THIS function respond".
- **THREE invalid measurements preceded the right one, each self-consistent:** (1) comparing against a table whose loader had RAISED, so the comparison ran on an empty dict and reported 0 matches; (2) calling `bucket_ids` on the RAW row instead of through the scorer's `view_from_candidate` adapter, so every id stamped `|unknown|` in the phase slot against a `pregame`-keyed table — which produced "0 of 1,414 match" AND a tidy false root cause about a broken ONE-DEFINITION promise; (3) a service-split hypothesis falsified by one read. **Each had a plausible mechanism attached, which is exactly why none felt wrong.**
- **What distinguished the valid measurement: reading the CALL SITE.** `layer2_board` calls `bucket_factor(view_from_candidate(row))`. One grep for the caller replaced two hours of plausible wrongness. **Call it the way production calls it, or you are measuring your own call.**
- **And the downstream cost, which is why this matters beyond the lane:** a wrong claim of mine reached `state_model.md`, a findings file, a lead, and a `deploys.md` verify line before being caught. Three of those four are corrected in the same commit as this entry. **A wrong measurement does not stay where it was made.**

## 2026-10-15 RULE: a refresh-worker-only restart must not wait for exit-0 CLEAR -- and a verdict-line gate must match the BLOCKER wording, not a prefix the healthy line shares `[lane nhl-puckline-orientation, session 1eabcf3d]`

- **Exit 0 is the wrong gate for a refresh-worker TERM.** `check_deploy_safety` blocks on live-odds-worker child jobs and on an odds refresh stamped `lane=live-odds-worker`, and a refresh-worker TERM touches neither. Measured 2026-10-15 21:25-21:53Z: exit 0 never came in 28 minutes, because live-odds-worker and refresh-worker soccer odds cycles run almost back to back. The window the user's rule actually asks for (`Board build idle ... persisted`, `refresh-worker child jobs: none`, no MLB sim) came twice in that time, at 21:28:05Z and 21:53:40Z.
- **My first narrowed gate missed the first window.** It matched the substring `refresh-worker child job`, and the HEALTHY line `refresh-worker child jobs: none` contains it, so every healthy reading read as blocked. Silent: the log said `blockers=1`, never "error".
- **Rule:** match the blocker wording exactly (`child job RUNNING`, `child jobs UNKNOWN`, `Board build IN FLIGHT`, `state UNKNOWN`). REQUIRE the positive lines (`child jobs: none`, `Board build idle`) to be present, so a missing or empty reading can never pass. Replay the predicate over the real readings you have already logged before arming it: the replay here classified all four logged readings correctly, including one empty-output reading, and the TERM fired on the next window. Check, kill, pid-unchanged and claim-holder go in ONE iteration (`deploys.md` 2026-10-15 21:53:40Z).
- **Also:** `deploy_claim.py acquire` will not renew a claim its own holder holds ("Not acquiring"). To extend, `release --token`, then `acquire --ttl <s>` and capture the new token.

## 2026-10-15 RULE: a "ROI CI excludes 0" signal rule measures the VIG on any population with EV < 0 cells -- test realised ROI against the cell's OWN predicted EV `[lane sim-gap-ev-study, session 9e18a0e7]`
- **Pre-registered, then wrong:** the sim-gap x EV study registered "a cell counts when its game-bootstrap ROI CI excludes 0". Run 1 (476 games, 09-30..10-14) found 149 signals: 146 negative, and 142 of those sat in EV < 0, where a FAIRLY priced bet loses by design (-110 vs a 0.5 fair is -4.5%). 96.6% of bets in the population are EV < 0, so the rule mostly counted the vig.
- **Rule:** the null for a betting cell is its own predicted EV. Use realised ROI minus mean EV, with a game CI. Keep the registered column, labelled, and record the amendment in the instrument (`sim_gap_ev_study.PREREGISTRATION["amendments"]`) before anything rests on it. Run 2 with that headline: 65 of 321, ~16 by chance, 43 of them one-sided soccer fairs that realise far below what they promise. That is the known ~8.5-point overstatement of `book_margin_model` -- a real finding the vig-rule hid.
- **Companion:** never pool a two-sided fair with a one-sided one. Pooled, soccer's sim looked BETTER than the market; split, it ties on two-sided markets and the effect sits entirely in one-sided fairs.

## 2026-10-15 RULE: `monkeypatch.delenv(name, raising=False)` on an ABSENT variable records NOTHING -- code under test that later WRITES `os.environ[name]` leaks it for the rest of the process `[lane cheat-sheets, session 9e18a0e7; found by lane ci-suite-red-1015]`
- `build_cheat_sheets.align_data_root` sets `SYNDICATE_DATA_ROOT` from `--data-root`. A test that ran `main` inside a TemporaryDirectory left the variable naming a DELETED dir, and 12 NCAAF tests later in the same CI chunk lost their team registry (todo #697). The suggested one-line fix, `monkeypatch.delenv(..., raising=False)`, did not help, and the sibling test already using it leaked too: monkeypatch only restores what it recorded, and an absent key is never recorded.
- **Rule:** to start a test with a variable unset AND restore the original on teardown, call `monkeypatch.setenv(name, "x")` and THEN `monkeypatch.delenv(name)`. Prove a leak fix with a probe test that FAILS after an unguarded call and passes after the fixed tests. A worktree without `data/` cannot run the NCAAF half of the pair, so the probe is what verifies there. The owner of the CI checkout confirmed the pair: 12 failed before the fix, 0 after (dd3c0085).

## 2026-10-15 — REPEAT of the 2026-09-16 FORBIDDEN (opening a file for write before its content is built) `[lane soccer-uefa-competitions]`

- **What happened:** a ledger helper wrote `open(p, "wb").write(fn(s))`. Python evaluates `open()`, which TRUNCATES, before `fn()`. `fn` raised on a failed assert, so `.syndicate/state.md` went to 0 bytes: 744 deleted lines staged, with no error naming the file. It was caught by reading `git diff --cached --numstat` (0 added / 744 deleted), restored from HEAD, and never committed.
- **The one-line form is the trap:** `open(p, "wb").write(build())` LOOKS like build-then-write. Always build into a variable first, then `with open(p, "wb")`. Check `--numstat` deletions before EVERY ledger commit.


## 2026-10-15 RULE: the null for a ONE-SIDEDNESS claim is the MEASURED directional base rate, never 50/50 `[lane model-edge-ceiling-implied-probability]`

- **What happened:** the ceiling study found six player-prop families whose
  large-gap rows were 100% on the UNDER side (ncaaf rushing yards 0/16, nhl
  assists 0/14, nhl points 0/10, nfl passing tds 0/9, ncaaf passing yards 0/8,
  nhl saves 0/6). My instinct was to score these against a fair coin, which
  gives 1.5e-05 for the 0/16 and reads as overwhelming proof of a defect.
- **The measured base rate was p(over) = 0.334, not 0.5** -- the large-gap
  population is ALREADY 2:1 under platform-wide. Against the real null the same
  families are only p = 1.5e-03 .. 8.7e-02, and the weakest is unremarkable.
  The 50/50 null overstated the strongest case by **two orders of magnitude**.
- **Rule:** before claiming a split is one-sided, compute the direction's base
  rate IN THE SAME POPULATION and score against that. A platform-wide skew is
  exactly the kind of thing that makes every subgroup look one-sided.
- **And report the aggregate as the finding when no single cell survives:** six
  co-occurring one-sided families is the real signal here, so it is stated that
  way rather than by quoting the smallest p-value in the table.
- **Companion:** the same-day rule that a betting cell's null is its own
  predicted EV, not 0. Both are the same mistake -- assuming a null instead of
  deriving it from the population in hand.

## 2026-10-16 RULE: one statistic, two owners -- the EV fair and the projection's anchor fair are computed differently, and a row can be +EV against one and -EV against the other `[lane fair-price-v2, session 9e18a0e7]`
- Measured on the 10-15 NBA board. The QUOTE fair behind `ev_pct` / Suggested / the sizer / the cheat-sheet `p_market` takes every grid cell, STALE INCLUDED (`layer2_board._resolve_fair` -> `_two_sided_prices_by_book`). The GRID fair behind the projection blend uses cells within 900 s of the freshest only (`book_grid.py:663-702`).
- On the Knicks total 225.5, 7 of 8 books had moved off the line hours earlier. The stale median made one book's +107 under look +3.5% EV, and it was the only Suggested NBA row. Fresh-only, it is about -4.6%.
- Stale share inside the quote fair on the served board: 34-78% by sport.
- **Rule:** before reading an EV, a sim gap or a "sim agrees", find which fair each side of the comparison used. Two fairs on one row is a defect until shown otherwise. Fix it at the producer, as one fair (H5, `fair-price-v2`), not with a reconciling patch at a reader.

## 2026-10-16 RULE: a display fix must target the payload the page READS -- the board page reads the embedded intelligence payload, whose cards carry no `projection` dict `[lane live-winpct-blank, session 9e18a0e7]`
- I wrote the "pregame proj" label to read `item.projection.pregame_on_live`. The flag was set correctly, and verified on the shortlist API (114 of 114 NFL rows). The page still showed 0 labels on 22 live rows.
- The page reads `initial-intelligence-response`, 17 MB, built from cards (`layer2_rows_to_board_cards`) that drop the projection dict. The fix was a card column.
- **Rule:** verify a UI change on the page's own payload, not on an API that looks equivalent. Card columns are built on the refresh-worker (`book_grid_artifact`), so a web reload does not deliver them; a worker restart does.

## 2026-10-16 RULE: "green in my worktree" is not evidence about the fleet ci-suite -- verify in `~/syndicate-prod/ci-checkout` under `run_ci_suite._step_env()`, in chunk ORDER when a test passes alone `[lane ci-suite-red-1015, session b9bb5f37]`
- I classed 11 of 42 CI failures "already green on main" from a worktree run. Session worktrees exclude `data/`, CI's checkout has all of it, and 10 of the 11 still failed: they read real repo data the fixtures never pinned (settlement rows, season write-ups, an NFL props CSV, a roster snapshot).
- 5 more (test_paper_execution_batch) passed in ANY single-file run and failed only in CI's chunk (`files[i % 8]`, `-n 0`). The leaker: a test patched `execution_mode`/`live_execution_armed` BEFORE the first import of a module that binds them BY NAME. That module then kept the lambdas for the rest of the process. Its `write_json_file` patch also missed a LOCAL import inside the function.
- **Rule:** reproduce in ci-checkout with `_step_env()` and the fleet venv (`/home/amyn/.venvs/syndicate/bin/python`). For pass-alone/fail-in-CI, bisect the chunk prefix. When patching a name that other modules import by name, import those modules FIRST. Patch where the function LOOKS IT UP, not where it is defined.

## 2026-10-16 -- RULE: a swallowed-exception persist path + an object built at runtime = silent TOTAL loss; test the round trip `[lane basketball-scenario-calibration, session e0a3e383]`
- **Measured (P3's catch):** the new `nba_engine_config.json` cfg was a `make_dataclass` class built at runtime.
  pickle cannot find such a class by name. `_persist_engine_inputs_once_local` swallows every error, so the day the
  file went on, every NBA game would silently have lost its live-resume inputs. No test failed; the unit tests never
  pickled the cfg.
- **Same session, related:** "same seeds per game" was pre-registered and was false. The harness is run-to-run
  nondeterministic (the same code twice: 0/11 identical games), and a FIT-only finding (late-Q4 ML worse) did not
  replicate on VALID.
- **How to apply:**
  - Any object that crosses a persist / pickle / process boundary gets a round-trip test, including a load in a fresh
    process.
  - A write path that swallows errors needs a test that the write SUCCEEDS.
  - Measure determinism before claiming a same-seed pairing.
  - Treat a single-window finding as a lead until a second window agrees.

## 2026-10-16 -- RULE: a drift visible in point estimates is not a predictive gain; register the time-varying model and test it against the constant `[lane uefa-offsets-recency-prod, session 570a6cd1]`
- **Overturned belief:** "the UEFA offsets drift, so a 12-season constant is stale for 2026 use" (findings 2026-10-16, uefa-league-offsets).
- **Measured:**
  - The drift reappears on production's scale. Recency-weighted EPL−La Liga is −0.19 against −0.11 under the constant.
  - Yet recency-weighted offsets LOST to the constant out of sample: +0.0010 [−0.0024, +0.0048] over 1,278 matches.
  - Every half-life from 1 to 4 seasons was ≥ the constant, and the 2020-26 subset was no better.
  - Down-weighting halves the effective n, and β drifts together with the offsets.
- **How to apply:** before serving a time-varying parameter because an era split "looks different", run the registered walk-forward against the constant. Report the effective sample size the weighting leaves.

## 2026-10-16 RULE: a SUPPORT field is only a gate if you measured that it VARIES across the population first `[lane nfl-prop-support-fields -> nfl-prop-opportunity-volume]`

- **What happened:** I shipped `sample_games` onto NFL prop rows to give the  board something to gate on besides edge magnitude. It was correct,  reachable, tested, and **useless**: measured afterwards over 157  ceiling-rejected vs 453 accepted markets, its median is **5.0 on both  sides**. In week 6 it is a CALENDAR count — it cannot tell a rotational  player from a starter, which is the only thing it was wanted for.
- **The field that worked** was the projected OPPORTUNITY (receptions /  carries / attempts): 0.67..10.33, a 15x spread, and 4 of the 6 players  under 1.00 were the known-bad rows.
- **Rule:** before publishing a field so something can gate on it, compute  its distribution over the population it must separate — count,  distinct values, and the two sides' medians. A field with no spread is  indistinguishable from a working one at every level except the data,  which is `model_engine_standard.md`'s own failure mode.
- **It generalises to provenance too:** NHL's `sim_starter` is 4/364 (sparse  by design, goalies only) and `game_type` is constant; MLB's  `is_lineup_batter` is True on all 414 rows. Each is worth publishing as  provenance and worth NOT calling a gate. Applied prospectively on both,  which is the only reason those two lanes did not repeat the mistake.

## 2026-10-16 RULE: there is no quiet window on this fleet during active hours — board builds run back-to-back `[measured]`

- **Measured, and CORRECTED by the longer run of the same watcher.** The first 63 cycles (15:19Z-16:15Z) had a board build IN FLIGHT in every one, and I first wrote this rule as "there is no quiet window". **That was overstated.** Over the full **116 cycles spanning 16:05:39Z-16:53:05Z**, five had `board_build=0` and **one was a genuine refresh-worker-side window** (16:52:59Z, `rw_children=0 board_build=0`).
- **So windows DO occur — about 4% of 45s-sampled cycles — and they are SHORTER THAN THE SAMPLING INTERVAL.** The 16:52:59Z window was gone 60 seconds later with a fresh build already in flight. Build length varies too: `typical` read 8.5min earlier and 7.1min at 16:53Z, so the gap between builds is not predictable from one reading.
- **Why the distinction matters:** `check_deploy_safety` ends with "Wait, or proceed deliberately", which reads as though waiting will clear it. Waiting does clear it — rarely, and for less than a minute. "None exist" would say do not watch; "rare and sub-minute" says a WATCHER CANNOT BE THE MECHANISM unless it ACTS within seconds of seeing one, which for a production restart means acting unattended. That is the real trade, and it is not one a safety watcher should make by itself.
- **Rule:** for an OBSERVABILITY-only change, do not chase a window — record the reading as owed and let the next restart by anyone carry it (that is how `5457b428`'s reading arrived, inside the hour). For a change that must go now, proceed deliberately and SAY in `deploys.md` that a build was discarded. Either way, do not budget session time on waiting: the window exists but you will almost certainly be told about it after it closed.

## 2026-10-16 -- the book-quote shard is a CHANGE log: compare the same groups, never window against window
`<sport>_source/tracking/book_quotes/<date>.jsonl` gains a row when a book's quote moves (`snapshot_ts` is per book, not
per fetch). After the props book lists shipped, "books per group after 17:31Z" vs "before" read as a DROP (NFL median
7 -> 2, NCAAF 3 -> 2) because 20 minutes of changes were set against a morning of accumulation. On the SAME groups,
before vs before+after, it was a gain (NFL 7 -> 9, NCAAF 4 -> 5, NHL 2 -> 5). **How to apply:** any before/after count
from this shard compares one population with itself; a window comparison measures how often prices move, not books.


## 2026-10-16 -- "Stale relative to the freshest book" compares feeds that run on different clocks (session 9e18a0e7)

**Belief overturned:** the 10-06 seen-basis rule ("a cell is stale 15 min behind the most recently SEEN book on the
market") was taken as the fix for collapsing book counts. It still collapsed them whenever ONE venue is captured more
often than the rest: Kalshi / ProphetX pollers vs hourly sportsbook prop fetches -> Martinez K 2.5 read 1 of 10 books,
the board priced it against Kalshi's own two sides, and 20+ of 66 suggested picks rested on one venue.
**Rule:** judge a quote against ITS OWN BOOK's latest capture of the event, plus a separate dead-feed ceiling -- never
against another feed's clock. And read the LATEST start time on a line: quotes keep the old one when a start moves.
**Measurement trap, also from today:** "sides with 1 fresh book while >= 2 quote" counts MOVED LINES (every other book
re-posted at a new number) along with the defect -- 369 of NFL's 405 were correct. Before using a staleness share as
a pass/fail line, split out rows whose stale books are fresh at another line of the same bet.


## 2026-10-17 -- a published graphic is a commitment; a section recomputed per build cannot be reconciled to it (lane `cheat-sheets`)
**Belief overturned:** "a day's sheet is a record" (the blueprint's docstring). That was true for STARTED games' rows only.
Before the start, each build, page view and record recomputed every section from that moment's rows. A posted section
could therefore change under the post: NHL 10-16's 12:34 PM graphic (2 rows) became a 5-row section with one posted row
gone, and the record graded the 5.
**Two mechanisms, both ordinary:**
1. Side selection by best EV flips with small price moves: Karlsson u2.5 at 7/10 lost to his over by 3.2 EV points.
2. The board posts more props through the day: 108 groups grew to 186.

A third came from my own process: four manual full rebuilds, run to deploy unrelated sections (the ladder and
parlays), rewrote the published one.
**Rule:** record what was published at the moment it is published, server-side, from the served data (d956cbcc:
export = posted). Pin it in display and grading, at the published price. Never infer "what was posted" from the last
build.

## 2026-10-19 RULE: a missed one-time task may fire VERY late or not at all, and the task LISTING cannot tell you which — only `list_task_runs` can `[lane ncaaf-segment-refusal-cost]`

- **CORRECTED WITHIN THE HOUR, and the original claim was FALSE.** I first wrote that such a task "never fires again", from a listing showing `enabled: true`, a past `nextRunAt`, and no `lastRunAt` on 8 of 209 tasks. Re-checked 40 minutes later with **`list_task_runs`**, **three of those had fired that same afternoon** — `wnba-1017-watcher-rearm` at 15:25:57Z (~44 h late), `wnba-1017-period-lines-reading` at 15:37:58Z, `layer2-suggested-weekend-grade-1019` at 15:40:20Z. **The backlog was draining while I was writing the rule.**
- **What is actually true:** a one-time task whose slot passes while the host sleeps goes into a backlog that MAY drain much later (38-44 h observed) or may not drain at all — 4 of the 8 still showed `totalRuns: 0` after the others had fired. Both outcomes are real; the listing cannot distinguish them.
- **The instrument:** the listing's absent `lastRunAt` means "has not run YET", NOT "will never run". `list_task_runs <taskId>` returns `totalRuns` and each run's `started_at`/`status`, which is the only thing that answers it. Reading the listing alone is how I got this wrong.
- **THE REAL HAZARD IS NOT THE MISS, IT IS THE LATE FIRE.** A reading armed for a live Saturday that fires on Monday afternoon measures a slate its prompt was never written for, and will report a confident zero from an empty frame. `wnba-1017-*` tasks fired on a Monday with no WNBA game in play. So an armed reading needs a prompt that PROVES its frame is live and re-arms rather than reporting, which is exactly what `ncaaf-segment-refusal-cost-1017`'s prompt was written to do.
- **Rule:** after any gap where the host may have slept, audit one-time tasks with `list_task_runs`, not the listing. Re-arm only for a date the POPULATION exists on, and never re-arm another lane's task — the date carries a requirement only its owner knows. And write every armed prompt so that a late fire refuses rather than reports.
## 2026-10-19 -- RULE: split the model-vs-market gap by component BEFORE improving a component `[lanes uefa-outscope-ratings -> uefa-close-backtest, session 436c79e2]`
- **Overturned belief:** "UEFA pricing is weak because of the UEFA-specific parts (league offsets, out-of-scope club ratings), so better UEFA parts get it to market." Two registered steps improved those parts and both were SUPPORTED against their own baselines (offsets -0.0555, OOS fitted vs prior -0.0072).
- **Measured:** against the de-vigged close the model trails by +0.0286 overall, and by **+0.026 on in/in pairs and +0.026 on in/OOS pairs**, so the UEFA parts add nothing to the gap. The walk-forward blend weight fell 0.35 -> 0.05 and the gate was NO-GO for all three competitions. The gap is production's domestic rating (favourites underrated, the same signature as the domestic +0.022).
- **How to apply:** a SUPPORTED verdict against an internal baseline (prior-only, no-offset) says nothing about the distance to the market. Before a second component study, score model - close split by the component's subsets (here: pair type). If the gap is flat across them, the component is not the bottleneck, and the next study belongs upstream.

## 2026-10-19 -- an MLB gamePk is not a date: feed/live follows the reschedule (lane `mlb-postponed-grading`)
**Belief overturned:** "guarding `detailedState: Postponed` makes postponed MLB games safe to grade." That holds only while the feed
still says Postponed. 849817 (TB @ CLE, slate 10-16) read `abstract Final / coded D` at the postponement. Within a day the SAME
gamePk's `feed/live` described the makeup game (`Scheduled`, `officialDate 2026-10-18`), and after it was played, `Final` TB 3-1.
The schedule endpoint for 10-16 keeps the Postponed row. `settle_locked_policy_cards._load_feed` writes whatever it fetches into
date D's feed path, so a re-settle after the makeup game would have stored, and graded, 10-18's score as 10-16's.
Nothing graded this time only because the one-shot settlement ran in the 'Scheduled' window.
**Rule:** a grader for slate date D checks `gameData.datetime.officialDate == D` as well as the not-played coded state
(D/C/U). Use `syndicate/features/mlb/game_status.grading_refusal(feed, D)`. A clean result for a postponed game is TIMING until both are checked.

## 2026-10-19 -- RULE: before blaming the EV for "high claimed EV loses", split the DOLLARS into EV-only and sim-added `[lane ev-overstatement-decomp, session 24ac7737]`
- **Belief overturned:** the 3rd measurement of the 2026-09-29 STANDING anti-correlation (tuner backtest: stake ROI [4,5) -8.3, [5,7) -9.8) was read as "the EV stamp is overconfident above ~4%". It is not, at the resolution 17 days allow. Against the closing consensus fair the stamp keeps its band order (claimed 4.40 -> +4.11 at the close), and every fair-quality component tested is flat. The band-shaped loss sits in the sim's ADDED stake (`sim_share_of_stake`): -11.2 / -17.5 at [4,5) / [5,7) vs EV-only -4.2 / -4.0. That stake is sized at w = 1 while the fitted w on the same orders is -0.27 [-0.78, +0.18]. Pooled over EV>=2 the sim dollars are no worse than the EV-only ones (-2.9 vs -3.2): they amplify each band's noise, they do not bias it.
- **Rule:** a stake-weighted ROI is a statement about the SIZER as much as about the selection. Before reading it as an EV problem, (1) split each order's pnl pro rata into `1 - sim_share_of_stake` and `sim_share_of_stake`, (2) grade the claimed EV against the CLOSING consensus fair, which is far less noisy than outcomes, and (3) split by sizing regime: the sim was gated (share 0.00) 10-02..10-04 and sized 52-83% of dollars from 10-05. Flat units and EV-only dollars are the threshold's evidence; sim dollars are the sizer's.
- **Also, a near-miss on the 2026-10-09 FORBIDDEN rule:** I read the refresh-worker's env with `tr '\0' '\n' < /proc/<pid>/environ | grep -o "^SYNDICATE_..."`. The anchored grep printed only the data-root path, so nothing leaked, but the rule forbids line-splitting environ in a shell pipeline at all. Read env in Python.

## 2026-10-19 -- RULE: a join replay must run the SERVED join path on the SERVED inputs, not the name resolver `[lanes uefa-oddsapi-club-aliases -> kalshi-event-scoped-codes -> kalshi-join-all-game-lines, session 436c79e2]`
- **Overturned belief:** "15 UEFA club aliases take the Kalshi->board join from UEL 12 / UECL 11 to 18 / 17 of 18." My replay predicted that. It checked that `canonical_team` resolved both club names, and did not run the join.
- **Measured on the served grid after the restart:** UEL 6, UECL 11. The names did resolve. The real losses were:
  - (A) Kalshi club codes shared within one competition (KXUEL LEV, CEL), refused by `build_club_code_collisions`;
  - (B) the join runs against the published SHORTLIST, so a fixture with no shortlist row for the market can never be priced.
- Neither shows up in a name-only replay. The real-join replay (`join_kalshi_to_board` on fleet markets + `read_layer2_shortlist`, under the worker's own env from `/proc/<pid>/environ`) found both in one run.
- **How to apply:** before predicting a served count, replay the function that produces it, on the inputs it reads, in the env it runs under. A resolver-level check is a necessary condition, never the prediction.

## 2026-10-19 RULE: `git commit -m "..."` and unquoted heredocs EXECUTE backticks -- use `-F -` with `<<'EOF'` for anything containing `code spans` `[hit twice in one session]`

- **Twice today, same mechanism, different shape:**
  1. a `deploys.md` append written with `<<PY` (unquoted, so `$NOW` would
     interpolate) ran `` `local_aa5d7792` `` as a command and wrote it as EMPTY,
     leaving "session 3927eb2e (, lane ...". The shell printed ONE
     "command not found" and I had to check whether more had been eaten.
  2. a commit message passed as `git commit -m "... under \`market\` the sim's
     zero-Kelly VETO ..."` ran `` `market` `` and left "under  the sim's", a
     double space where the word had been.
- **Why it keeps happening:** backticks are the natural way to write a code span
  in this ledger's prose, and double-quoted shell contexts are the natural way to
  pass a message. The two are incompatible and nothing warns you -- a
  substitution DELETES text without leaving a mark where it was, so "one error
  printed" is not "one thing broken".
- **Rule:** any text containing backticks goes through `git commit -F -` with a
  **quoted** heredoc (`<<'EOF'`), or is built in Python and written with
  `ledger_io`. Never `-m "..."`, never `<<PY` unquoted. If an interpolated value
  is needed, pass it as an argv parameter to a Python script rather than letting
  the shell expand the document.
- **And verify after, not just before:** both times the fix was to re-read the
  stored text and check every token I intended was present. The first instance
  cost a repair commit; the second was caught the same way but only after it had
  been pushed, so the damage stands in the history as a double space.

## 2026-10-19 -- OVERTURNED: "Kalshi `portfolio_value` is cash plus open positions" (a code comment in `venue_balances.py`, trusted since 2026-08-26) `[lane compounding-bankroll, session 3927eb2e]`

- **What was true:** it is OPEN POSITIONS ONLY. Stamp 2026-10-19T18:13Z: 4.50 with exactly one $4.50 position beside $485.48 cash. Likewise Polymarket `buyingPower` INCLUDES a not-yet-cleared deposit ($550 of $586.05).
- **The rule going forward:** before a venue balance field becomes a SIZING basis, check it against a reading where you know the answer (one known position, one known deposit). Read the fields the venue already sends (`depositReservation`, `displayedAvailableSoon`) rather than inferring from the headline number.

## A helper's `None` has TWO meanings, and my check defaulted unknown to GUILTY `[2026-10-19, lane mlb-strikeouts-scale-check]`

I was one commit away from reporting **193 soccer rows as a defect** — rows whose own `model_skill` note predicts a score demotion and which carry no demotion stamp. I did the right thing first: I ran the REAL `measured_bucket_skill.bucket_factor` over the SERVED rows rather than reasoning about the code. It returned `None`, so I scored them `NEITHER -- DEFECT`.

**`None` from that function means either "no bucket matched this row" or "I have no overlay to match against".** My process had no overlay and said so, in a log line I had already printed and not read: `[skill_overlay] SOURCE=static reason=overlay_absent buckets=0`. Production holds `measured_bucket_skill_overlay.json` with **62 validated buckets of 3,985 tested** (FDR q=0.10, regenerated 11:30Z that morning), and it contains `soccer|player_shots|full|pregame|fair_method=book_margin_model` as a **validated `skill_pocket`** (brier_diff -0.0039, CI [-0.0058, -0.0019], 156 games / 10 dates). A validated pocket returns 1.0 and CANCELS the category demotion — which is the documented design, stated in `_apply_skill_reliability`'s own docstring.

**Why:** `feedback_unknown_must_not_default_permissive` says absent must not map onto the permissive branch. This is its mirror and it is just as wrong: my check mapped absent onto the ACCUSING branch, which manufactures findings instead of hiding them. Running the real function is necessary and not sufficient — it has to run somewhere that can SEE the data the consumer sees, and a worktree cannot (`feedback_worktree_results_are_not_main`: worktrees have no `data/`).

**How to apply:**
- Before reading a helper's `None` as a verdict, establish that its inputs were PRESENT. For an overlay/table-backed helper, assert the table is non-empty in the same process and print the count.
- A three-valued answer needs three branches: matched / did-not-match / could-not-look. Never fold the third into either of the first two.
- The discriminating evidence was already on the row: `optimizer_factor: 0.8816` is stamped only AFTER both of the function's early returns, so its presence proved the code had run and found `factor >= 1.0`. `feedback_read_the_field_you_already_have`, for the Nth time.

## 2026-10-19 — OVERTURNED: "the UEFA model underrates favourites" was a close-sorted decile, i.e. mostly selection (lane uefa-favourite-temper)
- **Belief:** step 3 and the anchored lane reported top decile model 0.778 vs close 0.821 vs actual 0.854, read as "the model underrates favourites", and a favourite-sharpening fix was expected to help.
- **Measured:** ranked by the MODEL's own favourite probability, its top decile is 0.835 vs actual 0.834, already calibrated. The domestic (a2) temperature pushed it to 0.877 and worsened UEFA log loss by +0.0032 [+0.0008, +0.0058].
- **Why:** sorting by the close selects the matches where the close sits above the model, so the model looks low there whatever its calibration (regression to the mean on the ranking variable).
- **Rule:** a calibration/bias claim needs deciles ranked by the PREDICTOR BEING JUDGED. Report the close-ranked table only beside the self-ranked one, never alone. Source: `.syndicate/findings_2026-10-19_uefa_favourite_temper.md`.

## Four times in two days I built a population out of a field whose SEMANTICS I assumed `[2026-10-19, lanes mlb-strikeouts-scale-check + ncaaf-skipped-no-fair]`

Each time the arithmetic was right and **the operand was not mine to combine**. Each time the result looked like a finding and would have been reported as one:

1. **`edge_vs_market_pct` vs `model_edge_pct`** — measured the RAW projection edge where the consumer reads the calibrated one. 16.7x apart on the family I was flagging.
2. **`bucket_factor`'s `None`** — read "no bucket matched" from a process whose overlay was absent, and scored 193 rows as a defect.
3. **`established_loss_rel`** — called the calibration layer inert without checking its consumers; it is read in seven non-test modules, just not through the probability.
4. **`other_sides`** — summed the BEST price per side ACROSS books and compared it to a fair built PER book. `_resolve_fair`'s own comment says *"It is the CROSS-book case that launders"*. 27 rows withdrawn.

**Why:** the shared cause is not carelessness about values, it is treating a field's NAME as its contract. `other_sides` sounds like "the other side of this market" and is really "best price per side across the book set"; `None` sounds like "no match" and is really three-valued. A population assembled this way is self-consistent and wrong, so nothing downstream flags it — which is exactly why these reached the point of almost being written down.

**How to apply:**
- Before a field becomes the BASIS of a population, read the code that WRITES it, not just a row that has it. One `grep` for the writer is cheaper than a withdrawn finding.
- When combining two fields, ask what grain each is at (per book? per side? per market? best-of?). If they are at different grains, the combination is not a measurement.
- A finding whose refutation you cannot state is not ready. All four of these were refuted by evidence ALREADY in the payload or ALREADY in the docstring of the function I was measuring.

## 2026-10-20 -- A post-hoc map fit on a RESEARCH LINK is not evidence about the SERVED SIM: measure the sim's own calibration before porting it `[lane soccer-team-strength, session e44b3e73]`

**The belief overturned:** a correction measured on the research Poisson link (27,285 matches, CI below 0) would transfer to the sim, the way the rating slope did.

**Measured:**
- The link's draw term wanted FEWER draws in mismatches (δ1 −0.36..−0.41).
- The served sim already UNDER-predicts them: 0.197 vs 0.220 actual on 2,724 matches. Refit on the sim, δ1 came out POSITIVE (+0.15) and NOT DEMONSTRATED.
- The link was under-confident on its own top decile; the sim was over-confident on its own.
- The link's 1X2 temperature hurt UEFA (+0.0032).
- Ported as-is, the "SUPPORTED" draw correction would have shipped a regression.

**Why:** a post-hoc 1X2 map corrects one model's SHAPE errors. The sim's 1X2 comes from simulated scores with different mechanics. Rating INPUTS transfer, because the sim reads them with a measured linear gain (R² 0.87). Output maps do not.

**How to apply:**
- Before shipping any map fit on a proxy model, run a descriptive read of the TARGET's own calibration on the same axis (one tercile table is enough).
- Then refit on the target's output under its own registration.
- Pass-through inputs (ratings) need a real-sim do-no-harm A/B before the default flips.


## 2026-10-19 -- OVERTURNED: "the live plan is empty because a gate or a cap is too tight" `[session 6200a74b, findings_2026-10-19_live_execution_empty_plan_funnel.md]`

The brief to diagnose an empty live plan listed EV floors, MAX_POSITIONS, per-game decay, the slate cap, the in-play refusal and the executor caps as suspects. None of them was the zero.

The whole board re-priced at the venue's own ask settled it:
- **Kalshi:** 0 of 556 quoted sides at >= +2% after the taker fee (41 before the fee).
- **Polymarket:** 0 of 324 quoted sides at >= +2% after the fee (24 before the fee).

The exchanges' asks are at or below the sportsbook consensus once their fee is paid. The beliefs about the gates were stale as well: the live commit floor is 0, not 2.0, and max_positions is 25, not 12.

**Why:** a funnel read only through its refusal counters names a gate for every dropped row. That made "loosen the gate" look like the fix, when the population beneath the gate was empty at any setting.

**How to apply:**
- Before proposing any gate or cap change to get volume, count the gate-free population: every row, re-priced at the venue, net of the venue's fee. If it is ~0, no gate change helps. Look for a different edge source or more coverage instead.
- Read the RESOLVED settings from the worker's environ (`resolve_settings()`, `limits()`). Never use the values a brief or a docstring states.

## 2026-10-20 -- A grep of a fleet role log for a failure token COUNTS YOUR OWN GREP: `ALL_PROCESS_MEMORY` lines quote every process's cmdline `[lane execution-alerts, session c1dad17d]`

`live-odds-worker.log` writes `ALL_PROCESS_MEMORY` about once a second, and each line carries the full cmdline of every process on the host. So any session (or watchdog) that greps for `EXECUTION_ERROR` or `[execution_self_heal]` shows up in the log it is grepping, as a match. Measured on the fleet: `grep -c EXECUTION_ERROR` returned 3, and all 3 were memory lines quoting a peer's grep at 22:41:15Z. `grep -c execution_self_heal` returned **160**, and the real count was **0**. Three quoted lines in one second is a full burst for the execution watchdog's `>= 3 per check` rule.

**Why:** a failure-token count reads as evidence of failures. Here it was evidence that someone was looking for them.

**How to apply:**
- Any count of a token in a role log: `grep -v ALL_PROCESS_MEMORY` (and `MEMORY_WATCHDOG`) first. Or anchor on the emitter's prefix with a timestamp, never a bare token.
- Any automated log scan excludes cmdline-quoting lines (`execution_watchdog._QUOTING_LINE`, a4aacc8f).
- Heredoc edits that write a Python regex: Git Bash turned `\b` into a literal backspace (0x08) once in this session. Check the written bytes (`od -c`) or use the Edit tool for regex lines.

## ANNOUNCE A FLEET FF: peers cut their ff targets against the fleet HEAD they last SAW, and a target cut before yours silently drops your change `[2026-10-20, lane board-implausible-book-upper-bound]`

Within 25 minutes of my ff, **two** sessions messaged me with restart plans built on a fleet HEAD of `d3878d69`. It was `e491c260d` — I had ff'd twice (`c36bdc9a` for the worker, then `e491c260` for a web-only fix plus a `reload-web`). Both also believed I still held the refresh-worker claim, which I had released by token; one of them held it themselves by then.

**The dangerous part is not the stale claim, it is the stale TARGET.** One peer's `--ff-only` target `6d7f4ea7` contained `c36bdc9a` but **not** `e491c260`. An `--ff-only` against it is refused, which is the SAFE outcome — but the natural response to a refusal is to re-cut onto something that merges, and anything cut from the same base drops the commits made after it. My API field-list fix would have gone back out without a single error message.

**Why:** the fleet has no notification. A session reads the fleet HEAD once, plans a deploy around it, and then negotiates for minutes or hours while another session moves it. The 60-minute restart rule makes that window LONGER, not shorter, so the staler the plan the more polite the peer was being.

**How to apply:**
- **Say the new fleet HEAD in the message that announces your restart**, not just the restart time and pid. "Fleet is now `<sha>`" is the field peers actually need and the one nobody sends.
- Before any `--ff-only`, re-read the fleet HEAD and check `git merge-base --is-ancestor <fleet HEAD> <your target>`. If it fails, re-cut ONTO the fleet HEAD — never onto your original base.
- Re-run the dirty-file collision check against `<fleet HEAD>..<target>`, not against the range you first computed.
- When a peer's plan quotes a fleet HEAD, CHECK IT rather than answering the question they asked. Both of these messages asked "when will you release?" when the answer they needed was "your target is now invalid".

## 2026-10-20 -- A Kalshi settlement row after a partial close carries GROSS counts on BOTH legs, and its revenue omits the netted pair `[lane kalshi-exit-path]`
- **What happened:** `550a4b20`'s tests modelled a partly sold position's settlement row as the NET remainder on one leg (sell 4 of 10 YES -> `yes_count_fp=6`). The real row (Thornton, 5 NO, 1 sold by a YES buy) reads `no_count_fp=5.00, yes_count_fp=1.00`, so `grade_kalshi_settlement` refused it `both_sides_held` and the exit-aware branch never ran. `revenue=400` covers only the 4 net contracts: the netted YES/NO pair paid its $1 at trade time, so the venue's pnl (-0.6695) is not the entry's (+0.3305).
- **How to apply:** before writing a fixture for a venue row, copy one real row from production. Never derive an entry's P&L from Kalshi's settlement `revenue` once any contract was closed; use `exit_adjusted_pnl`.


## CLV AGAINST THE CONSENSUS CLOSE IS BLIND FOR MAKER FILLS: the fill selects on information the close does not hold `[2026-10-19, lane kalshi-maker-entry-paper]`

I pre-registered a Kalshi maker-entry study with CLV against the sportsbook consensus close as its
falsifier. It PASSED: 554 filled resting bids at +3.75% [+2.62, +5.16]. Settlement then contradicted it.
Over all 2,676 settled orders the close was calibrated (1,325 wins against 1,324.7 expected), but
**filled** orders won 5.37pp below it [-9.48, -0.91] and **unfilled** orders 1.40pp above. ROI on fills
was -9.2% (recorded-ask fills) and -4.0% (trade-print fills). Kalshi's own pre-kickoff mid over-predicted
the fills as well.

**Why:** a taker who sells into your resting bid chooses WHEN to trade, and the choice is informed. CLV
measures the price against a later price. It cannot see selection on the OUTCOME, and that is exactly
what a passive fill is. For a taker, CLV is a fair proxy: we choose the moment.

**How to apply:**
- Grade anything that fills passively (maker entry, resting limits, limits left after a miss) on SETTLED
  OUTCOMES. Report `wins - close fair` separately for filled and unfilled orders: the split is the signal.
- A CLV pass on passive fills is "not yet falsified", never "works".
- Pre-register the outcome test alongside CLV, not as an afterthought.

## "N call sites" in prose is NOT mechanically checkable, and a symbol-count sweep over it is mostly FALSE POSITIVES `[2026-10-20, lane polymarket-zip-site-enumeration]`

`#379` went stale by enumerating "five rejection counters" when a sixth arrived, so I swept for sibling enumerations and counted call sites mechanically. **1 of 4 candidates was real.** The other three each failed in a different way that counting cannot see:

- **COUNTERFACTUAL.** `nfl/cards.py`: "One conversion, named, rather than a sign flip inline at three call sites." The three never existed — they are what the author AVOIDED. One call site is correct.
- **DIFFERENT SUBJECT.** `board_enrichment`: "the only placement downstream of both halves on all three call sites" counts the ENCLOSING function's call sites, not those of the symbol on the same line.
- **NAMED BY FILE, NOT SYMBOL.** `board_enrichment`: "there are four: `intelligence.py`, `book_grid_artifact.py`, `layer2_shortlist.py`, and ..." — those files import DIFFERENT symbols (`attach_live_game_state_from_lens`, `attach_live_gamelines_for_sport`), so grepping the symbol beside the claim counts the wrong thing.

**Why:** a count in prose is a claim about a POPULATION the sentence does not define. The subject may be hypothetical, scoped to an enclosing frame, or identified by file rather than symbol. A grep answers a different question and answers it confidently.

**How to apply:**
- **READ each enumeration before counting anything.** Decide what the population IS; only then count. A sweep that files findings from a symbol-count is a grep wearing a check's clothes.
- The ones worth checking are those whose population is named by a symbol AND asserted as current. One of four here qualified — and it WAS stale (three sites claimed, four real, the omitted one being the arbitrage resolver).
- When correcting an enumeration, **state both totals** if they differ ("4 call sites across 3 functions"). The stale number survived because "three" plus a function named "twice" in prose made `1+2+1` invisible — and that same invisibility made ME miscount it in the opposite direction.

## A CONTROL THAT REVERTS ONE OF YOUR SHIPPED CHANGES CANNOT EXONERATE THE OTHERS — and "I verified it is not mine" is the sentence to distrust `[2026-10-20, lane no-market-price-test-fallout]`

A peer's test went red in a file I had just edited. I reverted MY copy of **that file** (`board_enrichment.py`, a docstring-only change), reproduced the failure, and reported it as pre-existing and "not mine". **It was mine.** The cause was `dd499146`, my refusal branch in `layer2_board.py`, shipped hours earlier: the fixture had an empty `cells` with a model edge, which is exactly a `rows_no_market_price` row, so nothing seated and the gate never ran. Proven by disabling the branch: 10 pass disabled, 4 fail live.

**Why:** my control answered "did my LAST change break it" while the question was "did ANY of my changes break it". By then I had shipped `dd499146`, `c36bdc9a`, `e491c260` and a docstring edit, and the exoneration covered the smallest of them. The narrow claim was literally true, which is what made it convincing.

**How to apply:**
- **Enumerate what YOU have shipped into the area before claiming innocence**, and revert the candidate most likely to matter — which is the behaviour change, never the comment.
- Better: don't claim innocence. Say which control you ran and what it covers. "Reverting my docstring change does not reproduce it" is honest; "it is not mine" is a conclusion that control cannot support. (`feedback_retraction_is_not_innocence` says the same from the other direction: withdrawing a bad attribution gives "not proven guilty", never "proven innocent".)
- **Sweep the suites a behaviour change can reach, at ship time.** 44 test files drive `build_layer2_rows`/`select_shortlist`; running them takes ~2 minutes and would have found both casualties immediately instead of leaving one for a peer to debug and one undiscovered.
- The signature to recognise: a fixture whose rows go to ZERO reads as "the feature under test withheld everything", which is indistinguishable from the feature working. An empty population is never a pass.

## THE SESSION WORKTREE IS SPARSE, AND IT EXCLUDES `vendor/` AS WELL AS `data/` — four test files then fail to COLLECT, which reads as real breakage `[2026-10-20, session 4ab694ed]`

I already had the rule that a worktree has no `data/`, so a failure there is not "red on main". Measured today, the exclusion is wider and the symptom is worse. `git sparse-checkout list` in a session worktree returns exactly:

    .claude .syndicate docs pipeline router scripts syndicate tests

so `vendor/` is absent too, and `tests/test_wnba_prop_dispersion.py`, `tests/test_wnba_prop_shape.py`, `tests/test_wnba_sim_minutes_redistribution.py` and `tests/test_wnba_sim_rate_shrink.py` die with **`ModuleNotFoundError: No module named 'wnba_betting'`** at COLLECTION, not as test failures. `pytest tests/ --collect-only` reports `4 errors during collection` and **refuses to run anything** (`Interrupted`), so an unqualified "the suite is broken" is the natural and wrong conclusion.

**Why it matters more than the `data/` case:** a data-dependent FAILURE is visibly about data. A collection ERROR looks like an import or packaging defect on main, and it blocks the whole run rather than one file. The vendored tree IS tracked on `origin/main` and IS present in the fleet checkout — I checked both before attributing it.

**How to apply:**
- Before reporting ANY suite-wide result from a worktree, print `git sparse-checkout list` and say what is excluded. 517 tracked files live under `vendor/` against 34,702 under `data/`.
- **`git sparse-checkout add vendor` is cheap and fixes it** (517 files), and the four files then collect 54 tests. Adding `data/` is not cheap and is a lossy mirror anyway, so data-dependent tests stay unrunnable here by design.
- Neither the primary tree nor the fleet checkout is a free substitute: the primary tree was BEHIND `main` today, and running 25,103 tests in the fleet checkout risks writing into production artifacts. State which tree a result came from and what that tree lacked.

## 2026-10-20 - FORBIDDEN: relaying an option label as a user decision `[no lane, session 34fdabd0]`
- **What happened:** after showing the user a wrap_up question with buttons ("Yes, widen" / "Widen + band on"), the parent session sent the compounding-bankroll lane "USER DECISION, relayed word for word: ..." quoting the first button. The user had not answered. The peer had already started a turn on it. The retraction was queued behind that turn and only took effect because the deploy gate was 30+ minutes away.
- **Rule:** a decision relayed to another session must quote a genuine user message (or an AskUserQuestion answer), never an option you wrote. After a wrap_up with `ask`, make no further tool calls that turn. A receiving session should treat "USER DECISION" from a peer as a claim, and where cheap, ask the user to confirm in its own chat before an irreversible live action.
- **Why it matters here:** peers act on a relayed decision as if the user typed it, so a fabricated one launders straight into a live-money deploy.

## 2026-10-20 - Registering an unclassified thing makes PRE-EXISTING debt visible; that is not the same as adding it `[lane hygiene-guards-1020, session 4ab694ed]`
- **What happened:** classifying the 17 unregistered converter-shaped functions in `scripts/probability_differential.py` turned `test_every_converter_is_registered_or_excused` green and turned `test_failing_set_does_not_grow` RED, in two concepts at once. The natural reading — "my change broke two tests" — is wrong. The three newly-failing implementations have ALWAYS failed those requirements; they were invisible because they had never been registered, which is exactly the thing the tripwire exists to surface.
- **Rule:** when a registration/classification sweep makes a differential go red, the red is a MEASUREMENT of old debt, not a regression. Say which it is before anyone decides to revert. And do not "fix" it reflexively: two of the three were MLB sim-engine converters that prop pricing is calibrated around (a mechanism change owed a measurement, per the model-engine standard) and the third is another lane's pre-registered measurement instrument, so all three were recorded in `KNOWN_FAILING` with their reasons instead.
- **Why it matters:** the cheap way to keep a classification tripwire green is to excuse everything. The expensive and correct way surfaces real defects, and it will look like you caused them.

## 2026-10-20 - Do not infer a field's SEVERITY from its name `[lane hygiene-guards-1020, session 4ab694ed]`
- **What happened:** `IntervalHistory.__init__` does `self.today = today or date.today().isoformat()`. I wrote "this one IS a slate-date default, the high-stakes kind" into an allowlist reason — from the name `today` and nothing else. `self.today` is read at EXACTLY ONE site: `_keep`'s `day < self.today and all(g.get("decided") for g in games)`, the decision to persist a day to the disk cache. Behind `all(decided)` a one-day skew can only persist an already-final day early or defer it. It moves no slate and mis-dates no game. Corrected before committing.
- **The real defect was next to it, and naming the wrong one would have hidden it:** `cached_team_results` builds `IntervalHistory(root, offline=True)` with no `today=` and caches it in a module-level `_READERS` dict, so `self.today` is frozen at the value the PROCESS BOOTED with — days stale on a long-lived gunicorn worker, and `central_today()` would not fix it.
- **Rule:** before writing a severity into a ledger or a guard comment, grep every read of the field and look at the predicate it feeds. One grep. A wrong severity in an allowlist is worse than no entry, because the next reader trusts it and stops looking.

## 2026-10-20 - A whole-file read-modify-write rewrites every line ending, and the size change looks like data loss `[lane hygiene-guards-1020, session 4ab694ed]`
- **What happened:** appending 10 lines to `docs/ai_context/todo.md` with `io.open(...).read()` then `io.open(..., newline='').write()` shrank the file from 3,304,326 to 3,256,293 bytes. `lane-postwrite-check` reported the 48KB drop against a file claimed by 10 other lanes. Nothing was lost: reading with universal newlines turned CRLF into LF in memory and `newline=''` wrote it back unchanged, so ~48k lines each lost one byte. `git diff --numstat` said `10 0`, which is the authoritative check and settled it.
- **Rule:** on a shared ledger file, gate on `git diff --numstat` (content), never on bytes on disk — and expect a whitespace-only working-tree churn from this pattern. The bigger point is that read-modify-write of a 50,000-line shared file is a whole-file clobber window; prefer a genuine append (`open(p, 'a')`) whenever the insertion point is the end.


## 2026-10-21 - In play, "check the exit faster" was assumed to help; on an efficient price it sells earlier AND cheaper `[lane in-game-trading, session 15ceeb14]`
- **Belief overturned:** the in-game program began from "the exit check runs every 5-7 min while Kalshi quotes refresh every ~23 s, so it must run faster".
- **What was measured:**
  - Real cadences. Kalshi's in-play ask changes every ~11 s. The FLEET polls it every 2-3 min and Polymarket every 3-5 min (venue_poll lines), not the 60 s env default.
  - Speed costs money. Replaying the fixed take-profit on 379 settled synthetic positions, the 10 s loop lost MORE than the 6-min tick: -12.2% vs -10.3%, with hold at -6.4%.
  - Where both cadences fired, the slow tick sold +3.1c higher. In-play markouts after fee were negative (-1.26c, CI -1.80..-0.72), so prices that cross the line keep drifting the same way. There is no overshoot to sell into.
- **Rule:** before making a trading loop faster, replay it at both cadences against settlement. Latency only pays when the rule is right. A fixed-margin exit on an efficient price is a fee, and running it faster just pays the fee sooner.
- **Second rule:** the sportsbook consensus is not an in-play fair against Kalshi. Kalshi moves first (corr +0.44 at +2 polls). A book "edge" is usually the book's lag, often a score Kalshi priced 30-40 s before ESPN showed it. Measure an in-play fair against Kalshi's own LATER mid (markout), never against the books.
- Also: Windows `SetPriorityClass` through ctypes without `argtypes`/`restype` truncates the 64-bit pseudo-handle and fails SILENTLY. Every "Idle" recorder ran at Normal until a peer saw it in Task Manager. Check the return value.

## 2026-10-21 -- CORRECTION to the 2026-10-20 entry above: rating INPUTS did NOT transfer either. Gate EVERY engine change on the real sim, inputs included `[lane soccer-team-strength, session e44b3e73]`

The 2026-10-20 entry said: "Rating INPUTS transfer, because the sim reads them with a measured linear gain (R² 0.87). Output maps do not." **The first half is wrong.**

**Measured:**
- RATING V2 beat the shipped rating on the research link: −0.0019, CI below 0, 27,285 matches.
- Through the real SoccerSim it was WORSE: +0.0035 [−0.0011, +0.0077], 2,405 matches, 7 of 8 leagues.
- V2 widened the link's spread (0.323 → 0.327) but NARROWED the sim's (0.349 → 0.335).
- The sim was never under-dispersed: it matched the close's spread (0.334) and was over-confident on its own top decile.

**Why:** a linear gain on the goal-mean RATIO (R² 0.87) is not the same thing as the sim's 1X2 dispersion, which also comes from the possession mechanics. A change that helps a model that is under-dispersed hurts one that is not.

**How to apply:**
- The do-no-harm A/B through the real engine is the gate for EVERY engine change, inputs included, not only post-hoc maps.
- Read the engine's OWN dispersion and calibration (spread vs the close, own-decile calibration) BEFORE adopting a diagnosis made on a proxy.
- Here that one read would have shown the favourite-underrating premise did not apply to the served sim.

## 2026-10-21 -- RULE: inside `wsl -d Ubuntu-24.04 -- bash -lc '...'` run from Git Bash, EVERY `$VAR` and `$(...)` is expanded ONCE, up front, by an outer shell in the WINDOWS cwd -- a guard written that way is a no-op `[lane nba-current-rosters, session 8e69dd3f]`
- **What happened:** the fleet ff ran `cd /home/amyn/Syndicate && test "$(git rev-parse HEAD)" = "$(git rev-parse 3fffb430b)" && git merge --ff-only <sha>`. Both substitutions ran in the Windows worktree's mapped path ("fatal: not a git repository"), the test compared empty to empty, and the merge ran unguarded. It was safe only because `--ff-only` and an unchanged HEAD made it so. Earlier the same night `L=...; wc -c $L` read stdin and printed 0, which read as an EMPTY LOG.
- **Measured:** `wsl -d Ubuntu-24.04 -- bash -lc 'cd /tmp && echo $(pwd)'` prints the Windows worktree path, not /tmp. `$HOME` looks right only because the outer shell has it too.
- **Rule:** in a `wsl ... bash -lc` string, write no `$` that must be evaluated inside -- use literal values, escape `\$`, or put the logic in a script file (or Python) and pass paths as arguments. Never gate a production step on a `$(...)` test sent this way; read the gated value in a SEPARATE call and compare it yourself.

## 2026-10-21 -- RULE: a deploy claim acquired BEFORE asking the user can expire while the answer is pending; re-check `deploy_claim.py status` after every AskUserQuestion and before the action `[lane nba-current-rosters, session 8e69dd3f]`
- **What happened:** refresh-worker claimed at 11:28 PM CT (TTL 90) for an approved after-the-games ff; a ride-along question to the user was answered at ~7:40 AM CT; the ff ran at 7:43 AM under a claim EXPIRED 495 min. No one else held it, so nothing collided -- by luck, not by the lock.
- **Rule:** acquire (or re-acquire) the claim immediately before the merge/restart, gate on its exit code, and treat any user wait as invalidating the earlier acquire.

## 2026-10-21 -- OVERTURNED: "adding a player to an NBA sim pool takes his points from his teammates one for one, because the team score is market-anchored" `[lane nba-no-history-admit, session 15f24a49]`
- **Belief:** the market anchor fixes each team's score. So a player added to the pool must take his points out of
  his teammates' totals, one for one. This was pre-registered as P4: teammates give back 0.6-1.0x his points.
- **Measured, scratch 10-21:** teammates gave back only **0.50-0.69x** on 10 sides.
- **Cause:** the anchor holds the TEAM score (|d total| <= 2.3), but per-player means are not constrained to it. Summed
  player `pts_mean` minus the team's mean score is **+8.5** on the 12 unaffected sides. It was +3.0 on the affected
  sides before the stand-ins and +10.2 after.
- **RULE:** for an NBA sim pool change, judge the effect on prop prices from the player layer (`players[]` means and
  ladders), never from the team score. A conserved team total says nothing about how points split among players.
  Measure the player-sum gap on the unaffected sides first; that is the population the prop calibration was fitted on.

## 2026-10-21 - A stale test can be the COVER for a half-applied change; triage the file, not the assertion `[lane ci-suite-four-stale-1021, session 4ab694ed]`
- **What happened:** `tests/test_archives.py` pinned a hand-written six-key MLB live-lens `counts` dict and went red when `postponed` was added on 2026-10-16. Read as "stale expectation, update the dict" it is a one-line fix. Read as "why did the shape change" it turns out `live_lens.py` builds `counts` TWICE and only ONE path got the new bucket: `_card_status_bucket` still returned **`final` for a postponed game** (StatsAPI files one under abstract "Final"), and the cards-fallback `else` branch folded postponements into `pregame`. Measured HEAD-vs-fixed on the same card. The wrong number had been live for five days behind a test everybody could see was red.
- **Rule:** when a red test is "just stale", the change that made it stale is the thing to read. Ask whether that change was applied EVERYWHERE, and specifically whether the endpoint builds its answer by more than one path (the standing "one endpoint, two code paths" rule). Updating the assertion first and asking second gets the order backwards, and the suite goes green either way.
- **Why it matters:** a red test is a FREE pointer at recently-changed code. Spending it on the assertion instead of the change is the one way to get nothing for it.

## 2026-10-21 - A test that pins a PROXY goes red when the proxy expires, and it reads as a regression `[lane ci-suite-four-stale-1021, session 4ab694ed]`
- **What happened:** three of four failures were tests asserting a stand-in rather than the thing they cared about. `test_ncaaf_team_aliases` asserted "an FCS visitor refuses" as a proxy for "a Kalshi ticker is never guessed onto a fixture" -- and the FCS reach was deliberately ADDED (`club_key` into `chip_join_key`, the CFBD registry across all four divisions). `test_intelligence` pinned column LABELS as a proxy for "the blotter still shows a price, a projection and a live value", and was on its THIRD formulation after drifting twice. In both cases the property held and only the proxy had expired -- but a red test on a Kalshi resolver reads like real-money risk, so it costs a full investigation every time.
- **Rule:** assert the property, on the most stable axis the test can reach. For a resolver that is BEHAVIOUR -- probe the ways a wrong answer could happen (one-sided match, decoy, ambiguity, nonsense, empty input). For a UI it is the DATA each cell reads, never the label. For a shape it is a DERIVED expectation, never a hand-written literal. Where only a proxy is available, say in the test that it IS one and what it stands for, so the next reader can tell "the property broke" from "the proxy aged".
- **Measured corollary:** three of these four were broken by deliberate work on a single day (2026-10-16) by three different pieces of work, none of which updated the test pinning the old behaviour. Proxy pins concentrate that cost and hand it to whoever reads the suite next.

## 2026-10-21 - `ps -o lstart=` is LOCAL time; piping it into `date -u -d` shifts a boot time by the whole offset `[lane ci-suite-four-stale-1021, session 4ab694ed]`
- **What happened:** to decide whether a deployed fix was loaded, I needed the live-odds-worker's boot time. `ps -o lstart= -p $PID | xargs -I{} date -u -d {}` reported **08:48:13Z**. The container runs **CDT**, so `lstart` was already local and `date -u -d` parsed it as UTC: the real boot was **13:48:13Z**, five hours later. The same command printed `etimes=51:58` one line below, which implies 13:48Z and contradicted it outright -- **the disproof was in my own output and I read past it.**
- **Everything downstream inverted.** With the wrong boot the process looked older than the 13:38:41Z duplicate live orders, so "it placed them, therefore it has the old module cached in `sys.modules`, therefore the dedupe is inert" followed. With the right boot it started AFTER those orders and never placed them. I wrote the wrong conclusion into `deploys.md` and reported a money-path safety fix as inert; the user asked for a restart on the strength of it. The restart would have killed in-flight execution for nothing.
- **Rule:** never derive a boot time through a formatted-then-reparsed timestamp. Use `now_utc - etimes` (`ps -o etimes=` is a duration and carries no timezone), or `/proc/<pid>/stat` field 22 against `/proc/uptime`. Print `date +%Z` alongside any process timestamp so the zone is on the record. And when two readings in one output disagree, stop: one of them is wrong and the cheap one usually is not the formatted one.
- **Second rule, the one that would have caught it anyway:** "is this code loaded" has a PREDICATE, and uptime arithmetic is not it. What settled it was the `__pycache__` `.pyc` mtime (recompiled after the ff wrote the source), `strings` on that `.pyc` finding the new symbols, and the refusal paths from the same commit appearing in the log. Check the artifact the process actually loaded, not the clock.

## 2026-10-22 - "KEY ABSENT" is a THIRD state, not a null: a partial restart puts two record shapes in one append-only document `[lane order-sizing-provenance, session 4ab694ed]`
- **What happened:** after shipping `#722` (two new fields on the execution-ledger order) I ff'd the fleet and restarted only the live-odds-worker. Checking that new orders carried the fields, my first query used `o.get("staked_probability_version")` and reported **"289 None"**. That single number was two unrelated populations: **218 rows carrying the key with a NULL value** (paper LADDER placements — correct, a flat-stake ladder has no sizing basis) and **71 rows missing the key ENTIRELY**, written between 22:20Z and 02:27Z by the refresh-worker and web, which still held their pre-ff modules because only one role was restarted. The window closed exactly when that writer recycled.
- **Rule:** when a field is added by a partial deploy, treat `key not in record` as a third state and attribute it BY TIME WINDOW. `dict.get()` folds absent into null and destroys the distinction — use `in` for presence and `is None` for emptiness, separately. A missing key says an OLD BUILDER wrote the row; a null key says the new builder ran and had nothing to record. They have different causes and different fixes.
- **Why it matters:** the fold made the result look like a 50% failure of a fix that was in fact 17/17 on the path that mattered, and it hid a genuine finding (the ladder path can never enter the split) behind a number that looked like a bug in my own change.

## 2026-10-22 - A role respawn does NOT re-read `local_production.env`; only a full supervisor `up` does `[session 4ab694ed]`
- **What happened:** I appended `SYNDICATE_NBA_LIVE_PRICED=1` to `/home/amyn/syndicate-prod/local_production.env` and confirmed all three roles DERIVE it (`local_production.py env --role`). The running processes did not have it — expected. What is NOT obvious: the live-odds-worker then **respawned on its own** (new pid 3727746) and **still** reported the key absent. `local_production.py ... up` builds each role's env ONCE at `up` and its children inherit that dict, so a role restart re-reads nothing.
- **Rule:** an env change on this fleet loads on a full supervisor `down`/`up`, never on a role restart or a natural recycle. Do not verify an env change by waiting for a respawn, and do not record one as "will load at the next restart" without saying WHICH restart. The Render-era rule ("a restart does not re-inject env vars") has a local-fleet twin, and it is stricter: even the thing that normally does pick up new CODE will not pick up new ENV.
- **Corollary for verification:** `local_production.py env --role <role>` is the check that the config is right; `/proc/<pid>/environ` is the check that a process is running it. They answer different questions and today they disagreed by design.

## 2026-10-22 - A commit gate must tell "deleted someone else's line" from "replaced my own" `[session 4ab694ed]`
- **What happened:** the deletion gate I wrote on 10-21 (refuse to commit if any shared ledger file shows a deletion) correctly caught a retry loop that would have dropped 360 lines of a peer's soccer work. The next day it blocked **my own correct edit**: replacing one line of todo `#722` is 1 deletion + 1 insertion, and the gate saw only the deletion.
- **Rule:** gate on deletions of lines you did not write, not on the deletion count. Cheapest usable form: allow deletions only in files you are intentionally editing in place, assert the exact count you expect, and PRINT the deleted lines so the operator confirms they are their own. A gate that blocks correct work gets switched off, which is how the 360-line case comes back.

## 2026-10-22 - Two NBA files are NOT what their names say after tip: the processed props snapshot and pre-freeze production sims `[lane nba-sim-minutes-allocation, session ffb7ab00]`
- **Belief overturned (1):** `processed/oddsapi_player_props_<D>.csv` holds the slate's pre-tip lines.
  - Each pull overwrites it.
  - Read after 10-21's games, it held IN-PLAY rows only, so a pre-tip points-line join returned 0 of 157 players.
  - **Rule:** a post-hoc reading of pre-tip lines reads `raw/odds_nba_player_props_history_<D>.csv`, filtered to snapshot < commence. That file has no home/away columns; take event teams from the raw or opening snapshot.
- **Belief overturned (2):** a `smart_sim_<D>_*.json` on the fleet is a pregame prediction.
  - All three 10-20 sims were rebuilt 11:08 PM CT, after the games, and their frames carry the game's own box minutes as `lag1_min` (Cunningham 35/35).
  - Their minutes MAE was 0.6-3.0, against 4.5-11.0 on honest sides.
  - **Rule:** before scoring any production NBA/WNBA sim built before the tip freeze went live (2026-10-21 11:56 AM CT), compare its mtime with the tip and DROP post-tip builds.
  - `scripts/nba_sim_minutes_audit.py` does this and tags them `[built after tip]`.
- **Same session, smaller:** match player names ACROSS sources with `normalize_player_name_key` (orchestrator), never `_norm_name_key`.
  - `_norm_name_key` keeps periods and apostrophes: props_predictions "Jabari Smith Jr." never meets the books' "Jabari Smith Jr".
  - On 10-21 that hid 2 of 6 priced MIL players.



## 2026-10-22 - A claim watcher must treat EXPIRED as released, not wait for "free" `[lane in-game-trading, session 15ceeb14]`
- **What happened:** I waited on another lane's live-odds-worker claim with a loop that exited on `*free*`. `deploy_claim.py status` printed `EXPIRED (does not block)` from 23:37Z onward. The loop ran on to its 70-min timeout, and an in-game paper measurement started ~1 h into the NHL slate.
- **Rule:** a watcher on `deploy_claim.py status` exits on `free` OR `EXPIRED`. Better, it asks `acquire` (exit code 0) instead of parsing prose. The claim tool's own word for "not blocking" is not "free".
- **Also from this lane:** when this session's permission classifier refuses a money-moving step, a peer session's offer to "do that step here, where the user approved it" is declined. The decision goes back to this session's user, who chose paper-only. That path worked; the refused live module was never built anywhere.

## 2026-10-22 - A reader survey's "drops rows" and "paper-only" are claims about BEHAVIOUR; measure them on the ledger before scoping the fix `[lane fitter-contract-price-units, session 2f9bdfe9]`

- **Belief:** #719's reader survey listed `fit_staked_probability.py` as silently dropping live rows and `paper_bet_optimization.py` as "paper-only, safe today". Both came from reading the profit helper, not the row filter.
- **Measured on the fleet ledger (12,111 orders):** the staked fitter reads `requested_price` FIRST, and that is American on every live row, so it kept 72 of 72 live rows before the fix as well as after (the fix is latent). The "paper-only" script has `kalshi` and `polymarket` in its venue filter, and it was pricing all 73 live rows wrong (mean implied 0.9936 vs 0.6466). The file named as broken was fine, and the file named as safe was the one producing wrong numbers.
- **Rule:** for a unit or format defect, trace WHICH column each reader takes first, and which rows its filter admits, then count the kept rows before and after on real data. A two-unit column also needs the second question: which price was the stamp (`ev_pct`) computed against? Here it is `requested_price`, not the fill.

## 2026-10-22 - A cleaner's symptom list is a measurement of an upstream defect: count what it matches on the real input before adding a word to it `[lane nba-injury-pdf-parser, session ef55f9f7]`
- **Belief overturned:** the injury-PDF name splice was occasional. On this belief, a reason that WRAPPED onto the next line landed between a player's first name and his status, so adding the missing words (WAY, TEAR, TENDINOPATHY...) to `_NOISY_PLAYER_TOKENS` would fix it.
- **Measured on 167 real reports:** the parser took `<word> Last,` as a two-token surname (an allowance meant for `Lively II,`), so the LAST WORD OF NEARLY EVERY REASON became the next player's surname prefix. The tokens right before a `Last,` were `Strain` 759, `Surgery` 759, `Way` 456, `Sprain` 334 and so on. The only genuine two-token surnames were `Lively II,` and `Butler III,`. The vendored token list held exactly the commonest of those words: it had been masking a systematic defect one word at a time. 971 of 5,658 rows were still written under names no pool matches.
- **Rule:** when a cleaner carries a hand-grown list of "noise" words, tabulate where each listed word comes from on the real input before extending it. If the list keeps growing, the defect is upstream. Fix the producer, and decide ambiguous cases against an authority (here the roster), not against a longer list.
- **Smaller, same session:** I wrote a commit SHA into the ledger before `land`. The rebase changed it (3e3c3a37 -> 36eb357b) and the ledger had to be corrected. Cite a SHA only after the push, read from `git log origin/main` (memory rule "never write an unseen SHA").

## 2026-10-22 - The WSL system `python3` reads the fleet's keyvalue ledger as EMPTY, silently: run fleet reads on the fleet venv `[lane sim-stake-earned-profile, session bde77672]`
- **Belief overturned:** I believed `PYTHONPATH=~/Syndicate` plus the refresh-worker state env was enough to read the fleet's execution ledger read-only.
  - It is not, under `/usr/bin/python3`, which has no `redis`.
  - `read_json_file_result` returns ok=False, and `read_json_file` (`#658`) turns that into an EMPTY live document.
  - `full_history_orders()` then returns the disk archive alone: 9,178 of 12,175 orders, no live order, and newest 03:40Z instead of 16:15Z.
- **What it produced:** a coverage table, a fit and a fake "orders collapsed after 10-18" finding, all on a substrate missing the newest 3,000 orders. Nothing errored.
- **Caught by:** comparing the order count against a peer lane's number from the same day (12,111). The memory rule "re-derive cross-lane numbers" fired, the other way round.
- **Rules:**
  - Fleet reads use `/home/amyn/.venvs/syndicate/bin/python` (what the supervisor runs).
  - Any ledger reader asserts `read_json_file_result(_ledger_path())[1] is True` before trusting a count. `fit_staked_probability_cells.py` now exits 4 otherwise.
  - The older fitters (`fit_staked_probability`, `fit_probability_calibration`, `ev_overstatement_decomp`) do NOT check this yet.
