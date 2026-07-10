# WNBA Unified Reasoning Layer

## Step 1: Reasoning Inventory

| Field | Source File(s) | Usage |
| --- | --- | --- |
| `summary` | `syndicate/features/wnba/cards.py`, `syndicate/static/wnba/cards-parity.js` | Default bettor-facing explanation text for prop rows and card rows.
| `basketball_summary` | `syndicate/features/wnba/cards.py`, `syndicate/static/wnba/cards-parity.js` | Primary human-readable explanation for official and live prop recommendations.
| `why_explain` | `syndicate/features/wnba/cards.py`, `syndicate/static/wnba/cards-parity.js` | Secondary explanation / fallback narrative used when a fuller summary is unavailable.
| `reasons` | `syndicate/static/wnba/cards-parity.js` | Supporting reason tags for live and official prop rows.
| `reason_summary` | `syndicate/features/intelligence.py`, `syndicate/features/intelligence_analysis_common.py` | Cross-sport reasoning summary field used in analysis / intelligence surfaces.
| `why` | `syndicate/features/intelligence.py` | Final recommendation explanation field in unified intelligence outputs.
| `shape_summary` | `syndicate/static/wnba/cards-parity.js`, `syndicate/features/intelligence.py` | Live-lens / shape-based explanation text.
| `detail` | `syndicate/features/intelligence.py`, `syndicate/static/wnba/cards-parity.js` | Compact explanation field that can carry source summary text.
| `writeup` | `syndicate/features/intelligence.py` | Source-summary style explanation for intelligence outputs.

## Step 2: Reasoning Normalization

Target schema:

```json
{
  "headline": "Model projects a 7.3-point edge.",
  "supporting_reasons": [
    "72% simulated win probability",
    "Expected value +4.8%",
    "Market line trails model projection"
  ],
  "model_support": {
    "projection": 7.3,
    "win_probability": 0.72,
    "edge_pct": 4.8
  },
  "market_support": {
    "line": -2.5,
    "odds": -110
  }
}
```

Mapping:

- `summary` -> transform into `headline` or `supporting_reasons` depending on whether it is concise or compound.
- `basketball_summary` -> direct map into `headline` when concise; otherwise transform into `supporting_reasons[0]`.
- `why_explain` -> direct map into `headline` when it is the clearest explanation; otherwise fallback/transform.
- `reasons` -> direct map into `supporting_reasons`.
- `reason_summary` -> direct map into `headline` when it is the clearest summary field.
- `shape_summary` -> transform into `model_support` or `supporting_reasons` for live-context explanation.
- `detail` -> transform into `supporting_reasons` when the text is explanatory rather than numeric.
- `writeup` -> transform into `headline` or `supporting_reasons` depending on context.

Classification:

- Direct map: already bettor-friendly and concise.
- Transform: needs normalization, dedupe, or split into headline + support.
- Deprecated: legacy text that should not be emitted directly when a normalized reasoning object exists.

## Step 3: Reasoning Style Guide

- Lead with one concise headline.
- Use a short supporting list for evidence, not a paragraph dump.
- Keep model support and market support separate.
- Avoid duplicate statements between headline and bullets.
- Prefer model-first language: projection, win probability, edge, and line context.
- Avoid jargon unless the surface is explicitly advanced-data oriented.

Preferred format:

- Headline: `Model projects a 7.3-point edge.`
- Supporting reasons: `72% simulated win probability`, `Expected value +4.8%`, `Market line trails model projection`

## Step 4: Surface Inventory

WNBA surfaces showing recommendation reasoning:

- Main board evidence pack on the primary WNBA cards surface.
- Prop lens on the WNBA cards surface.
- Prop strip / live prop cards on the WNBA cards surface.
- Prop buttons and prop lane cards inside the WNBA betting-card / props panels.
- Sidebar prop overview cards in the WNBA cards surface.
- Live segment and live opportunity tiles when live props are active.

## Implementation Note

The WNBA UI now normalizes row-level explanation data into a shared `why` / `confidence` path and reuses it across the prop strip, prop lens, prop buttons, and sidebar lane cards without changing SmartSim, recommendation generation, refresh contracts, manifests, or publication adapters.
