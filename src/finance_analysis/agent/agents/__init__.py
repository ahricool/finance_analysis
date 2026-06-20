# -*- coding: utf-8 -*-
"""
Specialised agents for the multi-agent pipeline.

Each agent class inherits from :class:`BaseAgent` and implements
a focused analysis scope (technical, intelligence, decision, risk).
"""

from finance_analysis.agent.agents.base_agent import BaseAgent
from finance_analysis.agent.agents.technical_agent import TechnicalAgent
from finance_analysis.agent.agents.intel_agent import IntelAgent
from finance_analysis.agent.agents.decision_agent import DecisionAgent
from finance_analysis.agent.agents.risk_agent import RiskAgent

__all__ = [
    "BaseAgent",
    "TechnicalAgent",
    "IntelAgent",
    "DecisionAgent",
    "RiskAgent",
]
