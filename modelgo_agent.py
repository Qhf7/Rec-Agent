"""Generate structured, fact-grounded recommendation copy with DeepSeek."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections.abc import Iterable, Mapping
from typing import Any

from jev_adapter import build_ssl_context
from recommendation_copy import build_copy_brief, copy_generation_instructions, validate_reason_text
from scripts.strict_json_output import strict_json_loads

DEFAULT_ENDPOINT = "https://api.modelgo.ai/v1/chat/completions"
DEFAULT_MODEL = "deepseek-v4-flash"


class AgentConfigurationError(RuntimeError):
    pass


class AgentResponseError(RuntimeError):
    pass


def _extract_json(value: str | dict) -> Any:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        raise AgentResponseError("Agent response must be strict JSON text or an object")
    try:
        return strict_json_loads(value)
    except ValueError as exc:
        raise AgentResponseError("Agent response is not one complete strict JSON document") from exc


def _expected_pairs(expected: Mapping[str, str] | Iterable[tuple[str, str]]) -> set[tuple[str, str]]:
    """Accept the legacy one-item map while retaining every requested pair."""
    pairs = list(expected.items() if isinstance(expected, Mapping) else expected)
    if any(not isinstance(pair, (list, tuple)) or len(pair) != 2 for pair in pairs):
        raise AgentResponseError("expected pairs must contain user_id and item_id")
    if any(not isinstance(value, str) or not value.strip() for pair in pairs for value in pair):
        raise AgentResponseError("expected user_id and item_id must be non-empty strings")
    normalized = {tuple(pair) for pair in pairs}
    if len(normalized) != len(pairs):
        raise AgentResponseError("duplicate requested user/item pair")
    return normalized


def parse_agent_cards(
    raw: str | dict, expected: Mapping[str, str] | Iterable[tuple[str, str]]
) -> list[dict]:
    expected_pairs = _expected_pairs(expected)
    payload = _extract_json(raw)
    cards = payload.get("cards") if isinstance(payload, dict) else payload
    if not isinstance(cards, list):
        raise AgentResponseError("Agent response must contain a cards array")
    parsed = []
    seen = set()
    for card in cards:
        if not isinstance(card, dict):
            raise AgentResponseError("Agent card must be an object")
        for field in ("user_id", "item_id", "evidence_fields"):
            if field not in card:
                raise AgentResponseError(f"Agent card missing {field}")
        user_id, item_id = card["user_id"], card["item_id"]
        if not isinstance(user_id, str) or not isinstance(item_id, str):
            raise AgentResponseError("user_id and item_id must be strings")
        pair = (user_id, item_id)
        if pair not in expected_pairs:
            raise AgentResponseError(f"unexpected user/item pair: {user_id}/{item_id}")
        if pair in seen:
            raise AgentResponseError(f"duplicate user/item pair: {user_id}/{item_id}")
        try:
            exposure_reason = validate_reason_text(card.get("exposure_reason", card.get("generated_reason", "")))
        except ValueError as exc:
            raise AgentResponseError(f"invalid exposure_reason for {user_id}/{item_id}: {exc}") from exc
        generated_reason = card.get("generated_reason", exposure_reason)
        if generated_reason != exposure_reason:
            raise AgentResponseError(f"generated_reason must equal exposure_reason: {user_id}")
        reason = exposure_reason
        evidence_fields = card["evidence_fields"]
        if (
            not isinstance(evidence_fields, list)
            or not 2 <= len(evidence_fields) <= 6
            or any(not isinstance(field, str) or not field.strip() for field in evidence_fields)
            or len(set(evidence_fields)) != len(evidence_fields)
        ):
            raise AgentResponseError(f"evidence_fields must contain 2-6 distinct field names: {user_id}")
        parsed.append({
            "user_id": user_id,
            "item_id": item_id,
            "exposure_reason": reason,
            "generated_reason": reason,
            "evidence_fields": list(evidence_fields),
        })
        seen.add(pair)
    if expected_pairs != seen:
        raise AgentResponseError(f"Agent returned {len(seen)} cards, expected {len(expected_pairs)}")
    return parsed


class ModelGoAgent:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        endpoint: str = DEFAULT_ENDPOINT,
        model: str = DEFAULT_MODEL,
        timeout: float = 60.0,
        dry_run: bool = True,
    ) -> None:
        self.api_key = api_key if api_key is not None else os.getenv("MODELGO_API_KEY")
        self.endpoint = endpoint
        self.model = model
        self.timeout = timeout
        self.dry_run = dry_run

    def build_payload(self, contexts: list[dict]) -> dict:
        _expected_pairs((row["user_id"], row["item_id"]) for row in contexts)
        instructions = {
            **copy_generation_instructions(),
            "task": "根据每个 copy_brief 的商品关键信息，由大模型创作一条自然生动的广告曝光理由",
            "output_schema": {
                "cards": [
                    {
                        "user_id": "string",
                        "item_id": "string",
                        "exposure_reason": "商品卖点单行广告，目标8–18个Unicode字符，总长度不超过20字符，不含商品数量或规格参数",
                        "generated_reason": "与 exposure_reason 完全相同",
                        "evidence_fields": ["实际用于文案的2–6个规范字段路径，至少一个items.字段"]
                    }
                ]
            },
            "output_constraints": [
                "只输出 JSON，不要 Markdown 或解释",
                "整段回复必须是一个严格JSON根对象；不允许前后文字、代码围栏、重复键、NaN、Infinity或多个根值",
                "必须为每个 user_id/item_id 组合返回一张卡片，不能新增、遗漏或合并；同一用户可能有多个商品",
                "generated_reason 必须与 exposure_reason 完全相同，仅用于兼容旧字段",
                "evidence_fields 只能填写 copy_brief 实际给出且文案使用的事实字段路径",
            ],
            "expected_user_item_pairs": [
                {"user_id": row["user_id"], "item_id": row["item_id"]} for row in contexts
            ],
            "contexts": [
                {"user_id": row["user_id"], "item_id": row["item_id"], "copy_brief": build_copy_brief(row)}
                for row in contexts
            ],
        }
        return {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "你是电商广告文案创作 Agent。围绕给定商品事实写自然易读的曝光理由，严格遵守 JSON 输出约束。"},
                {"role": "user", "content": json.dumps(instructions, ensure_ascii=False)},
            ],
            "temperature": 0.7,
        }

    def generate_batch(self, contexts: list[dict]) -> dict | list[dict]:
        payload = self.build_payload(contexts)
        if self.dry_run:
            return {"dry_run": True, "request": payload}
        if not self.api_key:
            raise AgentConfigurationError("MODELGO_API_KEY is required when dry_run=False")
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
            with urllib.request.urlopen(request, timeout=self.timeout, context=build_ssl_context()) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")
            raise AgentResponseError(f"HTTP {exc.code}: {detail[:1000]}") from exc
        except urllib.error.URLError as exc:
            raise AgentResponseError(f"Agent request failed: {exc}") from exc
        try:
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise AgentResponseError("ModelGo response missing choices[0].message.content") from exc
        expected = [(row["user_id"], row["item_id"]) for row in contexts]
        return parse_agent_cards(content, expected)
