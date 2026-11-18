"""Replaceable Jev SystemOne HTTP adapter with a safe dry-run mode."""

from __future__ import annotations

import json
import math
import os
import re
import ssl
import urllib.error
import urllib.request
from typing import Any

from jev_protocol import (
    JEV_QUESTION_SCHEMA_VERSION,
    build_jev_input,
    build_jev_questions,
    parse_jev_answers,
)


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
    if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score) or not 0 <= float(score) <= 1:
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
        jev_input = build_jev_input(dict(fact_bundle, model_version=self.model))
        state = json.dumps(jev_input, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        return {
            "model": self.model,
            "state": state,
            "questions": build_jev_questions(),
        }

    def judge(self, fact_bundle: dict) -> dict:
        if self.dry_run:
            payload = self.build_payload(fact_bundle)
            return {"dry_run": True, "request": payload}
        if not self.api_key:
            raise JevConfigurationError("MODELGO_API_KEY is required when dry_run=False")
        payload = self.build_payload(fact_bundle)

        request = urllib.request.Request(
            self.endpoint,
            data=json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8"),
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
        return self.parse_response(raw, fact_bundle, expected_protocol=JEV_QUESTION_SCHEMA_VERSION)

    def parse_response(self, raw: str | bytes | dict, fact_bundle: dict, *,
                       expected_protocol: str | None = None) -> dict:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        parsed: Any = raw if isinstance(raw, dict) else json.loads(raw)
        if isinstance(parsed, dict) and isinstance(parsed.get("answers"), dict):
            return self._parse_systemone_response(parsed, fact_bundle, expected_protocol=expected_protocol)
        if expected_protocol is not None:
            raise JevResponseError("response format does not match requested scalar protocol")

        result = _find_decision_object(parsed)
        if result is None:
            raise JevResponseError("response did not contain a valid decision object")
        result.setdefault("reason_id", fact_bundle.get("reason_id"))
        result.setdefault("model_version", self.model)
        result.setdefault("score_name", self.score_name)
        if result["reason_id"] != fact_bundle.get("reason_id"):
            raise JevResponseError("response reason_id mismatch")
        result.setdefault("confidence", 0.0)
        self._apply_safety_gates(result, fact_bundle)
        return validate_decision(result)

    def _parse_systemone_response(self, payload: dict, fact_bundle: dict, *,
                                  expected_protocol: str | None = None) -> dict:
        if payload.get("model", self.model) != self.model:
            raise JevResponseError("response model does not match requested model")
        try:
            parsed_answers = parse_jev_answers(payload, fact_bundle, expected_protocol=expected_protocol)
        except (KeyError, TypeError, ValueError) as exc:
            raise JevResponseError("SystemOne response missing a valid Jev question answer") from exc

        result = {
            **parsed_answers,
            "reason_id": fact_bundle.get("reason_id"),
            "model_version": payload.get("model", self.model),
            "score_name": self.score_name,
        }
        result["evidence"] = list(result.get("evidence") or []) or build_evidence_from_fact_bundle(fact_bundle)
        result["evidence_source"] = "model_field_selection" if parsed_answers.get("evidence") else "workflow_fact_snapshot"
        self._apply_safety_gates(result, fact_bundle)
        return validate_decision(result)

    def _apply_safety_gates(self, result: dict, fact_bundle: dict) -> None:
        confidence = result.get("confidence", 0.0)
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not math.isfinite(confidence) or not 0 <= confidence <= 1:
            raise JevResponseError("confidence must be finite in [0, 1]")
        if result.get("reason_id") != fact_bundle.get("reason_id"):
            raise JevResponseError("response reason_id mismatch")
        result.setdefault("evidence", [])
        state = fact_bundle.get("verification_state", "unverifiable")
        missing = (fact_bundle.get("coverage") or {}).get("missing")
        human_gate = (
            state != "verified" or bool(missing) or confidence < 0.7
            or result.get("escalated") is True or result["decision"] == "human_review"
            or result.get("identity_choice") in {"invalid", "unverifiable"}
            or result.get("fact_support_choice") == "unverifiable"
            or result.get("commercial_accuracy_choice") == "unverifiable"
            or result.get("context_relevance_choice") == "unverifiable"
            or result.get("safety_gate_choice") == "human_review"
        )
        if human_gate:
            result.update(decision="human_review", escalated=True)
            result["evidence"].append("workflow.safety_gate: 事实不足、冲突、人工门禁或置信度不足")
            return
        features = fact_bundle.get("rule_features") or {}
        if (features.get("unsupported_efficacy_terms")
                or features.get("price_mismatch")
                or result.get("fact_support_choice") == "unsupported"
                or result.get("expression_risk_choice") == "blocking"
                or result.get("commercial_accuracy_choice") == "mismatch"
                or result.get("safety_gate_choice") == "fail"):
            result["decision"] = "block"
            if features.get("unsupported_efficacy_terms"):
                result["risk_type"] = "efficacy_or_medical_claim"
            elif features.get("price_mismatch") or result.get("commercial_accuracy_choice") == "mismatch":
                result["risk_type"] = "price_misleading"
            result["evidence"].append("workflow.safety_gate: 明确的事实或合规硬风险")
        elif result["decision"] != "block" and (
                result.get("fact_support_choice") == "partial"
                or result.get("expression_risk_choice") == "rewriteable"
                or result.get("context_relevance_choice") == "off_topic"
                or features.get("absolute_claim_terms") or features.get("topic_mismatch")):
            result["decision"] = "rewrite"
            if features.get("absolute_claim_terms"):
                result["risk_type"] = "absolute_claim"
            elif features.get("topic_mismatch") or result.get("context_relevance_choice") == "off_topic":
                result["risk_type"] = "off_topic"
        disclosure = fact_bundle.get("disclosure") or {}
        if disclosure.get("required", True) and disclosure.get("flag") is not True and result["decision"] != "block":
            result.update(decision="rewrite", risk_type="missing_ai_disclosure")
            result["evidence"].append("workflow.disclosure: 必须补充 AI 披露")
        if result["decision"] == "expose" and (result["risk_type"] != "compliant" or result["judge_score"] >= 0.5):
            result.update(decision="human_review", escalated=True)
            result["evidence"].append("workflow.consistency: 曝光建议与风险判断冲突")


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
