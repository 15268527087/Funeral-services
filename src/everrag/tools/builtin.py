"""阶段 1 的 5 个 MVP 工具。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from everrag.config import Settings
from everrag.retrieval.backend import RetrievalBackend, build_retrieval_backend
from everrag.retrieval.bm25_index import IndexNotReadyError
from everrag.retrieval.index import InMemoryCorpus
from everrag.schemas import Document, ToolError, ToolResult
from everrag.tools.base import BaseTool, ToolContext, ToolRegistry

CollectionName = Literal["funeral_service", "regulation", "cultural_custom"]


def _docs_payload(docs: list[Document]) -> list[dict]:
    return [doc.to_payload() for doc in docs]


class SearchKnowledgeBaseArgs(BaseModel):
    query: str = Field(min_length=1)
    collections: list[CollectionName] = Field(default_factory=lambda: ["funeral_service"])
    region: str | None = None
    ethnicity: str | None = None
    religion: str | None = None
    top_k: int = Field(default=5, ge=1, le=20)


class SearchKnowledgeBaseTool(BaseTool):
    name = "search_knowledge_base"
    description = "在殡仪服务/法规/文化习俗知识库中做词法检索，返回带元数据的文档。"
    args_model = SearchKnowledgeBaseArgs
    risk_level = "low"
    timeout_s = 3.0

    def __init__(
        self,
        corpus: InMemoryCorpus,
        settings: Settings,
        retrieval_backend: RetrievalBackend | None = None,
    ):
        super().__init__(corpus, settings)
        # 后端切换只发生在这里；run() 中不出现 bm25 / memory 的分支。
        self.retrieval_backend = retrieval_backend or build_retrieval_backend(corpus, settings)

    def run(self, args: SearchKnowledgeBaseArgs, ctx: ToolContext) -> ToolResult:
        query = args.query.strip()
        if not query:
            return ToolResult(
                ok=False,
                error=ToolError(code="INVALID_ARGS", message="query 不能为空或仅包含空白字符"),
            )
        try:
            docs = self.retrieval_backend.search(
                query=query,
                collections=list(args.collections),
                top_k=args.top_k,
                min_score=self.retrieval_backend.min_score,
                role=ctx.user_role,
                access_level=ctx.access_level,
                region=args.region,
                ethnicity=args.ethnicity,
                religion=args.religion,
            )
        except IndexNotReadyError as exc:
            # 索引未构建是边界状态，返回结构化错误，不把异常抛给注册表/调用方。
            return ToolResult(ok=False, error=ToolError(code="TOOL_ERROR", message=str(exc)))
        return ToolResult(
            ok=True,
            data={
                "documents": _docs_payload(docs),
                "total": len(docs),
                "retrieval_mode": self.retrieval_backend.mode,
            },
        )


class GetFAQAnswerArgs(BaseModel):
    question: str = Field(min_length=1)
    threshold: float = Field(default=0.85, ge=0.0, le=1.0)


class GetFAQAnswerTool(BaseTool):
    name = "get_faq_answer"
    description = "查询高频 FAQ；命中阈值时直接返回标准答案。"
    args_model = GetFAQAnswerArgs
    risk_level = "low"
    timeout_s = 0.3

    def run(self, args: GetFAQAnswerArgs, ctx: ToolContext) -> ToolResult:
        faq, score = self.corpus.lookup_faq(args.question, role=ctx.user_role, threshold=args.threshold)
        if faq is None:
            return ToolResult(ok=True, data={"hit": False, "score": score})
        return ToolResult(
            ok=True,
            data={"hit": True, "score": score, "faq": faq.model_dump()},
        )


class SearchRegulationArgs(BaseModel):
    query: str = Field(min_length=1)
    region: str | None = None
    top_k: int = Field(default=5, ge=1, le=20)


class SearchRegulationTool(BaseTool):
    name = "search_regulation"
    description = "检索现行有效的法规政策条款；自动过滤未生效或已过期文件。"
    args_model = SearchRegulationArgs
    risk_level = "medium"
    timeout_s = 3.0

    def run(self, args: SearchRegulationArgs, ctx: ToolContext) -> ToolResult:
        docs = self.corpus.search(
            query=args.query,
            collections=["regulation"],
            top_k=args.top_k,
            min_score=self.settings.retrieval.regulation_min_score,
            role=ctx.user_role,
            access_level=ctx.access_level,
            region=args.region,
            effective_only=True,
        )
        return ToolResult(
            ok=True,
            data={"documents": _docs_payload(docs), "total": len(docs), "retrieval_mode": "memory-lexical"},
        )


class VerifyCitationArgs(BaseModel):
    doc_id: str = Field(min_length=1)
    article_no: str | None = None


class VerifyCitationTool(BaseTool):
    name = "verify_citation"
    description = "核验法规文号/条款/生效日期，只有通过核验的引用才能进入最终回答。"
    args_model = VerifyCitationArgs
    risk_level = "medium"
    timeout_s = 1.0

    def run(self, args: VerifyCitationArgs, ctx: ToolContext) -> ToolResult:
        doc = self.corpus.get_doc(args.doc_id)
        if doc is None:
            return ToolResult(ok=True, data={"valid": False, "reason": "NOT_FOUND"})
        if not doc.is_visible(ctx.user_role, ctx.access_level):
            return ToolResult(ok=True, data={"valid": False, "reason": "FORBIDDEN"})
        if args.article_no and doc.article_no != args.article_no:
            return ToolResult(ok=True, data={"valid": False, "reason": "ARTICLE_MISMATCH"})
        if not doc.is_effective():
            return ToolResult(ok=True, data={"valid": False, "reason": "NOT_EFFECTIVE"})
        return ToolResult(ok=True, data={"valid": True, "reason": "OK", "doc": doc.to_payload()})


class LookupCulturalCustomArgs(BaseModel):
    query: str = Field(min_length=1)
    region: str | None = None
    ethnicity: str | None = None
    religion: str | None = None
    top_k: int = Field(default=5, ge=1, le=20)


class LookupCulturalCustomTool(BaseTool):
    name = "lookup_cultural_custom"
    description = "按地区/民族/宗教检索文化习俗资料；回答需提示与当地机构确认。"
    args_model = LookupCulturalCustomArgs
    risk_level = "medium"
    timeout_s = 3.0

    def run(self, args: LookupCulturalCustomArgs, ctx: ToolContext) -> ToolResult:
        docs = self.corpus.search(
            query=args.query,
            collections=["cultural_custom"],
            top_k=args.top_k,
            min_score=self.settings.retrieval.min_score,
            role=ctx.user_role,
            access_level=ctx.access_level,
            region=args.region,
            ethnicity=args.ethnicity,
            religion=args.religion,
        )
        return ToolResult(
            ok=True,
            data={"documents": _docs_payload(docs), "total": len(docs), "retrieval_mode": "memory-lexical"},
        )


def build_registry(
    corpus: InMemoryCorpus,
    settings: Settings,
    retrieval_backend: RetrievalBackend | None = None,
) -> ToolRegistry:
    # 索引在装配阶段构建一次；其他工具仍使用原有的内存检索实现。
    backend = retrieval_backend or build_retrieval_backend(corpus, settings)
    registry = ToolRegistry()
    registry.register(SearchKnowledgeBaseTool(corpus, settings, backend))
    for tool_cls in (
        GetFAQAnswerTool,
        SearchRegulationTool,
        VerifyCitationTool,
        LookupCulturalCustomTool,
    ):
        registry.register(tool_cls(corpus, settings))
    return registry
