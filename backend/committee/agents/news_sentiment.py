"""News & Sentiment Agent — README's second specialist. Focus: financial
news, earnings updates, corporate announcements. LLM-backed (Gemini);
degrades to a neutral WAIT rather than crashing the cycle when there's no
usable headline data or the LLM is unavailable.
"""

from backend.committee.llm.gemini_client import LLMUnavailableError, complete
from backend.committee.market_data.context import MarketContext
from backend.committee.nlp.preprocess import clean_headlines
from backend.committee.schemas import AgentOutput, Decision, LLMAgentVerdict

AGENT_NAME = "News & Sentiment"

SYSTEM_PROMPT = """You are the News & Sentiment Analyst on an autonomous investment committee.
Your focus is financial news, earnings updates, and corporate announcements for one NSE-listed stock.
Given a list of recent headlines, decide whether they support BUY, SELL, or WAIT for this stock intraday.
Justify your confidence (0.0-1.0) in your reasoning, and cite the specific headlines you relied on as evidence.
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
        verdict = complete(SYSTEM_PROMPT, user_prompt, LLMAgentVerdict)
        return verdict.to_agent_output(AGENT_NAME)
    except LLMUnavailableError as exc:
        return AgentOutput(
            agent=AGENT_NAME,
            decision=Decision.WAIT,
            confidence=0.0,
            reasoning=f"LLM unavailable ({exc}) — degraded to neutral instead of failing the cycle.",
            evidence=headlines[:3],
        )
