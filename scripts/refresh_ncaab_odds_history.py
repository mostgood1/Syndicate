from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared.refresh_state_store import build_input_hash
from syndicate.features.shared.refresh_state_store import record_refresh_state
from syndicate.features.shared.refresh_state_store import should_recompute
from syndicate.features.shared.oddsapi_quota import record_oddsapi_quota


ENV_API_KEY_NAMES = (
    "NCAAB_THEODDS_API_KEY",
    "THEODDSAPI_KEY",
    "THEODDS_API_KEY",
)


class _OddsApiRequestError(RuntimeError):
    def __init__(self, *, context: str, status_code: int, reason: str = "") -> None:
        self.context = context
        self.status_code = int(status_code)
        self.reason = reason
        suffix = f" {reason}" if reason else ""
        super().__init__(f"TheOddsAPI {context} failed (HTTP {status_code}{suffix})")


def _trim_api_key(value: str | None) -> str:
    raw = str(value or "").strip()
    if "|" in raw:
        raw = raw.split("|", 1)[0].strip()
    return raw


def _load_api_key(explicit_key: str | None = None) -> str:
    api_key = _trim_api_key(explicit_key)
    if api_key:
        return api_key
    for env_name in ENV_API_KEY_NAMES:
        api_key = _trim_api_key(os.environ.get(env_name))
        if api_key:
            return api_key
    raise ValueError("TheOddsAPI key not set. Provide NCAAB_THEODDS_API_KEY or pass --api-key.")


def _coerce_datetime(value: object) -> dt.datetime | None:
    if isinstance(value, dt.datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=dt.timezone.utc)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=dt.timezone.utc)


def _row_to_dict(row: object) -> dict:
    if isinstance(row, dict):
        return dict(row)
    model_dump = getattr(row, "model_dump", None)
    if callable(model_dump):
        return dict(model_dump())
    raise TypeError(f"Unsupported odds row type: {type(row)!r}")


class TheOddsApiClient:
    def __init__(self, *, region: str = "us", api_key: str | None = None, sport_key: str = "basketball_ncaab") -> None:
        self.api_key = _load_api_key(api_key)
        self.region = str(region or "us")
        self.sport_key = sport_key

    def _request_json(
        self,
        path: str,
        *,
        params: dict[str, object],
        context: str,
        timeout: int,
        ignore_statuses: tuple[int, ...] = (),
    ) -> object | None:
        query = urllib.parse.urlencode({**params, "apiKey": self.api_key}, doseq=True)
        url = f"https://api.the-odds-api.com/v4/sports/{self.sport_key}{path}?{query}"
        request = urllib.request.Request(url, headers={"Accept": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = response.read().decode("utf-8")
                # Full url: the recorder redacts apiKey before persisting, and
                # attribution needs the markets= in the query.
                record_oddsapi_quota(response.headers, sport="ncaab", endpoint=url)
        except urllib.error.HTTPError as exc:
            status_code = int(getattr(exc, "code", 0) or 0)
            if status_code in ignore_statuses:
                return None
            raise _OddsApiRequestError(
                context=context,
                status_code=status_code,
                reason=str(getattr(exc, "reason", "") or ""),
            ) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"TheOddsAPI {context} failed ({exc.reason})") from exc
        try:
            return json.loads(payload)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"TheOddsAPI {context} returned invalid JSON") from exc

    @staticmethod
    def _infer_period_from_key(market_key: str) -> str:
        key = str(market_key or "").lower().strip()
        if any(tok in key for tok in ("_1st_half", "1st_half", "first_half", "_1h", "1h_")):
            return "1h"
        if any(tok in key for tok in ("_2nd_half", "2nd_half", "second_half", "_2h", "2h_")):
            return "2h"
        if key in {"h2h", "spreads", "totals"}:
            return "full_game"
        if "first_half" in key or "1st_half" in key or "1h" in key:
            return "1h"
        if "second_half" in key or "2nd_half" in key or "2h" in key:
            return "2h"
        return "full_game"

    def _normalize_market_rows(
        self,
        event: dict,
        book: dict,
        market: dict,
        fetched_at: dt.datetime,
    ) -> list[dict]:
        event_id = str(event.get("id") or "")
        commence = _coerce_datetime(event.get("commence_time"))
        home_team = event.get("home_team") or None
        away_team = event.get("away_team") or None
        book_title = book.get("title") or "unknown"
        market_key = str(market.get("key") or "").lower()
        period = self._infer_period_from_key(market_key)
        last_update = _coerce_datetime(market.get("last_update") or book.get("last_update"))
        outcomes = market.get("outcomes") or []
        base_row = {
            "event_id": event_id,
            "book": book_title,
            "fetched_at": fetched_at,
            "last_update": last_update,
            "commence_time": commence,
            "home_team_name": home_team,
            "away_team_name": away_team,
            "market": "",
            "period": period,
        }
        if "h2h" in market_key:
            moneyline_home = None
            moneyline_away = None
            for outcome in outcomes:
                name = outcome.get("name") or outcome.get("team")
                price = outcome.get("price") or outcome.get("odds")
                try:
                    if name == home_team and price is not None:
                        moneyline_home = float(price)
                    elif name == away_team and price is not None:
                        moneyline_away = float(price)
                except Exception:
                    continue
            return [{**base_row, "market": "h2h", "moneyline_home": moneyline_home, "moneyline_away": moneyline_away}]
        if "spreads" in market_key:
            home_spread = None
            home_spread_price = None
            away_spread = None
            away_spread_price = None
            for outcome in outcomes:
                name = outcome.get("name") or outcome.get("team")
                point = outcome.get("point")
                price = outcome.get("price") or outcome.get("odds")
                try:
                    if name == home_team:
                        if point is not None:
                            home_spread = float(point)
                        if price is not None:
                            home_spread_price = float(price)
                    elif name == away_team:
                        if point is not None:
                            away_spread = float(point)
                        if price is not None:
                            away_spread_price = float(price)
                except Exception:
                    continue
            return [{
                **base_row,
                "market": "spreads",
                "home_spread": home_spread,
                "home_spread_price": home_spread_price,
                "away_spread": away_spread,
                "away_spread_price": away_spread_price,
            }]
        if "totals" in market_key:
            total = None
            over_price = None
            under_price = None
            for outcome in outcomes:
                point = outcome.get("point")
                name = str(outcome.get("name") or outcome.get("label") or "").lower()
                price = outcome.get("price") or outcome.get("odds")
                try:
                    if point is not None:
                        total = float(point)
                    if "over" in name and price is not None:
                        over_price = float(price)
                    if "under" in name and price is not None:
                        under_price = float(price)
                except Exception:
                    continue
            return [{
                **base_row,
                "market": "totals",
                "total": total,
                "over_price": over_price,
                "under_price": under_price,
            }]
        return []

    def list_events_by_date(self, date_iso: str) -> list[dict]:
        payload = self._request_json(
            "/events",
            params={
                "dateFormat": "iso",
                "commenceTimeFrom": f"{date_iso}T00:00:00Z",
                "commenceTimeTo": f"{date_iso}T23:59:59Z",
            },
            context="events",
            timeout=20,
        )
        return list(payload or []) if isinstance(payload, list) else []

    def iter_current_odds_expanded(self, *, markets: str, date_iso: str | None, bookmakers: str | None = None):
        params = {
            "regions": self.region,
            "markets": markets,
            "oddsFormat": "american",
            "dateFormat": "iso",
        }
        if bookmakers:
            params["bookmakers"] = bookmakers
        if date_iso:
            params["date"] = date_iso
        try:
            payload = self._request_json("/odds", params=params, context="odds", timeout=30)
        except _OddsApiRequestError as exc:
            if exc.status_code not in {400, 422}:
                raise
            retry_params = dict(params)
            retry_params.pop("date", None)
            try:
                payload = self._request_json("/odds", params=retry_params, context="odds", timeout=30)
            except _OddsApiRequestError as retry_exc:
                if retry_exc.status_code not in {400, 422}:
                    raise
                retry_params["markets"] = "h2h,spreads,totals"
                payload = self._request_json("/odds", params=retry_params, context="odds", timeout=30)
        fetched_at = dt.datetime.now(dt.timezone.utc)
        for event in payload or []:
            if not isinstance(event, dict):
                continue
            for book in event.get("bookmakers") or []:
                if not isinstance(book, dict):
                    continue
                for market in book.get("markets") or []:
                    if not isinstance(market, dict):
                        continue
                    for row in self._normalize_market_rows(event, book, market, fetched_at):
                        yield row

    def get_event_odds(self, event_id: str, *, markets: str, bookmakers: str | None = None) -> dict:
        event_key = str(event_id or "").strip()
        if not event_key:
            return {}
        params = {
            "regions": self.region,
            "markets": markets,
            "oddsFormat": "american",
            "dateFormat": "iso",
        }
        if bookmakers:
            params["bookmakers"] = bookmakers
        try:
            payload = self._request_json(
                f"/events/{event_key}/odds",
                params=params,
                context="event_odds",
                timeout=30,
            )
        except _OddsApiRequestError as exc:
            if exc.status_code not in {400, 422}:
                raise
            params["markets"] = "h2h,spreads,totals"
            payload = self._request_json(
                f"/events/{event_key}/odds",
                params=params,
                context="event_odds",
                timeout=30,
            )
        if isinstance(payload, dict):
            return payload
        if isinstance(payload, list) and payload and isinstance(payload[0], dict):
            return payload[0]
        return {}

    def iter_event_odds(self, event_id: str, *, markets: str, bookmakers: str | None = None):
        event = self.get_event_odds(event_id, markets=markets, bookmakers=bookmakers)
        if not isinstance(event, dict) or not event:
            return
        fetched_at = dt.datetime.now(dt.timezone.utc)
        for book in event.get("bookmakers") or []:
            if not isinstance(book, dict):
                continue
            for market in book.get("markets") or []:
                if not isinstance(market, dict):
                    continue
                for row in self._normalize_market_rows(event, book, market, fetched_at):
                    yield row

    def iter_odds_history_for_events(self, event_ids: list[str], *, markets: str, bookmakers: str | None = None):
        fetched_at = dt.datetime.now(dt.timezone.utc)
        for event_id in event_ids:
            event_key = str(event_id or "").strip()
            if not event_key:
                continue
            params = {
                "regions": self.region,
                "markets": markets,
                "oddsFormat": "american",
                "dateFormat": "iso",
            }
            if bookmakers:
                params["bookmakers"] = bookmakers
            payload = self._request_json(
                f"/events/{event_key}/odds-history",
                params=params,
                context="odds_history",
                timeout=45,
                ignore_statuses=(401, 403, 404, 422),
            )
            if payload is None:
                continue
            if isinstance(payload, list):
                payload = payload[0] if payload and isinstance(payload[0], dict) else {}
            if not isinstance(payload, dict) or not payload:
                continue
            for book in payload.get("bookmakers") or []:
                if not isinstance(book, dict):
                    continue
                for market in book.get("markets") or []:
                    if not isinstance(market, dict):
                        continue
                    for row in self._normalize_market_rows(payload, book, market, fetched_at):
                        yield row


def _load_source_adapter(source_root: Path | None = None):
    _ = source_root
    return TheOddsApiClient


def _target_timezone() -> ZoneInfo | dt.tzinfo:
    try:
        return ZoneInfo("America/Chicago")
    except Exception:
        return dt.timezone.utc


def _event_on_target_date(ct_raw: object, *, target_date: dt.date, tz: ZoneInfo) -> bool:
    if not ct_raw:
        return False
    try:
        if isinstance(ct_raw, str):
            dt_utc = dt.datetime.fromisoformat(ct_raw.replace("Z", "+00:00"))
        elif isinstance(ct_raw, dt.datetime):
            dt_utc = ct_raw
        else:
            return False
        if dt_utc.tzinfo is None:
            dt_utc = dt_utc.replace(tzinfo=dt.timezone.utc)
        return dt_utc.astimezone(tz).date() == target_date
    except Exception:
        return False


def _fetch_current_rows(*, adapter, date_iso: str, markets: str, bookmakers: str | None) -> list[dict]:
    mk_l = (markets or "").lower()
    wants_period = any(tok in mk_l for tok in ("_h1", "_h2", "1st_half", "2nd_half", "first_half", "second_half"))
    if not wants_period:
        return [_row_to_dict(row) for row in adapter.iter_current_odds_expanded(markets=markets, date_iso=date_iso, bookmakers=bookmakers)]

    tz = _target_timezone()
    target_date = dt.date.fromisoformat(date_iso)
    event_ids: set[str] = set()

    try:
        for event in adapter.list_events_by_date(date_iso) or []:
            event_id = str((event or {}).get("id") or "").strip()
            commence_time = (event or {}).get("commence_time")
            if event_id and _event_on_target_date(commence_time, target_date=target_date, tz=tz):
                event_ids.add(event_id)
    except Exception:
        pass

    try:
        for row in adapter.iter_current_odds_expanded(markets="h2h", date_iso=date_iso, bookmakers=bookmakers):
            event_id = str(getattr(row, "event_id", "") or "").strip()
            commence_time = getattr(row, "commence_time", None)
            if event_id and _event_on_target_date(commence_time, target_date=target_date, tz=tz):
                event_ids.add(event_id)
    except Exception:
        pass

    if event_ids:
        rows: list[dict] = []
        for event_id in sorted(event_ids):
            rows.extend(_row_to_dict(row) for row in adapter.iter_event_odds(event_id, markets=markets, bookmakers=bookmakers))
        if rows:
            return rows

    return [_row_to_dict(row) for row in adapter.iter_current_odds_expanded(markets=markets, date_iso=date_iso, bookmakers=bookmakers)]


def _discover_event_ids(*, adapter, date_iso: str) -> list[str]:
    tz = _target_timezone()
    target_date = dt.date.fromisoformat(date_iso)
    event_ids: set[str] = set()

    try:
        for event in adapter.list_events_by_date(date_iso) or []:
            event_id = str((event or {}).get("id") or "").strip()
            commence_time = (event or {}).get("commence_time")
            if event_id and _event_on_target_date(commence_time, target_date=target_date, tz=tz):
                event_ids.add(event_id)
    except Exception:
        pass

    try:
        for row in adapter.iter_current_odds_expanded(markets="h2h", date_iso=date_iso, bookmakers=None):
            event_id = str(getattr(row, "event_id", "") or "").strip()
            commence_time = getattr(row, "commence_time", None)
            if event_id and _event_on_target_date(commence_time, target_date=target_date, tz=tz):
                event_ids.add(event_id)
    except Exception:
        pass

    return sorted(event_ids)


def _fetch_history_rows(*, adapter, date_iso: str, markets: str, bookmakers: str | None) -> list[dict]:
    event_ids = _discover_event_ids(adapter=adapter, date_iso=date_iso)
    return [_row_to_dict(row) for row in adapter.iter_odds_history_for_events(event_ids, markets=markets, bookmakers=bookmakers)]


def _write_rows(out_path: Path, rows: list[dict]) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        raise RuntimeError(f"No odds rows returned for {out_path.stem}.")
    fieldnames: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row.keys():
            if key not in seen:
                seen.add(key)
                fieldnames.append(str(key))
    with out_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh NCAAB odds history through a Syndicate-owned runner.")
    parser.add_argument("--date", required=True)
    parser.add_argument("--source-root")
    parser.add_argument("--api-key")
    parser.add_argument("--region", default="us")
    parser.add_argument("--bookmakers")
    parser.add_argument("--markets", default="h2h,spreads,totals,spreads_h1,totals_h1,spreads_h2,totals_h2")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--mode", default="current", choices=("current", "history"))
    parser.add_argument("--refresh-mode", choices=("fast", "full"), default="full")
    args = parser.parse_args()

    source_root = Path(args.source_root).resolve() if args.source_root else None
    out_dir = Path(args.out_dir).resolve()
    date_iso = str(args.date).strip()
    TheOddsAPIAdapter = _load_source_adapter(source_root)
    try:
        adapter = TheOddsAPIAdapter(region=str(args.region or "us"), api_key=args.api_key)
    except TypeError:
        adapter = TheOddsAPIAdapter(region=str(args.region or "us"))

    if args.mode == "history":
        rows = _fetch_history_rows(adapter=adapter, date_iso=date_iso, markets=str(args.markets or ""), bookmakers=args.bookmakers)
    else:
        rows = _fetch_current_rows(adapter=adapter, date_iso=date_iso, markets=str(args.markets or ""), bookmakers=args.bookmakers)

    out_path = out_dir / f"odds_{date_iso}.csv"
    input_hash = build_input_hash(
        {
            "step": f"ncaab_odds_{args.mode}",
            "date": date_iso,
            "region": str(args.region or "us"),
            "bookmakers": str(args.bookmakers or ""),
            "markets": str(args.markets or ""),
            "rows": rows,
        }
    )
    if not should_recompute(f"ncaab_odds_{args.mode}:{date_iso}", input_hash) and out_path.exists():
        print(f"Reused {len(rows)} odds rows at {out_path}")
        return 0
    _write_rows(out_path, rows)
    record_refresh_state(
        f"ncaab_odds_{args.mode}:{date_iso}",
        input_hash,
        outputs=[str(out_path)],
        metadata={
            "date": date_iso,
            "mode": args.mode,
            "region": str(args.region or "us"),
            "bookmakers": str(args.bookmakers or ""),
            "markets": str(args.markets or ""),
            "rows": len(rows),
        },
    )
    print(f"Wrote {len(rows)} odds rows to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())