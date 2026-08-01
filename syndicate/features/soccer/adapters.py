from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from zlib import crc32

from syndicate.features.soccer.contracts import SoccerMatchFeatures
from syndicate.features.soccer.contracts import SoccerPlayerFeatures
from syndicate.features.soccer.contracts import SoccerSimulationInput
from syndicate.features.soccer.contracts import SoccerSimulationOutput
from syndicate.features.soccer.sim_engine.soccersim.contracts import SoccerSimSimulationInput
from syndicate.features.soccer.sim_engine.soccersim.distribution import MatchDistributionSummary
from syndicate.features.soccer.sim_engine.soccersim.distribution import simulate_match_distribution
from syndicate.features.soccer.sim_engine.soccersim.league_profiles import get_league_profile
from syndicate.features.soccer.sim_engine.soccersim.player_props import build_usage_profiles
from syndicate.features.soccer.sim_engine.soccersim.player_props import project_team_player_props

_DEFAULT_SIMULATIONS = 300


def _safe_float(value: Any) -> float:
    try:
        if value is None or str(value).strip() == "":
            return 0.0
        return float(value)
    except Exception:
        return 0.0


def _norm_team(value: Any) -> str:
    return str(value or "").upper().strip()


@dataclass(frozen=True)
class SoccerSimulationAdapter:
    league: str

    def load_features(self, *, date: str, selection: Any | None = None, season: int | None = None) -> SoccerSimulationInput:
        # League data sources are wired in the ingestion phase; until then the
        # adapter runs on explicitly constructed simulation inputs.
        return SoccerSimulationInput(league=self.league, date=date, adapter_metadata={"source": "fallback_empty"})

    def _match_seed(self, match: SoccerMatchFeatures) -> int:
        return crc32(f"{self.league}:{match.match_id}:{match.date}".encode("utf-8")) % 1_000_000 + 1

    def _simulation_count(self, simulation_input: SoccerSimulationInput) -> int:
        return max(1, int(_safe_float(simulation_input.metadata.get("simulations")) or _DEFAULT_SIMULATIONS))

    def _engine_input(self, match: SoccerMatchFeatures) -> SoccerSimSimulationInput:
        team_metrics = dict(match.team_metrics or {})
        payload = {
            "attacking_metrics": team_metrics,
            "defensive_metrics": dict(match.defensive_metrics or {}),
            "possession_metrics": dict(match.possession_metrics or {}),
            "set_piece_metrics": dict(match.set_piece_metrics or {}),
            "tempo": dict(match.tempo_features or {}),
            "market_features": dict(match.market_features or {}),
        }
        return SoccerSimSimulationInput(
            home_team=match.home_team,
            away_team=match.away_team,
            seed=self._match_seed(match),
            home_attack_rating=_safe_float(team_metrics.get("home_attack_rating")),
            home_defense_rating=_safe_float(team_metrics.get("home_defense_rating")),
            away_attack_rating=_safe_float(team_metrics.get("away_attack_rating")),
            away_defense_rating=_safe_float(team_metrics.get("away_defense_rating")),
            knockout=bool(match.knockout),
            feature_generation_payload=payload,
        )

    def _match_distribution(self, match: SoccerMatchFeatures, *, simulations: int) -> MatchDistributionSummary:
        return simulate_match_distribution(
            self._engine_input(match),
            simulations=simulations,
            profile=get_league_profile(self.league),
        )

    def _match_output(self, match: SoccerMatchFeatures, distribution: MatchDistributionSummary, *, index: int, date: str) -> dict[str, Any]:
        return {
            "match_id": match.match_id,
            "league": self.league,
            "date": date,
            "index": index,
            "matchup": {"home_team": match.home_team, "away_team": match.away_team},
            "win_probability": {
                "home": distribution.home_win_probability,
                "draw": distribution.draw_probability,
                "away": distribution.away_win_probability,
            },
            "team_projection": {
                "home_mean": distribution.mean_home_goals,
                "away_mean": distribution.mean_away_goals,
                "total_mean": distribution.mean_total,
                "margin_mean": distribution.mean_margin,
            },
            "spread_distribution": {"home": distribution.mean_margin, "away": -distribution.mean_margin},
            "total_distribution": {
                "mean": distribution.mean_total,
                "over_2_5_probability": distribution.over_2_5_probability,
                "both_teams_scored_probability": distribution.both_teams_scored_probability,
            },
            "volume_projection": {
                "home_shots": distribution.mean_home_shots,
                "away_shots": distribution.mean_away_shots,
                "home_shots_on_target": distribution.mean_home_shots_on_target,
                "away_shots_on_target": distribution.mean_away_shots_on_target,
                "home_corners": distribution.mean_home_corners,
                "away_corners": distribution.mean_away_corners,
            },
            "periods": {
                "h1": {"home_mean": distribution.mean_h1_home_goals, "away_mean": distribution.mean_h1_away_goals},
                "h2": {"home_mean": distribution.mean_h2_home_goals, "away_mean": distribution.mean_h2_away_goals},
            },
            "scoreline_probabilities": dict(distribution.scoreline_probabilities),
            "simulations": distribution.simulations,
            "adapter_metadata": dict(match.adapter_metadata or {}),
        }

    def _players_for_side(self, simulation_input: SoccerSimulationInput, team_name: str) -> list[SoccerPlayerFeatures]:
        team = _norm_team(team_name)
        return [player for player in simulation_input.players if _norm_team(player.team) == team]

    def _player_outputs_for_match(
        self,
        simulation_input: SoccerSimulationInput,
        match: SoccerMatchFeatures,
        distribution: MatchDistributionSummary,
    ) -> list[dict[str, Any]]:
        outputs: list[dict[str, Any]] = []
        side_starters = {"home": set(match.home_starter_ids), "away": set(match.away_starter_ids)}
        for side, team_name in (("home", match.home_team), ("away", match.away_team)):
            players = self._players_for_side(simulation_input, team_name)
            if not players:
                # #170: silent zero otherwise -- this fires both when the
                # league's whole roster source is missing/empty (see
                # build_soccer_artifacts.py's SOCCER_PLAYER_ROWS_MISSING,
                # which already covers that case for every match at once)
                # and, distinctly, when the roster source has data but none
                # of it resolves to *this* match's team name (a single
                # promoted/relegated club, rename, or spelling gap -- see
                # loaders.py's SOCCER_PLAYER_ROWS_UNMATCHED_TEAM for the
                # per-row detail). Either way, this match's props end up
                # empty while the match-level sim still fully populates, so
                # a signal here is the only place that distinguishes it from
                # every other reason a match could have zero player_props.
                print(
                    f"[soccer_adapter] SOCCER_MATCH_PLAYER_PROPS_EMPTY league={self.league} "
                    f"match_id={match.match_id} side={side} team={team_name!r} "
                    f"total_players_loaded={len(simulation_input.players)}",
                    flush=True,
                )
                continue
            rows = [
                {
                    "player_id": player.player_id,
                    "player_name": player.player_name,
                    "position": player.position,
                    "team": player.team,
                    **dict(player.usage_metrics or {}),
                }
                for player in players
            ]
            starters = side_starters[side] or None
            usage_profiles = build_usage_profiles(rows, side=side, team=team_name, starters=starters)
            projections = project_team_player_props(distribution, usage_profiles)
            market_by_player = {player.player_id: dict(player.market_features or {}) for player in players}
            for projection in projections:
                row = projection.to_dict()
                row["league"] = self.league
                row["date"] = simulation_input.date
                row["match_id"] = match.match_id
                row["market_features"] = market_by_player.get(projection.player_id, {})
                outputs.append(row)
        return outputs

    def simulate_games(self, simulation_input: SoccerSimulationInput) -> SoccerSimulationOutput:
        return self._simulate(simulation_input, include_props=False)

    def simulate_props(self, simulation_input: SoccerSimulationInput) -> SoccerSimulationOutput:
        return self._simulate(simulation_input, include_props=True)

    def _simulate(self, simulation_input: SoccerSimulationInput, *, include_props: bool) -> SoccerSimulationOutput:
        simulations = self._simulation_count(simulation_input)
        match_outputs: list[dict[str, Any]] = []
        player_outputs: list[dict[str, Any]] = []
        for index, match in enumerate(simulation_input.matches):
            distribution = self._match_distribution(match, simulations=simulations)
            match_outputs.append(self._match_output(match, distribution, index=index, date=simulation_input.date))
            if include_props:
                player_outputs.extend(self._player_outputs_for_match(simulation_input, match, distribution))

        win_probability = match_outputs[0].get("win_probability") if match_outputs else {"home": None, "draw": None, "away": None}
        expected_spread = match_outputs[0].get("spread_distribution") if match_outputs else {}
        expected_total = match_outputs[0].get("total_distribution") if match_outputs else {}
        distribution_summary = {
            "matches": len(match_outputs),
            "players": len(player_outputs),
            "simulations_per_match": simulations,
            "has_match_outputs": bool(match_outputs),
            "has_player_outputs": bool(player_outputs),
        }
        return SoccerSimulationOutput(
            league=self.league,
            date=simulation_input.date,
            win_probability=win_probability if isinstance(win_probability, dict) else {},
            expected_spread=expected_spread if isinstance(expected_spread, dict) else {},
            expected_total=expected_total if isinstance(expected_total, dict) else {},
            confidence=round(0.55 + (0.05 if match_outputs else 0.0), 3),
            distribution_summary=distribution_summary,
            match_outputs=tuple(match_outputs),
            player_outputs=tuple(player_outputs),
            artifacts={"match_count": len(match_outputs), "player_count": len(player_outputs)},
            evaluation={
                "calibration": {
                    "win_probability": {"brier": None},
                    "total": {"mae": None},
                    "spread": {"mae": None},
                    "props": {"mae": None},
                }
            },
            adapter_metadata=dict(simulation_input.adapter_metadata or {}),
        )

    def build_artifacts(self, simulation_output: SoccerSimulationOutput) -> dict[str, Any]:
        match_outputs = list(simulation_output.match_outputs)
        player_outputs = list(simulation_output.player_outputs)
        top_scorers = sorted(
            (row for row in player_outputs if row.get("anytime_scorer_probability")),
            key=lambda row: row.get("anytime_scorer_probability") or 0.0,
            reverse=True,
        )[:10]
        top_props = [
            {
                "player_name": row.get("player_name"),
                "team": row.get("team"),
                "position": row.get("position"),
                "anytime_scorer_probability": row.get("anytime_scorer_probability"),
                "expected_shots": row.get("expected_shots"),
                "expected_shots_on_target": row.get("expected_shots_on_target"),
                "market_features": dict(row.get("market_features") or {}),
            }
            for row in top_scorers
        ]
        return {
            "league": simulation_output.league,
            "date": simulation_output.date,
            "daily_summary": {
                "league": simulation_output.league,
                "date": simulation_output.date,
                "match_count": len(match_outputs),
                "player_count": len(player_outputs),
                "matches": match_outputs,
            },
            "profile_bundle": {
                "league": simulation_output.league,
                "date": simulation_output.date,
                "matches": match_outputs,
                "players": player_outputs,
            },
            "top_props": {
                "league": simulation_output.league,
                "date": simulation_output.date,
                "rows": top_props,
            },
        }


def build_soccer_simulation_adapter(league: str) -> SoccerSimulationAdapter:
    return SoccerSimulationAdapter(league=league)
