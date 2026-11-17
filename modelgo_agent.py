"""ModelGo DeepSeek fallback agent for structured recommendation-card generation."""

from __future__ import annotations

import json
import os
import re
import ssl
import urllib.error
import urllib.request
from typing import Any

from jev_adapter import build_ssl_context

DEFAULT_ENDPOINT = "https://api.modelgo.ai/v1/chat/completions"
DEFAULT_MODEL = "deepseek-v4-flash"


class AgentConfigurationError(RuntimeError):
    pass


class AgentResponseError(RuntimeError):
    pass


def _extract_json(value: str | dict) -> Any:
    if isinstance(value, dict):
        return value
    text = value.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", text, flags=re.S)
    text = fenced.group(1) if fenced else text
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        start = min([p for p in (text.find("{"), text.find("[")) if p >= 0], default=-1)
        end = max(text.rfind("}"), text.rfind("]"))
        if start >= 0 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                pass
        raise AgentResponseError("Agent response is not valid JSON") from exc


def parse_agent_cards(raw: str | dict, expected: dict[str, str]) -> list[dict]:
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
        user_id = str(card["user_id"])
        item_id = str(card["item_id"])
        if user_id not in expected:
            raise AgentResponseError(f"unexpected user_id: {user_id}")
        if expected[user_id] != item_id:
            raise AgentResponseError(f"item mismatch for {user_id}: {item_id}")
        if user_id in seen:
            raise AgentResponseError(f"duplicate user_id: {user_id}")
        exposure_reason = str(card.get("exposure_reason", card.get("generated_reason", ""))).strip()
        generated_reason = str(card.get("generated_reason", exposure_reason)).strip()
        if not exposure_reason:
            raise AgentResponseError(f"exposure_reason must be non-empty: {user_id}")
        if generated_reason != exposure_reason:
            raise AgentResponseError(f"generated_reason must equal exposure_reason: {user_id}")
        reason = exposure_reason
        if not reason or len(reason) > 24:
            raise AgentResponseError(f"exposure_reason must be 1-24 characters: {user_id}")
        evidence_fields = card["evidence_fields"]
        if not isinstance(evidence_fields, list) or not evidence_fields:
            raise AgentResponseError(f"evidence_fields must be non-empty: {user_id}")
        parsed.append({
            "user_id": user_id,
            "item_id": item_id,
            "exposure_reason": reason,
            "generated_reason": reason,
            "evidence_fields": [str(x) for x in evidence_fields],
        })
        seen.add(user_id)
    if set(expected) != seen:
        raise AgentResponseError(f"Agent returned {len(seen)} cards, expected {len(expected)}")
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
        expected = {row["user_id"]: row["item_id"] for row in contexts}
        instructions = {
            "task": "为每个用户生成一张商品推荐卡片",
            "output_schema": {
                "cards": [
                    {
                        "user_id": "string",
                        "item_id": "string",
                        "exposure_reason": "给用户展示的一句话，不超过24个汉字",
                        "generated_reason": "不超过24个汉字",
                        "evidence_fields": ["实际使用的字段名"]
                    }
                ]
            },
            "constraints": [
                "只输出 JSON，不要 Markdown 或解释",
                "必须为每个 user_id 返回一张卡片，不能新增或遗漏用户",
                "exposure_reason 是给用户看的单句文案，不超过24个汉字，必须基于给定商品事实",
                "generated_reason 必须与 exposure_reason 完全相同，仅用于兼容旧字段",
                "不得编造给定上下文中不存在的功能、优惠或功效",
                "evidence_fields 只能填写实际使用的上下文字段名",
            ],
            "expected_user_item_pairs": expected,
            "contexts": contexts,
        }
        return {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "你是电商推荐卡片生成 Agent。严格遵守 JSON 输出约束。"},
                {"role": "user", "content": json.dumps(instructions, ensure_ascii=False)},
            ],
            "temperature": 0.2,
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
        expected = {row["user_id"]: row["item_id"] for row in contexts}
        return parse_agent_cards(content, expected)
