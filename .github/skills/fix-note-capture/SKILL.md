---
name: fix-note-capture
description: Record a concise fix note for every nontrivial bug, regression, or incident response so future work can trace the symptom, root cause, fix, and validation without re-solving the same problem.
---

# Goal

Capture a short, factual note for every meaningful fix before closing the task.

# When to Use

Use this skill after any bug fix, deploy issue, regression fix, or incident response that required investigation.

# Procedure

1. Identify the user-facing symptom.
2. Record the root cause, not just the final patch.
3. Note the fix that was applied.
4. Record the narrow validation that proved the fix.
5. Add any follow-up or watch item that could prevent recurrence.

# Required Note Shape

Write a short entry in `docs/fix_notes_log.md` with:
- date
- symptom
- root cause
- fix
- validation
- follow-up

# Rules

- Keep the note concise and factual.
- Do not repeat large code snippets.
- Do not skip the root cause.
- Prefer one note per fix thread.
- Update the note if later validation changes the diagnosis.

# Output

A finished task should leave behind a durable note that explains what failed, why it failed, how it was fixed, and how it was validated.
