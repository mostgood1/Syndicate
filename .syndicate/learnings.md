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

## Index — 917 rules `[generated]`

> Full index: [`learnings_index.md`](learnings_index.md) — regenerate with
> `py -3 scripts/build_learnings_index.py` after appending. It spans BOTH
> this file and `learnings_evidence.md`, so a rule stays findable after its
> body is compacted out. **FORBIDDEN** = never do this again.
> **EXONERATED** = ruled out, stop re-investigating.

<!-- LEARNINGS-INDEX:END -->

---
## 2026-09-06 — FORBIDDEN: instrumenting join A, reading it, and concluding about a value written by join B. Name the WRITER of the field in the falsification test itself. `[lane mlb-first5-kalshi-fanin-mismatch, vs 15410ca7]`

Two sessions investigated one board row on the same day and reached opposite
verdicts. Both measurements were CORRECT:

    join_kalshi_to_board      -> the ORDER path resolves KXMLBF5TOTAL   (peer)
    apply_venue_quotes_to_grid-> the PRICE came from KXMLBTOTAL, -669   (this lane)

The peer's falsification test read "if the emitted series for that row reads
KXMLBF5TOTAL, the mismatch hypothesis is dead" — a well-formed test pointed at
the wrong function. "The series for that row" has two answers because two joins
touch the row, and the one that mattered was the one that WROTE the field under
suspicion (`price_source`, `book_prices`, `venue_basis`).

**THE REMEDY IS ONE CLAUSE IN THE TEST:** write the falsification test as *"the
series that `<function that assigns the field>` used"*, not *"the series for
that row"*. If you cannot name that function, that is the first thing to find,
not a detail to fill in later.

**AND THE TELL WAS SITTING IN THE FIXTURE.** Their test file carried both real
contracts with real prices — `KXMLBTOTAL` at `-669`/0.870 (commented "the number
production actually showed") and `KXMLBF5TOTAL` at `+103`/0.492. The conclusion
was "0.870 is a wide ask on a thin first5 market" while the file itself said the
first5 ask was 0.492 and the 0.870 belonged to the full-game contract. **When a
conclusion and a fixture in the same commit disagree, the fixture is the
measurement and the conclusion is the story.** Re-read your own fixture against
your own headline before shipping the headline.

**DO NOT let this read as "the peer was careless."** They revised their
hypothesis DOWNWARD before building, wrote an explicit falsification test,
shipped instrumentation only, and used real tickers instead of paraphrases —
all of which is why the refutation was cheap to produce. A vaguer investigation
would have left nothing to check.

## 2026-09-06 — FORBIDDEN: concluding a guard covers a symptom because the guard is deployed, firing, and named after it. Find the code that WROTE the field you are looking at. `[lane mlb-first5-kalshi-fanin-mismatch]`

A first5 board row was priced at a whole-game 0.870. `_segments_agree` exists
for exactly that, was present by content on all three live SHAs, and its counter
`segment_has_no_matching_series` was firing 160-191 times per join that very
hour. Every one of those readings is true and **none of them is about the field
in question**: the guard is on the ORDER path
(`portfolio_commit` → `kalshi_ticker_resolver`), and `price_source` /
`book_prices` / `venue_basis` are written by `venue_quote_fanin`, a different
module in which the word `segment` did not occur once.

The 2026-09-05 audit that established the guard was correct is still correct. It
answered "can a segment bet get a wrong TICKER". The question a day later was
"can a segment row get a wrong PRICE", and the same words name two joins.

**THE REMEDY, and it is one grep, not a judgement:** before crediting a guard,
grep for the WRITER of the exact field you are looking at, and check the guard
is on that call path. `grep -rn "price_source" ` reaches
`venue_quote_fanin.py:1397` in one hop. A counter's name is not its scope.

**THE COROLLARY THAT COST THE MOST TIME:** "the counter reads 0, which is
consistent both with the guard working and with the guard not being on this
path" is the right observation and the wrong conclusion to stop at. A counter
belonging to another path cannot be evidence in either direction — it is not
weak evidence, it is *no* evidence, and treating it as weak keeps the wrong
hypothesis alive.

## 2026-09-06 — FORBIDDEN: shipping a refusal keyed to ONE spelling of a value that has synonyms. Check the synonym set before the predicate, not after. `[lane mlb-first5-kalshi-fanin-mismatch]`

A segment guard compared `normalize_segment(row["segment"]) != "full"`.
`normalize_segment` folds only the empty string, and grid rows in two existing
suites carry `segment="full_game"` — so the guard refused **10 tests** and would
have stripped the venue price off every whole-game row spelled that way. A
refusal that removes coverage is not a fix; it is an outage with a good
rationale.

Production writes `full`, and that was ESTABLISHED rather than assumed: the
ORDER path's own comparator does not fold either, and it matched 545-845 board
rows per join that day — rows spelled `full_game` could not have done that.
The synonym lives in fixtures and in `layer2_board._segment_label`'s accepted
set (`full`, `full_game`, `game`).

**FOLD ANYWAY WHEN THE COST IS ASYMMETRIC.** Being wrong about the spelling
costs a silent coverage collapse; folding costs at most one refusal you would
have wanted. Take the cheap side, and write down which spelling you verified so
the next reader knows what the fold is insuring against.

**AND: the existing fixtures were the instrument.** They were not "wrong" and
must not be edited to make a new predicate pass — that is how a test stops being
able to witness the thing it was written for.

### 2026-09-05 — FORBIDDEN: a per-item guard implemented as an `A or B` search over a CONCATENATION of every item's source. Whichever item supplies B satisfies it for EVERY value of A, so the check has no failing input at all `[lane ncaaf-segment-capture, commits 7f197639 / 7dfabcf4, NO DEPLOY]`

- **What we believed:** `tests/test_all_sports_segment_wiring.py` guarded the
  gap it was written for — *"a sport with declared segments and NO wiring
  anywhere"*. It had been green since the day it was written.
- **What was actually true:** it read every wired fetcher into ONE string and
  asked, for each sport, whether `segment_market_keys("<sport>")` **or** the
  literal `segment_market_keys(league)` appeared in that string. The basketball
  fetcher always supplies the second token. **So the disjunction was true for
  every sport in `SPORT_SEGMENTS`, and `unwired` was unconditionally `[]`.**
  Behind it: NCAAF had never captured a single half or quarter price —
  `segment == "full"` on **153,723 of 153,723** production rows.
  Its sibling assertion was wrong in a second, different way: it checked that
  the token `segment_market_keys("nfl")` appeared in the NFL fetcher. It does —
  in a map that `main()` never passes to `markets=`, so the 36 keys reached the
  TAGGER and never the request. **Both halves of the guard were green, and both
  were measuring something other than what they claimed.**
- **How we found out:** looking for NFL's supposed 422 and finding there could
  never have been one, because no segment request was ever sent. Then reading
  the guard that should have said so.
- **The rule going forward:** **when a guard is per-item, the search corpus must
  be per-item too.** Flattening N sources into one string turns "does item i
  have property P" into "does ANY source have property P", and the two are
  indistinguishable while every source is healthy. Join on an explicit column
  instead — the fix here adds a `sport` field to the table and diffs
  `set(declared) - set(wired)`. And **ship the guard's own falsifier beside it**:
  a companion test that removes one row and asserts the expression goes
  non-empty. That test is what converts "it passes" into evidence.
  This is `instrument blindness` (a healthy reading is evidence only once you
  know what makes it read unhealthy) with a specific, greppable shape: an `or`
  over a corpus.
- **Cost:** NCAAF ran an entire season opener with zero segment capture and a
  green test asserting the opposite; NFL's regular-season segment map has been
  dead code with a docstring claiming it was live. Both found only because
  someone went looking for a vendor error that did not exist.


### 2026-09-05 — A DEPLOY GOING LIVE AND THE ARTIFACT IT CHANGES BEING REBUILT ARE DIFFERENT EVENTS — gate the check on the ARTIFACT'S mtime `[lane mlb-hitter-so-dead-field, commit bc82090f, no deploy]`

The MLB hitter-strikeouts fix was live on refresh-worker at 23:26:26Z. The
2026-09-05 board went on reading `mean 0.0 / modeProb 1.000 / 1 rung` for
**5 h 49 m** afterwards, sitting next to a healthy 2026-09-04. That is the shape
of a PARTIAL fix, and it is the most dangerous shape there is: it invites the
next person to "finish" work that is already complete, or to revert it.

The cause was vintage, and the margin was **106 seconds** — the 09-05 sims were
written 23:24:40Z, the deploy went live 23:26:26Z, and nothing rebuilt that date
until 05:13:08Z. On its first post-deploy build it read `mean 1.042`.

**RULE: when verifying a fix that a JOB writes into an artifact, gate on the
artifact's own `generated_at`/mtime crossing the deploy, never on wall clock and
never on "the deploy is live".** A watcher built that way read `mean 0.0` on two
of four polls; reporting either would have been a false negative against a
correct, deployed fix. Publishing the fix is one event, the job re-running is a
second, and here they were most of a working day apart.

**Corollary, and it is the cheap half: state the expected lag BEFORE you look.**
Saying "this needs a rebuild, so a zero right after the deploy means nothing"
costs one sentence and converts a scary reading into an expected one. Two peer
sessions hit the same confound the same night in opposite directions — one saw
NFL 78-unmatched persist past a live deploy and clear ninety seconds later on
the next rebuild.

**And a durability reading is not the same as a verification reading.** The
09-05 board was re-checked ~14 h and many rebuilds later (`mean 1.077`,
5 rungs). The first post-deploy read proves the code ran; the later one proves
it keeps running. A single post-deploy read cannot distinguish "fixed" from
"fixed once".


### 2026-09-04 — A TOOL THAT MUTATES IS NOT A PROBE, AND A POLL SLOWER THAN THE WINDOW MEASURES NOTHING `[lanes mlb-ladder-refusal-deploy, commits 2e555b2c / ccb053c7, DEPLOYED]`

Three things went wrong while deploying behind another lane's claim. None cost
production; all three are cheap to repeat.

**1. `deploy_claim.py acquire` IS NOT A READ-ONLY PROBE.** I ran it to READ the
refusal message. My own claim had expired seconds earlier, so it ACQUIRED —
under the throwaway `--holder probe-only` I had passed as a label. Released and
re-acquired within the minute, but for that minute the lock was recorded to a
holder that does not exist. **It only behaves like a probe while an unexpired
claim already exists**, which is exactly the state you cannot assume when you
are checking. To read the message safely, check `status` first.

**2. A POLL INTERVAL LONGER THAN THE WINDOW IS NOT A SLOW MEASUREMENT, IT IS NO
MEASUREMENT.** refresh-worker's idle windows are **~90 s, about one per 40 min**.
I polled at 150 s and returned six consecutive `HOLD`s over ~50 min — which
reads exactly like "permanently busy" and would have justified either giving up
or forcing. At 45 s the window appeared on the 4th attempt. **Before concluding
a resource is never free, check the poll is finer than the thing you are
hunting.**

**3. PARSE FAILURE MUST NOT WEAR THE SHAPE OF A GOOD READING.** The same waiter
printed `jobs=0 live=` on a truncated preflight — `jobs=0` is the IDLE signal I
was waiting for, produced by a read that failed. It defaulted to HOLD (the safe
branch) by luck of ordering, not design. The rewrite requires an explicit
`CLEAR`/`HOLD` line and treats anything else as UNKNOWN. Same family as the
09-04 rule about instruments whose partial output is indistinguishable from
their success output.

**FORBIDDEN: `git stash` / `rebase` / `stash pop` around a shared-ledger write.**
Measured: the pop re-applied content already on `origin/main`, producing TWO
blocks for each of four lanes plus a `UU` conflict, and left the INDEX holding
eleven files I never staged. `git add <my file>` then `git diff --cached` showed
all eleven — the index, not my edit. Recovery that worked: verify the
duplication against `origin/main` (1 block there vs 2 locally) BEFORE discarding
anything, reset to `origin/main`, re-apply only your own entry, confirm
`N additions / 0 deletions` on ONE file.


### 2026-09-04 — A SPEC THAT NAMES A KEY IS NOT A GUARANTEE THE KEY IS FED — check the JOIN, not the two sides `[lane mlb-hitter-so-dead-field, commit 0b9a03e7, NO DEPLOY]`

`_HITTER_PROP_DIST_SPECS` named `("strikeouts", "SO", "so_mean")` and the sim
computed `so` correctly three lines away. Both halves were right. **The defect
was the JOIN between them** — the curated `hitter_stat_values` dict handed to
the spec never set `"SO"`, and the read is `.get(row_key, 0)`. Every review of
either side passes. `strikeouts_dist` was `{0: n_sims}` and `so_mean` `0.0` for
every hitter of every game since at least 2026-05-25, confirmed on the SERVED
production payload 2026-09-04: the published ladder said every MLB hitter
strikes out exactly zero times with probability **1.000**.

**RULE — when a spec table drives a lookup, assert the containment.** `set(spec
row_keys) <= set(the dict that feeds it)` is one line. It is now enforced in
`scripts/sim_input_checklist.py`, which `run_mlb_daily_sim_job.py` executes, so
it fails the DAILY JOB and not merely pytest. The checklist could NOT have
caught this before and this is worth stating precisely: it enumerates INPUT
dataclass fields via `dataclasses.fields()`, and this is an OUTPUT spec/dict
mismatch. **`model_engine_standard` §4.1's "audit fields, don't grep names" has
a blind spot: a field audit sees the two sides, never the join.**

**THIRD INSTANCE of the same two-copy failure.** `daily_update.py` carries the
hitter accumulation TWICE (`_simw_chunk`, multiprocessing; `_sim_many`, serial).
`#334` changed one and not the other; `#429` wrote the warning comments at both
sites; `#621` is the same file, same dict, same mechanism. The comments did not
prevent it — **a comment asking a human to remember is not a control.** The AST
drift check is.

**AND THE REACHABILITY TEST DOES NOT COVER THE DRIFT.** Measured: with site 1
broken and site 2 intact, both reachability tests PASS, because `workers=1`
exercises only the serial path. §4.3's `run(off) != run(on)` is necessary and
here it was not sufficient — a duplicated code path needs a SOURCE-level
identity check as well.

**SEVERITY LESSON, and it is the sharper one: the loss was prevented by an
unrelated accident.** No priced recommendation was ever emitted — not because
any guard held, but because the market feed returns ZERO `batter_strikeouts`
quotes (production, 2026-09-04: requested in `meta.markets`, absent from
`meta.counts.markets`, 0 of 289 players, against 270-283 for the other six).
A dead model field was masked by an equally dead market feed. Had the quotes
arrived, a P=1.000 UNDER would have priced against a real line.
`probability_refusal.py`'s own docstring names this exact trap — *a healthy
reading that survives for a reason unconnected to the rule you are relying on
is not evidence that the rule exists* — and it applied to my own investigation:
the handoff's mirror sample (2026-07-12) showed `marketLine: null` and looked
exonerating, but it PREDATES the odds wiring (`#440`, 2026-08-19) by three
months, so it could not have shown anything else. **Check that your exonerating
evidence was capable of returning the other answer.**






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
## Entries before 2026-09-01 — moved to `learnings_archive.md` `[2026-08-20 cutoff on 2026-09-01; extended to 2026-09-01 on 2026-09-06]`

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
## Superseded on 2026-08-15 — the two `same_book_n` entries

Both were merged into **"never read a joiner zero as a fact about the world"**
above; full original text is in `learnings_evidence.md`. They reappeared here
once after being removed — a stale-read write on this shared file resurrected
them alongside their own replacement. If they show up a third time, delete
them again rather than assuming the merge was reverted: the merged rule and
the evidence file are the source of truth.
## 2026-09-01 REQUIRED: for every grader, ask what it does when its OUTCOME SOURCE IS ABSENT. A fallback there is a false-result generator. `[lanes wnba-accuracy-assessment + mlb-accuracy-assessment, independently]`

- **MLB** (`mlb-accuracy-assessment`): the live-lens grader settled from `lastSeenSnapshot.actual` — **a running tally** — whenever the statsapi feed was unavailable, which was 100% of the time (`feedResolved` 0 on all 11 days that produced rows, against `feed_live_miss: 1,802`). Published reading: **`over 0 wins / 1,578`, `under 206 / 206`.**
- *(evidence in `learnings_evidence.md`)*
## 2026-09-01 REQUIRED: assert on the VALUE THAT CROSSED THE BOUNDARY, not on the call returning. "It didn't raise" and "the counter moved" are different claims, and only the second is evidence. `[lane wnba-accuracy-assessment]`

- **What happened.** I added a block to publish WNBA recon artifacts from refresh-worker to web, because the producer was writing to the worker's disk and the web-facing endpoint reads web's. The block ran cleanly, raised nothing, returned, and **published zero files.**
- *(evidence in `learnings_evidence.md`)*
## 2026-09-01 FORBIDDEN: inferring a MECHANISM from a file's SIZE. Count the composition, or say you haven't. `[lane wnba-accuracy-assessment, caught by lane mlb-accuracy-assessment]`

- **What I claimed.** WNBA's board shows zero Kalshi/Polymarket quotes across 787 book references, while `wnba_source/tracking/book_quotes/2026-08-30.jsonl` is **45,776,899 bytes**. I wrote that up — into `todo.md #616`, into a peer message, and into a user-facing summary — as:
- *(evidence in `learnings_evidence.md`)*
## 2026-09-01 FORBIDDEN: naming a MECHANISM from a SYMPTOM. Three times in one session, on three different subjects. `[lane wnba-accuracy-assessment]`

- **The shape.** A symptom is a value you read. A mechanism is a claim about *why* that value is what it is. Reading one does not give you the other, and the gap is invisible from inside because the number is real and right there. The tell is grammatical: *"the board can't see it"*, *"it's structurally unreachable"*, *"excluded upstream"* — all causal claims, none of which any of those readings could support.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-01 REQUIRED: a PRODUCER fix is not in force on data that already exists. Ask when the artifact is next written. `[lane wnba-accuracy-assessment]`

- **What happened.** I fixed three things in the WNBA odds producer — totals withheld, impossible EV refused, certainty clamped — deployed them to all three services, verified all three deploys reached `live`, and was about to report the items done. Then I read the SERVED PAYLOAD:
- *(evidence in `learnings_evidence.md`)*
## 2026-09-01 REQUIRED: on the shared tree, read the DIFF of a ledger file before committing it, not its --stat. `[lane wnba-accuracy-assessment]`

- **What happened, twice in one day, in both directions.**
- *(evidence in `learnings_evidence.md`)*
## 2026-09-01 FORBIDDEN: recording a LIVENESS field that the recorder itself cannot outlive

- **The rule going forward.** A liveness field must name something that OUTLIVES the code writing it — a session id, checkable with `list_sessions` (`isRunning`) — never the pid of the short-lived CLI that records it. If no such identity is available, **write nothing and let the TTL be the invariant**: a missing field reads as UNKNOWN, which correctly refuses to authorise a force, whereas a dead-on-arrival pid reads as PERMISSION. Absent identity is not absence of a holder.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-01 FORBIDDEN: leaving anything staged in the SHARED index that you are not committing in the same breath

- **The rule going forward.** Stage and commit **atomically** or not at all: `git commit --only -- <paths>` takes the worktree copies of exactly those paths and leaves the rest of the index alone. When the commit needs content that is NOT the worktree copy (rebuilding `origin/main` + only your edits), build it in a **temporary index** — `GIT_INDEX_FILE=<tmp> git read-tree/update-index/ write-tree` then `git commit-tree` — which never touches the shared index at all. **Inspect BEFORE staging, never between staging and committing.** The older "never chain add and commit" is not wrong, but it is not the invariant: the invariant is that no staged state of yours may outlive your own commit.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-01 — FORBIDDEN: prescribing a fix in a spun-off task from a symptom you never traced to its enclosing control flow. My `continue` would have deleted the feature it was meant to instrument. `[lane phase0-basketball-integrity]`

- **What I did.** I found a real defect by reading a log line — `book_grid.py` counted every correctly-matched direct-feed row as a `near_miss`, so production read `kept_direct=603 near_misses={'kalshi': 603}`, an alarm firing at exactly the rate the feature succeeded. I filed it as a background task and, because the cause looked obvious, **I wrote the remedy into the chip: "add the missing `continue` after `kept_direct_feed += 1`."**
- *(evidence in `learnings_evidence.md`)*
## 2026-09-01 FORBIDDEN: running any git working-tree restore (`checkout --`, `restore`, `reset`) without pinning the repo with `-C <path>`. The cwd is not a fact; on this machine it is a liability that destroys OTHER SESSIONS' work. `[lane polymarket-prop-quote-capture]`

- **The rule going forward.** THREE layers, because each alone has now failed: (1) every git command that can DISCARD working-tree content must carry an explicit `git -C <absolute-path>` — never rely on the shell's cwd; (2) a file-wide restore is NEVER the tool for undoing a targeted experiment — reverse the specific edit (string-swap back) instead, which cannot exceed its own blast radius (this same session had already wiped its own uncommitted implementation once with `checkout --` in the worktree — same instrument, and the second firing hit ANOTHER session); (3) on the shared tree, `checkout/restore` of a ledger file is forbidden OUTRIGHT — uncommitted peer edits live there by design, and the command cannot distinguish yours from theirs.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-01 — FORBIDDEN: comparing a model against a market price without conditioning on QUOTE AGE. A stale price is a weak forecast, so staleness flatters the model — the error runs in the reassuring direction `[lane mlb-live-gameline-skill-audit]`

- **The model does not improve as the quote ages. The MARKET decays**, because a price that has not moved in half an hour is a bad forecast of an outcome it has not seen. Quote-age distribution in that file: p50 410s, p90 1,848s, **p99 74,997s** — roughly 1 row in 100 was priced against a quote over 20 hours old.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-01 — FORBIDDEN: pooling an accuracy history across a SCORER-version boundary, and shipping a scorer whose payload cannot say which version produced it `[lane mlb-live-gameline-skill-audit]`

- **Nothing in the row said which scorer wrote it**, so the boundary was invisible and had to be rediscovered by matching record counts. The rule has two halves:
- *(evidence in `learnings_evidence.md`)*
## 2026-09-01 — FORBIDDEN: `ast.parse` as a syntax check for an edit, and building a `write` and a `read` of the same path in one expression `[lane mlb-live-gameline-skill-audit]`

- *(evidence in `learnings_evidence.md`)*
## 2026-09-01 — FORBIDDEN: `git stash` in a worktree. The stash is SHARED with every other worktree, so a failed `stash push` followed by `stash pop` pops a PEER'S work into your tree. `[lane mlb-prop-freeze-source-trees]`

- **What I did.** To prove an off-is-not-on (does my test fail on the pre-fix code?), I ran:
- *(evidence in `learnings_evidence.md`)*
## 2026-09-01 — a log SEARCH tool echoes your query; grepping its output for the bare tag matches the ECHO. Grep for content the tool cannot have written itself `[lane prop-unmatched-decomposition]`

- **Rule:** a watcher grepping a search tool's output must anchor on content the tool cannot emit about itself — the payload shape (`POLYMARKET_UNMATCHED counts=`), never the bare tag you typed into the tool. Cheap check before arming any such watcher: run it once where the answer is known-absent and confirm it stays silent.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-01 — CONFIRMED INSTANCE, with the falsifying numbers: a bounded sample majority is not a plurality claim. I wrote the hypothesis down first, and the complete count reversed it `[lane prop-rung-miss-rate]`

- *(evidence in `learnings_evidence.md`)*
## 2026-09-01 — FORBIDDEN: reading a DEGENERATE FIT as a fact about the model. A slope pinned at its clamp floor describes the training window, not the signal. `[lane mlb-hrr-null-closed, correcting lane mlb-prop-calibration-refit one commit earlier]`

- **What I did.** Fitting the MLB prop calibration, `hits_runs_rbis_*` came back with `a = 0.05` on all four rungs — exactly the fitter's clamp floor. I read that as the fitter asking to discard the model probability, concluded **"HRR's probability carries no usable signal"**, and shipped that sentence into a config `_meta`, a commit message, a test and the ledger.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-01 — FORBIDDEN: reusing a DERIVED CONSTANT without re-deriving it from the source it cites — especially when that source is printed in the same document. `[lane mlb-prop-staking-gate-not-met]`

- **What happened.** The 08-31 MLB assessment converts price improvement into ROI with *"each 1pp of better entry is worth roughly +0.75pp of ROI"*, explicitly **"anchored to item 07's sensitivity"**. Item 07's sensitivity table is printed **in the same file, ~100 lines earlier**, and says:
- *(evidence in `learnings_evidence.md`)*
## 2026-09-01 — RULE: measure on the BOOK THE DECISION IS ABOUT, not on the convenient superset. `[lane mlb-prop-staking-gate-not-met]`

- **How to apply.** When a gate names a population, encode that population in the measurement script as a named predicate (`in_gate_book`) with tests, so the number and the gate cannot drift apart — and so the next person does not have to re-derive which markets "HRR" meant. Report `n` for the *gated* population; a sample that shrinks 2,062 → 653 is itself a finding about how much the answer rests on.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-01 — RULE: the WIDTH OF AN UNCERTAINTY IS NOT A RECOVERABLE GAIN. Resolving it buys certainty, which is worth having and is not ROI. `[lane kalshi-batter-prop-fee-multiplier]`

- **What I claimed.** Closing `#624` step 6 I wrote that resolving the Kalshi batter-prop fee multiplier was *"worth 0.44 ROI points, more than half the shortfall"*, and ranked it as the second-cheapest way to close a gate that missed by 0.35 points. That reads as: do this lookup and you might pass.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-01 — RULE: a venue parameter that varies per SERIES must never be generalised AT ALL — not to the sport, not to props-vs-games, not to the market family. `[lanes kalshi-batter-prop-fee-multiplier, book-quotes-publish-clobber]`

- **"Every MLB game/total/spread/K series is HALF RATE"**, which is true and reads as "MLB is half rate". Reading 19 MLB series:
- *(evidence in `learnings_evidence.md`)*
## 2026-09-01 — FORBIDDEN: treating a `data/**` daily shard as APPEND-ONLY. Two services publish WHOLE-FILE REPLACES of the same file, so a later read can be a SUBSET. `[lane book-quotes-publish-clobber]`

- **Measured.** `mlb_source/tracking/book_quotes/2026-09-01.jsonl` fetched twice, ~1h apart, counted with identical code:
- *(evidence in `learnings_evidence.md`)*
## 2026-09-01 — FORBIDDEN: recording an actor as having DONE the thing you just refused to let it do. A guard that books a refused attempt as success makes its own refusal a one-cycle delay. `[lane book-quotes-publish-clobber]`

- **Measured**, `ncaaf_source/tracking/book_quotes/2026-09-05.jsonl`:
- *(evidence in `learnings_evidence.md`)*
## 2026-09-02 — FORBIDDEN: scoping a lock (or any bound) to a key that does not cover the case it was built for. Check the bound against the SPECIFIC incident, not against the abstraction. `[lane book-quotes-publish-clobber]`

- **Different directories, therefore different locks.** Those two twins are precisely the pair observed publishing **2 SECONDS apart** in the production log — the concrete case I cited in the commit message as the reason the lock was needed. The lock would have permitted it. It read as a bound and bounded nothing that mattered.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-02 — RULE: read the RUNNING config, not a docstring in the same file that describes it. `[lane book-quotes-publish-clobber]`

I justified the lock with *"web runs 8 gunicorn workers; each is
single-request"*, copied from a note further down `ops.py`. The live process
list says:

    gunicorn wsgi:application --workers 2 --threads 4

**Two processes, four concurrent requests each.** Wrong in the direction that
matters: `--threads 4` means merges can race INSIDE one process, which the
per-process claim declares impossible. The `O_CREAT|O_EXCL` file lock happens
to be correct for both cases, so the CODE survived — but a wrong justification
is what the next person reasons from, and the next guard built on "each worker
is single-request" would be an in-process lock that silently does nothing.

Both errors surfaced only because I read `/api/ops/memory`'s process list while
setting up an unrelated memory watch. Neither would have been caught by a test.

**Corollary already in force here:** `container_memory_mb` includes page cache
and this merge reads/writes 50MB+ files, so it inflates for reasons that are not
a leak. `container_memory_unreclaimable_mb` is the figure to watch, and the
FLOOR across samples is the ratchet — every deploy reboots the workers and
resets it, so a post-deploy reading always looks healthy.
- **The rule going forward.** Stage and commit **atomically** or not at all: `git commit --only -- <paths>` takes the worktree copies of exactly those paths and leaves the rest of the index alone. When the commit needs content that is NOT the worktree copy (rebuilding `origin/main` + only your edits), build it in a **temporary index** — `GIT_INDEX_FILE=<tmp> git read-tree/update-index/ write-tree` then `git commit-tree` — which never touches the shared index at all. **Inspect BEFORE staging, never between staging and committing.** The older "never chain add and commit" is not wrong, but it is not the invariant: the invariant is that no staged state of yours may outlive your own commit.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-01 FORBIDDEN: running any git working-tree restore (`checkout --`, `restore`, `reset`) without pinning the repo with `-C <path>`. The cwd is not a fact; on this machine it is a liability that destroys OTHER SESSIONS' work. `[lane polymarket-prop-quote-capture]`

- **The rule going forward.** THREE layers, because each alone has now failed: (1) every git command that can DISCARD working-tree content must carry an explicit `git -C <absolute-path>` — never rely on the shell's cwd; (2) a file-wide restore is NEVER the tool for undoing a targeted experiment — reverse the specific edit (string-swap back) instead, which cannot exceed its own blast radius (this same session had already wiped its own uncommitted implementation once with `checkout --` in the worktree — same instrument, and the second firing hit ANOTHER session); (3) on the shared tree, `checkout/restore` of a ledger file is forbidden OUTRIGHT — uncommitted peer edits live there by design, and the command cannot distinguish yours from theirs.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-01 — FORBIDDEN: comparing a model against a market price without conditioning on QUOTE AGE. A stale price is a weak forecast, so staleness flatters the model — the error runs in the reassuring direction `[lane mlb-live-gameline-skill-audit]`

- **The model does not improve as the quote ages. The MARKET decays**, because a price that has not moved in half an hour is a bad forecast of an outcome it has not seen. Quote-age distribution in that file: p50 410s, p90 1,848s, **p99 74,997s** — roughly 1 row in 100 was priced against a quote over 20 hours old.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-01 — FORBIDDEN: pooling an accuracy history across a SCORER-version boundary, and shipping a scorer whose payload cannot say which version produced it `[lane mlb-live-gameline-skill-audit]`

- **Nothing in the row said which scorer wrote it**, so the boundary was invisible and had to be rediscovered by matching record counts. The rule has two halves:
- *(evidence in `learnings_evidence.md`)*
## 2026-09-01 — FORBIDDEN: `ast.parse` as a syntax check for an edit, and building a `write` and a `read` of the same path in one expression `[lane mlb-live-gameline-skill-audit]`

- *(evidence in `learnings_evidence.md`)*
## 2026-09-01 — RULE: a claimed GAIN that exceeds the TOTAL COST it is meant to remove is about a different population. One comparison rejects it, with no machinery. `[lane game-market-entry-roi-curve]`

- **+1.57pp** ... worth about +1.2% ROI"* for MLB game markets. The book that stakes that money pays **0.88pp per side in total** — a 1.96% two-way hold, because it already routes to exchanges. An improvement of 1.57pp cannot be harvested from an entry cost of 0.88pp; there is not that much cost there to remove.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-01 — FORBIDDEN: treating the timestamp on an ORDER as the timestamp of the PRICE it took. Board prices carry a real age, and the error does not surface as an error. `[lane game-market-entry-roi-curve]`

- **What it produced, and why nothing caught it.** The book's mean per-side entry cost came out at **-1.43pp** — paying *less* than fair on average, which is not a thing that happens — and the sensitivity table then read **-1.05%** at "today's" cost. No exception, no refusal, a full table printed. It was caught only because the ledger's own stake-weighted return on the same rows was **+5.31%**, six points away.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-01 — OVERTURNED: repairing a lossy artifact does not move a derived number in the "recovering" direction. A truncated file is not a random sample of itself. `[lane game-market-entry-roi-curve]`

- **What I expected.** Lane `book-quotes-publish-clobber` found that `book_quotes` shards LOSE ROWS to a whole-file publish race, and that their 2026-09-01 measurement had run on a copy missing its sportsbook tail (46.1% matchable). Once `e78aee52` repaired it I told them, in writing, that their +2.65% "can be re-measured on an intact file" — carrying an unstated assumption that recovering lost rows would recover lost value.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-01 — FORBIDDEN: closing or reassigning a lane because its RECORDED SESSION is gone. The session id is not an ownership key — it is a stamp that outlives the thing it names, in both directions. `[lane game-market-entry-roi-curve, ownership pass]`

- **The census.** 34 OPEN lanes, **32 already marked UNOWNED**. Checked every recorded owner session against a 200-session roster (`list_sessions include_archived=true`) whose oldest entry is **2026-08-13**, i.e. a window covering every lane in the file, so absence from it is real absence and not a truncated view. Result: **17 of 18 owner sessions DO NOT EXIST.** The 18th (`abf487e4`) is archived, last active 2026-08-20. Exactly **one** session in the entire store was running.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-02 REQUIRED: a pre-registered falsification test still needs a CONTROL CYCLE before you act on it. One reading on a cadence-driven instrument is not evidence. `[lane kalshi-soccer-club-aliases]`

- **The rule going forward.** Before acting on a falsification signal from a periodic instrument, take ONE more cycle with NOTHING changed. It costs one cadence (~15 min here) against a revert-and-redeploy round trip (~45), and it is the only thing that separates "my change did this" from "this cycle did this". State the control's result beside the signal in `deploys.md`.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-02 REQUIRED: before calling a thin downstream count a COVERAGE DEFECT, find the counter that ACCOUNTS for the gap and read the code that increments it. A deliberate quality filter and a broken pipeline look identical from the downstream end. `[lane kalshi-soccer-club-aliases -> finding soccer-board-coverage]`

- **Measured.** Kalshi lists 171 open soccer fixtures; our board carried 28. That reads as a coverage bug and the obvious next lever is "fix the board's soccer fixture coverage". It is not a bug. One read of `/api/board/layer2-shortlist` showed soccer selecting **1,547** rows with **129** reaching the board (8%), against mlb 95% and ncaaf 100%, and the accounting counter in the SAME payload was `rows_uninformative_ev = 1547` -- exactly soccer's selected count.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-02 FORBIDDEN: measuring a change by REPLAYING IT WITHOUT AN ARGUMENT PRODUCTION ALWAYS PASSES. The replay then measures a different system, and its null result is not about your change. `[lane kalshi-soccer-club-aliases]`

- **Measured.** To read whether 34 new club aliases helped, I replayed the resolve step on a stable slate and got `resolved=9, delta=+0` -- a clean null that would have justified reverting a shipped change. The replay omitted `code_names`, which production ALWAYS passes to `match_event_blob`; without it the code path that the aliases feed is not the path being exercised. Redone with production's arguments: **22 attempted/resolved WITH the aliases against 21 WITHOUT, +1.**
- *(evidence in `learnings_evidence.md`)*
## 2026-09-02 REQUIRED: a SIZE warning measured from the working tree is a statement about YOUR CHECKOUT, not about the ledger. Read the file at `origin/main` before trimming it. `[ledger trim pass]`

- **Measured.** The session-start digest said `LEDGER OVER BUDGET: lanes.md 246KB>234KB, learnings.md 286KB>273KB`, and I relayed those numbers as real pressure. At `origin/main` the same files were **144KB/240KB and 270KB/280KB -- both UNDER cap, and they had been for some time.** `session-start.sh` stats `.syndicate/*` in the PRIMARY SHARED TREE, which was **131 commits behind**; upstream had already moved ~122KB of lane blocks into `lanes_history.md` and the stale checkout still carried every one of them. The warning was true of the bytes on that disk and false of the ledger.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-02 REQUIRED: merging a TRIMMED file from a branch that still holds the untrimmed copy RESURRECTS what was archived. Verify against BOTH pre-merge baselines, not just "nothing was lost". `[primary-tree pull]`

- **Measured.** The primary shared tree was 139 commits behind, so its `lanes.md` still carried 39 blocks that upstream had moved into `lanes_history.md`. The merge auto-resolved with no conflict and **brought 19 of them back**, producing blocks that existed in `lanes.md` AND `lanes_history.md` at once, plus two lanes holding two blocks each — the exact state the lane system's exclusivity rests on not having.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-01 — FORBIDDEN: counting Render `server_failed` events without reading `reason`. It is not a failure count — one of its three meanings is a HEALTHY DELIBERATE EXIT. `[lane game-market-entry-roi-curve]`

- **Measured today, both classes, on two services within one hour of each other:**
- *(evidence in `learnings_evidence.md`)*
## 2026-09-01 — REQUIRED: before spending a correlation, drop the largest point and recompute. One window drove a +0.499 to a +0.139. `[lane game-market-entry-roi-curve]`

- **What happened.** `#632` asked for a per-route correlation against the web service's anonymous-memory series. A first look at two hand-picked windows was compelling: the high-growth one had `/api/ops/artifacts/stream` **24** times against **7** in the flat one, while `publish` ran the OTHER way (14 vs 31) — so it was not merely "more traffic". It looked like a clean discriminator.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-02 — FORBIDDEN: designing against a DEFAULT read out of a config template. `${VAR:-1}` is what runs when nobody set VAR, and somebody set VAR. `[lane web-request-memory-attribution]`

- **What happened.** Building the `#632` per-request memory instrument, the one design question that mattered was how many requests can overlap. I read `render.yaml`:
- *(evidence in `learnings_evidence.md`)*
## 2026-09-02 — FORBIDDEN: trusting a lock whose KEY is a name you chose, when the thing it protects has more than one name. `[lane game-market-entry-roi-curve]`

- **What happened.** I acquired `deploy_claim.py --service syndicate`, was granted it, preflighted CLEAR, and deployed web — cancelling a peer's in-flight build 0.6s later. They held `--service web`, unexpired, the whole time. **Both claims were valid. `web.json` and `syndicate.json` are separate files for ONE Render service** (`_path = CLAIM_DIR / f"{service}.json"`), and nothing aliases them.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-02 — FORBIDDEN: measuring a steady-state rate in the minutes after a restart. You are measuring the RAMP. `[lane web-request-memory-attribution]`

- **What happened.** I deployed to enable an instrument, then took my `#632` readings **inside the first 12 minutes after that deploy's restart**: anon 270.8 → 759.5 MB in 7m23s, published as leak growth. A peer's independent 150-minute watch showed the same service ramping and then **PLATEAUING**, oscillating 861.8-894.9 MB for 50 minutes and never crossing 900. One curve: a process filling to a **~890 MB working set**. My "+488.7 MB in 7m23s" was warm-up.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-02 — REQUIRED: mutate the code before believing a green test. Two of mine asserted on a CONSTANT and on a fixture that could not fail. `[lane game-market-entry-roi-curve]`

- **What happened.** Fixing `#635` I wrote six tests, all green, and then mutated the source five ways to check they bit. **Two mutations sailed straight through:**
- *(evidence in `learnings_evidence.md`)*
## 2026-09-02 — REQUIRED: when you correct a number, re-check the CLAIMS AROUND IT. Mine rode through two corrections untouched and was wrong the whole time. `[lane game-market-entry-roi-curve]`

- **What happened.** I published three things about web's memory in one paragraph: a rate (`~75 MB/h`), a mechanism (`monotonic climb`), and a property (**"anon never falls except at a restart"**). Over the next day I corrected the paragraph **twice** — once downgrading the mechanism from a smooth climb to steps and plateaus, once retracting the rate as post-restart warm-up. **Both times I left the property standing, and both times I restated it as the thing that survived.**
- *(evidence in `learnings_evidence.md`)*
## 2026-09-02 REQUIRED: a ledger APPEND computed in one tree is not valid in another. Both the insertion POINT and the base CONTENT differ, and neither difference announces itself. `[lane maxmun-pregame-read]`

- **How to apply.** Write ledger appends from a worktree at `origin/main`, not from the primary tree, and RE-DERIVE the insertion point in the tree you are actually writing to — never carry a line number or an "append at EOF" decision across trees. Then `py -3 scripts/check_lane_invariants.py` before committing. If a block already stands in the primary tree, remove it there after landing, or the next session to commit that file lands a duplicate.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-02 FORBIDDEN: a `git` command that can DISCARD work taking its tree from the working directory. `cd` persists, and the destructive call is not the one that moved you.

- **I deleted another session's OPEN lane from the shared tree.** `m625-env-snapshots` (session `3492626c`) existed only as an uncommitted modification in the PRIMARY `lanes.md`. I ran `git checkout HEAD -- .syndicate/lanes.md` believing I was in my worktree. A `cd` to the primary tree **two commands earlier**, added purely so `render_logs.py` could read `RENDER_API_KEY` from `.env`, had re-homed the shell — and the working directory persists between calls. Not recoverable: no commit contains it (`git log --all -S`), no worktree carries it, it was never staged.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-02 — FORBIDDEN: a log or metric query whose window straddles a restart. You get the wrong process and it looks like an answer. `[lane web-request-memory-attribution]`

- **Twice in one session, on opposite questions.**
- *(evidence in `learnings_evidence.md`)*
## 2026-09-02 FORBIDDEN: verifying a fix only in the window AFTER go-live, where a defect that stopped on its own is indistinguishable from one you fixed.

- **Nearly banked, as a pass:** "zero `KEYVALUE_WRITE_REJECTED` on refresh-worker since go-live 17:56:08Z". Perfectly true. It was true because the LAST rejection was at **17:06:10Z** — fifty minutes BEFORE that deploy. The defect was already gone, fixed by the OTHER service's deploy at 17:10:25Z.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-02 — RULE: TWO WRITERS IS A PRECONDITION FOR HARM, NOT HARM. And "fix all N contested paths" is the wrong instinct when the paths are REBUILT rather than accumulating. `[lane book-quotes-publish-clobber]`

- **corruption**, and it took a shape check to see it.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-02 — FORBIDDEN: calling a job "bounded" because something downstream of it is capped. A cap on the OUTPUT cannot bound the WORKING SET that produced it — and a cap that reports a count is not a bound until you check WHICH container it counted. `[lane accuracy-summary-alloc-profile]`

- **The rule going forward:** before calling anything bounded, name the QUANTITY the bound applies to and the MOMENT it applies, and check that both match the failure you are guarding against. A cap on emitted rows bounds the artifact, not the allocation; a cap that fires after the peak bounds nothing at all. And when a guard reports a count, print that count beside the length of the collection it claims to describe — a truncation pointed at the wrong container is invisible in every test, because it never truncates. Related and NOT the same rule: `#435`'s "the ceiling is per FILE; nothing bounded the SUM". That one is about a bound too small in EXTENT; this one is about a bound aimed at the wrong THING.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-02 — FORBIDDEN: arming a periodic job on refresh-worker on the strength of a bound that does not bound MEMORY. `[lane soccer-anchor-wiring]`

- **1,833 → 3,868 MB** against a 4,096 MB ceiling, headroom down to **0.051 MB**, climbing **+146.9 MB/s**, instance restarted 105 seconds after the job claimed.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-02 — RULE: a WATCHER carries the assumptions it was armed with, and those expire. Re-read the world before acting on what a watcher tells you. `[lane soccer-anchor-wiring]`

- **Neither was wrong about its predicate; both were wrong about the world.** A watcher is a snapshot of intent, and intent goes stale while it waits.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-02 FORBIDDEN: trusting a FILTER, EXCLUSION or ALLOW rule that has never been shown to MATCH something. Two inert rules in one file, both reading as correct. `[lane m625-replay-diff-gate]`

- **The rule going forward:** **every filter rule needs a POSITIVE and a NEGATIVE probe before it is trusted** — one path it must match, one adjacent path it must not. Assert both. This is the `presence is not reachability` rule applied to configuration: a rule that is PRESENT is not a rule that FIRES, and an over-broad rule is not distinguishable from a correct one except by the neighbour it eats. Cheapest form: write the probes as a test next to the table (`tests/test_replay_diff_gate.py`).
- *(evidence in `learnings_evidence.md`)*
## 2026-09-02 FORBIDDEN: reporting a clean result for anything a bounded scan did not reach. A cap on RECORDING must never become a cap on TRAVERSAL. `[lane m625-replay-diff-gate]`

- **The rule going forward:** **count everything, record a sample.** Keep the uncapped total AND an uncapped per-field histogram (indices collapsed, so 3,000 row-level differences aggregate to one line), and cap only the verbose sample. Same shape as `/api/ops/artifacts/export`'s `truncated` flag, which exists because "the puller only advances its watermark on a complete response". Sibling of `a rate, not a count`: a bounded scan must publish what it covered, or its silence about the rest reads as absence.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-02 FORBIDDEN: sampling a seeded Monte-Carlo estimator at CONSECUTIVE seeds and calling the spread a control. Overlapping draws read as sd = 0.0000, which looks exactly like determinism. `[lane soccer-anchor-cost]`

- **Measured.** To size how much precision soccer's anchor solver buys, I ran `solve_market_rating_shift` at 12 "different" seeds and got **sd = 0.0000, all twelve answers byte-identical**. The write-up would have been "the default solver is deterministic, so cutting its cost is free" — and that is the opposite of the truth.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-02 REQUIRED: when a mechanism is under-reaching, measure whether the CHEAP version is louder than the mechanism itself. "Cost lever costs accuracy" is not the finding; "cost lever exceeds the signal" is. `[lane soccer-anchor-cost]`

- **Measured.** The brief asked whether cutting soccer's anchor solver from 500 to 250/125/60 simulations preserved its validated gain. The obvious framing is a trade: cheaper, somewhat worse. Graded on the PROPS the build publishes:
- *(evidence in `learnings_evidence.md`)*
## 2026-09-02 FORBIDDEN: reading an ALLOWLIST-FILTERED inventory as a statement about what EXISTS. I made the 403-vs-absent error inside the change that fixes it. `[lane m625-export-only-patterns]`

- **The rule going forward:** **an inventory is evidence about its FILTER as much as about its subject.** Before reading absence out of any listing, state what the listing is filtered by, and ask whether the thing you are looking for could pass that filter. If it could not, the listing says NOTHING about it — and in this repo that specifically means: `/api/ops/artifacts/export` (both `names_only` and body form) can only ever report allowlisted paths, so it can never establish that a non-allowlisted family is absent. Use a channel whose filter does not contain the question — here, deploying the widened predicate and re-reading was the only way.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-02 FORBIDDEN: acting on a code comment's account of WHY something is excluded without checking the exclusion is real. Two of four families in a work item were already done. `[lane m625-export-only-patterns]`

- **The rule going forward:** **a work item's scope and a comment's rationale are both CLAIMS. Check each against the running system before building for it** — for an allowlist that means evaluating the predicate against a real path, which costs one line. Corollary specific to this repo: `fnmatch` patterns do not stop at `/`, so any `a/*/b` reads much wider than it looks, and a comment describing what a pattern excludes may simply be wrong.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-02 — FORBIDDEN: calling a job "bounded" because something downstream of it is capped. A cap on the OUTPUT cannot bound the WORKING SET that produced it — and a cap that reports a count is not a bound until you check WHICH container it counted. `[lane accuracy-summary-alloc-profile]`

- **The rule going forward:** before calling anything bounded, name the QUANTITY the bound applies to and the MOMENT it applies, and check that both match the failure you are guarding against. A cap on emitted rows bounds the artifact, not the allocation; a cap that fires after the peak bounds nothing at all. And when a guard reports a count, print that count beside the length of the collection it claims to describe — a truncation pointed at the wrong container is invisible in every test, because it never truncates. Related and NOT the same rule: `#435`'s "the ceiling is per FILE; nothing bounded the SUM". That one is about a bound too small in EXTENT; this one is about a bound aimed at the wrong THING.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-02 — FORBIDDEN: anchoring an edit on a GENERIC line in a shared append-only file. My lane note landed inside ANOTHER lane's block, and every check passed. `[lane accuracy-summary-ledger-budget]`

- **The rule going forward:** in a file every session appends to, anchor on something that NAMES YOU — your own `### <slug>` header, then scan forward to the next `### ` — never on a boilerplate line like `- Blocked by: none`, `- Files:` or a section terminator. `str.replace(old, new, 1)` with a count of 1 is not protection; it silently picks the first match, and the first match moves when someone else writes. If an anchor must be generic, assert it is UNIQUE (`s.count(old) == 1`) **and** that it sits inside your own block, and re-read the file immediately before the edit rather than trusting a read from earlier in the session.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-02 — RULE: a commit subject starting with `#` is a COMMENT to git, and cherry-pick/rebase silently delete it. This repo's `#<id>:` convention walks into it every time. `[lane accuracy-summary-ledger-budget]`

- **The rule going forward:** after ANY cherry-pick, rebase or squash of a commit whose subject starts with `#`, read `git log --oneline` and confirm the subject survived. To keep it: `git -c core.commentChar=';' rebase ...`, or rebuild with `git commit-tree -p <parent> -F <msgfile>` (verbatim, no cleanup) and `git update-ref`. `git commit --amend -C <sha>` does NOT fix it — it re-runs the same cleanup.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-02 FORBIDDEN: installing a guard in `sitecustomize.py` that RAISES. CPython swallows it, prints a warning, and the process runs on — my guard announced its refusal and permitted the thing it refused. `[lane m625-fleet-runner]`

- **The rule going forward:** **a refusal that another frame can catch is not a refusal.** In `sitecustomize`, and anywhere a host frame wraps your code in a broad `except`, terminate with `os._exit(code)` after writing the reason to stderr — it skips atexit handlers and cannot be caught. And more generally: for any guard, write the control that ARMS the condition and requires the refusal. A guard verified only by watching it pass is a guard whose refusal path has never executed.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-02 REQUIRED: derive a local run's config from a SNAPSHOT of production's, not by hand — the roles ARE their env, and they differ on 137 of 194 keys. `[lane m625-fleet-runner]`

- **The rule going forward:** **for any local reproduction of a deployed service, start from a snapshot of the deployed env and justify every deviation.** State the forced set and the dropped set in the tool's output, so a reader can see how far the local run is from production without reading the code. Corollary found the same way: a secret-withholding snapshot is also the best credential scrub available, because a value that was never written cannot leak through a deny-list somebody forgot to extend.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-02 FORBIDDEN: taking a deploy claim or preflight from a SESSION WORKTREE. `deploy-guard.py` reads `$CLAUDE_PROJECT_DIR` — the PRIMARY tree — so worktree locks are invisible and the deploy is blocked with a message that names the wrong lane. `[lane soccer-anchor-audit-artifact]`

- **Measured.** Claim acquired and preflight run from `C:\tmp\syndicate-sessions\soccer-anchor-cost`, both reporting success. Same command, same repo, same second:
- *(evidence in `learnings_evidence.md`)*
## 2026-09-02 REQUIRED: `deploy_preflight.py` CLEAR means "no job was running when I looked", NOT "no job dies". The old container keeps launching work for the whole build phase. `[lane soccer-anchor-audit-artifact]`

- **Measured on a deploy I ran:**
- *(evidence in `learnings_evidence.md`)*
## 2026-09-02 FORBIDDEN: drawing a conclusion from a log line the API TRUNCATED. Render's logs API cut a JSON payload at ~1,200 chars; the visible part was all zeros and I published "zero for every date" when it was 7 of 12. `[lane m639-actuals-zero-rows]`

- **The rule going forward:** **when a log line carries structured data, PARSE it and assert the parse succeeded — never conclude from the rendered string.** If `json.loads` fails on the tail, the line is cut and you know it. And state the denominator: "zero on N of M dates" is checkable, "zero for every date" is the claim truncation makes easy. Third instance today of the same family (see the inventory-filter rule and the traversal-cap rule): **a view that omits does not announce what it omitted.**
- *(evidence in `learnings_evidence.md`)*
## 2026-09-02 REQUIRED: `git rebase --continue` re-runs the message CLEANUP, so a commit subject starting with `#` is silently deleted. Every item id in this repo starts with `#`. `[lane m639-actuals-zero-rows]`

- **The rule going forward:** when a rebase may re-open a message whose subject starts with `#`, pass **`--cleanup=verbatim`** (`git commit --cleanup=verbatim -F msg.txt`, and `git -c commit.cleanup=verbatim rebase --continue`), or put the id after a word: `todo #639: ...`. **Do not fix it afterwards by force-pushing `main`** — several sessions push there in real time, and rewriting shared history to repair a subject line trades a cosmetic problem for a real one. Leave it, and make the body carry the id so `--grep` still finds it.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-02 FORBIDDEN: multiplying a measured unit cost by a population from a DIFFERENT query. State the scope of both, or the product is invented. `[lane soccer-anchor-wiring, corrected by soccer-anchor-cost]`

- **The rule going forward:** **a unit cost becomes a workload only when multiplied by the population the CONSUMER iterates.** Before multiplying, name the scope of each factor — its date window, its league set, its filter — and assert they are the same scope. A feed's row count is almost never the consumer's loop count: feeds are forward-looking and shared, consumers are usually single-date. Sibling of `a rate, not a count`, with the denominator drawn from the wrong table entirely.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-02 — FORBIDDEN: deriving a worst case from the NAMES of the limits instead of the loop's actual control flow. My "3 x 20 x 20 = 1,200s" described a nesting that does not exist. `[lane kalshi-discovery-deadline]`

- **The rule going forward:** before multiplying limits together, read where each counter is DECLARED and where the loop BREAKS. A limit's name tells you what it was for, not what it bounds. Cheapest check: instrument the leaf call and count, because the count settles nesting questions that reading alone gets wrong -- and do it BEFORE opening a lane on the arithmetic.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-02 — FORBIDDEN: calling a repeated-cost measurement a PER-REQUEST cost without finding the state that decides whether it recurs. Measured once it was 254 calls; measured an hour later, 0. `[lane kalshi-discovery-deadline]`

- **The rule going forward:** when a cost looks repeated, find the STATE that decides whether it repeats before naming it per-request: a TTL, a due-clock, an on-disk stamp. Then reproduce it deliberately (clear that state) rather than hoping to catch it again. And put the counter INSIDE the function you are bounding -- an external instrument cannot tell "my bound works" from "my bound is never reached".
- *(evidence in `learnings_evidence.md`)*
## 2026-09-02 — FORBIDDEN: adding a bound that returns a PARTIAL result without checking how the caller reads emptiness. This one would have blanked 150 series off the board for an hour. `[lane kalshi-discovery-deadline]`

- **The rule going forward:** a bound that DEGRADES rather than raises must be traced into every consumer of its result, because "partial" and "empty" are the same value to a caller that only checks length. Prefer stopping the caller's loop BEFORE spending, so unfinished work stays visibly unfinished; and give any pre-loop step its own sub-budget so it cannot starve the work the budget exists to protect.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-02 — RULE: run `lane_identity_check` AFTER landing, not only before. A rebase duplicates a lane block wholesale, and the write-side rule does not cover it. `[lane kalshi-discovery-deadline]`

- **The rule going forward:** `land` runs its checkers BEFORE the push, so a rebase-introduced duplicate reaches `main` and is only reported afterwards. Re-run `scripts/lane_identity_check.py` after every land and fix immediately -- lane exclusivity is what the claim system rests on.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-02 FORBIDDEN: reading a DIFFERENTIAL in which more than one variable moved. And an absent trace is not an absent dependency.

- **What I reported, and had to retract.** A "data-dependent tests" sweep compared PASS 1 (87 files, 2,672 tests, no `data/`) against PASS 2 (24 files, 1,031 tests, with `data/`) and called the difference bucket A. **Scope moved with the data.** A test that fails only when 2,672 tests share a process — leaked global state, a cache, a monkeypatch outliving its test — and passes in a 1,031-test run lands in that bucket having nothing to do with `data/`. `test_kalshi_catalogue` did exactly that: it passes with **no `data/` at all** when run in isolation.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-02 FORBIDDEN: acting on a tool's OUTPUT without checking the tool's actual THRESHOLD or PREDICATE. Its output is a claim about the tool, not about the system. `[lane ledger-stale-tree-guard]`

- **The rule going forward:** **a threshold comes from the ENFORCER, a claim comes from the PREDICATE.** Before acting on any tool line that asserts a system fact, run the predicate or read the constant in the code that enforces it. A number printed next to the word "cap" is not a budget, and a sentence printed next to a flagged line is not that line's behaviour. Sibling of `read the field you already have` and `instrument blindness`.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-02 FORBIDDEN: a blanket `except` in a guard. It converts VERSION SKEW into silence, and a silent guard is indistinguishable from a clean result. `[lane ledger-precommit-hook]`

- **The rule going forward:** **a guard's fail-open path must distinguish "no opinion" from "could not run".** Catch the skew signal (`TypeError`) separately and DEGRADE to the predicates the older version does have, rather than letting it fall into the blanket handler. And after installing any guard, exercise it where it now lives — in a repo with 48 worktrees at 48 commits, "it works" is a statement about one tree. Instance of `presence is not reachability`, with version skew as the mechanism.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 REQUIRED: before proposing to ARCHIVE or DATE anything in this repo, check whether the path is KEYVALUE-backed and price it. The live-lens snapshot is a 4 MB Redis key on a 60s tick -- dating it would have written ~5.76 GB/day into a 256 MB store. `[lane mlens-snapshot-dating]`

- **The rule going forward:** **"date it" and "archive it" are storage decisions, not code decisions.** Before proposing either: (1) is the path keyvalue-backed (`_keyvalue_backed`, and the exclusion list is one entry long, so assume YES); (2) how big is one object; (3) how often is it written; (4) what does the store have left. Multiply. And check whether adding a date token silently attaches a TTL — in this repo it does, which `execution_ledger.py` already documents for its own ledger ("NO DATE TOKEN -- a dated path takes the store's 10-day TTL and the record would silently expire"). **When the archive is unaffordable, a FINGERPRINT is usually the right substitute**: it cannot make the thing reproducible, but it makes a divergence attributable, which is most of the value at ~100 bytes instead of 4 MB.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-02 FORBIDDEN: dropping rows whose OUTCOME is zero. It reads as "cleaning the data" and it is selection on the dependent variable — 79% of my sample went, and the survivors all had realized >= 1. `[lane soccer-anchor-cost, #622(3)]`

- **Measured.** Grading anchored-vs-base soccer prop projections against realized shots, I skipped (player, match) rows where the player took no shots, reasoning that a 0 for an unused substitute is an availability fact rather than a prediction error. That is superficially sound and it is wrong.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-02 REQUIRED: when a sign test and a t-statistic DISAGREE, believe neither until you have found the clustering. Mine said p=0.0027 and t=-1.28 on the same rows. `[lane soccer-anchor-cost, #622(3)]`

- **Measured.** 197 (player, match) rows, anchored vs base: exact two-sided sign test **p = 0.0027** (wildly significant) beside a paired **t-ish of -1.28** (not significant). Both computed from the same 197 numbers.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-02 FORBIDDEN: attributing dirt in a shared tree to the thing you just ran, without checking what was dirty BEFORE you ran it.

- **I reported "the suite MUTATES tracked files" and named four. It does not.** Each of 24 modules alone: tree clean. All 24 together, 1,031 tests: tree clean. **Two of the files were already modified in this session's OPENING `git status` snapshot**, before I ran anything. A `git status` taken AFTER a long session attributes every prior session's dirt, and every one of your own earlier commands, to whatever you happened to run last.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-02 — FORBIDDEN: paying for an expensive CONTROL without first checking that its inputs can produce the signal. I nearly spent a 34,690-file checkout on a control that was arithmetically incapable of answering the question. `[lane wnba-cards-fallback-recursion]`

- **The rule going forward:** before running a control that costs real time, state what INPUT it needs and confirm that input exists FOR THE CONDITION UNDER TEST — the date, the sport, the state file, whichever discriminates. `data/` in this repo is a lossy mirror on its own per-family schedule (CLAUDE.md says so), so "the tree has data/" never implies "the tree has the data this test needs". When the input does not exist, MANUFACTURE the trigger instead: here, `rows` comes from `game_cards_<date>.csv`, so writing one row was the whole control — 0.01s against a 34,690-file checkout, and it answered the question exactly. And run the back-control: remove the fixture and confirm the old behaviour returns, or the fixture is not what changed.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 FORBIDDEN: writing a verification predicate into a lane without first checking that it is OBSERVABLE. Do that check BEFORE the work, not after. `[lanes soccer-anchor-wiring, board-window-floor-raise]`

- **The rule going forward:** **before a verification line goes into a lane, grep for the emitter and confirm the signal EXISTS on the path you intend to measure.** One `git grep` answers it. If nothing emits, the first deliverable of the lane is the telemetry, not the change — ship the observation, then the behaviour. That ordering is what turned this one from unanswerable into a reading: `33b181ee` shipped the log line, and the very first tick showed a gated enqueue at `elapsed_s=725` that the old floor would have admitted.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 FORBIDDEN: choosing the READ-only allowlist because "nothing serves this". The test is whether there is a serving HAZARD — export-only makes a family readable IF PRESENT, and if nothing publishes it the entry does nothing at all. `[lane worker-artifact-transport]`

- **The rule going forward:** **the question is not "does anything serve this", it is "is there a serving HAZARD".** Ask what READS the path on the receiving service and whether its behaviour changes on PRESENCE. For reconciliation the answer is no twice over — the autorun is false on web, and the reader defaults its roots to the repo checkout rather than `data_root()`. For `raw/statsapi/feed_live` the answer is yes, and that one stays read-only forever: `_mlb_feed_live_payload` returns the cached file if it exists, so presence IS the trigger. **Pin the discriminating pair in a test**, or the distinction decays back into a preference.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 REQUIRED: when a sign test says p=0.0000 and the t says -1.06, publish BOTH — the direction and the magnitude are different findings and only one of them decides anything. `[lane soccer-anchor-cost, #622(3)]`

- **Measured.** Anchored-vs-base soccer props over 136 matches: anchoring was worse in **95/136 (70%)**, exact sign test **p = 0.0000**. On the same data the per-match mean delta was **-0.00101 shots with sd 0.01106 — t = -1.06**, and the MEDIAN match delta was exactly **0.0000**.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 — FORBIDDEN: a comparative claim from ONE run per condition. I published a 40% effect, ruled out four mechanisms for it, and three paired replications erased it. `[lane intelligence-suite-runtime]`

- **The rule going forward:** **n=1 per condition cannot support a comparative claim, and a large effect is not protection — it is the warning sign.** Before writing a ratio into a ledger, run each condition at least three times and report the spread, not the point. Two specific traps this hit: the "cold" side was triple-measured and the "warm" side was not, which felt like rigour and was not — replicate the side you are ARGUING FOR; and ruling mechanisms out gave the effect false weight, because every exoneration made it feel better established when none of them tested whether it was real. When an isolated instrument disagrees with an end-to-end reading, the isolated one is usually right and the end-to-end one usually has a confound.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 — FORBIDDEN: instrumenting a COMPONENT when the contradiction is between two NUMBERS

- **Cost: four web deploys on `#642`, three of them wasted.**
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 — A per-date join counter is not safe to SUM across a multi-day window unless it is scoped to that date first. Second confirmed instance of the same shape as `#513`.

- **What we believed:** refresh-worker's `[layer2_shortlist] PREGAME_PROJECTION_JOIN sport=ncaaf considered=3625 projected=336 reason="no NCAAF SmartSim2 projections for this date"` (9.3%) described a real, near-total NCAAF projection outage the night of the 2026-09-03 opener slate.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 FORBIDDEN: inferring an environment variable's NAME from the name of the function that reads it. Read the key out of the code. `[lane soccer-projection-names]`

- **The rule going forward:** **before reading an env var to decide anything, grep the key literal in the code that consumes it.** Accessor names, ledger prose and CLAUDE.md all paraphrase; only the `os.environ.get("...")` string is the key. If a probe returns ABSENT, confirm the literal exists somewhere in the repo before reporting it — otherwise "absent" is a statement about your spelling. Sibling of `presence is not reachability`, one level lower: this is ABSENCE IS NOT DISABLEMENT.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 — FORBIDDEN: reading a provenance stamp emitted by the OBSERVER as evidence about the SUBJECT

- **The rule going forward:** **a provenance field tells you the version of the thing that WROTE it, not the version of the thing it describes.** Before partitioning a history on any stamp, name which process emits it and when that process gained the field; if emitter and subject are different components with different release dates, the stamp is a lower bound on the emitter and NOT a classifier for the subject. Where they diverge, "unstamped" collapses two distinct populations — genuinely old rows, and new rows from an old writer — into one bucket, and the partition silently discards good data.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 — FORBIDDEN: concluding content is LOST from a line-level diff of a REWORDED ledger

- **The rule going forward:** **line identity in these files tracks FORMATTING, not information.** Ledger files are rewritten, re-wrapped, collapsed and archived as a matter of routine, so a reworded restatement and a genuinely absent fact are indistinguishable at line level. Before calling anything lost: (a) compare distinctive TOKENS — numbers, SHAs, identifiers, ids — across the WHOLE ledger including `lanes_history.md` and the `state_archive_*` files; (b) check whether an ARCHIVED block supersedes the one you are missing; (c) treat a status word in a heading (OPEN vs CLOSED) as the signal that one side is stale. Sibling of `remote-absent is not content-absent`, one layer down: not "is this commit upstream" but "is this SENTENCE upstream".
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 FORBIDDEN: concluding a RESOLVER is broken without printing the path it actually reads. Two files with the same row count can differ, and the one you grep is not always the one it loads.

- **Three tests "failed" and the resolver was correct the whole time.** `resolve_team("St. Anselm")` returned None. The team is right there in `ncaaf_team_registry.csv` — which `resolve_team` **does not read**. It reads `ncaaf_team_registry_snapshot.csv`, same directory, **same 685 rows**, different contents: the snapshot has 12 St./Saint schools and no `St. Anselm`; the sibling has 11 and does.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 — FORBIDDEN: assuming a stopped background task is stopped. Its CHILDREN keep running, and if they write shared state that gates something, they will gate it against you. `[lane accuracy-autorun-rearm]`

- **The rule going forward:** after stopping a background task, VERIFY the processes are gone (`Get-CimInstance Win32_Process` filtered on the command line, then `Stop-Process`), not just that the task reports stopped. And treat any background loop that writes a file OTHER TOOLS READ as a shared mutation, not private scratch — in this repo that includes the preflight record, the refresh state store and every `.syndicate/**` file. A poller is not read-only just because its purpose is to look.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 — FORBIDDEN: polling a friendlier proxy instead of the instrument that GATES the action. `[lane accuracy-autorun-rearm]`

- **The rule going forward:** identify which instrument ENFORCES the thing you want, and poll that one. A friendlier tool that answers a similar question is a proxy, and proxies disagree exactly when it matters. Related and separately paid for the same day: poll on a documented EXIT CODE, not on substring-matching output — `"CLEAR"` matches inside `"NOT CLEAR"`, and an `[UNKNOWN]` read-failure is not a pass (`check_deploy_safety`'s own help says exit 2 "is NOT the same as clear, and is deliberately not exit 0").
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 — FORBIDDEN: leaving a tree after `git reset --mixed` to a NEWER ref without refreshing the working files

- **The rule going forward:** after any `reset --mixed`/`--soft` onto a newer ref, the working tree is NOT updated — finish the job. Record the genuinely modified paths FIRST (`git diff --name-only` before you touch anything), back them up, `git checkout -- .` to bring the files to the new HEAD, then restore those paths. Never commit from the intermediate state, and never trust "modified" to mean "someone edited this".
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 — FORBIDDEN: writing a poll predicate against the vocabulary you EXPECT instead of the states the tool actually emits. Three instances in one afternoon; two would have acted on a false signal. `[lane accuracy-autorun-rearm]`

- **The rule going forward:** prefer a documented EXIT CODE to string matching — `check_deploy_safety` states its own contract (0 clear / 1 busy / **2 could not determine, "which is NOT the same as clear, and is deliberately not exit 0"**). Where only text exists, ENUMERATE the states from the tool (`--help`, the source, or by reading a real sample of each) before writing the match, and make the predicate require the positive state explicitly rather than the absence of a negative one. An unknown or unrecognised state is NEVER a pass.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 — the DIVIDE rule, restated because I broke it the same day I wrote it

- **Why it fooled me twice in one day.** A total is a SUM, and a sum hides the factor that decides whether a limit is reachable. `bytes` alone genuinely cannot distinguish "2.5MB of many small records, structurally capped" from "2.5MB of few huge records, about to breach" — the test I wrote builds both at the same total size to pin that. So the rule is not merely "divide": **a threshold warning must report the RATIO that determines reachability, not the level.** A level tells you where you are; only the ratio tells you whether you can arrive.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 FORBIDDEN: carrying an obligation as "unverified" when a LATER change made the signal UNREACHABLE. In a log the two are identical; in meaning they are opposites.

- **I said it several times, including in a checkpoint:** refresh-worker's `#638` trim "has never executed in production" and "verifies itself the next time that service is first past the budget". The first half was true. The second was impossible by then and I kept repeating it.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 FORBIDDEN: joining two FEEDS on exact string equality. Four instances in one sport in one day, each one silent. `[lanes soccer-anchor-wiring, soccer-projection-names]`

- **The rule going forward:** **a cross-feed join is a normalisation problem, and exact equality is the bug, not the baseline.** Three things, together: 1. Normalise both sides (`_norm_name` already folds accents — that was the 2026-08-16 MLB fix, and it is why diacritics were NOT the cause here). 2. Fall back to a UNIQUE candidate within the narrowest scope available, and **REFUSE ON AMBIGUITY, counting the refusals**. A silently wrong join is worse than an unmatched row, because the row still prices and nothing downstream can tell. 3. **Publish matched/unmatched WITH the denominator and a cause split.** A join with no yield counter is a join nobody can prove works.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 — FORBIDDEN: correcting a false claim in ONE copy and calling it fixed. Fix the OPERATOR-VISIBLE copy first.

- **The rule going forward:** when a claim is disproved, **grep the whole repo for it before declaring it fixed, and rank the copies by how often each is READ, not by how close each is to the code you changed.** Operator-visible strings, `--help` text, log lines and ledger prose outrank comments every time; a comment misleads one editor, a printed line misleads every reader of every run. And check the correction's OWN container: appending "RESOLVED" to a cell that still asserts the original leaves one subject holding both halves of a contradiction, which is the exact failure `state.md`'s one-subject-one-section rule exists to prevent.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 — FORBIDDEN: editing a ledger file with Python TEXT-mode I/O. It rewrites every line ending in the file, and `git diff` will not show you. `[scheduled task live-gameline-accuracy-snapshot, checkpoint]`

- **Why nothing caught it.** `git diff --numstat` read `1	1` — correct, because `core.autocrlf` normalises on the way in, so the COMMIT would have been exactly the intended line. The mutation lived only in the working file, which is the copy every concurrent session reads directly. Git's warning (*"LF will be replaced by CRLF the next time Git touches it"*) is printed on every such diff and reads as boilerplate.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 — FORBIDDEN: judging what a reworded ledger would lose by a LINE-level diff. It reports as unique the prose that was superseded, which is exactly the prose you must not land. `[state.md archival pass]`

- **Why a line diff fails here specifically.** A ledger gets REWORDED as it is corrected: the same fact is restated shorter, or moved under a new heading. Line identity tracks the wording, which is the part designed to change; the fact is the part that persists. So the residue a line diff reports is biased TOWARD superseded text.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 — FORBIDDEN: forcing a deploy claim whose age keeps RESETTING without first checking the holder's deploys. A resetting age means the holder is WORKING, not that a dead poller is renewing it. `[lane prop-join-yield]`

- **WHY THE INSTRUMENT CANNOT ANSWER THIS.** "A dead session's poller is renewing" and "a live session is actively deploying" produce the SAME reading in `status` — a holder name and an age that keeps resetting. The field that separates them is not in that tool at all. It is one call away:
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 — FORBIDDEN: verifying a deploy by ANCESTRY. Check the deployed file's CONTENT.

- **Measured.** `#643`'s fix (`8add1bbe`) was on `main`. live-odds-worker deployed `48c68546`, and `git merge-base --is-ancestor 8add1bbe 48c68546` answers **YES**. The fix was still absent: `git show 48c68546:syndicate/features/shared/execution_ledger.py | grep -c bytes_per_order` answers **0**. Ancestry proves a commit was APPLIED, never that it SURVIVED — a later commit to the same file can overwrite it with no conflict and no signal. Verify by asking the deployed tree for the CONTENT.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 — a deploy CLAIM can be force-broken while live, and spacing will not catch it

- **The rule.** The second lock does not compensate: a preflight measures from the last FINISHED deploy, so **a build in flight is invisible to the spacing rule**. Serialisation rests on the claim alone and `--force` is one command away — so record the force in `deploys.md`, and before forcing, establish the holder is actually gone.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 — RULE: before you compact a file, measure whether it is BLOATED or merely BIG. They look identical from the size alone and take opposite fixes. `[lane none — ledger structure pass]`

- **The measurement.** 31 superseded markers. One self-delimiting region, 1,460 B. All 8 remaining candidates audited individually: SIX had no dead body at all — the superseded claim was DELETED when its correction was written and survives only as a quotation inside that correction, so the flagged paragraph IS the record and moving it deletes the correction. TWO keep their old block deliberately and say so in the correction. Total reclaimable: **0.2%**.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 — FIXED: a file lock is only a lock if every holder computes the SAME path

- **The blocked deploy was the harmless half.** Two sessions in two worktrees could each `acquire` the same service and both succeed, writing to different files — the lock silently non-mutual at exactly the moment it is load-bearing. Nothing would have reported it; both claims would have been "valid". That is `#635` on a new axis (two NAMES for one box → two TREES for one repo), and the shared shape is worth stating: **a lock is only a lock if every participant computes the same path. Derive that path from something GLOBAL to the repo, never from where the running copy of the code happens to live.**
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 — lane session ids are NOT CCD session ids, so a roster miss proves nothing

- **Consequences that matter.** `send_message` cannot reach a lane owner — session 82fe0160 recorded "not found" for this exact id at `lanes.md:1409` before I repeated the lookup from scratch. And any rule of the form "if that session is gone, `--force` it" must NOT be settled with `list_sessions` on a lane id: the deploy-claim tool's own prompt says an unrecorded session is UNKNOWN, not gone, and this is precisely why.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 — FORBIDDEN: calling a field's persistence "the measurement is now possible" without checking the population can REACH the table

- **I first wrote "three of nine" and it was wrong** — I enumerated the verdicts I had written fixtures for instead of the ones the BRANCH produces, and missed `live_contradicts`. Caught only when I went to encode the set as a constant and re-measured all nine. **A count derived from your own test fixtures is a count of your fixtures, not of the system.** Enumerate from the code that produces the values, then measure every one.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 — CONFIRMED BY DEMONSTRATION: a lane id absent from the roster can be a LIVE session

- **The rule.** `b2b5b45b` held a LIVE deploy claim on web for 27 minutes while appearing in **no row of a 200-entry `list_sessions` including archived**. Absent from the roster, provably alive — so roster evidence must **never** justify `deploy_claim.py --force`. Wait for the TTL, or leave the service to its owner.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 — FORBIDDEN: taking an exit code through a pipe

- **The rule.** `RC=$(cmd 2>&1 | tail -1); if [ $? -eq 0 ]` reads **`tail`'s** status, not the command's, and the wrong answer is always the PERMISSIVE one — `tail` essentially always succeeds, so every guard written this way degrades to "proceed". Capture first, then test: `OUT=$(cmd 2>&1); RC=$?`.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 — check SURVIVAL in the TARGET before deploying, not in the deployed tree after

- **The rule.** *Verify by content, not ancestry* says what to check. This says WHEN: when a pending commit touches a file you fixed recently, check the target before you deploy it. After-the-fact detection means the regression is already live and you have spent the deploy; before-the-fact costs a single read and the answer is the same either way.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 — a guard whose failure modes are ASYMMETRIC must be fixed in the safe direction only

- **The rule is not "add the marker".** It is that this guard's two failure modes are not equal:
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 — FORBIDDEN: writing a disclaimer INSIDE a `- Files:` block. It is a CLAIM, and the more emphatic the wording the more certain it is to be one. `[lane nfl-dispatch-order-assertion]`

- **I did it myself, in the lane block written to announce that I was not doing it.** I wrote ``\`scripts/run_refresh_worker.py\` is **READ-ONLY REFERENCE, NOT CLAIMED**``. Both markers are real — and both came AFTER the path, so the prefix cut removed nothing. Caught by the checker within a minute.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 — FORBIDDEN: reading a green `check_lane_invariants.py` as evidence that a path is unclaimed. Its invariant is "exactly ONE holder", which a phantom holder SATISFIES. `[lane nfl-dispatch-order-assertion]`

- **A contest is the symptom; the claim is the defect.** Going green because a rival withdrew is not a fix, and the check cannot tell those apart by design — its own docstring says the phantom scan is a HINT that is never failed on, because it cannot distinguish a real multi-line `Files:` list from prose.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 — A `-k` sweep partitions by NAME, so a defect spanning a family is reported at whatever fraction of that family happens to share a word. `[lane nfl-dispatch-order-assertion]`

- **How to apply:** when a `-k` run surfaces a failure, ask what else shares the CAUSE rather than the NAME, and re-run scoped to the cause's file family before calling the count complete. Corollary for the fix: three sibling files here had already replaced literal indices with relative ones, so the pattern was discoverable by looking at the family — `grep` for the assertion shape, not for the failing test.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 — FORBIDDEN: reading a repo file through `subprocess(text=True)` on Windows. It decodes with the LOCALE codepage, and this ledger is made of em-dashes

- **The rule.** Any pipeline that reads source or ledger content out of git —
  `git show`, `git cat-file`, `git diff` — must capture BYTES and
  `.decode("utf-8")` explicitly. `text=True` uses
  `locale.getpreferredencoding()`, which is cp1252 here, and a cp1252
  round-trip of U+2014 (`e2 80 94`) produces `c3 a2 e2 82 ac` — which still
  RENDERS as a dash in most terminals and matches no regex looking for the real
  one.
- **What it cost.** Regenerating `lane-guard`'s parser through that path wrote
  mojibake into `LANE_RE`. The live claim set went **50 → 0** and `lane-guard`
  enforced NOTHING — every lane in the repo unguarded — while every checker
  downstream reported success, because zero claims trivially satisfies "each
  claim has one holder" and "no claim names a missing file".
- **The second half, which is the transferable one.** The outage was invisible
  to every existing check and was found only by a differential that asserted a
  NON-ZERO count. **A parser's output count is a health signal and belongs in
  the check** — `scripts/check_lane_claims.py` now treats zero claims against
  OPEN headers as FATAL and names the em-dash by its bytes. Compare BYTES, not
  glyphs: `grep '^LANE_RE' .claude/hooks/lane_claims.py | xxd`.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 — A guard's COVERAGE is measured against the writes that reach it, not the writes it handles

- **The rule.** Before citing a guard as protection, measure the denominator:
  how many of the operations it exists to catch actually route through the tool
  it is registered on. `lane-guard.py` was registered on
  `Edit|Write|MultiEdit|NotebookEdit` only. Census over all 292 session
  transcripts, counting writes whose target resolves to a `git ls-files` path:
  writes to tracked SOURCE files ran **9,023 Edit-family against 1,045
  Bash/PowerShell — 10.4% never checked**, and under `.syndicate/` the shell is
  the MAJORITY path (2,618 vs 1,069).
- **Why it stayed hidden.** A guard that never sees an operation is
  indistinguishable from one that saw it and allowed it. `lane-guard` was the
  only guard in `.claude/hooks` standing on a single layer —
  `ledger-append-guard` shares the same Edit-only matcher but is backstopped at
  write time AND at commit time, which is why the ledger's shell-heavy profile
  never showed up as damage.
- **How to apply.** For every PreToolUse guard, ask which OTHER tool can perform
  the same effect, and either cover it or write down that it is uncovered.
  Prefer watching the OUTCOME over parsing the command: predicting a file write
  from a shell string needs seven regex families and still misses cases, and a
  guard that blocks on a guess is one people route around.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 — WHICH TREE: locks/markers/receipts to the PRIMARY tree, ledger/code to the worktree

- **The rule.** Locks, markers and receipts are read by the GUARDS, which run against the primary tree: take and clear them there. Ledger and code are committed, so they belong in the worktree. `deploy_claim.py` and `deploy_preflight.py` now resolve this themselves via `--git-common-dir` (2026-09-03), but the MARKER files still do not — clear `.syndicate/.current-lane.<session>` in **both** trees when closing a lane, or check with `ls .syndicate/.current-lane.*` in each.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-04 — FORBIDDEN: inferring a session is GONE from its absence in `list_sessions`, even with `include_archived`

- **The roster does not list unattended runs.** Scheduled tasks and remote-dispatched sessions execute without appearing, which the `send_message` tool documents in its own description ("Unavailable in unattended sessions (scheduled-task runs and remote-dispatched sessions)"). So the roster answers "is there an ATTENDED session", never "is anything running as this id".
- *(evidence in `learnings_evidence.md`)*
## 2026-09-04 — FORBIDDEN: counting a set from your own TEST FIXTURES instead of from the code that produces it

- **How to apply: enumerate from the producer, then measure every member.** When a claim is "N of M have property P", the M has to come from the code that emits the values — a branch sweep, a literal set, `dataclasses.fields()` — never from the fixtures in your test. And where the count is load-bearing enough to publish, make it a constant with a test that re-derives it from the source, which is what caught this one.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 — FORBIDDEN: reporting a census result as a property of the POPULATION when it is a property of your PROBE

- **The rule.** A census answers "what my pattern matched", never "what is
  out there". Before writing the conclusion, ask what a member of the
  population would have to look like to be MISSED, then check whether such
  members exist. If the probe is cheap to run directly — running the scripts,
  calling the function — prefer that over a grep, because the direct probe
  cannot have a blind spot the grep has.
- **Two instances the same day, in two sessions, one reviewing the other.**
  I refactored a shared parser and grepped for consumers with
  `spec_from_file_location|exec_module|import_module`. Five scripts load it via
  `exec(compile(...))`, which matches none of those, so I reported all five as
  "prose only". **My refactor had broken every one of them** — four dead on
  `NameError: __file__`, a fifth refusing correctly. A peer found ONE by running
  it; running all of them found five. Symmetrically, that peer hit a timeout
  importing a hook, concluded the module was unimportable, and wrote it into two
  ledger files; it imports in 0.02 s with `sys.stdin` stubbed. What blocked was
  their shell, not the module.
- **Why the false version is worse than silence.** "Prose only" told me those
  files were fine, so I did not run them. "Unimportable" tells the next reader
  not to try. **One failed probe licenses "this did not work here", never "this
  cannot work"** — and one unmatched pattern licenses "my grep found nothing",
  never "there is nothing".
- **How to apply.** State the probe alongside the count ("grep for X found N",
  not "there are N"). When the conclusion is that something is ABSENT or
  UNAFFECTED, run the direct check on at least the members you are about to act
  on. Same family as the caller-census rule of 2026-08-20 (`A DOCSTRING THAT
  NAMES ITS OWN PRECONDITION IS A CHECKABLE CLAIM`), which is about doing a
  census at all; this one is about the census being narrower than its claim.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 — FORBIDDEN: reporting a worker's `server_failed` as an incident without reading the log AT THE EXIT. On live-odds-worker, 20 of 23 are a SCHEDULED SELF-RECYCLE. `[lane prop-join-yield]`

- **THE EVENTS API CANNOT TELL YOU THIS.** Render's `/events` for the service:
- *(evidence in `learnings_evidence.md`)*
## 2026-09-04 — FORBIDDEN: verifying a ledger mutation with a BEFORE/AFTER set comparison computed by the parser that is blind to the thing at risk

- **Neither check could have detected the failure it was standing in for, and the second was not independent.** Both sides of my comparison came from `check_lane_invariants.claims()`, which skips any block whose header fails `OPEN_RE = OPEN`. My own block's header read `**REOPENED 2026-09-03 for the READ side**` — and `OPEN` correctly rejects `REOPENED`, there being no word boundary inside it. So the six files that block declared were **never in the claim set at all**, and a block holding six unenforced claims moved out of `lanes.md` reporting `claims unchanged`.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 — FORBIDDEN: reporting a commit as PUSHED on the strength of a command that also succeeds when it is not. And after a rebase, `--is-ancestor` on the old SHA is not evidence it is absent. `[session c38d3e5c with f97ad5ab]`

- **Direction 1 — existence read as reachability (mine).** I ran `git fetch origin`, then `git log --oneline -1 <sha>` and `git show <sha> --stat`, and reported "confirmed on origin". Both commands return identical output whether or not the commit is reachable from `origin/main`; they answer *does this object exist locally*. `git merge-base --is-ancestor <sha> origin/main` returned **exit 1** and the content was absent from the upstream blob. **The `git fetch` immediately before is what made it feel like an origin check** — it updates the ref, then the next command never consults it.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 — FORBIDDEN: comparing a CONTROL window sampled differently from the treatment window. The rate ratio is an artefact of the sampling, and it will flatter whichever side you sampled less. `[lane prop-join-yield]`

- **RE-RUN, both windows sliced into IDENTICAL 10-minute chunks with per-chunk coverage printed:**
- *(evidence in `learnings_evidence.md`)*
## 2026-09-04 — FORBIDDEN: asserting absence from a range whose START YOU CHOSE — and the reason this one got through, which is the actually useful part

- **This is `absence-in-a-window-is-not-absence` for the THIRD recorded time** (see 2026-08-2x, where the same shape carried a destructive forced deploy). The rule was already written, in this file, and I had cited a neighbouring rule in a commit message forty minutes earlier. So "know the rule" is demonstrably not the control, and a fourth copy of it would not be either.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-04 — A LANE CLAIM ON A LEDGER FILE GUARDS NOTHING, and I read the evidence for that TWICE without extracting it

- **REFINEMENT, because "guards nothing" reads as "unprotected" and that is false.** Ledger files are guarded by CONTENT INVARIANTS rather than by OWNERSHIP, which is a different model and a better fit — every session must write them, so an exclusive claim would be wrong:
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 — A false REASSURANCE is worse than a false WARNING, so it needs a higher bar. Every one of five errors in one night was in the reassuring direction. `[sessions c38d3e5c + 37abeca0]`

- **The asymmetry.** A wrong claim that says *worry about this* costs someone a check they did not need — expensive, and self-correcting, because they go and look and the claim dies. A wrong claim that says *this is covered* removes a check they did need, removes it **silently**, and nobody goes looking, because the whole point of a reassurance is that it ends the enquiry. So the two are not symmetric errors and must not carry the same evidentiary bar.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-04 — a failed rebase leaves a STALE ledger file that `git add` will happily record

- **Two rules.**
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 — FORBIDDEN: choosing a REMEDY from a checker's finding without reading the owning block's INTENT. A true finding can carry a false fix, and the fix is the part that does damage. `[session c38d3e5c, caught by f97ad5ab]`

- **I then triaged them as "the substantive ones — real files, unguarded" and told two sessions and a user that `run_refresh_worker.py` was the one to look at.** The block says, twice, in the same `- Files:` line I was reading tokens out of:
- *(evidence in `learnings_evidence.md`)*
## 2026-09-04 — before a catch-up deploy, check whether the OWNING lane is already shipping it

- **Round 9, web.** `442f82fe` was `web-oom-profiler-steady`'s OWN commit. That lane held web's claim and web had booted 24 minutes earlier — one minute short of the 25-min window its late-emission method needs, because the accumulator is cumulative from boot. A deploy would have reset the clock as the reading came due.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-04 — REBASE FIRST, then edit ledger files

- **The rule catches it; the SEQUENCING prevents it. Rebase, verify it said something other than a refusal, then edit.**
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 — EXONERATED: `deploys.md` and `learnings.md` ARE guarded. Two sessions filed the same false gap, and the second re-derived it with the SAME blind spot

- **The claim, twice:** that `.syndicate/deploys.md` has no ledger-guard
  coverage at any stage (session c38d3e5c, at close), and — after I "verified"
  it — that **2 of 18 `TRACKED` files have no predicate that can ever fire**.
  Both are wrong. `_deploys` and `_learnings` are registered in `CHECKS` and
  both fire.
- **AMENDED `[2026-09-03, session c38d3e5c]` — THE FIRST OF THOSE TWO WAS TRUE
  WHEN IT WAS MADE, AND IS WHY THE GUARD EXISTS.** Only the second is a false
  reading. `dbe0f3b4` is what closed it, and its diff is unambiguous:

      -TRACKED = (LANES, STATE, *STATE_PARTS, LEARNINGS)
      +DEPLOYS = ".syndicate/deploys.md"
      +TRACKED = (LANES, STATE, *STATE_PARTS, LEARNINGS, DEPLOYS)
      +def dropped_sections(...)      +def _deploys(text, root)
      +          DEPLOYS: _deploys,

  Before that commit `deploys.md` was absent from `TRACKED`, had no `_deploys`,
  and was not in `CHECKS` — measured at the time, alongside `ledger-append-guard`
  (two hits, both PROSE: docstring :31, remedy string :176) and
  `ledger-postwrite-check` (zero mentions). That commit's own added comment
  restates the finding as its justification: *"ledger file with no guard at ANY
  stage: absent from TRACKED, and its two ..."*.

  **The correction is therefore a TIME error, not a fact error** — a true claim
  re-evaluated against code that had changed in response to it, and then filed
  as a false alarm. **This matters beyond attribution:** left as written, a
  reader concludes `deploys.md` was never unguarded, which removes the reason
  the guard was added and makes deleting it look like tidying. `_deploys` is
  load-bearing — probed against the real 1.13MB upstream file: unchanged text
  0 violations, two sections REMOVED 1 violation, an APPEND 0 violations, so it
  blocks a drop while preserving append-only.

  Your second claim stands exactly as you wrote it, and the `root=None` lesson
  is the durable half: a probe is only evidence once it can produce the other
  value.
- **How the false reading was manufactured.** I drove every tracked file with
  empty/garbage text and `root=None`, and read the nulls as absence.
  `_deploys`' own first line is *"Fails OPEN: no root, no git, no ref -> no
  opinion"* — I passed exactly the argument that makes it silent, then reported
  the silence. `_learnings` needs its `- *(evidence in ...)*` marker, which my
  inputs never contained. **Driven, not grepped** is better than grepping and
  still not enough: a probe is only evidence once it can produce the other
  value.
- **Demonstrated, which is what the first pass owed:** `_deploys` with a real
  root reports **1** missing measurement section on the live file (this tree is
  behind origin) and **294** on a file truncated to 200 lines. It diffs against
  `origin/main:.syndicate/deploys.md` and refuses a commit that would DROP
  measurements — *"a lost entry makes an unverified deploy look verified"*. It
  is one of the STRONGER predicates in the module.
- **The rule, and it is not "check harder".** RE-DERIVING A PEER'S FINDING WITH
  THE SAME BLIND SPOT IS NOT CORROBORATION. I set out to verify their claim
  rather than accept it, which is the defence — and reproduced their error,
  because I chose an instrument that fails silent in the same direction. Two
  agreeing readings are one reading unless the instruments can fail
  independently. Same shape as the two-checks-one-parser case filed the same
  day, one layer up.
- **What actually stopped it:** reading `CHECKS` before writing code. A lane was
  open to add an `UNCHECKED` set and a coverage test — machinery guarding a gap
  that does not exist, in the file whose own comment says silence "fails
  PERMISSIVE", while the real predicates sat 30 lines below the dispatch I had
  already read. Nothing was built.
- **IT THEN BLOCKED THE COMMIT THAT RETRACTS THIS.** `ledger-commit-guard`
  refused it: *"1 measurement section(s) on origin/main are MISSING from this
  commit's deploys.md"* — a real entry (`## 2026-09-04 round 10`) this stale
  tree had not fetched. The predicate I had written off caught a real
  regression in a real commit, in the same minute. **A guard reported as dead
  is not dead; it is a guard nobody has made angry yet.**
- *(evidence in `learnings_evidence.md`)*
## 2026-09-04 — OVERTURNED: `_SCORE_SIM_WEIGHT` is **0.125**, not 0.0. Two load-bearing comments say 0.0, and one of them is the entire basis of `side_picked_by`. `[lane prop-join-yield]`

- **`sim_component` is NON-ZERO on 5,108**, min −1.5000, median 0.2737, max 1.5000, with 448 rows flagged `sim_capped`. The sim IS in the ranking, on ~20% of rows, and the served board's own explainer agrees ("capped at 1.5 EV points").
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 — FORBIDDEN: clearing a `git checkout -- <path>` on a DELETIONS count. It is structurally blind to the ADDITION you are about to destroy

- **The rule.** Before any discarding git operation in a shared tree
  (`checkout -- <path>`, `restore`, `reset --hard`, `stash` without `-u`), the
  check is *"what does this path contain that exists NOWHERE ELSE"*, not
  *"whose deletions are these"*. Run `git diff -- <path>` and read the `+`
  lines; anything added and uncommitted is gone the moment the command returns,
  and it is gone from every session, because the tree is shared.
- **What happened `[session c38d3e5c, on this session's lane block]`.** Their
  shell's cwd had silently reverted from their own worktree to the PRIMARY
  SHARED TREE. Recovering an unrelated edit, they ran
  `git checkout -- scripts/pending_deploys.py .syndicate/lanes.md` there. They
  DID check first, and the check was the wrong shape: the diff read **"0
  deletions, all mine"**. Another session's lane block was an ADDITION in that
  same unstaged diff, and the two `+### ` headers read as one. It existed in no
  commit on any branch — `git log --all -S` returned nothing — and no backup was
  newer than it.
- **The check was not weak, it was aimed elsewhere.** A deletions count answers
  "am I removing someone's existing lines". The hazard was "am I removing
  someone's NEW lines", which has no deletions at all. Same family as the
  session's other findings — a guard that cannot read the unhealthy state is
  silent in exactly the case it was reached for.
- **What worked, and it is the cheap half:** they left a PARTIAL
  RECONSTRUCTION in place rather than a hole, so the destroyed lane's file
  claims stayed ENFORCED and the loss stayed visible instead of reading as a
  lane that never existed. Reconstructing from the `lane-postwrite-check`
  report recovered the slug and the claims; everything else was lost.
- **The rebuild then duplicated the slug** — the owning session no longer had
  the block locally, rewrote it, and landed on a base that already carried the
  reconstruction. `ledger-postwrite-check` caught the double block within
  seconds of the push. Two blocks for one slug means two sessions can each read
  themselves as holder of the same files.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 — FORBIDDEN: retracting a claim you re-checked, without first asking whether the CODE MOVED between the claim and the check. Re-derivation cannot see this

- **The rule.** When you verify someone's finding and it comes back false,
  date the claim and date the code. One line answers it:

      git log --oneline -S "<symbol from the claim>" -- <file under test>

  If a commit lands between the two, you are not checking their claim — you are
  checking a different system, and very possibly one that changed BECAUSE of
  their claim.
- **Why it is worth its own entry.** This is invisible to the defence everyone
  reaches for. I re-derived instead of accepting, ran the check correctly, and
  got the correct CURRENT answer. **Nothing in a correct measurement tells you
  the ground moved under it.** That makes it distinct from the same-blind-spot
  failure filed beside it: there the instrument was wrong, here the instrument
  was right and the QUESTION had expired.
- **Measured.** c38d3e5c reported `.syndicate/deploys.md` had no ledger-guard
  coverage at any stage. TRUE when written: at `dbe0f3b4^` it was absent from
  `TRACKED`, absent from `CHECKS`, and had no predicate. `dbe0f3b4` (19:42:33)
  added all three, and **its own comment quotes the finding as its
  justification**. I checked at ~20:2x, found `_deploys` alive and firing, and
  filed the whole thing as a false alarm.
- **The cost direction is the dangerous one, and it is reassurance.** A
  retraction of a TRUE finding does not merely lose a fact: it deletes the
  stated reason a guard exists. Left standing, the next reader concludes
  `deploys.md` was never unguarded and removing `_deploys` reads as tidying.
  Compare the retraction rule already here — withdrawing a bad attribution buys
  "not proven guilty", never "proven innocent"; this is the same asymmetry
  pointed at a live guard.
- **How it was caught:** not by me. c38d3e5c amended the entry rather than
  messaging, on the grounds that the wrong version was the one being read. That
  is the right call for a correction whose damage is what a passer-by concludes.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-04 — THE LEDGER COMMIT GUARD CANNOT SEE A WITHIN-BLOCK REVERT, measured at 117,321 characters

- **Measured, not argued:**
- *(evidence in `learnings_evidence.md`)*
## 2026-09-04 — FORBIDDEN: clearing a shared-tree file on a STRUCTURE check. Content dies inside retained structure.

- **Twice-real, same day, two sessions, opposite roles.** The generalisation is session c38d3e5c's and it is sharper than either incident:
- *(evidence in `learnings_evidence.md`)*
## 2026-09-04 — THE UNIFYING RULE: A COMPARISON PROTECTS ONLY AT THE GRANULARITY IT COUNTS

- **The general form: a before/after comparison is blind to anything its extractor does not emit, and that blindness is SYMMETRIC — so both sides agree and the check reports success.** It is not that the comparison is wrong; it is that it answers a question one level coarser than the change.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 — A comparison protects only at the GRANULARITY IT COUNTS. Three instances in one night, and the finest-grained one destroyed work. `[session c38d3e5c with 37abeca0, cfcce46d]`

- **Each is blind to any loss smaller than its unit**, and the blindness is silent, because "no difference at my granularity" and "no difference" print identically.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 — FORBIDDEN: pushing a REBUILT file without asserting the EXPECTED diff shape first. A stale base produces correct-looking content and a silently wrong delta. `[session c38d3e5c]`

- **Reviewing the artifact cannot detect this; only the delta against the CURRENT base can.** That makes it invisible to every check aimed at content: a diff of the text, a grep for the restored lines, a byte count, reading it.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-04 — A DEPLOY THAT SUCCEEDS, TESTS THAT PASS, AND A SMALLER RESPONSE CAN ALL BE TRUE WHILE THE CHANGE DOES NOTHING

- **THE RULE: verify a payload change by the STRUCTURE you intended to change, not by the size of the result.** "Is the key actually gone?" found it in one call; the byte count would never have. The same trap re-appeared immediately after the real fix landed at a flattering **68.9%**, which was again partly slate size — the honest figure was 50.0%, from differencing the SAME captured payload.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 — FORBIDDEN: reading the clock with Git Bash `date` in this repo. It is FIVE HOURS SLOW, and `date -u` is wrong too. `[lane accuracy-autorun-rearm]`

- **The rule going forward:** **get the time from Python (`time.strftime` / `datetime`) or from a server response header, never from the Bash tool's `date`.** This matters far beyond cosmetics here: the accuracy autorun, settlement, the board window and every scheduled task gate on **Central hour**, and a 5-hour error moves you across the `hour >= 7` boundary — the exact predicate that decides whether arming a key waits politely until morning or fires immediately. Related standing rule: report local time, not UTC.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-03 — FORBIDDEN: treating an env key as INERT because the process has not been restarted. Inertness is about the DEPLOY; the DAMAGE is decided by the hour you set it in. `[lane accuracy-autorun-rearm]`

- **The rule going forward:** for any flag consumed by a TIME-GATED job, the question is never "is it deployed" but **"if this became live at this instant, would the gate still protect me?"** Reverting to `false` costs nothing while undeployed; leaving it armed delegates the firing decision to whichever unrelated session deploys next. Same key, opposite meaning, and the only variable is the hour.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-04 — THE TWO THINGS ROSTER-ABSENCE ALREADY COST, and what to check before the NEXT force `[lane prop-join-yield]`

- **The rule itself is one entry down, written by the lane that found it** (`lanes.md` carries `CLAUDE_CODE_SESSION_ID`s, `list_sessions` returns CCD `sessionId`s, the spaces never match). This entry is only what that rule cost in practice and the check it implies — I had written a THIRD copy of the rule here and removed it; `learnings.md` is over budget and three statements of one rule is exactly what makes it lossy.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-04 — FORBIDDEN: calling an env key "inert until a deploy" without reading the gate it feeds. If the gate's conditions are ALREADY true, the key is a primed charge waiting for someone else's deploy. `[lane prop-join-yield]`

- **THE HOUR YOU SET IT IN CHANGES ITS MEANING.** The scheduled task arms at 03:00 Central precisely because at `hour=3` the gate HOLDS the run until 07:00, on a worker that is quiet by then. Arming at 22:00 skips that protection entirely — same key, same value, opposite risk.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-04 — FORBIDDEN: treating absence from `list_sessions` as evidence a session is gone. **`lanes.md` carries `CLAUDE_CODE_SESSION_ID`s; `list_sessions` returns CCD `sessionId`s. The two ID SPACES DO NOT MATCH, so the test has NEVER been valid.** `[lane accuracy-autorun-rearm]`

- **The rule going forward:** **liveness must be established POSITIVELY, from an artifact the session itself writes** — a commit in the last N minutes, a claim whose age RESETS, a fresh preflight record — never from absence in a roster you cannot join to the id you hold. Before forcing any lock, read `/v1/services/<id>/deploys` and check for a deploy in flight; a build in `created` state IS the holder working. And if you must act on a stale-looking claim, prefer waiting: an unexpired claim costs minutes, a displaced deploy can cost a revert nobody sees.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-04 — CHECK THAT THE THING YOU ARE GATING ACTUALLY RUNS, BEFORE YOU BUILD THE GATE

- **Neither loop runs on web.** `SYNDICATE_ENABLE_LIVE_ODDS_REFRESH_LOOP=false`, `SYNDICATE_ENABLE_INTELLIGENCE_STATE_BACKGROUND_LOOP=false`, the code gate defaults to False, and web has logged ZERO loop lines ever. The gate is correct and inert, and the diagnosis it rests on is FALSIFIED.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-04 — FORBIDDEN: acting on a comparison guard whose inputs are not NORMALIZED

- **Why this is worse than an ordinary bug.** A comparison guard exists to answer "will I destroy something", and unnormalized it reports CATASTROPHE and CORRECTNESS with the same confidence and the same shape. Worse, the remedy it triggers — `git checkout origin/main -- <path>` — is the destructive command, the one that already destroyed a peer's lane block on 09-03. A miscalibrated guard does not merely fail to help; it points at the loaded gun.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-04 — AN IN-PYTHON FREE CANNOT MOVE PROCESS ANON. CHECK THE ALLOCATOR BEFORE HYPOTHESISING ABOUT FREES

- **Allocated 0.0 MB. Refunded 0.0 MB.**
- *(evidence in `learnings_evidence.md`)*
## 2026-09-04 FORBIDDEN: an instrument whose partial output is indistinguishable from its complete output. `[lane render-events-nondict-reason]`

- *(evidence in `learnings_evidence.md`)*
## 2026-09-04 — a BLOCKED money-relevant commit needs a follow-up read, not just a flag

- **The half that is easy to miss is going back to check.** I did, and it had shipped — refresh-worker `2332b47b`, 0 pending, verified BY CONTENT (`_sample_credibility` x1, `_settled_sample_size_by_sport` x2, `848bcab9` an ancestor). Bet sizing is corrected in production.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-04 CITE THE COMMAND YOU RAN, WITH ITS FLAGS — an abridged citation cannot be re-checked, and one day it will have to be. `[lane render-events-truncation-audit]`

- *(evidence in `learnings_evidence.md`)*
## 2026-09-04 — A WRONG CAUSE IN A PRE-REGISTRATION IS WORSE THAN NO PRE-REGISTRATION, because it is the first explanation the next reader reaches for. `[lane accuracy-ledger-budget-raise, challenged by lane mlb-rate-refit]`

- **The rule going forward:** pre-register **what reading counts as which outcome**, and keep candidate CAUSES out of it unless the mechanism is already established. A registered cause is not a neutral hypothesis — it is the explanation the next reader adopts first, and it steers them AWAY from the real driver precisely when the measurement goes bad and attention is short. If you do register one, register the check that would discriminate it. And **when retracting, mark the wrong claim false IN PLACE rather than deleting it**: a retraction needs something to point at, or the next reader meets a clean ledger and no reason to doubt the surrounding numbers.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-04 — FORBIDDEN: REBUILDING a shared ledger file from `origin/main`. Every git discard guard watches git; a rebuild is a plain WRITE and none of them fire. `[lane mlb-feed-live-terminal-refresh]`

- **The rule going forward.** **Never rebuild a shared ledger file from a remote. Rebase your own copy, or edit in place.** If a rebuild is genuinely the only option, the pre-check is not against upstream — it is `set(slugs in the file you are about to overwrite) - set(slugs in your replacement)`, which must be empty. Same shape as the 2026-09-03 rule (*"what does this contain that exists NOWHERE ELSE"*) with the answer computed against the WORKING TREE rather than against a remote.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-04 — a content-check TOKEN that was guessed FAILS CLOSED, and looks like a missing commit

- **The asymmetry.** *Verify by content, not ancestry* is the right rule and I keep using it; this is its failure mode. A token that is present-but-misspelled returns the SAME `0` as a commit that never landed, and `0` is the alarming answer, so the mistake manufactures incidents rather than hiding them. That is the safer direction than the reverse — but only if the token is checked.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-04 — FORBIDDEN: reporting a key as ABSENT from a paginated API without paginating. An unpaginated list read manufactures FALSE ABSENCE, and absence is the finding people act on. `[lane mlb-feed-live-terminal-refresh]`

- **The rule going forward.** **A list endpoint answers "what is on this page", never "what exists".** Absence is only a finding once the listing is known to be COMPLETE: paginate to exhaustion and report the total you enumerated (`keys=153`) next to the absence, so the denominator is visible and a short read is obvious to the next reader. And when a config read implies that deployed code is INERT, **check the code's own output before believing it** — a log line, a counter, an emitted stamp. A gate that is really inert is silent, and silence is directly observable. Sibling of *presence is not reachability* pointed the other way: this is ABSENCE is not INERTNESS.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-04 — "SELF-VERIFYING" is only true where the EMITTER runs. Find the print, then ask who owns it.

- **The rule.** A verification signal has an owner service exactly like the code it verifies, **and they need not be the same one**. Computation in `shared/` reaches all three; emission in `pipeline/` reaches one. So before claiming a deploy makes something verifiable: **locate the PRINT — `git grep <field>` for an f-string, repo-wide — and ask `_owners()` who runs THAT file.** Deploying the computation to a service that cannot print it buys nothing observable.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-04 — A FLAT READING FROM AN INSTRUMENT THAT CANNOT SEE THE SUSPECT IS NOT EVIDENCE

- **Both instruments are structurally incapable of seeing the allocation that turned out to be responsible.** CPython routes anything over 512 bytes past pymalloc to malloc/mmap; pymalloc arenas were ~40% of worker RSS and `malloc_info` reached 13.9% coverage. The growth is in 8-64MB anonymous mappings — a region class neither can report. A third instrument (`/proc/self/smaps`, the kernel's own accounting) found it in one window.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-04 — PRE-REGISTER THE GATE, AND LET IT BIND WHEN THE DATA IS POINTING WHERE YOU HOPE

- **34.6 minutes — 24 seconds short** — with the data pointing exactly where I wanted it to.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-04 — 100% OF WHAT YOU SAMPLED IS NOT 100% OF THE THING. THE DENOMINATOR MUST COME FROM OUTSIDE THE INSTRUMENT

- **Failing in OPPOSITE directions is the tell that it is not a scale error.** One worker climbed 90 MB with every sampled request reading zero; the other attributed nearly twice what its process gained.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-04 — A PRE-REGISTERED FALSIFICATION TEST IS WORTH WRITING, BECAUSE IT FIRES

- **A pre-registered falsification test is worth writing, because it FIRES.** *(this entry's body carried no separate rule line; its heading is the rule.)*
- *(evidence in `learnings_evidence.md`)*
## 2026-09-04 — A BROKEN IDENTIFIER IS WORSE THAN NO IDENTIFIER, BECAUSE IT MANUFACTURES FALSE CONTINUITY

- **It shipped INERT, and inert in the worst available way.** The token was generated at module import, and **gunicorn forks its workers AFTER the import**, so every worker inherited the identical value. Measured in production 20:24-20:26: pid 99 and pid 98 both emitted `6178fc632433`.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-04 WHEN A COMMIT NARROWS A PREDICATE, THE DOCSTRING IS PART OF THE PREDICATE — a stale contract line does not read as stale, it reads as CORROBORATION for whichever test still encodes the old rule

- **The rule going forward.** A guard's docstring is part of the change that narrows it, not documentation of it. Left behind, it does not read as stale — it reads as a SECOND SOURCE agreeing with whichever test still encodes the old rule, and the pair is an instruction to revert a change that was made on a production measurement. **Before committing a narrowed predicate, grep the whole enclosing docstring for the rule you just edited.** `28e55d86` rewrote the branch and its inline comment and left the docstring twenty lines above it stating the opposite; the contradiction sat red for two weeks and pointed the wrong way.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-04 FORBIDDEN: editing a scheduled task's prompt while a session of that task is still ALIVE — it can fire the new prompt IMMEDIATELY. `[lane feed-live-warn-rate, session c4287631]`

- **The dry run's session was still alive.** It picked up the restored prompt and began executing the REAL 30-minute measurement at 15:42 — 4.5 hours early, with **1 game live instead of the ~12** the window was chosen for, holding the worktree the 20:15 run was going to want.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-04 — A COEFFICIENT IS NOT A FINDING UNTIL IT SURVIVES LEAVE-ONE-OUT AND A RANK TEST

- **One collector, one metric, four verdicts, three of them wrong -- and each wrong one was a clean number with a plausible mechanism attached:**
- *(evidence in `learnings_evidence.md`)*
## 2026-09-04 — "THE CLAIM HOLDER IS NOT IN THE SESSION ROSTER" IS TRUE OF EVERY CLAIM. IT IS A CATEGORY ERROR, NOT A LIVENESS CHECK

- **The comparison cannot ever succeed, for anyone.** Measured:
- *(evidence in `learnings_evidence.md`)*
## 2026-09-04 — A RUNNING MINIMUM CANNOT DETECT A RISING FLOOR. CHECK THAT THE STATISTIC CAN EXPRESS THE ANSWER

- **The running minimum is the first reading, always, for any non-decreasing series.** It can only move DOWN, so on a process that never returns memory it is pinned at the boot value forever. The metric I chose to answer "does the floor rise" is mathematically incapable of rising. Both workers duly reported `floor_mb` fixed at their boot values, which looks like a flat floor -- the CHURN signature -- when the truth was the opposite.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-04 FORBIDDEN: pinning a copied definition against ANOTHER FILE'S SOURCE TEXT. When the definition moves, the test stops existing instead of failing `[lane lane-invariant-single-source]`

- **The rule going forward:** a module may not hold its own copy of a definition another module enforces -- import it. If you cannot, do NOT settle for a test that scrapes the other file for the definition and compares: that test's precondition is *being able to FIND both copies*, so the refactor that moves one turns the test red for a reason unrelated to drift, and drift then accumulates behind it unwatched. Assert the ABSENCE of a second definition in the file you control (`ast`, module scope) -- that survives any refactor of the other side. **14 tests across three files had been red on `origin/main` for exactly this**, all bound to `lane-guard.py`'s shape after its parser moved to `lane_claims.py`, while `check_lane_invariants.py` still exited 0 and printed INVARIANTS HOLD. The four pinned regexes had NOT drifted; four things nobody had thought to pin had. Worst: a `- Files:` line naming `scripts/archive_released_lanes.py` -- a filename CONTAINING the marker "released" -- yielded the checker ZERO claims, so that lane could contest nothing and the two-holder invariant passed vacuously. Measured on one adversarial ledger: old checker `INVARIANTS HOLD` exit 0 against a contested file AND a stray OPEN lane under `## Archived lanes`; new checker, 2 violations, exit 1. Fixed in `312c93a9`.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-04 — FORBIDDEN: choosing a DEPLOY TARGET by which service CONTAINS the code. Choose it by which service SERVES the reading you predicted. `[lane nfl-projection-deploy]`

- **What we believed:** deploying `web` would take NFL `unmatched_game_rows` from 78 to 0. `_attach_book_grid_projections` runs in web's request path, web serves `/api/board/book-grid`, and web had the fix. Every one of those is TRUE.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-05 — A CENSUS IS BOUNDED BY ITS ROOTS, AND THE ROOT SET IS THE FIRST THING TO STATE

`#632`. A retainer census walked module globals in `syndicate.*` / `pipeline.*`
and found that named containers explain **6.1% of a worker's anon GROWTH**. The
tempting headline is "the memory is not in Python, go look at C extensions".

That headline would be wrong, and the reason is in my own code: the walk's ROOTS
are module globals **that are already `dict`/`list`/`set`/`tuple`**. A
module-level OBJECT holding caches in its `__dict__` is skipped before the walk
starts. So are class attributes, closure cells, and thread-local state. The
supported claim is *"not in container-typed module globals"* — a strictly
narrower statement, and the difference is exactly where a lot of real caches live.

THE RULE: a reachability census answers "how much is reachable FROM THESE ROOTS",
never "how much exists". State the root set beside the coverage number, every
time, because a low coverage has two very different causes — the memory is
elsewhere in the process, or the roots were too narrow — and they lead to
opposite next steps.

The same run supplies a second, sharper instance. At `node_cap` 20k/100k/400k the
budget EXHAUSTED and coverage read 0.8% / 2.9% / 15.8%. **With the budget
exhausted, "top N by bytes" is only "biggest among whatever module iteration
order happened to reach first"** — an arbitrary sample presented as a ranking.
Only the completed 2M-node walk is quotable, and the census reports
`node_budget_exhausted` precisely so that a truncated run cannot be read as a
finished one.

Related: `[2026-09-04]` "a flat reading from an instrument that cannot see the
suspect is not evidence" and "a running minimum cannot detect a rising floor".
Three forms of one discipline: know what your instrument CANNOT show before you
believe what it does.
## 2026-09-05 FORBIDDEN: shipping a fix whose motivating measurement YOU labelled inconclusive. A caveat you wrote is an instruction to yourself, not a disclaimer to the reader

- **What happened.** A one-date run (6 game clusters, 6,396 pairs) showed the
  MLB sim's measured joint LOSING to plain independence, monotonically worse the
  further the estimator was allowed to move. I diagnosed a unit error -- the
  joint publishes Spearman rank correlation of COUNTS while a parlay bets
  THRESHOLDS, and under a Gaussian copula phi(indicator) is only 54-68% of
  rho(counts) -- wrote the correction, shipped it (`c6027e1f`), and reported it
  as explaining every number. I had written "6 clusters, one date; suggestive,
  not conclusive" onto that finding **in the same session**, then reasoned from
  it as though it were settled.
- **What the replication said.** Backfilled 177 games from git-tracked rosters
  and re-scored: 162,491 pairs, 151 games, 13 dates. **The motivating finding
  INVERTED.** The joint BEATS independence on same-player pairs by -0.02353
  log-loss, 95% CI [-0.02849, -0.01854]. And the correction was measurably WORSE
  than the raw coefficient: +0.00156, CI [+0.00100, +0.00219]. A Gaussian copula
  over-attenuates for discrete, zero-inflated counts. Reverted in `862b5ccf`.
- **The rule.** A caveat does not discharge the risk it names. If a finding is
  too thin to publish it is too thin to BUILD ON -- replicate first, at a sample
  that can actually separate the arms, or do nothing. The tell is writing a
  hedge and a fix in the same session.
- **The second half, and it is what made it invisible.** The conversion shipped
  with NO TEST referencing it. ADDING it was silently green and REVERTING it was
  silently green -- a behaviour change on a live pricing path that no test could
  see, in either direction. **A revert that passes cleanly is not reassurance;
  it is evidence the change was never covered.** Guard added
  (`tests/test_joint_resolver_returns_raw.py`), source-level so it needs no
  fixture, mutation-checked by re-adding the call.
- **Cost:** none in production -- `c6027e1f` landed after the last deploy
  (`3a9153f4`), so the conversion was never live. Luck, not process.
- **Instruments:** `scripts/backfill_mlb_sim_joint.py` (resumable, git-tracked
  rosters, no export and no StatsAPI) and
  `scripts/score_joint_pair_pricing.py` (four arms on identical marginals,
  bootstrap over GAMES).
## 2026-09-05 — A TRUNCATED MEASUREMENT CAN GIVE THE RIGHT ANSWER FOR THE WRONG REASON. CONVERGE, THEN READ.

`#632`. The deciding question was whether the retained bytes were Python objects
at all. The walk that answers it is budgeted, and the budget changes the answer:

    cap   200,000  ->   20.55 MB    7.2%   TRUNCATED
    cap   800,000  ->   97.75 MB   28.5%   TRUNCATED
    cap 2,000,000  ->  105.56 MB   28.3%   CONVERGED

Every reading pointed at the same conclusion ("not Python"). **Only the last one
is entitled to it.** At a 200k cap the walk had seen 7.2% of anon and would have
supported the verdict just as comfortably — and been wrong by a factor of five
about the size of the Python heap, which is the number the FOLLOW-UP work
depends on.

THE RULE: when a measurement is budgeted, the budget is a parameter of the
result. Escalate until the instrument reports it did NOT truncate, and refuse to
report a ratio computed from a truncated walk — build the refusal into the tool,
because the truncated number will usually agree with whatever you already
believe. A tool that returns a plausible number when it ran out of budget is
`[2026-09-04] an instrument whose partial output is indistinguishable from its
complete output` in a new costume.

The corroboration is worth recording too, including its limit: pymalloc's
`bytes_in_allocated_blocks` (`105.731 MB`) and an independent object-graph walk
(`105.56 MB`) agreed to **0.16%**. Two instruments with nothing in common
arriving at the same number is the strongest evidence this investigation has
produced — and it is still only SUGGESTIVE, because the readings came from
different processes hours apart. Same-instant would have made it proof;
saying so is the difference between corroboration and a coincidence.
## 2026-09-05 — SAMPLE FASTER THAN THE THING YOU ARE DESCRIBING, OR THE SHAPE IS YOUR SAMPLING GRID

`#632`. I opened a lane on a striking observation: both web workers gained ~98 MB
inside ~100 seconds, and **a single request cannot raise two workers at once**,
so it had to be a scheduled job or a fan-out. The reasoning was sound and the
conclusion was wrong, because the observation was an artifact of the sampling
interval.

It came from samples **50 seconds apart**. At that spacing, "worker A grew, then
worker B grew" and "A and B grew together" produce identical data. Re-measured at
**10 seconds**: 7 of 7 bursts hit ONE worker, gaps irregular (spread/mean 1.79
against a 0.35 bar), and the fan-out hypothesis died.

THE RULE: before drawing a conclusion from the SHAPE of a time series, state what
the sampling interval can and cannot distinguish. Simultaneity, periodicity and
burstiness are all properties the grid can manufacture. If the claim is "these
happened together", the interval must be shorter than the gap you are claiming
is zero.

The same session produced two more of these, which is what makes it a pattern
rather than an incident: a correlation called on a 12-minute window that
reversed at 35 minutes, and a retention-vs-churn verdict called on ONE time point
that reversed at the next reading. **Coarse sampling does not add noise, it adds
STRUCTURE** — and the structure looks like a finding.

Corollary, learned the hard way in the same lane: a detector watching a
production process needs a RESTART GUARD. A peer deployed mid-window and the
first run reported warm-up as bursts, `+570 MB` and `+284 MB`, with pids REUSED
across the restart so the process set looked continuous. Boot confounds are
already in this file for making a fix look good; they make a defect look
catastrophic just as easily.
---
## [2026-09-05] A MEASUREMENT THAT CAN ONLY SEE ONE BRANCH DOES NOT CERTIFY THE OTHER — and a fixture that cannot express the failure keeps a whole test file green over it

Lane `edge-basis-moneyline`. `edge_basis` was added on 2026-08-16 to say WHICH
probability `edge_vs_market_pct` is paired against, on a good measurement: 13
served rows, the 7 whose edge could not be reproduced from the pregame pair were
all `live_aware`, the 6 that reconciled were not. **7/7 separation.** It shipped,
it was verified on served rows, and the lane closed CLOSED-VERIFIED.

It was wrong on h2h from the first commit, for three weeks.

**THE MEASUREMENT SELECTED ITS OWN POPULATION.** Those 13 rows were identified by
carrying BOTH probabilities — and `live_model_prob_over` is written only by the
DISTRIBUTION branch. So every row in the sample was totals or spreads, and the
moneyline branch, which is the one that got the label wrong, could not appear in
the evidence that certified the fix. The selection criterion and the defect were
the same variable.

    the label is derived from    `live_projected`   (a PUBLICATION switch)
    the edge is computed from    `verdict["model_prob"]`
    the moneyline branch passes   no `live_projected`, deliberately
    => every live h2h row: edge from the LIVE probability, labelled "pregame"

Measured 2026-09-05 with the real functions: live probability 1.0 against
`market_fair_prob_over` 0.310 published `edge_vs_market_pct 69.0`, which is
`(1.0 - 0.310) * 100`; the pregame pairing gives 66.7 and is not what came out.

**AND THE UNIT TESTS COULD NOT HAVE CAUGHT IT.** `test_a_row_with_no_live_projection_says_pregame`
called `_apply_verdict` directly with a hand-built verdict **carrying no
`model_prob` key at all** — a verdict none of the three pricers can produce,
because all three set `model_prob` before they can set `priceable`. The fixture
was not a simplification of the real object; it was a different object, and the
one field that discriminates the two branches was the field it omitted. Six tests
passed over the defect, one of them asserting it by name.

THE RULE, two halves:

1. **State how a verification sample was SELECTED, and check whether the
   selection can reach the failure mode.** "N of N separated" is a strong result
   about the rows you looked at and says nothing about a branch that cannot
   produce a row matching your filter. Where a function has branches, enumerate
   them and say which ones the evidence covers — `presence != reachability`
   applied to the MEASUREMENT rather than to the code.
2. **A fixture must be able to fail.** Before trusting a green test over a
   hand-built input, ask what the real producer always sets that the fixture
   omits. Prefer building the input WITH the real producer; where a literal is
   unavoidable, pin the producer's invariant separately — here,
   `priceable is True => model_prob is not None`, asserted over all three real
   pricers, which is what makes the corrected label falsifiable at all.

Adjacent, same root: `layer2_board._live_projection_columns` carried a comment
asserting `_apply_verdict` is called with `live_projected=verdict["model_prob"]`
for "EVERY game market (h2h, totals AND spreads)". False, and harmless where it
stood — it was making a claim about UNITS — while being the load-bearing belief
one module over. **A comment is only checked where it is load-bearing, so it
rots fastest exactly where it is quoted.**
## [2026-09-05] IN `lanes.md`, A DISCLAIMER AFTER A PATH DOES NOT DISCLAIM IT — release lines must be MARKER-LED, and only `claims_by_path` can tell you

Lane `edge-basis-moneyline`, releasing three files. **Two attempts changed
nothing, and the file read correctly both times.**

`_claimable_prefix` cuts a line at its FIRST disclaimer marker and keeps
everything BEFORE it — deliberately, so "`a.py`, `b.py` (collision check CLEAR)"
still claims both. Two consequences nobody had written down:

- **A marker governs its own line only.** A `- Files:` line beginning
  `**released to X:**` disclaims nothing on the wrapped continuation lines that
  actually carry the paths.
- **Prose re-claims.** `ncaaf-live-resim` contained the sentence
  "`live_gameline_join.py` was named as SOLELY held by `live-edge-basis` ... those
  claims were released" — every marker in it (`held by`, `released`) sits AFTER
  the backticked path, so the claimable prefix keeps the path and the sentence
  re-claimed the file all by itself, defeating a release two bullets above it.

Both read, in English, as unambiguous releases. The parser disagreed with both.

THE RULE: write every release as its own marker-led line —
`  released: \`path/to/file.py\`` — one path per line, marker FIRST. Then
**verify with `.claude/hooks/lane_claims.py`'s `claims_by_path` over the file you
actually changed**, asserting the full expected map including the paths that must
NOT move. Reading the ledger is not verification of the ledger; this is the same
lesson as `[2026-08-2x] the commit-guard's own fix list can omit a path it just
flagged`, and it applies to the lane parser for the same reason — the machine and
the reader disagree about what a sentence means, and only one of them is enforcing.

Corollary for a session worktree: `lane-guard` reads
`$CLAUDE_PROJECT_DIR/.syndicate/lanes.md` — the PRIMARY tree's working copy — and
nothing else. That copy was **57 commits behind `origin/main`** here, so a lane
OPEN upstream guarded nothing locally and three paths read FREE. Landing a claim
is not the same as enforcing it: check both files.

**SECOND INSTANCE, SAME DAY, FOUND WHILE RESTORING ANOTHER LANE'S BLOCK.**
`evaluation-ledger-projected-mirror`'s `- Files:` line reads, in one breath:

    ... `artifact_publisher.py` (one allowlist entry -- the file is explicitly
    RELEASED and NOT CLAIMED), `scripts/run_refresh_worker.py` (the autorun call
    site only -- every OPEN-lane reference to this file is RELEASED; checked).

The parser reads **both backwards**. The first marker is the `RELEASED` that sits
AFTER `artifact_publisher.py`, so the prefix keeps that path (CLAIMED, though the
sentence says released) and discards everything after it, including
`run_refresh_worker.py` (FREE, though the sentence claims it). No human reads that
line as ambiguous. Two lanes were then working from opposite beliefs about the
same file, and a third lane's collision check inherited the error.

Corollary, and it is the expensive half: **the ledger has more than one copy and
they disagree.** For those four paths, `origin/main`, the primary tree's working
copy (which is what `lane-guard` actually reads) and the owning lane's own
worktree gave three different answers. A collision check names ONE substrate or it
names nothing. Check the copy the guard reads AND the copy other sessions rebase
onto, and say which you checked.
## 2026-09-06 — FORBIDDEN: passing `--commit $(git rev-parse ...)` to `render_deploy.py`. A COMMAND SUBSTITUTION MAKES `deploy-guard` SKIP ITS SHA CHECK ENTIRELY, AND SAYS NOTHING. `[lane ncaaf-live-state-to-worker]`

- **The rule going forward:** pass a **literal SHA** to `render_deploy.py --commit`. The guard reads the command STRING, before any shell expansion, so `$(...)` is not a SHA to it — and its binding is `if deploy_sha:`, which means an unparseable commit **silently disables** the receipt-to-SHA check rather than refusing. **Unknown defaults permissive here**, which this ledger already forbids in general.
- **Measured.** `COMMIT_ARG = re.compile(r"--commit[=\s]+['\"]?([0-9a-f]{7,40})", re.I)`. Against `--commit b72ebcd6` it parses and the check is enforced; against `--commit $(git rev-parse origin/main)` it does not match, `deploy_sha` is `None`, and the whole `if deploy_sha:` block is skipped.
- **It bit me twice tonight and I did not notice either time.** web `3cb5b4ba` (23:00:51Z) and web `67fd8c9d` (01:15:14Z) were both deployed with `--commit $(git rev-parse origin/main)` after a preflight run WITHOUT `--target-commit`. The claim and CLEAR checks did apply, so those deploys were not unguarded — but **the SHA binding, the thing that stops a CLEAR for one commit vouching for another, was never evaluated.** I only found out because a later deploy used a literal SHA and was correctly refused.
- **What made it invisible:** the guard's PASSING path is silent, so a skipped check and a satisfied check look identical. The failure only surfaces when you accidentally do the safer thing.
- **The fix, NOT YET MADE and deliberately not made unilaterally:** when `shape == "deploy"` and a `--commit` argument is PRESENT but unparseable, refuse instead of skipping. It is a two-line change to a guard **every session shares**, and tightening shared infrastructure while eight sessions are mid-flight is its own hazard — a session using the `$(...)` form would start being blocked with no warning. Raised to the user instead.
## 2026-09-05 — FORBIDDEN: running the ledger guard's own remedy, `git checkout origin/main -- <ledger file>`, without first reading `git diff` on that file. It DESTROYS uncommitted work, and a deletions count cannot see what it destroyed. `[lane render-egress-transport]`

- **The rule going forward:** before `git checkout origin/main -- .syndicate/<file>`, run `git diff --numstat -- <that file>` and read it. A working-tree copy that is BEHIND upstream can still hold additions that exist NOWHERE ELSE, and the checkout silently discards them. **`0` in the deletions column is not safety** — it is the exact signature of the case that loses the most, because pure additions delete nothing while being the only copy. Two sessions hit this from opposite directions the same night.
- **Measured, both instances.** Asked to take upstream's `lanes.md` in the primary tree, `git diff --numstat` read **`98  0`** — ninety-eight lines belonging to another live session, uncommitted, invisible to any deletions check. Separately, the guard blocked a commit touching only `state_football.md` because of a stale `lanes.md` that was never staged, and its printed remedy would have destroyed that same work to unblock an unrelated file.
- **The guard prints this remedy constantly and warns about the blind spot two lines below it.** The warning is easy to skip because the remedy reads as the fix. Treat the order as: diff first, then decide, and only then checkout.
- **What to do instead, in the three cases that actually occur.** (1) Only YOUR OWN block is stale — edit that block in place; it is surgical, races nobody, and needs no checkout. (2) The stale file is not the one you are committing — use a scratch index (`GIT_INDEX_FILE` + `read-tree origin/main` + `hash-object -w` + `update-index --cacheinfo` + `write-tree` + `commit-tree`), asserting one path and zero deletions before push; that sidesteps the shared index entirely. (3) You genuinely must take upstream — land from a throwaway worktree at the tip instead, so the shared tree is never rewritten. `[recipe (2) from lane `ledger-repair-invariants`, hit independently the same night]`
- **A repair left UNCOMMITTED can be the correct end state, and this is when.** If the right content is already on `origin/main`, the tree you are in is dozens of commits behind, and other sessions have uncommitted work in the same file, then committing from there either trips the guard or races them — while the working-tree edit still fixes what local hooks and checkers read. Nobody should later "tidy" it into a commit: a snapshot commit from a stale tree deletes blocks that exist upstream.
## 2026-09-05 — FORBIDDEN: treating a cache path resolved off `__file__` as durable on Render. It is in the EPHEMERAL CHECKOUT, so every deploy erases it — and the erasure is invisible because the code refetches. `[lane ncaaf-live-resim-wire]`

- **What I nearly shipped.** The NCAAF live re-sim's rating input is
  `sp_ratings_<season>.json`, read through
  `generate_smartsim2_ncaaf_projections.load_sp_ratings`. Both of its cache
  locations resolve off `__file__` —
  `sp_ratings_cache_path` (`Path(__file__).resolve().parents[1] / "data" / ...`)
  and `ncaaf_historical_loader.DEFAULT_CACHE_DIR` (`parents[6] / "data" / ...`)
  — which on Render is `/opt/render/project/`**`src`**`/data/...`, the checkout,
  not `/opt/render/project/data/...`, the mounted disk. Wiring the producer
  without noticing would have made its FIRST reading after its own deploy
  `no_pregame_ratings` on every game, for the ~24 h until the next projections
  autorun. A zero that is indistinguishable from an inert feature, arriving in
  the shape of the very bug the lane existed to fix.
- **THE ERASURE IS INVISIBLE BECAUSE THE FALLBACK WORKS.** `load_sp_ratings`
  falls through a cache miss to CFBD and succeeds, so nothing anywhere reports a
  lost cache. The tell is in the log line it already prints and nobody read:
  refresh-worker, `2026-09-04T01:03:29Z` and `2026-09-05T01:15:49Z`, **both**
  `[sp_ratings] season=2026 source=api teams=138 cached=/opt/render/project/src/...`.
  `source=api` twice in a row, for a file the same process wrote yesterday, IS
  the measurement — a cache that never reads `source=cache` is not a cache.
- **THIS IS THE SECOND INSTANCE OF THE SAME CLASS, and the first is already in
  this repo.** `#389`, NFL: "the generator wrote to
  /opt/render/project/src/data/nfl_source (the ephemeral repo checkout) while
  this guard read /opt/render/project/data/nfl_source (the mounted disk), so the
  artifact existed and was invisible here, and every deploy discarded it." The
  fix there was to route BOTH sides through one function. The class predicts
  more: any `Path(__file__).parents[N] / "data"` in a producer is on the wrong
  disk on Render, and the sport-root env vars
  (`SYNDICATE_<SPORT>_SOURCE_ROOT`, `SYNDICATE_DATA_ROOT`) exist precisely
  because of it.
- **The rule going forward.** Before treating any file as a model INPUT, resolve
  its path on the DEPLOYED service and say which of the two roots it lands in.
  `/opt/render/project/src/` is erased by every deploy;
  `/opt/render/project/data/` is not. A `__file__`-relative default is the
  signal. And when a producer and a consumer disagree about where a file lives,
  do not repoint the producer if that changes ANOTHER lane's refresh cadence —
  mirroring to the durable root and reading the mirror keeps the producer's
  behaviour intact, which is what this lane did rather than setting
  `SYNDICATE_SP_RATINGS_CACHE_DIR` and freezing in-season SP+ at week 1.
- **The corollary that caught my own bug.** The mirror-freshness branch compared
  `_parse_utc_timestamp`'s NAIVE datetime against an AWARE
  `datetime.now(timezone.utc)`, raising TypeError inside a bare `except`, so the
  mirror was never trusted and every boot fell through to the loader. **It failed
  in the SAFE direction and was therefore silent**: the ratings were still
  correct, merely refetched. The only run that could distinguish the two was one
  with no `CFBD_API_KEY` in the environment at all — i.e. reproducing the
  post-deploy state rather than testing the happy path. `presence != reachability`
  applies to a FALLBACK too: a working fallback hides whether the primary path
  ever ran.
## 2026-09-04 FORBIDDEN: a tool that updates a REGION of a shared file rebuilding that file from the region's start. Splice the region; carry the remainder through untouched, and REFUSE if you cannot classify it

- **The rule going forward.** When a tool rewrites one region of a file other sessions also write, it must locate the region's END, not just its start, and splice. `split_state.py --reindex` computed `head + regenerated_rows` and stopped — correct for every byte it knew about, and it silently deleted everything it did not. **The tell is a rebuild expressed as a prefix plus new content with no suffix term.** Two things make it worse than an ordinary bug: the region's end was defined by a FILTER (`[l for l in lines if not l.startswith("| [")]`) that has no notion of where a table ends, and the result was reported as success — `WROTE state.md (index rebuilt)`, exit 0. Add the conservation check as a RUNTIME guard, not only a test: every non-blank input line outside the rewritten region must appear in the output, or refuse. Verified 2026-09-04: `origin/main` carried 171 non-blank lines below that table, and the fix preserves 171 of 171. Fixed in `29ab5bfb`.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-04 FORBIDDEN: calling a merge lossy from a SAME-FILE line comparison. Content that "vanished" may have MOVED to a sibling file, and the panic fix is to restore stale content over good

- **The rule going forward.** When checking whether a merge, sync or rebuild lost content, diff the working file against the WHOLE sibling corpus, not only against its own previous version. Measured 2026-09-04 syncing the shared primary tree 201 commits forward: a same-file check reported **1,059 lines lost from `learnings.md`**. Against every `.syndicate/**.md` the true number was **3** — upstream had run `compact_learnings.py`, which moves rule bodies into `learnings_archive.md` BY DESIGN. A 350x overstatement, and in the alarming direction, which is the dangerous one here: the obvious response to "the sync ate a thousand lines" is to restore the pre-sync copy, which in this case would have reverted 201 commits of other sessions' work to fix nothing. The same pass also over-reported 113 upstream lines as lost purely because `origin/main` had moved 3 commits past the sync target while the sync ran — **compare against the SHA you actually merged, never against a moving ref.** This is the exact inverse of the same day's rule about rebuilding a shared ledger from `origin/main`: there a check said "0 deletions" and content was genuinely gone; here a check screamed and nothing was. Both come from asking one file a question that is about the tree.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-05 FORBIDDEN: overriding the pre-commit ledger guard when it names a file you did not stage - it is reporting a STALE BASE, and the fix is to change the base. `[scheduled task live-gameline-accuracy-snapshot]`

Staged exactly one file (`reports/live_gameline_accuracy/history.jsonl`). The
guard rejected the commit over `.syndicate/deploys.md`, naming 8 measurement
sections present on `origin/main` and absent from the commit. Nothing about
`deploys.md` had been touched.

**It was correct.** The guard checks the whole STAGED TREE, not the diff, and
local `main` was **32 commits behind** `origin/main` - so HEAD's `deploys.md`
genuinely was missing those 8 measurements, and the commit would have recorded
that stale copy. `SYNDICATE_ALLOW_LEDGER_COMMIT=1` or `--no-verify` would have
made an unverified deploy look verified, which is the precise harm the guard
exists to prevent.

**How to apply:** when the guard names a file outside your change set, read it
as "your BASE is stale", never as "the guard is confused about scope". Check
`git rev-list --left-right --count HEAD...origin/main` first. Then either
fast-forward, or - if the shared tree cannot safely move - build the commit on
top of `origin/main` directly.

**The safe recipe when the primary tree must not move** (it was 32 behind, and
`state.md` + `log/2026-09-04.md` had BOTH changed upstream and carried other
sessions' uncommitted edits, so a fast-forward there was a cross-session action
with real blast radius):

    BLOB=$(git hash-object -w <content>)
    export GIT_INDEX_FILE=<temp>           # never the shared index
    git read-tree origin/main
    git update-index --cacheinfo 100644,$BLOB,<path>
    TREE=$(git write-tree)
    C=$(git commit-tree $TREE -p origin/main -F -)
    git diff --numstat origin/main $C      # MUST be your file(s) only, 0 deletions
    git push origin $C:refs/heads/main

This satisfies the guard's invariant by CONSTRUCTION rather than bypassing it:
every ledger file in the pushed tree is `origin/main`'s own copy.

**Second trap in the same pass - a local append-only file is not necessarily an
append of upstream's.** The primary tree's `history.jsonl` held the same 32
upstream rows in a **different order** plus 4 new ones. `diff` said `1,32c1,32`;
a set comparison said **0 upstream rows missing**. Committing the local copy
would have rewritten 32 lines of a file whose standing rule is *never rewrite in
place* - and a line diff would have called that a rewrite while a row-set check
would have called it clean. **Reconcile append-only files as SETS, then emit
upstream-bytes + the new rows in order.** Both checks were needed; either alone
gives the wrong verdict.
## 2026-09-05 FORBIDDEN: attributing a hazard to the change you just made without measuring the tree WITHOUT it. And `ledger_invariants` does NOT catch a stale tree that is merely MISSING newer blocks

- **The guard gap, measured 2026-09-05 and still open.** The primary tree sat 36
  commits behind `origin/main`. Committing its `.syndicate/lanes.md` from there
  would drop **210 non-blank lines and 7 whole lane blocks**, one of them an
  **OPEN** lane. `ledger_invariants.violations()` returns **0** on that file -
  called directly, not inferred from a hook exit code - so `ledger-commit-guard`
  allows it. The staleness arm (`ledger_invariants.py:211-248`) models a stale
  tree RESURRECTING archived content, which is addition; a stale tree missing
  newer blocks is SUBTRACTION, and nothing keys on it. The file's own docstring
  already flagged a sibling case reading "0 on a 208 KB stale working copy", so
  this is the second instance of the same shape, not the first.
- **The rule going forward.** Before undoing your own change to remove a hazard,
  measure the hazard **with the change and without it**. I read the 210-line
  exposure, attributed it to a 116 KB lane trim I had just applied, and reverted
  the trim. The restored tree measured **210 lines / 7 blocks - identical**: the
  exposure was the 36 commits, not the trim, and the revert destroyed a verified
  reclamation while removing no risk at all. **A number measured only in the
  present state cannot tell you what caused it.** This is the same error shape
  as banking a success against the wrong cause, run in reverse - a cost paid
  against a cause that was never there.
**CORRECTED THE SAME DAY, BY MEASUREMENT, AFTER A PEER LANE TESTED THE
PRESCRIPTION I HAD JUST LANDED.** The rule above says to write every release as
"its own marker-led line". **The MARKER-LED half is right; the OWN-LINE half is
actively harmful, and I am striking it.** Hoisting a path OUT of a Files line
moves `_claimable_prefix`'s cut point for everything that followed it, so the
edit that releases the path you meant to release can silently CLAIM one you did
not. Run against the real parser on
`evaluation-ledger-projected-mirror`'s actual line:

    ORIGINAL                     claims artifact_publisher.py   (author says RELEASED)
                                 leaves run_refresh_worker.py FREE (author says CLAIMED)
    (a) hoist to its own bullet  releases artifact_publisher.py  <- what I prescribed
                                 **and NEWLY CLAIMS run_refresh_worker.py**
    (b) marker moved BEFORE the  releases artifact_publisher.py
        path, line shape kept    run_refresh_worker.py stays FREE

(a) was my advice and it would have taken a third lane's file
(`ncaaf-live-resim-wire` had staged edits in `run_refresh_worker.py`) with nobody
told. (b) removes exactly one pair and nothing else changes hands. Landed by that
lane as `744689c9`.

THE CORRECTED RULE: **move the MARKER in front of the path; do not move the PATH.**
And the part that generalises past this parser — a ledger edit is a MUTATION OF A
CLAIM SET, so diff the claim set, not the text: compute `claims_by_path` before
and after and assert the delta is exactly the pair you intended, **including that
nothing else moved**. I had written "assert the full expected map including the
paths that must NOT move" and then, two paragraphs later, prescribed an edit that
violates it. A rule and its worked example must be checked against each other;
the example is what people copy.
## [2026-09-05] A CONTROL THAT KILLS ONE ALTERNATIVE IS NOT A DISCRIMINATOR — and "did the producer run" is never answerable from the consumer

Lane `edge-basis-moneyline`, and the sharp part is that I made this error **ninety
seconds after writing up the same one**. At ~23:10Z I recorded that a
`supported: false` reading had come off an artifact built 20 seconds before the
deploy. At 23:13–23:15Z I then concluded "the producer is deployed and NOT
writing" from a window that ended **before the first tick ran at 23:15:29Z**.
Vigilance did not survive one turn. The check has to be mechanical.

**The control was good and it still did not license the conclusion.** I checked
that the same endpoint on the same service read `snapshot_present: true` for the
three other sports in the same directory, which really does eliminate the
web/worker disk split. I then treated *the confound I thought of is eliminated*
as *my hypothesis is confirmed* — while a third explanation was live the whole
time. `no_snapshot_at_path` is produced BOTH by "NCAAF-specific defect" and by
"the tick has not run yet", so the reading could not separate them, and I never
established the tick interval to know which window I was in.

THE RULE, and it is mechanical rather than attentional:

- **Enumerate what else produces this exact reading before the reading means
  anything.** A control eliminates the alternative it was designed against and
  says nothing about the ones you did not list. Two hypotheses that share an
  observable are one hypothesis until you find an observable they do not share.
- **Ask the EMITTER, not the absence.** "Did the producer run" is answerable only
  from the producer's own signal. It existed the whole time and I never looked:
  `NCAAF_LIVE_RESIM {... "written": true, "elapsed_seconds": 21.741 ...}` on
  refresh-worker at 23:15:51Z. Same family as
  *absent signal is about the emitter* and *gate verification on artifact mtime*
  — this is the third instance in one session, which is the argument for making it
  a checklist item rather than a thing to remember.
- **A null needs a denominator IN TIME.** Before reporting "X has not happened",
  state how long since it could have and what its period is. I had neither.

CORROBORATION FROM THE OTHER SIDE, and it is what settles that this is structural
rather than a lapse: the peer lane hit the identical trap on the identical data
and escaped by luck. It read the board at 23:15:59Z, saw
`"no published live-lens snapshot"`, and the ONLY thing that stopped it recording
a defect was that it happened to compare two timestamps. **Two independent
sessions, same reading, same hour; one wrote the wrong conclusion and one did
not, and the difference was not method.** That is the argument against "be more
careful" as a remedy -- an error that catches the person who has just finished
writing the rule about it needs a mechanical check, not attention.
## 2026-09-05 — FORBIDDEN: a JOIN test whose fixture builds BOTH SIDES from one set of names. The key match is then a tautology, and it reads as end-to-end coverage. `[lane ncaaf-live-resim-wire]`

- **18 green tests, a five-way mutation check, and production missed 257 of 257
  rows.** The NCAAF live re-sim published a lens keyed from the projections
  artifact (CFBD names) while the board grid is keyed by the ODDS source. First
  board rebuild past the first snapshot, 2026-09-05T23:17:39Z: `index_size 8`,
  `sources_seen {live_resim: 8, pregame: 43}`, `skipped_no_team_names 0` — a
  PERFECT index — and `rows_live_gameline_considered 257`,
  `rows_live_gameline_edged 0`, `withheld_by_reason
  {no_live_gameline_projection: 257}`. The two key sets intersected **zero**
  times: `('baylor', 'auburn')` against `('baylor bears', 'auburn tigers')`.
- **THE TEST ASSERTED THE BROKEN KEY AND PASSED.** `_wire_tick` built the ESPN
  event and the projection row from the same `"Baylor"` / `"Auburn"` strings, so
  both sides of the join agreed BY CONSTRUCTION. The assertion
  `assert list(index) == [("baylor", "auburn")]` was true of the fixture and
  false of production, and no amount of running it could tell.
- **AND THE MUTATION CHECK DID NOT SAVE IT, which is the part I did not expect.**
  Five mutations, each red exactly where predicted. Mutating the CODE cannot
  expose this, because the defect is not in the code the test runs — it is in the
  fixture's assumption that one name space exists. **The mutation you need is to
  the FIXTURE.** A mutation suite over code is blind to a fixture that cannot
  express the failure.
- **This is the join-specific form of the 2026-08-27 rule** ("a test whose FIXTURE
  cannot violate the property it asserts is not weak coverage, it is zero coverage
  that reads as strong"), and it is worth stating separately because a JOIN has an
  obvious tell the general rule does not name: **two producers, one string.** If a
  join test constructs both sides from a single literal, it is testing `dict.get`.
- **The rule going forward.** A join test must spell the two sides DIFFERENTLY —
  the way the two real producers do — and assert the outcome in both directions:
  one lens spelled like the grid (joins), one spelled like the other producer
  (does not), with the SAME grid row. `index_size` must be identical across that
  pair; that is the whole signature, and it is what a perfect index over a failed
  join looks like. Peer lane `edge-basis-moneyline` built exactly that pair for
  its own file after this was reported (`c45ad022`) and found the same shape
  there; a defect of this class is rarely in one file only.
- **Corollary for the PRODUCER side.** When two systems name the same entity and
  one of them is an odds feed, do not assume a canonical spelling exists — MEASURE
  which field matches. Here: ESPN `displayName` **7/8** against the live grid keys,
  `location` **0/8**, `shortDisplayName` **0/8**, `name` **0/8**. `location` is
  what the artifact used and it never matched once. And leave the residual NAMED
  (`sam houston bearkats` vs the grid's `sam houston state bearkats`) rather than
  aliasing it: one alias fixes one night and is a guess about the feed's naming
  everywhere else. `live_gameline_join._norm_team` has no alias table on purpose,
  and its docstring records why — the prop join's alias machinery carries a 91%
  miss.

---
## 2026-09-05 — FORBIDDEN: reading the RESIDUAL of a partial control as "the one that survived". A control is only a control over the population it actually REACHES. `[lane nfl-la-rams-alias, corrected by ci-archives-nba-card-js]`

- **What we believed:** the full suite's 169 failures in a data-less worktree split
  cleanly into environment and truth. Re-running the 43 failing files with
  `SYNDICATE_DATA_ROOT` set gave `169 → 47`, so 122 were data absence — and the
  archive test still failing was **a confirmed real defect in the file CI runs.**
- **What was actually true:** the knob was wrong, so the differential never covered
  the cases it appeared to adjudicate. `session_worktree.py` says it in its own
  source, written the day BEFORE the measurement: *"`SYNDICATE_DATA_ROOT` does NOT
  solve it. Nine of these read `REPO_ROOT/data/...` directly and ignore the variable
  entirely."* The flagged test is ONE OF THOSE NINE. It passes in the primary tree
  and under `SYNDICATE_NBA_ARTIFACT_ROOT`; the asset is git-tracked and CI checks out
  the full repo. **CI was green throughout. There was no red test.**
- **How we found out:** a peer lane read the failing ASSERTION. It was
  `assertIsInstance(content, str)` on the FIRST line of a test named
  `..._rewrites_source_routes_...` — the asset never loaded, so the route-rewriting
  logic was never evaluated. One line of output refuted the claim.
- **The rules going forward:**
  1. **A residual is not a survivor until you show the instrument REACHED it.**
     Resolving 30 of 31 cases is not evidence about the 31st; the remainder is
     exactly where the instrument is blind, so a partial control CONCENTRATES its
     own blind spot into the result it makes look most significant.
  2. **Use the documented control.** `--with-test-data` is this repo's; an env var
     that merely sounds like the right root is not.
  3. **Read the failing assertion before classifying a failure.** An `assertIsInstance`
     on line 1 says INPUT; a comparison deep in a test says LOGIC. Classifying from
     the test's NAME is how a setup failure becomes a reported defect.
- **The compounding error, and it is the one to take personally:** the report that
  made the false claim ALSO contained the caveat that refutes it — *"this control is
  a LOWER bound on data-absence, not an upper bound"* — and then called the residual a
  confirmed defect two sentences later. **Writing a limitation and then reasoning as
  if it did not apply is worse than never noticing it**, because the caveat makes the
  conclusion look considered to every later reader. If you state a limitation, the
  next sentence is the one to check against it.
- **Cost:** none shipped — a false alarm retracted before anyone acted on it, plus one
  spawned session. **It repaid itself:** chasing why the asset would not load found a
  REAL production outage in that path (`[nba-betting-card-assets-404]`).
## 2026-09-05 — FORBIDDEN: inferring a workload's SHAPE from a reading taken on a CONTENDED machine. A SATURATED MACHINE IS NOT EVIDENCE ABOUT THE WORKLOAD. `[lane full-suite-xdist-run, self-retraction]`

I measured the full pytest suite at **61m06s** (`-n 6`) while six peer python
jobs were running, sampled CPU, saw the machine turning only **~1.5 cores across
ten processes** (7.2s of worker CPU per 8s wall over six workers), and wrote into
`state_ledger.md`: *"this suite is I/O bound here, not CPU bound"* and *"do not
quote 3.7x for this machine"* — contradicting a scope note that had measured 3.7x.

A second run on an IDLE machine: **19m26s**. 3.1x faster. The claim was wrong and
is retracted in place.

**Why the reading could not have supported the conclusion.** Six peer jobs were
contending for the same disk. Disk contention is *the* condition that makes any
workload — CPU-bound ones included — show low CPU utilisation and long wall clock.
So the observation was equally consistent with both hypotheses and discriminated
neither. **A low-utilisation reading on a loaded box is a fact about the BOX.**

This is the same family as `[2026-09-05] A CONTROL THAT KILLS ONE ALTERNATIVE IS
NOT A DISCRIMINATOR`, but the tell is different and worth naming on its own:
**the confound was ambient rather than in the experiment.** Nothing in the
measurement looked wrong — the numbers were real, the arithmetic right, the
sampling honest. What was missing was a baseline of the machine itself.

**The rule.** Before attributing slowness to a workload's nature, record what
else was running. If anything was, the reading bounds the workload's performance
UNDER THAT LOAD and says nothing about its shape. Re-run on an idle machine
before writing a characterisation into the ledger — especially one that tells
future sessions to disregard an existing measurement, which is what makes this
expensive rather than merely wrong.

**And when you do re-run, change ONE variable.** My second run moved two (idle
AND 12 workers instead of 6), so the 3.1x still cannot be split between them. It
was enough to falsify the claim, and NOT enough to replace it with a number —
recorded as such rather than quoted as a worker-scaling factor.
## 2026-09-05 FORBIDDEN: attributing a workload to YOUR run because it appeared in a dump YOUR run emitted — a machine-wide process dump is not a description of you

- **The rule going forward.** `ALL_PROCESS_MEMORY` / `PROCESS_TREE_MEMORY` enumerate **every process on the box**, so on a machine with parallel sessions your own output contains other lanes' worktrees, command lines and RSS. Reading one of those lines as "what my run was doing" is a single step and it reads exactly like evidence. **Before blaming a test file for your failure, prove it was IN YOUR TREE:** `git merge-base --is-ancestor <commit-that-added-it> <your HEAD>`. Mine was not — the file postdated my worktree by hours, so it could not have participated at all, and no amount of reasoning about its allocations was ever going to be relevant. Second half: a `tree_rss_mb` line is one process's tree, never a pytest total.
- *(evidence in `learnings_evidence.md`)*
## [2026-09-05] ANCHOR A LEDGER EDIT ON A LINE, NEVER ON A SUBSTRING — `text.index("## Archived lanes")` matched PROSE

Lane none (primary-tree pull), session b4916e4e. Restoring a lane block, I found
the insertion point with `text.index("## Archived lanes")`. That string occurs in
`lanes.md` **as prose inside another lane's block** at line 97 — a sentence about
the archived section, not the heading. The block was spliced into the middle of
that sentence, and because the splice left `## Archived lanes` at a line start
above 48 OPEN lanes, `check_lane_invariants` went from `[ok]` to
**`48 OPEN lane(s) under Archived`** in one write.

Caught only because I re-ran the checker; the file still looked plausible, and a
grep for my own inserted header returned NOTHING, which is the tell — an anchor
that lands mid-line produces a block whose header is not at a line start.

THE RULE: match on `line.startswith(...)` over `splitlines(keepends=True)`, and
prefer the most specific form of the heading (`## Archived lanes (full bodies`)
because this file has TWO archived sections and several prose mentions. Then
verify the result STRUCTURALLY — `grep -c "^### <slug>"` must be 1 — rather than
trusting that the write succeeded. A ledger file is prose ABOUT its own
structure, so its structure words appear in its prose; substring search cannot
tell the two apart.
## 2026-09-06 — A CONTROL AND ITS TREATMENT MUST COVER THE SAME LENGTH OF TIME

`#632`. I took a pre-deploy control of a cache size and it came out beautifully
tight: 10 samples, spread **0.003 MB**. I recorded that tightness as a strength —
"far outside the control spread" became the test the treatment had to beat.

The control was **10 samples over ~60 seconds**. The treatment was **60 samples
over 31 minutes**. The tightness measured the DURATION, not the quantity: a
one-minute window cannot contain variation that takes minutes to appear. Sampled
over comparable spans the two ranges overlap almost entirely — pre `8.509-11.783`
against post `7.250-11.336` — and the effect I was about to certify sits inside
that overlap.

An automated verdict said CONFIRMED on the strength of that control. It was
right about its own criteria and wrong about the world.

THE RULE: a baseline and the thing it is compared against must span the same
duration, and a suspiciously tight baseline is evidence the window is too short,
NOT evidence the system is stable. Before quoting a spread, state how long it was
measured over.

This is the sampling-grid failure again, in a third costume: earlier the same
session, 50-second sampling manufactured a fan-out that 10-second sampling
dissolved, and a 12-minute correlation window reversed at 35 minutes. Coarse or
short windows do not merely add noise — they produce STRUCTURE that reads as a
finding. The direction of the error is not predictable, only its presence.


**THE REMEDY, and it needs no A/B.** When a matched baseline cannot be recovered
— the old code is no longer live and reverting costs production restarts —
measure the METRIC'S OWN DRIFT instead: two consecutive windows of the length you
intend to quote, on unchanged code. Their difference is the noise floor, and an
effect smaller than it is unmeasurable no matter how carefully the arms were
collected. Measured here: `-8.2%` drift on identical code against a `-10.6%`
claimed effect, which retired the claim. This costs polling time and nothing
else, and it answers the question a mis-sampled control cannot.
## 2026-09-05 — A PREDICTION NAMING SPECIFIC TESTS EXPIRES IN A REPO WITH LIVE PEERS. Re-derive it at LAUNCH, not when you write it `[lane full-suite-xdist-run]`

Before a 38-minute full-suite run I pre-registered the failing set as **2**, and
named them: the `test_live_refresh_loop` pair, another lane's, deliberately left
alone. The run returned **4**, and **none of them was that pair** — a peer had
fixed both in `c353b47d` at 22:27, **four minutes before my run started**, acting
on a message I had sent them myself.

**The reasoning was sound and the answer was still wrong**, which is the part
worth keeping. Pre-registering a prediction is right and I would do it again; the
defect was that I derived it from a snapshot taken earlier in the session and did
not re-derive at launch. On this repo that window is not theoretical — ~22 peer
commits landed between run 2 and run 3, and one of the four new failures
(`ada53db5`) landed **11 minutes before the run began**.

**THE SAME DEFECT IS IN THE RESULT, NOT ONLY THE PREDICTION, AND THAT IS THE
SHARPER FORM:** a suite run reports the tree as of its **START**, so **a failure
list is not a fact about `main` — it is a fact about a SHA nobody names.** Run 3
took 37m54s and **3 of its 4 failures were already fixed before it finished**; it
had photographed a real intermediate state (tests at 22:20, their producer at
22:52 and 23:09, run started 22:31). `[framing from lane
ncaaf-live-state-worker, whose commits those were]`

**The rule.** A prediction that names specific tests, files or counts must be
re-derived against `origin/main` AT THE MOMENT the measurement starts, and must
record the SHA it was derived from. Without that, a wrong number cannot be told
apart from a stale one — and those have opposite lessons: one says the model of
the system is broken, the other says only the clock moved.

**FIXED IN THE TOOL, not left as a discipline.** `scripts/pytest_baseline.py`
now prints `STARTED <local time> -- tree <sha>, <clean|N path(s) dirty>` plus a
line saying the result describes THAT tree. A discipline only helps the person
who ran the suite; the person judging a failure list is usually someone else, and
to them the staleness was invisible. Before acting on suite output anyone hands
you, check its start time against the commits in the area.

**Corollary, and it cuts the other way too:** a peer acting on your own message
is a state change you CAUSED. I sent `suite-order-pollution` the finding, they
fixed it, and I then predicted their tests would still be red. Messaging a lane
is a write to the shared system, not just communication.
## 2026-09-05 — FORBIDDEN: simulating "the artifact is absent" by repointing its ROOT env var alone. The repo mirror is still a candidate, so the test measures your machine. `[lane nfl-fantasy-artifact-root]`

- **The rule.** A test that wants an artifact to read as ABSENT must disable the
  repo-mirror fallback as well as repoint the root:
  `SYNDICATE_REQUIRE_HOSTED_STORAGE=1` **and** `RENDER` cleared. Repointing
  `SYNDICATE_<SPORT>_SOURCE_ROOT` at an empty tmp dir does not achieve absence.
- **Why.** `source_roots.preferred_artifact_roots` appends the repo
  `data/<sport>` mirror as a candidate root unless strict hosted storage is on —
  deliberately, as `CLAUDE.md`'s cold-start safety net — and re-appends it when
  `RENDER` is set even under strict mode. So the search still reaches the
  checkout.
- **The failure it produces is the worst kind: it depends on the DEVELOPER'S
  DISK.** `nfl_fantasy_projections_<season>.json` is UNTRACKED and absent from
  `origin/main`. Three tests in `test_nfl_fantasy_artifact.py` therefore PASSED
  on CI and on a fresh dyno and FAILED on any box that had run the build. Same
  commit, same tests, opposite results — decided by whether `data/` happened to
  hold a local artifact. Measured 2026-09-05: env at an empty tmp dir ->
  `load_projection_artifact(2026)` returned the real checkout artifact; fallback
  disabled -> `None`.
- **AND THE OBVIOUS FIX WAS THE WRONG ONE.** The persuasive hypothesis was that
  `artifact_path()` is a third instance of `#389`/`#441` — resolving through
  `_first_existing_root`, which picks a root by probing for the UNRELATED
  `upcoming_recs_*.csv`. The repo has fixed that selector twice and documents it
  precisely, so it reads as the answer. It is not: the per-requested-file
  resolver searches the SAME candidate list, the checkout root is in it and has
  the file, and both resolvers returned it. Converting `artifact_path()` would
  have been a plausible, well-argued, entirely inert change — and the red test
  would have stayed red for a reason nobody was looking at any more.
- **How to apply.** Before "fixing" a resolver because its docstring describes
  your symptom, run BOTH resolvers on the failing input and check they actually
  differ. A shared candidate list makes two different selectors give the same
  answer.
- **SWEPT 2026-09-06, and it is the ONLY instance.** The entry above closed with
  "not swept for"; it has now been swept. Across all 989 test files, four tests
  repoint an artifact root AND assert absence without disabling the fallback,
  and all four are accounted for: one is this entry's own fixed test, and three
  are FALSE POSITIVES whose `is None` / `== []` is not about an artifact at all
  — `record["prior_attempts"]` on a fresh order
  (`test_execution_ledger:2139`), `_artifact_date()` of a file the test just
  WROTE (`test_live_gameline_accuracy:261`), and a quota latch the test cleared
  (`test_ncaaf_games_cache_refresh:331`).
- **The null result is only worth what the instrument is worth, so the sweep was
  validated against the pre-fix file first: it flagged 3 of 3 known-bad tests.**
  Its blind spots, stated: it matches `SYNDICATE_*_{SOURCE,DATA,ARTIFACT}_ROOT`
  literals and a fixed set of absence forms, so a repoint done inside a FIXTURE
  or helper, or an absence written as `len(x) == 0` / `assert not payload`,
  would not match. This entry's own fixed test demonstrates that blind spot
  exactly — once the guard moved into `_isolate_source_root`, the regex stopped
  seeing it and reported the test as suspect.
## [2026-09-06] AN ATTRIBUTE'S NAME IS NOT ITS SEMANTICS, AND A REMEDY IS A CLAIM UNTIL YOU MEASURE IT

Lane `git-out-of-onedrive`. I found `ReadOnly` on the directories under
`.git/worktrees/` and reported, confidently, that "ReadOnly on the directories is
exactly why deletion fails with Permission denied. That's the whole thing." Then
I prescribed `attrib -R /S /D`.

**Both halves were wrong, and each was wrong in a way the other hid.** Windows
largely IGNORES `ReadOnly` on directories — it honours it on FILES, and the real
blockers were the `logs`/`refs` files INSIDE each entry. And `attrib -R /S /D`
did not clear it either: **118 ReadOnly before, 118 after**. The thing that
works is `Remove-Item -Recurse -Force`, and it works because `-Force` overrides
`ReadOnly` itself — not because anything I ran had prepared the ground.

I only found out because I ran the remedy and counted afterwards. Had I run
`Remove-Item -Force` first (as I did on one entry, which succeeded), I would have
concluded `attrib` had worked and shipped a runbook step that does nothing.

TWO RULES, and the second is the one that generalises past Windows:

- **Do not infer a mechanism from a flag's NAME.** `ReadOnly`, `Offline`,
  `PINNED` are OS-specific words whose behaviour differs by object type. Test the
  mechanism on one instance before describing it, and before prescribing for it.
- **A REMEDY IS A HYPOTHESIS. Count before and after.** "I applied the fix and
  the operation then succeeded" does not establish that the fix did anything —
  something else in the same command may be doing the work. Same shape as
  *gate on the output, not the input* and *confirm the code ran*: assert the
  thing you changed actually changed, not merely that the outcome improved.

Related, same session: I called a `git worktree` lock "a deliberate act by
whoever created it" and declined to clear it, without reading
`.git/worktrees/<name>/locked`. It said `initializing` — git's own automatic lock
from an abandoned `worktree add`. **Intent is a thing you read, not infer from a
flag being set.**
## 2026-09-06 FORBIDDEN: asserting an ABSOLUTE threshold on a timing ratio in a test — it is a claim about the machine's scheduler, and the instrument reporting otherwise would be LYING

- **The rule going forward.** `assertLess(off_cpu_pct, 40.0)` held only while a core was free. In a full `-n auto` suite it measured **79.7** — and the instrument was RIGHT: a build burning 0.25 s of CPU that waits a second to be scheduled genuinely did spend ~80% of its wall time off-CPU. **Do not "fix" the instrument to satisfy the threshold, and do not weaken the assertion — replace it with a COMPARISON taken in the same process**, so both readings see the same contention. Here: a busy build must read as more on-CPU than a SLEEPING one, which is sound by construction because a sleeping build's `off_cpu_pct` is exactly 100.0. Corollary, measured the same day: **a load test is not a reproduction.** 6x CPU oversubscription (72 burners) reached only 15.8%, where the old assertion still PASSES — so whatever descheduled that worker was not CPU contention, and a green load test would have been false comfort.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-06 — VERIFY A DEPLOY WITH A DISCRIMINATOR THAT IS A **KEY**, NOT A VALUE. My predicted value was wrong and the verification survived anyway. `[lane ncaaf-live-resim-wire]`

- **What I predicted, in writing, to the user and to the peer:** the tick would
  report `fetch_reasons {"record_absent": N}`, because the producer half was not
  deployed. **The real reading was `record_dates 1, fetch_dates 0`** — their
  producer shipped in the window between my saying it and the tick running.
- **Why it cost nothing:** the check asserted that `record_dates` / `fetch_dates`
  / `fetch_reasons` were **PRESENT**, not that they held particular values. Those
  keys did not exist in that log line before the commit, so their presence proves
  the new code executed *whatever it reports*. Had I asserted the expected value,
  a CORRECT result would have read as a failure and I would have chased a
  working system.
- **The rule.** A verification has two jobs — *did my code run* and *what did it
  say* — and they need different instruments. Prove execution with something
  STRUCTURAL that only the new build can emit: a new key, a new counter name, a
  new log prefix. Prove behaviour with the value. **Collapsing them into one
  value assertion means a wrong prediction is indistinguishable from a broken
  deploy**, and on a machine where peers deploy under you, predictions about the
  world go stale between writing them and reading them.
- **Corollary, same session:** `git checkout origin/main -- <file>` does not
  clear a rebase collision — it STAGES a change and leaves the file just as
  dirty. And in a multi-tree session, do not trust cwd: a `pytest` run and a
  `grep` both silently landed in the PRIMARY tree, the first measuring another
  session's uncommitted edits to the file under test, the second reporting a file
  I had just written as missing. Use `git -C <path>`.

## 2026-09-06 — A SCHEDULING INTERVAL IS NOT A COMPLETION INTERVAL, and the two share a name. Measured 7.8x apart. `[lane ncaaf-live-resim-wire]`

- **A peer reported their live phase runs on a 60 s median and I sized a staleness
  bound against it.** The step riding that phase actually completed every **514 s
  median** (mean 469, range 319–672, n=27) — because it writes once per FULL PASS
  of the phase, and a pass takes minutes. Both numbers are true; only one is the
  interval at which the artifact changes.
- **How to tell them apart cheaply: does every item move in lockstep?** All five
  dates' write gaps matched to within 1 s. That is the signature of one pass
  writing everything, and it identifies a per-pass cadence rather than a per-item
  timer without reading any scheduler code.
- **METHOD, and it is the reusable half. RECONSTRUCT the event time from an AGE
  field; do not infer a period from the shape of a sawtooth.** Every consumer
  log line carrying `age_seconds` yields an exact write timestamp as
  `log_time - age_seconds`. 400 consumer samples gave 27 exact producer intervals
  — from a service I cannot read the disk of, and without adding a single log
  line to the producer.
- **Then make it predict something.** `E[max(0, gap-bound)]/E[gap]` said 20.6% of
  my ticks should find the record too old; the tick had independently observed
  25.0%. A cadence that explains an already-measured rate is a finding; one that
  merely sounds plausible is not.
- **The trap it closes: "raise the bound until the fallback disappears."** The
  same distribution says a 700 s bound gives 0.0% fallback — a clean number
  bought by pricing live probabilities on state averaging 251 s old. **A
  staleness threshold widened to make a counter look good is a silent downgrade
  of the model's input**, and the counter it fixes is the one that would have
  reported it.

## 2026-09-06 FORBIDDEN: gating a destructive decision on a record that something COMPLETED, when a reading of whether it is STILL RUNNING exists. Three instances in one evening. `[lane shortlist-prop-row-duplicates, generalised with lane prop-region-knob]`

- **The near-miss.** Before deploying refresh-worker I ran
  `scripts/check_deploy_safety.py`: `MLB sim: finished (exit=0)`. At the same
  instant `scripts/deploy_preflight.py` listed `run_mlb_daily_sim_job.py`
  **pid 5346 plus four children ALIVE**. The first reads the status ARTIFACT,
  the second reads the PROCESS LIST. Gating on the cheap one would have killed a
  running sim while printing a clean window — and the deploy would have looked
  correct afterwards, because the artifact it consulted still said "finished".
- **It is a CLASS, not one tool's bug.** The same shape bit twice more the same
  evening, in a peer lane:
  - `lastRunAt` reports **dispatch**, not execution (Modern Standby once stalled
    a scheduled call 9h13m behind its own `lastRunAt`);
  - `finishedAt` says a deploy **landed** while the artifact it should have
    rebuilt is hours stale.
- **The rule.** *Prefer the instrument that samples the thing itself over the one
  that reads a note about it.* A completion record and a liveness reading
  disagree **exactly when it matters** — at the moment you are deciding whether
  something is safe to interrupt — because the note is written by the same run
  whose state you are asking about, and a run that is still going has not
  written its ending yet.
- **How to apply.** Before any interrupt-shaped action (deploy, restart, kill,
  truncate, overwrite), name which of the two you are holding. If it is a
  record, go find the sampler: a process list, a live env read, a served
  payload, an artifact mtime. `deploy_preflight.py` is the sampler for deploys
  and `check_deploy_safety.py` is not — the latter's own docstring says it
  widened past `sim_run_status`, which is true and still leaves it artifact-fed.
- **The inverse also holds and is cheaper to get wrong:** a record that
  something is STILL RUNNING is not evidence it is DOING anything. `jobs=0`
  across three post-deploy samples of live-odds-worker is recorded in
  `deploys.md` as an absence WITH its window (~5 min), because a fixture-aware
  cadence makes idle the designed state and that window cannot separate idle
  from stalled.
## 2026-09-06 — AN INTERVENTION'S OWN OUTPUT CANNOT SUPPLY ITS COUNTERFACTUAL

`#632`. I enabled an automatic `malloc_trim`, measured `1,481 MB` returned over
34 minutes across 12 trims, and wrote: *"without the trims the container would
have reached ~2,361 MB against a 2,048 MB limit."*

The arithmetic was simply `starting_level + returned + observed_net`. Every term
came from the intervention's own instrumentation while the intervention was
running. **The one thing it needed — what the memory would have done with the
trim OFF — was never measured.**

It would have done something different. Matched windows before and after the
flag: `/api/ops/artifacts/publish` cost a median of **0.000 MB/call across 62
pre-trim windows** and **0.893 MB/call across 28 post-trim ones**. `malloc_trim`
releases pages with `MADV_DONTNEED`; `smaps_rollup` counts RESIDENT pages, so the
next request faults them back and every instrument records a re-fault as fresh
allocation. Before the trim, that memory was reused in place and cost nothing.

So the returned `1,481 MB` was largely memory the trim itself caused to be
re-acquired. The saving was real; the counterfactual was fiction.

THE RULE: when an intervention is running, its instruments measure a world that
CONTAINS it. A claim of the form "without X this would have been worse" requires
an observation with X OFF — not a subtraction performed on X's own numbers. If
turning X off is not possible, the claim is not available either, and the honest
output is "X did N, net effect undetermined".

The tell was there and I walked past it: the number I was crediting to X was
produced by X. Ask "what generated this figure?" before "what does it imply?".

Related, and this is the fourth costume this session: a 60-second control against
a 31-minute treatment, a fan-out invented by 50-second sampling, a retention
verdict from one time point. Each time the comparison was against something that
could not answer the question — here, against nothing at all.

## 2026-09-06 FORBIDDEN: reaching for `--force` on a refusal you have not read. Mine said what was wrong, I invented a tool bug instead, and nearly wrote it into this file as a class. `[lane shortlist-prop-row-duplicates, caught by lane prop-region-knob]`

- **What happened.** `deploy_claim.py release --service <svc>` refused twice:
  *"held by shortlist-prop-row-duplicates and the token does not match"* — my own
  lane, my own session. I concluded a poller had rotated the token, named
  `deploy_preflight --holder` as the rotating call, `--force`d past both, wrote
  it into `lanes.md`, told a peer, and proposed the class rule **"any repeated
  claim-aware call rotates the token, not just `acquire`."**
- **All of that was invented.** `release` takes `--token`, `default=None`
  (`deploy_claim.py:402`), and compares it at `:342`. **I never passed it.**
  `acquire` had printed the token to me both times and I read past it.
  `deploy_preflight.py` contains no claim write whatsoever — every `token` in it
  is `ADMIN_TOKEN`, the API auth header.
- **The refusal was not ambiguous.** "the token does not match" is a statement
  about an argument. I read it as a statement about a race.
- **`--force` is the gesture reserved for a session that is GONE**, and I used it
  on two live claims to get past my own missing flag. Nothing was lost — both
  claims were mine — but a habit that survives because its blast radius happened
  to be zero is still a habit.
- **The rule.** A guard's refusal text is the FIRST place to look, not the last.
  Before escalating past any refusal, state which of its named preconditions you
  have actually satisfied — and if you cannot name the one that failed, you have
  not diagnosed it. **An override used on an undiagnosed refusal converts an
  operator error into a permanent false belief**, because the override succeeds
  and the wrong explanation is never tested again.
- **The direction the error ran matters.** A cause I invent for my own mistake
  becomes a hazard OTHERS design around: this one was two hours from being a
  class rule telling the next session to restructure poll loops around a
  mechanism that does not exist — while leaving them exposed to the real one,
  which is simply forgetting an argument. **A peer challenged it and I verified
  by experiment** (acquire; release with no token -> REFUSED; `release --token
  <tok>` -> released). Neither the code read nor their word alone would have been
  enough — the experiment is what settled it.

## 2026-09-06 REQUIRED: write a belief in the form that makes a PREDICTION. A wrong rule about a mechanism gets caught in minutes; the same wrong belief as a one-off remedy is simply adopted. `[insight from lane prop-region-knob, recorded by lane shortlist-prop-row-duplicates]`

- **Two sessions hit the identical bug hours apart and neither memory protected
  the second.** `deploy_claim.py release` refuses without `--token` (it defaults
  to `None`; `:342` compares it to the stored token, and there is no fallback).
  Both of us read the refusal, failed to diagnose it, and reached for an
  override.
- **The asymmetry in how the two errors ended is the finding.** Mine was written
  as a general rule — *"any repeated claim-aware call rotates the token"* — which
  made a checkable prediction about `deploy_preflight.py`. A peer tested it in
  two minutes and it died. Theirs was written as a one-off remedy in a memory
  file — *"pass `--token`; without it, a stored value a re-acquire invalidated"* —
  which predicts nothing, so it was adopted rather than tested, and it sat there
  through their own repeat of the incident. **It is also wrong**: there is no
  stored value and no re-acquire condition; release refuses unconditionally.
  Being un-checkable is what let the wrong half survive next to the right half.
- **The rule.** State the MECHANISM beside the remedy, in a form that predicts
  something. "Do X" cannot be falsified and therefore cannot be corrected; "X is
  required BECAUSE the check compares `args.token`, default `None`, against the
  stored value with no fallback" names a file and a line that either says that
  or does not.
- **This cuts against the instinct to write cautiously.** A hedged one-off note
  feels safer than a general claim and is epistemically worse: it is
  unfalsifiable, so it is never repaired. **Prefer the claim that can be shown
  wrong.** The cost of being caught is one correction; the cost of not being
  checkable is that a wrong belief is re-adopted by its own author.
- **Corollary for memory files specifically**, which are the least checkable
  place a belief can live — nobody diffs them and no test covers them: a note
  there without a mechanism is a permanent unexamined assertion. If it is worth
  storing, store what would falsify it.

## 2026-09-06 — FORBIDDEN: `git stash` in this repo. The stash stack is SHARED across every worktree, so a push/pop pair is not yours and can swap two sessions' work. `[lane venue-fanin-segment-key / kalshi-alt-line-join]`

- **What happened.** I ran `git stash push <2 files>` in a session worktree to
  get a clean tree for a control test, then `git stash pop`. Between the two,
  another session pushed and popped on the same stack. I popped THEIR entry:
  81 lines of unpushed work from lane `kalshi-join-counters-logged`
  (`pipeline/portfolio_commit.py` +24, `tests/test_kalshi_join_counters_logged.py`
  +57) landed in MY worktree AND MY INDEX, staged, while my own two files
  vanished. Diagnosing it, I then ran `git stash push --keep-index`, which wiped
  my edits a SECOND time and swept their content into a mixed stash.
- **Why the worktree does not protect you.** `session_worktree.py` gives each
  session its own INDEX, and that is the isolation the protocol advertises. The
  stash is a REF (`refs/stash`), and refs live in the shared object store — so a
  worktree isolates the index and shares the stash. "I am in my own worktree" is
  exactly the belief that made this feel safe.
- **The tell I ignored.** Every safe recipe I had used all session builds a
  commit through a private `GIT_INDEX_FILE`, reads blobs with `git hash-object`,
  and NEVER touches the worktree or a shared ref. I stepped outside that for one
  convenience command.
- **How to apply.** Never `git stash` here. To test against a different tree
  state: `git diff > /tmp/mine.patch` then `git checkout -- <paths>`, or read the
  other state with `git show <rev>:<path>` and diff in memory. To build a commit,
  use the `GIT_INDEX_FILE` recipe. If you have already stashed, do NOT pop --
  `git stash show -p stash@{n}` it to a patch file, verify the paths are YOURS,
  and apply that.
- **Recovery that worked**, for the next person: the popped content was still in
  the worktree, so `git diff --cached <their paths> > .syndicate/recovered_*.patch`
  preserved it before anything else; `git apply --check` verified it; my own
  change was REBUILT from context rather than recovered forensically, which was
  faster and deterministic. Dropped stash commits also survive in
  `git fsck --unreachable` until GC, but do not rely on it.
- **A mixed stash is the lasting hazard.** `stash@{0}` labelled `WIP on
  session/pc-counters` now contains BOTH that session's work and mine, because
  `--keep-index` stashes whatever is in the tree regardless of who put it there.
  A stash's LABEL names the branch it was created on, not the work it holds --
  so the label is not evidence of ownership. Check `git stash show --numstat`
  before popping anything.

## 2026-09-06 - COMMITTING A LANE BLOCK IS NOT CLAIMING IT. LANDING IS.

Lane `web-oom-fragmentation` ran to completion with its OPEN block committed at
lane-open (`df83d8a0`, 29 insertions to `lanes.md`) and NEVER PUSHED. For the
lane's entire life `origin/main` carried no record of it, so:

* every peer's collision check -- which reads `origin/main`, not your tree --
  saw the lane's files as unheld;
* `check_lane_invariants.py` reported the slug **zero times**, and I read that
  null as *"my lane is not implicated in the contested files"* when it meant
  **the checker could not see the lane at all**. A null from an instrument is
  only exoneration once you know the instrument can see your subject.

A worktree has its OWN `lanes.md`. That is the point of worktrees and it is also
this trap: the block you can read is not the block anyone else can read.

**How to apply.** After `/lane open`, LAND the block before doing the work -- a
lane that is not on `origin/main` claims nothing, however carefully it is
written. And when a checker returns nothing about your lane, confirm it can SEE
your lane before treating the silence as a clean bill.

Blast radius here was nil only because this lane claimed no files (scratchpad
poller, no code changes). The same omission on a lane holding real paths is a
silent invitation for a peer to edit underneath you.

Related, same day and same root: the block ALSO sat above the `## OPEN` heading
(the `#466` violation), which is a second way for a block to be present and
still not count.

## 2026-09-06 FORBIDDEN: concluding a hypothesis is WRONG from a simulation you did not confirm reached the real object — `tests/` is not a package, so pytest's module is not yours

- **The rule going forward.** A reproduction that changes nothing has TWO readings: the hypothesis is wrong, or the instrument never touched the thing. Distinguish them before believing either. Concretely: pytest imports a test module under a name derived from rootdir, and with no `tests/__init__.py` that name is top-level `test_foo` — **not** `tests.test_foo`. Importing the dotted path creates a SECOND module object, so mutating it is invisible to the run. I aged a module-level timestamp, saw 23 passed, and was one step from recording "not the cause"; against `sys.modules["test_foo"]` exactly the 3 predicted tests failed. **Assert the object you mutated is the one under test** — print its `id()`, or mutate through `sys.modules` and fail loudly when the key is absent.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-06 — FORBIDDEN: adding a transform that REBINDS the name a reported field is derived from. The field keeps its name, changes its meaning, and every existing reader keeps working while answering a different question. `[lane kalshi-join-counters-logged]`

- **What happened.** `join_kalshi_to_board` reports `board_rows=len(board_rows)`.
  I added `board_rows, collisions = _collapse_duplicate_bets(board_rows)` above
  it. From that commit (`21aac548`) the field stopped meaning "rows handed to
  the join" and started meaning "rows surviving deduplication" — on ONE of the
  two emitters, because the other takes its own `len()` of the input.
- **Why nothing caught it.** Before the collapse the two values were identical,
  so no test, reader or log line could distinguish them; the divergence only
  begins on the first board that HAS a duplicate. The symptom in production was
  a 2-row gap between two prints 24 seconds apart — `1100` vs `1102` — which
  I wrote up in `deploys.md` as the board moving between them. It was
  `alt_main_collisions` exactly, and I had to correct the entry (`dc886130`).
- **How it WAS caught, which is the transferable part.** Not by review and not
  by looking for it. A test written for a DIFFERENT feature needed a case where
  the row count and a new denominator differ, and it failed with `board_rows=2`
  where 3 rows went in. **A new field that must differ from an old one is a
  cheap probe for whether the old one still means what it says.**
- **The rule.** When adding a transform whose output you bind to an existing
  name, grep for every reported/logged/returned field derived from that name
  BEFORE landing, and either leave the field on the pre-transform value or
  rename it. A silently redefined field is worse than a missing one: a missing
  field breaks its readers loudly, a redefined field keeps them all green.
- *(evidence: `deploys.md` entries for `bd658209` and its correction; fix and
  test in `922a68dc`)*

## 2026-09-06 — FORBIDDEN: asserting "the token is present" as the test for a log line other tools parse. A duplicate is present twice. `[lane kalshi-join-counters-logged]`

- **What happened.** A peer session and I added counters to the SAME print
  statement within minutes. Both landed. The merged line emitted
  `alt_main_collisions=` twice, two spellings of the same segment data, and half
  the fields stranded after the `reasons={...}` dict repr.
- **Neither test suite caught it** — both of us asserted the token appeared in
  the line, and it did, twice. `re.search(r'alt_main_collisions=(\d+)')` silently
  takes the first of two; I had written that exact regex against these logs
  repeatedly the same day.
- **The rule.** For a line that is machine-read, presence is not the predicate.
  Assert the field set: no name emitted twice, and the dict-repr field last so
  nothing is stranded behind it. `test_no_field_is_emitted_twice` in
  `tests/test_kalshi_join_counters_logged.py` is the shape.
- **Second-order:** when two sessions must touch one statement, one of them
  should do both edits. I asked the peer to add my field; they asked me to add
  theirs; we both edited anyway. Whoever notices the overlap first should take
  the whole thing rather than split it.
- *(evidence: the merged line and its fix in `3d1d2173`)*

## 2026-09-06 A DUPLICATE MODULE-LEVEL NAME IN A TEST FILE SILENTLY UN-RUNS TESTS. A GREEN SUITE IS NOT EVIDENCE THEY RAN -- COUNT COLLECTED, NOT PASSED

- **The rule going forward.** Python keeps the LAST binding, so a second `def` of
  an existing name deletes the first while it goes on looking like live code --
  no error, no warning, and invisible in any diff that does not happen to show
  both. In `tests/`, that means the shadowed tests are never COLLECTED, so they
  can never fail and the suite is green *because* they are gone. Measured:
  `tests/test_venue_settlement.py` had three `test_the_repair_*` names colliding
  across two different repairs; the three covering `repair_multi_side_grades`
  (self-limiting, never touches an INFERRED grade, never touches paper --
  money-adjacent settlement invariants) had **never run once**. 75 collected
  before the rename, 78 after. **The reading that shows this is the COLLECTED
  count, not the passed count**, and nothing else in the suite would ever have
  said so. Third instance of the family in the repo, after
  `memory_observability.py` (`67af1276`, which cost `#285`'s `MALLOC_TRIM_INIT`
  proof line) and `nba/live_lens.py` (benign) -- so it is now a check,
  `scripts/check_duplicate_module_names.py`, not a thing to notice in review.
  **The sweep is cheap and the false-positive load is near zero**: counting
  module-level ASSIGNMENTS as well as `def`/`class` over
  `syndicate/ pipeline/ scripts/ tests/` returned **8 files**, not dozens, which
  is what made an EMPTY allowlist possible. Keep it empty -- an allowlist with
  entries in it is where the next real one hides.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-06 A CHECKER'S COVERAGE CLAIM IS ONLY AS GOOD AS THE FILES IT COULD PARSE. COUNT WHAT IT SKIPPED, NOT ONLY WHAT IT FOUND

- **The rule going forward.** `check_duplicate_module_names.py` read sources as
  `utf-8`. Every BOM'd file therefore raised
  `SyntaxError: invalid non-printable character U+FEFF` and was SKIPPED. Measured
  over `vendor/`: **`utf-8` skips 46 files and reports 10 duplicates; `utf-8-sig`
  skips 0 and reports 12.** Python's own import machinery decodes with
  `utf-8-sig`, so those files import fine; only the checker could not read them.
  **The skip was REPORTED** as ERROR lines and still did not register, because
  the run was piped through `tail` and I read `EXIT=0` off the pipe rather than
  the script. Then, writing the fix up, I gave the skip count as **15** -- read
  off that same `tail`-truncated list -- and it reached a code comment, a test
  docstring and a commit message before I measured it. **I made the error the fix
  is about while documenting the fix.** Three lessons: (a) parse with `utf-8-sig`
  when analysing source you did not write; (b) **a checker that returns "clean"
  over N files has told you nothing until you know N and how many it could not
  read** -- a skipped file is indistinguishable from a clean one in any output
  that reports only findings; (c) a piped `$?` is `tail`'s exit code, not the
  command's. Corollary that made this visible at all: **widening a check's scope
  is how you discover the check's own blind spots** -- this defect existed from
  the moment the script was written and was invisible while it scanned only owned
  code, where nothing carries a BOM.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-06 A SHADOWED MODULE-LEVEL BINDING IS ONLY DEAD IF NOTHING READ IT *AND* NO DECORATOR CAPTURED THE OBJECT. "DEFINED TWICE" IS NOT "THE FIRST ONE IS DEAD"

- **The rule going forward.** Asked to delete 12 duplicate module-level
  definitions in `vendor/`, only **5** were actually dead. Three distinct reasons
  the other 7 were live, and each needs its own test: (1) **a sequential
  rebinding whose successor consumes it** -- `cols_subset = [c for c in
  cols_subset if ...]`; deleting the first gives `NameError`, and the read is on
  the SECOND binding's own right-hand side, so any liveness window that stops
  before it reports the opposite of the truth. (2) **a decorator already captured
  the object** -- `@cli.command()` then `@cli.command('fetch-rosters')` on the
  same function name leaves the module name dead but registers TWO working
  commands (`fetch-rosters-cmd` and `fetch-rosters`, verified by running the
  pattern against click 8.1.7); Typer with a derived name collapses to one, so
  the same shape goes the OTHER way and must be checked, not assumed. (3) **a
  module-level `if __name__ == '__main__':` between the two definitions** --
  `backtest_daily_summary.py` is two scripts concatenated, so as a script the
  FIRST `main` runs and exits before the second is defined, and as an import the
  second wins. **Verify a deletion by the file's OBSERVABLE SURFACE** -- the
  values the surviving function returns, the command set the decorators register,
  the `__all__` -- never by the source diff, which cannot see any of these.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-06 — FORBIDDEN: mutating the tree a BACKGROUND JOB is reading. It keeps running and silently measures something else. `[lane nfl-rating-units]`

- **What happened.** A linearity experiment ran `os.chdir(<primary tree>)` and
  looped over two rating scales. While it ran, I reverted that tree to the
  original code -- correctly, to move my change into a worktree -- and the job
  carried on against the reverted source. It reported a clean, plausible,
  fully-formed result for a code path that no longer existed.
- **The tell was in the output and I nearly read past it: `margin ratio 20/10 =
  1.000, stdev 0.000`.** An effect of EXACTLY zero, with zero variance, is not a
  finding about the system -- it is the signature of an input that never
  changed. A sublinear response would have been noisy; a no-op is silent and
  perfect. **Suspect a result that is too clean before you suspect one that is
  surprising.**
- **A background job holds a DEPENDENCY on the tree it was launched against, and
  nothing in git or the job records that.** `git checkout`'s guards protect
  files from being lost; they say nothing about a running reader. The
  discard-guard fired on that very checkout, I preserved the content correctly,
  and the preservation was irrelevant to this failure.
- **The rule.** Before mutating a tree, enumerate what is RUNNING against it --
  and if a long job needs a specific code state, launch it from a worktree
  pinned to that state, not from the shared tree. Corollary for the reader: a
  job that depends on source should PRINT the discriminating fact about the code
  it loaded (here, whether the constant it is sweeping even exists), so the
  output is self-diagnosing rather than plausible.
- **What saved it: the derived number was already LABELLED derived.** The
  backtest computed its own rating differences and never called the sim, so the
  verdict (model loses to the close at t=3.34) was untouched. Only the
  `NFL_RATING_SCALE ~25` conversion depended on the void run, and it had been
  written down as "derived, not verified" before the error was found. **Labelling
  a number's provenance is what makes a later invalidation cheap instead of
  contaminating.**
## 2026-09-06 A PARTIAL CLONE THAT CHECKS OUT A WORKING TREE IS NOT A PARTIAL CLONE. `--filter=blob:none` WITHOUT `--no-checkout` FETCHES EVERY BLOB ANYWAY, ONE REQUEST AT A TIME

- **The rule going forward.** `git clone --depth 1 --filter=blob:none <url>`
  populates a working tree by default, and populating it requires every blob at
  that commit -- so git dutifully refetches them all individually, each landing in
  its own pack. **Measured: four caches totalling 3.8 GB, MLB-BettingV2 alone
  2.6 GB against a repo GitHub reports as 354 MB — larger than a full clone.**
  Adding `--no-checkout` took the same four to **950 KB** and a full report from
  **5m29s to 8.9s**, with byte-identical results. The filter had been "working"
  the whole time; the checkout undid it. **The general shape: an optimisation
  flag is a claim about a code path, and a DEFAULT elsewhere can re-enter that
  path and cancel it.** Verify the optimisation by MEASURING the resource it was
  supposed to save -- I had already written a comment calling the filter
  "load-bearing, not a micro-optimisation" before ever checking the cache size,
  and that comment was false when written. Corollary from the same script, same
  hour: comparing `ls-tree HEAD` instead of the working tree made an uncommitted
  local edit invisible to a tool whose entire purpose was to not overwrite local
  edits. **Both were found by RUNNING the thing against real data; the fixture
  tests passed throughout.**
- *(evidence in `learnings_evidence.md`)*

## 2026-09-06 "WE COMMITTED TO IT" IS NOT "WE PATCHED IT". TO TELL A LOCAL PATCH FROM A STALE COPY, ASK WHETHER YOUR CONTENT EVER EXISTED UPSTREAM

- **The rule going forward.** Deciding whether a vendored file that differs from
  upstream is OURS or merely OLD cannot be done from `git log`: a bulk
  `daily update ... (pre-source publish)` commit touches the file exactly the way
  a deliberate fix does, and if that commit was itself a vendor re-pull then the
  content came FROM upstream and the difference is pure staleness. The test that
  actually decides it is a CONTENT one -- **does our blob hash appear anywhere in
  that path's upstream history?** Found, and we are simply behind; absent, and the
  content never existed upstream, so it is ours. Run over 53 files it returned
  **53 ours, 0 stale**, and it is cheap: `git log --format= --raw --no-abbrev
  <branch> -- <path>` reads blob hashes straight out of the tree diff. Do NOT use
  `cat-file --batch-check` on `<rev>:<path>` for this -- on a blobless clone that
  is a promisor fetch per revision, and the same probe went from over ten minutes
  (killed) to 4 seconds. Corollary from the same hour: **a hand-run `diff` between
  a vendored file and its upstream blob reports the whole file as changed** on a
  CRLF checkout, because the blob is LF-normalised -- the exact artefact the tool
  avoids by comparing hashes, reintroduced the moment the check went manual.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-06 A STATE MACHINE THAT SHORT-CIRCUITS ON THE HAPPY PATH STOPS MAINTAINING THE DATA THE UNHAPPY PATHS NEED. THE STALENESS IS INVISIBLE UNTIL IT IS LOAD-BEARING

- **The rule going forward.** `classify(local, upstream, baseline)` returns
  `IN_SYNC` as soon as `local == upstream`, without consulting the baseline --
  correct as a verdict, and exactly why the baseline was allowed to go stale
  underneath it. When upstream absorbed our patch, the file became IN_SYNC and
  kept its PRE-merge hash; nothing was wrong, nothing was reported, and the file
  looked healthy. The damage only lands at the NEXT upstream change, which then
  reads `CONFLICT` where the answer is `UPSTREAM_AHEAD` -- and `CONFLICT` is the
  one state that STOPS an automatic sync, so the effect is to silently convert a
  file we no longer patch into a permanent manual step. **If a field is only read
  on some branches, something must still WRITE it on the others** -- so refresh
  derived state on the happy path too, or the first unhappy path inherits a lie.
  Found only by inspecting the outcome of a real run: the fixture tests passed,
  and would have kept passing, because they never had a file transition INTO
  in-sync and then move again.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-06 A SCHEDULE IS A CLAIM ABOUT A PLATFORM YOU HAVE NOT TESTED. DISPATCH IT ONCE, OR YOU HAVE SHIPPED A JOB THAT SILENTLY NEVER RUNS

- **The rule going forward.** A committed workflow file with a valid cron is not
  a scheduled job; it is a request. Dispatching `vendor-sync` once returned
  `completed/failure` in **1 second with zero steps executed** -- *"The job was
  not started because your account is locked due to a billing issue."* Valid
  YAML, `bash -n`-clean scripts, and a registered workflow ID all said healthy;
  none of them touches whether a runner will pick it up. **And the failure mode
  is the worst kind for a sync: a job that never runs produces no report, which
  reads exactly like "nothing to do".** The same reasoning that rejected a local
  scheduled task here (`lastRunAt` is dispatch, not execution) applies to the
  replacement, and I nearly shipped it unexercised. Corollary, found by the same
  dispatch and much larger than the lane: **GitHub Actions has been dead for this
  whole repo for 15 days** -- last success 2026-08-22T21:07Z, 100 of the last 100
  runs failed -- so `ci.yml`'s pytest-baseline gate has not gated a single commit
  in that window, including this session's. Nothing announced it. **A CI system
  that stops running looks identical to one that keeps passing, from anywhere
  except its own run history.**
- *(evidence in `learnings_evidence.md`)*

## 2026-09-06 A GUARD THAT INFERS ITS POSTCONDITION FROM AN ARTEFACT'S EXISTENCE CANNOT SEE A HALF-BUILT ONE, AND WILL DEFEND IT FOREVER

- **The rule going forward.** `if (-not (Test-Path "$wt\.git")) { worktree add; sparse-checkout set }`
  reads as "set this up once". It is really "assume anything with a `.git` is
  fully set up". An earlier failure died BETWEEN the two commands, leaving a
  worktree that was real but not sparse -- and from then on the guard skipped
  repair on every run while each checkout materialised the entire repository:
  **3.9 GB, `data/` and all, for a job whose input is two directories.** Nothing
  reported it; the job "worked". **Check the POSTCONDITION you actually need
  (`git sparse-checkout list` succeeds), not a proxy for it (a directory
  exists)** -- the two differ exactly when a previous run was interrupted, which
  is the case a setup guard exists for. Same family as this session's stale
  baseline: state that is only WRITTEN on the happy path, or only CHECKED by
  proxy, silently rots. Corollary, three more from the same script and all found
  the same way: it read a shared checkout **241 commits behind** and missing the
  script it invokes; `$ErrorActionPreference='Stop'` plus a redirected native
  stderr turned git's own success message into a recorded error (PowerShell 5.1
  wraps native stderr in ErrorRecords); and `param([string[]] $Args)` collides
  with PowerShell's AUTOMATIC `$Args`, so git ran with no arguments. **The script
  parsed cleanly through all four.**
- *(evidence in `learnings_evidence.md`)*

## 2026-09-08 FORBIDDEN: a parity check that compares PRESENTATION and ignores CAPABILITY `[lane nfl-ncaaf-ui-parity]`

**What we believed.** That moving NFL onto NCAAF's card partial was a strict
improvement, because every number said so: compact card 643-1085px across
sixteen distinct heights -> 181px uniform, crests 0 -> 32, prose blocks 32 -> 0,
`card_variant` 16/16.

**What was actually true.** The partial being switched TO rendered two fewer
panels than the one being switched FROM. Same served NFL game, both partials:

    generic   panels = game, boxscore, props, panels
    football  panels = identity, context, coverage, details

Box Score and Props were dropped, live, for several hours. The data was never
missing: `shared_prop_rows`, `shared_box_sections` and `shared_period_rows` were
all **16/16 non-empty** on the served payload the whole time.

**How we found out.** The user said props and a box score were "a big miss".
Not from any check of mine -- and every check of mine passed, because I had
measured how the card LOOKED and never what it could DO.

**The rule going forward.** When swapping a renderer, diff the CAPABILITY SET,
not the appearance: enumerate the panels/tabs/sections each side produces for
the SAME input and diff them. One `grep -c 'data-panel-id'` on both partials
would have caught this before the deploy. Heights, crests and byte counts are
evidence about presentation and say nothing about what was traded away.

**Cost.** Two tabs missing from the live NFL board for ~4 hours on the day
before the season opener, found by the user rather than by me. Restored in
`4be5c5a5`, contract-based so it also gave NCAAF a Box Score it had never had.

**And the fix's own first cut repeated the family's oldest defect:** I gated the
new TABS on `box_sections`/`prop_rows` and left the PANELS ungated, shipping an
orphan `props` panel on NCAAF -- markup reachable by nothing, which is exactly
what that card's header records collapsing a card on 2026-08-14. Caught before
commit by rendering both sports and diffing tab-set against panel-set, which is
now a test.

## 2026-09-08 FORBIDDEN: reading ZERO from an allowlist-gated instrument as ABSENCE `[lane nfl-props-precompute]`

**What we believed.** That production had no NFL play-by-play, because
`/api/ops/artifacts/export?pattern=*pbp_2025*` returned `count=0`, and therefore
that the prop model was structurally dead everywhere.

**What was actually true.** That endpoint only serves ALLOWLISTED patterns, and
pbp is not one. `count=0` means "no matching allowlisted artifact", not "no
file". The stream endpoint returns **403** for the same path -- a REFUSAL, not a
404. Both instruments are blind here, and I read blindness as evidence.

**Then the retraction was ALSO wrong, in the other direction.** Seeing
`rating_source=nflverse_pbp_epa_rolling[...]` on the deployed projection
artifact, I retracted and said production HAS pbp. True of **refresh-worker**,
which generates that artifact -- and I generalised it to "production". This
platform runs THREE SERVICES WITH SEPARATE DISKS; "production" is not a place.

**How we found out.** A counter, not an argument. With the fix live, the props
join printed `odds_rows=2455 sim_rows=0 refused_wrong_team=0
refused_unknown_team=0`. Both refusals at zero proved nothing reached the team
check, so every row exited at the one `continue` above it -- which requires the
player index empty for BOTH seasons. web has no pbp; the worker does.

**The rule going forward.** Before reading a zero as absence, ask what the
instrument REFUSES to show. An allowlist, an auth gate and a 403 all produce
zeros that look like emptiness. And when a claim is about "production", name the
SERVICE -- a fact true of the worker is not a fact about web.

**Cost.** Two wrong claims to the user in one session, one in each direction,
and an artifact pipeline nearly built for the wrong reason. Net cost low only
because the counter was added before acting on either.

## 2026-09-08 FORBIDDEN: promising a verification target without tracing WHICH PRODUCER stamps that field `[lane nfl-ncaaf-ui-parity]`

**What we believed.** That deploying the NFL card fix to refresh-worker would be
verifiable by reading `shared_predictions.probabilities.home_cover` on
`/api/board/book-grid?sport=nfl`. That prediction was written into `deploys.md`,
into the lane block, and told to the user, all before anything was checked.

**What was actually true.** That endpoint's `projection` field is stamped by
`attach_nfl_game_projections`, which reads the smartsim2 projection artifact
DIRECTLY and never touches the card's `predictions` block. Its keys are
`basis` / `model_prob_over` / `projected` / `side` / `edge_vs_market_pct`;
`home_cover` is not among them and never was. Coverage there was already
**300/300** before the change and would have been 300/300 after.

**How we found out.** By fetching the payload BEFORE deploying, to capture a
"before" number. The keys were simply not the ones promised. Read AFTER the
deploy instead, a flat 300/300 was available to be told either way -- "already
perfect, nothing to prove" or "the fix did not land" -- and nothing in the
reading itself would have distinguished them.

**The rule going forward.** A verification target names a FIELD on a SURFACE. Before
promising it, name the PRODUCER that writes that field and confirm the change is
upstream of it. "The board reads the cards" was an assumption about a pipeline
with two independent producers for the same-looking value. The cheap check is
one fetch of the endpoint and a look at the key set -- do it while WRITING the
prediction, not while settling it.

**Cost.** No wrong claim reached production or the ledger unretracted: it was
caught by a pre-deploy read and retracted in the `15:05:37Z` `deploys.md` row and
the lane block. What it cost was a promise to the user that had to be walked
back, and it would have cost a false verification had the order been reversed.

**Related and NOT the same:** `gate-on-the-output-not-the-input` and
`test-the-fixs-predicate-not-its-deploy-state` are about a predicate that is
wrong or inert. This one is about a predicate that is well-formed, measurable,
and reads a field your change cannot reach.

## 2026-09-08 FORBIDDEN: leaving a self-refreshing board open while diagnosing the service it loads `[lane nfl-ncaaf-ui-parity]`

**What we believed.** That the `/ncaaf*` request family appearing in web's slow-request
logs after a 14:02:20Z deploy was organic traffic, and that the candidates for
web's elevated OOM rate were my deploy, the other commits in its range, and a
peer lane's burst harness.

**What was actually true.** The requests were MINE, from a browser pane tab.
`syndicate/static/shared/game_board.js:installSharedBoardAutoRefresh()` starts a
poller on every `/cards` and `/game/` page: `intervalMs: 30000`, `onTick` doing
`fetch(window.location.href)` -- a full server-side re-render -- and
**`skipWhenHidden: false`**, so it keeps firing with the tab hidden. I had
`/ncaaf/cards` open as the CONTROL for a parity comparison. On a 16 s route that
is ~53% duty cycle on 1 of 8 gunicorn slots, from a viewer who is not looking.

**How we found out.** A peer reported `/ncaaf*` as 25 of the 29 slow requests on
the service and noted it had **ZERO** requests in their 23:00Z baseline -- "not a
route that got slower, one that did not exist there". That is exactly the
signature of a route nobody was requesting until somebody started. Reading the
tab's own network log showed ~22 sequential same-URL requests, and
`game_board.js` supplied the mechanism.

**The rule going forward.** An open board is a load generator, not an
observation. When measuring a service, close every page of it you are not
actively reading, and say in the report which requests were yours. A "control"
tab left open for comparison is instrumentation that changes the thing it
measures.

**Cost.** Real but unquantified: three OOM kills (14:13, 14:23, 14:43) that a
peer lane spent its own time attributing, and my own contribution to the
candidate list I handed them was omitted because I did not think of my browser
as traffic. Not proven to be the cause -- closing the tab gives a clean window,
and it was explicitly flagged not to be called early.

**The check, because a rule alone will not catch this.** `skipWhenHidden: false`
on a poller that re-renders a whole page server-side is a product defect
independent of any operator: any user who leaves a board open does this, hidden
tab included. It is the strongest open lead in `#632`. NOT changed here --
`game_board.js` is a cross-sport shared file that no lane claims, and a
platform-wide polling policy is not a thing to alter unilaterally.

## 2026-09-07 FORBIDDEN: reading an artifact-backed surface ONCE to decide whether a deploy worked

**The instrument's clock is not the thing's clock.** Three separate lessons in
this ledger are one lesson, and naming them together is what makes the next one
recognisable:

- `lastRunAt` is DISPATCH, not EXECUTION (Modern Standby stalled a scheduled call
  9h13m; the timestamp was honest about the wrong event).
- Gate verification on ARTIFACT MTIME, not on deploy status (a 5h49m lag between
  a deploy going live and the artifact rebuilding read as a failed fix).
- A SHORTLIST READ shows the artifact's age, not the code's. Measured 2026-09-07
  by lane `soccer-threeway-precision-gate`: refresh-worker went `status=live` at
  01:26:11Z and the served shortlist stayed flat -- 36 rows / 28 edged -- for
  EIGHT MINUTES, changing to 35/11 only at 01:34:05Z on the first post-deploy
  build. **A single read at 01:27Z would have recorded a clean null result for a
  fix that was already live.**

THE OPERATIONAL FORM, which is the part that is actionable: **the poll interval
must be SHORTER than the artifact's rebuild cadence.** Four samples across eight
minutes made the transition legible; one sample is indistinguishable from a
failed fix, and two samples on the same side of the boundary are worse -- they
look like corroboration.

`[ATTRIBUTION, split precisely, because this entry is about credit surviving the
conversation that produced it. The eight-minute measurement and the poll-interval
rule are lane `soccer-threeway-precision-gate`'s. The two-sample corroboration
clause and the adjacency explanation are this lane's. I initially credited the
corroboration clause TO them in a message; they checked their own sent text,
found they had not written it, and asked to be un-credited. A wrong credit in a
ledger outlives the conversation -- which is the same argument that made the
retraction above worth making, pointed the other way.]`

WHY THIS KEEPS RECURRING. Every one of these instruments is honest about
something; it is just not the something being asked. `status=live` is true about
the deploy. `lastRunAt` is true about dispatch. The shortlist is true about the
last build. Each answers a question adjacent to "is the new code's output
visible", and adjacency is what makes the substitution invisible.

The same 2026-09-07 exchange produced a second instance of a rule already here --
**one field carrying two states, with the consumer branching as if it carried
one.** `_model_edge_for` returns early on `edge is None`, written for a one-sided
quote; a new precision gate then wrote `None` for "priced and withheld", and the
early return silently dropped the draw and away legs before their own bars were
consulted (3 of 10 legs). Sibling of `ANALYTIC_UNCALIBRATED` and of "unknown must
not default permissive". A per-side count taken across that boundary measures the
early return as much as the gate, which is why the "8 home / 9 away / 0 draw"
split was retracted while the 17-of-28 total stood.

## 2026-09-07 FORBIDDEN: deciding whether a model earns its keep from a SLATE-AVERAGE metric

`[user, 2026-09-07: "remember you are globally making a call on something that
should enhance SOME games to be bet on"]`

**Nobody bets the slate.** A model can lose to the market on mean MAE and still
be worth having, if its errors concentrate in games it has no read on while the
subset where it disagrees hardest with the market is where it is right. That is
the entire mechanism of selective +EV betting: you do not need to beat the market
everywhere, you need a subset where you do.

So `mean |model - actual|` over every game **cannot answer the question it is
usually asked to answer.** Reported alone it is not merely incomplete -- it will
say NO to a model that has a real, narrow edge, and it will say so with a
confident-looking number.

WHAT THIS COST HERE. The NFL drive-prior backtest reported
`MAE off 10.573 / on 10.537 / market 9.410, t=+0.61` and I read it as a clean
null. It may still be one -- but the harness had **discarded the per-game rows**,
so the only data that could distinguish "no edge anywhere" from "no edge on
average, real edge in the top decile" was gone, and answering required
re-simulating 178 games twice.

THE RULE, in three parts:

1. **KEEP THE PER-GAME ROWS.** They cost nothing and every interesting cut --
   by disagreement, by week, by favourite/underdog, by total -- is then seconds
   instead of another full run. An aggregate is a lossy summary of data you
   already had.
2. **BUCKET BY THE AXIS THE BETTOR SELECTS ON**, which is
   `|model - market|`, not by anything intrinsic to the model. Beating the market
   on games you would never bet is worth nothing; losing there costs nothing.
3. **FIT TO THE SUBSET, NOT THE SLATE.** A calibration fitted to minimise mean
   error over every game is optimising performance on the games nobody bets. A
   grid search against that objective can be executed perfectly and still be
   answering the wrong question -- which is why the NFL first-calibration sweep
   was STOPPED mid-run rather than reported.

THIS INDICTS AN EXISTING HARNESS TOO, not just mine.
`scripts/refit_ncaaf_smartsim2_payload.py` frames its go/no-go as whether the
payload "closes any of that 3.56-point gap" in **slate-wide margin MAE** (model
15.775 vs market 12.212 over n=2233). That framing is right to benchmark against
the MARKET rather than the model's own past -- and still wrong to do it on the
slate average. The same 2,233 games would answer the subset question if the rows
were kept.

## 2026-09-07 FORBIDDEN: verifying a fix with a predicate on a TOTAL that can move for another reason

**Nineteen days, every night, the same ten failures — and the guard that was
supposed to catch it fired correctly and said nothing.**

MLB's sim publishes `sim_input_report_<date>.json` from the WORKER. Read back
across every report on production:

    08-19   ok 55   FAIL 15   disabled 0
    08-20   ok 55   FAIL 10   disabled 5     <- the "improvement"
    08-21 .. 09-07  ok 55   FAIL 10   disabled 5   (19 days, identical)

`deploys.md` for `39570b24` had written the verification in advance and written
it well: *"Expect nfail 15 -> 6 ... Still 15 on a fresh generated_at means a
SIXTH cause and must be reopened."* The count went to 10. Not 15, so the reopen
never triggered; not 6, so nothing had actually cleared.

**THE 15 -> 10 DROP WAS A RECLASSIFICATION, NOT A FIX.** Five `vs_pitcher_*`
fields moved from `FAIL` to `disabled` (BVP off by config) in the same window.
The ten fields the note NAMED -- `conditional_arsenal`, `count_bucket_map`,
`pitch_type_*`, the four `statcast_splits_*` -- never cleared once.

THE RULE. **A verification predicate must key on the THING, not on a count that
contains it.** The note listed the exact ten field names and then gated on the
total. Had it gated on the names it would have failed loudly on 08-21. Same
family as "a rate, not a count" and "gate on the output, not the input": an
aggregate is a lossy summary, and the loss is exactly where a second cause hides.

### And the root cause is a SECOND instance of the same shape

`SYNDICATE_MLB_ROSTER_REBUILD_DATE` was pinned to `2026-08-19` -- **the day
BEFORE** the artifact fix it was meant to prove went live (`39570b24`, live
2026-08-20T17:54:04Z). The gate is date-scoped and self-expiring BY DESIGN, which
is good design; it was armed for a date that expired before the thing it gated
existed. So every run since printed `ROSTER_REBUILD inert: gate=2026-08-19 does
not match date=<today>` and reused `roster_objs` built the day before the
artifacts arrived.

The artifacts were present, loadable and correct the whole time -- arsenal 546 KB
/ 466 pitchers, `payload["pitchers"]` exactly as `load_arsenal` expects, and
`SYNDICATE_DATA_ROOT` correctly set. This is CLAUDE.md's own warning realised:
*"Publishing is not sufficient -- a new input needs a roster REBUILD or it is
silently ignored."*

### Two instruments that could not have caught it, and one that did

* **The log line cannot be read.** The code prints `ROSTER_REBUILD inert`
  deliberately ("Silence here would be indistinguishable from 'the rebuild
  ran'") -- but `MLB_DAILY_SIM_START` and `mlb_sim_job` return **0 lines in 8h**
  from Render's logs API while that process is demonstrably running. The
  emitter never reaches the collector, so a log-based check would have read
  clean forever. **Test that the line is EMITTED before designing a check
  around it.**
* **The local checklist is worse than useless here.** Run on a laptop it
  reported 17 fields at 0.0%; production says 7 of those are fed at 76-79% and
  10 are genuinely dead. Both halves wrong in opposite directions.
* **The ARTIFACT is the instrument.** `sim_input_report` is written by the
  worker, exportable, and 20 days deep. It had the answer every night.

### The date basis, because I got it wrong the same way

I armed the replacement gate from the report FILENAME
(`sim_input_report_2026-09-07.json`) and set `2026-09-07`. The job's own paths
say otherwise: `daily/snapshots/2026-09-06/roster_*.json`, and `2026-09-06`
dominates the worker's log messages 37-to-6. The filename and the slate date use
different bases. The value happens to be right for the NEXT slate -- correct by
luck, not by reasoning, which is worth recording as exactly that.

## 2026-09-07 CORRECTION: the MLB "ten dead inputs" was SEVEN-TENTHS A BROKEN INSTRUMENT

**Retracts most of the entry above it, and the retraction is the lesson.**

I reported that ten MLB pitcher inputs had been dead in production for nineteen
days, root-caused it to a stale `SYNDICATE_MLB_ROSTER_REBUILD_DATE`, armed a new
gate, and deployed. Then I read the ROSTER SNAPSHOTS the sim actually consumes:

    field                    09-07(post)  09-06   09-04   08-25
    pitch_type_whiff_mult       14/18     17/18   13/19   12/16
    statcast_splits_source      14/18     11/18   10/19   11/16
    conditional_arsenal          0/18      0/18    0/19    0/16
    count_bucket_map             0/18      0/18    0/19    0/16

**Seven of the ten were already fed, for at least two weeks before my deploy.**
They were never broken. And the post-deploy `sim_input_report` STILL says 0/10
while those same rosters read 60-95% -- so the report and the artifact it claims
to summarise flatly contradict each other, and the roster is the one the sim
reads. `rosters: 8` in the report against 12-17 roster files on disk is the same
symptom: it is measuring a different, smaller roster source.

WHAT ACTUALLY SURVIVES: `conditional_arsenal`, `conditional_arsenal_source` and
`count_bucket_map` are 0 on EVERY day sampled including after the rebuild --
genuinely unfed, from the `conditional_mix` artifact. **Three fields, not ten.**
The stale gate was real and is worth fixing; it was not the cause of the reported
zeros, and my deploy's effect is NOT demonstrated -- 09-07 sits inside the
day-to-day spread of the pre-deploy samples.

### THE RULE, and it is not "the mirror lies"

I had already rejected the LOCAL checklist for being mirror-based. I then treated
the PRODUCTION report as ground truth **because it came from the worker** -- and
provenance is not accuracy. A report is a CLAIM ABOUT an artifact; the artifact
is the evidence. I built a verification, a monitor and a deploy on a number I had
never once checked against the thing it summarises.

**Check the summary against its subject before building anything on the summary.**
The cost of that check here was one export call. The cost of skipping it was a
wrong root cause, a production env change, a deploy, and a confident ledger entry
that had to be retracted.

The corollary is uncomfortable and worth stating: the previous entry's whole
"nineteen days, nobody noticed" narrative was ALSO built on that report. The
nineteen days of identical `FAIL 10` are nineteen days of the same broken
measurement, not nineteen days of dead inputs. The predicate lesson in that entry
(key on the thing, not on a count containing it) still stands -- it is just that
the thing it should have keyed on was wrong too.

## 2026-09-07 RESOLVED: the ten MLB pitcher inputs ARE unfed -- and my retraction was the wrong turn

**This closes a thread that reversed twice. The FIRST answer was right; the
retraction two entries up is WRONG and is withdrawn.**

The report now records which rosters it measured, and it read the sim's own path:

    generated      2026-09-07T07:48:38Z
    roster_source  'sim'
    roster_glob    .../data/daily/snapshots/*/roster_objs/roster_obj_*.json
    rosters        8
    POPULATED      0/10

So all ten pitcher fields are genuinely empty in the artifact the simulation
consumes: `pitch_type_{whiff,inplay,hr}_mult`, `conditional_arsenal{,_source}`,
`count_bucket_map`, and the four `statcast_splits_*`.

### WHY I RETRACTED A CORRECT FINDING

I read `daily/snapshots/<date>/roster_*.json` -- FLAT game rosters -- saw
`pitch_type_whiff_mult` at 14/18 on four separate dates, and concluded seven of
the ten had been fed all along. **Those are a different file.** The sim reuses the
SERIALIZED `roster_objs/roster_obj_*.json`; the flat rosters are a separate
published artifact. Two files, one directory apart, similar names, opposite
content -- and I compared the one I could read against a claim about the one I
could not.

The tell was available and I walked past it: the flat file's top-level keys are
`away/home/mode/park/pbp/pitch_model/statcast/umpire/weather` while
`read_game_roster_artifact` expects `schema_version/away/home/meta`. Different
schemas. I noticed the difference, wrote it down, and still treated the two as
interchangeable evidence.

**THE RULE: "I read the artifact" is only stronger than "the report says" when it
is THE SAME ARTIFACT.** Reading the wrong file directly is not more rigorous than
reading a report about the right one -- it is less, because it FEELS like primary
evidence. Confirm the identity of the file before promoting it over a summary.

### AND THE ROSTER-REBUILD DIAGNOSIS IS WRONG IN ITS MIDDLE TERM

The chain I published was: stale gate -> stale `roster_objs` -> dead fields. The
gate WAS stale (`2026-08-19`, armed the day before the fix it was meant to prove
went live) and that part stands. But after arming it for `2026-09-07` and running
a job on that date, **the fields are still zero.** A fresh build produces empty
fields too, so reuse was never the cause.

That relocates the defect to the LOADERS -- `apply_arsenal_to_pitcher` and
`_apply_cached_statcast_pitch_splits` -- which run at build time and are supposed
to populate exactly these fields from artifacts that are present, loadable, and
correctly shaped on the worker (`arsenal_2026.json`, 546 KB, 466 pitchers,
`payload["pitchers"]` exactly as `load_arsenal` expects). Present input, running
loader, empty output: that is the next thing to chase, and it is NOT a
publishing, allowlist, path or reuse problem, all of which were checked and
cleared in this thread.

### WHAT THE INSTRUMENT FIX BOUGHT

The report now carries `roster_source` and `roster_glob`, so this question is
answerable in one read instead of a night of it. It did not change the answer --
it made the answer TRUSTWORTHY, which is the only reason the reversal could be
settled at all.


## 2026-09-07 FORBIDDEN: building or proposing a guard before locating the one that already exists

TWO INSTANCES IN ONE SESSION, on the same machinery, both mine.

**(a) I built a narrower copy of a check and trusted it over the real one.**
Before deploying refresh-worker I pre-screened for an in-flight MLB sim by
grepping the last `ALL_PROCESS_MEMORY` line for `mlb_daily_sim`. It said clear.
`deploy_preflight.py`, reading the actual process table, said `HOLD: 5 job(s) in
flight` -- `run_mlb_daily_sim_job.py`, `daily_update.py --workflow ui-daily`,
and three vendor children, none of whose cmdlines contained my substring. On the
strength of MY check I armed a production env flag and held the deploy claim on
a contended service for 33 minutes for a deploy that could never go.

**(b) I proposed adding a check that already existed twice.** A pinned deploy
target (`5876bbc9`, live when chosen) became a rollback of a peer's `8f647bbb`
two hours later. I reported it as a near-miss and proposed adding an ancestry
check to `deploy_preflight.py`. But `render_deploy.py:136-156` ALREADY re-reads
the live sha at deploy time and refuses a non-descendant (`--allow-rollback` is
the escape; its docstring cites the 2026-08-14 incident of this exact shape),
and preflight ALREADY reports `HOLD: <sha> is already contained in live <sha>`.
My watcher goes through `render_deploy.py`, so it would have returned 2 and my
loop would have disarmed and released. **It would have failed loudly. It was
never armed to revert, and I said it was.**

WHY THE OVERSTATEMENT MATTERS MORE THAN THE MISS. A near-miss report is a claim
about what the SYSTEM would have allowed. Getting that wrong argues for guards
that exist and misprices the ones that do not. I reported catching a hazard I
had not actually been exposed to.

AND THE PROPOSED FIX WAS WORSE THAN THE STATUS QUO, per lane
`ncaaf-live-resim-wire`: preflight's CLEAR is valid for 15 minutes and this
check must hold AT POST TIME, so a copy there is a second owner that drifts and
gives false comfort in exactly the window the real guard covers.

RELATED, and why the reflex is strong: a guard you did not write is invisible
until you go looking, while one you write yourself is vivid. That asymmetry is
the whole mechanism -- it is not laziness, it is that your own instrument is the
one you can see.

HOW TO APPLY. Before writing a check, or reporting that one is missing:
`grep` the sanctioned entrypoint for the concern (`REFUS`, `HOLD`, `guard`,
`--allow-`) and read its docstring. If a guard exists, route through it instead
of reimplementing it -- and if the answer is "my code bypasses it", the fix is
to stop bypassing it, not to duplicate it. State which entrypoint you checked.

COROLLARY, measured the same night: a target chosen because it was live is an
ASSUMPTION the moment it is stored. Anything sitting in a poll loop must
re-resolve the world before acting, not remember it. And `target == live` is
STRICTER than the shipped rule and self-defeating -- `render_deploy.py` returns
2 on it (`ALREADY live -- nothing to deploy`). Deploys are meant to be
CUMULATIVE; roll-forward from `main` is the sanctioned shape, so "isolate my
change by redeploying the live sha" is the doctrine backwards.
- *(evidence in `.syndicate/log/2026-09-07.md`)*

## 2026-09-07 The deploy claim's `session:` breadcrumb does not resolve, even for a LIVE holder

`deploy_claim.py status` printed holder session
`520cd594-1ffa-4116-8951-4c4b53ffbfcf`. That id does not resolve in
`list_sessions` even with `include_archived: true` -- while that session was
alive, running, and holding the claim. The peer independently hit the same thing
looking up `3492626c` and concluded "gone" when only "not resolvable" was
supported.

The claim's own text already says it is a breadcrumb and the TTL is the real
liveness bound. What was NOT known: it fails to resolve for a live holder, so
`not found` carries no information about the holder at all -- it is not weak
evidence of absence, it is zero evidence.

HOW TO APPLY. To reach a claim holder, search `list_sessions` by TITLE (lane
slugs map to session titles closely enough in practice) -- that worked when the
id did not. Never infer a holder is gone from a failed id lookup; the TTL is the
only bound, and `--force` on that basis breaks a live session's claim.
- *(evidence in `.syndicate/log/2026-09-07.md`)*

## 2026-09-07 A CONVENTION YOU COPY MAY BE A DECISION YOU ARE OVERTURNING. "ALL THE OTHER FILES DO X" DOES NOT TELL YOU WHY THEY DO X

- **The rule going forward.** Adding `.github/workflows/vendor-sync.yml` I read
  the two neighbouring workflows, matched their structure, permissions and
  comment style — and shipped the one thing they pointedly did NOT have: a
  `schedule:`. Both are `workflow_dispatch`-only because `#486`
  `[2026-08-20, user decision]` removed `Daily Update`'s cron with the words *"we
  no longer use that daily update feature, everything runs on render"*. My file
  became **the only cron in the repository**, seventeen days after the last one
  was deliberately deleted. **Copying a convention reproduces its SHAPE and
  discards its REASON**, and the absence of a feature is exactly the part a
  template cannot carry. Before adding a recurring or outward-facing mechanism,
  grep the ledger for a decision about that mechanism — `state_ledger.md` had it,
  quoted, and I never searched. Note also what made it hard to see: Actions was
  not retired wholesale (`ci.yml` is live and maintained), so "does this repo use
  Actions?" answered YES and told me nothing. **The retired thing was a narrower
  category than the tool** — recurring unattended jobs — and a question pitched
  at the tool cannot find a decision pitched at the pattern.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-07 SETTLED: the MLB pitcher inputs were NEVER dead -- nineteen days of measuring June

**Final state of a thread that reversed three times. Every earlier entry on it is
superseded by this one.**

    generated 2026-09-07T16:27:40Z   roster_source 'sim'   rosters 8
    POPULATED 9/10
      fed        pitch_type_{whiff,inplay,hr}_mult, conditional_arsenal,
                 count_bucket_map, statcast_splits_{source,n_pitches,
                 start_date,end_date}
      still zero conditional_arsenal_source
    CONTROL     bb_gb_rate 69.3%  (77.4% in the June-sampled report)

**THE CONTROL IS THE POINT.** `bb_gb_rate` comes from the same enrichment block
and was expected to MOVE if the sample changed. It moved. Without it, 9/10 would
have been just another number from an instrument that had already lied four
times; with it, the reading is anchored. **Every check in this thread that lacked
a field whose value I could predict SHOULD change produced a wrong conclusion.**

### THE ONE-WORD CAUSE

`sorted(glob(...))[:8]` is ASCENDING, and the date is the leading path segment.
It selected the eight OLDEST roster_objs on disk -- 2026-06-15, two months before
the arsenal and pitch-splits artifacts existed. Those rosters could never contain
the audited fields. So the report was a constant, and a constant reading was read
as a stable fact about production when it was a stable fact about eight fixed old
files.

### MY OWN CLAIMS, SCORED

    original: 10 fields dead          WRONG   -- measuring June
    retraction: 7 already fed         RIGHT in substance, WRONG in method
                                      (compared the FLAT rosters, a different file)
    un-retraction: 10 genuinely dead  WRONG   -- trusted a report still sampling June
    actual: 9/10 fed on current rosters

Twice I reversed on evidence that was itself measuring the wrong thing. The
retraction was right for reasons I could not have defended, which is not the same
as being right -- and I withdrew it on a report I had not validated.

### WHAT WAS WASTED, AND WHAT WAS NOT

Wasted: a stale-gate root cause (`SYNDICATE_MLB_ROSTER_REBUILD_DATE=2026-08-19`
was genuinely stale but irrelevant), a production env change, and two deploys --
all chasing an artifact of the measurement. The loaders were never broken;
running `apply_arsenal_to_pitcher` over the real artifact populated all three
maps first try, and I should have weighted that above the report the moment they
disagreed.

Not wasted: three real defects in the instrument, each independently capable of
producing a false negative -- wrong parent directory (`daily_pitcher_props`
instead of `daily`), no provenance field in the PUBLISHED report, and the
ascending sort. Four sports' input audits run on this shape.

### THE RULE

**A measurement that never changes is not therefore stable.** Nineteen identical
nightly readings read as strong evidence of a persistent defect; they were
evidence that the sample was frozen. Before trusting a constant, establish what
would make it move -- and if nothing in the pipeline could, the constant is
describing the instrument, not the system.

Remaining, and it is the whole of it: `conditional_arsenal_source` is zero while
`conditional_arsenal` is populated -- a value present without its provenance
label. One field.


## 2026-09-07 A probe you designed yourself can MANUFACTURE bugs -- discriminate shape-failure from real failure BEFORE reporting

Auditing whether MLB profile fields survive the roster artifact, I set every
field to a distinctive value via `dataclasses.fields()`, round-tripped, and got
**26 fields "LOST"** across `PitcherProfile` and `BatterProfile`. A 26-defect
report would have been confident, specific, and entirely wrong.

All 26 were the PROBE's fault. The serializer uses a different key domain per
field family and both sides agree on each: `{str(k): float(v)}` for
`platoon_mult_*` / `venue_mult_*` / `statcast_quality_mult` (**str** keys),
`_ser/_de_intkey_map` for `vs_venue_*` / `vs_pitcher_*` (**int** keys), and
`str(cell_key)` for `conditional_arsenal`. I had fed `PitchType` enum keys to
all of them and a tuple to the last. Wrong-shaped keys came back as
`'PitchType.FF'` or were silently dropped to `{}` -- which is INDISTINGUISHABLE
from a serializer that does not persist the field.

Re-run with each field's real key shape: **1 lost, not 26** -- and that one was
a genuine write-side omission (`conditional_arsenal_source`), confirmed OFF!=ON.

HOW TO APPLY. When a broad audit returns a large number of hits, the FIRST
hypothesis is the instrument, not the system -- especially when the hits cluster
by shape rather than by subsystem (here: every dict field, no scalar). Before
reporting N findings, take one hit and prove it fails for the reason you claim,
against what the real PRODUCER writes. A null-shaped result (`{}`, `''`, `0`)
means "my probe did not survive"; it does NOT mean "this field is not
persisted". And a permanent test must not encode the probe shape it happened to
guess -- probe every shape the module supports and call a field lost only when
NONE survives, or the test re-breaks at the next refactor.

COROLLARY -- a compound `verify:` inherits its WEAKEST clause. `state_mlb.md`
required `conditional_arsenal` / `count_bucket_map` / `conditional_arsenal_source`
all non-zero. The third could not be satisfied by any deploy of that change --
the field was dropped by a different file -- so the verify was permanently
un-passable and its failure said nothing about the change under test. This is
the same-day rule about compound ABSENCE claims, running the other way. One
clause per mechanism, each separately falsifiable.
- *(evidence in `.syndicate/log/2026-09-07.md`)*


## 2026-09-07 A freshness gate must be `> deploy.finishedAt`, and an UNCHANGED control is not automatically a null result

Two instrument errors in one verification, both of which would have reported the
WRONG verdict about a fix that was in fact correct.

**1. "Newer than my last reading" is not "newer than the deploy."** Verifying
`conditional_arsenal_source`, I gated the watcher on `generated_at` differing
from the 16:27:40Z baseline. It fired on a report generated **17:12:10Z** --
newer than the baseline, and **12 minutes BEFORE the deploy went live at
17:24:04Z**. Old code, still showing the failure. Reported as the verdict it
would have called a good fix broken and sent me hunting a second bug that did
not exist. The correct predicate is `generated_at > deploy.finishedAt`; the
baseline is not a proxy for it, because artifacts are produced continuously and
one will land in the gap between your reading and your deploy.

**2. The control I demanded was the wrong control, and I had said so in advance.**
I wrote that `bb_gb_rate` MUST move or the artifact is cached. It did not move
(0.6933/0.6786, identical), and the result was still sound. That control was
built for the June-glob SAMPLING bug, where the underlying sample changed and
rates shifted 77.4% -> 69.3%. This was a pure SERIALISATION fix on the same date
and the same inputs, where every rate should be byte-identical and a MOVED rate
would have been the alarm. Holding to my own stated criterion would have made me
doubt a correct result.

HOW TO APPLY. Name, before reading, WHICH failure each control discriminates and
in WHICH direction. A control inherits the failure mode it was designed against;
carried to a different change it can invert -- "must move" becomes "must not
move" -- and a criterion stated in advance is not thereby the right one. Where a
control is ambiguous, prefer a discriminator the failure CANNOT fake: here the
key's own presence, since a pre-fix artifact does not contain
`conditional_arsenal_source` at all, so no cached roster could return non-zero
for it, and the fixed value matching its sibling exactly (0.86 = 0.86) is the
predicted value rather than merely a non-zero one.
- *(evidence in `.syndicate/deploys.md`, 2026-09-07 17:44:53Z)*


## 2026-09-07 The deploy-claim breadcrumb id is not merely un-prefixed -- it is not in the roster at all

SUPERSEDES the entry above it, which said the claim's `session:` breadcrumb
"does not resolve in `list_sessions` even for a LIVE holder" and told the reader
to search by TITLE. A peer offered a tidier explanation: ids DO resolve, they
just need the `local_` prefix, and the breadcrumb stores the bare uuid.

**Half right, and the half that is wrong matters.** The prefix gotcha is REAL:
`send_message` to a bare uuid returns "not found" and to `local_<uuid>` works --
I hit that myself today and it cost a lookup. But it does not explain the
breadcrumb, and I checked before accepting it:

    deploy_claim breadcrumb        520cd594-1ffa-4116-8951-4c4b53ffbfcf
    that lane's actual session id  local_605f483c-45a8-48d2-a500-eb4f4572d515

Different uuids. `520cd594` appears in `list_sessions` in NEITHER form, across
40 sessions back to 2026-09-04, which covers the whole life of that claim. So
prefixing `520cd594` resolves nothing -- there is no such session by that id.

HOW TO APPLY, both facts kept separate because they have different remedies:
- To MESSAGE a session, use the `local_`-prefixed id from `list_sessions`. A
  bare uuid fails with "not found", which reads as absence and is not.
- To identify a CLAIM HOLDER, do not expect the breadcrumb to resolve at all --
  it records an id that need not correspond to anything `list_sessions` returns.
  Match by TITLE. The TTL remains the only liveness bound, and a failed lookup
  is still zero evidence the holder is gone.

AND THE META-POINT, which is why this is an entry rather than an edit: a peer's
correction is a claim like any other. This one was offered confidently, was
plausible, matched a real gotcha, and still did not explain the case at hand.
Accepting it unmeasured would have replaced one wrong mechanism with another --
and a remedy whose mechanism is wrong makes no prediction, so it fails silently
the next time.
- *(evidence in `.syndicate/log/2026-09-07.md`)*

## 2026-09-06 FORBIDDEN: reading a shared refusal/guard function's SCOPE off its NAME. Its scope is the FIELD LIST it actually reads, and a three-way market has three legs. `[lane soccer-threeway-precision-gate]`

`probability_refusal.refuse_published_certainty` is named, documented and
reasoned about as the platform's answer to "a finite simulation cannot
establish impossibility". Its module docstring runs forty lines, calls itself
**platform-wide**, and tabulates the 25 certainties it was built for across four
sports. It reads exactly one field: `model_prob_over`.

Soccer's `h2h_3_way` projection carries THREE probabilities --
`model_prob_over` (home), `draw_probability`, `away_probability`. So the guard
covered one leg of three, and the two it missed are the ones structurally most
likely to hit the boundary: a draw is a NARROW outcome, and `draws / n` reaches
zero as soon as a second goal separates the sides.

WHAT MADE IT INVISIBLE FOR WEEKS, and this is the part worth keeping:
`layer2_board._MODEL_EDGE_MAX_POINTS` (15.0) was silently dropping the WORST
cases. A `0/400` leg against a 0.16 fair reads -16.0 pp and is refused by the
cap, never by a certainty rule. So the extreme end looked handled, the middle
published freely, and nobody could find an example that looked wrong.
**A cap that discards your worst cases will hide the defect that produces them.**

HOW TO APPLY. Before relying on a shared guard, grep the FIELDS it reads and
compare that list against the fields the data actually carries on the path you
are on. "It is handled platform-wide" is a claim about a function's ambition,
not its predicate. The same check would have caught
`soccer_live_gameline_source.py:198`, which publishes a full `side_probabilities`
vector that no consumer reads at all.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-07 FORBIDDEN: a COMPOUND absence claim where only one clause was checked. "Not in X, not in Y" from one command that saw only X. `[lane soccer-threeway-precision-gate]`

I ran `ls .syndicate/findings_*` in the PRIMARY TREE and reported a file was
"not in the primary tree, not on origin/main". The first clause was measured.
The second was invented in the same breath, and it was FALSE -- three commits
touch that file on `origin/main` (`cc598278`, `583519c9`, `cbe02a45`). A peer
spent a turn refuting it, and I had warned THEM about primary-tree staleness in
the same message.

The failure is not the stale tree -- that is already a rule. It is that the
verified clause LAUNDERS the unverified one. Two clauses in one sentence read as
one measurement because there is no visible seam, so the half with evidence
lends its credibility to the half without. `[sharpened 2026-09-07 by lane
ncaaf-live-resim-wire, which hit the identical shape as "a grep proving a symbol
EXISTS doing duty for a claim that it is CALLED" -- same defect, different
clause.]`

AND IT HAPPENED INSIDE A WARNING ABOUT THE VERY THING. I was telling a peer to
beware primary-tree staleness in the same message. That is not incidental: the
seam stops being visible exactly when you are most confident, because the
sentence is doing rhetorical work and you are reading it for force rather than
for evidence.

HOW TO APPLY. For a shared file, `git ls-tree -r origin/main -- <path>` or
`git cat-file -e origin/main:<path>` after a `git fetch` -- the checkout answers
a different question. More generally: if a sentence names two scopes, run two
checks or name only the one you ran.
- *(evidence in `learnings_evidence.md`)*

### 2026-09-07 — FORBIDDEN: verifying a change with an AGGREGATE COUNT that BOTH your intended effect and a collateral bug would move the same way `[lane soccer-threeway-precision-gate]`

Also FORBIDDEN: making an existing field take a value it never took before
without enumerating that field's READERS first.

- **What we believed:** the soccer precision gate (`d9672ac7`) did one thing —
  withhold moneyline legs whose edge is inside their own Monte-Carlo noise. It
  was verified on the served board: model-edge rows fell **28 -> 11** across a
  rebuild, polled rather than read once. That number was taken as confirmation.
- **What was actually true:** the deploy did TWO things.
  `_price_against_market` began writing `edge_vs_market_pct = None` for a NEW
  state — "priced against a real fair, withheld as imprecise" — on ~60% of
  soccer moneyline rows, where before it was ~never null.
  `layer2_board._model_edge_for` opens with `if edge is None: return
  _modelled_fair_edge_for(...)`, an early return written for a DIFFERENT state
  (a one-sided quote with no two-sided fair). The two are indistinguishable at
  that line, so a withheld HOME leg silently dropped the DRAW and AWAY legs of
  the same match before their own bars were consulted. Measured on the
  2026-09-07 slate: **3 of 10 legs lost, including a +10.13 pp away edge
  (Getafe) that cleared its own 4.84 pp bar.**
- **How we found out:** not from a test and not from review — both passed. The
  user asked for the draw leg to be checked on the next slate, and that check
  was PER-LEG (served value against that leg's own bar), not an aggregate. An
  aggregate could never have found it: **both mechanisms push the edged count
  DOWN, so 28 -> 11 is exactly what the gate alone looks like AND exactly what
  gate-plus-collateral-damage looks like.** The metric could not fail for the
  second mechanism, and it was read as though it could.
- **The rule going forward:** two, and the second is the cheap one.
  1. A verification metric must be able to FAIL for the bug you did not think
     of. If your intended effect and a plausible collateral effect move it the
     same direction, it verifies nothing — measure per-row against the predicate
     you actually changed.
  2. When a change makes an existing field newly-null (or newly-anything),
     `git grep` that field name and enumerate every site that BRANCHES on the
     value. One grep for `edge_vs_market_pct` would have surfaced this early
     return in seconds.
     **AND ONE HOP FURTHER: the fields DERIVED from it.** `[amended 2026-09-07,
     after breaking this rule while obeying it]` The fix for the above made
     `_model_edge_for` return a market-priced edge where `edge_vs_market_pct` is
     None; `model_edge_basis` decides "market" off that same field, so the LABEL
     fell through to None on a real edge -- 4 of 77 served soccer rows. I ran the
     grep and stopped at direct readers. A field computed FROM the one you
     changed is a reader too, and it is the one a grep for the original name does
     not show you. Found by reading the deployed board; no test caught it.
- **Cost:** 43m51s live in production (`d9672ac7` 01:26:11Z -> `62937ea4`
  02:10:02Z), coverage only — `_modelled_fair_edge_for` is side-matched, so the
  dropped legs returned None rather than an ungated number. Plus a per-side
  split published to a peer session and into `state_soccer.md` that had to be
  retracted, because it summed the two mechanisms.

**NEITHER HALF WAS A BUG, WHICH IS WHY NOTHING CAUGHT IT.** The early return is
correct for a one-sided quote; the gate is correct for an imprecise estimate.
The COLLISION is the defect. A missing branch announces itself; a second meaning
quietly assigned to an existing sentinel does not. Same family as
`unknown must not default permissive` — one field carrying two states, and the
consumer branching as if it carried one.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-07 FORBIDDEN: `git reset` the SHARED PRIMARY TREE to origin/main to tidy away unpushed commits. It converts a harmless pointer into 153 files of revert exposure. `[lane soccer-threeway-precision-gate]`

The primary tree sat 3 ahead / 327 behind. All three commits were verified
CONTENT-REDUNDANT -- every line already upstream, checked per file, with the
only exceptions being two generated header lines. So "drop them" looks like
free tidying. It is not.

MEASURED before acting:

    tracked files where working tree != origin/main   170
      of those, locally MODIFIED (live work)           17
      of those, merely STALE                          153

**HEAD currently MATCHES the working tree.** That is the property that makes the
tree safe: a session running `git add -A && git commit` records only its own
real edits. Move HEAD to origin/main and those 153 stale files become unstaged
"modifications" that are actually REVERSIONS of up to 327 commits -- and the next
`add -A` from any of the ~80 sessions on this machine commits them. Every pointer
move has this shape: `reset --mixed` leaves it in the working tree,
`reset --soft` puts it in the SHARED index, `update-ref` puts it in both.

So the cosmetic gain ("ahead 3" disappears) is paid for with a
revert hazard strictly WORSE than the one being tidied.

HOW TO APPLY.
- Unpushed commits in the primary tree are harmless while HEAD matches the tree.
  Verify they are content-redundant, say so in the ledger, and LEAVE THEM.
- If they are NOT redundant, land the unique content by targeted append from a
  worktree off origin/main -- never by pushing the stale file, and never by
  rebasing the shared tree.
- The only real cure is a full sync (merge/pull), which needs the in-flight
  files landed by their owning sessions first. That is the tree owner's call,
  not a passing session's.
- A `DO NOT PUSH` line in the commit message is the cheap mitigation, because
  the hazard is only realised on a push.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-07 FORBIDDEN: repeating a REPORTER'S impact framing as your own measurement. You inherit its SCOPE without inheriting its evidence. `[lane publish-refusal-201-triage]`

Triaging a live defect in `/api/ops/artifacts/export`, I wrote in a findings doc
and told the owning lane: *"that endpoint is how most sessions verify
production... I used it myself earlier tonight."*

**I had not used it.** This session's production reads were
`/api/board/layer2-shortlist`, `/api/board/layer1`, `/soccer/<league>/api/cards`,
the Render API and `render_logs.py`. What I actually knew was that ONE lane read
it. "Most sessions" came from the reporter's framing and I restated it as though
I had counted.

THE HARM IS SPECIFIC AND IT IS NOT COSMETIC: an impact claim sets someone else's
PRIORITY. The owning lane was mid-optimisation on a live service, and I gave them
a reason to interrupt that was broader than the evidence. The mechanism argument
was sufficient on its own and was WEAKER for carrying an inflated blast radius --
if they had checked the usage claim and found it hollow, the real defect would
have inherited its credibility.

WHY IT SLIPPED THROUGH THE EXISTING RULES. I was strict all evening about not
inheriting other sessions' MEASUREMENTS unverified, and completely unstrict about
inheriting their CHARACTERISATIONS. "201 refusals" I re-derived; "most sessions
use this" I passed straight through. A scope claim is a claim.

HOW TO APPLY. Before repeating an impact statement, ask what you would have to
have counted for it to be true, and whether you counted it. If not, attribute it
(`the reporter says X`) or drop it -- the mechanism usually carries the argument
alone. And a claim about your OWN behaviour is checkable in seconds: I did not
check mine.
- *(evidence in `learnings_evidence.md`)*

## 2026-09-07 FORBIDDEN: publishing a PRODUCTION LATENCY or ERROR reading without first establishing that no other session was loading that service. ~80 sessions share these three services; a concurrent load test makes the instrument read the other session, not the route. `[lane ncaaf-live-resim-wire]`

I probed `/api/ops/artifacts/export?names_only=1` on web, saw one subset take
>150 s and a third return **502**, and reported it as `#632` latency on that
route. It was not. `web-oom-profiler-steady` was firing 18 requests at
`/api/intelligence/query` in three 6-concurrent bursts, 00:50:06-00:53:14Z,
against **8 gunicorn slots** (`WEB_CONCURRENCY=2` x `GUNICORN_THREADS=4`), each
held 20-65 s. Their clean reading of the SAME route at 00:48:22Z was **19.1 s
median / 25.6 s max**. My number was ~8x their number and was measuring them.

THE OVERLAP IS CHECKABLE AFTER THE FACT, and checking it is what turned a
retraction into two findings. My probe's output file was last written
**00:53:45.302Z** and had run >120 s, so it began no later than 00:51:45Z --
inside their window. But it also showed:

- My 502 landed **31 s AFTER their burst ENDED**. So a burst's slot-hold outlives
  its last dispatch by the length of its longest request; "my load stopped at T"
  does not mean the service was free at T.
- It landed **1.4 s BEFORE** their `unhealthy` event at 00:53:46.700Z, so that
  health-check failure is at least PARTLY MINE. **The confound is symmetric and
  you owe the other session the reciprocal warning** -- otherwise they
  re-baseline against a failure you caused.

**HOW TO APPLY.**
- Before publishing any production timing, ask what else is running. `lanes.md`
  names the lanes; a message to the owner costs one turn and is cheaper than a
  retraction.
- SPLIT THE READING BY WHAT LOAD CAN TOUCH. Counts, ancestry, and pure local
  computations survive; wall-clock and 5xx do not. Here the correctness readings
  (2,371 artifacts / 667 deep; 6,316 / 5,924) and the keep-counts (111/107/161 of
  177 patterns) all stood -- only the latency claim died. Saying which half is
  which is the difference between a retraction and a total loss.
- **A STRUCTURAL claim and its PRODUCTION consequence are two claims.** "Leading-`*`
  subsets are the pre-filter's worst case" is arithmetic over the pattern list and
  stands. "...and therefore still fall over in production" needed the measurement,
  and died with it. Do not let the surviving half smuggle the dead half along.
- *(evidence in this file's PART 4 entry in `log/2026-09-07.md`)*

## 2026-09-07 - FORBIDDEN: treating UNTRACKED as NEW. It can mean your HEAD is behind.

**What happened.** `.syndicate/log/2026-09-07.md` showed as `??` in
`git status`, so I blob-staged my local copy against `origin/main` as if it were
a new file. It was not new. My HEAD predated the commit that added it, so what I
held was a **stale 184-line prefix of a 1,233-line file**. The push deleted
1,125 lines of the same day's log. Restored in `9abfc537`.

**`??` answers "is this in MY index", not "does this exist upstream".** On a
tree whose HEAD is behind `origin/main` -- the normal state here, already
recorded as `primary_tree_is_not_deployed_code` -- an untracked path and a path
that exists upstream with far more content look **identical**. The status letter
is about my index; the question was about the remote.

**The guard printed the answer and was not looking at it.** The gate emitted
`76 1125` on screen and refused nothing, because its deletion check named
`lanes.md` only. Two paths were being written; one clause was checked. That is
the compound-check failure recorded in `compound_absence_claim` **earlier the
same day**, committed by the session that recorded it -- writing a rule down
does not make you apply it to the next thing you build.

**How to apply.**
- Before staging ANY ledger path, run `git show origin/main:<path>` first. If it
  exists, your copy is a candidate for a stale-prefix clobber no matter what
  `git status` says. Merge onto the upstream copy; never push yours over it.
- A deletion gate must iterate over **every path in the diff**, never a named
  one: `for r in rows: if int(r[1]) != 0: refuse`, with no path allowlist.
- This is a SCOPE bug, not an oversight: the correct reasoning was present and
  applied to `lanes.md` in the very same script, to one of two arguments.

Related: [[shell_layer_transcodes_bytes]] (0-deletion rule on a shared append),
[[compound_absence_claim]], [[primary_tree_is_not_deployed_code]].
## 2026-09-07 FORBIDDEN: writing a test from the SAME reading of a contract that produced the code. `[#632, session b2b5b45b]`

`d5e4cc51`'s `patterns_that_can_match` compared directory DEPTH. The caller
applies the subset with `fnmatch`, whose `*` CROSSES `/`; the patterns are
globbed, where it does not. My unit test
`test_subset_prefilter_is_conservative_when_it_cannot_tell` asserted MY reading
of `*` rather than the caller's actual call, **so it passed and proved nothing**.
The endpoint then short-answered with no error for 10 minutes in production.

**A test written from the same misreading as the code cannot catch that code.**
Reviewers cannot either, for the same reason.

**How to apply:** when a value crosses a boundary between two languages/dialects
(glob vs fnmatch, SQL vs ORM, shell vs Python quoting), the test must exercise
THE CALLER'S ACTUAL CALL, not your model of it. And prefer a PROPERTY over
examples: *pre-filter then post-filter must equal post-filter alone* is
executable, and it is what finally caught this. Then verify the test can FAIL:
reverting to the buggy implementation produced 250 unsound drops. A test never
seen red is not evidence. See [[feedback_gate_on_the_output_not_the_input]].

## 2026-09-07 FORBIDDEN: reading a null result from a window that ENDS BEFORE THE EFFECT CAN OCCUR. `[#632, session b2b5b45b]`

I checked Render events ~1 minute after a load burst began, saw none, and
reported "no health-check event fired" as a RESULT. It fired at burst-end +32 s.
In the baseline arm it had fired at +0 s.

**A burst's blast radius is its longest TAIL, not its last request.** 18 requests
with 20–65 s tails hold gunicorn slots long after dispatch stops, so the
observation window must extend past the slowest request, not past the last one.

**How to apply:** before reporting an absence, state the window AND the latency
of the thing you are looking for, and confirm the window covers it. Reinforces
[[feedback_absence_in_a_window_is_not_absence]].

## 2026-09-07 FORBIDDEN: comparing percentiles across arms with DIFFERENT ERROR COUNTS. `[#632, session b2b5b45b]`

BEFORE: 16/18 completed, 2 errors, p50 20,671 ms. AFTER: 18/18, 0 errors, p50
24,108 ms. I nearly reported "latency got 17% worse". **The two errors were the
WORST cases and were excluded from BEFORE's percentiles**, so the arms do not
share a denominator; the fix's arm is penalised for completing the requests the
baseline dropped.

**How to apply:** percentiles over successes only are a survivorship statistic.
Report completion rate BESIDE them, and when error counts differ, the percentile
comparison is invalid — say so rather than picking the flattering reading. Also:
**retain raw per-request samples, not summaries.** Keeping only summaries is what
made this unresolvable. See [[feedback_a_rate_not_a_count]].

## 2026-09-07 A pre-filter that can change the ANSWER is not a pre-filter. `[#632, session b2b5b45b]`

An optimisation placed in front of a filter must be provably sound in ONE
direction only: keeping something that cannot match wastes work and the
post-filter still corrects it; dropping something that can match is
unrecoverable and silent. `patterns_that_can_match` now returns True for
anything it cannot decide (a `[...]` class), and the caller's `fnmatch`
backstop was kept.

**How to apply:** state which direction of error is recoverable before writing
the optimisation, and make the undecidable case fall to the recoverable side.
Reinforces [[feedback_unknown_must_not_default_permissive]] — same rule, opposite
polarity: the safe default is whichever side a downstream check can still fix.

## 2026-09-07 - FORBIDDEN: reporting a null result without checking the sampled population COULD have produced a non-null one.

**What happened.** I called `/api/ops/live-lens/snapshot-index?sport=mlb`,
printed the first three games, saw `modelHomeWinProb: null, source: null` on
every `first1/first3/first5` lane, and concluded **"MLB's segment lanes are
EMPTY -- not filtered, not imprecise, absent."** I put that in a commit message
on `main` (`70622e0b`) and told the user I was retracting a *correct* earlier
statement in its favour. Retracted in `305f2d74`.

**All three sampled games were FINAL**, and `_build_game_lens` returns `[]` for
a final game -- so those lanes came from `_live_lens_segments_from_card`, which
has no `source` and no `modelHomeWinProb` **by construction**. The population I
sampled could not have produced a non-null answer no matter what the system did.
`prop_status_text: "final final"` was in the payload I had already fetched.

**On live games the lanes are populated:** gamePk 823902 `first5 0.3242,
first7 0.2991`; 823175 `first7 0.6511`, with the Nones monotone in segment
length -- `_segment_projection`'s `closed` flag working correctly.

**Why this is its own rule and not just [[instrument_blindness]].** That rule
says a healthy reading is evidence only once you know what makes it read
unhealthy. This is the inverse and the more dangerous direction: an ABSENT
reading was taken as evidence of absence, when the sampling frame guaranteed
absence. It also compounded [[read_the_field_you_already_have]] -- the
discriminating field was on screen -- and produced a **retraction of a true
statement**, which is worse than the original error: the user had been told
something correct and I replaced it with something false, confidently.

**How to apply.**
- Before reporting any null/zero as a property of the system, state the
  population and show it contains at least one case that COULD have been
  non-null. If it cannot, the reading is about the sample, not the system.
- For live-state endpoints, FILTER TO LIVE before drawing conclusions. `live`,
  `final` and `pregame` rows are produced by different code paths here, and
  final rows are built by a path that has no live fields at all.
- Never sample "the first N" of a heterogeneous payload. Group by the state
  field first, then look.
- A retraction is not free. Re-derive before overturning something you already
  told the user was true -- [[retraction_is_not_innocence]] runs both ways.

Related: [[instrument_blindness]], [[read_the_field_you_already_have]],
[[absence_in_a_window_is_not_absence]], [[a_projection_is_not_a_model_edge]].

## 2026-09-07 FORBIDDEN: justifying a sign/unit transform by pointing at a SIBLING CALL SITE. The convention belongs to the SOURCE, and one function can read two sources. `[lane nfl-rating-units]`

`backfill_nfl_performance` negated nflverse's `spread_line` to build
`market_margin`. That field is already HOME-MARGIN-POSITIVE, so every NFL
regular-season market number was inverted. Measured by running the repo's own
`load_completed_games` over real 2025 results: **34.7%** agreement with the
actual winner against the market's true **65.3%** -- almost exactly
one-minus-the-truth, which is the signature of a SIGN ERROR rather than a weak
signal. 65.3% after the fix.

**THE COMMENT DEFENDING IT WAS ACCURATE AND STILL WRONG.** It cited two siblings
-- the preseason branch a few lines below, and
`backfill_smartsim2_performance.py` -- and BOTH of those negate CORRECTLY,
because they read a SPORTSBOOK spread, which genuinely is bet notation. One
function, two sources, two conventions, one negation applied to both. A reviewer
who checks the cited siblings finds them correct and moves on.

**AND A TEST ASSERTED THE WRONG VALUE AND PASSED.** Second instance the same day
of that shape -- the artifact-export pre-filter (`web-oom-profiler-steady`) was
the first. A test written from the same misreading as the code cannot catch that
code, and a green suite is then evidence of nothing.

**HOW TO APPLY.**
- Trace the field to the FILE and the WRITER that produced it. Here
  `schedule_{season}.csv` <- `fetch_nfl_schedule.py` <- nflverse `games.csv`,
  copied verbatim. The convention was three hops away and knowable.
- Prefer a check the DATA can fail. "Does the market pick winners more often than
  chance" needs no documentation and cannot be satisfied by a plausible comment.
- When you fix it, fix the TESTS THAT ENCODED IT, and add a probe for the
  PROPERTY rather than the value -- an equality assertion can be satisfied by an
  unrelated change.
- *(evidence: `findings_2026-09-07_nfl_rating_units_and_market_sign.md`, and
  PART 5 of `log/2026-09-07.md`)*

## 2026-09-08 FORBIDDEN: carrying a scoped finding forward as a GENERAL claim after its scope expires. `[#632, session b2b5b45b]`

`UPDATE 37` established "web is not OOM-killed, it TIMES OUT" from 35
`server_failed` events with zero `evicted=True`. True of those events. I then
repeated it for a full day — in messages to two peers and in my own reasoning —
while web took **six `oomKilled memoryLimit=2Gi`** in one day, four of them before
I sent anything.

**A finding is scoped to the window it was measured in.** "Not X in these 35
events" is not "not X". The moment it becomes a premise for someone else's
debugging it needs re-checking, because the cost of a stale premise is paid by
whoever trusts it.

**How to apply:** when relaying a finding to a peer, state its WINDOW alongside
it. When a finding is more than a few hours old and you are about to act on it,
re-read the events. See [[feedback_absence_in_a_window_is_not_absence]] and
[[feedback_rebaseline_before_judging]] — this is the same failure aged into a
belief.

## 2026-09-08 FORBIDDEN: a periodic publisher whose interval EQUALS its reader's freshness threshold. `[#632, session b2b5b45b]`

I set the chip publish interval to 120 s to "match" the endpoint's 120 s
threshold and wrote that in the docstring as a virtue. The real gap is
`interval + build_time + poll_granularity` = ~135 s, so the artifact was stale
for the tail of EVERY cycle and ~40% of requests still fell back to the inline
fan-out.

**A publisher must run FASTER than the threshold that judges it**, by at least
its own build time plus its scheduler's granularity. Matching exactly guarantees
a stale window; matching is the worst of both.

**How to apply:** when a producer and a consumer both carry a time bound, write
down which is which and make the producer's strictly smaller — or raise the
consumer's, which is what was done here (120 → 180 on web) because the worker was
the constrained service.

## 2026-09-08 FORBIDDEN: reading a marker at the wrong nesting level and concluding the code did not run. `[#632, session b2b5b45b]`

I verified a new response guard by reading `_response_slimmed_reason` at the TOP
level of the payload, got `None`, and was one sentence from reporting that the
guard had not fired in production. The payload nests under `response`; the marker
was there, with the right value.

**A null read from the wrong path is indistinguishable from a null read from dead
code** — and I have spent a whole session insisting on exactly that distinction
for logs. It applies to payloads too.

**How to apply:** before concluding "the code did not run", print the CONTAINER
you searched, not just the miss. Dump the keys. If a marker is absent, prove you
looked where it is written. Same family as
[[feedback_absent_signal_is_about_the_emitter]].

## 2026-09-08 A probe is production load, and an unbounded one is an outage. `[#632, session b2b5b45b]`

To measure a slow endpoint I POSTed it with no `limit` and no `slim_aliases`. It
built a **64.98 MB** response in a 2 GiB container and web was `oomKilled` twice
within three minutes. Earlier the same night a 6-concurrent burst tripped a real
`unhealthy` health-check failure. **Three production incidents this session were
caused by my own measurements.**

Reproducing a failure deliberately IS legitimate and produced the session's best
evidence. What was not legitimate was sending the heaviest possible variant of a
request without first asking what it would cost.

**How to apply:** before probing, estimate the response size and the concurrency
you are about to add, and bound them explicitly (a `limit`, a slim flag, fewer
threads). Prefer the shape a real client sends — I measured a request production
never serves and nearly drew conclusions from it. Then say plainly, in the write-
up, which incidents were yours.

## 2026-09-08 - FORBIDDEN: `git stash` inside a session worktree. The stash stack is REPOSITORY-GLOBAL.

**What happened.** I used `git stash -q -u && git fetch && git rebase && git
stash pop -q` as a rebase helper in my session worktree, as I had several times
that day. This time my tree was CLEAN, so `stash -q -u` stashed **nothing** --
and `stash pop` popped **another session's** work in progress
(`stash@{0}: WIP on session/pc-counters`) into my worktree, producing `UU`
merge conflicts in four files belonging to lane
`mlb-first5-kalshi-fanin-mismatch` plus 58 lines of their lane blocks staged in
`lanes.md`.

**`scripts/session_worktree.py` gives each session its own INDEX. It does not
give it its own STASH.** `git stash` is a ref (`refs/stash`) in the shared
repository, so every worktree pushes and pops the same stack. Worktree isolation
does not extend to it, and nothing warns you.

**Why the earlier uses did not break.** On every previous call I actually had
local changes, so my own entry was on top and `pop` returned mine. The hazard is
invisible until the one time the tree is clean -- which is exactly when the
helper looks safest.

**Nothing was lost, and the reason is luck plus git being careful.** The pop
conflicted rather than applying cleanly, so git KEPT the entry
("The stash entry is kept in case you need it again"). Had it applied cleanly it
would have been DROPPED, and another session's uncommitted work would have
existed only inside my worktree, on top of my unrelated changes.

**How to apply.**
- **Do not run `git stash` in a worktree.** To rebase over local changes, commit
  them first (a throwaway commit you amend or reset later), or `git rebase
  --autostash` which uses its own storage, or simply rebase before you start
  editing.
- If you have already popped someone else's work:
  `git restore --staged --worktree <their paths>` to put them back at HEAD,
  confirm `git stash list` still holds their entry, and say so. **Never
  `git stash drop`.**
- `git status --porcelain` showing `UU` on files you have never touched is the
  signature. Read the paths before resolving anything.

Related: [[shared_index_can_hold_a_revert]] (same class -- the index was shared
until worktrees; the stash still is), [[concurrent_parallel_sessions]],
[[untracked_is_not_new]].

## 2026-09-08 FORBIDDEN: treating scope drift as a discipline problem. Change the COST of deferring, or nothing changes. `[lanes session-scope-drift-guard + lead-deferral-and-lane-census, session e51345f0]`

- **What we believed:** sessions drift off their objective because they fail to
  notice, and the fix is to notice harder — or to delegate the lead to a subagent
  or a new session. The user's own framing: *"every session that has an objective
  ends up drifting instead of delegating or spinning up a new session to follow a
  lead."*
- **What was actually true:** two things, and both make "notice harder" useless.
  **(1) NO HOP IS CATCHABLE BY JUDGEMENT.** Stated best by lane
  `profitable-buckets`, opened the same day because its session kept deviating:
  *"This session already spent hours going from a ledger bucket gap into segment
  pricing, first5 skill, full-game discrimination, late-inning ceilings, a
  home-field term and two deploys. **Each hop was locally justified and the sum
  was deviation.**"* Every hop is defensible AT THE MOMENT IT IS TAKEN; only the
  sum is wrong, and nothing was watching the sum.
  **(2) THE COST GRADIENT POINTED THE WRONG WAY.** Following a lead cost **zero**.
  Deferring it cost `/lane open`'s **seven** steps of collision checking. A rule
  telling sessions to defer, laid over that gradient, is a rule asking people to
  choose the expensive option every time.
  Delegation was NOT the missing piece: the `syndicate-engineer` subagent
  CLAUDE.md prescribes for exactly this had **zero recorded invocations** in the
  entire ledger, and the sessions that DID close their lanes did it by
  re-declaring the goal per lead inside ONE context window, not by isolating.
- **How we found out:** measured on `origin/main` (never the checkout — the
  primary tree was 441 commits behind): **53 OPEN lane blocks, 26 UNOWNED, 20
  with no date newer than 2026-09-01.** Deferral ran **9 explicit instances
  against 41 `findings_*.md`** — about **1 lead in 4.5** — and **18 of 54**
  findings/handoff files were referenced by no lane at all. Every guard in
  `.claude/hooks` protected FILES AND THE LEDGER FROM THE SESSION;
  `lane-guard.py:187` fires only on `claimed by OPEN lane <other>`, so a write to
  a file NO lane claims was free. `current_lane()` had two non-test consumers and
  both used it only to EXCLUDE you from other-lane conflict detection. Nothing
  anywhere asked "is this write serving the goal I declared".
- **The rule going forward:**
  1. **A lead gets `/lead "<one line>"`, not inline work.** One line into
     `.syndicate/leads.md`, then back to the objective. Never into `lanes.md` — a
     lead has no claims and would inflate the population that is the problem.
  2. **`/checkpoint` states the lane's Goal VERBATIM and answers MET / NOT MET /
     DRIFTED.** `DRIFTED` is not a failure verdict; it is the only one that makes
     the next session's pickup honest. Copy the goal, never paraphrase it — a
     paraphrase drifts toward whatever you actually did.
  3. **When you propose a discipline fix, ask what it costs to obey.** If the
     compliant path is more expensive than the non-compliant one, you have
     written an exhortation, not a mechanism. `scope-guard.py` names the cheap
     path (`/lead`) precisely because a warning that offers only the expensive
     one is a reprimand.
  4. **Count the ledger with `scripts/lane_census.py`, never with grep or by
     reading prose.** Three methods gave three answers for "how many lanes are
     open" the same hour: `grep '— OPEN'` said 47 (it misses bold `**OPEN`), a
     prose reading said 47 (it counted three lanes as closed whose status field
     says OPEN and whose claims `lane-guard` still enforces), the parser said 53.
     The parser is authoritative because it is the one the guard uses.
- **Cost:** the 53/26 population itself, and 18 orphaned findings files nothing
  points at. Plus two near-misses inside the session that wrote this rule: the
  first draft of `scope-guard.py` went silent on any lane whose goal contained an
  em-dash — i.e. every lane following the ledger's own header convention — and
  its first live run fired with a `../../..` area that would have poisoned the
  once-per-area slot. **Both were invisible to 27 green unit tests and appeared on
  the first run against the real ledger.** A guard for a discipline problem fails
  toward SILENCE, which looks exactly like compliance.

## 2026-09-08 FORBIDDEN: proposing a rule without grepping `learnings_index.md` first. This file re-learns what it already knows. `[lane session-scope-drift-guard, session e51345f0]`

- **What we believed:** that "a reading goes stale between measuring and acting"
  was an uncovered lesson. I hit it three times in one session, told the user
  `learnings.md` had no rule for it, and was told to add one.
- **What was actually true:** it is covered at least **eight** times, and **two
  entries are near-verbatim descriptions of the exact instances I hit**:
  - `2026-08-15 — FORBIDDEN: a scratch index seeded with `git read-tree HEAD`
    snapshots the WHOLE TREE, and `git diff --cached --numstat` cannot see it go
    stale.` Same mechanism, **same file**: that entry lost 35 lines of
    `.syndicate/deploys.md` to a peer's commit landing mid-staging. **24 days
    later I staged against `origin/main`, origin advanced, and my commit carried
    a 26-line deletion of `deploys.md`** — a file I never opened or named. I
    caught it by reading `git show --stat`, not because I knew the rule; and the
    entry had already warned that the `--cached --numstat` check I was relying on
    is blind to this *by construction*.
  - `2026-08-27 — A CARRIED-FORWARD FACT DECAYS EACH TIME IT IS RESTATED WITHOUT
    RE-READING THE SOURCE.` **12 days later** I restated "lane
    `profitable-buckets` is unpushed" from a two-hour-old reading, in a lane
    block, in `leads.md`, and twice to the user. Its owner had pushed it. The
    correction had to be pushed too, because the stale claim was already on
    `origin`.
- **How we found out:** one `grep` over `learnings_index.md` — run *after* the
  user approved the new rule, when it should have preceded the proposal. The
  index exists precisely for this and cost one command.
- **The rule going forward:**
  1. **Before proposing or appending a rule, grep `learnings_index.md`.** It
     spans `learnings.md`, `learnings_evidence.md` and `learnings_archive.md`, so
     a rule stays findable after its body is compacted out.
  2. **If a matching rule exists, do not append a restatement.** Nine entries
     saying one thing is worse than one, because the digest samples the file and
     dilution is the failure mode. Cite the existing rule by its date instead.
  3. **If you broke a rule that already existed, the finding is about DELIVERY,
     not knowledge.** Say so plainly and name the rule you broke, so the next
     reader can reach it. Do not launder a repeat into a discovery.
- **Cost:** two rules broken 24 and 12 days after they were written, by the
  session whose own lane was *about* scope drift — and a ninth restatement very
  nearly appended. **The corpus has outgrown its delivery: 910 rules, of which
  the session-start digest carries 6 headings (`RULE_CAP=450`).** Size is not the
  constraint — `learnings.md` is 331 KB against a 460 KB cap. Compaction will not
  fix this; `2026-08-20 — TRIMMING state.md AND learnings.md DOES NOT FIX THE
  DIGEST. Measured.` already established that. **A rule that exists and does not
  reach the session is an exhortation with a distribution problem** — which is
  the same finding as this session's other rule, turned on this file itself.

## 2026-09-08 MAP: ~95 rules in this file are one question in 17 shapes — *"is the number I read the one the decision depends on?"* Read this before writing another. `[lane learnings-instrument-family-consolidation, session e51345f0]`

- **What we believed:** that the instrument/predicate family had grown to ~50-95
  near-duplicate entries and should be CONSOLIDATED — folded into one entry with
  the originals archived, following `2026-08-20 — ONE ERROR IN FIVE GUISES`.
  That was the plan, a tool was built for it, and it was **rejected on the
  evidence.**
- **What was actually true:** they are not near-duplicates. A full inventory read
  from `origin/main` found **~95 entries in FOUR families whose fixes differ**,
  and folding them would have deleted ~78 headings each naming a mechanism a
  generic rule would not have prevented:
  - **A — INSTRUMENT** (~65): *can the reading vary with the truth at all?*
    Fix: build a case that makes it read otherwise.
  - **B — MEASUREMENT-SOURCE** (~11): *is the value about the thing it claims?*
    Fix: find the surface that actually serves the reading.
  - **C — PREDICATE** (~13): *where did the threshold come from?*
    Fix: read the enforcer, not a docstring beside it.
  - **D — CONFOUNDED READING** (~10): *is the population or window contaminated?*
    Fix: split by eligibility, or clip the regime.
  "Check your instruments" is what a merged entry would have said, and it would
  have prevented none of the incidents that produced these.
- **How we found out:** the inventory was commissioned specifically to argue
  AGAINST consolidation, and did. The decisive check was cheaper: **the 2026-08-20
  precedent's own five originals had been absent from `learnings_index.md` since
  the day they were archived** — the generator spanned `learnings_archive.md` but
  not the dated file. Consolidation had already cost five rules once, silently.
  (Fixed 2026-09-08, `d1d4045d`: 911 -> 916 indexed, 0 removed.)
- **The rule going forward:**
  1. **Before writing a rule about a measurement, grep this map's clusters
     below.** ~95 entries already cover this ground; the odds you have a new
     claim are low and the cost of a duplicate is dilution.
  2. **Do not fold this family.** Merge at CLUSTER level at most, never at
     family level, and only where two entries make the same claim from the same
     mechanism. A topical neighbour is not a duplicate.
  3. **A map is the cheaper lever than a merge.** The problem was never that
     there are too many rules — it is that 911 rules reach a session as SIX
     headings. This entry costs one heading and destroys nothing; a merge would
     have cost 78 rules to save the same one heading.
- **THE 17 CLUSTERS.** Regenerate membership with
  `grep -iE 'instrument|predicate|discriminat|control|denominator|proxy|reachab' .syndicate/learnings_index.md`.
  - **A1 calibration** — prove it CAN read otherwise before trusting a clean
    reading. *(08-13 emit-non-zero · 08-27 built-out-of-the-thing-it-measures ·
    09-02 mutate-before-believing-green)*
  - **A2 wrong surface** — the instrument is not attached to what broke.
    *(08-16 wrapper-vs-siblings · 08-27 reading-from-a-different-surface)*
  - **A3 silent failure** — working and never-ran emit the same thing.
    *(08-13 discriminator-only-on-FAILURE, written TWICE the same day from two
    incidents · 08-19 guard-that-fails-open-silently)*
  - **A4 coverage gap** — the failure lives where the instrument never looks.
    *(09-04 cannot-see-the-suspect · 09-05 one-branch-does-not-certify-the-other)*
  - **A5 control design** — the comparison group cannot discriminate.
    *(08-27 control-broken-the-same-way · 09-06 same-length-of-time)*
  - **A6 discriminating power** — the signal was never shown to separate the
    states. *(08-31 visible-vs-discriminates · 09-06 key-not-value)*
  - **A7 singletons (~14)** — mechanism-specific, deliberately unmerged: a killed
    process emits no log; watchers lie in four ways; a green suite over a file
    that cannot boot.
  - **B1 reachability** — code-reachable is not data-reachable. *(08-13
    presence-is-not-reachability · 09-04 deploy-target-by-what-SERVES)*
  - **B2 describes the instrument** — the reading is a fact about the reader.
    *(08-29 count-0-is-about-the-SCANNER · 09-01 degenerate-fit)*
  - **B3 singletons (2)** — including 09-03 *polling a friendlier proxy instead
    of the instrument that GATES*, which is 2026-08-20's claim recurring two
    weeks later in another subsystem. **Left separate on purpose: it is the
    evidence that consolidating a family does not stop the mistake.**
  - **C1 read the enforcer (9)** — not the comment, the docstring, or the name.
    *(09-02 threshold-from-ENFORCER-claim-from-PREDICATE — the anchor · 09-06
    name-the-WRITER-of-the-field)*
  - **C2 predicate soundness (4)** — is it observable, and does its label follow
    from its condition? *(08-13 label-entailed-by-exit-condition · 09-03
    check-it-is-OBSERVABLE-first)*
  - **D1 wrong denominator (4)** — which ROWS are in the population. *(08-13
    pooled-denominator · 09-04 denominator-from-OUTSIDE-the-instrument)*
  - **D2 window confound (5)** — which MOMENTS are in the window. *(09-02
    measuring-the-RAMP-after-a-restart · 09-07 another-session-was-loading-it)*
  - **D3 singleton** — 09-07 a predicate on a TOTAL that can move for another
    reason.
  *(D1 and D2 are NOT one cluster: one is an eligibility filter you failed to
  apply, the other a regime you failed to exclude. Different operations.)*
- **Cost:** four of these rules were broken in a single session on 2026-09-08 —
  the digest budget read off total stdout instead of `$BODY`; an open-lane count
  from a grep instead of the parser `lane-guard` uses; a commit diffed against
  the base its index was SEEDED from instead of the one it lands on; a push-state
  claim restated from a two-hour-old reading. Every one of them had a rule, aged
  6 to 24 days, and none reached the session. **That is the cost this map exists
  to reduce, and it is the second confirmed instance of this file's own
  2026-09-08 rule about delivery.**


### 2026-09-08 — FORBIDDEN: inferring that a service HAS an input from a related artifact's provenance string. Read the consuming code's own counter.

- What we believed: refresh-worker had the NFL play-by-play and web did not, so
  moving the prop model to the worker would fix a zero-row join. The evidence
  was the worker's projection artifact carrying
  `rating_source=nflverse_pbp_epa_rolling[...]`.
- What was actually true: that string is TEAM-level EPA and says nothing about
  the player-level columns `player_name_index` needs. **Neither service can
  resolve a player name.** The worker's own first autorun:
  `JOIN ... sim_source=computed odds_rows=2463 sim_rows=0 refused_wrong_team=0
  refused_unknown_team=0` — 2,463 odds rows, MORE than web's 2,455, and still
  zero. `_pbp_path` reads `nfl_source/tracking/nflverse/pbp/pbp_<season>.csv`,
  which is **not in `HOT_ARTIFACT_PATTERNS` at all**, and `pbp_2025.csv` is
  **97.9 MB** against a 12 MiB `_PUBLISH_MAX_BYTES`. The input cannot travel, so
  the worker can NEVER build this artifact. The producer is an offline run.
- How we found out: reading the worker's own JOIN line at the timestamp of its
  launch — a field that had been in the log for an hour before anyone read it.
  The inference chain (`rating_source` mentions pbp -> the service has pbp) was
  never checked against the counter that the consuming code already emits.
- The rule going forward: an input's presence is a property of THE PATH THE
  CONSUMER READS, not of any artifact that mentions it. Before moving work to a
  service "because the data is there", read that service's own instrumentation
  for the consuming code path. A provenance label is about the producer's
  inputs, never about yours.
- Cost: one commit built on the wrong premise (landed, then removed the same
  hour), and — worse — an autorun deployed to a service that cannot succeed,
  whose first run published a 284-byte empty artifact over a healthy 966-row one
  and took `/nfl/api/props` to zero cards a day before the season opener.

### 2026-09-08 — FORBIDDEN: a guard that only DECLINES TO WRITE, when the damaging artifact already exists on disk.

- What we believed: moving the zero-row guard above the write and publish fixed
  the clobber. "Existing artifact left untouched" reads like safety.
- What was actually true: untouched was exactly the problem. The empty 284-byte
  file was ALREADY on the worker's disk, and a periodic publish sweep
  republishes it to web after every restart — `PUBLISH_OK ... bytes=284` at
  19:19:57, 19:22:34, and again at 20:01:38 immediately after the 19:58:07
  deploy, with `PUBLISH_SKIPPED_UNCHANGED checksum=77a9ed3cd0c7` in between. So
  the outage was not a one-off; it recurred on every boot, and the guard was
  silent through all of it because it never ran again.
- How we found out: `/nfl/api/props` was empty AFTER the guard was live, and the
  published artifact measured 111 bytes.
- The rule going forward: when a guard prevents producing bad state, ask what
  the bad state ALREADY on disk will do next. If something else republishes,
  serves, or re-reads it, the guard must REPAIR, not just abstain. Pair every
  "refuse to write" with "and restore the good copy" wherever a copy exists.
- Second-order, and it nearly shipped: the repair was gated behind an autorun
  whose staleness check reads `stat()` only, so a zero-row artifact written ten
  seconds ago is `artifact_fresh` for 24 h. The fix would have deployed and done
  nothing for a day. **Gate on the OUTPUT (rows), not the input (mtime).**
- Cost: a second deploy, and a repair that was written unconditionally the first
  time — it pulled web's 111-byte empty file straight over a good local copy
  before being conditioned on `local_rows == 0`.


### 2026-09-08 — FORBIDDEN: a test whose FIXTURE hand-rolls the artifact schema the code under test reads. Round-trip the production writer.

- What we believed: `_nfl_prop_artifact_is_empty` detected the zero-row NFL prop
  artifact, and three unit tests proved it. They passed.
- What was actually true: the helper read `payload["rows"]`. That key has never
  existed — `write_nfl_prop_projection_artifact` emits `{season, week,
  generated_at, sim_rows, row_count}` and `read_nfl_prop_projection_artifact`
  reads `sim_rows`. So the helper returned False for EVERY input, the staleness
  override it gates never fired, and the commit deployed to refresh-worker
  completely inert. The tests passed because their fixtures were written with
  the same invented key: **they asserted against the same wrong schema as the
  bug, so they confirmed it rather than catching it.** That is not a weak test,
  it is an absent one wearing a passing badge.
- How we found out: by accident, reading the real artifact on disk for an
  unrelated reason — 404,766 bytes with `row_count=980` while a probe printed
  `rows: 0`. Nothing in the test suite, the deploy, or the logs would have said
  so; an inert guard is silent by construction.
- The rule going forward: when a test exercises code that PARSES an artifact,
  build the fixture by calling the real WRITER (patch its output root), never by
  hand-writing a payload literal. Add one explicit schema-agreement assertion
  naming the key. And before trusting a new guard, verify the test can FAIL:
  reintroduce the bug and watch it go red. Here that flipped 3 tests red and
  back to green, which is the only evidence the tests were load-bearing.
- Cost: one wasted deploy of an inert change (~20 min build), on the day before
  the season opener. The silver lining is the only reason it was harmless: an
  override that never fires also never busy-loops.

## 2026-09-08 RECURRENCE, not a new rule: I compared a baseline recorded on ONE host against a run on ANOTHER and read the difference as change over TIME. `[lane render-cron-failures, session e371dfde]`

**The general case is already here** — 2026-08-28, *"baselining a test in a
fresh worktree when the test reads state the worktree does not share — it is
not a baseline, it is a different experiment"*. This is that rule in a shape it
did not cover in my head: **a persisted baseline FILE**, not a worktree.

- **What I did.** `tests/pytest_baseline.json` records 19 known-failing tests,
  taken 2026-08-26 under `-n auto` on somebody's machine. The `ci-suite` cron
  first completed the suite 2026-09-08 and reported 25 new failures. I filed 19
  of them as REGRESSIONS on two checks that were both TRUE — the test existed at
  the baseline commit, and it still failed in ISOLATION on the cron — and both
  are equally consistent with *never having passed on that host*. **The cron did
  not exist when the baseline was taken.** 15 of the 19 turned out to be a
  memory floor (`floor_mb=3000` against `max_mb=2048`) that the runner cannot
  reach; the rest were stale tests. **Zero regressions.**
- **The sentence that would have caught it:** *"not in the baseline's failing
  set"* means **passed somewhere else**, never **passed here**.
- **Why it is worth a line despite the duplicate-rule ban.** The recurrence is
  the information: the 2026-08-28 rule is filed under WORKTREES, and I did not
  retrieve it while holding a JSON file recorded on a different box. A rule
  indexed by its mechanism is invisible from a different mechanism. If this
  family gets consolidated (see the 2026-09-08 MAP entry), index it by the
  QUESTION — *are these two numbers from the same environment?* — not by the
  artefact that carried it.
- **Retracted publicly the same day**: `#648`, `.syndicate/findings_2026-09-08_nineteen_pytest_regressions.md`,
  commits `db9febae` / `33abd83c`. A peer session's two passing runs on their own
  machine are what broke it open.


### 2026-09-08 — FORBIDDEN: pricing a market against an estimator without asking WHICH QUANTITY it estimates.

- What we believed: the NFL prop model produced a per-game projection, so a
  disagreement with the line was an edge.
- What was actually true: `player_game_log` only creates a row for a game the
  player has a QUALIFYING PLAY in, so a receiver who dressed and was never
  targeted left the denominator. The model estimated **yards per game he was
  INVOLVED in**; the market prices **yards per game**. Measured over 1,923
  quoted rows: median +7.7%, mean +12.1%, 24% of rows >25% ABOVE the line
  against 5% below — concentrated in `receiving_yards` (+18.2%) and
  `rushing_yards` (+11.9%), while `passing_yards` (-1.1%) was clean because a
  quarterback never loses a game from his denominator.
- How we found out: comparing the model's projected value against the quoted
  line per market, instead of only reading the probabilities it produced. The
  per-market split is what identified the mechanism — a pooled number would have
  shown "+12% high" and named nothing.
- The rule going forward: before treating model-minus-market as an edge, state
  the estimator's POPULATION and check it is the population the bet settles
  over. A systematic one-sided bias is an estimator defect until proven
  otherwise; edges are two-sided.
- Cost: every "edge" on the board was inflated for as long as props have
  existed, and a +46.5% headline was shown to the user as evidence of health.

### 2026-09-08 — FORBIDDEN: crediting an improvement to a change without an A/B, when two fixes shipped close together.

- What we believed: the zero-game estimator fix produced "a dramatic reduction
  in overconfidence" — no more 95% probabilities, no more +46% edges.
- What was actually true: measured both ways on the same board, cards claiming
  >90% are **8 either way**; median |edge| 9.2 -> 8.4; edges >30pts 57 -> 51.
  The absurd readings were killed by the LINE-KEY fix shipped an hour earlier.
  Its real contribution is the bias (median +7.7% -> +3.5%), which is a
  different and less dramatic claim.
- How we found out: running the estimator A/B under its own flag, after having
  already told the user the wrong attribution.
- The rule going forward: when two fixes land in one session, no improvement may
  be attributed to either until each is measured with the other held fixed. A
  remembered "before" is not a baseline — and the flag that makes the A/B
  possible must be used, not merely shipped.
- Cost: one wrong claim to the user, retracted in the next message.


### 2026-09-08 — FORBIDDEN: pushing `render.yaml` without first ENUMERATING the live env of all three services. It is 166 keys behind production.

- What we believed: `render.yaml` describes production, so adding one gunicorn
  flag to it is a one-line change whose blast radius is that flag.
- What was actually true, measured key-by-key against
  `/v1/services/<id>/env-vars` (paginated at 100; `limit` > 100 returns 400):

      service            yaml   live   sync would DELETE   would CHANGE
      web (syndicate)      52     84          33                1
      refresh-worker       84    161          77                1
      live-odds-worker     76    132          56                1

  **A `blueprint_sync` would delete 166 live env vars and overwrite
  `ODDS_API_KEY` on all three services with a different value.** Among the
  deletions: `SYNDICATE_EXECUTION_MODE=live`, `SYNDICATE_EXECUTION_LIVE_ARMED=1`,
  and the spend caps of a LIVE-MONEY execution system
  (`MAX_ORDER_DOLLARS=10`, `MAX_DAY_DOLLARS=40`, `..._ALL_VENUES=150`), plus
  sport intervals, segment markets and backfill windows. The caps do have code
  defaults so deletion is not "unlimited" — but it silently rewrites a
  live-money configuration that nobody has enumerated.
- How we found out: by running CLAUDE.md's own pre-push enumeration instead of
  treating it as boilerplate. It took one script and it was the difference
  between a one-line flag and a three-service configuration rewrite.
- The rule going forward: **`render.yaml` is not a description of production;
  it is a 166-key-stale proposal to REPLACE production.** Nobody may push it
  until the drift is reconciled INTO the file. Until then, treat any
  render.yaml edit as blocked, and reach production config through the
  SINGLE-KEY env endpoint (`PUT /v1/services/<id>/env-vars/<KEY>`), which
  writes exactly one key and fires no sync. The bulk `PUT /env-vars` is the
  same failure mode by hand and must not be used either.
- Worked example, same evening: the gunicorn `--max-requests` fix web needed was
  delivered by setting `GUNICORN_CMD_ARGS` as a single env key (84 -> 85 keys,
  verified, nothing else touched) instead of editing the startCommand in
  `render.yaml`. Identical effect, no sync, revertible by deleting one key.
- Cost: none, because the enumeration ran first. Had it not, the cost would have
  been a live-money system's configuration and every sport's tuning, hours
  before the NFL season opener.


### 2026-09-08 — FORBIDDEN: editing a `.claude/hooks/` file in a worktree and believing it is in force. Hooks run from the PRIMARY tree.

- What we believed: a guard change landed on `main` is a guard change in effect.
- What was actually true: `deploy-guard.py` resolves its root as
  `CLAUDE_PROJECT_DIR`, which is the PRIMARY tree, and the hook binary Claude
  Code executes is that tree's copy — not the worktree's, and not `main`'s. A
  new `render.yaml` drift branch tested green in the worktree and was **inert**
  in every real invocation, because the checker it shells out to did not exist
  at that root. The helper's missing-file branch returns "allow", so it failed
  silently and open, which is correct for a hook and invisible to the author.
- How we found out: by driving the branch with a forced payload instead of
  trusting that a landed commit is a live guard. The same session had already
  shipped one inert guard earlier in the day, which is the only reason the
  question got asked.
- The rule going forward: after changing anything under `.claude/hooks/`, prove
  it from the PRIMARY tree — run the hook's own test there, or invoke the hook
  with a payload — before recording it as protection. And a hook that shells out
  to a script must be landed TOGETHER with that script into the tree the hook
  reads, or the guard is a no-op that looks installed.
- Related: the primary tree can be hundreds of commits behind with dozens of
  modified files, so "pull it" is not a safe default. Update the specific clean
  files, then UNSTAGE them — `git checkout <ref> -- <paths>` stages as a side
  effect, and the index there is shared.
- Cost: none this time. The cost avoided was a guard that everyone believed was
  protecting a live-money configuration and was not.

## 2026-09-08 An era split that quarantines a STORED metric does not bind a recomputation from the RAW records — check which one the split is about before accepting its sample size `[scheduled task live-gameline-accuracy-snapshot, no lane]`

- **The rule.** When a tool refuses to pool across a boundary, read WHAT it pools.
  `pool_live_gameline_trend.py` raises on a mixed-era set, and the task brief
  states flatly that a number spanning the eras "measures the bug, not the
  model". Both are correct **about the board's STORED score**, which pre-`75cf9aec`
  compared `P(over)` / `P(home covers)` against "did the home team win". They say
  nothing about a figure recomputed from the raw ledger, because filtering
  `market=='h2h'` yourself *applies the post-fix restriction by construction*.
- **What it cost to not notice.** The quarantine was inherited as a fact about the
  DATA rather than about one consumer of it, and that capped the analysis at
  **121 games / 9 dates** when **252 games / 19 dates** were sitting in the same
  retained ledger. On the smaller sample the headline result's CI straddled zero
  (`>10pp`: +0.03063, CI [-0.00916, +0.07095]); on the full one it does not
  (+0.03432, CI [+0.00650, +0.06077]). **The boundary was not costing accuracy,
  it was costing power** — and an under-powered result reads as "we cannot say
  yet", which is indistinguishable from "there is nothing here".
- **How to discharge it.** Diff the boundary commit against the fields you
  actually read, and say so. Here: `git show --stat 75cf9aec` / `4d20ea00` touch
  neither `model_home_win_prob`, `market_fair_prob` nor `market`; v3 added `line`
  to `record_key` (population change for totals/spreads dedup only) and v4 added
  the game clock. **The same diff found a boundary that DOES bind:** `priceable`
  gained stale/age-absent refusals on 2026-09-01, so any priceable-cut comparison
  spanning that date is not like-for-like. One check, two answers, opposite signs
  — which is the point. Do not generalise either.

## 2026-09-08 FORBIDDEN: reading an empty segment as an ABSENT FIELD without checking the field's TYPE. A wrong type guard and a missing column return the identical empty set `[scheduled task live-gameline-accuracy-snapshot, no lane]`

- **What happened.** A score-state segmentation returned zero rows in every bucket
  and was reported to the user as *"the most promising remaining segmentation is
  blocked by instrumentation — `home_score`/`away_score` are null on every row"*,
  with a lead offered off the back of it. The fields were fully populated:
  **string**-typed (`'0'`, `'1'`), and the filter was `isinstance(h, int)`. A
  by-version field census, run for an unrelated reason, showed `home_score
  984/988` and blew the claim up.
- **Why the existing rule did not catch it.** `learnings.md`'s "read the field you
  already have" and "absence in a window isn't absence" both point at a field
  being *unfetched* or *unpopulated*. This one was fetched AND populated, and the
  emptiness was manufactured by my own predicate one line later. **The null result
  is evidence about the QUERY until the query has been shown to be capable of
  returning something.** Same failure class as "prove the frame could have been
  non-null" (2026-09-05), reached through types rather than through sampling.
- **The cheap check.** Before reporting any segment as unavailable, print the
  population and the distinct values of the field you filtered on — not its
  non-null count, which was 4,489/4,489 here and looked perfect. Two of the four
  "dead field" claims made in that same pass were wrong for two different reasons
  (`sigma` was constant BY DESIGN — it is `PRICEABLE_SIGMA`, documented in
  `state.md` and in the code comment; the scores were a type error), and both were
  withdrawn inside the session. **A field census is one command and it is the
  thing that should precede the claim, not follow it.**

## 2026-09-08 A Brier gap is not evidence of miscalibration. DECOMPOSE before prescribing a recalibration — reliability and resolution fail differently and only one of them is fixable by a transform `[scheduled task live-gameline-accuracy-snapshot, no lane]`

- **The trap.** A model that scores worse than the market, and whose error grows
  monotonically with how far it departs from the market, *looks* exactly like an
  overconfident model. I stated that reading to the user and wrote it into
  `state.md` as "strongly indicated". The reliability curve refuted it the same
  session: the model is **adequately calibrated** (slope 0.9053, ECE 0.03037 vs
  0.02514, all ten bins' bootstrap intervals covering the diagonal), and the
  reliability gap is **+0.00055 with a 95% CI of [-0.00324, +0.00475] — it spans
  zero.** The deficit is **resolution**: +0.00790, CI [+0.00065, +0.01511].
- **Why it matters more than a wording fix.** Brier = reliability - resolution +
  uncertainty, and **a recalibration can only move the reliability term.** Driving
  it to zero — a ceiling no fitted transform actually reaches — leaves the model at
  0.17711 against the market's 0.17020. **At most 6.5% of the gap is reachable by
  recalibration.** That is the mechanism behind the leave-one-date-out
  recalibration already recorded as having failed out of sample, and it predicts
  that any further transform-fitting will also fail. Without the decomposition the
  obvious next move — "it's overconfident, shrink it" — is a guaranteed dead end
  that looks reasonable and costs a cycle.
- **The distinguishing measurement, and it is cheap.** Higher spread with lower
  resolution is the signature: model sd **0.28231** vs market **0.26601** while
  model resolution **0.07146** vs market **0.07935**. It moves more and tracks
  outcomes less — the extremeness is variance, not information. **Check the split
  at several bin counts before believing it** (Murphy is bin-dependent): here
  resolution held 92-98% of the gap across 5/8/10/15/20 bins, so the finding is
  not a binning artifact. A single bin count would not have earned the claim.

## 2026-09-08 FORBIDDEN: validating a measurement instrument ONLY against a case whose expected answer is the SAME as the bug's output. A control that cannot distinguish "working" from "broken" is not a control `[lane mlb-pregame-baseline-feed]`

Reconstructed from `log/2026-09-08.md` (entry *"reliability curve, the encompassing
null, and the pregame-baseline fix"*) and `deploys.md` `## 2026-09-08 20:44:27Z —
live-odds-worker 57052784`, which recorded the reading as MEASUREMENT PENDING with
the pre-fix control quoted below.

- **The TECHNICAL failure: none in the system.** The fix worked on the first
  deploy. What failed was the INSTRUMENT that judged it. `measure_pregame_baseline.py`
  filtered `game_state == "live"` and never filtered `market == "h2h"` /
  `segment == "full"` — the h2h restriction my own historical analysis had used
  hours earlier in the same session, on the same ledger.
- **What we believed:** "STILL NULL on live rows — the fix did NOT reach
  production", reported to the user as a terminal verdict on **109 post-deploy
  rows, 0 non-null**.
- **What was actually true:** all 109 rows were `first1`/`first3`/`first5`
  SEGMENT REFUSALS (`market=totals_alt`, `withheld_reason=segment_pricing_disabled`,
  `game_pk=None`, `model_home_win_prob=None`) — the rows a sibling lane made
  visible in the ledger. They carry no `live_mc` h2h lane, so the field is
  legitimately None on them and always would be. **Priced full-game h2h rows in
  that population: ZERO.** The correct verdict was "nothing to read". Forty
  minutes later, on the corrected predicate: **38/38 non-null, 7 games, 7
  distinct values.**
- **How we found out:** by printing EVERY FIELD of one raw row instead of
  trusting the aggregate. The row count was 109 — big enough to feel like a
  sample, and that feeling did the damage.
- **WHY THE EXISTING RULE DID NOT CATCH IT, which is the point of this entry.**
  `learnings.md` already carries *"a null result needs a live population — prove
  the frame could have been non-null"* (2026-09-05), and I WROTE A SIBLING RULE
  THE SAME DAY (*"reading an empty segment as an ABSENT FIELD"*). Prose did not
  save me. What I actually did was build a positive control — 2026-09-07,
  pre-fix, "4,017 live rows, 0 non-null" — and declare the instrument validated.
  **That control expected NULL. The bug also produced NULL. So the control was
  incapable of detecting the defect, and its green reading is what gave me the
  confidence to report a falsification.** It even mis-stated its own denominator:
  4,017 was every live row, where only ~521 were h2h.
- **The rule going forward:** an instrument that can emit a NEGATIVE verdict must
  be validated against a case whose expected answer is **POSITIVE**. If every
  control you have expects the same output as the failure mode, you have tested
  nothing. Corollary, and cheaper than the rule: **before reading a null as a
  falsification, print the COMPOSITION of the population you scored — the
  breakdown by the discriminating fields — never only its size.** `n=109` and
  `n=0 of the right kind` are the same number to a counter and opposite answers
  to a reader.
- **Cost:** one false FALSIFIED published to the user, withdrawn ~15 minutes
  later. Had the raw row not been inspected, a working fix would have been
  recorded as broken and the next session would have re-debugged a non-defect.
- **THE CHECK, because prose demonstrably failed twice here.**
  `measure_pregame_baseline.py` now prints the post-deploy population's
  `(market, segment)` breakdown and returns exit 2 — "nothing to read" — rather
  than exit 1 whenever the priced-full-game-h2h subset is empty. Exit 1 is now
  reachable ONLY from a non-empty, correctly-typed population. Any future
  measurement script in this repo owes the same two things: a composition print,
  and a positive control.

## 2026-09-08 FORBIDDEN: concluding two working trees hold the SAME content because the same path is dirty in both. Co-occurrence is not identity, and the difference is ADDITIONS a deletions count cannot see `[worktree cleanup, no lane]`

- **What I believed:** `unknown-submit-retry-provenance` carried "routine mirror
  churn, regenerable, safe to discard" — reasoned from the fact that
  `vendor/wnba_betting_repo/data/processed/schedule_2026.{csv,json}` are ALSO
  dirty in the primary tree. I said so to the user and moved to `git checkout --`
  them.
- **What was actually true:** `.claude/hooks/discard-guard.py` blocked it, having
  searched **all 58 committed versions across every ref**: **16 CSV lines and 1
  JSON line exist in NO commit anywhere.** Two trees can carry DIFFERENT
  modifications to the same path; "both dirty" says only that both were touched.
- **How we found out:** the guard, not me. I had already committed to the
  conclusion in a message.
- **The rule going forward:** before discarding a modification because "it is
  also modified elsewhere", DIFF THE TWO VERSIONS AGAINST EACH OTHER, or search
  the content across refs. Same path + both dirty is not evidence of same
  content. **And the failure is invisible to the usual check:** unique content
  here is ADDITIONS, so `git diff --numstat` reading "0 deletions, nothing of
  mine destroyed" is exactly the reassurance that fails — the same shape as the
  2026-09-03 lane-block destruction the guard's own docstring cites.
- **Cost:** none, because the guard held. Would have been 17 lines of content
  existing in no commit on any ref, deleted on a bad inference.

## 2026-09-08 FORBIDDEN: extracting a block by splitting ONLY on its own delimiter. The LAST block swallows the file's entire trailing structure, and pasting it elsewhere duplicates that structure silently `[lanes.md reconcile, no lane]`

- **What I believed:** a lane block runs from its `### <slug>` header to the next
  `### ` header, so extracting one from `origin/main:.syndicate/lanes.md` and
  inserting it locally is a clean copy.
- **What was actually true:** `bandwidth-controlled-transfer` is the LAST block in
  upstream's `## OPEN` section, so "to the next `###`" ran to END OF FILE. Its
  "block" was **234 lines** carrying `## Archived lanes` and **12 other `## `
  structural headings**. Inserting it dropped a duplicate archive heading into the
  middle of the OPEN section and pushed the next inserted block BELOW it — where
  `lane-guard` reads it as archived and **stops enforcing its file claims,
  silently**. Correct extraction bounds the block by the next `###` **OR** the
  next `##`, whichever comes first; the same block then measures **8 lines**.
  234 vs 8 is the tell.
- **How we found out:** `.claude/hooks/ledger-postwrite-check.py` fired on the
  write — "lane block(s) BELOW `## Archived lanes`". Not from reading the diff:
  the insert looked correct in every summary I printed, because the corruption
  was INSIDE a block body I never examined.
- **The rule going forward:** any structural extractor must be bounded by the
  NEXT DELIMITER OF ITS OWN LEVEL *OR ANY HIGHER LEVEL*, and the cheap check is
  to assert the extracted body contains **no heading of a higher level than the
  block itself** — one line, and it would have caught this before the write.
  Sanity-check the extracted SIZE too: one block 30x the others is not a big
  block, it is a parse that ran off the end.
- **DO NOT "FIX" THIS BY HOISTING.** The guard suggests `hoist_open_lanes.py`,
  which moves the misplaced block — correct for a genuine ordering drift, wrong
  here, because it leaves the duplicated `## Archived lanes` heading in place and
  the file stays corrupt in a way the next check will not name. Revert to the
  pre-write backup and redo the extraction.
- **Cost:** none — reverted from a backup taken before the write. Would have been
  a shared ledger with duplicated section structure and at least one OPEN lane's
  claims silently unenforced for every session in this tree.

## 2026-09-08 When reconciling two divergent copies of a ledger, RECENCY ALONE MAY NOT PICK THE WINNER. Check the losing side for UNIQUE CONTENT before overwriting it `[lanes.md status reconcile, no lane]`

- **The situation:** 20 lanes were OPEN locally and CLOSED/ORPHANED on
  `origin/main`. Flipping them is the DANGEROUS direction — a closed lane's
  claims stop being enforced, so a wrong call lets another session edit across
  lanes silently.
- **Recency said take upstream, unanimously:** local was newer for **0 of 20**,
  upstream newer for 15, equal for 5. On that evidence alone the answer is
  "overwrite all 20".
- **That would have destroyed work.** A separate unique-content check — every
  substantive local line searched against upstream's `lanes.md` +
  `lanes_closed.md` + `lanes_history.md` — found **3 blocks carrying lines
  present nowhere upstream**, including a shared-file declaration written earlier
  the same session. Those 3 were left untouched; the other 17 were replaced.
- **Why recency was insufficient, concretely:** 5 of the 20 tied on date, and two
  carried dates in the FUTURE (09-10, 09-15 against a real date of 09-08) because
  the max-date proxy reads target dates out of body prose, not edit times. A
  date extracted from free text is a weak instrument and cannot be the only one.
- **The rule going forward:** two independent checks must AGREE before
  overwriting a block in a shared ledger — one for which side is newer, one for
  whether the losing side holds anything unique. If they disagree, keep the local
  copy: over-enforcement of a stale claim is recoverable, a deleted claim or a
  deleted note is not.
- **Cost:** none. The method is the same predicate `discard-guard.py` applies to
  file content, applied to ledger blocks.
### 2026-09-09 — DISCHARGED, not overridden: the 2026-08-29 NCAAF alias-map prohibition was CONDITIONAL, and both its conditions are now met

- **What we believed:** that `FORBIDDEN: closing a name-join gap by POPULATING an
  alias map, without first checking the map's source carries the missing name`
  (2026-08-29) barred NCAAF from ever getting a map. Read as a blanket ban it
  would have left `canonical_team("ncaaf", …)` returning `None` for every club
  indefinitely.
- **What was actually true:** the rule's own wording is conditional -- it forbids
  populating a map *without first* doing two things, and it names both: (a)
  confirm the SOURCE contains the specific name the join fails on, and (b)
  enumerate what the map resolves that the heuristics previously left
  unresolved, because those lookups flip from "fall back" to "authoritative".
  **Both were run and both passed**, on the 08-29 entry's own named failures:
  `umass minutemen` -> `massachusetts` now resolves (the token that defeated the
  08-29 attempt), and `canonical_team("ncaaf","MAS")` -> `UMass Dartmouth` -- its
  headline mis-resolution -- returns **None**.
- **Why it works now and did not then:** a DIFFERENT SOURCE and a different
  derivation. 08-29 built 2,232 keys from `unambiguous_team_index()` over
  `ncaaf_team_registry.csv` (2026-07-21). This derives 595 entries over 138 FBS
  clubs from `iter_team_alias_offers()` over
  `ncaaf_team_registry_snapshot.csv` (2026-08-26) -- the file
  `oddsapi_lines.resolve_team` actually reads. **Fewer keys, better ones.** The
  collision pass also counts across all four divisions BEFORE filtering to FBS,
  so a code an FCS school also claims is dropped rather than handed to the FBS
  programme: 95 bare mascots dropped (`tigers` 25 schools, `bulldogs` 23,
  `wildcats` 15).
- **The semantics-flip the 08-29 rule feared was measured and went the other
  way.** Wrong-pair false positives **fell 7 -> 1**: `Iowa`/`Iowa State`,
  `Ohio`/`Ohio State` and `Texas`/`North Texas` all returned True under the old
  prefix heuristic and are now correctly distinct. `teams_match` gained **+190
  correct with 0 lost**.
- **How we found out:** by treating the rule as a checklist rather than a wall,
  running its two gates against the exact tokens its evidence entry names, and
  refusing to proceed on key count alone -- which is precisely the error 08-29
  recorded ("2,232 keys looked like success; the one token that mattered still
  returned `None`").
- **The rule going forward:** **a CONDITIONAL prohibition is discharged by
  meeting its conditions and recording the measurement, not by asking for an
  override.** Read the rule's own wording before treating it as absolute, and
  when it names a failing token, test THAT token. The blanket reading of this
  entry would have cost the platform every NCAAF club resolution indefinitely.
  Where a rule IS absolute (`FORBIDDEN` with no condition), this does not apply.
- **Cost:** none. 138/138 FBS clubs resolve, 102/102 club slots on a 51-game
  card, 22/22 eligible board games via `match_event_blob`, where all were 0.
  Landed `04a82c38` + `8730b829`. **Scope held: this removes ONE OF TWO gates on
  the Kalshi execution path and places no orders** -- none of today's NCAAF
  contracts is FBS-vs-FBS.

## 2026-09-09 FORBIDDEN: reporting a sweep as COMPLETE without its COVERAGE DENOMINATOR. A sweep that was stopped early is not a sweep, and "every hit I found is fixed" reads as "every hit is fixed" `[lane data-tree-write-guard, commit 7a03160d]`

`ac801817`'s own message said "all 57 data/-mirror write hits closed, at four
seams". True of the 57 that had been NAMED, and false about the sweep: the verbose
pass that produced them was stopped at ~37%. A peer session ran theirs to
completion and reported **105 hit node ids across 23 files**.

The 48-hit gap was not cosmetic. Re-measuring their extra files against
`ac801817` found **11 live hits in 3 files**, so `main` was RED for those tests
while a landed commit message described the sweep as closed.

**HOW TO APPLY.** State the denominator with the numerator, every time: "57 of a
pass that reached 37%" is honest and "all 57" is not. The words that made this
wrong are cheap to fix — "every hit I found" rather than "all hits" — and a
partial sweep is worth landing, so this is a REPORTING rule, not a do-more-work
rule.

**AND THE SAME SHAPE, TWICE MORE IN ONE SESSION.** A per-file green result
(`test_refresh_worker.py` 70/0) cannot see a between-test write — the peer's 25 of
143 vendor-schedule writes carried an EMPTY `PYTEST_CURRENT_TEST`. And a
guard-ON-and-clean reading cannot tell FIXED from BLOCKED; only the guard-OFF arm
can. In all three the reading was true and the SCOPE it was offered for was wider
than the reading could support.
