# Findings 2026-11-17 — `scripts/fleet_local.py` env source (lane `fleet-local-env-source`)

Session 4d8c567e (a side session started by local_8aba9e1c). NO DEPLOY: `fleet_local.py` is local tooling; nothing on
the fleet was restarted, written or reconfigured. Every fleet read below was a file read or a TCP connect probe that
sent no bytes; no value from `fleet_env/` was printed (names and counts only).

## The question

A docs pass on 2026-11-17 reported, unverified, that `fleet_local.py up` needs an `--env-snapshot` in the format of
`snapshot_render_env.py`, a producer deleted at the render-retirement (2026-11-15, `f9ed2ec0f`). Does the rehearsal
harness still run? Several `.github/skills/*/SKILL.md` send readers to a "fleet-equivalent run" through it.

## Hypothesis (written into the lane before testing)

1. Every `doctor`/`up` exits at `load_env_snapshot` ("no env snapshot") because its only producer is gone; given a
   hand-made old-format file, the rest still runs.
2. Since the fleet moved onto this machine (2026-09-30), the guard's assumption that "loopback is the rehearsal's own
   roles" is false: :10000 and :6379 answer from Windows, and a worker with no web URL falls back to `_base_url`'s fleet
   default `127.0.0.1:10000`.

Falsification: `doctor` with an old-format snapshot also fails for some other reason, or a guarded child's connect to
`127.0.0.1:10000` is already refused.

## Before (reproduced from a clean worktree at `a8966e439`, scratch mirror `C:\fleetlocal_rehearsal_mirror`)

- `fleet_local.py --mirror C:\fleetlocal_rehearsal_mirror doctor` -> `no env snapshot. Pass --env-snapshot <file.json>.
  Its producer, scripts/snapshot_render_env.py, read the Render API and was retired 2026-11-15`, **rc=1**. `up --bounded`:
  the same, **rc=1**. So the tool could not be run by anyone without a hand-kept Render-era file.
- **H1, not falsified:** with the newest surviving Render-era file (`%LOCALAPPDATA%\syndicate_mirror\env\
  env_20261001T234655Z.json`, 49/125/93 plaintext keys), `doctor` was **READY**. The missing producer was the only break.
- **H2, confirmed:** a guarded, replay-mode live-odds-worker child built by the old `derive_env` CONNECTED to
  `127.0.0.1:10000` (the fleet's web) and `127.0.0.1:6379` (the fleet's Redis, its whole shared state store);
  `_base_url.default_base_url()` returned `http://127.0.0.1:10000` and `SYNDICATE_INTERNAL_WEB_BASE_URL` was unset. A
  rehearsal on this machine could read the live web and write the live state store; only the `--state file` default and
  the absence of a URL kept it from the store.

## A correction to the 2026-09-02 reading

`[local-fleet-runner]` said "production run-modes preserved — 103 / 77 / 37 keys passed through". The old producer kept a
plaintext value only for booleans and for numbers under non-secret names. **Read 2026-11-17 off the 10-01 file:
`SYNDICATE_REFRESH_LANE`, `SYNDICATE_ACTIVE_SPORTS`, `SYNDICATE_LIVE_ODDS_REFRESH_MODE` and `SYNDICATE_DATA_ROOT` had no
plaintext value for any service.** So the string run-modes and every data path were never passed through. On the live
`fleet_env/`, that rule would withhold 19 / 30 / 29 plain-named string keys and 16 / 17 / 16 `{data_root}` paths. The old
test `test_a_withheld_value_can_never_reach_a_child` used `SYNDICATE_REFRESH_LANE` as a plaintext value — a fixture the
real producer never produced.

## What changed (`scripts/fleet_local.py`, `scripts/_fleet_guard.py`, `tests/test_fleet_local.py`)

- **Env construction is the fleet's own.** `derive_env` calls `local_production.derive_role_env` (spec
  `scripts/fleet_role_spec.json` -> snapshot -> the fleet's forced keys), passing `{}` for `local_production.env` (it
  holds the live keys and the live arm; a test fails if `parse_env_file` is called). The settings move the data root to
  the mirror and the run dir under `<mirror>/.fleet_local/home`. The rehearsal overrides then apply: paper / unarmed /
  `ENABLED=0`, credentials dropped from every layer including the operator's shell, inherited `SYNDICATE_*` stripped,
  `SYNDICATE_HOSTED` removed, file backend with `REQUIRE_HOSTED_STORAGE` cleared (what `local_production --state file`
  does), per-sport roots kept only when they resolve inside the mirror. Commands are `local_production.role_command`
  (gunicorn on Linux, waitress on Windows) plus `--run-once` for a bounded worker. Memory caps are
  `local_production.PLAN_MEMORY_MB`. **`render_plan` is gone**, along with the "straight from `render.yaml`" comments.
- **New `snapshot` verb** replaces the retired producer: reads `<fleet home>/fleet_env/<role>.json` once (through
  `local_production.load_env_snapshot`), writes `<mirror>/.fleet_local/env/fleet_env/<role>.json` with only values that
  cannot be credentials (`rehearsal_value_allowed`): a boolean; a `{data_root}`/`{repo_root}` path; or a short value with
  no key-shaped run (16+ alphanumerics mixing letters and digits) under a non-secret name. SHAPE AND NAME, as the 09-02
  producer learned from the ten-digit `ADMIN_TOKEN`. Withheld keys are recorded by NAME only — no hash, since a ten-digit
  token's `sha256` reverses in seconds. `doctor`/`up` refuse a `fleet_env/` without the rehearsal mark (so the live one
  cannot be pointed at them), refuse a single JSON file (the Render-era format, with its history in the message), and
  re-apply the rule on load. Without a snapshot a role is refused unless `--spec-only` says so (absent is not off).
- **Production is on this machine:** the guard denies `FLEET_PORTS` (10000, 6379; pinned by a test to
  `local_production.Settings` defaults) on ANY host in EVERY fetch mode, and refuses (rc=71) a data/reports root inside a
  fleet home or a state URL on a fleet port. The parent refuses `--port`/`--redis-url` on those ports and a mirror inside
  a fleet home; the workers' web URLs are forced to this run's web by the fleet's own forced keys.

## After

- `snapshot` (inside WSL; `fleet_env/` is mode 0700 and not readable from Windows): **83/88, 172/182, 139/148 kept.**
  Withheld: web `ADMIN_TOKEN, ODDS_API_KEY, SYNDICATE_PORTFOLIO_PASSWORD, SYNDICATE_PORTFOLIO_USERNAME,
  SYNDICATE_REFRESH_STATE_URL`; both workers add the Kalshi/Polymarket keys, `CFBD_API_KEY` (refresh-worker),
  `SYNDICATE_WEB_PUBLISH_URL` and `SYNDICATE_PUBLISH_HOURLY_BYTE_BUDGET` (a safe false positive: "HO**URL**Y" contains
  `URL`).
- **Leak check on the live files:** 0 withheld values (length >= 4) appear anywhere in any rehearsal file; every kept
  value is byte-identical to the fleet's.
- `doctor` from Windows: **READY**; per role: guard engaged, money-armed env refused rc=70, :10000 and :6379 refused by
  the guard, fleet data root refused rc=71, worker->web URL = `http://127.0.0.1:5000`, markers `SYNDICATE_SERVICE_ID=
  local-<role>` (web serves; it does not start its own board builder). `doctor` inside WSL with the fleet venv:
  **READY**, web `server=gunicorn`, and the ports refused there too, where the live web actually listens.
- `up --bounded --duration-seconds 120` (Windows, Idle priority): **ok=True**; web 168.7 MB (waitress), refresh-worker
  570.2 MB, live-odds-worker 1004.2 MB, 0 cap breaches; outbound denied 163 / 167 (ESPN, Kalshi, Novig, ...); **fleet-port
  attempts 0**; 0 tracebacks in the three logs. Both workers were still in their single pass when the window closed
  (`exit=None`), so this is a 120-second sample, not a completed pass.
- Tests at Idle: `tests/test_fleet_local.py tests/test_service_marker_readers.py tests/test_fleet_role_spec.py`
  **118 passed**.

## Not reproduced, by design

The venue/OddsAPI/CFBD credentials and the admin token; the hosted-only branches (request-path guard, portfolio auth,
disk compaction), as on the fleet's own `--state file`; gunicorn on Windows. The snapshot is the fleet's
`fleet_env/` as taken 2026-10-01 (it is what the fleet runs); `local_production.env` overrides (78 keys, 42 `ROLE__KEY`)
are deliberately NOT applied, so a run-mode set only there is absent from a rehearsal.

## Leads (not followed)

1. The fleet's `NHL_DATA_DIR` / `NHL_LIVE_LENS_DIR` are checkout-relative (`./...`, 5 and 6 segments; read as prefixes
   only), so the fleet reads NHL from under `~/Syndicate`, not `~/syndicate-prod/data`. The rehearsal drops both
   ("outside the mirror"). Worth a check against `CLAUDE.md`'s "data/** in git is a lossy mirror".
2. Three Render-era snapshot files remain at `%LOCALAPPDATA%\syndicate_mirror\env\` (09-02, 09-09, 10-01). They carry
   `sha256[:12]` of every withheld value, including the numeric Render-era `ADMIN_TOKEN` (the fleet rejects that token,
   per CLAUDE.md). `fleet_local.py` now refuses them. Deleting them is the user's call.
3. `_SECRET_NAME` is substring-based, so `HOURLY` matches `URL`. That errs safe; a segment-aware match would keep one
   more key but also needs care for names like `APIKEY`.
