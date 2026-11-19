# Findings 2026-11-19 -- how fresh NHL odds are at puck drop (lane `nhl-puckdrop-odds-freshness`)

Read-only. The hypothesis was written into the lane (`4ee543dcd`) before any per-game measurement.
The user asked for this study ("Yes, study it") after the 11-18 live-window reading.

## Verdicts

- **H1 FALSIFIED.** The prediction was that the first in-game NHL odds refresh usually lands more than 10 min after puck drop, mostly because the loop keeps NHL on its pregame cadence.
  - Measured: **median 194 s** (p75 303 s, max 851 s) over **43 games**, 8 nights.
  - 4 of 43 games waited over 600 s; 0 waited over 900 s.
  - The falsifier was a median of 5 min or less. 194 s is 3.2 min.
  - **The mechanism was wrong too.** Across the 14 games with logs, the loop skipped NHL by cadence after a drop **0 times**, and launched **0 sweeps that left NHL out**.
  - The live checker marks NHL live within seconds of the drop. 11-18: ESPN shows the BOS @ DET drop at 00:38:54Z; the loop's `SLATE_PHASE sport=nhl ... to=live` line is at 00:38:59Z.
- **H2 SUPPORTED, n = 3.** The prediction was that after a refused NHL sweep, most of the lost time is the loop not retrying once the lane frees.
  - Only 3 of 14 logged games saw a refused NHL sweep.
  - Idle time after the lane freed, against time the lane was held:

    | night | game | idle after lane free | lane held |
    |---|---|---|---|
    | 11-16 | MTL @ NYR | 391 s | 92 s |
    | 11-18 | BOS @ DET | 279 s | 250 s |
    | 11-17 | CGY @ SJ | 111 s | 389 s |

  - 2 of 3 retries came more than 2 min after the lane freed. The refusal games are 3 of the 4 worst waits that have logs: 845 s, 604 s and 555 s.

## What the wait is made of

14 games with logs (nights 11-15..11-18), summing to 3,805 s:

| part | seconds | share |
|---|---|---|
| until the loop's first launch attempt naming NHL ("not_due") | 1,384 | 36% |
| run itself, launch to NHL odds step end | 908 | 24% |
| lane free, no attempt ("idle") | 781 | 21% |
| lane held by another live run ("held") | 731 | 19% |

- Per drop slot (9 slots, the first game per 30 min), "not_due" is 53%.
- **"not_due" is NOT NHL being left out of sweeps.** No sweep left NHL out, so this is the gap until the live loop's next launch attempt.
  - Launch-attempt gaps 00-05Z, any sport, every logged night: n 479, p50 93 s, p90 299 s, max 657 s.
- So **the loop's attempt cadence ("not_due" + "idle") is 57% of the per-game wait and 70% per slot.**
  - The run is ~1 min: NHL's fast odds step after the 11-18 split, and ~105 s on 11-17 behind other sports.
  - Lane holds matter only in the refusal games.

## Correction to the 11-18 live-window reading (deploys.md 2026-11-19 05:05Z)

That reading measured from the SCHEDULED 6:30 PM start and from the first live-phase NHL run (00:20:55Z, the T-10 sweep). It said the one odds-age miss (1,604 s, 00:22:15Z -> 00:48:59Z) was "NHL not in the sweep set". But:

- The first NHL puck drop was **00:38:54Z (6:38:54 PM CST)**. ESPN state flip in the in-play recorder, NHL polls ~61 s apart, so the drop happened no more than about 61 s before that time.
- NHL was correctly on its pregame cadence until then. 999 s of the 1,604 s gap came before any NHL game had started.
- The in-game part was **605 s** (BOS @ DET):

  | piece | seconds |
  |---|---|
  | drop to the first NHL-naming attempt | 14 |
  | refused, lane held by the 337 s soccer + NBA live run | 250 |
  | idle until the next attempt (00:43:19Z -> 00:47:57Z) | 279 |
  | run | 61 |

- Measured from the actual first drop, **0 of the window's NHL odds gaps was over 1,200 s**, so the odds-age prediction is MET.

## Coverage (per family; dates the result rests on)

- **Puck drops:** the in-play recorder's ESPN polls (`C:/tmp/inplay_<D>/espn.jsonl`).
  - Nights: 11-10, 11-11, 11-13, 11-14, 11-15, 11-16, 11-17, 11-18.
  - 11-12 was not recorded.
  - On 11-17 the recorder started after the 6:00 / 6:30 PM drops, so 7 of 11 games are censored.
  - 43 games have a seen drop.
- **Odds refreshes:** fleet manifests (`odds_refresh.json` step times). 16,794 runs, slate dates 11-10..11-20, 1,486 NHL odds steps.
- **Loop events:** live-odds-worker logs, 11-15 08:30Z..now.
  - The parts above rest on 4 nights (11-15..11-18): 14 games in 9 drop slots.
  - 11-10..11-14 have the wait only.
- **The 11-17 night** (slow NHL API, before the deadline fix) is included. Its 4-refusal game is the "held" outlier.

## Levers (none built; each would be a betting change: default-off, or the 11-24 window, put to the user)

1. **Faster launch attempts while a sport has a live game.** This is the largest part (attempt gaps p50 93 s, p90 299 s). The cause of the 5-10 min tick spacing is NOT yet read from code. That is the next read before any build.
2. **Retry a refused sweep when the holder exits.** It acts only in refusal games (3 of 14), which hold the tail: 391 s, 279 s and 111 s idle.

## Per-game table (scratchpad `puckdrop.py`, run 2026-11-19 ~14:05Z)

```
COVERAGE
  recorder 2026-11-10: 7 NHL games, 7 drops seen, NHL poll gap p50 61s
  recorder 2026-11-11: 6 NHL games, 6 drops seen, NHL poll gap p50 62s
  recorder 2026-11-13: 2 NHL games, 2 drops seen, NHL poll gap p50 61s
  recorder 2026-11-14: 14 NHL games, 14 drops seen, NHL poll gap p50 61s
  recorder 2026-11-15: 5 NHL games, 5 drops seen, NHL poll gap p50 61s
  recorder 2026-11-16: 2 NHL games, 2 drops seen, NHL poll gap p50 61s
  recorder 2026-11-17: 11 NHL games, 4 drops seen, NHL poll gap p50 61s
  recorder 2026-11-18: 3 NHL games, 3 drops seen, NHL poll gap p50 61s
  manifests: 16794 runs with steps, dates 2026-11-10..2026-11-20; NHL odds steps 1486
  live-odds-worker.log: 11-19 05:16Z..11-19 13:50Z
  live-odds-worker.log.1: 11-18 11:19Z..11-19 05:15Z
  live-odds-worker.log.2: 11-17 17:56Z..11-18 11:18Z
  live-odds-worker.log.3: 11-16 23:38Z..11-17 17:55Z
  live-odds-worker.log.4: 11-16 05:10Z..11-16 23:37Z
  live-odds-worker.log.5: 11-15 08:30Z..11-16 05:09Z

night      game          sched(CT) drop(CT) res  age@drop | first in-game refresh: start(CT) end(CT) wait | not_due held idle run | notes
2026-11-10 WSH @ OTT     18:00:00 18:07:08  63    1220 | 18:09:21 18:10:17   189 |    (no logs)        | run 20261111_000920 live
2026-11-10 COL @ TOR     18:00:00 18:10:21  61       4 | 18:13:18 18:15:09   288 |    (no logs)        | run 20261111_001317 live
2026-11-10 NJ @ WPG      18:00:00 18:10:21  61       4 | 18:13:18 18:15:09   288 |    (no logs)        | run 20261111_001317 live
2026-11-10 MIN @ MTL     18:00:00 18:20:41  63     332 | 18:26:41 18:29:10   509 |    (no logs)        | run 20261111_002354 live
2026-11-10 FLA @ CBJ     18:30:00 18:36:54  62     129 | 18:38:14 18:39:23   149 |    (no logs)        | run 20261111_003813 live
2026-11-10 DET @ STL     19:00:00 19:09:45  62     203 | 19:10:01 19:10:47    61 |    (no logs)        | run 20261111_010957 live
2026-11-10 NSH @ LA      21:00:00 21:08:42  58     217 | 21:11:03 21:15:49   427 |    (no logs)        | run 20261111_031058 live
2026-11-11 TB @ BUF      18:00:00 18:04:49  64     291 | 18:07:13 18:08:03   194 |    (no logs)        | run 20261112_000711 live
2026-11-11 NYR @ CGY     18:30:00 18:49:03  64      59 | 18:49:23 18:50:12    69 |    (no logs)        | run 20261112_004831 live
2026-11-11 PHI @ EDM     20:00:00 20:12:11  65     498 | 20:17:03 20:17:49   338 |    (no logs)        | run 20261112_021657 live
2026-11-11 UTA @ VGK     20:30:00 20:46:54  61      13 | 20:51:12 20:52:00   305 |    (no logs)        | run 20261112_025102 live
2026-11-11 NSH @ ANA     21:00:00 21:06:54  63      72 | 21:07:33 21:08:21    86 |    (no logs)        | run 20261112_030727 live
2026-11-11 PIT @ SJ      21:00:00 21:07:57  63      51 | 21:12:06 21:22:08   851 |    (no logs)        | run 20261112_031200 live
2026-11-13 NYR @ VAN     20:00:00 20:09:52  65     741 | 20:13:16 20:14:04   251 |    (no logs)        | run 20261114_021311 live
2026-11-13 NSH @ VGK     21:00:00 21:06:47  57      50 | 21:10:07 21:10:57   250 |    (no logs)        | run 20261114_031001 live
2026-11-14 SEA @ CAR     12:00:00 12:09:02  61    2198 | 12:12:11 12:13:11   248 |    (no logs)        | run 20261114_181210 live
2026-11-14 WPG @ CHI     14:30:00 14:36:20  70     314 | 14:45:27 14:46:31   611 |    (no logs)        | run 20261114_204522 live
2026-11-14 MIN @ BOS     18:00:00 18:07:19  70     515 | 18:07:27 18:08:20    61 |    (no logs)        | run 20261115_000726 live
2026-11-14 PHI @ CBJ     18:00:00 18:07:19  70     515 | 18:07:27 18:08:20    61 |    (no logs)        | run 20261115_000726 live
2026-11-14 NJ @ WSH      18:00:00 18:08:27  68       8 | 18:10:46 18:11:36   188 |    (no logs)        | run 20261115_001045 live
2026-11-14 FLA @ STL     18:00:00 18:08:27  68       8 | 18:10:46 18:11:36   188 |    (no logs)        | run 20261115_001045 live
2026-11-14 DET @ TB      18:00:00 18:09:28  60      68 | 18:10:46 18:11:36   128 |    (no logs)        | run 20261115_001045 live
2026-11-14 EDM @ TOR     18:00:00 18:17:00  71     246 | 18:20:17 18:21:09   248 |    (no logs)        | run 20261115_001921 live
2026-11-14 COL @ MTL     18:00:00 18:18:10  70      33 | 18:20:17 18:21:09   179 |    (no logs)        | run 20261115_001921 live
2026-11-14 OTT @ PIT     18:00:00 18:21:48  90      39 | 18:22:56 18:23:46   118 |    (no logs)        | run 20261115_002253 live
2026-11-14 BUF @ DAL     19:00:00 19:07:05  64     570 | 19:15:45 19:16:35   570 |    (no logs)        | run 20261115_011540 live
2026-11-14 SJ @ UTA      20:00:00 20:06:49  65     116 | 20:07:03 20:07:51    62 |    (no logs)        | run 20261115_020659 live
2026-11-14 NYI @ ANA     21:00:00 21:07:44  65     416 | 21:16:24 21:17:09   564 |    (no logs)        | run 20261115_031620 live
2026-11-14 CGY @ LA      21:00:00 21:19:31  60      14 | 21:21:50 21:22:33   181 |    (no logs)        | run 20261115_032146 live
2026-11-15 EDM @ PHI     18:30:00 18:40:34  61    1245 | 18:41:35 18:42:21   106 |      54    0    0  52 | run 20261116_004129 live; 0 sweeps w/o NHL, 0 nhl cadence-skips, 1 ticks, 0 NHL refusals; slate_phase live 18:41:20
2026-11-15 CGY @ ANA     19:00:00 19:04:53  60      62 | 19:05:48 19:06:36   103 |      49    0    0  54 | run 20261116_010542 live; 0 sweeps w/o NHL, 0 nhl cadence-skips, 0 ticks, 0 NHL refusals; slate_phase live 18:50:26
2026-11-15 FLA @ DAL     19:00:00 19:08:58  63     142 | 19:09:35 19:10:20    82 |      31    0    0  52 | run 20261116_010928 live; 0 sweeps w/o NHL, 0 nhl cadence-skips, 1 ticks, 0 NHL refusals; slate_phase live 18:50:26
2026-11-15 VAN @ VGK     20:00:00 20:05:22  60      77 | 20:06:03 20:06:50    88 |      33    0    0  55 | run 20261116_020555 live; 0 sweeps w/o NHL, 0 nhl cadence-skips, 1 ticks, 0 NHL refusals; slate_phase live 19:45:25
2026-11-15 NSH @ SJ      20:00:00 20:10:25  59      51 | 20:13:31 20:14:20   235 |     178    0    0  57 | run 20261116_021323 live; 0 sweeps w/o NHL, 0 nhl cadence-skips, 1 ticks, 0 NHL refusals; slate_phase live 18:51:22
2026-11-16 MTL @ NYR     18:30:00 18:47:34  57    2008 | 19:00:34 19:01:40   845 |     267   92  391  95 | run 20261117_010005 live; 0 sweeps w/o NHL, 0 nhl cadence-skips, 1 ticks, 1 NHL refusals; slate_phase live 18:51:22
2026-11-16 VAN @ UTA     20:30:00 20:35:10  61      20 | 20:36:48 20:37:32   141 |      92    0    0  50 | run 20261117_023642 live; 0 sweeps w/o NHL, 0 nhl cadence-skips, 1 ticks, 0 NHL refusals; slate_phase live 18:08:29
2026-11-17 ANA @ STL     19:00:00 19:08:27 153      58 | 19:10:05 19:11:34   187 |      82    0    0 105 | run 20261118_010949 live; 0 sweeps w/o NHL, 0 nhl cadence-skips, 0 ticks, 0 NHL refusals; slate_phase live 23:06:40
2026-11-17 NSH @ MIN     19:00:00 19:09:31  58     122 | 19:10:05 19:11:34   123 |      18    0    0 105 | run 20261118_010949 live; 0 sweeps w/o NHL, 0 nhl cadence-skips, 0 ticks, 0 NHL refusals; slate_phase live 23:06:40
2026-11-17 CGY @ SJ      21:00:00 21:08:07  47    6746 | 21:16:36 21:17:22   555 |       0  389  111  54 | run 20261118_031628 live; 0 sweeps w/o NHL, 0 nhl cadence-skips, 0 ticks, 4 NHL refusals; slate_phase live 23:06:40
2026-11-17 DAL @ VGK     21:00:00 21:17:15  61     189 | 21:21:31 21:22:16   301 |     251    0    0  50 | run 20261118_032126 live; 0 sweeps w/o NHL, 0 nhl cadence-skips, 1 ticks, 0 NHL refusals; slate_phase live 23:06:40
2026-11-17 LA @ BOS      18:00:00 CENSORED (recorder started after the drop)
2026-11-17 EDM @ FLA     18:00:00 CENSORED (recorder started after the drop)
2026-11-17 CBJ @ NYI     18:00:00 CENSORED (recorder started after the drop)
2026-11-17 BUF @ PHI     18:00:00 CENSORED (recorder started after the drop)
2026-11-17 OTT @ WPG     18:00:00 CENSORED (recorder started after the drop)
2026-11-17 WSH @ TB      18:30:00 CENSORED (recorder started after the drop)
2026-11-17 TOR @ CHI     18:30:00 CENSORED (recorder started after the drop)
2026-11-18 BOS @ DET     18:30:00 18:38:54  63    1000 | 18:48:09 18:48:59   604 |      14  250  279  61 | run 20261119_004758 live; 0 sweeps w/o NHL, 0 nhl cadence-skips, 0 ticks, 1 NHL refusals; slate_phase live 18:38:59
2026-11-18 MTL @ NJ      18:30:00 18:45:39  66    1405 | 18:48:09 18:48:59   199 |     138    0    0  61 | run 20261119_004758 live; 0 sweeps w/o NHL, 0 nhl cadence-skips, 1 ticks, 0 NHL refusals; slate_phase live 18:38:59
2026-11-18 COL @ UTA     21:00:00 21:17:48  63     172 | 21:20:53 21:21:41   233 |     176    0    0  57 | run 20261119_032044 live; 0 sweeps w/o NHL, 0 nhl cadence-skips, 1 ticks, 0 NHL refusals

GAMES with a seen drop and an in-game refresh: 43; wait p50 194s p75 303s max 851s; over 600 s 4, over 900 s 0
DROP SLOTS (first game per 30-min slot): 26; wait p50 213s max 845s
PARTS over 14 games with logs (sum 3805s): nd 1384s (36%), held 731s (19%), idle 781s (21%), run 908s (24%)
  nd: p50 68s max 267s; dominant in 6 games
  held: p50 0s max 389s; dominant in 1 games
  idle: p50 0s max 391s; dominant in 2 games
  run: p50 56s max 105s; dominant in 5 games
PARTS over 9 drop slots with logs (sum 2268s): nd 1206s (53%), held 92s (4%), idle 391s (17%), run 579s (26%)
LAUNCH-ATTEMPT GAPS 00-05Z (any sport, all logged nights): n 479 p50 93s p90 299s max 657s
```
