# -*- coding: utf-8 -*-
"""
Agent module for stock analysis system.

Provides LLM-based agent with tool-calling capabilities,
pluggable trading strategies, and multi-turn conversation support.

Enabled via AGENT_MODE=true environment variable.

Use explicit imports to avoid pulling in heavy dependencies (e.g. json_repair)
when only lightweight sub-modules like tools.registry are needed::

    from finance_analysis.agent.executor import AgentExecutor, AgentResult
    from finance_analysis.agent.runner import run_agent_loop, RunLoopResult
    from finance_analysis.agent.protocols import AgentContext, AgentOpinion, StageResult, AgentRunStats
    from finance_analysis.agent.orchestrator import AgentOrchestrator
"""


def __getattr__(name):
    """Lazy import to avoid triggering json_repair etc. on package access."""
    if name == "AgentExecutor":
        from finance_analysis.agent.executor import AgentExecutor
        return AgentExecutor
    if name == "AgentResult":
        from finance_analysis.agent.executor import AgentResult
        return AgentResult
    if name == "RunLoopResult":
        from finance_analysis.agent.runner import RunLoopResult
        return RunLoopResult
    if name in ("AgentContext", "AgentOpinion", "StageResult", "AgentRunStats"):
        from finance_analysis.agent import protocols
        return getattr(protocols, name)
    if name == "AgentOrchestrator":
        from finance_analysis.agent.orchestrator import AgentOrchestrator
        return AgentOrchestrator
    if name == "AgentMemory":
        from finance_analysis.agent.memory import AgentMemory
        return AgentMemory
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "AgentExecutor",
    "AgentResult",
    "RunLoopResult",
    "AgentContext",
    "AgentOpinion",
    "StageResult",
    "AgentRunStats",
    "AgentOrchestrator",
    "AgentMemory",
]
