import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

import oscilo

DEFAULT_LOG_NAME = "oscilo.jsonl"

# Resolve the directory that contains the oscilo package so subprocess scenarios
# import the same package regardless of src layout or installed layout.
PACKAGE_PARENT = Path(oscilo.__file__).resolve().parents[1]

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
    test_case.assertTrue(os.path.exists(log_path), "expected oscilo.jsonl to be written")

    with open(log_path, "r", encoding="utf-8") as file:
        return [json.loads(line) for line in file]

def events_for(entries, name):
    return [(entry["event"], entry["data"]) for entry in entries if entry["name"] == name]

class TestRegisterPublicAPI(unittest.TestCase):
    def test_two_variables_merge_into_single_default_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            run_scenario(self, temp_dir, """
                from oscilo import register

                def run():
                    A = 1
                    result = register("A")
                    assert result is None
                    A = 2
                    B = 10
                    register("B")
                    A = 3
                    B = 20

                run()
            """)

            entries = read_default_log(self, temp_dir)

        self.assertEqual(events_for(entries, "A"), [("init", 1), ("updated", 2), ("updated", 3)])
        self.assertEqual(events_for(entries, "B"), [("init", 10), ("updated", 20)])

    def test_second_registration_does_not_clobber_first(self):
        # Regression for issue #29: a later register() call must not hijack
        # tracing or overwrite the history collected for earlier variables.
        with tempfile.TemporaryDirectory() as temp_dir:
            run_scenario(self, temp_dir, """
                from oscilo import register

                def first():
                    A = 1
                    register("A")
                    A = 2

                def second():
                    B = 10
                    register("B")
                    B = 20

                first()
                second()
            """)

            entries = read_default_log(self, temp_dir)

        self.assertEqual(events_for(entries, "A"), [("init", 1), ("updated", 2)])
        self.assertEqual(events_for(entries, "B"), [("init", 10), ("updated", 20)])

    def test_global_update_in_active_module_frame_is_tracked(self):
        # Regression for issue #39: sys.settrace() does not retroactively
        # attach line tracing to module frames that were already active when
        # register() was called from a child frame.
        with tempfile.TemporaryDirectory() as temp_dir:
            run_scenario(self, temp_dir, """
                import oscilo

                A = 10

                def register_a():
                    oscilo.register("A")

                def update_a():
                    global A
                    A = 11

                register_a()
                update_a()
                A = 12

                checkpoint = "after module update"
                print(checkpoint)
            """)

            entries = read_default_log(self, temp_dir)

        a_entries = [
            entry
            for entry in entries
            if entry["name"] == "A"
        ]

        self.assertEqual(
            events_for(entries, "A"),
            [
                ("init", 10),
                ("updated", 11),
                ("updated", 12),
            ],
        )
        self.assertEqual(a_entries[-1]["domain"], "GLOBAL")
        self.assertEqual(a_entries[-1]["func"], "<module>")

    def test_global_update_in_active_parent_function_is_tracked(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            run_scenario(self, temp_dir, """
                import oscilo

                A = 10

                def outer():
                    global A

                    def register_a():
                        oscilo.register("A")

                    register_a()
                    A = 20

                    checkpoint = "after parent update"
                    print(checkpoint)

                outer()
            """)

            entries = read_default_log(self, temp_dir)

        a_entries = [
            entry
            for entry in entries
            if entry["name"] == "A"
        ]

        self.assertEqual(
            events_for(entries, "A"),
            [
                ("init", 10),
                ("updated", 20),
            ],
        )
        self.assertEqual(a_entries[-1]["domain"], "GLOBAL")
        self.assertEqual(a_entries[-1]["func"], "outer")

    def test_import_only_leaves_no_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            run_scenario(self, temp_dir, "import oscilo\n")

            self.assertFalse(os.path.exists(os.path.join(temp_dir, DEFAULT_LOG_NAME)))

    def test_register_without_events_leaves_no_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            run_scenario(self, temp_dir, """
                from oscilo import register

                register("this_name_never_exists")
            """)

            self.assertFalse(os.path.exists(os.path.join(temp_dir, DEFAULT_LOG_NAME)))

    def test_public_api_surface(self):
        # Importing oscilo is side-effect free, so this check can run in-process.
        self.assertEqual(oscilo.__all__, ["register"])
        self.assertTrue(callable(oscilo.register))
        self.assertFalse(hasattr(oscilo, "logger"))
        self.assertFalse(hasattr(oscilo, "VMlog"))
        self.assertFalse(hasattr(oscilo, "logRegister"))

if __name__ == "__main__":
    unittest.main(verbosity=2)
