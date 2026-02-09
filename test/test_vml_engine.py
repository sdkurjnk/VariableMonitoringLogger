import sys
import os
import copy

vml_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src", "vml"))
if vml_dir not in sys.path:
    sys.path.insert(0, vml_dir)

try:
    import vml_engine
    print("Module import successful.")
except ImportError:
    print("Failed to import vml_engine.")
    sys.exit(1)

def run_engine_test():
    print("\n--- vml_engine Logic Test ---")
    frame = sys._getframe()
    results = []
    
    # 1. Test: Existence Check
    res_existence = vml_engine.check_variable(frame, None, "undefined_var", "L")
    test1 = res_existence is None
    results.append(test1)
    print(f"Test 1 (Existence): {res_existence} -> {'Pass' if test1 else 'Fail'}")

    # 2. Test: No Change
    sample_list = [1, 2, 3]
    res_no_change = vml_engine.check_variable(frame, sample_list, "sample_list", "L")
    test2 = res_no_change is False
    results.append(test2)
    print(f"Test 2 (No Change): {res_no_change} -> {'Pass' if test2 else 'Fail'}")

    # 3. Test: Reference Change (Stack)
    prev_ref = sample_list
    sample_list = "New String" 
    res_stack = vml_engine.check_variable(frame, prev_ref, "sample_list", "L")
    test3 = res_stack is True
    results.append(test3)
    print(f"Test 3 (Stack/Ref): {res_stack} -> {'Pass' if test3 else 'Fail'}")

    # 4. Test: Data Change (Heap)
    mutable_obj = [10, 20]
    old_snapshot = copy.deepcopy(mutable_obj)
    
    mutable_obj.append(30)
    res_heap = vml_engine.check_variable(frame, old_snapshot, "mutable_obj", "L")
    test4 = res_heap is True
    results.append(test4)
    print(f"Test 4 (Heap/Data): {res_heap} -> {'Pass' if test4 else 'Fail'}")

    if all(results):
        print("\nAll Tests Passed")
    else:
        print("\nSome Tests Failed")

if __name__ == "__main__":
    run_engine_test()