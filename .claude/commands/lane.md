---
description: Open, close, or list Syndicate work lanes
argument-hint: open <slug> "<goal>" | close <slug> | list | block <slug> "<reason>"
allowed-tools: Read, Write, Edit, Grep, Glob, Bash(git status:*), Bash(git diff:*)
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
5. Append the lane:

```
### <slug> — OPEN — opened <date> — session <id or name>
- Goal: <single testable outcome>
- Files: <explicit paths>
- Hypothesis: <if diagnostic; else "n/a">
- Falsification test: <what result would prove the hypothesis wrong>
- Verification: <how we will know this is done>
- Blocked by: <lane slug or none>
```

6. Report the lane and the first concrete step. Nothing else.

## close
1. Confirm the verification step actually ran and state the result.
   If it did not run, refuse to close and say what is missing.
2. Flip status to CLOSED with the date and a one-line outcome.
3. If the lane produced a wrong belief or a broken deploy, invoke
   `/postmortem <slug>` before closing.

## list
Show OPEN lanes only, one line each: slug, goal, files, blocker.
Then flag any lane open more than 48h without a checkpoint.

## block
Mark the lane BLOCKED with the reason and what would unblock it.
