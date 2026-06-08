---
description: Build or improve Syndicate intelligence layer
---

MISSION:
You are the core intelligence engine of Syndicate.

Your role is to turn sports data, predictions, and market data into intelligent answers.

INPUT:
- Current file: ${file}
- Relevant modules: ${selection}

TASK:
1. Analyze the current intelligence layer
2. Identify gaps in:
   - reasoning
   - explanation
   - confidence scoring
   - data usage
3. Build or refactor logic that:
   - answers natural language questions
   - consumes structured artifacts (predictions, edges, recommendations)
   - produces explainable outputs

REQUIREMENTS:
- Separate:
  - data retrieval
  - analysis logic
  - output formatting
- Output structured response:

{
  summary: string,
  key_factors: [],
  risks: [],
  confidence: float,
  supporting_data: []
}

CONSTRAINTS:
- Use local artifacts only
- Do not rely on source APIs
- Preserve compatibility with existing API outputs

OUTPUT:
1. code
2. architecture explanation
3. example usage queries
