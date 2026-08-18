service: web
branch: main
sha: c87f6634
lane: live-game-line-projection
reason: `/api/board/book-grid` drops `live_gamelines` and `live_gameline_ledger`
        even though the artifact on web's own disk carries both. Reading either
        counter tonight required streaming a **9,953,474-byte** artifact through
        `/api/ops/artifacts/stream`. This is the instrument for the worker
        request filed alongside it — without it, the ledger's counters are not
        observable from an API at all.

        Same bug the route already carries a long comment about for
        `live_projections` / `live_game_state`. Second occurrence in one
        function, which is why the regression test asserts pass-through of the
        artifact's ungated coverage keys as a SET rather than by name.

**NOT blocked.** The refresh-worker hold does not apply to this service. But it
is also not urgent on its own: it makes a counter readable, it changes no
number. If web is quiet, ship it; if anything else is in flight there, wait.

blast radius: web only, and additive — two keys added to one JSON response.
        No template reads them. Absent still serializes as `null`, which is the
        "this artifact predates the join" signal the existing gate exists to
        give, so an old artifact degrades honestly.

**CHECK WHAT ELSE RIDES ALONG.** At the time of writing, another session has
uncommitted work in the SAME file (`syndicate/blueprints/intelligence.py`) —
a `?clv=1` join on `/api/board/layer2-shortlist`, visible in the working tree
and not in `c87f6634`. If it lands on main before this deploys, the deploy
carries it too. Deploy by content: diff the deploy target against the live SHA
rather than assuming this request describes everything in it.

verify: `/api/board/book-grid?sport=mlb&date=<today>&limit=1` returns
        `live_gamelines` as an object with `rows_live_gameline_considered`, and
        `live_gameline_ledger` as an object with `written`. Both `null` means
        the artifact predates the join, NOT that this deploy failed — check
        `generated_at` on the response before concluding anything.

        NB for whoever reads it: `index_size` inside `live_gamelines` counts
        snapshot games carrying a `live_mc` lens, **not live games**. Measured
        03:0xZ: 10 = 8 Final + 2 Live. It is monotone across a slate because a
        Final keeps its last lens. Its growth is not a defect.

rollback: previous deployed sha — read it at deploy time from
        `/v1/services/srv-d88ahvrbc2fs73eodu30/deploys`. **Do not assume it is
        an ancestor of main**: web runs a deploy branch.

---

## RESULT — SHIPPED AND MEASURED 2026-08-16 03:38Z

**Deployed `ebd5f677`, NOT `639ecce0`.** This request named a sha on `main`; the
preflight failed it. `main` is not an ancestor of what web runs — the live SHA
was `fa1871cf` and **33 commits were live on the service and absent from
`origin/main`**, including the opt-in per-recommendation `clv_pct` block
(`484221bd`) and `4316c907` ("a close stamped after first pitch is an in-play
price"). Deploying `main` would have reverted all 33. Re-parented on the live
SHA. The request's own "check what else rides along" paragraph is what caught it.

`dep-da0itvpt0dsc739pj3n0`, fired 03:31:11Z, `live` **03:38:07.648Z** (6m56s).

**MEASURED — the pre-registered predicate, met:**

    before (03:0xZ)   live_gamelines: null        live_gameline_ledger: null
    after  (03:38Z)   live_gamelines: {...}       live_gameline_ledger: {...}

    03:38:28Z  artifact 03:37:13.853Z  considered 8  index_size 10  written 0
    03:38:57Z  artifact 03:37:13.853Z  considered 8  index_size 10  written 0
    03:39:43Z  artifact 03:39:36.922Z  considered 8  index_size 10  written 0

**Two DIFFERENT artifacts, both serving the keys** — not two reads of one build,
which is the distinction the "two lags in series" rule exists for. The
discriminator is unambiguous here: the artifact already carried both keys
(proven at 03:00Z off the raw stream), so nothing but the route could have
turned `null` into an object.

**`written: 0` is EXPECTED and is not this deploy's business.** The recorder
still runs v1 on refresh-worker, where `candidates: 0` because 0 of 8 rows are
priceable. That is the worker request, still held.

**Cost recorded, not netted out:** fired 22:31 Central with 2 MLB games live, so
the board 502'd for part of a ~7-minute swap. No worker restarted; the OOM lane's
hold was not crossed and no in-flight sim was killed.

---

## OUTCOME — EXECUTED AND MEASURED. Recorded 2026-08-18 by the coordinator.

**This outcome was reconstructed, not written at the time.** The deploy happened
and was measured on 2026-08-16; the request file was moved to `done/` without
carrying the result back. Every number below is quoted from the `deploys.md` rows
named at the end, except the 2026-08-18 re-read, which I took.

**DEPLOYED** as `ebd5f677`, `dep-da0itvpt0dsc739pj3n0`, fired 2026-08-16
03:31:11Z, live **03:38:07.648Z** (6m56s), gated on the affirmative token `live`.

**NOT deployed from `main`.** The first preflight candidate was `639ecce0`
(= `origin/main`) and it was REFUSED: web was running `fa1871cf`, with **33
commits live on the service and absent from `origin/main`**. Shipping main would
have reverted another session's work the same night. Re-parented on the live SHA
and verified by CONTENT, not ancestry.

**MEASURED 03:38–03:40Z — PASS.** Pre-state was `null` for both keys at 03:0xZ.
After: `live_gamelines` and `live_gameline_ledger` both served as objects across
**two different artifacts** (`generated_at` 03:37:13.853Z and 03:39:36.922Z), so
two builds, not two reads of one.

    live_gamelines       considered 8  projected 2  priceable 0  edged 0
                         withheld 8 = {segment_is_not_full_game: 6,
                                       prob_interval_swamps_edge: 2}
    live_gameline_ledger candidates 0  written 0  enabled true

`written: 0` was correct and NOT this deploy's business — refresh-worker still
ran the v1 recorder at that moment. The worker half is the sibling request.

**STILL TRUE 2026-08-18** (re-read by the coordinator against web `e5107913`,
`/api/board/book-grid?sport=mlb&date=2026-08-17`): `live_gamelines`,
`live_gameline_ledger` and `live_gameline_score` all present as objects. The
pass-through did not regress across the deploys since.

**COST, recorded because it was real:** fired 22:31 Central with 2 MLB games
live; the board 502'd during the deploy.

**Rows:** `deploys.md` — `2026-08-16 03:31:11Z — web ebd5f677` (pending) and
`### MEASURED 2026-08-16 03:38–03:40Z — web ebd5f677 — PASS`.
