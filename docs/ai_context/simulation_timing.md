# Simulation Timing

## Current Pattern
- many simulations are run in daily pipeline
- results stored as artifacts
- runtime often displays them

## Problem
- live data and late signals are not always recomputed
- simulation results can become stale

## Tradeoff
- precompute = fast, stable
- runtime sim = fresh, adaptive

## Key Question
Which parts of simulation should:
- run in GitHub Actions?
- run at request time?
``