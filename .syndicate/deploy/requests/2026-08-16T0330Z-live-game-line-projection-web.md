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
