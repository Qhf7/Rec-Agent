#!/usr/bin/env python3
"""Generate deterministic daily exposure/click history for reference analysis.

The project keeps ``exposure_log*.jsonl`` as one aggregate row per reason. This
module expands those aggregates into daily rows without changing the source
logs, so analysts can slice the synthetic history by date, placement, device,
user, item, or Jev decision.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parent
DEFAULT_START_DATE = date(2026, 11, 3)
DEFAULT_DAYS = 14

COUNT_FIELDS = (
    "exposure_count",
    "click_count",
    "add_cart_count",
    "order_count",
    "refund_count",
    "complaint_count",
)


def _stable_rng(seed: int, reason_id: str) -> random.Random:
    digest = hashlib.sha256(reason_id.encode("utf-8")).digest()
    salt = int.from_bytes(digest[:8], "big")
    return random.Random(seed ^ salt)


def _allocate(total: int, capacities: list[int], rng: random.Random) -> list[int]:
    """Allocate ``total`` units across rows, respecting per-row capacities."""

    total = max(0, min(int(total), sum(max(0, c) for c in capacities)))
    result = [0] * len(capacities)
    if not total:
        return result

    weights = [rng.uniform(0.78, 1.22) if capacity > 0 else 0.0 for capacity in capacities]
    weight_sum = sum(weights)
    if not weight_sum:
        return result

    fractional: list[tuple[float, int]] = []
    assigned = 0
    for index, (capacity, weight) in enumerate(zip(capacities, weights)):
        raw = total * weight / weight_sum
        value = min(max(0, capacity), int(raw))
        result[index] = value
        assigned += value
        fractional.append((raw - int(raw), index))

    # Largest remainder allocation keeps sums exact while remaining stable.
    for _, index in sorted(fractional, reverse=True):
        if assigned >= total:
            break
        if result[index] < capacities[index]:
            result[index] += 1
            assigned += 1

    # A capacity cap can leave a remainder after the first pass.
    while assigned < total:
        available = [index for index, capacity in enumerate(capacities) if result[index] < capacity]
        if not available:
            break
        index = available[rng.randrange(len(available))]
        result[index] += 1
        assigned += 1
    return result


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _date_range(start_date: date, days: int) -> list[str]:
    return [(start_date + timedelta(days=offset)).isoformat() for offset in range(days)]


def _source_and_device(rng: random.Random) -> tuple[str, str, int]:
    source = rng.choices(
        ["猜你喜欢", "首页推荐", "频道页", "站内搜索"],
        weights=[0.56, 0.22, 0.14, 0.08],
        k=1,
    )[0]
    device = rng.choices(["app", "mobile_web", "desktop_web"], weights=[0.74, 0.18, 0.08], k=1)[0]
    position = rng.choices(range(1, 7), weights=[0.30, 0.23, 0.18, 0.13, 0.10, 0.06], k=1)[0]
    return source, device, position


def generate_history(
    candidates: list[dict[str, Any]],
    results: list[dict[str, Any]],
    exposure: list[dict[str, Any]],
    *,
    seed: int = 20261117,
    start_date: date = DEFAULT_START_DATE,
    days: int = DEFAULT_DAYS,
) -> list[dict[str, Any]]:
    """Expand aggregate exposure rows into deterministic daily history rows."""

    if days <= 0:
        raise ValueError("days must be positive")
    if any("attractiveness_score" in row and "judge_score" not in row for row in results):
        raise ValueError("Exposure history requires a risk-severity judge_score from the nine-question protocol")
    candidates_by_id = {row["reason_id"]: row for row in candidates}
    results_by_id = {row["reason_id"]: row for row in results}
    dates = _date_range(start_date, days)
    rows: list[dict[str, Any]] = []

    for aggregate in exposure:
        reason_id = aggregate["reason_id"]
        candidate = candidates_by_id.get(reason_id, {})
        result = results_by_id.get(reason_id, {})
        rng = _stable_rng(seed, reason_id)
        capacities = [1_000_000] * days
        exposure_counts = _allocate(int(aggregate.get("exposure_count", 0)), capacities, rng)
        click_counts = _allocate(int(aggregate.get("click_count", 0)), exposure_counts, rng)
        add_cart_counts = _allocate(int(aggregate.get("add_cart_count", 0)), click_counts, rng)
        order_counts = _allocate(int(aggregate.get("order_count", 0)), click_counts, rng)
        refund_counts = _allocate(int(aggregate.get("refund_count", 0)), order_counts, rng)
        complaint_counts = _allocate(int(aggregate.get("complaint_count", 0)), exposure_counts, rng)
        source, device, position = _source_and_device(rng)
        exposed = bool(aggregate.get("exposed", False))

        for index, event_date in enumerate(dates):
            exposure_count = exposure_counts[index] if exposed else 0
            click_count = click_counts[index] if exposed else 0
            add_cart_count = add_cart_counts[index] if exposed else 0
            order_count = order_counts[index] if exposed else 0
            refund_count = refund_counts[index] if exposed else 0
            complaint_count = complaint_counts[index] if exposed else 0
            rows.append({
                "event_date": event_date,
                "reason_id": reason_id,
                "user_id": candidate.get("user_id", ""),
                "item_id": candidate.get("item_id", ""),
                "decision": result.get("decision", aggregate.get("decision", "")),
                "risk_type": result.get("risk_type", ""),
                "judge_score": float(result.get("judge_score", aggregate.get("judge_score", 0.0))),
                "exposed": exposed,
                "traffic_source": source,
                "device_type": device,
                "position": position,
                "exposure_count": exposure_count,
                "click_count": click_count,
                "ctr": round(click_count / exposure_count, 6) if exposure_count else 0.0,
                "add_cart_count": add_cart_count,
                "order_count": order_count,
                "refund_count": refund_count,
                "complaint_count": complaint_count,
                "observation_window_days": days,
                "simulation_seed": seed,
                "history_version": "exposure-click-history-v1",
            })
    return rows


def write_csv(rows: Iterable[dict[str, Any]], output: Path) -> None:
    rows = list(rows)
    if not rows:
        raise ValueError("no rows to write")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="生成日粒度曝光点击历史（模拟数据）")
    parser.add_argument("--candidates", default="reason_candidates_full.jsonl")
    parser.add_argument("--results", default="result_jev_full.jsonl")
    parser.add_argument("--exposure", default="exposure_log_full.jsonl")
    parser.add_argument("--output", default="data/exposure_click_history.csv")
    parser.add_argument("--start-date", default=DEFAULT_START_DATE.isoformat())
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS)
    parser.add_argument("--seed", type=int, default=20261117)
    args = parser.parse_args()

    rows = generate_history(
        _load_jsonl(Path(args.candidates)),
        _load_jsonl(Path(args.results)),
        _load_jsonl(Path(args.exposure)),
        seed=args.seed,
        start_date=date.fromisoformat(args.start_date),
        days=args.days,
    )
    output = Path(args.output)
    write_csv(rows, output)
    print(f"wrote {len(rows)} rows to {output}")


if __name__ == "__main__":
    main()

