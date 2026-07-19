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

_FRAME_STATE_ATOMIC_TYPES = (
    int,
    float,
    bool,
    complex,
    str,
    bytes,
    type(None),
)


class VariableTracker:
    def __init__(self, varName, domain=None):
        self.varName = varName
        self.domain = domain

    def _make_state(self, value):
        # Frame state always keeps the current live reference. Only atomic values
        # can be compared by identity alone. Containers need a detached snapshot
        # because they may hold mutable objects even when the container is immutable.
        snapshot = None

        if not isinstance(value, _FRAME_STATE_ATOMIC_TYPES):
            snapshot = copy.deepcopy(value)

        return {
            "ref": value,
            "copy": snapshot,
        }

    def _get_current_value(self, frame, domain, varName):
        if domain == LOCAL or domain == ENCLOSING:
            return frame.f_locals.get(varName)

        if domain == GLOBAL:
            return frame.f_globals.get(varName)

        return None

    def get_snapshot(self, state):
        if state is None:
            return None

        if state["copy"] is None:
            return state["ref"]

        # Do not expose the stored mutable snapshot directly to callers.
        return copy.deepcopy(state["copy"])

    def check(
        self,
        frame,
        domain,
        varName=None,
        prev_state=None,
    ):
        if varName is None:
            varName = self.varName

        if domain == NOT_FOUND or domain == BUILTIN:
            if prev_state is None:
                return NOT_FOUND_EVENT, None

            return DELETED_EVENT, None

        self.domain = domain
        current_value = self._get_current_value(
            frame,
            domain,
            varName,
        )

        if prev_state is None:
            return INIT_EVENT, self._make_state(current_value)

        previous_ref = prev_state["ref"]
        previous_copy = prev_state["copy"]

        # Atomic values do not have a snapshot. Reference identity is enough
        # because they cannot contain independently mutable state.
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