---
name: intelligence-end-to-end
description: Use this when modifying the intelligence system that backs the live Render intelligence endpoint. Preserve the external endpoint contract rooted at the live intelligence URL while extending the internal pipeline safely.
---

# Purpose

This skill governs end-to-end changes to the intelligence system behind the live intelligence endpoint:

[Live intelligence endpoint](https://syndicate-an21.onrender.com/intelligence)

The external endpoint behavior is the contract to preserve unless the task explicitly asks to change it.

# System intent

The intelligence system should be evolved behind the endpoint through modular layers such as:
- request normalization
- routing
- pipeline orchestration
- intelligence engine invocation
- evidence extraction
- structured output mapping
- formatting / response assembly

# Core rules

1. Preserve the public behavior of the live intelligence endpoint unless the task explicitly requests a contract change.
2. Prefer adding or modifying logic in:
   - router
   - pipeline
   - evidence builder
   - structured output / formatter
3. Treat `intelligence.py` as a black box unless a targeted change to it is explicitly necessary.
4. Do not mix formatting with analysis logic.
5. Do not bypass structured output when returning endpoint responses.
6. Do not make unreviewed breaking changes to request or response shapes.
7. Any endpoint change must be grounded in repository code that Render will deploy.

# Required workflow

1. Inspect the current server-side endpoint that backs `/intelligence`.
2. Inspect `intelligence.py` and surrounding pipeline modules.
3. Identify whether the requested feature belongs in:
   - router
   - pipeline
   - evidence builder
   - structured output / formatter
4. Implement the smallest modular change possible.
5. Wire the change into the endpoint path without changing unrelated code.
6. Add or update tests for:
   - endpoint contract
   - pipeline logic
   - structured output
7. Summarize changed files and call out any contract impact explicitly.

# Endpoint contract policy

- The live endpoint is the public contract.
- Internal architecture may evolve.
- External request/response behavior should remain stable unless a contract change is explicitly requested.

# Files to inspect first

- the Flask route / blueprint file that serves `/intelligence`
- `intelligence.py`
- pipeline modules
- router modules
- response models / formatter
- tests covering intelligence behavior

# References

- ./references/live-endpoint-contract.md
- ./references/architecture.md
- ./references/render-runtime-notes.md

# Examples

- ./examples/request-example.json
- ./examples/response-example.json