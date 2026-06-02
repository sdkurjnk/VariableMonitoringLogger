import json
import os
import tempfile
import unittest

import vml

GLOBAL_COLLISION_VALUE = "global-value"
INIT_EVENT = "init"
UPDATED_EVENT = "updated"

def read_jsonl(filename):
    # Read VML output as JSONL, where each line contains one log entry.
    with open(filename, "r", encoding="utf-8") as file:
        return [json.loads(line) for line in file]

def finalize_and_read_logs(monitor, filename):
    # Flush pending tracking events before reading the generated log file.
    monitor._finalSave()
    return read_jsonl(filename)

def get_latest_entries_by_name(logs):
    # Keep the last log entry for each variable name.
    latest_by_name = {}
    for entry in logs:
        latest_by_name[entry["name"]] = entry

    return latest_by_name

class TestVMLEdgeCases(unittest.TestCase):
    def test_no_duplicate_update_when_value_does_not_change(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            filename = os.path.join(temp_dir, "no_duplicate.jsonl")

            target = [1, 2, 3]
            monitor = vml.logger("target", filename=filename)

            # Run several traced lines without changing the tracked value.
            checkpoint_one = "line one"
            checkpoint_two = "line two"
            checkpoint_three = "line three"

            self.assertEqual(checkpoint_one, "line one")
            self.assertEqual(checkpoint_two, "line two")
            self.assertEqual(checkpoint_three, "line three")

            logs = finalize_and_read_logs(monitor, filename)

        events = [entry["event"] for entry in logs]

        self.assertEqual(events.count(INIT_EVENT), 1)
        self.assertEqual(events.count(UPDATED_EVENT), 0)
        self.assertEqual(logs[0]["data"], [1, 2, 3])

    def test_tracks_nested_mutable_object_change(self):
        initial_data = {"users": [{"name": "Alice", "score": 10}]}
        updated_data = {"users": [{"name": "Alice", "score": 20}]}

        with tempfile.TemporaryDirectory() as temp_dir:
            filename = os.path.join(temp_dir, "nested_mutable.jsonl")

            target = {"users": [{"name": "Alice", "score": 10}]}
            monitor = vml.logger("target", filename=filename)

            target["users"][0]["score"] = 20

            # Trigger another traced line so nested in-place mutation can be detected.
            checkpoint = "after nested mutation"
            self.assertEqual(checkpoint, "after nested mutation")

            logs = finalize_and_read_logs(monitor, filename)

        self.assertEqual(logs[0]["event"], INIT_EVENT)
        self.assertEqual(logs[0]["data"], initial_data)
        self.assertEqual(logs[-1]["event"], UPDATED_EVENT)
        self.assertEqual(logs[-1]["data"], updated_data)

    def test_local_variable_has_priority_over_global_name_collision(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            filename = os.path.join(temp_dir, "name_collision.jsonl")

            def run_local_scope():
                target_name_collision = "local-value"
                monitor = vml.logger("target_name_collision", filename=filename)

                target_name_collision = "local-updated"

                # Keep tracing inside the local scope to verify local name resolution.
                checkpoint = "after local update"
                self.assertEqual(checkpoint, "after local update")

                monitor._finalSave()

            run_local_scope()
            logs = read_jsonl(filename)

        self.assertEqual(GLOBAL_COLLISION_VALUE, "global-value")
        self.assertEqual(logs[0]["event"], INIT_EVENT)
        self.assertEqual(logs[0]["data"], "local-value")
        self.assertEqual(logs[-1]["event"], UPDATED_EVENT)
        self.assertEqual(logs[-1]["data"], "local-updated")

    def test_dispatcher_stop_prevents_further_tracking(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            filename = os.path.join(temp_dir, "stop_tracking.jsonl")

            target = [1]
            monitor = vml.logger("target", filename=filename)

            target.append(2)

            # Capture the first mutation before stopping the dispatcher.
            checkpoint = "before stop"
            self.assertEqual(checkpoint, "before stop")

            monitor.dispatcher.stop()

            target.append(3)

            # This line should not produce another update after tracing has stopped.
            checkpoint = "after stop"
            self.assertEqual(checkpoint, "after stop")

            logs = finalize_and_read_logs(monitor, filename)

        logged_data = [entry["data"] for entry in logs]

        self.assertEqual(logs[0]["event"], INIT_EVENT)
        self.assertIn([1, 2], logged_data)
        self.assertNotIn([1, 2, 3], logged_data)

    def test_unicode_data_is_written_without_corruption(self):
        initial_data = {"message": "안녕하세요", "status": "준비"}
        updated_data = {"message": "안녕하세요", "status": "완료"}

        with tempfile.TemporaryDirectory() as temp_dir:
            filename = os.path.join(temp_dir, "unicode.jsonl")

            target = {"message": "안녕하세요", "status": "준비"}
            monitor = vml.logger("target", filename=filename)

            target["status"] = "완료"

            # Verify UTF-8 JSONL output after a Unicode value changes.
            checkpoint = "after unicode update"
            self.assertEqual(checkpoint, "after unicode update")

            logs = finalize_and_read_logs(monitor, filename)

        self.assertEqual(logs[0]["data"], initial_data)
        self.assertEqual(logs[-1]["data"], updated_data)

    def test_tracks_common_scalar_and_tuple_reassignments(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            filename = os.path.join(temp_dir, "common_types.jsonl")

            flag = True
            number = 1.5
            values = (1, 2)

            monitor = vml.VML(filename)
            monitor.logger("flag")
            monitor.logger("number")
            monitor.logger("values")

            flag = False
            number = 2.5
            values = (1, 2, 3)

            # Run a traced line after all reassignments so each variable can update.
            checkpoint = "after scalar updates"
            self.assertEqual(checkpoint, "after scalar updates")

            logs = finalize_and_read_logs(monitor, filename)

        latest_by_name = get_latest_entries_by_name(logs)

        self.assertEqual(latest_by_name["flag"]["event"], UPDATED_EVENT)
        self.assertEqual(latest_by_name["flag"]["data"], False)

        self.assertEqual(latest_by_name["number"]["event"], UPDATED_EVENT)
        self.assertEqual(latest_by_name["number"]["data"], 2.5)

        self.assertEqual(latest_by_name["values"]["event"], UPDATED_EVENT)
        self.assertEqual(latest_by_name["values"]["data"], [1, 2, 3])

if __name__ == "__main__":
    unittest.main(verbosity=2)