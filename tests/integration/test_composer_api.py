from fastapi.testclient import TestClient

from everrag.container import AppContainer
from everrag.llm.composer import ComposerResult
from everrag.main import create_app
from everrag.schemas import Citation


class FakeComposer:
    def __init__(self, result: ComposerResult):
        self.result = result

    def compose(self, state):
        return self.result


def test_api_marks_degraded_when_llm_fails():
    container = AppContainer(
        llm_composer=FakeComposer(
            ComposerResult(answer="", degraded=True, error="TimeoutError: timeout")
        )
    )
    client = TestClient(create_app(container))

    response = client.post(
        "/v1/chat",
        json={"message": "惠民殡葬减免政策包括哪些项目？", "user_role": "family"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["degraded"] is True
    assert body["citation_invalid"] is False
    assert body["answer"]


def test_api_marks_citation_invalid_when_llm_citation_is_bad():
    container = AppContainer()
    doc = container.corpus.get_doc("reg_003")
    assert doc is not None
    container.orchestrator.nodes.llm_composer = FakeComposer(
        ComposerResult(
            answer="根据资料，惠民殡葬通常包含基本服务减免 [reg_003]。",
            citations=[Citation.from_document(doc)],
            citation_invalid=True,
        )
    )
    client = TestClient(create_app(container))

    response = client.post(
        "/v1/chat",
        json={"message": "惠民殡葬减免政策包括哪些项目？", "user_role": "family"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["citation_invalid"] is True
    assert body["needs_human"] is True
    assert body["handoff_reason"] == "citation_unverified"


def test_stream_done_includes_degraded_and_citation_invalid(client):
    response = client.post("/v1/chat/stream", json={"message": "惠民殡葬减免政策包括哪些项目？"})
    assert response.status_code == 200
    assert "degraded" in response.text
    assert "citation_invalid" in response.text
