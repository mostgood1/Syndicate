---
description: Persist this session's work to the Syndicate ledger before context is lost
allowed-tools: Read, Write, Edit, Grep, Glob, Bash(git status:*), Bash(git diff:*), Bash(git log:*)
---

Write this session to disk. Assume the context window dies immediately after.

1. Run `git status` and `git diff --stat` to ground the summary in reality
   rather than in what you remember doing.

2. Append to `.syndicate/log/<today>.md`:
   - Lane(s) worked
   - What changed, by file
   - What was **verified**, with the evidence
   - What is **believed but unverified** — label these clearly
   - Dead ends hit, and why they were dead ends
   - Uncommitted work and where it lives

3. Update `.syndicate/state.md` **only** for facts that were verified this
   session. Overwrite the stale line; do not stack contradictory lines.
   If a fact was assumed rather than checked, it does not go in state.md.

4. Update the lane entry in `.syndicate/lanes.md` with current status.

5. If a belief was overturned this session, append to `.syndicate/learnings.md`.

6. Report, in five lines or fewer: what is now durable, what is at risk,
   and the single next action for whoever picks this up.

Do not summarize the conversation. Summarize the *system*.
