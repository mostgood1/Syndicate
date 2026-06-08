---
name: evidence-builder
description: Extract and normalize structured evidence from intelligence outputs.
---

# Goal

Transform intelligence output into structured, normalized evidence.

# Evidence Format

Each evidence item must include:
- source_type
- entity (team/player/etc)
- metric
- value
- timestamp

# Rules

1. Evidence must be domain-agnostic
2. Do NOT hardcode specific sports or schemas
3. Always normalize output format
4. Evidence must be consistent across all queries

# Procedure

1. Inspect intelligence output
2. Extract relevant signals
3. Normalize fields
4. Return list of evidence objects

# Constraints

- Do not modify upstream intelligence logic
- Do not include formatting logic

# Output Example

[
  {
    "source_type": "trend",
    "entity": "team_x",
    "metric": "pace",
    "value": 102,
    "timestamp": "..."
  }
]
``