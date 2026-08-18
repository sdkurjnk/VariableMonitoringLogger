import copy

try:
    from . import oscilo_engine
except ImportError:
    raise RuntimeError("oscilo_engine C extension is not found.")


LOCAL = 0
GLOBAL = 1
ENCLOSING = 2
BUILTIN = 3
NOT_FOUND = -1

INIT_EVENT = "init"
UPDATED_EVENT = "updated"
DELETED_EVENT = "deleted"
NOT_FOUND_EVENT = "not_found"
NO_CHANGE_EVENT = "no_change"
_SNAPSHOT_COPY_FAILED = "<uncopyable>"

_FRAME_STATE_ATOMIC_TYPES = (
    int,
    float,
    bool,
    complex,
    str,
    bytes,
    type(None),
)


class VariableTracker:
    def __init__(self, varName, domain=None):
        self.varName = varName
        self.domain = domain
        # 트래커가 자기 비교 상태를 스코프 인스턴스별로 소유한다.
        # key는 LOCAL=frame(재귀별 독립 timeline), ENCLOSING=id(cell)/frame, GLOBAL=고정 key.
        self._states = {}

    def _make_state(self, value):
        # atomic 값은 identity만으로 비교 가능하지만,
        # 컨테이너는 불변이어도 내부에 가변 객체를 담을 수 있어 분리된 스냅샷이 필요하다.
        snapshot = None
        copy_failed = False

        if not isinstance(value, _FRAME_STATE_ATOMIC_TYPES):
            try:
                snapshot = copy.deepcopy(value)
            except Exception:
                # 전부 deepcopy 되진 않는다(lock·socket·file handle 등).
                # 트레이스 콜백 밖으로 예외를 흘리지 말고 identity-only 비교로 폴백한다.
                snapshot = None
                copy_failed = True

        return {
            "ref": value,
            "copy": snapshot,
            "copy_failed": copy_failed,
        }

    def _get_current_value(self, frame, domain, varName):
        if domain == LOCAL or domain == ENCLOSING:
            return frame.f_locals.get(varName)

        if domain == GLOBAL:
            return frame.f_globals.get(varName)

        return None

    def get_snapshot(self, state):
        if state is None:
            return None

        if state["copy"] is None:
            if state["copy_failed"]:
                # 참조 자체를 복사 못 했으니 raw로 넘기면 위험하다(lock이 HistoryBuffer/json.dumps로).
                # JSON 직렬화 가능한 placeholder로 폴백.
                return _SNAPSHOT_COPY_FAILED

            return state["ref"]

        # 저장된 가변 스냅샷을 호출자에게 직접 노출하지 않는다.
        try:
            return copy.deepcopy(state["copy"])
        except Exception:
            # _make_state의 deepcopy는 성공했지만, 그 사본이 다시 복사 불가한
            # 경우다(예: __deepcopy__가 lock 반환).
            # 이후 line 이벤트마다 재시도·예외가 나지 않도록,
            # state를 그 자리에서 identity-only로 강등한다.
            # get_snapshot의 유일한 프로덕션 호출자(_log_event)는
            # check_owned가 self._states에 저장한 같은 dict를 받으므로,
            # 강등이 이후 check_owned 호출에 반영된다.
            state["copy"] = None
            state["copy_failed"] = True
            return _SNAPSHOT_COPY_FAILED

    def check(self, frame, domain, varName=None, prev_state=None):
        # 넘겨준 prev_state로 하는 무상태 평가.
        # dispatcher는 이제 상태를 소유·저장하는 check_owned로 추적하고, 이 메서드는 일회성 검사·테스트용 순수 헬퍼로 남는다.
        return self._evaluate(frame, domain, varName, prev_state)

    def check_owned(self, frame, domain, key):
        # dispatcher는 "이 인스턴스 검사해"만 한다.
        # 트래커가 key(LOCAL이면 frame)로 자기 상태를 조회·저장한다.
        prev_state = self._states.get(key)
        event_name, new_state = self._evaluate(frame, domain, self.varName, prev_state)

        if new_state is None:
            self._states.pop(key, None)
        else:
            self._states[key] = new_state

        return event_name, new_state

    def forget(self, key):
        # 한 스코프 인스턴스(예: return하는 frame)의 상태를 버린다.
        self._states.pop(key, None)

    def reset(self):
        self._states.clear()

    def _evaluate(
        self,
        frame,
        domain,
        varName=None,
        prev_state=None,
    ):
        if varName is None:
            varName = self.varName

        if domain == NOT_FOUND or domain == BUILTIN:
            if prev_state is None:
                return NOT_FOUND_EVENT, None

            return DELETED_EVENT, None

        self.domain = domain
        current_value = self._get_current_value(
            frame,
            domain,
            varName,
        )

        if prev_state is None:
            return INIT_EVENT, self._make_state(current_value)

        previous_ref = prev_state["ref"]
        previous_copy = prev_state["copy"]

        # previous_copy가 None인 경우: atomic이라 스냅샷이 필요 없었거나 (identity 비교 안전), deepcopy 실패로 identity-only로 강등된 경우.
        # 후자는 값이 실제로 가변일 수 있어, 재할당 없는 제자리 변경은 못 잡는다.
        if previous_copy is None:
            if current_value is previous_ref:
                return NO_CHANGE_EVENT, prev_state

            return UPDATED_EVENT, self._make_state(current_value)

        result = oscilo_engine.check_variable(
            frame,
            previous_ref,
            previous_copy,
            domain,
            varName,
        )

        if result is None:
            return DELETED_EVENT, None

        if result is False:
            return NO_CHANGE_EVENT, prev_state

        return UPDATED_EVENT, self._make_state(current_value)