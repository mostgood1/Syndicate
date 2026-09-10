# Open-work census — 2026-09-10

`[2026-09-10 09:55 CDT, session 78cad512 / desktop local_b85a1f7c, lane census-rescue-0910]`

A scrub of every source of open work — lanes, `todo.md`, the rest of the ledger,
git, Render, scheduled tasks and every Claude session — requested by the user,
with an execution plan. The full plan went to the user as an HTML page; this
file is the durable record. Sources: `.syndicate/` + `docs/ai_context/` read
from a `git archive` snapshot of `origin/main dbf38452` (the primary checkout
was 812 commits behind), the Render deploys API (read-only), the scheduled-task
roster, the session roster and transcripts, and a `git worktree` / `stash` /
branch census. Six read-only agents plus direct checks.

## Headline numbers (at 09:55 CDT)

- **24 OPEN lanes**; 11 held by an archived or missing session. One idle session
  (desktop `c05fdbca` = CLI `2edf8b82`) held 8 of the 24.
- **`todo.md`: ~240 items, ~140 open** (±10, going by each item's own status
  tag). About 105 of the open items wait on a production reading, 25–30 need
  code, about 35 have no owner.
- **Sessions:** 2 running (a bandwidth-tripwire scheduled run, and
  `portfolio-login-multibook`). About 45 of ~60 unarchived sessions are finished
  scheduled runs.
- **Render:** web + live-odds-worker live on `26c8cfc6`, refresh-worker on
  `0ceb9636` — all three ancestors of `origin/main`; `origin/deploy/*` count is
  **0**. Web was 11 code commits behind main.
- **Git:** 63 worktrees (32 safe to remove), 8 stashes (5 safe to drop), 3 local
  branches with content-unique commits, no remote branch with unique content.

## Why the ledger misreported — three mechanisms

1. **Id spaces.** Lane headers and deploy claims record the bare CLI session
   uuid; `list_sessions` returns desktop `local_` ids. "Owner absent from
   roster" is therefore ALWAYS the result, even for a live owner. The mapping
   that works: `search_session_transcripts` for the uuid as it appears in the
   holder's own scratchpad / task-output paths. Cost: `bandwidth-controlled-transfer`
   was adopted three times, and `board_enrichment.py` was taken from
   `mlb-stop-publishing-edges` on "nobody to ask".
2. **The stale primary checkout.** The session-start digest and
   `check_lane_claims.py` read the primary tree. At 812 behind, the digest
   reported 21 open lanes (24 on main) and `LEDGER INCOHERENT` for four claimed
   files that all exist on `origin/main`.
3. **Stale `.current-lane.*` pointers.** Four named closed lanes and three named
   slugs that exist nowhere.

## Claims that did not survive checking

- **Polymarket `atc-sea-ata-bol` "live on the wrong side, needs manual
  closure".** The ledger's own 2026-09-03 correction says status UNKNOWN: the
  fixture was 2026-08-31, so it has most likely settled without being recorded.
  The user is to confirm in the venue account.
- **NCAAF `h1` totals for 09-12 priced off a Polymarket full-game contract, with
  the refusal off.** `_SEGMENT_REFUSAL_ENABLED = True` on main since `90493e64`
  (2026-09-06), and every live service runs a later commit. `state_kalshi.md`'s
  "STILL LIVE" note is stale.
- **"The NFL prop autorun doesn't exist."** It was wired in `4be5c5a5`
  (2026-09-08). What is unproven is that it has FIRED.
- **"The bandwidth fire gate was never switched to metered/app-served."** It was
  switched in `2b72946e` and re-armed on the new gate in `2c9d01c2`.
- **"170 `origin/deploy/*` branches"** (CLAUDE.md) — there are 0 now.

## The plan, by deadline

- **Today (09-10).**
  - A7 — rescue work that exists only on this machine (lane
    `census-rescue-0910`).
  - A1 — ledger truth pass (same lane).
  - A2 — `restore-measurement` reading 1, the settlement autorun, is overdue
    after two tries. Hold refresh-worker deploys around the autorun.
  - A3 — web deploy once the portfolio credentials are set.
  - A4 — read whether `f5c2468a`'s MLB switch is in force.
  - A5 — the three tooling fixes above.
- **Before Saturday 09-12.**
  - `#633`: decide what to do about the CFBD quota.
  - Reassign `ncaaf-live-resim-wire`'s residual scope. The git census found only
    one runtime JSON in its worktree, so it is less at risk than first reported.
  - `ncaaf-games-cache-refresh`: its last reading, on 09-08, FAILED.
- **Sunday 09-13 to Tuesday 09-15.**
  - Prove the NFL prop autorun fires before kickoff.
  - NFL week-2 projections trap: production's
    `smartsim2_projections_2026_wk2.csv` is a pre-refit July file with no profile
    columns.
  - Once reading 1 passes, widen `EVALUATION_SETTLEMENT_SPORTS` in order: nfl,
    then ncaaf, then soccer.
- **By 09-17.**
  - Edge-plan Phase 0 (`#626`).
  - Add WNBA to Layer 2; its active sports are `ncaaf` and `soccer` only.
  - Give web OOM one owner: fold `#435` and `#632` into `web-oom-census`.
- **Before October.**
  - Port the WNBA pricing fixes to NBA.
  - Build NBA, NHL and NCAAB settlement resolvers.
  - Explain NHL's checklist: 21 alarms in production against 0 locally.
  - Unowned: `#369`, `#448`, `#610`/`#611`, `#634`.

## Decisions put to the user

1. Portfolio credentials on web, then a web deploy.
2. The three stalled sessions: `05fdfc3e`, `65729cfd`, `c05fdbca`.
3. Close or reassign the orphaned lanes. **PARTLY GIVEN 2026-09-10:** "close the
   3 shipped lanes".
4. GitHub Actions billing, locked since 2026-08-22.
5. Keep `render.yaml` parked: `b3ebd0cb` is unpushed, and `#650` has it 167 vars
   behind production.
6. Move the bandwidth watcher's re-arm duty into a scheduled task.
7. Product decision `#3`.
8. Check `atc-sea-ata-bol`.
9. Sync the primary checkout once A7 is done.

## Since the census, same day

- 16:00-16:05Z: web deployed `df60b3e3` by lane `portfolio-login-multibook`. The portfolio
  sign-in is verified on production and that lane is closed, so decision 1 was acted on.
- Lane `census-rescue-0910` ran A7 (rescue) and the lane-closure and deploy-marker parts of A1.
  Where every rescued item went is in `recovered_2026-09-10_uncommitted_code.md`; the three
  closures are in `lanes_closed.md` and the reconciled markers in `deploys.md`.
