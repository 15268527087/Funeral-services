from everrag.agent.nodes import AgentNodes
from everrag.llm.client import MockLLM
from everrag.llm.composer import LLMComposer
from tests.fakes import FakeClient, make_state


def _nodes(container, composer):
    return AgentNodes(
        container.registry,
        container.guardrails,
        container.settings,
        MockLLM(),
        llm_composer=composer,
    )


def test_llm_failure_falls_back_to_deterministic(container, caplog):
    composer = LLMComposer(
        container.settings,
        container.registry,
        client=FakeClient(error=TimeoutError("timeout")),
    )
    nodes = _nodes(container, composer)

    out = nodes.composer(make_state(container))

    assert out["degraded"] is True
    assert out["citation_invalid"] is False
    assert "参考依据" in out["draft_answer"]
    assert any(event.get("mode") == "degraded" for event in out["events"])


def test_llm_success_uses_llm_answer_and_citations(container):
    composer = LLMComposer(
        container.settings,
        container.registry,
        client=FakeClient(chunks=["根据证据，需要办理手续 [reg_002]。"]),
    )
    nodes = _nodes(container, composer)

    out = nodes.composer(make_state(container))

    assert out["degraded"] is False
    assert out["citation_invalid"] is False
    assert out["draft_answer"].startswith("根据证据")
    assert [citation.doc_id for citation in out["citations"]] == ["reg_002"]


def test_citation_invalid_marks_flag_and_critic_handoff(container):
    composer = LLMComposer(
        container.settings,
        container.registry,
        client=FakeClient(chunks=["根据证据，需要办理 [reg_002] 手续 [fake_999]。"]),
    )
    nodes = _nodes(container, composer)
    state = make_state(container)

    out = nodes.composer(state)
    assert out["citation_invalid"] is True
    assert out["needs_human"] is True
    assert out["handoff_reason"] == "citation_unverified"
    assert any(flag.code == "CITATION_INVALID" for flag in out["risk_flags"])

    critic_state = {**state, **out}
    critic_out = nodes.critic(critic_state)
    assert critic_out["needs_human"] is True
    assert critic_out["handoff_reason"] == "citation_unverified"
    assert "部分引用未能通过核验" in critic_out["final_answer"]
