# Render retirement — nothing in the repo or fleet operations needs Render

`[2026-11-15 / 11-16Z, lane render-retirement, session 6786c5e2; todo #766]`

**User, 2026-11-15:** "we shouldnt be using render for anything anymore", then "render
shouldnt be needed". This lane re-derived the 2026-11-07 inventory
(`findings_2026-11-07_render_dependency_inventory.md`) against `origin/main` and acted
on it. No Render API was called, no Render service was touched, `render.yaml` was not
edited, and nothing was loaded onto the fleet (every change is operator tooling, a
comment, or a fallback the fleet overrides).

## Where it stands

| inventory item | now |
|---|---|
| §2.3 operator scripts that call `api.render.com` | **21 deleted** (+8 test files): `docs/ai_context/render_retirement.md` lists each, its last commit and the fleet replacement. Checked first for importers, OPEN-lane / skill / command / agent / hook references, the 49 enabled Claude scheduled tasks and the Windows Task Scheduler: none live. |
| `snapshot_render_env.py` + `local_production.py import-render-env` | **deleted**. The snapshot files are untouched; see D5. |
| `_pipeline_diag.py` + `artifact_freshness` / `diagnose_betting_pipeline` / `diagnose_sim_pipeline` | **repointed at the fleet**: role-log tails through WSL, commits from `local_production.py status`, kills from `role_restarts.jsonl` and gunicorn's lines, env flags from `/proc/<pid>/environ` (named keys only). Each run once against the fleet. |
| `survey_nhl_club_tokens.py` (fetched ODDS_API_KEY from Render's env API) | **repointed** at the repo `.env`. |
| §3 onrender fallbacks: `_base_url.py` Render-host branch, MLB `daily_update.py` + `eval/` + `smoke/`, `live_lens_loop._wnba_live_box_base_url`, `watch_unknown_submit.ps1`, `sample_request_path_guard.py`, comment/doc sites | **repointed at `http://127.0.0.1:10000`**. `test_base_url`'s allowlist is now empty: no file in `scripts/` may hard-code the Render URL. |
| `.github/workflows/daily-update.yml` manual Render backup pull | **retired**: a GitHub runner cannot reach the fleet, and the fleet's `data-backup` job is the backup. The default dispatch now fails fast with the reason. |
| `deploy_preflight.py --target render`, `check_deploy_safety.py` and `render_logs.py --render` | **Render paths removed**; all three read the fleet only. Preflight run end to end on the live fleet with receipts redirected to a scratchpad: web CLEAR, refresh-worker CLEAR, ci-suite UNKNOWN by design. 443 tests across every file that imports these tools pass. |
| `check_blueprint_drift.py` (deploy-guard, `render.yaml` pushes) | **KEPT** by the 11-08 decision D3. It is the last Render API read in the repo. **D3' below.** |
| §1 the env snapshot `render_env/<role>.json` | unchanged on disk. **D5 below.** |
| §4 the `RENDER_*` markers the fleet fakes | unchanged. **D2' below.** |
| §5 docs | CLAUDE.md says plainly that nothing needs Render; the runbook's env-import and backup paragraphs are rewritten; skills and `.github/skills` links point at the fleet. |

Commits on main: `f9ed2ec0f` (retire scripts), `193df776e` (fallbacks + diagnostics),
`2aba260b6` (deploy tools), and the docs/ledger commit that carries this file.

## D5 — a Render-free source of truth for the role env snapshot (USER DECISION)

**Measured 2026-11-16 02:3xZ on the fleet (counts and modes only, no values):**
- `~/syndicate-prod/render_env/{web,refresh-worker,live-odds-worker}.json`: 88 / 182 /
  148 keys, `fetched_at` 2026-10-01T01:11:3xZ, all mode 600 (plus one 600 `.bak` from
  10-04).
- `~/syndicate-prod/local_production.env`: mode 600, 78 keys, 42 of them `ROLE__KEY`.
- The nightly `backup` copies the DATA ROOT (`~/syndicate-prod/data`) plus a Redis
  dump. Both secrets files live one level up, in `~/syndicate-prod/`, so **neither is
  in any backup**. They exist only on this WSL disk.
- Until today the documented recovery was `import-render-env` from the Render API. That
  command is gone (it is in git at `66b668952` / `f9ed2ec0f^`), and using it would
  contradict the user's instruction anyway. **So a lost WSL disk now loses every live
  venue/API secret, and nothing in the repo can rebuild them.**
- On the fleet host: `gpg` and `openssl` are installed; there is no gpg keyring.

**Options:**
- **E1 (recommended): an encrypted secrets backup beside the data archive.** A
  `local_production.py backup-secrets` step: `tar` the three snapshot files and
  `local_production.env`, encrypt with `gpg --symmetric --cipher-algo AES256` using a
  passphrase FILE the user creates (`~/.syndicate-secrets-passphrase`, mode 600) and
  ALSO keeps in their password manager (the only copy off this machine), and write
  `fleet-secrets-<ts>.tar.gpg` into the off-disk dir (OneDrive `SyndicateBackup`), newest
  N kept. Restore = decrypt + place + `chmod 600`, documented in the runbook. No fleet
  restart if it runs as its own scheduled task or inside the nightly `backup` subprocess
  (which loads code from disk each run). Owed from the user: the passphrase, and OK to
  write an encrypted copy to OneDrive. Note `cmd_backup`'s off-disk section is claimed by
  lane `syndicate-decision-engine`, so a separate step or task is the clean cut.
- **E2: fold the snapshot into a fleet-owned file and drop the Render name** (e.g.
  `<home>/fleet_env/<role>.env`, the layer under `local_production.env`; `render.yaml`
  out of `derive_role_env`). Clearer, but it is a fleet env change: a drained full
  `down`/`up` with a byte-equality check of each role's `/proc/<pid>/environ` before and
  after. It does not by itself fix the backup gap, so it would come with E1, not instead.
- **E3: keep as is.** Recovery from a lost disk = re-issue each key from its provider by
  hand (Kalshi, Polymarket, OddsAPI, ...).

## D2' — the `RENDER_*` markers (USER DECISION; 11-08 decided "keep")

Re-derived at `10094eae0` (subagent, read-only). They are names, not calls: **nothing
reaches Render through them**, so "Render is not needed" is already true of them. What
they still decide on the fleet:

| group | still load-bearing (no neutral key read first) | already covered by a neutral key |
|---|---|---|
| H1 "hosted web" (`RENDER` / `RENDER_EXTERNAL_URL` / `RENDER_SERVICE_ID`) | `syndicate/app.py:299-304` (web would start the intelligence + live-refresh loops: a SECOND board builder on the shared disk), `blueprints/home.py:296-301` (full home overview on the request path), `shared/portfolio_auth.py:88-95` (default auth `required`; credentials also hold it today) | `mlb/nba/wnba cards.py`, `game_board_contract.py` (read `SYNDICATE_WEB_DYNO` first) |
| H2 "hosted storage" (`RENDER`) | `source_roots.py` (repo-mirror fallback roots), `disk_compaction.py:89` (refresh-worker compaction stops), `request_path_guard.py` (only in `--state file` mode) | `refresh_state_store.py`, `blueprints/intelligence.py:211` (via `SYNDICATE_REQUIRE_HOSTED_STORAGE`) |
| S "which service am I" (`RENDER_SERVICE_NAME` / `_ID` / `_INSTANCE_ID`) | `run_refresh_worker.py:4225/4265/4300` (job throttle would count the OTHER worker's jobs), `build_soccer_artifacts.py:1397` (both workers would write one freeze file), `ops_refresh.py:413/424` (launcher ids, liveness falls back to pid+cmdline) | `disk_maintenance`, `win_prob_null_diag`, `artifact_retention` (`SYNDICATE_REFRESH_LANE`); `opportunity_contract_metrics` / `fetch_mlb_oddsapi_local` read `SYNDICATE_SERVICE_ROLE` first, but nothing sets it |
| C "which commit" (`RENDER_GIT_COMMIT`) | records only: `model_version.py:60` (falls back to `git rev-parse`), `deploy_drain`, `worker_shutdown`, `local_production.py status` | — |

33 source files and 37 test files read at least one marker. No OPEN-lane claim covers a
marker-reading line.

**Options:** (1) a `service_identity` helper that reads neutral keys
(`SYNDICATE_SERVICE_ROLE`, `SYNDICATE_HOSTED`, `SYNDICATE_INSTANCE_ID`,
`SYNDICATE_GIT_COMMIT`) first and `RENDER_*` second, every site repointed, both key sets
set by `local_production.py` for one release, the `RENDER_*` reads deleted after a fleet
restart proves equivalence (an off != on test per predicate); a drained full `down`/`up`;
(2) the helper and neutral keys only, `RENDER_*` kept as a permanent fallback; (3) keep
the markers, documented as the fleet's role convention (the 11-08 decision).
**Recommendation: (3).** Render is not needed for them; the rename buys clarity, not
capability, and the silent failure modes above are all on a live-money fleet. (1) is a
lane of its own if the user wants the names gone.

## D3' — the last Render read: `check_blueprint_drift.py` (USER DECISION; 11-08 decided "keep")

On a `render.yaml` push, `deploy-guard.py` runs it; it reads the suspended services' env
from the Render API (needs `RENDER_API_KEY`) and any non-zero exit BLOCKS the push
(override `SYNDICATE_ALLOW_BLUEPRINT_DRIFT=1`). Without a key it already blocks. On the
fleet a `render.yaml` VALUE edit is inert (learnings 2026-11-08); a push's only possible
effect is `blueprint_sync` on the suspended Render services, if the blueprint is still
linked.
**Options:** (a) retire it: the guard blocks EVERY `render.yaml` push outright, with an
explicit override and a reason, and no Render read remains anywhere; (b) keep it (11-08).
**Recommendation: (a)**, because it removes the last place the repo needs Render, and
"never push `render.yaml`" is already the rule. Separately, the user may unlink the
blueprint in the Render dashboard; that is their action, not a session's.

## Follow-ups (not decisions)

- `deploy_preflight._api_key` / `_get` remain as refusals ONLY because
  `tests/test_live_mechanism_outcome_gate.py` (claimed by OPEN lane `gate-smooth-family`)
  patches those names. That lane should drop its two `mock.patch.object(..., "_api_key"
  / "_get", ...)` lines; then delete both stubs.
- `render.yaml` comments still say "Verify with scripts/audit_blueprint_drift.py" (9
  sites). Not edited: a `render.yaml` push is gated and may fire `blueprint_sync`.
- Historical comments that name the onrender host remain in
  `poll_basketball_momentum.py:718`, `request_path_guard.py:31` and
  `venue_quote_fanin.py:130`. They describe the past and change nothing.
- `scripts/fleet_local.py` (the 09-02 `#625` runner, superseded by `local_production.py`)
  still reads the deleted producer's snapshot format. Only its hint was changed.
