"""Run a small, deterministic field-extraction benchmark on repository fixtures."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from change_order_extractor.cli import _read_input
from change_order_extractor.extractor import extract_text


def run_evaluation() -> dict[str, Any]:
    cases = json.loads((ROOT / "eval" / "cases.json").read_text(encoding="utf-8"))
    total = correct = 0
    per_field: dict[str, dict[str, int]] = {}
    failures: list[dict[str, Any]] = []

    for case in cases:
        source_path = ROOT / case["input"]
        if source_path.suffix.casefold() == ".pdf":
            text, pages = _read_input(source_path)
        else:
            text = source_path.read_text(encoding="utf-8", errors="replace")
            pages = None
        result = extract_text(text, source=source_path.name, page_texts=pages)
        for field, expected in case["expected"].items():
            actual = result["fields"][field]["value"]
            match = actual == expected
            total += 1
            correct += int(match)
            counts = per_field.setdefault(field, {"correct": 0, "total": 0})
            counts["correct"] += int(match)
            counts["total"] += 1
            if not match:
                failures.append({
                    "case": case["name"], "field": field, "expected": expected,
                    "actual": actual, "evidence": result["fields"][field]["evidence"],
                })
        if not result["validation"]["valid"]:
            failures.append({"case": case["name"], "validation_errors": result["validation"]["errors"]})

    return {
        "cases": len(cases),
        "field_checks": total,
        "exact_matches": correct,
        "exact_match_rate": correct / total if total else 1.0,
        "per_field": per_field,
        "failures": failures,
        "note": "Controlled repository fixtures only; this is not an estimate of accuracy on customer documents.",
    }


def main() -> int:
    report = run_evaluation()
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if not report["failures"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
