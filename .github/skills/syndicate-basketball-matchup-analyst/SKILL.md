---
name: syndicate-basketball-matchup-analyst
description: "Answer NBA, WNBA, and NCAAB matchup questions inside Syndicate. Use when the user asks for pace, usage, role, shot profile, matchup context, best props, same-game stacking logic, or why a basketball recommendation is strong or fragile."
---

# Syndicate Basketball Matchup Analyst

Use this skill for basketball questions across NBA, WNBA, and NCAAB when the answer should explain the shape of the play rather than only rank it.

## Best fits
- Best prop or game-bet questions for basketball slates.
- Pace, usage, minutes, role, and shot-profile explanations.
- Same-game clustering or correlation-aware basketball logic.
- Table or chart outputs summarizing top targets.

## Workflow
1. Identify league, date, market family, and whether the ask is pregame or live.
2. Start from the home rails or live-lens candidates already produced by Syndicate.
3. Pull the supporting matchup context that actually maps to the asked market: pace, role, usage, shot volume, assist environment, rebound environment, or team total shape.
4. Keep team and player context separate so the explanation stays readable.
5. Prefer concise structured support over long narrative.

## Deliverables
- Ranked basketball targets.
- Supporting context fields by market family.
- Same-game or cross-player caution notes when relevant.
