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
