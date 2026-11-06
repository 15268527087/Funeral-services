"""AgentState：LangGraph 图状态。"""

from __future__ import annotations

from typing import Any, TypedDict

from everrag.schemas import Citation, Document, RiskFlag, Task


class AgentState(TypedDict, total=False):
    # 会话标识
    session_id: str
    trace_id: str
    user_id: str
    user_role: str
    access_level: int
    user_profile: dict[str, Any]
    history: list[dict[str, Any]]

    # 输入与安全
    message: str
    normalized_message: str
    masked_message: str
    crisis: bool
    injection: bool
    pii_masked: bool

    # 路由与计划
    intent: str
    complexity: str
    plan: list[Task]

    # 执行与证据
    tool_calls: list[dict[str, Any]]
    tool_errors: list[dict[str, Any]]
    retrieved_docs: list[Document]
    citations: list[Citation]
    evidence_ok: bool

    # 回答与审核
    draft_answer: str
    final_answer: str
    critic_notes: str
    critic_ok: bool
    risk_flags: list[RiskFlag]
    needs_human: bool
    handoff_reason: str | None
    degraded: bool
    citation_invalid: bool

    # 预算与轨迹
    replan_count: int
    revision_count: int
    step_count: int
    events: list[dict[str, Any]]
    faq_hit: bool
