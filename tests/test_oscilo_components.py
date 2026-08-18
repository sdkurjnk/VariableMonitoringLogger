import json
import os
import sys
import tempfile
import unittest
from unittest.mock import Mock

from oscilo._core import _Oscilo
from oscilo.FileWriter import FileWriter
from oscilo.HistoryBuffer import HistoryBuffer
from oscilo.ScopeResolver import ScopeResolver

LOCAL = 0
GLOBAL = 1
NOT_FOUND = -1
TEST_GLOBAL_VALUE = "global-value"

def read_jsonl(filename):
    # Read VML output as JSONL, where each line is one log entry.
    with open(filename, "r", encoding="utf-8") as file:
        return [json.loads(line) for line in file]

def read_text(filename):
    # Read full file content when tests compare exact persisted output.
    with open(filename, "r", encoding="utf-8") as file:
        return file.read()

def finalize_and_read_logs(monitor, filename):
    # Force pending trace events to be written before assertions inspect logs.
    monitor.finalSave()
    return read_jsonl(filename)

class TestVMlogComponents(unittest.TestCase):
    def test_history_buffer_returns_deepcopy(self):
        buffer = HistoryBuffer()
        original_data = {"numbers": [1, 2, 3]}

        buffer.append("target", 1, original_data, "init", LOCAL, 1)

        history = buffer.getHistory()
        history[0]["data"]["numbers"].append(4)

        stored_history = buffer.getHistory()

        self.assertEqual(stored_history[0]["name"], "target")
        self.assertEqual(stored_history[0]["event"], "init")
        self.assertEqual(stored_history[0]["data"], {"numbers": [1, 2, 3]})
        self.assertEqual(stored_history[0]["var_id"], 1)

    def test_history_buffer_clear(self):
        buffer = HistoryBuffer()

        buffer.append("A", 1, 10, "init", LOCAL, 1)
        buffer.append("A", 1, 20, "updated", LOCAL, 2)

        history = buffer.getHistory()

        self.assertEqual(
            history,
            [
                {"name": "A", "var_id": 1, "data": 10, "event": "init", "domain": "LOCAL", "line": 1, "func": None, "call_id": None, "parent_call_id": None, "call_depth": None,},
                {"name": "A", "var_id": 1, "data": 20, "event": "updated", "domain": "LOCAL", "line": 2, "func": None, "call_id": None, "parent_call_id": None, "call_depth": None,},
            ],
        )

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
            lines = read_jsonl(filename)

        self.assertEqual(lines, history)

    def test_oscilo_register_delegates_resolution_to_dispatcher(self):
        monitor = object.__new__(_Oscilo)
        monitor.dispatcher = Mock()
        frame = sys._getframe()

        monitor.register("target", frame=frame)

        monitor.dispatcher.register.assert_called_once_with(
            "target",
            frame=frame,
        )

    def test_scope_resolver_finds_local_variable_first(self):
        resolver = ScopeResolver()
        TEST_GLOBAL_VALUE = "local-value"

        # Resolve against this exact frame so the local value shadows the global one.
        frame = sys._getframe()
        domain, value = resolver.resolve(frame, "TEST_GLOBAL_VALUE")

        self.assertEqual(domain, LOCAL)
        self.assertEqual(value, "local-value")

    def test_scope_resolver_finds_global_variable(self):
        resolver = ScopeResolver()

        # No local variable with this name exists here, so the resolver should use globals.
        frame = sys._getframe()
        domain, value = resolver.resolve(frame, "TEST_GLOBAL_VALUE")

        self.assertEqual(domain, GLOBAL)
        self.assertEqual(value, "global-value")

    def test_scope_resolver_returns_not_found(self):
        resolver = ScopeResolver()

        frame = sys._getframe()
        domain, value = resolver.resolve(frame, "THIS_VARIABLE_DOES_NOT_EXIST")

        self.assertEqual(domain, NOT_FOUND)
        self.assertIsNone(value)

    def test_oscilo_records_deleted_event(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            filename = os.path.join(temp_dir, "deleted_event.jsonl")

            target = [1, 2]
            monitor = _Oscilo(filename)
            monitor.register("target")

            target.append(3)
            del target

            # Run one more traced line after deletion so VML can record the missing variable.
            marker = "after-delete"
            self.assertEqual(marker, "after-delete")

            logs = finalize_and_read_logs(monitor, filename)

        events = [entry["event"] for entry in logs]
        deleted_logs = [entry for entry in logs if entry["event"] == "deleted"]

        self.assertIn("init", events)
        self.assertIn("updated", events)
        self.assertIn("deleted", events)
        self.assertIsNone(deleted_logs[-1]["data"])

    def test_final_save_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            filename = os.path.join(temp_dir, "idempotent_save.jsonl")

            target = ["start"]
            monitor = _Oscilo(filename)
            monitor.register("target")

            target.append("changed")

            # Saving twice should not rewrite or duplicate already flushed history.
            monitor.finalSave()
            first_save = read_text(filename)

            monitor.finalSave()
            second_save = read_text(filename)

        self.assertEqual(first_save, second_save)

if __name__ == "__main__":
    unittest.main(verbosity=2)