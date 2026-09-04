#!/usr/bin/env python3
"""Run repeatable old-to-new desktop state migration proofs.

The prototype intentionally uses only the Python standard library and JSON
configuration. Commands are argument arrays and are never executed through a
shell. This makes the first Windows GitHub Action deterministic and keeps the
customer's synthetic state on its own runner.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
from typing import Any


RESERVED_VARIABLES = {"profile", "evidence", "path_id", "attempt"}


class ContractError(ValueError):
    """Raised when a state-gate contract is invalid."""


def load_contract(path: pathlib.Path) -> dict[str, Any]:
    try:
        contract = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ContractError(f"contract not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ContractError(f"contract is not valid JSON: {exc}") from exc
    if not isinstance(contract, dict):
        raise ContractError("contract root must be an object")
    unknown_root = set(contract) - {"$schema", "contract_version", "project", "fail_on_flaky", "paths"}
    if unknown_root:
        raise ContractError(f"unknown contract field(s): {', '.join(sorted(unknown_root))}")
    if contract.get("contract_version") != 1:
        raise ContractError("contract_version must be 1")
    if "project" in contract and (not isinstance(contract["project"], str) or not contract["project"]):
        raise ContractError("project must be a non-empty string")
    if not isinstance(contract.get("fail_on_flaky", True), bool):
        raise ContractError("fail_on_flaky must be a boolean")
    paths = contract.get("paths")
    if not isinstance(paths, list) or not paths:
        raise ContractError("paths must be a non-empty array")

    seen: set[str] = set()
    for index, path_contract in enumerate(paths):
        if not isinstance(path_contract, dict):
            raise ContractError(f"paths[{index}] must be an object")
        path_id = path_contract.get("id")
        if not isinstance(path_id, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+", path_id):
            raise ContractError(f"paths[{index}].id must contain only letters, digits, _, . or -")
        if path_id in seen:
            raise ContractError(f"duplicate path id: {path_id}")
        seen.add(path_id)
        unknown_path = set(path_contract) - {
            "id", "from", "to", "timeout_seconds", "retries", "seed", "verify", "assertions"
        }
        if unknown_path:
            raise ContractError(f"{path_id} has unknown field(s): {', '.join(sorted(unknown_path))}")
        for version_field in ("from", "to"):
            if version_field in path_contract and not isinstance(path_contract[version_field], str):
                raise ContractError(f"{path_id}.{version_field} must be a string")
        for step_name in ("seed", "verify"):
            step = path_contract.get(step_name)
            command = step.get("command") if isinstance(step, dict) else None
            if not isinstance(command, list) or not command or not all(isinstance(item, str) for item in command):
                raise ContractError(f"{path_id}.{step_name}.command must be a non-empty string array")
            unknown_step = set(step) - {"command", "expected_exit"}
            if unknown_step:
                raise ContractError(
                    f"{path_id}.{step_name} has unknown field(s): {', '.join(sorted(unknown_step))}"
                )
            if not isinstance(step.get("expected_exit", 0), int):
                raise ContractError(f"{path_id}.{step_name}.expected_exit must be an integer")
        retries = path_contract.get("retries", 0)
        if not isinstance(retries, int) or retries < 0 or retries > 2:
            raise ContractError(f"{path_id}.retries must be an integer from 0 to 2")
        timeout = path_contract.get("timeout_seconds", 60)
        if not isinstance(timeout, int) or timeout < 1 or timeout > 900:
            raise ContractError(f"{path_id}.timeout_seconds must be an integer from 1 to 900")
        assertions = path_contract.get(
            "assertions",
            [{"path": "passed", "op": "equals", "value": True}],
        )
        if not isinstance(assertions, list) or not assertions:
            raise ContractError(f"{path_id}.assertions must be a non-empty array")
        for assertion_index, assertion in enumerate(assertions):
            if not isinstance(assertion, dict):
                raise ContractError(f"{path_id}.assertions[{assertion_index}] must be an object")
            unknown_assertion = set(assertion) - {"path", "op", "value"}
            if unknown_assertion:
                raise ContractError(
                    f"{path_id}.assertions[{assertion_index}] has unknown field(s): "
                    f"{', '.join(sorted(unknown_assertion))}"
                )
            if not isinstance(assertion.get("path"), str):
                raise ContractError(f"{path_id}.assertions[{assertion_index}].path must be a string")
            if assertion.get("op", "equals") not in {"equals", "not_equals", "exists", "truthy"}:
                raise ContractError(f"{path_id}.assertions[{assertion_index}].op is unsupported")
    return contract


def sha256(path: pathlib.Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def json_value(document: Any, dotted_path: str) -> tuple[bool, Any]:
    current = document
    if dotted_path == "":
        return True, current
    for part in dotted_path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            return False, None
    return True, current


def evaluate_assertions(evidence: Any, assertions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for assertion in assertions:
        dotted_path = assertion.get("path")
        operation = assertion.get("op", "equals")
        expected = assertion.get("value")
        if not isinstance(dotted_path, str):
            raise ContractError("each assertion.path must be a string")
        exists, actual = json_value(evidence, dotted_path)
        if operation == "equals":
            passed = exists and actual == expected
        elif operation == "not_equals":
            passed = exists and actual != expected
        elif operation == "exists":
            passed = exists
        elif operation == "truthy":
            passed = exists and bool(actual)
        else:
            raise ContractError(f"unsupported assertion operation: {operation}")
        results.append(
            {
                "path": dotted_path,
                "op": operation,
                "expected": expected,
                "actual": actual,
                "exists": exists,
                "passed": passed,
            }
        )
    return results


def render_token(token: str, variables: dict[str, str]) -> str:
    rendered = token
    for name, value in variables.items():
        rendered = rendered.replace("{" + name + "}", value)
    unresolved = re.findall(r"\{[A-Za-z0-9_]+\}", rendered)
    if unresolved:
        raise ContractError(f"unresolved command placeholder(s): {', '.join(unresolved)}")
    return rendered


def parse_variables(items: list[str]) -> dict[str, str]:
    variables: dict[str, str] = {}
    for item in items:
        if "=" not in item:
            raise ContractError("each --var must use NAME=VALUE")
        name, value = item.split("=", 1)
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", name):
            raise ContractError(f"invalid variable name: {name!r}")
        if name in RESERVED_VARIABLES:
            raise ContractError(f"variable name is reserved: {name}")
        if name in variables:
            raise ContractError(f"duplicate variable: {name}")
        if not value:
            raise ContractError(f"variable value must not be empty: {name}")
        variables[name] = value
    return variables


def resolve_command(command: list[str], variables: dict[str, str], contract_root: pathlib.Path) -> list[str]:
    rendered = [render_token(token, variables) for token in command]
    executable = pathlib.Path(rendered[0])
    if not executable.is_absolute() and ("/" in rendered[0] or "\\" in rendered[0]):
        candidate = (contract_root / executable).resolve()
        if candidate.exists():
            rendered[0] = str(candidate)
    return rendered


def run_step(
    name: str,
    step: dict[str, Any],
    variables: dict[str, str],
    contract_root: pathlib.Path,
    timeout_seconds: int,
    log_folder: pathlib.Path,
) -> dict[str, Any]:
    command = resolve_command(step["command"], variables, contract_root)
    environment = os.environ.copy()
    environment.update(
        {
            "STATE_GATE_PROFILE": variables["profile"],
            "STATE_GATE_EVIDENCE": variables["evidence"],
            "STATE_GATE_PATH_ID": variables["path_id"],
            "STATE_GATE_ATTEMPT": variables["attempt"],
        }
    )
    started = dt.datetime.now(dt.timezone.utc)
    try:
        completed = subprocess.run(
            command,
            cwd=contract_root,
            env=environment,
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
        timed_out = False
        exit_code: int | None = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        exit_code = None
        stdout = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        launch_error = None
    except OSError as exc:
        timed_out = False
        exit_code = None
        stdout = ""
        stderr = f"{type(exc).__name__}: {exc}"
        launch_error = stderr
    else:
        launch_error = None
    finished = dt.datetime.now(dt.timezone.utc)
    (log_folder / f"{name}.stdout.log").write_text(stdout, encoding="utf-8")
    (log_folder / f"{name}.stderr.log").write_text(stderr, encoding="utf-8")
    return {
        "command": command,
        "exit_code": exit_code,
        "timed_out": timed_out,
        "duration_ms": round((finished - started).total_seconds() * 1000),
        "stdout_log": str(log_folder / f"{name}.stdout.log"),
        "stderr_log": str(log_folder / f"{name}.stderr.log"),
        "launch_error": launch_error,
        "passed": not timed_out and launch_error is None and exit_code == step.get("expected_exit", 0),
    }


def run_attempt(
    path_contract: dict[str, Any],
    attempt_number: int,
    contract_root: pathlib.Path,
    attempt_folder: pathlib.Path,
    external_variables: dict[str, str] | None = None,
) -> dict[str, Any]:
    attempt_folder.mkdir(parents=True, exist_ok=True)
    profile = attempt_folder / "user-data"
    profile.mkdir()
    seed_evidence_path = attempt_folder / "seed-evidence.json"
    verify_evidence_path = attempt_folder / "verify-evidence.json"
    common = {
        **(external_variables or {}),
        "profile": str(profile.resolve()),
        "path_id": path_contract["id"],
        "attempt": str(attempt_number),
    }
    timeout = path_contract.get("timeout_seconds", 60)

    seed_variables = {**common, "evidence": str(seed_evidence_path.resolve())}
    seed = run_step("seed", path_contract["seed"], seed_variables, contract_root, timeout, attempt_folder)

    verify_variables = {**common, "evidence": str(verify_evidence_path.resolve())}
    if seed["passed"]:
        verify = run_step("verify", path_contract["verify"], verify_variables, contract_root, timeout, attempt_folder)
    else:
        verify = {
            "command": [],
            "exit_code": None,
            "timed_out": False,
            "duration_ms": 0,
            "stdout_log": None,
            "stderr_log": None,
            "launch_error": None,
            "passed": False,
            "skipped": "seed step failed",
        }

    seed_evidence: Any = None
    verify_evidence: Any = None
    evidence_error: str | None = None
    try:
        if seed_evidence_path.exists():
            seed_evidence = json.loads(seed_evidence_path.read_text(encoding="utf-8"))
        if verify_evidence_path.exists():
            verify_evidence = json.loads(verify_evidence_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        evidence_error = str(exc)

    assertions = path_contract.get(
        "assertions",
        [{"path": "passed", "op": "equals", "value": True}],
    )
    assertion_results = evaluate_assertions(verify_evidence, assertions) if verify_evidence is not None else []
    passed = bool(
        seed["passed"]
        and verify["passed"]
        and evidence_error is None
        and verify_evidence is not None
        and assertion_results
        and all(item["passed"] for item in assertion_results)
    )
    return {
        "attempt": attempt_number,
        "passed": passed,
        "profile": str(profile),
        "seed": seed,
        "verify": verify,
        "seed_evidence": seed_evidence,
        "verify_evidence": verify_evidence,
        "evidence_error": evidence_error,
        "assertions": assertion_results,
    }


def artifact_fingerprints(path_contract: dict[str, Any], contract_root: pathlib.Path) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for step_name in ("seed", "verify"):
        raw = path_contract[step_name]["command"][0]
        executable = pathlib.Path(raw)
        if not executable.is_absolute():
            executable = (contract_root / executable).resolve()
        result[step_name] = {
            "path": str(executable),
            "sha256": sha256(executable),
        }
    return result


def supplied_artifact_fingerprints(
    variables: dict[str, str] | None, contract_root: pathlib.Path
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for name, value in sorted((variables or {}).items()):
        if not name.endswith("_artifact"):
            continue
        artifact_path = pathlib.Path(value)
        if not artifact_path.is_absolute():
            artifact_path = (contract_root / artifact_path).resolve()
        result[name] = {
            "path": str(artifact_path),
            "exists": artifact_path.is_file(),
            "bytes": artifact_path.stat().st_size if artifact_path.is_file() else None,
            "sha256": sha256(artifact_path),
        }
    return result


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# State Migration Gate",
        "",
        f"Overall verdict: **{report['verdict'].upper()}**",
        "",
        "| Upgrade path | Status | Attempts |",
        "|---|---:|---:|",
    ]
    for path_result in report["paths"]:
        lines.append(f"| `{path_result['id']}` | {path_result['status']} | {len(path_result['attempts'])} |")
    lines.extend(["", "A flaky path passes only after an earlier failed attempt and fails the gate by default.", ""])
    return "\n".join(lines)


def execute(
    contract_path: pathlib.Path,
    output_root: pathlib.Path,
    run_id: str,
    external_variables: dict[str, str] | None = None,
) -> dict[str, Any]:
    contract = load_contract(contract_path)
    contract_root = contract_path.resolve().parent
    run_folder = (output_root / run_id).resolve()
    run_folder.mkdir(parents=True, exist_ok=False)
    fail_on_flaky = contract.get("fail_on_flaky", True)
    path_results: list[dict[str, Any]] = []

    for path_contract in contract["paths"]:
        attempts: list[dict[str, Any]] = []
        for attempt_number in range(1, path_contract.get("retries", 0) + 2):
            result = run_attempt(
                path_contract,
                attempt_number,
                contract_root,
                run_folder / path_contract["id"] / f"attempt-{attempt_number}",
                external_variables,
            )
            attempts.append(result)
            if result["passed"]:
                break
        if attempts[-1]["passed"] and len(attempts) == 1:
            status = "pass"
        elif attempts[-1]["passed"]:
            status = "flaky"
        else:
            status = "fail"
        path_results.append(
            {
                "id": path_contract["id"],
                "from": path_contract.get("from"),
                "to": path_contract.get("to"),
                "status": status,
                "artifacts": artifact_fingerprints(path_contract, contract_root),
                "attempts": attempts,
            }
        )

    passed = all(
        item["status"] == "pass" or (item["status"] == "flaky" and not fail_on_flaky)
        for item in path_results
    )
    report = {
        "contract_version": 1,
        "project": contract.get("project"),
        "run_id": run_id,
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "verdict": "pass" if passed else "fail",
        "fail_on_flaky": fail_on_flaky,
        "supplied_artifacts": supplied_artifact_fingerprints(
            external_variables, contract_root
        ),
        "paths": path_results,
    }
    (run_folder / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (run_folder / "summary.md").write_text(render_markdown(report), encoding="utf-8")
    report["report_path"] = str(run_folder / "report.json")
    report["summary_path"] = str(run_folder / "summary.md")
    return report


def default_run_id() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")


def main() -> int:
    parser = argparse.ArgumentParser(description="Prove desktop state survives an old-to-new release path.")
    parser.add_argument("--config", type=pathlib.Path, required=True)
    parser.add_argument("--output", type=pathlib.Path, default=pathlib.Path(".state-gate-results"))
    parser.add_argument("--run-id", default=default_run_id())
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument(
        "--var",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        help="Supply a named command placeholder; may be repeated.",
    )
    args = parser.parse_args()

    try:
        external_variables = parse_variables(args.var)
        contract = load_contract(args.config.resolve())
        if args.validate_only:
            print(json.dumps({"valid": True, "paths": [item["id"] for item in contract["paths"]]}, indent=2))
            return 0
        report = execute(
            args.config.resolve(), args.output.resolve(), args.run_id, external_variables
        )
    except (ContractError, OSError) as exc:
        print(json.dumps({"verdict": "error", "error": str(exc)}, indent=2), file=sys.stderr)
        return 2

    print(json.dumps(report, indent=2))
    github_step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if github_step_summary:
        with pathlib.Path(github_step_summary).open("a", encoding="utf-8") as handle:
            handle.write(render_markdown(report))
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with pathlib.Path(github_output).open("a", encoding="utf-8") as handle:
            handle.write(f"verdict={report['verdict']}\n")
            handle.write(f"report={report['report_path']}\n")
    return 0 if report["verdict"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
