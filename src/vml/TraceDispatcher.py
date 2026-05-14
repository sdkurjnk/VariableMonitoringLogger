import sys

class TraceDispatcher:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(TraceDispatcher, cls).__new__(cls)
            cls._instance._trackers = []
            cls._instance._is_tracing = False
            cls._instance._bufferRef = None
        return cls._instance

    @classmethod
    def get_instance(cls):
        return cls()

    def setBuffer(self, buffer):
        self._buffer = buffer

    def register(self, tracker):
        self._trackers.append(tracker)
        if not self._is_tracing:
            sys.settrace(self._trace_calls)
            self._is_tracing = True

    def unregister(self, tracker):
        if tracker in self._trackers:
            self._trackers.remove(tracker)
        if not self._trackers and self._is_tracing:
            sys.settrace(None)
            self._is_tracing = False

    def _trace_calls(self, frame, event, arg):
        if event != 'call':
            return
        return self._trace_lines

    def _trace_lines(self, frame, event, arg):
        if event not in ('line', 'return'):
            return self._trace_lines

        for tracker in self._trackers:
            tracker.check(frame)

        return self._trace_lines
