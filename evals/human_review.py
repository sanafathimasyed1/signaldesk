"""Prepare blind real-data cases, then import completed human labels without guessing."""

import argparse
import csv
import json
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from salesintel.accounts import build_accounts
from salesintel.ai import context_for

DIRECTORY = ROOT / "evals" / "human-review"
FIELDS = ["id", "label", "confidence", "reason", "reviewer", "reviewed_at"]


def prepare(directory):
    if directory.exists():
        raise ValueError("Review packet already exists. Keep it frozen; choose --directory for a new set.")
    with (ROOT / "data" / "observations.jsonl").open(encoding="utf-8") as source:
        accounts = build_accounts(json.loads(line) for line in source if line.strip())
    groups = [
        [account for account in accounts if account["eligible"] and
         any(signal["weight"] >= 25 for signal in account["signals"])],
        [account for account in accounts if account["eligible"] and
         account["signal_score"] > 0 and not any(signal["weight"] >= 25 for signal in account["signals"])],
        [account for account in accounts if account["eligible"] and account["signal_score"] == 0],
        [account for account in accounts if not account["eligible"]],
    ]
    rng = random.Random(20261012)
    selected = []
    for group, limit in zip(groups, (4, 8, 6, 6)):
        selected.extend(rng.sample(group, min(limit, len(group))))
    if len(selected) < 20:
        raise ValueError("Not enough cases for a 20-30 example review set")
    rng.shuffle(selected)
    directory.mkdir(parents=True)
    packets, contexts = [], []
    prepared_at = datetime.now(timezone.utc).isoformat()
    for index, account in enumerate(selected, 1):
        case_id = f"H{index:02}"
        # A reviewer sees source evidence, not scores, predictions, weights or model text.
        packets.append({"id": case_id, "candidate": account["name"], "provider": account["provider"],
                        "attribution": account["attribution"], "prepared_at": prepared_at,
                        "evidence": account["evidence"]})
        contexts.append({"id": case_id, "account_id": account["id"], **context_for(account)})
    (directory / "blind-packet.json").write_text(json.dumps(packets, indent=2) + "\n", encoding="utf-8")
    (directory / "contexts.json").write_text(json.dumps(contexts, indent=2) + "\n", encoding="utf-8")
    with (directory / "labels.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows({"id": case["id"]} for case in packets)
    print(f"Prepared {len(packets)} real-data cases in {directory}.")
    print("Read blind-packet.json only while labelling. Fill labels.csv yourself; do not read contexts.json.")


def import_labels(directory):
    contexts = json.loads((directory / "contexts.json").read_text(encoding="utf-8"))
    with (directory / "labels.csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    expected_ids = {case["id"] for case in contexts}
    ids = [row.get("id") for row in rows]
    if len(ids) != len(set(ids)) or set(ids) != expected_ids:
        raise ValueError("Labels must match every packet ID exactly once")
    by_id = {}
    for row in rows:
        if row.get("label") not in {"review", "research", "monitor", "insufficient"}:
            raise ValueError(f"{row['id']}: supply review, research, monitor or insufficient")
        if row.get("confidence") not in {"low", "medium", "high"}:
            raise ValueError(f"{row['id']}: confidence must be low, medium or high")
        if not row.get("reason", "").strip() or not row.get("reviewer", "").strip():
            raise ValueError(f"{row['id']}: reviewer and reason are required; never invent human provenance")
        datetime.fromisoformat(row.get("reviewed_at", "").replace("Z", "+00:00"))
        by_id[row["id"]] = row
    accepted = [case for case in contexts if by_id[case["id"]]["label"] != "insufficient"]
    if not 20 <= len(accepted) <= 30:
        raise ValueError("Need 20-30 evaluable human labels; collect more cases if too many are insufficient")
    output = directory / "human-labeled.jsonl"
    with output.open("w", encoding="utf-8", newline="\n") as handle:
        for case in accepted:
            row = by_id[case["id"]]
            handle.write(json.dumps({**case, "expected": row["label"], "why": row["reason"],
                                     "reviewer": row["reviewer"], "reviewed_at": row["reviewed_at"],
                                     "confidence": row["confidence"]}) + "\n")
    print(f"Imported {len(accepted)} human labels; {len(contexts)-len(accepted)} insufficient cases excluded.")
    print(f"Run: python evals\\run.py --dataset \"{output}\" --mode live")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "import"))
    parser.add_argument("--directory", type=Path, default=DIRECTORY)
    args = parser.parse_args()
    try:
        (prepare if args.action == "prepare" else import_labels)(args.directory)
    except (ValueError, OSError, KeyError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
