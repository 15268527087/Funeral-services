"""工具基类、上下文与注册表。

工具是 Agent 的「手脚」：强类型参数、超时、权限校验、结构化错误、可审计。
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from everrag.config import Settings
from everrag.retrieval.index import InMemoryCorpus
from everrag.schemas import Role, ToolError, ToolResult


class ToolContext(BaseModel):
    trace_id: str = ""
    user_role: Role = "family"
    access_level: int = 0
    user_profile: dict[str, Any] = Field(default_factory=dict)


class BaseTool(ABC):
    name: str
    description: str
    args_model: type[BaseModel]
    risk_level: str = "low"
    timeout_s: float = 3.0

    def __init__(self, corpus: InMemoryCorpus, settings: Settings):
        self.corpus = corpus
        self.settings = settings

    @abstractmethod
    def run(self, args: BaseModel, ctx: ToolContext) -> ToolResult:
        raise NotImplementedError


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"工具重复注册: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> BaseTool | None:
        return self._tools.get(name)

    def describe(self) -> list[dict[str, Any]]:
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "risk_level": tool.risk_level,
                "timeout_s": tool.timeout_s,
                "parameters": tool.args_model.model_json_schema(),
            }
            for tool in self._tools.values()
        ]

    def execute(self, name: str, raw_args: dict[str, Any], ctx: ToolContext) -> ToolResult:
        tool = self.get(name)
        if tool is None:
            return ToolResult(
                ok=False,
                error=ToolError(code="TOOL_NOT_FOUND", message=f"未知工具: {name}"),
                trace_id=ctx.trace_id,
            )
        try:
            args = tool.args_model.model_validate(raw_args)
        except ValidationError as exc:
            return ToolResult(
                ok=False,
                error=ToolError(code="INVALID_ARGS", message=str(exc)),
                trace_id=ctx.trace_id,
            )

        start = time.perf_counter()
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                result = pool.submit(tool.run, args, ctx).result(timeout=tool.timeout_s)
        except FutureTimeoutError:
            result = ToolResult(
                ok=False,
                error=ToolError(
                    code="TOOL_TIMEOUT",
                    message=f"工具 {name} 超时（>{tool.timeout_s}s）",
                    retryable=True,
                ),
            )
        except Exception as exc:  # noqa: BLE001 - 工具边界统一兜底
            result = ToolResult(
                ok=False,
                error=ToolError(code="TOOL_ERROR", message=f"{type(exc).__name__}: {exc}"),
            )

        result.trace_id = ctx.trace_id
        result.elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
        return result
