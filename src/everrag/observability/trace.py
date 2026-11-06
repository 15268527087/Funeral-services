"""Trace ID 生成。阶段 2 接入 Langfuse / OpenTelemetry。"""

from __future__ import annotations

from uuid import uuid4


def new_trace_id() -> str:
    return "tr_" + uuid4().hex[:12]
