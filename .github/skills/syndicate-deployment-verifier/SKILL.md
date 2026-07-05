---
name: syndicate-deployment-verifier
description: "Verify Syndicate deployment state and local-versus-Render parity. Use when a fix works locally but Render looks stale, when the deployed revision may be old, or when public artifacts do not match the current repo and data roots."
---

# Syndicate Deployment Verifier

Use this skill when the question is whether the deployed app is actually serving the code and artifacts you expect.

## Workflow
1. Identify the route, artifact, or payload that looks stale.
2. Check the local file or response contract first, and reproduce the behavior in a local Render-emulated environment when runtime shape or startup behavior could matter.
3. Compare deployed revision, published artifacts, and data-root expectations after the local runtime-equivalent check.
4. Distinguish code drift from stale mirrors, stale deployment, or a runtime-equivalence mismatch.
5. End with a concrete parity statement: local only, deploy only, runtime-equivalent local only, or full parity.

## Good fits
- Render mismatches.
- Stale public payloads.
- Suspicion that a push landed without the needed artifacts.
