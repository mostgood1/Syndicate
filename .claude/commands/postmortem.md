---
description: Convert a mistake or dead end into a durable rule
argument-hint: <what went wrong>
allowed-tools: Read, Write, Edit, Grep, Glob
---

Incident: `$ARGUMENTS`

Be blunt. This file exists to stop the same hour being spent twice.

1. Reconstruct from `.syndicate/log/` and `.syndicate/deploys.md`, not
   from memory. Cite the entries.

2. Separate the two failures, because they are almost never the same:
   - The **technical** failure — what the system did.
   - The **epistemic** failure — why we believed the wrong thing, and
     what evidence we accepted that we should not have.

3. Append to `.syndicate/learnings.md`:

```
### <date> — <imperative rule, one line>
- What we believed:
- What was actually true:
- How we found out:
- The rule going forward:
- Cost:
```

4. If something was ruled out, mark it `EXONERATED` with the evidence.
   If something must never be done again, mark it `FORBIDDEN`.

5. Correct any line in `state.md` that the incident proved wrong.

6. Ask: would a rule have caught this, or only a check? If only a check,
   propose the check — a hook, a test, a preflight question — rather than
   another line of prose nobody will read.
