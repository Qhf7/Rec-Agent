#!/usr/bin/env python3
"""Build the public GitHub Pages demo from an explicit static-file allowlist."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""}:
    sys.path.insert(0, str(ROOT))

from canonical_data import load_canonical_items, load_canonical_users
from scripts.strict_json_output import strict_json_loads

FILES = ("index.html", "styles.css", "app.js", "static-api.js", "assets/mark.svg", "data/sample-runs.json")


def build(output: Path) -> dict:
    output = output.resolve()
    if output == ROOT or ROOT.is_relative_to(output) or output.is_relative_to(ROOT / "web"):
        raise ValueError("build output must not overwrite the repository or web sources")
    if output.exists() and any(output.iterdir()):
        raise ValueError("output directory must be new or empty")
    source = ROOT / "web"
    samples = strict_json_loads((source / "data/sample-runs.json").read_text(encoding="utf-8"))["samples"]
    for sample in samples:
        for card in sample["recommendations"]:
            audit = card["jev_audit"]
            expected = "expose" if audit["risk_type"] == "compliant" and audit["attractiveness_score"] > 50 else "rewrite"
            if audit["decision"] != expected:
                raise ValueError("saved audit does not match the current disposition contract")
    output.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        destination = output / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / name, destination)
    html = (output / "index.html").read_text(encoding="utf-8")
    marker = '<meta name="rec-agent-hosting" content="local">'
    if html.count(marker) != 1:
        raise ValueError("missing or duplicate deployment metadata")
    (output / "index.html").write_text(html.replace(marker, '<meta name="rec-agent-hosting" content="github-pages">'), encoding="utf-8")
    index = {"user_ids": sorted(load_canonical_users()), "user_count": len(load_canonical_users()),
             "item_count": len(load_canonical_items()), "scenario_date": "2026-06-15"}
    (output / "data/user-index.json").write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / ".nojekyll").touch()
    return {"output": str(output), "files": len(list(output.rglob("*.*"))), "sample_users": len(samples),
            "hosting": "github-pages", "new_model_calls": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "runs/github-pages")
    args = parser.parse_args()
    print(json.dumps(build(args.output), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
