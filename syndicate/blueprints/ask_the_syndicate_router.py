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


# Vocabulary that makes a question ABOUT THIS PRODUCT.
#
# Used only to qualify the market_summary default (see `route`). Deliberately
# generous: a false positive costs one board summary -- the behaviour that
# already exists -- while a false negative declines a real betting question,
# which is strictly worse. So this errs toward answering.
#
# It is a POSITIVE list rather than a blocklist of things to refuse. A blocklist
# is an arms race and is wrong by default for anything not yet thought of; a
# positive list is wrong only for domain vocabulary nobody listed, which is
# discoverable from the logs once J2 lands.
_BETTING_DOMAIN = re.compile(
    r"\b("
    # wagering
    r"bet|bets|betting|wager|wagers|stake|stakes|bankroll|parlay|parlays|"
    r"hedge|payout|juice|vig|vigorish|hold|lock|action|ticket|slip|"
    # market structure
    r"odds|line|lines|price|prices|spread|spreads|total|totals|moneyline|ml|"
    r"puck ?line|run ?line|over|under|favou?red|favou?rite|underdog|dog|"
    r"draw|handicap|book|books|bookmaker|sportsbook|market|markets|"
    # the product's own nouns
    r"board|slate|edge|edges|value|ev|roi|clv|closing|pick|picks|play|plays|"
    r"opportunit(?:y|ies)|recommendation|recommendations|prop|props|"
    r"target|targets|projection|projections|projected|model|models|sim|"
    r"simulation|probabilit(?:y|ies)|confidence|calibration|accuracy|"
    # Day-scoping. A question scoped to a slate day IS a question about the
    # slate, and this is what rescues the bare-entity phrasings the lexical
    # test cannot otherwise see: "How is Jokic looking tonight?" names no
    # domain noun at all, and `_fetchers_for_sport`'s own comment already
    # records that exact question as one the keyword sets miss. Declining it
    # would be a real regression -- the entity resolvers downstream
    # (`_mlb_player_history_evidence`, `_basketball_last10_evidence`) match
    # arbitrary player names and the router cannot know whether they would hit.
    r"tonight|today|tomorrow|yesterday|"
    # competition / event
    # `match` only, NOT `matches` -- "matches" is a common verb and it let
    # "qwertyuiop nothing matches this at all" through the gate on the first
    # pass. Real soccer questions carry `league` / `fixture` / `value` / a team.
    r"game|games|match|matchup|fixture|fixtures|league|season|week|"
    r"team|teams|player|players|lineup|starter|starters|injury|injuries|"
    # sports
    r"mlb|nba|wnba|nhl|nfl|ncaaf|ncaab|soccer|baseball|basketball|hockey|"
    r"football|epl|premier ?league|la ?liga|bundesliga|serie ?a|mls|"
    # common stat nouns that only appear in this domain here
    r"score|scores|scoring|goal|goals|run|runs|point|points|strikeout|"
    r"strikeouts|rebound|rebounds|assist|assists|touchdown|touchdowns"
    r")\b",
    re.IGNORECASE,
)

# The one category that is never answerable, however it is phrased.
#
# This product has NO user accounts and NO per-user state -- there is no
# balance, no bet history, no positions belonging to a caller. `/api/syndicate/query`
# is public and unauthenticated, so a question about "my" records has no
# subject to resolve, and answering it with board data would imply a
# personalisation that does not exist. Measured 2026-08-14: "What is my account
# balance and betting history?" returned five betting opportunities.
#
# Kept deliberately narrow -- first-person possessive about one's own records.
# It is NOT a general blocklist, and must not grow into one.
_PERSONAL_RECORDS = re.compile(
    r"\bmy\s+(?:\w+\s+){0,2}?"
    r"(account|balance|bankroll|history|wagers?|bets?|positions?|portfolio|"
    r"profile|winnings|losses|record|settings|subscription)\b",
    re.IGNORECASE,
)


class SyndicateQueryRouter:
    def __init__(self, rules: Iterable[RouteRule] | None = None) -> None:
        self._rules = tuple(rules or DEFAULT_RULES)

    @staticmethod
    def _normalize_question(question: str) -> str:
        return re.sub(r"\s+", " ", str(question or "").strip()).lower()

    def route(self, question: str, context: dict[str, object] | None = None) -> RouteDecision:
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

        # The board's own "Ask about this pick" button (ask_bar.js's
        # wireAskButtons) asks a fixed, generic phrasing -- "What's the case
        # for and against <selection>?" -- that never matches any pattern
        # above, so every per-card click fell through to the market_summary
        # default and discarded the real context (selection/candidate_id/
        # market) it attached, even though that context unambiguously
        # names ONE specific pick. Reported live 2026-08-04: clicking the
        # per-card ask action never returned real single-bet analysis, no
        # matter which card. Only engages when nothing textual matched at
        # all (best_decision.score == 0) -- an explicit textual match (e.g.
        # "compare X and Y" typed while old context happens to be attached)
        # still wins on its own merits.
        if best_decision.score == 0 and isinstance(context, dict):
            subject = str(context.get("selection") or context.get("candidate_id") or context.get("name") or "").strip()
            if subject:
                return RouteDecision(intent="bet_analysis", handler_name="handle_bet_analysis", matched_terms=("context_subject",), score=self._base_score("bet_analysis") + 1)

        # A question about the caller's own records can never be answered --
        # there is no per-user state to answer it from. Checked BEFORE the
        # domain gate below, because such a question usually does contain
        # betting vocabulary ("my betting history") and would otherwise sail
        # through it.
        if _PERSONAL_RECORDS.search(normalized_question):
            return RouteDecision(
                intent="out_of_scope",
                handler_name="handle_out_of_scope",
                matched_terms=("personal_records",),
            )

        # THE DEFAULT IS QUALIFIED, NOT REMOVED, and the distinction is the
        # whole point of this branch.
        #
        # `market_summary` as the fallback (2026-08-03) fixed a real dead end:
        # `bet_analysis` matches one specific recommendation and, failing,
        # returns an empty shell the UI renders as "No structured answer came
        # back", so every vague BETTING question died there. That fix was
        # correct and is preserved -- an unmatched question that is about
        # betting still gets a summary.
        #
        # What it never scoped was questions that are not about betting at all.
        # Measured on production 2026-08-14, `market_summary` was the resolved
        # intent on 40 of 52 regression questions, including "What is the
        # capital of France?", which returned five betting opportunities. A
        # surface that answers everything is worse than one that declines,
        # because a user cannot tell the two modes apart -- so the fallback now
        # requires the question to be about this product.
        #
        # SCOPE, honestly: this catches questions with no domain vocabulary at
        # all. It does NOT catch a question that borrows the vocabulary while
        # being unanswerable for another reason -- "How many home runs did Babe
        # Ruth hit against the Mets?" (dead player, no such matchup) and "Who
        # won the game that hasn't been played yet tonight?" (impossible tense)
        # both still route to a summary. Those need entity and temporal
        # validation respectively, which is a different fix in a different
        # layer, not a longer word list here.
        if best_decision.score == 0 and not _BETTING_DOMAIN.search(normalized_question):
            return RouteDecision(
                intent="out_of_scope",
                handler_name="handle_out_of_scope",
                matched_terms=("no_domain_vocabulary",),
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
