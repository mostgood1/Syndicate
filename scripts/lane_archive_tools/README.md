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
| `owner_liveness.py` | `dcb5f31e6120ed4f216414b20d329b5c1bdb48b828616d8ab77b1e94c26a7d18` | CRLF |
| `wait_owner_idle.py` | `1e23f5f14f7dccfe81b21bd0e5606c570fe70e8bfb42fcd35f36e87b5efcf0d0` | CRLF |
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

Three fixes are already in these copies and need no repeat: the 2026-09-23 `--diff-stale-min`
staleness bound; the 2026-09-23 `changed_lines_only()` fix (a slug matched against a diff's
unchanged CONTEXT lines blocked 15,508 B of archiving on a lane the diff never touched); and the
2026-09-24 `drop_upstream_echoes()` fix below.

## 2026-09-24 — `drop_upstream_echoes()`, and why the first two were not enough

A worktree's uncommitted `lanes.md` diff is taken against **its own HEAD**. On a checkout that is
behind, upstream's edits render as that worktree's `+`/`-` lines and are credited to its session.
Measured 2026-09-24: worktree `tripwire-applog-page-cap` (HEAD 143 commits behind) named **6 of the
8 CLOSED slugs** and blocked every one; of its 310 changed lines only **13 were novel**, and each of
the 3 slugs blocked solely by it was named by exactly one `+` line byte-identical to `origin/main`.
A second worktree only **18 commits behind** did the same to 5 slugs an hour earlier and had stopped
an hour later — so this is the ordinary, intermittent state of a large worktree pool.

Neither earlier fix can see it, and both are behaving correctly: the diff is genuinely FRESH (so the
staleness bound must not fire) and the lines are genuine `+`/`-` CHANGES (so the context narrowing
does not apply). **Do not widen `--diff-stale-min` to reach this** — that bound separates abandoned
WIP from live work and would discard true signals to suppress a false one.

Verified off != on against production state, both directions: the three slugs blocked only by the
echo cleared, while `polymarket-corners-btts-order-branch` and `nhl-ncaab-club-maps` stayed blocked
by the same worktree — correctly, since its 13 novel lines are older OPEN versions of exactly those
two lanes. Unit tests: `tests/test_lane_archive_tools.py` (18, both controls, mutation-checked).

**A trap this surfaced and did NOT fix (open lead).** The slug test is a substring match over the
whole changed line, so a lane block that merely MENTIONS another slug in its prose blocks it. The
lane that shipped this fix named its three target slugs in its own goal text and thereby blocked all
three until it landed. Harmless here — an uncommitted block stops mattering once committed — but it
is a fourth mechanism of the same family.

**`drop_upstream_echoes` takes and returns a STRING**, the same shape `changed_lines_only` produces,
because both callers then run `slug in text`. Its first draft took a list, iterated the string
character by character and returned single characters — on which `slug in text` is False for every
slug, silently disabling the worktree check entirely and making every CLOSED block archivable. That
is worse than the bug being fixed, and only the unit test caught it.