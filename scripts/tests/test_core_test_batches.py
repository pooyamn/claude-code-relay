"""All-case serial batching changes scheduling, not coverage or time ceilings."""
import unittest

from run_isolated import core_batches


class BatchTests(unittest.TestCase):
    def test_every_case_is_preserved_exactly_once_in_bounded_sorted_batches(self):
        catalog = ["test_core_fixture.Cases.test_case_" + str(index) for index in range(35)]
        batches = core_batches(list(reversed(catalog)))
        self.assertEqual([name for batch in batches for name in batch], sorted(catalog))
        self.assertEqual(len(batches), 9)
        self.assertTrue(all(1 <= len(batch) <= 4 for batch in batches))

    def test_unknown_empty_duplicate_or_non_core_imports_are_rejected(self):
        for catalog in ([], {}, ["os.system"], ["test_core_fixture.Case.runTest"],
                        ["test_core_fixture.Case.test_one"] * 2, [1],
                        ["test_core_fixture.Case.test_one;evil"], ["test_core_fixture.Case.test_x" * 100]):
            with self.subTest(catalog=catalog), self.assertRaises(RuntimeError):
                core_batches(catalog)


if __name__ == "__main__":
    unittest.main()
