import sys

from .CallContext import CallContextManager
from .ScopeResolver import ScopeResolver
from .VariableTracker import VariableTracker

LOCAL = 0
GLOBAL = 1
ENCLOSING = 2
BUILTIN = 3
TRACKABLE_DOMAINS = (LOCAL, GLOBAL, ENCLOSING)
BUFFERED_EVENTS = ("init", "updated", "deleted")
DELETED_EVENT = "deleted"

# "이 frame에 대해 cell 해석을 아직 시도하지 않음"과 "시도했지만 휴리스틱이
# cell을 찾지 못함"(진짜 None)을 구분하기 위한 sentinel.
_UNRESOLVED = object()

class TraceDispatcher:
    class _ClosureResolver:
        """free variable을 뒷받침하는 실제 closure `cell` 객체를 해석한다.

        `sys.settrace`의 콜백은 항상 frame 객체만 넘겨주며, 맨 frame만으로는
        어떤 공식 Python/C API로도 closure cell을 노출시킬 방법이 없다
        (실측 확인: `frame.f_locals`, `gc.get_referents(frame)`, 그리고 안정
        C-API인 `PyFrame_GetVar`조차 전부 *역참조된 값*만 반환하고 cell 자체는
        반환하지 않는다). cell은 오직 function 객체의 `__closure__`를 통해서만
        접근 가능하므로, 이 resolver는 직접 호출자(caller)의 frame
        (`frame.f_back`)에서 다음 조건을 만족하는 콜러블을 찾는다: (a) 추적 중인
        frame과 같은 code 객체를 쓰고, (b) 해당 인덱스의 closure cell이 현재
        추적 중인 frame의 실제 값과 일치한다.

        이것은 보장이 아니라 휴리스틱이다. 호출 시점에 caller의 locals/globals
        안에서 평범한 이름으로 접근 가능하지 않았던 콜러블(예: `outer()()`처럼
        이름에 바인딩되지 않은 즉시 호출, 또는 속성/딕셔너리 접근을 통해 호출된
        콜백)은 cell을 해석하지 못한다. `resolve`를 호출하는 쪽은 `None`을
        "소유권을 판단할 수 없음"으로 취급하고 그에 맞게 fallback해야 한다.
        """

        def resolve(self, frame, var_name):
            code = frame.f_code

            if var_name not in code.co_freevars:
                return None

            index = code.co_freevars.index(var_name)
            caller = frame.f_back

            if caller is None:
                return None

            current_value = frame.f_locals.get(var_name)
            candidates = list(caller.f_locals.values()) + list(caller.f_globals.values())

            for candidate in candidates:
                cell = self._match_candidate(candidate, code, index, current_value)
                if cell is not None:
                    return cell

            return None

        def _match_candidate(self, candidate, code, index, current_value):
            # `self.method` 형태의 콜백도 처리할 수 있도록 bound method를 풀어낸다.
            func = getattr(candidate, "__func__", candidate)

            if getattr(func, "__code__", None) is not code:
                return None

            closure = getattr(func, "__closure__", None)
            if not closure or len(closure) <= index:
                return None

            cell = closure[index]

            # 같은 code 객체를 공유하는 서로 다른 여러 closure가 caller의
            # namespace에 함께 존재할 수 있다(예: 서로 다른 이름으로 저장된
            # 두 개의 별도 `outer()` 결과). cell이 현재 추적 중인 frame이
            # 실행 중인 바로 그 객체를 담고 있는지 확인해서 구분한다.
            try:
                cell_value = cell.cell_contents
            except ValueError:
                # cell이 아직 바인딩되지 않음(드문 타이밍 엣지 케이스); 일치 여부를 확인할 수 없다.
                return None

            if cell_value is not current_value:
                return None

            return cell

    def __init__(self, buffer=None):
        self._trackers = []
        self._is_tracing = False
        self._bufferRef = buffer
        self._resolver = ScopeResolver()
        self._context_manager = CallContextManager()
        self._closure_resolver = self._ClosureResolver()

        # "이 code 객체에 어떤 tracker가 관련 있는지"를 frame.f_code로 키를
        # 잡아 캐싱해서, 무관한 frame은 line tracing을 아예 건너뛸 수 있게 한다.
        self._frame_cache = {}

        # 각 tracker의 등록 시점 scope identity를 tracker나 살아있는 frame
        # 참조가 아니라 dispatcher 쪽에 보관해서, tracker가 등록될 때의 정확한
        # function/module에만 적용되도록 한다.
        self._tracker_codes = {}
        self._tracker_globals = {}

        # 같은 변수/scope를 두 번(예: 재귀 호출마다) 등록해도 기존 tracker를
        # 재사용하고 호출마다 새로 늘어나지 않도록 하는 중복 제거 키.
        self._registered_local = {}
        self._registered_global = {}

        # GLOBAL 변수는 그것을 관찰하는 모든 frame이 공유하는 단일 timeline을
        # 가지므로, 이전 상태는 어느 한 frame의 state가 아니라 여기에 산다.
        self._global_states = {}

        # GLOBAL 변수는 이후 다른 call frame에서 변경이 일어나도, 처음
        # 등록됐던 frame의 ID를 계속 유지한다.
        self._global_var_ids = {}

        # frame 객체 자체를 key로 하는, 활성 frame별 local/enclosing state.
        # 해당 frame의 return 이벤트에서 항목이 제거되고 stop()에서 dict
        # 전체가 비워지므로, 여기 있는 어떤 것도 frame보다 오래 살아남지 않는다.
        self._frame_states = {}

        # ENCLOSING(nonlocal/freevar) 변수는 어느 한 call frame이 아니라
        # closure cell이 소유하므로, 그 identity와 값 이력은 소유 frame의
        # return 이후에도 살아남아야 한다(closure는 자신을 만든 함수가
        # 반환된 지 한참 후에도 호출될 수 있다). `cell` 객체는 해시 불가능
        # 하므로 아래 세 dict는 모두 id(cell)을 key로 쓴다; _enclosing_cell_refs는
        # 각 cell에 대한 strong reference를 붙잡아 둬서, 추적이 활성화된 동안
        # 그 id가 다른 무관한 객체에 재사용되지 않게 한다. GLOBAL 저장소와
        # 마찬가지로 stop()에서 비워진다.
        self._enclosing_var_ids = {}
        self._enclosing_states = {}
        self._enclosing_cell_refs = {}

        # "이 frame에서 이 ENCLOSING 변수를 뒷받침하는 cell이 무엇인지"를
        # frame으로 키를 잡아 캐싱해서, _ClosureResolver의 caller-frame
        # 휴리스틱이 추적된 line마다가 아니라 호출마다 한 번만 실행되게 한다.
        # 해당 frame의 return 이벤트에서 항목이 제거되고 stop()에서 비워진다.
        # 해석 결과가 None인 경우도 캐싱해서(휴리스틱이 정말로 이 frame에 대한
        # cell을 찾지 못한 경우), "아직 시도 안 함"과 "시도했지만 찾지 못함"을
        # sentinel로 구분한다.
        self._frame_cell_cache = {}

        # 특정 ENCLOSING tracker에 대해 지금까지 해석된 모든 cell을 기록해서,
        # unregister()가 _enclosing_var_ids / _enclosing_states에 새어나가게
        # 두지 않고 그 tracker가 소유한 상태만 정확히 정리할 수 있게 한다.
        self._tracker_cells = {}

    def setBuffer(self, buffer):
        self._bufferRef = buffer

    def _is_local_name(self, frame, varName):
        code = frame.f_code
        return (
            varName in code.co_varnames
            or varName in code.co_cellvars
            or varName in code.co_freevars
        )

    def _is_enclosing_case(self, domain, tracker):
        if domain == ENCLOSING:
            return True

        # 삭제됐거나 더 이상 해석 불가능한 nonlocal이라도 frame_state가 아니라
        # cell-keyed 저장소에서 정리돼야 한다. 그렇지 않으면 DELETED_EVENT가
        # 엉뚱한 저장소를 조회해서 아예 발생하지 않게 된다.
        return domain not in TRACKABLE_DOMAINS and tracker.domain == ENCLOSING

    def _resolve_cell_key_cached(self, frame, varName):
        cached = self._frame_cell_cache.get(frame, _UNRESOLVED)
        if cached is not _UNRESOLVED:
            return cached

        cell = self._closure_resolver.resolve(frame, varName)
        cell_key = None

        if cell is not None:
            cell_key = id(cell)
            # id로 참조하는 동안에는 cell을 계속 살려둬야 한다. 그러지 않으면
            # 나중에 무관한 객체가 같은 주소에 할당될 수 있다.
            self._enclosing_cell_refs[cell_key] = cell

        self._frame_cell_cache[frame] = cell_key
        return cell_key

    def _get_enclosing_var_id(self, cell_key):
        var_id = self._enclosing_var_ids.get(cell_key)
        if var_id is None:
            var_id = self._context_manager.next_id()
            self._enclosing_var_ids[cell_key] = var_id

        return var_id

    def _record_tracker_cell(self, tracker, cell_key):
        if cell_key is None:
            return

        self._tracker_cells.setdefault(tracker, set()).add(cell_key)

    def _check_and_log_enclosing(self, frame, tracker, varName):
        cell_key = self._resolve_cell_key_cached(frame, varName)
        self._record_tracker_cell(tracker, cell_key)

        # cell을 해석하지 못한 경우(caller-frame 휴리스틱이 소유 closure를
        # 찾지 못함)는 기존과 동일하게 frame별 state로 fallback한다: 변수는
        # 여전히 추적되지만 호출 간에 안정적인 identity를 갖지 못하고, var_id는
        # 현재 call_id로 강등된다(_log_event에서 처리).
        storage_key = cell_key if cell_key is not None else frame

        return self._check_and_log(
            frame,
            tracker,
            self._enclosing_states,
            storage_key,
            ENCLOSING,
            cell=cell_key,
        )

    def register(self, varName, frame):
        if frame is None:
            raise ValueError("frame is required to register a variable tracker")

        resolved_domain, _ = self._resolver.resolve(frame, varName)
        is_local = self._is_local_name(frame, varName)

        if is_local:
            dedup_key = (varName, frame.f_code)
            tracker = self._registered_local.get(dedup_key)
        else:
            dedup_key = (varName, id(frame.f_globals))
            tracker = self._registered_global.get(dedup_key)

        is_new_tracker = tracker is None

        if is_new_tracker:
            tracker = VariableTracker(varName, domain=resolved_domain)
            self._trackers.append(tracker)

            if is_local:
                self._registered_local[dedup_key] = tracker
                self._tracker_codes[tracker] = frame.f_code
            else:
                self._registered_global[dedup_key] = tracker
                self._tracker_globals[tracker] = frame.f_globals

                context = self._context_manager.ensure_context(frame)
                self._global_var_ids[tracker] = self._get_context_call_id(context)

            # 새 tracker가 추가되면 어떤 code 객체에 어떤 tracker가 적용되는지가
            # 바뀔 수 있으므로, relevance 캐시를 더 이상 신뢰할 수 없다.
            self._frame_cache.clear()

        # 첫 tracker가 등록되는 시점에 전역 tracing을 시작한다.
        self._start_tracing()

        # 등록 frame의 "call" 이벤트는 이 tracker가 생기기 전에 이미 발생했으므로,
        # line tracing을 여기서 명시적으로 붙여야 한다(또는 이전 등록/호출에서
        # 이미 붙어 있다면 그것을 재사용한다).
        frame_state = self._ensure_frame_tracking(frame)
        self._ensure_active_ancestor_tracking(frame, is_new_tracker)

        if self._is_enclosing_case(resolved_domain, tracker):
            self._check_and_log_enclosing(frame, tracker, varName)
        elif is_local:
            self._check_and_log(frame, tracker, frame_state, varName, resolved_domain)
        else:
            self._check_and_log(frame, tracker, self._global_states, tracker, resolved_domain)

        return tracker

    def unregister(self, tracker):
        if tracker in self._trackers:
            self._trackers.remove(tracker)

        code = self._tracker_codes.pop(tracker, None)
        if code is not None:
            self._registered_local.pop((tracker.varName, code), None)

        globals_dict = self._tracker_globals.pop(tracker, None)
        if globals_dict is not None:
            self._registered_global.pop((tracker.varName, id(globals_dict)), None)

        self._global_states.pop(tracker, None)
        self._global_var_ids.pop(tracker, None)

        cell_keys = self._tracker_cells.pop(tracker, None)
        if cell_keys:
            for cell_key in cell_keys:
                self._enclosing_var_ids.pop(cell_key, None)
                self._enclosing_states.pop(cell_key, None)
                self._enclosing_cell_refs.pop(cell_key, None)

        self._frame_cache.clear()

        if not self._trackers:
            self._stop_tracing()

    def stop(self):
        self._trackers.clear()
        self._stop_tracing()

    def _start_tracing(self):
        if self._is_tracing:
            return

        sys.settrace(self._trace_calls)
        self._is_tracing = True

    def _stop_tracing(self):
        if not self._is_tracing:
            return

        sys.settrace(None)
        self._is_tracing = False
        self._frame_cache.clear()
        self._frame_states.clear()
        self._tracker_codes.clear()
        self._tracker_globals.clear()
        self._registered_local.clear()
        self._registered_global.clear()
        self._global_states.clear()
        self._global_var_ids.clear()
        self._enclosing_var_ids.clear()
        self._enclosing_states.clear()
        self._enclosing_cell_refs.clear()
        self._frame_cell_cache.clear()
        self._tracker_cells.clear()
        self._context_manager.clear()

    def _append_buffer_event(self, varName, var_id, data, event_name, domain, line, func=None, call_id=None, parent_call_id=None, call_depth=None):
        if self._bufferRef is None:
            return

        self._bufferRef.append(varName, var_id, data, event_name, domain, line, func, call_id, parent_call_id, call_depth, )

    def _get_frame_line(self, frame):
        if frame is None:
            return None

        return frame.f_lineno

    def _get_frame_func(self, frame):
        if frame is None:
            return None

        return frame.f_code.co_name

    def _get_context_call_id(self, context):
        if context is None:
            return None

        return context["call_id"]

    def _get_context_parent_call_id(self, context):
        if context is None:
            return None

        return context["parent_call_id"]

    def _get_context_call_depth(self, context):
        if context is None:
            return None

        return context["call_depth"]

    def _get_logged_domain(self, tracker, event_name, resolved_domain):
        # Preserve the previous scope when deletion makes the variable unresolvable.
        domain = resolved_domain
        if event_name == DELETED_EVENT and resolved_domain not in TRACKABLE_DOMAINS:
            domain = tracker.domain

        # ENCLOSING is only an internal LEGB classification used to route
        # cell-based state/var_id resolution; the variable still lives in
        # (and is owned by) a LOCAL frame from the log's point of view, so
        # it is always reported as LOCAL, never ENCLOSING.
        if domain == ENCLOSING:
            return LOCAL

        return domain
    
    def _log_event(self, frame, tracker, event_name, new_state, domain, cell=None):
        context = self._context_manager.ensure_context(frame)
        call_id = self._get_context_call_id(context)

        if domain == ENCLOSING and cell is not None:
            # var_id는 값을 소유한 closure cell을 식별하고, call_id는 항상 이
            # 변경이 관측된 frame을 가리킨다. 그래서 ENCLOSING 변수에 한해
            # 이 둘은 의도적으로 서로 달라진다.
            var_id = self._get_enclosing_var_id(cell)
        elif tracker in self._global_var_ids:
            var_id = self._global_var_ids[tracker]
        else:
            var_id = call_id

        self._append_buffer_event(
            tracker.varName,
            var_id,
            tracker.get_snapshot(new_state),
            event_name,
            self._get_logged_domain(tracker, event_name, domain),
            self._get_frame_line(frame),
            self._get_frame_func(frame),
            call_id,
            self._get_context_parent_call_id(context),
            self._get_context_call_depth(context),
        )

    def _check_and_log(self, frame, tracker, storage, key, domain, cell=None):
        prev_state = storage.get(key)
        event_name, new_state = tracker.check(frame, domain, tracker.varName, prev_state)

        if new_state is None:
            storage.pop(key, None)
        else:
            storage[key] = new_state

        if event_name in BUFFERED_EVENTS:
            self._log_event(frame, tracker, event_name, new_state, domain, cell=cell)

        return event_name, new_state

    def _get_cache_entry(self, frame):
        code = frame.f_code
        entry = self._frame_cache.get(code)
        if entry is not None:
            return entry

        names = set(code.co_varnames) | set(code.co_cellvars) | set(code.co_freevars)
        local_candidates = [tracker for tracker in self._trackers if tracker.varName in names]
        global_candidates = [tracker for tracker in self._trackers if tracker.varName not in names]

        entry = (local_candidates, global_candidates)
        self._frame_cache[code] = entry
        return entry

    def _relevant_for(self, frame):
        local_candidates, global_candidates = self._get_cache_entry(frame)

        local_relevant = [
            tracker for tracker in local_candidates
            if self._tracker_codes.get(tracker) is frame.f_code
    ]

        global_relevant = [
            tracker for tracker in global_candidates
            if self._tracker_globals.get(tracker) is frame.f_globals
        ]

        return local_relevant, global_relevant

    def _process_frame(self, frame, frame_state):
        local_relevant, global_relevant = self._relevant_for(frame)

        for tracker in local_relevant:
            domain, _ = self._resolver.resolve(frame, tracker.varName)

            if self._is_enclosing_case(domain, tracker):
                self._check_and_log_enclosing(frame, tracker, tracker.varName)
            else:
                self._check_and_log(frame, tracker, frame_state, tracker.varName, domain)

        for tracker in global_relevant:
            domain, _ = self._resolver.resolve(frame, tracker.varName)
            self._check_and_log(frame, tracker, self._global_states, tracker, domain)

    def _make_line_tracer(self, frame_state):
        def trace_lines(current_frame, current_event, current_arg):
            if current_event not in ("line", "return"):
                return trace_lines

            self._process_frame(current_frame, frame_state)

            if current_event == "return":
                self._context_manager.on_return(current_frame)
                self._frame_states.pop(current_frame, None)
                self._frame_cell_cache.pop(current_frame, None)
                return None

            return trace_lines

        return trace_lines

    def _ensure_frame_tracking(self, frame):
        frame_state = self._frame_states.get(frame)
        if frame_state is not None:
            return frame_state

        frame_state = {}
        self._frame_states[frame] = frame_state
        frame.f_trace = self._make_line_tracer(frame_state)
        return frame_state

    def _ensure_active_ancestor_tracking(self, frame, is_new_tracker):
        current_frame = frame.f_back

        while current_frame is not None:
            # dedup 등록(기존 tracker 재사용)일 때, 이미 _frame_states에 있는 조상을
            # 만나면 그 지점에서 멈춘다. 그 조상은 이전 등록에서 이미 f_trace가
            # 붙었고, 이후 라인마다 relevance를 새로 계산하므로(frame_cache가 그
            # 사이 무효화되지 않는 한) 그 위 체인도 이미 처리된 것이 보장된다.
            # 새 tracker가 생기는 경우는 relevance 후보 자체가 바뀔 수 있으므로
            # 이 조기 종료를 적용하지 않는다.
            if not is_new_tracker and current_frame in self._frame_states:
                break

            local_relevant, global_relevant = self._relevant_for(
                current_frame
            )

            if local_relevant or global_relevant:
                self._ensure_frame_tracking(current_frame)

            # <module> frame은 이 실행 단위(파일, exec() 호출, Jupyter 셀 등)의
            # 최상단이다. 여기서 멈추지 않으면, 같은 globals dict를 재사용하는
            # 무관한 실행 단위(중첩 exec, 노트북 셀 러너 등)나 이 파일을 호출한
            # 인터프리터/테스트 러너 frame까지 조상으로 착각해 추적을 붙이게 된다.
            if current_frame.f_code.co_name == "<module>":
                break

            current_frame = current_frame.f_back

    def _trace_calls(self, frame, event, arg):
        if event != "call":
            return None

        local_relevant, global_relevant = self._relevant_for(frame)
        if not local_relevant and not global_relevant:
            return None

        self._ensure_frame_tracking(frame)
        return frame.f_trace