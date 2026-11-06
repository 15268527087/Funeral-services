from everrag.tools.base import ToolContext


def ctx(role="family", level=0):
    return ToolContext(trace_id="tr_test", user_role=role, access_level=level)


def test_registry_has_five_tools(container):
    names = {tool["name"] for tool in container.registry.describe()}
    assert names == {
        "search_knowledge_base",
        "get_faq_answer",
        "search_regulation",
        "verify_citation",
        "lookup_cultural_custom",
    }


def test_search_knowledge_base(container):
    result = container.registry.execute(
        "search_knowledge_base",
        {"query": "火化需要准备什么材料", "collections": ["funeral_service"]},
        ctx(),
    )
    assert result.ok is True
    assert result.trace_id == "tr_test"
    assert result.data["total"] >= 1
    assert result.data["documents"][0]["doc_id"].startswith("fun_")


def test_invalid_tool_args(container):
    result = container.registry.execute("search_knowledge_base", {"query": ""}, ctx())
    assert result.ok is False
    assert result.error.code == "INVALID_ARGS"


def test_unknown_tool(container):
    result = container.registry.execute("delete_database", {}, ctx())
    assert result.ok is False
    assert result.error.code == "TOOL_NOT_FOUND"


def test_faq_tool_hit_and_miss(container):
    hit = container.registry.execute(
        "get_faq_answer", {"question": "火化需要准备什么材料？"}, ctx()
    )
    assert hit.ok is True
    assert hit.data["hit"] is True
    assert hit.data["faq"]["faq_id"] == "faq_002"

    miss = container.registry.execute("get_faq_answer", {"question": "今天天气怎么样"}, ctx())
    assert miss.ok is True
    assert miss.data["hit"] is False


def test_search_regulation_returns_effective_docs(container):
    result = container.registry.execute(
        "search_regulation", {"query": "跨省遗体运输手续"}, ctx()
    )
    assert result.ok is True
    assert result.data["total"] >= 1
    for doc in result.data["documents"]:
        assert doc["metadata"]["effective_date"]
        assert doc["metadata"]["article_no"]


def test_verify_citation_valid_and_mismatch(container):
    valid = container.registry.execute(
        "verify_citation", {"doc_id": "reg_001", "article_no": "第十二条"}, ctx()
    )
    assert valid.ok is True
    assert valid.data["valid"] is True

    mismatch = container.registry.execute(
        "verify_citation", {"doc_id": "reg_001", "article_no": "第一条"}, ctx()
    )
    assert mismatch.ok is True
    assert mismatch.data["valid"] is False
    assert mismatch.data["reason"] == "ARTICLE_MISMATCH"


def test_verify_citation_not_found_and_forbidden(container):
    missing = container.registry.execute("verify_citation", {"doc_id": "nope"}, ctx())
    assert missing.data["valid"] is False
    assert missing.data["reason"] == "NOT_FOUND"

    forbidden = container.registry.execute("verify_citation", {"doc_id": "fun_006"}, ctx())
    assert forbidden.data["valid"] is False
    assert forbidden.data["reason"] == "FORBIDDEN"

    allowed = container.registry.execute(
        "verify_citation", {"doc_id": "fun_006"}, ctx(role="funeral_staff", level=1)
    )
    assert allowed.data["valid"] is True


def test_cultural_lookup_filter(container):
    result = container.registry.execute(
        "lookup_cultural_custom",
        {"query": "回族丧葬习俗", "ethnicity": "回族"},
        ctx(),
    )
    assert result.ok is True
    assert any(doc["doc_id"] == "cul_001" for doc in result.data["documents"])


def test_write_tool_not_registered(container):
    # 阶段 1 只注册读工具；写工具（handoff/crisis）在阶段 2 接入。
    assert container.registry.get("create_handoff_ticket") is None
