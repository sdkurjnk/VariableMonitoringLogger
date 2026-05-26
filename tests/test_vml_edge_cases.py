import json
import os
import tempfile
import unittest

import vml


target_name_collision = "global-value"


def read_jsonl(filename):
    with open(filename, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f]


class TestVMLEdgeCases(unittest.TestCase):

    def test_no_duplicate_update_when_value_does_not_change(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            filename = os.path.join(temp_dir, "no_duplicate.jsonl")

            target = [1, 2, 3]
            monitor = vml.logger("target", filename=filename)

            checkpoint_one = "line one"
            checkpoint_two = "line two"
            checkpoint_three = "line three"

            self.assertEqual(checkpoint_one, "line one")
            self.assertEqual(checkpoint_two, "line two")
            self.assertEqual(checkpoint_three, "line three")

            monitor._finalSave()
            logs = read_jsonl(filename)

        events = [entry["event"] for entry in logs]

        self.assertEqual(events.count("init"), 1)
        self.assertEqual(events.count("updated"), 0)
        self.assertEqual(logs[0]["data"], [1, 2, 3])

    def test_tracks_nested_mutable_object_change(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            filename = os.path.join(temp_dir, "nested_mutable.jsonl")

            target = {
                "users": [
                    {"name": "Alice", "score": 10}
                ]
            }

            monitor = vml.logger("target", filename=filename)

            target["users"][0]["score"] = 20

            checkpoint = "after nested mutation"
            self.assertEqual(checkpoint, "after nested mutation")

            monitor._finalSave()
            logs = read_jsonl(filename)

        self.assertEqual(logs[0]["event"], "init")
        self.assertEqual(logs[0]["data"], {
            "users": [
                {"name": "Alice", "score": 10}
            ]
        })

        self.assertEqual(logs[-1]["event"], "updated")
        self.assertEqual(logs[-1]["data"], {
            "users": [
                {"name": "Alice", "score": 20}
            ]
        })

    def test_local_variable_has_priority_over_global_name_collision(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            filename = os.path.join(temp_dir, "name_collision.jsonl")

            def run_local_scope():
                target_name_collision = "local-value"

                monitor = vml.logger("target_name_collision", filename=filename)

                target_name_collision = "local-updated"

                checkpoint = "after local update"
                self.assertEqual(checkpoint, "after local update")

                monitor._finalSave()

            run_local_scope()
            logs = read_jsonl(filename)

        self.assertEqual(target_name_collision, "global-value")
        self.assertEqual(logs[0]["event"], "init")
        self.assertEqual(logs[0]["data"], "local-value")
        self.assertEqual(logs[-1]["event"], "updated")
        self.assertEqual(logs[-1]["data"], "local-updated")

    def test_dispatcher_stop_prevents_further_tracking(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            filename = os.path.join(temp_dir, "stop_tracking.jsonl")

            target = [1]
            monitor = vml.logger("target", filename=filename)

            target.append(2)

            checkpoint = "before stop"
            self.assertEqual(checkpoint, "before stop")

            monitor.dispatcher.stop()

            target.append(3)

            checkpoint = "after stop"
            self.assertEqual(checkpoint, "after stop")

            monitor._finalSave()
            logs = read_jsonl(filename)

        self.assertEqual(logs[0]["event"], "init")
        self.assertIn([1, 2], [entry["data"] for entry in logs])
        self.assertNotIn([1, 2, 3], [entry["data"] for entry in logs])

    def test_unicode_data_is_written_without_corruption(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            filename = os.path.join(temp_dir, "unicode.jsonl")

            target = {"message": "안녕하세요", "status": "준비"}
            monitor = vml.logger("target", filename=filename)

            target["status"] = "완료"

            checkpoint = "after unicode update"
            self.assertEqual(checkpoint, "after unicode update")

            monitor._finalSave()
            logs = read_jsonl(filename)

        self.assertEqual(logs[0]["data"], {"message": "안녕하세요", "status": "준비"})
        self.assertEqual(logs[-1]["data"], {"message": "안녕하세요", "status": "완료"})

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

            checkpoint = "after scalar updates"
            self.assertEqual(checkpoint, "after scalar updates")

            monitor._finalSave()
            logs = read_jsonl(filename)

        latest_by_name = {}
        for entry in logs:
            latest_by_name[entry["name"]] = entry

        self.assertEqual(latest_by_name["flag"]["event"], "updated")
        self.assertEqual(latest_by_name["flag"]["data"], False)

        self.assertEqual(latest_by_name["number"]["event"], "updated")
        self.assertEqual(latest_by_name["number"]["data"], 2.5)

        self.assertEqual(latest_by_name["values"]["event"], "updated")
        self.assertEqual(latest_by_name["values"]["data"], [1, 2, 3])


if __name__ == "__main__":
    unittest.main(verbosity=2)