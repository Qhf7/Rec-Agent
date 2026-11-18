"""Migrate legacy candidate JSON records to the canonical Rec-Agent contract."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from canonical_data import (
    CANONICAL_SCHEMA_VERSION,
    CanonicalDataError,
    load_canonical_items,
    load_canonical_users,
    normalize_item_id,
    validate_canonical_item,
    canonical_promo_snapshot,
)


CANDIDATE_SCHEMA_VERSION = "rec-candidate-v2"


def _normalize_candidate_reason(candidate: Mapping[str, Any]) -> tuple[str, str]:
    exposure = candidate.get("exposure_reason", candidate.get("generated_reason", ""))
    generated = candidate.get("generated_reason", exposure)
    if not isinstance(exposure, str) or not exposure.strip():
        raise ValueError("candidate requires exposure_reason or generated_reason")
    if not isinstance(generated, str) or generated != exposure:
        raise ValueError("generated_reason must equal exposure_reason")
    return exposure, generated


def validate_candidate_contract(
    candidate: Mapping[str, Any], *, replace_item_snapshot: bool = False
) -> dict[str, Any]:
    """Validate and normalize a canonical candidate without changing its facts."""

    if not isinstance(candidate, Mapping):
        raise ValueError("candidate must be an object")
    for field in ("reason_id", "user_id", "item_id"):
        if not isinstance(candidate.get(field), str) or not candidate[field].strip():
            raise ValueError(f"candidate requires {field}")
    if "attrs_returned_complete" in candidate and type(candidate["attrs_returned_complete"]) is not bool:
        raise ValueError("attrs_returned_complete must be boolean")
    evidence = candidate.get("evidence_fields", [])
    if not isinstance(evidence, list) or any(not isinstance(field, str) for field in evidence):
        raise ValueError("evidence_fields must be a list of strings")
    user_id = str(candidate["user_id"])
    if user_id not in load_canonical_users():
        raise ValueError(f"unknown user_id: {user_id}")
    item_id = normalize_item_id(str(candidate["item_id"]))
    item = validate_canonical_item(load_canonical_items()[item_id])
    exposure_reason, generated_reason = _normalize_candidate_reason(candidate)
    declared_schema = candidate.get("schema_version")
    if declared_schema != CANDIDATE_SCHEMA_VERSION:
        raise ValueError(f"schema_version mismatch: {declared_schema}")
    declared_version = candidate.get("data_version")
    if declared_version != CANONICAL_SCHEMA_VERSION:
        raise ValueError(f"data_version mismatch: {declared_version}")
    supplied_item = candidate.get("item_attrs_returned")
    if supplied_item is not None:
        if not isinstance(supplied_item, Mapping):
            raise ValueError("item_attrs_returned must be an object")
        for field, value in supplied_item.items():
            if field not in item or type(value) is not type(item[field]) or value != item[field]:
                raise ValueError(f"{field} mismatch for canonical candidate")
    scene = candidate.get("user_context") or {}
    if not isinstance(scene, Mapping):
        raise ValueError("user_context must be an object")
    user = load_canonical_users()[user_id]
    for field in ("city", "city_tier", "climate_zone", "life_stage", "tags", "active_hours"):
        if field in scene and scene[field] != user.get(field):
            raise ValueError(f"user_context.{field} mismatch for canonical candidate")
    supplied_promo = candidate.get("promo_computed_in_code") or {}
    if not isinstance(supplied_promo, Mapping):
        raise ValueError("promo_computed_in_code must be an object")
    if supplied_promo:
        snapshot_at = candidate.get("snapshot_at")
        if not isinstance(snapshot_at, str) or len(snapshot_at) < 10:
            raise ValueError("promo snapshot requires snapshot_at")
        expected_promo = canonical_promo_snapshot(item, as_of=snapshot_at[:10])
        for field, value in supplied_promo.items():
            if field not in expected_promo or type(value) is not type(expected_promo[field]) or value != expected_promo[field]:
                raise ValueError(f"promo.{field} mismatch for canonical candidate")
    normalized = deepcopy(dict(candidate))
    normalized.update(
        {
            "schema_version": CANDIDATE_SCHEMA_VERSION,
            "data_version": CANONICAL_SCHEMA_VERSION,
            "user_id": user_id,
            "item_id": item_id,
            "exposure_reason": exposure_reason,
            "generated_reason": generated_reason,
            "item_attrs_returned": deepcopy(item if replace_item_snapshot or supplied_item is None else dict(supplied_item)),
        }
    )
    normalized.setdefault("evidence_fields", [])
    normalized.setdefault("context_summary", "")
    normalized.setdefault("user_context", {})
    normalized.setdefault("promo_computed_in_code", {})
    normalized.setdefault("attrs_returned_complete", True)
    return normalized


def migrate_legacy_candidate(candidate: Mapping[str, Any]) -> dict[str, Any]:
    """Migrate one item_#### candidate after verifying title/brand identity."""

    item_id = str(candidate.get("item_id", ""))
    legacy_item = candidate.get("item_attrs_returned") or {}
    declared_version = candidate.get("data_version")
    if declared_version is not None and declared_version not in ("", CANONICAL_SCHEMA_VERSION):
        raise ValueError(f"data_version mismatch: {declared_version}")
    canonical_id = normalize_item_id(item_id, legacy_item=legacy_item)
    migrated = dict(candidate)
    migrated["item_id"] = canonical_id
    migrated["data_version"] = CANONICAL_SCHEMA_VERSION
    migrated["schema_version"] = CANDIDATE_SCHEMA_VERSION
    migrated["item_attrs_returned"] = load_canonical_items()[canonical_id]
    migrated["legacy_source"] = {
        "item_id": item_id,
        "format": "legacy-candidate-v1",
    }
    return validate_candidate_contract(migrated, replace_item_snapshot=True)


def migrate_jsonl(input_path: str | Path, output_path: str | Path) -> int:
    source_path, target_path = Path(input_path), Path(output_path)
    if source_path.resolve() == target_path.resolve():
        raise ValueError("input and output must be different files")
    count = 0
    temporary = None
    try:
        with source_path.open(encoding="utf-8") as source, tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=target_path.parent, delete=False
        ) as target:
            temporary = Path(target.name)
            for number, line in enumerate(source, 1):
                if not line.strip():
                    continue
                try:
                    migrated = migrate_legacy_candidate(json.loads(line))
                except (ValueError, TypeError) as exc:
                    raise ValueError(f"line {number}: {exc}") from exc
                target.write(json.dumps(migrated, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n")
                count += 1
        os.replace(temporary, target_path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", help="legacy candidate JSONL")
    parser.add_argument("output", help="canonical candidate JSONL")
    args = parser.parse_args()
    try:
        count = migrate_jsonl(args.input, args.output)
    except (CanonicalDataError, ValueError, json.JSONDecodeError) as exc:
        raise SystemExit(f"migration failed: {exc}") from exc
    print(f"migrated {count} candidates to {args.output}")


if __name__ == "__main__":
    main()
