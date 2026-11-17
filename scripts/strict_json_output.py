#!/usr/bin/env python3
"""Extract the last complete strict JSON value from Harness output.

Harness may display tool previews, progress text, or several JSON-like blocks
around the final answer. This utility accepts only values that Python's strict
JSON parser accepts and prints one normalized JSON document.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterator


def _balanced_json_candidates(text: str) -> Iterator[tuple[int, int, str]]:
    for start, first in enumerate(text):
        if first not in "[{":
            continue
        stack: list[str] = []
        quote = False
        escape = False
        pairs = {"{": "}", "[": "]"}
        for index in range(start, len(text)):
            char = text[index]
            if quote:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == '"':
                    quote = False
                continue
            if char == '"':
                quote = True
            elif char in "[{":
                stack.append(char)
            elif char in "]}":
                if not stack or pairs[stack[-1]] != char:
                    break
                stack.pop()
                if not stack:
                    yield start, index + 1, text[start : index + 1]
                    break


def extract_last_json(text: str) -> Any:
    """Return the last complete strict JSON object or array in ``text``."""

    candidates: list[tuple[int, int, Any]] = []
    for start, end, candidate in _balanced_json_candidates(text):
        try:
            value = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(value, (dict, list)):
            candidates.append((end, start, value))
    if not candidates:
        raise ValueError("未找到完整的严格 JSON 对象或数组")
    candidates.sort(key=lambda pair: (pair[0], pair[1]))
    return candidates[-1][2]


def main() -> None:
    parser = argparse.ArgumentParser(description="从 Harness 整段输出中提取最后一个严格 JSON")
    parser.add_argument("input", nargs="?", help="包含 Harness 输出的文本文件；省略时从 stdin 读取")
    args = parser.parse_args()
    text = Path(args.input).read_text(encoding="utf-8") if args.input else sys.stdin.read()
    payload = extract_last_json(text)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
