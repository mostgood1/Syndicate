# Live Intelligence Endpoint Contract

Canonical public surface:
[Live intelligence endpoint](https://syndicate-an21.onrender.com/intelligence)

## Rule
The public behavior of this endpoint is the contract to preserve unless the task explicitly requires a contract change.

## Required review step
Before changing endpoint-facing code:
1. Inspect the current server-side implementation that backs `/intelligence`
2. Identify current request shape
3. Identify current response shape
4. Preserve those shapes unless explicitly instructed otherwise

## Change policy
- Internal refactors are encouraged
- Public contract drift is not allowed unless explicitly requested
