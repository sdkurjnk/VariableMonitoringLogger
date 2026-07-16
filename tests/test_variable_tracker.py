import unittest

from oscilo.VariableTracker import VariableTracker


class MutableValue:
    def __init__(self, value):
        self.value = value


class TestVariableTrackerState(unittest.TestCase):
    def setUp(self):
        self.tracker = VariableTracker("target")

    def test_atomic_value_state_keeps_reference_without_copy(self):
        value = "ready"

        state = self.tracker._make_state(value)

        self.assertIs(state["ref"], value)
        self.assertIsNone(state["copy"])

    def test_none_state_keeps_reference_without_copy(self):
        state = self.tracker._make_state(None)

        self.assertIsNone(state["ref"])
        self.assertIsNone(state["copy"])

    def test_immutable_container_keeps_reference_without_copy(self):
        value = (1, 2, 3)

        state = self.tracker._make_state(value)

        self.assertIs(state["ref"], value)
        self.assertIsNone(state["copy"])

    def test_mutable_list_state_uses_deepcopy(self):
        value = [1, 2]

        state = self.tracker._make_state(value)

        self.assertIs(state["ref"], value)
        self.assertEqual(state["copy"], [1, 2])
        self.assertIsNot(state["copy"], value)

        value.append(3)

        self.assertEqual(state["ref"], [1, 2, 3])
        self.assertEqual(state["copy"], [1, 2])

    def test_nested_mutable_value_uses_deepcopy(self):
        value = {
            "users": [
                {
                    "name": "Alice",
                    "scores": [10],
                }
            ]
        }

        state = self.tracker._make_state(value)

        value["users"][0]["scores"].append(20)

        self.assertEqual(
            state["copy"],
            {
                "users": [
                    {
                        "name": "Alice",
                        "scores": [10],
                    }
                ]
            },
        )

    def test_custom_mutable_object_uses_deepcopy(self):
        value = MutableValue(["before"])

        state = self.tracker._make_state(value)

        value.value.append("after")

        self.assertIs(state["ref"], value)
        self.assertIsNot(state["copy"], value)
        self.assertEqual(state["copy"].value, ["before"])

    def test_get_snapshot_returns_reference_for_immutable_state(self):
        value = (1, 2)
        state = self.tracker._make_state(value)

        snapshot = self.tracker.get_snapshot(state)

        self.assertIs(snapshot, value)

    def test_get_snapshot_returns_independent_mutable_copy(self):
        state = self.tracker._make_state(
            {
                "numbers": [1, 2],
            }
        )

        snapshot = self.tracker.get_snapshot(state)
        snapshot["numbers"].append(3)

        self.assertEqual(
            state["copy"],
            {
                "numbers": [1, 2],
            },
        )
        self.assertEqual(
            self.tracker.get_snapshot(state),
            {
                "numbers": [1, 2],
            },
        )

    def test_get_snapshot_returns_none_without_state(self):
        self.assertIsNone(self.tracker.get_snapshot(None))

    def test_get_snapshot_keeps_legacy_no_argument_behavior(self):
        tracker = VariableTracker(
            "target",
            value=[1, 2],
            exists=True,
        )

        snapshot = tracker.get_snapshot()
        snapshot.append(3)

        self.assertEqual(tracker.get_snapshot(), [1, 2])


if __name__ == "__main__":
    unittest.main(verbosity=2)