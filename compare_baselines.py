"""Compare rule and Jev results on the same pilot samples."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from run_rule_baseline import evaluate_report


def load_jsonl(path: str | Path) -> list[dict]:
    with Path(path).open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def compare_results(rule_results: list[dict], jev_results: list[dict], labels: list[dict]) -> dict:
    rule_by_id = {row["reason_id"]: row for row in rule_results}
    jev_by_id = {row["reason_id"]: row for row in jev_results}
    label_by_id = {row["reason_id"]: row for row in labels}
    ids = sorted(set(rule_by_id) & set(jev_by_id) & set(label_by_id))
    cases = []
    for reason_id in ids:
        rule = rule_by_id[reason_id]
        jev = jev_by_id[reason_id]
        gold = label_by_id[reason_id]
        if rule["decision"] != jev["decision"] or rule["risk_type"] != jev["risk_type"]:
            cases.append(
                {
                    "reason_id": reason_id,
                    "gold_decision": gold["gold_decision"],
                    "gold_risk_type": gold["gold_risk_type"],
                    "rule_decision": rule["decision"],
                    "rule_risk_type": rule["risk_type"],
                    "jev_decision": jev["decision"],
                    "jev_risk_type": jev["risk_type"],
                    "rule_score": rule["judge_score"],
                    "jev_score": jev.get("judge_score"),
                    **({"attractiveness_score": jev["attractiveness_score"]} if "attractiveness_score" in jev else {}),
                }
            )

    rule_eval = evaluate_report(rule_results, labels, model_version="rule-baseline-v1", score_name="rule-compliance-v1")
    jev_eval = evaluate_report(jev_results, labels)
    return {
        "sample_count": len(ids),
        "decision_disagreements": sum(
            rule_by_id[i]["decision"] != jev_by_id[i]["decision"] for i in ids
        ),
        "risk_type_disagreements": sum(
            rule_by_id[i]["risk_type"] != jev_by_id[i]["risk_type"] for i in ids
        ),
        "rule_evaluation": rule_eval,
        "jev_evaluation": jev_eval,
        "cases": cases,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rule", default="result_rule_baseline.jsonl")
    parser.add_argument("--jev", default="result_jev.jsonl")
    parser.add_argument("--labels", default="dev_labels.csv")
    parser.add_argument("--output", default="baseline_comparison_report.json")
    parser.add_argument("--markdown", default="baseline_comparison_report.md")
    args = parser.parse_args()

    rule_results = load_jsonl(args.rule)
    jev_results = load_jsonl(args.jev)
    with Path(args.labels).open(encoding="utf-8-sig", newline="") as handle:
        labels = list(csv.DictReader(handle))
    report = compare_results(rule_results, jev_results, labels)
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# 规则基线与 Jev Pilot 对比",
        "",
        f"样本数：{report['sample_count']}",
        f"决策不一致：{report['decision_disagreements']}",
        f"风险分型不一致：{report['risk_type_disagreements']}",
        "",
        "| 指标 | 规则基线 | Jev |",
        "|---|---:|---:|",
        f"| 违规漏放率 | {report['rule_evaluation']['violation_leak_rate']:.4f} | {report['jev_evaluation']['violation_leak_rate']:.4f} |",
        f"| 决策宏 F1 | {report['rule_evaluation']['decision_macro_f1']:.4f} | {report['jev_evaluation']['decision_macro_f1']:.4f} |",
        f"| 风险分型准确率 | {report['rule_evaluation']['risk_type_accuracy']:.4f} | {report['jev_evaluation']['risk_type_accuracy']:.4f} |",
        f"| 人工审核率 | {report['rule_evaluation']['human_review_rate']:.4f} | {report['jev_evaluation']['human_review_rate']:.4f} |",
        f"| 证据非空率 | {report['rule_evaluation']['evidence_nonempty_rate']:.4f} | {report['jev_evaluation']['evidence_nonempty_rate']:.4f} |",
        "",
        "## 不一致样本",
        "",
    ]
    for case in report["cases"]:
        lines.append(
            f"- `{case['reason_id']}`：gold={case['gold_decision']}/{case['gold_risk_type']}；"
            f"rule={case['rule_decision']}/{case['rule_risk_type']}；"
            f"jev={case['jev_decision']}/{case['jev_risk_type']}"
        )
    Path(args.markdown).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
