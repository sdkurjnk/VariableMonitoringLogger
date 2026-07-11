import sys

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
        self._next_call_id = 1
        self._frame_contexts = {}

    def setBuffer(self, buffer):
        self._bufferRef = buffer

    def register(self, varName, domain=None, value=None, frame=None):
        tracker = VariableTracker(
            varName,
            domain=domain,
            value=value,
            exists=domain in TRACKABLE_DOMAINS,
            frame=frame,
        )
        self._trackers.append(tracker)

        context = self._ensure_call_context(frame)

        # Record the initial value when the variable already exists in scope.
        if domain in TRACKABLE_DOMAINS:
            self._append_buffer_event(
                varName,
                tracker.get_snapshot(),
                "init",
                domain,
                self._get_frame_line(frame),
                self._get_frame_func(frame),
                self._get_context_call_id(context),
                self._get_context_parent_call_id(context),
                self._get_context_call_depth(context),
            )

        # Start global tracing once the first tracker is registered.
        self._start_tracing()

        # Attach line tracing to the registration frame so local changes are captured.
        if frame is not None:
            frame.f_trace = self._trace_lines

        return tracker

    def unregister(self, tracker):
        if tracker in self._trackers:
            self._trackers.remove(tracker)

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
        self._frame_contexts.clear()
        self._next_call_id = 1

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

    def _ensure_call_context(self, frame):
        if frame is None:
            return None

        context = self._frame_contexts.get(frame)
        if context is not None:
            return context

        parent_context = self._frame_contexts.get(frame.f_back)
        parent_call_id = self._get_context_call_id(parent_context)
        parent_depth = self._get_context_call_depth(parent_context)

        context = {
            "call_id": self._next_call_id,
            "parent_call_id": parent_call_id,
            "call_depth": parent_depth + 1 if parent_depth is not None else 1,
        }
        self._next_call_id += 1
        self._frame_contexts[frame] = context

        return context

    def _clear_call_context(self, frame):
        if frame is None:
            return

        self._frame_contexts.pop(frame, None)

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

    def _get_event_data(self, tracker, event_name):
        # Deleted variables no longer have a value, so history stores None.
        if event_name == DELETED_EVENT:
            return None

        return tracker.get_snapshot()

    def _get_logged_domain(self, tracker, event_name, resolved_domain):
        # Preserve the previous scope when deletion makes the variable unresolvable.
        if event_name == DELETED_EVENT and resolved_domain not in TRACKABLE_DOMAINS:
            return tracker.domain

        return resolved_domain

    def _trace_calls(self, frame, event, arg):
        if event != "call":
            return

        self._ensure_call_context(frame)
        return self._trace_lines

    def _trace_lines(self, frame, event, arg):
        if event not in ("line", "return"):
            return self._trace_lines
        context = self._ensure_call_context(frame)

        # Iterate over a copy so tracker changes are safe during tracing.
        for tracker in list(self._trackers):
            if self._should_skip_tracker(tracker, frame):
                continue

            domain, _ = self._resolver.resolve(frame, tracker.varName)
            event_name = tracker.check(frame, domain, tracker.varName)

            if event_name in BUFFERED_EVENTS:
                self._append_buffer_event(
                    tracker.varName,
                    self._get_event_data(tracker, event_name),
                    event_name,
                    self._get_logged_domain(tracker, event_name, domain),
                    frame.f_lineno,
                    self._get_frame_func(frame),
                    self._get_context_call_id(context),
                    self._get_context_parent_call_id(context),
                    self._get_context_call_depth(context),
                )

        if event == "return":
            self._clear_call_context(frame)

        return self._trace_lines

    def _should_skip_tracker(self, tracker, frame):
        if tracker.domain == LOCAL or tracker.domain == ENCLOSING and tracker.frame is not None:
            return frame is not tracker.frame

        if tracker.domain == GLOBAL and tracker.frame is not None:
            return frame.f_globals is not tracker.frame.f_globals

        return False