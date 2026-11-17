#!/usr/bin/env python3
"""Validate the mock data layer. Exit code 1 on any hard failure."""

from __future__ import annotations

import csv
import json
import sqlite3
import sys
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
DB = ROOT / "data" / "mock.db"
SCENARIO = date(2026, 6, 15)

ERRORS: list[str] = []
WARNINGS: list[str] = []


def check(cond, msg):
    if not cond:
        ERRORS.append(msg)


def warn(cond, msg):
    if not cond:
        WARNINGS.append(msg)


def read_csv(name):
    with (RAW / name).open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def split(value):
    return [v for v in (value or "").split("|") if v]


def main():
    users = read_csv("users.csv")
    items = read_csv("items.csv")
    history = read_csv("history_reason_stats.csv")
    rules = json.loads((RAW / "promo_rules.json").read_text(encoding="utf-8"))
    lexicon = [line for line in (RAW / "compliance_lexicon.txt").read_text(encoding="utf-8").splitlines() if line.strip()]
    variants = [line for line in (RAW / "lexicon_variants.tsv").read_text(encoding="utf-8").splitlines() if line.strip()][1:]

    # ---------- counts / uniqueness ----------
    check(len(users) == 200, f"users expected 200, got {len(users)}")
    check(len(items) == 200, f"items expected 200, got {len(items)}")
    check(len(rules) == 30, f"rules expected 30, got {len(rules)}")
    check(len(lexicon) == 45, f"lexicon expected 45, got {len(lexicon)}")
    check(len(variants) == 20, f"variants expected 20, got {len(variants)}")
    check(len(history) == 30, f"history expected 30, got {len(history)}")
    check(len({u["user_id"] for u in users}) == len(users), "duplicate user_id")
    check(len({i["item_id"] for i in items}) == len(items), "duplicate item_id")
    check(len({i["title"] for i in items}) == len(items), "duplicate item title")

    item_by_id = {i["item_id"]: i for i in items}
    rule_by_id = {r["rule_id"]: r for r in rules}

    # ---------- users ----------
    stages = {"学生", "新手妈妈", "新手爸爸", "学龄家长", "单身职场", "新婚", "空巢"}
    levels = {"L1", "L2", "L3", "L4", "L5"}
    statuses = {"normal", "risk_control", "limited"}
    l1s = {"家居日用", "美妆个护", "食品生鲜", "服饰鞋包", "3C数码", "母婴亲子", "运动户外", "保健医疗"}

    for u in users:
        uid = u["user_id"]
        check(18 <= int(u["age"]) <= 55, f"{uid}: age out of range")
        check(u["gender"] in {"男", "女"}, f"{uid}: gender")
        check(u["life_stage"] in stages, f"{uid}: life_stage")
        check(u["consumption_level"] in levels, f"{uid}: consumption_level")
        check(u["account_status"] in statuses, f"{uid}: account_status")
        check(u["member_level"] in {"normal", "88VIP"}, f"{uid}: member_level")
        check(int(u["account_age_days"]) > 0, f"{uid}: account_age_days")
        check(float(u["aov_90d"]) > 0, f"{uid}: aov_90d")
        check(int(u["orders_90d"]) >= 0, f"{uid}: orders_90d")
        check(u["price_sensitivity"] in {"high", "mid", "low"}, f"{uid}: price_sensitivity")
        check(u["night_owl"] in {"true", "false"}, f"{uid}: night_owl")
        check(bool(u["active_hours"]), f"{uid}: active_hours")
        prefs = split(u["preferred_categories"])
        check(2 <= len(prefs) <= 3 and set(prefs) <= l1s, f"{uid}: preferred_categories")
        for iid in split(u["recent_cart_item_ids"]) + split(u["recent_order_item_ids"]):
            check(iid in item_by_id, f"{uid}: unknown item reference {iid}")
        check(1 <= len(split(u["last_search_terms"])) <= 3, f"{uid}: last_search_terms")
        check(2 <= len(split(u["tags"])) <= 4, f"{uid}: tags")
        if u["life_stage"] == "新手妈妈":
            check(u["gender"] == "女", f"{uid}: 新手妈妈 gender")
        if u["life_stage"] == "新手爸爸":
            check(u["gender"] == "男", f"{uid}: 新手爸爸 gender")

    night = sum(1 for u in users if u["night_owl"] == "true") / len(users)
    new = sum(1 for u in users if int(u["account_age_days"]) < 30) / len(users)
    vip = sum(1 for u in users if u["member_level"] == "88VIP") / len(users)
    abnormal = sum(1 for u in users if u["account_status"] != "normal") / len(users)
    warn(0.12 <= night <= 0.28, f"night_owl ratio {night:.2%} outside 12-28%")
    warn(0.05 <= new <= 0.15, f"new user ratio {new:.2%} outside 5-15%")
    warn(0.15 <= vip <= 0.30, f"88VIP ratio {vip:.2%} outside 15-30%")
    warn(0.04 <= abnormal <= 0.12, f"abnormal account ratio {abnormal:.2%} outside 4-12%")

    # ---------- items ----------
    regs = {"general", "cosmetic", "food", "health_food", "medical_device", "children"}
    for it in items:
        iid = it["item_id"]
        check(it["category_l1"] in l1s, f"{iid}: category_l1")
        check(bool(it["category_l2"]) and bool(it["category_l3"]), f"{iid}: category l2/l3")
        check(len(split(it["functions"])) >= 1, f"{iid}: functions empty")
        check(it["regulated_category"] in regs, f"{iid}: regulated_category")
        check(it["sensitive_category"] in {"true", "false"}, f"{iid}: sensitive_category")
        price = int(it["price_cents"])
        original = int(it["original_price_cents"])
        check(0 < price < original, f"{iid}: price/original")
        check(int(it["stock"]) >= 0, f"{iid}: stock")
        check(int(it["sales_30d"]) >= 0, f"{iid}: sales")
        check(3.5 <= float(it["rating"]) <= 5.0, f"{iid}: rating")
        check(0 <= float(it["return_rate_30d"]) <= 0.25, f"{iid}: return rate")
        check(0 <= float(it["complaint_rate_30d"]) <= 0.10, f"{iid}: complaint rate")
        check(bool(it["ad_law_notes"]), f"{iid}: ad_law_notes empty")

        quals = split(it["qualifications"])
        claims = split(it["efficacy_claims_allowed"])
        reg = it["regulated_category"]
        if reg == "cosmetic":
            check("妆字号" in quals, f"{iid}: cosmetic without 妆字号")
            check(bool(claims), f"{iid}: cosmetic without allowed claims")
        if reg == "health_food":
            check("蓝帽子" in quals, f"{iid}: health_food without 蓝帽子")
        if reg == "medical_device":
            check("械字号" in quals, f"{iid}: medical_device without 械字号")
        if reg == "children":
            check(any(q.startswith("GB") or q == "3C" for q in quals), f"{iid}: children without standard")
        if reg in {"cosmetic", "health_food", "medical_device", "children"}:
            check(it["sensitive_category"] == "true", f"{iid}: regulated sensitive but flag false")
        if reg in {"general", "food"}:
            check(not (set(claims) & {"治疗", "消炎", "美白", "祛斑", "减肥"}), f"{iid}: general/food has medical claim")

        promo_ids = split(it["promo_rule_ids"])
        for rid in promo_ids:
            check(rid in rule_by_id, f"{iid}: unknown promo rule {rid}")
            r = rule_by_id.get(rid)
            if r:
                check(r["start"] <= SCENARIO.isoformat() <= r["end"], f"{iid}: promo {rid} not active")
        check(len(promo_ids) == len(split(it["promo_tags"])), f"{iid}: promo tags/ids mismatch")

    l1_counts = Counter(i["category_l1"] for i in items)
    for cat in l1s:
        warn(20 <= l1_counts[cat] <= 30, f"{cat}: item count {l1_counts[cat]} outside 20-30")
    sensitive_ratio = sum(1 for i in items if i["sensitive_category"] == "true") / len(items)
    promo_cov = sum(1 for i in items if i["promo_rule_ids"]) / len(items)
    warn(0.28 <= sensitive_ratio <= 0.40, f"sensitive ratio {sensitive_ratio:.2%} outside 28-40%")
    warn(0.60 <= promo_cov <= 0.85, f"promo coverage {promo_cov:.2%} outside 60-85%")

    # ---------- rules ----------
    active = sum(1 for r in rules if r["start"] <= SCENARIO.isoformat() <= r["end"])
    check(active == 22, f"active rules expected 22, got {active}")
    for r in rules:
        check(r["type"] in {"full_reduction", "discount", "coupon", "gift"}, f"{r['rule_id']}: type")
        check(bool(r["scope"]), f"{r['rule_id']}: scope")
        if r["type"] == "discount":
            check(0 < r["discount_percent"] < 100, f"{r['rule_id']}: discount_percent")
        elif r["type"] in {"full_reduction", "coupon"}:
            check(r["threshold_cents"] > 0 and r["discount_cents"] > 0, f"{r['rule_id']}: amounts")
        elif r["type"] == "gift":
            check(bool(r["gift"]), f"{r['rule_id']}: gift empty")

    # ---------- db ----------
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    for table, expected in [("users", 200), ("items", 200), ("promo_rules", 30),
                            ("lexicon", 45), ("lexicon_variants", 20), ("history_stats", 30)]:
        got = cur.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        check(got == expected, f"db {table}: expected {expected}, got {got}")
    conn.close()

    # ---------- summary ----------
    print("counts:", {"users": len(users), "items": len(items), "rules": len(rules),
                      "active_rules": active, "lexicon": len(lexicon),
                      "variants": len(variants), "history": len(history)})
    print("categories:", dict(sorted(l1_counts.items())))
    print("ratios:", {"sensitive": round(sensitive_ratio, 3), "promo": round(promo_cov, 3),
                      "night_owl": round(night, 3), "new_user": round(new, 3),
                      "88vip": round(vip, 3), "abnormal": round(abnormal, 3)})
    print("statuses:", dict(Counter(i["regulated_category"] for i in items)))

    if WARNINGS:
        print("\nWARNINGS")
        for w in WARNINGS:
            print(" -", w)
    if ERRORS:
        print("\nERRORS")
        for e in ERRORS:
            print(" -", e)
        return 1
    print("\nPASS: all hard checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
