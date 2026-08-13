# Syndicate — Deploy Ledger

> **Append only.** Never edit a past row. A row with an empty Measured
> column is an open obligation, not history.

---

### #394 — hash guard
- Deployed: 2026-08-12 20:26
- Change: compare the computed checksum instead of merely sending it, so
  unchanged artifacts are skipped rather than re-uploaded.
- Expected: sharp drop in redundant uploads per sweep.
- Measured: logging skips as intended. **Egress impact not isolated —
  deployed close to #395.** `[partial]`
- Rollback: revert #394
- Verdict: shipped, effect not cleanly attributed.

### #395 — rate ceiling
- Deployed: 2026-08-12
- Change: caps worst-case egress at 2 GB/hr per service.
- Expected: hard ceiling on blast radius, not a fix.
- Measured: `<pending>`
- Rollback: revert #395
- Verdict: mitigation, not remediation. Do not treat a flat graph under
  this cap as evidence the underlying issue is solved.

### Baseline measurement — first-byte sample
- Date: 2026-08-12
- n=29 uploads, 86.2 MB total. Min 325 B, median ~73 KB, max 11.6 MB.
- Read: highly skewed — bytes concentrated in a few large artifacts.
  Any fix must be evaluated on total bytes, not upload count.

---

### PENDING

- [ ] Internal-hostname cutover — expected effect, window, and rollback
      to be written by `/preflight` **before** it goes out.
