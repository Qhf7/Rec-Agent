"""Structured Jev questions, input allow-list and response compatibility."""

from __future__ import annotations

import re
import math
from copy import deepcopy
from typing import Any, Mapping

from canonical_data import CANONICAL_SCHEMA_VERSION, load_canonical_items
from jev_five_question import (
    FIVE_QUESTION_PREVIOUS_SCHEMA_VERSION, FIVE_QUESTION_SCHEMA_VERSION,
    build_five_question_questions, parse_five_question_answers,
)
from jev_two_question import (
    TWO_QUESTION_SCHEMA_VERSION, build_two_question_questions, parse_two_question_answers,
)


LEGACY_JEV_QUESTION_SCHEMA_VERSION = "jev-questions-v1"
V2_JEV_QUESTION_SCHEMA_VERSION = "jev-questions-v2"
JEV_QUESTION_SCHEMA_VERSION = TWO_QUESTION_SCHEMA_VERSION
Q2_LEGACY_QUESTION_SCHEMA_VERSION = "jev-questions-v2-q2-legacy"
SUPPORTED_JEV_QUESTION_VERSIONS = frozenset({
    LEGACY_JEV_QUESTION_SCHEMA_VERSION,
    FIVE_QUESTION_PREVIOUS_SCHEMA_VERSION,
    FIVE_QUESTION_SCHEMA_VERSION,
    JEV_QUESTION_SCHEMA_VERSION,
    V2_JEV_QUESTION_SCHEMA_VERSION,
    Q2_LEGACY_QUESTION_SCHEMA_VERSION,
})
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
_CLIMATE_FIELDS = {"city_tier", "climate_zone", "monsoon_months", "notes"}
_TIME_FIELDS = {"scenario_date", "snapshot_at", "timezone"}
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
    "scope",
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
_RULE_FEATURE_FIELDS = {
    "lexicon_hit_count",
    "attrs_returned_complete",
    "has_promo",
    "unsupported_efficacy_terms",
    "supported_efficacy_terms",
    "absolute_claim_terms",
    "price_mismatch",
    "topic_mismatch",
}
_DISCLOSURE_FIELDS = {"flag", "required", "status"}
_COVERAGE_FIELDS = {"missing", "complete"}
_PROVENANCE_FIELDS = {
    "reason",
    "user_context",
    "user_context.city",
    "item",
    "item.category_l1",
    "item.functions",
    "item.suit_audience",
    "item.price_cents",
    "promo",
    "lexicon_hits",
    "tool_trace",
    "disclosure",
}


def _legacy_jev_questions() -> dict[str, dict[str, Any]]:
    # Seven logical checks, with separate scalar risk and severity questions.
    definitions = {
        "q1_identity": ("确认候选、商品、版本与事实快照能否一致追溯。", {
            "valid": "身份和版本一致可追溯。", "invalid": "身份或版本冲突。", "unverifiable": "身份或版本缺少必要证据。"}),
        "q2_fact_support": ("逐项核验曝光理由；只能使用 facts，不把候选文本当作事实。", {
            "supported": "所有主张均有直接事实支持。", "partial": "部分主张缺乏支持，可删除或改写。", "unsupported": "存在无依据的核心主张。", "unverifiable": "关键事实不足。"}),
        "q3_expression_risk": ("判断绝对化、功效医疗、价格误导、披露及跑题等表达风险。", {
            "clean": "没有表达风险。", "rewriteable": "可以通过改写或补披露修复。", "blocking": "明确硬风险不能安全修复。"}),
        "q4_commercial_accuracy": ("核对文案中价格、折扣、门槛、赠品、适用范围和有效期。", {
            "verified": "所有商业表述均被有效规则支持。", "mismatch": "商业表述与事实冲突。", "not_mentioned": "文案没有商业主张。", "unverifiable": "存在商业主张但证据不足。"}),
        "q5_context_relevance": ("核对文案使用的场景与最小 scene、商品属性的相关性，不推测缺失的身份或偏好。", {
            "relevant": "商品与场景相关。", "off_topic": "场景或个性化主张不相关。", "unverifiable": "文案依赖的场景事实缺失。"}),
        "q6_safety_gate": ("检查事实缺失、冲突、敏感类目及资质是否需要人工审核。", {
            "pass": "事实充分且无人工处置疑点。", "human_review": "证据不足、冲突或敏感风险需要人工审核。", "fail": "明确硬风险，应拦截。"}),
        "q7_final_decision": ("独立根据 state 提出最终处置建议，各问题并行，不假定知道其他问题的答案。", {
            "expose": "事实充分、相关且无风险，可曝光。", "rewrite": "可安全改写；原文不得曝光。", "human_review": "证据不足或有疑点，需人工审核。", "block": "明确不可安全修复的硬风险，禁止曝光。"}),
        "risk_type": ("选择当前曝光理由的主要风险类型。", {
            "compliant": "没有风险。", "absolute_claim": "无法证明的绝对化或比较表达。", "efficacy_or_medical_claim": "无依据功效或医疗宣称。", "price_misleading": "价格或促销误导。", "missing_ai_disclosure": "缺少业务要求的 AI 披露。", "off_topic": "场景无关或无依据个性化。"}),
    }
    questions = {key: {"type": "choice", "instructions": text, "criteria": criteria}
                 for key, (text, criteria) in definitions.items()}
    questions["judge_score"] = {
        "type": "score",
        "instructions": "评估曝光理由风险严重度。分数为有序等级的期望值，不是校准违规概率。",
        "criteria": ["低风险，可以使用。", "中风险，改写或人工核查。", "高风险，应拦截。"],
    }
    return questions


def _question_version(version: str | None) -> str:
    actual = JEV_QUESTION_SCHEMA_VERSION if version is None else version
    if not isinstance(actual, str) or actual not in SUPPORTED_JEV_QUESTION_VERSIONS:
        raise ValueError(f"unsupported Jev question schema version: {actual}")
    return actual


def build_jev_questions(version: str | None = None) -> dict[str, dict[str, Any]]:
    """Build the current two-question protocol or frozen historical questions."""
    version = _question_version(version)
    if version == TWO_QUESTION_SCHEMA_VERSION:
        return build_two_question_questions()
    questions = _legacy_jev_questions()
    if version == LEGACY_JEV_QUESTION_SCHEMA_VERSION:
        return questions
    questions["q1_identity"]["instructions"] = (
        "只检查候选、商品标识、版本与事实来源是否一致可追溯；"
        "AI披露未知是独立配置状态，不构成身份冲突或事实来源缺失。"
    )
    if version != Q2_LEGACY_QUESTION_SCHEMA_VERSION:
        questions["q2_fact_support"] = {
            "type": "choice",
            "instructions": (
                "仅核验曝光理由中可验证的客观主张及其明确暗示的客观含义，依据facts中的相应商品、场景、时间和商业事实，"
                "不把候选文案当作事实。规格、材质、功能、功效、资质、量化或确定性收益、具体个人状态和事件需证据支持。"
                "允许忠实转述及与已知事实相容的一般使用场景；购买建议、祈使语气和纯主观情绪表达本身不要求数据库逐字记载，"
                "但不能借此暗示不存在的功能、疗效、安全保证或已发生的个人事件。不能从有娃等标签推断孩子尺码、疾病或实时状态。"
                "先区分可靠事实明确否定主张与关键事实源缺失；缺少未声明完备的资料不等于已证伪。"
                "coverage.complete及attrs_returned_complete只表示返回字段完整，不表示functions枚举了全部可能功能；"
                "词表命中和rule_features仅为核验线索，不能替代相应原始事实或资质来源。"
                "已明确证实的核心硬风险不被其他无关资料缺失抵消。只看本题所需事实，AI披露未知或缺失本身不降低事实支持结论。"
            ),
            "criteria": {
                "supported": "可核验的客观及暗示客观主张均有支持或被事实忠实蕴含；其余只是相容场景、行动建议或不含额外客观承诺的主观表达。",
                "partial": "核心客观卖点有依据，只有可独立删除的非核心客观断言无依据；不因存在购买建议或主观修辞本身而选择此项。",
                "unsupported": "可靠且足够的事实明确否定核心主张，或明确完备的功能/允许功效来源不支持核心宣称；不是仅因开放资料没有记载。",
                "unverifiable": "核验关键主张所需事实源确实缺失、不可追溯或可靠来源相互冲突，无法区分支持与不支持；不由AI披露状态单独触发。",
            },
        }
    questions["q3_expression_risk"]["instructions"] = (
        "检查文案本身的绝对化、功效医疗、比较或误导性客观暗示。"
        "普通行动建议、相容场景和纯主观修辞不自动构成风险，但不得掩盖客观承诺。"
        "AI披露未知只记录配置待确认，不构成表达违规或阻止曝光；"
        "只有明确required=true且flag=false（missing）才是可补充的披露缺失。"
    )
    questions["q5_context_relevance"]["instructions"] = (
        "核对文案采用或邀请的一般使用场景与scene、商品属性是否相容。"
        "普通场景叙事不等于声称已观察到实时事件；具体用户状态或身份断言仍需事实，不能额外推测偏好、疾病、孩子尺码。"
        "AI披露未知或缺失本身不影响场景相关性。"
    )
    questions["q6_safety_gate"]["instructions"] = (
        "判断是否存在核验内容所必需的资料缺失、可靠来源冲突或敏感功效/资质疑点需要人工；"
        "不能只因出现敏感类目就默认人工，明确核心硬风险应fail。"
        "AI披露unknown不是事实缺失或人工门禁，不单独阻止展示；"
        "已确认missing为可补配置问题，不等于不可核验的商品事实。"
    )
    questions["q7_final_decision"]["instructions"] = (
        "独立根据state提出内容处置建议，各问题并行，不假定知道其他问题答案。"
        "相容的一般场景、购买建议和没有客观承诺的主观修辞可使用；真正客观断言与暗示功效仍需事实支持。"
        "AI披露未知只作为独立配置待确认记录，不能仅因此选择human_review、rewrite或block，内容满足条件时可expose。"
        "已明确要求披露且确认missing可rewrite补齐；其他事实不足与真实风险照常判断。"
    )
    questions["risk_type"]["instructions"] = (
        "选择曝光理由的主要内容风险。AI披露unknown仅为配置待确认，不是missing_ai_disclosure，"
        "没有其他风险时选择compliant；只有明确required=true且flag=false（missing）可选择披露缺失。"
    )
    questions["judge_score"]["instructions"] = (
        "评估内容风险严重度；AI披露unknown仅为配置待确认，不应单独提高严重度。"
        "分数为有序等级的期望值，不是校准违规概率。"
    )
    if version in {FIVE_QUESTION_PREVIOUS_SCHEMA_VERSION, FIVE_QUESTION_SCHEMA_VERSION}:
        return build_five_question_questions(
            questions, display_guard=version == FIVE_QUESTION_SCHEMA_VERSION,
        )
    return questions


def _copy_allowed(source: Mapping[str, Any], allowed: set[str]) -> dict[str, Any]:
    return {key: deepcopy(source[key]) for key in allowed if key in source}


def build_jev_input(fact_bundle: Mapping[str, Any], *, question_version: str | None = None) -> dict[str, Any]:
    question_version = _question_version(question_version)
    item = fact_bundle.get("item") or {}
    promo = fact_bundle.get("promo") or {}
    user_context = fact_bundle.get("user_context") or {}
    candidate = {
        "schema_version": fact_bundle.get("candidate_schema_version", "rec-candidate-v2"),
        "reason_id": fact_bundle.get("reason_id"),
        "item_id": fact_bundle.get("item_id"),
        "exposure_reason": fact_bundle.get("exposure_reason", ""),
        "generated_reason": fact_bundle.get("generated_reason", ""),
        "evidence_fields": fact_bundle.get("evidence_fields") or [],
        "data_version": fact_bundle.get("data_version"),
    }
    raw_provenance = fact_bundle.get("provenance") or {}
    provenance = {}
    for key, value in raw_provenance.items():
        text = str(value)
        text = re.sub(r":?user_id=[^:]+", "", text)
        provenance[key] = text if not key.startswith("user_context") else "data/raw/users.csv"
    payload = {
        "input_schema_version": JEV_INPUT_SCHEMA_VERSION,
        "question_schema_version": question_version,
        "candidate": candidate,
        "facts": {
            "item": _copy_allowed(item, _ITEM_FIELDS),
            "promo": _copy_allowed(promo, _PROMO_FIELDS),
            "scene": _copy_allowed(user_context, _SCENE_FIELDS),
            "city_climate": _copy_allowed(fact_bundle.get("city_climate") or {}, _CLIMATE_FIELDS),
            "time_context": _copy_allowed(fact_bundle.get("time_context") or {}, _TIME_FIELDS),
            "lexicon_hits": fact_bundle.get("lexicon_hits") or [],
            "coverage": {
                key: (fact_bundle.get("coverage") or {}).get(key)
                for key in ("missing", "complete")
                if key in (fact_bundle.get("coverage") or {})
            },
            "verification_state": fact_bundle.get("verification_state"),
            "rule_features": fact_bundle.get("rule_features") or {},
            "disclosure": fact_bundle.get("disclosure") or {},
            "provenance": provenance,
        },
        "trace": {
            "reason_id": fact_bundle.get("reason_id"),
            "item_id": fact_bundle.get("item_id"),
            "schema_version": fact_bundle.get("schema_version"),
            "data_version": fact_bundle.get("data_version"),
            "agent_version": fact_bundle.get("agent_version", "rec-agent-v2"),
            "model_version": fact_bundle.get("model_version", "jev-1.14.0"),
            "snapshot_at": fact_bundle.get("snapshot_at"),
        },
        "questions": build_jev_questions(question_version),
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


def _typed_fields(source: Mapping[str, Any], *, lists=(), integers=(), booleans=(), numbers=(), nullable=()) -> None:
    """Reject containers hidden in scalar fields and enforce every list element."""
    for key, value in source.items():
        if value is None and key in nullable:
            continue
        if key in lists:
            valid = isinstance(value, list) and all(isinstance(part, str) for part in value)
        elif key in integers:
            valid = type(value) is int and value >= 0
        elif key in booleans:
            valid = type(value) is bool
        elif key in numbers:
            valid = type(value) in (int, float) and math.isfinite(value) and value >= 0
        else:
            valid = isinstance(value, str)
        if not valid:
            raise ValueError(f"invalid type for Jev input field: {key}")


def validate_jev_input(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Jev input must be an object")
    for key, path in _walk_keys(payload):
        lowered = key.casefold()
        if lowered == "user_id" or any(part in lowered for part in _FORBIDDEN_KEY_PARTS):
            raise ValueError(f"forbidden Jev input field: {path}")
    expected_top = {"input_schema_version", "question_schema_version", "candidate", "facts", "trace", "questions"}
    if set(payload) != expected_top:
        raise ValueError("unknown or missing Jev input fields")
    if payload.get("input_schema_version") != JEV_INPUT_SCHEMA_VERSION:
        raise ValueError("unsupported Jev input schema version")
    question_version = _question_version(payload.get("question_schema_version"))
    if payload.get("question_schema_version") is None:
        raise ValueError("unsupported Jev question schema version: missing")
    candidate = payload.get("candidate")
    if not isinstance(candidate, Mapping):
        raise ValueError("candidate is required")
    expected_candidate = {"schema_version", "reason_id", "item_id", "exposure_reason", "generated_reason", "evidence_fields", "data_version"}
    if set(candidate) != expected_candidate:
        raise ValueError(f"unknown or missing candidate fields: {sorted(set(candidate) ^ expected_candidate)}")
    for field in ("schema_version", "reason_id", "item_id", "exposure_reason", "generated_reason", "data_version"):
        if not isinstance(candidate.get(field), str) or not candidate[field].strip():
            raise ValueError(f"candidate requires {field}")
    if candidate["schema_version"] != "rec-candidate-v2":
        raise ValueError("candidate schema_version mismatch")
    if candidate["data_version"] != CANONICAL_SCHEMA_VERSION:
        raise ValueError("candidate data_version mismatch")
    if candidate["exposure_reason"] != candidate["generated_reason"]:
        raise ValueError("generated_reason must equal exposure_reason")
    if not re.fullmatch(r"i_\d{4}", str(candidate["item_id"])):
        raise ValueError("candidate item_id must be canonical")
    if str(candidate["item_id"]) not in load_canonical_items():
        raise ValueError(f"unknown item_id: {candidate['item_id']}")
    facts = payload.get("facts")
    if not isinstance(facts, Mapping):
        raise ValueError("facts are required")
    expected_facts = {"item", "promo", "scene", "city_climate", "time_context", "lexicon_hits", "coverage", "verification_state", "rule_features", "disclosure", "provenance"}
    if set(facts) != expected_facts:
        raise ValueError("unknown or missing facts fields")
    for name in ("item", "promo", "scene", "city_climate", "time_context", "coverage", "rule_features", "disclosure", "provenance"):
        if not isinstance(facts[name], Mapping):
            raise ValueError(f"facts.{name} must be an object")
    if not isinstance(facts["item"], Mapping) or facts["item"].get("item_id") != candidate["item_id"]:
        raise ValueError("facts.item_id must match candidate item_id")
    if set(facts["item"]) - _ITEM_FIELDS:
        raise ValueError("unknown facts.item fields")
    if set(facts["promo"]) - _PROMO_FIELDS:
        raise ValueError("unknown facts.promo fields")
    if set(facts["coverage"]) - _COVERAGE_FIELDS:
        raise ValueError("unknown facts.coverage fields")
    if set(facts["rule_features"]) - _RULE_FEATURE_FIELDS:
        raise ValueError("unknown facts.rule_features fields")
    if set(facts["disclosure"]) - _DISCLOSURE_FIELDS:
        raise ValueError("unknown facts.disclosure fields")
    if set(facts["provenance"]) - _PROVENANCE_FIELDS:
        raise ValueError("unknown facts.provenance fields")
    if set(facts["scene"]) - _SCENE_FIELDS:
        raise ValueError("unknown facts.scene fields")
    if set(facts["city_climate"]) - _CLIMATE_FIELDS or set(facts["time_context"]) - _TIME_FIELDS:
        raise ValueError("unknown climate/time context fields")
    if "scope" in facts["promo"]:
        scope = facts["promo"]["scope"]
        if not isinstance(scope, Mapping) or set(scope) - {"category_l1", "category_l2", "category_l3", "item_ids", "item_id", "brand"}:
            raise ValueError("unknown promo scope fields")
        _typed_fields(scope, lists=set(scope))
    if not isinstance(facts["lexicon_hits"], list):
        raise ValueError("lexicon_hits must be a list")
    if not isinstance(candidate["evidence_fields"], list):
        raise ValueError("evidence_fields must be a list")
    _typed_fields(facts["item"],
                  lists={"functions", "promo_tags", "promo_rule_ids", "efficacy_claims_allowed", "qualifications"},
                  integers={"price_cents", "original_price_cents", "stock"}, booleans={"sensitive_category"})
    _typed_fields({key: value for key, value in facts["promo"].items() if key != "scope"},
                  integers={"threshold_cents", "discount_cents", "discount_percent"},
                  numbers={"discount_rate"}, booleans={"applicable"})
    _typed_fields(facts["scene"], lists={"tags"})
    _typed_fields(facts["disclosure"], booleans={"flag", "required"}, nullable={"flag"})
    if "status" in facts["disclosure"]:
        status = facts["disclosure"]["status"]
        expected_flag = {"visible": True, "missing": False, "unknown": None}
        if status not in expected_flag or facts["disclosure"].get("flag") is not expected_flag[status]:
            raise ValueError("disclosure status must match flag")
    _typed_fields(facts["coverage"], lists={"missing"}, booleans={"complete"})
    _typed_fields(facts["rule_features"],
                  lists={"unsupported_efficacy_terms", "supported_efficacy_terms", "absolute_claim_terms"},
                  integers={"lexicon_hit_count"},
                  booleans={"attrs_returned_complete", "has_promo", "price_mismatch", "topic_mismatch"})
    _typed_fields(facts["provenance"])
    _typed_fields(facts["time_context"])
    _typed_fields({key: value for key, value in facts["city_climate"].items() if key != "monsoon_months"})
    months = facts["city_climate"].get("monsoon_months", [])
    if not isinstance(months, list) or any(type(month) is not int or not 1 <= month <= 12 for month in months):
        raise ValueError("invalid city_climate.monsoon_months")
    if facts["verification_state"] not in {"verified", "unverifiable", "conflict"}:
        raise ValueError("invalid verification_state")
    for hit in facts["lexicon_hits"]:
        if not isinstance(hit, Mapping):
            raise ValueError("lexicon hit must be an object")
        if set(hit) - {"term", "canonical_term", "risk_type", "severity", "match_type"}:
            raise ValueError("unknown facts.lexicon_hits fields")
        _typed_fields(hit)
    trace = payload.get("trace")
    if not isinstance(trace, Mapping):
        raise ValueError("trace is required")
    expected_trace = {"reason_id", "item_id", "schema_version", "data_version", "agent_version", "model_version", "snapshot_at"}
    if set(trace) != expected_trace:
        raise ValueError(f"unknown or missing trace fields: {sorted(set(trace) ^ expected_trace)}")
    _typed_fields(trace, nullable={"snapshot_at"})
    if trace["reason_id"] != candidate["reason_id"] or trace["item_id"] != candidate["item_id"]:
        raise ValueError("trace item_id/reason_id does not match candidate")
    if trace["schema_version"] != "fact-bundle-v2":
        raise ValueError("trace schema_version mismatch")
    if trace["data_version"] != CANONICAL_SCHEMA_VERSION:
        raise ValueError("data_version is required and must be canonical")
    if candidate.get("evidence_fields") is None:
        raise ValueError("evidence_fields is required")
    expected_questions = build_jev_questions(question_version)
    if payload["questions"] != expected_questions:
        raise ValueError("questions schema mismatch; expected the requested version definition")
    for field in list(candidate.get("evidence_fields") or []):
        sources = {"item": facts["item"], "user_context": facts["scene"], "promo": facts["promo"],
                   "city_climate": facts["city_climate"], "time_context": facts["time_context"]}
        if not isinstance(field, str) or not _evidence_path_present(field, sources):
            raise ValueError(f"invalid evidence field: {field}")
    for value in facts["provenance"].values():
        if "user_id" in str(value):
            raise ValueError("user identifier leaked in provenance")
    return payload


def _unit_number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError(f"{name} must be finite in [0, 1]")
    return float(value)


def _normalize_score(answer: Mapping[str, Any], *, fixed_scale: int | None = None) -> float:
    raw = answer.get("score")
    if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(raw):
        raise ValueError("judge_score must be finite numeric")
    probabilities = answer.get("probabilities") or {}
    if not isinstance(probabilities, Mapping):
        raise ValueError("judge_score probabilities must be an object")
    # The request defines a 0/1/2 scale. Archived unit scores may omit probabilities.
    scale = fixed_scale if fixed_scale is not None else 2 if probabilities else 1
    if probabilities:
        if set(probabilities) != {str(index) for index in range(scale + 1)}:
            raise ValueError("judge_score probabilities do not match the request scale")
        values = [_unit_number(value, "probabilities") for value in probabilities.values()]
        if not math.isclose(sum(values), 1.0, abs_tol=0.02):
            raise ValueError("judge_score probabilities must sum to one")
        # Official Score is an expected ordered level. Derive it from the
        # distribution so a contradictory scalar cannot lower the risk.
        raw = sum(int(level) * probability for level, probability in probabilities.items())
    if scale < 1 or not 0 <= raw <= scale:
        raise ValueError("judge_score outside declared scale")
    return round(float(raw) / scale, 4)


def _evidence_path_present(field: str, fact_bundle: Mapping[str, Any]) -> bool:
    if field == "time-context":
        return bool((fact_bundle.get("time_context") or {}).get("scenario_date"))
    prefix, _, name = field.partition(".")
    source = {"items": "item", "users": "user_context", "user_context": "user_context", "promo": "promo",
              "city_climate": "city_climate", "time_context": "time_context"}.get(prefix)
    if source:
        allowed = {"item": _ITEM_FIELDS, "user_context": _SCENE_FIELDS, "promo": _PROMO_FIELDS,
                   "city_climate": _CLIMATE_FIELDS, "time_context": _TIME_FIELDS}[source]
        return name in allowed and (fact_bundle.get(source) or {}).get(name) not in (None, "", [])
    return False


def parse_jev_answers(payload: Mapping[str, Any], fact_bundle: Mapping[str, Any], *,
                      expected_protocol: str | None = None) -> dict[str, Any]:
    answers = payload.get("answers") if isinstance(payload, Mapping) else None
    if not isinstance(answers, Mapping):
        raise ValueError("Jev response answers are required")
    if expected_protocol == TWO_QUESTION_SCHEMA_VERSION or (expected_protocol is None and set(answers) == {"risk_type", "attractiveness_score"}):
        return parse_two_question_answers(
            answers, fact_bundle, build_jev_questions(TWO_QUESTION_SCHEMA_VERSION), _evidence_path_present,
            protocol_version=TWO_QUESTION_SCHEMA_VERSION,
        )
    if expected_protocol in {FIVE_QUESTION_PREVIOUS_SCHEMA_VERSION, FIVE_QUESTION_SCHEMA_VERSION} or "attractiveness_score" in answers:
        if expected_protocol not in (None, FIVE_QUESTION_PREVIOUS_SCHEMA_VERSION, FIVE_QUESTION_SCHEMA_VERSION):
            raise ValueError("response format does not match requested protocol")
        version = expected_protocol or FIVE_QUESTION_SCHEMA_VERSION
        return parse_five_question_answers(
            answers, fact_bundle, build_jev_questions(version), _evidence_path_present,
            protocol_version=version,
        )
    question_version = _question_version(expected_protocol or V2_JEV_QUESTION_SCHEMA_VERSION)
    questions = build_jev_questions(question_version)
    full = "q7_final_decision" in answers
    archived = full and isinstance(answers["q7_final_decision"], Mapping) and "score" in answers["q7_final_decision"]
    if archived and ({"risk_type", "judge_score"} & set(answers)):
        raise ValueError("mixed archived/scalar response format")
    if expected_protocol is not None and (not full or archived):
        raise ValueError("response format does not match requested scalar protocol")
    required = set(questions) if full and not archived else set(questions) - {"risk_type", "judge_score"} if full else {"decision", "risk_type", "judge_score"}
    if not required <= set(answers):
        raise ValueError("Jev response is missing required question answers")
    for key in required:
        if not isinstance(answers[key], Mapping):
            raise ValueError(f"{key} answer must be an object")
        if key == "judge_score":
            continue
        definition = questions.get(key, questions["q7_final_decision"])
        if answers[key].get("choice") not in definition["criteria"]:
            raise ValueError(f"invalid {key} decision/choice")
    final = answers["q7_final_decision"] if full else answers["decision"]
    decision = final["choice"]
    risk_type = final.get("risk_type") if archived else answers["risk_type"]["choice"]
    if risk_type not in questions["risk_type"]["criteria"]:
        raise ValueError("invalid risk_type")
    score_answer = {"score": final.get("score")} if archived else answers["judge_score"]
    score = _normalize_score(score_answer, fixed_scale=2 if full and not archived else None)
    if full and not archived and any("confidence" not in answers[key] for key in required):
        raise ValueError("confidence is required for every scalar question")
    confidence_values = [_unit_number(answer["confidence"], "confidence") for key, answer in answers.items()
                         if key in required and isinstance(answer, Mapping) and "confidence" in answer]
    confidence = min(confidence_values or [0.0])
    evidence = final.get("evidence") or []
    if not isinstance(evidence, list) or any(not isinstance(field, str) or not _evidence_path_present(field, fact_bundle) for field in evidence):
        raise ValueError("invalid or unavailable evidence field")
    if "escalated" in final and not isinstance(final["escalated"], bool):
        raise ValueError("escalated must be boolean")
    result = {
        "protocol_completeness": (LEGACY_JEV_QUESTION_SCHEMA_VERSION if archived else question_version) if full else "legacy_3_question",
        "decision": decision, "risk_type": risk_type, "judge_score": score,
        "confidence": confidence,
        "decision_confidence": _unit_number(final.get("confidence", 0.0), "confidence"),
        "evidence": evidence,
        "escalated": decision == "human_review",
    }
    if full:
        result["question_confidences"] = {
            key: _unit_number(answer["confidence"], "confidence")
            for key, answer in answers.items()
            if key in required and "confidence" in answer
        }
        result["question_choices"] = {
            key: answer["choice"] for key, answer in answers.items()
            if key in required and key != "judge_score"
        }
        for key, field in (("q1_identity", "identity"), ("q2_fact_support", "fact_support"),
                           ("q3_expression_risk", "expression_risk"), ("q4_commercial_accuracy", "commercial_accuracy"),
                           ("q5_context_relevance", "context_relevance"), ("q6_safety_gate", "safety_gate")):
            result[field + "_choice"] = answers[key]["choice"]
    return result
