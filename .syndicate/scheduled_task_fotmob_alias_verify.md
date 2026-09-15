# Scheduled tasks -- `fotmob-alias-verify-0919-am` and `fotmob-alias-verify-0919-pm`

**One-time, Saturday 2026-09-19: 08:50 CT (13:50Z) and 14:05 CT (19:05Z).** Local
Claude desktop scheduled tasks. Prompts are at
`C:\Users\tempadmin\.claude\scheduled-tasks\<taskId>\SKILL.md`. They run only while
the app is open. If the machine is asleep they fire on next launch, which can be
AFTER the matches end, and the run then records NOT READ. Dispatch is not
execution: a prior scheduled Bash call stalled 9h13m under Modern Standby, so
check the `deploys.md` entry, not `lastRunAt`.

## What they verify

Lane `fotmob-team-name-aliases`, commit `867f1481`: the LOOSE team-name pass in
`resolve_fotmob_match_id`. It has been live on live-odds-worker since 2026-09-15
19:37:29Z, confirmed by content (resolver blob `7bb75289` in `f833f7ec`, `18be9107`
and `991a94d5`). No match that only the new code resolves has been read in play yet.

## Targets (ids from `867f1481`'s resolver on FotMob's 09-19 listing, read 2026-09-15 19:30:51Z; `c725cc29` returned None for each)

| run | league | ESPN fixture | kickoff | expected id |
|---|---|---|---|---|
| am | bundesliga | Hamburg SV v FC Cologne | 13:30Z | 5881174 |
| (either) | belgian_pro_league | Royal Charleroi SC v Cercle Brugge KSV | 16:15Z | 5811766 |
| pm | belgian_pro_league | Anderlecht v Zulte-Waregem | 18:45Z | 5811767 |
| pm | ligue_1 | Lyon v Stade Rennais | 18:45Z | 5802940 |
| (later) | mls | San Jose Earthquakes v LAFC | 23:30Z | 5071370 |

## Reading and verdict

- Step 0: the live commit (Render deploys API) must still contain `_loose_match_ids`. If it does not, the fix was rolled back: record and stop.
- ESPN scoreboard state per target, then production `soccer_source/<league>/api/live_state/live_state_2026-09-19.json` via `/api/ops/artifacts/export` (`X-Admin-Token`).
- **MET:** the target is `in`, present in `games` of a file generated after kickoff, with `momentum.supported True`, `source fotmob` and the expected `fotmob_match_id`. One MET closes the lane.
- **NOT MET:** in play and present, but unsupported or a wrong id. Take one control read at least 2 min later before concluding. No code change, no deploy.
- **NOT READ:** nothing in play or present. Not a failure.
- Each run appends one READING entry to `deploys.md` from a lane worktree. On MET it closes the lane in place (in both the primary and worktree `lanes.md`) and adds one sentence to `state_soccer.md` `[soccer-live-momentum]`. The pm run checks whether the am run already closed the lane, and does not reopen it.

## Permissions

The runs use Bash/PowerShell, git, and HTTPS to ESPN, FotMob, Render and the web service. If a run pauses on a permission prompt with nobody at the machine, it records nothing. Evidence of a run is its `deploys.md` entry.
