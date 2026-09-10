# HANDOFF → `refresh-worker-oom-recurrence` — 22 OOM kills in one 5h20m window

Written 2026-08-17 ~01:30Z by the `branch-overlap-baseline-watch` scheduled task.
**This is a MEASUREMENT handoff, not a diagnosis.** That lane owns refresh-worker
memory attribution; this task samples and does not change code or config.

Delivery note: attempted `send_message` to the two live refresh-worker-memory
sessions (`Oom band early read`, `Worker memory watchdog logs`) and both were
refused — the tool is unavailable in scheduled-task runs. The lane's own session
(`refresh-worker OOM: two kills in 25 min (fork)`) is archived, last activity
2026-08-16T15:33Z. Hence a file.

## The finding

**22 `oomKilled` events on refresh-worker**, all `memoryLimit=4Gi`.

Source (read-only): `py -3 scripts/render_events.py --service refresh-worker --failures-only --since 2026-08-16T19:55:41Z`
Events-API coverage: `2026-08-16T20:04:15.596Z .. 2026-08-17T01:23:37.298Z`
(15:04–20:23 local), 101 events over 2 pages. Last kill 01:21:07Z, 2.5 min
before the end of coverage.

Timestamps (Z):

    20:04:15  20:17:29  21:03:47  21:12:53  21:22:53  21:38:03
    21:52:09  22:07:57  22:21:51  22:41:52  23:03:50  23:16:51
    23:32:18  23:43:11  23:56:00  00:08:54  00:19:48  00:32:32
    00:41:00  00:49:05  01:07:16  01:21:07

## Why it may matter

- **Rate.** The baseline context handed to this task was 44 kills over the whole
  week 2026-08-09..08-16. This window is 22 in ~5h20m — roughly one every 14
  minutes, sustained, with no quiet stretch longer than ~22 min.
- **The second half of this window is inside the live-slate band (22:00Z–05:00Z)**
  that the lane scheduled via `scripts/oom_band_report.py`.
- **Name collision — do not merge these.** The lane's current header already
  carries "22 excursions over 5 deploy-free windows." That is a different
  quantity from these 22 *kill events*. Same number, unrelated derivation.

## Paired memory sampling (same run, overlapping window)

`scripts/watch_branch_overlap.py --hours 5 --scheduled`, covered
`2026-08-16T19:55:41Z .. 2026-08-17T00:55:19Z`, 1578 samples, 0 malformed.
Appended to `reports/branch_overlap/baseline.jsonl` as `run_mode=scheduled`.

- WORST `container_memory_mb` (any sample): **4096.0 MB = 100.0% of cap**
- WORST while BOTH branches live: 4096.0 MB
- Both-branches-live: **176 / 1578 = 11.2%**, concentrated in 15:00 local (44)
  and 18:00 local (65)

**The kills do not cluster on the both-live hours.** Per local hour:
15:00 ×2, 16:00 ×5, 17:00 ×3, 18:00 ×5, 19:00 ×5, 20:00 ×2 — roughly flat
against a both-live share that is anything but flat. On this one sample, branch
overlap does not look like the discriminator for *when* a kill lands. That is a
single window and should not be generalised.

## Limits on the above

- `container_memory_mb` is cgroup `memory.current` and **includes page cache**.
  The 4096.0 readings are not themselves the kills, and this run did not split
  anon vs `inactive_file`. At-cap is not a kill.
- The kill count comes from the **events API**, not from a log search.
- Baseline blind spot unchanged: **01:45–09:45 local is not covered** by the
  sampling cadence.
