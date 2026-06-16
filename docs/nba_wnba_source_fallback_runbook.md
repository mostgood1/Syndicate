# NBA/WNBA Source-App Fallback Runbook

This runbook completes NBA/WNBA recovery on Syndicate Render by wiring Syndicate to the working standalone source apps.

This is a compatibility path, not the normal Render data path. The authoritative Render disk layout is documented in [docs/render_data_authority.md](render_data_authority.md).

## What is already in code

Syndicate now supports source-app fallback for NBA and WNBA in these paths:

- `syndicate/features/nba/cards.py`
- `syndicate/features/wnba/cards.py`

Fallback includes:

- Remote `cards` fallback (NBA)
- Remote `live_state` fallback
- Remote `live_player_boxscore` fallback
- Remote `live_player_lens` fallback
- Remote `live_lines` fallback
- Remote `live_pbp_stats` fallback

Flags and envs recognized:

- NBA enable flag: `SYNDICATE_NBA_SOURCE_APP_FALLBACK`
- WNBA enable flag: `SYNDICATE_WNBA_SOURCE_APP_FALLBACK`
- NBA source URL: `SYNDICATE_NBA_SOURCE_APP_BASE_URL`
- WNBA source URL: `SYNDICATE_WNBA_SOURCE_APP_BASE_URL`
- NBA source token: `SYNDICATE_NBA_SOURCE_APP_TOKEN`
- WNBA source token: `SYNDICATE_WNBA_SOURCE_APP_TOKEN`

Compatibility envs are also supported:

- `NBA_BETTING_BASE_URL`, `WNBA_BETTING_BASE_URL`
- `NBA_BETTING_CRON_TOKEN`, `WNBA_BETTING_CRON_TOKEN`
- `CRON_TOKEN`

## Required Render env setup (Syndicate web service)

Set these env vars on the Syndicate Render web service:

- `SYNDICATE_NBA_SOURCE_APP_FALLBACK=true`
- `SYNDICATE_WNBA_SOURCE_APP_FALLBACK=true`
- `SYNDICATE_NBA_SOURCE_APP_BASE_URL=<NBA standalone Render URL>`
- `SYNDICATE_WNBA_SOURCE_APP_BASE_URL=<WNBA standalone Render URL>`
- `SYNDICATE_NBA_SOURCE_APP_TOKEN=<NBA standalone cron token>`
- `SYNDICATE_WNBA_SOURCE_APP_TOKEN=<WNBA standalone cron token>`

Notes:

- Base URLs must be absolute, for example `https://<service>.onrender.com`
- Tokens should match the standalone apps' accepted cron/auth token.

## Verification checklist

After deploy + env update, verify:

1. NBA live state:

- `GET /nba/api/live_state?date=YYYY-MM-DD`
- Confirm `generated_at` is current and game status/score are no longer stale.

2. WNBA live state:

- `GET /wnba/api/live_state?date=YYYY-MM-DD`
- Confirm fresh timestamp and active game progression.

3. NBA cards:

- `GET /nba/api/cards?date=YYYY-MM-DD`
- Confirm card payload has non-empty actionable fields when local artifacts are stale.

4. Browser pages:

- `/nba/cards?date=YYYY-MM-DD`
- `/wnba/cards?date=YYYY-MM-DD`
- Confirm live state and sim/market surfaces are populated.

## If still stale

If responses remain stale after env setup:

- Confirm standalone source URLs are reachable from Syndicate.
- Confirm source token is accepted by standalone app.
- Check Syndicate logs for remote fallback request failures.
- Re-run one targeted refresh after env changes:
  - sports: `nba,wnba`
  - phase: `live`
  - execution_mode: `source`
  - skip_mirror: `true`
