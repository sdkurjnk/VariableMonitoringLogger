import unittest

from oscilo.CallContext import CallContextManager


class FakeFrame:
    def __init__(self, name, f_back=None):
        self.name = name
        self.f_back = f_back
        self.f_trace = None
        self.f_trace_lines = True

    def __repr__(self):
        return f"FakeFrame({self.name!r})"


class TestCallContextManager(unittest.TestCase):
    def setUp(self):
        self.manager = CallContextManager()

    def test_context_is_created_lazily(self):
        frame = FakeFrame("root")

        self.assertEqual(self.manager._contexts, {})

        context = self.manager.ensure_context(frame)

        self.assertEqual(context["call_id"], 1)
        self.assertIsNone(context["parent_call_id"])
        self.assertEqual(context["call_depth"], 1)
        self.assertIs(self.manager._contexts[frame], context)

    def test_first_logging_frame_becomes_context_root(self):
        unrelated_parent = FakeFrame("unrelated")
        frame = FakeFrame(
            "logging-root",
            f_back=unrelated_parent,
        )

        context = self.manager.ensure_context(frame)

        self.assertEqual(context["call_depth"], 1)
        self.assertIsNone(context["parent_call_id"])
        self.assertNotIn(
            unrelated_parent,
            self.manager._contexts,
        )

    def test_existing_context_is_reused(self):
        frame = FakeFrame("root")

        first_context = self.manager.ensure_context(frame)
        second_context = self.manager.ensure_context(frame)

        self.assertIs(second_context, first_context)
        self.assertEqual(self.manager._next_call_id, 2)

    def test_direct_child_uses_existing_parent_context(self):
        parent = FakeFrame("parent")
        child = FakeFrame(
            "child",
            f_back=parent,
        )

        parent_context = self.manager.ensure_context(parent)
        child_context = self.manager.ensure_context(child)

        self.assertEqual(
            child_context["parent_call_id"],
            parent_context["call_id"],
        )
        self.assertEqual(child_context["call_depth"], 2)
        self.assertIsNone(child.f_trace)

    def test_missing_ancestor_contexts_are_created(self):
        root = FakeFrame("root")
        middle = FakeFrame(
            "middle",
            f_back=root,
        )
        leaf = FakeFrame(
            "leaf",
            f_back=middle,
        )

        root_context = self.manager.ensure_context(root)
        leaf_context = self.manager.ensure_context(leaf)
        middle_context = self.manager._contexts[middle]

        self.assertEqual(
            middle_context["parent_call_id"],
            root_context["call_id"],
        )
        self.assertEqual(middle_context["call_depth"], 2)

        self.assertEqual(
            leaf_context["parent_call_id"],
            middle_context["call_id"],
        )
        self.assertEqual(leaf_context["call_depth"], 3)

        self.assertTrue(callable(middle.f_trace))
        self.assertFalse(middle.f_trace_lines)
        self.assertIsNone(leaf.f_trace)

    def test_sibling_contexts_share_parent(self):
        root = FakeFrame("root")
        left = FakeFrame(
            "left",
            f_back=root,
        )
        right = FakeFrame(
            "right",
            f_back=root,
        )

        root_context = self.manager.ensure_context(root)
        left_context = self.manager.ensure_context(left)
        right_context = self.manager.ensure_context(right)

        self.assertEqual(
            left_context["parent_call_id"],
            root_context["call_id"],
        )
        self.assertEqual(
            right_context["parent_call_id"],
            root_context["call_id"],
        )
        self.assertNotEqual(
            left_context["call_id"],
            right_context["call_id"],
        )
        self.assertEqual(left_context["call_depth"], 2)
        self.assertEqual(right_context["call_depth"], 2)

    def test_relevant_frame_is_removed_on_return(self):
        frame = FakeFrame("relevant")

        first_context = self.manager.ensure_context(frame)
        self.manager.on_return(frame)

        self.assertNotIn(frame, self.manager._contexts)

        second_context = self.manager.ensure_context(frame)

        self.assertNotEqual(
            first_context["call_id"],
            second_context["call_id"],
        )

    def test_cleanup_trace_removes_gap_frame_on_return(self):
        root = FakeFrame("root")
        middle = FakeFrame(
            "middle",
            f_back=root,
        )
        leaf = FakeFrame(
            "leaf",
            f_back=middle,
        )

        self.manager.ensure_context(root)
        self.manager.ensure_context(leaf)

        cleanup_trace = middle.f_trace
        result = cleanup_trace(
            middle,
            "return",
            None,
        )

        self.assertIsNone(result)
        self.assertNotIn(middle, self.manager._contexts)
        self.assertIsNone(middle.f_trace)
        self.assertTrue(middle.f_trace_lines)

    def test_complete_return_sequence_leaves_no_contexts(self):
        root = FakeFrame("root")
        middle = FakeFrame(
            "middle",
            f_back=root,
        )
        leaf = FakeFrame(
            "leaf",
            f_back=middle,
        )

        self.manager.ensure_context(root)
        self.manager.ensure_context(leaf)

        cleanup_trace = middle.f_trace

        self.manager.on_return(leaf)
        cleanup_trace(middle, "return", None)
        self.manager.on_return(root)

        self.assertEqual(self.manager._contexts, {})
        self.assertEqual(self.manager._cleanup_traces, {})

    def test_clear_restores_cleanup_traces_and_resets_ids(self):
        root = FakeFrame("root")
        middle = FakeFrame(
            "middle",
            f_back=root,
        )
        leaf = FakeFrame(
            "leaf",
            f_back=middle,
        )

        self.manager.ensure_context(root)
        self.manager.ensure_context(leaf)

        self.assertTrue(callable(middle.f_trace))
        self.assertFalse(middle.f_trace_lines)

        self.manager.clear()

        self.assertEqual(self.manager._contexts, {})
        self.assertEqual(self.manager._cleanup_traces, {})
        self.assertIsNone(middle.f_trace)
        self.assertTrue(middle.f_trace_lines)

        new_root = FakeFrame("new-root")
        new_context = self.manager.ensure_context(new_root)

        self.assertEqual(new_context["call_id"], 1)
        self.assertIsNone(new_context["parent_call_id"])
        self.assertEqual(new_context["call_depth"], 1)

    def test_none_frame_returns_none(self):
        self.assertIsNone(
            self.manager.ensure_context(None)
        )

        self.manager.on_return(None)

        self.assertEqual(self.manager._contexts, {})


if __name__ == "__main__":
    unittest.main(verbosity=2)