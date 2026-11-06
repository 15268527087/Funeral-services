from everrag.schemas import Document


def test_search_returns_relevant_funeral_doc(container):
    docs = container.corpus.search(
        "火化需要准备什么材料",
        collections=["funeral_service"],
        role="family",
        access_level=0,
    )
    assert docs
    assert any(doc.doc_id == "fun_002" for doc in docs)


def test_faq_exact_match(container):
    faq, score = container.corpus.lookup_faq("火化需要准备什么材料？")
    assert faq is not None
    assert faq.faq_id == "faq_002"
    assert score == 1.0


def test_faq_no_match_below_threshold(container):
    faq, score = container.corpus.lookup_faq("今天天气怎么样")
    assert faq is None
    assert score < 0.85


def test_role_isolation_in_search(container):
    family_docs = container.corpus.search(
        "内部接待话术",
        collections=["funeral_service"],
        role="family",
        access_level=0,
    )
    staff_docs = container.corpus.search(
        "内部接待话术",
        collections=["funeral_service"],
        role="funeral_staff",
        access_level=1,
    )
    assert all(doc.doc_id != "fun_006" for doc in family_docs)
    assert any(doc.doc_id == "fun_006" for doc in staff_docs)


def test_region_filter(container):
    gansu = container.corpus.search(
        "公墓安葬",
        collections=["regulation"],
        role="family",
        access_level=0,
        region="甘肃省",
    )
    beijing = container.corpus.search(
        "公墓安葬",
        collections=["regulation"],
        role="family",
        access_level=0,
        region="北京市",
    )
    assert any(doc.doc_id == "reg_004" for doc in gansu)
    assert all(doc.doc_id != "reg_004" for doc in beijing)


def test_document_payload_roundtrip(container):
    doc = container.corpus.get_doc("reg_001")
    assert doc is not None
    payload = doc.to_payload()
    assert "metadata" in payload
    restored = Document.from_payload(payload)
    assert restored.doc_id == doc.doc_id
    assert restored.article_no == doc.article_no
    assert restored.effective_date == doc.effective_date


def test_corpus_counts(container):
    assert container.corpus.doc_count == 13
    assert container.corpus.faq_count == 5
