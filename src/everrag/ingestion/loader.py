"""JSONL 知识库加载与元数据校验。

阶段 1 使用 data/samples 下的样例数据；阶段 2 替换为 MinerU + Milvus 管道时，
只需保持 Document 的字段契约不变。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from everrag.config import Settings
from everrag.schemas import Document, FAQItem

UNIVERSAL_REQUIRED = {
    "doc_id",
    "kb_id",
    "doc_type",
    "title",
    "content",
    "access_level",
    "visible_to_roles",
}


def load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"数据文件不存在: {p}")
    rows: list[dict[str, Any]] = []
    with p.open("r", encoding="utf-8") as f:
        for lineno, raw in enumerate(f, start=1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{p}:{lineno} JSON 解析失败: {exc}") from exc
            if not isinstance(row, dict):
                raise TypeError(f"{p}:{lineno} 必须是 JSON 对象")
            rows.append(row)
    return rows


def _load_kb_config(root: Path) -> dict[str, Any]:
    path = root / "configs" / "kb" / "all.yaml"
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_corpus(settings: Settings) -> tuple[dict[str, list[Document]], list[FAQItem]]:
    kb_config = _load_kb_config(settings.root)
    kb_specs = kb_config.get("knowledge_bases", {})

    docs_by_kb: dict[str, list[Document]] = {}
    for kb_id, path in settings.retrieval.collections.items():
        required = set(UNIVERSAL_REQUIRED)
        required.update(kb_specs.get(kb_id, {}).get("required_metadata", []))
        rows = load_jsonl(path)
        docs: list[Document] = []
        for idx, row in enumerate(rows, start=1):
            missing = sorted(required - set(row))
            if missing:
                raise ValueError(f"{path} 第 {idx} 条缺少字段: {', '.join(missing)}")
            if row.get("kb_id") != kb_id:
                raise ValueError(
                    f"{path} 第 {idx} 条 kb_id={row.get('kb_id')!r} 与配置 {kb_id!r} 不一致"
                )
            doc = Document(**row)
            if not doc.is_effective():
                # 样例数据中若出现过期文档，保留但在检索时过滤；这里只提示。
                pass
            docs.append(doc)
        docs_by_kb[kb_id] = docs

    faq_rows = load_jsonl(settings.retrieval.faq_path)
    faqs = [FAQItem(**row) for row in faq_rows]
    return docs_by_kb, faqs
