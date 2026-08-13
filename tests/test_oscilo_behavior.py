import json
import os
import tempfile
import unittest

from oscilo._core import _Oscilo

EXPECTED_LOG_KEYS = {"name", "var_id", "data", "event", "domain", "line", "func", "call_id", "parent_call_id", "call_depth", }
TRACKING_EVENTS = {"init", "updated", "deleted"}
TRACKING_DOMAINS = {"LOCAL", "GLOBAL"}

def read_jsonl(filename):
    # Read VML output as JSONL, where each line is one log entry.
    with open(filename, "r", encoding="utf-8") as file:
        return [json.loads(line) for line in file]

def finalize_and_read_logs(monitor, filename):
    # Force VML to flush tracked events before assertions inspect the log file.
    monitor._finalSave()
    return read_jsonl(filename)

class TestVMLBehavior(unittest.TestCase):
    def test_tracks_list_append_without_manual_logging(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            filename = os.path.join(temp_dir, "list_append.jsonl")

            target = [1, 2]
            monitor = _Oscilo(filename)
            monitor.register("target")

            target.append(3)

            # Trigger another traced line so VML can observe the in-place mutation.
            checkpoint = "after append"
            self.assertEqual(checkpoint, "after append")

            logs = finalize_and_read_logs(monitor, filename)

        self.assertEqual(logs[0]["event"], "init")
        self.assertEqual(logs[0]["data"], [1, 2])
        self.assertIn("updated", [entry["event"] for entry in logs])
        self.assertEqual(logs[-1]["data"], [1, 2, 3])

    def test_tracks_dict_value_mutation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            filename = os.path.join(temp_dir, "dict_mutation.jsonl")

            target = {"count": 1, "items": ["A"]}
            monitor = _Oscilo(filename)
            monitor.register("target")

            target["count"] = 2
            target["items"].append("B")

            # Keep execution in the same test frame so line tracing can run.
            checkpoint = "after dict mutation"
            self.assertEqual(checkpoint, "after dict mutation")

            logs = finalize_and_read_logs(monitor, filename)

        updated_logs = [entry for entry in logs if entry["event"] == "updated"]

        self.assertGreaterEqual(len(updated_logs), 1)
        self.assertEqual(logs[-1]["data"], {"count": 2, "items": ["A", "B"]})

    def test_tracks_immutable_reassignment(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            filename = os.path.join(temp_dir, "immutable_reassignment.jsonl")

            target = "before"
            monitor = _Oscilo(filename)
            monitor.register("target")

            target = "after"

            # Reassignment is detected on a later traced line in this frame.
            checkpoint = "after reassignment"
            self.assertEqual(checkpoint, "after reassignment")

            logs = finalize_and_read_logs(monitor, filename)

        self.assertEqual(logs[0]["event"], "init")
        self.assertEqual(logs[0]["data"], "before")
        self.assertEqual(logs[-1]["event"], "updated")
        self.assertEqual(logs[-1]["data"], "after")

    def test_tracks_deleted_variable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            filename = os.path.join(temp_dir, "deleted_variable.jsonl")

            target = [10, 20]
            monitor = _Oscilo(filename)
            monitor.register("target")

            del target

            # The extra line gives the trace dispatcher a chance to record deletion.
            checkpoint = "after delete"
            self.assertEqual(checkpoint, "after delete")

            logs = finalize_and_read_logs(monitor, filename)

        deleted_logs = [entry for entry in logs if entry["event"] == "deleted"]

        self.assertEqual(logs[0]["event"], "init")
        self.assertGreaterEqual(len(deleted_logs), 1)
        self.assertIsNone(deleted_logs[-1]["data"])

    def test_tracks_multiple_variables_with_one_monitor(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            filename = os.path.join(temp_dir, "multiple_variables.jsonl")

            first = [1]
            second = "alpha"

            monitor = _Oscilo(filename)
            monitor.register("first")
            monitor.register("second")

            first.append(2)
            second = "beta"

            # Both variables should be checked during the same traced frame.
            checkpoint = "after multiple updates"
            self.assertEqual(checkpoint, "after multiple updates")

            logs = finalize_and_read_logs(monitor, filename)

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

    def test_func_field_identifies_function_scope_for_same_variable_name(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            filename = os.path.join(temp_dir, "func_scope.jsonl")
            monitor = _Oscilo(filename)
            def foo():
                target = "foo-before"
                monitor.register("target")

                target = "foo-after"

                # Keep tracing inside foo so the local update can be recorded.
                checkpoint = "after foo update"
                self.assertEqual(checkpoint, "after foo update")

            def bar():
                target = "bar-before"
                monitor.register("target")

                target = "bar-after"

                # Keep tracing inside bar so the local update can be recorded.
                checkpoint = "after bar update"
                self.assertEqual(checkpoint, "after bar update")

            foo()
            bar()

            logs = finalize_and_read_logs(monitor, filename)

        foo_logs = [entry for entry in logs if entry["func"] == "foo"]
        bar_logs = [entry for entry in logs if entry["func"] == "bar"]

        self.assertGreaterEqual(len(foo_logs), 2)
        self.assertGreaterEqual(len(bar_logs), 2)

        self.assertEqual({entry["name"] for entry in foo_logs}, {"target"})
        self.assertEqual({entry["name"] for entry in bar_logs}, {"target"})

        self.assertEqual(foo_logs[0]["event"], "init")
        self.assertEqual(foo_logs[0]["data"], "foo-before")
        self.assertEqual(foo_logs[-1]["event"], "updated")
        self.assertEqual(foo_logs[-1]["data"], "foo-after")

        self.assertEqual(bar_logs[0]["event"], "init")
        self.assertEqual(bar_logs[0]["data"], "bar-before")
        self.assertEqual(bar_logs[-1]["event"], "updated")
        self.assertEqual(bar_logs[-1]["data"], "bar-after")
    
    def test_log_entries_use_jsonl_schema(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            filename = os.path.join(temp_dir, "schema.jsonl")

            target = {"status": "ready"}
            monitor = _Oscilo(filename)
            monitor.register("target")

            target["status"] = "done"

            # Capture at least one update before validating the persisted schema.
            checkpoint = "after schema update"
            self.assertEqual(checkpoint, "after schema update")

            logs = finalize_and_read_logs(monitor, filename)

        self.assertGreaterEqual(len(logs), 2)

        for entry in logs:
            self.assertEqual(set(entry.keys()), EXPECTED_LOG_KEYS)
            self.assertEqual(entry["name"], "target")
            self.assertIn(entry["event"], TRACKING_EVENTS)
            self.assertIn(entry["domain"], TRACKING_DOMAINS)
            self.assertTrue(entry["line"] is None or isinstance(entry["line"], int))
            self.assertTrue(entry["func"] is None or isinstance(entry["func"], str))
            self.assertIsInstance(entry["var_id"], int)
            self.assertTrue(entry["call_id"] is None or isinstance(entry["call_id"], int))
            self.assertTrue(entry["parent_call_id"] is None or isinstance(entry["parent_call_id"], int))
            self.assertTrue(entry["call_depth"] is None or isinstance(entry["call_depth"], int))

    def test_call_context_identifies_recursive_function_calls(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            filename = os.path.join(temp_dir, "recursive_context.jsonl")
            monitor = _Oscilo(filename)

            def factorial(n):
                monitor.register("n")

                if n <= 1:
                    return 1

                return n * factorial(n - 1)

            self.assertEqual(factorial(3), 6)

            logs = finalize_and_read_logs(monitor, filename)

        init_logs = [
            entry
            for entry in logs
            if entry["name"] == "n" and entry["event"] == "init"
        ]

        self.assertEqual([entry["data"] for entry in init_logs], [3, 2, 1])
        self.assertEqual([entry["func"] for entry in init_logs], ["factorial", "factorial", "factorial"])
        self.assertEqual([entry["call_depth"] for entry in init_logs], [1, 2, 3])

        call_ids = [entry["call_id"] for entry in init_logs]
        var_ids = [entry["var_id"] for entry in init_logs]
        parent_call_ids = [entry["parent_call_id"] for entry in init_logs]

        self.assertEqual(len(set(call_ids)), 3)
        self.assertEqual(len(set(var_ids)), 3)
        self.assertEqual(var_ids, call_ids)

        self.assertIsNone(parent_call_ids[0])
        self.assertEqual(parent_call_ids[1], call_ids[0])
        self.assertEqual(parent_call_ids[2], call_ids[1])

    def test_call_context_distinguishes_sibling_recursive_calls(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            filename = os.path.join(temp_dir, "sibling_recursive_context.jsonl")
            monitor = _Oscilo(filename)

            def fib(n):
                monitor.register("n")

                if n <= 1:
                    return n

                return fib(n - 1) + fib(n - 2)

            self.assertEqual(fib(3), 2)

            logs = finalize_and_read_logs(monitor, filename)

        init_logs = [
            entry
            for entry in logs
            if entry["name"] == "n" and entry["event"] == "init"
        ]

        self.assertEqual([entry["data"] for entry in init_logs], [3, 2, 1, 0, 1])

        call_ids = [entry["call_id"] for entry in init_logs]
        parent_call_ids = [entry["parent_call_id"] for entry in init_logs]

        self.assertEqual(len(call_ids), 5)
        self.assertEqual(len(set(call_ids)), 5)

        root_call_id = call_ids[0]
        left_child_call_id = call_ids[1]
        right_child_call_id = call_ids[4]

        self.assertIsNone(parent_call_ids[0])
        self.assertEqual(parent_call_ids[1], root_call_id)
        self.assertEqual(parent_call_ids[2], left_child_call_id)
        self.assertEqual(parent_call_ids[3], left_child_call_id)
        self.assertEqual(parent_call_ids[4], root_call_id)

        self.assertNotEqual(left_child_call_id, right_child_call_id)
        self.assertEqual([entry["call_depth"] for entry in init_logs], [1, 2, 3, 3, 2])

    def test_generator_resume_keeps_single_call_context(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            filename = os.path.join(
                temp_dir,
                "generator_context.jsonl",
            )
            monitor = _Oscilo(filename)

            def generate():
                n = 0
                monitor.register("n")
                yield n

                n = 1
                yield n

                n = 2
                yield n

            generator = generate()

            self.assertEqual(next(generator), 0)

            def resume_a():
                return next(generator)

            def resume_b():
                return next(generator)

            self.assertEqual(resume_a(), 1)
            self.assertEqual(resume_b(), 2)

            logs = finalize_and_read_logs(monitor, filename)

        generator_logs = [
            entry
            for entry in logs
            if entry["name"] == "n"
        ]

        self.assertEqual(
            [
                (entry["event"], entry["data"])
                for entry in generator_logs
            ],
            [
                ("init", 0),
                ("updated", 1),
                ("updated", 2),
            ],
        )

        first_context = generator_logs[0]

        self.assertTrue(
            all(
                entry["call_id"] == first_context["call_id"]
                for entry in generator_logs
            )
        )
        self.assertTrue(
            all(
                entry["parent_call_id"]
                == first_context["parent_call_id"]
                for entry in generator_logs
            )
        )

        self.assertTrue(
            all(
                entry["call_depth"] == first_context["call_depth"]
                for entry in generator_logs
            )
        )

if __name__ == "__main__":
    unittest.main(verbosity=2)
