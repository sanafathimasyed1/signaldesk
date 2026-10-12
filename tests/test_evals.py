import csv
import json
import tempfile
import unittest
from pathlib import Path

from evals.human_review import FIELDS, import_labels
from evals.run import load_cases, metrics


class EvalTests(unittest.TestCase):
    def test_failed_predictions_count_as_incorrect(self):
        result = metrics([{"expected": "review", "decision": None},
                          {"expected": "monitor", "decision": "monitor"}])
        self.assertEqual(result["accuracy"], .5)
        self.assertEqual(result["classes"]["review"]["recall"], 0)

    def test_blank_label_sheet_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            (directory / "contexts.json").write_text(json.dumps([{"id": "H01"}]), encoding="utf-8")
            with (directory / "labels.csv").open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=FIELDS)
                writer.writeheader()
                writer.writerow({"id": "H01"})
            with self.assertRaises(ValueError):
                import_labels(directory)
            self.assertFalse((directory / "human-labeled.jsonl").exists())

    def test_complete_labels_import_with_provenance(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            cases = [{"id": f"H{index:02}", "eligible": True, "age_days": 2,
                      "ownership_verified": False, "signals": []} for index in range(20)]
            (directory / "contexts.json").write_text(json.dumps(cases), encoding="utf-8")
            with (directory / "labels.csv").open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=FIELDS)
                writer.writeheader()
                writer.writerows({"id": case["id"], "label": "monitor", "confidence": "medium",
                                  "reason": "Fixture: no source clues", "reviewer": "test fixture only",
                                  "reviewed_at": "2026-10-12T12:00:00Z"} for case in cases)
            import_labels(directory)
            actual = load_cases(directory / "human-labeled.jsonl")
            self.assertEqual(len(actual), 20)
            self.assertEqual(actual[0]["reviewer"], "test fixture only")

    def test_incomplete_expected_labels_fail_before_inference(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "cases.jsonl"
            path.write_text(json.dumps({"id": "H01", "expected": "", "why": ""}), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_cases(path)


if __name__ == "__main__":
    unittest.main()
