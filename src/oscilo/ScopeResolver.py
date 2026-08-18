LOCAL = 0
GLOBAL = 1
ENCLOSING = 2
BUILTIN = 3
NOT_FOUND = -1


class ScopeResolver:
    def resolve(self, frame, var_name):
        code = frame.f_code

        # 정적 지역 변수 (co_cellvars = 내부 함수가 캡처한 지역).
        if var_name in code.co_varnames or var_name in code.co_cellvars:
            # 선언된 지역은 미바인딩(삭제·미할당)이어도 바깥 스코프를 가리므로,
            # 통과시키지 말고 NOT_FOUND로 보고한다.
            if var_name in frame.f_locals:
                return LOCAL, frame.f_locals.get(var_name)
            return NOT_FOUND, None

        # 바깥 함수 스코프에서 캡처한 free variable.
        if var_name in code.co_freevars:
            if var_name in frame.f_locals:
                return ENCLOSING, frame.f_locals.get(var_name)
            return NOT_FOUND, None

        if var_name in frame.f_globals:
            return GLOBAL, frame.f_globals.get(var_name)

        if var_name in frame.f_builtins:
            return BUILTIN, frame.f_builtins.get(var_name)

        return NOT_FOUND, None

    def resolve_cell(self, frame, var_name):
        """
        free variable을 뒷받침하는 실제 closure cell 객체를 찾는다.

        settrace 콜백은 frame만 주는데, frame만으로는 어떤 공식 API로도 cell
        객체 자체를 못 얻는다(f_locals·PyFrame_GetVar 등은 역참조된 값만 준다).
        cell은 함수의 __closure__로만 접근되므로, 호출자 frame(f_back)에서
        (a) 같은 code 객체를 쓰고 (b) 해당 인덱스 cell이 현재 값과 일치하는
        콜러블을 찾는다.

        보장이 아니라 휴리스틱이다. 호출자 네임스페이스에서 평범한 이름으로
        접근 불가한 콜러블(예: outer()() 즉시 호출, 속성/딕셔너리로 부른 콜백)은
        못 찾고 None을 준다. 호출부는 None을 "소유권 판단 불가"로 보고 fallback한다.
        resolve(항상 답을 주는 전체함수)와 달리 best-effort로 cell|None을 준다.
        """
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

        # 같은 code를 공유하는 여러 closure가 caller 네임스페이스에 있을 수
        # 있으므로(예: outer()를 두 번 호출), cell 내용이 현재 추적 frame의
        # 값과 동일 객체인지로 구분한다.
        try:
            cell_value = cell.cell_contents
        except ValueError:
            # cell이 아직 바인딩 안 됨(드문 타이밍). 일치 확인 불가.
            return None

        if cell_value is not current_value:
            return None

        return cell