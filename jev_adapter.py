"""Jev SystemOne HTTP adapter that preserves the model disposition."""

from __future__ import annotations

import json
import math
import os
import re
import ssl
import urllib.error
import urllib.request
from typing import Any, Callable

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


def _strict_json_loads(text: str) -> Any:
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise JevResponseError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    def invalid_constant(value):
        raise JevResponseError(f"invalid JSON constant: {value}")

    return json.loads(text, object_pairs_hook=unique_object, parse_constant=invalid_constant)


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
        response_observer: Callable[[str, str], None] | None = None,
        question_version: str | None = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else os.getenv("MODELGO_API_KEY")
        self.endpoint = endpoint
        self.model = model
        self.score_name = score_name
        self.timeout = timeout
        self.dry_run = dry_run
        # The observer sees only the candidate ID and response body, before
        # parsing. Request headers and credentials stay private.
        self.response_observer = response_observer
        self.question_version = question_version or JEV_QUESTION_SCHEMA_VERSION
        build_jev_questions(self.question_version)

    def build_payload(self, fact_bundle: dict) -> dict:
        jev_input = build_jev_input(dict(fact_bundle, model_version=self.model), question_version=self.question_version)
        state = json.dumps(jev_input, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        return {
            "model": self.model,
            "state": state,
            "questions": build_jev_questions(self.question_version),
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
        if self.response_observer is not None:
            self.response_observer(fact_bundle["reason_id"], raw)
        return self.parse_response(raw, fact_bundle, expected_protocol=self.question_version)

    def parse_response(self, raw: str | bytes | dict, fact_bundle: dict, *,
                       expected_protocol: str | None = None) -> dict:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        parsed: Any = raw if isinstance(raw, dict) else _strict_json_loads(raw)
        if isinstance(parsed, dict) and isinstance(parsed.get("answers"), dict):
            return self._parse_systemone_response(parsed, fact_bundle, expected_protocol=expected_protocol)
        if expected_protocol is not None:
            raise JevResponseError("response format does not match requested scalar protocol")

        found = _find_decision_object(parsed)
        if found is None:
            raise JevResponseError("response did not contain a valid decision object")
        result = dict(found)
        result.setdefault("reason_id", fact_bundle.get("reason_id"))
        result.setdefault("model_version", self.model)
        result.setdefault("score_name", self.score_name)
        if result["reason_id"] != fact_bundle.get("reason_id"):
            raise JevResponseError("response reason_id mismatch")
        result.setdefault("confidence", 0.0)
        self._attach_result_metadata(result, fact_bundle, decision_question="decision")
        return validate_decision(result)

    def _parse_systemone_response(self, payload: dict, fact_bundle: dict, *,
                                  expected_protocol: str | None = None) -> dict:
        if payload.get("model", self.model) != self.model:
            raise JevResponseError("response model does not match requested model")
        expected_metadata = {
            "reason_id": fact_bundle.get("reason_id"),
            "item_id": fact_bundle.get("item_id"),
            "question_schema_version": expected_protocol or self.question_version,
        }
        for field, expected in expected_metadata.items():
            if field in payload and payload[field] != expected:
                raise JevResponseError(f"response {field} mismatch")
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
        self._attach_result_metadata(
            result, fact_bundle,
            decision_question="decision" if parsed_answers.get("protocol_completeness") == "legacy_3_question" else "q7_final_decision",
        )
        return validate_decision(result)

    def _attach_result_metadata(self, result: dict, fact_bundle: dict, *, decision_question: str) -> None:
        """Validate response metadata and describe its source without changing its disposition."""
        confidence = result.get("confidence", 0.0)
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not math.isfinite(confidence) or not 0 <= confidence <= 1:
            raise JevResponseError("confidence must be finite in [0, 1]")
        if result.get("reason_id") != fact_bundle.get("reason_id"):
            raise JevResponseError("response reason_id mismatch")
        if result.get("model_version") != self.model:
            raise JevResponseError("response model does not match requested model")
        if "escalated" in result and not isinstance(result["escalated"], bool):
            raise JevResponseError("escalated must be boolean")
        # Compatibility field describes the returned label; it does not dispatch work.
        result["escalated"] = result.get("decision") == "human_review"
        result["decision_source"] = "jev_model"
        result["decision_question"] = decision_question
        disclosure = fact_bundle.get("disclosure") or {}
        flag = disclosure.get("flag")
        disclosure_status = "visible" if flag is True else "missing" if flag is False else "unknown"
        result["disclosure_status"] = disclosure_status
        result["configuration_notes"] = (
            [f"ai_disclosure_{disclosure_status}"]
            if disclosure.get("required", True) and disclosure_status != "visible" else []
        )


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
                return _find_decision_object(_strict_json_loads(candidate))
            except json.JSONDecodeError:
                return None
    return None
