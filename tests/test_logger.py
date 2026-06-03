import json
import os
import tempfile
import unittest

import vml

INIT_EVENT = "init"
UPDATED_EVENT = "updated"
DELETED_EVENT = "deleted"

def read_jsonl(filename):
    # Read VML output as JSONL, where each line contains one log entry.
    with open(filename, "r", encoding="utf-8") as file:
        return [json.loads(line) for line in file]

def finalize_and_read_logs(monitor, filename):
    # Force VML to write pending trace events before assertions inspect the log file.
    monitor._finalSave()
    return read_jsonl(filename)

class TestVMLLoggerPackage(unittest.TestCase):
    def test_package_imports_public_api(self):
        self.assertTrue(hasattr(vml, "logger"))
        self.assertTrue(hasattr(vml, "VML"))

    def test_logger_writes_init_and_update_events(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            filename = os.path.join(temp_dir, "vml_package_test.jsonl")

            data_target = [100, 200]
            monitor = vml.logger("data_target", filename=filename)

            data_target.append(300)

            # Run one more traced line so the append operation can be captured.
            checkpoint = "after append"
            self.assertEqual(checkpoint, "after append")

            logs = finalize_and_read_logs(monitor, filename)

        self.assertEqual(logs[0]["event"], INIT_EVENT)
        self.assertEqual(logs[0]["data"], [100, 200])
        self.assertEqual(logs[-1]["event"], UPDATED_EVENT)
        self.assertEqual(logs[-1]["data"], [100, 200, 300])

    def test_logger_writes_deleted_event(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            filename = os.path.join(temp_dir, "vml_deleted_test.jsonl")

            data_target = [100, 200]
            monitor = vml.logger("data_target", filename=filename)

            del data_target

            # Run one more traced line so VML can detect that the variable is gone.
            checkpoint = "after delete"
            self.assertEqual(checkpoint, "after delete")

            logs = finalize_and_read_logs(monitor, filename)

        deleted_logs = [entry for entry in logs if entry["event"] == DELETED_EVENT]

        self.assertEqual(logs[0]["event"], INIT_EVENT)
        self.assertGreaterEqual(len(deleted_logs), 1)
        self.assertIsNone(deleted_logs[-1]["data"])

if __name__ == "__main__":
    unittest.main(verbosity=2)