#!/usr/bin/env python3
"""Generate synthetic recommendation exposure/click events for Rec-Agent history.

The file produced here is deliberately separate from Jev inputs. Every row is
an already-approved recommendation exposure and can be queried by Rec-Agent as
historical feedback. Real deployments should append the same schema only after
the final Jev-approved reason is shown to a user.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import random
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
DEFAULT_START_DATE = date(2026, 6, 1)
DEFAULT_DAYS = 14
DEFAULT_COUNT = 1600
HISTORY_VERSION = "recommendation-feedback-v1"


def _split(value: Any) -> list[str]:
    return [part for part in str(value or "").replace(";", "|").split("|") if part]


def _stable_rng(seed: int, index: int) -> random.Random:
    digest = hashlib.sha256(f"{seed}:{index}".encode("utf-8")).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def _parse_active_hours(value: str) -> tuple[int, int]:
    try:
        start, end = value.split("-", 1)
        return int(start.split(":", 1)[0]), int(end.split(":", 1)[0])
    except (AttributeError, ValueError):
        return 9, 21


def _choose_item(user: dict[str, str], items: list[dict[str, str]], rng: random.Random) -> dict[str, str]:
    available = [item for item in items if int(item.get("stock", 0) or 0) > 0]
    preferred = set(_split(user.get("preferred_categories")))
    matching = [item for item in available if item.get("category_l1") in preferred]
    pool = matching if matching and rng.random() < 0.75 else available
    return pool[rng.randrange(len(pool))]


def _pattern_ctr(item: dict[str, str], patterns: list[dict[str, str]]) -> float:
    matches = [row for row in patterns if row.get("category_l2") == item.get("category_l2")]
    if matches:
        return sum(float(row.get("ctr", 0.05)) for row in matches) / len(matches)
    return sum(float(row.get("ctr", 0.05)) for row in patterns) / max(1, len(patterns))


def _reason(user: dict[str, str], item: dict[str, str]) -> str:
    city = user.get("city", "")
    category = item.get("category_l2", "商品")
    if city and category:
        return f"{city}日常，{category}更方便"
    return f"日常使用，{category}更方便"


def _event_time(event_date: date, user: dict[str, str], rng: random.Random) -> datetime:
    start, end = _parse_active_hours(user.get("active_hours", "09:00-21:00"))
    span = end - start if end > start else (24 - start + end)
    hour = (start + rng.randrange(max(1, span))) % 24
    return datetime(event_date.year, event_date.month, event_date.day, hour, rng.randrange(60), rng.randrange(60))


def generate_feedback_events(
    users: list[dict[str, str]],
    items: list[dict[str, str]],
    patterns: list[dict[str, str]],
    *,
    count: int = DEFAULT_COUNT,
    seed: int = 20261117,
    start_date: date = DEFAULT_START_DATE,
    days: int = DEFAULT_DAYS,
) -> list[dict[str, Any]]:
    """Return deterministic, Jev-approved recommendation feedback events.

    The last 10% of users are intentionally left without events so the MCP
    history tool can exercise the cold-start path.
    """

    if not users or not items or not patterns:
        raise ValueError("users, items and patterns are required")
    if count < 0 or days <= 0:
        raise ValueError("count must be non-negative and days must be positive")
    warm_user_count = max(1, int(len(users) * 0.9))
    warm_users = users[:warm_user_count]
    events: list[dict[str, Any]] = []

    for index in range(count):
        rng = _stable_rng(seed, index)
        user = warm_users[(index * 17 + rng.randrange(len(warm_users))) % len(warm_users)]
        item = _choose_item(user, items, rng)
        event_date = start_date + timedelta(days=index % days)
        event_at = _event_time(event_date, user, rng)
        base_ctr = _pattern_ctr(item, patterns)
        affinity = 1.25 if item.get("category_l1") in set(_split(user.get("preferred_categories"))) else 0.82
        ctr_prior = min(0.20, max(0.005, base_ctr * affinity))
        click_probability = min(0.25, max(0.005, ctr_prior + rng.uniform(-0.008, 0.008)))
        clicked = rng.random() < click_probability
        click_at = event_at + timedelta(seconds=rng.randint(5, 180)) if clicked else None
        source = rng.choices(["猜你喜欢", "首页推荐", "频道页", "站内搜索"], weights=[56, 22, 14, 8], k=1)[0]
        device = rng.choices(["app", "mobile_web", "desktop_web"], weights=[74, 18, 8], k=1)[0]
        position = rng.choices([1, 2, 3, 4, 5, 6], weights=[30, 23, 18, 13, 10, 6], k=1)[0]
        event_id = f"re_{event_date:%Y%m%d}_{index + 1:06d}"
        events.append({
            "event_id": event_id,
            "event_time": event_at.isoformat(timespec="seconds") + "+08:00",
            "event_date": event_date.isoformat(),
            "user_id": user["user_id"],
            "item_id": item["item_id"],
            "reason_id": f"hist_{index + 1:06d}",
            "reason_version": "rec-agent-v2",
            "exposure_reason": _reason(user, item),
            "jev_decision": "expose",
            "jev_approved": True,
            "shown": True,
            "clicked": clicked,
            "click_time": click_at.isoformat(timespec="seconds") + "+08:00" if click_at else None,
            "position": position,
            "traffic_source": source,
            "device_type": device,
            "session_id": f"sess_{event_date:%Y%m%d}_{user['user_id']}_{index % 24:02d}",
            "ctr_prior": round(ctr_prior, 6),
            "source": "synthetic_reference",
            "history_version": HISTORY_VERSION,
        })
    return events


def _load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(rows: Iterable[dict[str, Any]], output: Path) -> None:
    rows = list(rows)
    if not rows:
        raise ValueError("no rows to write")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="生成 Jev 通过后的推荐曝光点击事件（模拟参考数据）")
    parser.add_argument("--users", default=str(RAW / "users.csv"))
    parser.add_argument("--items", default=str(RAW / "items.csv"))
    parser.add_argument("--patterns", default=str(RAW / "history_reason_stats.csv"))
    parser.add_argument("--output", default=str(ROOT / "data" / "recommendation_feedback_history.csv"))
    parser.add_argument("--count", type=int, default=DEFAULT_COUNT)
    parser.add_argument("--start-date", default=DEFAULT_START_DATE.isoformat())
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS)
    parser.add_argument("--seed", type=int, default=20261117)
    args = parser.parse_args()

    rows = generate_feedback_events(
        _load_csv(Path(args.users)),
        _load_csv(Path(args.items)),
        _load_csv(Path(args.patterns)),
        count=args.count,
        seed=args.seed,
        start_date=date.fromisoformat(args.start_date),
        days=args.days,
    )
    output = Path(args.output)
    write_csv(rows, output)
    clicked = sum(bool(row["clicked"]) for row in rows)
    print(f"wrote {len(rows)} events to {output}; clicked={clicked}; ctr={clicked / len(rows):.6f}")


if __name__ == "__main__":
    main()
