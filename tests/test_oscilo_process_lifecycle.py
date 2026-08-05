import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
DEFAULT_LOG_NAME = "oscilo.jsonl"
EXPECTED_LOG_KEYS = {"name", "var_id", "data", "event", "domain", "line", "func", "call_id", "parent_call_id", "call_depth", }
TRACKING_EVENTS = {"init", "updated", "deleted"}
TRACKING_DOMAINS = {"LOCAL", "GLOBAL"}

def read_jsonl(filename):
    # Read VMlog output as JSONL, where each line is one log entry.
    with open(filename, "r", encoding="utf-8") as file:
        return [json.loads(line) for line in file]

def build_pythonpath():
    # Make the local src package importable inside subprocess-based tests.
    existing_pythonpath = os.environ.get("PYTHONPATH", "")
    return str(SRC_DIR) + os.pathsep + existing_pythonpath

def run_python_script(script, cwd):
    # Run the sample program in a separate process to exercise atexit behavior.
    # cwd is the script's own temp directory so the default "oscilo.jsonl" output
    # lands there instead of polluting the project root.
    script_path = os.path.join(cwd, "sample_program.py")

    with open(script_path, "w", encoding="utf-8") as file:
        file.write(script)

    env = os.environ.copy()
    env["PYTHONPATH"] = build_pythonpath()

    return subprocess.run(
        [sys.executable, script_path],
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
    )

def run_script_and_read_logs(test_case, script, temp_dir):
    # Assert the subprocess completed successfully before reading its log output.
    result = run_python_script(script, temp_dir)
    log_file = os.path.join(temp_dir, DEFAULT_LOG_NAME)

    test_case.assertEqual(result.returncode, 0, result.stderr)
    test_case.assertTrue(os.path.exists(log_file))

    return read_jsonl(log_file)

class TestVMlogProcessLifecycle(unittest.TestCase):
    def test_atexit_saves_log_without_manual_final_save(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script = textwrap.dedent("""
                import oscilo

                target = [1, 2]
                oscilo.register("target")

                target.append(3)

                checkpoint = "after append"
                print(checkpoint)
            """)

            logs = run_script_and_read_logs(self, script, temp_dir)

        self.assertEqual(logs[0]["event"], "init")
        self.assertEqual(logs[0]["data"], [1, 2])
        self.assertEqual(logs[-1]["event"], "updated")
        self.assertEqual(logs[-1]["data"], [1, 2, 3])

    def test_return_event_captures_last_change_inside_function(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script = textwrap.dedent("""
                import oscilo

                def run():
                    target = {"count": 1}
                    oscilo.register("target")
                    target["count"] = 2
                    return "done"

                print(run())
            """)

            logs = run_script_and_read_logs(self, script, temp_dir)

        self.assertEqual(logs[0]["event"], "init")
        self.assertEqual(logs[0]["data"], {"count": 1})
        self.assertEqual(logs[-1]["event"], "updated")
        self.assertEqual(logs[-1]["data"], {"count": 2})

    def test_atexit_saves_multiple_variables_from_single_default_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script = textwrap.dedent("""
                import oscilo

                first = [10]
                second = "before"

                oscilo.register("first")
                oscilo.register("second")

                first.append(20)
                second = "after"

                checkpoint = "after multiple updates"
                print(checkpoint)
            """)

            logs = run_script_and_read_logs(self, script, temp_dir)

        first_logs = [entry for entry in logs if entry["name"] == "first"]
        second_logs = [entry for entry in logs if entry["name"] == "second"]

        self.assertGreaterEqual(len(first_logs), 2)
        self.assertGreaterEqual(len(second_logs), 2)

        self.assertEqual(first_logs[0]["event"], "init")
        self.assertEqual(first_logs[-1]["event"], "updated")
        self.assertEqual(first_logs[-1]["data"], [10, 20])

        self.assertEqual(second_logs[0]["event"], "init")
        self.assertEqual(second_logs[-1]["event"], "updated")
        self.assertEqual(second_logs[-1]["data"], "after")

    def test_register_on_unpicklable_value_does_not_crash_traced_program(self):
        # Case 1 from oscilo issue #51: registering a value that cannot be
        # deepcopy'd (threading.Lock) must not let TypeError from
        # sys.settrace's callback escape into the traced program.
        with tempfile.TemporaryDirectory() as temp_dir:
            script = textwrap.dedent("""
                import threading
                import oscilo

                def run():
                    lock = threading.Lock()
                    oscilo.register("lock")
                    print("done")

                run()
            """)

            logs = run_script_and_read_logs(self, script, temp_dir)

        self.assertEqual(logs[0]["name"], "lock")
        self.assertEqual(logs[0]["event"], "init")
        self.assertIsInstance(logs[0]["data"], str)

    def test_register_on_value_whose_copy_is_itself_uncopyable_does_not_crash(self):
        # The initial deepcopy in _make_state() succeeds here (__deepcopy__
        # doesn't raise), but hands back a lock. The second deepcopy inside
        # get_snapshot() then fails while building the log entry, which must
        # not let TypeError escape the trace callback and abort the program.
        with tempfile.TemporaryDirectory() as temp_dir:
            script = textwrap.dedent("""
                import threading
                import oscilo

                class CopyReturnsUncopyable:
                    def __deepcopy__(self, memo):
                        return threading.Lock()

                def run():
                    target = CopyReturnsUncopyable()
                    oscilo.register("target")
                    checkpoint = "program continued"
                    print(checkpoint)

                run()
            """)

            result = run_python_script(script, temp_dir)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("program continued", result.stdout)

            log_file = os.path.join(temp_dir, DEFAULT_LOG_NAME)
            self.assertTrue(os.path.exists(log_file))
            logs = read_jsonl(log_file)

        target_logs = [entry for entry in logs if entry["name"] == "target"]

        self.assertEqual(target_logs[0]["event"], "init")
        self.assertIsInstance(target_logs[0]["data"], str)

    def test_reassigning_tracked_value_to_unpicklable_value_keeps_running(self):
        # Case 2 from oscilo issue #51: assigning an unpicklable value to an
        # already-tracked variable used to raise TypeError from inside the
        # trace callback, aborting the traced program before it finished.
        with tempfile.TemporaryDirectory() as temp_dir:
            script = textwrap.dedent("""
                import threading
                import oscilo

                def run():
                    data = [1, 2, 3]
                    oscilo.register("data")
                    data = threading.Lock()
                    x = 42
                    print("end", x)

                run()
            """)

            result = run_python_script(script, temp_dir)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("end 42", result.stdout)

            log_file = os.path.join(temp_dir, DEFAULT_LOG_NAME)
            self.assertTrue(os.path.exists(log_file))
            logs = read_jsonl(log_file)

        data_logs = [entry for entry in logs if entry["name"] == "data"]

        self.assertEqual(data_logs[0]["event"], "init")
        self.assertEqual(data_logs[0]["data"], [1, 2, 3])
        self.assertEqual(data_logs[-1]["event"], "updated")
        self.assertIsInstance(data_logs[-1]["data"], str)

    def test_process_log_uses_jsonl_schema_after_exit(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script = textwrap.dedent("""
                import oscilo

                target = {"state": "start"}
                oscilo.register("target")

                target["state"] = "end"

                checkpoint = "after schema update"
                print(checkpoint)
            """)

            logs = run_script_and_read_logs(self, script, temp_dir)

        self.assertGreaterEqual(len(logs), 2)

        for entry in logs:
            self.assertEqual(set(entry.keys()), EXPECTED_LOG_KEYS)
            self.assertEqual(entry["name"], "target")
            self.assertIn(entry["event"], TRACKING_EVENTS)
            self.assertIn(entry["domain"], TRACKING_DOMAINS)
            self.assertTrue(
                entry["line"] is None or isinstance(entry["line"], int),
                f"Expected 'line' to be an int or None, got {entry['line']!r}",
            )

if __name__ == "__main__":
    unittest.main(verbosity=2)
