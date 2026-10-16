"""Same-game parlays for the NFL cheat sheet (lane `nfl-sgp-builder`, user 2026-10-16).

The joint probability of two legs is MEASURED, never assumed: a Gaussian copula whose correlation per (market|role,
relation) cell was fitted on 593 games of real closing prop lines, 2023-25 (`scripts/build_nfl_sgp_correlations.py`,
`.syndicate/findings_2026-10-16_nfl_sgp_correlations.md`), and scored out of sample (fit 2023-24, 2025 held out:
copula beats independence z -23; same player -22, teammates -10, opponents -4).

What a suggestion SAYS (user 2026-10-16, "proceed with recommendation in 2"):
  1. our probability that both legs win, its FAIR odds, and "worth it at +X or better" -- the user compares that
     against the book's own SGP quote, the only real SGP price there is;
  2. second, an ESTIMATE of what a book would pay, at an ASSUMED discount off the product of the leg prices
     (`ASSUMED_BOOK_DISCOUNT`), labelled an estimate -- no SGP price source exists;
  3. a same-player pair is flagged: books know that correlation best and price it tightest, and a flat assumed
     discount manufactures EV exactly there (the price study: >97% of "+EV at 18.5%" tickets were same-player).
Paper only: every suggestion goes to a ledger and no "edge" label is shown until a pre-registered, game-clustered
test passes (#621).
"""
from __future__ import annotations

import collections
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping

CORRELATIONS = Path("nfl_source") / "sgp" / "nfl_sgp_correlations.json"
ASSUMED_BOOK_DISCOUNT = 0.185      # ESTIMATE: the ~18.5% SGP margin in the 2026-10-13 research note; never measured
WORTH_IT_CUSHION = 0.05            # "worth it at" = 5% above fair: room for the correlation's and the legs' error
MIN_LIFT = 1.03                    # the pair must win together >= 3% more often than independent legs would
PER_GAME = 3
PER_SHEET = 10
MARKETS = {"Passing Yards": "pass_yds", "Passing Attempts": "pass_att", "Passing TDs": "pass_td",
           "Interceptions": "ints", "Rushing Yards": "rush_yds", "Rushing Attempts": "rush_att",
           "Receiving Yards": "rec_yds", "Receptions": "rec", "Anytime TD": "atd"}
_SUFFIX = {"jr", "sr", "ii", "iii", "iv", "v"}


# ------------------------------------------------------------------------------------------- bivariate normal
def _ndtr(x):
    from scipy.special import ndtr

    return ndtr(x)


def bvn_lower(h, k, rho):
    """Phi2(h, k; rho) via Owen's T (vectorised). h or k at exactly 0 is nudged; the formula divides by them."""
    import numpy as np
    from scipy.special import ndtr, owens_t

    h = np.where(np.abs(h) < 1e-9, 1e-9, h)
    k = np.where(np.abs(k) < 1e-9, 1e-9, k)
    rho = np.clip(rho, -0.999999, 0.999999)
    s = np.sqrt(1.0 - rho * rho)
    beta = np.where(h * k > 0, 0.0, 0.5)
    return 0.5 * ndtr(h) + 0.5 * ndtr(k) - owens_t(h, (k - rho * h) / (h * s)) - owens_t(k, (h - rho * k) / (k * s)) - beta


def bvn_upper(h, k, rho):
    """P(X > h, Y > k)."""
    return 1.0 - _ndtr(h) - _ndtr(k) + bvn_lower(h, k, rho)


def bvn_pdf(h, k, rho: float):
    import numpy as np

    s2 = 1.0 - rho * rho
    return np.exp(-(h * h - 2 * rho * h * k + k * k) / (2 * s2)) / (2 * math.pi * math.sqrt(s2))


def joint_over(p_a, p_b, rho):
    """P(a over AND b over) under a Gaussian copula with each leg's own P(over)."""
    from scipy.special import ndtri

    return bvn_upper(ndtri(1.0 - p_a), ndtri(1.0 - p_b), rho)


# ------------------------------------------------------------------------------------------- play-by-play usage
def name_key(name: Any) -> tuple[str, str] | None:
    """First initial + last name: 'Tory Horton' and nflverse's 'T.Horton' meet here; suffixes dropped."""
    import re

    parts = [p for p in re.split(r"[\s.]+", str(name or "").lower().replace("'", "")) if p and p not in _SUFFIX]
    return (parts[0][0], re.sub(r"[^a-z]", "", parts[-1])) if len(parts) >= 2 else None


def load_pbp(data_root: Path, season: int):
    import pandas as pd

    cols = ["game_id", "season", "season_type", "week", "game_date", "home_team", "away_team", "posteam",
            "two_point_attempt", "play_type", "pass_attempt", "rush_attempt", "sack", "qb_dropback", "complete_pass",
            "interception", "pass_touchdown", "touchdown", "passing_yards", "rushing_yards", "receiving_yards",
            "passer_player_id", "passer_player_name", "rusher_player_id", "rusher_player_name",
            "receiver_player_id", "receiver_player_name", "td_player_id", "td_player_name"]
    path = Path(data_root) / "nfl_source" / "tracking" / "nflverse" / "pbp" / f"pbp_{season}.csv"
    d = pd.read_csv(path, usecols=cols, low_memory=False)
    return d[(d.season_type == "REG") & (d.two_point_attempt.fillna(0) != 1)].copy()


def player_games(pbp):
    """(game_id, pid) -> stat line + team; and per game: name key -> pid, ambiguous keys dropped."""
    import pandas as pd

    f = lambda s: s.fillna(0)  # noqa: E731
    parts = []
    pa = pbp[pbp.passer_player_id.notna()]
    parts.append(pd.DataFrame({"game_id": pa.game_id, "pid": pa.passer_player_id, "name": pa.passer_player_name,
                               "team": pa.posteam, "pass_att": ((f(pa.pass_attempt) == 1) & (f(pa.sack) != 1)).astype(int),
                               "pass_yds": f(pa.passing_yards), "pass_td": f(pa.pass_touchdown),
                               "ints": f(pa.interception), "dropbacks": f(pa.qb_dropback)}))
    ru = pbp[pbp.rusher_player_id.notna() & (f(pbp.rush_attempt) == 1)]
    parts.append(pd.DataFrame({"game_id": ru.game_id, "pid": ru.rusher_player_id, "name": ru.rusher_player_name,
                               "team": ru.posteam, "rush_att": 1, "rush_yds": f(ru.rushing_yards)}))
    rc = pbp[pbp.receiver_player_id.notna() & (f(pbp.pass_attempt) == 1) & (f(pbp.sack) != 1)]
    parts.append(pd.DataFrame({"game_id": rc.game_id, "pid": rc.receiver_player_id, "name": rc.receiver_player_name,
                               "team": rc.posteam, "targets": 1, "rec": f(rc.complete_pass),
                               "rec_yds": f(rc.receiving_yards)}))
    td = pbp[pbp.td_player_id.notna() & (f(pbp.touchdown) == 1)]
    parts.append(pd.DataFrame({"game_id": td.game_id, "pid": td.td_player_id, "name": td.td_player_name,
                               "team": None, "atd": 1}))
    rows = pd.concat(parts, ignore_index=True)
    stat_cols = ["pass_att", "pass_yds", "pass_td", "ints", "dropbacks", "rush_att", "rush_yds", "targets", "rec",
                 "rec_yds", "atd"]
    for c in stat_cols:
        rows[c] = rows[c].fillna(0) if c in rows else 0
    team = rows.dropna(subset=["team"]).groupby(["game_id", "pid"]).team.agg(lambda s: s.mode().iloc[0])
    lines = rows.groupby(["game_id", "pid"])[stat_cols].sum()
    lines["atd"] = (lines["atd"] > 0).astype(int)
    lines = lines.join(team).reset_index()
    names: dict[str, dict[tuple[str, str], set]] = collections.defaultdict(lambda: collections.defaultdict(set))
    for g, pid, name in rows[["game_id", "pid", "name"]].dropna().itertuples(index=False):
        key = name_key(name)
        if key:
            names[g][key].add(pid)
    index = {g: {k: next(iter(v)) for k, v in m.items() if len(v) == 1} for g, m in names.items()}
    return lines, index


def usage_roles(prior) -> dict[str, str]:
    """pid -> role from a team's PRIOR usage table (columns dropbacks, rush_att, targets, indexed by pid): QB by
    dropbacks (>= 20); ground players (carries >= targets) RB1 / RB2 by carries; pass catchers R1 / R2 / R3 by
    targets. The study and the sheet use this one rule, so a role means the same thing in both."""
    if prior.empty:
        return {}
    qb = prior.dropbacks.idxmax() if prior.dropbacks.max() >= 20 else None
    other = prior.drop(index=[qb]) if qb is not None else prior
    other = other[other.dropbacks < (other.rush_att + other.targets)]
    ground = other[other.rush_att >= other.targets].sort_values("rush_att", ascending=False).index.tolist()
    air = other[other.rush_att < other.targets].sort_values("targets", ascending=False).index.tolist()
    rank = {}
    if qb is not None:
        rank[qb] = "QB"
    for i, pid in enumerate(ground):
        rank[pid] = "RB1" if i == 0 else "RB2"
    for i, pid in enumerate(air):
        rank[pid] = ("R1", "R2", "R3")[min(i, 2)]
    return rank


def current_roles(data_root: Path, day: str) -> dict[tuple[str, tuple[str, str]], str]:
    """(team, name key) -> role from this season's regular-season games BEFORE `day` (the sheet's date)."""
    season = int(day[:4]) if int(day[5:7]) >= 8 else int(day[:4]) - 1
    pbp = load_pbp(data_root, season)
    pbp = pbp[pbp.game_date < day]
    if pbp.empty:
        return {}
    lines, _ = player_games(pbp)
    names = collections.defaultdict(set)
    for col_id, col_name in (("passer_player_id", "passer_player_name"), ("rusher_player_id", "rusher_player_name"),
                             ("receiver_player_id", "receiver_player_name")):
        sub = pbp[[col_id, col_name, "posteam"]].dropna()
        for pid, name, team in sub.drop_duplicates().itertuples(index=False):
            key = name_key(name)
            if key:
                names[(team, key)].add(pid)
    out = {}
    for team, g in lines.dropna(subset=["team"]).groupby("team"):
        rank = usage_roles(g.groupby("pid")[["dropbacks", "rush_att", "targets"]].sum())
        for (t, key), pids in names.items():
            if t == team and len(pids) == 1:
                out[(team, key)] = rank.get(next(iter(pids)), "UNK")
    return out


# ------------------------------------------------------------------------------------------- the sheet's SGPs
def load_cells(data_root: Path) -> dict[str, Any] | None:
    try:
        return json.loads((Path(data_root) / CORRELATIONS).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def payout(price: Any) -> float | None:
    """Total return per unit staked at an American price (stake included), via the registered
    `opportunity_signals.implied_probability` -- no second converter (`scripts/probability_differential.py`)."""
    from syndicate.features.shared.opportunity_signals import implied_probability

    q = implied_probability(price)
    return 1.0 / q if q else None


def odds_at(payout_multiple: float) -> int | None:
    """The American price paying `payout_multiple` per unit, via the registered `opportunity_signals.american_price`."""
    from syndicate.features.shared.opportunity_signals import american_price

    return american_price(1.0 / payout_multiple) if payout_multiple and payout_multiple > 1.0 else None


def rho_for(cells: Mapping[str, Any], type_a: str, type_b: str, relation: str) -> tuple[float, str]:
    """The shrunk correlation for (over_a, over_b): the role cell, else the market cell, else 0."""
    (ta, tb) = sorted((type_a, type_b))
    by = cells.get("cells") or {}
    hit = (by.get("type") or {}).get(f"{ta}~{tb}~{relation}")
    if hit is not None:
        return float(hit["rho"]), "role"
    ma, mb = ta.split("|")[0], tb.split("|")[0]
    hit = (by.get("market") or {}).get(f"{ma}~{mb}~{relation}")
    if hit is not None:
        return float(hit["rho"]), "market"
    return 0.0, "none"


def _over_prob(row: Mapping[str, Any]) -> float | None:
    """P(over) (Anytime TD: P(scores)) at the row's line, from the de-vigged consensus the sheet already carries."""
    p = (row.get("check") or {}).get("p_market")
    try:
        p = float(p)
    except (TypeError, ValueError):
        return None
    if not 0.01 < p < 0.99:
        return None
    return 1.0 - p if str(row.get("side") or "").lower() == "under" else p


# The sheet's team codes (ESPN) against nflverse's (the play-by-play the roles come from).
_TEAM_TO_PBP = {"LAR": "LA", "WSH": "WAS", "JAC": "JAX", "LVR": "LV", "OAK": "LV", "SD": "LAC", "STL": "LA"}


def _leg(row: Mapping[str, Any], roles: Mapping[tuple[str, tuple[str, str]], str]) -> dict[str, Any] | None:
    market = row.get("market")
    if market not in MARKETS:
        return None
    po = _over_prob(row)
    if po is None:
        return None
    key = name_key(row.get("player"))
    team = str(row.get("team") or "").upper()
    role = roles.get((_TEAM_TO_PBP.get(team, team), key), "UNK") if key else "UNK"
    side = str(row.get("side") or "").lower()
    return {"player": row.get("player"), "team": row.get("team"), "market": market, "side": side, "line": row.get("line"),
            "p_over": po, "p_side": po if side in ("over", "yes") else 1.0 - po, "type": f"{market}|{role}",
            "role": role, "prices": dict(row.get("book_prices") or {}), "event_id": row.get("event_id"),
            "pos": row.get("pos"), "headshot_card_src": row.get("headshot_card_src"),
            "headshot_src": row.get("headshot_src"), "headshot_url": row.get("headshot_url"),
            "team_logo": row.get("team_logo"), "team_logo_src": row.get("team_logo_src")}


def joint_prob(a: Mapping[str, Any], b: Mapping[str, Any], rho: float) -> float:
    """P(both legs win) at their chosen sides."""
    oo = float(joint_over(a["p_over"], b["p_over"], rho))
    a_over, b_over = a["side"] in ("over", "yes"), b["side"] in ("over", "yes")
    if a_over and b_over:
        return oo
    if a_over:
        return a["p_over"] - oo
    if b_over:
        return b["p_over"] - oo
    return 1.0 - a["p_over"] - b["p_over"] + oo


def _bet_text(leg: Mapping[str, Any]) -> str:
    if leg["market"] == "Anytime TD":
        return f"{leg['player']} anytime TD"
    line = leg.get("line")
    line_txt = f"{line:g}" if isinstance(line, (int, float)) else str(line)
    return f"{leg['player']} {leg['side'].title()} {line_txt} {leg['market'].lower()}"


def _candidate(row: Mapping[str, Any]) -> bool:
    """A leg we would take on its own: the sheet suggests it, or its best price beats the de-vigged consensus.
    (Measured 2026-10-15, one TNF game: 2 suggested rows and 5 with a positive best-price EV of 163 -- suggested
    alone leaves a one-game sheet with one possible pair.)"""
    if row.get("suggested"):
        return True
    try:
        return float((row.get("check") or {}).get("ev_market")) > 0
    except (TypeError, ValueError):
        return False


def suggest(sheet: Mapping[str, Any], cells: Mapping[str, Any] | None,
            roles: Mapping[tuple[str, tuple[str, str]], str], *, per_game: int = PER_GAME,
            per_sheet: int = PER_SHEET) -> list[dict[str, Any]]:
    """Two-leg SGPs from legs we would take on their own (`_candidate`): same game, different bets, measured correlation that makes
    the pair win together more often than apart (lift >= MIN_LIFT), quoted by one book on both legs (an SGP is
    one book's ticket). Ranked by the estimate at the assumed discount -- a ranking, not an edge claim."""
    if not cells:
        return []
    legs_by_game: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    seen = set()
    for row in sheet.get("rows") or []:
        if not _candidate(row):
            continue
        leg = _leg(row, roles)
        if leg is None:
            continue
        ident = (leg["event_id"], leg["player"], leg["market"])
        if ident in seen:                        # one side per player x market on a ticket
            continue
        seen.add(ident)
        legs_by_game[str(leg["event_id"])].append(leg)
    games = {str(g.get("event_id")): g for g in sheet.get("games") or []}
    out: list[dict[str, Any]] = []
    for event_id, legs in legs_by_game.items():
        cands = []
        for i in range(len(legs)):
            for j in range(i + 1, len(legs)):
                a, b = legs[i], legs[j]
                same_player = a["player"] == b["player"]
                relation = "same_player" if same_player else ("teammate" if a["team"] == b["team"] else "opponent")
                rho, level = rho_for(cells, a["type"], b["type"], relation)
                if level == "none" or rho == 0.0:
                    continue
                pj = joint_prob(a, b, rho)
                indep = a["p_side"] * b["p_side"]
                if pj <= 0 or indep <= 0 or pj / indep < MIN_LIFT:
                    continue
                books = [bk for bk in a["prices"] if bk in b["prices"]]
                best = None
                for bk in books:
                    da, db = payout(a["prices"][bk]), payout(b["prices"][bk])
                    if da and db and (best is None or da * db > best[1]):
                        best = (bk, da * db)
                if best is None:
                    continue
                book, product = best
                fair_dec = 1.0 / pj
                est_dec = product * (1.0 - ASSUMED_BOOK_DISCOUNT)
                ticket = sorted([_bet_text(a), _bet_text(b)])
                sgp_id = "sgp_" + hashlib.sha1(f"{event_id}|{'|'.join(ticket)}".encode()).hexdigest()[:12]
                cands.append({
                    "sgp_id": sgp_id, "event_id": event_id, "legs": [dict(a, bet=_bet_text(a)), dict(b, bet=_bet_text(b))],
                    "relation": relation, "same_player": same_player, "rho": round(rho, 3), "rho_level": level,
                    "p_joint": round(pj, 4), "p_independent": round(indep, 4), "lift": round(pj / indep, 3),
                    "fair_odds": odds_at(fair_dec),
                    "worth_it_odds": odds_at(fair_dec * (1.0 + WORTH_IT_CUSHION)),
                    "book": book, "legs_product_odds": odds_at(product),
                    "assumed_discount": ASSUMED_BOOK_DISCOUNT, "est_book_odds": odds_at(est_dec),
                    "est_ev_pct": round((pj * est_dec - 1.0) * 100.0, 1),
                    "matchup": (games.get(event_id) or {}).get("matchup"),
                    "commence_time": (games.get(event_id) or {}).get("commence_time"),
                    "kickoff_ct": (games.get(event_id) or {}).get("kickoff_ct"),
                })
        # Different players before a second leg from the same player: a same-player pair is the one books price
        # tightest, so it never outranks a cross-player pair at an equal estimate.
        cands.sort(key=lambda c: (-c["est_ev_pct"] + (5.0 if c["same_player"] else 0.0)))
        out += cands[:per_game]
    out.sort(key=lambda c: -c["est_ev_pct"] + (5.0 if c["same_player"] else 0.0))
    return out[:per_sheet]


def merge_record(fresh: list[dict[str, Any]], prior: Iterable[Mapping[str, Any]] | None, *,
                 started: set[str]) -> list[dict[str, Any]]:
    """A day's SGPs are a RECORD like its picks: a game that has started keeps the parlays it had (at their
    probabilities and prices then); a game still to come shows this build's."""
    kept = [dict(s) for s in prior or [] if str(s.get("event_id")) in started]
    return kept + [s for s in fresh if str(s.get("event_id")) not in started]


def append_ledger(path: Path, records: Iterable[Mapping[str, Any]]) -> int:
    """Append each SGP once (its first appearance is its record); returns how many were new."""
    seen = set()
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                seen.add(json.loads(line).get("sgp_id"))
            except ValueError:
                continue
    new = [r for r in records if r.get("sgp_id") not in seen]
    if new:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            for r in new:
                fh.write(json.dumps(r) + "\n")
    return len(new)


def ledger_records(sgps: Iterable[Mapping[str, Any]], *, day: str, generated_at: str) -> list[dict[str, Any]]:
    """The paper record: what we said, at what probability and prices, before the game. Graded later on outcomes."""
    keep = ("sgp_id", "event_id", "relation", "same_player", "rho", "rho_level", "p_joint", "p_independent", "lift",
            "fair_odds", "worth_it_odds", "book", "legs_product_odds", "assumed_discount", "est_book_odds",
            "est_ev_pct", "matchup")
    return [{"date": day, "promoted_at": generated_at, **{k: s.get(k) for k in keep},
             "legs": [{k: leg.get(k) for k in ("player", "team", "market", "side", "line", "p_over", "role", "bet")}
                      for leg in s.get("legs") or []]}
            for s in sgps]
