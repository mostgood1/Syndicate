---
description: Open, close, or list Syndicate work lanes
argument-hint: open <slug> "<goal>" | close <slug> | list | block <slug> "<reason>"
allowed-tools: Read, Write, Edit, Grep, Glob, Bash(git status:*), Bash(git diff:*), Bash(echo:*)
---

Manage work lanes in `.syndicate/lanes.md`.

Request: `$ARGUMENTS`

## open
1. Read `.syndicate/lanes.md` and `.syndicate/learnings.md`.
2. Determine the file set this lane will touch. Grep if unsure — do not guess.
3. Check for collisions against every OPEN lane. If any file overlaps, STOP
   and report the conflict. Do not open the lane.
4. Check `learnings.md` for a FORBIDDEN or EXONERATED rule covering this
   work. If one exists, surface it and ask for explicit override.
5. **Insert the lane at the END of the `## OPEN` section — NOT at the end of
   the file.** Find the `## OPEN` heading, scan to the next `## ` heading, and
   put the block immediately before it.

   **"Append the lane" is what this step used to say, and it is how `#466`
   happened.** A bare "append" lands at EOF, which in `lanes.md` is *below*
   `## Archived lanes` — and `lane-guard` reads `lanes.md` and nothing else, so
   the next archive pass moves that block to `lanes_closed.md` and the lane's
   file claims stop being enforced **silently**, with nothing reporting it.
   Measured 2026-08-18: **7 OPEN lanes** were sitting inside the two archived
   sections, three of them owned by sessions that were running at the time.

   If the invariant has already regressed, `py -3 scripts/hoist_open_lanes.py`
   moves stray OPEN blocks back under `## OPEN` (dry run by default; it verifies
   the claim set is unchanged before writing). `py -3
   scripts/check_lane_invariants.py` is the check, and it runs at session start.

   The block to insert:

```
### <slug> — OPEN — opened <date> — session <id or name>
- Goal: <single testable outcome>
- Files: <explicit paths>
- Hypothesis: <if diagnostic; else "n/a">
- Falsification test: <what result would prove the hypothesis wrong>
- Verification: <how we will know this is done>
- Blocked by: <lane slug or none>
```

6. Write the lane slug to **your own per-session marker**,
   `.syndicate/.current-lane.<your session id>` — resolve the id with
   `Bash: echo $CLAUDE_CODE_SESSION_ID`, then `Write` the slug to
   `.syndicate/.current-lane.<that value>`. Both `lane-guard.py` and
   `deploy-guard.py` read this file FIRST and only fall back to the bare
   `.syndicate/.current-lane` when it's absent — their own docstrings say
   so, because the bare file is a single shared slot and whichever session
   wrote it last silently answers "your lane" for every OTHER session that
   has no marker of its own.

   **Do NOT also write the bare `.syndicate/.current-lane` file.** That
   used to be this step's whole instruction, and it is the confirmed cause
   of a real cross-session misattribution: measured 2026-08-19, a
   `refresh-worker` deploy claim was acquired under a lane-slug holder name
   that belonged to a DIFFERENT session — the acquiring session had no
   per-session marker, fell back to the bare file, read whichever lane a
   third session had most recently opened via this exact step, and (most
   likely) copied that misattributed name straight out of the guard's own
   printed remedy text into `deploy_claim.py --holder`. Twice, with two
   different lane names, both traced back to this step writing the shared
   file. Writing only the per-session marker removes the leak: a session
   with no marker of its own now correctly reads as "no lane" (safe,
   forces a real `/lane open`) instead of silently inheriting someone
   else's identity.

7. Report the lane and the first concrete step. Nothing else.

## close
1. Confirm the verification step actually ran and state the result.
   If it did not run, refuse to close and say what is missing.
2. Flip status to CLOSED with the date and a one-line outcome.
3. If the lane produced a wrong belief or a broken deploy, invoke
   `/postmortem <slug>` before closing.
4. Empty your per-session marker if it holds this slug:
   `Bash: echo $CLAUDE_CODE_SESSION_ID` to get the id, then `Write` an
   empty string to `.syndicate/.current-lane.<that value>`. Also check the
   bare `.syndicate/.current-lane` — if it happens to hold this slug
   (e.g. left over from before this step changed), empty that too, but do
   not write a NEW value into it.

## list
Show OPEN lanes only, one line each: slug, goal, files, blocker.
Then flag any lane open more than 48h without a checkpoint.

## block
Mark the lane BLOCKED with the reason and what would unblock it.
