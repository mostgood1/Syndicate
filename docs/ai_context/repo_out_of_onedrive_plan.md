# Plan: move the Syndicate repo out of OneDrive

Lane `repo-out-of-onedrive-plan`, written 2026-11-04 (CST). **Read-only: nothing was moved.**
Tags: **[M]** measured in this pass (2026-11-04 ~07:00-08:30 CST), **[B]** believed (code read or inference, not run).

---

## 0. Summary

- **This is not a first plan. A plan and a move script already exist, the user approved them, and they failed twice.**
  - Plan: session `86352bc9`'s scratchpad `repo_move_plan.md`, 2026-11-02, inventory plus runbook. It lives **only in a
    scratchpad**, so §3 records what it found here.
  - Script: `C:\SyndicateProd\repo_move\run_move.ps1`, approved 11-02 ("yes to all 3, do the move tonight"). Task
    `\Syndicate repo move (one-time 11-04)`. Dry runs passed on 11-02 09:55 and 11-03 07:48 [M, `move.log`].
  - **Both real runs gave up without changing anything** [M]:

    | Run | Logged result |
    |---|---|
    | 11-03 00:31 | `FAIL: gave up at 02:00, still: claude.exe running x26` |
    | 11-04 00:30 | `FAIL: gave up at 02:00, still: claude.exe running x20` |

    The script needs the Claude desktop app **fully quit**. Nobody quit it, so it waited 90 minutes and stopped. That is
    correct behaviour: a session cwd inside the repo holds a handle, and the app rewrites the JSON stores the script edits.
- **Had the app been quit, the script would have broken production state.** An independent review in this pass (§1b)
  found that R4 throws on git's normal stderr under PowerShell 5.1. That throw comes **after** the rename and **before**
  the fleet repair, it is uncaught, and it leaves a stale `FAILED … nothing moved` in `RESULT.txt`. Waiting on the app
  was what kept the script from causing harm.
- **What the next attempt needs:**
  1. The **script fixes in §1b** (S1-S4 are blockers). **DONE 2026-11-04 and rehearsed on the real branch (§1c).**
  2. **Pre-window code fixes** (§4: F1, F3 is now a blocker, F6, F7).
  3. An **attended** window in which the user quits the app (§5). An unattended night task cannot quiesce an app that is
     left open.
- **Target:** keep `C:\Users\tempadmin\Coding\Syndicate`, not `C:\dev\Syndicate` (§2).
- **Method:** a same-volume rename plus `git worktree repair`. A fresh clone loses local-only state (§6).
- **Downtime:** the desktop app and its sessions are down **about 20-40 min**. The **fleet is not down**. Its deploy-claim
  lock is mis-pointed for the minutes between the rename and R5.1, while no deploys run (§9).

---

## 1. What exists, and why it did not run

`run_move.ps1` steps, read in full [M]:

| Step | What it does |
|---|---|
| Preconditions (`:56-81`) | Waits until all of these are clear: no `claude.exe`, no process started from the repo, no fresh `index.lock`/`MERGE_HEAD`/rebase state, no HELD deploy claim. Gives up at `-WaitUntil` |
| R0 (`:83-105`) | Snapshot to `C:\SyndicateProd\repo_move_snapshot\<ts>`: worktree list and HEADs, desktop session store, `git-worktrees.json`, `claude_desktop_config.json`, `ccd-session-presets.json`, `~/.claude/scheduled-tasks`, user `settings.json`, the in-play runner, the watcher task XML, `hooksPath`, the fleet's `local_production.env`. Writes `ROLLBACK.txt` |
| R1/R2 (`:107-117`) | `OneDrive /shutdown`, then a 2,000-file rename test out of the sync root. Aborts if it takes more than 30 s |
| R3 (`:119-126`) | `Move-Item OLD NEW`. On failure it restarts OneDrive and aborts with nothing moved |
| R4 (`:128-139`) | Rewrites `.git/config` and `config.worktree` (`hooksPath`), runs `git worktree repair <new paths>`, checks every HEAD against the snapshot and that 0 OneDrive strings remain |
| R5.1 (`:141-154`) | Fleet: `sed` of `SYNDICATE_DEPLOY_CLAIM_DIR` to the new `/mnt/c` path, then `test -d` |
| R5.2 (`:156-162`) | Rewrites the in-play runner copy's `REPO`, and re-points the disabled `unknown-submit watcher` task |
| R5.3 (`:164-177`) | **Copies** (not moves) every `~/.claude/projects/C--Users-tempadmin-OneDrive-Coding-Syndicate*` folder to its new key, and fixes the `MEMORY.md` relative link |
| R5.4 (`:179-190`) | User `settings.json`: path rewrite plus a twin `Read(...)` rule. Checks the auto-mode "Trusted repo" rule |
| R5.5 (`:192-203`) | Desktop stores: session `local_*.json`, `scheduled-tasks.json`, `git-worktrees.json`, desktop config, presets, and every `SKILL.md`. All edits are byte-preserving and JSON-validated |
| End (`:205-208`) | **Leaves OneDrive off** and writes `RESULT.txt` |

Its path regex (`:29`) requires `Syndicate` to end the match. `OneDrive\SyndicateBackup` and `Syndicate-sync-backup-*`
are never rewritten.

### 1b. Script defects found in review (2026-11-04, independent reviewer, read-only plus a scratchpad test repo)

Dry runs cannot catch these. Everything below `:132` runs only when the script is not in DryRun mode.

| # | Sev | Defect | Evidence | Fix |
|---|---|---|---|---|
| S1 | **blocker** | `git worktree repair … 2>&1` runs under `$ErrorActionPreference='Stop'`. Git's normal `repair: gitdir incorrect` lines on stderr become a terminating error in PS 5.1. The error is **uncaught**: `Fail()` never runs, and R5.1-R5.5 never run. The fleet claim dir is left pointing at a missing directory, which splits the lock. `RESULT.txt` keeps the previous night's `FAILED … gave up`, which §7 reads as "nothing moved, restart OneDrive", and that would sync a mass delete | `run_move.ps1:12`, `:133` [M, line read]. The reviewer reproduced the throw with `2>&1` and with `2>$null` in a test repo. The same applies at `:85`/`:134` (`rev-parse 2>$null`) if a worktree path is missing. Memory `feedback_ps51_native_stderr_is_error` | run every git call under `'Continue'` and judge by `$LASTEXITCODE` (as `nightly_backup.ps1:25-30` does). Wrap everything after R3 in `try { } catch { Fail … }`. Write `RESULT.txt = RUNNING <ts>` at start |
| S2 | **blocker** | No resume. After any failure past R3, a re-run stops at `:57` ("OLD repo not found") | `:57` | add `-Resume`: skip R0-R3, assert NEW exists and OLD does not, then run R4+ (idempotent) |
| S3 | should-fix | R5.1 (fleet claim dir) runs **after** R4, the step most likely to fail. `ROLLBACK.txt` lists the fleet step 6th | `:141`, `:103` | move R5.1 to just after R3. Put fleet first in ROLLBACK |
| S4 | should-fix | The R2 rename test makes **fresh** files with OneDrive off, so they are not placeholders. The real tree is **413,700 files, 413,673 reparse-point placeholders**, pinned, 0 dehydrated [M, reviewer]. U1 stays untested | `:111` | test on an already-synced subfolder. After R3, run `git -C $NEW status` / `fsck --connectivity-only` and a read of sample files |
| S5 | should-fix | OneDrive `/shutdown` is logged but not enforced | `:109` | `Fail` if OneDrive is still running |
| S6 | should-fix | `~/.claude.json` (Claude Code per-project trust, MCP and settings) has **75 old-path hits** [M]. Not snapshotted, not rewritten | file grep | snapshot it in R0, `Rewrite-File -Json` in R5.4, and add it to ROLLBACK |
| S7 | nit | `hookspath_before.txt` captures only `.git/config`, not the 8 `config.worktree` values | `:94` | snapshot all 9 |
| S8 | nit | `-WaitUntil` is not "wait until": a run started between 02:00 and 14:00 gives up after the first unmet check | `:62` | pass `-WaitUntil` explicitly from the command line (§5) |
| S9 | nit | `$RX_PATH` skips an old path followed by `.` (sentence end in `SKILL.md`) | `:29` | allow a trailing `.` that is followed by whitespace or end of text |

#### 1c. FIXED 2026-11-04 (lane `repo-move-script-fixes`, user "Yes, fix both")

`run_move.ps1` was rewritten. The original is kept as `run_move.ps1.bak-20261104-pre-fixes`. Changes:

| Item | Fix |
|---|---|
| S1 | Every `git`, `py` and `wsl.exe` call goes through `Invoke-Native`: `'Continue'` plus `$LASTEXITCODE`. The whole body is in one `try/catch` that ends in `Fail`. `RESULT.txt` = `RUNNING …` from the first line |
| S2 | `-Resume` finishes R4+ from the newest snapshot that holds `moved.txt` (written right after R3) |
| S3 | R5.1 (fleet) runs right after R3. `ROLLBACK.txt` puts the fleet first |
| S4 | Partly addressed. A post-move check (`R3check`): main HEAD equals the snapshot, `git status` rc 0, 300 random tracked files read. The R2 test still uses fresh files, so U1 is still unmeasured before the move; the check catches it after |
| S5 | `Fail` if `OneDrive.exe` is still running 30 s after `/shutdown`. A failure before the move restarts OneDrive; a failure after it never does |
| S6 | `~/.claude.json` is snapshotted and rewritten with JSON validation |
| S7 | `.git/config` and every `config.worktree` are copied to `snapshot\gitconfig\` |
| S8 | `-WaitMinutes N` for attended runs. A past `-WaitUntil` means tomorrow |
| S9 | The path may be followed by `.` when no word character comes next |
| F1 | The in-play nightly task gets `--repo "<NEW>"` (`Set-ScheduledTask`; a warning on failure, not a stop) |
| F7 | The harvester launcher's `PRIMARY` is rewritten. The launcher does not self-sync, so the rewrite sticks |
| New | `-GitOnly` rehearsal mode (refuses the real paths), `-Old`/`-New`/`-StateDir`/`-SnapRoot`, and the `-FailAt <step>` test hook. Re-homing steps outside git (R5.2) record warnings in `RESULT.txt` instead of stopping |

**Rehearsal: the real branch, not a dry run** [M, 2026-11-04 09:15-09:17 CST]. Fixture `C:\tmp\repomove_rehearsal`: a repo with
an external worktree and an internal `.claude\worktrees` worktree, absolute `core.hooksPath` plus a `config.worktree`
`hooksPath`, and uncommitted files in both worktrees.

| Case | Result |
|---|---|
| Plain run | `REHEARSAL OK`, exit 0. Git **did** write `repair: gitdir incorrect … \| .git file broken …` to stderr, and it was handled (rc 0). `worktrees=3 prunable=0 head_mismatch=0`, 0 old paths in git files or pointers, `hooksPath` re-pointed in both configs, uncommitted files kept, OLD gone |
| `-FailAt R4` (after the move) | exit 1. `RESULT.txt`: `POST-MOVE FAILURE at R4 … The repo IS at <new> … DO NOT start OneDrive … re-run with -Resume` |
| then `-Resume` | `REHEARSAL OK`, exit 0. 3 worktrees, uncommitted file kept |
| `-FailAt R3` (before the move) | exit 1, `… (nothing moved)`. OLD intact, NEW absent |
| fresh `.git\index.lock` | exit 1 at the deadline: `gave up … git in-flight: …index.lock (nothing moved)` |
| `-GitOnly` with the default (real) paths | refused, exit 1 |

**Real-repo `-DryRun`** [M, 09:17-09:18 CST]: `DRY RUN OK`.
- Snapshot: 33 worktrees, 0 without a HEAD.
- Fleet: `fleet key lines on old path: 1`. Git configs: 9 of 30 to rewrite. 32 repair paths, 8 of them inside the repo.
- In-play runner: 1 rewrite. Harvester: 1. User `settings.json`: 4. **`~/.claude.json`: 75, JSON-valid.**
- Desktop stores: 5,136 rewrites in 1,487 files. `SKILL.md`: 401 rewrites in 285 files. 58 project folders to copy.

#### 1d. 2026-11-07: the R3 failure and the hardening

- **The 11-07 09:30 run** force-stopped claude.exe x20 (the `-StopAppAfterMinutes` option, added 11-06 by fleet-watcher). R0, R1 and R2 passed. **R3 threw "being used by another process", and nothing moved.** The holder was not named; `handle.exe` was not installed.
- **The fix**, details in the `.syndicate/log/2026-11-07.md` 15:58Z entry:
  - claude.exe is killed as a tree;
  - `OneDrive.Sync.Service` is stopped;
  - Windows command-line holders and WSL cwd holders are cleared before each try (WSL fd-only holders are only logged);
  - `handle64` is logged when installed;
  - the rename is retried 8 x 15 s.
- **Found in rehearsal:** `Move-Item` on a directory **splits the tree** when a handle is held inside it. R3 now uses `[IO.Directory]::Move`, which is all-or-nothing.
- **Rehearsed:** a cwd holder gives a clean "nothing moved"; a command-line holder is killed and the move succeeds; `-FailAt R4` then `-Resume` still works.
- **Real-repo `-DryRun` 11-07 09:56: OK.** It found one live WSL cwd holder, which a real run would kill.

**F6 LANDED 2026-11-04 `74767d036`** (loan from `in-game-trading`, user "Yes, take the loan", recorded at `2176a0329`):
- `inplay_nightly.py`: `REPO` = the first candidate (`Coding\Syndicate`, then `OneDrive\Coding\Syndicate`) holding a `.git`; `SYNDICATE_PRIMARY_TREE` overrides.
- The recorder is handed `--env <repo>\.env`. A missing repo logs `SYNC_FAILED repo not found`.
- `inplay_recorder.py` `--env` defaults to the first existing candidate; `SYNDICATE_ENV_FILE` overrides.
- `tests/test_inplay_repo_paths.py`: 5 pass, and 16 existing in-play tests pass. Today both defaults resolve to the OneDrive path, so behaviour is unchanged until the move.
- **Re-arm gate:** the runner at `C:	mp\inplay_runner` picks up the change at its next self-sync (the 08:00 CST run of `\Syndicate inplay nightly`). Its log must show `SYNC origin/main=<sha at or after 74767d036>`, or the runner copy of `inplay_recorder.py` must contain `ENV_CANDIDATES`.

---

## 2. Target path: keep `C:\Users\tempadmin\Coding\Syndicate`

| | `C:\Users\tempadmin\Coding\Syndicate` | `C:\dev\Syndicate` |
|---|---|---|
| Same volume as the source (rename, not copy) | yes [M] | yes [M] |
| ACL | inherits `C:\Users\tempadmin`: SYSTEM, Administrators, Amyn only [M, `icacls`] | `C:\` grants **Authenticated Users: Modify** to new subfolders [M, `icacls C:\`]. `.env` (secrets) would be writable by any local account until hardened |
| `run_move.ps1` (`:14`, `:147`, `:185`) | built for it, dry-run passed twice | 3 constants plus the WSL `sed` target need editing |
| `C:\SyndicateProd\dev_backup\nightly_backup.ps1:10-11` | already in its candidate list. The backup follows the move with no edit | **not in the list**: the nightly dev backup would fail with "repo not found" |
| Exists today | no [M] | no [M] |

**Recommendation:** `C:\Users\tempadmin\Coding\Syndicate`. Choosing `C:\dev` means editing the four places above and
running `icacls C:\dev /inheritance:r` plus explicit grants first.

---

## 3. Inventory of path dependencies (re-measured 2026-11-04)

The [M] "11-02" column is from the 11-02 plan. "Now" is this pass.

### 3a. Git

| Item | 11-02 | Now | Handled by |
|---|---|---|---|
| `git worktree list` entries | 53 | **33** [M]: 19 `C:\tmp\syndicate-sessions`, 3 `C:\tmp`, 8 `.claude\worktrees` (in the repo), 1 `Coding-archive`, 1 `AppData\Local\syndicate`, plus main | R4 `worktree repair`. Inside-repo entries are passed at their new path |
| `.git/worktrees/*/gitdir` | 52 | 32 present, **1 without `gitdir`** (`nostalgic-goldstine-c21b7b`, a husk) [M] | Run `py -3 scripts/session_worktree.py prune` (dry run) before the window. A husk does not block the move |
| `.git/config` `core.hooksPath` | absolute OneDrive path | same [M] | R4 rewrite |
| `config.worktree` `hooksPath` | 9 | **8** [M] | R4 rewrite |
| `<worktree>/.git` pointer files | 52 | 32 [M] | R4 `worktree repair` |

### 3b. Claude Code project config and hooks: no edit needed

- `.claude/settings.json` and `.claude/hooks/*` use `$CLAUDE_PROJECT_DIR` and git. 0 absolute OneDrive paths [M, grep].
  The one hit, `deploy-guard.py:473`, is a docstring.
- **`deploy-guard.py:249`** reads `<root>/.syndicate/deploy_claims/<svc>.json`, with `root` from the session's tree, so it
  follows the move.
- **`scripts/deploy_claim.py`**:
  - On Windows, `CLAIM_DIR` = `SYNDICATE_DEPLOY_CLAIM_DIR` → `~/syndicate-prod/local_production.env` → `git
    --git-common-dir`'s parent `/.syndicate/deploy_claims` (`:82-112`, `:114-143`; `CLAIM_DIR` `:147`). Path-independent.
  - **On the fleet it is not.** See 3e.

### 3c. Scheduled tasks

**Desktop app registry** [M]:
- `...\claude_pzs8sxrjxfjjc\claude-code-sessions\2fb48ee6-…\2a8d01a0-…\scheduled-tasks.json`: **60 tasks, 35 enabled,
  60/60 `cwd` = `C:\Users\tempadmin\OneDrive\Coding\Syndicate`**. 11-02 had 52 and 36. Handled by R5.5.
- `C:\Users\tempadmin\.claude\scheduled-tasks\*\SKILL.md`: **285 of 311** name the path (11-02: 278 of 303). Handled by
  R5.5.
- While the app is quit, these tasks do not fire. In a 00:30-02:30 window that is `archive-closed-lanes-0917` (`25 */2`).
  Fixed-time tasks inside the window should be checked with `list_task_runs` afterwards. One-time tasks have missed
  before (memory `project_one_time_scheduled_tasks_miss`).
- `scripts/check_scheduled_task_registry.py:71-76` globs the registry under `%LOCALAPPDATA%`/`%APPDATA%` and has no repo
  path [M]. The deployed copy is `C:\SyndicateProd\task_registry_check\` (it differs from the repo copy) and is also
  path-free [M].

**Windows Task Scheduler** (`schtasks /query /v`, read-only) [M]:

| Task | Path dependency | Action |
|---|---|---|
| `\SyndicateAltLadders`, `\SyndicateNbaGamedayProps`, `\SyndicateNbaPreviewProps` | **None any more.** `--env-file /home/amyn/syndicate-prod/secrets.env` (mode 600) [M]. The 11-02 blocker is closed | none |
| `\Syndicate inplay nightly` | Runner `C:\tmp\inplay_runner\scripts\inplay_nightly.py:42` `REPO = r"C:\Users\tempadmin\OneDrive\Coding\Syndicate"`, used by the self-sync `git -C REPO show origin/main:<file>` (`:83-96`) | **§4 F1** |
| `\Syndicate unknown-submit watcher` (Disabled) | `-File C:\Users\tempadmin\OneDrive\Coding\Syndicate\scripts\watch_unknown_submit.ps1`, Start In = the repo | R5.2 re-points it |
| `\SyndicateDevBackup` (04:00 daily) | `nightly_backup.ps1:10-11` accepts either path | none (target must be `Users\tempadmin\Coding`) |
| `\Syndicate repo move (one-time 11-04)` | the move itself; Next Run N/A, Last Result 1 | re-arm or Run-now in the window |
| `\SyndicateSoccerLiveProjectionHarvest` | `C:\tmp\soccer-live-projection-harvest\bin\run_harvest.py:40` `PRIMARY = Path(r"C:\Users\tempadmin\OneDrive\Coding\Syndicate")`, passed as `env_root` (`:163`) [M]. Per its docstring this only matters for a non-fleet target | **§4 F7** |
| `\SyndicateLocalProduction`, `\SyndicateFleetWatchdog`, `\SyndicateCheatSheets*`, `\SyndicateNewsCollector`, `\SyndicatePlayCards`, `\SyndicateTaskRegistryCheck` | `~/Syndicate`, `\\wsl.localhost\…`, `C:\SyndicateProd` only [M, reviewer grep of watchdog, task_registry_check and top-level `C:\SyndicateProd`] | none |

### 3d. Repo code with hard-coded paths (`origin/main`, `git grep`) [M]

**Unchanged since 11-02. The path-agnostic PR (11-02 P4) never landed.**
- 20 scripts:
  - `audit_lane_unguarding.py:35`
  - `backfill_uefa_historical_closes.py:17` (docstring)
  - `backtest_football_attribution_props.py:36`
  - `backtest_ncaaf_lines_props.py:243,398`
  - `backtest_ncaaf_total_units.py:71,295`
  - `commit_live_gameline_history.py:33`
  - `copy_backfill_to_fleet.py:35` (`/mnt/c`)
  - `diagnose_nfl_passing_yards_prop.py:32`
  - `e3_history_loaders.py:57` (`/mnt/c`)
  - `fetch_ncaaf_historical_props.py:35,37`
  - `football_attribution_tables.py:31`
  - `football_scenario_rates.py:57`
  - `football_scenario_refit_v4.py:331`
  - `grade_football_model_weight.py:36`
  - `grade_football_playability.py:42`
  - **`inplay_nightly.py:42`**
  - **`inplay_recorder.py:93`** (`--env` default)
  - `ncaaf_attribution_usage.py:24,25`
  - `release_phantom_lane_claims.py:62` (memory-folder key)
  - `survey_nhl_club_tokens.py:40`
  - `watch_unknown_submit.ps1:40`
- Every one except the two in bold is an ad-hoc or research script. They break only when someone runs them, and they
  break loudly (`FileNotFoundError`).
- Fixtures, inert: `tests/test_publish_parity.py:15-21`, `tests/test_football_sim_engine.py:414,454`,
  `tests/test_refresh_odds_sources.py:231`.
- Prose and history, left alone: `README.md`, `docs/`, `.syndicate/`, `logs/*.log`, `RENDER_SELF_HOST_*.md` (an older
  `c:/Users/mostg/...` path), and `data/**` JSON.

**Sibling-repo fallback** [M]:
- `scripts/refresh_odds_sources.py:44` sets `WORKSPACE_ROOT = REPO_ROOT.parent`. `_source_repo_root` (`:542-549`) falls
  back to `<WORKSPACE_ROOT>/NFL-Betting` and `/NCAAFCompare`.
- `scripts/unified_daily_update.ps1:4315` does the same through `Resolve-WorkspaceRepoPath`.
- After the move the parent is `C:\Users\tempadmin\Coding`, where those siblings do not exist. The fallback degrades with
  a printed "skipped" (`:4318`); it does not crash. It applies only to local runs with no hosted root and no
  `SYNDICATE_SOURCE_ROOT_<SPORT>`.
- Fix: move `NFL-Betting`, `NCAAB` and `NCAAFCompare` beside the repo in the same window. That also takes them off
  OneDrive. Alternatively, set the env vars.

### 3e. WSL fleet (`/home/amyn/Syndicate`, `~/syndicate-prod`), probed by key name only, no values printed [M]

- The fleet repo is its own clone (`origin` → `github.com/mostgood1/Syndicate`). No crontab.
  `\SyndicateLocalProduction` runs `cd ~/Syndicate`. **The fleet code does not live in OneDrive.**
- `local_production.env` has exactly two OneDrive-valued keys:
  - **`:82 SYNDICATE_DEPLOY_CLAIM_DIR` → the Windows repo's `.syndicate/deploy_claims` (load-bearing).** If that
    directory goes missing:
    - `deploy_claim.py` on the fleet ignores it (`:143`, `path if path.is_dir() else None`) and writes to
      `~/Syndicate/.syndicate/deploy_claims`. **The lock splits silently.**
    - `local_production.deploy_claim_dir` (`:1398-1407`) returns it unchecked, so `down` and restart guards read
      "unclaimed".
    - Handled by R5.1 in the same run. The fleet's CLI commands re-read the env file on each call (`:1636`).
    - The running supervisor's `up` read it once at start (`cmd_up` `:1244`, env read `:1260`) [B]. Its stale copy only labels
      `role_restarts.jsonl` entries (`record_role_event`, `:1441-1443`) until the next supervisor start [B, code read].
      No restart is needed for the move.
  - `:190 SYNDICATE_LOCAL_BACKUP_OFFDISK_DIR` → `OneDrive/SyndicateBackup`, **not** the repo. **Not touched; it must not
    be.** The nightly archive (09:15Z = 03:15 CST) keeps landing there.
- The only other `/mnt/c/.../OneDrive/Coding/Syndicate` references on the fleet are ad-hoc scripts
  (`copy_backfill_to_fleet.py:35`, `e3_history_loaders.py:57`; nothing imports the latter [M]) and stale
  `ci-checkout/reports/intelligence/*.json`. Not runtime.

### 3f. Claude Code memory and session history [M]

- `C:\Users\tempadmin\.claude\projects\`: **58** folders keyed `C--Users-tempadmin-OneDrive-Coding-Syndicate*` (the root
  plus one per `.claude\worktrees\*` session).
  - The root holds **142 memory files** and the transcripts (~4.35 GB at 11-02).
  - The key is the cwd with every non-alphanumeric character replaced by `-`. This session's own folder,
    `...-Syndicate--claude-worktrees-zealous-austin-3b6ba5`, fits that rule.
  - New key: `C--Users-tempadmin-Coding-Syndicate`. It does not exist yet [M].
- **Carry-over:** R5.3 **copies** each folder to its new key and leaves the old one as a fallback.
  - `MEMORY.md` has one relative link (`../../../../OneDrive/Coding/Syndicate/docs/...`), which R5.3 fixes.
  - `scripts/release_phantom_lane_claims.py:62` hard-codes the old key. After the move it reads the stale copy (§4 F3).
- **Session history:** the session store holds **1,478 `local_*.json` records, all with an OneDrive cwd; 965 archived**
  [M] (11-02: 1,419). R5.5 rewrites `cwd`/`originCwd` in place, with the app closed and a snapshot taken first.
  - Whether the app accepts hand-edited records is [B]. If it does not, the transcripts still exist under the new
    project key, and new sessions start fine at the new path.
- **Desktop config** [M]:
  - `git-worktrees.json`: 137 hits.
  - `claude_desktop_config.json:99,102,247,250,251`: permission-mode grants.
  - User `~/.claude/settings.json:152,153,159-161,204,292,307` and the **auto-mode trust rules `:358,:360`**.
  - All handled by R5.4/R5.5.

### 3g. Size

- 11-02 measured ~98 GB for the repo, with `vendor/` at 64.9 GB / 34.5k files. **Now: 413,700 files under the repo, 413,673 of them OneDrive placeholders** (pinned, 0 dehydrated) [M, reviewer scan 11-04].
- **`vendor/` is still 61 GB on disk now [M, `du -sh`].** It holds `data`, `mlb_bettingv2`, `nba_betting_repo`,
  `nhl_betting_repo`, `wnba_betting_repo` and `upstream_sync.json`. Git deleted those trees 10-19/10-20 (CLAUDE.md), so
  what remains is untracked or ignored leftovers.
  - A rename moves it for free.
  - It makes the robocopy fallback ~2x heavier.
  - Deleting or archiving it is a **separate** decision. It is not part of this lane, and the user decides it after
    checking that nothing reads it (memory `feedback_scan_the_parent_path_piece`: grep `vendor` too).
- **OneDrive file count, measured 2026-11-04 (`find -type f` per folder, read-only; the scan finished ~15:55Z) [M]:**
  **~509,800 files**, not the ~350k the brief assumed. It has crept back up since the 10-29 shrink to ~389k.

  | Folder | Files |
  |---|---|
  | `Coding/Syndicate` | 413,952 |
  | ...of which `.claude/` (worktrees) | 322,263 |
  | ...of which `data/` | 42,715 |
  | ...of which `vendor/` | 34,533 |
  | ...of which `.git/` | 6,634 |
  | `Coding/NCAAB` | 86,891 |
  | `Coding/NFL-Betting` | 6,354 |
  | `Coding/NCAAFCompare` | 1,839 |
  | everything else | < 1,000 |

  - **After the move, ~95,900 files remain**, well under 300k, so V6 passes without F4.
  - F4 (moving the siblings too) would take it to ~1,000. NCAAB alone is 86,891.

---

## 4. Required before the next attempt

| # | What | Why | Who |
|---|---|---|---|
| **F1** | Change the `\Syndicate inplay nightly` task to pass `--repo C:\Users\tempadmin\Coding\Syndicate` (argparse `inplay_nightly.py:133`). Alternatively, land the `REPO` fix on `origin/main` first. **R5.2's in-file rewrite is not enough** | The runner overwrites its own `inplay_nightly.py` with `origin/main`'s copy on each run (`RUNNER_FILES` `:43`, write `:93-94`). The first sync after the move puts the old `REPO` back. From the next night, `git -C <missing dir>` returns 128 without raising, which the code logs as **`SYNC_KEEP … (not on origin/main)`** (`:89`). Self-sync stops silently, under a misleading reason. Confirmed by review | add a line to `run_move.ps1` R5.2 (`Set-ScheduledTask`, args `+ --repo`), user-approved |
| **F6** | **Blocker: in-play recorder `.env`.** `inplay_nightly.py:169-171` launches the recorder **without `--env`**, and the recorder's default is `inplay_recorder.py:93` = the old `.env` path [M, runner copy]. Night 1 after the move, the odds key read raises `FileNotFoundError` and nothing is recorded | land `inplay_recorder.py:93` (default from the repo root, or `SYNDICATE_ENV_FILE`) **and** `inplay_nightly.py:42` on `origin/main` before the window, so the runner's own self-sync carries them. Or make nightly pass `--env` | code lane, before the window |
| **F7** | Harvester `run_harvest.py:40` `PRIMARY` | §3c | derive it from the env, or rewrite it in R5.2 | in the script patch |
| **F2** | Quiesce plan: an attended window, the app quit (§5 R-1) | the two failures | user |
| **F3** | Path-agnostic PR: `REPO = Path(__file__).resolve().parents[1]` (or `--git-common-dir`) for the scripts in 3d, `release_phantom_lane_claims.py:62` derived from the main-tree path. F6 is its must-land subset | It works at both paths, so it is safe to land any time. Without it, ad-hoc scripts fail loudly after the move | a normal code lane |
| **F8** | Patch `run_move.ps1` for S1-S7 in §1b, then `-DryRun` **and** a full non-dry rehearsal on a throwaway repo with one external worktree, outside OneDrive (it exercises R4's real branch) | dry runs skip every line that failed review | user OK to edit the script |
| F4 | Optional: also move `NFL-Betting`, `NCAAB`, `NCAAFCompare` to `C:\Users\tempadmin\Coding\` | 3d sibling fallback, and fewer OneDrive files | user decision |
| F5 | Re-run `run_move.ps1 -DryRun` on the day | worktrees went from 53 to 33, tasks from 52 to 60 since the last dry run | the session running the window |

---

## 5. Runbook

### R-2: the day before
1. Land F3 if it is ready. Patch `run_move.ps1` for F1. **Run `-DryRun`** and read `move.log`. It must end `DRY RUN OK`.
   The fleet line must read `fleet key lines on old path: 1`.
2. Ledger notice in `lanes.md`: "repo moves at <window>; land or commit by <window-30m>; the app will be quit." Peers
   read the ledger. Messages wait for a turn to end (memory `feedback_coordinate_with_parallel_sessions`).
3. Sweep `C:\tmp\syndicate-sessions\*` and `.claude\worktrees\*` with `git status --porcelain`.
   - The rename keeps uncommitted work, so this is not a blocker.
   - It lists what to re-check afterwards.
   - Push any local-only branch worth keeping, or rely on the 04:00 dev-backup bundle, which already covers all refs.

### R-1: quiesce (at the window)
1. `py -3 scripts/deploy_claim.py status`: all free. Hold the window if not.
2. `mcp__ccd_session_mgmt__list_sessions`: none mid-turn.
   - A session that is mid-turn is either allowed to finish its turn, or stopped (`stop_session`). Never stop one that
     is in a deploy or a git rebase.
   - In-flight git markers are checked again by the script.
3. **Check the fleet for an in-flight sim or a deploy.** The move does not touch the fleet, but nothing should take a
   claim mid-window: `check_deploy_safety` → CLEAR, and read the whole output (memory
   `feedback_safety_wait_loop_whole_output`).
4. **Quit the Claude desktop app: tray icon → Quit.** Closing the window is not enough.
   - Confirm `Get-Process claude` returns 0.
   - This is what the two failed nights lacked.
   - **This session (and every in-repo worktree session) ends here.** The rest is run by the user from an external
     PowerShell, or by the task.

### R0-R5: the move (`run_move.ps1`, not dry run)
Start it from an external PowerShell:
`powershell -NoProfile -ExecutionPolicy Bypass -File C:\SyndicateProd\repo_move\run_move.ps1 -WaitUntil <HH:mm, now+15m>`.

Do not use the stored task. Its `-WaitUntil 02:00` gives up immediately if the run starts between 02:00 and 14:00
(`:62`, S8).

The script runs §1's steps in order and stops at the first failure.
- It writes `RESULT.txt`. **`MOVED OK` is the only success.**
- On `FAILED … nothing moved`, nothing changed; restart OneDrive and the app.

### R6: after the script
1. **Start OneDrive.** If it raises a mass-delete prompt ("files were deleted"), choose **keep them deleted**. "Restore"
   re-downloads the whole tree into the old path [B, high].
2. Start the Claude app and open a new session at `C:\Users\tempadmin\Coding\Syndicate`. Run the §8 checks.
3. If F4 was chosen, move the three sibling folders (each a plain rename, with no git pointers into them [B; confirm
   with `git worktree list` first]).
4. Housekeeping (not in the window):
   - Mark `docs/ai_context/git_store_relocation.md` and `scripts/move_git_store.py` superseded.
   - Update CLAUDE.md and `docs/ai_context/end_to_end_context.md` where they state the path.
   - Write the memory note.
   - Delete the old `~/.claude/projects/C--Users-tempadmin-OneDrive-*` folders after 2 weeks.

---

## 6. Move method

| Option | Keeps | Loses or costs | Verdict |
|---|---|---|---|
| **Same-volume rename** (`Move-Item`, R3) | everything: uncommitted work in 33 worktrees, local-only branches, stash, reflog, untracked `.syndicate`, `.env`, `data/` mirror, `reports/` | Worktree pointers are absolute, so `git worktree repair` is needed (R4). The `cldflt` behaviour on a rename out of a sync root is **unmeasured**, which is why the R2 rename test aborts before R3 | **recommended**. The script is built for it |
| Robocopy copy plus later delete | the same | ~2x disk for a while (C: has 128.5 GB free [M]; the tree is ~101 GB [M, `du -sh` 11-04: `vendor/` 61, `.claude/worktrees` 31, `data` 6.2, `.git` 3.1]), so it barely fits unless `vendor/` is set aside first. Slow over ~414k files | fallback if R2 fails |
| Fresh clone plus re-add worktrees | committed, pushed history only | **Loses** local-only branches, the stash (repo-global), reflog-only commits, untracked ledger files (`.syndicate/deploy/preflight`, claims), `.env`, `data/`. It cannot re-add worktrees that hold uncommitted work. Every desktop session's worktree is orphaned | rejected. A clone is a new repo, not a moved one. Measured 09-10: husks alone held records of 413 unreachable SHAs |

A junction left at the old path is rejected as well (11-02 §3). OneDrive syncs a junction's contents on creation [B,
moderate], which would re-upload the tree and reproduce the original stall.

---

## 7. Rollback

`ROLLBACK.txt` in the snapshot folder carries this. Stop the app first.

| Failed at | Rollback |
|---|---|
| Preconditions, R1, R2 or R3 (`FAILED … nothing moved`) | Nothing to undo. Start OneDrive, start the app |
| R4 or later, if fixing forward | `run_move.ps1 -Resume` (S2) re-runs R4+ idempotently. **Never start OneDrive** until `RESULT.txt` reads `MOVED OK` or the rollback below is complete. A restart with the tree gone propagates the delete |
| R4 or later, rolling back | 1. `Move-Item C:\Users\tempadmin\Coding\Syndicate C:\Users\tempadmin\OneDrive\Coding\Syndicate` (OneDrive is still off, so it is a rename back).<br>2. `git worktree repair` with the old paths from `heads_before.tsv`, and restore `hooksPath` from `hookspath_before.txt`.<br>3. Restore the desktop stores, `scheduled-tasks\`, `settings.json` and the runner from the snapshot.<br>4. WSL: `cp local_production.env.bak ~/syndicate-prod/local_production.env`.<br>5. Re-import the watcher task XML.<br>6. Start OneDrive |
| After OneDrive has synced the delete | A local move back still works, but OneDrive would re-upload the tree. **Fix forward instead.** The cloud copies sit in the OneDrive recycle bin for 93 days |

**The fleet step first.** If anything goes wrong after R3, restore or correct `SYNDICATE_DEPLOY_CLAIM_DIR` before
anything else, so that a fleet deploy cannot split the lock.

---

## 8. Verify (all must pass; record the readings in `deploys.md`)

| # | Check | Pass |
|---|---|---|
| V1 | `RESULT.txt` | `MOVED OK …` |
| V2 | `move.log` git verify line | `prunable=0 head_mismatch=0 onedrive_left=0`, worktrees = the dry-run count |
| V3 | **Fleet unaffected:** from WSL, `deploy_claim.py status` lists the same claims as Windows `py -3 scripts/deploy_claim.py status` at the new path. `local_production.py status` shows the same supervisor pid and `started_at` as before the window. The next `data-backup` (09:15Z) archive lands in `OneDrive\SyndicateBackup` and reads synced (state 2/14) | identical; pid unchanged; archive synced |
| V4 | **Deploy guard loads:** in a new session at the new path, run a dry-run `deploy_claim.py status`, then a guard invocation that should block (a deploy-shaped command with no claim) and check that it is refused | refused, with the remedy text |
| V5 | **Scheduled tasks fire:** `list_scheduled_tasks` shows 60 tasks, 35 enabled, `cwd` = new path. Run-now one cheap task; its first message shows the new cwd. `\SyndicateTaskRegistryCheck` next run reports OK. `\Syndicate inplay nightly` log on **night 1 and night 2** (the F1 revert shows only on night 2): `SYNC origin/main=<non-empty sha>` with **0** `SYNC_KEEP` lines, and `recorder.stdout` has no `FileNotFoundError`. A missing repo still prints `SYNC origin/main= changed=[]` with an empty sha | all |
| V6 | **OneDrive count:** `find C:/Users/tempadmin/OneDrive -type f \| wc -l` (read-only). Baseline 11-04: ~509,800; expected after: ~95,900 | < 300,000 |
| V7 | Memory carried: `C:\Users\tempadmin\.claude\projects\C--Users-tempadmin-Coding-Syndicate\memory` has 142 files, and a new session's context lists the memory index | yes |
| V8 | Hooks: a `git commit` in a worktree runs `.githooks` (`git config --get core.hooksPath` = the new path) | yes |
| V9 | No old-path writes: 24 h later, `C:\Users\tempadmin\OneDrive\Coding\Syndicate` still does not exist | absent |

---

## 9. Downtime

| What | Down for |
|---|---|
| Fleet (Render-free local production) | **0**. No restart. The claim dir is mis-pointed for the seconds-to-minutes between R3 and R5.1, while no deploy is running (R-1) |
| Claude desktop app and every session | **~20-40 min** [B]: R-1 quiesce ~5-15 min, script ~2-10 min, R6 checks ~10-15 min. The 11-02 and 11-03 dry runs took 38 s and 28 s without the rename [M, `move.log`]; the rename itself is unmeasured |
| App-scheduled tasks | none fire while the app is quit. Check fixed-time ones in the window afterwards |
| OneDrive | off from R1 until R6.1. Backups written meanwhile upload on restart |

**Suggested window:** a daytime slot the user attends, outside live slates and outside 09:15Z ± 30 min (the nightly
archive). For example, a morning around 07:00-08:00 CST: the fleet backup is at 03:15 CST, the dev backup at 04:00, and
the in-play nightly at 08:00. Pick a gap.

---

## 10. Open unknowns

| # | Unknown | Effect | Mitigation |
|---|---|---|---|
| U1 | Whether `cldflt` makes the rename out of the sync root O(1) or per-file | slow, or a "cloud provider" error | R2 test aborts first; robocopy fallback |
| U2 | Whether the app accepts hand-edited session and task JSON | old sessions may not resume | snapshot restore; new sessions work regardless |
| U3 | Whether OneDrive raises a mass-delete prompt and how | wrong click re-downloads | R6.1 instruction |
| U4 | Supervisor's in-process `SYNDICATE_DEPLOY_CLAIM_DIR` copy | role-event labels only (code read) | next supervisor start picks it up |
| U5 | File count after the move | V6 | measured after |

---

## 11. Decisions for the user

0. ~~OK to patch `run_move.ps1` (F8) and land F6 first.~~ The user said yes on 11-04. The script is done (§1c). F6 landed
   `74767d036`; gate the window on the runner sync (§1c).
1. **Go, and a window** (attended; the app must be quit).
2. **Target:** `C:\Users\tempadmin\Coding\Syndicate` (recommended) or `C:\dev\Syndicate`.
3. **F1:** OK to add `--repo` to the `\Syndicate inplay nightly` task as part of the move.
4. **F4:** move `NFL-Betting`, `NCAAB` and `NCAAFCompare` beside the repo too?
