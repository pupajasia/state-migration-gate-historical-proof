#!/usr/bin/env python3
"""Tiny deterministic adapter used only to test the composite-action plumbing."""

from __future__ import annotations

import argparse
import json
import pathlib


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("seed", "verify"), required=True)
    parser.add_argument("--source-artifact", type=pathlib.Path, required=True)
    parser.add_argument("--profile", type=pathlib.Path, required=True)
    parser.add_argument("--evidence", type=pathlib.Path, required=True)
    args = parser.parse_args()

    source_version = args.source_artifact.read_text(encoding="utf-8").strip()
    args.profile.mkdir(parents=True, exist_ok=True)
    state_path = args.profile / "semantic-state.json"

    if args.mode == "seed":
        passed = source_version == "old-v1"
        if passed:
            state_path.write_text(
                json.dumps({"stable_id": "task-42", "meaning": "keep-me"}),
                encoding="utf-8",
            )
        evidence = {"passed": passed, "source_version": source_version, "seeded": passed}
    else:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        meaning = state.get("meaning")
        if source_version == "candidate-bad":
            meaning = "silently-changed"
        evidence = {
            "passed": source_version == "candidate-good" and meaning == "keep-me",
            "source_version": source_version,
            "stable_id": state.get("stable_id"),
            "meaning": meaning,
        }

    args.evidence.parent.mkdir(parents=True, exist_ok=True)
    args.evidence.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return 0 if evidence["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
