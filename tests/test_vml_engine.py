import copy
import sys
import unittest

from vml import vml_engine


class TestVMLEngine(unittest.TestCase):

    def test_returns_none_when_variable_does_not_exist(self):
        frame = sys._getframe()

        result = vml_engine.check_variable(
            frame, None, None, 0, "undefined_var"
        )

        self.assertIsNone(result)

    def test_returns_false_when_value_does_not_change(self):
        sample_list = [1, 2, 3]
        previous_reference = sample_list
        previous_snapshot = copy.deepcopy(sample_list)

        frame = sys._getframe()

        result = vml_engine.check_variable(
            frame, previous_reference, previous_snapshot, 0, "sample_list"
        )

        self.assertIs(result, False)

    def test_returns_true_when_reference_changes(self):
        sample_list = [1, 2, 3]
        previous_reference = sample_list
        previous_snapshot = copy.deepcopy(sample_list)

        sample_list = [1, 2, 3]
        frame = sys._getframe()

        result = vml_engine.check_variable(
            frame, previous_reference, previous_snapshot, 0, "sample_list"
        )

        self.assertIs(result, True)

    def test_returns_true_when_mutable_data_changes(self):
        mutable_obj = [10, 20]
        previous_reference = mutable_obj
        previous_snapshot = copy.deepcopy(mutable_obj)

        mutable_obj.append(30)
        frame = sys._getframe()

        result = vml_engine.check_variable(
            frame, previous_reference, previous_snapshot, 0, "mutable_obj"
        )

        self.assertIs(result, True)


if __name__ == "__main__":
    unittest.main(verbosity=2)