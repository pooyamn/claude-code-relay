#!/usr/bin/env python3
"""Catalog/run exact core cases inside the OS sandbox, without host discovery."""
import argparse
import json
from pathlib import Path
import sys
import unittest

from run_isolated import core_batches


def flatten(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from flatten(item)
        else:
            yield item.id()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--list", action="store_true")
    mode.add_argument("--run", nargs="+")
    args = parser.parse_args()
    loader = unittest.TestLoader()
    if args.list:
        suite = loader.discover(str(Path(__file__).resolve().parent), pattern="test_core*.py")
        if loader.errors:
            raise RuntimeError("core discovery failed:\n" + "\n".join(loader.errors))
        catalog = list(flatten(suite))
        core_batches(catalog)
        print(json.dumps(catalog))
        return 0
    batches = core_batches(args.run)
    if len(batches) != 1:
        parser.error("one bounded batch per child required")
    suite = loader.loadTestsFromNames(args.run)
    if loader.errors or suite.countTestCases() != len(args.run):
        raise RuntimeError("exact core case loading failed:\n" + "\n".join(loader.errors))
    return 0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
