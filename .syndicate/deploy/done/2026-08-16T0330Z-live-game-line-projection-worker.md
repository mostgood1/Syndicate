service: refresh-worker
branch: main
sha: c87f6634
lane: live-game-line-projection
reason: The live game-line ledger cannot produce a sample. Measured 2026-08-16
        03:00Z on a live slate (2 games live): `live_gamelines` read considered
        8, projected 2, **priceable 0**, so the recorder's `candidates` was 0.
        v1 records priceable rows only. v2 records every projected row and keeps
        `priceable` as a field.

**TIME-BOXED, AND THIS IS THE POINT OF THE REQUEST.** The scheduled task
`live-gameline-ledger-check` fires **2026-08-16 20:30 Central**. If this has not
shipped by then, that check runs against v1 and will read `written: 0` for the
second night running — which will mean neither "broken" nor "working", exactly
as it did tonight. Shipping it is what makes tomorrow's check a test.

**BLOCKED, DELIBERATELY.** `refresh-worker-oom-recurrence` holds deploys to this
service until it has written an attribution for the two `oomKilled` events at
02:11:34Z / 02:37:06Z, and its own note says the counter it is waiting on needs
"an hour without a kill or a deploy, which is a reason to keep deploys OFF."
**Do not deploy this over that hold.** Either that lane clears first, or the
hold is explicitly overridden with the cost accepted.

blast radius: refresh-worker only. The change is one append of a few hundred
        bytes per changed market per build, on a path that already runs; it adds
        ~2 records per build where it previously added 0. It cannot raise —
        `record_live_gamelines` catches everything and the board build ignores
        the result. Kill switch with no deploy: `MLB_LIVE_GAMELINE_LEDGER_ENABLED=0`.
        **Memory cost is the only real question**, and it is small: the dedup
        read (`read_last_by_key`) streams the day's JSONL line by line, and the
        file is bounded at 20,000 records. On a 4 GiB service currently being
        diagnosed for OOM, "small" is a claim worth checking rather than
        asserting — it is the reason this is a request and not a deploy.

verify: after the first board build post-deploy, read
        `/api/board/book-grid?sport=mlb&date=<today>&limit=1` (needs the WEB
        request below to be readable at all) and expect
        `live_gameline_ledger.written` > 0 while games are live, then
        `skipped_unchanged` > 0 on a later build — the second is the real test,
        because it is what says the dedup works rather than that the append does.
        **Read it twice across two builds, not once.** A single post-deploy read
        is a coin flip on the warm-up (`learnings.md`, "two lags in series").

rollback: previous deployed sha `f8ca54e1` (content-verified live before this
        request was written; re-verify at deploy time, not from this line).

---

## RESULT — SHIPPED 2026-08-16 04:24:33Z. **DEPLOYED, NOT YET EXERCISED.**

**The hold was cleared by evidence, not by overriding it.** The owning session
wrote its attribution (`9ed17262`) and then archived: the kill is a **~2 GB
transient, not a leak**, `#435` did not regress, 22 excursions across 5
deploy-free windows with flat amplitude. Its lane's own success criterion — "a
written attribution in `deploys.md` backed by a deploy-free window" — was met
before I deployed. **I asked first**, and the session archived between my
question and its answer; the `send_message` retry returned "session is archived".

**Residual cost, recorded rather than netted out:** that lane stays OPEN because
the allocator inside the 2 GB pass is still unnamed, and naming it needs an
in-pass measurement on a matured clean window. **The window was 70 min old at
03:47Z and my deploy reset it to zero.** Nobody was watching it at the time.

Deployed `5c419007` (branch `deploy/refresh-worker-gameline-ledger-v2`),
**parented on the live SHA `f8ca54e1`, not on main** — `main` is not an ancestor
of it and 13 commits are live here and absent from `origin/main`.
`dep-da0jk261egvs738t0d10`: fired 04:18:16Z, live **04:24:33.598Z** (6m17s).

**Sim discipline held.** `check_deploy_safety.py` reported MLB sims back to back
— pid 2441 (`props_now_available`), then pid 3275 (`fingerprint_change`) for
11 minutes. Polled on **exit code 0**, not on a string (`NOT CLEAR` contains
`CLEAR`), and fired inside the gap at 04:17:23Z. **No sim was killed.** No new
`oomKilled` event since 02:37:06Z as of 04:26Z.

**MEASURED — and the result is "no data yet", stated as such:**

    artifact 04:22:51Z (PRE-deploy, v1)   considered 4  projected 1  priceable 1
                                          ledger candidates 1  written 0  skipped_unchanged 1
    artifact 04:25:14Z (POST-deploy, v2)  considered 0  projected 0  priceable 0
                                          ledger candidates 0  written 0  skipped_unchanged 0

The slate ended between the two. **v2 is live and has had zero live rows to act
on**, so nothing here says whether it behaves as intended. The real test is the
scheduled `live-gameline-ledger-check` at 20:30 Central on a full slate — which
is now a test rather than a formality, and that was the point of shipping today.

### CORRECTION — "the recorder has never recorded a row" IS FALSE

The pre-deploy read at 04:22:51Z shows `candidates: 1, skipped_unchanged: 1`.
**`skipped_unchanged` can only be non-zero if a record with the same key and
identical numbers already exists on disk** — `_moved(None, rec)` returns True, so
an empty file always writes. **v1 wrote at least one row tonight**, between
02:4xZ and 04:22Z, when one market cleared the bar.

So the handoff's "`written: 0` with `enabled: true` proves wiring, not
behaviour", and my own "the ledger was never asked to write anything", were both
true of the 03:00Z build I measured and **false an hour later**. The premise for
v2 is unchanged and still holds — 1 of 4 considered is a self-selected sample
with no denominator — but **the stronger claim that it structurally could not
write was wrong, and it was wrong because I generalised one build to a night.**

**Rollback:** `POST /v1/services/srv-d91dpertqb8s73co8ls0/deploys` with
`{"commitId": "f8ca54e18a1b5cfd43107521729c25f19433a415"}` — the SHA live at
04:18Z. Feature-only kill needs no deploy: `MLB_LIVE_GAMELINE_LEDGER_ENABLED=0`
(currently ABSENT on the service, which the code reads as ENABLED).

---

## OUTCOME — EXECUTED. v2 SHIPPED AND IS NOW PROVEN TO RECORD. TWO CAVEATS ARE STILL OPEN. Recorded 2026-08-18 by the coordinator.

**This outcome was reconstructed, not written at the time.** Everything below is
quoted from the `deploys.md` rows named at the end, except the 2026-08-18 read,
which I took.

**THE HOLD WAS CLEARED BY EVIDENCE, NOT OVERRIDDEN.** The request named
`refresh-worker-oom-recurrence` as a deliberate block. That lane banked its
attribution (`9ed17262`, a ~2GB **transient**, not a leak; `#435` did not
regress) and archived. Permission was asked for first; the reply was "session is
archived". **Residual cost recorded at the time:** its clean window was 70
minutes old and this deploy reset it to zero, which is what its still-open
second question needed.

**DEPLOYED** as `5c419007`, `dep-da0jk261egvs738t0d10`, fired 2026-08-16
04:18:16Z, live **04:24:33.598Z** (6m17s). Parented on the live SHA `f8ca54e1`,
**not on main** — 13 commits were live on this service and absent from
`origin/main`. Sims were launching back to back; deploy went into the 04:17:23Z
gap, polled on `check_deploy_safety.py` **exit code 0** rather than a string
(because `NOT CLEAR` contains `CLEAR`). **No sim killed.**

**THE TIME-BOX WAS MET.** The request's whole argument was that shipping before
the 20:30 Central `live-gameline-ledger-check` is what turns that check into a
test. It shipped ~16 hours ahead of it.

**AT DEPLOY TIME: NOT EXERCISED, and that was stated honestly.** The slate ended
between the two sampled builds — post-deploy build read considered 0 / projected
0 / candidates 0. Those zeros carried no information about the recorder.

**MEASURED ON THE FIRST REAL SLATE — THE RECORDER WORKS, 3,748 ROWS.**
`live-gameline-ledger-check`, scheduled run, 2026-08-17 02:2x–02:3xZ, against
refresh-worker `8999f033` (content-verified: `LEDGER_VERSION = 2`, call site at
`book_grid_artifact.py:267`). The count came from
`live_gameline_score.records_considered` — the return of
`read_records(ledger_path(...))`, i.e. the file's own row count — **not** from
the per-build counters, which were dead that night because the Sunday day slate
had finished before the task fired. This retires "it has never recorded a row".

**TWO CAVEATS THAT THE MEASUREMENT LEFT OPEN, and both are still open today:**

1. **DEDUP IS UNMEASURED.** It is not measurable by sampling the artifact across
   builds (candidates is 0 on a dead slate), and the ledger file cannot be read
   off-worker: `/api/ops/artifacts/stream` returns **HTTP 403 `path is not an
   allowed hot artifact`**. **Re-verified 2026-08-18:** no entry in
   `HOT_ARTIFACT_PATTERNS` (`artifact_publisher.py:35`) matches
   `*_source/data/live_gameline_ledger/live_gameline_ledger_*.jsonl`. Still 403.
   Deliberately NOT inferred from 3,748 against a guessed build count.
2. **THE SCHEDULE IS WRONG FOR SUNDAYS.** 20:30 Central is mid-slate on a
   weeknight and after the last final on a Sunday day slate.

**2026-08-18 read** (`/api/board/book-grid?sport=mlb&date=2026-08-17`):
`enabled true, candidates 0, written 0, skipped_unchanged 0`. **This says
nothing** — same dead-slate condition as above. Quoting it as a negative would
repeat the exact error the 08-17 run warned against.

**WHERE THE RESIDUAL LIVES:** lane `live-game-line-projection`, **OPEN and
UNOWNED** in `lanes.md:931`. Its header still reads "v2 STILL UNEXERCISED",
which the 3,748-row measurement disproves; corrected in the same pass as this
outcome. The evaluation half of that lane has still not started.

**Rows:** `deploys.md` — `2026-08-16 04:24:33Z — refresh-worker 5c419007 — ledger
v2 — DEPLOYED, NOT YET EXERCISED` and `2026-08-16 22:2x–22:3x CDT —
live-gameline-ledger-check, scheduled run`.
