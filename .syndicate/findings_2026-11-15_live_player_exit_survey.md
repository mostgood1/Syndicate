# Live player-exit survey — 2026-11-15 (lane `live-player-exit-gate`)

Question: when a key player leaves a live game mid-game (injury, ejection,
foul-out, goalie/keeper change, red card), can the fleet see it from a feed it
already fetches, within one live tick? And where must a refusal plug in?

Substrates: ESPN `site.api.espn.com/.../summary?event=` fetched live from this
machine on 2026-11-15 (public endpoint, the same one the live loops call); the
fleet's own disk `~/syndicate-prod/data` (read through WSL); code read at
`origin/main` 89498a5c6. No conclusion below rests on the git `data/` mirror.

## 1. The motivating exit, measured

NE @ DET, ESPN event 401873053, kickoff 14:30Z (8:30 AM CT), 2026-11-15:

| wallclock (Z) | CT | feed signal |
|---|---|---|
| 14:41:43 | 8:41 AM | play-by-play: `D.Maye sacked ... NE-D.Maye was injured during the play.` |
| 14:59:45 | 8:59 AM | first `T.DeVito pass` (the backup is in) |
| 15:43 | 9:43 AM | summary `injuries`: Drake Maye, `Out`, `Ankle` (stamp after kickoff) |
| halftime | — | fleet `nfl_source/live_prop_capture/2026-11-15.jsonl`: Maye 4 att, DeVito 7 att |

**The play-by-play line comes about 1 hour before ESPN's own Out ruling.** Detection has to read
the plays. The injuries list alone would miss an hour of a backup QB playing.
The fleet's NFL re-sim reacted to neither (0 player inputs, measured by the
lane opener).

## 2. What the ESPN summary carries, per sport (real payloads)

| sport | exit signal in the payload | field | verified on |
|---|---|---|---|
| nfl / ncaaf | injured-in-play, then returned | `drives.previous[].plays[].text`: `"TEAM-X.Last was injured during the play"` / `"** Injury Update: TEAM-X.Last has returned to the game."`, each with a `wallclock` | 401873053 (Maye out; M.Moses out 14:56Z, returned 15:30Z) |
| nfl / ncaaf | in-game ruling | `injuries[].injuries[]` `status` + `date` stamped AFTER `header.competitions[0].date` | 401873053 (Maye Out 15:43Z; Hutchinson Questionable 15:06Z) |
| nba/wnba/ncaab/wncaab | ejection | `boxscore.players[].statistics[0].athletes[].ejected` (bool) | key present in 5 of 5 NBA finals from 11-14 (none true) |
| nba/wnba/ncaab/wncaab | foul-out | the `PF` column, at the league limit (6 / 6 / 5 / 5) | labels present in 5 of 5 |
| nba/... | in-game Out | `injuries` stamped after tip | the field exists. **Not yet observed live.** Every stamp on the 11-14 finals was a next-morning update. |
| nba/... | starter | athlete `starter` (bool) | 5 of 5 |
| nhl | goalie change | the team's `goalies` box category: a 2nd goalie with `TOI` > 0 | 401892708 (WPG Skinner 20:00, then Daws 43:41) |
| soccer | red card | `keyEvents[].type.text == "Red Card"`, **exact match**. `"Penalty - Scored"` contains "red", and my first scan matched it. | 401879244 (Igor Thiago 23') |
| soccer | keeper change | `rosters[].roster[]` `position.abbreviation == "G"`, `starter`, `subbedOut` | key present (not observed true) |
| mlb | — | statsapi `feed/live`, not ESPN. Out of season until 2027 and not surveyed for this pass. | — |

NBA play-by-play had no "injur"/"eject" text in 5 games, and the in-game
basketball injury signal is unproven. **Basketball injury exits may be invisible
to this feed until ESPN posts an Out, and that is the open risk for NBA.**
Ejection and foul-out are explicit.

## 2b. Corrections from the code-side feed survey (2026-11-15 ~11:00 AM CT)

- **The basketball `ejected` box flag is unreliable.** On a real WNBA final
  (401856991), "Isabelle Harrison ejected" is a play of type `ejection`, but her
  box entry still says `ejected: false`. The detector reads the play. Fixture and
  test are added.
- **NHL's live path is api-web, not ESPN.** It fetches
  `/v1/gamecenter/{id}/boxscore` every tick (`live_player_actuals`). Goalies
  carry `starter` and `toi`, and `exits_from_nhl_boxscore` marks the starter out
  once a non-starter has ice time. Real final 2025021309: Vejmelka (starter)
  40:00, Vanecek 18:31.
- **Already modelled, so refusing would discard a priced state (open decision
  for the user):**
  - **Basketball foul-outs:** the NBA, WNBA and NCAAB re-sims drop a fouled-out
    player from the lineup (`basketball_engine/resume.py:28-29,126-128`).
  - **Soccer red cards:** applied as a team rating penalty
    (`soccer/features/live_lens.py:79-98`), and props use the on-pitch lineup.
  - **MLB pitching changes:** the sim always uses the current pitcher.

  The lane goal names foul-out, so the detector refuses a starter's foul-out
  today.
- **Cadences, i.e. what "one live tick" means:**

  | sport | re-sim cadence |
  |---|---|
  | NFL | 300 s (refresh-worker) |
  | NCAAF | 75-180 s |
  | NBA / NCAAB | own thread, 120 s |
  | NHL / soccer | 60 s loop |

- **MLB:** the statsapi `feed/live` carries `playEvents[].details.eventType` of
  `injury` (2 in September) and `ejection` (9, managers included), plus
  `gameStatus`, but nothing reads them on the live path. Off-season until 2027.
- **No live tick persists a raw payload.** The fixtures here are the only
  replayable in-game evidence, which is why the fleet measurement must be taken
  live.

## 3. Detector built (`syndicate/features/shared/live_player_status.py`)

`exits_from_espn_summary(sport, summary) -> GameExitStatus` is pure, and returns
empty unless `status.type.state == "in"`. `gameline_refusal(status)` refuses on
any KEY exit (`key_player_out`). `prop_refusal(status, player)` refuses that
player's props on any exit (`key_player_out` / `player_out`).

KEY means: a QB in football, a starter in basketball, a goalie in NHL, and a
red card or a keeper in soccer. Switch `SYNDICATE_LIVE_PLAYER_EXIT_GATE`
(absent = on). 23 tests run on the four real payloads above.

## 4. Where a refusal must plug in (code at 89498a5c6)

No OPEN lane lists any of these files in its `Files:` line (checked 2026-11-15
against lanes.md). `nfl-live-width-fit` owns only its findings file.

- **Gamelines:** `live_gameline_join.attach_live_gamelines` (2257). The shared
  staleness choke point is at 2496-2539 (`quote_age_verdict or
  quote_behind_score_verdict or lane_verdict`). A `key_player_out` verdict added
  there covers moneyline, distribution and analytic rows, and the row never
  becomes `live_aware`, so `live_edge_policy` also refuses the edge. Segment rows
  are refused earlier (2353-2466), so a game-level gate must run before 2325.
- **Producers (better for gamelines):** each `<sport>/live_resim.py` already has
  a `*ResimRefusal(reason, detail)` that publishes a `pregame_only` lane, which
  the join withholds. This hands the refusal its lane, `refusalsByReason` and
  the tick log at no extra cost:
  - nba/wnba `NbaResimRefusal`
  - ncaab/wncaab `NcaabResimRefusal`
  - nfl `NflResimRefusal`
  - ncaaf `NcaafResimRefusal` (it already takes a caller-named
    `game["refusal"]`)
  - nhl `NhlResimRefusal`
- **Props:** `live_projection_join.attach_live_projections` (585). Plug in at
  about 725, beside the `pulled` check, either by keeping the row display-only or
  by calling `_withhold(projection, "key_player_out", ...)`. After line 835 a row
  is `live_aware`, and only `_withhold` can still stop it. Priced live-prop sports
  today: mlb, wnba, soccer, and nba when `SYNDICATE_NBA_LIVE_PRICED` is set. NFL
  and NHL props get box actuals only and are never priced.
- **Portfolio:** `shared/portfolio_commit.commit_portfolio` (1056), with
  `refuse(reason,row)`. Adding `refuse("key_player_out", row)` next to the
  in-play-fair check (1156) holds paper2, the live plan and every venue at once.
- **In-play entries (book consensus, not the model):**
  `inplay_entries_paper.PaperEntryLoop._step` (around 517) and
  `inplay_entries_live.LiveEntryPlacer.__call__` (276-300 guard chain). An entry
  carries its sport, the OddsAPI event_id and the team names, but no player and
  no ESPN id.
- **Matching:** board rows join on normalised home/away team NAMES, and the
  OddsAPI `event_id` is not the ESPN id. Prop rows carry only `player_name`, so
  `GameExitStatus` carries `home_team` / `away_team` display names for the match.

## 5. Plan

1. Publish exits in each live producer's snapshot (`playersOut`) and refuse the
   game at the producer with `*ResimRefusal("key_player_out")`. One detector
   call per game per tick, on the summary the producer already holds.
2. Props join: refuse a `player_name` that the same snapshot lists as out.
3. Portfolio + in-play entries: refuse rows whose game (by names) has a key
   exit in the snapshot.
4. Fleet measurement per sport on a real mid-game exit: a served refusal within
   one tick, lifted on return, and 0 change to games with no exit.
