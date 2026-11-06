"""并排对比确定性 composer 与 LLMComposer。

默认调用 DeepSeek（需要 DEEPSEEK_API_KEY）。没有 key 时可使用 --mock 做离线演示：
    PYTHONPATH=src python scripts/compare_composer.py --mock
    DEEPSEEK_API_KEY=... PYTHONPATH=src python scripts/compare_composer.py
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from pathlib import Path
from types import SimpleNamespace

from everrag.container import AppContainer
from everrag.llm.composer import LLMComposer
from everrag.schemas import ChatRequest, Citation, Document

EVIDENCE_ID_RE = re.compile(r'"doc_id"\s*:\s*"([^"]+)"')


class MockStreamingClient:
    """离线演示用；从 prompt 的 evidence JSON 中取 doc_id，生成带引用的回答。"""

    def __init__(self):
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        prompt = kwargs["messages"][0]["content"]
        doc_ids = list(dict.fromkeys(EVIDENCE_ID_RE.findall(prompt)))[:2]
        if doc_ids:
            answer = (
                "根据现有资料，建议先确认相关要求。"
                + "".join(f" [{doc_id}]" for doc_id in doc_ids)
                + "\n\n具体办理以当地机构正式规定为准。"
            )
        else:
            answer = "根据现有资料无法确认，建议联系当地殡仪馆或民政部门。"
        chunks = [answer[i : i + 18] for i in range(0, len(answer), 18)]
        return [
            SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=chunk))])
            for chunk in chunks
        ]


def load_cases(path: Path) -> list[dict]:
    cases = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                cases.append(json.loads(line))
    return cases


def build_comparison_state(container: AppContainer, state: dict, question: str) -> dict:
    """FAQ/无检索路径时，为对比补一份同样的证据，保证两个 composer 输入一致。"""
    if state.get("retrieved_docs"):
        return state
    ctx = container.orchestrator.nodes._ctx(state)
    result = container.registry.execute(
        "search_knowledge_base",
        {
            "query": question,
            "collections": ["funeral_service", "regulation", "cultural_custom"],
            "top_k": 5,
        },
        ctx,
    )
    docs = [Document.from_payload(item) for item in result.data.get("documents", [])] if result.ok else []
    citations: list[Citation] = []
    for doc in docs:
        if doc.kb_id == "regulation":
            verified = container.registry.execute("verify_citation", {"doc_id": doc.doc_id}, ctx)
            if verified.ok and verified.data.get("valid") and verified.data.get("doc"):
                citations.append(Citation.from_document(Document.from_payload(verified.data["doc"])))
        else:
            citations.append(Citation.from_document(doc))
    return {**state, "retrieved_docs": docs, "citations": citations}


def citation_stats(container: AppContainer, citations: list[Citation]) -> tuple[int, int]:
    valid = 0
    for citation in citations:
        if citation.doc_id.startswith("faq_"):
            if any(faq.faq_id == citation.doc_id for faq in container.corpus.faqs):
                valid += 1
            continue
        doc = container.corpus.get_doc(citation.doc_id)
        if doc is not None and doc.is_effective():
            valid += 1
    return valid, len(citations)


def truncate(text: str, limit: int = 220) -> str:
    one_line = " ".join(text.split())
    return one_line if len(one_line) <= limit else one_line[:limit] + "…"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mock", action="store_true", help="不调用真实 API，使用离线 mock 流")
    parser.add_argument("--dataset", default="eval/datasets/smoke.jsonl")
    args = parser.parse_args()

    if not args.mock and not os.getenv("DEEPSEEK_API_KEY"):
        print("未设置 DEEPSEEK_API_KEY。请设置 key，或加 --mock 做离线对比。")
        return 1

    container = AppContainer()
    if args.mock:
        llm_composer = LLMComposer(container.settings, container.registry, client=MockStreamingClient())
        llm_label = "LLM:mock"
    else:
        llm_composer = LLMComposer(container.settings, container.registry)
        llm_label = "LLM:deepseek"

    cases = load_cases(Path(args.dataset))
    print(f"compare_composer: {len(cases)} cases, {llm_label}\n")

    for index, case in enumerate(cases, start=1):
        question = case["query"]
        state = container.orchestrator.run_state(
            ChatRequest(
                message=question,
                user_role=case.get("user_role", "family"),
                user_profile=case.get("profile", {}),
            )
        )
        safety_path = state.get("handoff_reason") in ("crisis", "prompt_injection")
        non_retrieval = safety_path or state.get("intent") in ("smalltalk", "grief")

        if non_retrieval:
            comparison_state = state
        else:
            comparison_state = build_comparison_state(container, state, question)

        start = time.perf_counter()
        det_out = (
            {
                "draft_answer": state.get("final_answer", ""),
                "citations": state.get("citations", []),
                "degraded": False,
            }
            if non_retrieval
            else container.orchestrator.nodes.composer(comparison_state)
        )
        det_ms = (time.perf_counter() - start) * 1000
        det_valid, det_total = citation_stats(container, det_out.get("citations", []))

        print(f"=== Q{index}: {question} ===")
        print(
            f"[Deterministic] citations={det_total} valid={det_valid}/{det_total} "
            f"degraded={det_out.get('degraded', False)} latency={det_ms:.2f}ms"
        )
        print(f"  {truncate(det_out.get('draft_answer', ''))}")

        if non_retrieval:
            reason = state.get("handoff_reason") or state.get("intent")
            print(f"[{llm_label}] skipped: non-retrieval path ({reason})")
        else:
            start = time.perf_counter()
            llm_out = llm_composer.compose(comparison_state)
            llm_ms = (time.perf_counter() - start) * 1000
            llm_valid, llm_total = citation_stats(container, llm_out.citations)
            print(
                f"[{llm_label}] citations={llm_total} valid={llm_valid}/{llm_total} "
                f"degraded={llm_out.degraded} citation_invalid={llm_out.citation_invalid} "
                f"latency={llm_ms:.2f}ms"
            )
            print(f"  {truncate(llm_out.answer) if llm_out.answer else '(degraded / empty)'}")
        print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
