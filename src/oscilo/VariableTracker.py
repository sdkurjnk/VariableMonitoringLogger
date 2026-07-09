import copy

try:
    from . import oscilo_engine
except ImportError:
    raise RuntimeError("oscilo_engine C extension is not found.")

LOCAL = 0
GLOBAL = 1
NOT_FOUND = -1

INIT_EVENT = "init"
UPDATED_EVENT = "updated"
DELETED_EVENT = "deleted"
NOT_FOUND_EVENT = "not_found"
NO_CHANGE_EVENT = "no_change"

_ATOMIC_TYPES = (int, float, bool, str, bytes, type(None))

class VariableTracker:
    def __init__(self, varName, domain=None, value=None, exists=False, frame=None):
        self.varName = varName
        self.domain = domain
        self.frame = frame
        self._lastRef = None
        self._lastCopy = None
        self._lastSnapshot = None
        self._isActive = False

        if exists:
            self._store(value)
            self._isActive = True

    def _make_snapshot(self, value):
        # Atomic values are safe to reuse because they cannot be mutated in place.
        if isinstance(value, _ATOMIC_TYPES):
            return value

        value_type = type(value)

        # Handle common containers directly to avoid unnecessary deepcopy cost.
        if value_type is list:
            return [self._make_snapshot(item) for item in value]

        if value_type is dict:
            return {
                self._make_snapshot(key): self._make_snapshot(item)
                for key, item in value.items()
            }

        if value_type is set:
            return {self._make_snapshot(item) for item in value}

        if value_type is frozenset:
            return frozenset(self._make_snapshot(item) for item in value)

        if value_type is tuple:
            return tuple(self._make_snapshot(item) for item in value)

        # Fall back to deepcopy for custom objects, then repr if copying fails.
        try:
            return copy.deepcopy(value)
        except Exception:
            return repr(value)

    def _store(self, value):
        # Store both a live reference and a snapshot for native change detection.
        snapshot = self._make_snapshot(value)
        self._lastRef = value
        self._lastCopy = snapshot
        self._lastSnapshot = snapshot

    def _clear_state(self):
        self._lastRef = None
        self._lastCopy = None
        self._lastSnapshot = None
        self._isActive = False

    def _get_current_value(self, frame, domain, varName):
        if domain == LOCAL:
            return frame.f_locals.get(varName)

        return frame.f_globals.get(varName)

    def _handle_missing_variable(self):
        if self._isActive:
            self._clear_state()
            return DELETED_EVENT

        return NOT_FOUND_EVENT

    def get_snapshot(self):
        # Return a fresh snapshot so callers cannot mutate internal tracker state.
        return self._make_snapshot(self._lastSnapshot)

    def check(self, frame, domain, varName=None):
        if varName is None:
            varName = self.varName

        if domain == NOT_FOUND:
            return self._handle_missing_variable()

        self.domain = domain
        currentVal = self._get_current_value(frame, domain, varName)

        if not self._isActive:
            self._store(currentVal)
            self._isActive = True
            return INIT_EVENT

        result = oscilo_engine.check_variable(
            frame,
            self._lastRef,
            self._lastCopy,
            domain,
            varName,
        )

        if result is None:
            return self._handle_missing_variable()

        if result is False:
            return NO_CHANGE_EVENT

        self._store(currentVal)
        return UPDATED_EVENT