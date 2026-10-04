"""Structural evidence check only; actual artifacts require independent hashing."""
import json
from pathlib import Path
import re
import unittest


def invalid_digests(value, path=""):
    errors = []
    if isinstance(value, dict):
        for key, child in value.items():
            name = path + "/" + key
            if key.lower().endswith("sha256") and isinstance(child, str) and not re.fullmatch(r"[0-9a-fA-F]{64}", child):
                errors.append(name)
            errors.extend(invalid_digests(child, name))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            errors.extend(invalid_digests(child, path + "/" + str(index)))
    return errors


class MigrationEvidenceDigestTests(unittest.TestCase):
    def test_recorded_sha256_strings_are_not_truncated_or_console_wrap_duplicates(self):
        path = Path(__file__).resolve().parents[2] / "pc-router" / "deployment-status.json"
        with path.open() as source:
            self.assertEqual(invalid_digests(json.load(source)), [])

    def test_nested_bad_digests_fail_but_optional_absence_is_not_fabricated(self):
        value = {"runs": [{"sha256": "a" * 65}, {"archive_sha256": "g" * 64}, {"sha256": None},
                           {"router_sha256": "A" * 64}]}
        self.assertEqual(invalid_digests(value), ["/runs/0/sha256", "/runs/1/archive_sha256"])


if __name__ == "__main__":
    unittest.main()
