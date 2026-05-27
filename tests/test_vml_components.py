import json
import os
import sys
import tempfile
import unittest

import vml
from vml.FileWriter import FileWriter
from vml.HistoryBuffer import HistoryBuffer
from vml.ScopeResolver import ScopeResolver


TEST_GLOBAL_VALUE = "global-value"


class TestVMLComponents(unittest.TestCase):

    def test_history_buffer_returns_deepcopy(self):
        buffer = HistoryBuffer()
        original_data = {"numbers": [1, 2, 3]}

        buffer.append("target", original_data, "init", 0, 1)

        history = buffer.getHistory()
        history[0]["data"]["numbers"].append(4)

        stored_history = buffer.getHistory()

        self.assertEqual(stored_history[0]["name"], "target")
        self.assertEqual(stored_history[0]["event"], "init")
        self.assertEqual(stored_history[0]["data"], {"numbers": [1, 2, 3]})

    def test_history_buffer_clear(self):
        buffer = HistoryBuffer()

        buffer.append("A", 10, "init", 0, 1)
        buffer.append("A", 20, "updated", 0, 2)
        buffer.clearBuffer()

        self.assertEqual(buffer.getHistory(), [])

    def test_file_writer_writes_json_lines(self):
        history = [
            {"name": "A", "data": [1, 2, 3], "event": "init"},
            {"name": "A", "data": [1, 2, 3, 4], "event": "updated"},
            {"name": "A", "data": None, "event": "deleted"},
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            filename = os.path.join(temp_dir, "history.jsonl")

            writer = FileWriter()
            writer.write(filename, history)

            with open(filename, "r", encoding="utf-8") as f:
                lines = [json.loads(line) for line in f]

        self.assertEqual(lines, history)

    def test_scope_resolver_finds_local_variable_first(self):
        resolver = ScopeResolver()
        TEST_GLOBAL_VALUE = "local-value"

        frame = sys._getframe()
        domain, value = resolver.resolve(frame, "TEST_GLOBAL_VALUE")

        self.assertEqual(domain, 0)
        self.assertEqual(value, "local-value")

    def test_scope_resolver_finds_global_variable(self):
        resolver = ScopeResolver()

        frame = sys._getframe()
        domain, value = resolver.resolve(frame, "TEST_GLOBAL_VALUE")

        self.assertEqual(domain, 1)
        self.assertEqual(value, "global-value")

    def test_scope_resolver_returns_not_found(self):
        resolver = ScopeResolver()

        frame = sys._getframe()
        domain, value = resolver.resolve(frame, "THIS_VARIABLE_DOES_NOT_EXIST")

        self.assertEqual(domain, -1)
        self.assertIsNone(value)

    def test_vml_records_deleted_event(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            filename = os.path.join(temp_dir, "deleted_event.jsonl")

            target = [1, 2]
            monitor = vml.logger("target", filename=filename)

            target.append(3)
            del target

            # for checking after deletion
            marker = "after-delete"
            self.assertEqual(marker, "after-delete")

            monitor._finalSave()

            with open(filename, "r", encoding="utf-8") as f:
                logs = [json.loads(line) for line in f]

        events = [entry["event"] for entry in logs]

        self.assertIn("init", events)
        self.assertIn("updated", events)
        self.assertIn("deleted", events)

        deleted_logs = [entry for entry in logs if entry["event"] == "deleted"]
        self.assertEqual(deleted_logs[-1]["data"], None)

    def test_final_save_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            filename = os.path.join(temp_dir, "idempotent_save.jsonl")

            target = ["start"]
            monitor = vml.logger("target", filename=filename)

            target.append("changed")

            monitor._finalSave()

            with open(filename, "r", encoding="utf-8") as f:
                first_save = f.read()

            monitor._finalSave()

            with open(filename, "r", encoding="utf-8") as f:
                second_save = f.read()

        self.assertEqual(first_save, second_save)


if __name__ == "__main__":
    unittest.main(verbosity=2)