"""BM25 检索索引。

阶段 1 用 BM25 替换内存词法检索。索引与查询共用 ``tokenize``，
保证同一文本在两侧被切分成完全相同的 token 序列。

**文档与 FAQ 分开建索引**，原因：

1. ``search_knowledge_base`` 的冻结契约只返回 ``DocumentPayload``；
   ``FAQItem`` 的字段结构不同，混在同一个索引里会导致查询层必须按
   ``source_type`` 分支处理返回载荷，破坏工具契约的稳定性。
2. 文档检索需要 ``region`` / ``ethnicity`` / ``religion`` / ``access_level``
   等 metadata 过滤与 ``top_k`` 截断；FAQ 检索走 ``visible_to_roles``
   与阈值匹配，两者过滤语义不同。

FAQ 索引在应用启动时一并构建，当前 ``get_faq_answer`` 仍沿用原有
覆盖率评分（其 ``threshold=0.85`` 契约不变）；本次只替换
``search_knowledge_base`` 的检索实现。
"""

from __future__ import annotations

import re

import jieba
from rank_bm25 import BM25Okapi

from everrag.schemas import Document, FAQItem

# jieba 会把标点、空白也作为 token 输出；只保留含中文/字母/数字的 token。
_TOKEN_RE = re.compile(r"[0-9a-zA-Z一-鿿]+")

# 中文虚词/疑问词在 BM25 中区分度极低，且会让「请写一首关于春天的诗」这类
# 无关问题因为一个「的」字命中知识库。索引与查询共用同一份停用词表。
_STOPWORDS = frozenset(
    {
        "的", "了", "是", "在", "和", "有", "我", "你", "他", "她", "它",
        "吗", "呢", "吧", "啊", "呀", "哦", "嗯", "请", "想", "问", "要",
        "会", "能", "就", "都", "也", "还", "又", "再", "很", "太", "最",
        "这", "那", "哪", "谁", "什么", "怎么", "如何", "哪些", "哪个",
        "多少", "为什么", "一个", "这个", "那个", "关于", "可以", "需要",
    }
)


class IndexNotReadyError(RuntimeError):
    """BM25 索引尚未构建。"""


def tokenize(text: str) -> list[str]:
    """索引与查询共用的唯一分词器。

    统一使用 ``jieba.cut``，禁止索引侧用 jieba、查询侧用 ``split``。
    token 转小写并过滤纯标点/空白/中文虚词，保证英文与中文混合文本行为一致。
    """
    tokens: list[str] = []
    for token in jieba.cut(text.lower()):
        token = token.strip()
        if token and _TOKEN_RE.fullmatch(token) and token not in _STOPWORDS:
            tokens.append(token)
    return tokens


def _match_region(doc: Document, region: str | None) -> bool:
    if not region:
        return True
    return doc.region in (None, "全国", region)


def _match_attr(value: str | None, wanted: str | None) -> bool:
    if not wanted:
        return True
    if not value:
        return True
    return wanted in value


class BM25Index:
    """文档 + FAQ 的 BM25 索引，启动时构建，可通过 ``rebuild_index`` 热更新。"""

    def __init__(
        self,
        docs_by_kb: dict[str, list[Document]],
        faqs: list[FAQItem],
        *,
        autobuild: bool = True,
    ) -> None:
        self.docs_by_kb = docs_by_kb
        self.faqs = faqs
        # 文档/FAQ 的索引与对应的记录放在同一个元组里，重建时整体替换引用，
        # 避免热更新期间并发查询读到「新文档 + 旧索引」的混合状态。
        self._doc_state: tuple[list[Document], BM25Okapi | None] | None = None
        self._faq_state: tuple[list[FAQItem], BM25Okapi | None] | None = None
        if autobuild:
            self.rebuild_index()

    @property
    def is_ready(self) -> bool:
        return self._doc_state is not None and self._faq_state is not None

    @property
    def document_count(self) -> int:
        return len(self._doc_state[0]) if self._doc_state else 0

    def rebuild_index(self) -> None:
        """基于当前 ``docs_by_kb`` / ``faqs`` 全量重建索引。"""
        documents = [doc for docs in self.docs_by_kb.values() for doc in docs]
        doc_corpus = [tokenize(f"{doc.title} {doc.content}") for doc in documents]
        doc_bm25 = BM25Okapi(doc_corpus) if doc_corpus else None

        faq_snapshot = list(self.faqs)
        faq_corpus = [tokenize(faq.question) for faq in faq_snapshot]
        faq_bm25 = BM25Okapi(faq_corpus) if faq_corpus else None

        # 新索引全部构建完成后一次性替换，查询侧只读一次元组引用。
        self._doc_state = (documents, doc_bm25)
        self._faq_state = (faq_snapshot, faq_bm25)

    def search_documents(
        self,
        query: str,
        collections: list[str] | None = None,
        top_k: int = 5,
        min_score: float = 0.0,
        role: str = "family",
        access_level: int = 0,
        region: str | None = None,
        ethnicity: str | None = None,
        religion: str | None = None,
        effective_only: bool = False,
    ) -> list[Document]:
        """BM25 打分后先做 metadata 过滤，再按分数截断 Top-K。"""
        state = self._doc_state
        if state is None:
            raise IndexNotReadyError("BM25 索引尚未构建，请先调用 rebuild_index()")
        documents, doc_bm25 = state
        if doc_bm25 is None:
            return []

        query_tokens = tokenize(query)
        if not query_tokens:
            return []

        scores = doc_bm25.get_scores(query_tokens)
        # 注意顺序：先对全量文档打分，再做 metadata 过滤，最后才截断 Top-K。
        # 如果先截断再过滤，过滤条件会把候选集打空，召回率明显下降。
        scored: list[tuple[Document, float]] = []
        for doc, score in zip(documents, scores):
            if collections and doc.kb_id not in collections:
                continue
            if not doc.is_visible(role, access_level):
                continue
            if effective_only and not doc.is_effective():
                continue
            if not _match_region(doc, region):
                continue
            if not _match_attr(doc.ethnicity, ethnicity):
                continue
            if not _match_attr(doc.religion, religion):
                continue
            # BM25Okapi 在极小语料上可能给出负分（负 IDF 的 epsilon 下限
            # 仍为负）；相关性分数按契约保持非负，统一截到 0。
            score = max(0.0, float(score))
            if score < min_score:
                continue
            scored.append((doc, score))

        scored.sort(key=lambda item: item[1], reverse=True)
        return [
            doc.model_copy(update={"score": round(score, 4)})
            for doc, score in scored[:top_k]
        ]

    def search_faqs(
        self,
        question: str,
        role: str = "family",
        top_k: int = 5,
        min_score: float = 0.0,
    ) -> list[tuple[FAQItem, float]]:
        """FAQ 独立索引的检索接口（保留给后续 FAQ 检索迁移与对比测试）。"""
        state = self._faq_state
        if state is None:
            raise IndexNotReadyError("BM25 索引尚未构建，请先调用 rebuild_index()")
        faqs, faq_bm25 = state
        if faq_bm25 is None:
            return []

        query_tokens = tokenize(question)
        if not query_tokens:
            return []

        scores = faq_bm25.get_scores(query_tokens)
        scored: list[tuple[FAQItem, float]] = []
        for faq, score in zip(faqs, scores):
            if faq.visible_to_roles and role not in faq.visible_to_roles:
                continue
            score = max(0.0, float(score))
            if score < min_score:
                continue
            scored.append((faq, score))

        scored.sort(key=lambda item: item[1], reverse=True)
        return [(faq, round(score, 4)) for faq, score in scored[:top_k]]
