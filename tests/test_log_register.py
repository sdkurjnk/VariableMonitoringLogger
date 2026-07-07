import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

import vmlog

DEFAULT_LOG_NAME = "vmlog.jsonl"

# Resolve the directory that contains the vmlog package so subprocess scenarios
# import the same package regardless of src layout or installed layout.
PACKAGE_PARENT = Path(vmlog.__file__).resolve().parents[1]

def run_scenario(test_case, temp_dir, source):
    # Each scenario runs in its own interpreter because atexit-driven saving and
    # sys.settrace state can only be verified across a full process lifetime.
    script_path = os.path.join(temp_dir, "scenario.py")

    with open(script_path, "w", encoding="utf-8") as file:
        file.write(textwrap.dedent(source))

    env = os.environ.copy()
    env["PYTHONPATH"] = str(PACKAGE_PARENT) + os.pathsep + env.get("PYTHONPATH", "")

    result = subprocess.run(
        [sys.executable, script_path],
        cwd=temp_dir,
        env=env,
        capture_output=True,
        text=True,
    )

    test_case.assertEqual(result.returncode, 0, result.stderr)
    return result

def read_default_log(test_case, temp_dir):
    log_path = os.path.join(temp_dir, DEFAULT_LOG_NAME)
    test_case.assertTrue(os.path.exists(log_path), "expected vmlog.jsonl to be written")

    with open(log_path, "r", encoding="utf-8") as file:
        return [json.loads(line) for line in file]

def events_for(entries, name):
    return [(entry["event"], entry["data"]) for entry in entries if entry["name"] == name]

class TestLogRegisterPublicAPI(unittest.TestCase):
    def test_two_variables_merge_into_single_default_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            run_scenario(self, temp_dir, """
                from vmlog import logRegister

                def run():
                    A = 1
                    result = logRegister("A")
                    assert result is None
                    A = 2
                    B = 10
                    logRegister("B")
                    A = 3
                    B = 20

                run()
            """)

            entries = read_default_log(self, temp_dir)

        self.assertEqual(events_for(entries, "A"), [("init", 1), ("updated", 2), ("updated", 3)])
        self.assertEqual(events_for(entries, "B"), [("init", 10), ("updated", 20)])

    def test_second_registration_does_not_clobber_first(self):
        # Regression for issue #29: a later logRegister() call must not hijack
        # tracing or overwrite the history collected for earlier variables.
        with tempfile.TemporaryDirectory() as temp_dir:
            run_scenario(self, temp_dir, """
                from vmlog import logRegister

                def first():
                    A = 1
                    logRegister("A")
                    A = 2

                def second():
                    B = 10
                    logRegister("B")
                    B = 20

                first()
                second()
            """)

            entries = read_default_log(self, temp_dir)

        self.assertEqual(events_for(entries, "A"), [("init", 1), ("updated", 2)])
        self.assertEqual(events_for(entries, "B"), [("init", 10), ("updated", 20)])

    def test_import_only_leaves_no_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            run_scenario(self, temp_dir, "import vmlog\n")

            self.assertFalse(os.path.exists(os.path.join(temp_dir, DEFAULT_LOG_NAME)))

    def test_register_without_events_leaves_no_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            run_scenario(self, temp_dir, """
                from vmlog import logRegister

                logRegister("this_name_never_exists")
            """)

            self.assertFalse(os.path.exists(os.path.join(temp_dir, DEFAULT_LOG_NAME)))

    def test_public_api_surface(self):
        # Importing vmlog is side-effect free, so this check can run in-process.
        self.assertEqual(vmlog.__all__, ["logRegister"])
        self.assertTrue(callable(vmlog.logRegister))
        self.assertFalse(hasattr(vmlog, "logger"))
        self.assertFalse(hasattr(vmlog, "VMlog"))
        self.assertFalse(hasattr(vmlog, "register"))

if __name__ == "__main__":
    unittest.main(verbosity=2)
