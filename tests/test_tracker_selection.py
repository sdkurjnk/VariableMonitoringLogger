import unittest

from oscilo.HistoryBuffer import HistoryBuffer
from oscilo.TraceDispatcher import TraceDispatcher


class FakeFrame:
    def __init__(self, code, globals_dict, locals_dict=None, lineno=1):
        self.f_code = code
        self.f_globals = globals_dict
        self.f_locals = {} if locals_dict is None else locals_dict
        self.f_builtins = {}
        self.f_lineno = lineno
        self.f_trace = None
        self.f_trace_lines = True
        self.f_back = None


def _code_with_locals(*names):
    # Build a throwaway function whose code object declares exactly these
    # local names, without needing a real call/frame for it.
    lines = ["def _target():"]
    for name in names:
        lines.append(f"    {name} = None")
    lines.append("    return None")

    namespace = {}
    exec("\n".join(lines), namespace)
    return namespace["_target"].__code__


class TestTrackerSelectionCache(unittest.TestCase):
    def setUp(self):
        self.dispatcher = TraceDispatcher(HistoryBuffer())

    def tearDown(self):
        self.dispatcher.stop()

    def test_local_candidate_requires_exact_code_object(self):
        code_a = _code_with_locals("target")
        code_b = _code_with_locals("target")  # same name, unrelated function
        globals_dict = {}

        frame_a = FakeFrame(code_a, globals_dict)
        tracker = self.dispatcher.register("target", frame=frame_a)

        frame_b = FakeFrame(code_b, globals_dict)
        local_relevant, global_relevant = self.dispatcher._relevant_for(frame_b)

        self.assertNotIn(tracker, local_relevant)
        self.assertNotIn(tracker, global_relevant)

    def test_local_candidate_matches_same_code_object_on_another_frame(self):
        code = _code_with_locals("target")
        globals_dict = {}

        frame_a = FakeFrame(code, globals_dict)
        tracker = self.dispatcher.register("target", frame=frame_a)

        frame_b = FakeFrame(code, globals_dict)  # e.g. a later call of the same function
        local_relevant, _ = self.dispatcher._relevant_for(frame_b)

        self.assertIn(tracker, local_relevant)

    def test_global_candidate_requires_exact_globals_identity(self):
        code = _code_with_locals()  # "counter" is not a local name here
        module_globals = {"counter": 1}
        other_globals = {"counter": 1}

        frame_a = FakeFrame(code, module_globals)
        tracker = self.dispatcher.register("counter", frame=frame_a)

        frame_other_module = FakeFrame(code, other_globals)
        _, global_relevant = self.dispatcher._relevant_for(frame_other_module)

        self.assertNotIn(tracker, global_relevant)

    def test_global_candidate_matches_shared_globals_across_functions(self):
        code_caller = _code_with_locals()
        code_callee = _code_with_locals()
        module_globals = {"counter": 1}

        frame_a = FakeFrame(code_caller, module_globals)
        tracker = self.dispatcher.register("counter", frame=frame_a)

        frame_b = FakeFrame(code_callee, module_globals)
        _, global_relevant = self.dispatcher._relevant_for(frame_b)

        self.assertIn(tracker, global_relevant)

    def test_global_candidates_support_same_code_across_different_globals(self):
        code = _code_with_locals()
        globals_a = {"counter": 1}
        globals_b = {"counter": 2}

        tracker_a = self.dispatcher.register(
            "counter",
            frame=FakeFrame(code, globals_a),
        )
        tracker_b = self.dispatcher.register(
            "counter",
            frame=FakeFrame(code, globals_b),
        )

        # Force both frames to share one code-based cache entry.
        self.dispatcher._frame_cache.clear()

        frame_a = FakeFrame(code, globals_a)
        frame_b = FakeFrame(code, globals_b)

        _, relevant_a = self.dispatcher._relevant_for(frame_a)
        _, relevant_b = self.dispatcher._relevant_for(frame_b)

        self.assertEqual(relevant_a, [tracker_a])
        self.assertEqual(relevant_b, [tracker_b])

    def test_irrelevant_frame_call_event_returns_none(self):
        code_a = _code_with_locals("target")
        frame_a = FakeFrame(code_a, {})
        self.dispatcher.register("target", frame=frame_a)

        unrelated_code = _code_with_locals("nothing_tracked")
        unrelated_frame = FakeFrame(unrelated_code, {})

        result = self.dispatcher._trace_calls(unrelated_frame, "call", None)

        self.assertIsNone(result)

    def test_relevant_frame_call_event_returns_tracer(self):
        code = _code_with_locals()
        module_globals = {"counter": 1}

        frame_a = FakeFrame(code, module_globals)
        self.dispatcher.register("counter", frame=frame_a)

        frame_b = FakeFrame(code, module_globals)
        result = self.dispatcher._trace_calls(frame_b, "call", None)

        self.assertTrue(callable(result))
        self.assertIs(frame_b.f_trace, result)

    def test_cache_invalidated_on_register(self):
        # Assert on the effect of invalidation (relevance reflects the
        # latest tracker set) rather than on _frame_cache being empty, since
        # unrelated calls can repopulate it once tracing is globally active.
        code = _code_with_locals("a", "b")
        frame = FakeFrame(code, {})

        self.dispatcher.register("a", frame=frame)
        local_relevant, _ = self.dispatcher._relevant_for(frame)
        self.assertEqual({tracker.varName for tracker in local_relevant}, {"a"})

        self.dispatcher.register("b", frame=frame)
        local_relevant, _ = self.dispatcher._relevant_for(frame)
        self.assertEqual({tracker.varName for tracker in local_relevant}, {"a", "b"})

    def test_cache_invalidated_on_unregister(self):
        code = _code_with_locals("a")
        frame = FakeFrame(code, {})

        tracker = self.dispatcher.register("a", frame=frame)
        local_relevant, _ = self.dispatcher._relevant_for(frame)
        self.assertEqual(local_relevant, [tracker])

        self.dispatcher.unregister(tracker)
        local_relevant, _ = self.dispatcher._relevant_for(frame)
        self.assertEqual(local_relevant, [])

    def test_cache_splits_candidates_by_code_structure(self):
        code = _code_with_locals("local_name")
        globals_dict = {}
        frame = FakeFrame(code, globals_dict)

        local_tracker = self.dispatcher.register("local_name", frame=frame)
        global_tracker = self.dispatcher.register("global_name", frame=frame)

        local_candidates, global_candidates, entry_globals = self.dispatcher._get_cache_entry(frame)

        self.assertIn(local_tracker, local_candidates)
        self.assertNotIn(local_tracker, global_candidates)
        self.assertIn(global_tracker, global_candidates)
        self.assertNotIn(global_tracker, local_candidates)
        self.assertIs(entry_globals, globals_dict)


if __name__ == "__main__":
    unittest.main(verbosity=2)