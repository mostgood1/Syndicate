# hockeysim Phase 3b — projection profile calibration

Truth: 1312 games, season 20252026, 2025-10-07..2026-04-16 (source nhl_statsweb_landing).

**Accept score before:** 0.7271
**Accept score after:**  0.9890

## Before

| metric | target | measured | norm error |
|---|---|---|---|
| goals_per_game | 6.2538 | 6.1000 | 0.205 |
| home_goals_per_game | 3.1921 | 3.2025 | 0.021 |
| away_goals_per_game | 3.0617 | 2.8975 | 0.328 |
| period1_share | 0.2924 | 0.3100 | 0.440 |
| period2_share | 0.3478 | 0.3400 | 0.195 |
| period3_share | 0.3598 | 0.3500 | 0.245 |
| home_win_pct | 0.5221 | 0.5459 | 0.476 |

## After

| metric | target | measured | norm error |
|---|---|---|---|
| goals_per_game | 6.2538 | 6.2538 | 0.000 |
| home_goals_per_game | 3.1921 | 3.1923 | 0.000 |
| away_goals_per_game | 3.0617 | 3.0615 | 0.000 |
| period1_share | 0.2924 | 0.2924 | 0.000 |
| period2_share | 0.3478 | 0.3478 | 0.000 |
| period3_share | 0.3598 | 0.3598 | 0.000 |
| home_win_pct | 0.5221 | 0.5183 | 0.076 |

## Applied profile overrides

- `league_baseline_goals_per_60` = `3.1269`
- `league_xg_per_60` = `3.1269`
- `home_ice_attack_mult` = `1.0209`
- `away_ice_attack_mult` = `0.9791`
- `period_shares` = `(0.2924, 0.3478, 0.3598)`
