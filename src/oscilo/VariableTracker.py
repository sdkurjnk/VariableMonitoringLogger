import copy

try:
    from . import oscilo_engine
except ImportError:
    raise RuntimeError("oscilo_engine C extension is not found.")

LOCAL = 0
GLOBAL = 1
ENCLOSING = 2
BUILTIN = 3
NOT_FOUND = -1

INIT_EVENT = "init"
UPDATED_EVENT = "updated"
DELETED_EVENT = "deleted"
NOT_FOUND_EVENT = "not_found"
NO_CHANGE_EVENT = "no_change"

_ATOMIC_TYPES = (int, float, bool, str, bytes, type(None))

_FRAME_STATE_IMMUTABLE_TYPES = (
    int,
    float,
    bool,
    complex,
    str,
    bytes,
    tuple,
    frozenset,
    type(None),
)

_STATE_UNSET = object()

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

    def _make_state(self, value):
        # Frame state always keeps the current live reference. Only values whose
        # type may mutate in place need a detached snapshot for later comparison.
        snapshot = None

        if not isinstance(value, _FRAME_STATE_IMMUTABLE_TYPES):
            snapshot = copy.deepcopy(value)

        return {
            "ref": value,
            "copy": snapshot,
        }

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
        if domain == LOCAL or domain == ENCLOSING:
            return frame.f_locals.get(varName)
        elif domain == GLOBAL:
            return frame.f_globals.get(varName)

    def _handle_missing_variable(self):
        if self._isActive:
            self._clear_state()
            return DELETED_EVENT

        return NOT_FOUND_EVENT

    def get_snapshot(self, state=_STATE_UNSET):
        # Keep the existing no-argument path until the dispatcher is migrated to
        # frame-local state in the following stages.
        if state is _STATE_UNSET:
            return self._make_snapshot(self._lastSnapshot)

        if state is None:
            return None

        if state["copy"] is None:
            return state["ref"]

        # Do not expose the stored mutable snapshot directly to callers.
        return copy.deepcopy(state["copy"])

    def _check_with_instance_state(self, frame, domain, varName):
        # Temporary compatibility path for the current dispatcher. This path is
        # removed after the dispatcher migrates to frame-local state.
        if domain == NOT_FOUND or domain == BUILTIN:
            return self._handle_missing_variable()

        self.domain = domain
        current_value = self._get_current_value(frame, domain, varName)

        if not self._isActive:
            self._store(current_value)
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

        self._store(current_value)
        return UPDATED_EVENT

    def _check_with_frame_state(self, frame, domain, varName, prev_state):
        if domain == NOT_FOUND or domain == BUILTIN:
            if prev_state is None:
                return NOT_FOUND_EVENT, None

            return DELETED_EVENT, None

        self.domain = domain
        current_value = self._get_current_value(frame, domain, varName)

        if prev_state is None:
            return INIT_EVENT, self._make_state(current_value)

        previous_ref = prev_state["ref"]
        previous_copy = prev_state["copy"]

        # Immutable values do not have a snapshot. Their reference identity is
        # sufficient because they cannot mutate in place.
        if previous_copy is None:
            if current_value is previous_ref:
                return NO_CHANGE_EVENT, prev_state

            return UPDATED_EVENT, self._make_state(current_value)

        result = oscilo_engine.check_variable(
            frame,
            previous_ref,
            previous_copy,
            domain,
            varName,
        )

        if result is None:
            return DELETED_EVENT, None

        if result is False:
            return NO_CHANGE_EVENT, prev_state

        return UPDATED_EVENT, self._make_state(current_value)

    def check(
        self,
        frame,
        domain,
        varName=None,
        prev_state=_STATE_UNSET,
    ):
        if varName is None:
            varName = self.varName

        if prev_state is _STATE_UNSET:
            return self._check_with_instance_state(
                frame,
                domain,
                varName,
            )

        return self._check_with_frame_state(
            frame,
            domain,
            varName,
            prev_state,
        )