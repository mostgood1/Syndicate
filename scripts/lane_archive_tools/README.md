# `scripts/lane_archive_tools/` — a byte-exact mirror, not the live copy

These three files are **copies**. The scheduled task `archive-closed-lanes-0917` runs the
originals from `C:\tmp\lane-archive-tools\`, which is **outside git**, shared between sessions,
and freely rewritten — two of the three were rewritten by another session on 2026-09-23 at
16:29 and 16:35 CDT, mid-run. Nothing version-controlled them, so a rewrite that dropped a fix
would have been silent and unrecoverable. This directory is the recovery copy.

## Why this exists

A fix landed in `C:\tmp` only is reverted by the next rewrite, with no diff, no history and
nobody notified. Mirrored here, a revert becomes a `git diff` away from visible.

## Verifying the live copies have not been reverted

    py -3 scripts/lane_archive_tools/verify_mirror.py

or by hand — the hashes below are of the bytes as committed:

| file | sha256 | eol |
|---|---|---|
| `owner_liveness.py` | `fc83a8e5130c26f7975f60fa6042cb5815e8d4f0f5fda2eef63af81f0e8f4e03` | CRLF |
| `wait_owner_idle.py` | `575f4735a90b5d63152eae9287847f8f88698cacfca9c78a8d6db02a2f520ebd` | CRLF |
| `archive_closed_lanes_before.py` | `5f92bc4440223eb5d7eee39f3d5857884e1a587527383fa440ed531fab7ecb8b` | LF |

**The three do not agree on line endings, and `core.autocrlf` is `true` on the dev machine.**
`.gitattributes` therefore carries `scripts/lane_archive_tools/*.py -text`, which disables all
eol conversion. Without it these files check out rewritten and every hash comparison reports a
phantom revert. If you add a file here, add it to that rule's glob or the same trap returns.

## Restoring

    cp scripts/lane_archive_tools/<file> C:\tmp\lane-archive-tools\<file>

Check first that the live copy is not simply *newer* — a rewrite is not automatically a revert,
and another session may have improved it. Diff before you copy, and if the live copy is ahead,
mirror it back into git here instead.

## What is in them, as of 2026-09-23

- **`owner_liveness.py`** — the authoritative read-only gate. Prints SAFE/WAIT per CLOSED lane
  block on `origin/main`; last line `SAFE_SLUGS=`. Flags `--idle-min` (the task uses 240) and
  `--diff-stale-min` (default 4320 = 3 days).
- **`wait_owner_idle.py`** — a polling watcher around the same rules. **Its `SLUGS` list and its
  `IDLE_MIN, POLL_SEC, MAX_WAIT_MIN` are hardcoded to an old run.** Do not run it as-is: the task
  writes a private copy with substitutions. It is mirrored here as-is so the mirror stays a
  faithful backup rather than a fork.
- **`archive_closed_lanes_before.py`** — the only one that WRITES. Dry run unless `--apply`.

Two fixes are already in these copies and need no repeat: the 2026-09-23 `--diff-stale-min`
staleness bound, and the 2026-09-23 `changed_lines_only()` fix (a slug matched against a diff's
unchanged CONTEXT lines blocked 15,508 B of archiving on a lane the diff never touched).
