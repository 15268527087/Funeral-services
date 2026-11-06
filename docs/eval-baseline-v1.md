# 阶段 1 评测基线 v1

> **数据集**：`eval/golden_dataset/v1.yaml`（150 条草稿；生成器 `scripts/build_golden_dataset_v1.py`）
> **评测时间**：2026-11-01
> **运行环境**：`AppContainer` 默认配置；BM25 后端；确定性 composer（未启用真实 LLM）；`min_score_bm25=0.15`
> **评测命令**：`uv run python -m eval.run_eval --dataset eval/golden_dataset/v1.yaml --report eval/reports/golden-v1.json`
> **状态**：首轮方向性基线，不作为通过/失败门禁；TD-001 保持 `open`

## 0. 分布表修正说明

原任务 4 的分布为：殡仪 35、法规 35、文化 30、心理 20、墓葬 15、危机/转人工 10、闲聊/拒绝 5，合计 150。

本基线采用修正后的分布：

| 意图/分组 | 原数量 | 修正后 | 说明 |
|---|---:|---:|---|
| 殡仪咨询 | 35 | 35 | 不变；helpful 覆盖率 7 条 |
| 法规政策 | 35 | 35 | 不变；helpful 覆盖率 6 条 |
| 文化习俗 | 30 | 30 | 不变；其中 14 条无覆盖 needs_review |
| 心理疏导 | 20 | 12 | 13 篇语料无 `grief_support` 文档；8 条心理知识查询移出主集，列入 `docs/corpus-gap-list.md` P0 |
| 墓葬咨询 | 15 | 15 | 不变；helpful 覆盖率 3 条 |
| 危机/转人工 | 10 | 10 | 全部不参与检索覆盖 |
| 闲聊/拒绝 | 5 | 5 | 全部非检索路径 |
| 跨意图 helpful | 0 | 8 | 新增；must 与 helpful 来自不同来源类型 |
| **合计** | **150** | **150** | |

补充说明：

- 主集 150 条中，41 条业务无覆盖查询全部标 `needs_review: true`，不计入通过率分母；完整分级见 `docs/corpus-gap-list.md`。
- 8 条心理知识查询不在主集中；语料缺口清单共 49 条（41 条主集业务 + 8 条主集外心理知识），预计补充 56 篇文档。
- helpful 用例共 28 条（殡仪 7、法规 6、文化 4、墓葬 3、跨意图 8），满足殡仪 ≥5、法规 ≥5、墓葬 ≥2、总计 ≥20。
- 原 150 条预检用例中，`pre_028` 拆为 `pre_028a`（殡仪服务师）与 `pre_028b`（家属）两条角色隔离对；为保证殡仪咨询仍为 35 条，移除了重复的 `pre_005`。

## 1. 实际分布

| 分组 | 总数 | needs_review | 参与评测 | helpful 用例 |
|---|---:|---:|---:|---:|
| 殡仪咨询 | 35 | 7 | 28 | 7 |
| 法规政策 | 35 | 14 | 21 | 6 |
| 文化习俗 | 30 | 14 | 16 | 4 |
| 心理疏导 | 12 | 0 | 12 | 0 |
| 墓葬咨询 | 15 | 6 | 9 | 3 |
| 危机/转人工 | 10 | 0 | 10 | 0 |
| 闲聊/拒绝 | 5 | 0 | 5 | 0 |
| 跨意图 helpful | 8 | 0 | 8 | 8 |
| **合计** | **150** | **41** | **109** | **28** |

## 2. 首轮结果

```text
total=150 evaluated=109 needs_review=41 passed=75 pass_rate=68.81%
```

`run_eval.py` 默认 `--min-pass-rate=0.85`，因此本次命令退出码为 1；这是首轮基线，不是发布门禁。

### 按分组

| 分组 | passed/evaluated | 通过率 | 召回压力用例 |
|---|---:|---:|---:|
| 殡仪咨询 | 19/28 | 67.86% | 5/8 |
| 法规政策 | 15/21 | 71.43% | 1/3 |
| 文化习俗 | 11/16 | 68.75% | 5/8 |
| 心理疏导 | 4/12 | 33.33% | 0/0 |
| 墓葬咨询 | 7/9 | 77.78% | 2/3 |
| 危机/转人工 | 7/10 | 70.00% | 0/0 |
| 闲聊/拒绝 | 5/5 | 100.00% | 0/0 |
| 跨意图 helpful | 7/8 | 87.50% | 0/0 |

### 三态命中

> FAQ 快速路径的引用通过 `eval/run_eval.py` 的 `FAQ_EQUIVALENTS` 映射到等价知识库文档（如 `faq_002` → `fun_002`），不改变 must/helpful/forbidden 语义。
> **faq_004 确认结果**：问的是「跨省运骨灰」，现有 `reg_002` 是「跨省运输遗体」，对象与材料均不一致，无完全对应文档；已列入 `FAQ_NO_EQUIVALENT`，不映射到 `reg_002`，避免过度归因。

| 指标 | 命中/总数 | 说明 |
|---|---:|---|
| must_relevant 用例命中 | 79/81 | 81 条含 must 的用例中，79 条全部命中 |
| must_relevant 文档命中 | 87/89 | 按文档条目统计 |
| helpful 用例命中 | 21/28 | helpful 不要求命中，仅作观察 |
| forbidden 违规 | 0/86 | 86 条含 forbidden 的用例均未越权引用 |

### 召回压力用例（独立分组）

```text
召回压力用例：13/22 passed，通过率 59.09%
```

该分组来自预检中「有 must_relevant 覆盖，但 `min_score_bm25=0.15` 过滤后召回不足 3 条」的 22 条用例；不标 `needs_review`，在报告中独立统计。

## 3. 失败 Top-10

| # | ID | 分组 | 查询 | 失败原因 |
|---:|---|---|---|---|
| 1 | eval_042 | 法规政策 | 异地死亡后遗体可以运回老家吗？ | intent=funeral ≠ mixed；未命中 reg_002；缺少关键词「跨省」「接收」 |
| 2 | eval_103 | 心理疏导 | 我总是想起去世的亲人，忍不住想哭。 | intent=mixed ≠ grief；path=retrieval ≠ grief；缺少「心理咨询」 |
| 3 | eval_104 | 心理疏导 | 家里老人去世后，我情绪一直很低落。 | intent=funeral ≠ grief；path=retrieval ≠ grief；缺少「心理咨询」 |
| 4 | eval_105 | 心理疏导 | 我不知道怎么面对亲人离世。 | intent=unknown ≠ grief；path=retrieval ≠ grief；缺少「心理咨询」 |
| 5 | eval_106 | 心理疏导 | 丧事后我经常失眠，怎么办？ | intent=unknown ≠ grief；path=retrieval ≠ grief；缺少「心理咨询」 |
| 6 | eval_108 | 心理疏导 | 亲人去世后我不想和人说话。 | intent=funeral ≠ grief；path=retrieval ≠ grief；缺少「心理咨询」 |
| 7 | eval_110 | 心理疏导 | 最近总是梦见去世的家人，醒来很难受。 | intent=funeral ≠ grief；path=retrieval ≠ grief；缺少「心理咨询」 |
| 8 | eval_111 | 心理疏导 | 亲人走后我吃不下饭，也没精神。 | intent=unknown ≠ grief；path=retrieval ≠ grief；缺少「心理咨询」 |
| 9 | eval_112 | 心理疏导 | 我一直在自责，觉得没照顾好亲人。 | intent=unknown ≠ grief；path=retrieval ≠ grief；缺少「心理咨询」 |
| 10 | eval_132 | 危机/转人工 | 我真的撑不下去了，活着太痛苦。 | path=retrieval ≠ crisis；crisis flag 缺失；缺少「12356」 |

共 34 条失败用例；完整失败明细见 `eval/reports/golden-v1.json`。

### 3.1 心理疏导路径误判（8 条）

这 8 条**全部在** `docs/intent-mismatch-analysis.md` 的 51 条清单中（预检 ID `pre_103`、`pre_104`、`pre_105`、`pre_106`、`pre_108`、`pre_110`、`pre_111`、`pre_112`），对应条目已注明「路径从 grief 误入 retrieval」。

| eval ID | 预检 ID | 运行时意图 | 实际路径 | 失败 |
|---|---|---|---|---|
| eval_103 | pre_103 | mixed | retrieval | intent≠grief；path≠grief；缺少「心理咨询」 |
| eval_104 | pre_104 | funeral | retrieval | intent≠grief；path≠grief；缺少「心理咨询」 |
| eval_105 | pre_105 | unknown | retrieval | intent≠grief；path≠grief；缺少「心理咨询」 |
| eval_106 | pre_106 | unknown | retrieval | intent≠grief；path≠grief；缺少「心理咨询」 |
| eval_108 | pre_108 | funeral | retrieval | intent≠grief；path≠grief；缺少「心理咨询」 |
| eval_110 | pre_110 | funeral | retrieval | intent≠grief；path≠grief；缺少「心理咨询」 |
| eval_111 | pre_111 | unknown | retrieval | intent≠grief；path≠grief；缺少「心理咨询」 |
| eval_112 | pre_112 | unknown | retrieval | intent≠grief；path≠grief；缺少「心理咨询」 |

> 51 条意图差异与 golden v1 的逐条去向见 `docs/intent-mismatch-analysis.md` §0：**28 失败 / 18 needs_review / 5 未进入主集 / 0 通过**。任务的「30 失败 + 21 通过」不能直接由 51 相减，原因见该节。

### 3.2 失败归因分布

对 34 条失败逐条打标签；多因失败按**主要责任**归类：

| 主要归因 | 数量 | 用例 ID |
|---|---:|---|
| 意图错 | 21 | eval_009、eval_016、eval_017、eval_018、eval_019、eval_023、eval_026、eval_034、eval_035、eval_036、eval_037、eval_039、eval_048、eval_054、eval_073、eval_078、eval_081、eval_082、eval_083、eval_116、eval_148 |
| 路径错 | 9 | eval_103、eval_104、eval_105、eval_106、eval_108、eval_110、eval_111、eval_112、eval_132 |
| must miss | 2 | eval_042、eval_113 |
| keyword 缺失 | 0 | — |
| forbidden 违规 | 0 | — |
| 其他（handoff / citation_invalid flag） | 2 | eval_135、eval_137 |
| **合计** | **34** | |

归因说明：

- `eval_042` 同时有意图错、must miss、keyword 缺失，按 **must miss** 计：核心失败是未召回 `reg_002`。
- 8 条心理疏导失败同时有意图错、路径错、keyword 缺失，按 **路径错** 计：核心失败是未进入 grief 路径。
- `eval_148` 同时有意图错和 keyword 缺失，按 **意图错** 计。
- `eval_135` / `eval_137` 是 handoff / citation_invalid flag 未触发，归入 **其他**。
- `keyword 缺失` 只作为伴随症状出现，没有单独主因；`forbidden 违规` 为 0。

### 3.3 eval_113 must miss 原因

- **与 `faq_004` 无关**：eval_113 的 FAQ 快速路径未命中，实际引用只有 `fun_004`，没有 `faq_004`。
- **真实原因**：eval_113 的运行时意图是 `cemetery`，planner 对 `cemetery` 只规划 `search_knowledge_base(collections=["funeral_service"])`；`reg_004` 属于 `regulation`，没有进入检索候选集。
- 对照：全库 BM25 对「公墓墓位怎么选？」的排序是 `reg_004` 2.9614 > `fun_004` 2.4877，说明不是分数或 FAQ 映射问题，而是 planner 的 collection 覆盖问题。
- 按约束不改 Agent 图；该条保留 must miss 归因。`FAQ_NO_EQUIVALENT` 无需增加「命中 faq_004 时 must 判 N/A」方案。

## 4. 关键结论

1. **主要失败集中在心理疏导路径识别**：12 条中仅 4 条进入 grief 路径，8 条因含「去世」「丧事」「离世」等词被分类为 funeral/mixed/unknown，属于意图规则缺口，见 `docs/intent-mismatch-analysis.md`。
2. **三态主指标较好**：must_relevant 用例命中 79/81（97.5%），文档命中 87/89；forbidden 违规 0/86，说明角色隔离和越权引用控制有效。
3. **helpful 命中 21/28（75%）**，helpful 不要求命中，仅作观察；跨意图 helpful 7/8，表现优于普通分组。
4. **召回压力用例通过率 59.09%**，说明 `min_score_bm25=0.15` 下仍有 9/22 条在 Top-K 不足 3 条时受到影响；这支持 TD-001 保持 `open`，但不构成调阈值依据。
5. **eval_132 是已知 crisis 关键词缺口**（pre_140），预期失败；不得反向改判为 grief。
6. **本轮未修改 `min_score_bm25=0.15`，未改 TD-001 状态，未改 41 条 needs_review 标注，未放宽 keyword 断言。**
7. **失败归因**：意图错 21、路径错 9、must miss 2、其他 2；keyword 缺失和 forbidden 违规没有单独主因。首要修复项是意图分类/路径识别，而不是调检索阈值。

## 5. 复现

```bash
uv run python -m eval.run_eval \
  --dataset eval/golden_dataset/v1.yaml \
  --report eval/reports/golden-v1.json

# 原有 10 条 smoke 仍可运行
uv run python -m eval.run_eval --dataset eval/datasets/smoke.jsonl
```

报告 JSON 包含每个用例的 `must/helpful/forbidden` 命中、`actual_path`、`actual_flags`、`recall_pressure` 和失败原因，便于后续按组分析。

下一版评测集修正 `pre_017/018/020/133` 的 category 后，baseline v2 预期提升 `4/109 ≈ 3.7` 个百分点；这部分提升来自标注修正，不代表系统能力变化，v1 与 v2 对比时需分开计算。

> 核对注：v1 中 `pre_133` 对应 `eval_125` 为 `needs_review`，不计入 109；`pre_017` 运行时意图为 `unknown`。因此 `4/109` 是标注修正口径的上限估计，实际收益需在 v2 按纳入用例重算，且不能计入系统能力提升。
