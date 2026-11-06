"""Agent 编排入口：构建图、执行请求、写会话记忆。"""

from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

from everrag.agent.graph import build_graph
from everrag.agent.nodes import AgentNodes
from everrag.config import Settings
from everrag.guardrails.guards import Guardrails
from everrag.llm.client import build_llm
from everrag.llm.composer import LLMComposer, build_llm_composer
from everrag.memory.session import InMemorySessionStore
from everrag.observability.trace import new_trace_id
from everrag.schemas import ROLE_ACCESS_LEVELS, ChatRequest
from everrag.tools.base import ToolRegistry

logger = logging.getLogger(__name__)


class Orchestrator:
    def __init__(
        self,
        registry: ToolRegistry,
        guardrails: Guardrails,
        sessions: InMemorySessionStore,
        settings: Settings,
        llm_composer: LLMComposer | None = None,
    ):
        self.settings = settings
        self.sessions = sessions
        self.llm = build_llm(settings.agent.llm)
        self.llm_composer = (
            llm_composer if llm_composer is not None else build_llm_composer(settings, registry)
        )
        self.nodes = AgentNodes(
            registry,
            guardrails,
            settings,
            self.llm,
            llm_composer=self.llm_composer,
        )
        self.graph = build_graph(self.nodes, settings)

    def _invoke(self, req: ChatRequest) -> tuple[str, str, dict[str, Any]]:
        session_id = req.session_id or uuid4().hex
        trace_id = new_trace_id()
        initial: dict[str, Any] = {
            "session_id": session_id,
            "trace_id": trace_id,
            "user_id": req.user_id,
            "user_role": req.user_role,
            "access_level": ROLE_ACCESS_LEVELS.get(req.user_role, 0),
            "user_profile": req.user_profile,
            "history": self.sessions.get(session_id),
            "message": req.message,
            "events": [],
        }

        try:
            result = self.graph.invoke(initial, config={"recursion_limit": 40})
        except Exception as exc:
            logger.exception("Agent 执行失败")
            result = {
                **initial,
                "final_answer": (
                    "抱歉，系统暂时无法完成本次咨询。请稍后重试，"
                    "或联系当地殡仪馆、民政部门；也可以为您转接人工。"
                ),
                "intent": "unknown",
                "citations": [],
                "risk_flags": [],
                "needs_human": True,
                "handoff_reason": "system_error",
                "tool_calls": [],
                "degraded": False,
                "citation_invalid": False,
                "events": [{"type": "error", "message": type(exc).__name__}],
            }
        return session_id, trace_id, result

    def run_state(self, req: ChatRequest) -> dict[str, Any]:
        """返回图执行后的完整 state，供对比脚本/调试使用；不写会话。"""
        _, _, result = self._invoke(req)
        return result

    def run(self, req: ChatRequest) -> dict[str, Any]:
        session_id, trace_id, result = self._invoke(req)
        answer = result.get("final_answer") or result.get("draft_answer") or "暂未生成回答。"
        self.sessions.append(session_id, req.message, answer)
        return {
            "session_id": session_id,
            "trace_id": trace_id,
            "answer": answer,
            "intent": result.get("intent", "unknown"),
            "citations": result.get("citations", []),
            "risk_flags": result.get("risk_flags", []),
            "needs_human": bool(result.get("needs_human", False)),
            "handoff_reason": result.get("handoff_reason"),
            "tool_calls": result.get("tool_calls", []),
            "events": result.get("events", []),
            "degraded": bool(result.get("degraded", False)),
            "citation_invalid": bool(result.get("citation_invalid", False)),
        }
