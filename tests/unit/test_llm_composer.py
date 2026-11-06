import logging

import pytest

from everrag.llm.composer import LLMComposer
from tests.fakes import FakeClient, make_state


def test_llm_composer_streams_tokens_and_valid_citations(container):
    chunks = ["根据现有资料，", "跨省运输需办理相关手续 [reg_002]。", "建议咨询当地机构。"]
    composer = LLMComposer(container.settings, container.registry, client=FakeClient(chunks=chunks))

    tokens: list[str] = []
    result = composer.compose(make_state(container), on_token=tokens.append)

    assert result.degraded is False
    assert result.answer == "".join(chunks)
    assert [citation.doc_id for citation in result.citations] == ["reg_002"]
    assert result.citation_invalid is False
    assert tokens == chunks
    assert result.model == "deepseek-chat"


def test_llm_composer_stream_yields_tokens(container):
    composer = LLMComposer(
        container.settings,
        container.registry,
        client=FakeClient(chunks=["第一段", "第二段", "第三段"]),
    )

    assert list(composer.stream(make_state(container))) == ["第一段", "第二段", "第三段"]


def test_llm_composer_removes_invalid_citation(container):
    chunks = ["根据资料，需要办理 [fake_999] 手续 [reg_002]。"]
    composer = LLMComposer(container.settings, container.registry, client=FakeClient(chunks=chunks))

    result = composer.compose(make_state(container))

    assert result.citation_invalid is True
    assert [citation.doc_id for citation in result.citations] == ["reg_002"]
    assert "[fake_999]" not in result.answer
    assert "[reg_002]" in result.answer


def test_llm_composer_marks_missing_citation(container):
    composer = LLMComposer(
        container.settings,
        container.registry,
        client=FakeClient(chunks=["根据资料，需要办理相关手续。"]),
    )

    result = composer.compose(make_state(container))

    assert result.citation_invalid is True
    assert result.citations == []


def test_llm_composer_timeout_degrades_and_logs(container, caplog):
    composer = LLMComposer(
        container.settings,
        container.registry,
        client=FakeClient(error=TimeoutError("timed out")),
    )

    with caplog.at_level(logging.ERROR, logger="everrag.llm.composer"):
        result = composer.compose(make_state(container))

    assert result.degraded is True
    assert result.answer == ""
    assert "TimeoutError" in result.error
    assert any("LLMComposer" in record.message for record in caplog.records)


def test_llm_composer_empty_response_degrades(container):
    composer = LLMComposer(container.settings, container.registry, client=FakeClient(chunks=[]))

    result = composer.compose(make_state(container))

    assert result.degraded is True
    assert "RuntimeError" in result.error


def test_prompt_is_externalized(container):
    composer = LLMComposer(
        container.settings,
        container.registry,
        client=FakeClient(chunks=["ok [reg_002]"]),
    )
    prompt = composer.build_prompt(make_state(container))

    assert "跨省运输遗体需要哪些材料" in prompt
    assert "reg_002" in prompt
    assert "{{question}}" not in prompt
    assert "{{evidence}}" not in prompt

    template = (container.settings.root / "configs" / "prompts" / "composer_v1.md").read_text(
        encoding="utf-8"
    )
    for phrase in ("温和", "只能基于", "doc_id", "无法确认"):
        assert phrase in template


def test_llm_composer_requires_api_key_when_client_not_injected(container, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        LLMComposer(container.settings, container.registry)


def test_llm_composer_uses_deepseek_defaults(container):
    composer = LLMComposer(container.settings, container.registry, client=FakeClient(chunks=["x"]))
    assert composer.model == "deepseek-chat"
    assert composer.base_url == "https://api.deepseek.com"
    assert composer.timeout_s == 15.0
