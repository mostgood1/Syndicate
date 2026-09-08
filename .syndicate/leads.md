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

- [ ] 2026-09-08 — from `session-scope-drift-guard` — `learnings.md` (4,081 lines on origin) has NO standing rule on scope drift, deferring leads or delegation; the mechanism now exists but the rule is unwritten — evidence: grepped FORBIDDEN/`scope drift`/`deviat`/`delegat`/`anti-drift` on `origin/main`, zero on-topic hits
- [x] 2026-09-08 — from `session-scope-drift-guard` — **RESOLVED, and the original claim was already stale when written.** The lane WAS pushed by its owner (session 3492626c) in a later form; what was actually missing was the ANTI-DRIFT RULE bullet, dropped in that rewrite and surviving only in an uncommitted local copy. Moved verbatim to `lanes_history.md`; its general form is `learnings.md` 2026-09-08 — evidence: `git grep 'Each hop was locally justified' origin/main` now hits 4 files
- [ ] 2026-09-08 — from `lead-deferral-and-lane-census` — THREE lanes say `— OPEN` in their status field while their header prose says they are done (`layer2-cap-raise`, `accuracy-ledger-budget-raise`, `ncaaf-live-resim-wire`); `lane-guard` still enforces their claims — evidence: `py -3 scripts/lane_census.py` vs the CLOSED text in those headers
- [ ] 2026-09-08 — from `lead-deferral-and-lane-census` — the session-start digest body is **1910 B against BUDGET=1800**, so the tail is still cut; the lane census freed 389 B but other sections grew past it — evidence: `bash .claude/hooks/session-start.sh | wc -c`
- [ ] 2026-09-08 — from `session-scope-drift-guard` — the `syndicate-engineer` subagent CLAUDE.md prescribes has ZERO recorded invocations anywhere in the ledger, despite being the prescribed escape hatch for exactly the surveys that go wrong — evidence: 7 mentions across `lanes.md`/`learnings.md`/`state.md`/`log/*`, all referring to the agent FILE being created
- [ ] 2026-09-08 — from `lead-deferral-and-lane-census` — `scope-guard` covers the Edit family only; `lane-postwrite-check` measured shell writes at ~1 in 10 of all writes to tracked source, so that fraction of drift is unseen — evidence: `.claude/hooks/lane-postwrite-check.py` docstring, 9,023 Edit vs 1,045 Bash/PowerShell writes over 292 transcripts
- [ ] 2026-09-08 — from the `live-gameline-accuracy-snapshot` task — the MLB live model prices further from 0.5 than the market on 5 of 5 post-fix dates checked (mean abs(p-0.5) 0.246-0.304 vs 0.211-0.251), which is what lets one comeback game set a whole date's Brier sign; whether that extremeness is skill or miscalibration is unmeasured — evidence: `findings_2026-09-08_live_gameline_0904_per_game.md`, needs a reliability curve over the pooled post-fix sample, not one date

## Promoted

_(none yet — strike a line above and name the lane slug it became)_
