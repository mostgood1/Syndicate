# Live-betting change register — what restarts the scale-up gate's clock (todo #815)

**Rule (user 2026-11-16, verbatim: "Any betting change").** The scale-up gate's count of independent events restarts
at every fleet load that changes which live bets are placed, how they are sized, or how they are held or exited.
Display-only, ledger-only and shadow-only changes do not restart it. That boundary is the lane's operational reading
of the user's choice (`findings_2026-11-16_live_book_edge_readout.md`, § "Scale-up gate").

**Tool:** `scripts/betting_change.py` — `clock`, `candidates`, `add`, `resolve`, `list`. Read by
`scripts/live_book_edge_readout.py`, which measures the gate over bets SUBMITTED after the clock start.

- **`loaded_at` is the LOAD, not the ff:** the instant the running role picked the change up, i.e. a TERM, a recycle,
  a drained down/up, or the next run of a fresh child. An ff-only deploy is `pending:<roles>` until that happens.
- **While any `yes` is pending, the count is 0.** `resolve` records the load. Failing closed is deliberate: an unknown
  load time must not let pre-change bets count toward the gate.
- **Coverage:** every deploys.md entry that loads code or env, from `Classified from:` on, gets a row here (`yes` or
  `no`) or a `- betting change: yes|no` line in its own body. A `yes` always needs a row here with its load time.
  `python scripts/betting_change.py candidates` lists what is missing and exits 1 while anything is.

Classified from: `2026-11-16T18:15:00Z`

Rows BC-001..BC-011 predate that instant. They are a PARTIAL backfill from deploys.md headings: the changes the lane
named on 11-16, plus the football player-exit gates. They never decide the clock. Before 18:15Z 11-16 the register
makes no completeness claim.

Load times derived from process ages (BC-013..BC-017, ±5 s): live-odds-worker pid 2834332 (first line 18:15:23Z) exited after
20,383 s and restarted in 5 s, so pid 2925378 started ~23:55:06Z; lane live-player-exit-gate's watcher pins it at 23:55:09Z
(deploys.md 2026-11-17 00:49Z), which BC-013..015 use. Refresh-worker
(booted 16:29:24Z) exited after 27,309 s, so pid 2953295 started ~00:04:38Z (etimes: 00:04:37Z). Both are ±5 s.

| id | kind | loaded_at (UTC) | what changed | deploys.md entry | lane |
|---|---|---|---|---|---|
| BC-001 | yes | 2026-11-04T00:46:25Z | NCAAB game lines traded on Kalshi (refresh-worker TERM) | 2026-11-04T01:01:00Z | ncaab-kalshi-pairing |
| BC-002 | yes | 2026-11-04T13:41:34Z | Women's college basketball game lines traded on Kalshi (refresh-worker TERM) | 2026-11-04T14:00:00Z | wncaab-kalshi-pairing |
| BC-003 | yes | 2026-11-07T22:25:00Z | In-game exits off (8b1dcd020), live-odds-worker; loaded by its own recycle at or before this entry | 2026-11-07T22:25:00Z | exit-state-size |
| BC-004 | yes | 2026-11-08T00:43:32Z | Live lane-age gate DEFAULT ON (#762): live rows on a stale re-sim lane refused (refresh-worker TERM) | 2026-11-08T00:43:32Z | live-gameline-lane-age-gate |
| BC-005 | yes | 2026-11-09T05:13:12Z | NCAAB live mechanisms env: blowout rule off + tip re-centre (#768), drained down/up | 2026-11-09T05:13:12Z | ncaab-blowout-off-load |
| BC-006 | yes | 2026-11-09T17:05:47Z | In-play entries refuse a decision ask below 0.55 (live-odds-worker TERM) | 2026-11-09T17:05:47Z | inplay-min-ask |
| BC-007 | yes | 2026-11-10T07:49:30Z | NCAAB live mechanisms env: score effect + re-centre 0.46 (RC46, #765), drained down/up | 2026-11-10T07:49:30Z | #765 phase 2 step 3h |
| BC-008 | yes | 2026-11-10T22:56:28Z | NCAAB RC46 reverted to #768's 7 fields, drained down/up (up 22:56:28Z) | 2026-11-10T22:55:46Z | #765 phase 2 step 3h |
| BC-009 | yes | 2026-11-15T18:25:41Z | NFL live player-exit gate + in-play entry holds (refresh-worker 18:24:27Z, live-odds-worker 18:25:41Z) | 2026-11-15T18:24:27Z | live-player-exit-gate |
| BC-010 | yes | 2026-11-16T01:28:28Z | NCAAF live player-exit gate + football replaced-QB rule (refresh-worker) | 2026-11-16T01:28:28Z | live-player-exit-gate |
| BC-011 | yes | 2026-11-16T01:44:49Z | NCAAF in-play entry holds (live-odds-worker routine recycle on db2af02ab) | 2026-11-16T01:44:49Z | live-player-exit-gate |
| BC-012 | yes | 2026-11-16T18:15:23Z | NBA live player-exit gate (live-odds-worker self-recycle, pid 2834332) | 2026-11-16T18:15:23Z | live-player-exit-gate |
| BC-013 | yes | 2026-11-16T23:55:09Z | NCAAB/WNCAAB live player-exit gate (ff 18:39:51Z; live-odds-worker recycle, pid 2925378) | 2026-11-16T18:39:51Z | live-player-exit-gate |
| BC-014 | yes | 2026-11-16T23:55:09Z | NHL live player-exit gate (ff 20:55:22Z; live-odds-worker recycle, pid 2925378) | 2026-11-16T20:55:22Z | live-player-exit-gate |
| BC-015 | yes | 2026-11-17T00:04:38Z | Soccer live player-exit gate: entry hold 23:55:09Z (live-odds-worker), board skip 00:04:38Z (refresh-worker pid 2953295) | 2026-11-16T21:17:00Z | live-player-exit-gate |
| BC-016 | yes | 2026-11-16T22:32:09Z | NFL game-line quotes filed by Central kickoff date (#817): MNF in-play rows reach the 11-16 overlay; fresh child of the next NFL lines run | 2026-11-16T22:31:26Z | nfl-gameline-kickoff-shard |
| BC-017 | yes | 2026-11-17T00:04:38Z | NCAAB per-line total calibration (#816): every live NCAAB total leans under (refresh-worker TERM, pid 2953295) | 2026-11-17T00:04:20Z | ncaab-total-overprojection |
| BC-018 | no | 2026-11-17T00:20:21Z | NFL shard log line allowlisted in the odds sweep (#817): no filing or behaviour change | 2026-11-17T00:20:21Z | nfl-gameline-kickoff-shard |
| BC-019 | no | 2026-11-17T00:49:00Z | READING of the 23:55:09Z live-odds-worker recycle that loaded BC-013..BC-015 (already counted); no new change | 2026-11-17T00:49:00Z | live-player-exit-gate |
| BC-020 | no | 2026-11-17T00:55:46Z | #816 display-path fix: the Live number on NCAAB rows refused BEFORE pricing is calibrated (display only; refresh-worker restart pid 3101432 loaded live_gameline_join.py only) | 2026-11-17T00:55:46Z | ncaab-total-overprojection |
| BC-021 | no | 2026-11-17T00:59:08Z | READING: the NFL filing log line is readable on the fleet (#817) | 2026-11-17T00:59:08Z | nfl-gameline-kickoff-shard |
| BC-022 | yes | 2026-11-17T15:47:46Z | NFL live re-sim on #808's profile (7 end-of-half/kickoff switches, hfb 0.03, TD 0.825) + #813 drive state + live timeouts; #814 live props join refuses players listed out (refresh-worker TERM, pid 4027303). #814's MLB entry hold reaches live-odds-worker at its next recycle; MLB out of season, no bet affected | 2026-11-17T15:25:08Z | nfl-profile-load |
