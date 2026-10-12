"""Run exact same deterministic/LLM triage and tracing path against small eval JSONL."""

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from salesintel.ai import run_triage
from salesintel.storage import connect, initialize

CORPUS = Path(__file__).resolve().parent / "labeled-v1.jsonl"
RESULTS = Path(__file__).resolve().parent / "results"
CLASSES = ("review", "research", "monitor")


def load_cases(path):
    cases = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not cases:
        raise ValueError("Evaluation set is empty")
    ids = set()
    for case in cases:
        if case.get("expected") not in CLASSES or not case.get("why"):
            raise ValueError("Every evaluation case needs a valid expected label and review rationale")
        if case.get("id") in ids or not case.get("id"):
            raise ValueError("Evaluation IDs must be present and unique")
        ids.add(case["id"])
    return cases


def metrics(rows):
    total = len(rows)
    correct = sum(row["decision"] == row["expected"] for row in rows)
    by_class = {}
    for category in CLASSES:
        tp = sum(row["decision"] == category and row["expected"] == category for row in rows)
        fp = sum(row["decision"] == category and row["expected"] != category for row in rows)
        fn = sum(row["decision"] != category and row["expected"] == category for row in rows)
        precision = tp / (tp + fp) if tp + fp else 0
        recall = tp / (tp + fn) if tp + fn else 0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0
        by_class[category] = {"precision": round(precision, 4), "recall": round(recall, 4),
                              "f1": round(f1, 4), "support": tp + fn}
    return {"accuracy": round(correct / total, 4) if total else 0,
            "macro_f1": round(sum(item["f1"] for item in by_class.values()) / len(CLASSES), 4),
            "n": total, "classes": by_class}


def run(version, mode, cases):
    with connect() as db:
        first_row = db.execute("SELECT COALESCE(MAX(rowid),0) FROM traces").fetchone()[0]
    output = []
    failures = 0
    for case in cases:
        try:
            result = run_triage({key: case[key] for key in
                                ("eligible", "age_days", "ownership_verified", "signals")},
                               version, mode=mode, account_id="eval:" + case["id"])
            output.append({**case, "decision": result["decision"], "accepted": True,
                           "evidence_ids": result["evidence_ids"], "trace_id": result["trace_id"],
                           "cost_usd": result["cost_usd"]})
            failures += result["decision"] != case["expected"]
        except (RuntimeError, ValueError, TimeoutError) as error:
            # Errors are not correct predictions, safe defaults, or hidden fallbacks.
            output.append({**case, "decision": None, "accepted": False,
                           "error": f"{type(error).__name__}: {error}"})
            failures += 1
    scores = metrics(output)
    with connect() as db:
        usage = db.execute("SELECT COALESCE(SUM(cost_usd),0), AVG(latency_ms) FROM traces "
                           "WHERE rowid>? AND prompt_version=? AND mode=?",
                           (first_row, version, mode)).fetchone()
    return {"prompt_version": version, "mode": mode, "failures_including_errors": failures,
            "metrics": scores, "results": output,
            "unsupported_evidence_ids": sum(
                not set(row.get("evidence_ids", [])).issubset(
                    {key for signal in row.get("signals", []) for key in signal["evidence_ids"]})
                for row in output),
            "acceptance_rate": round(sum(row.get("accepted", False) for row in output) / len(output), 4),
            "cost_usd": round(usage[0], 8), "mean_latency_ms": round(usage[1], 2) if usage[1] is not None else None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("offline", "live"), default="offline")
    parser.add_argument("--db", default=str(ROOT / "var" / "evals.sqlite"))
    parser.add_argument("--dataset", type=Path, default=CORPUS)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.mode == "live" and not os.getenv("OPENAI_API_KEY"):
        parser.error("--mode live requires OPENAI_API_KEY; offline is not a simulated LLM result")
    os.environ["SIGNALDESK_DB"] = args.db
    initialize()
    try:
        cases = load_cases(args.dataset)
    except (ValueError, OSError) as error:
        parser.error(str(error))
    corpus_hash = hashlib.sha256(args.dataset.read_bytes()).hexdigest()
    results = {version: run(version, args.mode, cases) for version in ("v1", "v2")}
    previous_path = args.output or RESULTS / (
        "latest.json" if args.mode == "offline" and args.dataset == CORPUS
        else f"{args.mode}-{args.dataset.stem}-latest.json")
    previous = None
    if previous_path.exists():
        try:
            previous = json.loads(previous_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            print("Previous evaluation is unreadable; replacing with current measured run.", file=sys.stderr)
    comparable = previous and previous.get("mode") == args.mode and previous.get("corpus_sha256") == corpus_hash
    prior_v2 = previous.get("prompts", {}).get("v2", {}).get("metrics") if comparable else None
    for version, result in results.items():
        result["prompt_sha256"] = hashlib.sha256(
            (ROOT / "prompts" / "evidence-triage" / f"{version}.txt").read_bytes()).hexdigest()
    current = {
        "evaluated_at": datetime.now(timezone.utc).isoformat(), "mode": args.mode,
        "corpus": args.dataset.name, "corpus_sha256": corpus_hash,
        "corpus_caveat": ("Illustrative rule-policy cases, authored/reviewed by AI coding agent; "
                          "not independent human labels or field performance." if args.dataset == CORPUS else
                          "User-supplied labels; reviewer provenance is recorded per case. "
                          "Small stratified sample, not representative production traffic."),
        "prompts": results,
        "v2_delta_from_previous": ({
            "previous_evaluated_at": previous.get("evaluated_at"),
            "accuracy": round(results["v2"]["metrics"]["accuracy"] - prior_v2["accuracy"], 4),
            "macro_f1": round(results["v2"]["metrics"]["macro_f1"] - prior_v2["macro_f1"], 4),
        } if prior_v2 else None),
    }
    previous_path.parent.mkdir(parents=True, exist_ok=True)
    previous_path.write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")
    print(f"Mode: {args.mode} (offline is deterministic policy, not an LLM)")
    for version in ("v1", "v2"):
        result = results[version]
        print(f"\nPrompt {version}: accuracy {result['metrics']['accuracy']:.0%} | "
              f"macro-F1 {result['metrics']['macro_f1']:.3f} | "
              f"accepted {result['acceptance_rate']:.0%} | failures incl. errors "
              f"{result['failures_including_errors']}/{result['metrics']['n']} | "
              f"cost ${result['cost_usd']:.6f}")
        for category, scores in result["metrics"]["classes"].items():
            print(f"  {category:8} P={scores['precision']:.3f} "
                  f"R={scores['recall']:.3f} F1={scores['f1']:.3f} n={scores['support']}")
    if current["v2_delta_from_previous"]:
        delta = current["v2_delta_from_previous"]
        print(f"\nv2 vs previous run: accuracy {delta['accuracy']:+.1%}; "
              f"macro-F1 {delta['macro_f1']:+.3f}")
    else:
        print("\nNo previous comparison for this output path; this run establishes the baseline.")
    print(f"\nJSON, prompt hashes, sample decisions and per-request traces: {previous_path}")
    if args.mode == "live":
        print("Live cost is provider-reported usage at the configured rate; values are not prediction or safety truth.")
    # Quality differences surface as exit status; subsequent comparison still saves the measurements.
    return int(results["v2"]["failures_including_errors"] > 0 or
               results["v2"]["unsupported_evidence_ids"] > 0)


if __name__ == "__main__":
    raise SystemExit(main())
