#!/usr/bin/env python3
"""Extract and pretty-print a Rec-Agent JSON response from pasted Harness text."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from scripts.strict_json_output import extract_last_json


def extract_json(text: str) -> dict:
    payload = extract_last_json(text)
    if not isinstance(payload, dict):
        raise ValueError("结果必须是 JSON 对象")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="格式化 Rec-Agent / Harness 输出")
    parser.add_argument("input", nargs="?", help="包含 Harness 输出的文本文件；省略时从 stdin 读取")
    parser.add_argument("--json-only", action="store_true", help="只输出缩进后的 JSON")
    args = parser.parse_args()

    text = Path(args.input).read_text(encoding="utf-8") if args.input else sys.stdin.read()
    payload = extract_json(text)
    formatted = json.dumps(payload, ensure_ascii=False, indent=2)

    if args.json_only:
        print(formatted)
        return

    print("用户画像")
    print("--------")
    profile = payload.get("user_profile") or {}
    print(f"用户 ID：{payload.get('user_id', '')}")
    print(f"城市：{profile.get('city', '')}（{profile.get('city_tier', '')}）")
    print(f"人生阶段：{profile.get('life_stage', '')}")
    print(f"偏好类目：{'、'.join(profile.get('preferred_categories', []))}")
    print(f"用户标签：{'、'.join(profile.get('tags', []))}")
    print()
    print("推荐卡片")
    print("--------")
    for index, rec in enumerate(payload.get("recommendations", []), start=1):
        print(f"{index}. {rec.get('title', '')}（{rec.get('item_id', '')}）")
        print(f"   曝光理由：{rec.get('exposure_reason', '')}")
        print(f"   支撑字段：{'、'.join(rec.get('evidence_fields', []))}")
        print(f"   上下文：{rec.get('context_summary', '')}")
        print()

    print("格式化 JSON")
    print("-----------")
    print(formatted)


if __name__ == "__main__":
    main()
