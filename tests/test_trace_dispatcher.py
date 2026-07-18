import sys
import unittest

from oscilo.HistoryBuffer import HistoryBuffer
from oscilo.TraceDispatcher import TraceDispatcher

MODULE_LEVEL_COUNTER = {"value": 0}


def events_for(history, name):
    return [(entry["event"], entry["data"]) for entry in history if entry["name"] == name]


class TestTraceDispatcherFrameRelevance(unittest.TestCase):
    def setUp(self):
        self.buffer = HistoryBuffer()
        self.dispatcher = TraceDispatcher(self.buffer)

    def tearDown(self):
        self.dispatcher.stop()

    def test_irrelevant_frame_call_event_returns_none(self):
        target = [1, 2]
        self.dispatcher.register("target", frame=sys._getframe())

        def unrelated():
            local_only = "no tracked variable in this scope"
            return sys._getframe()

        frame = unrelated()
        result = self.dispatcher._trace_calls(frame, "call", None)

        self.assertIsNone(result)

    def test_unresolved_registration_spreads_relevance_across_module_frames(self):
        # A registration whose variable does not exist anywhere yet cannot be
        # scoped to a single code object in advance (we don't know which
        # frame will eventually define it), so it stays relevant to every
        # frame sharing this module's globals until it resolves or is
        # unregistered. This is a deliberate cost of supporting "register
        # before the variable exists", not a cache bug: it trades away the
        # return-None fast path for any frame in this module for the ability
        # to catch a not-yet-existing global appearing anywhere in it.
        varname = "test_trace_dispatcher_not_yet_defined"
        self.assertNotIn(varname, globals())

        self.dispatcher.register(varname, frame=sys._getframe())

        def elsewhere_in_module():
            return sys._getframe()

        frame = elsewhere_in_module()
        self.assertTrue(callable(self.dispatcher._trace_calls(frame, "call", None)))

        def define_it():
            globals()[varname] = "now-exists"
            marker = "checkpoint"
            self.assertEqual(marker, "checkpoint")

        try:
            define_it()

            events = events_for(self.buffer.getHistory(), varname)
            self.assertEqual(events, [("init", "now-exists")])
        finally:
            globals().pop(varname, None)

    def test_late_defined_local_initializes_once_defined(self):
        def scenario():
            self.dispatcher.register("later_var", frame=sys._getframe())
            later_var = "now-exists"
            marker = "checkpoint"
            self.assertEqual(marker, "checkpoint")

        scenario()

        events = events_for(self.buffer.getHistory(), "later_var")
        self.assertEqual(events, [("init", "now-exists")])


class TestTraceDispatcherRecursion(unittest.TestCase):
    def setUp(self):
        self.buffer = HistoryBuffer()
        self.dispatcher = TraceDispatcher(self.buffer)

    def tearDown(self):
        self.dispatcher.stop()

    def test_recursion_keeps_frame_state_isolated(self):
        def recurse(n):
            acc = n
            self.dispatcher.register("acc", frame=sys._getframe())
            if n > 1:
                recurse(n - 1)

        recurse(3)

        events = events_for(self.buffer.getHistory(), "acc")
        self.assertEqual(events, [("init", 3), ("init", 2), ("init", 1)])

    def test_recursion_updates_are_isolated_per_frame(self):
        def recurse(n):
            acc = [n]
            self.dispatcher.register("acc", frame=sys._getframe())
            if n > 1:
                recurse(n - 1)
            acc.append(n * 100)

        recurse(3)

        events = events_for(self.buffer.getHistory(), "acc")
        self.assertEqual(
            events,
            [
                ("init", [3]),
                ("init", [2]),
                ("init", [1]),
                ("updated", [1, 100]),
                ("updated", [2, 200]),
                ("updated", [3, 300]),
            ],
        )

    def test_repeated_registration_in_recursion_does_not_proliferate_trackers(self):
        def recurse(n):
            acc = n
            self.dispatcher.register("acc", frame=sys._getframe())
            if n > 1:
                recurse(n - 1)

        recurse(3)

        acc_trackers = [t for t in self.dispatcher._trackers if t.varName == "acc"]
        self.assertEqual(len(acc_trackers), 1)

        events = events_for(self.buffer.getHistory(), "acc")
        self.assertEqual(events, [("init", 3), ("init", 2), ("init", 1)])

    def test_sequential_calls_reuse_tracker_and_isolate_state(self):
        def once(value):
            local_var = value
            self.dispatcher.register("local_var", frame=sys._getframe())

        once(1)
        once(2)
        once(3)

        local_trackers = [t for t in self.dispatcher._trackers if t.varName == "local_var"]
        self.assertEqual(len(local_trackers), 1)

        events = events_for(self.buffer.getHistory(), "local_var")
        self.assertEqual(events, [("init", 1), ("init", 2), ("init", 3)])


class TestTraceDispatcherConsecutiveRegistration(unittest.TestCase):
    def setUp(self):
        self.buffer = HistoryBuffer()
        self.dispatcher = TraceDispatcher(self.buffer)

    def tearDown(self):
        self.dispatcher.stop()

    def test_consecutive_registration_in_same_frame_preserves_both(self):
        frame = sys._getframe()
        first = [1]
        second = "alpha"

        self.dispatcher.register("first", frame=frame)
        self.dispatcher.register("second", frame=frame)

        self.assertEqual(len(self.dispatcher._frame_states), 1)

        first.append(2)
        second = "beta"
        marker = "checkpoint"
        self.assertEqual(marker, "checkpoint")

        history = self.buffer.getHistory()
        first_events = events_for(history, "first")
        second_events = events_for(history, "second")

        self.assertEqual(first_events[0], ("init", [1]))
        self.assertEqual(first_events[-1], ("updated", [1, 2]))
        self.assertEqual(second_events[0], ("init", "alpha"))
        self.assertEqual(second_events[-1], ("updated", "beta"))

    def test_register_stores_new_state_in_shared_frame_state(self):
        frame = sys._getframe()
        target = [1, 2]

        self.dispatcher.register("target", frame=frame)

        frame_state = self.dispatcher._frame_states[frame]
        self.assertIn("target", frame_state)
        self.assertIs(frame_state["target"]["ref"], target)


class TestTraceDispatcherGlobalDedup(unittest.TestCase):
    def setUp(self):
        self.buffer = HistoryBuffer()
        self.dispatcher = TraceDispatcher(self.buffer)

    def tearDown(self):
        self.dispatcher.stop()

    def test_global_change_is_not_duplicated_across_active_frames(self):
        global MODULE_LEVEL_COUNTER
        MODULE_LEVEL_COUNTER = {"value": 0}

        def recurse(depth):
            if depth == 0:
                MODULE_LEVEL_COUNTER["value"] += 1
                marker = "leaf"
                self.assertEqual(marker, "leaf")
                return
            recurse(depth - 1)
            marker = "unwind"
            self.assertEqual(marker, "unwind")

        self.dispatcher.register("MODULE_LEVEL_COUNTER", frame=sys._getframe())
        recurse(3)

        events = events_for(self.buffer.getHistory(), "MODULE_LEVEL_COUNTER")
        self.assertEqual(events, [("init", {"value": 0}), ("updated", {"value": 1})])

    def test_register_stores_new_state_in_global_states(self):
        global MODULE_LEVEL_COUNTER
        MODULE_LEVEL_COUNTER = {"value": 0}

        tracker = self.dispatcher.register("MODULE_LEVEL_COUNTER", frame=sys._getframe())

        self.assertIn(tracker, self.dispatcher._global_states)
        self.assertIs(self.dispatcher._global_states[tracker]["ref"], MODULE_LEVEL_COUNTER)


class TestTraceDispatcherCallContextLaziness(unittest.TestCase):
    def setUp(self):
        self.buffer = HistoryBuffer()
        self.dispatcher = TraceDispatcher(self.buffer)

    def tearDown(self):
        self.dispatcher.stop()

    def test_context_created_lazily_only_on_buffered_event(self):
        observed_before = []
        observed_after = []

        def scenario():
            self.dispatcher.register("never_seen", frame=sys._getframe())
            observed_before.append(dict(self.dispatcher._context_manager._contexts))

            never_seen = "now-exists"
            marker = "trigger check"
            observed_after.append(dict(self.dispatcher._context_manager._contexts))
            self.assertEqual(marker, "trigger check")

        scenario()

        self.assertEqual(observed_before[0], {})
        self.assertEqual(len(observed_after[0]), 1)


class TestTraceDispatcherCacheInvalidation(unittest.TestCase):
    def setUp(self):
        self.buffer = HistoryBuffer()
        self.dispatcher = TraceDispatcher(self.buffer)

    def tearDown(self):
        self.dispatcher.stop()

    def test_cache_invalidated_on_register_and_unregister(self):
        # Assert on the effect of invalidation (does relevance reflect the
        # latest tracker set?) rather than on the cache dict being empty:
        # tracing is globally active here, so unrelated internal calls can
        # repopulate _frame_cache between "clear" and "assert" regardless of
        # whether invalidation itself worked.
        a = 1
        b = 2
        frame = sys._getframe()
        self.dispatcher.register("a", frame=frame)

        local_relevant, _ = self.dispatcher._relevant_for(frame)
        self.assertEqual({tracker.varName for tracker in local_relevant}, {"a"})

        tracker_b = self.dispatcher.register("b", frame=frame)

        local_relevant, _ = self.dispatcher._relevant_for(frame)
        self.assertEqual({tracker.varName for tracker in local_relevant}, {"a", "b"})

        self.dispatcher.unregister(tracker_b)

        local_relevant, _ = self.dispatcher._relevant_for(frame)
        self.assertEqual({tracker.varName for tracker in local_relevant}, {"a"})


class TestTraceDispatcherStopCleanup(unittest.TestCase):
    def setUp(self):
        self.buffer = HistoryBuffer()
        self.dispatcher = TraceDispatcher(self.buffer)

    def test_stop_clears_call_context_and_frame_state(self):
        def recurse(n):
            acc = n
            self.dispatcher.register("acc", frame=sys._getframe())
            if n > 1:
                recurse(n - 1)

        recurse(3)
        self.dispatcher.stop()

        self.assertEqual(self.dispatcher._context_manager._contexts, {})
        self.assertEqual(self.dispatcher._context_manager._cleanup_traces, {})
        self.assertEqual(self.dispatcher._frame_states, {})
        self.assertEqual(self.dispatcher._trackers, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)