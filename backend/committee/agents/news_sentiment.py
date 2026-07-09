"""News & Sentiment Agent — README's second specialist. Focus: financial
news, earnings updates, corporate announcements. LLM-backed, routed through
config.AGENT_PROVIDER_MAP; degrades to a neutral WAIT rather than crashing
the cycle when there's no usable headline data or the LLM is unavailable.
"""

from backend.committee.llm.router import LLMUnavailableError, complete_for_agent
from backend.committee.market_data.context import MarketContext
from backend.committee.nlp.preprocess import clean_headlines
from backend.committee.schemas import AgentOutput, Decision, LLMAgentVerdict

AGENT_NAME = "News & Sentiment"

SYSTEM_PROMPT = """You are the News & Sentiment Analyst on an autonomous INTRADAY investment committee.
Your focus is financial news, earnings updates, and corporate announcements for one NSE-listed stock. Given
a list of recent headlines, decide whether they support BUY, SELL, or WAIT for this stock intraday.

This is a same-day trading desk: if the headlines lean one way even moderately, that lean is a tradeable
edge — take that side, sized to how strong the signal is, rather than defaulting to WAIT because the
picture isn't unanimous or the news isn't dramatic. Reserve WAIT for when the headlines are genuinely
neutral, stale, or pull in opposite directions with no net lean.

Confidence must measure the strength of your directional read, not how cautious your call feels: a modest
lean is real and should be reported as such (e.g. 0.3-0.5). A WAIT call means "these headlines give no
usable edge" and should itself carry LOW confidence (roughly 0.0-0.2) — a high-confidence WAIT is a strong
claim that, in this committee's consensus math, can silently override other specialists' directional votes,
so reserve it for genuinely balanced or irrelevant news, not as a hedge.

Justify your confidence in your reasoning, and cite the specific headlines you relied on as evidence.
Respond only with the requested JSON shape."""


def analyze(context: MarketContext) -> AgentOutput:
    headlines = clean_headlines(context.headlines)

    if not headlines:
        return AgentOutput(
            agent=AGENT_NAME,
            decision=Decision.WAIT,
            confidence=0.0,
            reasoning="No relevant headlines found this cycle.",
            evidence=[],
        )

    user_prompt = f"Stock: {context.symbol}\nRecent headlines:\n" + "\n".join(f"- {h}" for h in headlines)

    try:
        verdict = complete_for_agent(AGENT_NAME, SYSTEM_PROMPT, user_prompt, LLMAgentVerdict)
        return verdict.to_agent_output(AGENT_NAME)
    except LLMUnavailableError as exc:
        return AgentOutput(
            agent=AGENT_NAME,
            decision=Decision.WAIT,
            confidence=0.0,
            reasoning=f"LLM unavailable ({exc}) — degraded to neutral instead of failing the cycle.",
            evidence=headlines[:3],
        )
