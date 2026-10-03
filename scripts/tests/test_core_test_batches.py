"""All-case serial batching changes scheduling, not coverage or time ceilings."""
import unittest

from run_isolated import core_batches, select_core_tests


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

    def test_real_git_replays_run_alone_with_all_neighbors_preserved(self):
        catalog = ["test_core_a.Cases.test_first", "test_core_a.Cases.test_second",
                   "test_core_post_merge.Cases.test_replay_one", "test_core_post_merge.Cases.test_replay_two",
                   "test_core_z.Cases.test_last"]
        batches = core_batches(list(reversed(catalog)))
        self.assertEqual([name for batch in batches for name in batch], sorted(catalog))
        self.assertTrue(all(1 <= len(batch) <= 4 for batch in batches))
        self.assertTrue(all(len(batch) == 1 for batch in batches if any(name.startswith("test_core_post_merge.") for name in batch)))

    def test_focused_modules_select_every_case_with_exact_module_boundaries(self):
        catalog = ["test_core_a.Cases.test_second", "test_core_ab.Cases.test_other",
                   "test_core_a.Cases.test_first", "test_core_z.Cases.test_last"]
        self.assertEqual(select_core_tests(catalog, ["test_core_a"]),
                         [catalog[0], catalog[2]])
        self.assertEqual(select_core_tests(catalog, ["test_core_a"], [catalog[0], catalog[3]]),
                         [catalog[0], catalog[2], catalog[3]])
        self.assertEqual([name for batch in core_batches(select_core_tests(catalog, ["test_core_a"]))
                          for name in batch], sorted([catalog[0], catalog[2]]))

    def test_no_focus_preserves_the_full_catalog_without_mutating_it(self):
        catalog = ["test_core_a.Cases.test_second", "test_core_a.Cases.test_first"]
        selected = select_core_tests(catalog)
        self.assertEqual(selected, catalog)
        self.assertIsNot(selected, catalog)

    def test_undiscovered_duplicate_and_non_core_selectors_fail_closed(self):
        catalog = ["test_core_a.Cases.test_one"]
        for modules, tests in ((["test_core_missing"], []), (["test_core_a"] * 2, []),
                               (["os.system"], []), (["test_core_a;evil"], []),
                               ([], ["test_core_a.Cases.test_missing"]),
                               ([], catalog * 2), ([], ["os.system"]),
                               (["test_core_a", "test_core_missing"], catalog)):
            with self.subTest(modules=modules, tests=tests), self.assertRaises(RuntimeError):
                select_core_tests(catalog, modules, tests)

    def test_focus_does_not_hide_invalid_unselected_catalog_entries(self):
        good = "test_core_a.Cases.test_one"
        for catalog in ([good, "os.system"], [good, good], []):
            with self.assertRaises(RuntimeError):
                select_core_tests(catalog, ["test_core_a"])


if __name__ == "__main__":
    unittest.main()
