# The 201 publish "refusals" are not refusals — and the real cost is 2.22 GB/hour

`[2026-09-07, lane publish-refusal-201-triage, session 28c6162b]`
Read-only triage. `ops.py` / `artifact_publisher.py` are held by lane
`ncaaf-live-resim-wire`; nothing here was edited and no claim was taken.

Raised by lane `soccer-unfed-inputs`: ~201 `verdict=REFUSED` in an hour,
`refresh-worker` vs `live-odds-worker` alternating on soccer `odds_history`,
described as "the `#488` incident shape still running at volume".

## VERDICT: no data is being lost. The label is wrong, not the system.

**`verdict=REFUSED` is the verdict FUNCTION's opinion, printed before the caller
decides.** `_publish_divergence_verdict` builds the marker string and returns
`should_refuse=True`; `_publish_streamed_body` then acts on it only via

    if refuse and not will_merge:      # ops.py, streamed path

and `#630` deliberately exempts merged families. Ran the real predicate against
the real paths from the logs — `will_merge` is **True for every refused path**
(`is_mergeable_odds_history` matches both `soccer_source/tracking/odds_history/*`
and `soccer_source/artifacts/soccer/odds_history/*`). So the 409 is never
returned for them.

The HTTP status is decisive and the log line is not:

    true refusal   -> 409 "publish refused: would replace a larger artifact"
    at capacity    -> 503 "retry next sweep"   (backpressure; target keeps its copy)
    deferred merge -> 200 ok:true              (child owns the staged file)

**Outcome measured, not inferred:** 819 `ARTIFACT_MERGE_CHILD` records for
`family=odds_history` in a 2h window, **all merged**. Data lands.

This is NOT the `#488` shape. `#488` was last-writer-wins DESTROYING rows. Here
the merge preserves the existing copy by construction.

## THE REAL FINDING: 2.22 GB/hour of publishes, 95.8% of which add nothing

Measured over 93 minutes (2026-09-07 21:00-22:33Z), from the divergence markers
themselves:

    divergence publishes            366
    total incoming                  3.45 GB   ->  2.22 GB/HOUR
    by publisher                    refresh-worker 352 (3.32 GB)
                                    live-odds-worker 12 (0.13 GB)
    distinct paths                  16          <- each republished ~40x in 93 min
    payload sizes                   4.4 - 11.1 MB each

And what those publishes accomplish, over 819 merges:

    added = 0        785   (95.8%)
    added > 0         34   ( 4.2%)   range 1-84 markets

**refresh-worker is republishing a strict subset ~every 2.3 minutes.** Its copy
is consistently ~74-75% the size of live-odds-worker's (`ratio=0.740`, `0.750`,
`0.753`), which is why the shrink guard fires every time.

STATED CAREFULLY: this is not pure waste. The merge earns its keep on 4.2% of
runs, and it is the thing PREVENTING the `#488` clobber — **it must not be
removed.** What is wasteful is the 95.8%, and the fact that it is paid at
multi-megabyte granularity.

Two collateral costs:
- **Merge capacity saturation.** 2,359 `ARTIFACT_MERGE_AT_CAPACITY` in the same
  93 minutes against `cap=1`, plus 850 `ARTIFACT_MERGE_DEFERRED`. Each capacity
  rejection is a 503 the publisher retries next sweep — safe, but it means the
  queue is permanently full and a genuinely new publish waits behind redundant ones.
- **Log noise masking real divergences.** 294 `REFUSED` + 52
  `ALLOWED_WITH_WARNING` in 93 min, streaks to 8. A real cross-publisher
  divergence on a NON-mergeable path would be one line in three hundred.

## WHAT I DID NOT ESTABLISH

- **Why** refresh-worker publishes soccer `odds_history` at all when
  live-odds-worker owns the fuller copy. That is the question worth answering,
  and it belongs to whoever owns that publish loop.
- Whether 2.22 GB/hour is billed egress. It is worker->web inside Render, so it
  may be internal; `[render-egress-cause]` says web's OUTBOUND polling is 100%
  billed, which is a different path. Do not cite this as a bill without checking.
- Whether the 4.2% that add markets could be captured by a cheaper trigger
  (publish only when the local copy grew, or a content hash) — plausible, unmeasured.

## SUGGESTED, NOT DONE

1. **Rename the marker.** `verdict=REFUSED` on a path that then merges is an
   instrument reporting something adjacent to the truth. `verdict=WOULD_REFUSE`
   or `verdict=REFUSED_EXEMPT_MERGE` costs one line and stops the next reader
   spending an hour where this lane just spent one.
2. Ask why refresh-worker publishes a subset copy every ~2.3 min at all.
