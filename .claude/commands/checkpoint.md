---
description: Persist this session's work to the Syndicate ledger before context is lost
allowed-tools: Read, Write, Edit, Grep, Glob, Bash(git status:*), Bash(git diff:*), Bash(git log:*), Bash(touch:*)
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

4. **EDIT your lane's EXISTING block in `.syndicate/lanes.md` in place. Do NOT
   append a second `### <slug>` block.** Rewrite the header's status field and
   any lines that changed. One lane, one block.

   **`lanes.md` carries STATUS. The narrative already went in step 2** — the
   daily log is where "what changed, what was verified, what is believed" lives,
   and duplicating it here is what makes this file grow. If a superseded block
   holds something worth keeping, move it VERBATIM to
   `.syndicate/lanes_history.md`; do not leave it in `lanes.md`.

   **WHY, measured 2026-08-18.** `lanes.md` is read at every session start and
   weighed against a 120,000-byte cap, and the session-start digest truncates
   its OPEN LANES section to 600 bytes — so an oversized file arrives *lossy*,
   which is the opposite of what checkpointing is for. Appending had taken it to
   **2.12x the cap**, with one lane holding **16 blocks / 44,905 B** and its
   current status in only one of them. After a trim it was back **over cap
   within eight hours**, purely from appended blocks.

   If the digest reports `LEDGER OVER BUDGET`, run
   `py -3 scripts/trim_lane_blocks.py` (dry run by default; it keeps every
   claim-bearing and every OPEN block, and verifies the claim set is unchanged
   before writing). That tool is the cleanup — this step is the prevention.

5. If a belief was overturned this session, append to `.syndicate/learnings.md`.

6. Report, in five lines or fewer: what is now durable, what is at risk,
   and the single next action for whoever picks this up.

7. `touch .syndicate/.last-checkpoint` — do this LAST, after every write above.

   The `checkpoint-guard` Stop hook does **not** read this file's mtime. The
   marker is repo-global, so its timestamp answers "did somebody checkpoint",
   not "did I" — and on a tree with concurrent sessions that let one session's
   checkpoint silence another's warning. What counts is the *act*, seen in
   this session's own transcript: the `/checkpoint` invocation, any
   `.syndicate/**` write, or the `touch` above. Any one of them is sufficient,
   so forgetting this step is not fatal — steps 2–5 already witness it.

   A session with no such signal of its own and uncommitted non-ledger work is
   warned, regardless of what any marker on disk says.

Do not summarize the conversation. Summarize the *system*.
