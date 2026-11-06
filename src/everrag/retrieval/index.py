"""内存检索索引。

阶段 1 目标是把检索链路和字段契约跑通，因此使用「中文字符 + 二元组 + 英文词」
的词法匹配，不依赖 Milvus / BGE-M3。阶段 2 保持 search() 签名不变，替换实现即可。
"""

from __future__ import annotations

import re

from everrag.config import Settings
from everrag.ingestion.loader import load_corpus
from everrag.schemas import Document, FAQItem

_CJK_RE = re.compile(r"[一-鿿]")
_LATIN_RE = re.compile(r"[a-z0-9]+")
_PUNCT_RE = re.compile(r"[\s，。！？、；：,.!?;:\"'“”‘’（）()【】\[\]《》<>]+")

_STOP_CHARS = set("的了是在和有我你他她它吗呢吧啊请想问想要什么怎么如何可以哪些一个这个那个")


def tokenize(text: str) -> set[str]:
    text = text.lower()
    tokens: set[str] = set(_LATIN_RE.findall(text))
    chars = [c for c in _CJK_RE.findall(text) if c not in _STOP_CHARS]
    tokens.update(chars)
    tokens.update("".join(chars[i : i + 2]) for i in range(len(chars) - 1))
    return tokens


def normalize_question(text: str) -> str:
    return _PUNCT_RE.sub("", text).lower()


def _score(query: str, doc: Document) -> float:
    q = tokenize(query)
    if not q:
        return 0.0
    body = tokenize(f"{doc.title} {doc.content}")
    title = tokenize(doc.title)
    overlap = q & body
    if not overlap:
        return 0.0
    coverage = len(overlap) / len(q)
    title_coverage = len(q & title) / len(q)
    return 0.7 * coverage + 0.3 * title_coverage


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


class InMemoryCorpus:
    def __init__(self, docs_by_kb: dict[str, list[Document]], faqs: list[FAQItem]):
        self.docs_by_kb = docs_by_kb
        self.faqs = faqs
        self._by_id = {doc.doc_id: doc for docs in docs_by_kb.values() for doc in docs}

    @classmethod
    def from_settings(cls, settings: Settings) -> InMemoryCorpus:
        docs_by_kb, faqs = load_corpus(settings)
        return cls(docs_by_kb, faqs)

    @property
    def doc_count(self) -> int:
        return len(self._by_id)

    @property
    def faq_count(self) -> int:
        return len(self.faqs)

    def get_doc(self, doc_id: str) -> Document | None:
        return self._by_id.get(doc_id)

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
        docs: list[Document] = []
        for kb_id in collections or list(self.docs_by_kb):
            docs.extend(self.docs_by_kb.get(kb_id, []))

        results: list[Document] = []
        for doc in docs:
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
            score = _score(query, doc)
            if score >= min_score:
                results.append(doc.model_copy(update={"score": round(score, 4)}))

        results.sort(key=lambda d: d.score, reverse=True)
        return results[:top_k]

    def lookup_faq(
        self,
        question: str,
        role: str = "family",
        threshold: float = 0.85,
    ) -> tuple[FAQItem | None, float]:
        q_norm = normalize_question(question)
        q_tokens = tokenize(question)
        best: FAQItem | None = None
        best_score = 0.0
        for faq in self.faqs:
            if faq.visible_to_roles and role not in faq.visible_to_roles:
                continue
            if normalize_question(faq.question) == q_norm:
                return faq, 1.0
            f_tokens = tokenize(faq.question)
            if not q_tokens:
                continue
            score = len(q_tokens & f_tokens) / len(q_tokens)
            if score > best_score:
                best, best_score = faq, score
        if best_score >= threshold:
            return best, round(best_score, 4)
        return None, round(best_score, 4)
