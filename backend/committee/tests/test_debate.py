from backend.committee.debate.engine import _revise
from backend.committee.schemas import AgentOutput, Decision


def test_disagreement_damps_confidence():
    agent = AgentOutput(agent="Technical", decision=Decision.BUY, confidence=0.8, reasoning="bullish EMA cross", evidence=[])
    contrarian = AgentOutput(agent="Contrarian", decision=Decision.SELL, confidence=0.6, reasoning="overextended rally", evidence=[])

    revised = _revise(agent, contrarian)

    assert revised.confidence == round(0.8 * (1 - 0.6 * 0.5), 4)
    assert "revised" in revised.reasoning


def test_agreement_leaves_confidence_unchanged():
    agent = AgentOutput(agent="Technical", decision=Decision.BUY, confidence=0.8, reasoning="x", evidence=[])
    contrarian = AgentOutput(agent="Contrarian", decision=Decision.BUY, confidence=0.9, reasoning="agrees", evidence=[])

    revised = _revise(agent, contrarian)

    assert revised.confidence == 0.8
    assert revised.reasoning == "x"


def test_contrarian_wait_leaves_confidence_unchanged():
    agent = AgentOutput(agent="Technical", decision=Decision.BUY, confidence=0.8, reasoning="x", evidence=[])
    contrarian = AgentOutput(agent="Contrarian", decision=Decision.WAIT, confidence=0.9, reasoning="no strong view", evidence=[])

    revised = _revise(agent, contrarian)

    assert revised.confidence == 0.8
