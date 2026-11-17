"""Deterministic rule baseline for the pilot Jev exposure-review dataset."""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from pathlib import Path
from typing import Iterable


DEFAULT_MODEL_VERSION = "rule-baseline-v1"
DEFAULT_SCORE_NAME = "rule-compliance-v1"
SEVERITY_WEIGHT = {"medium": 0.60, "high": 0.82, "critical": 0.95}


def load_lexicon(path: str | Path) -> list[dict]:
    entries: list[dict] = []
    with Path(path).open(encoding="utf-8") as handle:
        for raw in handle:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("|", 6)
            if len(parts) != 7:
                raise ValueError(f"invalid lexicon row: {line}")
            term, risk_type, severity, rule_basis, canonical_term, match_type, note = parts
            entries.append(
                {
                    "term": term,
                    "risk_type": risk_type,
                    "severity": severity,
                    "rule_basis": rule_basis,
                    "canonical_term": canonical_term,
                    "match_type": match_type,
                    "note": note,
                }
            )
    return entries


def _contains(text: str, term: str) -> bool:
    return term.casefold() in text.casefold()


def find_lexicon_hits(reason: str, lexicon: Iterable[dict]) -> list[dict]:
    hits = [entry for entry in lexicon if _contains(reason, entry["term"])]
    return sorted(
        hits,
        key=lambda entry: (-SEVERITY_WEIGHT.get(entry["severity"], 0.5), -len(entry["term"])),
    )


def _as_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return "|".join(str(x) for x in value)
    return str(value)


def _field_values(item: dict, names: Iterable[str]) -> list[str]:
    values: list[str] = []
    for name in names:
        value = item.get(name)
        if isinstance(value, list):
            values.extend(str(x) for x in value)
        elif value not in (None, ""):
            values.append(str(value))
    return values


def _supported_efficacy(candidate: dict, canonical_term: str) -> bool:
    item = candidate.get("item_attrs_returned") or {}
    allowed = set(_field_values(item, ["efficacy_claims_allowed"]))
    if canonical_term in allowed:
        return True

    values = _field_values(
        item,
        ["functions", "suitable_scenes", "description", "title", "target_tags"],
    )
    text = "|".join(values)
    synonyms = {
        "防潮": ["防潮", "除湿"],
        "除湿": ["除湿", "防潮"],
        "防晒": ["防晒"],
    }
    accepted = synonyms.get(canonical_term, [canonical_term])
    return any(term in text for term in accepted)


def _topic_mismatch(candidate: dict) -> tuple[bool, list[str]]:
    reason = candidate.get("generated_reason", "")
    item = candidate.get("item_attrs_returned") or {}
    item_text = "|".join(
        _field_values(
            item,
            ["title", "category", "subcategory", "description", "functions", "suitable_scenes", "target_tags"],
        )
    )
    user = candidate.get("user_context") or {}
    user_text = "|".join(_field_values(user, ["interests", "recent_categories"]))
    checks = [
        (["猫咪", "猫粮", "猫砂", "狗狗", "宠物"], ["宠物", "猫", "狗"]),
        (["婴儿", "宝宝", "新手妈妈", "母婴"], ["母婴", "婴儿", "宝宝", "儿童"]),
        (["玩具"], ["玩具", "潮玩"]),
        (["汽车", "车载"], ["汽车", "车载"]),
    ]
    for cues, expected in checks:
        matched_cue = next((cue for cue in cues if cue in reason), None)
        if matched_cue and not any(term in item_text for term in expected):
            # User interest cannot override a direct product-topic mismatch.
            return True, [
                f"商品字段与理由主题不一致：理由命中「{matched_cue}」",
                f"item_attrs_returned 未命中主题词；user_context={user_text or '未提供'}",
            ]
    return False, []


def _price_evidence(candidate: dict, price_hits: list[dict]) -> tuple[bool, list[str]]:
    reason = candidate.get("generated_reason", "")
    promo = candidate.get("promo_computed_in_code") or {}
    evidence: list[str] = []
    mismatch = False

    match = re.search(r"满\s*(\d+(?:\.\d+)?)\s*减\s*(\d+(?:\.\d+)?)", reason)
    if match:
        threshold_yuan = float(match.group(1))
        discount_yuan = float(match.group(2))
        threshold_cents = round(threshold_yuan * 100)
        discount_cents = round(discount_yuan * 100)
        actual_threshold = promo.get("threshold_cents")
        actual_discount = promo.get("discount_cents")
        if not promo or not promo.get("applicable"):
            mismatch = True
            evidence.append("promo_computed_in_code 未返回适用的满减规则")
        elif actual_threshold != threshold_cents or actual_discount != discount_cents:
            mismatch = True
            evidence.append(
                f"促销规则实际为满{(actual_threshold or 0) / 100:g}减{(actual_discount or 0) / 100:g}，理由写为满{threshold_yuan:g}减{discount_yuan:g}"
            )

    generic_terms = {
        "全场半价": lambda p: p.get("type") == "percent_discount" and p.get("discount_rate") == 0.5,
        "买一送一": lambda p: p.get("type") == "gift" and p.get("gift_item") in {"同款商品", "同款"},
        "买一赠一": lambda p: p.get("type") == "gift" and p.get("gift_item") in {"同款商品", "同款"},
        "无门槛优惠": lambda p: bool(p) and p.get("threshold_cents") in (None, 0),
        "0元购": lambda p: False,
        "限时最低": lambda p: False,
    }
    for term, predicate in generic_terms.items():
        if term in reason and not predicate(promo):
            mismatch = True
            evidence.append(f"promo_computed_in_code 不支持「{term}」")

    if price_hits and not promo and any(entry["term"] in reason for entry in price_hits):
        mismatch = True
        evidence.append("promo_ids 为空，未发现可核验的促销规则")

    return mismatch, evidence


def _support_evidence(candidate: dict) -> list[str]:
    item = candidate.get("item_attrs_returned") or {}
    evidence: list[str] = []
    functions = item.get("functions") or []
    scenes = item.get("suitable_scenes") or []
    if functions:
        evidence.append(f"item_attrs_returned.functions 支持：{'、'.join(str(x) for x in functions[:3])}")
    if scenes:
        evidence.append(f"item_attrs_returned.suitable_scenes 支持：{'、'.join(str(x) for x in scenes[:2])}")
    if not evidence and item.get("category"):
        evidence.append(f"item_attrs_returned.category={item['category']} 可作为主题依据")
    return evidence or ["候选输入未提供可引用的商品事实"]


def evaluate_candidate(
    candidate: dict,
    lexicon: list[dict],
    *,
    model_version: str = DEFAULT_MODEL_VERSION,
    score_name: str = DEFAULT_SCORE_NAME,
) -> dict:
    reason = candidate.get("generated_reason", "")
    hits = find_lexicon_hits(reason, lexicon)
    absolute_hits = [h for h in hits if h["risk_type"] == "absolute_claim"]
    efficacy_hits = [h for h in hits if h["risk_type"] == "efficacy_or_medical_claim"]
    price_hits = [h for h in hits if h["risk_type"] == "price_misleading"]
    unsupported_efficacy = [h for h in efficacy_hits if not _supported_efficacy(candidate, h["canonical_term"])]
    price_mismatch, price_evidence = _price_evidence(candidate, price_hits)
    topic_mismatch, topic_evidence = _topic_mismatch(candidate)
    disclosure_missing = candidate.get("ai_disclosure_flag_from_code") is False
    attrs_complete = candidate.get("attrs_returned_complete", True)

    evidence: list[str] = []
    decision = "expose"
    risk_type = "compliant"
    score = 0.03
    escalated = False

    if not attrs_complete:
        decision = "human_review"
        risk_type = "efficacy_or_medical_claim" if efficacy_hits else "off_topic"
        score = 0.58
        escalated = True
        evidence.append("关键商品属性字段缺失，无法完成事实核验")
        returned = set()
        for trace in candidate.get("tool_trace", []):
            returned.update(trace.get("returned_fields", []))
        evidence.append(f"tool_trace 未返回完整 functions/suitable_scenes，实际字段：{sorted(returned)}")

    elif price_mismatch:
        decision = "block"
        risk_type = "price_misleading"
        score = 0.96
        evidence.extend(price_evidence)

    elif unsupported_efficacy:
        decision = "block"
        risk_type = "efficacy_or_medical_claim"
        score = max(0.92, max(SEVERITY_WEIGHT.get(h["severity"], 0.8) for h in unsupported_efficacy))
        evidence.extend(
            f"item_attrs_returned.functions/suitable_scenes 不支持「{h['canonical_term']}」功效"
            for h in unsupported_efficacy
        )
        evidence.extend(
            f"lexicon 命中「{h['term']}」（{h['risk_type']}）" for h in unsupported_efficacy
        )

    elif absolute_hits:
        decision = "rewrite"
        risk_type = "absolute_claim"
        score = max(0.68, max(SEVERITY_WEIGHT.get(h["severity"], 0.6) for h in absolute_hits) - 0.1)
        evidence.extend(
            f"lexicon 命中「{h['term']}」（absolute_claim，规范词：{h['canonical_term']}）"
            for h in absolute_hits
        )
        evidence.append("商品属性和价格字段不足以证明该绝对化比较结论")

    elif disclosure_missing:
        decision = "rewrite"
        risk_type = "missing_ai_disclosure"
        score = 0.72
        evidence.append("ai_disclosure_flag_from_code=false")
        evidence.append("补充 AI 生成标识后可重新审核")

    elif topic_mismatch:
        decision = "rewrite"
        risk_type = "off_topic"
        score = 0.68
        evidence.extend(topic_evidence)

    else:
        evidence.extend(_support_evidence(candidate))
        if candidate.get("promo_computed_in_code"):
            evidence.append("promo_computed_in_code 与候选理由未发现明显冲突")

    return {
        "reason_id": candidate.get("reason_id"),
        "decision": decision,
        "risk_type": risk_type,
        "evidence": evidence or ["规则基线未生成可引用证据"],
        "judge_score": round(float(score), 4),
        "escalated": bool(escalated),
        "model_version": model_version,
        "score_name": score_name,
    }


def evaluate_all(candidates: list[dict], lexicon: list[dict]) -> list[dict]:
    return [evaluate_candidate(candidate, lexicon) for candidate in candidates]


def _macro_f1(y_true: list[str], y_pred: list[str], labels: list[str]) -> float:
    scores = []
    for label in labels:
        tp = sum(a == label and b == label for a, b in zip(y_true, y_pred))
        fp = sum(a != label and b == label for a, b in zip(y_true, y_pred))
        fn = sum(a == label and b != label for a, b in zip(y_true, y_pred))
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        scores.append(2 * precision * recall / (precision + recall) if precision + recall else 0.0)
    return sum(scores) / len(scores)


def evaluate_report(
    results: list[dict],
    labels: list[dict],
    *,
    model_version: str | None = None,
    score_name: str | None = None,
) -> dict:
    by_id = {row["reason_id"]: row for row in results}
    gold = [row for row in labels if row["reason_id"] in by_id]
    decisions = ["expose", "rewrite", "human_review", "block"]
    y_true = [row["gold_decision"] for row in gold]
    y_pred = [by_id[row["reason_id"]]["decision"] for row in gold]
    risk_true = [row["gold_risk_type"] for row in gold]
    risk_pred = [by_id[row["reason_id"]]["risk_type"] for row in gold]
    block_total = sum(x == "block" for x in y_true)
    leak = sum(a == "block" and b == "expose" for a, b in zip(y_true, y_pred))
    evidence_nonempty = sum(bool(by_id[row["reason_id"]]["evidence"]) for row in gold)
    return {
        "sample_count": len(gold),
        "decision_counts": dict(Counter(y_pred)),
        "risk_type_counts": dict(Counter(risk_pred)),
        "violation_leak_rate": leak / block_total if block_total else 0.0,
        "violation_leak_count": leak,
        "gold_block_count": block_total,
        "decision_macro_f1": round(_macro_f1(y_true, y_pred, decisions), 4),
        "risk_type_accuracy": round(sum(a == b for a, b in zip(risk_true, risk_pred)) / len(gold), 4) if gold else 0.0,
        "escalation_rate": round(sum(by_id[row["reason_id"]]["escalated"] for row in gold) / len(gold), 4) if gold else 0.0,
        "human_review_rate": round(sum(x == "human_review" for x in y_pred) / len(gold), 4) if gold else 0.0,
        "evidence_nonempty_rate": round(evidence_nonempty / len(gold), 4) if gold else 0.0,
        "model_version": model_version or (results[0].get("model_version") if results else DEFAULT_MODEL_VERSION),
        "score_name": score_name or (results[0].get("score_name") if results else DEFAULT_SCORE_NAME),
        "note": (
            "Pilot rule baseline; judge_score is a deterministic risk score, not a Jev model probability."
            if (model_version or DEFAULT_MODEL_VERSION).startswith("rule-")
            else "Pilot evaluation against synthetic labels; metrics are not production conclusions."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidates", default="reason_candidates.jsonl")
    parser.add_argument("--lexicon", default="compliance_lexicon.txt")
    parser.add_argument("--labels", default="dev_labels.csv")
    parser.add_argument("--output", default="result_rule_baseline.jsonl")
    parser.add_argument("--report", default="rule_baseline_report.json")
    args = parser.parse_args()

    with Path(args.candidates).open(encoding="utf-8") as handle:
        candidates = [json.loads(line) for line in handle if line.strip()]
    lexicon = load_lexicon(args.lexicon)
    results = evaluate_all(candidates, lexicon)
    with Path(args.output).open("w", encoding="utf-8") as handle:
        for result in results:
            handle.write(json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n")

    with Path(args.labels).open(encoding="utf-8-sig", newline="") as handle:
        labels = list(csv.DictReader(handle))
    report = evaluate_report(results, labels)
    with Path(args.report).open("w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")

    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
