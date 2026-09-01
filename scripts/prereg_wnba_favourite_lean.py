"""PRE-REGISTERED test: does the WNBA prop book beat the price on the FAVOURITE side?

**Written 2026-09-01, BEFORE the data it will be read on exists.** WNBA has no
games between 2026-08-31 and 2026-09-16; the test window is the 30-game sprint
2026-09-17..2026-09-25. Committing the test first is the point: T2-1's
exploratory pass took roughly **30 looks** at 656 rows, and a +1.5 SE result is
the expected maximum from 30 draws of noise. Nothing found that way can be
believed without an out-of-sample confirmation that was specified in advance.

WHAT IS BEING TESTED, and it is ONE thing:

    Among clean-root, priced, graded WNBA prop bets whose implied probability is
    >= 0.528, does the realized hit rate exceed the implied probability?

`0.528` is frozen here deliberately -- it is the median `abs_price` split from
the exploratory pass (price <= -114 / >= +114), not a value to be re-tuned on the
new data. Re-tuning it would make this another exploratory look wearing a
pre-registration's clothes.

THE EXPLORATORY READING BEING CONFIRMED OR REFUTED (2026-05-17..2026-08-30,
n=656, clean artifact root only):

    whole population        gap +1.80pp   +0.92 SE   ROI  +3.32%
    implied >= 0.528        consistently POSITIVE across every partition tried:
        first half of time  +3.99pp    second half  +4.89pp
        OVER  +1.24pp       UNDER      +5.59pp
        pr    +6.27pp       threes    +10.58pp      pts  +12.94pp
    implied <  0.528        negative or flat in 4 of 6 cells

Those six cells are SIX VIEWS OF ONE EFFECT on the same 656 rows, not six
independent draws -- so their agreement is suggestive and is not a p-value. The
honest single number is the whole-population +0.92 SE.

**THIS IS NOT A MODEL RANKING KEY, and that matters for what it can unblock.**
It says "prefer the side the book already prices higher". It uses no Syndicate
model output at all, so confirming it does NOT unblock `todo #615` (routing
volume to the moneyline), which needs a key that ranks the MODEL's own picks.
What it would unblock is a market-side selection rule, which is a different and
smaller thing.

DECISION RULE, fixed in advance:

    CONFIRMED   gap > 0 with z >= +1.96   -> a real, tradeable market-side lean
    REFUTED     gap <= 0                  -> the exploratory result was noise
    INCONCLUSIVE otherwise                -> more data; do NOT trade it
    UNREADABLE  n < 150                   -> the sprint did not produce enough
                                            rows; NOT a refutation

`UNREADABLE` exists because the precondition can fail independently of the
hypothesis: a window that produces too few graded rows says nothing either way,
and reporting that as REFUTED would discard a live hypothesis on an empty
population. Exit 3, following `verify_wnba_totals_pricing.py`.

Exit codes: 0 CONFIRMED  1 REFUTED  2 INCONCLUSIVE  3 UNREADABLE
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared import wnba_card_provenance as provenance  # noqa: E402

# FROZEN 2026-09-01. Do not re-fit on the test data.
IMPLIED_THRESHOLD = 0.528
MIN_ROWS = 150
WINDOW_START = "2026-09-17"
WINDOW_END = "2026-09-25"

CONFIRMED, REFUTED, INCONCLUSIVE, UNREADABLE = 0, 1, 2, 3


def american_to_probability(odds: float | None) -> float | None:
    if odds is None:
        return None
    try:
        value = float(odds)
    except (TypeError, ValueError):
        return None
    if -100.0 < value < 100.0:  # not an American price; reject, never coerce
        return None
    return (-value) / ((-value) + 100.0) if value < 0 else 100.0 / (value + 100.0)


def evaluate(rows: list[dict]) -> tuple[int, dict]:
    """`rows` need: implied (or price), y (1 win / 0 loss), source_path."""
    clean = [
        row for row in rows
        if provenance.root_of(row.get("source_path")) == provenance.SYNDICATE
        and row.get("y") in (0, 1)
    ]
    priced = []
    for row in clean:
        implied = row.get("implied")
        if implied is None:
            implied = american_to_probability(row.get("price"))
        if implied is None:
            continue
        priced.append((implied, int(row["y"])))

    selected = [(p, y) for p, y in priced if p >= IMPLIED_THRESHOLD]
    n = len(selected)
    detail = {
        "window": f"{WINDOW_START}..{WINDOW_END}",
        "threshold": IMPLIED_THRESHOLD,
        "rows_clean_root": len(clean),
        "rows_priced": len(priced),
        "n_selected": n,
    }
    if n < MIN_ROWS:
        detail["reason"] = (
            f"only {n} selected rows, need {MIN_ROWS}; the window did not produce "
            "enough graded rows. This is NOT a refutation."
        )
        return UNREADABLE, detail

    hit = sum(y for _, y in selected) / n
    implied_mean = sum(p for p, _ in selected) / n
    gap = hit - implied_mean
    se = math.sqrt(max(hit * (1 - hit), 1e-12) / n)
    z = gap / se
    detail.update({"hit": hit, "implied": implied_mean, "gap": gap, "se": se, "z": z})

    if gap <= 0:
        return REFUTED, detail
    return (CONFIRMED, detail) if z >= 1.96 else (INCONCLUSIVE, detail)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--rows-json", required=True,
                        help="graded prop rows for the window (price|implied, y, source_path)")
    args = parser.parse_args(argv)

    import json

    with open(args.rows_json, encoding="utf-8") as handle:
        rows = json.load(handle)

    code, detail = evaluate(rows if isinstance(rows, list) else rows.get("rows", []))
    verdict = {CONFIRMED: "CONFIRMED", REFUTED: "REFUTED",
               INCONCLUSIVE: "INCONCLUSIVE", UNREADABLE: "UNREADABLE"}[code]
    print(f"{verdict}: favourite-lean on WNBA props (implied >= {IMPLIED_THRESHOLD})")
    for key, value in detail.items():
        if isinstance(value, float):
            print(f"    {key}: {value:.4f}")
        else:
            print(f"    {key}: {value}")
    if code == CONFIRMED:
        print("    NOTE: this is a MARKET-SIDE rule. It does not unblock todo #615,")
        print("    which needs a key that ranks the MODEL's own picks.")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
