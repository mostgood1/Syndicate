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

## Index — 1106 rules `[generated]`

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
## 2026-09-09 FORBIDDEN: caching a `git check-ignore` verdict per DIRECTORY. The answer differs INSIDE one directory — that is the whole point of the exemption — and one query for an ignored name then exempts every TRACKED file beside it `[lane data-tree-write-guard, hole found by lane data-mirror-write-guard-sweep, fix ba732005]`

The guard in `tests/conftest.py` exempts a write whose path `.gitignore` already
excludes, and the exemption's stated basis is that **`git check-ignore` answers
NOT ignored for anything in the index, whatever rules match it** — so a new cache
file under an ignored-by-rule subtree is exempt while a TRACKED file beside it is
not. I then cached the verdict per directory "because a directory rule applies to
the whole subtree", which denies exactly that.

MEASURED, one directory holding 208 tracked files:

    tracked      -> False   correct
    ignored name -> True    correct, and PRIMES the per-directory cache
    tracked      -> True    WRONG — guard disarmed for the rest of the process

**THE SHAPE, past this instance: A CACHE KEY COARSER THAN THE PREDICATE IT CACHES
IS A CORRECTNESS BUG, NOT A PERFORMANCE TRADE.** The predicate here is per-PATH by
definition; keying it per directory cannot represent two answers, so the second
answer is silently replaced by the first. Check the key against the predicate's
own granularity before caching anything.

**AND THE SELF-CHECK POISONED IT.** The test that pins "a tracked file inside an
ignored subtree is still guarded" ended on a query for an ignored NAME in that
directory, priming the cache as its last act. It passed alone and failed only in a
parallel full run. So: **a guard's self-check must not leave the guard in a
different state than it found it** — and the general form, contributed by the
sibling lane, is that A SELF-CHECK FOR A GUARD MUST ASSERT THE GUARD IS INSTALLED
BEFORE IT EXERCISES THE GUARDED PATH, or the check's own failure mode is to
perform the damage it exists to detect.
## 2026-09-09 FORBIDDEN: trusting a LOCAL end-to-end test of a producer/reader pair that crosses SERVICES. Locally the state backend is `filesystem` — one process, one disk — so the test proves the code and says nothing about whether the two services share a store `[lane intelligence-coverage-artifact, commit 5c7af861]`

**What we believed.** The new coverage artifact was proven: the worker-side
publish and the web-side read were exercised end to end, and BOTH states were
observed — the page said "No coverage report published for this date yet", then
the loop logged `PUBLISHED date=2026-09-09 sports=8` and the page showed
"Published 13:12:20". That is a genuinely discriminating local reading.

**What was actually true.** It was a reading about the CODE, not the
DEPLOYMENT. `_state_backend_kind()` returns `filesystem` locally, so producer
and reader were one process writing and reading one disk. In production they are
two services, and *Render's disk cannot be shared between them* — the whole
reason `refresh_state_store` exists. The local pass would have looked identical
if the artifact were per-service disk, which would have made the page
permanently degraded in production while every test stayed green.

**How we found out.** Asking, before deploying web, which paths
`_keyvalue_backed()` actually covers — then reading the LIVE env-vars API for
both services rather than `render.yaml`. Backend and store URL matched. The
namespace did NOT look symmetric: web sets
`SYNDICATE_REFRESH_STATE_NAMESPACE`, refresh-worker omits it. That resolved
safely only because `_state_namespace()` defaults to exactly web's value
(`"syndicate"`). Had the default been anything else, the deploy would have gone
green and the artifact would have been written under one prefix and read under
another.

**The rule going forward.** For any artifact one service writes and another
reads, three things get checked on the LIVE services before the deploy, not
after: (1) the path is keyvalue-backed — no `_KEYVALUE_EXCLUDED_PATH_MARKERS`
hit; (2) `SYNDICATE_REFRESH_STATE_BACKEND` and `..._URL` match on both; (3) the
NAMESPACE resolves to the same string on both, **including when one side omits
the key and falls back to a default**. An asymmetric env var is not
automatically a bug and not automatically fine — resolve it to a value.

**And the generalisation of the near-miss:** a fallback default that happens to
equal the other side's explicit value is a correct system for an accidental
reason. It is worth writing down precisely because nothing in the code says the
two must agree.
## 2026-09-09 A REPLACEMENT THAT IS LESS INFORMATIVE THAN WHAT IT REPLACED IS A REGRESSION, however much better it looks. A generic branded 404 discarded the route's own `abort(404, description=...)` `[lane brand-mascot-logo, commit 00902dd1]`

**What we believed.** Adding the app's first-ever error pages was a pure gain —
before them a typo'd URL served Werkzeug's bare white default, with no nav and
no way back.

**What was actually true.** Some routes 404 with something far better than a
generic page can say. Soccer's unknown-league gate aborts with a description
naming every valid league slug; the new handler threw that away and printed
boilerplate. Strictly worse than the ugly page it replaced, for that route.

**How we found out.** `tests/test_soccer_blueprint_routes.py::
test_the_404_names_the_valid_leagues` — a test written for a different reason
that happened to pin the message. Nothing in review caught it, and the page
looked good.

**The rule going forward.** When replacing a generic surface with a branded one,
enumerate what the OLD surface carried that the new one drops. For HTTP errors
specifically: read `HTTPException.description` and prefer it, comparing against
the **class default** rather than truthiness — werkzeug always populates that
field, so a truthiness check silently prints its boilerplate instead of yours.

**Two sibling defects in the same change, both found by probe rather than
review, both the same shape — an instrument that cannot vary:** the 500 log line
printed `type(exc).__name__`, which Flask makes the constant
`InternalServerError` on every 500 ever logged (the cause lives in
`original_exception`); and `Accept: */*` scores html and json equally, so a `>=`
comparison tied and fell to JSON, making `curl` on an HTML path return a JSON
body. A tie is not a preference.
## 2026-09-09 FORBIDDEN: reading a ZERO-HOLDER result from `lane_claims` as "nobody is working on this file". It reports on lanes, and a session can be instructed not to open one. `[lane data-mirror-write-guard-sweep, session 83b5aca4]`

- **What we believed:** the documented collision check — `lane_claims.claims_by_path` over `origin/main:.syndicate/lanes.md`, the guard's OWN parser — answers "is anyone else editing these files". Zero holders means the files are free.
- **What was actually true:** it answers "does any lane BLOCK DECLARE these files". A second session was actively editing all four of my files, had already landed a commit touching them, and held two more unpushed — and returned ZERO, correctly, because its instructions explicitly forbade it from editing `.syndicate/*`, so it had never opened a lane. The check was accurate and the conclusion was wrong. The set it measures is SELF-SELECTED: a session told to stay out of the ledger is invisible to it BY CONSTRUCTION, and those are exactly the sessions least likely to coordinate.
- **How we found out:** the other session messaged mid-work asking me to stand down, then corrected me itself: *"my lane isn't declaring those files because I never opened a lane"*. Nothing in my own tooling could have surfaced it — I had run the strongest available check and it passed.
- **The rule going forward:** a zero-holder result is evidence about `lanes.md`, NEVER about the world. State it with its scope — "no OPEN lane declares these" — never as "these files are free". Before a multi-file edit to shared infrastructure (`tests/conftest.py`, `.claude/hooks/`, the ledger), pair it with a check the ledger cannot opt out of: `mcp__ccd_session_mgmt__list_sessions` for live sessions, and `git log --oneline -5 -- <paths>` for recent commits by anyone. A lane check plus a commit check disagree exactly when it matters. **And the check itself should report "N sessions declared" alongside the holder list** [suggested by `local_74f19a18`]: zero holders and zero DECLARERS read identically today, and only one of them means the file is free.
- **Cost:** two sessions duplicated a full sweep of the same suite — roughly 70 minutes of full-suite runs each, plus two rounds of user adjudication. No work was lost, because both sessions worked in isolated worktrees and neither pushed; the isolation protocol did its job even though the coordination protocol did not.
## 2026-09-09 FORBIDDEN: concluding a guard closed a hole because the symptom disappeared between two runs that ALSO differ in test ORDER. `[lane data-mirror-write-guard-sweep, session 83b5aca4]`

- **What we believed:** the newly-added `os.open` wrapper explained why a tracked mirror file (`live_lens_2026_06_02.jsonl`) was modified in run 1 and clean in run 2. It was the only relevant code change between them, and the file's `1 0` diff matched a copy path that uses `os.open` exactly.
- **What was actually true:** nothing of the sort. The A/B — wrapper present vs removed, one variable, same test — gave the IDENTICAL result in both arms: the test errors, the file stays at 20 lines, 0 dirty. The writer is caught by the ordinary `Path.open` guard either way. `pytest-randomly` reseeds every run, so run 1 and run 2 differed in test order as well as in code, and the order is the surviving explanation.
- **How we found out:** ran the mutation check instead of banking the story. It took 8 seconds and falsified a claim I had already sent to another session.
- **The rule going forward:** between two full-suite runs, code is never the only variable — `pytest-randomly` makes ORDER a variable too, and order decides which test reaches a shared artifact first and in what state. A symptom that moves between runs is attributable ONLY by a same-order A/B on the single change, never by "it was the only thing I changed". Corollary: when you hand a candidate explanation to another session, label it a candidate and go run the check, because the retraction has to travel as far as the claim did.
- **Cost:** one wrong candidate published to a peer session and retracted within the hour. Caught before either of us wrote it into a commit message or a `state.md` line.
## 2026-09-09 FORBIDDEN: isolating a test's side effects with a PER-TEST fixture when the thing being isolated can outlive the test. A function-scoped isolation is a WINDOW, not a wall. `[lane data-mirror-write-guard-sweep + local_74f19a18, generalised jointly]`

- **What we believed:** an autouse function-scoped fixture — `monkeypatch.setenv`, `patch.object`, a `tmp_path_factory` redirect — isolates a test's writes. It is the shape this repo's `conftest.py` already uses four times (`_isolate_reports_root`, `_isolate_kalshi_markets_artifact`, `_isolate_prediction_ledger`, and the `data/live` redirect), and each was added after a real dirty-tree incident.
- **What was actually true:** it isolates the test's MAIN THREAD, for the duration of the test. Anything that outlives the test — a background loop the test started, a thread still draining, a subprocess spawned late — runs after teardown has restored the environment, and writes to the REAL path. **MEASURED: of 143 mtime changes on one tracked artifact in a single full-suite run, 25 carried an EMPTY `PYTEST_CURRENT_TEST`** — i.e. they happened between tests, unprotected by construction. No single-file run can show this: with one test file the window is almost always open when the thread writes.
- **How we found out:** two independent instances turned out to be one defect. `local_74f19a18` shipped a subprocess block as an autouse fixture and my empty-`PYTEST_CURRENT_TEST` count showed it was in force only during tests; it was re-landed to enter once at conftest import and never exit (`cb13ce0f`). Separately, `reports/intelligence/*` kept coming back modified despite the function-scoped `_isolate_reports_root`. Same shape, different artifact.
- **The rule going forward:** decide isolation scope by the LIFETIME of what you are isolating, not by the convenience of the fixture. If the code under test can start a thread, a loop or a subprocess that outlives the call, the redirect must be applied ONCE AT IMPORT and never lifted — a `conftest` module-level patch, or an env var set before the first import — not an autouse fixture. Test for it with the population, not the happy path: **an empty `PYTEST_CURRENT_TEST` on a write is the signature**, and it only appears under a full parallel run. Corollary for verification: "I ran the one file and the tree stayed clean" does not test this at all.
- **Cost:** one shipped fix that was inert for the exact case it was written for, caught only because a second session was measuring the same artifact from a different angle. Plus an unknown number of `reports/` rewrites over an unknown period, since three of this repo's four isolation fixtures have the same scope.
## 2026-09-09 FORBIDDEN: adding an `out_dir`/`--out-dir` parameter whose DEFAULT resolves through `data_root()`, and then testing the flagged path. The assertion passes on the flag while the write lands in the mirror. `[lane data-mirror-write-guard-sweep + local_74f19a18]`

- **What we believed:** a test that passes an explicit output directory and asserts on the files there has controlled where the code writes.
- **What was actually true:** it has controlled only the writes that HONOUR the flag. THREE independent instances in one sweep, all the same shape: `append_book_quotes` resolves from `data_root()` and ignores the `--out-dir` its callers pass (`test_ncaab_refresh_runner`); `scripts/emit_settlement_inputs.py:265` takes `out_dir` if given and otherwise `data_root() / "settlement_inputs"`, and `run_refresh_worker.py:2869` calls `emit_for_date(target_date)` with no `out_dir` at all; `_persist_live_lens_report` resolves `live_lens_log_path` separately from `live_lens_report_path`, so a test that redirects the report still writes the log to the mirror. **The assertion on the flagged output is what HID all three** — it was green, and it was green about the wrong file.
- **How we found out:** an interceptor on the write seam, not a review. Each was invisible to a passing test suite; two were invisible to a `-k`-scoped run as well.
- **The rule going forward:** an optional output path is a two-branch function and the tests must cover BOTH branches — call it with the flag AND without. When adding one, make the default raise or require the caller to be explicit rather than silently resolving to `data_root()`. When reviewing a "writes to the wrong place" bug, the question is never "does the test pass an out_dir", it is "does every writer on that path READ it".
- **Cost:** three separate fixes in one sweep for what is one API shape, plus the original reported symptom (`book_quotes/.jsonl` with an empty date prefix) that started the whole guard.
## 2026-09-09 FORBIDDEN: a guard self-check that exercises the guarded path BEFORE asserting the guard is installed. Its failure mode is to PERFORM the damage it exists to detect. `[lane data-mirror-write-guard-sweep + local_74f19a18]`

- **What we believed:** a test for a guard proves the guard works by doing the forbidden thing and asserting it was refused.
- **What was actually true:** that is only safe if the guard is present. When it is NOT — a regression, a mutation check, a half-finished refactor — the test proceeds to do the forbidden thing FOR REAL, and the check becomes the writer. Two instances in one day. Mine: with the `os.open` wrapper removed for a mutation check, the self-check's own `os.open(..., O_CREAT)` SUCCEEDED and left a real file in `data/`. `local_74f19a18`'s: a self-check for the vendored-schedule block, if the block is absent, proceeds to call the real `_fetch_basketball_schedule_via_cli` — so the test guarding the tracked file becomes the thing that rewrites it, over the network.
- **How we found out:** independently, from both sides, and only because both of us ran mutation checks. A guard test that has only ever been run WITH the guard installed cannot show this.
- **The rule going forward:** ORDER THE ASSERTIONS. A guard self-check asserts the guard is INSTALLED first — against a floor the test can see (`_VENDORED_SCHEDULE_FETCH_BLOCK is not None`, a `mirror_roots()` accessor, a marker attribute) — and only then exercises the guarded path. And its cleanup must assume the write MAY have landed, because in exactly the run where the assertion is about to fail, it did.
- **Cost:** one real file written into the tracked mirror by the guard's own self-check. Caught immediately because the mutation run was being watched; in CI it would have been a dirty tree with the guard reporting green.
## 2026-09-09 FORBIDDEN: accepting a mutation check that PASSES without first proving the mutation was REACHED. A no-op mutation and a working guard are the same green. `[lane data-mirror-write-guard-sweep]`

- **What we believed:** a mutation check that comes back green on the fixed code and red on the broken code proves the test binds — and if the "broken" arm stays green, the finding must not be real.
- **What was actually true:** the broken arm can stay green because the MUTATION NEVER RAN, or because the test cannot see it. THREE times in one session, each looking like a clean pass: (1) the patch script's `assert raw.count(old) == 1` failed and the file was never written, so both arms ran identical code; (2) a probe spawned a subprocess from INSIDE a test, where the per-test fixture was active either way, so it could not distinguish; (3) a regression test picked a file in a SUBDIRECTORY, and the defect was keyed on the parent directory, so the poisoned cache entry never applied. In (2) and (3) the test passed against a deliberately reintroduced bug.
- **How we found out:** by running an independent probe — a plain script, outside pytest — against the mutated code and confirming it reproduced the defect. When the probe said "HOLE CONFIRMED" and the test said "passed", the test was wrong.
- **The rule going forward:** a mutation check has THREE outcomes, not two: red (binds), green-because-fixed, and **green-because-the-mutation-did-not-land**. Distinguish them before reading the result. Assert the mutation is present in the file after writing it, and confirm the mutated path is REACHED — an independent probe, a print, a deliberate exception. A test that passes against the reintroduced bug is not a regression test, and the arm that "confirms" your fix is the one most likely to be lying. **GENERALISED, after a FOURTH instance the same day and across two sessions [formulation: `local_74f19a18`]: A CONTROL MUST BE SHOWN TO FAIL IN THE ARM WHERE THE THING IS BROKEN, AND PASSING IS NOT EVIDENCE UNTIL IT HAS.** This is not only about mutation checks. The four, every one of which looked like a clean pass: (1) a child-process probe run INSIDE a test, where the per-test fixture was active in both arms; (2) a regression test that globbed a directory and picked an untracked, ignored shard, so it failed against a CORRECT guard; (3) one that picked a file in a SUBDIRECTORY when the defect was keyed on the parent, so it passed against a deliberately reintroduced bug; (4) a floor probe using `monkeypatch.delenv`, which removes the variable outright instead of peeling off the per-test layer, and prints `None` whether or not the wall exists. In all four the arms were indistinguishable by construction, and in none of them did the runner say so.
- **Cost:** three false reads inside one investigation. Two would have shipped a regression test that pins nothing, against a real correctness hole.
## 2026-09-09 FORBIDDEN: a ledger-append check that only counts DELETIONS. The merge hazard is ADDED lines nobody wrote today. `[lane data-mirror-write-guard-sweep + local_74f19a18]`

- **What we believed:** `git diff --numstat` showing ZERO deletions proves a ledger append did not clobber another session's work. It is the check this repo's rules already prescribe, and both sessions ran it on every ledger write all day.
- **What was actually true:** it catches the clobber and is blind to the inverse. A rebase's 3-way merge RESURRECTED a stale lane block — re-adding `### intelligence-coverage-artifact` in its older OPEN form beside the CLOSED block that was current, silently reverting another session's lane to a status they had already moved past. The diff was **9 INSERTIONS, 0 deletions**, and sailed straight through the check. Caught by `ledger-postwrite-check.py`'s duplicate-slug rule, not by the append discipline.
- **How we found out:** the post-write hook flagged "a lane with MORE THAN ONE block" mid-rebase. `local_74f19a18` then audited their own `lanes.md` the same way and was clean — 22 blocks, 22 distinct slugs — but noted that a duplicate-slug count would MISS the variant that resurrects content INSIDE a block without duplicating the header, and checked per-commit that every added line was theirs.
- **The rule going forward:** **the check is not "0 deletions", it is "every ADDED line is one I wrote."** Same cost, strictly stronger, and it catches both directions. Per-commit: `git diff --numstat` for the deletions AND `git diff origin/main -- <ledger file> | grep '^+'` read against what you actually authored. A duplicate-slug count is a necessary backstop, not the check — it cannot see a resurrection inside an existing block.
- **Cost:** one silent revert of another session's lane status, introduced by my own rebase, in a file whose whole purpose is cross-session exclusivity. Zero lines were deleted.
## 2026-09-09 FORBIDDEN: attributing a test's red->green flip to ORDERING without first checking what LANDED between the two runs. I made this error in BOTH directions in one day. `[lane data-mirror-write-guard-sweep]`

- **What we believed:** first, that a symptom moving between two full-suite runs was caused by the one code change I had made (it was ordering); then, having learned that, that a test flipping red->green between two runs was ordering (it was a fix).
- **What was actually true:** both times TWO things had changed and I named one. `tests/test_probability_differential.py::test_every_converter_is_registered_or_excused` failed in my run 7 and passed in my run 8, and I reported it as order-dependent. It was not: another session's fix `f6c7a3ac` landed 12:37, my run-8 base `c9d6660d` is 13:47, so **the fix was in the tree**. `git merge-base --is-ancestor f6c7a3ac c9d6660d` -> YES. I was one message away from sending that wrong correction to the session that owns the lane, whose own reading (10 passed vs a 1-failed baseline) was right.
- **How we found out:** checking the ancestry before sending the correction, because the claim was about somebody else's work. The same check would have taken ten seconds before publishing it the first time.
- **The rule going forward:** on a shared fast-moving `main`, the tree is a variable between ANY two runs, and usually the largest one. Before attributing a flip to ordering, run `git log <base1>..<base2>` and `git merge-base --is-ancestor <candidate fix> <base>`. "Order-dependent" is a claim about a POPULATION of orderings and needs repeated runs on ONE tree; a single flip across two different trees is evidence about the trees. Corollary: the more experienced you are with the ordering explanation, the more available it becomes — I reached for it precisely because I had just been burned by the opposite error.
- **Cost:** a wrong attribution published to two sessions and nearly a third, plus an inaccurate framing offered to the lane owner about their own closed work. Caught before delivery, by one ancestry check.
## 2026-09-09 FORBIDDEN: AMPLIFYING a peer's unverified CONCLUSION into a relay to a THIRD lane, without measuring it yourself. The bar for a claim about someone else's CLOSED lane is higher than for one about your own, not lower `[lane data-tree-write-guard, caught by lane data-mirror-write-guard-sweep before it was sent]`

**THE ORIGINATION IS CORRECTED HERE `[2026-09-09, at that lane's own
insistence]`. This entry first said they reported an OBSERVATION and that I turned
it into a conclusion. That was wrong in the direction that flattered them, and they
refused it.** What they actually sent, verbatim, was: *"`test_probability_
differential` passed this run, which makes it order-dependent too rather than
reliably red -- worth knowing for the lane you spun out."* "Passed this run" is the
observation; everything after the comma is a CONCLUSION about a third lane's closed
work, with a recommendation to act on it attached.

So the sequence was **their unverified conclusion -> MY AMPLIFICATION into a
proposed relay -> their verification stopping it.** I had spun that test out to
lane `probability-converter-registry` (session 359fa678) on the strength of it
being red on `main`, and that lane had CLOSED it; I agreed with their conclusion
and proposed they tell that session "order-dependent is the more accurate word"
than its own "was RED on main and is now green".

**I DID NOT CHECK, AND IT WAS WRONG.** The peer verified before sending and it does
not survive one command:

    f6c7a3ac  12:37:31  the converter fix
    bdc6ed50  12:08:12  their run 7 base -> `merge-base --is-ancestor` NO
    c9d6660d  13:47:28  their run 8 base -> `merge-base --is-ancestor` YES

It passed because it was FIXED. That lane's framing was exactly right, its
1-failed/10-passed baseline was the right measurement, and my "order-dependent"
was an unforced attribution error about work I had not measured, belonging to a
session that was not in the conversation to defend it.

**WHY THIS IS WORSE THAN AN ORDINARY WRONG NUMBER.** A wrong reading about my own
lane costs me a re-run. A wrong correction RELAYED into a third lane's closed
record costs that session its verdict, and it arrives with a peer's authority
attached rather than mine. The chain was: their CONCLUSION -> my amplification
into a proposed relay -> a message to a third party. NEITHER of us had measured it,
and the amplification is the step that would have made it arrive carrying two
sessions' apparent agreement.

**HOW TO APPLY.** Before relaying anything as a correction to another lane: run the
discriminating command yourself, and if you cannot, relay the OBSERVATION with its
provenance ("their run 8 passed; I have not checked why") and never the CONCLUSION.
"Order-dependent" is a claim about a POPULATION of orderings and needs repeated
runs on ONE tree — a single flip across two DIFFERENT trees is evidence about the
trees. On a fast-moving shared `main` the tree is a variable between any two runs
and usually the largest one: `git log <base1>..<base2>` first.

Related, same day, same pair of sessions: [a-cache-key-coarser-than-its-predicate]
and the rule that a control must be shown to FAIL in the arm where the thing is
broken. Four non-discriminating controls between two sessions in one day; this is
the fifth instance of trusting a reading that had not been made to fail.
## 2026-09-09 FORBIDDEN: appending a rule to `learnings.md` without running `build_learnings_index.py`. The rule is then INVISIBLE to the index every session reads, and nothing anywhere reports the drift `[lane data-tree-write-guard, found while correcting an unrelated entry]`

Measured 2026-09-09: `grep -c` for my freshly appended rule in
`.syndicate/learnings_index.md` returned **0**. I had appended to `learnings.md`
and never regenerated. Running `py -3 scripts/build_learnings_index.py` did not
add one rule, it added **31** -- the index header went **917 -> 948**. So this is
not my slip alone; it is the steady state of a file several sessions append to and
nobody regenerates.

**WHY IT MATTERS MORE THAN A STALE COUNT.** The index is the file the session-start
digest and every "what do we already know about X" search actually reads;
`learnings.md` itself is 948 rules and no session reads it whole. A rule that is
in `learnings.md` and not in the index has been WRITTEN and not PUBLISHED. It will
be rediscovered the expensive way, which is precisely what the ledger exists to
prevent -- and the author has no signal, because the append succeeded, the commit
succeeded, `git status` is clean, and the diff shows exactly the lines intended.

**THE SHAPE, past this instance: A GENERATED VIEW THAT IS NOT REBUILT BY THE WRITE
THAT INVALIDATES IT WILL DRIFT SILENTLY, AND THE DRIFT IS INVISIBLE FROM THE SIDE
THAT WRITES.** Same family as the `state.md` subject index, which at least refuses
(`split_state.py --reindex` is documented as required when adding a subject) and
which the same day was found missing two subjects that existed in a part.

**HOW TO APPLY.** Append and regenerate in ONE step, and verify by reading the
GENERATED view rather than the source. **Grep a SHORT distinctive substring, not
the heading:** the index truncates each heading with an ellipsis, so my own first
check used the full heading, returned 0 against an index that DID contain the rule,
and read as the very failure it was testing for. A false alarm in the same family
as the four non-discriminating controls this pair of sessions logged the same day --
the pattern has to be able to match before its 0 means anything.
### 2026-09-09 — FORBIDDEN: quoting a spending cap, limit or flag from `env-vars` when a STORE can override it — and treating a one-source instrument's negative as a fact about the value

- **What we believed:** that `live-odds-worker`'s environment held the live
  execution caps — `MAX_ORDER_DOLLARS=10`, `MAX_DAY_DOLLARS_KALSHI=50`,
  `BANKROLL_UNITS=40` — and that they were a testing leftover throttling the
  platform's largest measured lever to ~$2/day.
- **What was actually true:** a STORED settings store overrides the environment
  on every one of those fields and has since **2026-09-04T13:21:37-05:00**.
  Resolved: **`max_order_dollars` 35.01, `max_day_dollars_kalshi` 150.01,
  `max_day_orders_kalshi` 15, `bankroll_units` 1000** — `/api/portfolio/limits`
  and `/api/portfolio/settings` report `"stored"` for every field with
  `store_error: null`. The prize was understated **~3x**, and the conclusion
  flips from "raise the caps" to "score the edge; no cap decision is pending".
- **How we found out:** only by reading the endpoint that reports what the guard
  RESOLVES, after three env vars set on the user's authority had no effect.
  **The pre-check that was supposed to catch this returned a clean, confident
  negative** — `/api/ops/artifacts/export?pattern=…execution_limits.json` →
  "NO STORED LIMITS FILE". The store lives in the **keyvalue backend**, which
  artifact export cannot see; `execution_limits_settings.py:19-25` says so in its
  own docstring, and [[project_keyvalue_artifact_split_blinds_guards]] already
  recorded the split.
- **The rule going forward:** **a cap has a RESOLVED value and a SET value, and
  they are different objects — never quote the SET one.** Read the endpoint that
  reports the guard's resolution and read its `sources` map. Generally: **when a
  value has more than one possible source, an instrument that can see only one
  source cannot produce a negative result ABOUT THE VALUE — only about its own
  source.** A clean negative from such an instrument is worthless and reads
  exactly like a real one.
- **A SECOND READER AGREEING IS NOT CORROBORATION WHEN BOTH READ THE SAME WRONG
  SOURCE.** A subagent independently reported the same env-derived caps; two
  wrong readings of one source is **one error counted twice**, and that is why
  this survived an afternoon of work built on top of it.
- **Cost:** none shipped, by luck rather than design — the env values set were at
  or below the stored ones and stored wins regardless, so no live limit moved.
  Had env governed and the values been higher, this session would have raised
  real spending limits on a false premise. Three now-inert env vars remain and
  are owed a reconciliation; **do not simply delete them**, because absent
  resolves to a code default that differs from both the env and the stored value.
## 2026-09-09 FORBIDDEN: scoping a fix from the COUNT written in the lead that reported it. A lead's number is the author's hypothesis at the moment of noticing; re-census first `[lane probability-converter-registry]`

Three leads followed in one session, and **every one of the three undercounted
the thing it named** — each time by a factor, and each time the real number
changed what the right fix was:

| the lead said | the census found | what it changed |
|---|---|---|
| "SIX byte-identical copies of two JS renderers" | **74 definitions** — ALL 15 functions in both reconciliation templates, 11 across all four market-accuracy ones | the fix was two modules, not one edit |
| "residual THREE-way `localYMD` duplication" | **6 definitions in 2 implementations**, five of them already inside shipped modules | the fix became one parameterised function, not a 3-way hoist |
| "NBA settlement books EVEN MONEY on a missing price" (one function) | **3 sites in 2 modules**, one of them CROSS-SPORT | fixing only the named one would have left the same defect live in soccer/MLB/NBA live-lens |

And the same session produced the INVERSE: a "6 Eastern vs 3 Central" census I
wrote into a lead myself turned out to have counted three different things as
one — slate-date resolution, display formatting, and a deliberate ET comparison
that must NOT be changed. Only **two** of the six were what the lead implied.

**WHY IT HAPPENS, and why it is not carelessness.** A lead is written at the
moment of NOTICING, from whatever grep surfaced the thing — usually a
first-line or single-token match, on the file that happened to be open. That is
exactly the cheapest and least accurate moment to count. `/lead`'s whole value
is that it costs nothing to record, and the cost it saves is the census.

**HOW TO APPLY.** Treat the lead's number as the lower bound and the lead's
FRAMING as unverified. Before scoping: re-census over the full tree with a
matcher that can see the whole construct (full function BODIES, not first
lines; templates AND static; nested and method scope, not just column 0), and
CLASSIFY the hits before counting them — "same string" is not "same thing", and
the NHL live-polling comparison would have been broken by a fix that treated it
as one more instance.

**The cost of not doing it is asymmetric.** Under-counting ships a fix that
leaves the defect live somewhere else, and the ledger then records the lead as
CLOSED. Over-counting only wastes a grep.
## 2026-09-09 FORBIDDEN: reporting a STAGE, FEATURE or MECHANISM as OFF because its env flag is ABSENT, without finding the resolution site and checking for an UNCONDITIONAL installer. A stage's state is a property of the PROCESS THAT RAN IT, not of the environment `[lane segments-joint-v1, my SECOND instance of this shape in six hours]`

**WHAT HAPPENED.** The step 5 recon read five flags off both workers, found four
ABSENT, and reported "five of six stages are shipped dark". One of the five was
wrong. `pipeline/layer2_shortlist.py:664` calls `install_measured_correlation`
UNCONDITIONALLY and by design (`#621` phase 4), writing a PROCESS-WIDE resolver
registry that all ten `compute_correlation` call sites read -- including
`bankroll_manager.compute_correlation`, so it reaches BET SIZING. Its own
counter shows 61 of 62 installs True on the date that has sims, 54 of those
across the full 15-game slate. It had been live all day. And
`SYNDICATE_PARLAY_MEASURED_JOINT`, the flag I read, gates something NARROWER
than its name: only the n-leg phi expansion in the parlay runtime.

**WHY THIS IS ALREADY A RULE AND STILL HAPPENED.** Six hours earlier the same
lane retracted the execution caps for the same reason and wrote *"a cap, limit
or flag has a RESOLVED value and a SET value, and they are different objects."*
That correction was about a STORE overriding env. I filed it as a fact about
stores, so when the second case had no store -- just an unconditional call site
-- the rule did not fire. **The generalisation is not "check the store". It is
that reading configuration NEVER establishes what code did.**

**HOW TO APPLY.** Before writing any on/off verdict: (1) grep every reference to
the flag NAME and confirm the resolution site is the only one; (2) grep the
mechanism's installer/entry symbol separately -- an unconditional caller will
not appear in a search for the flag; (3) prefer a reading the code already
prints. `install_measured_correlation` printing `installed=` on every build,
including when nothing is installed, is why this was catchable in one query.
That counter exists because its author wrote that a resolver answering `None`
for everything is indistinguishable from one nobody wired up -- **the same
ambiguity my flag read walked into.**

**COROLLARY WORTH MORE THAN THE CORRECTION.** A mechanism installed into a
process-wide registry resolves DIFFERENTLY PER DECISION PATH depending on which
process installed it, and no flag anywhere reports that. Any claim of the form
"X is on" is incomplete without naming the process.
## 2026-09-09 FORBIDDEN: trusting a season/week (or any period) resolver that derives from a DIFFERENT artifact family than the one you are about to read. It lags by exactly as long as the two families disagree, and the join then returns nothing -- which is indistinguishable from "the model has no view" `[lane nfl-prop-model-coverage, caught by a reachability run, not by 13 green unit tests]`

**WHAT HAPPENED.** The new NFL prop join asked `latest_season()` which season to
read. On 2026-09-09 it answered **2025** while the artifact on disk was
`nfl_prop_projections_2026_wk1.json`. `latest_season` derives from
`week_summaries()`, which globs the **SmartSim2 projection** family -- a
different family on a different publish cadence. Early in a season, when week-1
props exist and last season's projections still dominate that glob, it is a year
behind. The join stamped ZERO rows and reported success.

**THIRTEEN UNIT TESTS WERE GREEN THROUGH THIS.** They all passed an index in
directly, so none of them exercised resolution. Only running the real entry
point against the real published artifact showed it, which is
`model_engine_standard.md`'s "reachability test before correctness tests"
earning its keep on the first try.

**AND THE FIRST FIX WAS ALSO WRONG, THE SAME WAY.** The fallback scan probed
`[resolved, resolved - 1]` -- so from a resolved 2025 it could never reach 2026,
the very year it needed. A fallback built on the same bad input inherits the bad
input. What fixed it was a signal that does NOT depend on which artifact family
is on this disk: **the season the DATE names.**

**HOW TO APPLY.** (1) Resolve a period from something intrinsic to the request
(the date) or from the family you are actually reading -- never from a sibling
family's presence on disk. (2) When you must fall back, make the fallback's
inputs independent of what failed. (3) Report WHICH period answered
(`artifact_season`/`artifact_week`) and whether a fallback ran
(`resolution="artifact_scan"`), so an empty join is attributable instead of
silent. This repo has shipped period self-pinning before -- `#471`, NFL week
pinning to 1.

**THE GENERAL SHAPE, which is the part worth keeping:** an empty join and an
honest "nothing to join" are the same observation unless the code says which
inputs it used. Every join that can address the wrong partition must name the
partition it addressed.
## 2026-09-09 - FORBIDDEN: predicting that a consumer-side key fix will start resolving, without first checking that the PRODUCER's data reaches its key builder at all. The field being absent from a key and the data being absent from the function are different defects, and the second makes the first's fix inert `[lane odds-history-segment-term, commits cff0cd4e / 26c8cfc6, DEPLOYED]`

- **What I believed:** having added `segment` to `clv_join._history_key`, I wrote
  in that commit -- and told the user -- that segment CLV would become available
  "the moment `_odds_history_market_key` emits a `segment=` part; this key
  already matches it, and nothing else here needs to change."
- **What was true:** the producer's key list was the SMALLER half of its problem.
  `_market_rows_from_mapping` descends `markets`, meets the container key
  `segments`, stamps `market="segments"` from the container NAME and stops --
  the level below is segment names (`first5`), which is neither a recognised
  container nor a line snapshot. **The whole subtree had never produced a row.**
  Measured by running the real flattener over a real 15-game snapshot: **45 rows
  out, 15 each of h2h/spreads/totals, ZERO carrying a segment.** Adding
  `segment` to that key alone would have shipped INERT and looked done.
- **Why the wrong belief was so comfortable:** the consumer's defect was
  legible -- a field missing from a tuple -- so I generalised it to the other
  side of the same contract. Both halves were "missing `segment`", which is true
  and useless: one was missing a FIELD FROM A KEY, the other was missing the
  DATA ENTIRELY.
- **The check that would have caught it in one command**, and which is now the
  rule: before predicting a consumer will resolve, run the producer's real
  reader over a real input and count the rows carrying the field. Not a grep for
  the field name -- the field name appears in the snapshot, in the fetcher and
  in the segment map; it was the ROW COUNT that was zero.
- **Cost:** none shipped, because the reachability run happens before the commit
  in this repo's standard (`model_engine_standard.md`: reachability test before
  correctness tests, `off != on`). That standard is written about sim engines
  and it caught a key builder -- **its scope is wider than its title.**
- **Generalises to:** any two-sided contract fixed one side at a time --
  `_KEY_FIELDS` consumers, board joins, settlement identity. `presence != reachability`
  already exists as a rule; this is the producer-side twin of it.
## 2026-09-09 FORBIDDEN: measuring a change against a harness that SUPPLIES AN INPUT PRODUCTION DOES NOT HAVE. The result describes the harness, and the gap can be the entire effect `[lane nfl-prop-model-coverage, caught only because the prediction was written down BEFORE the reading]`

**WHAT HAPPENED.** To estimate how many NFL prop rows a new join would give a
usable model edge, I ran the real code over real served board rows. Those rows
carry no two-sided `consensus`/`sides`, and the de-vig needs both, so I
RECONSTRUCTED the consensus by pairing the board's own over/under best prices.
That produced **950 edged rows of 1,019**, and a prediction of ~726 reaching the
sizer.

**PRODUCTION PRODUCED ZERO.** Not 726, not 64 -- **0 of 112 rows carry
`edge_vs_market_pct`**, every one reporting *"one-sided market: no two-sided fair
to price against"*. Served prop rows are one-sided, always. The 950 was entirely
manufactured by the reconstruction. The join still works -- the value arrives
through a FALLBACK path I had not designed for -- but the number, the mechanism
and the confidence were all wrong.

**I LABELLED IT AND SHIPPED IT ANYWAY.** The commit said the figure was
"INDICATIVE, not exact". That was too generous by a category: an indicative
number is the right quantity measured roughly, and this was a different quantity.
**I had ALSO measured the honest number in the same run -- 64 edged without
reconstruction -- and set it aside as the less interesting one.** The correct
reading was in hand and was discarded for the flattering one.

**WHAT MADE IT RECOVERABLE.** The prediction went into `deploys.md` BEFORE the
reading, with the reasoning and the caveat. When the reading came back it could
not be quietly re-narrated, because the number it had to beat was already
written down. **Pre-registration is what turns a wrong prediction into a
finding instead of an embarrassment.**

**HOW TO APPLY.** Before trusting any local measurement of a production effect,
ask: *which fields did I provide that production does not?* Any such field
invalidates the reading for that quantity. If a required input is absent in
production, that ABSENCE IS THE FINDING -- report it, do not synthesise around
it. And when a run yields both a flattering number and a plain one, the plain one
is the measurement; the flattering one needs a reason to exist that is not "it
looks better".

Fourth instance this session of the same family
([[feedback_instrument_blindness]]): caps read from env when a store governed;
a counter that is structurally zero on the path being taken; a flag read instead
of its unconditional installer; and this. **All four were the reading being about
the instrument rather than the system.**
## 2026-09-10 — REQUIRED: before restoring a shared ledger file over its working copy, audit it for sections that exist ONLY there — and audit by inner CONTENT, because a header-set comparison lies in BOTH directions `[lane odds-history-segment-term]`

- **The primary tree is where work goes to be forgotten.** Cleaning my own redundant edits out of its `lanes.md` and `deploys.md`, I found a complete 9,889-char deploy row from lane `ncaaf-games-cache-refresh` — a finished verification, its lane still OPEN — that existed in **no commit, no worktree and no stash**. A plain `git checkout origin/main -- <files>` would have destroyed it, and I would never have known. This is the same hazard as `2026-09-02 FORBIDDEN: a git command that can DISCARD work taking its tree from the working directory`, where `m625-env-snapshots` was actually lost; **that entry has the mechanism, this one has the check.**
- **How to apply.** Before any restore/checkout over a shared ledger file, diff the two versions at SECTION level and list what exists only in the working copy. Then confirm each hit by **distinctive inner content** — a SHA, a byte count, a measured figure — never by header text: my header-set pass reported **two** unpushed rows and one of them was a false positive, because these headers carry em-dashes that encode differently through `git show` than in the working copy. The same encoding gap can hide a real orphan, so the failure runs both ways. Rescue by landing the block from a worktree based on `origin/main` (append-only files: 0 deletions), never by keeping the stale file. **And `git checkout <rev> -- <path>` STAGES what it writes** — on this repo's shared index that parks the change where another session's commit can sweep it up, so `git restore --staged` immediately and verify the index is empty.
- *(evidence in `learnings_evidence.md`)*
## 2026-09-10 — FORBIDDEN: publishing "this remedy does not work" from ONE invocation form of a tool. `attrib -R <dir> /S /D` failed because `/S` makes the last path component a NAME to match; `attrib -R "<dir>\*" /S /D` works — and the failed form carried a WRONG MECHANISM into the ledger for four days `[lane worktree-close-and-prune, correcting lane git-out-of-onedrive 2026-09-06]`

- **What we believed** (`state_ledger.md [git-store-onedrive]` and the 2026-09-06 entry *AN ATTRIBUTE'S NAME IS NOT ITS SEMANTICS*): Windows ignores ReadOnly on directories; the blockers were read-only `logs/` and `refs/` FILES; `attrib -R /S /D` does not work, so "do not reach for `attrib`".
- **What was actually true**: the reverse on every point. `logs` and `refs` are DIRECTORIES, and they are the read-only entries; the files inside are not (`logs\HEAD` = Archive + ReparsePoint + PINNED). `rmdir` on a read-only directory fails (`PermissionError 13`), and a lab repo OUTSIDE OneDrive with the directory bit alone reproduces git's exact `failed to delete '.git/worktrees/<id>': Permission denied` and the exact husk shape. `attrib` works in the `"<dir>\*"` form; the 09-06 form only ever cleared `<dir>` itself, which is why its count did not move.
- **How we found out**: one lab husk per remedy, read-only count and survival measured after each — 5 remedies, 2 fail (`attrib -R "<dir>" /S /D`, `shutil.rmtree(ignore_errors=True)`).
- **The rule going forward**: a negative verdict on a remedy is a claim about the INVOCATION until a second form has been tried — quote the exact command line in the verdict. A mechanism written into the ledger must come from a reproduction that varies ONLY that mechanism (here the attribute, with OneDrive absent), never from which remedy happened to work. The 09-06 entry's own rule — test the mechanism on one instance before describing it — was the right rule; it was not applied to a directory.
- **Cost**: four days of the ledger steering sessions away from a working fix; husks regrew 83 -> 122 unseen; `session_worktree.py close` crashed in the fallback this failure triggers.
## 2026-09-10 — FORBIDDEN: running anything from `REPO_ROOT = Path(__file__).parents[1]` after deleting a checkout, or acting on SHARED state from it. With one worktree per session a script's own copy lives INSIDE a session tree, so `REPO_ROOT` means "the checkout this copy came from", not the repo. Resolve the MAIN worktree explicitly `[lane worktree-close-and-prune]`

- **What we believed**: `REPO_ROOT` is the repository, so a git call from it is always safe.
- **What was actually true**: `py -3 C:/tmp/syndicate-sessions/<lane>/scripts/session_worktree.py close --lane <lane>` makes `REPO_ROOT` the very tree `close` deletes. Its fallback deleted the directory, the next `git()` (default `cwd=REPO_ROOT`) raised `NotADirectoryError [WinError 267]`, and the branch was never deleted. An earlier `--force` close took the same fallback and survived only because it ran a copy living in another tree — the flag was not the difference. Second instance of the shape after `#497`, where `deploy_claim.py` wrote its claim into the worktree and the lock went silently non-mutual.
- **How we found out**: a test that runs `close` with `REPO_ROOT` set to the closed tree reproduces `[WinError 267]` on the unfixed script and passes on the fix. The lab showed `git worktree remove` run with its own cwd inside the target exits 255, and a retry exits 128 `is not a working tree` — the two codes in session transcripts.
- **The rule going forward**: a script under `scripts/` that deletes a checkout, or reads or writes state shared across sessions (claims, locks, the worktree registry), resolves the main worktree — `git worktree list` names it first, and `--git-common-dir`'s parent breaks if `.git` ever moves — and uses THAT, never `REPO_ROOT`. Test it with `REPO_ROOT` pointed at a session worktree.
- **Cost**: one crashed close, one orphaned branch, and two exit codes nobody had attributed.
## 2026-09-10 — REQUIRED: before recording a producer fix as "in force once the artifact is rebuilt", check EVERY site on the path that WRITES that artifact. The WNBA EV refusal covered 2 of 3 prop sites, and the one it missed is the slate writer `[lane wnba-accuracy-assessment, session 8c631ba2]`

- **What we believed**: the WNBA EV refusal (`_plausible_ev_pct`, 2026-09-01) would reach the served slate on the first post-break rebuild. `state_basketball.md [wnba-settlement-live]` and the lane said so for nine days.
- **What was actually true**: it is applied at `refresh_wnba_oddsapi_props.py:2081` (game picks) and at `:2286` and `:2354` (props). It is NOT applied at `:2192`, the prop loop of `_build_local_recommendations_slate_artifact`, which is the one that writes `recommendations_slate_<date>.json`. NBA's port applies it at both of its prop sites. On the slate, `ev_pct` is also `score` and the within-game sort key, so the omission is not cosmetic.
- **How we found out**: a code trace of what the 09-17 rebuild actually runs, then a grep of every `top_play.get("ev_pct")` in both producers. Four sites apply the refusal; one does not.
- **The rule going forward**: a fix is in force on an artifact only if it is on the path that WRITES that artifact.
  - Name the writer.
  - Grep the fixed input (here `top_play.get("ev_pct")`) across the writer's call chain.
  - List the sites with and without the fix before writing "in force after rebuild".
  - A complete sibling port (NBA here) is the fastest diff.
- **Cost**: nothing in money (no WNBA slate was written 08-31..09-16). Nine days of a ledger line overstating a fix, found seven days before it would have been read as proven.
## 2026-09-10 — RECURRENCE, not a new rule: I shipped a fix predicted from a REFRESH-WORKER instrument and measured it on WEB. It was right for the service the instrument read, and inert on the service that serves the symptom `[lanes mlb-final-state-mapping / mlb-lens-final-status]`

- **What I believed**: `/mlb/api/cards?date=2026-09-03` served ATH@SEA `Live` because `_merge_live_lens_row_into_game` overwrote a feed-derived Final. The basis was 09-04's `FEED_LIVE_STATUS ... source_status_abstract='Final'` for all nine games.
- **What was actually true**: `FEED_LIVE_STATUS` prints only when `not _render_web_dyno()`, so it is refresh-worker's feed map. WEB serves the route, and it holds ZERO `feed_live` files for September (`export?names_only=1` `count=0`; June control 78). On web the base status is `Pregame/Scheduled` and the frozen lens row is the only status. A guard that protects a Final base cannot fire where there is none.
- **How we found out**: the post-deploy reading, +31 s after `finishedAt`, matched the pre-deploy baseline game for game. The discriminating fields had been in the served payload all along: `gameDate` empty and `detail` = the date on ALL nine games, Final and Live alike. A present feed payload populates both.
- **The rule going forward** -- the same family as 2026-09-06 "instrumenting join A, reading it, and concluding about a value written by join B". Before predicting a served value from an instrument, read the instrument's own GATE (`if not _render_web_dyno()`, `in_request=`) and confirm it ran on the service that SERVES the surface. If it cannot have, read the INPUT on that service first; here that was a 30-second `export?names_only=1` for the feed files, taken with a control that can read non-zero.
- **Cost**: one web deploy that moved nothing, plus a closed-lane verdict and a state paragraph corrected within the hour. The fix itself stands: it is correct for refresh-worker's board builds.
## 2026-09-10 — FORBIDDEN: clearing a stranded ledger row on a field that the LOST write set. A lost update restores the other writer's stale copy of the WHOLE row, so every field that write carried is gone with it `[lane write-ahead-build-refusal]`

- **What we believed**: the order refused at build on 2026-09-04 (`6bc5617ccc3bf1f54d02bb35`) could be auto-cleared by reconcile. The rule proposed was: a `submitted` row with no `venue_order_id`, whose recorded error shows `venue_contacted=False`, never reached the venue. It was one of the two remedies proposed for the residual.
- **What was actually true**: the stored row had `error`, `venue_resolved_at` and `pre_resolution_error` all null. It was the WRITE-AHEAD version, not a `rejected` row with only its status flipped back.
  - `_persist` merges on a fresh read and then SETs, with nothing atomic between the two.
  - refresh-worker's paper SET at 18:27:25.228 was exactly its own 24.711 document + 48 B. It carried the row as it stood before live-odds-worker's `rejected` SET at 25.083.
  - The merge is last-writer-wins at ROW grain, so the error, the timestamps and the status reverted together. A predicate on `error` could never have reached the exact row it was meant to clear.
- **How we found out**:
  - Byte accounting of both services' `KEYVALUE_WRITE_LARGE` sizes over a 1.1-second window.
  - Then the stored row, off `/api/portfolio/live?on=2026-09-04&show=all`. Its `prior_attempts` also showed a build refused on every pass since 07:48Z.
  - `test_KNOWN_HAZARD_a_write_landing_between_merge_read_and_SET_is_lost` replays the interleaving on the real `_persist`.
- **The rule going forward**: before writing a rule that clears a row a lost update stranded, read the STORED row and list which fields survived.
  - Key only on evidence the lost write did not carry, or on a separate key no other writer touches.
  - If nothing survives, the fix is upstream: either do not write the row (`2914b6c7` builds before the write-ahead), or make the write atomic (`#656`).
  - A unit test cannot catch this. A fixture builds the row WITH the error, the predicate passes, and production never has that row.
- **Cost**: none paid; it was caught before shipping. It would have been a dead predicate on the money path that tested green and never fired.
## 2026-09-10 — OVERTURNED: `#600`'s three-way merge does NOT stop different orders clobbering each other, because its re-read and its SET are not atomic `[lane write-ahead-build-refusal, correcting state_model.md [execution-ledger-cross-service-race], 2026-08-28]`

- **What we believed**: since `f66c7441` (2026-08-28), `_persist` three-way merges onto a fresh read. So "different orders no longer clobber; the same order in one window is still last-writer-wins, blast radius one row". `LEDGER_MERGE` had not been seen firing.
- **What was actually true**: the fresh read and the SET are separate operations, ~0.3-0.5 s apart at 2.7 MB. A SET that lands between them is overwritten by the late writer's stale copy of every row it kept.
  - On 2026-09-04 that hit three different orders in 1.1 s:
    - paper `4aa69211…` lost its fill to live-odds-worker's SET at 24.160;
    - paper Q was dropped at 25.083;
    - live `6bc5617c…` was reverted to `submitted` by refresh-worker's SET at 25.228.
  - `LEDGER_MERGE concurrent=6/1/2` fired in those same seconds. The merge ran, and still lost the writes.
- **How we found out**:
  - Byte accounting of both services' `KEYVALUE_WRITE_LARGE` sizes, read as document versions.
  - The stored rows.
  - `test_KNOWN_HAZARD_a_write_landing_between_merge_read_and_SET_is_lost` replays it.
- **The rule going forward**: a merge-on-write protects a ledger only if the read it merges onto and the write are ONE atomic step, via compare-and-swap (WATCH/MULTI) or a lock. Otherwise it narrows the window without closing it, and the narrowed window is still hit.
  - Paper rows stuck at `submitted` count the hits: 13 across 09-06..09-11. That is an upper bound, since a crash mid-`place_order` leaves the same shape.
  - Fix: `todo.md #656`.
- **Cost**: six days with no live placement on either venue (09-04 to 09-10), plus paper fills silently lost.
## 2026-09-10 — FORBIDDEN: recording an ESPN refusal from Render as a property of the HOST. It is a (host, headers) pair: `site.api.espn.com` answered web 5 of 5 with urllib's default User-Agent, in the same hour it refused `has_games_for_date`'s `Syndicate-WNBA/1.0` `[lane wnba-public-scoreboard-host]`

- **What we believed**: `site.api.espn.com` returns 403 to every Render service, so any code on that host is dark in production. `state_basketball [espn-egress-and-wnba-boxscores]` said so on 2026-08-26: "The 403 is the HOST". I carried that into a trace and into a proposed fix for the live WNBA public scoreboard.
- **What was actually true**: `_public_scoreboard_live_state_payload` asks `site.api` with NO custom User-Agent. It ran 5 times on web on 2026-09-10 from 22:12:23Z with ZERO `SCOREBOARD_FETCH_FAILED`, a line it prints on any exception. The workers logged none that day either. In the same hour web's `has_games_for_date` (same host, `User-Agent: Syndicate-WNBA/1.0`) returned a non-False verdict. The 2026-08-05 probe in `wnba/cards.py` had already said this: a custom UA gets a 403 from Render, and the default answers.
- **How we found out**: the fix's lane recorded a falsification test (a failure-line count) BEFORE shipping. The zero was made readable by a positive marker that the call ran: the request-path warning `operation=wnba_public_scoreboard_live_state_fetch`, triggered by a request.
- **The rule going forward**: when an ESPN call fails from Render, vary the HEADERS before blaming the host, and record the refusal as the (host, User-Agent) pair that was measured. Never conclude "this host is dark" for a caller whose headers differ from the ones measured.
- **Cost**: an unneeded code change and deploy, caught before landing, and a state line that overstated the refusal for two weeks.
## 2026-09-10 — RECURRENCE (instrument blindness): I cited `last_blind_write None` as evidence about a ledger write. The field cannot be set in production `[lane write-ahead-build-refusal; found by lane execution-ledger-cas]`

- **What I believed**: `last_blind_write None` on `/api/ops/execution/ledger-summary` meant no blind write had happened. `state_model.md` called it "a meaningful null", and I quoted it in both the baseline and the verify of the `2914b6c7` deploy.
- **What was actually true**: the field is set only when `_load()` raises inside `_merge_onto_current`. `_load()` cannot raise: `refresh_state_store.read_json_file_result` catches every read failure on both backends and returns None, and `_load` turns that into an EMPTY ledger. The null is structural.
  - `test_an_unreadable_ledger_refuses_rather_than_looking_empty` passes only because it monkeypatches the reader to raise. That is a harness supplying a failure production cannot produce.
- **How we found out**: lane `execution-ledger-cas`, scoping `#656`, read the reader's exception handling. I confirmed both functions from code.
- **The rule going forward**: before citing a status field as evidence, find the code path that sets its UNHEALTHY value and confirm that path can execute in production. A field that can only ever read healthy is not an instrument. Same family as this file's instrument-blindness rules, and the 2026-09-09 FORBIDDEN on harness-supplied failure modes.
- **Cost**: two uninformative readings in a deploy entry, corrected the same evening. The entry's other readings stand.
## 2026-09-10 — OVERTURNED (my own docstring): a producer rewrite of a PAST-dated artifact does NOT reach web through the publish sweep. The sweep refuses slates more than a day old, and web serves whichever of its two copies is newer `[lane mlb-lens-final-status]`

- **What I believed**: the final pass rewrites live-odds-worker's copy of an old live-lens report, and `live_lens_loop`'s own publish sweep, which runs right after the tick, carries the rewrite to web "the same cycle". I wrote that into the module docstring and the lane, and pre-registered a reading on it.
- **What was actually true**: `artifact_publisher._publish_skip_reason` refuses any file whose NAME dates it more than `_PUBLISH_MAX_AGE_DAYS = 1` back, and the code calls that check "never exempted". Every sweep after the deploy logged `stale_slate=[..09_03, 09_01, 09_06..]`. The one date inside the window, 09-09, did reach web, and was undone within a second: web's `sources._resolve_data_path_with_reconcile` copies the NEWER of its two published forms over the served target, and the slim frozen form arrived 175 ms after the full final one.
- **How we found out**: the pre-registered reading. The producer's line said `finalized=6 still_open=0`, while web's copy of 09-03 still had `finalPass_entries=0`, and the publisher's own `SWEEP_SKIPPED_DETAIL` named the skipped files. The reconcile took three reads: web's `[ops.publish] ACCEPTED` lines (two publishes 175 ms apart), both web copies by export, and one more export after a cards read (8,736,835 B -> 132,548 B).
- **The rule going forward** (the same family as the 2026-09-10 RECURRENCE above, lanes mlb-final-state-mapping / mlb-lens-final-status): a fix is on the path to the surface only once the TRANSPORT and the READER have been read, not just the writer. For an artifact a worker writes and web serves, check two things before predicting "it reaches web". (1) The sweep's skip rules (`_publish_skip_reason`: age AND size) against the file's NAME and SIZE. (2) How web RESOLVES the path. If there is more than one published form and a reconcile, the newest copy wins, not the one you wrote.
- **Cost**: one live-odds-worker deploy whose reading could not move. A second change is now owed: a status-only patch of web's own served copy (`e035c829`), which must ship before the 10-day look-back loses 09-01.
## 2026-09-10 — RECURRENCE (the 09-09 absent-is-not-off rule): I read the env key a COMMENT named, got a 404, and nearly called another lane's pass inert on refresh-worker. The code reads a different key, and it is `true` there `[lane execution-ledger-cas]`

- **What I believed**: `e035c829`'s MLB web pass would be inert on refresh-worker. `run_refresh_worker.py:7223` says "LIVE_LENS_LOOP already defaults False", and a single-key read of `LIVE_LENS_LOOP` on refresh-worker returned HTTP 404.
- **What was actually true**: `live_lens_loop._is_live_lens_loop_enabled()` reads `SYNDICATE_ENABLE_LIVE_LENS_LOOP` (default False). That key is `true` on refresh-worker and live-odds-worker, and refresh-worker logged `TICK_COMPLETE results={'mlb': True, ...}` every cycle. A refresh-worker deploy would switch that lane's passes on there, on a service the lane never targeted.
- **How we found out**: before acting on the 404, I grepped the READER (`live_lens_loop.py:327`), then read that key per service, then read the tick lines.
- **The rule going forward**: the 09-09 rule says find the resolution site. What this adds: take the KEY NAME from the function that reads it, never from a comment or a docstring. A comment can name a key nothing reads, and a 404 on that key is an answer about nothing. Then confirm the behaviour from a line the reader itself emits.
- **Cost**: none paid. It was caught before the refresh-worker deploy, and the timing question went to the user, who chose to carry the passes.
## 2026-09-10 — OVERTURNED (mine): a finished game's rows are NOT served as `final` on the Layer 2 board. They leave through the unserved `dead` lane, so "served rows read `final`" is a check the board cannot produce `[lane football-layer2-live-parity]`

- **What I believed**:
  - After `42d49364` corrected FAMU @ MIA's 35 rows `pregame -> final`, `rows_stale_kickoff` fell 58 -> 0. I read that as the rows being "back on the board as final", told a peer so, and wrote it into a draft `deploys.md` entry.
  - My game watcher's BOARD_FINAL check (served rows with `game_state == final`) rested on the same belief.
- **What was actually true**: the served shortlist at 03:33:26Z had 0 rows for either finished game. `per_sport_ingest.<sport>.by_lane.dead` rose (ncaaf 173 -> 219, nfl 550 -> 577). Settled games are classed dead and not served. The counter fell because the rows now fail a DIFFERENT gate, not because they came back.
- **How we found out**: the watcher went silent after both ESPN finals. To explain it I compared the served rows' `game_state` with `game.state`, and there were no rows at all.
- **The rule going forward**:
  - A counter falling to 0 says the row left THAT filter, never that it was served.
  - To verify a final transition on Layer 2, read the enrichment coverage (`live_game_state.transitions`) and `by_lane.dead`, not the served rows.
  - Before trusting a watcher's terminal check, probe it on a game that already finished.
- **Cost**: one wrong claim to a peer (corrected within ~25 min, before its reading). The watcher could only end by being stopped.
## 2026-09-10 — FORBIDDEN: a repair guard that protects ANY POPULATED local copy, on a service that cannot produce the artifact itself. "Has rows" is not "is current", and nothing else will ever refresh it `[lane nfl-layer2-kalshi-identity]`

- **What was believed:** `scripts/build_nfl_prop_projections.py` held that "a local copy with rows is left alone no matter what web is serving". The rule was written after web's EMPTY 111-byte copy had been pulled over a good local one, and it was correct about that failure.
- **What was true:** refresh-worker cannot build this artifact, because it has no player pbp. So the copy it held from 2026-09-08 was never replaced. That copy had 980 rows, was generated at 20:17:22Z, and predates the `stat::player::line` key. The worker logged `REPAIR_SKIPPED_LOCAL_OK local_rows=980` every hour for two days while web served 1,140 rows. The NFL board's sim view survived only on Anytime TD, the one lineless market: 119 of 119 rows.
- **How it was found:** production's published artifact matched my local copy, while the board reported `artifact_rows 683`. The worker's own log line named the skip.
- **The rule:**
  - Gate a repair on the pulled copy's VINTAGE, not on the local copy's presence.
  - Keep a pull only if it is populated and not older by the artifact's own `generated_at`. Otherwise roll it back byte-for-byte, mtime included, so neither the next pull nor the publish sweep reads it as a fresh edit.
  - A guard written against one failure (empty over good) must not create the opposite one (stale forever). Test BOTH directions; `tests/test_nfl_props_prior_season_fallback.py` has five repair cases.
- **Measured after the fix:** `REPAIR_PULLED_NEWER 980 -> 1140` at 2026-09-11T03:50:19Z, then 486 non-Anytime-TD NFL props carried a sim view (was 0).
- **Generalises to:** any worker-side copy of an artifact that only another machine produces.
## 2026-09-10 — OVERTURNED (mine): "non-card NCAAF chips never get live state". The chip WAS on the live-state join; it read the UTC date, and ESPN files an evening-ET kickoff under the previous UTC day `[lane ncaaf-fcs-market-implied-rating]`

- **What I believed**: FAMU @ MIA's chip stayed `pregame` all game because only the FBS-vs-FBS week cards receive ESPN live state. I read "the cards have 49 games and FAMU @ MIA is not one of them" as the mechanism, wrote it into `deploys.md` (22:15 CT), a lane line and a lead, and told a peer.
- **What was actually true**: `build_ncaaf_chip_games` builds FBS-vs-FCS chips and calls `_attach_live_state` with the right ESPN ids (registry ids ARE ESPN ids: Florida A&M 50, Miami 2390). The index was built for `_ncaaf_week_kickoff_dates`, the UTC dates `2026-09-11/12/13`, and ESPN filed the 00:00Z kickoff under 09-10. It was the same UTC-vs-ESPN-date shape as `a9bafa9d` (settlement) and `86c82220` (board chips) that same day: the THIRD instance in one day.
- **How I found out**: before promoting the lead, I tested each input of the join in code. The ids came first, and disproved my first guess (a missing logo id). The date set came second, and confirmed the cause.
- **The rule going forward**:
  - Any NCAAF/NFL lookup into an ESPN capture must use `bet_status_nfl.kickoff_capture_dates` (the Eastern date, plus the previous day for a small-hours kickoff), never `commence_time[:10]` or `startDate.split("T")[0]`.
  - A row or card COUNT ("X is not among the 49") is not a mechanism. Trace the join's actual inputs before naming a structural boundary as the cause.
- **Cost**: one wrong mechanism in the ledger, a lead and a peer message, corrected about 30 min later (append-only). The fix was smaller than the wrong diagnosis implied: one call site. Also this session: a watcher reported a false "0 dates" because its filter matched `render_logs.py`'s own header line. I read the log directly before believing it.
## 2026-09-11 — OVERTURNED: "uncontracted rows crowd real Kalshi edges out of the plan's slots". The cut's own counters said neither the cap nor the ceiling bound `[lane kalshi-plan-placeable]`

- **What was believed:** `placeable_committed=4/22` meant 18 aggregator-priced NCAAF rows were holding slots that contracted Kalshi rows needed. The task was written on that premise, and it is the natural reading of the ratio.
- **What was true:**
  - On that build, `beyond_max_positions=1` and `slate_scale_factor=1.0` ($67.76 staked against a $251 ceiling). `prefer_placeable` has ranked contracted rows first since 2026-08-25, so the one row cut was an aggregator row. The 18 rows cost the 4 nothing.
  - There were 4 contracted rows only because the join never saw Saturday's rungs: `MAX_MARKETS_PER_SERIES=400` cut `KXNCAAFSPREAD` 2,141 of 2,541 before the join ran.
- **How it was found:** the PAPER2 line's own `refusals=`, and each position's `sizing.slate_scale_factor`. Both were read before any code, and both were already in fetched payloads.
- **The rule:**
  - Before fixing a crowding-out, read the constraint's own counter: `beyond_max_positions`, `slate_scale_factor`, `exposure_capped`. A wanted/total ratio is a symptom, not a mechanism.
  - A working-set histogram (`BY_GAME_DATE`, 6,000 markets) is not the join's population (`markets_from_state`, 14,818 markets). Read `PRECAP_SELECT` for what the join can see.
- **Also, tooling:**
  - PreToolUse hooks resolve `CLAUDE_PROJECT_DIR` to the PRIMARY tree, even in a `session_worktree` session. So lane-guard enforces the primary's STALE `lanes.md`. On 2026-09-11 it blocked two unclaimed files for a lane that was CLOSED on origin/main.
  - Check the claim on origin/main before believing a block. The remedy is `git restore --source=origin/main --worktree -- .syndicate/lanes.md` in the primary, with no local edits there and the index untouched. Never a bypass.
## 2026-09-11 — FORBIDDEN: reporting a lane's file claims as RELEASED on the strength of the edit you meant to make. Read the claim set back with `claims_by_path`, the same parser `lane-guard` enforces with `[lane nfl-layer2-kalshi-identity]`

- **What I believed:** my 2026-09-10 checkpoint rewrote this lane's block with a new header and a goal verdict. So I told the user the lane "no longer claims any files".
- **What was true:**
  - That edit's anchor was the header plus the `- Goal:` line. The old `- Files:` line, naming five code paths, sat below it untouched, so lane-guard kept enforcing those claims against every other session.
  - The next fix wrote `Files: NONE claimed ... verbatim in` a backticked `lanes_history.md`. The parser read that filename as a NEW claim.
- **How it was found:** I ran `claims_by_path(text)` over the file as written, filtered to this lane. It returned the five paths the first time and `{'lanes_history.md': ...}` the second. `check_lane_invariants.py` printed INVARIANTS HOLD both times, because a claim on a real path violates no invariant.
- **The rule:**
  - After any edit meant to release claims, run `claims_by_path` over the WRITTEN file, filter to your lane, and require NONE before saying so to anyone.
  - A `Files:` line that claims nothing must carry no backticked path-like token.
  - "Invariants hold" is not evidence that claims were released.
- **Cost:** one false statement to the user, corrected before it caused a blocked edit elsewhere, and three extra ledger commits.
## 2026-09-11 — OVERTURNED (a ledger state claim, by this session's measurement): "NCAAF serves ZERO orders by design" and "#593 can never be verified end-to-end" were both false by 2026-09-10 `[lane nfl-prop-grading]`

- **What the ledger said:**
  - `state_football.md [ncaaf-zero-orders-is-two-gates]` (verified 2026-09-01): NCAAF places 0 orders, because `pick_gate` and `portfolio_commit.py:267` hold by design.
  - Its state line said NCAAF settlement was "NEVER verified end-to-end".
  - Scheduled task `verify-ncaaf-settlement-593` was disabled with "Do NOT re-enable ... a Friday run was GUARANTEED to report PENDING".
- **What was actually true:**
  - Plan date 2026-09-10 held **517 distinct NCAAF orders on 72 games**, 211 of them in the portfolio book.
  - 20 FAMU @ MIA orders were graded end-to-end by `paper_settlement` on 2026-09-10, every outcome consistent with the score.
  - Some change after 09-01 let NCAAF orders through. No state line recorded it.
- **How we found out**: the first-grade reading counted orders per game in `/api/portfolio/paper` instead of assuming them.
- **The rule going forward:**
  - A state claim of the form "zero BY DESIGN" describes a configuration that other lanes can change without touching that section.
  - Before building on one, or before writing a task or a disable-note that assumes it, count it in production and date the count.
  - A lane that lifts such a gate owes the superseding line in the section that stated it.
- **Cost**: none paid this time. The reading counted before concluding. A reader trusting the section would have skipped NCAAF settlement verification entirely.
## 2026-09-11 — OVERTURNED: "pregame near-even Polymarket sides have no book, so hold them until live". Our own ledger held the rule's falsifier more than ten times before the rule shipped `[lane polymarket-e2e-review]`

- **What was believed:** 11 orders on 08-31 showed pregame orders above ~0.41 "resting" and never filling, while live everything filled. So a 0.35 pregame ceiling held near-even bets until live (`0c3f102f`, `97fe50b2`). The rule's own stated falsifier was "a PREGAME FILL above 0.410".
- **What was true:**
  - 24 of the 41 near-even pregame orders that reached the venue FILLED within about 2 s (08-28..09-01), including fills at 0.44–0.48 taken 31 to 821 minutes before kickoff. The other 17 were CANCELED by the venue 0.6–1.6 s after submit, and none of THOSE rested; what was read as "resting" was instant cancels.
  - **But resting does happen.** On 2026-09-11 two near-even pregame orders RESTED unfilled (`order_state_new`). A venue behavior seen in one window is not the venue's behavior, and a resting good-till-cancel order can fill in-play at a stale price. Orders now expire at kickoff (`16de339b`).
  - The deferral path failed. Of the 51 held bets whose games started, 36 were never placed, because the plan drops started games, and 4 became fills. Near-even bets placed in-play went 3-10 against 5.7 expected.
  - The venue's own book (`GET /v1/markets/{slug}/book`, signed) showed BAL–TOR pregame at 0.445/0.45, with 151,604 shares at the offer.
- **How it was found:**
  - `/api/portfolio/live?on=all&show=all&venue=polymarket`: `venue_status`, `submitted_at` and `venue_resolved_at` were already on every order.
  - A log join of every `HELD_PREGAME_NEAR_EVEN` line to later `LIVE_ORDER` lines.
- **The rule:**
  - Run a gate's stated falsifier against the population ALREADY in the ledger before the gate ships, not only going forward. A gate that suppresses its own falsifier can never see it later.
  - "Did not fill" has three readings: rested, canceled by the venue, or never sent. Read `venue_status` and the submit-to-resolve lag before calling an order resting.
  - A gate that DEFERS ("places once live") owns a measurement of whether the deferred path completes. Here 71% of deferrals never completed, and nothing counted them.
- **Also, tooling:**
  - The discard-guard hook resolves EVERY path named in a command containing `checkout --` against the PRIMARY tree. A worktree command that also ran `scripts\check_lane_invariants.py` was blocked for that second path. Run the discard as its own command.
  - `lane_claims` reads every backticked path in a `- Files:` line as a claim, including one inside a "NOT ..." clause. That made `check_lane_invariants` report a contested file. Name unclaimed files outside the Files line.
## 2026-09-11 — OVERTURNED (mine, same morning): I explained a falling ALL-TIME count as "the window moved" without reading how the count is taken. It was data loss `[lane nfl-prop-grading]`

- **What I believed**: `SETTLED_SAMPLE` nfl 12 -> 4 (mlb and wnba down too) meant a rolling window. I wrote that into `deploys.md` at 08:50 CT.
- **What was actually true**: the counter reads the whole execution ledger, and the ledger is at its 5,000-record cap. `TRIMMED dropped=1` fires on every write and evicts the oldest orders, which are the settled ones. Every stake's credibility input is shrinking.
- **How we found out**: the next session step read `_settled_sample_size_by_sport` -> `settled_decisions_by_sport` (whole ledger, all time). A count with no window cannot fall unless records leave, and `TRIMMED` showed them leaving.
- **The rule going forward**: before explaining a count that moved, read the function that takes it and name its UNIT and its WINDOW. A count documented as all-time that decreases is a data-loss alarm, never a window.
- **Cost**: one wrong line in `deploys.md`, corrected the same morning. The eviction itself had been running since at least 09-09 13:24Z, unremarked.
## 2026-09-11 — OVERTURNED (mine, same day) and REQUIRED: `claims_by_path` is NOT the matcher `lane-guard` enforces with, and a claim transfer is not in force until the PRIMARY tree's `lanes.md` says so `[lane ncaaf-tbd-kickoff-date]`

- **What it overturns:** my FORBIDDEN entry above ("reporting a lane's file claims as RELEASED on the strength of the edit you meant to make") tells you to read the claim set back with `claims_by_path`, "the same parser `lane-guard` enforces with". It is not the same. `lane-guard` matches every `_claims()` token against the target path by SUFFIX; `claims_by_path` indexes exact keys.
- **What happened:**
  - I landed `released:` markers for two files on `origin/main` (`22d7cbd6`), and lane-guard still BLOCKED my edits to both. It reads `$CLAUDE_PROJECT_DIR/.syndicate/lanes.md`, the primary checkout's copy, not `origin/main`.
  - That copy was 63 commits behind and held 188 lines of OTHER sessions' uncommitted edits, so overwriting it would have destroyed them. The three changes were mirrored into it surgically: one atomic read-modify-write, each anchor asserted to occur exactly once, CRLF preserved.
  - One line still blocked. Another lane's `Files:` continuation line read "... `ncaaf/sources.py` was `released:`.". Its bare token suffix-matched my file, and a `released:` in mid-line is not a disclaimer. My `claims_by_path` check printed NONE while the guard printed BLOCKED.
- **How to apply:**
  - After landing a claim change, mirror it into the primary copy, touching only its own lines.
  - Verify with the guard's `_claims()` plus a SUFFIX match against every target path.
  - Put `released:` at the START of a line, and keep path tokens out of prose inside a `Files:` block.
## 2026-09-11 — FORBIDDEN: predicting that legacy rows "expire at the date roll" without enumerating every shard the old writer touched. The board loop writes TOMORROW's shard too `[lane nfl-layer2-kalshi-identity]`

- **What I predicted:** `deploys.md` 2026-09-10 ~22:20 CT said the raw Kalshi rows leave "with the midnight CT date roll".
- **What happened:** the user reported the phantom "Matchup" card again on 09-11. Web's NFL 09-11 shard held 205 pre-deploy Kalshi rows, captured 09-10 20:35-23:31Z, because the intelligence loop also builds the NEXT day's board. The roll moved the residue forward a day instead of ending it.
- **The rule:** before saying "old rows expire at X", list every shard or date the old code wrote, from the rows' own `captured_at`. Then name the LAST date the residue can appear.
## 2026-09-11 — RECURRENCE (the 2026-09-10 "check EVERY site that WRITES that artifact" rule): the Kalshi per-series cap had TWO writers and a selection flag on ONE `[lane kalshi-precap-board-lines]`

- **What was believed:** the per-series cap was refresh-worker's. `SYNDICATE_KALSHI_PRECAP_DATE_AWARE` and every `PRECAP_SELECT` reading quoted in the lanes and in todo `#661` came from refresh-worker's logs.
- **What was measured:** live-odds-worker runs the SAME `run_kalshi_odds_refresh` every ~2 min, at `PRECAP_SELECT mode=arrival` (14:49:52Z, 2026-09-11). It writes the SAME `kalshi_markets.json` working set that `portfolio_commit` and the executor read (`markets_from_state`). The date-aware flag was never set there, so once it shipped, roughly every other write of the working set was the old arbitrary slice.
- **The rule going forward:** before calling a selection or cap rule ON, grep EVERY service's logs for the rule's own line (`PRECAP_SELECT mode=`), not only the service you deployed. A shared keyvalue artifact is written by whichever service runs the writer, and loop ownership moves with env.
## 2026-09-11 — FORBIDDEN: passing a live commit remembered from an earlier read to `deploy_preflight.py --target-commit ... --reinject-env`. Its "ALREADY LIVE" is ANCESTRY, and `--reinject-env` turns that into a CLEAR for a ROLLBACK `[lane kalshi-precap-board-lines]`

- **What happened:** live-odds-worker's live commit moved `1afec00f` -> `16de339b` between my reads (another lane's deploy, 16:53:31Z). Preflight for `--target-commit 1afec00f --reinject-env` printed `live commit 16de339b`, then `target commit 1afec00f ALREADY LIVE -- redundant`, then `CLEAR` (16:59Z). Deploying it would have rolled back `16de339b`'s change.
- **Why:** `deploy_preflight.py:792-796` sets `target_already_live = is_ancestor(target, live)`, and lines 806-808 waive that redundancy under `--reinject-env`. An ancestor is "already live" by containment, so a rollback target reads as the same-commit case the flag exists for. `render_deploy.py`'s descendant check is the only remaining guard, and it was not exercised here.
- **The rule:** for `--reinject-env`, use the `live commit` printed by THAT preflight run as the target, and require target == live, not merely contained. Caught here only by reading the `live commit` line on the same output.
## 2026-09-11 — OVERTURNED (mine): I offered the user an option saying withheld rows would "still be recorded, so skill can be measured" before checking who consumes the filtered artifact `[lane pricing-plane-v1]`

- **What I believed**: withholding rows from the shortlist changes only the display, and measurement continues.
- **What was actually true**: `portfolio_commit` sizes from the persisted shortlist (`read_layer2_shortlist`). Withholding a row also stops its paper orders, and those orders were the only order-based route to measuring those models.
- **How we found out**: tracing the shortlist's consumers while implementing, after the user had already chosen.
- **The rule going forward**: before describing a filter's side effects to the user, trace every consumer of the artifact it filters. The Layer 2 board is also the portfolio's input. State the consequence IN the question, not after the answer.
- **Cost**: small. The consequence was surfaced before the deploy and recorded as a lead, and the decision stood.
## 2026-09-11 — RECURRENCE (a stale ledger number read as a live constraint): I quoted a 16-day-old cap from `state.md` as the binding limit and planned around it `[lane kalshi-precap-board-lines]`

- **What I said:** the 09-11 Kalshi spend of $30.07 left "~$20 of room" under a "$50/day cap". The cap came from `state.md`'s 2026-08-25 caps line; `EXECUTED` prints `spent=` but no cap.
- **What happened:** the next pass spent to $58.84 and was bound by the ORDER count: `refused={'over_max_day_orders': 14}`.
- **The rule:** a cap quoted as binding must come from the running service's env, or from its own refusal counter, never from a dated ledger line. The executor's `refused=` dict names the cap that actually bound.
## 2026-09-11 — OVERTURNED: the 2026-08-01 same-surname guard ("Yordan", not "Jose", Alvarez) could never fire for a player who goes by initials, because it took first names from the SCORER's filtered tokens `[lane ask-rail-evidence]`

- **What was believed:** `_person_conflicts_with_question_name` downgrades a bare-surname match whenever the question pairs that surname with a different first name.
- **What was measured:** production served "Last 10 games — AJ Griffin (through 2024-04-17)" for "What's the case for and against Konnor Griffin?". The guard reused `_person_matches`' token list, which drops every token under 3 letters. "AJ Griffin" reduced to `["griffin"]`, the guard's `len(parts) < 2` early return fired, and with no first name to compare, the match was allowed.
- **The rule going forward:** a guard must not inherit the normalisation of the thing it guards. A filter that is right for SCORING (ignore short tokens) removed exactly the tokens the GUARD needed, and the failure was silent and in the permissive direction. Test a disambiguation guard on the short and initial forms (`AJ`, `A.J.`, `N.`) in both directions: the conflict must fire, and a question that names the initials player must still match.
## 2026-09-11 — FORBIDDEN: running a ledger script by ABSOLUTE PATH from a shell whose cwd is another checkout. `build_learnings_index.py` resolves `.syndicate/...` against the CWD, not its own checkout, so the worktree's copy rewrote the PRIMARY tree's `learnings_index.md` `[lane ask-rail-evidence]`

- **What happened:** `py -3 /c/tmp/syndicate-sessions/ask-rail-evidence/scripts/build_learnings_index.py`, run from a Bash whose cwd had reset to the primary tree, printed "index written: 965 rules" and changed nothing in the worktree. It wrote the SHARED tree's `.syndicate/learnings_index.md` (mtime 18:16:08Z) from that tree's stale `learnings.md`. `INDEX_PATH = ".syndicate/learnings_index.md"` (line 28) and the `learnings.md` rewrite (line 199) are both cwd-relative.
- **How it was caught:** the printed count (965) disagreed with the worktree index's own header (981), and the worktree's diff for the file was empty.
- **The rule:** run ledger scripts with the cwd set to the tree you mean (`(cd <worktree> && py -3 scripts/...)`), and afterwards read `git status` in BOTH trees. A script run by absolute path is not scoped to the checkout it came from. This is the other side of the 2026-09-10 `REPO_ROOT` rule: there the path came from `__file__`, here from the cwd.
## 2026-09-12 FORBIDDEN: measuring model quality on a population defined by a PUBLICATION filter. When publishing is switched off the metric does not go noisy, it goes SILENT — and a pool FREEZES rather than shrinking `[lane live-gameline-accuracy-cut-repoint]`

The MLB live-gameline accuracy task headlined the `priceable_only` cut for
months. `priceable` is a verdict about whether the board will PUBLISH an edge:
it folds in `prob_interval_swamps_edge`, `no_two_sided_market_price`, and —
from 2026-09-10 — `model_edge_publishing_disabled_for_sport`. None of those are
statements about whether a forecast can be scored.

When MLB edge publishing was switched off, the cut went to n=0 permanently.
Measured on the per-record ledger: 2026-09-11 has 13,187 records with
`priceable=True` on **zero** and that reason on 245, while 2026-09-09 has 41
priceable and the reason absent. The forecasts were still being recorded the
whole time.

**The failure mode is the part worth keeping.** `best_per_date` SKIPS a date
whose cut carries no brier, so the pooled total did not fall — it stayed at
"12 dates, 146 games", unchanged and unmarked, and would have re-printed that
same number every night forever while new dates vanished. A metric that dies
by *freezing* looks exactly like a metric that is stable. **A shrinking sample
is visible; a frozen one is not.** Any pooled statistic that drops
non-conforming rows needs a counter for what it dropped, and must fail loudly
when the newest period contributes nothing.

**How to apply:** condition on properties of the FORECAST and the OUTCOME
(quote age, market, segment, whether a final exists), never on whether the
product chose to act on it. Selection on a publication decision is selection on
the model's own confidence, which biases the comparison even while it is
populated. `fresh_quotes_only` was the right headline all along for an
independent reason: `learnings.md:854` already FORBADE comparing model against
market without conditioning on quote age, and `priceable_only` never did.
## 2026-09-12 FORBIDDEN: writing an instruction that asks for a reading without naming the instrument, when a known-broken instrument is the obvious one to reach for `[lane live-gameline-accuracy-cut-repoint]`

`learnings.md:1584` has said since 2026-09-03 that Git Bash `date` in this repo
is badly skewed. The scheduled task's step 3 nonetheless said *"state your
actual wall-clock run time"* and named no tool. I reached for `date`, got
`Fri Sep 11 23:34:45 CDT` against a true local time of `2026-09-12 11:52`, and
published that the run was **ON TIME**. It was standby-displaced by ~12 hours —
the exact failure the task file documents at length as happening on 6 of 10
nights.

**The skew runs in the flattering direction**, which is what made it stick: a
displaced run reads as punctual, so the one instruction designed to catch
displacement instead certified its absence.

**How to apply:** a rule that forbids a tool is only half a rule. Name the
replacement AT THE POINT OF USE, in the file that asks for the reading — not
only in the ledger that forbids it, which the actor may never open. Better
still, add a check that needs no instrument: here, *if the served date is
tomorrow relative to the slate you meant to capture, the run was displaced
regardless of what any clock says.* Both were added to the task file.
## 2026-09-12 FORBIDDEN: quoting a tool's aggregate without recomputing it once from the components the tool printed beside it `[lane gameline-trend-paired-pool]`

`pool_live_gameline_trend.py` printed, per date, `model`, `market` and `diff` —
where `diff` was the row's own PAIRED `model_minus_market_brier` and `model` was
the model's brier over ALL its rows — then pooled from `model` and `market`. On
2026-09-01 the one line read model 0.13160, market 0.13198 (a difference of
-0.00038) and diff **+0.00077**. Visibly inconsistent, on the same line.

I ran that output at least three times in one session, repointed a scheduled
task's headline at it, published **+0.00571** to `state.md` and the task file,
and checkpointed — without once checking `model - market` against `diff`. The
paired figure is **+0.00460**. The discriminating field (`model_paired`) was in
every row since scorer contract 2, and the scorer's own `_paired` docstring
names this exact failure ("THE DIFFERENCE MUST NOT USE `model`").

**Why it survived:** the old headline cut (`priceable_only`) always had
matched n, so the defect produced no visible symptom for two weeks. Switching
the headline to `fresh_quotes_only` made it live, and the switch was the moment
nobody re-audited the tool against the new cut.

**How to apply:**
- When a table prints components and an aggregate, recompute the aggregate from
  the printed components once before quoting it. When a row prints two terms
  and their difference, check term - term = difference. A disagreement beyond
  rounding is a bug in the tool, not noise.
- When a cut, a population or a field becomes the HEADLINE, re-audit the tool
  that computes it against that cut specifically. A defect latent under the old
  headline goes live the moment you switch.
## 2026-09-12 FORBIDDEN: grading in-play price movement on the markets that are still there `[lane layer2-live-scorecard-gate]`

Grading live NCAAF Layer 2 opportunities by re-pricing the SAME market 10 minutes
later: 65 live +EV first sightings, 48 re-checkable, and **32 of those 48 (67%) had
vanished** -- mostly because the line moved, which is exactly what a stale price being
picked off looks like. Pregame, 13 of 258 (5%) vanished. The survivors' median then
said the rows a staleness gate would REMOVE held +1.85 EV points and the rows it would
keep held +0.68 -- the opposite of the mechanism, measured only on the markets that
did not move.

Before printing denominators I also quoted a mean split in chat ("<5m held +2.11,
10m+ fell to -11.28"). It rested on n=3 vs n=13 and three William Hill rows at median
-69, and was retracted within the hour.

The same session's first scorecard joined **0 of 932** opportunities while two games
were final, and printed it as `no_final_score`: run from a session worktree, the NCAAF
team alias registry under `data/` did not exist, so feed names never met scoreboard
names.

**How to apply:**
- Print the vanish rate beside any in-play re-price metric, per cell, and never read
  survivors' movement as "the edge held". Settle against results, or price the moved
  line; do not drop it.
- Print n beside every mean, and a median beside any mean a few rows can swing.
- A join that can fail must name its failure (`no_chip_match`), and a known-final game
  must be shown to join before any result from it is read.
## 2026-09-12 RULE: from a session WORKTREE, the deploy locks live in the PRIMARY tree. The lane marker must be written THERE, and a claim is released with its TOKEN. `[lane nfl-prop-certainty-refusal]`

**What I believed.** `/lane open` step 6 ("Write the slug to `.syndicate/.current-lane.<id>`")
was enough for `deploy-guard.py`, and `deploy_claim.py release --service <svc>` would release my
own claim.

**What happened.** I did step 6 inside `C:/tmp/syndicate-sessions/<lane>`, as the worktree protocol
directs. I then held the claim and a CLEAR preflight for the exact SHA, and the guard still refused
the deploy with `your lane: <none>`. The hook resolves its root to the PRIMARY tree and reads the
marker there. `deploy_claim.py` says so in its own banner ("claims live in the MAIN tree"); the
lane marker has no such banner. After deploying, `release --service web` returned
`REFUSED ... the token does not match`, and it succeeded only with `--token` set to the value
printed at `acquire`.

**Also measured.**
- The guard has NO override for a preflight HOLD. The only way past a user-approved HOLD is
  `.syndicate/deploy/grants/<session_id>.json`.
- `_grant()` checks `expires_epoch` ONLY, not `service`. A grant therefore opens EVERY service for
  this session until it expires.

**How to apply.**
- In a worktree, write `.current-lane.<session id>` in BOTH trees before any deploy.
- Record the `acquire` token and pass it to `release`.
- If a HOLD is overridden by the user, write the grant with a minutes-scale expiry immediately before
  the trigger. Delete it in the same command, and log it in `deploys.md`.
- *(evidence in `.syndicate/log/2026-09-12.md`, section "Deploy of `77f8d890`")*
## 2026-09-12 FORBIDDEN: reporting "the code has no X" from a search whose pattern was never shown to match anything `[lane layer2-live-scorecard-gate]`

A Grep over `syndicate` with the glob `{templates/**/*.html,static/**/*.js}` returned "No files found" for `quote_seen_age|book_age|written_at|...`. I told the user the board's templates and JS read no age field at all. That was false: the same tokens with single-extension globs found 25 matches in `intelligence.html` alone, including the card's existing `renderFreshness` book-age strip. A second query with the same brace glob also returned zero. The glob, not the code, was empty.

This is the search-tool twin of the 2026-09-02 rule about filters that have never been shown to match.

**How to apply:** before stating an absence, run the same search for a token you KNOW is there, with the same path and glob. A zero on that control means the search is broken, not the code.
## 2026-09-12 FORBIDDEN: calling a production endpoint "small" without checking its size first `[lane layer2-live-scorecard-gate]`

Mid-slate, with the user betting off the web service, I fetched `/api/intelligence/status` as a "small" endpoint to read freshness fields. It returned 87,903,243 B, the whole state payload. Its neighbour `POST /api/intelligence/query` was already measured at ~67 MB (`#632`), and the route was one grep away.

**How to apply:** read the route, or use a size-first form (`names_only`, a limit, a HEAD), before fetching from a live service, and pick the narrowest endpoint that carries the field.
## 2026-09-12 FORBIDDEN: alerting on a projection from ONE interval's rate, or applying a correction factor to readings already taken after the change `[lane layer2-live-scorecard-gate]`

A watcher on the 09-12 opening ledger projected its 05:00Z close from the latest single poll interval, times 1.117 for the four new per-record fields. At 00:48:53Z it fired `ALERT_PROJECTION_OVER_95PCT 97.4%` off one 11-minute interval growing at 2.25 MB/h. The same log showed intervals as low as 0.29 MB/h, and the 20:12->00:44Z average was 0.78 MB/h, which projects ~75%. The 1.117 was also double-counted: every reading after the 20:20Z deploy already included the new fields. Reaching the tripwire needed a sustained 2.73 MB/h. The rearmed rolling-60-minute watcher then read 770,795 -> 296,075 B/h, projecting ~71%.

**How to apply:**
- Project from a rolling window (an hour here) with a minimum span, never from the newest single interval, and state which window the alert used.
- Apply an adjustment for a change only to readings taken BEFORE it; after the change, the readings already contain it.
## 2026-09-12 RULE: a kill census's START DATE is a claim about ONSET, and a stage sampler on ONE thread is blind to a spike on ANOTHER. `[lane live-odds-worker-oom]`

**What I believed.** Kills began 13 min after the 09-11 18:03Z deploy of `21c26db1`, and the preceding 10.5 h `3bafdd2b` lifetime (0 kills) was a clean baseline. I pre-registered H1 on that commit range.

**What was true.** I had read `render_events` from 09-10, a start I chose. A peer read from 09-07 and found the onset at 09-09T19:43Z. The "clean" stretch was quiet partly because 09-11 carried a deploy roughly every hour, each resetting memory. Separately, my `ALL_PROCESS_MEMORY` stage samples went silent 40-66 s before every kill. They are emitted by the live-lens thread, and the spike was on the venue-poll thread (the Kalshi daily-book write), which those samples never cover. 7 of 7 kills sat in that other thread's window.

**How to apply.**
- Before naming an onset or a baseline, widen the events window until kills stop appearing, and write the read's start next to the claim.
- Discount any "quiet" interval that contains deploys: every deploy reboots, and memory is boot-confounded.
- When a per-stage sampler shows nothing in the last N seconds before a kill, list the OTHER threads that run in that window before reading the silence as "nothing happened". Log timing against their own markers (here `TRIM_SELECT`/`DAILY_BOOK`).
- *(evidence in `.syndicate/log/2026-09-12.md`, section "live-odds-worker OOM")*
## 2026-09-13 FORBIDDEN: using the wall time between two log lines as the COST of the code between them when another thread shares the GIL. And a preflight CLEAR on a slate night may be a post-kill restart, not a quiet worker. `[lane live-odds-worker-oom-loop]`

**What I believed.**
- I pre-registered R1: if the streaming daily-book writer runs, `TRIM_SELECT`->`DAILY_BOOK` drops to a p50 of <= 24 s (the 58736a69 baseline was 36.0 s). The only code between those two lines is the book write, and the new writer was ~3x faster locally.
- Separately, I read the deploy preflight's `CLEAR: only infrastructure processes running` as the worker being between sweeps.

**What was true.**
- **R1:** the first 12 paired ticks gave p50 31.1 s, neither met nor falsified. The slowest ticks carried the FEWEST appended points (82.8 s / 1,398 and 97.8 s / 1,404), interleaved with 9-11 s ticks. The venue-poll thread shares the interpreter with the live-lens thread's Monte Carlo builds, so its wall time measured contention as much as work. A reachability test that cannot read healthy when the code runs is instrument blindness.
- **CLEAR:** the worker had been oomKilled at 00:07:50Z and restarted at 00:07:51Z. The CLEAR at 00:09:13Z was a fresh process, 83 s old. Separately, I told the user "no kills to the deploy" from event reads that ended at 00:00:32Z and ~00:02Z; that kill landed 5-7 min after them.

**How to apply.**
- To prove a code path ran, emit a line FROM that path (a counter or a stamp), or measure a property only it can change. Never use the gap between two neighbouring log lines on a multi-threaded process.
- If you pre-register a duration anyway, first show over the baseline that it tracks the work, e.g. correlate it with `appended` before trusting it.
- When a preflight on a live-slate night returns CLEAR, read `render_events` up to that minute before calling the worker quiet. A post-kill restart reads identically.
- Any "0 kills up to event X" must come from a read whose window reaches X.
- *(evidence in `.syndicate/deploys.md` 2026-09-13 00:14:31Z and 01:14Z, and `.syndicate/log/2026-09-12.md`)*
## 2026-09-13 FORBIDDEN: grading "still there N minutes later" from a poller without checking that the later poll read a NEWER build `[lane layer2-live-scorecard-gate]`

A session capture polled `/api/board/layer2-shortlist` every 2 min and graded the vanish rate as "a poll at least 10 min later still carries the market". Two things made later polls re-read the build the market was sighted in:
- Build gaps of up to 1,601s during the slate.
- The 09-12 shortlist stopped rebuilding at 04:58:55Z (the Central date roll), leaving 2 h of polls on one build.

A re-read of one build reports every market as still there. On the same final capture (80 builds), skipping same-build polls moved live vanish from 400 of 663 (60%) to 426 of 648 (66%). Rows served 5-10 min old moved from 56% to 69%, and the first gate window from 56% to 78%. The obvious alternative, "a build at least 10 min newer", read 77% because it also lengthened every row's horizon.

**How to apply:**
- Measure persistence against a NEWER artifact (its `written_at`), not a later poll. A re-read of the same artifact is "no new look", never "still there".
- When fixing such a rule, change only the defective case and report both readings. A fix that also moves the horizon changes the thing it is correcting.
- Judge presence AT the check point, never "did it ever leave before it". A replay of the worker's departure log over the same 80 builds wrote 1,109 returns against 2,245 departures, and an "ever left" join called 108 live sightings gone that were back by the deciding build.
## 2026-09-13 An approval covers a SHIP LIST, not "main": when main moves between the answer and the deploy, re-ask or deploy the approved SHA `[lane layer2-live-scorecard-gate]`

This refines the 2026-09-07 corollary above ("re-resolve the world before acting"; roll forward from `main`).

The user approved "Deploy both now" against a named ship list: web would carry this lane's allowlist line plus six named files from other lanes, and refresh-worker would carry this lane's four files. Between that answer and the web claim, origin/main moved to `3e18be8e`, another lane's refresh-worker disk COMPACTION, which deletes and gzips files. Re-resolving showed web growing from 10 to 12 code paths and refresh-worker from 4 to 7. Rolling forward to "main" would have shipped a destructive, unmeasured change under an approval that never covered it.

Re-resolving also showed refresh-worker already live on `3e18be8e`, which contains this lane's commit. No refresh-worker deploy was needed, and deploying the approved (older) SHA there would have reverted the compaction.

**How to apply:**
- Immediately before preflight, re-run `git diff --stat <live>..<target>` for every service you deploy. If the ship list grew past what was approved, either re-ask or deploy the approved SHA (it must still be on origin/main), and say which in `deploys.md`.
- Never deploy a SHA OLDER than what a service already runs. Read each service's live commit first: a peer's newer deploy may already carry yours.
## 2026-09-13 FORBIDDEN: gating a ledger commit on a PowerShell function's return value without `@()` at the call site. A single match unrolls to a bare string, so `.Count` reads 1 and `[0]` is its FIRST CHARACTER. `[lane live-odds-worker-oom-loop]`

**What I believed.** A deleted-lines gate was sound as written:

```
$d = Get-DeletedLines 'x'
$d.Count -eq 1 -and $d[0] -like '...'
```

It was meant to confirm that a commit removed exactly the one line I had edited.

**What was true.**
- The gate refused two correct commits in a row. PowerShell unrolls a one-element pipeline result, so `$d` was a string: `.Count` was 1 and `$d[0]` was `-`.
- The only visible symptom was `[System.Char] does not contain a method named 'Contains'`, and that appeared only once I split the conditions apart.
- It failed CLOSED, which is the safe direction. But a gate that cannot pass on correct input teaches people to override it.
- Separately, the harness refused a helper named `Del` as `Remove-Item` (its alias) before anything ran.

**How to apply.**
- Write `$d = @(Get-DeletedLines ...)` at EVERY call site, and cast each element with `[string]` before calling string methods.
- Print each gate condition on its own line before AND-ing them. A combined `False` names no culprit.
- Never name a helper after a PowerShell alias: `del`, `rm`, `ri`, `sl`, `gc`, `cat`, `ls`, `echo`.
- After `session_worktree.py land`, check `rebase-merge` is absent BEFORE testing `merge-base --is-ancestor HEAD origin/main`. During a paused rebase HEAD is upstream, so that test passes trivially.
- *(evidence in `.syndicate/log/2026-09-13.md`, section "live-odds-worker-oom-loop — session 791399da — ~1:25 PM CT")*
## 2026-09-13 — RECURRENCE (the 2026-09-11 REQUIRED rule that a claim transfer is not in force until the PRIMARY `lanes.md` says so): I released a claim in my worktree, read it back as free, and both code edits were BLOCKED `[lane layer2-prior-date-live-carryover]`

- **What I did:** I released `football-layer2-live-parity`'s claim on `pipeline/intelligence_state.py` in the WORKTREE copy of `lanes.md`, confirmed with `claims_by_path` that only my lane held it, and started editing.
- **What happened:** `lane-guard` read `$CLAUDE_PROJECT_DIR/.syndicate/lanes.md`. That is the PRIMARY tree: 163 commits behind origin/main, carrying +205/-55 uncommitted edits from other sessions.
  - My release did not exist there.
  - `ncaaf-window-reason`, CLOSED on origin/main since 09-11, still read OPEN there and held `pipeline/layer2_shortlist.py`.
  - Both edits blocked. Getting past them cost a user override question.
- **The rule going forward:**
  - Mirror a claim change into the primary copy BEFORE the first edit: anchors asserted exactly once, CRLF preserved.
  - Check the result with the guard's own `_claims()` plus a suffix `matches()` against the primary file.
  - Also look there for claims that origin/main has already CLOSED. They block exactly like live ones.
## 2026-09-13 — OVERTURNED: the Layer 2 fast path is NOT a 14-27 s stage. It measured 133-182 s per build on refresh-worker, and the docstring figure had sized my plan `[lane layer2-prior-date-live-carryover]`

- **What was believed:** `_refresh_layer2_shortlist_only`'s docstring (2026-08-14) says "the shortlist stage measured 14-27s". It uses that figure to call a 300 s rate limit a ~8% duty cycle. I carried the figure into the carryover's cost estimate.
- **What was measured:** refresh-worker, `LAYER2_FAST_REFRESH date=2026-09-12`, 2026-09-13 04:34:59-04:58:57Z: `elapsed_s` 176.89, 182.04, 133.53, 166.74 and 164.11. Against builds ~5-7 min apart, that is roughly half the loop's time, not 8%.
- **How to apply:** before sizing periodic worker work off a stage's cost, read that stage's own elapsed line from production logs for a comparable slate. A cost quoted in a comment is a dated measurement taken on a different board size. The carryover's cost is restated in its lane and in `state_layer2.md [layer2-prior-date-carryover]`.
## 2026-09-13 — OVERTURNED: "a 304 from /api/ops/artifacts/stream means refresh-worker's copy is current" is FALSE for append-only tails, and "ODDS_SWEEP_LAUNCHED means the sweep ran" is FALSE. Together they took NFL off the Sunday board `[lane refresh-worker-disk-inventory]`

- **Belief 1 (the puller's own comment): a 304 is the cheap steady state.**
  - `pull_streamed_artifact` sent `since=<local mtime>` AND `Range: bytes=<local size>-`. The route answers 304 on `st_mtime <= since` BEFORE it reads Range.
  - Measured: refresh-worker's `nfl_source/tracking/book_quotes/2026-09-13.jsonl` sat at 19,914,752 B (books from 09-12 08:02Z) while web held 28,757,424 B (13:40Z).
  - Probes with Range from 19,914,752: `since` older than web -> 206 (8.8 MB); `since` >= web -> 304.
  - The served board had 0 NFL rows for today. Fixed in `48c1fc61`.
- **Belief 2: `ODDS_SWEEP_LAUNCHED ... sports=mlb,nfl,soccer` at 15:48:15Z meant NFL was swept.** It was refused 32 s later: `A refresh run is already active (pid=17018)`. The per-sport marker had already been stamped (`#25`), so NFL's next sweep moved past kickoff.
- **How to apply:**
  - A silent success path (304/416) needs its own "current since when" reading, not an inferred one.
  - For append-only files the byte offset is the watermark; a clock is a second, conflicting one.
  - Grade a launch by what LANDED (web shard mtime and size, `ODDS_SWEEP_OUTCOME`), never by the launch line.
  - When a board sport looks stale, compare web's shard (ops stream probe: `X-Artifact-Mtime`/`X-Artifact-Size`) against the reader's copy BEFORE diagnosing capture.
  - *(evidence: `deploys.md` 2026-09-13 15:43:33Z and 16:09-18:02Z)*
## 2026-09-13 — OVERTURNED: "gzip magic + a trailer ISIZE bigger than the compressed size proves a `.gz` is complete" is FALSE `[lane book-quotes-prefer-fuller-copy]`

- **What I believed:** a `.gz` that starts with `1f 8b` and whose last 4 bytes (ISIZE) are >= its on-disk size is trustworthy enough to prefer over a plain copy.
- **What falsified it:** `test_a_truncated_gz_never_wins` (write a 500-row `.gz`, cut it in half) resolved to the truncated `.gz`. A stream cut mid-way keeps its header, and its "trailer" is 4 arbitrary bytes of compressed data, which easily read as a large ISIZE.
- **How to apply:**
  - The gzip trailer is an estimate, not proof of completeness. That is fine for a memory guard that over-estimates (`book_quotes_logical_bytes`), and wrong for a decision about WHICH file readers get.
  - To prefer a `.gz`, inflate it to the end once (EOFError/CRC failure = incomplete) and cache by (path, size, mtime).
  - Write the truncation test BEFORE trusting a cheap check. Here it was the only thing that caught this.
  - *(evidence: `log/2026-09-13.md`, section "lane `book-quotes-prefer-fuller-copy` — checkpoint")*
## 2026-09-13 — OVERTURNED: "the OddsAPI live endpoint can only ever serve upcoming events" is FALSE, and a fetcher filtered on it for a whole season `[lane nfl-live-props-missing]`

- **What was believed:** the NFL props fetcher's `events_in_scope` docstring said the endpoint serves only upcoming events, and the code dropped every event with `commence_time < now`. So no prop was ever requested for a game in progress. The board showed 0 live NFL props all afternoon, and every live prop died in the opportunity gate as `live_market_stale`.
- **What falsified it:** a probe at 2026-09-13T22:26Z. `/events` listed the 4 games in progress (and not the finished ones). Each game's `/events/{id}/odds` returned props from 6 books with 25 of 25 markets updated after kickoff. The OddsAPI v4 guide says `/events` returns "in-play and pre-match events".
- **How to apply:**
  - A filter justified by a claim about an external API is a belief until probed. One call costs credits in single digits; a season of missing in-play markets does not.
  - When one sport's live markets work and another's do not, diff the EVENT SELECTION first. MLB selects by slate date (`fetch_mlb_oddsapi_local.py:772`); NFL and NCAAF selected by `commence_time >= now`.
  - Instrument corollary from the same lane: `[live_refresh_loop] ODDS_SWEEP_LAUNCHED` is printed BEFORE `launch_refresh_run` (`live_refresh_loop.py:5741` vs `:5767`). It fires for launches then refused with `A refresh run is already active`. Count runs from the refresh run itself, never from that line.
  - *(evidence: `log/2026-09-13.md`, section "lane `nfl-live-props-missing` — checkpoint")*
## 2026-09-13 — OVERTURNED: "the fast path keeps the board fresh, so nothing is lost when the heavy build is refused" `[lane kalshi-nfl-quote-gap]`

- **What was believed:** `_refresh_layer2_shortlist_only` exists so the board survives `MEMORY_GUARD_ABORT stage=pre_source_state_fingerprint`. Its docstring frames the refusal as "the expensive path stays refused exactly as often as before; this only stops the cheap path being refused WITH it", as if the heavy path's only product were the board.
- **What falsified it:**
  - 403 refusals, 09-12 21:34Z..09-13 16:14Z. The board rebuilt 13-51 times an hour.
  - But every side effect that lived ONLY in the heavy build stopped for ~16 h: Kalshi quote capture for all sports (`QUOTE_CAPTURE` 0), `PORTFOLIO_COMMIT` (paper orders) 0, `CANDIDATE_POOL` and `BOARD_PUBLICATION` 0.
  - Nothing reported that as a failure. A fresh board looked like health.
- **How to apply:**
  - When a cheap path replaces an expensive one under a guard, list EVERYTHING the expensive path does besides its headline output: joins, captures, commits, publications. Decide for each whether it moves, or name it as dropped.
  - Grade a refused-build stretch by the side effects' own log lines (`QUOTE_CAPTURE`, `PORTFOLIO_COMMIT`), never by board freshness.
  - Tooling corollary: `git merge-file` between a working copy and a `git show` blob can report the whole file as one conflict when their line endings differ. Fast-forward and re-apply the edit instead of trusting that conflict.
  - *(evidence: `log/2026-09-13.md`, section "lanes `kalshi-nfl-quote-gap`, `heavy-build-memory-refusal` — checkpoint")*
## 2026-09-13 — OVERTURNED: "a served board showing the rows = the fix is verified" — ONE build is a sample of a process that FLAPS `[lanes nfl-live-props-missing, quote-state-publish-retry]`

- **What I believed:** Layer 2 NFL `written_at` 22:44:36Z served 278 live props (0 before the capture fix), so I recorded "verify MET", released the deploy claim and closed the lane.
- **What falsified it:** the next builds read 0 (22:49:15Z), 216 (23:05:18Z), then 0 (23:09:02Z). Capture was fixed. The in-play gate still depended on a last-seen clock that went stale whenever web answered a quote-state publish with 503 at merge capacity. My own watcher's stop condition had broken out after the FIRST build.
- **Also overturned in the same hour:** "the 503 on the state sidecar is transient and heals" (I wrote it after one repaired publish). It heals by the NEXT sweep, and 2-8 minutes of lag is exactly longer than the 300 s in-play observation ceiling.
- **How to apply:**
  - A board-presence verification needs at least TWO consecutive builds, spanning more than one capture cycle, and the read must include the clock the gate uses (`quote_seen_age_seconds`), not only the row count.
  - A watcher must not `break` on the first success when the claim is "it stays fixed". Stop on N distinct builds instead.
  - Do not release a claim or close a lane on a first reading of a periodic process. Write "part 1 MET / part 2 OWED" instead.
  - *(evidence: `deploys.md` 22:46Z, 23:12Z correction, 23:24Z; `log/2026-09-13.md` "lane `quote-state-publish-retry`")*
## 2026-09-14 — OVERTURNED: "the 1,900 MB heavy-build floor is stale" AND "refresh-worker's memory ratchets slowly until the build is refused". Both are false. The main process STEPS up once after its first full build and holds it `[lane heavy-build-memory-refusal]`

- **What was believed (the lane's own H1/H2, and the floor's comment):**
  - The floor was sized 2026-08-07 for an in-process MLB hydration transient that now runs in a capped child, so it must be too high.
  - The ~16 h refusal came from a slow anon ratchet or from concurrent child jobs.
- **What falsified it** (refresh-worker, 09-12 18Z..09-13 23:30Z, 8,829 `ALL_PROCESS_MEMORY` samples plus 2 s `MEMORY_WATCHDOG` in 16 builds):
  - Steady-state builds still peak +296 / 719 / 1,416 MB at parent stages, with minimum headroom 633 MB. The floor is about right.
  - After every boot, unreclaimable jumps from ~75 MB past the 2,196 MB refusal line within 16-60 min, then barely moves (+~190 MB in 16 h).
  - 3,303 refused-level samples had no child process.
  - Only restarts cleared it.
- **How to apply:**
  - Before lowering a memory guard whose sizing comment is out of date, measure the current build's continuous peak (watchdog cadence, not stage-boundary samples). The stage that moved may not have been the only cost.
  - Split "step after first build" from "ratchet" by the per-hour MINIMUM within one boot. A flat minimum after the first hour is a step, and restarts, not trims, are what reset it.
  - Ledger corollary from the same lane: a claim-transfer note on a `- Files:` line that still names the file (backticked OR bare) is parsed as a live claim by `lane_claims._claims`. Wording like "is also claimed by ..." there reads as a disclaimer and drops the path after it. Describe moved claims without the file name, then re-run `_claims` on the PRIMARY `lanes.md` before editing.
  - *(evidence: `log/2026-09-14.md`, section "lane `heavy-build-memory-refusal` — checkpoint"; `state_worker.md [refresh-worker-heavy-build-refusal]`)*
## 2026-09-14 — OVERTURNED: "a capped `games_with_outcome` is a finals-side loss" — and, twice in the same diagnosis, "the producer failed" `[no lane]`

- **What was believed:**
  - Every documented cause of a capped `games_with_outcome` is finals-side (0-0 placeholder, no numeric score, game_pk/event_id join), so a 5-of-15 night reads as a finals problem.
  - Then, in turn: "the live-odds-worker OOM storm starved the lens", and "the lens produced no full-game projection".
- **What falsified it:**
  - 09-12 served `unscored: {}` with 15/15 finals. The cap was the ledger population: 8 `segment=full` h2h records.
  - The OOM storm was as bad on 09-11 (32 kills), which scored 13 games.
  - `TICK_COMPLETE` read mlb True, and layer2's `sources_seen.live_mc` showed full-game projections for 1-9 games while the ledger wrote none.
- **How to apply:**
  - On a capped date, read `unscored` FIRST. If it is empty, the loss is in the ledger population. The next reading is `records_by_market.h2h` and per-game `segment=full` counts in the per-record ledger, not the finals index.
  - Before naming an infrastructure event (OOM storm, deploy) as the cause of a data loss, pull the same event count on a night that did NOT lose data. Here that was one events-API call, and it killed the attribution.
  - A producer's health line and a join's index count are both UPSTREAM of the ledger write. Neither shows the write happened.
  - *(evidence: `log/2026-09-14.md` section "no lane — `live-gameline-accuracy-snapshot` run")*
## 2026-09-14 — OVERTURNED: "PUBLISH_FAILED rose 0 -> 9 after the refresh-worker deploy" — the baseline hour sat inside the defect window `[lane heavy-build-memory-refusal]`

- **What was believed:** the scheduled deploy of `fb0c91cf` recorded a red flag. There were 0 `PUBLISH_FAILED` in the hour before the deploy and 9 in the first 16 min after it.
- **What falsified it:**
  - The baseline hour (12:36-13:36Z) was a heavy-build refusal stretch: 35 refusals, 0 `PORTFOLIO_COMMIT`. The heavy build is what publishes, so it publishes nothing and cannot fail to publish. The hour was quiet by construction.
  - The 22 h before it on the same old commit: 4,053 `PUBLISH_FAILED` (94-261/h).
  - After the deploy: 62 in ~50 min, the low end of the old rate.
- **How to apply:**
  - Before comparing a post-deploy count to a pre-deploy window, check the window was doing the work that produces the count. A deploy that fixes a stall re-enables every side effect the stall had suppressed. "0 before" then means "not running", not "not failing".
  - Pick a baseline outside the defect window, or report the count per unit of work (per heavy build), not per hour.
  - Specialises [[re-baseline before judging]]: the one-hour window was not stale, it was unrepresentative.
  - *(evidence: `deploys.md` 2026-09-14 14:55Z; `log/2026-09-14.md` session 0f5b256e ~14:45Z section)*
## 2026-09-14 — OVERTURNED: "my commit gate checked the deleted lines". It passed on an EMPTY set, and a `-NoNewline` patch export then destroyed the edits it was protecting `[lane book-grid-gameline-ledger-log]`

- **What was believed:** a PowerShell gate verified that a `lanes.md` commit removed only my own lines:
  - `$deleted = git diff -U0 | ? { $_ -match "^-[^-]" }`
  - then "fail if any deleted line is foreign".
- **What falsified it:**
  - My one deleted line was `-- Blocked by: none.`. Its second character is `-`, so the filter dropped it.
  - `$foreign` was empty because `$deleted` was empty. The gate printed an empty list and passed, while numstat beside it read `7 1`.
  - Minutes later, recovering from a stale-base ledger-guard block, `git diff --cached | Out-File -NoNewline` joined every patch line into one.
  - `git restore` had already discarded the worktree copy, and `git apply` refused: "No valid patches in input".
- **How to apply:**
  - A "none of X is foreign" gate must ALSO assert the size of X. numstat's deletion count is the cross-check: `7 1` must yield exactly 1 deleted line.
  - Exclude only the `---` file header, never a `^-[^-]` class. A markdown bullet is `- `, so a deleted bullet starts `-- `.
  - Never export a patch through a PowerShell pipeline (`Out-File`, `-NoNewline`, `>`). Use `git diff --output=<file>`.
  - Prove the patch with `git apply --check` BEFORE discarding its source.
  - *(evidence: `log/2026-09-14.md` section "lane `book-grid-gameline-ledger-log` — checkpoint")*
## 2026-09-14 — OVERTURNED: "only a restart clears a heavy-build refusal stretch" — and a safety threshold chosen without that data cost ~11 h of builds in 45 h `[lane heavy-build-memory-refusal]`

- **What was believed:** once refresh-worker's main process settled above ~2.2 GB, heavy builds stayed refused until a boot. That belief set `339dc6e9`'s recycle threshold at 15 consecutive refusals, "to avoid restarting over a transient spike".
- **What falsified it:**
  - A replay of 23 closed streaks. 18 ended with an admitted build and no boot, after 10-80 min.
  - The same replay against thresholds: 15 leaves 987 minutes with no full build, while 1 leaves 300, because a boot resumes builds in a median 13.1 min.
  - The user asked "why do we need 15?" before anyone had measured it.
- **How to apply:**
  - A safety margin on a recovery action is a number, and it needs the same evidence as any other number. Replay candidate thresholds against the logged history before shipping one, and count the cost the margin buys (here, minutes without builds), not only the failure it guards against.
  - "Clears only on X" needs the population where it did NOT clear, counted. The original diagnosis looked at the 16 h stall and the boots, never at the streaks between them.
  - *(evidence: lane heavy-build-memory-refusal DECISION 2026-09-14 ~15:10Z; `scratchpad/threshold_sim.py` from session 0f5b256e)*
## 2026-09-14 — OVERTURNED: "CANDIDATE_POOL_CACHE limit= reports the real cap" — the test pinning it compared two values that are EQUAL by default `[lane heavy-build-child-process]`

- **What was believed:** `0a18557a` made the log line report the pool-cache cap. Its commit message and lane text said so, and `test_reports_this_pool_and_the_cache_total` passed, asserting `limit == service._candidate_pool_cache_max`.
- **What falsified it:** production at 19:20:05Z with the env read back as 2 printed `limit=12`. The print still used `_max_snapshots`. The test built the service with the env unset, where both attributes are 12, so it passed against the wrong field.
- **How to apply:**
  - A test that a value comes from X and not Y must run in a state where X != Y. When a new knob defaults to the old value, every default-state assertion about the knob is vacuous. Set the knob to a non-default value in the test.
  - Also run the new test against HEAD's file: a test that passes on the old code proves nothing about the change. Here the cap tests failed on HEAD, but the log-field test had no case that could.
  - Before quoting a log field as proof that config reached production, check the field reads the variable you changed.
  - *(evidence: `deploys.md` 2026-09-14 20:29Z and 21:16:30Z; fix `d4deb502`)*
## 2026-09-14 — OVERTURNED: "the 09-15 board is a post-deploy population because its date begins after the deploy" — a per-day first-sighting ledger is written by builds that ran BEFORE its date `[lane accuracy-assessment-0914]`

- **What was believed:** deploy #3's prediction named "the first board date written entirely after live (09-15 CT)" as the full read of the recorder's new team-name fields.
- **What falsified it:**
  - The pre-live 20:53:26Z build on 09-14 had already recorded every 2026-09-15 key; the shortlist builds the next date inside its horizon.
  - The recorder writes a key once per board date, so the post-live 09-15 builds only added 414 new keys, all soccer.
- **How to apply:**
  - A "post-change population" is defined by each record's own written-at time (`t` vs the live time), never by the date label on the file.
  - Before naming a date as the reading, check when its first part was written.
  - *(evidence: deploys.md 2026-09-14 21:30Z follow-up; `deploy3_reading.py 2026-09-15 2026-09-14T21:03:17Z`)*
## 2026-09-14 — OVERTURNED: "I can write the time from how long things usually take" — two ledger times this session were written from expectation, and both were wrong `[lane accuracy-assessment-0914]`

- **What was believed:** a finish time, or a claim's expiry, could be written into the ledger from the expected duration.
- **What falsified it:**
  - "preview v2 finished ~20:05Z": it finished before 20:00Z; the clock read 20:01:50Z.
  - "the claim lapsed at its TTL (21:16:44Z) before this entry was pushed": the push finished 21:14:28Z, and the claim was released by token.
  - Both reached origin/main before a clock read caught them.
- **How to apply:**
  - Read the clock in the same command that writes a ledger time. The corrected appends stamp their heading from `datetime.now(timezone.utc)` at write time.
  - Something that has not happened yet ("will lapse", "should finish") goes in the future tense, never as a past fact.
  - *(evidence: deploys.md 2026-09-14 21:15Z correction; lanes.md PREVIEW v2 heading correction)*
## 2026-09-14 — OVERTURNED: "a layout fit measured on the worktree app predicts production" — the same commit at the same viewport put the header lettering ON screen locally and OFF screen in production `[lane brand-logo-v3]`

- **What was believed:** a 13-reading local sweep of the header gives production's shape, and production only needs a spot check.
- **What falsified it:**
  - `/market-board` at 1500px. Locally the wordmark slot was 273px, so the lettering (which needs 268) was SHOWN.
  - On production web `ff7ec8be`, same viewport, the slot was 264px and the lettering was hidden. The live pills are ~9px wider.
  - The cause is undiagnosed: font availability, or the nav's contents.
- **Why it did not ship a defect:** the fit rule is content-driven (a flex basis plus wrap and clip, no breakpoint), so it hid correctly. A breakpoint tuned on the local numbers would have put the pills onto a second row in production at 1500.
- **How to apply:**
  - Any size-sensitive layout claim ("shows from N px", "fits at N px") is read on PRODUCTION after the deploy, at the edge widths. A local reading is a prediction, not the result.
  - Prefer a content-driven fit over a breakpoint tuned on one environment's metrics.
  - *(evidence: `lanes_history.md` brand-logo-v3 local reading; `deploys.md` 2026-09-14 5:34 PM CT)*
## 2026-09-15 — OVERTURNED: "H1 test-confirmed" — the test stubbed the one input production lacked, so it confirmed a mechanism that was not the cause `[lane nfl-live-props-board-lane]`

- **What was believed:** live NFL props were demoted on the main board because pre-kickoff state rows won a first-wins dedupe over restated L2-A cards. A new test through the real `read_combined_intelligence_response` failed on HEAD and passed with a fix, and the fix was deployed to web as `dedfede6`.
- **What falsified it:** after the deploy the page still served all 72 DEN @ KC props as watchlist / `no_game_state`.
  - Every `by_date` candidate_count was 0: there were NO state rows in production, so the fix's own log line never printed. **[CORRECTED 2026-09-15, lane combined-board-state-rows-lost: FALSE. There WERE state rows (refresh-worker persisted 374 for 09-14 at 01:56:23Z). The combined reader could not parse them. See the FORBIDDEN entry "a reader's zero is not the writer's absence" below. The dedfede6 conclusion (inert) still stands; its stated reason does not.]**
  - The real cause was upstream of the merge. The live restate built chips in-process (`build_game_chips`), which on web had no live NFL chip, while `/api/board/game-chips` served the worker-published artifact that did.
  - The test had patched `build_game_chips` to return the live chip, the exact thing production was missing. Fix 2 (`c4f45fee`) read the published chips, and props went live on the next read.
- **How to apply:**
  - Before building a test on a hypothesis, confirm its PRECONDITION exists in production. H1 needed state rows, and `by_date.candidate_count` in the same payload already said 0.
  - A test may only stub an input after it has been shown to carry, in production, the value the stub returns. Stubbing an upstream source proves the code downstream of it and nothing about whether that source delivers.
  - After a fix deploys, read the fix's OWN log line (`COMBINED_STATE_LIVE_RESTATED` here) before reading the outcome. Its absence named the wrong mechanism in one query.
  - *(evidence: `deploys.md` 2026-09-15 02:15:21Z and 02:29:09Z; lane nfl-live-props-board-lane)*
## 2026-09-15 — FORBIDDEN: reading a READER's zero as the WRITER's absence — `by_date` 0 was a dated state the reader could not parse, and the line quoted as proof said so `[lane combined-board-state-rows-lost]`

- **What we believed:** production had no per-date state rows. So `dedfede6`'s state-row restate had nothing to act on, and the combined board was built from Layer 2 cards alone by necessity.
  - `log/2026-09-14.md:720` "so there were no state rows"; `deploys.md` 2026-09-15 02:15:21Z entry ("no state rows: `COMBINED_BOARD_VINTAGE_IGNORED ...`"); this file's line above, now corrected.
- **What was actually true:**
  - TECHNICAL: refresh-worker persisted real boards: 374 / 275 / 259 candidates for 09-14 (e.g. `STATE_PERSIST_BEGIN candidate_count=374` 01:56:23Z) and 14 for 09-15.
  - Web read those exact payloads: stamps equal the worker's `CANDIDATE_POOL_READY` to the second on 4 of 4. Then it dropped every row.
  - The cause: `_read_single_date_response_for_combining` read through `_read_state_payload` and never called `_expand_persisted_state`. The writer stores `by_sport` member-aliased, the combine loop's `isinstance(items, list)` skipped every entry, and the scalar `candidate_count` held the `> 0` gate open.
  - Every other reader of that file (`read_intelligence_state`) expands; this one never did.
  - Duration unknown: aliasing landed 2026-08-09 (`2e6ad549`), and the last non-zero `by_date` in the ledger is 2026-08-29.
  - EPISTEMIC: the line quoted as proof of absence was a contradiction. `COMBINED_BOARD_VINTAGE_IGNORED date=2026-09-14 stamp=2026-09-15T01:54:49Z reason=no_rows` means a payload WAS read (it has a stamp), and it had already passed a `candidate_count > 0` gate. "Has candidates, has no rows" is a reader defect by construction. It was read as "no data".
  - The earlier tests of this function (`test_board_vintage_gating.py`) replace the reader with hand-built plain lists, which is exactly the shape production never delivers. That class is already FORBIDDEN (2026-09-09, harness that supplies what production lacks); it is not restated here.
- **How we found out:** the user asked why the board said stale while the worker persisted hundreds of candidates. The writer's own line (`STATE_PERSIST_BEGIN`) was cross-read against the reader's (`VINTAGE_IGNORED`) for the same date and minute. Then a test with the REAL writer and REAL reader, nothing stubbed: 40 and 1,500 rows read back as 0 on HEAD, and expand-on-read gave 40 and 1,500. Live on web `b6a0e346`: `by_date` 09-15 0 -> 106 (`deploys.md` 2026-09-15 14:03:51Z).
- **EXONERATED:** a key/date mismatch between the worker's writes and web's reads. Stamps matched to the second on 4 payloads, and `/api/ops/artifacts/export` showed the states travel in keyvalue, which web reads.
- **The rule going forward:**
  - A zero, empty or "missing" reported by a READER is a statement about that reader. Before recording it as a property of production, read the WRITER's own line for the same key and time window.
  - A line that carries BOTH a stamp/count AND "no rows" is a contradiction to chase, never a confirmation of absence.
- **Cost:**
  - One web deploy shipped inert on the false precondition (`dedfede6`).
  - A false line stood in this file for ~12 h, repeated in `deploys.md` and the session log.
  - Every persisted state row (259-479 per build on 09-14) was absent from the main board for an unknown period, possibly weeks.
- **Check, not rule:**
  - (1) Put expansion INSIDE `_read_state_payload`, the choke point every state read shares, so no future caller can skip it. Pin it with a test that round-trips the real writer through every public reader.
  - (2) Emit `by_date[date].stored_candidate_count` (the payload's scalar) beside `candidate_count` (rows read), and log `COMBINED_BOARD_STATE_ROWS_UNREADABLE` when stored > 0 and rows = 0. The contradiction then appears in the served payload, where the last three sessions looked, instead of only in a log line nobody queried.
## 2026-09-15 — FORBIDDEN: carrying a deploy's predicted effect on a time-varying field from a reading taken hours earlier — re-derive it at preflight, and baseline every field it names plus the served row count `[lane combined-board-state-rows-lost]`

- **What we believed:** expanding the state on read "would NOT move `computed_at`", because the state stamps it adds are newer than tomorrow's shortlist. Written into the lane and `state_board.md` before the deploy, from readings taken at 03:56Z.
- **What was actually true:**
  - At deploy (web `b6a0e346`, live 14:10:07Z), refresh-worker's heavy builds had been refused since 13:41:13Z. The fast path kept the shortlists fresh (09-15 `14:07:00Z`, 09-16 `14:10:11Z`), so the 09-15 state (`13:39:43Z`) was now the OLDEST input.
  - `computed_at` moved from `13:48:51Z` `fresh` to `13:39:43Z` `stale`. The prediction had been true in the 03:56Z regime and false in the 14:10Z one, and nobody re-derived it for the regime the deploy landed in.
  - SECOND HALF OF THE SAME ERROR: the pre-deploy baseline (13:57:55Z) recorded `by_date`, `legacy_candidate_count`, `artifacts_dated` and `computed_at`, but NOT the served row count. So whether state rows displaced Layer 2 cards under first-wins dedupe is now PERMANENTLY unmeasurable (at most 106).
- **How we found out:** the post-deploy reading at 14:10:27Z, cross-read with refresh-worker `CANDIDATE_POOL_READY date=2026-09-15 count=106` at 13:39:43Z (`deploys.md` 2026-09-15 14:03:51Z).
- **The rule going forward:**
  - A deploy's expected effect on any field that depends on worker timing (ages, freshness verdicts, counts) is re-derived from readings taken inside the preflight window, not carried from the diagnosis.
  - The baseline captures every field the prediction names PLUS the served row count and its composition by source, because a merge-order change can only be attributed against those.
- **Cost:**
  - The user was shown a false prediction and approved a deploy partly on it. The outcome was benign (the new age is true, and the user kept the `stale` label).
  - One effect of a product change can never be measured.
- **Check, not rule:** preflight asks for the prediction and the baseline. `deploy_preflight.py` takes `--expect "<field>=<value>"` and `--baseline-read-at <UTC>`, and returns HOLD when the baseline is older than the 15-min CLEAR window or names no row count. The post-deploy entry then lists expected against measured, one line per field.
## 2026-09-15 — FORBIDDEN: caching a verdict whose validity depends on the date's relation to TODAY under a key that is only the date. At midnight "tomorrow" becomes "today" and the verdict outlives its premise. `[lane wnba-future-date-cache-carry]`
- **The belief overturned:** `has_games_for_date` (`syndicate/features/wnba/sources.py`) said *"A confirmed True is stable and safe to remember."* It was safe for an ESPN-confirmed True. The same set also held Trues from the "not today and a slate file exists" shortcut, whose premise is the date NOT being today. It was checked before the today rule, so after midnight it answered for today.
- **What was actually true:**
  - refresh-worker writes an EMPTY `recommendations_slate_<tomorrow>.json` (94 B, 0 games) before midnight CT.
  - The process that asked about tomorrow in the evening read the no-game day as confirmed. It saved the 2026-08-30 slate under today's `live_state` key, and the board showed four FINAL chips on 09-14 and 09-15.
  - This is exactly the seed `wnba-schedule-guard-fix` left unnamed on 09-11.
- **How we found out:** the user saw the chips. The phantom log line starts at 00:04 and 00:06 CDT, right after midnight. The empty slates were published BEFORE their date's CT midnight on the bad days and AFTER it on the clean days (`deploys.md` 2026-09-15 14:34:14Z). A writer-level test that primes tomorrow, rolls the clock and builds returned `2026-08-30` on origin/main.
- **The rule going forward:**
  - One cache holds one provenance.
  - A value derived under a clock-relative condition (`!= today`, "past", "future") is either not cached, or keyed by (date, the day it was evaluated).
  - A test for any date-keyed cache ROLLS THE CLOCK between the write and the read. Two calls on the same "today" cannot see this.
- **Cost:** two days of stale WNBA chips and a phantom `scheduled_games 4` on Layer 2. The 09-10 fix had passed its same-day readings because they never crossed a midnight with a pre-written tomorrow file.
## 2026-09-15 — OVERTURNED: "the board-snapshot readers miss the writer's disk fallback, so route them through `_read_state_payload`" — the fallback cannot reach web at all, and routing would have handed them month-old disk files `[lane state-read-expand-choke-point]`

- **What was believed:** `read_latest_intelligence_board_snapshot_response` and its fallback read keyvalue only, while `_write_state_payload` can divert an oversized snapshot to disk. So they had a real gap, and the user was told so and asked for the routing.
- **What falsified it,** measured 2026-09-15 14:39-14:41Z before any code:
  - `board_snapshot*.json` is deliberately NOT in the artifact allowlist (`artifact_publisher.py:1072-1095`), so no fresh snapshot can reach web's disk whatever the reader does.
  - 0 disk-fallback writes on either service in 24 h.
  - Web's disk DOES hold a stale `reports/intelligence/intelligence_state.json` (25.8 MB, stamped 2026-08-10). `_read_state_payload` returns a disk copy whenever keyvalue has none, and the snapshot fallback loop globs disk. The "fix" would have created the failure it claimed to close.
- **How to apply:**
  - Before widening a reader to a new SOURCE, check two things on the SERVICE that runs the reader: (a) does the transport ever deliver a FRESH copy of that source there (allowlist, publish logs), and (b) what STALE copies already sit there.
  - A reader and its transport are one change. Neither half is a fix alone, and the reader half is the dangerous one.
  - A gap stated from code alone is a hypothesis. It was surfaced to the user as a finding, which is how it became an instruction.
  - *(evidence: `state_board.md` `[combined-board-state-rows-lost]`; `log/2026-09-15.md` session 3a65723e)*
## 2026-09-15 — OVERTURNED: "the stored count will equal the rows read" — the writer caps each `by_sport` list per sport, so an instrument pairing two counts differed by design on its first reading `[lane combined-board-rows-unreadable-tripwire]`

- **What was believed:** after web `da268e07`, `by_date[date].stored_candidate_count` would equal `candidate_count` for every readable date. That was written into the lane's Verification and the deploy's prediction.
- **What falsified it:**
  - The first reading (15:37:01Z): 09-15 stored **113**, rows **111**.
  - refresh-worker saved the full pool (`CANDIDATE_POOL_READY count=113`). The writer builds `by_sport` with `_default_unbounded_by_sport_cap()` = 60 per sport, and La Liga was served at exactly 60.
  - The cap and its "true counts stay available via `candidate_count`" comment sat at the call site the whole time.
- **Why it cost nothing:** the tripwire fires only at `rows == 0`, a rule chosen for the defect, not for equality. Had it fired on `stored != rows`, it would have alarmed on every busy slate from the first minute.
- **How to apply:**
  - Before predicting that two numbers from one payload agree, enumerate every TRANSFORM the writer applies between them: caps, dedupe, filters, pruning. Read the builder, not only the field names.
  - Gate an instrument on the defect's own signature (`rows 0 / stored > 0`), never on equality of two counts that pass through different transforms.
  - *(evidence: `deploys.md` 2026-09-15 15:30:14Z; `state_board.md` `[combined-board-state-rows-lost]`)*
## 2026-09-15 — OVERTURNED: "a `cd` at the top of a Bash call scopes that call" — parallel Bash calls share ONE shell, and a sibling's `cd` ran `git rebase` in the primary tree twice `[lanes state-read-expand-choke-point, combined-board-rows-unreadable-tripwire]`

- **What was believed:** `cd /c/tmp/syndicate-sessions/<lane> && git rebase ...` operates on that worktree, whatever other Bash calls run beside it.
- **What falsified it:**
  - Twice, a call issued in parallel with one that ran `cd /c/Users/tempadmin/OneDrive/Coding/Syndicate` printed `cannot rebase: You have unstaged changes`. The worktree was clean, so the rebase had run in the PRIMARY checkout.
  - A survey `grep` in the same batch returned line numbers ~400 lower: the primary tree's stale copy of `pipeline/intelligence_state.py`.
  - Git refused both rebases, and the primary tree was verified untouched (HEAD `e88447a2`, no rebase in progress). A clean primary tree would not have refused.
- **How to apply:**
  - In any Bash call issued in PARALLEL with another, never use a bare `cd`. Use `git -C <path>` and absolute paths, or confine it to a subshell: `( cd <path> && ... )`.
  - A result whose line numbers, HEAD or `git status` do not match the worktree you meant is the signal. Stop and re-read the tree before running a mutating command.
  - A mutating git command (`rebase`, `reset`, `add`, `commit`) never shares a batch with a call that changes directory.
  - *(evidence: `log/2026-09-15.md` session 3a65723e, dead ends)*
## 2026-09-15 — OVERTURNED: "a deploy the guard let through was a deploy the guard checked" — two web deploys passed `deploy-guard.py` because it never classified them as deploys `[lane deploy-guard-python-post]`

- **What was believed:** the two 2026-09-15 web deploys (`b6a0e346`, `da268e07`) went through the two-lock gate. The claim and a CLEAR preflight had been taken, the deploy call was not refused, and that read as "the guard checked the locks".
- **What was actually true:** `POST_INTENT` knew only curl/PowerShell. The Python `urllib` POST matched `DEPLOYS_ENDPOINT` but not the intent, so the guard returned exit 0 WITHOUT looking at a claim or a receipt. The locks were held only because the session took them voluntarily. Any session deploying the same way would have skipped both, and `NO_EXPECTATION` too, silently.
- **How we found out:** a smoke test of the updated guard in the primary tree. A first synthetic command ALSO returned 0 (its "POST" was only in a comment), and asking why led to the pattern. The guard's own blocked shape (`render_deploy.py`) returned 2, while a command shaped exactly like that day's deploys returned 0. Fixed in `11167fdf`; the primary tree now returns 2 for it.
- **The rule going forward:**
  - A guard's SILENCE is evidence only for shapes the guard is known to classify. Before relying on "not refused", run the guard on the EXACT command shape you are about to use and see it refuse without locks. Same family as `feedback_instrument_blindness`: a healthy reading means nothing until you have seen what makes it read unhealthy.
  - When a deploy goes through, look for the guard's own "DEPLOY GUARD: clear" line. Its absence means the command was never classified.
  - A text guard cannot see into a script run from a FILE; deploy inline, with `scripts/render_deploy.py`, or with curl.
- **Cost:** two production deploys ran outside the gate they were believed to pass. No harm, because the locks happened to be held, but that was luck of habit, not enforcement.
  - *(evidence: `leads.md` 2026-09-15 lead, promoted; `log/2026-09-15.md` session 3a65723e; lane `deploy-guard-python-post`)*
## 2026-09-15 — OVERTURNED: "soccer shots props over-predict by 40%; ship a 1.33 divisor". A per-row skill score keyed on a PREDICTION list cannot see what the list is missing, and it read a stale squad as a level error `[lane soccer-season-market-audit]`

- **What was believed:** `[soccer-shots-prop-skill]` (2026-08-31) measured predicted 0.58 vs realised 0.42 over 9,840 (player, match) rows, a ratio of 1.40, and a held-out scalar divisor of 1.33 "wins in all 9 leagues".
- **What was actually true** (season to date, 07-22..09-14):
  - Players who actually appeared are UNDER-predicted: 0.87 held-out; regular starters 0.68, fringe players 1.08.
  - The predicted lists are last season's. The share of real team shots attributable to a listed player runs from 36% (Championship) to 87% (MLS).
  - On the new data, the 08-31 method gives 1.09–1.13. That method is an unconditional mean over every predicted row, with unmatched or absent players scored as 0. Absent squad members and name misses become zero-shot rows, and shots by unlisted players are invisible; both push toward "over-predicts".
  - The divisor now worsens MAE in the leagues props are bet on (EPL 0.828 → 0.831, Serie A 0.835 → 0.839).
- **How we found out:** a props run on ESPN box scores, bound one-to-one per side, read 0.88 — the opposite sign. Before quoting either number, the join was measured from the OUTCOME side: the share of real shots belonging to a listed player, per league.
- **The rule going forward:**
  - Before reading a level error off rows keyed on a prediction list, measure coverage from the outcome side: what share of the real volume (shots, goals, minutes) belongs to entities the list contains. Below ~90%, the "error" is at least partly the list.
  - Score a conditional quantity on the population the bet settles on — appeared players, `*_if_playing` — not an unconditional mean over a roster.
  - A held-out fit validates a correction only for the population and method it was fitted on. Re-measure when the season, and the squads, turn over.
- **Cost:** a standing shipping recommendation that would have cut starters' shot probabilities further. Caught before any engine change.
  - *(evidence: `findings_2026-09-15_soccer_season_market_audit.md` "Player props"; `state_soccer.md [soccer-season-market-audit]`; `log/2026-09-15.md` session abacd435)*
## 2026-09-15 — OVERTURNED: "a FotMob league id verified against name AND country is a stable join key" — it identified ONE SEASON of the competition, and a same-day decoy check cannot see that `[lane fotmob-season-scoped-league-ids]`

- **What was believed (2026-08-22):** the league ids in `fotmob_match_id.py` and `soccer_fotmob_harvest_2y.py` were "verified against ccode", so they were safe to pin as the join key.
- **What happened:**
  - FotMob's league `id` is SEASON-SCOPED for 4 of the 10 leagues:
    - Eredivisie 892939 -> 900368 -> 937276
    - Championship 893033 -> 900638 -> 938218
    - Belgian 892857 -> 900433 -> 937988
    - MLS 889747 -> 896669 -> 913550
  - The competition itself is `primaryId` (57/48/40/130).
  - From the 2026-27 season on, every live Championship, Eredivisie and Belgian match hid its momentum panel (9 of 9 None on 09-12). Nothing errored.
  - The 2y harvest walked 2024-08..2026-08 with the 2025-26 ids, so it kept ONE season for those four leagues. It was described as two seasons across ten leagues.
- **Why the check missed it:**
  - The verification was a same-day decoy test (Canada 9986, Brazil 268). That proves a key is unambiguous on the day it is read. It says nothing about whether the key is the same next season.
  - The six leagues that never broke have `id == primaryId`, so most of the population looked healthy.
- **How to apply:**
  - A pinned external id needs a CROSS-TIME check as well as a same-day one. Read the vendor's listing on a date from a previous season and confirm the id resolves there too.
  - Prefer the vendor's canonical id (`primaryId`, `parentLeagueId`) when the payload carries one.
  - A dataset described as "N seasons over K groups" must print its coverage per (group, season). A narrow key truncates it silently.
- *(evidence: `deploys.md` 2026-09-15 18:08:50Z entry; commit `c725cc29`; `state_soccer.md` `[soccer-live-momentum]`)*
## 2026-09-15 — OVERTURNED: "the attached-POST classifier leaves reads alone" — it shipped tested only on hand-written commands, and the repo's own read-only graft builder classified as a deploy `[lanes deploy-guard-python-post, deploy-guard-file-scripts]`

- **What was believed:** `11167fdf`'s `_PY_POST_INTENT` blocked Python deploys and ALLOWED reads, on the evidence of its test file (GETs, a comment, GET-list + POST-elsewhere) and three probes of this session's own command shapes.
- **What was actually true:** its body rule `\bdata\s*=` matched any `data = ...`, including the ASSIGNMENT `data = json.loads(urllib.request.urlopen(req...))` that `scripts/build_consolidated_graft.py:93-96` writes right after a GET of `/deploys?limit=5`. That read-only shape, pasted inline, was already blocked on main. The test corpus was written by the author of the rule, so it contained only the shapes the author had in mind.
- **How we found out:** the next lane scanned EVERY repo file naming a deploys endpoint (22) through the landed classifier BEFORE extending it. 2 classified as deploys; one was `render_deploy.py` (correct) and the other the graft builder (wrong). Fixed in `af7c895c`: `data=` counts only after `(` or `,`. Rescan: only `render_deploy.py`.
- **The rule going forward:**
  - Before landing a text classifier that can BLOCK (a guard, a gate, a filter), run it over the REAL corpus it will meet (the repo's own files and past commands that mention the pattern), and list every hit. A hand-written test set proves the cases you thought of, not the ones that exist.
  - Put the real files in the allow tests (copied, resolved, run), not synthetic stand-ins, so a false positive is a red test rather than a user report.
- **Cost:** one false positive shipped to main, and it was live in the primary tree's guard for about an hour. Caught before any read-only script was actually blocked.
- *(evidence: `log/2026-09-15.md` session 3a65723e, the `deploy-guard-file-scripts` entry; commits `11167fdf`, `af7c895c`)*
## 2026-09-15 — OVERTURNED: "a sparkline of the pick's market probability tells the same story as the movement arrow beside it" — the line plotted the no-vig CONSENSUS, the arrow read the shown PRICE, and they disagreed on 132 of 294 rows `[lane layer2-row-parity]`

- **What was believed:** a time series of the pick's no-vig ("fair") probability is the natural picture of "did the market move toward the pick", so it would agree with the arrow that reads the label's odds.
- **What happened:**
  - The first design shipped in `87558f2f`. At 18:08:02Z, 45 of 94 series sloped against their own arrow; at 19:11:17Z, 132 of 294 did.
  - They are different quantities:
    - The arrow compares the label's own price pair: one book, or the best price across books.
    - The line was the de-vigged consensus across every book.
    - The best price can lengthen while the consensus shortens: one book hangs a stale number, the vig moves, or the best-price book changes.
  - Every series was well-formed and every test passed, because the tests checked each visual on its own, never the line against the arrow on the same card.
  - The redesign (`5686a555`, user decision "Plot the label's price from our open") makes the line's ends the label's price pair, so line and arrow cannot disagree. The consensus move went to the tooltip.
  - After it: 0 disagreements on every date (19:56Z), and 519 of 519 on the rendered page.
- **How to apply:**
  - Two visuals side by side on one row must be computed from the same quantity, or labelled as different ones. Test the PAIR, not each one: a "line vs arrow disagree" count would have caught this before the deploy.
  - Name the quantity in the caption ("Implied probability of this pick's price … (best price across books)").
  - A verify script's allow-lists are part of the design. After the redesign the script read "malformed 867" because it still named the old bases. Change the instrument in the same commit as the code it measures.
- *(evidence: `deploys.md` 2026-09-15 18:08:02Z FOLLOW-UP (1), the 19:13:36Z entry and its 19:57:56Z FOLLOW-UP; commits `87558f2f`, `5686a555`, `4ccbea86`)*
## 2026-09-15 — OVERTURNED: "fix the puller that spliced, repair web's copy, and web's merge refusals go to 0" — a SECOND publisher kept republishing its own stale copy, and the merge log had named it all along `[lane book-quotes-splice-repair]`

- **What was believed:** P2 (refresh-worker's tail sync) plus P3 (web's repair) would bring `MERGE_REFUSED_BAD_LINES` to 0. The P4 verify was written that way.
- **What happened:**
  - refresh-worker behaved exactly as predicted: one `STREAM_SYNC_WHOLE` per shard, dropping exactly web's refused counts.
  - Refusals continued on today's shards (mlb 10, soccer 43 per publish), and every one was `publisher=live-odds-worker` in web's `ARTIFACT_MERGE_DEFERRED` line in the same second.
  - live-odds-worker holds its own copies and never re-syncs a shard it already has: the repair list asks only for missing files.
- **Also in the same hour:**
  - I attributed the refusals to `clv_openings` publishes by timestamp adjacency. `_requires_json_lines` matches `book_quotes` only, and `dir=` prints the GRANDPARENT folder (`tracking`), not the family.
  - Three parallel log scans drew 503s from the log API. Most windows came back empty and were printed as "non-json" rather than failing.
- **How to apply:**
  - Before predicting that a receiver-side count reaches 0, enumerate EVERY publisher of the path over a window. Web's merge lines carry `publisher=`; a fix scoped to one publisher is scoped to one publisher.
  - Read the emitter's format string before interpreting a log field (`dir=` was not what its name suggests).
  - A log-API scan runs as ONE process with retry and backoff, and it records which windows actually returned. An empty window is not an empty log.
- *(evidence: `deploys.md` 2026-09-15 19:27:29Z follow-up; `lanes.md` book-quotes-splice-repair P4 READING; `state_worker.md` `[streamed-pull-append-only-tail]`)*
## 2026-09-15 — OVERTURNED: "a lane whose header reads CLOSED on origin/main is safe to archive" — its live owner was reopening it in an uncommitted worktree edit `[session 3a65723e, ledger archive; no lane]`

- **What was believed:** `scripts/trim_lane_blocks.py` proposed 39 closed or orphaned blocks for removal. All 39 read CLOSED on origin/main, held 0 claims and had no OPEN header, so moving any of them to `lanes_closed.md` looked like pure bookkeeping.
- **What happened:**
  - Before touching the 12 closed TODAY, a liveness read found all 4 owning sessions had written their transcripts within minutes. One of them, `3421d2c5`, had an UNCOMMITTED `lanes.md` edit in worktree `disk-inventory-test-clock` flipping `ncaaf-prop-kickoff-slate-date` from CLOSED back to OPEN for a refresh-worker deploy.
  - origin/main cannot show that edit, and the header, claims check and invariants all read origin/main. Archiving the block would have deleted the text the owner's rebase was about to modify.
  - The user's choice ("older lanes only", leaving today's closures to possibly-running owners) avoided the collision; the header alone would not have.
  - A 09-14 closure whose owner was idle for 21h (`brand-logo-v3`) was archived. A 09-10 lane with a stale marker (`wnba-schedule-guard-fix`) was NOT: a live session had closed it today with a handoff to its own OPEN lane.
- **How to apply:**
  - A CLOSED header is the owner's LAST PUSHED state, not their current intent. Before moving or rewriting another session's block, read owner liveness:
    - the session transcript mtime (`~/.claude/projects/*/<sid>.jsonl`)
    - its `.current-lane.<sid>` marker
    - OPEN lanes naming the session
    - `git status` of any worktree named for the lane
  - Treat "live, or has an uncommitted ledger edit" as "do not touch".
  - The lane's CLOSER can differ from its OWNER: check the liveness of both.
- *(evidence: `log/2026-09-15.md` addenda "archived 26 lanes closed before 2026-09-15" and "owner liveness of the 13 closed lanes"; commits `7e721cfa`, `d1d74ce9`)*
## 2026-09-15 — OVERTURNED: "a mechanism that passed a held-out test is ready to build". The test fed it an input production does not have, and on production's own inputs it failed until a join defect was fixed `[lane soccer-player-role-allocation]`

- **What was believed:** the start/sub shot mixture was validated. It passed held out (H8: 9/10 leagues), with P(start | appear) taken from ESPN box-score roles.
- **What was actually true:**
  - Production has no box-score role table.
  - Built from what production does carry (Understat minutes per appearance, ESPN counts, a minutes prior), the same mechanism FAILED: H11 won 6/10 leagues, and H12 was +0.031 log loss.
  - The cause was a join, not the mechanism. A side's rows mix seasons, and one match count across them pushed the big five's shot means to 1.15-1.67x actual.
  - Scoped per season, it passed (H13). A replay of the SHIPPED engine then reproduced it within 0.0001 (H14).
- **The rule going forward:**
  - When a mechanism passes on a convenient input, pre-register a second test on the input the production code will actually read.
  - Then replay the shipped code itself before landing.
  - A pass on outcome-derived features is a pass for the mechanism, not for the build.
- **Cost:** none shipped. The failure surfaced before code.
  - *(evidence: `log/2026-09-15.md` session abacd435; `scripts/soccer_season_audit/calibration_role_mixture5.py`, `calibration_role_mixture6.py`, `calibration_engine_replay.py`; commit `b33ef901`)*
## 2026-09-15 — FORBIDDEN: reading ESPN's soccer scoreboard with a `dates=YYYYMMDD-YYYYMMDD` RANGE for live state. Ask for the single date, and judge freshness by a content field `[lane soccer-live-scoreboard-range-stale]`

- **What happened:** the live poller asked `dates=20260915-20260915`. ESPN answered that query from a copy about an hour old, on both hosts, while `dates=20260915`, the undated scoreboard and the summary were live in the same second. Soccer live state, the live lens and the Layer 2 chips ran ~65 match-minutes behind.
- **Why nothing flagged it:** every timestamp on the way was one this platform wrote -- the file's `generated_at`, `PUBLISH_OK`, the chip `published_at` (79 s old). Only the match CLOCK, compared against ESPN, showed the age.
- **Also:** the range form returned HTTP 400 on 31 of 60 league-dates probed; the single-date form 200 on 60/60 with identical events.
- **The rule:**
  - Any live ESPN read uses the single-date form.
  - A freshness check compares a content field (clock, score, state) against the source. A timestamp written by our own pipeline proves the pipeline ran, not that the data is current.
  - *(evidence: `deploys.md` 2026-09-15 20:29:23Z; commit `20568eff`)*
## 2026-09-15 — OVERTURNED: "`pull_hot_artifacts`' `since=` floor is the calling service's last successful pull". It was ONE keyvalue key across workers, so live-odds-worker's pulls set refresh-worker's floor `[lane soccer-live-scoreboard-range-stale]`

- **What was believed:** the docstring's "floor = the start of the last successful pull".
- **What was true:** the watermark path was keyvalue-backed and identical on both workers. refresh-worker, pulling each board date every ~15-30 min, asked for files changed since live-odds-worker's last pull ~2 min earlier, and never re-fetched an older change it already held. Measured twice from the request URLs: 20:41:05Z -> 20:39:04Z and 21:02:50Z -> 20:58:06Z. The Layer 2 soccer chips stayed stale for 26 minutes while web held the fresh file.
- **Second instance of the shape** after `disk_maintenance._status_path` (2026-08-12), and the one `live_lens_loop.py`'s own comment names for the publish watermark.
- **The rule:**
  - A keyvalue-backed "last run / last seen" stamp carries the SERVICE (`disk_maintenance._service_slug`) and the SCOPE it tracks (date, league) in its path.
  - When a floor looks wrong, read the `since=` value off the request and convert it. Does it equal THIS service's previous start?
  - *(evidence: `lanes_history.md` lane soccer-live-scoreboard-range-stale; commit `082da3e3`)*
## 2026-09-15 — OVERTURNED: "own-goal is correctly excluded" from the soccer TEAM score. Count by the feed's own `scoringPlay`, not by a type-key prefix `[lane soccer-live-scoreboard-range-stale]`

- **What was believed:** `espn_live_state.py`'s comment. Goal variants share the `goal` prefix, and "own-goal ... is correctly excluded here".
- **What was true:** that rule reproduced ESPN's final score on 68 of 95 finished matches. It dropped all 23 `penalty---scored` and all 7 `own-goal` events. Counting every non-shootout `scoringPlay` for the team ESPN tags: 95/95. Excluding an own goal is right for a player's tally and wrong for the scoreboard.
- **The rule:**
  - When a feed publishes its own verdict (`scoringPlay`, `shootout`), carry it through normalization and count by it.
  - Before trusting a hand-listed type vocabulary, replay it against the feed's own final score over a real sample.
  - *(evidence: commit `e115cd6b`; `tests/test_soccer_scoring_events.py`)*
## 2026-09-15 — OVERTURNED: "the fix is on main but its deploy is still my lane's to schedule" — once a commit is on main, the NEXT deploy of main by ANY lane ships it, and a user's timing decision cannot hold `[lane fotmob-team-name-aliases]`

- **What I believed.** Pushing `.py` to main ships nothing, so I could land `867f1481` and then ask the user WHEN to deploy. The user chose "After tonight's matches", and I built a slate-end watcher around that answer.
- **What happened.**
  - `867f1481` landed on main around 19:20Z. The user's decision came around 19:27Z.
  - At 19:31:33Z lane `soccer-player-substrate` deployed main (`f833f7ec`) to the same service, mid-slate, for its own fix. The ride-along included `867f1481`, live at 19:37:29Z.
  - Two more deploys of main by other lanes followed. By the time the slate ended, the "deploy step" had been done three times over, and not on the schedule the user picked.
  - That lane recorded the conflict honestly. Nothing broke. But the user's decision was never enforceable, and my question implied it was.
- **Why.** "Deploy only commits on `origin/main`" makes landing the same as queuing: every deploy is cumulative by design. `autoDeploy = no` bounds WHEN someone deploys, not WHAT their deploy carries.
- **How to apply.**
  - When a user wants to control when a change reaches a service, decide that BEFORE landing it. Either keep it off main (branch) until the window opens, or say in the question that the next deploy of main by any lane will carry it.
  - When a lane's deploy is pending, read the service's deploys API before building any schedule around it. Check by CONTENT whether an earlier deploy already carries the commit.
- *(evidence: `deploys.md` 2026-09-15 19:31:33Z `soccer-player-substrate` entry, its "CONFLICT" bullet, and the 21:3xZ `fotmob-team-name-aliases` READING)*
## 2026-09-15 — OVERTURNED: "log lines found by a scan can be re-read later" — Render's ~14-day retention is ROLLING, and 12 of 20 order records expired between the scan and the re-read, 75 minutes apart `[lanes polymarket-no-fill-booking-audit, execution-ledger-live-trim]`

- **What happened:**
  - A day-by-day FILL_PRICE scan read lines stamped 09-01T19:25:55Z at about 20:00Z on 09-15, and saved only side, avgPx and booked price.
  - The re-read for contracts, market and stake at 21:15Z returned 0 lines for all 13 of those orders.
  - Retention had rolled past them. One record (`C7CNYDJV4KDH`) survived only because a separate query had printed its whole `ORDER_STATE` line at 20:58Z.
- **How to apply:**
  - Anything older than about 13 days in Render logs is about to disappear. When a scan finds a record that matters, save the FULL raw line to disk in the same pass, not a parsed subset.
  - State the window's age when reporting a log-based reading, so its expiry is visible.
- **Same session, different instrument:** releasing a file claim was checked by the full path only. A bare basename in another Files-labelled bullet of the same block kept the claim (`lane_claims.matches` uses endswith), and a peer lane caught it. Diff the claim SET for every token that `matches()` the path, not the path string.
- *(evidence: `lanes.md` execution-ledger-live-trim RESTORE MANIFEST; the lane soccer-live-scoreboard-range-stale message recorded in its block; `deploys.md` 2026-09-15 20:52:30Z)*
## 2026-09-15 — OVERTURNED: "main can't ship, steps A/B are not approved" — the status came from ANOTHER lane's citation, and the owning lane had already recorded the approval `[lane anytime-td-quote-side-yes]`

- **What I believed.** At 21:00Z, `f833f7ec..6d526851` carried soccer-player-role-allocation steps A/B "not approved for deploy". I read that from lane `book-quotes-splice-repair`'s block, which cited it. So I put "off-main" to the user as the recommended path, built `1d78d38b` (live SHA + the fix), took the claim and looped preflight.
- **What was true.** soccer-player-role-allocation's OWN block, in its 20:45Z VERDICT, already read "User decision: deploy main's tip to live-odds-worker, then refresh-worker, AFTER 21:25Z".
  - An off-main deploy after that tip deploy would have reverted A/B and `070a05bf` on refresh-worker. One before it would have cost an extra reboot and 25 min of spacing.
  - A peer's message caught it before any deploy. The fix then shipped as a ride-along in the tip deploy (`2d579fd1`, reading 256/256).
- **Why.** A citation is a copy with its own timestamp. A deploy blocker's status moves within the hour on a day like this, and the lane that CITES it has no reason to update the copy.
- **How to apply.**
  - Before calling a commit on main a deploy blocker, read the OWNING lane's block on `origin/main` at that moment: its VERDICT or STATUS lines, and any "User decision" line.
  - Then read the service's claim status. A claim held for a main tip is the other half of the same answer.
  - Put the read time in the question to the user. An option built on a status that is 15 minutes old or older should say so.
- *(evidence: `lanes.md` book-quotes-splice-repair line 437 vs soccer-player-role-allocation VERDICT 2026-09-15 20:45Z; `deploys.md` 2026-09-15 22:15:53Z READING; log 2026-09-15 anytime-td-quote-side-yes stand-down entry)*
## 2026-09-15 — OVERTURNED: "re-running another run's script on unchanged inputs reproduces its numbers" — `SYNDICATE_REPO_ROOT` decides WHICH checkout's `team_names.py` is imported, and that alias set changes the market join `[session abacd435, fix #5a measurement; no lane]`

- **What I believed.** H22's script, re-run against the same audit cache an hour later, returned 402 priced matches and primary n=320 against the recorded 394 / 312. No cache file had been touched (fd CSVs 17:09Z, prod/recs 17:11Z, outcomes.json 17:19Z) and `audit_games.load_fd` reads local CSVs with no network path, so I wrote it up as the football-data closing-odds join drifting — and put that claim into two docstrings of the H25 runner.
- **What was true.** Run the way it was actually run — `SYNDICATE_REPO_ROOT` pointing at the primary tree, which this session's own transcript records — the script reproduces its recorded output byte-for-byte: 394 priced, n=312, P0 +0.0117, WF60 +0.0075, WFP +0.0076, M0 +0.0097.
- **Why.** `scripts/soccer_season_audit/common.py` puts `SYNDICATE_REPO_ROOT` on `sys.path` and imports `canonical_team_name` / `match_team_name` from THERE. The primary tree is 117+ commits behind origin/main, and the worktree's `team_names.py` (201 lines vs 182) carries six club-spelling aliases it lacks — RasenBallsport Leipzig, Paderborn 07, Parma Calcio 1913, Deportivo La Coruna, Stade Rennais, Oud-Heverlee Leuven, each mapped to its fixture spelling — added by fix #1's `f833f7ec`. They bind 8 more fixtures to football-data rows.
- **Scope.** The alias set moves ONLY which matches carry a market price. 584 matches, 477 primary, every arm's log loss and bias, and both the H22 and H23 verdicts are identical either way.
- **How to apply.**
  - When reproducing another run, pin every environment variable it set — the repo root included — and print them beside the result. An unset root silently resolves to a DIFFERENT checkout, and on this machine the checkouts are hundreds of commits apart.
  - A count that moves while every scored number holds still is pointing at a JOIN, not at data drift. Diff the helper module the join imports before blaming a cache, and check `load_*` for a network path before blaming a feed.
  - Name the checkout (or the alias set) in any cross-run comparison of market-joined numbers. H25's Brier gap to the close is on 320 matches and is NOT comparable to H22's 312.
- *(evidence: `log/2026-09-15.md` 17:55 CT entry; scratchpad `scoring_env_out.txt` vs `scoring_env_rerun_2248.txt` vs `scoring_env_rerun_primaryroot.txt`; `team_names.py` diff, primary tree vs worktree)*
## 2026-09-15 — FORBIDDEN: running `session_worktree.py land --lane <slug>` with any slug other than the one whose branch this worktree is on. It lands THAT LANE'S BRANCH, not the commit in front of you `[session abacd435, lanes soccer-player-role-allocation / soccer-anytime-scorer]`

- **What happened.** From the `soccer-player-role-allocation` worktree, with a ledger commit ready, I ran `land --lane soccer-anytime-scorer` because my per-session marker had just moved to that lane. It pushed the OTHER worktree's branch: `04b907a0`, the producer-half shrink whose H19 was FALSIFIED and which was deliberately unlanded. My ledger commit stayed local.
- **Why it reads as success.** The tool printed "pushed session/soccer-anytime-scorer -> main" and, on the retries, "nothing to land -- no commits beyond origin/main" — both true statements about a branch I had not written. Only a verification that grepped for MY OWN subject on `origin/main` caught it.
- **How to apply.**
  - `--lane` selects a BRANCH. Before landing, read `git rev-parse --abbrev-ref HEAD` in the worktree and pass the lane whose branch that is — the lane marker governs edit permission, not what gets pushed.
  - Verify a land by the COMMIT, not by the push line: `git merge-base --is-ancestor <your sha> origin/main`. A subject grep also fails when the push succeeded but pushed someone else's commit.
  - After an accidental land, measure the exposure window against every service that can ship main — the long-running services AND the crons, which build the branch tip when they fire — before saying nothing shipped.
- *(evidence: `log/2026-09-15.md` 18:05 CT entry; `04b907a0` and its revert `d2d7b398`; the Render deploys read at 23:02Z)*
## 2026-09-15 — OVERTURNED: "adding a sport to `SYNDICATE_ACTIVE_SPORTS` is a config change" — on WEB it is a REQUEST-PATH code-path flip, and this exact one has an outage on record `[lane web-dashboard-prop-dates-quotes]`

- **What I was asked, and nearly did.** "add ncaaf to web's active sports" — a one-key env write plus a deploy. The key is not declared in `render.yaml`, no lane claimed it, and the blast-radius question I started with was the usual one (would `blueprint_sync` revert it, does it move worker sweep ownership). Both answers were reassuring.
- **What the list actually gates on web.** `build_home_overview` filters to `_active_sport_slugs()` and then BUILDS each surviving sport inside the request (`home.py:8305`). For NCAAF that is `_NCAAFDataProvider.games(...)` without `include_upcoming` — `build_smartsim_cards_page_context(week)` **plus** `build_ncaaf_market_board(week)` (`home.py:6709-6713`), measured at 6.4 s warm for 51 games on a 2 GB display-only service.
- **It has happened.** `deploys.md` 2026-08-29 12:18 CT: when a resolver fix made that path reachable, `/` went **3.5 s -> 37.9 s**, `/ncaaf/cards` 502'd and `/api/ops/memory` 502'd; revert `0163f904` restored it. The repair that followed (`fccd923d`) made only the CHIPS path light (`build_ncaaf_chip_games`, 0.23 s warm), so the home path is still the heavy one today.
- **And the payoff was nil:** nothing under `syndicate/` fetches `/api/home` (only `tests/` and the run-syndicate skill), and `/` renders the Layer 2 board. The NCAAF surfaces users see do not read this key.
- **How to apply.**
  - Before flipping any list-shaped env var, find what the list GATES. A membership test in front of a builder is a code path, not configuration.
  - Grep the ledger for the last time that value changed on that service. An outage with a revert is usually already written down.
  - Ask what would become observable. If no served surface reads the thing the flip enables, the change is cost with no reading to verify it by.
- *(evidence: `home.py:691/8305/6709-6713`, `deploys.md` 2026-08-29 12:18 CT and 12:46 CT; `/api/home` read 2026-09-15 22:31:13Z; user decision "Don't add it")*
## 2026-09-15 — OVERTURNED: "`git diff | grep '^-[^-]'` lists the lines a change removes". It SKIPS every removed line that itself starts with `-`, which on a bulleted ledger is most of them `[lane soccer-live-scoreboard-range-stale]`

- **What happened:** re-applying a lane-block edit onto a moved `main`, `--numstat` said **9** deletions while the grep listed **6**. The 3 it hid were ordinary ledger bullets (`- **VERDICT ...`, `- Files: ...`, `- Blocked by: ...`): in a diff they read `-- Files: ...`, and `^-[^-]` rejects them.
- **Why it matters here:** the standing rule on a shared ledger is "0 deletions, and every deletion is mine". A grep that under-counts deletions makes that check pass while another lane's lines are being dropped.
- **The rule:** count deletions with `--numstat`, and list them with `grep -E '^-' | grep -v '^---'`. Reconcile the two numbers before staging; if they disagree, the listing is wrong, not the count.
  - *(evidence: this session's 22:4xZ re-sync; `git diff --cached --numstat` 2/2 on `lanes.md` after the reconciliation)*
## 2026-09-15 — FORBIDDEN: gating a ledger commit on a SHELL `grep` filter over diff lines, and reading a dot-prefixed `rev:path` answer from Git Bash as fact `[lane fotmob-join-coverage-check]`

Three instrument failures in one session, two of them inside the guard that was
supposed to protect a ledger commit.

- **A `grep -v "^[-+][-+]"` filter meant to drop diff headers also dropped `+- `
  and `-- ` lines** — markdown bullets, which is what `leads.md` and `lanes.md`
  are made of. The gate printed a single blank `+` and was blind to the very
  lines it existed to check.
- **A deletion guard reported 2 "unexpected" deletions in `state_ledger.md`**
  that were a blank line and an em-dash line the shell could not match. The
  staged content was correct. Re-checking the SAME staged diff in Python passed,
  and the commit went through.
- **`git cat-file -e origin/main:.github/...` and `git show
  origin/main:.syndicate/...` from Git Bash said two landed files were ABSENT
  from `origin/main`.** MSYS rewrites `origin/main:.syndicate/x` into
  `origin\main;.syndicate\x`. Only DOT-PREFIXED paths were affected, so
  `scripts/...` in the same loop answered correctly — a partially working
  instrument is the convincing kind, and it briefly read as "the land lied".

**How to apply.**
- Verify a staged diff in PYTHON, comparing against the exact expected line set.
  A `grep -v` chain over `git diff` output is not a gate; it is a filter whose
  failure mode is silence.
- Read any `rev:path` through `subprocess` from Python (or PowerShell). Never
  from Git Bash. This is the same rule as `feedback_git_bash_mangles_rev_path_args`,
  now with a second shape: a false ABSENT rather than a false empty.
- When a check answers ABSENT or none for SOME paths and correctly for others,
  suspect the instrument before the repository, and re-read with a different one.
- *(evidence: this session's `state_ledger.md` guard output and the `origin/main`
  re-read in `.syndicate/log/2026-09-15.md`)*

### REFINEMENT (same session, 23:43Z): verifying a land by the ancestry of the sha you held BEFORE landing gives a FALSE NEGATIVE

The rule above says to verify a land by the commit rather than the push line, and `git merge-base --is-ancestor <sha> origin/main` is how I implemented it. That check is correct only when `land` fast-forwards.

- Measured 23:42Z: the checkpoint commit pushed successfully (`64496c36..585106a7`), and my check reported NOT LANDED three times, because `session_worktree.py land` REBASES onto the fetched tip first. The rebased commit has a different sha, and the sha I was holding no longer exists on any branch.
- The retries then printed `nothing to land -- no commits beyond origin/main`, which was the true state and the signal I should have read.
- **How to apply:** verify a land by CONTENT or by the commit SUBJECT on `origin/main` (`git show origin/main:<path>` and look for your marker; or `git log origin/main --grep`), and treat `rev-list --count origin/main..HEAD == 0` as corroboration. Keep the sha check only for the fast-forward case, and never report NOT LANDED on its evidence alone.
- This is the mirror of the mid-rebase FALSE POSITIVE recorded earlier today: one check lies while a rebase is in progress, the other lies after a rebase completes. Both are fixed by asking about the content, not the identity.

### 2026-09-15 (session a1e40980, lane `soccer-live-scoreboard-range-stale`) — FORBIDDEN: reading a green test as evidence of the property it NAMES, when its fixture and the code could share the same mistake

`tests/test_soccer_cards_context_cache.py` exists to prove one thing, and says so itself: *"`test_a_live_score_change_invalidates` is the load-bearing one. If it ever goes green with the vintage removed from the key, this cache has become the bug it was written to avoid."* It was green for two weeks over exactly that.

- `_live_vintage` fingerprinted `entry.get("home_score")` / `away_score`. Every real entry carries `score_home` / `score_away` — `build_live_state` writes it (`espn_live_state.py:180`) and the poller copies ESPN's `home_score` INTO it (`poll_soccer_live_state.py:178`). The score was absent from the key.
- The fixture `_live()` wrote `home_score` too. So the test agreed with the code, the code agreed with the test, and **neither agreed with any bytes production has ever produced**. The assertion did fire — on a field the cache would never see.
- It survived because the fingerprint ALSO carries the clock, which moves every poll. The defect was therefore bounded at one displayed minute instead of the 600 s TTL, and never presented as the freeze that would have exposed it.
- **How to apply:** a test whose fixture is hand-written asserts that the CODE agrees with the FIXTURE. To make it assert anything about production, the fixture's field names must come from the writer — cite the writing line — or the test must run the writer. When a suite declares a test load-bearing, check what its fixture is made of before trusting the claim; and when you fix a name like this, do NOT keep the old one as a fallback, because a reader that accepts both preserves exactly the ambiguity that hid it.
- Same family as *a fixture can pick a cheaper path than production* and *presence is not reachability*: the instrument was measuring itself.
- *(evidence: `test_a_live_score_change_invalidates` FAILS with the fingerprint reverted to `home_score` against the corrected fixture, passes with `score_home`; `.syndicate/log/2026-09-15.md`, commit `116690a8`)*
## 2026-09-15 -- A FALSIFIER IN THE WRONG UNIT KILLS A LIVE HYPOTHESIS, and the retraction looks rigorous while it happens

Lane `polymarket-rejected-resubmit-loop` wrote: "H2 (insufficient buying power) dies if the account's available balance covered $1.60 at a
rejected submit." It did -- flat at $2.84 across all 34 rejections -- so I recorded H2 as DEAD BY ITS OWN FALSIFIER, which is the strongest
form of retraction this ledger has.

**H2 was right.** The venue checks a NO order against $1.00 per contract, so the number that had to be covered was $6.53, not $1.60. The
falsifier was written in NET dollars against a venue that checks GROSS. Everything downstream was correct reasoning on the wrong unit, and
the error was invisible precisely BECAUSE the falsifier fired cleanly.

- **STANDING RULE: a falsifier must name its UNIT, not just its threshold.** "balance covered the stake" is not a test until "stake" is
  pinned to cost, notional, payout or margin. Where a venue or API could plausibly mean a different one, write the falsifier for EACH and
  say which reading kills the hypothesis.
- A hypothesis killed by its own falsifier deserves the same scepticism as one confirmed by its own prediction. Both are self-graded.
- Same family as *read the field you already have* and *a rate, not a count*: the arithmetic was never wrong, the denominator was.
- *(evidence: `.syndicate/state_polymarket.md [polymarket-no-fill-size-is-gross-capped]`; commits `ce64e639` -> `16c7d919` -> `a8668557`,
  which are the overclaim, the over-retraction, and the table that settled it)*
## 2026-09-15 -- `finishedAt` IS NOT WHEN THE OLD INSTANCE STOPS WRITING

Lane `legacy-steam-crossing-delta` measured soccer steam events **38 s AFTER its deploy went live** that were still written by the OUTGOING
instance, in the old format. A post-deploy window that starts at `finishedAt` therefore contains old-code output at its head.

- **STANDING RULE: when a reading starts at `finishedAt`, discard or separately label the first minute** -- an old-format line there is
  evidence of an overlap, not of a failed fix. Gate the verdict on lines comfortably after the boundary.
- The inverse error is worse: crediting the NEW code with output the OLD instance produced. That lane retracted an attribution for exactly
  this reason -- its 200 events were stamped 66 s after a second service's deploy, so they could not identify which service wrote them.
- Extends *gate verification on artifact mtime*: deploy live is not code live, and code live is not old code STOPPED.
- *(evidence: cross-session reports from lane `legacy-steam-crossing-delta`, 2026-09-15 ~23:35Z and its retraction ~23:55Z;
  `.syndicate/log/2026-09-15.md`)*
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
## 2026-09-15 -- A LANE BLOCK CAN CONTRADICT ITSELF, and the STALE half is the one that reads like an instruction

I recommended deploying `57b67127` because lane `book-quotes-prefer-fuller-copy` said **"STATUS 2026-09-13 ~19:25Z: LANDED on main, NOT
DEPLOYED."** The user approved it. It was already live on all three services, and had been for a day -- the SAME BLOCK, further down,
carried a 2026-09-15 verdict describing the production reading taken after that deploy.

The stale line won because of its SHAPE: "landed, not deployed" is an action item, and a verdict paragraph is prose. Scanning a 16 KB block
for what to do next surfaces the imperative and buries the correction.

- **STANDING RULE: `deploy state` is never read from `lanes.md`. Read it from the SERVICE.** Before proposing or running any deploy, test
  ancestry of the commit against the LIVE commit on each target service (`git merge-base --is-ancestor <sha> <live-sha>`, live SHA from the
  Render deploys API). It is two commands and it is the only source that cannot be stale.
- **A deploy that would be a no-op must be caught BEFORE approval is sought**, not after it is granted. Approval spends the user's trust on
  a decision that was never real, and an approved-but-pointless deploy still restarts a service and kills in-flight work.
- When a block holds two statements about the same fact, the NEWER one wins and the older must be rewritten in place -- not left below it.
  This is the same failure `learnings.md` records for `state.md` ("overwrite the stale line; do not stack contradictory lines"), appearing
  in `lanes.md` instead.
- Same family as *primary tree is not deployed code* and *test the fix's predicate, not its deploy state*: the ledger describes the world, it
  is not the world.
- *(evidence: `57b67127` an ancestor of web `4f65f2b2`, refresh-worker `1175e0ef`, live-odds-worker `88df44cd`, read 2026-09-16 03:20Z; the
  contradicting verdict is in the same lane block, dated 2026-09-15 ~11:25 CDT)*
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
