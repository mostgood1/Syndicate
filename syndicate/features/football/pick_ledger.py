"""Stage 0: the record that lets the pick gate open.

`pick_gate.py` suppresses NCAAF picks because the model loses to the closing
line. It opens again only on a measurement, and a measurement needs a table
nobody is currently writing. This is that table.

ONE ROW PER (game x provider). Four quantities per row:

    model margin/total       what we predicted, and from which rating source
    OPENING line             what the market first posted
    CLOSING line             what the market settled on
    REALISED margin/total    what actually happened

Everything the exit criterion asks for is a join away, and nothing else needs
to be collected.

WHY PER-PROVIDER, NOT A CONSENSUS. Collapsing books to one number is a measured
mistake in this repo: the odds capture kept 1 of 4-8 books platform-wide, and
price shopping across them was worth **+2.79 ROI points**. A ledger that
averages books away cannot ever show that again, and averaging is not reversible
after the fact.

WHY OPENING *AND* CLOSING. The closing line is the hardest target in betting --
it has absorbed every injury report and every sharp bet. The open is materially
softer. A model that beats the open but not the close has a TIMING problem, not
an ACCURACY problem, and those need completely different fixes. Recording only
the close cannot distinguish them.

**CFBD serves `spreadOpen`/`overUnderOpen` retrospectively** (measured
2026-08-19: 157 of 212 lines in a sampled week, ~74%), and final scores ride the
same payload. So this ledger BACKFILLS -- it does not have to accrue forward
over a season before it answers anything. That is the difference between a
question answerable today and one answerable in January.

**The gap is that ~26% of lines carry no opening price.** That is a coverage
fact to report, not a hole to fill with the closing price -- substituting close
for open would silently answer "beats the open?" with the close's own number.
`open_missing` counts it instead.
"""
from __future__ import annotations

import csv
import os
import re
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any, Iterable, Mapping

LEDGER_SUBDIR = "pick_ledger"

#: Column order is the file contract. Append only -- readers key by name, but a
#: stable order keeps diffs of the artifact legible.
_HEADER_CACHE: list[str] | None = None


@dataclass
class PickLedgerRow:
    """One (game, provider) observation. Fields fill in over the game's life."""

    sport: str
    season: int
    week: int
    game_id: str
    home_team: str
    away_team: str
    start_date: str = ""
    provider: str = ""

    # market
    spread_open: float | None = None
    spread_close: float | None = None
    total_open: float | None = None
    total_close: float | None = None
    home_moneyline: float | None = None
    away_moneyline: float | None = None

    # model
    model_margin: float | None = None
    model_total: float | None = None
    model_home_win_prob: float | None = None
    model_margin_stdev: float | None = None
    rating_source: str = ""
    model_generated_at: str = ""

    # outcome
    home_score: float | None = None
    away_score: float | None = None
    realised_margin: float | None = None
    realised_total: float | None = None

    captured_at: str = ""

    def __post_init__(self) -> None:
        self.provider = normalise_provider(self.provider)

    def key(self) -> tuple[str, str, str]:
        return (self.sport, str(self.game_id), self.provider or "")


#: Books that arrive under more than one spelling. Measured 2026-08-19: CFBD
#: served BOTH "DraftKings" (n=714) and "Draft Kings" (n=10) in one season, and
#: they graded as separate books -- the 10-row split even read TIED against the
#: 714-row parent's MODEL_WORSE. Same book, two names, two verdicts.
_PROVIDER_ALIASES = {
    "draft kings": "DraftKings",
    "draftkings": "DraftKings",
    "espn bet": "ESPN Bet",
    "espnbet": "ESPN Bet",
    "bovada": "Bovada",
    "caesars": "Caesars",
    "william hill (new jersey)": "Caesars",
}


def normalise_provider(name: Any) -> str:
    text = str(name or "").strip()
    if not text:
        return ""
    return _PROVIDER_ALIASES.get(text.lower(), text)


def header() -> list[str]:
    global _HEADER_CACHE
    if _HEADER_CACHE is None:
        _HEADER_CACHE = [f.name for f in fields(PickLedgerRow)]
    return list(_HEADER_CACHE)


def data_root() -> Path:
    """Disk-backed via SYNDICATE_DATA_ROOT.

    model_engine_standard 3b: a local-only cache cannot reach Render, because
    `vendor/*/data/` is gitignored AND inside the ephemeral checkout. The
    ledger has to live where the worker's mounted disk is.
    """
    raw = os.environ.get("SYNDICATE_DATA_ROOT", "").strip()
    return Path(raw) if raw else Path("data")


def ledger_path(sport: str, season: int, *, root: Path | str | None = None) -> Path:
    base = Path(root) if root is not None else data_root()
    slug = str(sport or "").strip().lower()
    return base / f"{slug}_source" / "data" / LEDGER_SUBDIR / f"pick_ledger_{slug}_{season}.csv"


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def load_ledger(sport: str, season: int, *, root: Path | str | None = None) -> list[PickLedgerRow]:
    path = ledger_path(sport, season, root=root)
    if not path.exists():
        return []
    names = {f.name for f in fields(PickLedgerRow)}
    floats = {
        "spread_open", "spread_close", "total_open", "total_close",
        "home_moneyline", "away_moneyline", "model_margin", "model_total",
        "model_home_win_prob", "model_margin_stdev", "home_score", "away_score",
        "realised_margin", "realised_total",
    }
    out: list[PickLedgerRow] = []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        for raw in csv.DictReader(fh):
            kw: dict[str, Any] = {}
            for k, v in raw.items():
                if k not in names:
                    continue
                if k in floats:
                    kw[k] = _as_float(v)
                elif k in {"season", "week"}:
                    try:
                        kw[k] = int(float(v)) if v not in (None, "") else 0
                    except (TypeError, ValueError):
                        kw[k] = 0
                else:
                    kw[k] = v or ""
            out.append(PickLedgerRow(**kw))
    return out


def _merge(existing: PickLedgerRow, incoming: PickLedgerRow) -> PickLedgerRow:
    """Field-wise upsert. Non-null incoming wins, EXCEPT the opening line.

    An opening line is a point-in-time fact: once observed it must never be
    rewritten, or a later capture silently turns "what the market opened at"
    into "what it moved to" and the open-vs-close comparison quietly becomes
    close-vs-close.
    """
    merged = PickLedgerRow(**asdict(existing))
    for f in fields(PickLedgerRow):
        name = f.name
        if name in {"spread_open", "total_open"} and getattr(merged, name) is not None:
            continue
        new = getattr(incoming, name)
        if new is None or new == "":
            continue
        setattr(merged, name, new)
    return merged


def upsert(
    sport: str,
    season: int,
    rows: Iterable[PickLedgerRow],
    *,
    root: Path | str | None = None,
) -> dict[str, int]:
    """Merge rows into the season ledger. Idempotent: re-running changes nothing.

    Returns counts so a caller can report what it actually did rather than that
    it ran.
    """
    existing = {r.key(): r for r in load_ledger(sport, season, root=root)}
    added = updated = unchanged = 0
    for row in rows:
        k = row.key()
        prior = existing.get(k)
        if prior is None:
            existing[k] = row
            added += 1
            continue
        merged = _merge(prior, row)
        if asdict(merged) == asdict(prior):
            unchanged += 1
        else:
            existing[k] = merged
            updated += 1

    path = ledger_path(sport, season, root=root)
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(existing.values(), key=lambda r: (r.week, str(r.game_id), r.provider))
    tmp = path.with_suffix(".csv.tmp")
    with tmp.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=header())
        writer.writeheader()
        for r in ordered:
            writer.writerow({k: ("" if v is None else v) for k, v in asdict(r).items()})
    tmp.replace(path)
    return {"added": added, "updated": updated, "unchanged": unchanged, "total": len(ordered)}


def coverage(rows: Iterable[PickLedgerRow]) -> dict[str, Any]:
    """What the ledger can and cannot answer. Denominators, not just counts.

    A rate without its denominator is the failure mode this repo has recorded
    repeatedly, so every count here is reported against `rows`.
    """
    rows = list(rows)
    n = len(rows)
    if not n:
        return {"rows": 0}
    have = lambda attr: sum(1 for r in rows if getattr(r, attr) is not None)  # noqa: E731
    gradable_close = sum(
        1 for r in rows if r.model_margin is not None and r.spread_close is not None and r.realised_margin is not None
    )
    gradable_open = sum(
        1 for r in rows if r.model_margin is not None and r.spread_open is not None and r.realised_margin is not None
    )
    graded = [r for r in rows if r.model_margin is not None and r.realised_margin is not None]
    status: dict[str, int] = {}
    for r in graded:
        st = leak_status(r.rating_source, r.season)
        status[st] = status.get(st, 0) + 1
    return {
        "rows": n,
        "games": len({r.game_id for r in rows}),
        "providers": sorted({r.provider for r in rows if r.provider}),
        "graded_leak_status": status,
        "with_model": have("model_margin"),
        "with_spread_close": have("spread_close"),
        "with_spread_open": have("spread_open"),
        "open_missing": n - have("spread_open"),
        "with_result": have("realised_margin"),
        "gradable_vs_close": gradable_close,
        "gradable_vs_open": gradable_open,
    }


def _paired(model_err: list[float], market_err: list[float]) -> dict[str, Any]:
    """Paired model-vs-market comparison. The SE of the DIFFERENCE governs.

    Comparing two independent MAEs is the wrong test here and it has already
    misled once this session: |error| spreads ~12 points, so an unpaired SE is
    ~0.8 and a real 0.17 difference vanishes into it. The games and the market
    price are the same rows, so the comparison is paired.
    """
    n = len(model_err)
    if n < 2:
        return {"n": n, "verdict": "INSUFFICIENT"}
    d = [m - k for m, k in zip(model_err, market_err)]
    mean = sum(d) / n
    var = sum((x - mean) ** 2 for x in d) / (n - 1)
    se = (var / n) ** 0.5
    if se:
        t = mean / se
    elif mean == 0:
        t = 0.0               # identical every row: genuinely tied
    else:
        # Zero variance with a NON-ZERO mean is a perfectly CONSISTENT
        # difference -- the most significant result possible, not the least.
        # `t = mean / se if se else 0.0` reported it as TIED, which would have
        # let a model that loses on every single row read as indistinguishable
        # from the market. Caught by test_model_better_is_detected.
        t = float("inf") if mean > 0 else float("-inf")
    if abs(t) < 2.0:
        verdict = "TIED"          # indistinguishable from the market
    elif mean < 0:
        verdict = "MODEL_BETTER"
    else:
        verdict = "MODEL_WORSE"
    return {
        "n": n,
        "model_mae": sum(model_err) / n,
        "market_mae": sum(market_err) / n,
        "delta_mae": mean,
        "se": se,
        "t": t,
        "verdict": verdict,
    }


def evaluate(rows: Iterable[PickLedgerRow]) -> dict[str, Any]:
    """The gate's lift condition, computed.

    Grades the model's margin against BOTH the opening and the closing line on
    the rows where all three of (model, line, result) exist. Reports each
    provider separately as well as pooled, because a model can beat a soft book
    and lose to a sharp one and the pooled number hides both.

    A market may reopen in `pick_gate._SERVING_REGISTRY` only when
    `verdict` is MODEL_BETTER on the CLOSING line, out-of-sample. TIED is not
    good enough: tied on average, minus the vig, still loses money.
    """
    rows = list(rows)
    out: dict[str, Any] = {"coverage": coverage(rows)}
    for label, line_attr in (("vs_close", "spread_close"), ("vs_open", "spread_open")):
        me: list[float] = []
        ke: list[float] = []
        by_provider: dict[str, tuple[list[float], list[float]]] = {}
        by_source: dict[str, tuple[list[float], list[float]]] = {}
        for r in rows:
            line = getattr(r, line_attr)
            if r.model_margin is None or line is None or r.realised_margin is None:
                continue
            # CFBD spread is quoted from the HOME side and negative when the
            # home team is favoured, so the market's implied home margin is its
            # negation. Getting this backwards inverts every comparison while
            # still producing plausible-looking numbers.
            market_margin = -float(line)
            m_err = abs(float(r.model_margin) - float(r.realised_margin))
            k_err = abs(market_margin - float(r.realised_margin))
            me.append(m_err)
            ke.append(k_err)
            p = r.provider or "unknown"
            by_provider.setdefault(p, ([], []))
            by_provider[p][0].append(m_err)
            by_provider[p][1].append(k_err)
            src = r.rating_source or "(none)"
            by_source.setdefault(src, ([], []))
            by_source[src][0].append(m_err)
            by_source[src][1].append(k_err)
        out[label] = _paired(me, ke)
        out[label]["by_provider"] = {
            p: _paired(a, b) for p, (a, b) in sorted(by_provider.items())
        }
        out[label]["by_rating_source"] = {
            s: _paired(a, b) for s, (a, b) in sorted(by_source.items())
        }
    out["leak_warning"] = leak_warning(rows)
    return out


#: Rating sources KNOWN to contain the outcome of the games they predict.
#: `cfbd_ppa_season_<Y>` is CFBD's SEASON-AGGREGATE PPA: rating a team by its
#: whole-season performance and then "predicting" that season's games means the
#: rating already contains the result. Measured 2026-08-19, correlation with
#: outcome fell 0.663 -> 0.509 once the as-of fix landed, i.e. ~30% of the
#: apparent skill was hindsight.
_LEAKED_RATING_SOURCE = re.compile(r"^cfbd_ppa_season_\d{4}$")


def is_leaked_rating_source(source: Any) -> bool:
    return bool(_LEAKED_RATING_SOURCE.match(str(source or "").strip()))


#: Any 4-digit year inside a rating-source string, e.g.
#: "cfbd_sp_plus_2023[scale=10]+cfbd_ppa_season_2023_fallback_for_2024".
_YEAR_IN_SOURCE = re.compile(r"(19|20)\d{2}")


def rating_seasons(source: Any) -> list[int]:
    """Every season named in a rating source, ascending.

    A composite source names more than one (a primary rating plus a fallback,
    and sometimes the TARGET season in a '..._fallback_for_2024' suffix), so the
    check below uses the LATEST — the most recent information the run could
    possibly have seen.
    """
    text = str(source or "")
    return sorted({int(m.group(0)) for m in _YEAR_IN_SOURCE.finditer(text)})


def leak_status(source: Any, game_season: Any) -> str:
    """Classify one graded row's rating against the season it predicts.

    This is the GENERAL rule; `is_leaked_rating_source` is the special case for
    a source known to be season-aggregate regardless of year.

      "clean"        every rating season is STRICTLY BEFORE the game's season,
                     so the rating cannot contain the game.
      "same_season"  the rating names the game's own season. AMBIGUOUS and it
                     genuinely matters which: PRESEASON SP+ for an unplayed
                     season is clean and is what production uses, while FINAL
                     SP+ for a completed one is leaked. The two are
                     indistinguishable from the string alone, so this reports
                     rather than guesses.
      "leaked"       a rating season AFTER the game's season (future
                     information), or a known season-aggregate source.
      "unknown"      no season could be parsed.
    """
    if is_leaked_rating_source(source):
        return "leaked"
    try:
        target = int(game_season)
    except (TypeError, ValueError):
        return "unknown"
    seasons = rating_seasons(source)
    # A '..._fallback_for_<target>' suffix names the TARGET, not a rating; it
    # would otherwise make every prior-season run look same-season.
    seasons = [s for s in seasons if s != target] or seasons
    if not seasons:
        return "unknown"
    latest = max(seasons)
    if latest > target:
        return "leaked"
    if latest == target:
        return "same_season"
    return "clean"


def leak_warning(rows: Iterable[PickLedgerRow]) -> dict[str, Any] | None:
    """Flag graded rows whose model number had hindsight in it.

    Returns None when clean. This exists because the ledger's whole purpose is
    to decide whether a market reopens, and a leaked row flatters the model --
    so a silent mix of leaked and clean rows could open a market on hindsight.
    The evaluator therefore reports BY rating_source, and this names the
    offenders outright rather than leaving it to whoever reads the table.
    """
    graded = [
        r for r in rows
        if r.model_margin is not None and r.realised_margin is not None
    ]
    bad = [r for r in graded if is_leaked_rating_source(r.rating_source)]
    if not bad:
        return None
    sources = sorted({str(r.rating_source) for r in bad})
    return {
        "leaked_rows": len(bad),
        "graded_rows": len(graded),
        "sources": sources,
        "message": (
            f"{len(bad)} of {len(graded)} graded rows use a LEAKED rating source "
            f"({', '.join(sources)}) -- the rating contains the outcome of the "
            "game it predicts, so the model's error is FLATTERED. A loss on "
            "these rows is real and then some; a WIN on them proves nothing and "
            "must NOT reopen a market."
        ),
    }
