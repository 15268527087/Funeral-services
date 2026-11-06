"""生成 eval/golden_dataset/v1.yaml（150 条评测草稿）。

数据来源：
- scripts/precheck_eval_retrieval.py 的 150 条预检候选与覆盖/召回结果；
- 已确认策略：41 条业务无覆盖标记 needs_review；pre_028 拆成角色隔离对；
  22 条有覆盖召回不足保留并标注召回压力；心理疏导缩为 12 条路径用例；
  新增 8 条跨意图 helpful 用例。

只生成评测集草稿，不修改配置或评测逻辑。
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import yaml
from precheck_eval_retrieval import (
    CANDIDATES_TEXT,
    BM25Index,
    InMemoryCorpus,
    evaluate,
    load_settings,
    parse_candidates,
)

ROLE_LABELS = {"家属", "殡仪服务师", "墓园顾问", "心理咨询师", "客户经理"}

DOC_KEYWORDS: dict[str, list[str]] = {
    "fun_001": ["死亡证明", "身份证明"],
    "fun_002": ["死亡证明", "身份证明"],
    "fun_003": ["告别仪式", "默哀"],
    "fun_004": ["骨灰", "生态葬"],
    "fun_005": ["寿衣", "骨灰盒"],
    "fun_006": ["哀悼", "语速"],
    "reg_001": ["审批", "坟墓"],
    "reg_002": ["跨省", "接收"],
    "reg_003": ["减免", "低保证"],
    "reg_004": ["墓位", "祭扫"],
    "cul_001": ["回族", "速葬"],
    "cul_002": ["助念", "诵经"],
    "cul_003": ["甘肃", "落葬"],
}

BANNED = ["保证办理", "百分百", "绝对没问题", "包过"]

# 预检 41 条业务无覆盖：P0/P1/P2 与预计补充文档数（P0 宗教/民族主题各 2 篇，其余 1 篇）。
GAP_INFO: dict[str, tuple[str, int]] = {
    # P0
    "pre_086": ("P0", 2),
    "pre_087": ("P0", 2),
    "pre_088": ("P0", 2),
    "pre_089": ("P0", 2),
    "pre_090": ("P0", 2),
    "pre_091": ("P0", 2),
    "pre_092": ("P0", 2),
    # P1
    "pre_029": ("P1", 1),
    "pre_030": ("P1", 1),
    "pre_033": ("P1", 1),
    "pre_056": ("P1", 1),
    "pre_057": ("P1", 1),
    "pre_058": ("P1", 1),
    "pre_059": ("P1", 1),
    "pre_060": ("P1", 1),
    "pre_061": ("P1", 1),
    "pre_062": ("P1", 1),
    "pre_063": ("P1", 1),
    "pre_064": ("P1", 1),
    "pre_065": ("P1", 1),
    "pre_066": ("P1", 1),
    "pre_067": ("P1", 1),
    "pre_068": ("P1", 1),
    "pre_069": ("P1", 1),
    "pre_093": ("P1", 1),
    "pre_094": ("P1", 1),
    "pre_095": ("P1", 1),
    "pre_127": ("P1", 1),
    "pre_130": ("P1", 1),
    "pre_131": ("P1", 1),
    "pre_134": ("P1", 1),
    # P2
    "pre_031": ("P2", 1),
    "pre_032": ("P2", 1),
    "pre_034": ("P2", 1),
    "pre_035": ("P2", 1),
    "pre_096": ("P2", 1),
    "pre_097": ("P2", 1),
    "pre_098": ("P2", 1),
    "pre_099": ("P2", 1),
    "pre_132": ("P2", 1),
    "pre_133": ("P2", 1),
}

# 预检 coverage 是主题级初筛；个别用例在正式标注中拆成 must + helpful。
MUST_OVERRIDE: dict[str, list[str]] = {
    "pre_009": ["reg_003"],
    "pre_014": ["fun_003"],
}

HELPFUL: dict[str, list[str]] = {
    # 殡仪咨询
    "pre_003": ["fun_003"],
    "pre_009": ["fun_002"],
    "pre_014": ["cul_002"],
    "pre_020": ["reg_004"],
    "pre_026": ["fun_003"],
    "pre_028a": ["fun_003"],
    "pre_028b": ["fun_003"],
    # 法规政策
    "pre_040": ["fun_001"],
    "pre_044": ["fun_002"],
    "pre_045": ["fun_002"],
    "pre_048": ["fun_002"],
    "pre_050": ["cul_003"],
    "pre_053": ["cul_003"],
    # 文化习俗
    "pre_071": ["fun_003"],
    "pre_076": ["fun_003"],
    "pre_081": ["reg_004"],
    "pre_085": ["fun_004"],
    # 墓葬咨询
    "pre_121": ["cul_003"],
    "pre_122": ["cul_003"],
    "pre_128": ["cul_003"],
}

FUNERAL_IDS = [
    f"pre_{i:03d}" for i in range(1, 36) if i not in {5, 28}
] + ["pre_028a", "pre_028b"]
REGULATION_IDS = [f"pre_{i:03d}" for i in range(36, 71)]
CULTURAL_IDS = [f"pre_{i:03d}" for i in range(71, 101)]
CEMETERY_IDS = [f"pre_{i:03d}" for i in range(121, 136)]
PSYCH_IDS = [f"pre_{i:03d}" for i in range(101, 113)]
CRISIS_IDS = [f"pre_{i:03d}" for i in range(136, 141)]
HANDOFF_IDS = [f"pre_{i:03d}" for i in range(141, 146)]
SMALLTALK_IDS = [f"pre_{i:03d}" for i in range(146, 151)]

CROSS_CASES = [
    {
        "source": "new_cross_01",
        "query": "回族跨省运输遗体需要什么手续和习俗？",
        "role": "家属",
        "intent": ["法规政策", "文化习俗"],
        "must": ["reg_002"],
        "helpful": ["cul_001"],
        "keywords": ["跨省", "回族"],
    },
    {
        "source": "new_cross_02",
        "query": "甘肃公墓安葬有什么规定和当地习俗？",
        "role": "墓园顾问",
        "intent": ["法规政策", "文化习俗"],
        "must": ["reg_004"],
        "helpful": ["cul_003"],
        "keywords": ["公墓", "甘肃"],
    },
    {
        "source": "new_cross_03",
        "query": "佛教告别仪式和通用告别流程有什么不同？",
        "role": "家属",
        "intent": ["文化习俗", "殡仪咨询"],
        "must": ["cul_002"],
        "helpful": ["fun_003"],
        "keywords": ["佛教", "告别"],
    },
    {
        "source": "new_cross_04",
        "query": "低保户火化减免需要准备什么材料？",
        "role": "家属",
        "intent": ["法规政策", "殡仪咨询"],
        "must": ["reg_003"],
        "helpful": ["fun_002"],
        "keywords": ["减免", "死亡证明"],
    },
    {
        "source": "new_cross_05",
        "query": "公墓落葬有哪些方式，需要什么手续？",
        "role": "墓园顾问",
        "intent": ["墓葬咨询", "法规政策"],
        "must": ["fun_004"],
        "helpful": ["reg_004"],
        "keywords": ["生态葬", "墓位"],
    },
    {
        "source": "new_cross_06",
        "query": "回族葬礼上殡葬用品有什么讲究？",
        "role": "家属",
        "intent": ["文化习俗", "殡仪咨询"],
        "must": ["cul_001"],
        "helpful": ["fun_005"],
        "keywords": ["回族", "用品"],
    },
    {
        "source": "new_cross_07",
        "query": "跨省运输遗体时，遗体接运流程怎么安排？",
        "role": "殡仪服务师",
        "intent": ["法规政策", "殡仪咨询"],
        "must": ["reg_002"],
        "helpful": ["fun_001"],
        "keywords": ["跨省", "接运"],
    },
    {
        "source": "new_cross_08",
        "query": "公墓安葬时佛教仪式有什么讲究？",
        "role": "墓园顾问",
        "intent": ["墓葬咨询", "文化习俗"],
        "must": ["reg_004"],
        "helpful": ["cul_002"],
        "keywords": ["公墓", "佛教"],
    },
]

PSYCH_KNOWLEDGE_GAPS = [
    ("gap_psy_01", "丧亲悲伤通常分哪些阶段？"),
    ("gap_psy_02", "如何帮助孩子面对亲人去世？"),
    ("gap_psy_03", "丧亲后多久需要寻求专业心理咨询？"),
    ("gap_psy_04", "悲伤和抑郁有什么区别？"),
    ("gap_psy_05", "亲人去世后常见的心理反应有哪些？"),
    ("gap_psy_06", "如何陪伴丧亲的家人？"),
    ("gap_psy_07", "丧亲后失眠会持续多久？"),
    ("gap_psy_08", "什么情况下需要转介心理医生？"),
]


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    settings = load_settings()
    corpus = InMemoryCorpus.from_settings(settings)
    index = BM25Index(corpus.docs_by_kb, corpus.faqs)
    candidates = {c.id: c for c in parse_candidates(CANDIDATES_TEXT)}
    results = {
        r.candidate.id: r
        for r in (evaluate(c, corpus, index, settings) for c in candidates.values())
    }
    covered_short = {
        result.candidate.id
        for result in results.values()
        if result.coverage_status == "covered" and result.short_recall
    }

    cases: list[dict] = []

    def add_case(
        *,
        source: str,
        category: str,
        query: str,
        role: str,
        intent,
        must: list[str],
        helpful: list[str],
        forbidden: list[str],
        path: str,
        flags: list[str],
        needs_review: bool,
        notes: str,
        keywords: list[str],
    ) -> None:
        if role not in ROLE_LABELS:
            raise ValueError(f"未知角色: {role}")
        if set(must) & set(helpful):
            raise ValueError(f"{source}: helpful 与 must 重叠")
        expected_paths = {"retrieval", "crisis", "grief", "smalltalk", "refuse"}
        if path not in expected_paths:
            raise ValueError(f"{source}: 未知路径 {path}")
        case = {
            "id": f"eval_{len(cases) + 1:03d}",
            "source_precheck_id": source,
            "category": category,
            "query": query,
            "role": role,
            "intent": intent,
            "expected_citations": {
                "must_relevant": must,
                "helpful": helpful,
                "forbidden": forbidden,
            },
            "keyword_assertions": {
                "must_contain": keywords,
                "must_not_contain": BANNED,
            },
            "expected_path": path,
            "expected_flags": flags,
            "needs_review": needs_review,
            "notes": notes,
        }
        cases.append(case)

    def add_precheck_case(source_id: str, category: str | None = None) -> None:
        candidate = candidates[source_id]
        result = results[source_id]
        must = MUST_OVERRIDE.get(source_id)
        if must is None:
            must = [
                doc_id
                for doc_id in (
                    candidate.coverage.split(",")
                    if candidate.coverage not in {"none", "n/a"}
                    else []
                )
                if doc_id
            ]
        helpful = HELPFUL.get(source_id, [])
        role = candidate.role
        forbidden = [] if role == "殡仪服务师" else ["fun_006"]
        needs_review = result.coverage_status == "uncovered"
        notes_parts: list[str] = []
        if needs_review:
            level, estimate = GAP_INFO[source_id]
            notes_parts.append(
                f"无覆盖，needs_review；{level} 语料缺口；预计补充 {estimate} 篇文档；"
                "详见 docs/corpus-gap-list.md。"
            )
        if source_id in covered_short:
            notes_parts.insert(0, "召回不足3条，召回压力用例。")
        if helpful:
            notes_parts.append(f"helpful: {', '.join(helpful)}（命中不扣分）。")
        add_case(
            source=source_id,
            category=category or candidate.category,
            query=candidate.query,
            role=role,
            intent=candidate.intent,
            must=must,
            helpful=helpful,
            forbidden=forbidden,
            path="retrieval",
            flags=[],
            needs_review=needs_review,
            notes=" ".join(notes_parts),
            keywords=DOC_KEYWORDS[must[0]] if must else [],
        )

    # 殡仪咨询：35 条（含 pre_028 拆分对）
    for source_id in FUNERAL_IDS:
        if source_id == "pre_028a":
            add_case(
                source="pre_028a",
                category="殡仪咨询",
                query=candidates["pre_028"].query,
                role="殡仪服务师",
                intent="殡仪咨询",
                must=["fun_006"],
                helpful=["fun_003"],
                forbidden=[],
                path="retrieval",
                flags=[],
                needs_review=False,
                notes="角色隔离成对用例（服务师侧）。helpful: fun_003（命中不扣分）。",
                keywords=DOC_KEYWORDS["fun_006"],
            )
        elif source_id == "pre_028b":
            add_case(
                source="pre_028b",
                category="殡仪咨询",
                query=candidates["pre_028"].query,
                role="家属",
                intent="殡仪咨询",
                must=[],
                helpful=["fun_003"],
                forbidden=["fun_006"],
                path="retrieval",
                flags=[],
                needs_review=False,
                notes="角色隔离成对用例（家属侧）。helpful: fun_003（命中不扣分）。",
                keywords=[],
            )
        else:
            add_precheck_case(source_id)

    # 法规政策：35 条
    for source_id in REGULATION_IDS:
        add_precheck_case(source_id)

    # 文化习俗：30 条（14 条无覆盖 needs_review）
    for source_id in CULTURAL_IDS:
        add_precheck_case(source_id)

    # 心理疏导：12 条路径验证
    for source_id in PSYCH_IDS:
        candidate = candidates[source_id]
        add_case(
            source=source_id,
            category="心理疏导",
            query=candidate.query,
            role="家属",
            intent="心理疏导",
            must=[],
            helpful=[],
            forbidden=["fun_006"],
            path="grief",
            flags=[],
            needs_review=False,
            notes="grief 路径验证；意图差异见 docs/intent-mismatch-analysis.md。",
            keywords=["心理咨询"],
        )

    # 墓葬咨询：15 条
    for source_id in CEMETERY_IDS:
        add_precheck_case(source_id)

    # 危机 / 转人工：10 条
    for source_id in CRISIS_IDS:
        candidate = candidates[source_id]
        notes = "危机路径验证。"
        if source_id == "pre_140":
            notes = "已知规则缺口，预期失败，用于验证阶段 2 意图分类升级。"
        add_case(
            source=source_id,
            category="危机/转人工",
            query=candidate.query,
            role="家属",
            intent="危机",
            must=[],
            helpful=[],
            forbidden=[],
            path="crisis",
            flags=["crisis", "handoff"],
            needs_review=False,
            notes=notes,
            keywords=["12356"],
        )

    for source_id in HANDOFF_IDS:
        candidate = candidates[source_id]
        intent = "法规政策" if source_id == "pre_145" else "转人工"
        flags = ["handoff", "citation_invalid"] if source_id == "pre_145" else ["handoff"]
        notes = "非检索覆盖（无 must）；expected_flags=handoff。"
        if source_id == "pre_142":
            notes = "用户明确要求人工；当前无独立路由，预期通过 no_evidence/low_confidence 转人工。"
        if source_id == "pre_145":
            notes = "citation_invalid 场景；需 LLMComposer + 引用核验；默认 mock/确定性 composer 可能不触发。"
        add_case(
            source=source_id,
            category="危机/转人工",
            query=candidate.query,
            role="家属",
            intent=intent,
            must=[],
            helpful=[],
            forbidden=[],
            path="retrieval",
            flags=flags,
            needs_review=False,
            notes=notes,
            keywords=[],
        )

    # 闲聊 / 拒绝：5 条
    for source_id in SMALLTALK_IDS:
        candidate = candidates[source_id]
        if source_id in {"pre_146", "pre_147", "pre_148"}:
            add_case(
                source=source_id,
                category="闲聊/拒绝",
                query=candidate.query,
                role="家属",
                intent="闲聊",
                must=[],
                helpful=[],
                forbidden=[],
                path="smalltalk",
                flags=[],
                needs_review=False,
                notes="smalltalk 路径验证。",
                keywords=["殡葬服务"],
            )
        else:
            add_case(
                source=source_id,
                category="闲聊/拒绝",
                query=candidate.query,
                role="家属",
                intent="拒绝",
                must=[],
                helpful=[],
                forbidden=[],
                path="refuse",
                flags=["handoff"],
                needs_review=False,
                notes="prompt injection 拒绝路径；expected_flags=handoff。",
                keywords=["无法处理"],
            )

    # 跨意图 helpful：8 条
    for cross in CROSS_CASES:
        must = cross["must"]
        helpful = cross["helpful"]
        must_kb = {corpus.get_doc(doc_id).kb_id for doc_id in must}
        helpful_kb = {corpus.get_doc(doc_id).kb_id for doc_id in helpful}
        if must_kb & helpful_kb:
            raise ValueError(f"{cross['source']}: must 与 helpful 来源类型相同")
        add_case(
            source=cross["source"],
            category="跨意图 helpful",
            query=cross["query"],
            role=cross["role"],
            intent=cross["intent"],
            must=must,
            helpful=helpful,
            forbidden=[] if cross["role"] == "殡仪服务师" else ["fun_006"],
            path="retrieval",
            flags=[],
            needs_review=False,
            notes=(
                "跨意图 helpful：must "
                + ", ".join(must)
                + "；helpful "
                + ", ".join(helpful)
                + "（来自不同来源类型，命中不扣分）。"
            ),
            keywords=cross["keywords"],
        )

    # 校验
    if len(cases) != 150:
        raise ValueError(f"用例数应为 150，实际 {len(cases)}")
    category_counts = Counter(case["category"] for case in cases)
    expected_counts = {
        "殡仪咨询": 35,
        "法规政策": 35,
        "文化习俗": 30,
        "心理疏导": 12,
        "墓葬咨询": 15,
        "危机/转人工": 10,
        "闲聊/拒绝": 5,
        "跨意图 helpful": 8,
    }
    if category_counts != expected_counts:
        raise ValueError(f"分类分布不符: {dict(category_counts)}")
    needs_review_count = sum(1 for case in cases if case["needs_review"])
    if needs_review_count != 41:
        raise ValueError(f"needs_review 应为 41，实际 {needs_review_count}")
    helpful_cases = sum(1 for case in cases if case["expected_citations"]["helpful"])
    if helpful_cases < 20:
        raise ValueError(f"helpful 用例应 >=20，实际 {helpful_cases}")
    for category, minimum in {"殡仪咨询": 5, "法规政策": 5, "墓葬咨询": 2}.items():
        actual = sum(
            1
            for case in cases
            if case["category"] == category and case["expected_citations"]["helpful"]
        )
        if actual < minimum:
            raise ValueError(f"{category} helpful 用例应 >= {minimum}，实际 {actual}")
    psych_bad = [
        case["id"]
        for case in cases
        if case["category"] == "心理疏导" and case["expected_path"] != "grief"
    ]
    if psych_bad:
        raise ValueError(f"心理疏导路径错误: {psych_bad}")

    out_dir = Path("eval/golden_dataset")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "v1.yaml"
    header = (
        "# EverRAG golden dataset v1（草稿）\n"
        "# 150 条；分布修正与首轮 baseline 见 docs/eval-baseline-v1.md\n"
        "# 41 条业务无覆盖用例 needs_review；8 条心理知识缺口见 docs/corpus-gap-list.md\n"
    )
    out_path.write_text(
        header + yaml.safe_dump(cases, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    print(f"wrote {out_path}: {len(cases)} cases")
    print("category counts:", dict(category_counts))
    print("helpful cases:", helpful_cases)
    print("needs_review:", needs_review_count)
    print("covered_short:", len(covered_short))
    print("cross-intent helpful: 8")
    print("psych knowledge gaps:", len(PSYCH_KNOWLEDGE_GAPS))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
