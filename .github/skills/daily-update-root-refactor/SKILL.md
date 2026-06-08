---
name: daily-update-root-refactor
description: >-
  Use for refactoring Syndicate's in-season daily update root into a self-contained,
  state-aware execution controller with run planning, run modes, run-state,
  stage decisions, and simulation-trigger scaffolding.
---

# Daily Update Root Refactor Skill

Use this skill when the user asks to improve or redesign the in-season daily update root.

## Objective
Evolve the root script from a schedule-aware launcher into a state-aware execution controller.

## Core principles
- The sim engine is foundational compute.
- Planning must happen before execution.
- State should drive execution more than date/calendar rules.
- Preserve current script compatibility when practical.
- Add focused tests only for touched slices.
- Prefer additive architecture scaffolding over broad rewrites.

## Required analysis sequence
1. Inspect current root responsibilities.
2. Identify downstream responsibilities delegated to the child script.
3. Add explicit run mode support.
4. Introduce a structured run plan.
5. Introduce persistent run-state.
6. Add per-stage execution decision scaffolding.
7. Add sim-trigger planning scaffold.
8. Add structured status output.

## Expected outputs
- new parameters
- run plan object/schema
- run-state schema
- stage decision contract
- status artifact schema
- focused test plan
``