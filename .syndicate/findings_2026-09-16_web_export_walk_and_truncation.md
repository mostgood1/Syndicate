# The web export timeouts are the WALK, and the truncation next to them is worse

`[2026-09-16 03:24-03:40Z, lane web-export-timeout, session a1e40980]`

The lead, carried since 2026-09-15: web's `/api/ops/artifacts/export?pattern=*<today>*`
exceeded the pull client's 30 s timeout on **10 of 60** requests (~1 in 6), and both
workers failed within the same seconds twice. Web's access log carries no duration, so
server time had never been read. Four hypotheses were registered before measuring
(`lanes.md`, lane `web-export-timeout`, landed `24f1993e`).

## H2 CONFIRMED — the cost is the WALK, and its upper tail crosses the client's timeout

**THIS IS NOT NEW, and the credit matters for what to do next.** `#632` already found it and
already fixed it once: *"`/api/ops/artifacts/export` had a 26 s median and an 87 s max, and
`?names_only=1` -- which reads no file bodies -- timed out after 180 s. The cost is the directory
walk: 176 patterns collapsing onto 95 parents"* (`tests/test_artifact_walk.py`). The numbers below
are the POST-optimisation state -- 26 s median improved to 15.21 s -- so the contribution here is
the residual distribution against the client's timeout, and the truncation defect beside it.

`names_only=1` runs the SAME `iter_pattern_matches` walk and the same `since` filter and
returns a few bytes per file instead of the file, so it isolates the walk. Seven samples
of the production-shaped query (`pattern=*2026-09-15*`, `since=now-30min`), identical work
every time — **129 files matched, ~326 MB of matched bytes**, 16 KB of wire per response:

| # | duration | | # | duration |
|---|---|---|---|---|
| 1 | 15.01 s | | 5 | 29.71 s |
| 2 | 13.74 s | | 6 | 13.10 s |
| 3 | 27.58 s | | 7 | 15.21 s |
| 4 | **38.13 s** | | | |

**min 13.10 s, median 15.21 s, max 38.13 s — a 2.9x spread for identical work — and
1 of 7 over the 30 s client timeout.** Production's observed rate is 10 of 60 (~1 in 6).
The rate reproduces because the walk's distribution straddles the timeout: nothing has to
go wrong for a request to fail, it just has to land in the tail.

An earlier set with no `since` (1,115-1,119 files) ran 27.17 / 27.80 / 28.91 / 34.32 s, and
one `since=2h` sample reached **53.99 s**.

## H3 FALSIFIED — bytes do not drive the duration, they SHORTEN it

Full-body exports were **faster** than the names-only walks: `since=150s` took 14.23 s and
`since=30min` took **3.16 s**, against 27-34 s for the no-since walk. The reason is in the
handler: when the 24 MB budget is reached it sets `truncated = True` and **`break`s out of
the walk**. A request with more to fetch stops walking sooner.

## The 2026-09-15 "UNEXPLAINED" anomaly is explained by that same `break`

The sizing run at 21:00:52Z recorded a 150 s window returning **more** files (21) than the
30 min and 2 h windows (7-8) at nearly the same instant, taking 20.1 s against 1.2 s and
2.3 s — a wider window returning fewer files, which is impossible for a superset. It is not
a superset: the wider windows match the big movers sooner, hit 24 MB earlier in walk order,
`break`, and return **fewer files faster**. Today's readings reproduce it exactly
(`FULL since=30min`: 4 files, 17.68 MB, `truncated: true`, 3.16 s).

## H4 CONFIRMED — and it is a silent correctness defect, not a performance one

Both full exports came back **`truncated: true`**: 22 of 26 matched files for a 150 s
window, and **4 files for a 30 min window** (17.68 MB of ~326 MB matched).

**The client never reads the field.** `truncated` appears nowhere in
`artifact_publisher.py` (the one mention at :1897 is about publish gzip). A truncated
response is HTTP 200, so `_pull_hot_artifacts_request` returns `succeeded=True`,
`all_succeeded` stays True, and `_record_hot_artifact_pull_watermark(pull_started_epoch)`
advances the floor **past every file that was not delivered**. Those files are then below
the watermark and are never re-requested. The repair pass cannot recover them: it fetches
only artifacts missing **outright**, never ones present and stale.

`pull_hot_artifacts`'s own docstring states the guarantee this defeats:

> the watermark only advances when every sub-request for this call succeeds, so a partial
> failure re-fetches that same window next time instead of silently skipping it

The guarantee holds for a *failure*. Truncation is a **success**, so it walks straight
through it. This is the same shape as the shared pull watermark fixed in `082da3e3`
yesterday — a floor advancing past files that were never received — in a different place.

## The two failure modes are opposites, which is why this hid

- A pull with **little** to fetch completes the whole walk and is the one that **times out**.
- A pull with **much** to fetch truncates early, returns fast, is logged `PULL_OK`, and
  **silently drops the remainder** while advancing its floor.

Both leave refresh-worker holding stale today-dated artifacts. Only the first is visible in
the logs.

## Not established

- **H1 (contention) is neither confirmed nor ruled out.** It is not needed for the LEVEL —
  a 15 s median walk needs no explanation — but the 13 → 38 s spread on identical work is
  unattributed. Page cache, Render disk latency, CPU steal and concurrent worker pulls are
  all live candidates and none was isolated. Do not report the variance as contention.
- Whether `patterns_that_can_match` meaningfully narrows the pattern set for a `*<date>*`
  glob, or whether the walk covers essentially the whole data tree. Not read.
- The truncation RATE in production over time. Measured here on four requests, not sampled.

## What a fix would have to do (none taken — the files are another lane's)

1. **P0, correctness:** the client must treat `truncated: true` as "this window is not
   finished" — do not advance the watermark, or re-request immediately from the last
   delivered path. Lives in `artifact_publisher.py`, held by `book-quotes-splice-repair`.
2. **P1, the timeout:** either make the walk cheaper, or raise the client's 30 s timeout
   above the observed tail. Raising it is a one-line change that would have prevented all
   10 observed failures, but it treats the symptom; the walk is the cost.
3. Note that (1) and (2) interact: fixing the timeout alone makes truncation MORE frequent,
   because more requests will complete and more of them will be large ones.

Measurement cost: 38.0 MB of wire for the two full exports plus ~250 KB for every
names_only sample.
