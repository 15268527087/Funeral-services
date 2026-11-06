"""检索后端集成测试：bm25 / memory 切换、契约结构与边界返回。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from everrag.config import load_settings
from everrag.container import AppContainer
from everrag.retrieval.backend import BM25RetrievalBackend
from everrag.retrieval.bm25_index import BM25Index
from everrag.schemas import Document
from everrag.tools.base import ToolContext
from everrag.tools.builtin import build_registry


def make_container(backend: str, **thresholds: float) -> AppContainer:
    settings = load_settings()
    settings.retrieval.backend = backend
    for key, value in thresholds.items():
        setattr(settings.retrieval, key, value)
    return AppContainer(settings=settings)


def ctx(role: str = "family", level: int = 0) -> ToolContext:
    return ToolContext(trace_id="tr_retrieval_test", user_role=role, access_level=level)


def execute(container: AppContainer, args: dict, context: ToolContext | None = None):
    return container.registry.execute(
        "search_knowledge_base", args, context or ctx()
    )


@pytest.mark.parametrize(
    ("backend", "expected_mode"),
    [("bm25", "bm25"), ("memory", "memory-lexical")],
)
def test_retrieval_backend_switch_changes_mode(backend: str, expected_mode: str):
    container = make_container(backend)

    result = execute(
        container,
        {"query": "火化需要准备什么材料", "collections": ["funeral_service"]},
    )

    assert result.ok is True
    assert result.data["retrieval_mode"] == expected_mode
    assert result.data["documents"]


def test_bm25_and_memory_share_top1_and_payload_structure():
    memory = make_container("memory")
    bm25 = make_container("bm25")
    args = {
        "query": "火化需要准备什么材料",
        "collections": ["funeral_service"],
        "top_k": 5,
    }

    memory_result = execute(memory, args)
    bm25_result = execute(bm25, args)

    assert memory_result.ok is True
    assert bm25_result.ok is True
    memory_top = memory_result.data["documents"][0]
    bm25_top = bm25_result.data["documents"][0]
    assert bm25_top["doc_id"] == memory_top["doc_id"]
    assert bm25_top["title"] == memory_top["title"]
    assert bm25_top["metadata"] == memory_top["metadata"]

    # 工具信封与文档载荷字段不得因后端替换而增删。
    assert set(bm25_result.model_dump()) == set(memory_result.model_dump())
    assert set(bm25_result.data) == {"documents", "total", "retrieval_mode"}
    assert set(bm25_top) == {"doc_id", "title", "content", "score", "metadata"}
    assert set(bm25_top["metadata"]) == set(memory_top["metadata"])


def test_search_knowledge_base_schema_unchanged():
    container = make_container("bm25")
    tool = container.registry.get("search_knowledge_base")
    assert tool is not None
    properties = tool.args_model.model_json_schema()["properties"]

    assert set(properties) == {
        "query",
        "collections",
        "region",
        "ethnicity",
        "religion",
        "top_k",
    }
    assert tool.risk_level == "low"
    assert tool.timeout_s == 3.0


def test_bm25_and_memory_use_their_own_min_score():
    args = {
        "query": "火化需要准备什么材料",
        "collections": ["funeral_service"],
    }

    # min_score_bm25 放宽、min_score 收紧：只有 BM25 返回结果。
    bm25_loose = make_container("bm25", min_score=1e9, min_score_bm25=0.01)
    memory_strict = make_container("memory", min_score=1e9, min_score_bm25=0.01)
    assert execute(bm25_loose, args).data["documents"]
    assert execute(memory_strict, args).data["documents"] == []

    # min_score 放宽、min_score_bm25 收紧：只有 memory 返回结果。
    bm25_strict = make_container("bm25", min_score=0.01, min_score_bm25=1e9)
    memory_loose = make_container("memory", min_score=0.01, min_score_bm25=1e9)
    assert execute(bm25_strict, args).data["documents"] == []
    assert execute(memory_loose, args).data["documents"]


def test_bm25_region_metadata_filter():
    container = make_container("bm25")
    base = {"query": "公墓安葬", "collections": ["regulation"], "top_k": 5}

    gansu = execute(container, {**base, "region": "甘肃省"})
    beijing = execute(container, {**base, "region": "北京市"})

    assert any(doc["doc_id"] == "reg_004" for doc in gansu.data["documents"])
    assert all(doc["doc_id"] != "reg_004" for doc in beijing.data["documents"])


def test_bm25_access_level_and_role_filter():
    container = make_container("bm25")
    args = {
        "query": "内部接待话术",
        "collections": ["funeral_service"],
        "top_k": 5,
    }

    family = execute(container, args, ctx(role="family", level=0))
    staff = execute(container, args, ctx(role="funeral_staff", level=1))

    assert all(doc["doc_id"] != "fun_006" for doc in family.data["documents"])
    assert any(doc["doc_id"] == "fun_006" for doc in staff.data["documents"])


def test_empty_query_returns_structured_error():
    container = make_container("bm25")

    empty = execute(container, {"query": ""})
    whitespace = execute(container, {"query": "   "})

    assert empty.ok is False
    assert empty.error is not None and empty.error.code == "INVALID_ARGS"
    assert whitespace.ok is False
    assert whitespace.error is not None and whitespace.error.code == "INVALID_ARGS"


def test_no_results_is_empty_success_per_contract():
    container = make_container("bm25")

    result = execute(container, {"query": "zzqwertyuiop"})

    # docs/contracts.md §1.3.1：空结果不是错误。
    assert result.ok is True
    assert result.data == {
        "documents": [],
        "total": 0,
        "retrieval_mode": "bm25",
    }


def test_container_rebuild_index_hot_update():
    container = make_container("bm25")
    new_doc = Document(
        doc_id="fun_hot_001",
        kb_id="funeral_service",
        title="火星基地守则",
        content="火星基地守则要求登记土豆种植数量。",
    )
    container.corpus.docs_by_kb["funeral_service"].append(new_doc)
    container.corpus._by_id[new_doc.doc_id] = new_doc

    container.rebuild_index()
    result = execute(
        container,
        {"query": "火星基地守则", "collections": ["funeral_service"]},
    )

    assert any(doc["doc_id"] == "fun_hot_001" for doc in result.data["documents"])


def test_index_not_built_returns_structured_error():
    container = make_container("bm25")
    index = BM25Index(
        container.corpus.docs_by_kb,
        container.corpus.faqs,
        autobuild=False,
    )
    registry = build_registry(
        container.corpus,
        container.settings,
        retrieval_backend=BM25RetrievalBackend(
            index, container.settings.retrieval.min_score_bm25
        ),
    )

    result = registry.execute(
        "search_knowledge_base", {"query": "火化"}, ctx()
    )

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "TOOL_ERROR"
    assert "索引" in result.error.message


def test_config_backend_default_and_env_override(monkeypatch):
    monkeypatch.delenv("RETRIEVAL_BACKEND", raising=False)
    assert load_settings().retrieval.backend == "bm25"

    monkeypatch.setenv("RETRIEVAL_BACKEND", "memory")
    assert load_settings().retrieval.backend == "memory"

    monkeypatch.setenv("RETRIEVAL_BACKEND", "unknown")
    with pytest.raises(ValidationError):
        load_settings()
