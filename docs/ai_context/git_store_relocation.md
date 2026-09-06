# Moving the git store off OneDrive — runbook

`[2026-09-05, lane git-out-of-onedrive]` Written after a night in which OneDrive's
management of `.git` produced 36 invisible dead worktree registrations, 16 husk
directories, and a `git worktree remove` that half-fails by design. **Not run
yet** — it needs a quiet tree, and the tree was not quiet.

## The problem, measured

The repo is at `C:\Users\<user>\OneDrive\Coding\Syndicate`, so OneDrive's Cloud
Files filter manages `.git` as well as the working tree:

```
.git                    Directory + ReparsePoint + PINNED
.git\worktrees          ReadOnly + Directory + Archive + ReparsePoint + PINNED
.git\worktrees\<entry>  ReadOnly + Directory + Archive + ReparsePoint + PINNED
                        and logs/ + refs/ INSIDE each carry ReadOnly too
```

Windows honours `ReadOnly` on **files**, not directories. So:

- `git worktree remove` deletes the worktree's contents, then fails to delete
  `.git/worktrees/<name>` — leaving a stale registration **and** an empty husk.
- A registration whose `gitdir` file is missing is **hidden from
  `git worktree list`** while still occupying `.git/worktrees/`. 36 accumulated
  unseen; `list` said 83 while the directory held 118.
- `attrib -R /S /D` does **not** clear it (118 before, 118 after). Only
  `Remove-Item -Recurse -Force` does, because `-Force` overrides `ReadOnly`.
- **The store is 5.9 GB**, and `du -sh .git` took over 400 s to say so —
  placeholder recall makes traversal slow enough to time out tooling. Two
  consequences. (1) OneDrive is syncing ~5.9 GB of loose objects and packs to
  the cloud continuously, which is quota and upload bandwidth spent on data git
  already stores compressed and never needs synced. (2) It makes the
  same-volume precondition below load-bearing rather than tidy: on one volume
  the move is a metadata-only rename and effectively instant; across volumes it
  is a **5.9 GB copy+delete**, not atomic, with a long window in which the store
  exists in neither place. `move_git_store.py` refuses the cross-volume case.

## What moving `.git` does and does not fix

**Fixes:** the worktree-metadata `ReadOnly` churn, sync races on `.git/index`
and `.git/refs`, and the traversal slowness.

**Does NOT fix:** `.syndicate/` carries the same
`ReadOnly + ReparsePoint + PINNED` — it is in the *working tree*. The ledger
churn (a CRLF rewrite warning on every append) and OneDrive arbitrating ledger
writes are unchanged. **Ending the whole class means moving the repo, not the
store.** Decide which problem you are solving before running anything.

## Preconditions — all of them, not most

1. **Zero concurrent git activity.** This is the only genuinely dangerous part.
   Worktree pointers are absolute, so the store cannot move without rewriting
   84 of them, and any git command in any session can see a half-moved store.
   `scripts/move_git_store.py` refuses on a dirty tree for this reason.
2. `git worktree prune` clean (0 prunable).
3. Target on the **same volume** (a cross-volume move is copy+delete, not
   atomic) and **not** inside OneDrive.
4. No `index.lock` / `MERGE_HEAD` / `rebase-merge` etc.

## Procedure

```bash
# 1. dry run -- prints the exact rewrite for all 84 and validates each
py -3 scripts/move_git_store.py --target C:/gitstore/Syndicate.git

# 2. when preflight reports CLEAR (it will refuse otherwise)
py -3 scripts/move_git_store.py --target C:/gitstore/Syndicate.git --apply
```

`--apply` records every worktree's HEAD first, moves the store, writes the
repo's `.git` pointer file, rewrites all 84 worktree `.git` files, runs
`git worktree repair`, then **re-resolves every HEAD and compares**. A mismatch
exits 3 and says so rather than reporting success.

## Afterwards — what still references the old path

Not handled by the script, because they are outside git:

- `CLAUDE_PROJECT_DIR` and every running session's cwd
- `.claude/hooks/*` and `.claude/settings.json` path references
- scheduled tasks
- `.syndicate/` prose that names the absolute path

The store move leaves all of these valid (the repo does not move); they matter
only for the **full repo relocation** variant.

## The trap this script already fell into

The first cut computed the required pointer from the **current** store rather
than the target, so the dry run printed 84 rewrites whose `from` and `to` were
identical. With `--apply` that is silent and total: every pointer "rewritten"
to the value it already had, the store gone, 84 worktrees pointing at nothing —
and it would have *looked* clean, because nothing checked that a rewrite
changed anything. Pinned by
`tests/test_move_git_store.py::test_required_pointer_derives_from_the_TARGET_not_the_current_store`,
mutation-checked in both directions.

**The dry run is the check.** Read the `from`/`to` pairs before `--apply`; if
they are equal, stop.
