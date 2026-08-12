import logging
import re
import time
from dataclasses import dataclass
from typing import Any

from libs.shared.schemas import GuardrailDecision, GuardrailResult

logger = logging.getLogger(__name__)


@dataclass
class PIIEntity:
    type: str
    value: str
    start: int
    end: int
    confidence: float


class PIIDetector:
    PATTERNS: dict[str, re.Pattern] = {
        "EMAIL": re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'),
        "PHONE": re.compile(r'\b(?:\+?1[-.\s]?)?\(?([0-9]{3})\)?[-.\s]?([0-9]{3})[-.\s]?([0-9]{4})\b'),
        "AADHAAR": re.compile(r'\b\d{4}\s?\d{4}\s?\d{4}\b'),
        "PAN": re.compile(r'\b[A-Z]{5}[0-9]{4}[A-Z]{1}\b'),
        "CREDIT_CARD": re.compile(r'\b(?:\d{4}[-\s]?){3}\d{4}\b'),
        "IP_ADDRESS": re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b'),
    }

    def detect(self, text: str) -> list[PIIEntity]:
        entities = []
        for pii_type, pattern in self.PATTERNS.items():
            for match in pattern.finditer(text):
                entities.append(PIIEntity(
                    type=pii_type,
                    value=match.group(),
                    start=match.start(),
                    end=match.end(),
                    confidence=0.9,
                ))
        return entities

    def anonymize(self, text: str, entities: list[PIIEntity]) -> tuple[str, dict[str, str]]:
        mapping = {}
        result = text
        offset = 0
        for i, entity in enumerate(entities):
            token = f"<{entity.type}_{i}>"
            mapping[token] = entity.value
            start = entity.start + offset
            end = entity.end + offset
            result = result[:start] + token + result[end:]
            offset += len(token) - (entity.end - entity.start)
        return result, mapping

    def deanonymize(self, text: str, mapping: dict[str, str]) -> str:
        result = text
        for token, value in mapping.items():
            result = result.replace(token, value)
        return result


class PromptInjectionDetector:
    INJECTION_PATTERNS = [
        re.compile(r'ignore\s+(?:previous|all|above)\s+(?:instructions|prompts|rules)', re.IGNORECASE),
        re.compile(r'(?:system|developer|admin)\s*:?\s*(?:override|bypass|ignore)', re.IGNORECASE),
        re.compile(r'pretend\s+(?:to\s+be|you\s+are)\s+(?:a\s+)?(?:system|admin|developer)', re.IGNORECASE),
        re.compile(r'<\s*system\s*>.*?<\s*/\s*system\s*>', re.IGNORECASE | re.DOTALL),
        re.compile(r'\[INST\].*?\[/INST\]', re.IGNORECASE | re.DOTALL),
        re.compile(r'###\s*(?:System|Instruction|Prompt)\s*###', re.IGNORECASE),
        re.compile(r'(?:reveal|show|print|output)\s+(?:your|the)\s+(?:system|hidden|internal)\s+(?:prompt|instructions)', re.IGNORECASE),
        re.compile(r'DAN\s+(?:mode|prompt)', re.IGNORECASE),
        re.compile(r'(?:jailbreak|bypass|circumvent)\s+(?:safety|guardrail|filter)', re.IGNORECASE),
    ]

    def detect(self, text: str) -> tuple[bool, list[str]]:
        matches = []
        for pattern in self.INJECTION_PATTERNS:
            for match in pattern.finditer(text):
                matches.append(match.group()[:100])
        return len(matches) > 0, matches


class ToxicityDetector:
    TOXIC_PATTERNS = [
        re.compile(r'\b(?:hate|kill|murder|violence|abuse|harass|threat)\b', re.IGNORECASE),
        re.compile(r'\b(?:racist|sexist|homophobic|transphobic|bigot)\b', re.IGNORECASE),
    ]

    def detect(self, text: str) -> tuple[bool, float]:
        score = 0.0
        for pattern in self.TOXIC_PATTERNS:
            matches = len(pattern.findall(text))
            score += matches * 0.3
        return score > 0.5, min(score, 1.0)


class HallucinationDetector:
    def __init__(self):
        self.uncertainty_phrases = [
            "i don't know", "i'm not sure", "i cannot", "i'm unable",
            "as an ai", "i don't have", "i cannot access", "i cannot verify",
            "it's possible", "might be", "could be", "uncertain",
        ]

    def detect(self, response: str, context: str | None = None) -> tuple[bool, float]:
        response_lower = response.lower()
        uncertainty_count = sum(1 for phrase in self.uncertainty_phrases if phrase in response_lower)
        score = min(uncertainty_count * 0.15, 1.0)
        return score > 0.4, score


class SafeInferenceV3:
    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}
        self.pii_detector = PIIDetector()
        self.injection_detector = PromptInjectionDetector()
        self.toxicity_detector = ToxicityDetector()
        self.hallucination_detector = HallucinationDetector()
        self.max_prompt_length = self.config.get("max_prompt_length", 100000)
        self.max_response_length = self.config.get("max_response_length", 50000)
        self.enabled_checks = self.config.get("enabled_checks", [
            "pii", "injection", "toxicity", "length", "hallucination"
        ])

    async def pre_flight(self, prompt: str, context: dict[str, Any] | None = None) -> GuardrailResult:
        start_time = time.time()
        violations = []
        modified_prompt = prompt
        pii_mapping: dict[str, str] = {}

        if "length" in self.enabled_checks:
            if len(prompt) > self.max_prompt_length:
                violations.append(f"Prompt exceeds max length ({self.max_prompt_length})")

        if "pii" in self.enabled_checks:
            entities = self.pii_detector.detect(prompt)
            if entities:
                modified_prompt, pii_mapping = self.pii_detector.anonymize(prompt, entities)
                violations.append(f"PII detected and anonymized: {[e.type for e in entities]}")
                logger.warning(f"PII anonymized: {len(entities)} entities")

        if "injection" in self.enabled_checks:
            detected, matches = self.injection_detector.detect(prompt)
            if detected:
                violations.append(f"Prompt injection detected: {matches[:3]}")
                return GuardrailResult(
                    decision=GuardrailDecision.DENY,
                    reason="Prompt injection attempt detected",
                    latency_ms=(time.time() - start_time) * 1000,
                    metadata={"injection_matches": matches},
                )

        if "toxicity" in self.enabled_checks:
            detected, score = self.toxicity_detector.detect(prompt)
            if detected:
                violations.append(f"Toxic content detected (score: {score:.2f})")
                return GuardrailResult(
                    decision=GuardrailDecision.DENY,
                    reason="Toxic content in prompt",
                    latency_ms=(time.time() - start_time) * 1000,
                    metadata={"toxicity_score": score},
                )

        decision = GuardrailDecision.MODIFY if violations else GuardrailDecision.ALLOW
        return GuardrailResult(
            decision=decision,
            reason="; ".join(violations) if violations else "Pre-flight checks passed",
            modified_prompt=modified_prompt if modified_prompt != prompt else None,
            latency_ms=(time.time() - start_time) * 1000,
            metadata={"checks": self.enabled_checks, "pii_mapping": pii_mapping},
        )

    async def post_generation(
        self,
        response: str,
        prompt: str,
        context: dict[str, Any] | None = None,
    ) -> GuardrailResult:
        start_time = time.time()
        violations = []

        if "length" in self.enabled_checks:
            if len(response) > self.max_response_length:
                violations.append(f"Response exceeds max length ({self.max_response_length})")

        if "pii" in self.enabled_checks:
            # De-anonymize response before checking for PII leakage
            pii_mapping = context.get("pii_mapping", {}) if context else {}
            if pii_mapping:
                check_response = self.pii_detector.deanonymize(response, pii_mapping)
            else:
                check_response = response
            entities = self.pii_detector.detect(check_response)
            if entities:
                violations.append(f"PII leaked in response: {[e.type for e in entities]}")
                return GuardrailResult(
                    decision=GuardrailDecision.DENY,
                    reason="PII detected in model response",
                    latency_ms=(time.time() - start_time) * 1000,
                    metadata={"pii_types": [e.type for e in entities]},
                )

        if "hallucination" in self.enabled_checks:
            detected, score = self.hallucination_detector.detect(response, context.get("retrieved_context") if context else None)
            if detected:
                violations.append(f"Potential hallucination detected (score: {score:.2f})")

        if "toxicity" in self.enabled_checks:
            detected, score = self.toxicity_detector.detect(response)
            if detected:
                violations.append(f"Toxic content in response (score: {score:.2f})")
                return GuardrailResult(
                    decision=GuardrailDecision.DENY,
                    reason="Toxic content in model response",
                    latency_ms=(time.time() - start_time) * 1000,
                    metadata={"toxicity_score": score},
                )

        decision = GuardrailDecision.MODIFY if violations else GuardrailDecision.ALLOW
        return GuardrailResult(
            decision=decision,
            reason="; ".join(violations) if violations else "Post-generation checks passed",
            latency_ms=(time.time() - start_time) * 1000,
            metadata={"checks": self.enabled_checks},
        )


_guardrail: SafeInferenceV3 | None = None


def get_guardrail(config: dict[str, Any] | None = None) -> SafeInferenceV3:
    global _guardrail
    if _guardrail is None:
        _guardrail = SafeInferenceV3(config)
    return _guardrail