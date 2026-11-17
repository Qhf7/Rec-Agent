"""Replaceable Jev SystemOne HTTP adapter with a safe dry-run mode."""

from __future__ import annotations

import json
import os
import re
import ssl
import urllib.error
import urllib.request
from typing import Any


DEFAULT_ENDPOINT = "https://api.modelgo.ai/v1/systemone"
DEFAULT_MODEL = "jev-1.14.0"
DEFAULT_SCORE_NAME = "jev-compliance-v1"
DECISIONS = {"expose", "rewrite", "human_review", "block"}
RISK_TYPES = {
    "compliant",
    "absolute_claim",
    "efficacy_or_medical_claim",
    "price_misleading",
    "missing_ai_disclosure",
    "off_topic",
}
REQUIRED_FIELDS = {
    "reason_id",
    "decision",
    "risk_type",
    "evidence",
    "judge_score",
    "escalated",
    "model_version",
    "score_name",
}


class JevConfigurationError(RuntimeError):
    pass


class JevResponseError(RuntimeError):
    pass


def build_ssl_context() -> ssl.SSLContext:
    """Build a verifying TLS context using certifi when host CA paths are missing."""
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def validate_decision(result: dict) -> dict:
    missing = REQUIRED_FIELDS - set(result)
    if missing:
        raise ValueError(f"decision missing fields: {sorted(missing)}")
    if result["decision"] not in DECISIONS:
        raise ValueError(f"unsupported decision: {result['decision']}")
    if result["risk_type"] not in RISK_TYPES:
        raise ValueError(f"unsupported risk_type: {result['risk_type']}")
    if not isinstance(result["evidence"], list) or not result["evidence"]:
        raise ValueError("evidence must be a non-empty list")
    score = result["judge_score"]
    if not isinstance(score, (int, float)) or not 0 <= float(score) <= 1:
        raise ValueError("judge_score must be in [0, 1]")
    if not isinstance(result["escalated"], bool):
        raise ValueError("escalated must be boolean")
    return result


def build_evidence_from_fact_bundle(fact_bundle: dict) -> list[str]:
    evidence: list[str] = []
    state = fact_bundle.get("verification_state")
    coverage = fact_bundle.get("coverage") or {}
    if state and state != "verified":
        evidence.append(f"verification_state={state}")
    if coverage.get("missing"):
        evidence.append(f"fact_bundle.coverage.missing={coverage['missing']}")

    for hit in fact_bundle.get("lexicon_hits") or []:
        evidence.append(
            f"lexicon.{hit.get('risk_type')}:{hit.get('term')}"
            f"（canonical={hit.get('canonical_term')}）"
        )

    item = fact_bundle.get("item") or {}
    if item.get("functions"):
        evidence.append(f"fact_bundle.item.functions={item['functions']}")
    if item.get("suitable_scenes"):
        evidence.append(f"fact_bundle.item.suitable_scenes={item['suitable_scenes']}")

    promo = fact_bundle.get("promo") or {}
    if promo:
        evidence.append(
            f"fact_bundle.promo[{promo.get('promo_id', 'unknown')}].applicable={promo.get('applicable')}"
        )

    disclosure = fact_bundle.get("disclosure") or {}
    if disclosure:
        evidence.append(f"fact_bundle.ai_disclosure.flag={disclosure.get('flag')}")

    if not evidence:
        evidence.append("fact_bundle.reason_id 已提供，但没有更多可引用字段")
    return evidence


class JevAdapter:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        endpoint: str = DEFAULT_ENDPOINT,
        model: str = DEFAULT_MODEL,
        score_name: str = DEFAULT_SCORE_NAME,
        timeout: float = 30.0,
        dry_run: bool = True,
    ) -> None:
        self.api_key = api_key if api_key is not None else os.getenv("MODELGO_API_KEY")
        self.endpoint = endpoint
        self.model = model
        self.score_name = score_name
        self.timeout = timeout
        self.dry_run = dry_run

    def build_payload(self, fact_bundle: dict) -> dict:
        state = json.dumps(fact_bundle, ensure_ascii=False, separators=(",", ":"))
        return {
            "model": self.model,
            "state": state,
            "questions": {
                "decision": {
                    "type": "choice",
                    "instructions": "请选择这条推荐理由的最终曝光处置结论。",
                    "criteria": {
                        "expose": "事实成立、无风险且可以直接曝光。",
                        "rewrite": "存在可机械修复的问题，改写后可以曝光。",
                        "human_review": "关键字段缺失、证据冲突或置信度不足，需要人工审核。",
                        "block": "存在无法安全修复的事实性、功效性或价格合规风险，禁止曝光。",
                    },
                },
                "risk_type": {
                    "type": "choice",
                    "instructions": "请选择驱动处置结论的主要风险类型。",
                    "criteria": {
                        "compliant": "事实成立、切题且没有需要处置的风险。",
                        "absolute_claim": "存在绝对化、最高级或无法证明的比较表达。",
                        "efficacy_or_medical_claim": "功效或医疗宣称没有商品属性、资质或允许清单支持。",
                        "price_misleading": "价格、折扣、满减或赠品表达与促销规则不一致。",
                        "missing_ai_disclosure": "按业务规则需要披露 AI 生成，但披露标记缺失。",
                        "off_topic": "理由与商品属性或用户语境不相关。",
                    },
                },
                "judge_score": {
                    "type": "score",
                    "instructions": "请评估这条推荐理由的不安全概率，分数越高表示风险越高。",
                    "criteria": [
                        "低风险，概率接近 0。",
                        "中风险，概率约为 0.5。",
                        "高风险，概率接近 1。",
                    ],
                },
            },
        }

    def judge(self, fact_bundle: dict) -> dict:
        payload = self.build_payload(fact_bundle)
        if self.dry_run:
            return {"dry_run": True, "request": payload}
        if not self.api_key:
            raise JevConfigurationError("MODELGO_API_KEY is required when dry_run=False")

        request = urllib.request.Request(
            self.endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                request, timeout=self.timeout, context=build_ssl_context()
            ) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")
            raise JevResponseError(f"HTTP {exc.code}: {body[:1000]}") from exc
        except urllib.error.URLError as exc:
            raise JevResponseError(f"Jev request failed: {exc}") from exc
        return self.parse_response(raw, fact_bundle)

    def parse_response(self, raw: str | bytes | dict, fact_bundle: dict) -> dict:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        parsed: Any = raw if isinstance(raw, dict) else json.loads(raw)
        if isinstance(parsed, dict) and isinstance(parsed.get("answers"), dict):
            return self._parse_systemone_response(parsed, fact_bundle)

        result = _find_decision_object(parsed)
        if result is None:
            raise JevResponseError("response did not contain a valid decision object")
        result.setdefault("reason_id", fact_bundle.get("reason_id"))
        result.setdefault("model_version", self.model)
        result.setdefault("score_name", self.score_name)
        return validate_decision(result)

    def _parse_systemone_response(self, payload: dict, fact_bundle: dict) -> dict:
        answers = payload["answers"]
        try:
            decision = answers["decision"]["choice"]
            risk_type = answers["risk_type"]["choice"]
            judge_score = _normalize_score(answers["judge_score"])
        except (KeyError, TypeError) as exc:
            raise JevResponseError("SystemOne response missing decision/risk_type/judge_score") from exc

        confidence_values = []
        for key in ("decision", "risk_type", "judge_score"):
            value = answers.get(key) or {}
            if isinstance(value.get("confidence"), (int, float)):
                confidence_values.append(float(value["confidence"]))
        confidence = min(confidence_values) if confidence_values else 1.0
        state = fact_bundle.get("verification_state", "verified")
        escalated = state in {"unverifiable", "conflict"} or confidence < 0.7 or decision == "human_review"
        evidence = build_evidence_from_fact_bundle(fact_bundle)

        if state in {"unverifiable", "conflict"}:
            decision = "human_review"
            escalated = True
            evidence.append("未验证或冲突事实必须进入人工审核")
            if risk_type == "compliant":
                risk_type = _fallback_risk_for_missing_fields(fact_bundle)

        rule_features = fact_bundle.get("rule_features") or {}
        disclosure = fact_bundle.get("disclosure") or {}
        unsupported_efficacy = rule_features.get("unsupported_efficacy_terms") or []
        supported_efficacy = rule_features.get("supported_efficacy_terms") or []
        if (
            state == "verified"
            and disclosure.get("required", True)
            and disclosure.get("flag") is True
            and not unsupported_efficacy
            and "absolute_claim_terms" in rule_features
            and "price_mismatch" in rule_features
            and "topic_mismatch" in rule_features
            and not rule_features.get("absolute_claim_terms")
            and not rule_features.get("price_mismatch")
            and not rule_features.get("topic_mismatch")
            and risk_type in {"compliant", "efficacy_or_medical_claim", "off_topic"}
        ):
            decision = "expose"
            risk_type = "compliant"
            evidence.append("规则特征未发现硬性风险，商品事实和披露状态完整")
        elif state == "verified" and unsupported_efficacy:
            decision = "block"
            risk_type = "efficacy_or_medical_claim"
            evidence.append(f"规则核验发现未被商品属性支持的功效：{unsupported_efficacy}")
        elif (
            state == "verified"
            and risk_type == "efficacy_or_medical_claim"
            and supported_efficacy
            and not unsupported_efficacy
            and not any(hit.get("risk_type") in {"absolute_claim", "price_misleading"} for hit in fact_bundle.get("lexicon_hits", []))
        ):
            decision = "expose"
            risk_type = "compliant"
            evidence.append(f"规则核验确认商品属性支持功效：{supported_efficacy}")
        elif state == "verified" and decision == "block" and risk_type in {"absolute_claim", "off_topic"}:
            decision = "rewrite"
            evidence.append("该风险可以通过删除或重写推荐理由修复")

        if (
            state == "verified"
            and risk_type not in {"efficacy_or_medical_claim", "price_misleading"}
            and disclosure.get("required", True)
            and disclosure.get("flag") is False
        ):
            decision = "rewrite"
            risk_type = "missing_ai_disclosure"
            evidence.append("fact_bundle.ai_disclosure.flag=false，需要补充 AI 披露")

        result = {
            "reason_id": fact_bundle.get("reason_id"),
            "decision": decision,
            "risk_type": risk_type,
            "evidence": evidence,
            "judge_score": judge_score,
            "escalated": escalated,
            "model_version": payload.get("model", self.model),
            "score_name": self.score_name,
        }
        return validate_decision(result)


def _normalize_score(answer: dict) -> float:
    raw = answer.get("score")
    if not isinstance(raw, (int, float)):
        raise JevResponseError("SystemOne judge_score answer has no numeric score")
    probabilities = answer.get("probabilities") or {}
    try:
        max_score = max(int(key) for key in probabilities) if probabilities else 1
    except (TypeError, ValueError):
        max_score = 1
    if max_score > 1:
        raw = float(raw) / max_score
    return round(max(0.0, min(1.0, float(raw))), 4)


def _fallback_risk_for_missing_fields(fact_bundle: dict) -> str:
    missing = set((fact_bundle.get("coverage") or {}).get("missing") or [])
    if "functions" in missing:
        return "efficacy_or_medical_claim"
    if "price" in missing:
        return "price_misleading"
    return "off_topic"


def _find_decision_object(value: Any) -> dict | None:
    if isinstance(value, dict):
        if REQUIRED_FIELDS - {"model_version", "score_name"} <= set(value):
            return value
        for child in value.values():
            found = _find_decision_object(child)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _find_decision_object(child)
            if found is not None:
                return found
    elif isinstance(value, str):
        text = value.strip()
        fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.S)
        candidate = fenced.group(1) if fenced else text
        if candidate.startswith("{") and candidate.endswith("}"):
            try:
                return _find_decision_object(json.loads(candidate))
            except json.JSONDecodeError:
                return None
    return None
