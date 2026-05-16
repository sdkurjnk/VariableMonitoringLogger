import sys
import atexit
from .HistoryBuffer import HistoryBuffer
from .TraceDispatcher import TraceDispatcher
from .FileWriter import FileWriter
from .ScopeResolver import ScopeResolver

class VML:
    def __init__(self, fileName="vml_log.json"):
        self.fileName = fileName
        self.buffer = HistoryBuffer()

        self.dispatcher = TraceDispatcher()
        self.dispatcher.setBuffer(self.buffer)

        self.resolver = ScopeResolver()
        self.fileWriter = FileWriter()
        self._saved = False
        atexit.register(self._finalSave)

    def logger(self, varName, frame=None):
        if frame is None:
            frame = sys._getframe(1)

        domain, value = self.resolver.resolve(frame, varName)
        self.dispatcher.register(varName, domain, value, frame)
        return self

    def _finalSave(self):
        self._final_save()

    def _final_save(self):
        if self._saved:
            return
        self.dispatcher.stop()
        self.fileWriter.write(self.fileName, self.buffer.getHistory())
        self._saved = True


def logger(varName, filename="vml_log.json"):
    monitor = VML(filename)
    return monitor.logger(varName, sys._getframe(1))