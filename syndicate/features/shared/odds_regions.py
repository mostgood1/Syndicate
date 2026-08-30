"""Which OddsAPI regions a GAME-LINE call asks for. One owner, every sport.

Lifted verbatim out of `scripts/fetch_mlb_oddsapi_local.py` on 2026-08-29 so a
second sport could use it without a second copy. The mechanism, the reasoning
and the safety property below are MLB's and are unchanged -- what is new is that
NCAAF can reach them.

WHY THIS IS A SEPARATE KNOB FROM THE PROP CALLS
-----------------------------------------------
THE SPLIT IS A BILLING FACT, NOT A PREFERENCE. OddsAPI bills game lines per
REQUEST and player props per EVENT, and measured on production 2026-08-07 the
per-event families (props + segment + alternate) are **95.5% of all credits**.
So a region added to the game-line call costs roughly 30K/month, while the same
region added to the prop calls costs ~1M. Wiring both through one flat `regions`
string is what made "eu and us_ex on game lines only" inexpressible.

EXTRAS, NEVER A REPLACEMENT
---------------------------
The base `regions` is always kept, so a misconfigured value can widen coverage
but can never silently drop `us`. Unset is exactly today's behaviour. Order is
preserved so `us` stays first, and a region named twice is not billed twice.

WHY NCAAF NEEDED THIS (2026-08-29)
----------------------------------
`SYNDICATE_LIVE_ODDS_GAME_LINE_REGIONS` had exactly ONE reader -- the MLB
fetcher. `fetch_ncaaf_oddsapi_game_lines.py` takes a single `--region` off
`ODDS_API_REGION` (default `us`), so setting that env var was **inert for
NCAAF**: the value would have been present in the environment, read by nothing,
and the sharps would not have appeared. Measured the same day, NCAAF's served
book set was 11 books with **0 of 5 sharps/exchanges** -- absent are `pinnacle`
(45 events via `eu`), `novig` (51) and `prophetx` (8) via `us_ex` -- while the
board's own consensus, and therefore every market-basis edge computed against
it, was anchored on soft books alone.

Region coverage measured live, same instant, `americanfootball_ncaaf`:

    us     111 events   the 11 soft books        3 credits
    us_ex   51 events   novig, prophetx, betopenly   3 credits
    eu     111 events   pinnacle, matchbook, betfair_ex_eu, +9   3 credits

Credits are not the constraint: quota read `x-requests-remaining: 4,853,063`
during that probe.
"""

from __future__ import annotations

import os

#: The env var. Named here so the two fetchers and the tests all read the same
#: string rather than three string literals that can drift apart.
GAME_LINE_REGIONS_ENV = "SYNDICATE_LIVE_ODDS_GAME_LINE_REGIONS"


def game_line_regions(regions: str, *, env: "dict[str, str] | None" = None) -> str:
    """`regions` widened by the configured extras. Never narrowed.

    `env` is injectable so a test can prove the merge without mutating the
    process environment -- the default reads `os.environ`, which is what both
    fetchers pass through.
    """
    source = os.environ if env is None else env
    extra = str(source.get(GAME_LINE_REGIONS_ENV) or "").strip()
    if not extra:
        return regions
    seen: set[str] = set()
    merged: list[str] = []
    for candidate in list(str(regions or "").split(",")) + list(extra.split(",")):
        name = candidate.strip().lower()
        if name and name not in seen:
            seen.add(name)
            merged.append(name)
    return ",".join(merged) or regions
