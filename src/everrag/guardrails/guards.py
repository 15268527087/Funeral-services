"""规则型护栏：PII、危机、Prompt 注入、输出合规。

阶段 1 以可解释的规则为主；阶段 2 可叠加分类器与 LLM Judge，规则仍作为高优先级兜底。
"""

from __future__ import annotations

import re

from everrag.config import GuardrailConfig
from everrag.schemas import Citation, InputGuardResult, OutputGuardResult, RiskFlag

_PII_LABELS = {
    "id_card": "[身份证号已脱敏]",
    "phone": "[手机号已脱敏]",
    "email": "[邮箱已脱敏]",
}


class InputGuard:
    def __init__(self, config: GuardrailConfig):
        self.crisis_keywords = config.crisis_keywords
        self.injection_patterns = [re.compile(p, re.IGNORECASE) for p in config.injection_patterns]
        self.pii_patterns = {
            name: (re.compile(pattern), _PII_LABELS.get(name, "[PII已脱敏]"))
            for name, pattern in config.pii_patterns.items()
        }

    def check(self, text: str) -> InputGuardResult:
        masked = text
        pii_masked = False
        for pattern, label in self.pii_patterns.values():
            new_masked, count = pattern.subn(label, masked)
            if count:
                masked = new_masked
                pii_masked = True

        matched_crisis = [kw for kw in self.crisis_keywords if kw in text]
        matched_injection = [p.pattern for p in self.injection_patterns if p.search(text)]
        return InputGuardResult(
            masked_text=masked,
            crisis=bool(matched_crisis),
            injection=bool(matched_injection),
            pii_masked=pii_masked,
            matched_crisis=matched_crisis,
            matched_injection=matched_injection,
        )


class OutputGuard:
    def __init__(self, config: GuardrailConfig):
        self.banned_patterns = [re.compile(p) for p in config.banned_output_patterns]

    def check(
        self,
        answer: str,
        citations: list[Citation],
        intent: str,
        needs_human: bool = False,
    ) -> OutputGuardResult:
        flags: list[RiskFlag] = []
        if len(answer.strip()) < 20 and not needs_human:
            flags.append(RiskFlag(code="ANSWER_TOO_SHORT", severity="medium", message="回答过短"))

        for pattern in self.banned_patterns:
            if pattern.search(answer):
                flags.append(
                    RiskFlag(
                        code="BANNED_OUTPUT",
                        severity="high",
                        message=f"回答包含禁止表述: {pattern.pattern}",
                    )
                )

        if intent in ("regulation", "mixed") and not citations:
            flags.append(
                RiskFlag(
                    code="MISSING_CITATION",
                    severity="high",
                    message="法规/混合意图回答缺少有效引用",
                )
            )

        if intent in ("cultural", "mixed") and not any(
            word in answer for word in ("当地", "确认", "咨询", "差异")
        ):
            flags.append(
                RiskFlag(
                    code="CULTURAL_DISCLAIMER_MISSING",
                    severity="medium",
                    message="文化习俗回答缺少与当地确认的提示",
                )
            )

        ok = not any(flag.severity in ("high", "critical") for flag in flags)
        revised = answer
        for pattern in self.banned_patterns:
            revised = pattern.sub("以官方规定为准", revised)
        if intent in ("regulation", "mixed") and not citations:
            revised += "\n\n补充说明：暂未核验到有效法规依据，建议咨询当地民政部门或殡仪馆。"
        if intent in ("cultural", "mixed") and "当地" not in revised:
            revised += "\n\n不同地区和家庭的做法存在差异，建议与当地殡仪馆或相关宗教人士确认。"
        return OutputGuardResult(ok=ok, flags=flags, revised_answer=revised)


class Guardrails:
    def __init__(self, config: GuardrailConfig):
        self.input = InputGuard(config)
        self.output = OutputGuard(config)

    def check_input(self, text: str) -> InputGuardResult:
        return self.input.check(text)

    def check_output(
        self,
        answer: str,
        citations: list[Citation],
        intent: str,
        needs_human: bool = False,
    ) -> OutputGuardResult:
        return self.output.check(answer, citations, intent, needs_human)
