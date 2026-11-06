"""阶段 1 评测入口：兼容原有 smoke JSONL 与 golden YAML。

用法：
    python -m eval.run_eval
    python -m eval.run_eval --dataset eval/datasets/smoke.jsonl
    python -m eval.run_eval --dataset eval/golden_dataset/v1.yaml \
        --report eval/reports/golden-v1.json
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import yaml

from everrag.container import AppContainer
from everrag.schemas import ChatRequest

ROLE_MAP = {
    "家属": "family",
    "殡仪服务师": "funeral_staff",
    "墓园顾问": "cemetery_advisor",
    "心理咨询师": "counselor",
    "客户经理": "account_manager",
}

INTENT_MAP = {
    "殡仪咨询": "funeral",
    "墓葬咨询": "cemetery",
    "法规政策": "regulation",
    "心理疏导": "grief",
    "文化习俗": "cultural",
    "闲聊": "smalltalk",
    "危机": "unknown",
    "转人工": "unknown",
    "拒绝": "unknown",
}

# FAQ 快速路径的引用 ID 映射到等价知识库文档；不改变三态语义。
FAQ_EQUIVALENTS = {
    "faq_001": "fun_001",
    "faq_002": "fun_002",
    "faq_003": "reg_003",
    "faq_005": "reg_004",
}

# faq_004 问的是「跨省运骨灰」，现有 reg_002 是「跨省运输遗体」：
# 对象（骨灰 vs 遗体）和材料（火化证明 vs 防腐/车辆资质）不一致，
# 因此不映射到 reg_002，避免评测过度归因；显式记录为无完全对应文档。
FAQ_NO_EQUIVALENT = {
    "faq_004": "无完全对应文档；reg_002 仅主题相近（遗体 vs 骨灰）",
}


def load_cases(path: Path) -> list[dict]:
    if path.suffix.lower() in {".yaml", ".yml"}:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data = data.get("cases", [])
        if not isinstance(data, list):
            raise TypeError(f"{path} 必须是 YAML 列表或包含 cases 列表的对象")
        return data

    cases: list[dict] = []
    with path.open("r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                cases.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{lineno} JSON 解析失败: {exc}") from exc
    return cases


# ---------------- 原有 smoke JSONL 逻辑 ----------------

def check_case(container: AppContainer, case: dict) -> tuple[bool, list[str]]:
    result = container.orchestrator.run(
        ChatRequest(
            message=case["query"],
            user_role=case.get("user_role", "family"),
            user_profile=case.get("profile", {}),
        )
    )
    answer = result["answer"]
    failures: list[str] = []

    if case.get("expect_intent") and result["intent"] != case["expect_intent"]:
        failures.append(f"intent {result['intent']} != {case['expect_intent']}")
    for text in case.get("must_include", []):
        if text not in answer:
            failures.append(f"缺少关键词: {text}")
    for text in case.get("must_not_include", []):
        if text in answer:
            failures.append(f"出现禁止词: {text}")
    if case.get("expect_crisis") and result["handoff_reason"] != "crisis":
        failures.append(f"危机未触发: {result['handoff_reason']}")
    if bool(case.get("expect_handoff")) != bool(result["needs_human"]):
        failures.append(f"handoff {result['needs_human']} != {case.get('expect_handoff')}")
    if case.get("need_citation") and not result["citations"]:
        failures.append("缺少引用")

    for citation in result["citations"]:
        if citation.doc_id.startswith("reg_"):
            doc = container.corpus.get_doc(citation.doc_id)
            if doc is None:
                failures.append(f"引用不存在: {citation.doc_id}")
            elif not doc.is_effective():
                failures.append(f"引用已过期: {citation.doc_id}")

    return not failures, failures


def run_legacy(
    container: AppContainer,
    cases: list[dict],
    dataset: Path,
    report_path: Path,
    min_pass_rate: float,
) -> int:
    rows: list[dict] = []
    passed = 0

    for case in cases:
        ok, failures = check_case(container, case)
        passed += int(ok)
        rows.append({"id": case.get("id", ""), "query": case["query"], "ok": ok, "failures": failures})
        mark = "PASS" if ok else "FAIL"
        print(f"[{mark}] {case.get('id', '')} {case['query']}")
        for failure in failures:
            print(f"       - {failure}")

    total = len(cases)
    pass_rate = passed / total if total else 0.0
    report = {
        "dataset": str(dataset),
        "total": total,
        "passed": passed,
        "pass_rate": round(pass_rate, 4),
        "cases": rows,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n{passed}/{total} passed, pass_rate={pass_rate:.2%}, report={report_path}")
    return 0 if pass_rate >= min_pass_rate else 1


# ---------------- Golden 三态 YAML 逻辑 ----------------

def expected_runtime(intent) -> str:
    if isinstance(intent, (list, tuple)):
        return "mixed"
    if "+" in str(intent):
        return "mixed"
    return INTENT_MAP.get(str(intent), "unknown")


def actual_path(result: dict) -> str:
    if result.get("handoff_reason") == "crisis":
        return "crisis"
    if result.get("handoff_reason") == "prompt_injection":
        return "refuse"
    if result.get("intent") == "grief" or any(
        event.get("stage") == "grief_support" for event in result.get("events", [])
    ):
        return "grief"
    if result.get("intent") == "smalltalk" or any(
        event.get("stage") == "smalltalk" for event in result.get("events", [])
    ):
        return "smalltalk"
    return "retrieval"


def actual_flags(result: dict) -> set[str]:
    flags: set[str] = set()
    if result.get("handoff_reason") == "crisis":
        flags.add("crisis")
    if result.get("handoff_reason") == "prompt_injection":
        flags.add("injection")
    if result.get("needs_human"):
        flags.add("handoff")
    if result.get("citation_invalid"):
        flags.add("citation_invalid")
    return flags


def expanded_citations(result: dict) -> tuple[set[str], set[str]]:
    actual = {citation.doc_id for citation in result.get("citations", [])}
    expanded = set(actual)
    for citation_id in actual:
        equivalent = FAQ_EQUIVALENTS.get(citation_id)
        if equivalent:
            expanded.add(equivalent)
    return actual, expanded


def check_golden_case(container: AppContainer, case: dict) -> dict:
    role = ROLE_MAP[case["role"]]
    result = container.orchestrator.run(
        ChatRequest(
            message=case["query"],
            user_role=role,
            user_profile=case.get("profile", {}),
        )
    )
    answer = result["answer"]
    failures: list[str] = []

    expected_intent = expected_runtime(case["intent"])
    if result["intent"] != expected_intent:
        failures.append(f"intent {result['intent']} != {expected_intent}")
    path = actual_path(result)
    if path != case["expected_path"]:
        failures.append(f"path {path} != {case['expected_path']}")

    flags = actual_flags(result)
    for flag in case.get("expected_flags", []):
        if flag not in flags:
            failures.append(f"flag {flag} missing (actual={sorted(flags)})")

    actual_ids, expanded = expanded_citations(result)
    citations = case["expected_citations"]
    must = citations.get("must_relevant", [])
    helpful = citations.get("helpful", [])
    forbidden = citations.get("forbidden", [])

    must_hits = [doc_id for doc_id in must if doc_id in expanded]
    must_ok = all(doc_id in expanded for doc_id in must)
    if not must_ok:
        missing = sorted(set(must) - expanded)
        failures.append(f"must missing: {missing}")

    helpful_hits = [doc_id for doc_id in helpful if doc_id in expanded]
    forbidden_hits = sorted(set(forbidden) & (expanded | actual_ids))
    if forbidden_hits:
        failures.append(f"forbidden cited: {forbidden_hits}")

    assertions = case.get("keyword_assertions", {})
    for text in assertions.get("must_contain", []):
        if text not in answer:
            failures.append(f"missing keyword: {text}")
    for text in assertions.get("must_not_contain", []):
        if text in answer:
            failures.append(f"forbidden keyword: {text}")

    return {
        "id": case["id"],
        "source_precheck_id": case.get("source_precheck_id", ""),
        "category": case["category"],
        "query": case["query"],
        "role": case["role"],
        "intent": case["intent"],
        "ok": not failures,
        "failures": failures,
        "needs_review": bool(case.get("needs_review", False)),
        "recall_pressure": "召回压力用例" in case.get("notes", ""),
        "actual_intent": result["intent"],
        "actual_path": path,
        "actual_flags": sorted(flags),
        "citation_ids": sorted(actual_ids),
        "must_total": len(must),
        "must_hit": len(must_hits),
        "must_ok": must_ok,
        "helpful_total": len(helpful),
        "helpful_hit": bool(helpful_hits),
        "helpful_hits": helpful_hits,
        "forbidden_total": len(forbidden),
        "forbidden_hits": forbidden_hits,
    }


def _rate(passed: int, total: int) -> float:
    return passed / total if total else 0.0


def run_golden(
    container: AppContainer,
    cases: list[dict],
    dataset: Path,
    report_path: Path,
    min_pass_rate: float,
) -> int:
    rows = [check_golden_case(container, case) for case in cases]
    evaluated = [row for row in rows if not row["needs_review"]]
    skipped = [row for row in rows if row["needs_review"]]
    passed = sum(1 for row in evaluated if row["ok"])
    pass_rate = _rate(passed, len(evaluated))

    for row in rows:
        mark = "SKIP" if row["needs_review"] else ("PASS" if row["ok"] else "FAIL")
        print(f"[{mark}] {row['id']} [{row['category']}] {row['query']}")
        if not row["needs_review"]:
            for failure in row["failures"]:
                print(f"       - {failure}")

    # 按 category 分组；needs_review 不计入通过率分母
    groups: dict[str, dict] = {}
    by_category: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_category[row["category"]].append(row)
    for category, group_rows in by_category.items():
        group_eval = [row for row in group_rows if not row["needs_review"]]
        group_passed = sum(1 for row in group_eval if row["ok"])
        recall = [row for row in group_eval if row["recall_pressure"]]
        groups[category] = {
            "total": len(group_rows),
            "evaluated": len(group_eval),
            "passed": group_passed,
            "pass_rate": round(_rate(group_passed, len(group_eval)), 4),
            "needs_review": len(group_rows) - len(group_eval),
            "must_cases": sum(1 for row in group_eval if row["must_total"]),
            "must_hits": sum(1 for row in group_eval if row["must_total"] and row["must_ok"]),
            "helpful_cases": sum(1 for row in group_eval if row["helpful_total"]),
            "helpful_hits": sum(1 for row in group_eval if row["helpful_total"] and row["helpful_hit"]),
            "forbidden_violations": sum(
                1 for row in group_eval if row["forbidden_hits"]
            ),
            "recall_pressure_total": len(recall),
            "recall_pressure_passed": sum(1 for row in recall if row["ok"]),
            "recall_pressure_pass_rate": round(
                _rate(sum(1 for row in recall if row["ok"]), len(recall)), 4
            ),
        }

    must_cases = [row for row in evaluated if row["must_total"]]
    helpful_cases = [row for row in evaluated if row["helpful_total"]]
    forbidden_cases = [row for row in evaluated if row["forbidden_total"]]
    recall_rows = [row for row in evaluated if row["recall_pressure"]]
    three_state = {
        "must_cases": len(must_cases),
        "must_case_hits": sum(1 for row in must_cases if row["must_ok"]),
        "must_doc_total": sum(row["must_total"] for row in must_cases),
        "must_doc_hits": sum(row["must_hit"] for row in must_cases),
        "helpful_cases": len(helpful_cases),
        "helpful_hits": sum(1 for row in helpful_cases if row["helpful_hit"]),
        "forbidden_cases": len(forbidden_cases),
        "forbidden_violations": sum(1 for row in forbidden_cases if row["forbidden_hits"]),
    }
    recall_pressure = {
        "total": len(recall_rows),
        "passed": sum(1 for row in recall_rows if row["ok"]),
        "pass_rate": round(_rate(sum(1 for row in recall_rows if row["ok"]), len(recall_rows)), 4),
    }
    top_failures = sorted(
        [row for row in evaluated if not row["ok"]],
        key=lambda row: (-len(row["failures"]), row["id"]),
    )[:10]

    print("\n=== Golden eval summary ===")
    print(
        f"total={len(rows)} evaluated={len(evaluated)} needs_review={len(skipped)} "
        f"passed={passed} pass_rate={pass_rate:.2%}"
    )
    print("\nBy category:")
    for category in (
        "殡仪咨询",
        "法规政策",
        "文化习俗",
        "心理疏导",
        "墓葬咨询",
        "危机/转人工",
        "闲聊/拒绝",
        "跨意图 helpful",
    ):
        group = groups.get(category)
        if group is None:
            continue
        print(
            f"  {category}: {group['passed']}/{group['evaluated']} "
            f"pass_rate={group['pass_rate']:.2%}, needs_review={group['needs_review']}, "
            f"recall_pressure={group['recall_pressure_passed']}/{group['recall_pressure_total']}"
        )
    print(
        f"\nThree-state: must cases {three_state['must_case_hits']}/{three_state['must_cases']}, "
        f"must docs {three_state['must_doc_hits']}/{three_state['must_doc_total']}, "
        f"helpful cases {three_state['helpful_hits']}/{three_state['helpful_cases']}, "
        f"forbidden violations {three_state['forbidden_violations']}/{three_state['forbidden_cases']}"
    )
    print(
        f"Recall pressure: {recall_pressure['passed']}/{recall_pressure['total']} "
        f"pass_rate={recall_pressure['pass_rate']:.2%}"
    )
    print("\nTop failures:")
    for row in top_failures:
        print(f"  {row['id']} [{row['category']}] {row['query']}")
        print(f"    failures: {row['failures']}")

    report = {
        "dataset": str(dataset),
        "mode": "golden",
        "total": len(rows),
        "evaluated": len(evaluated),
        "passed": passed,
        "pass_rate": round(pass_rate, 4),
        "needs_review": len(skipped),
        "groups": groups,
        "three_state": three_state,
        "recall_pressure": recall_pressure,
        "top_failures": [
            {
                "id": row["id"],
                "category": row["category"],
                "query": row["query"],
                "failures": row["failures"],
            }
            for row in top_failures
        ],
        "cases": rows,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nreport={report_path}")
    return 0 if pass_rate >= min_pass_rate else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="eval/datasets/smoke.jsonl")
    parser.add_argument("--report", default="eval/reports/latest.json")
    parser.add_argument("--min-pass-rate", type=float, default=0.85)
    args = parser.parse_args()

    dataset = Path(args.dataset)
    cases = load_cases(dataset)
    is_golden = bool(cases) and (
        "expected_citations" in cases[0] or "category" in cases[0]
    )
    container = AppContainer()
    report_path = Path(args.report)
    if is_golden:
        return run_golden(container, cases, dataset, report_path, args.min_pass_rate)
    return run_legacy(container, cases, dataset, report_path, args.min_pass_rate)


if __name__ == "__main__":
    raise SystemExit(main())
