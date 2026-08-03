from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable


@dataclass(frozen=True)
class RouteDecision:
    intent: str
    handler_name: str
    matched_terms: tuple[str, ...] = ()
    score: int = 0


@dataclass(frozen=True)
class RouteRule:
    intent: str
    handler_name: str
    base_score: int
    patterns: tuple[tuple[str, re.Pattern[str]], ...]

    def score_question(self, question: str) -> tuple[int, tuple[str, ...]]:
        matched_terms = tuple(label for label, pattern in self.patterns if pattern.search(question))
        if not matched_terms:
            return 0, ()
        return self.base_score + len(matched_terms), matched_terms


class SyndicateQueryRouter:
    def __init__(self, rules: Iterable[RouteRule] | None = None) -> None:
        self._rules = tuple(rules or DEFAULT_RULES)

    @staticmethod
    def _normalize_question(question: str) -> str:
        return re.sub(r"\s+", " ", str(question or "").strip()).lower()

    def route(self, question: str) -> RouteDecision:
        normalized_question = self._normalize_question(question)
        # Unmatched questions fall back to a BOARD SUMMARY, not single-bet
        # analysis. bet_analysis matches one specific recommendation to the
        # question and, failing that, returns an empty shell whose only
        # content is "No board recommendation matches ... specifically" --
        # which the UI surfaces as "No structured answer came back."
        # Confirmed live 2026-08-03: "Summarize today's best opportunities
        # across the board and what to watch for" matched NO rule at all, so
        # every general question hit that dead end even with a healthy
        # 10-card board behind it. A summary of the board is always
        # answerable and is the sane default for a vague question.
        best_decision = RouteDecision(intent="market_summary", handler_name="handle_market_summary", score=0)

        for rule in self._rules:
            score, matched_terms = rule.score_question(normalized_question)
            if score <= 0:
                continue
            if score > best_decision.score or (score == best_decision.score and rule.base_score > self._base_score(best_decision.intent)):
                best_decision = RouteDecision(
                    intent=rule.intent,
                    handler_name=rule.handler_name,
                    matched_terms=matched_terms,
                    score=score,
                )

        return best_decision

    @staticmethod
    def _base_score(intent: str) -> int:
        return {
            "market_summary": 400,
            "comparison": 350,
            "bet_analysis": 300,
            "matchup_analysis": 100,
        }.get(intent, 0)


DEFAULT_RULES: tuple[RouteRule, ...] = (
    RouteRule(
        intent="comparison",
        handler_name="handle_matchup_analysis",
        base_score=350,
        patterns=(
            ("compare", re.compile(r"\bcompare\b", re.IGNORECASE)),
            ("which_is_better", re.compile(r"\bwhich is better\b", re.IGNORECASE)),
            ("side_by_side", re.compile(r"\bside by side\b", re.IGNORECASE)),
        ),
    ),
    RouteRule(
        intent="bet_analysis",
        handler_name="handle_bet_analysis",
        base_score=300,
        patterns=(
            ("what_do_you_think_of", re.compile(r"\bwhat do you think of\b", re.IGNORECASE)),
            ("spreads", re.compile(r"\bspreads?\b", re.IGNORECASE)),
            ("totals", re.compile(r"\btotals?\b", re.IGNORECASE)),
            ("player_props", re.compile(r"\bplayer props?\b|\bprops?\b", re.IGNORECASE)),
        ),
    ),
    RouteRule(
        intent="market_summary",
        handler_name="handle_market_summary",
        base_score=400,
        patterns=(
            ("best_bets", re.compile(r"\bbest bets\b", re.IGNORECASE)),
            ("top_edges", re.compile(r"\btop edges\b", re.IGNORECASE)),
            # Only the two literal phrases above existed, so ordinary
            # board-summary phrasing scored zero and fell through to the
            # single-bet path. These cover how the question is actually
            # asked -- including the home-page prompt itself.
            ("summarize", re.compile(r"\bsummar(?:ise|ize|y)\b", re.IGNORECASE)),
            ("best_opportunities", re.compile(r"\b(?:best|top)\s+(?:opportunit(?:y|ies)|plays?|bets?|edges?|picks?)\b", re.IGNORECASE)),
            ("across_the_board", re.compile(r"\bacross the board\b", re.IGNORECASE)),
            ("what_to_watch", re.compile(r"\bwhat to watch\b", re.IGNORECASE)),
            ("the_board", re.compile(r"\b(?:the|today'?s)\s+board\b", re.IGNORECASE)),
            # "any good props" is a plural, open-ended ask -- it names a
            # market family but no specific bet, so single-bet analysis
            # dead-ends on it the same way. Summary always has an answer.
            ("whats_good", re.compile(r"\b(?:what'?s|anything|any)\s+(?:good|worth|interesting)\b", re.IGNORECASE)),
            ("what_should_i_bet", re.compile(r"\bwhat should i (?:bet|play|back)\b", re.IGNORECASE)),
            ("overview", re.compile(r"\b(?:overview|rundown|slate)\b", re.IGNORECASE)),
        ),
    ),
    RouteRule(
        intent="matchup_analysis",
        handler_name="handle_matchup_analysis",
        base_score=100,
        patterns=(
            ("versus", re.compile(r"\bvs\.?\b|\bversus\b", re.IGNORECASE)),
        ),
    ),
)
