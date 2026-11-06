# 阶段 1 纵向切片契约（冻结）

> **冻结版本**：v1.2（v1.1 + 检索阈值拆分，见 §9.6）
> **冻结日期**：2026-11-01
> **冻结范围**：`src/everrag` 当前实现、`data/samples` 样例数据、`eval` 冒烟评测
> **原则**：只从现有代码提取，不设计新契约；本文件不改动任何代码。
> **行号基准**：当前工作区文件。后续代码变动后，行号需要重新校对。

## 0. 阅读口径

### 0.1 路径简写

| 简写 | 实际路径 |
|---|---|
| `schemas.py` | `src/everrag/schemas.py` |
| `base.py` | `src/everrag/tools/base.py` |
| `builtin.py` | `src/everrag/tools/builtin.py` |
| `routes.py` | `src/everrag/api/routes.py` |
| `state.py` | `src/everrag/agent/state.py` |
| `nodes.py` | `src/everrag/agent/nodes.py` |
| `orchestrator.py` | `src/everrag/agent/orchestrator.py` |
| `index.py` | `src/everrag/retrieval/index.py` |
| `session.py` | `src/everrag/memory/session.py` |
| `CLAUDE.md` | 仓库根目录 `CLAUDE.md` |

### 0.2 路由数量口径

任务描述为「7 个路由」。当前代码实际是 **7 个业务路由 + 1 个健康检查**：

- 业务路由：`/v1/chat`、`/v1/chat/stream`、`/v1/citations/{doc_id}`、`/v1/sessions/{session_id}`、`/v1/tools`、`/v1/feedback`、`/v1/handoff`
- 健康检查：`/healthz`

本文全部列出，健康检查单独放在路由表最后一行。来源：`routes.py:40-112`。

### 0.3 必填口径

- `AgentState` 使用 `TypedDict(total=False)`，**类型层面所有字段可选**；运行时由 `Orchestrator.run` 初始化 9 个键。来源：`state.py:10-56`、`orchestrator.py:47-60`。
- Pydantic 请求/工具参数模型中，没有默认值的字段为必填；有 `Field(default=...)` 或类属性默认值的字段为可选。
- 下文的「必填」均指对应模型的必填口径，不是 JSON Schema 之外的隐式要求。

### 0.4 来源类型口径

`Citation` 模型**没有** `source_type` / `kb_id` 字段。任务要求的 doc / faq / regulation / custom 四类来源，只能由 `doc_id` 前缀和 `title` 推断。本文如实记录，不新增字段。来源：`schemas.py:105-113`。

### 0.5 样例数据口径

`data/samples/*.jsonl` 中的法规条款、收费标准、习俗内容均标注 `is_sample: true`，仅用于开发验证，不是生产政策依据。来源：`data/samples/regulation.jsonl:1`、`data/samples/cultural_custom.jsonl:1`。

---

## 1. 工具契约

### 1.1 公共信封

#### 1.1.1 `ToolResult`

所有工具通过注册表执行后统一返回该结构。来源：`schemas.py:141-146`。

| 字段 | 类型 | 必填/默认 | 说明 |
|---|---|---|---|
| `ok` | `bool` | 必填 | 工具执行是否成功；业务性「未命中/引用无效」仍为 `true` |
| `data` | `dict[str, Any]` | 默认 `{}` | 业务载荷 |
| `error` | `ToolError / null` | 默认 `null` | 注册表层错误 |
| `trace_id` | `str` | 默认 `""` | 注册表执行时写入调用方 trace id |
| `elapsed_ms` | `float` | 默认 `0.0` | 注册表执行耗时，毫秒 |

#### 1.1.2 `ToolError`

来源：`schemas.py:135-138`。

| 字段 | 类型 | 必填/默认 | 说明 |
|---|---|---|---|
| `code` | `str` | 必填 | 错误码，见 §1.1.4 |
| `message` | `str` | 必填 | 错误描述 |
| `retryable` | `bool` | 默认 `false` | 仅 `TOOL_TIMEOUT` 显式置为 `true` |

#### 1.1.3 `ToolContext`

工具执行上下文。来源：`base.py:21-25`。

| 字段 | 类型 | 必填/默认 | 说明 |
|---|---|---|---|
| `trace_id` | `str` | 默认 `""` | 审计 trace |
| `user_role` | `Role` | 默认 `"family"` | 角色枚举，见 §2.1.1 |
| `access_level` | `int` | 默认 `0` | 角色对应访问级别 |
| `user_profile` | `dict[str, Any]` | 默认 `{}` | 地区、民族、宗教等画像 |

#### 1.1.4 注册表执行语义与错误码

`ToolRegistry.execute` 的固定流程：查找工具 → Pydantic 校验入参 → 线程池执行并施加超时 → 统一写入 `trace_id` / `elapsed_ms`。来源：`base.py:68-106`。

| 错误码 | 产生层 | 触发条件 | `ok` | `retryable` | 来源 |
|---|---|---|---|---|---|
| `TOOL_NOT_FOUND` | 注册表 | 工具名不存在 | `false` | `false` | `base.py:70-75` |
| `INVALID_ARGS` | 注册表 | Pydantic `ValidationError` | `false` | `false` | `base.py:76-83` |
| `TOOL_TIMEOUT` | 注册表 | 执行超过工具 `timeout_s` | `false` | `true` | `base.py:89-97` |
| `TOOL_ERROR` | 注册表 | 其他异常 | `false` | `false` | `base.py:98-102` |
| `DEPENDENCY_MISSING` | Executor | `verify_citation` 任务没有解析出 `doc_id` | 不适用 | 不适用 | `nodes.py:446-454` |
| `TOOL_BUDGET_EXCEEDED` | Executor | 工具调用次数达到 `max_tool_calls` | 不适用 | 不适用 | `nodes.py:435-443` |
| `CITATION_INVALID` | Executor RiskFlag | `verify_citation` 返回 `valid=false` | 不适用 | 不适用 | `nodes.py:497-507`、`nodes.py:533-543` |
| `TOOL_ERROR` | Executor RiskFlag | 工具 `result.ok=false` | 不适用 | 不适用 | `nodes.py:479-482` |

> 注意：`verify_citation` 的 `NOT_FOUND` / `FORBIDDEN` / `ARTICLE_MISMATCH` / `NOT_EFFECTIVE` 不是 `ToolError.code`，而是 `data.reason` 业务结果，`ok` 仍为 `true`。见 §1.3.4。

### 1.2 工具总表

5 个工具由 `build_registry` 注册。来源：`builtin.py:165-175`。

| 工具名 | 必填入参 | 可选入参 | 成功返回 | 风险级别/超时 | 来源 |
|---|---|---|---|---|---|
| `search_knowledge_base` | `query` | `collections`、`region`、`ethnicity`、`religion`、`top_k` | `documents`、`total`、`retrieval_mode` | low / 3.0s | `builtin.py:21-52` |
| `get_faq_answer` | `question` | `threshold` | `hit`、`score`、`faq`（命中时） | low / 0.3s | `builtin.py:55-74` |
| `search_regulation` | `query` | `region`、`top_k` | `documents`、`total`、`retrieval_mode` | medium / 3.0s | `builtin.py:77-104` |
| `verify_citation` | `doc_id` | `article_no` | `valid`、`reason`、`doc`（有效时） | medium / 1.0s | `builtin.py:107-129` |
| `lookup_cultural_custom` | `query` | `region`、`ethnicity`、`religion`、`top_k` | `documents`、`total`、`retrieval_mode` | medium / 3.0s | `builtin.py:132-162` |

### 1.3 逐工具 Schema

> 以下 JSON 示例中的值仅示意；字段名、类型与默认值以表格和源码为准。

#### 1.3.1 `search_knowledge_base`

| 字段 | 类型 | 必填/默认 | 约束 | 来源 |
|---|---|---|---|---|
| `query` | `str` | 必填 | `min_length=1` | `builtin.py:22` |
| `collections` | `list[Literal]` | 默认 `["funeral_service"]` | 枚举：`funeral_service`、`regulation`、`cultural_custom` | `builtin.py:14`、`builtin.py:23` |
| `region` | `str / null` | 默认 `null` | 地区过滤 | `builtin.py:24` |
| `ethnicity` | `str / null` | 默认 `null` | 民族过滤 | `builtin.py:25` |
| `religion` | `str / null` | 默认 `null` | 宗教过滤 | `builtin.py:26` |
| `top_k` | `int` | 默认 `5` | `ge=1, le=20` | `builtin.py:27` |

成功返回：

```json
{
  "ok": true,
  "data": {
    "documents": [
      {
        "doc_id": "fun_001",
        "title": "遗体接运办理流程",
        "content": "……",
        "score": 0.42,
        "metadata": {
          "kb_id": "funeral_service",
          "doc_type": "manual",
          "source_url": "sample://funeral_service/fun_001",
          "authority": "集团服务规范（示例）",
          "regulation_id": null,
          "article_no": null,
          "effective_date": null,
          "expiry_date": null,
          "region": "全国",
          "ethnicity": null,
          "religion": null,
          "ethnicity_religion": null,
          "access_level": 0,
          "visible_to_roles": ["family", "funeral_staff"],
          "version": "v0",
          "sensitivity": "low",
          "is_sample": true
        }
      }
    ],
    "total": 1,
    "retrieval_mode": "memory-lexical"
  },
  "error": null,
  "trace_id": "tr_...",
  "elapsed_ms": 1.23
}
```

- 空结果不是错误：`ok=true`、`documents=[]`、`total=0`。来源：`builtin.py:49-52`。
- 返回文档结构来自 `Document.to_payload()`，字段见 §1.4.1。来源：`builtin.py:17-18`、`schemas.py:68-75`。
- 检索使用 `settings.retrieval.min_score` 与角色/地区/民族/宗教过滤。来源：`builtin.py:38-48`、`index.py:85-119`。

#### 1.3.2 `get_faq_answer`

| 字段 | 类型 | 必填/默认 | 约束 | 来源 |
|---|---|---|---|---|
| `question` | `str` | 必填 | `min_length=1` | `builtin.py:56` |
| `threshold` | `float` | 默认 `0.85` | `ge=0.0, le=1.0` | `builtin.py:57` |

命中返回：

```json
{
  "ok": true,
  "data": {
    "hit": true,
    "score": 1.0,
    "faq": {
      "faq_id": "faq_002",
      "question": "火化需要准备什么材料？",
      "answer": "一般需要死亡证明、逝者身份证明、经办人身份证明……",
      "intent": "funeral",
      "region": "全国",
      "visible_to_roles": ["family", "funeral_staff"],
      "version": "v0",
      "is_sample": true
    }
  },
  "error": null,
  "trace_id": "tr_...",
  "elapsed_ms": 0.21
}
```

未命中返回：

```json
{
  "ok": true,
  "data": { "hit": false, "score": 0.42 },
  "error": null,
  "trace_id": "tr_...",
  "elapsed_ms": 0.15
}
```

- 精确归一化匹配返回 `score=1.0`；否则按问题 token 覆盖率评分；最高分低于 `threshold` 时返回 `hit=false`。来源：`index.py:121-144`。
- FAQ 可见性按 `FAQItem.visible_to_roles` 过滤；空列表表示对所有角色可见。来源：`index.py:131-133`、`schemas.py:163`。
- FAQ 载荷字段见 §1.4.2。来源：`schemas.py:157-165`。

#### 1.3.3 `search_regulation`

| 字段 | 类型 | 必填/默认 | 约束 | 来源 |
|---|---|---|---|---|
| `query` | `str` | 必填 | `min_length=1` | `builtin.py:78` |
| `region` | `str / null` | 默认 `null` | 地区过滤 | `builtin.py:79` |
| `top_k` | `int` | 默认 `5` | `ge=1, le=20` | `builtin.py:80` |

成功返回：与 `search_knowledge_base` 相同的 `documents` / `total` / `retrieval_mode` 结构。来源：`builtin.py:101-104`。

- 固定只检索 `regulation` Collection。来源：`builtin.py:91-94`。
- 使用更低的 `settings.retrieval.regulation_min_score`（默认 `0.05`，低于通用 `min_score` 的 `0.15`），以更高容忍度保留法规候选。来源：`builtin.py:95`、`configs/retrieval.yaml:3-4`。
- 强制 `effective_only=True`，检索层过滤未生效/已过期文档。来源：`builtin.py:99`、`index.py:104-106`、`schemas.py:83-97`。
- 空结果不是错误：`ok=true`、`documents=[]`、`total=0`。

#### 1.3.4 `verify_citation`

| 字段 | 类型 | 必填/默认 | 约束 | 来源 |
|---|---|---|---|---|
| `doc_id` | `str` | 必填 | `min_length=1` | `builtin.py:108` |
| `article_no` | `str / null` | 默认 `null` | 提供时做严格相等校验 | `builtin.py:109` |

有效返回：

```json
{
  "ok": true,
  "data": {
    "valid": true,
    "reason": "OK",
    "doc": {
      "doc_id": "reg_001",
      "title": "殡葬管理条例（示例节选）",
      "content": "……",
      "score": 0.0,
      "metadata": { "regulation_id": "reg_001", "article_no": "第十二条", "authority": "国务院", "effective_date": "2013-01-01" }
    }
  },
  "error": null,
  "trace_id": "tr_...",
  "elapsed_ms": 0.31
}
```

无效返回（`ok` 仍为 `true`）：

```json
{
  "ok": true,
  "data": { "valid": false, "reason": "ARTICLE_MISMATCH" },
  "error": null,
  "trace_id": "tr_...",
  "elapsed_ms": 0.28
}
```

`reason` 取值与条件：

| `reason` | 条件 | 来源 |
|---|---|---|
| `OK` | 文档存在、可见、条款匹配（如提供）、现行有效 | `builtin.py:129` |
| `NOT_FOUND` | `corpus.get_doc(doc_id)` 返回 `None` | `builtin.py:120-122` |
| `FORBIDDEN` | `Document.is_visible(role, access_level)` 为假 | `builtin.py:123-124`、`schemas.py:99-102` |
| `ARTICLE_MISMATCH` | 提供了 `article_no` 且与文档不一致 | `builtin.py:125-126` |
| `NOT_EFFECTIVE` | `effective_date` 未到、`expiry_date` 已过，或日期解析失败 | `builtin.py:127-128`、`schemas.py:83-97` |

> `verify_citation` 只查 `InMemoryCorpus._by_id`，该索引只包含 `Document`，不包含 FAQ。FAQ 的 `faq_id` 不在其中。来源：`index.py:67`、`index.py:82-83`。

#### 1.3.5 `lookup_cultural_custom`

| 字段 | 类型 | 必填/默认 | 约束 | 来源 |
|---|---|---|---|---|
| `query` | `str` | 必填 | `min_length=1` | `builtin.py:133` |
| `region` | `str / null` | 默认 `null` | 地区过滤 | `builtin.py:134` |
| `ethnicity` | `str / null` | 默认 `null` | 民族过滤 | `builtin.py:135` |
| `religion` | `str / null` | 默认 `null` | 宗教过滤 | `builtin.py:136` |
| `top_k` | `int` | 默认 `5` | `ge=1, le=20` | `builtin.py:137` |

成功返回：与 `search_knowledge_base` 相同的 `documents` / `total` / `retrieval_mode` 结构。来源：`builtin.py:159-162`。

- 固定只检索 `cultural_custom` Collection。来源：`builtin.py:148-151`。
- 使用通用 `settings.retrieval.min_score`。来源：`builtin.py:152`。
- 空结果不是错误：`ok=true`、`documents=[]`、`total=0`。

### 1.4 公共载荷

#### 1.4.1 `DocumentPayload`

由 `Document.to_payload()` 生成。来源：`schemas.py:68-75`。

| 字段 | 类型 | 必填/默认 | 说明 |
|---|---|---|---|
| `doc_id` | `str` | 必填 | 文档唯一 id |
| `title` | `str` | 必填 | 文档标题 |
| `content` | `str` | 必填 | 文档正文 |
| `score` | `float` | 默认 `0.0` | 检索分数；`verify_citation` 返回的 doc 来自 `corpus.get_doc`，通常为 `0.0`；executor 合并时保留已有检索分数 |
| `metadata` | `dict` | 必有 | `Document.metadata()` 输出，见下表 |

`metadata` 字段来自 `Document`（`schemas.py:35-63`）：

| 字段 | 类型 | 默认 | 来源 |
|---|---|---|---|
| `kb_id` | `str` | 必填 | `schemas.py:41` |
| `doc_type` | `str` | `"manual"` | `schemas.py:42` |
| `source_url` | `str / null` | `null` | `schemas.py:47` |
| `authority` | `str / null` | `null` | `schemas.py:48` |
| `regulation_id` | `str / null` | `null` | `schemas.py:49` |
| `article_no` | `str / null` | `null` | `schemas.py:50` |
| `effective_date` | `str / null` | `null` | `schemas.py:51` |
| `expiry_date` | `str / null` | `null` | `schemas.py:52` |
| `region` | `str / null` | `null` | `schemas.py:54` |
| `ethnicity` | `str / null` | `null` | `schemas.py:55` |
| `religion` | `str / null` | `null` | `schemas.py:56` |
| `ethnicity_religion` | `str / null` | `null` | `schemas.py:57` |
| `access_level` | `int` | `0` | `schemas.py:59` |
| `visible_to_roles` | `list[str]` | `[]` | `schemas.py:60` |
| `version` | `str` | `"v0"` | `schemas.py:61` |
| `sensitivity` | `str` | `"low"` | `schemas.py:62` |
| `is_sample` | `bool` | `true` | `schemas.py:63` |

`Document.from_payload` 会将 `metadata` 展开回顶层字段；来源：`schemas.py:77-81`。`executor` 合并文档时用 `_upsert_doc` 保留已有检索分数，避免 `verify_citation` 返回的 `score=0.0` 覆盖排序。来源：`nodes.py:126-131`。

> 上文 JSON 中的值是字段示意，不是固定数据；实际值由 `data/samples` 决定。

#### 1.4.2 `FAQ` 载荷

来源：`schemas.py:157-165`。

| 字段 | 类型 | 默认 |
|---|---|---|
| `faq_id` | `str` | 必填 |
| `question` | `str` | 必填 |
| `answer` | `str` | 必填 |
| `intent` | `str` | `"unknown"` |
| `region` | `str` | `"全国"` |
| `visible_to_roles` | `list[str]` | `[]` |
| `version` | `str` | `"v0"` |
| `is_sample` | `bool` | `true` |

---

## 2. API 契约

### 2.1 请求/响应模型

#### 2.1.1 `ChatRequest`

来源：`schemas.py:168-173`。

| 字段 | 类型 | 必填/默认 | 约束 |
|---|---|---|---|
| `message` | `str` | 必填 | `1 <= len <= 2000` |
| `session_id` | `str / null` | 默认 `null`；为空时由 `uuid4().hex` 生成 | — |
| `user_id` | `str` | 默认 `"anonymous"` | — |
| `user_role` | `Role` | 默认 `"family"` | 枚举：`family`、`funeral_staff`、`cemetery_advisor`、`counselor`、`account_manager` |
| `user_profile` | `dict[str, Any]` | 默认 `{}` | 可含 `region`、`ethnicity`、`religion` |

`session_id` 生成逻辑来源：`orchestrator.py:37`；角色枚举来源：`schemas.py:10-16`。

#### 2.1.2 `ChatResponse`

来源：`schemas.py:176-188`。

| 字段 | 类型 | 必填/默认 | 说明 |
|---|---|---|---|
| `session_id` | `str` | 必填 | 会话 id |
| `trace_id` | `str` | 必填 | `tr_` + 12 位 hex；来源：`observability/trace.py:8-9` |
| `answer` | `str` | 必填 | 最终回答 |
| `intent` | `str` | 默认 `"unknown"` | 字符串，不是枚举；取值见下方说明 |
| `citations` | `list[Citation]` | 默认 `[]` | 引用列表，见 §4 |
| `risk_flags` | `list[RiskFlag]` | 默认 `[]` | 风险标记 |
| `needs_human` | `bool` | 默认 `false` | 是否转人工 |
| `handoff_reason` | `str / null` | 默认 `null` | 转人工原因，见下表 |
| `tool_calls` | `list[dict]` | 默认 `[]` | 每次工具调用记录 |
| `events` | `list[dict]` | 默认 `[]` | 图内事件列表；SSE 会追加 citation/token/done 并过滤内部 done，见 §3 |
| `degraded` | `bool` | 默认 `false` | LLMComposer 超时/错误后是否降级到确定性 composer；见 §9 |
| `citation_invalid` | `bool` | 默认 `false` | LLM 回答是否存在缺失/无效引用；见 §9 |

> `AgentState.tool_errors` 仅存在于图内部，不出现在 `ChatResponse` 中；`ChatResponse` 只暴露 `tool_calls` 与 `events`。来源：`state.py:35`、`schemas.py:176-188`、`orchestrator.py:89-106`。

`intent` 当前由 `classify_intent` 产生，取值包括：`unknown`、`smalltalk`、`grief`、`cultural`、`regulation`、`funeral`、`cemetery`、`mixed`。危机和 Prompt 注入路径不经过 router，响应中的 `intent` 为默认 `"unknown"`。来源：`nodes.py:80-94`、`orchestrator.py:76`。

`handoff_reason` 当前代码中出现的取值：

| 取值 | 触发位置 | 来源 |
|---|---|---|
| `crisis` | 危机路径 | `nodes.py:252` |
| `prompt_injection` | 注入拒绝路径 | `nodes.py:266` |
| `system_error` | 图执行异常兜底 | `orchestrator.py:65` |
| `no_evidence` | 无检索证据 | `nodes.py:659` |
| `citation_unverified` | 法规引用未核验 | `nodes.py:714` |
| `guardrail` | 输出审查最终兜底 | `nodes.py:798` |
| `low_confidence` | `finalize` 在 `needs_human` 且无原因时兜底 | `nodes.py:846` |

`tool_calls` 单项结构来源：`nodes.py:116-123`。

| 字段 | 类型 | 说明 |
|---|---|---|
| `task_id` | `str / null` | 计划任务 id；FAQ 调用为 `"faq"`，自动核验为 `auto_<doc_id>` |
| `tool` | `str` | 工具名 |
| `ok` | `bool` | 工具是否执行成功 |
| `elapsed_ms` | `float` | 耗时 |
| `error` | `str / null` | `ToolError.code` 或 `null` |

`RiskFlag` 结构来源：`schemas.py:129-132`。

| 字段 | 类型 | 默认 |
|---|---|---|
| `code` | `str` | 必填 |
| `severity` | `"low" / "medium" / "high" / "critical"` | `"low"` |
| `message` | `str` | 必填 |

#### 2.1.3 `FeedbackRequest`

来源：`schemas.py:189-193`。

| 字段 | 类型 | 必填/默认 | 约束 |
|---|---|---|---|
| `session_id` | `str` | 必填 | — |
| `trace_id` | `str` | 必填 | — |
| `rating` | `int` | 必填 | `1 <= rating <= 5` |
| `comment` | `str` | 默认 `""` | — |

#### 2.1.4 `HandoffRequest`

来源：`schemas.py:196-199`。

| 字段 | 类型 | 必填/默认 |
|---|---|---|
| `session_id` | `str` | 必填 |
| `reason` | `str` | 默认 `"user_request"` |
| `note` | `str` | 默认 `""` |

### 2.2 路由总表

来源：`routes.py:40-112`。

| # | 方法 | 路径 | 请求 | 成功响应 | 状态码 | 来源 |
|---|---|---|---|---|---|---|
| 1 | `POST` | `/v1/chat` | `ChatRequest` JSON | `ChatResponse` JSON | 200；422 | `routes.py:40-43` |
| 2 | `POST` | `/v1/chat/stream` | `ChatRequest` JSON | `text/event-stream` | 200；422 | `routes.py:46-72` |
| 3 | `GET` | `/v1/citations/{doc_id}` | 路径参数 `doc_id` | `Document.model_dump()` | 200；404 | `routes.py:75-80` |
| 4 | `GET` | `/v1/sessions/{session_id}` | 路径参数 `session_id` | `{session_id, history}` | 200 | `routes.py:83-85` |
| 5 | `GET` | `/v1/tools` | 无 | `list[ToolDescriptor]` | 200 | `routes.py:88-90`、`base.py:56-66` |
| 6 | `POST` | `/v1/feedback` | `FeedbackRequest` JSON | `{ok: true}` | 200；422 | `routes.py:93-96` |
| 7 | `POST` | `/v1/handoff` | `HandoffRequest` JSON | `{ok, ticket_id, status}` | 200；422 | `routes.py:99-102` |
| 8 | `GET` | `/healthz` | 无 | `{status, docs, faqs, tools}` | 200 | `routes.py:105-112` |

### 2.3 路由响应细节

#### 2.3.1 `POST /v1/chat`

- 请求：`ChatRequest`；响应：`ChatResponse(**orchestrator.run(req))`。来源：`routes.py:40-43`。
- `ChatResponse` 字段见 §2.1.2。
- 校验失败（如空 `message`、非法 `user_role`）由 FastAPI/Pydantic 返回 422，源码未显式声明。来源：`schemas.py:168-173`。

#### 2.3.2 `POST /v1/chat/stream`

- 请求：`ChatRequest`；响应：`StreamingResponse(media_type="text/event-stream")`。来源：`routes.py:46-72`。
- 事件格式与顺序见 §3。
- 校验失败返回 422；图执行异常由 `orchestrator.run` 捕获并以 `error` 事件返回。来源：`orchestrator.py:51-68`。

#### 2.3.3 `GET /v1/citations/{doc_id}`

- 响应：`Document.model_dump()`，包含 Document 全部字段（含 `score`）。来源：`routes.py:75-80`、`schemas.py:35-63`。
- 文档不存在：HTTP 404，`detail="引用文档不存在"`。来源：`routes.py:78-79`。
- 只查 `corpus.get_doc`，FAQ 不在该索引中；FAQ 的 `faq_id` 会 404。来源：`index.py:67`、`index.py:82-83`。

#### 2.3.4 `GET /v1/sessions/{session_id}`

- 响应：`{session_id: str, history: list}`。来源：`routes.py:83-85`。
- `history` 由 `InMemorySessionStore.get` 返回，最多保留最近 `max_turns * 2` 条消息；单项结构为 `{"role": "user"|"assistant", "content": str}`。来源：`session.py:15-24`。
- 不存在的 session 返回空列表，不返回 404。来源：`session.py:17`。

#### 2.3.5 `GET /v1/tools`

- 响应：工具描述列表，每项字段为 `name`、`description`、`risk_level`、`timeout_s`、`parameters`（`args_model.model_json_schema()`）。来源：`routes.py:88-90`、`base.py:56-66`。
- 顺序为注册顺序：`search_knowledge_base`、`get_faq_answer`、`search_regulation`、`verify_citation`、`lookup_cultural_custom`。来源：`builtin.py:165-175`。

#### 2.3.6 `POST /v1/feedback`

- 请求：`FeedbackRequest`；响应：`{"ok": true}`。来源：`routes.py:93-96`、`schemas.py:189-193`。
- 仅写日志，不落库。来源：`routes.py:95-96`。

#### 2.3.7 `POST /v1/handoff`

- 请求：`HandoffRequest`；响应：`{"ok": true, "ticket_id": "ho_" + session_id[-8:], "status": "queued"}`。来源：`routes.py:99-102`。
- 仅写日志，不调用真实工单系统。来源：`routes.py:101-102`。

#### 2.3.8 `GET /healthz`

- 响应：`{"status": "ok", "docs": int, "faqs": int, "tools": int}`。来源：`routes.py:105-112`。
- 当前样例数据下为 `docs=13`、`faqs=5`、`tools=5`。来源：`data/samples/*.jsonl`、`builtin.py:165-175`。

### 2.4 状态码口径

| 状态码 | 适用范围 | 来源/说明 |
|---|---|---|
| 200 | 所有成功响应 | FastAPI 默认，路由未显式声明 `status_code`；`routes.py:40-112` |
| 404 | 仅 `/v1/citations/{doc_id}` 文档不存在 | 显式 `HTTPException(status_code=404)`；`routes.py:78-79` |
| 422 | 请求体/路径参数校验失败 | FastAPI/Pydantic 自动生成，源码未显式声明；`schemas.py:168-199` |
| 500 | 未显式声明的 API 级异常 | 图执行异常被 `orchestrator.run` 捕获并降级为 200 + `error` 事件；其他 API 异常可能由框架返回 500。来源：`orchestrator.py:51-68` |

---

## 3. SSE 契约

### 3.1 帧格式与发送顺序

帧格式：

```text
event: <event_type>
data: <JSON>

```

- JSON 使用 `ensure_ascii=False`，`default=str`。来源：`routes.py:31-33`。
- 发送顺序：先发送 `result.events` 中除 `done` 外的事件，再发送每个 `result.citations` 的完整 `citation` 事件，再按 24 字符切分发送 `token`，最后发送 `done`。来源：`routes.py:50-70`。
- **data 中是否带 `type`**：来自 `result.events` 的状态类事件（`meta`、`status`、`tool_start`、`tool_result`、`handoff`、`error`、FAQ 精简 `citation`）由 `_append` 写入 `type`；API 追加的完整 `citation`、`token`、`done` 只通过 SSE 的 `event:` 行标识类型，data 里**没有** `type` 字段。来源：`nodes.py:97-98`、`routes.py:56-70`。
- `token` 切分大小为 24 个字符。来源：`routes.py:36-37`。

### 3.2 事件总表

| 事件类型 | 发送来源 | payload 字段 | 来源 |
|---|---|---|---|
| `meta` | `intake` | `type`、`trace_id`、`session_id` | `nodes.py:185-191` |
| `status` | safety/router/planner/evidence/replan/composer/critic/grief/smalltalk | `type`、`stage` + 各阶段字段 | 见 §3.3 |
| `tool_start` | executor | `type`、`tool`、`task_id` | `nodes.py:458`、`nodes.py:518` |
| `tool_result` | executor / FAQ 快速路径 | 两种形态，见 §3.4.3 | `nodes.py:297-303`、`nodes.py:461-469`、`nodes.py:521-528` |
| `citation` | FAQ 节点 / API 流 | FAQ 节点形态含 `type`、`doc_id`、`title`；API 完整形态为 `Citation` 字段且不含 `type`，见 §3.4.4 | `nodes.py:315`、`routes.py:56-57` |
| `handoff` | crisis / refuse | `type`、`reason` | `nodes.py:254`、`nodes.py:267` |
| `error` | orchestrator 异常兜底 | `type`、`message` | `orchestrator.py:67` |
| `token` | API 流 | `text`（无 `type`） | `routes.py:58-59` |
| `done` | API 流 | 见 §3.4.2（无 `type`） | `routes.py:60-72` |

> 图中的 `finalize` 节点也会产生一个内部 `done` 事件，但 API 在 `routes.py:53-54` 明确跳过它，只发送 API 自己的 `done`。同步 `/v1/chat` 的 `ChatResponse.events` 仍包含内部 `done`。来源：`nodes.py:836-842`、`orchestrator.py:82`。

### 3.3 `status` 事件的 stage 与字段

| `stage` | 额外字段 | 来源 |
|---|---|---|
| `safety_screen` | `crisis: bool`、`injection: bool`、`pii_masked: bool` | `nodes.py:220-227` |
| `router` | `intent: str`、`complexity: str` | `nodes.py:276-282` |
| `planner` | `tasks: list[str]`（工具名列表） | `nodes.py:409-414` |
| `evidence_gate` | `evidence_ok: bool`、`docs: int`、`citations: int` | `nodes.py:572-579` |
| `replan` | `tasks: list[str]` | `nodes.py:635-640` |
| `composer` | `docs: int`、`citations: int` | `nodes.py:742-748` |
| `critic` | `ok: bool` + 以下之一：`flags: list[str]`；`revision: int`；`final_safe_fallback: bool` | `nodes.py:767-773`、`nodes.py:784-790`、`nodes.py:800-806` |
| `grief_support` | 无额外字段 | `nodes.py:816-819` |
| `smalltalk` | 无额外字段 | `nodes.py:827-830` |

### 3.4 关键事件详解

#### 3.4.1 `token`

```json
{ "text": "关于您咨询的事项，" }
```

- data 中只有 `text` 字段；没有 `type`、`index`、`id` 或 `finish_reason`；类型由 SSE `event: token` 行表示。来源：`routes.py:58-59`。
- 文本按 24 字符切分；一个回答会产生多个 `token` 事件。来源：`routes.py:36-37`。

#### 3.4.2 `done`

```json
{
  "session_id": "…",
  "trace_id": "tr_…",
  "intent": "funeral",
  "citations": [
    {
      "doc_id": "fun_001",
      "title": "遗体接运办理流程",
      "article_no": null,
      "authority": "集团服务规范（示例）",
      "effective_date": null,
      "source_url": "sample://funeral_service/fun_001",
      "quote": "……",
      "valid": true
    }
  ],
  "needs_human": false,
  "handoff_reason": null,
  "degraded": false,
  "citation_invalid": false
}
```

- data 中**没有 `type`**，类型由 SSE `event: done` 行表示。
- **不包含 `answer` 字段**；完整回答由 `token` 事件拼接得到。来源：`routes.py:60-72`。
- `degraded` / `citation_invalid` 为 v1.1 新增字段，见 §9。
- `citations` 是完整 `Citation.model_dump()` 列表，不是 FAQ 节点的精简 citation 事件；每项也不含 `type`。来源：`routes.py:66`。
- 内部 `finalize` 的 `done` payload 为 `type`、`citations: int`、`needs_human`、`steps`，与 API `done` 不同；API 会过滤内部 `done`。来源：`nodes.py:836-842`、`routes.py:53-54`。

#### 3.4.3 `tool_result`

executor 形态：

```json
{
  "type": "tool_result",
  "tool": "search_regulation",
  "task_id": "t2",
  "ok": true,
  "total": 5,
  "valid": null
}
```

- 字段：`type`、`tool`、`task_id`、`ok`、`total`、`valid`。来源：`nodes.py:461-469`。
- 自动二次核验时 `task_id` 为 `auto_<doc_id>`，字段为 `type`、`tool`、`task_id`、`ok`、`valid`，没有 `total`。来源：`nodes.py:521-528`。

FAQ 快速路径形态：

```json
{
  "type": "tool_result",
  "tool": "get_faq_answer",
  "ok": true,
  "hit": true
}
```

- 字段：`type`、`tool`、`ok`、`hit`；没有 `task_id`、`total`、`valid`，也没有对应的 `tool_start` 事件。来源：`nodes.py:297-303`。

#### 3.4.4 `citation`

API 完整形态（每个最终引用发送一次）：

```json
{
  "doc_id": "reg_001",
  "title": "殡葬管理条例（示例节选）",
  "article_no": "第十二条",
  "authority": "国务院",
  "effective_date": "2013-01-01",
  "source_url": "sample://regulation/reg_001",
  "quote": "殡葬管理应当节约土地、保护环境……",
  "valid": true
}
```

- 字段来自 `Citation.model_dump()`；data 中**没有 `type`**，类型由 SSE `event: citation` 行表示。来源：`routes.py:56-57`、`schemas.py:105-113`。

FAQ 节点精简形态（FAQ 快速路径时先发送一次）：

```json
{
  "type": "citation",
  "doc_id": "faq_002",
  "title": "常见问题解答（FAQ）"
}
```

- 字段为 `type`、`doc_id`、`title`；这是来自 `result.events` 的状态事件，所以 data 里带 `type`。来源：`nodes.py:315`。
- 同一 FAQ 回答可能先出现精简 citation（节点事件，带 `type`），再出现完整 citation（API 事件，不带 `type`）。见 §7.2 I1。

#### 3.4.5 `error`

```json
{ "type": "error", "message": "TimeoutError" }
```

- 字段为 `type`、`message`；业务字段只有 `message`，值为异常类名。来源：`orchestrator.py:67`。
- 仅在图执行异常兜底时产生；没有 `code`、`retryable` 或堆栈。来源：`orchestrator.py:53-68`。
- 请求校验失败（422）和引用不存在（404）是 HTTP 响应，不是 SSE `error` 事件。来源：`routes.py:78-79`、`schemas.py:168-199`。

---

## 4. Citation 契约

### 4.1 字段

来源：`schemas.py:105-113`。

| 字段 | 类型 | 必填/默认 | 说明 |
|---|---|---|---|
| `doc_id` | `str` | 必填 | 文档 id 或 FAQ id |
| `title` | `str` | 必填 | 引用标题 |
| `article_no` | `str / null` | 默认 `null` | 法规条款号 |
| `authority` | `str / null` | 默认 `null` | 发布机关 |
| `effective_date` | `str / null` | 默认 `null` | 生效日期，ISO `YYYY-MM-DD` |
| `source_url` | `str / null` | 默认 `null` | 来源链接 |
| `quote` | `str / null` | 默认 `null` | 引用摘录 |
| `valid` | `bool` | 默认 `true` | 见 §4.4 |

### 4.2 生成规则

- **没有独立的 Citation ID 生成器**。`Citation.doc_id` 直接复制 `Document.doc_id`。来源：`schemas.py:118-126`。
- `Citation.from_document`：
  - 复制 `doc_id`、`title`、`article_no`、`authority`、`effective_date`、`source_url`；
  - `quote` 取文档正文前 100 个字符，超长追加 `…`；
  - `valid` 未显式赋值，使用默认 `true`。来源：`schemas.py:115-126`。
- FAQ 引用：
  - `doc_id = faq_id`；
  - `title = "常见问题解答（FAQ）"`；
  - `source_url = "sample://faq/{faq_id}"`；
  - `quote = answer[:100]`；
  - `valid` 默认 `true`。来源：`nodes.py:309-314`。

### 4.3 来源类型映射

`Citation` 本身没有 `source_type` / `kb_id`。当前只能按 `doc_id` 前缀和标题推断：

| 任务口径 | 当前表示 | 证据 |
|---|---|---|
| `doc` | `doc_id` 前缀 `fun_`；文档 `kb_id="funeral_service"` | `data/samples/funeral_service.jsonl:1`、`schemas.py:41` |
| `regulation` | `doc_id` 前缀 `reg_`；文档 `kb_id="regulation"`；带 `article_no`/`authority`/`effective_date` | `data/samples/regulation.jsonl:1`、`schemas.py:49-52` |
| `custom` | `doc_id` 前缀 `cul_`；文档 `kb_id="cultural_custom"` | `data/samples/cultural_custom.jsonl:1` |
| `faq` | `doc_id` 前缀 `faq_`；`title="常见问题解答（FAQ）"` | `data/samples/faq.jsonl:1`、`nodes.py:309-314` |

> 这不是正式字段契约，只是当前数据与代码的约定。若后续需要 `source_type` 字段，属于契约变更，必须先裁决（见 §7.2）。

### 4.4 `valid` 语义

- `valid` 默认 `true`，但**不是所有来源都经过核验**：
  - 非法规文档：`Citation.from_document` 直接创建，未调用 `verify_citation`。来源：`nodes.py:486-491`。
  - 法规文档（经 `search_regulation`）：只有 `verify_citation.valid=true` 才创建 Citation。来源：`nodes.py:492-496`、`nodes.py:529-532`。
  - FAQ：直接创建，未调用 `verify_citation`。来源：`nodes.py:304-314`。
  - **例外**：`intent=="unknown"` 时，`search_knowledge_base` 的 collections 包含 `regulation`（`nodes.py:342-347`）；executor 因工具名不是 `search_regulation` 而直接创建 Citation（`nodes.py:486-491`），这类法规引用可能未经 `verify_citation`。见 §7.2 I10。
- 核验失败的法规引用**不会进入 `citations`**，而是记录 `CITATION_INVALID` RiskFlag。来源：`nodes.py:497-507`、`nodes.py:533-543`。
- 因此：
  - 对经 `search_regulation` 返回的法规来源，`citations` 中出现即代表通过核验；
  - 对 `search_knowledge_base` 的 unknown 路径、非法规来源和 FAQ，`valid=true` 只表示模型默认值，不代表外部核验；
  - 若需要统一的「已验证」语义，需要新增字段或调整构造规则，属于契约变更。

---

## 5. AgentState 契约

### 5.1 类型声明

`AgentState` 为 `TypedDict(total=False)`，所有字段在类型层面可选。来源：`state.py:10-56`。

运行时初始化：`Orchestrator.run` 初始化以下 9 个键。来源：`orchestrator.py:47-60`。

```text
session_id, trace_id, user_id, user_role, access_level,
user_profile, history, message, events
```

其余字段由各节点写入。节点读取时普遍使用 `state.get(..., default)`，因此缺字段不会抛 `KeyError`，但会改变路由或输出。

### 5.2 字段表

> 「类型必填」均为「否」，因为 `total=False`；「运行时初始化」指是否由 Orchestrator 初始写入；「主要写入/消费」描述节点间流向。

| 字段 | 类型 | 类型必填 | 运行时初始化 | 主要写入/消费 | 来源 |
|---|---|---|---|---|---|
| `session_id` | `str` | 否 | 是 | Orchestrator → 所有节点/API | `state.py:12`、`orchestrator.py:51` |
| `trace_id` | `str` | 否 | 是 | Orchestrator → 所有节点/审计 | `state.py:13`、`orchestrator.py:52` |
| `user_id` | `str` | 否 | 是 | Orchestrator 初始化；当前节点未消费 | `state.py:14`、`orchestrator.py:53` |
| `user_role` | `str` | 否 | 是 | Orchestrator → ToolContext | `state.py:15`、`orchestrator.py:54` |
| `access_level` | `int` | 否 | 是 | Orchestrator → ToolContext | `state.py:16`、`orchestrator.py:55` |
| `user_profile` | `dict[str, Any]` | 否 | 是 | Orchestrator → planner / ToolContext | `state.py:17`、`orchestrator.py:56` |
| `history` | `list[dict[str, Any]]` | 否 | 是 | Orchestrator 初始化；当前节点未消费 | `state.py:18`、`orchestrator.py:57` |
| `message` | `str` | 否 | 是 | Orchestrator → safety | `state.py:21`、`orchestrator.py:58` |
| `normalized_message` | `str` | 否 | 否 | safety → router/planner/composer/evidence | `state.py:22`、`nodes.py:229-230` |
| `masked_message` | `str` | 否 | 否 | safety 写入 | `state.py:23`、`nodes.py:229` |
| `crisis` | `bool` | 否 | 否 | safety → graph 条件边 | `state.py:24`、`nodes.py:231` |
| `injection` | `bool` | 否 | 否 | safety → graph 条件边 | `state.py:25`、`nodes.py:232` |
| `pii_masked` | `bool` | 否 | 否 | safety 写入 | `state.py:26`、`nodes.py:233` |
| `intent` | `str` | 否 | 否 | router → planner/evidence/composer/critic | `state.py:29`、`nodes.py:274` |
| `complexity` | `str` | 否 | 否 | router → graph 路由 | `state.py:30`、`nodes.py:275` |
| `plan` | `list[Task]` | 否 | 否 | planner/replan → executor | `state.py:31`、`nodes.py:408`、`nodes.py:633` |
| `tool_calls` | `list[dict[str, Any]]` | 否 | 否 | intake 初始化；executor 追加 | `state.py:34`、`nodes.py:196`、`nodes.py:549` |
| `tool_errors` | `list[dict[str, Any]]` | 否 | 否 | intake 初始化；executor 追加 | `state.py:35`、`nodes.py:200`、`nodes.py:550` |
| `retrieved_docs` | `list[Document]` | 否 | 否 | intake 初始化；executor 写入 | `state.py:36`、`nodes.py:197`、`nodes.py:547` |
| `citations` | `list[Citation]` | 否 | 否 | intake 初始化；executor/FAQ 写入 | `state.py:37`、`nodes.py:198`、`nodes.py:319`、`nodes.py:548` |
| `evidence_ok` | `bool` | 否 | 否 | evidence_gate/FAQ → graph 路由 | `state.py:38`、`nodes.py:320`、`nodes.py:571` |
| `draft_answer` | `str` | 否 | 否 | composer → critic | `state.py:41`、`nodes.py:738`、`nodes.py:779` |
| `final_answer` | `str` | 否 | 否 | crisis/refuse/FAQ/critic/finalize → API | `state.py:42`、`nodes.py:250`、`nodes.py:264`、`nodes.py:318`、`nodes.py:764`、`nodes.py:795`、`nodes.py:844` |
| `critic_notes` | `str` | 否 | 否 | intake 初始化；composer 清空；critic 写入 | `state.py:43`、`nodes.py:206`、`nodes.py:739`、`nodes.py:780` |
| `critic_ok` | `bool` | 否 | 否 | intake 初始化；critic 写入 | `state.py:44`、`nodes.py:205`、`nodes.py:765`、`nodes.py:781`、`nodes.py:796` |
| `risk_flags` | `list[RiskFlag]` | 否 | 否 | intake 初始化；safety/executor/critic 合并 | `state.py:45`、`nodes.py:199`、`nodes.py:234`、`nodes.py:551`、`nodes.py:758` |
| `needs_human` | `bool` | 否 | 否 | intake 初始化；crisis/refuse/composer/critic/finalize 写入 | `state.py:46`、`nodes.py:203`、`nodes.py:251`、`nodes.py:265`、`nodes.py:740`、`nodes.py:797`、`nodes.py:845` |
| `handoff_reason` | `str / null` | 否 | 否 | crisis/refuse/composer/critic/finalize 写入 | `state.py:47`、`nodes.py:252`、`nodes.py:266`、`nodes.py:741`、`nodes.py:798`、`nodes.py:846` |
| `replan_count` | `int` | 否 | 否 | intake 初始化；replan 自增 | `state.py:52`、`nodes.py:201`、`nodes.py:634` |
| `revision_count` | `int` | 否 | 否 | intake 初始化；critic 自增 | `state.py:53`、`nodes.py:202`、`nodes.py:782` |
| `step_count` | `int` | 否 | 否 | intake 置 1；各节点自增 | `state.py:54`、`nodes.py:193`、`nodes.py:236`、`nodes.py:283` 等 |
| `events` | `list[dict[str, Any]]` | 否 | 是 | Orchestrator 初始化；各节点追加 | `state.py:55`、`orchestrator.py:59`、`nodes.py:194` |
| `faq_hit` | `bool` | 否 | 否 | intake 初始化；FAQ 节点写入 | `state.py:56`、`nodes.py:204`、`nodes.py:317` |
| `degraded` | `bool` | 否 | 否 | intake 初始化；LLMComposer 失败时写入；finalize/API 读取 | `state.py:48`、`nodes.py:654-702`、`nodes.py:789` |
| `citation_invalid` | `bool` | 否 | 否 | intake 初始化；LLMComposer 引用核验失败时写入；critic/API 读取 | `state.py:49`、`nodes.py:661-690`、`nodes.py:802-880` |

### 5.3 节点间主传递

| 传递字段 | 生产者 | 消费者 | 说明 | 来源 |
|---|---|---|---|---|
| `message` / `normalized_message` | Orchestrator / safety | safety、router、planner、composer | 原始消息与脱敏后消息 | `orchestrator.py:58`、`nodes.py:229-230` |
| `intent` / `complexity` | router | planner、evidence_gate、composer、critic | 意图与复杂度 | `nodes.py:271-284` |
| `plan` | planner / replan | executor | `list[Task]` | `nodes.py:407-416`、`nodes.py:632-642` |
| `retrieved_docs` | executor | evidence_gate、composer | `list[Document]` | `nodes.py:545-548` |
| `citations` | executor / FAQ | evidence_gate、composer、API | `list[Citation]` | `nodes.py:319`、`nodes.py:548` |
| `evidence_ok` | evidence_gate / FAQ | graph 条件边 | 是否满足证据门槛 | `nodes.py:320`、`nodes.py:571` |
| `draft_answer` | composer | critic | 待审查草稿 | `nodes.py:738`、`nodes.py:753` |
| `final_answer` | crisis/refuse/FAQ/critic/finalize | Orchestrator/API | 最终回答 | `nodes.py:250`、`nodes.py:264`、`nodes.py:318`、`nodes.py:764`、`nodes.py:795`、`nodes.py:844` |
| `needs_human` / `handoff_reason` | crisis/refuse/composer/critic/finalize | Orchestrator/API | 转人工标记与原因 | `nodes.py:251-252`、`nodes.py:265-266`、`nodes.py:740-741`、`nodes.py:797-798`、`nodes.py:845-846` |
| `risk_flags` | safety/executor/critic | Orchestrator/API | 风险标记 | `nodes.py:234`、`nodes.py:551`、`nodes.py:758` |
| `events` | 各节点 | Orchestrator/API/SSE | 事件轨迹 | `nodes.py:194`、`nodes.py:834-842` |

### 5.4 `Task` 与占位符

`Task` 结构来源：`schemas.py:149-154`。

| 字段 | 类型 | 必填/默认 | 说明 |
|---|---|---|---|
| `task_id` | `str` | 必填 | 任务 id，如 `t1`、`t2`、`r1` |
| `goal` | `str` | 必填 | 任务目标 |
| `tool` | `str` | 必填 | 工具名 |
| `args` | `dict[str, Any]` | 默认 `{}` | 工具入参 |
| `depends_on` | `list[str]` | 默认 `[]` | 依赖的 task_id |

`args` 中的 `$task_id.doc_id` 占位符由 executor 解析：取该任务返回的第一个文档的 `doc_id`；没有文档则解析为 `None`。来源：`nodes.py:168-181`、`nodes.py:445`。

- `verify_citation` 任务依赖上游检索；解析不到 `doc_id` 时记录 `DEPENDENCY_MISSING` 并跳过。来源：`nodes.py:446-454`。
- 工具调用达到 `max_tool_calls` 时记录 `TOOL_BUDGET_EXCEEDED` 并停止追加。来源：`nodes.py:435-443`。

---

## 6. `verify_citation` 校验规则

### 6.1 有效条件

`verify_citation` 返回 `valid=true` 必须同时满足：

| # | 条件 | 实现 | 来源 |
|---|---|---|---|
| 1 | `doc_id` 存在于 `InMemoryCorpus._by_id` | `corpus.get_doc(doc_id)` 非空 | `builtin.py:120-122`、`index.py:67`、`index.py:82-83` |
| 2 | 文档对调用方可见 | `access_level <= ctx.access_level` 且（`visible_to_roles` 为空或包含 `ctx.user_role`） | `builtin.py:123-124`、`schemas.py:99-102` |
| 3 | 条款匹配（如提供 `article_no`） | `article_no` 与文档 `article_no` 严格相等 | `builtin.py:125-126` |
| 4 | 文档现行有效 | `effective_date` 存在时不得晚于今天；`expiry_date` 存在时不得早于今天；日期解析失败视为无效 | `builtin.py:127-128`、`schemas.py:83-97` |

满足后返回：

```json
{ "valid": true, "reason": "OK", "doc": { "...": "DocumentPayload" } }
```

来源：`builtin.py:129`。

### 6.2 无效原因

| `reason` | 触发条件 | 来源 |
|---|---|---|
| `NOT_FOUND` | `doc_id` 不在 `_by_id` | `builtin.py:120-122` |
| `FORBIDDEN` | 文档不可见（access_level 不足或角色不在 visible_to_roles） | `builtin.py:123-124`、`schemas.py:99-102` |
| `ARTICLE_MISMATCH` | 提供的 `article_no` 与文档不一致 | `builtin.py:125-126` |
| `NOT_EFFECTIVE` | 未生效、已过期或日期解析失败 | `builtin.py:127-128`、`schemas.py:83-97` |

> 这些是业务结果：`ToolResult.ok` 仍为 `true`，`ToolError` 为空。只有注册表层的未知工具、参数校验失败、超时、其他异常才会使 `ok=false`。来源：`builtin.py:119-129`、`base.py:68-106`。

### 6.3 缺失与证据门禁

| 场景 | 行为 | 来源 |
|---|---|---|
| 上游检索没有文档，`verify_citation` 的 `doc_id` 解析为 `None` | executor 记录 `DEPENDENCY_MISSING`，不调用工具 | `nodes.py:446-454` |
| `verify_citation` 返回 `valid=false` | 不创建 Citation；合并 `CITATION_INVALID`（severity `high`）RiskFlag | `nodes.py:492-507`、`nodes.py:529-543` |
| 法规/混合问题缺少 `reg_` 前缀引用 | evidence_gate 返回 `evidence_ok=false`，触发 replan；最多 `max_replans` 次 | `nodes.py:556-568`、`nodes.py:108-113` |
| 达到重规划上限仍无有效法规引用 | composer 追加提示并将 `needs_human=true`、`handoff_reason="citation_unverified"` | `nodes.py:711-715` |

核心判定：

```python
has_reg_citation = any(c.doc_id.startswith("reg_") for c in citations)
if _has_regulation_need(intent, message):
    ok = has_reg_citation
else:
    ok = len(good) >= min_evidence_docs
```

来源：`nodes.py:562-568`。`_has_regulation_need` 的规则：`intent=="regulation"` 恒为真；`intent=="mixed"` 时消息包含任一法规关键词才为真。来源：`nodes.py:108-113`、`nodes.py:24-77`。

### 6.4 哪些引用算「已验证」

| 来源 | 是否经过 `verify_citation` | Citation 是否进入最终列表 | 来源 |
|---|---|---|---|
| 法规文档（经 `search_regulation`） | 是；executor 对未核验法规文档按插入顺序补核验，累计最多 3 次尝试 | 仅 `valid=true` 时进入 | `nodes.py:492-496`、`nodes.py:509-543` |
| 法规文档（经 `search_knowledge_base` 的 unknown 路径） | 否 | 直接进入，`valid` 默认 `true`；可能未核验 | `nodes.py:342-347`、`nodes.py:486-491` |
| 殡仪服务文档 | 否 | 直接进入，`valid` 默认 `true` | `nodes.py:486-491`、`schemas.py:115-126` |
| 文化习俗文档 | 否 | 直接进入，`valid` 默认 `true` | `nodes.py:486-491`、`schemas.py:115-126` |
| FAQ | 否 | 直接进入，`valid` 默认 `true` | `nodes.py:304-314` |

> 「已验证」只对经 `search_regulation` 的法规来源有实际含义；非法规来源和 unknown 路径的 `valid=true` 可能是模型默认值，不是核验结果。见 §4.4 与 §7.2 I10。

---

## 7. 待裁决冲突

### 7.1 代码与 `CLAUDE.md` 冲突

| # | 冲突 | 代码证据 | `CLAUDE.md` 证据 | 影响 | 待裁决 |
|---|---|---|---|---|---|
| C1 | 角色隔离缺少 Redis key 角色前缀层 | 会话为进程内存储：`session.py:1-28`；当前只有 `user_role` + `access_level` metadata 过滤（`schemas.py:99-102`）和 FAQ `visible_to_roles`（`index.py:131-133`） | `CLAUDE.md:83` 要求 `user_role` + `access_level` metadata 过滤 + **Redis key 角色前缀** + FAQ `visible_to_roles` 三层校验 | 进程重启后会话丢失；多实例部署时会话不共享；未达到「三层」约束 | 阶段 2 接 Redis 时必须补齐 key 前缀隔离；或明确裁决 MVP 阶段豁免 |
| C2 | 确定性 composer 的回答模板硬编码 | `nodes.py:652-720` 直接拼接回答文本；composer 的外部 Prompt 只覆盖 LLM system prompt（`configs/prompts/composer.v1.md`）；crisis/grief/smalltalk/refusal 模板已外置，但 composer 回答模板仍在代码中 | `CLAUDE.md:79` 要求 Prompt 模板放 `configs/prompts/` 并按版本号命名，禁止硬编码 | 若把回答模板视为 Prompt，则违反约束；替换为真实 LLM 时模板与 Prompt 可能漂移 | 裁决确定性回答模板是否属于「Prompt 模板」；若属于，需外置为版本化文件 |
| C3 | `llm/client.py` 单模块覆盖率低于 60% | 最近一次 `pytest-cov`：`src/everrag/llm/client.py` 31 行中 16 行未覆盖，48%；总体 92% | `CLAUDE.md:80` 要求「每个模块」覆盖率不低于 60% | 按单模块口径不达标；按总体口径达标 | 裁决覆盖率口径是「每模块」还是「项目总体」；若每模块，需补 OpenAI 兼容路径测试 |
| C4 | 文化习俗内容缺少 100% 业务顾问审核证据 | `data/samples/cultural_custom.jsonl:1-3` 均标注 `is_sample=true`，无审核记录字段 | `CLAUDE.md:82` 要求文化习俗库内容 100% 经业务顾问审核；民族/宗教类回答人工抽检 | 样例数据可用于开发，但不能据此宣称满足生产审核约束 | 裁决样例数据是否豁免；生产数据必须补审核记录与抽检流程 |

### 7.2 契约内部不一致（非 `CLAUDE.md` 冲突，但冻结前需裁决）

| # | 不一致 | 证据 | 影响 | 待裁决 |
|---|---|---|---|---|
| I1 | `citation` SSE 事件有两种 payload | FAQ 节点发 `{type, doc_id, title}`（`nodes.py:315`）；API 发完整 `Citation.model_dump()`，data 不含 `type`（`routes.py:56-57`、`schemas.py:105-113`） | 前端按统一字段解析会失败；同一 FAQ 可能收到两条 citation | 统一为完整 Citation，或明确区分 `citation` 与 `citation_ref` |
| I2 | `done` 事件有两种 payload | 图内 `finalize` 发 `{type, citations:int, needs_human, steps}`（`nodes.py:836-842`）；API 发 `{session_id, trace_id, intent, citations:list, needs_human, handoff_reason}`，data 不含 `type`（`routes.py:60-72`） | 直接用 LangGraph 事件的消费者与 SSE 消费者看到不同结构 | 裁决图内 `done` 是否仅内部使用；若是，API 过滤即为正式契约 |
| I3 | `tool_result` 有两种 payload | executor 版含 `type`、`task_id`、`total`、`valid`（`nodes.py:461-469`）；FAQ 版只有 `type`、`tool`、`ok`、`hit`（`nodes.py:297-303`） | 统一事件解析器需兼容两种分支 | 统一字段；或正式声明 FAQ 快速路径使用独立事件 |
| I4 | FAQ 快速路径没有 `tool_start` | FAQ 节点只发 `tool_result`（`nodes.py:297-303`）；executor 每次都发 `tool_start`（`nodes.py:458`） | 依赖 `tool_start`/`tool_result` 配对的客户端会缺开始事件 | 补 `tool_start`，或声明 FAQ 快速路径不参与配对 |
| I5 | `Citation` 没有 `source_type` / `kb_id` | `schemas.py:105-113` 只有 `doc_id`、`title` 等；来源类型只能按前缀推断 | 调用方无法稳定区分 doc/faq/regulation/custom；前缀约定不在模型层强制 | 是否新增字段属于契约变更；在冻结版中只能沿用前缀约定 |
| I6 | FAQ 引用无法通过 `/v1/citations/{doc_id}` 解析 | Citation 的 `doc_id=faq_id`（`nodes.py:309-314`），但 `get_doc` 只查 Document 索引（`index.py:67`、`index.py:82-83`），FAQ 不在其中（`routes.py:75-79`） | FAQ citation 的 `source_url` 可用，但点击引用详情会 404 | 让 `get_doc` 支持 FAQ，或在路由中分流 FAQ 查询 |
| I7 | SSE `error` 事件没有结构化错误码 | 只有 `{type, message}`（`orchestrator.py:67`）；`ToolError` 有 `code`/`retryable`（`schemas.py:135-138`），但未映射到 SSE | 客户端无法按错误码重试或分流；只能展示异常类名 | 是否为 `error` 增加 `code`/`retryable` 属于契约变更；需裁决 |
| I8 | 同步与 SSE 的 events 口径不同 | 同步 `ChatResponse.events` 包含图内 `done`（`orchestrator.py:82`）；SSE 明确过滤 `done`（`routes.py:53-54`） | 同一请求两种消费方式的事件序列不一致 | 统一是否暴露图内 `done`；或在文档中声明两种消费口径 |
| I9 | `Citation.valid` 语义不统一 | 经 `search_regulation` 的法规引用经过 `verify_citation` 才创建（`nodes.py:492-496`）；非法规、FAQ 以及 unknown 路径的法规文档直接创建，`valid` 默认为 `true`（`nodes.py:486-491`、`nodes.py:304-314`、`schemas.py:113`） | `valid=true` 不能统一表示「已验证」，容易误导前端 | 裁决 `valid` 定义；或新增 `verified` 字段（契约变更） |
| I10 | unknown 意图下法规引用可绕过 `verify_citation` | `planner` 对 `unknown` 使用 `search_knowledge_base` 且 collections 含 `regulation`（`nodes.py:342-347`）；executor 对非 `search_regulation` 工具直接建 Citation（`nodes.py:486-491`）；自动核验又跳过已在 `citations` 中的文档（`nodes.py:509-516`） | 未核验的法规引用可能进入最终回答，削弱 §6.3 的引用门禁 | 限制 `search_knowledge_base` 的 collections，或对 `kb_id=="regulation"` 的文档强制走 `verify_citation` |

### 7.3 未实现约束（非冲突，备注）

| # | 约束 | 现状 | 来源 |
|---|---|---|---|
| N1 | `CLAUDE.md:78` 的 `RegulationChunker` 条款级分块 | 阶段 1 直接加载 JSONL 样例，没有分块器；样例法规为整条短文本 | `CLAUDE.md:78`、`ingestion/loader.py:1-75` |
| N2 | `CLAUDE.md:83` 的 Redis 会话/缓存 | 使用 `InMemorySessionStore`，无 Redis | `session.py:1-28` |
| N3 | `CLAUDE.md:80` 的每模块 60% 覆盖率 | 总体 92%，`llm/client.py` 48% | 见 C3 |
| N4 | 生产级法规/习俗数据审核与抽检 | 仅样例数据，无审核记录 | 见 C4 |

---

## 8. 冻结规则

- 本文件 v1.0 冻结的是 **阶段 1 纵向切片的对外契约**：工具 Schema、API 请求/响应、SSE 事件、Citation、AgentState、verify_citation 规则。
- 替换内部实现（内存检索 → BM25、确定性 composer → 真实 LLM、进程内记忆 → Redis）时，**不得改变**本文件中的字段名、类型、必填/默认、错误码、事件类型与 payload 结构；只能替换内部实现。
- 任何契约变更必须：
  1. 在本文新增版本号与变更说明；
  2. 同步更新 `docs/implementation-status.md`；
  3. 跑全量 `pytest` 与 `eval.run_eval`，并在变更说明中附结果；
  4. 对受影响的前端、工具层、评测集做迁移说明。
- 本文件中的「待裁决冲突」在裁决前保持现状，不修改代码。

---

## 9. v1.1 增量：LLMComposer（2026-11-01）

> 本节是 v1.0 的增量；v1.0 已有字段、工具 Schema、API 路由不变。

### 9.1 新增可选响应字段

来源：`schemas.py:176-188`、`routes.py:60-72`。

| 字段 | 类型 | 默认 | 含义 |
|---|---|---|---|
| `degraded` | `bool` | `false` | LLMComposer 超时/错误后是否降级到确定性 composer |
| `citation_invalid` | `bool` | `false` | LLM 回答是否存在缺失引用或来源不存在的引用 |

- `ChatResponse` 新增这两个字段，旧字段不变。
- SSE `done` 新增这两个字段。
- `AgentState` 新增 `degraded`、`citation_invalid`（`state.py:48-49`）。

### 9.2 Composer 接口

- `LLMComposer.compose(state, on_token=None) -> ComposerResult`：主接口；支持逐 token 回调。来源：`llm/composer.py:110-144`。
- `LLMComposer.stream(state) -> Iterator[str]`：逐 token 产出。来源：`llm/composer.py:92-108`。
- `ComposerResult` 字段：`answer`、`citations`、`degraded`、`citation_invalid`、`error`、`latency_ms`、`model`。来源：`llm/composer.py:33-42`。
- `AgentNodes.composer` 的节点签名与返回结构保持兼容，新增 `degraded`、`citation_invalid`、`citations`、`risk_flags` 键；确定性 composer 路径保留为降级与对比基线。来源：`nodes.py:644-790`。
- 仅当 `settings.agent.llm.provider == "deepseek"` 且 `DEEPSEEK_API_KEY` 存在时启用；否则保持确定性 composer。来源：`llm/composer.py:197-205`。

### 9.3 Prompt 外置

- Prompt 文件：`configs/prompts/composer_v1.md`。
- 文件包含：温和尊重共情、仅基于检索证据、`[doc_id]` 引用格式、不确定时明确说无法确认。
- 代码只填充 `{{question}}` 与 `{{evidence}}`，不包含 Prompt 指令文本。来源：`llm/composer.py:84-89`。

### 9.4 降级与生成后引用核验

- 默认超时 15 秒。来源：`llm/composer.py:66`、`config.py:18`。
- LLM 超时/异常：`logger.exception` 记录原因，返回 `ComposerResult(degraded=True, error=...)`；`AgentNodes.composer` 回退到确定性 composer，并在响应标记 `degraded=true`。来源：`llm/composer.py:130-144`、`nodes.py:697-702`、`nodes.py:783-790`。
- 生成后解析 `[doc_id]`，逐个调用 `verify_citation`；来源不存在或核验失败的标记被移除，`citation_invalid=true`，并写入 `CITATION_INVALID` RiskFlag；critic 追加提示并设置 `handoff_reason="citation_unverified"`。来源：`llm/composer.py:146-180`、`nodes.py:657-690`、`nodes.py:802-880`。

### 9.5 测试与对比

- 单测：`tests/unit/test_llm_composer.py`（流式、无效/缺失引用、超时降级、Prompt 外置、API key 环境变量）。
- 集成测试：`tests/integration/test_composer_fallback.py`（降级回退、citation_invalid → critic）、`tests/integration/test_composer_api.py`（响应字段）。
- 对比脚本：`scripts/compare_composer.py`；无 key 时用 `--mock` 离线运行。

### 9.6 v1.2 增量：检索阈值拆分（2026-11-01）

> 本节是 v1.1 的增量；v1.0 / v1.1 已有的工具 Schema、API 路由、SSE、Citation、AgentState 与 `verify_citation` 契约不变。

| 字段 | 类型 | 默认 | 消费方 | 说明 |
|---|---|---|---|---|
| `retrieval.min_score_bm25` | `float` | `0.15` | `search_knowledge_base` 的 BM25 后端 | 仅 BM25 后端使用；memory 后端继续使用 `retrieval.min_score` |

- BM25 分数无上界，取决于 IDF 与语料规模；memory 覆盖率分数为 0–1 有界。**两者量纲不同，阈值不可跨后端复用。**
- `search_knowledge_base` 的工具 Schema、返回字段、错误码不变；阈值仍是系统级配置，不进入 `SearchKnowledgeBaseArgs`。
- `search_regulation` 继续使用 `retrieval.regulation_min_score`；在切换到 BM25 之前，该值仍按 memory 覆盖率标定。
- 对既有描述的影响：§1.3.1 中「检索使用 `settings.retrieval.min_score`」在 BM25 后端由 `min_score_bm25` 取代；§1.3.1 其余字段与结构不变。
- 配置落点：`configs/retrieval.yaml`；加载逻辑：`src/everrag/config.py`；后端阈值分配：`src/everrag/retrieval/backend.py`。
