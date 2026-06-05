---
name: syndicate-advanced-data-analyst
description: "Answer rich Syndicate sports questions using advanced data artifacts. Use when the user asks for matchup analysis, top targets, Statcast-backed explanations, supporting tables or charts, or sport-specific 'why' answers that should combine board candidates with local advanced-data files."
---

# Syndicate Advanced Data Analyst

Use this skill when the user wants more than a pick list and needs an evidence-backed answer.

## Best use cases
- Questions like `best home run matchups today and why`.
- Top-10 target tables or chart-ready grids.
- Explaining which advanced metrics are driving a recommendation.
- Deciding which local artifact should answer a question for a given sport.

## Workflow
1. Identify the sport, date, market, and expected output format.
2. Start from the board candidates or recommendation surface that already contains the actionable entities.
3. Join the advanced-data artifact using stable ids when available.
4. Surface the supporting metrics in a structured payload first, then in human-readable rationale.
5. Keep the output render-ready for both API and UI consumers.

## Output expectations
- Ranked targets.
- Supporting stat fields.
- Clear explanation of why each candidate rates well.
- Suggested focused validation for the touched analysis path.
