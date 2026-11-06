"""配置加载：configs/*.yaml + 环境变量覆盖。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field


class LLMConfig(BaseModel):
    provider: str = "mock"
    model: str = "deepseek-chat"
    base_url: str = "https://api.deepseek.com"
    api_key: str = ""
    temperature: float = 0.2
    timeout_s: float = 15.0


class AgentConfig(BaseModel):
    max_steps: int = 12
    max_tool_calls: int = 8
    max_replans: int = 2
    max_revisions: int = 1
    min_evidence_docs: int = 1
    min_retrieval_score: float = 0.15
    faq_fast_path_threshold: float = 0.85
    crisis_hotline: str = "12356"
    llm: LLMConfig = Field(default_factory=LLMConfig)


class RetrievalConfig(BaseModel):
    backend: Literal["bm25", "memory"] = "bm25"
    top_k: int = 5
    min_score: float = 0.15
    regulation_min_score: float = 0.05
    # BM25 原始分无上界，不能复用 memory 的覆盖率阈值 min_score。
    min_score_bm25: float = 0.15
    collections: dict[str, str]
    faq_path: str


class GuardrailConfig(BaseModel):
    crisis_keywords: list[str]
    injection_patterns: list[str]
    banned_output_patterns: list[str]
    pii_patterns: dict[str, str]


class Settings(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    root: Path
    agent: AgentConfig
    retrieval: RetrievalConfig
    guardrails: GuardrailConfig


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"配置文件不存在: {path}")
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise TypeError(f"配置文件必须是 YAML 对象: {path}")
    return data


def _resolve(root: Path, value: str) -> str:
    p = Path(value)
    return str(p if p.is_absolute() else (root / p).resolve())


def load_settings(config_dir: str | Path | None = None) -> Settings:
    root = Path(os.getenv("EVERRAG_ROOT") or Path(__file__).resolve().parents[2]).resolve()
    cfg_dir = Path(config_dir) if config_dir else root / "configs"

    agent_raw = _load_yaml(cfg_dir / "agent.yaml")
    agent = AgentConfig(
        **agent_raw.get("agent", {}),
        llm=LLMConfig(**agent_raw.get("llm", {})),
    )
    retrieval_raw = _load_yaml(cfg_dir / "retrieval.yaml")["retrieval"]
    retrieval = RetrievalConfig(
        backend=os.getenv("RETRIEVAL_BACKEND") or retrieval_raw.get("backend", "bm25"),
        top_k=int(retrieval_raw.get("top_k", 5)),
        min_score=float(retrieval_raw.get("min_score", 0.15)),
        regulation_min_score=float(retrieval_raw.get("regulation_min_score", 0.05)),
        min_score_bm25=float(retrieval_raw.get("min_score_bm25", 0.15)),
        collections={
            name: _resolve(root, path)
            for name, path in retrieval_raw.get("collections", {}).items()
        },
        faq_path=_resolve(root, retrieval_raw["faq_path"]),
    )
    guardrails = GuardrailConfig(**_load_yaml(cfg_dir / "guardrails.yaml"))

    # 环境变量覆盖，便于本地/容器切换
    if os.getenv("LLM_PROVIDER"):
        agent.llm.provider = os.environ["LLM_PROVIDER"]
    if os.getenv("LLM_MODEL"):
        agent.llm.model = os.environ["LLM_MODEL"]
    if os.getenv("LLM_BASE_URL"):
        agent.llm.base_url = os.environ["LLM_BASE_URL"]
    if os.getenv("LLM_API_KEY"):
        agent.llm.api_key = os.environ["LLM_API_KEY"]
    if os.getenv("CRISIS_HOTLINE"):
        agent.crisis_hotline = os.environ["CRISIS_HOTLINE"]

    return Settings(root=root, agent=agent, retrieval=retrieval, guardrails=guardrails)
