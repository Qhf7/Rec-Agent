#!/usr/bin/env python3
"""Render Chinese summary charts from normalized, recorded Jev evaluations.

Usage:
    python3 scripts/plot_jev_multiround_results.py \
      --input runs/<run>/normalized-results.json \
      --output-dir docs/assets/jev-multiround-2026-11-20

The charts count model calls, including repeated calls. They describe observed
answers and dispositions; no accuracy or CTR estimate is derived.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
import math
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.lines import Line2D


SOURCES = ("fresh_harness", "frozen_controls")
SOURCE_LABELS = {"fresh_harness": "新 Harness 推荐", "frozen_controls": "冻结样本与对照"}
SOURCE_COLORS = {"fresh_harness": "#3578B9", "frozen_controls": "#99B6D5"}
DECISIONS = ("expose", "rewrite")
DECISION_LABELS = {"expose": "曝光 expose", "rewrite": "需改写 rewrite"}
COLORS = {"expose": "#16877A", "rewrite": "#D8842F", "risk": "#B44452", "ink": "#24364A"}
RISK_LABELS = {
    "compliant": "无所列风险",
    "absolute_claim": "绝对化表达",
    "efficacy_or_medical_claim": "功效 / 医疗宣称",
    "price_misleading": "价格 / 促销误导",
    "missing_ai_disclosure": "必需 AI 披露缺失",
    "off_topic": "场景不相关",
}
FONT_CANDIDATES = (
    Path("/System/Library/Fonts/STHeiti Medium.ttc"),
    Path("/System/Library/Fonts/PingFang.ttc"),
    Path("/System/Library/Fonts/Supplemental/Songti.ttc"),
)


def configure_style() -> None:
    for font in FONT_CANDIDATES:
        if font.is_file():
            font_manager.fontManager.addfont(str(font))
            plt.rcParams["font.family"] = font_manager.FontProperties(fname=str(font)).get_name()
            break
    else:
        plt.rcParams["font.family"] = ["Noto Sans CJK SC", "SimHei", "DejaVu Sans"]
    plt.rcParams.update({
        "axes.unicode_minus": False,
        "figure.facecolor": "#FFFFFF",
        "axes.facecolor": "#FFFFFF",
        "axes.edgecolor": "#D5DEE7",
        "axes.labelcolor": COLORS["ink"],
        "text.color": COLORS["ink"],
        "xtick.color": "#5D6C7C",
        "ytick.color": COLORS["ink"],
        "font.size": 11,
        "axes.titlesize": 14,
        "svg.fonttype": "path",
        "savefig.facecolor": "white",
    })


def _strict_object(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_records(path: Path) -> tuple[list[dict], dict]:
    document = json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=_strict_object)
    if not isinstance(document, dict) or not isinstance(document.get("records"), list):
        raise ValueError("input requires a records array")
    if not isinstance(document.get("metadata", {}), dict):
        raise ValueError("metadata must be an object")
    records = document["records"]
    if not records:
        raise ValueError("records must not be empty")
    identities = set()
    for row in records:
        if not isinstance(row, dict):
            raise ValueError("each record must be an object")
        for key in ("source", "round_id", "case_id", "item_id", "title", "exposure_reason", "risk_type", "compliance", "decision"):
            if not isinstance(row.get(key), str) or not row[key].strip():
                raise ValueError(f"record requires non-empty {key}")
        if row["source"] not in SOURCES or row["risk_type"] not in RISK_LABELS:
            raise ValueError("unknown source or risk_type")
        if type(row.get("repeat")) is not int or row["repeat"] < 1:
            raise ValueError("repeat must be a positive integer")
        score = row.get("attractiveness_score")
        if type(score) not in (int, float) or not math.isfinite(score) or not 1 <= score <= 100:
            raise ValueError("attractiveness_score must be finite in [1, 100]")
        compliance = "Y" if row["risk_type"] == "compliant" else "N"
        decision = "expose" if compliance == "Y" and score > 50 else "rewrite"
        if row["compliance"] != compliance or row["decision"] != decision:
            raise ValueError("record disposition does not match the two-question rule")
        identity = (row["source"], row["round_id"], row["case_id"], row["repeat"])
        if identity in identities:
            raise ValueError("duplicate source/round/case/repeat identity")
        identities.add(identity)
    return records, document.get("metadata", {})


def _group_key(row: dict) -> tuple[str, str, str]:
    return row["source"], row["round_id"], row["case_id"]


def _case_count(records: list[dict]) -> int:
    return len({_group_key(row) for row in records})


def _save(fig: plt.Figure, output: Path, stem: str) -> list[str]:
    paths = []
    for suffix in ("png", "svg"):
        path = output / f"{stem}.{suffix}"
        fig.savefig(path, dpi=220, bbox_inches="tight", pad_inches=0.2)
        paths.append(str(path))
    plt.close(fig)
    return paths


def _clean_axes(ax: plt.Axes) -> None:
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.set_axisbelow(True)


def overview_chart(records: list[dict], output: Path) -> list[str]:
    fig, axes = plt.subplots(1, 2, figsize=(14, 6.4), gridspec_kw={"width_ratios": [1, 1.35]})
    left, right = axes
    present = [source for source in SOURCES if any(r["source"] == source for r in records)]
    labels = []
    for source in present:
        group = [r for r in records if r["source"] == source]
        labels.append(f"{SOURCE_LABELS[source]}\n{_case_count(group)} 个案例 ID / {len(group)} 次调用")
    positions = list(range(len(present)))
    counts = {source: Counter(r["decision"] for r in records if r["source"] == source) for source in present}
    baseline = [0] * len(present)
    for decision in DECISIONS:
        values = [counts[source][decision] for source in present]
        bars = left.barh(positions, values, left=baseline, height=0.48,
                         label=DECISION_LABELS[decision], color=COLORS[decision])
        for index, (bar, value) in enumerate(zip(bars, values)):
            if value:
                left.text(baseline[index] + value / 2, bar.get_y() + bar.get_height() / 2,
                          str(value), ha="center", va="center", color="white", weight="bold", fontsize=12)
        baseline = [start + value for start, value in zip(baseline, values)]
    for y, total in zip(positions, baseline):
        left.annotate(f"{total} 次", (total, y), xytext=(6, 0), textcoords="offset points", va="center", fontsize=10)
    left.set_yticks(positions, labels)
    left.invert_yaxis()
    left.set_xlim(0, max(baseline, default=1) * 1.18)
    left.set_ylim(len(present) - 0.45, -0.55)
    left.set_xlabel("Jev 调用数（含重复）")
    left.set_title("最终处置分布", loc="left", y=1.15, weight="bold")
    left.legend(loc="lower left", bbox_to_anchor=(0, 1.03), frameon=False, ncol=2, fontsize=10)
    left.grid(axis="x", color="#E8EDF2", linewidth=0.8)
    _clean_axes(left)

    risk_positions = list(range(len(RISK_LABELS)))
    height = 0.34 if len(present) == 2 else 0.5
    for index, source in enumerate(present):
        values = [sum(r["source"] == source and r["risk_type"] == risk for r in records) for risk in RISK_LABELS]
        offset = (index - (len(present) - 1) / 2) * height
        bars = right.barh([y + offset for y in risk_positions], values, height=height * 0.88,
                         label=SOURCE_LABELS[source], color=SOURCE_COLORS[source])
        for bar, value in zip(bars, values):
            if value:
                right.annotate(str(value), (value, bar.get_y() + bar.get_height() / 2),
                               xytext=(4, 0), textcoords="offset points", va="center", fontsize=10)
    max_risk = max(Counter(r["risk_type"] for r in records).values())
    right.set_xlim(0, max_risk * 1.16)
    right.set_yticks(risk_positions, list(RISK_LABELS.values()))
    right.invert_yaxis()
    right.set_xlabel("风险选择次数（含重复）")
    right.set_title("风险分型分布", loc="left", y=1.15, weight="bold")
    right.legend(loc="lower left", bbox_to_anchor=(0, 1.03), frameon=False, ncol=2, fontsize=10)
    right.grid(axis="x", color="#E8EDF2", linewidth=0.8)
    _clean_axes(right)
    fig.suptitle("Jev 两题协议 · 多轮测试汇总", fontsize=19, x=0.055, ha="left", weight="bold", y=0.99)
    fig.text(0.055, 0.005, f"合计 {_case_count(records)} 个案例 ID、{len(records)} 次调用；案例 ID 可能含重复内容条件，观察计数不代表审核准确率。",
             fontsize=10, color="#66788A")
    fig.tight_layout(w_pad=3.5, rect=(0, 0.04, 1, 0.91))
    return _save(fig, output, "overview")


def _short(text: str, maximum: int) -> str:
    return text if len(text) <= maximum else text[:maximum - 1] + "…"


def _row_label(rows: list[dict], source: str) -> str:
    row = rows[0]
    if source == "fresh_harness":
        parts = row["title"].split()
        title = parts[1] if len(parts) > 1 else row["title"]
        return f"{row['round_id']} · {_short(title, 15)}\n{row['item_id']} · {_short(row['exposure_reason'], 19)}"
    disclosure = row.get("ai_disclosure", row.get("disclosure", ""))
    suffix = f" · {disclosure}" if disclosure else ""
    return f"{row['case_id']}{suffix}\n{_short(row['exposure_reason'], 22)}"


def stability_chart(records: list[dict], output: Path, source: str) -> list[str]:
    selected = [row for row in records if row["source"] == source]
    grouped: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for row in selected:
        grouped[_group_key(row)].append(row)
    groups = [sorted(rows, key=lambda row: row["repeat"]) for _, rows in sorted(grouped.items())]
    stem = "score_stability" if source == "fresh_harness" else "control_stability"
    title = "新 Harness 推荐 · 重复评分与曝光门槛" if source == "fresh_harness" else "冻结样本与边界对照 · 重复评分"
    if not groups:
        fig, ax = plt.subplots(figsize=(10, 3))
        ax.axis("off")
        ax.text(0.5, 0.5, f"{SOURCE_LABELS[source]}：本轮没有记录", ha="center", va="center", fontsize=17)
        return _save(fig, output, stem)
    fig, ax = plt.subplots(figsize=(13.5, max(5.3, 0.64 * len(groups) + 2.25)))
    ax.axvspan(1, 50, color="#E9AD68", alpha=0.07, zorder=0)
    ax.axvline(50, color="#8A5B2A", linestyle=(0, (4, 3)), linewidth=1.4, zorder=1)
    summary = []
    for y, rows in enumerate(groups):
        scores = [row["attractiveness_score"] for row in rows]
        ax.plot([min(scores), max(scores)], [y, y], color="#9BAABB", linewidth=2.1,
                solid_capstyle="round", zorder=2)
        offsets = [0] if len(rows) == 1 else [0.2 * (index / (len(rows) - 1) - 0.5) for index in range(len(rows))]
        for row, offset in zip(rows, offsets):
            ax.scatter(row["attractiveness_score"], y + offset, s=55,
                       marker="o" if row["compliance"] == "Y" else "X",
                       color=COLORS[row["decision"]], edgecolors="white", linewidths=0.75, zorder=3)
        mean = sum(scores) / len(scores)
        status = "处置一致" if len({row["decision"] for row in rows}) == 1 else "处置有变化"
        summary.append(f"均值 {mean:.2f} · n={len(rows)}\n{min(scores):.2f}–{max(scores):.2f} · {status}")
        ax.text(1.025, y, summary[-1], transform=ax.get_yaxis_transform(),
                va="center", fontsize=9.3, color="#546A80", clip_on=False, linespacing=1.5)
    ax.set_xlim(1, 100)
    ax.set_xticks([1, 20, 40, 50, 60, 80, 100])
    ax.set_ylim(len(groups) - 0.5, -0.6)
    ax.set_yticks(range(len(groups)), [_row_label(rows, source) for rows in groups])
    ax.tick_params(axis="y", length=0, pad=12, labelsize=10)
    ax.set_xlabel("吸引力分（1–100；仅合规 Y 且严格 > 50 才曝光）", labelpad=12)
    ax.grid(axis="x", color="#E5EBF1", linewidth=0.8)
    _clean_axes(ax)
    ax.spines["left"].set_visible(False)
    fig.suptitle(title, fontsize=18, x=0.055, ha="left", weight="bold", y=0.985)
    fig.text(0.055, 0.936, f"{len(groups)} 个案例 ID / {len(selected)} 次调用；横线为同一案例的最小–最大分，散点为每次返回。", fontsize=10.5, color="#66788A")
    handles = [
        Line2D([], [], marker="o", color="none", markerfacecolor=COLORS["expose"], markersize=7, label="曝光"),
        Line2D([], [], marker="o", color="none", markerfacecolor=COLORS["rewrite"], markersize=7, label="需改写"),
        Line2D([], [], marker="X", color="none", markerfacecolor=COLORS["rewrite"], markersize=7, label="风险选项非 compliant（N）"),
        Line2D([], [], color="#8A5B2A", linestyle="--", label="50 分门槛"),
    ]
    fig.legend(handles=handles, loc="lower left", bbox_to_anchor=(0.055, 0.025), frameon=False,
               ncol=2 if len(groups) < 4 else 4, fontsize=10)
    fig.text(0.055, -0.005, "分数反映模型对当前文案的评价，非真实点击率；没有独立人工金标。", fontsize=9.5, color="#66788A")
    fig.subplots_adjust(left=0.315, right=0.80, top=0.885, bottom=0.145)
    return _save(fig, output, stem)


def render(input_path: Path, output_dir: Path) -> dict:
    records, metadata = load_records(input_path)
    configure_style()
    output_dir.mkdir(parents=True, exist_ok=True)
    artifacts = overview_chart(records, output_dir)
    artifacts.extend(stability_chart(records, output_dir, "fresh_harness"))
    artifacts.extend(stability_chart(records, output_dir, "frozen_controls"))
    return {
        "input": str(input_path.resolve()),
        "record_count": len(records),
        "case_count": _case_count(records),
        "source_counts": dict(Counter(row["source"] for row in records)),
        "question_schema_version": metadata.get("question_schema_version"),
        "artifacts": artifacts,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="normalized JSON containing records and metadata")
    parser.add_argument("--output-dir", required=True, type=Path, help="directory for PNG and SVG figures")
    args = parser.parse_args()
    try:
        summary = render(args.input, args.output_dir)
    except (ValueError, OSError) as exc:
        raise SystemExit(f"plot failed: {exc}") from exc
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
