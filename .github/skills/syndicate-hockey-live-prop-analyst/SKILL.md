---
name: syndicate-hockey-live-prop-analyst
description: "Answer NHL live and pregame prop questions inside Syndicate. Use when the user asks about shots, goals, assists, live-state shifts, goalie or scoring context, or why an NHL live-lens or prop recommendation changed."
---

# Syndicate Hockey Live Prop Analyst

Use this skill for NHL questions where state, pace, or shots/goals context matters.

## Best fits
- Live shots, goals, and assist questions.
- Explaining why a live recommendation moved.
- Comparing pregame versus live hockey edges.
- Building ranked NHL prop summaries with supporting context.

## Workflow
1. Identify whether the ask is live or pregame.
2. Start from the actual NHL candidate or live-lens row in Syndicate, and reproduce the state in a local Render-emulated environment when runtime behavior or freshness could explain the change.
3. Use the game-state context that matters to hockey props: score state, shot volume, power-play environment, goalie context, and recent event flow when available.
4. Preserve live-state freshness and avoid mixing final-state rows into active recommendations.
5. Return a short rationale plus structured support fields.

## Deliverables
- Ranked NHL targets.
- Live-state support or caveats.
- Clear distinction between pregame and in-game reasoning.
