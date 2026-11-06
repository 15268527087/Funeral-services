def test_healthz(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["docs"] == 13
    assert body["faqs"] == 5
    assert body["tools"] == 5


def test_chat_sync(client):
    response = client.post("/v1/chat", json={"message": "火化需要准备什么材料？"})
    assert response.status_code == 200
    body = response.json()
    assert body["answer"]
    assert body["intent"] == "funeral"
    assert body["citations"]
    assert body["trace_id"].startswith("tr_")


def test_chat_stream_sse(client):
    response = client.post("/v1/chat/stream", json={"message": "低保户可以减免哪些费用？"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    text = response.text
    assert "event: token" in text
    assert "event: done" in text
    assert "citations" in text


def test_citation_endpoint(client):
    response = client.get("/v1/citations/fun_001")
    assert response.status_code == 200
    body = response.json()
    assert body["doc_id"] == "fun_001"
    assert body["title"]


def test_citation_not_found(client):
    assert client.get("/v1/citations/not-exist").status_code == 404


def test_tools_endpoint(client):
    response = client.get("/v1/tools")
    assert response.status_code == 200
    assert len(response.json()) == 5


def test_feedback_and_handoff(client):
    feedback = client.post(
        "/v1/feedback",
        json={"session_id": "s1", "trace_id": "tr_1", "rating": 5, "comment": "ok"},
    )
    assert feedback.status_code == 200
    assert feedback.json()["ok"] is True

    handoff = client.post(
        "/v1/handoff",
        json={"session_id": "s1", "reason": "user_request", "note": ""},
    )
    assert handoff.status_code == 200
    assert handoff.json()["status"] == "queued"


def test_session_history(client):
    chat = client.post(
        "/v1/chat",
        json={"message": "你好", "session_id": "session-api-test"},
    )
    assert chat.status_code == 200
    history = client.get("/v1/sessions/session-api-test")
    assert history.status_code == 200
    assert len(history.json()["history"]) >= 2


def test_empty_message_rejected(client):
    response = client.post("/v1/chat", json={"message": ""})
    assert response.status_code == 422
