# Syndicate — Verified System State

> Overwrite lines here as facts change. Do not stack contradictions.
> Every line carries an evidence tag and a date. Untagged lines are invalid.
> **Seeded 2026-08-13 from prior session notes. Lines marked `[unverified]`
> must be confirmed against the dashboard before anyone relies on them.**

## Config

- Max concurrent open lanes: **3** `[policy]`
- Repo tip: `a9df9f9b` (`a9df9f9b0fa24f08b647e31a76e835df7028500a`),
  `origin/main` at the same commit, 2026-08-13 10:16 -05:00,
  "#401 runner: not a defect -- a 24h interval with 15.6h elapsed".
  `[from-git 08-13]`
- Deployed SHA: **not derivable from git.** `autoDeploy = no` on all three
  services, so the repo tip is an upper bound, not the running commit — and
  each service can sit on a different one. Read
  `/v1/services/<id>/deploys` per service before treating any SHA as
  deployed. `[unverified 08-13]`

## Services

- `syndicate` — web service. ~333 GB outbound in Aug, almost entirely HTTP
  responses; only 207 MB service-initiated. `[measured 08-12]`
- `live-odds-worker` — background worker, 1 CPU / 2 GB, 50 GB persistent
  disk. Publishes a single date, ~30–60 publishes/min. `[measured 08-12]`
- `refresh-worker` — background worker. Multi-date sweep, ~30–60
  publishes/min. `[measured 08-12]`

## Platform constraints

- Hosted on Render. `[fact]`
- Artifacts stored on **Render persistent disks**, not S3/GCS. This forces
  single-instance services and stop-then-start deploys with downtime.
  `[from-code 08-12]`
- Render April 2026 pricing: included bandwidth cut, $0.15/GB overage.
  `[fact]`
- Included pipeline/build minutes exceeded in Aug: 1,549 of 1,000.
  `[measured 08-12]`

## Open problems

- `live-odds-worker` disk usage climbing steadily, ~20% → ~40% of 50 GB
  over two weeks. Something accumulates and is not cleaned up.
  **Not yet diagnosed.** `[measured 08-12]`
- Chronic instance restarts / failures across the fortnight, instance count
  dropping to 0. Pegged CPU, climbing memory. **Cause unconfirmed — may or
  may not be downstream of the egress issue.** `[from-logs 08-12]`

## Resolved

- Aug egress ~2.1 TB outbound vs 25 GB included; ~1.79 TB service-initiated.
  Root cause: `SYNDICATE_WEB_PUBLISH_URL` pointed at the web service's
  **public** URL, so workers POSTed every artifact out to the public
  internet and back in. `[from-code 08-12]`
- Secondary cause: a checksum was computed and sent but never compared, so
  unchanged artifacts re-uploaded in full every sweep. `[from-code 08-12]`
