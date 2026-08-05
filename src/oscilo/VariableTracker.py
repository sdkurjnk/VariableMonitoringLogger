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
        copy_failed = False

        if not isinstance(value, _FRAME_STATE_ATOMIC_TYPES):
            try:
                snapshot = copy.deepcopy(value)
            except Exception:
                # Not everything is deepcopy-able (locks, sockets, file handles,
                # or containers hiding one of those). Fall back to identity-only
                # comparison instead of letting this escape the trace callback.
                snapshot = None
                copy_failed = True

        return {
            "ref": value,
            "copy": snapshot,
            "copy_failed": copy_failed,
        }

    def _get_current_value(self, frame, domain, varName):
        if domain == LOCAL or domain == ENCLOSING:
            return frame.f_locals.get(varName)

        if domain == GLOBAL:
            return frame.f_globals.get(varName)

        return None

    def _safe_repr(self, value):
        try:
            return repr(value)
        except Exception:
            return "<unrepresentable>"

    def get_snapshot(self, state):
        if state is None:
            return None

        if state["copy"] is None:
            if state["copy_failed"]:
                # The reference itself could not be deepcopy'd, so it is not
                # safe to hand out raw (e.g. a lock reaching HistoryBuffer /
                # json.dumps). Fall back to a JSON-serializable placeholder.
                return self._safe_repr(state["ref"])

            return state["ref"]

        # Do not expose the stored mutable snapshot directly to callers.
        try:
            return copy.deepcopy(state["copy"])
        except Exception:
            # The initial deepcopy in _make_state() succeeded, but the copy it
            # produced is itself uncopyable (e.g. __deepcopy__ hands back a
            # lock). Demote state in place so future check() calls fall back
            # to identity-only comparison instead of retrying this deepcopy
            # and raising again on every subsequent line event. This is safe
            # because get_snapshot() has exactly one production caller
            # (TraceDispatcher._log_event), which always receives the same
            # dict object already stored by _check_and_log, so the demotion
            # is observed by later check() calls on that state.
            state["copy"] = None
            state["copy_failed"] = True
            return self._safe_repr(state["ref"])

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

        # previous_copy is None means either: the value is atomic (no snapshot
        # was ever needed, safe to compare by identity), or a deepcopy failed
        # and the state was demoted to identity-only comparison. In the
        # demoted case the value may still be genuinely mutable, so an
        # in-place mutation with no reassignment will not be detected here.
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