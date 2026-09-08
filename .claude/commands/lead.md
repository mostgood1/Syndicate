---
description: Record a lead without following it — one line, no ceremony
argument-hint: "<one line: what you saw>"
allowed-tools: Read, Write, Edit, Bash(echo:*), Bash(date:*)
---

Record what you just noticed and **go back to your objective**.

Lead: `$ARGUMENTS`

## The point of this command

Following a lead costs **zero**. `/lane open` costs seven steps of collision
checking. That gradient — not discipline — is why this repo defers about **1
lead in 4.5** and carries **18 of 54** findings files that no lane references.
This command exists to cost less than following the lead. **If using it ever
feels like more work than just fixing the thing, it has failed and should be
made cheaper.**

## Do exactly this

1. **Append ONE line** to `.syndicate/leads.md`, under `## Open`:

   ```
   - [ ] <today> — from `<your lane slug>` — <what you saw> — evidence: <file:line, or the command that shows it>
   ```

   Read your lane slug from `.syndicate/.current-lane.<session id>`
   (`Bash: echo $CLAUDE_CODE_SESSION_ID`). If you hold no lane, write `no lane`.

2. **Say one sentence** confirming it is recorded, then **resume the objective
   you were on**. Do not investigate the lead. Do not open files to characterise
   it. Do not "just check one thing" — that is the deviation, and the check is
   never one thing.

3. **Stop.** That is the whole command.

## Hard limits

- **Never write a lead into `.syndicate/lanes.md`.** A lead has no file claims.
  Putting it there inflates the OPEN-lane population and the claim set
  `lane-guard` enforces against every other session — 53 open lanes is already
  the problem, not the solution.
- **One line.** If it will not fit on one line you are characterising it, which
  is following it. Write less, or accept that it is a lane and open one.
- **No collision check, no `Files:`, no verification design, no hypothesis.**
  Those are lane ceremony and they are exactly the cost this command removes.
- **Do not promote it yourself.** If it turns out to be the real work, say so to
  the user and let them redirect you. Silently switching objectives is the thing
  this whole mechanism exists to catch.

## When it should be a lane instead

Open a lane (`/lane open <slug> "<goal>"`) rather than a lead when **the lead is
now the objective** and the user has said so, or when it blocks your current
goal outright and you cannot finish without it. State the blockage, then open
the lane — do not just start working in it.

## When it should be its own session

If the lead is substantial and independent, and this session has a task-spawning
tool available (`spawn_task`), offer it to the user in one line — a background
task carries its own context window, so it neither consumes nor drifts this one.
**Offer; do not spawn unasked.** If no such tool exists, the leads file is the
handoff and the next session reads it.

## Promoting a lead later

Strike the line under `## Open`, move it under `## Promoted`, and name the lane
slug it became. A lead that was picked up is a record worth keeping; a lead that
turned out to be nothing can simply be deleted — nothing here is owed by anyone.
