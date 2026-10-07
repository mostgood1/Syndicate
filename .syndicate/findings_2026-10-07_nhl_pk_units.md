# NHL hockeysim penalty-kill units -- lane `nhl-pk-units` (2026-10-07)

## Defect
Fixed PK1/PK2 units (`engine.py` `_pk_units`, PK1 preferred 0.60 + alternation) put PK1 skaters on ~0.88 of
team PK time; PK2 and everyone else far under real (engine measure, 386 games of 2025-26 vs NHL stats
`skater/timeonice` shTimeOnIce; shares normalised /5 both sides):

| group | production | pk_usage=minutes | real |
|---|---|---|---|
| PK1 D / F | 1.097 / 1.097 | 0.690 / 0.600 | 0.678 / 0.577 |
| PK2 D / F | 0.152 / 0.153 | 0.425 / 0.419 | 0.424 / 0.429 |
| no PK unit D / F | 0 / 0 | 0.134 / 0.059 | 0.153 / 0.064 |

Team goals/SOG/SH rates unchanged (1.081x -> 1.082x goals). H1 supported.

## Fix (on main, default off: 2790fdf7)
`SimConfig.pk_usage = "minutes"`: each PK segment draws 4 skaters by systematic PPS on `PlayerState.sh_toi_proj`
(SH minutes per game). `proj_sh_toi` is written by `lineups.project_lineup`; `loaders._proj_sh_toi` derives it as
proj_toi - proj_ev_toi - proj_pp_toi when a lineups file predates the column.

## Paired props backtest vs production (Brier d x1e3, game-clustered 95% CI)
Regular season (decides; 13,161 skater-games): BLOCKS@1.5 -2.85 [-3.70,-1.93] better; SOG@1.5 +0.32, @2.5 -0.46,
@3.5 -0.29; GOALS@0.5 -0.37; ASSISTS@0.5 -0.12; POINTS@0.5 -0.22, @1.5 -0.09; SAVES@22.5/25.5/28.5 +1.04/+0.84/+0.46
-- none significantly worse. Elite SOG@2.5 -3.47 better. Playoffs (2,769, reported): BLOCKS@1.5 -1.63 better;
POINTS@0.5 +1.53 [+0.07,+2.99] worse (no-PP-unit skaters), rest n.s.

## Leads
- Engine quirk: an away PP with no PP units listed falls to the EV branch (`elif seg_is_away_pp and pp_away`)
  while still labelling the home skaters PK; the home branch has no such condition. Production lineups always
  carry PP units.
