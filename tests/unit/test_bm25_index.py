"""BM25 索引层单测：分词、排序、metadata 过滤、边界与热更新。"""

from __future__ import annotations

import pytest

from everrag.retrieval.bm25_index import BM25Index, IndexNotReadyError, tokenize
from everrag.schemas import Document, FAQItem


def make_doc(doc_id: str, title: str, content: str, **kwargs) -> Document:
    return Document(
        doc_id=doc_id,
        kb_id=kwargs.pop("kb_id", "funeral_service"),
        title=title,
        content=content,
        **kwargs,
    )


def make_faq(faq_id: str, question: str, **kwargs) -> FAQItem:
    return FAQItem(
        faq_id=faq_id,
        question=question,
        answer=kwargs.pop("answer", "示例答案"),
        **kwargs,
    )


def filler_docs(count: int = 5) -> list[Document]:
    """增加语料规模，避免 rank_bm25 在 1-2 篇文档时出现负 IDF 边界。"""
    return [
        make_doc(f"zz_filler_{i}", f"无关占位文档{i}", f"阿尔法 贝塔 伽马 德尔塔 {i}")
        for i in range(count)
    ]


def filler_faqs(count: int = 3) -> list[FAQItem]:
    return [
        make_faq(f"zz_faq_{i}", f"无关占位问题{i}", answer=f"欧米伽 {i}")
        for i in range(count)
    ]


def test_tokenize_uses_jieba_and_filters_punctuation_stopwords():
    tokens = tokenize("火化需要准备什么材料？")
    assert tokens == ["火化", "准备", "材料"]
    # 索引与查询共用同一个函数：查询侧不会退化为 str.split。
    assert tokenize("BGE-M3 检索") == ["bge", "m3", "检索"]
    assert tokenize("   ") == []
    assert tokenize("") == []


def test_search_ranks_relevant_document_and_returns_bm25_score():
    docs = {
        "funeral_service": [
            make_doc("d_fire", "火化办理材料", "火化需要死亡证明、逝者身份证明和经办人身份证明。"),
            make_doc("d_burial", "骨灰安葬", "公墓落葬需要墓位手续与安葬时间确认。"),
            *filler_docs(),
        ]
    }
    index = BM25Index(docs, [])

    results = index.search_documents("火化需要什么材料", top_k=5, min_score=0.01)

    assert [doc.doc_id for doc in results] == ["d_fire"]
    assert results[0].score > 0
    assert results[0].score == round(results[0].score, 4)


def test_metadata_filter_runs_before_top_k_truncation():
    docs = {
        "funeral_service": [
            # 北京市文档会拿到最高 BM25 分；如果先截断再过滤，top_k=1 会返回空。
            make_doc(
                "d_beijing",
                "火化材料",
                "火化 材料 火化 材料 火化 材料 火化 材料",
                region="北京市",
            ),
            make_doc("d_gansu", "火化材料", "火化 材料 安葬 流程", region="甘肃省"),
            make_doc("d_national", "骨灰安葬", "骨灰 安葬 流程", region="全国"),
            *filler_docs(),
        ]
    }
    index = BM25Index(docs, [])

    results = index.search_documents(
        "火化材料", top_k=1, min_score=0.01, region="甘肃省"
    )

    assert [doc.doc_id for doc in results] == ["d_gansu"]


def test_access_level_and_role_filter_runs_before_top_k_truncation():
    docs = {
        "funeral_service": [
            make_doc(
                "d_internal",
                "内部接待话术",
                "内部 接待 话术 内部 接待 话术 内部 接待 话术",
                access_level=2,
                visible_to_roles=["counselor"],
            ),
            make_doc("d_public", "家属接待说明", "接待 家属 说明 内部 资料"),
            *filler_docs(),
        ]
    }
    index = BM25Index(docs, [])

    family = index.search_documents(
        "内部接待话术", top_k=1, min_score=0.01, role="family", access_level=0
    )
    counselor = index.search_documents(
        "内部接待话术", top_k=1, min_score=0.01, role="counselor", access_level=2
    )

    assert [doc.doc_id for doc in family] == ["d_public"]
    assert [doc.doc_id for doc in counselor] == ["d_internal"]


def test_ethnicity_and_religion_filters():
    docs = {
        "cultural_custom": [
            make_doc(
                "d_han",
                "汉族丧葬习俗",
                "汉族 丧葬 习俗 汉族 丧葬 习俗 汉族 丧葬 习俗",
                kb_id="cultural_custom",
                ethnicity="汉族",
                religion="无",
            ),
            make_doc(
                "d_hui",
                "回族丧葬习俗",
                "回族 丧葬 习俗",
                kb_id="cultural_custom",
                ethnicity="回族",
                religion="伊斯兰教",
            ),
            *filler_docs(),
        ]
    }
    index = BM25Index(docs, [])

    by_ethnicity = index.search_documents(
        "丧葬习俗", top_k=5, min_score=0.01, ethnicity="回族"
    )
    by_religion = index.search_documents(
        "丧葬习俗", top_k=5, min_score=0.01, religion="伊斯兰教"
    )

    # 与内存实现一致：doc 字段为空时不因过滤条件被排除；有值时必须包含目标值。
    assert [doc.doc_id for doc in by_ethnicity] == ["d_hui"]
    assert [doc.doc_id for doc in by_religion] == ["d_hui"]


def test_collections_and_effective_only_filters():
    docs = {
        "funeral_service": [make_doc("d_fun", "火化材料", "火化 材料"), *filler_docs()],
        "regulation": [
            make_doc(
                "d_expired",
                "火化规定",
                "火化 材料 规定 火化 材料 规定",
                kb_id="regulation",
                effective_date="2000-01-01",
                expiry_date="2001-01-01",
            )
        ],
    }
    index = BM25Index(docs, [])

    only_funeral = index.search_documents(
        "火化材料", collections=["funeral_service"], top_k=5, min_score=0.01
    )
    effective_only = index.search_documents(
        "火化材料",
        collections=["regulation"],
        top_k=5,
        min_score=0.01,
        effective_only=True,
    )

    assert [doc.doc_id for doc in only_funeral] == ["d_fun"]
    assert effective_only == []


def test_empty_query_returns_empty_list_without_exception():
    index = BM25Index({"funeral_service": [make_doc("d1", "火化", "火化 材料")]}, [])

    assert index.search_documents("", top_k=5, min_score=0.0) == []
    assert index.search_documents("   ", top_k=5, min_score=0.0) == []
    assert index.search_faqs("") == []


def test_min_score_filters_results():
    index = BM25Index(
        {"funeral_service": [make_doc("d1", "火化材料", "火化 材料"), *filler_docs()]},
        [],
    )

    results = index.search_documents("火化材料", top_k=5, min_score=0.0)
    assert results[0].doc_id == "d1"
    assert results[0].score > 0
    assert index.search_documents("火化材料", top_k=5, min_score=1e9) == []


def test_index_not_ready_raises_domain_error():
    index = BM25Index(
        {"funeral_service": [make_doc("d1", "火化", "火化 材料")]},
        [],
        autobuild=False,
    )

    assert index.is_ready is False
    with pytest.raises(IndexNotReadyError):
        index.search_documents("火化", top_k=5, min_score=0.0)
    with pytest.raises(IndexNotReadyError):
        index.search_faqs("火化")


def test_rebuild_index_picks_up_new_documents_and_faqs():
    docs = {"funeral_service": [make_doc("d1", "火化材料", "火化 材料"), *filler_docs()]}
    faqs = [make_faq("faq_1", "火化需要什么材料？"), *filler_faqs()]
    index = BM25Index(docs, faqs)

    docs["funeral_service"].append(make_doc("d2", "公墓安葬", "公墓 安葬 流程"))
    faqs.append(make_faq("faq_2", "公墓安葬需要什么手续？"))
    index.rebuild_index()

    docs_hit = index.search_documents("公墓安葬", top_k=5, min_score=0.01)
    faq_hits = index.search_faqs("公墓安葬需要什么手续？", top_k=5, min_score=0.01)

    assert [doc.doc_id for doc in docs_hit] == ["d2"]
    assert [faq.faq_id for faq, _ in faq_hits] == ["faq_2"]


def test_faq_index_is_separate_and_filters_visible_roles():
    faqs = [
        make_faq("faq_public", "火化需要什么材料？", visible_to_roles=["family"]),
        make_faq("faq_staff", "内部接待话术是什么？", visible_to_roles=["funeral_staff"]),
        *filler_faqs(),
    ]
    index = BM25Index({"funeral_service": []}, faqs)

    family_hits = index.search_faqs("内部接待话术", role="family", top_k=5, min_score=0.01)
    staff_hits = index.search_faqs(
        "内部接待话术", role="funeral_staff", top_k=5, min_score=0.01
    )

    assert family_hits == []
    assert [faq.faq_id for faq, _ in staff_hits] == ["faq_staff"]
