import atexit
import sys

from .FileWriter import FileWriter
from .HistoryBuffer import HistoryBuffer
from .ScopeResolver import ScopeResolver
from .TraceDispatcher import TraceDispatcher


class _vmlog:
    def __init__(self, fileName="vmlog.jsonl"):
        self.fileName = fileName
        self.buffer = HistoryBuffer()
        self.dispatcher = TraceDispatcher(self.buffer)
        self.resolver = ScopeResolver()
        self.fileWriter = FileWriter()
        self._saved = False

        # Register a final save so logs are written even without manual cleanup.
        atexit.register(self._finalSave)

    def register(self, varName, frame=None):
        # Use the caller's frame by default so the requested variable can be resolved.
        if frame is None:
            frame = sys._getframe(1)

        domain, value = self.resolver.resolve(frame, varName)
        self.dispatcher.register(varName, domain, value, frame)

    def _finalSave(self):
        # Keep this method idempotent because it may be called manually and by atexit.
        if self._saved:
            return

        self._stop_tracking()
        self._write_history()
        self._saved = True

    def _stop_tracking(self):
        # Stop tracing before writing so no further events are recorded during save.
        self.dispatcher.stop()

    def _write_history(self):
        # Persist the collected history as JSONL through the configured writer.
        self.fileWriter.write(self.fileName, self.buffer.getHistory())