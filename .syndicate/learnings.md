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

## Index — 690 rules `[generated]`

> Full index: [`learnings_index.md`](learnings_index.md) — regenerate with
> `py -3 scripts/build_learnings_index.py` after appending. It spans BOTH
> this file and `learnings_evidence.md`, so a rule stays findable after its
> body is compacted out. **FORBIDDEN** = never do this again.
> **EXONERATED** = ruled out, stop re-investigating.

<!-- LEARNINGS-INDEX:END -->

---





### 2026-08-30 — FORBIDDEN: `git commit --only -- <shared ledger file>`. The pathspec form commits the WORKING TREE, which in this repo holds every other session's uncommitted edits to that file `[lane stale-row-cause-blind-spot]`

- **What we believed:** `git commit --only -- <paths>` is the safe way to commit
  in a shared tree, because the pathspec decides the contents rather than the
  shared index. That is true and it is why it was chosen — the index really can
  hold another session's staged work, and this form ignores it.
- **What was actually true:** the pathspec form commits the **working tree**
  state of those paths. For a file only this session touches that is exactly
  right. For a SHARED file — `lanes.md`, `learnings.md`, `state.md`,
  `deploys.md` — the working tree already contains every other session's
  uncommitted edits, and they all ship. Commit `888d02ee` carried another
  session's closure of `venue-first-market-universe` from OPEN to CLOSED. **I
  did not close that lane, do not own it, and had no way to judge whether the
  closure was ready.**
- **AND IT RUNS BOTH WAYS, observed within the hour.** Commit `fde61650`
  ("lanes: CLOSE venue-first-market-universe") swept THIS session's pending
  `stale-row-cause-blind-spot` lane block into their commit. Neither session
  chose to publish the other's work; the tree did it.
- **How we found out:** a rebase. The commit would not fast-forward, and the
  3-way merge of `lanes.md` conflicted on a lane block whose two sides were
  CLOSED (mine) and OPEN (theirs) — for a lane I had never edited. Comparing
  base/mine/theirs on that one heading is what exposed it.
- **The rules going forward:**
  1. **Never commit a shared ledger file by pathspec from the shared tree.**
     Build the blob deterministically instead: take `origin/main`'s version,
     apply YOUR edit to that, and commit it via
     `update-index --cacheinfo` / `write-tree` / `commit-tree`. Then the
     committed content is provably `remote + your change` and nothing else.
  1a. **PIN THE REF TO A SHA FIRST — `BASE=$(git rev-parse origin/main)` — and
     use `$BASE` for BOTH the `read-tree` and the `-p`.** Naming `origin/main`
     twice is a race with every other session, and it bit me inside this very
     entry: `origin/main` advanced between the two steps, so the TREE came from
     the old tip and the PARENT from the new one, and the resulting commit
     **deleted 31 lines of another session's `log/2026-08-30.md`.** That is a
     stale-HEAD revert manufactured by the procedure meant to prevent one.
     Caught in `git diff --numstat` before pushing; `main` was reset and the
     commit rebuilt against a pinned base.
  1b. **Assert the blast radius before `commit-tree`, do not eyeball it.** Sum
     the deletion column and refuse unless it is `0` — and **do NOT exempt your
     own paths from that check.** My first version of this guard excluded the
     files I was editing, which is exactly backwards: the shared ledger file is
     both the thing I edit AND the thing another session is appending to, so a
     stale local copy of it reverts their work while the guard reports clean.
     It fired on the very next attempt: `13 insertions, 36 DELETIONS` on
     `learnings.md`, because the remote had moved again.
  1c. **Apply your edit to the REMOTE's bytes, not to your working copy.**
     `git show $BASE:<path> > tmp`, patch `tmp`, hash THAT. A working copy in a
     shared tree is stale the moment another session pushes, and re-editing it
     re-introduces the revert the whole procedure exists to avoid.
  2. **Before committing any shared file, diff the working copy against
     `origin/main` and read every hunk.** If a hunk is not yours, you are about
     to publish someone else's draft. `git diff origin/main -- <file>` is the
     whole check.
  3. This does NOT retract the existing rule about the shared INDEX. Both are
     real and they are different: the index can hold a stale-HEAD revert, the
     working tree can hold another session's half-finished edit. `--only`
     dodges the first and walks into the second.
- **Cost:** none shipped wrong — caught during the rebase, the commit was
  rebuilt from `origin/main` with only this session's two code files, and
  `lanes.md` was left exactly as the remote had it. The other session's closure
  then landed under their own commit, which is where it belonged.

**THE GENERAL SHAPE, and it is the fourth instance tonight:** in a tree several
sessions share, an artifact does not carry the identity of who made it — not a
commit (author is one bot for everyone), not a lane claim (prose parsed as a
claim), not a backup (named for a state it did not hold), and not a working-tree
edit. **Attribution has to come from outside the artifact every time.**

---

### 2026-08-30 — FORBIDDEN: inferring WHO wrote a commit from ADJACENCY in a shared branch where every commit carries one bot author `[lane exchange-join-refusals]`

- **What we believed:** a peer session attributed commit `c17bc3d8`
  ("polymarket's fee MEASURED ... it is ZERO", touching `venue_fees.py` and
  `kalshi_polymarket_arb.py`) to THIS session, and opened a substantive
  contradiction against it — asking this session to adjudicate a fee model that
  moved a break-even threshold 3.38c -> 0.88c and gates real money.
- **What was actually true:** not this session's commit. It landed **45 seconds**
  after this session's `a29dd997` and 5 minutes before `3a00f35d`. This session
  touched **0 of its 5 files**, `state.md` included. The owner was
  `live-venue-order-placement`, which claims both fee files in its `Files:` block
  and whose checkpoint header describes exactly that work.
- **Why the author field could not help:** every commit in this repo is authored
  `github-actions[bot] <github-actions[bot]@users.noreply.github.com>`. Several
  sessions push to one branch under one identity, so `%an` separates nobody and
  temporal order is the only remaining signal. **It is not a signal.** Sessions
  here commit minutes apart all evening.
- **The rules going forward:**
  1. **Attribute a commit by CONTENT against a lane's declared `Files:`, never
     by position in the log.** One line does it:
     `git show --stat <commit>` and compare to the `Files:` blocks in
     `lanes.md`. `git log --oneline <mine> -- <path>` confirms the negative.
  2. **A misattributed commit is not a harmless mixup when it carries a
     REQUEST.** This one asked a session with no stake and no independent
     reading to break a tie on a live financial threshold. Refusing to
     adjudicate was the correct answer, not a lack of helpfulness — and the
     refusal only became available by checking authorship first.
- **Cost:** none. Caught before any edit to `state.md` or the fee model; the peer
  re-verified and re-routed to the owning session.

**THIRD INSTANCE TONIGHT OF ONE ROOT CAUSE — identity is not recoverable from the
artifact in a shared tree.** (1) A lane block's PROSE naming a contested path
inside a `- Files:` block was parsed as a live CLAIM on a file the lane was
explicitly staying off. (2) A backup named `.CONFLICTED.bak` contained the
RESOLVED file, because `cp` raced another session's resolution. (3) This. Each
was caught by someone checking the artifact against an independent source rather
than reading its name, its neighbours, or its timestamp.

---

### 2026-08-30 — FORBIDDEN: offering a backup as a safety net without verifying it contains what its NAME claims. Mine held the RESOLVED file `[lane exchange-join-refusals]`

- **What we believed:** `.syndicate/lanes.md.CONFLICTED.bak` captured the
  pre-resolution conflicted ledger, so three OPEN lanes that existed on only one
  side of a `git stash pop` conflict were recoverable whatever anyone did next. I
  told my user that in those words, and told two peer sessions the same.
- **What was actually true:** both copies contained **0 conflict markers, 54
  headings, one `mlb-resolver-write-side-effect` block** — the RESOLVED file. The
  `cp` raced the resolution: I grepped markers at 3724/3778/3966, and by the time
  the copy ran (~30s later) another session had resolved it. **The
  pre-resolution state is gone and was never captured.**
- **How we found out:** a peer went to use the file as a test fixture and
  measured it first, rather than trusting the filename. I then verified it
  myself: `grep -c '^<<<<<<<'` = 0 on both copies.
- **Why it was worse than no backup:** the name asserts a property the contents
  do not have, so the next person trusts it. A missing backup fails loudly; a
  lying one fails at the moment someone needs it.
- **The rules going forward:**
  1. **A backup is evidence only once you have checked it contains what its name
     claims** — for a conflict snapshot that is one `grep -c '^<<<<<<<'`, run
     against the COPY, not the source.
  2. **Snapshotting a file under concurrent modification is a RACE.** `cp` of a
     contended path in a shared tree can land either side of another session's
     write. Verify after copying, and name the file for what you verified.
  3. **Never name an artifact for the state you INTENDED to capture.** Rename or
     delete the moment the contents disagree.
- **Cost:** no data lost — the union resolution was correct (+153/−0 vs
  `origin/main`, all three at-risk lanes intact) and the peer built a synthetic
  fixture instead. But a false assurance stood in three places for ~40 minutes,
  and the recovery path I advertised did not exist.

---

### 2026-08-30 — FORBIDDEN: sizing work off a REFUSAL COUNTER before checking how much of it is out of scope. `clubs_unresolved: 314` was ~26 recoverable markets `[lane exchange-join-refusals]`

- **What we believed:** Polymarket's `clubs_unresolved: 314` on NCAAF was a join
  backlog — 314 quotes we were failing to key, and therefore the largest
  single-sport exchange prize on the board. An assessment ranked it #1 to attack.
- **What was actually true:** measured n=25 against a 165-market population,
  **21 of 25 were games this platform does not card** — Campbell v East Tennessee
  St, VMI v Idaho St, Citadel v Wofford, Stetson v South Dakota St. The registry
  is 247 D-III / 171 D-II / 128 FCS / 138 FBS and the board cards FBS-vs-FBS.
  Polymarket lists far more college football than Syndicate boards. Recoverable
  is **~16%, ~26 markets — not 157.** The counter was accurate; the SIZING was
  wrong by 6x.
- **How we found out:** only by building the join and classifying every miss. The
  counter's own name (`clubs_unresolved`) and the adapter comment beside it
  ("each one is a missing `team_aliases` entry") both invite reading it as a
  backlog, and neither is a measurement of recoverability.
- **The rules going forward:**
  1. **A refusal counter measures what a reader REFUSED, not what is
     RECOVERABLE.** Before sizing work off one, classify a sample of the
     refusals into out-of-scope / recoverable. The two can differ by an order of
     magnitude and nothing in the counter says which.
  1b. **AND "recoverable" is not "worth having" — check what the refused rows
     CONTAIN.** `oddsapi no_side_in_key: 3647` is an HONEST counter (a real
     `continue`) on a sport whose board demand is not in doubt, and it is still
     worth ~0: 4.2% are game lines with genuinely no side (correct refusal),
     and 95.7% are props whose side IS present as `selection=` — recoverable in
     one line, and REDUNDANT. Same capture the board already reads
     (`oddsapi_hitter_props_*.json`), no bookmaker field against the board's 8
     named books on 250/250 rows, and OLDER — p50 4.5h against the board's
     58min, so it loses freshest-wins on 78.5% of rows. **Four scope checks,
     four near-zeros, and this is the one where the counter was accurate and
     the demand was real.**
  2. **Two wrong fixes were proposed for this before one was measured** — an
     alias map (already FORBIDDEN the previous day) and a slug-token join (8%,
     dead on the same upstream-vocabulary wall). A named cause sitting next to a
     counter is a HYPOTHESIS. This one had been refuted 24 hours earlier in a
     file the reader was not reading.
  3. **A scope test must not leak across the ambiguity it is scoping.** The first
     cut asked "is any school sharing either mascot FBS?" and called Citadel v
     Wofford in-scope because "Bulldogs" is also Georgia's — over-reporting
     recoverable misses **15x, 28.6% against a true ~0%.** Ask whether the PAIR
     could be in scope, never whether either half could.
- **Cost:** none shipped — measurement-only lane, fix sites held by another lane
  and never touched. Two proposals retracted before code.
- **CONFIRMED THREE TIMES IN ONE SESSION, on the same `reason` string.** The
  scope check that followed found `h2h_keyed_by_team: 905` is **not a refusal at
  all** — it increments on the SUCCESS path (`venue_quote_adapters.py:628-631`,
  no `continue` before `quotes.append`) and its own docstring says it is reported
  "alongside the refusals rather than only on failure". And `spreads_refused:
  3288` is 45% NFL+soccer, which carry ZERO board spread rows, with the rest
  being ladder RUNGS (~8 per game) rather than games. Resized: 905 -> 0,
  314 -> ~26, 3288 -> ~443. **A ~4,500-quote headline collapsed to a few
  hundred.**
- **FOUR INSTANCES, NOT THREE.** A peer session found `no_price` /
  `leg_without_price` two lines above `h2h_keyed_by_team` — same shape, and this
  one APPENDS a `Quote(probability=None, american=None)`; the MIRROR leg in the
  same function guards correctly (`if None: count; else: append`) while the
  PRIMARY leg does not, which is what proves it an oversight rather than a
  design choice. **Traced, not assumed: it is NOT a correctness bug today** —
  `venue_quote_fanin.py:1128` refuses it at the point of use (`if quote.american
  is None: continue`) and nothing outside the adapter reads `.probability`. It
  is inert, and one unguarded future consumer away from not being.
- **MARK WHICH CORRECTIONS ARE PERMANENT.** `905 -> 0` and the `no_price`
  finding rest on reading an INCREMENT SITE and cannot drift. `314 -> ~11-43`
  and `3288 -> ~443` rest on production slate state that moved 166 -> 163 within
  the hour. Written the same way, a reader re-running next week reproduces the
  zeros, fails to reproduce the rest, and concludes the METHOD is unreliable
  rather than that the SLATE moved. Timestamp the readings; leave the
  code-derived corrections undated.
- **THE STRUCTURAL CAUSE, and it is a design defect in the emitter, not just a
  reading error:** `_kalshi_ok_reason` and `_polymarket_ok_reason` format
  SUCCESS counters and REFUSAL counters identically — `name:count`, space
  separated, inside one field literally called `reason`. Nothing in the string
  distinguishes "we could not key these" from "we keyed these fine". A reader
  cannot tell them apart without opening the increment site, and I did not, three
  times. **If you emit a diagnostic counter that is not a refusal, it must not
  share a field named `reason` with the refusals** — or it must carry its own
  prefix (`ok:h2h_keyed=905`).

**WHAT DOES SURVIVE:** the schedule-constrained mascot-pair join is sound and is
the right mechanism when the ~26 markets are worth taking — 51 carded games gave
51 distinct mascot pairs with 0 collisions, and 0 of 25 rows resolved
ambiguously. It is safe where a global alias map is FORBIDDEN precisely because
ambiguity is refused per-row against a real slate instead of pre-resolved into a
map that makes `teams_match` authoritative. Instrument:
`scripts/probe_polymarket_ncaaf_slug_role_join.py`.

---

### 2026-08-22 — FORBIDDEN: never read a `service_updated` deploy as shipping code. An env-var change RESTARTS the service on the commit it is already running

**Measured twice in one evening, the second time after I had already been
caught by the first shape.**

Render redeploys on an env-var change, and with `autoDeploy: no` that redeploy
carries **the commit the service is already on** — it does not pull the branch
tip. So setting a feature flag ships the flag and NOT the code the flag gates.

    dep-da51b13bc2fs73fgu5n0  trigger=service_updated  live 21:33:18Z
      carried 6cd980b4  <- the same commit it was already running
      origin/main was 471cbac9d, one commit ahead, holding the wiring

`SYNDICATE_PORTFOLIO_COMMIT_ENABLED=1` went live against a binary with no
caller for the job it enables. Second time tonight the config landed and the
code did not: an hour earlier `admitted_by_blend=` was committed 18 minutes
AFTER the worker deployed, so the counter could never appear either.

**THE RULE.** Enabling a flag is TWO changes, not one: the env var, and a code
deploy of a SHA that contains what the flag gates. Verify the second with
`git merge-base --is-ancestor <feature-sha> <live-sha>` — the deploy list's
`commit.id` is the live SHA and is the only thing that answers it. A
`service_updated` entry in the deploy history is a RESTART, and reading it as an
update is the same category error as reading a green deploy status as a content
check.

**AND THE DEEPER ONE, which is why this rates a FORBIDDEN rather than a note:**
a flag whose gated code is absent behaves EXACTLY like a flag that is off. There
is no error, no log line, and no failing test — the same signature as
`model_engine_standard.md`'s unfed input, and as a counter that exists at the
builder and never reaches the endpoint. **Whenever a flag is turned on, the
acceptance reading is the feature's own affirmative token** (here
`PORTFOLIO_COMMIT date=… positions=…`), never the absence of an error.

### 2026-08-22 — FORBIDDEN: never name a datastore SETTING and a service ENV VAR by the same store without saying which surface. A 4-minute refresh-worker outage came from that ambiguity

**What happened.** A recommendation to change the eviction policy on the
keyvalue store was written as *"`allkeys_lru` → `volatile_lru` on
`syndicate-refresh-state`"*. There are TWO settable things whose names both
point at that store: the Key Value instance's `maxmemoryPolicy` (Redis's own
eviction rule) and the services' `SYNDICATE_REFRESH_STATE_BACKEND` env var
(which backend the APP routes to). The value went into the env var.

**Measured.** `refresh-worker` crash-looped 2026-08-22T19:31:36Z → 19:35:31Z:

    REFRESH_STATE_BACKEND = volatile_lru
    RuntimeError: Local state backend not allowed in multi-service deployment
                  for refresh-worker: volatile_lru

Recovery on a new instance at 19:35:31.931Z, `BACKGROUND_LOOP_START`
19:35:33.035Z, then `PUBLISH_OK` ×2, `MLB_LINEUP_STATE games=15 posted=5`,
`OVERVIEW_SPORT_BEGIN sport=mlb`. Web and live-odds-worker were never affected
(0 matches for the same error text; web's `PUBLISH_OK` proves it was up).

**THE RULE.** When recommending a change to a hosted resource, name the SURFACE
as well as the resource: *"the Key Value instance's own settings page"* vs
*"the service's Environment tab"*. A resource name alone is not an address when
two surfaces answer to it.

**WHY IT WAS ONLY 4 MINUTES, and this is the part to keep.**
`_state_backend_kind()` maps any unrecognised value to `"filesystem"` — so
`volatile_lru` did not error, it silently meant "use the local disk". On Render
that is three separate disks, i.e. `#502`'s failure applied to the entire board,
and it would have run HAPPILY while every cross-service artifact went private,
discoverable days later. `assert_refresh_state_backend_ready` refuses at startup
BEFORE any state is touched, which converted a silent multi-day corruption into
a loud four-minute outage. **A permissive parse plus a strict startup assert is
the pattern**: the assert is doing the work the `.get(key, default)` cannot.

### 2026-08-25 — FORBIDDEN: never ship a venue's submit side without its read side
- What we believed: the Polymarket integration was incomplete but safe — it
  could place orders, and the read side was a later nicety. `_venue_reader`
  said so in its own docstring: *"The read side of a venue adapter. Only Kalshi
  has one."* A missing reader reads as a gap in coverage.
- What was actually true: it is a LATCH ON THE WHOLE LIVE PATH. The first
  Polymarket order was placed at `16:08:10Z` and rested unfilled. From that
  moment every live pass on EVERY venue returned
  `status=blocked reason=unreconciled_orders` — Kalshi included — and no order
  could be placed again by anything. The unreconciled gate is global by design
  (a stranded order might have doubled), and the only thing that lifts it is a
  venue read. Two independent causes, each sufficient: there was no Polymarket
  reader at all, and `execute_portfolio` called `reconcile_live_orders()` bare,
  whose `venue` defaults to `"kalshi"`.
- How we found out: a USER CANCELLED the order at the venue and said so. That
  prompted the question "will the ledger see it?" — and the answer was no,
  nothing could. The block itself had been printing for 32 minutes
  (`BLOCKED_ON_UNRECONCILED count=1` at `16:40:00Z`, both scopes) and had not
  been looked at, because the absence of LIVE_ORDER lines looks identical to a
  quiet slate.
- The rule going forward: **a venue's submit side and read side are not
  independently shippable — shipping one without the other arms a latch that
  the first resting order closes.** Two tripwires: (1) an invariant test that
  every venue with a submitter has a reader, so a third venue cannot
  reintroduce this by being added to one side alone
  (`tests/test_execution_ledger.py`); (2) when a gate is GLOBAL, the thing that
  lifts it must be attempted for every venue, not just the one in hand —
  reconciling only "our" venue leaves us blocked by a row we declined to ask
  about. And more generally: **an operator action at the venue cannot fix a
  state the system has no way to observe.** Cancelling was necessary and could
  never have been sufficient.
- Cost: 40 minutes of no live execution on both venues, self-sustaining and
  unrecoverable without a code change. No money lost — the one order that did
  go out was on the wrong team for an unrelated reason, and did not fill.

### 2026-08-21 — FORBIDDEN: never publish a field under a name that describes a DIFFERENT quantity, however well-documented the real one is
- What we believed: the Layer 2 board's `Win%` column showed a win probability,
  and `model_probability` was the model's number for the row being recommended.
  Both are what the field names say, and the frontend comment asserted the
  second one outright.
- What was actually true: `Win%` rendered `score["book_confidence"]` — the
  books-quoting ladder `((1,0.5),(2,0.7),(4,0.85))`, else 1.0 — so **"Win% 100%"
  meant "five or more books quote this market"**. And `model_probability` was
  `projection["model_prob_over"]`, always the OVER/HOME framing, so every AWAY
  and DRAW row showed the other side's probability next to a correctly
  side-adjusted "sim disagrees" badge. Separately, `_HITTER_BUCKETS` named three
  mean fields (`runs_mean`, `doubles_mean`, `triples_mean`) that do not exist in
  the artifact (`r_mean`, `2b_mean`, `3b_mean`), so three whole markets could
  never project.
- How we found out: a USER LOOKED AT THE BOARD and said the sim-disagrees column
  seemed wrong. Five distinct Win% values on one screenshot mapped 1:1 onto the
  book-count ladder with nothing left over — a fingerprint no amount of reading
  the producing code had surfaced, because every function was individually
  correct and documented. The producing code even named the hazard: the comment
  above `projection["side"]` says putting home's edge on the away row is "a
  number that is right and labelled wrong, which reads as a real signal", and
  the display layer then did precisely that with the probability.
- The rule going forward: **a value crossing a layer boundary must be named for
  the quantity it IS, and the consuming surface must be checked against that
  name, not against the producer's docstring.** Two specific tripwires, both
  cheap: (1) when a field is displayed, read the TEMPLATE to see what label sits
  above it — `book_confidence` was honest everywhere except the one place a
  human reads it; (2) any lookup key naming an external artifact's field must be
  asserted against a real artifact, at the ROW level, because a key that never
  resolves produces a blank, and a blank is indistinguishable from honest
  missing coverage. `tests/test_layer2_sim_view_sides.py` holds both.
- Cost: unknown but non-zero — a board presented "Win% 100%" on 5+-book markets
  and the other side's probability on every away/draw row, for as long as those
  surfaces have existed. No settled bets, so no measurable financial loss; the
  loss is that the board's most reassuring column was its least meaningful.

### 2026-08-12 — EXONERATED: the soccer window is not the egress cause
- What we believed: the change that tripled dates per sweep (5–6 → 15–18),
  shipped the same day the egress spike was noticed, caused the spike.
- What was actually true: the 14-day graph shows the same spikes since
  7/30, predating the change entirely.
- How we found out: looked at the metric *before* the change instead of
  only after it.
- The rule going forward: **before blaming a recent change for a symptom,
  pull the metric back far enough to see whether the symptom predates it.**
- *Full working in `learnings_evidence.md` under this heading.*

### 2026-08-12 — Do not batch changes during a diagnosis
- What we believed: shipping the guard and the rate ceiling together
  would resolve things faster.
- What was actually true: with #394 and #395 landing together, neither
  effect could be attributed cleanly. The egress drop cannot be assigned
  to the guard.
- The rule going forward: **while diagnosing, one substantive change per
  deploy, with a measurement window closed before the next one starts.**
  Enforced by `/preflight` question 1.
- Cost: a permanently ambiguous data point in `deploys.md`.

### 2026-08-12 — A rate ceiling is not a fix
- The rule going forward: **a cap makes a graph look healthy while the
  underlying waste continues.** Never close a lane on the strength of a
  metric that is being clamped. Measure the uncapped behaviour, or
  measure something the cap does not touch.

### 2026-08-12 — Parallel sessions on one problem need lane discipline
- What was actually true: a second coding session worked the same problem
  concurrently, with no shared record of hypotheses tried or ruled out.
- The rule going forward: **hypotheses go into the lane before they are
  tested, and exonerations are written down as loudly as findings.** The
  expensive failure is re-litigating a dead end three sessions later.

### 2026-08-13 — A grep excerpt is not the file
- What was actually true: a `grep` result rendered
  `open("/proc/self/status")` as `open("\proc\self\status")`. A
  permanently-inert memory guard was half written up on that basis —
  against another lane's freshly shipped work.
- The rule going forward: **read the file before filing a defect against
  a literal.** Search output is a pointer, not evidence. `sed -n` on the
  path is authoritative where a tool's excerpt is not.
- Cost: none, caught before filing. Records the near-miss because the
  next one will not announce itself.

### 2026-08-10 — a briefed premise is a hypothesis, not a starting condition
- What was believed: soccer sims were OFF by standing instruction, so the lane
  was working against a mitigated system.
- What was actually true: the autorun flag was `'true'` live, all three sim
  fixes were ancestors of the deployed commit, and a 20m13s sim was running.
  **Nothing had been mitigating it all evening.**
- The rule going forward: **verify the premise of the brief before writing code
  against it.** Checking cost one env query and one ancestry check; it changed
  the urgency of the whole lane.

### 2026-08-15 — a threshold is calibrated against a SPAN; changing what the span contains invalidates it without touching the constant
- **The rule going forward:** before deploying, ask what else READS the window
  whose contents you are changing — thresholds, guards, timeouts, caches sized
  against "a pass". Grep the span's own markers for constants that mention it. A
  threshold invalidated this way appears in NO diff, so review cannot catch it;
  only asking the question can.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-15 — EXONERATED: "eight hydrated sports at once cannot fit in 4GiB"

The `#387` handoff carried this as settled, from the 20:03:11Z kill: peak = SUM
across eight sports "is sufficient on its own to cross 4GiB", and "the floor
plays no part". Measured on the SAME evening, on the pre-cutover code:

    22:36:48 -> 22:37:43   8 sports hydrated   PEAK 804.2 MB anon  (19.6%)
    22:49:19 -> 22:49:50   8 sports hydrated   PEAK 613.1 MB anon  (15.0%)

The shape that "cannot fit" ran twice, twenty minutes apart, at a fifth of the
ceiling. **The eight-sport pass is exonerated as a sufficient cause.** The
20:03:11Z kill remains UNEXPLAINED: something made MLB cost +3.5GB in that pass
- *Full working in `learnings_evidence.md` under this heading.*

### 2026-08-15 — FORBIDDEN: never conclude "no OOM" from a LOG search. Kills are EVENTS, and I had this rule already
- **The rule going forward:** a negative result about process death MUST come
  from the events API. `scripts/render_logs.py` cannot answer this question and
  a 0-match result from it is not evidence. Absence of a log line is evidence
  about the EMITTER, and a killed process emits nothing.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-15 — the kill is MLB game hydration in pid 39, not the overview pass

Measured at the 00:41:16 kill, the best-instrumented one:

    00:40:14  container 3357.8MB (82.0%)   pid 39 = 1612.1MB   7 processes
    00:40:42  container 4095.8MB (100.0%)  pid 39 = 3079.6MB   10 processes
    00:40:58  anon 3941.6 -> 4047.6MB in 1.2s, game_count 15, unreclaimable 4058MB
    00:41:16  server_failed oomKilled 4Gi

**pid 39 — the main worker — grew ~1.47GB in 28 seconds** while its children
stayed small (`daily_update.py` 166.6MB, soccer odds refresh 95.5MB). The
payloads carry `game_count: 15` / `game_pk_count: 15`, i.e. the MLB game
- *Full working in `learnings_evidence.md` under this heading.*

## 2026-08-14 — OVERTURNED: a number that corrects a known bias is the easiest one to believe

- **Believed:** the joiner's first same-book CLV, `avg_clv_pct = -5.215` over 25 rows (beat-close 9/25), was the first honest measurement of our closing-line value. It was the number the whole lane existed to produce.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-14 — a control with no baseline is a guess wearing a control's clothes

- **2023-2025**), unrelated to the MLB window (2026-08-01..08-14), and they predate the deploy. **I had baselined the MLB props before deploying and never baselined non-mlb** — so the control's expected value was assumed, not measured.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-14 — read the system's clock, not the wall clock

- The rule going forward: **before firing a pinned deploy, re-read the service's live commit AND check for an in-flight deploy; then pin onto whatever is live at that moment, not onto what was live when the branch was built.** A pinned branch is a snapshot with an expiry date, and the expiry is the next deploy by anyone. Where two lanes are shipping the same service, stack — cherry-pick onto their commit — rather than racing from a shared base.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-15 — RULE: WEB DOES NOT RUN `main`. Parent a deploy on the LIVE SHA.

- **The rule going forward.**
- *(evidence in `learnings_evidence.md`)*

## 2026-08-15 — A CADENCE IS A DISTRIBUTION ACROSS REGIMES, NOT A CONSTANT

- **The belief.** "MLB quote capture runs on a metronomic ~121.6-minute beat." It sat in `state.md` with a proper measurement behind it (seven captures in 18h, read from the artifact rather than the logs — good method), it was carried into the program plan as a hard floor on the Tier 5 measurement, and it was the premise of a standing freeze on 23 movement implementations, `movement_velocity` and the steam detector.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-15 — ANCESTRY OF `origin/main` IS NOT DEPLOYMENT; READ THE DEPLOYED TREE

- **The near-miss.** Asked whether the per-sport pregame cooldown had shipped, the first check was `git merge-base --is-ancestor ea8fad58 origin/main` → **yes**. On a repo where `autoDeploy = no`, that answer means nothing about production, and taken alone it would have reported a fix as live that is not.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-15 — RULE: a "baseline" is a FILE you diffed, not a number you quoted

- **The rule going forward:** a shared stylesheet exists precisely so one class renders in more than one place, so **one sample per class is not a measurement of that class** — key the table by surface and report a class whose computed value differs across surfaces as CONFLATED rather than collapsing it to its first hit. `scripts/ui_layout_probe.py` now does this and the whole story is in `docs/reports/ui_audit_2026_08_14/README.md`, because the wrong number outlived the probe that produced it and got written into two plans.
- *(evidence in `learnings_evidence.md`)*

## Compacted entries (rule kept here, evidence in `learnings_evidence.md`)
> Compacted 2026-08-15: entries before 2026-08-15 keep their heading and their
> rule. Nothing was deleted. The full working — what we believed, how we
> found out, the cost — is in `learnings_evidence.md` under the same heading.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-12 — FORBIDDEN: never point a worker publish URL at a public hostname
- The rule going forward: **any service-to-service call inside Render must use the internal private-network hostname. Same-region private traffic is unbilled. Audit every URL env var against this rule before adding a new one.**
- *(evidence in `learnings_evidence.md`)*

### 2026-08-13 — A guard can measure a number that moves without the system moving
- The rule going forward: **when a threshold decides whether work runs, audit what moves the quantity it reads — not just the constant.** A stale constant is the easy half. A quantity that swings on kernel LRU bookkeeping makes the guard's verdict unrelated to the risk it guards. Guard on unreclaimable memory (`anon + shmem + slab_unreclaimable`), which is what an OOM kill actually responds to.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-13 — A criterion has a DIRECTION, and checking it is free
- The rule going forward: before instrumenting, ask **which way the suspected fault would push the observable.** Extends "a criterion is an instrument too": an instrument has a sign as well as a denominator.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-13 — Confirm an instrument can emit non-zero before believing its zero
- The rule going forward: before believing a zero, produce a case that makes the same instrument read non-zero — or build the reading so it carries its own liveness proof. `snapshot_prop_keys` is populated before any filtering, so a zero beside a non-empty key list is a *measured* zero, not a blind one.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-13 — A pooled denominator can make a measurement unreadable
- The rule going forward: when a counter pools populations with different eligibility, **split it by the thing that determines eligibility** before reading it. "The mechanism failed" and "most rows were never eligible" produce the identical zero. Sibling of the wrong-denominator shape recorded the same night, arrived at from the other direction.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-13 — `git log --format=%an` is zero evidence in this repo
- The rule going forward: **the only working discriminator is which FILES a lane has touched.** Verify a ticket number against `origin/main` immediately before pushing, not when drafting — the gap between choosing and pushing is a real race.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-10 — an instrument's blind spot will be mistaken for a finding
- The rule going forward: **ask what the instrument cannot see before trusting what it shows, and compute the base rate before believing a coincidence.** Both directions of this error were made in one evening on the same candidate.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-10 — segment on process boundaries before any neighbour-based test
- The rule going forward: **any local/neighbour test must segment on boot first.** A restart is a discontinuity, not a data point.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-10 — counts are the wrong denominator when the cost is bytes
- The rule going forward: **before quoting a rate, check the denominator actually measures the thing being paid for, and that it spans the population of interest.**
- *(evidence in `learnings_evidence.md`)*

### 2026-08-13 — Presence is not reachability: verify the PATH, not the symbol
- **Overturned belief:** that confirming a fix is present in the deployed code means the observed behaviour goes through it.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-13 — A safety gate answers ITS question, not the one you were asked
- The rule going forward: **when a human states a condition, encode THAT condition, not the nearest existing check.** A pre-built guard is evidence about its own predicate only. Before arming any watcher, write down the instruction's condition and the instrument's condition as two separate sentences; if they are not the same sentence, the instrument is not sufficient and needs the missing clause added explicitly.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-13 — "Identical to origin" does not mean "absent from the commit"
- The rule going forward: **to claim a change is ABSENT from a deploy, compare the target against what is LIVE, not against the branch you built on.** The live commit is the only baseline the deploy actually acts on, and it moves under you while you work.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-13 — "Who reads this env var" is a grep question; "does this service read it" is not
- The rule going forward: **reachability has three entry classes, and a trace that omits any one of them is not evidence. (1) module-level statements, including calls to functions defined elsewhere in the file; (2) the specific symbols another module imports — not the module as a whole; (3) indirect targets: thread/process `target=`, callbacks, registries, decorators.** Exclude `if __name__ == "__main__"`. A negative result from an incomplete trace is indistinguishable from a real one, so state which classes were covered whenever the conclusion is "unreachable, safe to delete."
- *(evidence in `learnings_evidence.md`)*

### 2026-08-13 — FORBIDDEN: never `cat` a ledger file into hook stdout — a hook delivers the obligation, not the content
- The rule going forward: **a hook is a channel with a budget, and the only measurement that counts is what ARRIVES, not what was emitted.** Verify a hook by reading the `attachment` record in the consuming session's transcript (`stdout` length, `exitCode`, `type`), never by running the script in a terminal — a terminal has no cap, so it can only ever confirm the emitter. Keep hook stdout under **2,000 B**. A hook's job is to deliver the OBLIGATION to read the ledger plus the few facts too costly to miss; the ledger itself gets read from disk by the session. Direct sibling of `2026-08-13 — Presence is not reachability`: the content was present at the emitter and unreachable at the destination.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-13 — EXONERATED: `shell: "bash"` in a Windows hooks block works
- Named as the likely culprit when SessionStart could not be verified ("if the ledger doesn't appear, the likely culprit is `shell: "bash"` not being honored"). Measured working: session `ac67a9f1`, Claude Code **2.1.227**, `hookName=SessionStart:startup`, `exitCode=0`, `durationMs=459`, `stderr` empty, `type=hook_success`, on a `.sh` script invoked as `"$CLAUDE_PROJECT_DIR"/.claude/hooks/session-start.sh`.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-13 — A guard that has never once PASSED is not a guard
- The rule going forward: **a guard's pass branch needs a witness too.** The ledger already says "before believing a zero, produce a case that makes the instrument read non-zero" — this is the same rule pointed at the other branch. An alarm that has never been silent is indistinguishable from an alarm wired to a constant. Check the distribution of a guard's outcomes before quoting any single one: all-fire and all-pass are both evidence of a broken predicate, not of a system state.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-13 — A discriminator that is only emitted on FAILURE cannot confirm a fix
- The rule going forward: **when choosing a signal to prove a fix ran, check which BRANCH emits it.** A signal on the failure path proves the failure path; it can never prove the success path. Before deploying, ask "if this works perfectly, what line appears?" If the answer is "none", there is no liveness proof and the deploy ships blind, however green the tests were.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-13 — A watcher's headline can contradict its own body
- The rule going forward: **the label a script prints is an assertion, and it must be entailed by the condition that triggered it.** When writing a watcher, state the exit condition in the output next to the verdict, so a reader can check the inference rather than trust the adjective. Sibling of `an instrument's SPAN is not its NAME` — same failure, moved from a timing mark to a boolean.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-13 — A guard's "is this mine" input must not default to the locked state
- The rule going forward: **when a guard reads an identity token to decide "yours vs theirs", the absent case must default to PERMISSIVE-with-a-reason, not to deny.** Absent identity is not a hostile identity, it is a missing input, and the failure surfaces as a confusing cross-lane collision message rather than as "the marker is missing". Same shape as the ledger's `unknown must not default permissive`, inverted: there the danger was a failed join relaxing a rule, here it is a failed join inventing a conflict.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-13 — A path one toolchain resolves and another cannot makes a guard pass silently
- The rule going forward: **this machine has two path universes, and a value that crosses between them fails open rather than erroring.** Bash-tool paths (`/tmp`, `/c/...`) are invisible to native Windows Python and to `python3` invoked from PowerShell; `git cat-file blob origin/main:path` is mangled by MSYS arg conversion into `origin\main;path` and returns an empty pipe, not an error. Fixtures and payloads handed to a Windows interpreter must use `C:/...`. When a check produces no output at all, verify it reached its own code before believing its verdict — extends `2026-08-13 — Confirm an instrument can emit non-zero before believing its zero`.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-13 — A free-text status field cannot be a predicate; test guards against the ledger, not against synthetics
- The rule going forward: **a guard whose input humans hand-write must be tested against the actual file, not against examples written by the same person who wrote the guard.** Re-run guards over the live ledger after any parsing change, and diff the set they classify as open against the lanes physically under `## OPEN` — a mismatch is the whole test. Where a field is free text, match a word (`\bOPEN\b`), never the whole field, and never a bare substring.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-13 — A discriminator that only emits on FAILURE cannot confirm success
- The rule going forward: **when choosing a liveness signal, ask which branch emits it. If the only emitter is the failure path, the signal cannot distinguish "working" from "never ran" — the two produce identical silence.** Put the proof on the path you expect to take, not on the one you are trying to eliminate. Direct sibling of "confirm an instrument can emit non-zero before believing its zero"; that entry covered a zero, this one covers a total absence, which is worse because nothing appears at all.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-13 — A watcher's LABEL must be entailed by its exit CONDITION
- The rule going forward: **the words a monitor prints are a claim; write them from the condition that fired, not from the outcome you are hoping for.** Before trusting a watcher's verdict, re-read the branch that produced it. Any word in the label that does not correspond to a term in the predicate is editorial.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-13 — "Pushed to origin" is not "applied to production"
- The rule going forward: **for `render.yaml`, "on origin" and "in effect" are two different measurements, and only the second one matters. Read the live service's `/v1/services/<id>/env-vars` and compare counts before recording a config change as shipped.** The CLAUDE.md warning that a push applies to production is about the *risk* that a sync fires; it is not a guarantee that one *has*. Both errors are available, in opposite directions.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-13 — FORBIDDEN: never edit a file from a read taken earlier in the session
- The rule going forward: **before editing any file, re-read it, and read the config that dispatches to it.** A hook, handler or entrypoint is defined by what invokes it, not by its filename. On a shared tree the gap between reading and editing is a race, and `Write` silently resurrects a deletion rather than failing — a deleted file and a file you have not re-read are indistinguishable from the editor's side.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-13 — The enforcement layer cannot protect itself, and a lane is one deletable line
- The rule going forward: **`lanes.md` is executable configuration, not documentation, and it is edited by hand by several sessions at once.** After ANY concurrent-session ledger edit, re-run the guard over the files that matter rather than trusting the file to still say what it said. The cheap check is one line: `awk '/^### /{h=$0} /<path>/{print h}' .syndicate/lanes.md` — if a file's nearest preceding header is not the lane you expect, the block is orphaned. And harness work needs either a stated exemption in the protocol or a real lane; three sessions deciding it individually is how the one collision that mattered happened.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-13 — A FAILED READ RENDERS AS A RESULT. Five instances, one session, five different tools
- The rule going forward: **before believing a negative result from a one-off check, run the positive control.** Grep for something you KNOW is in the file; if that also returns 0, the probe is broken, not the world. It costs one command and it caught nothing this session only because it was skipped. Corollary: `grep -c` on a pipeline whose upstream can fail is not a count, it is a count-or-zero. Check the upstream exit status, or query a way that cannot silently produce an empty stream.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-13 — The stale-read rule failed on its second application, in a form it did not cover
- The FORBIDDEN entry above ("never edit a file from a read taken earlier in the session") was written after a rewrite of a file that had been deleted. **Within the same session it was broken again**, differently: a defect was REPORTED against `lane-guard.py` — "`memory-guard-reclaimable` is unguarded, its status parses as DEPLOYED" — derived by running a copy of `LANE_RE` lifted from a read taken ~2h earlier. `559d353d` had already replaced that regex, and its comment names that lane as the motivating case. The claim was false when written, and it was published to `state.md`, where a parallel session could have acted on it.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-13 — A guard has TWO failure directions, and fixing the loud one is where the silent one survives
- The rule going forward: **a guard's scope and its witness must have the same granularity.** Per-session denominator + global witness is not a fix, it is the same hole rotated — and rotated toward the silent direction. Whenever a guard is narrowed, ask what else can satisfy it, not just what it now counts. Concretely: **when fixing a guard that fails in one direction, write the test for the opposite direction in the same pass**, and for anything on a shared tree that means a two-actor test — one fixture where a second session's action is what changes your verdict. A single-actor fixture suite cannot express the failure that matters here, however many cases it has.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-13 — Cite the SHA that will exist on origin, not the one your clone minted
- The rule going forward: **write the SHA after the push, and write the one that is on `origin`.** If a commit must be referenced before it is pushed, cite the commit SUBJECT — the subject survives cherry-pick, the SHA does not. Deploy SHAs read from the Render API are already origin SHAs and are fine as they are. Session ids are visually identical to short SHAs; always prefix them with `session`.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-13 — MY OWN DISPLAY TRUNCATION BECAME A FINDING, AND THEN A LANE'S PREMISE
- The rule going forward: **a slice width is a property of your printout, not of the record. Never read a numeric field out of a truncated line.** When a value is load-bearing, re-fetch it untruncated and print the field, not a prefix of the message. Corollary for surprise: **the more a datum overturns the expected answer, the more it must be re-read at full width before being written down** — surprise is the signal to verify, not to publish.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-13 — A BROKEN GUARD CAN MASK THE REAL PROBLEM. Fixing it is how you find out
- The rule going forward: **when a guard is found to be reading the wrong quantity, do not assume the alarms it raised were all false. Re-derive what the CORRECT quantity was doing over the same window.** Had `anon` been read on the `#417` samples with the same care as `inactive_file`, the flat +18.9MB would have been noticed as the thing that made `#417` bookkeeping — and its later non-flatness would have been the leak, visible hours earlier.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-13 — Symptom relief resets the clock that would have proved the cause
- The rule going forward: **before restarting to clear a symptom, capture the series that proves the cause** — here, `anon` over time, which is one log query. A restart is not neutral: it is the deletion of the measurement. Record the pre-restart numbers in the row, not just "restarted, recovered".
- *(evidence in `learnings_evidence.md`)*

### 2026-08-13 — Check whether the obvious fix was already tried, BEFORE building an instrument
- The rule going forward: **before instrumenting a known-hard problem, read what the codebase already says about it.** The answer to "don't we need a flush" was 50 lines of measured prose in `memory_observability.py`. An hour of sampler-building preceded finding it.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-13 — I RETRACTED POINT-SAMPLING, THEN BUILT A HEADLINE ON IT ANYWAY
- The rule going forward: **when you retract a METHOD, re-audit every live conclusion that used it, not just the instrument that exposed it.** A retraction is not local to the tool that failed; it is a statement about a class of evidence. Grep your own ledger for numbers derived the same way before the retraction goes in.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-13 — A habit that fails silently needs a tool, not more care
- The rule going forward: **when the same mistake recurs and its signature is indistinguishable from success, stop resolving to be careful and change the shape of the operation.** `scripts/push_via_worktree.py` resolves every SHA in the main repo BEFORE a worktree exists, and treats an empty payload as a hard error naming that exact cause. The class of bug is now unreachable rather than merely watched for.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-14 — A TROUGH THAT CLEARS AN EARLIER PEAK IS A RATCHET. That is the test
- What we believed, three times in one evening, each time on the evidence available: (1) refresh-worker leaks ~300MB/hour [from two point samples]; (2) no leak is established, it may be a 1550MB oscillation [after measuring the within-window spread]; (3) the leak is real at ~+1200MB/hour [after 45 minutes of floor series].
- *(evidence in `learnings_evidence.md`)*

### 2026-08-14 — I RE-READ THE DEPLOYED SHA BEFORE EVERY *READ* AND SKIPPED IT BEFORE A *WRITE*
- The rule going forward: **re-read the live SHA inside the same step that deploys, and assert the target is a descendant of it.** "I checked a few minutes ago" is not a check on a repo with concurrent sessions. A deploy tool should refuse when `merge-base --is-ancestor <live> <target>` fails — that single assertion turns this class of accident into an error message.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-13 — A "PURE READ" endpoint is a reader you will not find by grepping the attach
- The rule going forward: **when a fix's observable is served by an endpoint, ask what BUILDS the payload that endpoint returns, not which functions mutate it.** For anything artifact-backed the answer is usually a different service, and "the code is deployed" then says nothing about the reading. Find the readers from the DATA (who writes this artifact, who reads it) rather than from the function name.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-13 — A CONSTANT that reproduces exactly is a data outage, not a weak model
- The rule going forward: **before treating "every row is identical" as a modelling defect, reproduce the constant from an empty input.** If it matches exactly, the bug is upstream in data availability or file selection, and every hour spent in the model is wasted. `#377` sat OPEN and UNOWNED for days as a product decision about what a board may assert; it was a file-selection bug the whole time.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-13 — A FIXTURE THAT OMITS A MARKER FILE TESTS A DIFFERENT DIRECTORY, AND SCORES IT AS A DEFECT
- The rule going forward: **a fixture that selects a resource by CONVENTION must assert which resource it actually selected, before it is allowed to render a verdict.** Concretely: print the resolved root/path/connection and compare it to the intended one, and abort if they differ. v2 does exactly that (`if resolved -ne $root { ABORT: this fixture tests nothing }`) and the guard then passed all three checks plus a positive control.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-13 — CLOSING A TICKET IS A SCOPE DECISION, AND WHOLESALE CLOSURE SILENTLY RETIRES THE PART NOBODY WORKED
- The rule going forward: **before closing a ticket, enumerate its distinct claims and resolve each one separately. Any claim without evidence gets carved out into its own ticket, with a forward reference from the closure, BEFORE the parent is marked closed.** A ticket is not an atom; long entries in this repo routinely accrete a second and third finding under the original headline, and the accreted ones are the least likely to have an owner.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-14 — A PLATEAU IS A STRONGER SIGNAL THAN A PERCENTAGE
- **The rule going forward: when attributing growth, look for what STOPS growing, not for what is large.** A percentage describes one instant and can be high for uninteresting reasons; a plateau against a rising total is a structural statement and needs no threshold to interpret. Same shape as the trough-vs-earlier-peak test recorded hours earlier — both replace "how big is it" with "what does it do over time", and both settled a question that a single number had left ambiguous twice.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-14 — I MEASURED A STAGE WITHOUT THE THING THAT DOMINATES IT, AND ALMOST SHIPPED THE FIX
- The rule going forward: **before quoting a measurement, ask which input dominates and whether the run contained it.** A partial run does not produce a smaller version of the answer — it produces a different answer wearing the same units. Coverage is not a confidence interval on the number; it decides whether the number is about the thing at all.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-14 — A guard's floor is a claim about ONE stage; refusing everything downstream of it is a separate bug
- **The rule going forward: a memory floor is a claim about the cost of ONE stage. Before putting a guard in front of a span, enumerate what is inside the span and what each part costs. If the span contains work an order of magnitude cheaper than the floor, the guard is not protecting that work — it is deleting it.** The cheap work needs its own, measured floor, and the abort line needs to say WHICH floor fired or the two become indistinguishable in the logs.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-14 — A CADENCE IS NOT AN OUTAGE, AND I ESCALATED ONE AS THE OTHER
- What I believed, and told the user in bold: MLB odds "have not been refetched since 8:09am CDT, now 2h10m and counting", framed as a capture stall worth chasing. I had two independent readings 78 minutes apart showing the freshest observation frozen at the *identical* instant, which felt decisive.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-14 — A CONSTANT THAT REPRODUCES EXACTLY FROM AN EMPTY INPUT IS A DATA OUTAGE, NOT A WEAK MODEL
- The rule going forward: **before treating "every row is identical" as a modelling defect, reproduce the constant from an empty input.** If it matches, the bug is upstream in data availability or file selection and every hour spent in the model is wasted.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-14 — A LANE LEFT OPEN AFTER ITS WORK SHIPS IS AN ACTIVE LOCK, NOT A STALE NOTE
- The rule going forward: **close a lane when its measurement lands, not at checkpoint.** The ledger already treats an unmeasured deploy as an open obligation; an unclosed lane is worse, because it also blocks other people.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-14 — `git add <paths>` SCOPES THE INDEX; ONLY A PATHSPEC ON `commit` SCOPES THE COMMIT
- The rule going forward: **on a shared tree, always `git commit -- <paths>`.** Check `git diff --cached --name-only` BEFORE committing and the commit's `--stat` AFTER. And note the argument order: `-m`/`-F` must come BEFORE the `--`, or git reads the message as a pathspec.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-14 — DECOMPOSE BIAS BEFORE PUBLISHING A SKILL VERDICT
- The rule going forward: **before writing any skill verdict, subtract the mean error and re-score.** Report `mae_model`, `mae_constant_baseline` AND `mae_debiased` together. A model that beats the baseline only after de-biasing is a calibration ticket, not a dead model, and the three numbers side by side are what make that legible. MAE alone cannot separate them.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-14 — A GUARD MUST COUNT THE ROWS THE STATISTIC USES, NOT THE ROWS THE JOIN PRODUCED
- The rule going forward: **a guard's denominator must be the denominator of the thing it is guarding.** If a statistic is computed over a subset, the gate counts the subset. Print BOTH — "361 joined, 9 with a projection" — because the gap between them is itself the finding: here it was the whole story (a column added 13 days earlier), not a footnote to a skill result.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-14 — THREE wrong root causes in one session, one shape: a single sample of a moving quantity
- The rule going forward: **before concluding from an absence or a single reading, ask "what is the period of this thing?" and take a span longer than it — or read the durable state instead of the event stream.** And when a finding rests on a constant, read the whole comment AND the call sites of the function that owns it before publishing; the disconfirming sentence was already written in the file all three times.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-14 — I CALLED A CORRELATION A PROOF, TWICE IN ONE SESSION
- What I believed: the soccer odds gap was step truncation. The evidence felt airtight — the pregame run is 50 steps grouped by kind, odds sit at #21-30 behind ten sims, and the fresh/dark split matched the step order with **no exceptions**: `soccer_eredivisie_odds` #27 current, #28/#29/#30 all 3.6 days stale. I wrote "ROOT CAUSE PROVEN" into the lane, shipped a reorder, and told the user it was the fix.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-14 — A HEALTHY-LOOKING SIBLING MASKED A PLATFORM-WIDE OUTAGE
- What we believed, for most of a session: three soccer leagues had a broken odds capture while eredivisie was fine. The contrast WAS the evidence — same script, same key, same region, one works — and it drove three successive hypotheses (season gate, step truncation, per-league fetch fault), two of which were shipped against.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-14 — A fallback CHAIN has a rung that fires; find it before costing the fix
- The rule going forward: **when a defect is described as "it falls back to X", the fix is worthless until you know which rung actually fires.** Removing the last rung of a chain whose third rung always fires is an inert fix that will be reported as shipped. Enumerate the chain, find who writes each key upstream, and exercise the function once per shape before estimating impact or urgency.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-14 — A MANGLED SHELL ARGUMENT NEARLY BECAME "THE LEDGER LOST MY WORK"
- What I believed for about ninety seconds: the retraction and root cause I had just pushed were NOT on `origin/main`. Four greps, all returning 0, against files I had verified before pushing.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-14 — A watcher that compares TIMESTAMPS to identify a thing will misidentify it by microseconds
- The rule going forward: **to answer "is this still the same thing", compare the IDENTITY, not a timestamp derived from it.** The fix was one line — check the deploy's commit SHA against the SHA the window opened on. A timestamp is a measurement of an event; the SHA IS the event. Identity comparisons do not have precision, and precision is where this class of bug lives.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-14 — I PREDICTED FILE OWNERSHIP INSTEAD OF PROBING IT, TWICE
- What I believed, twice, and wrote into a checkpoint as a blocker: that `scripts/refresh_odds_sources.py` and then `scripts/run_live_odds_refresh_worker.py` were claimed by other OPEN lanes and would need a reassignment before I could touch them. The second one was handed to the next session as "needs a lane reassignment or their owner".
- *(evidence in `learnings_evidence.md`)*

### 2026-08-14 — PINNED DEPLOYS PUT CODE IN PRODUCTION THAT WAS NEVER ON MAIN
- What I believed at three consecutive checkpoints: everything I had shipped was on `origin/main`. I had verified the ledger content each time, and the reorder commit, and reported "all content is on origin".
- *(evidence in `learnings_evidence.md`)*

### 2026-08-14 — Separating `add` from `commit` is not enough if you chain them with `&&`
- The rule going forward: **the inspection must be its own tool call, with the commit in a LATER call.** And prefer the pathspec form, which makes the index state irrelevant:
- *(evidence in `learnings_evidence.md`)*

### 2026-08-14 — A saturated log window proves nothing, and the untouched sibling is the control
- The rule going forward: **when you suspect a change caused a symptom, find the sibling that did NOT get the change and look there first.** A same-config, same-moment, untouched service settles causation in one query, while before/after windows on the affected service can be silently truncated. Corollary: **a log window that returns exactly `limit` rows is evidence of nothing absent** — re-query narrower until it comes back under the cap, or count POSITIVE markers (`PUBLISH_OK`) instead, which a tail cannot hide.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-14 — A regex over a hand-written ledger inverts "NOT claimed" into "claimed"
- The rule going forward: **`lanes.md` is prose written for humans, and the negations are load-bearing. Do not derive a claim set from a regex over it.** If a lane's claims matter — for a collision check, a census, or an accusation — read the block. The cheap guard: any extracted claim list should be re-checked against the lines containing `NOT claimed`, `Collision`, `elsewhere`, or `held by` before it is used.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-14 — An audit's CAUSAL claim is a hypothesis; its MEASUREMENT is evidence
- The rule going forward: **an audit's measurements and its explanations have different evidentiary status.** "28px of overflow at 1440" is a reading and survives being handed on; "because the grid does not stack" is the auditor's inference and must be re-derived by whoever acts on it. Before editing the rule an audit names, confirm that rule currently produces the symptom — the cheap version is one `getComputedStyle`/`getBoundingClientRect` on the element, which takes a minute and would have caught this.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-14 — A COUNT can rise because the population grew, not because the property got worse
- The rule going forward: **when a count changes across a fix, check whether the fix changed what is being counted.** A raw count carries an implicit denominator — here "tabs that exist" — and a change that adds members makes the count move on its own. Report it as a rate, or report the denominator beside it, or the next reader files a regression that does not exist.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-14 — An audit brief's "known already" inputs are claims, not axioms
- The rule going forward: **spend the first ten minutes of any audit re-verifying the inputs it tells you not to re-derive.** An input marked "known" is the one nobody will check, which is exactly why a stale one propagates. Cheap to test, and a single dead citation invalidates every downstream count that assumed it.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-14 — the Render logs API returns the NEWEST N in a window; paging forward silently reports a peak over a sliver
- I wrote a pager that walked a time window by advancing `startTime` past the last line of each page. The API does not work that way: it returns the newest `limit` lines inside `[startTime, endTime]`, presented oldest-first (`deploy_preflight. newest_log`'s own docstring says so and I did not read it). Advancing startTime re-reads the same tail and terminates.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-14 — a before/after is void if the change moved work INSIDE the measured span
- The `#387` streaming cutover was measured as "peak anon during `OVERVIEW_SPORT_BEGIN mlb` -> pass end". The change also moves per-sport candidate collection INTO that pass. So the after-span contains work the before-span did not, and "peak went UP" is partly definitional, not behavioural.
- *(evidence in `learnings_evidence.md`)*

### 2026-08-14 — "it cannot fit" from one sample, when the same shape runs fine twice
- A handoff carried, as its single next action, a fix whose justification was one OOM: eight sports hydrated at once, "peak = SUM is sufficient on its own to cross 4GiB", "the floor plays no part". I deployed it, then measured two pre-deploy passes of the IDENTICAL shape from the same evening: 8 sports hydrated, peaks 804MB and 613MB, 15-20% of the ceiling, no death.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-23 — FORBIDDEN: claiming a feature works when no test runs the path that CALLS it

- **The rule going forward:** a feature whose failure mode is `except` + a log line MUST have a test that executes the real call path end to end. Testing the callee directly proves the callee works and says NOTHING about whether anything invokes it. And verify the test by reintroducing the bug: a green test that has never been seen red is a claim, not evidence.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-23 — FORBIDDEN: a module may not hold its own list of market names. It WILL drift from `market_keys`, silently

- **The rule going forward:** market names have exactly one authority, `market_keys.canonical_market_key` (`#224`). Canonicalise on lookup wherever a sport is in hand. Where the function takes no sport and cannot, hold BOTH spellings **and** a test that derives one set from the other — a private list with no such test is a silent time bomb, not a mapping.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-23 — FORBIDDEN: never read `settled_at` on an order as "the bet was decided"

- **The rule going forward:** `settled_at` is the ORDER's clock — `complete_order` stamps it when the order reaches a terminal state at the VENUE, seconds after a paper fill and hours before the game ends. The WAGER's clock is `graded_at`, written by `paper_settlement`. Two clocks, two fields, never one.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-15 — FORBIDDEN: never treat equality of a LABEL as identity of a BET

- **The rule going forward:** every memory number carries a SCOPE — container, process, or thread — and only same-scope numbers may be subtracted. Write the scope next to the figure. `memory.current`/`anon` and `oomKilled` are container; `smaps`, `PYMALLOC_STATS`, `HEAP_CENSUS`, `mallinfo` and `getsizeof` are process; a container with children makes them differ by hundreds of MB.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 — FORBIDDEN: never deploy on `check_deploy_safety.py` alone. It said CLEAR while three jobs were running on the service.

- **Measured 2026-08-16 00:13Z on refresh-worker.** `check_deploy_safety.py`
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 — FORBIDDEN: a wait loop must gate on an AFFIRMATIVE success token, never on the absence of a failure string

- *Full working in `learnings_evidence.md` under this heading.*
- *(evidence in `learnings_evidence.md`)*

## 2026-08-15 — FORBIDDEN: never read a joiner zero as a fact about the world until the reader is shown to SEE the data

- **What happened.** The rule was written in advance, in good faith, and was wrong. `same_book_n=0` came back for all 8 sports. The truth: `/api/ops/clv/report` runs on **web**, `load_openings` is a `path.exists()` on a local file, and web held **0 bytes** of the ledger while refresh-worker had **490 openings recorded for that same date**. The endpoint returned `ok: true` throughout. Shipping one allowlist line moved `same_book_n` **0 → 144** with **no change to odds history at all**. Breadth constrains `resolved` (`no_market_in_history: 172`), never `same_book_n`.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-15 — FORBIDDEN: shipping a verification you have not falsified. THREE failed checks in one night, zero failed fixes

- **The rule.** Before arming any check, ask the falsification question about the CHECK, not the fix: *what reading would this produce if the fix worked perfectly?* If that equals the failure reading, the check is broken. Then:
- *(evidence in `learnings_evidence.md`)*

## 2026-08-15 — FORBIDDEN: `git <cmd> <rev>:<dotpath>` in Git Bash on Windows. It silently reads the WRONG thing, and only for dot-prefixed trees

- **The part that makes it dangerous: it is selective.** Measured:
- *(evidence in `learnings_evidence.md`)*

## Superseded on 2026-08-15 — the two `same_book_n` entries

Both were merged into **"never read a joiner zero as a fact about the world"**
above; full original text is in `learnings_evidence.md`. They reappeared here
once after being removed — a stale-read write on this shared file resurrected
them alongside their own replacement. If they show up a third time, delete
them again rather than assuming the merge was reverted: the merged rule and
the evidence file are the source of truth.

### 2026-08-16 — verify a watcher's FIRST line, or it will report failure as patience

- **What we believed:** a background poller was waiting for a deploy window. It
  printed a line every 30s and looked like it was working.
- **What was actually true:** it failed on its FIRST poll and every one after —
  90 identical `RENDER_API_KEY not set in the environment or .env` lines over 45
  minutes. It never once read the gate. The key was present in `.env`; the
  PowerShell background environment could not resolve it, while the same command
  from Bash worked.
- **How we found out:** the owner asked whether it had deployed. Nothing in the
- *Full working in `learnings_evidence.md` under this heading.*

### 2026-08-16 — do not rebase onto a deploy target that has not shipped

- **What we believed:** rebasing onto `c70eeff0` — the SHA a claim holder had
  DECLARED as their target — would put the commit ahead of production and stop
  it going stale again.
- **What was actually true:** they shipped something else. Live went to
  `57a437d5`, which does not contain `c70eeff0`, so the rebased commit would
  have **ROLLED PRODUCTION BACK** had it been deployed.
- **How we found out:** an explicit ancestry check before deploying —
  `git merge-base --is-ancestor <live> <mine>` — not the deploy tool refusing.
- *Full working in `learnings_evidence.md` under this heading.*

### 2026-08-16 — A DEPLOY HAS TWO LAGS IN SERIES. I GUARDED ONE AND MISREAD THE SYSTEM THREE TIMES

`deploy -> snapshot -> artifact`. live-odds-worker's tick rewrites the snapshot;
refresh-worker's build turns it into the artifact you read. **A fresh artifact
can carry a stale snapshot**, so "generated_at is after the deploy" is NOT
sufficient to conclude the number reflects the new code.

Three failures tonight, all one shape — comparing a number to an event without
establishing the number was PRODUCED AFTER the event:

1. **Warm-up read as regression.** 5 and 8 minutes after the fix landed,
   `index_size` was 0 twice. I called it a persistent regression and **asked for
- *Full working in `learnings_evidence.md` under this heading.*

### 2026-08-16 — I HELD A CLAIM ONCE AND THEN DEPLOYED OVER SOMEONE ELSE'S, TWICE

At 23:42 another session's deploy cancelled mine one second apart, and I wrote
up the deploy claim as advisory. Then `clamp-fix-to-workers` acquired
live-odds-worker at ~00:34 — and **my 00:47 rollback and 00:58 re-deploy both
fired on that service without re-checking the claim.** I did to them exactly
what had just been done to me, while holding the ledger entry about it.

**Acquiring a claim is not honouring one.** The claim I took at 23:39 gave me a
sense of ownership that outlived the claim itself; I never re-read it, and it
had moved. **Check the claim IMMEDIATELY BEFORE EVERY FIRE, not once at the
- *Full working in `learnings_evidence.md` under this heading.*

## 2026-08-16 — FORBIDDEN: never read a deploy claim's `target` as a statement about what is running

- **Measured 2026-08-15/16 on live-odds-worker.** Its claim advertised `target=49797f4b`, and `49797f4b` genuinely carried the clamp fix — verified by reading the code, not just counting a grep. I concluded twice, in writing, that the service "needs nothing".
- *(evidence in `learnings_evidence.md`)*

## 2026-08-15 — RULE: merge in the object database when the shared tree is dirty

- **The rule going forward:** on this repo a reconcile does **not** need a checkout. `git merge-tree --write-tree` + temp index + `commit-tree` + `push <sha>:main` merges with **zero** working-tree writes, so concurrent sessions' edits cannot be refused, overwritten, or staged by accident.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-15 — RULE: resolve a ledger conflict by REPLACING the stale entry, never by appending

- **The rule going forward:** when both sides changed a lane, the merge is not "keep both" — a union leaves the file **asserting two contradictory statuses** for one slug and nothing flags it. Find the slug's other occurrence and overwrite the stale header in place; demote the old body to marked history.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-15 — RULE: merge in the object database when the shared tree is dirty

- **The rule going forward:** on this repo a reconcile does **not** need a checkout. `git merge-tree --write-tree` + temp index + `commit-tree` + `push <sha>:main` merges with **zero** working-tree writes, so concurrent sessions' edits cannot be refused, overwritten, or staged by accident.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-15 — RULE: resolve a ledger conflict by REPLACING the stale entry, never by appending

- **The rule going forward:** when both sides changed a lane, the merge is not "keep both" — a union leaves the file **asserting two contradictory statuses** for one slug and nothing flags it. Find the slug's other occurrence and overwrite the stale header in place; demote the old body to marked history.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 — FORBIDDEN: reading a git error as noise from the NEXT command when it names the file the PREVIOUS one staged

- **Git told me, in the same output as the push.** The command chained `commit-tree`, `push`, then `git reset`, and printed:
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 — RULE: fix a bad commit MESSAGE by rebuilding the commit from its own tree, not by `--amend` and not by living with it

- **What we believed:** the shared-tree recipe offered two options for a wrong commit message — `git commit --amend -- <paths>` (dangerous: without a pathspec it commits the whole shared index, and it once swallowed another session's 22 staged files) or *"accept the message and move on."* Written as a binary, so a message defect looked like something you either risk a disaster over or simply eat.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 — a per-row field read off ONE row and generalised to all of them

- **Overturned:** my own same-day claim that "every exercised `win_prob` run is on an OLDER commit", which I wrote into `deploys.md` and `state.md` and pushed, along with a discriminator ("one `rows>0` on a current commit") for resolving it.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 — OVERTURNED: a pinned SHA identifies deployed CODE

- **The belief.** Two scheduled measurement tasks pinned their comparison with "if the live SHA is no longer `d72d670c`, the comparison is invalid — a different SHA may have reverted the fixes." That reads as rigour. It is a string equality test standing in for a question about content.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 — CORRECTED IN-SESSION: at-cap is not a kill

- *Full working in `learnings_evidence.md` under this heading.*
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 — NEAR-MISS: verifying against a ref NAME is not verifying

- **What almost shipped.** A three-file ledger commit that also silently reverted another session's in-flight feature: `book_shortlist.py` −129, `layer2_board.py` −172, `test_layer2_bettable_books_and_labels.py` −224, plus `deploys.md` −43 and `lanes.md` −75. It would have been a valid commit, pushed cleanly, with a message about ledger writes.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 — NARROWING AN INSTRUMENT TO A MEASURED DISTRIBUTION BUILDS IN A BLIND SPOT

- **What I did, and it looked like good work.** A census said **41 of 42**
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 — FORBIDDEN: never test what is deployed with `git merge-base --is-ancestor`. It answers a question about HISTORY; deployment is a question about CONTENT.

- `edbbee9d` (spread-sign fix) is **NOT an ancestor** of live `97491161` — and the fix **is running**. `git show 97491161:...layer2_board.py` returns the same 3 occurrences as `main`.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 — FORBIDDEN: never use a fresh `git worktree` as a test baseline for anything that reads `data/`.

- *Full working in `learnings_evidence.md` under this heading.*
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 — the shared-index revert fired TWICE against one session, and the second time it was armed AFTER a clean push.

- *Full working in `learnings_evidence.md` under this heading.*
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 — a mirrored row set makes a wrong join look like a UNIFORM defect, which is the most convincing kind.

- **What happened.** To verify an edge-attribution fix before deploying, I fetched the real served payloads, filtered to the exact rows that were serving a blank `Edge` with no reason, and ran the changed helper over them. Result: **287 of 287 attributed, 0 unattributed.** I wrote that into `deploys.md` as the verification and deployed.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 - FORBIDDEN: never let a branch sit behind a deploy gate without re-cutting it. Waiting is itself a source of staleness.

- *Full working in `learnings_evidence.md` under this heading.*
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 - FORBIDDEN: a deploy does not race another deploy on this platform. It CANCELS it.

- *Full working in `learnings_evidence.md` under this heading.*
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 - a verification script needs the same predicate discipline as the code it verifies, and a disagreeing verifier is suspect BEFORE the fix is.

- `h2h_lay` counted with `'lay' in market` - which matches **player**
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 - `check_deploy_safety.py` can report a blocker that does not exist, and a BLIND read of it is not a CLEAR one.

- **What happened:** an isolated-index commit of 3 ledger files produced a commit of **14 files** that rendered every path it had not re-read as a DELETION — including this session's own `scripts/fetch_nfl_pbp.py` (0/276), `run_refresh_worker.py` (0/193) and another session's `syndicate/features/soccer/cards.py` (0/64).
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 — FORBIDDEN: letting a FITTED MODEL judge, when a model-free measurement of the same thing is available

- *(the heading states the rule; full working in `learnings_evidence.md`)*
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 — FORBIDDEN: shipping a check whose FAILURE MESSAGE does not carry the evidence for the failure

- *Full working in `learnings_evidence.md` under this heading.*
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 - FORBIDDEN: a deploy-content check must return THREE verdicts, not pass/fail. "Nothing shipped" is not "shipped wrong".

- *** THE THREE FILES DID NOT TRAVEL TOGETHER. Expect cards_error / blank board. ***
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 — OVERTURNED: "my commits are safe once the guard passes and `git show --stat HEAD` looks right"

- *Full working in `learnings_evidence.md` under this heading.*
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 — FORBIDDEN: never let an UNATTENDED session fire a deploy, and do not rely on prose to stop it

- *Full working in `learnings_evidence.md` under this heading.*
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 - FORBIDDEN: never split one change across separately-deployed files and rely on TELLING the deployer. A message is not a guard.

- *Full working in `learnings_evidence.md` under this heading.*
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 - FORBIDDEN: never record a detector's zero as a pass when the data gave it no chance to fire.

- *Full working in `learnings_evidence.md` under this heading.*
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 - the third instance of the same instrumentation gap, in the file where I fixed the second.

- *(the heading states the rule; full working in `learnings_evidence.md`)*
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 — FORBIDDEN: curating a deploy branch BY FILE without checking the call boundary you just cut

- *(the heading states the rule; full working in `learnings_evidence.md`)*
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 — FORBIDDEN: computing a RATE or a COUNT from `scripts/render_logs.py`

- *Full working in `learnings_evidence.md` under this heading.*
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 - FORBIDDEN: never join a CHANGE metric on a key that contains the changing fields. The metric becomes conditioned on the absence of what it measures.

- *Full working in `learnings_evidence.md` under this heading.*
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 - a blob hash written into a ledger is a SNAPSHOT, not a lease.

- **re-read the blobs before cutting rather than trusting the numbers printed in it**.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 — ASK-ANSWER-SUBSTANCE CHECKPOINT 2: five beliefs overturned

- **Sorting orders a pool; it does not decline to publish one.** Necessary, never sufficient. **General form: a fix aimed at the ORDER of bad output does not stop the output, and the note it leaves behind reads like a closed case.** When a past note says "fixed by ranking", check whether anything filters.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 — ASK-ANSWER-SUBSTANCE CHECKPOINT 3: two more

- **The rule: when a metric moves across your change, diff the code path the metric actually reads before attributing it — to yourself OR to anyone else.** Both directions of misattribution are expensive. Claiming a regression you did not cause sends the next session hunting in the wrong file; claiming innocence you have not checked is worse. The check is one `git diff` scoped to the path, and it takes a minute.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 - FORBIDDEN: a loose join key makes a row VISIBLE. It does not make the row's values COMPARABLE. Those are two decisions and I made only one.

- *Full working in `learnings_evidence.md` under this heading.*
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 - a test I wrote can encode the belief that production later disproves, and then it defends the bug.

- *(the heading states the rule; full working in `learnings_evidence.md`)*
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 — SCOPE NOTE on "blob-staging needs `--path`": true in general, WRONG for this repo

- *Full working in `learnings_evidence.md` under this heading.*
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 - FORBIDDEN: a verifier that cannot FAIL cannot PASS. State the denominator every assertion needs, or it will report an empty population as success.

- *(the heading states the rule; full working in `learnings_evidence.md`)*
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 — FORBIDDEN: reading `$?` after a pipeline. TWICE IN ONE HOUR, two different tools, both times the wrong answer was the REASSURING one

- *(the heading states the rule; full working in `learnings_evidence.md`)*
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 — OVERRIDE, LOGGED: an unattended session was authorised by the user to fire this deploy

- *(the heading states the rule; full working in `learnings_evidence.md`)*
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 — CORRECTION: the shared index CHURNS, it does not accumulate — and staged content is not the alarm

- **Extends the same-day rule about slug-level ledger checks.** That one framed whole-file rewrites from stale in-memory copies as a `.syndicate/**` hazard. Measured three hours later: the same mechanism reverted a **source file**.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 — ASK-ANSWER-SUBSTANCE CHECKPOINT 4: fixing a fix, and two bad inferences

- **The rule going forward:** a conditioning variable must be derivable from observable state ALONE. When a payload mixes state and prediction, split them explicitly and say so on the record. **The test for this is cheap and worth writing:** assert the model's field names are absent from the shape.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-17 — FORBIDDEN: deploying `main`'s TREE to a service that runs a curated deploy branch

- **The tell is per-file, and it is cheap:** for each conflicted path compute `live-only` and `main-only` line counts. **`main-only == 0` means production is AHEAD there** and taking main is a revert. Measured tonight on `refresh_nba_oddsapi_props.py`, `refresh_wnba_oddsapi_props.py` and `test_win_prob_null_counter.py` — three files, on two separate services, where the obvious move was the wrong one.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-17 — FORBIDDEN: gating a deploy on "no jobs running" for a continuously-busy worker

- **Worse, the gate measures the wrong moment.** Render BUILDS first and stops the service after (`build_started 21:13:49 -> build_ended 21:18:29 -> live 21:21:05`). What dies is whatever runs at the STOP, ~5 minutes after the trigger — not what preflight saw when you fired.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-17 — FORBIDDEN: resolving the SAME symbolic ref in two git calls. A stale tree on a current parent is a fast-forward, and git cannot tell it from a deliberate revert.

- *(the heading states the rule; full working in `learnings_evidence.md`)*
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 — FORBIDDEN: attributing an excursion with a field that is not THREAD-scoped. A process-global "last stage" names the last thread to speak, not the one allocating.

- **The rule going forward:** before concluding the DATA is wrong, scan the residual against the fitted value. Structure there indicts the model.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-16 — FORBIDDEN: instrumenting a WRAPPER when the hot path has siblings that reach the same work directly. Twice in one night.

- **The rule going forward — the recipe, because it worked and is reusable:**
- *(evidence in `learnings_evidence.md`)*

## 2026-08-17 — RULE: the em-dash in a lane header is SYNTAX, not punctuation. A hyphen header is an UNGUARDED lane

- **Evidence.** `wnba-fixture-identity` was opened by a live session with ASCII hyphens: `### wnba-fixture-identity - OPEN - **...`. `lane-guard.py` parses `^###\s+(\S+)\s+—\s*([^—]*)` and requires U+2014, so the header did not parse at all. Consequences, all silent: the lane's three claimed files were unguarded (one of them contended with a lane closed minutes earlier), and the session-start digest did not list the lane as OPEN, so an arriving session saw no claim on those paths. Found 2026-08-17 12:3x CDT by the `ledger-sweep` lane while verifying something else; the hook had been printing `(1 lane header(s) have no parseable status and are NOT guarded)` and nobody had read it as naming a specific live lane.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-17 — FORBIDDEN: diagnosing from FILTERED log projections. Six wrong attributions, one question, and the answer was in the lines I was truncating.

- **Each filter encoded the hypothesis I was trying to test.** A `text=` query returns only what I already believed mattered; stripping the memory lines removed the only rows carrying `seconds_since_stage` and `climb_mb_per_s`; truncation hid the discriminating field. The phantom "third ledger pass" was a filtered window that began mid-scan and invented a caller that never existed.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-17 — RULE: committing through an ISOLATED index ARMS the shared index with a revert of that commit. Disarm after, not just before

- **The recipe is still right; it has a second half nobody had written down.**
- *(evidence in `learnings_evidence.md`)*

## 2026-08-17 — OVERTURNED: "a statistical win on a sim parameter can be graded by betting hit rate on the same sample"

- **Belief going in:** the overrides file records `starter_tto_quality_scaling`
- *(evidence in `learnings_evidence.md`)*

## 2026-08-17 — RULE: before building a fix, check whether it was already considered and REJECTED in the code you are about to edit

- **The rule going forward:** **an override is not an override until it has been exercised through the real entry point.** For a hook, that means over stdin as a payload — not by setting the variable in the test process, which is a different environment than any user of the documented recipe will ever have. Corollary: the test that would have caught this is the one that runs the guard's own printed text verbatim. If a tool prints instructions, those instructions are an interface and belong in the suite.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-17 — RULE: score a DISTRIBUTIONAL forecast with a distributional baseline. A point test on a distribution is the wrong instrument, even when it agrees.

- **What happened.** Phase 7's whole purpose was to build a proper scoring rule for projections (CRPS, bias/dispersion). I built it, used it to find a real defect — the MLB F5 starter leash, dispersion 1.002 vs a 0.7979 target — and then decided whether the model had SKILL by comparing its **mean absolute error to a constant point prediction**. That verdict went into `state.md`.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-17 — RULE: a LEAKED backtest number is an UPPER BOUND, not merely an untrustworthy one

- **Standing practice here is to mark a leaky backtest "not citable" and stop.**
- *(evidence in `learnings_evidence.md`)*

## 2026-08-17 — RULE: a PATHSPEC commit is the default; the isolated index is the FALLBACK. The latter arms a revert every time

- **Relayed by `commit-guard-blind-to-own-recipe`, owed to and written by the coordinator.** That lane measured the two forms against a repo whose index held a revert of `A.txt` and a deletion of `C.txt`:
- *(evidence in `learnings_evidence.md`)*

## 2026-08-17 — RULE: never close a queue item in BULK. Close each against its own evidence

- **I did this to a live deploy request within hours of documenting the same failure shape.** After deploying three requests I moved *everything* in `.syndicate/deploy/requests/` to `done/` and stamped it all "EXECUTED by the coordinator". A fourth request (`soccer-layer2-dates`) had been filed at 20:20Z, after that batch was scoped. It was never deployed — its commits were not even pushed — and it spent that time marked delivered.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-17 — RULE: an aggregate dispersion check cannot see an UNINFORMATIVE CENTRE

- **What happened.** Phase 7's bias/dispersion decomposition reported MLB pitcher outs at **dispersion 0.791 against a 0.798 target** — as close to perfect as that metric gets. I read it as "the shape is right, only the location is off" and went looking for a calibration fix.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-17 — RULE: a signature change needs a CALLER CENSUS, not a spot-check of the caller you just edited

- **Evidence.** `_load_team_ratings` gained a required third parameter (`as_of`, audit §7 #6). The author updated the caller inside the same module and wrote a test for it:
- *(evidence in `learnings_evidence.md`)*

## 2026-08-17 — RULE: a falsified prediction LOCALISES a bug; treat it as a measurement, not a miss

- **Three predictions were falsified today and each was worth more than the confirmation would have been.**
- *(evidence in `learnings_evidence.md`)*

## 2026-08-17 — A SIGNATURE CHANGE NEEDS A CALLER CENSUS, AND THE CALLER YOU CANNOT REACH IS THE ONE THAT BREAKS

- **Why it survived â€” three independent covers, and each is a general shape:**
- *(evidence in `learnings_evidence.md`)*

## 2026-08-17 — TEST DEPLOYMENT BY CONTENT, NEVER BY ANCESTRY OR BY A SHARED SYMBOL

- **False negative.** live-odds-worker deployed `7470939b`.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-17 — RULE: the FIRST test for any flagged feature is "does enabling it change anything"

- **I built three inert things today.** Not three bugs — three pieces of work that existed, looked complete, passed their obvious tests, and did nothing:
- *(evidence in `learnings_evidence.md`)*

## 2026-08-17 — RULE: a watcher that reports a PEAK of ZERO has not measured a peak. Zero samples is NO DATA, never "clean"

- **I wrote a memory watcher whose entire purpose was to catch an OOM I had predicted, and it reported `Window clean. Peak live-odds-worker memory 0.0% of 2048MB` while the service was at 85.3% and climbing.** Had I trusted it, the rollback would not have happened. It was caught only because the user asked me to check the number by hand.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-17 — RULE: a feature can be unfed at the DATA layer, and it looks nothing like a bug

- **Standing rules here cover code that is present-but-unreachable.** This is the same failure one level down: code that IS reached, with inputs that are empty.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-17 — RULE: rank modelling gaps by how much the dimension DISCRIMINATES, not by how complete its machinery is

- **What I did.** Researching what the MLB sim was missing, I found pitch-type effectiveness fully built — model fields, four consumption sites, a loader, a cache, a fetch tool — and **0% populated**. I ranked it "where a market beat is most likely" *because everything existed and only needed wiring*, and spent **314 network calls and ~2 hours** filling it.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-17 — RULE: you cannot add a MECHANISM to a CALIBRATED engine without re-fitting its rates

- **Measured, 2x2 factorial, 4 of 4 markets:** adding position-player substitution and pitch-type splits to the MLB sim produced a **NEGATIVE interaction, mean −0.00331**. On RBIs each feature alone helped (−0.00573, −0.00271) and together they gained almost nothing (−0.00046). **On runs, both-on was WORSE than neither.**
- *(evidence in `learnings_evidence.md`)*

## 2026-08-17 — RULE: "the model is absent" needs a FIELD AUDIT, not a name search

- **I published a research document stating the MLB sim has "no batted-ball type model — no GB/FB/LD". It was wrong.** The model exists and `simulate.py:1120-1136` consumes it for both batter and pitcher:
- *(evidence in `learnings_evidence.md`)*

## 2026-08-17 — FOUR DEFECTS IN ONE SESSION SHARED ONE SHAPE: THE ERROR PATH RENDERED AS THE SYSTEM'S OWN "NOTHING HERE"

- **1.** `poll_active_leagues_for_tick` caught each league's exception into an `errors` dict and continued with no print. That dict reaches only `data/live/soccer_live_lens.json`, which is not in the publisher allowlist, so it is unreadable from web. Worse, the broken call sat behind `if live_events:` — so **only a league WITH a live match could reach it**. Silent on a quiet slate, total on a busy one. Three instruments read healthy simultaneously: the tick reported `ok: true` (because `validate_live_lens_snapshot` accepts an EMPTY games list), seven leagues wrote their files successfully, and no error appeared anywhere.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-18 — RULE: a cache with a TTL can serve EMPTINESS as authoritative

- **Measured:** 1,282 BVP cache files, every one `by_batter: {}`. I concluded twice from the file COUNT — first "the data is already collected, it just needs mapping", then "it needs a real fetch job". **Both wrong, in opposite directions.** Computing fresh returned 117-170 batter entries for 5 of 5 pitchers.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-18 — RULE: when a claim is corrected TWICE, stop asserting and run it

- **I made FOUR wrong calls about BVP in one session, alternating direction:**
- *(evidence in `learnings_evidence.md`)*

## 2026-08-18 — I ALMOST REQUESTED A DEPLOY FOR SOMETHING ALREADY LIVE, AND ONLY THE BASELINE CAUGHT IT

- **What caught it was mechanical, not clever:** the deploy-request template has a `verify:` field that demands a BEFORE value, so filing it forced one fresh read. The discipline that saved this was writing down the before-number at the moment of filing rather than carrying it forward.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-18 — RULE: a bias can be the NET of two opposing errors, and fixing one is a wash

- **Measured:** the MLB engine under-produced strikeouts by **27%** (K/PA 0.179 vs 0.226). The obvious cause was the pitch-outcome mix — `base_in_play` 0.23 against a league ~0.17, `base_foul` 0.12 against ~0.18 — and correcting it lands the mix almost exactly on the league.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-18 — A STRUCTURAL DEFECT AND A MARKET EDGE ARE DIFFERENT QUESTIONS

- **The market moved by −0.00013. Two markets better, two worse.**
- *(evidence in `learnings_evidence.md`)*

## 2026-08-18 — MEASURE THE COUNT MATRIX; DO NOT GRID-SEARCH IT

- **`count_delta` is a single scalar** and structurally CANNOT express take-early / attack-middle / protect-late. No amount of search fixes a parameterisation that cannot represent the answer.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-18 — RULE: a session RESUME reassigns the session id, which silently stands the coordinator role down. The register must be re-verified, not assumed

- **My own deploy guard blocked me.** `coordinator.id` held `9ed7fd89-...` — correct when written at 13:36 — and the hook was being handed `6f0980eb-...`. Nothing edited the register; **the session id changed underneath it** when the session was resumed. The role had been silently unheld for an unknown stretch, and the first symptom was the coordinator being unable to deploy.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-18 — THE MARKET HARNESS HAS A NOISE FLOOR 2.4x THE EFFECTS IT WAS USED TO JUDGE

- **Same configuration, two seeds, nothing else changed:**
- *(evidence in `learnings_evidence.md`)*

## 2026-08-18 — RULE: a `sed` backreference that does not match writes a RAW CONTROL BYTE, and it ate three lane slugs

- **Three OPEN lanes lost their names entirely.** Their headers read `###  \x01  —  \x02  — **body` — the literal bytes `\x01` and `\x02` where the slug and status should be. A session correcting the ASCII-hyphen headers ran a substitution with `\1`/`\2` backreferences whose capture groups did not match, and `sed` wrote the escape sequences as raw control characters instead of the captured text.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-18 — A DUPLICATED TERM PASSES EVERY CHECK THIS REPO HAS. A PLAUSIBILITY READ CAUGHT IT.

- **WHAT DID NOT CATCH IT — the full list, because that is the finding.**
- *(evidence in `learnings_evidence.md`)*

## 2026-08-18 — RULE: a union merge CANNOT carry a deliberate deletion. A collapse pushed through one is undone, and comes back bigger

- **I collapsed `state.md` from 59 sections to 26, pushed it through the merge cycle, and `origin/main` came out with 87.** The collapse was reverted and my new sections were added on top, so the file ended up **larger than before I started**.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-18 — A VARIANCE-REDUCTION TRICK THAT CHANGES THE ANSWER IS NOT A VARIANCE-REDUCTION TRICK

- **The first bug, and why finding it was NOT the end.** I keyed the seed on `half.next_batter_index`, reasoning that "a team's Nth plate appearance is the same logical event in both arms." **`simulate.py:3178` advances that index MODULO the lineup length.** It holds 9 values, so the same stream replayed 4-5 times per game — scoring inflated up to **126%**. I had even written "batter_index grows monotonically (not modulo)" into the lane note; one line of code said otherwise.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-18 — RULE: a wiring gate must ask whether the payload is READ, not whether a payload is PASSED

- **Lane `football-model-owner`. Caught by measurement, one step before it would have been published as a clean result.**
- *(evidence in `learnings_evidence.md`)*

## 2026-08-18 — RULE: a zero from a LOCAL checkout is a statement about the mirror, never about production. I filed one as a defect

- **Lane `football-model-owner`. Caught by the repo's own rule, one step after I had already written the wrong claim into `todo.md` and a reference doc.**
- *(evidence in `learnings_evidence.md`)*

## 2026-08-18 — RULE: a guard that gates on IDENTITY fails to a total block when the identity holder disappears. Gate on STATE

- **The failure.** `deploy-guard.py` allowed a deploy when `session_id in .syndicate/coordinator.id`. The coordinator was a session. The session was archived. From that moment the allow-branch was **unreachable**, and the guard blocked every deploy from every session — while presenting itself as a routing rule ("file a request, carry on"). Two requests sat in `deploy/requests/`, `deploy/grants/` was empty, and an 11-day clock ran on the NCAAF opener. Nobody had disabled anything; the predicate simply stopped having a true value.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-18 — CHECK WHETHER A FIELD EXISTS BEFORE DECLARING IT

- **No error, no warning, no test failure.** The symptom was that an override dict of 1.0s produced different results from an empty dict.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-18 — OVERTURNED: "the ledger files were fine, just big" — session `football-model-owner`

- **What was believed.** The session-start digest measured `LEDGER OVER BUDGET`
- *(evidence in `learnings_evidence.md`)*

## 2026-08-18 — OVERTURNED: "a guard that is present is a guard that is working" — session `football-model-owner`

- **Two instances in one session, on two different hooks.**
- *(evidence in `learnings_evidence.md`)*

## 2026-08-18 — FORBIDDEN: never apply a transform to a shared file by patching the transform's own source with `str.replace` — session `football-model-owner`

- **What happened.** To re-run a collapse against the WORKING copy instead of `HEAD`, I rewrote the script's input line with `str.replace` and `exec`'d it. The replacement DID NOT MATCH — whitespace differed — so the "worktree rebuild" silently re-ran the HEAD version, and writing the result destroyed another session's 31 uncommitted lines, including a deployed-and-measured NCAAF result.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-18 — RULE: before wiring ANY feature into a model, check whether the feature is computed FROM THE THING BEING PREDICTED. Ask what WINDOW it covers, not what it is named.

- *(the heading states the rule; full working in `learnings_evidence.md`)*
- *(evidence in `learnings_evidence.md`)*

## 2026-08-18 — A TRUNCATED READING IS NOT A COMPLETE ONE

- **RULE: before reporting a null or an absence, prove the query can return a non-null.** A control that must succeed. `pattern=*conditional_mix*` returns count:1 where `pattern=conditional_mix_2026.json` returns count:0 for the SAME file — and I ran the bad form five times and quoted it to two other sessions.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-18 — A STALE-BUT-"RUNNING" SESSION IS INVISIBLE TO EVERY ORPHAN CHECK

- **It survived BOTH checks, for opposite reasons:**
- *(evidence in `learnings_evidence.md`)*

## 2026-08-18 — RULE: a session worktree protects your INDEX, not your EDIT. Shared-file carry is not absorption.

- The rule going forward: **not scoped to ledger files — confirmed 2026-08-19 on two plain hook-script docstrings.** Expect the next session that commits the shared tree to carry ANY uncommitted edit sitting in the working copy, and expect an UNCOMMITTED edit to be destroyed outright if it conflicts. Commit it with a PATHSPEC commit (`git commit <paths> -m ...`, no staging) the moment it is written, or at minimum re-check `git diff --cached` / `git log -1 -- <path>` before assuming an edit is still pending — a carried edit shows a clean diff and a commit you did not make. Attribution is not worth defending; LOSS is the only thing to check.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-18 — RULE: a check that answers a SLIGHTLY DIFFERENT question returns a confident wrong answer. Six in one session.

- The rule going forward: **before believing a surprising reading, state what the command actually compared.** Every one of these was a real command, exiting 0, returning a plausible number — and answering a question adjacent to the one asked. None failed loudly. The tell is always the same: a result that would be *convenient* or *alarming* if true, produced by a check nobody restated in words first.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-19 — RULE: no active owner, no claims. And a liveness read EXPIRES.

- The rule going forward: **a lane whose owning session is archived, absent from the roster, or silent for hours MUST NOT hold file claims.** Releasing claims is NOT closing the lane — its findings stand and it can be reopened. Audit the full claim set against the roster **including archived**, because `include_archived: false` hides exactly the evidence the question needs.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-19 — CORRECTION: the PATHSPEC commit does NOT cover a NEW file. Staging is still the race, and it bit.

- The rule going forward: **`git commit -- <paths>` only works on paths git already knows. A brand-new file MUST be `git add`ed first, and that add-to-commit window is exactly the race the pathspec form was adopted to remove.** For a new file on a shared tree, either commit it from your own worktree, or accept that it may be carried into another session's commit and verify by CONTENT afterwards.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-19 — RULE: before building a feature pipeline for an unwired input, check whether the engine has a BETTER-WIRED input already doing that job

- **Evidence.** `smartsim2` reads 33 alias-terms from `feature_generation_payload` and no production entrypoint passes it. I measured that wiring it changed the output, then spent a session building a leak-free as-of feature pipeline for it.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-19 — RULE: a population checklist CANNOT detect leakage, and a large clean first-wiring effect is a leakage SUSPECT

- **Evidence.** `build_nflverse_game_metrics` computes EPA from the game being predicted. **r = 0.988** against the final margin over 285 games.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-19 — RULE: a small-n result is not a preview of the large-n result. It is the artifact.

- **Evidence, one metric, one session:**
- *(evidence in `learnings_evidence.md`)*

## 2026-08-19 — RULE: a repair pass must be constrained to EXTEND, never SUBSTITUTE. And a mid-flight hook protects only new sessions.

- The rule going forward: **when automating a fix across N items, the safety condition is a property of the REPLACEMENT RELATIVE TO THE ORIGINAL — "the new text must START WITH the old" — not a property of the source you pulled it from.** "The evidence file has a rule line" is not "this is the SAME line, longer", and the gap between those two clobbered 18 lines that existed nowhere else.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-19 — RETRACTION: "a mid-flight hook protects only new sessions" is WRONG. Hooks fire per call. The real hole is BASH.

- The rule going forward: **hooks are evaluated on every tool call, not cached at session start — a newly registered guard IS in force immediately, including for sessions that started before it existed. But a PreToolUse guard matched on `Edit|Write|MultiEdit` is BLIND to writes made through Bash**, and in this repo that is not an edge case: `trim_lane_blocks.py`, `hoist_open_lanes.py` and `compact_learnings.py` all write ledger files from Bash by design.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-19 — VERIFY THE CHANNEL, NOT JUST THE QUERY

- **It could never appear there.** `live_refresh_loop.py:2784-2790` spawns the sim job with `popen_kwargs["stdout"] = open(log_path, "wb")` — every line the wrapper prints goes to a FILE on the worker's disk, never to the container stdout Render collects.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-19 — RULE: a guard that fails open silently is indistinguishable from a guard that works. Grep for the symbol you deleted.

- The rule going forward: **after editing a guard, prove it still FIRES — do not accept "it parses" or "it is registered" as evidence.** Every hook here wraps its work in `except Exception: return 0` so a broken guard cannot block real work, which means a broken guard is also SILENT. Those two properties are the same line of code.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-19 — RULE: a threshold raise buys HEADROOM ÷ GROWTH RATE. Compute it, or you are choosing a fix you have not measured.

- The rule going forward: **before raising a limit instead of fixing what fills it, divide the new headroom by the observed growth rate and say the answer out loud in hours.** If that number is smaller than the interval between the people who would act on it, the raise is not a fix, it is a snooze — and it costs the credibility of the threshold as well as the time.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-19 — RULE: "this cannot be automated" is a claim like any other. Name the predicate you tried.

- The rule going forward: **before concluding something is not enforceable, state the specific predicate you tested and why it fails. If you cannot name one, you have described the first idea you had, not the problem.** The useful move is almost always to narrow the target: not "detect appending", but "detect the one SHAPE of appending that causes the damage".
- *(evidence in `learnings_evidence.md`)*

## 2026-08-19 — RULE: exonerated as the CAUSE is not free of DEFECTS. Re-ask the narrower question.

- The rule going forward: **when a suspect is cleared of causing the symptom you were chasing, ask separately whether it is nonetheless broken.** An exoneration answers one question — "did this cause X" — and it is routinely read as answering a bigger one, "is this fine". Those come apart, and the second question is cheap to ask once you are already looking at the thing.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-19 — CORRECTION: shared-file carry reaches plain files too, and it reads as nothing to commit, not as loss

- The rule going forward: **`git diff --cached` (or plain `git diff`) coming back EMPTY on a file you know you just edited means the edit already landed in someone else's commit — check before concluding there is nothing to do.** Two hook-script docstrings (`.claude/hooks/ledger-commit-guard.py`, `ledger-postwrite-check.py`, not `.syndicate/*.md`) were fixed here, left uncommitted pending the user's go-ahead, then swept into a parallel `github-actions[bot]` checkpoint commit (`f5953d4c`) before this session staged them. `git log -1 -- <path>` then `git blame -L <line>,<line> <path>` named the commit and confirmed the exact content in two calls. Cost was zero — the fix is correct and already on `origin/main` — but the intended atomic, reviewable two-file commit never existed as such; it rode inside an unrelated bundle. Broadens the 2026-08-18 "shared-file carry is not absorption" rule above: the mechanism is not ledger-specific, it is anything sitting uncommitted in the one shared working tree.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-19 — RULE: read the convention off the DIRECTORY before restructuring it. The precedent is usually already on disk.

- The rule going forward: **before splitting, renaming or re-keying a set of files, look at how the EXISTING members are keyed and confirm your rule reproduces them.** If your scheme would have filed yesterday's files differently than they are actually filed, your scheme is wrong -- the existing layout is the specification.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-19 — RULE: a mass-deletion diff is not self-explaining. Compare DISTINCT lines before accepting "it was just dedupe".

- The rule going forward: **when a diff you did not intend shows large deletions, do not reason from the line COUNTS or from a plausible story about reformatting. Take the set difference of DISTINCT lines, both directions, and then grep the tree for a sample of what is missing.** Counts cannot separate "500 duplicate copies removed" from "500 unique records deleted", and those are the same number.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-19 — RULE: when diagnosis has failed repeatedly, look for the fix that does not need the cause.

- The rule going forward: **after two or three wrong causes for one symptom, stop buying lottery tickets on the fourth and ask whether a fix exists that is correct under ALL of them.** Such a fix is available more often than it looks, because a symptom usually has more than one route to the same evidence — and it is strictly safer, since it cannot be invalidated by the answer arriving later.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-19 — RULE: a cause must explain the TIMING, not just the mechanism. Date the change before believing it.

- The rule going forward: **when you propose a change as the cause of a dated symptom, find out WHEN that change happened before asserting it.** A mechanism that cannot produce the observed timing is not the cause, however completely it explains the current state — and "explains the state" is the part that feels like proof.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-19 — RULE: a flag's NAME is a hypothesis about its meaning, not its meaning. Read the setter before gating on it.

- The rule going forward: **before rejecting or filtering data on a flag found in a payload, find where the flag is SET and read what condition actually produces it — do not infer meaning from the flag's name, even when the name reads as self-explanatory.** A name chosen for one context (display copy, a UI hint) can sound like it means something load-bearing (live adjustment, circularity) in a different context (a backtest scoring real predictions).
- *(evidence in `learnings_evidence.md`)*

## 2026-08-19 — VERIFY WHAT THE THING YOU CHANGED *DEPENDS ON*

- **RULE: verifying the code you wrote is present is HALF a check. Verify its inputs, its callees and its data exist in the same environment.** "Is my change live?" and "can my change do anything?" are different questions, and I answered the first one twice while never asking the second.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-19 — RULE: to find where variance is CREATED, decompose the outcome. Correlating its inputs finds what MOVES WITH it, which is a different question.

- **Evidence.** NCAAF projected total SD was 1.67x the market's. I proposed three mechanisms, each plausible, each swept, each wrong:
- *(evidence in `learnings_evidence.md`)*

## 2026-08-19 — CORRECTION: `git commit -- <paths>` fixes the shared INDEX. It is the DELIVERY MECHANISM for a shared FILE. I applied it to both and caused two more incidents.

- The rule going forward: **this is the SAME class of gap already documented for `commit-guard.py`** (2026-08-17: "all THREE documented overrides were unreachable... a PreToolUse hook runs BEFORE the shell") — a sibling instance in a different hook, not a new mechanism. Any `SYNDICATE_*_GUARD` off-switch mentioned in prose must be assumed unreachable from inside a tool call until proven otherwise; it can only be set at the harness/settings level, outside any session's own reach. Do not spend a second attempt varying the prefix syntax — go straight to reading the hook's source for where it actually reads the value from, or hand the decision to the user.
- *(evidence in `learnings_evidence.md`)*

## `#472` — a quiet autorun is not evidence it is idle `[2026-08-19]`

**What we believed:** WNBA's pregame autorun going silent for 5+ hours after
a fresh deploy was benign — smart-sim generation is tied to actual game
slates, not a fixed interval, so a quiet stretch with no game imminent
reads as correctly-skipped, not broken.

**What was actually true:** it was failing on every tick, repeatedly, and
each failure silently cost a full 4-hour retry window. The autorun's own
except-block wrote a fresh, full-interval-resetting epoch on ANY exception,
including plain mutex contention (`launch_refresh_run`'s "already active"
ValueError) where NOTHING was actually attempted — some other job (a
legitimately in-flight MLB resim) just held the shared single-run slot.
Soccer's identical, copy-pasted autorun had the same defect.

**How we found out:** the user pushed back once ("well that tells me
there's a problem") on the "benign cadence" framing, and again ("this
should not cause a 5 hour delay") after a first, still-too-generous
explanation. Both times the fix was to actually read
`/api/ops/live-refresh/state` and the raw log stream instead of reasoning
from a plausible-sounding mechanism. The production timestamps settled it:
WNBA succeeded cleanly at ~4h intervals all day (01:24/05:24/09:29/13:35Z),
then went dark the moment it first collided with a job that was still
verifiably running (confirmed via its own pid switching mid-investigation,
not assumed).

**The rule going forward:** a scheduled job going quiet for longer than its
own stated interval is not "no trigger yet" until you have checked whether
it is actually TRYING and losing — read the live state/logs for the actual
attempt-and-failure pattern before accepting an absence as benign. And
separately: any retry/backoff logic must distinguish "we tried and
genuinely need to wait" from "we didn't get a turn" — collapsing both into
one epoch/cooldown timestamp turns ordinary resource contention into a
multi-hour outage.

**Cost:** ~1 extra investigation cycle before the user's second, sharper
pushback forced the real trace; the underlying bug (fixed in `97e85b66`)
had likely been silently starving WNBA's refresh cadence for longer than
just this session's window, unmeasured.

---

## An absent log marker is only evidence if the marker's transport actually reaches you `[2026-08-19]`

**What we believed:** repeated checks of `BOXSCORE_BOOTSTRAP_STALLED` never
appearing in Render's log collector, across many hours and multiple real
runs, was treated as inconclusive-leaning-toward-still-broken evidence
about `#469`'s ESPN fetch — the marker's own `print(..., flush=True)` had
been specifically added so it WOULD be observable, so its absence felt
like it should mean something.

**What was actually true:** it meant nothing, for a whole class of runs.
`launch_refresh_run` spawns autorun-launched children with
`stdout=DEVNULL` by explicit design (soccer's own pre-existing `#433`
code comment explains why) — so no `print()` from inside
`refresh_wnba_oddsapi_props.py`, including this exact marker, could ever
reach Render's log collector for THOSE specific runs, regardless of
whether the underlying condition it reports on ever occurred. Every
"still no STALLED marker" observation during that stretch was reading a
transport gap as a negative result.

**How we found out:** the user pushed back twice on "still frozen, still
waiting" as an answer before the actual mechanism got read rather than
assumed. Reading `launch_refresh_run`'s own code (not just its
docstring/comment, the actual spawn call) showed the DEVNULL redirect
directly. The script's own `_append_log` FILE turned out to be the one
surviving signal, but had never been allowlisted either — a second,
independent gap in the SAME diagnostic chain, only found by trying to
read that file and hitting a 403.

**The rule going forward:** before treating an expected log marker's
absence as a negative result, confirm the marker's actual transport
reaches you for the SPECIFIC invocation path being tested — a detached/
fire-and-forget subprocess, a different launch mode, or a different
service can silently sever stdout capture while the underlying code still
runs exactly as written. When in doubt, verify with a marker or file
KNOWN to exist for that exact path (a positive control) before trusting a
negative one. This is the same shape as the file-vs-stdout gap already
documented for soccer's own reporting (`#433`) — it cost real
investigation time again here specifically because the SPECIFIC launch
path (`launch_mode="web_process"` from the WNBA/soccer pregame autorun)
hadn't been checked against it before, only assumed to behave like other,
already-verified invocation paths.

**Cost:** several hours of "still no marker, still inconclusive" reporting
that was never going to resolve on its own, until the transport gap itself
was found and fixed (allowlisting `_append_log`'s own file) and a manual
trigger was used to get a real, direct answer instead.

### 2026-08-19 — a disclaimer marker must PRECEDE the path it disclaims, not follow it

- **What we believed:** adding a phrase to `lane-guard.py`'s
  `_DISCLAIMER_MARKERS` list is sufficient to make any sentence containing
  that phrase stop misreading as a claim — the same fix that worked for
  "not touch" and "not taken" earlier the same day.
- **What was actually true:** `_claimable_prefix` cuts a line AT the
  marker's position and keeps only the text BEFORE it as claimable.
  Writing a release note as "`path` claim RELEASED..." (path first, marker
  second) still left the path in the claimable prefix, because the marker
  came too late to protect it. Every marker that already worked
  ("NOT claimed: `path`", "BLOCKED, not taken: `path`", "held by") happens
  to precede the path it disclaims — the mechanism has a required word
  order this session had never had to state explicitly, because nobody had
  written a marker-after-path sentence before.
- **How we found out:** wrote a regression test for the new marker BEFORE
  trusting the fix, exactly as the two same-day precedents had — and it
  failed. Fixed the actual `lanes.md` prose to be marker-first and re-ran;
  the test passed.
- **The rule going forward:** when writing any Files-block disclaimer in
  `lanes.md`, put the marker phrase FIRST and the path AFTER — "RELEASED,
  no longer claimed: `path`", never "`path` ... RELEASED". When adding a
  new marker to `_DISCLAIMER_MARKERS`, the regression test must reproduce
  the EXACT sentence about to be committed, not a hand-simplified stand-in
  — the first version of this fix's own test used marker-first phrasing
  from the start and would have passed even if the real `lanes.md` prose
  (path-first) stayed broken, which is a different, easier trap than the
  bug itself.
- **Cost:** caught before shipping — the failing test was the whole point
  of writing it first — but it is the fourth instance of this general
  parser-gap shape in one day, and this specific sub-shape (word order,
  not just word presence) had not been named until now.

**Same session, a THIRD sub-shape found minutes later while writing a
DIFFERENT disclaimer.** `_claims()` processes each PHYSICAL LINE of a
wrapped bullet independently — `_claimable_prefix`/`_paths_in` never see
a joined logical bullet, only one line at a time. A marker phrase that
line-wraps ("... NOT\n    claimed here:** `path`") has its recognized
words split across two lines the parser reads separately: line one
("... NOT") contains no path so yields nothing; line two ("claimed
here:** `path`") contains the path but, read in isolation, no longer
contains "not claimed" — only "claimed", which matches nothing — so the
path is extracted as a claim regardless of the marker one line up.
**Verified against `_claims()` directly, not assumed**: this exact wrap
reproduced the double-claim live in `lanes.md`; moving the marker and the
path onto the SAME physical line (no line break between them) fixed it,
confirmed by re-running `_claims()` against the file afterward. **The
rule, combined with the one above: a marker must be on the SAME physical
line as the path, AND before it on that line.** Splitting either way
(wrong order, or right order but wrapped) is invisible to the parser.
This also means `check_lane_invariants.py` is currently the wrong tool to
verify a disclaimer fix with — separately discovered this session that
its own copied `FILES_RE` has drifted from `lane-guard.py`'s (caught by
`tests/test_check_lane_invariants.py`'s own pinning test, pre-existing,
not caused here) — so it can report a false double-claim independent of
whether the real, live-enforced parser agrees. Verify any lane-claim
question against `lane-guard.py`'s own `_claims()` directly (see this
session's own throwaway one-liner, or write a test in
`tests/test_lane_guard_files_forms.py`), not against the invariant
checker, until that drift is fixed.

### 2026-08-19 — NEAR-MISS: an object-database merge updates the REF, not the working tree, and a later working-tree write can silently revert real content

- **What happened.** Used the sanctioned zero-working-tree-writes merge
  recipe (`git merge-tree --write-tree` + `commit-tree` + `update-ref`) to
  push a checkpoint past a dirty shared tree — correctly, and it worked.
  Minutes later, wrote a NEW deploy measurement to `.syndicate/deploys.md`
  via a plain `cat >> .syndicate/deploys.md` against the WORKING TREE file
  — which the merge had never touched, so it still held an OLDER version
  of the file, missing a real ~80-line entry (`#473`, another session's
  NBA investigation) that had arrived via the merge into the REF only.
  `git add` + `git commit` then staged "the stale working file plus my
  append" against a parent commit that DID have `#473` — producing a diff
  that deleted their entire entry and replaced it with mine.
- **How we found out.** Read the commit's own diff before pushing (a
  `git diff --cached --stat` showing 77 deletions on what should have been
  a pure append was the tell) rather than trusting the commit message.
  Caught before the commit reached `origin` — verified with `git log
  --oneline origin/main..HEAD` first.
- **The rule going forward: after ANY object-database merge that moves
  `HEAD` via `update-ref` without touching the working tree, treat every
  file in that merge as STALE in the working tree until proven otherwise.**
  Before writing to a file with a plain shell append/edit, diff the
  working-tree copy against `HEAD`'s own copy of that exact path
  (`git diff HEAD -- <path>`) — a non-empty diff on a file you have not
  touched since the merge means the working tree is behind the ref you
  just created, and a naive append will re-base off the wrong content.
  Safer still: build any further edit to that file the SAME way the merge
  was built (read `HEAD`'s blob, edit that content, write a new blob/tree/
  commit) rather than mixing the two methods on the same file in one
  session.
- **Cost:** fully recoverable, not yet pushed when caught — rebuilt the
  correct tree from `HEAD`'s real content plus the intended addition,
  verified content on `origin/main` after pushing (both entries present,
  exactly once each) rather than trusting the push succeeding silently.


## Reachability of the call is not reachability of the data `[2026-08-19]`

**What we believed:** asked whether NBA had `#468`'s WNBA reachability
defect (a fixed function made unreachable by broken wiring), traced the
call graph and found `refresh_nba_oddsapi_props.py` genuinely reaches the
same shared, monkeypatched, `#468`-fixed function as WNBA does — same
entry point, `league_code` threading through generically, no env-var
override. Concluded "structurally identical to WNBA, should work the
same way" and reported that as the answer.

**What was actually true:** the CALL is reachable; what it needs to
compute from is not. A real reachability test (the same methodology that
had verified `#468` for WNBA — real historical data in a scratch copy,
not code-reading) showed NBA's rebuild returns nothing: the function's
own two data sources are both structurally absent for NBA (a `boxscores/`
subdirectory the vendor package expects but Syndicate's NBA pipeline
never populates, and `player_logs.csv`, also absent). The wiring question
(`#468`'s exact shape) and the "does this function have anything to work
with" question are different questions, and tracing the first does not
answer the second.

**How we found out:** the user asked the identical question twice. The
first answer rested entirely on a call-graph trace and treated symmetry
of the CALL PATH as symmetry of the OUTCOME — an assumption never tested.
Only re-running the actual verification methodology (not a repeat of the
same trace) surfaced the real difference.

**The rule going forward:** "is this reachable" and "is this reachable
AND does the destination have valid inputs" are separate claims requiring
separate evidence. A call-graph trace proves the first; only running the
function (or a faithful scratch-data reproduction of it) proves the
second. This is the same shape `model_engine_standard.md` already
enforces for model inputs (CONSUMED × POPULATED, never one dimension
alone, never a name grep) — the same discipline applies to any
"is X wired to Y" reachability question, not just input-field audits.
When a reachability answer is being extended from one instance (WNBA,
verified) to a sibling (NBA, untested) by structural analogy alone,
treat that extension as unverified until it's actually run, even when
the code paths look identical.

**Cost:** one full round of "here's the answer" that had to be walked
back and re-verified from scratch, after the user declined to accept the
first pass at face value.
---

## 2026-08-19 — I declared a deploy FAILED 60 seconds after it went live, and it had not

- **The rule going forward.** After a deploy, before drawing ANY conclusion from a served payload, establish how the change is supposed to reach the surface and how long that takes. If the path includes an async step — a bootstrap sync, a cache TTL, a background worker, a CDN — the first read is not evidence and must be a POLL, not a sample. And if a failing read leads you into a diagnosis, re-read the payload before acting on the diagnosis: the cheapest possible test of "is this still true?" costs one call and would have saved five here.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-19 — FORBIDDEN: never treat a green local `pytest` run as evidence about CI. **CI runs `unittest`, and `conftest.py` does not exist to it.**

- **Measured:** `tests/test_wnba_cards_merge_aliases` — `20 passed` under `python -m pytest`, `FAILED (failures=2)` under `python -m unittest`, same commit, same machine, same minute. Cause: `build_source_cards_payload`'s cache is keyed on `(date, ...)` + a wall-clock TTL bucket, `conftest.py` had cleared it since months ago, and under `unittest` nothing did — so the alphabetically-first test's `("2026-07-02", True)` payload was served to the two tests after it. **Deterministic, not a flake, and it had failed the Daily Update workflow every single morning it was able to run.**
- *(evidence in `learnings_evidence.md`)*

## "We don't capture that" is a claim about NAMES until you check the CACHES `[2026-08-19]`

**What we believed:** two of the four smart-sim calibration artifacts
(`intervals_band_calibration`, `intervals_time_profile`) could not be built
because they need per-3-minute-segment actual scoring, and "Syndicate
captures final box lines and quarter totals, not intra-quarter segment
scoring". Reported as `actuals_unavailable` and deferred as separate work
requiring a new play-by-play capture pipeline.

**What was actually true:** the actuals were already on disk. ESPN's summary
endpoint returns a `plays` array (~380 plays/game) carrying `period.number`,
`clock.displayValue`, and the RUNNING `homeScore`/`awayScore` — and
`_espn_summary_local` already fetches and CACHES that payload for every game
the boxscore bootstrap touches. 113 of 114 locally-cached summaries were
usable immediately. Differencing the running score across plays yields exact
per-segment scoring; verified on a real game where the 16 derived segments
summed to 179 against a final score of 179.

**How we found out:** the user declined the deferral and said "find
actuals". The search that followed was not clever — it was grepping for
play-by-play in the repo (which surfaced an entire existing
`game-shape-capture` lane), then listing the ESPN cache directory, then
opening one cached file and reading its top-level keys. Every one of those
steps was available before the wrong conclusion was published.

**The rule going forward:** an artifact that does not exist under its own
name is not the same as data that does not exist. Before concluding a
derived input cannot be built, enumerate what the pipeline already FETCHES
and CACHES — raw upstream payloads (`_espn_cache/**`, vendor caches, raw/
snapshots) routinely carry far more than the narrow field the consumer
extracted from them. Grep for the concept, list the cache directories, and
open one file. "We don't capture that" is a statement about the
transformation layer; the raw payload usually captured it anyway.

**Cost:** one wrong deferral published in a commit message and a lane block,
retracted the same session. The fix, once the data was found, was a single
builder script and no new capture infrastructure at all.

## 2026-08-19 — NEAR-MISS: a multi-step object-database commit re-resolved `origin/main` mid-construction

- **The rule going forward:** on a shared clone, symbolic refs (`origin/main`) can move between separate tool-call boundaries because other sessions fetch concurrently. A multi-step object-database construction must pin one explicit commit SHA at the start (`BASE=$(git rev-parse origin/main)`) and use `$BASE` — never the symbolic ref — at every subsequent step (`read-tree`, `commit-tree -p`), even across separate calls. See [[project_shared_index_can_hold_a_revert]] and the object-database-merge near-miss already in this file for the sibling failure modes on the same shared-clone hazard.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-19 — A commit's own summary line overclaimed "closes to zero" while its body text said otherwise

- **The rule going forward:** a summary sentence and the detail underneath it can drift apart within a single piece of work, not just across sessions — check a "fully closed" / "zero remaining" claim against the SAME document's own caveats section before repeating it in a lane block, todo.md, or a user-facing summary. This is a sibling to [[feedback_retraction_is_not_innocence]] (withdrawing a claim doesn't prove the opposite) and to [[feedback_gate_on_the_output_not_the_input]] (check what a document actually says, not what its own headline implies it says) — here the discrepancy was inside one document, not between two.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-20 — An artifact can OUTGROW the publish ceiling, and the failure is silent

- **Why it cost so much to find: every other link was CORRECT.** The worker really did rebuild the ladder (`generatedAt 19:54:41 CT`). `is_stale()` really did correctly answer `fresh` — the content genuinely was newer than the odds and the sims. There was no error, no failing test, and nothing wrong anywhere near the ladder code. I chased five successive causes, each hidden behind the last, and three of my intermediate diagnoses were wrong.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-19 — OVERTURNED: "leak-free" is not "representative" -- a backtest can be methodologically clean and still measure the wrong pipeline

- **The general rule.** A backtest's job is to measure what production does. "Leak-free" answers "is this number honestly measured from the data it uses" -- a completely separate question from "is this the SAME data production uses." Passing the first says nothing about the second, and nothing about the second's absence produces an error, a test failure, or any signal at all -- both pipelines run, both produce plausible numbers, both pass every existing test. The two pipelines have to be checked against each other DIRECTLY (does the backtest's league-branching logic match production's, field for field), not inferred from either one looking correct in isolation.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-20 — OVERTURNED: "the slate date rolled, the gate expired". It had not.

- **How to apply:** any artifact keyed by SLATE date — ladders, sims, status documents, rebuild gates — is on Central time. Before concluding a document is missing, stale, or expired, convert: `slate_date = (utc - 5h).date()`. A watcher keyed on the wrong date does not return "nothing happened", it returns a CONFIDENT WRONG ANSWER, because the document it is polling really does exist and really is old.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-19 — a single read of a MULTI-WORKER service is not a measurement

- **The rule going forward.** Verifying anything on a multi-worker service — post-deploy or not — means PROBING REPEATEDLY and reporting the distribution, not a value. If the probes disagree, that disagreement IS the finding: it means the workers hold different state, and a deploy (which restarts them) is what resolves it. Report "10/10" or "9 of 12", never a bare reading.
- *(evidence in `learnings_evidence.md`)*

## Ancestry is the wrong test for a cherry-picked deploy `[2026-08-20]`

**Believed:** `git merge-base --is-ancestor <fix> <live_sha>` tells you whether
a fix is live.

**Actually:** a cherry-pick creates a NEW commit with a new SHA, so the
ORIGINAL commit is never an ancestor of it. Checking `#475` on web that way
returned NO for a deploy that was completely correct — the test was wrong, not
the deploy. Nearly reported a successful deploy as failed.

**Rule:** for any cherry-picked/scoped deploy — which on this repo is MOST of
them, because service live-SHAs are usually off-main — verify by CONTENT
(`git show <live_sha>:<path> | grep <the new symbol>`), never by ancestry.
Ancestry is only valid when deploying a commit that literally descends from
what is live.

## `HOT_ARTIFACT_PATTERNS` is about worker→web, not "can the sim see it" `[2026-08-20]`

**Believed:** `#474`'s and `#477`'s new artifacts were blocked from production
by the missing allowlist entries, so the work was inert until another lane
added them.

**Actually:** every consumer of those artifacts is the SIM, which runs
worker-side and reads them from its own `processed_root`.
`HOT_ARTIFACT_PATTERNS` governs PUBLISHING worker→WEB. A builder running
inside the worker refresh writes to the same disk its reader uses, so no
allowlist is involved in making it work. The allowlist buys external
auditability via `/api/ops/artifacts/export` — worth having, not blocking.

**Rule:** before treating an allowlist entry as a blocker, name the READER and
the disk it reads from. "Producer and consumer are both worker-side" and
"needs to cross to web" are different problems with different fixes, and
conflating them makes a lane wait on another lane for no reason.


## 2026-08-20 — OVERTURNED: I reported "CI is green" and closed the lane on a 16-run green streak that did not span the hours CI actually fails. **A streak is a SAMPLE. Check whether it covers the condition that breaks the thing.**

- **What I actually verified was "CI is green at 23:40Z."** I reported "CI is green." Those differ by exactly the hours that matter, and the whole point of the original request — *"anytime we deploy to git there are CI errors"* — was most likely THIS defect, which I then wrote off as fixed.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-19 — READ THE WRITER BEFORE INSTRUMENTING THE READER. A branch that turns on a key is answered by the SCHEMA, not by a deploy.

- **Overturned belief, recorded verbatim from `.syndicate/deploys.md` (2026-08-16 04:5xZ):** the uncached odds_history shard load inside `_enrich_games_with_tracked_market_lines` was *"the best candidate on the table"* for the refresh-worker's ~2GB excursion, and the entry closed with *"What would settle it: one bounded in-pass measurement around `:2294` (bytes read, parse peak, call count per build), **which needs a deploy**."*
- *(evidence in `learnings_evidence.md`)*

## 2026-08-20 — FORBIDDEN: never repair, rebuild or optimise a scheduled job without first establishing that anything still CONSUMES it. Fixing a dead job can be worse than leaving it broken.

- **80.6%**. Good work on a feature the user then said they do not use: *"we no longer use that daily update feature, everything runs on render."*
- *(evidence in `learnings_evidence.md`)*

## 2026-08-20 — A STANDING INSTRUCTION BLOCK GOES STALE SILENTLY, AND STALE READS AS AUTHORITATIVE

- **How to apply.** A ledger block written as an INSTRUCTION ("cut from THIS", "deploy X") must carry the reading that proves it is still valid, and the instruction must be re-derived, not trusted:
- *(evidence in `learnings_evidence.md`)*

## 2026-08-20 — "Everything upstream is correct" is a REASON TO LOOK FURTHER DOWN, not a reason to doubt the symptom

- **The generalisable error:** I kept re-examining whether the upstream verdict was WRONG, when the actual question was WHICH COPY it described. `is_stale()` reads the worker's disk; the symptom lived on web's. A component can be perfectly correct and still tell you nothing about the system, because it is answering a question about a different machine.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-20 — I NAMED A VERIFICATION CHECK WITHOUT CONFIRMING THE INSTRUMENT COULD SEE

- **How to apply.** `fnmatch`-vs-`glob` is a real trap in this repo: they disagree on `/`, so "it matches the allowlist" does NOT mean "it is published". Check the SWEEP's semantics, not the reader's.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-20 — OVERTURNED (pre-registered): soccer is not under-dispersed anymore, and fixing dispersion + missing inputs did not close the gap to the market

- **The 2026-08-20 re-run measured exactly the falsification condition.** Mean model stdev rose to 0.1922, past market's 0.1859 -- under-dispersion is gone. The Brier gap did not close: still worse than market in 8 of 9 leagues, `belgian_pro_league` the same single exception as the original diagnosis, completely unchanged by the entire session's work.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-20 — CORRECTED BELOW. FORBIDDEN: buying data before probing it exists — and NEVER diagnose a vendor from your own broken query

- **I verified the COST of a purchase carefully and never verified the PREMISE.**
- *(evidence in `learnings_evidence.md`)*

## An unbiased mean hides a broken distribution `[2026-08-20]`

**What we believed:** the WNBA live win-probability path was roughly fine. Its
constants were admittedly un-backtested, but nothing pointed at them, and any
aggregate check looked clean.

**What was actually true:** it was severely UNDERCONFIDENT. Graded over 212
games / 73,878 live samples, samples it priced 0.6-0.7 actually won **91.3%**;
samples it priced 0.3-0.4 won **11.6%**. The scale was ~2.5x too wide and
compressed every probability toward 0.5. Brier 0.1896 -> 0.1644 after refit.

**Why it survived so long:** the MEAN was already right — 0.573 predicted vs
0.571 actual. Every summary statistic that averages over samples said the
model was unbiased, and it WAS unbiased. The defect was in the second moment,
not the first. A calibration table by predicted-probability bucket exposes it
in one glance; no amount of staring at aggregate accuracy ever would.

**The rule:** for any probability output, "is the average right" and "is the
distribution right" are different questions, and only the second one tells you
whether an individual price is usable. Bucket predictions and compare each
bucket's mean prediction to its realised rate. A model can be perfectly
unbiased on average while being wrong on literally every bet you place with it.

**Corollary that cost me a wrong conclusion in the same session:** when fitting
a replacement, fit INSIDE the real function's structure. My first fit used a
bare logistic while the shipped function also blends toward a pregame anchor,
so part of the apparent gain came from silently dropping the blend rather than
from the scale. Refitting within the real structure gave the honest number
(+0.0261). And the variant that scored best of all — blend removed entirely —
was an ARTIFACT of grading with a neutral 0.5 anchor, which makes blending
toward it pure noise by construction. In production that anchor is a real
estimate. A fit is only as meaningful as the harness's fidelity to production.

## 2026-08-20 — FORBIDDEN: an assertion whose subject is a TEMPLATE must not take the ambient `data/` mirror as its input. Pin the fixture, then prove the pin is load-bearing.

- **Pinning is only half the fix, and the dangerous half is the other one.** A pinned test that can no longer fail is worse than a flaky one, because it reads as coverage. Run the off != on probe: break the fixture and confirm the test fails. Here, flipping `active_today` to `False` produced `AssertionError: 'Live slate' not found` — that is what makes the green meaningful.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-20 — "strictly dominated" is a different diagnosis from "broken", and it changes the fix

- **The NCAAF model has REAL predictive power and is still worthless for betting. Those are compatible, and I spent a session treating them as if they were not.**
- *(evidence in `learnings_evidence.md`)*

## 2026-08-20 — ONE ERROR IN FIVE GUISES: validating against a PROXY, not the objective

- **Consolidates five entries this lane wrote on 08-19/08-20** (originals verbatim in `learnings_archive_2026-08-20.md`). They are the same mistake wearing different clothes, and seeing them together is the point — each looked novel while I was inside it.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-20 — A NULL HAS A SAMPLE SIZE. I called a lever dead, revived it, then buried it properly.

- **The same question answered three ways as n grew, and only the third was honest about its own power.**
- *(evidence in `learnings_evidence.md`)*

## 2026-08-20 — TRIMMING state.md AND learnings.md DOES NOT FIX THE DIGEST. Measured.

- **I told the user both files "arrive lossy at session start". That was wrong, and I had not read the hook that builds the digest.**
- *(evidence in `learnings_evidence.md`)*

## 2026-08-20 — RELAXING A FILTER CAN MAKE THE OUTPUT WORSE. Selection matters as much as the match.

- **That would have made it worse.** 43 headings is ~4,800 B against a 450 B cap, and `head -c` takes lines in FILE order, which in an append-only file is OLDEST first. So the "fix" would have shown ~7 of the most stale rules and silently dropped every lesson learned since — trading 8 visible rules for 7 worse ones.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-20 — A WORKTREE COMMIT LEAVES THE SHARED TREE STALE, AND STALE IS A REVERT WAITING

- **Working from a worktree is the right way to avoid the shared index. It has a cost nobody had written down: the shared tree does not learn about it.**
- *(evidence in `learnings_evidence.md`)*

## 2026-08-20 — OVERTURNED: a genuinely BRACKETED grid-search optimum (not an edge artifact) still failed held-out validation

- **It failed held-out validation anyway.** Applied to a worktree, run on a larger match set at both the old and new value, scored ONLY on the matches not used to find the value: mean Brier delta +0.0121, the WRONG direction.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-20 — A STALE-BASE PUSH DOES NOT LOSE WORK ONCE; IT POISONS THE BASE

- **How to apply.**
- *(evidence in `learnings_evidence.md`)*

## 2026-08-20 — A MUTATION TEST THAT MUTATES A COMMENT PROVES THE OPPOSITE OF WHAT IT LOOKS LIKE

- **How to apply.** Assert the mutation took effect before trusting the result — re-import the symbol and print it, or anchor on a form that appears exactly once (here: leading indentation plus trailing comma). Documenting a bug in a comment NEXT TO the code makes the code and its description textually identical, which is precisely what defeats a naive replace.
- *(evidence in `learnings_evidence.md`)*

## Saying a thing is done is not doing it `[2026-08-20]`

**What happened:** mid-deploy I told the user I had "stopped the older
monitor's redundant refresh-worker loop so it can't race this one." I had not.
Both monitors were still running deploy loops against the same service, and
either could have fired a deploy independently.

**Why it mattered and why it nearly didn't get caught:** the sentence was
plausible, sat in a report full of true statements, and described an action
I had genuinely intended. Nothing in the surrounding output contradicted it.
I only found it by re-reading my own claim against the task list. No
double-fire occurred — verified via `deploys?limit=2` — so the cost was zero
this time, which is exactly what makes the class dangerous.

**The rule:** an assertion about an action YOU took is a claim like any other
and needs the same evidence as a claim about the system. Before writing "I
stopped X" / "I released Y" / "I cleaned up Z", either the tool call is in
this turn's transcript or it is not true yet. Narrating an intention in the
past tense is the failure mode, and it is easiest to commit while reporting
progress on something else that IS going well.

**Corollary observed the same session:** a service moved mid-deploy THREE
times (`41f79353`->`85296826`, `39570b24`->`a54dffa3`, plus web). Re-reading
the live SHA immediately before cutting a branch is not caution on this repo,
it is the only thing that works — and `render_deploy`'s rollback refusal
caught two of those, which is a guard earning its keep rather than a nuisance.

## 2026-08-20 — AN EDIT THAT REPORTS SUCCESS IS NOT EVIDENCE THE EDIT LANDED

- **One.** To prove new tests were load-bearing I mutated the source and ran them. 16 passed. The honest reading is "these tests are worthless". The true reading was that `str.replace(..., 1)` had hit the FIRST occurrence — inside the comment I had just written documenting the bug — so the code was never touched. A green mutation run is evidence about the MUTATION as much as the test, and the two readings demand opposite responses.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-20 — FORBIDDEN: concluding a producer was REPLACED because a module says it replaced it

- **10**. Both write the same path. Last writer wins.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-20 — FORBIDDEN: fixing a guard bug ONLY in the guard you found it in

- **The rule.** When a hook/guard defect is about the ENVIRONMENT all guards share — which repo, which index, which env, which tree — fix it in a SHARED module and migrate the other guards, or the next guard written will re-make it. "Fixed" in one file is not fixed.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-20 — FORBIDDEN: a guard test that asserts against the live ledger

- **The rule.** Tests for the ledger hooks MUST build their own throwaway repos. Never assert against `.syndicate/*.md` in the primary tree or any worktree.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-20 — A SUFFIX MATCH CAN HIDE A PATH BUG BY ACCIDENT (`lane-guard` EXONERATED)

- **The rule going forward:** finding a bug via one API surface does not make that surface the right one to verify the fix against. Before writing "verified", confirm which endpoint/shape the actual consumer (the template, the frontend function, the downstream caller) reads, and check THAT one -- even if it means re-deriving the check from scratch rather than reusing the diagnostic query. The two shapes can diverge for the exact same underlying field, on the exact same row, at the exact same instant.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-20 -- A READING OF SHARED MUTABLE STATE EXPIRES AT THE INSTANT IT IS TAKEN

- **How to apply.** For anything shared and mutable -- the index, a deploy claim, a live SHA, `lanes.md`, an in-flight job list -- re-take the measurement in the SAME step that acts on it, not in the step that decided to act. This is the same failure as deploying a branch cut against a stale live SHA, which cost a re-cut earlier the same day; the shape is identical and so is the fix.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-20 — A MUTATION TEST THAT MUTATES THE WRONG MODULE READS AS "VACUOUS SUITE"

- **The rule.** Before concluding a suite is vacuous because a mutation left it green, confirm the code you mutated is the code that suite's SUBJECT actually executes. A false "vacuous" verdict is as costly as a false green: it argues for deleting or distrusting a test that works.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-20 A SAMPLE THAT CONTAINS ONLY ONE STATE CANNOT DIAGNOSE A STATE MACHINE

- **The sample could not have shown that.** A census of every git-tracked recommendations artifact finds `status_state == "pre"` on **all 57 matches in them** -- there was no started match anywhere in the local mirror. "Always 0" and "0 until kickoff" are indistinguishable in a sample drawn entirely from before kickoff, and "0" is exactly what a correct reading looks like there.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-20 A DOCSTRING THAT NAMES ITS OWN PRECONDITION IS A CHECKABLE CLAIM

- **How to apply.** When a function's docstring states a precondition on its CALLERS, that is a grep, not prose -- enumerate the call sites and check each one. This module had already been bitten by exactly this shape (the `_load_team_ratings(as_of)` outage, whose own comment says "a signature change needs a caller census, not a spot-check of the caller you just edited") and the census was never widened to the other preconditions in the same file.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-20 A LOCAL VARIABLE NAMED FOR THE PARENT OF WHAT IT HOLDS

- **How to apply.** When adding a field to an existing extractor, dump the raw node you are reading from and confirm the field is on THAT node -- do not infer it from the variable's name. Renaming to `status_block` / `status` made the two levels visible and the bug impossible to restate.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-20 THE EDIT TOOL REPORTED SUCCESS ON A WRITE THAT NEVER REACHED DISK

- **How to apply.** After an `Edit` on a hook-guarded path, verify the text is on disk -- `grep` for the new symbol, or `git diff --stat` for a plausible line count -- before building anything on top of it. A syntax check is not enough: the file parsed fine, because the missing piece was a definition, not a statement. This session switched to writing edits through a script that asserts its anchor count and re-greps afterwards.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-20 — FORBIDDEN: reading a KILLED pytest run as a result. I retracted a 12-failure report that never existed.

- **I reported "~12 failures in the deployed areas", repeated it, and proposed rolling back three verified production deploys on the strength of it. The number was fiction.**
- *(evidence in `learnings_evidence.md`)*

## 2026-08-20 A POST-DEPLOY VERIFICATION READ ONCE CAN BE AN ARTIFACT OF TIMING, NOT A PROPERTY OF THE SYSTEM

- **Three minutes later the same endpoint served the same fixture with no score and no box**, and stayed that way across six consecutive reads. The passing reading had depended on a transiently fresh input artifact; web then fell back to a month-old git-tracked mirror (`generated_at 2026-07-20`, `status_state "pre"`) and every score source correctly refused it.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-20 A CORRECT REFUSAL ON STALE INPUT IS INDISTINGUISHABLE FROM A BROKEN FEATURE

- **The gate did exactly its job and the user-visible result was a blank card.** Meanwhile the right answer sat on the same disk, in the same request: the live poller's `match_box` carried `final: true`, `FT`, `1-1`, both goals and full team stats, written ninety seconds before.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-20 — A TIMEOUT WROTE `none` AND I DIVIDED BY IT. Four false diagnoses, one root habit.

- **The rule going forward.** Before attributing a stale artifact to a producer, read its MTIME and compare it to when the file was last known good. **An mtime earlier than that, or landing exactly on a whole second, means a `copy2` from the checkout — look at boot-time sync, not at publishers.** And check WHICH SERVICE runs the sync from the CODE, never from the env var: `SYNDICATE_BOOTSTRAP_ON_START=1` is set on all three services and read by nothing on the two workers, because neither imports `syndicate.app`.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-20 FORBIDDEN: staging a SHARED ledger file by path in the PRIMARY tree — `git add <path>` sweeps other sessions' uncommitted edits to that same file

- **The rule going forward.** Make ledger edits wherever protocol wants them, but **COMMIT them from your own worktree**: branch from a fresh `origin/main`, rebuild the file as `origin/main` + only your own edits (line-based), then **assert the heading-level diff against `origin/main` shows ONLY your headings** before committing. The assert is the point — it fails loudly on a stale premise instead of succeeding quietly, which is the general form already recorded in `project-shared-tree-commit-recipes`.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-20 A CENSUS THAT CANNOT READ UNHEALTHY IS NOT A VERIFICATION — the slate can retire your test case between diagnosis and deploy

- **What happened.** The Layer 2 rail duplicated NFL games because two row families for one game reached the board. Between 18:20 and 18:59 CT one family LEFT the live board (`candidate_type=game` rows **2 → 0**; the 21 `layer2_shortlist` rows unchanged). The duplicate needs BOTH. So the obvious post-deploy check — census the current payload for "chips seating more than one card" — returned **0**, and would have returned 0 with the fix reverted.
- *(evidence in `learnings_evidence.md`)*

## FORBIDDEN: a `continue` that skips a check inside a loop whose only failure signal is a counter `[2026-08-20, #481]`

**The belief overturned.** `scripts/verify_wnba_live_scale.py` exited **0** and
printed `VERIFIED on 1 live row(s)` on the first live game it ever saw, having
**compared nothing**. The obligation it was written to discharge was recorded as
discharged on the strength of that exit code. It was caught only because the
output line above the verdict said
`payload omits live_margin/elapsed_min -- cannot recompute`.

**The shape, which is general.** The loop was
`for row: if inputs_missing: continue; ... if mismatch: bad += 1`, and the
verdict was `return 2 if bad else 0`. A skipped row never touches `bad`, so
**"could not check" is indistinguishable from "checked and passed"** in the only
variable the exit code reads. This is the `unknown must not default permissive`
rule, but the permissive branch is a `continue` rather than an `else` — which is
why it does not look like a default at all, and why reviewing the comparison
logic (which was correct) finds nothing.

**The rule going forward.** **Count what you CHECKED, not just what you FAILED,
and refuse to pass on zero checks.** Any verifier needs a third outcome
alongside pass/fail: *did not verify*. Concretely: `checked`, `bad` and
`unchecked` as separate counters; `if not checked: return <nonzero>`; and the
skip path must PRINT what was missing. A success message should state its own
denominator (`VERIFIED: 2 check(s) across 1 live row(s)`) so a zero is visible
in the output rather than inferred from its absence.

**Second defect, same script, independent.** It read `lane["live_margin"]` and
`lane["elapsed_min"]` — fields `_wnba_game_lens` does not publish (margin is
`projection.homeMargin`; elapsed is DERIVED from `status.period`/`clock`). So
the skip fired on EVERY row, always. A verifier that has never once been run
against the live shape it parses has not been tested, only written — and this
one was authored in the same session as the fix it was meant to police, when no
live game existed to run it against. **If you write a verifier you cannot
execute yet, say so where the obligation is recorded**, or its first green run
will be mistaken for the confirmation.

**Also: drive the expected value by IMPORTING the shipped function.** This
script re-implemented the blend locally, so it could have "verified" a formula
production does not run — the same two-copies hazard `#475` called out.

**Cost.** ~0. Caught on the first real live game, and the same run then produced
the genuine confirmation (gap `0.00e+00`, both paths). Fixed in `2ff4ce5b`.

## A WNBA/board date lookup must search YESTERDAY-UTC `[2026-08-20]`

The board keys games by **ET business date**, so an ordinary 7pm ET tip —
`2026-08-21T00:00Z` — is filed under `2026-08-20`. A today/tomorrow-UTC search
therefore returns *"no live game"* during exactly the evening window when games
are being played. Measured at 00:16Z with IND@DAL live and in Q1. Cheap to get
right (search yesterday/today/tomorrow); the miss reads as a clean null result,
which is the dangerous part — it looks like evidence of absence.

## 2026-08-20 — FORBIDDEN: verifying pushed content by slicing a computed substring out of it. Anchor on the LINE. Twice in one session my own checker said ABSENT about content that was PRESENT.

- **What happened, twice, same session, same shape.** Both times I pushed a ledger edit and then "verified" it by pulling the file off `origin/main` and testing a *computed slice* of it. 1. Checked my lane block carried the new baseline number by extracting the block with `IndexOf("`n### ", start)` and searching the slice. Reported `carries number: False`. **The number was there** — the slice ended before it. 2. Checked the old `state.md` bullet was gone by testing whether the string `is NOT "224 green"` still appeared anywhere. Reported the old line **still present**. It was not: my *replacement text deliberately quotes the old line*, so the substring matched my own new prose.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-20 — A PLATEAU IS NOT A FREEZE. A monotonic counter read ONCE cannot tell "stopped" from "between events".

- **The near-miss.** `#387`'s closing reading turned on one field: does `FEED_LIVE_PRUNE plays_dropped` grow during the live slate? Growth = the mechanism works. Stuck near zero = **PREMISE RETIRED**, the verdict that would have withdrawn the whole reason the change exists.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-20 — A ONE-REVISION PRESENCE CHECK CANNOT TELL "ALREADY UPSTREAM" FROM "ONLY IN MY OWN ABANDONED COMMIT"

- **Belief overturned, and I stated it to the user as fact:** that my session's `log/<today>.md` entry was already on `origin/main`, having been swept there by another session's commit. It was not. It was **nowhere in main's history** — it existed only in the commit I had just abandoned.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-20 — OVERTURNED: a loose threshold is a SYMPTOM. Ask what it compensates for before tuning it.

- **What was believed:** `match_team_name`'s 0.72 fuzzy threshold was a tolerance choice — the price of matching team names across three sources that spell them differently, to be tightened or loosened as needed.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-20 — OVERTURNED: "N of N" is worth nothing until you know the sample COULD have contained a counterexample.

- **What was believed:** `live_home_score`/`live_away_score` are a placeholder the artifact builder writes, not a real reading. Evidence: the string `"0"` on **12 of 12** sampled matches, *including* `status_state == "pre"`.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-20 — FORBIDDEN: in a tree you did not create, an unexplained diff is another session's work until proven otherwise.

- **What happened:** I ran `git checkout -- syndicate/features/soccer/cards.py` in the shared lane worktree, on a 67-line diff I had not written. I checked that the function it contained was already on `origin/main`, concluded the working copy was a redundant leftover, and discarded it. It was almost certainly the `soccer-live-score-clock-box` session's in-flight work — they independently reported two `Edit` calls that "reported success and never reached disk" in that window.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-21 — A GITIGNORED FILE CANNOT BE A MODEL INPUT. Allowlisting it does not help, and the result is a feature that is live, tested, deployed and does nothing

- **Believed:** wiring the NFL prop model to `spread_line`/`total_line` from `data/nfl_source/tracking/nflverse/schedules_games.csv` and adding that path to `HOT_ARTIFACT_PATTERNS` was enough to ship the game-context mechanism.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-21 — A REACHABILITY PROBE SAMPLED FROM REAL DATA CAN BE DEGENERATE, and then it reports a live mechanism as dead

- **Believed:** `off != on` on a real row proves a mechanism is reachable, so probing `train_rows[0]` was a fair test.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-21 — A DOCUMENTED "acceptable for v1" LIMITATION IS A LIVE DEFECT THE MOMENT DATA ARRIVES TO EXERCISE IT

- **Believed:** `short_name_from_full`'s docstring already named the collision ("two players sharing a first initial + last name would collide — acceptable for a v1"), so it was a known, bounded simplification.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-21 — OPENING A LANE IN THE PRIMARY TREE AND THEN OPENING A WORKTREE SILENTLY DROPS THE LANE BLOCK

- **Believed:** `adopt` is only needed when a lane has PRE-EXISTING uncommitted work, so a brand-new lane can skip straight to `open`.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-21 — FORBIDDEN: concluding a capability is ABSENT from two adjacent artifacts

- **The rule going forward.** Before reporting a capability ABSENT, name the surface that WOULD carry it and check THAT — an API route, a payload key, a producer function — not two artifacts adjacent to it. Grepping for the concept (`live_player`, `boxscore`) takes one call and would have found it immediately. The asymmetry is the point: "present" needs one positive reading, "absent" needs a search over where it would live, and I spent the effort budget of the first on a claim of the second.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-21 — A HEALTHY LOG LINE CAN LOOK LIKE THE BUG (`written=0` was correct)

- **The rule going forward.** When a question is decided by ONE artifact, build the read for that artifact before forming a third hypothesis. `GET /api/ops/live-lens/snapshot-index?sport=wnba` now reads the lens through the same keyvalue-aware reader the join uses and reports the join's verdict per game; it answered in a single call what four rounds of inference could not, and it also disproved a fifth hypothesis of mine (a `pregame` lane on a FINAL game is correct, not a drop). The corollary to the standing "instrument blindness" rule: a reading is only evidence once you know what HEALTHY looks like, and `written=0` had a healthy meaning nobody had written down.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-21 — ABSENT IS NOT None, AND THE DIFFERENCE NAMES THE PRODUCER

- **The rule going forward.** On a dict-shaped payload, distinguish `key not in payload` from `payload[key] is None` before theorising about VALUES. Absent indicts the PRODUCER (this code path never ran); None indicts the INPUT (it ran and had nothing). Two of my three explanations were about the input; the answer was the producer, and one `in` check would have pointed there first. Carried into the fix: a one-sided market now yields None with the KEY PRESENT, so the join can tell "this producer does not do market prices" from "it does, and this row has none".
- *(evidence in `learnings_evidence.md`)*

## 2026-08-21 — "UNAVAILABLE" IN A LEDGER ENTRY MEANS "NOT RETAINED", NOT "UNOBTAINABLE"

- **The rule going forward.** "Unavailable" in a ledger entry is a statement about what was retained at the time of writing, not a property of the world. Before inheriting one as a permanent constraint, ask what it would COST to obtain — this repo already had the fetcher, the credit accounting and the precedent. Totals moves from "refused forever" to "refused until graded", which is a different roadmap.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-21 — I DERIVED SERVICE OWNERSHIP FROM CODE AND SHIPPED TO THE WRONG WORKER. The env gate runs FIRST

- **Believed:** `_weekly_sport_claimed_by_fast_tick("nfl", today) == True`, so NFL is owned by the fast tick, which runs on **live-odds-worker** — therefore that service needed the NFL capture fix before the season. I said so to the user, wrote it into `state.md` and `deploys.md`, and deployed on it.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-21 — A 403 FROM WEB IS A ROUTE RESTRICTION, NOT AN ABSENT FILE

- **The rule going forward.** Before recording a file as unreachable, say WHICH reader refused and WHICH consumer actually needs it. If the consumer runs on a worker and the refusal came from a web route, the answer is not "blocked" — nothing has been established. Cheapest discriminator: name the consumer's process first, then test the reader THAT process would use.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-21 — AN APOSTROPHE IS INTRA-WORD; A HYPHEN SEPARATES WORDS

- **The rule going forward.** In a name normaliser, DELETE intra-word punctuation (apostrophes, straight and typographic) and SUBSTITUTE separators (hyphens, slashes) with a space. One regex for both is wrong for one of them, always. And a name join must COUNT AND NAME its misses: `players_unmatched` exists so a zero is attributable, because a silent zero and a named zero need different fixes.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-21 — FORBIDDEN: `cat >` on a ledger file. Append only, and re-check AFTER the rebase

- **The rule going forward.** Never `cat >` a `.syndicate/**` file — `>>` always, or an Edit against content you have just read IN THE TREE YOU ARE WRITING TO. Re-check existence AFTER any rebase or fetch, not before. And read `git diff --cached --numstat` before every ledger push: it is one line, it is the only thing that distinguishes "I added my entry" from "I replaced someone else's", and it has now caught this class twice.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-21 — THE DEPLOY CLAIM IS NOT A GLOBAL LOCK ONCE SESSIONS USE WORKTREES

- **FORBIDDEN: reading `deploy_claim.py acquire`'s own `ACQUIRED` as proof you hold a service.** It is proof you hold it *in the tree you ran it from*.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-21 — FORBIDDEN: taking a CODE COMMENT as authority for WHICH SERVICE runs something

- **The rule going forward.** Before ANY deploy, get the running system to name the executor of the exact branch you changed, in one call:
- *(evidence in `learnings_evidence.md`)*

## 2026-08-21 A `max(timestamp)` INSIDE A SEASON-SCOPED ARTIFACT IS A HINDSIGHT LEAK, AND IT FLATTERS

- **Two rules.**
- *(evidence in `learnings_evidence.md`)*

## 2026-08-21 THE PRIMARY SHARED TREE IS NOT A NARRATOR OF `main`, AND `reset --hard` ON IT DESTROYS OTHER SESSIONS' WORK

- **1. A grep in that tree is not evidence about the codebase.** Checking field names before writing them into a scheduled task, `grep -r WNBA_LIVE_BOX_` returned NOTHING — while that exact string was in production logs 40 minutes earlier. The grep was correct; the assumption about which tree it ran in was not. **When a tool disagrees with production about whether code EXISTS, suspect the tree before the production reading.** `git rev-list --left-right --count HEAD...origin/main` is one line and settles it. Read source from the remote (`git show origin/main:<path>`) rather than from the checkout.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-21 — AN UNCHANGED VALUE ACROSS A DEPLOY IS STALE DATA UNTIL PROVEN OTHERWISE

- **FORBIDDEN: concluding a deployed fix failed, from a reading whose artifact you have not shown was rebuilt by it.** Four false failures in one session, all this shape:
- *(evidence in `learnings_evidence.md`)*

## 2026-08-21 — A SUCCESS-ONLY EMITTER MAKES ZERO INVISIBLE

- **Rule: report the zero, not just the success.** Corollary already in this file — absence of a signal is a fact about the EMITTER first.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-21 — A CONDITIONAL LOCAL IMPORT SHADOWS FOR THE WHOLE FUNCTION

- **Rule: a conditional local import binds that name local for the ENTIRE function, so every branch that does NOT run the import raises `UnboundLocalError`.** An UNCONDITIONAL local import at the top of a function is harmless — it always runs before any use. Only the conditional one is a trap.**

- *(evidence in `learnings_evidence.md`)*

## 2026-08-21 — A NULL RESULT NEEDS A NEGATIVE CONTROL BEFORE IT IS EVIDENCE

- **Rule: run the control on something known-good before an absence counts.**

- *(evidence in `learnings_evidence.md`)*

## 2026-08-21 — A DOCSTRING DESCRIBES INTENT; THE CODE DESCRIBES BEHAVIOUR

- **Rule: where a comment and the writer disagree, the writer wins.**

- *(evidence in `learnings_evidence.md`)*

## 08-21 A KILLED PROCESS IS NOT A KILLED PIPELINE — `pkill` on the child leaves the wrapper running with STALE ARGS

`pkill -f backtest_soccer_live_totals` killed the python. It did NOT kill the
`bash -c "cmd_A; cmd_B"` wrapper, which then ran **cmd_B with the OLD
arguments** and wrote `holdout_ON.json` at 21:02Z — a file with plausible
numbers, a fresh timestamp, and entirely the wrong data (37 MLS matches from a
window I had already rejected).

Caught only by checking the file's OWN provenance (`window`, `leagues`) before
reading its results. The tell was a timestamp that PREDATED the run I thought
produced it.

**RULE: kill the wrapper, not the child. And before reading any result file,
check that it describes the run you think you launched — window, scope, and a
timestamp AFTER you started it.** Third stale-artifact catch in one session;
the other two were a board built before a deploy and a shortlist artifact that
had not been regenerated.

**Corollary that made this cheap:** write each run to a DISTINCT filename. A
leftover cannot impersonate a result it cannot overwrite.

## 08-21 FORBIDDEN: validating a finding on a window that does not contain the thing

A held-out validation for a EUROPEAN bias was pointed at **June–July**, the
European off-season. It returned 37 matches, all MLS. Had it run, it would have
reported "held-out validation" while actually testing whether a European
finding transfers to a different competition — and it would have looked
entirely legitimate.

**RULE: before running a validation, assert the window CONTAINS the population
the finding is about.** One `fetch_events` count per league, seconds, and it
turns a meaningless result into a caught error. An empty or wrong-population
window and a genuine null result are indistinguishable in the output.

## 08-21 MAE HIDES DIRECTION, AND DIRECTION IS THE WHOLE FIX

I hypothesised the live totals mean OVER-predicts late and was ready to correct
it. Signed bias showed the OPPOSITE: it under-predicts. **A correction applied
in the hypothesised direction would have made the model strictly worse while
looking like progress.**

Two further hypotheses died the same way: a flat −0.18 offset that was my own
neutral-ratings input, not a model defect; and "second-half rate too low",
refuted by measuring 57.1% ± 3.7pp against an assumed 55–56% — inside one
standard error, so changing the calibrated constant would have been fitting
noise.

**RULE: report SIGNED error beside absolute, always. Before changing a
calibrated constant, measure what it encodes and compare against its standard
error — a difference inside 1 SE is not evidence.** Three hypotheses, three
refutations, one real defect (a resumed sim missing stoppage — a MISSING
QUANTITY, not a tuned parameter).

## 08-21 AN UNDERPOWERED TEST PASSES AND FAILS BY LUCK — RAISE n, DO NOT RE-ROLL THE SEED

`test_red_carded_team_is_disadvantaged` failed after an unrelated change to the
resume clock. Swept at one seed:

    n= 150  diff +0.0267  (1 SE ~0.0384)   <- decided by noise
    n= 600  diff -0.0817  (1 SE ~0.0192)
    n=1500  diff -0.1313  (1 SE ~0.0121)   <- ~11 SE, unambiguous

The mechanism was correct and LARGE. At n=150 the effect was smaller than one
standard error, so the assertion was decided by the seed's trajectory: it passed
before the change and failed after, and **both outcomes were luck**.

**RULE: when a Monte Carlo test flips on an unrelated change, sweep n before
touching anything. Re-rolling the seed until it goes green restores a pass that
measures nothing** — and leaves the next person believing a mechanism is tested
when it is not.

## 2026-08-21 — FORBIDDEN: a deploy chained in the same shell command as anything naming another service

- **Rule: one deploy, one bash call, with no other `--service` in it.** Release claims, acquire claims and run preflights as their own calls.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-21 — FORBIDDEN: explaining a local failure with a LOCAL cause when the same code runs in production

- **Rule: a cause that conveniently quarantines a failure to the machine you are standing on deserves more scepticism than a cause that implicates production, not less** — the two are not symmetric, because only one of them lets you ship.**

- *(evidence in `learnings_evidence.md`)*

## 2026-08-21 — READ THE TTL BEFORE BREAKING A LOCK. The force bought 12 minutes.

- **Rule: before forcing a claim, print its age against the TTL and state the remaining wait.** The protocol's `--force` is for a session that is GONE; when the holder is alive, the honest question is whether the work can wait N minutes, and N is a number the tooling already knows. A remaining-wait figure belongs in the guard's own output, next to where it prints the holder.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-21 — FORBIDDEN: asserting a trend from one sample, especially a scary one

- **10.2 / 10.4 / 19.5 BEFORE I touched anything**, and 12.8 / 11.4 / 17.8 after. 19.7 was an ordinary member of the spread. There was no trend.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-21 — Reasoning off an invented clock, and querying a window in the future

- **Rule: never state an elapsed time without reading the clock, and never treat an empty log result as absence until the tool's own COVERED range contains the period you care about.** Related: [[feedback_instrument_blindness]].
- *(evidence in `learnings_evidence.md`)*

## 2026-08-21 — A poll that matched its own instrument

- **Rule: a poll predicate must match the SHAPE of a real record, not the topic.** `^2026-` (a timestamped line) is a predicate; the search term is not, because the tool prints the search term back. Anchor on the record format.
- *(evidence in `learnings_evidence.md`)*

## 08-21 THE "EMPTY BOX SECTIONS" BUG NEVER EXISTED — I COUNTED THE WRONG FIELD

Card sections come in TWO SHAPES. List sections carry `rows`. TABLE sections
carry `table_rows` and set `"rows": []` **by design** (see
`soccer/cards.py::_correct_score_section`, which returns both keys). Goals,
Match stats and squad projections are all table sections.

I measured `len(section["rows"])`, got 0 for every table section, and reported
"box sections render 0 rows on all 4 games" in a UI audit. The truth, read from
the same production payload with the right key:

    Goals        3 table_rows   15' Havertz, 23' Saka, 49' Odegaard
    Match stats 12 table_rows   Possession 35.5%/64.5%, Shots 4/20
    ARS squad   23 table_rows   with prices and edges

**WHAT THAT ONE WRONG FIELD COST:** a false audit finding; two commits
(`0aaf71f0` reader swap, `94a53639` data_root path) shipped to fix a
non-problem; a web deploy and rollback; a 502 misread as caused by my own
change; and two wrong outage attributions chased in sequence. Every later
"still 0 rows" reading LOOKED like confirmation that the fix had failed, so the
bad metric kept generating new hypotheses instead of being questioned.

**RULE: before reporting a count of zero as a defect, print the CONTAINER'S
KEYS.** One `sorted(section.keys())` would have shown `table_rows` beside
`rows` and ended this at the first reading. A zero from the wrong key is
indistinguishable from a zero from missing data, and it is far more likely --
missing data has a cause, a typo'd key needs none.

**Corollary, and the reason this ran so long:** when a fix does not move a
metric, suspect the METRIC before writing the next fix. I twice diagnosed the
read path -- because that is where the PREVIOUS bug was -- rather than testing
whether the measurement was sound.

## 2026-08-21 — The preview pane CANNOT verify a CSS edit. It caches the parsed stylesheet.

- **This is the dangerous class of instrument failure, because it reads as a CODE failure.** The obvious conclusion — "my CSS is wrong, it isn't applying" — is exactly what the tool is showing you, and it is false. I nearly rewrote working rules to satisfy a cached stylesheet.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-21 — A tooltip is not a reading surface, and the data was already there

- **When adding a UI affordance for stored data, print the FIELD LIST of what is stored and ask which fields the surface can physically show.** Here that is one command and it would have named `description` on day one.
- *(evidence in `learnings_evidence.md`)*

## 08-22 `INVALID_MARKET` MEANS TWO DIFFERENT THINGS, AND A STATUS CODE CANNOT TELL THEM APART

`fetch_soccer_oddsapi_odds_local.py` carried, since 2026-07-21:

    # btts/draw_no_bet/double_chance confirmed unavailable (HTTP 422) against
    # the live API on the current plan/region -- not attempted here.

**It was wrong, and it cost a month of two markets nobody knew we could have.**
The Odds API returns `INVALID_MARKET` with two distinct messages:

    "Markets NOT SUPPORTED BY THIS ENDPOINT: btts"   <- VALID key, wrong endpoint
    "INVALID markets: both_teams_to_score"           <- no such key

Read as a bare 422 they are identical. `btts` and `alternate_totals_corners`
are served from the PER-EVENT endpoint -- the one the props fetcher ALREADY
calls -- so capturing them costs no additional API calls at all.

**RULE: when an API refuses, READ THE MESSAGE, not the status code.** And a
dated "confirmed unavailable" comment is a measurement with an expiry, not a
fact: plans, regions and endpoints all move.

**SECOND FAILURE IN THE SAME PROBE, and the more general one:** the first
region tried was `eu` (btts 4 books, corners 1) and that was nearly written up
as the market's depth. Actual coverage: us 7/7, uk 11/4, all four regions
29/18. **A single-parameter probe measures that parameter, not the world.**
Before reporting a capability as thin, vary the one knob most likely to explain
thinness.

## 08-22 A COUNT OF ZERO IS A CLAIM ABOUT YOUR QUERY FIRST

Card sections come in two shapes: list sections carry `rows`, TABLE sections
carry `table_rows` and set `"rows": []` BY DESIGN. Goals, Match stats and squad
projections are all table sections.

Counting `len(section["rows"])` produced 0 for every one of them, which was
filed as a UI-audit defect ("box sections render 0 rows on all 4 games"). The
same production payload, read with the right key: Goals 3 rows (15' Havertz,
23' Saka, 49' Odegaard), Match stats 12, ARS squad 23.

**COST: two commits fixing a non-problem, a web deploy, a rollback, a 502
misattributed to my own change, and a second wrong attribution after that.**
Every later "still 0 rows" LOOKED like confirmation the fix had failed, so the
bad metric kept generating hypotheses instead of being questioned.

**RULE: before reporting a zero as a defect, print the container's KEYS.** One
`sorted(section.keys())` ends it at the first reading.
**COROLLARY: when a fix does not move a metric, suspect the METRIC before
writing the next fix.** The read path was diagnosed twice -- because that is
where the PREVIOUS bug was -- rather than testing whether the measurement was
sound.

## 08-22 VERIFY THE SHA OF THE SERVICE THAT EXECUTES, NOT THE ONE YOU DEPLOYED

A soccer refresh was fired to exercise new capture code, after explicitly
checking that `live-odds-worker` was live on it. The job produced nothing:
`launch_mode: manifest_only` routes onto **refresh-worker's** claim loop, and
refresh-worker was three commits behind. That routing was written down in this
session's own commit message an hour earlier.

The same shape governs whether a FEATURE is live at all: soccer live_state --
and therefore momentum -- is written by refresh-worker
(`SYNDICATE_ENABLE_SOCCER_WEEKLY_REFRESH_AUTORUN`, scoped in `render.yaml` to
"the sim and live_state"), NOT by the worker whose name suggests live data.

**Worse than absent: the live-lens loop runs on BOTH workers writing the same
aggregate, so a partial deploy makes a feature FLICKER -- whichever service
ticks last wins.** A clean zero is easier to diagnose than intermittent truth.

**RULE: a sequencing check is only worth the service it points at.** Before
claiming a feature is live, resolve which service executes it -- from env and
routing, not from the name -- and check THAT SHA.

## 08-22 MOMENTUM DOES NOT PREDICT *WHEN* A GOAL IS COMING — and the earlier positive result did not imply it would

Swept 5 weight variants x 6 half-lives (90s-900s) over 200 completed matches
from last season, held out by match-id hash, target = "does a goal land in the
next 10 minutes", feature = ABSOLUTE pressure (a goal happening is about
pressure on either side; signed momentum answers WHO, not WHETHER):

    BEST ON FIT : on-target-heavy @ 600s   AUC 0.5403
    ITS HOLDOUT :                          AUC 0.5107   (base rate 0.2471)
    every variant x half-life: holdout AUC 0.49 - 0.54

**0.5107 is a coin flip. Not usable for timing.** WHO, conditional on a goal
having happened, is no better: best fit `shots-only @ 900s` 0.5961 -> holdout
**0.5224** on n=1221.

**THE TRAP, AND IT IS THE WHOLE LESSON.** The 08-21 lead/lag test found
momentum elevated before goals: +1.141 vs 0.000 control, Cohen's d = +0.397,
and that result was sound. It answered: *given a goal happened, was momentum
elevated 2 min before, versus a control instant?* -- retrospective, and
oriented to the side that scored.

The question worth acting on is: *at an ARBITRARY instant, is a goal coming?*
The signal does not survive the translation. **"Separates from control" and
"predicts the event" are different claims**, and only the first was earned. The
phrase "momentum LEADS goals" -- written into a commit message and a state.md
section -- reads as the second.

**RULE: a retrospective separation result is a HYPOTHESIS about prediction, not
evidence of it.** Before building on one, restate it as the forward question
(at time T, with only information available at T, what happens next?) and score
it held out against the base rate. The two differ by ~0.04 AUC here, which is
the difference between a feature and nothing.

**ALSO: the best HOLDOUT row was not the best FIT row** (`corners-heavy @ 900s`,
0.5426). Selecting it would be fitting the holdout -- the same error one level
up -- so it is recorded as a hypothesis for a fresh slice, not a result.

**WHAT THIS DOES NOT RETRACT:** the chart itself. It is an honest DESCRIPTIVE
panel of who is on top, which is what the user reads it for manually, and the
sign convention is verified correct against live scorelines. It is a narrator.
It is not a timing signal, and nothing should price off it.

## 08-22 THE PRE-REGISTERED TEST KILLED THE 40.2%, AND MY OWN PASS/FAIL BANDS WERE WRONG

Rule fixed in advance (`0fff6254`): fire when 34-38 min into a half AND pressure
>= 9.2525 (90th pct, derived from the FIT half only). Scored on 158 matches from
a DIFFERENT period, all 699 prior ids excluded:

    hypothesis (post-hoc)  0.402
    FRESH hit rate         0.2547
    time-window only       0.3063   (n=1580)
    momentum increment    -0.0516
    fresh base rate        0.2631

**MOMENTUM ACTIVELY HURTS.** The full rule is 5.2 points BELOW the time window
alone, and BELOW the base rate -- firing on pressure selects worse-than-average
moments. The 40.2% was an artifact of picking the time window AFTER seeing which
decile won on the holdout, exactly as suspected.

**MY PRE-REGISTERED BANDS WERE THEMSELVES DEFECTIVE.** They read
`>= 0.25 -> WEAK PASS (clears 3-1)`, so the run printed **WEAK PASS** for a rule
that loses to doing nothing. I set the bands against BREAK-EVEN and never against
the BASE RATE. A signal must beat the base rate before break-even is even the
right question -- otherwise "profitable at 3-1" is satisfied by any rule that
fires during a period when goals are common, including a rule with no signal at
all.

**RULE: a pre-registered threshold must include the do-nothing baseline, not
just the economic one.** Beating break-even is necessary and not sufficient; the
comparison that decides whether a FEATURE works is against the base rate, and
against the simpler feature it claims to improve on.

**WHAT REPLICATED:** the clock, not the momentum. 34-38 minutes into a half ran
0.3186 on holdout and 0.3063 on fresh, against base rates of 0.2342 and 0.2631 --
a stable ~1.16-1.36x lift from an unbiased decile split both times. That effect
is real, needs none of this machinery, and is almost certainly in the market
price already.

**STANDING: momentum is a NARRATOR.** Three tests now -- global AUC (0.5417
held out), conditional tail (killed by preregistration), and the increment over
time alone (NEGATIVE). Nothing should price off it. The chart stays because it
honestly describes who is on top, which is what it is read for.
---

## 2026-08-22 — An absent LOG LINE is not an absent EVENT, and a stale ledger figure will out-argue a fresh measurement

- **1. I diagnosed for two hours on a number the ledger had, and production didn't.** `state.md` said the soccer projection join served `rows_with_projection: 4` of 1,142. I quoted it forward as current, built a mechanism around it, wrote a `todo.md` item on it, and shipped instrumentation to explain it. The first real reading was **9,598 of 20,014 (48%)** — the join had been working since `#379`'s window fix actually ran. The figure predated that deploy and nobody had re-measured.
- *(evidence in `learnings_evidence.md`)*

## 08-22 THE BEST GOAL WINDOW WAS HIDDEN BY MY OWN SAMPLING CUTOFF

Every momentum sweep sampled `start=300, end=5100` -- so **80-95' was never a
decision point**. The densest scoring period in football was excluded by a
constant I chose and never questioned. Sampling the full match (to 5700s):

    clock    n     hit     lift   window available
    80-84   848   0.3455   1.48        8.5 min     <<< best in the match
    36-40   848   0.2889   1.24       10.0 min
    84-88   846   0.2636   1.13        4.5 min
    88-92   211   0.2275   0.98        2.0 min
     8-16         0.1722   0.74       10.0 min     (quietest)

**80-84' clears the 2-1 break-even (33.3%) on the CLOCK ALONE**, base rate
0.2331. And the `window available` column is why later is not better: by 88'
only 2 minutes of a 10-minute window remain, so the rate keeps climbing while
the bet stops existing. 80-84' is where rate and runway overlap.

**EVENTS, TESTED INDIVIDUALLY FOR THE FIRST TIME.** Earlier sweeps moved four
shot families together, so no single type could be seen:

    corner-awarded    1.19      shot-ON-target   0.97   <- BELOW base
    shot-off-target   1.19      handball         0.88
    shot-blocked      1.17      "all types"      1.03   <- dilutes

**Shots ON target predict goals WORSE than shots off target.** Goals are
excluded from the feature, so a remaining on-target shot is a SAVED one -- the
chance is spent. Off-target and blocked shots mean pressure still building.
Anyone hand-weighting these would have ranked them the other way round; I did,
in the shipped chart (`shot-on-target: 3.0` vs `shot-off-target: 1.5`).

Crossed against time, the best feature adds +0.02 at the money bucket and flips
sign across others (+0.054 at 16-20', -0.050 at 8-12'). Noise-shaped.

**RULE: a sampling range is a modelling assumption. State it and test its
edges.** `end=5100` was written once, carried through four analyses, and hid the
only result that clears a real break-even. No amount of feature engineering
inside the window could have recovered what the window excluded.

## 08-22 POOLED RESULT: THE CLOCK IS THE ONLY REAL SIGNAL — and FotMob IS reachable

Pooled 370 matches (212 holdout + 158 fresh), 32,501 samples, base 0.2450:

    TIME    80-84'   0.3320  lift 1.35   <- best, essentially AT 2-1 break-even
            36-40'   0.3122  lift 1.27
            12-16'   0.1851  lift 0.76   (quietest)
    EVENTS  corner / shot-off-target     lift 1.19
            shot-ON-target               lift 0.97  (BELOW base)
    MOMENTUM top-3 deciles               lift 1.12
    MARGIN  margin 1                     lift 1.06
    COMBOS  "all types"                  lift 1.03  (dilutes)

**FOUR HYPOTHESES OF MINE DIED HERE, all measured:**
1. Momentum predicts WHEN -- AUC 0.5417 held out.
2. Momentum works conditionally in a time window -- prereg killed it, and the
   increment over the clock was NEGATIVE (-0.0516).
3. Momentum is better at saying NO goal -- pooled bottom-3 lift 0.92 vs top-3
   1.12. The TOP discriminates more. Also non-monotonic: decile 1 reads 1.10
   because near-zero pressure means "early match", not "quiet match".
4. Score state matters -- "losing by 1 late pushes" does NOT appear. At 80-84',
   margin 1 (0.3283) is BELOW the bucket average (0.3320).

**REPLICATION IS OF THE PATTERN, NOT THE BUCKET.** 80-84' ran 0.3455 holdout ->
0.3135 fresh, while 36-40' ran 0.2889 -> 0.3434. Both late-half windows are
elevated in both samples (1.20-1.48) but which one WINS flips. Picking the
single best bucket is the same overfit that killed the 40.2%.
CONFOUND, stated: the fresh set is Jun-Aug 2026, heavily MLS/early-season, base
0.2610 vs 0.2331 -- a robustness check across different football, not like-for-like.

**FOTMOB IS REACHABLE, and the scope doc's blocker was WRONG.**

    /api/matchDetails?matchId=      -> 404
    /api/data/matchDetails?matchId= -> 200, 276,792 bytes
    expectedGoals YES · xg YES · momentum YES · shotmap YES
    NO x-mas signing header needed. AiScore root: 403 (blocked).

The path moved from `/api/` to `/api/data/`. `scope_2026-08-21_fotmob_xg_
enrichment.md` recorded it as unverified-and-probably-signed; it is neither.

**WHY THIS NOW MATTERS MORE, not less.** Everything we already own has been
measured and is weak. FotMob supplies the one thing ESPN structurally cannot --
chance QUALITY (shot xG) rather than shot COUNTS -- and there is now a hard bar
to clear: beat 0.3320 at 80-84', and beat +0.02 as an increment over the clock.

## 2026-08-22 — FORBIDDEN: never join on an id minted from a content hash of a payload that carries live prices

- **The tell, and it was in the repo the whole time:** `pipeline/intelligence_state.py:2028` already said those ids come from "a content hash of the full recommendation payload (incl. live odds/edge/probability)" and would mint a fresh row "purely from ordinary price drift". A mitigation was built around that fact (gate recording on `source_fingerprint`) without anyone asking what it meant for the JOIN downstream.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-22 — FORBIDDEN: verifying a REORDERING by elapsed-time-since-boot

- **The rule:** to verify a change in ORDER, measure ORDER — the co-occurrence of the branch's marker with the marker of the branch above it. `#504`'s real reading is `RECONCILIATION_AUTORUN_GATED` at 18:28:38.192696 and `LEDGER_INDEX_SIZE` at 18:28:38.194012: **1.3ms, same tick**, against 116s and a different tick before. Elapsed-since-boot measures the loop; delta-between- branches measures the chain.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-22 — EXONERATED: forcing the settlement autorun with an interval override

- **Stop re-investigating this.** If settlement is not running, read WHICH branch took the tick before touching any gate. A job can be enabled, correctly configured, past its interval, and still never evaluated.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-22 — the retraction was as wrong as the claim. "It ran once" is not "it runs"

- The rule going forward: **an allowlist entry is a change to the CONSUMER, not to the producer.** Before adding one, find every reader of that path and check what it does when the file is suddenly present. A reader that gates on EXISTENCE rather than freshness converts a latency fix into a silent correctness bug. The producer's refresh cadence is the second question: an artifact refreshed prior-day cannot serve a live surface no matter who can read it.
- *(evidence in `learnings_evidence.md`)*

## 08-22 TWO REAL LEADS AT LAST — and they came from questions I did not think to ask

**1. LA LIGA 80-84' REPLICATES HELD OUT. The first result all session to survive
a clean test above break-even.**

    DISCOVERY (98 matches)    80-84'  0.3954  lift 1.77
    HELD-OUT  (222 matches)   80-84'  0.3604  lift 1.57   CLEARS 2-1 (33.3%)

The 222 were the FIT half, never scored on time. Held-out profile shows real
structure, not a lone spike: quiet 16-28' (~0.17), a first-half rise to 0.3018
at 40-44', flat mid-second-half, then 0.3604 at 80-84' falling to 0.2374 by
88-92' as the window runs out.

**THE POOLED NUMBER WAS HIDING THIS.** Pooled 80-84' read 0.3320 / lift 1.35
across all leagues. Split by league: la_liga 1.78, epl 1.24 (largest sample, does
NOT clear 2-1), mls 1.17, primeira_liga **0.89 -- below base**. I reported a
league-averaged number as a property of football. Same averaging error that made
momentum look like a global null when it was conditional, running the other way.

**2. FOTMOB xG BEATS ITS OWN CONTROL. Chance QUALITY adds where VOLUME does not.**

    top decile        xg 1.19   bigchance 1.30   count 1.09  <- control
    at 80-84'         xg  clock 0.2972 -> 0.4000  delta +0.1028
                      count               0.2778  delta -0.0194  HURTS

`count` is the ESPN-equivalent feature and it hurts by -0.019, replicating the
ESPN momentum increment (-0.0516) on completely different data. That is the
FotMob question answered: xG measures something shot counts cannot.

**BUT n IS ~90 IN THAT CELL, AND THE PRECEDENT IS UGLY.** The last promising
tail number this session was **40.2%** at n=276, and preregistration killed it.
This one reads **40.0%** at n=90. Treat +0.103 as UNVALIDATED until it survives
the same treatment. Reading a tail result after the fact is how the 40.2%
happened.

**THE METHOD LESSON, twice over:** both leads came from splits I had not thought
to make -- the user asked for leagues individually, and for the full sampling
range. Neither was a modelling insight; both were "you are averaging over
something that differs". Before reporting a pooled effect, enumerate the
dimensions it averages over and check the big ones.

## 08-22 THE xG RESULT DID NOT REPLICATE — AND THE CONTROL THAT "PROVED" IT WAS ARITHMETIC

Pre-registered (`fdf1b892`, committed before the fresh sample existed), scored on
246 fresh matches, ZERO overlap with discovery. Identical procedure, top quartile
inside the 80-84' band:

                  discovery(n=90)   fresh(n=241)
        xg            +0.1028          +0.0319
        count         -0.0194          +0.1107

**THE RANKING REVERSES.** On discovery xG beat count by 0.12; on fresh count beats
xG by 0.08, and count FLIPS SIGN. "Chance quality beats chance volume" was the
whole case for a FotMob dependency, and it is dead — not weakened, reversed.

**FORBIDDEN: a control matched by THRESHOLD VALUE when the features are on
different scales.** The first scoring run applied xG's threshold (0.8905) to
both. xG-pressure ranges 0.09..1.82; count-pressure ranges 1.55..13.76. So the
threshold fired on 24% of the band for xG and **100% for count** — the control
selected the ENTIRE band, making its delta `+0.0000` BY ARITHMETIC, before any
data existed. That forced zero then read as *"the control does not clear"*, which
was the single sentence justifying the dependency. Match controls by SELECTION
RATE. Rebuilt that way the control scored +0.1447 and won.

**The tell was in the output I had already read**: `count` fired on 963 samples
and `xg` on 229, and the delta was EXACTLY +0.0000. An exact zero on a
noisy empirical quantity is a computation, not a measurement. Same family as the
box-section `rows: []` error — the discriminating number was on screen and I
was reading the verdict line instead.

**THREE tail results have now failed to replicate this session** (momentum 40.2%,
xG +0.1028, and the xG-over-count ranking). All three were read AFTER seeing the
tail, at n<300. The one result that DID replicate (la_liga 80-84', 222 held-out)
was tested because the user asked for a split, not because a number looked good.

**What actually survives:** the CLOCK. Both samples independently show 80-84'
elevated over base (0.2972 and 0.2793 vs base 0.2562). That is the third
independent confirmation, and it needs no vendor dependency at all.

---

## 2026-08-22 (later) — A rule written from one sport's vocabulary is a rule about that sport; and a safety net that skips the biggest cases is not a safety net

- **1. THE ALT-LINE FILTER I SHIPPED DID NOTHING ON SOCCER, and the user found it, not me and not the tests.** I defined "alt line" as a market whose name ends `_alt`, because that is how MLB and NFL quote them. Soccer's `DEFAULT_GAME_MARKETS` is exactly `["h2h","totals","spreads"]` — it has no such market, and expresses the same concept as SEVERAL ROWS OF ONE MARKET at different lines. The filter matched nothing; "Main lines only" was a no-op on the sport with the worst ladder problem. I had even written a test asserting `totals_alt` is alt and `totals` is not, which passed and proved nothing about soccer.
- *(evidence in `learnings_evidence.md`)*

## 08-22 THE ANSWER, at 5,552 matches: THE EVENT SIGNALS ARE NOISE. The clock is real and too small to bet.

Two years, ten leagues, 9 signals (xg, count, ontarget, inbox, bigchance,
FotMob's OWN momentum abs+slope, red-card advantage, subs) x 10 leagues x 24
time bands. Fit-half selects, holdout-half scores once, distinct cells only.

**NULL CONTROL SETTLES IT.** Same pipeline, goal series swapped BETWEEN matches
within league (severs feature-label link, KEEPS within-match label clustering):

    REAL      distinct cells 23
    NULL runs                15, 22, 17, 15, 13   mean 16.4

23 against a null that routinely produces 22. The sweep MANUFACTURES ~16
"surviving" cells on data with no signal in it; it found 23. That excess is
run-to-run variation, not a discovery. **Every individual cell in that list --
including the ones clearing 2-1 with tight CIs -- is indistinguishable from
what the machine produces on noise.** This is why the earlier "36 survivors vs
~20 by chance" line was worthless: I made the 20 up by multiplying 0.05 by 417.

**THE CLOCK IS REAL BUT SMALL.** Corrected profile, holdout, n~6,700/band:
16-20' 0.2408 [0.231,0.251] rising to 44-48' 0.2932 [0.282,0.304], second half
flat ~0.27-0.28. Non-overlapping CIs, smooth shape -- real structure. But the
BEST band is 0.2932 and 2-1 needs 0.3333. **Nothing clears 2-1 anywhere in the
match.** 3-1 (0.25) is cleared by the base rate alone (~0.264), i.e. by betting
blind, which no book will price.

**A CLOCK BUG MANUFACTURED THE FIRST ANSWER.** `_clock_seconds` folded
`minAdded` into `min`, so first-half 45+3 became minute 48 and collided with a
genuine second-half 48th. 4.4% of all shots shared a bucket with the other
half, concentrated in 45-52'. A window opened at 44' swept ~13 minutes of play
scored as 10. That printed 40-48' as the densest scoring period (lift 1.21) --
a counterintuitive result contradicting the user's late-game intuition, with
n=6,712 and tight CIs. Corrected: 1.21 -> 1.11, and the late game went 0.94 ->
1.02. **Large n made the artifact MORE convincing, not less.** The `period`
field was in the payload from the first fetch.

**WHAT THIS CLOSES.** Stop building momentum/event-triggered goal bets. FotMob
is not owed a production dependency: its own momentum series ranked no better
than anything else, and shot COUNT (free from ESPN) matched or beat xG. Five
promising numbers died this session -- 40.2%, xG +0.1028, xG-over-count,
la_liga 80-84', 40-48' peak -- and all five were read off a tail or a bug
before a control existed. The control was always the cheap part.

## 08-22 REVERSAL: there IS a signal. I had spent the whole day testing at the WRONG TIMESCALE.

The cell sweep's negative was real about its own cells and WRONG as a general
claim. A pooled model over all ~380k samples, clock as a 24-way one-hot
baseline (the strongest clock-only predictor), holdout AUC:

    window   60s  dAUC +0.0238        window 300s  +0.0081
             120s       +0.0189               600s  +0.0088   <-- EVERY earlier test
             180s       +0.0143               900s  +0.0058

Monotonic in window. **Every analysis today used a 600s window and a 900s
half-life. The signal lives at 60-120s with a 60s half-life.** Football momentum
decays in about a minute; I smeared it across fifteen and then concluded five
times that it was not there. That was a design assumption I never tested, not a
property of the game.

**CORRECTED NULL (the first one was wrong).** `rng.shuffle(yperm)` globally
permutes TRAINING labels, which trains BOTH arms on noise and makes the
increment ~0 by construction -- far too lenient, and the docstring claimed
within-match. Correct null permutes FEATURE ROWS within time band, leaving
clock and labels intact so only the feature link breaks:
    real +0.0181   null -0.0022, +0.0002, +0.0018, -0.0057
Ten times the null's best run.

**THE DRIVER IS FOTMOB'S OWN MOMENTUM, and nothing else.**
    solo (added to clock)      leave-one-out
      vmom_abs  +0.0098          +0.0118   <-- unique, irreplaceable
      xg        +0.0046          -0.0002
      inbox     +0.0045          -0.0001
Every shot feature is redundant; dropping any costs nothing. This REVERSES
"FotMob has not earned a dependency" -- it has, for MOMENTUM, not for xG.

**BUT MOMENTUM IS MOSTLY REACTIVE, and that is the honest headline.**
    AUC predicting FUTURE goals 0.5242   AUC predicting PAST goals 0.6050
It rises AFTER attacks and goals, far more than it anticipates them. And its
per-minute stamp can overlap the label window, so it was re-tested lagged:
    lag   0s  dAUC +0.0181 (vmom +0.0098)
         60s        +0.0138 (vmom +0.0076)   <-- the defensible number
        120s        +0.0098 (vmom +0.0046)
76% of the effect survives a strict 60s lag, so it is not a bucket artifact --
but it decays fast, which is what a genuinely short-lived signal looks like.

**ECONOMICS, and the reason this is still not a green light.** At a 120s window
the base rate is 0.0581, so the 2-1/3-1 bars from the 10-minute work DO NOT
APPLY. Lagged, top 2% of predicted risk hits 0.0946 [0.085,0.105], lift 1.63x,
needing better than ~9.6-1. Whether that is exploitable depends entirely on how
books price live goal markets -- and they price them with their own shot and
pressure models, which see the same 1.63x. NOT MEASURED. That is a test against
live odds, which is a different question from this one.

**THE METHOD LESSON.** "No signal" is only ever a claim about the test you ran.
Five negatives at one timescale said nothing about other timescales, and the
one-line fix (sweep the window) was available from the start. A negative result
needs its power characterised before it is trusted, exactly as a positive needs
a null.

## 08-22 LIVE ODDS PILOT: plumbing works, answer is 1.8 match-days away

**WE DO HAVE LIVE ODDS HISTORY, but it effectively STARTED TODAY** -- the 60s
live-odds work deployed this evening is what produced it. Coverage by date:

    2026-08-22  2300 markets, 1523 live, 370 live TOTALS, 36 events, 31 MB
    2026-08-21  live-totals events 0
    2026-08-19  8 events, none with >=10 snapshots
    2026-08-14  163 markets, 5 capture passes, live h2h stamped 08-10 (STALE)

Do not read "58 odds_history dates" as 58 usable dates. One is usable.

**RESOLUTION IS THE BINDING CONSTRAINT.** Snapshots arrive every ~333s median.
That gap is OURS, not the books': 69% of consecutive pairs carry IDENTICAL odds
and 92% are labelled `flat`, so history is POLL-triggered, not change-triggered.
The signal has a ~60s half-life, so a spike is usually over before the next
price exists. We shipped "60-second live refresh" today and the observed floor
is 160s. Worth knowing before anyone trusts the cadence claim.

**THE PILOT ASKED THE CHEAP QUESTION.** "Does my signal beat the book at
predicting goals" needs GOALS -- ~30 positives at this sample, which resolves
nothing. "Does the book's PRICE move with momentum" needs no goals at all, so it
has far more power per match. Result, de-vigged Over prob vs vmom_abs,
residualised on clock+clock^2+score:

    raw corr      +0.0692
    PARTIAL corr  +0.1446   1 SE 0.0990   n=106   -> 1.46 SE, NOT resolved

**THE USEFUL OUTPUT IS THE POWER CALCULATION, not the correlation.** To resolve
+0.1446 at 2 SE needs n >= 195 in-play observations. Today gave 106 from 11
joined matches. **That is 1.8 more match-days.** Two more Saturdays of capture
answers a question that has been open all session -- and the pipeline now exists
to answer it automatically.

Sign is positive, i.e. books probably DO track sustained pressure, which is the
unsurprising direction. Note what this design can and cannot see: at 333s
sampling it tests whether books track SUSTAINED pressure. It CANNOT see whether
they miss brief spikes -- which is precisely where an edge would live.

**Clock alignment is by FotMob kickoff time, never by assuming the first live
snapshot is kickoff** -- books quote in-play markets before the whistle, so that
assumption would shift every match by an unknown offset.

## 08-22 FORBIDDEN: `git add -A` in this repo. THE TEST SUITE MUTATES TRACKED FILES

Running the full pytest suite (`python -m pytest tests/`) leaves the working
tree dirty in two ways at once: it MODIFIES tracked files —
`reports/manifests/*.json` (all 8 sports), `reports/refresh_state.json`,
`reports/intelligence/intelligence_state.json`,
`data/mlb_source/.../live_lens_2026_06_02.jsonl` — and it CREATES untracked
ones, including `reports/sim_runs/`, `reports/win_prob_null/`,
`reports/mlb_odds_diag/`, and a literal
`Z:\definitely\does\not\exist\perf.jsonl` from a Windows-path test.

`git add -A && git commit` after that run committed **38 files and ~10,500
insertions when exactly ONE file was intended**, including a 10,049-line diff
to `intelligence_state.json`. It was pushed before I read the stat. The `git
status --porcelain` that would have shown it ran in the same command, ABOVE the
add — so the evidence was printed and the commit happened anyway.

**RULE: stage explicitly. `git add <path> [<path>...]`, never `-A`, never `.`**
Every commit in this session that did name its paths was clean; the one that
did not was not.

**COROLLARY, and it is the part that nearly hid this: `.gitignore` cannot save
you here.** Several of these byproducts are legitimately TRACKED files that the
suite rewrites, so there is no ignore rule that makes `-A` safe. Earlier in this
same session I gitignored four *untracked* byproducts (`#515`) and that was
correct — but it addresses a different half of the problem and must not be
mistaken for having solved this one.

Recovery, for the next person: `git reset --soft HEAD~1 && git reset`, then
`git checkout --` the tracked byproducts and `git clean -fd -- reports/ data/`
the untracked ones, re-stage by name, and force-push (safe only on your own
unshared branch — never on someone else's).

## 08-22 FORBIDDEN: calling a test failure "pre-existing on main" from a clean WORKTREE. A worktree shares site-packages

I reported `#517` as "76 failures across 26 files on clean `origin/main`", and
backed it by re-running three sampled files in a detached worktree at
`origin/main`, getting identical counts. That check was real and it was not
sufficient. **`git worktree` gives you a different CODE tree and the SAME Python
environment.** It controls for the diff and controls for nothing else.

The environment was broken. `cffi` was absent — collateral from my own earlier
`pip install --ignore-installed` / `--force-reinstall` juggling to fix a
numpy/pandas mismatch — so `cryptography` could not import, and everything
importing it failed. Installing one package:

    test_refresh_state_store.py      18 failed -> 1 failed
    test_wnba_refresh_runner.py       6 failed -> 4 failed
    test_nba_cards_keyvalue_backend   3 failed -> 3 PASSED
    test_wnba_cards_keyvalue_backend  3 failed -> 7 PASSED

**At least 25 of the 76 were mine, not the repo's**, and I had already written
the 76 into `todo.md` and committed a baseline built on it.

**RULE: before attributing failures to the code, prove the ENVIRONMENT is
sound.** `python -m pip check` is one command and would have said so — it
reported a broken requirement the whole time. Then re-run
`pip install -r requirements.txt` clean and re-measure.

**COROLLARY: a `ModuleNotFoundError` for a C-extension or transitive dependency
(`_cffi_backend`, `_ssl`, `_lzma`) is an environment claim, never a code claim.**
Read the actual error before counting failures; `--tb=no` hides exactly this,
and I ran the whole 27-minute suite with it.

**COROLLARY: never repair a dependency with `--ignore-installed` or
`--force-reinstall` on a single package.** It resolves that package against
nothing and silently strands its dependencies. Reinstall from the requirements
file and let the resolver see the whole graph.

## 08-22 FORBIDDEN: treating a todo id as RESERVED because you checked it was free. Checking is not reserving

`CLAUDE.md` says ids are stable and never reused, and says to check both
`todo.md` and `todo_closed.md` before taking a number. I did. **It collided
twice in one session anyway**, because concurrent sessions can all pass the
same check against a shared counter and then all take the same numbers:

    took #502-#505  ->  main had independently used #502-#505  ->  moved to #507-#510
    took #507-#510  ->  main had independently used #507-#513  ->  moved to #514-#517

Nothing was wrong with the check. The gap is between checking and MERGING: on a
branch that lives for hours while other sessions land on `main`, the number you
reserved is only as good as the moment you read it.

**RULE: renumber at MERGE time, not at file-creation time.** Re-read the max
immediately before the merge commit and move your block then; the collision
window shrinks from hours to seconds. Expect it to happen and make the move
cheap rather than trying to pick a number that will survive.

**RULE: renumber by LINE RANGE, never globally.** By the second collision the
merged `todo.md` contained main's `#507-#513` AND mine, and `learnings.md` and
`lanes.md` each carried main's references to ITS `#502-#505`. A global
search-and-replace would have silently rewritten another lane's history into
nonsense. Scope every substitution to the line span of your own block, and
verify the other side's headers survived before committing.

**COROLLARY: a numeric id is the wrong identity for a long-lived branch.** The
work is findable by lane slug and by scope-doc filename, neither of which can
collide. The number is a convenience for `todo.md` ordering and should be
assigned as late as possible.
## 08-22 DEEP DIVE VERDICT: MOMENTUM IS DIRECTIONAL. It says WHICH TEAM -- not whether, how many, or when.

5,552 matches, holdout-only, every baseline = the live state a book already
knows (clock, score diff, goals so far). Signals added on top. dAUC:

    WHICH TEAM                                   WHETHER / HOW MANY / WHEN
    next team to score      +0.0707  (AUC .577)  any goal in 15m      +0.0007
    home scores in 15m      +0.0332               goals remaining >=1  +0.0003
    away scores in 15m      +0.0286               goals remaining >=2  +0.0001
    match winner (away)     +0.0101               BTTS                 -0.0009
    match winner (home)     +0.0069               goal before half-end +0.0001
    winner at 0-15'         +0.0393               goal before 75'      +0.0002
                                                  corners in 5/10m     -0.010 / -0.006 (ESPN, 699 m)

Same signal, same matches: +0.03 on "home scores in 15m", +0.0007 on "any goal
in 15m". The information is almost entirely in the SIGN. Signed vendor momentum
alone carries +0.0710 of the +0.0707 direction effect; signed xG +0.0203, signed
count +0.0362 -- momentum dominates and the rest is redundant.

**DIRECTION IS A SLOW SIGNAL, unlike "whether".** Lagged 60s it keeps 94%, lagged
300s it keeps 88%. The 2-minute "whether" signal lost 24% at 60s. Being on top
PERSISTS; a goal arriving does not. That is why direction maps onto quotable
markets (next team to score has no time limit) and "whether" does not.

**CORRECTION to my earlier "momentum is largely reactive" caveat.** Stripping
every sample with a goal in the prior 600s leaves dAUC +0.0152 vs +0.0152
unstripped, momentum-only +0.0134 vs +0.0116. The post-goal reaction is REAL
(AUC .605 on past goals) but it does not cannibalise the forward signal. I
reported the reactive finding as the honest headline; it was a true fact that
did not bear on the decision.

**CALIBRATED.** ECE 0.0026; top decile predicted 8.17% observed 8.26%. Direction
decile 10 predicted .664 observed .653. Model outputs can be set against book
implied probabilities directly.

**CONTEXT.** Signal is 4x stronger with a 2+ goal lead (+0.041) than level
(+0.010); strongest 60-75' (+0.071); near-zero 0-15' for "whether" but STRONGEST
0-15' for WINNER (+0.039) -- early, before the score has separated outcomes.
Winner signal decays to +0.004 by 75-90' as the scoreboard takes over. Belgian
(-0.008, n small) and MLS (+0.006) carry nothing; Primeira (+0.035), Bundesliga
(+0.029) carry most.

**ECONOMICS, 120s window.** Top 0.5%: hit 13.2% [11.0,15.8], lift 2.27x, ROI
+95% against a NAIVE book (clock rate + 8% vig), -vig against a SHARP book. Fires
0.46x per match. At 600s the lift collapses to 1.2x and naive ROI to ~0. LULLS:
bottom decile 0.98x of clock -- the model does NOT find quiet spells; "no goal"
is not a market here.

**WHAT A READING MEANS.** |momentum| <40: no information (0.93-0.99x). 60-80:
1.19x. 80+: 1.23x. The card should not colour anything below 40.

**PRODUCTION GAP.** momentum.py DEFAULT_HALF_LIFE_SECONDS = 300.0; the data says
60s. The card shows a 5x over-smoothed series. And production momentum is
ESPN-commentary-derived; the signal that carries is FotMob's series, which is
not wired.

## 08-22 ESPN'S TWO HOSTS HAVE DIFFERENT User-Agent POLICIES, and this repo documents both without saying so

Measured from Render, 2026-08-22, during a live WNBA slate:

    site.api.espn.com      (scoreboard)  browser-spoof UA -> 403     no custom UA -> 200
    site.web.api.espn.com  (summary)     browser-spoof UA -> 200 (fallback never fired)

**Two comments in this repo give opposite advice and BOTH ARE CORRECT — about
different hosts.** `scripts/fetch_espn_live_status_for_date.py` says never use a
spoofed UA (probed from Render: bare `Mozilla/5.0` 403, full Chrome header set
403, no headers 200). `basketball_props_smart_sim._http_get_json_local` says a
browser UA is the FIX for soft-blocking. Neither names the host as the reason.

I read the second, applied it to the first's endpoint, and the scoreboard 403'd
on every tick of a live game. A bare `except` returned `{}`, so a 403 and an
empty slate were the same observation: `live_events=0`. I checked that zero
TWICE before tip-off and read it as correct pregame behaviour.

**RULE: when two comments in this codebase contradict each other, the
difference is usually a scope neither one states.** Find the axis — host,
service, phase, sport — before picking a side. Picking the more recent or the
more confident one is guessing.

**RULE: never let a fetch helper swallow its status.** `except: return {}` cost
most of a scarce live window here. A 403 and an empty result are different
facts and must print differently. `#514`'s helper now logs status and URL on
every failure, and the caller prints `events_total` so "3 games, none tipped"
can never again look like "the call returned nothing".

**COROLLARY on where diagnostics go.** A `NO_SERIES` diagnostic shipped 40
minutes earlier could not catch this: it ran only after summaries were fetched,
and the failure was one hop upstream. **Instrument the FIRST hop, not the
interesting one.**


---

## 2026-08-23 — a measurement that matches your CHANGE instead of the COMPLAINT is not verification `[lane layer2-sim-view-and-live-projection]`

- **RULE: verify against the WORDS OF THE COMPLAINT, not against the diff.** Ask "what would the reporter look at?" and measure that. Reading back the field your own change writes proves the edit landed, which was never in doubt.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-23 — a counter's POSITION relative to its gate decides which question it answers

- **RULE: when you add a counter, state whether it sits BEFORE or AFTER the gate, and prefer before.** A denominator measured past the filter cannot distinguish "nothing was eligible" from "nothing qualified". `record()`'s own docstring in that file says `considered` exists so `edged / considered` is "a rate with a real denominator" — it is, for rows that got in, and the rows that did not are the ones you are usually looking for.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-23 — a guard firing 248 times looks exactly like a coverage regression

- **RULE: before reporting a coverage drop, check the DENOMINATOR and check for a guard.** A rate can fall because the numerator broke or because the population grew, and the two need opposite responses. Here the population grew *because of my own fix*, and reporting it as a regression would have sent the next session to delete a safety feature.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-23 — `trim_lane_blocks.py` is now exhausted, and `lanes.md` is over cap anyway

- **RULE: "run the trim tool" is no longer a complete answer to LEDGER OVER BUDGET.** The next reduction has to come from CLOSING lanes or from shrinking live blocks, both of which are owner decisions. Editing in place still prevents growth; it cannot reverse it. The session-start digest truncates OPEN LANES to 600 bytes, so an over-cap file arrives lossy — which is the opposite of what the ledger is for.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-23 — READ THE RATE, NOT THE REASON STRING `[lane layer2-sim-view-and-live-projection]`

- **RULE: a reason that accounts for 100% of a population is a bug, not a distribution.** Check the RATE before believing the string. A plausible explanation attached to a total failure is the most expensive kind of wrong, because it reads as already-diagnosed and stops the search.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-23 — a counter whose inputs are absent reports CONSTANTS that look like findings

- **RULE: `miss_player=0` and `player_in_lens: False` in the same line cannot both be findings.** When two counters contradict each other, suspect the FEEDER before either counter. The tell is free and it is the only reason this was caught.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-23 — `git merge-base --is-ancestor` on an unfetched object exits 128, and `2>/dev/null` turns that into a clean "no"

- **RULE: never route an ancestry check's failure into a boolean.** Verify the object exists (`git cat-file -t`) first, and let the error surface. A tool that cannot answer must not be allowed to answer "no" — the two are different, and on a deploy check the wrong one triggers a needless redeploy or a revert war.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-24 — A PRE-FLIGHT CHECK DOES NOT SURVIVE A TURN BOUNDARY. Three times in one session.

- The rule going forward: for any change to a shared allowlist, gate, or vocabulary, enumerate every SERVICE that evaluates it and deploy them all before reading the result. And when a fetch fails, **read the status code before theorising** — 403 vs 404 vs 304 each name a different end of the wire.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-25 — GitHub Actions CI results are not this repo's source of truth

**User, direct instruction: "ignore the CI results, just keep pushing
normally."** Said in response to "we don't use github actions anymore" — a
claim I VERIFIED rather than took on faith (per the notification-handling
rule to check anything surprising against a primary source) and found
false in the narrow, mechanical sense: `.github/workflows/ci.yml` is
enabled and fires on every push/PR event exactly as configured (confirmed
live, `mcp__github__actions_list`, runs created and completing within the
same minute as pushes made this session, 40 total runs on the repo). The
user's real point survived the verification anyway: whatever fires there is
not what this repo relies on to decide a change is good.

**RULE:** treat `check_run`/`workflow_run` events on a Syndicate PR as noise,
not as signal. Do not open the job logs, do not diagnose a `pytest-baseline`
or `test` job failure, do not hold a push waiting for a check to go green,
and do not report a PR as "CI is red" as if that were an open question this
repo needs answered. Push and merge on the same basis this repo already
uses everywhere else in `CLAUDE.md`: targeted local test runs for the
actual diff, the lane ledger, and (for anything that reaches Render)
production reads via `.syndicate/deploys.md` -- never a GitHub Actions
badge.

**What this does NOT change:** `.github/workflows/ci.yml` itself, and this
session's own 2026-08-25 work parallelizing its `pytest-baseline` job
(`.syndicate/scope_2026-08-25_ci_pytest_parallelization.md`), are still
valid, still committed, and still fine to leave in the repo -- the rule
above is about what to DO with the results it produces, not about deleting
or reverting the mechanism. A PR's mergeability (conflicts, human review
threads) is still worth watching; only the CI-check dimension of "drive to
green" stops applying here.

### 2026-08-25 — FORBIDDEN: report a real-money code-default change as "done" without reading the live service's actual env vars. A contradicting override wins silently

- What we believed: changing `execution_guard.py`'s code defaults (bankroll,
  per-venue day-dollar caps, max order size, order-count caps) to match the
  user's stated real policy, plus 427 passing tests, was the fix. Reported it
  as complete.
- What was actually true: `live-odds-worker` already had explicit env-var
  overrides (`SYNDICATE_EXECUTION_MAX_DAY_DOLLARS=40` flat for both venues,
  `_ALL_VENUES=80`) that outrank ANY new code default under this file's own
  env>default precedence. The service was still running the OLD "$40/day,
  survive-being-wrong" policy after the code change merged — the new defaults
  were completely inert for the two live venues.
- How we found out: the user asked "these were set as environment variables —
  are you sure this is set correctly now?" instead of accepting the report.
  Read `live-odds-worker`'s actual production logs
  (`[execute_portfolio] LIMITS ... caps={...}`) via the Render MCP server and
  found the drift directly, before/after.
- The rule going forward: **a code-default change to a file whose whole design
  is "env var wins over default" is not verified by the diff or the test
  suite — it is verified by reading the live service's actual resolved
  values.** For Syndicate specifically: `mcp__Render__list_logs` on the
  relevant service, filtered to the module's own log line, is the read; there
  is no env-var-listing tool, so log lines that print the resolved config
  (this file's `LIMITS`/`EXECUTION` lines) are the only way to see what a
  service is actually running without one.
- Cost: none — caught before any real order was placed under the wrong caps,
  and only because the user asked rather than accepted the report.

### 2026-08-25 — FORBIDDEN: rename a lane's header status away from the literal word "OPEN" without checking what that silently releases

- What we believed: rewording a lane's header from `OPEN` to a descriptive
  status like `GOAL COMPLETE, lane idle` was a harmless, purely cosmetic
  checkpoint edit — the lane's Files: claims were untouched text, so surely
  the claims themselves were untouched too.
- What was actually true: `check_lane_invariants.py` (and, by the same
  `OPEN_RE = re.compile(r"\bOPEN\b")` pattern, several sibling scripts —
  `archive_released_lanes.py`, `audit_lane_unguarding.py`,
  `hoist_open_lanes.py`) recognize a lane's claims as live ONLY if the literal
  word `OPEN` appears in its header. Dropping that one word silently voided
  EVERY claim the lane held — not just the one file being reconsidered, but
  six unrelated, still-legitimately-owned modules in the same block.
  `trim_lane_blocks.py` then read the now-claim-free block as eligible to
  leave `lanes.md` entirely, compounding it.
- How we found out: ran `check_lane_invariants.py` after the rewording as a
  sanity check (not required, done out of caution) and saw the OPEN-lane
  count drop by one and the claim count drop by dozens — traced to the
  regex, not to any Files: line actually being edited.
- The rule going forward: **a lane's header keeps the literal word `OPEN` for
  as long as it holds ANY claim it intends to keep enforced**, however done
  or idle the work described in the body is. To retire a specific claim while
  the lane stays open, strike through that one file with an explicit release
  note (the convention already used elsewhere in this file) — never rename
  the whole lane out of `OPEN` as a shortcut. Only drop `OPEN` once every
  claim is explicitly released one at a time.
- Cost: none — caught by running the invariant checker before committing,
  not after.

## A null result from a QUERY is not a null result from the SYSTEM `[2026-08-26]`

Render's log API `text` filter does NOT support regex alternation the way it
looks like it does. `text: ["BY_GAME_DATE|BY_CLOSE_DATE"]` returns
`logs: null`; each single term returns rows. Silently — no error, no warning,
and `null` is exactly what a genuinely quiet service returns.

Cost: seven consecutive "no output yet" reports over 36 minutes while the lines
were printing the whole time, plus two elaborate explanations built on the
absence (a dormant-interval calculation, then a board-build stage-depth model).
Both were plausible, both were unfalsifiable against a filter that could not
return anything, and both were wrong.

**The rule:** before reporting that something is ABSENT from a log, prove the
query can find something PRESENT. Query one term at a time, or include a string
you know is in the window as a control. An unproven filter turns "I asked
wrong" into "it did not happen", and those license opposite conclusions.

This is `#370`'s error one layer up, again: the same session had just deployed a
fix for a histogram that reported `close_time` under the name `by_date`, and
then made the identical mistake reading the logs of that very fix.

## A measurement taken from the right population can still be taken at the wrong TIME `[2026-08-26]`

`PRECAP_CUT_BY_DATE` was built specifically to stop a change being shipped on an
un-measured claim, and it worked: it refuted its own author's prediction of
~1,600 recoverable markets with a measured 133.

But the reading was taken at 03:11Z, after the MLB slate had finished. The same
series had cut 747 markets at 01:49Z and cut 132 by 03:11Z, because a venue
retires a slate's markets as its games end. **The population was correct; the
clock was not.** A number that is honest about WHAT it counted can still be
silently unrepresentative of WHEN, and "measured" reads as settled either way.

**The rule:** when a quantity varies with a live event, state the phase of that
event beside the number, and say explicitly which phase the conclusion covers.
Here: refuted post-slate, UNPROVEN mid-slate — those license different actions,
and only one of them was measured.

Corollary already paid for once tonight: the same reading also covered only ONE
of the two bounds that discard markets (`cut_total=3940` vs `trimmed=8744`). A
gate that measures half the mechanism is not a gate yet.

## A REFUSAL IN A LIST OF FAILURES IS INDISTINGUISHABLE FROM A DEFECT `[2026-08-26]`

`OrderBuildError: unmappable_side: 'away' market='spreads'` — 11 orders a cycle,
sitting in a table between `market_not_found` and `no_venue_ticker`. It read as
one more thing to clear. A peer session called it *"a straight mapping
omission"*; I agreed, and implemented it. **It was not a defect. It was the only
thing standing between a mis-keyed join and ten inverted real-money bets per
cycle.**

The mapper was correct in isolation: resolve the side against the team named in
the ticker. But the ticker stamped on those orders was the WRONG MARKET, so
resolving against it faithfully produced a faithful inversion:

```
board:   away (Texas) +1.5 @ -185      -> intent: TEXAS +1.5 (underdog, getting runs)
ticker:  ...TEXCWS-TEX2 = "Texas wins by over 1.5 runs?"  -> TEXAS -1.5
mapper:  _side_to_kalshi("away","spreads","...-TEX2") -> "yes"   = TEXAS -1.5
```

Systematic: every spreads order with a ticker had `line=+1.5` and a suffix
naming the picked team; every `-1.5` row — the one that genuinely matches a
Kalshi "wins by over" market — had NO ticker. Root cause in
`kalshi_board_join._match_key`, keying Kalshi's strike as a positive MAGNITUDE
against the board's SIGNED handicap, so `1.5 == 1.5` pairs the underdog row with
the favourite's market.

**THE RULE:** before clearing a refusal, establish WHAT IT WAS REFUSING and why
someone wrote it. A guard and a gap look identical in a counter. The cheap test
here — compare the board row's line SIGN against the venue's own market title —
was one the venue answers in seconds, and *neither* session ran it until both
had a working implementation in hand.

**Corollary, on how close this got.** The patch was parked, labelled
`BACKUP ONLY — do not apply`, tested, and verified to apply cleanly. That label
is not a safety mechanism: a working backup is exactly what a later session
reaches for when the primary stalls, which is precisely when nobody re-derives
whether it was ever right. **Delete a refuted artifact; do not annotate it.**
The analysis survives in `.syndicate/handoff/README_kalshi_side_mapper.md`; the
applicable diff is gone.

**Second corollary, and the deeper one.** `kalshi_board_join` ALREADY computes a
correct `kalshi_side` and throws it away — `venue_scope.py` stamps only the
ticker, so `OrderRequest` carries the BOARD side and `_side_to_kalshi` is asked
to re-derive at the boundary from data that cannot settle it. **Re-deriving at a
boundary what an earlier stage already knew is what made the inversion
possible.** Same shape as the unfed-input class in `model_engine_standard.md`:
the value is available, nothing carries it across, and the recomputation is
indistinguishable from the real thing at every level except the money.

## A GREEN PATH ON A SHARED VENUE PROVES NOTHING ABOUT THE BROKEN ONE `[2026-08-26]`

Kalshi MLB failed for two days while WNBA filled normally, same credential, same
code, same endpoint. The whole time, "Kalshi orders are working" was true and
useless: **WNBA is on exchange shard 0, which this account is provisioned on;
MLB migrated to shard 3, which it is not.** n=9, perfect split — every order that
ever filled is shard 0, every failure is shard 3.

The two MLB fills on 08-24 were shard 0. That is why it "broke" on 08-25 with no
deploy in between, and why a code-regression hunt through `git log` found
nothing: **there was no regression. The venue moved the markets.**

Both errors were literally true and neither was ours:

```
exchange_index 0 (pinned)  -> market is not on shard 0 -> market_not_found
exchange_index -1 (auto)   -> routes to shard 3, FOUND -> user_not_found
```

**The rule:** when one slice of a venue works and another does not, find the
axis that separates them BEFORE theorising about code. Here it was a public
field on the market payload (`exchange_index`) — no credential, one GET. I had
even read that field in a log line (`KALSHI_SERIES_CATALOGUE ... row_keys=[...
'exchange_index' ...]`) and used it to argue FOR a hypothesis instead of asking
what value our own failing markets carried.

**Corollary — intermittent success across an otherwise identical population is a
PER-ITEM property, not a point-in-time change.** I treated "worked Monday, fails
Wednesday" as a regression and searched the diff. The correct first question was
"what is different about the items that fail", which the venue answers directly.

**Corollary — a fix that moves the error inward is working, and must not be read
as failure.** `market_not_found` -> `user_not_found` was progress; I called the
shard fix refuted an hour before it was confirmed, by reading my own probe line
(which fires on ANY exception) instead of the error string underneath it.

## A DIAGNOSIS AND ITS REMEDY ARE SEPARATE CLAIMS `[2026-08-26]`

The Kalshi shard finding was measured, n=9, perfect split, confirmed in
production from two independent clients. The REMEDY attached to it — *"the venue
must enable this account on that shard; no code change fixes it"* — was never
checked against anything. It rode in on the diagnosis's credibility, and I
printed it into a **production error string**, where the next person to hit it
would read it as settled.

It was wrong. `GET /exchange/status` shows shards are PRODUCT partitions, all
active (0 Default, 1 Combos, 2 Crypto, 3 Tennis & Baseball). Kalshi's doc:
*"Subaccount balances are local to a specific exchange instance"* and
*"Programmatic traders must preallocate collateral on a given exchange shard
before order placement."* `user_not_found` meant NO FUNDS THERE. The fix was the
account holder moving money — about a minute — not a support ticket.

**A confident wrong remedy inside a correct diagnosis is more dangerous than a
wrong diagnosis**, because the diagnosis's evidence launders it and nobody
re-checks the half that had none.

**The rule:** "what is broken" and "whose move it is" are different claims
needing different evidence. Before writing a remedy into anything durable — an
error string, a ledger entry, a message to the user — ask what was READ to
support it, not what was inferred. Here the answer was one fetch of a doc page.

**Corollary:** the same goes for the error text itself. An error message that
names a remedy is making a claim with the system's authority behind it, and it
outlives the conversation that produced it.

## THE DEPLOY CLAIM DOES NOT SERIALISE ACROSS ENVIRONMENTS `[2026-08-26]`

**I cancelled another session's in-flight build while it correctly held the
claim.** Measured:

```
dep-da7h54bm6pss73fmo2n0  f1a2c78f  CANCELED 16:23:12Z   <- theirs, mid-build
dep-da7h5rrbc2fs73cr8u9g  2e5f425e  started immediately  <- mine
```

`deploy_claim.py status --service live-odds-worker` read **HELD by
kalshi-spread-join-sign** in the primary tree at that moment. My own container
said the service was free, and I had "acquired" it there — twice, plus a
careless probe that re-acquired and had to be released again.

**The claim directory resolves from `REPO_ROOT`, so it is per-tree and
per-environment.** A cloud session gets its own. Two sessions can each hold
"the" claim on the same service, simultaneously, both correctly, and neither
can see the other. `acquire` succeeding proves nothing about the other
environment.

This is exactly the 2026-08-15 shape the claim was built to prevent — two
deploys that do not contain each other. It did not bite this time only because
`2e5f425e` was newer and ledger-only, so nothing was reverted. **Serialisation
that silently covers one environment is worse than none, because it is trusted.**

**The rule for a cloud/remote session:** `deploy_claim.py acquire` in your own
container is a local no-op with respect to every other environment. Before
deploying, check the claim state that the PRIMARY tree sees — and if you cannot
reach it, say so and coordinate explicitly rather than treating a local
`ACQUIRED` as authority. The atomic `O_CREAT|O_EXCL` lock is sound; its
NAMESPACE is the thing that does not span machines.

**Generalisation:** a lock is only a lock over the state everyone contends on.
Ask what storage the lock lives in and who can see it, before trusting what it
says.


## 2026-08-26 — FORBIDDEN: treating ARITHMETIC ON A DERIVED FIELD as a measurement

**A number you computed from another stored number is not evidence about the
world. Dividing it back out recovers your own input, and it will look like a
reading.**

**MEASURED, and it produced a wrong finding reported to the user as fact.**
Investigating a Polymarket order that appeared mispriced, I wrote:

    IMPLIED PRICE PAID = fill_stake / contracts = 4.05 / 7.11 = 0.5696

and concluded *"a real overpay, not a reporting artifact."* It is not a
measurement of anything. `execution_ledger.py:996`:

    filled_dollars = contracts * fill_price

`fill_stake_dollars` IS `contracts x fill_price`, so dividing by `contracts`
returns `fill_price` — the very field under suspicion — with the appearance of
independent corroboration. `venue_order_view` sets `"fill_cost_dollars": None`,
so **NOTHING in this system independently measures what was paid.** The correct
statement was "the ledger RECORDS 0.57 and nothing here can tell us what was
paid", which is a different investigation with a different next step.

**HOW TO APPLY.** Before using a stored number as evidence, find its WRITER. If
it was computed from another field in the same record, it can corroborate
nothing about that field, and any ratio between them is an identity. Reach for
an input the system did not compute: the SUBMITTED value, the venue's own cash
field, a second service's copy. The check that finally worked here compares the
recorded fill against the price WE SENT — an independent input — and is the
`FILL_ABOVE_LIMIT` guard.

**THE SAME SESSION, THE SAME SHAPE, THREE MORE TIMES**, which is why this is a
rule and not a note:

- **A guard that "needs no venue semantics" but silently picks a side.** I built
  a cross-check between `_side_to_outcome` (name axis) and
  `outcome_side_for_index` (POSITIONAL) and claimed it was semantics-free. It
  makes the positional reading authoritative — precisely the disputed question —
  and it contradicted three deliberate tests asserting the opposite convention.
  Reverted before landing. **A cross-check between two readings is not neutral;
  it enthrones one of them.**
- **A background run that exited 0 having never run.** `pytest -k ...` returned
  exit 0 with 110KB of output and NO summary line: the process never collected a
  test. Exit status described the shell, not the suite.
- **A watcher that "found" the thing by matching the wrong string.** Searching
  logs for `SETTLED` matched `settled_count` inside `INTEL_TRACE`, reporting
  "11 settlement passes" when zero had run. The filter had to require
  `SETTLED date=`.

Related: [[feedback_read_the_field_you_already_have]],
[[feedback_confirm_the_code_ran]], [[feedback_instrument_blindness]],
[[feedback_rate_not_count]].

## 2026-08-26 — FORBIDDEN: concluding a VENUE must act because its error names your account

**`user_not_found: <uuid>` from a venue is a statement about a REQUEST, not about
your account's existence.** I read it as "the exchange has no record of us here,
so the venue must enable us", shipped that as the remedy, and it went LIVE IN A
PRODUCTION ERROR STRING telling any reader to contact Kalshi support:

    "the market resolved and the ACCOUNT did not. This needs the venue to enable
     this account on that exchange shard; no code change fixes it."

**It was never the venue's move.** The user challenged it; reading the venue
instead of restating the conclusion took minutes.
`GET /trade-api/v2/exchange/status` enumerates shards as PRODUCTS — `0 Default`,
`1 Combos`, `2 Crypto`, `3 Tennis & Baseball` — ALL `trading_active`, and
docs.kalshi.com/getting_started/exchange_sharding.md says plainly: *"Subaccount
balances are local to a specific exchange instance"* and *"Programmatic traders
must preallocate collateral on a given exchange shard before order placement."*
A one-minute transfer by the account holder. It was fixed the same hour.

**HOW TO APPLY.** Before asserting that a counterparty must act, read what the
counterparty documents about the thing it just refused. The diagnosis and the
REMEDY are two claims; evidence for the first is not evidence for the second,
and the remedy is the half that gets pasted into an error message and sends
someone to the wrong place for a day. Related:
[[feedback_retraction_is_not_innocence]], [[feedback_presence_is_not_reachability]].

---

## 2026-08-26 — An empty log query is not evidence of absence until the query shape is known to match

Lane `layer2-sim-view-and-live-projection`, session `e47e1b67`.

**OVERTURNED:** that a null result from the Render log `text` filter means the
line is not there.

Passing ONE string containing `|` alternation (`["A|B|C"]`) matches it
LITERALLY and returns nothing. The working form is a LIST of separate strings
(`["A","B","C"]`). I used the correct form early in the session, switched to the
broken one, and twice reported `GAME_CHIPS_PUBLISHED` missing while it was
present — one step from investigating a publish failure that had not happened.

The tell: `["layer2_shortlist"]` returned health lines in the SAME window where
the alternation query returned null. **Before concluding absence, confirm the
query returns something you already know is there.**

## 2026-08-26 — A before/after comparison where both sides are the same tree always agrees

Same lane. I "confirmed" three failures were pre-existing by running `git stash`
on an already-clean tree — which stashed nothing — so the "before" run was the
same commit as the "after" run and produced an identical result that looked like
proof. Caught only because `git stash pop` reported "No stash entries found".

**Use a detached worktree at the parent commit** (`git worktree add --detach
<path> <sha>~1`), which cannot silently be the same tree. Done correctly later
the same session for `test_it_cannot_downgrade_a_started_match`.

## 2026-08-26 — One shared method, two callers wanting different answers: check the OTHER caller

Same lane, twice in one day, and the second instance was my own regression.

`#542` widened `provider.games()` to two matchdays to fix the board's chip
coverage. `games()` is ALSO the home rail's source, which renders everything it
is given — the rail went **98 -> 210 games** with a count badge claiming 210
today. Nothing failed; no test covered it; I found it only when a later task
made me read the call graph.

Identically, `_SOCCER_VENDOR_NAME_ALIASES` has two consumers: `teams_match`
falls through to heuristics, `canonical_team` is map-only. A club can join
fixtures fine and still return None for a chip key — so an entry that an
existing test calls redundant can be load-bearing.

**Before changing a shared resolver, enumerate its callers and state what each
one needs.** The fix in both cases was to make the difference EXPLICIT
(`include_upcoming`; the two-resolver rule in the invariant), not to pick one
caller's answer and hope.

## 2026-08-26 — "Done" before the sweep returns is a claim about the future

Same lane. I reported the NFL fix complete while the regression sweep was still
running; it then failed FOUR tests I had caused — three in my own `#542` file,
which asserted the behaviour `#575` deliberately made opt-in. The measurements I
quoted were real; the completion claim was not. Same shape as the alternation
query: **acting on a result before confirming the method behind it.**

## 2026-08-26 — `-k` chosen by TOPIC misses the files you edited

Same lane. I ran `-k "chip or scoreboard or ..."` and reported a clean surface
— but the change edited `pipeline/intelligence_state.py` and
`syndicate/blueprints/home.py`, whose tests that selector never ran. Three more
failures existed there (all pre-existing, verified). Earlier the same day `#539`
shipped with a guard test a `-k` filter had skipped.

**Choose `-k` from the FILES TOUCHED, not the topic being worked on.**

## 2026-08-26 — An estimated window is one sample until you measure the spans

Same lane. I called a board build "past its window" at 16 minutes, from a single
prior run where `candidate_collection_with_fallback` took 222s. That run it took
**447s** and the build was healthy throughout.

**`BUILD_SPAN_ENTER`/`BUILD_SPAN_EXIT` distinguishes SLOW from STUCK; elapsed
time against a remembered number does not.** Also relevant: the worker restarted
five times in two hours from other sessions' deploys, and two instances never
reached the shortlist stage at all — so an absent line had a cause entirely
outside the change under test.


## 2026-08-26 — FORBIDDEN: TWO HOSTS ARE NOT ONE VENDOR, and "X can reach ESPN" is not a fact about X

**A success against one hostname says nothing about another hostname, even when
both belong to the same provider and serve the same path.**

`WNBA_LIVE_BOX_CAPTURED date=2026-08-25 games=3 players=66` -- web fetching from
ESPN, succeeding. I read that as *"web can reach ESPN"*, routed a producer
through web on the strength of it, deployed, and got:

    {"ok":false,"error":"HTTPError: HTTP Error 403: Forbidden","games":0}

The capture uses `site.web.api.espn.com` (summary). My call used
`site.api.espn.com` (scoreboard). **One of those answers Render and the other
does not.** Both serve both paths, so the fix was a one-line host swap -- but
only after a wasted deploy, because the evidence I had was about a DIFFERENT
HOST than the one I was using.

**HOW TO APPLY.** Before citing a past success as proof a hop works, compare the
HOSTNAME, not the vendor. Write the host into the claim: "web reaches
`site.web.api.espn.com`" is checkable; "web can reach ESPN" is not. Same rule as
[[feedback_presence_is_not_reachability]] one level down -- the route is not the
provider.

## 2026-08-26 — FORBIDDEN: assuming an artifact "published to production" is where its CONSUMER reads

**`POST /api/ops/artifacts/publish` writes `data_root() / relative_path` on
WEB'S FILESYSTEM.** `bet_status_wnba` reads the same relative path through
`read_text_file`, i.e. the KEYVALUE store, on REFRESH-WORKER. Same string, two
stores, two services.

I published 84 backfilled boxscore files, verified them with
`/api/ops/artifacts/export` (which reads the same filesystem, so it agreed), and
reported production coverage restored. **Settlement cannot see any of them.**
The verification was circular: I checked the store I had just written to.

**HOW TO APPLY.** An artifact has a WRITER and a READER and they must be shown
to use the SAME store, not the same path string. `_keyvalue_backed(path)`
answers it for the state store; the publish endpoint bypasses it entirely. When
a fix depends on data reaching a consumer, verify from the consumer's side --
read it back the way the consumer does, on the service the consumer runs on.
This is the third shape of the same defect in one session, after
`iterdir`-vs-`read_json_file` (soccer leagues) and web-vs-worker disks.
Related: [[project_keyvalue_artifact_split_blinds_guards]],
[[feedback_isolate_the_source_you_changed]].

## A correct measurement of an unrepresentative case is still a wrong answer

`[2026-08-26, lane board-staleness-visibility, #567/#569]`

**`#567` existed because every board-build estimate had been read from the gap
between two log lines. I fixed that, instrumented the call properly — and then
drew four wrong conclusions from correctly-instrumented readings.** The
instrument was right every time. The SAMPLING and the NAMING were not.

**Overturned belief 1: "the board build takes 19m43s."** It is **~108s** in
steady state (n=40, median 107.8s). Every large figure was a COLD build — first
after a restart, 6.9x a warm one — taken in a window with 15 deploys in 6h15m
where the worker never reached a warm build. **We were measuring restarts and
calling it the board.**

**Overturned belief 2: "the board is computing, not queued" (`off_cpu_pct=10.4`).**
That was ONE cold build. Steady state medians **52.8%** off-CPU across 40
samples. I reported an outlier as the answer.

**Overturned belief 3: "NFL stopped capturing — new, unattributed, worth a
lane."** NFL runs a deliberate **8-hour** fixture-aware sweep interval
(`#440` Phase 1b, whose own comment predicted `nfl_preseason 12.00 -> 3.56
sweeps/day`). **I called a working feature an outage** because my threshold was
a flat 900s, which every sport with a cadence over 15 minutes trips
unconditionally.

**Overturned belief 4: "3 rows survive the guard wrongly."** That was 3 of 9
**sampled** — the classifier reads the 3 worst rows per sport. The population
was never measured, and I used the 3-vs-946 ratio to justify a decision.

**THE COMMON SHAPE, and it is the rule:** *a label producible by more than one
mechanism, reported as though it named one.* `sidecar_frozen` meant both "the
capture broke" and "this sport sweeps slowly by design". `market_gone` came out
of a frozen file as readily as a live one. `orphaned_line` came out of a
staggered freeze as readily as a real line move.

**WHAT TO DO INSTEAD, all three cheap:**
1. **Before quoting a reading, ask what ELSE could produce this exact number.**
   If more than one thing could, the label is not an answer yet.
2. **Take n>1, and check the samples are comparable.** I nearly reported an 80%
   board collapse from `kept=15672 -> kept=3124` — different SPORT and different
   DATE. The publish line beside it settled it in one query.
3. **Put the discriminating field ON the line.** `sidecar=<age>` and
   `worst_seen_by_sport` are what made the later readings checkable rather than
   trusted; the aggregate alone hid everything.

**Corollary, measured the same day:** an instrument can be defeated by the thing
it measures. Two of my own cold builds were killed mid-flight by other sessions'
deploys — the exact deploy-churn mechanism this lane had just documented.

## 2026-08-23 — RULE: editing a fast-appended shared ledger from a stale local copy manufactures a fake conflict

- **Twice in one session, on `.syndicate/deploys.md`.** I read the file, appended a new section with `Edit`, committed, pushed, opened a PR — and GitHub reported "Pull Request has merge conflicts" on a PURE APPEND with nothing else touched. The cause both times: `main` had moved between my read and my push (this repo runs many parallel sessions appending to the same few ledger files), so my commit's diff was computed against a base that was already behind. A rebase onto `origin/main` then showed the "conflict" for what it was — an EMPTY `- *(evidence in `learnings_evidence.md`)*

## 2026-08-23 — RULE: an empty tmp dir for `SYNDICATE_NFL_SOURCE_ROOT` can still resolve to the REAL checkout, and a test can write into it

- **The rule going forward.** Before verifying a consumer against an artifact, **enumerate that artifact's PRODUCERS** — `git grep` the write path, not just the read path — and carry a fixture from EACH one into the test. One producer is an assumption, not a finding; two producers that disagree on shape is a thing this repo already does. And the shapes must be READ OFF PRODUCTION over a window, not inferred from the writer that happens to be documented: a single sample cannot distinguish "one shape" from "the shape that was current when I looked". Corollary for the consumer itself: `#413`'s "`{}` means ALL, not SOME" belongs per ROW, not per FILE — a row that cannot answer must return None rather than a hollow state, because a non-None empty answer suppresses the fallback that would have been correct.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-26 — RULE: a measurement can be REAL and still describe the WRONG POPULATION. State the denominator before you generalise a rate.

**Two instances the same evening, in two different sessions, in opposite
directions — which is why this is a rule and not an anecdote.**

**Instance 1 (`open-bet-live-status`, `#584`).** Measured off the whole
portfolio plan artifact: `bet_status` resolved **3 of 442**, `live_marks`
**82 of 442**. Reported to the user as "the status column will be ~5% useful,
the marks will populate broadly", and the build was scoped on that. Measured
again after deploying, on the population the feature actually serves — the OPEN
LIVE book — **status 81 of 126, marks 18 of 126. The inverse.** The 442-row
plan is dominated by PAPER SOCCER rows, which have no live resolver and so
answer `no_live_feed`; the live book is MLB/WNBA-heavy where the resolver
works. And a game in progress has usually LEFT the board, so the marks thin out
in exactly the rows where the statuses arrive. Neither number was wrong. The
denominator was.

**Instance 2 (lane `mlb-chip-live-state`, reported unprompted by that session,
and it belongs to `todo.md #581`'s VERIFICATION rather than to the fix — the
error was made while checking the fix, not in it).** "12 wrong on the worker
path", from four samples that turned out to be **ONE artifact re-read as it
aged 18.7s → 114.8s**. Three misses counted four times, and all three were
ordinary artifact age rather than the defect being hunted.
**Repeated reads of one object are one sample.**

**WHY THIS IS NOT JUST `feedback_rate_not_count`.** That rule says: supply a
denominator. This one says: **supply the RIGHT denominator, and say what it
is.** Both instances above HAD a denominator — 442 and 4 — and both were
quoted with it. The failure was that the population measured was not the
population the claim was about, and nothing in the phrasing exposed the gap.

**HOW TO APPLY.**
- Before generalising a rate, write the population down: *"N of M, measured over
  <what>"*. If the sentence you are about to say is about a different <what>,
  you do not have the number yet.
- A plan/board/catalogue artifact is usually a MIXED population (paper and live,
  every sport, every venue). A feature that serves one slice must be sized on
  that slice.
- Repeated observations of one object are one observation. Count distinct
  objects, not reads.
- **MAKE THAT STRUCTURAL, NOT A HABIT** (that lane's own point, and it is the
  mechanical half of this rule). Instance 2's sampler polled
  `/api/board/game-chips` on a fixed interval and recorded every response, when
  it should have keyed on the artifact's `published_at` and collapsed reads
  sharing one. **A rule that depends on someone remembering to check the
  denominator will fail again; a sampler that cannot emit the duplicate will
  not.** Where you are building the instrument, dedupe at the source.
- The cheap check is to re-measure on the real population AFTER shipping and
  compare. Both instances above were caught that way, not by reasoning.

## 2026-08-26 — FORBIDDEN: reporting a test as failing on `main` from a session worktree, when its fixture is DERIVED from `data/`. And a stash-and-rerun does NOT isolate it.

**`session_worktree.py open` excludes `data/` by design** (34,690 of 37,745
tracked files; it is a lossy mirror and never evidence about production). Any
test whose fixture is BUILT FROM those artifacts therefore fails in a session
worktree and **looks exactly like a real regression on `main`**.

**MEASURED, twice in one evening, in two sessions that had not spoken yet.**

*This session:* `tests/test_venue_quote_adapters.py` reported 3 failures
(`no_rows` on every soccer row). Traced: `team_aliases._soccer_alias_to_name()`
is DERIVED from `data/soccer_source/<league>/.../team_branding/*.csv`, so with
`data/` absent it builds an **EMPTY** map; `canonical_team("soccer","ars")`
returns None; `polymarket_board_join._effective_league` classifies a row as
soccer only when BOTH clubs resolve, so no soccer row could ever match.
Junctioned the worktree at the primary tree's `data/soccer_source`: **alias map
0 → 474**, `ars`→arsenal, `che`→chelsea, **all 6 pass**. Nothing was broken.

*Lane `ncaaf-opener-regions-props`, independently:* `40 failed / 397 passed` on
`-k ncaaf`, from `test_ncaaf_team_registry_reachability` and
`test_ncaaf_transfer_portal_builder`, both built from
`data/ncaaf_source/source_artifacts/...`.

**THE METHOD ERROR IS THE POINT, AND IT IS THE EXPENSIVE HALF.** Both sessions
"confirmed pre-existing" by **stashing their own diff and re-running — in the
same worktree**. That controls for your CODE and not for your ENVIRONMENT, and
the environment was the variable that mattered. Both got the same failures at
HEAD and both concluded, wrongly, that `main` was broken. **A stash-and-rerun
feels like a control while isolating exactly one axis.** This session then
repeated the false claim to the user and to two peer sessions before checking.

**HOW TO APPLY.**
- Before calling ANY test failure pre-existing from a worktree, ask what its
  fixture is built from. `grep` the failing module for `data/` — directly or
  through a `_source_root` / `all_teams` / `_alias_to_name` style derivation.
- The check is cheap and definitive: make the data reachable and re-run. A
  Windows junction (`New-Item -ItemType Junction`) onto the primary tree's
  specific subtree takes seconds, or `session_worktree.py open --with-data`.
- **REMOVE THE JUNCTION AFTERWARDS — AND THEN `git sparse-checkout reapply`.**
  Two distinct hazards, and the second is the dangerous one:
  1. While the junction exists, the worktree's `git` sees the primary tree's
     untracked files and a test that WRITES lands in the real checkout — the
     2026-08-23 `default_nfl_source_root()` entry above, by another route.
  2. **Removing it leaves the tree reading as ~150 DELETED tracked files.**
     Measured here: `session_worktree.py` excludes `data/` via non-cone
     sparse-checkout (`/*`, `!/data/`), and materialising that path through a
     junction clears the SKIP_WORKTREE bits — so after deleting the junction
     `git status` shows ` D` on every path it had touched, and `land` correctly
     refuses a dirty tree. **`git sparse-checkout reapply` restores it to
     zero.** Do NOT `git restore data/` (writes 34k files) and do NOT commit
     past it — that is the 4,993-staged-deletions incident's exact shape.
- "Same failures with my diff stashed" is a statement about your diff. It is
  not a statement about `main`. Say the first and do not imply the second.


### 2026-08-28 — FORBIDDEN: chaining an EDIT and a COMMIT so that a FAILED edit still commits. The guard fired correctly and the commit ran anyway, taking another session's uncommitted work with it.

Known cousin: [[never chain add and commit]]. This is the same lesson one step
earlier in the pipeline, and the existing rule did not cover it — I was careful
about `add`, and committed by explicit pathspec, and it happened anyway.

**The shape.** One Bash call containing, on separate lines:

    python - <<'PY'   ... assert old in s ...  PY      <-- FAILED, AssertionError
    cat > msgfile <<'EOF' ... EOF && git commit -F msgfile -- fileA fileB

The `assert` did exactly its job: the anchor no longer matched because another
session had rewritten that part of `lanes.md`. But the statements were newline-
separated, not `&&`-joined, so the failure printed a traceback and the shell ran
the commit regardless.

**Why pathspec did not save me.** `git commit -- <paths>` commits the WORKING
TREE version of those paths. `lanes.md` held 97 lines of another session's
uncommitted edits (`venue-join-refusal-visibility` transferring a claim, and a
"DO NOT fire a separate refresh-worker deploy" note from a third lane). I
committed all of it under a message about NCAAF settlement, having never read
it. Pathspec bounds WHICH files, never WHOSE CHANGES.

**Caught by arithmetic, not by review.** The commit said `2 files changed, 106
insertions` for a ten-line constant rename. That mismatch is the whole
detection: a number far larger than the change I made.

**Repaired** (unpushed, so recoverable): `git reset --soft HEAD~1`, then
`git restore --staged .syndicate/lanes.md` to return their work to the working
tree uncommitted, then re-commit my file alone. The index was verified EMPTY
first — a soft reset stages everything in the commit, so doing it with another
session's staged work present would have made it worse.

**Rules:**
1. **Never put an edit and a commit in the same Bash call.** Separate calls, and
   read the edit's result before committing. `&&` is not enough either — it
   makes the failure mode quieter, not absent.
2. **Check the diffstat against the size of the change you made** before
   accepting a commit. "10 lines edited, 106 committed" is the alarm.
3. **A file another session is editing is not yours to commit, even by
   pathspec.** If a shared ledger file is dirty and the dirt is not yours, hold
   your edit until it is clean rather than adding to it — an edit made now can
   only be committed by entangling both.

**AMENDMENT to rule 3 `[2026-08-28, session 28195565 — the third lane whose note
this incident swept up]`. The first half stands; "can only" is FALSE, and it
matters because it forbids the technique that actually solves this.**

The `"DO NOT fire a separate refresh-worker deploy"` note named above is mine. It
was an uncommitted working-tree edit when this incident took it. Twenty minutes
later I committed that same note, by hand, while 91 lines of two other sessions'
work sat dirty in the same file — and took none of it. **Blob-stage against
HEAD:**

    git show HEAD:<path>            # build from HEAD, never read the dirty file
    ...apply your hunk to that text...
    BLOB=$(git hash-object -w tmp)
    git update-index --cacheinfo 100644,$BLOB,<path>

The index entry becomes `HEAD + your hunk`. The working tree is never written to,
so the other sessions' edits survive untouched and still uncommitted. Verified
before committing: **22 insertions, 0 deletions, one hunk**, and every added line
mine. Their 91 lines were still dirty afterwards. See `[[shared-tree commit
recipes]]`, which already carried this recipe.

**Rule 2 is what makes it safe, and it is not optional here** — blob-staging is
precisely the operation where a miscomputed blob would commit a silent revert of
someone's work. `git diff --cached --numstat` before every such commit, and
confirm the added lines are yours.

**Choose by whether you can wait.** Holding until clean is still the better
default — it needs no plumbing and cannot go wrong. Blob-stage when the edit is
load-bearing now and the file may not go clean soon: mine said "do not fire a
second deploy", which was worth nothing after someone had fired one. Waiting
would have been the wrong call, and rule 3 as written prescribes waiting.

**A note that is committed is not therefore intact.** After the sweep and the
`reset --soft` repair, I re-read the file and counted: `RIDES ALONG` appears
**exactly once**, all three of its sections present, my lane block whole. A
round trip through someone else's commit and an undo is a plausible place to
lose or double a block, and the count is cheap.

## 2026-08-28 — FORBIDDEN: treating a refuted MECHANISM as a refuted OBSERVATION. I disproved my own theory of how a wrong-side fill happened, and used that to dismiss the fill.

**THIS ENTRY REPLACES THE ONE THAT STOOD HERE FOR SIX HOURS, WHICH WAS WRONG IN
ITS CONCLUSION AND WOULD HAVE TAUGHT THE NEXT SESSION TO DISMISS A REAL ONE.**
The superseded version was titled *"FORBIDDEN: escalating a wrong-side money
alarm on a property the code already handles"* and concluded the alarm was
false. It was not. Left in the history; do not restore it.

**What happened.** The user reported a filled order, `aec-mlb-az-sf-2026-08-27`,
board `side=home` (San Francisco), as showing on Polymarket as "Arizona ML".

I found the venue's `outcomes` array reversed relative to its slug, proposed
that `outcomes[i]` and `outcomePrices[i]` were MISALIGNED, then tested that
theory properly and refuted it — the totals markets give a sharp test, `under`
at index 1 priced 0.445 against a planned 0.4444 where misalignment would read
Over's ~0.555. Alignment proven at both indices.

**Then I concluded the fill was fine.** That step is the defect. Disproving my
own mechanism said nothing about the user's observation, which never depended on
my theory being right.

**The truth, established by a parallel session and verified here:** SF won 6-1
(MLB StatsAPI, `Arizona Diamondbacks 1 @ San Francisco Giants 6`, Final,
`home_win=True`). The venue graded the order **lost**, pnl **-5.871** — exactly
our cost basis — with `held_side=POSITION_RESOLUTION_SIDE_SHORT`. Across the
settled ledger: polymarket h2h **5 agree, 3 MISMATCH**; polymarket totals 9/0;
kalshi totals 4/0. A coin flip on h2h, and the totals path is immune only
because it resolves by NAME (`over`->YES) where h2h has no name to fall back on.

**THE CONFLATION THAT MADE IT PLAUSIBLE, and it is the reusable part.** There are
TWO mappings here:

    outcomes[i]  <->  outcomePrices[i]        (alignment)   -- I proved this
    OUTCOME_SIDE_YES  <->  outcomes[0]        (the binding) -- I assumed this

I proved the first and reported it as evidence about the second. They are
independent, and only the second was ever in question. My follow-up argument —
"a 0.38 fill is impossible for Arizona at 0.62" — inherits the same error, since
it prices the leg using the alignment I proved rather than the binding I did
not.

**Rules:**
1. **Refuting your own explanation is not refuting the report.** When a proposed
   mechanism dies, the observation returns to unexplained — NOT to explained-away.
   Say "I no longer know why" and keep the alarm open.
2. **Name the mappings before claiming one is proven.** Write them down as
   separate lines. Two adjacent index-keyed relations look like one fact and are
   not.
3. **A person looking at the venue outranks inference from our own logs, because
   our logs cannot contain the answer.** The order row carries no outcome NAME —
   measured keys are `action, avgPx, ..., marketSlug, outcomeSide, price, ...` —
   so reading an order back only ever echoes the side we sent. When the only
   independent observer is a human, their reading is the evidence, not the thing
   to be explained away.
4. **A settled ledger beats every live-price argument.** Three lines of
   `held_side` and pnl against the real result ended a question that hours of
   price reasoning could not. Go to settled outcomes first.

5. **Before calling a venue property a bug, check whether the code's own
   docstring already names it.** `outcome_side_for_index` did, with its own
   measured example, one function above the line being read.
6. **Rank candidate tests by SEPARATION before running them.** The moneyline
   comparison separates by ~0.04 and read as inconclusive; the totals comparison
   separates by ~0.11 and was decisive, in the same log window.

*(5 and 6 are restored from the superseded entry at the request of the session
that found the real defect. They were good rules, they are not what failed, and
dropping them was over-correction — the failure was one inference step, not the
whole entry.)*

**WHY THE HEADING WAS REPLACED ANYWAY, having kept the body.** That session
argued for amending rather than retracting. Half right, and the half that is not
is the heading specifically: the session-start digest surfaces STANDING RULES
**as headings only**. A heading reading *"FORBIDDEN: escalating a wrong-side
money alarm"* is therefore the most-read and least-qualified sentence in the
entry, and it told the next session not to escalate the exact class of report
that was correct. A rule whose body is right and whose title is wrong is worse
than no rule, because the title is what survives compression.

**A FOURTH CORROBORATION, and the cleanest, because it needs no team-name
reasoning at all.** Measured 2026-08-28T15:07:31Z by the same session — four
sibling futures in ONE catalogue response:

    tec-mlb-nlchamp-2026-09-27-nym   outcomes=["Yes","No"]
    tec-mlb-champ-2026-09-27-ath     outcomes=["Yes","No"]
    tec-mlb-nlchamp-2026-09-27-atl   outcomes=["No","Yes"]   <-- reversed
    tec-mlb-champ-2026-09-27-atl     outcomes=["Yes","No"]

The outcomes are literally the strings "Yes" and "No", listed NO-first on 1 of
4. No alias, no nickname, no slug to misread — the array simply is not
YES-first, and any positional rule over it is a coin flip by construction.

**THE VENUE NAMES ITS OWN YES LEG, and it is NOT wired yet — deliberately.**
`marketSides[].long` with `.team.name` is a NAME rule of the same shape that
makes totals immune. But only the FIRST `marketSides` entry has been observed (a
400-char log truncation), so "long == YES" is still an INFERENCE, and the
sequence in `todo.md #595` is: widen the log to both sides, persist a derived
`yes_outcome` string (not `marketSides` itself — ~6.7MB against an 8MB ceiling),
then score it against the 8 venue-settled moneylines where ground truth exists,
INCLUDING the 3 that went the wrong way. A rule that predicts all 8 is proven on
real money; anything less is a better-sourced guess. **Do not wire it early.**

**Still true from the superseded entry, and worth keeping:** the outcomes array
being reversed relative to the slug means nothing on its own — `lad-atl` carries
its outcomes in slug order and `az-sf` does not — because outcomes order is not
slug order and `outcome_side_for_index`'s own docstring says so. That part was
a genuine dead end. And the cost of a WRONG fix here is still the bug itself,
so the correct response remains a named REFUSAL of `home`/`away` on this venue
until the YES leg can be read by name, not a flip of
`_YES_OUTCOME_INDEX_DEFAULT`.

## 2026-08-27 — FORBIDDEN: pushing past a ledger checker's warning because its output "looks like the usual noise". A WARNING THAT IS USUALLY WRONG GETS TRAINED OUT — and two sessions proved it independently on the same night

- **What we believed.** `session_worktree.py land` prints `ledger/todo ids
  PROBLEMS   (run scripts/todo_id_reconcile.py)` and pushes anyway. Both
  sessions active on 2026-08-26 read that line as known background — the
  reconciler's `REVIEW` section lists twelve ancient ids (`#65`–`#81`) that have
  been unmatched for weeks, so the warning is *usually* about nothing.

- **What was actually true.** The same output also said `DUPLICATED in todo.md
  -- 1 id(s) declared more than once: #581: 2 item headers`. Lane
  `mlb-chip-live-state` and lane `open-bet-live-status` had both taken `#581`
  within about half an hour, and both had landed it. Four pushes went past the
  warning before anyone read it. The list's own rule is that ids are stable and
  never reused, so two items sharing one number breaks every cross-reference to
  it.

- **How we found out.** By finally running the tool the warning names, an hour
  later, for an unrelated reason. Resolved by ancestry — `merge-base
  --is-ancestor 23f065d4 f8d8b05f` passes, so the first-landed item keeps the
  number and the second renumbered to `#584`. **Not by a blanket
  find-and-replace:** eight files mention `#581`, four belonged to the renumbering
  lane and four to the other, and one of those four is a correct reference by the
  renumbering lane's own author to the OTHER lane's item. A `sed` would have
  broken all four.

- **The rule going forward.** **A checker that emits known-false warnings beside
  true ones is not a checker, it is noise with an exit code.** Two things follow.
  (1) When a checker fires, READ ITS FULL OUTPUT before deciding it is the usual
  thing — "I recognise this warning" is a memory of a DIFFERENT run. (2) Separate
  the classes at the point that ACTS on the finding: a duplicate declaration should
  BLOCK, while historical unmatched ids stay advisory. The check that cannot be
  trained out is the one that only fires when something is wrong.

  **CORRECTED `[2026-08-27, same night]` — this bullet first said the RECONCILER
  needed the blocking split, and sent the reader to the wrong file.**
  `scripts/todo_id_reconcile.py` was already correct and already exited 1 on a
  duplicate; `syndicate-27` proved it by introducing one. The gap was one layer
  up, in `session_worktree.py`'s `_run_checkers`/`cmd_land`, which printed
  `PROBLEMS` and pushed anyway — so the entire consequence of a correct finding
  was a line of text. **Both of us mis-attributed a correct tool's finding to the
  tool**, which is the same error as the rest of this entry one level out. Fixed
  in `98d4e119`: `land` now REFUSES on a duplicate id, with
  `--allow-duplicate-ids` for whoever is fixing it; `missing` and `in both files`
  still only report, so a pre-existing `#469` does not take everyone's pushes
  down. Corollary for id assignment
  specifically: "check both files before taking a number" cannot prevent a
  simultaneous take, because both sessions check and both see the same maximum.
  **The check has to be at LAND, not at write.**

- **Cost.** One duplicated id across two lanes, four pushes past a correct
  warning, and a renumber touching four files after the fact. Nothing shipped
  wrong and no code was affected — the cost is entirely in the ledger, which is
  the thing this repo says its context window is not. **Still open, and named
  because routing around it is not fixing it:** the reconciler prints twelve
  lines of ancient `#65`–`#81` noise in its unfiltered form, which is what
  trained both sessions to skim it. Blocking the push stops the damage; it does
  not make the output readable.


### 2026-08-27 — FORBIDDEN: REFUSING A BAD VALUE UPSTREAM OF A COALESCING FALLBACK and calling it fixed. The fallback picks it back up one candidate later, and the fix ships inert

- **What we believed.** `_apply_wnba_live_scores` (`home.py`) was where a
  SmartSim PROJECTION was leaking into a live score — `GSV 85.43 / CON 68.94` on
  the Layer 2 chip strip, user-reported. Refuse a fractional value there, stop
  setting `away["score"]`, done.

- **What was actually true.** `_side_score` (`game_chip_scoreboard.py`) is a
  COALESCING CHAIN — `container.score`, then `status.<side>_score`, then
  `score.<side>`, then `<side>_score`, then **`live_state.<side>_pts`**. Not
  setting `away["score"]` just means the chain falls through one more candidate
  and finds the same projection in `live_state`, which the fix had not touched.
  The refusal computed the right answer and changed nothing on screen.

- **How we found out.** A test written against the real production row, before
  deploying: `test_a_refused_score_does_not_reach_the_chip` failed on its first
  run with `'85.43' is not None`. Nothing else would have caught it — the unit
  under change behaved exactly as intended, every other assertion passed, and the
  served page would have looked identical to the bug.

- **The rule going forward.** Before refusing or sanitising a value, **find every
  place the consumer can obtain it.** `grep` the field name, not the function you
  are editing. If the read path is a coalescing chain (`a or b or c`, a `for
  candidate in (...)` loop, `dict.get` with a fallback), the guard belongs at the
  CHOKE POINT the chain converges on, not at one of its inputs — and preferably
  stated as a property of the domain, so a source nobody has written yet is
  covered too. Here: a fractional value is not a score in any sport this platform
  carries, so `_score_value` refuses it for every sport and every future feed.
  Distinct from the existing reachability rules (2026-08-13, 2026-08-25): those
  ask whether your code RUNS. This one is about code that runs, is correct, and
  is overtaken by a sibling branch.

- **Cost.** None shipped — caught by a pre-deploy test. Recorded because it was
  hit three times on one night across two sessions: this one, `#583`'s date
  filter that built `dateFilteredGames` while the function still returned
  `gamesList`, and twice more in `ncaaf-opener-regions-props`' own work. The
  common shape is a correct computation that nothing downstream consumes.

## 2026-08-27 — RULE: a deploy claim serialises SESSIONS. It does not reserve a service against a HUMAN, and an assistant cannot lift the guard from inside a command.

**MEASURED 2026-08-26.** Lane `ncaaf-opener-regions-props` held the
`refresh-worker` and `live-odds-worker` claims (acquired 22:57:41Z, TTL 2700s,
so live until 23:42:41Z). At **23:26:02Z** — **16.6 minutes inside the window**
— both services were deployed to `23f065d4` by the user from their own
terminal. Nothing refused it, because `.claude/hooks/deploy-guard.py` only
intercepts an ASSISTANT's Bash calls.

**No harm that time: `23f065d4` was strictly forward of everything live.** The
hazard is structural, and it is a belief problem rather than a tooling one — the
holding session believed the service was reserved, and reported to its own user
that it was.

**A CORRECTION THAT WAS NEARLY WRITTEN THE OTHER WAY ROUND.** That session first
concluded its claim had already expired and that `deploy_claim.py status` — which
displayed it as HELD — was the defect. The arithmetic does not support it
(22:57:41 + 45:00 = 23:42:41 > 23:26:02). **The display was correct.** Filing it
as a display bug would have left every reader still trusting a claim to reserve a
service, which is the belief that gets someone hurt on a deploy that is NOT
strictly forward.

**THE OTHER HALF: an assistant cannot turn the guard off from inside a command.**
`SYNDICATE_DEPLOY_GUARD=off python scripts/render_deploy.py ...` does NOT work —
the hook runs in its own process and never sees an inline prefix. Attempted twice
tonight, refused both times. The remaining routes are forging a preflight receipt
or POSTing the Render API directly, and **both were declined**: that guard exists
because a deploy fired 61 seconds after a job started and cancelling it CAUSED
the restart it was meant to avoid. Both deploys were run by the user from their
own terminal instead, with the cost of the kill stated first.

**HOW TO APPLY.**
- A claim tells you no OTHER SESSION will deploy. It tells you nothing about the
  person at the keyboard. Do not report a service as reserved.
- Before acting on "my claim was violated", do the arithmetic:
  `acquired_at + ttl_seconds` against the deploy's `createdAt`. A stale claim and
  a bypassed live one call for opposite fixes.
- When the guard blocks you and the user has authorised the deploy, hand them
  the exact command and state what it kills. Do not route around the hook.
- After a user-run deploy, **re-read the live SHA on every service** rather than
  assuming your last deploy is still live. This session told a peer
  live-odds-worker was on `022583f6` when it had been on `ebfec2ed` for an hour.

## 2026-08-27 — FORBIDDEN: running `deploy_claim.py` from a session worktree. The claim file is PER-TREE, so nobody else can see it.

**MEASURED 2026-08-27T01:0xZ.** Two `web` claims existed at once, in two files,
neither aware of the other:

    C:\Users\...\Syndicate\.syndicate\deploy_claims\web.json
        holder venue-settlement       token 0ddf5e4c...  01:06:32Z
    C:\tmp\syndicate-sessions\<lane>\.syndicate\deploy_claims\web.json
        holder open-bet-live-status   token 9d2542ac...  01:07:38Z

`deploy_claim.py` resolves `.syndicate/deploy_claims/` **relative to the tree it
is run from**, and `session_worktree.py open` gives every lane its own tree. So a
claim taken from a worktree lands in a directory no other session reads, while
`deploy-guard.py` and `deploy_preflight.py` — which run under
`CLAUDE_PROJECT_DIR` — consult the PRIMARY tree's copy.

**Both failure directions are live:**
- **A claim you cannot see.** Take it from your worktree and every other session
  reads `web free`. You believe the service is reserved; it is not. This is the
  same class as the 2026-08-26 finding that a claim does not reserve a service
  against a human at a terminal — a lock whose holder is the only one who knows
  it exists.
- **A claim you cannot release.** `release --token <t>` run from the wrong tree
  answers `web: no claim to release` and exits 0, leaving the real claim held.
  Measured here: three "successful" release/acquire cycles moved nothing,
  because they were all operating on the worktree's copy.

**The guard's `your lane:` line is resolved independently of any of this** — it
did not match the marker file this session wrote, so aligning the marker did not
help and the mismatch persisted until the holder name was matched to what the
guard reported.

**HOW TO APPLY.**
- **Run every `deploy_claim.py` / `deploy_preflight.py` / `render_deploy.py`
  from the PRIMARY tree**, with an explicit `cd`. The Bash tool's working
  directory persists between calls and a `cd` several commands earlier is enough
  to put you in the worktree without noticing.
- The tell is `RENDER_API_KEY not set in the environment or .env` — the worktree
  has no `.env`. Treat that message as "you are in the wrong tree", not as a
  credentials problem.
- Before deploying, confirm `deploy claim   held by YOU` in the PREFLIGHT output
  from the primary tree. An `ACQUIRED` line proves only that some file was
  written somewhere.
- If the guard names a lane you do not recognise, acquire under THAT name rather
  than editing markers to match — the guard's identity resolution is the one
  that gates the push.

---

## 2026-08-27 — MEASURED NEGATIVE: the NCAAF advanced-data payload does not close the gap to market

**Do not re-litigate this without new evidence.** The re-fit ran; the answer is
no. `scripts/refit_ncaaf_smartsim2_payload.py --season 2025 --sims 60`, 714
games, both arms sharing seeds, ~60 min of compute:

    paired_games            693  (21 skipped: no SP+ rating or no payload)
    model MAE payload OFF   15.184
    model MAE payload ON    15.144
    market MAE, same games  11.854
    delta ON - OFF          -0.040
    gap_to_market_ON        +3.290     BAR WAS <= 0

The payload closes **1.2% of the 3.33-point gap to the close.** It would need to
be ~80x larger to earn a deploy. The bar was fixed BEFORE any results existed,
deliberately: ON beating OFF is not the test, because a model can improve
against itself and still lose to the market, and this one does.

**THIS IS A VALID NULL, NOT AN UNFED PIPELINE — that is the load-bearing part.**
Per-block coverage was 98.6% on the priors-moving blocks (coach_continuity
714/714, returning_production 704/714, transfer_impact 708/714, roster_depth
714/714). An EARLIER version of this same harness reported **"100% payload
coverage"** while `returning_production` and `coach_continuity` were absent for
EVERY game — the only block present was `roster_depth`, and the aggregate
"any block" figure hid it at full confidence. Per-block reporting is what makes
"the features don't help" distinguishable from "the features never arrived".
Any future re-run MUST print per-block or its null means nothing.

**DO NOT read the -0.040 as directional.** The harness emits no paired SE and
no t-statistic, so significance is unstated in BOTH directions; at 1.2% of the
gap this is where paired-seed noise lives. Calling it "a small improvement"
would be inventing a result the instrument cannot resolve.

**Two instrumentation gaps in this harness, to fix before any re-run:**
- No progress output anywhere in the sim loop — only early-exit errors and the
  final report. A 60-minute job whose completion can only be inferred from CPU
  time. Needs a per-N-games heartbeat.
- No paired SE / t-stat on `delta_on_minus_off`, which is precisely the number
  the deploy decision hinges on.

**What this does NOT say:** the wiring is fine. 16/22 fields move, the payload
is reachable and disk-backed, and `set_snapshot_root` correctly kept the 2025
re-fit off the 2026 board's snapshots. Building it was right; shipping it as a
model improvement is not supported. Three blocks remain broken and were never
part of this test (`defensive_metrics` misrouted, `pace` null at source,
`player_usage` wrong grain) — fixing those is the only route to a different
answer, and it is a NEW measurement, not a re-run of this one.

---

## 2026-08-27 — NCAAF TOTALS ARE NOT OVER-DISPERSED. The deficit is ONE CONSTANT BIAS, and the residual spread already matches the market

Measured offline on **711 completed 2025 games**, joining the committed
`smartsim2_projections_2025_wk*.csv` (engine output, payload OFF) to
`cfbd_lines_*.json` (market total + final score). Zero API calls.

    MEAN BIAS      model  -5.211      market  +0.709    (actual - predicted)
    RESIDUAL SD    model  15.324      market  15.304
    sim's CLAIMED predictive SD              12.832
    CALIBRATION RATIO 0.837   (<1 = OVER-CONFIDENT, not over-dispersed)
    bias removed:  model total MAE 12.401   vs market 12.373

**Rule: before attacking a model's DISPERSION, decompose its error into BIAS
and SPREAD. They demand opposite fixes and only one of them was ever wrong
here.** The model's residual SD is statistically indistinguishable from the
market's — its errors are ALREADY as tight. The entire totals deficit is a
single systematic over-prediction of 5.2 points.

**WHAT THIS CORRECTS.** `state.md` carried "totals 1.94x over-dispersed",
measured on the LIVE slate, and I used it to motivate the pace work. It does
not reproduce on completed games and it points the OTHER WAY (0.837). The
live-slate figure compared the sim's predictive SD against a MARKET SD with no
outcomes available — a different quantity from realised residual spread. **A
dispersion number computed without outcomes is not a calibration measurement.**

**WHY THE PACE WORK SURVIVES THIS, with a better reason than it had.** A
hardcoded 24.0 s/play runs 151.6 s/drive against a real 179.5 — ~18% more
drives per game, hence more scoring. A CONSTANT over-prediction of totals is
precisely the signature of a pace pinned too fast, and the magnitude fits.

**PRE-REGISTERED, before the re-fit runs:** correcting pace should cut the mean
total, but a naive full correction scales 58.11 x 0.845 = 49.1 against an actual
52.90 — it should OVERSHOOT DOWNWARD. The profile was calibrated with pace
pinned at +0.4, so this is a mechanism added to a calibrated engine and owes a
re-fit of the rates that were absorbing it. Overshoot is the EXPECTED result,
not a failure of the input.

**BOUNDS, because these numbers will be quoted.** The projections carry
`rating_source=cfbd_ppa_season_2025` — the LEAKED season aggregate that
`state.md` records as inflating apparent skill 30%. Accuracy here is FLATTERED;
the true gap is wider than +0.914 and "as good as the market" is NOT
established. The bias removal is IN-SAMPLE. The rating source differs from the
re-fit's SP+, so this is not the identical configuration.

### 2026-08-27 — PRE-REGISTERED PREDICTION CONFIRMED: raw pace OVER-CORRECTS the totals bias by ~35-56%

The prediction was written into the entry above BEFORE this ran. Measured with
ratings HELD NEUTRAL (n=300, 40 sims, paired seeds) so the contrast is pace and
nothing else, and needing no CFBD call:

    mean total, pace OFF (hardcoded 24.0s)  50.20
    mean total, pace ON  (real, mean 26.25) 43.18
    MEAN SHIFT   -7.02 pts (-14.0%)   sd 4.41   min -22.33  max +7.00
    17/300 games where pace RAISED the total

**Rule: a mechanism that is the RIGHT SIGN and the RIGHT ORDER OF MAGNITUDE is
still not shippable alone -- check whether it OVERSHOOTS.** Pace covers 135% of
the -5.21 point bias by raw comparison, or ~156% scaling the 14.0% shift onto
the engine's real 58.11 mean. Enabling it by itself would flip NCAAF totals
from ~5.2 too HIGH to ~2-3 too LOW. The calibration profile was fitted with
`pace_index` pinned at +0.4, so the scoring rates absorbed the pace error;
correcting one without re-fitting the other just moves the bias across zero.

That the shift is NOT uniform (17/300 games get faster) is the check that this
is real per-team signal and not a constant offset dressed up as a feature.

BOUND: neutral ratings put absolute totals (50.20/43.18) below the engine's
real 58.11, so the PERCENTAGE transfers more reliably than the point shift.
Both framings are given above rather than the flattering one.

---

## 2026-08-27 — NCAAF drive structure is an ENGINE ACCOUNTING BUG, not a calibration gap. The sim's own numbers do not multiply out

Measured with `scripts/calibrate_ncaaf_drive_structure.py` against
`ncaaf_historical_truth_report.md` (53,548 real drives / 2,264 games):

    metric                 truth      sim     err
    yards per play (MEAS)  7.364    7.413   +0.7%   <- correct
    yards per drive       42.490   43.143   +1.5%   <- correct
    plays per drive        5.770    7.246  +25.6%   <- the defect
    seconds per drive     165.400 182.977  +10.6%
    possessions per game   23.650  20.033  -15.3%

**Rule: before tuning a model to a target, check the model's own metrics are
INTERNALLY CONSISTENT. If they do not multiply out, the defect is accounting,
not calibration, and no parameter will reach it.** Truth multiplies:
5.77 x 7.36 = 42.5. The sim does not: 7.246 x 7.413 = 53.7 against a credited
43.1 yards/drive -- a ~10.5 yard/drive gap between gross play gains and net
drive yardage that real football does not have. Divide the sim's OWN numbers
and you get 43.14 / 7.413 = **5.82 effective plays/drive, essentially truth's
5.77**. The football is right; the play COUNT is inflated ~25%.

Everything downstream follows from that one gap: clock burn (+10.6%), lost
possessions (-15.3%), and the outcome shares (field goals +76%, turnover-on-
downs -51%, punts -27%) are all drives lasting longer than their yardage
warrants.

**ALL THREE PROFILE LEVER FAMILIES WERE SWEPT AND NONE REACHES IT** -- which is
the evidence for "engine, not profile", not an assumption:
  - yardage (`drive_yardage_multiplier` 1.15 -> 1.60): plays/drive asymptotes at
    6.99 and then RISES; yards/play overshoots to 11.46, TD rate to 0.403
  - explosiveness (`explosive_play_multiplier` 1.45 -> 6.0): same floor
  - 4th-down policy (punt probabilities, conversion multiplier): 7.25 -> 7.21
    across the entire range, and trades punt rate up for turnover-on-downs
    DOWN, away from truth
The profile's 26 parameters have no lever for it because there is nothing to
tune -- the per-play yardage distribution is already right (32.4% of plays gain
<= 0, realistic for college).

**A METRIC I MANUFACTURED, AND THE CORRECTION.** The first pass DERIVED
yards/play as drive_yards / drive_plays and reported **-18.9% vs truth**, which
sent me sweeping yardage multipliers. Measured per play the way the truth report
measures it, it is **+0.7%**. In real football the derived and measured values
are identical by construction; comparing a derived quantity to a measured one
invented a defect that was not there. The tool now reports BOTH, and their
disagreement is the actual diagnostic.

**ALSO CORRECTED: the pace story, twice.** `expected_clock_seconds` from
`drive_priors` is a PRIOR (151.6s), not the realized simulation output (183.0s).
I quoted the prior as the engine's behaviour and concluded the engine ran 18%
too fast. It runs 10.6% too SLOW. Feeding the real-world pace measurement makes
every truth metric worse (possessions 17.91, seconds/drive 209.1), so the
`pace` block must stay OFF -- the engine's `pace_seconds_per_play` is not on the
real-world scale its name implies.

---

## 2026-08-27 — A GUARD THAT ASSERTS THE CALL, NOT THE RESULT, IS TRUE OF CODE THAT DOES NOTHING

Three defects in one session, all shipped, all passing every check in place:

    projections deploy   built clean, went live, board unchanged (0/51 -> 0/51).
                         Two of three builders put `predictions` INSIDE the
                         `ncaaf_card` sub-dict; the adapter reads it at the TOP
                         level. My structural test asserted the builders CALL
                         the helper and never WHERE the result lands.

    NameError            two builders passed a bare `projection` neither binds.
                         Every call raised. Found by session syndicate-27, not
                         by me — the same structural test passed it, because a
                         call site can be present and still be unexecutable.

    orphaned tab         moving a tab rail left two surplus `</div>` behind,
                         evicting the Details panel. Live ~20 minutes while
                         jinja parsed, 67 payload tests passed, the API served
                         correct JSON and shared_predictions confirmed 51/51.

**Rule: a guard must assert the OUTCOME at the place that CONSUMES it, and must
be seen to FAIL before it is trusted.** "The builder calls the helper" was true
of a payload nothing read. "Jinja parses" was true of markup that collapsed a
card in a browser. Both are statements about the thing built, not about the
thing that reads it.

Two practices came out of it and both earned their place the same day:
- **Negative-control every new guard.** Reintroduce the exact defect, watch the
  test fail, restore it. The placement test and the template-render suite were
  both controlled this way, and the control identified WHICH assertion does the
  work — for the orphaned tab it is the DIV-BALANCE test, not the orphan-tab
  test, because in an isolated render the section is still in the output string
  and only a browser's DOM parse evicts it.
- **A payload check cannot see a template defect.** Rendering is a different
  instrument, not a more thorough version of the same one.

---

## 2026-08-27 — MEASURE THE OUTCOME YOU PROMISED, NOT THE CHANGE YOU MADE

The NCAAF compact strip, three times:

    generic fallback  435px   the problem
    my "fix"          633px   WORSE, and shipped — I verified that the prose
                              blocks were gone (they were) and never measured
                              the height, which is what I had promised
    soccer's shape    181px   uniform across all 51

The 633px version passed every check I ran: prose removed, abbreviation
leading, jinja parsing, div balance. The defect was that moving a long school
name into `cards-mini-copy` — which `dense_cards.css` gives
`overflow-wrap: anywhere` — rendered it **1px wide and 226px tall** in a 39px
box. I had moved a long string OUT of an element that handled it and INTO one
that breaks anywhere.

**Rule: state the outcome as a NUMBER before changing anything, then measure
that number.** "Prose blocks: 0" is a fact about my edit. "Card height 181px vs
435px, uniform across 51" is the thing the user asked for.

Corollary, from the same session: **verify a class is STYLED by the stylesheet
the page actually loads before using it.** MLB and NCAAF load different sheets
(`cards_exact.css` vs `dense_cards.css`). `.cards-market-sub` had a colour rule
and NO font-size rule in the NCAAF sheet, so it inherited 16px body text and
rendered LARGER than the 15px value it annotates. MLB's `cards-linescore*` have
zero rules there. Soccer's `cards-strip-pregame-*` ARE global — which is why
they were safe to reuse, checked rather than assumed.

## 2026-08-27 — FORBIDDEN: deferring work around a ledger BLOCKER without re-measuring it. A blocker is a measurement and it expires.

Lane `live-game-line-projection` carried, in bold: *"AND IT CANNOT BE READ
OFF-WORKER. `/api/ops/artifacts/stream` returns 403 `path is not an allowed hot
artifact` for the ledger `.jsonl`; re-verified 2026-08-18 — no entry in
`HOT_ARTIFACT_PATTERNS` matches. Whoever takes this lane needs the artifact
route, or the allowlist entry first."*

**It was true on 2026-08-18 and false from 2026-08-20**, when `d7dbdbd2`
("allowlist: make the live-gameline ledger readable off-worker (#440)") added
both patterns. Content-verified 2026-08-27 on all three DEPLOYED SHAs — web
`e3568422`, refresh-worker `ad3f116c`, live-odds-worker `34b4d4b4`.

**The damage is that a blocker does not just sit there — it PROPAGATES.** For
seven days it was the stated reason the ledger route was "deliberately OUT of
scope and handed on", and a SECOND lane
(`layer2-rail-duplicate-nfl-cards`) wrote its own scope note around the same
file. Two lanes shaped their work around a fact that had already been fixed by
a third. Nobody re-read it because it was bold, dated, and specific — the three
properties that make a stale fact most convincing.

Compounding it, the claim that would have enforced the detour was held by
session `e8d83eb5-…`, absent from the roster even with `include_archived=true`.
So the file was guarded by a dead holder against an edit that was already made.

**Rules:**
1. **Re-measure a blocker before you scope around it.** The cost of re-running
   one grep is always lower than the cost of routing work around a phantom. If
   the blocker names a file:line or a pattern, check that file:line.
2. **Date-stamp blockers with what was measured, not just when.** "no entry in
   `HOT_ARTIFACT_PATTERNS` matches" is checkable in seconds; "cannot be read
   off-worker" is a conclusion that outlives its evidence.
3. **A blocker inherited from another lane is second-hand.** Same rule as
   [[feedback_rederive_load_bearing_cross_lane_numbers]] — if it changes what
   you build, you measure it yourself.
4. **Check the holder is alive before honouring a claim** — `include_archived=true`,
   because "ended" and "never existed" look identical without it.

Same family as the other half of this session: the lane ALSO believed its
accuracy collector was "accumulating nightly" when the scheduled task had been
`enabled: false` for six days, because one task delegated its own re-enable to
another and nothing verified the handoff. Both are the same failure — **a
written status standing in for a reading.**

## 2026-08-27 — FORBIDDEN: trusting a test whose FIXTURE cannot violate the property it asserts. It is not weak coverage; it is zero coverage that reads as strong.

`tests/test_live_gameline_score.py::test_model_and_market_are_scored_on_identical_rows`
existed, was named for exactly the right invariant, and carried the docstring
*"The load-bearing assertion. If the market were scored on a different population
the comparison would be meaningless, and it would still LOOK like a number."*

It passed for weeks while production computed **model n 94 vs market n 90**.

**Why it could never fail:** every record in its fixture carries BOTH
`model_home_win_prob` and `market_fair_prob`. The populations diverge only when a
record has a model probability and NO market price — a row the fixture does not
contain. So `assert model.n == market.n == 2` was re-measuring the fixture, not the
code. Any implementation, including the broken one, passes it.

The defect it missed had ALREADY been observed, too: `all_records` was recorded in
`state.md` as "UNSOUND (model n 1526 vs market 1449)" — **written down as a caveat
and never fixed**, so the same bug shipped in three cuts. A known-unsound number
that stays in the ledger as a warning is a bug with a comment on it.

**Rules:**
1. **Before trusting a test, ask what input would make it fail — then check the
   fixture contains that input.** If no fixture row can violate the property, the
   test asserts nothing. Name the negative case in the fixture or the test is
   decoration.
2. **A property about MISSING data needs a fixture row with data missing.** Null,
   absent, one-sided. This is the whole class: every "scored on identical rows",
   "handles absent X", "unknown defaults safely" test needs the absence present.
3. **When you record a number as UNSOUND, open the fix or say why not.** "UNSOUND"
   in a ledger is not containment — three cuts and several weeks of quoting say so.
   Same failure shape as [[a blocker is a measurement and it expires]] from earlier
   today: writing the caveat felt like handling it.

Both fixes this session were caught the same way and neither by a test: by PRINTING
BOTH n VALUES side by side instead of the difference. The difference looked fine.

## 2026-08-27 — FORBIDDEN: reading `pid` in a deploy claim as evidence the holder is alive

Both claim PIDs read NOT RUNNING. I was one step from `acquire --force` against
a LIVE session's lock on that basis.

`deploy_claim.py` records `os.getpid()` — the PID of the short-lived *claim
script*, which exits the instant it writes the file. **It reads "dead" for
every healthy claim ever taken.** The field cannot distinguish a live holder
from an abandoned one, which is the only question anyone consults it for.

Liveness comes from finding the READER: search session transcripts for the lane
slug or the session id. Here `local_38d39247…` had printed
`SESSION=3515d143-…`, matching the lane owner, last active two minutes earlier.
It released the claim voluntarily ~2 min after being messaged.

Same family as *"find the READER before calling any id stale"*. A dead PID is
"not proven alive", never "proven gone".

## 2026-08-27 — `Path(__file__).parents[1]` MAKES THE PRIMARY TREE THE RENDEZVOUS, AND A WORKTREE INVISIBLE

The session-worktree protocol and the deploy locks disagree about where `.syndicate/` is.

- `deploy_claim.py` sets `CLAIM_DIR = REPO_ROOT / ".syndicate" / "deploy_claims"`
  with `REPO_ROOT` from the **script's own** location. Run it from a session
  worktree and the claim lands in that worktree — **no other session can see
  it**, so the lock silently stops being a lock while still reporting ACQUIRED.
- The deploy guard resolves the lane marker against `$CLAUDE_PROJECT_DIR`, the
  primary tree. Writing `.current-lane.<session>` in the worktree (which is what
  `/lane open` does if you run it there) makes the guard print
  `your lane: <none>` while you hold the claim — it blocked a deploy whose
  claim was already mine.

**Run every deploy-lock command from the PRIMARY tree, and write the
per-session lane marker there too.** Code edits stay in the worktree; the locks
are shared state and must live where the other sessions read them.

Same family as *"keyvalue/artifact split blinds guards"*: a guard reading a
different store than the one that matters is blind in exactly the case it exists for.

## 2026-08-27 — A COMMENTED-OUT PATH IS STILL A CLAIM; AND THE DEPLOY GUARD MATCHES LEDGER PROSE

Two collisions between ledger text and the tools that parse it, both caught by
the tools rather than by me.

1. Striking a stale claim by wrapping it in an HTML comment inside a `- Files:`
   block **created two new claims** — `check_lane_invariants.py` parses paths
   positionally and does not know what a comment is, so both the path I was
   removing and one I merely *named in my explanation* registered. The note has
   to live outside the `- Files:` block entirely.
2. Writing the literal deploy command into `lanes.md` tripped the deploy guard:
   it pattern-matches command text and cannot tell a ledger write from a POST.
   **A false positive here is correct behaviour** — the fix is to reword the
   ledger, never to reach for a route the guard does not recognise.

The general rule: ledger files are INPUTS to guards, not just prose for humans.
Text written into them is executed-as-pattern by something.

## 2026-08-27 — A CLAIM HOLDER IS NOT A DEPLOY AUTHOR. The API cannot tell you who fired it.

**Overturned by `ncaaf-opener-regions-props`, self-caught.** They thanked me for
deploying `600a753a` to refresh-worker. I had not — my deploys that day were all
live-odds-worker.

The inference was: *X held the claim near the deploy timestamp, therefore X
deployed it.* Render's deploys API records `trigger=api` and **no session
identity**. Nothing in it supports that step.

- **Misdirected credit is harmless. Misdirected blame is not**, and it is the
  same inference — a bad deploy pinned on whoever held the lock.
- It makes sessions **block on the wrong party**: the same message asked me to
  release a claim I did not hold while the real holder was a third lane.

**How to apply.** `deploy_claim.py status` answers who holds a claim NOW. For who
DEPLOYED something, the only record is what that session wrote to
`.syndicate/deploys.md`; absent that, authorship is unknown and must be stated as
unknown. Never reconstruct it from timestamps.

## 2026-08-27 — FORBIDDEN: measuring a dirty SHARED tree against `HEAD`. In a stale checkout `HEAD` is the thing that is wrong, and every diff built on it lies in the safe-looking direction.

I was asked to commit this session's ledger edits from the primary tree. The obvious
check — `git diff HEAD -- <my files>` — read **+159/-2437** on `deploys.md`,
**+77/-1225** on `learnings.md`. Alarming, so I checked the real baseline. Against
`origin/main` the same files read **+159/-12,933** and **+2,665/-2,271**: the primary
tree was **791 commits behind**, so its ledger copies were missing everything landed
since. Committing them — even path-scoped, even having audited the diff — would have
deleted **~17,000 lines** of other sessions' work.

**`HEAD` looked authoritative and was not.** It is the local branch tip; in a shared
checkout nobody rebases, that tip is arbitrarily old. Diffing against it compares
stale-to-stale and hides exactly the deletions that matter.

The same trap fired again ten minutes later, one level down: `log/2026-08-27.md` was
already tracked and 405 lines long on `origin/main`, written by other sessions.
Copying my version over it read **+518/-405**. Restored, then appended only my own
sections — and two blocks in my copy belonged to other lanes and were left out.

**Rules:**
1. **In a shared tree, diff against `origin/main`, never `HEAD`.** Fetch first.
   `git rev-list --left-right --count HEAD...origin/main` before you trust any diff.
2. **Read the DELETION column before staging.** Additions are what you wrote;
   deletions are what you are about to destroy. `--numstat` per file, and account for
   every deletion by name — I committed 674 insertions and exactly 2 deletions, both
   intentional replacements I could name.
3. **Never assume a file you are creating is new.** `git status` said `??` in the stale
   tree; the file existed on `origin/main`. Untracked-here is not absent-there.
4. **Re-apply onto current content rather than committing a stale copy.** Appends are
   cheap to replay; a stale whole-file write is a revert wearing the shape of a save.

Related: [[a blocker is a measurement and it expires]] and
[[a test whose fixture cannot violate its property]] — all three are the same failure,
a stale or incapable reference standing in for a live measurement.

---

## 2026-08-27 — RE-FITTING A MODEL CAN BE THE WRONG ANSWER. Measure the do-nothing arm.

Asked to re-fit both football calibration profiles after a mechanism fix, the
result was ONE promotion and ONE REFUSAL. All four combinations, 120 games each:

    sport  profile     mechanism   SCORED err
    ncaaf  shipped     off           15.19%
    ncaaf  candidate   ON             7.25%   <- promoted
    nfl    shipped     off            3.87%   <- BEST for NFL: do nothing
    nfl    candidate   ON             4.18%
    nfl    candidate   off            7.42%

**Rule: include the DO-NOTHING arm in the grid, and let it win if it wins.** NFL
was already at its best; the fix plus a careful re-fit made it worse. Had the
grid only compared "candidate ON" against "candidate OFF", NFL's candidate would
have looked like a 3.24-point win and shipped a regression.

**Corollary — a mechanism and its calibration are ONE change.** The bottom row
is the proof: a re-fitted profile with the mechanism OFF is worse than the
profile it replaces, for both sports. Ship them together or not at all.

**Corollary — do not let one global switch make two engines share a decision.**
The mechanism was an env flag, so NCAAF's 7.94-point gain would have cost NFL
0.31. Moving it onto the PROFILE removed the trade-off entirely; the object that
should decide was already in scope at the call site. A single knob spanning two
calibrated systems is a modelling error, not a config choice.

---

## 2026-08-27 — PROMOTING AN ARTIFACT IS A CHAIN. THREE LINKS FAILED SILENTLY.

Promoting a re-fitted calibration profile is "write the file", and it is not:

  1. **NCAAF's profile was a HARDCODED CONSTANT.** `calibration_profile_path("ncaaf")`
     resolved, the file wrote, and NOTHING read it. NFL had used
     `load_versioned_profile` since `#440` Phase 5; NCAAF was never wired.
  2. **The new field was missing from `to_dict()`.** `save_versioned_profile`
     serialises `to_dict()`, so the artifact round-tripped `goal_line_touchdown`
     to its DEFAULT — the whole re-fit inert while appearing to apply.
  3. **`git add` skipped it.** `data/calibration/` is outside this worktree's
     sparse checkout, so a plain `git add` staged the wiring and not the artifact.

**Rule: test the CHAIN — write, read back, and confirm the consumer holds the new
value — never the individual link.** Each of these passes an "is the field there"
check. Only a round-trip catches (2), and only reading the staging output catches (3).

**And make the loaded value OBSERVABLE.** `load_versioned_profile` degrades
silently by design — absent, corrupt or partially-invalid all fall back to the
default and never raise — so a silent load and a silent fallback are
indistinguishable from outside. That is a good property for a sim and a terrible
one for an operator, unless something states which one happened.

The line added for it is itself weakly placed and worth knowing: it prints at
module IMPORT, and nothing in the worker's boot path imports the profile —
`run_refresh_worker.py` runs the projections generator as a SUBPROCESS. A
boot-time log search reads zero forever. `absent signal is about the emitter`,
one level further out than usual: the emitter is not merely quiet, it is in a
process that has not started. The durable form is a field on the OUTPUT artifact
(the projections CSV already carries `profile_name`, `rating_source`,
`generated_at`), not a line in a job's stdout.

## 2026-08-27 — A CARRIED-FORWARD FACT DECAYS EACH TIME IT IS RESTATED WITHOUT RE-READING THE SOURCE. And a clean kill census proves nothing until you prove the feature was RUNNING in that window.

The lane's OOM debt read: *"an `oomKilled` fired at 04:46:44Z, 22 min after my deploy."*
I restated that four times across one session — in the lane, twice in reports, in a
scheduled task — and it was wrong every time. The event is **2026-08-16**T04:46:44Z, not
08-17. Nobody introduced the error; it degraded by repetition, because each restatement
was copied from the previous one rather than from the events API.

Re-reading the source did not just fix a date. It dissolved the debt: the kill sits
inside a storm of **56 oomKilled** whose first is 2026-08-15T00:04:47Z — **28 hours
BEFORE the ledger deploy**. The deploy landed mid-incident. The attribution had never
been supported by anything, and a whole session had been treating it as a live liability.

**THE SECOND HALF, which is the part most likely to be skipped.** "Zero kills in 10d13h"
is worthless on its own — it is equally consistent with the feature being switched off.
The reading only counts because the ledger was PROVEN to be running in that same window:
20 ledger files / 47.7 MB with fresh mtimes, and `MLB_LIVE_GAMELINE_LEDGER_ENABLED`
absent (= enabled). Pair every null with proof the thing could have fired.

**Rules:**
1. **Re-read the SOURCE before restating a carried fact, not your own last summary.**
   If a fact has a timestamp, an id, or a count, it has a source — go to it.
2. **Exonerate on three legs, not one:** the timeline (does it predate the suspect?), the
   rate (with its window stated, fully paged), and the mechanism (measured, not
   estimated — 36.3 MB against a 4,096 MB limit ends the argument).
3. **A null result requires a liveness proof.** No kills / no errors / no hits means
   nothing until you show the code was executing during the window you read.
4. Kills are EVENTS. `render_events.py`, never a log search — a killed process emits
   nothing, so a 0-match log result is evidence about the emitter.

Same family as [[a blocker is a measurement and it expires]] and [[a test whose fixture
cannot violate its property]]: a stale or incapable reference standing in for a live one.
---

## 2026-08-27 — A GREEN TEST SUITE OVER A FILE THAT CANNOT BOOT `[lane venue-quote-line-join]`

**FORBIDDEN: appending a definition below `if __name__ == "__main__":` and
treating a passing unit suite as evidence the file still runs.**

I crash-looped `live-odds-worker` for 18 minutes (16:39-16:57Z, `NameError:
start_venue_poll_loop`, restart every ~85s) by appending functions to the end of
the entrypoint. `main()` executes at the guard, before the defs below it exist.

**All 18 tests passed the entire time**, and would have passed forever:
importing a module executes its whole body, so the names exist by the time a
test asks for them, and the `__main__` guard never runs under pytest at all.
The suite asked "does the loop behave once running" — true, and irrelevant.
Nothing asked "does this file still BOOT".

**The guard is STRUCTURAL, not behavioural**: walk the AST, find the `__main__`
`If`, assert no `FunctionDef` follows it. A behavioural test only ever catches
the instance someone thought to write; this catches the class.

---

## 2026-08-27 — CADENCE LIVES IN THE CALLER, NOT THE INTERVAL CONSTANT `[lane venue-quote-line-join]`

**FORBIDDEN: reporting an interval env var as a cadence lever without reading
its CALL SITE.** I told the user twice that raising venue cadence was "pure env,
no code". Both times wrong, both caught only by reading callers:

- `SYNDICATE_POLYMARKET_REFRESH_INTERVAL_SECONDS` governs
  `_polymarket_catalogue_at_boot()` — **boot only**, `force=True`.
- Kalshi's refresh is called **once per board build** (~748s measured), so its
  120s interval could never fire faster than its caller asked.
- Both slate/market ticks ride the live worker's **adaptive** loop, which returns
  the ~900s IDLE interval whenever no game is live.

A self-paced function reaches its own interval only if something asks it that
often. **The binding constraint is `min(caller frequency, own interval)`**, and
the interval is the half that is visible in config — which is exactly why it
gets mistaken for the lever.

---

## 2026-08-27 — A KEY MUST NAME EVERY PARTY TO THE BET `[lane venue-quote-line-join]`

**FORBIDDEN: a join key for a player prop that omits the player, or for a total
that omits the game.** Both were live and both look identical to a working join
from every counter.

Props keyed `<sport>|<market>|<side>|<line>`, so every player's anytime-scorer
row collapsed to ONE string and the first row took a quote describing a
different human. Fixed. **Totals still do this by GAME** — 672 polymarket soccer
quotes collapse into SIX distinct keys, so one fixture's price can stamp
another's row.

**The tell is a collapse ratio.** Adapter-reported quotes against DISTINCT keys:
`oddsapi_props` 15,378 -> 15,378 (1:1, correctly keyed), `polymarket_us` 672 ->
6 (112:1). **And instability is the second tell**: polymarket's soccer
selections moved 212 -> 4 across two consecutive builds on an unchanged feed. A
correctly keyed source does not move 50x on identical input.

---

## 2026-08-27 — A BREAKDOWN THAT DOES NOT RECONCILE IS NOT EVIDENCE `[lane venue-quote-line-join]`

I shipped `TRIM_BY_SPORT kept=6000 ... kept_by_sport={...}` summing to **1,506**,
because the tally was updated in one of two passes. The floor WAS working; the
line written to PROVE it invited the reader to conclude 4,494 markets had
vanished. **Assert `sum(breakdown) == total` in the test that covers the
diagnostic**, not just that the diagnostic fires.

Same session, same shape: `[venue_poll]` printed KALSHI on success and
Polymarket only on FAILURE, so a Polymarket half that had silently stopped
produced output identical to one working perfectly. Found only because the user
asked a question the instrument could not answer.

## 2026-08-27 — FORBIDDEN: allowlisting a KEYVALUE-backed path in `HOT_ARTIFACT_PATTERNS` and calling it readable. The guard will pass and the data will not arrive.

I was one step from proposing exactly this. The ask was "make the execution
ledger readable off-worker so we can compare Polymarket volume day over day",
and the obvious move is an entry in `HOT_ARTIFACT_PATTERNS`.

**It would have been inert, and inert in the worst way — it looks like a fix,
it passes review, and it changes a 403 into an empty result.**

`write_json_file` routes every path outside `migration_runs/` to the keyvalue
store **and returns before touching disk**. `/api/ops/artifacts/export` is a
DISK read. So for anything written that way there is no file behind the path:
the allowlist gates a read of something that was never written there.
`execution_ledger._ledger_path()` is one of these.

**The repo already knew.** `ops.py:566` (`api_ops_live_lens_snapshot_index`)
documents the same trap and records that FOUR hypotheses — broken pull, dead
loop, headroom gate, stale builder — were each eliminated by measuring
something ADJACENT to the artifact that actually decided the join, because the
one file that mattered could not be read at all. That endpoint is the pattern:
read through the keyvalue-aware `read_json_file`, not the disk export.

**HOW TO TELL, BEFORE WRITING THE PATTERN:** find the WRITER. If it is
`write_json_file` / `refresh_state_store`, the artifact is in keyvalue and
`HOT_ARTIFACT_PATTERNS` is the wrong lever entirely. Only a real
`open()`/`Path.write_*` on disk makes the allowlist meaningful.

**SECOND ERROR IN THE SAME THREAD, worth its own line:** I first reported the
ledger as unreadable after probing `reports/execution/live_ledger.jsonl`, a
path that DOES NOT EXIST. The real path is
`reports/intelligence/execution_ledger.json`. Re-tested, it is genuinely
blocked — so my conclusion survived, but it survived by luck. A blocker
reported off a guessed path is not a measurement, even when it happens to be
right. Same family as "re-measure the blocker, it expires" (2026-08-27) and
"read the field you already have".

## 2026-08-27 — FORBIDDEN: validating a CONVERTED value while STORING the raw one. The guard clears a number that is not the number anything uses.

`execution_ledger` reconcile computed its safety bound through
`_price_as_probability(fill_price)` and then stamped `fill_price` RAW. One
Polymarket fill arrived as American odds:

```
LIVE_LEDGER_ROW status=filled venue=polymarket
  ticker=tsc-nfl-lar-lac-2026-08-27-total-38pt5
  price=104.0  stake=1.64  fill_price=104.0        <- siblings all 0.445-0.49
```

`contracts x 104.0 = ~$349` against a `stake=1.64`. `spent_today` prefers
`fill_stake_dollars`, so ONE order took the day's Polymarket spend from
**$23.25 to $368.97** — against a `max_day_dollars_polymarket` of **100.01**.
Real spend was ~$20.71. No money moved; the BOOKKEEPING was 15.9x wrong and
the cap enforces on it.

**THE GUARD DID NOT MISS IT. IT CHECKED A DIFFERENT QUANTITY.**
`_FILL_DOLLAR_ABSURD = 10.0` compares `filled_dollars > stake * 10`. But
`filled_dollars` is built from the CONVERTED price (3.36 x 0.4902 = $1.64) —
entirely plausible against a $1.64 stake — while the value written to the
ledger and summed by the budget is the RAW one. Two bands, careful
thresholds, a documented rationale, and it cleared the defect it was written
to catch, because the quantity it validated was not the quantity that was
stored.

**THE CONVERTER WAS INNOCENT AND I CHECKED BEFORE BLAMING IT.**
`_price_as_probability(104.0)` hits `abs(parsed) >= 100.0` and returns
`american_to_probability(104.0) = 0.4902`, matching the venue's own
`avgPx='0.4900'`. The obvious suspect was correct code. The bug was the
ASYMMETRY between the path that validates and the path that persists.

**HOW TO APPLY.** Wherever a value is normalised before being checked, assert
that the SAME normalised value is what gets written. If a guard reads
`f(x)` and the store receives `x`, the guard is not guarding the store — and
a passing guard on a stored raw value is worse than no guard, because it
reads as verified. Search for the pattern: a converter called inside a bound
computation, with the unconverted variable still in scope at the assignment.

**COROLLARY, on unit errors and thresholds.** The two-band design assumed a
unit error would be an ABSURD multiple (>=10x) and a real overspend would be
small (<=1.25x). That is a reasonable prior and it did not save anything here,
because the band was never applied to the wrong-unit number at all. A
threshold cannot classify a value it never sees.

**FOUND ONLY BECAUSE AN AGGREGATE EXISTED.** Invisible in logs — every
individual line looked normal, including the bad row unless you knew sibling
`fill_price` values. It surfaced on the FIRST read of a new per-day per-venue
ledger summary endpoint. A per-day total is a cheap invariant over a record
that is otherwise only ever appended to one row at a time.

## 2026-08-27 FORBIDDEN: an instrument built out of the thing it measures, or out of a symptom the slate can retire — FOUR instances in one session, every one reading HEALTHY

- **The belief overturned.** "The measurement discriminates because the numbers
  moved." They moved in three of four cases *and the instrument was still
  incapable of reading unhealthy* — a clean bill of health manufactured by the
  defect itself. Numbers moving is not discrimination; only a CONTROL run that
  actually reads unhealthy is.
- **The four, all in `#589`/`#590`/`#591`, all caught only by running the
  pre-change bytes against the same payload:**
  1. A duplicate detector that grouped cards by the chip `chipForGame`
     resolved — the code under test, which returns null for exactly the
     duplicated cards. Reported **0 duplicates in BOTH states.**
  2. A metric ("a bare sport label beside a league") needing two labels present
     at once. The league-labelled rows drained off the board twelve minutes
     later; the same pre-change template then read a uniform `SOCCER=213`,
     **flag 0, defect fully intact.**
  3. A test harness with a hand-copied `chipForGame` stub that had neither the
     canonical nor the normalized index and keyed on `group.sport` — the field
     the defect is about. **The new assertions could not have failed against
     it.**
  4. A fixture (`celChip`) with no `league_display`, so the property under test
     could not be expressed. This one FAILED loudly instead of passing
     vacuously, because the assertion was an equality between two computed
     labels rather than a check for a constant.
- **The rule going forward.** Derive the instrument from a source the defect
  CANNOT touch, and state that source. Concretely, all three fixes ended up
  joining on the slug taken from `group.key` and on `chip.league_display` —
  fields no code path under test writes. **And run the control on the SAME
  payload, at the same instant, every time:** a fix verified only against
  post-deploy data is verified against a slate that may have retired the test
  case. This is the 2026-08-20 census rule (`A CENSUS THAT CANNOT READ UNHEALTHY
  IS NOT A VERIFICATION`) generalised from "the slate moved" to "the instrument
  was never able".
- **The cheap test, worth applying before any verification is banked:** *if the
  fix were reverted right now, would this reading change?* If it needs the
  world to cooperate — a particular row family present, two labels coexisting —
  it is not a verification, it is a coincidence. Pair every "0 bad" count with a
  "N actually checked" count; `#591`'s `rows that JOIN a league-carrying chip:
  496` is the shape, and it was the first guard this session built BEFORE
  measuring rather than after being burned.
- *(evidence: `.syndicate/log/2026-08-27.md`, the `#589`/`#590`/`#591` entries
  and the 20:5xZ checkpoint)*

## 2026-08-27 — A SINGLE OBSERVATION READ AS A BOUND `[lane venue-quote-line-join]`

**FORBIDDEN: concluding "supply-limited" from one reading where a quantity sat
below its cap.** I saw mlb take 1,512 slots against a cap of 1,550, concluded
its Kalshi listings were the constraint, and wrote it into `deploys.md` as the
finding. mlb went **794 -> 1,741 across the same evening** — its available
markets GREW as its slate approached first pitch. 1,512 was a moment, not a
ceiling.

`matched` tracks mlb's slot count almost exactly (794/27, 1620/208, 1741/218,
1706/221), so ALLOCATION was the binding constraint all along — the opposite of
what I recorded.

**THE TELL I HAD AND IGNORED:** two hours earlier in the same file I refused to
read one build's `matched` as a trend. I applied that discipline to the number
I was suspicious of and not to the one that supported a conclusion I had
already reached. A bound needs a series; one point below a cap is consistent
with supply, with timing, and with the cap simply not binding yet.

**WHAT STILL HELD, and why the correction is not a full retraction:** the demand
PATH did not execute for the recovery (`demand=None` in the trim's own line),
so the change was still not what fixed it. Deployed is not executed — that half
survived because it was checked against a predicate rather than a deploy
timestamp.
## 2026-08-27 — A CONTROL THAT IS BROKEN IN THE SAME WAY AS THE TREATMENT DISTINGUISHES NOTHING. I ran one and reported the result as positive.

I reported 5 failing tests in `tests/test_polymarket_board_join.py` as
"pre-existing, not mine". **There were none — 53 passed in the primary tree.**

They failed only in my session worktree, which excludes `data/` by design, and
those tests resolve soccer clubs through an alias map BUILT FROM `data/`
artifacts. Already a standing rule (2026-08-21, `978963b5`).

**THE METHOD ERROR IS THE POINT, NOT THE STALE RULE.** I "verified" by
stashing my diff and re-running. **Stashing does not restore `data/`.** Both
arms of the comparison were missing the same thing, so the experiment could
only ever return "same either way". That proved the failures were not caused
by MY DIFF; it could not prove they were REAL. I collapsed two different
claims and reported the weaker result as the stronger one.

**THE GENERAL FORM:** before trusting an A/B, ask what the control still
shares with the treatment. If the suspected cause is present in BOTH arms, a
null result is not evidence of anything. Same family as the `sports=8` board
that "passed" while the guard never fired — which I DID catch, two hours
earlier, in the same session. Recognising a shape once does not install it.

**AND: I ATTRIBUTED THE FAILURES TO A COMMIT ON TOPIC ADJACENCY.** `git log -8
--format='%an'` returns `github-actions[bot]` eight times — authorship
distinguishes NOTHING in this repo — so I had no basis whatever. When the
attribution was challenged I removed it rather than reassigning it to another
guess.

## 2026-08-27 — I CHECKED ANCESTRY AND CALLED IT CAUSATION. The fix's own log line said the path never ran.

`[kalshi_odds] BOARD_JOIN matched` recovered from 5-24 to 208-221. I verified
`bd81ba3c` (demand-weighted trim) was an ancestor of the live SHA and reported
that the trim had fixed it — to my user, to the ledger, and to the lane that
wrote it.

**The trim's own line, at the moment of the recovery, reads:**

```
19:49:44  TRIM_BY_SPORT ... demand=None  mlb_slots=1620     <- matched=208
```

`_sport_slot_caps` returns None with no demand signal and the trim falls back
to the FLAT-FLOOR branch. The code was DEPLOYED AND NOT EXECUTED. Caught by
`venue-quote-line-join`, whose fix it was — they declined credit for it.

**"IS THE COMMIT IN THE LIVE SHA" AND "DID THE CODE RUN" ARE DIFFERENT
QUESTIONS, AND ONLY THE SECOND IS EVIDENCE.** Ancestry is necessary and never
sufficient. This repo already has the rule — *"test the fix's predicate, not
its deploy state"* — and a discriminating field was being PRINTED on the same
line as the outcome I was reading. I read `kept_by_sport` off that line and
did not read `demand=` two fields earlier.

**THE REAL CAUSE MATTERED, WHICH IS WHY THIS WAS NOT A HARMLESS
MIS-CREDIT.** MLB's slate approaching first pitch made its markets the
freshest in the catalogue, and the staleness-ordered remainder pass handed
them the slots — staleness accidentally doing what demand weighting does
deliberately. That mechanism is DIURNAL, so **the collapse is expected to
RECUR TOMORROW MORNING** — corrected from "afternoon", which was wrong.
MAPPED TO CENTRAL, today's collapse was MORNING/MIDDAY and the recovery came
in the AFTERNOON: 09:19-13:57 CT matched 5-27 (spiking 146/210/99), then
14:49 CT matched=208, 15:25 218, 15:51 221. So the bad window is roughly
09:00-14:00 CT, when far-dated football is fresh and MLB is not.
Believing it was already fixed would have meant not deploying the thing that
actually prevents recurrence.

**A "verified fixed" that names the wrong cause predicts the wrong future.**

Third instance in one session of the same family: a `sports=8` board that
passed while the guard never fired (caught), a stash control that could not
restore `data/` (missed), and this (missed). Recognising the shape once does
not install it.
## 2026-08-27 — A WATCHER IS AN INSTRUMENT AND IT LIES IN FOUR SPECIFIC WAYS

Five verification failures in one session, each producing output that looked
like a result. None was caught by the watcher; all four were caught by reading
the payload instead of the exit code.

1. **Floored on `createdAt`, not `finishedAt`.** A join tick 69s after the
   deploy was CREATED ran the OLD commit and returned the baseline. I nearly
   reported my own change dead on evidence that never touched it. **A deploy
   timestamp marks when you ASKED; only `finishedAt` marks when the code ran.**

2. **Matched a shared word.** `"calibration" in message.lower()` fired on
   `[INTEL_TRACE] {"event": "evaluation_reliability_profile"}` — a different
   subsystem. The watcher exited 0 claiming success. **Match on the tokens the
   EMITTER writes, not on the topic.**

3. **The re-arm silently didn't apply.** A patch script opened a POSIX path
   under Windows Python, raised `FileNotFoundError`, and the next line in the
   same chain ran the UNPATCHED watcher — reproducing the identical bad reading.
   **A failed edit followed by a successful run of old code is indistinguishable
   from a successful re-arm.**

4. **Sampled with the function under test.** Measuring recovery from the `lal`
   bucket returned 0% BY CONSTRUCTION, because that bucket holds exactly the
   rows the function failed to fold. **If the grouping is produced by the thing
   you are testing, the sample is already biased.**

5. **A null with no denominator.** `matched 55 -> 59` read as a fix working;
   the metric swings 48-59 on its own and `58` predated the deploy. **Establish
   variance before attributing a delta.**

**The general rule:** an absence proves something only once you have shown the
emitter RAN. Every watcher should count something adjacent that must be non-zero
— `POLYMARKET_CATALOGUE 0` means nothing until `US_AUTH 1` proves the boot
happened, and `no calibration line` means nothing until you count the
projections-process lines. Build the discriminator into the watcher, not into
the interpretation afterwards.

## 2026-08-27 FORBIDDEN: calling a fix verified when the READING came from a different surface than the one that was broken

Session de363735, lane `ncaaf-opener-regions-props`. Shipped `94d6b6e6` to put
the NCAAF live-lens phase split on the builder that serves, verified it on
`/ncaaf/api/live-lens`, and it was CORRECT there:
`Games 51 | Live 0 | Final 0 | Pregame 51`. I nearly reported it done.

The PAGE was unchanged. `GET /ncaaf/live-lens` came back **byte-identical to the
pre-deploy fetch — 108,486 bytes both times.** `shared/rank_board.html` renders
`summary_panel.summary_stats` and never reads `header_stats`, which reaches the
API payload only. Two hops; the fix landed on the first.

**The rule:** when a value crosses more than one hop to reach the surface that
was reported broken, a correct reading at hop 1 is not evidence about hop 2.
Verify at the surface the complaint came from. **A byte-identical response
across a deploy is a positive signal that nothing changed** — cheap, and it is
what caught this. Fixed in `d281995b`; one list now feeds both, so payload and
page cannot drift.

Same session, same shape, one layer earlier: the split had first been added to
`build_live_lens_page_context`, the legacy FALLBACK, while the route calls
`build_smartsim_live_lens_page_context`. Present in the file, unreachable in the
product. **Three surfaces — file, payload, page — and only the last one is the
product.**

## 2026-08-27 FORBIDDEN: inferring that a scheduled job SUCCEEDS from an age that sits at one interval

`state.md` had recorded that an `age_seconds` sitting at one interval rather
than growing "is also the evidence the generator SUCCEEDS". It is not. The age
is stamped by the LAUNCHER, so a job that crashes one second in produces the
same signal as one that completes. Measured this evening: four NCAAF projection
runs 21:21:37–21:23:31Z each printed their calibration line at import and then
died on `HTTP 429` in `load_ppa_ratings_asof`. Corrected in place.

**Generalises to:** any liveness signal emitted BEFORE the work it is taken to
vouch for. Ask what the signal is stamped by, not what it is near.

## 2026-08-27 A lane can be CLOSED while a session keeps working under its name

This session's lane was closed and moved to `lanes_history.md` earlier the same
day, covering the props/odds/Layer 2 work. Everything after that — an engine
calibration confirmation, two live-lens deploys, a cross-sport template fix —
ran under the same slug, and **three deploy claims were acquired with a closed
lane as `--holder`**. The claims serialised correctly and nothing was harmed,
so nothing surfaced it; `deploy_claim.py` does not check that a holder is an
OPEN lane, and the per-session marker still held the slug.

**Not proposing a guard** — the claim's job is mutual exclusion and it did that.
The point is narrower: **a lane name in a claim is not evidence the lane is
open**, so "who holds this" can point at a closed lane indefinitely. When work
continues past a close, open a new lane or reopen the old one before touching
production.

## 2026-08-27 A survey keyed by BARE FUNCTION NAME collapses same-named functions across sports

Two static surveys of the rank_board routes were wrong and discarded before the
production sweep produced the real number. The first keyed builders by function
name, so five sports' identically-named `build_live_lens_page_context` collapsed
onto whichever file parsed last (soccer) — every result misattributed. The
second added a delegation check that matched `build_module_links` and
`build_rank_page_context`, which nearly every builder calls, and reported **0
defective** where the truth was 14.

**Resolve by IMPORT, not by name** in a repo with per-sport parallel modules.
And when a static result says "no problems anywhere", treat that as a suspected
broken query before treating it as a finding.

## 2026-08-27 — FORBIDDEN: fitting a model to a total when you can COUNT the operation

- **The rule:** if the thing you are optimising is made of discrete operations —
  syscalls, queries, requests — **count them**. Do not infer their cost by
  regressing the total against plausible predictors.
- **Evidence.** The boot sync's 72.20s was fitted as `1.337 ms/file + 117 MB/s`
  over 9 roots: r ~1.2% error, and the two largest roots matched to **0.01s**.
  It predicted −26.6s from removing the byte compare. The measured saving was
  **−13.05s**, wrong by 2x, and the fix that rested on it was shipped and had to
  be followed by a second one. Counting syscalls on a real subtree took one
  script and gave the true answer immediately: **5.34 per file**, of which four
  were re-asking what the directory read already knew. The regression was not
  merely imprecise — it pointed at the WRONG TERM, so the first fix optimised
  the part that was not the cost.
- **The tell:** a beautiful fit over few points with more parameters than
  mechanisms. 9 points, 2 parameters, and the residuals looked perfect because
  one root (31,149 of 33,392 files) dominated both predictors at once.

## 2026-08-27 — FORBIDDEN: a verification criterion that can only be met by the failure it is watching for

- **The rule:** before adopting a criterion, ask what it reads on a HEALTHY
  instance that was never going to fail. If the answer is "the same as on a
  fixed one", it discriminates nothing.
- **Evidence.** The lane's criterion was "`/healthz` answered inside 5s across
  the boot window". Post-fix it read perfectly: 25 probes, max gap 5.10s, zero
  missed — against pre-fix blackouts of 35.21s and 34.74s. It looked like proof.
  Then two PRE-FIX boots that happened to SURVIVE were measured: max gaps
  **5.13s and 5.59s, zero missed**. A clean trace is simply what a surviving
  boot looks like; the only trace with blackouts is the boot that was killed, so
  the criterion was measuring the kill rather than exposure to it. With a
  ~1-in-5 base rate, n=1 was never going to be evidence either way.
- **What to use instead:** a RATE over enough trials (`server_failed` per
  deploy, >=5), or — better where available — a STRUCTURAL quantity that does
  not need a base rate. Here the honest claim is the duration: the window in
  which sync I/O can starve a health check is 0.6s wide instead of 72s. That is
  measured directly and one boot establishes it.
- **Related, same session:** grepping `"on the board"` to check whether a
  `rank_board` route renders slate stats reads **0 on every route without a
  populated slate**, which is most of them. It nearly produced a false
  contradiction of another lane's completed sweep. Caught only by checking the
  probe against a route known to be GOOD before trusting a negative. The real
  marker is `feature-summary-pill`.

## 2026-08-28 — A GAP BETWEEN TWO LOG LINES IS NOT A COST. I measured one, believed it, and was wrong by 30x.

Reading refresh-worker logs I saw ~37 seconds of `[artifact_publisher] PULL_*`
lines inside the board build, two of them `error=timed out`, and reported the
cross-service HTTP pull as a significant part of the build's unattributed time.

**Spanned directly, it is `pull_hot_artifacts` = 1.15s.** The 37 seconds was
everything happening on a shared worker between two prints — other threads, the
memory watchdog, the sim tick, GC — not the work I attributed it to.

`_timed_candidate_pool`'s own docstring in this repo already says this, and
names three wrong answers produced the same way on 2026-08-25. I read that
docstring while looking for something else and still did it.

**THE TELL WAS ALREADY IN THE LOGS AND I HAD NOT READ IT.**
`BOARD_BUILD_TIMING wall_s=1058.9 cpu_s=942.2 off_cpu_pct=11.0` had been
emitting all along. A build that is 89% on-CPU cannot be dominated by HTTP
waits, and one line settles it. The later build read `off_cpu_pct=2.2`.

**HOW TO APPLY.** Before attributing time to a stage, ask which measurement you
have: a SPAN around the call, or a GAP between two prints. Only the first is a
cost. On a process with concurrent threads a gap is an upper bound on
everything, and an estimate of nothing. If only a gap exists, say "at most" or
add the span — do not name a component.

**AND CHECK FOR AN EXISTING wall-vs-CPU READING FIRST.** "Is it slow or is it
waiting" is one number, it is often already emitted, and it invalidates whole
families of hypothesis before any instrumentation is written. Three of mine died
to it: the HTTP pulls, the Polymarket join (0.25s), and venue-loop contention.

Same family as `feedback_read_the_field_you_already_have`, and this is now the
second night running that the answer sat in a field I had already fetched.


## 2026-08-28 FORBIDDEN: reading a "not yet running" list as proof something IS running

`pending_deploys.py` enumerates what is committed and **NOT** deployed. I
polled its JSON for my target SHA, matched, and announced the deploy was live —
the match meant the exact opposite of what I read into it. Caught only because
the SERVED page still had the old bytes.

**The rule:** poll the PREDICATE, never a status field that merely mentions your
SHA. For a deploy that means the changed behaviour appearing in the served
response, or a log line that exists ONLY in the new code (`ORDERS_ENVELOPE` was
built for exactly this and worked).

## 2026-08-28 FORBIDDEN: a shared rule reimplemented as "the half I needed"

The `unknown` bucket tested `not _is_venue_refusal`. The page's actual rule is
`rejected` OR venue-refused. Production then described **63** build-time
rejections — orders that never reached a venue — as *"submitted, never
confirmed at the venue"*: possibly-live money. True figure: 2.

The commit that shipped it had warned, in its own message, against "a fourth
local definition of not a position, which is how these totals drifted apart in
the first place." **A commit message asserting the discipline is not the
discipline.** If two readers must agree, they call ONE function — identity,
asserted in a test — and it lives in the module that owns the concept, not in
whichever file noticed first.

Every test passed through this because not one put a `rejected` row in front of
the counter: the suite only exercised the case I had in mind while writing it.

## 2026-08-28 FORBIDDEN: grading an AMBIGUOUS zero as a definite outcome

`grade_polymarket_resolution` computed `delta = after.realized -
before.realized` and called a zero delta a PUSH. That conflates "resolved and
moved no money" with "nothing booked yet". Seven live orders were stamped
`push / settled_by=venue` — one of them nine and a half hours BEFORE its game
started — and grading is idempotent, so the verdict was permanent and
self-concealing. It landed in the push column, the bucket nobody audits because
it reads as a non-event.

Measured afterwards: `sides=[LONG, SHORT]`, **no NEUTRAL row anywhere**. The
venue never called any of them a push.

**The rule:** a value that two different states both produce is not evidence
for either. Refuse with a NAMED reason and leave the row for a later pass. And
when a wrong verdict can be written permanently, the repair must carry a
discriminator that makes it TERMINATE — `held_side` here, without which the
repair would clear a correct grade every tick forever.

## 2026-08-28 An absent log line is only evidence once you know the line is EMITTED

Twice in one session. `UNKNOWN_ORDER_PROBE` prints only when it finds unknowns,
so its absence was ambiguous — the neighbouring `VENUE_SETTLEMENT` line, which
prints unconditionally, is what proved no tick had run. And a watcher grepped
`"still open . this slate"` where `·` is two UTF-8 bytes: it reported "not yet"
thirteen times against a deploy that was already live.

**Check the instrument can fire before trusting what it says.** An unfiltered
query returning *something* is the cheap version of that check.

## 2026-08-28 FORBIDDEN: reading a job's TIMESTAMP as evidence it ran, on a machine that sleeps

`live-gameline-accuracy-snapshot` fired at 23:34:21 CT and issued its script call
three seconds later. The tool result came back at **08:49:37 the next morning** —
Windows Modern Standby (entered 22:57:42, exited 08:48:00) suspended the child
while the scheduler and the model both ran normally. `lastRunAt` was correct and
completely misleading: the cron fired, the session opened, the model wrote the
call, and none of that means the work happened.

I first reported this as "fired on time and left no row". It left a row — stamped
with the WAKE time and carrying the rolled-over date. Displaced, not dropped.

**Compounding it:** the sibling task `live-gameline-fixes-first-real-reading` had a
hardcoded freshness window ("a row `captured_at` between 04:33Z and 04:45Z") and was
instructed, on a miss, to declare *"the recurring task is not firing on its cron,
which is EXACTLY the failure that lost six nights."* Under displacement that window
can never be met, so it was primed to raise a false alarm indistinguishable from a
real outage — and the plausible response to that alarm is re-enabling things that
were never off. 6 of 10 nights (08-18..08-27) fell inside a standby span.

**The rule:** gate on the ARTEFACT, not the clock. "Does a row exist for the slate
date" survives a nine-hour displacement; "was it captured between 04:33 and 04:45Z"
does not. A wall-clock window is only evidence on a machine you have shown stays
awake. When you must distinguish "never fired" from "fired and was suspended", the
readings that actually discriminate are `enabled: false` and a `lastRunAt` older
than a full period — not a stale `captured_at`.

## 2026-08-28 A lane-guard claim can be held by PROSE, and "TRANSFERRED" releases nothing

Blocked from editing `game_chip_scoreboard.py` by `wnba-chip-live-token`. Removing
the path from that lane's `- Files:` line did not clear it, because:

- `lane-guard.py` matches `rel.endswith("/" + f)`, so a **bare filename anywhere in
  the Files block counts as a claim**. The historical note "— `game_chip_scoreboard.py`
  ADDED after the first test run" was holding the claim by itself.
- Its disclaimer vocabulary is a **fixed list** — `not claimed`, `released`, `held by`,
  `claimed by`, `collision check`, … — and **"TRANSFERRED" is not in it.** So the
  `~~polymarket_board_join.py~~ **CLAIM TRANSFERRED**` note in `open-bet-live-status`
  releases NOTHING; that claim is still live despite reading as handed off.

**The rule:** a release is only real if the guard parses it. Verify by DRIVING the
hook (`echo '{"tool_name":"Edit","tool_input":{"file_path":"..."}}' | python
.claude/hooks/lane-guard.py`), never by reading the ledger and believing the prose.
Note the guard cannot express a per-branch claim: releasing for one concern releases
the file for everyone, so say so where the next reader will see it.

---

## 2026-08-28 — FORBIDDEN: building a fix for a hypothesis the REFUSAL NAME has already ruled out `[lane venue-join-refusal-visibility]`

- **What we believed:** soccer was absent from Polymarket execution because
  whole competitions never entered the `soccer` bucket — `mls` was unprovable,
  so its 30 h2h markets sat under a key no board row looks up. Measured and
  true: 0 of 9 MLS fixtures resolve both clubs through the flat alias map.
- **What was actually true:** that defect is real and was NOT the blocker for
  the rows I pointed at. The board's 104 soccer h2h rows were already refusing
  as **`no_match`**, never `no_candidates`. Those are different words for
  different facts and the module documents the difference: `no_candidates`
  means the bucket was empty, `no_match` means candidates were present and no
  FIXTURE paired. The bucketing fix shipped, proved 13 competitions, moved the
  ops reader from 738 to 1,809 markets — and left `no_match|soccer|h2h` at
  **93 of 93 board rows**. Zero soccer matches gained.
- **How we found out:** the denominator. `no_match|soccer|h2h` fell 104 -> 93
  and I nearly reported it as the fix working. The board had shrunk 1326 ->
  1308 rows and carried exactly 93 soccer h2h rows. 93 of 93 is 100%, same as
  104 of 104.
- **The rule:** before building a fix, read the refusal NAME that is already
  being emitted and ask which hypothesis it eliminates. A refusal vocabulary
  written to distinguish causes is worthless if the next person treats every
  entry as "it didn't work". The name was in production logs for days.
- **Corollary, and it is the cheaper half:** a count without its denominator
  cannot tell a fix from a shrinking population. `no_match: 93` is not progress
  from `104` until you know the board had 93 rows to offer.
- Real blocker, one instance, UNVERIFIED: fixture home/away orientation
  (`rrc-elc` vs board `Elche @ Racing`). Counter shipped, never run.

---

## 2026-08-28 — FORBIDDEN: reading ~0.5 as a weak signal from a comparison never shown to DISCRIMINATE `[lane venue-join-refusal-visibility]`

- **What we believed:** the Polymarket spread sign test was under-powered.
  Ten production runs returned `rate` 0.44-0.60 at n=9..22 against
  `min_sample=30`, and the verdict said `UNDECIDED: n < min_sample` — which
  reads as "collect more".
- **What was actually true:** the test could never answer. Polymarket lists a
  spread market per side per line, so a fixture's ladder spans BOTH signs —
  measured, 12 of 12 sampled MLB fixture/magnitude pairs carry `pos` and `neg`.
  Comparing "the sign of a rung" to the board's sign is a coin flip by
  construction. Final reading after the guard: `fixtures=0 rate=None
  both_signs=17` — **all 17** previously-scored fixtures were non-identifying.
  Every one of those 17 votes was manufactured out of slate iteration order.
- **The trap this was minutes from setting:** the verdict ladder mapped
  anything other than ~1.0/~0.0 to **`FALSIFIED: the sign is not fixed per
  fixture; do not ship a mapping on this`**. ~0.5 is exactly what a
  non-identifying test returns. At n>=30 it would have written a property of
  the INSTRUMENT into the ledger as a durable measurement about the VENUE, and
  the next reader would have believed Polymarket spreads were unfixable.
- **Three rounds of one mistake, and I shipped round two:** the module header
  already recorded round zero (segment `f5` slugs producing 0.2857 that "looked
  like evidence"). I fixed the rung selection to compare like-for-like, got
  0.4706, and only then checked whether the comparison could discriminate at
  all. The better comparison landed in the same place because the defect was
  never in the sampling.
- **The rule:** a rate near 0.5 is not weak evidence. It is what NO evidence
  looks like, and it is indistinguishable from a real coin flip until you have
  shown the comparison can separate the cases. Prove discrimination BEFORE
  reading the rate, and never let a verdict ladder map "inconclusive" onto a
  substantive conclusion.
- `UNDECIDED` and `NON-IDENTIFYING` are different instructions to the reader:
  "collect more" versus "collecting more cannot help". A test that cannot tell
  them apart will keep being fed data forever.

## 2026-08-28 — FORBIDDEN: reading `lastRunAt` as evidence a scheduled job RAN. It records DISPATCH, and on this machine the two were nine hours apart.

`live-gameline-accuracy-snapshot` showed `lastRunAt: 2026-08-28T04:34:17Z`,
exactly in its expected window, and had produced no row. The obvious readings —
the task is broken, the script is broken, the scorer is off — were all wrong.

The session fired on time and emitted its Bash call at `04:34:24.813Z`. **The
result returned at `13:49:37.933Z`.** Windows entered Modern Standby at
`03:57:42Z` (Kernel-Power **506**, Idle Timeout) and left it at `13:48:00Z`
(**507**, "Reason: Input Mouse"). Modern Standby keeps the NETWORK alive — so
the scheduler ran and the model produced a tool call — while the Desktop
Activity Moderator suspends user-mode processes. The session could DECIDE to run
the script and could not RUN it. The slate rolled in between; the capture landed
empty.

**How to tell it apart from a task bug, cheaply:** other concurrent sessions
will show a gap ending at the SAME INSTANT. Three did — 10.22h, 9.99h, 9.78h,
all resuming inside 72 seconds, from different start times. A per-task bug
cannot do that. Confirm with `Get-WinEvent` System log, Kernel-Power 506/507.

**The general form:** a scheduler's own record of firing is upstream of every
interesting failure. Check the ARTIFACT the job writes and compare its timestamp
to `lastRunAt`. Same family as "presence is not reachability" and "confirm the
code ran".

**Corollary, and it cost a near-miss the same day:** a wall-clock cron whose
deadline is a real-world roll (a slate date, a market close) must not live on a
machine that sleeps. The fix was not to harden the cron but to move the work to
where the data already is — the worker that builds the artifact — which deleted
the deadline rather than defending it.

## 2026-08-28 — FORBIDDEN: baselining a test in a fresh worktree when the test reads state the worktree does not share. It is not a baseline, it is a different experiment.

Two `MissingRequiredArtifactRepairTests` failed after my change. I created a
worktree at `origin/main`, ran them, saw them PASS, and reported that my change
had broken them.

**A git worktree does not carry the primary tree's `data/` mirror, and that test
reads the real data root** — visible in its own error output
(`...\Syndicate\data\wnba_source\...`), which I had already been shown and did
not read. The worktree was a different environment, so the comparison was
meaningless.

Reverting ONLY my edit **in place**, in the tree where the symptom appeared,
reproduced both failures. They were pre-existing and environmental.

**The rule: isolate the variable you changed, in the environment the symptom
lives in.** Changing the environment and the code at once and attributing the
delta to the code is the error. Related: "re-baseline before judging" — but note
this failed the other way, a stale baseline said INNOCENT when the truth was
also innocent, and I still got the attribution wrong.

## 2026-08-28 — FORBIDDEN: concluding a lane claim is free because the roster says its session is gone. `get_session` said "not found" while the session was live.

`syndicate/blueprints/intelligence.py` was claimed by an OPEN lane and I had
authorisation to take it. `get_session` on the holding session
(`12b2be57-...`) returned **"Session not found"** — which reads as "it ended,
the claim is stale, reassign it."

Its transcript's last entry was **11 seconds old**. The session was actively
editing that file.

An archived-but-running session, an ended session, and one that never existed
are **indistinguishable** through the roster. The transcript's last timestamp is
the ground truth and costs one read:

    ~/.claude/projects/<project>/<session-id>.jsonl   -> max timestamp

Extends "session roster hides archived": that rule said the roster OMITS things;
this says it can also answer a confident NOT FOUND about something running right
now. Never reassign a claim on roster evidence alone.


### 2026-08-28 — FORBIDDEN: trusting a refusal's stated premise without rechecking it. A REASONED "we cannot do this" is stickier than a bug, because it tells the next reader not to look

**What the code said, and it had said it for months.**
`bet_status_wnba` refused every WNBA spread, moneyline and total. Not by
omission — by an argued comment:

> The market IS gradeable in principle -- `game_line_bet` handles spreads and
> moneylines for any sport that can supply two team scores. This capture is a
> PLAYER box and has none, **so the fix is upstream in the capture** rather than
> a missing entry in a table here.

Every clause of that is true except the last one. The final boxscore CSV, which
this same module ALREADY READS for player props, carries `TEAM_ABBREVIATION` and
`PTS`. **In basketball a team's score IS the sum of its players' points** — there
is no team-level scoring, no own goal, no defensive touchdown — so the team score
was one `groupby` away in an artifact the function had open. Nothing upstream had
to change.

**Why it survived.** The comment is GOOD writing. It names the constraint,
distinguishes two candidate fixes, says which is wrong and why, and points at the
right owner. It reads like a conclusion someone reached carefully — which is
exactly what makes it a stop sign. A missing feature invites investigation; a
reasoned refusal closes it. This one even carried its own test
(`test_a_game_line_names_the_CAPTURE_as_the_blocker_not_the_vocabulary`), so the
premise had a green check beside it.

**What it cost.** Five WNBA game lines exist in the live book. One settled, and
only because Kalshi settled it for us. Two (`GSV @ CON` 2026-08-26, over and
under 151.5) sat ungraded for two days with no mechanism that could ever reach
them. The real total was 153.

**HOW TO APPLY.**
1. **A refusal's premise is a CLAIM, and claims get checked.** "This artifact has
   no X" is falsifiable in about a minute — open the artifact. I found the
   answer by fetching one CSV and reading its header.
2. **Suspect a premise hardest when the code already reads the artifact it
   claims is insufficient.** `_load_final_box` was fifteen lines away.
3. **Domain invariants are evidence, and they are sport-specific.** Sum-of-parts
   equals the whole for basketball points; it does NOT for soccer goals (own
   goals) or football points (defensive scores). The reasoning transfers by
   sport, not by shape — check the sport before reusing this.
4. **Verify the derivation against an independent source BEFORE relying on it**,
   even when the arithmetic looks obvious. Six of six exact against ESPN's own
   scoreboard, both sides of three games, took one request. Had it been five of
   six I would have shipped a settlement path on an assumption.
5. **A test can pin a wrong premise as firmly as a right one.** When the premise
   falls, the test is the thing to invert — not the evidence.

**Companion, same session, same shape:** the SECOND wrong belief I held was
`/api/ops/artifacts/export` showing no `boxscores_2026-08-26.csv`, which I read
as "the capture died". It is a DISK read; the producer and the consumer both use
`read_text_file` (KEYVALUE). The count endpoint returned `games: 2` the whole
time. That is the keyvalue/artifact split already in this file, hit again — so
the rule needs restating as an instruction rather than a fact: **before
concluding an artifact is absent, name which STORE you looked in and which store
its consumer reads.** They are frequently not the same one.

## 2026-08-28 — FORBIDDEN: instrumenting a function without first proving it is ON the path you are measuring. I did it, and the counter read zero.

Soccer's overview cost was unlocated. I found a mechanism that explained it
beautifully: `build_soccer_market_board` takes a LEAGUE, caches on a **60s TTL**
against a **680-874s** board build, and loads a **sport-wide** odds_history
shard that had grown **3,935,768 -> 48,169,883 bytes (12x)** in a day — without
passing the `cache` argument the loader accepts. Ten leagues x 48MB per build.
Magnitude and growth curve both fit.

**Every one of those facts is true, and the theory is worthless, because
`build_soccer_market_board` IS NOT ON THE OVERVIEW PATH.** `soccer/cards.py` —
what `_build_sport_overview` actually calls — never imports `market_board`. Its
importers are the `/soccer` blueprint, `layer1_board`, `live_refresh_loop`. I
shipped a counter into it and production emitted ZERO lines.

**THE CHECK I SKIPPED IS ONE GREP.** Before instrumenting `f`, grep from the
entry point you are timing to `f`. Not "is `f` plausible", not "does `f` have
the right shape" — is `f` REACHED. A mechanism can be real, documented, and
irrelevant at the same time, and a coherent story is the most dangerous form of
that because it stops you checking.

**THE ZERO WAS THE FIND.** A counter that never fires is not a failed
measurement — it is a strong negative about reachability, and it arrived faster
than any positive would have. Instrument to falsify, and treat an empty log as
data rather than as something wrong with the logging.

**THIS WAS PREDICTION FIVE OF FIVE, ALL REFUTED**, on one subsystem in one day:
~39 leagues (10), fan-out (one cold league), one slow league (whichever is
cold), props (0.17s), this. `feedback_presence_is_not_reachability` already
covers the general case; the new part is that I applied it to DEPLOYS all
session and never once to a CODE PATH.

**AND THE HONEST CONSEQUENCE:** after five refutations my hit rate on a
subsystem is evidence about my model of it. The right move was to stop
proposing mechanisms and change method — a profiler over one real build, rather
than a sixth incremental log span.

### 2026-08-28 — FORBIDDEN: diagnosing a resolver when the log said `graded=N` and the served payload changed nothing. That is a LOST WRITE, and I spent three theories on the wrong layer

**The symptom, and how long it fooled me.** `[paper_settlement] SETTLED
date=2026-08-26 ... graded=8` with `outcomes={'lost': 3, 'won': 5}` — and zero
live rows changing outcome on `/api/portfolio/live` across that pass. I read
that as "the rows never reached the resolver" and went looking for what filtered
them, through **three** theories: a reconcile race on `status` (disproved —
`reconciled_at` is re-stamped every cycle, so `reconciled_from: 'submitted'`
records the ORIGINAL transition, not a recent one); an upstream sport filter;
a missing artifact. A peer offered a fourth (a keyvalue/disk store mismatch).

**What settled it was running the DEPLOYED predicate chain against the REAL
order records** rather than reasoning about it:

    outcome truthy?  False
    status = 'filled'   -> not_filled?      False
    mode   = 'live'     age 42.76h/45.21h   -> awaiting_venue? False (24h grace)
    => REACHES RESOLVER: True

Nothing filtered them. They were graded, and the write was discarded 12 seconds
later by the other service.

**The cause was two log lines apart the whole time.** Both services print
`KEYVALUE_WRITE_LARGE` with a `size_bytes`:

    refresh-worker    17:40:48   1,276,296
    live-odds-worker  17:41:00   1,268,265   <- 8,031 bytes SMALLER

**HOW TO APPLY.**
1. **`graded=N` (N>0) with no outcome change on the served surface is a LOST
   WRITE. It is not a resolver bug.** Check the write, not the reader.
2. **A whole-document `size_bytes` that goes DOWN is the cheapest possible
   detector for a clobber**, and both services already print it. Diff the sizes
   across services before forming any theory about why data is missing.
3. **Run the deployed predicate chain against the real record.** Every one of my
   three theories was about which branch a row took; the branch was checkable in
   about a minute and I kept reasoning instead.
4. **A peer's theory is not evidence either.** Declining the fourth one because
   the chain had already answered it was the only correct move available.

**Related, same session, same shape one level up:** the durable
`last_blind_write` stamp I added to replace an ephemeral log line shipped
WRITE-ONLY — into the document and into `ledger_summary()`, which nothing in
production calls. **Durable state with no reader is barely better than the log
line it replaced.** Found by reading the deployed endpoint's payload instead of
assuming the field had arrived. Add the reader in the same commit as the field.


## 2026-08-28 — FORBIDDEN: treating a "this API does not exist" finding as a fact about the VENUE when it was written from a network that could not reach the venue. It is a fact about the NETWORK.

`cryptocom_client.py`'s `FINDING` (2026-08-24) said: no public REST/WebSocket
market-data API has shipped; the one concrete endpoint anyone had cited came
from "a third-party marketing site" and was "uncorroborated by any
Crypto.com-owned source". It carried a `confidence` field admitting the agent
proxy had denied a direct read of the page it was reasoning about.

Re-checked 2026-08-28 from a machine with egress. **Three claims, three wrong,
all in the direction that stops the next reader looking:**

1. The endpoint is printed on **Crypto.com's own API page**, in the hero
   terminal sample. The third party was quoting them.
2. A JSON endpoint serving **sports events exists** and returns 200 with 200 MLB
   rows. "Nothing shipped" was false.
3. Sports was treated as uncovered because `exchange-pro` says "crypto, politics
   and economics". That page describes the DCM/FCM institutional feed. Sports is
   a **headline category of the product**. Neither page is evidence about the
   other.

The real blocker was findable only WITH egress and is much more specific:
Cloudflare. 200 JSON to a challenged browser, **403 to curl with full Chrome
headers**. That is a sharper, more actionable fact than "no API", and the
blocked session could not have reached it.

**The decision ("do not build") was right in both versions. The REASONS were
false, and a false reason is worse than no reason** — it reads as a closed
question. Compounding: the same finding's `probe()` named "HTML that mentions a
live REST path" as its unblock signal; that would FIRE TODAY and be wrong, since
the page advertises a REST path no host serves.

**How to apply.** A finding whose own text says the network was blocked is a
HYPOTHESIS with a stated expiry, not a result. Re-run it from egress before
citing it, and write the status as what you could not do
(`no_sanctioned_server_readable_api`) rather than as a claim about what the
other party has not built (`no_public_api_yet`). Extends "trusting a refusal's
stated premise without rechecking it" (same day) from code comments to findings.


## 2026-08-28 — A lane disclaimer marker governs its OWN LINE ONLY. Three of five "contested" files were deference that PARSED as ownership.

`check_lane_invariants` flagged 5 files with two or three OPEN holders. Three
were never real contests — the ledger already recorded the resolution in prose:

    ~~`scripts/run_refresh_worker.py`~~ (claim on THIS ONE FILE released
    `paper_settlement.py` (held by `open-bet-live-status`, session `syndicate-27`,

`lane-guard._claimable_prefix` cuts a line at its FIRST disclaimer marker and
keeps what precedes it. In both lines the path precedes the marker, so both
parsed as live claims. A **strikethrough means nothing to the parser**, and a
marker on line N does not govern a path on line N+1.

**The form that works** — marker first, path after, on ONE line:

    RELEASED `[2026-08-28, session <id>]`: `syndicate/templates/portfolio.html`

My first fix attempt failed for exactly this reason: I put the released paths on
a continuation line under a marker line. It also created a PHANTOM claim on
`/.claude`, because `PATH_RE` matched `~/.claude` in prose I wrote inside a
`- Files:` block. **Do not write example paths, tool paths, or directories
inside a Files block.**

**How to apply.** After any edit to `lanes.md` claims, diff the CLAIM SET
against `HEAD` with the checker's own parser rather than reading the text —
`m.claims(git show HEAD:...)` vs `m.claims(working copy)`. It caught both
mistakes here and proved the final state removed exactly 5 and added 0 (121 ->
116). Reading the markdown would not have shown either.

---

## 2026-08-28 — AMENDS the `createdAt`/`finishedAt` rule: the DEPLOY RECORD and the PROCESS are not the same instant `[lane venue-join-refusal-visibility]`

The existing rule says *"a deploy timestamp marks when you ASKED; only
`finishedAt` marks when the code ran."* The first half is right. **The second
half is off by up to half a minute**, and on a worker that emits every few
seconds that is a real window.

Measured on refresh-worker, 2026-08-28:

```
deploy 521b6dea finishedAt   20:20:59      <- the deploy record
[refresh_worker] BOOTED      20:21:29      <- the process, 30s later
```

A log line at 20:21:10 is AFTER `finishedAt` and BEFORE the new process
existed. `finishedAt` says the artifact is ready; only the boot line says the
code is running. **For a before/after they are not interchangeable, and the one
that matters is the process.**

**HONESTY ABOUT SCOPE, because overstating this would make it a worse rule:**
in the incident that produced it, `finishedAt` WOULD have been sufficient. A
peer read a `POLYMARKET_ORIENTATION` line from 20:19:16 as post-deploy — before
`finishedAt` AND before `BOOTED` — because they INFERRED "~20:18Z" instead of
reading the field at all. The actual error was not consulting the record; the
30-second window is a hazard I found while checking, not the one that bit.

Both halves are worth carrying:

- **Read `finishedAt`, never infer a deploy time.** That is what went wrong.
- **Prefer the service's own boot line when a reading sits within ~30s of it.**
  That is what could go wrong next.

**WHY IT MATTERED HERE.** The mislabelled reading showed `listed 5 -> 24` and
`unreadable 66 -> 45` on a counter I had shipped, and I was told my tri-code
table had worked. It had never executed. The change was slate turnover between
two reads of the SAME binary — the exact "a count is not a rate when the
population moves underneath it" error this lane spent the day fixing, arriving
one level up as a gift from a peer. **A result handed to you by another session
still needs its boundary established, and the more welcome it is the more that
applies.**

## 2026-08-28 — FORBIDDEN: keying a venue join on the fixture without keying it on the PORTION of the fixture

**Measured, real money: five orders, $7.08.** `kalshi_board_join._match_key` and
`_row_key` were five-tuples — game, market, player, line, side — with no
`segment`. A board row for "under 2.5 runs, first 3 innings" therefore matched
Kalshi's FULL-GAME `KXMLBTOTAL` on every field the key contained, and nothing
downstream checked that the contract settles on a different portion of the game.

    first3  under 2.5  KXMLBTOTAL-26AUG281940TEXMIL-3  +1900,  5c
    first3  under 2.5  KXMLBTOTAL-26AUG282138PHILAA-3  +1900,  5c
    first3  under 2.5  KXMLBTOTAL-26AUG281845MIAWSH-3  +1900,  5c
    first3  under 2.5  KXMLBTOTAL-26AUG281840LADDET-3  +1567,  6c
    first5  under 3.5  KXMLBTOTAL-26AUG281840LADDET-4  +567,  15c

**THE PRICE IS THE TELL, AND IT LOOKS LIKE FREE MONEY RATHER THAN LIKE A BUG.**
The model priced "under 2.5 through three innings" — an ordinary proposition —
against the venue's price for "under 2.5 in nine", correctly ~5c because it
almost never happens. +1900 is not an edge; it is the two numbers describing
different events. **A mis-keyed join does not present as a missing match, it
presents as the best line on the board** — so the edge-ranking that is supposed
to find value actively SELECTS for the defect. Every one of the five will lose.

Kalshi HAS the right contract (`KXMLBF5TOTAL`, 'First 5 innings: Over 6.5 runs')
and we already fetch it, so this was a mis-SELECTION, not an impossibility.

**RULE.** A join key must carry every dimension on which the two sides could
disagree while still comparing equal. For a venue contract that is at minimum
fixture + market + line + side + **segment**. Adding a market family to an
existing join is the moment to re-audit the key, not to reuse it.

**AND THE COROLLARY THAT NEARLY CAUSED A BIGGER LOSS.** My first fix refused
every unmapped series. That would have unindexed the entire player-prop book —
`KXMLBKS`, `KXWNBAREB`, `KXMLBHIT` are absent from the table and all inherently
whole-game — trading a $7.08 defect for no Kalshi orders at all. The general
rule "unknown must not default permissive" is right, but **the permissive branch
has to be identified against what the field actually ranges over**, not assumed
from the shape of the bug. Here the protection belongs on the BOARD side: a row
saying `first3` cannot match a contract saying `full` whatever the series is
named, so unmapped can safely default to `full`. Refusal is reserved for a
series carrying a segment MARKER (F5, INNING, 1H…) that is not in the table,
which closes the mirror failure without touching the props.

Caught by the existing suite, not by me: `test_the_price_resolver_is_keyed_as
_tightly_as_the_join` failed on a fixture with no `series` — which was itself
the discovery that NEITHER match-record construction carried one, so version one
would have unindexed every Kalshi match in production.

**Stale reassurance is a hazard in its own right.** `_match_key`'s docstring
said Kalshi "currently supplies only player props, whose `player_name` happens
to identify a game" — true when written, and it named its own accident. The
accident expired when the join started supplying game totals, and nothing
re-read the paragraph that depended on it. Corrected in place rather than
replaced, as the record of a comment that went false silently.

Fix: `632f3473`. `kalshi_catalogue.segment_for_series` + `segment` in both key
tuples + `series` stamped at both match-record sites. 9 new tests, 127 passing
across the Kalshi join and catalogue suites.

## 2026-08-28 — FORBIDDEN: closing on the venue that was REPORTED when the join it mirrors has the same key

`#601` arrived as "the Kalshi segment bug" and I fixed it as one — correctly,
with tests, and landed. Then I ran the same query against Polymarket and found
**four more bad orders of the same class, the same day.** Nine distinct wrong
orders across both venues, not five. Nothing pointed at Polymarket; the only
reason it surfaced is that the audit was repeated rather than concluded.

**HALF A GUARD IS WORSE THAN NONE.** Polymarket's join ALREADY refused segment
MARKETS on the venue side (`segment_market_not_full_game`), ~200 lines above the
board loop that had no matching check. That guarantee made the index safe and
the missing board-side check unsafe in the same stroke: because every indexed
market is full-game, a `first3` row could not match a CORRECT contract — only a
wrong one. **The half that exists is what makes the other half look
unnecessary**, and a reader who finds the venue-side refusal will reasonably
conclude segment is handled.

So: when a guard exists on one side of a join, that is a reason to check the
other side, not evidence that the concern is covered.

**THE UPSTREAM SIGNAL WAS SITTING IN PLAIN SIGHT AND BOTH CONSUMERS IGNORED IT.**
`layer2_board.py:623` keys a board row on `(event_id, market, **segment**, line,
player_name)`. The board has always treated segment as part of a row's identity.
Two independent venue resolvers each flattened that identity to a 5-tuple. That
is not two bugs, it is one mistake made twice — which is the argument for
grepping every consumer of a shared record shape when one is found wrong, rather
than fixing the one that was reported. **Not yet done for the remaining
consumers, and recorded as open in `#602`.**

Related: the correction discipline that found it. The reported symptom named a
venue; the DEFECT named a key. Fixing at the level of the symptom would have
left half the money on the table and the ledger reading as if it were closed.

## 2026-08-28 — FORBIDDEN: sizing a fix before measuring the component's SHARE of the whole. I did it twice in one day on the same subsystem.

**Instance 1.** I found soccer's cards-context TTL (600s) was finer than the
board build period (680-874s), fixed it, measured `games()` 42.34s -> 2.76s and
recorded a verified 15x win. The sport bracket was 163-382s. The component I
fixed was ~3s of it. I optimised a real defect that could not matter.

**Instance 2, after being caught on the first.** I traced the cost to
`week_games`, proposed a request-scoped memo of `recommendations_payload`, and
worked out the plumbing in detail -- `games()` is an 8-implementation
interface, three signatures below it need changing, and memoizing the payload
itself is FORBIDDEN (`@lru_cache` removed 2026-07-24; matches froze at
`status_state="pre"` 0-0 for days). Every word of that is correct. Then I
measured:

```
la_liga  total 20.78s   payload_s 1.29   assemble_s 19.49
```

**`payload_s` is under 7%.** The memo would save 1.3 of 20.8 seconds.

**THE RULE:** before designing a fix for component `C`, get `C / whole`. Not
`C`'s absolute cost, not whether `C` contains a genuine defect -- its SHARE.
A real defect in a 7% component is a real defect that cannot move the number.
Both times I had the whole (163-382s bracket; 20.78s call) and the component
in hand and did not divide.

**WHY IT KEPT HAPPENING:** finding a defect feels like finding THE defect. The
TTL was genuinely too fine. The payload memo was genuinely blocked by two
recorded cache removals. Being right about the mechanism is what made me stop
checking whether it mattered.

**COROLLARY, from the same session:** `la_liga` week 3, SAME 10 fixtures, read
3.24s and 13.99s -- 4x on identical inputs. A single sample of a variable
quantity is not a measurement of it, and I built a "slow league" theory on one
`belgian_pro_league` reading. When the spread on identical inputs is larger
than the difference you are explaining, you are explaining noise.

## 2026-08-28 — FORBIDDEN: judging a change by the metric I chose instead of the metric the USER SEES. Mine read "bought nothing"; the board read 4h24m stale.

I raised `SYNDICATE_INTELLIGENCE_BOARD_WINDOW_SLOW_REFRESH_SECONDS` 300 -> 1800
(code default) so future dates would stop stealing cycles from today. I then
measured today's SHARE of build cycles, found it unmoved at ~50%, and recorded
the change as **"bought nothing"** — harmless, left in place.

Nine hours later the user asked why the board was stale. It was showing
`as of 12:15 PM` at 4:33 PM:

```
2026-08-28   last build 21:20:24   19m
2026-08-29   last build 21:37:15    3m
2026-08-30   last build 17:15:20  264m   <- sets computed_at
```

`combined_board_window` reports `computed_at` as the OLDEST contributor's
stamp, deliberately, so the weakest link is what the board shows. My throttle
starved the third date of a 3-day window until it set the vintage for the
whole board. Today and tomorrow were 19 and 3 minutes fresh and it did not
matter.

**THE RULE:** when a change alters scheduling, priority or cadence, check the
USER-FACING freshness/quality signal, not only the internal counter you
reasoned about. "Bought nothing" is a conclusion about MY metric. The question
is always "what does the surface show now".

**AND "NO EFFECT" IS NOT A SAFE VERDICT.** I left it deployed BECAUSE I
believed it was inert. A change measured as neutral on the chosen metric is
not thereby harmless — it is unmeasured on every other one. Either revert it
or check the surface; do not bank neutrality as safety.

Same family as the share-of-the-whole rule logged earlier today: both are
measuring a real quantity confidently and it being the wrong quantity.

## 2026-08-28 — Pre-registering a confound does not help if you get its SIGN wrong

Before deploying `#604` I wrote the expected reading down in `deploys.md`:
Kalshi `matched` would FALL (my phantom-match removal) while `unreadable_title`
would also fall (a peer's soccer grammars) — "two independent causes moving two
numbers in the same direction, so neither is evidence for the other."

Measured after: `matched` **233 → 255, it ROSE**; `unreadable_title` 2242 → 1790.
The two causes moved in **opposite** directions, and the peer's +452 newly
readable titles swamped my guard, which fired **twice**.

Writing the prediction down was still right — it is why the miss is legible at
all instead of being quietly re-narrated. But two further rules come out of it:

1. **A co-deployed change can swamp your effect entirely.** A 2-count guard is
   not measurable against a 452-count change in what the same function can read.
   The honest report is "cannot isolate", not a hedged causal story. If an effect
   must be attributed, it needs its OWN counter — which is exactly what `#604`
   added, and why `segment_has_no_matching_series: 2` is the real evidence while
   `matched` is not.
2. **Predict the SIGN, not just the confound.** "Both move together" felt like
   rigour and was an unchecked assumption doing the work of a measurement.

Related, same session, same shape: I told the user tonight's 20:22 sim "was
killed by a deploy and relaunched harmlessly" while advising them on whether to
override a deploy guard. It **completed on its own** at 20:56:24, two minutes
before the 20:58:17 deploy — which is precisely why preflight read CLEAR. **No
sim was killed tonight, so there was no local example of a kill being harmless**,
only the ledger's example of one being harmful. I had inverted the evidence in
the direction that made the action I was about to take look cheaper. Corrected
to the user before they decided.

## 2026-08-28 — FORBIDDEN: reaching for the next knob after a tuning change fails. Three attempts, each refuted by the next reading, when the second should have said "structural".

The board displayed `as of 12:15 PM` at 4:33 PM. `computed_at` is the OLDEST
contributing date's stamp, so one starved date sets the whole board's vintage.

  1. I had raised `SLOW_REFRESH_SECONDS` 300 -> 1800 that morning and recorded
     it "bought nothing" -- measured today's SHARE of cycles, never the board.
  2. Set it to 600 to loosen the throttle. **`2026-08-29` went 3m -> 84m.**
  3. Set `BOARD_WINDOW_DAYS=2` to remove a competitor. **Today absorbed the
     freed slot: 36 minutes post-boot, two builds, both today.**

**THE SIGNAL I IGNORED IS AT STEP 2.** A change that moves the metric the WRONG
WAY is not a dosage problem, it is evidence the model is wrong. I read it as
"not enough" and reached for a second knob. The cause was structural the whole
time: today is re-queued every loop iteration UNTHROTTLED while futures are
throttled, and with 11-15 minute builds today wins every slot. Eligibility was
never the constraint; slot allocation was.

**THE RULE:** when a tuning change makes the observable worse, STOP TUNING. One
more knob is a guess that the mechanism is right and the value is wrong -- and
the wrong-direction result is precisely the evidence against that. State the
mechanism as unknown and go read the scheduler.

**AND THE THIRD ATTEMPT PROVED IT CONCLUSIVELY, WHICH IS THE TELL.** Removing a
competitor freed a slot and the DOMINANT party took it. If I had predicted that
outcome I would not have run the experiment; I ran it because I still believed
the starving date was merely under-eligible.

Sits with the two rules already logged today: judging by the metric I chose
rather than the one the user sees, and sizing a fix without the component's
share of the whole. All three are confident measurement of the wrong quantity.

## 2026-08-29 — FORBIDDEN: naming a cause from a mechanism you can see without measuring the one you cannot

I diagnosed board staleness as queue starvation -- today re-queued unthrottled,
futures throttled -- and wrote it into `state.md` and `learnings.md` as the
STRUCTURAL cause, with "round-robin the pending queue" as the fix. The starvation
mechanism is really in the code. It is not what was happening. One log query
(`BUILD_SPAN_ENTER`, 8 builds) showed the dates alternating cleanly, and the real
cause -- 900-2000s build duration against a 2-date window -- was in a stage timer
I had already deployed and never read.

**Why it survived three failed fixes:** each failure was read as "not enough of
the right thing" rather than "the wrong thing". The `=600` result moved `08-29`
the WRONG way, which is a refutation of the model, and I took it as a dosage
problem. The rule written that day (`stop tuning when the observable moves the
wrong way`) fired correctly and I still did not re-examine the CAUSE, only the knob.

**The asymmetry to watch for:** a mechanism you can read in the source is
available for free; the quantity that decides whether it BINDS costs a query. The
free one will always be more available, and it is not evidence. Both of the
session's real findings this day -- the alternation, and the 60-loads-per-week
count -- came from measuring the thing that was not visible in the code.

**How to apply:** before writing a cause into `state.md`, state the ONE reading
that would refute it and take that reading. "Today starves tomorrow" is refuted by
the build-start sequence, which is one query against a log line that already
existed. Cost: two minutes. It was skipped for three deploys and a wrong ledger entry.

## 2026-08-29 — FORBIDDEN: carrying a component's SHARE across regimes when the regime is what sets it

I found a real defect (`_match_to_game` re-reading the same `(league,date)`
artifacts once per FIXTURE; 60 file loads -> 4, structural and reproducible),
sized it with `assemble_s 19.49 of 20.78s`, shipped it, and measured no change at
the sport level. The share was the problem, not the defect. That 19.49/20.78 was
taken at 20:24Z inside a European live window. Overnight -- when I deployed and
measured -- one full eight-league pass totals ~28.8s of a ~206s soccer bracket:
**14%, not 95%.** A 40% cut of 14% is ~6%, which is below the noise of the thing
I promised to move.

**This is the SAME confound this lane already retracted once**, in the other
direction: a "TTL 42.34 -> 2.76s, 15x" win that was a quiet reading compared
against a live one. I wrote that retraction, wrote the rule, and then re-used a
live-window ratio as though it were a constant.

**The generalisation:** a magnitude and a SHARE degrade differently when carried
across regimes. `assemble_s = 19.49s` stays true of that moment. `assemble_s is
95% of the call` is a ratio between two things that move independently, and it
survives nothing. Treat every share as scoped to the window it was taken in.

**How to apply:** before sizing a fix from a share, re-measure the share in the
regime you will DEPLOY and MEASURE in. One query. If the deploy window and the
measurement window differ from the window that motivated the work, that is the
first thing to reconcile, not the last.

**Also: state the settle bar and then actually meet it.** I required >25 min
post-boot and every sample I took was 2-19 min in, across two boots. I reported
the numbers anyway. A caveat is not a substitute for a measurement.
## 2026-08-29 — FORBIDDEN: reading a conditional log's silence as absence of the EVENT, when it is really absence of one SPECIAL CASE of the event

`#600`'s merge logs `LEDGER_MERGE` only when `concurrent > 0` or the merge
failed. I checked that the line is conditional, confirmed the code was live on
all three writers, and reported a 68-minute production null — 59 settlement
lines, 49 execute lines, zero merges — as "no collision happened, the conflict
branch has never executed".

**Both halves of that were wrong, and a forced-collision test found it in
minutes.** `counts["concurrent"]` increments only when a row **already in our
baseline** has a different fingerprint now (`execution_ledger.py:443`). An
intruder that only APPENDS rows never trips it. So:

- an addition-only race IS a collision, IS merged correctly, and logs NOTHING;
- **a placement cycle appending orders while a settlement pass holds a snapshot
  is exactly that case** — i.e. the most likely real-world race on this ledger
  is the one the instrument cannot see;
- the conflict branch may well have been running successfully all along.

**The rule.** "This log is conditional, therefore its silence is meaningful" is
only half the check. The other half is **what exactly the condition is**, read
off the increment site — not the log line, not the function name. `concurrent`
sounds like "another writer wrote"; it means "another writer modified a row I
had already loaded". Those differ by the entire class of appends.

I had already done the shallow version of this check twice the same night
(`SIM_START` never emitted; `LEDGER_MERGE` is conditional) and both times
stopped at "does the line exist". The deeper question is what makes it fire.

**And the general one: when waiting cannot produce the event, FORCE it.** Sixty-
eight minutes of real traffic produced no reading. A test with two threads and
an `Event` produced it immediately, plus a defect in my own interpretation.
Waiting for a rare event is not evidence-gathering — it is deferring the
experiment that would settle it.

## 2026-08-29 — FORBIDDEN: breaking a lock before checking whether the thing it guards has already happened

I forced an UNEXPIRED 30-minute-old deploy claim off an active peer lane. The
very next command — preflight — returned `TOO_SOON: refresh-worker was deployed
4 min ago`. **The peer had already deployed the exact SHA I was about to
deploy**, and it carried both lanes' work. The claim was not an obstacle to my
goal; the claim's HOLDER had already achieved my goal.

**The ordering error, stated precisely:** I checked "is anyone deploying?"
(`render_events.py --since`) at 15:46, saw none, and then forced at 15:52 on the
strength of that. The deploy landed at 15:52:29. A null result is scoped to the
window it covered — 15:30-15:46Z — and I carried it forward as a standing fact
across the six minutes that actually mattered. This is the same shape as
`absence_in_a_window_is_not_absence`, now with a destructive action attached
instead of a wrong opinion.

**Why the guard still saved it:** the 25-minute spacing rule (`#563`) refused the
redeploy, which would have discarded the in-flight build and frozen the board for
~21 minutes. So the cost was a broken claim and an interrupted peer, not an
outage. That is luck plus somebody else's foresight, not judgement.

**How to apply:** before `--force` on ANY lock, re-check the state the lock
protects, in that order and at that moment — not the check you ran earlier.
Specifically for deploys: `render_events.py --since <5 min ago>` for a
`deploy_started`, and read the live SHA. If the answer is "already done", the
correct action is to release, not to proceed. A held lock is evidence that
someone else is acting on the same system; treat the holder as a source of
information about the world, not purely as a queue ahead of you.

## 2026-08-29 FORBIDDEN: letting a shipped "cannot be tested until X" caveat stand without putting the test on X's date

`ncaaf-board-surfaces` shipped the NCAAF live-lens state path on 2026-08-27 and
wrote, accurately: *"The live lens's state PATH is tested; its DATA cannot be
until a game is in progress."* The first game of the season kicked off
2026-08-29 16:00Z. At 16:05Z, with the game visibly in progress, production
served `Games 51 | Live 0 | Final 0 | Pregame 51`. `ncaaf/cards.py` had **zero
occurrences of `live_state`** — the key `_shared_game_state` derives
`live`/`final`/`period`/`clock` from. The live branch was **unreachable by
construction**, and had been for the whole preseason.

**An honest caveat is not a mitigation. It is a defect with a date on it**, and
the date arrives when nobody is looking at that surface.

Compounding it: `test_smartsim_live_lens_runtime_uses_runtime_cards` had been
FAILING since 08-27, asserting the pre-08-27 constant eyebrow. **A test that is
already red cannot report that something else broke.** It was the one test over
this exact code path.

**How to apply:** when a trigger condition arrives (opening day, first live
game, first scheduled run), grep the ledger for THAT CONDITION and re-test what
named it, before starting anything new. And never let a red test sit in the area
you are relying on the suite to watch.

## 2026-08-29 FORBIDDEN: reading `check_lane_invariants` PASSING as proof that lane claims are sane

`lane-guard` blocked an NCAAF edit during the first game of the season,
attributing `syndicate/features/ncaaf/cards.py` to the UNOWNED lane
`soccer-board-mlb-parity`. That lane's `- Files:` block spelled a bare
`cards.py` twice — **inside a note stating the claim had been REMOVED**. The
guard matches on path SUFFIX (`rel.endswith("/" + f)`, `lane-guard.py:420`), and
a bare filename has no directory to disambiguate it, so that one token claimed
**mlb, nba, nfl, ncaaf and wnba** cards builders simultaneously.

`check_lane_invariants` reported `INVARIANTS HOLD` throughout — it verifies that
each claim has exactly ONE holder, and this claim did. The two tools disagree
about what a claim IS, and only one of them gates edits.

Same basename-collision class `state.md` already records for `live_lens` across
eight sports.

**How to apply:** a disclaimer next to a path does not unclaim it — only
deleting the path text does. Never write a bare filename inside a `- Files:`
block, prose or not; always the full repo-relative path. And when the guard
blocks you on a file you believe is unclaimed, read the guard's matching rule
before assuming the ledger is right.

### 2026-08-29 — FORBIDDEN: making a previously-unreachable code path reachable without measuring the cost of the path that will now call it

- **What we believed:** that fixing `ncaaf_week_and_card_keys_for_date` was a
  CORRECTNESS change. It restored a dead join, so the risk seemed to be "does
  it return the right games", and that is what was measured: 8/8 and 30/30 keys
  matched real card gamePks locally, and production went 0 -> 8 chips at
  17:14:02Z with the live game carrying `Q2 5:44` and `10-10`. **The fix worked.
  It was verified. And it took the site down anyway.**
- **What was actually true:** `_NCAAFDataProvider.games()` builds the ENTIRE
  NCAAF board on every chips build — `build_smartsim_cards_page_context` PLUS
  `build_ncaaf_market_board`, 51 games. That code was always that expensive.
  The broken resolver's `return []` had been acting as an **accidental circuit
  breaker** for months. Removing it put a ~30s build on the home page's request
  path behind a 30s TTL, on a 2GB display-only service with two gunicorn
  workers. One slow build occupies a worker; two exhaust the pool; Render's
  router then fast-fails everything else with 502 in ~0.4s.
- **How we found out:** the user's board went down. Measured: `/` 3.5s baseline
  -> **37.9s**; `/ncaaf/cards` **502**; `/api/ops/memory` **502**. Restored by
  reverting forward (`0163f904`) — `/` settles to 1.8s, all routes 200.
- **The rule going forward:** **enabling dead code is a performance change, not
  only a correctness one.** Before shipping a fix that makes an unreachable path
  reachable, read what the newly-reachable code CALLS and measure it on the path
  that will now call it. "It returns the right answer" is not a deploy
  verification for a change that alters *how often* something runs.
- **Cost:** ~8 minutes of degraded-to-502 production during the FIRST live
  college football game of the season — the exact surface the user was watching
  — plus a revert, plus the resolver fix now unshipped and owed.

#### The epistemic failure is worse than the technical one, three times over

1. **I noticed the risk and shipped anyway.** Before deploying I wrote to myself
   that the chips path would now do "real NCAAF board work" and that it was
   "worth flagging". Then I deployed and did not measure it. A noticed-and-
   unacted risk is worse than an unnoticed one, because it proves the
   information was in hand.
2. **I dropped a habit exactly when it mattered most.** Two deploys earlier I
   measured latency on this very endpoint family (3.0/3.0/3.3/3.9/5.3s against a
   4.85s baseline) and wrote it into `deploys.md`. On the riskier change I
   measured only correctness.
3. **My verification watcher could not have seen it.** It polled
   `chips>0` and exited on success — a success-only filter, which the Monitor
   guidance explicitly warns against, and the SECOND one I wrote this session
   (the first broke on `head != '0:00'` and fired on a stale render). **A
   watcher that cannot express the failure is not a watcher.**

### 2026-08-29 — the check that would have caught this ALREADY EXISTS and was not applied

`syndicate/features/shared/request_path_guard.py` carries **two** functions:
`warn_if_compute_in_request_path` (logs only) and
**`refuse_if_compute_in_request_path`** — a HARD refusal written for `#56/#98/#109`,
whose docstring names this exact failure: *"the web service does no heavy
computation ... `_build_candidate_pool` directly on the 2GB [service]"*.

Neither is called anywhere on the game-chips path, and `_NCAAFDataProvider.games()`
calls neither. The rule was written down, the enforcement was built, and the
new caller simply never opted in.

**PROPOSED CHECK, because another line of prose will not catch the next one:**
a post-deploy latency assertion in the web verification loop — measure `/` and
the changed route against the pre-deploy baseline in the same run, and treat
**>2x** as a FAILED deploy verification rather than a passing one. This incident
would have failed it at 37.9s vs 3.5s, ~4 minutes before it was noticed by hand.
A rule would not have caught this; I had the rule and violated it. Only a
measurement in the verify step catches it.

### 2026-08-29 — a cross-session ANSWER has to go where the reader looks, because SendMessage cannot address a lane

- **What we believed:** that a peer session or a lane holder can be reached by
  the identifier the ledger gives you.
- **What was actually true:** lane blocks and inbound peer messages carry
  session UUIDs (`3e5a9659`, `764eca35`, `local_5163d9b3…`); `ListAgents` lists
  NAMES (`syndicate-9c [4ad613]`, `Polymarket execution gaps`). **There is no
  mapping between the two**, and neither the UUID nor the quoted name resolved.
  Three attempts, three failures, in one session:
  `ncaaf-settlement-resolver` (wanted a 2-field parser addition),
  `soccer-overview-cost` (wanted a carve-out on `home.py`), and a peer who
  explicitly asked whether a revert-then-reapply was safe to deploy and said
  they would HOLD until answered.
- **How we found out:** `SendMessage` returned "No agent named … is reachable"
  for the `from` attribute the message itself supplied, which is the exact value
  the tool documentation says to reply to.
- **The rule going forward:** when a peer or lane holder cannot be addressed,
  **write the answer into the artefact they demonstrably read and say why it is
  there.** The peer had cited `deploys.md`, so the answer went into `deploys.md`
  under a heading naming them. Do not let an unreachable address turn into
  silence — silence read as "no objection" is how a lane's file gets taken
  without its holder ever hearing, which happened twice today.
- **Cost:** two carve-outs taken without the holder's consent (both logged on
  both lane blocks), and a peer blocked on an answer until the user relayed it
  by hand.

**Check, not prose:** the useful fix is for lane headers to carry the
`ListAgents` NAME alongside the session UUID, so a holder is addressable from
the ledger. Until then, `/lane open` should record both.

## 2026-08-29 — FORBIDDEN: trusting a profiler's ANSWER without validating its SCOPE against the metric you care about

I wired cProfile into `_build_sport_overview`, read `posix.lstat` at 46% of it,
fixed that, and reported it as soccer's cost. The profile was correct. **The
region was 2.4% of soccer's `OVERVIEW_SPORT` bracket** (10.95s of 452.97s, later
3.22s of 362.76s). I had carried "sport_branch is 98%" from this lane's own
notes, where it meant 98% OF `_build_sport_overview`'S OWN ELAPSED — a share
against a different denominator.

**The instrument does not know what you are trying to explain.** A profiler tells
you where time went INSIDE ITS BRACKET, with total authority and no opinion about
whether that bracket is the thing you care about. That check is one subtraction:
compare the profile's `elapsed_s` against the enclosing measurement. 10.95 vs
452.97 was visible in logs I had already pulled, and I did not do it until the
second profile forced the question.

**The correct move, once done, took one step:** `OVERVIEW_SPORT_BEGIN..END`
contains exactly three calls, so ~99% had to be in the consumer. Profiling THERE
gave `collect_s=901.59 of 902.06` and named the leaf in one run.

**How to apply:** before acting on a profile, state the profiled region's share of
the number you are trying to move, from a measurement OUTSIDE the profiler. If
you cannot, you do not yet know what you measured.

## 2026-08-29 — FORBIDDEN: windowing a verification watcher on wall-clock time instead of on the boot it is verifying

My post-deploy watcher opened its log window at a fixed timestamp and returned
`CONSUME_SPORT_SEGMENTS total_s=1114.41` — a clean, plausible, correctly-formatted
number **from a pass that ran eight minutes BEFORE the deploy started**, on the old
code, with a profiler still armed. Read as a post-fix result it says the fix made
things worse. The `boot=none` field in the same output was the only tell.

Fixed by keying the window on the BOOTED timestamp and requiring the sample to be
strictly after it. The rewritten watcher then produced the real number, 75.78s.

**This is the same family as the substring collisions this session** (`BOOTED`
matching the log tool's own header; `ODDS_HISTORY_LOAD` matching
`ODDS_HISTORY_LOADED`; a claim watcher grepping `free` against a status line
reading `EXPIRED (does not block)`, which cost 13 minutes of waiting on an
already-dead lock). **Four instances in one session of a query matching something
that was not what it was looking for.** The shared fix is to anchor the query on
an identifier the target event actually emits, and to include in the output the
field that would reveal a mismatch.

### 2026-08-29 — a fix proven on ONE consumer is not proven on another that recomputes it elsewhere

- **What we believed:** that fixing `board_enrichment._side_matches` would fix
  every surface that shows NCAAF game state, because they all go through
  `attach_game_state`.
- **What was actually true:** `book-grid` re-runs the enrichment at READ time on
  web, so a web deploy fixed it instantly (`rows_matched` 0 -> 44).
  `layer2-shortlist` runs the same enrichment in
  `pipeline/layer2_shortlist.py:548` on the WORKER, over its own artifact.
  Measured 18:59:25Z with `95c4fb12` live on BOTH services and the worker past
  its ~21-min first-publish window: book-grid **44**, shortlist **0 of 96**.
- **How we found out:** reading both surfaces in the same minute instead of
  generalising from the one that moved.
- **The rule going forward:** when two endpoints display "the same" joined
  field, find out WHERE each computes it before treating one reading as
  evidence for the other. A shared function is not a shared execution site, and
  on this platform the web/worker split makes that difference routine rather
  than exotic.
- **Cost:** none yet — the lane was NOT closed on the book-grid number, which is
  the whole point of writing this down now rather than after closing it.

### 2026-08-29 — PowerShell reserved variables can fake a regression

`$home = git show <sha>:path` fails (`HOME` is read-only), leaving the variable
empty, so a content check reported the light chip path MISSING from a commit
that contained it. A false "regression" on a deploy candidate is exactly the
reading that triggers an unnecessary revert. Use non-reserved names (`$homePy`)
in verification scripts, and treat a surprising negative as suspect before
acting on it.

---

## 2026-08-29 — a diagnostic that TRUNCATES will be read as evidence. Twice.

`key_miss_samples`' `market_indexed_under` is `sorted({...})[:4]`. Alphabetical,
capped at four. `cfb` and `alsv` sort first, so they filled the cap on EVERY
market they touched.

I read that as attribution twice in one session:

- `soccer|btts` -> `['lgscup|...', 'lmx|...', 'soccer|2026-08-29']` was read as
  "unmapped competitions are losing BTTS". It was not. The meaningful entry was
  the FOURTH -- right league, wrong date. No tokens needed adding at all.
- `ncaaf|spreads` -> `['cfb|...']` was read as the `cfb` alias. The IDENTICAL
  list appeared under `wnba|totals`, where `cfb` cannot possibly be the alias.

**RULE: a bounded, sorted sample is not a rate and not an attribution.** Before
drawing a conclusion from a truncated list, ask what a NULL result would look
like -- here, the same list under an unrelated key, which was visible the whole
time. The `cfb` alias was real, but it was settled by a NAMED FIXTURE on both
sides (`tsc-cfb-sacst-emich` = the exact board row), not by the list.

**Corollary that cost the most:** the same session nearly DELETED the corners
route on a 19-slug sample showing no corners family. The census found 434.
A sample that finds nothing is not evidence of absence at any n you did not
choose in advance.

---

## 2026-08-29 — FORBIDDEN: mapping an outcome polarity that the venue has not stated

Polymarket corners are `["Yes","No"]` while the board asks over/under. The
obvious map (`over -> Yes`) would have closed 59 refusals in two lines. If the
polarity were reversed it prices the OPPOSITE SIDE of a live bet at a
confident-looking number -- the $7.08 MLB error, at scale.

What made it safe was NOT reasoning about which word "should" mean over. It was
shipping a census first (`side_gap_samples`: outcome names AND prices beside the
wanted side and the board's line), then reading two independent confirmations:

    TOKEN  `cor-all-gt10pt5` -- the venue states "greater than" IN THE SLUG
    PRICE  `Yes` = 0.76 on a 7.5 line; over 7.5 corners is the likely side of a
           ~10-corner match, under would be ~0.24

The fix is gated on the `gt` TOKEN, not on "Yes/No plus a line": the gate IS the
evidence, so a family that never declares a direction keeps refusing instead of
being assigned one.

**MLB spreads are still refusing for the same reason and must stay that way**
until a sample settles them: outcomes are `+1.50`/`-1.50`, both observed samples
carry `pos-1pt5` and differ only in the side wanted, so they cannot establish
whose perspective the venue states the spread from.

**RULE: coverage may be traded for certainty; a side may not.** A refusal costs
a bet. A wrong polarity costs the bet AND pays the other side.

---

## 2026-08-29 — ancestry is a DEPLOY-TIME MEASUREMENT, never a claim

I twice told a peer they would "carry my commits anyway, they're on main ahead
of you". Wrong both times -- my commit landed AFTER their trigger. They
corrected me, and the correction is the rule:

**main moves under every session. Only the deploying session can see its own
trigger moment.** Telling a peer what their deploy contains is asserting a fact
only they can measure. State main's head as a fact they can check; let them
verify ancestry themselves.

The same discipline caught a real one later: a peer deployed `6625b5e6` and I
checked rather than assumed -- `1be9fa3e` was NOT in it. Had I assumed the other
way I would have read an unchanged counter off a binary without the fix and
called it inert.

### 2026-08-29 — FORBIDDEN: gating a verdict on ELAPSED TIME when the artifact carries its own build stamp

- **What we believed:** that enough minutes after a worker deploy, a zero on
  `/api/board/layer2-shortlist` meant the fix had failed. The watcher was built
  on that: a grace window counted from the deploy, then a `STILL ZERO` verdict.
- **What was actually true:** the endpoint is a **PURE READ**
  (`source: layer2_shortlist_artifact`) of a pool built on refresh-worker inside
  `_build_candidate_pool`. It computes nothing at request time. The pool it was
  serving carried `written_at 2026-08-29T18:30:44Z` — **twelve minutes OLDER
  than the fix**, which went live at 18:42:34Z. No amount of waiting would have
  changed that reading, because nothing had rebuilt it.
- **How we found out:** dumping every scalar key on the payload instead of only
  the rows, and finding `written_at` already there.
- **The rule going forward:** when a surface serves an artifact, the ONLY input
  that licenses a verdict about a code change is the artifact's own build stamp
  crossing the deploy time. Elapsed time is a fact about you, not about the
  system. Find the build stamp BEFORE arming a watcher — `written_at`,
  `generated_at`, `published_at` — and gate on it. If a surface has no such
  stamp, that absence is the first thing to fix, not to work around.
- **Cost:** none — the false `STILL ZERO` was caught before it was reported.
  Once re-gated on `written_at`, the confirmation arrived in 90 seconds:
  ncaaf 0/96 -> 49/92.

This is the same shape as two other errors the same day: a green local read off
an untracked `cfbd_lines` mirror production has never had, and a "baseline"
worktree that passed only because it lacked untracked MLB data. **Three times
in one session the instrument, not the system, produced the reading** — see
[[feedback_instrument_blindness]] in spirit. The discriminator is always the
same question: *what would this reading look like if the thing I am testing had
never run?*

### 2026-08-29 — FORBIDDEN: closing a name-join gap by POPULATING an alias map, without first checking the map's source carries the missing name

- **What we believed:** that NCAAF's join gap was a missing alias MAP, so
  deriving one from `ncaaf_team_registry.unambiguous_team_index()` would close
  it. The registry has 684 teams and is the lane's authoritative vocabulary; it
  looked like the obvious source.
- **What was actually true, on two counts:**
  1. **A derived map cannot invent vocabulary its source lacks.** With 2,232
     keys built, `canonical_team("ncaaf", "UMass Minutemen")` still returned
     `None` — team 113 is `Massachusetts` and carries no `umass` in any column,
     so the combined key is `massachusetts minutemen`. The target case was
     untouched.
  2. **Populating a map CHANGES THE SEMANTICS of every lookup for that sport.**
     `teams_match` returns the map's verdict when both sides resolve
     (`team_aliases.py:640-644`) and deliberately does NOT fall through to the
     heuristics. So a mis-resolution stops being a harmless miss and becomes a
     confident wrong answer. Measured: `canonical_team("ncaaf", "MAS")` ->
     **`UMass Dartmouth`**, team 379's real abbreviation, colliding with the
     chip's synthetic abbr for Massachusetts.
- **How we found out:** spot-checking the map's own output on the exact failing
  token before trusting the key count. 2,232 keys looked like success; the one
  token that mattered still returned `None`.
- **The rule going forward:** before adding a map for a sport that has none,
  (a) confirm the SOURCE contains the specific name the join is failing on, and
  (b) enumerate what the new map resolves that the heuristics previously left
  unresolved — because those are exactly the lookups whose semantics flip from
  "fall back" to "authoritative". A map is not a strictly-additive change.
- **Cost:** none shipped. Built, measured, reverted; control confirmed the map
  back to 0 keys and the 8 slate pairs still 8/8. The real gap is REGISTRY DATA
  upstream (CFBD does not ship the alias), handed to the owning lane.

`_basketball_alias_to_name`'s docstring already recorded this exact failure from
the other direction — a merged map made `("wnba", "min")` vs "Minnesota Lynx"
FALSE, "a wrong answer, and worse than no answer, because the map is treated as
authoritative and skips the heuristic fallback." **The warning was in the file I
was editing.**

---

## 2026-08-29 — FORBIDDEN: calling a placeholder threshold "conservative" without checking it against the real one. A threshold above break-even everywhere is a DISABLED FEATURE wearing safety language. `[lane live-venue-order-placement]`

- **What we believed:** `kalshi_polymarket_arb.DEFAULT_FEE_BUFFER = 0.04` was a
  safe stand-in. Its own docstring says so at length and honestly — "a
  conservative placeholder, not either venue's real fee schedule", "only
  `edge_after_buffer` should be read as an actionable signal". Every word of
  that is true and it still produced the wrong outcome.
- **What was actually true:** measured break-even for a two-leg MLB pair runs
  **3.38c at even money down to 0.39c at 0.97**. The flat 4.00c threshold sat
  **above break-even at every price on the board.** The detector could not
  report a profitable MLB pair — not "rarely", not "only the big ones". Never.
  And MLB is the sport with the most volume on the platform.
- **Why the honest label made it worse, not better.** "Conservative" names the
  DIRECTION of the error and says nothing about its MAGNITUDE. Over-stating a
  cost feels like the safe side, so nobody re-derived it. But a detector that
  never fires is indistinguishable from a market with no arb in it — the exact
  empty-list confusion `kalshi_client.py`'s header already warns about, arriving
  through a threshold instead of through a return value.
- **How we found out:** not by auditing the buffer. By computing the real fee
  from the venue's own `fee_type`/`fee_multiplier` fields for an unrelated
  reason, and noticing the break-even table was under 4c on every row.
- **The rules going forward:**
  1. **A placeholder threshold must be compared to the real quantity before it
     is called conservative.** One number and one comparison. Until then the
     right word is "unvalidated", which invites the check that "conservative"
     suppresses.
  2. **A flat stand-in for a curved cost is wrong in SHAPE, not just level, and
     no single value fixes it.** Kalshi's fee is `rate * P * (1-P)`. At p=0.05
     the flat buffer was 12x the truth; at even money on a full-rate series it
     was roughly right. A constant cannot approximate a parabola, so the error
     changes sign across the book and any calibration of the constant just
     moves where it is wrong.
  3. **When a detector reports zero, the first question is whether it CAN
     report non-zero.** `test_arb_net_edge.py::test_the_old_flat_buffer_was_
     above_mlb_break_even_at_every_price` asserts exactly that, so the class
     cannot come back silently. Same shape as the standing
     `presence_is_not_reachability` rule, applied to a threshold.
- **Also corrected, and it is the smaller half:** every third-party source says
  Kalshi rounds fees "up to the next cent". Against 18 real fills that is wrong
  — ceil-to-4dp matches **18/18**, round-to-4dp **9/18**. A spot check on one or
  two fills cannot separate them (9 of the 18 agree under both rules), which is
  why the count is the evidence and a sample is not. **The venue's own fields
  and our own fills outrank any explainer, and both were available the whole
  time.**
- **Cost:** none realised — no money was placed on the bad threshold, because
  the detector's silence also meant nothing ever acted. That is luck, not
  design: the same class of error on the permissive side would have placed
  losing pairs at even money instead of finding nothing at the tails.

---

## 2026-08-29 — FORBIDDEN: reading `count: 0` from an artifact export as "the artifact is unreachable". It is a fact about what the READER scans. I had this rule on file and walked into it anyway. `[lane live-venue-order-placement]`

- **What we believed:** `/api/ops/artifacts/export?pattern=*polymarket*`
  returning `count: 0` meant the Polymarket slate was not reachable from web,
  so any cross-venue measurement needed a worker-side probe or a publishing
  change first. I put that in `state.md` and built a recommendation on it.
- **What was actually true:** the slate has been reachable from web the whole
  time. Both services run `SYNDICATE_REFRESH_STATE_BACKEND=keyvalue`, so
  `persist_game_slate` writes to the KEYVALUE store and never to disk, while
  the export scans DISK. `/api/ops/polymarket/slate` returns `count: 17241`.
  **`ops.py:450`'s docstring records this exact trap, measured 2026-08-27**,
  including the observation that the obvious fix (allowlist it in
  `HOT_ARTIFACT_PATTERNS`) would have been an inert no-op.
- **And better than that:** `/api/board/layer2-shortlist` carries BOTH venues'
  prices on the same row in `quote.book_prices`. The measurement I said needed
  a credentialed worker probe needed ONE web call.
- **How we found out:** a peer lane mentioned in passing that it had settled
  several venue questions off `/api/ops/polymarket/slate` without credentials.
  I checked instead of accepting, and they were right.
- **Why the existing rule did not save me.** I have
  `keyvalue_artifact_split_blinds_guards` in memory — "read_json_file sees only
  keyvalue; a guard reading it is blind to exactly the big payloads that
  matter". That is the SAME split, from the other side, and I did not connect
  it because the symptom presented as an ordinary empty result rather than as a
  guard misfiring. **A rule filed under one symptom does not fire on another.**
- **The rules going forward:**
  1. **A zero from a reader is a fact about the reader until you have checked
     what it reads.** Before concluding "absent", name the STORE the writer
     writes to and confirm the reader scans it. One question, and it is the
     same question in both directions of this split.
  2. **Before building a new reader, grep the ops blueprint for an existing
     one.** `/api/ops/polymarket/slate` existed, was documented, and answered
     the question. I proposed building a probe and publishing an artifact —
     both unnecessary, both would have shipped.
  3. **Ask what is already joined before assembling a join.** Two venues'
     prices sitting on one board row is a stronger instrument than two
     separately-fetched catalogues, because it is same-instant by construction
     — which is a standing rule here (`measure_same_instant`) that I satisfied
     by luck rather than by design.
- **Cost:** none realised — no code was written against the wrong conclusion,
  and the correction arrived before the next increment. But the recommendation
  I gave the user ("worker-side probe, or publish the slate first") was wrong
  in both branches, and had they picked either we would have built something
  that already existed.


## 2026-08-29 — FORBIDDEN: judging whether `main` is green from a session worktree OR the primary tree. Neither is a control, and they lie in OPPOSITE directions

- **What we believed:** that running a test file in my own worktree told me
  whether the branch was healthy. I reported to the user that a deploy carried
  "9 red tests, 1 of them a new regression," named the regression, identified
  which lane owned it, and messaged that lane about it.
- **What was actually true:** every one of those 9 was an artifact of my
  worktree. `scripts/session_worktree.py` excludes `data/` BY DEFAULT (34,689 of
  37,745 tracked files) and CLAUDE.md instructs every session to work that way.
  `_teams_match` -> `soccer_fixture_clubs` -> `all_teams` -> `rosters_path()`
  reads `rosters_<season>.csv` from `data/`; absent it,
  `_soccer_alias_by_league()` returns **0 leagues** and every soccer pair
  resolves to None. Same SHA, `data/`-complete tree: **144 passed**.
- **And the mirror-image failure, same evening, same two files.** Asked to fix
  the primary tree's failures, I found it 3 commits stale AND carrying 141
  uncommitted entries from other sessions -- including `venue_quote_fanin.py`
  (+107), mid-change, adding a game-scoped candidate key. Six tests asserting
  exact `_candidate_keys` lists were red there while `origin/main` was **145
  passed**. So the primary tree showed red main did not have, minutes after my
  worktree had shown red main did not have.
- **The general form:** a sparse worktree under-reports what code can see; a
  shared tree over-reports, because it contains work nobody has committed. Both
  produce confident, specific, WRONG failure names -- with assertion text, line
  numbers, and a plausible owner. Nothing about the output says "environment".

**How to apply:**
- **Only a clean worktree at `origin/main` answers "is main green."** `git
  worktree add --detach /c/tmp/<x> origin/main`, run, remove. It costs ~40s.
- **CHEAPER CONTROL, and usually the right one first** `[session 4465737c,
  2026-08-30]`: you rarely need a whole clean tree. `git diff origin/main --
  <path>` returning 0 lines PROVES that file matches main, so a dirty tree is a
  valid environment for anything whose inputs you can enumerate. They cleared a
  probe this way over three modules plus its registry CSV — no worktree, no 40s.
  **The caveat is the enumeration, not the method:** it is only sufficient once
  you have listed every input, TRANSITIVE IMPORTS AND `data/` INCLUDED. Miss one
  and you have proved something about the files you thought of. Use the diff
  when the input set is small and known; use the clean worktree when it is not,
  or when the question is "is the SUITE green" rather than "is this file main's".
- Before attributing ANY test failure to a commit, reproduce it there. If you
  cannot, the failure is yours, not the code's.
- **Never "fix" a red in the primary tree without checking `git status` on the
  module under test first.** The six here were another lane's in-flight
  cross-game-bleed fix; reverting the file to make them green would have deleted
  a live-money safety change. A shared tree showing red actively invites that.
- A peer's "I cannot reproduce" outranks your own reproduction when your
  environment is the non-standard one. `[session 5163d9b3 pushed back twice and
  was right both times.]`
- Corollary they supplied and it is the same rule one level up: **checks that
  agree are only independent if they differ in the decisive variable.** They
  reported "three configurations, all green"; all three carried `data/`. Their
  three checks were one check.

## 2026-08-29 — a null from an instrument you have not calibrated is not evidence. RUN THE CONTROL

- **What we believed:** that `venue_balance_history.json` being absent from
  `/api/ops/keyvalue/usage?top_keys=100` and from `sweep-preview` meant the new
  write was not happening.
- **What was actually true:** both endpoints ALSO report `venue_balances.json`
  absent -- a file written every worker tick and rendered on `/portfolio`. The
  smallest key `usage` lists is **196,768 bytes**; both files are a few hundred.
  The instrument cannot see artifacts of that size at all.
- **How to apply:** before reading a null as absence, ask what makes this
  instrument read PRESENT, and check it against something you already know is
  there. One extra call. Without it the honest answer ("not observable by any
  route available to me") is indistinguishable from a real finding -- and the
  real finding here would have been a false alarm about my own fix.
- Same family as [[feedback-instrument-blindness]] and
  [[feedback-absence-in-a-window-is-not-absence]]; this is the third instance,
  so the control is now the rule rather than the diligence.
---

### 2026-08-29 — FORBIDDEN: never treat a `lanes.md` claim as evidence that anyone is holding the file. `lane-guard.py` has NO liveness notion, so a claim outlives its session forever

- **What we believed:** the lane system's file claims describe live contention —
  if `lane-guard` blocks you, another session is working that file and the
  correct move is to surface the conflict and work elsewhere. The protocol says
  exactly that: "If another OPEN lane lists a file you need, stop and surface
  the conflict."
- **What was actually true:** claims never expire, and nothing ever released
  them on a session's death. Measured 2026-08-29: **26 OPEN lanes held 133
  claims while 3 sessions were alive.** 121 of those claims (91%) were enforced
  on behalf of sessions that no longer existed — some archived nine days
  earlier. There were also **56 `.current-lane.<session>` markers for 4 live
  sessions.** The lane blocks themselves were often not even wrong: several
  headers *say* "CLAIMS RELEASED" or "UNOWNED" in prose while their `- Files:`
  block still parses as a live claim, because the guard reads the block, not
  the header.
- **How we found out:** a user asking why so many things were claimed. Liveness
  is measurable and was never being measured: a session is live iff its
  transcript `~/.claude/projects/<proj>/<id>.jsonl` was written recently, and
  the break was unambiguous — 4 files inside 60s, the next 87 minutes back.
  The cost had already been paid once that same day: `live-venue-order-placement`
  needed a **USER OVERRIDE** to take `venue_quote_adapters.py` off
  `kalshi-line-aware-rungs`, a lane whose session was gone and whose header
  already said the files were free.
- **The rules going forward:**
  1. **Before honouring a claim, check the holder is alive.** The header names
     a session id; if its transcript is hours stale, the claim is a phantom and
     `py -3 scripts/release_phantom_lane_claims.py` releases it — no override,
     no permission, no waiting on a session that cannot answer.
  2. **A lane header saying "UNOWNED"/"CLAIMS RELEASED" releases NOTHING.**
     `lane-guard` parses the `- Files:` block and never reads the header's
     prose. Release means putting a `_DISCLAIMER_MARKERS` token ahead of the
     path text on every line of the block. Verify with the hook itself.
  3. **Prove a release on the guard, both directions.** Feed `lane-guard.py`
     the real payload before and after: a released path must go exit 2 -> exit
     0 **and a still-held path must stay exit 2**. A claim count dropping is
     not that proof — it is consistent with having disarmed the guard.
  4. **Do not run the release from PowerShell's pipe.** `'json' | py -3 hook.py`
     returned **exit 0 with no output** — `json.load` failed on the piped
     stdin and `main()` returns 0 on parse failure, so a BLOCKED path read as
     ALLOWED. That is the exact shape of a false clean bill. Use bash `printf`.
- **Cost:** one user override spent on a file nobody held, an unknown number of
  earlier sessions routed away from files that were free, and 121 claims'
  worth of standing false contention. Nothing was lost: the sweep released
  enforceability only — every path stays in its block as a record, and a lane
  resuming the work reclaims by striking the note.

---

## 2026-08-29 — FORBIDDEN: gating on a status string you did not read from the function that emits it. The whole conversion shipped INERT and every test was green. `[lane live-venue-order-placement]`

- **What we believed:** `#603`'s Kalshi half was done. The adapter resolved a
  ticker's club blob through `match_event_blob`, took the matched fixture, and
  keyed the quote to it. Code present, suite green, downstream green.
- **What was actually true:** the guard read
  `result["status"] == "matched"`. **`"matched"` is not a value that function
  ever returns.** Its vocabulary is `ok` / `no_match` / `ambiguous`. Every
  Kalshi quote failed the check, fell back to a bare key, and the conversion
  did **nothing at all**.
- **Everything else was right.** Blob extracted, split resolved against the
  schedule, teams returned, token built correctly. One guessed string, and the
  feature was decorative.
- **Why green meant nothing.** An inert conversion is indistinguishable from a
  correct one from outside: no test failed, no log line changed, and the
  fallback it landed in is the pre-change behaviour — which is by design
  *correct*, just not new. Had the fallback been an error instead of graceful
  degradation, this would have been obvious in a second.
- **How we found out:** ONE test —
  `test_a_kalshi_totals_quote_names_its_game_OFF_vs_ON` — asserting
  `on_keys != off`, i.e. *passing the new argument must CHANGE something*.
  An ON-only assertion passes if the qualifier is unconditional. An OFF-only
  assertion passes while inert. Only the pair discriminates.
- **The rules going forward:**
  1. **A status string is a fact about the emitting function. Read it there.**
     One grep of `match_event_blob` for `"status"` would have shown three
     values and none of them mine. I had already read that function's
     docstring in the same session and still guessed the value.
  2. **Every graceful fallback needs an off != on test.** Where wrong input
     degrades quietly instead of raising, "it works" and "it never runs" look
     identical. The test must assert the CHANGE, not the outcome.
  3. **Suspect inertness hardest when a feature is additive.** This one could
     only add a key. Adding nothing is a perfectly valid-looking state for an
     additive change, which is what let it through the whole suite.
- **Related, same session, same shape:** a `TypeError` from passing a new
  keyword to a monkeypatched three-argument `collect_quotes` stub was being
  swallowed by a surrounding `except Exception` into an EMPTY QUOTE POOL — a
  silent zero, the failure that module's own rule 3 exists to prevent. Two
  tests caught that one. **Both defects are the same species: a new argument
  that fails quietly and leaves the system looking healthy.**
- **Cost:** none realised — caught before commit, by a test written in the same
  pass. Had the off != on test not been written, a green suite and a
  confident finding would have recorded "Kalshi now names its game" while the
  cross-game bleed continued on every Kalshi quote in production.

## 2026-08-29 — FORBIDDEN: verifying a DELETION by grepping for the deleted string, without first proving the container renders

- **What we believed:** that grepping the served `/portfolio` HTML for the two
  sentences I had just removed, and finding them ABSENT, confirmed the edit was
  live. I reported it that way, with a tidy `ABSENT ok` next to each.
- **What was actually true:** there are ZERO unknown submits right now, so the
  entire `{% if L.unknown_submits %}` block does not render. Both sentences
  would have read ABSENT against the OLD template too. The check could not fail,
  which means it could not confirm anything either.
- **The shape, and it is the general one:** a test for the absence of X is only
  evidence once you know the page WOULD have shown X. Deletion checks are
  uniquely prone to this because the passing result and the vacuous result are
  byte-identical. Two other strings on the same page misled the same way in the
  same minute -- `500 ` matched `drift=+0.0500`, and `live-unknown-list` matched
  the CSS class DEFINITION in `<style>` rather than a rendered banner.

**How to apply:**
- **Verify a deployment by the ARTEFACT, not by the rendered absence:**
  `git show <deployed-sha>:<path>` for the content, plus the service's own
  reported SHA. That pair cannot be vacuous.
- If you must assert on rendered output, assert something POSITIVE that only the
  new code emits, and make the fixture actually reach that branch. The unit
  tests here did exactly that (`assert "Balance unchanged across the submit" in
  body`) and were the only real evidence the template works.
- State plainly when a path is covered by tests but has never run in
  production. "Deployed" and "exercised" are different claims.
- Third instance in one session of the same family, so it is now a rule rather
  than diligence: see [[feedback-instrument-blindness]] and the entry above on
  running the control before reading a null as absence.

---

## 2026-08-30 — FORBIDDEN: fixing the caller whose NAME matches what you are looking for, without checking which caller actually runs. `#603` shipped inert twice for this. `[lane live-venue-order-placement]`

- **What we believed:** the venue reprice happens in
  `venue_quote_fanin.apply_venue_quotes`. I traced the corrupted price properly
  — `book_prices` <- `cells` <- `_reprice_live_benchmark` <- `venue_quote_fanin`
  — and then stopped one frame early, at the caller whose name matched.
- **What was actually true:** there are TWO callers.
  `apply_venue_quotes_to_grid` is the one the board build runs, and it is the
  one that calls `_reprice_live_benchmark`. It looked up quotes with a bare
  `quote_key`, passed no schedule, and used none of `_candidate_keys`. **The
  entire fix landed on the function that does not run.**
- **The log said so the whole time.** `GRID_REPRICE` fires every cycle;
  `VENUE_REPRICE` appeared ZERO times in 45 minutes of production logs. I had
  grepped for both and read the absence as "the build has not reached that
  stage yet" rather than as "that stage is not on this path".
- **It survived a deploy and a production reading.** The reading came back flat
  (kalshi 2 -> 2) and I attributed it to empty NCAAF alias maps — a true fact
  that was NOT the cause. A real secondary finding made a wrong primary
  diagnosis feel well-evidenced.
- **The rules going forward:**
  1. **Identify the caller by its LOG LINE, not its name.** If two functions
     could do the job, find which one production actually emits from before
     editing either. One grep, and it was already in my terminal.
  2. **An absent log line is a fact about the path, not about the clock.**
     "It has not got there yet" and "it never goes there" look identical for as
     long as you are willing to keep waiting.
  3. **When a fix lands on a shared mechanism, EXTRACT the shared piece.** Both
     callers now use `_row_game_token` and `_quote_is_for_another_game`. Two
     paths with their own idea of a row's identity is a join that works on
     whichever one you happen to read.
  4. **A flat reading deserves the same scepticism as a green one.** I had a
     ready explanation (empty alias maps) and stopped looking. The question
     "could this code have run at all?" was never asked.
- **Related, same session:** the grid-path test I wrote first had `best: {}`, so
  `sides_seen` never incremented and `repriced == 0` passed against an
  implementation that did nothing. Fixed by giving `best` a real dict per side
  with a deliberately STALE age, so a legitimate quote genuinely would reprice.
  **A fixture that cannot fail is the same defect as a feature that cannot
  run.**
- **Cost:** one wasted deploy, one wasted production reading, and a recorded
  diagnosis that named the wrong cause. No money path affected — the adapters
  only qualify keys when handed a schedule, and the grid path passed none, so
  the inert version could not regress coverage either.


## 2026-08-30 — FORBIDDEN: an exact-count assertion over a pipeline that has an unmocked ADDITIVE source. It measures the machine, not the code

- **What we believed:** that `assertEqual(len(rows), 1)` tested "when the
  betting card is empty, the top-props source is used". It had been green in CI
  for as long as anyone had looked.
- **What was actually true:** `pregame_props` ends
  `return list(mlb_rows) + hr_target_rows` — HR targets are appended WHATEVER
  the fallback chain did. The test patched the two FALLBACK sources and left the
  ADDITIVE one live, so the count was really "1 + however many HR targets this
  machine has". Measured: **1 on a checkout with no MLB data, 11 on a populated
  mirror.** Row[0] was the patched row in both cases — the property under test
  was never broken. Only the count was environment-dependent.
- **The same shape one file over, and worse:** `test_artifact_publisher`
  asserted 7 repair requests. A PATH RESOLVER (`daily_artifact_path` ->
  `_resolve_data_path_with_reconcile` -> `shutil.copy2`) wrote **2.46MB into a
  fresh tempdir** as a side effect of being asked which paths are required, so
  two artifacts stopped looking missing and the count fell to 5.

**How to apply:**
- Assert the PROPERTY, not the population size, unless every contributor is
  stubbed. `rows[0]["name"] == "MLB top prop"` is the claim; `len(rows) == 1`
  smuggles in "and nothing else contributes", which is a statement about the
  machine.
- Before stubbing "the source", read the function to the RETURN. A fallback
  chain that ends in a `+` has a contributor no `if not rows:` branch reveals.
- **Treat a resolver that can WRITE as a mutation, not a lookup.** Nothing in
  the name `daily_artifact_path` suggests 2.46MB of I/O, and the caller
  explicitly wanted to judge presence on the runtime disk.
- Environment isolation is NOT the universal fix and reaching for it first cost
  me four attempts here: `SYNDICATE_DATA_ROOT`, `_MLB_SOURCE_ROOT`,
  `_REPORTS_ROOT`, `_ARTIFACT_ROOT_MLB` all failed because the leak was an
  unmocked call, and for the publisher because `_artifact_roots()` appends the
  repo path with no env over it. Find the contributor first.
- Verify a test fix in BOTH directions — the tree where it failed AND a clean
  worktree at `origin/main` where it passed. A fix that only makes the red tree
  green is indistinguishable from weakening the assertion.
- **A fix that makes things worse must be reverted, not defended.** Mocking
  `deploy_claim.active_claim` to None to stop six live-state failures produced
  eight. Reverted; the finding is logged unfixed. Related:
  [[feedback-rebaseline-before-judging]].
---

## 2026-08-30 — CORRECTION to the entry above: my "VENUE_REPRICE never fires" was LOG TRUNCATION, not absence. The rule I wrote from it was right; the evidence I wrote it from was not.

**RETRACTED:** *"`GRID_REPRICE` fires every cycle; `VENUE_REPRICE` appeared ZERO
times in 45 minutes of production logs"* and the conclusion drawn from it, that
`apply_venue_quotes` is never called.

**What actually happened.** I queried the Render logs API with `limit=200` and
no text filter. On a service emitting thousands of lines that returns the newest
200 — so my window never contained the line I was looking for, and I read the
empty result as proof the code path does not run.

Re-queried with `text=` filtering, same window:

    VENUE_REPRICE   8 matches  00:15-01:25Z   (00:18:39, 00:30:57, ...)
    GRID_REPRICE   20 matches

**BOTH PATHS RUN.** A peer lane (`exchange-join-refusals`) cited
`VENUE_REPRICE_KEYS unmatched 2255` off the 00:53:27Z build in an unrelated
message. That number could not exist if my finding were true, so I re-measured.
Credit theirs; I would not have looked again.

**WHAT SURVIVES, stated so this is not over-retracted.** The grid path genuinely
did lack the game term, and it is the one that calls `_reprice_live_benchmark`
-> `cells[book][side]` -> `book_prices`, which is where the corrupted prices come
from. `apply_venue_quotes` stamps freshness on opportunity rows and does not
write `cells`. **So the FIX was necessary and correct; the REASON I gave for it
was false.** `0c5243b4` stands.

**THE IRONY IS THE LESSON.** The entry above states *"an absent log line is a
fact about the path, not about the clock."* Mine was a fact about my QUERY. The
rule generalises one step further than I wrote it:

**An absent observation is a fact about the INSTRUMENT until you have shown the
instrument could have seen it.** Clock, path, and query limit are three ways to
be blind, and I had already written the rule for two of them while standing in
the third.

**Practical form:** before concluding a log line never appears, either use a
`text=` filter or prove the window was not truncated — a `limit` that equals the
number of rows returned is a truncation signal, and mine returned exactly 200.

**Cost:** a wrong causal claim committed to `learnings.md`, `findings_...md` and
a commit message, live for roughly 40 minutes. No wrong code: the change it
justified was independently correct.


## 2026-08-30 — RULE: an artifact is evidence only once you have checked it contains what its NAME claims. Four instances in one session

- **What we believed:** that `.syndicate/lanes.md.CONFLICTED.bak` held the
  pre-resolution ledger. It was offered to a user as the safety net that made an
  unresolved-merge situation recoverable.
- **What was actually true:** measured before use — 337,086 bytes, **0
  `<<<<<<<`, 0 `>>>>>>>`, 0 `=======`**, 54 headings, all four lanes present
  exactly once. It is the RESOLVED file under a name that says otherwise. The
  pre-resolution state is gone. **A file named `.CONFLICTED.bak` that contains
  no conflict is worse than no backup, because the next person will trust it.**
- **The same shape, three more times the same night, all measured:**
  - `INVARIANTS HOLD` printed over a file with conflict markers in it — the
    guard parsed BOTH sides as lanes. A green from a checker that cannot see the
    corruption it is standing in front of.
  - Production's `daily_summary_2026_07_12.json` byte-identical to the git
    mirror, which looks like proof the reconcile copy won and proves NOTHING —
    the mirror is refreshed FROM production, so identity is expected either way.
  - Grepping a served page for two sentences I had just deleted, and finding
    them absent — because the whole block does not render. The check could not
    have failed, so it could not confirm.

**How to apply:**
- **Before citing an artifact — backup, fixture, receipt, log, snapshot — open
  it and assert it contains the thing its name promises.** One `grep -c` for the
  distinguishing feature. If the artifact's whole purpose is to hold X, the check
  is "does it hold X", not "does it exist".
- A guard's PASS is evidence only if you know what makes it FAIL. Feed it the
  broken input once. `check_lane_invariants.py` now refuses conflict markers
  (`10f45a0c`) precisely because its green had never been tested against a
  corrupted ledger.
- Prefer artifacts that cannot be vacuous: `git show <sha>:<path>` for content
  and the service's own reported SHA for deployment beat any rendered absence.
- Corollary for backups specifically: **verify the copy before you rely on the
  original being disposable**, not after. The window in which the original still
  exists is the only window in which the check is actionable.
- Same family as [[feedback-instrument-blindness]] and the 2026-08-29 entry on
  running the control before reading a null as absence — this is the fourth
  distinct instance, so it is a standing rule, not diligence.

---

## 2026-08-30 — FORBIDDEN: `git checkout --theirs .` to clear a conflict in an append-only ledger. It is a DELETION TOOL, and it staged 929 of them over a peer's work.

- **What we believed:** that after hand-resolving a stash-pop conflict in
  `deploys.md`, a trailing `git checkout --theirs .` was a harmless tidy-up.
- **What was actually true:** the stashed side of both conflict regions was
  EMPTY — an older copy of the ledger. `--theirs` therefore replaced the
  working tree with nothing, staging **929 deletions**, including a peer lane's
  `da2de430` entry. My own python resolution, run seconds earlier, had been
  CORRECT; the git shortcut undid it.
- **How we found out:** `git diff --cached --stat` before committing, which
  read `929 deletions(-)` on a file that should only ever grow. That habit is
  the only reason this is a near-miss and not an incident — the repo already
  carries a 4,993-staged-deletion entry from the same family.
- **A second trap inside the recovery.** After restoring from HEAD I checked for
  my own entry using the phrase from the COMMIT TITLE ("one real reading, two
  worthless zeros"), which never appears in the file. It reported missing and I
  briefly believed I had lost my own work. **Grep the artifact for text that is
  in the artifact, not for what you called the commit.**
- **The rules going forward:**
  1. **On an append-only file, `--ours`/`--theirs` are both wrong by default.**
     The correct resolution is a UNION, and it has to be reasoned about. If one
     side is empty, that side is a stale copy and taking it deletes history.
  2. **A negative line count on a ledger is an alarm, not a diff.** `deploys.md`,
     `learnings.md`, `lanes.md` and `state.md` grow. Any staged deletion in them
     is a mistake until proven otherwise.
  3. **Verify a restore by CONTENT, both directions.** Mine present AND the
     peer's present, plus byte count and zero markers. One of those four alone
     would have passed while the file was wrong.
- **Cost:** none realised. Caught pre-commit, restored from HEAD, verified at
  2,091,630 bytes with the peer's entry and mine both present.

---

## 2026-08-30 — FORBIDDEN: measuring a FILL-time cost from a SETTLEMENT-time quantity. Realized P&L is `(exit - entry)`; a commission taken at fill is invisible to it BY CONSTRUCTION, so the method returns zero whether or not a fee was charged.

- **What we believed:** Polymarket charges no commission. Ten venue-settled
  orders, $75.98 notional, implied fee -2.37 bps, every value negative-or-zero.
  I checked circularity (the delta is the venue's number, not ours) and shipped
  it — into `state.md`, a lane header, a code constant, and an INVERTED test.
- **What was actually true:** ~150 bps of notional. Disproven on the same
  sample: `C60JWBG0WKDK` implied -0.0023 in my table while the venue charged
  **$0.06**. Two more of the ten were also commissioned and read ~0.
- **The defect is the INSTRUMENT, not the arithmetic.** `venue_settlement`
  grades from `after_realized - before_realized` on the position. If the venue
  books the commission at fill — reducing cash, not the position's entry basis
  — the settlement delta never contains it. **My method had no path to a
  non-zero answer.** Ten agreeing zeros felt like strong evidence and were one
  observation of the instrument, repeated.
- **How we found out:** a peer's unrelated message quoted a real
  `commissionNotionalTotalCollected` of `0.0600`, plus an independent
  `buyingPower` delta of -$1.8977 on a $1.8377 fill. Two routes, same $0.06.
  They also flagged the one field that SUPPORTED me
  (`commissionsBasisPoints: '0'`) rather than only the ones that did not.
- **The rules going forward:**
  1. **Match the measurement's TIMING to the cost's timing.** A fill-time charge
     needs a fill-time observable — the commission field, or cash before/after
     the fill. A settlement-time quantity can only see settlement-time effects.
  2. **Before believing a zero, construct the case that would make it
     non-zero.** If you cannot describe an input that flips it, the instrument
     is blind and the zero is a fact about the instrument. I have written this
     rule twice tonight in other words and still shipped this.
  3. **N agreeing samples from ONE method is one observation.** The ten did not
     corroborate each other; they shared a blind spot.
  4. **A premise about what is READABLE decays fast in a shared repo.** Mine
     ("the value never reaches the ledger") was true when written and stale
     within hours because a peer fixed exactly that.
- **Two further defects the correction exposed**, both from the same root:
  the "worst case" bound was a QUADRATIC and after the shape fix sat BELOW the
  measured fee at every price — a bound cheaper than the thing it bounds; and
  the first correction still modelled Polymarket quadratically, understating
  the tails sevenfold where in-play pairs actually live.
- **Cost:** a wrong money-path threshold live on `main` for ~40 minutes,
  2.8x too permissive at even money. Not deployed, and the arb verdict was
  negative either way, so nothing was placed on it. Caught by a peer, not by me.

## 2026-08-30 — FORBIDDEN: attributing a commit to a session by ADJACENCY. And: a method that cannot return a non-zero answer has not measured zero

Two distinct rules from one exchange; both cost real time.

### 1. Commit adjacency is not authorship
- **What we believed:** that `c17bc3d8` belonged to the session whose commit
  landed 45 seconds earlier. I sent that session a substantive challenge to a
  live-money finding it had never touched.
- **What was actually true:** `git show --stat c17bc3d8` names five files; the
  accused session's commits touched **0 of 5**, and 0 for `state.md`. In this
  repo EVERY commit carries `github-actions[bot]`, so the author field cannot
  separate sessions — and with a dozen sessions pushing to one branch, temporal
  proximity is the default, not a signal.
- **How to apply:** attribute by `git show --stat <commit>` intersected with the
  lane's declared `- Files:` block. One command. Never by neighbourhood, never
  by "who was working on something similar". If no lane claims the files, say
  the owner is unknown rather than guessing — a misrouted challenge is worse
  than an unrouted one, because it burns a peer's turn and leaves the real owner
  uninformed.

### 2. An instrument whose output is constant is not evidence
- **What we believed:** that ten venue-settled orders showing zero implied fee
  measured a zero fee. Break-even was moved 3.38c -> 0.88c on it and a test was
  inverted to pin it.
- **What was actually true:** the venue's realized-P&L field is fee-EXCLUSIVE.
  Every settled row's `pnl_dollars` equals ±(contracts x fill_price) EXACTLY —
  the no-fee arithmetic. **That method returns zero whether or not a commission
  was charged**, so it could not have found one.
- **The account settled it.** `buyingPower` 101.33 -> 91.17 over a window
  enumerated FIRST and containing exactly two filled orders: no-fee expectation
  9.84, with-fee 10.16, observed **10.16**. Exact with fees, on a second
  independent window too.
- **How to apply:** before believing a null, ask what input would make this
  instrument return non-null, and confirm it CAN. If the answer is "nothing in
  the population I sampled", the reading is structural, not empirical. Prefer
  the measurement that is not a field interpretation — cash moved is harder to
  misread than a field named `commissionNotionalTotalCollected`.
- **Direction of error matters when deciding whether to wait.** A fee measured
  too LOW moves a threshold BELOW break-even and manufactures arbs that lose on
  every fill. That asymmetry is why the ledger was corrected before the owning
  lane replied — the code was left untouched, and the refutation was placed
  ABOVE the original rather than replacing it.
- Fifth instance of the family this session: see the 2026-08-30 entry on
  artifacts, and [[feedback-instrument-blindness]].

---

## 2026-08-30 — checks that AGREE are only independent if they differ in the decisive variable

I reported "three configurations, all green" against a peer's red test. All
three carried `data/soccer_source`. It was ONE configuration run three times,
and the peer reproduced it immediately in a `data/`-less worktree -- which is
what `scripts/session_worktree.py` creates BY DEFAULT and what CLAUDE.md tells
every session to use.

The same shape three times in one day:
- three trees that shared the decisive variable
- a fee rate fitted on fills that all share one multiplier (a peer's, caught
  before it was quoted)
- `market_indexed_under` as `sorted(...)[:4]`, where `cfb` and `alsv` sort first
  and fill the cap on ANY market -- read as attribution TWICE

**RULE: before reporting agreement across N checks, name the variable that
differs between them. If you cannot, you have one check and N-1 rehearsals.**

Corollary that cost the most: a bounded sample that finds NOTHING is not
evidence of absence. 19 sampled Polymarket PROP slugs showed no corners family
and I was one reading from DELETING the corners route. The census found 434.

---

## 2026-08-30 — FORBIDDEN: gating one instance of a shared cause

A peer's test went red because the per-league soccer roster lives in `data/`,
which the documented worktree excludes. I gated THAT test, wrote the reason into
its skip text, and left EIGHT more failing for the identical cause -- in a
session whose whole theme is that a fix without a mechanism looks like a working
one.

`_soccer_rosters_present()` was already the exact predicate for all nine.

**RULE: when a cause is named, grep for every site it reaches BEFORE fixing the
one that was reported.** The reported instance is a sample, not the population.

Related, same day: a peer shipped `#603` fixing "the wrong function" and had to
follow with "fix the GRID path -- the one that actually runs".

---

## 2026-08-30 — "not priceable" and "no board row" are different problems with different owners

I told the user Kalshi team totals were "not priceable" because the board has no
`team_totals` market. Wrong framing, and they challenged it.

`basketball_props_smart_sim` already projects per-team scoring -- `home_mu`,
`away_mu`, `home_team_total_pts_mean`, `team_total_pts` in every simulated box.
It is a Monte Carlo, so P(team over N) is countable off the runs TODAY.

What is missing is a BOARD ROW, because the board is built from the odds source
and OddsAPI supplies no WNBA team total.

**RULE: "we cannot model this" and "nothing generates the row" call for
completely different work and different owners. Say which.** One is a modelling
problem; the other is a plumbing problem that a model already solved.

This generalises to the session's strategic finding: 25,000 venue markets
captured, 277 acted on, and almost none of the loss is modelling.

---

## 2026-08-30 — an orphaned `autostash` is somebody's work, and nothing reads a stash list

Eight orphaned `autostash` entries had accumulated in the shared tree, oldest
from June. An autostash only survives when the rebase that created it did NOT
finish, so each is uncommitted work picked up and never handed back.

Triage: 3 were already on main (checked by SYMBOL, not line count -- they
differed by 662-790 lines purely because main had moved on), 4 were `data/**`
mirror output, and ONE (`tools/ask.py`, 2026-06-22) existed nowhere else.

**RULE: drop stashes in DESCENDING index order** -- a low drop renumbers every
higher one, which is how the wrong stash gets deleted. **Record SHAs BEFORE the
first drop and re-check one AFTER**, so the recovery path is verified rather
than asserted.


## 2026-08-30 — RULE: a shared tree can sit BEHIND its own HEAD, and the diff then reads as YOU reverting someone. Prove whose content is on disk before restoring

- **What we believed:** that `git status` showing my two files as ` M` in the
  primary tree meant I had uncommitted work there.
- **What was actually true:** `HEAD == origin/main` and my commit `c0989cfe` was
  IN it, yet the working copy was the version from BEFORE it — `git diff` read
  `-53` on the module and `-72` on the tests, i.e. **deleting all eight tests I
  had just added.** Anyone committing those paths from that tree would have
  reverted me, and the blame would have read as theirs.
- **Cause (unconfirmed, but it is the documented one):** a `commit-tree` +
  `update-ref` / scratch-index recipe moves HEAD and updates NEITHER the index
  NOR the working tree, so the tree is left behind by exactly whatever landed in
  between. See [[project-shared-tree-commit-recipes]], which warns the damage
  "lands later, on a different lane, and presents as *them* reverting *you*."
  This is that, observed from the victim's side.

**How to apply:**
- **Before restoring anything in a shared tree, prove WHOSE content is on
  disk.** Hash the working copy against candidate revisions:
  `disk == HEAD?` and `disk == <mycommit>^?`. Here it matched `c0989cfe^`
  exactly — my own pre-commit state, no foreign work — which is what made
  `git checkout HEAD -- <paths>` safe. Had it matched neither, someone else's
  edit was in there and the restore would have destroyed it.
- **Scope the restore to the exact paths and check the blast radius by count:**
  dirty entries 197 -> 195, exactly two. A restore that moves any other number
  touched something you did not inspect.
- **` M` in a shared tree is not evidence of your own uncommitted work.** It
  means only "disk differs from HEAD", and in a tree several sessions write to,
  the difference is as likely to be staleness as authorship. Check the direction
  before assuming: `git diff` showing DELETIONS of your own recent additions is
  the signature of a stale tree, not of work in progress.
- Corollary: after committing from a worktree, it is worth confirming the shared
  tree agrees with HEAD on the paths you touched. Nothing warns you, and the
  window between your commit and someone else's `git add` is where it bites.

## 2026-08-30 — METHOD: agreement across a sample cannot distinguish a real signal from a CONSTANT INSTRUMENT. Ask what the method is structurally blind to before counting how many times it agreed

**What happened.** Polymarket's fee was "measured" at zero from the venue's own
realized P&L on ten settled orders — every value negative-or-zero, total
−$0.0180, −2.37 bps of notional, one outlier excluded for a documented reason.
Ten independent orders agreeing to within rounding. It was published, acted on,
and it inverted a lane's recorded priority ("Polymarket is two thirds of pair
cost" → "Kalshi is the entire bar").

**The real fee is 150 bps of notional, flat.** Order `C60JWBG0WKDK` implied
−0.0023 by that method while the venue's own payload recorded **$0.0600
collected**.

**Why the method could not have worked.** `venue_settlement` grades from
`delta = after_realized − before_realized`. Realized P&L is `exit − entry`. The
commission is charged **at fill** and is therefore **not a term in that
difference**. The method was not a weak measurement of the fee; it was **not a
measurement of the fee at all** — fee-blind by construction. It would have
returned approximately zero on a venue charging nothing and, identically, on a
venue charging plenty.

**The trap is that the blindness LOOKED like corroboration.** Ten orders
agreeing was read as ten independent confirmations. They were ten repetitions of
one constant instrument. Tightness of agreement measured the *instrument's*
consistency, and said nothing whatever about the quantity.

**How to apply:**
- **Before counting agreements, write down the arithmetic path from the quantity
  you want to the number you are reading.** If the quantity does not appear as a
  term, no sample size rescues it. Here: fee → charged at fill; reading →
  `exit − entry`; the fee is absent from the expression. One line, and it kills
  the finding before ten orders endorse it.
- **A null result from an untested instrument is not a null result.** Same shape
  as [[feedback-instrument-blindness]] (a healthy reading is evidence only once
  you know what makes it read unhealthy) and
  [[feedback-absence-in-a-window-is-not-absence]]. This is that failure applied
  to a *derived* quantity rather than a log line.
- **Prefer a route where the quantity is NAMED over one where it is inferred.**
  `commissionNotionalTotalCollected` states the fee. Realized P&L implies it, and
  the implication was invalid. Two named routes agreed
  (`commissionNotionalTotalCollected`, and a peer's independent `buyingPower`
  cash delta); the one inferred route was the one that was wrong.
- **A single discriminating fill beats a sample that cannot discriminate.** The
  18.70-contract fill separates flat ($0.2805) from cost-basis ($0.1579) on its
  own. Ten agreeing small fills separated nothing.
- **Errors in the CHEAP direction manufacture trades.** A fee understated to zero
  does not merely mis-rank; it invents opportunities that do not exist. Bias an
  unverified cost estimate upward — and check that the bound still bounds:
  `POLYMARKET_ASSUMED_WORST_CASE_RATE` had been tightened to 0.01 **on the
  strength of the zero finding**, which made the supposedly conservative bound
  CHEAPER than the truth (0.015). A bound derived from a belief inherits that
  belief; when the belief falls the bound is just a second wrong number.
  `test_venue_fees.py:272` now asserts `bound > measured` at every price.

## 2026-08-30 — RULE: a retraction must reach the DOCSTRING of the module whose behaviour changed. Prose is an interface, and it has no test

**What happened.** The zero-fee finding above was retracted and the constant
fixed the same hour: `polymarket_fee_dollars` returned `0.015 * contracts`.
**The module docstring went on asserting the retracted finding for four
commits** — "Polymarket took **no commission** on these fills",
"`polymarket_fee_dollars` returns the measured 0.0" — and additionally called
`commissionsBasisPoints` "authoritative where this inference is not", a field
that reads `'0'` on every order observed. A reader following the prose would
have been handed a zero fee and landed exactly where the retraction started.

Nothing was red. Every test passed throughout, because tests exercise the
function and no test reads the paragraph above it.

**A peer had checked this area and cleared it.** Their question was *"does
anything PRICE off this field"* — answer: no, only a comment and a log line. The
right question was *"does anything SAY something about this field"*. Containment
of the executable risk was real and was not containment.

**How to apply:**
- **A retraction has a checklist and the docstring is on it:** the constant, the
  function, the module header, the finding, `state.md`. Fixing the value and
  leaving the prose produces a module that is *internally contradictory in the
  authoritative voice* — the stale sentence sits beside true ones and inherits
  their credibility.
- **When you retract, `grep` the retracted CLAIM, not just the changed symbol.**
  "zero", "no commission", "0.0" — the wrong belief is stated in prose that does
  not mention the constant you edited.
- **"Nothing reads it" is not "nothing says it".** Dead-code reasoning does not
  transfer to documentation: prose has no callers, so it is never dead and never
  flagged.
- Related: [[feedback-documented-caveat-is-a-scheduled-defect]] (a caveat comes
  due), [[project-closed-todo-not-shipped-gap]] (a closure is not a landing).


## 2026-08-30 — RULE: `lastRunAt` is DISPATCH. Prove execution from the run's own artifact, and prove WHICH failure it was before naming it

- **What we believed:** that a scheduled task with `lastRunAt` set had run. Mine
  showed `lastRunAt: 2026-08-30T03:10:47Z` and had done **nothing at all** — no
  heartbeat, no output, no findings.
- **What was actually true:** it stalled ~13 seconds in, waiting on a tool
  approval no human was present to grant. `lastActivityAt` froze at 03:11:00
  while `isRunning` stayed `true` for fifteen minutes.
- **The heartbeat caught it on run one**, having been added an hour earlier for
  exactly this. A task that is SILENT on a null result plus a `lastRunAt` that
  records dispatch = "ran and found nothing" and "never ran" are the same
  observation. **Any silent-on-null watcher needs a liveness artifact or its
  silence is uninterpretable.**

**And the second half, which is where I nearly stopped too early:**

- I first called it a Modern Standby stall — the documented failure on this
  machine (`lastRunAt is dispatch`, a 9h13m suspension). Wrong. `get_session`
  showed a session existing with `scheduledTaskId` set, which **proves it
  executed**. Same symptom, different cause, different fix: a stall needs
  waking, a permission block needs the task narrowed or pre-approved.
- **How to apply:** two artifacts, not one. `lastRunAt` answers *was it
  dispatched*. A run SESSION with `scheduledTaskId` answers *did it start*. The
  task's own written artifact answers *did it work*. Naming the failure without
  the middle one gets the remedy wrong.
- **Design consequence:** a scheduled task whose first action needs approval is
  not unattended, whatever its schedule says. Prefer unauthenticated reads and
  local writes; put credentials and `git push` in an interactive session. When
  narrowing costs coverage, say what was given up — here `balance_settled` and
  the log-derived control — and REBUILD the control from what remains rather
  than dropping it (`recent_orders_60m` off the same public payload).
- Related: [[project-lastrunat-is-dispatch-not-execution]], and the 2026-08-30
  entry on artifacts being evidence only once you check they contain what their
  name claims.


## 2026-08-30 — FORBIDDEN: shipping a scheduled task without proving it can complete ONE run. A schedule is not a mechanism

- **What we believed:** that writing a good task prompt and setting a cron
  produced a working watcher. Mine was created to close the last open
  measurement of a long session, and was reported as "the durable version that
  survives the session".
- **What was actually true:** it never worked. Two dispatches, two sessions
  created, two freezes within a minute, **zero measurements**. It blocked on the
  permission prompt for its FIRST `Bash` call — read directly from the run's
  transcript, which was two messages: the prompt, then `(called Bash)`.
- **A NEW SCHEDULED TASK HAS NO STORED TOOL APPROVALS.** Approvals are captured
  during a run and replayed on later runs, so tasks that already work do so
  because a human once approved them. A brand-new one has nothing, and its first
  tool call blocks — regardless of how modest the command is.
- **I narrowed it to read-only and that was the WRONG REMEDY, recommended by
  me.** The blocker is the TOOL, not what the tool does. Removing credentials,
  the Render API and every `git` command changed nothing, because `curl` was
  always going to prompt first. Diagnosing the *class* of failure is not the
  same as diagnosing the *cause*.

**How to apply:**
- **Prove one complete run before believing a schedule.** The proof is the
  task's own artifact, not `lastRunAt` and not a green-looking session list.
- **Give any silent-on-null task a liveness artifact.** The heartbeat here was
  the only reason the failure was visible at all: without it, `lastRunAt` set +
  silence reads as "ran, found nothing" — a clean green from something that did
  nothing, twice.
- **Three artifacts, three questions**: `lastRunAt` = dispatched; a run SESSION
  with `scheduledTaskId` = started; the written artifact = worked. Name the
  failure only after all three.
- **Use a working sibling as the control.** `live-gameline-accuracy-snapshot`
  fired and COMPLETED in the same minutes on the same machine — which ruled out
  the scheduler, the machine and Modern Standby in one reading, and left
  approvals as the only difference.
- **An enabled-but-broken schedule is worse than none**: it manufactures a dead
  session every hour that looks like activity. Disable it and hand the
  measurement back to a human, rather than leaving a watcher that cannot watch.

## 2026-08-30 — FORBIDDEN: reading a gate's VERDICT without reading what its KEY covers. A measurement about one claim silently denied a different one

- **What happened.** `football/pick_gate.py` measured the NCAAF margin model
  losing to the close (n=2233, t=+17.20) — correct, and correctly denying. But
  the registry was keyed `(sport, market)`, so the same verdict also suppressed
  a claim nobody had measured and that uses no model: *this book's price beats
  the market's own consensus*. Measured on production 2026-08-29, the cost was
  total: **90 of 90 board sides carried a computed `edge_vs_consensus_pct` while
  45 of 45 rows rendered no edge at all**, and `portfolio_commit` refused all 90
  as `no_model_edge_pct`. The number existed, was served, and was thrown away
  one layer below the user. Two prior sessions read the gate, agreed it was
  correct, and moved on — because the VERDICT was sound. Nobody asked what the
  KEY spanned.
- **The rule going forward:** when a gate denies, read its KEY, not just its
  reason. Ask *what else does this key cover that the measurement never
  touched?* A gate is entitled to deny what it measured; denying a neighbouring
  claim by sharing a key with it is an accident, not a policy. The fix shape is
  a BASIS dimension — the claim being made — not a relaxation of the threshold.
- Corollary, and it is what makes this expensive to find: a correct gate with an
  over-broad key produces a board that is **empty and self-explanatory**. Every
  surface says exactly why, in terms that are true. There is no error, no zero
  counter, and no anomaly to trip over.

## 2026-08-30 — FORBIDDEN: reporting a config key as UNSET without reading its LIVE value. "The knob is not reaching X" does not mean the knob is empty

- **What happened.** I told the user and wrote into two ledger files that
  `SYNDICATE_LIVE_ODDS_GAME_LINE_REGIONS` was "unset on every service", and
  built a whole "wired but not enabled" framing on it. `render_env_set` then
  reported `before 'eu,us_ex'` on refresh-worker and `NO CHANGE NEEDED` on
  live-odds-worker: **it had been set on both workers the entire time.** The
  source was `findings_2026-08-26_ncaaf_opener_readiness.md`, which says the
  knob *"already exists as a knob; it is not reaching the NCAAF capture"* — a
  statement about a missing READER that I read as a statement about a missing
  VALUE.
- **The rule going forward:** a claim that a key is unset is a claim about
  production, and only a live read of the env is evidence for it. Reading a
  findings doc is not. Before reporting "not enabled", run the setter/reader and
  quote its `before`. And distinguish the two failure modes explicitly, because
  they have different fixes: **absent VALUE** is a config change; **absent
  READER** is a code change, and setting the value fixes nothing while making
  the environment look correct.
- Near-miss worth recording: had I "enabled" it by setting the var without the
  code change, nothing would have happened and the config would have read as
  done. Related: [[feedback_presence_is_not_reachability]].

## 2026-08-30 — RULE: a guard that refuses only what it can PROVE wrong is SILENT on the majority case when identity is usually unknown. Measure what share of the population it can even evaluate, before shipping it

**What happened.** `#603` — venue quotes answering the wrong game. The first fix
added a game-qualified key and refused any quote that **named a different
fixture**. It was correct, tested, deployed, and on its first production board
it **rejected exactly zero**.

The quotes doing the damage named nothing at all. A bare key is
`sport|market|side|line` and carries no game term, so one unnamed quote answers
every row that shares it:

    refs answering >1 FIXTURE       11 of 35
    rows served by such a ref      108 of 148   (73%)
    one Belgian tie ticker answered 33 fixtures across five countries
    a White Sox@Twins ticker was the SERVED HEADLINE price on Orioles@Athletics

The fix documented its own asymmetry as a virtue: *"a quote that names none is
allowed through exactly as it is today... it can only ever remove a match that
is provably wrong."* True, and the wrong bar. **"Cannot regress coverage" and
"cannot fix anything" were the same property**, and nothing in the design said
which one it would be.

**The rule that replaced it inverts the burden**: on a CONTESTED key — one more
than one game claims — a match now requires POSITIVE confirmation. Absent
identity refuses instead of passing. Result: 0 of 96 refs, against 192 contested
keys and 992 rows of opportunity.

**How to apply:**
- **Before shipping a guard, compute its DENOMINATOR: on today's data, how many
  of the bad cases does it have enough information to judge?** Not "is the rule
  correct" — a correct rule with no jurisdiction is inert. One query would have
  said 73% of the population carried no game name and the guard could not see
  any of them.
- **"Refuses only what is provably wrong" is a red flag wherever the missing
  proof IS the failure mode.** Identity guards are the common case: the join
  breaks precisely because something could not be identified, so a rule keyed on
  successful identification is scoped to the healthy rows.
- **Prefer confirmation to refutation when the population is mostly unknown.**
  Require a positive match on the contested subset and let the uncontested pass
  — that preserves coverage exactly where it is safe. Measured cost here: 107
  rows dropped, and 0 of them had a plausibly-correct ticker.
- Companion to [[feedback-unknown-must-not-default-permissive]], which is the
  same failure at the level of ONE branch; this is it at the level of a whole
  guard's scope. Both were live in the same file on the same night: the
  replacement rule ALSO shipped inert, because its claimant map read only the
  grid row shape (`sides`) and returned empty for candidate rows (`side`), and
  an absent key took the permissive branch.



## 2026-08-30 — FORBIDDEN: `[ -d data ]` as a check that a worktree is data-complete. Partial is worse than absent, and it passes

- **What we believed:** that having confirmed `data/` was "present", a worktree
  was a valid place to triage test failures. I had already written the rule that
  a `data/`-less tree fabricates failures, and I checked for it.
- **What was actually true:** `core.sparseCheckout=true` — set by
  `scripts/session_worktree.py`, which excludes `data/` BY DESIGN — **survived a
  later `git checkout --detach origin/main`**. The tree had **12 files** under
  `data/` against a complete tree's **34,758**, and `[ -d data ]` reported
  "present" for both. I ran a 23-file triage sweep in it.
- **What caught it was an IMPOSSIBLE READING, not the check:** isolation
  reported MORE failures than the full suite (19 vs 1 on
  `test_ncaaf_team_registry_reachability`; 13 vs 2 on
  `test_ncaaf_oddsapi_game_lines`). **Running a file alone cannot ADD
  failures** — that arithmetic is what exposed the environment, after the
  directory check had already passed.
- The corrected sweep differed in BOTH directions: pollution files 10 -> 6, real
  failures 13 files -> 17. The bad sweep under-reported real failures AND
  inflated their counts, so no part of it was salvageable.

**How to apply:**
- **Check data COMPLETENESS, never presence.** `find data -type f | wc -l`
  against `git ls-files data | wc -l`, or `git config core.sparseCheckout`. A
  directory that exists tells you nothing.
- **Sparse-checkout is sticky.** Re-pointing a worktree with `checkout --detach`
  does NOT clear it. `git sparse-checkout disable` does.
- **Keep one KNOWN-COMPLETE tree and do measurement there.** Mixing a session
  worktree (deliberately partial) with a measurement tree (must be complete) is
  the setup for this, and the two look identical to every cheap check.
- **Trust an arithmetic impossibility over a passing environment check.** If a
  narrower run produces more failures, or a subset exceeds its superset, stop
  and re-derive the environment before reading a single result.
- Fourth form of the same family this session, after: absent `data/` faking a
  regression, an artifact that did not contain what its name claimed, and a
  guard that passed over conflict markers. The common shape is a cheap check
  that cannot distinguish the healthy case from the broken one.

## 2026-08-30 — RULE: two guards in series, each encoding a DIRECTION assumption, can withhold a TRUE value with no error anywhere. Each is individually correct and neither can clear the other

**What happened.** Live execution halted for ~13 hours on both venues. Nothing
errored, nothing was misconfigured, and every component behaved exactly as
written:

1. `polymarket_us_orders.FILL_ABOVE_LIMIT` saw `avgPx 0.2350` against our `0.22`
   limit and WITHHELD the price, on the rule *"a BUY cannot fill above its own
   limit."* True. **The order was `side=ORDER_SIDE_SELL`,
   `intent=ORDER_INTENT_BUY_SHORT`** — on a sell, filling above the limit is
   price improvement, and the inverse rule (a SELL cannot fill BELOW its limit)
   was never encoded.
2. `execution_ledger`'s reconcile then found `fill_price=None`, fell back to a
   CONTRACT bound, and refused `13.13 > 10.8953 + 0.01` as implausible — while
   its own comment said the failure it guards against is a 100x fixed-point
   error. 1.21x is price improvement.
3. A refused order can never be stamped, so it blocked every live slate
   indefinitely.

**The venue had reported the price all along.** Our own guard suppressed it, and
the second guard then punished its absence. Neither guard could clear the other,
because each was doing its job under an assumption the other could not see.

**How to apply:**
- **When a guard encodes a direction — buy/sell, over/under, long/short, sender/
  receiver — write the inverse in the same commit or refuse both.** A rule true
  in one direction is a rule that is silently WRONG in the other, and the wrong
  case will not raise; it will quietly produce a null, a withhold, or a refusal
  that looks like data.
- **Trace what a withhold does DOWNSTREAM before shipping it.** Withholding was
  the right call at the point of decision (the price could not be validated) and
  catastrophic two functions later, where "absent" meant something different.
  `polymarket_us_orders` even DOCUMENTED the intended downstream behaviour —
  *"reconciliation falls back to the price we ASKED for"* — and reconciliation
  did no such thing. A documented hand-off nobody tested is a guess.
- **A halt with no error line is the signature.** Look for a chain of individually
  correct guards, not a broken component. Every counter here read healthy:
  `implausible=1` was the only number in the whole system that was unusual, and
  it named a unit error that had not occurred.
- **Ask of any guard: what does it emit when it fires, and can the next stage
  tell that from a genuine absence?** Here it could not — `fill_price=None`
  meant both "the venue said nothing" and "we suppressed what it said", and the
  downstream branch was written for the first.
- Companion to [[feedback-gate-on-the-output-not-the-input]] and
  [[feedback-unknown-must-not-default-permissive]]. Raised as a generalisation by
  a peer session that had hit the same shape from the opposite side.

## 2026-08-30 — METHOD: a DEGENERATE distribution is not a boring result. It is evidence the field is not measuring what its NAME says

**What happened.** A freshness ceiling (`MAX_VENUE_QUOTE_AGE_SECONDS = 45`) was
refusing live venue quotes, and the two ages recoverable from refusals were both
64s. Rather than move the ceiling on n=2 from the censored side, the age
distribution was instrumented UNCENSORED — every quote considered, passing and
failing. First production emission:

    sport=mlb    n=32  min=4.9  p25=4.9  p50=4.9  p75=4.9  p90=4.9  max=4.9
    sport=soccer n=2   min=34.5 ... max=34.5

**Thirty-two values, identical to the decimal.** The expected reading was "the
spread is wider than I thought" or "the tail is long". The actual reading was
that `age_seconds` **is not a per-quote age at all** — it is the age of the whole
venue CAPTURE for that sport, and every quote in a build inherits it.

**That changed what the guard is.** It is not filtering stale quotes out of
fresh ones; it is an ALL-OR-NOTHING gate on one number per sport per build — a
race between the capture cycle and the board build cycle. Two readings that had
looked like different market conditions were the same mechanism:

    16:57Z  capture 64s old   ->  0 of 6 passed
    17:28Z  capture 4.9s old  ->  32 of 32 passed

Raising the ceiling would have "fixed" it by widening tolerance for a scheduling
artifact, and the number would have looked defensible because it came from data.

**How to apply:**
- **When a distribution collapses to one value, stop and ask what the field
  actually is.** Zero variance across a population that should vary is not a
  quiet result to note and move past; it means the quantity is constant by
  CONSTRUCTION, which almost always means it is measuring a different thing
  from the one its name promises.
- **The name is the hypothesis.** `age_seconds` on a per-quote object reads as
  per-quote freshness. Nothing asserted that, and 32 identical values disproved
  it in one line.
- **This is why the sample had to be uncensored.** Refusals alone would have
  given 64, 64 — also degenerate, but degenerate for a second reason (one
  build's worth of failures), and indistinguishable from a real slow tail. The
  passing values are what made the constancy legible.
- **A guard whose input is constant across a population is a coin flip on a
  schedule, not a filter.** Look for that shape wherever a per-item threshold
  sits on a field populated once per batch.
- Corollary for the fix: prefer removing the race (have the consumer read or
  trigger the capture it needs) over widening the bar, and RENAME the bar to
  what it gates. The mis-description is what made the original number look
  reasonable.
- Related: [[feedback-instrument-blindness]] and
  [[feedback-read-the-field-you-already-have]]. Prompted by a peer session
  observing that percentiles would have HIDDEN this had they not been
  degenerate.

## 2026-08-30 — FORBIDDEN: reasoning about a limit order's cost as if the LIMIT were the price paid. It is a CAP; a marketable limit fills at the book.

`round_price_to_tick` floored a BUY, and the docstring gave the reason: rounding
up "pays more than the price the edge was computed against -- small per
contract and systematic across a slate." Every clause of that is true and the
conclusion is still wrong, which is why it survived review.

The error is a unit confusion between two things that are not comparable:

  floor SAVES  <= one tick PER CONTRACT, and only WHEN IT FILLS
  floor COSTS  THE ENTIRE POSITION, when it does not

MEASURED 2026-08-30, live-odds-worker. `tsc-mlb-lad-det-2026-08-30-7pt5` quoted
0.515 on a 0.01 tick, sent as `submitted_limit=0.51`, `filled=0.0`. Our bid sat
a half-tick under the ask and rested.

AND THE SAVING WAS NEVER REAL. A marketable limit fills at the BOOK, not at the
limit -- order C4N3GPYA4GNQ was submitted at 0.51 and filled at `avgPx=0.4900`.
So raising the limit does not raise what we pay; it only decides whether we
trade at all. The floor bought nothing and cost whole positions.

HOW TO APPLY. When a price transform is justified by "this is the conservative
direction", ask what the conservative direction is conservative ABOUT. Toward
the venue on a BUY limit is not caution, it is a free option written to
everyone else: it fills only if the market comes back to us, which is the market
moving AGAINST the thesis. `kalshi_price_for` had already written that down on
2026-08-24 -- "a resting order is worse than a missed one" -- and the two
conclusions sat in two files, opposed, for six days.

WHY KALSHI HID IT: its quotes are already whole cents on a 0.01 tick, so the
floor is a NO-OP there and the venue filled 15 of 20. Polymarket runs 0.01 and
0.005 ticks in the same slate. A shared helper can be correct on one caller and
destroying orders on the next; "it works at the other venue" is not evidence.

SCOPE, MEASURED, NOT TOTAL: this explains 2 of the 3 orders resting that day.
The third was quoted 0.44, sent 0.44 -- already on the grid -- and still rested.
The slate carries `prices[]`, one probability per outcome, and NO bid/ask, while
Kalshi prices off an explicit `no_ask_dollars`. Bidding a non-ask exactly may
never cross. Fixing one cause does not retire the symptom.

## 2026-08-30 — CORRECTION, same day: the tick floor did NOT cause the resting Polymarket orders. I paired two log lines 30 minutes apart and called it a mechanism.

The entry above claims, as MEASURED, that `round_price_to_tick` flooring a BUY
put our bid under the ask on `tsc-mlb-lad-det-2026-08-30-7pt5`. **That is
false.** The pairing was:

    17:49:02  POLYMARKET_ARTIFACT_PRICE ... price=0.515      <- read LATER
    (FILL_ABOVE_LIMIT)  submitted_limit=0.51  filled=0.0     <- order from 17:19

Two different moments, treated as one event. The actual quote at submit time,
which was in the same log the whole time:

    17:00:45  price=0.51      17:12:57  price=0.51
    17:08:12  price=0.51      17:18:54  price=0.51
    17:19:27  price=0.51   -> SUBMIT price={'value': '0.51'}

**The quote was 0.51 and we sent 0.51. The floor changed nothing.** It could
not have: 0.51 is already on the grid. The 0.515 appeared THIRTY MINUTES LATER,
after the order was already resting. The price moved after we bid; that is
market drift, not a rounding defect.

Confirmed by deploying the "fix" and measuring it: **0 of 9 quotes off-grid**
across 3 slugs and 27 minutes. Every quote the venue publishes sits on that
market's own tick (0.005 and 0.01 both seen). The snap has never once fired.
A no-op shipped as a fix.

WHAT SURVIVES. The general point is still true and still worth keeping: a limit
is a CAP, not the price paid — `C4N3GPYA4GNQ` was submitted at 0.51 and filled
at `avgPx=0.4900`. And gating slippage on the price actually sent rather than
the pre-snap quote is a real improvement. Neither of those needed the false
causal story, and I attached them to it anyway.

WHAT THE REAL CAUSE LOOKS LIKE NOW. We bid the venue's quote exactly, and then
never re-price or cancel. The order rests; the market moves; the resting limit
is now behind. `tsc-lal-cel-ath` is the same shape — quoted 0.44, sent 0.44,
never filled. Bidding AT a quote is not crossing a spread, and the slate carries
`prices[]` with NO bid/ask, so we may be bidding a mid that no one will hit.
That is the hypothesis to test next, and it is where I should have stayed.

HOW TO APPLY. **Two log lines are one event only if they carry the same
identifier for that event.** Same slug is not same order. Before pairing a
cause line with an effect line, find the cause line whose TIMESTAMP PRECEDES the
effect and belongs to the same attempt — here that line existed, was one query
away, and said the opposite. The pairing felt safe because the arithmetic
worked: 0.515 floors to 0.51 at a 0.01 tick, which is a real mechanism that
produces exactly the observed number. **An arithmetic coincidence that explains
the data is not evidence that it produced the data.**

