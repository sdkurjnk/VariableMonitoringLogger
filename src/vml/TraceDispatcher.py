import sys
from .ScopeResolver import ScopeResolver
from .VariableTracker import VariableTracker

class TraceDispatcher:
    def __init__(self, buffer = None):
        self._trackers = []
        self._is_tracing = False
        self._bufferRef = buffer
        self._resolver = ScopeResolver()

    def setBuffer(self, buffer):
        self._bufferRef = buffer

    def register(self, varName, domain=None, value=None, frame=None):
        tracker = VariableTracker(
            varName,
            domain=domain,
            value=value,
            exists=domain in (0, 1),
            frame=frame
        )
        self._trackers.append(tracker)

        if domain in (0, 1) and self._bufferRef is not None:
            self._bufferRef.append(varName, tracker.get_snapshot(), "init", domain, frame.f_lineno if frame is not None else None)

        if not self._is_tracing:
            sys.settrace(self._trace_calls)
            self._is_tracing = True

        if frame is not None:
            frame.f_trace = self._trace_lines

        return tracker

    def unregister(self, tracker):
        if tracker in self._trackers:
            self._trackers.remove(tracker)
        if not self._trackers and self._is_tracing:
            sys.settrace(None)
            self._is_tracing = False

    def stop(self):
        self._trackers.clear()
        if self._is_tracing:
            sys.settrace(None)
            self._is_tracing = False

    def _trace_calls(self, frame, event, arg):
        if event != 'call':
            return
        return self._trace_lines

    def _trace_lines(self, frame, event, arg):
        if event not in ('line', 'return'):
            return self._trace_lines

        for tracker in list(self._trackers):
            if tracker.domain == 0 and tracker.frame is not None and frame is not tracker.frame:
                continue
            if tracker.domain == 1 and tracker.frame is not None and frame.f_globals is not tracker.frame.f_globals:
                continue

            domain, _ = self._resolver.resolve(frame, tracker.varName)
            event_name = tracker.check(frame, domain, tracker.varName)

            if event_name in ("init", "updated", "deleted") and self._bufferRef is not None:
                data = None if event_name == "deleted" else tracker.get_snapshot()
                logged_domain = tracker.domain if event_name == "deleted" and domain not in (0, 1) else domain
                self._bufferRef.append(tracker.varName, data, event_name, logged_domain, frame.f_lineno)

        return self._trace_lines