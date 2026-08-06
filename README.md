# oscilo

Zero-invasive variable-change tracker for Python. Register a variable once and `oscilo` records every change it undergoes — without touching your code.

[![PyPI version](https://img.shields.io/pypi/v/oscilo)](https://pypi.org/project/oscilo/)
[![Python](https://img.shields.io/pypi/pyversions/oscilo)](https://pypi.org/project/oscilo/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)

**English** | [한국어](./docs/README.ko.md)

`oscilo` observes program execution in the background and captures how a variable evolves over time — reassignments, in-place mutations, and deletions — then writes the full history to a JSON Lines file when the program exits. The value comparison that runs on every line is delegated to a small C extension to keep the runtime overhead low.

## Contents

- [Motivation](#motivation)
- [Installation](#installation)
- [Quick start](#quick-start)
- [Output format](#output-format)
- [How it works](#how-it-works)
- [Project layout](#project-layout)
- [Testing](#testing)
- [Contributing](#contributing)
- [License](#license)

## Motivation

Inspecting variable state during debugging usually means scattering `print` calls through the code:

```python
def solve(data):
    result = []
    for x in data:
        result.append(x * 2)
        print("result:", result)   # temporary, easy to forget to remove
    return result
```

This clutters the source, is easy to leave behind, and does not scale to hot loops. Interactive debuggers avoid the clutter but interrupt execution, which is impractical when a loop runs thousands of times.

`oscilo` takes a different approach: register a variable by name once, and its history is collected automatically.

```python
import oscilo

def solve(data):
    result = []
    oscilo.register("result")   # every change to `result` from here on is recorded
    for x in data:
        result.append(x * 2)
    return result
```

## Installation

```bash
pip install oscilo
```

`oscilo` ships a C extension. A prebuilt wheel is used when available; otherwise the extension is compiled locally, which requires a C compiler.

<details>
<summary>Building from source</summary>

```bash
pip install -e .                        # editable install (recommended for development)
pip install .                           # standard install
python setup.py build_ext --inplace     # build the C extension only
```
</details>

**Requirements**

- Python 3.11+
- A C compiler (GCC / Clang / MSVC) when building from source

## Quick start

The public API is a single function, `oscilo.register()`, which takes the variable name as a string.

```python
import oscilo

def run():
    target = [100, 200]
    oscilo.register("target")   # recorded as an "init" event

    target.append(300)          # updated (in-place mutation)
    target = "reassigned"       # updated (reassignment)
    del target                  # deleted

run()
# On exit, the history is written to oscilo.jsonl
```

Calling `oscilo.register()` multiple times adds each variable to the same monitor, and all histories are merged into a single output file:

```python
import oscilo

def run():
    score = 10
    items = ["potion", "shield"]

    oscilo.register("score")
    oscilo.register("items")

    score += 55
    items.append("sword")

run()
```

Notes:

- `register()` returns `None`; registration is its only effect.
- Importing `oscilo` has no side effects — tracing starts only when `register()` is called.
- If no change is ever recorded, no file is written.
- If a tracked value cannot be deep-copied, oscilo records `<uncopyable>` and tracks reassignment only. In-place mutations of the same object cannot be detected because no comparison snapshot is available.

## Output format

History is written as [JSON Lines](https://jsonlines.org/) (`oscilo.jsonl` by default). Each line represents a single change:

```json
{"name": "target", "var_id": 1, "data": [100, 200], "event": "init", "domain": "LOCAL", "line": 4, "func": "run", "call_id": 1, "parent_call_id": null, "call_depth": 1}
{"name": "target", "var_id": 1, "data": [100, 200, 300], "event": "updated", "domain": "LOCAL", "line": 6, "func": "run", "call_id": 1, "parent_call_id": null, "call_depth": 1}
{"name": "target", "var_id": 1, "data": "reassigned", "event": "updated", "domain": "LOCAL", "line": 7, "func": "run", "call_id": 1, "parent_call_id": null, "call_depth": 1}
{"name": "target", "var_id": 1, "data": null, "event": "deleted", "domain": "LOCAL", "line": 8, "func": "run", "call_id": 1, "parent_call_id": null, "call_depth": 1}
```

| Field | Description |
|-------|-------------|
| `name` | The tracked variable name |
| `var_id` | Identity of the tracked binding; records sharing a `var_id` refer to the same variable (matches `call_id` for locals; stays stable across frames for globals and closure variables) |
| `data` | The value at the time of the change (`null` for `deleted`) |
| `event` | `init`, `updated`, or `deleted` |
| `domain` | Variable scope: `LOCAL` or `GLOBAL` (a closure/enclosing variable is reported as `LOCAL` from its owning frame's point of view and is identified by `var_id`) |
| `line` | Source line where the change was detected |
| `func` | Function in which the change occurred (`<module>` at module level) |
| `call_id` | Unique id of the function call (frame) where the change occurred |
| `parent_call_id` | `call_id` of the calling frame (`null` for a root call) |
| `call_depth` | Call depth relative to the registration frame (root = `1`) |

The `call_id` / `parent_call_id` / `call_depth` fields let a consumer reconstruct the call tree — i.e. which call each change happened in, and how the calls nest.

The line-delimited format streams and parses efficiently for large histories.

## How it works

`oscilo` watches execution in Python and delegates value comparison to a C extension.

1. The first `register()` call lazily creates a single monitor and installs a trace hook via `sys.settrace`.
2. On each executed line, the C engine (`oscilo_engine`) determines whether a tracked variable changed, using a short-circuiting sequence:

   ```
   Variable no longer in scope?      → deleted
   Reference identity changed?       → updated   (reassignment)
   Immutable type (int/str/...)?     → unchanged (skip comparison)
   Container size changed?           → updated
   Otherwise, compare values         → updated / unchanged
   ```

3. When the process exits, an `atexit` hook flushes the in-memory history to disk in a single write. Records are buffered rather than written per change to avoid I/O overhead.

Unchanged values produce no record, and immutable values are skipped entirely when their reference is unchanged — both are central to keeping the per-line cost low.

## Project layout

```
src/oscilo/
├── __init__.py          # public API (register) and single-instance management
├── _core.py             # monitor implementation and atexit save logic
├── CallContext.py       # lazy call-context tracking (call_id / parent_call_id / call_depth)
├── FileWriter.py        # JSONL output
├── HistoryBuffer.py     # in-memory history buffer
├── ScopeResolver.py     # LEGB scope resolution (local/enclosing/global/builtin)
├── TraceDispatcher.py   # sys.settrace event handling
├── VariableTracker.py   # per-variable change detection and value snapshots
└── oscilo_engine.c      # C extension for value comparison
```

## Testing

```bash
python tests/test.py
```

Tests are discovered from `tests/` (`test_*.py`). Component tests run in-process, while the end-to-end scenarios (registration and process lifecycle) spawn a separate interpreter process, since `atexit`-driven saving and `sys.settrace` behavior can only be verified across a full process lifetime.

## Contributing

Contributions are welcome — bug reports, feature ideas, and pull requests alike.

- Open an issue using the bug report or feature request template.
- Follow the checklist in `.github/pull_request_template.md` when submitting a PR.
- Include tests with new features or fixes where practical.

## License

[MIT](./LICENSE) © 2026 [sdkurjnk](https://github.com/sdkurjnk)
