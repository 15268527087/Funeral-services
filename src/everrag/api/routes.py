"""FastAPI 路由：同步问答、SSE 流式、引用、反馈、健康检查。"""

from __future__ import annotations

import json
import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from everrag.container import AppContainer
from everrag.schemas import (
    ChatRequest,
    ChatResponse,
    FeedbackRequest,
    HandoffRequest,
)

logger = logging.getLogger(__name__)
router = APIRouter()


def get_container(request: Request) -> AppContainer:
    return request.app.state.container


ContainerDep = Annotated[AppContainer, Depends(get_container)]


def _sse(event: str, data: dict[str, Any]) -> str:
    payload = json.dumps(data, ensure_ascii=False, default=str)
    return f"event: {event}\ndata: {payload}\n\n"


def _chunk_text(text: str, size: int = 24) -> list[str]:
    return [text[i : i + size] for i in range(0, len(text), size)]


@router.post("/v1/chat", response_model=ChatResponse)
def chat(req: ChatRequest, container: ContainerDep) -> ChatResponse:
    result = container.orchestrator.run(req)
    return ChatResponse(**result)


@router.post("/v1/chat/stream")
def chat_stream(req: ChatRequest, container: ContainerDep):
    result = container.orchestrator.run(req)

    def generate():
        for event in result["events"]:
            event_type = event.get("type", "status")
            if event_type == "done":
                continue
            yield _sse(event_type, event)
        for citation in result["citations"]:
            yield _sse("citation", citation.model_dump())
        for chunk in _chunk_text(result["answer"]):
            yield _sse("token", {"text": chunk})
        yield _sse(
            "done",
            {
                "session_id": result["session_id"],
                "trace_id": result["trace_id"],
                "intent": result["intent"],
                "citations": [c.model_dump() for c in result["citations"]],
                "needs_human": result["needs_human"],
                "handoff_reason": result["handoff_reason"],
                "degraded": result["degraded"],
                "citation_invalid": result["citation_invalid"],
            },
        )

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.get("/v1/citations/{doc_id}")
def get_citation(doc_id: str, container: ContainerDep) -> dict[str, Any]:
    doc = container.corpus.get_doc(doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="引用文档不存在")
    return doc.model_dump()


@router.get("/v1/sessions/{session_id}")
def get_session(session_id: str, container: ContainerDep) -> dict[str, Any]:
    return {"session_id": session_id, "history": container.sessions.get(session_id)}


@router.get("/v1/tools")
def list_tools(container: ContainerDep) -> list[dict[str, Any]]:
    return container.registry.describe()


@router.post("/v1/feedback")
def feedback(req: FeedbackRequest) -> dict[str, Any]:
    logger.info("feedback session=%s trace=%s rating=%s", req.session_id, req.trace_id, req.rating)
    return {"ok": True}


@router.post("/v1/handoff")
def handoff(req: HandoffRequest) -> dict[str, Any]:
    logger.info("handoff session=%s reason=%s note=%s", req.session_id, req.reason, req.note)
    return {"ok": True, "ticket_id": f"ho_{req.session_id[-8:]}", "status": "queued"}


@router.get("/healthz")
def healthz(container: ContainerDep) -> dict[str, Any]:
    return {
        "status": "ok",
        "docs": container.corpus.doc_count,
        "faqs": container.corpus.faq_count,
        "tools": len(container.registry.describe()),
    }
