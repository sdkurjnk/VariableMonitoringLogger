import copy

try:
    from . import vml_engine
except ImportError:
    import vml_engine

LOCAL = 0
GLOBAL = 1

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
        try:
            return copy.deepcopy(value)
        except Exception:
            return repr(value)

    def _store(self, value):
        snapshot = self._make_snapshot(value)
        self._lastRef = value
        self._lastCopy = snapshot
        self._lastSnapshot = snapshot

    def get_snapshot(self):
        return self._make_snapshot(self._lastSnapshot)

    def check(self, frame, domain, varName=None):
        if varName is None:
            varName = self.varName

        if domain == -1:
            if self._isActive:
                self._lastRef = None
                self._lastCopy = None
                self._lastSnapshot = None
                self._isActive = False
                return "deleted"
            return "not_found"

        self.domain = domain

        if domain == LOCAL:
            currentVal = frame.f_locals.get(varName)
        else:
            currentVal = frame.f_globals.get(varName)

        if not self._isActive:
            self._store(currentVal)
            self._isActive = True
            return "init"

        result = vml_engine.check_variable(
            frame,
            self._lastRef,
            self._lastCopy,
            domain,
            varName
        )

        if result is None:
            if self._isActive:
                self._lastRef = None
                self._lastCopy = None
                self._lastSnapshot = None
                self._isActive = False
                return "deleted"
            return "not_found"

        if result is False:
            return "no_change"

        self._store(currentVal)
        return "updated"