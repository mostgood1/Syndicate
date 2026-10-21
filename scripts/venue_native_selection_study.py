"""Venue-native vs Suggested selection, graded on the venue books' own settled rows. Read-only.

usage: py -3 scripts/venue_native_selection_study.py LEDGER_JSON REPO_ROOT

LEDGER_JSON = venue-family rows of `execution_ledger.full_history_orders()`, dumped read-only on the
fleet at nice 19 (`{"rows": [...]}` or a bare list). Findings:
.syndicate/findings_2026-10-20_venue_native_selection.md (lane venue-native-selection).

Selection regimes, split by SUBMIT time (each is a code change on main, so the split is by policy, not by
outcome):
  R1 venue-native  paper:<venue> before 2ecf7c2e (2026-10-13T16:35:16Z): the WHOLE shortlist was scoped to
                   the venue and gated on the venue's own price (gross >= 2%, net of fee > 0).
  R2 suggested     paper:<venue> from 2ecf7c2e: only rows the board flagged Suggested at the BEST book, then
                   the same venue gates.
  R3 ladder        paper:<venue>:ladder (from 289c0b69, 2026-10-20T21:29Z): EV-only-refused rows priced at
                   the venue, banded by venue net EV, flat $1, the complement of paper2.
  R4 live          kalshi / polymarket mode=live rows with ev_pct (live 0% floor from 2026-10-20T20:45:40Z).
Returns are per $1 staked, net of the venue fee (recorded, else imputed with venue_fees), exactly as
scripts/paper_bet_optimization.py computes them, so the two studies' numbers are comparable.
"""
import collections, json, math, sys

LEDGER, REPO = sys.argv[1], sys.argv[2]
sys.path.insert(0, REPO)
from syndicate.features.shared import venue_fees  # noqa: E402

SUGGESTED_ONLY_FROM = "2026-10-13T16:35:16"
LIVE_FLOOR_FROM = "2026-10-20T20:45:40"
BANDS = ((-99, 0, "<0"), (0, 1, "0-1"), (1, 2, "1-2"), (2, 4, "2-4"), (4, 99, ">=4"))


def dec(a):
    """Decimal odds from an American price OR a contract price. Live venue rows record `fill_price` as the
    contract price (0.65), paper rows as American (-186); no American price lies strictly inside (-100, 100)."""
    a = float(a)
    if 0 < a < 1:
        return 1 / a
    return 1 + (a / 100 if a > 0 else 100 / -a)


def regime(r):
    v, sub = str(r.get("venue")), str(r.get("submitted_at") or "")
    if v.endswith(":ladder"):
        return "R3 ladder"
    if r.get("mode") == "live":
        return "R4 live" if sub >= LIVE_FLOOR_FROM else None
    return "R1 venue-native" if sub < SUGGESTED_ONLY_FROM else "R2 suggested"


def load():
    raw = json.load(open(LEDGER))
    orders = raw["rows"] if isinstance(raw, dict) else raw
    orders.sort(key=lambda r: str(r.get("submitted_at") or ""))
    seen, rows, coverage = set(), [], collections.defaultdict(set)
    for r in orders:
        reg = regime(r)
        if reg is None or r.get("ev_pct") is None:
            continue
        venue = "kalshi" if "kalshi" in str(r.get("venue")) else "polymarket"
        coverage[(reg, venue, "booked")].add(str(r.get("selected_date")))
        if r.get("outcome") not in ("won", "lost"):
            continue
        if r.get("fill_price") in (None, 0) or not float(r.get("fill_stake_dollars") or 0):
            continue
        key = (r.get("venue"), r.get("opening_key") or r.get("position_key"))
        if key in seen:
            continue
        seen.add(key)
        d = dec(r["fill_price"])
        stake = float(r["fill_stake_dollars"])
        fee = float(r.get("fees_dollars") or 0.0)
        if fee <= 0:
            try:
                per, _b, _u = venue_fees.taker_fee_per_contract(venue, 1.0 / d, sport=r.get("sport"),
                                                                 market=r.get("market"), segment=r.get("segment"))
                fee = float(per or 0.0) * stake * d
            except Exception:
                pass
        fee_frac = fee / stake
        won = r["outcome"] == "won"
        p_fair = (1 + float(r["ev_pct"]) / 100) / d
        q_cost = 1.0 / d + fee_frac / d
        ev_net = 100 * (p_fair - q_cost) / q_cost
        cm = r.get("closing_mark") if isinstance(r.get("closing_mark"), dict) else {}
        clv = cm.get("clv_pct") if cm.get("close_book_scope") == "same_book" and cm.get("reason") == "resolved" else None
        fp = float(r["fill_price"])
        if clv is not None and 0 < fp < 1 and cm.get("close_price") is not None:
            # DEFECT, measured 2026-10-21: the stored clv_pct on LIVE rows reads the contract price (0.65) as
            # American odds (+0.65 -> 99.4% implied), so every live mark is ~ -35 points. Recomputed here in
            # the ledger's own convention (probability points, closing implied - our implied).
            clv = round((1.0 / dec(cm["close_price"]) - fp) * 100.0, 4)
        coverage[(reg, venue, "settled")].add(str(r.get("selected_date")))
        rows.append({
            "reg": reg, "venue": venue, "date": str(r.get("selected_date")), "event": str(r.get("event_id") or key[1]),
            "sport": str(r.get("sport") or "?").lower(), "ev": float(r["ev_pct"]), "ev_net": ev_net,
            "ev_net_stamped": r.get("ev_net_pct"), "band": r.get("ev_band"),
            "ret": (d - 1 - fee_frac) if won else (-1 - fee_frac), "won": won, "imp": 1.0 / d,
            "clv": None if clv is None else float(clv), "stake": stake,
            "fee_pts": 100.0 * fee_frac / d,  # fee per $1 of payout = probability points, CLV's unit
        })
    return rows, coverage


def clustered(rows, f=lambda r: r["ret"]):
    rows = [r for r in rows if f(r) is not None]
    n = len(rows)
    if not n:
        return float("nan"), float("nan"), 0, 0
    m = sum(f(r) for r in rows) / n
    g = collections.defaultdict(float)
    for r in rows:
        g[r["event"]] += f(r) - m
    return m, math.sqrt(sum(v * v for v in g.values())) / n, n, len(g)


def line(label, rows):
    m, se, n, e = clustered(rows)
    c, cse, cn, _ = clustered(rows, lambda r: r["clv"])
    ev = sum(r["ev_net"] for r in rows) / len(rows) if rows else float("nan")
    dates = len({r["date"] for r in rows})
    fee = sum(r["fee_pts"] for r in rows) / len(rows) if rows else float("nan")
    print(f"  {label:<26} n {n:4d} ev {e:4d} dates {dates:2d} | claimed ev_net {ev:+5.2f}% | "
          f"ROI {100*m:+6.1f}% +- {100*se:4.1f} | same-book CLV {c:+5.2f}pt +- {cse:4.2f} (n {cn}) | fee {fee:4.2f}pt")


def main():
    rows, coverage = load()
    print("COVERAGE (selected dates booked / settled, per regime x venue)")
    for (reg, venue, kind), ds in sorted(coverage.items()):
        ds = sorted(ds)
        print(f"  {reg:<16} {venue:<10} {kind:<7} {len(ds):2d} dates  {ds[0]}..{ds[-1]}")
    allds = sorted({r["date"] for r in rows})
    print(f"  settled rows {len(rows)} on {len(allds)} selected dates {allds[0]}..{allds[-1]}")
    for reg in ("R1 venue-native", "R2 suggested", "R3 ladder", "R4 live"):
        print(f"\n{reg}")
        for venue in ("kalshi", "polymarket", None):
            sub = [r for r in rows if r["reg"] == reg and (venue is None or r["venue"] == venue)]
            if not sub:
                continue
            line(venue or "both venues", sub)
            for lo, hi, name in BANDS:
                b = [r for r in sub if lo <= r["ev_net"] < hi]
                if b:
                    line(f"   ev_net {name}", b)
    # The floor question on the venue-native population, pooled venues and per venue: what does each
    # candidate floor keep, and how does what it keeps grade?
    print("\nFLOOR SWEEP on R1 venue-native (net-of-fee EV at the venue's own price)")
    for venue in ("kalshi", "polymarket", None):
        print(f" {venue or 'both venues'}")
        sub = [r for r in rows if r["reg"] == "R1 venue-native" and (venue is None or r["venue"] == venue)]
        for floor in (0, 0.5, 1, 1.5, 2, 3, 4):
            line(f"   ev_net >= {floor}", [r for r in sub if r["ev_net"] >= floor])
    # The two regimes cover different weeks (MLB postseason sits in R1), so compare them inside one sport.
    print("\nSPORT SPLIT, R1 venue-native vs R2 suggested (both venues)")
    for sport in sorted({r["sport"] for r in rows}):
        for reg in ("R1 venue-native", "R2 suggested"):
            sub = [r for r in rows if r["reg"] == reg and r["sport"] == sport]
            if len(sub) >= 10:
                line(f"  {sport} {reg[:2]}", sub)
    print("\nR1 venue-native WITHOUT mlb, floor sweep")
    for venue in ("kalshi", "polymarket", None):
        print(f" {venue or 'both venues'}")
        sub = [r for r in rows if r["reg"] == "R1 venue-native" and r["sport"] != "mlb"
               and (venue is None or r["venue"] == venue)]
        for floor in (0, 0.5, 1, 1.5, 2):
            line(f"   ev_net >= {floor}", [r for r in sub if r["ev_net"] >= floor])
    print("\nFAVOURITE / DOG split (R1+R2 pooled, both venues)")
    pool = [r for r in rows if r["reg"] in ("R1 venue-native", "R2 suggested")]
    line("  implied >= .5", [r for r in pool if r["imp"] >= 0.5])
    line("  implied < .5", [r for r in pool if r["imp"] < 0.5])


if __name__ == "__main__":
    main()
