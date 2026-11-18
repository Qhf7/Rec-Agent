"""Migrate legacy candidate JSON records to the canonical Rec-Agent contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from canonical_data import (
    CANONICAL_SCHEMA_VERSION,
    CanonicalDataError,
    load_canonical_items,
    load_canonical_users,
    normalize_item_id,
    validate_canonical_item,
)


CANDIDATE_SCHEMA_VERSION = "rec-candidate-v2"


def _normalize_candidate_reason(candidate: Mapping[str, Any]) -> tuple[str, str]:
    exposure = str(candidate.get("exposure_reason") or candidate.get("generated_reason") or "").strip()
    generated = str(candidate.get("generated_reason") or exposure).strip()
    if not exposure:
        raise ValueError("candidate requires exposure_reason or generated_reason")
    if generated != exposure:
        raise ValueError("generated_reason must equal exposure_reason")
    return exposure, generated


def validate_candidate_contract(candidate: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and normalize a canonical candidate without changing its facts."""

    for field in ("reason_id", "user_id", "item_id"):
        if not candidate.get(field):
            raise ValueError(f"candidate requires {field}")
    user_id = str(candidate["user_id"])
    if user_id not in load_canonical_users():
        raise ValueError(f"unknown user_id: {user_id}")
    item_id = normalize_item_id(str(candidate["item_id"]))
    item = validate_canonical_item(load_canonical_items()[item_id])
    exposure_reason, generated_reason = _normalize_candidate_reason(candidate)
    normalized = dict(candidate)
    normalized.update(
        {
            "schema_version": CANDIDATE_SCHEMA_VERSION,
            "data_version": CANONICAL_SCHEMA_VERSION,
            "user_id": user_id,
            "item_id": item_id,
            "exposure_reason": exposure_reason,
            "generated_reason": generated_reason,
            "item_attrs_returned": item,
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
    canonical_id = normalize_item_id(item_id, legacy_item=legacy_item)
    migrated = dict(candidate)
    migrated["item_id"] = canonical_id
    migrated["legacy_source"] = {
        "item_id": item_id,
        "format": "legacy-candidate-v1",
    }
    return validate_candidate_contract(migrated)


def migrate_jsonl(input_path: str | Path, output_path: str | Path) -> int:
    count = 0
    with Path(input_path).open(encoding="utf-8") as source, Path(output_path).open("w", encoding="utf-8") as target:
        for line in source:
            if not line.strip():
                continue
            migrated = migrate_legacy_candidate(json.loads(line))
            target.write(json.dumps(migrated, ensure_ascii=False, separators=(",", ":")) + "\n")
            count += 1
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
