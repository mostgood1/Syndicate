---
description: Build natural language query system
---

MISSION:
Allow users to ask questions about sports data and trends.

TASK:
Build a query handler that:
1. parses natural language input
2. identifies:
   - sport
   - market
   - timeframe
3. retrieves relevant artifacts
4. generates structured answer

OUTPUT FORMAT:
{
  summary: string,
  recommendations: [],
  reasoning: [],
  risk_signals: [],
  confidence: float
}

REQUIRE:
- modular architecture
- reusable retrieval functions
- cross-sport support

OUTPUT:
- code
- usage examples