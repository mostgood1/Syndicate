# Orphaned `autostash` triage — 7 dropped, 1 KEPT, all recoverable by SHA

`venue-first-market-universe` (session d617eefd), 2026-08-30.

Found while verifying I had not damaged a peer's uncommitted work during a
rebase. An `autostash` only survives if the rebase that created it did NOT
finish -- a conflict or an interrupt -- so each one is somebody's uncommitted
work that was picked up and never handed back. Nothing reads a stash list, so
they are silent. Same failure family as the 4,993 staged deletions.

## Verdicts

| stash | SHA | date | contents | verdict |
|---|---|---|---|---|
| `{5}` | `95ef31f4` | 2026-08-16 | ui_layout_probe + tests + ledger, 28 files | ALREADY ON MAIN |
| `{6}` | `5fccc650` | 2026-08-16 | same, 26 files | ALREADY ON MAIN |
| `{7}` | `d63ef276` | 2026-08-16 | same, 28 files | ALREADY ON MAIN |
| `{17}` | `7b240d3d` | 2026-07-07 | `data/**` live-lens jsonl | MIRROR OUTPUT |
| `{23}` | `45d67ed4` | 2026-06-26 | `data/**` 118 files, statsapi cache | MIRROR OUTPUT |
| `{25}` | `1f5cc893` | 2026-06-20 | `data/**` live-lens jsonl | MIRROR OUTPUT |
| `{26}` | `aff2b193` | 2026-06-09 | `data/**` live-lens jsonl | MIRROR OUTPUT |
| `{24}` | `bf7f4202` | 2026-06-22 | `tools/ask.py` | **KEPT — NEVER LANDED** |

## How "already on main" was established

NOT by line count. The stashed files differ from main by 662-790 lines, which
only says main moved on in two weeks. Checked by SYMBOL instead -- every
distinctive thing those stashes ADD is present on `origin/main` today:

    WATCH_METRICS           3
    SETTLE_QUIET_MS         3
    _contradicted_width     2
    identicalContentSpread  23

So that work reached main by another route and the autostash was a stranded
duplicate, not lost work.

## Why the `data/**` ones are not work

Live-lens jsonl, a rotowire HTML cache blob, eval manifests. `data/` is a lossy
mirror of what production computed and is never evidence -- CLAUDE.md is
explicit. The 118-file / 353,325-insertion one is entirely regenerated output.

## `{24}` KEPT and why

Two lines added to `tools/ask.py`:

    +WORKER CONTEXT:
    +{load("worker_architecture.md")}

Neither `WORKER CONTEXT` nor `worker_architecture.md` appears in `tools/ask.py`
on main. Someone was feeding the worker-architecture doc into the ask tool's
prompt on 2026-06-22 and it never landed. Ten weeks old and possibly abandoned
deliberately -- but it is the ONLY one of the eight that exists nowhere else, so
dropping it is the only one that loses something.

## Recovery

The seven dropped remain reachable by the SHAs above until git gc prunes them:

    git stash apply <sha>        # or: git show <sha>

Dropped in DESCENDING index order. Dropping a low index renumbers everything
above it, which is how the wrong stash gets deleted.
