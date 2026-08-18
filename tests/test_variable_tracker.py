import json
import sys
import threading
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


class UnrepresentableValue:
    # Fails deepcopy and repr so both fallback paths can be exercised.
    def __deepcopy__(self, memo):
        raise TypeError("cannot deepcopy UnrepresentableValue")

    def __repr__(self):
        raise RuntimeError("cannot repr UnrepresentableValue")


class CopyReturnsUncopyable:
    # Deepcopy succeeds but hands back an object that cannot itself be copied.
    def __deepcopy__(self, memo):
        return threading.Lock()


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

    def test_tuple_with_mutable_member_uses_deepcopy(self):
        value = ([1, 2], 3)

        state = self.tracker._make_state(value)

        self.assertIs(state["ref"], value)
        self.assertEqual(state["copy"], ([1, 2], 3))
        self.assertIsNot(state["copy"], value)
        self.assertIsNot(state["copy"][0], value[0])

        value[0].append(4)

        self.assertEqual(state["ref"], ([1, 2, 4], 3))
        self.assertEqual(state["copy"], ([1, 2], 3))

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

    def test_get_snapshot_returns_reference_for_atomic_state(self):
        value = "ready"
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

    def test_frame_state_check_initializes_local_value(self):
        target = [1, 2]
        frame = sys._getframe()

        event_name, state = self.tracker.evaluate(
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

        _, state = self.tracker.evaluate(
            frame,
            LOCAL,
            "target",
            None,
        )
        event_name, new_state = self.tracker.evaluate(
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

        _, state = self.tracker.evaluate(
            frame,
            LOCAL,
            "target",
            None,
        )

        target.append(2)

        event_name, new_state = self.tracker.evaluate(
            frame,
            LOCAL,
            "target",
            state,
        )

        self.assertEqual(event_name, UPDATED_EVENT)
        self.assertIs(new_state["ref"], target)
        self.assertEqual(new_state["copy"], [1, 2])
        self.assertEqual(state["copy"], [1])

    def test_frame_state_check_detects_nested_tuple_mutation(self):
        target = ([1, 2], 3)
        frame = sys._getframe()

        _, state = self.tracker.evaluate(
            frame,
            LOCAL,
            "target",
            None,
        )

        target[0].append(4)

        event_name, new_state = self.tracker.evaluate(
            frame,
            LOCAL,
            "target",
            state,
        )

        self.assertEqual(event_name, UPDATED_EVENT)
        self.assertIs(new_state["ref"], target)
        self.assertEqual(new_state["copy"], ([1, 2, 4], 3))
        self.assertEqual(state["copy"], ([1, 2], 3))

    def test_frame_state_check_detects_immutable_reassignment(self):
        target = "before"
        frame = sys._getframe()

        _, state = self.tracker.evaluate(
            frame,
            LOCAL,
            "target",
            None,
        )

        target = "".join(["af", "ter"])

        event_name, new_state = self.tracker.evaluate(
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

        _, state = self.tracker.evaluate(
            frame,
            LOCAL,
            "target",
            None,
        )

        del target

        event_name, new_state = self.tracker.evaluate(
            frame,
            NOT_FOUND,
            "target",
            state,
        )

        self.assertEqual(event_name, DELETED_EVENT)
        self.assertIsNone(new_state)

    def test_frame_state_check_returns_not_found_without_previous_state(self):
        frame = sys._getframe()

        event_name, new_state = self.tracker.evaluate(
            frame,
            NOT_FOUND,
            "missing_target",
            None,
        )

        self.assertEqual(event_name, NOT_FOUND_EVENT)
        self.assertIsNone(new_state)

    def test_tracker_instance_owns_identity_metadata_and_state(self):
        self.assertEqual(
            vars(self.tracker),
            {
                "varName": "target",
                "domain": None,
                "_states": {},
            },
        )

    def test_frame_state_check_tracks_global_with_external_state(self):
        global FRAME_STATE_GLOBAL_VALUE

        original_value = FRAME_STATE_GLOBAL_VALUE

        try:
            FRAME_STATE_GLOBAL_VALUE = ["before"]
            frame = sys._getframe()

            event_name, state = self.tracker.evaluate(
                frame,
                GLOBAL,
                "FRAME_STATE_GLOBAL_VALUE",
                None,
            )

            self.assertEqual(event_name, INIT_EVENT)
            self.assertEqual(state["copy"], ["before"])

            FRAME_STATE_GLOBAL_VALUE.append("after")

            event_name, new_state = self.tracker.evaluate(
                frame,
                GLOBAL,
                "FRAME_STATE_GLOBAL_VALUE",
                state,
            )

            self.assertEqual(event_name, UPDATED_EVENT)
            self.assertEqual(new_state["copy"], ["before", "after"])
        finally:
            FRAME_STATE_GLOBAL_VALUE = original_value

    def test_frame_state_check_tracks_enclosing_value(self):
        target = ["before"]

        def check_target(prev_state):
            # Referencing target makes it a free variable in this frame.
            target
            return self.tracker.evaluate(
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

    def test_deleted_variable_can_initialize_again(self):
        target = ["first"]
        frame = sys._getframe()

        event_name, state = self.tracker.evaluate(
            frame,
            LOCAL,
            "target",
            None,
        )

        self.assertEqual(event_name, INIT_EVENT)
        self.assertEqual(state["copy"], ["first"])

        del target

        event_name, state = self.tracker.evaluate(
            frame,
            NOT_FOUND,
            "target",
            state,
        )

        self.assertEqual(event_name, DELETED_EVENT)
        self.assertIsNone(state)

        target = ["second"]

        event_name, state = self.tracker.evaluate(
            frame,
            LOCAL,
            "target",
            state,
        )

        self.assertEqual(event_name, INIT_EVENT)
        self.assertEqual(state["copy"], ["second"])

    def test_make_state_flags_copy_failure_for_unpicklable_value(self):
        value = threading.Lock()

        state = self.tracker._make_state(value)

        self.assertIs(state["ref"], value)
        self.assertIsNone(state["copy"])
        self.assertTrue(state["copy_failed"])

    def test_make_state_detects_copy_failure_inside_nested_container(self):
        value = {"a": [threading.Lock()]}

        state = self.tracker._make_state(value)

        self.assertIs(state["ref"], value)
        self.assertIsNone(state["copy"])
        self.assertTrue(state["copy_failed"])

    def test_make_state_success_and_atomic_paths_set_copy_failed_false(self):
        atomic_state = self.tracker._make_state("ready")
        mutable_state = self.tracker._make_state([1, 2])

        self.assertFalse(atomic_state["copy_failed"])
        self.assertFalse(mutable_state["copy_failed"])

    def test_get_snapshot_returns_stable_placeholder_for_copy_failure(self):
        value = threading.Lock()
        state = self.tracker._make_state(value)

        snapshot = self.tracker.get_snapshot(state)

        self.assertEqual(snapshot, "<uncopyable>")
        json.dumps(snapshot)

    def test_get_snapshot_does_not_call_repr_for_copy_failure(self):
        state = self.tracker._make_state(UnrepresentableValue())

        snapshot = self.tracker.get_snapshot(state)

        self.assertEqual(snapshot, "<uncopyable>")
        json.dumps(snapshot)

    def test_check_demotes_copy_failure_state_to_identity_only_comparison(self):
        target = threading.Lock()
        frame = sys._getframe()

        event_name, state = self.tracker.evaluate(
            frame,
            LOCAL,
            "target",
            None,
        )

        self.assertEqual(event_name, INIT_EVENT)
        self.assertTrue(state["copy_failed"])

        # Same lock object kept across checks must settle on NO_CHANGE_EVENT
        # instead of re-attempting deepcopy and spamming UPDATED_EVENT.
        for _ in range(3):
            event_name, state = self.tracker.evaluate(
                frame,
                LOCAL,
                "target",
                state,
            )
            self.assertEqual(event_name, NO_CHANGE_EVENT)

    def test_check_transitions_from_copy_failure_state_on_reassignment(self):
        target = threading.Lock()
        frame = sys._getframe()

        event_name, state = self.tracker.evaluate(
            frame,
            LOCAL,
            "target",
            None,
        )
        self.assertEqual(event_name, INIT_EVENT)

        target = 42

        event_name, state = self.tracker.evaluate(
            frame,
            LOCAL,
            "target",
            state,
        )

        self.assertEqual(event_name, UPDATED_EVENT)
        self.assertEqual(state["ref"], 42)
        self.assertFalse(state["copy_failed"])

    def test_get_snapshot_demotes_state_when_second_deepcopy_fails(self):
        value = CopyReturnsUncopyable()
        state = self.tracker._make_state(value)

        # Precondition: the initial deepcopy in _make_state() must succeed,
        # since __deepcopy__ only returns an uncopyable object, it doesn't
        # raise. Only the second deepcopy inside get_snapshot() should fail.
        self.assertFalse(state["copy_failed"])
        self.assertIsNotNone(state["copy"])

        snapshot = self.tracker.get_snapshot(state)

        self.assertEqual(snapshot, "<uncopyable>")
        json.dumps(snapshot)  # Must not raise.

        self.assertIsNone(state["copy"])
        self.assertTrue(state["copy_failed"])

    def test_get_snapshot_stays_stable_across_repeated_calls_after_demotion(self):
        state = self.tracker._make_state(CopyReturnsUncopyable())

        first_snapshot = self.tracker.get_snapshot(state)
        second_snapshot = self.tracker.get_snapshot(state)

        self.assertEqual(first_snapshot, "<uncopyable>")
        self.assertEqual(second_snapshot, "<uncopyable>")

    def test_recursive_frames_keep_independent_states(self):
        tracker = VariableTracker("n")
        observations = []

        def visit(n):
            frame = sys._getframe()

            event_name, state = tracker.evaluate(
                frame,
                LOCAL,
                "n",
                None,
            )

            self.assertEqual(event_name, INIT_EVENT)
            self.assertEqual(state["ref"], n)

            if n > 1:
                visit(n - 1)

            event_name, restored_state = tracker.evaluate(
                frame,
                LOCAL,
                "n",
                state,
            )

            observations.append(
                (
                    n,
                    event_name,
                    restored_state["ref"],
                )
            )

        visit(3)

        self.assertEqual(
            observations,
            [
                (1, NO_CHANGE_EVENT, 1),
                (2, NO_CHANGE_EVENT, 2),
                (3, NO_CHANGE_EVENT, 3),
            ],
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)