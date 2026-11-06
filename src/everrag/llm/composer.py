"""LLMComposer：基于 DeepSeek 的生成器，支持流式、降级与引用后核验。

设计约束：
- Prompt 只从 configs/prompts/composer_v1.md 读取，代码只填充问题和证据。
- LLM 超时/错误时返回 degraded=True，由 AgentNodes.composer 回退到确定性 composer。
- LLM 产出的 [doc_id] 标记在生成后统一走 verify_citation；无效/缺失引用标记 citation_invalid。
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from openai import OpenAI

from everrag.config import Settings
from everrag.schemas import Citation, Document
from everrag.tools.base import ToolContext, ToolRegistry

logger = logging.getLogger(__name__)

CITATION_RE = re.compile(r"\[([A-Za-z0-9_\-]+)\]")


@dataclass
class ComposerResult:
    """LLMComposer 的输出；degraded/citation_invalid 会进入响应。"""

    answer: str
    citations: list[Citation] = field(default_factory=list)
    degraded: bool = False
    citation_invalid: bool = False
    error: str | None = None
    latency_ms: float = 0.0
    model: str = ""


class LLMComposer:
    """与 AgentNodes.composer 解耦的 LLM 生成器。

    compose(state) 是主接口；stream(state) 供需要逐 token 消费的调用方使用。
    """

    def __init__(
        self,
        settings: Settings,
        registry: ToolRegistry,
        client: Any | None = None,
        prompt_path: Path | None = None,
    ):
        self.settings = settings
        self.registry = registry
        self.model = (
            settings.agent.llm.model
            if settings.agent.llm.model not in ("", "mock-evidence-composer")
            else "deepseek-chat"
        )
        self.base_url = settings.agent.llm.base_url or "https://api.deepseek.com"
        self.timeout_s = float(settings.agent.llm.timeout_s or 15.0)
        self.temperature = float(settings.agent.llm.temperature)

        path = prompt_path or (Path(settings.root) / "configs" / "prompts" / "composer_v1.md")
        self.prompt_template = path.read_text(encoding="utf-8")

        if client is not None:
            self.client = client
        else:
            api_key = os.getenv("DEEPSEEK_API_KEY")
            if not api_key:
                raise RuntimeError("DEEPSEEK_API_KEY 未设置，无法启用 LLMComposer")
            self.client = OpenAI(
                api_key=api_key,
                base_url=self.base_url,
                timeout=self.timeout_s,
            )

    def build_prompt(self, state: dict[str, Any]) -> str:
        question = state.get("normalized_message") or state.get("message") or ""
        evidence = [self._doc_evidence(doc) for doc in state.get("retrieved_docs", [])]
        evidence_text = json.dumps(evidence, ensure_ascii=False, indent=2) if evidence else "[]"
        return self.prompt_template.replace("{{question}}", question).replace(
            "{{evidence}}", evidence_text
        )

    def stream(self, state: dict[str, Any]) -> Iterator[str]:
        prompt = self.build_prompt(state)
        stream = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=self.temperature,
            stream=True,
            timeout=self.timeout_s,
        )
        for chunk in stream:
            choices = getattr(chunk, "choices", None) or []
            if not choices:
                continue
            delta = getattr(choices[0], "delta", None)
            content = getattr(delta, "content", None) if delta is not None else None
            if content:
                yield content

    def compose(
        self,
        state: dict[str, Any],
        on_token: Callable[[str], None] | None = None,
    ) -> ComposerResult:
        start = time.perf_counter()
        try:
            chunks: list[str] = []
            for token in self.stream(state):
                chunks.append(token)
                if on_token is not None:
                    on_token(token)

            answer = "".join(chunks).strip()
            if not answer:
                raise RuntimeError("LLM 返回空内容")

            citations, citation_invalid, cleaned_answer = self._post_verify(answer, state)
            return ComposerResult(
                answer=cleaned_answer,
                citations=citations,
                citation_invalid=citation_invalid,
                latency_ms=round((time.perf_counter() - start) * 1000, 2),
                model=self.model,
            )
        except Exception as exc:
            logger.exception("LLMComposer 调用失败，将降级到确定性 composer")
            return ComposerResult(
                answer="",
                citations=[],
                degraded=True,
                error=f"{type(exc).__name__}: {exc}",
                latency_ms=round((time.perf_counter() - start) * 1000, 2),
                model=self.model,
            )

    def _post_verify(
        self,
        answer: str,
        state: dict[str, Any],
    ) -> tuple[list[Citation], bool, str]:
        """生成后核验：只保留 verify_citation 通过的引用，并移除无效标记。"""
        evidence_ids = {doc.doc_id for doc in state.get("retrieved_docs", [])}
        cited_ids = list(dict.fromkeys(CITATION_RE.findall(answer)))
        ctx = ToolContext(
            trace_id=state.get("trace_id", ""),
            user_role=state.get("user_role", "family"),
            access_level=int(state.get("access_level", 0)),
            user_profile=state.get("user_profile", {}),
        )

        citations: dict[str, Citation] = {}
        invalid_ids: set[str] = set()
        for doc_id in cited_ids:
            if doc_id not in evidence_ids:
                invalid_ids.add(doc_id)
                continue
            result = self.registry.execute("verify_citation", {"doc_id": doc_id}, ctx)
            if result.ok and result.data.get("valid") and result.data.get("doc"):
                doc = Document.from_payload(result.data["doc"])
                citations[doc_id] = Citation.from_document(doc)
            else:
                invalid_ids.add(doc_id)

        cleaned = answer
        for doc_id in invalid_ids:
            cleaned = cleaned.replace(f"[{doc_id}]", "").strip()

        citation_invalid = bool(evidence_ids) and (not citations or bool(invalid_ids))
        return list(citations.values()), citation_invalid, cleaned

    @staticmethod
    def _doc_evidence(doc: Document) -> dict[str, Any]:
        """只做证据序列化，不包含 Prompt 指令文本。"""
        return {
            "doc_id": doc.doc_id,
            "title": doc.title,
            "content": doc.content,
            "authority": doc.authority,
            "article_no": doc.article_no,
            "effective_date": doc.effective_date,
            "region": doc.region,
            "ethnicity_religion": doc.ethnicity_religion,
            "is_sample": doc.is_sample,
        }


def build_llm_composer(settings: Settings, registry: ToolRegistry) -> LLMComposer | None:
    """仅当 provider=deepseek 且环境变量存在时启用；否则使用确定性 composer。"""
    if settings.agent.llm.provider != "deepseek":
        return None
    if not os.getenv("DEEPSEEK_API_KEY"):
        logger.warning("DEEPSEEK_API_KEY 未设置，LLMComposer 未启用，使用确定性 composer")
        return None
    return LLMComposer(settings, registry)
