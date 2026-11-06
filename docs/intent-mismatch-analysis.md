# 意图差异分析（51 条）

> 来源：`scripts/precheck_eval_retrieval.py` 的 150 条候选查询预检。
> 状态：分析记录，不修改标注；51 条全部保留在 golden dataset 中。
> 说明：若某条同时属于 41 条无覆盖 needs_review，仍只按覆盖策略标 needs_review，不因意图差异额外标记。
> 注：`pre_028` 在 golden dataset 中拆为 `pre_028a`（服务师）与 `pre_028b`（家属），两条保留同一意图差异；本表按预检 ID 记一次。

## 0. golden v1 统计核对（2026-11-02）

任务给出的口径是「51 条中失败 30 条（意图错 21 + 路径错 9），通过 21 条」。按 golden v1 的 `source_precheck_id` 逐条映射，实际分布为：

| 去向 | 数量 | 说明 |
|---|---:|---|
| 主集失败 | 28 | 19 条意图错 + 8 条路径错 + 1 条 must miss（按预检 ID 去重；`pre_028` 在 golden 中拆成 `eval_034`/`eval_035`，两条均失败） |
| needs_review | 18 | 所在用例被排除，不计入通过/失败 |
| 未进入主集 | 5 | `pre_113`、`pre_114`、`pre_115`、`pre_116`、`pre_118`（心理疏导缩减） |
| 通过 | 0 | 无 |
| 合计 | 51 | |

逐条 ID：

- **失败-意图错（19）**：`pre_010`、`pre_017`、`pre_018`、`pre_019`、`pre_020`、`pre_024`、`pre_027`、`pre_028`、`pre_036`、`pre_037`、`pre_039`、`pre_048`、`pre_054`、`pre_073`、`pre_078`、`pre_081`、`pre_082`、`pre_083`、`pre_124`
- **失败-路径错（8）**：`pre_103`、`pre_104`、`pre_105`、`pre_106`、`pre_108`、`pre_110`、`pre_111`、`pre_112`
- **失败-must miss（1）**：`pre_042`
- **needs_review（18）**：`pre_030`、`pre_032`、`pre_034`、`pre_056`、`pre_057`、`pre_061`、`pre_062`、`pre_064`、`pre_065`、`pre_067`、`pre_068`、`pre_087`、`pre_094`、`pre_096`、`pre_097`、`pre_098`、`pre_099`、`pre_133`
- **未进入主集（5）**：`pre_113`、`pre_114`、`pre_115`、`pre_116`、`pre_118`
- **通过（0）**：无

> 结论：任务要求的「21 条意图差异但通过」在当前 golden v1 中不存在；实际是 0 条通过。全局 30 条失败（21 intent + 9 path）不是 51 条的子集：其中 `eval_148`（跨意图新增）和 `eval_132`（crisis 缺口）不在 51 内，且 `pre_028` 在 golden 中拆成两条；51 内另有 18 条 needs_review、5 条未进入主集。若把 needs_review + 未进入主集算作「非失败」，数量是 23，不是 21。

## 1. 分类口径

| 类型 | 定义 | 数量 | 处理建议 |
|---|---|---:|---|
| A 分类器问题 | 语义标注正确，关键词分类器缺词/误命中，影响 expected_path 或工具族 | 28 | 保留标注，记录为阶段 2 意图分类升级项 |
| B 标注问题 | category/主次意图需要调整，分类器与标注双方需对齐 | 9 | 本轮不改标注；正式规范复评时调整 |
| C 路径不影响答案 | 语义与运行时都走 retrieval，仅意图统计/工具组合差异 | 14 | 保留，记录即可 |
| 合计 | | 51 | |

## 2. 代表用例

### A 分类器问题
- `pre_103`「我总是想起去世的亲人，忍不住想哭。」：语义为心理疏导，运行时 `mixed`，会被错误路由到 retrieval，丢失 grief 路径。
- `pre_124`「生态葬有哪些形式？」：语义为墓葬咨询，运行时 `unknown`，原因是关键词表缺少「生态葬」。
- `pre_064`「殡仪馆经营需要什么许可？」：语义为法规政策，运行时 `funeral`，关键词「殡仪」压过了「许可」。

### B 标注问题
- `pre_017`「生态葬包括哪些形式？」：归在殡仪咨询，但主题是墓葬咨询；category 应调整。
- `pre_036`「殡葬管理条例对建坟有哪些规定？」：核心是法规政策，标注为法规政策+墓葬咨询，次意图过宽。
- `pre_133`「夫妻合葬需要什么手续？」：只标墓葬咨询，缺少法规政策次意图。

### C 路径不影响答案
- `pre_010`「火化需要死亡证明吗？」：语义殡仪咨询，运行时 mixed；两者都走 retrieval，required 文档仍可命中。
- `pre_057`「生态葬有补贴政策吗？」：语义法规政策+墓葬咨询，运行时 regulation；都属于 retrieval 路径。
- `pre_073`「回族丧葬中遗体怎么处理？」：语义文化习俗，运行时 mixed；都属于 retrieval 路径。

## 3. 全部 51 条清单

| ID | 主题分类 | 标注意图 | 运行时意图 | expected_path | 类型 | 原因 | 处置决定 |
|---|---|---|---|---|---|---|---|
| pre_010 | 殡仪咨询 | 殡仪咨询 | mixed | retrieval | C | 语义与运行时都走 retrieval；mixed/单意图差异不改变本用例 expected_path 与 required 文档。 | — |
| pre_017 | 殡仪咨询 | 殡仪咨询 | unknown | retrieval | B | 「生态葬」当前归殡仪咨询，主题应为墓葬咨询；category/primary 标注需调整。 | fix_annotation |
| pre_018 | 殡仪咨询 | 殡仪咨询 | cemetery | retrieval | B | 树葬/草坪葬/海葬属于墓葬主题；category 标注应改为墓葬咨询。 | fix_annotation |
| pre_019 | 殡仪咨询 | 殡仪咨询 | mixed | retrieval | C | 语义与运行时都走 retrieval；mixed/单意图差异不改变本用例 expected_path 与 required 文档。 | — |
| pre_020 | 殡仪咨询 | 殡仪咨询 | cemetery | retrieval | B | 「落葬」属于墓葬主题；category 标注应改为墓葬咨询。 | fix_annotation |
| pre_024 | 殡仪咨询 | 殡仪咨询 | unknown | retrieval | A | 关键词表缺少该主题词，语义意图正确但运行时 unknown。 | — |
| pre_027 | 殡仪咨询 | 殡仪咨询 | unknown | retrieval | A | 关键词表缺少该主题词，语义意图正确但运行时 unknown。 | — |
| pre_028 | 殡仪咨询 | 殡仪咨询 | mixed | retrieval | C | 语义与运行时都走 retrieval；mixed/单意图差异不改变本用例 expected_path 与 required 文档。 | — |
| pre_030 | 殡仪咨询 | 殡仪咨询 | regulation | retrieval | B | 「死亡证明补办」更接近法规/办事流程；应在殡仪/法规之间明确主次。 | needs_review |
| pre_032 | 殡仪咨询 | 殡仪咨询 | unknown | retrieval | A | 关键词表缺少该主题词，语义意图正确但运行时 unknown。 | — |
| pre_034 | 殡仪咨询 | 殡仪咨询 | unknown | retrieval | A | 关键词表缺少该主题词，语义意图正确但运行时 unknown。 | — |
| pre_036 | 法规政策 | 法规政策+墓葬咨询 | regulation | retrieval | B | 核心是条例规定；法规政策+墓葬咨询的次意图过宽，建议主意图法规政策。 | accept_as_is |
| pre_037 | 法规政策 | 法规政策+墓葬咨询 | cemetery | retrieval | B | 核心是法规禁止区域；次意图墓葬咨询过宽。 | accept_as_is |
| pre_039 | 法规政策 | 法规政策 | unknown | retrieval | A | 关键词表缺少该主题词，语义意图正确但运行时 unknown。 | — |
| pre_042 | 法规政策 | 法规政策+殡仪咨询 | funeral | retrieval | B | 核心是跨省运输资格；次意图殡仪咨询可保留但需评审。 | accept_as_is |
| pre_048 | 法规政策 | 法规政策 | mixed | retrieval | C | 语义与运行时都走 retrieval；mixed/单意图差异不改变本用例 expected_path 与 required 文档。 | — |
| pre_054 | 法规政策 | 法规政策+墓葬咨询 | unknown | retrieval | B | 核心是法规禁令；次意图墓葬咨询过宽。 | needs_review |
| pre_056 | 法规政策 | 法规政策+墓葬咨询 | funeral | retrieval | A | 关键词命中另一业务族，语义意图正确但工具族/路径选择错误。 | — |
| pre_057 | 法规政策 | 法规政策+墓葬咨询 | regulation | retrieval | C | 语义与运行时都走 retrieval；mixed/单意图差异不改变本用例 expected_path 与 required 文档。 | — |
| pre_061 | 法规政策 | 法规政策+墓葬咨询 | cemetery | retrieval | C | 语义与运行时都走 retrieval；mixed/单意图差异不改变本用例 expected_path 与 required 文档。 | — |
| pre_062 | 法规政策 | 法规政策 | mixed | retrieval | C | 语义与运行时都走 retrieval；mixed/单意图差异不改变本用例 expected_path 与 required 文档。 | — |
| pre_064 | 法规政策 | 法规政策 | funeral | retrieval | A | 关键词命中另一业务族，语义意图正确但工具族/路径选择错误。 | — |
| pre_065 | 法规政策 | 法规政策+墓葬咨询 | cemetery | retrieval | C | 语义与运行时都走 retrieval；mixed/单意图差异不改变本用例 expected_path 与 required 文档。 | — |
| pre_067 | 法规政策 | 法规政策 | funeral | retrieval | A | 关键词命中另一业务族，语义意图正确但工具族/路径选择错误。 | — |
| pre_068 | 法规政策 | 法规政策+墓葬咨询 | unknown | retrieval | A | 关键词表缺少该主题词，语义意图正确但运行时 unknown。 | — |
| pre_073 | 文化习俗 | 文化习俗 | mixed | retrieval | C | 语义与运行时都走 retrieval；mixed/单意图差异不改变本用例 expected_path 与 required 文档。 | — |
| pre_078 | 文化习俗 | 文化习俗 | mixed | retrieval | C | 语义与运行时都走 retrieval；mixed/单意图差异不改变本用例 expected_path 与 required 文档。 | — |
| pre_081 | 文化习俗 | 文化习俗 | mixed | retrieval | C | 语义与运行时都走 retrieval；mixed/单意图差异不改变本用例 expected_path 与 required 文档。 | — |
| pre_082 | 文化习俗 | 文化习俗 | unknown | retrieval | A | 关键词表缺少该主题词，语义意图正确但运行时 unknown。 | — |
| pre_083 | 文化习俗 | 文化习俗 | mixed | retrieval | C | 语义与运行时都走 retrieval；mixed/单意图差异不改变本用例 expected_path 与 required 文档。 | — |
| pre_087 | 文化习俗 | 文化习俗 | mixed | retrieval | C | 语义与运行时都走 retrieval；mixed/单意图差异不改变本用例 expected_path 与 required 文档。 | — |
| pre_094 | 文化习俗 | 文化习俗 | mixed | retrieval | C | 语义与运行时都走 retrieval；mixed/单意图差异不改变本用例 expected_path 与 required 文档。 | — |
| pre_096 | 文化习俗 | 文化习俗 | unknown | retrieval | A | 关键词表缺少该主题词，语义意图正确但运行时 unknown。 | — |
| pre_097 | 文化习俗 | 文化习俗 | unknown | retrieval | A | 关键词表缺少该主题词，语义意图正确但运行时 unknown。 | — |
| pre_098 | 文化习俗 | 文化习俗 | unknown | retrieval | A | 关键词表缺少该主题词，语义意图正确但运行时 unknown。 | — |
| pre_099 | 文化习俗 | 文化习俗 | unknown | retrieval | A | 关键词表缺少该主题词，语义意图正确但运行时 unknown。 | — |
| pre_103 | 心理疏导 | 心理疏导 | mixed | grief | A | 语义为心理疏导；关键词分类器命中 funeral/mixed/unknown，会误路由到 retrieval；路径从 grief 误入 retrieval。 | — |
| pre_104 | 心理疏导 | 心理疏导 | funeral | grief | A | 语义为心理疏导；关键词分类器命中 funeral/mixed/unknown，会误路由到 retrieval；路径从 grief 误入 retrieval。 | — |
| pre_105 | 心理疏导 | 心理疏导 | unknown | grief | A | 语义为心理疏导；关键词分类器命中 funeral/mixed/unknown，会误路由到 retrieval；路径从 grief 误入 retrieval。 | — |
| pre_106 | 心理疏导 | 心理疏导 | unknown | grief | A | 语义为心理疏导；关键词分类器命中 funeral/mixed/unknown，会误路由到 retrieval；路径从 grief 误入 retrieval。 | — |
| pre_108 | 心理疏导 | 心理疏导 | funeral | grief | A | 语义为心理疏导；关键词分类器命中 funeral/mixed/unknown，会误路由到 retrieval；路径从 grief 误入 retrieval。 | — |
| pre_110 | 心理疏导 | 心理疏导 | funeral | grief | A | 语义为心理疏导；关键词分类器命中 funeral/mixed/unknown，会误路由到 retrieval；路径从 grief 误入 retrieval。 | — |
| pre_111 | 心理疏导 | 心理疏导 | unknown | grief | A | 语义为心理疏导；关键词分类器命中 funeral/mixed/unknown，会误路由到 retrieval；路径从 grief 误入 retrieval。 | — |
| pre_112 | 心理疏导 | 心理疏导 | unknown | grief | A | 语义为心理疏导；关键词分类器命中 funeral/mixed/unknown，会误路由到 retrieval；路径从 grief 误入 retrieval。 | — |
| pre_113 | 心理疏导 | 心理疏导 | unknown | grief | A | 语义为心理疏导；关键词分类器命中 funeral/mixed/unknown，会误路由到 retrieval。 | — |
| pre_114 | 心理疏导 | 心理疏导 | funeral | grief | A | 语义为心理疏导；关键词分类器命中 funeral/mixed/unknown，会误路由到 retrieval。 | — |
| pre_115 | 心理疏导 | 心理疏导 | funeral | grief | A | 语义为心理疏导；关键词分类器命中 funeral/mixed/unknown，会误路由到 retrieval。 | — |
| pre_116 | 心理疏导 | 心理疏导 | funeral | grief | A | 语义为心理疏导；关键词分类器命中 funeral/mixed/unknown，会误路由到 retrieval。 | — |
| pre_118 | 心理疏导 | 心理疏导 | unknown | grief | A | 语义为心理疏导；关键词分类器命中 funeral/mixed/unknown，会误路由到 retrieval。 | — |
| pre_124 | 墓葬咨询 | 墓葬咨询 | unknown | retrieval | A | 关键词表缺少该主题词，语义意图正确但运行时 unknown。 | — |
| pre_133 | 墓葬咨询 | 墓葬咨询 | regulation | retrieval | B | 「夫妻合葬需要什么手续」应补法规政策次意图；当前只标墓葬咨询。 | fix_annotation |

## 3.1 B 类 9 条处置决定

| ID | 处置决定 | 理由 |
|---|---|---|
| pre_017 | fix_annotation | category 应为墓葬咨询；下一版评测集修正，本任务不改数据集。 |
| pre_018 | fix_annotation | 树葬/草坪葬/海葬属墓葬主题；下一版修正 category。 |
| pre_020 | fix_annotation | 落葬属墓葬主题；下一版修正 category。 |
| pre_030 | needs_review | 殡仪/法规主次意图不清，需人工裁决。 |
| pre_036 | accept_as_is | 法规+墓葬的混合标注可辩护；保留，记录分类器粒度差异。 |
| pre_037 | accept_as_is | 法规禁止区域+坟墓的混合标注可辩护；保留。 |
| pre_042 | accept_as_is | 跨省运输资格+遗体的混合标注可辩护；保留。 |
| pre_054 | needs_review | 法规禁令与墓葬主题边界不清，需人工评审。 |
| pre_133 | fix_annotation | 应补法规政策次意图；下一版修正。 |

> 处置决定只记录，不在本任务修改评测集；`fix_annotation` 进入下一版数据集复评，`needs_review` 进入人工裁决队列。

## 4. 意图错 21 条的三类标签

> 口径说明：baseline 的「意图错 21」按 golden 失败用例计，**不含** 8 条心理疏导（心理疏导在「路径错 9」中）。因此「21 - 8 = 13」的口径不成立；8 条心理疏导已单独列在 baseline §3.1。以下给出 21 条全量标签。

| 标签 | 数量 | 用例 ID |
|---|---:|---|
| classifier_truly_wrong | 6 | eval_023、eval_026、eval_039、eval_054、eval_082、eval_116 |
| annotation_too_strict | 12 | eval_009、eval_016、eval_017、eval_018、eval_019、eval_036、eval_037、eval_048、eval_073、eval_078、eval_081、eval_083 |
| ambiguous | 3 | eval_034、eval_035、eval_148 |
| **合计** | **21** | |

标签口径：

- `classifier_truly_wrong`：关键词表缺词或命中错误业务族；语义标注本身正确（如 unknown、funeral 误命中）。
- `annotation_too_strict`：查询实际包含多个合理维度（如火化+证明、文化+殡仪），标注只给单意图；或 category 与主题不一致。
- `ambiguous`：混合/单一意图均可辩护，无法仅凭现有语料裁决（如 pre_028 的流程+费用、跨意图新增用例）。

### 4.1 可审计的 13 条非 B 子集（替代口径）

由于「21 排除 8 条心理疏导」不成立，若必须给出 13 条清单，只能按「排除 B 类标注问题」定义：从 51 内的 19 条意图错中排除 6 条 B 类失败（`pre_017`、`pre_018`、`pre_020`、`pre_036`、`pre_037`、`pre_054`），得到 13 条预检 ID：

| 标签 | 数量 | 预检 ID / eval ID |
|---|---:|---|
| classifier_truly_wrong | 5 | `pre_024`/eval_023、`pre_027`/eval_026、`pre_039`/eval_039、`pre_082`/eval_082、`pre_124`/eval_116 |
| annotation_too_strict | 7 | `pre_010`/eval_009、`pre_019`/eval_018、`pre_048`/eval_048、`pre_073`/eval_073、`pre_078`/eval_078、`pre_081`/eval_081、`pre_083`/eval_083 |
| ambiguous | 1 | `pre_028`/eval_034、eval_035（golden 拆成两条，按预检 ID 计 1 条） |
| **合计** | **13** | |

> 这是「非 B 类意图错」口径，不是任务所述「21 - 8 条心理疏导」口径；两种口径不可混用。

## 5. 结论

- 51 条差异中 A 类 28 条，说明主要问题是关键词分类器覆盖不足，而非标注本身。
- B 类 9 条需要在正式标注规范复评时调整 category/主次意图；本轮按策略不改标注。
- C 类 14 条不改变 retrieval 路径，可在基线中作为意图统计偏差记录。
- 所有 51 条均不额外标 needs_review；pre_140 的 crisis 缺口单独记录在 baseline。
