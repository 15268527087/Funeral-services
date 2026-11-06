"""BM25 阈值标定分析（只分析，不修改配置）。

输出内容：
1. 每条查询的 BM25 Top-K 分数；
2. 三态人工标注（must_relevant / helpful / irrelevant）及排名；
3. must_relevant 最低分与 irrelevant 最高分形成的阈值间隙；
4. 无干净间隙时，给出「召回优先」与「F1 最优」两个折中候选。

标注口径（统一标准）：
- must_relevant：直接回答查询核心问题（列出具体流程 / 材料 / 环节），计入正例；
- helpful：与查询主题相关、提供背景或周边信息，但不直接回答核心问题；
  单独统计，不参与间隙计算，也不计入 precision / recall / F1；
- irrelevant：与查询主题无关，计入负例；
- 特别规则：覆盖多个环节的政策类文档（如惠民政策），对某一具体环节的查询
  应判 helpful，不判 irrelevant。

用法：
    uv run python scripts/calibrate_min_score.py
    uv run python scripts/calibrate_min_score.py --top-k 10
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass

from everrag.config import load_settings
from everrag.retrieval.bm25_index import BM25Index
from everrag.retrieval.index import InMemoryCorpus
from everrag.schemas import Document, FAQItem

QUERIES = [
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

# must_relevant：直接回答查询的文档。
MUST_RELEVANT = {
    "火化需要准备什么材料？": ["fun_002"],
    "低保户可以减免哪些费用？": ["reg_003"],
    "跨省运输遗体需要哪些手续？": ["reg_002"],
    "遗体接运办理流程是什么？": ["fun_001"],
    "公墓安葬需要什么手续？": ["reg_004", "fun_004"],
    "回族丧葬习俗有哪些要点？": ["cul_001"],
    "佛教告别仪式有哪些环节？": ["cul_002"],
    "清明祭扫有什么规定？": ["reg_004"],
    "生态葬有哪些形式？": ["fun_004"],
    "殡葬管理条例对建坟有什么规定？": ["reg_001"],
}

# helpful：不直接回答，但对查询有通用/间接帮助的文档。
# Q01/Q04：reg_003 是覆盖遗体接运、冷藏、火化、骨灰存放的政策类文档，
#           对具体环节查询只提供费用/政策背景 → helpful。
# Q05：cul_003 提供落葬环节和「以公墓规定为准」的间接指引，但没有具体手续。
# Q07：fun_003 提供通用告别仪式环节与宗教仪轨沟通提示，但没有佛教特定仪轨。
HELPFUL = {
    "火化需要准备什么材料？": ["reg_003"],
    "遗体接运办理流程是什么？": ["reg_003"],
    "公墓安葬需要什么手续？": ["cul_003"],
    "佛教告别仪式有哪些环节？": ["fun_003"],
}

# 使用 funeral_staff/access_level=1 以覆盖全部 13 篇文档；
# fun_006 是内部资料，family/access_level=0 视角下不可见。
ROLE = "funeral_staff"
ACCESS_LEVEL = 1


@dataclass
class QueryResult:
    query: str
    documents: list[Document]
    must_relevant: set[str]
    helpful: set[str]
    faq_hits: list[tuple[FAQItem, float]]

    def rank_of(self, doc_id: str) -> int | None:
        for rank, doc in enumerate(self.documents, start=1):
            if doc.doc_id == doc_id:
                return rank
        return None

    def score_of(self, doc_id: str) -> float | None:
        for doc in self.documents:
            if doc.doc_id == doc_id:
                return doc.score
        return None

    def label_of(self, doc_id: str) -> str:
        if doc_id in self.must_relevant:
            return "must_relevant"
        if doc_id in self.helpful:
            return "helpful"
        return "irrelevant"

    def lowest_must_relevant(self) -> tuple[str, float] | None:
        scores = [
            (d.doc_id, d.score)
            for d in self.documents
            if d.doc_id in self.must_relevant
        ]
        return min(scores, key=lambda item: item[1]) if scores else None

    def highest_irrelevant(self) -> tuple[str, float] | None:
        scores = [
            (d.doc_id, d.score)
            for d in self.documents
            if self.label_of(d.doc_id) == "irrelevant"
        ]
        return max(scores, key=lambda item: item[1]) if scores else None


def collect(index: BM25Index, query: str, top_k: int) -> QueryResult:
    documents = index.search_documents(
        query,
        top_k=max(top_k, index.document_count),
        min_score=0.0,
        role=ROLE,
        access_level=ACCESS_LEVEL,
    )
    faq_hits = index.search_faqs(query, role="family", top_k=5, min_score=0.0)
    return QueryResult(
        query=query,
        documents=documents,
        must_relevant=set(MUST_RELEVANT[query]),
        helpful=set(HELPFUL.get(query, [])),
        faq_hits=faq_hits,
    )


def counts(results: list[QueryResult], threshold: float) -> tuple[int, int, int]:
    """返回 TP / FP / FN；helpful 与 score=0 的文档不参与计数。

    precision = TP / (TP + FP)，其中 TP=must_relevant 命中，
    FP=irrelevant 命中；helpful 不计入分子或分母。
    """
    tp = fp = fn = 0
    for result in results:
        for doc in result.documents:
            label = result.label_of(doc.doc_id)
            if label == "helpful":
                continue
            predicted = doc.score > 0 and doc.score >= threshold
            if label == "must_relevant":
                if predicted:
                    tp += 1
                else:
                    fn += 1
            elif predicted:
                fp += 1
    return tp, fp, fn


def metrics(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return precision, recall, f1


def helpful_ratio_at_k(
    results: list[QueryResult], top_k: int
) -> tuple[int, int, float]:
    """Top-K 列表中 helpful 文档占比；独立指标，不参与 precision/F1。"""
    helpful = 0
    total = 0
    for result in results:
        top_docs = result.documents[:top_k]
        total += len(top_docs)
        helpful += sum(
            1 for doc in top_docs if result.label_of(doc.doc_id) == "helpful"
        )
    return helpful, total, (helpful / total if total else 0.0)


def format_ranks(result: QueryResult, doc_ids: set[str]) -> str:
    if not doc_ids:
        return "无"
    parts = []
    for doc_id in sorted(doc_ids):
        rank = result.rank_of(doc_id)
        score = result.score_of(doc_id)
        if rank is None or score is None:
            parts.append(f"{doc_id}=未命中")
        else:
            parts.append(f"{doc_id}=第{rank}名(score={score:.4f})")
    return ", ".join(parts)


def print_query(result: QueryResult, top_k: int) -> None:
    print(f"\n{result.query}")
    print(f"  must_relevant: {', '.join(sorted(result.must_relevant))}")
    print(f"  helpful: {', '.join(sorted(result.helpful)) or '无'}")
    print(f"  BM25 Top-{top_k}:")
    for rank, doc in enumerate(result.documents[:top_k], start=1):
        label = result.label_of(doc.doc_id)
        marker = ""
        if label == "must_relevant":
            marker = " [must]"
        elif label == "helpful":
            marker = " [helpful]"
        print(f"    {rank:2d}. {doc.doc_id:<8} {doc.score:8.4f}{marker}  {doc.title}")

    print(f"  must_relevant 排名: {format_ranks(result, result.must_relevant)}")
    print(f"  helpful 排名（不参与间隙）: {format_ranks(result, result.helpful)}")

    top_docs = result.documents[:top_k]
    helpful_in_top = sum(
        1 for doc in top_docs if result.label_of(doc.doc_id) == "helpful"
    )
    helpful_ratio = helpful_in_top / len(top_docs) if top_docs else 0.0
    print(
        f"  Top-{top_k} 中 helpful 占比: "
        f"{helpful_in_top}/{len(top_docs)} = {helpful_ratio:.1%}"
    )

    faq_text = ", ".join(
        f"{faq.faq_id}={score:.4f}" for faq, score in result.faq_hits
    )
    print(f"  FAQ 索引 Top-{len(result.faq_hits)}: {faq_text}")

    lowest = result.lowest_must_relevant()
    highest = result.highest_irrelevant()
    if lowest and highest:
        if lowest[1] > highest[1]:
            interval = f"({highest[1]:.4f}, {lowest[1]:.4f}]"
        else:
            interval = "无干净间隙"
        print(
            f"  区分度（must vs irrelevant）: 相关最低={lowest[1]:.4f} ({lowest[0]}) | "
            f"不相关最高={highest[1]:.4f} ({highest[0]}) | 间隙={interval}"
        )


def print_calibration(results: list[QueryResult], top_k: int) -> None:
    must_points: list[tuple[str, str, float]] = []
    helpful_points: list[tuple[str, str, float]] = []
    irrelevant_points: list[tuple[str, str, float]] = []
    for result in results:
        for doc in result.documents:
            point = (result.query, doc.doc_id, doc.score)
            label = result.label_of(doc.doc_id)
            if label == "must_relevant":
                must_points.append(point)
            elif label == "helpful":
                helpful_points.append(point)
            else:
                irrelevant_points.append(point)

    min_relevant = min(must_points, key=lambda item: item[2])
    max_irrelevant = max(irrelevant_points, key=lambda item: item[2])
    print("\n=== 阈值标定 ===")
    print(
        f"标注统计: must_relevant={len(must_points)} 篇，"
        f"helpful={len(helpful_points)} 篇（不参与间隙），"
        f"irrelevant={len(irrelevant_points)} 篇"
    )
    print("helpful 单独统计（不参与间隙，也不计入 TP/FP/FN）:")
    for query, doc_id, score in helpful_points:
        print(f"  - {doc_id:<8} {score:8.4f}  {query}")

    print(
        f"全局相关最低分（must_relevant）: {min_relevant[2]:.4f} "
        f"({min_relevant[0]} / {min_relevant[1]})"
    )
    print(
        f"全局不相关最高分（irrelevant）: {max_irrelevant[2]:.4f} "
        f"({max_irrelevant[0]} / {max_irrelevant[1]})"
    )
    helpful_hits, helpful_total, helpful_ratio = helpful_ratio_at_k(results, top_k)
    print(
        f"Top-{top_k} 中 helpful 占比（独立指标）: "
        f"{helpful_hits}/{helpful_total} = {helpful_ratio:.1%}"
    )
    print(
        "precision 口径: TP/(TP+FP)，TP=must_relevant 命中，"
        "FP=irrelevant 命中；helpful 不计入。"
    )

    recall_tp, recall_fp, recall_fn = counts(results, min_relevant[2])
    recall_p, recall_r, recall_f1 = metrics(recall_tp, recall_fp, recall_fn)

    if min_relevant[2] > max_irrelevant[2]:
        print(
            f"干净间隙: ({max_irrelevant[2]:.4f}, {min_relevant[2]:.4f}]"
        )
        print(
            "建议阈值区间: "
            f"({max_irrelevant[2]:.4f}, {min_relevant[2]:.4f}]；"
            f"召回优先取 {min_relevant[2]:.4f}，"
            f"折中可取 {(max_irrelevant[2] + min_relevant[2]) / 2:.4f}"
        )
        print(
            "参考指标（召回优先阈值）: "
            f"TP={recall_tp} FP={recall_fp} FN={recall_fn} "
            f"precision={recall_p:.3f} recall={recall_r:.3f} F1={recall_f1:.3f}"
        )
    else:
        overlap = max_irrelevant[2] - min_relevant[2]
        print(
            f"干净间隙: 无（全局相关最低分 <= 不相关最高分，重叠 {overlap:.4f}）"
        )
        print("建议阈值区间: 空集；单一阈值无法完全分离 must_relevant 与 irrelevant 文档")
        candidates = sorted(
            {doc.score for result in results for doc in result.documents if doc.score > 0}
        )
        best = None
        for threshold in candidates:
            tp, fp, fn = counts(results, threshold)
            precision, recall, f1 = metrics(tp, fp, fn)
            key = (f1, precision, recall, threshold)
            if best is None or key > best[0]:
                best = (key, threshold, tp, fp, fn, precision, recall, f1)
        print(
            "折中候选（召回优先）: "
            f"t={min_relevant[2]:.4f} "
            f"TP={recall_tp} FP={recall_fp} FN={recall_fn} "
            f"precision={recall_p:.3f} recall={recall_r:.3f} F1={recall_f1:.3f}"
        )
        if best is not None:
            _, threshold, tp, fp, fn, precision, recall, f1 = best
            print(
                "折中候选（F1 最优）: "
                f"t={threshold:.4f} "
                f"TP={tp} FP={fp} FN={fn} "
                f"precision={precision:.3f} recall={recall:.3f} F1={f1:.3f}"
            )

    print("F1 数值基于 10 条查询，仅供方向参考，不具备统计意义。")
    print("\n说明: 本脚本只输出分析，不修改 configs/retrieval.yaml。")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser()
    parser.add_argument("--top-k", type=int, default=10)
    args = parser.parse_args()

    settings = load_settings()
    corpus = InMemoryCorpus.from_settings(settings)
    index = BM25Index(corpus.docs_by_kb, corpus.faqs)

    print(
        f"calibrate_min_score: {corpus.doc_count} 篇文档 / "
        f"{corpus.faq_count} 条 FAQ / {len(QUERIES)} 条查询"
    )
    print(f"文档评分视角: role={ROLE}, access_level={ACCESS_LEVEL}（含内部资料 fun_006）")
    print(
        f"当前配置: min_score={settings.retrieval.min_score}, "
        f"min_score_bm25={settings.retrieval.min_score_bm25}, "
        f"regulation_min_score={settings.retrieval.regulation_min_score}"
    )
    print("标注口径: must_relevant=正例；irrelevant=负例；helpful 单独统计，不参与间隙")

    results = [collect(index, query, args.top_k) for query in QUERIES]
    for result in results:
        print_query(result, args.top_k)
    print_calibration(results, args.top_k)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
