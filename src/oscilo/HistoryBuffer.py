import copy

class HistoryBuffer:
    _DOMAIN_LABELS = {
        0: "LOCAL",
        1: "GLOBAL",
    }
    _UNKNOWN_DOMAIN_LABEL = "UNKNOWN"

    def __init__(self):
        self._history = []

    def append(self, name, data, event, domain=None, line=None, func=None, call_id=None, parent_call_id=None, call_depth=None,):
        # Store a readable domain label so JSONL output is easy to inspect.
        history_entry = {
            "name": name,
            "data": data,
            "event": event,
            "domain": self._get_domain_label(domain),
            "line": line,
            "func": func,
            "call_id": call_id,
            "parent_call_id": parent_call_id,
            "call_depth": call_depth,
        }
        self._history.append(history_entry)

    def _get_domain_label(self, domain):
        # Use UNKNOWN when the resolved scope is not local or global.
        return self._DOMAIN_LABELS.get(domain, self._UNKNOWN_DOMAIN_LABEL)

    def getHistory(self):
        # Return a deep copy so callers cannot mutate the internal history.
        return copy.deepcopy(self._history)

    def clearBuffer(self):
        self._history.clear()