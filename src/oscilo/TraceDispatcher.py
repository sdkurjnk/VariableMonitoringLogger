import sys

from .CallContext import CallContextManager, is_suspended_return
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

# GLOBAL 변수는 관찰하는 모든 frame이 공유하는 단일 timeline을 가지므로,
# tracker는 이 고정 key 하나로 자기 GLOBAL 상태를 보관한다.
GLOBAL_STATE_KEY = object()

class TraceDispatcher:
    def __init__(self, buffer=None):
        self._trackers = []
        self._is_tracing = False
        self._bufferRef = buffer
        self._resolver = ScopeResolver()
        self._context_manager = CallContextManager()

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

        # GLOBAL 변수의 값 이력은 이제 tracker가 GLOBAL_STATE_KEY 하나로
        # 소유한다. dispatcher는 var_id만 관리하는데, GLOBAL 변수는 이후 다른
        # call frame에서 변경이 일어나도 처음 등록됐던 frame의 ID를 유지한다.
        self._global_var_ids = {}

        # frame 객체 자체를 key로 하는, 활성 frame별 local/enclosing state.
        # 해당 frame의 return 이벤트에서 항목이 제거되고 stop()에서 dict
        # 전체가 비워지므로, 여기 있는 어떤 것도 frame보다 오래 살아남지 않는다.
        self._frame_states = {}

        # ENCLOSING(nonlocal/freevar) 변수의 값 이력은 이제 tracker가 소유하되,
        # 아래 두 dict는 dispatcher가 계속 관리한다. cell이 소유한 identity와
        # 이력은 소유 frame의 return 이후에도 살아남아야 하므로(closure는 자신을
        # 만든 함수가 반환된 지 한참 후에도 호출될 수 있다), `cell` 객체는 해시
        # 불가능하므로 아래 dict는 id(cell)을 key로 쓴다; _enclosing_cell_refs는
        # 각 cell에 대한 strong reference를 붙잡아 둬서, 추적이 활성화된 동안
        # 그 id가 다른 무관한 객체에 재사용되지 않게 한다. GLOBAL 저장소와
        # 마찬가지로 stop()에서 비워진다.
        self._enclosing_var_ids = {}
        self._enclosing_cell_refs = {}

        # "이 frame에서 이 ENCLOSING 변수를 뒷받침하는 cell이 무엇인지"를
        # frame으로 키를 잡아 캐싱해서, ScopeResolver.resolve_cell의 caller-frame
        # 휴리스틱이 추적된 line마다가 아니라 호출마다 한 번만 실행되게 한다.
        # 해당 frame의 return 이벤트에서 항목이 제거되고 stop()에서 비워진다.
        # 해석 결과가 None인 경우도 캐싱해서(휴리스틱이 정말로 이 frame에 대한
        # cell을 찾지 못한 경우), "아직 시도 안 함"과 "시도했지만 찾지 못함"을
        # sentinel로 구분한다.
        self._frame_cell_cache = {}

        # 특정 ENCLOSING tracker에 대해 지금까지 해석된 모든 cell을 기록해서,
        # unregister()가 _enclosing_var_ids / _enclosing_cell_refs에 새어나가게
        # 두지 않고 그 tracker가 소유한 cell만 정확히 정리할 수 있게 한다.
        self._tracker_cells = {}

    def setBuffer(self, buffer):
        self._bufferRef = buffer

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

        cell = self._resolver.resolve_cell(frame, varName)
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

    def _guarded_check_and_log(self, fn, *args, **kwargs):
        # 추적 대상 값의 __eq__/__ne__(네이티브 비교 엔진 내부에서 호출됨)나
        # check-and-log 도중의 다른 내부 실패가 관찰 대상 프로그램으로 절대
        # 전파되면 안 된다. 전파되려 하면 그 tracker/이벤트 하나로만 격리해서
        # 다른 tracker와 이후 이벤트는 계속 정상 동작하게 한다. 이슈 #52 참고.
        try:
            return fn(*args, **kwargs)
        except Exception:
            return None

    def _check_and_log_enclosing(self, frame, tracker, varName):
        cell_key = self._resolve_cell_key_cached(frame, varName)

        # unregister 정리를 위해 이 tracker가 건드린 cell을 기록해 둔다.
        if cell_key is not None:
            self._tracker_cells.setdefault(tracker, set()).add(cell_key)

        # cell을 해석하지 못한 경우(caller-frame 휴리스틱이 소유 closure를
        # 찾지 못함)는 기존과 동일하게 frame별 state로 fallback한다: 변수는
        # 여전히 추적되지만 호출 간에 안정적인 identity를 갖지 못하고, var_id는
        # 현재 call_id로 강등된다(_log_event에서 처리).
        storage_key = cell_key if cell_key is not None else frame

        event_name, new_state = tracker.check_owned(frame, ENCLOSING, storage_key)

        if event_name in BUFFERED_EVENTS:
            self._log_event(frame, tracker, event_name, new_state, ENCLOSING, cell=cell_key)

        return event_name, new_state

    def register(self, varName, frame):
        if frame is None:
            raise ValueError("frame is required to register a variable tracker")

        resolved_domain, _ = self._resolver.resolve(frame, varName)

        code = frame.f_code
        is_local = (
            varName in code.co_varnames
            or varName in code.co_cellvars
            or varName in code.co_freevars
        )

        if is_local:
            dedup_key = (varName, code)
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
                self._global_var_ids[tracker] = context["call_id"]

            # 새 tracker가 추가되면 어떤 code 객체에 어떤 tracker가 적용되는지가
            # 바뀔 수 있으므로, relevance 캐시를 더 이상 신뢰할 수 없다.
            self._frame_cache.clear()

        # 첫 tracker가 등록되는 시점에 전역 tracing을 시작한다.
        self._start_tracing()

        # 등록 frame의 "call" 이벤트는 이 tracker가 생기기 전에 이미 발생했으므로,
        # line tracing을 여기서 명시적으로 붙여야 한다(또는 이전 등록/호출에서
        # 이미 붙어 있다면 그것을 재사용한다).
        self._ensure_frame_tracking(frame)
        self._ensure_active_ancestor_tracking(frame, is_new_tracker)

        if self._is_enclosing_case(resolved_domain, tracker):
            self._guarded_check_and_log(self._check_and_log_enclosing, frame, tracker, varName)
        elif is_local:
            self._guarded_check_and_log(
                self._check_and_log_local, frame, tracker, resolved_domain
            )
        else:
            self._guarded_check_and_log(
                self._check_and_log_global, frame, tracker, resolved_domain
            )

        return tracker

    def unregister(self, tracker):
        if tracker in self._trackers:
            self._trackers.remove(tracker)

        tracker.reset()

        code = self._tracker_codes.pop(tracker, None)
        if code is not None:
            self._registered_local.pop((tracker.varName, code), None)

        globals_dict = self._tracker_globals.pop(tracker, None)
        if globals_dict is not None:
            self._registered_global.pop((tracker.varName, id(globals_dict)), None)

        self._global_var_ids.pop(tracker, None)

        # The enclosing comparison state itself now lives in the tracker and is
        # dropped by tracker.reset() above; only the dispatcher-owned var_id and
        # cell strong-ref bookkeeping is purged here.
        cell_keys = self._tracker_cells.pop(tracker, None)
        if cell_keys:
            for cell_key in cell_keys:
                self._enclosing_var_ids.pop(cell_key, None)
                self._enclosing_cell_refs.pop(cell_key, None)

        self._frame_cache.clear()

        if not self._trackers:
            self._stop_tracing()

    def stop(self):
        for tracker in self._trackers:
            tracker.reset()
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
        self._global_var_ids.clear()
        self._enclosing_var_ids.clear()
        self._enclosing_cell_refs.clear()
        self._frame_cell_cache.clear()
        self._tracker_cells.clear()
        self._context_manager.clear()

    def _append_buffer_event(self, varName, var_id, data, event_name, domain, line, func=None, call_id=None, parent_call_id=None, call_depth=None):
        if self._bufferRef is None:
            return

        self._bufferRef.append(varName, var_id, data, event_name, domain, line, func, call_id, parent_call_id, call_depth, )

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
        # None-safe by construction: a None frame yields a None context, and both
        # `context or {}` / the frame guards below then report None fields.
        context = self._context_manager.ensure_context(frame) or {}
        call_id = context.get("call_id")

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
            frame.f_lineno if frame is not None else None,
            frame.f_code.co_name if frame is not None else None,
            call_id,
            context.get("parent_call_id"),
            context.get("call_depth"),
        )

    def _check_and_log_global(self, frame, tracker, domain):
        # GLOBAL variables share one timeline across every observing frame, so
        # the tracker owns a single state under GLOBAL_STATE_KEY.
        event_name, new_state = tracker.check_owned(frame, domain, GLOBAL_STATE_KEY)

        if event_name in BUFFERED_EVENTS:
            self._log_event(frame, tracker, event_name, new_state, domain)

        return event_name, new_state

    def _check_and_log_local(self, frame, tracker, domain):
        # LOCAL state is owned by the tracker and keyed by frame; the dispatcher
        # no longer holds the previous value, it just asks the tracker to check.
        event_name, new_state = tracker.check_owned(frame, domain, frame)

        if event_name in BUFFERED_EVENTS:
            self._log_event(frame, tracker, event_name, new_state, domain)

        return event_name, new_state

    def _forget_frame_local_states(self, frame):
        # LOCAL state is frame-keyed and dies with the frame, mirroring the old
        # _frame_states.pop(frame) on return. ENCLOSING state (cell-keyed, or the
        # frame-keyed fallback) must outlive the frame — a closure can be called
        # long after its defining frame returns — so enclosing trackers are
        # skipped here and cleared only on unregister/stop.
        local_relevant, _ = self._relevant_for(frame)
        for tracker in local_relevant:
            domain, _ = self._resolver.resolve(frame, tracker.varName)
            if not self._is_enclosing_case(domain, tracker):
                tracker.forget(frame)

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

    def _process_frame(self, frame):
        local_relevant, global_relevant = self._relevant_for(frame)

        for tracker in local_relevant:
            domain, _ = self._resolver.resolve(frame, tracker.varName)

            if self._is_enclosing_case(domain, tracker):
                self._guarded_check_and_log(
                    self._check_and_log_enclosing, frame, tracker, tracker.varName
                )
            else:
                self._guarded_check_and_log(
                    self._check_and_log_local, frame, tracker, domain
                )

        for tracker in global_relevant:
            domain, _ = self._resolver.resolve(frame, tracker.varName)
            self._guarded_check_and_log(
                self._check_and_log_global, frame, tracker, domain
            )

    def _make_line_tracer(self):
        def trace_lines(current_frame, current_event, current_arg):
            if current_event not in ("line", "return"):
                return trace_lines

            self._process_frame(current_frame)

            if current_event == "return":
                if is_suspended_return(current_frame):
                    return trace_lines

                self._context_manager.on_return(current_frame)
                self._forget_frame_local_states(current_frame)
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
        frame.f_trace = self._make_line_tracer()
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