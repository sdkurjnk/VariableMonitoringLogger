import atexit
import sys

from .FileWriter import FileWriter
from .HistoryBuffer import HistoryBuffer
from .TraceDispatcher import TraceDispatcher


class _Oscilo:
    def __init__(self, fileName="oscilo.jsonl"):
        self.fileName = fileName
        self.buffer = HistoryBuffer()
        self.dispatcher = TraceDispatcher(self.buffer)
        self.fileWriter = FileWriter()
        self._saved = False

        # Register a final save so logs are written even without manual cleanup.
        atexit.register(self.finalSave)

    def register(self, varName, frame=None):
        # Pass the caller's frame so the dispatcher can resolve the variable.
        if frame is None:
            frame = sys._getframe(1)

        self.dispatcher.register(varName, frame=frame)

    def finalSave(self):
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
        history = self.buffer.getHistory()

        # Skip the write entirely so runs without recorded events leave no file behind.
        if not history:
            return

        self.fileWriter.write(self.fileName, history)
