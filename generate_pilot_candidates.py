"""Generate 20 factual and 20 controlled-stress canonical replay fixtures."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from generate_full_candidates import _candidate, _load_tables, _natural_reason


def build_pilot_dataset():
    users, items, promo_rules = _load_tables()
    user_ids = sorted(users)[:20]
    # Controlled mutations use ordinary household items, where the asserted
    # medical functions and pet-toy topics are absent.
    item_ids = sorted(items)[:20]
    candidates, labels = [], []
    for source in ("natural", "stress"):
        for index, (user_id, item_id) in enumerate(zip(user_ids, item_ids)):
            user, item = users[user_id], items[item_id]
            reason = _natural_reason(user, item, index)
            risk, decision = "compliant", "expose"
            evidence = "items.category_l3、items.spec、items.functions 与理由逐项一致"
            complete, ai_flag = True, True
            factually_supported = True
            if source == "stress":
                scenario = index % 6
                factually_supported = scenario == 3
                if scenario == 0:
                    reason = "治疗鼻炎，根治过敏"
                    risk, decision = "efficacy_or_medical_claim", "block"
                    evidence = "items.functions和efficacy_claims_allowed无治疗鼻炎或根治过敏能力"
                elif scenario == 1:
                    reason = "全网最低价，入手更划算"
                    risk, decision = "absolute_claim", "rewrite"
                    evidence = "商品事实不能证明全网最低；命中绝对化词表"
                elif scenario == 2:
                    reason = "满99减50"
                    risk, decision = "price_misleading", "block"
                    evidence = "canonical促销规则没有适用的满99减50规则"
                elif scenario == 3:
                    ai_flag = False
                    risk, decision = "missing_ai_disclosure", "rewrite"
                    evidence = "理由事实支持，但ai_disclosure_flag_from_code=false"
                elif scenario == 4:
                    reason = "猫咪的宠物玩具"
                    risk, decision = "off_topic", "rewrite"
                    evidence = "商品家居日用类目和功能均不属于宠物玩具"
                else:
                    reason, complete = "治疗鼻炎的日常好物", False
                    risk, decision = "efficacy_or_medical_claim", "human_review"
                    evidence = "关键functions/efficacy_claims_allowed字段缺失，无法核验"
            candidate = _candidate(
                user_id, item_id, user, item, reason, source, "canonical_pilot_fixture_v2", "pilot",
                complete=complete, ai_flag=ai_flag, promo_rules=promo_rules,
            )
            candidate["reason_id"] = f"r_pilot_{len(candidates) + 1:04d}"
            candidates.append(candidate)
            labels.append({
                "reason_id": candidate["reason_id"], "factually_supported": factually_supported,
                "gold_risk_type": risk, "gold_decision": decision, "gold_evidence": evidence,
                "annotator_confidence": "medium" if decision == "human_review" else "high",
                "label_source": "synthetic_seed_v2", "label_version": "label-spec-v2-pilot-synthetic",
                "split": "pilot", "source": source,
            })
    return candidates, labels


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", default="reason_candidates.jsonl")
    parser.add_argument("--labels", default="dev_labels.csv")
    args = parser.parse_args()
    candidates, labels = build_pilot_dataset()
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
