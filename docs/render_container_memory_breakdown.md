# Render Container Memory Breakdown

## Purpose
This document tracks the process-level accounting investigation for the Render odds-refresh container.

The problem statement is the observed gap between container memory and the refresh process tree:

- `PROCESS_TREE_MEMORY` peak is about 109 MB
- container memory stays around 551-577 MB
- child count remains 0 in the observed refresh tree
- the run completes successfully
- about 450-470 MB is not explained by the observed refresh process tree

## What the new instrumentation logs
The refresh path now emits a whole-container process snapshot as:

```text
ALL_PROCESS_MEMORY {
  "processes": [...]
}
```

Each process entry includes:

- `pid`
- `ppid`
- `name`
- `cmdline`
- `rss_mb`

The list is sorted by RSS descending.

The snapshot also includes these rollups:

- `accounted_rss_mb`
- `container_memory_mb`
- `unexplained_memory_mb`

## Logging points
The refresh orchestration now records whole-container snapshots at:

- worker startup
- before MLB launch
- before WNBA launch
- every 60 seconds during refresh
- before exit

The same startup and exit snapshot is also emitted by the live odds refresh worker entrypoint.

## How to interpret the data
Use the next Render run to answer the accounting question directly:

1. If `accounted_rss_mb` is close to `container_memory_mb`, the gap is mostly process RSS and the earlier tree-only view was incomplete.
2. If a `gunicorn`, `uvicorn`, or `flask` process appears with large RSS, the refresh container is sharing memory with the web application.
3. If a Render sidecar or scheduler worker process appears, that process is part of the shared container footprint.
4. If only Syndicate refresh processes appear and the sum still does not close the gap, the missing memory is likely allocator overhead, page cache, or another non-tree resident in the same container.

## Current evidence
From the latest pre-instrumentation Render run:

- the refresh command completed successfully
- the observed refresh tree stayed near 85-109 MB RSS
- child processes stayed at 0 in the logged checkpoints
- container memory stayed around 551-577 MB
- the observed tree did not account for roughly 450-470 MB of container memory

That means the earlier tree-only probe was insufficient for attribution. The next run must use `ALL_PROCESS_MEMORY` to identify the hidden residents.

## Accounting formula
For each snapshot:

- `accounted_rss_mb` = sum of visible process RSS values
- `container_memory_mb` = cgroup/container current memory
- `unexplained_memory_mb` = `container_memory_mb - accounted_rss_mb`

## Recommendations
### A. Dedicated worker service
If the snapshot shows the web application process in the same container as the refresh worker, move the refresh job into its own Render worker service.

### B. Dedicated web service
If the refresh worker and web application are both present in the same container, the web service should remain gunicorn-only and the compute path should move out of the web dyno.

### C. Splitting refresh jobs
If MLB and WNBA together drive the peak and the heartbeat snapshots show the memory rise during sport launch, split the refresh into separate runs or serialize the launches.

### D. Process isolation
If Render sidecars, scheduler workers, or other Syndicate jobs are visible in the same container, isolate them into separate services or disable the shared runtime path.

## Next measurement
Run the refresh again and collect the `ALL_PROCESS_MEMORY` snapshots at the logging points above. The ranked process list should make the missing memory owner explicit.
