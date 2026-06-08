---
name: extend-intelligence-feature
description: Use this when adding new capabilities to the intelligence system. Ensures all changes follow pipeline architecture.
---

# Goal

Add new functionality without breaking system architecture.

# Rules

1. NEVER modify intelligence.py directly unless absolutely necessary
2. Add new logic in:
   - pipeline layer
   - evidence builder
   - router

3. Maintain separation:
   - analysis vs formatting
   - pipeline vs routing

# Procedure

1. Identify feature goal
2. Decide placement:
   - new query type → router
   - new computation → pipeline
   - new data structure → structured-output
3. Implement in smallest modular unit
4. Wire into pipeline

# Validation

- No duplication
- No breaking changes
- Pipeline remains intact
``