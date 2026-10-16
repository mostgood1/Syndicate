# How each sim handles a player OUT or limited — survey, 2026-10-16

User 2026-10-16: news "should also then potentially impact sims based on players taking on additional share of
minutes in game"; on being asked where to start, the answer was "Survey all first". READ-ONLY survey (no code
changed, no paid calls). Fleet reads were taken 2:20–2:35 PM CDT on main `8e025175`. Tags: **[measured]** on the
fleet, **[code]** read in the repo, everything else **UNVERIFIED**.

## Per sport

| Sport | Availability input | OUT removed? | Teammates absorb it? | Timing / example |
|---|---|---|---|---|
| NBA | `raw/injuries.csv` from the daily `fetch-injuries` snapshot (`basketball_props_smart_sim.py:4641-4840`), not the news collector. On 10-16 it equals ESPN's state: 130/130 rows, 24/24 OUT [measured] | Yes: OUT, DOUBTFUL, SUSPENDED and INACTIVE are dropped (`_drop_excluded`, smart_sim `:1312`). DTD keeps full weight | Pro-rata only: the rest are rescaled to 240 minutes (`_scale_minutes_to_target` `:704`, 44-min cap `:1041`). Each excluded player also takes 0.3 off pace and 0.5 off points, whoever he is (props_smart_sim `:1170`, `:896`) [code] | Lineup check runs every tick inside 30 min of tip (`live_refresh_loop.py:619`, `:905`); PHI_BOS re-simmed 2:04 PM, 3 min after the 2:01 PM injuries refresh [measured]. 17 of 17 OUT absent from the 10-16 sims (GSW without Butler, Moody, Porzingis); 78 of 88 DTD in the pools at full weight [measured] |
| WNBA | Same feed, plus `wnba_sim_availability` (missed-games rule) | Yes | Pro-rata; the explicit re-share was REFUTED (below) | Season over |
| NHL | **None.** The lineup comes from last-8-game TOI, "played last game" and book-listed skaters (`ingestion/collect.py:94-100`, `lineups.py:196-216`) | **No.** ESPN had Granlund (ANA) Out at 12:31 PM; `lineups_2026-10-16.csv` (2:06 PM) has him L1/PP1, 20.8 min, 5 prop lines [measured]. His ESPN note later says travelling, so he may play — the defect is that status is never read | Slot shift only; `proj_toi` is the player's own average | Scratches arrive about 1 h before puck drop and feed only the board flag |
| NFL | **None** in the prop model (rolling mean × game multiplier). `injury_adjustment.py` is team-level and OFF since `36cd8a5c` (accuracy 60.98% → 56.44%) | **No**: 11 of 120 OUT/IR players still have rows in the wk6 artifact (2:01 PM) [measured]; the board flags them | No | An injury change triggers an odds sweep, not a resim (`live_refresh_loop.py:5966`) |
| NCAAF | None (Anytime TD on rolling rates; ESPN's CFB injury feed is dead) | No | No | — |
| MLB | StatsAPI IL + the confirmed/projected nine (`build_roster.py:1696`, `:1778-1840`) | Yes (IL); DTD not handled | By construction: the replacement takes the slot | 10-min checks, 1 h minimum between fingerprint resims; no live example (postseason, lineup not posted) |
| Soccer | No injury feed; ESPN's confirmed XI arrives about 1 min before kickoff | Indirect: starters ≥ 0.75 share, bench 0.15, renormalised (`player_props.py:~620`) | Pro-rata; 7–10 of 11 starters recognised (n=4) | Rarely reaches the sim before kickoff |

## Model-engine standard

- **Consumed, not populated (NBA):** `league_status_<date>.csv` (one file on the fleet, dated 05-26); `exp_min_mean`,
  the heaviest minutes weight (0.58, smart_sim `:973`) — the NBA file has 6 starter-only columns.
- **Populated, consumed by no sim:** the collector's injuries for all five sports and the NHL scratches (they feed
  the board flag, cheat sheets and `news_price_follow` only); nflverse `injuries_2026.csv` (sweep trigger only).
- **Collector churn [measured]:** the collector re-keys ESPN athlete ids, so 37 of 82 NBA events on 10-16 are a
  same-run new + cleared pair for one name (Kennard 52 events; Sabally 36 on WNBA). `injury_events`
  (`news_price_follow.py:90`) does not dedupe. **The cheat-sheet page is NOT affected**: `align_news` (deployed
  `f81f1c2d`) nets each player's change across the window, so a same-run pair cancels — measured on the fleet's
  code over the NBA 10-16 sheet: 13 stored items (Moody and Butler among them) → 0 served. The stored file still
  holds them because it was built at 12:35 PM, before that deploy.

## Prior evidence: redistribution is unproven wherever it was tested

WNBA minutes re-share REFUTED (PRA Brier +0.0073 / +0.0088; bench-only variant inert — `findings_2026-10-04`,
`state_basketball.md`); perfect injury information barely moves props (points Brier −0.0020); NBA/WNBA minutes
trends already priced (findings 10-13, 10-14); NFL vacated targets not supported (residual −10.5% [−17.4, −3.4] —
the market over-reacts); soccer share redistribution overturned (learnings 10-06); NBA teammate effects retired 10-13.

## Gaps, ranked by expected impact

1. NHL never reads status.
2. NFL / NCAAF have no availability input — OUT players flagged but still projected.
3. NBA: DTD at full minutes; a blanket per-absence pace/points penalty; no confirmed-lineup feed; the minutes
   inputs above.
4. Soccer: no injury feed.
5. Collector churn corrupts any event-driven consumer.

## Candidate first fixes (not started)

- NHL: feed collector OUT/IR + `gameinfo` scratches (state, deduped by name+team) into lineup building before
  `infer_lines` (`syndicate/features/nhl/sim_engine/hockeysim/ingestion/collect.py`); oracle-style replay first.
- A state-based `out_names(sport, date)` seam in `syndicate/features/shared/news_availability.py` (lane
  `news-availability-gate` is open — coordinate).
- Dedupe by name+team in `injury_events` (`scripts/news_price_follow.py`; lane `news-price-follow` is open).

**Verdict:** removal correctness before redistribution, one change per deploy, measurement written first; any
redistribution mechanism needs a pre-registered before/after test, because every prior test was negative or null.
