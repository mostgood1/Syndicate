from __future__ import annotations

from dataclasses import dataclass
from statistics import mean
from typing import Any, Protocol

from syndicate.features.football.artifacts import persist_football_artifacts
from syndicate.features.football.contracts import FootballSeasonEvaluation
from syndicate.features.football.contracts import FootballSimulationInput
from syndicate.features.football.contracts import FootballEvaluationRecord
from syndicate.features.football.contracts import FootballSimulationOutput
from syndicate.features.football.evaluation import persist_football_backtest_manifest
from syndicate.features.football.evaluation import persist_football_evaluation
from syndicate.features.football.features.loaders import build_historical_football_simulation_input
from syndicate.features.football.features.loaders import build_football_simulation_input
from syndicate.features.nfl.sources import available_weeks
from syndicate.features.nfl.sources import latest_season


class SportSimulationAdapter(Protocol):
    sport: str

    def load_features(self, *, date: str, selection: Any | None = None, season: int | None = None) -> FootballSimulationInput:
        ...

    def simulate_games(self, simulation_input: FootballSimulationInput) -> FootballSimulationOutput:
        ...

    def simulate_props(self, simulation_input: FootballSimulationInput) -> FootballSimulationOutput:
        ...

    def build_artifacts(self, simulation_output: FootballSimulationOutput) -> dict[str, Any]:
        ...

    def evaluate(self, simulation_output: FootballSimulationOutput) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class FootballSimulationAdapter:
    sport: str

    def _normalize_usage_value(self, value: Any) -> float | None:
        try:
            if value is None or str(value).strip() == "":
                return None
            normalized = float(value)
        except Exception:
            return None
        return max(0.0, min(1.0, normalized))

    def _combined_player_usage_index(self, usage_metrics: dict[str, Any]) -> tuple[float, float]:
        weighted_fields = (
            ("snap_share", 0.25),
            ("target_share", 0.25),
            ("route_participation", 0.25),
            ("air_yard_share", 0.25),
        )
        weighted_sum = 0.0
        observed_weight_sum = 0.0
        observed_field_count = 0
        for key, weight in weighted_fields:
            normalized_value = self._normalize_usage_value(usage_metrics.get(key))
            if normalized_value is None:
                continue
            weighted_sum += normalized_value * weight
            observed_weight_sum += weight
            observed_field_count += 1
        if observed_weight_sum > 0.0:
            usage_index = weighted_sum / observed_weight_sum
        else:
            usage_index = 0.0
        usage_confidence = observed_field_count / 4.0
        return usage_index * usage_confidence, usage_confidence

    def _team_player_usage(self, simulation_input: FootballSimulationInput, team_abbr: str) -> dict[str, float]:
        team = str(team_abbr or "").upper().strip()
        if not team:
            return {"snap_share": 0.0, "target_share": 0.0, "route_participation": 0.0, "air_yard_share": 0.0}
        players = [player for player in simulation_input.players if str(getattr(player, "team", "") or "").upper().strip() == team]
        if not players:
            return {"snap_share": 0.0, "target_share": 0.0, "route_participation": 0.0, "air_yard_share": 0.0}

        def _mean_for(keys: tuple[str, ...]) -> float:
            values: list[float] = []
            for player in players:
                usage_metrics = dict(getattr(player, "usage_metrics", {}) or {})
                for key in keys:
                    value = usage_metrics.get(key)
                    try:
                        if value is None or str(value).strip() == "":
                            continue
                        values.append(float(value))
                        break
                    except Exception:
                        continue
            return round(mean(values), 4) if values else 0.0

        return {
            "snap_share": _mean_for(("snap_share", "snap_pct", "snap_rate", "snaps_share")),
            "target_share": _mean_for(("target_share", "targets_share", "target_pct")),
            "route_participation": _mean_for(("route_participation", "route_pct", "routes_share", "wopr")),
            "air_yard_share": _mean_for(("air_yard_share", "air_yards_share", "air_yards_pct")),
        }

    def _base_point_projection(self, simulation_input: FootballSimulationInput) -> float:
        game_count = len(simulation_input.games)
        return 20.0 + (game_count * 1.5)

    def _game_projection(self, game: Any, *, index: int, simulation_input: FootballSimulationInput) -> dict[str, Any]:
        game_metrics = dict(getattr(game, "team_metrics", {}) or {})
        pace_metrics = dict(getattr(game, "pace_features", {}) or {})
        market_features = dict(getattr(game, "market_features", {}) or {})
        home_team = str(getattr(game, "home_team", "") or "").upper().strip()
        away_team = str(getattr(game, "away_team", "") or "").upper().strip()
        market_total = market_features.get("total", {}).get("line") if isinstance(market_features.get("total"), dict) else None
        market_spread = market_features.get("spread", {}).get("home_line") if isinstance(market_features.get("spread"), dict) else None
        home_offensive = float(game_metrics.get("home_offensive_epa") or game_metrics.get("offensive_epa") or game_metrics.get("epa_play") or 0.0)
        away_offensive = float(game_metrics.get("away_offensive_epa") or 0.0)
        home_defensive = float(game_metrics.get("home_defensive_epa") or game_metrics.get("defensive_epa") or game_metrics.get("epa_allowed") or 0.0)
        away_defensive = float(game_metrics.get("away_defensive_epa") or 0.0)
        epa_component = (home_offensive - away_offensive) + (away_defensive - home_defensive)
        success_component = (
            float(game_metrics.get("home_success_rate") or game_metrics.get("success_rate") or 0.0)
            - float(game_metrics.get("away_success_rate") or 0.0)
            + float(game_metrics.get("away_success_rate_allowed") or 0.0)
            - float(game_metrics.get("home_success_rate_allowed") or 0.0)
        )
        proe_component = (
            float(game_metrics.get("pass_rate_over_expectation") or game_metrics.get("proe") or 0.0)
            + float(game_metrics.get("home_pass_rate") or 0.0)
            - float(game_metrics.get("away_pass_rate") or 0.0)
        )
        red_zone_component = float(game_metrics.get("home_red_zone_efficiency") or game_metrics.get("red_zone_efficiency") or 0.0) - float(game_metrics.get("away_red_zone_efficiency") or 0.0)
        explosive_component = float(game_metrics.get("home_explosive_pass_rate") or game_metrics.get("explosive_play_rate") or 0.0) - float(game_metrics.get("away_explosive_pass_rate") or 0.0)
        home_usage = self._team_player_usage(simulation_input, home_team)
        away_usage = self._team_player_usage(simulation_input, away_team)
        usage_component = (
            (home_usage["snap_share"] - away_usage["snap_share"]) * 1.5
            + (home_usage["target_share"] - away_usage["target_share"]) * 1.8
            + (home_usage["route_participation"] - away_usage["route_participation"]) * 1.2
            + (home_usage["air_yard_share"] - away_usage["air_yard_share"]) * 1.1
        )
        pace_value = float(pace_metrics.get("pace") or pace_metrics.get("possessions") or 0.0)
        base_total = float(market_total) if market_total is not None else self._base_point_projection(simulation_input)
        base_margin = float(market_spread) if market_spread is not None else 0.0
        total_projection = base_total + (epa_component * 4.5) + (success_component * 8.0) + (proe_component * 3.0) + (red_zone_component * 3.5) + (explosive_component * 3.0) + (usage_component * 5.0) + (pace_value * 0.05)
        margin_projection = base_margin + (epa_component * 4.0) + (success_component * 6.0) + (proe_component * 2.5) + (red_zone_component * 2.5) + (explosive_component * 2.0) + (usage_component * 4.0)
        home_projection = round((total_projection + margin_projection) / 2.0, 2)
        away_projection = round(total_projection - home_projection, 2)
        margin_projection = round(home_projection - away_projection, 2)
        home_win_probability = max(0.05, min(0.95, 0.5 + (margin_projection / 28.0)))
        away_win_probability = round(1.0 - home_win_probability, 4)
        score_distribution = {
            "home_mean": home_projection,
            "away_mean": away_projection,
            "total_mean": round(home_projection + away_projection, 2),
            "margin_mean": margin_projection,
            "home_win_probability": round(home_win_probability, 4),
            "away_win_probability": away_win_probability,
        }
        return {
            "game_id": getattr(game, "game_id", ""),
            "sport": simulation_input.sport,
            "date": simulation_input.date,
            "index": index,
            "team_projection": score_distribution,
            "spread_distribution": {
                "home": round(margin_projection, 2),
                "away": round(-margin_projection, 2),
            },
            "total_distribution": {
                "line": round(total_projection, 2),
                "mean": round(total_projection, 2),
            },
            "win_probability": {
                "home": round(home_win_probability, 4),
                "away": away_win_probability,
            },
            "matchup": {
                "home_team": getattr(game, "home_team", ""),
                "away_team": getattr(game, "away_team", ""),
            },
            "adapter_metadata": dict(getattr(game, "adapter_metadata", {}) or {}),
        }

    def _player_projection(self, player: Any, *, index: int, simulation_input: FootballSimulationInput) -> dict[str, Any]:
        usage_metrics = dict(getattr(player, "usage_metrics", {}) or {})
        position = str(getattr(player, "position", "") or "").upper()
        usage_value, usage_confidence = self._combined_player_usage_index(usage_metrics)
        base_mean = 1.0 + (usage_value * 10.0)
        if position == "QB":
            stat_line = {
                "attempts_mean": round(24.0 + usage_value * 12.0, 2),
                "completions_mean": round(15.0 + usage_value * 8.0, 2),
                "passing_yards_mean": round(185.0 + usage_value * 120.0, 2),
                "passing_tds_mean": round(1.3 + usage_value * 1.6, 2),
                "interceptions_mean": round(max(0.2, 1.1 - usage_value), 2),
            }
        elif position == "RB":
            stat_line = {
                "carries_mean": round(10.0 + usage_value * 14.0, 2),
                "rushing_yards_mean": round(45.0 + usage_value * 110.0, 2),
                "rushing_tds_mean": round(0.4 + usage_value * 1.0, 2),
            }
        else:
            stat_line = {
                "targets_mean": round(4.0 + usage_value * 9.0, 2),
                "receptions_mean": round(3.0 + usage_value * 6.0, 2),
                "receiving_yards_mean": round(35.0 + usage_value * 100.0, 2),
                "receiving_tds_mean": round(0.3 + usage_value * 0.9, 2),
            }
        stat_line["projection_mean"] = round(base_mean + usage_value * 8.0, 2)
        return {
            "player_id": getattr(player, "player_id", ""),
            "player_name": getattr(player, "player_name", ""),
            "team": getattr(player, "team", ""),
            "position": position,
            "index": index,
            "projection": stat_line,
            "usage_metrics": usage_metrics,
            "usage_index": round(usage_value, 4),
            "usage_confidence": round(usage_confidence, 4),
            "market_features": dict(getattr(player, "market_features", {}) or {}),
            "adapter_metadata": dict(getattr(player, "adapter_metadata", {}) or {}),
            "sport": simulation_input.sport,
            "date": simulation_input.date,
        }

    def load_features(self, *, date: str, selection: Any | None = None, season: int | None = None) -> FootballSimulationInput:
        if self.sport == "nfl":
            requested_season = int(season) if season is not None else None
            if requested_season is not None and available_weeks(requested_season):
                historical_input = build_historical_football_simulation_input(sport=self.sport, date=date, season=requested_season)
                if historical_input.games:
                    return historical_input

            from syndicate.features.nfl.cards import build_cards_page_context

            resolved_season = requested_season if requested_season is not None and available_weeks(requested_season) else latest_season()
            resolved_week = int(selection or 1)
            if not available_weeks(resolved_season):
                resolved_season = latest_season()
            context = build_cards_page_context(resolved_week, season=resolved_season)
            return build_football_simulation_input(
                sport=self.sport,
                date=date,
                games=list(context.get("games") or []),
                season=resolved_season,
                selection=resolved_week,
            )
        if self.sport == "ncaaf":
            from syndicate.features.ncaaf.cards import build_cards_page_context

            context = build_cards_page_context(int(selection or 1))
            return build_football_simulation_input(
                sport=self.sport,
                date=date,
                games=list(context.get("games") or []),
                season=season,
                selection=selection,
            )
        return FootballSimulationInput(sport=self.sport, date=date, adapter_metadata={"source": "fallback_empty"})

    def simulate_games(self, simulation_input: FootballSimulationInput) -> FootballSimulationOutput:
        game_outputs = tuple(
            self._game_projection(game, index=index, simulation_input=simulation_input)
            for index, game in enumerate(simulation_input.games)
        )
        player_outputs = tuple(
            self._player_projection(player, index=index, simulation_input=simulation_input)
            for index, player in enumerate(simulation_input.players)
        )
        win_probability = game_outputs[0].get("win_probability") if game_outputs else {"home": None, "away": None}
        expected_spread = game_outputs[0].get("spread_distribution") if game_outputs else {}
        expected_total = game_outputs[0].get("total_distribution") if game_outputs else {}
        distribution_summary = {
            "games": len(game_outputs),
            "players": len(player_outputs),
            "has_game_outputs": bool(game_outputs),
            "has_player_outputs": bool(player_outputs),
        }
        return FootballSimulationOutput(
            sport=simulation_input.sport,
            date=simulation_input.date,
            win_probability=win_probability if isinstance(win_probability, dict) else {},
            expected_spread=expected_spread if isinstance(expected_spread, dict) else {},
            expected_total=expected_total if isinstance(expected_total, dict) else {},
            confidence=round(0.55 + (0.05 if game_outputs else 0.0), 3),
            distribution_summary=distribution_summary,
            game_outputs=game_outputs,
            player_outputs=player_outputs,
            artifacts={
                "game_count": len(game_outputs),
                "player_count": len(player_outputs),
            },
            evaluation={
                "calibration": {
                    "win_probability": {"brier": 0.0 if not game_outputs else round(1.0 / max(len(game_outputs), 1), 4)},
                    "total": {"mae": 0.0},
                    "spread": {"mae": 0.0},
                    "props": {"mae": 0.0},
                }
            },
            adapter_metadata=dict(simulation_input.adapter_metadata or {}),
        )

    def simulate_props(self, simulation_input: FootballSimulationInput) -> FootballSimulationOutput:
        return self.simulate_games(simulation_input)

    def build_artifacts(self, simulation_output: FootballSimulationOutput) -> dict[str, Any]:
        game_outputs = list(simulation_output.game_outputs)
        player_outputs = list(simulation_output.player_outputs)
        top_props = []
        for player_output in player_outputs[:5]:
            projection = dict(player_output.get("projection") or {})
            top_props.append(
                {
                    "player_name": player_output.get("player_name"),
                    "team": player_output.get("team"),
                    "position": player_output.get("position"),
                    "projection_mean": projection.get("projection_mean"),
                    "market_features": dict(player_output.get("market_features") or {}),
                }
            )
        daily_summary = {
            "sport": simulation_output.sport,
            "date": simulation_output.date,
            "game_count": len(game_outputs),
            "player_count": len(player_outputs),
            "games": game_outputs,
        }
        profile_bundle = {
            "sport": simulation_output.sport,
            "date": simulation_output.date,
            "games": game_outputs,
            "players": player_outputs,
        }
        return {
            "sport": simulation_output.sport,
            "date": simulation_output.date,
            "daily_summary": daily_summary,
            "profile_bundle": profile_bundle,
            "locked_policy_card": {
                "sport": simulation_output.sport,
                "date": simulation_output.date,
                "game_count": len(game_outputs),
                "player_count": len(player_outputs),
                "status": "locked",
            },
            "top_props": {
                "sport": simulation_output.sport,
                "date": simulation_output.date,
                "rows": top_props,
            },
            "ladders": {
                "sport": simulation_output.sport,
                "date": simulation_output.date,
                "rows": top_props,
            },
            "season_manifest": {
                "sport": simulation_output.sport,
                "date": simulation_output.date,
                "game_count": len(game_outputs),
                "player_count": len(player_outputs),
            },
        }

    def persist_artifacts(self, simulation_output: FootballSimulationOutput) -> dict[str, str]:
        artifacts = self.build_artifacts(simulation_output)
        return persist_football_artifacts(sport=simulation_output.sport, date=simulation_output.date, artifacts=artifacts)

    def persist_evaluation(self, simulation_output: FootballSimulationOutput, *, season: int | None = None) -> dict[str, str]:
        evaluation = self.evaluate(simulation_output)
        if season is None:
            season = int((simulation_output.adapter_metadata or {}).get("season") or 0) or 0
        persisted = persist_football_evaluation(
            sport=simulation_output.sport,
            season=season,
            date=simulation_output.date,
            evaluation=evaluation,
        )
        season_manifest = persist_football_backtest_manifest(
            sport=simulation_output.sport,
            season=season,
            evaluation_records=[
                {
                    "sport": evaluation.get("sport"),
                    "date": evaluation.get("date"),
                    "brier": evaluation.get("brier"),
                    "roi": evaluation.get("roi"),
                    "clv": evaluation.get("clv"),
                    "win_rate": evaluation.get("win_rate"),
                    "sim_vs_actual": evaluation.get("sim_vs_actual"),
                    "calibration": evaluation.get("calibration"),
                }
            ],
        )
        persisted["backtest_manifest"] = season_manifest
        return persisted

    def evaluate(self, simulation_output: FootballSimulationOutput) -> dict[str, Any]:
        game_count = len(simulation_output.game_outputs)
        player_count = len(simulation_output.player_outputs)
        evaluation_record = FootballEvaluationRecord(
            sport=simulation_output.sport,
            season=None,
            date=simulation_output.date,
            simulation_kind="game_and_props",
            calibration=dict(simulation_output.evaluation.get("calibration") or {}),
            sim_vs_actual={"game_count": game_count, "player_count": player_count},
            prop_accuracy={"player_count": player_count},
            brier=0.0 if game_count else None,
            roi=0.0,
            clv=0.0,
            win_rate=0.0 if game_count else None,
            adapter_metadata=dict(simulation_output.adapter_metadata or {}),
        )
        season_evaluation = FootballSeasonEvaluation(
            sport=simulation_output.sport,
            season=int((simulation_output.adapter_metadata or {}).get("season") or 0) or 0,
            records=(evaluation_record,),
            sim_vs_actual={"game_count": game_count, "player_count": player_count},
            calibration=dict(simulation_output.evaluation.get("calibration") or {}),
            brier=evaluation_record.brier,
            roi=evaluation_record.roi,
            clv=evaluation_record.clv,
            win_rate=evaluation_record.win_rate,
            adapter_metadata=dict(simulation_output.adapter_metadata or {}),
        )
        return {
            "sport": simulation_output.sport,
            "date": simulation_output.date,
            "calibration": dict(simulation_output.evaluation.get("calibration") or {}),
            "sim_vs_actual": {"game_count": game_count, "player_count": player_count},
            "prop_accuracy": {"player_count": player_count},
            "brier": evaluation_record.brier,
            "roi": evaluation_record.roi,
            "clv": evaluation_record.clv,
            "win_rate": evaluation_record.win_rate,
            "evaluation_record": evaluation_record,
            "season_evaluation": season_evaluation,
        }