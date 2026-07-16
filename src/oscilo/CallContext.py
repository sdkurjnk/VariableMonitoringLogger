class CallContextManager:
    def __init__(self):
        self._next_call_id = 1
        self._contexts = {}
        self._cleanup_traces = {}

    def ensure_context(self, frame):
        if frame is None:
            return None

        existing_context = self._contexts.get(frame)
        if existing_context is not None:
            return existing_context

        missing_frames = []
        current_frame = frame

        # Walk toward an already known logging ancestor. Frames between that
        # ancestor and the requested frame must also receive contexts so parent
        # links and call depth remain continuous.
        while (
            current_frame is not None
            and current_frame not in self._contexts
        ):
            missing_frames.append(current_frame)
            current_frame = current_frame.f_back

        if current_frame is None:
            # No logging ancestor exists. The requested frame becomes the root of
            # a new logging chain rather than pulling unrelated interpreter and
            # test-runner frames into the context tree.
            return self._create_context(
                frame,
                parent_context=None,
            )

        parent_context = self._contexts[current_frame]

        for missing_frame in reversed(missing_frames):
            context = self._create_context(
                missing_frame,
                parent_context,
            )

            # The requested frame is relevant and its normal return tracer will
            # call on_return(). Only automatically created gap frames need the
            # lightweight return-only cleanup tracer.
            if missing_frame is not frame:
                self._attach_return_cleanup(missing_frame)

            parent_context = context

        return self._contexts[frame]

    def on_return(self, frame):
        if frame is None:
            return

        self._contexts.pop(frame, None)
        self._restore_cleanup_trace(frame)

    def clear(self):
        for frame in list(self._cleanup_traces):
            self._restore_cleanup_trace(frame)

        self._contexts.clear()
        self._next_call_id = 1

    def _create_context(self, frame, parent_context):
        parent_call_id = None
        call_depth = 1

        if parent_context is not None:
            parent_call_id = parent_context["call_id"]
            call_depth = parent_context["call_depth"] + 1

        context = {
            "call_id": self._next_call_id,
            "parent_call_id": parent_call_id,
            "call_depth": call_depth,
        }

        self._next_call_id += 1
        self._contexts[frame] = context

        return context

    def _attach_return_cleanup(self, frame):
        if frame in self._cleanup_traces:
            return

        # A frame with an existing local tracer is expected to be relevant. Its
        # normal return path must call on_return(), so do not replace that tracer.
        previous_trace = getattr(frame, "f_trace", None)
        if previous_trace is not None:
            return

        previous_trace_lines = getattr(
            frame,
            "f_trace_lines",
            True,
        )

        def cleanup_trace(current_frame, event, arg):
            if event == "return":
                self.on_return(current_frame)
                return None

            return cleanup_trace

        frame.f_trace = cleanup_trace
        frame.f_trace_lines = False

        self._cleanup_traces[frame] = {
            "installed_trace": cleanup_trace,
            "previous_trace": previous_trace,
            "previous_trace_lines": previous_trace_lines,
        }

    def _restore_cleanup_trace(self, frame):
        cleanup_state = self._cleanup_traces.pop(
            frame,
            None,
        )

        if cleanup_state is None:
            return

        installed_trace = cleanup_state["installed_trace"]

        if getattr(frame, "f_trace", None) is installed_trace:
            frame.f_trace = cleanup_state["previous_trace"]

        frame.f_trace_lines = cleanup_state[
            "previous_trace_lines"
        ]