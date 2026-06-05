---
name: syndicate-mlb-statcast-analyst
description: "Answer MLB matchup and prop questions with Syndicate Statcast artifacts. Use when the user asks about home run targets, strikeout matchups, total-bases upside, batter versus pitcher shape, pitch-mix context, or why an MLB recommendation grades well."
---

# Syndicate MLB Statcast Analyst

Use this skill for MLB questions that need more than generic board ranking.

## Best fits
- Home run targets and power matchup questions.
- Strikeout and pitch-mix matchup analysis.
- Batter-versus-pitcher shape using local Statcast feature artifacts.
- Top-target tables or chart-ready support for MLB props.

## Workflow
1. Start from the actionable board candidates or prop rows for the selected date.
2. Join Statcast artifacts with stable ids such as batter and pitcher ids whenever available.
3. Surface the specific supporting metrics that fit the market: barrel rate, EV, launch angle, HR/BIP, xwOBA, pitch mix, whiff shape, or in-play quality.
4. Keep the explanation tied to the actual market instead of dumping raw stats.
5. Return structured fields first, then concise rationale text.

## Deliverables
- Ranked MLB targets.
- Supporting Statcast metrics.
- A short why-explanation per target.
- Focused validation targets for the MLB intelligence slice.
