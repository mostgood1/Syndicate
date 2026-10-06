# Soccer O/U 2.5 loss to the close — reliability or resolution?

Lane `soccer-ou-loss-source` (session 43e4d5fe), 2026-10-05. Hypothesis and falsifiers were pre-registered in the lane
block (`a17f2ff3`) before any number below was computed.

## Data and coverage

| family | n | dates | source |
|---|---|---|---|
| 2025-26 harness dumps, all nine leagues: model + TRUE close + outcome | 2,724 | 2025-08-01..2026-05-24 | `C:/tmp/soccer-lpb/h2h_2526_all9.jsonl` (leak-free per-day as-of, 300 sims, post-`bc438e3e`) |
| 2026-27 harness, xG five (H-STALE arm A = production ratings) | 187 | 2026-08-15..2026-09-20 | `h2h27_A.jsonl` |
| 2026-27 SERVED pre-kickoff builds → outcome → TRUE close, nine leagues | 196 | 2026-08-07..2026-09-20 | audit cache (Render-era export; the fleet prunes past recommendation files) |

TRUE close = football-data `AvgC>2.5` / `AvgC<2.5`, de-vigged. Every row carries all three fields; no family is
narrower than its own count. Method: Murphy decomposition, 10 equal-count bins per arm, Brier ≈ REL − RES + UNC;
1,000-rep match bootstrap of model−close differences (bins recomputed per rep).

## Decomposition

| set | n | model Brier / REL / RES | close Brier / REL / RES | model−close Brier | REL diff | RES diff |
|---|---|---|---|---|---|---|
| **2025-26 all nine (PRIMARY)** | 2,724 | 0.2461 / 0.0023 / 0.0043 | 0.2416 / 0.0011 / 0.0075 | **+0.0045 [+0.0016, +0.0072]** | +0.0012 [−0.0008, +0.0037] | **−0.0032 [−0.0057, −0.0001]** |
| 2025-26 xG five | 1,391 | 0.2451 / 0.0040 / 0.0071 | 0.2415 / 0.0028 / 0.0091 | +0.0036 [−0.0004, +0.0076] | +0.0012 | −0.0020 [−0.0072, +0.0028] |
| 2025-26 goals four | 1,333 | 0.2471 / 0.0046 / 0.0051 | 0.2417 / 0.0013 / 0.0071 | +0.0054 [+0.0019, +0.0091] | +0.0033 [−0.0010, +0.0075] | −0.0020 [−0.0066, +0.0017] |
| 2026-27 harness xG five | 187 | 0.2314 / 0.0152 / 0.0233 | 0.2221 / 0.0167 / 0.0315 | +0.0093 [−0.0007, +0.0193] | −0.0015 | −0.0082 |
| 2026-27 served | 196 | 0.2425 / 0.0215 / 0.0191 | 0.2340 / 0.0130 / 0.0190 | +0.0085 [−0.0021, +0.0189] | +0.0085 | +0.0001 |

Primary share of the gap: **lost resolution 71%, reliability 26%** (binning residual 3%). The model's P(over 2.5) is
MORE spread than the close's (sd 0.098 vs 0.090) yet separates outcomes LESS (RES 0.0043 vs 0.0075): its spread
is partly noise.

## Recalibration, fitted on 2025-26, tested held out

Logistic on logit(p_model), n 2,724: **p' = sigmoid(+0.0375 + 0.6242 · logit p)** — slope 0.62, i.e. the model's
probabilities are too extreme for the information they carry.

| set | model−close raw | recalibrated | recal − raw |
|---|---|---|---|
| in-sample 2025-26 (n 2,724) | +0.0045 [+0.0018, +0.0072] | +0.0030 [+0.0007, +0.0054] | −0.0015 [−0.0028, −0.0002] |
| **HELD-OUT 2026-27 harness (n 187)** | +0.0093 [−0.0000, +0.0189] | **+0.0124 [+0.0033, +0.0218]** | +0.0031 [−0.0014, +0.0071] |
| **HELD-OUT 2026-27 served (n 196)** | +0.0085 [−0.0032, +0.0198] | +0.0073 [−0.0032, +0.0179] | −0.0012 [−0.0062, +0.0038] |

## Verdict against the pre-registration: SUPPORTED

- Falsifier 1 (resolution not below the close's): **does not fire** — RES −0.0032 [−0.0057, −0.0001], n 2,724.
  The CI's upper end is close to 0; neither subgroup separates on its own.
- Falsifier 2 (reliability ≥ half the gap): **does not fire** — 26% (primary). The goals-four subgroup reads 61%
  reliability (not deciding; its CIs span 0).
- Falsifier 3 (held-out recalibration closes the gap): **does not fire** — 2026-27 harness gets worse
  (+0.0093 → +0.0124), served moves −0.0012 with a CI spanning 0. In-sample it removes 0.0015 of 0.0045 — the
  reliability share — and that gain does not transfer.

**Reading.** Soccer's O/U 2.5 loss to the close is mostly information, not calibration: the book separates high- from
low-scoring matches better than the model, and no monotone remap of the model's probability recovers that. A
recalibration is not worth shipping (it fails held out). This agrees with the per-line weight fit (w = 0.000 for
totals, findings 2026-10-02) and with H-LEVEL (removing the goals-level bias left O/U 2.5 unchanged). What the
missing information IS (lineups/news timing, team-specific scoring tendencies, the ratings' spread — see lane
`soccer-team-strength`) is not measured here.

Reproduce: `py -3 C:/tmp/soccer-lpb/ou_decomp.py` (output `C:/tmp/soccer-lpb/ou_decomp.out`).
