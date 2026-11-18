"""Canonical data contract shared by offline candidates, MCP and Jev facts."""

from __future__ import annotations

import csv
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping
from copy import deepcopy


ROOT = Path(__file__).resolve().parent
RAW = ROOT / "data" / "raw"
CANONICAL_SCHEMA_VERSION = "canonical-2026-06-15-v1"
_ITEM_ID_RE = re.compile(r"^(?:i|item)_(\d{4})$")


class CanonicalDataError(ValueError):
    """Raised when a record cannot be trusted as canonical data."""


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


def _normalize_user(row: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(row)
    for key in (
        "preferred_categories",
        "recent_cart_item_ids",
        "recent_order_item_ids",
        "last_search_terms",
        "tags",
    ):
        result[key] = _split(str(row.get(key, "")))
    for key in ("age", "account_age_days", "orders_90d"):
        if key in result:
            result[key] = _int(result[key])
    if "aov_90d" in result:
        result["aov_90d"] = _float(result["aov_90d"])
    if "night_owl" in result:
        result["night_owl"] = str(result["night_owl"]).lower() == "true"
    return result


def _normalize_item(row: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(row)
    for key in (
        "functions",
        "promo_tags",
        "promo_rule_ids",
        "efficacy_claims_allowed",
        "qualifications",
    ):
        result[key] = _split(str(row.get(key, "")))
    for key in ("price_cents", "original_price_cents", "stock", "sales_30d"):
        if key in result:
            result[key] = _int(result[key])
    for key in ("rating", "return_rate_30d", "complaint_rate_30d"):
        if key in result:
            result[key] = _float(result[key])
    if "sensitive_category" in result:
        result["sensitive_category"] = str(result["sensitive_category"]).lower() == "true"
    return result


@lru_cache(maxsize=1)
def _load_users() -> dict[str, dict[str, Any]]:
    with (RAW / "users.csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = {_row["user_id"]: _normalize_user(_row) for _row in csv.DictReader(handle)}
    return rows


@lru_cache(maxsize=1)
def _load_items() -> dict[str, dict[str, Any]]:
    with (RAW / "items.csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = {_row["item_id"]: _normalize_item(_row) for _row in csv.DictReader(handle)}
    for item in rows.values():
        validate_canonical_item(item)
    return rows


@lru_cache(maxsize=1)
def _load_promos() -> list[dict[str, Any]]:
    return json.loads((RAW / "promo_rules.json").read_text(encoding="utf-8"))


def load_canonical_users() -> dict[str, dict[str, Any]]:
    return deepcopy(_load_users())


def load_canonical_items() -> dict[str, dict[str, Any]]:
    return deepcopy(_load_items())


def load_canonical_promos() -> list[dict[str, Any]]:
    return deepcopy(_load_promos())


def load_canonical_climate() -> dict[str, Any]:
    return json.loads((RAW / "city_climate.json").read_text(encoding="utf-8"))


def canonical_promo_snapshot(item: Mapping[str, Any], *, as_of: str) -> dict[str, Any]:
    """Freeze the first assigned promotion with its scope and item/date eligibility."""
    ids = item.get("promo_rule_ids") or []
    if not ids:
        return {}
    rule = next(row for row in load_canonical_promos() if row["rule_id"] == ids[0])
    scope = rule.get("scope") or {}
    return {
        "promo_id": rule["rule_id"], "type": rule["type"], "title": rule["title"],
        "applicable": bool(rule["start"] <= as_of <= rule["end"] and scope and all(item.get(k) in values for k, values in scope.items())),
        "scope": deepcopy(scope), "start": rule["start"], "end": rule["end"],
        "threshold_cents": rule["threshold_cents"], "discount_cents": rule["discount_cents"],
        "discount_percent": rule["discount_percent"],
        "discount_rate": rule["discount_percent"] / 100 if rule["discount_percent"] else 0,
        "gift_item": rule["gift"], "fine_print": rule["fine_print"],
        "computed_by": "canonical_fixture_rule_engine_v2",
    }


def normalize_item_id(value: str, *, legacy_item: Mapping[str, Any] | None = None) -> str:
    """Return a verified canonical ID, accepting one legacy ID at an explicit boundary."""

    match = _ITEM_ID_RE.fullmatch(str(value).strip())
    if not match:
        raise CanonicalDataError(f"invalid item_id: {value!r}")
    canonical_id = f"i_{match.group(1)}"
    canonical = load_canonical_items().get(canonical_id)
    if canonical is None:
        raise CanonicalDataError(f"unknown item_id: {value!r}")
    if str(value).startswith("i_"):
        return canonical_id
    if legacy_item is None:
        raise CanonicalDataError(
            f"legacy item_id {value!r} requires title and brand identity for migration"
        )
    for field in ("title", "brand"):
        if field not in legacy_item or not str(legacy_item.get(field, "")).strip():
            raise CanonicalDataError(f"legacy item_id {value!r} requires {field} identity for migration")
    legacy_suffix = legacy_item.get("item_id") or legacy_item.get("id")
    if legacy_suffix is not None:
        suffix_match = _ITEM_ID_RE.fullmatch(str(legacy_suffix).strip())
        if not suffix_match or suffix_match.group(1) != match.group(1):
            raise CanonicalDataError(f"item_id suffix mismatch for {value!r}")
    for field in ("title", "brand"):
        if str(legacy_item[field]).strip() != str(canonical.get(field, "")).strip():
            raise CanonicalDataError(f"{field} mismatch for {value!r}")
    return canonical_id


def validate_canonical_item(item: Mapping[str, Any]) -> dict[str, Any]:
    item_id = str(item.get("item_id", ""))
    if not re.fullmatch(r"i_\d{4}", item_id):
        raise CanonicalDataError(f"invalid canonical item_id: {item_id!r}")
    for field in ("title", "brand", "category_l1", "price_cents", "stock"):
        if field not in item or item[field] in (None, ""):
            raise CanonicalDataError(f"missing canonical item field: {field}")
    if not isinstance(item["price_cents"], int) or isinstance(item["price_cents"], bool):
        raise CanonicalDataError("price_cents must be an integer number of cents")
    if not isinstance(item["stock"], int) or isinstance(item["stock"], bool):
        raise CanonicalDataError("stock must be an integer")
    return dict(item)


def canonical_metadata() -> dict[str, str]:
    return {"schema_version": CANONICAL_SCHEMA_VERSION, "data_source": "data/raw"}
