"""LangGraph 节点实现。

流程：intake → safety → router → FAQ 快速路径 / planner → executor
→ evidence gate → (replan) → composer → critic → finalize。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from everrag.agent.state import AgentState
from everrag.config import Settings
from everrag.guardrails.guards import Guardrails
from everrag.llm.client import LLMClient
from everrag.llm.composer import LLMComposer
from everrag.schemas import Citation, Document, RiskFlag, Task, ToolResult
from everrag.tools.base import ToolContext, ToolRegistry

GREETING_KEYWORDS = ["你好", "您好", "在吗", "谢谢", "再见", "哈喽", "嗨"]

INTENT_KEYWORDS: dict[str, list[str]] = {
    "grief": ["难过", "悲伤", "睡不着", "情绪低落", "想哭", "心里难受", "走不出来", "哀伤"],
    "cultural": [
        "回族",
        "佛教",
        "道教",
        "基督教",
        "伊斯兰教",
        "习俗",
        "民族",
        "宗教",
        "头七",
        "做七",
        "仪轨",
        "禁忌",
        "祭奠",
    ],
    "regulation": [
        "政策",
        "法规",
        "条例",
        "手续",
        "证明",
        "补贴",
        "减免",
        "收费",
        "费用",
        "标准",
        "跨省",
        "运输",
        "低保",
        "特困",
        "惠民",
        "规定",
    ],
    "funeral": [
        "流程",
        "接运",
        "冷藏",
        "整容",
        "告别",
        "火化",
        "骨灰",
        "寿衣",
        "花圈",
        "殡仪",
        "遗体",
        "去世",
        "后事",
        "办理",
        "第一步",
    ],
    "cemetery": ["墓", "安葬", "落葬", "祭扫", "风水", "海葬", "树葬", "草坪葬", "墓位"],
}


def classify_intent(text: str) -> tuple[str, str]:
    text = (text or "").strip()
    if not text:
        return "unknown", "simple"
    if len(text) <= 12 and any(kw in text for kw in GREETING_KEYWORDS):
        return "smalltalk", "simple"

    matched = [intent for intent, kws in INTENT_KEYWORDS.items() if any(kw in text for kw in kws)]
    if not matched:
        return "unknown", "simple"
    if len(matched) >= 2:
        return "mixed", "complex"
    intent = matched[0]
    complexity = "complex" if len(text) > 60 else "simple"
    return intent, complexity


def _append(events: list[dict[str, Any]], event_type: str, **payload: Any) -> list[dict[str, Any]]:
    return [*events, {"type": event_type, **payload}]


def _merge_flags(existing: list[RiskFlag], new: list[RiskFlag]) -> list[RiskFlag]:
    merged = {flag.code: flag for flag in existing}
    for flag in new:
        merged[flag.code] = flag
    return list(merged.values())


def _has_regulation_need(intent: str, message: str) -> bool:
    if intent == "regulation":
        return True
    if intent == "mixed":
        return any(kw in message for kw in INTENT_KEYWORDS["regulation"])
    return False


def _record_tool(name: str, result: ToolResult, task_id: str | None = None) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "tool": name,
        "ok": result.ok,
        "elapsed_ms": result.elapsed_ms,
        "error": result.error.code if result.error else None,
    }


def _upsert_doc(docs_by_id: dict[str, Document], doc: Document) -> None:
    """合并文档时保留已有检索分数，避免 verify_citation 的 score=0 覆盖排序。"""
    existing = docs_by_id.get(doc.doc_id)
    if existing and existing.score > doc.score:
        doc = doc.model_copy(update={"score": existing.score})
    docs_by_id[doc.doc_id] = doc


class AgentNodes:
    def __init__(
        self,
        registry: ToolRegistry,
        guardrails: Guardrails,
        settings: Settings,
        llm: LLMClient,
        llm_composer: LLMComposer | None = None,
    ):
        self.registry = registry
        self.guardrails = guardrails
        self.settings = settings
        self.llm = llm
        self.llm_composer = llm_composer
        self._prompt_cache: dict[str, str] = {}

    # ---------- 工具 ----------

    def _prompt(self, name: str, fallback: str) -> str:
        if name not in self._prompt_cache:
            path = Path(self.settings.root) / "configs" / "prompts" / name
            try:
                self._prompt_cache[name] = path.read_text(encoding="utf-8")
            except OSError:
                self._prompt_cache[name] = fallback
        return self._prompt_cache[name]

    def _ctx(self, state: AgentState) -> ToolContext:
        return ToolContext(
            trace_id=state.get("trace_id", ""),
            user_role=state.get("user_role", "family"),
            access_level=int(state.get("access_level", 0)),
            user_profile=state.get("user_profile", {}),
        )

    @staticmethod
    def _resolve_args(args: dict[str, Any], results: dict[str, dict[str, Any]]) -> dict[str, Any]:
        resolved: dict[str, Any] = {}
        for key, value in args.items():
            if isinstance(value, str) and value.startswith("$"):
                task_id, _, field = value[1:].partition(".")
                data = results.get(task_id, {})
                if field == "doc_id":
                    docs = data.get("documents", [])
                    resolved[key] = docs[0].get("doc_id") if docs else None
                else:
                    resolved[key] = None
            else:
                resolved[key] = value
        return resolved

    # ---------- 节点 ----------

    def intake(self, state: AgentState) -> dict[str, Any]:
        events = _append(
            list(state.get("events", [])),
            "meta",
            trace_id=state.get("trace_id", ""),
            session_id=state.get("session_id", ""),
        )
        return {
            "step_count": 1,
            "events": events,
            "plan": [],
            "tool_calls": [],
            "retrieved_docs": [],
            "citations": [],
            "risk_flags": [],
            "tool_errors": [],
            "replan_count": 0,
            "revision_count": 0,
            "needs_human": False,
            "faq_hit": False,
            "critic_ok": False,
            "critic_notes": "",
            "degraded": False,
            "citation_invalid": False,
        }

    def safety_screen(self, state: AgentState) -> dict[str, Any]:
        result = self.guardrails.check_input(state.get("message", ""))
        flags: list[RiskFlag] = []
        if result.pii_masked:
            flags.append(RiskFlag(code="PII_MASKED", severity="low", message="输入中的 PII 已脱敏"))
        if result.injection:
            flags.append(
                RiskFlag(code="PROMPT_INJECTION", severity="high", message="检测到疑似 Prompt 注入")
            )
        if result.crisis:
            flags.append(RiskFlag(code="CRISIS_SIGNAL", severity="critical", message="检测到危机信号"))
        events = _append(
            list(state.get("events", [])),
            "status",
            stage="safety_screen",
            crisis=result.crisis,
            injection=result.injection,
            pii_masked=result.pii_masked,
        )
        return {
            "masked_message": result.masked_text,
            "normalized_message": result.masked_text.strip(),
            "crisis": result.crisis,
            "injection": result.injection,
            "pii_masked": result.pii_masked,
            "risk_flags": _merge_flags(list(state.get("risk_flags", [])), flags),
            "events": events,
            "step_count": state.get("step_count", 0) + 1,
        }

    def crisis(self, state: AgentState) -> dict[str, Any]:
        template = self._prompt(
            "crisis.v1.md",
            "听到您这么说，我很担心您。可以立即联系心理援助热线 {hotline}，或拨打 120/110。",
        )
        answer = template.replace("{hotline}", self.settings.agent.crisis_hotline)
        flags = _merge_flags(
            list(state.get("risk_flags", [])),
            [RiskFlag(code="CRISIS_HANDOFF", severity="critical", message="危机场景转人工")],
        )
        return {
            "final_answer": answer,
            "needs_human": True,
            "handoff_reason": "crisis",
            "risk_flags": flags,
            "events": _append(list(state.get("events", [])), "handoff", reason="crisis"),
            "step_count": state.get("step_count", 0) + 1,
        }

    def refuse(self, state: AgentState) -> dict[str, Any]:
        answer = self._prompt(
            "refusal.v1.md",
            "抱歉，这个请求涉及不当指令或越权操作，我无法处理。",
        )
        return {
            "final_answer": answer,
            "needs_human": True,
            "handoff_reason": "prompt_injection",
            "events": _append(list(state.get("events", [])), "handoff", reason="prompt_injection"),
            "step_count": state.get("step_count", 0) + 1,
        }

    def router(self, state: AgentState) -> dict[str, Any]:
        intent, complexity = classify_intent(state.get("normalized_message", ""))
        return {
            "intent": intent,
            "complexity": complexity,
            "events": _append(
                list(state.get("events", [])),
                "status",
                stage="router",
                intent=intent,
                complexity=complexity,
            ),
            "step_count": state.get("step_count", 0) + 1,
        }

    def faq_lookup(self, state: AgentState) -> dict[str, Any]:
        ctx = self._ctx(state)
        result = self.registry.execute(
            "get_faq_answer",
            {
                "question": state.get("normalized_message", ""),
                "threshold": self.settings.agent.faq_fast_path_threshold,
            },
            ctx,
        )
        tool_calls = [*list(state.get("tool_calls", [])), _record_tool("get_faq_answer", result, "faq")]
        events = _append(
            list(state.get("events", [])),
            "tool_result",
            tool="get_faq_answer",
            ok=result.ok,
            hit=bool(result.data.get("hit")) if result.ok else False,
        )
        if result.ok and result.data.get("hit"):
            faq = result.data["faq"]
            answer = faq["answer"]
            if faq.get("is_sample"):
                answer += "\n\n说明：以上为示例 FAQ，仅用于开发验证。"
            citation = Citation(
                doc_id=faq["faq_id"],
                title="常见问题解答（FAQ）",
                source_url=f"sample://faq/{faq['faq_id']}",
                quote=faq["answer"][:100],
            )
            events = _append(events, "citation", doc_id=faq["faq_id"], title=citation.title)
            return {
                "faq_hit": True,
                "final_answer": answer,
                "citations": [citation],
                "evidence_ok": True,
                "tool_calls": tool_calls,
                "events": events,
                "step_count": state.get("step_count", 0) + 1,
            }
        return {
            "faq_hit": False,
            "tool_calls": tool_calls,
            "events": events,
            "step_count": state.get("step_count", 0) + 1,
        }

    def planner(self, state: AgentState) -> dict[str, Any]:
        message = state.get("normalized_message", "")
        intent = state.get("intent", "unknown")
        profile = state.get("user_profile", {})
        region = profile.get("region")
        ethnicity = profile.get("ethnicity")
        religion = profile.get("religion")
        top_k = self.settings.retrieval.top_k
        tasks: list[Task] = []

        if intent in ("funeral", "cemetery", "unknown", "mixed"):
            collections = (
                ["funeral_service", "regulation", "cultural_custom"]
                if intent == "unknown"
                else ["funeral_service"]
            )
            tasks.append(
                Task(
                    task_id="t1",
                    goal="检索殡仪服务知识",
                    tool="search_knowledge_base",
                    args={
                        "query": message,
                        "collections": collections,
                        "region": region,
                        "top_k": top_k,
                    },
                )
            )
        if intent in ("regulation", "mixed"):
            tasks.append(
                Task(
                    task_id="t2",
                    goal="检索法规政策",
                    tool="search_regulation",
                    args={"query": message, "region": region, "top_k": top_k},
                )
            )
            tasks.append(
                Task(
                    task_id="t3",
                    goal="核验法规引用",
                    tool="verify_citation",
                    args={"doc_id": "$t2.doc_id"},
                    depends_on=["t2"],
                )
            )
        if intent in ("cultural", "mixed"):
            tasks.append(
                Task(
                    task_id="t4",
                    goal="检索文化习俗",
                    tool="lookup_cultural_custom",
                    args={
                        "query": message,
                        "region": region,
                        "ethnicity": ethnicity,
                        "religion": religion,
                        "top_k": top_k,
                    },
                )
            )
        if not tasks:
            tasks.append(
                Task(
                    task_id="t1",
                    goal="全库检索",
                    tool="search_knowledge_base",
                    args={
                        "query": message,
                        "collections": ["funeral_service", "regulation", "cultural_custom"],
                        "top_k": top_k,
                    },
                )
            )
        return {
            "plan": tasks,
            "events": _append(
                list(state.get("events", [])),
                "status",
                stage="planner",
                tasks=[task.tool for task in tasks],
            ),
            "step_count": state.get("step_count", 0) + 1,
        }

    def executor(self, state: AgentState) -> dict[str, Any]:
        plan = list(state.get("plan", []))
        results: dict[str, dict[str, Any]] = {}
        docs_by_id: dict[str, Document] = {
            doc.doc_id: doc for doc in state.get("retrieved_docs", [])
        }
        citations_by_id: dict[str, Citation] = {
            citation.doc_id: citation for citation in state.get("citations", [])
        }
        tool_calls = list(state.get("tool_calls", []))
        tool_errors = list(state.get("tool_errors", []))
        events = list(state.get("events", []))
        risk_flags = list(state.get("risk_flags", []))
        ctx = self._ctx(state)
        attempted_verifies: set[str] = set()

        for task in plan:
            if len(tool_calls) >= self.settings.agent.max_tool_calls:
                tool_errors.append(
                    {
                        "task_id": task.task_id,
                        "code": "TOOL_BUDGET_EXCEEDED",
                        "message": "工具调用次数超预算",
                    }
                )
                break

            args = self._resolve_args(task.args, results)
            if task.tool == "verify_citation" and not args.get("doc_id"):
                tool_errors.append(
                    {
                        "task_id": task.task_id,
                        "code": "DEPENDENCY_MISSING",
                        "message": "上游检索未返回可核验的文档",
                    }
                )
                continue
            if task.tool == "verify_citation" and args.get("doc_id"):
                attempted_verifies.add(args["doc_id"])

            events = _append(events, "tool_start", tool=task.tool, task_id=task.task_id)
            result = self.registry.execute(task.tool, args, ctx)
            tool_calls.append(_record_tool(task.tool, result, task.task_id))
            events = _append(
                events,
                "tool_result",
                tool=task.tool,
                task_id=task.task_id,
                ok=result.ok,
                total=len(result.data.get("documents", [])) if result.ok else 0,
                valid=result.data.get("valid") if result.ok else None,
            )

            if not result.ok:
                tool_errors.append(
                    {
                        "task_id": task.task_id,
                        "code": result.error.code if result.error else "TOOL_ERROR",
                        "message": result.error.message if result.error else "工具调用失败",
                    }
                )
                risk_flags = _merge_flags(
                    risk_flags,
                    [RiskFlag(code="TOOL_ERROR", severity="medium", message=f"{task.tool} 调用失败")],
                )
                continue

            results[task.task_id] = result.data
            if task.tool in ("search_knowledge_base", "search_regulation", "lookup_cultural_custom"):
                for payload in result.data.get("documents", []):
                    doc = Document.from_payload(payload)
                    _upsert_doc(docs_by_id, doc)
                    if task.tool != "search_regulation":
                        citations_by_id.setdefault(doc.doc_id, Citation.from_document(doc))
            elif task.tool == "verify_citation":
                if result.data.get("valid") and result.data.get("doc"):
                    doc = Document.from_payload(result.data["doc"])
                    _upsert_doc(docs_by_id, doc)
                    citations_by_id[doc.doc_id] = Citation.from_document(doc)
                else:
                    risk_flags = _merge_flags(
                        risk_flags,
                        [
                            RiskFlag(
                                code="CITATION_INVALID",
                                severity="high",
                                message=f"引用核验失败: {result.data.get('reason', 'UNKNOWN')}",
                            )
                        ],
                    )

        # Policy Agent 二次核验：对检索到但尚未核验的法规文档，最多再核验 2 篇。
        for doc in list(docs_by_id.values()):
            if doc.kb_id != "regulation" or doc.doc_id in citations_by_id:
                continue
            if doc.doc_id in attempted_verifies:
                continue
            if len(tool_calls) >= self.settings.agent.max_tool_calls or len(attempted_verifies) >= 3:
                break
            attempted_verifies.add(doc.doc_id)
            events = _append(events, "tool_start", tool="verify_citation", task_id=f"auto_{doc.doc_id}")
            result = self.registry.execute("verify_citation", {"doc_id": doc.doc_id}, ctx)
            tool_calls.append(_record_tool("verify_citation", result, f"auto_{doc.doc_id}"))
            events = _append(
                events,
                "tool_result",
                tool="verify_citation",
                task_id=f"auto_{doc.doc_id}",
                ok=result.ok,
                valid=result.data.get("valid") if result.ok else None,
            )
            if result.ok and result.data.get("valid") and result.data.get("doc"):
                verified = Document.from_payload(result.data["doc"])
                _upsert_doc(docs_by_id, verified)
                citations_by_id[verified.doc_id] = Citation.from_document(verified)
            else:
                risk_flags = _merge_flags(
                    risk_flags,
                    [
                        RiskFlag(
                            code="CITATION_INVALID",
                            severity="high",
                            message=f"引用核验失败: {result.data.get('reason', 'UNKNOWN')}",
                        )
                    ],
                )

        docs = sorted(docs_by_id.values(), key=lambda d: d.score, reverse=True)
        return {
            "retrieved_docs": docs,
            "citations": list(citations_by_id.values()),
            "tool_calls": tool_calls,
            "tool_errors": tool_errors,
            "risk_flags": risk_flags,
            "events": events,
            "step_count": state.get("step_count", 0) + 1,
        }

    def evidence_gate(self, state: AgentState) -> dict[str, Any]:
        docs = list(state.get("retrieved_docs", []))
        citations = list(state.get("citations", []))
        intent = state.get("intent", "unknown")
        message = state.get("normalized_message", "")
        good = [d for d in docs if d.score >= self.settings.agent.min_retrieval_score]
        has_reg_citation = any(c.doc_id.startswith("reg_") for c in citations)

        if _has_regulation_need(intent, message):
            # 法规类问题以「通过核验的引用」为准；检索分数仅用于排序。
            ok = has_reg_citation
        else:
            ok = len(good) >= self.settings.agent.min_evidence_docs

        return {
            "evidence_ok": ok,
            "events": _append(
                list(state.get("events", [])),
                "status",
                stage="evidence_gate",
                evidence_ok=ok,
                docs=len(good),
                citations=len(citations),
            ),
            "step_count": state.get("step_count", 0) + 1,
        }

    def replan(self, state: AgentState) -> dict[str, Any]:
        intent = state.get("intent", "unknown")
        message = state.get("normalized_message", "")
        profile = state.get("user_profile", {})
        top_k = self.settings.retrieval.top_k
        tasks: list[Task] = []

        if intent in ("regulation", "mixed"):
            tasks.append(
                Task(
                    task_id="r1",
                    goal="扩大法规检索",
                    tool="search_regulation",
                    args={"query": f"{message} 全国 一般规定", "region": None, "top_k": top_k},
                )
            )
            tasks.append(
                Task(
                    task_id="r2",
                    goal="核验法规引用",
                    tool="verify_citation",
                    args={"doc_id": "$r1.doc_id"},
                    depends_on=["r1"],
                )
            )
        if intent in ("cultural", "mixed"):
            tasks.append(
                Task(
                    task_id="r3",
                    goal="扩大文化习俗检索",
                    tool="lookup_cultural_custom",
                    args={"query": message, "top_k": top_k},
                )
            )
        if intent in ("funeral", "cemetery", "unknown") and not tasks:
            tasks.append(
                Task(
                    task_id="r4",
                    goal="扩大殡仪知识检索",
                    tool="search_knowledge_base",
                    args={
                        "query": message,
                        "collections": ["funeral_service", "regulation", "cultural_custom"],
                        "region": profile.get("region"),
                        "top_k": top_k,
                    },
                )
            )

        return {
            "plan": tasks,
            "replan_count": state.get("replan_count", 0) + 1,
            "events": _append(
                list(state.get("events", [])),
                "status",
                stage="replan",
                tasks=[task.tool for task in tasks],
            ),
            "step_count": state.get("step_count", 0) + 1,
        }

    def composer(self, state: AgentState) -> dict[str, Any]:
        docs = list(state.get("retrieved_docs", []))
        citations = list(state.get("citations", []))
        intent = state.get("intent", "unknown")
        message = state.get("normalized_message", "")
        needs_human = bool(state.get("needs_human", False))
        handoff_reason = state.get("handoff_reason")
        events = list(state.get("events", []))
        degraded = False

        # LLM 生成路径：成功后直接进入 critic；失败则回退到下面的确定性 composer。
        if self.llm_composer is not None and docs:
            llm_result = self.llm_composer.compose(state)
            if not llm_result.degraded and llm_result.answer:
                flags = list(state.get("risk_flags", []))
                citation_invalid = bool(llm_result.citation_invalid)
                if citation_invalid:
                    flags = _merge_flags(
                        flags,
                        [
                            RiskFlag(
                                code="CITATION_INVALID",
                                severity="high",
                                message="LLM 回答存在缺失或无效引用",
                            )
                        ],
                    )
                    needs_human = True
                    handoff_reason = handoff_reason or "citation_unverified"
                events = _append(
                    events,
                    "status",
                    stage="composer",
                    mode="llm",
                    docs=len(docs),
                    citations=len(llm_result.citations),
                    degraded=False,
                    citation_invalid=citation_invalid,
                )
                return {
                    "draft_answer": llm_result.answer,
                    "citations": llm_result.citations,
                    "risk_flags": flags,
                    "degraded": False,
                    "citation_invalid": citation_invalid,
                    "critic_notes": "",
                    "needs_human": needs_human,
                    "handoff_reason": handoff_reason,
                    "events": events,
                    "step_count": state.get("step_count", 0) + 1,
                }
            degraded = True
            events = _append(
                events,
                "status",
                stage="composer",
                mode="degraded",
                error=llm_result.error,
            )

        if not docs:
            answer = (
                "暂未检索到足够依据，无法给出确定结论。\n\n"
                "建议您联系当地殡仪馆、民政部门或相关服务机构确认。"
                "我已为您标记转人工，您可以继续补充信息，或等待人工协助。"
            )
            needs_human = True
            handoff_reason = handoff_reason or "no_evidence"
        else:
            # 按知识库分组选材：政策/文化/殡仪各取最多 2 篇，避免单一库淹没其他证据。
            priority: list[str] = []
            if _has_regulation_need(intent, message):
                priority.append("regulation")
            if intent in ("cultural", "mixed"):
                priority.append("cultural_custom")
            priority.append("funeral_service")
            if intent == "unknown":
                priority.extend(["regulation", "cultural_custom"])

            selected: list[Document] = []
            seen_ids: set[str] = set()
            for kb_id in priority:
                for doc in [d for d in docs if d.kb_id == kb_id][:2]:
                    if doc.doc_id not in seen_ids:
                        selected.append(doc)
                        seen_ids.add(doc.doc_id)
            for doc in docs:
                if len(selected) >= 6:
                    break
                if doc.doc_id not in seen_ids:
                    selected.append(doc)
                    seen_ids.add(doc.doc_id)

            parts = ["关于您咨询的事项，以下信息供您参考："]
            for doc in selected:
                snippet = doc.content.strip()
                if len(snippet) > 110:
                    snippet = snippet[:110] + "…"
                parts.append(f"- 【{doc.title}】{snippet}")

            selected_citations = [c for c in citations if c.doc_id in seen_ids]
            if selected_citations:
                parts.append("\n参考依据：")
                for citation in selected_citations[:6]:
                    label = f"《{citation.title}》"
                    if citation.article_no:
                        label += f" {citation.article_no}"
                    if citation.authority:
                        label += f"（{citation.authority}）"
                    if citation.effective_date:
                        label += f"，生效日期 {citation.effective_date}"
                    parts.append(f"- {label}")

            if any(doc.is_sample for doc in selected):
                parts.append("\n说明：以上内容来自示例知识库，仅用于开发验证。")
            parts.append("具体办理要求以当地殡仪馆、民政部门或相关机构的正式规定为准。")
            if intent in ("cultural", "mixed"):
                parts.append("不同地区、民族和家庭的做法存在差异，建议与当地殡仪馆或相关宗教人士确认。")

            has_reg_citation = any(c.doc_id.startswith("reg_") for c in citations)
            if _has_regulation_need(intent, message) and not has_reg_citation:
                needs_human = True
                handoff_reason = handoff_reason or "citation_unverified"
                parts.append("注意：当前未核验到有效法规引用，建议咨询当地民政部门。")

            if state.get("critic_notes"):
                parts.append("\n补充说明：以上信息仅供参考，具体以当地官方规定为准。")

            answer = "\n".join(parts)

        events = _append(
            events,
            "status",
            stage="composer",
            mode="deterministic",
            docs=len(docs),
            citations=len(citations),
            degraded=degraded,
        )
        return {
            "draft_answer": answer,
            "citations": citations,
            "risk_flags": list(state.get("risk_flags", [])),
            "degraded": degraded,
            "citation_invalid": False,
            "critic_notes": "",
            "needs_human": needs_human,
            "handoff_reason": handoff_reason,
            "events": events,
            "step_count": state.get("step_count", 0) + 1,
        }

    def critic(self, state: AgentState) -> dict[str, Any]:
        answer = state.get("draft_answer") or state.get("final_answer") or ""
        citations = list(state.get("citations", []))
        intent = state.get("intent", "unknown")
        citation_invalid = bool(state.get("citation_invalid", False))
        needs_human = bool(state.get("needs_human", False))
        handoff_reason = state.get("handoff_reason")
        result = self.guardrails.check_output(answer, citations, intent, needs_human)
        risk_flags = _merge_flags(list(state.get("risk_flags", [])), result.flags)
        revised = result.revised_answer or answer
        revision_count = state.get("revision_count", 0)

        if citation_invalid:
            risk_flags = _merge_flags(
                risk_flags,
                [
                    RiskFlag(
                        code="CITATION_INVALID",
                        severity="high",
                        message="LLM 回答存在缺失或无效引用",
                    )
                ],
            )
            needs_human = True
            handoff_reason = handoff_reason or "citation_unverified"
            warning = "注意：部分引用未能通过核验，已按保守方式处理；建议以当地官方信息为准。"
            if warning not in revised:
                revised = f"{revised}\n\n{warning}"

        if result.ok:
            return {
                "final_answer": revised,
                "critic_ok": True,
                "needs_human": needs_human,
                "handoff_reason": handoff_reason,
                "citation_invalid": citation_invalid,
                "risk_flags": risk_flags,
                "events": _append(
                    list(state.get("events", [])),
                    "status",
                    stage="critic",
                    ok=True,
                    flags=[flag.code for flag in result.flags],
                    citation_invalid=citation_invalid,
                ),
                "step_count": state.get("step_count", 0) + 1,
            }

        if revision_count < self.settings.agent.max_revisions:
            return {
                "draft_answer": revised,
                "critic_notes": "; ".join(flag.message for flag in result.flags),
                "critic_ok": False,
                "needs_human": needs_human,
                "handoff_reason": handoff_reason,
                "citation_invalid": citation_invalid,
                "revision_count": revision_count + 1,
                "risk_flags": risk_flags,
                "events": _append(
                    list(state.get("events", [])),
                    "status",
                    stage="critic",
                    ok=False,
                    revision=revision_count + 1,
                    citation_invalid=citation_invalid,
                ),
                "step_count": state.get("step_count", 0) + 1,
            }

        return {
            "final_answer": revised,
            "critic_ok": True,
            "needs_human": True,
            "handoff_reason": state.get("handoff_reason") or "guardrail",
            "citation_invalid": citation_invalid,
            "risk_flags": risk_flags,
            "events": _append(
                list(state.get("events", [])),
                "status",
                stage="critic",
                ok=False,
                final_safe_fallback=True,
                citation_invalid=citation_invalid,
            ),
            "step_count": state.get("step_count", 0) + 1,
        }

    def grief_support(self, state: AgentState) -> dict[str, Any]:
        answer = self._prompt(
            "grief.v1.md",
            "听到您现在的感受，我很抱歉。失去亲人后的悲伤是正常的，不必强迫自己马上振作。"
            "如果持续失眠或无法正常生活，建议联系专业心理咨询师。",
        )
        return {
            "final_answer": answer,
            "events": _append(list(state.get("events", [])), "status", stage="grief_support"),
            "step_count": state.get("step_count", 0) + 1,
        }

    def smalltalk(self, state: AgentState) -> dict[str, Any]:
        answer = self._prompt(
            "smalltalk.v1.md",
            "您好，我是殡葬服务智能咨询助手。您可以直接描述需要了解的事项。",
        )
        return {
            "final_answer": answer,
            "events": _append(list(state.get("events", [])), "status", stage="smalltalk"),
            "step_count": state.get("step_count", 0) + 1,
        }

    def finalize(self, state: AgentState) -> dict[str, Any]:
        answer = state.get("final_answer") or state.get("draft_answer") or "暂未生成回答。"
        needs_human = bool(state.get("needs_human", False))
        events = _append(
            list(state.get("events", [])),
            "done",
            citations=len(state.get("citations", [])),
            needs_human=needs_human,
            steps=state.get("step_count", 0),
        )
        return {
            "final_answer": answer,
            "needs_human": needs_human,
            "handoff_reason": state.get("handoff_reason") or ("low_confidence" if needs_human else None),
            "events": events,
        }
