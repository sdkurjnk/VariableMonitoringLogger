class HistoryBuffer:
    def __init__(self):
        self._history = []

    def append(self, name, data, event):
        self._history.append({"name" : name, "data" : data, "event" : event})

    def getHistory(self):
        return self._history.copy()

    def clearBuffer(self):
        self._history.clear()