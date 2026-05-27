import json
import os
import tempfile
import unittest

import vml


def read_jsonl(filename):
    with open(filename, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f]


class TestVMLBehavior(unittest.TestCase):

    def test_tracks_list_append_without_manual_logging(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            filename = os.path.join(temp_dir, "list_append.jsonl")

            target = [1, 2]
            monitor = vml.logger("target", filename=filename)

            target.append(3)

            # line tracing shold capture this change
            checkpoint = "after append"
            self.assertEqual(checkpoint, "after append")

            monitor._finalSave()
            logs = read_jsonl(filename)

        self.assertEqual(logs[0]["event"], "init")
        self.assertEqual(logs[0]["data"], [1, 2])

        self.assertIn("updated", [entry["event"] for entry in logs])
        self.assertEqual(logs[-1]["data"], [1, 2, 3])

    def test_tracks_dict_value_mutation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            filename = os.path.join(temp_dir, "dict_mutation.jsonl")

            target = {"count": 1, "items": ["A"]}
            monitor = vml.logger("target", filename=filename)

            target["count"] = 2
            target["items"].append("B")

            checkpoint = "after dict mutation"
            self.assertEqual(checkpoint, "after dict mutation")

            monitor._finalSave()
            logs = read_jsonl(filename)

        updated_logs = [entry for entry in logs if entry["event"] == "updated"]

        self.assertGreaterEqual(len(updated_logs), 1)
        self.assertEqual(logs[-1]["data"], {"count": 2, "items": ["A", "B"]})

    def test_tracks_immutable_reassignment(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            filename = os.path.join(temp_dir, "immutable_reassignment.jsonl")

            target = "before"
            monitor = vml.logger("target", filename=filename)

            target = "after"

            checkpoint = "after reassignment"
            self.assertEqual(checkpoint, "after reassignment")

            monitor._finalSave()
            logs = read_jsonl(filename)

        self.assertEqual(logs[0]["event"], "init")
        self.assertEqual(logs[0]["data"], "before")

        self.assertEqual(logs[-1]["event"], "updated")
        self.assertEqual(logs[-1]["data"], "after")

    def test_tracks_deleted_variable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            filename = os.path.join(temp_dir, "deleted_variable.jsonl")

            target = [10, 20]
            monitor = vml.logger("target", filename=filename)

            del target

            checkpoint = "after delete"
            self.assertEqual(checkpoint, "after delete")

            monitor._finalSave()
            logs = read_jsonl(filename)

        self.assertEqual(logs[0]["event"], "init")

        deleted_logs = [entry for entry in logs if entry["event"] == "deleted"]
        self.assertGreaterEqual(len(deleted_logs), 1)
        self.assertIsNone(deleted_logs[-1]["data"])

    def test_tracks_multiple_variables_with_one_monitor(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            filename = os.path.join(temp_dir, "multiple_variables.jsonl")

            first = [1]
            second = "alpha"

            monitor = vml.VML(filename)
            monitor.logger("first")
            monitor.logger("second")

            first.append(2)
            second = "beta"

            checkpoint = "after multiple updates"
            self.assertEqual(checkpoint, "after multiple updates")

            monitor._finalSave()
            logs = read_jsonl(filename)

        first_logs = [entry for entry in logs if entry["name"] == "first"]
        second_logs = [entry for entry in logs if entry["name"] == "second"]

        self.assertGreaterEqual(len(first_logs), 2)
        self.assertGreaterEqual(len(second_logs), 2)

        self.assertEqual(first_logs[0]["event"], "init")
        self.assertEqual(first_logs[-1]["event"], "updated")
        self.assertEqual(first_logs[-1]["data"], [1, 2])

        self.assertEqual(second_logs[0]["event"], "init")
        self.assertEqual(second_logs[-1]["event"], "updated")
        self.assertEqual(second_logs[-1]["data"], "beta")

    def test_log_entries_use_jsonl_schema(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            filename = os.path.join(temp_dir, "schema.jsonl")

            target = {"status": "ready"}
            monitor = vml.logger("target", filename=filename)

            target["status"] = "done"

            checkpoint = "after schema update"
            self.assertEqual(checkpoint, "after schema update")

            monitor._finalSave()
            logs = read_jsonl(filename)

        self.assertGreaterEqual(len(logs), 2)

        for entry in logs:
            self.assertEqual(set(entry.keys()), {"name", "data", "event", "domain", "line"})
            self.assertEqual(entry["name"], "target")
            self.assertIn(entry["event"], {"init", "updated", "deleted"})
            self.assertIn(entry["domain"], {"LOCAL", "GLOBAL"})
            self.assertTrue(entry["line"] is None or isinstance(entry["line"], int))


if __name__ == "__main__":
    unittest.main(verbosity=2)