#!/usr/bin/env python3
"""Compatibility command for replaying Jev model dispositions from frozen responses."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""}:
    sys.path.insert(0, str(ROOT))

from scripts.replay_jev_model_decisions import replay_model_decisions


def calibrate_policy(comparison_dir: str | Path, output_dir: str | Path, *,
                     human_labels: str | Path | None = None, fixture_path: str | Path | None = None,
                     thresholds: list[float] | None = None, max_unsafe_exposure_rate: float | None = None,
                     ai_disclosure: str | None = None) -> dict:
    """Preserve the former entry point while producing model disposition replay."""
    if any(value is not None for value in (human_labels, fixture_path, thresholds, max_unsafe_exposure_rate, ai_disclosure)):
        raise ValueError("Jev Q7 determines disposition; use replay without local threshold or label-selection options")
    return replay_model_decisions(comparison_dir, output_dir)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--comparison-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    try:
        report = calibrate_policy(args.comparison_dir, args.output_dir)
    except (OSError, ValueError) as error:
        raise SystemExit(f"replay failed: {error}") from error
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["error_count"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
