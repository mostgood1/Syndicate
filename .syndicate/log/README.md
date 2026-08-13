# Session logs

One file per day: `YYYY-MM-DD.md`, append-only, written by `/checkpoint`.

These are raw and verbose by design. Durable conclusions get promoted out
of here into `state.md` (facts) or `learnings.md` (rules). If a fact only
exists in this directory, it has not been promoted and should not be
trusted by a future session.
