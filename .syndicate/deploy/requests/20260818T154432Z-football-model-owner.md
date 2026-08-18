# Deploy request — set `CFBD_API_KEY` on refresh-worker before the NCAAF opener

> **STATUS 2026-08-18 21:5xZ — ASK DISCHARGED, VERIFY STILL PENDING. NOTHING
> IS OWED TO ANYONE HERE; do not action this file.**
>
> - ✅ **`CFBD_API_KEY` IS SET on refresh-worker.** The ⬜ line below is STALE —
>   it was true when written at 18:48Z and false by 21:43:32Z. Record:
>   `deploys.md` → "2026-08-18 21:43:32Z — refresh-worker `00e9a49f` —
>   `CFBD_API_KEY` set — lane `football-model-owner`". Key count 105 → 106,
>   confirmed BY NAME never by value; absent on web and live-odds-worker, which
>   is correct — only the NCAAF generator reads it.
> - **The user set it in the Render dashboard, which fired Render's own
>   `service_updated` deploy.** No deploy was needed from the lane, and one
>   would have been destructive: preflight at 21:44:54Z read `HOLD: 2 job(s) in
>   flight` (an MLB sim and `daily_update --workflow ui-daily`). `trigger` is
>   the field that proves it — the preceding five deploys are `api`, this one
>   is not.
> - ⏳ **`verify:` HAS NOT PASSED YET, and this is not a pass.** Baseline taken
>   BEFORE the autorun: `0 of 51` games carry a non-null
>   `predictions.home_mean`. PASS is `51 of 51`, expected within one autorun
>   cycle (interval 86400s, so ≤24h from 21:43Z). **The ask being discharged is
>   not the same as the deploy being verified** — whoever reads this next
>   should run the `verify:` curl below, not assume it.
> - ✅ **The ordering hazard is fully resolved.** It required web-before-key;
>   web `841b6d84` (carrying `5fdabc46` + `4c3b0aa5`) went live at 20:31:26Z,
>   ahead of the 21:43Z key. Key-alone — the one combination to avoid — did not
>   happen.
>
> ---
>
> **SUPERSEDED STATUS 2026-08-18 18:48Z — HALF DONE. The WEB half is LIVE AND
> MEASURED; only the KEY remains.** *(kept for the record; the ⬜ below is now
> false)*
>
> - ✅ **Web deployed and verified.** `5fdabc46` + `4c3b0aa5`. The 16-game cap is
>   gone: served payload now 51/49/57/56/56/66 across weeks 1/2/3/5/8/12, with
>   `truncated: false` and `dropped: 0` on every one. **The ordering hazard this
>   file warned about is now RESOLVED** — the board can no longer cut a ~51-row
>   projection artifact back to 16 the moment the key starts producing one.
> - ⬜ **`CFBD_API_KEY` still ABSENT on refresh-worker.** This is the only
>   remaining blocker, and **it must be set by a human — I do not enter API keys.**
> - ⚠️ **refresh-worker showed `HOLD: 3 job(s) in flight`** at 17:4xZ. Its deploy
>   needs a clear preflight window; unlike web, its preflight instrument WORKS
>   (7s-fresh sample), so just re-run it and wait for CLEAR.
> - Revised `verify:` — with the cap gone, expect **~51 of 51**, and `16 of 16`
>   is no longer a plausible pass at all.

    service:   refresh-worker (srv-d91dpertqb8s73co8ls0)  [env]
               web / syndicate (srv-d88ahvrbc2fs73eodu30) [code]
    sha:       752a866d for WEB. refresh-worker is ENV-ONLY (no new code).
    reason:    NCAAF has produced ZERO projections and will keep producing zero
               through the 2026-08-29 opener. The sole blocker is one absent env var.
    verify:    the SERVED board, not a log line and not a file: ~51 of 51 NCAAF
               games carry a non-null predictions.home_mean. `16 of 16` is a FAIL.
    rollback:  env — remove the key; NCAAF returns to its current zero-output
               state, the status quo. No other sport reads it.
               code — revert `752a866d`; the board returns to a 16-game cap.
               Both are independently reversible.
    urgency:   ELEVEN DAYS. Not an outage today — NCAAF is out of season — but
               the fix must be live and PROVEN before 08-29, and proving it needs
               one daily autorun cycle to turn over. Do not leave it to the 28th.

---

## ORDERING — the code must not land AFTER the key

**Two parts, and the sequence matters.**

1. **WEB first (or together): deploy `752a866d`.** It raises the NCAAF board's
   hardcoded 16-game cap to 80. 16 is the NFL's natural weekly slate; FBS plays
   50–60, and CFBD lists **51** FBS-vs-FBS for 2026 wk1.
2. **THEN refresh-worker: set `CFBD_API_KEY`** (the env change described below).

**If the key lands first, the board serves 16 of 51 and looks fixed.** The
SmartSim2-standalone branch of `build_smartsim_cards_page_context` returns zero
rows today *only* because the projection artifact is missing. The moment the key
produces that artifact, the branch returns ~51 rows — and the pre-`752a866d`
`[:16]` cuts them straight back to 16. Predictions would be non-null on all 16
and the `verify:` below would **pass while two thirds of the slate was missing.**

**Deploying web alone is safe and is already an improvement** — the cap binds
today (exactly 16 on all six weeks sampled), so widening it widens the board
immediately, with or without the key. **Deploying the key alone is the one
combination to avoid.**

`752a866d` touches `syndicate/features/ncaaf/cards.py` only, plus tests and docs.
74 NCAAF-surface tests pass.

## The change

**Set `CFBD_API_KEY` on refresh-worker.** One key, one service.

**I have not put the value in this file and will not** — it is a secret. It is
present in the repo-local `.env` (gitignored) as `CFBD_API_KEY`. Take the value
from there, or from the CFBD account directly, and set it through Render's
single-key env-var endpoint or the dashboard.

**`render.yaml` must NOT be touched for this.** A blueprint push fires
`blueprint_sync`, which rewrites the WHOLE env block on live services and 502'd
every route for ~2 minutes on 2026-08-08. This needs one key on one service.

Per the standing note: **a Render env change does not take effect on restart —
env vars are injected at deploy.** Single-key endpoint, then a deploy of the
service. **refresh-worker's deploy carries no new code** — redeploy whatever is
live (`00e9a49f` at time of writing). The `752a866d` code half is WEB only.

---

## Why — measured, not inferred

**Production state, refresh-worker logs 06:00Z–15:34Z today:**

    SEASON_PROJECTION_ARTIFACT_MISSING sport=ncaaf artifact_missing_after_launch
      since_launch_seconds=43375 -> 75416   interval_seconds=86400

21 matches in the window, **21 of 21 `sport=ncaaf`, 0 `sport=nfl`.** That split
is the positive control: the same guard is silent for the football sport that
works, so it is reporting a real NCAAF-specific failure, not misfiring.

`since_launch_seconds` climbs monotonically and `interval_seconds=86400`, so this
is a **once-daily** failure, not a relaunch loop. **It is not burning worker
cycles** — I checked, because on a service with this OOM history that would have
changed the urgency. It has not.

**The blocker, isolated by a two-arm test run locally against the real CFBD API:**

| arm | result |
|---|---|
| **A — no CFBD key anywhere (= production today)** | `RuntimeError: Missing CFBD API key.` Run dies before any game is fetched. |
| **B — with the key** | CFBD returns **99 games** for 2026 wk1 → `#445` fallback yields **51 FBS-vs-FBS rows** → PPA ratings **136 teams** (`cfbd_ppa_season_2025_fallback_for_2026`, the prior-season proxy behaving exactly as designed) → **50 of 51** home teams resolve to a non-zero rating. |

**Everything downstream of the key already works.** Specifically confirmed
against the DEPLOYED tree (`00e9a49f`), by content and not by ancestry:

- `#445`'s guard IS live — `generate_smartsim2_ncaaf_projections.py:102`
  `if not ENHANCED_CSV.is_file():` is present in the deployed blob, so the old
  `FileNotFoundError` is gone and the CFBD fallback is reachable.
- The same deployed blob still raises on the missing key at `:57`.

So the run now gets one step further than it did before `#445` and dies at the
next gate. **`#445` was a real fix and is not the problem.**

---

## verify: — the reading that proves it worked

**Do not accept a log line for this.** The failure mode is a run that starts and
dies, which produces plenty of log activity and no artifact.

**THE READING THAT MATTERS — the served board, not the disk.** Measured today on
production `GET /ncaaf/api/cards?week=1`: **16 games served, and all 16 carry an
entirely NULL predictions block** —

    "predictions": {"home_mean": null, "away_mean": null, "margin_mean": null,
                    "total_mean": null,
                    "probabilities": {"home_win": null, "away_win": null,
                                      "home_cover": null, "away_cover": null,
                                      "total_over": null, "total_under": null}}

`smartsim_reasons` is `[]` on every one. **The NCAAF board is live and shows no
model output whatsoever.** That is the missing projection artifact seen from the
user's side, and it is the cleanest pass/fail available:

**PASS = `predictions.home_mean` is non-null on that served payload.**

Re-read it with:

```bash
curl -s "https://syndicate-an21.onrender.com/ncaaf/api/cards?week=1" | python -c "import json,sys; g=json.load(sys.stdin)['games']; print(sum(1 for x in g if x['predictions']['home_mean'] is not None), 'of', len(g), 'games have a model number')"
```

Today that prints `0 of 16`. After BOTH parts land it should print roughly
`51 of 51` — **not `16 of 16`.** A `16 of 16` means the code half did not ship,
or shipped after the key.

**Also read `board_row_counts` on the same payload** (new in `752a866d`), which
reports `runtime_rows`, `limit`, `truncated` and `dropped` whether or not it
truncated:

```bash
curl -s "https://syndicate-an21.onrender.com/ncaaf/api/cards?week=1" | python -c "import json,sys; d=json.load(sys.stdin); print(d.get('board_row_counts'))"
```

`truncated: true` after the deploy means the slate is still being cut and the
limit needs revisiting. A missing key means the code half is not live.

### The secondary reading (disk side, same fact)

**The reading:** within one autorun cycle (≤24h, `interval_seconds=86400`) of the
deploy, this file exists on refresh-worker's disk and is non-empty:

    /opt/render/project/data/ncaaf_source/data/smartsim2_projections_2026_wk1.csv

and `SEASON_PROJECTION_ARTIFACT_MISSING sport=ncaaf` **stops appearing** — that
warning is emitted precisely because the artifact is absent, so its disappearance
is the same fact read from the other side.

**Expected content, so a degenerate artifact is not mistaken for success:**
roughly **51 rows** (FBS-vs-FBS for 2026 wk1) with `rating_source` reading
`cfbd_ppa_season_2025_fallback_for_2026`. **A 0-row or 1-row CSV is a FAILURE**,
not a pass — an empty projections list still writes a file.

If it is still missing after 24h, the next thing to read is whether the autorun
launched at all: `SEASON_PROJECTION_ENABLE_REFRESH_WORKER_AUTORUN` is currently
`'1'` on refresh-worker (verified today), so it should.

---

## Scope — what this does NOT do

- **It does not fix the model.** After this lands, NCAAF will produce projections
  from four rating scalars, like NFL. `smartsim2` consumes 65 feature keys and no
  production entrypoint passes any (`#457`,
  `docs/ai_context/football_sim_engine_reference.md`). This request only gets
  NCAAF producing the projections it is already designed to produce.
- **It does not touch NFL.** NFL derives ratings from nflverse pbp and never
  reads this key.
- **It may not cover the whole slate.** CFBD lists **51** FBS-vs-FBS games for
  2026 wk1; the board serves **16**. That gap is unexplained and is being tracked
  separately — do not treat `16 of 16` as proof the full slate is covered.

**CORRECTION to an earlier claim of mine, made before I filed this:** I had
recorded that "the NCAAF feature loader returns zero games". **That is true only
of my LOCAL checkout.** Production serves 16. The local zero was the
`data/**` lossy-mirror trap, and I nearly filed it as a production defect.
`#458` is corrected accordingly.

Filed by lane `football-model-owner`, 2026-08-18 15:44Z. Carrying on with `#458`
rather than blocking on a reply.
