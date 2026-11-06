"""应用容器：装配配置、检索、工具、护栏、记忆与编排器。"""

from __future__ import annotations

from pathlib import Path

from everrag.agent.orchestrator import Orchestrator
from everrag.config import Settings, load_settings
from everrag.guardrails.guards import Guardrails
from everrag.llm.composer import LLMComposer
from everrag.memory.session import InMemorySessionStore
from everrag.retrieval.backend import RetrievalBackend, build_retrieval_backend
from everrag.retrieval.index import InMemoryCorpus
from everrag.tools.base import ToolRegistry
from everrag.tools.builtin import build_registry


class AppContainer:
    def __init__(
        self,
        config_dir: str | Path | None = None,
        llm_composer: LLMComposer | None = None,
        settings: Settings | None = None,
    ):
        self.settings: Settings = settings or load_settings(config_dir)
        self.corpus = InMemoryCorpus.from_settings(self.settings)
        # 应用启动时构建检索索引；retrieval.backend 决定 bm25 / memory。
        self.retrieval_backend: RetrievalBackend = build_retrieval_backend(
            self.corpus, self.settings
        )
        self.registry: ToolRegistry = build_registry(
            self.corpus, self.settings, retrieval_backend=self.retrieval_backend
        )
        self.guardrails = Guardrails(self.settings.guardrails)
        self.sessions = InMemorySessionStore()
        self.orchestrator = Orchestrator(
            registry=self.registry,
            guardrails=self.guardrails,
            sessions=self.sessions,
            settings=self.settings,
            llm_composer=llm_composer,
        )

    def rebuild_index(self) -> None:
        """热更新检索索引；memory 后端为空操作。"""
        self.retrieval_backend.rebuild_index()
