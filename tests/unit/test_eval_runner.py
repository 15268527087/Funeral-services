"""评测映射单测：FAQ 快速路径引用必须覆盖全部 FAQ（或显式声明无对应）。"""

from __future__ import annotations

from eval.run_eval import FAQ_EQUIVALENTS, FAQ_NO_EQUIVALENT
from everrag.config import load_settings
from everrag.ingestion.loader import load_corpus


def test_faq_equivalents_cover_all_faqs_or_declare_no_equivalent():
    docs_by_kb, faqs = load_corpus(load_settings())
    faq_ids = {faq.faq_id for faq in faqs}
    doc_ids = {doc.doc_id for docs in docs_by_kb.values() for doc in docs}
    covered = set(FAQ_EQUIVALENTS) | set(FAQ_NO_EQUIVALENT)

    assert covered == faq_ids
    assert not (set(FAQ_EQUIVALENTS) & set(FAQ_NO_EQUIVALENT))
    assert set(FAQ_EQUIVALENTS.values()) <= doc_ids
    # faq_004 无完全对应文档，显式记录原因，不静默遗漏。
    assert "faq_004" in FAQ_NO_EQUIVALENT
    assert "faq_004" not in FAQ_EQUIVALENTS
    assert FAQ_NO_EQUIVALENT["faq_004"]
