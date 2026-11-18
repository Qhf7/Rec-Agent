"""Structured Jev questions, input allow-list and response compatibility."""

from __future__ import annotations

from typing import Any, Mapping


JEV_QUESTION_SCHEMA_VERSION = "jev-questions-v1"
JEV_INPUT_SCHEMA_VERSION = "jev-input-v1"

_ALLOWED_EVIDENCE_PREFIXES = (
    "users.",
    "items.",
    "city_climate.",
    "user_context.",
    "time-context",
)
_FORBIDDEN_KEY_PARTS = (
    "history",
    "ctr",
    "click",
    "order",
    "refund",
    "complaint",
    "rank",
    "sorting",
    "search",
    "cart",
    "device",
    "feedback",
    "future",
)
_SCENE_FIELDS = {
    "city",
    "city_tier",
    "climate_zone",
    "life_stage",
    "tags",
    "active_hours",
}
_ITEM_FIELDS = {
    "item_id",
    "title",
    "brand",
    "category_l1",
    "category_l2",
    "category_l3",
    "functions",
    "material",
    "spec",
    "suit_audience",
    "suit_season",
    "efficacy_claims_allowed",
    "qualifications",
    "price_cents",
    "original_price_cents",
    "promo_tags",
    "promo_rule_ids",
    "stock",
    "regulated_category",
    "sensitive_category",
    "ad_law_notes",
}
_PROMO_FIELDS = {
    "promo_id",
    "type",
    "title",
    "applicable",
    "threshold_cents",
    "discount_cents",
    "discount_percent",
    "discount_rate",
    "gift",
    "gift_item",
    "start",
    "end",
    "fine_print",
}


def build_jev_questions() -> dict[str, dict[str, Any]]:
    return {
        "q1_identity": {
            "type": "choice",
            "instructions": "确认 reason_id、item_id、版本和事实包是否一致且可追溯。",
            "choices": ["valid", "invalid", "unverifiable"],
        },
        "q2_fact_support": {
            "type": "choice_with_evidence",
            "instructions": "逐句判断曝光理由是否由商品或场景事实直接支持。",
            "choices": ["supported", "partial", "unsupported", "unverifiable"],
        },
        "q3_expression_risk": {
            "type": "choice_with_risk_type",
            "instructions": "判断绝对化、功效/医疗、价格误导、披露缺失或跑题等表达风险。",
            "choices": ["clean", "rewriteable", "blocking"],
        },
        "q4_commercial_accuracy": {
            "type": "choice_with_evidence",
            "instructions": "核对理由中的价格、折扣、满减、赠品和有效期是否与快照一致。",
            "choices": ["verified", "mismatch", "not_mentioned", "unverifiable"],
        },
        "q5_context_relevance": {
            "type": "choice_with_evidence",
            "instructions": "判断最小用户场景摘要与商品事实是否相关。",
            "choices": ["relevant", "off_topic", "unverifiable"],
        },
        "q6_safety_gate": {
            "type": "choice_with_escalation",
            "instructions": "处理缺字段、证据冲突、敏感类目和低置信度情况。",
            "choices": ["pass", "human_review", "fail"],
        },
        "q7_final_decision": {
            "type": "structured_decision",
            "instructions": "综合前六问输出最终处置、风险类型、分数、置信度和证据。",
            "choices": ["expose", "rewrite", "human_review", "block"],
            "risk_types": [
                "compliant",
                "absolute_claim",
                "efficacy_or_medical_claim",
                "price_misleading",
                "missing_ai_disclosure",
                "off_topic",
            ],
            "required_fields": ["choice", "risk_type", "score", "confidence", "evidence", "escalated"],
        },
    }


def _copy_allowed(source: Mapping[str, Any], allowed: set[str]) -> dict[str, Any]:
    return {key: source[key] for key in allowed if key in source}


def build_jev_input(fact_bundle: Mapping[str, Any]) -> dict[str, Any]:
    item = fact_bundle.get("item") or {}
    promo = fact_bundle.get("promo") or {}
    user_context = fact_bundle.get("user_context") or {}
    candidate = {
        "reason_id": fact_bundle.get("reason_id"),
        "user_id": fact_bundle.get("user_id"),
        "item_id": fact_bundle.get("item_id"),
        "exposure_reason": fact_bundle.get("exposure_reason", ""),
        "generated_reason": fact_bundle.get("generated_reason", ""),
        "evidence_fields": fact_bundle.get("evidence_fields") or [],
    }
    payload = {
        "input_schema_version": JEV_INPUT_SCHEMA_VERSION,
        "question_schema_version": JEV_QUESTION_SCHEMA_VERSION,
        "candidate": candidate,
        "facts": {
            "item": _copy_allowed(item, _ITEM_FIELDS),
            "promo": _copy_allowed(promo, _PROMO_FIELDS),
            "scene": _copy_allowed(user_context, _SCENE_FIELDS),
            "lexicon_hits": fact_bundle.get("lexicon_hits") or [],
            "coverage": fact_bundle.get("coverage") or {},
            "verification_state": fact_bundle.get("verification_state"),
            "rule_features": fact_bundle.get("rule_features") or {},
            "disclosure": fact_bundle.get("disclosure") or {},
            "provenance": fact_bundle.get("provenance") or {},
        },
        "trace": {
            "reason_id": fact_bundle.get("reason_id"),
            "item_id": fact_bundle.get("item_id"),
            "user_id": fact_bundle.get("user_id"),
            "data_version": fact_bundle.get("data_version"),
            "agent_version": fact_bundle.get("agent_version", "rec-agent-v2"),
            "snapshot_at": fact_bundle.get("snapshot_at"),
        },
        "questions": build_jev_questions(),
    }
    return validate_jev_input(payload)


def _walk_keys(value: Any, path: str = "$"):
    if isinstance(value, Mapping):
        for key, child in value.items():
            yield str(key), f"{path}.{key}"
            yield from _walk_keys(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk_keys(child, f"{path}[{index}]")


def validate_jev_input(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("input_schema_version") != JEV_INPUT_SCHEMA_VERSION:
        raise ValueError("unsupported Jev input schema version")
    if payload.get("question_schema_version") != JEV_QUESTION_SCHEMA_VERSION:
        raise ValueError("unsupported Jev question schema version")
    candidate = payload.get("candidate")
    if not isinstance(candidate, Mapping):
        raise ValueError("candidate is required")
    for field in ("reason_id", "item_id", "exposure_reason", "generated_reason"):
        if not candidate.get(field):
            raise ValueError(f"candidate requires {field}")
    if candidate["exposure_reason"] != candidate["generated_reason"]:
        raise ValueError("generated_reason must equal exposure_reason")
    if not str(candidate["item_id"]).startswith("i_"):
        raise ValueError("candidate item_id must be canonical")
    data_version = (payload.get("trace") or {}).get("data_version")
    if not data_version:
        raise ValueError("data_version is required")
    for key, path in _walk_keys(payload):
        lowered = key.casefold()
        if any(part in lowered for part in _FORBIDDEN_KEY_PARTS):
            raise ValueError(f"forbidden Jev input field: {path}")
    for field in candidate.get("evidence_fields") or []:
        field = str(field)
        valid = any(field.startswith(prefix) for prefix in ("city_climate.", "time-context"))
        if field.startswith("users.") or field.startswith("user_context."):
            valid = field.split(".", 1)[1] in _SCENE_FIELDS
        if field.startswith("items."):
            valid = field.split(".", 1)[1] in _ITEM_FIELDS
        if not valid:
            raise ValueError(f"invalid evidence field: {field}")
    return payload


def _normalize_score(value: Any) -> float:
    if not isinstance(value, (int, float)):
        raise ValueError("judge_score must be numeric")
    return round(max(0.0, min(1.0, float(value))), 4)


def parse_jev_answers(payload: Mapping[str, Any], fact_bundle: Mapping[str, Any]) -> dict[str, Any]:
    answers = payload.get("answers") if isinstance(payload, Mapping) else None
    if not isinstance(answers, Mapping):
        raise ValueError("Jev response answers are required")
    if {"decision", "risk_type", "judge_score"}.issubset(answers):
        decision = answers["decision"].get("choice")
        risk_type = answers["risk_type"].get("choice")
        score = answers["judge_score"].get("score")
        return {
            "protocol_completeness": "legacy_3_question",
            "decision": decision,
            "risk_type": risk_type,
            "judge_score": _normalize_score(score),
            "confidence": min(
                [float(answers[key].get("confidence")) for key in ("decision", "risk_type") if isinstance(answers[key].get("confidence"), (int, float))]
                or [1.0]
            ),
            "evidence": [],
            "escalated": decision == "human_review",
        }
    required = {
        "q1_identity",
        "q2_fact_support",
        "q3_expression_risk",
        "q4_commercial_accuracy",
        "q5_context_relevance",
        "q6_safety_gate",
        "q7_final_decision",
    }
    if not required.issubset(answers):
        raise ValueError("Jev response is missing one or more q1-q7 answers")
    final = answers["q7_final_decision"]
    if not isinstance(final, Mapping):
        raise ValueError("q7_final_decision must be structured")
    return {
        "protocol_completeness": JEV_QUESTION_SCHEMA_VERSION,
        "decision": final.get("choice"),
        "risk_type": final.get("risk_type", "compliant"),
        "judge_score": _normalize_score(final.get("score")),
        "confidence": float(final.get("confidence", 1.0)),
        "evidence": list(final.get("evidence") or []),
        "escalated": bool(final.get("escalated", False)),
    }
