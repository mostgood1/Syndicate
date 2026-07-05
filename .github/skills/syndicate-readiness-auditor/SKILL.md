---
name: syndicate-readiness-auditor
description: "Audit Syndicate readiness, mirror coverage, advanced inputs, and migration-gate blockers. Use when checking whether required artifacts exist, whether an active sport should block the gate, or whether local readiness matches the intended deployment contract."
---

# Syndicate Readiness Auditor

Use this skill when the task is about release readiness, migration gates, artifact coverage, or whether the current mirrors and advanced inputs are sufficient.

## Workflow
1. Determine the active sports and selected date.
2. Inspect the artifact paths the feature actually consumes, not just adjacent files.
3. Separate active-slate blockers from off-season or zero-game sports.
4. Confirm tracked versus untracked artifact expectations.
5. Validate the readiness path in a local Render-emulated environment when deployment runtime, disk layout, env vars, or worker/web split behavior could affect the gate.
6. Validate with the migration gate or the narrow readiness test slice after the runtime-equivalent local check.

## Typical outputs
- Missing artifact list.
- Active-sport readiness summary.
- Minimal fixes required for the gate to pass.
