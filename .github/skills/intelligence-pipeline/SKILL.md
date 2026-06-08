---
name: intelligence-pipeline
description: Use this when working with the intelligence system. Handles pipeline orchestration, ensuring intelligence.py is treated as a black box and all new work follows the pipeline architecture.
---

# System Overview

The system follows a pipeline architecture:

request → router → pipeline → intelligence.py → evidence → structured output → formatter

# Rules

1. intelligence.py is a black box
   - NEVER modify its internal logic
   - Only wrap or call it

2. All new logic must exist in pipeline modules:
   - pipeline/intelligence_pipeline.py
   - pipeline/evidence_builder.py
   - router/query_router.py
   - formatter.py

3. Maintain stage separation:
   - input normalization
   - enrichment
   - intelligence execution
   - post-processing
   - formatting

4. Outputs must be structured objects, not raw dicts

# Procedure

When modifying or extending the system:

1. Identify where the change belongs:
   - routing → router/
   - execution → pipeline/
   - output → formatter/

2. NEVER inject logic directly into intelligence.py

3. If new data is introduced:
   - pass through pipeline
   - update evidence_builder if needed

4. Validate:
   - pipeline still runs end-to-end
   - no breaking changes

# Anti-patterns

- Modifying intelligence.py logic
- Mixing formatting into analysis
- Returning unstructured dictionaries
``