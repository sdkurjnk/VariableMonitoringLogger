import vml
import os
import json

def test_vml_package():
    log_name = "vml_package_test.jsonl"
    
    if os.path.exists(log_name):
        os.remove(log_name)

    print("\n--- Starting Integrated Package Test ---")
    results_check = []

    data_target = [100, 200]

    monitor = vml.logger("data_target", filename=log_name)
    
    data_target.append(300) 
    data_target = "String Assignment"
    
    monitor._final_save()

    if os.path.exists(monitor.filename):
        with open(monitor.filename, "r", encoding="utf-8") as f:
            logs = [json.loads(line) for line in f]
            
        print(f"Captured Events: {len(logs)}")
        for i, entry in enumerate(logs):
            print(f"Event {i} [{entry['event']}]: {entry['data']}")

        test_passed = len(logs) >= 3
        results_check.append(test_passed)

        if all(results_check):
            print("\nAll Tests Passed")
        else:
            print("\nSome Tests Failed")
    else:
        print(f"\nFail: Log not found at {monitor.filename}")

if __name__ == "__main__":
    test_vml_package()