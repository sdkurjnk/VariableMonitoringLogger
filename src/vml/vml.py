import sys
import atexit
from historyBuffer import HistoryBuffer
from traceDispatcher import TraceDispatcher
from variableTracker import VariableTracker
from fileWriter import FileWriter

class VML:
    _instance = None

    def __new__(cls, *args, **kwargs):
        
        if not cls._instance:
            cls._instance = super(VML, cls).__new__(cls)
            cls._instance._isInitialized = False
            cls._instance.buffer = HistoryBuffer()
        return cls._instance

    def __init__(self, fileName="vml_log.json"):
        if self._isInitialized:
            return
            
        self.fileName = fileName
        self._isInitialized = True

        self.dispatcher = TraceDispatcher(self.buffer)

        sys.settrace(self.dispatcher._traceCalls)
        atexit.register(self._finalSave)

    def logger(self, varName):
        
        tracker = VariableTracker(varName)
        self.dispatcher.register(tracker)

    def _finalSave(self):
        
        writer = FileWriter()
        writer.write(self.fileName, self.buffer)