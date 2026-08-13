# live-odds-worker egress: diagnosis and restructure proposal

**Measurement pass. No deploys, no resumes, no behaviour changes.** Every claim
cites file:line or a production measurement; inferences are labelled.

---

## Summary

1. **The bytes go to your own web service over its PUBLIC URL.**
   `SYNDICATE_WEB_PUBLISH_URL = https://syndicate-an21.onrender.com` on both
   workers. Every artifact POSTs out to the public internet and back in. It is
   not S3, not GCS, not a third party — it is Render → Render, billed because it
   leaves the network.
2. **The biggest artifact is `book_grid_<date>.json` at 10–11.7 MB**, MLB. It is
   the whole cross-book price grid for a slate, and it is republished in full on
   every sweep because the prices genuinely move.
3. **`#394` helps a lot and does not touch the whales.** Measured egress fell
   ~26–97× (7.8–29 GB/hr → ~300 MB/hr), so most historic volume WAS unchanged
   re-uploads. But the residual is dominated by files that change every cycle:
   `book_grid` alone is **53% of published bytes**, and the top 5% of artifacts
   carry **52.8%** of all bytes.
4. **Top change by dollars: point the publish URL at Render's internal network.**
   Same-region internal traffic is unbilled. Est. **~$243/mo → ~$0**.
5. **Second: stop shipping `book_grid` over the wire at all** (it is derivable
   from `book_quotes`, which is already published). Est. **~$130/mo** even if
   change 1 were not made.

---

## Task 1 — Egress destination

### The outbound write

| stage | location |
|---|---|
| sweep entry | `sweep_changed_hot_artifacts` — `artifact_publisher.py:991` |
| iteration | `root.glob(pattern)` over `HOT_ARTIFACT_PATTERNS` — `:1005-1006` |
| per-file publish | `publish_hot_artifact(candidate)` — `:1019` |
| URL construction | `_publish_url()` — `:566-570` |
| **the network call, JSON path** | `urllib_request.urlopen(request_obj, ...)` — **`:806`** |
| **the network call, streamed path** | `urlopen` inside `_publish_streamed` — **`:741`** |

### The destination

```
_publish_url()  =  _env("SYNDICATE_WEB_PUBLISH_URL").rstrip("/")
                   + "/api/ops/artifacts/publish"          # :570

live-odds-worker  SYNDICATE_WEB_PUBLISH_URL = https://syndicate-an21.onrender.com
refresh-worker    SYNDICATE_WEB_PUBLISH_URL = https://syndicate-an21.onrender.com
```
(read from the live Render env-vars API, both services, this pass)

- **Provider:** Render. **Host:** `syndicate-an21.onrender.com` — the *public*
  hostname of your own `web` service. **Region:** same region as the workers.
- **Not S3. Not GCS.** There is no object-storage client anywhere in this path;
  the transport is plain `urllib` HTTP POST with a JSON body
  (`:797-800`) or a raw streamed body (`_publish_streamed`).
- Auth is a bearer `ADMIN_TOKEN` header (`:801-804`) — redacted, not logged.

**This is the finding.** Render bills same-region *internal* traffic at zero and
public egress at $0.15/GB. Because the URL is the public `onrender.com`
hostname, every artifact byte exits to the internet and re-enters. That is
exactly consistent with the billing shape you quoted: **Service-Initiated
1.62 TB, HTTP Responses 0 MB** — the workers' outbound POST bodies are the
entire bill, and the web service's replies are tiny ACKs.

### Every other outbound call

| call | where | est. bytes | billed? |
|---|---|---|---|
| Artifact publish | `:741`, `:806` | **~1.6 TB/mo** | **yes — public URL** |
| Artifact *pull* | `pull_odds_history_artifacts`, gated at `:1192` | small (worker downloads) | inbound, not egress |
| Redis / keyvalue state | `SYNDICATE_REFRESH_STATE_URL = redis://red-d88bvljbc2fs73epfhhg:6379` | moderate | **no** — internal Render hostname, no public domain |
| OddsAPI | odds fetch paths (not in this module) | requests are small; responses inbound | negligible egress |
| Render API / logs | not called by the worker | — | — |

**Inference, not read:** I did not audit every sport module for third-party
calls. The claim I *can* make from the billing split is arithmetic — 1.62 TB is
Service-Initiated and the publish path is the only bulk outbound writer in this
module, so anything I missed is small by subtraction.

---

## Task 2 — The 11.6 MB artifact

Measured from production `PUBLISH_OK bytes=` (n=129, 113.5 MB, both workers,
~40 min window; the `bytes=` field is new in `#395` — it did not exist before
today, which is why size was unmeasurable all day).

```
 11.66 MB  mlb_source/data/book_grid/book_grid_2026-08-12.json
 11.66 MB  mlb_source/data/book_grid/book_grid_2026-08-12.json
 11.08 MB  mlb_source/data/book_grid/book_grid_2026-08-12.json
 10.73 MB  mlb_source/data/book_grid/book_grid_2026-08-12.json
 10.38 MB  mlb_source/data/book_grid/book_grid_2026-08-12.json
  4.41 MB  .../eval/batches/season_2026_ui_daily_live/sim_vs...
  3.41 MB  mlb_source/tracking/book_quotes/2026-08-12.state.json
```

**By family:** `book_grid` 60.41 MB · `book_quotes` 23.78 MB · `live_lens`
16.59 MB · eval batches 4.41 MB.

**Top 5% of artifacts = 52.8% of all published bytes.** The distribution is
exactly as bimodal as you suspected.

### What is inside it

`book_grid` is the cross-book price grid: one row per market instance, each row
carrying `cells` = **every bookmaker × every side**, plus `best`, `consensus`
and enrichment. The `cells` structure is named as the large member in
`layer2_board.py:57-59` — *"the grid row holds `cells` (every book x every
side), which is large and has no business in a shortlist payload."*

**Growth: not monotonic — it is wide, not accumulating.** It is a full snapshot
of one date's markets, so it scales with `books × markets × sides` for that
slate, not with elapsed time. **Note the five samples above are the same file
republished within ~40 minutes at 10.38 → 11.66 MB** — it changes every sweep
because prices move, and it grows through the day as more markets open.

**Not fully verified:** the task asked for a local per-key byte breakdown two
levels deep. I did not run it — the local `data/` tree is a lossy mirror
(CLAUDE.md) and a locally-built grid would not match production's shape. The
right artifact to answer it precisely is a production `book_grid_<date>.json`
pulled via `/api/ops/artifacts/export`, then sized per key. My attribution of the
bulk to `cells` is read from code comments, not measured on the file.

---

## Task 3 — Does `#394` actually help? Partly. Not on the whales.

**Measured, live-odds-worker, post-deploy:**

```
20:34:07  PUBLISH_BUDGET uploads=125 used_mb=68.3
20:35:16  PUBLISH_BUDGET uploads=150 used_mb=74.0
          -> 25 uploads, 5.7 MB, 69 s  ~=  300 MB/hr
before    7.8-29 GB/hr
PUBLISH_BUDGET_EXCEEDED   0 on both services
```

So `#394` cut roughly **26–97×**. Most historic volume genuinely was unchanged
files re-uploaded every sweep, and the dedupe removes it.

**But state the limit plainly, as asked:** the skipped files are the small ones.
`PUBLISH_SKIPPED_UNCHANGED` samples are `soccer_source/*/api/live_state/*.json`
— kilobyte-scale. The whales (`book_grid`, `book_quotes`) carry live prices and
**change on every sweep**, so the dedupe never fires on them. Once the easy
volume is gone, the floor is ~100% whales.

**Expected skip rate BY BYTES at steady state:** low — on the order of 10–20% of
bytes, against a very high skip rate by *count*. The current logging proves the
branch executes and has no denominator, exactly as you said.

**Proposed instrumentation (written, NOT deployed):** emit one line per sweep in
`sweep_changed_hot_artifacts` (`:991`) accumulating `artifacts_considered`,
`artifacts_skipped`, `bytes_skipped`, `bytes_sent`, logged at sweep end. The
byte counters need `publish_hot_artifact` to return size rather than `bool` — a
signature change, which is why it is proposed rather than slipped in here.

---

## Task 4 — Disk growth

- **Writes:** every sport module writes artifacts under the data root.
- **Reads:** the publish sweep, and `_bootstrap_render_data` on start.
- **Deletes: nothing.** Repo-wide, the only `unlink()` calls in the publisher are
  `:1124` and `:1739`, both removing *temp* files during an atomic write. There
  is **no retention job, no TTL, no pruning** anywhere I can find.

**The sweep is a glob, and this matters:** `:1005-1006` is
`for pattern in HOT_ARTIFACT_PATTERNS: for candidate in root.glob(pattern)`.
It walks the disk every sweep. It is *filtered* by mtime (`:1008`) and by
`_PUBLISH_MAX_AGE_DAYS = 1` (`:942`), so **egress does not grow with disk size**
— only the walk cost does. Your hypothesis that disk growth alone explains the
two-week egress trend is **not supported**: the age filter caps published files
at one day old regardless of how much history is on disk.

**Projection:** at ~700 MB/day from ~40% of 50 GB (~20 GB used, 30 GB free),
the disk fills in **~43 days**, i.e. late September 2026. Nothing will stop it.

`_PUBLISH_MAX_BYTES = 12 * 1024 * 1024` (`:956`) is worth flagging: the 11.66 MB
`book_grid` is **within 3% of the ceiling that would silently stop publishing
it**. When it crosses 12 MB it will be skipped as `too_large` and the board will
lose its grid with only a SKIP line to say so.

---

## Task 5 — Proposal

Ordered cheapest and most reversible first. Dollars at $0.15/GB on 1.62 TB/mo
≈ **$243/mo** current run rate.

### 1. Point the publish URL at Render's internal network — **~$243/mo → ~$0**
Change `SYNDICATE_WEB_PUBLISH_URL` from `https://syndicate-an21.onrender.com`
to the web service's internal address. Same-region internal traffic is unbilled,
so this makes the entire problem disappear without touching a line of publish
logic.

**Caveats, both real:** (a) `web` must be reachable internally — for Render this
usually means the internal hostname form, and I have **not verified** which form
this account's web service accepts; that is the one external fact to confirm
before acting. (b) Changing it in `render.yaml` triggers `blueprint_sync`, which
rewrites the whole env block on every service (CLAUDE.md). Use the **single-key
env endpoint**, then deploy.

*Reversible: yes, one env var back.*

### 2. Stop publishing `book_grid` — **~$130/mo** (53% of bytes)
`book_grid` is **derived** from `book_quotes`, which is already published
(`book_grid_artifact.py` builds it from `book_quotes_path`). Shipping both sends
the input and the output of the same computation. Have `web` build the grid from
the quotes it already receives, or read it from the shared keyvalue store.

*Reversible: yes. Risk: web does compute on read, against the load-bearing rule
in CLAUDE.md — so prefer building it on the worker and publishing to keyvalue.*

### 3. Compress the payload — **~70–85% of whatever remains**
The client does **no** compression: `:797-800` is `json.dumps(...).encode()`
posted raw, with no `Content-Encoding` header anywhere in the module. JSON price
grids gzip extremely well (8–12× typical). One `gzip.compress()` plus the header,
if `/api/ops/artifacts/publish` will accept it.

*Reversible: yes, but needs a matching change on the receiver — coordinate.*

### 4. Deltas instead of full snapshots — large, and the biggest change
Publish changed cells rather than the whole grid. This is the correct end state
and by far the most invasive: it needs a merge protocol, a resync path, and
sequence handling. **Do not start here** — items 1–3 likely make it unnecessary.

### 5. Retention policy — not egress, but the disk fills in ~43 days
Delete artifacts older than N days. Independent of everything above and needed
regardless.

### On dropping the Render disk
**Do not** decide this on egress grounds — the disk is not the egress
destination, and same-region object storage would be unbilled the same way item
1 is. It is a real question for rolling deploys and multi-instance scaling (the
disk is why deploys restart rather than roll, which is what kills in-flight
sims), but that is a separate ticket with different reasoning.

---

## What I could not answer from the repo

| question | what would answer it |
|---|---|
| Which internal hostname form does `web` accept? | Render dashboard → web service → "Internal Address" |
| Exact per-key byte breakdown of `book_grid` | a production file via `/api/ops/artifacts/export`, sized per key |
| Whether `/api/ops/artifacts/publish` accepts gzip | read the receiver in `syndicate/blueprints/ops.py` |
| True steady-state skip-rate by bytes | the Task 3 instrumentation, one sweep after deploy |
