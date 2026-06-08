---
name: structured-output
description: Convert raw intelligence output into typed structured objects.
---

# Goal

Ensure all outputs are strongly typed and consistent.

# Required Models

- IntelligenceResult
- Insight
- Evidence

# Rules

1. No raw dict outputs allowed downstream
2. All responses must validate schema
3. Preserve all data from intelligence layer

# Procedure

1. Analyze raw output
2. Map fields into dataclasses
3. Validate required fields
4. Return structured result

# Anti-patterns

- Passing raw JSON to formatter
- Missing required fields