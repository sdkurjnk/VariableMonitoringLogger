import sys
import unittest

from oscilo.ScopeResolver import ScopeResolver

LOCAL = 0
GLOBAL = 1
ENCLOSING = 2
BUILTIN = 3
NOT_FOUND = -1

TEST_LEGB_GLOBAL = "global-value"

class TestScopeResolverLEGB(unittest.TestCase):
    def setUp(self):
        self.resolver = ScopeResolver()

    def test_captured_local_is_classified_as_local(self):
        captured = "cell-value"

        # Referencing the variable from an inner function moves it to co_cellvars,
        # but it must still be classified as LOCAL in the defining frame.
        def inner():
            return captured

        frame = sys._getframe()
        domain, value = self.resolver.resolve(frame, "captured")

        self.assertEqual(domain, LOCAL)
        self.assertEqual(value, "cell-value")

    def test_free_variable_is_classified_as_enclosing(self):
        enclosing_value = "enclosing-value"

        def inner():
            frame = sys._getframe()
            result = self.resolver.resolve(frame, "enclosing_value")
            # Reference the name so it stays a free variable of this code object.
            self.assertEqual(enclosing_value, "enclosing-value")
            return result

        domain, value = inner()

        self.assertEqual(domain, ENCLOSING)
        self.assertEqual(value, "enclosing-value")

    def test_module_variable_is_classified_as_global(self):
        frame = sys._getframe()
        domain, value = self.resolver.resolve(frame, "TEST_LEGB_GLOBAL")

        self.assertEqual(domain, GLOBAL)
        self.assertEqual(value, "global-value")

    def test_builtin_name_is_classified_as_builtin(self):
        frame = sys._getframe()
        domain, value = self.resolver.resolve(frame, "len")

        self.assertEqual(domain, BUILTIN)
        self.assertIs(value, len)

    def test_local_shadows_builtin(self):
        len = "shadowed-builtin"

        frame = sys._getframe()
        domain, value = self.resolver.resolve(frame, "len")

        self.assertEqual(domain, LOCAL)
        self.assertEqual(value, "shadowed-builtin")

    def test_enclosing_shadows_global(self):
        TEST_LEGB_GLOBAL = "enclosing-value"

        def inner():
            frame = sys._getframe()
            result = self.resolver.resolve(frame, "TEST_LEGB_GLOBAL")
            self.assertEqual(TEST_LEGB_GLOBAL, "enclosing-value")
            return result

        domain, value = inner()

        self.assertEqual(domain, ENCLOSING)
        self.assertEqual(value, "enclosing-value")

    def test_declared_local_shadows_global_even_while_unbound(self):
        frame = sys._getframe()

        # The assignment below makes the name a declared local for this whole
        # function, so resolving before it binds must not fall back to the global.
        domain, value = self.resolver.resolve(frame, "TEST_LEGB_GLOBAL")

        self.assertEqual(domain, NOT_FOUND)
        self.assertIsNone(value)

        TEST_LEGB_GLOBAL = "local-value"
        self.assertEqual(TEST_LEGB_GLOBAL, "local-value")

    def test_deleted_local_is_not_found(self):
        target = "local-value"
        del target

        frame = sys._getframe()
        domain, value = self.resolver.resolve(frame, "target")

        self.assertEqual(domain, NOT_FOUND)
        self.assertIsNone(value)

    def test_unbound_free_variable_is_not_found(self):
        captured = "will-be-deleted"

        def inner():
            frame = sys._getframe()
            result = self.resolver.resolve(frame, "captured")
            # Reference the name so it stays a free variable of this code object.
            if False:
                captured
            return result

        del captured
        domain, value = inner()

        self.assertEqual(domain, NOT_FOUND)
        self.assertIsNone(value)

if __name__ == "__main__":
    unittest.main(verbosity=2)