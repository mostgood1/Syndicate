"""Synthetic ESPN-shaped basketball summaries for the P2 tests (lane `basketball-native-live-state`).

Shapes copied from real payloads measured 2026-10-09 (NBA 401859967, WNBA 401857158, NCAAB 401827679):
plays carry `type.text`, `text`, `period.number`, `clock.displayValue`, `team.id`, `participants`,
`scoringPlay`/`scoreValue`, `shootingPlay`, running `homeScore`/`awayScore`.
"""

from __future__ import annotations

from typing import Any

HOME_ID, AWAY_ID = "1", "2"
HOME = [f"h{i}" for i in range(1, 9)]  # h1-h5 start
AWAY = [f"a{i}" for i in range(1, 9)]  # a1-a5 start


class Game:
    def __init__(self, league: str = "nba", *, state: str = "post", season_type: int = 2):
        self.league = league
        self.state = state
        self.season_type = season_type
        self.plays: list[dict[str, Any]] = []
        self.score = {"home": 0, "away": 0}

    def _add(self, period: int, clock: str, type_text: str, text: str, side: str | None, players: list[str], *,
             points: int = 0, shooting: bool = False, attempted: int | None = None) -> "Game":
        if points:
            self.score[side] += points
        play = {
            "id": str(len(self.plays) + 1), "sequenceNumber": str(len(self.plays) + 1),
            "type": {"text": type_text}, "text": text, "period": {"number": period}, "clock": {"displayValue": clock},
            "scoringPlay": bool(points), "scoreValue": points, "shootingPlay": shooting,
            "homeScore": self.score["home"], "awayScore": self.score["away"],
            "participants": [{"athlete": {"id": p}} for p in players],
        }
        if attempted is not None:
            play["pointsAttempted"] = attempted
        if side:
            play["team"] = {"id": HOME_ID if side == "home" else AWAY_ID}
        self.plays.append(play)
        return self

    def shot(self, period, clock, side, player, *, made=True, pts=2):
        return self._add(period, clock, "Jump Shot", f"{player} {'makes' if made else 'misses'} jumper", side, [player],
                         points=pts if made else 0, shooting=True, attempted=pts)

    def ft(self, period, clock, side, player, n, of, *, made=True):
        return self._add(period, clock, f"Free Throw - {n} of {of}", f"{player} {'makes' if made else 'misses'} free throw {n} of {of}",
                         side, [player], points=1 if made else 0, shooting=True, attempted=1)

    def foul(self, period, clock, side, player, kind="Personal Foul"):
        return self._add(period, clock, kind, f"{player} {kind.lower()}", side, [player])

    def rebound(self, period, clock, side, player, kind="Defensive Rebound"):
        return self._add(period, clock, kind, f"{player} {kind.lower()}", side, [player])

    def turnover(self, period, clock, side, player):
        return self._add(period, clock, "Lost Ball Turnover", f"{player} turnover", side, [player])

    def sub(self, period, clock, side, player_in, player_out):
        return self._add(period, clock, "Substitution", f"{player_in} enters the game for {player_out}", side, [player_in, player_out])

    def sub_in(self, period, clock, side, player):
        return self._add(period, clock, "Substitution", f"{player} subbing in for team", side, [player])

    def sub_out(self, period, clock, side, player):
        return self._add(period, clock, "Substitution", f"{player} subbing out for team", side, [player])

    def timeout(self, period, clock, side):
        return self._add(period, clock, "Full Timeout", "Full timeout", side, [])

    def end_period(self, period):
        return self._add(period, "0.0", "End Period", f"End of period {period}", None, [])

    def summary(self, *, minutes: dict[str, float] | None = None, pf: dict[str, int] | None = None,
                official: tuple[int, int] | None = None) -> dict[str, Any]:
        minutes = minutes or {}
        pf = pf or {}
        completed = self.state == "post"
        home_score, away_score = official or (self.score["home"], self.score["away"])

        def block(team_id, ids, starters):
            return {"team": {"id": team_id}, "statistics": [{
                "names": ["MIN", "PTS", "PF"],
                "athletes": [{"athlete": {"id": p, "displayName": p.upper()}, "starter": p in starters,
                              "didNotPlay": p not in minutes and p not in starters,
                              "stats": [str(int(round(minutes.get(p, 0)))), "0", str(pf.get(p, 0))]} for p in ids],
            }]}

        return {
            "header": {
                "id": "999", "season": {"year": 2026, "type": self.season_type},
                "competitions": [{"date": "2026-01-15T00:00Z", "status": {"type": {"state": self.state, "completed": completed}},
                                  "competitors": [
                                      {"homeAway": "home", "score": str(home_score), "team": {"id": HOME_ID, "abbreviation": "GS"}},
                                      {"homeAway": "away", "score": str(away_score), "team": {"id": AWAY_ID, "abbreviation": "NY"}},
                                  ]}],
            },
            "boxscore": {"players": [block(HOME_ID, HOME, HOME[:5]), block(AWAY_ID, AWAY, AWAY[:5])]},
            "plays": list(self.plays),
        }


def full_nba_game() -> Game:
    """A 4-quarter NBA game with in-quarter subs, a between-quarter sub, and a same-clock FT/sub sequence.

    Home: h1-h5 start. Q1 6:00 h6 for h1. Between Q1 and Q2 (unlogged) h1 returns for h6 -- h1 acts first
    in Q2, h6 never appears. Q3 h7 for h2 at 12:00 (logged). Away: a1-a5 the whole game except Q4 5:00
    a6 for a5 (between two free throws by a1).
    """
    g = Game("nba")
    g.shot(1, "11:30", "home", "h1").shot(1, "11:00", "away", "a1", pts=3)
    g.sub(1, "6:00", "home", "h6", "h1").shot(1, "5:00", "home", "h6").end_period(1)
    g.shot(2, "11:40", "home", "h1").rebound(2, "11:00", "away", "a2").end_period(2)
    g.sub(3, "12:00", "home", "h7", "h2").shot(3, "10:00", "home", "h7").end_period(3)
    g.foul(4, "5:00", "home", "h3", "Shooting Foul").ft(4, "5:00", "away", "a1", 1, 2)
    g.sub(4, "5:00", "away", "a6", "a5").ft(4, "5:00", "away", "a1", 2, 2).shot(4, "1:00", "away", "a6").end_period(4)
    return g
