# DRY RUN 2026-09-04 -- scheduled task `feed-live-warn-rate-live-slate`

**THIS IS NOT A MEASUREMENT. IT CARRIES NO FINDING.** It is a PRE-APPROVAL DRY
RUN whose only purpose was to exercise tonight's tool chain so the permission
prompts are granted before the unattended 20:15 run, not during it.

- when: 2026-09-04 15:10 CDT (America/Chicago)
- lane: feed-live-dryrun (dry-run scaffolding only; owns no source file)

## Step 2 -- live-slate check (statsapi schedule, 2026-09-04)

    Counter({'Preview': 15, 'Live': 1})

Read at 15:09 CDT. 16-game slate, 1 game live at that instant. Recorded only as
proof the reader ran; the real run reads its own.

## Step 1 -- sampler, one-line result

`sample_request_path_guard.py --minutes 1 --interval 30 --operation
mlb_cards_fetch_current_feed_live`: 3 samples, 0 failed reads, pids [78, 79],
`+0 over 1.0 min in 0 event(s)` and `RATE NOT QUOTABLE` (0 increase events, 5
required). That is the tool refusing to quote a rate off a 1-minute window,
which is correct behaviour and the reason the window was set to 1 minute here.

## Defect this dry run actually caught (about the RUNNER, not the system)

The scheduled task's step 1 says to run the sampler from the PRIMARY tree
because that tree holds the gitignored `.env`. **The primary tree does not
contain the script.** It sits 141 commits behind `origin/main`, and
`scripts/sample_request_path_guard.py` was added upstream of it:

    py -3 scripts/sample_request_path_guard.py ...
    -> can't open file '...\scripts\sample_request_path_guard.py': [Errno 2]

Tonight's run would have died on its first command. Workaround used here, and
what the task file should say: run the sampler from the SESSION WORKTREE (it is
cut from `origin/main`, so it has the script) with `ADMIN_TOKEN` exported into
the environment from the primary tree's `.env` -- `_admin_token()` prefers
`os.environ` over the file, so the secret still never reaches argv.
