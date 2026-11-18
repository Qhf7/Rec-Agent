import os
from pathlib import Path
import subprocess
import sys

from canonical_data import load_canonical_items

ROOT = Path(__file__).resolve().parents[1]


def test_import_and_help_never_generate_artifacts(tmp_path):
    env = dict(os.environ, PYTHONPATH=str(ROOT))
    subprocess.run([sys.executable, "-c", "import generate_pilot_candidates"], cwd=tmp_path, env=env, check=True, capture_output=True)
    result = subprocess.run([sys.executable, str(ROOT / "generate_pilot_candidates.py"), "--help"], cwd=tmp_path, check=True, capture_output=True, text=True)
    assert "--candidates" in result.stdout
    assert not list(tmp_path.iterdir())


def test_pilot_reasons_and_labels_match_canonical_snapshots():
    from generate_pilot_candidates import build_pilot_dataset
    from run_rule_baseline import evaluate_candidate, load_lexicon

    candidates, labels = build_pilot_dataset()
    items = load_canonical_items()
    assert len(candidates) == len(labels) == 40
    by_id = {row["reason_id"]: row for row in labels}
    for row in candidates:
        item = items[row["item_id"]]
        assert row["item_attrs_returned"]["title"] == item["title"]
        assert row["generated_reason"] == row["exposure_reason"]
        assert row["evidence_fields"]
        if row["source"] == "natural":
            assert item["category_l3"] in row["generated_reason"]
            assert item["functions"][0] in row["generated_reason"]
        actual = evaluate_candidate(row, load_lexicon(ROOT / "data/raw/compliance_lexicon.txt"))
        assert actual["decision"] == by_id[row["reason_id"]]["gold_decision"]
        assert actual["risk_type"] == by_id[row["reason_id"]]["gold_risk_type"]
