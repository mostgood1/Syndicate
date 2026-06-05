---
name: syndicate-intelligence-planner
description: "Plan and scope The Syndicate intelligence layer. Use when adding broad question-answering support, advanced-data access, sport-specific reasoning, ranking logic, charts/tables, or translating product asks into concrete files, tests, and validation commands."
---

# Syndicate Intelligence Planner

Use this skill when the request is about expanding what Syndicate intelligence can answer or how it should reason.

## Focus areas
- Broad question-answering coverage across MLB, NBA, WNBA, NHL, NCAAB, and related surfaces.
- Advanced-data integration such as Statcast, live-lens artifacts, processed mirrors, and feature payloads.
- Recommendation ranking, rationale construction, same-game or cross-sport logic, and render-ready analysis payloads.
- Converting product asks into concrete backend, API, UI, and test slices.

## Workflow
1. Identify the user question, sport, date, market, and whether the ask is pregame, live, ranking, explainer, table, or chart oriented.
2. Trace the current intelligence path first: parser, candidate collection, advanced enrichment, ranking, API response, then UI rendering.
3. Prefer stable ids and tracked artifacts over name matching or ad hoc scraping.
4. Keep changes local and testable: backend payload first, then rendering, then focused tests.
5. Validate with the narrowest intelligence test slice before widening scope.

## Deliverables
- Concrete file targets.
- A minimal implementation plan.
- Validation commands for the touched intelligence slice.
