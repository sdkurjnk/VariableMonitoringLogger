import sys
import unittest
from pathlib import Path

TEST_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TEST_DIR.parent
SRC_DIR = PROJECT_ROOT / "src"
TEST_PATTERN = "test_*.py"

def add_import_paths():
    # Allow tests to import both local test modules and the package under src.
    sys.path.insert(0, str(SRC_DIR))
    sys.path.insert(0, str(TEST_DIR))

def discover_tests():
    # Discover all unittest files that follow the test_*.py naming convention.
    loader = unittest.TestLoader()
    return loader.discover(
        start_dir=str(TEST_DIR),
        pattern=TEST_PATTERN,
    )

def run_tests(suite):
    # Keep verbosity=2 so each test name and status is shown in the output.
    runner = unittest.TextTestRunner(verbosity=2)
    return runner.run(suite)

def main():
    add_import_paths()
    suite = discover_tests()
    result = run_tests(suite)

    return 0 if result.wasSuccessful() else 1

if __name__ == "__main__":
    raise SystemExit(main())