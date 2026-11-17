import csv
import json
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ITEMS_PATH = ROOT / "items.csv"
PROMO_PATH = ROOT / "promo_rules.json"
LEXICON_PATH = ROOT / "compliance_lexicon.txt"

# The first 12 promo IDs already appear in items.csv. Keep those IDs stable so
# item -> promo_rules foreign-key checks continue to pass.
with ITEMS_PATH.open(encoding="utf-8-sig", newline="") as f:
    items = list(csv.DictReader(f))

items_by_promo = {}
for row in items:
    for promo_id in filter(None, row.get("promo_ids", "").split("|")):
        items_by_promo.setdefault(promo_id, []).append(row["item_id"])

categories = sorted({row["category"] for row in items})
subcategory_by_category = {}
for row in items:
    subcategory_by_category.setdefault(row["category"], set()).add(row["subcategory"])

promo_rules = []
for idx in range(1, 31):
    promo_id = f"promo_{idx:03d}"
    linked_item_ids = items_by_promo.get(promo_id, [])
    # When an item already references this promo ID, derive the rule scope from
    # the linked item so item scope and category scope cannot contradict each other.
    linked_rows = [row for row in items if row["item_id"] in linked_item_ids]
    linked_categories = sorted({row["category"] for row in linked_rows})
    linked_subcategories = sorted({row["subcategory"] for row in linked_rows})
    category = linked_categories[0] if linked_categories else categories[(idx - 1) % len(categories)]
    rule_type = ["full_reduction", "percent_discount", "coupon", "gift", "member_price"][
        (idx - 1) % 5
    ]
    enabled = idx <= 24
    start = "2026-01-01" if enabled else "2025-01-01"
    end = "2026-12-31" if enabled else "2025-12-31"
    threshold_cents = 9900 + ((idx - 1) % 5) * 5000
    discount_cents = 1000 + ((idx - 1) % 6) * 500
    rule = {
        "promo_id": promo_id,
        "type": rule_type,
        "threshold_cents": threshold_cents if rule_type in {"full_reduction", "coupon"} else None,
        "discount_cents": discount_cents if rule_type in {"full_reduction", "coupon"} else None,
        "discount_rate": round(0.85 - ((idx - 1) % 4) * 0.05, 2) if rule_type == "percent_discount" else None,
        "gift_item": "便携收纳袋" if rule_type == "gift" else None,
        "member_level": "普通会员" if rule_type == "member_price" else None,
        "scope": {
            "item_ids": linked_item_ids,
            "category_l1": linked_categories or [category],
            "category_l2": linked_subcategories or sorted(subcategory_by_category[category])[:2],
        },
        "start": start,
        "end": end,
        "enabled": enabled,
        "stackable": idx % 3 == 0,
        "fine_print": (
            "不与其他同类优惠叠加；具体以结算页为准"
            if idx % 2
            else "活动库存有限，优惠条件以活动页和结算页为准"
        ),
        "teaching_note": "Mock促销规则，仅用于推荐理由事实核验，不代表真实活动。",
    }
    promo_rules.append(rule)

with PROMO_PATH.open("w", encoding="utf-8") as f:
    json.dump(
        {
            "schema_version": "promo-rules-v1",
            "as_of": "2026-11-16",
            "rules": promo_rules,
        },
        f,
        ensure_ascii=False,
        indent=2,
    )
    f.write("\n")

# Format: term|risk_type|severity|rule_basis|canonical_term|match_type|note
entries = []
def add(term, risk_type, severity, basis, canonical, match_type, note):
    entries.append((term, risk_type, severity, basis, canonical, match_type, note))

absolute_terms = [
    ("第一", "high"), ("首创", "high"), ("独家", "medium"), ("最佳", "high"),
    ("顶级", "high"), ("领先", "high"), ("全网第一", "high"), ("行业第一", "high"),
    ("全网最低", "high"), ("最低价", "high"), ("绝无仅有", "high"), ("万里挑一", "medium"),
    ("天花板", "medium"), ("王者", "medium"), ("王牌", "medium"), ("顶尖", "high"),
    ("极致", "medium"), ("NO.1", "high"), ("最便宜", "high"),
]
for term, severity in absolute_terms:
    add(term, "absolute_claim", severity, "广告法第9条（教学口径）", term, "canonical", "命中后需结合上下文判断是否为绝对化表达。")

efficacy_terms = [
    ("防潮", "high"), ("除湿", "high"), ("除甲醛", "critical"), ("杀菌", "critical"),
    ("抗菌", "high"), ("消炎", "critical"), ("治疗", "critical"), ("治愈", "critical"),
    ("根治", "critical"), ("祛斑", "critical"), ("美白", "high"), ("减肥", "critical"),
    ("降血糖", "critical"), ("降血压", "critical"), ("增高", "critical"), ("医用级", "high"),
    ("药效", "critical"), ("提高免疫力", "high"), ("改善失眠", "critical"), ("缓解焦虑", "critical"), ("防晒", "medium"),
]
for term, severity in efficacy_terms:
    add(term, "efficacy_or_medical_claim", severity, "广告法第28条/医疗功效教学口径", term, "canonical", "词语本身不是自动违规，必须核验商品属性、资质和允许宣称。")

price_terms = [
    ("满减", "medium"), ("满199减50", "high"), ("满99减50", "high"), ("全场半价", "high"),
    ("低至", "medium"), ("0元购", "high"), ("买一送一", "high"), ("价格保护", "medium"),
    ("限时最低", "high"), ("原价", "medium"), ("直降", "medium"), ("无门槛优惠", "high"),
]
for term, severity in price_terms:
    add(term, "price_misleading", severity, "促销规则核验（教学口径）", term, "canonical", "必须与promo_rules计算结果和适用范围交叉核验。")

variants = [
    ("蕞低", "absolute_claim", "high", "最低价"),
    ("zui di", "absolute_claim", "high", "最低价"),
    ("首創", "absolute_claim", "high", "首创"),
    ("第一名", "absolute_claim", "high", "第一"),
    ("天花板级别", "absolute_claim", "medium", "天花板"),
    ("全网TOP1", "absolute_claim", "high", "全网第一"),
    ("防潮神器", "efficacy_or_medical_claim", "high", "防潮"),
    ("除湿神器", "efficacy_or_medical_claim", "high", "除湿"),
    ("抗菌率100%", "efficacy_or_medical_claim", "critical", "抗菌"),
    ("治疗级", "efficacy_or_medical_claim", "critical", "治疗"),
    ("医美级", "efficacy_or_medical_claim", "high", "医用级"),
    ("美白淡斑", "efficacy_or_medical_claim", "critical", "美白"),
    ("祛痘", "efficacy_or_medical_claim", "high", "治疗"),
    ("满99立减50", "price_misleading", "high", "满99减50"),
    ("满199立减50", "price_misleading", "high", "满199减50"),
    ("全网最低价", "absolute_claim", "high", "最低价"),
    ("限时史低", "price_misleading", "high", "限时最低"),
    ("无门槛立减", "price_misleading", "high", "无门槛优惠"),
    ("买一赠一", "price_misleading", "high", "买一送一"),
    ("全场五折", "price_misleading", "high", "全场半价"),
]
for term, risk_type, severity, canonical in variants:
    basis = "广告法第9条变体教学口径" if risk_type == "absolute_claim" else "教学词表变体"
    add(term, risk_type, severity, basis, canonical, "variant", "变体、谐音、拼音或语义近似命中；仍需结合结构化事实核验。")

with LEXICON_PATH.open("w", encoding="utf-8") as f:
    f.write("# compliance_lexicon v1\n")
    f.write("# 教学用词表，不构成正式法务结论。\n")
    f.write("# term|risk_type|severity|rule_basis|canonical_term|match_type|note\n")
    for row in entries:
        f.write("|".join(row) + "\n")

print(f"generated {PROMO_PATH.name}: {len(promo_rules)} rules")
print(f"generated {LEXICON_PATH.name}: {len(entries)} entries")
print(f"linked item promo ids: {sorted(items_by_promo)}")
