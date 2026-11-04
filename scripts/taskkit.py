#!/usr/bin/env python3
"""Offline structural checks, cost estimates and observed-run summaries.

Python 3.10+, standard library only. No command in this module calls a model.
The checks deliberately make no claim about semantic quality or log authenticity.
"""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import re
import sys
from typing import Any


class InputError(ValueError):
    """An unreadable document or invalid command input."""


def _load(path: str | Path) -> tuple[dict[str, Any], Path]:
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"),
                          parse_constant=lambda value: (_ for _ in ()).throw(
                              ValueError(f"non-finite JSON number: {value}")))
    except (OSError, UnicodeError, ValueError) as exc:
        raise InputError(f"Cannot read JSON {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise InputError("The JSON document must be an object")
    return data, path.resolve().parent


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InputError(f"{label} must be a non-empty string")
    return value


def _number(value: Any, label: str, *, integer: bool = False,
            maximum: float | None = None, positive: bool = False) -> float | int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InputError(f"{label} must be a number")
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite or value < 0 or (positive and value == 0):
        raise InputError(f"{label} must be finite and {'positive' if positive else 'non-negative'}")
    if integer and (not isinstance(value, int)):
        raise InputError(f"{label} must be an integer")
    if maximum is not None and value > maximum:
        raise InputError(f"{label} must be <= {maximum}")
    return value


def _list(value: Any, label: str, *, nonempty: bool = False) -> list[Any]:
    if not isinstance(value, list) or (nonempty and not value):
        raise InputError(f"{label} must be {'a non-empty' if nonempty else 'a'} list")
    return value


def _hash(value: Any, label: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise InputError(f"{label} must be a lowercase SHA-256 hex digest")
    return value


def _safe_path(root: Path, value: Any, label: str, *, exists: bool = False,
               public: bool = False, private: bool = False) -> Path:
    raw = _text(value, label)
    rel = Path(raw)
    if rel.is_absolute() or ".." in rel.parts or "\\" in raw:
        raise InputError(f"{label} must be a portable relative path without '..'")
    try:
        path = (root / rel).resolve()
        actual = path.relative_to(root)
    except (ValueError, OSError, RuntimeError) as exc:
        raise InputError(f"{label} escapes the task directory") from exc
    if not actual.parts:
        raise InputError(f"{label} must name a file")
    if public and ("private" in rel.parts or "private" in actual.parts):
        raise InputError(f"{label} exposes the private grading directory")
    if private and (not rel.parts or rel.parts[0] != "private" or actual.parts[0] != "private"):
        raise InputError(f"{label} must remain inside private/")
    if exists and not path.is_file():
        raise InputError(f"{label} does not name an existing regular file")
    return path


def _digest(path: Path) -> str:
    result = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                result.update(chunk)
    except OSError as exc:
        raise InputError(f"Cannot read {path}: {exc}") from exc
    return result.hexdigest()


def _version(data: dict[str, Any]) -> None:
    if type(data.get("schema_version")) is not int or data["schema_version"] != 1:
        raise InputError("schema_version must be integer 1")


def _id_map(items: Any, label: str) -> dict[str, dict[str, Any]]:
    output = {}
    for i, item in enumerate(_list(items, label, nonempty=True)):
        if not isinstance(item, dict):
            raise InputError(f"{label}[{i}] must be an object")
        identifier = _text(item.get("id"), f"{label}[{i}].id")
        if identifier in output:
            raise InputError(f"Duplicate {label} id: {identifier}")
        output[identifier] = item
    return output


def _refs(value: Any, label: str) -> set[str]:
    items = _list(value, label, nonempty=True)
    refs = [_text(item, label) for item in items]
    if len(set(refs)) != len(refs):
        raise InputError(f"Duplicate references in {label}")
    return set(refs)


def validate_task(path: str | Path) -> dict[str, Any]:
    """Check a task package's structure. Semantic/human checks remain external."""
    data, root = _load(path)
    errors: list[str] = []
    warnings = ["Structural checks do not validate semantic correctness, business authenticity, rights, or grading quality; human review is still required."]
    mode = data.get("mode")
    if mode == "synthetic_demo":
        warnings.append("Synthetic demonstration: not evidence of a real business task and not submission-ready.")
    try:
        _version(data)
        for name in ("id", "title", "purpose"):
            _text(data.get(name), name)
        if mode not in ("real", "synthetic_demo"):
            raise InputError("mode must be real or synthetic_demo")
        prompt = _safe_path(root, data.get("prompt_path"), "prompt_path", exists=True, public=True)
        prompt_expected = _hash(data.get("prompt_sha256"), "prompt_sha256")
        inputs = _id_map(data.get("inputs"), "inputs")
        deliverables = _id_map(data.get("deliverables"), "deliverables")
        criteria = _id_map(data.get("criteria"), "criteria")
        dependencies = _list(data.get("dependencies"), "dependencies")
    except InputError as exc:
        return {"status": "NOT_READY", "mode": mode,
                "attachment_count": len(data["inputs"]) if isinstance(data.get("inputs"), list) else 0,
                "errors": [str(exc)], "warnings": warnings}

    input_paths: dict[Path, str] = {}
    input_hashes: dict[str, str] = {}
    input_refs: dict[str, set[str]] = {}
    criterion_refs: dict[str, set[str]] = {}
    prompt_digest = _digest(prompt)
    if prompt_digest != prompt_expected:
        errors.append("prompt_sha256: SHA-256 mismatch")
    for identifier, item in inputs.items():
        try:
            label = f"inputs.{identifier}"
            _text(item.get("source_ref"), label + ".source_ref")
            if item.get("role") not in ("evidence", "rule", "template"):
                raise InputError(label + ".role must be evidence, rule, or template")
            file_path = _safe_path(root, item.get("path"), label + ".path", exists=True, public=True)
            expected = _hash(item.get("sha256"), label + ".sha256")
            actual = _digest(file_path)
            if expected != actual:
                errors.append(label + ": SHA-256 mismatch")
            if file_path == prompt:
                errors.append(label + ": prompt must not be counted as an attachment")
            if file_path in input_paths:
                errors.append(f"{label}: duplicate path with {input_paths[file_path]}")
            if actual in input_hashes:
                errors.append(f"{label}: duplicate content with {input_hashes[actual]}")
            input_paths[file_path] = identifier
            input_hashes[actual] = identifier
            refs = _refs(item.get("used_by"), label + ".used_by")
            input_refs[identifier] = refs
            if refs - criteria.keys():
                errors.append(f"{label}: unknown criteria {sorted(refs - criteria.keys())}")
        except InputError as exc:
            errors.append(str(exc))

    output_paths: set[Path] = set()
    for identifier, item in deliverables.items():
        try:
            _text(item.get("description"), f"deliverables.{identifier}.description")
            output_path = _safe_path(root, item.get("path"), f"deliverables.{identifier}.path", public=True)
            if output_path in output_paths or output_path in input_paths or output_path == prompt:
                errors.append(f"deliverables.{identifier}: output path duplicates an output or overwrites an input")
            output_paths.add(output_path)
        except InputError as exc:
            errors.append(str(exc))

    weights: list[float | int] = []
    used_deliverables: set[str] = set()
    for identifier, item in criteria.items():
        try:
            label = f"criteria.{identifier}"
            weights.append(_number(item.get("weight"), label + ".weight", positive=True, maximum=100))
            _text(item.get("description"), label + ".description")
            tolerance = item.get("tolerance")
            if isinstance(tolerance, str):
                _text(tolerance, label + ".tolerance")
            else:
                _number(tolerance, label + ".tolerance")
            refs = _refs(item.get("input_ids"), label + ".input_ids")
            criterion_refs[identifier] = refs
            if refs - inputs.keys():
                errors.append(f"{label}: unknown inputs {sorted(refs - inputs.keys())}")
            target = _text(item.get("deliverable_id"), label + ".deliverable_id")
            used_deliverables.add(target)
            if target not in deliverables:
                errors.append(label + ": unknown deliverable " + target)
            oracle = _safe_path(root, item.get("oracle_path"), label + ".oracle_path", exists=True, private=True)
            oracle_expected = _hash(item.get("oracle_sha256"), label + ".oracle_sha256")
            oracle_digest = _digest(oracle)
            if oracle_digest != oracle_expected:
                errors.append(label + ".oracle_sha256: SHA-256 mismatch")
            if oracle in input_paths or oracle_digest in input_hashes or oracle_digest == prompt_digest:
                errors.append(label + ": oracle content leaks into solver-visible input/prompt")
            if oracle in output_paths:
                errors.append(label + ": deliverable overwrites an oracle")
        except InputError as exc:
            errors.append(str(exc))
    if not math.isclose(sum(weights), 100, rel_tol=0, abs_tol=1e-8):
        errors.append(f"Criterion weights must sum to 100; got {sum(weights)}")
    for input_id in inputs:
        forward = input_refs.get(input_id, set())
        backward = {cid for cid, refs in criterion_refs.items() if input_id in refs}
        if forward != backward:
            errors.append(f"inputs.{input_id}: used_by and criteria.input_ids are asymmetric")
        if not backward:
            errors.append(f"inputs.{input_id}: unused attachment")
    for target in deliverables.keys() - used_deliverables:
        errors.append(f"deliverables.{target}: no criterion checks this deliverable")

    graph: dict[str, set[str]] = {identifier: set() for identifier in criteria}
    for i, edge in enumerate(dependencies):
        if (not isinstance(edge, dict)
                or not isinstance(edge.get("from"), str)
                or not isinstance(edge.get("to"), str)
                or edge["from"] not in graph or edge["to"] not in graph):
            errors.append(f"dependencies[{i}]: must reference existing criteria")
        else:
            graph[edge["from"]].add(edge["to"])
    indegree = {node: 0 for node in graph}
    for targets in graph.values():
        for target in targets:
            indegree[target] += 1
    queue = [node for node, degree in indegree.items() if degree == 0]
    visited = 0
    while queue:
        node = queue.pop()
        visited += 1
        for target in graph[node]:
            indegree[target] -= 1
            if indegree[target] == 0:
                queue.append(target)
    if visited != len(graph):
        errors.append("Criterion dependencies contain a cycle")
    return {"status": "NOT_READY" if errors else "STRUCTURE_PASS", "mode": mode,
            "attachment_count": len(inputs), "errors": errors, "warnings": warnings}


def estimate_cost(path: str | Path) -> dict[str, Any]:
    """Estimate authoring/review/rework plus user-supplied model/tool prices."""
    data, _ = _load(path)
    currency = _text(data.get("currency"), "currency")
    billing_mode = data.get("billing_mode")
    if billing_mode not in ("api", "subscription"):
        raise InputError("billing_mode must be api or subscription")
    api_fields = ("input_tokens_per_run", "output_tokens_per_run", "input_price_per_million",
                  "output_price_per_million")
    subscription_fields = ("subscription_allocated_cost", "overage_cost_per_run")
    mode_fields = api_fields if billing_mode == "api" else subscription_fields
    excluded_fields = subscription_fields if billing_mode == "api" else api_fields
    mixed = [name for name in excluded_fields if name in data]
    if mixed:
        raise InputError(f"Fields not allowed for billing_mode={billing_mode}: {', '.join(mixed)}")
    names = ("attachment_count", "author_minutes_per_attachment", "review_minutes_per_attachment",
             "rework_rate", "rework_minutes_per_attachment", "hourly_rate", "fixed_cost", "model_runs",
             "tool_cost_per_run", "budget_cap") + mode_fields
    for name in names:
        _number(data.get(name), name, integer=name in ("attachment_count", "model_runs"),
                maximum=1 if name == "rework_rate" else None)
    try:
        labor_minutes = data["attachment_count"] * (
            data["author_minutes_per_attachment"] + data["review_minutes_per_attachment"]
            + data["rework_rate"] * data["rework_minutes_per_attachment"])
        labor_cost = labor_minutes / 60 * data["hourly_rate"]
        if billing_mode == "api":
            model_cost = data["model_runs"] * (data["input_tokens_per_run"] * data["input_price_per_million"]
                         + data["output_tokens_per_run"] * data["output_price_per_million"]) / 1_000_000
        else:
            model_cost = data["subscription_allocated_cost"] + data["model_runs"] * data["overage_cost_per_run"]
        tool_cost = data["model_runs"] * data["tool_cost_per_run"]
        total = labor_cost + model_cost + tool_cost + data["fixed_cost"]
        remaining = data["budget_cap"] - total
        if not all(math.isfinite(value) for value in (labor_minutes, labor_cost, model_cost, tool_cost, total, remaining)):
            raise OverflowError
    except (OverflowError, ValueError) as exc:
        raise InputError("Budget arithmetic exceeds the supported finite numeric range") from exc
    return {"status": "OVER_BUDGET" if total > data["budget_cap"] else "WITHIN_ESTIMATE",
            "billing_mode": billing_mode, "currency": currency, "attachment_count": data["attachment_count"],
            "labor_hours": round(labor_minutes / 60, 4), "labor_cost": round(labor_cost, 4),
            "model_cost": round(model_cost, 4), "tool_cost": round(tool_cost, 4),
            "fixed_cost": data["fixed_cost"], "total_cost": round(total, 4),
            "budget_cap": data["budget_cap"], "remaining_budget": round(remaining, 4),
            "warnings": ["Planning estimate only; supplied rates are not verified current prices. Shared preparation/ground-truth work belongs in fixed_cost; subscription allocation belongs only in subscription_allocated_cost to avoid double counting. Runtime is not estimated from attachment count."]}


def _timestamp(value: Any, label: str) -> datetime:
    raw = _text(value, label)
    try:
        result = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if result.tzinfo is None or result.utcoffset() is None:
            raise ValueError("timezone missing")
        return result
    except ValueError as exc:
        raise InputError(f"{label} must be an ISO-8601 timestamp with timezone") from exc


def summarize_runs(path: str | Path) -> dict[str, Any]:
    """Report finite observed attempts without claiming future stability."""
    data, root = _load(path)
    _version(data)
    policy = data.get("policy")
    if not isinstance(policy, dict):
        raise InputError("policy must be an object")
    _number(policy.get("max_score"), "policy.max_score", maximum=100)
    _number(policy.get("min_assistant_messages"), "policy.min_assistant_messages", integer=True, positive=True)
    _number(policy.get("min_elapsed_seconds_exclusive"), "policy.min_elapsed_seconds_exclusive")
    _number(policy.get("min_repeats"), "policy.min_repeats", integer=True, positive=True)
    attempts = _list(data.get("runs"), "runs")
    seen_ids: set[str] = set()
    seen_real_traces: set[str] = set()
    configs: set[tuple[str, str, str]] = set()
    results = []
    for i, item in enumerate(attempts):
        label = f"runs[{i}]"
        if not isinstance(item, dict):
            raise InputError(label + " must be an object")
        identifier = _text(item.get("id"), label + ".id")
        if identifier in seen_ids:
            raise InputError(f"Duplicate run id: {identifier}")
        seen_ids.add(identifier)
        task_hash = _hash(item.get("task_sha256"), label + ".task_sha256")
        model = _text(item.get("model"), label + ".model")
        mode = _text(item.get("mode"), label + ".mode")
        if type(item.get("synthetic")) is not bool:
            raise InputError(label + ".synthetic must be boolean")
        synthetic = item["synthetic"]
        if item.get("status") not in ("completed", "error", "interrupted"):
            raise InputError(label + ".status must be completed, error, or interrupted")
        if "assistant_messages" not in item:
            raise InputError(label + ".assistant_messages is required; use null when unobservable")
        messages = item["assistant_messages"]
        if messages is not None:
            _number(messages, label + ".assistant_messages", integer=True)
        if "score" not in item:
            raise InputError(label + ".score is required; use null for an ungraded failed attempt")
        score = item["score"]
        if score is not None or item["status"] == "completed":
            _number(score, label + ".score", maximum=100)
        start = _timestamp(item.get("started_at"), label + ".started_at")
        finish = _timestamp(item.get("finished_at"), label + ".finished_at")
        elapsed = (finish - start).total_seconds()
        if elapsed < 0:
            raise InputError(label + ": finished_at precedes started_at")
        for field in ("trace", "score_evidence"):
            evidence = _safe_path(root, item.get(field + "_path"), label + "." + field + "_path", exists=True)
            expected = _hash(item.get(field + "_sha256"), label + "." + field + "_sha256")
            if _digest(evidence) != expected:
                raise InputError(label + ": " + field + " SHA-256 mismatch")
        if not synthetic:
            if item["trace_sha256"] in seen_real_traces:
                raise InputError("Real attempts reuse an identical trace; independence is not established")
            seen_real_traces.add(item["trace_sha256"])
            configs.add((task_hash, model, mode))
        time_met = elapsed > policy["min_elapsed_seconds_exclusive"]
        messages_met = messages is not None and messages >= policy["min_assistant_messages"]
        score_met = score is not None and score <= policy["max_score"]
        difficulty_met = (not synthetic and item["status"] == "completed" and score_met
                          and (time_met or messages_met))
        results.append({"id": identifier, "synthetic": synthetic, "status": item["status"],
                        "elapsed_seconds": elapsed, "assistant_messages": messages, "score": score,
                        "time_over_threshold": time_met,
                        "completed_time_over_threshold": time_met and item["status"] == "completed",
                        "messages_threshold_met": messages_met,
                        "score_threshold_met": score_met, "difficulty_met": difficulty_met})
    real = [run for run in results if not run["synthetic"]]
    n = len(real)
    k = sum(run["difficulty_met"] for run in real)
    consistent = len(configs) <= 1
    if not n:
        status = "UNTESTED"
    elif consistent and n >= policy["min_repeats"] and k == n:
        status = "OBSERVED_CRITERIA_MET"
    else:
        status = "NOT_READY"
    return {"status": status, "policy": policy, "config_consistent": consistent,
            "real_attempts": n, "qualifying_attempts": k,
            "observed_qualifying_fraction": k / n if n else None,
            "real_time_over_threshold": sum(run["time_over_threshold"] for run in real),
            "real_completed_time_over_threshold": sum(run["completed_time_over_threshold"] for run in real),
            "real_messages_threshold_met": sum(run["messages_threshold_met"] for run in real),
            "real_completed_attempts": sum(run["status"] == "completed" for run in real),
            "synthetic_attempts": len(results) - n, "runs": results,
            "warnings": ["Hashes verify file integrity, not authenticity of traces, timestamps, message counts or grades. Inspect original product traces and independent grading evidence. All real errors/interrupted attempts remain in the denominator. Observed criteria are not a guarantee of future duration or project acceptance."]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("validate", "cost", "runs"))
    parser.add_argument("path", help="Path to the JSON input document")
    args = parser.parse_args(argv)
    functions = {"validate": validate_task, "cost": estimate_cost, "runs": summarize_runs}
    try:
        report = functions[args.command](args.path)
    except InputError as exc:
        print(json.dumps({"status": "INPUT_ERROR", "errors": [str(exc)]}, ensure_ascii=False))
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
    return 0 if report["status"] in ("STRUCTURE_PASS", "WITHIN_ESTIMATE", "OBSERVED_CRITERIA_MET") else 1


if __name__ == "__main__":
    sys.exit(main())
