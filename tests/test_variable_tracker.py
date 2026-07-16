import sys
import unittest

from oscilo.VariableTracker import (
    DELETED_EVENT,
    ENCLOSING,
    GLOBAL,
    INIT_EVENT,
    LOCAL,
    NO_CHANGE_EVENT,
    NOT_FOUND,
    NOT_FOUND_EVENT,
    UPDATED_EVENT,
    VariableTracker,
)


FRAME_STATE_GLOBAL_VALUE = ["before"]

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

    def test_frame_state_check_initializes_local_value(self):
        target = [1, 2]
        frame = sys._getframe()

        event_name, state = self.tracker.check(
            frame,
            LOCAL,
            "target",
            None,
        )

        self.assertEqual(event_name, INIT_EVENT)
        self.assertIs(state["ref"], target)
        self.assertEqual(state["copy"], [1, 2])

    def test_frame_state_check_returns_same_state_without_change(self):
        target = (1, 2)
        frame = sys._getframe()

        _, state = self.tracker.check(
            frame,
            LOCAL,
            "target",
            None,
        )
        event_name, new_state = self.tracker.check(
            frame,
            LOCAL,
            "target",
            state,
        )

        self.assertEqual(event_name, NO_CHANGE_EVENT)
        self.assertIs(new_state, state)

    def test_frame_state_check_detects_mutable_value_change(self):
        target = [1]
        frame = sys._getframe()

        _, state = self.tracker.check(
            frame,
            LOCAL,
            "target",
            None,
        )

        target.append(2)

        event_name, new_state = self.tracker.check(
            frame,
            LOCAL,
            "target",
            state,
        )

        self.assertEqual(event_name, UPDATED_EVENT)
        self.assertIs(new_state["ref"], target)
        self.assertEqual(new_state["copy"], [1, 2])
        self.assertEqual(state["copy"], [1])

    def test_frame_state_check_detects_immutable_reassignment(self):
        target = "before"
        frame = sys._getframe()

        _, state = self.tracker.check(
            frame,
            LOCAL,
            "target",
            None,
        )

        target = "".join(["af", "ter"])

        event_name, new_state = self.tracker.check(
            frame,
            LOCAL,
            "target",
            state,
        )

        self.assertEqual(event_name, UPDATED_EVENT)
        self.assertEqual(new_state["ref"], "after")
        self.assertIsNone(new_state["copy"])

    def test_frame_state_check_returns_deleted_for_previous_state(self):
        target = [1]
        frame = sys._getframe()

        _, state = self.tracker.check(
            frame,
            LOCAL,
            "target",
            None,
        )

        del target

        event_name, new_state = self.tracker.check(
            frame,
            NOT_FOUND,
            "target",
            state,
        )

        self.assertEqual(event_name, DELETED_EVENT)
        self.assertIsNone(new_state)

    def test_frame_state_check_returns_not_found_without_previous_state(self):
        frame = sys._getframe()

        event_name, new_state = self.tracker.check(
            frame,
            NOT_FOUND,
            "missing_target",
            None,
        )

        self.assertEqual(event_name, NOT_FOUND_EVENT)
        self.assertIsNone(new_state)

    def test_frame_state_check_does_not_mutate_instance_value_state(self):
        target = [1]
        frame = sys._getframe()

        self.tracker.check(
            frame,
            LOCAL,
            "target",
            None,
        )

        self.assertIsNone(self.tracker._lastRef)
        self.assertIsNone(self.tracker._lastCopy)
        self.assertIsNone(self.tracker._lastSnapshot)
        self.assertFalse(self.tracker._isActive)

    def test_frame_state_check_tracks_global_with_external_state(self):
        global FRAME_STATE_GLOBAL_VALUE

        original_value = FRAME_STATE_GLOBAL_VALUE

        try:
            FRAME_STATE_GLOBAL_VALUE = ["before"]
            frame = sys._getframe()

            event_name, state = self.tracker.check(
                frame,
                GLOBAL,
                "FRAME_STATE_GLOBAL_VALUE",
                None,
            )

            self.assertEqual(event_name, INIT_EVENT)
            self.assertEqual(state["copy"], ["before"])

            FRAME_STATE_GLOBAL_VALUE.append("after")

            event_name, new_state = self.tracker.check(
                frame,
                GLOBAL,
                "FRAME_STATE_GLOBAL_VALUE",
                state,
            )

            self.assertEqual(event_name, UPDATED_EVENT)
            self.assertEqual(new_state["copy"], ["before", "after"])
            self.assertIsNone(self.tracker._lastRef)
            self.assertIsNone(self.tracker._lastCopy)
        finally:
            FRAME_STATE_GLOBAL_VALUE = original_value

    def test_frame_state_check_tracks_enclosing_value(self):
        target = ["before"]

        def check_target(prev_state):
            # Referencing target makes it a free variable in this frame.
            target
            return self.tracker.check(
                sys._getframe(),
                ENCLOSING,
                "target",
                prev_state,
            )

        event_name, state = check_target(None)

        self.assertEqual(event_name, INIT_EVENT)
        self.assertEqual(state["copy"], ["before"])

        target.append("after")

        event_name, new_state = check_target(state)

        self.assertEqual(event_name, UPDATED_EVENT)
        self.assertEqual(new_state["copy"], ["before", "after"])


if __name__ == "__main__":
    unittest.main(verbosity=2)