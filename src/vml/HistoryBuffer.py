import copy

class HistoryBuffer:
    def __init__(self):
        self._history = []

    _DOMAIN_LABELS = {0: "LOCAL", 1: "GLOBAL"}
    _UNKOWN_DOMAIN_LABEL = "UNKNOWN"
    def append(self, name, data, event, domain=None, line=None):
        self._history.append({"name" : name, "data" : data, "event" : event, "domain" : self._DOMAIN_LABELS.get(domain, self._UNKOWN_DOMAIN_LABEL), "line" : line})

    def getHistory(self):
        return copy.deepcopy(self._history)

    def clearBuffer(self):
        self._history.clear()