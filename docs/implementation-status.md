# 阶段 1 MVP 实现状态

> 最后更新：2026-11-01
> 技术债与计划中能力见 [docs/technical-debt.md](technical-debt.md)：前者记录「故意没做什么」，本文件记录「做了什么」。
> 对应计划：`NEW_README.md` 阶段 1（Agent MVP）
> 约束来源：`CLAUDE.md` 第 2/3/6 节

## 1. 已实现

| 模块 | 实现 | 说明 |
|---|---|---|
| 工程骨架 | `pyproject.toml`、`configs/`、`src/everrag/` | Python 3.11+，FastAPI + Pydantic + LangGraph |
| 知识库 | 3 个样例 Collection（殡仪/法规/文化习俗），13 篇文档 + 5 条 FAQ | `data/samples/*.jsonl`，字段契约见 `CLAUDE.md` |
| 检索 | BM25（rank_bm25 + jieba）默认；`retrieval.backend=memory` 可回退内存词法检索 | 文档与 FAQ 独立索引，应用启动时构建，`rebuild_index()` 热更新；阶段 2 接 BGE-M3 + Milvus |
| 工具 | 5 个：`search_knowledge_base`、`get_faq_answer`、`search_regulation`、`verify_citation`、`lookup_cultural_custom` | 强类型 Schema、超时、权限、结构化错误、审计字段 |
| Agent 图 | LangGraph 状态机：intake → safety → router → FAQ/planner → executor → evidence → composer → critic → finalize | 含 crisis / refuse / smalltalk / grief 分支 |
| LLM 生成 | `LLMComposer`（DeepSeek/OpenAI SDK，流式、降级、生成后引用核验） | 默认 mock；设置 `LLM_PROVIDER=deepseek` + `DEEPSEEK_API_KEY` 启用；Prompt 在 `configs/prompts/composer_v1.md` |
| 安全护栏 | PII 脱敏、危机识别、Prompt 注入检测、输出禁用词、引用缺失/文化提示检查 | 规则型；阶段 2 叠加分类器/LLM Judge |
| API | `/v1/chat`、`/v1/chat/stream`（SSE）、`/v1/citations/{id}`、`/v1/sessions/{id}`、`/v1/tools`、`/v1/feedback`、`/v1/handoff`、`/healthz` | SSE 事件：meta/status/tool_start/tool_result/citation/token/done |
| 记忆 | 进程内最近 10 轮 | 阶段 2 替换为 Redis |
| 可观测 | trace_id、节点/tool 事件 | 阶段 2 接 Langfuse / Prometheus |
| 测试 | 82 个 pytest 用例 | 覆盖护栏、BM25/内存检索、双阈值、FAQ 映射、工具契约、Agent 图、API、LLMComposer 降级/引用核验 |
| 对比脚本 | `scripts/compare_composer.py`、`scripts/compare_retrieval.py`、`scripts/calibrate_min_score.py` | composer 对比支持 `--mock`；检索对比输出 memory vs BM25 Top-3；标定脚本只分析不改配置 |
| 评测 | 10 条冒烟评测集 + 150 条 golden v1 草稿 | `eval/run_eval.py`；smoke 10/10；golden 109 条参与评测、41 条 needs_review，首轮基线见 `docs/eval-baseline-v1.md` |

## 2. 当前为 Mock / 待接入

| 项 | 当前状态 | 阶段 2 计划 |
|---|---|---|
| 向量检索 | BM25 词法检索（`retrieval.backend=bm25`，可回退 `memory`） | BGE-M3 + Milvus 混合检索 + Reranker |
| 生成模型 | 默认确定性 composer；LLMComposer 已实现但需配置 key | 设置 `LLM_PROVIDER=deepseek` + `DEEPSEEK_API_KEY` 启用 DeepSeek；阶段 2 接 vLLM Qwen2.5-14B |
| 意图/路由模型 | 关键词规则 | Fine-tuned Qwen2.5-7B |
| 会话/缓存 | 进程内 | Redis 会话 + FAQ/语义缓存 |
| 数据库 | 无（数据从 JSONL 加载） | MySQL FAQ/事件/审计 |
| LoRA 微调 | 未开始 | 5 万条 SFT，阶段 2 |
| HITL 工作台 | 仅 API 转人工占位 | 审核队列、工单、SLA |
| SSO/RBAC | 角色 + access_level 过滤 | 业务系统 SSO |
| 评测集 | 10 条冒烟 | 850 条分层评测集（450/200/150/50） |

> 样例数据与回答中的法规条款均为 **示例内容**，不可用于真实业务咨询。

## 3. 运行方式

```bash
# 依赖（若未安装）
python -m pip install -e ".[dev]"

# 启动 API
PYTHONPATH=src python -m uvicorn everrag.main:app --reload --port 8000

# 测试
PYTHONPATH=src python -m pytest

# 评测
PYTHONPATH=src python -m eval.run_eval

# 生成对比（无 key 时用 --mock）
PYTHONPATH=src python scripts/compare_composer.py --mock
# DEEPSEEK_API_KEY=... PYTHONPATH=src python scripts/compare_composer.py

# 或使用 Makefile（Windows 需安装 make）
make dev
make test
make eval
```

## 4. API 快速验证

```bash
curl -X POST http://localhost:8000/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"火化需要准备什么材料？","user_role":"family"}'

curl -N -X POST http://localhost:8000/v1/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"message":"我父亲是回族人，在新疆去世，想在甘肃安葬，需要什么手续？"}'
```

## 5. 已知限制

- 检索为 BM25 词法匹配（可回退 `memory`），长问题的召回排序仍会漏掉部分低分但关键的法规文档；已通过 `regulation_min_score=0.05` 与 Policy Agent 二次核验缓解。
- 默认仍使用确定性 composer；`LLMComposer` 已实现，但当前环境未设置 `DEEPSEEK_API_KEY`，尚未做真实模型对比。测试全部使用 mock 流式响应，不调用外部 API。
- 样例法规条款、收费标准、习俗内容均为示例，不能作为真实政策依据。
- 危机场景只做识别与转人工，不替代专业危机干预。
- 阶段 1 只注册 5 个读工具；写工具（工单、危机升级）在阶段 2 接入。
- 检索文档内容尚未做 Prompt 注入隔离；阶段 2 引入来源白名单与内容隔离。
- 尚未接入 RAGAS / Langfuse；当前评测为规则校验 + 引用有效性检查。
- 13 篇语料下 Top-1 一致率 100%，BM25 优势体现在分数区分度，排名靠后结果存在噪声，需在语料扩充后重新评估
- FAQ BM25 索引已就绪，get_faq_answer 接入留到阶段 2 三级缓存任务

## 6. 下一步（阶段 1 收尾）

1. 将样例库扩展到 150 条评测集覆盖的业务场景，补充法规条款与地区习俗。
2. 设置 `DEEPSEEK_API_KEY`，运行 `scripts/compare_composer.py` 做真实模型对比，并把结果写入评测报告。
3. 在 BM25 基础上接入 BGE-M3 + Milvus 混合检索，保持工具契约不变。
4. 补齐工具调用超时、熔断、重试的集成测试。
5. `CLAUDE.md` 目录结构已同步为本仓库实际结构（`src/everrag/`）。
