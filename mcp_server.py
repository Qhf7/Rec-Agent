"""Read-only MCP data tools for the Rec-Agent Harness preset.

The server reads the canonical mock data under ``data/raw``. It never writes
workspace files and never calls the Jev API; Jev remains a downstream judge.
Run with ``python3 mcp_server.py`` for the default stdio transport.
"""

from __future__ import annotations

import csv
import json
import os
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from mcp.server.fastmcp import FastMCP


ROOT = Path(__file__).resolve().parent
RAW = ROOT / "data" / "raw"
SCENARIO_DATE = "2026-06-15"
TIMEZONE = "Asia/Shanghai"

mcp = FastMCP(
    "Rec-Agent Data Tools",
    instructions=(
        "Read-only user, behavior, item, promotion and session-context tools "
        "for the Rec-Agent recommendation preset. Do not mutate data or judge Jev exposure."
    ),
)


def _split(value: str | None) -> list[str]:
    return [part for part in (value or "").replace(";", "|").split("|") if part]


def _int(value: Any) -> int | Any:
    try:
        return int(value)
    except (TypeError, ValueError):
        return value


def _float(value: Any) -> float | Any:
    try:
        return float(value)
    except (TypeError, ValueError):
        return value


def _normalize_user(row: dict[str, str]) -> dict[str, Any]:
    result: dict[str, Any] = dict(row)
    for key in (
        "preferred_categories",
        "recent_cart_item_ids",
        "recent_order_item_ids",
        "last_search_terms",
        "tags",
    ):
        result[key] = _split(row.get(key))
    for key in ("age", "account_age_days", "orders_90d"):
        if key in result:
            result[key] = _int(result[key])
    if "aov_90d" in result:
        result["aov_90d"] = _float(result["aov_90d"])
    if "night_owl" in result:
        result["night_owl"] = result["night_owl"] == "true"
    return result


def _normalize_item(row: dict[str, str]) -> dict[str, Any]:
    result: dict[str, Any] = dict(row)
    for key in (
        "functions",
        "promo_tags",
        "promo_rule_ids",
        "efficacy_claims_allowed",
        "qualifications",
    ):
        result[key] = _split(row.get(key))
    for key in ("price_cents", "original_price_cents", "stock", "sales_30d"):
        if key in result:
            result[key] = _int(result[key])
    for key in ("rating", "return_rate_30d", "complaint_rate_30d"):
        if key in result:
            result[key] = _float(result[key])
    if "sensitive_category" in result:
        result["sensitive_category"] = result["sensitive_category"] == "true"
    return result


@lru_cache(maxsize=1)
def _users() -> dict[str, dict[str, Any]]:
    with (RAW / "users.csv").open(encoding="utf-8-sig", newline="") as handle:
        return {row["user_id"]: _normalize_user(row) for row in csv.DictReader(handle)}


@lru_cache(maxsize=1)
def _items() -> dict[str, dict[str, Any]]:
    with (RAW / "items.csv").open(encoding="utf-8-sig", newline="") as handle:
        return {row["item_id"]: _normalize_item(row) for row in csv.DictReader(handle)}


@lru_cache(maxsize=1)
def _promos() -> list[dict[str, Any]]:
    return json.loads((RAW / "promo_rules.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _climate() -> dict[str, Any]:
    return json.loads((RAW / "city_climate.json").read_text(encoding="utf-8"))


def _not_found(key: str, value: str) -> dict[str, Any]:
    return {"found": False, key: value}


@mcp.tool()
def get_user_profile(user_id: str) -> dict[str, Any]:
    """Return a normalized user profile, or found=false for an unknown user."""

    user = _users().get(user_id)
    if user is None:
        return _not_found("user_id", user_id)
    return {"found": True, **user}


@mcp.tool()
def get_user_behavior(user_id: str) -> dict[str, Any]:
    """Return behavior fields needed for personalized item selection."""

    user = _users().get(user_id)
    if user is None:
        return _not_found("user_id", user_id)
    keys = (
        "user_id",
        "city",
        "preferred_categories",
        "recent_cart_item_ids",
        "recent_order_item_ids",
        "last_search_terms",
        "tags",
        "night_owl",
        "active_hours",
        "price_sensitivity",
        "aov_90d",
    )
    return {"found": True, **{key: user.get(key) for key in keys}}


@mcp.tool()
def get_session_context() -> dict[str, Any]:
    """Return the fixed mock scenario date and the current local session time."""

    now = datetime.now(ZoneInfo(TIMEZONE))
    return {
        "scenario_date": SCENARIO_DATE,
        "timezone": TIMEZONE,
        "local_time": now.isoformat(timespec="seconds"),
        "city_climate_count": len(_climate()),
    }


@mcp.tool()
def get_item(item_id: str) -> dict[str, Any]:
    """Return one normalized item, or found=false for an unknown item."""

    item = _items().get(item_id)
    if item is None:
        return _not_found("item_id", item_id)
    return {"found": True, **item}


@mcp.tool()
def search_items(
    query: str = "",
    category_l1: str | None = None,
    limit: int = 10,
    in_stock_only: bool = True,
) -> list[dict[str, Any]]:
    """Search items by text/category and return a small ranked result set."""

    terms = [term.lower() for term in query.split() if term.strip()]
    candidates: list[tuple[int, dict[str, Any]]] = []
    for item in _items().values():
        if in_stock_only and int(item.get("stock", 0)) <= 0:
            continue
        if category_l1 and item.get("category_l1") != category_l1:
            continue
        haystack = " ".join(
            str(item.get(key, ""))
            for key in ("title", "brand", "category_l1", "category_l2", "category_l3", "functions", "spec")
        ).lower()
        if terms and not all(term in haystack for term in terms):
            continue
        exact = 100 if query and query.lower() in str(item.get("title", "")).lower() else 0
        score = exact + sum(haystack.count(term) for term in terms) * 10 + int(item.get("sales_30d", 0)) // 1000
        candidates.append((score, item))
    candidates.sort(key=lambda pair: (-pair[0], -int(pair[1].get("sales_30d", 0)), pair[1]["item_id"]))
    return [item for _, item in candidates[: max(0, min(limit, 50))]]


@mcp.tool()
def get_promo(
    item_id: str | None = None,
    rule_id: str | None = None,
    as_of: str = SCENARIO_DATE,
) -> dict[str, Any]:
    """Return promotion rules and whether they are active on the requested date."""

    item = _items().get(item_id) if item_id else None
    if item_id and item is None:
        return {"found": False, "item_id": item_id, "rules": [], "active": False, "as_of": as_of}
    ids = set(item.get("promo_rule_ids", [])) if item else None
    rules = [rule for rule in _promos() if (rule_id is None or rule.get("rule_id") == rule_id)]
    if ids is not None:
        rules = [rule for rule in rules if rule.get("rule_id") in ids]
    active_rules = [rule for rule in rules if rule.get("start", "") <= as_of <= rule.get("end", "")]
    return {
        "found": bool(rules),
        "item_id": item_id,
        "rule_id": rule_id,
        "as_of": as_of,
        "active": bool(active_rules),
        "rules": rules,
        "active_rules": active_rules,
    }


def main() -> None:
    transport = os.environ.get("MCP_TRANSPORT", "stdio")
    mcp.run(transport=transport)


if __name__ == "__main__":
    main()
