class HistoryBuffer:
    def __init__(self):
        self._history = []

    _DOMAIN_LABELS = {0: "LOCAL", 1: "GLOBAL"}

    def append(self, name, data, event, domain, line):
        self._history.append({"name" : name, "data" : data, "event" : event, "domain" : self._DOMAIN_LABELS.get(domain, domain), "line" : line})

    def getHistory(self):
        return self._history.copy()

    def clearBuffer(self):
        self._history.clear()