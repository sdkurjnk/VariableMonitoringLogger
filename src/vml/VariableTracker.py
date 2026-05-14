import copy
import vml_engine

LOCAL = 0
GLOBAL = 1

class VariableTracker:

    def __init__(self, varName):
        self.varName = varName
        self._lastRef = None
        self._lastCopy = None
        self._isActive = False

    def check(self, frame, domain, varName):

        result = vml_engine.check_variable(
            frame,
            self._lastRef,
            self._lastCopy,
            domain,           
            varName
        )

        if result is None:
            return "not_found"

        if result is False:
            return "no_change"

        if domain == LOCAL:
            currentVal = frame.f_locals.get(varName)
        else:
            currentVal = frame.f_globals.get(varName)

        if self._lastRef is None:
            event = "initialized"
        else:
            event = "ref_changed"  

        try:
            snapshot = copy.deepcopy(currentVal)
        except Exception:
            snapshot = repr(currentVal)

        self._lastRef = currentVal
        self._lastCopy = snapshot

        return event