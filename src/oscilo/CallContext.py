class CallContextManager:
    def __init__(self):
        self._next_call_id = 1
        self._contexts = {}
        self._cleanup_traces = {}

    def next_id(self):
        # ID 공간을 공유해서, 합성된 identity(예: closure cell에 대한 ENCLOSING
        # var_id)가 frame 기반 call_id 값과 절대 충돌하지 않도록 한다.
        new_id = self._next_call_id
        self._next_call_id += 1
        return new_id

    def ensure_context(self, frame):
        if frame is None:
            return None

        existing_context = self._contexts.get(frame)
        if existing_context is not None:
            return existing_context

        missing_frames = []
        current_frame = frame

        # 이미 알려진 logging ancestor를 향해 거슬러 올라간다. 그 ancestor와
        # 요청된 frame 사이에 있는 frame들도 context를 가져야 parent 연결과
        # call depth가 끊기지 않고 이어진다.
        while (
            current_frame is not None
            and current_frame not in self._contexts
        ):
            missing_frames.append(current_frame)
            current_frame = current_frame.f_back

        if current_frame is None:
            # logging ancestor가 존재하지 않는다. context 트리에 무관한 인터프리터나
            # 테스트 러너 frame을 끌어들이는 대신, 요청된 frame이 새로운 logging
            # chain의 root가 된다.
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

            # 요청된 frame은 관련(relevant) frame이므로 그 정상 return tracer가
            # on_return()을 호출한다. 자동으로 생성된 gap frame만 가벼운
            # return 전용 cleanup tracer가 필요하다.
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

        # 이미 local tracer가 있는 frame은 relevant한 frame으로 간주된다. 그
        # 정상 return 경로가 on_return()을 호출해야 하므로 그 tracer를 대체하지 않는다.
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