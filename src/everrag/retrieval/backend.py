"""检索后端抽象与工厂。

``search_knowledge_base`` 只依赖 ``RetrievalBackend`` 协议；具体用 BM25
还是内存词法检索由 ``build_retrieval_backend`` 按 ``retrieval.backend``
配置决定，工具内部不出现后端分支。
"""

from __future__ import annotations

from typing import Protocol

from everrag.config import Settings
from everrag.retrieval.bm25_index import BM25Index
from everrag.retrieval.index import InMemoryCorpus
from everrag.schemas import Document


class RetrievalBackend(Protocol):
    mode: str
    # 每个后端持有自己的默认阈值；工具只读取该值，不做后端判断。
    min_score: float

    def search(
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
    ) -> list[Document]: ...

    def rebuild_index(self) -> None: ...


class MemoryRetrievalBackend:
    """原有内存词法检索的适配层；不改变 ``InMemoryCorpus.search`` 的行为。"""

    mode = "memory-lexical"

    def __init__(self, corpus: InMemoryCorpus, min_score: float) -> None:
        self.corpus = corpus
        self.min_score = min_score

    def search(
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
        return self.corpus.search(
            query=query,
            collections=collections,
            top_k=top_k,
            min_score=min_score,
            role=role,
            access_level=access_level,
            region=region,
            ethnicity=ethnicity,
            religion=religion,
            effective_only=effective_only,
        )

    def rebuild_index(self) -> None:
        """内存实现没有持久索引，保持接口一致的空操作。"""


class BM25RetrievalBackend:
    mode = "bm25"

    def __init__(self, index: BM25Index, min_score: float) -> None:
        self.index = index
        self.min_score = min_score

    def search(
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
        return self.index.search_documents(
            query=query,
            collections=collections,
            top_k=top_k,
            min_score=min_score,
            role=role,
            access_level=access_level,
            region=region,
            ethnicity=ethnicity,
            religion=religion,
            effective_only=effective_only,
        )

    def rebuild_index(self) -> None:
        self.index.rebuild_index()


def build_retrieval_backend(corpus: InMemoryCorpus, settings: Settings) -> RetrievalBackend:
    """按 ``settings.retrieval.backend`` 选择实现；这里是唯一的切换点。

    阈值也在这里按后端分配：memory 使用覆盖率阈值 ``min_score``，
    BM25 使用独立阈值 ``min_score_bm25``，避免两种分数量纲互相污染。
    """
    backend = settings.retrieval.backend
    if backend == "memory":
        return MemoryRetrievalBackend(corpus, settings.retrieval.min_score)
    if backend == "bm25":
        return BM25RetrievalBackend(
            BM25Index(corpus.docs_by_kb, corpus.faqs),
            settings.retrieval.min_score_bm25,
        )
    raise ValueError(f"未知检索后端: {backend!r}（可选 bm25 / memory）")
