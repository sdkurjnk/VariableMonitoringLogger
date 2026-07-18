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

class TraceDispatcher:
    def __init__(self, buffer=None):
        self._trackers = []
        self._is_tracing = False
        self._bufferRef = buffer
        self._resolver = ScopeResolver()
        self._context_manager = CallContextManager()

        # Cache of "which trackers matter for this code object", keyed by
        # frame.f_code so unrelated frames can skip line tracing entirely.
        self._frame_cache = {}

        # Registration-time scope identity for each tracker, kept on the
        # dispatcher (never on the tracker or as a live frame reference) so a
        # tracker only ever applies to the exact function or module it was
        # registered against.
        self._tracker_codes = {}
        self._tracker_globals = {}

        # Dedup keys so registering the same variable/scope twice (e.g. once
        # per recursive call) reuses the existing tracker instead of
        # proliferating one per call.
        self._registered_local = {}
        self._registered_global = {}

        # GLOBAL variables have a single timeline shared by every frame that
        # observes them, so their previous state lives here instead of in any
        # one frame's state.
        self._global_states = {}

        # Per-active-frame local/enclosing state, keyed by the frame object
        # itself. Entries are removed on that frame's return event and the
        # dict is cleared on stop(), so nothing here outlives the frame.
        self._frame_states = {}

    def setBuffer(self, buffer):
        self._bufferRef = buffer

    def _is_local_name(self, frame, varName):
        code = frame.f_code
        return (
            varName in code.co_varnames
            or varName in code.co_cellvars
            or varName in code.co_freevars
        )

    def register(self, varName, domain=None, value=None, frame=None):
        if frame is None:
            tracker = VariableTracker(varName, domain=domain)
            self._trackers.append(tracker)
            self._frame_cache.clear()
            self._start_tracing()
            return tracker

        resolved_domain, _ = self._resolver.resolve(frame, varName)
        is_local = self._is_local_name(frame, varName)

        if is_local:
            dedup_key = (varName, frame.f_code)
            tracker = self._registered_local.get(dedup_key)
        else:
            dedup_key = (varName, id(frame.f_globals))
            tracker = self._registered_global.get(dedup_key)

        if tracker is None:
            tracker = VariableTracker(varName, domain=resolved_domain)
            self._trackers.append(tracker)

            if is_local:
                self._registered_local[dedup_key] = tracker
                self._tracker_codes[tracker] = frame.f_code
            else:
                self._registered_global[dedup_key] = tracker
                self._tracker_globals[tracker] = frame.f_globals

            # A new tracker can change which trackers apply to any code
            # object, so the relevance cache can no longer be trusted.
            self._frame_cache.clear()

        # Start global tracing once the first tracker is registered.
        self._start_tracing()

        # The registration frame's "call" event already happened before this
        # tracker existed, so line tracing must be attached here explicitly
        # (or reused if already attached by an earlier registration/call).
        frame_state = self._ensure_frame_tracking(frame)

        if is_local:
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
        self._context_manager.clear()

    def _append_buffer_event(self, varName, data, event_name, domain, line, func=None, call_id=None, parent_call_id=None, call_depth=None):
        if self._bufferRef is None:
            return

        self._bufferRef.append(varName, data, event_name, domain, line, func, call_id, parent_call_id, call_depth, )

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
        if event_name == DELETED_EVENT and resolved_domain not in TRACKABLE_DOMAINS:
            return tracker.domain

        return resolved_domain

    def _log_event(self, frame, tracker, event_name, new_state, domain):
        # Only touch call-context bookkeeping when there is something to log.
        context = self._context_manager.ensure_context(frame)

        self._append_buffer_event(
            tracker.varName,
            tracker.get_snapshot(new_state),
            event_name,
            self._get_logged_domain(tracker, event_name, domain),
            self._get_frame_line(frame),
            self._get_frame_func(frame),
            self._get_context_call_id(context),
            self._get_context_parent_call_id(context),
            self._get_context_call_depth(context),
        )

    def _check_and_log(self, frame, tracker, storage, key, domain):
        prev_state = storage.get(key)
        event_name, new_state = tracker.check(frame, domain, tracker.varName, prev_state)

        if new_state is None:
            storage.pop(key, None)
        else:
            storage[key] = new_state

        if event_name in BUFFERED_EVENTS:
            self._log_event(frame, tracker, event_name, new_state, domain)

        return event_name, new_state

    def _get_cache_entry(self, frame):
        code = frame.f_code
        entry = self._frame_cache.get(code)
        if entry is not None:
            return entry

        names = set(code.co_varnames) | set(code.co_cellvars) | set(code.co_freevars)
        local_candidates = [tracker for tracker in self._trackers if tracker.varName in names]
        global_candidates = [tracker for tracker in self._trackers if tracker.varName not in names]

        entry = (local_candidates, global_candidates, frame.f_globals)
        self._frame_cache[code] = entry
        return entry

    def _relevant_for(self, frame):
        local_candidates, global_candidates, entry_globals = self._get_cache_entry(frame)

        local_relevant = [
            tracker for tracker in local_candidates
            if self._tracker_codes.get(tracker) is frame.f_code
        ]

        global_relevant = []
        if global_candidates and frame.f_globals is entry_globals:
            global_relevant = [
                tracker for tracker in global_candidates
                if self._tracker_globals.get(tracker) is frame.f_globals
            ]

        return local_relevant, global_relevant

    def _process_frame(self, frame, frame_state):
        local_relevant, global_relevant = self._relevant_for(frame)

        for tracker in local_relevant:
            domain, _ = self._resolver.resolve(frame, tracker.varName)
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

    def _trace_calls(self, frame, event, arg):
        if event != "call":
            return None

        local_relevant, global_relevant = self._relevant_for(frame)
        if not local_relevant and not global_relevant:
            return None

        self._ensure_frame_tracking(frame)
        return frame.f_trace