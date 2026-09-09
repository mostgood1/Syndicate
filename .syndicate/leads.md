# Leads — things noticed, deliberately NOT followed

A **lead** is something you noticed while working on something else. It is not a
lane. It has no owner, no file claims, no verification design and no goal — it
is one line saying what you saw and where the evidence is, so that the next
session can pick it up and you can go back to your actual objective.

**Why this file exists.** Measured 2026-09-08 on `origin/main`: this repo defers
about **1 lead in 4.5** (9 explicit "not mine to take" instances in `lanes.md`
against 41 `findings_*.md` files, which are the usual product of following a
lead inline). **18 of 54** findings/handoff files are referenced by no lane at
all. The cause is a gradient, not a discipline problem: following a lead costs
**zero**, and `/lane open` costs seven steps of collision checking. This file
makes deferring cost one line.

The mechanism, from lane `profitable-buckets` (2026-09-08), which was opened
because the work kept deviating:

> This session already spent hours going from a ledger bucket gap into segment
> pricing, first5 skill, full-game discrimination, late-inning ceilings, a
> home-field term and two deploys. **Each hop was locally justified and the sum
> was deviation.**

## Rules

- **One line per lead.** If it needs a paragraph it is a lane, not a lead.
- **Never write a lead into `lanes.md`.** A lead has no claims; putting it there
  inflates the open-lane population and the claim set that `lane-guard` enforces.
- **Nothing here is owed by anyone.** An unclaimed lead is not a broken promise;
  it is a note. Deleting a stale one is fine and needs no ceremony.
- **Promote a lead to a lane** by running `/lane open <slug> "<goal>"` and
  striking the line here with a pointer to the slug.
- Format: `- [ ] <date> — from \`<lane>\` — <what you saw> — evidence: <where>`

---

## Open

- [ ] 2026-09-08 — from `no lane` — `/api/ops/artifacts/export` is being POLLED ~55x/hour by each of two MLB patterns (`**/daily_summary_*.json&limit=40` ~2430 KB/call, `data/book_grid/book_grid_*.json&limit=6` ~1868 KB/call) = ~240 MB/h of billed edge, on the endpoint `scripts/diagnose_betting_pipeline.py:136` refuses by default as "not safe to poll"; NOT the metered spike (ran unchanged through its 13.2x drop) — evidence: `.syndicate/findings_2026-09-08_egress_run_boundaries.md` — CALLER IDENTIFIED: session `local_ea1e4863` "Sports sim engine competitive edge analysis" (archived, not running); both patterns stop together at 20:02:56Z, 26 min before that session's last activity, and are dead since
- [x] 2026-09-08 — from `session-scope-drift-guard` — **RESOLVED, and the premise was half wrong.** `learnings.md` had no rule naming scope drift, and one was added (2026-09-08, *"treating scope drift as a discipline problem"*). But the STALENESS half of this session's findings was already covered EIGHT times — see 2026-08-15 (scratch index) and 2026-08-27 (carried-forward fact). That gap is delivery, not knowledge, and is now its own rule: 910 rules, 6 digest headings — evidence: `grep learnings_index.md` before proposing anything
- [x] 2026-09-08 — from `session-scope-drift-guard` — **RESOLVED, and the original claim was already stale when written.** The lane WAS pushed by its owner (session 3492626c) in a later form; what was actually missing was the ANTI-DRIFT RULE bullet, dropped in that rewrite and surviving only in an uncommitted local copy. Moved verbatim to `lanes_history.md`; its general form is `learnings.md` 2026-09-08 — evidence: `git grep 'Each hop was locally justified' origin/main` now hits 4 files
- [x] 2026-09-08 — from `lead-deferral-and-lane-census` — **RETRACTED: they were never stale.** All three are correctly OPEN and each names its outstanding work in the same header sentence I quoted from — `layer2-cap-raise` *ONE THING OWED: the 2000-cap raise is STAGED AND UNVERIFIED* (and it holds ZERO claims, released 08-31, so it blocks nobody); `accuracy-ledger-budget-raise` *NOT CLOSED — next step is a CHUNK-COUNT bound*; `ncaaf-live-resim-wire` *OPEN: NFL drive-prior backtest in flight*. I anchored on `GOAL MET` / `CLOSED 2026-09-07` and stopped reading. Nothing was changed — evidence: the three header lines in full, and `_claims()` per lane
- [x] 2026-09-08 — from `lead-deferral-and-lane-census` — **RESOLVED: there was no overflow. My reading was wrong, not the digest.** BODY is **1556 B against BUDGET=1800** (244 B headroom, no `DIGEST OVERFLOW`, last line intact); the census change took it 1945 -> 1556. I had measured total stdout (1911 B), which includes `DIGEST NOTES` + `LEDGER INCOHERENT` — 304 B echoed at `session-start.sh:476-477`, AFTER the `LEN` check at `:472`, so never in the budget — evidence: the script's own `LEN`, probed without altering its logic
- [ ] 2026-09-08 — from `session-scope-drift-guard` — the `syndicate-engineer` subagent CLAUDE.md prescribes has ZERO recorded invocations anywhere in the ledger, despite being the prescribed escape hatch for exactly the surveys that go wrong — evidence: 7 mentions across `lanes.md`/`learnings.md`/`state.md`/`log/*`, all referring to the agent FILE being created
- [ ] 2026-09-08 — from `lead-deferral-and-lane-census` — `scope-guard` covers the Edit family only; `lane-postwrite-check` measured shell writes at ~1 in 10 of all writes to tracked source, so that fraction of drift is unseen — evidence: `.claude/hooks/lane-postwrite-check.py` docstring, 9,023 Edit vs 1,045 Bash/PowerShell writes over 292 transcripts
- [ ] 2026-09-08 — from the `live-gameline-accuracy-snapshot` task — the MLB live model prices further from 0.5 than the market on 5 of 5 post-fix dates checked (mean abs(p-0.5) 0.246-0.304 vs 0.211-0.251), which is what lets one comeback game set a whole date's Brier sign; whether that extremeness is skill or miscalibration is unmeasured — evidence: `findings_2026-09-08_live_gameline_0904_per_game.md`, needs a reliability curve over the pooled post-fix sample, not one date

- [x] 2026-09-08 — from `lead-deferral-and-lane-census` — **PROMOTED to lane `learnings-instrument-family-consolidation`, and the fold was REJECTED on the evidence.** The family is ~95 entries in 4 families with DIFFERENT fixes, not near-duplicates; folding would have deleted ~78 mechanism-specific rules. Shipped a MAP entry instead (1 heading, 0 destroyed) plus the generator fix that recovered 5 rules the 2026-08-20 fold had orphaned — evidence: `2026-09-08 MAP:` in `learnings.md`, and `d1d4045d`
- [ ] 2026-09-08 — from the `bandwidth-spike-tripwire` task — FALSIFIED, so the metered-vs-served residual is real and not an instrument gap: 0 of 15,644 app log lines in the 1,660.8 MB bucket (window 2026-09-07T23:00Z—00:00Z) carry a `-` size field, so `bandwidth_tripwire.py`'s `(\d+|-)`→0 branch never fires; `/api/ops/artifacts/stream`'s 3.3 KB mean is genuine — 566 of its 882 calls are 404 and 153 are 304, only 99 carried a body — evidence: `scripts/bandwidth_tripwire.py:85,237` + re-run `_logs(web, 23:00Z, 00:00Z, "app")` over that window
- [ ] 2026-09-08 — from the `bandwidth-spike-tripwire` task — the artifact transport errors heavily and no instrument surfaces it: in ONE hour web answered 693 `503`s to 2,996 `/api/ops/artifacts/publish` calls (23%) and 566 `404`s to 882 `/api/ops/artifacts/stream` calls (64%, plus 64 `416`s), while the spike captures record call counts and bytes but NOT status — unmeasured whether this is normal steady state or specific to a spike hour — evidence: parse `type=app` for 2026-09-07T23:00Z—00:00Z with `bandwidth_tripwire._ACCESS` (`scripts/bandwidth_tripwire.py:84`) and count match-group 4

- [ ] 2026-09-08 — from `session-scope-drift-guard` — a commit MESSAGE written to a shared `/c/tmp` path was clobbered between the write and `git commit-tree`: `cc101553` carries my tree under another session's subject. Same shared-slot class as `.current-lane`, the shared index and worktree `git stash`, all already ruled — so recorded, not re-ruled. Worth a one-line convention (write commit messages to the session scratchpad) rather than a rule — evidence: `git cat-file commit cc101553ab7f...` vs `git log -S` on the same sha

- [x] 2026-09-08 — from the `bandwidth-spike-tripwire` task — **RESOLVED in the task file; recorded because the FAILURE SHAPE is reusable.** The task's stop rule keyed on the tool's trailing `no new spike to capture`, which prints identically when nothing spiked and when every spike bucket was ALREADY CAPTURED by an earlier fire. So the 23:05Z fire reported "tripwire clear" on the largest day this phenomenon has ever had — 7 web buckets over 400 MB, ~14.2 GB metered, captured across the 01:05Z–21:05Z fires — and a fire every 2h would have kept reporting clear for as long as earlier fires stayed ahead of it. A stop rule must key on NOTHING OUTSTANDING, not on NOTHING NEW. The same run also read the 8 capture files as uncommitted from `git status` (`??`) when all 10 are on `origin/main`; the primary tree was 562 commits behind and fires push from throwaway worktrees. Both are now branches/traps in `SKILL.md`, which also carries the open user decision (controlled-transfer experiment vs overriding the component-instrumentation rule) so a fire reports it instead of re-deriving it — evidence: the 23:05Z run output (`M over 400 MB` = 7, every line `already captured`) against `git ls-tree -r --name-only origin/main -- reports/bandwidth_spikes/` = 10 files; `~/.claude/scheduled-tasks/bandwidth-spike-tripwire/SKILL.md` branches A/B/C. NOT generalised into `learnings.md` — worth checking whether other tripwire-shaped tasks stop on an emptiness message rather than an outstanding-work check.
- [ ] 2026-09-08 — from the `live-gameline-accuracy-snapshot` task (no lane) — `pregame_home_win_prob`, added in ledger v4 (4d20ea00) expressly to answer "should the live estimate have stayed closer to its prior", has NEVER been populated: 0/2872 on v4 rows and 0/531 on v5 — the question it was added for is still unanswerable — evidence: field-population-by-version over the same exported ledgers
- [ ] 2026-09-08 — from worktree cleanup (no lane) — branch `session/measured-correlation-pays-off` holds **`ab83a66b`, 1,303 lines of RESCUED orphaned work** (`scripts/measure_correlation_arm_value.py` 877 + `tests/test_correlation_arm_value.py` 426) that were untracked on a `C:/tmp` disk with no lane and are on no other ref; unpushed and unreviewed, tests never run — someone should decide whether to land or drop it — evidence: `git show session/measured-correlation-pays-off`

## Promoted

_(none yet — strike a line above and name the lane slug it became)_
