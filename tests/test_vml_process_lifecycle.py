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


def read_jsonl(filename):
    with open(filename, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def run_python_script(script):
    with tempfile.TemporaryDirectory() as temp_dir:
        script_path = os.path.join(temp_dir, "sample_program.py")

        with open(script_path, "w", encoding="utf-8") as f:
            f.write(script)

        env = os.environ.copy()
        env["PYTHONPATH"] = str(SRC_DIR) + os.pathsep + env.get("PYTHONPATH", "")

        result = subprocess.run(
            [sys.executable, script_path],
            cwd=str(PROJECT_ROOT),
            env=env,
            text=True,
            capture_output=True
        )

        return result


class TestVMLProcessLifecycle(unittest.TestCase):

    def test_atexit_saves_log_without_manual_final_save(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_file = os.path.join(temp_dir, "atexit_basic.jsonl")

            script = textwrap.dedent(f"""
                import vml

                target = [1, 2]
                monitor = vml.logger("target", filename={log_file!r})

                target.append(3)

                checkpoint = "after append"
                print(checkpoint)
            """)

            result = run_python_script(script)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(os.path.exists(log_file))

            logs = read_jsonl(log_file)

        self.assertEqual(logs[0]["event"], "init")
        self.assertEqual(logs[0]["data"], [1, 2])
        self.assertEqual(logs[-1]["event"], "updated")
        self.assertEqual(logs[-1]["data"], [1, 2, 3])

    def test_return_event_captures_last_change_inside_function(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_file = os.path.join(temp_dir, "return_event.jsonl")

            script = textwrap.dedent(f"""
                import vml

                def run():
                    target = {{"count": 1}}
                    monitor = vml.logger("target", filename={log_file!r})
                    target["count"] = 2
                    return "done"

                print(run())
            """)

            result = run_python_script(script)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(os.path.exists(log_file))

            logs = read_jsonl(log_file)

        self.assertEqual(logs[0]["event"], "init")
        self.assertEqual(logs[0]["data"], {"count": 1})
        self.assertEqual(logs[-1]["event"], "updated")
        self.assertEqual(logs[-1]["data"], {"count": 2})

    def test_atexit_saves_multiple_variables_from_single_monitor(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_file = os.path.join(temp_dir, "multiple_variables_atexit.jsonl")

            script = textwrap.dedent(f"""
                import vml

                first = [10]
                second = "before"

                monitor = vml.VML({log_file!r})
                monitor.logger("first")
                monitor.logger("second")

                first.append(20)
                second = "after"

                checkpoint = "after multiple updates"
                print(checkpoint)
            """)

            result = run_python_script(script)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(os.path.exists(log_file))

            logs = read_jsonl(log_file)

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

    def test_process_log_uses_jsonl_schema_after_exit(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_file = os.path.join(temp_dir, "schema_after_exit.jsonl")

            script = textwrap.dedent(f"""
                import vml

                target = {{"state": "start"}}
                monitor = vml.logger("target", filename={log_file!r})

                target["state"] = "end"

                checkpoint = "after schema update"
                print(checkpoint)
            """)

            result = run_python_script(script)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(os.path.exists(log_file))

            logs = read_jsonl(log_file)

        self.assertGreaterEqual(len(logs), 2)

        for entry in logs:
            self.assertEqual(set(entry.keys()), {"name", "data", "event", "domain", "line"})
            self.assertEqual(entry["name"], "target")
            self.assertIn(entry["event"], {"init", "updated", "deleted"})


if __name__ == "__main__":
    unittest.main(verbosity=2)