# NBA live games with no Live proj. / Live actual on Layer 2 — 2026-11-04 (lane `nba-live-proj-actuals`, session c3e396a7)

User report (2026-11-04 ~6:45 PM CT): "On the layer 2 board, I'm not [seeing] live proj and live actual being
populated across a lot of games that are live."

Substrate: the FLEET (production). Served board = `POST http://127.0.0.1:10000/api/intelligence/query`
(`response.ranked_all`), artifacts read from the fleet Redis (`syndicate:refresh-state:<data root>/live/...`),
logs from `/home/amyn/syndicate-prod/logs/`. Nothing here is from the git `data/` mirror.

## 1. The symptom, measured

Served board 2026-11-05 00:49:04Z (snapshot `state_meta.dates.2026-11-04.sources.layer2_shortlist` = 00:48:09Z),
live NBA rows only:

| game (tip, commence_time) | game rows w/ Live proj. | prop rows w/ Live proj. | prop rows w/ Live actual |
|---|---|---|---|
| ATL @ WAS (00:12Z) | 25 / 47 | 27 / 28 | 27 / 28 |
| PHI @ DET (00:13Z) | 23 / 61 | 29 / 34 | 29 / 34 |
| CHA @ BKN (00:30Z) | **0 / 39** | **0 / 36** | **0 / 36** |
| CHI @ NYK (00:40Z) | **0 / 35** | **0 / 32** | **0 / 32** |
| MIL @ BOS (00:40Z) | **0 / 55** | **0 / 69** | **0 / 69** |

Total: 436 live NBA rows, 104 with Live proj. Game rows' full-game Actual (the score) was present for all five
(it comes from the chip game-state join); quarter/half rows never carry a live number (see §5).

## 2. Cause A — the Layer 2 build lag (15-25 min after tip)

The live columns were written only by the Layer 2 build. Fleet logs, 2026-11-05:

- `00:41:34Z [layer2_shortlist] LIVE_PROJECTION_JOIN sport=nba ... lens_indexed=1423` and
  `LIVE_GAMELINE_JOIN ... index=2` — the join ran while the re-sim held 2 games;
- `00:44:01Z NBA_LIVE_RESIM_TICK games=5 resimmed=5` — the re-sim reached all five;
- `00:48:04Z [layer2_shortlist] LAYER2_BOARD_HEALTH sport=nba rows=1161 ... live_proj=58` — the publish
  carried the 00:41 join.

Join cadence 00:32:28 -> 00:41:34 (~9 min); publish ~6.5 min after its join. A game tipping just after a join
waits for the next join plus its publish. The lens on the web's own box (`live/nba_live_lens.json`, written every
~60 s by live-odds-worker's lens loop, merging the re-sim) already carried 716 / 721 re-sim props for CHA@BKN /
MIL@BOS at 00:50:30Z. MLB had this exact defect in 2026-08 and got a read-time refresh
(`intelligence._refresh_live_columns_from_artifact`); NBA never did.

**Replay** (the 00:49Z served payload + the 00:50:30Z lens, through the new read-time refresh): props with
Live proj. CHA@BKN 0 -> 25 / 36, MIL@BOS 0 -> 36 / 69, PHI@DET 29 -> 31, ATL@WAS 27 -> 27; CHI@NYK stays 0 (cause B).

## 3. Cause B — the re-sim budget starves the scoreboard tail

`nba/live_resim.build_live_lens_snapshot` walked ESPN scoreboard order under ONE 240 s tick deadline. When the
slate does not fit, the games at the END of the scoreboard are refused `budget_exhausted` — the same games every
tick — and a refused game publishes `pregame_only`, i.e. no live number at all.

`NBA_LIVE_RESIM_TICK` lines over the retained logs (10-31 .. 11-05):

| hour (Z) | ticks | max live games | mean elapsed s | ticks exhausting budget | game-ticks refused |
|---|---|---|---|---|---|
| 11-01 00-01 | 44 | 5 | 41-47 | 0 | 0 |
| 11-03 00 | 20 | 6 | 60 | 2 | 4 |
| 11-03 01 | 10 | 11 | 236 | 8 | 27 |
| 11-03 02 | 10 | 12 | 235 | 8 | 21 |
| 11-03 03 | 14 | 9 | 144 | 2 | 2 |
| 11-05 00 | 20 | 5 | 50 | 2 | 4 |

Per game on the 11-02 slate (`live_resim_history/2026-11-02.jsonl`, 95 ticks), ordered by mean scoreboard position:
OKC@CLE / DET@CHA / PHX@GSW / ATL@IND / TOR@LAC / BKN@NYK re-simmed on 98-100% of their ticks; NOP@MEM 70%,
BOS@HOU 70%, UTA@SAS 64%, MIL@MIN 64%. Longest consecutive refusals: **UTA@SAS 10 ticks (~1 h)**, NOP@MEM 7,
MIL@MIN 7, SAC@DAL 6, POR@DEN 6. Tonight 00:50:02Z: CHI@NYK `budget_exhausted 72/100`.

Per-game cost swings ~5x with host load (00:44Z: 5 games in 56.5 s; 00:50Z: 4.7 games in 241 s while
`INPLAY_OVERLAY` took 326 s) — capacity, not a fixed per-game cost, sets how many fit.

## 4. The fixes (lane `nba-live-proj-actuals`)

1. **Re-sim (live-odds-worker): stalest-first + bounded carry-forward.** Never-re-simmed games first, then the
   oldest re-simmed state. A budget refusal republishes the game's previous `live_resim` lane and props, stamped
   `carriedForward` / `carriedRefusal` / `carriedAgeSeconds`, keeping its ORIGINAL `liveStateAsOf` and `simsRun`
   (never a thinner number), refused as before once that state is older than 900 s. Sized from the cadence
   measured under load: at peak a tick runs 240 s then waits 120 s, so a game re-simmed first in one tick is
   ~595 s old when the next tick reaches it -- 600 s (first draft, the live quote ceiling) would have refused
   about a quarter of single-tick carries. History records a carried lane as the refusal
   the tick produced (`pregame_only` / `budget_exhausted` + `carried_forward`), so forward grading never
   double-counts it; the tick line's `resimmed` counts fresh lanes only and `carried=` is new.
   Switches: `SYNDICATE_NBA_LIVE_RESIM_CARRY` (absent = ON), `SYNDICATE_NBA_LIVE_RESIM_CARRY_MAX_AGE_SECONDS`.
   WNBA's wrapper calls the same builder without `previous`, so it is unchanged.
2. **Web: read-time refresh of NBA prop `live_projection` / `actual`** from `live/nba_live_lens.json`, keyed by the
   build join's own lookup (`live_projection_join.live_prop_hit`), same date only, 15 s per-process index reuse.
   Line `[intelligence] LIVE_COLUMNS_REFRESHED_FROM_ARTIFACT sport=nba considered= matched= refreshed=`.
3. **Layer 2 build: a live gameline's `total_mean` fills `live_total` on TOTALS rows only.** Spread rows (NBA 27,
   NCAAF 6, NCAAB 3 at 00:49Z) and moneyline rows (NCAAB 3, NCAAF 1) showed the game's projected total as their
   Live proj. ("215.9" beside PHI -3.5). Spreads now show the live cover probability.

Money: in-play entries are refused on both venues after commence (`cd0901bf`), so none of this reaches an order.

## 5. Seen, NOT fixed here (follow-ups)

- **Quarter / half lines never get a live number:** `segment_is_not_full_game` withholds 948-2,194 NBA rows per
  join (`seg_index=na`); the re-sim already publishes per-segment means (`projection.segments`). ~50% of live NBA
  game rows.
- **The NBA lens's own game state is stale:** at 00:50Z `nba_live_lens.json` had MIL@BOS / CHA@BKN / CHI@NYK as
  `Scheduled 0-0` and ATL@WAS at "1:07 - 1st" while the re-sim's ESPN summary had them in Q1 / Q2. The Layer 2
  rows' live flag comes from the chips, so the board is unaffected; the NBA page lens and the join's
  `lens_live_games` instrument (0 for NBA: the lens `status` is a string, `_status_text` reads mappings) are.
- **The live gameline join has no MODEL-lane age gate**, only a quote-age one: a lane is priced however old it is
  by the time the board reads it (up to ~15 min before this change).
- NCAAB has its own copy of `build_live_lens_snapshot` (`ncaab/live_resim.py:959`) — the same scoreboard-order
  budget shape is likely; not measured.

## 6. Overtime dropped from the live full game -- FIXED on main `d6a691168` (todo `#763`, NBA half)

Reported by lane `wncaab-module` (session "NCAAB readiness check"), verified here. `basketball_engine` returns
regulation periods in `home_q_pts` / `away_q_pts` and every overtime in the box's `ot_pts`
(`engine.py` overtime loop + `home_box["ot_pts"]`); `resim_live_game` summed the period lists only. Fleet
`live_resim_history` 10-13..11-05, 6,215 `live_resim` lanes: 74.2% carry at least one regulation-tied draw, 2.9% of
draws on average; Q4 last 5:00 at margin <= 5 (250 lanes): 9.2% (home win probability understated ~4-5 pp, total
~1 pt). **All 41 lanes resumed IN overtime published `modelHomeWinProb` 0.0** (every draw a regulation tie). The fix
adds each box's `ot_pts` to the full-game total / margin / win; quarter and half blocks stay regulation-only.
Negative control: a real-engine resume tied after regulation returns 0.0 without the fix and a real split with it.
