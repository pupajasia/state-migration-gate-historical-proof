from __future__ import annotations

import hashlib
import pathlib
import tempfile
import unittest

from action_preflight import PreflightError, preflight


class ActionPreflightTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.workspace = pathlib.Path(self.temporary.name).resolve()
        (self.workspace / "state-gate.json").write_text(
            '{"contract_version":1,"paths":[]}', encoding="utf-8"
        )
        (self.workspace / "old.exe").write_bytes(b"old")
        (self.workspace / "candidate.exe").write_bytes(b"candidate")
        self.old_sha = hashlib.sha256(b"old").hexdigest()
        self.candidate_sha = hashlib.sha256(b"candidate").hexdigest()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def base(self) -> dict[str, str]:
        return {
            "workspace": str(self.workspace),
            "runner_os": "Windows",
            "config": "state-gate.json",
            "output": ".state-gate-results",
            "previous_repo": "",
            "previous_release": "",
            "previous_asset_name": "",
            "previous_asset_regex": "",
            "previous_artifact": "old.exe",
            "previous_sha256": self.old_sha,
            "candidate_artifact": "candidate.exe",
            "candidate_sha256": self.candidate_sha,
        }

    def test_accepts_two_pinned_workspace_artifacts(self) -> None:
        result = preflight(self.base())
        self.assertEqual(result["download_required"], "false")
        self.assertEqual(result["previous_sha256"], self.old_sha)
        self.assertEqual(result["candidate_sha256"], self.candidate_sha)
        self.assertEqual(pathlib.Path(result["previous_artifact"]), self.workspace / "old.exe")

    def test_accepts_explicit_pinned_github_release(self) -> None:
        values = self.base()
        values.update(
            {
                "previous_artifact": "",
                "previous_repo": "owner/repository",
                "previous_release": "v1.2.3",
                "previous_asset_name": "app-portable.exe",
            }
        )
        result = preflight(values)
        self.assertEqual(result["download_required"], "true")
        self.assertEqual(result["previous_artifact"], "")

    def test_rejects_non_windows_runner(self) -> None:
        values = self.base()
        values["runner_os"] = "Linux"
        with self.assertRaisesRegex(PreflightError, "Windows runner"):
            preflight(values)

    def test_rejects_missing_or_duplicate_previous_source(self) -> None:
        values = self.base()
        values["previous_artifact"] = ""
        with self.assertRaisesRegex(PreflightError, "exactly one previous source"):
            preflight(values)
        values["previous_artifact"] = "old.exe"
        values["previous_repo"] = "owner/repository"
        with self.assertRaisesRegex(PreflightError, "exactly one previous source"):
            preflight(values)

    def test_rejects_latest_or_ambiguous_release_selector(self) -> None:
        values = self.base()
        values.update(
            {
                "previous_artifact": "",
                "previous_repo": "owner/repository",
                "previous_release": "latest",
                "previous_asset_name": "app.exe",
            }
        )
        with self.assertRaisesRegex(PreflightError, "explicit immutable tag"):
            preflight(values)
        values["previous_release"] = "v1"
        values["previous_asset_regex"] = ".*"
        with self.assertRaisesRegex(PreflightError, "exactly one"):
            preflight(values)

    def test_rejects_missing_or_wrong_previous_hash(self) -> None:
        values = self.base()
        values["previous_sha256"] = ""
        with self.assertRaisesRegex(PreflightError, "previous-sha256 is required"):
            preflight(values)
        values["previous_sha256"] = "0" * 64
        with self.assertRaisesRegex(PreflightError, "does not match"):
            preflight(values)

    def test_rejects_wrong_candidate_hash_but_allows_computed_hash(self) -> None:
        values = self.base()
        values["candidate_sha256"] = "0" * 64
        with self.assertRaisesRegex(PreflightError, "does not match"):
            preflight(values)
        values["candidate_sha256"] = ""
        self.assertEqual(preflight(values)["candidate_sha256"], self.candidate_sha)

    def test_rejects_workspace_escape_and_workspace_root_output(self) -> None:
        values = self.base()
        values["candidate_artifact"] = "../candidate.exe"
        with self.assertRaisesRegex(PreflightError, "outside GITHUB_WORKSPACE"):
            preflight(values)
        values = self.base()
        values["output"] = "."
        with self.assertRaisesRegex(PreflightError, "must not be the workspace root"):
            preflight(values)

    def test_rejects_release_fields_for_local_artifact(self) -> None:
        values = self.base()
        values["previous_release"] = "v1"
        with self.assertRaisesRegex(PreflightError, "only valid with previous-repo"):
            preflight(values)


if __name__ == "__main__":
    unittest.main()
