# 已知技术债与计划中能力

> **使用说明**
> 1. 本文件只记录「有意识推迟」的问题，不是 TODO 列表。随手想到的改进不进来。
> 2. 每条必须写清两件事：**为什么现在不修**、**什么条件下必须修**。
> 3. 未填写「触发条件」的条目视为无效，Review 时直接打回。
> 4. 修复后不删除条目，状态改为 `resolved` 并填写变更记录，保留决策痕迹。
> 5. 本文件与 `docs/implementation-status.md` 分工：前者记录「故意没做什么」，后者记录「做了什么」。

---

## 索引

| ID | 标题 | 类型 | 严重度 | 状态 | 触发条件 | 关联文件 |
|---|---|---|---|---|---|---|
| TD-001 | BM25 min_score 语义漂移 | 债 | 中 | open | 语料扩充到 150 篇前 | `configs/retrieval.yaml:5` 等 |
| TD-002 | evidence_gate 跨工具分数量纲混用 | 债 | 中 | open | 阶段 2 策略路由上线 | `nodes.py:563` 等 |
| CAP-001 | Reranker 重排 | 能力 | — | scheduled | 阶段 2 + 语料 ≥ 150 篇 | `models/bge-reranker-large/` |

---

## 一、技术债

### TD-001 · BM25 min_score 语义漂移

**严重度**：中 ｜ **状态**：open ｜ **发现于**：任务 3（BM25 替换内存检索）验收

**现状**
`retrieval.min_score = 0.15` 原本是内存词法检索的覆盖率阈值（取值 0–1 有界，含义为「覆盖 15% 查询词」）。任务 3 将 `search_knowledge_base` 切换到 BM25 后，同一阈值被直接作用于 BM25 原始分。BM25 分数无上界，取决于 IDF 与语料规模，`score >= 0.15` 已不再等价于任何覆盖率含义。任务 4 已将 BM25 阈值拆分为独立的 `min_score_bm25`，但默认值仍沿用 0.15，未重新标定，因此语义漂移本身尚未消除。

**影响**
- 13 篇样例语料下，相关文档 BM25 分数通常在 2–9 之间，远超 0.15，问题被掩盖。
- 噪声恰好卡线放行：Q08「清明祭扫」第二名 0.1542、第三名 0.1511，均属弱相关但未被过滤。
- 语料扩充后，阈值会同时产生「误杀」与「漏放」两种风险，且无法用单一数值兼顾。

**为什么现在不修**
13 篇语料规模不足以做统计意义上的阈值标定；当前 10 条对比与 10 条冒烟评测全部通过，贸然改动会引入不确定性。

**触发条件（必须修）**
- 语料扩充到 150 篇之前
- 或 `search_regulation` / `lookup_cultural_custom` 切换到 BM25 时同步处理

**修复方案（草案）**
1. `RetrievalConfig` 新增 `min_score_bm25`，与 `min_score` 分离，仅 BM25 后端消费。
2. 用 `scripts/calibrate_min_score.py` 基于相关/不相关文档分数分布标定新阈值。
3. 契约增量写入 `docs/contracts.md §9`。

**关联文件**
`configs/retrieval.yaml:5`、`src/everrag/config.py:37,89`、`src/everrag/tools/builtin.py:61`、`src/everrag/retrieval/bm25_index.py:163`

**变更记录**
2026-11-01 初始登记；同日完成 `min_score_bm25` 字段拆分与后端阈值分配（任务 4 第 2 步），阈值数值仍待语料扩充后标定，状态保持 `open`。

---

### TD-002 · evidence_gate 跨工具分数量纲混用

**严重度**：中 ｜ **状态**：open ｜ **发现于**：任务 3 验收（min_score 梳理时发现）

**现状**
`agent.min_retrieval_score = 0.15` 在 `evidence_gate` 节点基于 `Document.score` 做门禁判断。若同一批 `retrieved_docs` 中同时包含 `search_knowledge_base`（BM25 分数，无上界）与 `search_regulation` / `lookup_cultural_custom`（内存覆盖率分数，0–1）的结果，两个分数量纲不同，直接与同一阈值比较无意义。

**影响**
- 门禁判断在混合来源下不可靠，可能误判「证据充足/不足」。
- 阶段 1 的 `mixed` 意图已会并行调用 `search_knowledge_base`、`search_regulation`、`lookup_cultural_custom`；法规类 mixed 问题由 `has_reg_citation` 决定，非法规 mixed 才会使用 `good` 分数列表，样例集尚未暴露误判。阶段 2 策略路由（SubQuery / Backtrack）上线后，该路径会成为稳定判据。

**为什么现在不修**
阶段 1 为纵向切片，多工具并行检索属阶段 2 范围；现在修等于提前设计策略路由的输入契约，容易返工。

**触发条件（必须修）**
- 阶段 2 策略路由上线，或多工具并行检索结果合并进入 `evidence_gate` 时

**修复方案（草案，三选一）**
- (a) 各后端分数归一化到 0–1 后再比较
- (b) `evidence_gate` 按后端分组，分别应用各自阈值
- (c) `Document` 新增 `score_source` 字段，门禁按来源分别判定

倾向 (c)：侵入最小，且为后续接入 Milvus 预留扩展位。

**关联文件**
`configs/agent.yaml:7`、`src/everrag/config.py:28`、`src/everrag/agent/nodes.py:563`

**变更记录**
2026-11-01 初始登记。

---

## 二、计划中能力

### CAP-001 · Reranker 重排

**状态**：scheduled（阶段 2） ｜ **当前**：无代码、无配置、无调用路径

**现状**
- `RetrievalConfig` 无 reranker 相关字段；`build_retrieval_backend()` 仅支持 `bm25` / `memory`。
- `src/` 下无 `reranker.py`，`pyproject.toml` 无 `FlagEmbedding` / `transformers` / `torch` 依赖。
- `models/bge-reranker-large/` 目录存在但未被任何代码引用。
- `NEW_README.md` 与 `docs/implementation-status.md` 均列为阶段 2 规划。

**设计草案**
1. BM25 召回 `top_N`（N > `top_k`），再执行 metadata 过滤（`region` / `ethnicity` / `religion` / `access_level`）。
2. 将过滤后的候选集送入 reranker 重排，取最终 `top_k`。
3. reranker 模型加载失败、超时或推理异常时，回退到 BM25 原排序，保证检索可用。
4. 配置项置于 `retrieval.reranker.*`，建议字段：`enabled`、`model`、`recall_k`、`top_k`、`timeout_s`、`on_error`。

**为什么现在不做**
13 篇语料下 BM25 Top-3 往往只有 1–3 条候选，重排没有足够的候选集，收益无法验证；reranker 属阶段 2 能力，当前契约冻结范围不含重排。

**触发条件（启动条件）**
阶段 2 上线，且语料规模 ≥ 150 篇；单查询候选达到可重排规模（≥ 10 条）时启动。

**依赖影响**
- 需引入 `FlagEmbedding` / `transformers` / `torch` 等依赖；按 `CLAUDE.md`「不引入未在技术栈中列出的第三方库（需先确认）」，启动前需单独确认。
- `models/bge-reranker-large/` 已有模型文件，但当前未被代码引用。

**关联文件**
`models/bge-reranker-large/`、`NEW_README.md`、`docs/implementation-status.md`

**变更记录**
2026-11-01 初始登记。
