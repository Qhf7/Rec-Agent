"""Offline, strictly validated MCP tools used by the Agent benchmark."""
from __future__ import annotations

from copy import deepcopy
import re
import time
from typing import Any

from canonical_data import load_canonical_items
import mcp_server

SCENARIO_DATE = mcp_server.SCENARIO_DATE
TOOL_NAMES = ("get_user_profile", "get_user_behavior", "get_user_recommendation_history", "get_session_context", "search_items", "get_item", "get_promo")


def tool_schemas() -> list[dict[str, Any]]:
    """Return standard OpenAI function tools; additional arguments are forbidden."""
    uid = {"type": "string", "pattern": r"^u_[0-9]{4}$"}
    iid = {"type": "string", "pattern": r"^i_[0-9]{4}$"}
    date = {"type": "string", "enum": [SCENARIO_DATE]}
    categories = sorted({x["category_l1"] for x in load_canonical_items().values()})
    definitions = [
        ("get_user_profile", "Read the target user's profile; found=false means unknown user.", {"user_id": uid}, ["user_id"]),
        ("get_user_behavior", "Read shopping behavior and category preferences.", {"user_id": uid}, ["user_id"]),
        ("get_user_recommendation_history", "Read exposure/click history at the fixed scenario date; no history is normal.", {"user_id": uid, "days": {"type": "integer", "minimum": 1, "maximum": 365}, "limit": {"type": "integer", "minimum": 0, "maximum": 100}, "as_of": date}, ["user_id"]),
        ("get_session_context", "Read the benchmark's fixed date and scene context.", {}, []),
        ("search_items", "Search canonical products. Whitespace-separated terms use AND matching.", {"query": {"type": "string", "maxLength": 120}, "category_l1": {"type": ["string", "null"], "enum": categories + [None]}, "limit": {"type": "integer", "minimum": 1, "maximum": 50}, "in_stock_only": {"type": "boolean"}}, []),
        ("get_item", "Read one product's facts before recommending it.", {"item_id": iid}, ["item_id"]),
        ("get_promo", "Read promotion rules at the fixed scenario date.", {"item_id": {**iid, "type": ["string", "null"]}, "rule_id": {"type": ["string", "null"], "pattern": r"^P[0-9]{3}$"}, "as_of": date}, []),
    ]
    return [{"type": "function", "function": {"name": name, "description": desc, "parameters": {"type": "object", "properties": deepcopy(props), "required": required, "additionalProperties": False}}} for name, desc, props, required in definitions]


def validate_arguments(name: str, arguments: Any, task: dict | None = None) -> None:
    """Raise ValueError for invalid names, extras, coercions, IDs or boundaries."""
    definition = next((x["function"] for x in tool_schemas() if x["function"]["name"] == name), None)
    if definition is None:
        raise ValueError("unknown tool")
    if not isinstance(arguments, dict):
        raise ValueError("arguments must be an object")
    schema = definition["parameters"]
    if set(arguments) - set(schema["properties"]):
        raise ValueError("unexpected argument")
    if set(schema["required"]) - set(arguments):
        raise ValueError("missing required argument")
    for key, value in arguments.items():
        spec = schema["properties"][key]
        types = spec["type"] if isinstance(spec["type"], list) else [spec["type"]]
        valid_type = any((t == "null" and value is None) or (t == "string" and isinstance(value, str)) or (t == "integer" and type(value) is int) or (t == "boolean" and type(value) is bool) for t in types)
        if not valid_type:
            raise ValueError(f"invalid type for {key}")
        if "enum" in spec and value not in spec["enum"]:
            raise ValueError(f"invalid enum for {key}")
        if value is None:
            continue
        if "pattern" in spec and re.fullmatch(spec["pattern"], value) is None:
            raise ValueError(f"invalid ID for {key}")
        if isinstance(value, str) and (len(value) > spec.get("maxLength", 10000) or any(ord(c) < 32 for c in value)):
            raise ValueError(f"invalid string for {key}")
        if type(value) is int and not spec.get("minimum", value) <= value <= spec.get("maximum", value):
            raise ValueError(f"out of bounds for {key}")
    if task and "user_id" in arguments and arguments["user_id"] != task["user_id"]:
        raise ValueError("user_id must match the task user")


class ToolExecutor:
    """Execute MCP functions locally, recording every attempted call.

    call() returns {ok, result, error?}; calls stores the unwrapped result.
    Invalid and over-budget attempts count against max_tool_calls. Faults are
    one-shot and deterministic, and are recorded in both result and trace.
    """

    def __init__(self, task: dict):
        self.task = deepcopy(task)
        self.calls: list[dict] = []
        self.faults: list[dict] = []
        self._injected = False

    @property
    def budget_exceeded(self) -> bool:
        return len(self.calls) > int(self.task.get("max_tool_calls", 12))

    def call(self, name: str, arguments: dict) -> dict:
        started = time.perf_counter()
        record = {"name": name, "arguments": deepcopy(arguments), "result": None, "valid_parameters": False, "duration_seconds": 0.0}
        self.calls.append(record)
        try:
            validate_arguments(name, arguments, self.task)
            record["valid_parameters"] = True
            if self.budget_exceeded:
                raise RuntimeError("tool call budget exceeded")
            scenario = self.task.get("scenario")
            fault = None
            if not self._injected and scenario in ("empty_search", "tool_timeout") and name == "search_items":
                self._injected = True
                fault = {"scenario": scenario, "call_index": len(self.calls) - 1, "tool": name}
                self.faults.append(fault)
                record["fault"] = fault
                if scenario == "tool_timeout":
                    raise TimeoutError("injected search timeout; retry or simplify the query")
                value = []
            else:
                value = deepcopy(getattr(mcp_server, name)(**arguments))
                if name == "get_session_context":
                    value["local_time"] = SCENARIO_DATE + "T12:00:00+08:00"
                if not self._injected and scenario == "missing_item_fields" and name == "get_item" and value.get("found"):
                    self._injected = True
                    for key in ("functions", "material", "spec"):
                        value.pop(key, None)
                    fault = {"scenario": scenario, "call_index": len(self.calls) - 1, "tool": name, "removed_fields": ["functions", "material", "spec"]}
                    self.faults.append(fault)
                    record["fault"] = fault
            record["result"] = value
            response = {"ok": True, "result": deepcopy(value)}
            if fault:
                response["fault"] = fault
            return response
        except Exception as exc:
            error = {"type": type(exc).__name__, "message": str(exc)}
            record["error"] = error
            return {"ok": False, "result": None, "error": error}
        finally:
            record["duration_seconds"] = round(time.perf_counter() - started, 6)
