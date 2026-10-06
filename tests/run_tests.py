#!/usr/bin/env python3
"""
Run all BHTTP/1.0 tests.

Usage:
    python tests/run_tests.py          # run everything
    python tests/run_tests.py unit     # only protocol unit tests
    python tests/run_tests.py integ    # only integration tests
"""

import os
import sys
import unittest

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR  = os.path.dirname(TESTS_DIR)

sys.path.insert(0, ROOT_DIR)


def _suite_for(pattern):
    loader = unittest.TestLoader()
    return loader.discover(TESTS_DIR, pattern=pattern)


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"

    if mode == "unit":
        suite = _suite_for("test_protocol.py")
        label = "protocol unit tests"
    elif mode in ("integ", "integration"):
        suite = _suite_for("test_integration.py")
        label = "integration tests"
    elif mode == "all":
        suite = _suite_for("test_*.py")
        label = "all tests"
    else:
        sys.exit(f"unknown mode {mode!r}. use: unit | integ | all")

    print(f"Running {label} ...\n")
    runner = unittest.TextTestRunner(verbosity=2, stream=sys.stdout)
    result = runner.run(suite)

    print()
    total  = result.testsRun
    passed = total - len(result.failures) - len(result.errors)
    print(f"Results: {passed}/{total} passed")

    sys.exit(0 if result.wasSuccessful() else 1)


if __name__ == "__main__":
    main()
