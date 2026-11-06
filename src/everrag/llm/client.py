"""LLM 客户端。

MVP 默认 mock：回答由 composer 基于检索证据确定性生成，便于离线测试。
配置 LLM_PROVIDER=openai_compatible 后，可接入 vLLM / DeepSeek / 其他 OpenAI 兼容端点。
"""

from __future__ import annotations

import httpx

from everrag.config import LLMConfig


class LLMError(RuntimeError):
    pass


class LLMClient:
    def generate(self, system: str, user: str) -> str:
        raise NotImplementedError


class MockLLM(LLMClient):
    def generate(self, system: str, user: str) -> str:
        # 返回空串表示「使用确定性 composer」，避免在无模型环境下产生不可控内容。
        return ""


class OpenAICompatibleLLM(LLMClient):
    def __init__(self, config: LLMConfig):
        self.config = config
        self.url = config.base_url.rstrip("/") + "/chat/completions"

    def generate(self, system: str, user: str) -> str:
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        payload = {
            "model": self.config.model,
            "temperature": self.config.temperature,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        try:
            resp = httpx.post(self.url, json=payload, headers=headers, timeout=self.config.timeout_s)
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
        except Exception as exc:
            raise LLMError(f"LLM 调用失败: {type(exc).__name__}: {exc}") from exc


def build_llm(config: LLMConfig) -> LLMClient:
    if config.provider == "openai_compatible" and config.base_url:
        return OpenAICompatibleLLM(config)
    return MockLLM()
