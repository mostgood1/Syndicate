---
name: syndicate-deployment-verifier
description: "Verify Syndicate deployment state and local-versus-fleet parity. Use when a fix works locally but the fleet (production, http://127.0.0.1:10000) looks stale, when the deployed revision may be old, or when public artifacts do not match the current repo and data roots."
---

# Syndicate Deployment Verifier

Use this skill when the question is whether the deployed app is actually serving the code and artifacts you expect.

Production is the local WSL fleet `[since 2026-09-30; Render is retired]`. Pushing to `main` ships nothing: the fleet runs the commit its checkout `~/Syndicate` was fast-forwarded to (an exact-SHA `git merge --ff-only <sha>`), and an ff alone reaches web only at its next worker recycle or a `local_production.py reload-web`. A `/versionz` behind `main` is expected until someone deploys.

## Workflow
1. Identify the route, artifact, or payload that looks stale.
2. Check the local file or response contract first, and reproduce the behavior in a local fleet-equivalent run (same role env and worker/web split, paper money only: `scripts/fleet_local.py`) when runtime shape or startup behavior could matter.
3. Compare the deployed revision (web's `/versionz` at `http://127.0.0.1:10000`; `scripts/deploy_preflight.py` reads each role's loaded commit), published artifacts (`/api/ops/artifacts/export` on the fleet), and data-root expectations (`~/syndicate-prod/data`) after the local runtime-equivalent check.
4. Distinguish code drift from stale mirrors, stale deployment, or a runtime-equivalence mismatch.
5. End with a concrete parity statement: local only, deploy only, runtime-equivalent local only, or full parity.

## Good fits
- Fleet mismatches: local code or artifacts versus what `http://127.0.0.1:10000` serves.
- Stale public payloads.
- Suspicion that a deploy landed without the needed artifacts.
