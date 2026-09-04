#!/usr/bin/env python3
"""Validate and normalize the public composite-action inputs.

The action intentionally targets GitHub-hosted Windows runners. Local artifact
paths and evidence output stay inside GITHUB_WORKSPACE. A previous shipped
artifact must always be pinned by SHA-256, whether it is already in the
workspace or will be downloaded from an explicit GitHub release tag.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import re
import sys
from typing import Any


SHA256_PATTERN = re.compile(r"[0-9a-fA-F]{64}")
REPOSITORY_PATTERN = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")


class PreflightError(ValueError):
    """Raised when action inputs do not describe one safe, pinned run."""


def sha256_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def clean_text(value: str, label: str) -> str:
    if "\n" in value or "\r" in value or "\0" in value:
        raise PreflightError(f"{label} contains a forbidden control character")
    return value.strip()


def normalize_sha256(value: str, label: str, *, required: bool) -> str:
    value = clean_text(value, label).lower()
    if not value:
        if required:
            raise PreflightError(f"{label} is required")
        return ""
    if not SHA256_PATTERN.fullmatch(value):
        raise PreflightError(f"{label} must be exactly 64 hexadecimal characters")
    return value


def ensure_within_workspace(path: pathlib.Path, workspace: pathlib.Path, label: str) -> pathlib.Path:
    try:
        common = pathlib.Path(os.path.commonpath((str(path), str(workspace))))
    except ValueError as exc:
        raise PreflightError(f"{label} is outside GITHUB_WORKSPACE") from exc
    if os.path.normcase(str(common)) != os.path.normcase(str(workspace)):
        raise PreflightError(f"{label} is outside GITHUB_WORKSPACE")
    return path


def workspace_path(raw: str, workspace: pathlib.Path, label: str) -> pathlib.Path:
    raw = clean_text(raw, label)
    if not raw:
        raise PreflightError(f"{label} is required")
    candidate = pathlib.Path(raw)
    if not candidate.is_absolute():
        candidate = workspace / candidate
    return ensure_within_workspace(candidate.resolve(), workspace, label)


def workspace_file(raw: str, workspace: pathlib.Path, label: str) -> pathlib.Path:
    candidate = workspace_path(raw, workspace, label)
    if not candidate.is_file():
        raise PreflightError(f"{label} is not a file: {candidate}")
    return candidate


def validate_file_digest(path: pathlib.Path, expected: str, label: str) -> str:
    actual = sha256_file(path)
    if actual != expected:
        raise PreflightError(f"{label} SHA-256 does not match the pinned value")
    return actual


def preflight(values: dict[str, str]) -> dict[str, str]:
    runner_os = clean_text(values.get("runner_os", ""), "runner-os")
    if runner_os and runner_os.lower() != "windows":
        raise PreflightError("State Migration Gate currently requires a Windows runner")

    workspace_raw = clean_text(values.get("workspace", ""), "workspace")
    if not workspace_raw:
        raise PreflightError("workspace is required")
    workspace = pathlib.Path(workspace_raw).resolve()
    if not workspace.is_dir():
        raise PreflightError(f"workspace is not a directory: {workspace}")

    config = workspace_file(values.get("config", ""), workspace, "config")
    output = workspace_path(values.get("output", ""), workspace, "output")
    if output == workspace:
        raise PreflightError("output must not be the workspace root")

    candidate = workspace_file(
        values.get("candidate_artifact", ""), workspace, "candidate-artifact"
    )
    expected_candidate_sha = normalize_sha256(
        values.get("candidate_sha256", ""), "candidate-sha256", required=False
    )
    candidate_sha = sha256_file(candidate)
    if expected_candidate_sha and candidate_sha != expected_candidate_sha:
        raise PreflightError("candidate-artifact SHA-256 does not match candidate-sha256")

    previous_repo = clean_text(values.get("previous_repo", ""), "previous-repo")
    previous_artifact_raw = clean_text(
        values.get("previous_artifact", ""), "previous-artifact"
    )
    if bool(previous_repo) == bool(previous_artifact_raw):
        raise PreflightError(
            "set exactly one previous source: previous-repo or previous-artifact"
        )

    previous_release = clean_text(values.get("previous_release", ""), "previous-release")
    previous_asset_name = clean_text(
        values.get("previous_asset_name", ""), "previous-asset-name"
    )
    previous_asset_regex = clean_text(
        values.get("previous_asset_regex", ""), "previous-asset-regex"
    )
    previous_sha = normalize_sha256(
        values.get("previous_sha256", ""), "previous-sha256", required=True
    )

    result = {
        "config": str(config),
        "output": str(output),
        "candidate_artifact": str(candidate),
        "candidate_sha256": candidate_sha,
        "previous_sha256": previous_sha,
        "previous_artifact": "",
        "download_required": "false",
    }

    if previous_repo:
        if not REPOSITORY_PATTERN.fullmatch(previous_repo):
            raise PreflightError("previous-repo must use the exact owner/repository form")
        if not previous_release or previous_release.lower() == "latest":
            raise PreflightError("previous-release must be an explicit immutable tag, not latest")
        if bool(previous_asset_name) == bool(previous_asset_regex):
            raise PreflightError(
                "set exactly one of previous-asset-name or previous-asset-regex"
            )
        result["download_required"] = "true"
    else:
        if previous_release or previous_asset_name or previous_asset_regex:
            raise PreflightError(
                "release and asset selector inputs are only valid with previous-repo"
            )
        previous_artifact = workspace_file(
            previous_artifact_raw, workspace, "previous-artifact"
        )
        validate_file_digest(previous_artifact, previous_sha, "previous-artifact")
        result["previous_artifact"] = str(previous_artifact)

    return result


def write_github_outputs(values: dict[str, str]) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        return
    with pathlib.Path(output_path).open("a", encoding="utf-8") as handle:
        for name, value in values.items():
            if "\n" in value or "\r" in value:
                raise PreflightError(f"GitHub output contains a line break: {name}")
            handle.write(f"{name}={value}\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate State Migration Gate action inputs")
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--runner-os", default="")
    parser.add_argument("--config", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--previous-repo", default="")
    parser.add_argument("--previous-release", default="")
    parser.add_argument("--previous-asset-name", default="")
    parser.add_argument("--previous-asset-regex", default="")
    parser.add_argument("--previous-artifact", default="")
    parser.add_argument("--previous-sha256", default="")
    parser.add_argument("--candidate-artifact", default="")
    parser.add_argument("--candidate-sha256", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = preflight(vars(args))
        write_github_outputs(result)
    except (OSError, PreflightError) as exc:
        print(json.dumps({"valid": False, "error": str(exc)}, indent=2), file=sys.stderr)
        return 2
    print(json.dumps({"valid": True, **result}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
