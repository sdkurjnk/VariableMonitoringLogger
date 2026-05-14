import sys
import atexit
from HistoryBuffer import HistoryBuffer
from TraceDispatcher import TraceDispatcher
from VariableTracker import VariableTracker
from FileWriter import FileWriter

class VML:
    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(VML, cls).__new__(cls)
            cls._instance._isInitialized = False
        return cls._instance

    def __init__(self, fileName="vml_log.json"):
        if self._isInitialized:
            return

        self.fileName = fileName
        self.buffer = HistoryBuffer()       
        self._isInitialized = True

        self.dispatcher = TraceDispatcher(self.buffer)
        self.dispatcher.start()             

        self.fileWriter = FileWriter()      
        atexit.register(self._finalSave)

    def logger(self, varName):
        tracker = VariableTracker(varName)
        self.dispatcher.register(tracker)

    def _finalSave(self):
        self.fileWriter.write(self.fileName, self.buffer)