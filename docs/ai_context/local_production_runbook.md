# Local production runbook: Syndicate on one machine

Lane `local-production-host`, 2026-09-30. On 2026-09-30 at 06:37:51Z Render suspended all three services for billing: web `srv-d88ahvrbc2fs73eodu30`, refresh-worker `srv-d91dpertqb8s73co8ls0` and live-odds-worker `srv-d91dpertqb8s73co8lt0`. This runbook moves production onto one machine you own. The tool that does it is `scripts/local_production.py`.

---

## 1. Assessment: what production is, and what changes locally

### What Render ran (render.yaml plus the dashboard)

| Render service | plan | start command | local role |
|---|---|---|---|
| `syndicate` (web) | standard, 2 GB | gunicorn `wsgi:application`, 2 workers × 4 threads | `web`: gunicorn on Linux/WSL2, waitress on native Windows |
| `refresh-worker` | pro, 4 GB | `scripts/run_refresh_worker.py` | `refresh-worker` |
| `live-odds-worker` | standard, 2 GB | `scripts/run_live_odds_refresh_worker.py` | `live-odds-worker` |
| `syndicate-refresh-state` | keyvalue | Redis | local `redis-server` (or Memurai), started by `up` |
| `model-scorecard` cron (dashboard only) | `30 11 * * *` UTC | `publish_model_scorecard.py --publish --verify` | a scheduled job inside `up` |
| `sim-input-reports` cron (dashboard only) | `0 7 * * *` UTC | `publish_sim_input_reports.py --publish --verify` | a scheduled job: `--no-pull` (inputs are already on the shared disk) |
| `ci-suite` cron (dashboard only) | `0 8 * * *` UTC | `run_ci_suite.py --pytest-chunks 8 --pytest-workers 0` | a scheduled job: `local_production.py ci-run`, in `<home>/ci-checkout` with a scrubbed env |
| `mlb-season-artifacts` cron (dashboard only) | `0 9 * * 1` UTC | `publish_mlb_season_artifacts.py --publish --verify` | a scheduled job (Mondays), builds straight into the data root; needs `pybaseball` in the venv |
| Render's per-service disks | — | — | `data-backup` job, `09:15` UTC daily: `local_production.py backup` (section 4) |
| three 50 GB disks, one per service | — | — | **one** shared data root |

The three services run the **same code** with **different environments**. The environment decides which loops run where. For example, the intelligence loop runs only on refresh-worker, the live-odds loop and the MLB refresh tick only on live-odds-worker, and the MLB sim, weekly sports and look-ahead only on refresh-worker.

So the local tool does not hand-write any run-mode. It reads `render.yaml` at start, service by service. It then layers on each service's **live** dashboard env if you import it (section 3), and after that your local overrides.

### Changes from Render, and why each one is there

| Change | Why |
|---|---|
| `/opt/render/project/data/*` becomes `<home>/data/*`, the same path for all three roles | There is one disk. Readers resolve artifacts from `data_root()` directly. |
| `SYNDICATE_WEB_PUBLISH_URL` is **removed** | On Render, workers pushed files to web and pulled them back over HTTP because the disks were separate. On one disk that path is **harmful**, not merely redundant: the publish receiver `os.replace`s and merges the very file the worker is appending to, so rows appended during a merge are lost. With the URL unset, the publisher logs `*_SKIP_NOT_CONFIGURED` and does nothing, which is correct here. |
| `SYNDICATE_INTERNAL_WEB_BASE_URL`, `SYNDICATE_WNBA_LIVE_BOX_BASE_URL` and `SYNDICATE_BASE_URL` point at `http://127.0.0.1:<port>` | Unset, the code falls back to the public `syndicate-an21.onrender.com`, which is suspended. |
| `RENDER=true`, plus `RENDER_SERVICE_NAME`, `RENDER_SERVICE_ID`, `RENDER_INSTANCE_ID` and `RENDER_GIT_COMMIT` per role | The code branches on these. They turn on the request-path compute guard, required portfolio login and disk compaction. Most importantly, without a marker **web starts the intelligence and live-refresh loops on its first request whatever their flags say** (`syndicate/app.py _start_background_loops`), and you get a second board builder on the same disk. |
| State store: a local Redis on `127.0.0.1:6379` | Production is keyvalue. With `RENDER=true`, the workers refuse a file backend. |
| Bootstrap runs **once** in `up`, before any role starts, and `SYNDICATE_BOOTSTRAP_ON_START=0` inside the roles | This is the same seed-only copy of the checkout mirror that Render ran at boot. Existing files are never overwritten. It runs once instead of racing on one disk. |
| Money is **always paper** unless you pass `up --allow-live-execution` | The live services ran `SYNDICATE_EXECUTION_MODE=live` and `LIVE_ARMED=1` with real Kalshi and Polymarket keys. Importing that env must not, by itself, arm real orders on a new machine. |
| `RENDER_API_KEY` is never passed to any role | A local fleet must not act on the Render account. |
| The `model-scorecard` job runs **without** `--publish` | `--publish` self-publishes over HTTP onto the file its own `write()` already wrote to disk. |

### What does NOT carry over (read before trusting anything)

1. **Data that existed only on Render's disks.**
   - Examples: `mlb_source/tracking/book_quotes` (about 330 MB/day, the only line-movement record), the evaluation and execution ledgers, `reports/intelligence/opportunity_population/*`, `reports/live_gameline_accuracy/history.jsonl` and `feed_live`.
   - The git `data/**` tree is a *lossy, per-family-windowed mirror* (CLAUDE.md). Everything local starts from it, and history rebuilds from today onward.
   - The only way to recover the disk-only data is `/api/ops/artifacts/export`, which needs the web service **running**. That means paying the bill and unsuspending long enough to export. **Decide this first. It is a billing decision only you can make.** If you do it, pull over the private path or accept the egress (August egress was about 2.1 TB against a 25 GB allowance, so scope the export with `names_only=1` and explicit families).
2. **The Render keyvalue contents** (run manifests, watermarks, lane state). A fresh Redis starts empty. Everything in it is rebuildable state, not records.
3. **Memory ceilings.**
   - Render's 2/4/2 GB cgroup limits were what the memory guards read.
   - **CORRECTED 2026-09-30 (first native-Windows run):** with no cgroup limit, those guards did NOT "let everything through". Every headroom gate treats unmeasurable as insufficient and failed CLOSED: game-chip publishing skipped 34/34, MLB overview isolation was refused, and the MLB daily sim starved on `intelligence_pipeline_busy_and_no_headroom`.
   - `up` now gives each role `SYNDICATE_LOCAL_MEMORY_LIMIT_MB` = its old Render plan (2048/4096/2048). Where no cgroup limit is readable, `memory_observability` measures the role's process-tree RSS (psutil) against that ceiling, so each gate trips where it did on Render. Render never sets the key. Override it in `local_production.env`.
   - `status` shows each role's RSS next to its old plan size so you can watch the ratchet.
   - Web's gunicorn `--max-requests` and anon-memory recycle still apply under gunicorn.
4. **Native Windows** (use WSL2 instead, section 2):
   - Process liveness and the file locks are no longer a Windows gap (fixed `67b5f471`, lane `windows-process-liveness`). Every liveness check goes through `syndicate/features/shared/process_liveness.py`, which uses OpenProcess on Windows instead of `os.kill(pid, 0)` (that is CTRL_C_EVENT there). The book-quote and portfolio-books locks take an `msvcrt` lock instead of being skipped.
   - Install psutil (`requirements-dev.txt`) on a native Windows host. Without it the PID-reuse check cannot read a process's command line, and it assumes a match (fails open).
   - `os.replace` onto an open file fails intermittently.
   - Gunicorn does not run, so web is served by waitress.

---

## 2. Setup (Windows host, WSL2 recommended)

WSL2 is the supported host. Everything in section 1's Windows row goes away, gunicorn runs exactly as on Render, and Redis is native.

```powershell
# PowerShell (admin), once
wsl --install -d Ubuntu
```

```bash
# Inside Ubuntu (WSL2)
# Ubuntu 24.04 ships Python 3.12 and has no python3.11 package: add deadsnakes first.
# Run this INSIDE Ubuntu; Windows PowerShell 5.1 rejects `&&` (the 2026-10-01 setup hit that).
sudo add-apt-repository -y ppa:deadsnakes/ppa && sudo apt update && sudo apt install -y python3.11 python3.11-venv python3.11-dev build-essential redis-server
# Clone INSIDE the Linux filesystem, not /mnt/c (10x faster I/O, and not OneDrive):
git clone https://github.com/mostgood1/Syndicate.git ~/Syndicate && cd ~/Syndicate
python3.11 -m venv ~/.venvs/syndicate && . ~/.venvs/syndicate/bin/activate
pip install -r requirements.txt psutil waitress pyyaml
```

Native Windows fallback (no WSL):

- `py -3.11 -m pip install -r requirements.txt psutil waitress pyyaml`
- Install **Memurai Developer**, which is Redis-compatible and runs as a Windows service. Alternatively, run `up --state file`, which clears `RENDER`; section 1 lists what that turns off.
- Keep `SYNDICATE_LOCAL_HOME` **out of OneDrive**. The default is `%LOCALAPPDATA%\SyndicateProd`.
- **Found on the first native-Windows run (2026-09-30, lane `local-production-first-run`):**
  - **Clone at least two directories below the drive root**, e.g. `C:\SyndicateProd\repo\Syndicate`. At `C:\Syndicate`, web crashes on import with `IndexError: 3`, because `pipeline/intelligence_state.py` calls `repo_root_from(__file__)` = `parents[3]` (`#313`). On Render that resolves to `/opt/render`, so the clone depth reproduces Render and the code is left alone. `doctor` now checks it.
  - **Do not use the `%LOCALAPPDATA%` default when running from the Claude desktop app** (or any MSIX-packaged shell). Writes there are redirected into `...\AppData\Local\Packages\<app>\LocalCache\Local\`, so the data root is invisible to your own shells and is deleted with the app. Set `SYNDICATE_LOCAL_HOME=C:\SyndicateProd\home` for every command.
  - `--state` is a **global** flag and goes before the subcommand: `local_production.py --state file doctor`.

## 3. Configure

```bash
python3 scripts/local_production.py init
```

- `init` creates `<home>`:
  - `~/syndicate-prod` on Linux/WSL, or `%LOCALAPPDATA%\SyndicateProd` on Windows.
  - Override with `SYNDICATE_LOCAL_HOME`, and pick it **once**: the Redis keys embed the absolute data-root path.
- It also writes `<home>/local_production.env`, a template listing every key the blueprint declares without a value, plus the dashboard-only keys the code reads. It generates a fresh `ADMIN_TOKEN`.

**For full parity, import the live env.** The Render API still answers for suspended services, and the blueprint was about 166 keys behind live:

```bash
RENDER_API_KEY=... python3 scripts/local_production.py import-render-env
# or: --env-file /path/to/.env   (the repo's gitignored .env on your Windows checkout holds it)
```

- This writes `<home>/render_env/{web,refresh-worker,live-odds-worker}.json` with real values, mode 600, outside the repo. **Never commit these files.**
- It is read-only against Render.
- Anything in `local_production.env` overrides the imported values. Use it to change a single key, such as your own `ADMIN_TOKEN` or turning an autorun off.

Without an import, you must set these yourself in `local_production.env`. `doctor` lists what is absent per role.

| key | role | note |
|---|---|---|
| `EVALUATION_SETTLEMENT_ENABLE_REFRESH_WORKER_AUTORUN` | refresh-worker | Absent means OFF. Do NOT set `EVALUATION_SETTLEMENT_REFRESH_INTERVAL_SECONDS` at all: any value overrides the daily gate (CLAUDE.md #284). |
| `RECONCILIATION_ENABLE_REFRESH_WORKER_AUTORUN`, `RECONCILIATION_ENABLE_MLB_ACTUALS_WRITER` | refresh-worker | The ledger records `=true` on live. |
| `SYNDICATE_ENABLE_SOCCER_WEEKLY_REFRESH_AUTORUN` | refresh-worker | The ledger records `true`. |
| `SYNDICATE_ENABLE_SOCCER_PREGAME_REFRESH_AUTORUN` | live-odds-worker | The ledger records `true`. |
| `ANTHROPIC_API_KEY` | web | Ask the Syndicate. Absent means snapshot-only answers. |
| `KALSHI_*`, `POLYMARKET_US_*` | workers | Venue quotes. Orders happen only when live-armed. |
| `SYNDICATE_PORTFOLIO_USERNAME`, `SYNDICATE_PORTFOLIO_PASSWORD_HASH` | web | Required: with `RENDER=true`, `/portfolio` returns 503 until they are set. |

## 4. Run

```bash
python3 scripts/local_production.py doctor   # must print READY
python3 scripts/local_production.py up       # foreground; Ctrl-C stops everything cleanly
```

`up` does the following:
1. Starts Redis if nothing answers (persistent, AOF, loopback only). If a Redis already answers (the WSL host's apt/systemd `redis-server`, which ships `appendonly no`), `up` turns AOF on with `CONFIG SET` + `CONFIG REWRITE` and prints `[redis] aof=...`.
2. Seeds the data root (first run: about 2 GB, a couple of minutes).
3. Starts web and waits for `/healthz` 200.
4. Starts both workers.
5. From then on:
   - restarts any role that exits, with backoff from 5 s up to 5 min;
   - rotates logs at 200 MB -- at spawn by rename, and every minute by copy+truncate for a role that never exits (refresh-worker);
   - runs `SCHEDULED_JOBS` (the four Render dashboard crons plus `data-backup`), each once on its UTC day at the first tick at or after its time. `status` lists each job's last run and rc, and flags a role whose loaded commit is not HEAD (`STALE`). A gunicorn `HUP` loads new code but keeps the old `RENDER_GIT_COMMIT`, so `STALE` on web after a HUP means "stamp", not necessarily "code".

**Backups** (`local_production.py backup`, also the nightly `data-backup` job). It runs in two stages:
- **Snapshot:** rsync the data root, plus `redis-cli --rdb`, into `SYNDICATE_LOCAL_BACKUP_DIR` (default `<home>-backup`, the same filesystem as the data root). Each snapshot is hard‑linked against the previous one, so an unchanged file costs nothing. The newest 7 are kept (`--keep`). A snapshot stays `<ts>.partial` until its `manifest.json` (file counts, bytes, rsync rc, commit) is written.
- **Off‑disk archive:** the newest snapshot is `tar | gzip -1`'d into ONE file in `SYNDICATE_LOCAL_BACKUP_OFFDISK_DIR` (default `/mnt/c/SyndicateBackup` on WSL). The newest 2 are kept (`--offdisk-keep`). The WSL disk is one VHDX file, so this archive survives a lost or unregistered distro. It is still the same physical disk, so for disk failure, copy `C:\SyndicateBackup` to a second drive or off the machine.

**Why not rsync straight onto `/mnt/c`:** WSL mounts it as 9p with `uid=0` and no metadata, so every utime from the WSL user is refused. Measured 2026‑10‑01: 2,946 `failed to set times` errors in 4 minutes, with 2,768 of ~41k files copied. Without mtimes, `--link-dest` never matches. Secrets (`render_env/`, `local_production.env`) are deliberately not in it: re-import them with `import-render-env`.

live-odds-worker exits by design every 6 h (`SYNDICATE_LIVE_ODDS_WORKER_MAX_UPTIME_SECONDS`), and the supervisor restarts it. That is expected, not a crash.

Operations:

```bash
python3 scripts/local_production.py status            # pids, RSS vs old plan, /healthz, log tails
python3 scripts/local_production.py down              # from another shell
python3 scripts/local_production.py env --role refresh-worker   # exact env a role gets (secrets masked)
tail -f ~/syndicate-prod/logs/refresh-worker.log
```

Start at boot and restart on failure:

- **Windows, native** (measured 2026-09-30, lane `local-production-boot-task`: the task started the fleet, `/healthz` 200 in 85 s, same home reused): `powershell -ExecutionPolicy Bypass -File deploy\local\install_windows_task.ps1 -Mode Native -LocalHome C:\SyndicateProd\home -GlobalArgs '--state file' -Python <path to python311-x64\python.exe>`. All three flags are needed, and the script header says why. The trigger is **at logon**. Starting at boot with nobody signed in requires "Run whether user is logged on or not", which asks for your Windows password, so set it yourself in Task Scheduler.
- **Windows, running WSL2** (the production host since 2026-10-01, lane `local-production-wsl`): `powershell -ExecutionPolicy Bypass -File deploy\local\install_windows_task.ps1 -Mode Wsl -WslDistro Ubuntu-24.04 -WslRepo '~/Syndicate' -LocalHome '~/syndicate-prod'`. This uses the venv python (`-WslPython`, default `~/.venvs/syndicate/bin/python`); Ubuntu's own `python3` has none of the requirements. Measured: gunicorn 2x4 with `WEB_MEMORY_GUARD_ARMED`, `REFRESH_STATE_BACKEND = keyvalue` on both workers against apt's redis-server 7.0.15 (a systemd unit, so `up` finds it already answering), and `/healthz` reachable from Windows on `127.0.0.1:10000` through WSL localhost forwarding.
  - **WSL distros are per Windows account.** Install Ubuntu as the account the task runs as, or the task sees no distro.
  - **Cloning from a Windows checkout under `/mnt/c`** trips git's ownership check (`dubious ownership`), and `-c safe.directory` is NOT inherited by the clone's upload-pack. A throwaway `GIT_CONFIG_GLOBAL` file holding the exception works and leaves `~/.gitconfig` alone. Expect about 90 MB/min across `/mnt/c`.
  - **Migrating a native data home:** rsync it over and exclude `*.lock` and `*.pid`. A Windows PID in a lock would be checked against Linux processes. Seed-only bootstrap then fills in only what is missing, so the migrated files win.
  - This registers a logon task that runs `up` in WSL and restarts it every minute on failure.
  - Also run `powercfg /change standby-timeout-ac 0`. Modern Standby suspends scheduled-task children, so the workers silently stop.
- **Linux, or WSL with systemd:** use `deploy/local/syndicate-prod.service`. Install steps are in its header.

**Live money** needs *both* of these; neither alone arms it:
- the env (imported or local) says `SYNDICATE_EXECUTION_MODE=live` and `SYNDICATE_EXECUTION_LIVE_ARMED=1`;
- `up --allow-live-execution`.

`up` prints `money: LIVE` or `money: paper` on its first lines. The day stake caps are stored in the execution store, not in env, and start fresh on a new Redis.

## 5. Exposing the site (optional)

Web binds `127.0.0.1` by default. Do not port-forward it. To serve the public:

1. Install `cloudflared` and create a named tunnel to `http://127.0.0.1:10000` in the Cloudflare dashboard.
2. Put `CLOUDFLARED_TUNNEL_TOKEN=...` and `SYNDICATE_PUBLIC_URL=https://your.host` in `local_production.env`. `up` then supervises the tunnel as a fourth role, and the URL becomes `RENDER_EXTERNAL_URL`.
3. Set portfolio credentials first. `/api/syndicate/query` is public and capped by `SYNDICATE_ASK_LLM_MAX_CALLS`, as on Render.

`.github/workflows/daily-update.yml` (manual trigger) takes a `base_url` input. Point it at the tunnel URL; it still needs the `ADMIN_TOKEN` secret to match your local one.

## 6. Verified in the lane session (Linux container, 2026-09-30)

This is what was measured, and what was not.

**Measured:**
- `init`, then `doctor`, reported READY.
- `up`:
  - Redis started.
  - Bootstrap seeded 1.9 GB in 136 s, rc 0.
  - Web ran under gunicorn 2×4 with `MALLOC_ARENA_INIT` and `WEB_MEMORY_GUARD_ARMED`, as on Render, and `/healthz` returned 200.
  - `/`, `/mlb`, `/nba`, `/nfl`, `/nhl`, `/wnba`, `/ncaaf` and `/intelligence` returned 200.
  - `/portfolio` returned 503, which is correct: `mode=required`, no credentials set.
- Both workers printed `REFRESH_STATE_BACKEND = keyvalue` and wrote about 40 state keys to the local Redis.
- The scorecard job started against `base=http://127.0.0.1:10000` and the local data root.
- RSS after about 3 minutes: web 292 MB, refresh-worker 235 MB, live-odds-worker 552 MB (children included). There were no unplanned restarts. A deliberate `kill -9` of refresh-worker was restarted by the supervisor in 10 s and reconnected to the state store.
- `down` stopped every role and Redis.

**Not measured:**
- Fresh data. That container's egress policy denied The Odds API, ESPN, statsapi and Kalshi, so no odds fetch or sim completed there.
- The first real measurement is on your machine: after about 15 minutes of `up`, check that `data/mlb_source/source_artifacts/data/...` has today's odds snapshot and that the board shows a fresh `generated_at`.
- Record that reading in `.syndicate/deploys.md`. Until then, "local production works end to end" is an unverified belief.
