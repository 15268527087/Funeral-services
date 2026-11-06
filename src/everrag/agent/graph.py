"""LangGraph 状态图构建。"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from everrag.agent.nodes import AgentNodes
from everrag.agent.state import AgentState
from everrag.config import Settings


def build_graph(nodes: AgentNodes, settings: Settings):
    builder = StateGraph(AgentState)

    builder.add_node("intake", nodes.intake)
    builder.add_node("safety_screen", nodes.safety_screen)
    builder.add_node("crisis", nodes.crisis)
    builder.add_node("refuse", nodes.refuse)
    builder.add_node("router", nodes.router)
    builder.add_node("smalltalk", nodes.smalltalk)
    builder.add_node("grief_support", nodes.grief_support)
    builder.add_node("faq_lookup", nodes.faq_lookup)
    builder.add_node("planner", nodes.planner)
    builder.add_node("executor", nodes.executor)
    builder.add_node("evidence_gate", nodes.evidence_gate)
    builder.add_node("replan", nodes.replan)
    builder.add_node("composer", nodes.composer)
    builder.add_node("critic", nodes.critic)
    builder.add_node("finalize", nodes.finalize)

    builder.add_edge(START, "intake")
    builder.add_edge("intake", "safety_screen")

    def route_safety(state: AgentState) -> str:
        if state.get("crisis"):
            return "crisis"
        if state.get("injection"):
            return "refuse"
        return "normal"

    builder.add_conditional_edges(
        "safety_screen",
        route_safety,
        {"crisis": "crisis", "refuse": "refuse", "normal": "router"},
    )

    def route_router(state: AgentState) -> str:
        intent = state.get("intent", "unknown")
        if intent == "smalltalk":
            return "smalltalk"
        if intent == "grief":
            return "grief_support"
        # 复杂/混合问题跳过 FAQ 快速路径，直接进入规划，避免无谓的工具调用。
        if state.get("complexity") == "complex" or intent == "mixed":
            return "planner"
        return "faq"

    builder.add_conditional_edges(
        "router",
        route_router,
        {
            "smalltalk": "smalltalk",
            "grief_support": "grief_support",
            "faq": "faq_lookup",
            "planner": "planner",
        },
    )

    def route_faq(state: AgentState) -> str:
        return "finalize" if state.get("faq_hit") else "planner"

    builder.add_conditional_edges(
        "faq_lookup",
        route_faq,
        {"finalize": "finalize", "planner": "planner"},
    )

    builder.add_edge("planner", "executor")
    builder.add_edge("executor", "evidence_gate")

    def route_evidence(state: AgentState) -> str:
        if not state.get("evidence_ok") and state.get("replan_count", 0) < settings.agent.max_replans:
            return "replan"
        return "composer"

    builder.add_conditional_edges(
        "evidence_gate",
        route_evidence,
        {"replan": "replan", "composer": "composer"},
    )
    builder.add_edge("replan", "executor")
    builder.add_edge("composer", "critic")

    def route_critic(state: AgentState) -> str:
        if (
            not state.get("critic_ok")
            and state.get("revision_count", 0) < settings.agent.max_revisions
        ):
            return "composer"
        return "finalize"

    builder.add_conditional_edges(
        "critic",
        route_critic,
        {"composer": "composer", "finalize": "finalize"},
    )

    builder.add_edge("crisis", "finalize")
    builder.add_edge("refuse", "finalize")
    builder.add_edge("smalltalk", "finalize")
    builder.add_edge("grief_support", "finalize")
    builder.add_edge("finalize", END)

    return builder.compile()
