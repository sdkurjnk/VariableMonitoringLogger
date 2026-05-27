import sys
import unittest
from pathlib import Path


TEST_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TEST_DIR.parent
SRC_DIR = PROJECT_ROOT / "src"

if __name__ == "__main__":
    sys.path.insert(0, str(SRC_DIR))
    sys.path.insert(0, str(TEST_DIR))

    loader = unittest.TestLoader()
    suite = loader.discover(
        start_dir=str(TEST_DIR),
        pattern="test_*.py",
    )

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    raise SystemExit(0 if result.wasSuccessful() else 1)