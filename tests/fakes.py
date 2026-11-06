"""测试用 LLM 流式客户端与状态构造器，不访问真实 API。"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from everrag.schemas import Citation


class FakeCompletions:
    def __init__(self, chunks: list[str] | None = None, error: Exception | None = None):
        self.chunks = chunks or []
        self.error = error
        self.last_kwargs: dict[str, Any] | None = None

    def create(self, **kwargs: Any):
        self.last_kwargs = kwargs
        if self.error is not None:
            raise self.error
        return [
            SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content=chunk))]
            )
            for chunk in self.chunks
        ]


class FakeClient:
    def __init__(self, chunks: list[str] | None = None, error: Exception | None = None):
        self.completions = FakeCompletions(chunks=chunks, error=error)
        self.chat = SimpleNamespace(completions=self.completions)


def make_state(
    container,
    question: str = "跨省运输遗体需要哪些材料？",
    doc_ids: tuple[str, ...] = ("reg_002", "cul_001"),
    intent: str = "mixed",
) -> dict[str, Any]:
    docs = [container.corpus.get_doc(doc_id) for doc_id in doc_ids]
    docs = [doc for doc in docs if doc is not None]
    return {
        "retrieved_docs": docs,
        "citations": [Citation.from_document(doc) for doc in docs],
        "normalized_message": question,
        "message": question,
        "intent": intent,
        "trace_id": "tr_test",
        "user_role": "family",
        "access_level": 0,
        "user_profile": {},
        "events": [],
        "step_count": 0,
        "risk_flags": [],
        "needs_human": False,
        "handoff_reason": None,
        "degraded": False,
        "citation_invalid": False,
    }
