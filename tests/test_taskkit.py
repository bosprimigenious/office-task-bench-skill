"""Behavioral regressions for offline task-package tooling."""

from __future__ import annotations

from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "taskkit.py"
SPEC = importlib.util.spec_from_file_location("taskkit", SCRIPT)
taskkit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(taskkit)


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.write("prompt.md", "Review all invoices and give a reconciled payment decision.")
        self.write("inputs/invoice.csv", "id,amount\nA,100\nB,200\n")
        self.write("private/oracle.json", '{"sum":300}')

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def sha(self, name):
        return hashlib.sha256((self.root / name).read_bytes()).hexdigest()

    def json_file(self, name, data):
        return self.write(name, json.dumps(data))

    def task(self):
        return {
            "schema_version": 1, "id": "demo", "title": "Invoice review",
            "purpose": "Decide the payable amount", "mode": "synthetic_demo",
            "prompt_path": "prompt.md", "prompt_sha256": self.sha("prompt.md"),
            "inputs": [{"id": "A", "path": "inputs/invoice.csv", "sha256": self.sha("inputs/invoice.csv"),
                        "role": "evidence", "source_ref": "handwritten synthetic fixture", "used_by": ["C1", "C2"]}],
            "deliverables": [{"id": "D", "path": "outputs/decision.csv", "description": "Reconciled decision"}],
            "criteria": [
                {"id": "C1", "weight": 50, "description": "Coverage", "input_ids": ["A"],
                 "deliverable_id": "D", "oracle_path": "private/oracle.json",
                 "oracle_sha256": self.sha("private/oracle.json"), "tolerance": "exact"},
                {"id": "C2", "weight": 50, "description": "Amount", "input_ids": ["A"],
                 "deliverable_id": "D", "oracle_path": "private/oracle.json",
                 "oracle_sha256": self.sha("private/oracle.json"), "tolerance": 0}],
            "dependencies": [{"from": "C1", "to": "C2"}],
        }

    def budget(self):
        return {"billing_mode": "api", "currency": "CNY", "attachment_count": 120,
                "author_minutes_per_attachment": 5, "review_minutes_per_attachment": 3,
                "rework_rate": 0.25, "rework_minutes_per_attachment": 4,
                "hourly_rate": 60, "fixed_cost": 100, "model_runs": 3,
                "input_tokens_per_run": 100000, "output_tokens_per_run": 10000,
                "input_price_per_million": 10, "output_price_per_million": 20,
                "tool_cost_per_run": 2, "budget_cap": 1200}

    def subscription_budget(self):
        budget = self.budget()
        for name in ("input_tokens_per_run", "output_tokens_per_run", "input_price_per_million",
                     "output_price_per_million"):
            del budget[name]
        budget.update(billing_mode="subscription", subscription_allocated_cost=3, overage_cost_per_run=0.2)
        return budget

    def make_run(self, identifier="r1", elapsed=2401, score=50, messages=49, synthetic=False, status="completed"):
        self.write(f"traces/{identifier}.txt", f"ORIGINAL FIXTURE TRACE {identifier}")
        self.write(f"scores/{identifier}.txt", f"INDEPENDENT FIXTURE GRADE {identifier}: {score}")
        start = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)
        return {"id": identifier, "task_sha256": "a" * 64, "model": "test-model", "mode": "test-mode",
                "started_at": start.isoformat(), "finished_at": (start + timedelta(seconds=elapsed)).isoformat(),
                "assistant_messages": messages, "score": score, "status": status, "synthetic": synthetic,
                "trace_path": f"traces/{identifier}.txt", "trace_sha256": self.sha(f"traces/{identifier}.txt"),
                "score_evidence_path": f"scores/{identifier}.txt", "score_evidence_sha256": self.sha(f"scores/{identifier}.txt")}

    def runs(self, items):
        return {"schema_version": 1, "policy": {"max_score": 50, "min_assistant_messages": 50,
                "min_elapsed_seconds_exclusive": 2400, "min_repeats": 3}, "runs": items}


class ValidateTests(Fixture):
    def check(self, data):
        return taskkit.validate_task(self.json_file("task.json", data))

    def test_valid_package_only_passes_structure(self):
        report = self.check(self.task())
        self.assertEqual(report["status"], "STRUCTURE_PASS")
        self.assertEqual(report["attachment_count"], 1)
        self.assertIn("Synthetic", " ".join(report["warnings"]))

    def test_missing_oracle_fails(self):
        data = self.task()
        data["criteria"][0]["oracle_path"] = "private/missing.json"
        self.assertEqual(self.check(data)["status"], "NOT_READY")

    def test_input_digest_detects_changed_material(self):
        data = self.task()
        self.write("inputs/invoice.csv", "id,amount\nA,999\n")
        self.assertIn("SHA-256 mismatch", " ".join(self.check(data)["errors"]))

    def test_prompt_and_oracle_hashes_are_required(self):
        data = self.task()
        del data["prompt_sha256"]
        self.assertIn("prompt_sha256", " ".join(self.check(data)["errors"]))
        data = self.task()
        del data["criteria"][0]["oracle_sha256"]
        self.assertIn("oracle_sha256", " ".join(self.check(data)["errors"]))

    def test_prompt_and_oracle_mutation_detected(self):
        data = self.task()
        self.write("prompt.md", "Changed task instructions")
        self.assertIn("prompt_sha256: SHA-256 mismatch", " ".join(self.check(data)["errors"]))
        data["prompt_sha256"] = self.sha("prompt.md")
        self.write("private/oracle.json", '{"sum":999}')
        self.assertIn("oracle_sha256: SHA-256 mismatch", " ".join(self.check(data)["errors"]))

    def test_duplicate_input_content_fails(self):
        data = self.task()
        self.write("inputs/copy.csv", (self.root / "inputs/invoice.csv").read_text())
        second = dict(data["inputs"][0], id="B", path="inputs/copy.csv")
        data["inputs"].append(second)
        for criterion in data["criteria"]:
            criterion["input_ids"].append("B")
        self.assertIn("duplicate content", " ".join(self.check(data)["errors"]))

    def test_duplicate_path_and_duplicate_id_fail(self):
        data = self.task()
        data["inputs"].append(dict(data["inputs"][0], id="B"))
        self.assertIn("duplicate path", " ".join(self.check(data)["errors"]))
        data["inputs"][1]["id"] = "A"
        self.assertIn("Duplicate inputs id", " ".join(self.check(data)["errors"]))

    def test_unused_and_asymmetric_input_fails(self):
        data = self.task()
        data["inputs"][0]["used_by"] = ["C1"]
        self.assertIn("asymmetric", " ".join(self.check(data)["errors"]))
        for criterion in data["criteria"]:
            criterion["input_ids"] = ["UNKNOWN"]
        self.assertIn("unused attachment", " ".join(self.check(data)["errors"]))

    def test_weight_sum_and_cycle_fail(self):
        data = self.task()
        data["criteria"][0]["weight"] = 49
        self.assertIn("sum to 100", " ".join(self.check(data)["errors"]))
        data["criteria"][0]["weight"] = 50
        data["dependencies"].append({"from": "C2", "to": "C1"})
        self.assertIn("cycle", " ".join(self.check(data)["errors"]))

    def test_private_prompt_and_copied_oracle_fail(self):
        data = self.task()
        data["prompt_path"] = "private/oracle.json"
        self.assertEqual(self.check(data)["status"], "NOT_READY")
        data = self.task()
        self.write("inputs/invoice.csv", (self.root / "private/oracle.json").read_text())
        data["inputs"][0]["sha256"] = self.sha("inputs/invoice.csv")
        self.assertIn("oracle content leaks", " ".join(self.check(data)["errors"]))

    def test_traversal_absolute_and_symlink_paths_fail(self):
        for invalid in ("../outside.csv", str(self.root / "inputs/invoice.csv")):
            data = self.task()
            data["inputs"][0]["path"] = invalid
            self.assertEqual(self.check(data)["status"], "NOT_READY")
        with tempfile.TemporaryDirectory() as external:
            outside = Path(external) / "outside.csv"
            outside.write_text("outside")
            (self.root / "inputs/link.csv").symlink_to(outside)
            data = self.task()
            data["inputs"][0]["path"] = "inputs/link.csv"
            self.assertIn("escapes", " ".join(self.check(data)["errors"]))

    def test_private_directory_symlink_escape_fails(self):
        (self.root / "private/public-alias").symlink_to(self.root / "inputs", target_is_directory=True)
        data = self.task()
        data["criteria"][0]["oracle_path"] = "private/public-alias/invoice.csv"
        self.assertIn("inside private", " ".join(self.check(data)["errors"]))

    def test_deliverable_cannot_overwrite_source(self):
        data = self.task()
        data["deliverables"][0]["path"] = "inputs/invoice.csv"
        self.assertIn("overwrites an input", " ".join(self.check(data)["errors"]))

    def test_deliverable_cannot_overwrite_manifest_or_prompt(self):
        for target in ("task.json", "prompt.md"):
            with self.subTest(target=target):
                data = self.task()
                data["deliverables"][0]["path"] = target
                self.assertEqual(self.check(data)["status"], "NOT_READY")

    def test_deliverable_directory_and_file_parent_are_rejected(self):
        self.write("outputs/blocker", "An existing file")
        for target in ("inputs", "outputs/blocker/nested/result.csv"):
            with self.subTest(target=target):
                data = self.task()
                data["deliverables"][0]["path"] = target
                self.assertEqual(self.check(data)["status"], "NOT_READY")

    def test_parent_child_outputs_conflict_in_both_orders(self):
        for paths in (("result", "result/part.csv"), ("result/part.csv", "result")):
            with self.subTest(paths=paths):
                data = self.task()
                data["deliverables"][0]["path"] = paths[0]
                data["deliverables"].append({"id": "D2", "path": paths[1], "description": "Second result"})
                data["criteria"][1]["deliverable_id"] = "D2"
                self.assertIn("parent/child", " ".join(self.check(data)["errors"]))

    def test_output_hardlinks_cannot_overwrite_protected_files(self):
        self.json_file("task.json", self.task())
        for i, target in enumerate(("inputs/invoice.csv", "prompt.md", "private/oracle.json", "task.json")):
            with self.subTest(target=target):
                alias = f"alias-{i}.csv"
                os.link(self.root / target, self.root / alias)
                data = self.task()
                data["deliverables"][0]["path"] = alias
                self.assertEqual(self.check(data)["status"], "NOT_READY")

    def test_two_outputs_cannot_alias_the_same_inode(self):
        self.write("outputs/one.csv", "Existing output")
        os.link(self.root / "outputs/one.csv", self.root / "outputs/two.csv")
        data = self.task()
        data["deliverables"][0]["path"] = "outputs/one.csv"
        data["deliverables"].append({"id": "D2", "path": "outputs/two.csv", "description": "Second result"})
        data["criteria"][1]["deliverable_id"] = "D2"
        self.assertIn("duplicate identities", " ".join(self.check(data)["errors"]))

    def test_legitimate_output_paths_remain_valid(self):
        self.write("outputs/existing.csv", "Previous unrelated output")
        for target in ("outputs/existing.csv", "new/nested/result.csv"):
            with self.subTest(target=target):
                data = self.task()
                data["deliverables"][0]["path"] = target
                self.assertEqual(self.check(data)["status"], "STRUCTURE_PASS")

    def test_windows_drive_paths_are_rejected_on_every_platform(self):
        for target in ("C:/result.csv", "C:result.csv", "//server/share/result.csv"):
            with self.subTest(target=target):
                data = self.task()
                data["deliverables"][0]["path"] = target
                self.assertIn("portable relative path", " ".join(self.check(data)["errors"]))

    def test_empty_input_prompt_and_oracle_are_rejected(self):
        for target in ("inputs/invoice.csv", "prompt.md", "private/oracle.json"):
            with self.subTest(target=target):
                original = (self.root / target).read_bytes()
                try:
                    self.write(target, "")
                    data = self.task()
                    self.assertIn("empty file", " ".join(self.check(data)["errors"]))
                finally:
                    (self.root / target).write_bytes(original)

    def test_header_only_csv_remains_valid(self):
        self.write("inputs/invoice.csv", "id,amount\n")
        self.assertEqual(self.check(self.task())["status"], "STRUCTURE_PASS")

    def test_malformed_dependency_reports_error_instead_of_crashing(self):
        data = self.task()
        data["dependencies"] = [{"from": ["C1"], "to": "C2"}]
        self.assertEqual(self.check(data)["status"], "NOT_READY")


class CostTests(Fixture):
    def test_decimal_budget_boundary_and_actual_excess(self):
        budget = self.subscription_budget()
        budget.update(attachment_count=0, model_runs=0, subscription_allocated_cost=0.2,
                      fixed_cost=0.1, budget_cap=0.3)
        report = taskkit.estimate_cost(self.json_file("budget.json", budget))
        self.assertEqual(report["status"], "WITHIN_ESTIMATE")
        self.assertEqual(report["total_cost"], 0.3)
        self.assertEqual(report["remaining_budget"], 0)
        budget["fixed_cost"] = 0.1001
        self.assertEqual(taskkit.estimate_cost(self.json_file("budget.json", budget))["status"], "OVER_BUDGET")

    def test_decimal_labor_and_api_boundaries(self):
        budget = self.budget()
        budget.update(attachment_count=1, author_minutes_per_attachment=1,
                      review_minutes_per_attachment=0, rework_rate=0, hourly_rate=180,
                      fixed_cost=0, model_runs=0, budget_cap=3)
        self.assertEqual(taskkit.estimate_cost(self.json_file("budget.json", budget))["status"], "WITHIN_ESTIMATE")
        budget.update(attachment_count=0, model_runs=1, input_tokens_per_run=100000,
                      input_price_per_million=1, output_tokens_per_run=100000,
                      output_price_per_million=2, tool_cost_per_run=0, budget_cap=0.3)
        self.assertEqual(taskkit.estimate_cost(self.json_file("budget.json", budget))["status"], "WITHIN_ESTIMATE")

    def test_decimal_results_outside_finite_json_range_are_rejected(self):
        budget = self.budget()
        budget.update(hourly_rate=1e308, author_minutes_per_attachment=1e308)
        with self.assertRaises(taskkit.InputError):
            taskkit.estimate_cost(self.json_file("budget.json", budget))

    def test_api_and_subscription_modes_compute_equivalent_budgets(self):
        api = taskkit.estimate_cost(self.json_file("api.json", self.budget()))
        subscription = taskkit.estimate_cost(self.json_file("subscription.json", self.subscription_budget()))
        self.assertEqual(api["billing_mode"], "api")
        self.assertEqual(subscription["billing_mode"], "subscription")
        for name in ("model_cost", "total_cost", "remaining_budget"):
            self.assertEqual(api[name], subscription[name])

    def test_unknown_or_missing_billing_inputs_are_not_assumed_zero(self):
        for factory, field in ((self.budget, "billing_mode"), (self.budget, "input_price_per_million"),
                               (self.subscription_budget, "subscription_allocated_cost"),
                               (self.subscription_budget, "overage_cost_per_run")):
            for missing in (True, False):
                with self.subTest(field=field, missing=missing):
                    budget = factory()
                    if missing:
                        del budget[field]
                    else:
                        budget[field] = None
                    with self.assertRaises(taskkit.InputError):
                        taskkit.estimate_cost(self.json_file("budget.json", budget))

    def test_cross_mode_fields_are_rejected_even_when_zero(self):
        cases = ((self.budget, "subscription_allocated_cost"), (self.budget, "overage_cost_per_run"),
                 (self.subscription_budget, "input_tokens_per_run"), (self.subscription_budget, "output_tokens_per_run"),
                 (self.subscription_budget, "input_price_per_million"), (self.subscription_budget, "output_price_per_million"))
        for factory, field in cases:
            with self.subTest(field=field):
                budget = factory()
                budget[field] = 0
                with self.assertRaisesRegex(taskkit.InputError, "Fields not allowed"):
                    taskkit.estimate_cost(self.json_file("budget.json", budget))

    def test_cost_arithmetic_and_threshold(self):
        budget = self.budget()
        report = taskkit.estimate_cost(self.json_file("budget.json", budget))
        self.assertEqual(report["labor_hours"], 18)
        self.assertEqual(report["model_cost"], 3.6)
        self.assertEqual(report["tool_cost"], 6)
        self.assertEqual(report["total_cost"], 1189.6)
        self.assertEqual(report["status"], "WITHIN_ESTIMATE")
        budget["budget_cap"] = 1189.5
        self.assertEqual(taskkit.estimate_cost(self.json_file("budget.json", budget))["status"], "OVER_BUDGET")

    def test_negative_nan_infinite_and_fractional_counts_rejected(self):
        for field, value in (("hourly_rate", -1), ("hourly_rate", float("nan")),
                             ("fixed_cost", float("inf")), ("attachment_count", 1.5),
                             ("model_runs", True), ("rework_rate", 1.01)):
            with self.subTest(field=field, value=value):
                data = self.budget()
                data[field] = value
                with self.assertRaises(taskkit.InputError):
                    taskkit.estimate_cost(self.json_file("budget.json", data))


class RunTests(Fixture):
    def check(self, items):
        return taskkit.summarize_runs(self.json_file("runs.json", self.runs(items)))

    def test_strict_40_minute_boundary(self):
        report = self.check([self.make_run(elapsed=2400)])
        self.assertFalse(report["runs"][0]["time_over_threshold"])
        self.assertFalse(report["runs"][0]["difficulty_met"])
        report = self.check([self.make_run(elapsed=2400.001)])
        self.assertTrue(report["runs"][0]["difficulty_met"])

    def test_steps_alternative_and_score_and_condition(self):
        report = self.check([self.make_run(elapsed=100, messages=50)])
        self.assertTrue(report["runs"][0]["difficulty_met"])
        self.assertFalse(report["runs"][0]["time_over_threshold"])
        report = self.check([self.make_run(elapsed=3000, messages=100, score=50.01)])
        self.assertFalse(report["runs"][0]["difficulty_met"])

    def test_three_observed_matches_no_guarantee(self):
        report = self.check([self.make_run(f"r{i}") for i in range(3)])
        self.assertEqual(report["status"], "OBSERVED_CRITERIA_MET")
        self.assertEqual(report["real_attempts"], 3)
        self.assertEqual(report["qualifying_attempts"], 3)
        self.assertIn("not a guarantee", " ".join(report["warnings"]))

    def test_too_few_and_mixed_configs_not_ready(self):
        self.assertEqual(self.check([self.make_run()])["status"], "NOT_READY")
        items = [self.make_run(f"r{i}") for i in range(3)]
        items[1]["model"] = "other-model"
        report = self.check(items)
        self.assertEqual(report["status"], "NOT_READY")
        self.assertFalse(report["config_consistent"])

    def test_errors_and_interruptions_stay_in_denominator(self):
        items = [self.make_run("a"), self.make_run("b", status="error"), self.make_run("c", status="interrupted")]
        report = self.check(items)
        self.assertEqual(report["real_attempts"], 3)
        self.assertEqual(report["qualifying_attempts"], 1)
        self.assertEqual(report["status"], "NOT_READY")

    def test_unknown_message_count_preserved_without_counting_as_steps(self):
        report = self.check([self.make_run(messages=None)])
        self.assertIsNone(report["runs"][0]["assistant_messages"])
        self.assertFalse(report["runs"][0]["messages_threshold_met"])
        self.assertTrue(report["runs"][0]["difficulty_met"])
        report = self.check([self.make_run(messages=None, elapsed=100)])
        self.assertFalse(report["runs"][0]["difficulty_met"])

    def test_ungraded_failures_remain_in_denominator(self):
        report = self.check([self.make_run("a", status="error", score=None),
                             self.make_run("b", status="interrupted", score=None),
                             self.make_run("c")])
        self.assertEqual(report["real_attempts"], 3)
        self.assertEqual(report["qualifying_attempts"], 1)
        self.assertEqual(report["real_time_over_threshold"], 3)
        self.assertEqual(report["real_completed_time_over_threshold"], 1)
        self.assertFalse(report["runs"][0]["score_threshold_met"])
        self.assertFalse(report["runs"][0]["completed_time_over_threshold"])

    def test_completed_without_grade_and_missing_message_field_rejected(self):
        with self.assertRaises(taskkit.InputError):
            self.check([self.make_run(score=None)])
        item = self.make_run()
        del item["score"]
        with self.assertRaises(taskkit.InputError):
            self.check([item])
        item = self.make_run()
        del item["assistant_messages"]
        with self.assertRaises(taskkit.InputError):
            self.check([item])

    def test_synthetic_runs_and_empty_list_are_untested(self):
        self.assertEqual(self.check([])["status"], "UNTESTED")
        report = self.check([self.make_run(f"r{i}", synthetic=True) for i in range(3)])
        self.assertEqual(report["status"], "UNTESTED")
        self.assertEqual(report["real_attempts"], 0)
        self.assertEqual(report["synthetic_attempts"], 3)
        self.assertIsNone(report["observed_qualifying_fraction"])

    def test_tampered_trace_and_score_evidence_rejected(self):
        for name in ("trace_sha256", "score_evidence_sha256"):
            item = self.make_run()
            item[name] = "0" * 64
            with self.assertRaises(taskkit.InputError):
                self.check([item])

    def test_empty_trace_or_score_evidence_rejected(self):
        for field in ("trace", "score_evidence"):
            with self.subTest(field=field):
                item = self.make_run()
                self.write(item[field + "_path"], "")
                item[field + "_sha256"] = self.sha(item[field + "_path"])
                with self.assertRaisesRegex(taskkit.InputError, "empty file"):
                    self.check([item])

    def test_reused_trace_and_duplicate_run_id_rejected(self):
        a, b = self.make_run("a"), self.make_run("b")
        b["trace_path"], b["trace_sha256"] = a["trace_path"], a["trace_sha256"]
        with self.assertRaisesRegex(taskkit.InputError, "identical trace"):
            self.check([a, b])
        with self.assertRaisesRegex(taskkit.InputError, "Duplicate run id"):
            self.check([a, a])

    def test_missing_timezone_and_negative_duration_rejected(self):
        item = self.make_run()
        item["started_at"] = "2026-11-04T12:00:00"
        with self.assertRaises(taskkit.InputError):
            self.check([item])
        with self.assertRaises(taskkit.InputError):
            self.check([self.make_run(elapsed=-1)])


class CLITests(Fixture):
    def cli(self, command, path):
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            status = taskkit.main([command, str(path)])
        return status, json.loads(stdout.getvalue())

    def test_cli_exit_codes_and_json(self):
        good = self.json_file("task.json", self.task())
        self.assertEqual(self.cli("validate", good)[0], 0)
        data = self.task()
        data["criteria"][0]["weight"] = 40
        self.assertEqual(self.cli("validate", self.json_file("task.json", data))[0], 1)
        status, report = self.cli("validate", self.write("bad.json", "{bad"))
        self.assertEqual(status, 2)
        self.assertEqual(report["status"], "INPUT_ERROR")
        self.assertEqual(self.cli("runs", self.json_file("runs.json", self.runs([])))[0], 1)


if __name__ == "__main__":
    unittest.main()
