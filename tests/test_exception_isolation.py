import json
import os
import tempfile
import unittest

from oscilo.Oscilo import Oscilo
from oscilo.FileWriter import FileWriter

INIT_EVENT = "init"
UPDATED_EVENT = "updated"


class RaisesOnCompare:
    # A tracked object whose __eq__/__ne__ raise, simulating any user type
    # with a broken or intentionally-explosive comparison implementation.
    def __init__(self, value):
        self.value = value

    def __eq__(self, other):
        raise RuntimeError("boom: __eq__ should never be trusted")

    __ne__ = __eq__


class PlainCustomObject:
    # A perfectly ordinary user-defined object: no custom __eq__, no custom
    # __deepcopy__, nothing exotic. copy.deepcopy() succeeds on it (so the
    # #51 deepcopy guard never engages), but json.dumps() cannot serialize it.
    def __init__(self, x):
        self.x = x


class RaisesOnRepr:
    def __repr__(self):
        raise RuntimeError("boom: repr should never be trusted either")


def read_jsonl(filename):
    with open(filename, "r", encoding="utf-8") as file:
        return [json.loads(line) for line in file]


def finalize_and_read_logs(monitor, filename):
    monitor.finalSave()
    return read_jsonl(filename)


class TestTracerExceptionIsolation(unittest.TestCase):
    # Issue #52 (A): a tracked value's comparison raising inside the native
    # engine must never propagate into the traced program.

    def test_eq_exception_does_not_propagate_to_user_code(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            filename = os.path.join(temp_dir, "eq_exception.jsonl")

            def run():
                obj = RaisesOnCompare(1)
                monitor = Oscilo(filename)
                monitor.register("obj")

                # In-place mutation with the reference unchanged forces the
                # native engine down the compare_mutable_value() path, which
                # invokes __eq__/__ne__ on RaisesOnCompare.
                obj.value = 2

                checkpoint = "reached after mutation"
                return checkpoint, monitor

            # The whole point of the fix: this call must not raise.
            checkpoint, monitor = run()

            self.assertEqual(checkpoint, "reached after mutation")

            logs = finalize_and_read_logs(monitor, filename)

        # The init event was still recorded; the record just never advances
        # past it because every subsequent compare keeps failing and getting
        # swallowed. No crash, no total data loss.
        self.assertEqual(logs[0]["event"], INIT_EVENT)

    def test_eq_exception_isolates_only_the_failing_tracker(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            filename = os.path.join(temp_dir, "eq_exception_isolation.jsonl")

            def run():
                broken = RaisesOnCompare(1)
                healthy = [1, 2]

                monitor = Oscilo(filename)
                monitor.register("broken")
                monitor.register("healthy")

                broken.value = 2
                healthy.append(3)

                checkpoint = "after both mutations"
                return checkpoint, monitor

            checkpoint, monitor = run()
            self.assertEqual(checkpoint, "after both mutations")

            logs = finalize_and_read_logs(monitor, filename)

        healthy_events = [entry["event"] for entry in logs if entry["name"] == "healthy"]
        healthy_last = [entry for entry in logs if entry["name"] == "healthy"][-1]

        # A broken tracker must not stop a healthy tracker sharing the same
        # frame/event from being checked and logged normally.
        self.assertIn(UPDATED_EVENT, healthy_events)
        self.assertEqual(healthy_last["data"], [1, 2, 3])


class TestFileWriterExceptionIsolation(unittest.TestCase):
    # Issue #52 (B): a single entry that can't be JSON-serialized must not
    # take the rest of the recorded history down with it.

    def test_unserializable_data_falls_back_to_repr(self):
        history = [
            {"name": "p", "data": PlainCustomObject(1), "event": "init"},
            {"name": "p", "data": PlainCustomObject(2), "event": "updated"},
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            filename = os.path.join(temp_dir, "repr_fallback.jsonl")

            FileWriter().write(filename, history)
            lines = read_jsonl(filename)

        self.assertEqual(len(lines), 2)
        # The rest of the entry (name/event/...) survives untouched...
        self.assertEqual(lines[0]["name"], "p")
        self.assertEqual(lines[0]["event"], "init")
        self.assertEqual(lines[1]["event"], "updated")
        # ...while the unserializable value is replaced by its repr() text
        # rather than crashing the write.
        self.assertIsInstance(lines[0]["data"], str)
        self.assertIn("PlainCustomObject", lines[0]["data"])

    def test_entry_is_skipped_only_when_repr_also_fails(self):
        history = [
            {"name": "before", "data": 1, "event": "init"},
            {"name": "unrepresentable", "data": RaisesOnRepr(), "event": "init"},
            {"name": "after", "data": 2, "event": "init"},
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            filename = os.path.join(temp_dir, "skip_unrepresentable.jsonl")

            FileWriter().write(filename, history)
            lines = read_jsonl(filename)

        names = [entry["name"] for entry in lines]

        # The one entry that can't even be repr()'d is dropped, but entries
        # before and after it in the same write are preserved -- this is the
        # regression #52 exists to prevent (today the whole file is 0 bytes).
        self.assertEqual(names, ["before", "after"])

    def test_single_bad_entry_no_longer_zeroes_out_the_whole_file(self):
        # End-to-end version of the issue's second repro case: a plain
        # custom object with no special __eq__/__repr__ at all.
        with tempfile.TemporaryDirectory() as temp_dir:
            filename = os.path.join(temp_dir, "no_total_loss.jsonl")

            def run():
                point = PlainCustomObject(1)
                monitor = Oscilo(filename)
                monitor.register("point")

                point.x = 2
                point.x = 3

                return monitor

            monitor = run()
            logs = finalize_and_read_logs(monitor, filename)

        self.assertGreaterEqual(len(logs), 1)
        events = [entry["event"] for entry in logs]
        self.assertIn(INIT_EVENT, events)


if __name__ == "__main__":
    unittest.main(verbosity=2)
