"""Which build hour would have had prop odds available, per slate?

Inputs are the measured values printed by measure_odds_posting.py (full scan of
book_quotes, 2026-08-06..13). Times are CDT expressed as hours from midnight of
the SLATE day, so a capture the previous evening is negative.

BUILD_MINUTES is the slack a build needs to finish before first pitch. Today's
scoped MLB daily_update ran 244s; full-slate runs are longer, so 30 minutes is
deliberately generous rather than optimistic.
"""
from __future__ import annotations

BUILD_MINUTES = 30

# slate: (first prop capture, first pitch), both in hours from slate-day midnight CDT
MEASURED = {
    "2026-08-06": (11.42, 11.60),
    "2026-08-07": (-0.50, 17.68),
    "2026-08-08": (1.72, 14.08),
    "2026-08-09": (-0.27, 11.27),
    "2026-08-10": (-2.33, 18.12),
    "2026-08-11": (-6.78, 17.68),
    "2026-08-12": (2.05, 12.67),
    "2026-08-13": (2.03, 12.18),
}

CURRENT_EVENING_HOUR = 18.0 - 24.0  # SYNDICATE_MLB_EVENING_NEXT_DAY_SIM_START_HOUR=18, on D-1


def score(build_hour: float) -> tuple[int, int, list[str]]:
    """(slates with odds available, slates finishing before first pitch, failures)."""
    slack = BUILD_MINUTES / 60.0
    have_odds = 0
    in_time = 0
    failures = []
    for slate, (capture, pitch) in MEASURED.items():
        odds = capture <= build_hour
        timely = build_hour + slack <= pitch
        have_odds += odds
        in_time += timely
        if not (odds and timely):
            failures.append(f"{slate}({'no odds' if not odds else 'too late'})")
    return have_odds, in_time, failures


def main() -> None:
    print(f"n=8 slates (2026-08-06..13). Build needs {BUILD_MINUTES}min before first pitch.")
    print()
    print(f"{'build hour (CDT)':<20}{'odds ready':>12}{'beats 1st pitch':>18}{'both':>7}   failures")
    print("-" * 96)

    candidates = [("18:00 the night before (CURRENT)", CURRENT_EVENING_HOUR)]
    candidates += [(f"{h:02d}:00 slate day", float(h)) for h in (4, 5, 6, 7, 8, 9, 10, 11)]

    for label, hour in candidates:
        odds, timely, failures = score(hour)
        both = sum(
            1
            for capture, pitch in MEASURED.values()
            if capture <= hour and hour + BUILD_MINUTES / 60.0 <= pitch
        )
        print(f"{label:<20}{odds:>10}/8{timely:>16}/8{both:>5}/8   {', '.join(failures) if failures else '-'}")

    print()
    earliest_pitch = min(p for _, p in MEASURED.values())
    latest_capture = max(c for c, _ in MEASURED.values())
    print(f"Earliest first pitch in window: {earliest_pitch:.2f}h ({int(earliest_pitch)}:{int(earliest_pitch % 1 * 60):02d} CDT)")
    print(f"Latest prop capture in window:  {latest_capture:.2f}h ({int(latest_capture)}:{int(latest_capture % 1 * 60):02d} CDT)")
    print()
    print("Note: 2026-08-06 had prop odds captured 11:25 against an 11:36 first pitch --")
    print("11 minutes of lead. No build hour can satisfy that slate; it is a book-side")
    print("reality, not a scheduling failure. Every recommendation below is 7/8, not 8/8.")


if __name__ == "__main__":
    main()
