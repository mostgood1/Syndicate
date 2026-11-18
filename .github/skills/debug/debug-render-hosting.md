# Skill: Debug Production Hosting Issues

> `[2026-11-17]` The filename is historical. Production was hosted on Render until 2026-09-30; it is now the local WSL fleet (`docs/ai_context/local_production_runbook.md`).

## When to Use
- works locally but not in production

## Steps
1. Check the fleet's role logs. Each role writes `~/syndicate-prod/logs/<role>.log`; read a window with `py -3 scripts/fleet_logs.py --service <web|refresh-worker|live-odds-worker> --text <substring> --start <UTC ISO8601>`.
2. Check environment variables. A role's env is built at `up` from `scripts/fleet_role_spec.json` -> `~/syndicate-prod/fleet_env/<role>.json` -> `~/syndicate-prod/local_production.env` -> forced keys, a later layer winning; `python3 scripts/local_production.py env --role <role>` prints it with secrets masked. `render.yaml` is read by nothing. A changed env needs a drained full `down` + `up`; a role restart reuses the old env.
3. verify the code calls the URL production serves (`http://127.0.0.1:10000`, resolved by `scripts/_base_url.py`), not a dev-server port or an `onrender.com` URL
4. confirm external APIs respond in production
5. check `/healthz` and `/versionz` at `http://127.0.0.1:10000`, and `python3 scripts/local_production.py status` (pids, `/healthz`, log tails) in the fleet checkout

## Goal
Catch production-only failures
