"""Generate deterministic synthetic exposure outcomes and calibration summaries."""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
import statistics
from pathlib import Path


def _sigmoid(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-value))


def _binomial(rng: random.Random, n: int, probability: float) -> int:
    return sum(rng.random() < probability for _ in range(n))


def _bucket(score: float) -> int:
    return min(9, max(0, int(float(score) * 10)))


def generate_exposure_records(candidates: list[dict], results: list[dict], seed: int = 20261116):
    if any("attractiveness_score" in row and "judge_score" not in row for row in results):
        raise ValueError("Exposure simulation requires a risk-severity judge_score from the nine-question protocol")
    rng = random.Random(seed)
    result_by_id = {row["reason_id"]: row for row in results}
    latent_records = []
    exposure_records = []
    for candidate in candidates:
        reason_id = candidate["reason_id"]
        result = result_by_id[reason_id]
        user = candidate.get("user_context") or {}
        item = candidate.get("item_attrs_returned") or {}
        category = item.get("category", "")
        recent_categories = user.get("recent_categories") or []
        interests = user.get("interests") or []
        rel = 0.72 if category in recent_categories else (0.58 if category in interests else 0.35)
        rel = min(1.0, max(0.0, rel + rng.uniform(-0.08, 0.08)))
        reason = candidate.get("generated_reason", "")
        appeal = min(1.0, max(0.0, 0.35 + min(len(reason), 24) / 60 + (0.12 if any(x in reason for x in ["梅雨季", "深夜", "租房", "卧室", "旅行"]) else 0) + rng.uniform(-0.06, 0.06)))
        risk_type = result.get("risk_type")
        claim_gap = {"compliant": 0.05, "missing_ai_disclosure": 0.12, "off_topic": 0.45, "absolute_claim": 0.58, "price_misleading": 0.72, "efficacy_or_medical_claim": 0.82}.get(risk_type, 0.4)
        claim_gap = min(1.0, max(0.0, claim_gap + rng.uniform(-0.04, 0.04)))
        quality = min(1.0, max(0.35, rng.uniform(0.55, 0.95)))
        risk = min(1.0, max(0.0, 0.65 * claim_gap + 0.35 * float(result.get("judge_score", 0.0))))
        p_click = _sigmoid(-1.2 + 1.3 * rel + 1.0 * appeal - 0.8 * claim_gap)
        p_order_given_click = _sigmoid(-0.35 + 1.1 * quality - 0.8 * claim_gap)
        p_refund_given_order = _sigmoid(-3.0 + 2.2 * (1.0 - quality) + 2.6 * claim_gap + 1.2 * risk)
        p_complaint = _sigmoid(-4.0 + 2.5 * claim_gap + 2.0 * risk)
        potential_exposure_count = rng.randint(2000, 5000)
        potential_click_count = _binomial(rng, potential_exposure_count, p_click)
        potential_order_count = _binomial(rng, potential_click_count, p_order_given_click)
        potential_refund_count = _binomial(rng, potential_order_count, p_refund_given_order)
        potential_complaint_count = _binomial(rng, potential_exposure_count, p_complaint)
        exposed = result.get("decision") in {"expose", "rewrite"}
        exposure_count = potential_exposure_count if exposed else 0
        click_count = potential_click_count if exposed else 0
        order_count = potential_order_count if exposed else 0
        refund_count = potential_refund_count if exposed else 0
        complaint_count = potential_complaint_count if exposed else 0
        latent_records.append({
            "reason_id": reason_id,
            "judge_score": float(result.get("judge_score", 0.0)),
            "rel": round(rel, 6),
            "appeal": round(appeal, 6),
            "claim_gap": round(claim_gap, 6),
            "quality": round(quality, 6),
            "risk": round(risk, 6),
            "potential_exposure_count": potential_exposure_count,
            "potential_click_count": potential_click_count,
            "potential_order_count": potential_order_count,
            "potential_refund_count": potential_refund_count,
            "potential_complaint_count": potential_complaint_count,
        })
        exposure_records.append({
            "reason_id": reason_id,
            "decision": result.get("decision"),
            "judge_score": float(result.get("judge_score", 0.0)),
            "exposed": exposed,
            "exposure_count": exposure_count,
            "click_count": click_count,
            "add_cart_count": _binomial(rng, click_count, 0.25) if exposed else 0,
            "order_count": order_count,
            "refund_count": refund_count,
            "complaint_count": complaint_count,
            "observation_window_days": 14,
            "simulation_seed": seed,
        })
    return latent_records, exposure_records


def _rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 6) if denominator else 0.0


def summarize_calibration(rows: list[dict], population_rows: list[dict]) -> dict:
    buckets = []
    for bucket in range(10):
        lower = bucket / 10
        upper = (bucket + 1) / 10
        observed = [row for row in rows if bucket == _bucket(float(row.get("judge_score", 0.0)))]
        population = [row for row in population_rows if bucket == _bucket(float(row.get("judge_score", 0.0)))]
        refund_count = sum(int(row.get("refund_count", 0)) for row in observed)
        order_count = sum(int(row.get("order_count", 0)) for row in observed)
        complaint_count = sum(int(row.get("complaint_count", 0)) for row in observed)
        exposure_count = sum(int(row.get("exposure_count", 0)) for row in observed)
        potential_refunds = sum(int(row.get("potential_refund_count", row.get("refund_count", 0))) for row in population)
        potential_orders = sum(int(row.get("potential_order_count", row.get("order_count", 0))) for row in population)
        potential_complaints = sum(int(row.get("potential_complaint_count", row.get("complaint_count", 0))) for row in population)
        potential_exposure = sum(int(row.get("potential_exposure_count", row.get("exposure_count", 0))) for row in population)
        buckets.append({
            "bucket": bucket,
            "score_range": [round(lower, 1), round(upper, 1)],
            "sample_count": len(observed),
            "exposure_count": exposure_count,
            "refund_rate": _rate(refund_count, order_count),
            "complaint_rate": _rate(complaint_count, exposure_count),
            "order_rate": _rate(order_count, exposure_count),
            "population_refund_rate": _rate(potential_refunds, potential_orders),
            "population_complaint_rate": _rate(potential_complaints, potential_exposure),
            "population_order_rate": _rate(potential_orders, potential_exposure),
        })
    nonempty = [b for b in buckets if b["sample_count"]]
    violations = sum(
        nonempty[i]["population_complaint_rate"] > nonempty[i + 1]["population_complaint_rate"]
        for i in range(len(nonempty) - 1)
    )
    return {"bucket_count": 10, "buckets": buckets, "population_monotonicity_violations": int(violations)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidates", default="reason_candidates.jsonl")
    parser.add_argument("--results", default="result_jev.jsonl")
    parser.add_argument("--output", default="exposure_log.jsonl")
    parser.add_argument("--latent", default="latent.csv")
    parser.add_argument("--report", default="calibration_report.json")
    parser.add_argument("--seed", type=int, default=20261116)
    args = parser.parse_args()

    with Path(args.candidates).open(encoding="utf-8") as handle:
        candidates = [json.loads(line) for line in handle if line.strip()]
    with Path(args.results).open(encoding="utf-8") as handle:
        results = [json.loads(line) for line in handle if line.strip()]
    latent, exposure = generate_exposure_records(candidates, results, seed=args.seed)
    with Path(args.output).open("w", encoding="utf-8") as handle:
        for row in exposure:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    with Path(args.latent).open("w", encoding="utf-8", newline="") as handle:
        fields = list(latent[0].keys())
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(latent)
    report = summarize_calibration(exposure, latent)
    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
