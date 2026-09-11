#!/usr/bin/env python3
"""
RateGuard AI — Golden Set Calibration Harness (Phase 2.0.3).
Scoreboard for the 90% -> 95% -> 98% precision trajectory (PRD §10).

Executes full deterministic validation & audit pipeline over benchmark golden fixtures:
- Extraction self-validation (Phase 2.0.1)
- Deterministic checks (DUP, RATE, FSC, ARITH)
- Compares against ground-truth human-labeled annotations and planted errors
- Enforces CI Gate: Precision >= 90.0% and Recall >= 80.0%
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

# Ensure root and packages are in sys.path
root_dir = Path(__file__).resolve().parents[1]
audit_engine_dir = root_dir / "packages" / "audit-engine"
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))
if str(audit_engine_dir) not in sys.path:
    sys.path.insert(0, str(audit_engine_dir))

from engine import check_arithmetic, check_duplicates, check_fsc, check_rates
from validation import validate_invoice_extraction
from packages.schemas.models import (
    CalibrationMetric,
    FSCEntry,
    InvoiceJSON,
    RateMatrixJSON,
)


def get_git_commit_sha() -> str:
    """Retrieve current Git commit SHA or fallback."""
    try:
        output = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=str(root_dir), stderr=subprocess.DEVNULL)
        return output.decode("utf-8").strip()
    except Exception:
        return "development-head"


def load_golden_fixtures(fixtures_dir: Path) -> List[Dict[str, Any]]:
    """Loads all JSON golden fixture files from directory."""
    fixtures = []
    if not fixtures_dir.exists():
        print(f"Error: Fixtures directory not found at {fixtures_dir}", file=sys.stderr)
        sys.exit(1)

    for file_path in sorted(fixtures_dir.glob("*.json")):
        if file_path.name.startswith("latest_") or file_path.name.startswith("report_"):
            continue
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if "carrier" in data and "cases" in data:
                fixtures.append(data)
    return fixtures


def run_calibration(
    fixtures: List[Dict[str, Any]],
    output_json_path: Path = None
) -> Tuple[bool, Dict[str, Any]]:
    """
    Executes audit engine on all fixtures and computes precision/recall per check and carrier.
    Returns: (gate_passed, results_payload)
    """
    CHECK_TYPES = ["DUP", "RATE", "FSC", "ARITH"]

    # Counters: [category][name][metric]
    metrics_by_check: Dict[str, Dict[str, int]] = {c: {"tp": 0, "fp": 0, "fn": 0, "tn": 0} for c in CHECK_TYPES}
    metrics_by_carrier: Dict[str, Dict[str, int]] = {}
    overall_counts = {"tp": 0, "fp": 0, "fn": 0, "tn": 0}
    total_invoices_audited = 0

    all_case_details = []

    for fixture in fixtures:
        carrier_name = fixture["carrier"]
        contract_data = fixture["contract"]
        contract = RateMatrixJSON(**contract_data)
        fsc_tables = [FSCEntry(**f) for f in fixture.get("fsc_tables", [])]
        eia_diesel_price = fixture.get("eia_diesel_price", None)

        if carrier_name not in metrics_by_carrier:
            metrics_by_carrier[carrier_name] = {"tp": 0, "fp": 0, "fn": 0, "tn": 0}

        # Build list of InvoiceJSON objects for this carrier batch
        cases = fixture.get("cases", [])
        invoices: List[InvoiceJSON] = []
        for case in cases:
            inv = InvoiceJSON(**case["invoice"])
            invoices.append(inv)

        # Audit each invoice in the batch
        for case, invoice in zip(cases, invoices):
            total_invoices_audited += 1
            case_id = case["id"]
            planted_errors = set(case.get("planted_errors", []))

            # 1. Extraction Self-Validation (Phase 2.0.1)
            val_res = validate_invoice_extraction(invoice)

            # 2. Audit Engine Execution
            flags_dup = check_duplicates(invoice, invoices)
            flags_rate = check_rates(invoice, [contract])
            flags_fsc = check_fsc(invoice, fsc_tables, eia_diesel_price)
            flags_arith = check_arithmetic(invoice)

            all_flags = flags_dup + flags_rate + flags_fsc + flags_arith
            flagged_types = {f.check_type for f in all_flags}

            # Evaluate each check type for this invoice
            for c_type in CHECK_TYPES:
                has_planted = c_type in planted_errors
                was_flagged = c_type in flagged_types

                if has_planted and was_flagged:
                    # True Positive
                    metrics_by_check[c_type]["tp"] += 1
                    metrics_by_carrier[carrier_name]["tp"] += 1
                    overall_counts["tp"] += 1
                elif not has_planted and was_flagged:
                    # False Positive
                    metrics_by_check[c_type]["fp"] += 1
                    metrics_by_carrier[carrier_name]["fp"] += 1
                    overall_counts["fp"] += 1
                elif has_planted and not was_flagged:
                    # False Negative
                    metrics_by_check[c_type]["fn"] += 1
                    metrics_by_carrier[carrier_name]["fn"] += 1
                    overall_counts["fn"] += 1
                else:
                    # True Negative
                    metrics_by_check[c_type]["tn"] += 1
                    metrics_by_carrier[carrier_name]["tn"] += 1
                    overall_counts["tn"] += 1

            all_case_details.append({
                "case_id": case_id,
                "carrier": carrier_name,
                "confidence": val_res.composite_confidence,
                "validation_passed": val_res.is_valid,
                "planted_errors": list(planted_errors),
                "flagged_checks": list(flagged_types),
                "flags": [f.model_dump() for f in all_flags]
            })

    # Helper function to compute precision, recall, f1
    def calc_metrics(counts: Dict[str, int]) -> Dict[str, float]:
        tp = counts["tp"]
        fp = counts["fp"]
        fn = counts["fn"]
        precision = (tp / (tp + fp)) * 100.0 if (tp + fp) > 0 else 100.0
        recall = (tp / (tp + fn)) * 100.0 if (tp + fn) > 0 else 100.0
        f1 = (2 * precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0
        return {
            "precision": round(precision, 2),
            "recall": round(recall, 2),
            "f1": round(f1, 2),
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "tn": counts.get("tn", 0),
        }

    overall_metrics = calc_metrics(overall_counts)
    check_metrics = {c: calc_metrics(metrics_by_check[c]) for c in CHECK_TYPES}
    carrier_metrics = {k: calc_metrics(v) for k, v in metrics_by_carrier.items()}

    # Phase 2.0 Gate Criteria: Precision >= 90.0% and Recall >= 80.0%
    gate_passed = (overall_metrics["precision"] >= 90.0) and (overall_metrics["recall"] >= 80.0)

    # CLI Scoreboard Formatting
    print("=" * 80)
    print("RATEGUARD AI — CALIBRATION HARNESS SCOREBOARD (PHASE 2.0.3)")
    print(f"Commit SHA: {get_git_commit_sha()[:8]} | Total Invoices Audited: {total_invoices_audited}")
    print("=" * 80)
    print(f"{'CHECK TYPE':<15} | {'TP':<4} | {'FP':<4} | {'FN':<4} | {'TN':<4} | {'PRECISION':<10} | {'RECALL':<10} | {'F1':<6}")
    print("-" * 80)
    for c_type in CHECK_TYPES:
        m = check_metrics[c_type]
        print(f"{c_type:<15} | {m['tp']:<4} | {m['fp']:<4} | {m['fn']:<4} | {m['tn']:<4} | {m['precision']:>8.1f}% | {m['recall']:>8.1f}% | {m['f1']:>5.1f}")
    print("-" * 80)

    print(f"\n{'CARRIER':<15} | {'TP':<4} | {'FP':<4} | {'FN':<4} | {'TN':<4} | {'PRECISION':<10} | {'RECALL':<10} | {'F1':<6}")
    print("-" * 80)
    for carrier, m in carrier_metrics.items():
        print(f"{carrier:<15} | {m['tp']:<4} | {m['fp']:<4} | {m['fn']:<4} | {m['tn']:<4} | {m['precision']:>8.1f}% | {m['recall']:>8.1f}% | {m['f1']:>5.1f}")
    print("=" * 80)

    status_str = "GATE PASSED [GO FOR PHASE 3]" if gate_passed else "GATE FAILED [DO NOT PROCEED]"
    print(f"\nOVERALL ACCURACY: Precision: {overall_metrics['precision']:.1f}% (Gate >= 90%) | Recall: {overall_metrics['recall']:.1f}% (Gate >= 80%)")
    print(f"DECISION: {status_str}\n")

    payload = {
        "commit_sha": get_git_commit_sha(),
        "golden_set_version": "v1.0.0",
        "total_invoices_audited": total_invoices_audited,
        "gate_passed": gate_passed,
        "overall": overall_metrics,
        "checks": check_metrics,
        "carriers": carrier_metrics,
        "cases": all_case_details,
    }

    if output_json_path:
        with open(output_json_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        print(f"Scoreboard saved to {output_json_path}")

    return gate_passed, payload


def main():
    parser = argparse.ArgumentParser(description="RateGuard AI Golden Set Calibration Harness")
    parser.add_argument(
        "--fixtures-dir",
        type=Path,
        default=root_dir / "fixtures" / "golden",
        help="Path to directory containing golden fixture JSON files"
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=root_dir / "fixtures" / "golden" / "latest_run.json",
        help="Path to output calibration scoreboard JSON"
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        default=True,
        help="Exit with non-zero status code if precision < 90%% or recall < 80%%"
    )
    args = parser.parse_args()

    fixtures = load_golden_fixtures(args.fixtures_dir)
    gate_passed, _ = run_calibration(fixtures, args.output_json)

    if args.strict and not gate_passed:
        print("Calibration Gate check failed. Precision >= 90.0% and Recall >= 80.0% required.", file=sys.stderr)
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
