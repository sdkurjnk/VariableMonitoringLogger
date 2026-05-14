class HistoryBuffer:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(HistoryBuffer, cls).__new__(cls)
            cls._instance._history = []
        return cls._instance

    def append(self, name, data, event):
        self._history.append({"name" : name, "data" : data, "event" : event})

    def getHistory(self):
        return self._history

    def clearBuffer(self):
        self._history.clear()
