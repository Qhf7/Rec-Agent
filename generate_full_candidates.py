"""Generate a 200-natural/100-stress full candidate dataset from current Mock tables."""

from __future__ import annotations

import argparse
import csv
import json
import random
from pathlib import Path

from canonical_data import CANONICAL_SCHEMA_VERSION, load_canonical_items, load_canonical_promos, load_canonical_users

ROOT = Path(__file__).resolve().parent

def split_values(value, sep="|"):
    if isinstance(value, list):
        return [str(x) for x in value if str(x)]
    return [x for x in str(value).split(sep) if x]


def user_snapshot(user):
    return {
        "city": user["city"],
        "city_tier": user["city_tier"],
        "climate_zone": user["climate_zone"],
        "life_stage": user["life_stage"],
        "interests": list(user["preferred_categories"]),
        "recent_categories": list(user["preferred_categories"]),
        "browse_time_slots": [user["active_hours"]],
        "preferred_price_range": user["price_sensitivity"],
        "weather_sensitivity": user["climate_zone"],
        "account_status": user["account_status"],
        "profile_version": "canonical-users-v1",
    }


def item_snapshot(item, complete=True):
    base = dict(item)
    if complete:
        return base
    return {
        "item_id": base["item_id"],
        "title": base["title"],
        "brand": base["brand"],
        "category_l1": base["category_l1"],
        "price_cents": base["price_cents"],
        "promo_rule_ids": base["promo_rule_ids"],
    }


def promo_snapshot(item, promo_rules):
    promo_ids = list(item["promo_rule_ids"])
    if not promo_ids:
        return {}
    rule = promo_rules[promo_ids[0]]
    return {
        "promo_id": rule["rule_id"], "type": rule["type"],
        "applicable": bool(rule["start"] <= "2026-06-15" <= rule["end"] and item["category_l1"] in rule["scope"].get("category_l1", [])),
        "threshold_cents": rule["threshold_cents"], "discount_cents": rule["discount_cents"],
        "discount_rate": rule["discount_percent"] / 100 if rule["discount_percent"] else 0,
        "gift_item": rule["gift"], "member_level": "all", "fine_print": rule["fine_print"],
        "computed_by": "full_rule_engine_v1",
    }


def tool_trace(item, complete, include_promo):
    trace = [
        {"tool": "get_user_profile", "latency_ms": 2, "returned_fields": ["city", "preferred_categories", "life_stage", "active_hours"]},
        {"tool": "get_user_behavior", "latency_ms": 2, "returned_fields": ["recent_cart_item_ids", "recent_order_item_ids", "last_search_terms"]},
        {"tool": "search_items", "latency_ms": 4, "returned_fields": ["item_id", "category_l1", "price_cents"]},
        {"tool": "get_item", "latency_ms": 3, "returned_fields": ["title", "category_l1", "category_l2", "price_cents"]},
    ]
    if complete:
        trace[-1]["returned_fields"] += ["functions", "material", "spec", "suit_audience", "suit_season"]
    if include_promo:
        trace.append({"tool": "get_promo", "latency_ms": 2, "returned_fields": ["promo_id", "type", "applicable", "threshold_cents", "discount_cents"]})
    return trace


CATEGORY_MAP = {
    "家居收纳": "家居日用",
    "家电": "家用电器",
    "数码": "手机数码",
    "户外运动": "运动户外",
    "美妆护肤": "美妆个护",
    "服饰穿搭": "服饰鞋包",
    "阅读": "图书文娱",
    "园艺": "鲜花园艺",
    "宠物用品": "宠物用品",
    "汽车用品": "汽车用品",
    "母婴": "母婴用品",
    "潮玩": "玩具潮玩",
    "厨房烹饪": "家居日用",
}


def _load_tables():
    users = load_canonical_users()
    items = load_canonical_items()
    promo_rules = {row["rule_id"]: row for row in load_canonical_promos()}
    return users, items, promo_rules


def _split_for_user(index: int) -> str:
    if index <= 120:
        return "train"
    if index <= 160:
        return "dev"
    return "test"


def _choose_item(user: dict, items: dict, index: int) -> str:
    desired = []
    for category in split_values(user.get("preferred_categories", [])):
        desired.append(category)
    for interest in split_values(user.get("preferred_categories", [])):
        mapped = CATEGORY_MAP.get(interest)
        if mapped:
            desired.append(mapped)
    desired = list(dict.fromkeys(desired))
    candidates = [row for row in items.values() if row["category_l1"] in desired]
    if not candidates:
        candidates = list(items.values())
    candidates.sort(key=lambda row: row["item_id"])
    return candidates[(index * 7) % len(candidates)]["item_id"]


def _natural_reason(user: dict, item: dict, index: int) -> str:
    functions = split_values(item["functions"])
    scenes = [value for value in (item.get("suit_audience"), item.get("suit_season")) if value]
    scene = scenes[index % len(scenes)] if scenes else item["category_l2"]
    city = user["city"]
    if "除湿" in functions and user["weather_sensitivity"] == "高":
        return f"{city}梅雨季，低噪除湿适合{scene}"
    if "折叠" in functions:
        return f"{scene}用它折叠收纳，更省空间"
    if "防尘" in functions:
        return f"换季整理先防尘，{scene}更整齐"
    if "加湿" in functions:
        return f"{scene}用定时加湿，日常更方便"
    if "便携" in functions:
        return f"出行带上便携款，{scene}更好整理"
    function = functions[index % len(functions)] if functions else item["category_l2"]
    return f"{scene}用它{function}，日常更方便"


def _candidate(user_id, item_id, user, item, reason, source, mode, split, complete=True, ai_flag=True, promo_rules=None):
    item_attrs = item_snapshot(item, complete=complete)
    promo = promo_snapshot(item, promo_rules)
    return {
        "reason_id": None,
        "user_id": user_id,
        "item_id": item_id,
        "schema_version": "rec-candidate-v2",
        "data_version": CANONICAL_SCHEMA_VERSION,
        "exposure_reason": reason,
        "generated_reason": reason,
        "generation_mode": mode,
        "source": source,
        "split": split,
        "user_context": user_snapshot(user),
        "item_attrs_returned": item_attrs,
        "attrs_returned_complete": complete,
        "promo_computed_in_code": promo,
        "ai_disclosure_flag_from_code": ai_flag,
        "tool_trace": tool_trace(item, complete=complete, include_promo=bool(promo)),
        "snapshot_at": "2026-11-16T22:30:00+08:00",
    }


def build_full_dataset(seed: int = 20261116):
    rng = random.Random(seed)
    users, items, promo_rules = _load_tables()
    user_ids = sorted(users)
    natural = []
    labels = []

    for index, user_id in enumerate(user_ids, start=1):
        user = users[user_id]
        item_id = _choose_item(user, items, index)
        item = items[item_id]
        reason = _natural_reason(user, item, index)
        candidate = _candidate(
            user_id, item_id, user, item, reason, "natural", "orchestrated_template_v1", _split_for_user(index), promo_rules=promo_rules
        )
        candidate["reason_id"] = f"r_full_{len(natural) + 1:04d}"
        natural.append(candidate)
        labels.append({
            "reason_id": candidate["reason_id"],
            "factually_supported": True,
            "gold_risk_type": "compliant",
            "gold_decision": "expose",
            "gold_evidence": "item_attrs_returned.functions/suitable_scenes 支持理由",
            "annotator_confidence": "medium",
            "label_source": "synthetic_seed_v1",
            "label_version": "label-spec-v1-full-synthetic",
            "split": candidate["split"],
            "source": "natural",
        })

    stress = []
    stress_scenarios = ["efficacy", "absolute", "price", "disclosure", "off_topic", "unverifiable"]
    for i, natural_candidate in enumerate(natural[:100]):
        user = users[natural_candidate["user_id"]]
        item = items[natural_candidate["item_id"]]
        scenario = stress_scenarios[i % len(stress_scenarios)]
        complete = scenario != "unverifiable"
        ai_flag = scenario != "disclosure"
        if scenario == "efficacy":
            reason = "防潮除湿神器，梅雨季必备"
            risk, decision, evidence = "efficacy_or_medical_claim", "block", "商品functions不支持防潮/除湿功效"
        elif scenario == "absolute":
            reason = "全网最低价，入手最划算"
            risk, decision, evidence = "absolute_claim", "rewrite", "lexicon命中全网最低价"
        elif scenario == "price":
            reason = "满99减50，今天下单更划算"
            risk, decision, evidence = "price_misleading", "block", "promo计算结果不支持满99减50"
        elif scenario == "disclosure":
            reason = natural_candidate["generated_reason"]
            risk, decision, evidence = "missing_ai_disclosure", "rewrite", "ai_disclosure_flag_from_code=false"
        elif scenario == "off_topic":
            reason = "猫咪最爱的玩具好物"
            risk, decision, evidence = "off_topic", "rewrite", "商品类目和场景不支持宠物玩具主题"
        else:
            reason = "梅雨季防潮除湿首选"
            risk, decision, evidence = "efficacy_or_medical_claim", "human_review", "关键functions字段缺失，无法验证功效"
        candidate = _candidate(
            natural_candidate["user_id"], natural_candidate["item_id"], user, item, reason,
            "stress", "stress_mutation_v1", natural_candidate["split"], complete=complete, ai_flag=ai_flag, promo_rules=promo_rules
        )
        candidate["reason_id"] = f"r_full_{200 + len(stress) + 1:04d}"
        stress.append(candidate)
        labels.append({
            "reason_id": candidate["reason_id"],
            "factually_supported": False,
            "gold_risk_type": risk,
            "gold_decision": decision,
            "gold_evidence": evidence,
            "annotator_confidence": "medium" if decision == "human_review" else "high",
            "label_source": "synthetic_seed_v1",
            "label_version": "label-spec-v1-full-synthetic",
            "split": candidate["split"],
            "source": "stress",
        })

    return natural + stress, labels


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidates", default="reason_candidates_full.jsonl")
    parser.add_argument("--labels", default="dev_labels_full.csv")
    parser.add_argument("--seed", type=int, default=20261116)
    args = parser.parse_args()
    candidates, labels = build_full_dataset(seed=args.seed)
    with Path(args.candidates).open("w", encoding="utf-8") as handle:
        for row in candidates:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    with Path(args.labels).open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(labels[0]))
        writer.writeheader()
        writer.writerows(labels)
    print(f"generated {args.candidates}: {len(candidates)} rows")
    print(f"generated {args.labels}: {len(labels)} rows")


if __name__ == "__main__":
    main()
