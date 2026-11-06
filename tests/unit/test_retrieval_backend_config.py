"""后端工厂阈值分配单测：BM25 与 memory 使用各自的 min_score。"""

from __future__ import annotations

from everrag.config import load_settings
from everrag.retrieval.backend import (
    BM25RetrievalBackend,
    MemoryRetrievalBackend,
    build_retrieval_backend,
)
from everrag.retrieval.index import InMemoryCorpus


def test_factory_assigns_thresholds_per_backend():
    settings = load_settings()
    settings.retrieval.min_score = 0.11
    settings.retrieval.min_score_bm25 = 0.77
    corpus = InMemoryCorpus.from_settings(settings)

    settings.retrieval.backend = "bm25"
    bm25 = build_retrieval_backend(corpus, settings)
    assert isinstance(bm25, BM25RetrievalBackend)
    assert bm25.min_score == 0.77

    settings.retrieval.backend = "memory"
    memory = build_retrieval_backend(corpus, settings)
    assert isinstance(memory, MemoryRetrievalBackend)
    assert memory.min_score == 0.11


def test_min_score_bm25_default_is_loaded_from_config(monkeypatch):
    monkeypatch.delenv("RETRIEVAL_BACKEND", raising=False)
    settings = load_settings()
    assert settings.retrieval.min_score == 0.15
    assert settings.retrieval.min_score_bm25 == 0.15
