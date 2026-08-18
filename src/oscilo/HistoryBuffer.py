import copy

class HistoryBuffer:
    _DOMAIN_LABELS = {
        0: "LOCAL",
        1: "GLOBAL",
        2: "ENCLOSING",
    }
    _UNKNOWN_DOMAIN_LABEL = "UNKNOWN"

    def __init__(self):
        self._history = []

    def append(self, name, var_id, data, event, domain=None, line=None, func=None, call_id=None, parent_call_id=None, call_depth=None,):
        # JSONL을 읽기 쉽게 domain을 라벨로 저장한다.
        history_entry = {
            "name": name,
            "var_id": var_id,
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
        # 매핑에 없는 domain은 UNKNOWN으로.
        return self._DOMAIN_LABELS.get(domain, self._UNKNOWN_DOMAIN_LABEL)

    def getHistory(self):
        # 호출자가 내부 이력을 변형 못 하도록 깊은 복사본을 반환한다.
        return copy.deepcopy(self._history)

    def clearBuffer(self):
        self._history.clear()