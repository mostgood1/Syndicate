# state — ledger

Split out of `state.md` by `scripts/split_state.py`. Bodies are verbatim.
The INDEX of every subject, across every part, is in `state.md`; the
one-subject-one-section rule is global and spans these files.
Same rules as state.md: when a fact changes, EDIT THE LINE.

## [state-file-split] state.md IS AN INDEX PLUS NINE PARTS `[2026-09-03, scripts/split_state.py, commit 23bf6bc7]`

**Read `state.md` first, then open only the part your work touches.** It holds
the cross-cutting subjects and the `[subject-index]` table naming every subject
and its file. Bodies live in `state_<domain>.md`: mlb, soccer, football,
basketball, venues, polymarket, kalshi, board, ui, layer2, portfolio, worker,
model, ledger.

    state.md   746,526 -> 62,510 B      largest part  state_venues.md 152,212
    total across ten files  774,933 B   -- the split ADDED ~28 KB of part
                                           headers and index rows

**COMPACTION WAS MEASURED FIRST AND REJECTED ON THE NUMBERS.** Of ~746,500
chars only **1,460 (0.2%)** was reclaimable superseded prose, and all 8
remaining candidates were audited by hand and found NOT archivable -- six had
no dead body (the superseded claim was deleted when its correction was written
and survives only as a quotation inside it), two keep their old block on
purpose and say so. This file is not bloated, it is BIG, because it is live
current truth. Do not send anyone hunting fat here again.

**ONE SUBJECT, ONE SECTION IS NOW GLOBAL.** `state_key_check.py` pools slugs
across state.md + every part (archives excluded, they legitimately repeat a
slug). The commit guard `ledger_invariants.py` checks each file SEPARATELY and
**cannot see a cross-file stack** -- that gap is covered only by
`state_key_check.py` in session-start's coherence loop.

**Adding a subject to a part means adding its index row:**
`py -3 scripts/split_state.py --reindex --apply`. Plain `--apply` REFUSES once
the index exists -- re-splitting would rewrite the index to cover only what is
left in state.md and orphan the parts.

Budget alarms are three now, not one (`session-start.sh`): index 120,000,
per-part 250,000, total 1,100,000. The old single 920,000 cap could not fire
after the split -- state.md would sit at 7% of it forever while a part grew
unbounded.

## [session-harness] SESSION HARNESS — what the hooks actually enforce

- **`lane-guard` STRIPPED THE LEADING DOT until 2026-08-31, so every claim under
  `.syndicate/` or `.claude/` guarded NOTHING** — `.syndicate/x.md` parsed to
  `syndicate/x.md` and matching is `rel.endswith("/" + f)`, which can never
  match. Fixed asymmetrically (right side keeps the original strip set, left
  side drops the dot). Audited before applying: no shared ledger among the
  affected claims, so no session newly blocks on ledger writes.
- **`py -3 scripts/lane_claim_audit.py` is the one tool for "what does the guard
  actually claim".** It loads the hook by AST (running it blocks on stdin) and
  applies BOTH checks, because either alone misses half: a token that does not
  look like a path (prose written inside a `- Files:` block becomes a claim —
  `1/p`, `15.0` and a bare `/` all did this in one day), and a path absent from
  `git ls-files` (the dot-strip class, which looks well-formed). **Run it from a
  worktree pinned to `origin/main`** — the shared primary tree drifts behind and
  reports live files as phantom. `check_lane_invariants` catches neither: one
  holder per claim is true of a claim that guards nothing.

- **THE CLAIM PARSER HAS ONE DEFINITION: `.claude/hooks/lane_claims.py`**
  `[verified 2026-09-04, lane lane-invariant-single-source, 312c93a9, NO DEPLOY]`.
  `lane-guard.py` imports it, and `scripts/check_lane_invariants.py` now does
  too -- it used to carry frozen copies of four regexes and the 14-marker tuple,
  pinned against `lane-guard.py`'s SOURCE TEXT by a test. **That test had been
  silently red since the parser was extracted** (it searched the hook for
  definitions that had moved), and with it 8 more in
  `test_lane_guard_dot_directory_claim.py` and 1 in
  `test_lane_guard_prohibition_marker.py` -- **14 across three files, all bound
  to the hook's pre-extraction shape**, while the checker still exited 0 and
  printed INVARIANTS HOLD.
  **The regexes had NOT drifted; four unpinned behaviours had.** Measured on one
  adversarial ledger: the OLD checker read **1 OPEN lane / 1 claim** and printed
  `INVARIANTS HOLD` exit 0 against a file that held a CONTESTED path AND a stray
  OPEN lane under `## Archived lanes`; the new one reads **3 lanes / 4 claims**
  and reports both, exit 1. The severe case is a `- Files:` line naming
  `scripts/archive_released_lanes.py` -- a filename CONTAINING the marker
  "released" -- which yielded the checker ZERO claims for that lane, so it could
  contest nothing and the one-holder invariant passed vacuously.
  Consequence to hold onto: **`is` does not prove a regex was not copied.**
  `re.compile` memoises, so a re-pasted pattern returns the other module's own
  object and an identity assertion passes -- verified by mutation, the copy went
  in and all 30 tests stayed green. `test_the_checker_defines_none_of_them_itself`
  asks the AST for the ABSENCE of a second definition, which is the form that
  survives the next refactor of the hook.

- **THE LEDGERS ARE KEYED AND CHECKED** `[verified 2026-08-18]`. One checker per
  ledger, all three ENFORCED in CI and reported at session start as
  `LEDGER INCOHERENT`: `scripts/lane_identity_check.py` (slug, one OPEN block,
  one home), `scripts/todo_id_reconcile.py` (numeric id in exactly one of
  `todo.md`/`todo_closed.md`), `scripts/state_key_check.py` (every `## [slug]`
  unique). All three verified to EXIT 1 on deliberately corrupted copies before
  being wired in — the gate is not vacuous. Green at checkpoint: lanes 54 blocks
  coherent, state 35 sections/35 subjects, todo 166 ids.
- **`state.md` sections carry a subject key** `## [subject-slug] TITLE`. One
  subject, one section; a shared slug IS the stacking failure. Added because "no
  duplicate titles" was trivially true while sections were titled by date.
- **`lane-guard.py` reads BOTH Files forms and wrapped continuation lines**
  `[verified 2026-08-18: file-like claims 52 -> 80]`. It previously matched only
  `- Files:`, so 5 lanes using `- **Files (...):**` declared paths NO HOOK COULD
  SEE. A disclaimer now governs only what FOLLOWS it, not the whole line.
  `_DISCLAIMER_MARKERS` gained `"not touch"` (covers "does not touch"/"not
  touch"/"not touched" — subsumes the prior "not touched" entry),
  `"read-only reference"`, and `"not taken"` `[verified 2026-08-19, commits
  0a7fdbeb + f52fc91b + a1cbcde1, all on origin/main]`; each closed a real
  false-positive that had blocked a lane from a file its own ledger text
  explicitly disclaimed. `"not taken"` is a NEW failure shape, not a repeat:
  a lane correctly got blocked from a file it did not own, recorded that
  block as its own disclaimer ("BLOCKED, not taken: ..."), and THAT SENTENCE
  then re-read as a phantom counter-claim, blocking the file's actual,
  correctly-enforced owner from editing their own file — a disclaimer about
  the guard's own prior correct enforcement, not about a file the writer
  never touched.
  Claim matching is exact-or-suffix (`rel == f or rel.endswith("/"+f) or
  f.endswith("/"+rel)`), never a directory prefix — so a non-path token claimed
  out of prose is INERT.
- **`lane-guard.py` (PreToolUse) enforces.** Blocks `Edit`/`Write` against a file
  claimed by another OPEN lane (exit 2); allows it when `.syndicate/.current-lane`
  names the claiming lane. **With the marker empty it blocks your OWN lane's
  files**, reporting `Current lane: 'none'` — so a session that hand-edits
  `lanes.md` instead of running `/lane` locks itself out.
- **`Bash` is not BLOCKED, but is no longer UNSEEN** `[updated 2026-09-04,
  verified, session f97ad5ab]`. `lane-guard`'s matcher is still
  `Edit|Write|MultiEdit|NotebookEdit`, so a shell write cannot be REFUSED —
  predicting a file write from a command STRING is not reliably possible, and a
  guard that blocks on a guess gets routed around. `lane-postwrite-check.py`
  (Pre+PostToolUse on `Bash|PowerShell`) DETECTS it instead: it snapshots
  `(mtime,size)` of paths claimed by OTHER open lanes before the command and
  compares after, so the window is ONE TOOL CALL. It WARNS, never blocks.
  **Scale of the gap, measured over all 292 session transcripts:** writes to
  tracked SOURCE files ran 9,023 Edit-family vs **1,045 Bash/PowerShell
  (10.4%)**; under `.syndicate/` the shell is the MAJORITY path (2,618 vs 1,069).
  **Two limits, both real:** a `git rebase`/`checkout` is suppressed by a
  HEAD-move check, but a concurrent session's UNCOMMITTED write to a claimed file
  is indistinguishable from your own — observed once, live — so it names no
  author.
- **A COMMIT CANNOT REVERT A LEDGER COMPACTION** `[2026-09-04, verified]`.
  `ledger_invariants.resurrected_lines()` refuses a `lanes.md` carrying lines
  upstream moved to `lanes_history.md`. `resurrected_blocks` was blind to it --
  `a8000faf` compacted WITHIN blocks (203,047 -> 84,956 B), so no block read as
  resurrected and `violations()` returned 0 on a stale copy whose commit would
  have restored 1,308 lines. Same shape `_deploys` already refused on its file.
- **A DESTRUCTIVE `git checkout` IS NOW GATED** `[2026-09-04, verified]`.
  `discard-guard.py` (PreToolUse `Bash|PowerShell`) refuses `checkout -- <path>`,
  `restore` and `reset --hard` when the working file holds non-blank lines in
  neither the incoming version nor `HEAD` -- i.e. content with no other copy.
  Before it, that command was allowed by EVERY hook here and had destroyed an
  uncommitted lane block once and nearly a second time. The predicate is
  "exists nowhere else", NOT "has deletions": a deletions count is structurally
  blind to an uncommitted ADDITION, which is what both incidents lost.
- **A CLAIM OUTLIVES ITS SESSION FOREVER — the guard has NO liveness notion**
  `[verified 2026-08-29T23:2xZ, lane lane-claim-phantom-sweep]`. Nothing released
  a claim when a session ended, so they accumulated: **26 OPEN lanes holding 133
  claims while 3 sessions were alive**, 121 of them (91%) enforced on behalf of
  sessions that no longer existed, plus 56 `.current-lane.<session>` markers for
  4 live sessions. Already paid for once the same day — `live-venue-order-placement`
  needed a USER OVERRIDE to take `venue_quote_adapters.py` off `kalshi-line-aware-rungs`,
  whose session was gone. **A header reading "OPEN, UNOWNED" or "CLAIMS RELEASED"
  releases NOTHING**: the guard parses the `- Files:` block and never the
  header's prose. Sweep with `py -3 scripts/release_phantom_lane_claims.py`
  (dry run by default; verifies against `lane-guard._claims()`, keeps every path
  as a record). Post-sweep state: claims held ONLY by live sessions' lanes.
  Verified off != on against the hook itself, not against a claim count —
  `scripts/build_soccer_artifacts.py` and `syndicate/features/ncaaf/sources.py`
  went exit 2 -> exit 0 while a live lane's `venue_quote_adapters.py` stayed
  exit 2.
- **A HOOK THAT RESOLVES PATHS AGAINST `CLAUDE_PROJECT_DIR` IS ANSWERING ABOUT
  THE WRONG REPOSITORY** `[verified 2026-08-20, shipped 58c63b62]`. Every session
  works in its own linked worktree, so `CLAUDE_PROJECT_DIR` is the PRIMARY
  checkout while the tool call targets the worktree. Both failure directions were
  MEASURED: `ledger-commit-guard.py` blocked a `soccer-board-mlb-parity` commit
  over duplicate lane blocks that existed only in the primary tree (its own
  `lanes.md` was clean, `check_lane_invariants.py` said INVARIANTS HOLD), and it
  had never once examined a broken `lanes.md` in the committing worktree.
  `ledger-append-guard.py` was worse — **fully INERT in every worktree**:
  identical violating edit gave `primary exit=2 BLOCKED` / `worktree exit=0
  ALLOWED`, because `relpath(file, PRIMARY)` is `../../../../../tmp/...` and
  matched neither ledger name. **An inert guard and a satisfied guard are
  indistinguishable from outside**, which is why it survived unnoticed.
  `commit-guard.py` had already been fixed for this on 2026-08-16; the fix was
  local to that file, so the next guard written re-made it. Shared resolver now
  in `.claude/hooks/commit_context.py`.
- **A `VAR=1 <cmd>` OVERRIDE PRINTED BY A PreToolUse HOOK IS UNREACHABLE UNLESS
  THE HOOK PARSES THE COMMAND STRING** `[verified 2026-08-20]`. The hook runs
  BEFORE the shell assigns it, so `os.environ` never sees it. Same defect
  `commit-guard.py` fixed 2026-08-17; `ledger-commit-guard.py` shipped with the
  broken form and printed an escape hatch that did not exist. A real exported
  environment variable always worked.
- **`lane-guard.py` is NOT affected, and the reason is accidental**
  `[verified 2026-08-20]`. A worktree path yields the same mangled relpath, but
  claim matching is exact-or-suffix (`rel.endswith("/" + f)`), which matches it
  anyway. It blocks correctly; only its refusal MESSAGE prints the
  `../../../../../tmp/...` form. Do not "fix" it by changing `root` — for
  lane-guard the PRIMARY `lanes.md` is the CORRECT source, because cross-session
  claim exclusivity is inherently global. That is the opposite of
  `ledger-commit-guard`, which must read the tree being committed.
- **`ledger-postwrite-check.py` FIXED** `[verified 2026-08-20, `f73d163e`]`. It
  now watches the worktree the command ran in AND the primary checkout, deduped
  to one scan when they are the same, with per-tree state so neither silences
  the other. It had been blind to worktree Bash writes — **the one thing it
  exists to catch** — and it blamed whichever session happened to observe the
  change (seen firing at a `grep`). It reports that a file CHANGED and is
  broken, says it may be another session, and NAMES THE TREE. Two things the
  work turned up, both measured: `abspath` does not expand Windows 8.3 short
  names, so the same tree deduped as two and was reported twice (caught by a
  "reported exactly once" assertion, not by inspection); and finding the root
  via `git rev-parse` costs **41ms on EVERY Bash call** vs **0.0ms** for a
  filesystem walk to the directory holding `.syndicate/lanes.md` — same answer,
  so the walk is used. End-to-end 162ms → 106ms, ~100ms of it Python booting.
- **ALL FOUR HOOK SUITES ARE ENFORCED IN CI** `[verified 2026-08-20 on the
  Linux runner, `86ec6b42`, run 32415246596 green in 3m18s]`: 16/16, 17/17,
  16/16, 10/10. Enforced, not `continue-on-error`, because each was
  **mutation-tested** first — disable the predicate under test and every suite
  goes red, so a green run means the guards work rather than that the suite is
  vacuous. All four build throwaway repos under the OS temp dir; they are
  stdlib-only, shell-free and need no repo history, so CI's shallow clone cannot
  bite them the way it does `todo_id_reconcile`. **They never read the live
  ledger** — the first version did, and a parallel session trimming real
  duplicates mid-run flipped three cases from pass to fail.
- **`lane-guard` is blind to `.claude/**` AND `.syndicate/**` by design**
  (`lane-guard.py:244`, one `rel.startswith` test covering both), so the
  enforcement layer cannot protect the directory it lives in — and every real
  collision has happened there. **The `.syndicate/**` half matters just as much
  and was missing from this line until 2026-08-18:** no lane claim can ever
  guard `lanes.md`, `state.md`, `deploys.md` or `learnings.md`, so concurrent
  ledger writes are unprotected by design and a phantom claim on a ledger file
  is inert rather than a lock. Measured during the 2026-08-18 orphan sweep:
  `basketball-model-owner`'s Files block claims bare `lanes.md` (a prose
  collision-check sentence the parser reads as a claim) and it blocks nobody —
  while an unrelated session's write to `lanes.md` landed **between** two of
  that sweep's own edits, reported by the Edit tool as "modified on disk since
  you last read it". Anchor ledger edits on unique strings, never on line
  numbers, and re-read before any edit that depends on surrounding content.
- **`commit-guard.py` (PreToolUse) reads the index the COMMIT will use, fixed
  `a52a2b64` 2026-08-16.** It previously evaluated both predicates against
  `CLAUDE_PROJECT_DIR` — the MAIN worktree — while the commit runs wherever the
  shell is, which for this repo's own contended-tree recipe is a LINKED worktree
  with its own index and its own HEAD. **It blocked three clean commits in one
  session**, and, the half that matters, **would have passed a stale index in the
  worktree actually being committed from without a word.** Now resolves
  `cd` → `-C` → payload `cwd` → project dir, then `rev-parse --show-toplevel`.
  `git -C <dir> commit` is CHECKED (it was skipped for "has its own index";
  having your own index is not having a fresh one). **`--git-dir` /
  `--work-tree` remain a KNOWN GAP** — index and tree decouple, so "is it still
  on disk" has no single correct base. 13 tests on real repos
  (`tests/test_commit_guard_worktree_index.py`); pre-fix 7 fail, post-fix 13 pass.
- **`commit-guard.py` reads the COMMAND, not a proxy for it, fixed `5fb52342`
  2026-08-17.** Two exemptions, both measured:
  (a) **all THREE documented overrides were unreachable.** They were
  `os.environ.get(...)` — the HOOK's env — but a PreToolUse hook runs BEFORE the
  shell, so the `export GIT_INDEX_FILE=…` in the recipe the guard PRINTS, and
  the `SYNDICATE_ALLOW_STAGED_*=1 git commit` prefix it prints as the override,
  were both invisible to it. A session that followed the refusal message was
  refused again. Assignments are now parsed out of the command string,
  last-write-wins against `unset`.
  (b) **a pathspec-limited commit is exempt whole.** MEASURED 2026-08-17 against
  an index holding a revert of `A.txt` plus a `D` of on-disk `C.txt`:
  `git commit -m x -- C.txt` produced a tree keeping BOTH, `--stat` 1 file;
  `--pathspec-from-file=` and `--amend -- <paths>` likewise. A partial commit
  builds from HEAD plus the WORKING TREE content of the named paths and never
  consults the index — not even for the named paths — so there is no path left
  to evaluate. **`-i`/`--include` NOT exempt** (the revert landed).
  **`-a` NOT exempt** (it kept the line but COMMITTED the deletion, so predicate
  1 is live under it); `-a` remains a known false positive for predicate 2,
  left alone because `-a` does not refresh `skip-worktree`/`assume-unchanged`
  and that case is unmeasured. Unrecognised options fall through to "keep
  guarding" — false positive, never false negative. Verified by running 19 cases
  through the pre-fix and post-fix guards together: 10 flip 2→0, 8 hold at 2.
  **62 tests in `tests/test_commit_guard_worktree_index.py`** (69 for the
  two-file run that also covers `test_checkpoint_guard_hook.py` — cite the 62 if
  you mean this guard); exemption path 81 ms, short-circuiting before any git
  call.
- **A PATHSPEC COMMIT NEEDS NO REPAIR STEP; THE ISOLATED-INDEX RECIPE DOES.**
  Measured on `5fb52342`: the partial commit UPDATED the shared index for the
  three paths it committed (`git diff --cached` for them empty afterwards) and
  left another session's staged work untouched. The isolated-index route, by
  contrast, is recorded in `learnings.md` 2026-08-15 as arming a revert of the
  file you just committed, every time, requiring a follow-up
  `git restore --staged`. The guard's refusal message now leads with the
  pathspec form for this reason.
- **`commit-guard` matches the COMMAND STRING**, so bundling a file write or a
  `git reset` into the same command as `git commit` blocks the whole thing.
  Separate them. `[recorded by another lane 2026-08-16]`
- **THE ARCHIVE PASS ITSELF CREATES ORPHANS, and that is a second mechanism, not
  a repeat of the one below.** Moving a CLOSED lane to `lanes_closed.md` takes
  the header and whatever body existed AT THAT MOMENT; any bullet the owning
  session appends afterwards lands in `lanes.md` with no header above it and is
  silently adopted by whichever lane precedes it. Measured 2026-08-15: two
  blocks of `model-audit-devig-and-hygiene` ended up under
  `nfl-live-edge-suppression` and `live-game-line-projection`, and **a later
  collision check therefore reported a FALSE claim on
  `scripts/backtest_mlb_props.py`** — the guard reading a real file claim that
  belonged to nobody. Reconciled 2026-08-15; line arithmetic verified exact.
  **When archiving, re-check the source lane for appends made after the move,
  and when a collision check names a file, read the matched text before trusting
  the slug it is attributed to.**
- **A lane's guard state hangs on ONE header line in a hand-edited shared file,
  and its deletion is silent.** A header once vanished while its body stayed, and
  all 4 of that lane's claimed files went to exit 0. Nothing detected it; it was
  found by reading a diff. Both hooks now take the field between the 1st and 2nd
  em-dash and match the WORD `OPEN` in it.
- **`checkpoint-guard.py`'s witness is this session's OWN transcript;
  `.last-checkpoint`'s mtime is never read.** The marker is repo-global, so its
  mtime answers "did somebody checkpoint", not "did I" — reading it let session
  A's checkpoint silence session B's warning, losing B's work silently.
  `.syndicate/**` is excluded from work-at-risk: it is the persistence, not the
  thing persisted. **Exit 1 on Stop is advisory**, not a gate.
- **The 3-lane cap in policy has no enforcement** — `/lane open` checks file
  collisions only and never counts. Eight lanes are open today.

---

## [worktree-test-data] THE 92 RED TESTS IN A SESSION WORKTREE ARE THE ENVIRONMENT, NOT DEFECTS `[measured + shipped 2026-09-03]`

A default session worktree excludes `data/`, and **92 tests fail for that alone**
— established by holding the code constant and varying only the mirror's
presence, then re-checking each candidate IN ISOLATION (2 of the original 103
were test-pollution, not data-dependence).

**They must not be stubbed or skipped.** Their SUBJECT is the data;
`test_ncaaf_team_registry_reachability` states it — *"a value assertion over a
fixture cannot catch either; the fixture is the thing that lied"*. Skipping their
modules would drop **601 PASSING tests**, 353 in `test_archives.py`, the file CI
runs.

**`SYNDICATE_DATA_ROOT` does NOT reach them.** Nine read `REPO_ROOT/data`
directly and ignore the variable — which is why a differential built on that env
var could not see them. Only a real checkout does.

    python scripts/session_worktree.py open --lane <slug> --with-test-data

|  | files | MB |
|---|---|---|
| `--with-data` (full mirror) | 34,690 | 3,547.5 |
| `--with-test-data` | 6,013 | 2,071.2 |

Verified in a FRESH worktree: the 24 files carrying all 118 sweep failures run
**1,031 passed / 0 failed**. Opt-in, because 2 GB across 20+ worktrees is real
disk.

**A METHOD TRAP:** with `data/` present the TEST IDS THEMSELVES CHANGE — several
parametrized tests derive params from the alias map, so an id list captured
without `data/` returns `no tests ran` with it. **Compare by FILE, never by node
id.**

## [test-baselines] TEST BASELINES

- **`tests/test_intelligence_state.py` — `224 passed, 10 subtests passed, 0
  failed in 1361.70s`** `[measured 2026-08-20, lane intel-empty-pool-fallback-test,
  todo.md #495]`. **It costs ~23 minutes, NOT the ~15 this line used to say.**
- **READ THE NEXT TWO BULLETS BEFORE QUOTING THAT NUMBER.** This entry said, for
  six days and in bold, that the file *is NOT "224 green" — that line was wrong
  and is corrected here.* It is now 224 green again. **That is not a reverted
  correction and must not be tidied into one** (`learnings.md` 08-20 forbids
  re-applying a ledger edit by restoring an old revision). The 08-14/15 refutation
  was RIGHT when written; both failures it named have since been resolved on their
  merits:
  - `..._fallback_merge_falls_back_on_empty_pool` — **fixed 2026-08-20**. The TEST
    was the stale side: it asserted a `force_refresh` kwarg `#387` deliberately
    removed from the `collect_all_recommendations:empty_fallback` call site. The
    branch under test had been behaving correctly the whole time. `todo.md` `#495`.
  - `..._recomputes_when_cached_snapshot_is_stale` — **passes on `main`**,
    re-measured 2026-08-20 (72s), individually, not inferred from a suite total.
    Cause of its recovery not investigated.
- **LINEAGE CAVEAT DISCHARGED — this number IS a tip-of-`main` reading.**
  Re-measured at `56b4dd41` (tip): **`224 passed, 10 subtests passed, 0 failed in
  1668.24s`**, identical pass/fail to the first run, which was taken on the primary
  tree's lineage (`d2222426` + the fix), 30 commits behind. **The 34 commits of
  product code between them change nothing for this file.**
- **The COST figure is the one thing that moved: 22:41 then, 27:48 now.** Read
  **~25-30 min**, not ~23. Other sessions were writing the shared `data/`
  throughout both runs, so load is the likely cause — **not isolated, not
  claimed.**
- **HOW the tip run was taken, because a naive re-run would NOT have been valid.**
  `learnings.md` 08-16 forbids a fresh `git worktree` as a baseline for anything
  that reads `data/`, and this suite DOES reach the real disk (`tests/conftest.py`
  isolates `data/prediction_ledger.json` precisely because tests were writing it
  through `data_root()`). So: worktree at tip, sparse-checkout of every top-level
  dir EXCEPT `data/`, and `data/` supplied as a **junction to the primary tree's
  `data/`** — the same bytes the first run used, making the product code the only
  delta. **`SYNDICATE_DATA_ROOT` alone would have been WRONG:** `data_root()`
  honours it, but `REPO_ROOT / "data"` and the per-sport path helpers do not, so
  those reads would have silently fallen back to the worktree's own lossy copy —
  the inert-redirect failure that rule was written about.
- **Neither run is hermetic.** The junction shares a LIVE directory that other
  sessions write, and the suite writes into it. Same exposure both times, so the
  comparison holds; a sealed number is still untaken.
- **Gate against the lineage you are shipping, not against `main`** — the rule
  that made the old `218 passed / 6 failed` at `2b14fbeb` worth recording. It is
  satisfied here, not waived.
- **`tests/test_intelligence.py` is 218 passed / 0 failed on committed `main`**
  `[measured 08-15 ~21:5xZ, lane red-intelligence-tests]`. It was **216/2** at
  the start of that session and 217/1 mid-way. All three reds were real, and
  **two of the three were product defects, not stale tests** — see
  `todo_closed.md` `#436`/`#438`. **It costs ~37 minutes**, single-threaded;
  `pytest-xdist` is NOT installed, so there is no faster path today.
- **The "526 passed, 0 failed" line below is NOT contradicted by that, but it is
  narrower than it reads.** Three `test_intelligence.py` failures existed on
  committed code at 08-15 21:00Z, so whatever that full-suite run covered, it
  either predates them or did not include this file. Treat it as unverified for
  `test_intelligence.py` specifically; the line above is the direct measurement.
- Full suite: **526 passed, 0 failed** after the soccer `as_of` fix `[08-15]`.
- `tests.test_archives` (what CI runs) — **383 pass, 2 skipped, ~6 min**
  `[re-measured 2026-08-19, lane ci-green]` — **but only OUTSIDE 00:00-05:00Z,
  and only on a Central machine.** See the next line; the unqualified version of
  this line was wrong.
- **CI WAS TIME-DEPENDENT — structurally RED ~5 HOURS EVERY DAY — NOW FIXED AND
  VERIFIED INSIDE THE WINDOW** `[run 32323646103, `df8aec91`, 02:09Z, 2026-08-20,
  #482]`. 11 consecutive failures 01:24-01:53Z in the same UTC band without the
  fix, then green with it. **Held overnight: 18 of 19 runs inside 00:00-05:00Z
  green**, a band that was previously 100% red.
- **Test assertions must not depend on the ambient `data/` mirror**
  `[#487, 2026-08-20]`. The one remaining overnight failure was
  `test_archive_launch_links_and_tracker_copy` asserting home-page markers that
  `_home_sport_stack.html` only renders when a sport is present and
  `active_today` — i.e. a function of what the mirror held for
  `central_today_iso()`, not of the page. `build_home_overview` is now pinned to
  a fixture there. **`#480`, `#482` and `#487` are all closed; CI is green in
  both time windows.**
- **`Daily Update`'s cron is REMOVED** `[#486, 2026-08-20, user decision]` —
  "we no longer use that daily update feature, everything runs on render."
  `workflow_dispatch` kept for manual backfill/recovery. Confirmed it did not
  fire on 08-20. Its steps 12-13 have not executed since 2026-07-15 and were
  never proven end to end. 7 `test_archives` tests computed "today" with
  `date.today()` — the runner's date, **UTC** on GHA — while the routes use
  `central_today_iso()`. CDT is UTC-5, so **00:00-05:00Z they disagree** and the
  suite fails no matter what was pushed. Evidence is a clock, not a diff: 16
  consecutive greens 2026-08-19 23:25-23:53Z, then 29 consecutive reds from
  23:57Z; across 45 runs, 28 failures inside the window vs 11 successes outside.
  **Fix applied (assert `central_today_iso()`); a Central dev box CANNOT
  reproduce it, so only a CI run inside the window proves it.** `Daily Update`
  runs 06:00Z and is outside the window.
- **CI RUNS `unittest`, NOT `pytest`, AND `conftest.py` DOES NOT EXIST TO IT**
  `[verified 2026-08-19]`. `ci.yml` runs `python -m unittest tests.test_archives`
  and `daily-update.yml` runs 13 modules the same way, while the documented
  local loop is `python -m pytest tests/`. `tests/conftest.py` is a pytest
  plugin file, so **every autouse fixture in it is absent in CI**. Measured on
  one commit, one machine, one minute: `tests/test_wnba_cards_merge_aliases` was
  `20 passed` under pytest and `FAILED (failures=2)` under unittest. **A green
  local pytest run is not evidence about CI.** Shared setup a CI-run module
  needs belongs in `tests/_cache_isolation.py` (plain functions + a `TestCase`
  mixin, which `conftest.py` now delegates to), not in `conftest.py` alone.
- `daily-update.yml`'s 13-module contract list — **55 pass**
  `[measured 2026-08-19]`, the same count CI reports.

---

## [lane-state-carried] LANE STATE RECORDS CARRIED THROUGH THE 2026-08-18 COLLAPSE — **ARCHIVED 2026-08-19 to `state_archive_2026-08-19.md`, verbatim.**

## [lane-guard-disclaimer-and-worktree-exemption-bugs] TWO REAL BUGS FOUND IN `lane-guard.py`, NEITHER FIXED `[found 2026-08-18]` — **ARCHIVED 2026-08-19 to `state_archive_2026-08-19.md`, verbatim.**

## [split-state-reindex-truncation] `split_state.py --reindex --apply` DELETED EVERYTHING BELOW THE `[subject-index]` TABLE — **FIXED, ON MAIN (`29ab5bfb`), AND NOW IN THE PRIMARY TREE TOO** `[2026-09-04, lane split-state-reindex-truncation]`

`reindex()` rebuilt `state.md` as `head + body[:hdr+1] + rows + [""]` and never
re-emitted `body[hdr+1:]`. Every byte below the table was dropped — silently:
`reindex: 179 subject(s) across 15 file(s)` / `WROTE state.md (index rebuilt)`,
exit **0**. Found by lane `sim-clv-decomposition` when it deleted 55 lines of a
`### [web-oom-leak]` UPDATE block that existed in no commit on any branch.

**The exposure was live and larger than the report.** `origin/main`'s `state.md`
carried **171 non-blank lines** below the table when the fix landed.

**FIXED.** `table_span()` bounds the table as the `|---` separator plus the
CONTIGUOUS run of `| [` rows; the rows are spliced in place and head and tail
carry through untouched. An unclassifiable post-table region — index-shaped rows
separated from the table by other content — **REFUSES with exit 1 and writes
nothing**. A runtime guard refuses if any non-blank, non-row input line would be
lost. Measured on a copy of the real `origin/main` corpus: **171 of 171 tail
lines preserved**, `state_key_check.py` "coherent". 9 new tests, 8 of which FAIL
on the pre-fix code.

**THE PRIMARY TREE NOW HAS THE FIX** `[2026-09-04, later the same day]`. A full
`git pull` was NOT possible and was not forced: the tree is 183 commits behind
and **11 of its 14 modified files collide** with upstream — other sessions' live
uncommitted work (`deploys.md`, `lanes.md`, `learnings.md`, `state.md`,
`render_events.py`, `intelligence_evaluation.py`, two test files, ...). Git
refuses such a merge outright, and stashing a shared tree would yank four
sessions' work mid-turn.

Instead, only the two fixed paths were taken:
`git checkout origin/main -- scripts/split_state.py tests/test_split_state.py`.
Safe because both were byte-identical to HEAD first, so nothing uncommitted was
discarded. **Verified in the primary tree:** 31/31 tests pass, and a DRY RUN on
its real `state.md` reports `post-table region: 56 line(s) PRESERVED (48
non-blank)` and wrote nothing. The rest of the tree is still 183 behind.

**A worktree cut before `29ab5bfb` still has the old script.** Pull first.

**THAT EXPOSED TWO REAL DEFECTS IN `discard-guard.py`, NOW FIXED (`e3a5154f`)
AND LIVE IN THE PRIMARY TREE** — see `[discard-guard-origin-blindness]`.

**Preservation is of CONTENT, not BYTES.** The live `state.md` is MIXED-ending —
580 CRLF lines and a 55-line bare-LF tail written by the appending session's
tool. `load()` + the write have always normalised endings whole-file, so a
reindex shows the whole tail in a diff. That is not a content loss.



## [discard-guard-origin-blindness] `discard-guard.py` CALLED PUSHED CONTENT "NOWHERE ELSE", AND BLOCKED `git restore --staged` — **FIXED (`e3a5154f`) THEN WIDENED TO ALL 610 REFS (`5641ca08`), BUDGET 30s WITH A REAL CEILING (`c56c48a2`); ALL LIVE** `[2026-09-04, lane discard-guard-sees-origin]`

Two defects, both in the OVER-BLOCKING direction — which the hook's own
`reset --hard` comment already names as the dangerous one, because a guard that
cries wolf teaches sessions to override it reflexively.

1. **The predicate consulted only `src` and `HEAD`.** A shared tree runs behind
   routinely — the primary tree was **183 commits behind** — so pushed content
   read as existing nowhere. `git restore --staged scripts/split_state.py` was
   BLOCKED with *"201 uncommitted line(s) in neither HEAD nor HEAD"* while the
   working file was the SAME BLOB as `origin/main` (`363b5528`). Nothing could
   have been lost. `_safe_revs()` now yields src, HEAD, `origin/main` and the
   branch upstream, dropping unresolvable ones so it never fetches. The
   comparison stays PER PATH, so a line is only excused by a copy of the SAME
   file. The message names the revs it checked.
2. **`git restore --staged` was matched though the docstring said it was not.**
   The exemption was documented from day one and never implemented — an
   index-only command that cannot touch a working file was blocked as a
   discard. `_index_only()` implements it: `--staged`/`-S` alone is index-only;
   `--worktree`/`-W`, `-SW`, or neither flag (restore defaults to `--worktree`)
   all reach the file and still refuse.

**VERIFIED LIVE on the primary tree**, hook driven directly so no real checkout
ran: `checkout HEAD -- scripts/split_state.py` → **exit 0 (was 2)**;
`checkout HEAD -- .syndicate/lanes.md` → **exit 2**, "128 uncommitted line(s),
on none of HEAD, origin/main". 5 new tests FAIL on the pre-fix hook, all
over-blocks; **every must-refuse case passes on BOTH versions**, which is what
shows the guard was not weakened. 29/29.


**WIDENED TO ALL REFS `[user request, same day]`.** Four revs is still only four;
content can sit on a branch nobody named, and this repo has **610 refs**, ~170
of them stale `origin/deploy/*`. `_deep_lines` now searches EVERY committed
version of the path across every ref.

**The cost was MEASURED, not assumed** — it had been the stated reason to defer:

| path | commits (all refs) | distinct blobs | unique bytes | exhaustive |
|---|---|---|---|---|
| `.syndicate/lanes.md` | 1,322 | 1,301 | 246 MB | 11.6s / 13.4s |
| `.syndicate/learnings.md` | 660 | 654 | 177 MB | ~7s |
| an ordinary code file | 3-4 | 3-4 | ~30 KB | <0.5s |

Early exit when the line IS found: 3.9s, 120 of 1,301 blobs. `git log --all -S`
(pickaxe) was rejected on measurement, not taste: **5.9s PER LINE**, so three
residual lines cost ~18s where the chunked scan resolves all of them in one
pass. Three git processes regardless of ref count — `rev-list`, one `cat-file
--batch-check` mapping commits to blobs, then chunked `cat-file --batch`.

**THE SWEEP IS NOT UNCONDITIONAL:** it runs only after the cheap revs fail, i.e.
only when the hook is about to BLOCK anyway. Allow-path measured **0.59s ->
0.60s**. **The budget is ONE deadline for the invocation, not one per path** —
per-path let `checkout -- a b c` cost three budgets, and a hook that can stall a
shell for an unbounded multiple of its own limit has no limit. 20s keeps this
repo's worst real case exhaustive: both big ledger files in ONE command measured
**18.7s, both answers complete**.

**A TRUNCATED SEARCH BLOCKS AND SAYS SO.** It claims "all N committed version(s)
across every ref" only when it read all of them; otherwise SEARCH TRUNCATED plus
the knob to raise. A partial search must not be reported as an exhaustive one.

**END-TO-END PROOF, unplanned and better than the tests:** installing the new
hook was itself BLOCKED by the old one over 6 lines "on none of HEAD,
origin/main" — every one of which was in pushed commit `e3a5154f`. The identical
command under the new hook exits **0 in 0.58s**, while `.syndicate/lanes.md`
with 143 truly unreachable lines still refuses in 11.2s. Same-instant A/B on the
live tree: **147 flagged -> 143**. 40/40 tests; 8 fail on `e3a5154f`.


**BUDGET RAISED TO 30s, AND MADE A REAL CEILING `[user request, c56c48a2]`.**
Raising it exposed that it was not a ceiling at all: `_git` used a FIXED 30s
per-call timeout, and `_blob_ids`' `rev-list --all` — the slowest call, 3-5s and
growing with history — runs BEFORE the chunk loop's deadline check. True bound
was budget + timeout, **60s for a 30s budget** — the "unbounded multiple of its
own limit" the constant's own comment rejects one function above. Every git call
in the sweep now takes its timeout from the time LEFT on the shared deadline.
Measured same-instant on the live tree with the budget forced to 1s:

| version | elapsed | multiple of budget |
|---|---|---|
| `5641ca08` fixed per-call timeout | 6.23s | **6.2x** |
| `c56c48a2` deadline-derived | 1.30s | 1.3x |

**The subtle half:** when the deadline kills the blob LISTING, `_blob_ids`
returns empty — indistinguishable from "this path has no committed version at
all". The first means UNKNOWN, the second NOWHERE. It now reports INCOMPLETE
there, while a path that genuinely has no history is still NOT labelled
truncated.

**Why 30 and not 20:** worst real case (both big ledger files, one command,
content genuinely nowhere) is **18.7s cold / 14.6s warm**. Against 20 that is a
1.3s margin, which is not headroom; against 30 it is ~11s.

**44 tests, and an HONEST NOTE: all 44 pass on `5641ca08` too.** They are
REGRESSION GUARDS, not proof of this change — a fixed-vs-derived timeout cannot
be distinguished in a throwaway repo where every git call is instant. The
evidence for the ceiling is the measurement above, not the suite.

**THE WIDENING PAID OFF TWICE IN REAL USE.** Installing `5641ca08` was BLOCKED
by its predecessor and needed `SYNDICATE_ALLOW_DISCARD=1`; installing
`c56c48a2` needed **no override**, because the deep sweep found the outgoing
version in history by itself. Separately, a later run on `lanes.md` returned
exit 0 in 7.2s with **122 lines still unaccounted for by the cheap revs** — all
found in OLDER commits. A line can sit in an older `origin/main` commit and not
at its tip; only the all-refs sweep sees that.
