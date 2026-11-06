"""并排对比内存词法检索与 BM25 的 Top-K 结果。

用法：
    uv run python scripts/compare_retrieval.py
    uv run python scripts/compare_retrieval.py --top-k 5
    uv run python scripts/compare_retrieval.py --dataset eval/datasets/smoke.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from everrag.config import load_settings
from everrag.retrieval.backend import BM25RetrievalBackend, MemoryRetrievalBackend
from everrag.retrieval.bm25_index import BM25Index
from everrag.retrieval.index import InMemoryCorpus
from everrag.schemas import Document

DEFAULT_QUERIES = [
    "火化需要准备什么材料？",
    "低保户可以减免哪些费用？",
    "跨省运输遗体需要哪些手续？",
    "遗体接运办理流程是什么？",
    "公墓安葬需要什么手续？",
    "回族丧葬习俗有哪些要点？",
    "佛教告别仪式有哪些环节？",
    "清明祭扫有什么规定？",
    "生态葬有哪些形式？",
    "殡葬管理条例对建坟有什么规定？",
]


def load_queries(path: str | None) -> list[str]:
    if not path:
        return DEFAULT_QUERIES
    queries: list[str] = []
    with Path(path).open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                queries.append(json.loads(line)["query"])
    return queries


def format_hit(rank: int, doc: Document) -> str:
    return f"    {rank}. {doc.doc_id:<8} {doc.score:>8.4f}  {doc.title}"


def print_backend(label: str, docs: list[Document]) -> None:
    print(f"  [{label}]")
    if not docs:
        print("    （无结果）")
        return
    for rank, doc in enumerate(docs, start=1):
        print(format_hit(rank, doc))


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser()
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--min-score", type=float, default=None)
    parser.add_argument(
        "--dataset",
        default=None,
        help="可选 JSONL 数据集（读取 query 字段）；默认使用脚本内置 10 条查询",
    )
    args = parser.parse_args()

    settings = load_settings()
    corpus = InMemoryCorpus.from_settings(settings)
    memory = MemoryRetrievalBackend(corpus, settings.retrieval.min_score)
    bm25 = BM25RetrievalBackend(
        BM25Index(corpus.docs_by_kb, corpus.faqs),
        settings.retrieval.min_score_bm25,
    )
    # 对比时两个后端使用同一阈值，避免阈值差异掩盖排序差异；
    # 应用内 search_knowledge_base 的 BM25 后端默认使用 min_score_bm25。
    min_score = (
        settings.retrieval.min_score if args.min_score is None else args.min_score
    )
    queries = load_queries(args.dataset)

    print(
        f"compare_retrieval: {len(queries)} queries, top_k={args.top_k}, "
        f"min_score={min_score}\n"
    )

    same_top1 = 0
    for index, query in enumerate(queries, start=1):
        print(f"Q{index:02d} {query}")
        memory_docs = memory.search(
            query, top_k=args.top_k, min_score=min_score, role="family"
        )
        bm25_docs = bm25.search(
            query, top_k=args.top_k, min_score=min_score, role="family"
        )
        print_backend(memory.mode, memory_docs)
        print_backend(bm25.mode, bm25_docs)
        if memory_docs and bm25_docs and memory_docs[0].doc_id == bm25_docs[0].doc_id:
            same_top1 += 1
            print("  Top-1: 一致")
        else:
            print("  Top-1: 不同")
        print()

    print(f"Top-1 一致：{same_top1}/{len(queries)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
