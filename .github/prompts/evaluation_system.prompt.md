---
description: Build evaluation and accuracy tracking system
---

MISSION:
Track performance of predictions and recommendations.

TASK:
Design a full evaluation system.

REQUIRE:
1. Define tracking schema:
   - prediction_id
   - recommendation_id
   - result
   - pnl
   - closing_line
   - implied_probability

2. Build functions:
   - record_prediction()
   - record_recommendation()
   - settle_result()
   - compute_metrics()

3. Metrics required:
   - win rate
   - ROI
   - closing line value (CLV)
   - calibration

OUTPUT:
- schema
- code
- sample metrics outputs