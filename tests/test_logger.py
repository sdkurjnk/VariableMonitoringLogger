import json
import os
import tempfile
import unittest

import vml


def read_jsonl(filename):
    with open(filename, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f]


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

            checkpoint = "after append"
            self.assertEqual(checkpoint, "after append")

            monitor._finalSave()
            logs = read_jsonl(filename)

        self.assertEqual(logs[0]["event"], "init")
        self.assertEqual(logs[0]["data"], [100, 200])

        self.assertEqual(logs[-1]["event"], "updated")
        self.assertEqual(logs[-1]["data"], [100, 200, 300])

    def test_logger_writes_deleted_event(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            filename = os.path.join(temp_dir, "vml_deleted_test.jsonl")

            data_target = [100, 200]
            monitor = vml.logger("data_target", filename=filename)

            del data_target

            checkpoint = "after delete"
            self.assertEqual(checkpoint, "after delete")

            monitor._finalSave()
            logs = read_jsonl(filename)

        self.assertEqual(logs[0]["event"], "init")

        deleted_logs = [entry for entry in logs if entry["event"] == "deleted"]
        self.assertGreaterEqual(len(deleted_logs), 1)
        self.assertIsNone(deleted_logs[-1]["data"])


if __name__ == "__main__":
    unittest.main(verbosity=2)