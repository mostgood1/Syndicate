# HANDOFF — MLB odds provenance / betting-edge thread (2026-08-05)

Written at the end of a long session. Everything is committed and pushed through
**`f4fceb9a`**. Working tree clean apart from generated state.

---

## 1. DO THIS FIRST (5 minutes)

A deploy is in flight: **`dep-d9pvimnlk1mc73e9ec10`** on `live-odds-worker`
(`srv-d91dpertqb8s73co8lt0`), commit `f4fceb9a`.

Once it reads `live`, the provenance diagnostic fires on the worker's next
invocation — no forced refresh needed, it no longer sits behind a fetch. Then:

```bash
curl -H "X-Admin-Token: $ADMIN_TOKEN" \
  "https://syndicate-an21.onrender.com/api/ops/artifacts/stream?path=reports/mlb_odds_diag/odds_history_provenance_2026-08-06.json"
```

(Try `2026-08-05` too — the date used is the slate date passed to the fetcher.)

## 2. THE QUESTION IT ANSWERS

`odds_history` is written to three paths. The third,
`reports/odds_control_plane/odds_history/`, sits **outside `data_root()`** by
construction, so it can never be allowlisted and **never crosses services**. Web
cannot see it. This diagnostic runs on live-odds-worker, which can.

Compare the artifact's numbers against what web reports (measured 2026-08-05:
props **0%** bookmaker coverage, **2.0%** closing-line capture, 8 books on game
markets only):

| result | meaning | consequence |
|---|---|---|
| source **>>** web | **PUBLISH defect** | Prop verdicts in #186–#204 are RECOVERABLE. CLV is measurable today. Fix the sync path. |
| source **≈** web | **CAPTURE defect** | Both are forward-only fixes. Prop verdicts are genuinely unrecoverable. |
| `freshest_summary` empty | no odds_history on that disk | shards live elsewhere — itself a finding |

This gates everything else. Do not resume modelling until it is answered.

## 3. WHY IT MATTERS (the one-paragraph version)

Every ROI number in #186–#204 was graded against **one arbitrarily-chosen
bookmaker** (sometimes offshore books like `mybookieag`), because the game-lines
artifact keeps a single price per game while the API call already returns ~5–8
US books. That inflated apparent edge, drove worse selection, and settled at
worse prices — three errors compounding the same direction. Separately, CLV has
never been measured, and outcome-based ROI on 300–500 bets has no power to
detect a 2% edge (bootstrap CI on the moneyline was `[-5.5%, +22.4%]`).
**Model quality was never the binding constraint.** See #195, #205, #206.

## 4. THEN, IN ORDER

1. **Fix closing-line capture** — CLV is the only instrument with the power to
   detect the edge size that matters. Every day without it is unusable data.
2. **Fix prop book capture** — add the bookmaker dimension to prop history; stop
   collapsing to one book at persistence.
3. **Re-grade GAME markets against best price** — possible today from existing
   odds_history (8 books). The only retroactive win available.
4. **#202 Phase 1 continues** — H1–H3 (K slices). Rules are pre-registered in
   `docs/ai_context/mlb_edge_scan_preregistration.md` and must be applied
   verbatim; H8 (NRFI) already ran and FAILED all rules (#203).
5. **Also broken, found in passing**: the pre-existing `live_events_coverage`
   diagnostic is allowlisted but has never reached web (absent for every date
   back to 2026-07-20) because nothing published it. Same root cause as #207.

## 5. HARD-WON GOTCHAS — READ BEFORE TOUCHING ANYTHING

- **Allowlisting only PERMITS a push.** `write_json_file` does not cross
  services. Something must call `publish_hot_artifact`. (#207)
- **`git commit` with no pathspec commits the WHOLE index.** A parallel session
  works in this same checkout; explicit `git add` does not protect you. Always
  `git commit -m "..." -- <exact paths>` (pathspec goes LAST).
- **A parallel session ran `git checkout --` and destroyed uncommitted work.**
  Commit early. Never leave things staged you are not about to commit.
- **Check the `commit` field in the Render deploy response.** The first
  redeploy came back on a stale commit because Render read the branch head
  before the push propagated. Re-trigger after ~10s.
- **`sims-list` and `artifacts/stream` resolve roots differently** — sims-list
  reports dates that stream returns 0 bytes for. Trust stream.
- **Web's disk only goes back to 2026-05-28.** Render has sims to 04-10 but they
  are unreachable (#193a). 66 dates for odds/summary work, 48 with rosters.
- **Trace, don't reason, about call chains.** I guessed wrong twice about why the
  diagnostic did not fire. Both were resolved in one grep of the actual chain.

## 6. EPISTEMIC WARNING

This thread produced **six self-corrections**, two caught by the user rather than
by me — both times because I concluded from a synced copy instead of the service
that owns the data. Reversals included #188 (Statcast "doesn't help" → does),
#192 (1.85× lift → 1.59×), #187 (K edge → not significant), a +51.9% moneyline
that was a join bug, and a "34% over-dispersion" that was a truncation error.

**Every number here computed once, without an independent cross-check, has had
roughly even odds of being wrong.** Cross-check before acting, prefer a control
(does the *sibling* artifact exist?) over an assumption, and state date counts
with every result — `season_data.usable(*families)` exists for exactly that.

## 7. USEFUL ARTIFACTS

- `season_data.py` (scratchpad) — accessor over the Render+StatsAPI cache with
  `coverage()` / `usable()`. 66 dates odds/summary, 48 with rosters, point-in-time
  `batters_faced` rebuilt for 116 dates.
- Cache lives in the session scratchpad `season_cache/` — regenerate with
  `pull_season.py` (resumable) if gone.
- Trail in `docs/ai_context/todo.md`: **#193 → #207**, newest first.
