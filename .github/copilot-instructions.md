# Syndicate Copilot Instructions

## Project Overview
Syndicate is a multi-sport analytics and simulation platform with:
- Local artifact mirrors per sport
- Sim-engine outputs (predictions, edges, recommendations)
- Live-lens and snapshot systems
- A unified intelligence layer ("The Syndicate")
- Evaluation, experimentation, and adaptive recommendation logic

Syndicate is not just a UI over sports data.
It is evolving into a self-contained, world-class:
1. data analytics platform
2. simulation platform
3. intelligence system
4. evaluation and experimentation system

---

## Architectural Direction

### Core Platform Direction
- All sports must conform to a shared artifact manifest
- The sim engine is foundational compute, not just a downstream step
- Prefer state-driven execution over purely time-driven execution
- Prefer self-contained Syndicate-owned contracts over source-app fallbacks
- Every recommendation or intelligence output must be traceable to source artifacts, sim inputs, and evaluation history

### Intelligence Direction
The intelligence layer must:
- Answer questions using evidence, not raw outputs
- Track recommendations, performance, and drift
- Be model-aware, data-aware, and reliability-aware
- Incorporate evaluation feedback into confidence and recommendation behavior

### Daily Update Root Direction
The root daily update system is evolving from a time-driven wrapper into a state-aware execution controller.

The daily update root should ultimately own:
1. planning
2. run mode selection
3. run-state / checkpoint handling
4. execution coordination
5. stage status / observability

The root should distinguish between:
- source refresh required
- sim execution required
- artifact rebuild required
- manifest rebuild required
- intelligence / evaluation rebuild required

---

## Core Layers
1. Artifact Layer (data ingestion, storage, manifest)
2. Sim Engine (prediction, edges, recommendations)
3. Intelligence Layer (query, reasoning, structured responses)
4. Evaluation Layer (accuracy, scoring, calibration, CLV, ROI)
5. Experimentation Layer (policy comparison, selection, promotion)
6. Optimization Layer (future phase: policy tuning, context-awareness, regime detection)

---

## Coding Principles
- Prefer explicit data contracts over ad-hoc dicts
- Prefer modular architecture (services, builders, planners, state handlers)
- Prefer additive refactors over broad rewrites
- Keep orchestration logic separate from domain logic
- Avoid source-app fallback dependencies whenever possible
- Build for evaluation, auditability, and replay safety
- Preserve public API contracts unless explicitly asked to change them

---

## Daily Pipeline / Simulation Principles
- Treat simulation as foundational compute
- Prefer state-driven sim execution over time-driven "run everything daily"
- Prefer incremental work over full recomputation when safe
- Add explicit run modes where appropriate (for example: full, incremental, sim_only, manifest_only, evaluation_only, backfill)
- Add persistent run-state/checkpoint handling before advanced orchestration
- The daily root should plan first, then execute
- The root should become stage-aware before replacing downstream scripts
- Existing script entrypoints should be preserved as compatibility shims when practical

---

## Expectations for Copilot
When implementing new features or refactors:
- Propose the schema / contract first
- Identify the correct layer(s) affected
- Preserve compatibility unless explicitly asked to break it
- Prefer the smallest safe architectural slice first
- Include focused tests when generating or modifying logic
- When working on the daily update root:
  - build a structured run plan before execution
  - distinguish refresh vs sim vs artifact vs manifest vs evaluation work
  - introduce state-awareness before major orchestration changes

---

## Testing Expectations
Every meaningful change should include tests appropriate to the slice.

Prefer targeted regression coverage for:
- first / full run
- incremental run
- no-op run
- failed partial run / replay
- manifest compatibility
- intelligence contract compatibility
- evaluation persistence / scoring
- recommendation policy behavior

---

## Near-Term Roadmap Awareness
Syndicate currently considers the intelligence/evaluation/experimentation system as "Phase 1 complete."

Current and upcoming work should align with:
- root daily update redesign
- simulation-trigger decision logic
- state-aware execution planning
- policy optimization
- context-aware policy selection
- regime detection
- later simulation pipeline optimization