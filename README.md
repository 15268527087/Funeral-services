下面是一份可直接放进仓库根目录的 `README.md`。它把项目规划、技术约束、Claude Code + DeepSeek 配置和提示词体系整合成一份文档，`CLAUDE.md` 可以从这里面直接摘出对应章节。

```markdown
# EverRAG · 殡葬服务智能咨询助手

> 企业级 RAG 问答平台。为某殡葬服务集团（覆盖 15 省、殡仪馆/墓园 30+、员工 3000+、年服务家庭 10 万+）
> 整合 8 万+ 文档与 6 万+ FAQ，构建 5 大知识库，提供 7×24 小时秒级智能问答。

- **当前阶段**：阶段 1（MVP 基础版）
- **项目周期**：2024.05 — 2025.03（三期，10 个月）
- **团队**：RAG/后端/数据 1 人 · 前端 1 人 · 业务顾问（兼职）1 人

---

## 目录

- [一、项目简介](#一项目简介)
- [二、技术栈](#二技术栈)
- [三、目录结构](#三目录结构)
- [四、快速开始](#四快速开始)
- [五、项目路线图](#五项目路线图)
- [六、开发规范（硬性约束）](#六开发规范硬性约束)
- [七、Claude Code + DeepSeek 配置](#七claude-code--deepseek-配置)
- [八、提示词体系](#八提示词体系)
- [九、验收与质量门禁](#九验收与质量门禁)
- [十、风险清单](#十风险清单)

---

## 一、项目简介

殡葬服务行业的专业问答系统。集团核心资产是分散在 7+ 业务系统中的殡葬知识文档：

| 知识库 | Collection | 规模 | 主要内容 |
|---|---|---|---|
| 殡仪服务库 | `funeral_service` | 2 万+ 篇 | 接运/冷藏/整容/告别/火化/安葬流程、仪式方案、礼仪规范、用品说明 |
| 墓葬知识库 | `cemetery` | 1.5 万+ 篇 | 墓型介绍、风水知识、安葬流程、祭扫规范 |
| 法规政策库 | `regulation` | 1.5 万+ 篇 | 殡葬管理条例、地方政策、收费标准、惠民政策 |
| 心理疏导库 | `grief_support` | 1.2 万+ 篇 | 悲伤辅导、心理自助、沟通话术、危机干预 |
| 文化习俗库 | `cultural_custom` | 1.8 万+ 篇 | 各地丧葬习俗、宗教信仰礼仪、民族传统、现代殡葬文化 |
| FAQ 库 | `faq` | 6 万+ 条 | 五大知识库高频问答对 |

**核心目标**：殡仪咨询响应从 30 分钟缩短至 3 秒；政策法规引用准确率 ≥ 94%；RAGAS 综合 ≥ 0.86。

---

## 二、技术栈

| 分类 | 选型 | 说明 |
|---|---|---|
| 语言 | Python 3.10 | 依赖用 `uv` 管理，锁定 `pyproject.toml` |
| 文档解析 | MinerU | 保留标题层级、表格、列表；扫描件走 OCR 兜底 |
| Embedding | BGE-M3 | 1024 维，COSINE 距离 |
| 向量库 | Milvus 2.4.4 | Docker 单机，HNSW 索引 |
| 缓存 | Redis 7.x | 高频 FAQ，TTL=24h |
| 数据库 | MySQL 8.x | 全量 FAQ + 会话记录 |
| 全文检索 | BM25 | 全量文档兜底（`rank_bm25` 或 ES） |
| LLM | Qwen2.5-7B / 14B | vLLM 部署，OpenAI 兼容接口 |
| 微调 | LoRA | rank=16，alpha=32，1×A100 约 5–6 小时 |
| 服务 | FastAPI + Uvicorn | 提供 HTTP + WebSocket |
| 评估 | RAGAS | Faithfulness / Answer Relevancy / Context Precision / Context Recall |

> **不引入 LangChain 全家桶**，检索链路手写，便于控制与排障。

---

## 三、目录结构

```
everrag/
├── CLAUDE.md                   # AI 协作规约（从 README 第六/八节摘出）
├── README.md
├── docker-compose.yml
├── pyproject.toml
├── .env.example
├── configs/
│   ├── collections.yaml        # 5 个 Collection schema
│   ├── strategies.yaml         # 策略路由规则
│   └── prompts/                # Prompt 模板（版本化）
├── docker/
│   └── mysql/init/             # 建库建表脚本
├── data_pipeline/
│   ├── connectors/             # 7+ 系统接入适配器
│   ├── parsers/                # MinerU 封装
│   ├── cleaners/
│   ├── chunkers/               # 按服务类型分块
│   └── indexers/               # BGE-M3 + Milvus 写入
├── retrieval/
│   ├── intent/                 # 意图识别（Qwen2.5-7B）
│   ├── strategies/             # Direct / HyDE / SubQuery / Backtrack
│   ├── reranker/
│   └── cache/                  # 三级缓存
├── generation/
│   ├── llm_client.py           # vLLM / API 适配
│   └── prompt_builder.py
├── api/
│   ├── routes/                 # /chat、/faq、/admin
│   └── ws/                     # WebSocket
├── evaluation/
│   ├── golden_dataset/         # Golden Dataset（100 → 300 → 500 条）
│   └── ragas_runner.py
├── finetune/
│   ├── data_builder/
│   └── lora_train.py
└── tests/
```

---

## 四、快速开始

### 4.1 启动基础设施

```bash
cp .env.example .env          # 填写 MySQL 密码、Redis 密码等
docker compose up -d
docker compose ps             # 确认 Milvus / Redis / MySQL 均为 healthy
```

### 4.2 安装依赖

```bash
uv sync
```

### 4.3 初始化 Collection

```bash
uv run python -c "from data_pipeline.indexers.schema import create_collections; create_collections()"
```

### 4.4 启动服务

```bash
uv run uvicorn api.main:app --reload --port 8000
```

### 4.5 跑测试与静态检查

```bash
uv run pytest
uv run ruff check .
```

---

## 五、项目路线图

| 阶段 | 时间 | 目标 | 验收标准 |
|---|---|---|---|
| **阶段 0：地基** | 第 1–2 周 | 环境、架构、数据摸底 | 架构评审通过；数据源清单确认 |
| **阶段 1：MVP** | 2024.05–2024.08 | 2 库 + Direct + FastAPI | 殡仪/法规两库可问答；Golden 100 条；Faithfulness ≥ 0.75 |
| **阶段 2：能力增强** | 2024.08–2024.12 | 5 库 + 意图识别 + 4 策略 + 三级缓存 + LoRA + WebSocket | 意图准确率 ≥ 91%；路由 ≥ 88%；缓存命中 ≥ 35%；Faithfulness ≥ 0.85 |
| **阶段 3：生产优化** | 2025.01–2025.03 | 评估体系、SSO 对接、监控、压测、部署 | RAGAS ≥ 0.86；准确率 ≥ 94%；P95 < 3s；首 Token < 800ms |

### 阶段 1 任务顺序

```
connectors → parsers → chunkers（关键）→ indexers
→ FastAPI 骨架 → Direct 检索 → Prompt 模板 → Golden 100 条评估
```

### 阶段 2 任务顺序

```
扩 3 库 → 三级缓存（Redis → MySQL → BM25）→ 意图识别训练
→ 策略路由（先出计划）→ LoRA 微调 → WebSocket 流式
```

> **原则**：先跑通再优化；数据质量优先于模型能力；评估集先行。

---

## 六、开发规范（硬性约束）

以下约束同时写入 `CLAUDE.md`，AI 协作与人工开发均须遵守：

1. **Collection schema 一致**：所有 Collection 的 metadata 必须与 `configs/collections.yaml` 一致，代码从 YAML 读取，禁止两处硬编码。
2. **分块保留关键字段**：必须保留 `regulation_id` / `region` / `ethnicity_religion` / `access_level` / `visible_to_roles`。
3. **法规条文禁止截断**：`RegulationChunker` 以「第 X 条」为边界，单条超长则整条保留。
4. **Prompt 外置**：Prompt 模板放 `configs/prompts/` 并按版本号命名，禁止硬编码。
5. **测试覆盖**：每个模块配套 pytest 单测，覆盖率不低于 60%。
6. **密钥管理**：禁止把密钥写进代码，统一走环境变量。
7. **文化敏感性**：文化习俗库内容 100% 经业务顾问审核；民族/宗教类回答人工抽检。
8. **角色隔离**：`user_role` + `access_level` metadata 过滤 + Redis key 角色前缀 + FAQ `visible_to_roles` 三层校验。

**禁止事项**：
- 不自行改动 `docker-compose.yml` 端口
- 不引入未在技术栈中列出的第三方库（需先确认）
- 不写「TODO 后续补充」占位，未实现须明确说明

---

## 七、Claude Code + DeepSeek 配置

Claude Code 默认调用 Anthropic API。要让底层使用 DeepSeek，需通过兼容 Anthropic Messages API 的端点转发：

```bash
# 方式一：使用 claude-code-router 做协议转换（Anthropic → OpenAI 格式 → DeepSeek）
export ANTHROPIC_BASE_URL="http://localhost:3456"
export ANTHROPIC_AUTH_TOKEN="<router 分配的 token>"

# 方式二：使用提供 Anthropic 兼容端点的中转服务
export ANTHROPIC_BASE_URL="<中转服务地址>"
export ANTHROPIC_AUTH_TOKEN="<你的密钥>"
```

> **注意**：DeepSeek 官方 API 为 OpenAI 兼容格式，不能仅改 `base_url` 直连，必须经协议转换层。

**适配调整**（因 DeepSeek Agent 能力弱于 Claude）：
- 单次任务范围缩小 30%，一次改 2–3 个文件
- 非平凡任务要求先输出计划，确认后再动手
- 路由规则、字段映射写进 YAML 配置，减少隐式推理
- 接口对接时直接贴上游签名与下游格式
- 坚持「先写测试 → 确认 → 再写实现」

---

## 八、提示词体系

### 8.1 L1：`CLAUDE.md`（项目级长期记忆）

Claude Code 每次会话自动读取仓库根目录的 `CLAUDE.md`。建议内容 = 本文档**第六节（开发规范）+ 第三节（目录结构）+ 第二节（技术栈版本）**。

首次可执行 `/init` 生成初稿，再手动补齐约束。

### 8.2 L2：任务提示词模板

每次下任务使用以下骨架：

```markdown
【背景】一句话说明模块在系统中的位置（引用文档章节号）
【输入】要读哪些文件 / 参考哪些文档段落 / 已有接口契约
【任务】只做一件事，动宾结构，边界清晰
【输出】要产出哪些文件、每个文件职责
【约束】本任务特有约束（版本、算法参数、命名规范）
【验收】跑什么命令、断言什么结果算通过
【不要做】明确排除的范围，防止误改其他模块
```

> **【输入】和【不要做】最容易省略，也最能减少返工。**

### 8.3 L3：任务示例（节选）

**示例：分块器**

```
任务：实现 data_pipeline/chunkers/ 下的两个分块器。

1. FuneralChunker：按"接运→冷藏→整容→告别→火化→安葬"六个环节切分，
   依赖文档标题层级识别环节，chunk 512-800 token，overlap 10%。
2. RegulationChunker：按条款自然分段，以"第X条"为边界，禁止截断完整条款；
   若单条超过 800 token 则整条保留不切。必须提取 regulation_id 和 effective_date。

约束：
- 不要用 LangChain 的 RecursiveCharacterTextSplitter
- token 计数用 tiktoken 的 cl100k_base 近似
- 必须写测试：3 篇样本（殡仪流程手册、法规条文、含表格的习俗文档），
  断言环节识别正确、条款未被截断

验收：uv run pytest tests/chunkers/ -v 全绿。
不要改 schema.py 和索引层。
```

**示例：策略路由**

```
任务：实现 retrieval/strategies/ 下的策略选择器和 4 个检索策略。
先读 configs/strategies.yaml 和 retrieval/intent/ 现有接口。

路由规则（写进 strategies.yaml，代码读配置，不要硬编码 if-else）：
- 单一事实 + intent=法规政策 → Direct
- 模糊研究型 + intent=心理疏导 → HyDE
- 检测到多个实体/多个意图标签 → SubQuery
- 对话历史存在指代（"那""这个""它"）→ Backtrack

每个策略继承 BaseStrategy.retrieve(query, context) -> List[Document]。
SubQuery 用 asyncio.gather 并行检索多 Collection，结果按 id 去重。
Backtrack 最多回溯 5 轮历史。

验收：uv run pytest tests/strategies/ -v，且脚本对 10 条样例查询打印路由结果。
不要动 retrieval/cache/。
```

### 8.4 L4：纠偏提示词

```
刚才你修改了 X，但违反了 CLAUDE.md 第 3 条约束（法规条文不得截断）。
请：
1. 只回滚 X 相关改动，列出改了哪些文件
2. 说明为什么没遵守约束
3. 重新实现，先贴出实现计划让我确认，再动手
```

### 8.5 充分利用的 Claude Code 机制

| 机制 | 用法 | 优先级 |
|---|---|---|
| **计划模式** | 复杂任务先出计划 | 极高 |
| **Hooks（PostToolUse）** | 写完 `.py` 自动跑 `ruff check` + `pytest` | 极高 |
| **`/init`** | 首次生成 `CLAUDE.md` 初稿 | 高 |
| **自定义斜杠命令** | 将 L2 模板存为 `.claude/commands/task.md` | 高 |
| **TodoWrite** | 任务拆 todo 逐项完成 | 高 |
| **子智能体** | 测试/review 拆给 subagent | 中 |
| **`#` 记忆** | 新约束追加进 `CLAUDE.md` | 中 |

---

## 九、验收与质量门禁

### 9.1 每个任务完成前必须执行

```bash
uv run ruff check .
uv run pytest
```

要求 AI 将**命令输出原文**贴出，不接受「应该通过了」的口头结论。

### 9.2 阶段验收指标

| 指标 | 阶段 1 | 阶段 2 | 阶段 3 |
|---|---|---|---|
| 问答准确率 | — | — | ≥ 94% |
| RAGAS 综合 | — | — | ≥ 0.86 |
| Faithfulness | ≥ 0.75 | ≥ 0.85 | ≥ 0.88 |
| 意图分类准确率 | — | ≥ 91% | ≥ 91% |
| 策略路由准确率 | — | ≥ 88% | ≥ 88% |
| 缓存命中率 | — | ≥ 35% | 37% |
| 首 Token 延迟 | < 1.5s | < 1.0s | < 800ms（P95） |
| 整体响应 P95 | — | — | < 3s |

### 9.3 评估集演进

```
阶段 1：100 条（殡仪 + 法规两类）
阶段 2：300 条（覆盖 6 类意图）
阶段 3：500 条（6 类均衡，业务顾问每月抽检新增）
```

> 没有评估集，所有准确率数字都是空话。

---

## 十、风险清单

| 风险 | 影响 | 应对 |
|---|---|---|
| 扫描件/表格解析质量差 | 知识库脏数据，检索不准 | 阶段 0 抽样评估；MinerU 失败走 OCR + 人工抽检 |
| 民族/宗教内容出错 | 文化冒犯，项目致命 | 文化习俗库 100% 业务顾问审核；回答人工抽检 |
| 政策更新不及时 | 引用过期法规 | 法规库监听 + 增量更新，24h 内入库 |
| 微调数据不足 | LoRA 效果不达预期 | 一期即开始积累 SFT 数据，业务顾问深度参与标注 |
| 500 并发扛不住 | 清明/冬至高峰宕机 | vLLM Continuous Batching；阶段 3 压测 |
| 角色越权访问 | 家属看到内部话术 | metadata + Redis key + FAQ 权限三层校验，写测试用例 |
| AI 越界改动 | 连带破坏其他模块 | 提示词明确【不要做】；配置与代码职责分明；hook 强制质量门禁 |

---

## 附：本周可启动的 5 件事

1. 拉业务顾问开数据摸底会，列出 7+ 系统导出格式与优先级，确认一期只接 2 个库
2. 搭 Docker Compose 环境：Milvus + Redis + MySQL + FastAPI 骨架
3. 写 `configs/collections.yaml` 初稿（5 个 Collection 统一字段），团队评审
4. 抽样 30 篇殡仪 + 30 篇法规文档跑 MinerU，记录解析失败类型
5. 建 Golden Dataset 表格，业务顾问先标 20 条，验证标注流程

---

**文档版本**：V1.0 · 最后更新：阶段 0 启动前
```

---

几点使用建议：

- **`CLAUDE.md` 直接从本文档第六、八节摘**，不要单独维护两份，避免约束漂移。
- 第七节的 `ANTHROPIC_BASE_URL` 配置，实际端口和 token 以你选的 router/中转服务为准，落地时替换。
- README 里的验收指标和风险清单是给团队看的，`CLAUDE.md` 里可以精简，只留硬性约束和目录结构，控制每次会话的上下文长度。

需要的话，我可以再把 `CLAUDE.md` 单独拆出来出一份精简版（控制在 100 行以内，更适合每次都塞进上下文）。