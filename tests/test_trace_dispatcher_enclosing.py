import sys
import unittest

from oscilo.HistoryBuffer import HistoryBuffer
from oscilo.TraceDispatcher import TraceDispatcher


def events_for(history, name):
    return [(entry["event"], entry["data"]) for entry in history if entry["name"] == name]


def var_ids_for(history, name):
    return [entry["var_id"] for entry in history if entry["name"] == name]


def call_ids_for(history, name):
    return [entry["call_id"] for entry in history if entry["name"] == name]

def domains_for(history, name):
    return [entry["domain"] for entry in history if entry["name"] == name]

class TestTraceDispatcherEnclosingIdentity(unittest.TestCase):
    def setUp(self):
        self.buffer = HistoryBuffer()
        self.dispatcher = TraceDispatcher(self.buffer)

    def tearDown(self):
        self.dispatcher.stop()

    def test_same_closure_called_repeatedly_keeps_same_var_id(self):
        def outer():
            total = 0
            def inner():
                nonlocal total
                self.dispatcher.register("total", frame=sys._getframe())
                total += 1
            return inner

        cb1 = outer()
        cb1()
        cb1()
        cb1()

        history = self.buffer.getHistory()
        events = events_for(history, "total")
        var_ids = var_ids_for(history, "total")
        call_ids = call_ids_for(history, "total")
        domains = domains_for(history, "total")

        self.assertEqual(events, [("init", 0), ("updated", 1), ("updated", 2), ("updated", 3)])
        self.assertEqual(len(set(var_ids)), 1)

        # Each *call* to cb1 gets its own call_id; events produced within the
        # same call share it. Here the 1st call yields two events (init +
        # updated) sharing one call_id, while the 2nd and 3rd calls each
        # yield a single updated event with a call_id of their own.
        self.assertEqual(call_ids[0], call_ids[1])
        self.assertEqual(len({call_ids[1], call_ids[2], call_ids[3]}), 3)

        # ENCLOSING is an internal LEGB classification only; the log always
        # reports the variable as LOCAL, never as "ENCLOSING".
        self.assertTrue(all(domain == "LOCAL" for domain in domains))

    def test_different_outer_calls_get_different_var_ids(self):
        def outer():
            total = 0
            def inner():
                nonlocal total
                self.dispatcher.register("total", frame=sys._getframe())
                total += 1
            return inner

        cbA = outer()
        cbB = outer()
        cbA()
        cbB()
        cbA()
        cbB()

        history = self.buffer.getHistory()
        entries = [entry for entry in history if entry["name"] == "total"]
        var_ids = {entry["var_id"] for entry in entries}

        # Two independent closures over the same code object must resolve to
        # two distinct cells, so exactly two var_ids should appear.
        self.assertEqual(len(var_ids), 2)

        # Within each var_id's own events, the value sequence must be its own
        # independent 0, 1, 2 count (each closure has its own cell), proving
        # the two var_ids were not accidentally merged or cross-contaminated.
        for var_id in var_ids:
            data_sequence = [entry["data"] for entry in entries if entry["var_id"] == var_id]
            self.assertEqual(data_sequence, [0, 1, 2])

    def test_recursion_with_closure_keeps_var_id_and_advances_call_depth(self):
        def make_counter():
            total = 0
            def inner(n):
                nonlocal total
                self.dispatcher.register("total", frame=sys._getframe())
                total += 1
                if n > 1:
                    inner(n - 1)
            return inner

        counter = make_counter()
        counter(3)

        history = self.buffer.getHistory()
        events = events_for(history, "total")
        var_ids = var_ids_for(history, "total")
        depths = [entry["call_depth"] for entry in history if entry["name"] == "total"]

        self.assertEqual(events, [("init", 0), ("updated", 1), ("updated", 2), ("updated", 3)])
        self.assertEqual(len(set(var_ids)), 1)
        self.assertEqual(depths, [1, 1, 2, 3])

    def test_closure_called_after_outer_has_returned(self):
        def outer():
            total = 0
            def inner():
                nonlocal total
                self.dispatcher.register("total", frame=sys._getframe())
                total += 1
            return inner

        callback = outer()
        callback()
        callback()

        history = self.buffer.getHistory()
        events = events_for(history, "total")
        var_ids = var_ids_for(history, "total")

        self.assertEqual(events, [("init", 0), ("updated", 1), ("updated", 2)])
        self.assertEqual(len(set(var_ids)), 1)

    def test_unregister_purges_enclosing_state_for_that_tracker(self):
        def outer():
            total = 0
            def inner():
                nonlocal total
                tracker = self.dispatcher.register("total", frame=sys._getframe())
                total += 1
                return tracker
            return inner

        cb1 = outer()
        tracker = cb1()
        cb1()

        self.assertIn(tracker, self.dispatcher._tracker_cells)
        self.assertTrue(self.dispatcher._enclosing_var_ids)
        self.assertTrue(self.dispatcher._enclosing_states)
        self.assertTrue(self.dispatcher._enclosing_cell_refs)

        self.dispatcher.unregister(tracker)

        self.assertNotIn(tracker, self.dispatcher._tracker_cells)
        self.assertEqual(self.dispatcher._enclosing_var_ids, {})
        self.assertEqual(self.dispatcher._enclosing_states, {})
        self.assertEqual(self.dispatcher._enclosing_cell_refs, {})

    def test_stop_clears_all_enclosing_state(self):
        def outer():
            total = 0
            def inner():
                nonlocal total
                self.dispatcher.register("total", frame=sys._getframe())
                total += 1
            return inner

        cb1 = outer()
        cb1()
        cb1()

        self.dispatcher.stop()

        self.assertEqual(self.dispatcher._enclosing_var_ids, {})
        self.assertEqual(self.dispatcher._enclosing_states, {})
        self.assertEqual(self.dispatcher._enclosing_cell_refs, {})
        self.assertEqual(self.dispatcher._frame_cell_cache, {})
        self.assertEqual(self.dispatcher._tracker_cells, {})

    def test_unresolvable_cell_falls_back_to_var_id_equal_call_id(self):
        def make():
            total = 0
            def inner():
                nonlocal total
                self.dispatcher.register("total", frame=sys._getframe())
                total += 1
            return inner

        # Never bound to a name in the caller's locals/globals, so the
        # caller-frame heuristic cannot find the owning cell.
        make()()

        history = self.buffer.getHistory()
        entries = [entry for entry in history if entry["name"] == "total"]

        self.assertTrue(entries)
        for entry in entries:
            self.assertEqual(entry["var_id"], entry["call_id"])


class TestTraceDispatcherEnclosingAncestorEarlyExit(unittest.TestCase):
    """Covers issue #59's register() ancestor-walk early exit specifically
    for the ENCLOSING domain: closures resolve identity via
    _enclosing_states/id(cell), not _frame_states, so the early-exit
    condition (keyed off _frame_states) must have no effect on that
    cell-based bookkeeping while still short-circuiting the frame walk
    itself for recursive dedup registrations.
    """

    def setUp(self):
        self.buffer = HistoryBuffer()
        self.dispatcher = TraceDispatcher(self.buffer)

    def tearDown(self):
        self.dispatcher.stop()

    def _freeze_global_trace(self):
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

    def test_enclosing_recursive_dedup_gets_ancestor_early_exit(self):
        self._freeze_global_trace()
        counts = self._count_relevant_for_calls()
        depths_checked = []

        def make_counter():
            total = 0

            def inner(n):
                nonlocal total
                frame = sys._getframe()
                self.dispatcher.register("total", frame=frame)
                total += 1
                if n < 4:
                    parent = frame.f_back
                    self.assertIn(parent, self.dispatcher._frame_states)
                    depths_checked.append(counts.get(id(parent), 0))
                if n > 1:
                    inner(n - 1)

            return inner

        counter = make_counter()
        counter(4)

        self.assertEqual(depths_checked, [0, 0, 0])

        # Cell/var_id bookkeeping is untouched by the frame-walk shortcut:
        # a single recursive closure still resolves to exactly one cell.
        self.assertEqual(len(self.dispatcher._enclosing_var_ids), 1)

        history = self.buffer.getHistory()
        var_ids = {entry["var_id"] for entry in history if entry["name"] == "total"}
        self.assertEqual(len(var_ids), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
