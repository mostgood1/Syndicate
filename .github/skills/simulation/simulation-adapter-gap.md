# Simulation Adapter Gaps

Problem:
Adapters are not converting all available data into simulation inputs.

Observed Gaps:

## MLB
- live lens not fully integrated
- segment outputs not part of simulation inputs
- evaluation results not reused

## NBA / WNBA
- live state partially used
- boxscore, player lens, and lines not consistently fed into simulation

## NHL
- mainly artifact-driven
- props and reconciliation data not feeding simulation

## NFL
- snapshot-based
- missing dynamic inputs like odds movement or state updates

## NCAAB / NCAAF
- minimal simulation usage
- mostly static recommendations

---

## Core Issue
Simulation engine is underfed, not underpowered
