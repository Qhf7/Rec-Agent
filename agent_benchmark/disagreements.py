"""Describe matched model/Jev agreement without treating Jev as ground truth."""
from __future__ import annotations

from collections import Counter
import json
from pathlib import Path


def trajectory_agreement(results: list[dict], baseline: str = "jev") -> dict:
    indexed = {}
    for result in results:
        key = (result["case_id"], result["kind"], result.get("repeat", 1))
        if key in indexed:
            raise ValueError("duplicate evaluator/case/repeat")
        indexed[key] = result
    names = sorted({r["kind"] for r in results} - {baseline})
    comparisons = {}
    for name in names:
        pairs, missing = [], []
        cases = sorted({(r["case_id"], r.get("repeat", 1)) for r in results})
        for case_id, repeat in cases:
            model = indexed.get((case_id, name, repeat))
            jev = indexed.get((case_id, baseline, repeat))
            if not model or not jev or model.get("status") != "ok" or jev.get("status") != "ok":
                missing.append({"case_id": case_id, "repeat": repeat,
                                "model_status": model.get("status") if model else "missing",
                                "jev_status": jev.get("status") if jev else "missing"})
                continue
            if model["input_sha256"] != jev["input_sha256"]:
                raise ValueError("paired evaluator inputs differ")
            if model["reference"] != jev["reference"]:
                raise ValueError("paired executable references differ")
            keys = set(model["choices"])
            if keys != set(jev["choices"]):
                raise ValueError("paired question keys differ")
            differences = {}
            for key in sorted(keys):
                if model["choices"][key] == jev["choices"][key]:
                    continue
                truth = model["reference"][key]
                differences[key] = {"model": model["choices"][key], "jev": jev["choices"][key],
                                    "programmatic_reference": truth,
                                    "model_matches_reference": model["choices"][key] == truth,
                                    "jev_matches_reference": jev["choices"][key] == truth}
            pairs.append({"case_id": case_id, "repeat": repeat, "differences": differences,
                          "all_answers_equal": not differences})
        question_keys = sorted({key for r in results if r["kind"] == name for key in r.get("choices", {})})
        comparisons[name] = {
            "baseline": baseline, "planned_pairs": len(cases), "valid_pairs": len(pairs),
            "missing_pairs": missing, "all_answers_equal_pairs": sum(r["all_answers_equal"] for r in pairs),
            "all_answers_equal_rate_valid": sum(r["all_answers_equal"] for r in pairs) / len(pairs) if pairs else None,
            "per_question": {key: {
                "equal_pairs": sum(key not in pair["differences"] for pair in pairs),
                "agreement_rate_valid": sum(key not in pair["differences"] for pair in pairs) / len(pairs) if pairs else None,
                "model_only_matches_reference": sum(pair["differences"].get(key, {}).get("model_matches_reference") is True
                    and pair["differences"][key]["jev_matches_reference"] is False for pair in pairs),
                "jev_only_matches_reference": sum(pair["differences"].get(key, {}).get("jev_matches_reference") is True
                    and pair["differences"][key]["model_matches_reference"] is False for pair in pairs),
                "neither_matches_reference": sum(key in pair["differences"] and not pair["differences"][key]["model_matches_reference"]
                    and not pair["differences"][key]["jev_matches_reference"] for pair in pairs)
            } for key in question_keys},
            "disagreements": [pair for pair in pairs if pair["differences"]]}
    return {"baseline": baseline, "interpretation": "Jev agreement is not accuracy; executable contract reference is a separate comparator.",
            "comparisons": comparisons}


def write_trajectory_agreement(run: str | Path, output: str | Path) -> dict:
    run, output = Path(run), Path(output)
    output.mkdir(parents=True, exist_ok=True)
    result = trajectory_agreement(json.loads((run / "results.json").read_text()))
    (output / "jev-agreement.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    return result
