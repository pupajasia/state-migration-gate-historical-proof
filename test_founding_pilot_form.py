from __future__ import annotations

import pathlib
import re
import unittest


REPOSITORY = pathlib.Path(__file__).resolve().parent
FORM_PATH = REPOSITORY / ".github" / "ISSUE_TEMPLATE" / "founding-pilot-interest.yml"
README_PATH = REPOSITORY / "README.md"


class FoundingPilotFormTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.form = FORM_PATH.read_text(encoding="utf-8")

    def test_has_expected_top_level_routing(self) -> None:
        self.assertIn("name: Founding pilot interest\n", self.form)
        self.assertIn('title: "[pilot interest] "\n', self.form)
        self.assertRegex(self.form, r"(?m)^labels:\n  - pilot-interest$")
        self.assertNotIn("\t", self.form)

    def test_question_contract_is_complete_and_ordered(self) -> None:
        expected_ids = [
            "product",
            "team",
            "role",
            "framework",
            "packaging",
            "path",
            "artifacts",
            "semantics",
            "budget",
            "ai",
            "ip",
            "consent",
        ]
        ids = re.findall(r"(?m)^    id: ([A-Za-z0-9_-]+)$", self.form)
        self.assertEqual(ids, expected_ids)
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(re.findall(r"(?m)^  - type: ", self.form)), 13)

    def test_every_question_requires_an_answer(self) -> None:
        blocks = re.split(r"(?m)(?=^  - type: )", self.form)
        question_blocks = [block for block in blocks if "\n    id: " in block]
        self.assertEqual(len(question_blocks), 12)
        for block in question_blocks:
            field_id = re.search(r"(?m)^    id: ([A-Za-z0-9_-]+)$", block)
            self.assertIsNotNone(field_id)
            with self.subTest(field=field_id.group(1)):
                self.assertIn("required: true", block)

    def test_triage_facing_choices_are_stable(self) -> None:
        required_choices = (
            "Commercial paid desktop product",
            "I can approve the release test and its budget",
            "Electron",
            "Both Windows-x64 builds can later be made available in a buyer-controlled disposable test environment without production secrets or customer data.",
            "EUR 149 is acceptable subject to confirmed scope and tax treatment",
            "Codex-assisted test preparation and minimized evidence analysis is allowed",
            "I understand the reusable engine remains separately licensed and non-exclusive",
            "I am voluntarily asking the repository owner to reply to this issue about this pilot request.",
        )
        for choice in required_choices:
            with self.subTest(choice=choice):
                self.assertEqual(
                    len(
                        re.findall(
                            rf"(?m)^\s+- (?:label: )?{re.escape(choice)}$",
                            self.form,
                        )
                    ),
                    1,
                )

    def test_readme_links_to_the_exact_form(self) -> None:
        readme = README_PATH.read_text(encoding="utf-8")
        self.assertIn(
            "https://github.com/pupajasia/state-migration-gate-historical-proof/"
            "issues/new?template=founding-pilot-interest.yml",
            readme,
        )

    def test_price_language_does_not_pretend_tax_readiness(self) -> None:
        readme = README_PATH.read_text(encoding="utf-8")
        self.assertNotIn("EUR 149 net", self.form)
        self.assertNotIn("EUR 149 net", readme)
        self.assertIn("tax treatment", self.form)
        self.assertIn("tax treatment", readme)


if __name__ == "__main__":
    unittest.main()
