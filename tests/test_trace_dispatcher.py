import sys
import unittest

from oscilo.HistoryBuffer import HistoryBuffer
from oscilo.TraceDispatcher import TraceDispatcher, GLOBAL_STATE_KEY

MODULE_LEVEL_COUNTER = {"value": 0}


def events_for(history, name):
    return [(entry["event"], entry["data"]) for entry in history if entry["name"] == name]


class TestTraceDispatcherFrameRelevance(unittest.TestCase):
    def setUp(self):
        self.buffer = HistoryBuffer()
        self.dispatcher = TraceDispatcher(self.buffer)

    def test_register_requires_frame(self):
        with self.assertRaisesRegex(
            ValueError,
            "frame is required",
        ):
            self.dispatcher.register("target", frame=None)

        self.assertEqual(self.dispatcher._trackers, [])
        self.assertEqual(self.dispatcher._frame_cache, {})
        self.assertFalse(self.dispatcher._is_tracing)

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

    def test_active_ancestor_with_shadowing_local_is_not_traced(self):
        global MODULE_LEVEL_COUNTER
        MODULE_LEVEL_COUNTER = {"value": 0}
        ancestor_tracking = []

        def outer():
            MODULE_LEVEL_COUNTER = "shadowed local"

            def register_global():
                self.dispatcher.register(
                    "MODULE_LEVEL_COUNTER",
                    frame=sys._getframe(),
                )

            register_global()

            ancestor_tracking.append(
                sys._getframe() in self.dispatcher._frame_states
            )
            self.assertEqual(
                MODULE_LEVEL_COUNTER,
                "shadowed local",
            )

        outer()

        self.assertEqual(ancestor_tracking, [False])

    def test_active_ancestor_tracking_stops_at_module_frame_boundary(self):
        # A nested exec() that reuses this module's globals() dict (the same
        # pattern a Jupyter cell or a dynamic-code loader uses) creates a
        # second "<module>" frame sharing globals identity with this test's
        # own frame. Ancestor tracking must stop once it reaches that nested
        # <module> frame instead of climbing past it into the real caller,
        # which only happens to share the same globals dict by coincidence.
        # Membership is checked while each frame is still on the stack,
        # since return-cleanup would otherwise pop it before we can inspect it.
        global MODULE_LEVEL_COUNTER
        MODULE_LEVEL_COUNTER = {"value": 0}
        tracked = {}

        def register_global():
            self.dispatcher.register(
                "MODULE_LEVEL_COUNTER",
                frame=sys._getframe(),
            )

        exec_globals = globals()
        exec_globals["_boundary_test_register"] = register_global
        exec_globals["_boundary_test_tracked"] = tracked
        exec_globals["_boundary_test_dispatcher"] = self.dispatcher
        source = (
            "import sys\n"
            "def _nested_caller():\n"
            "    _boundary_test_register()\n"
            "    _boundary_test_tracked['nested_caller'] = ("
            "sys._getframe() in _boundary_test_dispatcher._frame_states)\n"
            "_nested_caller()\n"
            "_boundary_test_tracked['module'] = ("
            "sys._getframe() in _boundary_test_dispatcher._frame_states)\n"
        )

        try:
            exec(compile(source, "<ancestor-boundary-test>", "exec"), exec_globals)
        finally:
            del exec_globals["_boundary_test_register"]
            del exec_globals["_boundary_test_tracked"]
            del exec_globals["_boundary_test_dispatcher"]

        caller_tracked = sys._getframe() in self.dispatcher._frame_states

        self.assertTrue(tracked["nested_caller"])
        self.assertTrue(tracked["module"])
        self.assertFalse(caller_tracked)

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

    def test_register_stores_new_state_in_owning_tracker(self):
        frame = sys._getframe()
        target = [1, 2]

        tracker = self.dispatcher.register("target", frame=frame)

        self.assertIn(frame, tracker._states)
        self.assertIs(tracker._states[frame]["ref"], target)


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

        history = self.buffer.getHistory()
        events = events_for(history, "MODULE_LEVEL_COUNTER")

        self.assertEqual(
            events,
            [
                ("init", {"value": 0}),
                ("updated", {"value": 1}),
            ],
        )

        counter_logs = [
            entry
            for entry in history
            if entry["name"] == "MODULE_LEVEL_COUNTER"
        ]

        init_log = next(
            entry
            for entry in counter_logs
            if entry["event"] == "init"
        )
        updated_log = next(
            entry
            for entry in counter_logs
            if entry["event"] == "updated"
        )

        self.assertEqual(init_log["var_id"], init_log["call_id"])
        self.assertEqual(updated_log["var_id"], init_log["var_id"])
        self.assertNotEqual(updated_log["call_id"], updated_log["var_id"])

    def test_register_stores_new_global_state_in_owning_tracker(self):
        global MODULE_LEVEL_COUNTER
        MODULE_LEVEL_COUNTER = {"value": 0}

        tracker = self.dispatcher.register("MODULE_LEVEL_COUNTER", frame=sys._getframe())

        self.assertIn(GLOBAL_STATE_KEY, tracker._states)
        self.assertIs(tracker._states[GLOBAL_STATE_KEY]["ref"], MODULE_LEVEL_COUNTER)


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

    def tearDown(self):
        self.dispatcher.stop()

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

    def test_active_ancestor_states_are_isolated_and_removed_on_return(self):
        global MODULE_LEVEL_COUNTER
        MODULE_LEVEL_COUNTER = {"value": 0}
        returned_frames = []

        def outer():
            def register_global():
                self.dispatcher.register(
                    "MODULE_LEVEL_COUNTER",
                    frame=sys._getframe(),
                )

            register_global()

            outer_frame = sys._getframe()
            parent_frame = outer_frame.f_back

            self.assertIn(
                outer_frame,
                self.dispatcher._frame_states,
            )
            self.assertIn(
                parent_frame,
                self.dispatcher._frame_states,
            )
            self.assertIsNot(
                self.dispatcher._frame_states[outer_frame],
                self.dispatcher._frame_states[parent_frame],
            )

            returned_frames.append(outer_frame)

        outer()

        self.assertNotIn(
            returned_frames[0],
            self.dispatcher._frame_states,
        )
        self.assertIn(
            sys._getframe(),
            self.dispatcher._frame_states,
        )

    def test_stop_clears_active_ancestor_frame_state(self):
        global MODULE_LEVEL_COUNTER
        MODULE_LEVEL_COUNTER = {"value": 0}

        def register_global():
            self.dispatcher.register(
                "MODULE_LEVEL_COUNTER",
                frame=sys._getframe(),
            )

        register_global()

        active_ancestor = sys._getframe()

        self.assertIn(
            active_ancestor,
            self.dispatcher._frame_states,
        )

        self.dispatcher.stop()

        self.assertNotIn(
            active_ancestor,
            self.dispatcher._frame_states,
        )
        self.assertEqual(
            self.dispatcher._frame_states,
            {},
        )


class TestTraceDispatcherAncestorEarlyExit(unittest.TestCase):
    """Covers the register() ancestor-walk early exit (issue #59): a dedup
    registration (is_new_tracker=False) must stop climbing frame.f_back as
    soon as it reaches a frame already present in _frame_states, instead of
    re-walking ancestors an earlier registration already tracked. A new
    tracker (is_new_tracker=True) must never take this shortcut, since it
    can change relevance for the whole frame_cache.
    """

    def setUp(self):
        self.buffer = HistoryBuffer()
        self.dispatcher = TraceDispatcher(self.buffer)

    def tearDown(self):
        self.dispatcher.stop()

    def _freeze_global_trace(self):
        # Force _is_tracing True *before* any register() call so that
        # register()'s internal _start_tracing() sees tracing as already
        # active and skips re-installing sys.settrace. This keeps the
        # global "call"-event hook (_trace_calls) off for the whole test,
        # so the _relevant_for counts below reflect only calls made
        # explicitly by the ancestor-walk/registration code path, not the
        # incidental noise sys.settrace adds for every Python call while
        # active. The dispatcher's own dict bookkeeping is unaffected by
        # whether sys.settrace is actually installed.
        self.dispatcher._is_tracing = True
        sys.settrace(None)

    def _count_relevant_for_calls(self):
        counts = {}
        original = self.dispatcher._relevant_for

        def wrapper(frame):
            counts[id(frame)] = counts.get(id(frame), 0) + 1
            return original(frame)

        self.dispatcher._relevant_for = wrapper
        return counts

    def test_dedup_registration_stops_before_checking_tracked_parent(self):
        self._freeze_global_trace()
        counts = self._count_relevant_for_calls()
        depths_checked = []

        def recurse(n):
            acc = n
            frame = sys._getframe()
            self.dispatcher.register("acc", frame=frame)
            if n < 5:
                parent = frame.f_back
                self.assertIn(parent, self.dispatcher._frame_states)
                depths_checked.append(counts.get(id(parent), 0))
            if n > 1:
                recurse(n - 1)

        recurse(5)

        # Each dedup registration's immediate parent was already tracked by
        # the parent's own register() call still on the stack, so the
        # early-exit break must fire before _relevant_for is ever invoked
        # on that parent.
        self.assertEqual(depths_checked, [0, 0, 0, 0])

    def test_global_dedup_registration_gets_ancestor_early_exit(self):
        global MODULE_LEVEL_COUNTER
        MODULE_LEVEL_COUNTER = {"value": 0}

        self._freeze_global_trace()
        counts = self._count_relevant_for_calls()
        depths_checked = []

        def recurse(n):
            frame = sys._getframe()
            self.dispatcher.register("MODULE_LEVEL_COUNTER", frame=frame)
            if n < 4:
                parent = frame.f_back
                self.assertIn(parent, self.dispatcher._frame_states)
                depths_checked.append(counts.get(id(parent), 0))
            if n > 1:
                recurse(n - 1)

        recurse(4)

        self.assertEqual(depths_checked, [0, 0, 0])

    def test_interleaved_untracked_frame_is_checked_once_then_walk_stops(self):
        self._freeze_global_trace()
        counts = self._count_relevant_for_calls()

        depth = 4
        wrapper_frames = []
        recurse_body_frames = []

        def wrapper(k):
            wrapper_frames.append(sys._getframe())
            recurse_body(k)

        def recurse_body(k):
            acc = k
            frame = sys._getframe()
            recurse_body_frames.append(frame)
            self.dispatcher.register("acc", frame=frame)
            if k > 1:
                wrapper(k - 1)

        wrapper(depth)

        # wrapper() declares no tracked variable and is a brand-new frame
        # object on every call, so it can never already be in _frame_states;
        # the ancestor walk must therefore evaluate its relevance exactly
        # once (never skip it, or relevance would silently go unchecked).
        for frame in wrapper_frames:
            self.assertEqual(counts.get(id(frame), 0), 1)

        # recurse_body() tracks its own frame before recursing further, so
        # no deeper registration's ancestor walk should ever re-examine it.
        for frame in recurse_body_frames:
            self.assertIn(frame, self.dispatcher._frame_states)
            self.assertEqual(counts.get(id(frame), 0), 0)

    def test_new_tracker_mid_recursion_does_not_early_exit(self):
        self._freeze_global_trace()
        counts = self._count_relevant_for_calls()

        def recurse(n):
            a = n
            frame = sys._getframe()
            self.dispatcher.register("a", frame=frame)
            if n == 2:
                parent = frame.f_back
                self.assertIn(parent, self.dispatcher._frame_states)

                # "b" has never been registered anywhere, so this is a
                # brand-new tracker (is_new_tracker=True). Even though the
                # immediate parent is already tracked, the walk must still
                # visit it -- new trackers never take the early-exit
                # shortcut, since _frame_cache.clear() can change what is
                # relevant for any frame.
                self.dispatcher.register("b", frame=frame)
                self.assertGreaterEqual(counts.get(id(parent), 0), 1)
            if n > 1:
                recurse(n - 1)

        recurse(3)

        b_trackers = [t for t in self.dispatcher._trackers if t.varName == "b"]
        self.assertEqual(len(b_trackers), 1)

    def test_unregister_then_reregister_forces_full_walk_again(self):
        def outer():
            other = 1
            outer_frame = sys._getframe()
            self.dispatcher.register("other", frame=outer_frame)

            def inner():
                x = 1
                frame = sys._getframe()
                tracker1 = self.dispatcher.register("x", frame=frame)
                self.dispatcher.unregister(tracker1)

                dedup_key = ("x", frame.f_code)
                self.assertNotIn(dedup_key, self.dispatcher._registered_local)

                self._freeze_global_trace()
                counts = self._count_relevant_for_calls()

                parent = frame.f_back
                self.assertIn(parent, self.dispatcher._frame_states)

                tracker2 = self.dispatcher.register("x", frame=frame)

                self.assertIsNot(tracker1, tracker2)
                # Re-registration after unregister creates a brand-new
                # tracker (is_new_tracker=True), so the walk must still
                # visit the already-tracked parent instead of
                # short-circuiting.
                self.assertGreaterEqual(counts.get(id(parent), 0), 1)

            inner()

        outer()


if __name__ == "__main__":
    unittest.main(verbosity=2)