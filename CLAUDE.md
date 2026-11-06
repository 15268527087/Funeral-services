# CLAUDE.md · EverRAG 项目协作规约

> 本文件抽取自 README 第 2/3/6 节，并已按 `NEW_README.md` 阶段 1 迁移到 `src/everrag/`。硬性约束保持不变；新代码按本文件第三节执行。对外契约已冻结在 `docs/contracts.md`，替换内部实现的任务必须遵守该文件。

## 一、技术栈（版本基线）

| 分类 | 选型 | 说明 |
|---|---|---|
| 语言 | Python 3.11+ | 依赖用 `uv` 管理，锁定 `pyproject.toml` |
| 文档解析 | MinerU | 保留标题层级、表格、列表；扫描件走 OCR 兜底 |
| Embedding | BGE-M3 | 1024 维，COSINE 距离 |
| 向量库 | Milvus 2.4.4 | Docker 单机，HNSW 索引 |
| 缓存 | Redis 7.x | 高频 FAQ，TTL=24h |
| 数据库 | MySQL 8.x | 全量 FAQ + 会话记录 |
| 全文检索 | BM25 | 全量文档兜底（`rank_bm25` 或 ES） |
| LLM | Qwen2.5-7B / 14B | vLLM 部署，OpenAI 兼容接口 |
| 微调 | LoRA | rank=16，alpha=32，1×A100 约 5–6 小时 |
| 服务 | FastAPI + Uvicorn | 提供 HTTP + SSE（WebSocket 阶段 2） |
| 评估 | RAGAS | Faithfulness / Answer Relevancy / Context Precision / Context Recall |

> **不引入 LangChain 全家桶**，检索链路手写，便于控制与排障。

## 二、目录结构

```
everrag/
├── CLAUDE.md                   # AI 协作规约（本文件）
├── README.md
├── NEW_README.md               # 项目计划 V2.0
├── pyproject.toml
├── docker-compose.yml          # Redis + MySQL（Milvus 阶段 2）
├── Makefile
├── .env.example
├── configs/
│   ├── agent.yaml              # 预算、阈值、LLM 配置
│   ├── retrieval.yaml          # 检索路径与阈值
│   ├── guardrails.yaml         # 安全规则
│   ├── kb/all.yaml             # 知识库 schema/必填字段
│   └── prompts/                # Prompt 模板（版本化）
├── data/
│   └── samples/                # 阶段 1 样例知识库
├── src/everrag/
│   ├── main.py                 # FastAPI 入口
│   ├── container.py            # 依赖装配
│   ├── config.py               # 配置加载
│   ├── schemas.py              # 共享数据模型
│   ├── api/routes.py           # /v1/chat、SSE、引用、反馈
│   ├── agent/
│   │   ├── state.py            # AgentState
│   │   ├── nodes.py            # 节点实现
│   │   ├── graph.py            # LangGraph 状态图
│   │   └── orchestrator.py     # 执行入口
│   ├── tools/
│   │   ├── base.py             # 工具注册表/上下文/超时
│   │   └── builtin.py          # 5 个 MVP 工具
│   ├── retrieval/index.py      # 内存检索（阶段 2 换 Milvus）
│   ├── guardrails/guards.py    # PII/危机/注入/输出护栏
│   ├── llm/client.py           # Mock + OpenAI 兼容客户端
│   ├── memory/session.py       # 进程内会话（阶段 2 换 Redis）
│   ├── ingestion/loader.py     # JSONL 加载与元数据校验
│   └── observability/trace.py  # trace_id
├── eval/
│   ├── datasets/smoke.jsonl    # 阶段 1 冒烟评测集
│   └── run_eval.py             # 评测入口
├── tests/
│   ├── unit/
│   ├── contract/
│   └── integration/
└── docs/
    ├── contracts.md            # 阶段 1 对外契约（冻结）
    └── implementation-status.md
```

## 三、开发规范（硬性约束）

以下约束 AI 协作与人工开发均须遵守：

1. **Collection schema 一致**：所有 Collection 的 metadata 必须与 `configs/kb/all.yaml` 一致，代码从 YAML 读取，禁止两处硬编码。
2. **分块保留关键字段**：必须保留 `regulation_id` / `region` / `ethnicity_religion` / `access_level` / `visible_to_roles`。
3. **法规条文禁止截断**：`RegulationChunker` 以「第 X 条」为边界，单条超长则整条保留。
4. **Prompt 外置**：Prompt 模板放 `configs/prompts/` 并按版本号命名，禁止硬编码。
5. **测试覆盖**：每个模块配套 pytest 单测，覆盖率不低于 60%。
6. **密钥管理**：禁止把密钥写进代码，统一走环境变量。
7. **文化敏感性**：文化习俗库内容 100% 经业务顾问审核；民族/宗教类回答人工抽检。
8. **角色隔离**：`user_role` + `access_level` metadata 过滤 + Redis key 角色前缀 + FAQ `visible_to_roles` 三层校验。
9. **契约冻结**：对外契约以 `docs/contracts.md` 为准。替换内部实现（内存检索→BM25、确定性 composer→真实 LLM、进程内记忆→Redis 等）时，不得改变其中的工具 Schema、API、SSE、Citation、AgentState、verify_citation 契约；相关任务提示词必须写明「不得违反 docs/contracts.md」。

**禁止事项**：
- 不自行改动 `docker-compose.yml` 端口
- 不引入未在技术栈中列出的第三方库（需先确认）
- 不写「TODO 后续补充」占位，未实现须明确说明


## 四、任务提示词模板

> 任务提示词模板见 .claude/prompts/task-template.md，调用方式：/task <任务描述>
>
> 替换类任务（检索、LLM、记忆、存储等）必须在提示词中写明「不得违反 docs/contracts.md」，验收需附契约回归结果。

## 五、分析类任务的自检规则

> 触发条件：任务涉及「统计 X 中有多少 Y」「A − B = C」这类推导时，必须应用本节规则。

### 5.1 推导前必须核对三件事

1. **定义域一致**：X 是否包含 Y 之外的元素？例如「51 条意图差异」是否完全覆盖「30 条意图相关失败」？不一定——存在拆分、新增、未进主集的情况。
2. **拆分与合并**：同一逻辑记录在上下游数据里可能是不同的行数。例如 `pre_028` 在预检里是 1 条，在 golden 里拆成 `eval_034` / `eval_035` 两条。
3. **可审计性**：结论中的 C 必须给出完整 ID 列表，且 C 的每个元素都能在 A 里找到。如果给不出 ID 列表，说明推导过程不可审计。

**推导结果与直觉不符时，优先怀疑推导过程**，而不是数据本身。

### 5.2 反面案例（本项目的真实教训）

> 把「34 条全局失败中意图错 21 + 路径错 9 = 30」直接与「51 条意图差异」相减，得出「21 条通过」。
> 实际情况：51 条的去向是 **28 失败 / 18 needs_review / 5 未进主集 / 0 通过**。
> 错因：30 条不是 51 的子集（`eval_148` 与 `eval_132` 不在 51 内；`pre_028` 被拆成两条）。

### 5.3 违反后果

一旦发现推导链缺少 ID 级可审计依据，任务视为未完成，必须回退重做。

---

## 六、验收习惯与 AI 协作原则

### 6.1 每个任务完成前必须执行

```bash
uv run ruff check .
uv run pytest
```

要求 AI 贴出命令输出原文，不接受「应该通过了」的口头结论。

涉及契约改动的任务，额外执行：

```bash
uv run python -m eval.run_eval --dataset eval/datasets/smoke.jsonl
```

确认 smoke 10/10 不退化。

### 6.2 AI 协作原则

- **人类给的前提不一定对**：当你（AI）判断任务描述中的数字、定义、推导关系有误时，先指出、再执行，不要顺着错误前提编造数据。
- **不编造不存在的结论**：如果被要求列出「21 条通过的 ID 列表」而实际是 0 条通过，正确做法是明确回答「不存在，实际 0 条」并给出真实分布，而不是硬凑 21 个 ID。
- **不确定时主动说不知道**：宁可标 `needs_review` 或交回人工判断，也不要为了把任务「完成」而给出未经核实的数据。
- **完成 vs 正确**：任务完成的标准是「结论可审计」，不是「通过率好看」。宁可交一份 68.81% 但每个失败都有归因的基线，也不要交一份 90% 但归因不清的基线。

### 6.3 不允许的操作

- 为让评测通过而放宽 `must_contain` / `must_not_contain` 断言。
- 声称「业务顾问已审核」而实际未审核。
- 把 `needs_review` 用例计入通过率分母。
- 修改已有的 smoke 用例来迁就新的系统行为。
- 在未做预检的情况下标注新的评测用例。

---

## 七、当前阶段与优先级

当前所处阶段：阶段 1 已收官（纵向切片通过，基线 v1 见 `docs/eval-baseline-v1.md`），进入阶段 2 启动期。

### 7.1 阶段 1 基线摘要（供新会话快速定位）

- 150 条 golden 集：109 条参与评测，41 条 `needs_review`，通过 75（68.81%）。
- `must_relevant` 命中 79/81（97.5%）；`forbidden` 违规 0/86。
- 34 条失败归因：意图错 21、路径错 9、must miss 2、其他 2。

### 7.2 阶段 2 首批任务（按优先级）

| 优先级 | 任务 | 依据 |
|---|---|---|
| P0 | 路由层重构：意图分类器升级（Qwen2.5-7B）+ planner collection 选择外置到 `configs/routing.yaml` | 88% 失败集中于此；`eval_113` 暴露 collection 路由的独立缺陷（cemetery 意图只查 `funeral_service`，`reg_004` 未进候选集） |
| P0 | 补语料 P0 级 22 篇 | `docs/corpus-gap-list.md` P0 清单 |
| P1 | 真实 DeepSeek 联调 + baseline v1.1 | 当前 baseline 为确定性 composer 基线 |
| P1 | 修正 B 类 4 条标注（`pre_017` / `pre_018` / `pre_020` / `pre_133`）+ 验证 `eval_113` 修复 | `docs/intent-mismatch-analysis.md` 处置决定列 |
| P2 | 4 种策略路由（Direct / HyDE / SubQuery / Backtrack） | 建立在已修复的 collection 路由之上 |
| P2 | BGE-M3 + Milvus 替换 BM25 | 35 条「召回不足 3 条」用例是主要受益方 |
| P3 | Reranker | CAP-001，语料 ≥ 150 篇后启动 |

### 7.3 当前不做的

- 调 `min_score_bm25`（TD-001 保持 `open`）。
- 实现 reranker（CAP-001 保持 `scheduled`）。
- 改 Agent 图结构（阶段 2 路由层重构只改 planner 内部，不改拓扑）。
- 优化确定性 composer 的 Prompt（真实 LLM 联调后才有意义）。
