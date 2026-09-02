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

## Index — 653 rules `[generated]`

> Full index: [`learnings_index.md`](learnings_index.md) — regenerate with
> `py -3 scripts/build_learnings_index.py` after appending. It spans BOTH
> this file and `learnings_evidence.md`, so a rule stays findable after its
> body is compacted out. **FORBIDDEN** = never do this again.
> **EXONERATED** = ruled out, stop re-investigating.

<!-- LEARNINGS-INDEX:END -->

---





### 2026-09-01 — FORBIDDEN: citing `deploy_claim.py`'s `pid` as evidence a claim holder is gone. It records the CLI process's own pid, which exits in ~1s, so EVERY claim reads as dead within seconds of being taken — I broke a live claim on it `[lane mlb-accuracy-assessment, reported by lane open-lanes-cleanup]`

- **What we believed:** the protocol says a claim held by a session that is gone
  may be taken with `--force`. The claim file carries a `pid`, so checking
  whether that process is alive looked like the way to establish "gone" — an
  actual reading rather than an assumption, which is exactly what this repo
  keeps asking for.
- **What was actually true:** `scripts/deploy_claim.py:125` writes
  `"pid": os.getpid()` — **the pid of the short-lived `deploy_claim.py acquire`
  CLI process, not of the owning session.** That process exits about a second
  after writing the file. So the field is dead-on-arrival for every claim ever
  taken, and a liveness check built on it **cannot return anything but "dead"**.
  It is a guard whose unknown case defaults permissive, in the worst possible
  place: it makes `--force` look justified against a perfectly live holder.
- **How we found out:** I forced `refresh-worker` off lane
  `mlb-native-ladders-producer`, citing "pid 22884, verified DEAD via
  `Get-Process`". The holder was live and its claim unexpired (TTL to 16:06Z);
  they told me so, and did not contest the claim. **The proof is on my own
  claim:** I then read `.syndicate/deploy_claims/refresh-worker.json` for the
  claim *I* had taken four minutes earlier and still held —
  `pid 8040` — and `Get-Process -Id 8040` returned **not running**. A live,
  unexpired, actively-held claim reads as dead by the same check I had just
  relied on.
- **The rule going forward:** **never cite the claim's `pid` as evidence of
  anything.** To establish a holder is gone, use signals that describe the
  SESSION rather than the CLI that wrote the file: the claim's `acquired_at_iso`
  against its `ttl_seconds` (an expired claim is genuinely stale), `ListAgents`
  for a live session, or — best — ask the holder, since `SendMessage` reaches
  peers in seconds and a claim exists precisely to make that conversation
  happen. **If the only thing saying "gone" is the pid, you know nothing.**
  Forcing may still be right; it must be argued from the TTL or from silence
  after asking, and recorded as such.
- **Cost:** one live claim broken. Nothing was lost — the holder was not
  mid-deploy, did not contest it, and in fact wanted the deploy my claim was
  for. That is luck, not process: the same reasoning would have killed a deploy
  someone was in the middle of, and the field would have looked just as
  authoritative.

### 2026-09-01 — FORBIDDEN: reading a null or a clean result before establishing that it is READABLE YET. Find the thing that says the signal could have arrived, then read it — four instances in one evening, two false positives and two false negatives `[lanes mlb-accuracy-assessment + wnba-accuracy-assessment]`

- **What we believed:** verification is "deploy, then look at the number". If
  the number looks right the change worked; if it looks wrong it did not. Both
  halves feel like measurement and neither is, because a reading taken before
  the change could possibly have reached the surface says nothing in either
  direction.
- **What was actually true:** in one evening the same defect produced FOUR
  wrong readings across two lanes, in both directions:
  1. **False positive, rolled date.** `/api/portfolio/live` showed no
     `by_venue_family` row below -100% after a P&L fix — but the date had
     rolled, the payload came back dated `2026-08-26`, and the offending order
     `C7AZA3MBEKDD` **was not in it at all**. A clean table was equally
     consistent with "different orders today".
  2. **False negative, pre-deploy tick.** `PLAN_WRITTEN` showed
     `no_model_edge_pct: 1092` and no `market_family_excluded` — stamped
     **03:47:51Z against a 03:52:11Z deploy**. Old code. Read carelessly it
     says "the fix does not work".
  3. **Unreadable null, neighbour not reached.** `WNBA_POSTGAME_PRODUCER` had
     0 matches — but the tick immediately upstream of it in `main()`,
     `BOOK_GRID_TICK`, had also not emitted since the deploy. The worker had
     not reached the dispatch point, so the absence carried no information.
  4. **Never-readable null.** `/api/ops/artifacts/export` returned `count 0`
     for a freshly produced artifact, and it always would have: the worker
     publishes explicitly per path and **allowlisting a path makes it eligible
     to cross, it does not carry it**. No amount of waiting could have changed
     that number.
- **How we found out:** two sessions checking each other. (1) and (2) were
  caught by asking "does this reading post-date the change?" before quoting it.
  (3) was caught by the neighbour technique — find the marker immediately
  upstream of the one you want, and treat your null as unreadable until the
  neighbour fires. (4) was caught by a code comment written by the other lane
  hours earlier, which recorded that **two previous watchers had already burned
  ~35 minutes polling for a change that was structurally impossible**.
- **The rule going forward:** **before reading a null or a clean result, find
  and check the thing that tells you the signal could have arrived.** In order
  of preference: (a) a timestamp on the reading that you compare against the
  deploy/change time — not "recent", the actual comparison; (b) the marker
  immediately upstream of the one you want, so a missing signal is
  distinguishable from an unreached one; (c) proof that a path from producer to
  reader EXISTS at all — for cross-service artifacts that means a publish call,
  not an allowlist entry; and **(d) that the SUBJECT is present in the
  population you are reading** — a post-deploy tick over a slate that no longer
  contains the rows your change acts on is as unreadable as a pre-deploy one.
  **Write the falsifier down before the reading arrives, and write its
  PRECONDITION next to it.** A pre-registered band with an explicit "falsified if" cannot be
  fitted to the result afterwards, and it forces you to name the neighbour.
  **And prefer a gate on the one line only your code can emit** over a
  downstream count that something else could also flip.
- **A FIFTH instance, 04:09Z, which is why (d) is in the rule:** the MLB
  exclusion gate finally got a post-deploy `PLAN_WRITTEN` — check (a) satisfied
  — showing no `market_family_excluded` and `no_model_edge_pct` UP from 1,092 to
  1,260. Read as written, the pre-registered test was falsified. It was not:
  `top_market_per_refusal` named `alternate_totals_corners:690`, a SOCCER
  market, and the board at that hour carried **0 MLB prop rows** (MLB down to 31
  game rows, slate over). **The change had nothing to act on.** The
  pre-registration named a falsifier and did not name a precondition, so a
  reading with no subject in it looked exactly like a failing one.
- **A SIXTH instance, 2026-09-01T12:46Z, and it is a DIFFERENT lesson worth its
  own line: A FALSIFIER MUST TEST THE CLAIM, NOT A SIDE-ASSUMPTION ABOUT
  MECHANISM.** The gate finally became readable (`verify_mlb_prop_exclusion.py`
  READY, 1,876 MLB prop rows) and PASSED: `market_family_excluded: 1860`, top
  market `batter_rbis:379`, i.e. 99.1% of MLB props refused, exactly as
  designed. **But my pre-registered falsifier said "FALSIFIED IF the counter
  appears and `no_model_edge_pct` does not move" — and it did not move
  (1,092 -> 1,277). By my own written test, a working change fails.** The
  falsifier rested on an assumption that MLB props are where the missing model
  edge sits; they are not — `no_model_edge_pct`'s top market is
  `alternate_totals_corners`, a SOCCER market. Pre-registering is necessary and
  not sufficient: a test aimed at a mechanism you have assumed rather than at
  the claim you are making will condemn a change that does exactly what it says.
- **Cost:** ~35 minutes of watcher time on the WNBA side before the code
  comment stopped a third watcher being armed; two wrong conclusions drafted
  and withdrawn on the MLB side before either was quoted; and one WNBA
  web-facing accuracy path that would have stayed at zero forever while its
  producer reported `status: ok` every hour. Nothing reached a user, because
  both sessions checked before quoting — which is the only reason this is a
  learnings entry rather than a postmortem.

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

## Entries before 2026-08-20 — moved to `learnings_archive.md` `[2026-09-01]`

> **149 entries (70,075 chars) moved out of this file, VERBATIM and in full.**
> Nothing was deleted, summarised, or reworded.
>
> **They are still indexed.** `build_learnings_index.py` now spans
> `learnings.md`, `learnings_evidence.md` AND `learnings_archive.md`, so every
> archived rule remains findable in [`learnings_index.md`](learnings_index.md).
> A rule you cannot find is a rule you will break again.
>
> **THE COST, STATED: the session-start digest greps THIS FILE only, so its
> standing-rule count drops 160 -> 125.** Those 35 rules are older than
> 2026-08-20 and are one file away, not gone — but a session that greps only
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

## 2026-08-23 — FORBIDDEN: claiming a feature works when no test runs the path that CALLS it

- **The rule going forward:** a feature whose failure mode is `except` + a log line MUST have a test that executes the real call path end to end. Testing the callee directly proves the callee works and says NOTHING about whether anything invokes it. And verify the test by reintroducing the bug: a green test that has never been seen red is a claim, not evidence.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-23 — FORBIDDEN: a module may not hold its own list of market names. It WILL drift from `market_keys`, silently

- **The rule going forward:** market names have exactly one authority, `market_keys.canonical_market_key` (`#224`). Canonicalise on lookup wherever a sport is in hand. Where the function takes no sport and cannot, hold BOTH spellings **and** a test that derives one set from the other — a private list with no such test is a silent time bomb, not a mapping.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-23 — FORBIDDEN: never read `settled_at` on an order as "the bet was decided"

- **The rule going forward:** `settled_at` is the ORDER's clock — `complete_order` stamps it when the order reaches a terminal state at the VENUE, seconds after a paper fill and hours before the game ends. The WAGER's clock is `graded_at`, written by `paper_settlement`. Two clocks, two fields, never one.
- *(evidence in `learnings_evidence.md`)*

## Superseded on 2026-08-15 — the two `same_book_n` entries

Both were merged into **"never read a joiner zero as a fact about the world"**
above; full original text is in `learnings_evidence.md`. They reappeared here
once after being removed — a stale-read write on this shared file resurrected
them alongside their own replacement. If they show up a third time, delete
them again rather than assuming the merge was reverted: the merged rule and
the evidence file are the source of truth.

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

## 2026-08-20 — An artifact can OUTGROW the publish ceiling, and the failure is silent

- **Why it cost so much to find: every other link was CORRECT.** The worker really did rebuild the ladder (`generatedAt 19:54:41 CT`). `is_stale()` really did correctly answer `fresh` — the content genuinely was newer than the odds and the sims. There was no error, no failing test, and nothing wrong anywhere near the ladder code. I chased five successive causes, each hidden behind the last, and three of my intermediate diagnoses were wrong.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-20 — OVERTURNED: "the slate date rolled, the gate expired". It had not.

- **How to apply:** any artifact keyed by SLATE date — ladders, sims, status documents, rebuild gates — is on Central time. Before concluding a document is missing, stale, or expired, convert: `slate_date = (utc - 5h).date()`. A watcher keyed on the wrong date does not return "nothing happened", it returns a CONFIDENT WRONG ANSWER, because the document it is polling really does exist and really is old.
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

- The rule going forward: **a code-default change to a file whose whole design is "env var wins over default" is not verified by the diff or the test suite — it is verified by reading the live service's actual resolved values.** For Syndicate specifically: `mcp__Render__list_logs` on the relevant service, filtered to the module's own log line, is the read; there is no env-var-listing tool, so log lines that print the resolved config (this file's `LIMITS`/`EXECUTION` lines) are the only way to see what a service is actually running without one.
- *(evidence in `learnings_evidence.md`)*

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

- **A number you computed from another stored number is not evidence about the world. Dividing it back out recovers your own input, and it will look like a reading.**
- *(evidence in `learnings_evidence.md`)*

## 2026-08-26 — FORBIDDEN: concluding a VENUE must act because its error names your account

- **`user_not_found: <uuid>` from a venue is a statement about a REQUEST, not about your account's existence.** I read it as "the exchange has no record of us here, so the venue must enable us", shipped that as the remedy, and it went LIVE IN A PRODUCTION ERROR STRING telling any reader to contact Kalshi support:
- *(evidence in `learnings_evidence.md`)*

## 2026-08-26 — An empty log query is not evidence of absence until the query shape is known to match

- **OVERTURNED:** that a null result from the Render log `text` filter means the line is not there.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-26 — A before/after comparison where both sides are the same tree always agrees

- **Use a detached worktree at the parent commit** (`git worktree add --detach <path> <sha>~1`), which cannot silently be the same tree. Done correctly later the same session for `test_it_cannot_downgrade_a_started_match`.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-26 — One shared method, two callers wanting different answers: check the OTHER caller

- **Before changing a shared resolver, enumerate its callers and state what each one needs.** The fix in both cases was to make the difference EXPLICIT (`include_upcoming`; the two-resolver rule in the invariant), not to pick one caller's answer and hope.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-26 — "Done" before the sweep returns is a claim about the future

- *(the heading states the rule; full working in `learnings_evidence.md`)*
- *(evidence in `learnings_evidence.md`)*

## 2026-08-26 — `-k` chosen by TOPIC misses the files you edited

- **Choose `-k` from the FILES TOUCHED, not the topic being worked on.**
- *(evidence in `learnings_evidence.md`)*

## 2026-08-26 — An estimated window is one sample until you measure the spans

- **447s** and the build was healthy throughout.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-26 — FORBIDDEN: TWO HOSTS ARE NOT ONE VENDOR, and "X can reach ESPN" is not a fact about X

- **A success against one hostname says nothing about another hostname, even when both belong to the same provider and serve the same path.**
- *(evidence in `learnings_evidence.md`)*

## 2026-08-26 — FORBIDDEN: assuming an artifact "published to production" is where its CONSUMER reads

- **`POST /api/ops/artifacts/publish` writes `data_root() / relative_path` on WEB'S FILESYSTEM.** `bet_status_wnba` reads the same relative path through `read_text_file`, i.e. the KEYVALUE store, on REFRESH-WORKER. Same string, two stores, two services.
- *(evidence in `learnings_evidence.md`)*

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
- *(evidence in `learnings_evidence.md`)*

## 2026-08-23 — RULE: an empty tmp dir for `SYNDICATE_NFL_SOURCE_ROOT` can still resolve to the REAL checkout, and a test can write into it

- **The rule going forward.** Before verifying a consumer against an artifact, **enumerate that artifact's PRODUCERS** — `git grep` the write path, not just the read path — and carry a fixture from EACH one into the test. One producer is an assumption, not a finding; two producers that disagree on shape is a thing this repo already does. And the shapes must be READ OFF PRODUCTION over a window, not inferred from the writer that happens to be documented: a single sample cannot distinguish "one shape" from "the shape that was current when I looked". Corollary for the consumer itself: `#413`'s "`{}` means ALL, not SOME" belongs per ROW, not per FILE — a row that cannot answer must return None rather than a hollow state, because a non-None empty answer suppresses the fallback that would have been correct.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-26 — RULE: a measurement can be REAL and still describe the WRONG POPULATION. State the denominator before you generalise a rate.

- **Two instances the same evening, in two different sessions, in opposite directions — which is why this is a rule and not an anecdote.**
- *(evidence in `learnings_evidence.md`)*

## 2026-08-26 — FORBIDDEN: reporting a test as failing on `main` from a session worktree, when its fixture is DERIVED from `data/`. And a stash-and-rerun does NOT isolate it.

- **`session_worktree.py open` excludes `data/` by design** (34,690 of 37,745 tracked files; it is a lossy mirror and never evidence about production). Any test whose fixture is BUILT FROM those artifacts therefore fails in a session worktree and **looks exactly like a real regression on `main`**.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-28 — FORBIDDEN: treating a refuted MECHANISM as a refuted OBSERVATION. I disproved my own theory of how a wrong-side fill happened, and used that to dismiss the fill.

- **THIS ENTRY REPLACES THE ONE THAT STOOD HERE FOR SIX HOURS, WHICH WAS WRONG IN ITS CONCLUSION AND WOULD HAVE TAUGHT THE NEXT SESSION TO DISMISS A REAL ONE.** The superseded version was titled *"FORBIDDEN: escalating a wrong-side money alarm on a property the code already handles"* and concluded the alarm was false. It was not. Left in the history; do not restore it.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-27 — FORBIDDEN: pushing past a ledger checker's warning because its output "looks like the usual noise". A WARNING THAT IS USUALLY WRONG GETS TRAINED OUT — and two sessions proved it independently on the same night

- **The rule going forward.** **A checker that emits known-false warnings beside true ones is not a checker, it is noise with an exit code.** Two things follow. (1) When a checker fires, READ ITS FULL OUTPUT before deciding it is the usual thing — "I recognise this warning" is a memory of a DIFFERENT run. (2) Separate the classes at the point that ACTS on the finding: a duplicate declaration should BLOCK, while historical unmatched ids stay advisory. The check that cannot be trained out is the one that only fires when something is wrong.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-27 — RULE: a deploy claim serialises SESSIONS. It does not reserve a service against a HUMAN, and an assistant cannot lift the guard from inside a command.

- **MEASURED 2026-08-26.** Lane `ncaaf-opener-regions-props` held the `refresh-worker` and `live-odds-worker` claims (acquired 22:57:41Z, TTL 2700s, so live until 23:42:41Z). At **23:26:02Z** — **16.6 minutes inside the window** — both services were deployed to `23f065d4` by the user from their own terminal. Nothing refused it, because `.claude/hooks/deploy-guard.py` only intercepts an ASSISTANT's Bash calls.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-27 — FORBIDDEN: running `deploy_claim.py` from a session worktree. The claim file is PER-TREE, so nobody else can see it.

- **MEASURED 2026-08-27T01:0xZ.** Two `web` claims existed at once, in two files, neither aware of the other:
- *(evidence in `learnings_evidence.md`)*

## 2026-08-27 — MEASURED NEGATIVE: the NCAAF advanced-data payload does not close the gap to market

- **Do not re-litigate this without new evidence.** The re-fit ran; the answer is no. `scripts/refit_ncaaf_smartsim2_payload.py --season 2025 --sims 60`, 714 games, both arms sharing seeds, ~60 min of compute:
- *(evidence in `learnings_evidence.md`)*

## 2026-08-27 — NCAAF TOTALS ARE NOT OVER-DISPERSED. The deficit is ONE CONSTANT BIAS, and the residual spread already matches the market

- **Rule: before attacking a model's DISPERSION, decompose its error into BIAS and SPREAD. They demand opposite fixes and only one of them was ever wrong here.** The model's residual SD is statistically indistinguishable from the market's — its errors are ALREADY as tight. The entire totals deficit is a single systematic over-prediction of 5.2 points.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-27 — NCAAF drive structure is an ENGINE ACCOUNTING BUG, not a calibration gap. The sim's own numbers do not multiply out

- **Rule: before tuning a model to a target, check the model's own metrics are INTERNALLY CONSISTENT. If they do not multiply out, the defect is accounting, not calibration, and no parameter will reach it.** Truth multiplies: 5.77 x 7.36 = 42.5. The sim does not: 7.246 x 7.413 = 53.7 against a credited 43.1 yards/drive -- a ~10.5 yard/drive gap between gross play gains and net drive yardage that real football does not have. Divide the sim's OWN numbers and you get 43.14 / 7.413 = **5.82 effective plays/drive, essentially truth's 5.77**. The football is right; the play COUNT is inflated ~25%.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-27 — A GUARD THAT ASSERTS THE CALL, NOT THE RESULT, IS TRUE OF CODE THAT DOES NOTHING

- **Rule: a guard must assert the OUTCOME at the place that CONSUMES it, and must be seen to FAIL before it is trusted.** "The builder calls the helper" was true of a payload nothing read. "Jinja parses" was true of markup that collapsed a card in a browser. Both are statements about the thing built, not about the thing that reads it.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-27 — MEASURE THE OUTCOME YOU PROMISED, NOT THE CHANGE YOU MADE

- **Rule: state the outcome as a NUMBER before changing anything, then measure that number.** "Prose blocks: 0" is a fact about my edit. "Card height 181px vs 435px, uniform across 51" is the thing the user asked for.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-27 — FORBIDDEN: deferring work around a ledger BLOCKER without re-measuring it. A blocker is a measurement and it expires.

- **It was true on 2026-08-18 and false from 2026-08-20**, when `d7dbdbd2` ("allowlist: make the live-gameline ledger readable off-worker (#440)") added both patterns. Content-verified 2026-08-27 on all three DEPLOYED SHAs — web `e3568422`, refresh-worker `ad3f116c`, live-odds-worker `34b4d4b4`.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-27 — FORBIDDEN: trusting a test whose FIXTURE cannot violate the property it asserts. It is not weak coverage; it is zero coverage that reads as strong.

- **Why it could never fail:** every record in its fixture carries BOTH `model_home_win_prob` and `market_fair_prob`. The populations diverge only when a record has a model probability and NO market price — a row the fixture does not contain. So `assert model.n == market.n == 2` was re-measuring the fixture, not the code. Any implementation, including the broken one, passes it.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-27 — FORBIDDEN: reading `pid` in a deploy claim as evidence the holder is alive

- *(the heading states the rule; full working in `learnings_evidence.md`)*
- *(evidence in `learnings_evidence.md`)*

## 2026-08-27 — `Path(__file__).parents[1]` MAKES THE PRIMARY TREE THE RENDEZVOUS, AND A WORKTREE INVISIBLE

- **Run every deploy-lock command from the PRIMARY tree, and write the per-session lane marker there too.** Code edits stay in the worktree; the locks are shared state and must live where the other sessions read them.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-27 — A COMMENTED-OUT PATH IS STILL A CLAIM; AND THE DEPLOY GUARD MATCHES LEDGER PROSE

- **A false positive here is correct behaviour** — the fix is to reword the ledger, never to reach for a route the guard does not recognise.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-27 — A CLAIM HOLDER IS NOT A DEPLOY AUTHOR. The API cannot tell you who fired it.

- **Overturned by `ncaaf-opener-regions-props`, self-caught.** They thanked me for deploying `600a753a` to refresh-worker. I had not — my deploys that day were all live-odds-worker.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-27 — FORBIDDEN: measuring a dirty SHARED tree against `HEAD`. In a stale checkout `HEAD` is the thing that is wrong, and every diff built on it lies in the safe-looking direction.

- **+77/-1225** on `learnings.md`. Alarming, so I checked the real baseline. Against `origin/main` the same files read **+159/-12,933** and **+2,665/-2,271**: the primary tree was **791 commits behind**, so its ledger copies were missing everything landed since. Committing them — even path-scoped, even having audited the diff — would have deleted **~17,000 lines** of other sessions' work.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-27 — RE-FITTING A MODEL CAN BE THE WRONG ANSWER. Measure the do-nothing arm.

- **Rule: include the DO-NOTHING arm in the grid, and let it win if it wins.** NFL was already at its best; the fix plus a careful re-fit made it worse. Had the grid only compared "candidate ON" against "candidate OFF", NFL's candidate would have looked like a 3.24-point win and shipped a regression.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-27 — PROMOTING AN ARTIFACT IS A CHAIN. THREE LINKS FAILED SILENTLY.

- **Rule: test the CHAIN — write, read back, and confirm the consumer holds the new value — never the individual link.** Each of these passes an "is the field there" check. Only a round-trip catches (2), and only reading the staging output catches (3).
- *(evidence in `learnings_evidence.md`)*

## 2026-08-27 — A CARRIED-FORWARD FACT DECAYS EACH TIME IT IS RESTATED WITHOUT RE-READING THE SOURCE. And a clean kill census proves nothing until you prove the feature was RUNNING in that window.

- **THE SECOND HALF, which is the part most likely to be skipped.** "Zero kills in 10d13h" is worthless on its own — it is equally consistent with the feature being switched off. The reading only counts because the ledger was PROVEN to be running in that same window: 20 ledger files / 47.7 MB with fresh mtimes, and `MLB_LIVE_GAMELINE_LEDGER_ENABLED` absent (= enabled). Pair every null with proof the thing could have fired.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-27 — A GREEN TEST SUITE OVER A FILE THAT CANNOT BOOT `[lane venue-quote-line-join]`

- **FORBIDDEN: appending a definition below `if __name__ == "__main__":` and treating a passing unit suite as evidence the file still runs.**
- *(evidence in `learnings_evidence.md`)*

## 2026-08-27 — CADENCE LIVES IN THE CALLER, NOT THE INTERVAL CONSTANT `[lane venue-quote-line-join]`

- **FORBIDDEN: reporting an interval env var as a cadence lever without reading its CALL SITE.** I told the user twice that raising venue cadence was "pure env, no code". Both times wrong, both caught only by reading callers:
- *(evidence in `learnings_evidence.md`)*

## 2026-08-27 — A KEY MUST NAME EVERY PARTY TO THE BET `[lane venue-quote-line-join]`

- **FORBIDDEN: a join key for a player prop that omits the player, or for a total that omits the game.** Both were live and both look identical to a working join from every counter.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-27 — A BREAKDOWN THAT DOES NOT RECONCILE IS NOT EVIDENCE `[lane venue-quote-line-join]`

- *(evidence in `learnings_evidence.md`)*

## 2026-08-27 — FORBIDDEN: allowlisting a KEYVALUE-backed path in `HOT_ARTIFACT_PATTERNS` and calling it readable. The guard will pass and the data will not arrive.

- **It would have been inert, and inert in the worst way — it looks like a fix, it passes review, and it changes a 403 into an empty result.**
- *(evidence in `learnings_evidence.md`)*

## 2026-08-27 — FORBIDDEN: validating a CONVERTED value while STORING the raw one. The guard clears a number that is not the number anything uses.

- **$23.25 to $368.97** — against a `max_day_dollars_polymarket` of **100.01**. Real spend was ~$20.71. No money moved; the BOOKKEEPING was 15.9x wrong and the cap enforces on it.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-27 FORBIDDEN: an instrument built out of the thing it measures, or out of a symptom the slate can retire — FOUR instances in one session, every one reading HEALTHY

- **The rule going forward.** Derive the instrument from a source the defect CANNOT touch, and state that source. Concretely, all three fixes ended up joining on the slug taken from `group.key` and on `chip.league_display` — fields no code path under test writes. **And run the control on the SAME payload, at the same instant, every time:** a fix verified only against post-deploy data is verified against a slate that may have retired the test case. This is the 2026-08-20 census rule (`A CENSUS THAT CANNOT READ UNHEALTHY IS NOT A VERIFICATION`) generalised from "the slate moved" to "the instrument was never able".
- *(evidence in `learnings_evidence.md`)*

## 2026-08-27 — A SINGLE OBSERVATION READ AS A BOUND `[lane venue-quote-line-join]`

- **FORBIDDEN: concluding "supply-limited" from one reading where a quantity sat below its cap.** I saw mlb take 1,512 slots against a cap of 1,550, concluded its Kalshi listings were the constraint, and wrote it into `deploys.md` as the finding. mlb went **794 -> 1,741 across the same evening** — its available markets GREW as its slate approached first pitch. 1,512 was a moment, not a ceiling.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-27 — A CONTROL THAT IS BROKEN IN THE SAME WAY AS THE TREATMENT DISTINGUISHES NOTHING. I ran one and reported the result as positive.

- **THE METHOD ERROR IS THE POINT, NOT THE STALE RULE.** I "verified" by stashing my diff and re-running. **Stashing does not restore `data/`.** Both arms of the comparison were missing the same thing, so the experiment could only ever return "same either way". That proved the failures were not caused by MY DIFF; it could not prove they were REAL. I collapsed two different claims and reported the weaker result as the stronger one.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-27 — I CHECKED ANCESTRY AND CALLED IT CAUSATION. The fix's own log line said the path never ran.

- **The trim's own line, at the moment of the recovery, reads:**
- *(evidence in `learnings_evidence.md`)*

## 2026-08-27 — A WATCHER IS AN INSTRUMENT AND IT LIES IN FOUR SPECIFIC WAYS

- **A failed edit followed by a successful run of old code is indistinguishable from a successful re-arm.**
- *(evidence in `learnings_evidence.md`)*

## 2026-08-27 FORBIDDEN: calling a fix verified when the READING came from a different surface than the one that was broken

- **The rule:** when a value crosses more than one hop to reach the surface that was reported broken, a correct reading at hop 1 is not evidence about hop 2. Verify at the surface the complaint came from. **A byte-identical response across a deploy is a positive signal that nothing changed** — cheap, and it is what caught this. Fixed in `d281995b`; one list now feeds both, so payload and page cannot drift.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-27 FORBIDDEN: inferring that a scheduled job SUCCEEDS from an age that sits at one interval

- **Generalises to:** any liveness signal emitted BEFORE the work it is taken to vouch for. Ask what the signal is stamped by, not what it is near.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-27 A lane can be CLOSED while a session keeps working under its name

- **Not proposing a guard** — the claim's job is mutual exclusion and it did that. The point is narrower: **a lane name in a claim is not evidence the lane is open**, so "who holds this" can point at a closed lane indefinitely. When work continues past a close, open a new lane or reopen the old one before touching production.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-27 A survey keyed by BARE FUNCTION NAME collapses same-named functions across sports

- **Resolve by IMPORT, not by name** in a repo with per-sport parallel modules. And when a static result says "no problems anywhere", treat that as a suspected broken query before treating it as a finding.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-27 — FORBIDDEN: fitting a model to a total when you can COUNT the operation

- **The rule:** if the thing you are optimising is made of discrete operations — syscalls, queries, requests — **count them**. Do not infer their cost by regressing the total against plausible predictors.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-27 — FORBIDDEN: a verification criterion that can only be met by the failure it is watching for

- **The rule:** before adopting a criterion, ask what it reads on a HEALTHY instance that was never going to fail. If the answer is "the same as on a fixed one", it discriminates nothing.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-28 — A GAP BETWEEN TWO LOG LINES IS NOT A COST. I measured one, believed it, and was wrong by 30x.

- **Spanned directly, it is `pull_hot_artifacts` = 1.15s.** The 37 seconds was everything happening on a shared worker between two prints — other threads, the memory watchdog, the sim tick, GC — not the work I attributed it to.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-28 FORBIDDEN: reading a "not yet running" list as proof something IS running

- **The rule:** poll the PREDICATE, never a status field that merely mentions your SHA. For a deploy that means the changed behaviour appearing in the served response, or a log line that exists ONLY in the new code (`ORDERS_ENVELOPE` was built for exactly this and worked).
- *(evidence in `learnings_evidence.md`)*

## 2026-08-28 FORBIDDEN: a shared rule reimplemented as "the half I needed"

- *(evidence in `learnings_evidence.md`)*

## 2026-08-28 FORBIDDEN: grading an AMBIGUOUS zero as a definite outcome

- **The rule:** a value that two different states both produce is not evidence for either. Refuse with a NAMED reason and leave the row for a later pass. And when a wrong verdict can be written permanently, the repair must carry a discriminator that makes it TERMINATE — `held_side` here, without which the repair would clear a correct grade every tick forever.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-28 An absent log line is only evidence once you know the line is EMITTED

- **Check the instrument can fire before trusting what it says.** An unfiltered query returning *something* is the cheap version of that check.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-28 FORBIDDEN: reading a job's TIMESTAMP as evidence it ran, on a machine that sleeps

- **Compounding it:** the sibling task `live-gameline-fixes-first-real-reading` had a hardcoded freshness window ("a row `captured_at` between 04:33Z and 04:45Z") and was instructed, on a miss, to declare *"the recurring task is not firing on its cron, which is EXACTLY the failure that lost six nights."* Under displacement that window can never be met, so it was primed to raise a false alarm indistinguishable from a real outage — and the plausible response to that alarm is re-enabling things that were never off. 6 of 10 nights (08-18..08-27) fell inside a standby span.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-28 A lane-guard claim can be held by PROSE, and "TRANSFERRED" releases nothing

- **The rule:** a release is only real if the guard parses it. Verify by DRIVING the hook (`echo '{"tool_name":"Edit","tool_input":{"file_path":"..."}}' | python .claude/hooks/lane-guard.py`), never by reading the ledger and believing the prose. Note the guard cannot express a per-branch claim: releasing for one concern releases the file for everyone, so say so where the next reader will see it.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-28 — FORBIDDEN: building a fix for a hypothesis the REFUSAL NAME has already ruled out `[lane venue-join-refusal-visibility]`

- **What we believed:** soccer was absent from Polymarket execution because whole competitions never entered the `soccer` bucket — `mls` was unprovable, so its 30 h2h markets sat under a key no board row looks up. Measured and true: 0 of 9 MLS fixtures resolve both clubs through the flat alias map.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-28 — FORBIDDEN: reading ~0.5 as a weak signal from a comparison never shown to DISCRIMINATE `[lane venue-join-refusal-visibility]`

- **What we believed:** the Polymarket spread sign test was under-powered. Ten production runs returned `rate` 0.44-0.60 at n=9..22 against `min_sample=30`, and the verdict said `UNDECIDED: n < min_sample` — which reads as "collect more".
- *(evidence in `learnings_evidence.md`)*

## 2026-08-28 — FORBIDDEN: reading `lastRunAt` as evidence a scheduled job RAN. It records DISPATCH, and on this machine the two were nine hours apart.

- **How to tell it apart from a task bug, cheaply:** other concurrent sessions will show a gap ending at the SAME INSTANT. Three did — 10.22h, 9.99h, 9.78h, all resuming inside 72 seconds, from different start times. A per-task bug cannot do that. Confirm with `Get-WinEvent` System log, Kernel-Power 506/507.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-28 — FORBIDDEN: baselining a test in a fresh worktree when the test reads state the worktree does not share. It is not a baseline, it is a different experiment.

- **A git worktree does not carry the primary tree's `data/` mirror, and that test reads the real data root** — visible in its own error output (`...\Syndicate\data\wnba_source\...`), which I had already been shown and did not read. The worktree was a different environment, so the comparison was meaningless.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-28 — FORBIDDEN: concluding a lane claim is free because the roster says its session is gone. `get_session` said "not found" while the session was live.

- **What the code said, and it had said it for months.** `bet_status_wnba` refused every WNBA spread, moneyline and total. Not by omission — by an argued comment:
- *(evidence in `learnings_evidence.md`)*

## 2026-08-28 — FORBIDDEN: instrumenting a function without first proving it is ON the path you are measuring. I did it, and the counter read zero.

- **Every one of those facts is true, and the theory is worthless, because `build_soccer_market_board` IS NOT ON THE OVERVIEW PATH.** `soccer/cards.py` — what `_build_sport_overview` actually calls — never imports `market_board`. Its importers are the `/soccer` blueprint, `layer1_board`, `live_refresh_loop`. I shipped a counter into it and production emitted ZERO lines.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-28 — FORBIDDEN: treating a "this API does not exist" finding as a fact about the VENUE when it was written from a network that could not reach the venue. It is a fact about the NETWORK.

- **The decision ("do not build") was right in both versions. The REASONS were false, and a false reason is worse than no reason** — it reads as a closed question. Compounding: the same finding's `probe()` named "HTML that mentions a live REST path" as its unblock signal; that would FIRE TODAY and be wrong, since the page advertises a REST path no host serves.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-28 — A lane disclaimer marker governs its OWN LINE ONLY. Three of five "contested" files were deference that PARSED as ownership.

- **The form that works** — marker first, path after, on ONE line:
- *(evidence in `learnings_evidence.md`)*

## 2026-08-28 — AMENDS the `createdAt`/`finishedAt` rule: the DEPLOY RECORD and the PROCESS are not the same instant `[lane venue-join-refusal-visibility]`

- **HONESTY ABOUT SCOPE, because overstating this would make it a worse rule:** in the incident that produced it, `finishedAt` WOULD have been sufficient. A peer read a `POLYMARKET_ORIENTATION` line from 20:19:16 as post-deploy — before `finishedAt` AND before `BOOTED` — because they INFERRED "~20:18Z" instead of reading the field at all. The actual error was not consulting the record; the 30-second window is a hazard I found while checking, not the one that bit.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-28 — FORBIDDEN: keying a venue join on the fixture without keying it on the PORTION of the fixture

- **Measured, real money: five orders, $7.08.** `kalshi_board_join._match_key` and `_row_key` were five-tuples — game, market, player, line, side — with no `segment`. A board row for "under 2.5 runs, first 3 innings" therefore matched Kalshi's FULL-GAME `KXMLBTOTAL` on every field the key contained, and nothing downstream checked that the contract settles on a different portion of the game.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-28 — FORBIDDEN: closing on the venue that was REPORTED when the join it mirrors has the same key

- **four more bad orders of the same class, the same day.** Nine distinct wrong orders across both venues, not five. Nothing pointed at Polymarket; the only reason it surfaced is that the audit was repeated rather than concluded.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-28 — FORBIDDEN: sizing a fix before measuring the component's SHARE of the whole. I did it twice in one day on the same subsystem.

- **Instance 1.** I found soccer's cards-context TTL (600s) was finer than the board build period (680-874s), fixed it, measured `games()` 42.34s -> 2.76s and recorded a verified 15x win. The sport bracket was 163-382s. The component I fixed was ~3s of it. I optimised a real defect that could not matter.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-28 — FORBIDDEN: judging a change by the metric I chose instead of the metric the USER SEES. Mine read "bought nothing"; the board read 4h24m stale.

- **THE RULE:** when a change alters scheduling, priority or cadence, check the USER-FACING freshness/quality signal, not only the internal counter you reasoned about. "Bought nothing" is a conclusion about MY metric. The question is always "what does the surface show now".
- *(evidence in `learnings_evidence.md`)*

## 2026-08-28 — Pre-registering a confound does not help if you get its SIGN wrong

- *(the heading states the rule; full working in `learnings_evidence.md`)*
- *(evidence in `learnings_evidence.md`)*

## 2026-08-28 — FORBIDDEN: reaching for the next knob after a tuning change fails. Three attempts, each refuted by the next reading, when the second should have said "structural".

- **THE SIGNAL I IGNORED IS AT STEP 2.** A change that moves the metric the WRONG WAY is not a dosage problem, it is evidence the model is wrong. I read it as "not enough" and reached for a second knob. The cause was structural the whole time: today is re-queued every loop iteration UNTHROTTLED while futures are throttled, and with 11-15 minute builds today wins every slot. Eligibility was never the constraint; slot allocation was.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-29 — FORBIDDEN: naming a cause from a mechanism you can see without measuring the one you cannot

- **Why it survived three failed fixes:** each failure was read as "not enough of the right thing" rather than "the wrong thing". The `=600` result moved `08-29` the WRONG way, which is a refutation of the model, and I took it as a dosage problem. The rule written that day (`stop tuning when the observable moves the wrong way`) fired correctly and I still did not re-examine the CAUSE, only the knob.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-29 — FORBIDDEN: carrying a component's SHARE across regimes when the regime is what sets it

- **14%, not 95%.** A 40% cut of 14% is ~6%, which is below the noise of the thing I promised to move.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-29 — FORBIDDEN: reading a conditional log's silence as absence of the EVENT, when it is really absence of one SPECIAL CASE of the event

- **Both halves of that were wrong, and a forced-collision test found it in minutes.** `counts["concurrent"]` increments only when a row **already in our baseline** has a different fingerprint now (`execution_ledger.py:443`). An intruder that only APPENDS rows never trips it. So:
- *(evidence in `learnings_evidence.md`)*

## 2026-08-29 — FORBIDDEN: breaking a lock before checking whether the thing it guards has already happened

- **The ordering error, stated precisely:** I checked "is anyone deploying?" (`render_events.py --since`) at 15:46, saw none, and then forced at 15:52 on the strength of that. The deploy landed at 15:52:29. A null result is scoped to the window it covered — 15:30-15:46Z — and I carried it forward as a standing fact across the six minutes that actually mattered. This is the same shape as `absence_in_a_window_is_not_absence`, now with a destructive action attached instead of a wrong opinion.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-29 FORBIDDEN: letting a shipped "cannot be tested until X" caveat stand without putting the test on X's date

- **An honest caveat is not a mitigation. It is a defect with a date on it**, and the date arrives when nobody is looking at that surface.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-29 FORBIDDEN: reading `check_lane_invariants` PASSING as proof that lane claims are sane

- **The rule going forward:** **enabling dead code is a performance change, not only a correctness one.** Before shipping a fix that makes an unreachable path reachable, read what the newly-reachable code CALLS and measure it on the path that will now call it. "It returns the right answer" is not a deploy verification for a change that alters *how often* something runs.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-29 — FORBIDDEN: trusting a profiler's ANSWER without validating its SCOPE against the metric you care about

- **The instrument does not know what you are trying to explain.** A profiler tells you where time went INSIDE ITS BRACKET, with total authority and no opinion about whether that bracket is the thing you care about. That check is one subtraction: compare the profile's `elapsed_s` against the enclosing measurement. 10.95 vs 452.97 was visible in logs I had already pulled, and I did not do it until the second profile forced the question.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-29 — FORBIDDEN: windowing a verification watcher on wall-clock time instead of on the boot it is verifying

- **The rule going forward:** when two endpoints display "the same" joined field, find out WHERE each computes it before treating one reading as evidence for the other. A shared function is not a shared execution site, and on this platform the web/worker split makes that difference routine rather than exotic.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-29 — a diagnostic that TRUNCATES will be read as evidence. Twice.

- **RULE: a bounded, sorted sample is not a rate and not an attribution.** Before drawing a conclusion from a truncated list, ask what a NULL result would look like -- here, the same list under an unrelated key, which was visible the whole time. The `cfb` alias was real, but it was settled by a NAMED FIXTURE on both sides (`tsc-cfb-sacst-emich` = the exact board row), not by the list.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-29 — FORBIDDEN: mapping an outcome polarity that the venue has not stated

- **MLB spreads are still refusing for the same reason and must stay that way** until a sample settles them: outcomes are `+1.50`/`-1.50`, both observed samples carry `pos-1pt5` and differ only in the side wanted, so they cannot establish whose perspective the venue states the spread from.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-29 — ancestry is a DEPLOY-TIME MEASUREMENT, never a claim

- **The rule going forward:** when a surface serves an artifact, the ONLY input that licenses a verdict about a code change is the artifact's own build stamp crossing the deploy time. Elapsed time is a fact about you, not about the system. Find the build stamp BEFORE arming a watcher — `written_at`, `generated_at`, `published_at` — and gate on it. If a surface has no such stamp, that absence is the first thing to fix, not to work around.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-29 — FORBIDDEN: calling a placeholder threshold "conservative" without checking it against the real one. A threshold above break-even everywhere is a DISABLED FEATURE wearing safety language. `[lane live-venue-order-placement]`

- **What we believed:** `kalshi_polymarket_arb.DEFAULT_FEE_BUFFER = 0.04` was a safe stand-in. Its own docstring says so at length and honestly — "a conservative placeholder, not either venue's real fee schedule", "only `edge_after_buffer` should be read as an actionable signal". Every word of that is true and it still produced the wrong outcome.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-29 — FORBIDDEN: reading `count: 0` from an artifact export as "the artifact is unreachable". It is a fact about what the READER scans. I had this rule on file and walked into it anyway. `[lane live-venue-order-placement]`

- **What we believed:** `/api/ops/artifacts/export?pattern=*polymarket*` returning `count: 0` meant the Polymarket slate was not reachable from web, so any cross-venue measurement needed a worker-side probe or a publishing change first. I put that in `state.md` and built a recommendation on it.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-29 — FORBIDDEN: judging whether `main` is green from a session worktree OR the primary tree. Neither is a control, and they lie in OPPOSITE directions

- **What we believed:** that running a test file in my own worktree told me whether the branch was healthy. I reported to the user that a deploy carried "9 red tests, 1 of them a new regression," named the regression, identified which lane owned it, and messaged that lane about it.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-29 — a null from an instrument you have not calibrated is not evidence. RUN THE CONTROL

- **What we believed:** that `venue_balance_history.json` being absent from `/api/ops/keyvalue/usage?top_keys=100` and from `sweep-preview` meant the new write was not happening.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-29 — FORBIDDEN: gating on a status string you did not read from the function that emits it. The whole conversion shipped INERT and every test was green. `[lane live-venue-order-placement]`

- **What we believed:** `#603`'s Kalshi half was done. The adapter resolved a ticker's club blob through `match_event_blob`, took the matched fixture, and keyed the quote to it. Code present, suite green, downstream green.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-29 — FORBIDDEN: verifying a DELETION by grepping for the deleted string, without first proving the container renders

- **What we believed:** that grepping the served `/portfolio` HTML for the two sentences I had just removed, and finding them ABSENT, confirmed the edit was live. I reported it that way, with a tidy `ABSENT ok` next to each.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-30 — FORBIDDEN: fixing the caller whose NAME matches what you are looking for, without checking which caller actually runs. `#603` shipped inert twice for this. `[lane live-venue-order-placement]`

- **What we believed:** the venue reprice happens in `venue_quote_fanin.apply_venue_quotes`. I traced the corrupted price properly — `book_prices` <- `cells` <- `_reprice_live_benchmark` <- `venue_quote_fanin` — and then stopped one frame early, at the caller whose name matched.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-30 — FORBIDDEN: an exact-count assertion over a pipeline that has an unmocked ADDITIVE source. It measures the machine, not the code

- **What we believed:** that `assertEqual(len(rows), 1)` tested "when the betting card is empty, the top-props source is used". It had been green in CI for as long as anyone had looked.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-30 — CORRECTION to the entry above: my "VENUE_REPRICE never fires" was LOG TRUNCATION, not absence. The rule I wrote from it was right; the evidence I wrote it from was not.

- **RETRACTED:** *"`GRID_REPRICE` fires every cycle; `VENUE_REPRICE` appeared ZERO times in 45 minutes of production logs"* and the conclusion drawn from it, that `apply_venue_quotes` is never called.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-30 — RULE: an artifact is evidence only once you have checked it contains what its NAME claims. Four instances in one session

- **What we believed:** that `.syndicate/lanes.md.CONFLICTED.bak` held the pre-resolution ledger. It was offered to a user as the safety net that made an unresolved-merge situation recoverable.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-30 — FORBIDDEN: `git checkout --theirs .` to clear a conflict in an append-only ledger. It is a DELETION TOOL, and it staged 929 of them over a peer's work.

- **What we believed:** that after hand-resolving a stash-pop conflict in `deploys.md`, a trailing `git checkout --theirs .` was a harmless tidy-up.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-30 — FORBIDDEN: measuring a FILL-time cost from a SETTLEMENT-time quantity. Realized P&L is `(exit - entry)`; a commission taken at fill is invisible to it BY CONSTRUCTION, so the method returns zero whether or not a fee was charged.

- **What we believed:** Polymarket charges no commission. Ten venue-settled orders, $75.98 notional, implied fee -2.37 bps, every value negative-or-zero. I checked circularity (the delta is the venue's number, not ours) and shipped it — into `state.md`, a lane header, a code constant, and an INVERTED test.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-30 — FORBIDDEN: attributing a commit to a session by ADJACENCY. And: a method that cannot return a non-zero answer has not measured zero

- **What we believed:** that `c17bc3d8` belonged to the session whose commit landed 45 seconds earlier. I sent that session a substantive challenge to a live-money finding it had never touched.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-30 — checks that AGREE are only independent if they differ in the decisive variable

- **RULE: before reporting agreement across N checks, name the variable that differs between them. If you cannot, you have one check and N-1 rehearsals.**
- *(evidence in `learnings_evidence.md`)*

## 2026-08-30 — FORBIDDEN: gating one instance of a shared cause

- **RULE: when a cause is named, grep for every site it reaches BEFORE fixing the one that was reported.** The reported instance is a sample, not the population.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-30 — "not priceable" and "no board row" are different problems with different owners

- **RULE: "we cannot model this" and "nothing generates the row" call for completely different work and different owners. Say which.** One is a modelling problem; the other is a plumbing problem that a model already solved.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-30 — an orphaned `autostash` is somebody's work, and nothing reads a stash list

- **RULE: drop stashes in DESCENDING index order** -- a low drop renumbers every higher one, which is how the wrong stash gets deleted. **Record SHAs BEFORE the first drop and re-check one AFTER**, so the recovery path is verified rather than asserted.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-30 — RULE: a shared tree can sit BEHIND its own HEAD, and the diff then reads as YOU reverting someone. Prove whose content is on disk before restoring

- **What we believed:** that `git status` showing my two files as ` M` in the primary tree meant I had uncommitted work there.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-30 — METHOD: agreement across a sample cannot distinguish a real signal from a CONSTANT INSTRUMENT. Ask what the method is structurally blind to before counting how many times it agreed

- **What happened.** Polymarket's fee was "measured" at zero from the venue's own realized P&L on ten settled orders — every value negative-or-zero, total −$0.0180, −2.37 bps of notional, one outlier excluded for a documented reason. Ten independent orders agreeing to within rounding. It was published, acted on, and it inverted a lane's recorded priority ("Polymarket is two thirds of pair cost" → "Kalshi is the entire bar").
- *(evidence in `learnings_evidence.md`)*

## 2026-08-30 — RULE: a retraction must reach the DOCSTRING of the module whose behaviour changed. Prose is an interface, and it has no test

- **What happened.** The zero-fee finding above was retracted and the constant fixed the same hour: `polymarket_fee_dollars` returned `0.015 * contracts`. **The module docstring went on asserting the retracted finding for four commits** — "Polymarket took **no commission** on these fills", "`polymarket_fee_dollars` returns the measured 0.0" — and additionally called `commissionsBasisPoints` "authoritative where this inference is not", a field that reads `'0'` on every order observed. A reader following the prose would have been handed a zero fee and landed exactly where the retraction started.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-30 — RULE: `lastRunAt` is DISPATCH. Prove execution from the run's own artifact, and prove WHICH failure it was before naming it

- **What we believed:** that a scheduled task with `lastRunAt` set had run. Mine showed `lastRunAt: 2026-08-30T03:10:47Z` and had done **nothing at all** — no heartbeat, no output, no findings.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-30 — FORBIDDEN: shipping a scheduled task without proving it can complete ONE run. A schedule is not a mechanism

- **What we believed:** that writing a good task prompt and setting a cron produced a working watcher. Mine was created to close the last open measurement of a long session, and was reported as "the durable version that survives the session".
- *(evidence in `learnings_evidence.md`)*

## 2026-08-30 — FORBIDDEN: reading a gate's VERDICT without reading what its KEY covers. A measurement about one claim silently denied a different one

- **The rule going forward:** when a gate denies, read its KEY, not just its reason. Ask *what else does this key cover that the measurement never touched?* A gate is entitled to deny what it measured; denying a neighbouring claim by sharing a key with it is an accident, not a policy. The fix shape is a BASIS dimension — the claim being made — not a relaxation of the threshold.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-30 — FORBIDDEN: reporting a config key as UNSET without reading its LIVE value. "The knob is not reaching X" does not mean the knob is empty

- **The rule going forward:** a claim that a key is unset is a claim about production, and only a live read of the env is evidence for it. Reading a findings doc is not. Before reporting "not enabled", run the setter/reader and quote its `before`. And distinguish the two failure modes explicitly, because they have different fixes: **absent VALUE** is a config change; **absent READER** is a code change, and setting the value fixes nothing while making the environment look correct.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-30 — RULE: a guard that refuses only what it can PROVE wrong is SILENT on the majority case when identity is usually unknown. Measure what share of the population it can even evaluate, before shipping it

- **What happened.** `#603` — venue quotes answering the wrong game. The first fix added a game-qualified key and refused any quote that **named a different fixture**. It was correct, tested, deployed, and on its first production board it **rejected exactly zero**.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-30 — FORBIDDEN: `[ -d data ]` as a check that a worktree is data-complete. Partial is worse than absent, and it passes

- **What we believed:** that having confirmed `data/` was "present", a worktree was a valid place to triage test failures. I had already written the rule that a `data/`-less tree fabricates failures, and I checked for it.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-30 — RULE: two guards in series, each encoding a DIRECTION assumption, can withhold a TRUE value with no error anywhere. Each is individually correct and neither can clear the other

- **What happened.** Live execution halted for ~13 hours on both venues. Nothing errored, nothing was misconfigured, and every component behaved exactly as written:
- *(evidence in `learnings_evidence.md`)*

## 2026-08-30 — METHOD: a DEGENERATE distribution is not a boring result. It is evidence the field is not measuring what its NAME says

- **What happened.** A freshness ceiling (`MAX_VENUE_QUOTE_AGE_SECONDS = 45`) was refusing live venue quotes, and the two ages recoverable from refusals were both 64s. Rather than move the ceiling on n=2 from the censored side, the age distribution was instrumented UNCENSORED — every quote considered, passing and failing. First production emission:
- *(evidence in `learnings_evidence.md`)*

## 2026-08-30 — FORBIDDEN: reasoning about a limit order's cost as if the LIMIT were the price paid. It is a CAP; a marketable limit fills at the book.

- *(evidence in `learnings_evidence.md`)*

## 2026-08-30 — CORRECTION, same day: the tick floor did NOT cause the resting Polymarket orders. I paired two log lines 30 minutes apart and called it a mechanism.

- **The quote was 0.51 and we sent 0.51. The floor changed nothing.** It could not have: 0.51 is already on the grid. The 0.515 appeared THIRTY MINUTES LATER, after the order was already resting. The price moved after we bid; that is market drift, not a rounding defect.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-30 — FORBIDDEN: presenting an agreement as corroboration without asking what INPUT the two sides share. Three blind cross-checks in one evening, from one root

- **The rule going forward, and it costs one line of algebra BEFORE collecting data:** *ask what input the two sides share.* Shared and cancelling -> an identity. Shared and invisible to both -> a blind spot. Shared as a fitting range sitting on the crossover -> a degenerate comparison. If the answer is "nothing", the check may be real; if it is anything else, it is not evidence.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-30 — FORBIDDEN: concluding "the venue does not report X" from X being absent in OUR stored row. Read the payload, not the record of it

- **The rule going forward:** `field is None` in a stored row is a fact about the WRITER, never about the venue. Before claiming a source does not supply something, read the source — a one-shot read-only probe took minutes and settled what three sessions had been reasoning about for hours. The same applies to `venue_count: None`, which I used to hypothesise a null-comparison bug in a guard that never reads that row at all.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-30 — FORBIDDEN: trusting a guard that has been crying wolf. Count its false firings before reading its silence OR its alarm

- **The rule going forward:** before citing a guard's alarm as evidence, or its silence as safety, measure its FALSE firing rate on current production. A guard firing on a routine, healthy state is not a guard; it is noise wearing a guard's name, and it is invisible precisely because everyone has learned to skip it. The fix is to make the routine case silent, not to raise the threshold: the correct end state here is `nothing matched`.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-30 — FORBIDDEN: writing to a money-path file without first reading what landed on it. I shipped an unsafe rule that silently overrode a correct fix committed 20 minutes earlier.

- **The premise was false.** `kalshi_orders.fetch_orders` covers the **OPEN** book. An order that FILLED or was CANCELLED is legitimately missing from a completely successful read. An order that filled after a lost submit response has no venue id, does not match by client id, and is not in the open book — exactly my branch's conditions — and would have been marked `rejected`, **deleting a real position from the money record**.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-30 — FORBIDDEN: carrying a count across a population boundary. "71 board spread rows never reach ORDER_PATH" compared an ODDS-BOARD row count against a PORTFOLIO position count, and I spent a day tracing the gap between them.

- *(evidence in `learnings_evidence.md`)*

## 2026-08-30 — A GATE WRITTEN AGAINST DATA THE SYSTEM DOES NOT RETAIN DOES NOT GATE. IT BLOCKS.

- *(evidence in `learnings_evidence.md`)*

## 2026-08-30 — A RETRACTION: I DIAGNOSED THE `not_found` LATCH CORRECTLY IN GENERAL AND WRONGLY IN THE INSTANCE

- **The cause I attributed to the actual blocking order was wrong.** I said it had FILLED or been CANCELLED and so legitimately left Kalshi's open book. It had `venue_order_id=None`, no ticker, `market=spreads_alt`, $1.45 — it was NEVER SENT. A write-ahead record was left `submitted` when the build failed with `OrderBuildError(ticker=None)`. A peer's `63661af1` found that and is what cleared the 55-minute outage; my fix requires a venue id to read by and would have named the order and kept blocking.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-30 — FORBIDDEN: keying a predicate to a field name you have not confirmed the record STORES. My log printed `ticker=None` for every order because `ticker` is not a key on it.

- *(evidence in `learnings_evidence.md`)*

## 2026-08-31 — FORBIDDEN: concluding from ONE tick of a counter that increments before its own drop gate. Three wrong readings in one session, each confident and each plausible

- **What was overturned.** Three separate claims I stated as findings and had to retract, all from the same shape: a reading that was true of its sample and false of the system.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-31 — `TaskStop` does not kill the shell child, and a poller that re-`acquire`s strands its own deploy claim

- **How to apply:** a poll loop reads `deploy_claim.py status` and NEVER `acquire`. Acquire once, keep the token, release with `release --service <svc> --token <t>`. After any `TaskStop` on a shell loop, confirm with `ps -ef | grep <script>` and `kill -9` the survivor. Prefer bounded loops (`for i in $(seq 1 N)`) so a stray child expires on its own.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-31 — THREE HYPOTHESES DIED ON ONE DATASET, AND ALL THREE WERE ONE-DIMENSIONAL PROJECTIONS OF A TWO-VARIABLE RULE

- **THE RULE, measured.** Polymarket fills separate on PRICE, CONDITIONED ON PREGAME. n=14, zero overlap:
- *(evidence in `learnings_evidence.md`)*

## 2026-08-31 — A reachability test in TWO STATES says nothing about the EDGE between them

- **FORBIDDEN: claiming a guard is proven because `off != on` passes. That pair tests the two resting states and is blind to the TRANSITION, which is where a guard that fires late still costs everything it was built to save.**
- *(evidence in `learnings_evidence.md`)*

## 2026-08-31 — A tidier rendering of a `- Files:` list SILENTLY DECLAIMS

- **FORBIDDEN: rewriting a lane's `- Files:` block while compacting it. Reuse those lines VERBATIM. The claim set is parsed out of them, and a rendering that is obviously equivalent to a human is not equivalent to the parser.**
- *(evidence in `learnings_evidence.md`)*

## 2026-08-31 — FORBIDDEN: shipping a gate on a one-variable rule when the sample cannot rule out a second variable. Three hypotheses died on one dataset because each was a projection of a 2-D structure.

- *(evidence in `learnings_evidence.md`)*

## 2026-08-31 — `lane-guard` strips the leading dot, so every claim under `.syndicate/` or `.claude/` is UNENFORCED

- **FOUND, NOT FIXED, and the reason it is not fixed is the interesting half.**
- *(evidence in `learnings_evidence.md`)*

## 2026-08-31 — a branch assertion proves the code RAN, not that it did the right thing

- **OVERTURNED:** my own standard, that a field which exists only in the new code is sufficient verification of a deploy. I have argued this repeatedly and it is still the right FIRST check. It is not a sufficient one.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-31 — a correct fix can make a latent bug REACHABLE, and that is the fix's problem

- **The mechanism generalises.** The gate used to read PLANNED prices — 0.441, 0.444 — which are arbitrary and essentially never land on a round boundary. The fix made it read SUBMIT prices, which are SNAPPED TO THE TICK and therefore land on round boundaries constantly. Correcting the input did not change the comparison; it changed the DISTRIBUTION of values reaching it, and moved the mass onto exactly the point where the comparison was wrong. 0.45 is where a 0.44 or 0.445 quote crosses to, so the arm's most probable price was its blind spot.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-31 — TWO THINGS ABOUT GATED DEPLOYS THAT COST AN HOUR EACH TO REDISCOVER

- **It went UP before it went down.** New sweeps queue behind finishing ones, so the job count is a level, not a countdown.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-31 — FORBIDDEN: verifying a ranking change by TOP-N COMPOSITION. The slate rotates faster than you deploy

- **A composition count over a ranked list is not a property of your change. It is a property of what happened to be on the board.** Measured on the served Layer 2 shortlist, with NO code change, inside twenty minutes:
- *(evidence in `learnings_evidence.md`)*

## 2026-08-31 — A basis LABEL does not make two scales commensurable

- **FORBIDDEN: putting two differently-united quantities into one sort field and treating a stamped `basis` string as having handled it.**
- *(evidence in `learnings_evidence.md`)*

## 2026-08-31 FORBIDDEN: reporting an ROI whose grades we produced ourselves, without naming that we produced them.

- **The rule this is a second instance of, not a first.** `paper_settlement.py` already carries the rule in its own docstring — "THESE ARE NOT THE SAME KIND OF NUMBER AND MUST NOT SHARE AN ROI" — written 2026-08-26 off n=3. `state.md` carried it as UNVERIFIED AND LOAD-BEARING for five days. The surface kept showing the blend the whole time, so the rule existed in prose and nowhere a decision could trip over it.
- *(evidence in `learnings_evidence.md`)*

## [08-31 FORBIDDEN: sizing a payload raise against the key you SHARDED, when another key still scales with the same quantity]

**Measured 2026-08-31, and it corrupted the production board for ~29 minutes.**

Sharding the Layer 2 board split `rows` into per-sport keys, each self-trimming
against its own 8MB ceiling. I raised `SYNDICATE_LAYER2_ROWS_PER_SPORT` 1000 → 3000
after verifying each SHARD fit. It broke immediately, because the **combined key
still carries ~2,200 bytes/row of card/metadata even when `rows: []`**:

```
1634 rows -> combined 3,754,595 B   OK
4552 rows -> combined 9,648,192 B   REFUSED (ceiling 8,388,608)
```

Sharding moved PART of the payload. The unsharded remainder scaled with exactly
the quantity I was raising, so "each shard fits" was true and irrelevant.

**The aggravating detail: I had written the fact down myself**, in the deploys
entry immediately above the incident — *"the combined key is ~3.75MB of
cards/metadata and does not shrink with rows — that is the fixed cost, and it is
the thing to watch"* — then sized the next raise off shard bytes anyway. Calling
it "fixed cost" was the error; it is per-row. **A note you wrote yourself is not
protection unless the next decision actually reads it.**

**How to apply.** Before raising any bound that a splitting change was supposed to
relieve: enumerate EVERY key the write path touches and measure each against the
quantity being raised. "The thing I split now fits" answers nothing about the
things you did not split. The instrument to trust is the one naming the key that
actually refused — `LAYER2_SHORTLIST_WRITE_FAILED` names it and its byte count.

## [08-31 FORBIDDEN: assuming a refused write degrades to STALE. Check what the reader does with a half-updated set]

Same incident, and this is the defect that turned a bad config into wrong data.
`_write_layer2_shards` runs BEFORE `write_json_file(combined)` with **no
rollback**. The shards advanced to a 4,552-row board; the combined write refused;
the combined key stayed frozen at `shard_row_total=1635`. `_merge_layer2_shards`
sizes its slots from that stale total, so **2,917 rows were unplaceable and an
entire sport (NCAAF) vanished from the board** — for at least three build cycles,
because every cycle repeated it. It does not self-heal.

`_shed_rows_to_fit_keyvalue` — the guard that exists for exactly this — is
**skipped when sharding is on** (`if keeps_rows: payload = _shed(...)`), so nothing
trimmed the overflowing key.

**How to apply.** A write that can refuse, in a multi-key set, needs the reader to
be safe against a PARTIAL update — or the writes ordered so the last one is the
one that makes the new set visible. Writing the data first and the index second,
with no rollback, means a refused index write publishes data nobody can address
correctly. "It'll just serve the last good copy" is a claim about the READER, and
must be verified there, not assumed from the writer's try/except.

## [08-31 FORBIDDEN: a size instrument that measures a payload the code no longer writes]

`SHORTLIST_PERSIST_LARGE` reports the payload WITH rows and advises *"lower
SYNDICATE_LAYER2_ROWS_PER_SPORT"*. Since sharding, that payload is **never written
as one key**. It read `pct=93.3` on a perfectly healthy 1,600-row board and
`pct=237.9` on the build that broke — alarming in both cases, actionable in
neither, and its advice was backwards for the healthy one.

**How to apply.** When a write is split, every size/health instrument pointed at
the old single write becomes a liar in both directions. Re-point it at the keys
that are actually written, in the SAME change that splits them.

## [08-31 FORBIDDEN: trusting `git cherry` alone. It gives FALSE POSITIVES, and they push DUPLICATES]

**Refines the standing "remote-absent ≠ content-absent" rule, which said to run
`git cherry` FIRST. That is still right, and it is not sufficient.**

Measured 2026-08-31. Pushing a second batch, `git cherry -v origin/main HEAD`
marked **4 commits `+` (absent upstream). Two of them were already upstream** —
I had pushed them myself an hour earlier as cherry-picks. Their patch-ids no
longer matched because upstream context around them had moved, so `git cherry`
could not recognise its own copies.

Acting on that would have appended two `deploys.md` entries a second time.

**How to apply.** `git cherry` is the cheap filter, not the verdict. Before
pushing, grep the UPSTREAM BLOB for a distinctive string from each commit:

    git show "origin/main:.syndicate/deploys.md" | Select-String '<distinctive phrase>'

and require exactly one occurrence in the tree you are about to push. PowerShell,
not Git Bash: `origin/main:path` is mangled to `origin\main;path` and the command
fails, which — with a `|| echo 0` fallback — reads as **"content absent"** and
argues for pushing MORE. That happened here, in the same check.

## [08-31 FORBIDDEN: running a long test sweep while editing the files under test]

A 72-minute sweep (`-k "layer2 or shard or intelligence_state or shortlist"`)
returned **5 failures**, two naming the exact function I had changed. All 5 pass
in isolation and their three full files pass clean.

The cause was mine: during that 72 minutes I edited
`pipeline/intelligence_state.py` repeatedly AND deliberately swapped it to the
pre-fix `HEAD` version for about a minute to prove the new tests fail without the
fix. A long run imports modules as it reaches them, so it read whatever was on
disk at that moment.

**The result is void in BOTH directions** — it is not evidence of a regression
and not evidence of correctness, because it never tested one tree. Same class as
a `git stash` control that stashed nothing: a control that was not controlling.

**How to apply.** A sweep is a measurement, and a measurement needs a frozen
subject. Either let it finish before touching the files, or run it against a
worktree pinned to the commit you mean to test. Reading its failures at face
value sends you hunting a regression that does not exist — or "fixing" working code.

## [08-31 RETRACTED: the pregame PRICE rule. A pregame fill at 0.45 exists, and I handed that rule to a peer as a threshold]

**What I claimed, earlier this session, and passed on as a usable threshold:**
pregame fills and resting orders separate cleanly on PRICE — *max filled pregame
`0.335`, min resting `0.410`, zero overlap* — with live/past fills at `0.490`.

**The counter-example, measured 2026-08-31 from the served ledger:**

```
tsc-epl-ast-ars-2026-08-31-2pt5   totals over 2.5   polymarket
  fill_price          0.45          <- ABOVE the 0.410 "nothing fills pregame above this"
  submitted_at        15:25:45.239Z
  venue_resolved_at   15:25:45.994Z  <- filled in 0.75 SECONDS
  commence_time       19:00:00Z
  => PREGAME at both submit and resolve, by 3.57 hours
```

A pregame fill at `0.45` cannot coexist with "pregame fills top out at 0.335".
**The rule is FALSIFIED.** Anyone gating on it is using a bound that has a live
counter-example.

**The likely reframe, NOT yet established:** the discriminator is probably
MARKETABILITY, not price. This order resolved in 0.75s, which is a taker crossing
the book, not a maker resting on it. My original population almost certainly mixed
aggressive orders (fill instantly at whatever they are priced) with passive ones
(rest until the market comes to them), and read the mixture as a price boundary.
`EXPLORE_PREGAME_BOUNDARY` deliberately prices ABOVE the ceiling, so exploration
orders land in the aggressive population by construction.

**How to apply.** Do not gate on the 0.335/0.410 numbers. Before any replacement
rule, split fills by `venue_resolved_at - submitted_at`: sub-second is a taker and
tells you nothing about whether a resting order would have filled. A threshold
fitted across both populations describes neither.

**Also, on counting these at all:** `EXPLORE_*` exists ONLY as a log line — no
field on the order marks it. In a 26h window, **17 log lines were 3 distinct
tickers**, because the same order re-logs every tick. Count distinct tickers and
join to the ledger; a line count overstates by ~6x.


## 2026-08-31 — FORBIDDEN: choosing a hypothesis from what is VISIBLE rather than what DISCRIMINATES

- **Three hypotheses on one question in one night, all confidently reasoned, all wrong** (lane `layer2-accuracy-audit`, `todo #611`): the MLB prop pregame freeze has produced nothing since 2026-08-16, and I successively blamed (1) the freeze being unreachable on the worker's disk, (2) the seal's `source_path` being absent under `market/oddsapi`, and (3) the freeze never being invoked for MLB. Each was refuted within the hour, twice by evidence I already held.
- *(evidence in `learnings_evidence.md`)*

## [08-31 FORBIDDEN: matching a guarded status on a GUESSED STRING instead of the condition you care about]

**Twice in one session, same shape, both in my own deploy watchers.**

1. A watcher polled the **LIVE** deploy to decide whether one was in flight. A
   deploy that is `build_in_progress` is not live, so it read "nothing happening"
   and **took the deploy claim while another deploy was mid-build** — the exact
   race the claim exists to prevent.
2. A watcher gated acquisition on the status line containing `free`. The real line
   read `EXPIRED (does not block)` — my own 61-minute-old claim, which was not
   blocking anything and which `acquire` would have replaced immediately. It
   polled for **six minutes and would have polled forever**, in the middle of a
   sequence whose next step was a production flip.

Both are the same error: I encoded a **guess about how the state would be
spelled** rather than the condition. `free` and `EXPIRED (does not block)` are
both "you may acquire"; `live` and `build_in_progress` are both "a deploy exists".

**How to apply.** When gating on a tool's output, gate on the tool's OWN verdict —
its exit code, or the explicit set of states it documents — never on a substring
you expect to see. If you must match text, enumerate every terminal AND permissive
spelling, and assume the one you did not think of is the one that will appear. A
watcher that stalls is the benign outcome; the other one deployed into a race.


## 2026-08-31 — FORBIDDEN: shipping a diagnostic without first proving its OUTPUT is readable

- **The check that would have caught it costs one query and I did not run it:** before adding a log line, confirm that SOME EXISTING line from the same process reaches the reader you intend to use. I had the evidence to do this — I had already been told the odds-refresh subprocess's stdout is captured to a file, and I had already watched Render's logs API return MLB refresh activity only as `ALL_PROCESS_MEMORY` process-list entries, never as script output.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-31 — FORBIDDEN: shipping a model INPUT artifact without tracing its delivery topology first. "Publish" does not mean "the engine can read it"

- **Three separate mechanisms had to be checked before a 867-byte calibration file could reach the engine that reads it, and TWO of my first two choices were silently wrong. None of them would have failed loudly.**
- *(evidence in `learnings_evidence.md`)*

## 2026-08-31 — A miscalibration can be REAL and still not worth correcting. Check what carries the LOSS, not what looks wrong in a ratio table

- **I pre-registered the wrong expectation and the held-out test refuted it, which is the only reason it is not now shipped.**
- *(evidence in `learnings_evidence.md`)*

## 2026-08-31 FORBIDDEN: two guards that read the SAME input are one guard

- **Independence is a property of the INPUT, not of the code path.** A second check that consumes the first one's source adds only the appearance of redundancy, and it reads as defence-in-depth in review precisely because it was written to be.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-31 A CONVENTION VERIFIED ON ONE SPORT IS NOT A CONVENTION

- **HOW TO APPLY.** When a parser encodes an external system's naming convention, the docstring must say WHICH instances it was verified against. A convention confirmed on one league, one sport, or one feed is a sample of one. And the places that consume the roles POSITIONALLY are the blast radius — here, fixture matching survives an inversion (both teams are present, so the game is still found) while ROLE selection does not, which is why only the leg choice broke.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-31 A TEST CAN PASS THROUGH THE BUG IT IS NAMED FOR

- **HOW TO APPLY.** A stub that makes a dependency maximally permissive does not "isolate" the unit — it silently selects whichever code path does not consult that dependency. When the test's name is about CHOOSING between candidates, an always-True matcher guarantees the choice is made somewhere else, and the test then pins that somewhere-else forever. Stub discriminatingly, mirroring what the real dependency answers, and pin the permissive case as its own explicit test with the opposite expectation: a resolver that matches everything must REFUSE.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-31 FORBIDDEN: two guards that read the SAME input are ONE guard

- **HOW TO APPLY.** When a comment claims one check guards another, ask what each READS. Independence is about INPUTS, not about being separate code. Two checks over one derived value are one check with extra words — and the redundancy makes it look safer than a single check would. Prefer the check that reads a DIFFERENT SOURCE (here: the board's own team names, not the slug's positions), and put it FIRST when it is the authoritative one. Related: [[feedback_gate_on_the_output_not_the_input]].
- *(evidence in `learnings_evidence.md`)*

## 2026-08-31 FORBIDDEN: fixing a decision's INPUT without checking every CALLER supplies it

- **HOW TO APPLY.** Changing which field a decision reads is a change to every caller, whether or not their code changes. Enumerate the call sites and check each supplies the new field — the schema is the evidence (`_SLATE_STORAGE_FIELDS`), not the passing suite. And when the new failure mode is "refuses", a green suite is especially weak evidence: most safety tests assert exactly that.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-31 FORBIDDEN: treating `Auto-merging <file>` as a verification of a ledger merge

- **The rule going forward.** Before pushing ANY merge that touches `.syndicate/`, run each ledger file's own invariant against the MERGED blob, never the merge exit code, and never only the file that failed last time: `py -3 scripts/lane_claim_audit.py` plus an explicit **one OPEN `### <slug>` header per slug** assertion for `lanes.md`; **one `## [subject]` section per subject** for `state.md`; then `echo '{}' | py -3 .claude/hooks/ledger-postwrite-check.py` — it reads stdin like every hook here, so on a bare TTY it hangs and reads as a pass. Prefer `git merge-tree` / `commit-tree` when other sessions are live: it lets you inspect the merged tree before it exists anywhere.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-31 FORBIDDEN: taking a tool's DEFAULT liveness detection as the answer to "is this session gone"

- **The rule going forward.** Establish liveness from the roster, then pass `--live <id>` explicitly for each session that is genuinely running; never let the mtime default decide. **And re-read liveness immediately before the write, not once at the start** — "no active sessions" was true at 01:4xZ, false by 02:0xZ when a new session opened a lane, and a second one appeared at 02:4xZ. Note the default errs CONSERVATIVE (a dead session looks live, so a lane is skipped); the dangerous direction — sweeping a lane whose session is running — is what the re-read before writing protects against.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-31 FORBIDDEN: pooling an evaluation sample across artifact ROOTS. Split on provenance BEFORE the first statistic, and report the split. `[lane wnba-accuracy-assessment]`

- **What happened.** I graded the WNBA pregame sim over the whole 2026 season off `/wnba/api/cards` and reported: **Brier skill -21.5%, AUC 0.5954, spread AUC 0.4806, totals +10.45 pts/game biased.** That reads as "the model is worse than climatology and its spread signal is inverted" — a delete-it verdict. It was wrong.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-31 FORBIDDEN: reporting a live-model hit rate without splitting by GAME CLOCK and by LINE SOURCE. A number that improves as the game ends is leakage, not edge. `[lane wnba-accuracy-assessment]`

- **What happened.** The WNBA live prop engine grades out at **1249-440, hit 73.95%, +41.18% ROI at -110** over 1,689 signals — graded correctly, against *final* box scores. Every step of that arithmetic is right and the conclusion would have been catastrophic.
- *(evidence in `learnings_evidence.md`)*

## 2026-08-31 FORBIDDEN: shipping a calibration refit validated only in-sample — and treating a POOLED miscalibration as a current one. `[lane wnba-accuracy-assessment]`

- **What happened.** I measured the WNBA win-prob mapping's implied margin SD at **10.87** against a pooled residual SD of **12.81**, refit sigma to **18.25**, and watched in-sample Brier skill go **+16.53% → +21.51%**. A clean one-parameter win, and I was one step from recommending it.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-01 REQUIRED: for every grader, ask what it does when its OUTCOME SOURCE IS ABSENT. A fallback there is a false-result generator. `[lanes wnba-accuracy-assessment + mlb-accuracy-assessment, independently]`

Two lanes hit the same instrument family on the same evening, on different
sports, and compared notes. The comparison is worth more than either finding.

**MLB** (`mlb-accuracy-assessment`): the live-lens grader settled from
`lastSeenSnapshot.actual` — **a running tally** — whenever the statsapi feed was
unavailable, which was 100% of the time (`feedResolved` 0 on all 11 days that
produced rows, against `feed_live_miss: 1,802`). Published reading:
**`over 0 wins / 1,578`, `under 206 / 206`.**

**WNBA** (`wnba-accuracy-assessment`): the same shared module,
`live_lens_local._settle_over_under`, returns **`None`** when the outcome is
absent. Grep that module for a running-tally fallback — `get("actual")`,
`lastSeen`, snapshot-actual — and it is **zero hits**. The signal row *carries*
an in-progress `actual` and the grader never reads it. Published reading:
**`n_settled: 0`.**

**Same missing input. Opposite blast radius. Zero is a null result; 0-for-1578 is
a false one, and a number gets acted on.** The discriminating variable is not
whether the input is published, not which sport, and not the shape of the
plumbing. It is one question:

> **When the outcome source is missing, does this grader return UNSETTLED, or
> does it settle from something else?**

That question is cheap, needs no knowledge of a sport's pipeline, and would have
caught every instance below. **Ask it of every grader.** If there is a fallback,
that fallback is a false-result generator, and publishing its real input does not
fix it — it only changes which wrong number you get.

**The family is NOT "unpublished input".** That was the first hypothesis and it
is too narrow. The family is **"one side of the comparison is not what it claims
to be"**, and it already has three distinct mechanisms:

| mechanism | side that lies | measured |
|---|---|---|
| proxy outcome | outcome | MLB: running tally for a final ⇒ 0/1,578 |
| stale line | line | WNBA: pregame full-game prop line, `line_live_age_sec` null on 1,777/1,777 ⇒ hit rate walks Q1 55.9% → Q4 88.0% on the clock alone |
| self-priced line | line | WNBA: 701 of 1,777 signals graded against the engine's OWN model line ⇒ 91.2% |

The unpublished-input hypothesis IS instantiated on the WNBA side and was worth
chasing — `recon_quarters_*`, the sole settlement source for every half- and
quarter-total market, was in **no** `HOT_ARTIFACT_PATTERNS` entry while both its
siblings were (`git show 9dbb870d~1:...artifact_publisher.py | grep -c
recon_quarters` → **0**). It is fixed. But it was never why WNBA read zero, and
treating it as the common cause would have left the two line-side mechanisms
undetected.

**How to apply, in order:** (1) for each grader, name its outcome source and its
line source; (2) delete or hard-fail any fallback on either; (3) only then
publish the missing inputs. Doing (3) first turns a visible null into an
invisible falsehood.

---

## 2026-09-01 REQUIRED: assert on the VALUE THAT CROSSED THE BOUNDARY, not on the call returning. "It didn't raise" and "the counter moved" are different claims, and only the second is evidence. `[lane wnba-accuracy-assessment]`

**What happened.** I added a block to publish WNBA recon artifacts from
refresh-worker to web, because the producer was writing to the worker's disk and
the web-facing endpoint reads web's. The block ran cleanly, raised nothing,
returned, and **published zero files.**

The bug: the tick builds a small summary off the producer's result for the log
line —

    result["recon"] = {key: recon.get(key) for key in ("status", "games", "quarters", "props")}

— and `paths` is not one of those four keys. The publish loop then iterated
`(result.get("recon") or {}).get("paths", {})`, which was **always empty**. Every
observable said fine: no exception, `status: ok`, a well-formed log line, and a
`published` map that was simply `{}` rather than obviously wrong.

**What caught it, and it is the only thing that would have.** The test asserted
on *what reached the publisher* — it patched `publish_hot_artifact` with a
recorder and asserted the four expected filenames were in it:

    names = {p.rsplit("/", 1)[-1] for p in sent}
    assert "recon_quarters_2026-08-30.csv" in names

A test that asserted the tick returned without raising, or that `published` was
present, or that the producer reported `ok`, would have **passed on the broken
version**.

**THE GENERALISATION.** This is the same failure as a test asserting *a deploy
happened* rather than *the code ran*, and the same as an off/on check asserting
*the call succeeded* rather than *the counter's value changed*. Any time work
crosses a boundary — a process, a service, a disk, a queue, a network — the
assertion has to name **the thing on the far side**:

| weak assertion | what it actually proves |
|---|---|
| the call did not raise | the caller survived |
| the function returned a dict | the caller survived, verbosely |
| status == "ok" | the PRODUCER is happy |
| **the recipient received X** | **the boundary was crossed** |

**This is distinct from the readability rule** (`before reading a null result,
find the thing that says the signal could have arrived`) and the two were nearly
folded together. Readability is about **when a reading is interpretable**; this is
about **what the assertion is even claiming**. A test can be perfectly readable
and still assert nothing that matters.

**How to apply.** For any cross-boundary work: patch or observe the RECIPIENT,
and assert on the value it received. If the recipient cannot be observed in a
test, that is itself the finding — an unobservable boundary is where silent
failures live, and it is exactly where this one lived for its whole short life.

### SECOND INSTANCE, SAME DAY, BY THE SESSION THAT CITED THIS RULE APPROVINGLY — `[lane mlb-accuracy-assessment]`

**About an hour after telling the lane above that their `paths` bug deserved its
own rule, I shipped it in my own file.** `quote_rows_from_kalshi_matches` set
`venue_ticker`, documented as *"the only field that makes a row traceable back to
a specific Kalshi market"*. `_normalize` in the same module builds a **fixed key
set** and silently drops anything outside it. The field reached disk on **0 of
603 production rows**, through a full deploy, with a GREEN test.

The test's failure is the precise thing this rule names. It asserted:

    row = quote_rows_from_kalshi_matches([_match()])[0]
    assert row["venue_ticker"] == "KXMLBHR-..."

— which is the **near** side. The builder is not the boundary; `_normalize` is.
The replacement asserts against the boundary itself, and needs no fixture to know
what survives:

    kept = _normalize(row, sport=..., date_str=..., captured_at=...)
    assert set(row) - set(kept) == set()

**WHY THIS INSTANCE ADDS SOMETHING.** The first instance had a plainly weak
assertion (the call did not raise). Mine had a **specific assertion on a real
value** — it looked exactly like a good test, and the rule as written above could
be read as already satisfied by it. It is not. The question is not *"does the
assertion name a value?"* but *"is that value on the FAR side of the boundary the
change has to cross?"* A builder that returns the right dict has crossed nothing.

**THE CHEAP GENERAL FORM, when the boundary is a normaliser/serialiser/schema:**
do not assert the field is present — assert the **set difference** between what
the producer emits and what the boundary keeps is empty. That catches every
future field at once, including ones nobody thought to test, and it fails at the
moment the producer adds one rather than in production weeks later.

**Corollary that decided the fix.** The remedy was to DELETE the field, not to
teach `_normalize` a new key. A normaliser widened to rescue a field that nothing
downstream reads is scope taken on the strength of a mistake.

---

## 2026-09-01 FORBIDDEN: inferring a MECHANISM from a file's SIZE. Count the composition, or say you haven't. `[lane wnba-accuracy-assessment, caught by lane mlb-accuracy-assessment]`

**What I claimed.** WNBA's board shows zero Kalshi/Polymarket quotes across 787
book references, while `wnba_source/tracking/book_quotes/2026-08-30.jsonl` is
**45,776,899 bytes**. I wrote that up — into `todo.md #616`, into a peer message,
and into a user-facing summary — as:

> *"a JOIN gap, not an ingestion gap. The prices are already captured, on the
> same service, in a 45MB file."*

**What was actually in the file.** 101,129 rows, 11 bookmakers, and
**ZERO exchange rows** — no kalshi, no polymarket, no novig, no prophetx, on any
market. The board showing no exchange price was **correct behaviour over its
input**, not a defect. There was nothing to join.

**The bytes were real and the mechanism was invented.** 45.8MB is a true fact
about the file and says nothing whatever about whose prices are in it. I used
size as a proxy for content and then named a fix ("a join, one function call")
that would have been a **no-op**.

**How it was caught, which is the part to copy.** The peer lane refused to accept
the symmetry I offered it and counted ITS OWN file instead — 274,129 lines,
26,710 exchange quotes on game markets, 0 on props — concluding MLB's was a
SOURCE gap, not a join. That composition count is what made me count mine. **I
had told that same lane, twice, to measure rather than assume symmetry, and then
did not do it myself on the one file my own conclusion rested on.**

**The tell, in hindsight.** I had the file's *name* and *size* from a
`names_only=1` listing. `names_only` is a listing, not a reading. Every number I
had was metadata, and I reasoned about contents.

**The rule.** A claim about WHAT IS IN a store must come from counting what is in
it — by the field that decides the claim (here: `bookmaker`). Size, row count,
mtime and existence are all metadata and support none of:
"the data is there", "it's a join problem", "the producer ran", "coverage is
fine". If counting is too expensive right now, the honest form is *"N bytes
exist; composition uncounted"* — which is a fact — rather than a mechanism, which
is a guess wearing a measurement's clothes.

**Related and distinct:** `[read the field you already have]` is about ignoring a
discriminating field that is already in hand. This is about not HAVING the field
and proceeding anyway. Both end in a confident wrong mechanism; the fix here is
to go and get the field.

---

## 2026-09-01 FORBIDDEN: naming a MECHANISM from a SYMPTOM. Three times in one session, on three different subjects. `[lane wnba-accuracy-assessment]`

Same error, three subjects, one day. Recording the set rather than any one of
them, because the pattern is the finding.

| I measured (true) | I claimed (invented) | what it actually was |
|---|---|---|
| `book_quotes` file is **45.8MB** | "captured but not joined — a JOIN gap" | **0 exchange rows in it.** Nothing to join. |
| `artifacts/export` count **0** for recon | "gate 2 is STRUCTURALLY unreachable" | It crossed on its own. The count predated the producer's first run. |
| `active_sports: ['ncaaf','soccer']` | "Layer 2 EXCLUDES WNBA upstream" | **No allowlist exists.** The field is derived from whichever sports had rows. |

Each measurement was correct. Each mechanism was fiction, stated with the
confidence the measurement had earned — and in two of the three I named a FIX,
which would have been a no-op.

**The shape.** A symptom is a value you read. A mechanism is a claim about *why*
that value is what it is. Reading one does not give you the other, and the gap is
invisible from inside because the number is real and right there. The tell is
grammatical: *"the board can't see it"*, *"it's structurally unreachable"*,
*"excluded upstream"* — all causal claims, none of which any of those readings
could support.

**The check that would have caught all three**, and it is one question:

> **What else would produce this same reading?**

- 45.8MB → "a file full of sportsbook rows" would too. → count by `bookmaker`.
- count 0 → "the producer hasn't run yet" would too. → check the producer ran first.
- `active_sports` without wnba → "no WNBA rows in the pool" would too. → read the code that builds the field.

In all three the disambiguating evidence was **one command away** and I did not
run it, because the symptom already felt like an explanation.

**Corollary that cost the most time:** two of the three were *fixes I nearly
shipped*. A mechanism invented from a symptom generates a plausible, specific,
wrong repair — and it will pass its own tests, because the tests are written
against the invented mechanism too.

**How to apply.** Before writing a causal sentence about a system, name the
reading it rests on and one alternative that would produce the same reading.
If you cannot rule the alternative out with evidence in hand, the honest form is
*"symptom X; cause not established"* — which is a finding, and is what `#614`
and `#616` now say.

---

## 2026-09-01 REQUIRED: a PRODUCER fix is not in force on data that already exists. Ask when the artifact is next written. `[lane wnba-accuracy-assessment]`

**What happened.** I fixed three things in the WNBA odds producer — totals
withheld, impossible EV refused, certainty clamped — deployed them to all three
services, verified all three deploys reached `live`, and was about to report the
items done. Then I read the SERVED PAYLOAD:

    card_bucket: candidate      <- live, changed
    p_win:       1.0            <- unchanged
    market:      TOTAL present  <- unchanged

Not a failed deploy. `card_bucket` is assigned at READ time, so it changed the
instant web restarted. `p_win`, `ev_pct` and `market` are **baked into
`recommendations_slate_*.json`** and copied verbatim by the card builder — the
producer governs what is *written*, and **WNBA does not rebuild until
2026-09-17**. The fix was live and in force on nothing anyone could see, for
sixteen days.

**THE DISTINCTION, which is not the same as the deploy one.** "Deployed" vs
"running" is already a rule here. This is a third state past it:

| state | question it answers |
|---|---|
| landed | is it on `origin/main`? |
| deployed | is the process running it? |
| **in force** | **has the artifact it governs been rewritten since?** |

A producer fix reaches production instantly and reaches *the data* only at the
next write. Between those two moments every reading looks exactly like the fix
failing.

**How to apply.** For any change to a producer, name the artifact it writes and
answer *"when is that artifact next written?"* before claiming the item is done.
If the answer is "not for N days", the change is **deployed, not in force**, and
that is what to report. Where the gap matters — here, a board serving
`p_win = 1.0` and `EV 2264.8%` for sixteen days — apply the same rule at READ
time as well, so the fix governs what a reader sees and not only what a future
writer produces.

**Seasonal sports make this the normal case, not an edge case.** Any producer
fixed during an off-season or a mid-season break is in exactly this state, and
the break is precisely when there is time to fix things.

---

## 2026-09-01 REQUIRED: on the shared tree, read the DIFF of a ledger file before committing it, not its --stat. `[lane wnba-accuracy-assessment]`

**What happened, twice in one day, in both directions.**

* A peer's broad `git add` swept MY `log/2026-09-01.md` entry into their commit
  `7b31a766`. Content durable, attribution theirs.
* I staged `.syndicate/lanes.md` to record a one-line claim and swept **112
  lines of a third session's brand-new lane block** (`mlb-live-gameline-skill-audit`,
  session `250953ef`) into my commit `c544b30c`.

Nothing was lost either time — both were purely additive, and I verified the
swept block is complete on `origin/main` before moving on. That is luck about the
shape of the edit, not a property of the process.

**The specific miss, and it is not "I forgot to check".** I DID run
`git diff --cached --stat`. It printed `.syndicate/lanes.md | 113 +++...` for a
change I knew was one line, and I read the file list rather than the number. A
`--stat` answers *which files* am I committing; only the diff answers *what*.

**The rule.** For any file in `.syndicate/` or another shared ledger, `--stat` is
not sufficient before commit:

    git diff --cached -- .syndicate/lanes.md | grep -E "^\+### |^-"

Two things to look for: a `### ` heading you did not write (someone else's lane
block rode along) and ANY deletion line (which is the case where content is lost
rather than merely re-attributed).

**Why the number is the tell.** A one-line edit that stages as 113 lines is
arithmetic that cannot be right, and it was visible before the commit. The check
that catches this costs one command; the version where the edit is *not* additive
costs someone their work.

**This is the same shape as `[shared index can hold a revert]`** — 4,993 staged
deletions invisible in the worktree — and the same fix applies: the index on a
shared tree contains whatever anyone put there, so read it, do not assume it
holds only what you touched.

## 2026-09-01 FORBIDDEN: recording a LIVENESS field that the recorder itself cannot outlive

- **What we believed.** `deploy_claim.py`'s `"pid"` identified the session holding
  a deploy lock, so the documented `--force` procedure — "verify the holder is
  gone" — could distinguish a live holder from a dead one.
- **What was actually true.** It recorded `os.getpid()` **inside the
  `deploy_claim.py acquire` CLI process**, which exits about a second after
  writing the claim. **Every claim in the repo read as "held by a dead process"
  within seconds of being taken.** The field could only ever say "gone", so
  `--force` was not an escape hatch, it was the default outcome.
- **How we found out.** A live claim with **15 minutes of TTL left** was
  force-broken by another session citing "pid 22884, verified DEAD via
  Get-Process". `Get-Process` was right and the checker was right — **the FIELD
  lied.** Nothing programmatic ever read it (`deploy_preflight.py` never did), so
  its only consumer was a human deciding whether to break someone's lock.
- **The rule going forward.** A liveness field must name something that OUTLIVES
  the code writing it — a session id, checkable with `list_sessions`
  (`isRunning`) — never the pid of the short-lived CLI that records it. If no
  such identity is available, **write nothing and let the TTL be the invariant**:
  a missing field reads as UNKNOWN, which correctly refuses to authorise a force,
  whereas a dead-on-arrival pid reads as PERMISSION. Absent identity is not
  absence of a holder.
- **Cost.** One force-broken live claim and a deploy handed to another session
  mid-work. No production damage — the TTL was doing the real work the whole
  time, which is exactly why the pid was safe to delete rather than repair.

## 2026-09-01 FORBIDDEN: leaving anything staged in the SHARED index that you are not committing in the same breath

- **What we believed.** The hazard of the shared index is `git add <path>`
  sweeping ANOTHER session's edits into MY commit — the 2026-08-20 rule above —
  and the standing guidance "never chain add and commit" follows from it. So
  staging, then pausing to inspect `git diff --cached` before committing, reads
  like the careful thing to do.
- **What was actually true.** **The exposure is the DURATION, and it runs in both
  directions.** `git commit` commits the WHOLE index, so anything of mine sitting
  staged is fair game for any other session's next commit — whatever files it
  names, whatever its message says. Measured 2026-09-01: I staged a `lanes.md`
  closure and a 27-line `todo.md` carry-forward, paused to inspect, and another
  session's commit `fff3a3f8` — titled *"deploys: 417e19ed — the near-miss false
  alarm is gone"* — absorbed both. Content survived; two of its three files have
  nothing to do with its message.
- **How we found out.** `git diff --cached --stat` listed a file I had not
  staged (`deploys.md`), then moments later listed NOTHING and `HEAD` had moved.
  An index that empties itself under you is another session committing, not a
  git quirk.
- **The rule going forward.** Stage and commit **atomically** or not at all:
  `git commit --only -- <paths>` takes the worktree copies of exactly those paths
  and leaves the rest of the index alone. When the commit needs content that is
  NOT the worktree copy (rebuilding `origin/main` + only your edits), build it in
  a **temporary index** — `GIT_INDEX_FILE=<tmp> git read-tree/update-index/
  write-tree` then `git commit-tree` — which never touches the shared index at
  all. **Inspect BEFORE staging, never between staging and committing.** The
  older "never chain add and commit" is not wrong, but it is not the invariant:
  the invariant is that no staged state of yours may outlive your own commit.
- **Cost.** None to content — both edits reached `origin/main`. The damage is to
  the record: a commit message that misdescribes two of its three files, and an
  authorship trail that says a session did work it never did. On a repo whose
  ledger is read as evidence, that is the expensive kind of wrong.

## 2026-09-01 FORBIDDEN: running any git working-tree restore (`checkout --`, `restore`, `reset`) without pinning the repo with `-C <path>`. The cwd is not a fact; on this machine it is a liability that destroys OTHER SESSIONS' work. `[lane polymarket-prop-quote-capture]`

- **What we believed.** "I am in my worktree" — because the previous command
  `cd`'d there. So `git checkout -- .syndicate/lanes.md`, meant to discard a
  botched insert in MY worktree copy, was safe.
- **What was actually true.** An intervening one-off command (`cd <primary> &&
  py -3 scripts/render_logs.py ...`) had silently moved the persistent shell
  cwd back to the PRIMARY, SHARED tree. The checkout ran there, restored
  `lanes.md` from HEAD, and destroyed EVERY uncommitted edit in the file:
  my own lane-close block AND two closed-lane blocks belonging to a live
  peer session (syndicate-8d: `phase0-graded-supply`, `phase0-accuracy-autorun`)
  — ledger records of landed work, existing nowhere else. A foreign
  cherry-pick was also in progress in that tree at that moment.
- **How we found out.** The next command in the chain printed the PRIMARY
  tree's `git status` (branch main, 10/45 diverged, cherry-pick in progress)
  where worktree output was expected; `grep -c` then found 0 of the 3 blocks.
- **The rule going forward.** THREE layers, because each alone has now failed:
  (1) every git command that can DISCARD working-tree content must carry an
  explicit `git -C <absolute-path>` — never rely on the shell's cwd;
  (2) a file-wide restore is NEVER the tool for undoing a targeted
  experiment — reverse the specific edit (string-swap back) instead, which
  cannot exceed its own blast radius (this same session had already wiped its
  own uncommitted implementation once with `checkout --` in the worktree —
  same instrument, and the second firing hit ANOTHER session);
  (3) on the shared tree, `checkout/restore` of a ledger file is forbidden
  OUTRIGHT — uncommitted peer edits live there by design, and the command
  cannot distinguish yours from theirs.
- **Cost.** Two peer ledger blocks destroyed (peer notified immediately with
  partial text; a HOLE MARKER stands in `lanes.md` until they rewrite from
  their own context — deliberately not reconstructed from fragments). My own
  block was reconstructible from context. No code, no production state, and
  no pushed history were touched.

## 2026-09-01 — FORBIDDEN: comparing a model against a market price without conditioning on QUOTE AGE. A stale price is a weak forecast, so staleness flatters the model — the error runs in the reassuring direction `[lane mlb-live-gameline-skill-audit]`

One ledger, two opposite conclusions, decided entirely by which prices were
admitted. MLB live game-lines, 12 dates / 72,587 records / 157 games, h2h scored
against StatsAPI finals:

    quote age   n     model    market   model-minus-market
    <= 120s     954   0.20000  0.17403  +0.02597   <- the model honestly LOSES
    300-600s    320   0.16264  0.17011  -0.00747
    600-1800s   501   0.16326  0.19047  -0.02721
    > 1800s     592   0.16459  0.21897  -0.05438   <- the model "WINS"

Pooled over every age: **-0.00202, CI straddles zero — reads as parity.**
Restricted to quotes that were alive: **+0.01096, CI [+0.00171, +0.02132],
model worse in 98.9% of game-level resamples.**

**The model does not improve as the quote ages. The MARKET decays**, because a
price that has not moved in half an hour is a bad forecast of an outcome it has
not seen. Quote-age distribution in that file: p50 410s, p90 1,848s, **p99
74,997s** — roughly 1 row in 100 was priced against a quote over 20 hours old.

**The failure mode is a FABRICATED EDGE, not a wrong number.** The subset the
board liked best — late game, `|edge| >= 20pp` — had a MEDIAN quote age of 42.9
minutes and scored a fair-odds "return" of **+98.7%**. That is not an edge; it is
the arithmetic of pricing against a quote nobody could have taken. On FRESH
quotes the same `|edge| >= 20pp` band scores **+0.16305** — the biggest claimed
edges are the biggest errors, the exact inversion.

Generalises past game-lines: any `model vs market` comparison — props, CLV,
settlement, venue routing — inherits this the moment its market side can be
stale. **Ask what the p99 quote age of your comparison population is before you
believe its sign.**

## 2026-09-01 — FORBIDDEN: pooling an accuracy history across a SCORER-version boundary, and shipping a scorer whose payload cannot say which version produced it `[lane mlb-live-gameline-skill-audit]`

`reports/live_gameline_accuracy/history.jsonl` reported "model worse on 10 of 12
dates, +0.04839". It was measuring a bug fixed on day 11. Until `75cf9aec` the
scorer compared totals `P(over)` and spreads `P(home covers)` against "did the
home team win" — ~92% of the population was a category error. Proof by n:
offline h2h-only scoring matches production EXACTLY on 08-30 (249/249 rows,
briers identical to 5dp) and is 10-20x smaller on every earlier date.

**Nothing in the row said which scorer wrote it**, so the boundary was invisible
and had to be rediscovered by matching record counts. The rule has two halves:

1. Every evaluation row carries the identity of the code that produced it
   (`scored_markets`, `scorer_contract`). Absence is itself a version signal.
2. **A branch that has nothing to measure must STILL report that identity.**
   Measured the same day: a pregame board served exactly
   `['enabled','finals_index','games_with_outcome','reason']`, so "the new
   scorer shipped and had nothing to score" and "the new scorer did not ship"
   were the same null, and a deploy could not be verified until a game finished.
   These are constants — they never needed a sample to be reportable.

## 2026-09-01 — FORBIDDEN: `ast.parse` as a syntax check for an edit, and building a `write` and a `read` of the same path in one expression `[lane mlb-live-gameline-skill-audit]`

Two self-inflicted breakages in one session, both from a check that looked
sufficient.

* **`ast.parse` does NOT catch `return` outside a function** — that is a
  compile-time check, not a parse-time one. A bad dedent while extracting a
  function passed `ast.parse` cleanly and the module raised `SyntaxError` on
  import, surfacing as an unrelated NFL test failure three files away. Use
  `py_compile.compile(path, doraise=True)`, and import the module.
* **`io.open(p,'w').write(io.open(p).read().replace(...))` TRUNCATES THE FILE.**
  Python evaluates the `'w'` open first, so the inner read sees an empty file.
  It silently zeroed a 368-line module. Caught only by `git diff --stat` showing
  368 deletions. Read to a variable first, then write.

## 2026-09-01 — RULE: a claimed GAIN that exceeds the TOTAL COST it is meant to remove is about a different population. One comparison rejects it, with no machinery. `[lane game-market-entry-roi-curve]`

The 08-31 assessment published *"an exchange improves on the best sportsbook by
**+1.57pp** ... worth about +1.2% ROI"* for MLB game markets. The book that
stakes that money pays **0.88pp per side in total** — a 1.96% two-way hold,
because it already routes to exchanges. An improvement of 1.57pp cannot be
harvested from an entry cost of 0.88pp; there is not that much cost there to
remove.

**That single sentence is a complete refutation**, and both numbers were
obtainable the same afternoon. Everything else the re-derivation found — that
62% of the improvement was already banked, that the residual mostly sits at
books with no execution path, that `+1.57pp` was a single date pooling to
`+1.101pp` — is *elaboration* on a conclusion this comparison already forces.

**How to apply.** Before converting any improvement into money, print the total
size of the thing it improves. `gain <= total cost` is a units check, and it is
cheaper than the measurement. If it fails, the gain and the cost were measured
on different populations — which is what happened here: the gain came from a
superset counting every quoted cell on the board, the cost from the rows
somebody actually bet.

**The companion trap.** Correcting only the *conversion rate* would have made it
worse. The published slope (0.75) was wrong and the true game-market slope is
**+2.45** at this book's operating point — so a diligent fix of just that error
publishes **+3.8 points**, further from the measured **+0.74** than the +1.2% it
replaced. **A wrong number can have two errors pointing opposite ways; fixing
the one you found is not progress until you have looked for the other.** The
prop-side correction the day before had exactly this shape and said so.

## 2026-09-01 — FORBIDDEN: treating the timestamp on an ORDER as the timestamp of the PRICE it took. Board prices carry a real age, and the error does not surface as an error. `[lane game-market-entry-roi-curve]`

Anchoring a de-vig on `submitted_at` looks obviously right and is wrong here.
The board hands the executor a price with an age of its own (`book_age_seconds`
median 202s, p90 1,308s), so an order written at 20:00 is routinely taking a
quote the book showed at 19:00 and has since moved off. Measured: on **139 of
584** MLB game-market orders the book's quote at submission differed from
`fill_price` by more than 1pp — mean **-2.46pp**, worst -77pp.

**What it produced, and why nothing caught it.** The book's mean per-side entry
cost came out at **-1.43pp** — paying *less* than fair on average, which is not
a thing that happens — and the sensitivity table then read **-1.05%** at
"today's" cost. No exception, no refusal, a full table printed. It was caught
only because the ledger's own stake-weighted return on the same rows was
**+5.31%**, six points away.

**How to apply.**
* **Anchor on the last moment the taking book actually SHOWED the price paid**,
  matched exactly. It is self-verifying and it dates itself: median age 16.5
  minutes here. Rows where the price never appears are REFUSED, not
  approximated — 206 of 929 land there, and they are reported as a coverage
  bound with their own ROI (+15.85% against the priced rows' +6.14%), because a
  refusal set that returns differently is not a random sample.
* **Put the ledger in the test.** `roi_at_book_cost(rows, today, today) ==
  roi_at_quoted_price(rows)` is the invariant that failed, and it is now a unit
  test. A curve that does not pass through the price actually paid is not a
  curve, and the assertion costs one line.
* **`captured_at` is the refresh cycle; `snapshot_ts` is one book's own last
  update.** Grouping cross-book comparisons on the latter finds almost no cells
  and raises nothing — it returns a tiny population that still looks like a
  measurement. Pinned by a test with two books a second apart.

## 2026-09-01 — OVERTURNED: repairing a lossy artifact does not move a derived number in the "recovering" direction. A truncated file is not a random sample of itself. `[lane game-market-entry-roi-curve]`

**What I expected.** Lane `book-quotes-publish-clobber` found that
`book_quotes` shards LOSE ROWS to a whole-file publish race, and that their
2026-09-01 measurement had run on a copy missing its sportsbook tail (46.1%
matchable). Once `e78aee52` repaired it I told them, in writing, that their
+2.65% "can be re-measured on an intact file" — carrying an unstated assumption
that recovering lost rows would recover lost value.

**What happened.** On the healed shard the gate book roughly doubled (n=653 →
**1,235**) and the number got **WORSE**: gain +0.949pp → **+0.824pp**, ROI
+2.65% → **+2.43%**, shortfall 0.35 → **0.57** points.

**Why, measured rather than assumed.** Split the healed book at the clobbered
copy's last sportsbook quote (20:18:49Z): rows at or before it take the exchange
**64.5%** of the time for **+1.021pp**; the rows the repair restored take it
**40.2%** for **+0.737pp**. The truncation had preserved **exactly the window
where the exchange looks best** — early, pregame, thin sportsbook coverage —
and discarded the late in-play window where it looks worst. **The loss was
biased, in the direction that flattered the conclusion.**

**How to apply.** A lossy artifact loses a STRUCTURED subset — a tail, an hour,
one writer's rows — and that subset has its own statistics. So:
* **Never predict the direction of a repair.** "We lost rows, so the number is
  understated" is a guess with a 50% prior at best. Measure both cohorts.
* **The split is cheap and it is the whole test:** partition the repaired data
  at the loss boundary and compare. One query.
* **A doubled n is not reassurance.** Here n grew 89% and the estimate moved
  against the conclusion; the extra rows were the unfavourable ones.
* Sibling rules: *measure on the BOOK THE DECISION IS ABOUT* and *absence in a
  window isn't absence*. This is the same family — the population you can see
  was selected by something, and here the selector was a race.

## 2026-09-01 — FORBIDDEN: closing or reassigning a lane because its RECORDED SESSION is gone. The session id is not an ownership key — it is a stamp that outlives the thing it names, in both directions. `[lane game-market-entry-roi-curve, ownership pass]`

**The census.** 34 OPEN lanes, **32 already marked UNOWNED**. Checked every
recorded owner session against a 200-session roster (`list_sessions
include_archived=true`) whose oldest entry is **2026-08-13**, i.e. a window
covering every lane in the file, so absence from it is real absence and not a
truncated view. Result: **17 of 18 owner sessions DO NOT EXIST.** The 18th
(`abf487e4`) is archived, last active 2026-08-20. Exactly **one** session in the
entire store was running.

**Why that licenses nothing.** Lane `book-quotes-publish-clobber` records
session `3492626c`, which is NOT FOUND — and that lane was worked **today**: it
landed `51cf8b83`, messaged me about `#630`, and its work is why I re-ran a
measurement this afternoon. The live worker is `local_ea1e4863`, the one running
session. **A lane's recorded session dies and is replaced while the lane keeps
going.** Had the pass closed lanes on "owning session gone", it would have
closed an actively-worked lane holding four file claims.

**The instrument is dead in both directions.** A present id does not prove
ownership either — it proves someone once typed it.

**What the pass found instead, and this is the actionable half.** Classify on
what the lane says about ITS OWN GOAL, which is the thing a lane is for:

    A. header says GOAL MET and nothing owed anywhere ..........  0 lanes
    B. GOAL MET but the block still names owed work ............  4 lanes
    C. no goal-met claim in the header ........................ 32 lanes

**ZERO lanes are closeable on the evidence in the ledger.** Every one either
names owed work or never claimed its goal. So the honest output of an ownership
pass here is a census and two corrections — not closures.

**How to apply.**
* **Never close a lane on liveness.** Close it on its own stated verification,
  and if that verification is missing, the lane's problem is a missing reading,
  not a missing owner.
* **`UNOWNED` means "nobody is holding this right now", not "abandoned".** It is
  an invitation to pick up, and it already appears on 32 of 34 lanes — so it
  carries almost no information and must never be a closure trigger.
* **State the roster window whenever you call a session gone.** "Not in the
  roster" is meaningless without it; here it is 2026-08-13..09-02, ~200 sessions.
* Sibling rule, same family: *a LIVENESS field that the recorder cannot outlive*
  should not be recorded at all. The session id in a lane header is exactly that
  field, and this is the second time it has misled a census.

## 2026-09-02 REQUIRED: a pre-registered falsification test still needs a CONTROL CYCLE before you act on it. One reading on a cadence-driven instrument is not evidence. `[lane kalshi-soccer-club-aliases]`

- **What we believed.** A falsification test written in advance is the honest
  way to hold yourself to a result, so when it fires you act on it. Mine said:
  "`event_not_on_our_board` does not fall, or soccer matches drop — either
  means a pairing is wrong and this reverts."
- **What actually happened.** It fired hard on the first post-deploy cycle:
  `event_not_on_our_board` **314 -> 775** and `soccer_matches` **51 -> 4**, a
  92% collapse, with both denominators moving the WRONG way for a composition
  excuse (kalshi soccer markets 918 -> 948, soccer board rows 1,600 -> 1,565).
  Every aggregate said regression. **The next cycle, with the code untouched,
  read `soccer_matches=52` and `event_not_on_our_board=380`.** The dip was
  slate-state transience on a ~15-minute cadence.
- **Why reverting would have been self-confirming, which is the trap.** Had I
  reverted on the first reading, matches would have returned to ~52 anyway and
  I would have recorded "revert confirmed, the aliases were the cause" —
  a false finding, durably written, with the real change discarded.
- **The rule going forward.** Before acting on a falsification signal from a
  periodic instrument, take ONE more cycle with NOTHING changed. It costs one
  cadence (~15 min here) against a revert-and-redeploy round trip (~45), and it
  is the only thing that separates "my change did this" from "this cycle did
  this". State the control's result beside the signal in `deploys.md`.
- **What made waiting defensible rather than wishful, and this half is not
  optional:** the change was provably ADDITIVE before the deploy — 0 of 34 keys
  were dropped-as-ambiguous by the derived map, 0 were already present, the
  overlay is `setdefault`, no new ambiguity refusals appeared. **A change that
  could plausibly cause the harm gets reverted first and diagnosed after.** The
  control is for changes whose mechanism cannot produce the observed damage.
- **Cost.** None. But the near-miss was a correct change discarded plus a wrong
  cause recorded as fact — on a money-adjacent join, in a ledger read as evidence.

## 2026-09-02 REQUIRED: before calling a thin downstream count a COVERAGE DEFECT, find the counter that ACCOUNTS for the gap and read the code that increments it. A deliberate quality filter and a broken pipeline look identical from the downstream end. `[lane kalshi-soccer-club-aliases -> finding soccer-board-coverage]`

**Measured.** Kalshi lists 171 open soccer fixtures; our board carried 28. That
reads as a coverage bug and the obvious next lever is "fix the board's soccer
fixture coverage". It is not a bug. One read of `/api/board/layer2-shortlist`
showed soccer selecting **1,547** rows with **129** reaching the board (8%),
against mlb 95% and ncaaf 100%, and the accounting counter in the SAME payload
was `rows_uninformative_ev = 1547` -- exactly soccer's selected count.

`_row_ev_is_hold_restatement` drops a row whose `ev_pct` is arithmetically the
book's own margin: a one-sided market is priced `fair = implied x (1 - hold)`,
`expected_value_pct` is `fair/implied - 1`, so the price CANCELS and EV is
`-hold` for every such row **regardless of the bet**. Ranking on it ranks on
WHICH BOOK QUOTED. It fires only where the row has no model view, and soccer has
none by the recorded `soccer-model-dispersion` decision (model worse than market
in 8 of 9 leagues; publishing `model_edge_pct` declined). Every link deliberate.

**Why this rule and not just "check first":** the two available "fixes" were
publishing a model edge the model has not earned, and exempting soccer from the
filter -- which puts ~1,400 rows ranked on the book's margin onto a
money-adjacent board, against that filter's own evidence that 2,611 such rows
topped out at -4.73 while the live shortlist's #50 was +0.64. **A coverage fix
that removes a correct filter is indistinguishable from success at every level
except the money.** It would have looked like a win: more rows, more fixtures,
more Kalshi matches.

**How to apply.** (1) Read the per-stage counters in the response you already
have before theorising -- one of them usually equals the gap. (2) Then read the
FUNCTION that increments it, not its name. (3) A filter whose threshold derives
from the same quantity it filters on cannot be tuned around: soccer's value
floor was `-8.1425 = -1.25 x 6.514` against rows whose EV IS `-6.514`. (4) If
the filter is right, the lever is upstream of it -- here, giving soccer a model
view worth ranking on. THIRD requested fix in one session that was already
working as designed; the other two would merely have shipped inert.

## 2026-09-02 FORBIDDEN: measuring a change by REPLAYING IT WITHOUT AN ARGUMENT PRODUCTION ALWAYS PASSES. The replay then measures a different system, and its null result is not about your change. `[lane kalshi-soccer-club-aliases]`

**Measured.** To read whether 34 new club aliases helped, I replayed the resolve
step on a stable slate and got `resolved=9, delta=+0` -- a clean null that would
have justified reverting a shipped change. The replay omitted `code_names`,
which production ALWAYS passes to `match_event_blob`; without it the code path
that the aliases feed is not the path being exercised. Redone with production's
arguments: **22 attempted/resolved WITH the aliases against 21 WITHOUT, +1.**

Small, but the sign flipped, and the wrong sign here pointed at reverting.

**How to apply.** Before trusting a replay harness, diff its call site against
the PRODUCTION call site argument by argument -- optional/defaulted parameters
are exactly where this hides, because the replay still runs and still returns a
number. Sibling of "confirm the code ran": assert you are on the branch
production takes, not merely that something executed.

## 2026-09-02 REQUIRED: a SIZE warning measured from the working tree is a statement about YOUR CHECKOUT, not about the ledger. Read the file at `origin/main` before trimming it. `[ledger trim pass]`

**Measured.** The session-start digest said `LEDGER OVER BUDGET: lanes.md
246KB>234KB, learnings.md 286KB>273KB`, and I relayed those numbers as real
pressure. At `origin/main` the same files were **144KB/240KB and 270KB/280KB --
both UNDER cap, and they had been for some time.** `session-start.sh` stats
`.syndicate/*` in the PRIMARY SHARED TREE, which was **131 commits behind**;
upstream had already moved ~122KB of lane blocks into `lanes_history.md` and the
stale checkout still carried every one of them. The warning was true of the
bytes on that disk and false of the ledger.

**The trap is that trimming "works".** The tools would have run, the file would
have shrunk, and the warning would have cleared -- while the actual defect (a
checkout that stale is also serving STALE LANE STATUS to every session that
starts there) went untouched and unreported. A remedy that silences the symptom
is indistinguishable from a fix until someone reads the lane they thought was
open.

**What was really available**, after running every tool against `origin/main`:
`trim_lane_blocks.py` 4,518 B (one block, a lane I had closed myself),
`archive_released_lanes.py` the same block, and `compact_learnings.py`
0 bytes at every cutoff through 2026-09-01.

**CORRECTION, same day, and it is the more useful half.** I reported that last
figure as "already fully compacted, no lever left". It is literally true and
materially misleading -- I stopped testing one day short. `compact_learnings.py`
compacts entries strictly BEFORE `--keep-from`, so a cutoff of `2026-09-01`
cannot touch 2026-09-01's own 16 entries. `--keep-from 2026-09-02` reclaims
**27,669 bytes**; `2026-09-03` reclaims 32,624. **The lever LAGS BY A DAY BY
DESIGN and I read the lag as its absence.** Generalise it: when a tool takes a
cutoff, a null result at the boundary is a statement about the boundary, not
about the tool -- step the parameter one unit further before concluding
anything.

**How to apply.** (1) `git show origin/main:<path> | wc -c` before acting on any
digest size number, and check `git rev-list --count HEAD..origin/main` while you
are there. (2) Dry-run every tool and read the RECLAIMED figure before choosing
one -- three tools here, two of them with nothing to do. (3) Do not shrink
`lanes.md` by closing lanes whose sessions are gone: that is FORBIDDEN by the
2026-09-01 rule, and size is not a reason to reassign someone's work.
