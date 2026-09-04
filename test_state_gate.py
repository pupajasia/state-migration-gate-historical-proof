from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest

import state_gate


class ArtifactFingerprintTests(unittest.TestCase):
    def test_bare_path_command_resolves_through_path(self) -> None:
        contract = {
            "seed": {"command": [sys.executable]},
            "verify": {"command": ["python"]},
        }
        result = state_gate.artifact_fingerprints(contract, pathlib.Path.cwd())

        self.assertTrue(result["seed"]["exists"])
        self.assertIsNotNone(result["seed"]["sha256"])
        self.assertTrue(result["verify"]["exists"])
        self.assertIsNotNone(result["verify"]["sha256"])

    def test_relative_script_is_resolved_from_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            script = root / "tools" / "adapter.cmd"
            script.parent.mkdir()
            script.write_bytes(b"@echo off\r\n")
            contract = {
                "seed": {"command": ["tools/adapter.cmd"]},
                "verify": {"command": ["missing-command"]},
            }

            result = state_gate.artifact_fingerprints(contract, root)

        self.assertEqual(result["seed"]["path"], str(script.resolve()))
        self.assertTrue(result["seed"]["exists"])
        self.assertIsNotNone(result["seed"]["sha256"])
        self.assertEqual(result["verify"]["path"], "missing-command")
        self.assertFalse(result["verify"]["exists"])
        self.assertIsNone(result["verify"]["sha256"])


if __name__ == "__main__":
    unittest.main()
