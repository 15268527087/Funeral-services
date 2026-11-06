"""共享数据模型：文档、引用、工具结果、API 请求/响应。"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Role = Literal[
    "family",
    "funeral_staff",
    "cemetery_advisor",
    "counselor",
    "account_manager",
]

ROLE_ACCESS_LEVELS: dict[str, int] = {
    "family": 0,
    "funeral_staff": 1,
    "cemetery_advisor": 1,
    "counselor": 2,
    "account_manager": 1,
}

ROLE_LABELS: dict[str, str] = {
    "family": "逝者家属",
    "funeral_staff": "殡仪服务师",
    "cemetery_advisor": "墓园顾问",
    "counselor": "心理咨询师",
    "account_manager": "客户经理",
}


class Document(BaseModel):
    """知识库文档。字段与 CLAUDE.md 中的 metadata 约束保持一致。"""

    model_config = ConfigDict(extra="allow")

    doc_id: str
    kb_id: str
    doc_type: str = "manual"
    title: str
    content: str
    score: float = 0.0

    source_url: str | None = None
    authority: str | None = None
    regulation_id: str | None = None
    article_no: str | None = None
    effective_date: str | None = None
    expiry_date: str | None = None

    region: str | None = None
    ethnicity: str | None = None
    religion: str | None = None
    ethnicity_religion: str | None = None

    access_level: int = 0
    visible_to_roles: list[str] = Field(default_factory=list)
    version: str = "v0"
    sensitivity: str = "low"
    is_sample: bool = True

    def metadata(self) -> dict[str, Any]:
        return self.model_dump(exclude={"doc_id", "title", "content", "score"})

    def to_payload(self) -> dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "title": self.title,
            "content": self.content,
            "score": self.score,
            "metadata": self.metadata(),
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> Document:
        data = {**payload, **(payload.get("metadata") or {})}
        data.pop("metadata", None)
        return cls(**data)

    def is_effective(self, today: date | None = None) -> bool:
        today = today or date.today()
        if self.effective_date:
            try:
                if date.fromisoformat(self.effective_date) > today:
                    return False
            except ValueError:
                return False
        if self.expiry_date:
            try:
                if date.fromisoformat(self.expiry_date) < today:
                    return False
            except ValueError:
                return False
        return True

    def is_visible(self, role: str, access_level: int) -> bool:
        return self.access_level <= access_level and (
            not self.visible_to_roles or role in self.visible_to_roles
        )


class Citation(BaseModel):
    doc_id: str
    title: str
    article_no: str | None = None
    authority: str | None = None
    effective_date: str | None = None
    source_url: str | None = None
    quote: str | None = None
    valid: bool = True

    @classmethod
    def from_document(cls, doc: Document, quote_len: int = 100) -> Citation:
        quote = doc.content[:quote_len] + ("…" if len(doc.content) > quote_len else "")
        return cls(
            doc_id=doc.doc_id,
            title=doc.title,
            article_no=doc.article_no,
            authority=doc.authority,
            effective_date=doc.effective_date,
            source_url=doc.source_url,
            quote=quote,
        )


class RiskFlag(BaseModel):
    code: str
    severity: Literal["low", "medium", "high", "critical"] = "low"
    message: str


class ToolError(BaseModel):
    code: str
    message: str
    retryable: bool = False


class ToolResult(BaseModel):
    ok: bool
    data: dict[str, Any] = Field(default_factory=dict)
    error: ToolError | None = None
    trace_id: str = ""
    elapsed_ms: float = 0.0


class Task(BaseModel):
    task_id: str
    goal: str
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)


class FAQItem(BaseModel):
    faq_id: str
    question: str
    answer: str
    intent: str = "unknown"
    region: str = "全国"
    visible_to_roles: list[str] = Field(default_factory=list)
    version: str = "v0"
    is_sample: bool = True


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    session_id: str | None = None
    user_id: str = "anonymous"
    user_role: Role = "family"
    user_profile: dict[str, Any] = Field(default_factory=dict)


class ChatResponse(BaseModel):
    session_id: str
    trace_id: str
    answer: str
    intent: str = "unknown"
    citations: list[Citation] = Field(default_factory=list)
    risk_flags: list[RiskFlag] = Field(default_factory=list)
    needs_human: bool = False
    handoff_reason: str | None = None
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    events: list[dict[str, Any]] = Field(default_factory=list)
    degraded: bool = False
    citation_invalid: bool = False


class FeedbackRequest(BaseModel):
    session_id: str
    trace_id: str
    rating: int = Field(ge=1, le=5)
    comment: str = ""


class HandoffRequest(BaseModel):
    session_id: str
    reason: str = "user_request"
    note: str = ""


class InputGuardResult(BaseModel):
    masked_text: str
    crisis: bool = False
    injection: bool = False
    pii_masked: bool = False
    matched_crisis: list[str] = Field(default_factory=list)
    matched_injection: list[str] = Field(default_factory=list)


class OutputGuardResult(BaseModel):
    ok: bool = True
    flags: list[RiskFlag] = Field(default_factory=list)
    revised_answer: str = ""
