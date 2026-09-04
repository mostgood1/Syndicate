# web's 38 `nonZeroExit=137` (SIGKILL) events — what they are

`[2026-09-04, session c4287631, lane web-sigkill-137-cohort]`

**Headline, and the part that is a MEASUREMENT rather than a story: web's kill
count for 2026-06-15 .. 2026-07-09 was undercounted by 38.** Any census that
counted only `oomKilled` saw 164; the true figure for a service that was killed
is **202**, and the 38 were invisible because Render reported them as a bare
`nonZeroExit` and `classify()` binned them in `failed:unknown` with no label.

**What they are, in one line:** a crash loop confined to a bounded era, dying
1–14 minutes after every boot, under the exact commits that had the web service
computing intelligence itself — and it ends 92 seconds before the deploy that
moved that work off web. **Cause is INFERRED, not established** — the logs that
would settle it aged out. See "What is NOT established" before quoting this.

---

## Three hypotheses stated before testing, and all three killed

| # | hypothesis | prediction | result |
|---|---|---|---|
| H1 | deploy shutdown SIGKILLing an instance that missed its grace period | 137s cluster tightly after `deploy_started` | **DEAD.** Only 13% within 120s; median delta **1,381s**. The `unhealthy` control clusters *tighter* (31% within 120s, median 205s) — the 137s are LESS deploy-correlated than a class that is not deploy-caused |
| H2 | Render relabelled the same kill as `oomKilled` | a clean changeover, no overlap | **DEAD.** web's first `oomKilled` is **2026-06-10T22:22:40Z, five days BEFORE the first 137**, and **77 `oomKilled` sit inside the 137 window**. Both labels were in use simultaneously — on 2026-07-03 a 137 at 03:33:05Z is followed by `oomKilled` at 04:05:34Z and 04:14:58Z |
| H5 | the 75 user-triggered `server_restarted` in this era | 137s follow a restart | **DEAD. 0 of 38** within 300s of a restart; median gap **95,059s** (26 hours) |

H5 was added mid-investigation after the event inventory showed 75
`server_restarted`, all `triggeredByUser`, concentrated in exactly this window.
It looked compelling and it is simply false.

## What the 137s DO look like

**A crash loop with a tight, short uptime.** Time from `server_available` to the
kill, all of web's failure classes, same read:

| kind | n | min | p25 | median | p75 | max | under 10 min |
|---|---|---|---|---|---|---|---|
| **nonZeroExit (137)** | 38 | 69.9s | 95.9s | **161.6s** | 269.0s | **830.0s** | **37/38 (97%)** |
| earlyExit | 31 | 51.1s | 110.6s | 151.0s | 212.3s | 2,460s | 30/31 (97%) |
| oomKilled | 164 | 23.9s | 280.1s | 488.5s | 2,241s | **680,993s** | 92/164 (56%) |
| unhealthy | 734 | 0.8s | 85.6s | 201.1s | 1,192s | 419,733s | 487/734 (66%) |

**No 137 ever survived 14 minutes.** That is a boot / early-load kill, not a
slow leak — and it is distributionally near-identical to `earlyExit` (median
151s vs 162s) while clearly unlike `oomKilled`, whose tail runs to 7.9 days.
The reverse view agrees: 30 of 38 had a `server_available` within the prior
300s, and 26 of 38 had another `server_failed` there.

## What was LIVE at each of the 38

Reconstructed from `/v1/services/<id>/deploys` (1,900 deploys read, 19 pages,
fully paged; 1,619 with a successful `finishedAt`). `status == "live"` returns
only the CURRENT deploy — the history has to be rebuilt from `deactivated`.

    6 x  b8c242f56  Cut Render bootstrap startup cost
    4 x  2d7d694cb  Restore MLB refresh jobs in orchestrator
    4 x  552622bee  Compute intelligence responses when cache is empty
    3 x  f07578028  Make intelligence status JSON loading local
    3 x  d0b4a8a2f  Fix WNBA sim no-op and artifact control
    3 x  c204618ea  Compute intelligence query on empty cache
    2 x  6b3903058  Reduce Render Gunicorn concurrency
    2 x  3fe1c9f9e  Add WNBA cards API fallback
    1 x  b428270ca  Compute intelligence query when cache is empty
    1 x  a869c5648  Surface intelligence candidates synchronously
    1 x  3d29ca056  Restore web intelligence background loop
    1 x  191099f7f  Make intelligence board context-safe
    1 x  4569bc9cf  Reinforce Render web startup contract
    1 x  972914f01  Remove MLB per-game detail loop
    1 x  8ecf59ea9  Fix live board publication flow
    ... 5 more, 1 each

**Nine of the 38 ran under a commit whose subject is literally "compute
intelligence … on empty cache" or "surface intelligence candidates
synchronously".** Two more ran under "Reduce Render Gunicorn concurrency" —
somebody was already fighting memory by cutting workers. This is the era in
which web violated the rule `CLAUDE.md` calls the single most important
architectural constraint in the repo:

> The web service does no heavy computation… If data is missing at request
> time, the correct behavior is a degraded/empty UI state, not an on-request
> backfill.

## The two boundaries

- **Start.** First 137 `2026-06-15T20:09:10Z`. The preceding day carries
  `1a5798a0 Bootstrap Render-critical published artifacts`,
  `aee7bc16 Make Render bootstrap non-blocking`, `2cd5f7ee Start web service
  without bootstrap` (2026-06-14 evening CDT), and 06-15 adds `a6c5c1e5 Run live
  odds poller across all phases` and `d07fd9f7 Assign live polling to web
  service`. **Commit times are not deploy times** and the first 137 precedes the
  two 06-15 commits, so this end of the bracket is weaker than the other.
- **End.** Last 137 `2026-07-09T03:48:19Z`, live under `8ecf59ea9 Fix live board
  publication flow`. **92 seconds later**, at `03:49:51Z`, `9d259f857 Move
  intelligence publication to shared state` went live. No 137 has occurred
  since — 57 days. Deploys ran about one per 77 minutes in this period, so a
  deploy landing within 92s of any given instant is a ~2% coincidence; that is
  suggestive at n=1, not proof. The stronger form of the same point is the
  regime change in what was being shipped: the "compute intelligence on empty
  cache" family stops here and "move intelligence publication to shared state" /
  "board-only intelligence publication" begins.

## What is NOT established

- **That these were OOMs.** 137 = 128+9 = SIGKILL is a shell/POSIX reading of
  the code, not a Render guarantee. Render demonstrably *could* label a
  container OOM — it did so 164 times on this service in the same period,
  including inside the same storms — so whatever sent this SIGKILL was probably
  **not** the cgroup OOM killer firing on PID 1. A plausible mechanism is the
  OOM killer taking a gunicorn CHILD and the master exiting 137, which Render
  would see as a non-zero exit rather than a container OOM. **That is a
  hypothesis with no evidence behind it yet.** Do not repeat it as a finding.
- **Causation from the commit mapping.** What was live during a kill is not what
  caused it. The association is multiply supported — both boundaries, the
  commit subjects, the uptime signature, and the architectural rule it violates
  — and it is still association.
- **Anything from logs.** Render's log retention on this account is **~30 days**:
  bisected 2026-09-04, `2026-08-21` returns coverage, `2026-08-05` returns
  **HTTP 400**. June and July are unreachable. Note the failure mode is a 400,
  i.e. a READER failure, not an empty result — it must not be read as "no logs
  say anything". A recent positive control returned 6,288 lines, so the reader
  itself works.

**What would settle it:** nothing available today. If a 137 recurs, a log read
inside 30 days would show whether gunicorn reports a worker killed, and
`ALL_PROCESS_MEMORY` around the kill would separate a child OOM from a master
exit.

## Why this is still worth having

The cohort is **historical** — zero 137s in 57 days. But web's memory trouble is
not: 4 `oomKilled` and 3 `unhealthy` since 2026-09-02, at `memoryLimit=2Gi`.
What changed is the LABEL, and the practical consequence is the one at the top:
**a kill census that reads only `oomKilled` undercounts, and for this service in
this era it undercounted by 19%.** `classify()` now names `nonZeroExit` and puts
the code on the row, so the same undercount cannot recur silently.

Relevant open lanes, not touched here: `web-oom-thread-gating`,
`render-web-request-path`.

## Method notes

- Web's unfiltered event read **hits the 100-page cap** (10,000 events). Every
  number here comes from seven explicit date slices, each fully paged, totalling
  **12,518 distinct events, 2026-05-22 .. 2026-09-04**. The count of 38 is
  unchanged from the capped read — the lower bound turned out to be the bound,
  but that was checked, not assumed.
- Deploy history likewise paged to exhaustion (19 pages) rather than trusting
  the first page.
