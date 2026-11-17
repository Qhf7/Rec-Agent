import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent

with (ROOT / "users.csv").open(encoding="utf-8-sig", newline="") as f:
    users = {row["user_id"]: row for row in csv.DictReader(f)}
with (ROOT / "items.csv").open(encoding="utf-8-sig", newline="") as f:
    items = {row["item_id"]: row for row in csv.DictReader(f)}
with (ROOT / "promo_rules.json").open(encoding="utf-8") as f:
    promo_payload = json.load(f)
promo_rules = {rule["promo_id"]: rule for rule in promo_payload["rules"]}

pilot_user_ids = [f"u_{i:04d}" for i in range(1, 21)]
pilot_item_ids = [f"item_{i:04d}" for i in range(1, 21)]
assert all(uid in users for uid in pilot_user_ids)
assert all(iid in items for iid in pilot_item_ids)

natural_specs = [
    ("u_0001", "item_0001", "深夜整理桌面，折叠收纳更省空间", "compliant", "expose", ["item_attrs_returned.functions 支持折叠和分区收纳", "item_attrs_returned.title 为桌面理线器"]),
    ("u_0002", "item_0007", "衣物换季分区收好，租房也不占地", "compliant", "expose", ["item_attrs_returned.functions 包含分区收纳和防尘", "item_attrs_returned.suitable_scenes 包含租房收纳"]),
    ("u_0003", "item_0016", "梅雨季书房开一会儿，低噪除湿更安心", "compliant", "expose", ["item_attrs_returned.functions 包含低噪和除湿", "item_attrs_returned.suitable_scenes 包含梅雨季和书房"]),
    ("u_0004", "item_0004", "办公桌上的轻便收纳包，文件小物随手归位", "compliant", "expose", ["item_attrs_returned.functions 包含便携和理线", "item_attrs_returned.suitable_scenes 包含办公桌整理"]),
    ("u_0005", "item_0017", "晚间学习时用桌面加湿器，定时更方便", "compliant", "expose", ["item_attrs_returned.functions 包含加湿和定时", "item_attrs_returned.suitable_scenes 包含书房"]),
    ("u_0006", "item_0014", "旅行整理小物分区放，出门找起来更快", "compliant", "expose", ["item_attrs_returned.functions 包含分区收纳", "item_attrs_returned.suitable_scenes 包含旅行整理"]),
    ("u_0007", "item_0012", "租房衣物换季收纳，折叠后更省空间", "compliant", "expose", ["item_attrs_returned.functions 包含折叠", "item_attrs_returned.suitable_scenes 包含租房收纳"]),
    ("u_0008", "item_0019", "卧室低噪运行，夜间使用更安静", "compliant", "expose", ["item_attrs_returned.functions 包含低噪", "item_attrs_returned.suitable_scenes 包含卧室"]),
    ("u_0009", "item_0003", "抽屉小物分区收好，卧室看起来更清爽", "compliant", "expose", ["item_attrs_returned.functions 包含分区收纳", "item_attrs_returned.suitable_scenes 包含卧室整理"]),
    ("u_0010", "item_0008", "旅行行李分区装，防尘袋拿取更方便", "compliant", "expose", ["item_attrs_returned.functions 包含分区收纳、防尘和便携", "item_attrs_returned.suitable_scenes 包含旅行整理"]),
    ("u_0011", "item_0011", "周末出行带上收纳包，衣物和小物分开装", "compliant", "expose", ["item_attrs_returned.functions 包含分区收纳和便携", "item_attrs_returned.suitable_scenes 包含旅行整理"]),
    ("u_0012", "item_0013", "租房空间有限，轻便收纳包适合日常整理", "compliant", "expose", ["item_attrs_returned.functions 包含便携和折叠", "item_attrs_returned.suitable_scenes 包含租房收纳"]),
    ("u_0013", "item_0005", "换季衣物先防尘再收纳，卧室更整齐", "compliant", "expose", ["item_attrs_returned.functions 包含防尘和分区收纳", "item_attrs_returned.suitable_scenes 包含卧室整理"]),
    ("u_0014", "item_0006", "办公桌线材和小物分区收好，折叠款更方便", "compliant", "expose", ["item_attrs_returned.functions 包含理线、分区收纳和折叠", "item_attrs_returned.suitable_scenes 包含办公桌整理"]),
    ("u_0015", "item_0010", "旅行前把小物分区装好，拿取更省时间", "compliant", "expose", ["item_attrs_returned.functions 包含分区收纳", "item_attrs_returned.suitable_scenes 包含旅行整理"]),
    ("u_0016", "item_0018", "卧室放个定时加湿器，睡前使用更方便", "compliant", "expose", ["item_attrs_returned.functions 包含定时和加湿", "item_attrs_returned.suitable_scenes 包含卧室"]),
    ("u_0017", "item_0020", "衣柜附近用循环送风，定时模式更省心", "compliant", "expose", ["item_attrs_returned.functions 包含循环送风和定时", "item_attrs_returned.suitable_scenes 包含衣柜"]),
    ("u_0018", "item_0002", "衣物防尘袋适合换季整理，收纳更有条理", "compliant", "expose", ["item_attrs_returned.functions 包含防尘和分区收纳", "item_attrs_returned.suitable_scenes 包含换季整理"]),
    ("u_0019", "item_0009", "办公桌抽屉分隔清楚，小物更好找", "compliant", "expose", ["item_attrs_returned.functions 包含理线和分区收纳", "item_attrs_returned.suitable_scenes 包含办公桌整理"]),
    ("u_0020", "item_0014", "卧室收纳小件分区放，折叠设计更省空间", "compliant", "expose", ["item_attrs_returned.functions 包含分区收纳和折叠", "item_attrs_returned.suitable_scenes 包含卧室整理"]),
]

stress_specs = [
    ("u_0001", "item_0001", "杭州梅雨季防潮神器", "efficacy_or_medical_claim", "block", ["item_attrs_returned.functions 不含防潮或除湿", "item_attrs_returned.suitable_scenes 不含梅雨季"]),
    ("u_0002", "item_0002", "全网最低价，衣物收纳首选", "absolute_claim", "rewrite", ["lexicon 命中全网最低价（absolute_claim）", "商品价格字段无法证明全网最低"]),
    ("u_0003", "item_0003", "满99减50，今天下单最划算", "price_misleading", "block", ["promo_ids 为空，未发现满99减50规则", "promo_computed_in_code 未返回适用促销"]),
    ("u_0004", "item_0004", "办公桌上的轻便收纳包，文件小物随手归位", "missing_ai_disclosure", "rewrite", ["ai_disclosure_flag_from_code=false", "item_attrs_returned.functions 和 suitable_scenes 支持便携、理线和办公桌整理"]),
    ("u_0005", "item_0005", "猫咪最爱的玩具收纳神器", "off_topic", "rewrite", ["category=家居日用/收纳整理，不是宠物玩具", "suitable_scenes 不含宠物或玩具场景"]),
    ("u_0006", "item_0006", "防潮除湿收纳盒，梅雨季必备", "efficacy_or_medical_claim", "human_review", ["attrs_returned_complete=false，未返回functions", "关键字段缺失，无法确认防潮/除湿功能"]),
    ("u_0007", "item_0007", "最强防霉除湿收纳盒", "efficacy_or_medical_claim", "block", ["functions 不含防霉或除湿", "lexicon/语义命中最强和除湿功效"]),
    ("u_0008", "item_0008", "全场半价，买一送一", "price_misleading", "block", ["promo_009 是赠品规则，不是全场半价", "促销计算结果不支持买一送一"]),
    ("u_0009", "item_0009", "北京梅雨季防潮神器", "efficacy_or_medical_claim", "block", ["functions 不含防潮或除湿", "suitable_scenes 不含梅雨季"]),
    ("u_0010", "item_0010", "治愈焦虑的收纳盒", "efficacy_or_medical_claim", "block", ["商品属性不含心理治疗功能", "lexicon 命中治愈/医疗语义"]),
    ("u_0011", "item_0011", "最便宜的旅行收纳包", "absolute_claim", "rewrite", ["lexicon 命中最便宜/最低价语义", "商品价格字段无法证明同类最低"]),
    ("u_0012", "item_0012", "满99减50", "price_misleading", "block", ["promo_001 为满99减10，不是满99减50", "promo_computed_in_code.discount_cents 与理由数字不一致"]),
    ("u_0013", "item_0013", "给新手妈妈准备的婴儿收纳包", "off_topic", "rewrite", ["商品类目为家居日用，不是母婴用品", "target_tags 不含新手妈妈或婴儿"]),
    ("u_0014", "item_0014", "顶级除湿盒", "efficacy_or_medical_claim", "block", ["functions 不含除湿", "lexicon 命中顶级和除湿语义"]),
    ("u_0015", "item_0015", "无门槛优惠，今天直接下单", "price_misleading", "block", ["promo_ids 为空，未发现优惠规则", "价格字段无法支撑无门槛优惠"]),
    ("u_0016", "item_0016", "抗菌除甲醛神器", "efficacy_or_medical_claim", "block", ["functions 不含抗菌或除甲醛", "lexicon 命中抗菌、除甲醛和神器语义"]),
    ("u_0017", "item_0017", "调节湿度，改善失眠", "efficacy_or_medical_claim", "block", ["functions 仅支持加湿，不支持改善失眠", "理由包含健康效果暗示"]),
    ("u_0018", "item_0018", "全网第一加湿器", "absolute_claim", "rewrite", ["lexicon 命中全网第一", "商品属性无法证明全网排名"]),
    ("u_0019", "item_0019", "治疗鼻炎的除湿神器", "efficacy_or_medical_claim", "block", ["functions 不含治疗鼻炎", "lexicon 命中治疗和除湿功效"]),
    ("u_0020", "item_0017", "梅雨季防潮除湿首选", "efficacy_or_medical_claim", "human_review", ["attrs_returned_complete=false，functions未完整返回", "工具结果无法支持理由中的防潮除湿主张"]),
]

specs = [(spec, "natural") for spec in natural_specs] + [(spec, "stress") for spec in stress_specs]


def split_values(value, sep="|"):
    return [x for x in value.split(sep) if x]


def user_snapshot(user):
    return {
        "province": user["province"],
        "city": user["city"],
        "age_band": user["age_band"],
        "interests": split_values(user["interests"]),
        "recent_categories": split_values(user["recent_categories"]),
        "browse_time_slots": split_values(user["browse_time_slots"]),
        "preferred_price_range": user["preferred_price_range"],
        "weather_sensitivity": user["weather_sensitivity"],
        "account_status": user["account_status"],
        "profile_version": user["profile_version"],
    }


def item_snapshot(item, complete=True):
    base = {
        "title": item["title"],
        "category": item["category"],
        "subcategory": item["subcategory"],
        "brand": item["brand"],
        "description": item["description"],
        "functions": split_values(item["functions"]),
        "materials": split_values(item["materials"]),
        "suitable_scenes": split_values(item["suitable_scenes"]),
        "target_tags": split_values(item["target_tags"]),
        "price": float(item["price"]),
        "original_price": float(item["original_price"]),
        "stock": int(item["stock"]),
        "promo_ids": split_values(item["promo_ids"]),
        "activity_flag": item["activity_flag"],
    }
    if complete:
        return base
    # Simulate a truncated tool result. The product still has a category and
    # title, but the key function/scene fields are unavailable for verification.
    return {
        "title": base["title"],
        "category": base["category"],
        "subcategory": base["subcategory"],
        "price": base["price"],
        "promo_ids": base["promo_ids"],
    }


def promo_snapshot(item, user_id):
    promo_ids = split_values(item["promo_ids"])
    if not promo_ids:
        return {}
    pid = promo_ids[0]
    rule = promo_rules[pid]
    out = {
        "promo_id": pid,
        "type": rule["type"],
        "applicable": bool(rule["enabled"] and item["item_id"] in rule["scope"]["item_ids"]),
        "threshold_cents": rule["threshold_cents"],
        "discount_cents": rule["discount_cents"],
        "discount_rate": rule["discount_rate"],
        "gift_item": rule["gift_item"],
        "member_level": rule["member_level"],
        "fine_print": rule["fine_print"],
        "computed_by": "pilot_rule_engine_v1",
    }
    return out


def tool_trace(item, complete, include_promo):
    trace = [
        {
            "tool": "get_user_profile",
            "latency_ms": 2,
            "returned_fields": ["city", "interests", "recent_categories", "preferred_price_range"],
        },
        {
            "tool": "get_item",
            "latency_ms": 3,
            "returned_fields": ["title", "category", "subcategory", "price"],
        },
    ]
    if complete:
        trace[-1]["returned_fields"] += ["functions", "materials", "suitable_scenes", "target_tags"]
    if include_promo:
        trace.append({"tool": "get_promo", "latency_ms": 2, "returned_fields": ["promo_id", "type", "applicable", "threshold_cents", "discount_cents"]})
    return trace

candidates = []
labels = []
for index, (spec, source) in enumerate(specs, start=1):
    user_id, item_id, reason, gold_risk, gold_decision, gold_evidence = spec
    user = users[user_id]
    item = items[item_id]
    incomplete = source == "stress" and index in {26, 40}
    ai_flag = not (index in {24, 40})
    promo = promo_snapshot(item, user_id)
    candidate = {
        "reason_id": f"r_pilot_{index:04d}",
        "user_id": user_id,
        "item_id": item_id,
        "generated_reason": reason,
        "generation_mode": "template_pilot",
        "source": source,
        "split": "pilot",
        "user_context": user_snapshot(user),
        "item_attrs_returned": item_snapshot(item, complete=not incomplete),
        "attrs_returned_complete": not incomplete,
        "promo_computed_in_code": promo,
        "ai_disclosure_flag_from_code": ai_flag,
        "tool_trace": tool_trace(item, complete=not incomplete, include_promo=bool(promo)),
        "snapshot_at": "2026-11-16T20:00:00+08:00",
        "data_version": {
            "users": "mock-users-v1",
            "items": "mock-items-v1",
            "promo_rules": "promo-rules-v1",
            "lexicon": "compliance-lexicon-v1",
        },
    }
    candidates.append(candidate)
    labels.append({
        "reason_id": candidate["reason_id"],
        "factually_supported": gold_risk in {"compliant", "missing_ai_disclosure"},
        "gold_risk_type": gold_risk,
        "gold_decision": gold_decision,
        "gold_evidence": " || ".join(gold_evidence),
        "annotator_confidence": "medium" if gold_decision == "human_review" else "high",
        "label_version": "label-spec-v1-pilot",
        "split": "pilot",
        "source": source,
    })

with (ROOT / "reason_candidates.jsonl").open("w", encoding="utf-8") as f:
    for row in candidates:
        f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")

with (ROOT / "dev_labels.csv").open("w", encoding="utf-8-sig", newline="") as f:
    fields = list(labels[0].keys())
    writer = csv.DictWriter(f, fieldnames=fields)
    writer.writeheader()
    writer.writerows(labels)

print(f"generated reason_candidates.jsonl: {len(candidates)} rows")
print(f"generated dev_labels.csv: {len(labels)} rows")
print(f"pilot users: {len(set(x['user_id'] for x in candidates))}, items: {len(set(x['item_id'] for x in candidates))}")
